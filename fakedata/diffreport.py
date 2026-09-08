#!/usr/bin/env python3
"""差集清单 —— 「数据库允许、业务不允许」的那一份,给评测那条线用。

    python3 fakedata/diffreport.py            # 打自测靶子(离线,不碰任何真实服务)
    python3 fakedata/diffreport.py <spec.json> # 打真实服务(规格自己给)

## 这份清单是什么

数据库直连绕过业务层,而业务规则**大量地不在 schema 里**。
拿方案造出来的数据去打写接口,**每被拒一条,就等于问出了一条 schema 里看不见的规则**。

每条包含四样东西,合起来正好够写一道负向评测题:

| 字段 | 是什么 | 给题目提供什么 |
|---|---|---|
| `码` | 业务错误码(DUP_PHONE / NO_BACKFILL) | 归类锚点。文案带 id 和人名,会漂;码不会 |
| `最小请求体` | 逐字段删到不能再删,**且保持同一个码** | 题面 —— 干净、没有无关字段 |
| `库这边` | 这几个字段在数据库里的约束 | **差集的另一半**,题目的张力就在这 |
| `接口说` | 拒绝原文 | 标准答案的依据(它来自 backend/rules.py) |

「最小」必须保持**同一个码**,不能只要求"还是失败":
`DUP_PHONE` 的请求体删掉 name 之后照样失败,但失败的是 `NEED_NAME` —— 那是**另一条规则**,
拿它当题面,问的就不是原来那件事了。

## 为什么默认打的是自测靶子

真实服务(:8760)写的是 `backend/lanxiu.db` —— 四个数据检查的真值源,不能碰(闸门也拦着)。
而靶子的**校验是只读 import `backend/rules.py` 的那一份**,
所以拒绝理由和真实业务规则是同一个来源,不是我编的。
"""
import datetime as dt
import json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, gen as G, infer_llm as I, apidrive

WANT = ("NEED_NAME", "NO_BACKFILL", "DUP_PHONE")   # 先给最清楚的这几条


def build(spec=None, scale=0.3, driven=("customer", "appointment"), log=print):
    src = os.path.join(ROOT, "backend", "lanxiu.db")
    tmp = os.path.join(tempfile.mkdtemp(), "diffreport_test.db")
    shutil.copy(src, tmp)
    conn = S.connect(tmp)
    facts = D.discover(conn, conn.reflect())
    ovp = os.path.join(ROOT, ".fakedata", "lanxiu.db-20260906.overlay.json")
    if os.path.exists(ovp):
        ov, _d = I.validate(json.load(open(ovp, encoding="utf-8")), facts,
                            P.build(facts, scale=0.01))
        facts, _lg = P.apply_overlay(facts, ov)
    # 接口这条路必须**按要驱动的表集单独建方案** —— 全局的环判定会污染局部
    pl = P.build(facts, scale=scale, tables=list(driven))
    made, _man = G.generate(pl, conn)

    stop = None
    if spec is None:
        import apimock
        base, _store, stop = apimock.serve()
        spec = dict(apimock.SPEC, base=base)
        log(f"  打自测靶子 {base}(校验只读 import backend/rules.py)")

    # 种出要交付的那几条:靠边界值撞运气是不行的
    if len(made["customer"]) >= 3:
        made["customer"][0]["name"] = ""
        made["customer"][2]["phone"] = made["customer"][1]["phone"]
    past = dt.datetime.now() - dt.timedelta(days=3)
    for r in made["appointment"][:6]:
        r["start_ts"] = past.strftime("%Y-%m-%d %H:%M:%S")
        r["end_ts"] = (past + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    # 留一批**没发过**的行给定向构造当基线 —— 基线必须是"发出去会成功"的那种
    spare = {t: made[t][-6:] for t in driven if len(made.get(t, [])) > 8}
    for t in spare: made[t] = made[t][:-6]

    d = apidrive.Driver(spec, dry=False, log=lambda *a: None)
    d.run(pl, made)

    # ---- 定向构造:把随机数据撞不到的码补上 ----
    import probe as PR
    cov0 = d.coverage()
    targets = {t: c.get("没撞到") or [] for t, c in cov0.items()}
    # 先**不做外键翻译**地拿到完整请求体:`_payload` 一旦翻译不到就提前返回半条,
    # 后面想补都没字段可补(第一版就栽在这:补丁写了,但 body 是空的)。
    bases = {t: [d.payload_of(t, r, pl, set())[0] for r in rs]
             for t, rs in spare.items()}
    # **留出来的子表行,引用的是同样被留出的父表行** —— 那些父记录从没被创建,
    # 外键翻译不到,于是每条基线都被「客户不存在」挡回来,整张表只试了 2 次就没了。
    # (而它不报错、不跳过,只是"没撞到"—— 又一个「绿有两种」。)
    # 基线的外键改指到**真正建成的**那些记录上。
    for t, bs in bases.items():
        ep = spec["endpoints"][t]["create"]
        for f, col in (ep.get("fields") or {}).items():
            g = pl["tables"][t]["columns"].get(col) or {}
            if g.get("gen") != "fk" or g.get("table") not in driven: continue
            real = [v for (pt, _k), v in d.idmap.items() if pt == g["table"]]
            if not real: continue
            for i, b in enumerate(bs):
                if f in b: b[f] = real[i % len(real)]
    # **基线必须是发出去会成功的那种**,而我们照源库分布造的预约全是历史时间 ——
    # 业务规则只收未来的预约,于是每一条基线都被拒,整张表被跳过。
    # 这是这条路的真实前提:**造出来的数据本身违规时,你拿不到有效基线。**
    # 所以基线单独把时间挪到未来(只动基线,不动那批用来发现差集的数据)。
    fut = dt.datetime.now() + dt.timedelta(days=5)
    for t, bs in bases.items():
        for b in bs:
            for k, v in list(b.items()):
                if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
                    b[k] = (fut if "end" not in k.lower()
                            else fut + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    pres = PR.probe(d, pl, targets, bases, budget=300, log=log)
    for t, why in (pres.get("跳过的表") or {}).items():
        log(f"  ⚠️ {t}:{why}")
    # **无条件**打每张表试了几次。只在"有原因"时才打的话,
    # 「这张表试了 2 次就没戏了」和「这张表试了 30 次确实撞不到」看起来一模一样。
    for t, info in (pres.get("每张表") or {}).items():
        log(f"  定向构造 · {t}:试了 {info.get('试了', 0)} 次"
            + (f" —— {info['原因']}" if info.get("原因") else ""))
    if pres["撞出来的"]:
        log(f'  定向构造:试了 {pres["试了"]} 次,补上 {len(pres["撞出来的"])} 条'
            f'({"、".join(sorted(pres["撞出来的"]))})')
    for c, info in pres["撞出来的"].items():
        # 把探出来的也做成一条拒绝记录,好和随机撞到的一起归类
        d.rejected.append({"表": info["表"], "HTTP": 200, "码": c,
                           "错误": info["接口说"], "提交的": info["请求体"],
                           "定向构造": {"算子": info["算子"], "改的字段": info["改的字段"]}})
    calls = d.minimize(pl)
    rep = d.report()
    n, cant = d.rollback()
    log(f"  打了 {rep['成功']} 成功 / {rep['拒绝']} 拒绝 / {rep['判不出成败']} 判不出;"
        f"削最小 {calls} 次请求;回滚 {n} 条" + (f",删不掉 {cant}" if cant else ""))
    if stop: stop()

    cov = d.coverage()
    rep["覆盖"] = cov
    for t, c in cov.items():
        if c.get("全集") is None:
            log(f"  ⚠️ {t}:规格没声明业务码全集 —— **覆盖率无法度量**,别把这份清单当完整规则表")
        else:
            log(f"  {t}:撞到 {len(c['撞到'])}/{len(c['全集'])} 条规则"
                f"{'  没撞到:' + '、'.join(c['没撞到']) if c['没撞到'] else '  (全撞到了)'}")
    rules = [r for r in rep["规则"] if r["码"] in WANT]
    return {
        "说明": "「数据库允许、业务不允许」的差集。每条可直接变成一道负向评测题:"
                "题面用「最小请求体 + 库这边」,标准答案的依据是 backend/rules.py。",
        "来源": "fakedata 接口驱动;靶子的校验只读 import backend/rules.py,是产品真实那一份",
        "字段含义": {
            "码": "业务错误码。归类锚在码上,不锚在文案上 —— 文案带 id 和人名,同一条规则每次都不一样",
            "最小请求体": "逐字段删到不能再删,**且保持同一个错误码**。换个码就是另一条规则了",
            "库这边": "这个接口整个字段面在数据库里的约束 —— 差集的另一半",
            "删掉也一样": "删掉不影响这条规则触发,即与本规则无关的字段",
            "撞了几次": "这一批数据里撞上它多少次,可以当作它有多容易被踩",
        },
        "生成于": dt.datetime.now().isoformat(timespec="seconds"),
        "覆盖": cov,
        "定向构造": {k: {"算子": v["算子"], "改的字段": v["改的字段"]}
                     for k, v in pres["撞出来的"].items()},
        "覆盖说明": "「没撞到」有两种解释:规则不存在,或者这批数据恰好绕开了它 —— "
                    "两者在输出上分不开,所以必须把没撞到的也列出来。"
                    "规格没声明全集时,这份清单**不能**当作完整的规则清单。",
        "差集": rules,
    }


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 else None
    doc = build(spec)
    out = os.path.join(HERE, "差集清单.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n差集 {len(doc['差集'])} 条 → {out}\n")
    for r in doc["差集"]:
        print(f"[{r['码']}] {r['表']} · 撞了 {r['撞了几次']} 次")
        print(f"   接口说:   {r['接口说'][:72]}")
        print(f"   最小请求: {json.dumps(r['最小请求体'], ensure_ascii=False)}")
        print(f"   删掉也一样: {r.get('删掉也一样')}")
        for col, c in (r.get("库这边") or {}).items():
            print(f"   库这边 · {col}: 可空={c['可空']} 唯一={c['唯一']}")
        print()
