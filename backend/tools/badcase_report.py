"""Bad Case 归因工具（plan V1.5 知识库维护：Bad Case 自动转化为新 FAQ）。

对点踩记录逐条重新检索，归因三类：
- missing 知识库缺失型：检索无候选 / 最高分 < LOW（压根没这条 FAQ）
- weak    检索失效型：有相关但相似度仅 LOW~HIGH（有 FAQ 但召回弱，建议补变体问法）
- quality 生成质量型：已命中（≥ HIGH）但用户仍点踩（答案或话术需优化）

自动为「缺失型」去重后生成 FAQ 草案，写入 knowledge_base/suggestions/YYYY-MM-DD.json，
运营确认后补充进 faq.json 即可（Source of Truth 不变）。

用法：
    python backend/tools/badcase_report.py                # 全量归因 + 输出报告
    python backend/tools/badcase_report.py --limit 50     # 只看最近 50 条
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.storage.db import db  # noqa: E402
from app.storage.kb import kb  # noqa: E402

KIND_ZH = {"missing": "知识库缺失型", "weak": "检索失效型", "quality": "生成质量型"}


def classify(query: str, results: list[dict]) -> tuple[str, dict | None]:
    if not results:
        return "missing", None
    top = results[0]
    score = top["dense_score"]
    if score < settings.SIM_THRESHOLD_LOW:
        return "missing", top
    if score <= settings.SIM_THRESHOLD_HIGH:
        return "weak", top
    return "quality", top


def analyze(cases: list[dict]) -> tuple[Counter, list[dict], list[dict]]:
    """归因核心逻辑（纯函数，便于测试）：返回 (统计, 明细行, FAQ 草案)。"""
    stats: Counter = Counter()
    rows: list[dict] = []
    seen: set[str] = set()
    suggestions: list[dict] = []

    for c in cases:
        query = (c.get("query") or "").strip()
        if not query:
            continue
        results = kb.search(query, top_k=3)
        kind, top = classify(query, results)
        stats[kind] += 1
        rows.append({
            "id": c["id"],
            "kind": kind,
            "query": query,
            "top1_faq": top["faq"].id if top else None,
            "top1_score": round(top["dense_score"], 3) if top else None,
            "answer": (c.get("answer") or "")[:80],
            "created_at": c.get("created_at"),
        })
        # 缺失型 → FAQ 草案（去重）
        if kind == "missing" and query not in seen:
            seen.add(query)
            suggestions.append({
                "standard_question": query,
                "variants": [],
                "answer": "【待运营补充标准答案】",
                "category": "presales",
                "risk_level": "low",
                "source": "badcase_auto_suggest",
                "source_id": c["id"],
            })
    return stats, rows, suggestions


def main() -> int:
    parser = argparse.ArgumentParser(description="Bad Case 归因报告")
    parser.add_argument("--limit", type=int, default=0, help="只看最近 N 条点踩（0=全部）")
    args = parser.parse_args()

    kb.load(str(settings.KB_PATH))
    cases = db.list_badcases(args.limit) if args.limit else db.list_badcases(10**9)
    if not cases:
        print("暂无点踩记录，说明回答质量不错 🎉")
        return 0

    stats, rows, suggestions = analyze(cases)

    print("=" * 64)
    print(f"小答 Bad Case 归因报告（共 {len(rows)} 条点踩）")
    print("=" * 64)
    for kind in ("missing", "weak", "quality"):
        n = stats.get(kind, 0)
        print(f"  {KIND_ZH[kind]}: {n} 条（{n / len(rows):.1%}）")
    print("-" * 64)
    print("明细（前 15 条）：")
    for r in rows[:15]:
        print(f"  [{KIND_ZH[r['kind']]}]「{r['query'][:32]}」→ {r['top1_faq'] or '无候选'} ({r['top1_score']})")

    if suggestions:
        out_dir = Path(__file__).resolve().parent.parent.parent / "knowledge_base" / "suggestions"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"{date.today().isoformat()}.json"
        path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
        print("-" * 64)
        print(f"已为缺失型生成 {len(suggestions)} 条 FAQ 草案 → {path}")
        print("运营确认补充标准答案后，并入 knowledge_base/faq.json 即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
