from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
import re
from urllib.parse import quote, unquote, urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def should_web_search_question(question: str) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False
    keywords = [
        "最新",
        "当前版本",
        "这个版本",
        "版本",
        "补丁",
        "改动",
        "主流",
        "胜率",
        "出装",
        "符文",
        "阵容",
        "攻略",
        "opgg",
        "u.gg",
        "lolchess",
        "tactics.tools",
        "现在",
        "目前",
        "recent",
        "latest",
        "patch",
        "meta",
        "build",
        "guide",
        "tier",
        "win rate",
    ]
    return any(keyword in text for keyword in keywords)


def parse_search_sites_text(text: str) -> list[SearchSite]:
    sites: list[SearchSite] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",", 1)]
        domain = parts[0].lower()
        if not domain:
            continue
        try:
            priority = int(parts[1]) if len(parts) > 1 and parts[1] else 50
        except ValueError:
            priority = 50
        sites.append(SearchSite(domain=domain, priority=priority))
    return sites


def merge_search_sites(*site_groups: list[SearchSite]) -> list[SearchSite]:
    merged: dict[str, SearchSite] = {}
    for group in site_groups:
        for site in group:
            existing = merged.get(site.domain)
            if existing is None or site.priority > existing.priority:
                merged[site.domain] = site
    return sorted(merged.values(), key=lambda item: (-item.priority, item.domain))


def search_web_for_qa(
    *,
    question: str,
    engine: str,
    sites: list[SearchSite],
    timeout_seconds: int,
    max_results_per_site: int,
    max_pages: int,
    stop_after_first_site_success: bool = False,
) -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    if not question.strip() or not sites or max_pages <= 0:
        return docs

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

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
                    patch_version=_infer_patch_version(
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
                patch_version=_infer_patch_version(candidate["title"], excerpt, candidate["url"]),
            )
        )
        break
    if not docs:
        print(f"[web search] site={site.domain} direct_fallback failed")
    return docs


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


def fetch_page_html(*, url: str, timeout_seconds: int, session: requests.Session | None = None) -> str:
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        session.headers.update({"User-Agent": USER_AGENT})
    try:
        response = session.get(url, timeout=timeout_seconds)
    except Exception:
        return ""
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    return response.text


def sanitize_content_html(html: str) -> str:
    return _strip_non_content_tags(html)


def extract_meta_description(html: str) -> str:
    return _extract_meta_description(html)


def extract_heading_texts(html: str, *, max_items: int = 4) -> list[str]:
    return _extract_heading_texts(html, max_items=max_items)


def extract_visible_text_excerpt(html: str) -> str:
    return _extract_visible_text_excerpt(html)


def infer_patch_version(*parts: str) -> str:
    return _infer_patch_version(*parts)


def _search_site(
    *,
    session: requests.Session,
    engine: str,
    question: str,
    domain: str,
    timeout_seconds: int,
    max_results: int,
) -> list[dict[str, str]]:
    query = f"{question} site:{domain}"
    engine_name = str(engine).strip().lower()
    if engine_name == "google":
        url = f"https://www.google.com/search?q={quote(query)}&hl=zh-CN"
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
        title = _clean_html_text(match.group("title"))
        if href.startswith("//duckduckgo.com/l/?uddg="):
            href = unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if not href.startswith("http"):
            continue
        snippet = _clean_html_text(snippets[idx] if idx < len(snippets) else "")
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
        title = _clean_html_text(match.group("title"))
        results.append({"url": href, "title": title, "snippet": ""})
        if len(results) >= max_results:
            break
    return results


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

    if "tft" in question.lower() or "meta comps" in question.lower() or "阵容" in question:
        if normalized == "tactics.tools":
            return [{"title": "TFT Meta Comps", "url": "https://tactics.tools/team-comps"}]
        if normalized == "lolchess.gg":
            return [{"title": "TFT Meta", "url": "https://lolchess.gg/meta"}]
        if normalized == "mobalytics.gg":
            return [{"title": "TFT Team Comps", "url": "https://mobalytics.gg/tft/team-comps"}]

    return []


def _fetch_excerpt(*, session: requests.Session, url: str, timeout_seconds: int) -> str:
    try:
        response = session.get(url, timeout=timeout_seconds)
    except Exception:
        return ""
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    html = response.text
    return _extract_excerpt_from_html(url=url, html=html)


def _extract_excerpt_from_html(*, url: str, html: str) -> str:
    domain = infer_domain_from_url(url)
    html = _strip_non_content_tags(html)

    site_excerpt = _extract_site_specific_excerpt(domain=domain, html=html)
    if site_excerpt:
        return site_excerpt[:4000]

    meta_excerpt = _extract_meta_description(html)
    if meta_excerpt:
        text_excerpt = _extract_visible_text_excerpt(html)
        if text_excerpt and text_excerpt not in meta_excerpt:
            return f"{meta_excerpt} {text_excerpt[:1600]}".strip()[:4000]
        return meta_excerpt[:4000]

    return _extract_visible_text_excerpt(html)[:4000]


def _strip_non_content_tags(html: str) -> str:
    html = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<noscript\b[^<]*(?:(?!</noscript>)<[^<]*)*</noscript>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return html


def _extract_site_specific_excerpt(*, domain: str, html: str) -> str:
    normalized = domain.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]

    if normalized in {"op.gg", "u.gg", "leagueofgraphs.com", "mobafire.com", "mobalytics.gg"}:
        return _extract_curated_excerpt(html, include_visible_text=False, text_limit=600)
    if normalized in {"tactics.tools", "lolchess.gg"}:
        return _extract_curated_excerpt(html, include_visible_text=True, text_limit=1000)
    return ""


def _extract_curated_excerpt(html: str, *, include_visible_text: bool, text_limit: int) -> str:
    pieces: list[str] = []
    meta = _extract_meta_description(html)
    if meta:
        pieces.append(meta)

    headings = _extract_heading_texts(html, max_items=4)
    if headings:
        pieces.append(" / ".join(headings))

    if include_visible_text:
        visible = _extract_visible_text_excerpt(html)
        if visible:
            pieces.append(visible[:text_limit])

    return _dedupe_joined_text(" ".join(pieces))


def _extract_meta_description(html: str) -> str:
    patterns = [
        re.compile(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta[^>]+content=["\'](?P<content>[^"\']+)["\'][^>]+name=["\']description["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta[^>]+content=["\'](?P<content>[^"\']+)["\'][^>]+property=["\']og:description["\']',
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            return _clean_html_text(match.group("content"))
    return ""


def _extract_heading_texts(html: str, *, max_items: int) -> list[str]:
    pattern = re.compile(r"<h[1-3][^>]*>(?P<text>.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
    headings: list[str] = []
    for match in pattern.finditer(html):
        text = _clean_html_text(re.sub(r"<[^>]+>", " ", match.group("text")))
        if text and text not in headings:
            headings.append(text)
        if len(headings) >= max_items:
            break
    return headings


def _extract_visible_text_excerpt(html: str) -> str:
    text = _clean_html_text(re.sub(r"<[^>]+>", " ", html))
    return _dedupe_joined_text(text)


def _dedupe_joined_text(text: str) -> str:
    cleaned = _clean_html_text(text)
    if not cleaned:
        return ""
    tokens = re.split(r"(?<=[。.!?])\s+|\s{2,}", cleaned)
    seen: set[str] = set()
    kept: list[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(token)
    return " ".join(kept)


def _clean_html_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def infer_domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


def _infer_lol_champion_from_question(question: str) -> str:
    match = re.search(r"League of Legends\s+(.+?)\s+build", question, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _slugify_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower())
    return slug.strip("-")


def _infer_patch_version(*parts: str) -> str:
    patterns = [
        re.compile(r"(?:patch|版本)\s*([0-9]{1,2})[.。]([0-9]{1,2})", re.IGNORECASE),
        re.compile(r"\b([0-9]{1,2})[.。]([0-9]{1,2})\b"),
    ]
    for part in parts:
        text = str(part or "")
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return f"{int(match.group(1))}.{int(match.group(2))}"
    return ""


def _patch_sort_key(version: str) -> tuple[int, int, int]:
    if not version:
        return (0, -1, -1)
    try:
        major_text, minor_text = version.split(".", 1)
        return (1, int(major_text), int(minor_text))
    except Exception:
        return (0, -1, -1)
