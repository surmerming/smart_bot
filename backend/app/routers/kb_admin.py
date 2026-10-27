"""知识库后台（V2.0）：FAQ CRUD + 草稿审批流 + 版本历史 + 热更新。

审批流：draft(草稿) -> pending(待审) -> published(已生效) / rejected(已驳回)
生效即「原子写 faq.json → kb.load() 热重建索引（version+1 自动失效高频缓存）→ 记版本」。
faq.json 始终是知识库 Source of Truth，所有变更必须经审批流落盘，禁止绕过。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import (
    DraftReviewRequest,
    FAQCreateRequest,
    FAQPayload,
    FAQUpdateRequest,
)
from app.storage.db import db
from app.storage.kb import kb

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/kb", tags=["kb-admin"])

# 写 faq.json + 索引重建的串行化锁（防并发审批写竞态）
_apply_lock = asyncio.Lock()


# ---------- 文件读写（原子写） ----------
def _read_faq_file() -> dict:
    with open(settings.KB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_faq_file_atomic(data: dict) -> None:
    """原子写：临时文件 + os.replace，避免半写状态。"""
    path = settings.KB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".faq_", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------- 工具 ----------
def _next_faq_id() -> str:
    """生成新 FAQ id：现有最大号 +1（同时避开草稿中已占用的 id）。"""
    nums: list[int] = []
    for faq in kb.faqs:
        try:
            nums.append(int(faq.id.split("_")[1]))
        except (IndexError, ValueError):
            pass
    for draft in db.list_faq_drafts():
        fid = draft.get("faq_id") or ""
        try:
            nums.append(int(fid.split("_")[1]))
        except (IndexError, ValueError):
            pass
    return f"faq_{max(nums, default=0) + 1:03d}"


def _faq_dict(payload: FAQPayload, faq_id: str) -> dict:
    return {
        "id": faq_id,
        "category": payload.category,
        "standard_question": payload.standard_question,
        "variants": list(payload.variants),
        "answer": payload.answer,
        "risk_level": payload.risk_level,
        "follow_up": list(payload.follow_up),
    }


async def _apply_draft(draft: dict, operator: str) -> dict:
    """审批通过：把草稿应用到 faq.json 并热重建索引。调用方需持有 _apply_lock。"""
    action = draft["action"]
    payload = draft["payload"]
    faq_id = draft["faq_id"]

    data = _read_faq_file()
    faqs = data.get("faqs", [])
    index = {f["id"]: i for i, f in enumerate(faqs)}
    snapshot: dict | None = None

    if action == "create":
        if faq_id in index:
            raise HTTPException(status_code=409, detail=f"FAQ {faq_id} 已存在，无法重复新建")
        snapshot = dict(payload)
        faqs.append(snapshot)
    elif action == "update":
        if faq_id not in index:
            raise HTTPException(status_code=404, detail=f"FAQ {faq_id} 不存在，无法编辑")
        snapshot = dict(payload)
        snapshot["id"] = faq_id
        faqs[index[faq_id]] = snapshot
    elif action == "delete":
        if faq_id not in index:
            raise HTTPException(status_code=404, detail=f"FAQ {faq_id} 不存在，无法删除")
        snapshot = dict(faqs[index[faq_id]])  # 删除前快照，供版本历史留档
        faqs.pop(index[faq_id])
    else:
        raise HTTPException(status_code=400, detail=f"未知草稿动作: {action}")

    data["faqs"] = faqs
    _write_faq_file_atomic(data)
    # 热重建：kb.load 全量重建（40 条毫秒级）+ version+1 → 高频缓存自动失效
    kb.load(str(settings.KB_PATH))
    db.add_faq_version(faq_id, action, snapshot, operator)
    db.set_faq_draft_status(draft["id"], "published", operator)
    logger.info("知识库已热更新：%s %s（operator=%s）", action, faq_id, operator)
    return {"ok": True, "faq_id": faq_id, "action": action, "version": kb.version}


# ================= FAQ 查询 =================
@router.get("/faqs")
async def kb_faqs(category: str | None = None, q: str | None = None):
    """FAQ 列表（附带每条最新未生效草稿状态）；支持 category / q 过滤。"""
    faqs = [f.to_dict() for f in kb.faqs]
    if category:
        faqs = [f for f in faqs if f["category"] == category]
    if q:
        needle = q.strip().lower()
        faqs = [
            f for f in faqs
            if needle in f["standard_question"].lower()
            or any(needle in v.lower() for v in f["variants"])
            or needle in f["answer"].lower()
        ]
    # 附加草稿状态：faq_id -> 最新未生效草稿（list 已按 id DESC，先到先得保留最新）
    pending: dict[str, dict] = {}
    for d in db.list_faq_drafts():
        if d["status"] != "published" and d.get("faq_id") and d["faq_id"] not in pending:
            pending[d["faq_id"]] = {
                "draft_id": d["id"],
                "draft_status": d["status"],
                "draft_action": d["action"],
            }
    for f in faqs:
        f.update(pending.get(f["id"], {}))
    return {"total": len(faqs), "categories": kb.category_stats(), "faqs": faqs}


@router.get("/faqs/{faq_id}")
async def kb_faq_detail(faq_id: str):
    faq = kb.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail=f"FAQ {faq_id} 不存在")
    return faq.to_dict()


# ================= 新建 / 编辑 / 删除（进入草稿）=================
@router.post("/faqs", status_code=201)
async def kb_faq_create(req: FAQCreateRequest):
    faq_id = _next_faq_id()
    draft_id = db.create_faq_draft(faq_id, "create", _faq_dict(req.faq, faq_id), req.created_by)
    return {"draft_id": draft_id, "faq_id": faq_id, "status": "draft",
            "message": "草稿已创建，提交审核后生效"}


@router.put("/faqs/{faq_id}")
async def kb_faq_update(faq_id: str, req: FAQUpdateRequest):
    if not kb.get_faq(faq_id):
        raise HTTPException(status_code=404, detail=f"FAQ {faq_id} 不存在")
    draft_id = db.create_faq_draft(faq_id, "update", _faq_dict(req.faq, faq_id), req.created_by)
    return {"draft_id": draft_id, "faq_id": faq_id, "status": "draft",
            "message": "变更已存为草稿，提交审核后生效"}


@router.delete("/faqs/{faq_id}")
async def kb_faq_delete(faq_id: str, created_by: str = "ops"):
    if not kb.get_faq(faq_id):
        raise HTTPException(status_code=404, detail=f"FAQ {faq_id} 不存在")
    draft_id = db.create_faq_draft(faq_id, "delete", None, created_by)
    return {"draft_id": draft_id, "faq_id": faq_id, "status": "draft",
            "message": "删除已存为草稿，提交审核后生效"}


# ================= 草稿 / 审批 =================
@router.get("/drafts")
async def kb_drafts(status: str | None = None):
    return db.list_faq_drafts(status)


@router.get("/drafts/{draft_id}")
async def kb_draft_detail(draft_id: int):
    d = db.get_faq_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"草稿 {draft_id} 不存在")
    return d


@router.post("/drafts/{draft_id}/submit")
async def kb_draft_submit(draft_id: int):
    d = db.get_faq_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"草稿 {draft_id} 不存在")
    if not db.set_faq_draft_status(draft_id, "pending"):
        raise HTTPException(status_code=409, detail=f"草稿 {draft_id} 当前状态不允许提交（需为 draft 或 rejected）")
    return {"ok": True, "draft_id": draft_id, "status": "pending"}


@router.post("/drafts/{draft_id}/approve")
async def kb_draft_approve(draft_id: int, req: DraftReviewRequest):
    d = db.get_faq_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"草稿 {draft_id} 不存在")
    if d["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"草稿 {draft_id} 当前状态为 {d['status']}，仅待审可审批")
    async with _apply_lock:
        d = db.get_faq_draft(draft_id)  # 锁内重读，防并发重复审批
        if d["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"草稿 {draft_id} 已被其他操作处理")
        return await _apply_draft(d, req.reviewed_by)


@router.post("/drafts/{draft_id}/reject")
async def kb_draft_reject(draft_id: int, req: DraftReviewRequest):
    d = db.get_faq_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"草稿 {draft_id} 不存在")
    if d["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"草稿 {draft_id} 当前状态为 {d['status']}，仅待审可驳回")
    if not db.set_faq_draft_status(draft_id, "rejected", req.reviewed_by):
        raise HTTPException(status_code=409, detail=f"草稿 {draft_id} 驳回失败")
    return {"ok": True, "draft_id": draft_id, "status": "rejected", "reason": req.reason}


@router.delete("/drafts/{draft_id}")
async def kb_draft_delete(draft_id: int):
    if not db.delete_faq_draft(draft_id):
        raise HTTPException(status_code=409, detail="仅草稿/已驳回状态可撤销")
    return {"ok": True, "draft_id": draft_id}


# ================= 版本历史 / 手动热更新 =================
@router.get("/versions")
async def kb_versions(faq_id: str | None = None, limit: int = 50):
    return db.list_faq_versions(faq_id, limit)


@router.post("/rebuild")
async def kb_rebuild():
    """手动热更新：从当前 faq.json 重建索引（兜底；正常路径审批通过即自动热更新）。"""
    async with _apply_lock:
        kb.load(str(settings.KB_PATH))
    return {"ok": True, "faqs": len(kb.faqs), "version": kb.version}
