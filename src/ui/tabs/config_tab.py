from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QPushButton, QTextEdit, QGroupBox, QVBoxLayout
)
from PyQt6.QtCore import pyqtSignal
from src.config import Config


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

    def _load_values(self):
        self._provider_combo.setCurrentText(self._cfg.ai_provider)
        provider = self._cfg.ai_provider
        self._api_key_edit.setText(self._cfg.ai_config(provider).get("api_key", ""))
        self._model_edit.setText(self._cfg.ai_config(provider).get("model", ""))
        self._prompt_edit.setPlainText(self._cfg.system_prompt)
        self._tts_combo.setCurrentText(self._cfg.tts_backend)
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
        provider = self._provider_combo.currentText()
        self._cfg.set("ai.provider", provider)
        self._cfg.set(f"ai.{provider}.api_key", self._api_key_edit.text())
        self._cfg.set(f"ai.{provider}.model", self._model_edit.text())
        self._cfg.set("ai.system_prompt", self._prompt_edit.toPlainText())
        self._cfg.set("tts.backend", self._tts_combo.currentText())
        self._cfg.set("capture.interval", self._interval_spin.value())
        self._cfg.set("capture.hotkey", self._hotkey_edit.text())
        self._cfg.set("capture.region", self._region_combo.currentText())
        self._cfg.set("capture.monitor", self._monitor_spin.value())
        self._cfg.set("capture.jpeg_quality", self._quality_spin.value())
        self._cfg.set("overlay.fade_after", self._fade_spin.value())
        self._cfg.set("overlay.toggle_hotkey", self._overlay_hotkey_edit.text())
        self.config_changed.emit()
