"""知识库一键入库脚本：读取 faq.json → 构建 TF-IDF + BM25 索引 → 序列化保存。

用法（MVP 全量重建，秒级完成）：
    python knowledge_base/build_kb.py
"""
import json
import pickle
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# 允许直接运行：把 backend 加入 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.storage.kb import KnowledgeBase  # noqa: E402

KB_SOURCE = Path(__file__).resolve().parent / "faq.json"
INDEX_OUT = BACKEND_DIR / "data" / "kb_index.pkl"


def main() -> int:
    kb = KnowledgeBase()
    kb.load(str(KB_SOURCE))

    # 健康检查：重复率（相似度 > 0.95 视为重复，防止检索撞车）
    dupes = kb.find_duplicates(threshold=0.95)

    KB_SOURCE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_OUT, "wb") as f:
        pickle.dump(kb, f, protocol=4)

    print(f"✅ 知识库入库完成：{len(kb.faqs)} 条 FAQ")
    print(f"   索引保存至：{INDEX_OUT}")
    print(f"   分类分布：{kb.category_stats()}")
    if dupes:
        print(f"   ⚠️ 疑似重复 FAQ：{dupes}")
    else:
        print("   ✅ 未发现相似度 > 0.95 的重复 FAQ")

    # 抽样自检：设计稿示例问法
    samples = ["拆了包装还能退吗", "你们这破衣服能退不", "发货要几天", "退款多久能到账", "我忘记密码了"]
    for q in samples:
        hits = kb.search(q, top_k=1)
        if hits:
            top = hits[0]
            print(f"   · 「{q}」→ {top['faq'].id} {top['faq'].standard_question} (dense={top['dense_score']:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
