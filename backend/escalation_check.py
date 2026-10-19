#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判升级 = 正式转交 · 检查(用户 2026-10-17 拍)—— 库副本上自造工单,从升级走到接单 / 退回 / 超时退回 / 复核。

要守的(原来「已升级」算销账:交出去就从待办消失、计时停、又办不结):
  · 升给谁按类型登记,登记不了的不猜;升级必须写原因,不写**整个事务回滚**;
  · 升级后工单**还在待办里**,计时从建单算、不重置;
  · 只有接收岗位能接单 / 退回;退回要写理由;过了 4 个工作小时没人接 → 自动退回原负责人;
  · 接单之后只有接单人能复核;接单人复核完,升级记录办完。
"""
import datetime as dt
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("升级又算成已销账(交上去就从待办消失)", "升级后的工单还在待办里,计时接着走"),
    ("超时没人接不退回", "过了接单期限,自动退回原负责人"),
    ("不是接收岗位也能接单", "不是接收岗位的人接不了单"),
    ("接单后原复核人还能抢着复核", "接单之后只有接单人能复核"),
    ("没写原因也能升级", "没写原因升级被拒,而且研判状态没动"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


def 抛(f):
    try:
        f(); return None
    except Exception as e:                   # noqa: BLE001
        return e


print("研判升级 = 正式转交 · 检查")
print("=" * 80)

import escalation as E, ops, oplog

# ── 一、纯函数:去向 / 工作小时 ─────────────────────────────────────────
ck("退款失败升给总部运营", E.去向("财务人工任务", "店长")[0] == "总部运营")
ck("客户合并升给总部运营", E.去向("客户合并确认", "店长")[0] == "总部运营")
ck("售后判责升给店长", E.去向("售后判责", "售后")[0] == "店长")
ck("店长自己发起的售后单升给总部运营", E.去向("售后判责", "店长")[0] == "总部运营")
ck("总部运营已是最上一级,不能再升", E.去向("财务人工任务", "总部运营")[0] is None)
ck("没登记的类型不猜(差评没拍升给谁)", E.去向("评价差评", "店长")[0] is None)
d = lambda s: dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
ck("营业时间内:09:00 → 当天 14:00(开门才走表)", E.加工作小时(d("2026-01-05 09:00"), 4) == d("2026-01-05 14:00"))
ck("跨打烊:19:00 → 次日 12:00(当天只剩 2 小时)", E.加工作小时(d("2026-01-05 19:00"), 4) == d("2026-01-06 12:00"))
ck("打烊后发起:22:00 → 次日 14:00", E.加工作小时(d("2026-01-05 22:00"), 4) == d("2026-01-06 14:00"))

# ── 二、库副本上走一遍 ─────────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="esc-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
# 副本里先清掉主库上真实的升级记录 —— 「到期退回了几条」数的是全表,
# 主库有人真点过升级的话,别人的那条也会被数进来(10-19 主库多了一条真实升级,门禁当场红)
if c.execute("SELECT 1 FROM sqlite_master WHERE name='escalation'").fetchone():
    c.execute("DELETE FROM escalation")
人 = lambda role: c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 2",
                            (role,)).fetchall()
店长, 总部 = 人("店长"), 人("总部运营")
造 = ["T-检查-升级-甲", "T-检查-升级-乙", "T-检查-升级-丙", "T-检查-升级-旧"]
for tid in 造:
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, "财务人工任务", f"P-{tid}", "待处理", "2026-01-01 10:00:00", "检查"))
c.commit(); c.close()
if not (店长 and 总部):
    ck("库里有在职店长和总部运营 —— 没有就没验,不算通过", False)
else:
    长 = dict(zip(("no", "name", "role"), 店长[0]))
    部 = dict(zip(("no", "name", "role"), 总部[0]))
    研 = {tid: ops.save_triage(tid, "检查", "检查", "根因:检查造的\n建议动作:检查\n证据:无", []) for tid in 造}
    状态 = lambda tid: (ops.get_triage(研[tid]) or {}).get("status")
    行 = lambda tid: next((x for x in ops.queue() if x["task_id"] == tid), {})
    升级数 = lambda tid: sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='escalation'").fetchone()[0] and sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM escalation WHERE triage_id=?", (研[tid],)).fetchone()[0]

    # 甲:没写原因 → 拒,整个事务回滚
    e = 抛(lambda: ops.resolve(研["T-检查-升级-甲"], "已升级", 长, 来源="检查"))
    ck("没写原因升级被拒,而且研判状态没动", isinstance(e, ValueError) and "原因" in str(e)
       and 状态("T-检查-升级-甲") == "待复核" and not 升级数("T-检查-升级-甲"), (e, 状态("T-检查-升级-甲")))
    前 = 行("T-检查-升级-甲")
    ops.resolve(研["T-检查-升级-甲"], "已升级", 长, note="渠道返回码看不懂,要总部对一下", 来源="检查")
    后 = 行("T-检查-升级-甲")
    记 = E.当前(研["T-检查-升级-甲"], db) or {}
    ck("升级登记了一条待接单,交给总部运营,期限 = 发起 + 4 个工作小时",
       记.get("status") == "待接单" and 记.get("to_role") == "总部运营"
       and 记.get("deadline") == E.加工作小时(dt.datetime.strptime(记.get("created"), "%Y-%m-%d %H:%M:%S"), 4)
       .strftime("%Y-%m-%d %H:%M:%S"), 记)
    ck("升级后的工单还在待办里,计时接着走",
       not 后.get("done") and 后.get("level") == 前.get("level") == "已超时"
       and 后.get("waited_h") == 前.get("waited_h") and 后.get("state") == "已升级", (前.get("level"), 后))
    ck("队列那一行带着升级去向和状态", (后.get("升级") or {}).get("去向") == "总部运营"
       and (后.get("升级") or {}).get("状态") == "待接单", 后.get("升级"))
    ck("「已升级」档能单独筛出来", "T-检查-升级-甲" in {x["task_id"] for x in ops.queue("已升级")})
    e = 抛(lambda: E.接单(记["id"], 长))
    ck("不是接收岗位的人接不了单", isinstance(e, PermissionError) and 状态("T-检查-升级-甲") == "已升级", e)
    r = E.接单(记["id"], 部)
    ck("接收岗位接单 → 回到待复核,接单人记下", r.get("ok") and 状态("T-检查-升级-甲") == "待复核"
       and E.接单人(研["T-检查-升级-甲"], db) == 部["no"], r)
    e = 抛(lambda: ops.resolve(研["T-检查-升级-甲"], "已采纳", 长, 来源="检查"))
    ck("接单之后只有接单人能复核", isinstance(e, PermissionError) and 状态("T-检查-升级-甲") == "待复核", e)
    e = 抛(lambda: ops.resolve(研["T-检查-升级-甲"], "已升级", 部, note="再往上", 来源="检查"))
    ck("最上一级再升被拒,接单还在(整个事务回滚)", isinstance(e, ValueError) and 状态("T-检查-升级-甲") == "待复核"
       and E.接单人(研["T-检查-升级-甲"], db) == 部["no"], e)
    ops.resolve(研["T-检查-升级-甲"], "已采纳", 部, 来源="检查")
    ck("接单人复核完 → 升级记录办完、工单销账", (E.当前(研["T-检查-升级-甲"], db) or {}).get("status") == "已复核"
       and 行("T-检查-升级-甲").get("done"), E.当前(研["T-检查-升级-甲"], db))

    # 乙:超时没人接 → 自动退回
    ops.resolve(研["T-检查-升级-乙"], "已升级", 长, note="检查:等它超时", 来源="检查")
    乙 = E.当前(研["T-检查-升级-乙"], db)
    ck("期限之前不退回", E.收超时(dt.datetime.strptime(乙["deadline"], "%Y-%m-%d %H:%M:%S")
                              - dt.timedelta(minutes=1)) == 0 and 状态("T-检查-升级-乙") == "已升级")
    退 = E.收超时(dt.datetime.strptime(乙["deadline"], "%Y-%m-%d %H:%M:%S") + dt.timedelta(minutes=1))
    ck("过了接单期限,自动退回原负责人", 退 >= 1 and (E.当前(研["T-检查-升级-乙"], db) or {}).get("status") == "超时退回"
       and 状态("T-检查-升级-乙") == "待复核", (退, E.当前(研["T-检查-升级-乙"], db)))
    r = E.接单(乙["id"], 部)
    ck("超时退回之后接不了单", not r.get("ok") and "超时退回" in r.get("reason", ""), r)
    e = 抛(lambda: ops.resolve(研["T-检查-升级-乙"], "已采纳", 长, 来源="检查"))
    ck("退回之后原复核人能重新处理", e is None and 状态("T-检查-升级-乙") == "已采纳", e)

    # 丙:接收人写理由退回
    ops.resolve(研["T-检查-升级-丙"], "已升级", 长, note="检查:等它被退回", 来源="检查")
    丙 = E.当前(研["T-检查-升级-丙"], db)
    e = 抛(lambda: E.退回(丙["id"], 部, ""))
    ck("退回不写理由被拒", isinstance(e, ValueError) and 状态("T-检查-升级-丙") == "已升级", e)
    r = E.退回(丙["id"], 部, "流水对得上,不需要总部,店里按标准处理")
    ck("写理由退回 → 回到待复核,理由留着", r.get("ok") and 状态("T-检查-升级-丙") == "待复核"
       and (E.当前(研["T-检查-升级-丙"], db) or {}).get("return_note"), r)

    # 旧数据:10-17 之前「已升级」的,没有升级记录
    with sqlite3.connect(db) as cx:
        cx.execute("UPDATE triage SET status='已升级' WHERE id=?", (研["T-检查-升级-旧"],))
    旧 = 行("T-检查-升级-旧")
    ck("没有接收人的旧「已升级」不再算销账,标出来", not 旧.get("done")
       and (旧.get("升级") or {}).get("状态", "").startswith("旧数据"), 旧.get("升级"))
shutil.rmtree(tmp, ignore_errors=True)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("页面:升级要写原因、能接单 / 退回", "升级原因" in 页 and "/api/ops-escalation" in 页 and "办升级(" in 页)
ck("页面不再把「已升级」当成有结论", '["已采纳","已改判","已升级"].includes(d.status)' not in 页)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判升级:有接收人、有期限、超时退回、接单人复核、计时不停(验了 {n} 条){D}")
