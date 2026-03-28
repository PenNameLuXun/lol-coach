import sqlite3
from datetime import datetime
from typing import Optional


class History:
    def __init__(self, db_path: str = "lol_coach.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                started TEXT NOT NULL,
                ended   TEXT
            );
            CREATE TABLE IF NOT EXISTS advice (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER REFERENCES sessions(id),
                timestamp  TEXT NOT NULL,
                text       TEXT NOT NULL,
                trigger    TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def start_session(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started) VALUES (?)",
            (datetime.now().isoformat(),)
        )
        self._conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int):
        self._conn.execute(
            "UPDATE sessions SET ended = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        self._conn.commit()

    def list_sessions(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM sessions ORDER BY started DESC")
        return [dict(row) for row in cur.fetchall()]

    def add_advice(self, text: str, trigger: str, session_id: Optional[int] = None):
        self._conn.execute(
            "INSERT INTO advice (session_id, timestamp, text, trigger) VALUES (?, ?, ?, ?)",
            (session_id, datetime.now().isoformat(), text, trigger)
        )
        self._conn.commit()

    def list_advice(self, session_id: Optional[int] = None) -> list[dict]:
        if session_id is not None:
            cur = self._conn.execute(
                "SELECT * FROM advice WHERE session_id = ? ORDER BY timestamp",
                (session_id,)
            )
        else:
            cur = self._conn.execute("SELECT * FROM advice ORDER BY timestamp")
        return [dict(row) for row in cur.fetchall()]

    def export_session(self, session_id: int) -> str:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        lines = [f"=== 场次 {session_id} | 开始: {rows['started']} 结束: {rows['ended'] or '进行中'} ==="]
        for row in self.list_advice(session_id=session_id):
            lines.append(f"[{row['timestamp']}] ({row['trigger']}) {row['text']}")
        return "\n".join(lines)

    def close(self):
        self._conn.close()
