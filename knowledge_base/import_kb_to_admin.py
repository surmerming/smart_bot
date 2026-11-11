"""知识库后台初始化导入脚本：把 faq.json 现有 FAQ 补录为后台的正式记录。

背景：faq.json 是 Source of Truth，数据本身已生效（FAQ 列表可查），
但后台的「草稿审批流 / 版本历史」是空的（faq_drafts / faq_versions 为 0），
因为这些数据是直接写入 faq.json 的，没有经过后台审批流。

本脚本把这些 FAQ 登记为「初始新建（create）」记录：
- faq_drafts：每条一条 published 状态的 create 草稿（留档）
- faq_versions：每条一条 create 版本快照（支持回滚）
不修改 faq.json，不追加重复 FAQ，不改变现有生效数据。

用法：
    python knowledge_base/import_kb_to_admin.py
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# 允许直接运行：把 backend 加入 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.storage.db import db  # noqa: E402

KB_SOURCE = Path(__file__).resolve().parent / "faq.json"

# 与 kb_admin._faq_dict 保持一致的载荷格式（版本快照必须含 id，回滚依赖它）
_FIELDS = ["id", "category", "standard_question", "variants", "answer", "risk_level", "follow_up"]


def main() -> int:
    with open(KB_SOURCE, encoding="utf-8") as f:
        data = json.load(f)
    faqs = data["faqs"]

    # 已存在记录的 faq_id（幂等保护：重复运行不产生重复记录）
    existing = set()
    for d in db.list_faq_versions():
        fid = d.get("faq_id")
        if fid:
            existing.add(fid)
    skip = [faq["id"] for faq in faqs if faq["id"] in existing]
    todo = [faq for faq in faqs if faq["id"] not in existing]

    for faq in todo:
        payload = {k: faq[k] for k in _FIELDS}
        did = db.create_faq_draft(faq["id"], "create", payload, "ops")
        db.set_faq_draft_status(did, "pending", "ops")
        db.set_faq_draft_status(did, "published", "ops")
        db.add_faq_version(faq["id"], "create", payload, "ops")

    print(f"✅ 知识库后台导入完成")
    print(f"   本次导入：{len(todo)} 条（{KB_SOURCE} 共 {len(faqs)} 条）")
    if skip:
        print(f"   ⏭ 已存在跳过：{len(skip)} 条 {skip}")

    print(f"   草稿表 faq_drafts：{len(db.list_faq_drafts())} 条")
    print(f"   版本表 faq_versions：{len(db.list_faq_versions(limit=1000))} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
