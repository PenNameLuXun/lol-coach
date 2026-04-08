"""Formatting and sorting of search documents."""

from __future__ import annotations

import re

from src.search.models import SearchDocument


def sort_search_documents(docs: list[SearchDocument]) -> list[SearchDocument]:
    return sorted(
        docs,
        key=lambda doc: (
            _patch_sort_key(doc.patch_version),
            doc.priority,
            doc.domain,
        ),
        reverse=True,
    )


def format_search_documents(docs: list[SearchDocument]) -> str:
    if not docs:
        return "无联网搜索结果。"
    lines: list[str] = []
    for index, doc in enumerate(docs, start=1):
        version_line = f"版本: {doc.patch_version}\n" if doc.patch_version else ""
        lines.append(
            f"[{index}] 站点={doc.domain} 优先级={doc.priority}\n"
            f"{version_line}"
            f"标题: {doc.title}\n"
            f"链接: {doc.url}\n"
            f"摘要: {doc.snippet}\n"
            f"正文摘录: {doc.excerpt[:1200]}"
        )
    return "\n\n".join(lines)


def _patch_sort_key(version: str) -> tuple[int, int, int]:
    if not version:
        return (0, -1, -1)
    try:
        major_text, minor_text = version.split(".", 1)
        return (1, int(major_text), int(minor_text))
    except Exception:
        return (0, -1, -1)
