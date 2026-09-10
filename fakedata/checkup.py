#!/usr/bin/env python3
"""接手体检 —— 对着一个陌生系统跑的第一条命令。

    python3 fakedata/checkup.py backend/lanxiu.db
    python3 fakedata/checkup.py mysql://user:pass@host:3306/db

**只读。不写任何东西,不调模型,不花钱。** 几秒钟出一份
「**这个系统我读懂了多少**」。

## 为什么需要它

这个工具现在有五个入口(出方案 / 泛化体检 / 差集清单 / 起草规格 / 稳定性),
每个都能单独跑 —— 但接一个**没见过的系统**时,第一步该干什么没人说得清。

而更要紧的是:前面每一刀都在往报告里加分母(认出率、覆盖率、一致率),
它们散在五个地方。**分母散着放,等于没有** —— 没人会为了看清一件事跑五条命令。

## 这份体检的规矩

**每个数字都带分母**,并且最后一节明写「这份体检**没**覆盖什么」。
因为这一路撞见的所有洞都是同一个形状:
**系统没报告任何问题,而问题确实存在** —— 因为没发生的事不留痕迹。
一份不说自己盲区的体检报告,本身就是那个形状。
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import schema as S, discover as D, plan as P, guard

GENERIC = ("text", "number", "small_int")     # 没认出语义,只能造随机值


def checkup(target, env="test", log=print):
    log(guard.check_target(target, env))          # 只读也要过闸门:声明环境
    conn = S.connect(target)
    sc = conn.reflect()
    facts = D.discover(conn, sc)
    pl = P.build(facts, scale=1.0)

    tabs = sc.tables
    live = [t for t in tabs.values() if t.rows > 0]
    empty = sorted(t.name for t in tabs.values() if t.rows == 0)
    # 明写的外键要**按边去重**再数:同一条关系常常被声明两次
    # (列级 `references x(y)` + 表级 `foreign key(a) references x(y)`)。
    # 不去重的话报告会写成「明写 4 条 → 挖出 3 条」,读起来像**少了一条** ——
    # 而门面报告里的数字**不能让人产生错觉**,那正是这份报告要治的病。
    declared = len({(t.name, c, rt, rc) for t in tabs.values()
                    for c, rt, rc in t.declared_fks})
    fks = [(t, k) for t, tf in facts["tables"].items() for k in tf["fks"]]
    conf = collections.Counter(k["confidence"] for _t, k in fks)

    cols = [(t, c, g) for t, tp in pl["tables"].items() for c, g in tp["columns"].items()]
    known = [x for x in cols if x[2]["gen"] not in GENERIC]
    todo = [(t, c) for t, tp in pl["tables"].items()
            for c, g in tp["columns"].items() if "需确认" in g]
    skip = [t for t, tp in pl["tables"].items() if tp.get("skip")]
    seq = sum(len(tp.get("时间序") or []) for tp in pl["tables"].values())
    forb = sum(len(j["禁配候选"]) for tf in facts["tables"].values()
               for j in tf.get("joint", []))
    kinds = collections.Counter(g["gen"] for _t, _c, g in cols)

    return {
        "目标": sc.label, "方言": sc.dialect,
        "表": {"总数": len(tabs), "有数据": len(live), "空表": empty},
        "关系": {"库里明写": declared, "挖出来": len(fks), "按可信度": dict(conf)},
        "认出率": {"列总数": len(cols), "认出语义": len(known),
                   "百分比": round(len(known) / max(len(cols), 1), 3),
                   "分布": dict(kinds.most_common(8))},
        "待人确认": len(todo),
        "灌不了的表": skip,
        "断言": {"条数": len(pl["assertions"]),
                 "按类": dict(collections.Counter(a["类"] for a in pl["assertions"]))},
        "统计出的时间先后": seq,
        "禁配候选": forb,
        "环": len(pl["deferred_fks"]),
    }


def report(r, log=print):
    t, rel, rec = r["表"], r["关系"], r["认出率"]
    log(f"\n{'=' * 62}\n接手体检 · {r['目标']}({r['方言']})\n{'=' * 62}")
    log(f"\n【读到了什么】")
    log(f"  表        {t['有数据']}/{t['总数']} 张有数据"
        + (f"   空表 {len(t['空表'])} 张:{t['空表'][:5]}" if t["空表"] else ""))
    log(f"  表关系    库里明写 {rel['库里明写']} 条 → **挖出 {rel['挖出来']} 条**"
        f"   可信度 {rel['按可信度']}")
    log(f"  列语义    {rec['认出语义']}/{rec['列总数']} = **{rec['百分比']:.0%}**"
        f"   剩下的只能造随机串")
    log(f"  时间先后  从源库统计出 {r['统计出的时间先后']} 条")
    log(f"  禁配候选  {r['禁配候选']} 个「本该出现却一次没出现」的组合")

    log(f"\n【造出来之后能查什么】")
    log(f"  断言 {r['断言']['条数']} 条:{r['断言']['按类']}")

    log(f"\n【要你过目的】")
    log(f"  待人确认  **{r['待人确认']} 处**(推出来的关系 / 猜不准的列 / 空表)")
    if r["灌不了的表"]:
        log(f"  灌不了    {len(r['灌不了的表'])} 张表**没有主键** —— "
            f"灌得进去但删不掉,默认跳过:{r['灌不了的表'][:5]}")
    if r["环"]:
        log(f"  环        {r['环']} 条外键成环,要两阶段灌(先插空再回填)")

    # ── 这一节是这份报告存在的理由 ──
    log(f"\n【**这份体检没覆盖什么**】")
    log(f"  · 只读了**结构和分布**,没读业务规则 ——")
    log(f"    「数据库允许但业务不允许」的那道差,要跑 diffreport.py 打写接口才看得见")
    log(f"  · 认出率 {rec['百分比']:.0%} 说的是「有没有认出语义」,**不是「认得对不对」**")
    log(f"  · 挖出来的关系里,可信度非「高」的那些是**推的**,不是库里明写的")
    if r["表"]["空表"]:
        log(f"  · {len(r['表']['空表'])} 张空表上,一切结论都只能来自列名 —— "
            f"要它准,得给一个有数据的库当样本源")
    log(f"  · 本次**没调模型**:否决误报、补语义、推状态机都没做(那要 --infer)")
    log(f"  · 造数、灌入、回滚一概没跑 —— 这只是体检,不是治疗\n")


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "backend", "lanxiu.db")
    env = sys.argv[2] if len(sys.argv) > 2 else "test"
    r = checkup(tgt, env)
    report(r)
    out = os.path.join(ROOT, ".fakedata", "checkup.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(r, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"明细 → {out}")
