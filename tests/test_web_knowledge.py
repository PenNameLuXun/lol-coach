from datetime import datetime

from src.qa_web_search import SearchDocument
from src.config import Config
from src.game_plugins.lol.knowledge import build_lol_web_knowledge_item
from src.game_plugins.lol.plugin import LolPlugin
from src.game_plugins.tft.knowledge import build_tft_web_knowledge_item
from src.game_plugins.tft.plugin import TftPlugin
from src.web_knowledge import KnowledgeBundle, KnowledgeItem, WebKnowledgeManager, render_knowledge_item
from src.rule_engine import ActiveGameContext
from tests.test_lol_client import LOL_DATA, TFT_DATA


class _PluginConfigStub:
    def plugin_setting(self, _plugin_id, key, default=None):
        if key == "knowledge_include_enemy_champions":
            return False
        if key == "knowledge_max_champions":
            return 5
        return default


def test_web_knowledge_config_helpers(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text(
        'web_knowledge:\n'
        '  enabled: true\n'
        '  search_engine: google\n'
        '  refresh_interval_seconds: 180\n'
        '  timeout_seconds: 7\n'
        '  max_results_per_site: 2\n'
        '  max_pages: 5\n'
        '  hotkey: alt+`\n'
        '  window_width: 600\n'
        '  window_height: 800\n'
        '  default_sites_text: |\n'
        '    op.gg,100\n'
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n'
        '    knowledge_max_champions: 3\n'
        '    knowledge_search_sites_text: |\n'
        '      u.gg,95\n',
        encoding='utf-8',
    )
    cfg = Config(str(path))
    assert cfg.web_knowledge_enabled is True
    assert cfg.web_knowledge_search_engine == 'google'
    assert cfg.web_knowledge_refresh_interval_seconds == 180
    assert cfg.plugin_web_knowledge_enabled('lol') is True
    assert cfg.plugin_setting('lol', 'knowledge_max_champions') == 3


def test_lol_plugin_builds_web_knowledge_queries(tmp_path):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n'
        '    knowledge_max_champions: 2\n'
        '    knowledge_include_enemy_champions: false\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    queries = plugin.build_web_knowledge_queries(state, cfg)
    assert len(queries) == 2
    assert queries[0].title.endswith('玩法参考')
    assert 'League of Legends' in queries[0].query


def test_lol_plugin_can_optionally_include_enemy_champions(tmp_path):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n'
        '    knowledge_max_champions: 10\n'
        '    knowledge_include_enemy_champions: true\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    queries = plugin.build_web_knowledge_queries(state, cfg)
    titles = [query.title for query in queries]
    assert len(queries) >= 3
    assert any("Zed" in title for title in titles)


def test_lol_knowledge_sites_prefer_ugg_even_if_config_lists_opgg_first(tmp_path):
    from src.game_plugins.lol.knowledge import _knowledge_sites

    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_search_sites_text: |\n'
        '      op.gg,100\n'
        '      origin-lol.wzstats.gg,105\n'
        '      u.gg,95\n'
        '      leagueofgraphs.com,90\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    sites = _knowledge_sites(cfg)

    assert [site.domain for site in sites[:4]] == ["origin-lol.wzstats.gg", "u.gg", "leagueofgraphs.com", "op.gg"]


def test_tft_plugin_builds_web_knowledge_queries(tmp_path):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'plugin_settings:\n'
        '  tft:\n'
        '    knowledge_enabled: true\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = TftPlugin()
    state = plugin.extract_state(TFT_DATA, {})
    queries = plugin.build_web_knowledge_queries(state, cfg)
    assert len(queries) == 1
    assert 'meta comps' in queries[0].query


def test_tft_knowledge_sites_prefer_mobalytics_even_if_config_lists_tactics_first(tmp_path):
    from src.game_plugins.tft.knowledge import _knowledge_sites

    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'plugin_settings:\n'
        '  tft:\n'
        '    knowledge_search_sites_text: |\n'
        '      tactics.tools,100\n'
        '      lolchess.gg,95\n'
        '      mobalytics.gg,90\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    sites = _knowledge_sites(cfg)

    assert [site.domain for site in sites[:3]] == ["mobalytics.gg", "tactics.tools", "lolchess.gg"]


def test_web_knowledge_manager_collects_without_signature_method_regression(tmp_path, monkeypatch):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'web_knowledge:\n'
        '  enabled: true\n'
        '  refresh_interval_seconds: 300\n'
        '  search_engine: google\n'
        '  timeout_seconds: 5\n'
        '  max_results_per_site: 1\n'
        '  max_pages: 3\n'
        '  default_sites_text: |\n'
        '    op.gg,100\n'
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    context = ActiveGameContext(plugin=plugin, state=state)

    monkeypatch.setattr(plugin, "collect_web_knowledge_documents", lambda *_args, **_kwargs: [])

    manager = WebKnowledgeManager()
    bundle = manager.collect_for_context(context, cfg)

    assert bundle is not None
    assert bundle.plugin_id == "lol"


def test_web_knowledge_manager_reuses_cached_bundle_with_same_signature(tmp_path, monkeypatch):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'web_knowledge:\n'
        '  enabled: true\n'
        '  refresh_interval_seconds: 300\n'
        '  search_engine: google\n'
        '  timeout_seconds: 5\n'
        '  max_results_per_site: 1\n'
        '  max_pages: 3\n'
        '  default_sites_text: |\n'
        '    op.gg,100\n'
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    context = ActiveGameContext(plugin=plugin, state=state)

    calls = {"count": 0}

    def fake_collect(*_args, **_kwargs):
        calls["count"] += 1
        return []

    monkeypatch.setattr(plugin, "collect_web_knowledge_documents", fake_collect)

    manager = WebKnowledgeManager()
    bundle1 = manager.collect_for_context(context, cfg)
    bundle2 = manager.collect_for_context(context, cfg)

    assert bundle1 is bundle2
    assert calls["count"] == len(bundle1.items)


def test_web_knowledge_manager_stops_after_first_successful_site(tmp_path, monkeypatch):
    cfg_path = tmp_path / 'config.yaml'
    cfg_path.write_text(
        'web_knowledge:\n'
        '  enabled: true\n'
        '  refresh_interval_seconds: 300\n'
        '  search_engine: google\n'
        '  timeout_seconds: 5\n'
        '  max_results_per_site: 1\n'
        '  max_pages: 3\n'
        '  default_sites_text: |\n'
        '    op.gg,100\n'
        '    u.gg,95\n'
        'plugin_settings:\n'
        '  lol:\n'
        '    knowledge_enabled: true\n'
        '    knowledge_max_champions: 1\n',
        encoding='utf-8',
    )
    cfg = Config(str(cfg_path))
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    context = ActiveGameContext(plugin=plugin, state=state)

    seen = []

    def fake_collect(*args, **kwargs):
        seen.append(args[0].key)
        return []

    monkeypatch.setattr(plugin, "collect_web_knowledge_documents", fake_collect)

    manager = WebKnowledgeManager()
    manager.collect_for_context(context, cfg)

    assert seen == ["champion:Jinx"]


def test_render_knowledge_item_focuses_on_document_content():
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    query = plugin.build_web_knowledge_queries(state, _PluginConfigStub())[0]
    item = build_lol_web_knowledge_item(
        query,
        [
            SearchDocument(
                domain="op.gg",
                priority=100,
                title="Jinx Build",
                url="https://www.op.gg/champions/jinx/build",
                snippet="Patch 16.7 Jinx Build",
                excerpt="主流出装是暴击流，优先无尽和攻速装，小技巧是利用火箭炮拉扯。对线期注意三级前别被强开。",
                patch_version="16.7",
            )
        ],
        state,
        None,
    )
    rendered = render_knowledge_item(
        KnowledgeBundle(
            plugin_id="lol",
            display_name="League of Legends",
            summary="测试摘要",
            items=[item],
            generated_at=datetime.now(),
        ),
        0,
    )
    assert "主流出装是暴击流" in rendered
    assert "Jinx Build" in rendered
    assert "主流出装" in rendered
    assert "小技巧" in rendered


def test_render_knowledge_item_builds_tft_sections():
    plugin = TftPlugin()
    state = plugin.extract_state(TFT_DATA, {})
    query = plugin.build_web_knowledge_queries(state, None)[0]
    item = build_tft_web_knowledge_item(
        query,
        [
            SearchDocument(
                domain="tactics.tools",
                priority=100,
                title="TFT Meta Comps",
                url="https://tactics.tools/team-comps",
                snippet="Fast 8 flex and reroll comps.",
                excerpt="主流阵容是 Fast 8 Flex，运营思路是前期连胜保血，八人口再搜关键四费卡。站位要点是前排顶住、后排缩角保护主C。",
                patch_version="16.7",
            )
        ],
        state,
        None,
    )
    rendered = render_knowledge_item(
        KnowledgeBundle(
            plugin_id="tft",
            display_name="Teamfight Tactics",
            summary="测试摘要",
            items=[item],
            generated_at=datetime.now(),
        ),
        0,
    )
    assert "主流阵容" in rendered
    assert "运营思路" in rendered
    assert "站位要点" in rendered


def test_tft_collect_parser_extracts_mobalytics_comps():
    from src.game_plugins.tft.knowledge import _parse_tft_site_html

    html = """
    <html>
      <head>
        <title>TFT Meta Comps in Set 16</title>
        <meta name="description" content="Find out the strongest and most reliable meta Teamfight Tactics comps and builds.">
      </head>
      <body>
        <h1>TFT Meta Comps in Set 16</h1>
        <div>Create comp</div>
        <div>Bruiser Bear</div>
        <div>16.8</div>
        <div>Fast 8</div>
        <div>Medium</div>
        <div>Ryze Volibear Lissandra Wukong Taric Kennen Kobuko & Yuumi Sejuani Shen</div>
        <div>Copy team code</div>
        <div>Total Targon</div>
        <div>16.8</div>
        <div>Fast 8</div>
        <div>Medium</div>
        <div>Aurelion Sol Taric Seraphine Sylas Azir Shyvana Xerath Swain Vi</div>
        <div>Copy team code</div>
      </body>
    </html>
    """

    title, snippet, excerpt, sections, patch_version = _parse_tft_site_html("mobalytics.gg", "TFT Team Comps", html)

    assert title in {"TFT Meta Comps in Set 16", "TFT Team Comps"}
    assert "strongest and most reliable" in snippet
    assert patch_version == "16.8"
    rendered_sections = dict(sections)
    assert "Bruiser Bear" in rendered_sections["主流阵容概览"]
    assert "速8" in rendered_sections["推荐阵容 1"]
    assert "中等" in rendered_sections["推荐阵容 1"]
    assert "Ryze" in rendered_sections["推荐阵容 1"]
    assert "Total Targon" in rendered_sections["推荐阵容 2"]


def test_render_knowledge_item_skips_sections_for_noisy_text():
    plugin = LolPlugin()
    state = plugin.extract_state(LOL_DATA, {})
    query = plugin.build_web_knowledge_queries(state, _PluginConfigStub())[0]
    item = build_lol_web_knowledge_item(
        query,
        [
            SearchDocument(
                domain="op.gg",
                priority=100,
                title="Jinx Build",
                url="https://www.op.gg/champions/jinx/build",
                snippet="Patch 16.7 Jinx Build",
                excerpt="items,, , Runes, émon ? — émon + # % & türkiye + + + + + , % % Ban rate 4.91 % !",
                patch_version="16.7",
            )
        ],
        state,
        None,
    )
    rendered = render_knowledge_item(
        KnowledgeBundle(
            plugin_id="lol",
            display_name="League of Legends",
            summary="测试摘要",
            items=[item],
            generated_at=datetime.now(),
        ),
        0,
    )
    assert "主流出装" not in rendered
    assert "小技巧" not in rendered


def test_lol_collect_parser_ignores_script_shell_noise(monkeypatch):
    from src.game_plugins.lol.knowledge import _parse_lol_site_html

    html = """
    <html>
      <head>
        <title>Thresh Build - OP.GG</title>
        <meta name="description" content="Thresh Build with the highest win rate. Runes, items, and skill build in patch 16.7.">
        <script>
          if (theme dark && window.matchMedia('(prefers-color-scheme: dark)').matches) { document.body.dataset.theme = 'dark'; }
          inprogress = 1; top:0; left:0; width:100%;
        </script>
      </head>
      <body>
        <h1>Runes, and Items</h1>
        <div>Thresh Build with the highest win rate.</div>
      </body>
    </html>
    """

    title, snippet, excerpt, metadata = _parse_lol_site_html("op.gg", "Thresh", html)

    assert "Thresh Build" in title
    assert "highest win rate" in snippet
    assert "matchMedia" not in excerpt
    assert "top:0" not in excerpt
    assert metadata["quality"] == 30


def test_lol_collect_parser_extracts_structured_ugg_sections():
    from src.game_plugins.lol.knowledge import _parse_lol_site_html

    html = """
    <html>
      <head><title>Jinx Build - U.GG</title></head>
      <body>
        <script>
          window.__SSR_DATA__ = {
            "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/legacy-items.json": {
              "1055": {"name": "Doran's Blade"},
              "2003": {"name": "Health Potion"},
              "2523": {"name": "Yun Tal Wildarrows"},
              "3006": {"name": "Berserker's Greaves"},
              "3046": {"name": "Phantom Dancer"},
              "3031": {"name": "Infinity Edge"},
              "3094": {"name": "Rapid Firecannon"}
            },
            "https://static.bigbrain.gg/assets/lol/riot_static/16.7.1/data/en_US/summoner.json": {
              "4": {"name": "Flash"},
              "7": {"name": "Heal"}
            },
            "https://static.bigbrain.gg/assets/lol/riot_patch_update/prod/backup-champions.json": {
              "18": {"name": "Tristana"},
              "202": {"name": "Jhin"},
              "51": {"name": "Caitlyn"}
            },
            "https://static.bigbrain.gg/assets/lol/riot_static/16.7.1/data/en_US/runesReforged.json": [
              {"id": 8000, "name": "Precision", "slots": [{"runes": [{"id": 8008, "name": "Lethal Tempo"}]}]},
              {"id": 8300, "name": "Inspiration", "slots": [{"runes": [{"id": 8313, "name": "Triple Tonic"}]}]}
            ],
            "overview_emerald_plus_world_recommended::https://stats2.u.gg/lol/1.5/overview/16_7/ranked_solo_5x5/222/1.5.0.json": {
              "data": {
                "world_emerald_plus_jungle": {
                  "rec_runes": {
                    "primary_style": 8000,
                    "sub_style": 8300,
                    "active_perks": [8008, 8313]
                  },
                  "rec_summoner_spells": {"ids": [4, 11]},
                  "rec_starting_items": {"ids": [1055, 2003]},
                  "rec_core_items": {"ids": [2523, 3006, 3046]},
                  "rec_skills": {"slots": ["Q", "W", "E"]},
                  "matches": 1,
                  "win_rate": 100
                },
                "world_emerald_plus_adc": {
                  "rec_runes": {
                    "primary_style": 8000,
                    "sub_style": 8300,
                    "active_perks": [8008, 8313]
                  },
                  "rec_summoner_spells": {"ids": [4, 7]},
                  "rec_starting_items": {"ids": [1055, 2003]},
                  "rec_core_items": {"ids": [2523, 3006, 3046]},
                  "item_options_1": [{"id": 3031}, {"id": 3094}],
                  "rec_skills": {"slots": ["Q", "W", "E"]},
                  "matches": 15321,
                  "win_rate": 51.7
                }
              }
            },
            "rankings_emerald_plus_world::https://stats2.u.gg/lol/1.5/rankings/16_7/ranked_solo_5x5/222/1.5.0.json": {
              "data": {
                "world_emerald_plus_adc": {
                  "rank": 7,
                  "pick_rate": 16.4,
                  "ban_rate": 4.9,
                  "matches": 15321,
                  "win_rate": 51.7,
                  "counters": [
                    {"champion_id": 18, "win_rate": 56.2},
                    {"champion_id": 202, "win_rate": 55.1},
                    {"champion_id": 51, "win_rate": 54.8},
                    {"champion_id": 202, "win_rate": 46.2},
                    {"champion_id": 51, "win_rate": 45.7}
                  ]
                }
              }
            }
          };
        </script>
      </body>
    </html>
    """

    title, snippet, excerpt, metadata = _parse_lol_site_html("u.gg", "Jinx", html)

    assert "Jinx Build" in title
    assert metadata["source"] == "u.gg-ssr"
    assert metadata["patch_version"] == "16.7"
    sections = dict(metadata["sections"])
    assert sections["版本"] == "16.7"
    assert sections["主位置"] == "下路"
    assert "Doran's Blade" in sections["出门装"]
    assert "Yun Tal Wildarrows" in sections["核心三件"]
    assert "Infinity Edge" in sections["可选装备"]
    assert "精密" in sections["符文"]
    assert "启迪" in sections["符文"]
    assert "闪现 + 治疗" == sections["召唤师技能"]
    assert "Q > W > E" == sections["技能加点"]
    assert "Tristana" in sections["对线提醒"]
    assert "Jhin" in sections["优势对线"]
    assert "胜率 51.7%" in sections["数据概览"]


def test_lol_collect_parser_extracts_wzstats_sections():
    from src.game_plugins.lol.knowledge import _parse_lol_site_html

    html = """
    <html>
      <head>
        <title>Yasuo Performance - Win Rate, Stats & Skill Curve | Patch 26.5 | LoLStats</title>
        <meta name="description" content="Yasuo has a consistent win rate across all game lengths. Thrives in Diamond+ and rewards mechanical skill and game knowledge.">
      </head>
      <body>
        <h1>Yasuo Overall Performance in Mid</h1>
        <div>Power Spike</div>
        <div>Steady</div>
        <div>Consistent win rate across all game lengths</div>
        <div>Elo</div>
        <div>High Elo</div>
        <div>Thrives in Diamond+ — rewards mechanical skill and game knowledge</div>
        <div>Skill Curve</div>
        <div>Moderate</div>
        <div>Rewards some practice — noticeable improvement after a few games</div>
        <div>Performance</div>
        <div>Win Rate</div>
        <div>50.1%</div>
        <div>Carry Score</div>
        <div>4.14</div>
        <div>Combat</div>
        <div>KDA</div>
        <div>1.65</div>
        <div>Kills/game</div>
        <div>6.6</div>
        <div>Deaths/game</div>
        <div>7.5</div>
        <div>Assists/game</div>
        <div>5.7</div>
        <div>Economy & Vision</div>
        <div>CS/min</div>
        <div>7.6</div>
        <div>Gold/min</div>
        <div>430</div>
        <div>Vision Score</div>
        <div>20.6</div>
      </body>
    </html>
    """

    title, snippet, excerpt, metadata = _parse_lol_site_html("origin-lol.wzstats.gg", "Yasuo", html)

    assert "Yasuo Performance" in title
    assert metadata["source"] == "wzstats"
    sections = dict(metadata["sections"])
    assert sections["推荐位置"] == "中单"
    assert "平稳成型" in sections["强势期"]
    assert "高分段更强" in sections["适合分段"]
    assert "操作理解" in sections["适合分段"]
    assert "熟练几局后胜率提升明显" in sections["上手难度"]
    assert "胜率 50.1%" in sections["核心数据"]
    assert "每分钟补刀 7.6" in sections["经济与视野"]


def test_lol_collect_parser_extracts_wzstats_against_sections():
    from src.game_plugins.lol.knowledge import _parse_lol_site_html

    html = """
    <html>
      <head>
        <title>Yasuo Against Guide | LoLStats</title>
        <meta name="description" content="Punish Yasuo when Wind Wall is down and avoid long trades after his item spike.">
      </head>
      <body>
        <h1>How to Counter Yasuo</h1>
        <div>Punish</div>
        <div>Attack after Wind Wall is down and force short trades around his cooldowns.</div>
        <div>Avoid</div>
        <div>Avoid long extended fights once Yasuo has his first crit item.</div>
        <div>Respect</div>
        <div>Respect his level 6 all-in when the wave is on his side.</div>
      </body>
    </html>
    """

    title, snippet, excerpt, metadata = _parse_lol_site_html("origin-lol.wzstats.gg", "Yasuo", html)

    assert "Yasuo" in title
    assert metadata["source"] == "wzstats"
    sections = dict(metadata["sections"])
    assert "风墙进入冷却后立刻反打" in sections["对线提醒"]
    assert "暴击装" in sections["需要避免"]
    assert "六级一套爆发" in sections["关键时机"]
