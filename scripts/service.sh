#!/usr/bin/env bash
# XGEO 看板常驻服务（macOS LaunchAgent）
#
#   ./service.sh install     注册并启动：登录自启、崩溃自动拉起、不随终端/Claude 退出
#   ./service.sh uninstall   停止并移除
#   ./service.sh status      看运行状态
#   ./service.sh log         跟看服务日志
#
# 说明：服务只绑定 127.0.0.1:8765（插件与周期复跑都依赖这个固定端口）。
# 常驻的另一个收益：geo.json 里配置的「周期复跑」只在看板运行时触发，
# 服务常驻后到期就会自动跑完整一期，不再依赖你手动开着看板。

set -euo pipefail

LABEL="cc.xgeo.dashboard"
# 改名前的 label。老实例还在跑的话必须先卸掉——不然它会继续占着 8765，
# 新服务起不来（或者两个实例互相抢端口）。
LEGACY_LABEL="cc.geolook.dashboard"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/xgeo-dashboard.log"
PY="$(command -v python3 || true)"
# set -e 下 command -v 找不到会直接中止，用户只看到一个 exit 1、零提示
[ -n "$PY" ] || { echo "✗ 找不到 python3（macOS 可先跑 xcode-select --install）"; exit 1; }
UID_N="$(id -u)"

# plist 是 XML：路径里出现 & 或 < 会写出非法 XML，而 launchctl 只报它自己的
# 解析错，用户看不出问题出在路径上
xml_esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

# 卸掉旧 label 注册的服务（改名后的一次性清理，对新装的用户是空操作）
drop_legacy() {
  launchctl bootout "gui/$UID_N/$LEGACY_LABEL" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
}

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$(xml_esc "$LABEL")</string>
  <key>ProgramArguments</key><array>
    <string>$(xml_esc "$PY")</string>
    <string>$(xml_esc "$ROOT/scripts/geo.py")</string>
    <string>ui</string>
    <string>--no-open</string>
    <string>--port</string><string>8765</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml_esc "$ROOT")</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml_esc "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml_esc "$LOG")</string>
</dict></plist>
EOF
    # 先清掉可能占着端口的临时实例，让常驻服务接管
    drop_legacy
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
    OLD=$(lsof -ti :8765 2>/dev/null || true)
    [ -n "$OLD" ] && kill $OLD 2>/dev/null && sleep 1
    launchctl bootstrap "gui/$UID_N" "$PLIST"
    sleep 2
    # 看状态码，不用 curl -f：配了 XGEO_TOKEN 时 /api/projects 回 401，
    # -f 判失败 → 服务明明起好了却报「服务未响应」。200 和 401 都算活着。
    code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8765/api/projects || true)
    if [ "$code" = "200" ] || [ "$code" = "401" ]; then
      echo "✓ 已注册常驻服务：$LABEL"
      echo "  http://127.0.0.1:8765 · 登录自启 · 崩溃自动拉起 · 日志 $LOG"
      echo "  关闭 Claude / 终端都不影响；卸载：./service.sh uninstall"
    else
      echo "✗ 服务未响应，查看日志：tail -50 $LOG"; exit 1
    fi ;;

  uninstall)
    drop_legacy
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null && echo "✓ 已停止并移除" || echo "服务本就不在运行"
    rm -f "$PLIST" ;;

  status)
    if launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1; then
      PID=$(launchctl print "gui/$UID_N/$LABEL" 2>/dev/null | awk '/pid =/{print $3}')
      echo "✓ 常驻服务运行中（pid ${PID:-?}）"
      code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8765/api/projects || true)
      { [ "$code" = "200" ] || [ "$code" = "401" ]; } \
        && echo "✓ 看板可访问：http://127.0.0.1:8765" || echo "✗ 端口无响应，看日志：$LOG"
    else
      echo "未安装。运行：./service.sh install"
    fi ;;

  log) tail -f "$LOG" ;;

  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
