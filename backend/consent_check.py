#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同意分档与撤回 —— 口径在 `knowledge/12-成长与生命周期.md` 第七节。

## 这套检查为什么值得单独有

身体数据是敏感个人信息;不满十四周岁未成年人的个人信息**一律**是敏感个人信息。
依《个人信息保护法》要**单独同意**,未成年人还要**监护人同意**。

这些在库里都有了 —— `consent` 表、`scope` 分档、`_consent_ok()` 闸。
但 2026-09-18 查下来,其中两件事**只是存在,并没有在工作**:

### ① 撤回那条分支,从来没有被走过

    1169 条同意,`revoked_at` 非空的:**0 条**

`_consent_ok()` 里写着 `AND revoked_at IS NULL`。这个条件一直为真,
**所以它写对写错都一样** —— 把这半句删掉,所有检查照样绿,所有功能照样跑。

> **一条从没被走过的分支,和一条不存在的分支,效果一样。**

所以下面第 ④ 条**真的去撤一条**(在库的副本上),看对应的能力有没有当场关闭。
这是这套检查里唯一一条会**写**东西的,所以它只碰副本。

### ② `account.marketing_consent` 拦不住任何事

它只在两个地方出现:账户详情里显示、注销时置零。**没有一处拿它做过判断。**
一个长得像开关、却不控制任何东西的字段,**比没有这个字段更危险** ——
有人会以为它在生效。第 ⑤ 条把这件事钉成一条会红的检查,而不是一句注释。

## 最容易实现错的地方:让一档去顶另一档

「他都同意我们量体了,发条消息提醒复量总可以吧」—— 不可以。
量体是为了做这一单,触达是为了做下一单,**两个目的,两次同意**。

而在代码里这两种情况差的只是 `_consent_ok(w, scope)` 里那个参数。
**写错一个参数,和没有这条规则效果一样,而且从输出上看不出来** ——
所以第 ③ 条专门验它:拿一个只有身体数据同意的人,去问营销触达,必须被拒。
"""
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAIL = []
DONE = []

# 合法的同意用途。**手抄在这里,不从库里现算** ——
# 现算「库里出现过哪些 scope」再拿去校验库,等于没有白名单:
# 谁往表里写一个新 scope,它自动就合法了。
合法用途 = ("身体数据", "未成年人", "营销触达")


def ck(name, ok, n, msg=""):
    DONE.append(name)
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def main():
    print("同意分档与撤回 · 检查")
    print("=" * 80)
    主库 = os.path.join(HERE, "lanxiu.db")
    c = sqlite3.connect(主库)
    c.row_factory = sqlite3.Row

    同意 = [dict(r) for r in c.execute("SELECT * FROM consent")]

    # ── ① scope 必须在白名单里 ────────────────────────────────────
    野 = sorted({r["scope"] for r in 同意} - set(合法用途))
    ck("① 同意的用途在白名单里", not 野, len(同意),
       f"库里出现了没定义过的用途 {野} —— **一个没人定义过的用途,"
       f"没人知道它覆盖什么**" if 野 else
       f"白名单 {合法用途};**手抄不现算** —— 现算的话谁写进去的新用途自动就合法了")

    # ── ② 未成年着装人:有身体数据同意的,必须也有未成年人同意 ────
    import datetime
    今 = datetime.date.today()

    def 岁(b):
        try:
            return (今 - datetime.date.fromisoformat(b)).days // 365
        except Exception:
            return None

    有身体 = {r["wearer_id"] for r in 同意
             if r["scope"] == "身体数据" and not r["revoked_at"]}
    有未成年 = {r["wearer_id"] for r in 同意
               if r["scope"] == "未成年人" and not r["revoked_at"]}
    未成年着装人 = [dict(r) for r in c.execute(
        "SELECT id,name,birthday FROM wearer WHERE birthday IS NOT NULL")]
    未成年着装人 = [w for w in 未成年着装人
                 if (岁(w["birthday"]) if 岁(w["birthday"]) is not None else 99) < 14]
    缺 = [f"{w['id']}({w['name']})" for w in 未成年着装人
          if w["id"] in 有身体 and w["id"] not in 有未成年]
    ck("② 不满 14 岁且存了身体数据的,都有监护人同意", not 缺, len(未成年着装人),
       f"缺监护人同意的 {len(缺)} 人:{缺[:3]}" if 缺 else
       f"{len(未成年着装人)} 个未成年着装人,其中 {len([w for w in 未成年着装人 if w['id'] in 有身体])} 人存了身体数据")

    # ── ③ 一档不顶另一档 ─────────────────────────────────────────
    #    这是《个保法》「单独同意」的核心,也是最容易被实现错的地方。
    import api
    只有身体 = [w for w in 有身体 - 有未成年]
    if 只有身体:
        样 = 只有身体[0]
        顶了 = api._consent_ok(样, "营销触达")
        ck("③ 有身体数据同意 ≠ 有营销触达同意", not 顶了, len(只有身体),
           f"**{样} 只同意了身体数据,却被放行做营销触达** —— 一档顶了另一档"
           if 顶了 else
           "量体是为了做这一单,触达是为了做下一单 —— **两个目的,两次同意**;"
           "代码里这两种情况差的只是 `_consent_ok(w, scope)` 那个参数")
    else:
        ck("③ 有身体数据同意 ≠ 有营销触达同意", False, 0,
           "库里找不到「只有身体数据同意」的着装人,这条验不了")

    c.close()

    # ── ④ 撤回真的走得通(在副本上真撤一条) ──────────────────────
    #    **这是唯一一条会写东西的检查,所以只碰副本。**
    #    它存在的理由:`revoked_at IS NULL` 这个条件在真库里从来没被证伪过,
    #    1169 条同意,撤回过的 0 条 —— 那半句判断写对写错都一样。
    副本目录 = tempfile.mkdtemp(prefix="consent-")
    副本 = os.path.join(副本目录, "lanxiu.db")
    shutil.copy(主库, 副本)
    try:
        cc = sqlite3.connect(副本)
        行 = cc.execute("SELECT id,wearer_id FROM consent WHERE scope='身体数据'"
                        " AND revoked_at IS NULL LIMIT 1").fetchone()
        if not 行:
            ck("④ 撤回之后,对应的能力当场关闭", False, 0, "副本里找不到可撤的同意")
        else:
            cid, wid = 行
            api.DB = 副本
            撤前 = api._consent_ok(wid, "身体数据")
            cc.execute("UPDATE consent SET revoked_at=date('now') WHERE id=?", (cid,))
            cc.commit()
            撤后 = api._consent_ok(wid, "身体数据")
            api.DB = 主库
            ck("④ 撤回之后,对应的能力当场关闭", 撤前 and not 撤后, 1,
               f"撤前 {撤前} → 撤后 {撤后}" if not (撤前 and not 撤后) else
               "**真撤了一条才算验过** —— 这条分支在真库里 1169 条同意中被走过 0 次,"
               "而没被走过的分支,写对写错都一样")
        cc.close()
    finally:
        shutil.rmtree(副本目录, ignore_errors=True)
        api.DB = 主库

    # ── ⑤ 那个拦不住事的布尔字段 ─────────────────────────────────
    c = sqlite3.connect(主库)
    用到 = 0
    src = open(os.path.join(HERE, "api.py"), encoding="utf-8").read()
    # 只数**做判断**的地方:出现在 if / and / not 附近才算,单纯读出来展示不算
    for 行 in src.split("\n"):
        if "marketing_consent" in 行 and any(k in 行 for k in ("if ", " and ", "not ", "where ", "WHERE ")):
            用到 += 1
    有营销档 = sum(1 for r in 同意 if r["scope"] == "营销触达")
    ck("⑤ 营销触达以 consent 表为准,不靠那个布尔字段", 有营销档 > 0 or 用到 == 0,
       len(同意),
       f"`account.marketing_consent` 在 {用到} 处参与判断,而 consent 表里营销档 {有营销档} 条 —— "
       f"**两套并存会打架**"
       if not (有营销档 > 0 or 用到 == 0) else
       f"consent 表营销档 {有营销档} 条;`account.marketing_consent` 参与判断 {用到} 处"
       + ("(它只被显示和清零,**没拦过任何东西** —— "
          "一个长得像开关却不控制任何事的字段,比没有更危险,有人会以为它在生效)"
          if 用到 == 0 else ""))

    c.close()
    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print(f"✅ 同意分档与撤回 {len(DONE)} 条全过")
    return 0


咬合 = [
    ('往 consent 表里写一个没定义过的 scope', '① 同意的用途在白名单里'),
    ('删掉一个未成年着装人的监护人同意(身体数据那条留着)', '② 不满 14 岁且存了身体数据的'),
    ('把 _consent_ok 的 scope 参数忽略掉(任一档同意就全放行)', '③ 有身体数据同意 ≠ 有营销触达同意'),
    ('把 _consent_ok 里的 `revoked_at IS NULL` 删掉(撤回不再生效)', '④ 撤回之后'),
]

if __name__ == "__main__":
    sys.exit(main())
