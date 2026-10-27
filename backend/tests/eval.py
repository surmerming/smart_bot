"""自动评测脚本：黄金测试集（200+ 问法）→ 检索命中率 / MRR / 决策准确率。

用法：
    python backend/tests/eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)  # 管道输出不丢行

from app.config import settings  # noqa: E402
from app.storage.kb import KnowledgeBase  # noqa: E402


def main() -> int:
    kb = KnowledgeBase()
    kb.load(str(settings.KB_PATH))

    with open(Path(__file__).resolve().parent / "golden_dataset.json", encoding="utf-8") as f:
        cases = json.load(f)

    hit3 = 0
    mrr = 0.0
    kb_cases = 0
    negation_cases = 0
    negation_ok = 0
    handover_cases = 0
    handover_ok = 0
    risk_cases = 0
    risk_ok = 0

    for c in cases:
        exp = c["expected"]
        top = kb.search(c["query"], top_k=3)

        if exp == "kb_hit":
            kb_cases += 1
            target = c["faq_id"]
            ids = [r["faq"].id for r in top]
            if target in ids:
                hit3 += 1
                mrr += 1.0 / (ids.index(target) + 1)
        elif exp == "negation":
            # 否定句：要求 Top1 相似度不虚高，且系统走 NLI 校验路径
            negation_cases += 1
            top1 = top[0] if top else None
            if top1 and top1["dense_score"] < 0.95:
                negation_ok += 1
        elif exp == "high_risk":
            risk_cases += 1
            ids = [r["faq"].id for r in top]
            # 高风险问题：低置信转人工 或 命中高风险 FAQ（强制转人工）都算正确路径
            if not top or top[0]["dense_score"] < settings.SIM_THRESHOLD_HIGH or any(
                kb.get_faq(i).risk_level == "high" for i in ids if kb.get_faq(i)
            ):
                risk_ok += 1
        elif exp in ("handover", "handover_request"):
            handover_cases += 1
            top1 = top[0] if top else None
            # 未命中：分数低于 HIGH 都走人工路径（<LOW 直接转；LOW~HIGH 经 LLM 判断转人工）
            if not top1 or top1["dense_score"] < settings.SIM_THRESHOLD_HIGH:
                handover_ok += 1

    hit_rate = hit3 / kb_cases if kb_cases else 0
    mrr_score = mrr / kb_cases if kb_cases else 0
    print("=" * 60)
    print("小答 RAG 检索评估（golden_dataset.json）")
    print("=" * 60)
    print(f"  知识库命中类：{hit3}/{kb_cases}  Hit@3 = {hit_rate:.1%}  MRR = {mrr_score:.3f}")
    print(f"  否定句场景：{negation_ok}/{negation_cases} 通过阈值检查")
    print(f"  高风险场景：{risk_ok}/{risk_cases} 命中红线策略")
    print(f"  转人工场景：{handover_ok}/{handover_cases} 低置信判定")
    print(f"  达标线：Hit@3 ≥ 85%")

    # 汇总检索失败案例（便于补充变体问法）
    print("-" * 60)
    print("Top 检索失败案例（建议补变体问法）：")
    shown = 0
    for c in cases:
        if c["expected"] != "kb_hit":
            continue
        top = kb.search(c["query"], top_k=3)
        ids = [r["faq"].id for r in top]
        if c["faq_id"] not in ids and shown < 10:
            print(f"  「{c['query']}」→ 期望 {c['faq_id']}，实际 {ids or '无'}（Top1 sim={top[0]['dense_score']:.2f}）" if top else f"  「{c['query']}」→ 期望 {c['faq_id']}，实际 无")
            shown += 1
    if shown == 0:
        print("  全部命中，无失败案例 🎉")
    return 0 if hit_rate >= 0.85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
