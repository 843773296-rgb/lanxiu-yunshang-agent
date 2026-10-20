#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判示例库 · 开 / 关示例对比(一期,用户 2026-10-16 拍)。

    python3 agent/example_ab.py              # 看挑哪几道、每道会配哪几条示例(不调模型)
    ./agentsite/.venv/bin/python agent/example_ab.py --做 --轮 2

题:只从冻结的**评测**那一份取(`example_pool.评测ids`),每种根因一道 —— 示例池里的单一道都不考。
跑法:同一道题,关示例 / 开示例各跑 N 轮;提示词都从 `ops.研判提示词` 现取,唯一的差别是 `带示例`。
判分:`agent/eval.hit`(研判评测现成那份,不另写)。

⚠️ **读数之前先读这句**(用户 2026-10-16 知情选择「基础设施照做,涨分不算数」):
现有标注里特征和答案几乎一一对应(退款六种根因各一种返回码),**开示例的涨分是「查表」,不是「会判了」**。
这一轮能说明的只有两件事:① 开了示例**有没有退步** ② 答错时**是不是照抄了示例的根因**。
要测出示例真有用,得等业务给「表面一样、根因不同」的真实案例。

不落库:不走 `/api/run-triage`(那条会写 triage 和工单状态),直接调 `sdk.run`。结果追加到
`agent/example-ab-results.jsonl`,不覆盖。
"""
import argparse, asyncio, datetime, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite"), os.path.join(ROOT, "knowledge")]
结果文件 = os.path.join(HERE, "example-ab-results.jsonl")
类型 = {"BP-01": "财务人工任务", "BP-02": "客户合并确认", "BP-03": "售后判责"}


def 题们():
    import example_pool as E, truthdb
    评 = E.评测ids()
    标 = truthdb.by_case()
    已, 出 = set(), []
    for x in E.冻结的()["评测"]:
        if x["case_id"] not in 评 or (x["bp"], x["根因"]) in 已:
            continue
        已.add((x["bp"], x["根因"]))
        t = truthdb.rows("SELECT id, ref_id FROM task WHERE id=?", "T" + x["case_id"])
        if not t:
            continue
        出.append(dict(case_id=x["case_id"], bp=x["bp"], 类型=类型[x["bp"]], 工单=t[0]["id"],
                      ref=t[0]["ref_id"], 真因=标[x["case_id"]]["root_cause"]))
    return 出


def 分界点():
    try:
        sha = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        脏 = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, timeout=10).stdout.strip()
        return sha + ("+已跟踪文件有未提交改动" if 脏 else "")
    except Exception as e:
        return f"(取不到:{type(e).__name__})"


def 跑一题(题, 带示例):
    import ops, sdk, example_pool as E
    import eval as EV
    _, _, prompt = ops.研判提示词(题["类型"], 题["ref"], 题["工单"], 带示例=带示例)
    用了 = E.挑(题["bp"], 题["case_id"]) if 带示例 else []
    示根因 = [r["root_cause"] for r in
              __import__("truthdb").rows("SELECT root_cause FROM truth WHERE case_id IN (%s)" % ",".join("?" * len(用了)),
                                         *[u["case_id"] for u in 用了])] if 用了 else []
    r = asyncio.run(sdk.run("triage", prompt))
    文 = r.get("text") or ""
    过, 为什么 = EV.hit(文, 题["真因"], 题["case_id"])
    没答成 = "没有作为正式答复给出" in 文
    # 照抄:答错了,而且答案里出现的是某条示例的(错的)根因
    照抄 = (not 过) and any(rc != 题["真因"] and rc in 文 for rc in 示根因)
    return dict(case_id=题["case_id"], bp=题["bp"], 真因=题["真因"], 带示例=带示例,
                示例=[u["case_id"] for u in 用了], 示例根因=示根因,
                过=bool(过) and not 没答成, 没答成=没答成, 照抄示例根因=照抄, 为什么=str(为什么)[:200],
                调了几个工具=len(r.get("trajectory") or []),
                工具=[t.get("tool") for t in (r.get("trajectory") or [])][:20],
                花了=r.get("cost_usd"), 原文=文[:4000])


def 做(轮数):
    界 = 分界点()
    题 = 题们()
    行 = []
    for 轮 in range(1, 轮数 + 1):
        for t in 题:
            for 带 in (False, True):
                x = 跑一题(t, 带)
                x["轮"] = 轮
                行.append(x)
                print(f"  轮{轮} {'开' if 带 else '关'} {t['case_id']:9s} {'✅' if x['过'] else ('⏸ 没答成' if x['没答成'] else '❌')}"
                      + ("  ← 照抄了示例的根因" if x["照抄示例根因"] else ""))
    报 = 汇总(行, 轮数)
    with open(结果文件, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(跑于=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 分界点=界,
                                题数=len(题), 轮数=轮数, 报=报, 逐题=行), ensure_ascii=False) + "\n")
    print(json.dumps(报, ensure_ascii=False, indent=1))


def 汇总(行, 轮数):
    报 = {}
    for 带 in (False, True):
        名 = "开示例" if 带 else "关示例"
        报[名] = {f"轮{k}": dict(过=sum(1 for x in 行 if x["带示例"] == 带 and x["轮"] == k and x["过"]),
                               没答成=sum(1 for x in 行 if x["带示例"] == 带 and x["轮"] == k and x["没答成"]),
                               题数=sum(1 for x in 行 if x["带示例"] == 带 and x["轮"] == k))
                 for k in range(1, 轮数 + 1)}
    报["开示例时照抄了示例根因的"] = [(x["轮"], x["case_id"]) for x in 行 if x["照抄示例根因"]]
    关 = {(x["轮"], x["case_id"]): x["过"] for x in 行 if not x["带示例"]}
    报["开示例反而挂了的(关的时候过)"] = [(x["轮"], x["case_id"]) for x in 行
                                     if x["带示例"] and not x["过"] and 关.get((x["轮"], x["case_id"]))]
    报["读数提醒"] = "特征和答案几乎一一对应,开示例的涨分是查表,不算能力提升;只看有没有退步、有没有照抄"
    return 报


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true")
    ap.add_argument("--轮", type=int, default=2)
    a = ap.parse_args()
    if a.做:
        做(a.轮)
    else:
        import example_pool as E
        for t in 题们():
            print(f"{t['bp']} {t['case_id']:9s} {t['真因']:<22s} 示例 {[x['case_id'] for x in E.挑(t['bp'], t['case_id'])]}")
