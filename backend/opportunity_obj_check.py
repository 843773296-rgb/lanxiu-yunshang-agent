#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商机对象 · 检查 —— intent `opportunity-and-call-notes` 判据 ①⑤⑥⑦ 里不调模型的那几条。

`opportunity_check.py` 量的是「判断器认商机认得准不准」;这里查**认出来之后**:

    ① 沟通发现的商机指得回触发它的那次通话(通话真的在库里)
    ② 商机 ↔ 方案互相指得回(和「转过单的方案必须指得回订单」同一个形状)
    ③ 方案草稿必须挂一件具体服饰;商机可以没有(业务否掉了「商机 = 草稿方案」)
    ④ 两种终态分得开:已关闭写了为什么、不带等什么;搁置写了等什么(结构化);**已关闭不许被唤醒**
    ⑤ 每条诉求的原话真的在那通电话的逐字稿里 —— 指不回原话的诉求和瞎猜没区别
    样本量:商机少于 10 条时报「没扫到东西」,不报通过(10 是拍脑袋的,只为不让空表冒充通过)
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

咬合 = [
    ("把一条商机触发它的通话号改成库里没有的", "沟通发现的商机都指得回触发它的那次通话"),
    ("把方案那头指回商机的字段清掉", "商机和方案互相指得回"),
    ("把「已关闭」和「搁置等供给」合并成一个「已丢单」", "状态都在口径里"),
    ("把一条诉求的原话换成逐字稿里没有的一句", "每条诉求的原话都在那通电话的逐字稿里"),
    ("让口径允许已关闭的商机被唤醒", "已关闭的商机不许被唤醒"),
]
样本下限 = 10
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    import oppo_obj as K
    print("商机对象 · 检查")
    print("=" * 84)
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    有表 = c.execute("SELECT 1 FROM sqlite_master WHERE name='opportunity'").fetchone()
    os_ = [dict(r) for r in c.execute("SELECT * FROM opportunity")] if 有表 else []
    if len(os_) < 样本下限:
        print(f"  ⚠️ **没扫到东西**:商机只有 {len(os_)} 条(下限 {样本下限})—— 下面几条不算通过")
        FAIL.append(f"商机样本不足 {样本下限} 条")

    通话 = {r[0]: r[1] for r in c.execute(
        "SELECT a.id, t.text FROM call_audio a JOIN call_transcript t ON t.audio_id=a.id")}
    沟 = [o for o in os_ if o["source"] == "沟通发现"]
    断 = [o["id"] for o in 沟 if o["call_id"] not in 通话]
    ck("沟通发现的商机都指得回触发它的那次通话", not 断, len(沟), f"共 {len(断)} 条指不回:{断[:3]}" if 断 else "")

    转 = [o for o in os_ if o["scheme_id"]]
    方 = {r["id"]: r["opportunity_id"] for r in c.execute("SELECT id, opportunity_id FROM scheme")}
    正 = [o["id"] for o in 转 if 方.get(o["scheme_id"]) != o["id"]]
    反 = [s for s, oid in 方.items() if oid and not any(o["id"] == oid and o["scheme_id"] == s for o in os_)]
    ck("商机和方案互相指得回", not 正 and not 反, len(转) + sum(1 for v in 方.values() if v),
       f"商机→方案断 {正[:3]};方案→商机断 {反[:3]}" if (正 or 反) else f"{len(转)} 对")
    错转 = [o["id"] for o in os_ if (o["status"] == "已转方案") != bool(o["scheme_id"])]
    ck("只有「已转方案」的商机挂着方案,而且它一定挂着", not 错转, len(os_), f"共 {len(错转)} 条:{错转[:3]}" if 错转 else "")

    草 = [dict(r) for r in c.execute("SELECT id, xz FROM scheme WHERE status='草稿'")]
    空草 = [s["id"] for s in 草 if not s["xz"]]
    ck("方案草稿都至少挂了一件具体服饰(形制)", not 空草, len(草), f"共 {len(空草)} 条没挂:{空草[:3]}" if 空草 else "")
    无服 = [o["id"] for o in os_ if not c.execute(
        "SELECT 1 FROM opportunity_need WHERE opp_id=? AND dim='形制'", (o["id"],)).fetchone()]
    print(f"  ℹ 没有任何服饰诉求的商机 {len(无服)} 条 —— **这是合法的**(商机可以只是「这个客户可能要买东西」)")

    野 = [f"{o['id']}:{o['status']}" for o in os_ if o["status"] not in K.状态]
    ck("状态都在口径里(已关闭和搁置等供给是两个,不许合并成一个)", not 野, len(os_), f"共 {len(野)} 条:{野[:3]}" if 野 else "")
    关 = [o for o in os_ if o["status"] == "已关闭"]
    搁 = [o for o in os_ if o["status"] == "搁置等供给"]
    坏关 = [o["id"] for o in 关 if not o["close_reason"] or o["wait_for"]]
    ck("已关闭的写了为什么,而且不带「等什么」", not 坏关, len(关), f"共 {len(坏关)} 条:{坏关[:3]}" if 坏关 else "")
    坏搁 = [o["id"] for o in 搁 if not K.搁置理由合格吗(json.loads(o["wait_for"] or "null"))[0]]
    ck("搁置等供给的都写清等什么(结构化,能拿去和上新匹配)", not 坏搁, len(搁), f"共 {len(坏搁)} 条:{坏搁[:3]}" if 坏搁 else "")
    ck("已关闭的商机不许被唤醒", not K.能转吗("已关闭", "跟进中")[0] and K.能转吗("搁置等供给", "跟进中")[0], 2)
    # 已关闭可以从「待确认」直接关(顾问不认这条商机),所以不要求它有点头时间;其余走出待确认的都要有
    未点头 = [o["id"] for o in os_ if o["status"] not in ("待确认", "已关闭") and not o["confirmed_at"]]
    ck("走出「待确认」的(除了直接关掉的)都有顾问点头的时间", not 未点头, len(os_), f"共 {len(未点头)} 条:{未点头[:3]}" if 未点头 else "")

    诉 = [dict(r) for r in c.execute("SELECT opp_id, dim, val, quote, call_id FROM opportunity_need")]
    假 = [f"{x['opp_id']}「{x['quote'][:12]}」" for x in 诉 if not x["quote"] or x["quote"] not in 通话.get(x["call_id"], "")]
    ck("每条诉求的原话都在那通电话的逐字稿里", not 假, len(诉), f"共 {len(假)} 条:{假[:3]}" if 假 else "")
    野维 = [f"{x['opp_id']}:{x['dim']}" for x in 诉 if x["dim"] not in K.诉求维度]
    ck("诉求的维度都是可匹配的维度", not 野维, len(诉), f"共 {len(野维)} 条:{野维[:3]}" if 野维 else "")

    print()
    if FAIL:
        print(f"\033[31m❌ 商机对象 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 商机对象全部符合预期\033[0m({len(os_)} 条商机,{len(诉)} 条诉求)")


if __name__ == "__main__":
    main()
