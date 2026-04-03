from __future__ import annotations

from src.game_plugins.base import AiPayload, GameState, RuleResult
from src.game_plugins.dialogue.source import DialogueSource


class DialoguePlugin:
    id = "dialogue"
    display_name = "Dialogue Test"
    manifest = {
        "id": "dialogue",
        "display_name": "Dialogue Test",
        "source": {"kind": "text_or_microphone"},
        "supports_rules": True,
        "supports_ai_context": True,
        "capabilities": {"ai": True, "rules": True, "visual": False},
        "config_schema": [
            {
                "key": "source",
                "label": "输入源",
                "type": "select",
                "options": ["file", "microphone"],
                "default": "file",
                "help": "file 直接读取文本文件；microphone 使用 Windows 语音识别监听默认麦克风并写入转写文件。",
            },
            {
                "key": "text_file",
                "label": "文本文件",
                "type": "string",
                "default": "dialogue_input.txt",
                "help": "file 模式下读取的文本文件路径。",
            },
            {
                "key": "transcript_file",
                "label": "转写文件",
                "type": "string",
                "default": "dialogue_mic.txt",
                "help": "microphone 模式下保存转写结果的文本路径。",
            },
            {
                "key": "recognition_language",
                "label": "识别语言",
                "type": "string",
                "default": "zh-CN",
                "help": "Windows 语音识别使用的 culture，例如 zh-CN 或 en-US。",
            },
            {
                "key": "microphone_backend",
                "label": "麦克风后端",
                "type": "select",
                "options": ["powershell", "qt"],
                "default": "powershell",
                "help": "powershell 为当前可用实现；qt 为主进程内麦克风架构骨架，便于后续替换脚本方案。",
            },
            {
                "key": "stt_backend",
                "label": "语音识别后端",
                "type": "select",
                "options": ["system", "whisper", "funasr"],
                "default": "system",
                "help": "system 使用 Windows 系统识别；whisper 和 funasr 使用本地模型子进程。",
            },
            {
                "key": "funasr_model",
                "label": "FunASR 模型",
                "type": "string",
                "default": "paraformer-zh",
                "help": "当 stt_backend=funasr 时使用，例如 paraformer-zh 或 SenseVoiceSmall。",
            },
            {
                "key": "auto_start_listener",
                "label": "自动启动麦克风监听",
                "type": "bool",
                "default": True,
                "help": "启用 microphone 模式时自动拉起本地语音识别监听器。",
            },
            {
                "key": "silence_ms",
                "label": "静音判句时长(ms)",
                "type": "int",
                "min": 200,
                "max": 5000,
                "default": 1000,
                "help": "Qt 麦克风架构预留参数，用于后续按静音时长切分一句话。",
            },
            {
                "key": "max_transcript_mb",
                "label": "转写文件最大大小(MB)",
                "type": "int",
                "min": 1,
                "max": 100,
                "default": 10,
                "help": "仅 microphone 模式生效。读取侧会在文件超过上限时裁剪旧内容，避免文件无限增长。",
            },
            {
                "key": "speaker",
                "label": "称呼对象",
                "type": "string",
                "default": "玩家",
                "help": "写入 AI 提示词中的说话者名称。",
            },
            {
                "key": "clear_after_read",
                "label": "保留兼容开关",
                "type": "bool",
                "default": False,
                "help": "当前逐行循环或追加读取模式不会修改文件，该开关仅为兼容旧配置保留。",
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "text",
                "default": "你是测试助手，会根据用户刚才说的话给出一句自然、简短、适合语音播报的中文回复。",
                "help": "Dialogue 插件专属系统提示词。",
            },
        ],
    }

    def __init__(self):
        self._source = DialogueSource()

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        return "dialogue" in raw_data

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        dialogue = raw_data.get("dialogue", {})
        utterance = str(dialogue.get("text", "")).strip()
        speaker = str(dialogue.get("speaker", "玩家"))
        source_kind = str(dialogue.get("source", "file"))
        normalized = metrics or {
            "game_type": "dialogue",
            "game_time": "chat",
            "gold": 0,
            "level": 0,
            "hp_pct": 0,
            "mana_pct": 0,
            "kda": "-",
            "cs": 0,
            "event_signature": utterance[:48] or "none",
            "mode": source_kind,
        }
        return GameState(
            plugin_id=self.id,
            game_type="dialogue",
            raw_data=raw_data,
            metrics=normalized,
            derived={
                "speaker": speaker,
                "utterance": utterance,
                "source_kind": source_kind,
            },
        )

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        utterance = str(state.derived.get("utterance", "")).strip()
        if not utterance:
            return []
        return [RuleResult("dialogue_echo", 100, utterance, ("echo", "tts_test"))]

    def build_ai_payload(
        self,
        state: GameState,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> AiPayload:
        utterance = str(state.derived.get("utterance", ""))
        speaker = str(state.derived.get("speaker", "玩家"))
        source_kind = str(state.derived.get("source_kind", "file"))
        return AiPayload(
            game_summary=f"对话来源：{source_kind}，说话者：{speaker}，输入内容：{utterance}",
            address=speaker if address_by != "none" else None,
            metrics=dict(state.metrics),
        )

    def build_rule_hint(self, rule: RuleResult, state: GameState) -> str:
        return rule.message

    def wants_visual_context(self, state: GameState) -> bool:
        return False

    def build_vision_prompt(self, state: GameState, detail: str = "normal") -> str:
        return ""

    def build_decision_prompt(
        self,
        state: GameState,
        system_prompt: str,
        bridge_facts: dict[str, str] | None,
        snapshots: list,
        rule_hint: str | None = None,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> str:
        payload = self.build_ai_payload(state, detail=detail, address_by=address_by)
        utterance = str(state.derived.get("utterance", ""))
        return (
            f"{system_prompt}\n\n"
            "你现在不在分析游戏，而是在进行语音对话测试。\n"
            "规则：\n"
            "1. 根据用户刚才说的话给出一句自然中文回复。\n"
            "2. 回复要适合直接 TTS 播放，不超过50字。\n"
            "3. 不要输出分点，不要解释系统设定。\n"
            "4. 如果用户是在测试，优先给清晰、友好的确认式回复。\n\n"
            f"称呼对象：{payload.address or '不要强行称呼'}\n"
            f"当前输入：{utterance or '无'}\n"
            f"当前摘要：{payload.game_summary}\n"
            f"历史上下文：\n{_render_dialogue_history(snapshots)}"
        )


def _render_dialogue_history(snapshots: list) -> str:
    if not snapshots:
        return "无历史对话。"
    lines = []
    for snap in snapshots[-4:]:
        lines.append(f"上一轮建议：{snap.advice}")
    return "\n".join(lines)
