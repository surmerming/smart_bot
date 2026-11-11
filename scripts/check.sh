#!/usr/bin/env bash
# 本地一键质量检查（V1.5 质量保障）：后端测试 + 检索评估 + 压测冒烟 + 前端构建。
# 用法：./scripts/check.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY=python3

echo "== 1/5 后端 API 测试（Mock，离线） =="
(cd "$ROOT/backend" && "$PY" -m pytest tests/test_api.py tests/test_badcase_report.py tests/test_v2_ws_copilot.py tests/test_kb_admin.py tests/test_v2_ops.py tests/test_v2_gaps.py -q)

echo ""
echo "== 2/5 检索评估（黄金测试集） =="
(cd "$ROOT/backend" && "$PY" tests/eval.py)

echo ""
echo "== 3/5 并发压测冒烟（进程内 Mock） =="
(cd "$ROOT/backend" && "$PY" tests/load_test.py --concurrency 4 --total 5)

echo ""
echo "== 4/5 前端构建（官网 / 坐席 / 看板） =="
(cd "$ROOT/frontend" && pnpm run build)

echo ""
echo "== 5/5 知识库健康体检（重复 FAQ 检测） =="
(cd "$ROOT/backend" && "$PY" tools/check_duplicates.py)

echo ""
echo "✅ 全部检查通过"
