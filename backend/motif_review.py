#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品纹样的**业务核定** —— 人的判断覆盖推算,而且不许被重算冲掉。

## 为什么要单独一层

纹样是**算出来的**,不落库(`backend/opportunity.py` 原话)——
`knowledge/motif.py` 从商品名、面料、工艺推,词表是闭集,推不出来就标「待业务核」。
这个设计是对的:词表改了,296 件商品一起跟着更新,不会留陈旧快照。

但它和 `motif.py` 开头那条规则撞上了:

> **业务核过的不许被重新推的覆盖**(和裁片用料占比那套同一条)。

人核过的结论**不是算出来的**,它是事实 —— 没地方存就等于没有这条规则。
所以这里补一层:推算照旧归口径层,核定归这里,**读的时候核定优先**。

## 为什么放 backend/ 而不是写进 knowledge/motif.py

两个理由,第二个是硬的:

1. **分层**:核定不是「口径」,是「人的判断覆盖口径」。
   和裁片用料占比完全同形 —— 推算逻辑在 `knowledge/piece_ratio.py`,
   核定写口在 `backend/api.py`,两边分开。
2. **`build_logic_fp` 把 `knowledge/` 下所有 .py/.md 按内容算进去。**
   纹样不落库,所以改它**一个字节的库数据都不会变**;
   而写进 motif.py 会让库指纹变化,看起来像「造数逻辑变了、库该重建」。
   > 一个「造数逻辑变了,库该重建」和一个「只有读取口径变了,库好着呢」,
   > **在指纹变化上长得一模一样。**
   为一个读取层的改动去重建 1767 秒的库,不值得。

## 两种「没有纹样」必须分开

`motif.py` 第 17 行就写着这件事:「无纹样」(答案)和「待业务核」(待办),
**留空的话这两种长得一模一样,统计会把它们加在一起。**
所以核定时「这件确实是素面」要存成 `无纹样`,不是存空、也不是不存。
"""
import os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
来源 = "业务核"            # 和 motif.推() 的五种来源并列的第六种


def 建表(c=None):
    """登记在 `tools/ensure_tables.py` 里 —— 本地建过就一直在,**而 CI 每次从零**。

    ⚠️ **参数是 connection,不是路径** —— 和 `ownership.建表(c)`、`arrival_card.建表(c)`
    一个约定,`ensure_tables` 按这个调。第一版我写成接路径,ensure_tables 当场
    `TypeError: expected str … not Connection`。给了 connection 就不自己关它(调用方开的)。
    """
    自开 = c is None
    c = c or sqlite3.connect(DB)
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS product_motif(
                       spu    TEXT PRIMARY KEY,
                       motif  TEXT NOT NULL,
                       why    TEXT NOT NULL,
                       actor  TEXT NOT NULL,
                       said   TEXT NOT NULL,
                       at     TEXT NOT NULL)""")
        c.commit()
    finally:
        if 自开:
            c.close()


def 读(db=None):
    """→ {spu: {"motif","why","actor","said","at"}};表不在就返回空(不抛)。"""
    db = db or DB
    if not os.path.exists(db):
        return {}
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        有 = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_motif'").fetchone()
        if not 有:
            return {}
        return {r["spu"]: dict(r) for r in c.execute("SELECT * FROM product_motif")}
    finally:
        c.close()


def 定(spu, 名, 面料="", 工艺="", db=None, 核定=None):
    """这件商品的纹样 → (纹样, 来源, 证据)。**核定优先于推算。**

    `核定` 可以传一份已经读好的表(扫一整库时别一件查一次库)。
    """
    表 = 读(db) if 核定 is None else 核定
    r = (表 or {}).get(spu)
    if r:
        return r["motif"], 来源, f"{r['actor']} 核定于 {r['at']}:{r['why']}"
    import sys
    if os.path.join(os.path.dirname(HERE), "knowledge") not in sys.path:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import motif
    return motif.推(名, 面料 or "", 工艺 or "")


def 核(spu, 纹样, why, actor, said, db=None):
    """写一条核定。**校验在这里,不在调用方** —— 调用方是模型。

    ⚠️ 签名里**没有 role** —— 身份由 `api.review_motif` 从登录态取。
    照 `set_piece_ratio` 的注释:「有的话,一句『我以版师身份』就能提权」。
    """
    import sys
    if os.path.join(os.path.dirname(HERE), "knowledge") not in sys.path:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import motif
    import datetime
    允 = list(motif.词表()) + ["无纹样"]
    if 纹样 not in 允:
        raise ValueError(f"「{纹样}」不在纹样词表里。词表是**闭集** —— "
                         f"要加新纹样得先扩词表(knowledge/motif.py),不能从这里塞进去。"
                         f"现在认的是:{'、'.join(sorted(set(允)))}")
    c = sqlite3.connect(db or DB)
    try:
        建表(c)                     # 同一个连接里建,省一次开关
        c.execute("INSERT INTO product_motif(spu, motif, why, actor, said, at) "
                  "VALUES(?,?,?,?,?,?) ON CONFLICT(spu) DO UPDATE SET "
                  "motif=excluded.motif, why=excluded.why, actor=excluded.actor, "
                  "said=excluded.said, at=excluded.at",
                  (spu, 纹样, why, actor, said,
                   # 和 `db_build.盖章()` 的 build_at 同一个理由:核定是一次**真实的人类操作**,
                   # 平移演示世界的日期不该把它一起平移(那会让「谁什么时候核的」变成假的)。
                   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))  # 真实时钟:人在真实世界里什么时候核的,和演示世界日期无关
        c.commit()
    finally:
        c.close()
    return 定(spu, "", db=db)


def 待核的(db=None, limit=None):
    """还推不出来、也没核过的商品 → [{spu, name, 面料, 工艺, 为什么推不出来}]。

    **这就是「待业务核 34 件」那个数的来源**,核定过的会从这里消失。
    """
    db = db or DB
    if not os.path.exists(db):
        return []
    import sys
    if os.path.join(os.path.dirname(HERE), "knowledge") not in sys.path:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
    import motif
    表 = 读(db)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    try:
        行 = list(c.execute("SELECT p.spu, p.name, pc.mt_opts, pc.kf_opts FROM product p "
                            "LEFT JOIN product_custom pc ON pc.spu=p.spu"))
    finally:
        c.close()
    out = []
    for r in 行:
        w, src, ev = 定(r["spu"], r["name"], r["mt_opts"] or "", r["kf_opts"] or "",
                        db=db, 核定=表)
        if w == motif.待核:
            out.append({"spu": r["spu"], "商品名": r["name"],
                        "面料": r["mt_opts"] or "", "工艺": r["kf_opts"] or "",
                        "为什么推不出来": ev})
    return out[:limit] if limit else out
