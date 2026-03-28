import os
import pytest
from src.history import History


@pytest.fixture
def db(tmp_path):
    h = History(str(tmp_path / "test.db"))
    yield h
    h.close()


def test_add_and_list_advice(db):
    db.add_advice("push top", "timer")
    rows = db.list_advice()
    assert len(rows) == 1
    assert rows[0]["text"] == "push top"
    assert rows[0]["trigger"] == "timer"


def test_multiple_advice(db):
    db.add_advice("ward river", "hotkey")
    db.add_advice("recall now", "timer")
    rows = db.list_advice()
    assert len(rows) == 2


def test_session_grouping(db):
    session_id = db.start_session()
    db.add_advice("push mid", "timer", session_id=session_id)
    db.end_session(session_id)
    sessions = db.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    rows = db.list_advice(session_id=session_id)
    assert len(rows) == 1
    assert rows[0]["text"] == "push mid"


def test_export_text(db):
    session_id = db.start_session()
    db.add_advice("attack baron", "timer", session_id=session_id)
    db.end_session(session_id)
    text = db.export_session(session_id)
    assert "attack baron" in text


def test_advice_without_session(db):
    db.add_advice("buy item", "hotkey")
    rows = db.list_advice(session_id=None)
    assert any(r["text"] == "buy item" for r in rows)
