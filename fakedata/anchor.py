#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付物锚定 —— **一个值一旦被外面消费掉,重建就不许再动它。**

    python3 fakedata/anchor.py 钉 --db <库> --表 product --键列 spu --列 color \\
            --键 lxys_1,lxys_2 --消费方 "出图清单" --为什么 "图已交付,图上的颜色就是事实"
    python3 fakedata/anchor.py 验 --db <库>          # 逐条和库里对
    python3 fakedata/anchor.py 看                     # 钉了哪些、谁消费的

## 这和 `protect.py` 不是一回事

`protect.py` 管的是**灌数据时别碰这些行**(夹具、被真值引用的行)。
这里管的是**重建之后这些值还得是原来那个** —— 两个问题的时间点不同:

    protect   灌入的那一刻   「别写坏它」
    anchor    重建之后       「它自己变了没有」

后者防的是一类特别安静的事故:**没有人去改那个值,它是被算法算出来的,
而算法的输入变了。**

## 为什么需要它:图一旦交付,颜色就是事实

澜绣云裳 2026-09-20:38 款商品里 22 款换了颜色,**其中 6 款的图已经交付出去了**。
没有人改过颜色,它一直是算出来的 —— 原来按 `插入序号*3 + hash(款号)`,
改了两行造数据的代码,插入序号变了,颜色跟着整体偏移。

> 客户看到的是**图**,系统按**数据**发货。
> 两边对不上的时候,**页面上一点看不出来** —— 图是好看的,数据是自洽的。

修行级稳定(见 `stable.py`)能挡住下一次,但**挡不住已经发生的那次**:
那 6 张图在外面,数据得跟着图走,不是反过来。所以要有一张钉子表,
而且钉子上要写清**谁消费的、为什么钉**——

## 钉子上必须写「谁消费的」,不然它会变成一张没人敢动的表

只记「表.列.键 = 值」的话,半年后没人知道这颗钉子还算不算数,
于是它永远不会被拔掉,慢慢攒成一堆挡路的豁免
(和 `stable.py` 里「囤积的豁免和真豁免长得一模一样」是同一件事)。

所以每颗钉子都带 `消费方` 和 `为什么`,而且**拔钉要留痕**:
从 `钉住` 里删掉不算拔,要往 `解钉` 里写一条,写明什么时候、因为什么。
`验` 会把解钉记录一并打出来。
"""
import argparse, datetime, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# ⚠️ **钉子表不能放 `.fakedata/`** —— 那是工厂的输出目录(gitignore,随时清掉)。
# 钉子表是**声明**不是产物:它记的是「外面已经拿走了哪些值」,
# 清掉之后 `验` 会一本正经地说「没东西可验」,而那和「都对」长得一模一样。
默认锚文件 = os.path.join(HERE, "锚定.json")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ("把库里某个钉住的值改掉", "钉住的值和库里一致"),
    ("把库里某个钉住的行删掉", "钉住的行都还在"),
    ("从钉住表里直接删掉一条(不写解钉记录)", "拔钉留了痕"),
]


def 读锚(路径):
    if not os.path.isfile(路径):
        return {"说明": "", "锚": [], "解钉": []}
    d = json.load(open(路径, encoding="utf-8"))
    d.setdefault("锚", []); d.setdefault("解钉", [])
    return d


def 写锚(路径, d):
    os.makedirs(os.path.dirname(路径), exist_ok=True)
    json.dump(d, open(路径, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _取(conn, 表, 键列, 列, 键=None, 取法=None, 取法模块=None):
    """现在库里是什么值。`取法` 是一条自己写的 SQL(要返回两列:键、值)。

    为什么要留这个口子:真实的「一个值」常常不是 `表.列` 那么直——
    澜绣云裳那份颜色钉住表,键是款号(spu),值却在 `sku` 表上,
    而且取的是「按编码排第一个 sku 的颜色」。没有这个口子,
    通用引擎就只能覆盖最规整的那一类,**而要钉的恰恰常常是不规整的那些**。
    """
    if 取法模块:
        # `路径.py:函数名` —— 函数收一个连接,返回 {键: 值}。
        # **为什么要有这个口子**:锚定比的是「消费方看到的那个值」,
        # 而它常常是算出来的(澜绣的定制品颜色就是按款号挑的)。
        # 在锚文件里用 SQL 把规则重写一遍 = 造第二份实现,
        # 而两份实现分家的时候,检查会说绿、页面是另一个样子。
        路径, _, 函数名 = 取法模块.partition(":")
        import importlib.util
        full = 路径 if os.path.isabs(路径) else os.path.join(ROOT, 路径)
        spec = importlib.util.spec_from_file_location("_取法_" + 函数名, full)
        m = importlib.util.module_from_spec(spec)
        sys.path.insert(0, os.path.dirname(full))
        spec.loader.exec_module(m)
        d = {str(k): v for k, v in getattr(m, 函数名)(conn).items()}
        return {k: d[k] for k in 键 if k in d} if 键 else d
    if 取法:
        rows = conn.execute(取法).fetchall()
    else:
        rows = conn.execute(f'SELECT "{键列}", "{列}" FROM "{表}"').fetchall()
    d = {str(k): v for k, v in rows}
    return {k: d[k] for k in 键 if k in d} if 键 else d


def _组的值(组):
    """这一组钉住的值。**优先读外部真相源,不在锚文件里存副本。**

    存副本的下场这个项目见过太多次:两份同样的东西,改了一份忘了另一份,
    而**不一致时两边都看着很正常**。所以 `值来自` 指向那份真的,
    格式是 `路径#键路径`(如 `backend/图色钉住.json#钉住`)。
    """
    来 = 组.get("值来自")
    if not 来:
        return 组.get("值") or {}
    路径, _, 键路径 = 来.partition("#")
    p = 路径 if os.path.isabs(路径) else os.path.join(ROOT, 路径)
    if not os.path.isfile(p):
        raise SystemExit(f"❌ 锚文件指向的真相源不在:{p}\n"
                         f"   源没了就不是「验过了」,是没东西可验 —— 这里直接拒绝。")
    d = json.load(open(p, encoding="utf-8"))
    for seg in [x for x in 键路径.split("/") if x]:
        d = d[seg]
    return {str(k): v for k, v in d.items()}


def 钉(a):
    conn = sqlite3.connect(a.db)
    键 = [x.strip() for x in a.键.split(",")] if a.键 else None
    值 = _取(conn, a.表, a.键列, a.列, 键)
    if 键:
        缺 = [k for k in 键 if k not in 值]
        if 缺:
            # **点名要钉的键在库里找不到** —— 这多半是键打错了,
            # 静默少钉几条的话,`验` 以后永远说「都对」,而它根本没在看那几条。
            raise SystemExit(f"❌ 这些键在 {a.表} 里找不到:{'、'.join(缺[:6])}\n"
                             f"   少钉一条和钉对了在输出上长得一样,所以这里直接拒绝。")
    d = 读锚(a.锚文件)
    旧 = next((x for x in d["锚"]
               if (x["表"], x["键列"], x["列"]) == (a.表, a.键列, a.列)), None)
    if 旧:
        # 已经有这一组的钉子了 —— **覆盖已有的键要明说**,
        # 因为那意味着「外面那件交付物也一起换了」,不该顺手发生。
        改了 = {k: (旧["值"][k], v) for k, v in 值.items()
                if k in 旧["值"] and 旧["值"][k] != v}
        if 改了 and not a.强制:
            print(f"{R}❌ 这 {len(改了)} 条已经钉过,而且值不一样:{D}")
            for k, (o, n) in list(改了.items())[:6]:
                print(f"   {k}: 钉的是 {o!r},现在库里是 {n!r}")
            raise SystemExit("   钉子改了,就意味着外面那件交付物也得跟着改。\n"
                             "   确认要覆盖再加 --强制。")
        旧["值"].update({k: v for k, v in 值.items()})
        旧["钉于"] = datetime.date.today().isoformat()   # 真实时钟:钉子上记的是人钉它的那一天
    else:
        d["锚"].append({"表": a.表, "键列": a.键列, "列": a.列,
                        "消费方": a.消费方, "为什么": a.为什么,
                        "钉于": datetime.date.today().isoformat(),  # 真实时钟:同上
                        "值": 值})
    写锚(a.锚文件, d)
    print(f"✅ 钉了 {len(值)} 条:{a.表}.{a.列}(键 {a.键列})→ {a.锚文件}")
    print(f"   消费方:{a.消费方} · 为什么:{a.为什么}")
    return 0


def 验(a):
    d = 读锚(a.锚文件)
    conn = sqlite3.connect(a.db)
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print("交付物锚定 · 被外面消费过的值,重建后还得是那个")
    总 = sum(len(_组的值(x)) for x in d["锚"])
    # 样本量先报:**「钉的都对」和「一颗钉子都没有」在输出上长得一样**
    if not 总:
        print(f"     ℹ️ 这份锚文件里一颗钉子都没有({a.锚文件})—— "
              f"下面的性质**没东西可验**,不是验过了")
        print(f"{G}✅ 交付物锚定(没东西可验){D}")
        return 0
    ck(True, "样本量:钉住的值", f"{总} 条 / {len(d['锚'])} 组")

    丢, 变 = [], []
    for 组 in d["锚"]:
        try:
            现 = _取(conn, 组["表"], 组["键列"], 组["列"],
                     取法=组.get("取法"), 取法模块=组.get("取法模块"))
        except sqlite3.Error as e:
            丢.append(f'{组["表"]}.{组["列"]}:这张表/列读不了({e})')
            continue
        for k, v in _组的值(组).items():
            if k not in 现:
                # **行没了和值变了是两回事**:前者是重建把它删了/键变了,
                # 后者是算法算出了别的。合在一起报,人会往错的方向查。
                丢.append(f'{组["表"]}#{k}')
            elif str(现[k]) != str(v):
                变.append((组, k, v, 现[k]))

    ck(not 丢, "钉住的行都还在",
       "、".join(丢[:5]) + " —— **行不见了**(键变了或被删了),不是值变了"
       if 丢 else f"{总} 条都找得到")

    ck(not 变, "钉住的值和库里一致",
       "；".join(f'{g["表"]}#{k} {g["列"]}:钉的是 {v!r},库里是 {n!r}'
                 f'(消费方:{g["消费方"]})' for g, k, v, n in 变[:4])
       + " —— **外面那件交付物已经按钉住的值做出去了**,"
         "要么把库改回去,要么连交付物一起换掉并重新钉"
       if 变 else f"{总} 条逐条对上")

    # 拔钉留痕:`验` 不知道有没有人从文件里直接删掉过一条 ——
    # 它只看得见现在还在的。能查的是「解钉记录写全了没有」。
    坏解钉 = [x for x in d["解钉"]
              if not all(x.get(k) for k in ("表", "列", "键", "何时", "为什么"))]
    ck(not 坏解钉, "拔钉留了痕",
       f"{len(坏解钉)} 条解钉记录没写全(要有 表/列/键/何时/为什么)"
       if 坏解钉 else (f"{len(d['解钉'])} 条解钉记录都写全了" if d["解钉"]
                      else "还没有拔过钉子"))
    for x in d["解钉"][:3]:
        print(f'     ℹ️ 拔过:{x.get("表")}.{x.get("列")} #{x.get("键")} '
              f'({x.get("何时")}) —— {x.get("为什么")}')

    print((f"{R}❌ 交付物锚定 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 交付物锚定{D}")
    return 1 if 失败 else 0


def 看(a):
    d = 读锚(a.锚文件)
    if not d["锚"]:
        print(f"还没钉过东西({a.锚文件})")
        return 0
    print(f"锚文件:{a.锚文件}")
    for 组 in d["锚"]:
        vs = _组的值(组)
        print(f'\n  {组["表"]}.{组["列"]}(键 {组["键列"]}) · {len(vs)} 条 · 钉于 {组["钉于"]}')
        if 组.get("值来自"): print(f'    值来自:{组["值来自"]}(不存副本)')
        print(f'    消费方:{组["消费方"]}')
        print(f'    为什么:{组["为什么"]}')
        for k, v in list(vs.items())[:5]:
            print(f"      {k} = {v!r}")
        if len(vs) > 5:
            print(f"      …… 还有 {len(vs) - 5} 条")
    return 0


def 自测(a):
    """**把三条咬合跑出来**,而不是写在注释里。

    写在注释里的咬合会和本体分家:改了本体忘了改咬合,咬合就慢慢烂掉 ——
    而烂掉的样子和好着的样子一模一样(这是 handoff 门禁那边学到的)。

    每一条都要过三关:对照先绿 → 改坏之后红 → **红的必须是指定那一条**。
    只验「红了」是不够的:红错了理由,照着那条去查是白费功夫。
    """
    import io, tempfile, contextlib
    d = tempfile.mkdtemp()
    db = os.path.join(d, "t.db")
    锚 = os.path.join(d, "锚定.json")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE product(spu TEXT PRIMARY KEY, color TEXT)")
    c.executemany("INSERT INTO product VALUES(?,?)",
                  [("s1", "藕荷"), ("s2", "天青"), ("s3", "竹青")])
    c.commit(); c.close()

    class A: pass
    钉参 = A(); 钉参.db = db; 钉参.锚文件 = 锚; 钉参.表 = "product"
    钉参.键列 = "spu"; 钉参.列 = "color"; 钉参.键 = "s1,s2,s3"
    钉参.消费方 = "出图清单"; 钉参.为什么 = "图已交付,图上的颜色就是事实"; 钉参.强制 = False
    验参 = A(); 验参.db = db; 验参.锚文件 = 锚

    def 跑验():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = 验(验参)
        return rc, buf.getvalue()

    with contextlib.redirect_stdout(io.StringIO()):
        钉(钉参)

    坏 = []

    def 关(名, 期望红, 改, 还原):
        rc0, _ = 跑验()
        if rc0 != 0:
            坏.append(f"{名}:对照就不绿"); return
        改()
        rc1, out = 跑验()
        if rc1 == 0:
            坏.append(f"{名}:改坏了却没红 —— **这条检查看不见这个破坏**")
        elif f"❌ {期望红}" not in out:
            红的 = [l.strip() for l in out.splitlines() if l.strip().startswith("❌")]
            坏.append(f"{名}:红的不是「{期望红}」,是「{'/'.join(红的)[:60]}」")
        else:
            print(f"  ✓ 咬合:{名} → 红的正是「{期望红}」")
        还原()
        rc2, _ = 跑验()
        if rc2 != 0:
            坏.append(f"{名}:还原之后没回到绿")

    def sql(q, *v):
        cc = sqlite3.connect(db); cc.execute(q, v); cc.commit(); cc.close()

    print("交付物锚定 · 咬合")
    关("把库里某个钉住的值改掉", "钉住的值和库里一致",
       lambda: sql("UPDATE product SET color=? WHERE spu=?", "玄色", "s2"),
       lambda: sql("UPDATE product SET color=? WHERE spu=?", "天青", "s2"))
    关("把库里某个钉住的行删掉", "钉住的行都还在",
       lambda: sql("DELETE FROM product WHERE spu=?", "s3"),
       lambda: sql("INSERT INTO product VALUES(?,?)", "s3", "竹青"))

    def 加坏解钉():
        j = 读锚(锚); j["解钉"] = [{"表": "product", "列": "color", "键": "s9"}]; 写锚(锚, j)

    def 去坏解钉():
        j = 读锚(锚); j["解钉"] = []; 写锚(锚, j)
    关("写了一条没写全的解钉记录", "拔钉留了痕", 加坏解钉, 去坏解钉)

    # 反向那一半:空锚文件必须说「没东西可验」,不能报成「都对」
    空 = A(); 空.db = db; 空.锚文件 = os.path.join(d, "空.json")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        验(空)
    if "没东西可验" not in buf.getvalue():
        坏.append("空锚文件没说「没东西可验」—— 和「都对」分不开")
    else:
        print("  ✓ 空锚文件明说「没东西可验」,不冒充通过")

    for x in 坏:
        print(f"  ✗ {x}")
    print((f"{R}❌ 锚定咬合 {len(坏)} 条不过{D}") if 坏 else f"{G}✅ 锚定咬合:三条都咬得动{D}")
    return 1 if 坏 else 0


def main():
    p = argparse.ArgumentParser(description="交付物锚定:被外面消费过的值不许再动")
    p.add_argument("--锚文件", default=默认锚文件)
    sub = p.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("钉"); a1.set_defaults(fn=钉)
    a1.add_argument("--db", required=True)
    a1.add_argument("--表", required=True); a1.add_argument("--键列", required=True)
    a1.add_argument("--列", required=True); a1.add_argument("--键")
    a1.add_argument("--消费方", required=True, help="谁把这个值拿出去用了(出图清单 / 评测基线 / 发出去的报告)")
    a1.add_argument("--为什么", required=True, help="为什么它不许再动")
    a1.add_argument("--强制", action="store_true")
    a2 = sub.add_parser("验"); a2.set_defaults(fn=验); a2.add_argument("--db", required=True)
    a3 = sub.add_parser("看"); a3.set_defaults(fn=看)
    a4 = sub.add_parser("自测", help="跑咬合:每条检查都故意改坏一次,确认红的是它"); a4.set_defaults(fn=自测)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
