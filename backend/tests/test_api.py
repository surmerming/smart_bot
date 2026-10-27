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


def test_queue_status_and_complete():
    """V1.5 排队进度 + 坐席完成闭环。"""
    from app.storage.db import db

    data = _init_session()
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "message": "我要投诉！产品坏了你们管不管",
    })
    assert resp.status_code == 200
    queue = db.list_handovers("waiting")
    assert queue
    qid = queue[-1]["id"]

    st = client.get(f"/api/v1/ops/queue/status?queue_id={qid}")
    assert st.status_code == 200
    body = st.json()
    assert body["status"] == "waiting"
    assert body["position"] >= 1

    done = client.post(f"/api/v1/ops/handovers/{qid}/complete")
    assert done.status_code == 200
    assert db.get_handover(qid)["status"] == "done"


def test_ops_stats_with_feedback():
    """V1.5 运营看板：stats 含点赞率；badcases 返回点踩记录。"""
    data = _init_session()
    client.post("/api/v1/feedback", json={
        "session_id": data["session_id"], "value": "up", "query": "支持7天无理由吗", "answer": "支持",
    })
    client.post("/api/v1/feedback", json={
        "session_id": data["session_id"], "value": "down", "query": "怎么查物流", "answer": "xx",
    })
    resp = client.get("/api/v1/ops/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["feedback_total"] >= 2
    # 口径：up_rate = up / (up + down)
    assert body["feedback_up"] + body["feedback_down"] == body["feedback_total"]
    assert body["up_rate"] == round(body["feedback_up"] / body["feedback_total"], 4)

    bc = client.get("/api/v1/ops/badcases?limit=5")
    assert bc.status_code == 200
    assert any(b["value"] == "down" for b in bc.json())


def test_answer_cache_hit_seconds():
    """V1.5 高频缓存：session B 首轮相同问题应命中 session A 写入的缓存并秒回。"""
    from app.storage.cache import answer_cache

    answer_cache.clear()

    def _full(text: str):
        evs = _parse_sse(text)
        return "".join(e[1].get("content", "") for e in evs if e[0] == "text"), evs

    a = _init_session()
    ra = client.post("/api/v1/chat/stream", json={
        "session_id": a["session_id"], "visitor_token": a["visitor_token"],
        "message": "拆了包装还能退吗",
    })
    assert ra.status_code == 200
    full_a, evs_a = _full(ra.text)
    done_a = next(e[1] for e in evs_a if e[0] == "done")
    assert done_a["handover"] is False
    assert full_a

    # 带标点变体：规范化后应命中同一缓存 key
    b = _init_session()
    rb = client.post("/api/v1/chat/stream", json={
        "session_id": b["session_id"], "visitor_token": b["visitor_token"],
        "message": "拆了包装还能退吗？",
    })
    assert rb.status_code == 200
    full_b, evs_b = _full(rb.text)
    done_b = next(e[1] for e in evs_b if e[0] == "done")
    assert done_b.get("cached") is True
    assert full_b == full_a

    # 统计：命中计数已累加
    stats = answer_cache.stats()
    assert stats["size"] >= 1
    assert stats["hits_total"] >= 1


def test_answer_cache_not_used_on_multi_turn():
    """V1.5 缓存只用于会话首轮：第二轮提问不命中缓存。"""
    from app.storage.cache import answer_cache

    answer_cache.clear()
    data = _init_session()
    token = data["visitor_token"]
    r1 = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": token, "message": "怎么查我的物流信息",
    })
    assert r1.status_code == 200
    r2 = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": token, "message": "怎么查我的物流信息",
    })
    evs2 = _parse_sse(r2.text)
    done2 = next(e[1] for e in evs2 if e[0] == "done")
    assert done2.get("cached") is not True
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


def test_layered_memory_l3_facts_written():
    """V1.5 分层记忆 L3：第 2 轮起 session.meta.facts 应被写入（首轮跳过）。"""
    from app.storage.db import db

    data = _init_session()
    token = data["visitor_token"]
    # 第 1 轮：无历史可提，facts 不写
    r1 = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": token, "message": "你好",
    })
    assert r1.status_code == 200
    meta1 = db.get_session(data["session_id"])["meta"]
    assert "facts" not in meta1
    # 第 2 轮（≥4 条消息）：提取 facts
    r2 = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": token,
        "message": "订单号 JD20261027 的退款到哪一步了",
    })
    assert r2.status_code == 200
    meta = db.get_session(data["session_id"])["meta"]
    assert "facts" in meta
    assert isinstance(meta["facts"], dict)
    assert meta["facts"].get("user_intent")


def test_layered_memory_l2_summary_after_long_convo():
    """V1.5 分层记忆 L2：超过滑动窗口（5 轮）的长对话应生成摘要。"""
    from app.storage.db import db

    data = _init_session()
    token = data["visitor_token"]
    turns = [
        "怎么查我的物流信息",
        "那快递到哪了",
        "能改收货地址吗",
        "怎么申请7天无理由退货",
        "退款多久能到账",
        "运费谁出",
        "那我再确认一下，质量问题运费也是你们出吗",
    ]
    for i, msg in enumerate(turns):
        resp = client.post("/api/v1/chat/stream", json={
            "session_id": data["session_id"], "visitor_token": token, "message": msg,
        })
        assert resp.status_code == 200
        # 前 5 轮：不要求摘要；第 6 轮（>5 轮窗口）后应出现 summary
        if i >= 5:
            meta = db.get_session(data["session_id"])["meta"]
            if meta.get("summary"):
                break
    else:
        # 兜底：最后一轮后必须已有摘要
        meta = db.get_session(data["session_id"])["meta"]
        assert meta.get("summary"), "超过窗口的长对话应生成 L2 摘要"

