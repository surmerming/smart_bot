#!/usr/bin/env python3
"""小答自动化巡检（V2.0 质量保障）：每天定时跑，检测服务健康 + 核心指标 + 检索质量。

检查项：
  1. 服务存活      GET /health                  （后端可访问 + 知识库已加载）
  2. 核心指标      GET /ops/stats                （自动化率、CSAT、反馈）
  3. 检索质量      跑 backend/tests/eval.py      （黄金集 Hit@3 ≥ 阈值）
  4. 待办积压      GET /ops/handovers?status=waiting （转人工待办数）
  5. Bad Case     GET /ops/badcases             （待处理点踩数）

告警：
  - 任一检查失败 → 退出码 1，打印告警
  - 配置 WECHAT_WEBHOOK 或 DINGTALK_WEBHOOK 环境变量后自动推送群机器人

用法：
    python scripts/healthcheck.py                 # 一次性巡检
    python scripts/healthcheck.py --cron          # cron 模式（同上 + 只输出摘要）
    报告落盘 backend/logs/healthcheck-YYYY-MM-DD.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
LOG_DIR = BACKEND / "logs"
BASE_URL = os.environ.get("XD_BASE_URL", "http://127.0.0.1:8000")

# 阈值（可用环境变量覆盖，便于运维调整）
MIN_AUTO_RATE = float(os.environ.get("XD_MIN_AUTO_RATE", "0.5"))
MAX_PENDING_HANDOVERS = int(os.environ.get("XD_MAX_PENDING_HANDOVERS", "20"))
MAX_OPEN_BADCASES = int(os.environ.get("XD_MAX_OPEN_BADCASES", "20"))
HIT3_THRESHOLD = float(os.environ.get("XD_HIT3_THRESHOLD", "0.85"))

WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK", "")
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")


def fetch_json(path: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def check_health() -> dict:
    try:
        h = fetch_json("/health")
        ok = h.get("status") == "ok" and int(h.get("faqs", 0)) >= 1
        return {"name": "服务存活", "ok": ok, "detail": f"status={h.get('status')}, faqs={h.get('faqs')}"}
    except Exception as exc:
        return {"name": "服务存活", "ok": False, "detail": f"无法访问 {BASE_URL}: {exc}"}


def check_stats() -> dict:
    try:
        s = fetch_json("/api/v1/ops/stats")
        auto_rate = float(s.get("auto_rate", 0))
        issues = []
        if auto_rate < MIN_AUTO_RATE:
            issues.append(f"自动化率 {auto_rate:.1%} < {MIN_AUTO_RATE:.0%}")
        csat = s.get("csat_avg")
        if csat is not None and float(csat) < 3.0:
            issues.append(f"CSAT 平均分 {csat} < 3.0")
        ok = not issues
        detail = f"自动率={auto_rate:.1%}, 总咨询={s.get('total_sessions')}, 转人工={s.get('handover')}"
        if csat is not None:
            detail += f", CSAT={csat}({s.get('csat_total')}人)"
        if issues:
            detail += "；" + "；".join(issues)
        return {"name": "核心指标", "ok": ok, "detail": detail}
    except Exception as exc:
        return {"name": "核心指标", "ok": False, "detail": f"获取失败: {exc}"}


def check_eval() -> dict:
    try:
        res = subprocess.run(
            [sys.executable, "tests/eval.py"],
            cwd=str(BACKEND),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = res.stdout + res.stderr
        hit_rate = None
        m = re.search(r"Hit@3 = ([\d.]+)%", out)
        if m:
            hit_rate = float(m.group(1)) / 100
        ok = hit_rate is not None and hit_rate >= HIT3_THRESHOLD
        summary = next((l.strip() for l in out.splitlines() if "Hit@3" in l), out[-300:] if res.returncode else "")
        return {"name": "检索质量", "ok": ok, "detail": f"Hit@3={hit_rate:.1%}（阈值 {HIT3_THRESHOLD:.0%}）" if hit_rate else summary}
    except Exception as exc:
        return {"name": "检索质量", "ok": False, "detail": f"评估执行失败: {exc}"}


def check_pending_handovers() -> dict:
    try:
        items = fetch_json("/api/v1/ops/handovers?status=waiting")
        n = len(items)
        return {"name": "待办积压", "ok": n <= MAX_PENDING_HANDOVERS,
                "detail": f"转人工待办 {n} 条（阈值 {MAX_PENDING_HANDOVERS}）"}
    except Exception as exc:
        return {"name": "待办积压", "ok": False, "detail": f"获取失败: {exc}"}


def check_badcases() -> dict:
    try:
        items = fetch_json("/api/v1/ops/badcases?limit=100")
        open_n = sum(1 for c in items if c.get("status", "open") == "open")
        return {"name": "Bad Case 积压", "ok": open_n <= MAX_OPEN_BADCASES,
                "detail": f"待处理点踩 {open_n} 条（阈值 {MAX_OPEN_BADCASES}）"}
    except Exception as exc:
        return {"name": "Bad Case 积压", "ok": False, "detail": f"获取失败: {exc}"}


def push_alert(text: str) -> None:
    for name, url in (("企微", WECHAT_WEBHOOK), ("钉钉", DINGTALK_WEBHOOK)):
        if not url:
            continue
        try:
            payload = json.dumps({"msgtype": "text", "text": {"content": text}}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            print(f"  [已推送 {name} 机器人告警]")
        except Exception as exc:
            print(f"  [推送 {name} 失败: {exc}]")


def main() -> int:
    ap = argparse.ArgumentParser(description="小答自动化巡检")
    ap.add_argument("--cron", action="store_true", help="cron 模式：简洁输出（供 crontab 使用）")
    args = ap.parse_args()

    checks = [check_health(), check_stats(), check_eval(), check_pending_handovers(), check_badcases()]
    all_ok = all(c["ok"] for c in checks)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = {
        "ts": ts,
        "base_url": BASE_URL,
        "thresholds": {"min_auto_rate": MIN_AUTO_RATE, "max_pending_handovers": MAX_PENDING_HANDOVERS,
                       "max_open_badcases": MAX_OPEN_BADCASES, "hit3": HIT3_THRESHOLD},
        "checks": checks,
        "all_ok": all_ok,
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LOG_DIR / f"healthcheck-{datetime.now().strftime('%Y-%m-%d')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "✅ 全部健康" if all_ok else "⚠️ 存在异常"
    print(f"[{ts}] 小答巡检：{status}")
    for c in checks:
        mark = "✅" if c["ok"] else "❌"
        print(f"  {mark} {c['name']}：{c['detail']}")
    if not all_ok:
        lines = [f"[{ts}] 小答巡检异常"] + [f"- {c['name']}: {c['detail']}" for c in checks if not c["ok"]]
        print("  " + "\n  ".join(lines[1:]))
        push_alert("\n".join(lines))

    if not args.cron:
        print(f"  报告：{report_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
