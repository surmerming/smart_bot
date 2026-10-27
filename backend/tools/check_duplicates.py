"""知识库健康体检：重复 FAQ 检测（plan 1.4-4 防腐烂）。

对每条 FAQ 的标准问法做混合检索，若 Top 候选是另一条 FAQ 且相似度 ≥ 阈值，
提示两条 FAQ 语义撞车（检索时互相干扰）。

用法：
    python backend/tools/check_duplicates.py [--threshold 0.95]
退出码：0 = 无重复；1 = 发现重复对。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.storage.kb import KnowledgeBase  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库重复 FAQ 检测")
    ap.add_argument("--threshold", type=float, default=0.95, help="相似度阈值（默认 0.95）")
    args = ap.parse_args()

    kb = KnowledgeBase()
    kb.load(str(settings.KB_PATH))
    pairs = kb.find_duplicates(args.threshold)
    print("=" * 56)
    print(f"知识库重复率检查（faq.json，{len(kb.faqs)} 条，阈值 {args.threshold}）")
    print("=" * 56)
    if not pairs:
        print("✅ 无重复 FAQ，检索撞车风险低")
        return 0
    seen = set()
    for a, b, score in pairs:
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        print(f"⚠️  {a} ↔ {b}  相似度 {score}")
    print(f"\n共 {len(seen)} 对疑似重复，建议保留语义更标准的一条，另一条改问法/合并。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
