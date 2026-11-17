# -*- coding: utf-8 -*-
"""定制订单进「待生产」就生成工坊工单(执行手册 W43 ①,2026-11-17)。

## 为什么

工单(`workorder`)是工坊排产和「我的衣服做到哪了」的底:师傅手上有几件、哪道工序排到什么时候,
全从它算(knowledge/capacity.py)。可它**只在造数时生成过**:运行时没有任何写口建工单 ——
一张单方案审核通过、进了「待生产」,工坊那边什么都看不见,产能表上它不存在。
11-17 现查:生产中的定制单 354 张,有工单的 40 张;待生产 33 张,0 张有工单。

## 做法(不做排产决定)

- 触发点:订单状态机 `待审核 → 待生产`(server.transit 落状态那个事务里),只对「定制品订单」
- 每道工艺一条工单:订单行的定制品(`product_custom.kf_opts`,逗号分开的工艺名)→ 按 `craft.name` 对出工艺编码;
  对不上的工艺名不编造编码,工单上 craft 留空、note 写明
- **artisan 留空、status =「待派」、workdays / 日期留空** —— 派给谁、几个工日是排产的决定,不在这里替人定;
  排产那一步把它改成「在制」并填师傅和日期。产能计算(capacity._load)只数「在制」,待派的不占产能
- 同一张单、同一道工艺已有工单(任何状态)就不再建 —— 幂等;重复点状态也不会多出工单
- 工单号延续造数的样子 `WO + 数字`,取现有最大数字 + 1(同一事务里取,串行写)

## 不做的

- 不给「生产中」自动建:开裁时工单理应已经在;历史上没有的那 314 张走 `tools/backfill_workorders.py`(带 --干跑)
- 不删不改已有工单
"""
import sqlite3

待派 = "待派"


def 工艺编码表(c):
    """{工艺名: 编码},从 craft 表现读(KF 开头的是工艺;形制 XZ / 面料 MT 不在内)。"""
    return {r[1]: r[0] for r in c.execute("SELECT code, name FROM craft WHERE code LIKE 'KF%'")}


def 该建哪些(c, order_id):
    """→ [(工艺名, 编码或 None)],按订单行顺序去重;没有定制品行回 []。"""
    码表 = 工艺编码表(c)
    出, 见过 = [], set()
    for (kf,) in c.execute("""SELECT pc.kf_opts FROM ordr_item i JOIN product_custom pc ON pc.spu=i.spu
                              WHERE i.order_id=? ORDER BY i.id""", (order_id,)):
        for 名 in (kf or "").split(","):
            名 = 名.strip()
            if 名 and 名 not in 见过:
                见过.add(名); 出.append((名, 码表.get(名)))
    return 出


def _下一个号(c):
    r = c.execute("SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) FROM workorder WHERE id LIKE 'WO%'").fetchone()
    return int(r[0] or 8000) + 1


def 生成(c, order_id, 谁="系统", 备注="进待生产自动生成"):
    """在调用方的事务里建工单。→ 新建的工单号列表(已有的不重建)。表不在就回 [](不在这里建表)。"""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workorder'").fetchone():
        return []
    已有 = {r[0] for r in c.execute("SELECT craft FROM workorder WHERE ref=?", (order_id,))}
    已有名 = {r[0] for r in c.execute("SELECT note FROM workorder WHERE ref=? AND craft IS NULL", (order_id,))}
    新 = []
    for 名, 码 in 该建哪些(c, order_id):
        if 码 and 码 in 已有:
            continue
        note = f"{备注};工艺 {名}" + ("" if 码 else "(craft 表里没有这道工艺的编码,待人工对)")
        if not 码 and note in 已有名:
            continue
        号 = f"WO{_下一个号(c)}"
        c.execute("INSERT INTO workorder(id,artisan,craft,ref,workdays,start_date,due_date,status,note) "
                  "VALUES(?,NULL,?,?,NULL,NULL,NULL,?,?)", (号, 码, order_id, 待派, note))
        新.append(号)
    return 新


def 缺工单的(c, 状态们=("待生产", "生产中")):
    """→ [(订单号, 状态)]:定制品订单在这些状态里、一条工单都没有的。补录脚本和检查都用它。"""
    q = ",".join("?" * len(状态们))
    return [(r[0], r[1]) for r in c.execute(
        f"SELECT o.id, o.status FROM ordr o WHERE o.kind='定制品订单' AND o.status IN ({q}) "
        f"AND NOT EXISTS (SELECT 1 FROM workorder w WHERE w.ref=o.id) ORDER BY o.id", 状态们)]
