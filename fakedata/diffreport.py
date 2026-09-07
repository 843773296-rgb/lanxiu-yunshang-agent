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
import json, os, shutil, sys, tempfile

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

    d = apidrive.Driver(spec, dry=False, log=lambda *a: None)
    d.run(pl, made)
    calls = d.minimize(pl)
    rep = d.report()
    n, cant = d.rollback()
    log(f"  打了 {rep['成功']} 成功 / {rep['拒绝']} 拒绝 / {rep['判不出成败']} 判不出;"
        f"削最小 {calls} 次请求;回滚 {n} 条" + (f",删不掉 {cant}" if cant else ""))
    if stop: stop()

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
