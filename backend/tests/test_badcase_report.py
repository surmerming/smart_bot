"""Bad Case 归因工具测试：缺失型/生成质量型归类 + FAQ 草案生成（Mock 离线）。"""
import sys
from pathlib import Path

from conftest import client  # noqa: F401  确保环境变量（Mock + 临时库）先设置

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))


def test_badcase_analyze_suggests_missing_faq():
    from app.config import settings
    from app.storage.db import db
    from app.storage.kb import kb
    import badcase_report as br

    # 一条知识库缺失（0 相似度）、一条高置信命中（知识库内）
    db.add_feedback("sess_bc1", None, "down", "今天天气怎么样", None, "（Mock）")
    db.add_feedback("sess_bc1", None, "down", "怎么申请7天无理由退货", None, "支持7天无理由退换")

    kb.load(str(settings.KB_PATH))
    cases = db.list_badcases(10**9)
    stats, rows, suggestions = br.analyze(cases)

    # 缺失型被识别并生成 FAQ 草案
    assert stats.get("missing", 0) >= 1
    assert any(s["standard_question"] == "今天天气怎么样" for s in suggestions)
    # 知识库内问题：当前 TF-IDF 量纲下归为 weak（有候选但分不高）或 quality，绝不误判为缺失
    assert stats.get("missing", 0) + stats.get("weak", 0) + stats.get("quality", 0) == sum(stats.values())
    assert stats.get("weak", 0) + stats.get("quality", 0) >= 1
    # 草案去重
    assert len(suggestions) == len({s["standard_question"] for s in suggestions})
    # 每行明细都带归因
    assert all("kind" in r for r in rows)
