#!/usr/bin/env bash
# 每天把演示世界挪到当天 —— 定时任务调的就是这一行。
#
# 为什么需要它:数据不挪的话每天往后落一天,而**落的过程没有任何提示** ——
# 直到有人问「下周有哪些单」,发现一条都没有。那正是 2026-09-24 用户撞到的事。
#
# 四条刻意的设计:
#   ① **可反复跑**:已经在今天就什么都不做(shift_world 自己判,差 0 天直接返回)
#   ② **重建进行中就让开**:两个进程同时写同一个库,只会得到一个半成品
#   ③ **跑完自己核一遍**:挪完要世界自洽(库说的那天 = 数据实际的那天),
#      不自洽就以非零退出 —— 定时任务的失败**默认是没人看的**,所以要留在日志里
#   ④ 日志**带时间戳、只追加**:要回答的是「它到底有没有跑」,而不是「最后一次怎么样」
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=".feynman/daily-shift.log"
mkdir -p .feynman
say(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

if [ -f backend/.rebuilding ]; then
  say "跳过:有重建在跑(backend/.rebuilding 还在)"; exit 0
fi
if [ ! -f backend/lanxiu.db ]; then
  say "跳过:还没有库(没重建过)"; exit 0
fi

say "开始"
if OUT=$(python3 tools/shift_world.py 2>&1); then
  printf '%s\n' "$OUT" | sed 's/^/    /' >> "$LOG"
else
  printf '%s\n' "$OUT" | sed 's/^/    /' >> "$LOG"
  say "❌ 平移失败"; exit 1
fi
if OUT2=$(python3 tools/shift_world.py --check 2>&1); then
  say "✅ 完成,世界自洽"
else
  printf '%s\n' "$OUT2" | sed 's/^/    /' >> "$LOG"
  say "❌ 挪完了但世界不自洽 —— 去看上面那几行"; exit 1
fi
