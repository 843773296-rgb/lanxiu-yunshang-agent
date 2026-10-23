#!/bin/bash
# 共享资源锁 —— 这台机器上同一时刻只许一个工作区跑门禁 / 冒烟 / 写共享库。
#
# 用法:
#     ./tools/gate_lock.sh ./check.sh
#     ./tools/gate_lock.sh python3 tools/ensure_tables.py
#     ./tools/gate_lock.sh --who "子任务D" ./check.sh
#     ./tools/gate_lock.sh --selftest
#
# 退出码:原样传回被包的那条命令的退出码;拿不到锁是 3,用法错是 2。
#
# ⚠️⚠️ **变量名一律 ASCII。** 第一版用的是中文变量名(`锁目录=` 这种)——
# 这个项目的 Python 到处用中文标识符,我把那个习惯直接搬进了 bash,
# 而 **bash 不支持非 ASCII 变量名**:`锁目录=/tmp/x` 不是赋值,
# 是「找不到 `锁目录=/tmp/x` 这个命令」。
# 于是所有变量都是空的,脚本在 `mkdir ""` 上**无限打转**。
# > `bash -n` 只查语法、不查变量名,所以它报「语法 OK」;
# > 赋值失败只往 stderr 吐一行 `command not found`(很容易被管道吞掉),
# > 然后**一个在等别人锁的脚本,和一个在空路径上打转的脚本,从外面看一模一样** ——
# > 都是「挂着不动」。注释和输出照旧中文,**变量名不行**。
#
# ── 为什么要它 ────────────────────────────────────────────────────────
#
# 2026-10-23 用户要求提速,一下开到 **6 个 git 工作区**(主检出 + 评测线 +
# 4 个子任务)。库副本各自独立,但**这台机器只有一份 CPU / IO、一份 8770 常驻服务、
# 一份共享库 `backend/lanxiu.db`**。并发跑的后果不是慢,是**造出跟改动无关的红**:
# 门禁里有按时长判的东西,全线变慢时带超时的那几条会真的红,
# 而那种红查起来**和真回归一模一样**。
#
# ⚠️ 范围是**共享资源**,不只是门禁:写共享库(`ensure_tables` 建表、
# `shift_world` 平移、批量 UPDATE)和打共享 8770 的冒烟,**和门禁互相干扰的后果一样**。
# 名字叫「共享资源锁」就是为了防下一个人想「我只是写库,不用拿锁」。
#
# ── 锁目录为什么还叫 gate.lock(别改)────────────────────────────────
#
# ⚠️ **路径必须保持 `/tmp/lanxiu-gate.lock`,哪怕名字已经不准了。**
# 这把锁是从并行会话那段 shell snippet 演进来的,而**过渡期里那几个子任务
# 用的还是 snippet 版**。换一个路径的后果是:两边各锁各的,
# **互斥当场失效,而双方都显示「我拿到锁了」** ——
# 一把真的互斥的锁,和两把各自锁空气的锁,在那行「拿到锁」上长得一模一样。
# 等六个工作区全部改成调这个脚本之后再考虑改名。
#
# 三个环境变量能盖掉下面的默认值,**而那不是为了灵活,是为了这个脚本自己能被验**:
# 第一版路径写死,于是想自测「陈锁会不会被抢」时只能去动那把真锁 ——
# 而当时子任务 A 正拿着它跑门禁,一个 `rm -rf` 就把它那一轮掀翻了。
# > 一个**没法在不打扰别人的情况下被验**的守卫,等于一个没被验过的守卫:
# > 它要么没人验,要么验的时候出事。
# 咬合记录(左边改坏了什么,右边预期红的那一条;可执行规格在 tools/bite_specs.json)
# ⚠️ 两条攻的是**两种不同的假绿**:
#   ① 关掉抢陈锁那一支 → 一次崩掉就让后面所有工作区**静默卡死**
#   ② 让包装器永远退 0 → **门禁从此永远绿**(同一族:打印 ❌ 和拦截是两件事;
#      一个吃掉退出码的包装器,比没有包装器危险得多)
# 咬合 = [
#   ("把「原主进程已经不在了就抢锁」那一支关掉", "陈锁(原主进程已不在)被抢走"),
#   ("让包装器永远退 0(吃掉被包命令的退出码)", "被包命令的退出码原样传回"),
# ]

LOCK_DIR="${LANXIU_LOCK_DIR:-/tmp/lanxiu-gate.lock}"
OWNER_FILE="$LOCK_DIR/owner"
CAP_SEC="${LANXIU_LOCK_CAP:-3600}"      # 等过一小时就失败退出 —— 无人值守的夜跑不能挂死
SHOUT_SEC="${LANXIU_LOCK_SHOUT:-60}"    # 等的时候每隔多久打印一行

WHO="${LANXIU_LOCK_WHO:-$(basename "$(pwd)")}"
if [ "${1:-}" = "--who" ] || [ "${1:-}" = "--谁" ]; then
  WHO="${2:-}"; shift 2
fi

# ── 自测:在**临时锁目录**上验五件事,一个字都不碰那把真锁 ──────────────
if [ "${1:-}" = "--selftest" ] || [ "${1:-}" = "--自测" ]; then
  ME="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  BAD=0
  say() {
    if [ "$1" = 0 ]; then echo "  ✅ $2"; else echo "  ❌ $2  —— $3"; BAD=$((BAD + 1)); fi
  }
  echo "共享资源锁 · 自测(临时目录上跑,不碰 $LOCK_DIR)"
  echo "================================================================"

  # ① 正常:拿到锁、命令真跑了、锁还掉
  D="$(mktemp -d)/lock"
  OUT="$(LANXIU_LOCK_DIR="$D" "$ME" --who 自测1 echo 跑到了 2>/dev/null)"
  if [ "$OUT" = "跑到了" ] && [ ! -d "$D" ]; then say 0 "正常路径:拿锁 → 命令真跑了 → 锁还掉了"
  else say 1 "正常路径:拿锁 → 命令真跑了 → 锁还掉了" "输出=「$OUT」 锁还在=$([ -d "$D" ] && echo 是 || echo 否)"; fi

  # ② 被包命令的退出码**原样传回**(不是永远 0)——
  #    这条是「打印 ❌ 和拦截是两件事」的同一族:包装器吃掉退出码,门禁就永远绿
  D="$(mktemp -d)/lock"
  LANXIU_LOCK_DIR="$D" "$ME" --who 自测2 sh -c "exit 7" >/dev/null 2>&1
  RC=$?
  if [ "$RC" = 7 ]; then say 0 "被包命令的退出码原样传回(7)"
  else say 1 "被包命令的退出码原样传回(7)" "拿到的是 $RC —— 包装器吃掉退出码等于门禁永远绿"; fi

  # ③ **陈锁要被抢**:这条是整个脚本的主轴 ——
  #    没有它,一次崩掉就让后面所有人静默卡死
  D="$(mktemp -d)/lock"
  mkdir -p "$D"
  DEAD=999999
  while kill -0 "$DEAD" 2>/dev/null; do DEAD=$((DEAD + 1)); done
  echo "$DEAD 崩掉的那一轮 2026-01-01 00:00:00" > "$D/owner"
  OUT="$(LANXIU_LOCK_DIR="$D" LANXIU_LOCK_CAP=5 "$ME" --who 自测3 echo 抢到了 2>&1)"
  if printf '%s' "$OUT" | grep -q "抢到了" && printf '%s' "$OUT" | grep -q "陈锁"; then
    say 0 "陈锁(原主进程已不在)被抢走,而且**大声说了出来**"
  else
    say 1 "陈锁(原主进程已不在)被抢走,而且大声说了出来" "$(printf '%s' "$OUT" | tr '\n' '|' | cut -c1-140)"
  fi

  # ④ **活锁不许抢**:原主还活着就只能等,等到封顶退 3,**而且不许删别人的锁**
  D="$(mktemp -d)/lock"
  mkdir -p "$D"
  # ⚠️ **拿自测脚本自己的 pid 当「活着的原主」,不另起一个后台 sleep。**
  # 第一版起了 `sleep 30 &` 再 kill 掉,而 bash 回收那个作业时会异步吐一行
  # 「Terminated: 15」混进自测输出里(`set +m` 压不住,那是回收时打的)。
  # **一份带噪声的检查输出,迟早让人学会跳过它。**
  # 而「一个活着的 pid」自测脚本自己就是,根本不用造。
  ALIVE=$$
  echo "$ALIVE 正在跑的那一轮 2026-01-01 00:00:00" > "$D/owner"
  LANXIU_LOCK_DIR="$D" LANXIU_LOCK_CAP=1 LANXIU_LOCK_SHOUT=1 "$ME" --who 自测4 echo 不该跑到 >/dev/null 2>&1
  RC=$?
  if [ "$RC" = 3 ] && [ -d "$D" ]; then say 0 "原主还活着:不抢、等到封顶退 3,而且没把别人的锁删掉"
  else say 1 "原主还活着:不抢、等到封顶退 3,而且没把别人的锁删掉" "退出码=$RC 锁还在=$([ -d "$D" ] && echo 是 || echo 否)"; fi
  rm -rf "$D"

  # ⑤ 被打断也要还锁(靠 trap,不靠「命令跑完下一行 rm」那个顺序)
  D="$(mktemp -d)/lock"
  LANXIU_LOCK_DIR="$D" "$ME" --who 自测5 sleep 20 >/dev/null 2>&1 &
  WRAP=$!
  I=0
  while [ ! -d "$D" ] && [ "$I" -lt 50 ]; do sleep 0.1; I=$((I + 1)); done
  kill -TERM "$WRAP" 2>/dev/null
  wait "$WRAP" 2>/dev/null
  I=0
  while [ -d "$D" ] && [ "$I" -lt 30 ]; do sleep 0.1; I=$((I + 1)); done
  if [ ! -d "$D" ]; then say 0 "被 TERM 打断,锁照样还掉(靠 trap,不靠下一行 rm)"
  else say 1 "被 TERM 打断,锁照样还掉" "锁还在 —— 下一个人会静默卡死"; fi

  echo "================================================================"
  if [ "$BAD" != 0 ]; then echo "❌ $BAD/5 条没过"; exit 1; fi
  echo "✅ 5 条全过"
  exit 0
fi

if [ $# -eq 0 ]; then
  echo "用法:$0 [--who <名字>] <命令> [参数...]   /   $0 --selftest" >&2
  exit 2
fi

HELD=0

# ⚠️ **用 trap 还锁,不靠「命令跑完下一行 rm」那个顺序。**
# Ctrl-C、被 kill、机器睡过去 —— 任何一种都会让那行 rm 跑不到,
# 而锁目录就**永远留着**,此后每个人都在等一把没人持有的锁。
# > 「别人正在跑」和「两小时前有人崩了、锁没还」,
# > **在那个一直转圈的终端里长得一模一样。**
#
# ⚠️ 而且**只还自己那把** —— 万一我这把被别人当陈锁偷走了(我卡住很久、
# 进程又恰好还在),那现在的锁是别人的,删了就等于把别人正在跑的那轮掀翻。
release() {
  [ "$HELD" = 1 ] || return 0
  if [ -f "$OWNER_FILE" ] && [ "$(awk '{print $1}' "$OWNER_FILE" 2>/dev/null)" = "$$" ]; then
    rm -rf "$LOCK_DIR"
  else
    echo "⚠️ 锁已经不是我的了(owner=$(cat "$OWNER_FILE" 2>/dev/null))—— **不删**,免得掀翻别人那一轮" >&2
  fi
}
trap release EXIT INT TERM

START=$(date +%s)
SHOUTED=0
while :; do
  # `mkdir` 是这里唯一的原子动作 —— 成了就是我的,**所有判断都以它为准**
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    HELD=1
    echo "$$ $WHO $(date '+%Y-%m-%d %H:%M:%S')" > "$OWNER_FILE"
    break
  fi

  OWNER="$(cat "$OWNER_FILE" 2>/dev/null)"
  OWNER_PID="$(printf '%s' "$OWNER" | awk '{print $1}')"

  # ── 陈锁:原主进程已经不在了,抢过来 ──────────────────────────────
  # ⚠️ **大声说出来。** 悄悄抢锁的话,下次真出问题时没人知道这台机器上
  # 曾经有人崩在锁里 —— 而「一切正常」和「天天有人崩、天天被自动抢」
  # 在输出上长得一模一样。
  if [ -n "$OWNER_PID" ] && ! kill -0 "$OWNER_PID" 2>/dev/null; then
    echo "⚠️ 抢了一把**陈锁**:原主 pid $OWNER_PID 已经不在了(owner: $OWNER)。" >&2
    echo "   说明上一轮是崩掉 / 被杀 / 机器睡过去的 —— **那一轮的结果不算数**," >&2
    echo "   如果它是门禁,别把它那次「跑到一半」的输出当成绿。" >&2
    rm -rf "$LOCK_DIR"
    continue          # 回去重新 mkdir —— 抢的权威仍然在那个原子动作上
  fi

  WAITED=$(( $(date +%s) - START ))
  if [ "$WAITED" -ge "$CAP_SEC" ]; then
    echo "❌ 等了 $((WAITED / 60)) 分钟还没拿到锁,**不再等** —— 持有者:$OWNER" >&2
    echo "   要么那一轮真的很久(全量门禁约 10 分钟,夜跑评测更久)," >&2
    echo "   要么它卡住了而进程还在。去问一声,或者手工 rm -rf $LOCK_DIR。" >&2
    exit 3
  fi
  # 等的时候**必须吵** —— 一把静默的锁迟早被人注释掉
  if [ "$SHOUTED" = 0 ] || [ $((WAITED % SHOUT_SEC)) -lt 20 ]; then
    echo "⏳ 等「$(printf '%s' "$OWNER" | cut -d' ' -f2-)」那一轮,已等 $((WAITED / 60)) 分 $((WAITED % 60)) 秒" >&2
    SHOUTED=1
  fi
  sleep 20
done

echo "🔒 拿到共享资源锁($WHO,pid $$)—— 跑:$*" >&2
"$@"
RC=$?
echo "🔓 还锁($WHO,被包的命令退出码 $RC)" >&2
exit $RC
