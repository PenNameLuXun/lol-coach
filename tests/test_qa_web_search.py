from src.qa_channel import QaQuestion, build_qa_prompt
from src.search.engine import _direct_content_candidates
from src.search.html_extract import extract_excerpt_from_html as _extract_excerpt_from_html
from src.search.models import SearchDocument
from src.search.sites import merge_search_sites, parse_search_sites_text
from src.search.formatting import sort_search_documents


def test_parse_search_sites_text_and_merge_priority():
    global_sites = parse_search_sites_text("mobafire.com,70\nu.gg,80")
    plugin_sites = parse_search_sites_text("op.gg,100\nu.gg,95")

    merged = merge_search_sites(global_sites, plugin_sites)

    assert [(site.domain, site.priority) for site in merged] == [
        ("op.gg", 100),
        ("u.gg", 95),
        ("mobafire.com", 70),
    ]


def test_build_qa_prompt_includes_web_search_context():
    prompt = build_qa_prompt(
        question=QaQuestion(speaker="玩家", text="亚索怎么打阿卡丽？", source_kind="file", raw_data={}),
        system_prompt="你是游戏问答助手",
        active_context=None,
        snapshots=[],
        rule_advice=None,
        web_search_docs=[
            SearchDocument(
                domain="op.gg",
                priority=100,
                title="Yasuo vs Akali",
                url="https://www.op.gg/champions/yasuo",
                snippet="对线需要注意前三级换血。",
                excerpt="优先处理前三级兵线，避免被阿卡丽 E 命中后持续追击。",
                patch_version="16.5",
            )
        ],
    )

    assert "联网搜索资料" in prompt
    assert "op.gg" in prompt
    assert "前三级" in prompt
    assert "版本: 16.5" in prompt


def test_sort_search_documents_prefers_newer_patch():
    docs = [
        SearchDocument(
            domain="op.gg",
            priority=100,
            title="Yasuo Mid Build Patch 15.22",
            url="https://www.op.gg/champions/yasuo",
            snippet="Patch 15.22",
            excerpt="",
            patch_version="15.22",
        ),
        SearchDocument(
            domain="u.gg",
            priority=95,
            title="Yasuo Build Patch 16.5",
            url="https://u.gg/lol/champions/yasuo/build",
            snippet="Patch 16.5",
            excerpt="",
            patch_version="16.5",
        ),
    ]

    ordered = sort_search_documents(docs)

    assert [doc.domain for doc in ordered] == ["u.gg", "op.gg"]


def test_extract_excerpt_prefers_meta_description_for_lol_sites():
    html = """
    <html>
      <head>
        <meta name="description" content="Yasuo build guide for current patch with runes and items.">
      </head>
      <body>
        <h1>Yasuo Build</h1>
        <p>Some long generic body text.</p>
      </body>
    </html>
    """

    excerpt = _extract_excerpt_from_html(url="https://www.op.gg/champions/yasuo/build", html=html)

    assert "Yasuo build guide for current patch" in excerpt
    assert "Yasuo Build" in excerpt


def test_extract_excerpt_uses_headings_and_body_for_tft_sites():
    html = """
    <html>
      <head>
        <meta property="og:description" content="Best TFT comps for the current patch.">
      </head>
      <body>
        <h1>TFT Meta Comps</h1>
        <h2>Fast 8 Flex</h2>
        <p>Play strongest board early and pivot into capped four-cost carries.</p>
      </body>
    </html>
    """

    excerpt = _extract_excerpt_from_html(url="https://tactics.tools/team-comps", html=html)

    assert "Best TFT comps for the current patch" in excerpt
    assert "Fast 8 Flex" in excerpt
    assert "pivot into capped four-cost carries" in excerpt


def test_direct_content_candidates_for_lol_sites_prefer_champion_pages():
    candidates = _direct_content_candidates("op.gg", "League of Legends Jinx build guide combos lane tips current patch")

    assert candidates
    assert candidates[0]["url"].endswith("/champions/jinx/build")


def test_direct_content_candidates_for_tft_sites_prefer_meta_pages():
    candidates = _direct_content_candidates("tactics.tools", "current TFT meta comps patch set guide")

    assert candidates
    assert candidates[0]["url"] == "https://tactics.tools/team-comps"
