#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨存储端到端真跑 —— **真 Redis**,不是文件式适配器。**不进 check.sh**(要人手起服务)。

## 为什么非要真跑

`multistore.py` 原来只有文件式适配器,诚实清单里写着「没接真服务,接了也只是看起来支持」。
这份脚本就是去掉那句话的依据:**同一套抽象,换成真 Redis,一行调用方代码都不用改。**

跑之前起一个 Redis:

    brew install redis && redis-server --daemonize yes --port 6379
    python3 fakedata/multistore_e2e.py [127.0.0.1:6379]

## 这一跑验的是三件事

    ① 真驱动接得进来          —— 抽象没把「文件」的特性写死进去
    ② 少写一处会被对账抓到     —— 这层能力的全部价值
    ③ 回滚能跨存储删干净       —— 而且 Redis Stream **能真删**,
                                文件式和 Kafka 只能打作废标记 —— 抽象要容得下这个差别
"""
import json, os, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schema as S, multistore as MS


def main():
    地址 = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:6379"
    host, _, port = 地址.partition(":")
    port = int(port or 6379)
    try:
        探 = MS._RESP(host, port)
        探.cmd("PING")
        探.close()
    except Exception as e:
        raise SystemExit(f"连不上 Redis({地址}):{e}\n"
                         f"先起一个:redis-server --daemonize yes --port {port}")
    print(f"【真 Redis】{地址} 连上了")

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "main.db")
    c = sqlite3.connect(db)
    c.execute("create table ordr(id text primary key, sku text, qty int)")
    c.commit(); c.close()
    conn = S.connect(db)

    前缀 = "fakedata:e2e:"
    店 = {"关系库": MS.关系库(conn, "ordr", "id"),
          "KV": MS.RedisKV(host, port, 前缀=前缀),
          "事件流": MS.Redis流(host, port, 流名=前缀 + "events"),
          "对象": MS.对象(os.path.join(tmp, "obj"))}

    def 投影(事):
        return {"关系库": [(事["id"], {"id": 事["id"], "sku": 事["sku"], "qty": 事["qty"]})],
                "KV": [(f"stock:{事['sku']}", 100 - 事["qty"])],
                "事件流": [(f"order.created:{事['id']}", {"订单": 事["id"]})],
                "对象": [(f"{事['sku']}.jpg", b"fake-image")]}

    事实们 = [{"id": f"O{i}", "sku": f"S{i}", "qty": i} for i in (1, 2, 3)]
    凭 = [MS.落(店, 事, 投影) for 事 in 事实们]
    print(f"\n【落】{len(事实们)} 个事实 × 4 个存储")
    print(f"  Redis 里现在有:KV {店['KV'].读('stock:S1')} · "
          f"事件流 {'有' if 店['事件流'].读('order.created:O1') else '没有'}")

    缺 = MS.对账(店, 事实们, 投影, log=print)
    if 缺:
        print("  ❌ 刚落完就对不上,先查落的那一步"); return 1

    print("\n【故意少写一处】把 KV 里 stock:S2 删掉")
    店["KV"].删("stock:S2")
    缺2 = MS.对账(店, 事实们, 投影, log=print)
    对 = len(缺2) == 1 and 缺2[0]["存储"] == "KV"
    print(f"  {'✅' if 对 else '❌'} 对账{'抓到了' if 对 else '没抓到'}:{缺2}")

    print("\n【回滚】")
    for z in 凭:
        MS.回滚(店, z)
    剩库 = sqlite3.connect(db).execute("select count(*) from ordr").fetchone()[0]
    剩KV = 店["KV"].读("stock:S1")
    剩流 = 店["事件流"].读("order.created:O1")
    剩物 = 店["对象"].读("S1.jpg")
    净 = (剩库 == 0 and 剩KV is None and 剩流 is None and 剩物 is None)
    print(f"  关系库 {剩库} 行 · KV {剩KV} · 事件流 {剩流} · 对象 {剩物}")
    print(f"  {'✅ 四个存储都删干净了' if 净 else '❌ 有残留'}")
    print("  ⚠️ 注意:**Redis Stream 能 XDEL 真删,而文件式事件流和 Kafka 只能打作废标记** ——"
          "抽象只要求「清干净」,不规定怎么清,所以两种驱动都接得进来。")

    # 收尾:把这一批的键清掉,别在别人的 Redis 里留垃圾
    r = MS._RESP(host, port)
    r.cmd("DEL", 前缀 + "events")
    r.close()

    ok = 对 and 净 and not 缺
    print(f"\n{'✅ 跨存储端到端跑通(真 Redis)' if ok else '❌ 有没过的环节'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
