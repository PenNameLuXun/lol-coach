from PyQt6.QtWidgets import QApplication

from datetime import datetime

from src.qa_web_search import SearchDocument
from src.game_plugins.lol.knowledge import populate_lol_web_knowledge_window
from src.game_plugins.tft.knowledge import populate_tft_web_knowledge_window
from src.ui.knowledge_window import KnowledgeWindow
from src.web_knowledge import KnowledgeBundle, KnowledgeItem


def test_knowledge_window_can_be_revived_after_dismiss():
    app = QApplication.instance() or QApplication([])
    window = KnowledgeWindow()

    window.show()
    window.dismiss()
    assert window.is_dismissed is True

    window.revive()
    assert window.is_dismissed is False


def test_knowledge_window_paginates_items():
    app = QApplication.instance() or QApplication([])
    window = KnowledgeWindow()
    bundle = KnowledgeBundle(
        plugin_id="lol",
        display_name="League of Legends",
        summary="测试摘要",
        items=[
            KnowledgeItem(
                key="champion:Jinx",
                tab_label="Jinx",
                title="Jinx 玩法参考",
                query="jinx build",
                documents=[SearchDocument("op.gg", 100, "Jinx Build", "https://example.com/jinx", "snippet", "excerpt")],
            ),
            KnowledgeItem(
                key="champion:Thresh",
                tab_label="Thresh",
                title="Thresh 玩法参考",
                query="thresh build",
                documents=[SearchDocument("u.gg", 95, "Thresh Build", "https://example.com/thresh", "snippet", "excerpt")],
            ),
        ],
        generated_at=datetime.now(),
    )

    window.update_bundle(bundle)
    assert window._tabs.count() == 2
    assert window._tabs.tabText(0) == "Jinx"
    assert window._tabs.tabText(1) == "Thresh"

    window._tabs.setCurrentIndex(1)
    assert window._tabs.currentIndex() == 1


def test_lol_plugin_can_own_knowledge_window_content():
    app = QApplication.instance() or QApplication([])
    window = KnowledgeWindow()
    bundle = KnowledgeBundle(
        plugin_id="lol",
        display_name="League of Legends",
        summary="测试摘要",
        items=[
            KnowledgeItem(
                key="champion:Jinx",
                tab_label="Jinx",
                title="Jinx 玩法参考",
                query="jinx build",
                documents=[SearchDocument("op.gg", 100, "Jinx Build", "https://example.com/jinx", "snippet", "excerpt")],
                sections=[("主流出装", "无尽之刃")],
            ),
            KnowledgeItem(
                key="champion:Thresh",
                tab_label="Thresh",
                title="Thresh 玩法参考",
                query="thresh build",
                documents=[SearchDocument("u.gg", 95, "Thresh Build", "https://example.com/thresh", "snippet", "excerpt")],
                sections=[("小技巧", "先手留灯笼")],
            ),
        ],
        generated_at=datetime.now(),
    )

    handled = populate_lol_web_knowledge_window(window, bundle, None, None)
    assert handled is True
    assert window._title_label.text().startswith("League of Legends")
    assert window._content_widget is not None


def test_tft_plugin_can_own_knowledge_window_content():
    app = QApplication.instance() or QApplication([])
    window = KnowledgeWindow()
    bundle = KnowledgeBundle(
        plugin_id="tft",
        display_name="Teamfight Tactics",
        summary="测试摘要",
        items=[
            KnowledgeItem(
                key="tft-meta-comps",
                tab_label="主流阵容",
                title="当前主流阵容",
                query="tft meta",
                documents=[SearchDocument("tactics.tools", 100, "Meta", "https://example.com/tft", "snippet", "excerpt")],
                sections=[("主流阵容", "Fast 8 Flex")],
            ),
        ],
        generated_at=datetime.now(),
    )

    handled = populate_tft_web_knowledge_window(window, bundle, None, None)
    assert handled is True
    assert window._content_widget is not None
