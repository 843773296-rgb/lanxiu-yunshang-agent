# -*- coding: utf-8 -*-
"""门店用量账 + 费用闸(store_usage.py)守得住吗。不调模型、不碰真账(账目录指到临时目录)。

    python3 agentsite/store_usage_check.py

  ① 闸的四态,边界值逐个钉:拿不到(None)→ 照常升级(用户 11-13 拍)/ 0 → 正常 / 120(=80%)→ 提醒 /
     149.99 → 提醒 / 150(=上限)→ 到顶、**不升级**
  ② 账:没文件 = 0(还没人用,不是拿不到);两笔相加;有一笔金额未知 → 拿不到(**不当 0 算**);坏行 → 拿不到
  ③ 上限和管理后台上线验收页是同一个数(两个服务各写了一份,对不上就红)
  ④ 接线:聊天站 /run 在升级前问了费用闸、到顶时不升级;答完记账(读 app.py 语法树)
"""
import ast
import datetime
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["LANXIU_STORE_USAGE_DIR"] = tempfile.mkdtemp(prefix="store-usage-check-")
import store_usage as S  # noqa: E402

咬合 = [
    ("到顶判成 > 上限(正好 150 还照升)", "② 闸 · 150(正好上限)→ 到顶,不升级"),
    ("金额未知的那笔当 0 算", "账 · 有一笔金额未知 → 拿不到(不当 0)"),
    ("聊天站升级前不看费用闸", "④ 接线 · /run 升级前问费用闸,到顶就交小模型那一遍"),
]

坏 = []
def ck(名, ok, 说明=""):
    print(("  ✅ " if ok else "  ❌ ") + 名 + ("" if ok else f" —— {说明}"))
    if not ok:
        坏.append(名)

print("=== 门店用量账 + 费用闸 ===")
上 = S.月上限
for 额, 态, 升, 名 in ((None, "拿不到", True, "① 闸 · 拿不到 → 照常升级"),
                     (0, "正常", True, "② 闸 · 0 → 正常"),
                     (上 * S.提醒比例, "提醒", True, "② 闸 · 正好 80% → 提醒"),
                     (上 - 0.01, "提醒", True, "② 闸 · 差一分到顶 → 提醒、照升"),
                     (上, "到顶", False, "② 闸 · 150(正好上限)→ 到顶,不升级"),
                     (上 + 40, "到顶", False, "② 闸 · 超过上限 → 到顶,不升级")):
    g = S.闸(额)
    ck(名, g["状态"] == 态 and g["可升级"] is 升 and g["说明"], f"得到 {g}")

d = datetime.date(2031, 3, 15)
ck("账 · 这个月没文件 → 0(不是拿不到)", S.本月(d)[0] == 0.0)
S.记("t1", 0.25, "A01", "m", 今天=d); S.记("t2", 1.5, "A01", "m", 今天=d)
合, 笔, _ = S.本月(d)
ck("账 · 两笔相加", 合 == 1.75 and 笔 == 2, f"{合} / {笔}")
S.记("t3", None, "A01", "m", 今天=d)
ck("账 · 有一笔金额未知 → 拿不到(不当 0)", S.本月(d)[0] is None, f"{S.本月(d)}")
d2 = datetime.date(2031, 4, 2)
S.记("t4", 0.1, 今天=d2)
with open(S._文件(S._月(d2)), "a", encoding="utf-8") as f:
    f.write("{坏行\n")
ck("账 · 有坏行 → 拿不到", S.本月(d2)[0] is None, f"{S.本月(d2)}")
ck("账 · 现在() 读账出问题也不抛,落在拿不到/照升", S.现在(d2)["可升级"] is True and S.现在(d2)["状态"] == "拿不到")

AF = os.path.join(HERE, "..", "管理后台", "services", "api", "app", "acceptance_flow.py")
m = re.search(r"^月费用上限\s*=\s*([\d.]+)", open(AF, encoding="utf-8").read(), re.M)
ck("③ 上限和管理后台上线验收页是同一个数", bool(m) and float(m.group(1)) == float(上),
   f"验收页 {m and m.group(1)} / 聊天站 {上}")

src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
t = ast.parse(src)
问闸 = 记账 = 看可升级 = False
for n in ast.walk(t):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and getattr(n.func.value, "id", "") == "_su":
        问闸 |= n.func.attr == "现在"
        记账 |= n.func.attr == "记"
    if isinstance(n, ast.If):
        seg = ast.get_source_segment(src, n.test) or ""
        if "可升级" in seg and "升" in seg:
            # 那一支里交出去的必须是小模型那一遍(r = r0)
            看可升级 |= any(isinstance(b, ast.Assign) and getattr(b.value, "id", "") == "r0" for b in n.body)
ck("④ 接线 · /run 升级前问费用闸,到顶就交小模型那一遍", 问闸 and 看可升级, f"问闸 {问闸} · 到顶交 r0 {看可升级}")
ck("④ 接线 · /run 答完记门店用量账", 记账)

print("\n验了 14 条")
if 坏:
    print(f"❌ {len(坏)} 条不过"); sys.exit(1)
print("✅ 全过")
