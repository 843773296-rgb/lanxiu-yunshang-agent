#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工厂回传:补历史、再让模拟工厂发今天这一批 —— 重建的一步。

    python3 tools/seed_factory_feed.py

业务 2026-09-22:「已生产」「发货」是工厂回传的数据,走供应链系统,不给门店推进入口。
订单状态机上有一道闸(FACTORY_GATE):定制单「生产中→已生产→待发货→已发货」只认收下了的回传。

## 两件事

① **补历史**:库里已经过了生产的定制单(造数据直插的),按订单自己记的完工 / 发货时间,
  把工厂当年发过的回传直接记成「收下」—— 不补的话,这些单在新规下全都「没有回传撑着」。
  已经有回传的单(造旅程那批走的是真路径)不补。

② **今天这一批**:模拟工厂(fakedata/factory_sim.py)给生产中的单发回传,**混进故意的毛病**
  (重复、换号重发、乱序、没单号、未来时间、倒挂、查无此单、已取消),
  **逐条走接收写口**(backend/factory_inbox.收),拿结果和模拟工厂自己记的预期对 —— 对不上当场红。
  「该回没回」的那几张单不发消息,对的是该催清单。

每条的毛病、预期、实际记在 factory_outbox(**模拟工厂那一侧的表**,相当于答案 ——
和 truth 表同一条规矩,不经任何工具露出去)。
"""
import os, sys, sqlite3, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "fakedata"), ROOT]
import factory_inbox as fi, factory_sim as sim
from seed import TODAY

DB = os.path.join(ROOT, "backend", "lanxiu.db")
OUTBOX = """
CREATE TABLE IF NOT EXISTS factory_outbox(
  -- 模拟工厂那一侧:它发了什么、故意混了什么毛病、预期该怎么处理、我们实际怎么处理的。
  -- **相当于答案**,和 truth 表同一条规矩:不经任何 API / 工具露出去。
  seq INTEGER PRIMARY KEY, order_id TEXT, msg_id TEXT, event TEXT,
  flaw TEXT, expect TEXT, got TEXT, final TEXT);
"""


def main():
    c = sqlite3.connect(DB)
    fi.ensure(c); c.executescript(OUTBOX); c.commit()
    if c.execute("SELECT COUNT(*) FROM factory_outbox").fetchone()[0]:
        print("  工厂回传已经造过,不重复造"); return
    # ① 补历史
    有 = {r[0] for r in c.execute("SELECT DISTINCT order_id FROM factory_msg")}
    n = 0
    for m in sim.历史回传(c):
        if m["订单号"] in 有:
            continue
        c.execute("""INSERT INTO factory_msg(msg_id,order_id,event,at,tracking_no,promise_date,factory,received_at,
                     result,reason) VALUES(?,?,?,?,?,?,?,?,'收下','历史回传(接回传之前的单,按订单自己记的时间补)')""",
                  (m["消息号"], m["订单号"], m["事件"], m["时间"], m.get("物流单号"), m.get("承诺完工日"),
                   m.get("工厂"), m["时间"]))
        n += 1
    c.commit(); c.close()
    print(f"  补历史回传 {n} 条")

    # ② 今天这一批
    c = sqlite3.connect(DB)
    批 = sim.今日回传(c, TODAY)
    c.close()
    错, 计 = [], collections.Counter()
    for i, (m, 毛病, 预期) in enumerate(批):
        if 预期 == "该催":
            got = None
        else:
            got = fi.收(m, TODAY)["结论"]
            if got != 预期.split("→")[0]:
                错.append((毛病 or "正常", m.get("消息号"), 预期, got))
        计[毛病 or "正常"] += 1
        with sqlite3.connect(DB) as c:
            c.execute("INSERT INTO factory_outbox(seq,order_id,msg_id,event,flaw,expect,got) VALUES(?,?,?,?,?,?,?)",
                      (i, m.get("订单号"), m.get("消息号"), m.get("事件"), 毛病, 预期, got))
    # 最终结果(暂存的后来放没放行)按收件箱里现在的样子对
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE factory_outbox SET final=(SELECT result FROM factory_msg f WHERE f.msg_id=factory_outbox.msg_id)")
        for r in c.execute("SELECT flaw, msg_id, expect, final FROM factory_outbox WHERE expect LIKE '%→%'"):
            if r[3] != r[2].split("→")[-1]:
                错.append((r[0], r[1], r[2], f"最终 {r[3]}"))
    催 = {x["订单"] for x in fi.该催清单(TODAY)}
    预催 = {m["订单号"] for m, _, e in 批 if e == "该催"}
    if 催 != 预催:
        错.append(("该催清单", "", f"{len(预催)} 张", f"{len(催)} 张(多 {len(催 - 预催)}、少 {len(预催 - 催)})"))
    for k in ("重复发", "换号重发", "乱序:质检先到", "发出没单号", "未来时间", "时间倒挂", "查无此单", "已取消的单", "别家报完工", "车间在制却报完工"):
        if not 计[k]:
            错.append((k, "", "至少 1 条", "0 条 —— 这一支没样本,等于没测"))
    with sqlite3.connect(DB) as c:
        结 = collections.Counter(r[0] for r in c.execute(
            "SELECT result FROM factory_msg WHERE msg_id NOT LIKE 'H%'"))
        推 = collections.Counter(r[0] for r in c.execute(
            "SELECT status FROM ordr WHERE id IN (SELECT order_id FROM factory_msg WHERE msg_id LIKE 'T%' "
            "AND result='收下' AND event!='接单')"))
    print(f"  今天这一批 {len(批)} 条(其中该回没回 {len(预催)} 张不发):"
          + "、".join(f"{k} {v}" for k, v in 计.items()))
    print(f"  收件箱:" + "、".join(f"{k} {v}" for k, v in 结.items())
          + f";被回传推动的单现在:" + "、".join(f"{k} {v}" for k, v in 推.items()))
    if 错:
        print(f"  ❌ {len(错)} 条和模拟工厂记的预期对不上:")
        for x in 错[:10]: print(f"     {x}")
        sys.exit(1)
    print(f"  ✅ 每条都和预期对得上;该催 {len(催)} 张")


if __name__ == "__main__":
    main()
