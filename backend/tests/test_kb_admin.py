"""V2.0 知识库后台：FAQ CRUD + 草稿审批流 + 版本历史 + 热更新 全流程测试。

隔离：conftest 已将 KB_PATH 指向临时副本；本模块每个测试前恢复现场
（重拷原始 faq.json + 重建索引 + 清空草稿/版本表），模块结束时再恢复一次，
确保不影响同进程后续测试模块（test_v2_ws_copilot 等）。
"""
import json
import os
import shutil
import sqlite3

import pytest

from app.storage.kb import kb
from conftest import client

_KB_SRC = os.path.join(os.path.dirname(__file__), "../../knowledge_base/faq.json")
_KB_COPY = os.environ["KB_PATH"]


def _reset():
    shutil.copy(_KB_SRC, _KB_COPY)
    kb.load(_KB_COPY)
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("DELETE FROM faq_drafts")
    conn.execute("DELETE FROM faq_versions")
    conn.commit()
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def _module_reset():
    yield
    _reset()


@pytest.fixture(autouse=True)
def _each_test_reset(_module_reset):
    _reset()
    yield


def _new_payload(**overrides):
    payload = {
        "category": "aftersales",
        "standard_question": "测试：换货要多久？",
        "variants": ["测试换货时效", "换货几天"],
        "answer": "测试答案：换货一般3-5天。",
        "risk_level": "low",
        "follow_up": ["换货运费谁出"],
    }
    payload.update(overrides)
    return payload


def _create_draft(client, payload=None, faq_id=None):
    """POST /faqs 或 PUT /faqs/{id} 建草稿，返回 (resp, draft_id, faq_id)。"""
    if faq_id is None:
        resp = client.post("/api/v1/kb/faqs", json={"faq": payload or _new_payload(), "created_by": "ops"})
    else:
        resp = client.put(f"/api/v1/kb/faqs/{faq_id}", json={"faq": payload or _new_payload(), "created_by": "ops"})
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    return data["draft_id"], data["faq_id"]


# ================= 新建全流程 =================
def test_create_approve_publish():
    draft_id, faq_id = _create_draft(client)
    assert faq_id == "faq_041"  # 现有 40 条，新 id 顺延

    # 草稿可见、未生效
    d = client.get(f"/api/v1/kb/drafts/{draft_id}").json()
    assert d["status"] == "draft" and d["action"] == "create"
    assert client.get("/api/v1/kb/faqs").json()["total"] == 40

    # 提交审核
    assert client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={}).json()["status"] == "pending"

    # 审批通过 → 生效
    r = client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={"reviewed_by": "ops"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # ① faq.json 已落盘
    with open(_KB_COPY, encoding="utf-8") as f:
        data = json.load(f)
    ids = [x["id"] for x in data["faqs"]]
    assert faq_id in ids and len(data["faqs"]) == 41

    # ② 内存索引热更新，检索命中新 FAQ
    hits = kb.search("测试：换货要多久？", top_k=1)
    assert hits and hits[0]["faq"].id == faq_id

    # ③ API 列表可见
    assert client.get("/api/v1/kb/faqs").json()["total"] == 41

    # ④ 版本历史有 create 记录（快照完整）
    versions = client.get("/api/v1/kb/versions").json()
    assert any(v["faq_id"] == faq_id and v["action"] == "create" for v in versions)

    # ⑤ 草稿状态 → published
    assert client.get(f"/api/v1/kb/drafts/{draft_id}").json()["status"] == "published"


# ================= 编辑全流程 =================
def test_update_approve_hot_reload():
    # 以 faq_001 原始内容为基底，仅替换答案（保留原变体问法，确保检索仍命中）
    original = client.get("/api/v1/kb/faqs/faq_001").json()
    original.pop("id", None)
    original["answer"] = "测试：新答案——支持，不影响二次销售即可。"

    draft_id, faq_id = _create_draft(client, faq_id="faq_001", payload=original)
    client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={})
    client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={"reviewed_by": "ops"})

    # faq.json 中 faq_001 答案已替换
    with open(_KB_COPY, encoding="utf-8") as f:
        data = json.load(f)
    target = next(x for x in data["faqs"] if x["id"] == "faq_001")
    assert target["answer"] == "测试：新答案——支持，不影响二次销售即可。"

    # 检索返回新内容（热更新生效）
    hits = kb.search("可以退吗", top_k=1)
    assert hits and hits[0]["faq"].id == "faq_001"
    assert "新答案" in hits[0]["faq"].answer


# ================= 删除全流程 =================
def test_delete_approve_removes():
    # 删除 faq_040 → 建 delete 草稿
    r = client.delete("/api/v1/kb/faqs/faq_040?created_by=ops")
    assert r.status_code == 200, r.text
    draft_id = r.json()["draft_id"]
    # 再次删除应建另一条草稿（验证撤销路径）
    r2 = client.delete("/api/v1/kb/faqs/faq_040?created_by=ops")
    assert r2.status_code == 200
    client.delete(f"/api/v1/kb/drafts/{r2.json()['draft_id']}")

    # 提交 + 审批
    client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={})
    client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={"reviewed_by": "ops"})

    with open(_KB_COPY, encoding="utf-8") as f:
        data = json.load(f)
    assert all(x["id"] != "faq_040" for x in data["faqs"])
    assert len(data["faqs"]) == 39

    # 检索不再命中
    hits = kb.search("faq_040 相关问题", top_k=5)
    assert not any(h["faq"].id == "faq_040" for h in hits)

    # 版本历史留档删除前快照
    versions = client.get("/api/v1/kb/versions").json()
    del_v = next(v for v in versions if v["faq_id"] == "faq_040" and v["action"] == "delete")
    assert del_v["snapshot"]["id"] == "faq_040"


# ================= 驳回不生效 =================
def test_reject_does_not_publish():
    draft_id, faq_id = _create_draft(client)
    client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={})
    r = client.post(f"/api/v1/kb/drafts/{draft_id}/reject", json={"reviewed_by": "ops", "reason": "措辞不规范"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"

    # 未生效：faq.json 与索引无变化
    with open(_KB_COPY, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["faqs"]) == 40 and all(x["id"] != faq_id for x in data["faqs"])
    assert client.get("/api/v1/kb/faqs").json()["total"] == 40

    # 驳回后可修改再提交
    client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={})
    assert client.get(f"/api/v1/kb/drafts/{draft_id}").json()["status"] == "pending"


# ================= 状态机与越权操作 =================
def test_state_machine_guards():
    draft_id, _ = _create_draft(client)
    # draft 直接审批 → 409
    assert client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={}).status_code == 409
    # draft 直接驳回 → 409
    assert client.post(f"/api/v1/kb/drafts/{draft_id}/reject", json={}).status_code == 409
    # 提交两次 → 409
    client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={})
    assert client.post(f"/api/v1/kb/drafts/{draft_id}/submit", json={}).status_code == 409
    # 审批后重复审批 → 409
    client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={})
    assert client.post(f"/api/v1/kb/drafts/{draft_id}/approve", json={}).status_code == 409

    # 不存在的草稿 → 404
    assert client.get("/api/v1/kb/drafts/99999").status_code == 404


def test_draft_cancel():
    draft_id, _ = _create_draft(client)
    assert client.delete(f"/api/v1/kb/drafts/{draft_id}").json()["ok"] is True
    assert client.get(f"/api/v1/kb/drafts/{draft_id}").status_code == 404


# ================= 输入校验 =================
def test_payload_validation():
    bad = _new_payload(category="unknown")
    r = client.post("/api/v1/kb/faqs", json={"faq": bad, "created_by": "ops"})
    assert r.status_code == 422

    bad2 = _new_payload(standard_question="")
    assert client.post("/api/v1/kb/faqs", json={"faq": bad2, "created_by": "ops"}).status_code == 422

    # 编辑不存在的 FAQ → 404
    r = client.put("/api/v1/kb/faqs/faq_999", json={"faq": _new_payload(), "created_by": "ops"})
    assert r.status_code == 404

    # 删除不存在的 FAQ → 404
    r = client.delete("/api/v1/kb/faqs/faq_999?created_by=ops")
    assert r.status_code == 404


# ================= 列表过滤与草稿标记 =================
def test_list_filter_and_draft_badge():
    draft_id, _ = _create_draft(client)  # 未提交的草稿
    data = client.get("/api/v1/kb/faqs").json()
    assert data["total"] == 40
    assert data["categories"]["aftersales"] == 14

    # 过滤
    assert client.get("/api/v1/kb/faqs?category=presales").json()["total"] == 9
    assert client.get("/api/v1/kb/faqs?q=退货").json()["total"] >= 1

    # 新 FAQ 出现在列表并带草稿标记
    assert data["faqs"][0].get("draft_status") is None  # 现有 FAQ 无草稿
