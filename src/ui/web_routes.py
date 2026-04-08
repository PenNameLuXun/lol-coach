"""URL routing for embedded web knowledge — maps game state to site URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class EmbedRoute:
    """One tab in the embedded knowledge window."""
    label: str
    url: str
    domain: str


# ── LOL ──────────────────────────────────────────────────────────────────────

_LOL_SITE_BUILDERS: dict[str, tuple[str, object]] = {
    "op.gg": ("OP.GG", lambda slug: f"https://www.op.gg/champions/{slug}/build"),
    "u.gg": ("U.GG", lambda slug: f"https://u.gg/lol/champions/{slug}/build"),
    "lolalytics.com": ("Lolalytics", lambda slug: f"https://lolalytics.com/lol/{slug}/build/"),
    "mobafire.com": ("MOBAFire", lambda slug: f"https://www.mobafire.com/league-of-legends/champion/{slug}"),
}

_LOL_DEFAULT_SITES = ["op.gg", "u.gg", "lolalytics.com"]
_LOL_DEFAULT_SITE = "op.gg"


def build_lol_routes(
    champion: str,
    sites: list[str] | None = None,
) -> list[EmbedRoute]:
    """Build embed routes for a single LoL champion — one tab per site."""
    if not champion:
        return []
    slug = _slugify(champion)
    site_list = sites or _LOL_DEFAULT_SITES
    routes: list[EmbedRoute] = []
    for domain in site_list:
        key = domain.lower().removeprefix("www.")
        if key in _LOL_SITE_BUILDERS:
            label, url_fn = _LOL_SITE_BUILDERS[key]
            routes.append(EmbedRoute(label=label, url=url_fn(slug), domain=key))
    return routes


def build_lol_team_routes(
    champions: list[str],
    site: str | None = None,
) -> list[EmbedRoute]:
    """Build embed routes for multiple champions — one tab per champion, same site."""
    if not champions:
        return []
    site_key = (site or _LOL_DEFAULT_SITE).lower().removeprefix("www.")
    if site_key not in _LOL_SITE_BUILDERS:
        site_key = _LOL_DEFAULT_SITE
    _, url_fn = _LOL_SITE_BUILDERS[site_key]
    routes: list[EmbedRoute] = []
    for champion in champions:
        slug = _slugify(champion)
        if slug:
            routes.append(EmbedRoute(label=champion, url=url_fn(slug), domain=site_key))
    return routes


# ── TFT ──────────────────────────────────────────────────────────────────────

_TFT_SITE_URLS: dict[str, tuple[str, str]] = {
    "tactics.tools": ("Tactics.Tools", "https://tactics.tools/team-comps"),
    "lolchess.gg": ("LOLChess", "https://lolchess.gg/meta"),
    "mobalytics.gg": ("Mobalytics", "https://mobalytics.gg/tft/team-comps"),
    "tft.op.gg": ("TFT OP.GG", "https://tft.op.gg/meta-trends"),
}

_TFT_DEFAULT_SITES = ["tactics.tools", "lolchess.gg", "mobalytics.gg"]


def build_tft_routes(
    sites: list[str] | None = None,
) -> list[EmbedRoute]:
    """Build embed routes for TFT meta comps."""
    site_list = sites or _TFT_DEFAULT_SITES
    routes: list[EmbedRoute] = []
    for domain in site_list:
        key = domain.lower().removeprefix("www.")
        if key in _TFT_SITE_URLS:
            label, url = _TFT_SITE_URLS[key]
            routes.append(EmbedRoute(label=label, url=url, domain=key))
    return routes


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert champion name to URL slug (e.g. 'Kai'Sa' -> 'kaisa')."""
    slug = re.sub(r"[^a-z0-9]+", "", name.strip().lower())
    return slug
