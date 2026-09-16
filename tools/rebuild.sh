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
#   simulate_sales.py 6 个月标品销量(库存预警要它才算得出可售天数)
#   seed_fitting.py  白坯试衣记录(要先有定制订单行)
#   make_todo.py     待办清单(从 intent/ 生成)
#
# ⚠️ **后面每一步都依赖前面那一步的产物**,跳一步不会报错,
# 只会让某几张表空着 —— 而空表和「有数据但都是 0」在库里长得一样。
#
# 用法: ./tools/rebuild.sh
set -e
cd "$(dirname "$0")/.."
echo "⚠️  这会删掉 backend/lanxiu.db 重新生成。Ctrl-C 可中止,3 秒后开始。"
sleep 3
for 步 in "backend/seed.py" "tools/run_journey.py 42" "tools/simulate_sales.py" \
          "backend/seed_fitting.py" "tools/make_todo.py"; do
  printf "\n\033[1m▸ %s\033[0m\n" "$步"
  python3 $步 > /tmp/rebuild-step.out 2>&1 || {
    echo "  ❌ 这一步失败了,后面的不跑 —— **跳过一步不会报错,只会让某几张表空着**"
    tail -15 /tmp/rebuild-step.out | sed 's/^/     /'
    exit 1
  }
  tail -2 /tmp/rebuild-step.out | sed 's/^/     /'
done
printf "\n\033[32m✅ 重建完成\033[0m —— 现在跑 ./check.sh,**全绿才算真的重建得出来**。\n"
