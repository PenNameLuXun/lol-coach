from __future__ import annotations

import re
import time

from PyQt6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from src.qa_web_search import (
    SearchDocument,
    SearchSite,
    extract_heading_texts,
    extract_meta_description,
    extract_visible_text_excerpt,
    fetch_page_html,
    infer_patch_version,
    parse_search_sites_text,
    sanitize_content_html,
    search_web_for_qa,
)
from src.web_knowledge import KnowledgeItem, KnowledgeQuery


_TFT_TEMPO_TRANSLATIONS = {
    "Fast 8": "速8",
    "Fast 9": "速9",
    "Fast 10": "速10",
    "Slow Roll": "慢D",
    "Reroll": "赌狗追三",
}

_TFT_DIFFICULTY_TRANSLATIONS = {
    "Easy": "简单",
    "Medium": "中等",
    "Hard": "困难",
}


def build_tft_web_knowledge_queries(state, config) -> list[KnowledgeQuery]:
    return [
        KnowledgeQuery(
            key="tft-meta-comps",
            title="当前主流阵容",
            query="current TFT meta comps patch set guide",
        )
    ]


def build_tft_web_knowledge_summary(state, config) -> str:
    round_name = str(state.derived.get("round", "")).strip()
    if round_name:
        return f"当前展示 TFT 主流阵容资料，结合你现在的回合 {round_name} 做参考。"
    return "当前展示 TFT 主流阵容资料，可用来辅助判断运营方向。"


def build_tft_web_knowledge_item(query: KnowledgeQuery, documents: list[SearchDocument], state, config) -> KnowledgeItem:
    sections, fallback_text = _build_tft_sections(documents)
    return KnowledgeItem(
        key=query.key,
        tab_label="主流阵容",
        title=query.title,
        query=query.query,
        documents=documents,
        sections=sections,
        fallback_text=fallback_text,
    )


def collect_tft_web_knowledge_documents(query: KnowledgeQuery, state, config) -> list[SearchDocument]:
    timeout_seconds = int(getattr(config, "web_knowledge_timeout_seconds", 8))
    engine = str(getattr(config, "web_knowledge_search_engine", "google"))
    debug_timing = bool(getattr(config, "_debug_timing", False))
    sites = _knowledge_sites(config)

    for site in sites:
        started_at = time.perf_counter()
        doc = _collect_from_known_site(
            site,
            timeout_seconds,
            accept_language=config.web_knowledge_accept_language,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        if debug_timing:
            print(
                f"[WebKnowledge site] plugin=tft site={site.domain} mode=direct "
                f"ok={doc is not None} elapsed_ms={elapsed_ms:.0f}"
            )
        if doc is not None:
            return [doc]
        search_started_at = time.perf_counter()
        fallback = search_web_for_qa(
            question=query.query,
            engine=engine,
            sites=[site],
            timeout_seconds=timeout_seconds,
            max_results_per_site=1,
            max_pages=1,
            stop_after_first_site_success=True,
            accept_language=config.web_knowledge_accept_language,
        )
        search_elapsed_ms = (time.perf_counter() - search_started_at) * 1000
        if debug_timing:
            print(
                f"[WebKnowledge site] plugin=tft site={site.domain} mode=search "
                f"docs={len(fallback)} elapsed_ms={search_elapsed_ms:.0f}"
            )
        if fallback:
            return fallback[:1]
    return []


def populate_tft_web_knowledge_window(window, bundle, state, config) -> bool:
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    browser = _create_browser()
    browser.setHtml(_render_tft_bundle(bundle))
    layout.addWidget(browser)

    window.set_header(
        title=f"{bundle.display_name} Web Knowledge",
        summary=bundle.summary or "暂无摘要。",
        updated_text=f"更新于 {bundle.generated_at.strftime('%H:%M:%S')}",
    )
    window.set_content_widget(root)
    return True


def _collect_from_known_site(
    site: SearchSite,
    timeout_seconds: int,
    *,
    accept_language: str,
) -> SearchDocument | None:
    domain = site.domain.lower().removeprefix("www.")
    if domain == "tactics.tools":
        candidates = [("TFT Meta Comps", "https://tactics.tools/team-comps")]
    elif domain == "lolchess.gg":
        candidates = [("TFT Meta", "https://lolchess.gg/meta")]
    elif domain == "mobalytics.gg":
        candidates = [("TFT Team Comps", "https://mobalytics.gg/tft/team-comps")]
    elif domain == "tft.vinky.cn":
        candidates = [("TFT 阵容", "https://tft.vinky.cn/")]
    else:
        return None

    for title_hint, url in candidates:
        html = fetch_page_html(
            url=url,
            timeout_seconds=timeout_seconds,
            accept_language=accept_language,
        )
        if not html:
            continue
        title, snippet, excerpt, sections, patch_version = _parse_tft_site_html(domain, title_hint, html)
        if not excerpt and not snippet:
            continue
        return SearchDocument(
            domain=site.domain,
            priority=site.priority,
            title=title or title_hint,
            url=url,
            snippet=snippet,
            excerpt=excerpt or snippet,
            patch_version=patch_version or infer_patch_version(title, snippet, excerpt, url),
            metadata={
                "sections": sections,
                "fallback_text": snippet or title or title_hint,
            },
        )
    return None


def _build_tft_sections(documents: list[SearchDocument]) -> tuple[list[tuple[str, str]], str]:
    if not documents:
        return [], ""
    doc = documents[0]
    metadata = doc.metadata or {}
    structured_sections = metadata.get("sections")
    if isinstance(structured_sections, list) and structured_sections:
        fallback = str(metadata.get("fallback_text") or doc.snippet or doc.title).strip()
        return [(str(title), str(body)) for title, body in structured_sections if str(body).strip()], fallback

    cleaned = _clean_source_text(doc.excerpt or doc.snippet)
    if not _looks_readable_text(cleaned):
        fallback = _clean_source_text(doc.snippet or doc.title)
        return [], fallback

    sentences = _split_sentences(cleaned)
    if not sentences:
        fallback = _clean_source_text(doc.snippet or doc.title)
        return [], fallback

    sections: list[tuple[str, str]] = []
    _append_section(sections, "主流阵容", _pick_best(sentences, ("阵容", "comp", "carry", "前排", "后排", "4-cost", "5-cost")))
    _append_section(sections, "运营思路", _pick_best(sentences, ("经济", "利息", "升级", "搜牌", "运营", "fast 8", "roll", "level")))
    _append_section(sections, "站位要点", _pick_best(sentences, ("站位", "position", "角落", "缩角", "切后排", "保护", "前后排")))

    fallback = _clean_source_text(doc.snippet or doc.title)
    return sections[:3], fallback


def _parse_tft_site_html(
    domain: str,
    title_hint: str,
    html: str,
) -> tuple[str, str, str, list[tuple[str, str]], str]:
    clean_html = sanitize_content_html(html)
    title = _extract_title(html) or title_hint
    meta = extract_meta_description(html) or extract_meta_description(clean_html)
    headings = extract_heading_texts(clean_html, max_items=8)
    visible = _safe_visible_excerpt(clean_html)

    if domain == "tactics.tools":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Comps", "Tier", "Items", "Augments")), visible[:650])
    elif domain == "lolchess.gg":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Meta", "Comps", "Items", "Placement")), visible[:650])
    elif domain == "mobalytics.gg":
        comps = _extract_mobalytics_comps(clean_html)
        if comps:
            patch = _infer_common_patch(comps)
            sections = _build_mobalytics_sections(comps)
            summary = _compact_text(meta or " / ".join(headings[:3]) or title)
            excerpt = "\n".join(
                [summary] + [f"{name}: {body}" for name, body in sections[:4]]
            ).strip()
            return title, summary, excerpt, sections, patch
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Comps", "Items", "Positioning", "Guide")), visible[:650])
    else:
        excerpt = _join_excerpt_parts(meta, " / ".join(headings[:4]), visible[:650])
    return title, meta, excerpt, [], infer_patch_version(title, meta, excerpt)


def _render_tft_bundle(bundle) -> str:
    item = bundle.items[0] if bundle.items else None
    if item is None:
        return "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#12161f;color:#e8ebf1;'>暂无资料。</body></html>"

    parts = [
        "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#12161f;color:#e8ebf1;line-height:1.6;'>",
        "<div style='margin:0 0 18px 0;padding:14px 16px;background:#171d27;border:1px solid #252c38;border-radius:14px;'>",
        f"<div style='font-size:20px;font-weight:700;margin-bottom:10px;'>{_escape_html(item.title)}</div>",
    ]
    if not item.documents:
        parts.append("<div style='color:#b8bfcc;'>暂无搜索结果。</div></div></body></html>")
        return "".join(parts)

    doc = item.documents[0]
    version = (
        f"<span style='margin-left:8px;color:#98b2ff;'>版本 { _escape_html(doc.patch_version) }</span>"
        if doc.patch_version
        else ""
    )
    parts.append(
        "<div style='margin-bottom:14px;padding:14px 14px 12px 14px;background:#10151d;border:1px solid #202838;border-radius:12px;'>"
        f"<div style='margin-bottom:8px;'><span style='display:inline-block;padding:2px 8px;border-radius:999px;background:#253047;color:#d7e4ff;font-size:11px;'>{_escape_html(doc.domain)}</span>{version}</div>"
        f"<div style='margin-bottom:8px;font-size:16px;font-weight:700;'><a style='color:#8db4ff;text-decoration:none;' href='{_escape_html(doc.url)}'>{_escape_html(doc.title or doc.url)}</a></div>"
    )
    if doc.snippet and doc.snippet not in (doc.excerpt or ""):
        parts.append(f"<div style='margin-bottom:10px;color:#cfd6e4;font-size:13px;'>{_escape_html(doc.snippet)}</div>")
    if item.sections:
        for title, body in item.sections:
            parts.append(
                "<div style='margin:10px 0 0 0;padding:10px 12px;background:#151b25;border:1px solid #263043;border-radius:10px;'>"
                f"<div style='margin-bottom:6px;color:#9ec0ff;font-size:12px;font-weight:700;'>{_escape_html(title)}</div>"
                f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>{_escape_html(body)}</div>"
                "</div>"
            )
    elif item.fallback_text:
        parts.append(f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>{_escape_html(item.fallback_text[:1800])}</div>")
    else:
        parts.append(f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;'>{_escape_html((doc.excerpt or doc.snippet)[:1800])}</div>")
    parts.append("</div></div></body></html>")
    return "".join(parts)


def _append_section(sections: list[tuple[str, str]], title: str, body: str) -> None:
    if body:
        sections.append((title, body))


def _pick_best(sentences: list[str], keywords: tuple[str, ...]) -> str:
    matched = [s for s in sentences if any(k.lower() in s.lower() for k in keywords)]
    if matched:
        return " ".join(matched[:2]).strip()
    return ""


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s+|\n+", text)
    seen: set[str] = set()
    sentences: list[str] = []
    for part in parts:
        sentence = _clean_source_text(part)
        if sentence and sentence not in seen:
            seen.add(sentence)
            sentences.append(sentence)
    return sentences


def _clean_source_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b([A-Za-z0-9_./:-]+\s*){10,}", " ", cleaned)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\s.,:;!?%+\-()/&]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _looks_readable_text(text: str) -> bool:
    if len(text) < 30:
        return False
    weird_ratio = len(re.findall(r"[?]{2,}|[,]{2,}|[+]{3,}|[#%&]{2,}", text)) / max(1, len(text))
    if weird_ratio > 0.01:
        return False
    alpha_num_ratio = len(re.findall(r"[A-Za-z0-9]", text)) / max(1, len(text))
    cjk_ratio = len(re.findall(r"[\u4e00-\u9fff]", text)) / max(1, len(text))
    return alpha_num_ratio + cjk_ratio > 0.45


def _knowledge_sites(config) -> list[SearchSite]:
    text = ""
    if config is not None:
        text = str(config.plugin_setting("tft", "knowledge_search_sites_text", ""))
    sites = parse_search_sites_text(text)
    preferred_order = {
        "mobalytics.gg": 0,
        "tactics.tools": 1,
        "lolchess.gg": 2,
    }
    ordered = sorted(
        sites,
        key=lambda site: (
            preferred_order.get(site.domain.lower().removeprefix("www."), 99),
            -site.priority,
            site.domain,
        ),
    )
    return ordered


def _extract_mobalytics_comps(html: str) -> list[dict[str, str]]:
    visible = _compact_text(extract_visible_text_excerpt(html))
    if not visible:
        return []

    anchor = visible.find("TFT Meta Comps in Set")
    if anchor >= 0:
        visible = visible[anchor:]

    start = visible.find("Create comp")
    if start >= 0:
        visible = visible[start + len("Create comp") :].strip()

    comps: list[dict[str, str]] = []
    for chunk in visible.split("Copy team code"):
        cleaned_chunk = _compact_text(chunk)
        if not cleaned_chunk:
            continue
        match = re.match(
            r"(?P<name>.+?)\s+"
            r"(?P<patch>\d{2}\.\d)\s+"
            r"(?P<tempo>(?:Fast \d+|Slow Roll|Reroll|Fast 9|Fast 10|Level \d+))\s+"
            r"(?P<difficulty>Easy|Medium|Hard)\s+"
            r"(?P<units>.+)$",
            cleaned_chunk,
            re.IGNORECASE,
        )
        if not match:
            continue
        units_text = _compact_text(match.group("units"))
        normalized_units = _normalize_unit_line(units_text)
        if len(normalized_units) < 12:
            continue
        comps.append(
            {
                "name": _translate_tft_term(_compact_text(match.group("name"))),
                "patch": _compact_text(match.group("patch")),
                "tempo": _translate_tft_term(_compact_text(match.group("tempo"))),
                "difficulty": _translate_tft_term(_compact_text(match.group("difficulty"))),
                "units": _translate_tft_units(normalized_units),
            }
        )
        if len(comps) >= 5:
            break
    return comps


def _normalize_unit_line(text: str) -> str:
    cleaned = _compact_text(text).replace(" & ", " / ")
    cleaned = re.sub(r"\bCopy team code\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _build_mobalytics_sections(comps: list[dict[str, str]]) -> list[tuple[str, str]]:
    if not comps:
        return []

    top_names = " / ".join(comp["name"] for comp in comps[:3])
    sections: list[tuple[str, str]] = [("主流阵容概览", f"当前优先关注：{top_names}")]
    for index, comp in enumerate(comps[:4], start=1):
        sections.append(
            (
                f"推荐阵容 {index}",
                (
                    f"{comp['name']}\n"
                    f"版本：{comp['patch']}\n"
                    f"节奏：{comp['tempo']}\n"
                    f"难度：{comp['difficulty']}\n"
                    f"完整阵容：{comp['units']}"
                ),
            )
        )
    return sections


def _infer_common_patch(comps: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for comp in comps:
        patch = comp.get("patch", "")
        if not patch:
            continue
        counts[patch] = counts.get(patch, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _compact_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _translate_tft_term(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if value in _TFT_TEMPO_TRANSLATIONS:
        return _TFT_TEMPO_TRANSLATIONS[value]
    if value in _TFT_DIFFICULTY_TRANSLATIONS:
        return _TFT_DIFFICULTY_TRANSLATIONS[value]
    return value


def _translate_tft_units(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value.replace(" / ", " / ")


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(?P<title>.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clean_source_text(re.sub(r"<[^>]+>", " ", match.group("title")))


def _pick_heading_block(headings: list[str], keywords: tuple[str, ...]) -> str:
    matched = [heading for heading in headings if any(k.lower() in heading.lower() for k in keywords)]
    return " / ".join(matched[:4])


def _join_excerpt_parts(*parts: str) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = _clean_source_text(part)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(cleaned)
    return " ".join(values)


def _safe_visible_excerpt(html: str) -> str:
    visible = _clean_source_text(extract_visible_text_excerpt(html))
    if not visible:
        return ""
    noisy_tokens = (
        "matchmedia",
        "theme dark",
        "inprogress",
        "top:0",
        "left:0",
        "width:100%",
        "javascript",
        "window.",
        "document.",
    )
    lowered = visible.lower()
    if any(token in lowered for token in noisy_tokens):
        return ""
    return visible


def _create_browser() -> QTextBrowser:
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setFrameShape(QTextBrowser.Shape.NoFrame)
    browser.setStyleSheet(
        """
        QTextBrowser {
            background: #12161f;
            border: none;
            padding: 8px;
            color: #e8ebf1;
            selection-background-color: #274b8a;
        }
        QScrollBar:vertical {
            background: #12161f;
            width: 10px;
            margin: 4px 0 4px 0;
        }
        QScrollBar::handle:vertical {
            background: #2d3644;
            min-height: 28px;
            border-radius: 5px;
        }
        """
    )
    return browser


def _escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
