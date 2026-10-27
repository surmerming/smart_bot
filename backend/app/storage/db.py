"""SQLite 存储：会话 / 消息 / 反馈 / 人工排队。MVP 单文件库，线程锁保护。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Optional

from app.config import settings


def new_session_id() -> str:
    return "sess_" + uuid.uuid4().hex


class Database:
    def __init__(self, db_path=None) -> None:
        self._path = str(db_path or settings.DB_PATH)
        self._lock = threading.Lock()
        self._conn = None
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        # 每线程独立连接，避免跨线程共享
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self) -> None:
        import os

        os.makedirs(self._path.rsplit("/", 1)[0] or ".", exist_ok=True)
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                anonymous_id TEXT,
                user_id TEXT,
                status TEXT DEFAULT 'AGENT_ACTIVE',
                turn_count INTEGER DEFAULT 0,
                meta TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                message_id TEXT,
                value TEXT,
                query TEXT,
                context TEXT,
                answer TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS handover_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                summary TEXT,
                contact TEXT,
                status TEXT DEFAULT 'waiting',
                created_at TEXT
            );
            """
        )
        conn.commit()
        conn.close()

    # ================= 会话 =================
    def create_session(self, session_id: str, anonymous_id: str | None = None,
                       user_id: str | None = None) -> None:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, anonymous_id, user_id, status, turn_count, meta, created_at, updated_at) "
                "VALUES (?, ?, ?, 'AGENT_ACTIVE', 0, '{}', ?, ?)",
                (session_id, anonymous_id or session_id, user_id, now, now),
            )
            conn.commit()
            conn.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            conn.close()
            if not row:
                return None
            d = dict(row)
            try:
                d["meta"] = json.loads(d.get("meta") or "{}")
            except json.JSONDecodeError:
                d["meta"] = {}
            return d

    def update_session(self, session_id: str, **kwargs) -> None:
        allowed = {"status", "turn_count", "meta", "user_id", "anonymous_id"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        if "meta" in updates and isinstance(updates["meta"], dict):
            updates["meta"] = json.dumps(updates["meta"], ensure_ascii=False)
        updates["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cols = ", ".join(f"{k}=?" for k in updates)
        with self._lock:
            conn = self._connect()
            conn.execute(f"UPDATE sessions SET {cols} WHERE id=?", (*updates.values(), session_id))
            conn.commit()
            conn.close()

    def bind_user(self, session_id: str, user_id: str) -> None:
        """登录瞬间绑定：anonymous_session_id ↔ user_id。"""
        self.update_session(session_id, user_id=user_id)

    # ================= 消息 =================
    def add_message(self, session_id: str, role: str, content: str) -> int:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            conn.commit()
            mid = cur.lastrowid
            conn.close()
            return mid

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            conn.close()
        return [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]} for r in reversed(rows)]

    # ================= 反馈 =================
    def add_feedback(self, session_id: str, message_id: str | None, value: str,
                     query: str | None, context: str | None, answer: str | None) -> int:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO feedback (session_id, message_id, value, query, context, answer, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, message_id, value, query, context, answer, now),
            )
            conn.commit()
            fid = cur.lastrowid
            conn.close()
            return fid

    # ================= 反馈统计（V1.5 运营看板）=================
    def feedback_stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            rows = conn.execute("SELECT value, COUNT(*) AS cnt FROM feedback GROUP BY value").fetchall()
            conn.close()
        counts = {r["value"]: r["cnt"] for r in rows}
        up = counts.get("up", 0)
        down = counts.get("down", 0)
        total = up + down
        return {
            "feedback_total": total,
            "feedback_up": up,
            "feedback_down": down,
            "up_rate": round(up / total, 4) if total else None,
        }

    def list_badcases(self, limit: int = 20) -> list[dict]:
        """点踩记录（Bad Case 归因的原料）。"""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM feedback WHERE value='down' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    # ================= 人工排队（留言转人工，MVP 无 WebSocket）=================
    def enqueue_handover(self, session_id: str, summary: str, contact: str | None = None) -> int:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO handover_queue (session_id, summary, contact, status, created_at) VALUES (?, ?, ?, 'waiting', ?)",
                (session_id, summary, contact, now),
            )
            conn.commit()
            qid = cur.lastrowid
            conn.close()
            return qid

    def list_handovers(self, status: str = "waiting") -> list[dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM handover_queue WHERE status=? ORDER BY id ASC", (status,)
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    # ================= 人工排队（V1.5：排队进度）=================
    def get_handover(self, queue_id: int) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM handover_queue WHERE id=?", (queue_id,)).fetchone()
            conn.close()
        return dict(row) if row else None

    def complete_handover(self, queue_id: int) -> bool:
        """坐席标记处理完成（仅 waiting → done）。"""
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE handover_queue SET status='done' WHERE id=? AND status='waiting'", (queue_id,)
            )
            conn.commit()
            ok = cur.rowcount > 0
            conn.close()
        return ok

    def queue_status(self, queue_id: int) -> Optional[dict]:
        """排队进度：位置 / 前面还有几人 / 状态。"""
        row = self.get_handover(queue_id)
        if not row:
            return None
        waiting = self.list_handovers("waiting")
        position = None
        for i, r in enumerate(waiting, start=1):
            if r["id"] == queue_id:
                position = i
                break
        return {
            "queue_id": queue_id,
            "position": position,
            "ahead": (position - 1) if position is not None else None,
            "status": row["status"],
            "created_at": row["created_at"],
        }

    # ================= 运营统计（6.1 科学统计口径）=================
    def session_stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            rows = conn.execute("SELECT status, COUNT(*) AS cnt FROM sessions GROUP BY status").fetchall()
            conn.close()
        stats = {r["status"]: r["cnt"] for r in rows}
        total = sum(stats.values())
        agent = stats.get("AGENT_ACTIVE", 0)
        handover = stats.get("HANDOVER", 0)
        return {
            "total_sessions": total,
            "agent_resolved": agent,
            "handover": handover,
            "auto_rate": round(agent / total, 4) if total else 0.0,
        }


db = Database()
