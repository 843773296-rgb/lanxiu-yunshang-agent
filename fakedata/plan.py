#!/usr/bin/env python3
"""方案层 —— 把「观察到的事实」变成一份**人能审、机器能跑**的造数方案。

## 为什么要有「方案」这个中间物

有两种做法。第一种是让模型逐条把数据编出来:

    模型 → "生成 200 个客户" → 一条一条吐 JSON

慢、贵、**不可复现**(跑两次结果不一样)、上不了量(20 万条不可能)。
更要命的是没有可审的中间物 —— 数据错了只能回去重问模型。

这里走第二种:模型/推断只产出一份**方案**,由确定性程序去执行它。

    推断 → 方案(JSON,可读可改可进 git) → 程序 → 20 万条

代价是方案本身要设计好,而且一旦规则写错就是**批量**错。
换来的是:秒级出数、要多少有多少、同一个种子永远出同一批数据(bug 能复现)、
方案能 diff 能 review —— 下次跑根本不用再调模型。

**做一次,跑一万次。** 这是这个工具所有设计的出发点。

## 两份产物,给两种读者

  · `plan.json` —— 机器读。生成器唯一的输入。
  · 方案预览(Markdown) —— 人读。**它才是真正要被审的东西**。
    工具最容易犯的错是把方案做成黑盒:灌完了,数据在库里了,没人知道它凭什么这么造。
    所以「哪些关系是猜的」「哪些列它没把握」必须印在最显眼的地方。

## 灌入顺序:拓扑排序,以及环怎么办

先有客户才能有订单 —— 表之间的依赖决定了灌入顺序,拓扑排序解决。
麻烦的是**环**:账户指向「本人着装人」,着装人又指向账户。这时候没有合法顺序。
解法是两阶段:先把环上那条**可空**的外键留空插进去,全部插完再回填 UPDATE。
选哪条边来断,优先选可空的、可信度低的 —— 断错了代价最小。
"""
import os, sys, json, collections

# 语义类型 → 生成器名。生成器的实现在 gen.py,这里只负责挑。
SEM2GEN = {
    "cn_mobile": "cn_mobile", "cn_name": "cn_name", "email": "email",
    "date": "date", "datetime": "datetime", "money": "money",
    "province": "province", "city": "city", "district": "district",
    "address": "address", "url": "url", "json": "json_blob",
    "coded_id": "coded_id", "long_text": "long_text", "percent": "percent",
    "small_int": "small_int", "enum": "enum", "fk": "fk",
    "int": "number", "real": "number", "text": "text",
    "datetime_": "datetime", "blob": "text",
}

def _gen_for(cname, cf, fk):
    """给一列挑生成策略。**猜不准就明说**,别悄悄用个默认值糊过去。"""
    if fk:
        g = {"gen": "fk", "table": fk["table"], "column": fk["column_ref"],
             "shape": fk.get("shape"), "confidence": fk["confidence"],
             "source": fk["source"], "overlap": fk.get("overlap"),
             "alternatives": fk.get("alternatives", [])}
        if fk["confidence"] != "高":
            g["需确认"] = f'这条关系是{fk["source"]}推出来的,不是库里明写的'
        return g
    if cf["pk"]:
        return {"gen": "pk", "style": "coded" if cf["kind"] == "text" else "int_seq"}
    sem = cf.get("semantic", cf["kind"])
    g = {"gen": SEM2GEN.get(sem, "text")}
    if sem == "enum":     g["dist"] = cf.get("enum", {})
    if "range" in cf:     g["range"] = cf["range"]
    if "len" in cf:       g["len"] = cf["len"]
    if cf.get("unique"):  g["unique"] = True
    if cf.get("null_rate"): g["null_rate"] = cf["null_rate"]
    if cf.get("comment"): g["注释"] = cf["comment"]
    # 自由文本 + 无注释 + 无枚举 = 真的猜不准,标出来等人或模型补
    if g["gen"] == "text" and not cf.get("comment") and cf.get("distinct", 0) > 24:
        g["需确认"] = "自由文本,列名和取值都看不出语义,只能造随机串"
    if cf.get("confidence") == "低":
        g.setdefault("需确认", "源库这张表没数据,只能靠列名猜")
    return g


def topo_order(tables, fks):
    """拓扑排序。返回 (顺序, 要断的边)。

    Kahn 算法。环上断边的挑选顺序:可空 > 不可空,低可信 > 高可信 ——
    断一条可空的边,代价只是先插 NULL 再回填;断不可空的边就得造临时值,脏得多。
    """
    dep = {t: set() for t in tables}          # 我依赖谁
    for child, ks in fks.items():
        for k in ks:
            if k["table"] in tables and k["table"] != child:
                dep[child].add(k["table"])
    order, deferred, remaining, broken = [], [], dict(dep), set()
    while remaining:
        ready = sorted(t for t, d in remaining.items() if not (d & remaining.keys()))
        if not ready:
            # 成环了。在剩下的边里挑一条最该断的。
            # **已经断过的边必须排除** —— 第一版没排除,断完又把它当候选捞回来,
            # 于是每轮断同一条边、每轮都断不干净,死循环。
            # 症状很温和:不报错、不刷屏,就是不结束。查了才发现是「断边」和
            # 「记住断过」少了后半句 —— 和记录仪那个坑同一类:**漏掉的表现是「一切正常」**。
            cands = []
            for t in remaining:
                for k in fks.get(t, []):
                    key = (t, k["column"], k["table"])
                    if k["table"] in remaining and k["table"] != t and key not in broken:
                        cands.append((k.get("nullable", True), k["confidence"] != "高", t, k))
            if not cands:
                order += sorted(remaining); break      # 断无可断,兜底:剩下的按名字排
            cands.sort(key=lambda x: (not x[0], not x[1]))   # 可空优先、低可信优先
            _, _, t, k = cands[0]
            broken.add((t, k["column"], k["table"]))
            k["deferred"] = True
            deferred.append({"table": t, "column": k["column"],
                             "ref": f'{k["table"]}.{k["column_ref"]}',
                             "why": "成环,先插空再回填"})
            # 这张表对目标表的依赖,只有在**没有别的活边**指过去时才能真正解除
            if not any(x["table"] == k["table"] and (t, x["column"], x["table"]) not in broken
                       for x in fks.get(t, [])):
                remaining[t].discard(k["table"])
            continue
        order += ready
        for t in ready: remaining.pop(t)
    return order, deferred


def build(facts, seed=20260906, scale=1.0, counts=None, tables=None, marker="SYN-"):
    counts = counts or {}
    names = tables or sorted(facts["tables"])
    fkmap = {}
    for tn in names:
        ks = []
        for k in facts["tables"][tn]["fks"]:
            if k["table"] in names:
                cf = facts["tables"][tn]["columns"].get(k["column"], {})
                ks.append(dict(k, nullable=cf.get("nullable", True)))
        fkmap[tn] = ks
    order, deferred = topo_order(set(names), fkmap)

    plan = {"seed": seed, "dialect": facts["dialect"], "source": facts["source"],
            "marker": {"strategy": "id_prefix", "prefix": marker,
                       "why": "每条假数据的主键都带这个前缀,一条 DELETE 就能清干净"},
            "order": order, "deferred_fks": deferred, "tables": {}, "assertions": []}

    for tn in order:
        tf = facts["tables"][tn]
        n = counts.get(tn, max(1, int(round(tf["rows"] * scale)))) if tf["rows"] \
            else counts.get(tn, 10)
        byfk = {k["column"]: k for k in fkmap[tn]}
        plan["tables"][tn] = {
            "count": n, "pk": tf["pk"], "源行数": tf["rows"],
            "columns": {c: _gen_for(c, cf, byfk.get(c)) for c, cf in tf["columns"].items()},
        }
    plan["assertions"] = _assertions(facts, names, fkmap)
    return plan


def _assertions(facts, names, fkmap):
    """自动派生断言 —— 灌完立刻自检。

    数据库直连绕过了业务层校验,这是优点也是陷阱:能造出「数据库允许但业务不可能」的数据,
    然后你花半天 debug 一个根本不存在的 bug。
    所以这一层是数据库直连方案能不能用的**分水岭**,不是可选项。

    这里派生四类,全部是「查出来必须是 0 行」:
      孤儿引用 / 该非空的却空了 / 该唯一的却重了 / 枚举外的野值。
    时间线类(下单时间不能晚于发货时间)靠列名对推,标成候选,需要人或模型确认。
    """
    out = []
    TIME_PAIRS = [("created", "updated"), ("created", "paid_at"), ("paid_at", "shipped_at"),
                  ("shipped_at", "done_at"), ("created", "last_interact")]
    for tn in names:
        tf = facts["tables"][tn]
        for k in fkmap[tn]:
            out.append({"名": f'{tn}.{k["column"]} 不能有孤儿引用', "表": tn, "类": "孤儿",
                        "sql": f'select count(*) from "{tn}" where "{k["column"]}" is not null '
                               f'and "{k["column"]}" not in (select "{k["column_ref"]}" from "{k["table"]}")',
                        "期望": 0})
        for cn, cf in tf["columns"].items():
            if not cf["nullable"]:
                out.append({"名": f"{tn}.{cn} 不可为空", "表": tn, "类": "非空",
                            "sql": f'select count(*) from "{tn}" where "{cn}" is null', "期望": 0})
            if cf.get("unique"):
                out.append({"名": f"{tn}.{cn} 必须唯一", "表": tn, "类": "唯一",
                            "sql": f'select count(*) from (select "{cn}" from "{tn}" '
                                   f'where "{cn}" is not null group by 1 having count(*)>1)',
                            "期望": 0})
            if cf.get("enum"):
                vals = ",".join("'" + str(v).replace("'", "''") + "'" for v in cf["enum"])
                out.append({"名": f"{tn}.{cn} 只能取已知的 {len(cf['enum'])} 个值", "表": tn, "类": "枚举",
                            "sql": f'select count(*) from "{tn}" where "{cn}" is not null '
                                   f'and cast("{cn}" as text) not in ({vals})', "期望": 0})
        cols = set(tf["columns"])
        for a, b in TIME_PAIRS:
            if a in cols and b in cols:
                out.append({"名": f"{tn}: {b} 不该早于 {a}", "表": tn, "类": "时间线(候选)",
                            "sql": f'select count(*) from "{tn}" where "{a}" is not null '
                                   f'and "{b}" is not null and "{b}" < "{a}"',
                            "期望": 0, "需确认": "按列名对推的,业务上不一定成立"})
    return out


def to_markdown(plan, facts=None):
    """人读的那一份。**需要人确认的东西排在最前面** —— 排在后面等于没写。"""
    L = []
    A = L.append
    A(f'# 造数方案 · {plan["source"]}\n')
    A(f'> 种子 `{plan["seed"]}` —— 同一个种子永远造出同一批数据,bug 能复现。')
    A(f'> 假数据主键前缀 `{plan["marker"]["prefix"]}`,一条 DELETE 清得干净。\n')

    # 分三类。混在一张表里会被空表刷屏 —— 「这张表源库没数据」是**整表**的事实,
    # 逐列重复 40 遍,真正要看的那几条就被埋了。审阅体验本身就是这个产品的一部分。
    guessed_fk, empty_tabs, unknown_col = [], {}, []
    for tn, tp in plan["tables"].items():
        for cn, g in tp["columns"].items():
            if "需确认" not in g: continue
            if g["gen"] == "fk":                      guessed_fk.append((tn, cn, g))
            elif tp["源行数"] == 0:                    empty_tabs[tn] = tp
            else:                                      unknown_col.append((tn, cn, g))

    A(f'## ⚠️ 需要你确认的\n')
    A(f'**{len(guessed_fk)} 条表关系是推出来的**,库里没明写。推错一条,整批数据的 join 就是歪的。\n')
    if guessed_fk:
        A("| 关系 | 靠什么推的 | 值重叠 | 备选 |")
        A("|---|---|---:|---|")
        for tn, cn, g in guessed_fk:
            alt = ", ".join(g.get("alternatives", [])) or "—"
            A(f'| `{tn}.{cn}` → `{g["table"]}.{g["column"]}` | {g["source"]} | '
              f'{g.get("overlap", 0):.0%} | {alt} |')
    A("")
    if empty_tabs:
        A(f'**{len(empty_tabs)} 张表源库是空的**,只能照列名猜。要它准,得给一个有数据的库当样本源。\n')
        A("`" + "`  `".join(sorted(empty_tabs)) + "`\n")
    if unknown_col:
        A(f'**{len(unknown_col)} 列看不出语义**,只能造随机串 —— 能跑通,但不像真的。\n')
        by = {}
        for tn, cn, _g in unknown_col: by.setdefault(tn, []).append(cn)
        for tn in sorted(by): A(f'- `{tn}`: ' + ", ".join(f'`{c}`' for c in sorted(by[tn])))
    A("")

    if plan["deferred_fks"]:
        A(f'## 环:{len(plan["deferred_fks"])} 条边要两阶段灌\n')
        for d in plan["deferred_fks"]:
            A(f'- `{d["table"]}.{d["column"]}` → `{d["ref"]}` —— {d["why"]}')
        A("")

    A(f'## 灌入顺序({len(plan["order"])} 张表)\n')
    A("拓扑排序的结果:先有父亲才有孩子。\n")
    A("```")
    A(" → ".join(plan["order"][:40]) + (" → …" if len(plan["order"]) > 40 else ""))
    A("```\n")

    A("## 每张表\n")
    A("| 表 | 造多少 | 源库有 | 关系 | 引用形状(父亲有几个孩子) |")
    A("|---|---:|---:|---|---|")
    for tn in plan["order"]:
        tp = plan["tables"][tn]
        fks = [(cn, g) for cn, g in tp["columns"].items() if g["gen"] == "fk"]
        rel = "<br>".join(f'`{cn}`→`{g["table"]}`' for cn, g in fks[:3]) or "—"
        sh = ""
        for _cn, g in fks:
            if g.get("shape"):
                sh = " ".join(f'{k}:{v:.0%}' for k, v in g["shape"].items() if v); break
        A(f'| `{tn}` | {tp["count"]} | {tp["源行数"]} | {rel} | {sh or "—"} |')
    A("")
    kinds = collections.Counter(a["类"] for a in plan["assertions"])
    A(f'## 灌完自检:{len(plan["assertions"])} 条断言\n')
    A("每条都是「查出来必须是 0 行」。\n")
    for k, v in kinds.most_common(): A(f'- {k}:{v} 条')
    return "\n".join(L)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import schema as S, discover as D
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "backend", "lanxiu.db")
    conn = S.connect(tgt); sc = conn.reflect()
    f = D.discover(conn, sc)
    p = build(f, scale=0.1)
    print(to_markdown(p)[:3000])
    print(f'\n... 断言 {len(p["assertions"])} 条 / 表 {len(p["tables"])} 张 / 环 {len(p["deferred_fks"])} 条')
