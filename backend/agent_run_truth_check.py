#!/usr/bin/env python3
"""研判演示回包不带评测答案(用户 11-13 拍「收:接口不再返回答案」)。

红线:truth 表是评测答案,**不许经任何接口漏出去**(CLAUDE.md 第 6 节)。
原来 `/api/agent-run` 跑完把 truth 的根因 / 期望动作 / 期望证据原样并排回给页面,
登录的人都能看到 —— 答案漏一次,整套研判评测就废了。

三条,不调模型(真跑一次花钱):
  ① 纯函数:造一份带 truth / judge / 复述根因的回包 → 研判回包() 之后一个答案原文都不剩;
  ② 模型自己的结论(finding)里就算说中了根因也保留 —— 那是它的答案,不是我们的;
  ③ 接线:`/api/agent-run` 那一支真的经 研判回包() 出门(读 do_GET 的语法树,
     找那一支里的 self._send(...) 实参是不是 研判回包 调用)—— 防「函数对了、入口没走它」。
"""
import ast, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402

咬合 = [
    ("研判回包不再去掉 truth 键", "①b truth 键本身被去掉(不靠按原文兜底)"),
    ("入口绕过 研判回包 直接回原始结果", "③ /api/agent-run 那一支经 研判回包() 出门"),
    ("研判回包第二道(按答案原文兜)关掉", "①c 别的键复述答案原文也去掉"),
]

坏 = []
def ck(名, ok, 说明=""):
    print(("  ✅ " if ok else "  ❌ ") + 名 + ("" if ok else f" —— {说明}"))
    if not ok:
        坏.append(名)

print("=== 研判演示回包不带评测答案 ===")
tr = dict(root_cause="退款漏记一笔手续费", expected_action="补录手续费流水",
          expected_evidence="流水号 RF-0091", note="跨月")
r = dict(finding={"根因": "退款漏记一笔手续费"}, passed=True, case="X1",
         truth=dict(tr), judge="命中:退款漏记一笔手续费",
         extra_echo="期望证据是 流水号 RF-0091", model="m")
out = server.研判回包(r, tr)
s = json.dumps({k: v for k, v in out.items() if k != "finding"}, ensure_ascii=False)
漏 = [v for v in tr.values() if v in s]
ck("① 回包(除模型结论外)不含任何答案原文", not 漏 and "truth" not in out and "judge" not in out,
   f"还漏着 {漏} / 键 {sorted(out)}")
# ①b 只靠「去掉 truth 键」那一道:答案字段短于 4 字,第二道(按原文兜)不管 → 键没去掉就漏
短 = dict(root_cause="漏记")
out2 = server.研判回包(dict(passed=False, truth=dict(短)), 短)
ck("①b truth 键本身被去掉(不靠按原文兜底)", "truth" not in out2, f"键 {sorted(out2)}")
# ①c 只靠第二道:别的键复述了答案原文(不叫 truth 也不叫 judge)
out3 = server.研判回包(dict(passed=True, extra_echo="期望证据是 流水号 RF-0091"), tr)
ck("①c 别的键复述答案原文也去掉", "extra_echo" not in out3, f"键 {sorted(out3)}")
ck("② 模型自己的结论原样保留", out.get("finding") == r["finding"] and out.get("passed") is True,
   f"finding={out.get('finding')}")

src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
tree = ast.parse(src)
找到 = 走了 = False
for node in ast.walk(tree):
    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) \
            and any(isinstance(c, ast.Constant) and c.value == "/api/agent-run" for c in node.test.comparators):
        找到 = True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "_send" and sub.args:
                a = sub.args[0]
                if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "研判回包":
                    走了 = True
ck("③ /api/agent-run 那一支经 研判回包() 出门", 找到 and 走了,
   "没找到那一支" if not 找到 else "那一支里没有 self._send(研判回包(...))")

print(f"\n验了 5 条(样本 {len(tr)} 个答案字段)")
if 坏:
    print(f"❌ {len(坏)} 条不过"); sys.exit(1)
print("✅ 全过")
