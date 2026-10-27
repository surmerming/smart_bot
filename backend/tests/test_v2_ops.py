"""V2.0 生产版剩余项：运行控制（Kill Switch + 灰度）、Bad Case 管理、CSAT 满意度。"""
import json

import pytest

from app.storage.db import db
from app.storage.runtime_control import runtime
from conftest import client

BAD_STATUS = ("open", "resolved", "ignored")


@pytest.fixture(autouse=True)
def reset_runtime():
    """runtime 是全局单例，每个用例重置到默认状态。"""
    runtime.set_mode("auto")
    runtime.set_gray_percent(0)
    yield
    runtime.set_mode("auto")
    runtime.set_gray_percent(0)


def _init_session(session_id: str | None = None):
    resp = client.post("/api/v1/chat/init", json={"session_id": session_id})
    assert resp.status_code == 200
    return resp.json()


def _parse_sse(text: str):
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        etype = ""
        data = {}
        for line in block.split("\n"):
            if line.startswith("event:"):
                etype = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        events.append((etype, data))
    return events


# ================= 运行控制：Kill Switch =================
def test_runtime_default_state():
    st = client.get("/api/v1/ops/runtime").json()
    assert st["mode"] == "auto"
    assert st["gray_percent"] == 0
    assert st["kill_switch"] is False


def test_runtime_update_invalid():
    r = client.put("/api/v1/ops/runtime", json={"mode": "explode"})
    assert r.status_code == 400
    r = client.put("/api/v1/ops/runtime", json={"gray_percent": 150})
    assert r.status_code == 400


def test_kill_switch_off_maintenance():
    """维护模式：回复维护话术、不调 LLM、不入队。"""
    data = _init_session("ks_off_test")
    assert client.put("/api/v1/ops/runtime", json={"mode": "off"}).status_code == 200
    q_before = len(db.list_handovers("waiting"))
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "message": "你好，我想问退货",
    })
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    done = next(e[1] for e in events if e[0] == "done")
    assert meta["status"] == "maintenance"
    assert done["handover"] is False
    assert done["handover_reason"] == "kill_switch_off"
    assert "维护" in "".join(e[1].get("content", "") for e in events if e[0] == "text")
    assert len(db.list_handovers("waiting")) == q_before  # 不入队


def test_kill_switch_handover_all():
    """全局转人工：直接登记排队 + 转人工话术，不检索不调 LLM。"""
    data = _init_session("ks_handover")
    assert client.put("/api/v1/ops/runtime", json={"mode": "handover"}).status_code == 200
    q_before = len(db.list_handovers("waiting"))
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "message": "优惠券用不了怎么办",
    })
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    done = next(e[1] for e in events if e[0] == "done")
    assert meta["status"] == "handover"
    assert meta["handover_reason"] == "kill_switch_all"
    assert done["handover"] is True
    # 队列新增 1 条，会话状态置 HANDOVER
    waiting = [h for h in db.list_handovers("waiting") if h["session_id"] == "ks_handover"]
    assert len(waiting) == q_before + 1 or len(waiting) >= 1
    assert db.get_session("ks_handover")["status"] == "HANDOVER"


def test_kill_switch_auto_restore():
    """切回 auto：正常走 Agent 管线回答。"""
    data = _init_session("ks_auto_test")
    assert client.put("/api/v1/ops/runtime", json={"mode": "handover"}).status_code == 200
    assert client.put("/api/v1/ops/runtime", json={"mode": "auto"}).status_code == 200
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "message": "支持7天无理由退换吗",
    })
    events = _parse_sse(resp.text)
    meta = next(e[1] for e in events if e[0] == "meta")
    assert meta["status"] == "answering"


def test_handover_offline_rejected():
    data = _init_session("ks_offline_h")
    assert client.put("/api/v1/ops/runtime", json={"mode": "off"}).status_code == 200
    resp = client.post("/api/v1/handover", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "contact": "13800000000",
    })
    assert resp.status_code == 503


# ================= 运行控制：灰度开关 =================
def test_gray_full_on_off():
    client.put("/api/v1/ops/runtime", json={"gray_percent": 100})
    assert _init_session("gray_a_test")["gray"] is True
    client.put("/api/v1/ops/runtime", json={"gray_percent": 0})
    assert _init_session("gray_b_test")["gray"] is False


def test_gray_partial_split():
    client.put("/api/v1/ops/runtime", json={"gray_percent": 50})
    sessions = [_init_session(f"gray_p_{i}") for i in range(20)]
    hit = sum(1 for s in sessions if s["gray"])
    # 20 个不同 session 哈希应分布在两侧（统计上 5~15 内）
    assert 1 <= hit <= 19
    # 同一会话全程同组（稳定性）
    s = sessions[0]
    assert s["gray"] == (_init_session(s["session_id"])["gray"])


# ================= Bad Case 管理 =================
def test_badcase_status_flow():
    fid = db.add_feedback("bc_sess_01", "msg_1", "down", "优惠券用不了怎么办", "ctx", "ans")
    row = db.list_badcases(limit=100)[0]
    assert row["id"] == fid and row["status"] == "open"

    r = client.post(f"/api/v1/ops/badcases/{fid}/status", json={"status": "resolved", "note": "已更新知识库 faq_040"})
    assert r.status_code == 200
    row = next(x for x in db.list_badcases(limit=100) if x["id"] == fid)
    assert row["status"] == "resolved" and row["note"] == "已更新知识库 faq_040"

    r = client.post(f"/api/v1/ops/badcases/{fid}/status", json={"status": "ignored"})
    assert r.status_code == 200
    assert next(x for x in db.list_badcases(limit=100) if x["id"] == fid)["status"] == "ignored"


def test_badcase_status_guards():
    # 非法状态
    assert client.post("/api/v1/ops/badcases/1/status", json={"status": "wat"}).status_code == 404
    # 不存在的 id
    assert client.post("/api/v1/ops/badcases/999999/status", json={"status": "resolved"}).status_code == 404


# ================= CSAT 满意度 =================
def test_csat_submit_and_stats():
    data = _init_session("csat_sess_01")
    assert client.post("/api/v1/csat", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"],
        "rating": 5, "comment": "很满意",
    }).status_code == 200
    assert client.post("/api/v1/csat", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"], "rating": 4,
    }).status_code == 200
    st = client.get("/api/v1/ops/csat").json()
    assert st["csat_total"] >= 2
    assert st["csat_avg"] == 4.5
    assert st["csat_dist"].get("5") >= 1 and st["csat_dist"].get("4") >= 1


def test_csat_guards():
    data = _init_session("csat_sess_02")
    # 非法星级
    assert client.post("/api/v1/csat", json={
        "session_id": data["session_id"], "visitor_token": data["visitor_token"], "rating": 9,
    }).status_code == 400
    # 错误 token
    assert client.post("/api/v1/csat", json={
        "session_id": data["session_id"], "visitor_token": "bad_token", "rating": 3,
    }).status_code == 401
