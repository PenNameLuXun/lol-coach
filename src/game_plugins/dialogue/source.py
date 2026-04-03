from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.game_plugins.dialogue.microphone import MicrophoneListener, WindowsMicrophoneListener


class DialogueSource:
    def __init__(
        self,
        config_path: str = "config.yaml",
        plugin_id: str = "dialogue",
        settings_path: tuple[str, ...] | None = None,
    ):
        self._config_path = Path(config_path)
        self._plugin_id = plugin_id
        self._settings_path = settings_path or ("plugin_settings", plugin_id)
        self._config_mtime = 0.0
        self._config: dict = {}
        self._line_index_by_path: dict[str, int] = {}
        self._append_initialized_paths: set[str] = set()
        self._seen_activity = False
        self._microphone_listener = MicrophoneListener(plugin_id=plugin_id)

    def is_available(self) -> bool:
        cfg = self._source_config()
        source_kind = str(cfg.get("source", "file"))
        if source_kind == "file":
            return True
        if source_kind == "microphone":
            transcript_file = Path(str(cfg.get("transcript_file", "dialogue_mic.txt")))
            self._ensure_microphone_listener(cfg)
            return transcript_file.exists() or True
        return False

    def fetch_live_data(self) -> dict | None:
        cfg = self._source_config()
        source_kind = str(cfg.get("source", "file"))
        if source_kind == "microphone":
            self._ensure_microphone_listener(cfg)
            return self._read_append_only_payload(
                path=Path(str(cfg.get("transcript_file", "dialogue_mic.txt"))),
                speaker=str(cfg.get("speaker", "玩家")),
                source_kind="microphone",
            )
        return self._read_text_payload(
            path=Path(str(cfg.get("text_file", "dialogue_input.txt"))),
            speaker=str(cfg.get("speaker", "玩家")),
            clear_after_read=bool(cfg.get("clear_after_read", True)),
            source_kind="file",
        )

    def has_seen_activity(self) -> bool:
        return self._seen_activity

    def pause_microphone(self) -> None:
        cfg = self._source_config()
        if str(cfg.get("source", "file")) != "microphone":
            return
        self._microphone_listener.pause()

    def resume_microphone(self) -> bool:
        cfg = self._source_config()
        if str(cfg.get("source", "file")) != "microphone":
            return False
        resumed = self._microphone_listener.resume()
        if resumed:
            return True
        return self._ensure_microphone_listener(cfg)

    def stop(self) -> None:
        self._microphone_listener.stop()

    def _source_config(self) -> dict:
        if not self._config_path.exists():
            return {}
        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return {}
        if mtime != self._config_mtime:
            try:
                self._config = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
            except Exception:
                self._config = {}
            self._config_mtime = mtime
        node = self._config
        for key in self._settings_path:
            if not isinstance(node, dict):
                return {}
            node = node.get(key, {})
        return node if isinstance(node, dict) else {}

    def _ensure_microphone_listener(self, cfg: dict) -> bool:
        if not bool(cfg.get("auto_start_listener", True)):
            return False
        transcript_file = Path(str(cfg.get("transcript_file", "dialogue_mic.txt")))
        culture = str(cfg.get("recognition_language", "zh-CN"))
        backend = str(cfg.get("microphone_backend", "powershell"))
        stt_backend = str(cfg.get("stt_backend", "system"))
        silence_ms = int(cfg.get("silence_ms", 1000) or 1000)
        whisper_model = str(cfg.get("whisper_model", "base"))
        return self._microphone_listener.ensure_running(
            transcript_file,
            culture=culture,
            backend=backend,
            silence_ms=silence_ms,
            stt_backend=stt_backend,
            whisper_model=whisper_model,
        )

    def _prepare_append_only_path(self, path: Path) -> None:
        if not path.exists():
            return
        resolved = os.fspath(path.resolve())
        if resolved in self._append_initialized_paths:
            return
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return
        self._line_index_by_path[resolved] = len(lines)
        self._append_initialized_paths.add(resolved)

    def _read_text_payload(
        self,
        path: Path,
        speaker: str,
        clear_after_read: bool,
        source_kind: str,
    ) -> dict | None:
        if not path.exists():
            return None
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return None
        if not lines:
            return None
        resolved = os.fspath(path.resolve())
        index = self._line_index_by_path.get(resolved, 0)
        text = lines[index % len(lines)]
        self._line_index_by_path[resolved] = (index + 1) % len(lines)
        self._seen_activity = True
        return {
            self._plugin_id: {
                "speaker": speaker,
                "text": text,
                "source": source_kind,
                "source_path": os.fspath(path),
                "line_mode": "loop",
            }
        }

    def _read_append_only_payload(
        self,
        path: Path,
        speaker: str,
        source_kind: str,
    ) -> dict | None:
        if not path.exists():
            return None
        self._trim_append_only_file(path, cfg=self._source_config())
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return None
        if not lines:
            return None
        resolved = os.fspath(path.resolve())
        if resolved not in self._append_initialized_paths:
            self._line_index_by_path[resolved] = len(lines)
            self._append_initialized_paths.add(resolved)
            return None
        index = self._line_index_by_path.get(resolved, 0)
        if index > len(lines):
            index = 0
        if index >= len(lines):
            return None
        text = lines[index]
        self._line_index_by_path[resolved] = index + 1
        self._seen_activity = True
        return {
            self._plugin_id: {
                "speaker": speaker,
                "text": text,
                "source": source_kind,
                "source_path": os.fspath(path),
                "line_mode": "append_only",
            }
        }

    def _trim_append_only_file(self, path: Path, cfg: dict) -> None:
        max_mb = int(cfg.get("max_transcript_mb", 10) or 10)
        max_bytes = max(1, max_mb) * 1024 * 1024
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size <= max_bytes:
            return
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        if not raw_lines:
            return

        resolved = os.fspath(path.resolve())
        current_index = self._line_index_by_path.get(resolved, 0)
        unread_lines = raw_lines[current_index:] if current_index < len(raw_lines) else []
        if not unread_lines:
            unread_lines = raw_lines[-1:]

        selected: list[str] = []
        current_bytes = 0
        for line in reversed(unread_lines):
            line_bytes = len((line + "\n").encode("utf-8"))
            if not selected and line_bytes > max_bytes:
                selected.insert(0, self._tail_fit_utf8(line, max_bytes - 1))
                current_bytes = len((selected[0] + "\n").encode("utf-8"))
                break
            if selected and current_bytes + line_bytes > max_bytes:
                break
            selected.insert(0, line)
            current_bytes += line_bytes

        trimmed_text = "\n".join(selected).strip()
        if trimmed_text:
            trimmed_text += "\n"
        try:
            path.write_text(trimmed_text, encoding="utf-8")
        except Exception:
            return
        self._line_index_by_path[resolved] = 0
        self._append_initialized_paths.add(resolved)

    def _tail_fit_utf8(self, text: str, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        if len(text.encode("utf-8")) <= max_bytes:
            return text
        low = 0
        high = len(text)
        while low < high:
            mid = (low + high) // 2
            candidate = text[mid:]
            if len(candidate.encode("utf-8")) <= max_bytes:
                high = mid
            else:
                low = mid + 1
        return text[low:]
