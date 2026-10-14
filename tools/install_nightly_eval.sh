#!/usr/bin/env bash
# 装/卸「每天 0 点自动跑全套评测」的定时任务(macOS launchd)。用户 2026-10-14 拍:「放在12点跑」。
#
#     bash tools/install_nightly_eval.sh          # 装
#     bash tools/install_nightly_eval.sh --卸     # 卸(一行就能撤)
#     bash tools/install_nightly_eval.sh --看     # 看装没装、上次跑成没成
#
# 做法照抄 install_world_cron.sh(05:10 那个):用户级 LaunchAgents、launchd 而不是 crontab
# (笔记本睡着时 cron 那一跳就丢了)。⚠️ 但**睡醒补跑在这里是要挡的** —— 早上醒来补跑会和人抢库窗口,
# 所以 nightly_eval.py 自己判时间窗,不在 0:00–4:30 就只记一行「跳过」。
#
# ⚠️ 变量名一律 ASCII —— bash 不接受中文变量名(这个仓库栽过四次)。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.lanxiu.nightly-eval"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOUR=0
MINUTE=0
# launchd 起的进程环境极简,PATH 要自己给 —— 评测会起 claude 命令行(在 ~/.local/bin),
# 它又要 node(/usr/local/bin);python3 在 Python.framework 下。少一个,夜里就是一行「找不到」。
LPATH="$HOME/.local/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.14/bin:/usr/bin:/bin:/usr/sbin:/sbin"

look() {
  echo "▸ plist:$PLIST"
  [ -f "$PLIST" ] && echo "   在" || echo "   **不在**(没装)"
  echo "▸ launchd 认不认:"
  launchctl list 2>/dev/null | grep -i "nightly-eval" || echo "   (没有这个任务)"
  echo "▸ 最近几行日志(.feynman/nightly-eval.log):"
  tail -5 "$ROOT/.feynman/nightly-eval.log" 2>/dev/null | sed 's/^/   /' || echo "   (还没有)"
}

case "${1:-装}" in
  --看|--check) look; exit 0;;
  --卸|--uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null \
      || launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅ 卸了。夜里不再自动跑评测。"
    exit 0;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/.feynman"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Library/Frameworks/Python.framework/Versions/3.14/bin/python3</string>
    <string>$ROOT/tools/nightly_eval.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$ROOT/.feynman/nightly-eval-launchd.log</string>
  <key>StandardErrorPath</key><string>$ROOT/.feynman/nightly-eval-launchd.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$LPATH</string></dict>
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
  exit 1
fi
echo "   每天 $(printf '%02d:%02d' $HOUR $MINUTE) 跑;0:00–4:30 之外醒来补跑只记「跳过」"
echo "   夜报:.feynman/nightly-eval/<日期>.md · 日志:.feynman/nightly-eval.log"
echo "   卸载:bash tools/install_nightly_eval.sh --卸"
echo
look
