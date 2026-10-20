#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判专用角色 · 检查(用户 2026-10-20 拍「做」)。

研判原来跑后台运营助手那一整包(72 个工具、3.1 万字提示词,含开单 / 确认下单 / 撤单这类写工具)。
三代对比 10-20 实测 V3 调用数没变而成本是 09-16 的 1.6–2.9 倍 —— 每次调用都要把整包带上。
现在研判走 `sdk.run("triage", …)`:规矩还是后台运营那一套,工具收到 `sdk.研判工具`,提示词跟着只装管这些工具的规矩。

要守的:
  ① **截住 run("triage") 真交给 SDK 的配置**:MCP 暴露的 = allowed_tools = 研判工具;提示词就是 SYS_TRIAGE(+ 身份段)。
     run("task") 照旧是后台运营的全包 —— 只收研判这一条路
  ② 研判工具**全是只读**(不在写工具名单里)
  ③ 每类研判的提示词里点名要查的工具,都在研判工具里(否则研判会被叫去调一个它没有的工具)
  ④ 客户合并的判定标准(TK05)还在研判提示词里 —— 三代必须拿到同一份标准
  ⑤ 研判那几条路走 triage、差评研判**不走**(它最要紧的 TK16 / TK13 要挂着差评工具才装,收窄会一起收掉)
不调模型、不花钱:SDK 的选项构造被截住,跑不到真调用。
"""
import asyncio, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("run 不认 triage(研判还是拿后台运营全包)", "run(\"triage\") 交给 SDK 的工具 = 研判工具(MCP 暴露的、allowed_tools 是同一份)"),
    ("研判工具里混进一个写工具", "研判工具全是只读"),
    ("研判队列那一路还跑 task", "研判队列 / 隔离试运行 / 三代对比都走 triage;差评研判照旧走 task"),
]
坏, n = [], 0


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("研判专用角色 · 只挂研判用得上的只读工具")
print("=" * 80)
import sdk, api, ops


class _截住(Exception):
    pass


def 截一轮(kind):
    抓 = {}
    真 = sdk.ClaudeAgentOptions
    def 截(**kw):
        抓.update(kw); raise _截住()
    sdk.ClaudeAgentOptions = 截
    try:
        asyncio.run(sdk.run(kind, "测", guard=False))
    except _截住:
        pass
    except Exception as e:                       # noqa: BLE001 —— run 自己崩了也算这条不过,要红在点名那条上,不是整份崩掉
        抓["崩了"] = f"{type(e).__name__}: {e}"
    finally:
        sdk.ClaudeAgentOptions = 真
    暴露 = sorted(f"mcp__{k}__{t}" for k, v in (抓.get("mcp_servers") or {}).items()
                  for t in v["env"].get("LANXIU_TOOLS", "").split(",") if t)
    return 抓, 暴露


抓, 暴露 = 截一轮("triage")
ck("run(\"triage\") 交给 SDK 的工具 = 研判工具(MCP 暴露的、allowed_tools 是同一份)",
   not 抓.get("崩了") and 暴露 == sorted(抓.get("allowed_tools") or []) == sorted(sdk.研判工具),
   抓.get("崩了") or (暴露, 抓.get("allowed_tools")))
ck("run(\"triage\") 的提示词就是研判那份(不是后台运营全集那份)",
   (抓.get("system_prompt") or "").startswith(sdk.SYS_TRIAGE) and not (抓.get("system_prompt") or "").startswith(sdk.SYS_TASK))
抓2, 暴露2 = 截一轮("task")
ck("run(\"task\") 照旧是后台运营全包(只收研判这一条路)", len(暴露2) > len(暴露) and set(暴露) <= set(暴露2),
   (len(暴露2), len(暴露)))

写 = {str(x).rsplit("__", 1)[-1] for x in api.WRITE_TOOLS}
ck("研判工具全是只读", bool(sdk.研判工具) and not ({t.rsplit("__", 1)[-1] for t in sdk.研判工具} & 写),
   {t.rsplit("__", 1)[-1] for t in sdk.研判工具} & 写)

# ③ 每类研判提示词里点名的工具 —— 拿全部工具名去提示词正文里找(真调 ops.研判提示词,不抄模板)
全部名 = {t.rsplit("__", 1)[-1] for t in sdk._tools_for("all")} | {t.rsplit("__", 1)[-1] for t in sdk._tools_for("task")}
研判名 = {t.rsplit("__", 1)[-1] for t in sdk.研判工具}
点名, 验 = {}, 0
for 类, ref, tid in (("财务人工任务", "DQ-X", "TD-X"), ("客户合并确认", "C1|C2", "TMERGE-X"), ("售后判责", "MT-X", "TMQ-X")):
    try:
        _, _, 正文 = ops.研判提示词(类, ref, tid)
    except Exception as e:                       # noqa: BLE001
        点名[类] = f"取不到提示词:{e}"; continue
    验 += 1
    点名[类] = sorted(x for x in 全部名 if re.search(rf"\b{re.escape(x)}\b", 正文))
缺 = {k: [x for x in v if x not in 研判名] for k, v in 点名.items() if isinstance(v, list)}
ck("每类研判提示词里点名要查的工具都在研判工具里(三类)",
   验 == 3 and not any(缺.values()), (点名, 缺))

ck("客户合并判定标准(TK05)还在研判提示词里", "TK05" in sdk.TRIAGE_RULE_IDS, sdk.TRIAGE_RULE_IDS)

def 源(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()
ck("研判队列 / 隔离试运行 / 三代对比都走 triage;差评研判照旧走 task",
   'sdk.run("triage", prompt), 单条超时秒' in 源("agentsite/app.py")
   and 'sdk.run("triage", 提示)' in 源("agentsite/trial_run.py")
   and 'sdk.run("triage", p)' in 源("agent/gen_compare.py")
   and 'sdk.run("task", prompt, me=me, 被判包裹=ref,' in 源("agentsite/rating_triage.py"))
ck("研判版本号用研判那份提示词算指纹(研判队列、隔离试运行)",
   "sdk.SYS_TRIAGE.encode" in 源("agentsite/app.py") and "sdk.SYS_TRIAGE.encode" in 源("agentsite/trial_run.py"))

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判专用角色:{len(sdk.研判工具)} 个只读工具,提示词 {len(sdk.SYS_TRIAGE)} 字(后台运营全包 {len(sdk.SYS_TASK)} 字)(验了 {n} 条){D}")
