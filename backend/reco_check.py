#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推荐(协同过滤 / 矩阵分解 / 找像 A 的人)· 算法行为对、闸都在、范围收得住

    python3 backend/reco_check.py

## 为什么要有这个
用户 2026-11-28 拍:商品对商品协同过滤(归一化)+ 矩阵分解都做;找像 A 的人 行为 7 画像 3;
给人推荐两个都给;闸 = 买过的不推 / 只推在售 / 至少 5 人一起看过 / 不同意营销的不推 / 90 天冷却(共用 A-266 那道)。

数据是造的,**推得好不好验不了**(见 knowledge/reco.py 顶上)—— 这里只验**算法行为**和**闸**:
  1. 手算样本:归一化让「爆款」让位给「真正一起看的」;不到 5 人的不算相关;买过 / 不在售的不推;
     权重和半衰对;像的人按比重排、不含自己;每人最多推 5 件、按 A 的分量排;矩阵分解同输入两次一样
  2. 真库:所有商品「看了还看」前 5 里全店前 10 爆款的占比压得住(11-28 实测 18%,不归一化 65%);
     抽一批客户,推的都在售、都没买过;找像 A 的人里列为「能推」的,每一位都同意营销
  3. 接线:冷却真调的是 opportunity_store._上次推送(共用那道闸);库里 90 天内被推过的人,能推吗() 说不能;
     别店店长查不了这位客户
"""
import ast
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import browse as B      # noqa: E402
import lookalike as L   # noqa: E402
import reco as R        # noqa: E402

G, Rd, D = "\033[32m", "\033[31m", "\033[0m"


# ── 1. 手算样本 ────────────────────────────────────────────────────────
def 查手算():
    bad = []
    # 用户 1–5 看 X、Y、H;6–7 看 X、H;8–30 只看 H。X 和 H 一起被看 7 次、和 Y 5 次 ——
    # 按次数 H 排第一(爆款),归一化后 Y 排第一(余弦:X·Y = 5/√35 ≈ 0.85,X·H = 7/√210 ≈ 0.48)
    m = {}
    for i in range(1, 31):
        d = {"H": 1.0}
        if i <= 7: d["X"] = 1.0
        if i <= 5: d["Y"] = 1.0
        m[f"u{i}"] = d
    # Z 和 X 只有 4 个人一起看过 → 不到 5 人,不算相关
    for i in range(31, 35):
        m[f"u{i}"] = {"X": 1.0, "Z": 1.0}
    相 = R.商品相似(m)
    看 = R.看了还看(相, "X", {"H", "Y", "Z", "X"}, 5)
    if not 看 or 看[0][0] != "Y":
        bad.append(f"归一化:看了 X 的第一位应是 Y(真正一起看的),得到 {[x[0] for x in 看]} —— 爆款没被压住")
    if any(x[0] == "Z" for x in 看):
        bad.append("门槛:X 和 Z 只有 4 个人一起看过,却被算成相关")
    推 = R.给人推荐_协同({"X": 1.0}, 相, {"Y", "H"}, 买过={"Y"})
    if any(x["商品"] == "Y" for x in 推):
        bad.append("闸:她买过 Y,协同过滤还推 Y")
    推2 = R.给人推荐_协同({"X": 1.0}, 相, {"H"}, 买过=set())
    if any(x["商品"] == "Y" for x in 推2):
        bad.append("闸:Y 不在售,协同过滤还推 Y")
    if 推2 and 推2[0]["因为看过"] != "X":
        bad.append("理由:推 H 的理由应是「因为看过 X」")
    # 爆款降权:只看过 X 的人,H 和 Y 都和 X 相关;给 H 一个巨大的销量 → 降权后 Y 在 H 前
    a1 = R.给人推荐_协同({"X": 1.0}, 相, {"H", "Y"}, 买过=set(), 销量={"H": 10 ** 6, "Y": 0})
    if not a1 or a1[0]["商品"] != "Y":
        bad.append(f"爆款降权:H 卖了一百万件,推荐第一位应让给 Y,得到 {[x['商品'] for x in a1]}")
    # 权重与半衰:看了 70 秒 + 加购 = 1 + 1 + 3 = 5;90 天前同样一套 = 2.5
    今 = dt.date(2026, 6, 30)
    行 = lambda ts: [dict(customer_id="a", ts=ts, event=B.进入详情, spu="P"),
                    dict(customer_id="a", ts=ts, event=B.离开详情, spu="P", dwell_s=70),
                    dict(customer_id="a", ts=ts, event=B.加购, spu="P")]
    w0 = R.交互(行("2026-06-30 10:00:00"), 今)["a"]["P"]
    w90 = R.交互(行("2026-04-01 10:00:00"), 今)["a"]["P"]
    if abs(w0 - 5.0) > 1e-9 or abs(w90 - 2.5) > 1e-9:
        bad.append(f"权重:看 70 秒 + 加购应为 5、90 天前应为 2.5,得到 {w0:.3f} / {w90:.3f}")
    # 找像 A 的人:a 和 b 行为一样、画像全不同;a 和 c 画像一样、行为不重合
    p = lambda **kw: {"性别": "女", "年龄": 30, "城市": "杭州", "省": "浙江", "收入": "20w-30w", "职业": "律师",
                      "有车": True, "有孩子": True, "等级": "金卡", "消费档": 2, **kw}
    画 = {"a": p(), "b": p(性别="男", 年龄=60, 城市="成都", 省="四川", 收入="10w 以下", 职业="茶艺师", 有车=False,
                       有孩子=False, 等级="普通", 消费档=0), "c": p(), "d": p(性别="男")}
    行为 = {"a": {"X": 1.0, "Y": 1.0, "Q": 1.0}, "b": {"X": 1.0, "Y": 1.0, "Q": 1.0}, "c": {"Z": 1.0, "Q": 1.0}, "d": {"Q": 1.0}}
    for i in range(10):
        行为[f"z{i}"] = {"Q": 1.0, "W": 1.0}       # 让 X / Y / Z 有逆人数权重(Q 人人都有 → 权重低)
        画[f"z{i}"] = p(城市="广州", 省="广东", 职业="教师")
    W, 模 = L.逆人数加权(行为)
    只行为 = L.找像的人("a", sorted(画), W, 模, 画, 比重=1.0, k=3)
    只画像 = L.找像的人("a", sorted(画), W, 模, 画, 比重=0.0, k=3)
    if not 只行为 or 只行为[0]["客户"] != "b":
        bad.append(f"比重 1(只看行为):最像 a 的应是 b(行为一样),得到 {[x['客户'] for x in 只行为]}")
    if not 只画像 or 只画像[0]["客户"] != "c":
        bad.append(f"比重 0(只看画像):最像 a 的应是 c(画像一样),得到 {[x['客户'] for x in 只画像]}")
    if any(x["客户"] == "a" for x in 只行为 + 只画像):
        bad.append("找像的人把 A 自己也算进去了")
    推人 = L.推A买过的({f"S{i}" for i in range(8)} | {"OFF", "B1"}, [{"客户": "b", "相似": 1, "都有过动作的商品": [], "画像一样的": []}],
                     {"b": {"B1"}}, {f"S{i}" for i in range(8)} | {"B1"}, A的分={"S7": 9, "S6": 8})
    if not 推人 or len(推人[0]["推"]) != L.每人最多推:
        bad.append(f"每人最多推 {L.每人最多推} 件,得到 {len(推人[0]['推']) if 推人 else 0}")
    elif 推人[0]["推"][:2] != ["S7", "S6"]:
        bad.append(f"推的顺序应按 A 的分量(S7、S6 在前),得到 {推人[0]['推'][:2]}")
    if 推人 and ({"OFF", "B1"} & set(推人[0]["推"])):
        bad.append("推 A 买过的:把不在售的 / 他买过的也推了")
    # 矩阵分解:同输入两次一样;只看过 X 的人,Y 的分高于 Z
    U1, V1 = R.矩阵分解(m, 迭代=3)
    U2, V2 = R.矩阵分解(m, 迭代=3)
    if U1 != U2 or V1 != V2:
        bad.append("矩阵分解:同一份输入、同一个种子,两次结果不同")
    return bad


# ── 2. 真库 / 3. 接线 ──────────────────────────────────────────────────
def 查真库():
    import api
    import reco_query as Q
    from contextlib import closing
    bad, 说 = [], []
    m = Q._模型(要分解=True)
    if m is None:
        return ["没东西可验:库里没有 mp_event —— 先跑 python3 tools/backfill_browse.py"], 说, True
    品们 = sorted(m["相"])
    if len(品们) < 50 or len(m["M"]) < 500:
        return [], [f"商品 {len(品们)} / 人 {len(m['M'])} 太少"], True
    top10 = set(sorted(m["销量"], key=lambda s: (-m["销量"][s], s))[:10])
    n = 中 = 0
    for s in 品们:
        for x in R.看了还看(m["相"], s, m["可推"], 5):
            n += 1; 中 += x[0] in top10
    占 = 中 / max(1, n)
    说.append(f"{len(品们)} 件商品的「看了还看」前 5 里全店前 10 爆款占 {占:.0%}")
    if 占 > 0.35:
        bad.append(f"归一化:「看了还看」前 5 里爆款占 {占:.0%}(11-28 实测 18%,不归一化 65%)—— 爆款没压住")
    抽 = sorted(m["M"])[::max(1, len(m["M"]) // 200)][:200]
    坏 = 0
    for u in 抽:
        for x in R.给人推荐_协同(m["M"][u], m["相"], m["可推"], m["买过"].get(u, set())) + \
                 R.给人推荐_分解(m["U"].get(u), m["V"], m["可推"], m["买过"].get(u, set())):
            坏 += x["商品"] not in m["可推"] or x["商品"] in m["买过"].get(u, set())
    说.append(f"抽 {len(抽)} 人查给人推荐")
    爆 = 总 = 0
    for u in 抽:
        for x in R.给人推荐_协同(m["M"][u], m["相"], m["可推"], m["买过"].get(u, set()), k=3, 销量=m["销量"]):
            总 += 1; 爆 += x["商品"] in top10
    说.append(f"给人推荐前 3 里全店前 10 爆款占 {爆 / max(1, 总):.0%}(不降权约 60–75%)")
    if 总 and 爆 / 总 > 0.55:
        bad.append(f"爆款降权:给人推荐前 3 里爆款占 {爆 / 总:.0%} —— 降权没起作用(11-28 拍轻度降权,虚拟数据上约 45%)")
    if 坏:
        bad.append(f"闸:抽的 {len(抽)} 人里推出了 {坏} 件不在售或她买过的")

    q = lambda s, *a: api._rows(s, *a)
    hq = q("SELECT no, role, name, shop FROM staff WHERE role='总部运营' AND status='启用' LIMIT 1")
    if not hq:
        return bad + ["夹具没立起来:没有启用的总部运营"], 说, False
    A = sorted(m["买过"], key=lambda u: (-len(m["买过"][u]), u))[0]
    with api.as_user(dict(hq[0])):
        s = Q.similar_customers(A)
    if "error" in s or not s.get("能推的"):
        bad.append(f"接线:总部运营找像 {A} 的人没找到能推的:{str(s)[:150]}")
    else:
        说.append(f"像 {A} 的 {s['像的人']} 人里能推 {s['其中能推']},挡掉 {s['没推的原因']}")
        with closing(Q._连()) as c:
            for x in s["能推的"]:
                r = c.execute("SELECT a.status, a.marketing_consent FROM customer cu JOIN account a ON a.id=cu.account_id "
                              "WHERE cu.id=?", (x["客户"],)).fetchone()
                if not r or not r[1] or r[0] in ("注销中", "已注销"):
                    bad.append(f"闸:{x['客户']} 没同意营销 / 已注销,却列在「能推的」里"); break
    # 冷却:库里 90 天内被推过的人,能推吗() 必须说不能
    import opportunity_store as OS
    with closing(Q._连()) as c:
        最近 = c.execute("SELECT customer_id, MAX(created) FROM buy_pref_recall GROUP BY customer_id "
                         "ORDER BY MAX(created) DESC LIMIT 1").fetchone() \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='buy_pref_recall'").fetchone() else None
        if 最近 and (m["今"] - dt.date.fromisoformat(str(最近[1])[:10])).days < 90:
            why = Q.能推吗(c, 最近[0], m["今"])
            if not why:
                bad.append(f"冷却:{最近[0]} 在 {str(最近[1])[:10]} 刚被推过,能推吗() 却说能推")
            说.append(f"冷却样本 {最近[0]}:{why}")
        else:
            说.append("冷却:库里没有 90 天内的推送记录,这一条没验到真样本(源码那条照验)")
    # 别店店长
    店 = q("SELECT shop FROM customer WHERE id=?", A)[0]["shop"]
    别 = q("SELECT no, role, name, shop FROM staff WHERE role='店长' AND status='启用' AND shop<>? LIMIT 1", 店)
    if 别:
        with api.as_user(dict(别[0])):
            for 名, f in (("找像的人", Q.similar_customers), ("给人推荐", Q.recommend_for)):
                if "error" not in f(A):
                    bad.append(f"范围:别店店长用「{名}」看到了 {A}")
    else:
        bad.append("接线:找不到别店店长 —— 范围这一条没验到")
    return bad, 说, False


def 查共用闸():
    """能推吗() 里真调了 opportunity_store._上次推送 和 oppo_obj.冷却中(共用 A-266 那道闸,不另写一份)。"""
    src = open(os.path.join(HERE, "reco_query.py"), encoding="utf-8").read()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == "能推吗":
            调 = {getattr(x.func, "attr", "") for x in ast.walk(n) if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)}
            缺 = {"_上次推送", "冷却中"} - 调
            return [f"共用闸:能推吗() 没调 {sorted(缺)} —— 冷却成了另一份" ] if 缺 else []
    return ["共用闸:reco_query.py 里没有 能推吗()"]


咬合 = [
    ("商品相似去掉归一化(只数一起看的次数)", "归一化:看了 X 的第一位应是 Y"),
    ("去掉「至少 5 人一起看过」", "门槛:X 和 Z 只有 4 个人一起看过"),
    ("协同过滤不排除她买过的", "闸:她买过 Y"),
    ("能推吗() 不查营销同意", "没同意营销 / 已注销,却列在"),
    ("给人推荐去掉爆款降权", "爆款降权:H 卖了一百万件"),
    ("找像的人去掉范围闸", "范围:别店店长用"),
]


def main():
    print("推荐 · 算法行为 / 闸 / 范围\n" + "=" * 72)
    b = 查手算()
    if b:
        for x in b: print(f"  {Rd}❌ {x}{D}")
        print(f"{Rd}❌ 手算样本没过 —— 真库那层不算数{D}"); return 1
    print("  ✅ 手算样本:归一化 / 门槛 / 买过不推 / 不在售不推 / 权重半衰 / 比重两端 / 每人 5 件 / 分解确定性")
    bad, 说, 空 = 查真库()
    for x in 说: print(f"  · {x}")
    if 空:
        for x in bad: print(f"  {Rd}❌ {x}{D}")
        print(f"{Rd}❌ 没东西可验 —— 不是「都对」{D}"); return 1
    bad += 查共用闸()
    for x in bad: print(f"  {Rd}❌ {x}{D}")
    if bad:
        print(f"{Rd}❌ {len(bad)} 处不对{D}"); return 1
    print(f"{G}✅ 推荐:归一化压住爆款、闸都在、冷却共用原来那道、范围收得住{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
