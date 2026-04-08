from src.ui.web_routes import build_lol_routes, build_lol_team_routes, build_tft_routes, _slugify


def test_slugify_simple():
    assert _slugify("Yasuo") == "yasuo"


def test_slugify_apostrophe():
    assert _slugify("Kai'Sa") == "kaisa"


def test_slugify_space():
    assert _slugify("Lee Sin") == "leesin"


def test_build_lol_routes_default_sites():
    routes = build_lol_routes("Yasuo")
    assert len(routes) == 3
    assert routes[0].domain == "op.gg"
    assert "yasuo" in routes[0].url
    assert routes[1].domain == "u.gg"
    assert routes[2].domain == "lolalytics.com"


def test_build_lol_routes_custom_sites():
    routes = build_lol_routes("Jinx", sites=["u.gg", "op.gg"])
    assert len(routes) == 2
    assert routes[0].domain == "u.gg"
    assert "jinx" in routes[0].url


def test_build_lol_routes_empty_champion():
    assert build_lol_routes("") == []


def test_build_lol_team_routes_multiple_champions():
    routes = build_lol_team_routes(["Yasuo", "Jinx", "Thresh"])
    assert len(routes) == 3
    assert routes[0].label == "Yasuo"
    assert routes[1].label == "Jinx"
    assert routes[2].label == "Thresh"
    assert "yasuo" in routes[0].url
    assert "jinx" in routes[1].url
    # all on same site
    assert all(r.domain == "op.gg" for r in routes)


def test_build_lol_team_routes_custom_site():
    routes = build_lol_team_routes(["Yasuo", "Jinx"], site="u.gg")
    assert len(routes) == 2
    assert all(r.domain == "u.gg" for r in routes)
    assert "yasuo" in routes[0].url
    assert "jinx" in routes[1].url


def test_build_lol_team_routes_empty():
    assert build_lol_team_routes([]) == []


def test_build_tft_routes_default():
    routes = build_tft_routes()
    assert len(routes) == 3
    assert routes[0].domain == "tactics.tools"
    assert "team-comps" in routes[0].url


def test_build_tft_routes_custom_sites():
    routes = build_tft_routes(sites=["lolchess.gg"])
    assert len(routes) == 1
    assert routes[0].domain == "lolchess.gg"
    assert "meta" in routes[0].url
