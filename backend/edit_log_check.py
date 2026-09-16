#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资料编辑日志的检查 —— **日志要说实话,而且要说得出「改了什么」。**

## 三条各防一种坏法

**① 日志不许撒谎。** 第一版算改动时,把表单没提交的字段也算了进去,
于是写出「吊牌价 20160 → 空」「主图 → 空」——**而那几个字段根本没被改动**
(`save_product` 的 UPDATE 只写 name / category / kind / base_price / template)。
**一条撒谎的日志比没有日志糟**:查账的人会照着它去追一个从没发生过的改动。
所以这条检查把「日志声称会记的字段」和「写入语句真的覆盖的字段」对起来。

**② 日志不许只有标题。** 设计稿那一列叫「日志标题」,可
「编辑商品资料」这五个字回答不了「谁把售价从 5600 改成 5800」。
**标题是给人扫的,明细才是给人查的** —— `changes` 为空就等于没记。

**③ 「没改动」和「没记录」不许长得一样。** 一次什么都没改的提交,
要留一条写着「(无改动)」的日志;悄悄不写的话,
它在日志页面上和「这次操作没留下痕迹」完全一样,而后者是 bug。
"""
import os, re, sys, json, sqlite3, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「日志覆盖的字段」清单里去掉 remark(UPDATE 还在写它,日志不再记它)',
     '日志记的字段 = UPDATE 真的写的字段'),
]

def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    src = os.path.join(HERE, "lanxiu.db")
    tmp = tempfile.mkdtemp()
    shutil.copy(src, os.path.join(tmp, "lanxiu.db"))
    import server
    server.DB = os.path.join(tmp, "lanxiu.db")
    server.ensure_editlog()

    # ① **日志记的字段 = 写入真的覆盖的字段。**
    #    两边都从源码取,不手抄 —— 手抄件不会自己告诉你它旧了。
    src_txt = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    m = re.search(r'UPDATE product SET ([^"]+?)WHERE spu=\?', src_txt, re.S)
    # ⚠️ 正则要认两种写法:`字段=?` 和 `字段=COALESCE(?,字段)`。
    # 后者是「没传就保持原值」,加进 UPDATE 之后这条检查当场红 ——
    # **而红的是检查跟不上,不是代码错**。
    # 这类「检查本身的覆盖面」问题最容易被当成误报关掉,所以写清楚。
    写的 = ((set(re.findall(r"(\w+)=\?", m.group(1)))
            | set(re.findall(r"(\w+)=COALESCE\(", m.group(1))))
           - {"updated"}) if m else set()
    m2 = re.search(r"写入覆盖的字段 = \(([^)]*)\)", src_txt)
    记的 = set(re.findall(r'"(\w+)"', m2.group(1))) if m2 else set()
    ck("日志记的字段 = UPDATE 真的写的字段", 写的 == 记的 and 写的,
       len(写的 | 记的),
       (f"UPDATE 写 {sorted(写的)} / 日志记 {sorted(记的)} —— "
        f"**日志会撒谎**" if 写的 != 记的 else
        "两边都从源码取,不手抄 —— **一条撒谎的日志比没有日志糟**"))

    # ② 改一次商品,必须留一条说得出改了什么的日志
    r = server.rows("SELECT spu,name,base_price,category,kind,template "
                    "FROM product WHERE kind='定制品' LIMIT 1")[0]
    c = sqlite3.connect(server.DB)
    n0 = c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0]
    server.save_product({**dict(r), "base_price": r["base_price"] + 100},
                        actor="魏欣新", role="总部运营")
    got = c.execute("SELECT title,changes FROM edit_log ORDER BY id DESC "
                    "LIMIT 1").fetchone()
    n1 = c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0]
    ch = json.loads(got[1]) if got else []
    有价 = any(x["字段"] == "销售价" and x["改后"] != x["改前"] for x in ch)
    ck("改一次商品要留一条说得出改了什么的日志", n1 == n0 + 1 and 有价, 1,
       f"标题「{got[0]}」,明细 {ch}" if not 有价 else
       "**标题是给人扫的,明细才是给人查的**")

    # ③ 一条改动都没有时,也要留痕,并且**明说是「无改动」**
    server.save_product({**dict(r), "base_price": r["base_price"] + 100},
                        actor="魏欣新", role="总部运营")
    got2 = c.execute("SELECT title,changes FROM edit_log ORDER BY id DESC "
                     "LIMIT 1").fetchone()
    n2 = c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0]
    ck("没改动也要留痕,而且要明说「无改动」",
       n2 == n1 + 1 and "无改动" in (got2[0] or ""), 1,
       f"标题是「{got2[0]}」" if "无改动" not in (got2[0] or "") else
       "**「没改动」和「没记录」在页面上长得一样,而后者是 bug**")

    # ④ 被拒绝的编辑不许进资料改动史(它什么都没改)——
    #    但 op_log 要记(那是「这次操作允不允许」那一层)。
    n3 = c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0]
    bad = server.save_product({**dict(r), "name": "店长想改的名字"},
                              actor="李明华", role="店长")
    n4 = c.execute("SELECT COUNT(*) FROM edit_log").fetchone()[0]
    ck("被拒绝的编辑不许进资料改动史", (not bad.get("ok")) and n4 == n3, 1,
       "被拒的操作什么都没改 —— **它属于 op_log(允不允许),不属于改动史**")
    c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 资料编辑日志 4 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
