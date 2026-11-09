"""Lightweight paper history (M10).

stdlib sqlite3 only — no new dependencies, no auth. Stores generated papers
with their blueprint + validation snapshot so teachers can reopen, duplicate
or selectively regenerate later.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

_lock = threading.Lock()
_db_path: Optional[str] = None


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    with _db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS papers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                total_marks INTEGER NOT NULL DEFAULT 0,
                n_questions INTEGER NOT NULL DEFAULT 0,
                blueprint_json TEXT,
                paper_json TEXT NOT NULL,
                validation_json TEXT
            )"""
        )


def _conn() -> sqlite3.Connection:
    assert _db_path, "history DB not initialised"
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """Locked connection that commits on success and always closes.

    ``with sqlite3.connect(...)`` only manages transactions; it does not close
    the connection. Long-running servers therefore leaked file descriptors and
    eventually hit SQLite "too many open files" errors.
    """
    with _lock:
        conn = _conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def save_paper(title: str, subject: str, total_marks: int, n_questions: int,
               paper: Dict[str, Any], blueprint: Optional[Dict[str, Any]],
               validation: Optional[Dict[str, Any]]) -> int:
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO papers(title, subject, created_at, total_marks, n_questions,"
            " blueprint_json, paper_json, validation_json) VALUES(?,?,?,?,?,?,?,?)",
            (title[:200], subject[:200], datetime.now().isoformat(timespec="seconds"),
             int(total_marks or 0), int(n_questions or 0),
             json.dumps(blueprint) if blueprint is not None else None,
             json.dumps(paper), json.dumps(validation) if validation is not None else None),
        )
        return int(cur.lastrowid)


def list_papers() -> List[Dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, title, subject, created_at, total_marks, n_questions"
            " FROM papers ORDER BY id DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


def get_paper(paper_id: int) -> Optional[Dict[str, Any]]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("blueprint_json", "paper_json", "validation_json"):
        d[key.replace("_json", "")] = json.loads(d[key]) if d.get(key) else None
    return d


def delete_paper(paper_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        return cur.rowcount > 0
