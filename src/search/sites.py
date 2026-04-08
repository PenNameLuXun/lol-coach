"""Search site configuration parsing and merging."""

from __future__ import annotations

from src.search.models import SearchSite


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
