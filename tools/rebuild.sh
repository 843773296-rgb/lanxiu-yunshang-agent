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
MARK=backend/.rebuilding
if [ -f "$MARK" ] && kill -0 "$(cat "$MARK")" 2>/dev/null; then
  echo "❌ 另一个重建正在跑(pid $(cat "$MARK")),两个同时写同一个库只会得到一个半成品"
  exit 1
fi
echo $$ > "$MARK"
trap 'rm -f "$MARK"' EXIT
echo "⚠️  这会删掉 backend/lanxiu.db 重新生成。Ctrl-C 可中止,3 秒后开始。"
sleep 3

# ⚠️ **变量名用 ASCII。** 第一版写的是 `for 步 in ...`,bash 报
# `not a valid identifier`,于是**循环体一步都没跑** ——
# 而脚本照样打印了「✅ 重建完成」。
# `set -e` 没救它:那个错发生在循环语法解析,不是命令失败。
#
# **一个什么都没做的脚本,和一个做完了的脚本,输出长得一模一样。**
DONE=0
for STEP in "backend/seed.py" "tools/run_journey.py 42" "tools/grow_customers.py" "tools/simulate_sales.py" \
            "tools/order_mix.py" "backend/seed_fitting.py" "tools/backfill_scene.py" "tools/backfill_color.py" \
            "tools/backfill_transcript.py" "tools/backfill_roster.py" "tools/backfill_credit.py" "tools/ensure_tables.py" "tools/backfill_fixtures.py" "tools/backfill_biz_fields.py" \
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
if [ "$DONE" -ne 15 ]; then
  echo "❌ 只跑了 $DONE 步(应该 15 步)—— **循环没跑全,而上面看起来是顺利的**"
  exit 1
fi
printf "\n\033[32m✅ 重建完成(%s 步全跑到)\033[0m —— 现在跑 ./check.sh,**全绿才算真的重建得出来**。\n" "$DONE"
