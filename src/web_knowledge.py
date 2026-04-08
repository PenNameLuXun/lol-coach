from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.qa_web_search import SearchDocument, SearchSite, merge_search_sites, parse_search_sites_text, search_web_for_qa


@dataclass(slots=True)
class KnowledgeQuery:
    key: str
    title: str
    query: str
    sites: list[SearchSite] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeItem:
    key: str
    tab_label: str
    title: str
    query: str
    documents: list[SearchDocument]
    sections: list[tuple[str, str]] = field(default_factory=list)
    fallback_text: str = ""


@dataclass(slots=True)
class KnowledgeBundle:
    plugin_id: str
    display_name: str
    summary: str
    items: list[KnowledgeItem]
    generated_at: datetime


class WebKnowledgeManager:
    def __init__(self):
        self._cached_signature: tuple[Any, ...] | None = None
        self._cached_bundle: KnowledgeBundle | None = None
        self._cached_at = 0.0

    def collect_for_context(self, active_context, config, debug_timing: bool = False) -> KnowledgeBundle | None:
        if not config.web_knowledge_enabled or active_context is None:
            return None
        started_at = time.perf_counter()
        plugin = active_context.plugin
        plugin_id = plugin.id
        if not config.plugin_web_knowledge_enabled(plugin_id):
            return None
        build_queries = getattr(plugin, 'build_web_knowledge_queries', None)
        if build_queries is None:
            return None
        queries = build_queries(active_context.state, config) or []
        if not queries:
            return None
        embed_mode = str(config.web_knowledge_settings.get("mode", "text")).strip().lower() == "embed"
        signature = _signature_for_queries(plugin_id, queries)
        now = datetime.now().timestamp()
        if (
            self._cached_bundle is not None
            and self._cached_signature == signature
            and now - self._cached_at < config.web_knowledge_refresh_interval_seconds
        ):
            if debug_timing:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                print(
                    f"[WebKnowledge] plugin={plugin_id} cache_hit=true "
                    f"items={len(self._cached_bundle.items)} elapsed_ms={elapsed_ms:.0f}"
                )
            return self._cached_bundle

        def _collect_one(query: KnowledgeQuery) -> tuple[KnowledgeQuery, list[SearchDocument], float]:
            if embed_mode:
                # embed 模式直接由 WebEngine 加载 URL，无需抓取文字内容
                return query, [], 0.0
            query_started_at = time.perf_counter()
            collector = getattr(plugin, "collect_web_knowledge_documents", None)
            if callable(collector):
                documents = collector(query, active_context.state, config) or []
            else:
                sites = query.sites or _sites_from_config(config, plugin_id)
                documents = search_web_for_qa(
                    question=query.query,
                    engine=config.web_knowledge_search_engine,
                    sites=sites,
                    timeout_seconds=config.web_knowledge_timeout_seconds,
                    max_results_per_site=config.web_knowledge_max_results_per_site,
                    max_pages=config.web_knowledge_max_pages,
                    stop_after_first_site_success=True,
                    accept_language=config.web_knowledge_accept_language,
                )
            query_elapsed_ms = (time.perf_counter() - query_started_at) * 1000
            return query, documents, query_elapsed_ms

        collected: dict[str, tuple[KnowledgeQuery, list[SearchDocument], float]] = {}
        max_workers = max(1, min(len(queries), 4))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_collect_one, query): query.key for query in queries}
            for future in as_completed(future_map):
                query, documents, query_elapsed_ms = future.result()
                collected[query.key] = (query, documents, query_elapsed_ms)

        items: list[KnowledgeItem] = []
        for query in queries:
            _query, documents, query_elapsed_ms = collected[query.key]
            if debug_timing:
                print(
                    f"[WebKnowledge query] plugin={plugin_id} key={query.key} "
                    f"docs={len(documents)} elapsed_ms={query_elapsed_ms:.0f}"
                )
            item_builder = getattr(plugin, "build_web_knowledge_item", None)
            if item_builder is not None:
                built = item_builder(query, documents, active_context.state, config)
                if built is not None:
                    items.append(built)
                    continue
            items.append(
                KnowledgeItem(
                    key=query.key,
                    tab_label=query.title,
                    title=query.title,
                    query=query.query,
                    documents=documents,
                )
            )

        summary_builder = getattr(plugin, 'build_web_knowledge_summary', None)
        if summary_builder is not None:
            summary = str(summary_builder(active_context.state, config) or '').strip()
        else:
            summary = ''
        if not summary:
            summary = f'{plugin.display_name} 外部资料参考'

        bundle = KnowledgeBundle(
            plugin_id=plugin_id,
            display_name=plugin.display_name,
            summary=summary,
            items=items,
            generated_at=datetime.now(),
        )
        self._cached_signature = signature
        self._cached_bundle = bundle
        self._cached_at = now
        if debug_timing:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            print(
                f"[WebKnowledge] plugin={plugin_id} cache_hit=false "
                f"items={len(items)} elapsed_ms={elapsed_ms:.0f}"
            )
        return bundle



def render_knowledge_bundle(bundle: KnowledgeBundle | None) -> str:
    if bundle is None:
        return (
            "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;"
            "background:#12161f;color:#e8ebf1;'>"
            "<h3 style='margin:0 0 8px 0;'>Web Knowledge</h3>"
            "<p style='color:#b8bfcc;'>暂无资料。</p>"
            "</body></html>"
        )
    parts = [
        (
            "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;"
            "background:#12161f;color:#e8ebf1;line-height:1.55;'>"
        ),
    ]
    for item in bundle.items:
        parts.append(
            "<div style='margin:0 0 18px 0;padding:14px 16px;"
            "background:#171d27;border:1px solid #252c38;border-radius:14px;'>"
        )
        parts.append(
            f"<div style='font-size:16px;font-weight:700;margin-bottom:8px;'>"
            f"{_escape_html(item.title)}</div>"
        )
        parts.append(
            f"<div style='margin-bottom:12px;color:#8fa1bb;font-size:12px;'>"
            f"{_escape_html(item.query)}</div>"
        )
        if not item.documents:
            parts.append("<div style='color:#b8bfcc;'>暂无搜索结果。</div></div>")
            continue
        for index, doc in enumerate(item.documents, start=1):
            version = (
                f"<span style='margin-left:8px;color:#98b2ff;'>版本 { _escape_html(doc.patch_version) }</span>"
                if getattr(doc, "patch_version", "")
                else ""
            )
            parts.append(
                "<div style='margin-bottom:14px;padding:12px 12px 10px 12px;"
                "background:#10151d;border:1px solid #202838;border-radius:12px;'>"
                f"<div style='margin-bottom:6px;'>"
                f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
                f"background:#253047;color:#d7e4ff;font-size:11px;'>[{index}] { _escape_html(doc.domain) }</span>"
                f"{version}</div>"
                f"<div style='margin-bottom:6px;font-size:14px;font-weight:600;'>"
                f"<a style='color:#8db4ff;text-decoration:none;' href='{_escape_html(doc.url)}'>"
                f"{_escape_html(doc.title or doc.url)}</a></div>"
                f"<div style='margin-bottom:8px;color:#d7dce6;'>{_escape_html(doc.snippet)}</div>"
                f"<div style='color:#96a0b0;font-size:12px;'>{_escape_html((doc.excerpt or doc.snippet)[:500])}</div>"
                "</div>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    return ''.join(parts)


def render_knowledge_item(bundle: KnowledgeBundle | None, index: int) -> str:
    if bundle is None or not bundle.items:
        return render_knowledge_bundle(None)

    safe_index = max(0, min(index, len(bundle.items) - 1))
    item = bundle.items[safe_index]
    parts = [
        (
            "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;"
            "background:#12161f;color:#e8ebf1;line-height:1.6;'>"
        ),
        (
            "<div style='margin:0 0 18px 0;padding:14px 16px;"
            "background:#171d27;border:1px solid #252c38;border-radius:14px;'>"
        ),
        f"<div style='font-size:20px;font-weight:700;margin-bottom:10px;'>{_escape_html(item.title)}</div>",
    ]

    if not item.documents:
        parts.append("<div style='color:#b8bfcc;'>暂无搜索结果。</div></div></body></html>")
        return "".join(parts)

    for doc in item.documents:
        sections = item.sections
        version = (
            f"<span style='margin-left:8px;color:#98b2ff;'>版本 { _escape_html(doc.patch_version) }</span>"
            if getattr(doc, "patch_version", "")
            else ""
        )
        parts.append(
            "<div style='margin-bottom:14px;padding:14px 14px 12px 14px;"
            "background:#10151d;border:1px solid #202838;border-radius:12px;'>"
            f"<div style='margin-bottom:8px;'>"
            f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
            f"background:#253047;color:#d7e4ff;font-size:11px;'>{_escape_html(doc.domain)}</span>"
            f"{version}</div>"
            f"<div style='margin-bottom:8px;font-size:16px;font-weight:700;'>"
            f"<a style='color:#8db4ff;text-decoration:none;' href='{_escape_html(doc.url)}'>"
            f"{_escape_html(doc.title or doc.url)}</a></div>"
        )
        if doc.snippet and doc.snippet not in (doc.excerpt or ""):
            parts.append(
                f"<div style='margin-bottom:10px;color:#cfd6e4;font-size:13px;'>"
                f"{_escape_html(doc.snippet)}</div>"
            )
        if sections:
            for title, body in sections:
                parts.append(
                    "<div style='margin:10px 0 0 0;padding:10px 12px;"
                    "background:#151b25;border:1px solid #263043;border-radius:10px;'>"
                    f"<div style='margin-bottom:6px;color:#9ec0ff;font-size:12px;font-weight:700;'>{_escape_html(title)}</div>"
                    f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>{_escape_html(body)}</div>"
                    "</div>"
                )
        elif item.fallback_text:
            parts.append(
                f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>"
                f"{_escape_html(item.fallback_text[:1800])}</div>"
            )
        else:
            parts.append(
                f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>"
                f"{_escape_html((doc.excerpt or doc.snippet)[:1800])}</div>"
            )
        parts.append("</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def knowledge_item_tab_label(item: KnowledgeItem) -> str:
    label = str(item.tab_label or "").strip()
    return label or item.title or "资料"



def _sites_from_config(config, plugin_id: str) -> list[SearchSite]:
    global_sites = parse_search_sites_text(str(config.web_knowledge_settings.get('default_sites_text', '')))
    plugin_sites = parse_search_sites_text(str(config.plugin_setting(plugin_id, 'knowledge_search_sites_text', '')))
    return merge_search_sites(global_sites, plugin_sites)



def _escape_html(value: str) -> str:
    return (
        str(value or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )



def _signature_for_queries(plugin_id: str, queries: list[KnowledgeQuery]) -> tuple[Any, ...]:
    packed: list[Any] = [plugin_id]
    for query in queries:
        packed.append((query.key, query.query, tuple((site.domain, site.priority) for site in query.sites)))
    return tuple(packed)
