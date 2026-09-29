#!/usr/bin/env bash
# 每天把演示世界挪到今天。**给 launchd 跑的,没人看着。**
#
# ⚠️⚠️ **这个文件里的变量名一律 ASCII。** bash 不接受中文变量名 ——
# 写 `日志=...` 会当场 syntax error。这个仓库为这条栽过四次
# (tools/fetch_model.sh、CI 里的 `红=0`、管理后台的 gen_fresh.sh、还有一次)。
# **本机是 zsh、launchd 跑的是 sh/bash,而 zsh 允许中文变量名** ——
# 「我敲着能跑」和「定时任务能跑」的差别可以只是一个 shell。
#
# ## 为什么不是一行 `python3 tools/shift_world.py`
#
# **一个静默失败的定时任务,比没有定时任务更糟。**
# 没有的时候人知道要手动跑;装了之后人以为世界每天在跟着。
#
# 而 `shift_world.py --check` 要等到**落后 14 天**才判红 ——
# 也就是说任务挂了,两周内没有任何信号。
#
# 所以这个包装做三件事:
#   ① 每次**都**记一个「尝试过」的时间戳(哪怕这次啥也没挪)
#   ② 成功了再记一个「成功过」的时间戳
#   ③ 失败就退非 0,并把原因留在日志里
#
# ⚠️ **两个时间戳,不是一个。** 它们分开的理由是两种失败下一步完全不同:
#   · 「尝试过」也旧了  → **任务根本没在跑**(没装上 / 被卸了 / 机器一直关机)→ 去修任务
#   · 「尝试过」是新的、「成功过」是旧的 → **在跑但每次都失败** → 去看日志
# 只记一个的话,这两种在那个时间戳上长得一模一样。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

STATE_DIR="$ROOT/.feynman"
LOG="$STATE_DIR/world-shift.log"
TRIED="$STATE_DIR/world-shift-tried"
OK="$STATE_DIR/world-shift-ok"
mkdir -p "$STATE_DIR"

TS="$(date '+%Y-%m-%d %H:%M:%S')"
# ① 先记「尝试过」—— **在干活之前记**。放到后面记的话,
#    脚本挂在中途时这个时间戳也不会更新,于是「没在跑」和「跑了但挂了」又混在一起。
date '+%Y-%m-%dT%H:%M:%S' > "$TRIED"

{
  echo "──── $TS 开始 ────"
  # 先看世界自不自洽。不自洽的时候**不要挪** ——
  # 往一个半平移的库上再挪一次,只会得到一个更说不清的库。
  if ! python3 tools/shift_world.py --check > "$STATE_DIR/world-shift-check.out" 2>&1; then
    echo "❌ --check 不过,**这次不挪**。下面是 check 的输出:"
    tail -20 "$STATE_DIR/world-shift-check.out"
    echo "   (人要看一眼:python3 tools/shift_world.py --check)"
    exit 1
  fi
  python3 tools/shift_world.py
} >> "$LOG" 2>&1
RC=$?

if [ "$RC" -eq 0 ]; then
  date '+%Y-%m-%dT%H:%M:%S' > "$OK"
  echo "✅ $TS 平移完成" >> "$LOG"
else
  echo "❌ $TS 平移失败(退出码 $RC)—— **「成功过」那个时间戳没有更新**" >> "$LOG"
fi

# 日志留最近 2000 行就够。不截的话它会一直长,而一个没人读的日志长到多大都一样。
if [ -f "$LOG" ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exit "$RC"
