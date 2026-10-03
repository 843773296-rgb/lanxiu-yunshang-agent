#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立路由器的**成本探针** —— 量「它一次花多少钱、多慢、召回涨多少」。

## 为什么要有它

选型卡 §8.5 要拍「要不要开独立路由器」(契约里已有开关
`independent_router_enabled`,规格首版 false)。而拍之前缺一个数:**它贵不贵**。
业务 2026-10-03 定的是「**先量 B 的成本再拍**」。

## 它不是实现,是探针

和 `select_probe.py` 一样,名字叫 probe:
> 一个被当成实现用的探针,和一个实现,在跑起来的时候长得一模一样 ——
> 而探针没有闸、没有限额、没有权限复核。

真实现要走后台的 `selection_api`,并且受策略里那五个限额管
(候选 5 / 新增定义 4000 token / 活动 12000 / 补搜 2 次 / 超时 3000ms)。

## 要量的不只是「多花多少」,还有「替下来多少」

现状是**每一轮**都把 77 个工具的完整定义带给模型 ——
这个项目实测过:工具从 26 涨到 59,提示词从 21KB 涨到 55KB,**单条成本涨 38%**,
而「加一个工具的代价不在那个工具上,在此后每一次调用上」。

而路由器是**一次**调用、带一份精简目录(名字 + 一句话 ≈ 3900 token)。
所以它可能比「每轮带 77 个全定义」**更便宜**,不是更贵。
两个数都要报,只报前一个会把它说成纯成本。

## 两个配置都跑:**有缓存 / 无缓存**

目录每次都一样,是提示词缓存的完美前缀(`v1.call` 的 `cache=` 开关把
`cache_control` 标在 system 上,而渲染顺序是 tools → system → messages)。
不量缓存的话,报出来的单条成本会**系统性偏高** ——
而偏高的成本会让人以为这条路不值得走。

## ⚠️ 一律用 Claude,而且必须显式指定模型

业务 09-15 拍的板(`tools/eval_provenance_check.py` 在守)。
而**不指定模型时默认取决于用哪种凭证** —— 同一条命令在另一台机器上跑出来是另一个模型,
两张表不可比(成本能差一个量级)。所以这里**不指定就拒跑**。
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, os.path.join(HERE, "..", "agentsite"))

路由系统提示 = """你是工具路由器。下面是这个系统里所有可用工具的目录(工具名 + 一句话说明)。

用户会给你一个任务。你的工作**只有一件**:判断完成这个任务需要用到目录里的哪几个工具。

规则:
- 只返回一个 JSON 数组,里面是工具名,**不要任何别的文字**。例:["get_order","order_log"]
- 最多 {k} 个,按最该用的排在前面
- **拿不准就少给** —— 给错一个工具的代价是模型会去用它
- 目录里没有合适的,返回空数组 []

工具目录:
{目录}"""


def 目录文本(全量=None):
    """名字 + 首行说明。**不给全文** —— 全文 11300 token,首行 3900。

    给全文会让路由器这一次调用比它要省的那些还贵,
    而「路由器贵」这个结论就会是**我自己造的**。
    """
    import api
    行 = []
    for s in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS:
        if 全量 is not None and s["name"] not in 全量:
            continue
        首 = (s["description"] or "").strip().splitlines()[0]
        # 去掉 markdown 强调符 —— 它们在目录里只占 token 不带信息
        首 = re.sub(r"[*`]+", "", 首).strip()
        行.append(f"{s['name']}: {首[:100]}")
    return "\n".join(行)


def 读留出集():
    """两个留出集,共 33 题。**都不是为检索造的**。"""
    import importlib.util
    _s = importlib.util.spec_from_file_location(
        "agent_tool_eval", os.path.join(HERE, "tool_eval.py"))
    TE = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(TE)
    A = [(c[0], c[1], list(c[2])) for c in TE.CASES if c[2]]
    B路 = os.path.join(HERE, "..", "agentsite", "evals", "tool_routing.json")
    d = json.load(open(B路, encoding="utf-8"))
    B = [(f"R{c['id']}", c["prompt"], [e["工具"] for e in c["期望"]])
         for c in d["cases"]]
    return A, B


def 解析工具名(文, 池):
    """从回答里取工具名。**认不出就返回空,不猜**。

    ⚠️ 模型可能裹着 ```json 围栏,或者多说一句话。两种都收,
    但**目录外的名字一律丢掉并记下来** —— 一个凭空捏出来的工具名
    和一个真工具在 JSON 里长得一模一样,而后台对未注册的工具名是一律拒绝的(§9.4)。
    """
    m = re.search(r"\[.*?\]", 文, re.S)
    if not m:
        return [], []
    try:
        xs = json.loads(m.group(0))
    except Exception:
        return [], []
    好 = [x for x in xs if isinstance(x, str) and x in 池]
    编的 = [x for x in xs if isinstance(x, str) and x not in 池]
    return 好, 编的


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--模型", required=True,
                    help="**必填** —— 不指定时默认模型取决于用哪种凭证,"
                         "同一条命令在另一台机器上跑出来是另一个模型,两张表不可比")
    ap.add_argument("--k", type=int, default=5, help="最多让它给几个(规格 §14.3 是 5)")
    ap.add_argument("--缓存", choices=("开", "关", "都跑"), default="都跑")
    ap.add_argument("--只跑", type=int, default=0, help="只跑前 N 题(先试水用)")
    a = ap.parse_args()
    os.environ.setdefault("LANXIU_PROVIDER", "claude")

    import api
    import v1
    池 = {s["name"] for s in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS}
    import sdk
    挂得到 = {t.rsplit("__", 1)[-1] for t in sdk._tools_for("all")}
    目录 = 目录文本(全量=挂得到)
    系统 = 路由系统提示.format(k=a.k, 目录=目录)

    A, B = 读留出集()
    题 = [("A", *x) for x in A] + [("B", *x) for x in B]
    if a.只跑:
        题 = 题[:a.只跑]

    pv = v1.provider()
    pv = dict(pv, model=a.模型)
    print(f"独立路由器成本探针 · 模型 {a.模型} · k={a.k} · {len(题)} 题")
    print(f"  目录 {len(目录)} 字(名字+首行,{len(挂得到)} 个工具)")
    print("=" * 96)

    配置 = (["关", "开"] if a.缓存 == "都跑" else [a.缓存])
    汇总 = {}
    for 缓 in 配置:
        行 = []
        print(f"\n【缓存{缓}】")
        for 集, tid, q, need in 题:
            t0 = time.time()
            body = dict(model=a.模型, max_tokens=200, system=系统,
                        messages=[{"role": "user", "content": q}])
            try:
                r = v1.call(pv, body, purpose=f"工具路由探针/{集}{tid}",
                            cache=(缓 == "开"), gen="路由探针")
            except Exception as e:
                print(f"  {tid:5s} ❌ 跑挂了:{type(e).__name__}: {e}")
                行.append(dict(题=tid, 过=False, 挂了=True)); continue
            ms = int((time.time() - t0) * 1000)
            文 = "".join(b.get("text", "") for b in (r.get("content") or [])
                         if b.get("type") == "text")
            给的, 编的 = 解析工具名(文, 池)
            过 = bool(set(给的) & set(need))
            u = r.get("usage") or {}
            行.append(dict(题=tid, 集=集, 过=过, 给的=给的, 编的=编的,
                           ms=ms, usage=u))
            print(f"  {集}{tid:5s} {'✅' if 过 else '❌'} {ms:5d}ms  "
                  f"给 {len(给的)} 个{('(编了'+str(len(编的))+'个)') if 编的 else ''}  "
                  f"{','.join(给的[:3])}"
                  f"{'' if 过 else '  need='+','.join(need[:2])}")
        汇总[缓] = 行

    print("\n" + "=" * 96)
    for 缓, 行 in 汇总.items():
        好 = [x for x in 行 if not x.get("挂了")]
        if not 好: continue
        过 = sum(1 for x in 好 if x["过"])
        编 = sum(len(x.get("编的") or []) for x in 好)
        ms = sorted(x["ms"] for x in 好)
        入 = sum((x["usage"].get("input_tokens") or 0) for x in 好)
        出 = sum((x["usage"].get("output_tokens") or 0) for x in 好)
        读缓 = sum((x["usage"].get("cache_read_input_tokens") or 0) for x in 好)
        写缓 = sum((x["usage"].get("cache_creation_input_tokens") or 0) for x in 好)
        print(f"\n【缓存{缓}】{len(好)} 题")
        print(f"  召回(至少命中一个 need):{过}/{len(好)} = {100*过//len(好)}%")
        print(f"  延迟:中位 {ms[len(ms)//2]}ms · 最慢 {ms[-1]}ms")
        print(f"  token/条:入 {入//len(好)} · 出 {出//len(好)}"
              f" · 读缓存 {读缓//len(好)} · 写缓存 {写缓//len(好)}")
        if 编:
            print(f"  ⚠️ **编出了 {编} 个目录外的工具名** —— "
                  f"一个凭空捏的工具名和一个真工具在 JSON 里长得一样;"
                  f"后台对未注册的工具名一律拒绝(§9.4),所以这些会在执行时被拦 ——"
                  f"**而拦下来的表现是「这个任务没有可用工具」**")
    out = os.path.join(HERE, "..", ".feynman", "router-probe.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(汇总, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n明细 → {os.path.relpath(out, os.path.join(HERE, '..'))}")
    print("⚠️ **成本一律用 `sdk.cost_of()` 自己算** —— "
          "Agent SDK 返回的 total_cost_usd 跨供应商时是错的(实测差过 24 倍、135 倍)。"
          "这里报的是 token,换算在下一步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
