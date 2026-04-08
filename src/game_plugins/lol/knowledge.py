from __future__ import annotations

import json
import re
import time

from PyQt6.QtWidgets import QTabWidget, QTextBrowser

from src.ui.web_routes import build_lol_routes, build_lol_team_routes

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


_SUMMONER_SPELL_TRANSLATIONS = {
    "Flash": "闪现",
    "Heal": "治疗",
    "Barrier": "屏障",
    "Ghost": "疾跑",
    "Ignite": "点燃",
    "Teleport": "传送",
    "Exhaust": "虚弱",
    "Cleanse": "净化",
    "Smite": "惩戒",
}

_RUNE_STYLE_TRANSLATIONS = {
    "Precision": "精密",
    "Domination": "主宰",
    "Sorcery": "巫术",
    "Resolve": "坚决",
    "Inspiration": "启迪",
}

_RUNE_PERK_TRANSLATIONS = {
    "Lethal Tempo": "致命节奏",
    "Fleet Footwork": "迅捷步法",
    "Conqueror": "征服者",
    "Press the Attack": "强攻",
    "Electrocute": "电刑",
    "Hail of Blades": "丛刃",
    "Arcane Comet": "奥术彗星",
    "Phase Rush": "相位猛冲",
    "Grasp of the Undying": "不灭之握",
    "Aftershock": "余震",
    "First Strike": "先攻",
    "Triple Tonic": "三重药剂",
    "Cash Back": "回本",
    "Presence of Mind": "气定神闲",
    "Cut Down": "砍倒",
    "Legend: Bloodline": "传说：血统",
}

_LOL_ROLE_TRANSLATIONS = {
    "Top": "上单",
    "Jungle": "打野",
    "Mid": "中单",
    "ADC": "下路",
    "Support": "辅助",
}

_WZSTATS_PHRASE_TRANSLATIONS = {
    "Steady": "平稳成型",
    "Early": "前期强势",
    "Mid Game": "中期发力",
    "Late Game": "后期大核",
    "High Elo": "高分段更强",
    "All Elo": "全分段通用",
    "Low Elo": "低分段更容易发挥",
    "Moderate": "中等难度",
    "Hard": "上手较难",
    "Easy": "容易上手",
    "Consistent win rate across all game lengths": "各个时长段表现都比较稳定",
    "Thrives in Diamond+": "在钻石以上分段更容易发挥",
    "Rewards mechanical skill and game knowledge": "更吃熟练度和操作理解",
    "Performs equally well across all ranks": "不同分段都能稳定发挥",
    "Rewards some practice": "需要一定练习后效果更好",
    "noticeable improvement after a few games": "熟练几局后胜率提升明显",
    "Punish": "抓他失误",
    "Avoid": "需要避免",
    "Respect": "重点提防",
    "Attack after": "在……之后反打",
    "and force short trades": "并尽量打短换血",
    "around his cooldowns": "围绕他的技能冷却做消耗",
    "long extended fights": "长时间拉扯战",
    "once": "一旦",
    "has his first crit item": "做出第一件暴击装",
    "level 6 all-in": "六级一套爆发",
    "when the wave is on his side": "当兵线在他那边时",
    "Wind Wall": "风墙",
    "crit item": "暴击装",
}


def build_lol_web_knowledge_queries(state, config) -> list[KnowledgeQuery]:
    include_enemy = bool(config.plugin_setting("lol", "knowledge_include_enemy_champions", False))
    champions = _knowledge_champions(state.raw_data, include_enemy=include_enemy)
    max_champions = int(config.plugin_setting("lol", "knowledge_max_champions", 5) or 5)
    queries: list[KnowledgeQuery] = []
    for champion in champions[: max(1, max_champions)]:
        queries.append(
            KnowledgeQuery(
                key=f"champion:{champion}",
                title=f"{champion} 玩法参考",
                query=f"League of Legends {champion} build guide combos lane tips current patch",
            )
        )
    return queries


def build_lol_web_knowledge_summary(state, config) -> str:
    include_enemy = bool(config.plugin_setting("lol", "knowledge_include_enemy_champions", False))
    champions = _knowledge_champions(state.raw_data, include_enemy=include_enemy)
    max_champions = int(config.plugin_setting("lol", "knowledge_max_champions", 5) or 5)
    shown = champions[: max(1, max_champions)]
    return f"当前对局英雄资料，优先展示：{'、'.join(shown)}。"


def build_lol_web_knowledge_item(query: KnowledgeQuery, documents: list[SearchDocument], state, config) -> KnowledgeItem:
    champion = query.title.replace("玩法参考", "").strip() or query.title
    sections, fallback_text = _build_lol_sections(documents)
    return KnowledgeItem(
        key=query.key,
        tab_label=champion,
        title=query.title,
        query=query.query,
        documents=documents,
        sections=sections,
        fallback_text=fallback_text,
    )


def collect_lol_web_knowledge_documents(query: KnowledgeQuery, state, config) -> list[SearchDocument]:
    champion = _champion_from_query(query)
    if not champion:
        return []
    timeout_seconds = int(getattr(config, "web_knowledge_timeout_seconds", 8))
    engine = str(getattr(config, "web_knowledge_search_engine", "google"))
    debug_timing = bool(getattr(config, "_debug_timing", False))
    sites = _knowledge_sites(config)
    best_doc: SearchDocument | None = None
    best_score = -1

    for site in sites:
        site_started_at = time.perf_counter()
        doc = _collect_from_known_site(
            champion,
            site,
            timeout_seconds,
            accept_language=config.web_knowledge_accept_language,
        )
        if debug_timing:
            elapsed_ms = (time.perf_counter() - site_started_at) * 1000
            print(
                f"[WebKnowledge site] plugin=lol champion={champion} site={site.domain} "
                f"mode=direct ok={doc is not None} elapsed_ms={elapsed_ms:.0f}"
            )
        if doc is not None:
            score = _document_quality_score(doc)
            if score > best_score:
                best_doc = doc
                best_score = score
            if score >= 40:
                return [doc]

    if best_doc is not None:
        return [best_doc]

    for site in sites:
        site_started_at = time.perf_counter()
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
        if debug_timing:
            elapsed_ms = (time.perf_counter() - site_started_at) * 1000
            print(
                f"[WebKnowledge site] plugin=lol champion={champion} site={site.domain} "
                f"mode=search docs={len(fallback)} elapsed_ms={elapsed_ms:.0f}"
            )
        if fallback:
            return fallback[:1]
    return []


def populate_lol_web_knowledge_window(window, bundle, state, config) -> bool:
    if config is not None:
        embed_mode = str(config.web_knowledge_settings.get("mode", "embed")).strip().lower()
        if embed_mode == "embed" and hasattr(window, "load_routes"):
            return _populate_lol_embed(window, bundle, state, config)
    return _populate_lol_text(window, bundle, state, config)


def _populate_lol_embed(window, bundle, state, config) -> bool:
    include_enemy = bool(config.plugin_setting("lol", "knowledge_include_enemy_champions", False))
    champions = _knowledge_champions(state.raw_data, include_enemy=include_enemy)
    max_champions = int(config.plugin_setting("lol", "knowledge_max_champions", 5) or 5)
    champions = champions[: max(1, max_champions)]
    if not champions:
        return False
    embed_sites = config.plugin_setting("lol", "knowledge_embed_sites", None)
    preferred_site = embed_sites[0] if isinstance(embed_sites, list) and embed_sites else None
    routes = build_lol_team_routes(champions, site=preferred_site)
    if not routes:
        return False
    names = "、".join(champions)
    window.load_routes(
        routes,
        title=f"队伍英雄资料",
        summary=bundle.summary or f"当前展示：{names}",
        plugin_id="lol",
    )
    return True


def _populate_lol_text(window, bundle, state, config) -> bool:
    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    tabs.tabBar().setExpanding(False)
    tabs.setStyleSheet(
        """
        QTabWidget::pane {
            border: 1px solid #252c38;
            border-radius: 14px;
            background: #12161f;
            top: -1px;
        }
        QTabBar::tab {
            background: #171d27;
            color: #cfd6e4;
            padding: 8px 14px;
            margin-right: 6px;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            border: 1px solid #2c3646;
        }
        QTabBar::tab:selected {
            background: #24364f;
            color: #f6f7fb;
            border-color: #4d78b8;
        }
        """
    )

    for item in bundle.items:
        browser = _create_browser()
        browser.setHtml(_render_lol_item(item))
        tabs.addTab(browser, item.tab_label or item.title)

    window.set_header(
        title=f"{bundle.display_name} Web Knowledge",
        summary=bundle.summary or "暂无摘要。",
        updated_text=f"更新于 {bundle.generated_at.strftime('%H:%M:%S')}",
    )
    window.set_content_widget(tabs)
    return True


def _collect_from_known_site(
    champion: str,
    site: SearchSite,
    timeout_seconds: int,
    *,
    accept_language: str,
) -> SearchDocument | None:
    domain = site.domain.lower().removeprefix("www.")
    slug = _slugify_name(champion)
    candidates: list[str] = []
    if domain == "op.gg":
        candidates = [f"https://www.op.gg/champions/{slug}/build", f"https://www.op.gg/champions/{slug}/counters"]
    elif domain == "u.gg":
        candidates = [f"https://u.gg/lol/champions/{slug}/build", f"https://u.gg/lol/champions/{slug}/counter"]
    elif domain == "leagueofgraphs.com":
        candidates = [f"https://www.leagueofgraphs.com/champions/builds/{slug}"]
    elif domain == "mobalytics.gg":
        candidates = [f"https://mobalytics.gg/lol/champions/{slug}/build"]
    elif domain == "origin-lol.wzstats.gg":
        candidates = [
            f"https://origin-lol.wzstats.gg/en/champions/{slug}/performance",
            f"https://origin-lol.wzstats.gg/en/champions/{slug}/against",
        ]
    else:
        return None

    for url in candidates:
        html = fetch_page_html(
            url=url,
            timeout_seconds=timeout_seconds,
            accept_language=accept_language,
        )
        if not html:
            continue
        title, snippet, excerpt, metadata = _parse_lol_site_html(domain, champion, html)
        if not excerpt and not snippet:
            continue
        return SearchDocument(
            domain=site.domain,
            priority=site.priority,
            title=title or f"{champion} Build",
            url=url,
            snippet=snippet,
            excerpt=excerpt or snippet,
            patch_version=str(metadata.get("patch_version") or infer_patch_version(title, snippet, excerpt, url)),
            metadata=metadata,
        )
    return None


def _build_lol_sections(documents: list[SearchDocument]) -> tuple[list[tuple[str, str]], str]:
    if not documents:
        return [], ""
    doc = documents[0]
    structured_sections = doc.metadata.get("sections") if isinstance(doc.metadata, dict) else None
    if isinstance(structured_sections, list) and structured_sections:
        normalized = [(str(title), str(body)) for title, body in structured_sections if str(title).strip() and str(body).strip()]
        fallback = str(doc.metadata.get("fallback_text") or doc.snippet or doc.title).strip()
        return normalized, fallback
    cleaned = _clean_source_text(doc.excerpt or doc.snippet)
    if not _looks_readable_text(cleaned):
        fallback = _clean_source_text(doc.snippet or doc.title)
        return [], fallback

    sentences = _split_sentences(cleaned)
    if not sentences:
        fallback = _clean_source_text(doc.snippet or doc.title)
        return [], fallback

    sections: list[tuple[str, str]] = []
    _append_section(sections, "主流出装", _pick_best(sentences, ("出装", "build", "item", "装备", "rune", "符文", "boots")))
    _append_section(sections, "玩法思路", _pick_best(sentences, ("玩法", "trade", "poke", "fight", "拉扯", "团战", "节奏", "damage")))
    _append_section(sections, "小技巧", _pick_best(sentences, ("技巧", "tip", "combo", "连招", "注意", "利用", "window", "avoid")))
    _append_section(sections, "对线提醒", _pick_best(sentences, ("对线", "lane", "counter", "early", "前期", "六级", "三级", "兵线")))

    fallback = _clean_source_text(doc.snippet or doc.title)
    return sections[:4], fallback


def _parse_lol_site_html(domain: str, champion: str, html: str) -> tuple[str, str, str, dict[str, object]]:
    if domain == "u.gg":
        structured = _parse_ugg_structured(champion, html)
        if structured is not None:
            return structured
    if domain == "origin-lol.wzstats.gg":
        structured = _parse_wzstats_structured(champion, html)
        if structured is not None:
            return structured

    clean_html = sanitize_content_html(html)
    title = _extract_title(html) or f"{champion} Build"
    meta = extract_meta_description(html) or extract_meta_description(clean_html)
    headings = extract_heading_texts(clean_html, max_items=6)
    visible = _safe_visible_excerpt(clean_html)

    if domain == "op.gg":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Build", "Counter", "Runes", "Items")))
    elif domain == "u.gg":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Build", "Runes", "Counters", "Tips")))
    elif domain == "leagueofgraphs.com":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Build", "Skill", "Counters", "Spells")), visible[:500])
    elif domain == "mobalytics.gg":
        excerpt = _join_excerpt_parts(meta, _pick_heading_block(headings, ("Build", "Runes", "Combos", "Tips")))
    elif domain == "origin-lol.wzstats.gg":
        excerpt = _join_excerpt_parts(
            meta,
            _pick_heading_block(headings, ("出装", "符文", "Counter", "Build", "Tier", "技能")),
            visible[:600],
        )
    else:
        excerpt = _join_excerpt_parts(meta, " / ".join(headings[:4]), visible[:500])
    metadata = {
        "sections": [],
        "fallback_text": _clean_source_text(meta or excerpt or title),
        "quality": 30 if excerpt else 10,
    }
    return title, meta, excerpt, metadata


def _parse_wzstats_structured(champion: str, html: str) -> tuple[str, str, str, dict[str, object]] | None:
    clean_html = sanitize_content_html(html)
    title = _extract_title(html) or f"{champion} Performance"
    visible = _compact_text(extract_visible_text_excerpt(clean_html))
    if "How to Counter" in visible or "Against" in title or "Counter" in title or "Playing Against" in visible:
        title = f"{champion} Against Guide"
    elif "Performance" not in title:
        title = f"{champion} Performance"
    meta = extract_meta_description(html) or extract_meta_description(clean_html)
    if not visible:
        return None

    sections: list[tuple[str, str]] = []

    overall = _match_text(visible, rf"{re.escape(champion)} Overall Performance in ([A-Za-z]+)")
    if overall:
        sections.append(("推荐位置", _translate_lol_term(overall)))

    power_spike = _match_block(visible, "Power Spike", ("Elo", "Skill Curve", "Win Rate by Game Length"))
    if power_spike:
        sections.append(("强势期", _translate_wzstats_phrase(power_spike)))

    elo_fit = _match_block(visible, "Elo", ("Skill Curve", "Win Rate by Game Length", "Role Performance"))
    if elo_fit:
        sections.append(("适合分段", _translate_wzstats_phrase(elo_fit)))

    skill_curve = _match_block(
        visible,
        "Skill Curve",
        ("Win Rate by Game Length", "Role Performance", "Performance"),
        from_end=True,
    )
    if skill_curve:
        sections.append(("上手难度", _translate_wzstats_phrase(skill_curve)))

    performance = _collect_named_metrics(visible, ("Win Rate", "Carry Score"))
    combat = _collect_named_metrics(visible, ("KDA", "Kills/game", "Deaths/game", "Assists/game", "Damage/game"))
    economy = _collect_named_metrics(visible, ("CS/min", "Gold/min", "Vision Score"))
    if performance:
        sections.append(("核心数据", performance))
    if combat:
        sections.append(("战斗表现", combat))
    if economy:
        sections.append(("经济与视野", economy))

    if "Against" in title or "Counter" in title or "Playing Against" in title:
        punish = _match_block(visible, "Punish", ("Avoid", "Respect", "Summary", "Tips"))
        avoid = _match_block(visible, "Avoid", ("Respect", "Summary", "Tips"))
        respect = _match_block(visible, "Respect", ("Summary", "Tips"))
        if punish:
            sections.append(("对线提醒", _translate_wzstats_phrase(punish)))
        if avoid:
            sections.append(("需要避免", _translate_wzstats_phrase(avoid)))
        if respect:
            sections.append(("关键时机", _translate_wzstats_phrase(respect)))

    if not sections:
        return None

    patch = infer_patch_version(title, meta, visible)
    snippet = meta or "；".join(body for _, body in sections[:2])
    excerpt = " | ".join(f"{name}: {body}" for name, body in sections)
    metadata = {
        "sections": sections,
        "fallback_text": snippet or title,
        "quality": 90,
        "source": "wzstats",
        "patch_version": patch,
        "champion": champion,
    }
    return title, snippet, excerpt, metadata


def _parse_ugg_structured(champion: str, html: str) -> tuple[str, str, str, dict[str, object]] | None:
    data = _extract_ugg_ssr_data(html)
    if not data:
        return None

    overview_data = _first_ugg_dataset(data, "overview_", required_substring="recommended::")
    ranking_data = _first_ugg_dataset(data, "rankings_")
    if not overview_data:
        return None

    items_map = _first_ugg_mapping(data, "legacy-items.json")
    summoner_map = _first_ugg_mapping(data, "summoner.json")
    champions_map = _first_ugg_mapping(data, "backup-champions.json")
    runes_tree = _first_ugg_mapping(data, "runesReforged.json")

    overview_role_key, overview_leaf = _select_ugg_role_leaf(overview_data, ("rec_core_items", "rec_runes", "rec_skills"))
    ranking_role_key, ranking_leaf = _select_ugg_role_leaf(
        ranking_data,
        ("counters", "win_rate", "pick_rate"),
        preferred_role_key=overview_role_key,
    )
    if not overview_leaf:
        return None

    patch = _extract_ugg_patch_version(data)
    item_names = _map_ids_to_names(overview_leaf.get("rec_core_items", {}).get("ids", []), items_map)
    starting_items = _map_ids_to_names(overview_leaf.get("rec_starting_items", {}).get("ids", []), items_map)
    optional_items = _extract_ugg_optional_items(overview_leaf, items_map, exclude=item_names + starting_items)
    summoner_spells = _map_ids_to_names(overview_leaf.get("rec_summoner_spells", {}).get("ids", []), summoner_map)
    rune_text = _format_ugg_runes(overview_leaf.get("rec_runes", {}), runes_tree)
    skill_text = _format_skill_order(overview_leaf.get("rec_skills", {}))
    counter_sections = _format_ugg_counter_sections(ranking_leaf.get("counters", []), champions_map)
    stats_text = _format_ugg_stats(ranking_leaf or overview_leaf)
    role_label = _format_ugg_role_label(overview_role_key or ranking_role_key)

    sections: list[tuple[str, str]] = []
    if patch:
        sections.append(("版本", patch))
    if role_label:
        sections.append(("主位置", role_label))
    if starting_items:
        sections.append(("出门装", " + ".join(starting_items)))
    if item_names:
        sections.append(("核心三件", " -> ".join(item_names)))
    if optional_items:
        sections.append(("可选装备", " / ".join(optional_items[:6])))
    if rune_text:
        sections.append(("符文", rune_text))
    if summoner_spells:
        sections.append(("召唤师技能", " + ".join(summoner_spells)))
    if skill_text:
        sections.append(("技能加点", skill_text))
    sections.extend(counter_sections)
    if stats_text:
        sections.append(("数据概览", stats_text))

    title = f"{champion} Build"
    if patch:
        title += f" Patch {patch}"
    snippet_parts = [stats_text, rune_text]
    snippet = "；".join(part for part in snippet_parts if part)[:280]
    excerpt = " | ".join(f"{title}: {body}" for title, body in sections)
    metadata = {
        "sections": sections,
        "fallback_text": snippet or excerpt or title,
        "quality": 120 if sections else 70,
        "source": "u.gg-ssr",
        "patch_version": patch,
        "champion": champion,
    }
    return title, snippet or title, excerpt, metadata


def _render_lol_item(item: KnowledgeItem) -> str:
    doc = item.documents[0] if item.documents else None
    parts = [
        "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#12161f;color:#e8ebf1;line-height:1.6;'>",
        "<div style='margin:0;padding:14px 16px;background:#171d27;border:1px solid #252c38;border-radius:14px;'>",
        f"<div style='font-size:20px;font-weight:700;margin-bottom:12px;'>{_escape_html(item.title)}</div>",
    ]
    if not item.documents:
        parts.append("<div style='color:#b8bfcc;'>暂无搜索结果。</div></div></body></html>")
        return "".join(parts)

    version = (
        f"<span style='margin-left:8px;color:#98b2ff;'>版本 { _escape_html(doc.patch_version) }</span>"
        if doc.patch_version
        else ""
    )
    parts.append(
        "<div style='margin-bottom:14px;padding:12px 14px;background:#10151d;border:1px solid #202838;border-radius:12px;'>"
        f"<div style='margin-bottom:8px;'><span style='display:inline-block;padding:3px 8px;border-radius:999px;background:#253047;color:#d7e4ff;font-size:11px;'>{_escape_html(doc.domain)}</span>{version}</div>"
        f"<div style='margin-bottom:6px;font-size:16px;font-weight:700;'><a style='color:#8db4ff;text-decoration:none;' href='{_escape_html(doc.url)}'>{_escape_html(doc.title or doc.url)}</a></div>"
    )
    if doc.snippet and not item.sections:
        parts.append(f"<div style='margin-bottom:10px;color:#cfd6e4;font-size:13px;'>{_escape_html(doc.snippet)}</div>")
    if item.sections:
        hero_summary = _build_lol_hero_summary(item.sections)
        if hero_summary:
            parts.append(
                "<div style='margin:0 0 12px 0;padding:10px 12px;background:#141a24;border:1px solid #222c3b;border-radius:12px;"
                "color:#dbe1ea;font-size:13px;line-height:1.7;'>"
                f"{hero_summary}"
                "</div>"
            )
        for title, body in item.sections:
            parts.append(_render_lol_section_card(title, body))
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
        text = str(config.plugin_setting("lol", "knowledge_search_sites_text", ""))
    allowed = {"u.gg", "op.gg", "leagueofgraphs.com", "mobalytics.gg", "origin-lol.wzstats.gg"}
    sites = parse_search_sites_text(text)
    filtered = [site for site in sites if site.domain.lower().removeprefix("www.") in allowed]
    domain_rank = {
        "origin-lol.wzstats.gg": 0,
        "u.gg": 1,
        "leagueofgraphs.com": 2,
        "op.gg": 3,
        "mobalytics.gg": 4,
    }
    filtered.sort(
        key=lambda site: (
            domain_rank.get(site.domain.lower().removeprefix("www."), 99),
            -site.priority,
        )
    )
    return filtered or [
        SearchSite(domain="origin-lol.wzstats.gg", priority=110),
        SearchSite(domain="u.gg", priority=100),
        SearchSite(domain="leagueofgraphs.com", priority=80),
        SearchSite(domain="op.gg", priority=70),
    ]


def _champion_from_query(query: KnowledgeQuery) -> str:
    if query.key.startswith("champion:"):
        return query.key.split(":", 1)[1].strip()
    return query.title.replace("玩法参考", "").strip()


def _slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower())
    return slug.strip("-")


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


def _knowledge_champions(data: dict, include_enemy: bool = False) -> list[str]:
    my_player = _get_my_player(data)
    my_team = str(my_player.get("team", ""))
    ordered: list[str] = []
    seen: set[str] = set()

    my_champion = str(my_player.get("championName", "")).strip()
    if my_champion:
        ordered.append(my_champion)
        seen.add(my_champion)

    for player in data.get("allPlayers", []):
        if not include_enemy and my_team and str(player.get("team", "")) != my_team:
            continue
        champion = str(player.get("championName", "")).strip()
        if champion and champion not in seen:
            ordered.append(champion)
            seen.add(champion)
    return ordered


def _get_my_player(data: dict) -> dict:
    active = data.get("activePlayer", {})
    my_name = active.get("summonerName", "")
    return next((p for p in data.get("allPlayers", []) if p.get("summonerName") == my_name), {})


def _extract_ugg_ssr_data(html: str) -> dict[str, object]:
    marker = "window.__SSR_DATA__ = "
    start = html.find(marker)
    if start < 0:
        return {}
    index = start + len(marker)
    while index < len(html) and html[index].isspace():
        index += 1
    if index >= len(html) or html[index] != "{":
        return {}
    depth = 0
    in_string = False
    escape = False
    end = index
    while end < len(html):
        char = html[end]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
        end += 1
    payload = html[index:end]
    try:
        parsed = json.loads(payload)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_ugg_key(data: dict[str, object], prefix: str, required_substring: str = "") -> str:
    for key in data:
        if not isinstance(key, str):
            continue
        if not key.startswith(prefix):
            continue
        if required_substring and required_substring not in key:
            continue
        return key
    return ""


def _first_ugg_dataset(data: dict[str, object], prefix: str, required_substring: str = "") -> dict[str, object]:
    key = _first_ugg_key(data, prefix, required_substring=required_substring)
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _first_ugg_mapping(data: dict[str, object], key_contains: str) -> object:
    for key, value in data.items():
        if isinstance(key, str) and key_contains in key:
            if isinstance(value, dict) and "data" in value:
                return value.get("data")
            return value
    return {}


def _select_ugg_role_leaf(
    value: object,
    required_keys: tuple[str, ...],
    preferred_role_key: str = "",
) -> tuple[str, dict[str, object]]:
    if not isinstance(value, dict):
        return "", {}
    role_map = value.get("data") if isinstance(value.get("data"), dict) else value
    if not isinstance(role_map, dict):
        return "", {}
    if preferred_role_key:
        preferred = role_map.get(preferred_role_key)
        if isinstance(preferred, dict) and all(key in preferred for key in required_keys):
            return preferred_role_key, preferred
    candidates: list[tuple[int, str, dict[str, object]]] = []
    for role_key, role_value in role_map.items():
        if not isinstance(role_key, str) or not isinstance(role_value, dict):
            continue
        if not all(key in role_value for key in required_keys):
            continue
        matches = 0
        for probe in ("matches", "wins", "pick_rate"):
            raw = role_value.get(probe, 0)
            try:
                matches = max(matches, int(float(raw)))
            except Exception:
                continue
        candidates.append((matches, role_key, role_value))
    if not candidates:
        return "", {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, role_key, role_value = candidates[0]
    return role_key, role_value


def _map_ids_to_names(ids: object, mapping: object) -> list[str]:
    if not isinstance(ids, list) or not isinstance(mapping, dict):
        return []
    names: list[str] = []
    for raw_id in ids:
        key = str(raw_id)
        item = mapping.get(key)
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("title") or "").strip()
            if name:
                names.append(_translate_lol_term(name))
    return names


def _format_ugg_runes(rune_info: object, runes_tree: object) -> str:
    if not isinstance(rune_info, dict) or not isinstance(runes_tree, list):
        return ""
    style_names = _rune_style_names(runes_tree)
    perk_names = _rune_perk_names(runes_tree)
    primary = style_names.get(str(rune_info.get("primary_style", "")), "")
    secondary = style_names.get(str(rune_info.get("sub_style", "")), "")
    perk_list = [perk_names.get(str(perk_id), "") for perk_id in rune_info.get("active_perks", [])]
    perks = [perk for perk in perk_list if perk]
    summary = " / ".join(part for part in [primary, secondary] if part)
    if perks:
        return f"{summary}；关键符文：{', '.join(perks[:6])}" if summary else f"关键符文：{', '.join(perks[:6])}"
    return summary


def _rune_style_names(runes_tree: list[object]) -> dict[str, str]:
    names: dict[str, str] = {}
    for tree in runes_tree:
        if isinstance(tree, dict):
            style_id = tree.get("id")
            name = str(tree.get("name") or "").strip()
            if style_id is not None and name:
                names[str(style_id)] = _translate_lol_term(name)
    return names


def _rune_perk_names(runes_tree: list[object]) -> dict[str, str]:
    names: dict[str, str] = {}
    for tree in runes_tree:
        if not isinstance(tree, dict):
            continue
        for slot in tree.get("slots", []):
            if not isinstance(slot, dict):
                continue
            for perk in slot.get("runes", []):
                if not isinstance(perk, dict):
                    continue
                perk_id = perk.get("id")
                name = str(perk.get("name") or "").strip()
                if perk_id is not None and name:
                    names[str(perk_id)] = _translate_lol_term(name)
    return names


def _format_skill_order(skill_info: object) -> str:
    if not isinstance(skill_info, dict):
        return ""
    slots = skill_info.get("slots", [])
    if isinstance(slots, list) and slots:
        order = [str(slot).strip().upper() for slot in slots if str(slot).strip()]
        if order:
            return " > ".join(order)
    return ""


def _format_ugg_counter_sections(counters: object, champions_map: object) -> list[tuple[str, str]]:
    if not isinstance(counters, list) or not isinstance(champions_map, dict):
        return []
    sorted_counters = sorted(
        [item for item in counters if isinstance(item, dict)],
        key=lambda item: float(item.get("win_rate", 0.0)),
        reverse=True,
    )
    hard_matchups: list[str] = []
    for counter in sorted_counters[:3]:
        champion_data = champions_map.get(str(counter.get("champion_id")))
        if not isinstance(champion_data, dict):
            continue
        name = str(champion_data.get("name") or "").strip()
        if name:
            win_rate = float(counter.get("win_rate", 0.0))
            hard_matchups.append(f"{name}（对手胜率 {win_rate:.1f}%）")
    easier_matchups: list[str] = []
    for counter in list(reversed(sorted_counters[-3:])):
        champion_data = champions_map.get(str(counter.get("champion_id")))
        if not isinstance(champion_data, dict):
            continue
        name = str(champion_data.get("name") or "").strip()
        if name:
            win_rate = float(counter.get("win_rate", 0.0))
            easier_matchups.append(f"{name}（对手胜率 {win_rate:.1f}%）")
    sections: list[tuple[str, str]] = []
    if hard_matchups:
        sections.append(("对线提醒", "需要重点提防： " + "、".join(hard_matchups)))
    if easier_matchups:
        sections.append(("优势对线", "相对更好打： " + "、".join(easier_matchups)))
    return sections


def _format_ugg_stats(stats: object) -> str:
    if not isinstance(stats, dict):
        return ""
    pieces: list[str] = []
    win_rate = _percent_text(stats.get("win_rate"))
    pick_rate = _percent_text(stats.get("pick_rate"))
    ban_rate = _percent_text(stats.get("ban_rate"))
    matches = _int_text(stats.get("matches"))
    rank = _int_text(stats.get("rank"))
    if win_rate:
        pieces.append(f"胜率 {win_rate}")
    if pick_rate:
        pieces.append(f"登场率 {pick_rate}")
    if ban_rate:
        pieces.append(f"Ban {ban_rate}")
    if matches:
        pieces.append(f"样本 {matches} 场")
    if rank:
        pieces.append(f"排名 #{rank}")
    return " · ".join(pieces)


def _extract_ugg_patch_version(data: dict[str, object]) -> str:
    patterns = [
        re.compile(r"/([0-9]{1,2})_([0-9]{1,2})/"),
        re.compile(r"/([0-9]{1,2})\.([0-9]{1,2})\.[0-9]+/"),
        re.compile(r"\b([0-9]{1,2})\.([0-9]{1,2})\b"),
    ]
    for key in data:
        if not isinstance(key, str):
            continue
        for pattern in patterns:
            match = pattern.search(key)
            if match:
                return f"{int(match.group(1))}.{int(match.group(2))}"
    return ""


def _percent_text(value: object) -> str:
    try:
        number = float(value)
    except Exception:
        return ""
    if number <= 0:
        return ""
    return f"{number:.1f}%"


def _int_text(value: object) -> str:
    try:
        number = int(value)
    except Exception:
        return ""
    return str(number) if number > 0 else ""


def _extract_ugg_optional_items(overview_leaf: dict[str, object], items_map: object, *, exclude: list[str]) -> list[str]:
    if not isinstance(items_map, dict):
        return []
    seen = {name.lower() for name in exclude if name}
    optional: list[str] = []
    for key, value in overview_leaf.items():
        if not str(key).startswith("item_options_"):
            continue
        ids: list[object] = []
        if isinstance(value, dict):
            ids = value.get("ids") or value.get("item_ids") or []
        elif isinstance(value, list):
            ids = [entry.get("id") for entry in value if isinstance(entry, dict) and entry.get("id") is not None]
        else:
            continue
        names = _map_ids_to_names(ids, items_map)
        for name in names:
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            optional.append(name)
    return optional


def _document_quality_score(doc: SearchDocument) -> int:
    metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
    try:
        base = int(metadata.get("quality", 0))
    except Exception:
        base = 0
    if base:
        return base
    if doc.excerpt and len(doc.excerpt) > 180:
        return 40
    if doc.snippet:
        return 20
    return 0


def _format_ugg_role_label(role_key: str) -> str:
    if not role_key:
        return ""
    lowered = role_key.lower()
    mapping = {
        "top": "上单",
        "jungle": "打野",
        "mid": "中单",
        "adc": "下路",
        "support": "辅助",
    }
    for needle, label in mapping.items():
        if needle in lowered:
            return label
    return role_key


def _render_lol_section_card(title: str, body: str) -> str:
    rendered_body = _format_lol_section_body(title, body)
    return (
        "<div style='margin:10px 0 0 0;padding:12px 13px;background:#151b25;border:1px solid #263043;border-radius:12px;'>"
        f"<div style='margin-bottom:8px;color:#9ec0ff;font-size:12px;font-weight:700;letter-spacing:0.4px;'>{_escape_html(title)}</div>"
        f"{rendered_body}"
        "</div>"
    )


def _format_lol_section_body(title: str, body: str) -> str:
    compact_titles = {"版本", "主位置", "召唤师技能", "技能加点", "出门装", "核心三件", "可选装备"}
    if title in compact_titles:
        tokens = _split_lol_tokens(body)
        if tokens:
            chips = "".join(
                "<span style='display:inline-block;margin:0 8px 8px 0;padding:6px 10px;background:#1c2532;"
                "border:1px solid #33445c;border-radius:999px;color:#eef3fb;font-size:13px;'>"
                f"{_escape_html(token)}</span>"
                for token in tokens
            )
            return f"<div>{chips}</div>"
    return f"<div style='white-space:pre-wrap;color:#dbe1ea;font-size:14px;line-height:1.7;'>{_escape_html(body)}</div>"


def _split_lol_tokens(body: str) -> list[str]:
    separators = ["；", " -> ", " / ", " + ", "、", "·"]
    text = str(body or "").strip()
    if not text:
        return []
    normalized = text
    for separator in separators:
        normalized = normalized.replace(separator, "|")
    parts = [part.strip() for part in normalized.split("|")]
    return [part for part in parts if part]


def _build_lol_hero_summary(sections: list[tuple[str, str]]) -> str:
    section_map = {title: body for title, body in sections}
    pieces: list[str] = []
    if section_map.get("数据概览"):
        pieces.append(f"<b>数据：</b>{_escape_html(section_map['数据概览'])}")
    if section_map.get("符文"):
        pieces.append(f"<b>符文：</b>{_escape_html(section_map['符文'])}")
    if section_map.get("对线提醒"):
        pieces.append(f"<b>对线：</b>{_escape_html(section_map['对线提醒'])}")
    return "<br>".join(pieces[:3])


def _translate_lol_term(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if value in _SUMMONER_SPELL_TRANSLATIONS:
        return _SUMMONER_SPELL_TRANSLATIONS[value]
    if value in _LOL_ROLE_TRANSLATIONS:
        return _LOL_ROLE_TRANSLATIONS[value]
    if value in _RUNE_STYLE_TRANSLATIONS:
        return _RUNE_STYLE_TRANSLATIONS[value]
    if value in _RUNE_PERK_TRANSLATIONS:
        return _RUNE_PERK_TRANSLATIONS[value]
    return value


def _translate_wzstats_phrase(text: str) -> str:
    value = _compact_text(text)
    if not value:
        return ""
    translated = value
    translated = re.sub(
        r"Attack after (.+?) is down and force short trades around his cooldowns\.?",
        r"\1进入冷却后立刻反打，并围绕他的技能冷却打短换血。",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"Avoid long extended fights once (.+?) has his first crit item\.?",
        r"一旦\1做出第一件暴击装，避免和他打长时间拉扯战。",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"Respect his level 6 all-in when the wave is on his side\.?",
        "兵线在他那边时，要重点提防他的六级一套爆发。",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"Thrives in Diamond\+\s*[—-]\s*rewards mechanical skill and game knowledge",
        "在钻石以上分段更容易发挥，也更吃熟练度和操作理解。",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"Rewards some practice\s*[—-]\s*noticeable improvement after a few games",
        "需要一定练习后效果更好，熟练几局后胜率提升明显。",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"Thrives in Diamond\+\s+and rewards mechanical skill and game knowledge\.?",
        "在钻石以上分段更容易发挥，也更吃熟练度和操作理解。",
        translated,
        flags=re.IGNORECASE,
    )
    for english, chinese in _WZSTATS_PHRASE_TRANSLATIONS.items():
        translated = translated.replace(english, chinese)
    translated = translated.replace("  ", " ")
    return translated


def _compact_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _match_text(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return ""
    return _compact_text(match.group(1))


def _match_block(text: str, start_label: str, end_labels: tuple[str, ...], *, from_end: bool = False) -> str:
    start = text.rfind(start_label) if from_end else text.find(start_label)
    if start < 0:
        return ""
    content = text[start + len(start_label):]
    end_positions = [content.find(label) for label in end_labels if content.find(label) >= 0]
    if end_positions:
        content = content[: min(end_positions)]
    return _compact_text(content)[:220]


def _collect_named_metrics(text: str, metric_names: tuple[str, ...]) -> str:
    pairs: list[str] = []
    for metric in metric_names:
        value = _match_metric_value(text, metric)
        if value:
            pairs.append(f"{_translate_metric_name(metric)} {value}")
    return " · ".join(pairs)


def _match_metric_value(text: str, metric_name: str) -> str:
    pattern = rf"{re.escape(metric_name)}\s+([0-9.,%]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return ""
    return _compact_text(match.group(1))


def _translate_metric_name(name: str) -> str:
    mapping = {
        "Win Rate": "胜率",
        "Carry Score": "C位评分",
        "KDA": "KDA",
        "Kills/game": "场均击杀",
        "Deaths/game": "场均死亡",
        "Assists/game": "场均助攻",
        "Damage/game": "场均伤害",
        "CS/min": "每分钟补刀",
        "Gold/min": "每分钟经济",
        "Vision Score": "视野得分",
    }
    return mapping.get(name, name)
