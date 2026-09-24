#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""树状记录仪的结构检查 —— 盯三件事:接没接上、树是不是树、有没有把凭据记进去。

## 为什么要有

`agent/trace_check.py` 已经盯着「每个调模型的地方都接了记录仪」,但它认的是
**旧那份**(trace.record)。新加的树状记录仪是第二份日志,**它漏了不会报错** ——
文件还在、还有数据,只是不再长了。这个项目在同一个形状上栽过一次
(升到 Agent SDK 之后旧记录仪停写了一个月,表现是「一切正常」)。

## 查什么

① **接上了没**:sdk.py 里得真的开树、真的落盘。少一样都等于没接。
② **树是不是树**:一棵里只有一个根、每个 span 的父都在同一棵里、
   子的耗时不超过父。父子对不上时**不会报错**,只会让某一步在页面上消失。
③ **凭据没进日志**:这份日志记参数和返回值,比旧那份敏感得多。
   按键名抹是在写的时候做的,这里是**第二道**:直接扫文件里有没有凭据类键名。
④ **对不上账的数不许留**:分步输出 token 对不上整轮总数时,分步值必须已经被抹掉。
   一个「看起来合理」的错数比空着糟 —— 空着看得出没有,错数看不出错。

## 咬合(每条都验过真的会红)

    改坏什么                                   预期红的那一条
    ──────────────────────────────────────────────────────────
    sdk.py 里把落盘那句删掉                    记录仪接上了(开树 + 落盘)
    日志里塞一个 parent 指向别棵的 span        每个 span 的父都在同一棵里
    日志里塞两个根                             一棵树只有一个根
    日志里写一个 "密码" 键                     日志里没有凭据类字段
    根上说「对不上账」但分步还留着输出数        对不上账的分步用量已经抹掉
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import spans as _sp     # noqa: E402

# ── 咬合记录 ──────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**没红过的检查等于没有。**
# 下面八条在 `--selftest` 里都是可执行的,`python3 agent/spans_check.py` 会连跑。
咬合 = [
    ("sdk.py 里把落盘那句删掉(开了树但从不写文件)", "记录仪接上了(开树 + 落盘)"),
    ("日志里塞两个根", "根有 2 个"),
    ("把某个 span 的父指到别棵树去", "父不在同一棵里"),
    ("工具 span 收了尾却不带返回值(证据面板会是空的)", "没有返回值"),
    ("让子 span 的耗时超过根", "子比根还久"),
    ("根上说对不上账、分步却留着输出 token", "还留着输出 token"),
    ("往 attr 里写一个「密码」键", "日志里没有凭据类字段"),
    ("把凭据词表写宽(tokens 也当凭据)", "input_tokens / cache_read_input_tokens 不算凭据"),
]

LOG = os.path.join(ROOT, ".feynman", "spans.jsonl")
FAIL, N = [], [0]


def ck(名, 真, 补=""):
    N[0] += 1
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 else ''}")
    if not 真: FAIL.append(名)
    return 真


# ── ① 接上了没 ─────────────────────────────────────────────────────
def 接上了吗(src=None):
    """判的是结构不是词:要 import、要开根、要落盘,**三样都在才算接上**。"""
    s = src if src is not None else open(os.path.join(ROOT, "agentsite", "sdk.py"),
                                         encoding="utf-8").read()
    有 = dict(
        导入=bool(re.search(r"import\s+spans\b", s)),
        开树=bool(re.search(r"spans\s*\.\s*一棵树\s*\(|_spans\s*\.\s*一棵树\s*\(", s)),
        开根=bool(re.search(r"\.开\s*\(\s*[\"']invoke_agent", s)),
        落盘=bool(re.search(r"\.落盘\s*\(", s)),
    )
    return 有


# ── ② 树的形状 ─────────────────────────────────────────────────────
def 验一棵(spans):
    """返回问题清单(空 = 没问题)。"""
    问 = []
    ids = [s.get("span_id") for s in spans]
    if len(set(ids)) != len(ids): 问.append("span_id 重复")
    有 = set(ids)
    根 = [s for s in spans if not s.get("parent_span_id")]
    if len(根) != 1: 问.append(f"根有 {len(根)} 个(应当正好 1 个)")
    孤 = [s["span_id"] for s in spans
          if s.get("parent_span_id") and s["parent_span_id"] not in 有]
    if 孤: 问.append(f"父不在同一棵里的 span:{孤[:3]}")
    负 = [s["name"] for s in spans if (s.get("duration_ms") or 0) < 0]
    if 负: 问.append(f"耗时为负:{负[:3]}")
    if 根:
        顶 = 根[0].get("duration_ms") or 0
        超 = [s["name"] for s in spans
              if (s.get("duration_ms") or 0) > 顶 + 1000]    # 容 1 秒,时钟不是严格单调
        if 超: 问.append(f"子比根还久:{超[:3]}")
    # 工具 span 必须有参数;收了尾的还必须有返回值
    for s in spans:
        a = s.get("attr") or {}
        if a.get("gen_ai.operation.name") != "execute_tool": continue
        if "gen_ai.tool.call.arguments" not in a:
            问.append(f"工具 span 没记参数:{s['name']}")
        if s.get("status") in ("ok", "error") and "gen_ai.tool.call.result" not in a:
            问.append(f"工具 span 收了尾却没有返回值:{s['name']}")
    # 对不上账的分步用量必须已经抹掉
    根attr = (根[0].get("attr") if 根 else {}) or {}
    if 根attr.get("lanxiu.usage.output_split_unavailable"):
        留 = [s["name"] for s in spans
              if (s.get("attr") or {}).get("gen_ai.usage.output_tokens")
              and (s["attr"].get("gen_ai.operation.name") == "chat")]
        if 留: 问.append(f"根上说对不上账,分步却还留着输出 token:{留[:3]}")
    return 问


# ── ③ 凭据 ─────────────────────────────────────────────────────────
def 扫凭据(棵们):
    """扫**键名**。抹是在写的时候做的,这里是第二道 —— 第一道漏了要有人喊。"""
    中 = []
    for tid, spans in 棵们.items():
        for s in spans:
            for k, v in (s.get("attr") or {}).items():
                if _sp.凭据键.search(str(k)) and v != _sp.抹了:
                    中.append(f"{s['name']} 的 {k}")
                # 值里也扫一遍键名(参数和返回值是字符串,里面嵌着原始 JSON)
                if isinstance(v, str) and _sp.凭据键.search(v):
                    # 抹过的会留下痕迹,留了痕迹就算合格
                    if _sp.抹了 not in v: 中.append(f"{s['name']} 的 {k} 的值里")
    return 中


def 跑(棵们, src=None):
    有 = 接上了吗(src)
    ck("记录仪接上了(开树 + 落盘)", all(有.values()), 有)
    if not 棵们:
        # ⚠️ **这里不许红。** CI 从零建库、不调模型,日志必然是空的 ——
        # 红在这儿就是这个项目栽过三次的「本地绿、CI 从零红」。
        # 真正防住「忘了接」的是上面那条**读源码**的检查,它从零也成立。
        print("  ⚠ 日志还是空的(没跑过模型)。接没接上看上面那条;"
              "要看真数据跑一次:./agentsite/.venv/bin/python agentsite/sdk.py kb '香云纱能不能做妆花?'")
        return
    坏 = {}
    for tid, spans in 棵们.items():
        问 = 验一棵(spans)
        if 问: 坏[tid[:12]] = 问
    ck("每棵树的形状都对(一个根、父都在、耗时不为负、工具有参数和返回值)",
       not 坏, 坏 or f"{len(棵们)} 棵全对")
    中 = 扫凭据(棵们)
    ck("日志里没有凭据类字段", not 中, 中[:3] or "")
    # 词表写宽的代价和写窄一样大:红的全是好人,于是没人再看这条检查。
    # 2026-09-24 第一版就栽在这儿 —— `token` 写成光秃秃的,把用量字段全报成凭据。
    ck("input_tokens / cache_read_input_tokens 不算凭据",
       not any(_sp.凭据键.search(k) for k in
               ("gen_ai.usage.input_tokens", "gen_ai.usage.cache_read_input_tokens",
                "gen_ai.usage.cache_creation_input_tokens"))
       and all(_sp.凭据键.search(k) for k in ("access_token", "密码", "api_key")))
    # 工具的返回值**必须真的记着** —— 这是这次升级的全部意义所在,
    # 只记了调用没记返回值的话,证据面板还是空的,而树看起来是完整的。
    工具 = [s for v in 棵们.values() for s in v
            if (s.get("attr") or {}).get("gen_ai.operation.name") == "execute_tool"]
    有返回 = [s for s in 工具 if (s.get("attr") or {}).get("gen_ai.tool.call.result")]
    ck("工具调用记下了返回值(证据面板要的就是它)",
       not 工具 or len(有返回) >= len(工具) * 0.9,
       f"{len(有返回)}/{len(工具)} 个工具 span 带返回值")


def _自测():
    print("咬合:改坏了要红\n" + "-" * 84)
    好 = {"t1": [
        dict(trace_id="t1", span_id="r", parent_span_id=None, name="invoke_agent 门店顾问",
             duration_ms=100, status="ok", attr={"gen_ai.operation.name": "invoke_agent"}),
        dict(trace_id="t1", span_id="c", parent_span_id="r", name="chat m",
             duration_ms=50, status="ok", attr={"gen_ai.operation.name": "chat"}),
        dict(trace_id="t1", span_id="tu", parent_span_id="c", name="execute_tool get_order",
             duration_ms=5, status="ok",
             attr={"gen_ai.operation.name": "execute_tool",
                   "gen_ai.tool.call.arguments": '{"order_id":"DD1"}',
                   "gen_ai.tool.call.result": '{"状态":"已发货"}'}),
    ]}
    过 = []

    def 咬(名, 改, 应含):
        v = 改()
        命中 = any(应含 in x for x in v)
        过.append(命中)
        print(f"  {'✅' if 命中 else '❌'} {名}  →  {v or '(没红)'}"[:180])

    import copy
    ck2 = lambda d: 验一棵(list(d.values())[0])
    咬("对照(没改坏)应当全绿", lambda: ck2(copy.deepcopy(好)) or ["(没问题)"], "没问题")
    def 改_两个根():
        d = copy.deepcopy(好); d["t1"][1]["parent_span_id"] = None; return ck2(d)
    咬("两个根", 改_两个根, "根有 2 个")
    def 改_孤儿():
        d = copy.deepcopy(好); d["t1"][2]["parent_span_id"] = "别棵的"; return ck2(d)
    咬("父指到别棵去", 改_孤儿, "父不在同一棵里")
    def 改_没返回值():
        d = copy.deepcopy(好); d["t1"][2]["attr"].pop("gen_ai.tool.call.result"); return ck2(d)
    咬("工具收了尾却没返回值", 改_没返回值, "没有返回值")
    def 改_子比根久():
        d = copy.deepcopy(好); d["t1"][1]["duration_ms"] = 99999; return ck2(d)
    咬("子比根还久", 改_子比根久, "子比根还久")
    def 改_对不上账还留着():
        d = copy.deepcopy(好)
        d["t1"][0]["attr"]["lanxiu.usage.output_split_unavailable"] = "对不上"
        d["t1"][1]["attr"]["gen_ai.usage.output_tokens"] = 3
        return ck2(d)
    咬("对不上账却还留着分步输出数", 改_对不上账还留着, "还留着输出 token")
    def 改_凭据():
        d = copy.deepcopy(好); d["t1"][2]["attr"]["密码"] = "x"; return 扫凭据(d)
    咬("日志里写了凭据键名", 改_凭据, "密码")
    def 改_没落盘():
        return ["少了:" + k for k, v in 接上了吗(
            "import spans\n_spans.一棵树()\n.开('invoke_agent x')\n").items() if not v]
    咬("sdk.py 里删掉落盘那句", 改_没落盘, "落盘")

    print(f"\n{'✅' if all(过) else '❌'} 咬合 {sum(过)}/{len(过)} 条如预期")
    return 0 if all(过) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_自测())
    print("树状记录仪 · 结构检查\n" + "=" * 84)
    棵 = _sp.读(LOG)
    跑(棵)
    rc = _自测()
    print()
    if FAIL or rc:
        print(f"\033[31m❌ 树状记录仪 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        print("   **漏了不会报错** —— 文件还在、还有数据,只是不再长了")
        sys.exit(1)
    print(f"\033[32m✅ 树状记录仪 {N[0]} 条 + 咬合全过\033[0m —— "
          f"{len(棵)} 棵树、{sum(len(v) for v in 棵.values())} 个 span")
