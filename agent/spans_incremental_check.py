# -*- coding: utf-8 -*-
"""树状记录仪 · 边跑边记(证据中心 P0「记录恢复与完整性」,10-25)。

原来一轮只在正常结束时整棵写一次 —— 进程中途崩了,这一轮**一条都不剩**,而跑崩的那一轮恰恰最需要看。
真调 agent/spans.py 的 一棵树(边跑边记=True)/ 读 / 记中断,写在临时文件里,不碰真日志。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spans as S

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("span 收的时候不写(还是只在结束时整棵写)", "崩在半路:已经收尾的那次工具调用(带返回值)照样在"),
    ("读的时候同一个 span 后写的整条替换前写的(不合并)", "补记中断之后:根是「出错 + 为什么」,而原来的提问和角色还在"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def 新路径():
    return os.path.join(tempfile.mkdtemp(), "spans.jsonl")


def main():
    print("树状记录仪 · 边跑边记")
    # ① 崩在半路:根开了、一个工具调完、第二个工具开了没回来,然后进程没了(不调 落盘、不收根)
    p = 新路径()
    t = S.一棵树(角色="店长", 会话号="会话-甲", 模型="m", tid="T1", 边跑边记=True, 路径=p)
    根 = t.开("invoke_agent", "invoke_agent 测", 属性={"lanxiu.prompt": "出个周报"})
    模 = t.一次模型调用(父=根, 模型="m")
    a = t.一次工具调用(父=模, 工具="store_report", 参数={"kind": "周"}, 调用号="c1")
    t.工具回来了(a, "{\"营收\": 1}")
    t.一次工具调用(父=模, 工具="list_reports", 参数={}, 调用号="c2")
    树 = S.读(p).get("T1") or []
    按号 = {s["span_id"]: s for s in 树}
    ck("崩在半路:已经收尾的那次工具调用(带返回值)照样在",
       "c1" in 按号 and (按号["c1"].get("attr") or {}).get("gen_ai.tool.call.result") == "{\"营收\": 1}", list(按号))
    ck("崩在半路:根在,状态「进行中」,带着提问和会话号(权限判定要它)",
       按号.get(根, {}).get("status") == "进行中" and 按号[根].get("会话号") == "会话-甲"
       and (按号[根].get("attr") or {}).get("lanxiu.prompt") == "出个周报", 按号.get(根))
    ck("没回来的那次调用这时还没写(它没收尾)—— 不编一个返回值", "c2" not in 按号, list(按号))
    # ② 补记中断:根变「出错 + 为什么」,原来的属性还在(合并,不是替换)
    S.记中断("T1", 根, "TimeoutError: 模型 60 秒没回", path=p)
    r = {s["span_id"]: s for s in S.读(p)["T1"]}[根]
    ck("补记中断之后:根是「出错 + 为什么」,而原来的提问和角色还在",
       r.get("status") == "error" and "TimeoutError" in (r.get("attr") or {}).get("lanxiu.interrupted", "")
       and (r.get("attr") or {}).get("lanxiu.prompt") == "出个周报" and r.get("角色") == "店长", r)
    # ③ 早就该结束还「进行中」→ 读出来是「中断」(进程被杀、连补记都没机会)
    p2 = 新路径()
    t2 = S.一棵树(tid="T2", 边跑边记=True, 路径=p2)
    t2.开("invoke_agent", "invoke_agent 旧", 起=time.time() - S.中断秒 - 60)
    ck("开了一个多小时还「进行中」→ 读出来是「中断」", S.读(p2)["T2"][0].get("status") == "中断", S.读(p2)["T2"])
    t3 = S.一棵树(tid="T3", 边跑边记=True, 路径=p2)
    t3.开("invoke_agent", "invoke_agent 新")
    ck("刚开的那一轮读出来仍是「进行中」(不误判成中断)", S.读(p2)["T3"][0].get("status") == "进行中")
    # ④ 正常跑完:每个 span 读出来只一份,没收尾的在落盘时标出来
    p3 = 新路径()
    t4 = S.一棵树(tid="T4", 边跑边记=True, 路径=p3)
    r4 = t4.开("invoke_agent", "invoke_agent 正常")
    x = t4.一次工具调用(父=r4, 工具="get_order", 参数={}, 调用号="d1"); t4.工具回来了(x, "ok")
    t4.一次工具调用(父=r4, 工具="get_stock", 参数={}, 调用号="d2")
    t4.收(r4); t4.落盘(p3)
    读到 = S.读(p3)["T4"]
    ck("正常跑完:每个 span 读出来只一份(根写了两次也合成一份)", len(读到) == 3 and len({s["span_id"] for s in 读到}) == 3,
       [(s["span_id"], s.get("status")) for s in 读到])
    ck("没收尾的那次调用在落盘时标「未收尾」", {s["span_id"]: s.get("status") for s in 读到}.get("d2") == "未收尾", 读到)
    行数 = sum(1 for _ in open(p3, encoding="utf-8"))
    ck("文件里的行数 = 根两次 + 每个 span 一次(落盘不把收过的再写一遍)", 行数 == 4, 行数)
    # ⑤ 默认不边跑边记:落盘之前一行都不写(自测和别的调用方给的是自己的路径)
    p4 = 新路径()
    t5 = S.一棵树(tid="T5", 路径=p4); t5.开("invoke_agent", "x")
    ck("默认关:落盘之前一行都不写", not os.path.exists(p4))
    # ⑥ 接线
    根目录 = os.path.dirname(HERE)
    sdk = open(os.path.join(根目录, "agentsite", "sdk.py"), encoding="utf-8").read()
    app = open(os.path.join(根目录, "agentsite", "app.py"), encoding="utf-8").read()
    ck("聊天站开了边跑边记", "tid=_tid, 边跑边记=True)" in sdk)
    ck("聊天接口出错时补记中断,并把 trace 号回给页面", "_sp.记中断(轮[0], 轮[1]" in app and '"trace_id": 轮[0]}' in app)
    print()
    if 坏:
        print(f"{R}❌ 边跑边记 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 边跑边记:崩了也留下已收尾的、补记中断不丢原属性、久未收尾判中断、正常跑完不重复(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
