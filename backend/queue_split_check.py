#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判队列 / 值班台「差评待店长确认」分流 · 检查 —— 库副本上自造形状。

用户 2026-10-15:「给我做几个能跑的呀,不能跑的放在研判队列干啥?」
那天队列「未研判」171 条**全是评价差评**(差评按业务 10-10 拍板不走 AI),能跑的三类早就研判完了 ——
用户点进来一条能试的都没有。拍了:研判队列只放 AI 能跑的,差评挪到值班台。

要守的:
  · 研判队列里**没有**不能跑的(判定用 `能跑AI研判`,和真跑那处同一份);
  · **一条不丢**:研判队列 + 不走 AI 的 = 全部工单,不重不漏 ——
    「差评不见了」和「差评被挪走了」在研判队列那一页上长得一模一样,只有对得上总数才分得开;
  · 研判队列页**说了**挪去哪(否则用户看到的就是「差评不见了」)。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("研判队列不按能不能跑筛(差评又摆回研判队列)", "研判队列里没有不能跑的"),
    ("待店长确认漏掉还开着的差评", "自造的开着的差评落在值班台那一块"),
    ("「未研判」档不看 done(关掉的单又会被挑去重跑)", "已经关单、没研判过的,不在「未研判」档"),
    ("复核写回去掉状态条件(后到的悄悄盖掉先到的)", "同一条研判复核第二次被拒"),
    ("研判又把根因写进工单处理记录", "研判落库不动工单的处理记录"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("研判队列 / 差评待店长确认 分流 · 检查")
print("=" * 80)

import ops, oplog
tmp = tempfile.mkdtemp(prefix="qsplit-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
c = sqlite3.connect(db)
造 = {"差评": ("T-检查-分流-差评", "评价差评"), "财务": ("T-检查-分流-财务", "财务人工任务")}
for tid, typ in 造.values():
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
              (tid, typ, f"P-{tid}", "待处理", "2026-01-01 10:00:00", "检查"))
# 关了但没研判过的一条能跑的 —— 外部核查 10-15 指出「未研判」档会把它挑去重跑
c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
          ("T-检查-分流-已关", "财务人工任务", "P-已关", "已关闭", "2026-01-01 10:00:00", "检查"))
店长 = c.execute("SELECT no, name, role FROM staff WHERE role='店长' AND status='启用' LIMIT 1").fetchone()
c.commit(); c.close()

全 = ops.queue()
研 = ops.研判队列(全)
人 = ops.待店长确认(全)
不能跑 = [x for x in 全 if not x["能跑AI研判"]]
ids = lambda xs: {x["task_id"] for x in xs}
print(f"     ℹ️ 库副本上:全部 {len(全)} · 研判队列 {len(研)} · 不走 AI {len(不能跑)}(其中开着 {人['开着']})")

ck("研判队列里没有不能跑的", all(x["能跑AI研判"] for x in 研), [x["task_id"] for x in 研 if not x["能跑AI研判"]][:3])
ck("一条不丢:研判队列 + 不走 AI 的 = 全部工单,不重不漏",
   not (ids(研) & ids(不能跑)) and (ids(研) | ids(不能跑)) == ids(全) and len(全) > 0,
   (len(研), len(不能跑), len(全)))
ck("自造的开着的差评落在值班台那一块", 造["差评"][0] in ids(人["rows"]))
ck("自造的财务工单留在研判队列", 造["财务"][0] in ids(研))
ck("值班台那一块只列还开着的", all(not x["done"] for x in 人["rows"]))
ck("「没走正门关的」计数跟着搬过来,和逐行标记对得上",
   人["没走正门关的"] == sum(1 for x in 不能跑 if x.get("没走正门")))
ck("已经关单、没研判过的,不在「未研判」档", "T-检查-分流-已关" not in ids(ops.queue("未研判"))
   and "T-检查-分流-已关" in ids(全))

# 复核写回只认「待复核」那一刻(外部核查 10-15 指出:原来按 id 直接覆盖,后到的悄悄盖掉先到的)
if 店长:
    我 = dict(no=店长[0], name=店长[1], role=店长[2])
    tr = ops.save_triage(造["财务"][0], "检查", "检查", "根因:检查造的\n建议动作:检查\n证据:无", [])
    记录 = lambda: sqlite3.connect(db).execute("SELECT summary FROM task WHERE id=?", (造["财务"][0],)).fetchone()[0]
    ck("研判落库不动工单的处理记录(AI 根因不冒充办结记录)", 记录() == "检查", 记录())
    with sqlite3.connect(db) as cx:
        cx.execute("UPDATE triage SET ai_root_cause='' WHERE id=?", (tr,))
    ops.reparse()
    ck("重解析补出根因后也不回写处理记录", 记录() == "检查"
       and (ops.get_triage(tr) or {}).get("ai_root_cause"), (记录(), (ops.get_triage(tr) or {}).get("ai_root_cause")))
    ops.resolve(tr, "已采纳", 我, 来源="检查")
    try:
        ops.resolve(tr, "已改判", 我, root_cause="检查", 来源="检查"); 第二次 = None
    except ValueError as e:
        第二次 = str(e)
    ck("同一条研判复核第二次被拒", bool(第二次) and "已经是" in 第二次, 第二次)
    ck("被拒之后结论还是第一次那个(没被盖掉)", (ops.get_triage(tr) or {}).get("status") == "已采纳")
else:
    ck("库里有在职店长(复核要店长)—— 没有就没验,不算通过", False)
shutil.rmtree(tmp, ignore_errors=True)

页 = open(os.path.join(ROOT, "agentsite", "web", "queue.html"), encoding="utf-8").read()
ck("研判队列页说了不走 AI 的挪去哪(否则看着就是「差评不见了」)", "挪到值班台" in 页 and "/duty#差评" in 页)
app = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
ck("研判入口拦已经结束的工单(不重跑)", 'if t.get("done"):' in app)
值 = open(os.path.join(ROOT, "agentsite", "web", "duty.html"), encoding="utf-8").read()
ck("值班台有「差评待店长确认」那一块,取的是同一份分流", 'id="差评"' in 值 and "/api/ops-manual" in 值)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判队列只放能跑的,差评挪到值班台、一条不丢(验了 {n} 条){D}")
