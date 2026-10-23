#!/bin/bash
# 三个服务常驻:管理后台 :8760 + 智能运维平台 :8770(用户 2026-10-23 拍)+ AI 管理后台 :8801(同日晚拍「设成常驻吧」)。
#
#   ./tools/always_on.sh install     装上:登录就起、崩了自动拉起、关终端也不停
#   ./tools/always_on.sh uninstall   卸掉:回到「./start.sh 手起」的老样子
#   ./tools/always_on.sh status      两个服务在不在、端口通不通
#   ./tools/always_on.sh restart     拉了新代码之后重启(服务跑的是起来那一刻的代码)
#
# ⚠️ 装上之后别再用 `kill` 关它 —— launchd 会立刻再拉起来,这正是常驻的意思。
#    要停就 uninstall。./start.sh 也认得常驻:装了就改成重启常驻服务,不再自己 nohup 一份。
cd "$(dirname "$0")/.."
D="$HOME/Library/LaunchAgents"
U="gui/$(id -u)"
NAMES="backend agentsite aimc"

port() { case $1 in backend) echo 8760;; agentsite) echo 8770;; aimc) echo 8801;; esac; }

case "${1:-status}" in
  install)
    [ -d agentsite/.venv ] || { echo "❌ 没有 agentsite/.venv —— 先跑一次 ./start.sh 建好再装"; exit 1; }
    [ -f backend/lanxiu.db ] || { echo "❌ 没有库 —— 先跑一次 ./start.sh 建库再装"; exit 1; }
    [ -d 管理后台/.venv ] || { echo "❌ 没有 管理后台/.venv —— 先在 管理后台/ 里 make setup 再装"; exit 1; }
    for n in $NAMES; do
      # 手起的那份先停掉,不然常驻的那份抢不到端口、起来就退、launchd 每 10 秒重拉一次
      kill $(lsof -nP -iTCP:$(port $n) -sTCP:LISTEN -t 2>/dev/null) 2>/dev/null
      launchctl bootout "$U/com.lanxiu.$n" 2>/dev/null
      cp "tools/com.lanxiu.$n.plist" "$D/com.lanxiu.$n.plist"
      launchctl bootstrap "$U" "$D/com.lanxiu.$n.plist" && echo "  装上 com.lanxiu.$n"
    done
    sleep 4; "$0" status ;;
  uninstall)
    for n in $NAMES; do
      launchctl bootout "$U/com.lanxiu.$n" 2>/dev/null && echo "  卸掉 com.lanxiu.$n"
      rm -f "$D/com.lanxiu.$n.plist"
    done ;;
  restart)
    for n in $NAMES; do launchctl kickstart -k "$U/com.lanxiu.$n" && echo "  重启 com.lanxiu.$n"; done
    sleep 4; "$0" status ;;
  status)
    for n in $NAMES; do
      p=$(port $n)
      if launchctl print "$U/com.lanxiu.$n" >/dev/null 2>&1; then STATE="常驻"; else STATE="没装常驻"; fi
      CODE=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$p/")
      printf "  %-10s :%s  %s  HTTP %s  (日志 /tmp/lanxiu-%s.log)\n" "$n" "$p" "$STATE" "$CODE" "$n"
    done ;;
  *) echo "用法:$0 install | uninstall | status | restart"; exit 2 ;;
esac
