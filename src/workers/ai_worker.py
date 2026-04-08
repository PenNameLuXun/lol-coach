"""AI analysis worker thread — consumes screenshots, produces advice."""

import copy
import datetime
import logging
import threading
import time

from src.analysis_flow import (
    AnalysisPlan,
    AnalysisSnapshot,
    ContextWindow,
    choose_analysis_plan,
    parse_bridge_output,
)
from src.ai_provider import get_provider, BaseProvider
from src.config import Config
from src.event_bus import EventBus
from src.game_plugins.base import AiPayload
from src.rule_engine import RuleEngine, ActiveGameContext, RuleAdvice
from src.web_knowledge import WebKnowledgeManager
from src.workers.shared import (
    SignalBridge,
    QaRuntimeContext,
    log_with_timestamp,
    empty_ai_payload,
)

logger = logging.getLogger("lol_coach.ai_worker")

_RULE_REPEAT_LIMIT = 3

# ── Debug fake data ──────────────────────────────────────────────────────────

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

_DEBUG_FAKE_TFT_DATA = {
    "_game_type": "tft",
    "_source": "overwolf",
    "_overwolf": {
        "me": {"name": "DebugTFTPlayer"},
        "hp": 72,
        "gold": 34,
        "level": 7,
        "alive_players": 5,
        "round": "4-2",
        "mode": "TFT",
        "game_time": "18:20",
        "game_time_seconds": 1100,
        "shop": [
            {"name": "安妮", "cost": 2},
            {"name": "阿木木", "cost": 1},
            {"name": "厄斐琉斯", "cost": 4},
        ],
        "board": [
            {"name": "安妮", "stars": 2},
            {"name": "璐璐", "stars": 2},
            {"name": "厄斐琉斯", "stars": 1},
        ],
        "bench": [
            {"name": "阿木木", "stars": 2},
            {"name": "莫甘娜", "stars": 1},
        ],
        "traits": [
            {"name": "法师", "tier_current": 3},
            {"name": "哨兵", "tier_current": 2},
        ],
    },
}


def _build_debug_fake_context(rule_engine: RuleEngine, plugin_id: str, fake_data: dict):
    plugin = rule_engine.registry.get(plugin_id)
    if plugin is None:
        return None
    raw_data = copy.deepcopy(fake_data)
    state = plugin.extract_state(raw_data, {})
    return ActiveGameContext(plugin=plugin, state=state)


class _ProviderCache:
    """Caches the AI provider instance, only re-creating when config changes."""

    def __init__(self):
        self._provider: BaseProvider | None = None
        self._provider_name: str | None = None
        self._provider_cfg: dict | None = None

    def get(self, config: Config) -> BaseProvider:
        name = config.ai_provider
        cfg = dict(config.ai_config(name))
        if self._provider is None or name != self._provider_name or cfg != self._provider_cfg:
            self._provider = get_provider(name, cfg)
            self._provider_name = name
            self._provider_cfg = cfg
        return self._provider


def _emit_rule_advice(
    *,
    bus: EventBus,
    bridge: SignalBridge,
    context_window: ContextWindow,
    qa_runtime: QaRuntimeContext,
    active_context: ActiveGameContext | None,
    rule_advice: RuleAdvice,
    game_data: str,
    address: str | None,
    metrics: dict,
    source: str,
    debug_timing: bool,
    cycle_started_at: float,
):
    """Shared logic for emitting rule-based advice (rules mode and hybrid mode)."""
    text = rule_advice.text
    reason = f"{source}:{rule_advice.rule_id}"
    if debug_timing:
        cycle_elapsed_ms = (time.perf_counter() - cycle_started_at) * 1000
        logger.info(
            "[timing] reason=%s bridge_ms=0 provider_ms=0 total_ms=%.0f",
            reason, cycle_elapsed_ms,
        )
    bus.put_advice(
        text,
        source=source,
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
            reason=reason,
        )
    )
    qa_runtime.update(
        active_context=active_context,
        rule_advice=rule_advice,
        snapshots=context_window.items(),
    )


def ai_worker(
    bus: EventBus,
    config: Config,
    bridge: SignalBridge,
    stop_event: threading.Event,
    tts_busy_event: threading.Event,
    tray,
    capturer,
    qa_runtime: QaRuntimeContext,
    qa_channel=None,
    debug: bool = False,
    debug_timing: bool = False,
    debug_fake_lol_info: bool = False,
    debug_fake_tft_info: bool = False,
):
    from src.ui.tray import TrayIcon

    rule_engine = RuleEngine(enabled_plugin_ids=config.enabled_plugins, config=config)
    latest_image: bytes | None = None
    retry_after = 0.0
    context_window = ContextWindow(limit=config.decision_memory_size)
    knowledge_manager = WebKnowledgeManager()
    last_emitted_knowledge_bundle = None
    provider_cache = _ProviderCache()
    rule_repeat_count: dict[str, int] = {}

    while not stop_event.is_set():
        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        if retry_after > 0:
            logger.info("[AI worker] waiting %.0fs...", retry_after)
            stop_event.wait(timeout=retry_after)
            retry_after = 0.0
            if stop_event.is_set():
                break

        stop_event.wait(timeout=config.scheduler_interval)
        if stop_event.is_set():
            break

        fresh = bus.peek_latest_capture()
        if fresh is not None:
            latest_image = fresh

        try:
            cycle_started_at = time.perf_counter()
            tray.set_state(TrayIcon.STATE_BUSY)
            previous_plugin_id = rule_engine.bound_plugin_id

            # ── Discover active game context ─────────────────────────────
            active_context = rule_engine.discover_active_context()
            if active_context is None:
                if debug_fake_lol_info:
                    active_context = _build_debug_fake_context(rule_engine, "lol", _DEBUG_FAKE_LOL_DATA)
                    if active_context:
                        logger.info("[debug] using fake LoL live data context")
                elif debug_fake_tft_info:
                    active_context = _build_debug_fake_context(rule_engine, "tft", _DEBUG_FAKE_TFT_DATA)
                    if active_context:
                        logger.info("[debug] using fake TFT live data context")

            active_plugin_id = active_context.plugin.id if active_context else None
            if active_context and active_plugin_id != previous_plugin_id:
                logger.info(
                    "[AI worker] matched plugin %s (%s)",
                    active_context.plugin.display_name, active_plugin_id,
                )

            rule_advice = rule_engine.evaluate_context(active_context) if active_context else None
            qa_runtime.update(
                active_context=active_context,
                rule_advice=rule_advice,
                snapshots=context_window.items(),
            )

            # ── Check game availability ──────────────────────────────────
            live_data = active_context.state.raw_data if active_context else None
            if live_data is None and config.plugin_require_game(active_plugin_id):
                candidate_plugin_id = active_plugin_id or previous_plugin_id
                if candidate_plugin_id == "dialogue" and rule_engine.had_seen_activity():
                    logger.info("[AI worker] waiting for dialogue input")
                elif rule_engine.had_seen_activity():
                    logger.info("[AI worker] game over, skipping analysis")
                else:
                    logger.info("[AI worker] not in game, skipping analysis")
                capturer.pause()
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue
            capturer.resume()

            # ── Web knowledge collection ─────────────────────────────────
            if active_context is not None and config.web_knowledge_enabled:
                try:
                    knowledge_bundle = knowledge_manager.collect_for_context(
                        active_context, config, debug_timing=debug_timing,
                    )
                    if knowledge_bundle is not None and knowledge_bundle is not last_emitted_knowledge_bundle:
                        bridge.knowledge_ready.emit({
                            "plugin": active_context.plugin,
                            "state": active_context.state,
                            "bundle": knowledge_bundle,
                        })
                        last_emitted_knowledge_bundle = knowledge_bundle
                except Exception as exc:
                    logger.error("[WebKnowledge error] %s", exc)

            # ── Build AI payload ─────────────────────────────────────────
            payload = (
                active_context.plugin.build_ai_payload(
                    active_context.state,
                    detail=config.plugin_detail(active_plugin_id),
                    address_by=config.plugin_address_by(active_plugin_id),
                )
                if active_context
                else empty_ai_payload()
            )
            game_data = payload.game_summary
            metrics = payload.metrics
            address = payload.address

            if config.tts_playback_mode in {"wait", "fit_wait"} and tts_busy_event.is_set():
                tray.set_state(TrayIcon.STATE_RUNNING)
                logger.info("[AI worker] waiting for TTS before next cycle")
                continue

            # ── Rules-only mode ──────────────────────────────────────────
            decision_mode = config.decision_mode
            hybrid_threshold = int(config.rules_config.get("hybrid_priority_threshold", 85))

            if decision_mode == "rules":
                if not rule_advice:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    logger.info("[Rules] no matching rule, skipping cycle")
                    continue
                rid = rule_advice.rule_id
                rule_repeat_count[rid] = rule_repeat_count.get(rid, 0) + 1
                for key in list(rule_repeat_count):
                    if key != rid:
                        rule_repeat_count[key] = 0
                if rule_repeat_count[rid] > _RULE_REPEAT_LIMIT:
                    tray.set_state(TrayIcon.STATE_RUNNING)
                    logger.info("[Rules] suppressed repeat (%dx): %s", rule_repeat_count[rid], rid)
                    continue
                _emit_rule_advice(
                    bus=bus, bridge=bridge, context_window=context_window,
                    qa_runtime=qa_runtime, active_context=active_context,
                    rule_advice=rule_advice, game_data=game_data, address=address,
                    metrics=metrics, source="rule", debug_timing=debug_timing,
                    cycle_started_at=cycle_started_at,
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            # ── Hybrid mode: high-priority rules bypass AI ───────────────
            if decision_mode == "hybrid" and rule_advice and rule_advice.priority >= hybrid_threshold:
                _emit_rule_advice(
                    bus=bus, bridge=bridge, context_window=context_window,
                    qa_runtime=qa_runtime, active_context=active_context,
                    rule_advice=rule_advice, game_data=game_data, address=address,
                    metrics=metrics, source="hybrid_rule", debug_timing=debug_timing,
                    cycle_started_at=cycle_started_at,
                )
                tray.set_state(TrayIcon.STATE_RUNNING)
                continue

            # ── AI analysis mode ─────────────────────────────────────────
            provider = provider_cache.get(config)
            allow_visual = bool(active_context and active_context.plugin.wants_visual_context(active_context.state))
            img = latest_image if config.capture_use_screenshot and allow_visual else None

            plan: AnalysisPlan = choose_analysis_plan(
                current_metrics=metrics,
                previous_snapshot=context_window.latest(),
                has_image=img is not None,
                now=datetime.datetime.now(),
                trigger_cfg=config.plugin_analysis_trigger(active_plugin_id),
            )
            if not plan.should_analyze:
                tray.set_state(TrayIcon.STATE_RUNNING)
                logger.info("[AI worker] skipped stable cycle (%s)", plan.reason)
                continue

            # Vision bridge
            bridge_facts: dict[str, str] | None = None
            bridge_elapsed_ms = 0.0
            vb = config.vision_bridge
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
                        img = None
                        logger.info("[Vision bridge] %s → ok", vb["provider"])
                except Exception as e:
                    img = None
                    logger.error("[Vision bridge error] %s", e)
            elif context_window.latest() is not None:
                bridge_facts = context_window.latest().bridge_facts
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
                import os
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
                logger.info(
                    "[timing] reason=%s bridge_ms=%.0f provider_ms=%.0f total_ms=%.0f",
                    plan.reason, bridge_elapsed_ms, provider_elapsed_ms, cycle_elapsed_ms,
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
            import re as _re
            msg = str(e)
            logger.error("[AI worker error] %s", msg)
            tray.set_state(TrayIcon.STATE_RUNNING)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                match = _re.search(r"retryDelay.*?(\d+)s", msg)
                retry_after = int(match.group(1)) + 5 if match else 60
            elif "Connection error" in msg or "connect" in msg.lower():
                retry_after = 15
                logger.warning("[AI worker] connection failed, retrying in 15s — is Ollama running? (`ollama serve`)")
