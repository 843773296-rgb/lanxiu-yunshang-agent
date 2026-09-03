#!/usr/bin/env python3
"""V1 · 纯 API 循环。自己写 while(tool_use),自己定义和执行工具,不用任何编排框架。

HTTP 一律走 curl(本机 Python 的 TLS 校验会被中间人拦截失败)。
记录仪同时记 cost_usd(供应商口径)与 cost_local(按当前单价自算),用 cost_source 标明该信哪个。
"""
import json, os, subprocess, sys, time
import trace as _trace
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","backend"))
import api as backend
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","mcp"))
import client as mcp                    # 只读,不启动进程;USE_MCP=1 时才真的拉起来

def _tools(kind, extra=()):
    """工具来源:默认直连 api.py;USE_MCP=1 时改走 MCP。
    两条通道给出的 schema 同形、返回同形,所以**循环代码一个字都不用改**。"""
    if mcp.enabled():
        return mcp.get(kind).schemas() + list(extra)
    return (backend.KB_SCHEMAS if kind == "kb" else backend.SCHEMAS) + list(extra)

def _dispatch(kind, name, args):
    if mcp.enabled():
        return mcp.get(kind).call(name, **args)
    fn = backend.TOOLS.get(name)
    return fn(**args) if fn else {"error": f"未知工具 {name}"}

HERE=os.path.dirname(os.path.abspath(__file__))
TRACE=os.path.join(HERE,"llm-trace.jsonl")

# Anthropic 官方单价(美元 / 百万 token),缓存读取按输入的 0.1 倍
PRICE={"claude-opus-5":  dict(inp=5.0, cache=0.5,  out=25.0),
       "claude-opus-4-8":dict(inp=5.0, cache=0.5,  out=25.0),
       "claude-sonnet-5":dict(inp=2.0, cache=0.2,  out=10.0),
       "claude-haiku-4-5":dict(inp=1.0,cache=0.1,  out=5.0)}
def price_of(model):
    if model in PRICE: return PRICE[model]
    raise SystemExit(f"没有 {model} 的单价,拒绝用错误单价算成本(帕鲁项目踩过:虚高 12.5 倍)")

# ── 供应商解析(与 v1-raw-loop/src/api.ts 同逻辑)──────────
def provider():
    k=os.environ.get("DEEPSEEK_API_KEY")
    if k: return dict(id="deepseek",url="https://api.deepseek.com/anthropic/v1/messages",
        model=os.environ.get("DEEPSEEK_MODEL","deepseek-v4-pro"),
        headers=["x-api-key: "+k,"anthropic-version: 2023-06-01"],
        price=dict(inp=0.55,cache=0.055,out=2.19))
    k=os.environ.get("ANTHROPIC_API_KEY")
    if k:
        m=os.environ.get("ANTHROPIC_MODEL","claude-opus-5")
        return dict(id="claude",url="https://api.anthropic.com/v1/messages",model=m,
            headers=["x-api-key: "+k,"anthropic-version: 2023-06-01"],price=price_of(m))
    out=subprocess.run(["security","find-generic-password","-s","Claude Code-credentials","-w"],
                       capture_output=True,text=True)
    if out.returncode!=0: sys.exit("没有可用凭证:设置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY")
    tok=json.loads(out.stdout).get("claudeAiOauth",{}).get("accessToken")
    if not tok: sys.exit("钥匙串里没有 accessToken")
    m=os.environ.get("ANTHROPIC_MODEL","claude-haiku-4-5")
    return dict(id="claude-oauth",url="https://api.anthropic.com/v1/messages",model=m,
        headers=["authorization: Bearer "+tok,"anthropic-version: 2023-06-01",
                 "anthropic-beta: oauth-2025-04-20"],price=price_of(m))

def call(pv, body, retries=6, purpose="未标注", turn=None, cache=None):
    """限流退避:OAuth 凭证与本机 Claude Code 会话共用额度,必须退让。

    这是全项目唯一真正发出请求的地方 —— 记录仪就包在这一层,
    所以两个智能体、三套评测集、页面上的每一次点击,全都会被记下来。
    """
    # 提示词缓存(实验开关):把 system 改成带 cache_control 的块。
    # 渲染顺序是 tools → system → messages,所以标在 system 上,
    # 缓存的正好是「工具说明书 + 系统提示词」这段每轮都一样的前缀。
    if (cache if cache is not None else os.environ.get("PROMPT_CACHE")=="1") \
       and isinstance(body.get("system"), str):
        body=dict(body, system=[{"type":"text","text":body["system"],
                                 "cache_control":{"type":"ephemeral"}}])
    cmd=["curl","-sS","-X","POST",pv["url"],"-H","content-type: application/json"]
    for h in pv["headers"]: cmd += ["-H",h]
    cmd += ["--data-binary","@-"]
    delay=8
    for att in range(retries):
        t0=time.time()
        r=subprocess.run(cmd,input=json.dumps(body),capture_output=True,text=True)
        ms=(time.time()-t0)*1000
        def _rec(**kw):
            try: _trace.record(model=pv.get("model"),purpose=purpose,price=pv.get("price"),
                               latency_ms=ms,turn=turn,attempt=att,body=body,
                               cache_on=not isinstance(body.get("system"),str),**kw)
            except Exception: pass          # 记录仪永远不能把主流程搞挂
        if r.returncode!=0:
            _rec(usage=None,error=f"curl 失败: {r.stderr[:200]}")
            raise RuntimeError(f"curl 失败: {r.stderr[:300]}")
        try: resp=json.loads(r.stdout)
        except Exception:
            _rec(usage=None,error=f"响应不是 JSON: {r.stdout[:200]}")
            raise RuntimeError(f"响应不是 JSON: {r.stdout[:300]}")
        err=resp.get("error",{})
        if err.get("type") in ("rate_limit_error","overloaded_error","api_error"):
            _rec(usage=None,error=f"{err.get('type')}: {err.get('message','')[:120]}")
            if att==retries-1: raise RuntimeError(f"重试 {retries} 次仍限流")
            time.sleep(delay); delay=min(delay*2,120); continue
        _rec(usage=resp.get("usage"),finish_reason=resp.get("stop_reason"),
             resp_text="".join(b.get("text","") for b in resp.get("content",[]) if b.get("type")=="text"))
        return resp

SUBMIT={"name":"submit_finding","description":"提交最终草稿。调用后本次分析结束。",
  "input_schema":{"type":"object","properties":{
    "root_cause":{"type":"string","description":"一句话根因"},
    "recommended_action":{"type":"string","description":"建议的处理动作"},
    "evidence":{"type":"array","items":{"type":"string"},
                "description":"支撑结论的具体证据,每条必须引用真实存在的编号或字段值"},
    "confidence":{"type":"string","enum":["高","中","低"]}},
  "required":["root_cause","recommended_action","evidence","confidence"]}}

SYSTEM="""你是澜绣云裳门店客户运营管理后台的人工任务助手。

你的产出是**草稿**,供人确认或修改后使用。你没有任何写权限,不得建议由你自己执行操作。

铁律:
1. 结论必须建立在你实际读到的数据上。引用的每一个编号(押金单号、流水号、客户ID)都必须是你从工具返回值里看到的原文,不得编造或推测。
2. 数据不足以判断时,confidence 填「低」,并在 root_cause 里写明缺什么。
3. 不得建议绕过审批链、幂等号或重试上限。退款必须由客服或店长发起、店长复核,单笔达 1000 元时增加财务复核。
4. 分析完成后调用 submit_finding 提交,不要用纯文本回复结论。"""

def run_case(pv, prompt, max_turns=12, purpose="人工任务"):
    msgs=[{"role":"user","content":prompt}]
    tools=_tools("task",[SUBMIT])
    tin=tout=tcache=0; calls=0; t0=time.time(); finding=None; traj=[]; last_text=""
    for _t in range(max_turns):
        resp=call(pv,dict(model=pv["model"],max_tokens=2000,system=SYSTEM,tools=tools,messages=msgs),
                  purpose=purpose,turn=_t+1)
        if "error" in resp: raise RuntimeError(json.dumps(resp["error"],ensure_ascii=False)[:300])
        calls+=1
        u=resp.get("usage",{})
        tin+=u.get("input_tokens",0); tout+=u.get("output_tokens",0)
        tcache+=u.get("cache_read_input_tokens",0)
        msgs.append({"role":"assistant","content":resp["content"]})
        # 模型选择不调 submit_finding 时,纯文本就是它的全部回答 —— 不留下来就等于什么都没看见
        txt="".join(b.get("text","") for b in resp["content"] if b.get("type")=="text").strip()
        if txt: last_text=txt
        if resp.get("stop_reason")!="tool_use": break
        results=[]
        for blk in resp["content"]:
            if blk.get("type")!="tool_use": continue
            traj.append(blk["name"])
            if blk["name"]=="submit_finding":
                finding=blk["input"]
                results.append({"type":"tool_result","tool_use_id":blk["id"],"content":"已提交"})
                continue
            try: out=_dispatch("task",blk["name"],blk["input"])
            except Exception as e: out={"error":str(e)}
            results.append({"type":"tool_result","tool_use_id":blk["id"],
                            "content":json.dumps(out,ensure_ascii=False)})
        msgs.append({"role":"user","content":results})
        if finding: break
    p=pv["price"]
    cost=(tin*p["inp"]+tcache*p["cache"]+tout*p["out"])/1_000_000
    return dict(finding=finding,text=last_text,calls=calls,input=tin,output=tout,cache=tcache,
                cost_local=round(cost,6),cost_source=pv["id"],
                seconds=round(time.time()-t0,1),trajectory=traj)

BP01="""任务类型:财务人工任务
押金单号:{ref}

这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,给出建议的处理动作,并列出支撑结论的证据。"""

BP02="""任务类型:客户合并确认
两条疑似重复的客户档案:{a} 和 {b}

请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。"""

def one(task_id):
    """被后台页面调用:跑单个任务,最后一行输出 JSON。"""
    t=[x for x in backend.list_tasks(None,"待处理") if x["id"]==task_id]
    if not t: print(json.dumps({"error":"任务不存在"},ensure_ascii=False)); return
    t=t[0]
    if t["type"]=="财务人工任务": prompt=BP01.format(ref=t["ref_id"])
    else:
        a,b=t["ref_id"].split("|"); prompt=BP02.format(a=a,b=b)
    try:
        pv=provider(); r=run_case(pv,prompt); r["task_id"]=task_id
    except Exception as e:
        r={"finding":None,"error":str(e)[:300],"task_id":task_id}
    print(json.dumps(r,ensure_ascii=False))

if __name__=="__main__":
    if len(sys.argv)>2 and sys.argv[1]=="one":
        one(sys.argv[2]); sys.exit(0)
    pv=provider(); print(f"供应商 {pv['id']} / 模型 {pv['model']}\n")
    which=sys.argv[1] if len(sys.argv)>1 else "smoke"
    tasks=backend.list_tasks("财务人工任务")+backend.list_tasks("客户合并确认")
    if which=="smoke": tasks=[tasks[0],tasks[24]]
    elif which=="subset":
        # 每类真因各取一个:6 类退款 × 1 + 同一人/不同人 各 1
        tasks=[tasks[i] for i in [0,4,8,12,16,20,24,32]]
    recs=[]
    for i,t in enumerate(tasks,1):
        if t["type"]=="财务人工任务": prompt=BP01.format(ref=t["ref_id"]); case=t["ref_id"]
        else:
            a,b=t["ref_id"].split("|"); prompt=BP02.format(a=a,b=b); case=t["id"][1:]
        try: r=run_case(pv,prompt)
        except Exception as e: r=dict(finding=None,error=str(e)[:200]); print(f"[{i}] {case} 失败: {e}")
        r.update(case=case,bp="BP-01" if t["type"]=="财务人工任务" else "BP-02")
        recs.append(r)
        f=r.get("finding")
        print(f"[{i:2d}] {case:12s} {r.get('calls','-'):>2} 次调用  "
              f"{r.get('seconds','-'):>5}s  ${r.get('cost_local',0):.4f}  "
              f"{(f['root_cause'][:38] if f else '未提交')}")
    with open(os.path.join(HERE,"v1-results.jsonl"),"w") as fh:
        for r in recs: fh.write(json.dumps(r,ensure_ascii=False)+"\n")
    ok=[r for r in recs if r.get("finding")]
    print(f"\n完成 {len(ok)}/{len(recs)} | 总成本 ${sum(r.get('cost_local',0) for r in recs):.4f} "
          f"| 总调用 {sum(r.get('calls',0) for r in recs)}")
