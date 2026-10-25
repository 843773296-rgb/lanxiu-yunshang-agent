# -*- coding: utf-8 -*-
"""执行记录推送 · 推哪几轮、推什么(证据中心第四个工作包,10-25)。真调 tools/spans_push.py 的 要推的 / 载荷。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spans_push as SP

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("还在进行中的也推", "还「进行中」的不推(跑完或判中断以后再推)"),
    ("工具那步不用原文,只推展示副本", "工具那步有原文就推原文,并标「是原文」"),
    ("轮末补记的上报不算进签名", "推过之后轮末补记了上报 → 签名变了,重推"),
    ("推送不带逐句核对", "有回答的一轮:推的体里带逐句核对,用的是原文(和聊天站 /spans 同一个函数)"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def 根(tid, 状态, 起):
    return {"trace_id": tid, "span_id": "r", "parent_span_id": None, "name": "invoke_agent x", "start": 起,
            "status": 状态, "attr": {"gen_ai.operation.name": "invoke_agent", "lanxiu.prompt": "问"}}


def main():
    print("执行记录推送 · 推哪几轮、推什么")
    现在 = time.time()
    棵 = {"跑完": [根("跑完", "unset", 现在 - 100)], "在跑": [根("在跑", "进行中", 现在 - 10)],
         "断了": [根("断了", "中断", 现在 - 4000)], "太老": [根("太老", "unset", 现在 - 31 * 86400)]}
    要 = SP.要推的(棵, {}, 现在)
    ck("还「进行中」的不推(跑完或判中断以后再推)", "在跑" not in 要, 要)
    ck("跑完的、判中断的都推,老的先推", 要 == ["断了", "跑完"], 要)
    ck("超过 30 天的不推(原文就留这么久)", "太老" not in 要, 要)
    已 = {"跑完": SP.签名(棵["跑完"])}
    ck("推过、签名没变 → 不再推", "跑完" not in SP.要推的(棵, 已, 现在))
    棵["跑完"].append({"span_id": "k9", "parent_span_id": "r", "status": "unset", "attr": {}})
    ck("签名变了(多了一步 / 补记了中断)→ 重推", "跑完" in SP.要推的(棵, 已, 现在))
    ck("一次最多推 N 轮", len(SP.要推的({f"t{i}": [根(f"t{i}", "unset", 现在 - i)] for i in range(80)}, {}, 现在, 最多=50)) == 50)
    工具 = {"span_id": "c1", "parent_span_id": "r", "name": "execute_tool get_customer", "status": "unset",
          "attr": {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "get_customer",
                   "lanxiu.tool.full_name": "mcp__crm__get_customer", "gen_ai.tool.call.id": "c1",
                   "gen_ai.tool.call.arguments": "{\"phone\": \"138****5678\"}", "gen_ai.tool.call.result": "打码的"}}
    体 = SP.载荷("T", [根("T", "unset", 现在), 工具],
                [{"span": "c1", "哪段": "参数", "内容": "{\"phone\": \"13812345678\"}", "校验": "一致"},
                 {"span": "c1", "哪段": "返回", "内容": "原样的返回", "校验": "不一致 —— 存下以后被改过"}])
    步 = {s["id"]: s for s in 体["步们"]}
    ck("工具那步有原文就推原文,并标「是原文」", 步["c1"]["入"]["参数"] == "{\"phone\": \"13812345678\"}" and 步["c1"]["入"]["是原文"] is True, 步["c1"])
    ck("原文校验不一致的不推它,退回展示副本并标「不是原文」", 步["c1"]["出"]["返回"] == "打码的" and 步["c1"]["出"]["是原文"] is False, 步["c1"])
    ck("工具名带服务前缀;根带提问", 步["c1"]["入"]["工具"] == "mcp__crm__get_customer" and 步["r"]["入"]["提问"] == "问")
    # 上报:真走一遍「写一棵 → 轮末 spans.记上报 补到根上 → spans.读 合并」—— 合并后行数和状态都不变,签名要靠上报那一项变
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
    import spans as _SPN
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "s.jsonl")
        with open(f, "w", encoding="utf-8") as w:
            w.write(json.dumps(根("U", "unset", 现在), ensure_ascii=False) + "\n")
        前 = _SPN.读(f)["U"]
        已2 = {"U": SP.签名(前)}
        _SPN.记上报("U", "r", {"类": "环境故障", "理由": "工具 kb_size 碰到数据库故障(database is locked)"}, path=f)
        后 = _SPN.读(f)["U"]
    ck("推过之后轮末补记了上报 → 签名变了,重推", "U" in SP.要推的({"U": 后}, 已2, 现在), (SP.签名(前), SP.签名(后)))
    体2 = SP.载荷("U", 后, [])
    ck("带上报的那一轮,推的体里有「上报」{类, 理由}", (体2.get("上报") or {}).get("类") == "环境故障"
       and "locked" in 体2["上报"].get("理由", ""), 体2.get("上报"))
    ck("没上报的那一轮,体里不带「上报」(不推空单)", "上报" not in SP.载荷("U", 前, []))

    # ── 逐句核对跟着推(用户 10-25 拍:后台运行记录也要看得到)──
    答根 = 根("A", "unset", 现在)
    答根["attr"]["lanxiu.answer"] = "C90001 实付 5215.6 元。"
    客 = {"span_id": "c7", "parent_span_id": "r", "status": "unset",
         "attr": {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "get_member", "gen_ai.tool.call.id": "c7",
                  "gen_ai.tool.call.result": "…〔还有 300 字未记〕"}}
    原 = [{"span": "c7", "哪段": "返回", "内容": json.dumps({"客户号": "C90001", "实付": 5215.6}, ensure_ascii=False), "校验": "一致"}]
    结 = SP.逐句核对([答根, 客], 原)
    体3 = SP.载荷("A", [答根, 客], 原, SP.逐句核对([答根, 客], 原))
    ck("有回答的一轮:推的体里带逐句核对,用的是原文(和聊天站 /spans 同一个函数)",
       (体3.get("结论") or {}).get("计数", {}).get("已核对") == 1, 结)
    ck("没有回答的一轮(跑崩了)→ 不带逐句核对,不编一个", SP.逐句核对([根("B", "error", 现在)], []) is None
       and "结论" not in SP.载荷("B", [根("B", "error", 现在)], []))
    ck("签名带「核」:10-25 之前推过的轮会补推一次(接收端只补这一栏)", SP.签名([根("C", "unset", 现在)]).endswith(":核"))
    print()
    if 坏:
        print(f"{R}❌ 执行记录推送 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 执行记录推送:进行中不推、推过不重推、变了重推(含轮末补记的上报)、工具步优先原文(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
