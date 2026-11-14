# -*- coding: utf-8 -*-
"""研判示例库「表面一样、根因不同」反例清单 · 检查(11-15 夜加)。

`agent/example-counter-cases.json` 的说明里写着规矩 ——「每类至少 3 条:1 条进示例池、其余留评测」——
而**没有任何东西拦它**。这份清单是手改的(用户 11-14 拍:保留后期编辑 / 添加的能力),手改就会出这几种错,
而每一种在对比结果上都**长得像「示例有用 / 没用」**:

  · 某一根因 0 条进示例池 → 开 / 关示例那一类没区别,读成「示例没用」
  · 某一根因 2 条都进示例池 → 评测里没这一类,总分照出、而且更高
  · 编号和冻结切分撞上 → 带示例时模型看到这道题自己的答案(对比脚本的 assert 只在**真跑时**才炸)
  · 模板单据库里没有 → 对比脚本跑到一半才 SystemExit,前面花的模型调用白花
  · 「改」里写了造法不认的键 → **静默不改**,于是那道「反例」和模板一模一样,答案却标成了另一个根因

这份检查只读:读清单 + 只读打开真库查模板在不在,不造副本、不调模型。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent")]
清单文件 = os.path.join(ROOT, "agent", "example-counter-cases.json")
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], [0]

咬合 = [
    ("把某一根因唯一那条进示例池的改成「评测」", "每个根因至少 3 条、恰好 1 条进示例池"),
    ("把一条反例的编号改成冻结切分里已有的号", "反例编号不和冻结切分撞号"),
    ("把一条合并反例的模板改成库里没有的工单", "每条反例的模板单据都在库里"),
    ("在一条合并反例的「改」里写一个造法不认的键", "「改」里只有造法认得的键"),
]

# 造法认得的键 —— 照 agent/example_counter_ab.py 造到副本() 那三支抄的。
# ⚠️ 那边加了新键这里要跟着加;**这边没登记的键一律红**(宁可多红一次,也不许静默不改)
认得的键 = {
    "BP-01": {"删成功出账"},
    "BP-02": {"同一账户"},
    # 售后那一支是「改」里每个键直接写进维修单同名的列 —— **不是列名的键,INSERT 只按列取,静默丢掉**。
    # 所以这一支认得的就是 maintain 的列(下面从库里现读,不抄一份)
    "BP-03": None,
}


def ck(名, ok, 附=""):
    n[0] += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:240]}" if 附 else ""))


print("研判示例库 · 反例清单检查")
print("=" * 80)
案 = json.load(open(清单文件, encoding="utf-8"))
例 = 案.get("案例") or []
ck("反例清单不是空的(验了几条要先报 —— 空清单上下面每一条都成立)", len(例) >= 10, f"{len(例)} 条")

# ① 每个根因至少 3 条、恰好 1 条进示例池
from collections import defaultdict
组 = defaultdict(list)
for x in 例:
    组[(x.get("bp"), x.get("根因"))].append(x)
不够 = [f"{k[1]}:{len(v)} 条、进示例池 {sum(1 for y in v if y.get('进') == '示例池')} 条"
        for k, v in sorted(组.items()) if len(v) < 3 or sum(1 for y in v if y.get("进") == "示例池") != 1]
ck("每个根因至少 3 条、恰好 1 条进示例池", not 不够,
   不够 or f"{len(组)} 个根因,每个都是 1 条示例 + ≥2 条评测")
野 = [x.get("id") for x in 例 if x.get("进") not in ("示例池", "评测")]
ck("「进」只有「示例池」「评测」两种取值", not 野, 野)

# ② 编号唯一、不和冻结切分撞号
号 = [x.get("id") for x in 例]
重 = sorted({h for h in 号 if 号.count(h) > 1})
ck("反例编号不重复", not 重, 重)
import example_pool as E
冻 = E.冻结的()
已有 = {x["case_id"] for x in 冻["示例池"]} | {x["case_id"] for x in 冻["评测"]}
撞 = sorted(set(号) & 已有)
ck("反例编号不和冻结切分撞号", not 撞, 撞 or f"冻结切分 {len(已有)} 个号,一个没撞")

# ③ 模板在库里(只读打开)
库 = os.path.join(HERE, "lanxiu.db")
c = sqlite3.connect(f"file:{库}?mode=ro", uri=True)
缺 = []
for x in 例:
    模, bp = x.get("模板"), x.get("bp")
    if bp == "BP-01":
        有 = c.execute("SELECT 1 FROM deposit WHERE id=?", (模,)).fetchone() and \
             c.execute("SELECT 1 FROM task WHERE id=?", ("T" + str(模),)).fetchone()
    elif bp == "BP-02":
        t = c.execute("SELECT ref_id FROM task WHERE id=?", ("T" + str(模),)).fetchone()
        有 = bool(t and t[0] and "|" in t[0]) and all(
            c.execute("SELECT 1 FROM customer WHERE id=?", (h,)).fetchone() for h in t[0].split("|"))
    elif bp == "BP-03":
        有 = c.execute("SELECT 1 FROM maintain WHERE id=?", (模,)).fetchone() and \
             c.execute("SELECT 1 FROM task WHERE id=?", ("T" + str(模),)).fetchone()
    else:
        有 = False
    if not 有:
        缺.append(f"{x.get('id')}({bp} 模板 {模})")
认得的键["BP-03"] = {r[1] for r in c.execute("PRAGMA table_info(maintain)")}
c.close()
ck("每条反例的模板单据都在库里", not 缺, 缺 or f"{len(例)} 条的模板都查得到")

# ④ 「改」里只有造法认得的键
不认 = [f"{x.get('id')}:{sorted(set((x.get('改') or {})) - (认得的键.get(x.get('bp')) or set()))}"
        for x in 例 if set((x.get("改") or {})) - (认得的键.get(x.get("bp")) or set())]
ck("「改」里只有造法认得的键", not 不认,
   不认 or "**造法不认的键会被静默跳过** —— 那道反例就和模板一模一样,而答案标成了另一个根因")

print()
if bad:
    print(f"{R}❌ 反例清单 {len(bad)} 条不过(验了 {n[0]} 条){D}")
    sys.exit(1)
print(f"{G}✅ 反例清单 {n[0]} 条全过{D}({len(例)} 条反例、{len(组)} 个根因)")
