#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天站执行记录导入 · 端到端(2026-10-25,证据中心第四个工作包)。

真服务 + 真库。聊天站那一侧测试自己扮演(推过来的体由测试造)。
  ① 导入一轮 → 201;同一轮已收尾再导 → 不重写
  ② 运行记录列表按「聊天站」筛得到;调用树里原文**只给有「查看敏感输入」授权的**(用户 10-25 拍「平台管理员看原文」)
  ③ 进行中的那一轮,收尾后再导 → 同一条 trace,整棵换成新的
  ④ 超过 30 天的聊天站原文 → 下一次导入时换成到期说明,骨架留着
  ⑤ 执行故障上报(用户 10-25 拍「换模型也没用的直接上报」「上报给平台管理员」):带上报的一轮建一张单、一轮只一张、
     只有平台管理员看得到和能标、标要写怎么处理的、标过的不再改;认不出的类 422
  ⑥ 结论 ↔ 证据逐句核对(用户 10-25 拍「后台运行记录也要看得到」):跟着导入存下;计数和状态人人可见,
     句子正文只给有「查看敏感输入」的;已收尾的轮补推只补这一栏、已有的不覆盖;格式不对 422
"""
import time
from urllib.parse import quote
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(根, ".venv", "bin", "python")
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None




def 导(体):
    return 打("POST", P + "/trace-imports", "U001", 体=体)


def 步(sid, parent=None, stage="execute_tool get_customer", 入=None, 出=None, 开始=None):
    return {"id": sid, "parent": parent, "stage": stage, "开始": 开始 or time.time(), "结束": time.time(), "状态": "unset",
            "入": 入, "出": 出}


外 = "e2e" + uuid.uuid4().hex[:10]
原文 = "客户 13812345678 的完整档案"
print("▸ ① 导入一轮(收尾了的)")
c, r = 导({"外部trace": 外, "会话号": "会话-e2e", "状态": "unset", "开始": time.time() - 5, "结束": time.time(),
          "步们": [步("root", stage="invoke_agent 澜绣云裳助手", 入={"提问": "查一下客户"}),
                  步("k1", "root", 入={"工具": "mcp__crm__get_customer", "参数": "{}", "是原文": True},
                    出={"返回": 原文, "是原文": True})]})
ck("导入 → 201,两步", c == 201 and r.get("导入了吗") is True and r.get("步数") == 2, (c, r))
tid = (r or {}).get("trace_id")
c, r2 = 导({"外部trace": 外, "状态": "unset", "开始": time.time(), "步们": [步("x")]})
ck("**同一轮再导一次(已收尾)→ 不重写**", c == 201 and r2.get("导入了吗") is False and r2.get("trace_id") == tid, (c, r2))

print("\n▸ ② 列表和调用树")
c, l = 打("GET", P + "/traces?limit=200&entry_kind=" + quote("聊天站"), "U002")
行 = [x for x in (l or {}).get("items") or [] if x["id"] == tid]
ck("运行记录列表按「聊天站」筛得到这一轮,带会话号", 行 and 行[0].get("session_id") == "会话-e2e" and 行[0].get("entry_kind") == "聊天站", 行)
c, d = 打("GET", P + f"/traces/{tid}", "U002")
ck("没有专项授权的(U002)→ 调用树里**看不到原文**,只有形状", c == 200 and 原文 not in json.dumps(d, ensure_ascii=False)
   and d.get("看得到原文吗") is False, (c, str(d)[:200]))
c, d = 打("GET", P + f"/traces/{tid}", "U004")
ck("有「查看敏感输入」的(U004)→ 看得到原文(完整手机号)", c == 200 and "13812345678" in json.dumps(d, ensure_ascii=False), (c, str(d)[:200]))
ck("父子关系对得上(工具那步挂在根下面)", any(s.get("parent_span_id") and s["parent_span_id"].endswith("_root")
                                      for s in (d or {}).get("步们") or []), (d or {}).get("步们"))

print("\n▸ ③ 进行中的那一轮,收尾后再导 → 换成新的")
外2 = "e2e" + uuid.uuid4().hex[:10]
c, a = 导({"外部trace": 外2, "状态": "进行中", "开始": time.time(), "步们": [步("root", stage="invoke_agent x")]})
c, b = 导({"外部trace": 外2, "状态": "unset", "开始": time.time(), "结束": time.time(),
          "步们": [步("root", stage="invoke_agent x"), 步("k1", "root"), 步("k2", "root")]})
c, d = 打("GET", P + f"/traces/{a['trace_id']}", "U004")
ck("**进行中 → 收尾后再导:同一条 trace,步数换成新的 3 步**", b.get("trace_id") == a.get("trace_id") and b.get("导入了吗") is True
   and len((d or {}).get("步们") or []) == 3, (a, b, len((d or {}).get("步们") or [])))
c, l = 打("GET", P + "/traces?limit=200&entry_kind=" + quote("聊天站"), "U002")
状 = {x["id"]: x["end_reason"] for x in (l or {}).get("items") or []}
ck("状态跟着收尾改成 completed", 状.get(a.get("trace_id")) == "completed", 状.get(a.get("trace_id")))

print("\n▸ ④ 原文 30 天到期")
外3 = "e2e" + uuid.uuid4().hex[:10]
老 = time.time() - 31 * 86400
c, o = 导({"外部trace": 外3, "状态": "unset", "开始": 老, "结束": 老,
          "步们": [步("k1", 入={"参数": "老的原文 13900000000"}, 出={"返回": "老的返回"}, 开始=老)]})
c, n = 导({"外部trace": "e2e" + uuid.uuid4().hex[:10], "状态": "unset", "开始": time.time(), "步们": [步("y")]})
c, d = 打("GET", P + f"/traces/{o['trace_id']}", "U004")
s = json.dumps(d, ensure_ascii=False)
ck("**超过 30 天的聊天站原文:下一次导入时换成到期说明**(骨架留着)", "13900000000" not in s and "到期删除" in s
   and len((d or {}).get("步们") or []) == 1, s[:300])

print("\n▸ ⑤ 执行故障上报")
外5 = "e2e" + uuid.uuid4().hex[:10]
报 = {"类": "环境故障", "理由": "工具 kb_size 碰到数据库故障(database is locked)"}
c, r5 = 导({"外部trace": 外5, "状态": "unset", "开始": time.time(), "结束": time.time(), "步们": [步("root")], "上报": 报})
ck("带上报的一轮导入 → 201,说上报了", c == 201 and r5.get("上报了吗") is True, (c, r5))
c, again = 导({"外部trace": 外5, "状态": "unset", "开始": time.time(), "结束": time.time(), "步们": [步("root")], "上报": 报})
c, l = 打("GET", P + "/trace-incidents?limit=200", "U001")
我的 = [i for i in (l or {}).get("items") or [] if i["trace_id"] == r5.get("trace_id")]
ck("**同一轮再推一次 → 还是只有一张单**,待处理、类和理由原样", len(我的) == 1 and 我的[0]["status"] == "待处理"
   and 我的[0]["kind"] == "环境故障" and "locked" in 我的[0]["reason"], 我的)
外6 = "e2e" + uuid.uuid4().hex[:10]
c, r6 = 导({"外部trace": 外6, "状态": "unset", "开始": time.time(), "结束": time.time(), "步们": [步("root")]})
c, l = 打("GET", P + "/trace-incidents?limit=200", "U001")
ck("没带上报的一轮 → 不建单", not [i for i in (l or {}).get("items") or [] if i["trace_id"] == r6.get("trace_id")])
c, 晚 = 导({"外部trace": 外6, "状态": "unset", "开始": time.time(), "步们": [步("root")],
           "上报": {"类": "撞花费上限", "理由": "这条会话累计花费到了上限 $50"}})
c, l = 打("GET", P + "/trace-incidents?limit=200", "U001")
晚单 = [i for i in (l or {}).get("items") or [] if i["trace_id"] == r6.get("trace_id")]
ck("**已收尾的一轮,轮末才补来上报 → 不重写记录,但单照样建**", 晚.get("导入了吗") is False and len(晚单) == 1
   and 晚单[0]["kind"] == "撞花费上限", (晚, 晚单))
c, bad = 导({"外部trace": "e2e" + uuid.uuid4().hex[:10], "状态": "unset", "开始": time.time(), "步们": [],
            "上报": {"类": "随便写的", "理由": "x"}})
ck("认不出的上报类 → 422(不建一张谁也看不懂的单)", c == 422, (c, bad))
c, _ = 打("GET", P + "/trace-incidents", "U002")
ck("编辑者(U002)看不到故障单 → 403", c == 403, c)
c, _ = 打("GET", P + "/trace-incidents", "U004")
ck("有原文授权的标注员(U004)也看不到 → 403(看原文和处理故障是两件事)", c == 403, c)
单 = 我的[0]["id"] if 我的 else "?"
c, _ = 打("POST", P + f"/trace-incidents/{单}/handle", "U002", 体={"note": "x"})
ck("编辑者标已处理 → 403", c == 403, c)
c, e = 打("POST", P + f"/trace-incidents/{单}/handle", "U001", 体={"note": "  "})
ck("不写怎么处理的 → 422", c == 422, (c, e))
c, h = 打("POST", P + f"/trace-incidents/{单}/handle", "U001", 体={"note": "夜间造数占了库,已错开"})
ck("平台管理员写了处理说明 → 标成已处理", c == 200 and (h or {}).get("status") == "已处理", (c, h))
c, h2 = 打("POST", P + f"/trace-incidents/{单}/handle", "U001", 体={"note": "再标一次"})
ck("**标过的再标 → 409 ALREADY_HANDLED**,不改原来的处理记录", c == 409 and (h2 or {}).get("code") == "ALREADY_HANDLED", (c, h2))
c, l = 打("GET", P + "/trace-incidents?limit=200", "U001")
这张 = [i for i in (l or {}).get("items") or [] if i["id"] == 单]
ck("处理记录记了谁、什么时候、怎么处理的", 这张 and 这张[0]["handled_by"] == "U001" and 这张[0]["handled_at"]
   and 这张[0]["note"] == "夜间造数占了库,已错开", 这张)
c, _ = 导({"外部trace": 外5, "状态": "unset", "开始": time.time(), "步们": [步("root")], "上报": 报})
c, l = 打("GET", P + "/trace-incidents?limit=200", "U001")
ck("**处理完之后同一轮又推来上报 → 不会被重新打开**", [i["status"] for i in (l or {}).get("items") or [] if i["id"] == 单] == ["已处理"])
# 测试自己建的单都收掉,不在共享库里留「待处理」
for i in 晚单:
    打("POST", P + f"/trace-incidents/{i['id']}/handle", "U001", 体={"note": "e2e 测试单,收掉"})

print("\n▸ ⑥ 结论 ↔ 证据逐句核对")
句 = "C90001 实付 5300 元,手机 13812345678。"
结 = {"计数": {"已核对": 1, "存在冲突": 1, "缺少依据": 0, "未判定": 2},
     "句们": [{"句": 句, "状态": "存在冲突", "理由": "5300 元:C90001 那条记录里没有这个值",
              "依据": [{"工具": "get_member", "路径": "会员等级.这段时间实付", "值": "C90001"}]},
             {"句": "建议先确认。", "状态": "未判定"}],
     "说明": "规则逐句比对,不调模型"}
外7 = "e2e" + uuid.uuid4().hex[:10]
c, r7 = 导({"外部trace": 外7, "状态": "unset", "开始": time.time(), "结束": time.time(), "步们": [步("root")], "结论": 结})
ck("带逐句核对的一轮导入 → 201,说带了", c == 201 and r7.get("带了逐句核对吗") is True, (c, r7))
c, d = 打("GET", P + f"/traces/{r7.get('trace_id')}", "U004")
ck("有「查看敏感输入」的(U004)→ 看得到每句正文、理由和计数", c == 200 and (d.get("结论") or {}).get("句们", [{}])[0].get("句") == 句
   and d["结论"]["计数"]["存在冲突"] == 1, (c, str(d.get("结论"))[:200]))
c, d = 打("GET", P + f"/traces/{r7.get('trace_id')}", "U002")
s7 = json.dumps(d, ensure_ascii=False)
ck("**没授权的(U002)→ 计数和每句状态看得到,句子正文 / 理由 / 值看不到**(手机号、客户号、金额都不出)",
   c == 200 and (d.get("结论") or {}).get("计数", {}).get("存在冲突") == 1
   and [x["状态"] for x in d["结论"]["句们"]] == ["存在冲突", "未判定"]
   and "13812345678" not in s7 and "5300" not in s7 and "C90001" not in s7, (c, s7[:300]))
ck("trace 整行里不夹带逐句核对(否则没授权的从 trace 那一栏就看到原句了)", "claims_snapshot" not in json.dumps(d.get("trace") or {}), list((d or {}).get("trace") or {}))
外8 = "e2e" + uuid.uuid4().hex[:10]
c, r8 = 导({"外部trace": 外8, "状态": "unset", "开始": time.time(), "结束": time.time(), "步们": [步("root")]})
c, 补 = 导({"外部trace": 外8, "状态": "unset", "开始": time.time(), "步们": [步("root")], "结论": 结})
c, d = 打("GET", P + f"/traces/{r8.get('trace_id')}", "U004")
ck("**已收尾、当时没带的一轮 → 补推只补逐句核对**,不重写记录", 补.get("导入了吗") is False and 补.get("补了逐句核对吗") is True
   and (d.get("结论") or {}).get("计数", {}).get("已核对") == 1, (补, str(d.get("结论"))[:120]))
c, 再 = 导({"外部trace": 外8, "状态": "unset", "开始": time.time(), "步们": [步("root")],
           "结论": {**结, "计数": {"已核对": 9, "存在冲突": 0, "缺少依据": 0, "未判定": 0}}})
c, d = 打("GET", P + f"/traces/{r8.get('trace_id')}", "U004")
ck("已经有的不覆盖(快照:当时判成什么就是什么)", 再.get("补了逐句核对吗") is False and d["结论"]["计数"]["已核对"] == 1, (再, d.get("结论", {}).get("计数")))
c, bad = 导({"外部trace": "e2e" + uuid.uuid4().hex[:10], "状态": "unset", "开始": time.time(), "步们": [],
            "结论": {"计数": {"随便": 1}, "句们": [{"句": "x", "状态": "差不多"}]}})
ck("认不出的状态 → 422(不存一份看不懂的核对)", c == 422, (c, bad))

print()
if 挂:
    print(f"❌ 执行记录导入:{len(挂)} 条不过(验了 {len(过) + len(挂)} 条)")
    sys.exit(1)
print(f"✅ 执行记录导入:收尾的不重写 / 进行中的换新 / 原文只给有授权的 / 30 天到期换说明 / 故障单一轮一张、只给平台管理员、标过不改 / 逐句核对按授权给、只补不覆盖(验了 {len(过)} 条)")
