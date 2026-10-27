#!/usr/bin/env bash
# 小答 · 一键启动/停止（后端 8000 + 前端 5173）
# 用法：
#   ./dev.sh        启动前后端
#   ./dev.sh stop   停止前后端
#   ./dev.sh status 查看健康状态
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT_BACKEND=8000
PORT_FRONTEND=5173

stop_all() {
  echo "[停止] 清理端口 $PORT_BACKEND / $PORT_FRONTEND 上的进程..."
  lsof -ti :"$PORT_BACKEND" | xargs kill -9 2>/dev/null || true
  lsof -ti :"$PORT_FRONTEND" | xargs kill -9 2>/dev/null || true
  rm -f "$ROOT/.backend.pid" "$ROOT/.frontend.pid"
  sleep 1
  echo "[停止] 完成"
}

status_all() {
  echo "--- 后端 http://127.0.0.1:$PORT_BACKEND ---"
  curl -s -m 2 http://127.0.0.1:"$PORT_BACKEND"/health && echo || echo "（未运行）"
  echo "--- 前端 http://localhost:$PORT_FRONTEND ---"
  curl -s -o /dev/null -m 2 -w "HTTP %{http_code}\n" http://localhost:"$PORT_FRONTEND"/ || echo "（未运行）"
}

case "${1:-start}" in
  stop)
    stop_all
    exit 0
    ;;
  status)
    status_all
    exit 0
    ;;
  start|"")
    ;;
  *)
    echo "用法: ./dev.sh [start|stop|status]"
    exit 1
    ;;
esac

echo "[1/3] 清理旧进程（避免端口占用）"
lsof -ti :"$PORT_BACKEND" | xargs kill -9 2>/dev/null || true
lsof -ti :"$PORT_FRONTEND" | xargs kill -9 2>/dev/null || true
sleep 1

echo "[2/3] 启动后端 http://127.0.0.1:${PORT_BACKEND}（读取 .env，有 Key 自动走 DeepSeek 真实模式）"
cd "$ROOT/backend"
nohup .venv/bin/uvicorn app.main:app --port "$PORT_BACKEND" --host 127.0.0.1 \
  > "$ROOT/backend.log" 2>&1 &
disown
echo $! > "$ROOT/.backend.pid"

echo "[3/3] 启动前端 http://localhost:$PORT_FRONTEND"
cd "$ROOT/frontend"
nohup npm run dev > "$ROOT/frontend.log" 2>&1 &
disown
echo $! > "$ROOT/.frontend.pid"

# 等待后端就绪（最长 20s）
for _ in $(seq 1 40); do
  curl -s -o /dev/null -m 1 http://127.0.0.1:"$PORT_BACKEND"/health && break
  sleep 0.5
done

echo
status_all
echo
echo "✅ 启动完成：打开 http://localhost:$PORT_FRONTEND"
echo "   日志：backend.log（后端）/ frontend.log（前端）"
echo "   停止：./dev.sh stop"
