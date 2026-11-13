# -*- coding: utf-8 -*-
"""费用到 80% 给店长派「费用提醒」(cost_alert.py,用户 11-13 拍第三十八条)守得住吗。在库副本上真派、回读那一行。

    python3 backend/cost_alert_check.py

  ① 正常 → 不派;合计拿不到 → 不派(不知道花了多少,不能说「过了 80%」)
  ② 提醒 → 给工号所在店的在职店长派一条:类型「费用提醒」、ref_id = 月份、派给店长、说明里有金额和上限
  ③ 同月再推 → 不重派(每月每店一次);下个月 → 再派
  ④ 两家店的工号 → 两家店长各一条;没在花名册的工号 → 不派也不崩
  ⑤ 到顶 → 也派(说明写「到了上限」)
  ⑥ 接线:聊天站 /run 记完门店用量账后调 cost_alert.推(读 app.py 语法树)
"""
import ast
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cost_alert as CA  # noqa: E402

咬合 = [
    ("同月同店不查重(每次都派)", "③ 同月再推 → 不重派"),
    ("80% 那一档不派(只到顶才派)", "② 提醒 → 派一条给那家店的店长"),
    ("聊天站记完账不推费用提醒", "⑥ 接线 · /run 记完门店用量账后推费用提醒"),
]

坏 = []
验 = 0
def ck(名, ok, 说明=""):
    global 验
    验 += 1
    print(("  ✅ " if ok else "  ❌ ") + 名 + ("" if ok else f" —— {说明}"))
    if not ok:
        坏.append(名)

print("=== 费用提醒派给店长(库副本)===")
副本 = os.path.join(tempfile.mkdtemp(prefix="cost-alert-check-"), "lanxiu.db")
with sqlite3.connect(CA.DB) as 源, sqlite3.connect(副本) as 目:
    源.backup(目)
c = sqlite3.connect(副本)
店长们 = dict(c.execute("SELECT shop, no FROM staff WHERE role='店长' AND status='启用' ORDER BY no").fetchall()[::-1])
顾问 = c.execute("SELECT no, shop FROM staff WHERE role='顾问' AND status='启用' AND shop IS NOT NULL ORDER BY no").fetchall()
甲 = next((x for x in 顾问 if x[1] in 店长们), None)
乙 = next((x for x in 顾问 if x[1] in 店长们 and 甲 and x[1] != 甲[1]), None)
ck("样本:至少两家店有在职顾问和店长", bool(甲 and 乙), f"甲 {甲} 乙 {乙}")
if not (甲 and 乙):
    print(f"❌ 样本不够,{len(坏)} 条不过"); sys.exit(1)

def 数(月, 店=None):
    q, a = "SELECT COUNT(*) FROM schedule WHERE type='费用提醒' AND ref_id=?", [月]
    if 店:
        q += " AND shop=?"; a.append(店)
    return c.execute(q, a).fetchone()[0]

月 = "2031-03"
ck("① 正常 → 不派", CA.派(c, 月, 50.0, 150, "正常", [甲[0]], "2031-03-10") == [] and 数(月) == 0)
ck("① 合计拿不到 → 不派", CA.派(c, 月, None, 150, "拿不到", [甲[0]], "2031-03-10") == [] and 数(月) == 0)
ck("① 状态是提醒但合计 None → 不派", CA.派(c, 月, None, 150, "提醒", [甲[0]], "2031-03-10") == [] and 数(月) == 0)

出 = CA.派(c, 月, 121.5, 150, "提醒", [甲[0]], "2031-03-10")
行 = c.execute("SELECT type, assignee_no, ref_id, shop, assigned_by, note FROM schedule WHERE type='费用提醒' AND ref_id=?",
              (月,)).fetchall()
ck("② 提醒 → 派一条给那家店的店长", len(行) == 1 and 行[0][1] == 店长们[甲[1]] and 行[0][3] == 甲[1] and 行[0][4] == "SYS",
   f"{出} / {行}")
ck("② 说明里有金额、上限和 80%", bool(行) and "121.50" in 行[0][5] and "150" in 行[0][5] and "80%" in 行[0][5], 行)

CA.派(c, 月, 130.0, 150, "提醒", [甲[0]], "2031-03-11")
ck("③ 同月再推 → 不重派", 数(月) == 1, f"有 {数(月)} 条")
CA.派(c, "2031-04", 125.0, 150, "提醒", [甲[0]], "2031-04-02")
ck("③ 下个月 → 再派", 数("2031-04") == 1)

CA.派(c, "2031-05", 125.0, 150, "提醒", [甲[0], 乙[0], "不存在的工号"], "2031-05-02")
ck("④ 两家店的工号 → 两家店长各一条;没在花名册的工号不崩", 数("2031-05", 甲[1]) == 1 and 数("2031-05", 乙[1]) == 1
   and 数("2031-05") == 2)

CA.派(c, "2031-06", 150.0, 150, "到顶", [甲[0]], "2031-06-02")
到 = c.execute("SELECT note FROM schedule WHERE type='费用提醒' AND ref_id='2031-06'").fetchone()
ck("⑤ 到顶 → 也派,说明写到了上限", bool(到) and "到了每月上限" in 到[0], 到)

src = open(os.path.join(HERE, "..", "agentsite", "app.py"), encoding="utf-8").read()
推了 = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "推"
          and getattr(n.func.value, "id", "") == "_ca2" for n in ast.walk(ast.parse(src)))
ck("⑥ 接线 · /run 记完门店用量账后推费用提醒", 推了 and "import cost_alert as _ca2" in src)

c.close()
print(f"\n验了 {验} 条")
if 坏:
    print(f"❌ {len(坏)} 条不过"); sys.exit(1)
print("✅ 全过")
