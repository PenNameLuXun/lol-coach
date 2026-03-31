from __future__ import annotations

import os
from pathlib import Path

import yaml


class DialogueSource:
    def __init__(self, config_path: str = "config.yaml"):
        self._config_path = Path(config_path)
        self._config_mtime = 0.0
        self._config: dict = {}
        self._line_index_by_path: dict[str, int] = {}
        self._seen_activity = False

    def is_available(self) -> bool:
        cfg = self._dialogue_config()
        source_kind = str(cfg.get("source", "file"))
        if source_kind == "file":
            return True
        if source_kind == "microphone":
            transcript_file = Path(str(cfg.get("transcript_file", "dialogue_mic.txt")))
            return transcript_file.exists() or True
        return False

    def fetch_live_data(self) -> dict | None:
        cfg = self._dialogue_config()
        source_kind = str(cfg.get("source", "file"))
        if source_kind == "microphone":
            return self._read_text_payload(
                path=Path(str(cfg.get("transcript_file", "dialogue_mic.txt"))),
                speaker=str(cfg.get("speaker", "玩家")),
                clear_after_read=bool(cfg.get("clear_after_read", True)),
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

    def _dialogue_config(self) -> dict:
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
        plugin_settings = self._config.get("plugin_settings", {}).get("dialogue", {})
        if isinstance(plugin_settings, dict) and plugin_settings:
            return plugin_settings
        legacy = self._config.get("dialogue_plugin", {})
        return legacy if isinstance(legacy, dict) else {}

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
            "dialogue": {
                "speaker": speaker,
                "text": text,
                "source": source_kind,
                "source_path": os.fspath(path),
                "line_mode": "loop",
            }
        }
