# -*- coding: utf-8 -*-
"""**方案上那些编码,怎么翻回中文。**

## 为什么要单独有这一层

`scheme` 表上的形制 / 面料 / 工艺 / 版型存的是**编码**(`XZ04` `MT02` `KF02` `PT06`),
不是名字。这是刻意的 —— `backend/seed.py` 里那段注释说清了原因:

> 原来存的是名字(「明制立领长衫」「云锦」),而**名字一改,
> 所有历史方案的引用当场断掉而且悄无声息**。

代价是:**谁要显示方案,谁就得翻一次**。而「翻一次」这件事有三个容易各写各的地方 ——
页面、MCP 工具、报价单。三份手抄件迟早不一致,**而不一致的那天不会有人发现**,
只会有一个客户看到别的形制名字。

⚠️ 这个模块是 2026-09-18 补的,而 `seed.py` 里那句「见 `knowledge/scheme_ref.py`」
**在此之前指向的是一个不存在的文件** —— 注释写了,模块没建。
一条指着空气的注释比没有注释更糟:照着去找的人会以为自己看漏了。

## 翻不出来时报出来,不要静默丢掉

`XZ99` 这种查不到的编码,**返回 `XZ99(库里查不到)`,不返回 None**。

理由和这个项目里其他地方一致:**「这一格没有」和「这一格是空的」必须能分开**。
静默丢掉的话,一份引用了已删除形制的旧方案,看起来就像一份**没填形制**的方案 ——
而前者是数据事故,后者是正常的草稿。
"""

# 编码前缀 → (主数据表, 这类东西叫什么)。**按前缀分派,不按字段名分派** ——
# 字段名会改(xz / mt / kf 是缩写),编码前缀是印在数据里的,改不动。
前缀表 = {
    "XZ": ("xingzhi", "形制"),
    "MT": ("material", "面料"),
    "KF": ("craft", "工艺"),
    "PT": ("pattern", "版型"),
}


def 名(conn, code):
    """一个编码翻成中文。查不到返回「编码(库里查不到)」,不返回 None。"""
    if not code:
        return None
    code = str(code).strip()
    if not code:
        return None
    表 = 前缀表.get(code[:2].upper())
    if not 表:
        return f"{code}(认不出这是哪类编码)"
    r = conn.execute(f"SELECT name FROM {表[0]} WHERE code=?", (code,)).fetchone()
    if not r:
        return f"{code}(库里查不到)"
    return r[0] if not hasattr(r, "keys") else r["name"]


def 多名(conn, codes):
    """逗号分隔的一串编码翻成一串中文。空串返回空列表,不返回 [None]。"""
    if not codes:
        return []
    return [名(conn, c) for c in str(codes).split(",") if c.strip()]


def 展开(conn, r):
    """一行 scheme 翻成给人看的样子。

    `r` 可以是 sqlite3.Row,也可以是 dict —— 两种调用方都有。
    """
    g = (lambda k: r[k] if k in r.keys() else None) if hasattr(r, "keys") \
        else (lambda k: r.get(k))
    return {
        "方案号": g("id"), "名称": g("name"), "状态": g("status"),
        "客户号": g("customer_id"), "顾问工号": g("advisor_no"),
        "形制": 名(conn, g("xz")),
        "面料": 名(conn, g("mt")),
        "工艺": 多名(conn, g("kf")),
        "颜色": g("color") or None,
        # 配饰存的是中文名不是编码(库里就是「云肩,腰封」),所以这里不翻,只拆开
        "配饰": [x.strip() for x in (g("ps") or "").split(",") if x.strip()],
        "版型": 名(conn, g("pattern")),
        "备注": g("note"), "建于": g("created"), "改于": g("updated"),
    }


def 已锁定的(方案们):
    """从一组展开后的方案里挑出已锁定的。

    ⚠️ **业务 2026-09-18 明确:一个客户可以多条方案同时处于已锁定**
    (婚服、敬酒服、伴娘服各锁各的)。所以这个函数返回的是**列表不是单条** ——
    写成返回单条的话,调用方会自然而然地把「锁定那条」当成唯一标识,
    而那正是这条业务决定否掉的东西。**消歧只能靠方案号,不能靠状态。**
    """
    return [x for x in 方案们 if (x.get("状态") or x.get("status")) == "已锁定"]
