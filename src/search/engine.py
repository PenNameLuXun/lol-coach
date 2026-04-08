"""Search engine orchestration — DuckDuckGo, Google, and direct fallback."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote, unquote

import requests

from src.search.models import SearchSite, SearchDocument
from src.search.formatting import sort_search_documents
from src.search.html_extract import (
    DEFAULT_ACCEPT_LANGUAGE,
    clean_html_text,
    default_headers,
    extract_excerpt_from_html,
    infer_patch_version,
    primary_language_code,
)


def should_web_search_question(question: str) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False
    keywords = [
        "最新", "当前版本", "这个版本", "版本", "补丁", "改动", "主流",
        "胜率", "出装", "符文", "阵容", "攻略",
        "opgg", "u.gg", "lolchess", "tactics.tools",
        "现在", "目前",
        "recent", "latest", "patch", "meta", "build", "guide", "tier", "win rate",
    ]
    return any(keyword in text for keyword in keywords)


def search_web_for_qa(
    *,
    question: str,
    engine: str,
    sites: list[SearchSite],
    timeout_seconds: int,
    max_results_per_site: int,
    max_pages: int,
    stop_after_first_site_success: bool = False,
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE,
) -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    if not question.strip() or not sites or max_pages <= 0:
        return docs

    session = requests.Session()
    session.headers.update(default_headers(accept_language))

    for site in sites:
        if len(docs) >= max_pages:
            break
        results = _search_site(
            session=session,
            engine=engine,
            question=question,
            domain=site.domain,
            timeout_seconds=timeout_seconds,
            max_results=max_results_per_site,
            accept_language=accept_language,
        )
        print(f"[web search] site={site.domain} hits={len(results)}")
        if not results:
            fallback_docs = _direct_fallback_documents(
                session=session,
                site=site,
                question=question,
                timeout_seconds=timeout_seconds,
            )
            if fallback_docs:
                docs.extend(fallback_docs[: max_pages - len(docs)])
                if stop_after_first_site_success:
                    break
                continue
        for result in results:
            excerpt = _fetch_excerpt(
                session=session,
                url=result["url"],
                timeout_seconds=timeout_seconds,
            )
            docs.append(
                SearchDocument(
                    domain=site.domain,
                    priority=site.priority,
                    title=result["title"],
                    url=result["url"],
                    snippet=result["snippet"],
                    excerpt=excerpt or result["snippet"],
                    patch_version=infer_patch_version(
                        result["title"],
                        result["snippet"],
                        result["url"],
                        excerpt,
                    ),
                )
            )
            if len(docs) >= max_pages:
                break
        if stop_after_first_site_success and results:
            break
    return sort_search_documents(docs)


# ── Internal ─────────────────────────────────────────────────────────────────

def _search_site(
    *,
    session: requests.Session,
    engine: str,
    question: str,
    domain: str,
    timeout_seconds: int,
    max_results: int,
    accept_language: str,
) -> list[dict[str, str]]:
    query = f"{question} site:{domain}"
    engine_name = str(engine).strip().lower()
    if engine_name == "google":
        url = f"https://www.google.com/search?q={quote(query)}&hl={quote(primary_language_code(accept_language))}"
        html = session.get(url, timeout=timeout_seconds).text
        return _parse_google_results(html, max_results=max_results)
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    html = session.get(url, timeout=timeout_seconds).text
    return _parse_duckduckgo_results(html, max_results=max_results)


def _parse_duckduckgo_results(html: str, *, max_results: int) -> list[dict[str, str]]:
    pattern = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>.*?</a>.*?<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>|'
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>.*?</a>.*?<div[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet2>.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, str]] = []
    snippets = [match.group("snippet") or match.group("snippet2") or "" for match in snippet_pattern.finditer(html)]
    for idx, match in enumerate(pattern.finditer(html)):
        href = unescape(match.group("href"))
        title = clean_html_text(match.group("title"))
        if href.startswith("//duckduckgo.com/l/?uddg="):
            href = unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if not href.startswith("http"):
            continue
        snippet = clean_html_text(snippets[idx] if idx < len(snippets) else "")
        results.append({"url": href, "title": title, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _parse_google_results(html: str, *, max_results: int) -> list[dict[str, str]]:
    pattern = re.compile(
        r'<a href="/url\?q=(?P<href>https?://[^"&]+)[^"]*".*?<h3[^>]*>(?P<title>.*?)</h3>',
        re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, str]] = []
    for match in pattern.finditer(html):
        href = unquote(match.group("href"))
        title = clean_html_text(match.group("title"))
        results.append({"url": href, "title": title, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


def _direct_fallback_documents(
    *,
    session: requests.Session,
    site: SearchSite,
    question: str,
    timeout_seconds: int,
) -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    for candidate in _direct_content_candidates(site.domain, question):
        excerpt = _fetch_excerpt(session=session, url=candidate["url"], timeout_seconds=timeout_seconds)
        if not excerpt:
            continue
        print(f"[web search] site={site.domain} direct_fallback ok url={candidate['url']}")
        docs.append(
            SearchDocument(
                domain=site.domain,
                priority=site.priority,
                title=candidate["title"],
                url=candidate["url"],
                snippet=excerpt[:200],
                excerpt=excerpt,
                patch_version=infer_patch_version(candidate["title"], excerpt, candidate["url"]),
            )
        )
        break
    if not docs:
        print(f"[web search] site={site.domain} direct_fallback failed")
    return docs


def _direct_content_candidates(domain: str, question: str) -> list[dict[str, str]]:
    normalized = domain.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]

    champion = _infer_lol_champion_from_question(question)
    champion_slug = _slugify_name(champion)

    if champion_slug:
        if normalized == "op.gg":
            return [
                {"title": f"{champion} Build", "url": f"https://www.op.gg/champions/{champion_slug}/build"},
                {"title": f"{champion} Counters", "url": f"https://www.op.gg/champions/{champion_slug}/counters"},
            ]
        if normalized == "u.gg":
            return [
                {"title": f"{champion} Build", "url": f"https://u.gg/lol/champions/{champion_slug}/build"},
                {"title": f"{champion} Counters", "url": f"https://u.gg/lol/champions/{champion_slug}/counter"},
            ]
        if normalized == "leagueofgraphs.com":
            return [
                {"title": f"{champion} Builds", "url": f"https://www.leagueofgraphs.com/champions/builds/{champion_slug}"},
            ]
        if normalized == "mobalytics.gg":
            return [
                {"title": f"{champion} Build", "url": f"https://mobalytics.gg/lol/champions/{champion_slug}/build"},
            ]
        if normalized == "origin-lol.wzstats.gg":
            return [
                {"title": f"{champion} Build", "url": f"https://origin-lol.wzstats.gg/zh/champions/{champion_slug}"},
            ]

    if "tft" in question.lower() or "meta comps" in question.lower() or "阵容" in question:
        if normalized == "tactics.tools":
            return [{"title": "TFT Meta Comps", "url": "https://tactics.tools/team-comps"}]
        if normalized == "lolchess.gg":
            return [{"title": "TFT Meta", "url": "https://lolchess.gg/meta"}]
        if normalized == "mobalytics.gg":
            return [{"title": "TFT Team Comps", "url": "https://mobalytics.gg/tft/team-comps"}]
        if normalized == "tft.vinky.cn":
            return [{"title": "TFT 阵容", "url": "https://tft.vinky.cn/"}]

    return []


def _fetch_excerpt(*, session: requests.Session, url: str, timeout_seconds: int) -> str:
    try:
        response = session.get(url, timeout=timeout_seconds)
    except Exception:
        return ""
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    html = response.text
    return extract_excerpt_from_html(url=url, html=html)


def _infer_lol_champion_from_question(question: str) -> str:
    match = re.search(r"League of Legends\s+(.+?)\s+build", question, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower())
    return slug.strip("-")
