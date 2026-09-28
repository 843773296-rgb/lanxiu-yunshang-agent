#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等队列排空,**并且报出等的是谁的活**。

    python3 tools/drain_queue.py            # 最多等 180 秒
    python3 tools/drain_queue.py --秒 60
    python3 tools/drain_queue.py --看        # 只报,不等

## 为什么要它

`make progress` 的那份报告靠端到端**真打过哪些路由**来算「验过」。
而端到端里 Worker 那一组是「提一个活 → 等它跑完 → 看阶段和用量」,
等的时候用的是一个**固定窗口**。

⚠️ 队列是**共享**的:上一轮 `make progress` 被 `pkill` 打断时留下的活、
别人跑过的实验、失败重试的,全排在前面。于是「我这个活多久跑完」
取决于**历史积压有多长** ——
**昨天绿、今天红,而代码一个字没改。**

实测撞到过:队列里堆着 39 个「排队中」,于是端到端里 Worker 那一组挂,
而挂掉的后果不是报告红,是**报告少算 5 条「验过」而它自己看起来完全正常**
(那次是 `| tail -2` 把退出码吞了)。

所以「就绪」不只是「服务和 Worker 起来了」,还得包括**队列已经空了** ——
不然量的是别人的排队时间。

## ⚠️ 失败的活不算积压,但要报出来

`失败` 是终态,它不会再被谁处理,所以不影响等待。
但**不报就等于没有** —— 13 个失败的活静静躺着,和 0 个失败在「排队中=0」
这个数字上长得一模一样。
"""
import argparse, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text
from db import 连接

项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")


def 数一下():
    """⚠️ **必须排掉已归档的。**

    第一版没排,于是它报「排队中 39 条」,而那 39 条**全是已归档的** ——
    测试自己的清理机制就是「归档 + 标记 cancel_requested」,
    而每一条真实代码路径(`jobs/lease.py` 领活、界面列表)都带 `archived_at is null`。

    ⚠️ 我照着那个假数字**编了一个自洽的解释**:「『请求取消』不是终态,
    而没有任何东西会把它推进终态」—— 那个解释不但说得通,还**正好呼应**
    我当天在写的运行控制主题(「请求」不是「已经」),
    **所以我没去查是谁写的**,直接当成产品缺陷写进了交接。

    > CLAUDE.md 第 7.8 条:**不符合预期的数会被查,符合预期的数会被信。**
    > 这是它的变体 —— 正好印证你当前想法的现象,会被直接收下。

    归档的条数**单独报**,不混进积压:两者下一步完全不同
    (一个是等它跑完,一个是压根不用管)。
    """
    with 连接() as c:
        rs = dict(c.execute(text("""select status, count(*) from jobs
                                  where project_id=:p and archived_at is null
                                  group by status"""), {"p": 项目}).all())
        归 = c.execute(text("""select count(*) from jobs
                             where project_id=:p and archived_at is not null"""),
                       {"p": 项目}).scalar()
    rs["_已归档"] = 归
    return rs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--秒", type=int, default=180)
    ap.add_argument("--看", action="store_true")
    a = ap.parse_args()

    起 = 数一下()
    堆 = 起.get("排队中", 0) + 起.get("执行中", 0)
    print(f"  队列(**只数没归档的**):排队中 {起.get('排队中', 0)}"
          f" · 执行中 {起.get('执行中', 0)}"
          f" · 已完成 {起.get('已完成', 0)} · **失败 {起.get('失败', 0)}**")
    if 起.get("_已归档"):
        print(f"     另有 {起['_已归档']} 条**已归档**(多是端到端跑完自己清的)——"
              f"不算积压,也不用管")
    if 起.get("失败", 0):
        print(f"     ⚠️ {起['失败']} 个失败的活是终态,不影响等待 —— "
              f"**但不报就等于没有**:它们和 0 个失败在「排队中=0」上长得一样")
    if a.看 or 堆 == 0:
        if 堆 and a.看:
            print(f"     还有 {堆} 个没跑完(--看 只报不等)")
        return 0

    print(f"  等 {堆} 个活跑完(最多 {a.秒} 秒)", end="", flush=True)
    到 = time.time() + a.秒
    上次 = 堆
    while time.time() < 到:
        n = 数一下()
        剩 = n.get("排队中", 0) + n.get("执行中", 0)
        if 剩 == 0:
            print(f" 空了(跑完 {堆} 个)")
            return 0
        if 剩 != 上次:
            print(f" {剩}", end="", flush=True); 上次 = 剩
        else:
            print(".", end="", flush=True)
        time.sleep(2)
    n = 数一下()
    剩 = n.get("排队中", 0) + n.get("执行中", 0)
    print(f"\n  ❌ {a.秒} 秒之后还剩 {剩} 个 —— Worker 是不是没在收活?")
    print(f"     看 /tmp/aimc-worker.log;**别把这条改成「等不到就算了」** —— "
          f"那等于把不确定性搬进报告里")
    return 1


if __name__ == "__main__":
    sys.exit(main())
