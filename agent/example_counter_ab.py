#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判示例库 · 「表面一样、根因不同」案例的开 / 关示例对比(用户 2026-11-14 拍,台账第五十二条)。

    python3 agent/example_counter_ab.py              # 不调模型:在副本上造出案例,看每道题会配哪几条示例
    ./agentsite/.venv/bin/python agent/example_counter_ab.py --做 --轮 2

案例在 `agent/example-counter-cases.json`(**项目方按业务口径整理**,不是业务逐例认定 —— 见那份文件的说明)。
一期对比(agent/example_ab.py)只能说明「开示例不退步、不照抄」,测不出有没有用:现有标注特征和答案一一对应,
开示例的涨分是查表。这一批是故意造的「特征一样、根因不同」—— 例如尺寸差一模一样(腰围差 4cm),
一条是超出公差、一条是量体记录不全。**照抄示例的根因在这里一定答错**,所以这一轮的差距才说明示例有没有用。

## 不碰共享库

  · 全程跑在库副本上(agent/evaldb.用副本:本进程的模块 + 模型调的工具子进程都切过去)
  · 案例的单据在副本里照「模板」克隆一整套(维修单 + 判责工单),只改「改」里那几项证据
  · 案例的标注只插进**副本**的 truth 表(示例段从那里读「人认定的根因」);共享库的评测答案表一行不动
  · 冻结的示例池文件不改 —— 这一轮在进程里临时把「进示例池」的那几条并进去
结果追加到 agent/example-counter-ab-results.jsonl,每行都盖着分界点和案例来源。
"""
import argparse, asyncio, datetime, json, os, sqlite3, subprocess, sys
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite"), os.path.join(ROOT, "knowledge")]
案例文件 = os.path.join(HERE, "example-counter-cases.json")
结果文件 = os.path.join(HERE, "example-counter-ab-results.jsonl")
类型 = {"BP-01": "财务人工任务", "BP-02": "客户合并确认", "BP-03": "售后判责"}


def 读案例():
    with open(案例文件, encoding="utf-8") as f:
        return json.load(f)


def 处理(根因):
    return 根因.split(" · ")[-1]


def 造到副本(副本, 案):
    """照模板克隆维修单 + 判责工单,插标注 —— 只在副本里。→ 造了几条。"""
    n = 0
    with closing(sqlite3.connect(副本)) as c, c:
        def 克隆(表, 条件, 参数, 改):
            列 = [d[1] for d in c.execute(f"PRAGMA table_info({表})")]
            for r in c.execute(f"SELECT * FROM {表} WHERE {条件}", 参数).fetchall():
                行 = dict(zip(列, r)); 行.update(改(行) or {})
                if 行 is None: continue
                c.execute(f"INSERT OR REPLACE INTO {表}({','.join(列)}) VALUES({','.join('?' * len(列))})", [行[k] for k in 列])
        for x in 案["案例"]:
            if x["bp"] == "BP-01":
                # 退款:照模板押金克隆押金 + 退款轨迹 + 支付流水,**只不复制那笔成功出账** —— 渠道返回一模一样,钱没退出去
                模 = x["模板"]
                if not c.execute("SELECT 1 FROM deposit WHERE id=?", (模,)).fetchone():
                    raise SystemExit(f"{x['id']}:模板押金 {模} 不在库里")
                克隆("deposit", "id=?", (模,), lambda r: dict(id=x["id"]))
                tl = [d[1] for d in c.execute("PRAGMA table_info(refund_trace)")]
                for r in c.execute("SELECT * FROM refund_trace WHERE deposit_id=? ORDER BY attempt", (模,)).fetchall():
                    行 = dict(zip(tl, r)); 行["deposit_id"] = x["id"]
                    if "id" in 行: 行["id"] = None if isinstance(行["id"], int) else f"{行['id']}-{x['id']}"
                    c.execute(f"INSERT INTO refund_trace({','.join(tl)}) VALUES({','.join('?' * len(tl))})", [行[k] for k in tl])
                pl = [d[1] for d in c.execute("PRAGMA table_info(payment_flow)")]
                for r in c.execute("SELECT * FROM payment_flow WHERE deposit_id=?", (模,)).fetchall():
                    行 = dict(zip(pl, r))
                    if 行["direction"] == "out" and 行["status"] == "success" and x["改"].get("删成功出账"):
                        continue
                    行.update(id=f"PF{x['id']}{行['direction'][0].upper()}", deposit_id=x["id"])
                    c.execute(f"INSERT OR REPLACE INTO payment_flow({','.join(pl)}) VALUES({','.join('?' * len(pl))})", [行[k] for k in pl])
                克隆("task", "id=?", ("T" + 模,), lambda r: dict(id="T" + x["id"], ref_id=x["id"], status="待复核"))
                c.execute("INSERT OR REPLACE INTO truth(case_id,breakpoint,root_cause,expected_action,expected_evidence,note,src) "
                          "VALUES(?,?,?,?,?,?,?)", (x["id"], x["bp"], x["根因"], x.get("处理") or 处理(x["根因"]), x["依据"],
                                                     f"「表面一样、根因不同」反例 · {x['类']}", 案["来源"]))
                n += 1
                continue
            if x["bp"] != "BP-03":
                raise SystemExit(f"{x['id']}:合并类反例还没有造法")
            m = c.execute("SELECT * FROM maintain WHERE id=?", (x["模板"],)).fetchone()
            if not m: raise SystemExit(f"{x['id']}:模板维修单 {x['模板']} 不在库里")
            列 = [d[1] for d in c.execute("PRAGMA table_info(maintain)")]
            行 = dict(zip(列, m)); 行["id"] = x["id"]
            for k, v in x["改"].items():
                行[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
            if "尺寸差" not in x["改"]: 行["尺寸差"] = None
            c.execute(f"INSERT OR REPLACE INTO maintain({','.join(列)}) VALUES({','.join('?' * len(列))})", [行[k] for k in 列])
            t = c.execute("SELECT * FROM task WHERE id=?", ("T" + x["模板"],)).fetchone()
            if not t: raise SystemExit(f"{x['id']}:模板工单 T{x['模板']} 不在库里")
            tl = [d[1] for d in c.execute("PRAGMA table_info(task)")]
            tr = dict(zip(tl, t)); tr.update(id="T" + x["id"], ref_id=x["id"], status="待复核")
            c.execute(f"INSERT OR REPLACE INTO task({','.join(tl)}) VALUES({','.join('?' * len(tl))})", [tr[k] for k in tl])
            c.execute("INSERT OR REPLACE INTO truth(case_id,breakpoint,root_cause,expected_action,expected_evidence,note,src) "
                      "VALUES(?,?,?,?,?,?,?)", (x["id"], x["bp"], x["根因"], 处理(x["根因"]), x["依据"],
                                                 f"「表面一样、根因不同」反例 · {x['类']}", 案["来源"]))
            n += 1
    return n


def 准备():
    """切副本 → 造案例 → 把「进示例池」的并进示例池。→ (案例, 评测题)。"""
    import ops, example_pool as E, truthdb, eval as EV   # noqa: F401  先 import 再切库(evaldb 文件头)
    import evaldb
    副本 = evaldb.用副本("excounter-", 先导入=("ops", "example_pool", "truthdb"))
    assert os.path.realpath(E.DB) == os.path.realpath(副本), "示例池没切到副本"
    案 = 读案例()
    print(f"  在副本里造了 {造到副本(副本, 案)} 条案例(来源:{案['来源']})")
    原 = E.冻结的
    加 = [dict(case_id=x["id"], bp=x["bp"], 根因=x["根因"]) for x in 案["案例"] if x["进"] == "示例池"]
    def 冻结的_加反例():
        d = dict(原()); d["示例池"] = list(d["示例池"]) + 加; return d
    E.冻结的 = 冻结的_加反例
    题 = [dict(case_id=x["id"], bp=x["bp"], 类型=类型[x["bp"]], 工单="T" + x["id"], ref=x["id"], 真因=x["根因"], 类=x["类"])
         for x in 案["案例"] if x["进"] == "评测"]
    # 闸:评测题**一道都不许在示例池里**(否则带示例时模型会看到这道题自己的答案),
    # 也不许和冻结切分里的编号撞上(撞上就是两套标注混在一个号上)—— 和 example_ab 用 评测ids 取题是同一个约束
    号 = {t["case_id"] for t in 题}
    撞 = 号 & ({x["case_id"] for x in E.冻结的()["示例池"]} | E.评测ids() | E.示例池ids())
    assert not 撞, f"反例评测题和示例池 / 冻结切分撞号了:{sorted(撞)}"
    return 案, 题


def 跑一题(题, 带示例):
    import ops, sdk, example_pool as E, truthdb
    import eval as EV
    _, _, prompt = ops.研判提示词(题["类型"], 题["ref"], 题["工单"], 带示例=带示例)
    用了 = E.挑(题["bp"], 题["case_id"]) if 带示例 else []
    示根因 = [r["root_cause"] for r in truthdb.rows(
        "SELECT root_cause FROM truth WHERE case_id IN (%s)" % ",".join("?" * len(用了)), *[u["case_id"] for u in 用了])] if 用了 else []
    r = asyncio.run(sdk.run("triage", prompt))
    文 = r.get("text") or ""
    过, 为什么 = EV.hit(文, 题["真因"], 题["case_id"])
    没答成 = "没有作为正式答复给出" in 文
    照抄 = (not 过) and any(rc != 题["真因"] and rc in 文 for rc in 示根因)
    return dict(case_id=题["case_id"], 类=题["类"], 真因=题["真因"], 带示例=带示例,
                示例=[u["case_id"] for u in 用了], 示例根因=示根因,
                过=bool(过) and not 没答成, 没答成=没答成, 照抄示例根因=照抄, 为什么=str(为什么)[:200],
                花了=r.get("cost_usd"), 原文=文[:4000])


def 分界点():
    try:
        sha = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        脏 = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10).stdout.strip()
        return sha + ("+工作区有改动" if 脏 else "")
    except Exception:
        return "(取不到)"


def 做(轮数):
    案, 题 = 准备()
    行 = []
    for 轮 in range(1, 轮数 + 1):
        for t in 题:
            for 带 in (False, True):
                x = 跑一题(t, 带); x["轮"] = 轮; 行.append(x)
                print(f"  轮{轮} {'开' if 带 else '关'} {t['case_id']} {'✅' if x['过'] else ('⏸ 没答成' if x['没答成'] else '❌')}"
                      + ("  ← 照抄了示例的根因" if x["照抄示例根因"] else ""))
    报 = {}
    for 带 in (False, True):
        报["开示例" if 带 else "关示例"] = {f"轮{k}": dict(过=sum(1 for x in 行 if x["带示例"] == 带 and x["轮"] == k and x["过"]),
                                                        题数=sum(1 for x in 行 if x["带示例"] == 带 and x["轮"] == k)) for k in range(1, 轮数 + 1)}
    报["开示例时照抄了示例根因的"] = [(x["轮"], x["case_id"]) for x in 行 if x["照抄示例根因"]]
    关 = {(x["轮"], x["case_id"]): x["过"] for x in 行 if not x["带示例"]}
    报["开示例反而挂了的(关的时候过)"] = [(x["轮"], x["case_id"]) for x in 行 if x["带示例"] and not x["过"] and 关.get((x["轮"], x["case_id"]))]
    报["开示例才过的(关的时候挂)"] = [(x["轮"], x["case_id"]) for x in 行 if x["带示例"] and x["过"] and 关.get((x["轮"], x["case_id"])) is False]
    报["读数提醒"] = (f"案例来源:{案['来源']} —— 自己出的题;样本 {len(题)} 道 × {轮数} 轮,"
                     "两轮之间的抖动不小于开 / 关的差时,不下「有用 / 没用」的结论")
    with open(结果文件, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(跑于=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 分界点=分界点(),
                                题数=len(题), 轮数=轮数, 报=报, 逐题=行), ensure_ascii=False) + "\n")
    print(json.dumps(报, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true")
    ap.add_argument("--轮", type=int, default=2)
    a = ap.parse_args()
    if a.做:
        做(a.轮)
    else:
        import example_pool as E
        案, 题 = 准备()
        for t in 题:
            选 = E.挑(t["bp"], t["case_id"])
            print(f"  {t['case_id']} {t['真因']:<24s} 配的示例 {[(x['case_id'], x['重合']) for x in 选]}")
