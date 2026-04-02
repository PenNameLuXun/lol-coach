from __future__ import annotations

from src.game_plugins.base import AiPayload, GameState, RuleResult
from src.game_plugins.dialogue.source import DialogueSource


class GameQaPlugin:
    id = "game_qa"
    display_name = "Game Q&A"
    manifest = {
        "id": "game_qa",
        "display_name": "Game Q&A",
        "source": {"kind": "text_or_microphone"},
        "supports_rules": False,
        "supports_ai_context": True,
        "capabilities": {"ai": True, "rules": False, "visual": False},
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
                "default": "game_qa_input.txt",
                "help": "file 模式下读取的问答文本文件路径。",
            },
            {
                "key": "transcript_file",
                "label": "转写文件",
                "type": "string",
                "default": "game_qa_mic.txt",
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
                "key": "auto_start_listener",
                "label": "自动启动麦克风监听",
                "type": "bool",
                "default": True,
                "help": "启用 microphone 模式时自动拉起本地语音识别监听器。",
            },
            {
                "key": "speaker",
                "label": "提问者",
                "type": "string",
                "default": "玩家",
                "help": "写入 AI 提示词中的提问者名称。",
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "text",
                "default": "你是 MOBA 与策略游戏问答助手。用户会在对局中或对局外提出英雄对线、出装、运营、阵容理解等问题。请用简洁、可靠、可执行的中文直接回答，优先给出 2 到 4 个最关键建议；如果信息不够，就明确说明你的假设。",
                "help": "Game Q&A 插件专属系统提示词。",
            },
        ],
    }

    def __init__(self):
        self._source = DialogueSource(plugin_id=self.id)

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        return self.id in raw_data

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        payload = raw_data.get(self.id, {})
        question = str(payload.get("text", "")).strip()
        speaker = str(payload.get("speaker", "玩家"))
        source_kind = str(payload.get("source", "file"))
        normalized = metrics or {
            "game_type": self.id,
            "game_time": "qa",
            "gold": 0,
            "level": 0,
            "hp_pct": 0,
            "mana_pct": 0,
            "kda": "-",
            "cs": 0,
            "event_signature": question[:48] or "none",
            "mode": source_kind,
        }
        return GameState(
            plugin_id=self.id,
            game_type=self.id,
            raw_data=raw_data,
            metrics=normalized,
            derived={
                "speaker": speaker,
                "question": question,
                "source_kind": source_kind,
            },
        )

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        return []

    def build_ai_payload(
        self,
        state: GameState,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> AiPayload:
        question = str(state.derived.get("question", ""))
        speaker = str(state.derived.get("speaker", "玩家"))
        source_kind = str(state.derived.get("source_kind", "file"))
        return AiPayload(
            game_summary=f"问答来源：{source_kind}，提问者：{speaker}，问题：{question}",
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
        question = str(state.derived.get("question", ""))
        return (
            f"{system_prompt}\n\n"
            "当前任务：回答玩家的游戏问题，而不是分析截图。\n"
            "回答规则：\n"
            "1. 直接回答问题，不要复述系统设定。\n"
            "2. 优先给具体、可执行的建议，例如技能换血思路、兵线处理、装备选择、关键 timing。\n"
            "3. 若问题像“剑圣怎么打蛮王”，优先回答对线期处理、关键技能互动、中期思路。\n"
            "4. 回答尽量控制在 120 字以内，适合语音播报。\n"
            "5. 如果问题信息不足，可以先点明默认假设，例如“默认同水平单排”。\n\n"
            f"提问者：{payload.address or '玩家'}\n"
            f"当前问题：{question or '无'}\n"
            f"问题摘要：{payload.game_summary}\n"
            f"最近问答历史：\n{_render_qa_history(snapshots)}"
        )



def _render_qa_history(snapshots: list) -> str:
    if not snapshots:
        return "无历史问答。"
    lines = []
    for snap in snapshots[-4:]:
        lines.append(f"上一轮回复：{snap.advice}")
    return "\n".join(lines)
