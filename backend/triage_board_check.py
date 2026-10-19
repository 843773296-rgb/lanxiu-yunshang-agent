#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判质量看板 · 检查(研判队列未做项第 6 项第一块 · 用户 2026-10-19 拍:总部看全部,店长看本店)。

库副本上清掉真实研判、自造四件事(两家店、三类、一件跑了两次、一件高置信被改判、一件已升级、一件带版本号),
真调 `triage_board.看板()`。要守的:
  · 事项数和 AI 运行次数分开数(一件跑两次 = 1 件事、2 次运行);
  · **采纳率的分母不含「已升级」和「待复核」**(旧 health() 还把升级算成结论);
  · 店长只看得到本店;总部看全部;别的岗位看不了;门店从单据现查,不收前端传的;
  · 按版本拆:没记版本的单独一组;每个数都能下钻到是哪几件;分母小于 10 标样本少。
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("采纳率的分母把「已升级」也算进去", "采纳率 = 已采纳 ÷(已采纳 + 已改判):升级、待复核都不进分母"),
    ("店长看到全部门店", "店长只看得到本店的事"),
    ("事项数按研判行数数(跑两次算两件)", "事项数和 AI 运行次数分开数(一件跑两次 = 1 件、2 次)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:180]}" if 附 and not ok else ""))


def 抛(f):
    try:
        f(); return None
    except Exception as e:                   # noqa: BLE001
        return e


print("研判质量看板 · 检查")
print("=" * 80)

import check_copy
import triage_board as B
db = check_copy.用副本("tboard-")
c = sqlite3.connect(db)
# 两家店各挑一张押金单 / 一对客户 / 一张维修单 —— 门店要从单据现查
押 = {s: c.execute("SELECT d.id FROM deposit d JOIN customer cu ON cu.id=d.customer_id WHERE cu.shop=? ORDER BY d.id LIMIT 2",
                   (s,)).fetchall() for s in ("SH001 静安旗舰店", "SH002 徐汇店")}
客 = c.execute("SELECT a.id, b.id FROM customer a JOIN customer b ON b.id>a.id WHERE a.shop='SH002 徐汇店' "
              "ORDER BY a.id, b.id LIMIT 1").fetchone()
修 = c.execute("SELECT id FROM maintain WHERE shop='SH002 徐汇店' ORDER BY id LIMIT 1").fetchone()
if not (len(押["SH001 静安旗舰店"]) >= 2 and 客 and 修):
    ck("库里有 SH001 的两张押金单、SH002 的一对客户和一张维修单 —— 没有就没验,不算通过", False)
    sys.exit(1)
c.execute("DELETE FROM triage")                # 只看自造的四件事 —— 红不红不取决于主库被怎么用过
造 = [  # (工单, 类型, 单据, [(状态, 置信度, 版本)…按时间先后])
    ("T-检查-板-甲", "财务人工任务", 押["SH001 静安旗舰店"][0][0], [("待复核", "中", None), ("已采纳", "中", None)]),
    ("T-检查-板-乙", "财务人工任务", 押["SH001 静安旗舰店"][1][0], [("已改判", "高", None)]),
    ("T-检查-板-丙", "客户合并确认", f"{客[0]}|{客[1]}", [("已升级", "中", None)]),
    ("T-检查-板-丁", "售后判责", 修[0], [("待复核", "低", "研判:aaaaaaaaaaaa·系统:bbbbbbbbbbbb")]),
]
for tid, ty, ref, 次 in 造:
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, ty, ref, "待处理", "2026-01-01 10:00:00", "检查"))
    for st, 信, 版 in 次:
        c.execute("INSERT INTO triage(task_id,breakpoint,case_id,created,ai_root_cause,ai_confidence,status,prompt_ver) "
                  "VALUES(?,?,?,?,?,?,?,?)", (tid, "BP-01", tid, "2026-01-01 11:00:00", "检查造的根因", 信, st, 版))
c.commit(); c.close()

部 = B.看板({"no": "x", "role": "总部运营"}, db=db)
g = 部["总体"]
ck("事项数和 AI 运行次数分开数(一件跑两次 = 1 件、2 次)", g["事项数"] == 4 and g["AI运行次数"] == 5, (g["事项数"], g["AI运行次数"]))
ck("采纳率 = 已采纳 ÷(已采纳 + 已改判):升级、待复核都不进分母",
   (g["采纳率"]["分子"], g["采纳率"]["分母"], g["采纳率"]["比例"]) == (1, 2, 50) and g["已升级"] == 1 and g["待复核"] == 1,
   g["采纳率"])
ck("每件事按最后一次研判算(甲先待复核、后采纳 → 算采纳)",
   [x["task_id"] for x in g["下钻"]["已采纳"]] == ["T-检查-板-甲"])
ck("高置信被改判单独数,下钻得到是哪一件", g["高置信被改判"] == 1
   and [x["task_id"] for x in g["下钻"]["高置信被改判"]] == ["T-检查-板-乙"])
ck("分母小于 10 标样本少", g["采纳率"]["样本少"] is True)
ck("按类型拆:三类各自一组", set(部["按类型"]) == {"财务人工任务", "客户合并确认", "售后判责"}
   and 部["按类型"]["财务人工任务"]["事项数"] == 2)
ck("按版本拆:带版本号的一组,没记版本的单独一组,不混", 部["按版本"].get("研判:aaaaaaaaaaaa·系统:bbbbbbbbbbbb", {}).get("事项数") == 1
   and 部["按版本"].get(B.没记版本, {}).get("事项数") == 3, list(部["按版本"]))

长1 = B.看板({"no": "y", "role": "店长", "shop": "SH001 静安旗舰店"}, db=db)
长2 = B.看板({"no": "z", "role": "店长", "shop": "SH002 徐汇店"}, db=db)
ck("店长只看得到本店的事", 长1["总体"]["事项数"] == 2 and 长2["总体"]["事项数"] == 2
   and {x["task_id"] for k in 长1["总体"]["下钻"].values() for x in k} == {"T-检查-板-甲", "T-检查-板-乙"},
   (长1["总体"]["事项数"], 长2["总体"]["事项数"]))
ck("店长看的范围写明是哪家店", 长1["范围"] == "SH001 静安旗舰店" and 部["范围"] == "全部门店")
ck("别的岗位看不了(顾问)", isinstance(抛(lambda: B.看板({"no": "w", "role": "顾问"}, db=db)), PermissionError))
ck("没登录看不了", isinstance(抛(lambda: B.看板({}, db=db)), PermissionError))

服 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
段 = 服[服.index('if p=="/api/triage-board":'):]
段 = 段[:段.index('if p=="/api/triage-config":')]
ck("接口只按登录的人定范围,不收前端传的门店", "_tb.看板(u)" in 段 and "Q.get(" not in 段)
页 = open(os.path.join(ROOT, "agentsite", "web", "triage-board.html"), encoding="utf-8").read()
ck("页面:比例旁边写着分子 / 分母,样本少有标记,数字能下钻",
   "${b.分子}/${b.分母}" in 页 and "样本少" in 页 and "a.dd" in 页 and "/queue?task=" in 页)
队 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("研判队列认 ?task= 直达(下钻点过去能打开那一条)", 'new URLSearchParams(location.search).get("task")' in 队)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判看板:事项和运行分开数、升级不进采纳率分母、店长只看本店、按版本拆、能下钻(验了 {n} 条){D}")
