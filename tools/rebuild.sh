#!/bin/bash
# 从零重建整个库 —— **一条命令,而且跑完 check.sh 要全绿。**
#
# ## 为什么要有它
#
# `HANDOFF.md` 曾经写着「库是可再生的……别去抢救某个特定的库文件」,
# 而 2026-09-16 实测:照那三步重建,`./check.sh` **红 26 项**。
#
# > 库能一直是绿的,**只因为没有人从零重建过它**。
#
# 而那句话会让人真的把库删掉。**一个「能跑」的库和一个「重建得出来」的库
# 长得一模一样** —— 直到有人换台机器,或者照着那句话动手。
#
# 这个脚本就是那句话的兑现:**步骤只有一处,不在文档里手抄一份。**
# `intent/db-not-regenerable.md` 的验收条件 ② 要求文档和它一致,
# 而「一致」的做法是**文档指向这个脚本**,不是抄一遍。
#
# ## 顺序不能换
#
#   seed.py          建表 + 主数据 + 种子订单 + 真值标注
#   run_journey.py   一条完整客户旅程(预约→量体→方案→下单→生产→交付)
#   grow_customers.py 客户补到 1000 个(账户 / 着装人 / 同意 / 量体都齐)—— **先有人,再放量**
#   simulate_sales.py 6 个月标品销量(库存预警要它才算得出可售天数)
#   order_mix.py     把其中一批改成定制单 + 重建售后/换货/维保 + 客户汇总按订单重算
#                    (业务 2026-09-18 的数据集规格,intent/order-aftersale-dataset.md)
#   seed_fitting.py  白坯试衣记录(要先有定制订单行)
#   make_todo.py     待办清单(从 intent/ 生成)
#
# ⚠️ **后面每一步都依赖前面那一步的产物**,跳一步不会报错,
# 只会让某几张表空着 —— 而空表和「有数据但都是 0」在库里长得一样。
#
# 用法: ./tools/rebuild.sh
set -e
cd "$(dirname "$0")/.."

# ── 互斥标记:**「库坏了」和「库正在被重建」长得一模一样** ─────────────
# 2026-09-18 一天里,另一个会话三次读到重建到一半的库:一次报「表从 67 掉到 64」、
# 一次 `no such table: fitting`、一次门禁加 48 条咬合一起红 —— 每次都先花几分钟
# 确认「是不是我改坏了」。这两种情况该触发的动作正好相反:前者要去查,后者只要等。
# 标记里写进程号:check.sh / bite_run.py 看见它**而且那个进程还活着**就停下说明原因;
# 进程已经不在(上次重建崩了留下的)就当没看见 —— 不能让一个残留文件永远卡住门禁。
# ── 两种用法,差别只在「有没有一个库要被删掉」 ──────────────────────────
# 2026-09-20 外部审阅点出:`start.sh` 首次启动只跑了 `seed.py` —— **15 步里的第 1 步**。
# 2026-09-21 在隔离副本里实测:这样起出来的库 **65 张表 / 12886 行**,
# 而实际在用的库是 **79 张表 / 198646 行**;`roster` / `fitting` / `call_transcript`
# 等 **14 张表根本不存在**,订单只有 46 张(实际 26587 张)。
#
# 而 `start.sh` 当时只看了一眼「库文件在不在」——
# **一个只跑了第 1 步的空壳库,和一个跑完 15 步的库,在那个 `[ -f ]` 眼里长得一模一样。**
# 它还不会崩:首页照常打开,直到有人点进排班才 `no such table`。
#
# 修法**不是**让 start.sh 来调这个会删库的脚本(审阅明确反对:不能让每次启动
# 都执行一个有删除行为的脚本),而是给它一个**自己会拒绝删东西**的入口:
#
#   ./tools/rebuild.sh                删库重建 —— 人主动敲,有 3 秒反悔时间
#   ./tools/rebuild.sh --fresh-only   只在**没有库**的时候建;库已经在了就直接退出,
#                                     所以它**不可能删掉任何人的数据**。start.sh 用这个。
#
# 注意拒绝的判断写在**这个脚本里面**,不是写在调用方 ——
# 调用方的守卫只护得住调用方,而谁都能直接敲这一行。
#
# 步骤表仍然只有下面那一份。**分叉的是入口,不是步骤** ——
# 两份步骤表会各自漂移,而「漂了」和「没漂」在跑完的库上又是长得一样的。
FRESH_ONLY=0
if [ "$1" = "--fresh-only" ]; then FRESH_ONLY=1; fi

MARK=backend/.rebuilding
if [ -f "$MARK" ] && kill -0 "$(cat "$MARK")" 2>/dev/null; then
  echo "❌ 另一个重建正在跑(pid $(cat "$MARK")),两个同时写同一个库只会得到一个半成品"
  exit 1
fi
echo $$ > "$MARK"
trap 'rm -f "$MARK"' EXIT
if [ "$FRESH_ONLY" = 1 ]; then
  if [ -f backend/lanxiu.db ]; then
    echo "❌ --fresh-only 只管「从无到有建库」,而 backend/lanxiu.db 已经在了 —— 它不会去动它。"
    echo "   真要重建,请直接敲 ./tools/rebuild.sh(它会先说清楚要删什么,并留 3 秒反悔)。"
    exit 1
  fi
  echo "📦 首次建库:下面 15 步**全跑完**才算建好,少一步都会让某几张表空着。"
else
  echo "⚠️  这会删掉 backend/lanxiu.db 重新生成。Ctrl-C 可中止,3 秒后开始。"
  sleep 3
fi

# ⚠️ **变量名用 ASCII。** 第一版写的是 `for 步 in ...`,bash 报
# `not a valid identifier`,于是**循环体一步都没跑** ——
# 而脚本照样打印了「✅ 重建完成」。
# `set -e` 没救它:那个错发生在循环语法解析,不是命令失败。
#
# **一个什么都没做的脚本,和一个做完了的脚本,输出长得一模一样。**
DONE=0
# ⚠️ **场合标签(backfill_scene)排在造旅程之前**(2026-09-22 挪的):
# 白坯试衣必试的三类里「婚服」按商品的「婚礼婚服」场合标签认,而旅程会把订单推到开裁 ——
# 标签还没挂的话婚服判不出、闸判「判不了」、旅程卡在待生产,**时间没挪回过去,留下一批未来日期**
# (数据规范 C4 / A15 当场红)。场合标签只依赖商品和知识库,放前面不缺任何输入。
for STEP in "backend/seed.py" "tools/backfill_scene.py" "tools/run_journey.py 42" "tools/grow_customers.py" "tools/simulate_sales.py" \
            "tools/order_mix.py" "tools/backfill_order_measure.py" "backend/seed_fitting.py" "tools/backfill_color.py" \
            "tools/backfill_transcript.py" "tools/backfill_roster.py" "tools/backfill_credit.py" "tools/ensure_tables.py" "tools/backfill_fixtures.py" "tools/backfill_biz_fields.py" "tools/backfill_link.py" "tools/backfill_wattr.py" \
            "tools/make_todo.py"; do
  printf "\n\033[1m▸ %s\033[0m\n" "$STEP"
  python3 $STEP > /tmp/rebuild-step.out 2>&1 || {
    echo "  ❌ 这一步失败了,后面的不跑 —— **跳过一步不会报错,只会让某几张表空着**"
    tail -15 /tmp/rebuild-step.out | sed 's/^/     /'
    exit 1
  }
  tail -2 /tmp/rebuild-step.out | sed 's/^/     /'
  DONE=$((DONE + 1))
done

# **自己证明干了活。** 不加这一条的话,上面那个 bug 会一直以「✅」收场。
if [ "$DONE" -ne 18 ]; then
  echo "❌ 只跑了 $DONE 步(应该 18 步)—— **循环没跑全,而上面看起来是顺利的**"
  exit 1
fi
printf "\n\033[32m✅ 重建完成(%s 步全跑到)\033[0m —— 现在跑 ./check.sh,**全绿才算真的重建得出来**。\n" "$DONE"
