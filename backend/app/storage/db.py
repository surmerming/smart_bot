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
            -- V2.0 知识库后台：FAQ 变更草稿 / 审批流
            -- status: draft(草稿) -> pending(待审) -> published(已生效) / rejected(已驳回)
            CREATE TABLE IF NOT EXISTS faq_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faq_id TEXT,
                action TEXT,                 -- create / update / delete
                payload TEXT,                -- 完整 FAQ JSON（delete 时可为删除前快照）
                status TEXT DEFAULT 'draft',
                created_by TEXT DEFAULT 'ops',
                reviewed_by TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            -- V2.0 知识库后台：版本历史（每次审批生效记一条，含完整快照）
            CREATE TABLE IF NOT EXISTS faq_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faq_id TEXT,
                action TEXT,                 -- create / update / delete
                snapshot TEXT,               -- 发布后快照 JSON（delete 为删除前快照）
                operator TEXT DEFAULT 'ops',
                created_at TEXT
            );
            """
        )
        # V2.0 迁移：坐席 Copilot 数据列（工单卡片 + 回复模板），旧库自动加列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(handover_queue)").fetchall()]
        if "copilot" not in cols:
            conn.execute("ALTER TABLE handover_queue ADD COLUMN copilot TEXT DEFAULT '{}'")
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

    def get_waiting_by_session(self, session_id: str) -> Optional[dict]:
        """某会话当前 waiting 的排队项（WebSocket 建连时推送进度用）。"""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM handover_queue WHERE session_id=? AND status='waiting' "
                "ORDER BY id ASC LIMIT 1",
                (session_id,),
            ).fetchone()
            conn.close()
        return dict(row) if row else None

    # ================= 坐席 Copilot（V2.0）=================
    def set_copilot(self, queue_id: int, copilot: dict) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE handover_queue SET copilot=? WHERE id=?",
                (json.dumps(copilot, ensure_ascii=False), queue_id),
            )
            conn.commit()
            conn.close()

    def get_handover_copilot(self, queue_id: int) -> dict:
        row = self.get_handover(queue_id)
        if not row:
            return {}
        try:
            data = json.loads(row.get("copilot") or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

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

    # ================= 知识库后台（V2.0）：FAQ 草稿 / 审批流 =================
    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def create_faq_draft(self, faq_id: str, action: str, payload: dict | None,
                         created_by: str = "ops") -> int:
        """创建 FAQ 变更草稿（create / update / delete）。返回 draft_id。"""
        now = self._now()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO faq_drafts (faq_id, action, payload, status, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, 'draft', ?, ?, ?)",
                (faq_id, action, payload_json, created_by, now, now),
            )
            conn.commit()
            did = cur.lastrowid
            conn.close()
            return did

    def list_faq_drafts(self, status: str | None = None) -> list[dict]:
        """草稿列表；status 可为 draft / pending / rejected / published / None(全部)。"""
        with self._lock:
            conn = self._connect()
            if status:
                rows = conn.execute(
                    "SELECT * FROM faq_drafts WHERE status=? ORDER BY id DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM faq_drafts ORDER BY id DESC").fetchall()
            conn.close()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "null")
            except json.JSONDecodeError:
                d["payload"] = None
            out.append(d)
        return out

    def get_faq_draft(self, draft_id: int) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM faq_drafts WHERE id=?", (draft_id,)).fetchone()
            conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["payload"] = json.loads(d.get("payload") or "null")
        except json.JSONDecodeError:
            d["payload"] = None
        return d

    def set_faq_draft_status(self, draft_id: int, status: str, reviewed_by: str | None = None) -> bool:
        """状态流转：draft -> pending -> published / rejected（仅允许合法前进，防并发跳转）。"""
        allowed = {
            ("draft", "pending"): True,
            ("pending", "published"): True,
            ("pending", "rejected"): True,
            ("rejected", "pending"): True,   # 驳回后可修改再提交
        }
        now = self._now()
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT status FROM faq_drafts WHERE id=?", (draft_id,)).fetchone()
            if not row:
                conn.close()
                return False
            if not allowed.get((row["status"], status), False):
                conn.close()
                return False
            if status == "rejected" or status == "published":
                cur = conn.execute(
                    "UPDATE faq_drafts SET status=?, reviewed_by=?, updated_at=? WHERE id=?",
                    (status, reviewed_by or "ops", now, draft_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE faq_drafts SET status=?, updated_at=? WHERE id=?",
                    (status, now, draft_id),
                )
            conn.commit()
            ok = cur.rowcount > 0
            conn.close()
            return ok

    def delete_faq_draft(self, draft_id: int) -> bool:
        """撤销草稿（仅 draft / rejected 态可删）。"""
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "DELETE FROM faq_drafts WHERE id=? AND status IN ('draft','rejected')", (draft_id,)
            )
            conn.commit()
            ok = cur.rowcount > 0
            conn.close()
        return ok

    # ================= 知识库后台（V2.0）：版本历史 =================
    def add_faq_version(self, faq_id: str, action: str, snapshot: dict | None, operator: str = "ops") -> int:
        now = self._now()
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO faq_versions (faq_id, action, snapshot, operator, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (faq_id, action, json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
                 operator, now),
            )
            conn.commit()
            vid = cur.lastrowid
            conn.close()
            return vid

    def list_faq_versions(self, faq_id: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._connect()
            if faq_id:
                rows = conn.execute(
                    "SELECT * FROM faq_versions WHERE faq_id=? ORDER BY id DESC LIMIT ?",
                    (faq_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM faq_versions ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            conn.close()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["snapshot"] = json.loads(d.get("snapshot") or "null")
            except json.JSONDecodeError:
                d["snapshot"] = None
            out.append(d)
        return out


db = Database()
