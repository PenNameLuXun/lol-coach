from __future__ import annotations

from dataclasses import dataclass
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
    return sort_search_documents(docs)


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


def _fetch_excerpt(*, session: requests.Session, url: str, timeout_seconds: int) -> str:
    try:
        html = session.get(url, timeout=timeout_seconds).text
    except Exception:
        return ""
    html = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = _clean_html_text(re.sub(r"<[^>]+>", " ", html))
    return text[:1500]


def _clean_html_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def infer_domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


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
