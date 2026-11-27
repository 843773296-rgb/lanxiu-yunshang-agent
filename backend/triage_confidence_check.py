#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判置信度 · 只数查到东西的调用(查无此单 / 出错不算)

## 为什么要有这个
2026-11-27 负向研判集搬到研判专用那条路(产品真跑的那条)后真跑:「单号不存在」「支付流水查不到」两道题,
研判草稿的置信度都是「高」。置信度按过程信号推(`backend/ops.confidence`:查了几次 + 四段齐不齐),
而工具对「押金单 D7777 不存在」是**正常返回一个 {"error": …}**,协议层记成成功 ——
于是「两次都查无此单」也算查了两次数据。店员会信一条其实什么都没查到的「高置信」结论。
用户 11-27 拍「修」。这之前 `ops.confidence` 一条测试都没有。
11-28 再收一步:「证据残缺」那题押金单、退款记录都查到了、唯独支付流水查无,照样「高」。
用户拍「任一次查无就判低」(不按研判类型列关键证据表;代价是试错碰到查无也判低,只多让人看)。

## 查什么
1. 纯函数:`ops.confidence` 只数没挂「出错」「查无」的调用,且**有一次查无就判低** —— 同一份草稿,查到东西 2 次 → 高;两次都查无 → 低;查到两次 + 一次查无 → 低。
2. 认得出:`sdk._返回是查无` 对**真工具**的返回形状判得对(现调 `api.get_deposit` 一个不存在的单号取它的错误形状,
   不手写一份「我以为它长这样」)。没装 SDK 的环境(CI 系统 python)这一层明说「没验」,不算过。
3. 接线:sdk 记轨迹那一段真的在用它挂「查无」(只验纯函数的话,把调用那一支删掉自测照样全绿)。
"""
import ast, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

四段齐 = {"ai_root_cause": "押金单查不到", "ai_action": "核对单号", "ai_evidence": "get_deposit 返回不存在"}


def 查(样本):
    """样本:[(说明, 轨迹, 草稿, 期望置信度)] → (bad, 验了几个)。调的是真的 ops.confidence。"""
    import ops
    bad = []
    for 说明, 轨迹, 草稿, 期望 in 样本:
        得 = ops.confidence(轨迹, 草稿)
        if 得 != 期望:
            bad.append(f"{说明}:置信度是「{得}」,应为「{期望}」")
    return bad, len(样本)


def 样本们():
    查到 = {"tool": "mcp__finance__get_deposit"}
    return [
        ("查到东西 2 次、四段齐", [查到, dict(查到, tool="mcp__finance__get_refund_trace")], 四段齐, "高"),
        ("两次都查无此单,不算查过数据", [dict(查到, 查无=True), dict(查到, tool="mcp__finance__get_refund_trace", 查无=True)], 四段齐, "低"),
        ("一次查到、一次查无 → 有查无就判低", [查到, dict(查到, tool="mcp__finance__get_refund_trace", 查无=True)], 四段齐, "低"),
        ("查到两次、支付流水查无(负向集「证据残缺」那题的形状)→ 低",
         [查到, dict(查到, tool="mcp__finance__get_refund_trace"), dict(查到, tool="mcp__finance__get_payment_flow", 查无=True)], 四段齐, "低"),
        ("调用出错的也不算", [dict(查到, 出错=True), dict(查到, 出错=True)], 四段齐, "低"),
        ("旧轨迹没这两个键 → 照旧按调用次数", [查到, 查到], 四段齐, "高"),
    ]


def 自测():
    bad = []
    b, n = 查([])
    if n != 0:
        bad.append("自测:空样本该报 0 个")
    b, n = 查(样本们())
    bad += [f"自测:{x}" for x in b]
    return bad


def 认得出():
    """→ (bad, 说明)。真工具的错误形状 + 正常返回,喂给 sdk._返回是查无。"""
    try:
        import sdk
    except Exception as e:
        return [], f"没验:这个环境 import 不了 agentsite/sdk({type(e).__name__})—— 要用 agentsite/.venv/bin/python 跑才验这一层"
    import api
    with api.as_user(api.系统身份):
        错 = api.get_deposit("D-不存在-0000")
        真 = api.get_deposit((api._rows("SELECT id FROM deposit ORDER BY id LIMIT 1") or [{"id": "D2000"}])[0]["id"])
    bad = []
    if not (isinstance(错, dict) and 错.get("error")):
        bad.append(f"夹具没立起来:不存在的单号返回的不是 {{error: …}}(是 {str(错)[:80]})—— 换一个会报错的调用")
    elif not sdk._返回是查无([{"type": "text", "text": json.dumps(错, ensure_ascii=False)}]):
        bad.append(f"认不出「查无此单」:{json.dumps(错, ensure_ascii=False)[:80]}")
    if sdk._返回是查无([{"type": "text", "text": json.dumps(真, ensure_ascii=False)}]):
        bad.append("把一条查到了的押金单当成了查无")
    if sdk._返回是查无([{"type": "text", "text": "不是 JSON 的一段话"}]):
        bad.append("解析不了的返回被当成了查无(应宁可少标)")
    return bad, "真工具形状:查无 / 查到 / 非 JSON 三种"


def 接线():
    """sdk 记轨迹那段真的调了 _返回是查无 并挂「查无」键。"""
    src = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Call) and getattr(n.test.func, "id", "") == "_返回是查无":
            for m in ast.walk(n):
                if isinstance(m, ast.Constant) and m.value == "查无":
                    return []
    return ["接线:sdk.py 里没有「if _返回是查无(…): … 挂『查无』」那一段 —— 纯函数对了,轨迹上照样不标"]


# ── 咬合记录(规格在 tools/bite_specs.json,bite_run 能重放)────────────────
咬合 = [
    ("ops.confidence 照旧数所有调用(不排除查无 / 出错)", "调用出错的也不算"),
    ("sdk 记轨迹时不再挂「查无」", "接线:sdk.py 里没有"),
    ("ops.confidence 有查无也照样按查到次数给高", "查到两次、支付流水查无"),
]


def main():
    print("研判置信度 · 只数查到东西的调用(查无此单 / 出错不算)\n" + "=" * 72)
    bad = 自测()
    if bad:
        for b in bad: print(f"  {R}❌ {b}{D}")
        print(f"{R}❌ 自测没过,真跑不算数{D}"); return 1
    样本 = 样本们()
    bad, n = 查(样本)
    b2, 说 = 认得出()
    bad += b2 + 接线()
    print(f"  验了 {n} 条轨迹;认得出:{说};接线:看 sdk.py 那一段")
    if n == 0:
        print(f"{R}❌ 一个都没验到 —— 不是「都对」,是没东西可验{D}"); return 1
    for b in bad: print(f"  {R}❌ {b}{D}")
    if bad:
        print(f"{R}❌ {len(bad)} 处不符合预期{D}"); return 1
    print(f"{G}✅ 研判置信度只数查到东西的调用:查无此单 / 出错不再算成查过数据{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
