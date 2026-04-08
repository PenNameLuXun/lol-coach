"""HTML fetching, parsing, and text extraction utilities."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.7"


def fetch_page_html(
    *,
    url: str,
    timeout_seconds: int,
    session: requests.Session | None = None,
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE,
) -> str:
    own_session = session is None
    session = session or requests.Session()
    if own_session:
        session.headers.update(default_headers(accept_language))
    try:
        response = session.get(url, timeout=timeout_seconds)
    except Exception:
        return ""
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    return response.text


def sanitize_content_html(html: str) -> str:
    return strip_non_content_tags(html)


def extract_meta_description(html: str) -> str:
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
            return clean_html_text(match.group("content"))
    return ""


def extract_heading_texts(html: str, *, max_items: int = 4) -> list[str]:
    pattern = re.compile(r"<h[1-3][^>]*>(?P<text>.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
    headings: list[str] = []
    for match in pattern.finditer(html):
        text = clean_html_text(re.sub(r"<[^>]+>", " ", match.group("text")))
        if text and text not in headings:
            headings.append(text)
        if len(headings) >= max_items:
            break
    return headings


def extract_visible_text_excerpt(html: str) -> str:
    text = clean_html_text(re.sub(r"<[^>]+>", " ", html))
    return dedupe_joined_text(text)


def infer_patch_version(*parts: str) -> str:
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


def infer_domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


# ── Internal helpers ──────────────────────────────────────────────────────────

def strip_non_content_tags(html: str) -> str:
    html = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<noscript\b[^<]*(?:(?!</noscript>)<[^<]*)*</noscript>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return html


def extract_site_specific_excerpt(*, domain: str, html: str) -> str:
    normalized = domain.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if normalized in {"op.gg", "u.gg", "leagueofgraphs.com", "mobafire.com", "mobalytics.gg"}:
        return extract_curated_excerpt(html, include_visible_text=False, text_limit=600)
    if normalized in {"tactics.tools", "lolchess.gg"}:
        return extract_curated_excerpt(html, include_visible_text=True, text_limit=1000)
    return ""


def extract_curated_excerpt(html: str, *, include_visible_text: bool, text_limit: int) -> str:
    pieces: list[str] = []
    meta = extract_meta_description(html)
    if meta:
        pieces.append(meta)
    headings = extract_heading_texts(html, max_items=4)
    if headings:
        pieces.append(" / ".join(headings))
    if include_visible_text:
        visible = extract_visible_text_excerpt(html)
        if visible:
            pieces.append(visible[:text_limit])
    return dedupe_joined_text(" ".join(pieces))


def extract_excerpt_from_html(*, url: str, html: str) -> str:
    domain = infer_domain_from_url(url)
    html = strip_non_content_tags(html)
    site_excerpt = extract_site_specific_excerpt(domain=domain, html=html)
    if site_excerpt:
        return site_excerpt[:4000]
    meta_excerpt = extract_meta_description(html)
    if meta_excerpt:
        text_excerpt = extract_visible_text_excerpt(html)
        if text_excerpt and text_excerpt not in meta_excerpt:
            return f"{meta_excerpt} {text_excerpt[:1600]}".strip()[:4000]
        return meta_excerpt[:4000]
    return extract_visible_text_excerpt(html)[:4000]


def clean_html_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def dedupe_joined_text(text: str) -> str:
    cleaned = clean_html_text(text)
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


def default_headers(accept_language: str) -> dict[str, str]:
    language = str(accept_language or "").strip() or DEFAULT_ACCEPT_LANGUAGE
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": language,
    }


def primary_language_code(accept_language: str) -> str:
    language = str(accept_language or "").strip()
    if not language:
        return "zh-CN"
    first = language.split(",", 1)[0].strip()
    return first or "zh-CN"
