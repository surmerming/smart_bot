"""接口测试：init / stream(SSE) / bind / feedback / handover / 安全拦截。

Mock LLM 模式下离线运行，覆盖核心闭环（知识库内 / 未命中 / 高风险 / 轮次上限 / Token 校验）。
"""
import json

from conftest import client


def _init_session(session_id: str | None = None):
    resp = client.post("/api/v1/chat/init", json={"session_id": session_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["session_id"]
    assert data["visitor_token"]
    assert data["brand_name"]
    return data


def _parse_sse(text: str):
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev_type = "message"
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
        if data_str:
            events.append((ev_type, json.loads(data_str)))
    return events


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["faqs"] >= 30
    assert body["llm_mode"] == "mock"


def test_chat_init_and_history_restore():
    first = _init_session()
    sid = first["session_id"]

    # 发一条消息后再次 init，应能恢复历史（解决"视觉失忆"）
    token = first["visitor_token"]
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": sid, "visitor_token": token, "message": "支持7天无理由退换吗",
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e[0] for e in events]
    assert "meta" in types and "text" in types and "done" in types
    full = "".join(e[1].get("content", "") for e in events if e[0] == "text")
    assert full  # Mock 模式下有回答

    restored = _init_session(sid)
    assert len(restored["history"]) == 2  # user + assistant


def test_stream_kb_hit_flow():
    data = _init_session()
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"],
        "visitor_token": data["visitor_token"],
        "message": "拆了包装还能退吗",
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    assert meta["status"] == "answering"
    assert "faq_001" in meta["faq_ids"]
    assert meta["handover"] is False
    done = next(e[1] for e in events if e[0] == "done")
    assert done["handover"] is False
    assert done["message_id"]


def test_stream_low_confidence_handover():
    data = _init_session()
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"],
        "visitor_token": data["visitor_token"],
        "message": "今天天气怎么样",
    })
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    assert meta["status"] in ("handover", "confirming")
    done = next(e[1] for e in events if e[0] == "done")
    assert done["handover"] is True


def test_stream_high_risk_red_light():
    data = _init_session()
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"],
        "visitor_token": data["visitor_token"],
        "message": "我要投诉！东西坏了你们管不管",
    })
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    assert meta["handover"] is True
    assert meta["emotion"] == "LEVEL_3"
    done = next(e[1] for e in events if e[0] == "done")
    assert done["handover"] is True
    # 转人工后会话状态打标
    from app.storage.db import db

    assert db.get_session(data["session_id"])["status"] == "HANDOVER"
    assert db.list_handovers()


def test_stream_invalid_token_rejected():
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": "sess_invalid123456",
        "visitor_token": "forged.token.xxx",
        "message": "你好",
    })
    assert resp.status_code == 401


def test_session_bind():
    data = _init_session()
    resp = client.post("/api/v1/session/bind", json={
        "anonymous_session_id": data["session_id"],
        "user_id": "user_9527",
    })
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "user_9527"
    from app.storage.db import db

    assert db.get_session(data["session_id"])["user_id"] == "user_9527"


def test_feedback():
    data = _init_session()
    resp = client.post("/api/v1/feedback", json={
        "session_id": data["session_id"],
        "value": "down",
        "query": "支持7天无理由吗",
        "answer": "支持",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_handover_manual():
    data = _init_session()
    resp = client.post("/api/v1/handover", json={
        "session_id": data["session_id"],
        "visitor_token": data["visitor_token"],
        "contact": "13800138000",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_session_turn_limit():
    # 临时把上限调低验证熔断
    import app.config as cfg

    old = cfg.settings.SESSION_MAX_TURNS
    cfg.settings.SESSION_MAX_TURNS = 2
    try:
        data = _init_session()
        token = data["visitor_token"]
        for i in range(3):
            resp = client.post("/api/v1/chat/stream", json={
                "session_id": data["session_id"], "visitor_token": token, "message": f"问题{i}",
            })
            events = _parse_sse(resp.text)
            meta = next(e[1] for e in events if e[0] == "meta")
            if i < 2:
                assert meta["status"] != "limit"
            else:
                assert meta["status"] == "limit"
    finally:
        cfg.settings.SESSION_MAX_TURNS = old
