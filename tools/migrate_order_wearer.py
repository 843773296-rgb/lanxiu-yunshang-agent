#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给订单加「着装人」,并**只回填能确定的那些**。

## 为什么非加这个字段不可

`12-成长与生命周期.md` 写着「超期的量体记录**不是参考值,是无效值** ——
下单前必须拦下」,`knowledge/growth.py` 也实现了复量周期。
但订单表上没有着装人 —— 一个客户名下可以有本人加两个孩子,
**这一单是给谁做的,库里没记**。

于是那条规则不是「没人执行」,是**执行不了**。
判据写在文档里、库里没有字段承载它,那条规则就永远跑不到。

## 回填只填无歧义的

    名下只有 1 个在用着装人        73 单  → **确定地填**
    多个候选但只有 1 个量过体       5 单  → **也能定**(见下)
    两个人都量过体                 4 单  → **留空**,单独报出来
    查不到着装人                  10 单  → 留空

第二档**不是猜**,是一条能说出理由的判据:定制不能凭空裁,
家里只有一个人在下单前量过体,这单就只能是给他做的。
和「挑一个候选顶上」的区别在于**有没有排他的证据**。

**猜一个着装人的代价是不对称的**:猜对了没人知道,
猜错了这一单会拿着另一个人的尺寸去裁剪,而报表上完全正常。
那 9 单里有孩子也有大人(「黄青梧 / 黄先生 / 黄砚舟」),
挑哪一个都是编。**留空是诚实,填上才是造假。**

留空的那些,下单校验会报「判不了」——**判不了不等于可以**。

默认 dry-run,`--go` 才真改。`seed.py` 同步改好,老库新库两条路都对。
"""
import os, sqlite3, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "lanxiu.db")


def main():
    go = "--go" in sys.argv
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    cols = [x[1] for x in c.execute("PRAGMA table_info(ordr)")]
    有字段 = "wearer_id" in cols
    print(f"{'真跑' if go else 'dry-run(加 --go 才真改)'}")
    print(f"  ordr.wearer_id 字段:{'已有' if 有字段 else '**没有,要加**'}")

    确定, 歧义, 无人 = [], [], []
    for o in c.execute("SELECT id,customer_id FROM ordr"):
        ws = list(c.execute("SELECT id,name FROM wearer WHERE customer_id=? "
                            "AND status='在用'", (o["customer_id"],)))
        if not ws: 无人.append(o["id"])
        elif len(ws) == 1: 确定.append((o["id"], ws[0]["id"], ws[0]["name"]))
        else: 歧义.append((o["id"], o["customer_id"], [w["name"] for w in ws]))

    print(f"  能确定地回填 {len(确定)} 单")
    print(f"  **名下多个着装人,留空** {len(歧义)} 单 —— 挑哪一个都是编")
    for oid, cid, names in 歧义[:4]:
        print(f"     {oid[-6:]} {cid} 候选:{names}")
    print(f"  查不到着装人,留空 {len(无人)} 单")

    # ── 第二轮:**唯一有量体记录的候选** ────────────────────────
    # 这**不是猜**,是一条能说出理由的判据:
    # 定制不能凭空裁,家里只有一个人在下单前量过体,这单就只能是给他做的。
    #
    # 和「挑一个候选顶上」的区别在于**有没有排他的证据**:
    # 「黄青梧 / 黄先生 / 黄砚舟」里挑一个是编;
    # 「只有黄砚舟量过体,另外两个一条都没有」是推出来的。
    #
    # ⚠️ 仍然有两个人都量过的(4 单)—— 那些还是留空。
    # **判据能定几条就定几条,定不了的一条都不许凑。**
    唯一有量体, 仍歧义 = [], []
    for oid, cid, names in 歧义:
        o = c.execute("SELECT created FROM ordr WHERE id=?", (oid,)).fetchone()
        有量的 = []
        for w in c.execute("SELECT id,name FROM wearer WHERE customer_id=? AND status='在用'",
                           (cid,)):
            k = c.execute("SELECT COUNT(*) k FROM measure_rec WHERE wearer_id=? "
                          "AND measured_at<=?", (w["id"], o["created"])).fetchone()["k"]
            if k: 有量的.append((w["id"], w["name"]))
        if len(有量的) == 1: 唯一有量体.append((oid, 有量的[0][0], 有量的[0][1]))
        else: 仍歧义.append((oid, cid, [n for _, n in 有量的] or names))
    print(f"  其中**唯一有量体记录**的 {len(唯一有量体)} 单 → 能定(不是猜:"
          f"定制不能凭空裁,家里只有一个人量过体)")
    for oid, wid, nm in 唯一有量体[:5]:
        print(f"     {oid[-6:]} → {wid} {nm}")
    print(f"  两个人都量过的 {len(仍歧义)} 单 → **还是留空**")
    for oid, cid, names in 仍歧义[:4]:
        print(f"     {oid[-6:]} {cid} 都量过:{names}")

    if not go:
        return 0
    if not 有字段:
        c.execute("ALTER TABLE ordr ADD COLUMN wearer_id TEXT")
        print("  已加字段 ordr.wearer_id")
    n = 0
    for oid, wid, _ in 确定 + 唯一有量体:
        cur = c.execute("SELECT wearer_id FROM ordr WHERE id=?", (oid,)).fetchone()
        if cur and cur["wearer_id"]: continue        # 已经填过的不动
        c.execute("UPDATE ordr SET wearer_id=? WHERE id=?", (wid, oid))
        n += 1
    c.commit(); c.close()
    print(f"  回填 {n} 单;{len(仍歧义) + len(无人)} 单留空("
          f"下单校验会报「**判不了**」—— 判不了不等于可以)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
