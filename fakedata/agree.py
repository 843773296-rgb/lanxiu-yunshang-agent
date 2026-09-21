#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一个事实的几个落点必须一致 —— **而且不许投票。**

    python3 fakedata/agree.py --db <库>                # 照声明逐条对
    python3 fakedata/agree.py --db <库> --自测          # 跑咬合

## 这条防的是什么

一个事实在库里常常有好几个落点。澜绣云裳的「这一款是给大人还是小孩穿的」
就落在四个地方:**形制、性别字段、商品名、号型**。

2026-09-21 用户出图时发现:「竹节」童款交领襦裙 —— 名字说童款,
而性别、版型、号型三处都说成人。出图清单只看了形制名,**静默判成成人比例**,
提示词写着「按成人比例」而商品名写着「童款」。是用户读出来的。

> 四个落点各自都合法,单看每一个都挑不出毛病 ——
> **错误只存在于它们之间**,而没有任何一张表负责这个「之间」。

## 铁律:三比一也是矛盾,不许投票

四个信号三个说成人、一个说童款,**不许判成人**。
少数服从多数听起来很稳,实际上是把「这条数据错了」悄悄改写成
「这条数据是对的,只是有个字段写歪了」——

  · 投票会**给出一个确定的答案**,于是下游照着它往下做,错误被固化
  · 投票**把矛盾消灭在报告之前**,于是没有人知道这里曾经打过架

真正的结论只有一个:**这条数据错了,要业务核。**
所以这里只报冲突,一个字都不猜。

## 两条容易漏掉的判据

**① 只有一个落点知道的键,不算「验过了」。**
某个键只有一个信号有值,那它自然「不打架」—— 但那是**没东西可对**,
不是对上了。这两种在输出上长得一模一样,所以分开数、分开报。

**② 一个落点一条都没读到,是红不是绿。**
SQL 写错、表改名、条件写反,都会让某个落点返回空集合。
而空集合上「所有值都一致」自动成立 —— **检查会安静地变成一个空转的循环**。
"""
import argparse, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
默认声明 = os.path.join(HERE, "一致.json")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("把某一行的一个信号改成和另外三个不一样", "同一个事实的几个落点不打架"),
    ("把某个落点的 SQL 改成读不到东西(条件写反)", "每个落点都读到了东西"),
    ("把某个事实的落点删到只剩一个", "每个事实至少有两个落点"),
]


def 跑一条(conn, 事实):
    """返回 (每个落点的 {键:值}, 出错的落点)。"""
    出, 坏 = {}, []
    for 点 in 事实["落点"]:
        归 = 点.get("归一") or {}
        if 点.get("取法模块"):
            # `路径.py:函数名` —— 函数收一个连接,返回 {键: 值} 或 {键: {子键: 值}}。
            # **为什么要有这个口子**:这个「事实」的判定往往已经在系统里有一份口径了
            # (「这款是童装还是成人款」就在 knowledge/grading.py 里)。
            # 在声明文件里用 SQL 再写一遍 = 造第二份实现,而两份分家时
            # 检查会说绿、系统是另一个说法 —— 这正是这条检查要防的那件事本身。
            try:
                d = _调(点["取法模块"], conn)
            except Exception as e:
                坏.append(f'{点["名"]}:取法模块跑不了({e})')
                continue
            拿 = 点.get("取哪个")
            if 拿:
                d = {k: v[拿] for k, v in d.items() if isinstance(v, dict) and 拿 in v}
            出[点["名"]] = {str(k): 归.get(str(v), v) for k, v in d.items()}
            continue
        try:
            rows = conn.execute(点["sql"]).fetchall()
        except sqlite3.Error as e:
            坏.append(f'{点["名"]}:SQL 跑不了({e})')
            continue
        出[点["名"]] = {str(k): 归.get(str(v), v) for k, v in rows}
    return 出, 坏


_缓存 = {}


def _调(取法模块, conn):
    """装一次、缓存住 —— 一个事实的五个落点会指向同一个函数,别装五遍。"""
    路径, _, 函数名 = 取法模块.partition(":")
    if 取法模块 not in _缓存:
        import importlib.util
        full = 路径 if os.path.isabs(路径) else os.path.join(ROOT, 路径)
        spec = importlib.util.spec_from_file_location("_取法_" + 函数名, full)
        m = importlib.util.module_from_spec(spec)
        sys.path.insert(0, os.path.dirname(full))
        spec.loader.exec_module(m)
        _缓存[取法模块] = getattr(m, 函数名)(conn)
    return _缓存[取法模块]


def 查(conn, 声明, 报=print):
    失败 = []

    def ck(ok, 名, 说明=""):
        报(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    事实们 = 声明.get("事实") or []
    ck(bool(事实们), "样本量:声明了几个事实", f"{len(事实们)} 个")
    if not 事实们:
        return 失败

    少落点 = [f["名"] for f in 事实们 if len(f.get("落点") or []) < 2]
    # 一个落点的「事实」永远不会打架 —— 它不是被验过了,是**根本没有第二个说法可对**
    ck(not 少落点, "每个事实至少有两个落点",
       "、".join(少落点) + "(共 %d 条,全列出来了)" % len(少落点)
       + " —— 一个落点永远不打架,那不叫一致"
       if 少落点 else f"{len(事实们)} 个事实,落点 {sum(len(f['落点']) for f in 事实们)} 处")

    空落点, 坏落点, 冲突, 已知, 该消的, 单信号, 对过 = [], [], [], [], [], 0, 0
    for f in 事实们:
        认过的 = {x["键"]: x for x in (f.get("已知打架") or [])}
        还在打的 = set()
        出, 坏 = 跑一条(conn, f)
        坏落点 += [f'{f["名"]}·{x}' for x in 坏]
        for 名, d in 出.items():
            if not d:
                空落点.append(f'{f["名"]}·{名}')
        键们 = set().union(*出.values()) if 出 else set()
        for k in 键们:
            有 = {名: d[k] for 名, d in 出.items() if k in d}
            if len(有) < 2:
                单信号 += 1
                continue
            对过 += 1
            if len(set(有.values())) > 1:
                # **不投票。** 谁多谁少一个字都不看,只把打架的原样报出来。
                if k in 认过的:
                    # **已知的缺口,登记在案**:业务还没判哪边对,不拿它拦门禁 ——
                    # 但每次都打出来,不让它安静下去(见「诚实的缺口,不硬凑」)。
                    已知.append((f["名"], k, 有, 认过的[k])); 还在打的.add(k)
                else:
                    冲突.append((f["名"], k, 有))
        # 反向那一半:登记了却**已经不打架了**的,要从登记里删掉。
        # 不查这个的话,登记表会囤积一堆早就修好的豁免,
        # 而囤积的豁免和真豁免长得一模一样(stable.py 那边同一个道理)。
        该消的 += [f'{f["名"]}#{k}' for k in 认过的 if k not in 还在打的]

    ck(not 坏落点, "每个落点的 SQL 都跑得了", "；".join(坏落点[:3]) if 坏落点 else "都跑通了")
    ck(not 空落点, "每个落点都读到了东西",
       "、".join(空落点[:4]) + (f"  ……还有 {len(空落点)-4} 处(共 {len(空落点)})"
                                if len(空落点) > 4 else "")
       + " —— **空集合上「所有值都一致」自动成立**,"
       "这个落点已经变成一个空转的循环了"
       if 空落点 else "每个落点都有数据")

    ck(对过 > 0, "有东西可对:至少有一个键被两个以上落点覆盖",
       f"{对过} 个键做了交叉对比" + (f",另有 {单信号} 个键只有一个落点知道 —— "
                                    f"**那些没被验过,不是验过了**" if 单信号 else ""))

    # ── 不符率分流:**先怀疑尺子,别怀疑数据** ────────────────────────
    # 2026-09-21 一天三次,全是我的口径错了,一次数据错都没有:
    #   订单金额  3542/26587 不符 → 拿 SUM(total) 比,该用 SUM(base_amount)
    #   客户单数   804/859  不符 → 我根本没有这一列的定义
    #   出图颜色     3/12   不符 → 那几款有多个 SKU 色图
    #
    # 一条把 3542 个冲突原样倒出来的报告,**会让人去改本来就对的数据** ——
    # 那是最贵的一种错:照着错的判据改对的东西,改完还"对上了"。
    #
    # 所以按不符率分档。档位不是拍脑袋:
    #   ≤ 5%    像**数据**问题 —— 少数几条跑偏,逐条看
    #   5–30%   说不准 —— 两边都要看一眼
    #   > 30%   几乎一定是**口径**问题 —— 一个事实的多个落点真能有三成对不上,
    #           那这个"事实"本来就不是同一件事。先去核定义,别动数据。
    def _分档(n, 总):
        率 = n / 总 if 总 else 0
        if 率 > 0.30:
            return ("口径", f"{n}/{总}({率:.0%})—— **这几乎一定是你的口径错了,不是数据错了**。"
                            f"一个事实的多个落点不可能有三成对不上;那说明这几个落点"
                            f"说的本来就不是同一件事。**先去核定义,别照着这份报告改数据**")
        if 率 > 0.05:
            return ("说不准", f"{n}/{总}({率:.0%})—— 不高不低,两边都要看一眼:"
                              f"先随手挑两条查判据,判据没问题再当数据问题查")
        return ("数据", f"{n}/{总}({率:.0%})—— 少数几条跑偏,像是数据问题,逐条看")

    档 = {}
    for f in 事实们:
        这条 = [x for x in 冲突 if x[0] == f["名"]]
        if 这条:
            总 = sum(1 for x in 冲突 if x[0] == f["名"]) + \
                 sum(1 for _ in ())  # 占位,真正的分母在下面用 对过 兜
            档[f["名"]] = _分档(len(这条), max(对过, len(这条)))

    ck(not 冲突, "同一个事实的几个落点不打架",
       "；".join(f'{n}#{k}:' + "、".join(f"{a}={b!r}" for a, b in v.items())
                 for n, k, v in 冲突[:3])
       + " —— **不许投票**:三比一也是矛盾。真正的结论是这条数据错了,要业务核"
       + "".join(f"\n     ⚠️ 「{n}」看着像**{档[n][0]}**问题:{档[n][1]}" for n in 档)
       if 冲突 else f"{对过} 个键逐个对过,新的打架 0 处"
       + (f",另有 {len(已知)} 处**登记在案的已知打架**(等业务判)" if 已知 else ""))

    ck(not 该消的, "登记的已知打架确实还在打",
       "、".join(该消的[:4]) + (f"  ……还有 {len(该消的)-4} 处(共 {len(该消的)})"
                                if len(该消的) > 4 else "")
       + " —— **已经不打架了,该从「已知打架」里删掉**"
       if 该消的 else (f"{len(已知)} 处都还在打" if 已知 else "没有登记过已知打架"))

    for n, k, v, 记 in 已知[:5]:
        报(f'     ⚠️ 已知打架 {n}#{k}:' + "、".join(f"{a}={b!r}" for a, b in v.items()))
        报(f'        等谁:{记.get("等谁", "(没写)")} · {记.get("为什么还没修", "")}')
    return 失败


def 自测():
    """咬合:三条破坏点各自都要红,而且红的必须是指定那一条。"""
    import io, contextlib, tempfile
    d = tempfile.mkdtemp()
    db = os.path.join(d, "t.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE p(k TEXT PRIMARY KEY, 名 TEXT, 性别 TEXT)")
    c.executemany("INSERT INTO p VALUES(?,?,?)",
                  [("a", "童款襦裙", "童"), ("b", "齐胸襦裙", "成"), ("c", "童款马面", "童")])
    c.commit()

    def 声明(按名="LIKE '%童%'", 落点数=2):
        f = {"名": "大人还是小孩", "落点": [
            {"名": "名字", "sql": f"SELECT k, CASE WHEN 名 {按名} THEN '童' ELSE '成' END FROM p"},
            {"名": "性别", "sql": "SELECT k, 性别 FROM p"}]}
        return {"事实": [{"名": f["名"], "落点": f["落点"][:落点数]}]}

    def 跑(s):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            失败 = 查(sqlite3.connect(db), s)
        return 失败, buf.getvalue()

    坏 = []

    def 关(名, 期望红, s):
        失败, out = 跑(s)
        if not 失败:
            坏.append(f"{名}:改坏了却没红")
        elif 期望红 not in 失败:
            坏.append(f"{名}:红的不是「{期望红}」,是「{'/'.join(失败)}」")
        else:
            print(f"  ✓ 咬合:{名} → 红的正是「{期望红}」")

    print("跨字段一致 · 咬合")
    失败, _ = 跑(声明())
    if 失败:
        print(f"  ✗ 对照就不绿:{失败}")
        坏.append("对照不绿")
    else:
        print("  ✓ 对照:两个信号一致时是绿的")

    # ① 把一行改成打架
    c.execute("UPDATE p SET 性别='成' WHERE k='a'"); c.commit()
    关("把某一行的一个信号改成和另一个不一样", "同一个事实的几个落点不打架", 声明())
    c.execute("UPDATE p SET 性别='童' WHERE k='a'"); c.commit()
    # ② 落点读不到东西(条件写反成永假)
    关("把某个落点的 SQL 改成读不到东西", "每个落点都读到了东西",
       {"事实": [{"名": "大人还是小孩", "落点": [
           {"名": "名字", "sql": "SELECT k, '童' FROM p WHERE 1=0"},
           {"名": "性别", "sql": "SELECT k, 性别 FROM p"}]}]})
    # ③ 只剩一个落点
    关("把某个事实的落点删到只剩一个", "每个事实至少有两个落点", 声明(落点数=1))

    for x in 坏:
        print(f"  ✗ {x}")
    print((f"{R}❌ 一致性咬合 {len(坏)} 条不过{D}") if 坏 else f"{G}✅ 一致性咬合:三条都咬得动{D}")
    return 1 if 坏 else 0


def main():
    p = argparse.ArgumentParser(description="同一个事实的几个落点必须一致(不许投票)")
    p.add_argument("--db")
    p.add_argument("--声明", default=默认声明)
    p.add_argument("--自测", action="store_true")
    a = p.parse_args()
    if a.自测:
        return 自测()
    if not a.db:
        raise SystemExit("要么 --db <库>,要么 --自测")
    if not os.path.isfile(a.声明):
        print(f"     ℹ️ 没有声明文件({a.声明})—— **没东西可验**,不是验过了")
        return 0
    print("同一个事实的几个落点必须一致")
    失败 = 查(sqlite3.connect(a.db), json.load(open(a.声明, encoding="utf-8")))
    print((f"{R}❌ 跨字段一致 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 跨字段一致{D}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
