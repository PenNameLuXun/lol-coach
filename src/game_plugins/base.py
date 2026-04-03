from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.web_knowledge import KnowledgeItem, KnowledgeQuery
from src.qa_web_search import SearchDocument

@dataclass(slots=True)
class GameState:
    plugin_id: str
    game_type: str
    raw_data: dict
    metrics: dict[str, int | str]
    derived: dict[str, int | str] = field(default_factory=dict)


@dataclass(slots=True)
class RuleResult:
    rule_id: str
    priority: int
    message: str
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class AiPayload:
    game_summary: str
    address: str | None
    metrics: dict[str, int | str]


class GamePlugin(Protocol):
    id: str
    display_name: str
    manifest: dict[str, object]

    def is_available(self) -> bool: ...
    def fetch_live_data(self) -> dict | None: ...
    def has_seen_activity(self) -> bool: ...
    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool: ...
    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState: ...
    def evaluate_rules(self, state: GameState) -> list[RuleResult]: ...
    def build_ai_payload(
        self,
        state: GameState,
        detail: str = "normal",
        address_by: str = "champion",
    ) -> AiPayload: ...

    def build_rule_hint(self, rule: RuleResult, state: GameState) -> str:
        return rule.message

    def wants_visual_context(self, state: GameState) -> bool:
        return True

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
    ) -> str: ...

    def build_web_knowledge_queries(self, state: GameState, config) -> list[KnowledgeQuery]:
        return []

    def build_web_knowledge_summary(self, state: GameState, config) -> str:
        return ""

    def build_web_knowledge_item(self, query: KnowledgeQuery, documents, state: GameState, config) -> KnowledgeItem | None:
        return None

    def collect_web_knowledge_documents(self, query: KnowledgeQuery, state: GameState, config) -> list[SearchDocument]:
        return []
