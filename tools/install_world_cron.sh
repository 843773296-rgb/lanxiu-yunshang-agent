#!/usr/bin/env bash
# 装/卸「每日把演示世界挪到今天」的定时任务(macOS launchd)。
#
#     bash tools/install_world_cron.sh          # 装
#     bash tools/install_world_cron.sh --卸     # 卸(一行就能撤)
#     bash tools/install_world_cron.sh --看     # 看装没装、上次跑成没成
#
# ⚠️ 变量名一律 ASCII —— bash 不接受中文变量名(这个仓库栽过四次)。
#
# ## 为什么用 launchd 不用 crontab
#
# · **机器睡着的时候 cron 那一跳就丢了**,launchd 会在醒来之后补跑。
#   这台是笔记本,凌晨多半是睡着的 —— 用 cron 的话任务基本不会跑,
#   而**「装了但从来没跑过」和「没装」在结果上一模一样**。
# · launchd 的日志和退出码有地方落(StandardErrorPath),cron 只会发本地邮件(没人看)。
#
# ## ⚠️ 装在用户级,不碰系统
#
# plist 放 `~/Library/LaunchAgents/`(当前用户自己的),不是 `/Library/LaunchDaemons`。
# 卸载就是删一个文件 + 一条 `launchctl bootout` —— **一行能撤的东西才好装**。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.lanxiu.worldshift"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# 凌晨 5:10 —— 挑这个点的理由:这个脚本一次重写 30 万+ 个日期值,
# 中途被人读到的库是**平移到一半的库**。挑没人干活的时候,
# 把「和人撞上」的概率压到最低(撞上也有互斥标记兜着,但那是第二道)。
HOUR=5
MINUTE=10

看() {
  echo "▸ plist:$PLIST"
  [ -f "$PLIST" ] && echo "   在" || echo "   **不在**(没装)"
  echo "▸ launchd 认不认:"
  launchctl list 2>/dev/null | grep -i lanxiu || echo "   (没有 lanxiu 相关的任务)"
  echo "▸ 跑成没成:"
  python3 "$ROOT/tools/cron_health_check.py" || true
}

case "${1:-装}" in
  --看|--check) 看; exit 0;;
  --卸|--uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
      || launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅ 卸了。**注意:卸了之后世界就不会自己跟着日期走了** ——"
    echo "   而「数据停在过去」的表现是「下周一条单都没有」,和「真的没活」长得一样。"
    exit 0;;
esac

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/tools/daily_shift.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <!-- 机器睡着时这一跳会在醒来后补跑;这正是不用 crontab 的理由。 -->
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$ROOT/.feynman/world-shift-launchd.log</string>
  <key>StandardErrorPath</key><string>$ROOT/.feynman/world-shift-launchd.log</string>
  <!-- launchd 起的进程环境极简,PATH 要自己给,不然 python3 找不到。
       **「我在终端里能跑」和「launchd 里能跑」的差别常常就是这一行。** -->
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
  echo "✅ 装上了(bootstrap)"
elif launchctl load "$PLIST" 2>/dev/null; then
  echo "✅ 装上了(load,旧接口)"
else
  echo "❌ launchctl 没接受 —— plist 已经写好了($PLIST),但没加载成功。"
  echo "   自己跑一次:launchctl bootstrap gui/\$(id -u) \"$PLIST\""
  exit 1
fi
echo "   每天 $(printf '%02d:%02d' $HOUR $MINUTE) 跑一次;日志 .feynman/daily-shift.log"
echo "   卸载:bash tools/install_world_cron.sh --卸"
echo
看
