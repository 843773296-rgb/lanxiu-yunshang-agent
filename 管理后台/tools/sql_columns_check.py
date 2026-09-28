#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQL 里引的列**在库里真的存在吗** —— 问数据库,不猜。

## 为什么要这条检查

2026-09-28 一天之内同一族栽了四次:

    spans.error              是 JSONB,塞了裸字符串   ← 只在失败路径上炸
    feedback.note            是 TEXT,当 JSONB 用     ← `note->>` 直接报错
    evaluations.candidate_ref 是 JSONB,塞了裸字符串
    tool_versions.name       **根本不存在**(名字在 tool_definitions 上)
                             side_effect_level 也不存在(叫 side_effect_type)

四次的共同点只有一个:**在没查的情况下写了 SQL**。
而最后那次更糟 —— 它在「这条请求绑了工具版本」才走到的分支里,
**又是一个罕见分支里的必炸**。

> `sql_lint.py` 拦不住这一族:它查绑定参数,不查列名存不存在。
> 而这是**可查的** —— 库就在那儿。

## 判据:抠出 `from/join <表>` 和 `<别名>.<列>`,问 information_schema

⚠️ **只查带表别名的列引用**(`tv.side_effect_type`),不查裸列名。
裸列名要做别名解析和子查询作用域,而那是半个 SQL 解析器 ——
写错的部分会**不报**,而漏掉的那种正好是下次踩的那种。
带别名的那些已经覆盖了今天栽的四次里的第四次,
而前三次是**类型**问题,由 `sql_lint` 之外的另一条路管(见下)。

⚠️ 连不上库时**明确报出来并退非 0**,不静默跳过 ——
「跳过了」和「通过了」在输出上长得一模一样。

## ⚠️ 已知盲区(写下来才和「忘了」分得开)

  ① **裸列名不查**(`select name from …`)—— 要做别名解析和子查询作用域
  ② **非 ASCII 的列引用看不见** —— `_引用` 只认 `[a-z_][a-z0-9_]*`。
     这个仓库到处是中文标识符,不过那些是 `as` **之后**的别名
     (`sum(quantity) token数`),不是被引用的列,所以目前不漏。
     **真有中文列名的那天,这条检查会对它们静默放行。**
  ③ **只查列名存不存在,不查类型对不对** —— 今天栽的四次里有三次是类型
     (裸串塞 JSONB / 结构塞 TEXT)。那一族现在还是靠人查,
     **这是已知缺口**。
"""
import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "tools"))

过, 挂, 硬错 = [], [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 库里的列():
    try:
        from sqlalchemy import create_engine, text
        import runtime_cfg as CFG
    except ImportError as e:
        return None, f"要 sqlalchemy:{e}"
    try:
        e = create_engine(CFG.DATABASE_URL)
        with e.connect() as c:
            出 = {}
            for t, col in c.execute(text(
                    "select table_name, column_name from information_schema.columns "
                    "where table_schema='public'")):
                出.setdefault(t, set()).add(col)
        return 出, ""
    except Exception as ex:
        return None, f"{type(ex).__name__}: {str(ex)[:120]}"


_别名 = re.compile(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\s+(?:as\s+)?([a-z][a-z0-9_]*)\b",
                  re.I)
_引用 = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")
# 这些别名不是表(是 CTE、函数、关键字)
_不是表 = {"on", "and", "or", "where", "select", "set", "values", "as", "using",
        "left", "right", "inner", "outer", "lateral", "cast", "text", "jsonb"}


def main():
    列表, 为什么 = 库里的列()
    if 列表 is None:
        print(f"❌ 连不上库:{为什么}")
        print("   **这不叫跳过** —— 跳过和通过在输出上长得一样,所以退非 0")
        return 1
    ck(f"从 information_schema 读到 {len(列表)} 张表", len(列表) >= 40, len(列表))

    import sql_lint as SL
    文件们 = []
    for d in SL.扫的目录:
        full = os.path.join(根, d)
        if not os.path.isdir(full):
            continue
        for dp, dn, fn in os.walk(full):
            dn[:] = [x for x in dn if x not in (".venv", "__pycache__", "node_modules")]
            文件们 += [os.path.join(dp, f) for f in fn if f.endswith(".py")]

    查了 = 0
    for 路 in sorted(文件们):
        for 行号, sql in SL._text调用们(路):
            别名到表 = {a.lower(): t.lower() for t, a in _别名.findall(sql)
                    if a.lower() not in _不是表}
            if not 别名到表:
                continue
            for 别名, 列 in _引用.findall(sql):
                表 = 别名到表.get(别名.lower())
                if not 表 or 表 not in 列表:
                    continue
                查了 += 1
                if 列.lower() not in {c.lower() for c in 列表[表]}:
                    近 = sorted(c for c in 列表[表] if 列.lower()[:5] in c.lower())
                    硬错.append((os.path.relpath(路, 根), 行号,
                                 f"`{别名}.{列}` —— 表 `{表}` **没有这一列**"
                                 + (f"。像的有:{近[:3]}" if 近 else "")))
    ck(f"查了 {查了} 处带表别名的列引用", 查了 >= 20, 查了)

    if 硬错:
        print(f"\n  ❌ {len(硬错)} 处**硬错**(SQL 一跑就报 UndefinedColumn):")
        for 相对, i, 说 in 硬错:
            print(f"     {相对}:{i}  {说}")
    else:
        ck("每一处带别名的列引用,库里都真有那一列", True)

    # ── 咬合:这个检查自己得能咬 ────────────────────────────────
    # ⚠️ 假列名用 **ASCII**:`_引用` 的正则只认 `[a-z_][a-z0-9_]*`,
    # 第一版拿中文当假列名,于是**咬合自己没咬上** —— 而那不是咬合写错了,
    # 是判据有个盲区(见文件头「已知盲区」)。
    假 = "select tv.id, tv.no_such_column_here from tool_versions tv"
    别名到表 = {a.lower(): t.lower() for t, a in _别名.findall(假)}
    坏 = [(a, c) for a, c in _引用.findall(假)
          if 别名到表.get(a.lower()) in 列表
          and c.lower() not in {x.lower() for x in 列表[别名到表[a.lower()]]}]
    ck("咬合:编一个不存在的列 → 抓到", bool(坏), 坏)
    真 = "select tv.id, tv.version_no from tool_versions tv"
    别名到表2 = {a.lower(): t.lower() for t, a in _别名.findall(真)}
    坏2 = [(a, c) for a, c in _引用.findall(真)
           if 别名到表2.get(a.lower()) in 列表
           and c.lower() not in {x.lower() for x in 列表[别名到表2[a.lower()]]}]
    ck("对照:真存在的列**不报**(否则上一条可能只是恒为真)", not 坏2, 坏2)

    print(f"\n{'✅' if not (挂 or 硬错) else '❌'} 过 {len(过)} / 挂 {len(挂)} / 硬错 {len(硬错)}")
    return 1 if (挂 or 硬错) else 0


if __name__ == "__main__":
    sys.exit(main())
