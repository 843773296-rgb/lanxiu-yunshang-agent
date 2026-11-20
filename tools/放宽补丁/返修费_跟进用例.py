#!/usr/bin/env python3
"""用户跑完 返修费_问一下与话术闸.py 之后,由 Claude 跑这个:补回归用例 + 咬合规格(都是收紧侧,不用用户跑)。
补丁没落(guards.py 里没有标记)就拒跑 —— 否则「该放」那几条会当场红。"""
import io, json, os, sys
R = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
G = os.path.join(R, "agentsite", "guards.py"); T = os.path.join(R, "agentsite", "guards_test.py")
B = os.path.join(R, "tools", "bite_specs.json")
g = io.open(G, encoding="utf-8").read()
if "返修费_问一下与话术闸.py):这一轮查的是返修" not in g:
    print("❌ 拒跑:补丁还没落(guards.py 里没有标记)"); sys.exit(1)
t = io.open(T, encoding="utf-8").read()
if "11-20 夜跑返修 N03" in t:
    print("ℹ️ 用例已经补过了"); sys.exit(0)

# ① g30:在原五条对照的最后一条后面接两条
锚30 = '''        ("**反向** · 顾客这一问不谈钱(问工期)→ 不管", "顾客问能不能提前取?", [], _规TL60, False)]:'''
新30 = '''        ("**反向** · 顾客这一问不谈钱(问工期)→ 不管", "顾客问能不能提前取?", [], _规TL60, False),
        # 用户 11-20 跑的放宽(tools/放宽补丁/返修费_问一下与话术闸.py):返修费不是谈价
        ("**反向** · 查过返修单、问句里的钱是返修费 → 放过(11-20 夜跑返修 N03)",
         "返修单 MX1 判给顾客,返修,预估 300 块,直接开工吧。", [{"tool": "mcp__shop__get_maintain"}], _规TL60, False),
        ("查过返修单但拿不开票换价 → 照旧打回(放宽不许连带放掉)",
         "返修单 MX1 这件 300 块,不开票能便宜点吗?", [{"tool": "mcp__shop__get_maintain"}], _规TL60, True)]:'''
# ② g23 第二层:接在 11-14 那组 CASES 后面
锚23 = '''# ── 软性让价:不带折扣词,但把价格推给别人 / 推到以后(业务 2026-09-25 拍板)────'''
新23 = '''# ── 2026-11-20 用户亲手跑的放宽(tools/放宽补丁/返修费_问一下与话术闸.py):「问一下:」是在直接问对方 ──
CASES += [
 (False, None, "「现在问一下:顾客已经同意付 300 块了吗?」是在问店长,不是把价格往后推(11-20 夜跑返修 N03 原文)",
  "判给顾客前要确认**顾客已经同意付 300 块**。\\n\\n**现在问一下:顾客已经同意付 300 块返修费了吗?** 是怎么确认的?", []),
 (True,  "g23_discount_promise", "「我帮您问一下:能不能少点」是替顾客去问第三方:照拦",
  "4956 元是有点贵,我帮您问一下:能不能少一点。", []),
]

''' + 锚23
for 名, 锚 in (("g30", 锚30), ("g23", 锚23)):
    if t.count(锚) != 1:
        print(f"❌ {名} 锚在 guards_test.py 出现 {t.count(锚)} 次"); sys.exit(1)
t = t.replace(锚30, 新30).replace(锚23, 新23)

specs = json.load(io.open(B, encoding="utf-8"))
新规格 = [
 {"script": "agentsite/guards_test.py",
  "改坏": "g30 返修放宽那支不再看问句里有没有折扣词 / 不开票换价 —— 返修对话里拿开票换价也不用读话术了",
  "file": [{"path": "agentsite/guards.py",
            "old": "            and not (re.search(折扣词, prompt) or 不开票换钱.search(prompt)):",
            "new": "            and True:"}],
  "预期红": "查过返修单但拿不开票换价 → 照旧打回"},
 {"script": "agentsite/guards_test.py",
  "改坏": "g23 第二层「问一下:」放宽不再看前面有没有 帮 / 替 / 去 —— 「我帮您问一下:能不能少点」被放过",
  "file": [{"path": "agentsite/guards.py",
            "old": '                and not re.search(r"[去帮替跟向给]", text[max(0, m.start() - 4):m.start()]):',
            "new": "                and True:"}],
  "预期红": "「我帮您问一下:能不能少点」是替顾客去问第三方"},
]
for s in 新规格:
    o = s["file"][0]["old"]
    if g.count(o) != 1:
        print(f"❌ 咬合攻击点在 guards.py 出现 {g.count(o)} 次:{o[:40]}"); sys.exit(1)
specs += 新规格
io.open(T, "w", encoding="utf-8").write(t)
io.open(B, "w", encoding="utf-8").write(json.dumps(specs, ensure_ascii=False, indent=1) + "\n")
print("✅ guards_test 补 4 条(g30 该放1/该拦1,g23 该放1/该拦1)+ 咬合规格 2 条")
