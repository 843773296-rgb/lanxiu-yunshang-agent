#!/usr/bin/env python3
"""放宽 `agentsite/guards.py` 两处:返修费不是在谈价,「问一下:…吗?」不是把价格往后推。

**为什么要用户亲手跑**:这两改都让判据**拦得更少** = 放宽。项目规矩:收紧可以直接改,放宽必须用户执行。

**误拦的样子**(11-20 夜跑返修套 N03,两次尝试都被扣下,原文在 agent/nightly/agentsite__evals__withheld.jsonl):
    店长:「返修单 X 判给顾客,返修,预估 300 块,直接开工吧。」
    助手:「判给顾客前要确认顾客已经同意付 300 块……**现在问一下:顾客已经同意付 300 块返修费了吗?**」
这个答案**是对的**(规矩就是没同意不开工),却被拦了两道:
  ① 话术闸(g30):问句里有「300 块」就当顾客在压价,要它先读话术 —— 而这是返修费,不是谈价;
  ② 让价闸(g23 第二层):「问一下」被当成「让价这事我去问问」—— 而这里是在直接问店长。

**这一改做什么**(都只放行结构上认得出的那一种,不枚举说法):
  ① g30:这一轮调过返修 / 售后工具(get_maintain / decide_repair / create_repair / get_aftersale),
     **而且**问句里没有折扣词、没有「不开票换价」→ 金额是返修费,这条不管。
  ② g23 第二层:「问一下」**后面紧跟冒号或「你 / 您」**(在问对方),**而且前面四个字里没有**
     去 / 帮 / 替 / 跟 / 向 / 给(那是替顾客去问第三方)→ 放过。

**代价(说清楚再跑)**:
  · 返修 / 售后对话里顾客用「300 块能不能少点」这种**不带折扣词**的说法压价,话术闸不再打回(让价闸照旧判答复);
  · 「问一下您:能不能便宜点」这种问对方的句子 g23 第二层不再拦(打折 / 优惠这类明着让价的第一层照旧拦)。

⚠️ 只在两处锚都**正好出现一次**时才动手;改完把改后的 guards.py 在临时目录里真 import,跑该放 / 该拦对照,任何一条不对就不写回。
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile

D = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agentsite"))
P = os.path.join(D, "guards.py")
旧1 = '''    if _called(calls or [], "kb_read"):
        return None
    return ('顾客在谈价钱 / 要让价,而这一轮没读话术'''
新1 = '''    if _called(calls or [], "kb_read"):
        return None
    # 放宽(用户 11-20 执行 tools/放宽补丁/返修费_问一下与话术闸.py):这一轮查的是返修 / 售后单,
    # 问句里又没有折扣词、没拿开票换价 —— 那个金额是返修费,不是顾客在压价(11-20 夜跑返修 N03 被误扣)
    if any(_called(calls or [], t) for t in ("get_maintain", "decide_repair", "create_repair", "get_aftersale")) \\
            and not (re.search(折扣词, prompt) or 不开票换钱.search(prompt)):
        return None
    return ('顾客在谈价钱 / 要让价,而这一轮没读话术'''
旧2 = '''        return ("答复里**把价格的事往后推了**(「" + m.group(0) + "」)—— 业务定的是"'''
新2 = '''        # 放宽(用户 11-20 执行 tools/放宽补丁/返修费_问一下与话术闸.py):「问一下」后面紧跟冒号或「你 / 您」
        # 是在**直接问对方**(「现在问一下:顾客同意付 300 块了吗?」),不是替顾客去问第三方;
        # 前面四个字里有 去 / 帮 / 替 / 跟 / 向 / 给 的照旧拦(「我帮您问一下:能不能少点」)
        if m.group(0) == "问一下" and re.match(r"\\s*[:：你您]", text[m.end():m.end() + 2]) \\
                and not re.search(r"[去帮替跟向给]", text[max(0, m.start() - 4):m.start()]):
            continue
        return ("答复里**把价格的事往后推了**(「" + m.group(0) + "」)—— 业务定的是"'''

N03原文 = ("判给顾客前要确认**顾客已经同意付 300 块**。\n\n流程是这样的:\n- 要先把顾客的同意记下来\n"
          "- 确认后判责才能生效\n\n**现在问一下:顾客已经同意付 300 块返修费了吗?** 是怎么确认的?")
修 = [{"tool": "mcp__shop__get_maintain"}]
规 = 'kb_read("13")'
g23该放 = [N03原文, "预估 300 块。我想问一下您,顾客同意付这笔钱了吗?"]
g23该拦 = ["这个价格确实偏高,我帮您问一下店长。",
         "4956 元是有点贵,我帮您问一下:能不能少一点。",
         "这件 1200 块,我去问一下店长看看能不能少点。"]
g30该放 = [("返修单 MX1 判给顾客,返修,预估 300 块,直接开工吧。", 修)]
g30该拦 = [("返修单 MX1 这件 300 块,不开票能便宜点吗?", 修),          # 拿开票换价:照旧要读话术
          ("返修单 MX1 300 块,能打个九折吗?", 修),                   # 折扣词:照旧
          ("这件马面裙 1200 块,能不能便宜点?", [])]                  # 没调返修工具:照旧

s = io.open(P, encoding="utf-8").read()
if "返修费_问一下与话术闸.py):这一轮查的是返修" in s:
    print("ℹ️ 没动手:看起来已经改过了。"); sys.exit(0)
for 名, 旧 in (("话术闸", 旧1), ("让价闸", 旧2)):
    n = s.count(旧)
    if n != 1:
        print(f"❌ 没动手:{名}的锚在 {P} 里出现 {n} 次(要正好 1 次)。文件被改过了 —— 让 Claude 重新核一遍再给命令。"); sys.exit(1)
改后 = s.replace(旧1, 新1).replace(旧2, 新2)

tmp = tempfile.mkdtemp(prefix="返修费放宽-")
try:
    for f in os.listdir(D):
        if f.endswith(".py"): shutil.copy2(os.path.join(D, f), tmp)
    io.open(os.path.join(tmp, "guards.py"), "w", encoding="utf-8").write(改后)
    sys.path.insert(0, tmp); sys.path.insert(1, os.path.join(D, "..", "agent")); sys.path.insert(2, os.path.join(D, "..", "backend"))
    spec = importlib.util.spec_from_file_location("guards_改后_返修费", os.path.join(tmp, "guards.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    错 = [f"g23 该放没放:{t[-30:]!r}" for t in g23该放 if g.g23_discount_promise(t, []) is not None]
    错 += [f"g23 该拦没拦:{t[-30:]!r}" for t in g23该拦 if g.g23_discount_promise(t, []) is None]
    错 += [f"g30 该放没放:{q!r}" for q, c in g30该放 if g.g30_sales_script_unread("好的", c, prompt=q, 规矩=规) is not None]
    错 += [f"g30 该拦没拦:{q!r}" for q, c in g30该拦 if g.g30_sales_script_unread("好的", c, prompt=q, 规矩=规) is None]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
if 错:
    print("❌ 没动手:改后的对照不过 ——"); [print("   ", e) for e in 错]; sys.exit(1)
io.open(P, "w", encoding="utf-8").write(改后)
print("✅ 已放宽:返修 / 售后里的金额不再触发话术闸;「问一下:…/问一下您」在问对方,不再算把价格往后推")
print(f"   对照:g23 该放 {len(g23该放)} 条全放、该拦 {len(g23该拦)} 条全拦;g30 该放 {len(g30该放)} 条、该拦 {len(g30该拦)} 条"
      "(用改后的 guards.py 真 import、真调跑的)")
print("\n接着跑这条验一下(Claude 会接手补用例并提交):\n   python3 agentsite/guards_test.py            # 必须还是绿的")
