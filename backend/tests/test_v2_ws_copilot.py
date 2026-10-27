"""V2.0 测试：WebSocket 实时排队通道 + 坐席 AI Copilot。

- /ws/agent 首帧待办快照 + 新转人工/完成事件实时广播
- /ws/user Token 鉴权拒绝 + 建连即推送排队进度
- Copilot：工单卡片 / 快捷回复模板 / 内部系统查询（Mock）
"""
import json

from starlette.websockets import WebSocketDisconnect

from conftest import client


def _init_session(session_id: str | None = None):
    resp = client.post("/api/v1/chat/init", json={"session_id": session_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trigger_handover() -> int:
    """真实触发一次转人工，返回 queue_id（红灯投诉，Mock 固定 LEVEL_3）。"""
    data = _init_session()
    resp = client.post("/api/v1/chat/stream", json={
        "session_id": data["session_id"],
        "visitor_token": data["visitor_token"],
        "message": "我要投诉！东西坏了你们管不管，我要打12315",
    })
    assert resp.status_code == 200, resp.text
    queue_id = None
    for block in resp.text.split("\n\n"):
        if block.startswith("event: summary"):
            for line in block.split("\n"):
                if line.startswith("data:"):
                    queue_id = json.loads(line[5:].strip()).get("queue_id")
    assert queue_id, "转人工未返回 queue_id"
    return data, queue_id


def test_ws_agent_snapshot_and_live_broadcast():
    """坐席 WS：首帧快照；新转人工 → handover_new；完成 → handover_done。"""
    with client.websocket_connect("/ws/agent") as ws_agent:
        first = ws_agent.receive_json()
        assert first["type"] == "handovers"
        assert isinstance(first["data"], list)

        data, queue_id = _trigger_handover()

        # 实时收到新待办广播
        got_new = False
        for _ in range(3):
            msg = ws_agent.receive_json()
            if msg.get("type") == "handover_new" and msg.get("queue_id") == queue_id:
                got_new = True
                break
        assert got_new, "坐席端未收到 handover_new 实时广播"

        # 标记完成 → handover_done 广播
        resp = client.post(f"/api/v1/ops/handovers/{queue_id}/complete")
        assert resp.status_code == 200, resp.text
        got_done = False
        for _ in range(3):
            msg = ws_agent.receive_json()
            if msg.get("type") == "handover_done" and msg.get("queue_id") == queue_id:
                got_done = True
                break
        assert got_done, "坐席端未收到 handover_done 实时广播"


def test_ws_user_auth_and_queue_push():
    """用户 WS：坏 Token 拒绝（4401）；有效 Token 建连即收到当前排队进度。"""
    # 未授权 → 拒绝（4401）
    rejected = False
    try:
        with client.websocket_connect(
            "/ws/user?session_id=sess_bad1234567&visitor_token=bad-token-value",
        ) as ws:
            ws.receive_json()
    except WebSocketDisconnect as exc:
        assert exc.code == 4401
        rejected = True
    assert rejected, "无效 Token 的 WS 连接应被拒绝"

    # 有效 Token：先转人工再建连，应立刻推送排队进度
    data, queue_id = _trigger_handover()
    qs = client.get(f"/api/v1/ops/queue/status?queue_id={queue_id}").json()
    assert qs["status"] == "waiting"

    with client.websocket_connect(
        f"/ws/user?session_id={data['session_id']}&visitor_token={data['visitor_token']}",
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "queue"
        assert msg["queue_id"] == queue_id
        assert msg["status"] == "waiting"
        assert msg["ahead"] >= 0


def test_copilot_ticket_templates_query():
    """Copilot：工单卡片字段 + 3 个回复模板 + 内部系统 Mock 查询。"""
    data, queue_id = _trigger_handover()

    # 1) 工单卡片
    resp = client.get(f"/api/v1/ops/copilot/{queue_id}")
    assert resp.status_code == 200, resp.text
    copilot = resp.json()["copilot"]
    ticket = copilot["ticket"]
    assert "user_intent" in ticket and "order_info" in ticket
    assert "bot_answered" in ticket and "issue" in ticket

    # 2) 回复模板
    resp = client.post(f"/api/v1/ops/copilot/templates?queue_id={queue_id}")
    assert resp.status_code == 200, resp.text
    templates = resp.json()["templates"]
    assert isinstance(templates, list) and len(templates) >= 1

    # 3) 内部系统查询（开发期 Mock）
    resp = client.post(f"/api/v1/ops/copilot/query?queue_id={queue_id}&action=logistics")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mock"] is True
    assert "订单" in body["result"] or "物流" in body["result"] or "开发期" in body["result"]


def test_copilot_404():
    resp = client.get("/api/v1/ops/copilot/999999")
    assert resp.status_code == 404
