#!/usr/bin/env python3
"""语料生成器 —— **由系统真实状态组合出顾问会问的话**,不是我逐句想题。

## 为什么不手写

前七套评测的每一道题**都是我想到的题**,所以它们是我出题思路的镜子:
我想不到的情况,永远不会出现在题里。这一版报告已经栽过两次
(出了道模型能靠反问通过的题、设了条和自己论点矛盾的轴)。

这里换个来源:**题目的内容全部来自库里的真实状态** ——
这个客户的备注是什么、订单什么状态、量体过没过期、
有没有孩子、有没有远程量体、有没有在办售后。
长尾来自**数据自己的交叉**:某个客户同时「香云纱敏感 + 远程量体 +
孩子量体过期」,这种组合我不会主动去出。

## ⚠️ 它仍然是合成数据

组合是数据给的,**句式还是我写的**;而且库本身也是种子生成的。
它替代不了真实客户语料 —— 它只是**不再是我出题思路的镜子**。

真数据到手后,直接 `python3 agent/wild_run.py 真实语料.txt`。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backend")]
import api


def build(limit=24):
    """六类轮转取,不是取满一类再取下一类。

    第一版直接 `out[:24]`,结果 24 条**全被第一类(客户备注)占满** ——
    而备注只有 5 种在循环,拿到的是 24 条近似重复。
    **「够多」不等于「够杂」**,和「均匀不等于覆盖」是同一句话。
    """
    groups = [[] for _ in range(6)]
    out = groups[0]
    # ① 带备注的客户 —— 备注是当 CRM 记录写的,不是当题写的
    for c in api._rows("""SELECT id, name, remark FROM customer
                          WHERE remark IS NOT NULL AND remark <> '' ORDER BY id"""):
        out.append(f"{c['id']} {c['name']},档案备注写着「{c['remark']}」。"
                   f"她今天来问能做什么,我该怎么接?")

    out = groups[1]
    # ② 量体过期的着装人 —— 过期与否是数据算出来的,不是我指定的
    for w in api._rows("SELECT id, name, customer_id FROM wearer WHERE relation IN ('子','女')"):
        d = api.get_wearer(wearer_id=w["id"])["着装人"][0]
        e = d.get("量体是否过期") or {}
        if e.get("过期"):
            out.append(f"{w['customer_id']} 的孩子{w['name']}要做一件新的,"
                       f"我直接按库里的尺寸下单行吗?")

    out = groups[2]
    # ③ 在办售后 —— 判责现场
    for m in api._rows("""SELECT id, customer_id, item, issue FROM maintain
                          WHERE status IN ('待确认','待处理') ORDER BY id LIMIT 4"""):
        out.append(f"客户拿{m['item']}来说「{m['issue']}」,工单 {m['id']},这个算谁的?")

    out = groups[3]
    # ④ 有远程量体记录的客户 —— 尺寸争议的高危人群
    for r in api._rows("""SELECT DISTINCT customer_id FROM measure_rec
                          WHERE method='远程' LIMIT 3"""):
        out.append(f"{r['customer_id']} 是远程量的体,她说衣服穿着不合身,我怎么答?")

    out = groups[4]
    # ⑤ 卡在某个状态的定制单 —— 客户最常问的那句
    for o in api._rows("""SELECT id, customer_id, status FROM ordr
                          WHERE kind='定制品订单' AND status IN ('待生产','已生产','待发货')
                          ORDER BY id LIMIT 4"""):
        out.append(f"客户问 {o['id']} 这单到哪一步了,还要多久?")

    out = groups[5]
    # ⑥ 相容矩阵里判「不可」的真实组合 —— 客户提了做不了的要求
    for r in api._rows("""SELECT k.name kn, m.name mn FROM craft_combo cc
                          JOIN craft k ON k.code=cc.craft JOIN craft m ON m.code=cc.material
                          WHERE cc.verdict='不可' LIMIT 3"""):
        out.append(f"客户想要{r['mn']}上做{r['kn']},能做吗?怎么跟她说?")

    # 同一类里内容重复的先去掉(客户备注只有 5 种,别拿 20 个客户去凑)
    # 写成普通循环而不是一行推导 —— 上一版把 seen 和用它的推导式塞进同一条赋值,
    # 右边先求值,那时 seen 还不存在。**一行写完不等于写对。**
    seen = set()
    dedup = []
    for g in groups:
        keep = []
        for q in g:
            key = q.split("「")[-1]
            if key in seen: continue
            seen.add(key); keep.append(q)
        dedup.append(keep)
    groups = dedup
    # 轮转取:一类一条,转着拿,直到取满
    mixed, i = [], 0
    while len(mixed) < limit and any(g[i:] for g in groups):
        for g in groups:
            if i < len(g) and len(mixed) < limit: mixed.append(g[i])
        i += 1
    return mixed


def selftest():
    """**「够多」不等于「够杂」** —— 这条自测就是为了钉住这一点。

    第一版直接 `out[:24]`,24 条全被第一类占满,而那类只有 5 种备注在循环:
    拿到的是 24 条近似重复。数量达标、多样性为零,**而且看起来一切正常**。
    """
    bad = []
    def ck(n, c, e=""):
        print(f"  {'✅' if c else '❌'} {n}{('  ' + e) if e else ''}")
        if not c: bad.append(n)

    print("语料生成器 · 多样性自测\n" + "=" * 72)
    qs = build(20)
    ck("凑得够 20 条", len(qs) >= 18, f"实际 {len(qs)}")
    # 按句尾问法粗分类:每类不该超过总数的一半
    import collections
    kind = collections.Counter(q[-14:] for q in qs)
    top = kind.most_common(1)[0]
    ck("没有哪一类占到一半以上", top[1] <= len(qs) // 2,
       f"最多的一类 {top[1]}/{len(qs)}")
    ck("至少覆盖 5 种问法", len(kind) >= 5, f"实际 {len(kind)} 种")
    ck("没有完全重复的句子", len(set(qs)) == len(qs))
    # 每类内部也不该是同一句话换个编号
    core = collections.Counter(q.split("「")[-1] for q in qs if "「" in q)
    ck("同一段引文不重复出现", all(v == 1 for v in core.values()),
       f"重复的:{[k for k, v in core.items() if v > 1][:2]}")
    print("\n" + "=" * 72)
    if bad:
        print(f"❌ {len(bad)} 条没过:" + " / ".join(bad)); return 1
    print(f"✅ {len(qs)} 条语料,{len(kind)} 种问法,无重复")
    print("  数量达标、多样性为零的语料**看起来一切正常** —— 所以要专门查。")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv: sys.exit(selftest())
    qs = build(int(sys.argv[1]) if len(sys.argv) > 1 else 24)
    out = os.path.join(HERE, "wild-corpus.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# 由系统真实状态组合而成(agent/wild_corpus.py 生成)\n"
                "# ⚠️ 仍是合成数据:组合是数据给的,句式是人写的 —— 替代不了真实客户语料\n")
        for q in qs: f.write(q + "\n")
    print(f"{len(qs)} 条 → {out}\n")
    for q in qs: print("  " + q)
