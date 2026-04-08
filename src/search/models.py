"""Data models for web search."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchSite:
    domain: str
    priority: int = 50


@dataclass(slots=True)
class SearchDocument:
    domain: str
    priority: int
    title: str
    url: str
    snippet: str
    excerpt: str
    patch_version: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
