#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把聊天站的执行记录推给管理后台(证据中心第四个工作包,10-25)。

    python3 tools/spans_push.py            # 推,一次最多 50 轮
    python3 tools/spans_push.py --看        # 只报要推几轮,一轮都不发

原来管理后台只收得到用量上报(每次一个汇总 span),聊天站一轮里调了哪些工具、传了什么、回了什么,那边看不到。
现在每一轮**收尾之后**(完成 / 出错 / 中断)推一次,接收端按「lanxiu-chat:<trace>」确切对上,不靠模糊匹配。
工具那几步带**原文**(.feynman/raw/,没打码没截断)—— 管理后台按「查看敏感输入」授权决定谁看得到正文。

  · 还「进行中」的不推:跑完或被判中断(半小时)之后再推,省得每一轮同步都把半棵树来回换
  · 推过的记在 .feynman/spans-pushed.json(trace → 签名);签名变了(比如中断之后补记了原因)才重推
  · 只推 30 天内的(原文就留这么久;更早的推过去也只剩骨架)
要配:LANXIU_USAGE_URL / LANXIU_USAGE_USER(和用量上报同一套);项目用 LANXIU_TRACE_PROJECT,
不给就用 LANXIU_BRIDGE_PROJECT(正式项目 —— 聊天站是真业务,不往演示项目里推)。
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
import spans as SP

已推文件 = os.path.join(ROOT, ".feynman", "spans-pushed.json")
一次最多 = 50
最远天 = 30


def 签名(rows):
    根 = next((x for x in rows if not x.get("parent_span_id")), {})
    # 上报是轮末补记到根上的(读的时候合并,行数和状态都不变)—— 不算进签名的话,先推过的那一轮带着上报也不会再推
    报 = (根.get("attr") or {}).get("lanxiu.report.kind")
    return f"{len(rows)}:{根.get('status')}" + (f":报={报}" if 报 else "")


def 要推的(棵们, 已推, 现在=None, 最多=一次最多):
    """{trace: spans} + {trace: 签名} → [trace...](老的先推)。纯函数,spans_push_check 真调它。"""
    现在 = 现在 or time.time()
    候 = []
    for tid, rows in 棵们.items():
        根 = next((x for x in rows if not x.get("parent_span_id")), None)
        if not 根 or 根.get("status") == "进行中":
            continue
        if 现在 - (根.get("start") or 0) > 最远天 * 86400:
            continue
        if 已推.get(tid) == 签名(rows):
            continue
        候.append((根.get("start") or 0, tid))
    return [t for _, t in sorted(候)[:最多]]


def 载荷(tid, rows, 原文条):
    """一轮 → 接收端要的体。工具那几步优先用原文(有就用,标「是原文」),没有才用展示副本(并标出来)。"""
    原 = {(x.get("span"), x.get("哪段")): x.get("内容") for x in 原文条 if x.get("校验") == "一致"}
    根 = next((x for x in rows if not x.get("parent_span_id")), {})
    步们 = []
    for s in rows:
        a = s.get("attr") or {}
        op = a.get("gen_ai.operation.name")
        if op == "execute_tool":
            参, 返 = 原.get((s["span_id"], "参数")), 原.get((s["span_id"], "返回"))
            入 = {"工具": a.get("lanxiu.tool.full_name") or a.get("gen_ai.tool.name"), "调用号": a.get("gen_ai.tool.call.id"),
                 "参数": 参 if 参 is not None else a.get("gen_ai.tool.call.arguments"), "是原文": 参 is not None}
            出 = ({"返回": 返 if 返 is not None else a.get("gen_ai.tool.call.result"), "是原文": 返 is not None}
                 if (返 is not None or "gen_ai.tool.call.result" in a) else None)
        elif op == "chat":
            入 = {"模型": a.get("gen_ai.response.model") or a.get("gen_ai.request.model")}
            出 = {k: a.get(k) for k in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens") if a.get(k) is not None} or None
        elif op == "invoke_agent":
            入 = {"提问": a.get("lanxiu.prompt"), "角色": s.get("角色")}
            出 = {"回答": a.get("lanxiu.answer")} if a.get("lanxiu.answer") else None
        else:
            入, 出 = None, None
        错 = ({"状态": s.get("status"), "中断": a.get("lanxiu.interrupted")}
             if s.get("status") in ("error", "未收尾", "中断") else None)
        步们.append({"id": s["span_id"], "parent": s.get("parent_span_id"), "stage": s.get("name"),
                   "开始": s.get("start"), "结束": s.get("end"), "状态": s.get("status"), "入": 入, "出": 出, "错": 错})
    ra = 根.get("attr") or {}
    报 = ({"类": ra["lanxiu.report.kind"], "理由": ra.get("lanxiu.report.reason") or ""}
         if ra.get("lanxiu.report.kind") else None)
    return {"外部trace": tid, "会话号": 根.get("会话号"), "状态": 根.get("status"),
            "开始": 根.get("start"), "结束": 根.get("end"), "步们": 步们, **({"上报": 报} if 报 else {})}


def 配置():
    return dict(地址=os.environ.get("LANXIU_USAGE_URL"), 工号=os.environ.get("LANXIU_USAGE_USER"),
                项目=os.environ.get("LANXIU_TRACE_PROJECT") or os.environ.get("LANXIU_BRIDGE_PROJECT"))


def _发(cfg, 体):
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}/trace-imports"
    r = subprocess.run(["curl", "-sS", "-m", "20", "-X", "POST", url, "-H", "Content-Type: application/json",
                        "-H", f"X-Dev-User: {cfg['工号']}", "--data-binary", "@-", "-w", "\n%{http_code}"],
                       input=json.dumps(体, ensure_ascii=False), capture_output=True, text=True, timeout=30)
    正文, _, 码 = (r.stdout or "").rpartition("\n")
    return 码.strip(), 正文[:300] if r.returncode == 0 else f"curl 退 {r.returncode}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true")
    a = ap.parse_args()
    try:
        已推 = json.load(open(已推文件, encoding="utf-8"))
    except (OSError, ValueError):
        已推 = {}
    棵们 = SP.读()
    要 = 要推的(棵们, 已推)
    print(f"执行记录推送 · 要推 {len(要)} 轮(一次最多 {一次最多})")
    if a.看 or not 要:
        return 0
    cfg = 配置()
    缺 = [k for k, v in cfg.items() if not v]
    if 缺:
        print(f"  ⚠️ **没配推送地址,一轮都发不出去** —— 缺 {'/'.join(缺)}(LANXIU_USAGE_URL / LANXIU_USAGE_USER / LANXIU_BRIDGE_PROJECT)")
        return 2
    成, 败 = 0, {}
    for tid in 要:
        条, _ = SP.读原文(tid)
        码, 回 = _发(cfg, 载荷(tid, 棵们[tid], 条))
        if 码 in ("200", "201"):
            已推[tid] = 签名(棵们[tid]); 成 += 1
        else:
            败.setdefault(f"{码} {回[:80]}", []).append(tid)
    os.makedirs(os.path.dirname(已推文件), exist_ok=True)
    json.dump(已推, open(已推文件, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  推了 {成} 轮" + "".join(f";{len(v)} 轮没推成({k})" for k, v in 败.items()))
    return 0 if not 败 else 1


if __name__ == "__main__":
    sys.exit(main())
