#!/usr/bin/env bash
# 每天把演示世界挪到当天 —— 定时任务调的就是这一行。
#
# 为什么需要它:数据不挪的话每天往后落一天,而**落的过程没有任何提示** ——
# 直到有人问「下周有哪些单」,发现一条都没有。那正是 2026-09-24 用户撞到的事。
#
# ⚠️⚠️ **变量名一律 ASCII。** bash 不接受中文变量名(这个仓库栽过四次)。
# 本机是 zsh、launchd 跑的是 bash/sh,而 zsh 允许中文变量名 ——
# **「我敲着能跑」和「定时任务能跑」的差别可以只是一个 shell。**
#
# ## 六条刻意的设计(①—④ 是原版的,⑤⑥ 是 2026-09-29 装定时任务时加的)
#
#   ① **可反复跑**:已经在今天就什么都不做(shift_world 自己判,差 0 天直接返回)
#   ② **重建进行中就让开**:两个进程同时写同一个库,只会得到一个半成品
#   ③ **跑完自己核一遍**:挪完要世界自洽(库说的那天 = 数据实际的那天),
#      不自洽就以非零退出 —— 定时任务的失败**默认是没人看的**,所以要留在日志里
#   ④ 日志**带时间戳、只追加**:要回答的是「它到底有没有跑」,不是「最后一次怎么样」
#   ⑤ **开跑前也核一遍**:③ 和 ⑤ 问的是两个问题 ——
#      跑前核是「这个库能不能挪」(半平移的库上再挪一次只会更说不清),
#      跑后核是「我挪完有没有挪坏」。**两道都要。**
#   ⑥ **记两个时间戳**(见下),这样「任务没在跑」和「在跑但每次失败」分得开
#
# ## ⚠️ 为什么是两个时间戳
#
#     .feynman/world-shift-tried   每次都记,**在干活之前记**
#     .feynman/world-shift-ok      成功了才记
#
# 两种失败下一步完全不同:
#   · 「尝试过」也旧了 → **任务根本没在跑**(没装上/被卸了/机器一直关机)→ 修任务
#   · 「尝试过」新、「成功过」旧 → **在跑但每次都失败** → 看日志
# 只记一个的话,这两种在那个时间戳上长得一模一样。
# 「尝试过」要在干活**之前**记:放到后面记,脚本挂在中途时它也不会更新,
# 于是两种又混回一起了。
#
# 判它健康不健康:`python3 tools/cron_health_check.py`(已进 check.sh)。
set -u
cd "$(dirname "$0")/.." || exit 1
LOG=".feynman/daily-shift.log"
TRIED=".feynman/world-shift-tried"
OK=".feynman/world-shift-ok"
mkdir -p .feynman
say(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# ⚠️ **让开的那两种情况不更新「尝试过」** —— 它们不是失败,
# 但也不是「跑过一次」。更新了的话,一个永远在重建的机器会显得任务很健康。
if [ -f backend/.rebuilding ]; then
  say "跳过:有重建在跑(backend/.rebuilding 还在)"; exit 0
fi
if [ ! -f backend/lanxiu.db ]; then
  say "跳过:还没有库(没重建过)"; exit 0
fi

date '+%Y-%m-%dT%H:%M:%S' > "$TRIED"
say "开始"

# ⑤ 开跑前先核:世界不自洽的时候**不要挪** ——
#    往一个半平移的库上再挪一次,只会得到一个更说不清的库。
if ! OUT0=$(python3 tools/shift_world.py --check 2>&1); then
  printf '%s\n' "$OUT0" | sed 's/^/    /' >> "$LOG"
  say "❌ 开跑前就不自洽,**这次不挪** —— 人要看一眼上面那几行"; exit 1
fi

if OUT=$(python3 tools/shift_world.py 2>&1); then
  printf '%s\n' "$OUT" | sed 's/^/    /' >> "$LOG"
else
  printf '%s\n' "$OUT" | sed 's/^/    /' >> "$LOG"
  say "❌ 平移失败"; exit 1
fi

# ③ 跑完自己核一遍
if OUT2=$(python3 tools/shift_world.py --check 2>&1); then
  date '+%Y-%m-%dT%H:%M:%S' > "$OK"
  say "✅ 完成,世界自洽"
else
  printf '%s\n' "$OUT2" | sed 's/^/    /' >> "$LOG"
  say "❌ 挪完了但世界不自洽 —— 去看上面那几行。**「成功过」那个时间戳没有更新**"; exit 1
fi

# ── ⑦ 每日上新(2026-10-09 加的)───────────────────────────────────────
#
# 上面那几步只把**日期**往前挪,**一条新记录都没有**。
# 用户 2026-10-09 的原话:「数据这几天没上新」「每天看到的是同一个世界,只是日期变了」。
#
# ⚠️ **两步的先后不能换**:
#   先 `daily_fresh`(造新单 / 跟进 / 预约 / 评价 + 推进存量),
#   再 `lifecycle_refresh`(按世界今天重算档位并对齐历史)——
#   新单改了「最近互动」这类事实,档位要跟着变,否则 `lifecycle_sync_check` 的 C 类会红。
#
# ⚠️ **它们的失败不改「成功过」那个时间戳** —— 那个戳说的是「平移成功了」,
# 而平移确实成功了。两件事混进一个戳,就分不清是哪一步坏的。
# 失败只记日志 + 让整轮以非零退出(定时任务的失败默认没人看,所以要留在日志里)。
FRESH_FAIL=0
if OUT3=$(python3 tools/daily_fresh.py --做 2>&1); then
  printf '%s\n' "$OUT3" | sed 's/^/    /' >> "$LOG"
  say "✅ 每日上新完成"
else
  printf '%s\n' "$OUT3" | sed 's/^/    /' >> "$LOG"
  say "❌ 每日上新失败 —— 回滚:python3 tools/daily_fresh.py --回滚"; FRESH_FAIL=1
fi
if OUT4=$(python3 tools/lifecycle_refresh.py --做 2>&1); then
  printf '%s\n' "$OUT4" | sed 's/^/    /' >> "$LOG"
  say "✅ 档位按今天重算完成"
else
  printf '%s\n' "$OUT4" | sed 's/^/    /' >> "$LOG"
  say "❌ 档位重算失败 —— 存的档位和今天的事实对不上了,页面报的人数会是旧的"; FRESH_FAIL=1
fi

# 日志留最近 3000 行。不截的话它会一直长 ——
# 而④说的是「要答得出它到底有没有跑」,三千行足够答上几个月。
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 3000 ]; then
  tail -n 3000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# ⚠️ **非零退出要放在最后**(日志截断之后)—— 提前 exit 会把截断那一步跳掉,
# 而日志一直长的后果要几个月后才看得出来。
if [ "$FRESH_FAIL" -ne 0 ]; then
  say "❌ 这一轮有步骤失败(见上面)—— 平移本身是成功的,「成功过」那个戳照常更新了"
  exit 1
fi
