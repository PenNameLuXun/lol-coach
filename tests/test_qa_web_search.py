from src.qa_channel import QaQuestion, build_qa_prompt
from src.qa_web_search import (
    SearchDocument,
    merge_search_sites,
    parse_search_sites_text,
    sort_search_documents,
)


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
