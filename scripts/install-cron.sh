#!/usr/bin/env bash
# 安装小答自动化巡检 CronJob：每天 08:00 跑巡检脚本，异常自动推群机器人告警。
# 用法：
#   ./scripts/install-cron.sh            # 安装（每天 08:00）
#   ./scripts/install-cron.sh 22:30      # 自定义时间（HH:MM）
#   ./scripts/install-cron.sh --remove   # 卸载
# 可选环境变量（写入 crontab 前 export 即可）：
#   WECHAT_WEBHOOK / DINGTALK_WEBHOOK / XD_BASE_URL / 各阈值
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="# xiaoda-healthcheck"
CRON_LINE="${TAG} $("${ROOT}/backend/.venv/bin/python" -c 'print("")' 2>/dev/null || true)"

if [[ "${1:-}" == "--remove" ]]; then
  crontab -l 2>/dev/null | grep -v -F "$TAG" | crontab -
  echo "已卸载巡检 CronJob"
  exit 0
fi

TIME="${1:-08:00}"
HOUR="${TIME%%:*}"
MINUTE="${TIME##*:}"
case "$MINUTE" in
  *[!0-9]*|""|*:*) echo "时间格式错误，示例：08:00 / 22:30" >&2; exit 1 ;;
esac

# 环境变量透传（webhook 与阈值）
ENVS=()
for var in WECHAT_WEBHOOK DINGTALK_WEBHOOK XD_BASE_URL XD_MIN_AUTO_RATE XD_MAX_PENDING_HANDOVERS XD_MAX_OPEN_BADCASES XD_HIT3_THRESHOLD; do
  val="${!var:-}"
  [ -n "$val" ] && ENVS+=("$var=$val")
done
ENV_PREFIX=""
[ "${#ENVS[@]}" -gt 0 ] && ENV_PREFIX="$(printf '%s ' "${ENVS[@]}") "

LINE="${TAG} ${MINUTE} ${HOUR} * * * cd $ROOT && ${ENV_PREFIX}${ROOT}/backend/.venv/bin/python scripts/healthcheck.py --cron >> ${ROOT}/backend/logs/healthcheck-cron.log 2>&1 || true"

# 合并安装（去重）
if crontab -l 2>/dev/null | grep -q -F "$TAG"; then
  crontab -l 2>/dev/null | grep -v -F "$TAG" > /tmp/xd_cron.tmp || true
  cat /tmp/xd_cron.tmp > /tmp/xd_cron_new
else
  crontab -l 2>/dev/null > /tmp/xd_cron_new || true
fi
echo "$LINE" >> /tmp/xd_cron_new
crontab /tmp/xd_cron_new
rm -f /tmp/xd_cron.tmp /tmp/xd_cron_new

echo "✅ 巡检 CronJob 已安装：每天 $TIME 运行（$ROOT/scripts/healthcheck.py）"
echo "   日志：$ROOT/backend/logs/healthcheck-cron.log"
echo "   手动卸载：./scripts/install-cron.sh --remove"
crontab -l | grep -F "$TAG" | sed 's/^/   /'
