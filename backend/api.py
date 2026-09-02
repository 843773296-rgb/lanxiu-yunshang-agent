#!/usr/bin/env python3
"""只读数据接口 —— 这就是 agent 的工具层。

铁律:truth 表绝不通过任何接口暴露。评测比对在 agent 之外做。
"""
import sqlite3, os, json
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),"lanxiu.db")
def _c():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def _rows(sql,*a):
    with _c() as c: return [dict(r) for r in c.execute(sql,a)]

def list_tasks(task_type=None, status="待处理"):
    """列出人工任务。type: 财务人工任务 / 客户合并确认"""
    if task_type: return _rows("SELECT * FROM task WHERE type=? AND status=?",task_type,status)
    return _rows("SELECT * FROM task WHERE status=?",status)

def get_deposit(deposit_id):
    """押金单:金额、状态、幂等号、关联预约"""
    r=_rows("SELECT * FROM deposit WHERE id=?",deposit_id)
    return r[0] if r else {"error":f"押金单 {deposit_id} 不存在"}

def get_refund_trace(deposit_id):
    """退款尝试轨迹:每次重试的时间、渠道、请求金额、返回码、幂等号"""
    r=_rows("SELECT attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key FROM refund_trace WHERE deposit_id=? ORDER BY attempt",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无退款轨迹"}

def get_payment_flow(deposit_id):
    """支付流水:in=收款 out=退款,含渠道流水号与最终状态"""
    r=_rows("SELECT id,direction,amount,channel,channel_serial,status,ts FROM payment_flow WHERE deposit_id=?",deposit_id)
    return r if r else {"error":f"押金单 {deposit_id} 无支付流水"}

def get_customer(customer_id):
    """客户档案。敏感字段按后台规则脱敏:手机号中间四位、地址门牌号"""
    r=_rows("SELECT * FROM customer WHERE id=?",customer_id)
    if not r: return {"error":f"客户 {customer_id} 不存在"}
    d=r[0]
    p=d.get("phone") or ""
    d["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    return d

TOOLS={"list_tasks":list_tasks,"get_deposit":get_deposit,"get_refund_trace":get_refund_trace,
       "get_payment_flow":get_payment_flow,"get_customer":get_customer}

SCHEMAS=[
 {"name":"list_tasks","description":"列出待处理的人工任务。task_type 可选:财务人工任务、客户合并确认",
  "input_schema":{"type":"object","properties":{"task_type":{"type":"string"}},"required":[]}},
 {"name":"get_deposit","description":"读取押金单:金额、当前状态、幂等号、关联预约号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_refund_trace","description":"读取退款尝试轨迹,含每次重试的返回码、请求金额和幂等号",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_payment_flow","description":"读取支付流水,direction=in 为收款,out 为退款,含渠道流水号与最终状态",
  "input_schema":{"type":"object","properties":{"deposit_id":{"type":"string"}},"required":["deposit_id"]}},
 {"name":"get_customer","description":"读取客户档案(手机号与地址已脱敏)",
  "input_schema":{"type":"object","properties":{"customer_id":{"type":"string"}},"required":["customer_id"]}},
]

# ── 工艺知识库工具(只读)──────────────────────────────────────────
def kb_lookup(keyword=None, cat=None, src=None):
    """按关键词/分类/来源等级查工艺知识。cat: 形制/材质/工艺/配饰;src: public/scale/demo"""
    rs=_rows("SELECT code,name,cat,alias,brief,fit,lead_days,cost_level,src_type,src_url FROM craft ORDER BY code")
    if cat: rs=[r for r in rs if r["cat"]==cat]
    if src: rs=[r for r in rs if r["src_type"]==src]
    if keyword:
        k=keyword.strip()
        rs=[r for r in rs if any(k in str(r.get(f) or "") for f in ("name","alias","brief","fit","code"))]
    if not rs: return {"hit":0,"note":f"知识库里查不到「{keyword or cat or src}」,不要凭印象回答"}
    return {"hit":len(rs),"rows":rs[:12]}

def kb_detail(code):
    """按编码取某一条的完整内容"""
    r=_rows("SELECT * FROM craft WHERE code=?",code)
    if not r: return {"error":f"没有编码 {code} 这一条"}
    return r[0]

def _resolve(x, cat):
    """把「云锦」「MT02」都解析成同一条。模型不知道编码,让它猜编码是工具设计的错误 ——
    实测过:它会拿着猜错的编码得到一个关于完全不同组合的答案,然后自信地讲出来。"""
    x=(x or "").strip()
    if not x: return None,"空值"
    r=_rows("SELECT code,name,cat FROM craft WHERE code=? AND cat=?",x.upper(),cat)
    if r: return r[0],None
    r=_rows("SELECT code,name,cat FROM craft WHERE cat=? AND (name=? OR alias=?)",cat,x,x)
    if r: return r[0],None
    r=[q for q in _rows("SELECT code,name,alias,cat FROM craft WHERE cat=?",cat)
       if x in (q["name"] or "") or x in (q["alias"] or "") or (q["name"] or "") in x]
    if len(r)==1: return r[0],None
    if len(r)>1:
        return None,f"「{x}」在{cat}里对应多条:{[q['name'] for q in r]},请用更精确的名称或编码"
    names=[q["name"] for q in _rows("SELECT name FROM craft WHERE cat=?",cat)]
    return None,f"知识库里没有叫「{x}」的{cat}。现有{cat}:{names}"

def kb_combo(craft, material):
    """查某工艺能不能用在某面料上。工艺名/面料名或编码都接受。返回 可/需评估/不可/未定义。"""
    k,e1=_resolve(craft,"工艺")
    m,e2=_resolve(material,"材质")
    if e1: return {"error":e1}
    if e2: return {"error":e2}
    craft_code, material_code = k["code"], m["code"]
    r=_rows("SELECT verdict,reason,src_type FROM craft_combo WHERE craft=? AND material=?",
            craft_code,material_code)
    if not r:
        return {"craft":k["name"],"material":m["name"],
                "resolved":f"{k['code']} {k['name']} × {m['code']} {m['name']}","verdict":"未定义",
                "note":"这一格组合约束尚未录入。**必须如实告知查不到,并建议转工艺负责人确认**,"
                       "不得自行推断可或不可。","src_type":None}
    d=r[0]; d.update(craft=k["name"],material=m["name"],
                     resolved=f"{k['code']} {k['name']} × {m['code']} {m['name']}")
    return d

def kb_tables(topic=None):
    """决策表 —— 「客户说 X 该推什么」这类问题的答案在这里,不在条目里。"""
    rs=_rows("SELECT * FROM kb_table ORDER BY topic")
    if topic: rs=[r for r in rs if topic in r["topic"]]
    if not rs:
        return {"hit":0,"available":[r["topic"] for r in _rows("SELECT topic FROM kb_table")],
                "note":"没有这个主题的决策表,看 available 里有哪些"}
    out=[]
    for r in rs:
        out.append(dict(topic=r["topic"], head=json.loads(r["head"]),
                        rows=json.loads(r["rows"]), src=r["src_file"], src_type="demo"))
    return {"hit":len(out),"tables":out}

def kb_coverage():
    """相容矩阵的完成度 —— 让「没有数据」成为一个看得见的状态"""
    ks=_rows("SELECT code FROM craft WHERE cat='工艺'"); ms=_rows("SELECT code FROM craft WHERE cat='材质'")
    n=_rows("SELECT COUNT(*) c FROM craft_combo")[0]["c"]
    tot=len(ks)*len(ms)
    return {"工艺数":len(ks),"材质数":len(ms),"总格数":tot,"已定义":n,"未定义":tot-n,
            "完成度":f"{n/tot*100:.0f}%",
            "note":"未定义的格子占大多数。遇到未定义必须说查不到,不要推断。"}


TOOLS.update({"kb_lookup":kb_lookup,"kb_detail":kb_detail,"kb_tables":kb_tables,
              "kb_combo":kb_combo,"kb_coverage":kb_coverage})
KB_SCHEMAS=[
 {"name":"kb_lookup","description":"按关键词查工艺知识库。也可按分类(形制/材质/工艺/配饰)或来源等级(public/scale/demo)筛选。查不到会明确返回 hit=0。",
  "input_schema":{"type":"object","properties":{
    "keyword":{"type":"string","description":"关键词,如「香云纱」「盘金」「金线」"},
    "cat":{"type":"string","enum":["形制","材质","工艺","配饰"]},
    "src":{"type":"string","enum":["public","scale","demo"]}},"required":[]}},
 {"name":"kb_detail","description":"按编码取一条知识的完整内容(含出处链接)。编码形如 KF01 / MT01 / XZ01 / PS01。",
  "input_schema":{"type":"object","properties":{"code":{"type":"string"}},"required":["code"]}},
 {"name":"kb_combo","description":"查某工艺能否用于某面料。**工艺名和面料名直接写中文即可**(如「妆花」「云锦」),不必也不要猜编码 —— 名字对不上会明确报错并列出现有选项。返回「可/需评估/不可」及理由;该组合未录入时返回「未定义」;返回里的 resolved 字段是实际解析到的那一对,回答前请核对它和用户问的是不是同一对。",
  "input_schema":{"type":"object","properties":{
    "craft":{"type":"string","description":"工艺名称或编码,如「妆花」或 KF02。**直接写名称即可,不要猜编码。**"},
    "material":{"type":"string","description":"面料名称或编码,如「云锦」或 MT02。**直接写名称即可,不要猜编码。**"}},
   "required":["craft","material"]}},
 {"name":"kb_tables","description":"取全部决策表(6 张共 30 行:客户原话对照、选料决策、配饰形制搭配、配色易错、工期档位、售后争议判定)。顾问问「客户说了 X,我该推什么/避开什么/怎么处理」这类问题时**优先用这个**,而不是 kb_lookup。**直接不带参数调用即可**,取全部比挑一张更可靠。",
  "input_schema":{"type":"object","properties":{"topic":{"type":"string","description":"通常不要传。全部决策表合计只有 30 行,一次全取更可靠 —— 传了 topic 反而容易取错表。"}},"required":[]}},
 {"name":"kb_coverage","description":"查相容矩阵的完成度(共多少格、已定义多少、未定义多少)。",
  "input_schema":{"type":"object","properties":{},"required":[]}},
]
