#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""售后 / 客户合并的办结入口 · 检查(研判队列未做项第 7 项)—— 库副本上自造工单,从复核走到办结。

要守的(原来页面只给退款接了办结,另两类复核完就停在「已采纳」,办结永远进不去):
  · 页面画办结块靠后端的 `ops.办结预检`:认什么单、单号是哪张、够不够、谁办 —— 页面不按类型猜;
  · 回执就是工单挂的那张单 → 预检直接给出单号;单据没走完 → 说清差什么,不算够;
  · 复核没完的不能办结;不是办结那一段的角色办不了;办完之后预检报「已办结」。
"""
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
    ("预检不看维保单状态(没完成也说够了)", "维保单没完成 → 预检说还办不了,并说出差在哪"),
    ("页面把售后 / 合并的办结块拿掉", "页面:已有结论的非退款工单画办结块,照后端预检画"),
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


print("售后 / 客户合并的办结入口 · 检查")
print("=" * 80)

import ops, oplog

tmp = tempfile.mkdtemp(prefix="close-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
人 = lambda role: c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1",
                            (role,)).fetchone()
售后, 店长, 总部 = 人("售后"), 人("店长"), 人("总部运营")
完 = c.execute("SELECT id FROM maintain WHERE status='已完成' ORDER BY id LIMIT 1").fetchone()
没完 = c.execute("SELECT id FROM maintain WHERE status='待处理' ORDER BY id LIMIT 1").fetchone()
对 = c.execute("SELECT a.id, b.id FROM customer a JOIN customer b ON b.id > a.id ORDER BY a.id, b.id LIMIT 1").fetchone()
造 = {}
if 完 and 没完 and 对:
    for tid, ty, ref in (("T-检查-办结-完", "售后判责", 完[0]), ("T-检查-办结-没完", "售后判责", 没完[0]),
                         ("T-检查-办结-未复核", "售后判责", 完[0]), ("T-检查-办结-合并", "客户合并确认", f"{对[0]}|{对[1]}")):
        c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
                  (tid, ty, ref, "待处理", "2026-01-01 10:00:00", "检查"))
        造[tid] = ref
c.commit(); c.close()

if not (售后 and 店长 and 总部 and 造):
    ck("库里有售后 / 店长 / 总部运营、已完成和待处理的维保单、一对客户 —— 没有就没验,不算通过", False,
       (售后, 店长, 总部, 完, 没完, 对))
else:
    后 = dict(zip(("no", "name", "role"), 售后))
    长 = dict(zip(("no", "name", "role"), 店长))
    部 = dict(zip(("no", "name", "role"), 总部))
    研 = {tid: ops.save_triage(tid, "检查", "检查", "根因:检查造的\n建议动作:检查\n证据:无", []) for tid in 造}
    ops.resolve(研["T-检查-办结-完"], "已采纳", 后, 来源="检查")
    ops.resolve(研["T-检查-办结-没完"], "已采纳", 后, 来源="检查")
    ops.resolve(研["T-检查-办结-合并"], "已采纳", 长, 来源="检查")

    p = ops.办结预检(研["T-检查-办结-完"]) or {}
    ck("维保单已完成 → 预检给出单号(就是工单挂的那张)、说够了、谁办 = 售后",
       p.get("单号") == 造["T-检查-办结-完"] and p.get("行不行") is True and p.get("回执类型") == "维保单"
       and p.get("谁办") == ["售后"] and not p.get("已办结"), p)
    p = ops.办结预检(研["T-检查-办结-没完"]) or {}
    ck("维保单没完成 → 预检说还办不了,并说出差在哪",
       p.get("行不行") is False and "还没完成" in (p.get("为什么") or "") and p.get("单号") == 造["T-检查-办结-没完"], p)
    p = ops.办结预检(研["T-检查-办结-未复核"]) or {}
    ck("还没复核的 → 预检说先复核,不给单号", p.get("行不行") is False and not p.get("单号")
       and "复核" in (p.get("为什么") or ""), p)
    p = ops.办结预检(研["T-检查-办结-合并"]) or {}
    ck("客户合并 → 单号是那一对、谁办 = 总部运营、没合并就说还没合并",
       p.get("单号") == 造["T-检查-办结-合并"] and p.get("谁办") == ["总部运营"] and p.get("行不行") is False
       and "还没合并" in (p.get("为什么") or ""), p)

    e = 抛(lambda: ops.办结(研["T-检查-办结-完"], 造["T-检查-办结-完"], 长, 来源="检查"))
    ck("不是办结那一段的角色办不了(店长办售后)", isinstance(e, PermissionError), e)
    r = ops.办结(研["T-检查-办结-没完"], 造["T-检查-办结-没完"], 后, 来源="检查")
    ck("维保单没完成,点了也办不了(后端照样拦)", r.get("ok") is False and r.get("code") == "NO_RECEIPT", r)
    r = ops.办结(研["T-检查-办结-完"], 造["T-检查-办结-完"], 后, 来源="检查")
    p = ops.办结预检(研["T-检查-办结-完"]) or {}
    ck("售后凭维保单办结 → 预检报已办结、带着回执", r.get("ok") and p.get("已办结")
       and 造["T-检查-办结-完"] in (p.get("回执") or ""), (r, p))
shutil.rmtree(tmp, ignore_errors=True)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("页面:已有结论的非退款工单画办结块,照后端预检画",
   'x.type!=="财务人工任务" && d.办结) ? 办结块(d.办结' in 页 and "function 办结块(" in 页)
ck("页面:办结按钮走 /api/ops-close,失败不出成功样式",
   'data-close' in 页 and '"/api/ops-close"' in 页 and "r.ok===false" in 页)
服 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
ck("详情接口带上办结预检", "办结=_ops.办结预检(" in 服)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 售后 / 合并办结入口:预检照实说、角色和回执由后端判、页面照着画(验了 {n} 条){D}")
