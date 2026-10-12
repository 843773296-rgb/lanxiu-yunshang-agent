#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判差评能看哪些服务记录 —— **刻意不看的那几样,靠查返回的键名拦住,不靠「我没写那句 SQL」**。

    python3 backend/service_records_check.py

只读(走 `_c()` 的 `mode=ro` 连接),真库一行不碰。

## 这条检查在守什么

方案 V2.0 闸一要三样材料,第三样是「允许查看的服务记录」——
2026-10-12 之前**既没有工具,也没有定义「允许」的范围**。现在有了 `api.service_records`,
范围口径在 `knowledge/rating.服务记录范围()`。

最要紧的判据是**「刻意不看」那一半**:消费总额 / 会员等级 / 身体数据。
> 多给模型一个字段**不会让任何检查变红** —— 而「按客户价值差别对待」一旦被它学会,
> **在建议文本上看不出来**:同样一句「建议全额退款」,看过消费总额的那一次
> 和没看过的长得一模一样,而只有后者是业务要的。

所以攻击点放在**返回的键名**上(`api._挡住不该给的`),不放在「有没有写那句 SQL」上 ——
后者换个写法(`select *`、别名、子查询)就绕过去了。
**这个项目的凭据红线就是这么守住的**(`api._rows` 查返回的列名,与语句写法无关)。
同一个手法搬过来,而不是新发明一个。

⚠️ **明写的盲区:它拦得住「字段出现在返回里」,拦不住「模型自己去别的工具查」。**
`member_level` / `points_ledger` 这些工具照样给得出消费和等级 ——
那一层只有规矩 TK15 在管(**约定,不是结构**),已记进边界审计那一类。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import api
import rating as R

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("把 api._挡住不该给的 改成原样返回(不再按键名拦刻意排除的字段)",
     "返回里混进「刻意不看」的字段 → 当场抛"),
    ("让 service_records 两个参数都不给时随便挑一张单(替用户挑)",
     "两个参数都不给 → 报错(不替用户挑一张)"),
]


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


print("判差评能看哪些服务记录 · 只读")
c = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

一 = c.execute("""SELECT r.pkg_id, r.order_id, o.shop FROM rating r
                  LEFT JOIN ordr o ON o.id=r.order_id
                  WHERE r.star<=? AND o.shop IS NOT NULL LIMIT 1""", (R.差评线,)).fetchone()
店长 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=? LIMIT 1",
                 (一["shop"],)).fetchone() if 一 else None
售后 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='售后' AND status='启用' LIMIT 1").fetchone()
顾问 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' LIMIT 1").fetchone()

# ── ⓪ 样本量:空集合上什么都成立 ──────────────────────────────────────
ck("库里有差评样本可验(没有就不叫通过)", bool(一), "一条带门店的差评都查不到")
ck("三种身份都在职(售后 2026-10-11 才建)", bool(店长) and bool(售后) and bool(顾问),
   f"店长 {bool(店长)} / 售后 {bool(售后)} / 顾问 {bool(顾问)}")

if 一 and 店长 and 售后 and 顾问:
    with api.as_user(dict(店长)):
        r = api.service_records(pkg=一["pkg_id"])
    # ── ① 三类材料都在,而且是方案要的那三类 ───────────────────────────
    ck("三类材料都给了(交付与签收 / 返修与售后 / 这个客户历史上的差评)",
       all(k in r for k in ("交付与签收", "返修与售后", "这个客户历史上的差评")), str(list(r))[:120])
    ck("口径是从 knowledge 现取的,不是工具里手抄一份",
       r.get("口径", {}).get("能看") == [f"{名}:{理由}" for 名, 理由 in R.研判能看的服务记录],
       str(r.get("口径", {}).get("能看"))[:120])
    ck("返回里带着「业务还没拍过」那句话(报给人要带上)",
       "没拍过" in (r.get("口径", {}).get("要紧") or ""), str(r.get("口径", {}).get("要紧")))

    # ── ② 刻意不看的那几样,一个都不许在返回里 ─────────────────────────
    def 扒键(x, 出=None):
        出 = [] if 出 is None else 出
        if isinstance(x, dict):
            for k, v in x.items():
                出.append(str(k)); 扒键(v, 出)
        elif isinstance(x, (list, tuple)):
            for v in x: 扒键(v, 出)
        return 出
    键 = 扒键(r)
    命中 = [k for k in 键 for 禁 in R.不许出现的字段 if 禁 in k]
    ck(f"返回里一个「刻意不看」的字段都没有(扒了 {len(键)} 个键名)", not 命中, str(命中[:5]))
    ck("口径里把「刻意不看」逐条写出来了(让人看得见是刻意的,不是漏了)",
       len(r.get("口径", {}).get("刻意不看") or []) == len(R.研判刻意不看的),
       str(r.get("口径", {}).get("刻意不看"))[:100])
    ck("「消费总额 / 会员等级」那一条明写**刻意排除**",
       any("刻意排除" in x for x in (r.get("口径", {}).get("刻意不看") or [])))

    # ── ③ 那道闸是**按键名**拦的,不是靠「我没写那句 SQL」──────────────
    # ⚠️ 攻击点必须放在这儿:换个 SQL 写法就能把列带出来,而键名这一关换不掉。
    for 样, 说 in (({"这一单": {"消费总额": 9}}, "顶层字典里"),
                   ({"口径": {"明细": [{"会员等级": "金卡"}]}}, "列表里的字典里"),
                   ({"这一单": {"量体": {"胸围": 92}}}, "嵌套两层的身体数据")):
        try:
            api._挡住不该给的(样); 拦住 = False
        except AssertionError:
            拦住 = True
        ck(f"返回里混进「刻意不看」的字段 → 当场抛({说})", 拦住, str(样))
    try:
        api._挡住不该给的({"这一单": {"客户": "x", "门店": "SH001"}}); 放行 = True
    except AssertionError:
        放行 = False
    ck("干净的返回照过(不是无条件抛)", 放行)

    # ── ④ 隔离:和「A 顾问看不到 B 顾问的活」同一条口径 ────────────────
    with api.as_user(dict(顾问)):
        r顾 = api.service_records(pkg=一["pkg_id"])
    ck("顾问拿不到(判差评不是顾问的活)", "这一单" not in r顾 and r顾.get("条数") == 0, str(r顾)[:80])
    with api.as_user(dict(售后)):
        r售 = api.service_records(pkg=一["pkg_id"])
    ck("售后拿得到,而且跨门店(它门店字段是空的)", "这一单" in r售, str(r售)[:80])
    别店 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop<>? LIMIT 1",
                     (一["shop"],)).fetchone()
    if 别店:
        with api.as_user(dict(别店)):
            r别 = api.service_records(pkg=一["pkg_id"])
        ck("别的店的店长拿不到", "这一单" not in r别, str(r别)[:80])

    # ── ⑤ 空值要说清是哪一种空 ───────────────────────────────────────
    # ⚠️ 这儿原来还有一条 `ck("两个都不给 → 报错,不替用户挑", ...)`,
    # 写成了一串 `if/else` 最后**恒为真** —— 它永远绿、什么也没验,
    # 而正确的那条就在下面两行。删掉了。
    # > **一条恒为真的判据和一条真的验到了的,在绿勾上长得一模一样。**
    with api.as_user(dict(店长)):
        空1 = api.service_records()
        空2 = api.service_records(pkg="这个包裹不存在")
    # ⚠️ 判据要贴着**那句具体的拒绝**,不是「有没有 error」。
    # 咬合逼出来的:把那句 return 换成「随便挑一张单」之后,
    # 查不到那张单**照样返回 error** —— 于是「有 error 就算对」仍然绿。
    # > **一个「拒绝替你挑」的 error 和一个「挑了但查不到」的 error,
    # > 在「有没有 error」这个布尔上长得一模一样。**
    ck("两个参数都不给 → 报错(不替用户挑一张)",
       "不替你挑一张" in (空1.get("error") or ""), str(空1)[:90])
    ck("查不到时分清「没有这张单」和「没有服务记录」",
       "没有这个包裹" in (空2.get("error") or ""), str(空2)[:90])
    ck("判责那一项明说库里 0 行(「没录过」≠「没有责任」)",
       "没录过" in (r["返修与售后"].get("判责") or "") or
       any(x.get("判给谁") for x in r["返修与售后"]["返修"]),
       str(r["返修与售后"].get("判责"))[:80])

c.close()
print()
if bad:
    print(f"{Rd}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    for b in bad:
        print(f"    {Rd}❌{D} {b}")
    sys.exit(1)
print(f"{G}✅ 判差评的服务记录范围都对(验了 {n} 条){D}")
print(f"    {Y}⚠️ 盲区:它拦得住「字段出现在返回里」,拦不住「模型自己去 member_level 查」"
      f" —— 那一层只有规矩 TK15,**是约定不是结构**{D}")
