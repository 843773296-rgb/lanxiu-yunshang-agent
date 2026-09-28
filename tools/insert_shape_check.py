#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INSERT 要写具名列 —— **列数恰好相等而顺序错了,是不报错的。**

    python3 tools/insert_shape_check.py          # 门禁
    python3 tools/insert_shape_check.py --登记     # 把现存的位置参数写进欠债表(只在第一次用)

## 这条是怎么来的

2026-09-28 CI 红:`table craft has 13 columns but 12 values were supplied`。
给 `craft` 加了一列,`seed.py` 里那句 `INSERT INTO craft VALUES(?×12)` 没跟着改。
**本地一直绿** —— 本地是在现有库上 ALTER,从没跑过 seed 的 INSERT 这条路。

而那次是走运。列数不等 sqlite 当场抛;**要是恰好相等,值会整体挪一格而不报错** ——
name 存进 cat、cat 存进 alias,全库悄悄错位。

这条检查第一次跑就抓到一处真的:`server.py` 前台「新建方案」写的是 `VALUES(?×13)`,
而 `scheme` 早就是 14 列 —— **这条路一直在抛 500,没有任何检查红过**,
因为 seed 里所有方案都走具名列,本地数据从不经过它。

## 判四条

    列数对不上      → 红(跑之前就红,不用等从零重建)
    找不到建表语句  → 红,**而且单独报**。没东西可比,不是通过
    新增位置参数    → 红(棘轮)
    欠债表里改好的  → 红(反向检查)

**钉的是「具名列」,不只是「列数对不上」。** 列数对不上是吵闹的,sqlite 自己会抛;
真正危险的是**列数恰好相等而顺序错了** —— 这个静态扫描测不出来,
所以只能把这种可能性从结构上去掉:写了列名,顺序就没有语义了。

## 两层注释都要剥

走 AST 取字符串,**Python 注释**自然就不在视野里。但这还不够 ——
`seed.py` 的 SCHEMA 字符串里有一行 **SQL 注释** 就写着 `INSERT INTO sku VALUES(?×16)`,
那是一句告诫,在 AST 眼里它和真语句一样是字符串的一部分。
所以取到字符串之后还要剥掉 `-- …` 和 `/* … */`。
(写这份检查时当场撞到的:没剥之前,它把那句告诫本身报成了「列数对不上」。)

同理,建表语句里的 SQL 注释带逗号(`-- 关键尺寸,顿号分隔`),不剥会把列数数多。

## 棘轮的键是「文件 + 表名 → 处数」,不是行号

现存 100 多处位置参数,一次改完会出错、还会和并行会话抢文件。所以登记成欠债:
只许少不许多,改好了**必须**从欠债表里删掉。

键不用行号:行号被上面插一行注释就全乱,于是欠债表天天在变,
而**一份天天变的欠债表没人会看**。「这个文件往这张表位置参数插了几处」跟着逻辑走。

## 不在范围里的

`管理后台/` —— 另一个服务、另一个库(Postgres),表建在 alembic 迁移里而不是 SQL 字符串里。
扫进来只会多出一百多条「找不到建表」,而那是「不归这把尺子量」,不是「没东西可比」。
"""
import ast, json, os, re, sys, warnings
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
欠债表 = os.path.join(ROOT, "tools", "位置参数欠债.json")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ("把 derive_xingzhi 里 `INSERT INTO xingzhi VALUES(?,?,?,?,?)` 删掉一个 ?",
     "列数和建表语句对得上"),
    ("把 server.py 新建方案那句具名 INSERT 的表名改成不存在的 `schemex`",
     "每处 INSERT 都找得到建表语句"),
    ("在 server.py 新建方案那段加一句 `INSERT INTO scheme VALUES(?×14)`(列数对得上,只是位置参数)",
     "没有新增的位置参数 INSERT"),
    ("把 derive_xingzhi 那句改成具名列、但不删欠债表", "欠债表里的都还欠着"),
]

跳过目录 = {".git", "__pycache__", ".venv", "node_modules", ".fakedata", "static"}
不在范围 = ("管理后台",)
约束词 = {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}
动态 = "{…}"   # f-string 里的插值 —— 表名是运行时才知道的

建表式 = re.compile(r"CREATE\s+(?:TEMP\w*\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                 r"[\"`\[]?(\w+)[\"`\]]?\s*\(", re.I)
加列式 = re.compile(r"ALTER\s+TABLE\s+[\"`]?(\w+)[\"`]?\s+ADD\s+(?:COLUMN\s+)?[\"`]?(\w+)", re.I)
插入式 = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\"`]?(\w+|\{…\})[\"`]?\s*", re.I)


def 去注释(s):
    return re.sub(r"/\*.*?\*/", "", re.sub(r"--[^\n]*", "", s), flags=re.S)


def 字符串们(树):
    """AST 里所有**不是文档字符串**的字面串。f-string 拼成一条,插值处换成 {…}。"""
    文档, f内 = set(), set()
    for n in ast.walk(树):
        if (isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)):
            文档.add(id(n.body[0].value))
        if isinstance(n, ast.JoinedStr):
            f内.update(id(v) for v in ast.walk(n) if v is not n)
    for n in ast.walk(树):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and id(n) not in 文档 and id(n) not in f内:
            yield n.lineno, n.value
        elif isinstance(n, ast.JoinedStr):
            yield n.lineno, "".join(v.value if isinstance(v, ast.Constant) else 动态
                                    for v in n.values)


def 括号内(s, i):
    """s[i] 是 '(',返回配对括号里的内容;不配对返回 None。"""
    深 = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            深 += 1
        elif s[j] == ")":
            深 -= 1
            if 深 == 0:
                return s[i + 1:j]
    return None


def 顶层切(s):
    """按顶层逗号切 —— 括号里、引号里的逗号不算。"""
    出, 段, 深, 引 = [], "", 0, None
    for ch in s:
        if 引:
            段 += ch
            if ch == 引:
                引 = None
            continue
        if ch in "'\"":
            引 = ch
        elif ch == "(":
            深 += 1
        elif ch == ")":
            深 -= 1
        if ch == "," and 深 == 0:
            出.append(段.strip()); 段 = ""
        else:
            段 += ch
    if 段.strip():
        出.append(段.strip())
    return 出


def 扫():
    """返回 (建表 {表: [(文件, 列数)]}, 加列 {表: 加了几列}, INSERT 清单)。"""
    建表, 加列, 插入 = defaultdict(list), defaultdict(set), []
    for d, ds, fs in os.walk(ROOT):
        ds[:] = [x for x in ds if x not in 跳过目录 and not x.startswith(".")]
        if os.path.relpath(d, ROOT).split(os.sep)[0] in 不在范围:
            ds[:] = []
            continue
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, ROOT)
            # ⚠️ 不扫自己:咬合描述和提示语里都有 `INSERT INTO …`,
            # **判据的搜索范围盖住了它自己**(bite_check 记过的同一个坑,写这份时又撞了一次)
            if os.path.abspath(p) == os.path.abspath(__file__):
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)   # 别的文件里的 "\s" 之类
                    树 = ast.parse(open(p, encoding="utf-8").read())
            except Exception:
                continue
            for 行, s in 字符串们(树):
                s = 去注释(s)
                for m in 建表式.finditer(s):
                    体 = 括号内(s, m.end() - 1)
                    if 体 is None or 动态 in 体:
                        continue
                    列 = [x for x in 顶层切(体) if x.split()[0].strip('"`[]').upper() not in 约束词]
                    建表[m.group(1)].append((rel, len(列)))
                for m in 加列式.finditer(s):
                    加列[m.group(1)].add(m.group(2))
                for m in 插入式.finditer(s):
                    后 = s[m.end():]
                    列名 = None
                    if 后.startswith("("):
                        体 = 括号内(后, 0)
                        列名 = 顶层切(体) if 体 is not None and 动态 not in 体 else "?"
                    值数 = None
                    vm = re.match(r"(?:\([^)]*\)\s*)?VALUES\s*\(", 后, re.I)
                    if vm:
                        体 = 括号内(后, vm.end() - 1)
                        if 体 is not None and 动态 not in 体:
                            值数 = len(顶层切(体))
                    插入.append(dict(文件=rel, 行=行, 表=m.group(1), 列名=列名, 值数=值数))
    return 建表, 加列, 插入


def 位置参数账(插入):
    """{文件: {表: 处数}} —— 棘轮的键。"""
    账 = defaultdict(lambda: defaultdict(int))
    for x in 插入:
        if x["列名"] is None:
            账[x["文件"]][x["表"]] += 1
    return {f: dict(sorted(t.items())) for f, t in sorted(账.items())}


def 读欠债():
    if not os.path.isfile(欠债表):
        return {}
    return json.load(open(欠债表, encoding="utf-8")).get("欠着的", {})


def 列(清单, n=4):
    return "、".join(清单[:n]) + (f"  ……**还有 {len(清单) - n} 处**(共 {len(清单)})"
                                 if len(清单) > n else "")


def main():
    建表, 加列, 插入 = 扫()
    现 = 位置参数账(插入)
    if "--登记" in sys.argv:
        json.dump({"说明": __doc__.split("##")[0].strip(),
                   "怎么还": "把那几处改成 `INSERT INTO 表(列1,列2,…) VALUES(…)`,再把处数减掉(减到 0 删掉那张表)。"
                             "**减不减由这个检查强制** —— 改好了还留着,它会红。",
                   "登记于": "2026-09-28",
                   "欠着的": 现},
                  open(欠债表, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"登记 {sum(sum(t.values()) for t in 现.values())} 处 / {len(现)} 个文件 → {欠债表}")
        return 0

    欠 = 读欠债()
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("INSERT 要写具名列")
    n具名 = sum(1 for x in 插入 if x["列名"] is not None)
    n位置 = len(插入) - n具名
    # 样本量:扫不到东西时,下面几条会全部「成立」
    ck(len(建表) >= 50 and len(插入) >= 100, "扫到的建表语句和 INSERT",
       f"建表 {len(建表)} 张 / INSERT {len(插入)} 处(具名 {n具名} · 位置参数 {n位置})"
       + ("" if len(建表) >= 50 and len(插入) >= 100 else " —— **太少了,是扫描坏了,不是都通过**"))

    # ① 找不到建表 —— 单独一条,不和「列数对得上」混:没东西可比不是通过
    看不出 = [x for x in 插入 if x["表"] == 动态]
    没建表 = [f"{x['文件']}:{x['行']} {x['表']}" for x in 插入
            if x["表"] != 动态 and x["表"] not in 建表]
    ck(not 没建表, "每处 INSERT 都找得到建表语句",
       列(没建表) + " —— **没东西可比,不是通过**。表建在别处(迁移/别的库)的话,在这里说明为什么不归这把尺子量"
       if 没建表 else f"{len(插入) - len(看不出)} 处都找得到")
    if 看不出:
        print(f"     {Y}⚠️ 表名是运行时拼的 {len(看不出)} 处 —— 列数没法静态比,**这几处不算验过**:"
              f"{列([x['文件'] + ':' + str(x['行']) for x in 看不出], 8)}{D}")

    # ② 列数对不上。同文件里有建表就用同文件的(fixture 常自建一张同名小表),否则比全仓的
    不符, 可比 = [], 0
    for x in 插入:
        if x["表"] not in 建表 or x["值数"] is None:
            continue
        if x["列名"] is not None:
            if x["列名"] == "?":
                continue
            可比 += 1
            if len(x["列名"]) != x["值数"]:
                不符.append(f"{x['文件']}:{x['行']} {x['表']} 写了 {len(x['列名'])} 列、给了 {x['值数']} 个值")
            continue
        可比 += 1
        同 = [n for f, n in 建表[x["表"]] if f == x["文件"]] or [n for f, n in 建表[x["表"]]]
        合法 = set(同) | {n + len(加列.get(x["表"], ())) for n in 同}
        if x["值数"] not in 合法:
            不符.append(f"{x['文件']}:{x['行']} {x['表']} 给了 {x['值数']} 个值、"
                      f"建表是 {'/'.join(map(str, sorted(set(同))))} 列")
    ck(not 不符, "列数和建表语句对得上",
       列(不符) + " —— 从零重建会当场炸;本地在现有库上 ALTER 的话,这条路根本走不到"
       if 不符 else f"比了 {可比} 处")

    # ③ 棘轮:新增的位置参数
    新增 = [f"{f} → {t}" + (f" 多 {n - 欠.get(f, {}).get(t, 0)} 处" if 欠.get(f, {}).get(t) else "")
          for f, ts in 现.items() for t, n in ts.items() if n > 欠.get(f, {}).get(t, 0)]
    n欠 = sum(sum(t.values()) for t in 欠.values())
    ck(not 新增, "没有新增的位置参数 INSERT",
       列(新增) + " —— 写成 `INSERT INTO 表(列1,列2,…) VALUES(…)`。"
       "**列数恰好相等而顺序错了是不报错的**,值会整体挪一格"
       if 新增 else f"欠债表里 {n欠} 处,一处没多")

    # ④ 反向:改好了就得从欠债表里减掉
    好了 = [f"{f} → {t}(欠债 {n},现在 {现.get(f, {}).get(t, 0)})"
          for f, ts in 欠.items() for t, n in ts.items() if 现.get(f, {}).get(t, 0) < n]
    ck(not 好了, "欠债表里的都还欠着",
       列(好了) + f" —— **已经改好了,把 {os.path.basename(欠债表)} 里的处数减掉**。"
       "囤积的欠债和真欠债长得一模一样"
       if 好了 else f"{n欠} 处都还欠着")

    if n欠:
        print(f"     ℹ️ 欠着 {n欠} 处({len(欠)} 个文件)—— 不拦门禁,但**只许少不许多**。"
              f"最多的:{列([f'{f} {sum(t.values())}' for f, t in sorted(欠.items(), key=lambda kv: -sum(kv[1].values()))], 3)}")
    print((f"{R}❌ INSERT 形状 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ INSERT 都对得上建表,没有新增位置参数{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
