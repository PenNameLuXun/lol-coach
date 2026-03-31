from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QPushButton, QTextEdit, QGroupBox, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal
from src.config import Config
from src.game_plugins.registry import discover_plugins

PROMPT_PRESETS = {
    "LOL 5V5 对战": "你是一个英雄联盟教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条对局建议。",
    "云顶之弈": "你是一个云顶之弈教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条建议，例如该买什么英雄、阵容方向、经济决策等。",
    "王者荣耀": "你是一个王者荣耀教练，根据当前游戏截图，用简短的中文（不超过50字）给出最重要的一条对局建议。",
    "Dota2": "You are a Dota2 coach. Based on the current screenshot, give the single most important advice in concise Chinese (under 50 characters).",
    "自定义": "",
}


class ConfigTab(QWidget):
    """Form for editing all config.yaml settings.

    Emits `config_changed` after saving so other components can react.
    """

    config_changed = pyqtSignal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Decision ────────────────────────────────────────────────────────
        decision_box = QGroupBox("决策模式")
        decision_form = QFormLayout(decision_box)

        self._decision_mode_combo = QComboBox()
        self._decision_mode_combo.addItems(["ai", "rules", "hybrid"])
        decision_form.addRow("决策模式:", self._decision_mode_combo)

        self._enabled_plugins_edit = QLineEdit()
        plugin_ids = [plugin.id for plugin in discover_plugins()]
        self._enabled_plugins_edit.setPlaceholderText(",".join(plugin_ids) or "留空=全部插件")
        self._enabled_plugins_edit.setToolTip("逗号分隔插件ID，留空表示启用所有已发现插件")
        decision_form.addRow("启用插件:", self._enabled_plugins_edit)

        self._hybrid_threshold_spin = QSpinBox()
        self._hybrid_threshold_spin.setRange(0, 100)
        decision_form.addRow("混合直出阈值:", self._hybrid_threshold_spin)

        root.addWidget(decision_box)

        # ── AI ────────────────────────────────────────────────────────────────
        ai_box = QGroupBox("AI 设置")
        ai_form = QFormLayout(ai_box)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["claude", "openai", "gemini", "deepseek", "qwen", "zhipu", "ollama"])
        self._provider_combo.currentTextChanged.connect(self._update_api_key_label)
        ai_form.addRow("AI 提供商:", self._provider_combo)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        ai_form.addRow("API Key:", self._api_key_edit)

        self._model_edit = QLineEdit()
        ai_form.addRow("模型名称:", self._model_edit)

        self._preset_combo = QComboBox()
        self._preset_combo.addItems(list(PROMPT_PRESETS.keys()))
        self._preset_combo.currentTextChanged.connect(self._apply_preset)
        ai_form.addRow("游戏模式:", self._preset_combo)

        self._prompt_edit = QTextEdit()
        self._prompt_edit.setMaximumHeight(80)
        ai_form.addRow("System Prompt:", self._prompt_edit)

        root.addWidget(ai_box)

        # ── TTS ───────────────────────────────────────────────────────────────
        tts_box = QGroupBox("语音输出")
        tts_form = QFormLayout(tts_box)

        self._tts_combo = QComboBox()
        self._tts_combo.addItems(["windows", "edge", "openai"])
        tts_form.addRow("TTS 后端:", self._tts_combo)

        self._tts_rate_edit = QLineEdit()
        self._tts_rate_edit.setPlaceholderText("+0%  (如 +30% 加速，-20% 减速，仅 edge 生效)")
        tts_form.addRow("语速:", self._tts_rate_edit)

        root.addWidget(tts_box)

        # ── Capture ───────────────────────────────────────────────────────────
        cap_box = QGroupBox("截图设置")
        cap_form = QFormLayout(cap_box)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 60)
        self._interval_spin.setSuffix(" 秒 (0=禁用)")
        cap_form.addRow("定时间隔:", self._interval_spin)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("e.g. ctrl+shift+a  (空=禁用)")
        cap_form.addRow("截图热键:", self._hotkey_edit)

        self._region_combo = QComboBox()
        self._region_combo.addItems(["fullscreen", "lol_window"])
        cap_form.addRow("截图区域:", self._region_combo)

        self._monitor_spin = QSpinBox()
        self._monitor_spin.setRange(1, 8)
        self._monitor_spin.setToolTip("1 = 主屏，2 = 第二块屏幕，以此类推")
        cap_form.addRow("截图屏幕:", self._monitor_spin)

        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(10, 95)
        cap_form.addRow("JPEG 质量:", self._quality_spin)

        root.addWidget(cap_box)

        # ── Overlay ───────────────────────────────────────────────────────────
        ov_box = QGroupBox("悬浮窗")
        ov_form = QFormLayout(ov_box)

        self._fade_spin = QSpinBox()
        self._fade_spin.setRange(0, 60)
        self._fade_spin.setSuffix(" 秒 (0=不淡出)")
        ov_form.addRow("自动淡出:", self._fade_spin)

        self._overlay_hotkey_edit = QLineEdit()
        ov_form.addRow("显示/隐藏热键:", self._overlay_hotkey_edit)

        root.addWidget(ov_box)

        # ── Save button ───────────────────────────────────────────────────────
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)

    def _apply_preset(self, name: str):
        if name != "自定义" and PROMPT_PRESETS[name]:
            self._prompt_edit.setPlainText(PROMPT_PRESETS[name])

    def _load_values(self):
        self._decision_mode_combo.setCurrentText(self._cfg.decision_mode)
        self._enabled_plugins_edit.setText(",".join(self._cfg.enabled_plugins))
        self._hybrid_threshold_spin.setValue(self._cfg.rules_config.get("hybrid_priority_threshold", 85))
        self._provider_combo.setCurrentText(self._cfg.ai_provider)
        provider = self._cfg.ai_provider
        self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
        self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        current_prompt = self._cfg.system_prompt
        # match existing prompt to a preset, fallback to 自定义
        matched = next((k for k, v in PROMPT_PRESETS.items() if v == current_prompt), "自定义")
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentText(matched)
        self._preset_combo.blockSignals(False)
        self._prompt_edit.setPlainText(current_prompt)
        self._tts_combo.setCurrentText(self._cfg.tts_backend)
        self._tts_rate_edit.setText(self._cfg.tts_config("edge").get("rate", "+0%"))
        self._interval_spin.setValue(self._cfg.capture_interval)
        self._hotkey_edit.setText(self._cfg.capture_hotkey)
        self._region_combo.setCurrentText(self._cfg.capture_region)
        self._monitor_spin.setValue(self._cfg.capture_monitor)
        self._quality_spin.setValue(self._cfg.capture_jpeg_quality)
        self._fade_spin.setValue(self._cfg.overlay.get("fade_after", 8))
        self._overlay_hotkey_edit.setText(self._cfg.overlay.get("toggle_hotkey", ""))

    def _update_api_key_label(self, provider: str):
        try:
            self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
            self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        except KeyError:
            pass

    def _save(self):
        plugin_text = self._enabled_plugins_edit.text().strip()
        enabled_plugins = [item.strip() for item in plugin_text.split(",") if item.strip()]
        self._cfg.set("decision.mode", self._decision_mode_combo.currentText())
        self._cfg.set("decision.plugins.enabled", enabled_plugins)
        self._cfg.set("decision.rules.hybrid_priority_threshold", self._hybrid_threshold_spin.value())
        provider = self._provider_combo.currentText()
        self._cfg.set("ai.provider", provider)
        self._cfg.set(f"ai.{provider}.api_key", self._api_key_edit.text())
        self._cfg.set(f"ai.{provider}.model", self._model_edit.text())
        self._cfg.set("ai.system_prompt", self._prompt_edit.toPlainText())
        self._cfg.set("tts.backend", self._tts_combo.currentText())
        self._cfg.set("tts.edge.rate", self._tts_rate_edit.text())
        self._cfg.set("capture.interval", self._interval_spin.value())
        self._cfg.set("capture.hotkey", self._hotkey_edit.text())
        self._cfg.set("capture.region", self._region_combo.currentText())
        self._cfg.set("capture.monitor", self._monitor_spin.value())
        self._cfg.set("capture.jpeg_quality", self._quality_spin.value())
        self._cfg.set("overlay.fade_after", self._fade_spin.value())
        self._cfg.set("overlay.toggle_hotkey", self._overlay_hotkey_edit.text())
        self.config_changed.emit()
