from __future__ import annotations

import os
from pathlib import Path

import yaml

from src.game_plugins.dialogue.microphone import WindowsMicrophoneListener


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
        self._seen_activity = False
        self._microphone_listener = WindowsMicrophoneListener(plugin_id=plugin_id)

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
        return self._microphone_listener.ensure_running(transcript_file, culture=culture)

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
        try:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return None
        if not lines:
            return None
        resolved = os.fspath(path.resolve())
        index = self._line_index_by_path.get(resolved, 0)
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
