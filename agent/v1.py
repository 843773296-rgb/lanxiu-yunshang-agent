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

# ── 单价表(美元 / 百万 token)──────────────────────────────────────
# 一律以**官方文档**为准。这个项目在成本口径上栽过:
#   · Haiku 那次,OAuth 分支的单价写死成旧 Opus 的 $15/$75,虚高 15 倍
#   · DeepSeek 这次,原来写的 $0.55/$2.19 三方都对不上 ——
#     博客聚合站说 $0.435/$0.87,官方文档说 $0.66/$1.98。以官方为准。
#
# ⚠️ DeepSeek 有**分时定价**:周一至周五 UTC 01:00-04:00 与 06:00-10:00 为高峰,
#    单价是平峰的 2 倍;其余时段(含周末全天)平峰。下表存的是**平峰价**,
#    实际计费时按 price_now() 乘系数 —— 不算这一层,高峰时段的成本会少算一半。
#    出处:https://api-docs.deepseek.com/quick_start/pricing
DEEPSEEK_PRICE={
  "deepseek-v4-pro":              dict(inp=0.66, cache=0.022, out=1.98),
  "deepseek-v4-flash":            dict(inp=0.22, cache=0.007, out=0.66),
  "deepseek-v4-flash-vision-exp": dict(inp=0.22, cache=0.007, out=0.66),
}

def is_peak(ts=None):
    """DeepSeek 高峰时段:周一至周五 UTC 01:00-04:00 / 06:00-10:00"""
    t=time.gmtime(ts)
    if t.tm_wday>=5: return False
    return (1<=t.tm_hour<4) or (6<=t.tm_hour<10)

def price_now(pv, ts=None):
    """取当下有效单价。分时定价只有 DeepSeek 有,Anthropic 不分时段。"""
    p=pv.get("price") or {}
    if pv.get("id")=="deepseek" and is_peak(ts):
        return {k: v*2 for k, v in p.items()}
    return p

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
    """凭证来源:环境变量 → ~/.deepseek-key(600,在两个项目之外)。

    **LANXIU_PROVIDER=claude 可以强制走 Claude。** 加这个开关有两个理由:
      ① 三代横向对比要**控制变量** —— 换模型比就白比了,得能指定同一个
      ② **识图这条路只能走 Claude**(视觉输入),而顾问助手迟早要接
         「客户发张照片问这是什么形制/什么面料」
    不加开关的话,谁的 key 先被找到就用谁,这在对比实验里是致命的。
    """
    force = os.environ.get("LANXIU_PROVIDER", "").lower()
    k = None if force == "claude" else os.environ.get("DEEPSEEK_API_KEY")
    if not k and force != "claude":
        _kf=os.path.expanduser("~/.deepseek-key")
        if os.path.exists(_kf): k=open(_kf).read().strip()
    if k:
        m=os.environ.get("DEEPSEEK_MODEL","deepseek-v4-pro")
        if m not in DEEPSEEK_PRICE:
            raise SystemExit(f"没有 {m} 的官方单价。可用:{list(DEEPSEEK_PRICE)}。"
                             "拒绝用猜的单价算成本 —— 这个项目在这上面栽过两次。")
        # ⚠️ v4 系列是**推理模型**,返回里带 thinking 块,思考本身要吃掉大量输出额度。
        # 原来所有供应商共用写死的 max_tokens=2000,实测 6 次调用被 max_tokens 截断 ——
        # 截断的响应既没有 text 也没有 submit_finding,循环空着退出,评测记成「未提交」,
        # 看起来像模型能力不行,实际是配置不够。**这就是记录仪里 finish_reason 那一栏的用处。**
        return dict(id="deepseek",url="https://api.deepseek.com/anthropic/v1/messages",
            model=m, headers=["x-api-key: "+k,"anthropic-version: 2023-06-01"],
            price=DEEPSEEK_PRICE[m], max_tokens=8000)
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

def call(pv, body, retries=6, purpose="未标注", turn=None, cache=None, gen="V1"):
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
            # gen 由调用方传:V2 的工作流也走这个函数发请求,
            # 但它必须记成 V2,否则三代对照表就把它算进 V1 里了。
            try: _trace.record(gen=gen,model=pv.get("model"),purpose=purpose,price=price_now(pv),
                               latency_ms=ms,turn=turn,attempt=att,body=body,
                               cache_on=not isinstance(body.get("system"),str),
                               peak=(pv.get("id")=="deepseek" and is_peak()),**kw)
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

# 提示词的唯一源头在根目录 prompts.py。
# 这里原来是**第三份**同角色(后台人工任务助手)的提示词,只有 4 条铁律,
# 而 agentsite/sdk.py 那份有 6 条 —— 少的两条里包含「客户合并判定标准」,
# 那条是有实测的:**不给标准时模型 0/2,给了 2/2**。
# 而 V1 的评测里恰恰有合并题。于是三代对比里 V1 是**少带一条已知能加分的规矩**上的场,
# 「三代提示词本来就不同」这条限定不是脚注,它在咬人。
#
# 现在按本进程实际挂的工具装配。V1 多一个 submit_finding(交结构化结果),
# 所以它拿到的是「调 submit_finding 提交」那条,而不是 V3 的「按四段写纯文本」。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import prompts

_SYS_TASK = None
def system_task():
    global _SYS_TASK
    if _SYS_TASK is None:
        _SYS_TASK = prompts.assemble(
            "task", {t["name"] for t in _tools("task", [SUBMIT])})
    return _SYS_TASK

def run_case(pv, prompt, max_turns=12, purpose="人工任务"):
    msgs=[{"role":"user","content":prompt}]
    tools=_tools("task",[SUBMIT])
    tin=tout=tcache=0; calls=0; t0=time.time(); finding=None; traj=[]; last_text=""
    for _t in range(max_turns):
        resp=call(pv,dict(model=pv["model"],max_tokens=pv.get("max_tokens",2000),
                          system=system_task()[0],tools=tools,messages=msgs),
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
    p=price_now(pv)                    # 分时定价:高峰 ×2
    cost=(tin*p["inp"]+tcache*p["cache"]+tout*p["out"])/1_000_000
    return dict(finding=finding,text=last_text,calls=calls,input=tin,output=tout,cache=tcache,
                cost_local=round(cost,6),cost_source=pv["id"],
                seconds=round(time.time()-t0,1),trajectory=traj)

BP01="""任务类型:财务人工任务
押金单号:{ref}

这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,给出建议的处理动作,并列出支撑结论的证据。"""

BP02="""任务类型:客户合并确认
两条疑似重复的客户档案:{a} 和 {b}

请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。

**本店的合并判定标准(照此判,不要自行加严):**
· 姓名 + 生日 + 地址 三项全同 → **同一客户跨店重复建档**,建议合并
· 只有姓名相同,生日与地址不同 → **同名不同人**,不合并
· **手机号不同不是反对合并的理由** —— 换号很常见,这正是重复建档的典型成因
标准覆盖不到的情况(比如三项里只对上两项)如实说判不了,转人工。"""

BP03="""任务类型:售后判责
维修工单号:{ref}

客户报修,需要判定责任归属并给出处理方式。请查清现场,给出判责结论、处理动作和依据。

**判定表在知识库里,先查再判**(kb_tables 的「售后争议判定」,以及 09-养护与售后.md 第五节):
· 工艺瑕疵(脱线 / 开线 / 绣面脱落 / 拉链损坏) → **我方,免费返修**
· 尺寸偏差 + 量体记录完整且相符 → 客方,收费改
· 尺寸偏差 + 量体记录缺失或不全 → 我方,免费改
· **远程量体**偏差 → 按合同分担(优先于上面两条)
· 特性类(起球 / 色差 / 掉色 / 勾丝)**且已书面告知** → 无责,解释 + 提供保养服务
· 特性类**但未**书面告知 → **我方,让步处理**

两条硬规矩:
1. 「有没有书面告知」看现场里的「交付告知签收」—— **为 null 就是没有告知**,不要当成有。
2. **你只出草稿,不对客户承诺任何金额或返修结果** —— 涉及退换赔付,结论必须由人确认。
归不到上面任何一类就如实说判不了,转人工。"""

def one(task_id):
    """被后台页面调用:跑单个任务,最后一行输出 JSON。"""
    t=[x for x in backend.list_tasks(None,"待处理") if x["id"]==task_id]
    if not t: print(json.dumps({"error":"任务不存在"},ensure_ascii=False)); return
    t=t[0]
    if t["type"]=="售后判责": prompt=BP03.format(ref=t["ref_id"])
    elif t["type"]=="财务人工任务": prompt=BP01.format(ref=t["ref_id"])
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
        if t["type"]=="售后判责":
            prompt=BP03.format(ref=t["ref_id"]); case=t["ref_id"]
        elif t["type"]=="财务人工任务":
            prompt=BP01.format(ref=t["ref_id"]); case=t["ref_id"]
        else:
            a,b=t["ref_id"].split("|"); prompt=BP02.format(a=a,b=b); case=t["id"][1:]
        try: r=run_case(pv,prompt)
        except Exception as e: r=dict(finding=None,error=str(e)[:200]); print(f"[{i}] {case} 失败: {e}")
        r.update(case=case,bp={"财务人工任务":"BP-01","客户合并确认":"BP-02",
                              "售后判责":"BP-03"}.get(t["type"],"BP-02"))
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
