#!/usr/bin/env python3
"""通道等价性测试 —— 不调模型。

为什么需要:用评测集比较「直连 vs MCP」是**测不出通道差异**的 ——
模型有随机性,同一道题两次跑会换措辞,而判分器对措辞敏感。
实测就撞上了:负向集 5/8 → 1/8,但四条翻转的题**轨迹完全相同、工具返回完全相同**,
差别全在模型说法上,其中两条还是判分器的锅。

**要证明两条通道等价,就得把模型摘出去:同样的工具、同样的入参,直接比返回值。**
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import api, client as mcp

# 每个工具一组代表性入参,含正常值、边界值、不存在的值
CASES = {
 "kb":  [("kb_lookup",   {"keyword": "香云纱"}),
         ("kb_lookup",   {"cat": "工艺", "src": "public"}),
         ("kb_lookup",   {"keyword": "根本不存在的东西"}),
         ("kb_detail",   {"code": "KF01"}),
         ("kb_detail",   {"code": "XX99"}),
         ("kb_combo",    {"craft": "妆花", "material": "香云纱"}),
         ("kb_combo",    {"craft": "妆花", "material": "宋锦"}),
         ("kb_combo",    {"craft": "苗绣", "material": "香云纱"}),
         ("kb_tables",   {}),
         ("kb_tables",   {"topic": "客户原话对照"}),
         ("kb_coverage", {})],
 "task":[("list_tasks",  {}),
         ("list_tasks",  {"task_type": "财务人工任务"}),
         ("get_deposit", {"deposit_id": "D2000"}),
         ("get_deposit", {"deposit_id": "D9999"}),
         ("get_refund_trace",  {"deposit_id": "D2012"}),
         ("get_payment_flow",  {"deposit_id": "D9002"}),
         ("get_customer",      {"customer_id": "C10000"}),
         ("get_customer",      {"customer_id": "NOPE"})],
}

def norm(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True)

bad = 0; n = 0
print("通道等价性测试(不调模型)\n" + "=" * 74)
for kind, cases in CASES.items():
    cl = mcp.get(kind)
    # ① schema 必须同形
    direct_s = api.KB_SCHEMAS if kind == "kb" else api.SCHEMAS
    ms = {t["name"]: t for t in cl.schemas()}
    ds = {t["name"]: t for t in direct_s}
    if set(ms) != set(ds):
        bad += 1; print(f"  ❌ [{kind}] 工具名集合不同:MCP {sorted(ms)} vs 直连 {sorted(ds)}")
    else:
        diff = [k for k in ds if norm(ms[k]["input_schema"]) != norm(ds[k]["input_schema"])
                or ms[k]["description"] != ds[k]["description"]]
        if diff: bad += 1; print(f"  ❌ [{kind}] schema 不一致:{diff}")
        else: print(f"  ✅ [{kind}] {len(ds)} 个工具的 name/description/input_schema 完全一致")
    # ② 返回值必须逐字节相同
    for name, args in cases:
        n += 1
        a = api.TOOLS[name](**args)
        b = cl.call(name, **args)
        if norm(a) != norm(b):
            bad += 1
            print(f"  ❌ [{kind}] {name}({args}) 返回不同")
            print(f"       直连 {norm(a)[:110]}")
            print(f"       MCP  {norm(b)[:110]}")
print(f"\n对比了 {n} 组入参")
print("=" * 74)
if bad: print(f"❌ {bad} 处不等价"); sys.exit(1)
print("✅ 两条通道完全等价:schema 同形,返回逐字节相同")
