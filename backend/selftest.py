import api, json, sqlite3, os
print("=== 工具层离线自测 ===")
t=api.list_tasks("财务人工任务"); print(f"财务人工任务 {len(t)} 条,首条 ref={t[0]['ref_id']}")
d=t[0]['ref_id']
print("押金单:", json.dumps(api.get_deposit(d),ensure_ascii=False))
print("退款轨迹:", json.dumps(api.get_refund_trace(d),ensure_ascii=False)[:180])
print("支付流水:", json.dumps(api.get_payment_flow(d),ensure_ascii=False)[:180])
m=api.list_tasks("客户合并确认"); a,b=m[0]['ref_id'].split("|")
print(f"\n合并任务 {len(m)} 条,首条 {a} vs {b}")
print("客户A:", json.dumps(api.get_customer(a),ensure_ascii=False))
print("\n=== truth 表泄漏检查 ===")
leaked=[n for n,f in api.TOOLS.items() if "truth" in (f.__doc__ or "").lower()]
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"api.py")).read()
import re
# 原来只认 `FROM\s+(\w+)` —— **写成 `JOIN truth u ON …` 就完全查不到**,
# 而 ops.py 里正是那种写法。边界审计抓到了这一条:
# 这条「铁律」当时实际上是**约定**,靠没人写出那种语句形状守着。
#
# 真正的锁已经挪到 api._rows 的运行时拦截(不看语句形状)。
# 这里保留静态扫描作**纵深防御**,并把 JOIN / INTO / UPDATE 一起认上。
# 扫之前先把注释剥掉。第一版没剥,结果匹配到了 api.py 里**解释这条规则的注释**
# (我在那儿写了 `JOIN truth` 当例子)。这和密钥扫描那三次是同一个形状:
# **规则匹配到了规则的说明。**
#
# 但正解不同:密钥扫描扫的是任意文本,只能靠「别写出真实串」;
# 这个检查关心的是**代码**不是**散文**,所以剥注释才是对的 ——
# 用 tokenize 精确剥,不用正则猜。
import io, tokenize
_code = "".join(
    "" if t.type == tokenize.COMMENT else t.string + ("\n" if t.type == tokenize.NL else "")
    for t in tokenize.generate_tokens(io.StringIO(src).readline))
q=re.findall(r'(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)', _code, re.I)
print("接口触及的表:", sorted(set(x.lower() for x in q)))
ok = "truth" not in [x.lower() for x in q]
# 运行时锁也要在这里验一次 —— 静态扫描过了不代表运行时拦得住
try:
    api._rows("SELECT t.id FROM task t JOIN truth u ON u.case_id=t.id"); rt=False
except PermissionError: rt=True
print(("✅ truth 静态未触及" if ok else "❌ truth 静态泄漏!") +
      (" · 运行时 JOIN 绕过也被拦下" if rt else " · ❌ **运行时 JOIN 绕过没拦住**"))
ok = ok and rt
import sys; sys.exit(0 if ok else 1)
