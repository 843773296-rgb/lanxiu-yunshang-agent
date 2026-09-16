#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行级保护 —— **有些行碰不得,而它们和普通数据长得一模一样。**

## 为什么要这一层

工具原来的保护是「**整个库都不许灌**」(`guard.PROTECTED`),粒度太粗:
真正碰不得的往往是**某几行**,而那几行混在几百行正常数据里。

账单是现成的,而且不是假想:

    C10017 是个**普通客户**,不是夹具。但某条售后判责用例的真值
    依赖它「量体记录不全」这个事实 —— 有人好心给它补了 5 项,**判责结论当场翻了**。

    E-A4-01 的 `last_interact` 是生命周期真值的依据;
    给它加一笔订单、改一下最近互动,那条评测第二天给出的答案就变了。

**两次都不会有任何东西变红。** 规则没被改坏,只是再也测不到东西了 ——
和「反例夹具被补全」是同一种破法:**静默变成永远通过**。

## 保护的是两件不同的事

    ① 不许**引用**   造出来的行不许把外键指向这些行(指过去 = 把它们卷进新数据的语义里)
    ② 不许**改动**   工具只 INSERT、不 UPDATE 既有行,回滚只删自己 manifest 里的主键 ——
                     这一条本来就成立,这里把它写下来当约定,并且有自测钉着

⚠️ **受保护的值仍然要参与唯一性比对。** 它们在库里确实存在,撞了就是撞了。
所以「从外键池里剔掉」和「算唯一性时算进去」用的是同一批值,用途正好相反 ——
第一版差点把两处合成一个函数,那会造出一批和夹具主键相同的行。

## 声明长什么样

```json
[{"表": "customer", "条件": "id LIKE 'E-%'", "为什么": "反例夹具,种子里写着不许补全"},
 {"表": "customer", "条件": "id IN ('C10017')", "为什么": "售后判责用例的真值依赖它量体不全"}]
```

**条件是一段 SQL**,因为夹具的形状千奇百怪:前缀、枚举、关联子查询都有。
工具不替项目发明一套表达式语言 —— 库自己的 WHERE 已经够用,而且看得懂。

## 认夹具:证据和猜要分开

`猜夹具()` 出的是**建议清单**,不是结论。三种线索的分量完全不同:

    证据   **检查/评测脚本里写死的 id**,而且只占这张表的一小撮 —— 这种几乎不会错
    猜     被真值表引用的行
    猜     id 前缀和大多数行不一样(E- / TEST- / DEMO-)

**工具不自动保护任何一行。** 人看过、写进声明,才算数 ——
自动保护会悄悄缩小造数范围,而「少造了什么」在结果里看不见。

## 第一版这条判据画错了边(实测当场打脸)

第一版扫**全部源码**,于是 `category` 53 行里的 53 行、`craft` 42 行全被标成「证据」——
那些不是夹具,是**主数据**:派生脚本当然会提到每一个品类编码。
照那份清单去保护,等于**把整张表冻住**,而缩小了多少造数范围在结果里看不见。

改了两处,都是在收窄:

    只扫检查/评测类文件    派生脚本提到编码是正常的,检查里写死一个 id 才可疑
    **命中占比过半就降级**  一张表大部分行都被提到 → 那是主数据,不是夹具

**「夹具」的定义里本来就带着「少数」** —— 它是特意造出来的那几行反例。
一条把整张表都圈进去的判据,说明判据贴错了东西。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

默认声明文件 = os.path.join(ROOT, ".fakedata", "protected.json")
_ID字面量 = re.compile(r"""['"]([A-Za-z][A-Za-z0-9_\-]{2,39})['"]""")
_真值表 = re.compile(r"truth|eval|expect|真值|夹具|fixture", re.I)
# 只认检查/评测类文件:派生脚本、页面、工具里提到编码是正常的
_检查文件 = re.compile(r"(check|eval|judge|truth|fixture|夹具|selftest|_test)", re.I)
# 命中占这张表的比例到了这条线,就不是夹具是主数据 —— 夹具的定义里带着「少数」
主数据占比线 = 0.5


def 读声明(path=None):
    """读保护声明。没有文件就是空 —— **空要说出来**,不然「没保护」和「不需要保护」长得一样。"""
    path = path or 默认声明文件
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        decl = json.load(f)
    for d in decl:
        if not d.get("表") or not d.get("条件"):
            raise SystemExit(f"保护声明缺「表」或「条件」:{d}")
    return decl


def 条件_of(声明, table):
    """这张表上所有保护条件,合成一句 WHERE。没有就返回 None。"""
    conds = [d["条件"] for d in 声明 if d["表"] == table]
    return " OR ".join(f"({c})" for c in conds) if conds else None


def 受保护的值(conn, 声明, table, col, cap=50000):
    """这张表被保护的那些行,在 col 这一列上的取值。**外键池要从里面剔掉这些。**

    查不动(条件写错、表不存在)就**抛出来**,不静默返回空集 ——
    静默返回空集的后果是「保护看起来生效了,其实一行都没保护」。
    """
    w = 条件_of(声明, table)
    if not w:
        return set()
    sql = (f"select {conn.ident(col)} from {conn.ident(table)} "
           f"where ({w}) and {conn.ident(col)} is not null limit {cap}")
    try:
        return {r[0] for r in conn.q(sql)}
    except Exception as e:
        raise SystemExit(f"❌ 保护声明在 {table} 上查不动:{e}\n   条件:{w}\n"
                         f"   **不当作「没有要保护的行」往下走** —— 那会让保护静默失效。")


def 过滤外键池(conn, 声明, parent, col, 值):
    """把受保护的行从外键取值池里剔掉。返回 (剩下的, 剔掉几个)。"""
    if not 声明:
        return 值, 0
    bad = 受保护的值(conn, 声明, parent, col)
    if not bad:
        return 值, 0
    keep = [v for v in 值 if v not in bad]
    return keep, len(值) - len(keep)


def 统计(conn, 声明):
    """每条声明**实际护住了几行** —— 一条护住 0 行的声明,和没写是一样的,要报出来。"""
    out = []
    for d in 声明:
        try:
            n = conn.q(f"select count(*) from {conn.ident(d['表'])} where ({d['条件']})")[0][0]
        except Exception as e:
            n = f"查不动:{e}"
        out.append({**d, "护住几行": n})
    return out


# ── 认夹具:出建议,不出结论 ──────────────────────────────────────────
def _源码里的字面量(dirs, 后缀=(".py",), 跳过=("fakedata",), cap_files=4000, 只要检查文件=True):
    vals = set()
    for d in dirs:
        for root, subs, files in os.walk(d):
            subs[:] = [s for s in subs if not s.startswith(".") and s not in 跳过
                       and s not in ("node_modules", "__pycache__", ".venv")]
            for fn in files:
                if not fn.endswith(后缀):
                    continue
                if 只要检查文件 and not _检查文件.search(fn):
                    continue
                cap_files -= 1
                if cap_files < 0:
                    return vals
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        vals |= set(_ID字面量.findall(f.read()))
                except Exception:
                    continue
    return vals


def 猜夹具(conn, sc, dirs=None, 每表上限=50000):
    """扫出「可能碰不得」的行。**返回建议,人确认后才写进声明。**

    三种线索分量不同,所以分开标:写死在检查源码里的是**证据**,其余是**猜**。
    """
    dirs = dirs or [os.path.join(ROOT, "backend"), os.path.join(ROOT, "tools"),
                    os.path.join(ROOT, "agent"), os.path.join(ROOT, "knowledge")]
    源码值 = _源码里的字面量([d for d in dirs if os.path.isdir(d)])
    真值表 = [t for t in sc.tables if _真值表.search(t)]
    真值里的值 = set()
    for t in 真值表:
        for c in sc.tables[t].columns:
            try:
                真值里的值 |= {r[0] for r in conn.q(
                    f"select {conn.ident(c.name)} from {conn.ident(t)} limit 5000")
                    if isinstance(r[0], str)}
            except Exception:
                continue

    建议 = []
    for tname, tb in sc.tables.items():
        if not tb.pk or len(tb.pk) != 1 or _真值表.search(tname):
            continue
        pk = tb.pk[0]
        try:
            ids = [r[0] for r in conn.q(
                f"select {conn.ident(pk)} from {conn.ident(tname)} limit {每表上限}")
                if isinstance(r[0], str)]
        except Exception:
            continue
        if not ids:
            continue
        写死的 = sorted(set(ids) & 源码值)
        真值引用的 = sorted((set(ids) & 真值里的值) - set(写死的))
        # 前缀异常:取 id 的字母前缀,占比不到 5% 的那些前缀
        前缀 = {}
        for i in ids:
            m = re.match(r"^[A-Za-z]+[-_]?", i)
            if m:
                前缀.setdefault(m.group(0), []).append(i)
        少数前缀 = {p: v for p, v in 前缀.items()
                    if len(v) / len(ids) < 0.05 and len(前缀) > 1}
        if 写死的:
            占比 = len(写死的) / len(ids)
            主数据 = 占比 >= 主数据占比线   # **一半就不算「少数」了** —— 夹具的定义里带着少数
            建议.append({"表": tname,
                         "证据等级": "猜" if 主数据 else "证据",
                         "线索": (f"检查/评测里提到了这张表 {占比:.0%} 的行"
                                  if 主数据 else "写死在检查/评测里,且只占这张表的一小撮"),
                         "条件": f"{pk} IN ({', '.join(repr(x) for x in 写死的[:40])})",
                         "命中": len(写死的), "占比": round(占比, 3), "样例": 写死的[:6],
                         "为什么": ("**大部分行都被提到 → 这是主数据,不是夹具**。"
                                    "照它保护等于把整张表冻住,而少造了什么看不见"
                                    if 主数据 else
                                    "**写死在检查里的 id 就是夹具** —— 动了它,那条检查测的就是别的东西了")})
        if 真值引用的:
            建议.append({"表": tname, "证据等级": "猜", "线索": f"被真值表引用({', '.join(真值表[:3])})",
                         "条件": f"{pk} IN ({', '.join(repr(x) for x in 真值引用的[:40])})",
                         "命中": len(真值引用的), "样例": 真值引用的[:6],
                         "为什么": "真值是照当时的数据算出来的;数据变了,真值描述的就是一个不存在的世界"})
        for p, v in sorted(少数前缀.items(), key=lambda kv: -len(kv[1]))[:2]:
            建议.append({"表": tname, "证据等级": "猜", "线索": f"id 前缀 {p!r} 只占 {len(v)/len(ids):.1%}",
                         "条件": f"{pk} LIKE '{p}%'", "命中": len(v), "样例": v[:6],
                         "为什么": "前缀不一样的那一小撮,常常是**特意造出来的反例**"})
    建议.sort(key=lambda x: (x["证据等级"] != "证据", -x["命中"]))
    return 建议


def 写声明(path, 建议, 只要证据=True):
    """把建议落成声明文件。**默认只落「证据」那一档** —— 猜的要人看过再加。"""
    decl = [{"表": b["表"], "条件": b["条件"], "为什么": b["为什么"], "来源": b["线索"]}
            for b in 建议 if (not 只要证据 or b["证据等级"] == "证据")]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(decl, f, ensure_ascii=False, indent=1)
    return path, len(decl)
