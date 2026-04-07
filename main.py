"""LOL Coach — entry point.

Wires all components together:
- Config → loaded from config.yaml (copied from config.example.yaml on first run)
- EventBus → shared queues between threads
- Capturer → screenshot daemon thread
- AI worker thread → consumes capture_queue, produces advice
- TTS worker thread → consumes advice_queue
- History → SQLite, accessed from main thread via signals
- UI → MainWindow (hidden), TrayIcon, OverlayWindow
"""

import argparse
import copy
import datetime
import queue
import shutil
import signal
import sys
import threading
import os
import random
import subprocess
import time

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from src.analysis_flow import (
    AnalysisSnapshot,
    AnalysisPlan,
    ContextWindow,
    choose_analysis_plan,
    parse_bridge_output,
)
from src.config import Config
from src.event_bus import EventBus
from src.history import History
from src.capturer import Capturer
from src.ai_provider import get_provider
from src.tts_engine import get_tts_engine
from src.game_plugins.base import AiPayload
from src.rule_engine import RuleEngine
from src.rule_engine import ActiveGameContext
from src.qa_channel import QaChannel, build_qa_prompt, run_qa_web_search
from src.web_knowledge import WebKnowledgeManager
from src.ui.knowledge_window import KnowledgeWindow
from src.ui.main_window import MainWindow
from src.ui.tray import TrayIcon
from src.ui.overlay import OverlayWindow


_DEBUG_FAKE_LOL_DATA = {
    "activePlayer": {
        "summonerName": "DebugPlayer",
        "level": 12,
        "currentGold": 1350,
        "championStats": {
            "currentHealth": 800,
            "maxHealth": 1200,
            "resourceValue": 300,
            "resourceMax": 600,
        },
        "fullRunes": {"keystone": {"displayName": "Conqueror"}},
    },
    "allPlayers": [
        {
            "summonerName": "DebugPlayer",
            "championName": "Jinx",
            "team": "ORDER",
            "items": [
                {"displayName": "Kraken Slayer"},
                {"displayName": "Runaan's Hurricane"},
            ],
            "scores": {"kills": 3, "deaths": 1, "assists": 5, "creepScore": 120, "wardScore": 22},
            "summonerSpells": {
                "summonerSpellOne": {"displayName": "Flash"},
                "summonerSpellTwo": {"displayName": "Heal"},
            },
            "isDead": False,
            "respawnTimer": 0.0,
        },
        {
            "summonerName": "Ally1",
            "championName": "Thresh",
            "team": "ORDER",
            "scores": {"kills": 1, "deaths": 2, "assists": 8, "creepScore": 20, "wardScore": 40},
            "isDead": False,
            "respawnTimer": 0.0,
            "items": [],
        },
        {
            "summonerName": "Ally2",
            "championName": "Orianna",
            "team": "ORDER",
            "scores": {"kills": 2, "deaths": 2, "assists": 4, "creepScore": 138, "wardScore": 11},
            "isDead": False,
            "respawnTimer": 0.0,
            "items": [],
        },
        {
            "summonerName": "Enemy1",
            "championName": "Zed",
            "team": "CHAOS",
            "scores": {"kills": 5, "deaths": 1, "assists": 2, "creepScore": 150, "wardScore": 15},
            "isDead": True,
            "respawnTimer": 12.0,
            "items": [],
        },
        {
            "summonerName": "Enemy2",
            "championName": "Nautilus",
            "team": "CHAOS",
            "scores": {"kills": 0, "deaths": 3, "assists": 6, "creepScore": 28, "wardScore": 36},
            "isDead": False,
            "respawnTimer": 0.0,
            "items": [],
        },
    ],
    "gameData": {"gameTime": 725, "gameMode": "CLASSIC"},
    "events": {
        "Events": [
            {"EventName": "DragonKill", "DragonType": "Fire"},
            {"EventName": "ChampionKill"},
        ]
    },
}


# ── Qt Signal bridge from worker threads to UI ────────────────────────────────

class SignalBridge(QObject):
    advice_ready = pyqtSignal(str)
    knowledge_ready = pyqtSignal(object)


class QaRuntimeContext:
    def __init__(self):
        self._lock = threading.Lock()
        self._active_context: ActiveGameContext | None = None
        self._rule_advice = None
        self._snapshots: list[AnalysisSnapshot] = []

    def update(
        self,
        *,
        active_context: ActiveGameContext | None,
        rule_advice,
        snapshots: list[AnalysisSnapshot],
    ) -> None:
        with self._lock:
            self._active_context = active_context
            self._rule_advice = rule_advice
            self._snapshots = list(snapshots)

    def snapshot(self) -> tuple[ActiveGameContext | None, object, list[AnalysisSnapshot]]:
        with self._lock:
            return self._active_context, self._rule_advice, list(self._snapshots)


def _log_with_timestamp(tag: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{tag}] {message}")


def _empty_ai_payload() -> AiPayload:
    return AiPayload(
        game_summary="",
        address=None,
        metrics={
            "game_time": "?",
            "gold": "?",
            "hp_pct": "?",
            "mana_pct": "?",
            "level": "?",
            "kda": "?",
            "cs": "?",
            "event_signature": "none",
        },
    )


def _resolve_tts_rate_override(config: Config, backend: str, engine, text: str) -> int | None:
    mode = config.tts_playback_mode
    if mode not in {"fit_wait", "fit_continue"}:
        return None
    if backend != "windows" or not engine.supports_dynamic_rate():
        return None
    target_seconds = max(1.0, config.scheduler_interval * 0.9)
    base_rate = int(config.tts_config("windows").get("rate", 0))
    text_len = max(1, len(text.strip()))

    # Heuristic fit for short Chinese coaching lines on SAPI.
    estimated_chars_per_sec = max(1.6, 3.0 + base_rate * 0.18)
    desired_chars_per_sec = text_len / max(0.6, target_seconds - 0.4)
    desired_rate = round((desired_chars_per_sec - 3.0) / 0.18)
    # fit_* only speeds up when needed; it should never slow below the configured base rate.
    return max(-10, min(10, max(base_rate, desired_rate)))


def _is_overwolf_running() -> bool:
    try:
        result = shutil.which("powershell")
        shell = result or "powershell"
        cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('Overwolf.exe','OverwolfBrowser.exe') } | "
            "Select-Object -First 1 | ConvertTo-Json -Depth 2"
        )
        proc = os.popen(f'{shell} -NoProfile -Command "{cmd}"')
        output = proc.read().strip()
        proc.close()
        return bool(output and output != "null")
    except Exception:
        return False


def _try_start_overwolf(config: Config) -> None:
    if not config.overwolf_required:
        return
    if _is_overwolf_running():
        return

    method = str(config.get("launcher.overwolf.method", "auto")).strip().lower()
    path = str(config.get("launcher.overwolf.path", "")).strip()
    protocol = str(config.get("launcher.overwolf.protocol", "overwolf://")).strip() or "overwolf://"

    try:
        if method == "path" and path:
            subprocess.Popen([path], cwd=os.getcwd())
            print(f"[startup] Overwolf required, started via path: {path}")
            return
        if method == "protocol":
            os.startfile(protocol)
            print(f"[startup] Overwolf required, started via protocol: {protocol}")
            return

        auto_paths = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Overwolf", "OverwolfLauncher.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Overwolf", "OverwolfLauncher.exe"),
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "Overwolf", "OverwolfLauncher.exe"),
        ]
        for candidate in auto_paths:
            if candidate and os.path.exists(candidate):
                subprocess.Popen([candidate], cwd=os.getcwd())
                print(f"[startup] Overwolf required, started via auto path: {candidate}")
                return

        os.startfile(protocol)
        print(f"[startup] Overwolf required, started via fallback protocol: {protocol}")
    except Exception as exc:
        print(f"[startup] failed to start Overwolf: {exc}")


def _qa_hotkey_gate_open(config: Config) -> bool:
    if config.qa_settings.get("source", "file") != "microphone":
        return True
    if config.qa_microphone_trigger_mode != "hold":
        return True
    hotkey = config.qa_microphone_hotkey
    if not hotkey:
        return False
    try:
        import keyboard
        return bool(keyboard.is_pressed(hotkey))
    except Exception:
        return False


def _build_debug_fake_lol_context(rule_engine):
    plugin = rule_engine.registry.get("lol")
    if plugin is None:
        return None
    raw_data = copy.deepcopy(_DEBUG_FAKE_LOL_DATA)
    state = plugin.extract_state(raw_data, {})
    return ActiveGameContext(plugin=plugin, state=state)


# ── Worker threads ─────────────────────────────────────────────────────────────

def ai_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tray: TrayIcon,
    capturer,
    qa_runtime: QaRuntimeContext,
    qa_channel: QaChannel | None = None,
    debug: bool = False,
    debug_timing: bool = False,
    debug_fake_lol_info: bool = False,
):
    rule_engine = RuleEngine(enabled_plugin_ids=config.enabled_plugins, config=config)
    latest_image: bytes | None = None
    retry_after = 0.0
    context_window = ContextWindow(limit=config.decision_memory_size)
    knowledge_manager = WebKnowledgeManager()
    last_emitted_knowledge_bundle = None
    _rule_repeat_count: dict[str, int] = {}
    _RULE_REPEAT_LIMIT = 3

    while not stop_event.is_set():
        # Always drain capture queue to keep latest screenshot buffered
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        # Honour backoff
        if retry_after > 0:
            print(f"[AI worker] waiting {retry_after:.0f}s...")
            stop_event.wait(timeout=retry_after)
            retry_after = 0.0
            if stop_event.is_set():
                break

        # Wait for next AI analysis slot
        stop_event.wait(timeout=config.scheduler_interval)
        if stop_event.is_set():
            break

        # Drain again after sleeping
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        try:
            cycle_started_at = time.perf_counter()
            tray.set_state(TrayIcon.STATE_BUSY)
            previous_plugin_id = rule_engine.bound_plugin_id
            active_context = rule_engine.discover_active_context()
            if active_context is None and debug_fake_lol_info:
                active_context = _build_debug_fake_lol_context(rule_engine)
                if active_context is not None:
                    print("[debug] using fake LoL live data context")
            active_plugin_id = active_context.plugin.id if active_context else None
            if active_context and active_plugin_id != previous_plugin_id:
                print(
                    "[AI worker] matched plugin "
                    f"{active_context.plugin.display_name} ({active_plugin_id})"
                )
            rule_advice = rule_engine.evaluate_context(active_context) if active_context else None
            qa_runtime.update(
                active_context=active_context,
                rule_advice=rule_advice,
                snapshots=context_window.items(),
            )

            live_data = active_context.state.raw_data if active_context else None
            if live_data is None and config.plugin_require_game(active_plugin_id):
                candidate_plugin_id = active_plugin_id or previous_plugin_id
                if candidate_plugin_id == "dialogue" and rule_engine.had_seen_activity():
                    print("[AI worker] waiting for dialogue input")
                elif rule_engine.had_seen_activity():
                    print("[AI worker] game over, skipping analysis")
                else:
                    print("[AI worker] not in game, skipping analysis")
                capturer.pause()
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue
            capturer.resume()
            if active_context is not None and config.web_knowledge_enabled:
                try:
                    knowledge_bundle = knowledge_manager.collect_for_context(
                        active_context,
                        config,
                        debug_timing=debug_timing,
                    )
                    if knowledge_bundle is not None and knowledge_bundle is not last_emitted_knowledge_bundle:
                        bridge.knowledge_ready.emit(
                            {
                                "plugin": active_context.plugin,
                                "state": active_context.state,
                                "bundle": knowledge_bundle,
                            }
                        )
                        last_emitted_knowledge_bundle = knowledge_bundle
                except Exception as exc:
                    print(f"[WebKnowledge error] {exc}")

            payload = (
                active_context.plugin.build_ai_payload(
                    active_context.state,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                if active_context
                else _empty_ai_payload()
            )
            game_data = payload.game_summary
            metrics = payload.metrics
            address = payload.address
            if config.tts_playback_mode in {"wait", "fit_wait"} and tts_busy_event.is_set():
                tray.set_state(TrayIcon.STATE_RUNNING)
                print("[AI worker] waiting for TTS before next cycle")
                continue

            allow_visual = bool(active_context and active_context.plugin.wants_visual_context(active_context.state))
            img = latest_image if config.capture_use_screenshot and allow_visual else None
            bridge_facts: dict[str, str] | None = None
            previous_snapshot = context_window.latest()
            decision_mode = config.decision_mode
            hybrid_threshold = int(config.rules_config.get("hybrid_priority_threshold", 85))
            if decision_mode == "rules":
                if not rule_advice:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    print("[Rules] no matching rule, skipping cycle")
                    continue
                rid = rule_advice.rule_id
                _rule_repeat_count[rid] = _rule_repeat_count.get(rid, 0) + 1
                # reset counts for rules that are no longer firing
                for key in list(_rule_repeat_count):
                    if key != rid:
                        _rule_repeat_count[key] = 0
                if _rule_repeat_count[rid] > _RULE_REPEAT_LIMIT:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    print(f"[Rules] suppressed repeat ({_rule_repeat_count[rid]}x): {rid}")
                    continue
                text = rule_advice.text
                if debug_timing:
                    cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
                    print(
                        "[timing] "
                        f"reason=rule:{rule_advice.rule_id} "
                        "bridge_ms=0 "
                        "provider_ms=0 "
                        f"total_ms={cycle_elapsed_ms:.0f}"
                    )
                bus.put_advice(
                    text,
                    source="rule",
                    dedupe_key=f"rule:{rule_advice.rule_id}",
                    interruptible=False,
                )
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                context_window.add(
                    AnalysisSnapshot(
                        timestamp=datetime.datetime.now(),
                        game_summary=game_data,
                        address=address,
                        metrics=metrics,
                        bridge_facts={},
                        advice=text,
                        reason=f"rule:{rule_advice.rule_id}",
                    )
                )
                qa_runtime.update(
                    active_context=active_context,
                    rule_advice=rule_advice,
                    snapshots=context_window.items(),
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            if decision_mode == "hybrid" and rule_advice and rule_advice.priority >= hybrid_threshold:
                text = rule_advice.text
                if debug_timing:
                    cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
                    print(
                        "[timing] "
                        f"reason=hybrid_rule:{rule_advice.rule_id} "
                        "bridge_ms=0 "
                        "provider_ms=0 "
                        f"total_ms={cycle_elapsed_ms:.0f}"
                    )
                bus.put_advice(
                    text,
                    source="hybrid_rule",
                    dedupe_key=f"rule:{rule_advice.rule_id}",
                    interruptible=False,
                )
                bus.emit_advice(text)
                bridge.advice_ready.emit(text)
                context_window.add(
                    AnalysisSnapshot(
                        timestamp=datetime.datetime.now(),
                        game_summary=game_data,
                        address=address,
                        metrics=metrics,
                        bridge_facts={},
                        advice=text,
                        reason=f"hybrid_rule:{rule_advice.rule_id}",
                    )
                )
                qa_runtime.update(
                    active_context=active_context,
                    rule_advice=rule_advice,
                    snapshots=context_window.items(),
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
            plan: AnalysisPlan = choose_analysis_plan(
                current_metrics=metrics,
                previous_snapshot=previous_snapshot,
                has_image=img is not None,
                now=datetime.datetime.now(),
                trigger_cfg=config.plugin_analysis_trigger(active_plugin_id),
            )
            if not plan.should_analyze:
                tray.set_state(TrayIcon.STATE_RUNNING)
                print(f"[AI worker] skipped stable cycle ({plan.reason})")
                continue

            # Vision bridge: uses raw screenshot regardless of main provider's use_screenshot.
            # Converts image to text description, then main provider receives text only.
            vb = config.vision_bridge
            bridge_elapsed_ms = 0.0
            if vb and latest_image is not None and plan.run_bridge:
                try:
                    vb_provider_name, vb_provider_cfg = config.vision_bridge_provider_config()
                    vb_provider = get_provider(vb_provider_name, vb_provider_cfg)
                    vb_prompt = (
                        vb.get("prompt")
                        or (
                            active_context.plugin.build_vision_prompt(
                                active_context.state,
                                detail=config.plugin_detail(active_plugin_id),
                            )
                            if active_context
                            else ""
                        )
                    )
                    if vb_prompt.strip():
                        bridge_started_at = time.perf_counter()
                        description = vb_provider.analyze(latest_image, vb_prompt)
                        bridge_elapsed_ms = (time.perf_counter() - bridge_started_at) * 1000
                        bridge_facts = parse_bridge_output(description)
                        img = None  # main provider always receives text only when bridge is active
                        print(f"[Vision bridge] {vb['provider']} → ok")
                except Exception as e:
                    img = None
                    print(f"[Vision bridge error] {e}")
            elif previous_snapshot is not None:
                bridge_facts = previous_snapshot.bridge_facts
            if vb:
                img = None

            prompt = (
                active_context.plugin.build_decision_prompt(
                    active_context.state,
                    system_prompt=config.plugin_system_prompt(active_plugin_id),
                    bridge_facts=bridge_facts,
                    snapshots=context_window.items(),
                    rule_hint=rule_advice.hint if rule_advice else None,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                if active_context
                else ""
            )

            if debug:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                os.makedirs("debug_captures", exist_ok=True)
                with open(f"debug_captures/{ts}_prompt.txt", "w", encoding="utf-8") as _f:
                    _f.write(f"[provider] {config.ai_provider}\n")
                    _f.write(f"[model] {config.ai_config(config.ai_provider).get('model', '')}\n")
                    _f.write(f"[trigger_reason] {plan.reason}\n")
                    _f.write(f"[screenshot] {'yes' if img else 'no'}\n")
                    if vb:
                        _f.write(f"[vision_bridge] {vb['provider']} → {bridge_facts.get('confidence', 'failed') if bridge_facts else 'failed'}\n")
                        _f.write(f"[vision_bridge_ms] {bridge_elapsed_ms:.0f}\n")
                    _f.write("\n")
                    _f.write(prompt)
            provider_started_at = time.perf_counter()
            text = provider.analyze(img, prompt)
            provider_elapsed_ms = (time.perf_counter() - provider_started_at) * 1000
            cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
            if debug_timing:
                print(
                    "[timing] "
                    f"reason={plan.reason} "
                    f"bridge_ms={bridge_elapsed_ms:.0f} "
                    f"provider_ms={provider_elapsed_ms:.0f} "
                    f"total_ms={cycle_elapsed_ms:.0f}"
                )
            bus.put_advice(
                text,
                source="qa",
                expires_after_seconds=45.0,
                interruptible=False,
            )
            bus.emit_advice(text)
            bridge.advice_ready.emit(text)
            context_window.add(
                AnalysisSnapshot(
                    timestamp=datetime.datetime.now(),
                    game_summary=game_data,
                    address=address,
                    metrics=metrics,
                    bridge_facts=bridge_facts or {},
                    advice=text,
                    reason=plan.reason,
                )
            )
            qa_runtime.update(
                active_context=active_context,
                rule_advice=rule_advice,
                snapshots=context_window.items(),
            )
            tray.set_state(TrayIcon.STATE_RUNNING)
        except Exception as e:
            msg = str(e)
            print(f"[AI worker error] {msg}")
            tray.set_state(TrayIcon.STATE_RUNNING)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                import re
                match = re.search(r"retryDelay.*?(\d+)s", msg)
                retry_after = int(match.group(1)) + 5 if match else 60
            elif "Connection error" in msg or "connect" in msg.lower():
                retry_after = 15
                print("[AI worker] connection failed, retrying in 15s — is Ollama running? (`ollama serve`)")


def qa_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tts_interrupt_event: threading.Event,
    qa_channel: QaChannel,
    qa_runtime: QaRuntimeContext,
    debug_timing: bool = False,
):
    mic_paused_for_tts = False
    poll_interval_seconds = 0.2

    while not stop_event.is_set():
        stop_event.wait(timeout=poll_interval_seconds)
        if stop_event.is_set():
            break
        if not qa_channel.is_enabled(config):
            continue

        tts_busy_now = tts_busy_event.is_set()
        if tts_busy_now and not config.qa_wakeword_enabled:
            if not mic_paused_for_tts:
                qa_channel.pause_microphone()
                mic_paused_for_tts = True
            qa_channel.flush_transcript()
            continue

        if not _qa_hotkey_gate_open(config):
            if mic_paused_for_tts:
                qa_channel.resume_microphone()
                mic_paused_for_tts = False
            qa_channel.flush_transcript()
            continue

        if mic_paused_for_tts:
            qa_channel.resume_microphone()
            mic_paused_for_tts = False

        question = qa_channel.poll_question()
        if question is None:
            continue

        if question.wakeword_triggered and config.qa_wakeword_enabled:
            _log_with_timestamp("QA", "wakeword matched, requesting interrupt")
            tts_interrupt_event.set()
            ack_text = random.choice(config.qa_wakeword_ack_texts)
            bus.put_advice(
                ack_text,
                source="qa_ack",
                expires_after_seconds=3.0,
                interruptible=False,
            )
            bus.emit_advice(ack_text)
            bridge.advice_ready.emit(ack_text)
            if question.wakeword_only:
                continue

        active_context, rule_advice, snapshots = qa_runtime.snapshot()
        active_plugin_id = active_context.plugin.id if active_context else None
        cycle_started_at = time.perf_counter()
        _log_with_timestamp("QA", f"question={question.text!r} source={question.source_kind}")

        try:
            provider = get_provider(config.ai_provider, config.ai_config(config.ai_provider))
            search_started_at = time.perf_counter()
            web_search_docs = run_qa_web_search(
                question=question,
                config=config,
                active_context=active_context,
            )
            search_elapsed_ms = (time.perf_counter() - search_started_at) * 1000
            _log_with_timestamp(
                "QA search",
                f"enabled={config.qa_web_search_enabled} "
                f"mode={config.qa_web_search_mode} "
                f"engine={config.qa_web_search_engine} "
                f"docs={len(web_search_docs)} "
                f"elapsed_ms={search_elapsed_ms:.0f}",
            )
            for i, doc in enumerate(web_search_docs, 1):
                _log_with_timestamp(
                    "QA search result",
                    f"[{i}] site={doc.domain} title={doc.title!r} url={doc.url}",
                )

            prompt = build_qa_prompt(
                question=question,
                system_prompt=config.qa_system_prompt,
                active_context=active_context,
                snapshots=snapshots,
                rule_advice=rule_advice,
                web_search_docs=web_search_docs,
                detail=config.plugin_detail(active_plugin_id),
                address_by=config.plugin_address_by(active_plugin_id),
            )
            provider_started_at = time.perf_counter()
            text = provider.analyze(None, prompt)
            provider_elapsed_ms = (time.perf_counter() - provider_started_at) * 1000
            total_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
            _log_with_timestamp(
                "QA timing",
                f"provider={config.ai_provider} "
                f"provider_ms={provider_elapsed_ms:.0f} "
                f"total_ms={total_elapsed_ms:.0f}",
            )
            if debug_timing:
                print(
                    "[timing] "
                    "reason=qa "
                    "bridge_ms=0 "
                    f"provider_ms={provider_elapsed_ms:.0f} "
                    f"total_ms={total_elapsed_ms:.0f}"
                )
            bus.put_advice(
                text,
                source="qa",
                expires_after_seconds=45.0,
                interruptible=False,
            )
            bus.emit_advice(text)
            bridge.advice_ready.emit(text)
        except Exception as exc:
            print(f"[QA worker error] {exc}")


def tts_worker(
    bus: EventBus,
    config: Config,
    stop_event: threading.Event,
    busy_event: threading.Event,
    interrupt_event: threading.Event,
):
    current_engine = None
    current_backend = None
    current_cfg = None

    def get_engine():
        nonlocal current_engine, current_backend, current_cfg
        backend = config.tts_backend
        cfg = dict(config.tts_config(backend))
        if current_engine is None or backend != current_backend or cfg != current_cfg:
            current_engine = get_tts_engine(backend, cfg)
            current_backend = backend
            current_cfg = cfg
        return current_engine

    active_event = None
    active_started_at = 0.0

    def _should_interrupt_current(current_event, incoming_event, playback_mode: str, supports_interrupt: bool) -> bool:
        if not supports_interrupt or current_event is None or incoming_event is None:
            return False
        if getattr(incoming_event, "source", "") == "qa" and getattr(current_event, "source", "") != "qa":
            return True
        if not bool(getattr(current_event, "interruptible", True)):
            return False
        return playback_mode == "interrupt" and bool(getattr(incoming_event, "interruptible", True))

    while not stop_event.is_set():
        try:
            engine = get_engine()
            playback_mode = config.tts_playback_mode
            supports_interrupt = engine.supports_interrupt()
            if supports_interrupt:
                if active_event is not None:
                    if engine.is_busy():
                        busy_event.set()
                        if interrupt_event.is_set():
                            _log_with_timestamp("TTS", "interrupt requested by wakeword")
                            interrupt_event.clear()
                            engine.interrupt()
                            while engine.is_busy() and not stop_event.wait(timeout=0.02):
                                pass
                            elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                            _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f} interrupted=true")
                            active_event = None
                            busy_event.clear()
                            continue
                        try:
                            next_event = bus.get_latest_advice_event(timeout=0.1)
                        except queue.Empty:
                            continue
                        if not _should_interrupt_current(active_event, next_event, playback_mode, supports_interrupt):
                            bus.put_advice(
                                next_event.text,
                                source=next_event.source,
                                priority=next_event.priority,
                                expires_after_seconds=next_event.expires_after_seconds,
                                dedupe_key=next_event.dedupe_key,
                                interruptible=next_event.interruptible,
                            )
                            continue
                        _log_with_timestamp("TTS", f"interrupt len={len(next_event.text)} text={next_event.text[:60]}")
                        engine.interrupt()
                        while engine.is_busy() and not stop_event.wait(timeout=0.02):
                            pass
                        elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                        _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f} interrupted=true")
                        active_event = next_event
                        active_started_at = time.perf_counter()
                        _log_with_timestamp("TTS", f"start len={len(active_event.text)} text={active_event.text[:60]}")
                        busy_event.set()
                        engine.start(
                            active_event.text,
                            rate_override=_resolve_tts_rate_override(config, current_backend, engine, active_event.text),
                        )
                        continue
                    elapsed_ms = (time.perf_counter() - active_started_at) * 1000
                    _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
                    active_event = None
                    busy_event.clear()
                    continue

                try:
                    active_event = bus.get_latest_advice_event(timeout=1.0)
                except queue.Empty:
                    continue
                active_started_at = time.perf_counter()
                _log_with_timestamp("TTS", f"start len={len(active_event.text)} text={active_event.text[:60]}")
                busy_event.set()
                engine.start(
                    active_event.text,
                    rate_override=_resolve_tts_rate_override(config, current_backend, engine, active_event.text),
                )
                continue

            try:
                text = bus.get_latest_advice(timeout=1.0)
            except queue.Empty:
                continue
            started_at = time.perf_counter()
            _log_with_timestamp("TTS", f"start len={len(text)} text={text[:60]}")
            busy_event.set()
            engine.speak(text, rate_override=_resolve_tts_rate_override(config, current_backend, engine, text))
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _log_with_timestamp("TTS", f"end elapsed_ms={elapsed_ms:.0f}")
        except Exception as e:
            print(f"[TTS worker error] {e}")
            busy_event.clear()
            active_event = None
        finally:
            if active_event is None and not stop_event.is_set():
                busy_event.clear()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOL Coach")
    parser.add_argument("--debug", action="store_true", help="save each screenshot to debug_captures/")
    parser.add_argument("--debug-timing", action="store_true", help="print bridge/provider timing for each analyzed cycle")
    parser.add_argument("--debug-stt", action="store_true", help="print microphone/STT diagnostic logs")
    parser.add_argument("--debug-fake-lol-info", action="store_true", help="pretend a fake LoL match is active for UI/web-knowledge testing")
    args = parser.parse_args()
    os.environ["LOL_COACH_DEBUG_STT"] = "1" if args.debug_stt else "0"

    # Bootstrap config
    if not os.path.exists("config.yaml"):
        shutil.copy("config.example.yaml", "config.yaml")
        print("Created config.yaml from template — please add your API keys.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in tray

    config = Config("config.yaml")
    setattr(config, "_debug_timing", bool(args.debug_timing))
    config._start_watcher()
    _try_start_overwolf(config)

    bus = EventBus()
    history = History("lol_coach.db")

    bridge = SignalBridge()
    stop_event = threading.Event()
    tts_busy_event = threading.Event()
    tts_interrupt_event = threading.Event()
    running = [False]
    qa_channel = QaChannel(config_path="config.yaml")
    qa_runtime = QaRuntimeContext()

    # ── UI ────────────────────────────────────────────────────────────────────
    overlay = None
    knowledge_window = None
    if config.overlay.get("enabled", True):
        overlay = OverlayWindow(fade_after=config.overlay.get("fade_after", 8))
        overlay.move_to(config.overlay.get("x", 100), config.overlay.get("y", 100))

    if config.web_knowledge_enabled:
        knowledge_window = KnowledgeWindow(
            width=config.web_knowledge_window_width,
            height=config.web_knowledge_window_height,
        )
        screens = app.screens()
        if len(screens) > 1:
            geo = screens[1].availableGeometry()
            knowledge_window.move(geo.x(), geo.y())
            knowledge_window.show()
        elif config.web_knowledge_always_visible:
            knowledge_window.show()

    window: MainWindow | None = None
    tray = TrayIcon("assets/icon.png")
    tray.show()

    def ensure_window() -> MainWindow:
        nonlocal window
        if window is None:
            window = MainWindow(config, history)
        return window

    # ── Signals ───────────────────────────────────────────────────────────────
    def on_advice(text: str):
        _log_with_timestamp("UI", f"display len={len(text)} text={text[:60]}")
        if overlay is not None:
            overlay.show_advice(text)
        if window is not None:
            window.on_advice(text)
            session_id = window.history_tab.get_current_session_id()
        else:
            session_id = None
        history.add_advice(text, "timer", session_id=session_id)

    bridge.advice_ready.connect(on_advice)

    def on_knowledge(payload):
        if knowledge_window is None:
            return
        if not isinstance(payload, dict):
            knowledge_window.update_bundle(payload)
            return
        plugin = payload.get("plugin")
        state = payload.get("state")
        bundle = payload.get("bundle")
        if plugin is None or bundle is None:
            knowledge_window.update_bundle(bundle)
            return
        populate = getattr(plugin, "populate_web_knowledge_window", None)
        if callable(populate):
            handled = bool(populate(knowledge_window, bundle, state, config))
            if handled:
                return
        knowledge_window.update_bundle(bundle)

    bridge.knowledge_ready.connect(on_knowledge)

    # ── Capturer ──────────────────────────────────────────────────────────────
    capturer = Capturer(
        capture_queue=bus.capture_queue,
        interval=config.capture_interval,
        hotkey=config.capture_hotkey,
        region=config.capture_region,
        jpeg_quality=config.capture_jpeg_quality,
        monitor=config.capture_monitor,
        debug=args.debug,
    )

    # Register overlay toggle hotkey
    overlay_hotkey = config.overlay.get("toggle_hotkey", "")
    if overlay is not None and overlay_hotkey:
        try:
            import keyboard
            keyboard.add_hotkey(overlay_hotkey, lambda: overlay.setVisible(not overlay.isVisible()))
        except Exception:
            pass

    # ── Start / Pause ─────────────────────────────────────────────────────────
    ai_thread: threading.Thread | None = None
    qa_thread: threading.Thread | None = None
    tts_thread: threading.Thread | None = None

    def start_analysis():
        nonlocal ai_thread, qa_thread, tts_thread
        if running[0]:
            return
        running[0] = True
        stop_event.clear()
        tts_interrupt_event.clear()
        capturer.start()
        ai_thread = threading.Thread(
            target=ai_worker,
            args=(bus, config, bridge, stop_event, tts_busy_event, tray, capturer, qa_runtime, qa_channel),
            kwargs={
                "debug": args.debug,
                "debug_timing": args.debug_timing,
                "debug_fake_lol_info": args.debug_fake_lol_info,
            },
            daemon=True,
        )
        qa_thread = threading.Thread(
            target=qa_worker,
            args=(bus, config, bridge, stop_event, tts_busy_event, tts_interrupt_event, qa_channel, qa_runtime),
            kwargs={"debug_timing": args.debug_timing},
            daemon=True,
        )
        tts_thread = threading.Thread(
            target=tts_worker,
            args=(bus, config, stop_event, tts_busy_event, tts_interrupt_event),
            daemon=True,
        )
        ai_thread.start()
        qa_thread.start()
        tts_thread.start()
        tray.set_state(TrayIcon.STATE_RUNNING)

    def pause_analysis():
        if not running[0]:
            qa_channel.stop()
            return
        running[0] = False
        capturer.stop()
        stop_event.set()
        qa_channel.stop()
        tray.set_state(TrayIcon.STATE_PAUSED)

    def toggle():
        if running[0]:
            pause_analysis()
        else:
            start_analysis()

    def open_window():
        ensure_window().show()
        ensure_window().raise_()
        ensure_window().activateWindow()

    tray.toggle_requested.connect(toggle)
    tray.open_window_requested.connect(open_window)
    tray.quit_requested.connect(lambda: (pause_analysis(), config._stop_watcher(), app.quit()))

    # ── Ctrl+C support ────────────────────────────────────────────────────────
    # PyQt blocks Python signal handling; a periodic QTimer lets the interpreter
    # check for SIGINT so Ctrl+C works from the terminal.
    def _handle_sigint(*_):
        print("\nCtrl+C received, exiting...")
        pause_analysis()
        config._stop_watcher()
        app.quit()

    signal.signal(signal.SIGINT, _handle_sigint)
    if knowledge_window is not None and len(app.screens()) <= 1:
        _knowledge_hotkey_timer = QTimer()
        _knowledge_hotkey_timer.start(120)

        def _update_knowledge_visibility():
            hotkey = config.web_knowledge_hotkey
            always_visible = config.web_knowledge_always_visible
            visible = False
            try:
                import keyboard
                visible = bool(hotkey and keyboard.is_pressed(hotkey))
            except Exception:
                visible = False

            if always_visible:
                if knowledge_window.is_dismissed:
                    if visible:
                        knowledge_window.revive()
                elif not knowledge_window.isVisible():
                    knowledge_window.show()
                return

            if visible and not knowledge_window.isVisible():
                knowledge_window.revive()
            elif not visible and knowledge_window.isVisible():
                knowledge_window.hide()

        _knowledge_hotkey_timer.timeout.connect(_update_knowledge_visibility)

    _sigint_timer = QTimer()
    _sigint_timer.start(500)
    _sigint_timer.timeout.connect(lambda: None)  # wake Python every 500ms

    # Auto-start
    if not config.start_minimized:
        open_window()
    start_analysis()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
