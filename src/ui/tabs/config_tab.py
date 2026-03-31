from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QPushButton, QTextEdit, QGroupBox, QVBoxLayout,
    QCheckBox, QLabel, QScrollArea
)
from PyQt6.QtCore import pyqtSignal
from src.config import Config
from src.game_plugins.registry import discover_plugins
from src.ui.widgets.collapsible_box import CollapsibleBox

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
        self._plugins = discover_plugins()
        self._plugin_setting_widgets: dict[str, dict[str, tuple[dict, object]]] = {}
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)

        # ── Decision ────────────────────────────────────────────────────────
        decision_box = QGroupBox("决策模式")
        decision_form = QFormLayout(decision_box)

        self._decision_mode_combo = QComboBox()
        self._decision_mode_combo.addItems(["ai", "rules", "hybrid"])
        decision_form.addRow("决策模式:", self._decision_mode_combo)

        self._enabled_plugins_edit = QLineEdit()
        plugin_ids = [plugin.id for plugin in self._plugins]
        self._enabled_plugins_edit.setPlaceholderText(",".join(plugin_ids) or "留空=全部插件")
        self._enabled_plugins_edit.setToolTip("逗号分隔插件ID，留空表示启用所有已发现插件")
        decision_form.addRow("启用插件:", self._enabled_plugins_edit)

        self._hybrid_threshold_spin = QSpinBox()
        self._hybrid_threshold_spin.setRange(0, 100)
        decision_form.addRow("混合直出阈值:", self._hybrid_threshold_spin)

        root.addWidget(self._wrap_section("决策模式", decision_box, collapsed=False))
        root.addWidget(self._build_plugin_settings_box())

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

        root.addWidget(self._wrap_section("AI 设置", ai_box, collapsed=False))

        # ── TTS ───────────────────────────────────────────────────────────────
        tts_box = QGroupBox("语音输出")
        tts_form = QFormLayout(tts_box)

        self._tts_combo = QComboBox()
        self._tts_combo.addItems(["windows", "edge", "openai"])
        tts_form.addRow("TTS 后端:", self._tts_combo)

        self._tts_playback_mode_combo = QComboBox()
        self._tts_playback_mode_combo.addItems(["wait", "interrupt", "continue"])
        self._tts_playback_mode_combo.setToolTip("wait=顺序播完再继续；interrupt=若后端支持则打断当前播报；continue=不等待也不打断，继续排队。")
        tts_form.addRow("播报模式:", self._tts_playback_mode_combo)

        self._tts_windows_rate_spin = QSpinBox()
        self._tts_windows_rate_spin.setRange(-10, 10)
        self._tts_windows_rate_spin.setToolTip("Windows SAPI 使用相对语速档位，0 为默认，负数更慢，正数更快")
        tts_form.addRow("Windows 语速:", self._tts_windows_rate_spin)

        self._tts_edge_rate_edit = QLineEdit()
        self._tts_edge_rate_edit.setPlaceholderText("+0%  (如 +30% 加速，-20% 减速，仅 edge 生效)")
        tts_form.addRow("Edge 语速:", self._tts_edge_rate_edit)

        root.addWidget(self._wrap_section("语音输出", tts_box, collapsed=True))

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

        root.addWidget(self._wrap_section("截图设置", cap_box, collapsed=True))

        # ── Overlay ───────────────────────────────────────────────────────────
        ov_box = QGroupBox("悬浮窗")
        ov_form = QFormLayout(ov_box)

        self._fade_spin = QSpinBox()
        self._fade_spin.setRange(0, 60)
        self._fade_spin.setSuffix(" 秒 (0=不淡出)")
        ov_form.addRow("自动淡出:", self._fade_spin)

        self._overlay_hotkey_edit = QLineEdit()
        ov_form.addRow("显示/隐藏热键:", self._overlay_hotkey_edit)

        root.addWidget(self._wrap_section("悬浮窗", ov_box, collapsed=True))

        # ── Save button ───────────────────────────────────────────────────────
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save)
        root.addWidget(save_btn)
        root.addStretch(1)

    def _wrap_section(self, title: str, widget: QWidget, collapsed: bool) -> CollapsibleBox:
        box = CollapsibleBox(title, collapsed=collapsed)
        box.setContentWidget(widget)
        return box

    def _build_plugin_settings_box(self) -> CollapsibleBox:
        plugin_box = QWidget()
        plugin_layout = QVBoxLayout(plugin_box)

        for plugin in self._plugins:
            schema = plugin.manifest.get("config_schema", [])
            if not schema:
                continue
            capabilities = plugin.manifest.get("capabilities", {})
            caps = " / ".join(
                label
                for key, label in (("ai", "AI"), ("rules", "规则"), ("visual", "视觉"))
                if capabilities.get(key, False)
            ) or "无特殊能力"

            group = QGroupBox(plugin.display_name)
            form = QFormLayout(group)
            badge = QLabel(f"能力: {caps}")
            form.addRow("插件能力:", badge)

            widgets: dict[str, tuple[dict, object]] = {}
            for field in schema:
                widget = self._create_plugin_widget(field)
                help_text = str(field.get("help", "")).strip()
                if help_text:
                    widget.setToolTip(help_text)
                form.addRow(f"{field.get('label', field['key'])}:", widget)
                widgets[str(field["key"])] = (field, widget)

            self._plugin_setting_widgets[plugin.id] = widgets
            plugin_layout.addWidget(self._wrap_section(plugin.display_name, group, collapsed=True))

        plugin_layout.addStretch(1)
        return self._wrap_section("插件设置", plugin_box, collapsed=True)

    def _create_plugin_widget(self, field: dict):
        field_type = field.get("type", "string")
        if field_type == "bool":
            return QCheckBox()
        if field_type == "int":
            spin = QSpinBox()
            spin.setRange(int(field.get("min", 0)), int(field.get("max", 9999)))
            return spin
        if field_type == "select":
            combo = QComboBox()
            combo.addItems([str(option) for option in field.get("options", [])])
            return combo
        return QLineEdit()

    def _plugin_field_value(self, widget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return widget.text()

    def _set_plugin_field_value(self, widget, value):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(value))
        else:
            widget.setText("" if value is None else str(value))

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
        self._tts_playback_mode_combo.setCurrentText(self._cfg.tts_playback_mode)
        self._tts_windows_rate_spin.setValue(int(self._cfg.tts_config("windows").get("rate", 0)))
        self._tts_edge_rate_edit.setText(self._cfg.tts_config("edge").get("rate", "+0%"))
        self._interval_spin.setValue(self._cfg.capture_interval)
        self._hotkey_edit.setText(self._cfg.capture_hotkey)
        self._region_combo.setCurrentText(self._cfg.capture_region)
        self._monitor_spin.setValue(self._cfg.capture_monitor)
        self._quality_spin.setValue(self._cfg.capture_jpeg_quality)
        self._fade_spin.setValue(self._cfg.overlay.get("fade_after", 8))
        self._overlay_hotkey_edit.setText(self._cfg.overlay.get("toggle_hotkey", ""))
        for plugin in self._plugins:
            settings = self._cfg.plugin_settings(plugin.id)
            for key, (field, widget) in self._plugin_setting_widgets.get(plugin.id, {}).items():
                value = settings.get(key, field.get("default"))
                self._set_plugin_field_value(widget, value)

    def _update_api_key_label(self, provider: str):
        try:
            self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
            self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        except KeyError:
            pass

    def _save(self):
        plugin_text = self._enabled_plugins_edit.text().strip()
        enabled_plugins = [item.strip() for item in plugin_text.split(",") if item.strip()]
        provider = self._provider_combo.currentText()
        updates = {
            "decision.mode": self._decision_mode_combo.currentText(),
            "decision.plugins.enabled": enabled_plugins,
            "decision.rules.hybrid_priority_threshold": self._hybrid_threshold_spin.value(),
            "ai.provider": provider,
            f"ai.{provider}.api_key": self._api_key_edit.text(),
            f"ai.{provider}.model": self._model_edit.text(),
            "ai.system_prompt": self._prompt_edit.toPlainText(),
            "tts.backend": self._tts_combo.currentText(),
            "tts.playback_mode": self._tts_playback_mode_combo.currentText(),
            "tts.windows.rate": self._tts_windows_rate_spin.value(),
            "tts.edge.rate": self._tts_edge_rate_edit.text(),
            "capture.interval": self._interval_spin.value(),
            "capture.hotkey": self._hotkey_edit.text(),
            "capture.region": self._region_combo.currentText(),
            "capture.monitor": self._monitor_spin.value(),
            "capture.jpeg_quality": self._quality_spin.value(),
            "overlay.fade_after": self._fade_spin.value(),
            "overlay.toggle_hotkey": self._overlay_hotkey_edit.text(),
        }
        for plugin_id, fields in self._plugin_setting_widgets.items():
            for key, (_field, widget) in fields.items():
                updates[f"plugin_settings.{plugin_id}.{key}"] = self._plugin_field_value(widget)
        self._cfg.update_many(updates)
        self.config_changed.emit()
