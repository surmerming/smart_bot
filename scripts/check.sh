#!/usr/bin/env bash
# 本地一键质量检查（V1.5 质量保障）：后端测试 + 检索评估 + 压测冒烟 + 前端构建。
# 用法：./scripts/check.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY=python3

echo "== 1/4 后端 API 测试（Mock，离线） =="
(cd "$ROOT/backend" && "$PY" -m pytest tests/test_api.py tests/test_badcase_report.py -q)

echo ""
echo "== 2/4 检索评估（黄金测试集） =="
(cd "$ROOT/backend" && "$PY" tests/eval.py)

echo ""
echo "== 3/4 并发压测冒烟（进程内 Mock） =="
(cd "$ROOT/backend" && "$PY" tests/load_test.py --concurrency 4 --total 5)

echo ""
echo "== 4/4 前端构建（官网 / 坐席 / 看板） =="
(cd "$ROOT/frontend" && npm run build)

echo ""
echo "✅ 全部检查通过"
