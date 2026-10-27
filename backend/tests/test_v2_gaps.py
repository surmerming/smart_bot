"""V2.0 生产版缺口补齐：防死循环、会话超时复位、确认超时取消、幽默分段接线、OTP 验证。"""
import json

from app.config import settings
from app.storage.db import db
from conftest import client


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


def _chat(session_id: str, visitor_token: str, message: str):
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": session_id, "visitor_token": visitor_token, "message": message,
    })
    assert resp.status_code == 200, resp.text
    return _parse_sse(resp.text)


# ================= 防死循环（plan 6.2-2） =================
def test_repeated_unresolved_auto_hard_handover():
    """连续 2 轮未解决（转人工）→ 第 3 轮直接硬转人工，话术为专属提示。"""
    data = _init_session("loop_test")
    sid, token = data["session_id"], data["visitor_token"]

    # 两轮知识库外问题（Mock can_answer=false → 软转人工，done.handover=True）
    for i, q in enumerate(["老板是谁", "今天天气怎么样"], start=1):
        evs = _chat(sid, token, q)
        done = next(e[1] for e in evs if e[0] == "done")
        assert done["handover"] is True, f"第 {i} 轮应转人工"
        s = db.get_session(sid)
        assert s["meta"].get("unresolved_streak") == i

    # 第三轮：入口防死循环 → repeated_unresolved 硬转
    evs = _chat(sid, token, "换了个问题还是不懂")
    meta = next(e[1] for e in evs if e[0] == "meta")
    done = next(e[1] for e in evs if e[0] == "done")
    assert meta["handover_reason"] == "repeated_unresolved"
    assert done["handover"] is True
    text = "".join(e[1].get("content", "") for e in evs if e[0] == "text")
    assert "连续几次都没能帮您解决" in text
    # 计数封顶，不无限累加
    assert db.get_session(sid)["meta"].get("unresolved_streak") <= settings.REPEAT_UNRESOLVED_LIMIT + 1


def test_normal_answer_resets_streak():
    """正常闭环回答后 unresolved_streak 归零。"""
    data = _init_session("streak_reset")
    sid, token = data["session_id"], data["visitor_token"]
    _chat(sid, token, "老板是谁")  # 未解决 → streak=1
    assert db.get_session(sid)["meta"].get("unresolved_streak") == 1
    _chat(sid, token, "支持7天无理由退换吗")  # 命中高置信 → 正常回答
    assert db.get_session(sid)["meta"].get("unresolved_streak") == 0


# ================= 会话超时复位（plan 3.1-4） =================
def test_session_timeout_resets_turn_count():
    """会话 30 分钟无操作：下次请求自动复位（轮次归零、meta 清空、状态回 AGENT_ACTIVE）。"""
    data = _init_session("timeout_test")
    sid, token = data["session_id"], data["visitor_token"]
    _chat(sid, token, "支持7天无理由退换吗")
    _chat(sid, token, "退款多久到账")
    s = db.get_session(sid)
    assert s["turn_count"] == 2
    db.update_session(sid, meta={"unresolved_streak": 1})

    # 把会话时间拨回 40 分钟前（updated_at 由 update_session 自动刷新，这里直写底层）
    old = "2020-01-01 00:00:00"
    with db._lock:
        conn = db._connect()
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (old, sid))
        conn.commit()
        conn.close()

    _chat(sid, token, "发货要等几天？")  # 独特问题命中知识库，避免命中高频缓存跳过 done 分支
    s2 = db.get_session(sid)
    assert s2["turn_count"] == 1, "超时复位后轮次从 1 重新计数"
    assert s2["status"] == "AGENT_ACTIVE"
    # meta 复位：防死循环计数不跨会话（done 写回 unresolved_streak=0，属复位后新计数）
    assert s2["meta"].get("unresolved_streak") == 0
    assert "pending_faq_id" not in s2["meta"]


def test_pending_confirm_timeout_cancels():
    """确认状态 30 秒无回复：请求时自动清除 pending，回到自由对话。"""
    data = _init_session("pending_timeout")
    sid, token = data["session_id"], data["visitor_token"]
    db.update_session(sid, meta={"pending_faq_id": "faq_001", "pending_at": "2020-01-01 00:00:00"})

    evs = _chat(sid, token, "支持7天无理由退换吗")  # 命中知识库 → 正常回答
    done = next(e[1] for e in evs if e[0] == "done")
    assert done["handover"] is False
    m = db.get_session(sid)["meta"]
    assert m.get("pending_faq_id") is None, "超时后 pending 应被清除"
    assert "pending_at" not in m


# ================= 幽默分段生成（plan 5.5） =================
def test_humor_two_stage_polish():
    """售前 + 情绪绿灯 → 两段式接线：humor 开关打开，输出为事实版（Mock 下 polish 校验
    因模板数字指纹冲突回退事实版——安全路径，符合 5.5「不一致回退」设计）。"""
    data = _init_session("humor_test")
    sid, token = data["session_id"], data["visitor_token"]
    evs = _chat(sid, token, "下单后多久发货？")  # presales 分类 + LEVEL_0
    meta = next(e[1] for e in evs if e[0] == "meta")
    done = next(e[1] for e in evs if e[0] == "done")
    assert meta["humor"] is True, "售前绿灯应开启幽默"
    assert done["handover"] is False
    text = "".join(e[1].get("content", "") for e in evs if e[0] == "text")
    assert "知识库检索结果" in text  # 事实版（回退保护生效）


def test_polish_answer_unit(monkeypatch):
    """polish_answer 单测：润色成功路径 + 关键数字不一致回退路径。"""
    import asyncio

    from app.agent.humor import polish_answer
    from app.agent.llm import llm

    async def fake_ok(messages, **kw):
        return "下单后24小时内发货哦，快得很～放心冲！"

    async def fake_bad(messages, **kw):
        return "明天发货哦，快得很～"  # 丢了关键数字 24

    monkeypatch.setattr(llm, "complete", fake_ok)
    out = asyncio.run(polish_answer("下单后24小时内发货。", "多久发货"))
    assert "放心冲" in out and "24" in out, "润色成功且关键数字保留"

    monkeypatch.setattr(llm, "complete", fake_bad)
    out2 = asyncio.run(polish_answer("下单后24小时内发货。", "多久发货"))
    assert "放心冲" not in out2 and "24" in out2, "数字不一致应回退事实版"


def test_humor_off_serious_scene():
    """售后场景（aftersales）即使绿灯也不开幽默，单段流式输出。"""
    data = _init_session("humor_off")
    sid, token = data["session_id"], data["visitor_token"]
    evs = _chat(sid, token, "怎么申请7天无理由退货")
    meta = next(e[1] for e in evs if e[0] == "meta")
    assert meta.get("humor") is False
    text = "".join(e[1].get("content", "") for e in evs if e[0] == "text")
    assert "放心冲" not in text


# ================= OTP 聊天内验证（plan 3.1-5②） =================
def test_otp_send_mock_returns_code():
    data = _init_session("otp_send")
    sid, token = data["session_id"], data["visitor_token"]
    r = client.post("/api/v1/otp/send", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["mock"] is True
    assert len(body["code"]) == 6
    pending = db.get_session(sid)["meta"]["otp_pending"]
    assert pending["phone"] == "13800138000" and pending["code"] == body["code"]
    assert pending["expires_at"] > "2020"


def test_otp_verify_success_marks_session():
    data = _init_session("otp_ok")
    sid, token = data["session_id"], data["visitor_token"]
    r = client.post("/api/v1/otp/send", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000",
    })
    code = r.json()["code"]
    r2 = client.post("/api/v1/otp/verify", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000", "code": code,
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["verified"] is True
    meta = db.get_session(sid)["meta"]
    assert meta.get("otp_verified", {}).get("phone") == "13800138000"
    assert "otp_pending" not in meta


def test_otp_verify_wrong_code_and_expired():
    data = _init_session("otp_bad")
    sid, token = data["session_id"], data["visitor_token"]
    client.post("/api/v1/otp/send", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000",
    })
    r = client.post("/api/v1/otp/verify", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000", "code": "000000",
    })
    assert r.status_code == 400
    # 过期：把 otp_pending 的 expires_at 拨到过去 → 410 且销毁
    s = db.get_session(sid)
    m = dict(s["meta"]); m["otp_pending"]["expires_at"] = "2020-01-01 00:00:00"
    db.update_session(sid, meta=m)
    r2 = client.post("/api/v1/otp/verify", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000", "code": "123456",
    })
    assert r2.status_code == 410
    assert "otp_pending" not in db.get_session(sid)["meta"]


def test_otp_verify_without_send_rejected():
    data = _init_session("otp_none")
    sid, token = data["session_id"], data["visitor_token"]
    r = client.post("/api/v1/otp/verify", json={
        "session_id": sid, "visitor_token": token, "phone": "13800138000", "code": "123456",
    })
    assert r.status_code == 400
