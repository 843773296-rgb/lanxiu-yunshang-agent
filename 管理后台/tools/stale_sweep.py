#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清扫卡住的记录 —— **两档**:等外部的只报警,做不完的推到状态机允许的终态。

    python3 tools/stale_sweep.py                # 只报(默认)
    python3 tools/stale_sweep.py --做            # 真的改
    python3 tools/stale_sweep.py --门槛小时 48
    python3 tools/stale_sweep.py --项目 project_demo_a

## 业务 2026-10-07 拍的两件事

    超时之后做什么   **分两档**:等外部确认的只报警,做不完的自动推终态
    阈值             **72 小时**(依据见 `runtime/卡住判定.py`,一半实测一半猜的)

## ⚠️ 判定不在这儿 —— 在 `runtime/卡住判定.py`

这个脚本只做三件事:取数、调判定、(可选)落库。
一条判定写在脚本里的工具,下一个要用同一个判定的人会再抄一遍 ——
而两份判定迟早分叉(这个项目为「两份实现」栽过好几次)。

## ⚠️ 终态走 `contract/states.能不能走()`,不直接 UPDATE

> 一次「按状态机改的」和一次「直接 UPDATE 改的」,
> **在那条记录的新状态上长得一模一样** —— 而后者绕过了契约,
> 并且下一个人改了状态机也拦不住它。

实测这条校验真的管事:`queued` **到不了 `failed`**
(状态机只给它 running/cancelled/expired),所以 queued 超时走 `expired`。

## ⚠️ 「待上传」不在这儿

它在 `tools/abandon_stale_uploads.py`(门槛 24 小时,等**人**传文件)。
门槛不一样是有道理的,见 `卡住判定` 模块头。**不在这儿写第二套。**

## ⚠️ 默认只报

照抄 `abandon_stale_uploads.py`:一个默认就改库的清扫脚本,
第一次跑它的人没法先看看它要动什么。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))

from sqlalchemy import text                      # noqa: E402
import states as ST                              # noqa: E402
import 卡住判定 as SJ                             # noqa: E402
from db import 连接, 事务                          # noqa: E402

G, Y, R, D = "\033[32m", "\033[33m", "\033[31m", "\033[0m"

# 每一类:(表, 种类, 状态条件, 额外要取的列)
清单 = (
    ("evaluations", "评测", "status='排队中'", ""),
    ("deployments", "部署", "status='部署请求中'", ""),
    ("training_jobs", "训练", "status='取消请求中'", ""),
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true", help="真的改(默认只报)")
    ap.add_argument("--门槛小时", type=float, default=SJ.门槛小时)
    ap.add_argument("--项目", default=None)
    # ⚠️ **判据在脚本里,不在 Makefile 里。** 第一版我在 Makefile 写
    # `stale_sweep.py | tee … | tail -6` 再 grep 输出取数 —— 那是**第十二次
    # 管道**,而且更脆:脚本自己炸了的话 grep 找不到那一行,
    # `$${n:-0}` 就变成 0 → **不红**。
    # > 一次「可推终态 0 条」和一次「脚本炸了所以没输出那一行」,
    # > **在那个 n:-0 上长得一模一样。**
    # 钉在这儿之后 Makefile 只取退出码,不解析输出。
    ap.add_argument("--钉住", type=int, default=None,
                    help="可推终态超过这个数就退 1(门禁用,现状钉 0)")
    a = ap.parse_args()

    print(f"\n\033[1m▸ 清扫卡住的记录 · 门槛 {a.门槛小时} 小时 · "
          f"{'**真改**' if a.做 else '只报(加 --做 才改)'}\033[0m")
    print("  两档:等外部确认的**只报警**(系统推它违反契约)· "
          "做不完的推到状态机允许的终态")

    项目条件 = " and project_id=:proj" if a.项目 else ""
    参 = {"proj": a.项目} if a.项目 else {}
    报警, 要改, 判不了的 = [], [], []

    with 连接() as c:
        现在 = c.execute(text("select now()")).scalar()
        for 表, 种类, 条件, _ in 清单:
            for r in c.execute(text(
                    f"select id, status, created_at, project_id from {表} "
                    f"where {条件}{项目条件}"), 参).mappings():
                try:
                    档, 为 = SJ.判(种类=种类, 状态=r["status"],
                                 创建时间=r["created_at"], 现在=现在,
                                 门槛=a.门槛小时)
                except SJ.判不了 as e:
                    判不了的.append((表, r["id"], str(e)))
                    continue
                if 档 == SJ.只报警:
                    报警.append((表, 种类, r["id"], r["status"], 为))
                elif 档 != SJ.还没超:
                    要改.append((表, 种类, r["id"], r["status"], 档, 为,
                               r["project_id"]))

        # execution_runs 要多取两列 —— 它们是「做不完」和「可能能恢复」的分界
        for r in c.execute(text(
                f"select id, status, created_at, project_id, "
                f"       (checkpoint_seq is not null and checkpoint_seq>0) 有检查点, "
                f"       (definition_ref is not null) 有定义引用 "
                f"  from execution_runs "
                f" where status in ('queued','running'){项目条件}"), 参).mappings():
            try:
                档, 为 = SJ.判(种类="运行", 状态=r["status"],
                             创建时间=r["created_at"], 现在=现在,
                             有检查点=r["有检查点"], 有定义引用=r["有定义引用"],
                             门槛=a.门槛小时)
            except SJ.判不了 as e:
                判不了的.append(("execution_runs", r["id"], str(e)))
                continue
            if 档 == SJ.只报警:
                报警.append(("execution_runs", "运行", r["id"], r["status"], 为))
            elif 档 != SJ.还没超:
                要改.append(("execution_runs", "运行", r["id"], r["status"], 档,
                           为, r["project_id"]))

    # ── ① 只报警那一档 ───────────────────────────────────────────────
    print(f"\n  {Y}⏸ 只报警 {len(报警)} 条{D} —— **不动它们**")
    if 报警:
        按类 = {}
        for 表, 种类, i, 态, 为 in 报警:
            按类.setdefault((表, 态), []).append(i)
        for (表, 态), ids in sorted(按类.items()):
            print(f"     {表}/{态}: {len(ids)} 条  例:{ids[0]}")
        print(f"     ⚠️ 其中「等外部确认」的那几类**系统自己推就是撒谎**,"
              f"而且契约明令禁止(「取消请求中 → 已取消」只该由后台确认时走)。"
              f"\n        要处置得由人或外部系统来 —— 这一档**永远不会被 --做 碰到**。")

    # ── ② 可改那一档 ────────────────────────────────────────────────
    print(f"\n  {'🔧' if a.做 else '📋'} 可推终态 {len(要改)} 条")
    if not 要改:
        print("     (没有)")
    改了 = 0
    拦下 = []
    for 表, 种类, i, 从, 档, 为, proj in 要改:
        到 = "failed" if 档 == SJ.可标failed else "expired"
        # ⚠️ **走状态机校验,不直接 UPDATE。**
        # `能不能走` 返回 bool,而且**认不出的状态当场抛**(不返回 False)——
        # 它的理由值得抄在这儿:「返回 False 的话,拼错一个状态名就等于
        # 『这条路不通』,而那是另一回事」。所以这里把 ValueError 单独捞出来,
        # **不把「状态名拼错了」和「这条路不通」混成同一个结果**。
        if 表 != "execution_runs":
            行, 说 = False, "这一类没有状态机登记,不推"
        else:
            try:
                行 = ST.能不能走("execution_run", 从, 到)
                说 = "" if 行 else f"状态机不给 {从} → {到} 这条路"
            except ValueError as e:
                行, 说 = False, f"状态名认不出:{e}"
        if not 行:
            拦下.append((表, i, 从, 到, 说))
            continue
        if not a.做:
            改了 += 1
            continue
        with 事务() as c2:
            n = c2.execute(text(f"""
                update execution_runs
                   set status=:到, completion_reason=:因, ended_at=now(),
                       updated_at=now(), revision=revision+1
                 where project_id=:p and id=:i and status=:从"""),
                {"到": 到, "从": 从, "p": proj, "i": i,
                 "因": ("STALE_NO_CHECKPOINT" if 档 == SJ.可标failed
                        else "STALE_NO_DEFINITION")}).rowcount
            改了 += n
    if 要改:
        c失败 = sum(1 for x in 要改 if x[4] == SJ.可标failed)
        c过期 = sum(1 for x in 要改 if x[4] == SJ.可标expired)
        print(f"     running 没检查点 → **failed**: {c失败} 条 "
              f"(completion_reason=STALE_NO_CHECKPOINT)")
        print(f"     queued 没定义引用 → **expired**: {c过期} 条 "
              f"(completion_reason=STALE_NO_DEFINITION)")
        print(f"     ⚠️ expired 这一档**库里原来一条记录都没到过** —— "
              f"状态机给 queued 准备了它,而从没有人去执行")
        print(f"     {'已改' if a.做 else '将改'} {改了} 条")
    if 拦下:
        print(f"\n  {R}⚠️ 状态机拦下 {len(拦下)} 条{D} —— **这是对的,不要绕过**")
        for 表, i, 从, 到, 说 in 拦下[:6]:
            print(f"     {表} {i}: {从} → {到} 不许走 —— {说}")

    if 判不了的:
        print(f"\n  {R}❌ 判不了 {len(判不了的)} 条 —— 这**不是「没问题」**{D}")
        for 表, i, 说 in 判不了的[:6]:
            print(f"     {表} {i}: {说[:110]}")
        return 1

    print(f"\n  {G}✅ 扫完{D}:只报警 {len(报警)} · "
          f"{'已推' if a.做 else '可推'} {改了} · 状态机拦下 {len(拦下)}")
    print("     ⚠️ 「待上传」不在这儿 —— 跑 tools/abandon_stale_uploads.py"
          "(门槛 24 小时,等**人**传文件)")
    if a.钉住 is not None and not a.做 and 改了 > a.钉住:
        print(f"\n  {R}❌ 可推终态 {改了} 条,超过钉住的 {a.钉住} 条{D}")
        print(f"     说明又攒了一批残留 —— 跑 "
              f"`python3 tools/stale_sweep.py --做` 把它们推到终态。")
        print(f"     ⚠️ 「只报警」那 {len(报警)} 条**不计入** —— "
              f"它们等的是外部确认,是正常状态,不是残留。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
