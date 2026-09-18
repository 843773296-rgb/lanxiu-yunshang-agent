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
echo "⚠️  这会删掉 backend/lanxiu.db 重新生成。Ctrl-C 可中止,3 秒后开始。"
sleep 3

# ⚠️ **变量名用 ASCII。** 第一版写的是 `for 步 in ...`,bash 报
# `not a valid identifier`,于是**循环体一步都没跑** ——
# 而脚本照样打印了「✅ 重建完成」。
# `set -e` 没救它:那个错发生在循环语法解析,不是命令失败。
#
# **一个什么都没做的脚本,和一个做完了的脚本,输出长得一模一样。**
DONE=0
for STEP in "backend/seed.py" "tools/run_journey.py 42" "tools/simulate_sales.py" \
            "tools/order_mix.py" "backend/seed_fitting.py" "tools/make_todo.py"; do
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
if [ "$DONE" -ne 6 ]; then
  echo "❌ 只跑了 $DONE 步(应该 6 步)—— **循环没跑全,而上面看起来是顺利的**"
  exit 1
fi
printf "\n\033[32m✅ 重建完成(%s 步全跑到)\033[0m —— 现在跑 ./check.sh,**全绿才算真的重建得出来**。\n" "$DONE"
