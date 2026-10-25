# -*- coding: utf-8 -*-
"""聊天页证据面板 · 工具返回值按调用号对位(证据中心 10-25)。

原来按「第几个」对:中间有一次没记到,后面每一条都错一位 —— 错位的返回值和对的长得一样,不报错。
从 station.html 里**原样抠出** `返回值对位`,用 node 真调它(不在这里照样子重写一份)。
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("返回值退回按下标对(不看调用号)", "中间一次没记到:后面那条仍对到自己的返回值,不错位"),
    ("调用号找不到时拿下标那条顶上", "有调用号但没记到 → 显示没记到,不拿别人的返回值顶上"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {附}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def 调(号们, spans):
    src = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    m = re.search(r"function 返回值对位\(号们, spans\)\{.*?\n\}", src, re.S)
    if not m:
        raise SystemExit(f"{R}❌ station.html 里找不到 返回值对位 —— 这条判据读不到东西,不算通过{D}")
    js = m.group(0) + f"\nconsole.log(JSON.stringify(返回值对位({json.dumps(号们)}, {json.dumps(spans)})));"
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise SystemExit(f"{R}❌ node 跑不起来:{r.stderr[-300:]}{D}")
    return json.loads(r.stdout)


def sp(号, 值):
    return {"attr": {"gen_ai.tool.call.id": 号, "gen_ai.tool.call.result": 值}}


def main():
    print("聊天页证据面板 · 工具返回值按调用号对位")
    # 三次调用,第二次没记到 span(进程在那一步前后出过事 / 记录被截)
    out = 调(["t1", "t2", "t3"], [sp("t1", "一"), sp("t3", "三")])
    值 = [(x["sp"] or {}).get("attr", {}).get("gen_ai.tool.call.result") for x in out]
    ck("中间一次没记到:后面那条仍对到自己的返回值,不错位", 值[2] == "三", 值)
    ck("有调用号但没记到 → 显示没记到,不拿别人的返回值顶上", 值[1] is None, 值)
    ck("顺序打乱的 span 也按号对上", [(x["sp"] or {})["attr"]["gen_ai.tool.call.result"]
       for x in 调(["a", "b"], [sp("b", "B"), sp("a", "A")])] == ["A", "B"])
    老 = 调(["", ""], [sp("x", "甲"), sp("y", "乙")])
    ck("老对话没调用号 → 按先后对,并标「按顺序」", [x["按顺序"] for x in 老] == [True, True]
       and 老[1]["sp"]["attr"]["gen_ai.tool.call.result"] == "乙", 老)
    # 接线:轨迹里真的带着调用号(sdk.py 写进去),工具行真的把它挂在 data-call 上
    sdk = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    ck("sdk 轨迹每条带调用号(\"id\": _tu)", '"args": getattr(b, "input", {}), "id": _tu}' in sdk)
    html = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    ck("工具行挂着调用号(data-call),补返回值走 返回值对位", 'data-call="${esc(t.id || "")}"' in html
       and "返回值对位(rows.map(" in html)
    print()
    if 坏:
        print(f"{R}❌ 证据面板对位 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 证据面板按调用号对位:没记到的不错位、不顶替,老对话按顺序并标出(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
