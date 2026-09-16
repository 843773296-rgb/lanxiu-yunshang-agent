# ── 咬合记录 ────────────────────────────────────────────────────────────
# 每条都**真把代码改坏跑过一次**,确认对应检查会红。
# ⚠️ 这个文件 2026-09-16 之前一直没有咬合记录,**不是因为没测过**,
# 是因为它的判定是两句 `print` 拼出来的一行话 —— **没有名字可指**。
# 先补了具名检查,才记得了咬合。
咬合 = [
    ("把 api._rows 里拦 truth 的那段去掉(运行时锁失效)",
     "运行时 JOIN 绕过会被拦下"),
    ("在 api.py 里写一句真的 `FROM truth`(静态扫描该抓到)",
     "truth 表没有被任何工具的 SQL 静态触及"),
]

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
# ⚠️ **改成具名检查(2026-09-16)。**
#
# 这里原来是两句 `print` 拼出来的一行话。改的原因是
# `tools/bite_check.py` 的咬合记录要**指名道姓**说「预期红的是哪一条」——
# 而一句拼出来的话**没有名字可指**,于是这个文件一直记不了咬合。
#
# 顺序不能反:**先有具名检查,才记得了咬合。**
# (同一个形状:`stock_check` 那次是名字用 f-string 拼的,也指不到。)
_FAIL = []


def _ck(名, 成, 说=""):
    print(f"  {'✅' if 成 else '❌'} {名}{('  ' + 说) if 说 else ''}")
    if not 成: _FAIL.append(名)


print()
_ck("truth 表没有被任何工具的 SQL 静态触及", ok,
    "**纵深防御的第一层** —— 它挡的是「写出来就不对」的语句;"
    "而真正的锁在运行时(下一条)")
_ck("运行时 JOIN 绕过会被拦下", rt,
    "**这一条才是真锁** —— 它不看语句形状,所以 `JOIN truth u ON …` "
    "这种绕法也拦得住。静态扫描漏过一次(只认 `FROM\s+(\w+)`),"
    "而那次漏的时候这条铁律实际上只是**约定**")
import sys; sys.exit(1 if _FAIL else 0)
