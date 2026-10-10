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
#   backfill_rating.py    铺签收后的顾客评价
#   daily_fresh.py        「每日上新」那一步 —— 平移之后造一小批新记录 + 推进存量
#   seed_customer_tasks.py 造**客户族**的派单任务。交接里原来写「客户类还没造」——
#                         **不对**:客户族早有 79 条(预约到店 38 · 上门沟通 31 · 电话回电 7
#                         · 商机提醒 3),真缺口是「**接待任务 0 条**」这一整个类型。
#                         ⚠️ 它不只是补样本:`tasks.finish_task` 里那段**自动收尾**
#                         (「接待类任务做完了,把那条还开着的预约一并收尾」)写着「接待任务」,
#                         而库里是 0 条 —— **那一支从来没有数据走过**,
#                         `isolation_check` 那条判据也一直只在上门沟通上跑。
#                         造完会有 3 条预约被真的自动收尾。
#                         必须排在 shift_world 之后(要读 world_today)、
#                         backfill_opportunity 之后(商机提醒是它回捞出来的)。
#   seed_dispatch.py      造「派出去的任务」—— `schedule` 17467 行里有 17374 行是
#                         `type='到店'` 的**接待记录**(end_ts 全是 NULL),真正的派单
#                         任务原来只有 93 条,撑不起「这周派了多少/谁手上压着/有没有
#                         逾期」。走写口正门(api.as_user + assign_task),所以权限照常
#                         生效、op_log 里有「谁干的」;回滚按台账不按 id 前缀(正门不
#                         让指定 id)。排在最后 —— 它只依赖 staff
#   seed_churned.py       造「真正流失过的老客户」—— 流失预警的 GONE / IMPROVING /
#                         「曾经是但现在没了」三支长期没有样本。前两支的根因是
#                         **库里最老的订单只有 364 天前,而「流失」要 365 天 —— 差一天**;
#                         第三支的根因不同:库里**没有一个人的 12 个月金额是往下走的**
#                         (末值低于自己峰值的 0 个)。排在造历史之前(历史要先有人有单)
#   teen_self_consent.py  给 14—18 周岁补「本人签」的身体数据同意(业务 10-10 晚:本人为准)。
#                         排在 shift_world / daily_fresh 之后:年龄按世界今天算,新着装人也要先造出来
#   lifecycle_history_seed.py  造「档位历史」(回算 12/9/6/3/0 五个时点)——
#                         ⚠️ **这一步 2026-10-09 才进配方**,而这张表是流失预警的训练样本。
#                         在那之前配方里**一步都没有造它**,所以 CI 的库里它永远是空的,
#                         依赖它的判据在 CI 上一个字都没验。
#   lifecycle_refresh.py  按世界今天重算档位并对齐历史
#   ⚠️ **后两步接进配方不只是为了建表。** 2026-10-09 并行会话查出一类问题:
#      `lifecycle_history` 在配方里一步都没有造 —— 于是**CI 的库里它永远是空的**,
#      依赖它的判据在 CI 上一个字都没验,而绿勾看起来完全正常。
#      > 一个「这个功能的取数都对」的绿勾,和一个「CI 上这个功能的数据根本不存在」的,
#      > **长得一模一样。**
#      所以每日那两步要在**从零重建**里也真跑一遍(它们都幂等,重复跑不翻倍)。
#                         ⚠️⚠️ **必须排在 shift_world 之后。** 2026-09-27 CI 连红两次:
#                         `seed.py` 重建之后世界回到**建库基准日 2026-08-31**,
#                         而 shift_world 才把它挪到真实的今天(+27 天)。
#                         排在平移之前的话,造数看到的「今天」是 08-31 ——
#                         它按「8 月」给月度目标,随后平移把那批评价**挪成了 9 月**,
#                         **而目标是按 8 月给的**。业务拍的「三个月上升」当场被抹掉大半
#                         (设计升 0.30,实现只有 0.10~0.18)。
#                         这是「签收月 vs 评价月」那个错的**第三个位置**:
#                         前两次在一个文件里,这一次藏在**步骤顺序**里。
#                         机械防线见 `backend/rating_check.py` 的
#                         「造数之后世界没有再被平移过」那一条。
#   clamp_future_done.py  把「有已发生的事落在今天之后」的单**整条时间线**挪回来
#                         ⚠️ 2026-09-27 扩了判据:原来只认「完工日在未来」,
#                         而「**签收**在未来」是另一种未来(19 个包裹),它一张也选不到
#                    ⚠️ **必须排在 shift_world 之前。** 它原来只由 shift_world 事后调用,
#                    而并行会话 2026-09-26 新加的「平移前置闸」挡在平移之前 ——
#                    于是从零重建会卡住:修它的工具排在拦它的闸后面。
#                    (种子里那 7 张单的完工日来自一个写死的 2026-09-15 上限,
#                     而锚点是 08-31;直接改那个上限会破「量体→投产 ≥20 天」那条 assert,
#                     真正晚的是那几条量体记录 —— 所以这一轮靠事后压,不动造数。)
#   level_customer_orders.py  削峰:把「一个人买了 162 次」摊给同店少单客户
#                    (业务 2026-09-26 定。**排在最后、shift_world 之前** ——
#                     它要读客户建档日和订单下单日比大小,得等所有造单的步骤都跑完)
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
  echo "📦 首次建库:下面 37 步**全跑完**才算建好,少一步都会让某几张表空着。"
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
            "tools/order_mix.py" "tools/backfill_order_measure.py" "backend/seed_fitting.py" "backend/seed_pickup.py" "backend/seed_repair.py" "tools/backfill_color.py" \
            "tools/backfill_transcript.py" "tools/backfill_terms.py" "tools/backfill_opportunity.py" "tools/backfill_roster.py" "tools/backfill_credit.py" "tools/ensure_tables.py" "tools/backfill_fixtures.py" "tools/backfill_biz_fields.py" "tools/backfill_link.py" "tools/backfill_wattr.py" \
            "tools/seed_factory_feed.py" "backend/seed_pickup.py --铺到包裹" "tools/seed_pending_orders.py" \
            "tools/clamp_future_done.py" "tools/level_customer_orders.py" \
            "tools/shift_world.py" "tools/backfill_rating.py" \
            "tools/daily_fresh.py --做" "tools/teen_self_consent.py --做" "tools/seed_churned.py --做" \
            "tools/lifecycle_history_seed.py --做" \
            "tools/lifecycle_refresh.py --做" "tools/seed_dispatch.py --做" \
            "tools/seed_customer_tasks.py --做" "tools/seed_new_products.py --做" \
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
# ⚠️ **加步骤要改这个数。** 2026-10-09 加了 daily_fresh / lifecycle_refresh 两步,
# 忘了改 —— `backend/firstrun_check.py` 当场逮到「步骤表 31 步,自校验却写着 29 步」。
# 这个数存在的理由正是「循环没跑全,而上面看起来是顺利的」,所以它自己不能过期。
if [ "$DONE" -ne 37 ]; then
  echo "❌ 只跑了 $DONE 步(应该 37 步)—— **循环没跑全,而上面看起来是顺利的**"
  exit 1
fi
printf "\n\033[32m✅ 重建完成(%s 步全跑到)\033[0m —— 现在跑 ./check.sh,**全绿才算真的重建得出来**。\n" "$DONE"
