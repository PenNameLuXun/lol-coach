"""Web search subpackage — search engines, HTML parsing, and document models."""

from src.search.models import SearchSite, SearchDocument
from src.search.formatting import format_search_documents, sort_search_documents
from src.search.html_extract import (
    fetch_page_html,
    sanitize_content_html,
    extract_meta_description,
    extract_heading_texts,
    extract_visible_text_excerpt,
    infer_patch_version,
    infer_domain_from_url,
)
from src.search.engine import search_web_for_qa, should_web_search_question
from src.search.sites import parse_search_sites_text, merge_search_sites

__all__ = [
    "SearchSite",
    "SearchDocument",
    "format_search_documents",
    "sort_search_documents",
    "fetch_page_html",
    "sanitize_content_html",
    "extract_meta_description",
    "extract_heading_texts",
    "extract_visible_text_excerpt",
    "infer_patch_version",
    "infer_domain_from_url",
    "search_web_for_qa",
    "should_web_search_question",
    "parse_search_sites_text",
    "merge_search_sites",
]
