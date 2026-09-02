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
q=re.findall(r'FROM\s+(\w+)', src)
print("接口触及的表:", sorted(set(q)))
ok = "truth" not in q
print("✅ truth 未被任何接口触及" if ok else "❌ truth 泄漏!")
import sys; sys.exit(0 if ok else 1)
