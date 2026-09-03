#!/usr/bin/env python3
"""澜绣云裳管理后台 · 本地服务。数据全部来自 lanxiu.db,页面结构对齐 Figma 18 个页面。"""
import json, os, sqlite3, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api as backend
import fsm, rules

HERE=os.path.dirname(os.path.abspath(__file__))

def scheme_list():
    """已有方案清单。写成模块级函数而不是在路由里直接查 ——
    do_GET 内部有个局部变量也叫 rows,会把模块级的 rows() 函数整段遮蔽掉。"""
    return dict(rows=rows("SELECT * FROM scheme ORDER BY updated DESC"))

def scheme_status(sid):
    r=rows("SELECT status FROM scheme WHERE id=?",sid)
    return r[0]["status"] if r else None

def _now():
    import time as _t; return _t.strftime("%Y-%m-%d %H:%M")

def _agent():
    sys.path.insert(0, os.path.join(HERE,"..","agent")); import v1; return v1
def _eval():
    sys.path.insert(0, os.path.join(HERE,"..","agent")); import eval as _e; return _e
def _truths():
    """只在跑完之后判分时读 —— 绝不进模型上下文。"""
    return _eval().truths()
DB=os.path.join(HERE,"lanxiu.db")
DRAFTS=os.path.join(HERE,"drafts.json")

def rows(sql,*a):
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    try: return [dict(r) for r in c.execute(sql,a)]
    finally: c.close()

def load_drafts():
    try: return json.load(open(DRAFTS))
    except Exception: return {}
def save_drafts(d): json.dump(d,open(DRAFTS,"w"),ensure_ascii=False,indent=1)

def workbench():
    fin=rows("SELECT * FROM task WHERE type='财务人工任务' ORDER BY id")
    mrg=rows("SELECT * FROM task WHERE type='客户合并确认' ORDER BY id")
    dr=load_drafts()
    amt=rows("SELECT SUM(amount) s FROM deposit WHERE status IN ('退款失败','退款审批中')")[0]["s"] or 0
    fail=rows("SELECT COUNT(*) c FROM deposit WHERE status='退款失败'")[0]["c"]
    appr=rows("SELECT COUNT(*) c FROM deposit WHERE status='退款审批中'")[0]["c"]
    retry=rows("SELECT AVG(n) a FROM (SELECT COUNT(*) n FROM refund_trace GROUP BY deposit_id)")[0]["a"] or 0
    adopted=sum(1 for v in dr.values() if v.get("status","").find("采纳")>=0)
    rate="—" if not dr else f"{adopted*100//len(dr)}%"

    trend=rows("""SELECT substr(ts,1,10) d, COUNT(*) n, SUM(req_amount) amt
                  FROM refund_trace GROUP BY d ORDER BY d""")
    codes=rows("""SELECT resp_code c, COUNT(*) n, SUM(req_amount) amt
                  FROM refund_trace GROUP BY c ORDER BY amt DESC""")
    lifec=rows("SELECT lifecycle l, COUNT(*) n FROM customer GROUP BY l ORDER BY n DESC")
    def dod(k):
        if len(trend)<2 or not trend[-2][k]: return None
        return round((trend[-1][k]-trend[-2][k])/trend[-2][k]*100,1)

    shops=rows("""SELECT shop, COUNT(*) cust, SUM(order_cnt) orders, SUM(paid_amount) amt
                  FROM customer WHERE shop!='' GROUP BY shop ORDER BY shop""")
    for sh in shops:
        sh["deposit"]=rows("""SELECT COUNT(*) c FROM deposit d JOIN customer c2
                              ON d.customer_id=c2.id WHERE c2.shop=?""",sh["shop"])[0]["c"]
        sh["open"]= sh["shop"]!="SH003 杭州湖滨店"

    return dict(
      trend=trend, codes=codes, lifecycle=lifec, dod=dict(n=dod("n"),amt=dod("amt")),
      shops=shops, finance=fin, merge=mrg,
      appt=dict(total=rows("SELECT COUNT(*) c FROM appointment")[0]["c"],
                **{k:rows("SELECT COUNT(*) c FROM appointment WHERE status=?",v)[0]["c"]
                   for k,v in [("booked","已预约"),("arrived","已到店"),("noshow","爽约")]}),
      oplog=dict(**{k:rows("SELECT COUNT(*) c FROM op_log WHERE allowed=?",v)[0]["c"]
                    for k,v in [("allow",1),("deny",0)]}),
      drafts={k:v.get("status") for k,v in dr.items()},
      metrics=[
        dict(label="退款尝试(当日)",value=str(trend[-1]["n"] if trend else 0),unit="次",trend=dod("n")),
        dict(label="涉及金额(当日)",value=f"{(trend[-1]['amt'] if trend else 0):,.2f}",unit="元",trend=dod("amt")),
        dict(label="财务人工任务",value=str(len(fin)),unit="件",sub="退款连续失败转人工"),
        dict(label="客户合并确认",value=str(len(mrg)),unit="对",sub="疑似重复待核验"),
      ],
      metrics2=[
        dict(label="待退金额",value=f"{amt:,.2f}",unit="元",sub="失败与审批中合计"),
        dict(label="退款失败",value=str(fail),unit="笔",sub="已达重试上限"),
        dict(label="平均重试次数",value=f"{retry:.1f}",unit="次",sub="上限 3 次"),
        dict(label="客户档案",value=str(rows("SELECT COUNT(*) c FROM customer")[0]["c"]),unit="人",sub="含疑似重复档案"),
      ])

def task_detail(tid):
    t=rows("SELECT * FROM task WHERE id=?",tid)
    if not t: return {"error":"任务不存在"}
    t=t[0]; d=load_drafts().get(tid)
    if t["type"]=="财务人工任务":
        dep=t["ref_id"]
        return dict(task=t,kind="refund",deposit=backend.get_deposit(dep),
            trace=backend.get_refund_trace(dep),flow=backend.get_payment_flow(dep),
            customer=backend.get_customer(backend.get_deposit(dep).get("customer_id","")),draft=d)
    a,b=t["ref_id"].split("|")
    ca,cb=backend.get_customer(a),backend.get_customer(b)
    fields=[("姓名","name"),("手机号","phone"),("归属门店","shop"),("归属顾问","advisor"),
            ("生日","birthday"),("地址","addr"),("建档日期","created"),("订单数","order_cnt"),
            ("累计实付","paid_amount"),("生命周期","lifecycle"),("会员等级","level"),("最近互动","last_interact")]
    cmp=[dict(label=l,a=ca.get(k),b=cb.get(k),same=(ca.get(k)==cb.get(k))) for l,k in fields]
    st=t["status"] if t["status"]!="待处理" else "待核验"
    return dict(task=t,kind="merge",a=ca,b=cb,compare=cmp,draft=d,merge_status=st)

def gen_draft(tid):
    """调用 V1 agent 生成草稿。失败时如实返回错误,不伪造结果。"""
    t=rows("SELECT * FROM task WHERE id=?",tid)
    if not t: return {"error":"任务不存在"}
    t=t[0]
    r=subprocess.run([sys.executable,os.path.join(HERE,"..","agent","v1.py"),"one",tid],
                     capture_output=True,text=True,cwd=HERE)
    try: out=json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": (r.stderr or r.stdout or "agent 无输出")[-400:]}
    if not out.get("finding"): return {"error": out.get("error","agent 未提交结论")}
    d=load_drafts(); out["status"]="待采纳"; d[tid]=out; save_drafts(d)
    return out

def set_draft_status(tid,status,note=""):
    d=load_drafts()
    if tid not in d: return {"error":"草稿不存在"}
    d[tid]["status"]=status; d[tid]["note"]=note; save_drafts(d)
    return d[tid]

def ensure_oplog():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS op_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, machine TEXT,
          target TEXT, frm TEXT, too TEXT, allowed INT, code TEXT, reason TEXT, ctx TEXT)""")
ensure_oplog()

def log_op(actor,mid,target,frm,to,ok,code,reason,ctx):
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO op_log(ts,actor,machine,target,frm,too,allowed,code,reason,ctx)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?,?,?)",
                  (actor,mid,target,frm,to,1 if ok else 0,code,reason,json.dumps(ctx,ensure_ascii=False)))

def transit(mid, target, to, ctx, actor="魏欣新"):
    """统一入口:先过引擎,允许才落库,拒绝也留痕。"""
    if mid=="bk-deposit":
        r=rows("SELECT * FROM deposit WHERE id=?",target)
        if not r: return {"error":"押金单不存在"}
        cur=r[0]["status"]; ctx.setdefault("amount",r[0]["amount"])
        ctx.setdefault("retries",rows("SELECT COUNT(*) n FROM refund_trace WHERE deposit_id=?",target)[0]["n"])
    elif mid=="bk-activity":
        r=rows("SELECT * FROM activity WHERE code=?",target)
        if not r: return {"error":"活动不存在"}
        cur=r[0]["status"]
    elif mid=="bk-page":
        r=rows("SELECT * FROM page WHERE code=?",target)
        if not r: return {"error":"页面不存在"}
        cur=r[0]["status"]
    elif mid=="bk-download":
        r=rows("SELECT * FROM download_task WHERE id=?",target)
        if not r: return {"error":"任务不存在"}
        cur=r[0]["status"]
    elif mid=="bk-product":
        r=rows("SELECT * FROM product WHERE spu=?",target)
        if not r: return {"error":"商品不存在"}
        cur=r[0]["status"]
    elif mid=="bk-shop":
        r=rows("SELECT * FROM shop WHERE code=?",target)
        if not r: return {"error":"店铺不存在"}
        cur=r[0]["status"]
    elif mid=="bk-task":
        r=rows("SELECT * FROM schedule WHERE id=?",target)
        if not r: return {"error":"日程任务不存在"}
        cur=r[0]["status"]
    elif mid=="bk-appt":
        r=rows("SELECT * FROM appointment WHERE id=?",target)
        if not r: return {"error":"预约不存在"}
        cur=r[0]["status"]
    elif mid=="fe-scheme":
        r=rows("SELECT * FROM scheme WHERE id=?",target)
        if not r: return {"error":"定制方案不存在"}
        cur=r[0]["status"]
    else:
        return {"error":f"暂不支持 {mid}"}

    ok,code,why=fsm.check(mid,cur,to,ctx)
    log_op(actor,mid,target,cur,to,ok,code,why,ctx)
    if not ok: return dict(ok=False,code=code,reason=why,frm=cur,to=to)

    tbl={"bk-deposit":"deposit","bk-appt":"appointment","bk-shop":"shop","bk-task":"schedule",
         "bk-product":"product","bk-activity":"activity","bk-page":"page","bk-download":"download_task",
         "fe-scheme":"scheme"}[mid]
    key={"bk-shop":"code","bk-product":"spu","bk-activity":"code","bk-page":"code"}.get(mid,"id")
    with sqlite3.connect(DB) as c:
        c.execute(f"UPDATE {tbl} SET status=? WHERE {key}=?",(to,target))
        if mid=="bk-task" and to=="完结":
            c.execute("UPDATE schedule SET summary=? WHERE id=?",(ctx.get("summary") or "",target))
        if mid=="bk-task" and to=="取消":
            c.execute("UPDATE schedule SET cancel_reason=? WHERE id=?",(ctx.get("reason") or "",target))
        if mid=="bk-deposit" and to=="退款处理中":
            c.execute("""INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,
                         resp_code,resp_msg,idem_key)
                         SELECT ?,COALESCE(MAX(attempt),0)+1,datetime('now','localtime'),'微信支付',
                         (SELECT amount FROM deposit WHERE id=?),'PENDING','处理中',?
                         FROM refund_trace WHERE deposit_id=?""",(target,target,ctx.get("idem_key"),target))
    return dict(ok=True,code="OK",frm=cur,to=to,reason=f"已从「{cur}」流转到「{to}」")

def adjust_lifecycle(cid,to,reason,actor="魏欣新"):
    r=rows("SELECT lifecycle,matched FROM customer WHERE id=?",cid)
    if not r: return {"error":"客户不存在"}
    cur=r[0]["lifecycle"]
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE customer SET lifecycle=?,manual_lc=?,manual_at=date('now','localtime') WHERE id=?",
                  (to,to,cid))
    log_op(actor,"bk-lifecycle",cid,cur,to,True,"MANUAL",
           f"人工调整,30 天内优先。原因:{reason or '未填写'}",{"reason":reason})
    return dict(ok=True,frm=cur,to=to,reason="人工调整已生效,30 天内优先于每日重算")

def close_task(tid,result,note,actor="魏欣新"):
    r=rows("SELECT * FROM task WHERE id=?",tid)
    if not r: return {"error":"任务不存在"}
    if r[0]["status"]!="待处理":
        log_op(actor,"task",tid,r[0]["status"],result,False,"TERMINAL",
               f"任务已是「{r[0]['status']}」,不可重复关闭",{})
        return dict(ok=False,code="TERMINAL",reason=f"任务已是「{r[0]['status']}」,不可重复关闭")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE task SET status=?,summary=? WHERE id=?",(result,note,tid))
    log_op(actor,"task",tid,"待处理",result,True,"CLOSE",note or "",{})
    return dict(ok=True,code="CLOSE",reason=f"任务已关闭:{result}")

def merge_transit(tid, to, note, actor="魏欣新", role="顾问"):
    """客户合并流转:店长发起 → 总部运营审批。规则见后台 PRD 6.2。"""
    t=rows("SELECT * FROM task WHERE id=?",tid)
    if not t: return {"error":"任务不存在"}
    t=t[0]; cur=t["status"]
    if cur=="待处理": cur="待核验"
    ok,code,why=fsm.check("bk-merge",cur,to,{"role":role})
    log_op(actor,"bk-merge",t["ref_id"],cur,to,ok,code,why or (note or ""),{"role":role})
    if not ok: return dict(ok=False,code=code,reason=why)

    a,b=t["ref_id"].split("|")
    if to=="已合并":
        ra=rows("SELECT * FROM customer WHERE id=?",a)[0]
        rb=rows("SELECT * FROM customer WHERE id=?",b)[0]
        # PRD:保留最早客户编号
        main,dup=(ra,rb) if (ra["created"] or "") <= (rb["created"] or "") else (rb,ra)
        # PRD:冲突字段采用最近一次经确认的数据
        fresh = ra if (ra["last_interact"] or "") >= (rb["last_interact"] or "") else rb
        conflicts=[]
        for f in ("phone","addr","shop","advisor","level"):
            if ra[f]!=rb[f]: conflicts.append(f"{f}: 取自 {fresh['id']}")
        with sqlite3.connect(DB) as c:
            # 合并标签、量体、跟进、预约、购买记录 → 关联迁移到主档
            c.execute("UPDATE appointment SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            c.execute("UPDATE followup    SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            c.execute("UPDATE deposit     SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            # 冲突字段取最近确认的数据
            c.execute("""UPDATE customer SET phone=?,addr=?,shop=?,advisor=?,level=?,
                         last_interact=? WHERE id=?""",
                      (fresh["phone"],fresh["addr"],fresh["shop"],fresh["advisor"],fresh["level"],
                       fresh["last_interact"],main["id"]))
            # PRD:订单、积分和支付只建立关联,不重复累计 —— 故不做 order_cnt / paid_amount 相加
            c.execute("UPDATE customer SET archived=1 WHERE id=?",(dup["id"],))
            c.execute("UPDATE task SET status=?,summary=? WHERE id=?",
                      ("已合并",f"主档 {main['id']} 保留(建档最早);{dup['id']} 归档。"
                       f"冲突字段取自 {fresh['id']}。订单与积分仅建立关联,不重复累计。{note or ''}",tid))
        log_op(actor,"customer",f"{main['id']}<-{dup['id']}","独立","已合并",True,"MERGE_DONE",
               f"保留最早编号 {main['id']};冲突字段 {len(conflicts)} 项取自 {fresh['id']};"
               f"订单/积分只关联不累计",{"conflicts":conflicts})
        return dict(ok=True,code="MERGED",
          reason=f"已合并:保留 {main['id']}(建档最早),{dup['id']} 转归档;"
                 f"冲突字段 {len(conflicts)} 项取自 {fresh['id']};订单与积分仅建立关联,未累计")
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE task SET status=?,summary=? WHERE id=?",(to,note or "",tid))
    MSG={"待总部审批":"已提交总部运营审批","已核验":"已标记为非同一人,不再进入待核验队列",
         "已驳回":"总部运营已驳回,退回店长重新核验"}
    return dict(ok=True,code=to,reason=MSG.get(to,f"状态已更新为「{to}」"))

def shop_list(q):
    kw=(q.get("q") or [""])[0].strip(); stt=(q.get("status") or [""])[0]
    rs=rows("SELECT * FROM shop ORDER BY code")
    for r in rs:
        r["cust"]=rows("SELECT COUNT(*) c FROM customer WHERE shop LIKE ?",f"{r['code']}%")[0]["c"]
        r["staff"]=rows("SELECT COUNT(*) c FROM staff WHERE shop LIKE ?",f"{r['code']}%")[0]["c"]
    if kw: rs=[r for r in rs if kw in r["name"] or kw in r["code"]]
    if stt: rs=[r for r in rs if r["status"]==stt]
    d=_page(rs,q); d["facets"]=dict(status=["有效","无效"]); return d

def shop_detail(code):
    r=rows("SELECT * FROM shop WHERE code=?",code)
    if not r: return {"error":"店铺不存在"}
    s=r[0]
    s["staff"]=rows("SELECT * FROM staff WHERE shop LIKE ? ORDER BY role,no",f"{code}%")
    s["cust"]=rows("SELECT COUNT(*) c FROM customer WHERE shop LIKE ?",f"{code}%")[0]["c"]
    s["appt"]=rows("SELECT COUNT(*) c FROM appointment WHERE shop LIKE ?",f"{code}%")[0]["c"]
    s["logs"]=rows("SELECT * FROM op_log WHERE target=? ORDER BY id DESC LIMIT 20",code)
    return s

def staff_list(q):
    kw=(q.get("q") or [""])[0].strip()
    ro=(q.get("role") or [""])[0]
    rs=rows("SELECT * FROM staff ORDER BY no")
    if kw: rs=[r for r in rs if kw in r["no"] or kw in r["name"]]
    if ro: rs=[r for r in rs if r["role"]==ro]
    d=_page(rs,q)
    d["facets"]=dict(role=[r["v"] for r in rows("SELECT DISTINCT role v FROM staff ORDER BY v")])
    # PRD 第 8 章:角色 → 可执行操作的映射
    d["matrix"]={"顾问":["查看本人客户","新建跟进","新建预约"],
                 "店长":["顾问全部权限","客户转移","退款复核","补录 7 天内记录","发起客户合并"],
                 "财务":["退款财务复核(单笔≥1000元)","对账"],
                 "总部运营":["店长全部权限","审批客户合并","等级与积分人工调整","批量导出审批"]}
    return d

def schedule_list(q):
    kw=(q.get("q") or [""])[0].strip()
    stt=(q.get("status") or [""])[0]; ty=(q.get("type") or [""])[0]
    rs=rows("""SELECT s.*, c.name cname FROM schedule s
               LEFT JOIN customer c ON s.customer_id=c.id ORDER BY s.start_ts DESC""")
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["cname"] or "")]
    if stt: rs=[r for r in rs if r["status"]==stt]
    if ty:  rs=[r for r in rs if r["type"]==ty]
    d=_page(rs,q)
    d["facets"]=dict(status=["有效","完结","取消","无效"],
                     type=[r["v"] for r in rows("SELECT DISTINCT type v FROM schedule ORDER BY v")])
    return d

# 设计稿的 10 个状态页签 vs 前端 PRD 11.1 的 6 个状态 —— 差集 D 实例
DESIGN_TABS=["全部","待付款","待审核","待生产","生产中","已生产","待发货","已发货","待完成","完成","取消"]
TAB_MAP={"全部":None,"待付款":"待付款","待发货":"待发货","已发货":"待收货",
         "完成":"已完成","取消":"已关闭"}   # 其余 4 个页签在 PRD 中无对应状态

def order_list(q):
    kw=(q.get("q") or [""])[0].strip()
    tab=(q.get("tab") or ["全部"])[0]
    kind=(q.get("kind") or [""])[0]; src=(q.get("source") or [""])[0]
    rs=rows("""SELECT o.*, c.name cname FROM ordr o LEFT JOIN customer c
               ON o.customer_id=c.id ORDER BY o.created DESC""")
    for r in rs:
        r["items"]=rows("SELECT sku,name,tag,price,qty FROM ordr_item WHERE order_id=?",r["id"])
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["cname"] or "")]
    if kind: rs=[r for r in rs if r["kind"]==kind]
    if src:  rs=[r for r in rs if r["source"]==src]
    mapped=TAB_MAP.get(tab,"__NONE__")
    unmapped = tab!="全部" and tab not in TAB_MAP
    if mapped: rs=[r for r in rs if r["status"]==mapped]
    elif unmapped: rs=[]
    d=_page(rs,q)
    d["tabs"]=[dict(name=t,mapped=(t in TAB_MAP),
                    prd=TAB_MAP.get(t) or ("全部" if t=="全部" else None)) for t in DESIGN_TABS]
    d["tab"]=tab; d["unmapped"]=unmapped
    d["facets"]=dict(kind=[r["v"] for r in rows("SELECT DISTINCT kind v FROM ordr")],
                     source=[r["v"] for r in rows("SELECT DISTINCT source v FROM ordr ORDER BY v")])
    d["prd_states"]=["待付款","方案确认中","待发货","待收货","已完成","已关闭"]
    d["counts"]={s:rows("SELECT COUNT(*) c FROM ordr WHERE status=?",s)[0]["c"] for s in d["prd_states"]}
    return d

def product_list(q):
    kw=(q.get("q") or [""])[0].strip()
    f={k:(q.get(k) or [""])[0] for k in ("kind","status","category")}
    rs=rows("""SELECT p.*, c.name cat_name FROM product p
               LEFT JOIN category c ON p.category=c.code ORDER BY p.spu""")
    for r in rs:
        sk=rows("SELECT stock,locked,status FROM sku WHERE spu=?",r["spu"])
        r["sku_n"]=len(sk); r["stock"]=sum(x["stock"] for x in sk)
        r["locked"]=sum(x["locked"] for x in sk)
        r["avail"]=r["stock"]-r["locked"]
        r["sold"]=rows("SELECT COUNT(*) c FROM ordr_item WHERE sku=?",r["spu"])[0]["c"]
    if kw: rs=[r for r in rs if kw in r["spu"] or kw in r["name"]]
    for k,v in f.items():
        if v: rs=[r for r in rs if r.get(k if k!="category" else "category")==v]
    rs=_sort(rs,q,{"spu","name","base_price","stock","avail","updated"})
    d=_page(rs,q)
    d["facets"]=dict(kind=["标品","定制品"],status=["已上架","已下架"],
      category=[r["code"] for r in rows("SELECT code FROM category WHERE parent IS NOT NULL ORDER BY code")])
    d["catnames"]={r["code"]:r["name"] for r in rows("SELECT code,name FROM category")}
    return d

def product_detail(spu):
    r=rows("""SELECT p.*, c.name cat_name FROM product p
              LEFT JOIN category c ON p.category=c.code WHERE p.spu=?""",spu)
    if not r: return {"error":"商品不存在"}
    p=r[0]
    p["skus"]=rows("SELECT * FROM sku WHERE spu=? ORDER BY code",spu)
    p["orders"]=rows("""SELECT o.id,o.status,o.created,o.amount FROM ordr o
                        JOIN ordr_item i ON i.order_id=o.id WHERE i.sku=?
                        ORDER BY o.created DESC LIMIT 10""",spu)
    p["logs"]=rows("SELECT * FROM op_log WHERE target=? ORDER BY id DESC LIMIT 20",spu)
    return p

def category_tree():
    all_=rows("SELECT * FROM category ORDER BY sort")
    top=[c for c in all_ if not c["parent"]]
    for t in top:
        t["children"]=[c for c in all_ if c["parent"]==t["code"]]
        for ch in t["children"]:
            ch["n"]=rows("SELECT COUNT(*) c FROM product WHERE category=?",ch["code"])[0]["c"]
        t["n"]=sum(ch["n"] for ch in t["children"])
    return top

def stock_list(q):
    kw=(q.get("q") or [""])[0].strip()
    low=(q.get("low") or [""])[0]
    rs=rows("""SELECT s.*, p.name pname, p.kind FROM sku s
               JOIN product p ON s.spu=p.spu ORDER BY s.code""")
    for r in rs: r["avail"]=r["stock"]-r["locked"]
    if kw: rs=[r for r in rs if kw in r["code"] or kw in r["pname"]]
    if low=="是": rs=[r for r in rs if r["avail"]<=5]
    rs=_sort(rs,q,{"code","stock","avail","price"})
    d=_page(rs,q); d["facets"]=dict(low=["是","否"])
    d["alert"]=len([r for r in rows("SELECT stock,locked FROM sku") if r["stock"]-r["locked"]<=5])
    return d

def measure_items(q):
    rs=rows("SELECT * FROM measure_item ORDER BY sort")
    for r in rs:
        r["used"]=rows("SELECT COUNT(DISTINCT tpl) c FROM tpl_item WHERE item=?",r["code"])[0]["c"]
    return dict(rows=rs,total=len(rs))

def measure_tpls(q):
    kw=(q.get("q") or [""])[0].strip(); stt=(q.get("status") or [""])[0]
    rs=rows("SELECT * FROM measure_tpl ORDER BY code")
    names={r["code"]:r["name"] for r in rows("SELECT code,name FROM measure_item")}
    for r in rs:
        its=rows("SELECT item FROM tpl_item WHERE tpl=? ORDER BY sort",r["code"])
        r["items"]=[names.get(x["item"],x["item"]) for x in its]
        r["item_codes"]=[x["item"] for x in its]
        r["used"]=rows("SELECT COUNT(*) c FROM product WHERE template LIKE ?",f"{r['code']}%")[0]["c"]
        r["recs"]=rows("SELECT COUNT(DISTINCT customer_id) c FROM measure_rec WHERE tpl=?",r["code"])[0]["c"]
    if kw: rs=[r for r in rs if kw in r["name"] or kw in r["code"]]
    if stt: rs=[r for r in rs if r["status"]==stt]
    d=_page(rs,q); d["facets"]=dict(status=["启用","停用"]); return d

def measure_of(cid):
    rs=rows("""SELECT r.*, i.name iname, i.unit FROM measure_rec r
               LEFT JOIN measure_item i ON r.item=i.code
               WHERE r.customer_id=? ORDER BY r.tpl, i.sort""",cid)
    if not rs: return []
    tpls={}
    for r in rs: tpls.setdefault(r["tpl"],[]).append(r)
    names={t["code"]:t["name"] for t in rows("SELECT code,name FROM measure_tpl")}
    return [dict(tpl=k,name=names.get(k,k),at=v[0]["measured_at"],by=v[0]["measured_by"],items=v)
            for k,v in tpls.items()]

def content_list(q):
    kw=(q.get("q") or [""])[0].strip()
    f={k:(q.get(k) or [""])[0] for k in ("kind","status","channel")}
    rs=rows("SELECT * FROM content ORDER BY published DESC")
    if kw: rs=[r for r in rs if kw in r["title"] or kw in r["code"]]
    for k,v in f.items():
        if v: rs=[r for r in rs if r.get(k)==v]
    rs=_sort(rs,q,{"code","title","published","views"})
    d=_page(rs,q)
    d["facets"]=dict(kind=[r["v"] for r in rows("SELECT DISTINCT kind v FROM content ORDER BY v")],
                     status=["已发布","草稿"],
                     channel=[r["v"] for r in rows("SELECT DISTINCT channel v FROM content ORDER BY v")])
    return d

def toggle(table,key,val,col="status",on="启用",off="停用",actor="魏欣新"):
    r=rows(f"SELECT {col} s FROM {table} WHERE {key}=?",val)
    if not r: return {"error":"记录不存在"}
    cur=r[0]["s"]; to=off if cur==on else on
    with sqlite3.connect(DB) as c: c.execute(f"UPDATE {table} SET {col}=? WHERE {key}=?",(to,val))
    log_op(actor,table,val,cur,to,True,"TOGGLE",f"{table} 状态切换",{})
    return dict(ok=True,code="TOGGLE",frm=cur,to=to,reason=f"已从「{cur}」切换为「{to}」")

def _simple(table,q,key,sortable,facet_cols,order=None):
    kw=(q.get("q") or [""])[0].strip()
    rs=rows(f"SELECT * FROM {table}" + (f" ORDER BY {order}" if order else ""))
    for col in facet_cols:
        v=(q.get(col) or [""])[0]
        if v: rs=[r for r in rs if str(r.get(col))==v]
    if kw: rs=[r for r in rs if any(kw in str(r.get(k) or "") for k in key)]
    rs=_sort(rs,q,sortable)
    d=_page(rs,q)
    d["facets"]={col:[r["v"] for r in rows(f"SELECT DISTINCT {col} v FROM {table} ORDER BY v")]
                 for col in facet_cols}
    return d

def activity_list(q):
    d=_simple("activity",q,["code","name"],{"code","name","start_d","budget","signup","orders"},
              ["kind","status"],"start_d DESC")
    for r in d["rows"]:
        cs=rows("SELECT SUM(amount) s,COUNT(*) n FROM activity_cost WHERE activity=?",r["code"])[0]
        r["cost"]=cs["s"] or 0; r["cost_n"]=cs["n"]
        r["rate"]=round(r["cost"]/r["budget"]*100,1) if r["budget"] else 0
        r["codes"]=rows("SELECT COUNT(*) c FROM invite_code WHERE activity=?",r["code"])[0]["c"]
    return d

def activity_detail(code):
    r=rows("SELECT * FROM activity WHERE code=?",code)
    if not r: return {"error":"活动不存在"}
    a=r[0]
    a["costs"]=rows("SELECT * FROM activity_cost WHERE activity=? ORDER BY id",code)
    a["cost_total"]=sum(x["amount"] for x in a["costs"])
    a["rate"]=round(a["cost_total"]/a["budget"]*100,1) if a["budget"] else 0
    a["codes"]=rows("""SELECT batch,status,COUNT(*) n FROM invite_code WHERE activity=?
                       GROUP BY batch,status ORDER BY batch""",code)
    a["orders_l"]=rows("SELECT id,status,amount,created FROM ordr WHERE activity=? ORDER BY created DESC LIMIT 8",a["name"])
    a["logs"]=rows("SELECT * FROM op_log WHERE target=? ORDER BY id DESC LIMIT 10",code)
    return a

def invite_list(q):
    d=_simple("invite_code",q,["code","used_by"],{"code","batch","created"},["batch","status","activity"],"code")
    names={r["code"]:r["name"] for r in rows("SELECT code,name FROM activity")}
    for r in d["rows"]: r["act_name"]=names.get(r["activity"],r["activity"])
    d["batches"]=rows("""SELECT batch, activity, COUNT(*) n,
      SUM(status='已使用') used, SUM(status='未使用') unused, SUM(status='已作废') void
      FROM invite_code GROUP BY batch,activity ORDER BY batch""")
    for b in d["batches"]: b["act_name"]=names.get(b["activity"],b["activity"])
    return d

def page_list(q):
    d=_simple("page",q,["code","name"],{"code","name","updated"},["channel","status"],"code")
    for r in d["rows"]:
        r["blocks"]=rows("SELECT COUNT(*) c FROM page_block WHERE page=?",r["code"])[0]["c"]
    return d

def page_detail(code):
    r=rows("SELECT * FROM page WHERE code=?",code)
    if not r: return {"error":"页面不存在"}
    p=r[0]; p["blocks"]=rows("SELECT * FROM page_block WHERE page=? ORDER BY sort",code)
    return p

def syscode_list(q):
    return _simple("sys_code",q,["code","name","val"],{"code","sort"},["category","status"],"category,sort")

def download_list(q):
    return _simple("download_task",q,["id","kind"],{"id","created"},["kind","status"],"created DESC")

def create_download(kind,filters,actor="魏欣新"):
    import datetime
    n=rows("SELECT COUNT(*) c FROM download_task")[0]["c"]
    did=f"DL{datetime.datetime.now():%y%m%d}{n+1:04d}"
    cnt={"客户档案":lambda:customer_list({"per":["1"]})["total"],
         "操作日志":lambda:len(op_logs(100000)),
         "商品库":lambda:product_list({"per":["1"]})["total"],
         "交易查询":lambda:order_list({"per":["1"]})["total"]}.get(kind,lambda:0)()
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO download_task VALUES(?,?,?,?,?,?,?,?,?)",
          (did,kind,filters or "全部","已完成",cnt,max(1,cnt//8),"60000008",
           datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           (datetime.datetime.now()+datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")))
    log_op(actor,"download",did,"—","已完成",True,"EXPORT",
           f"{kind} 导出 {cnt} 行,筛选:{filters or '全部'};下载链接 24 小时后失效",{})
    return dict(ok=True,code="EXPORT",id=did,
      reason=f"导出任务 {did} 已生成({cnt} 行),可在 系统 › 下载中心 获取;链接 24 小时后失效")

def update_customer(cid,d,actor="魏欣新",role="顾问"):
    r=rows("SELECT * FROM customer WHERE id=?",cid)
    if not r: return {"error":"客户不存在"}
    old=r[0]
    ph=rules.norm_phone(d.get("phone") or old["phone"])
    if ph!=rules.norm_phone(old["phone"]):
        ex=[c for c in rows("SELECT id,name,phone,shop FROM customer") if c["id"]!=cid]
        same=[c for c in ex if rules.norm_phone(c["phone"])==ph]
        if same:
            log_op(actor,"customer",cid,"编辑","编辑",False,"DUP_PHONE",
                   f"手机号与 {same[0]['id']} 重复",d)
            return dict(ok=False,code="DUP_PHONE",
                reason=f"手机号与客户 {same[0]['id']}({same[0]['name']})重复,按 PRD 6.2 不可修改为该号")
    diff=[f"{k}: {old.get(k)} → {v}" for k,v in
          dict(name=d.get("name"),phone=ph,shop=d.get("shop"),advisor=d.get("advisor"),
               addr=d.get("addr"),birthday=d.get("birthday")).items()
          if v and str(old.get(k))!=str(v)]
    if not diff: return dict(ok=True,code="NOCHANGE",reason="没有字段发生变化")
    with sqlite3.connect(DB) as c:
        c.execute("""UPDATE customer SET name=COALESCE(?,name),phone=?,phone_tail=?,
                     shop=COALESCE(?,shop),advisor=COALESCE(?,advisor),
                     addr=COALESCE(?,addr),birthday=COALESCE(?,birthday) WHERE id=?""",
                  (d.get("name"),ph,ph[-4:],d.get("shop"),d.get("advisor"),
                   d.get("addr"),d.get("birthday"),cid))
    log_op(actor,"customer",cid,"编辑","编辑",True,"UPDATE","; ".join(diff),{"role":role})
    return dict(ok=True,code="UPDATE",reason=f"已更新 {len(diff)} 个字段:"+"; ".join(diff[:3]))

def import_customers(text,actor="魏欣新",role="顾问",dry=True):
    """批量导入。后台 PRD 6.2:结构错误整批拒绝;行级错误部分成功;重复跳过;疑似重复进人工确认。"""
    import csv, io, datetime
    if role not in ("店长","总部运营"):
        log_op(actor,"import","-","—","导入",False,"WRONG_ROLE",
               f"批量导入客户须由店长及以上操作,当前角色:{role}",{})
        return dict(ok=False,code="WRONG_ROLE",reason=f"批量导入客户须由店长及以上操作,当前角色:{role}")
    try: rd=list(csv.DictReader(io.StringIO((text or "").strip())))
    except Exception as e: return dict(ok=False,code="BAD_FILE",reason=f"文件解析失败:{e}")
    if not rd: return dict(ok=False,code="EMPTY",reason="文件为空或没有数据行")
    ok,code,why=rules.validate_import_header(list(rd[0].keys()))
    if not ok:
        log_op(actor,"import","-","—","导入",False,code,why,{})
        return dict(ok=False,code=code,reason=why)
    ex=rows("SELECT id,name,phone,shop FROM customer")
    good,skip,err,review,fatal=rules.validate_import_rows(rd,ex)
    if fatal:
        log_op(actor,"import","-","—","导入",False,fatal[0],fatal[1],{})
        return dict(ok=False,code=fatal[0],reason=fatal[1])
    batch=f"IMP{datetime.datetime.now():%y%m%d%H%M%S}"
    if not dry:
        n=rows("SELECT COUNT(*) c FROM customer")[0]["c"]
        with sqlite3.connect(DB) as c:
            for j,(ln,d) in enumerate(good):
                nid=f"C{40000+n+j}"
                c.execute("""INSERT INTO customer(id,name,phone,phone_tail,shop,advisor,lifecycle,
                  level,created,order_cnt,paid_amount,last_interact,addr,birthday,archived,
                  first_order,orders_12m,quarters_12m,amount_12m,idle_days,matched,manual_lc,manual_at)
                  VALUES(?,?,?,?,?,?,'潜在','普通',date('now','localtime'),0,0,date('now','localtime'),
                  '','',0,NULL,0,0,0,0,'潜在',NULL,NULL)""",
                  (nid,d["name"],d["phone"],d["phone"][-4:],d["shop"],d["advisor"]))
        # 疑似重复进人工确认队列
        with sqlite3.connect(DB) as c:
            for ln,nm,why2 in review:
                c.execute("INSERT OR IGNORE INTO task VALUES(?,?,?,?,?,?)",
                  (f"TIMP-{batch}-{ln}","客户合并确认",f"导入第 {ln} 行|{nm}","待处理",
                   datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),why2))
    log_op(actor,"import",batch,"—","导入",True,"IMPORT",
      f"批次 {batch}:成功 {len(good)}、跳过 {len(skip)}、错误 {len(err)}、待人工确认 {len(review)}"
      + ("(试算,未写入)" if dry else ""),{"role":role})
    return dict(ok=True,code="IMPORT",batch=batch,dry=dry,
      counts=dict(total=len(rd),ok=len(good),skip=len(skip),err=len(err),review=len(review)),
      detail=dict(skip=[[a,b,c2] for a,b,c2 in skip[:20]],
                  err=[[a,b,c2] for a,b,c2 in err[:20]],
                  review=[[a,b,c2] for a,b,c2 in review[:20]]),
      reason=(f"试算完成,批次 {batch}:可导入 {len(good)} 行,跳过 {len(skip)},错误 {len(err)},待确认 {len(review)}"
              if dry else
              f"导入完成,批次 {batch}:新增 {len(good)} 人,跳过 {len(skip)},错误 {len(err)},"
              f"{len(review)} 条进入人工确认队列"))

import json as _j
def apply_approval(kind,target,payload,note,actor="魏欣新",role="顾问"):
    """发起高风险操作审批(PRD 第 8 章:等级调整/积分调整/客户批量转移)"""
    if role not in ("店长","总部运营"):
        log_op(actor,"approval",target,"—","申请",False,"WRONG_ROLE",
               f"{kind}须由店长及以上发起,当前角色:{role}",{})
        return dict(ok=False,code="WRONG_ROLE",reason=f"{kind}须由店长及以上发起,当前角色:{role}")
    if not (note or "").strip():
        return dict(ok=False,code="NEED_REASON",
                    reason=f"{kind}必须填写原因(PRD 6.1:须填写原因并记录日志)")
    pre={"等级调整":"AP-LV","积分调整":"AP-PT","客户转移":"AP-TR"}.get(kind,"AP-XX")
    n=rows("SELECT COUNT(*) c FROM approval WHERE kind=?",kind)[0]["c"]+1
    aid=f"{pre}-{n:03d}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO approval VALUES(?,?,?,?,?,?,datetime('now','localtime'),NULL,NULL,?)",
                  (aid,kind,target,_j.dumps(payload,ensure_ascii=False),"待审批",actor,note))
    log_op(actor,"bk-approval",aid,"—","待审批",True,"APPLY",f"{kind} · {target} · {note}",{"role":role})
    return dict(ok=True,code="APPLY",id=aid,
      reason=f"{kind}申请 {aid} 已提交,等待总部运营审批")

def decide_approval(aid,to,note,actor="魏欣新",role="顾问"):
    r=rows("SELECT * FROM approval WHERE id=?",aid)
    if not r: return {"error":"审批单不存在"}
    a=r[0]; cur=a["status"]
    ok,code,why=fsm.check("bk-approval",cur,to,{"role":role})
    log_op(actor,"bk-approval",aid,cur,to,ok,code,why or (note or ""),{"role":role})
    if not ok: return dict(ok=False,code=code,reason=why)
    pl=_j.loads(a["payload"] or "{}")
    applied=""
    if to=="已通过":
        with sqlite3.connect(DB) as c:
            if a["kind"]=="等级调整":
                c.execute("UPDATE customer SET level=? WHERE id=?",(pl.get("to"),a["target"]))
                applied=f";已将 {a['target']} 等级调整为「{pl.get('to')}」"
            elif a["kind"]=="积分调整":
                applied=f";已为 {a['target']} 调整积分 {pl.get('delta'):+d}"
            elif a["kind"]=="客户转移":
                ids=a["target"].split("|")
                for i in ids: c.execute("UPDATE customer SET advisor=? WHERE id=?",(pl.get("to_advisor"),i))
                c.executemany("UPDATE appointment SET advisor=? WHERE customer_id=? AND status='已预约'",
                              [(pl.get("to_advisor"),i) for i in ids])
                applied=f";已将 {len(ids)} 位客户转至 {pl.get('to_advisor')},未完成预约同步迁移"
        log_op(actor,a["kind"],a["target"],"审批通过","已执行",True,"APPLIED",applied.lstrip(";"),{})
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE approval SET status=?,decided_by=?,decided_at=datetime('now','localtime'),note=? WHERE id=?",
                  (to,actor,(a["note"] or "")+" | 审批:"+(note or ""),aid))
    return dict(ok=True,code=to,reason=f"审批单 {aid} {to}"+applied)

def approval_list(q):
    d=_simple("approval",q,["id","target"],{"id","applied_at"},["kind","status"],"applied_at DESC")
    for r in d["rows"]:
        try: r["pl"]=_j.loads(r["payload"] or "{}")
        except Exception: r["pl"]={}
        nm=rows("SELECT name FROM customer WHERE id=?",(r["target"] or "").split("|")[0])
        r["target_name"]=nm[0]["name"] if nm else ""
    return d

def approvals():
    """审批中心:待总部运营审批的事项(后台 PRD 6.2 / 8.1)"""
    merge=rows("SELECT * FROM task WHERE type='客户合并确认' AND status='待总部审批' ORDER BY id")
    for m in merge:
        a,b=(m["ref_id"] or "|").split("|")[:2]
        ra=rows("SELECT id,name,created FROM customer WHERE id=?",a)
        rb=rows("SELECT id,name,created FROM customer WHERE id=?",b)
        m["a"]=ra[0] if ra else None; m["b"]=rb[0] if rb else None
    exp=rows("SELECT * FROM download_task WHERE status='生成中' ORDER BY created DESC")
    risky=rows("SELECT * FROM approval WHERE status='待审批' ORDER BY applied_at DESC")
    for r in risky:
        try: r["pl"]=_j.loads(r["payload"] or "{}")
        except Exception: r["pl"]={}
        nm=rows("SELECT name FROM customer WHERE id=?",(r["target"] or "").split("|")[0])
        r["target_name"]=nm[0]["name"] if nm else ""
    return dict(merge=merge, export=exp, risky=risky,
      rules=[["客户合并","由店长发起、总部运营审批;保留最早客户编号;订单积分只建立关联不重复累计","后台 PRD 6.2"],
             ["批量导出","须经总部运营负责人审批;导出文件添加操作人及时间水印;下载链接 24 小时后失效","后台 PRD 8.1"],
             ["客户转移","同店转移自动迁移未完成跟进任务和未来预约;跨店转移保留已确认预约","后台 PRD 6.2"],
             ["等级与积分调整","总部运营可人工调整,但须填写原因并记录日志","后台 PRD 6.1"]],
      todo=len(merge)+len(exp)+len(risky))

def aftersale_list(q):
    d=_simple("aftersale",q,["id","order_id","customer_id"],
              {"id","created","amount"},["kind","status","shop"],"created DESC")
    for r in d["rows"]:
        nm=rows("SELECT name FROM customer WHERE id=?",r["customer_id"])
        r["cname"]=nm[0]["name"] if nm else ""
    d["chain"]=dict(仅退款=["待确认","审批同意","审批失败","退款失败","待结算","已完成"],
                    退货退款=["提交申请","审批同意","审批拒绝","商品寄回","已入库","退款成功","退款失败","已完成"])
    d["readonly"]=True
    return d

def maintain_list(q):
    d=_simple("maintain",q,["id","order_id","customer_id","item"],
              {"id","created"},["status","shop"],"created DESC")
    for r in d["rows"]:
        nm=rows("SELECT name FROM customer WHERE id=?",r["customer_id"])
        r["cname"]=nm[0]["name"] if nm else ""
    d["chain"]=["待确认","待入库","待处理","处理中","待签收","已完成"]
    d["readonly"]=True
    return d

def guide_perf(q):
    """导购业绩:按顾问聚合。原设计稿无此页面,按后台 PRD 第 9 章数据指标口径实现。"""
    advs=rows("SELECT no,name,role,shop FROM staff WHERE role='顾问' ORDER BY no")
    out=[]
    for a in advs:
        key=f"%{a['name']}%"
        cust_n=rows("SELECT COUNT(*) c FROM customer WHERE advisor LIKE ?",key)[0]["c"]
        od=rows("""SELECT COUNT(*) n, COALESCE(SUM(amount),0) amt FROM ordr
                   WHERE advisor LIKE ? AND status IN ('已完成','待收货','待发货')""",key)[0]
        apt=rows("SELECT COUNT(*) c FROM appointment WHERE advisor LIKE ?",key)[0]["c"]
        arr=rows("SELECT COUNT(*) c FROM appointment WHERE advisor LIKE ? AND status IN ('已到店','已完成')",key)[0]["c"]
        fu=rows("SELECT COUNT(*) c FROM followup WHERE advisor LIKE ?",key)[0]["c"]
        sc=rows("SELECT COUNT(*) c FROM schedule WHERE advisor LIKE ?",key)[0]["c"]
        scd=rows("SELECT COUNT(*) c FROM schedule WHERE advisor LIKE ? AND status='完结'",key)[0]["c"]
        out.append(dict(no=a["no"],name=a["name"],shop=a["shop"],cust=cust_n,
          orders=od["n"],amount=od["amt"],appt=apt,arrived=arr,
          arrive_rate=round(arr/apt*100) if apt else 0,
          followup=fu,task=sc,task_done=scd,
          task_rate=round(scd/sc*100) if sc else 0,
          avg=round(od["amt"]/od["n"],2) if od["n"] else 0))
    key=(q.get("sort") or ["amount"])[0]
    out.sort(key=lambda r:r.get(key,0) or 0,reverse=(q.get("dir") or ["desc"])[0]!="asc")
    return dict(rows=out,total=len(out),
      note="原设计稿无导购业绩页面,本页按后台 PRD 第 9 章「数据指标口径」实现;销售额口径为实付金额,不含已关闭订单。")

def stock_log_list(q):
    d=_simple("stock_log",q,["sku","spu","ref","operator"],{"id","ts","delta"},
              ["kind","operator"],"ts DESC")
    names={r["spu"]:r["name"] for r in rows("SELECT spu,name FROM product")}
    for r in d["rows"]: r["pname"]=names.get(r["spu"],"")
    d["stat"]=rows("""SELECT kind, COUNT(*) n, SUM(delta) sum_d FROM stock_log
                      GROUP BY kind ORDER BY n DESC""")
    return d

def aftersale_detail(aid):
    r=rows("SELECT * FROM aftersale WHERE id=?",aid)
    if not r: return {"error":"售后单不存在"}
    a=r[0]
    o=rows("SELECT * FROM ordr WHERE id=?",a["order_id"])
    a["order"]=o[0] if o else None
    a["items"]=rows("SELECT * FROM ordr_item WHERE order_id=?",a["order_id"])
    cn=rows("SELECT id,name,phone,shop,advisor,level FROM customer WHERE id=?",a["customer_id"])
    if cn:
        c0=cn[0]; p=c0.get("phone") or ""
        c0["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
        a["customer"]=c0
    CHAIN=dict(仅退款=["待确认","审批同意","审批失败","退款失败","待结算","已完成"],
               退货退款=["提交申请","审批同意","审批拒绝","商品寄回","已入库","退款成功","退款失败","已完成"])
    a["chain"]=CHAIN.get(a["kind"],[])
    a["idx"]=a["chain"].index(a["status"]) if a["status"] in a["chain"] else -1
    return a

def maintain_detail(mid):
    r=rows("SELECT * FROM maintain WHERE id=?",mid)
    if not r: return {"error":"维保单不存在"}
    m=r[0]
    cn=rows("SELECT id,name,phone,shop,advisor FROM customer WHERE id=?",m["customer_id"])
    if cn:
        c0=cn[0]; p=c0.get("phone") or ""
        c0["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
        m["customer"]=c0
    o=rows("SELECT id,status,amount,created FROM ordr WHERE id=?",m["order_id"])
    m["order"]=o[0] if o else None
    m["chain"]=["待确认","待入库","待处理","处理中","待签收","已完成"]
    m["idx"]=m["chain"].index(m["status"]) if m["status"] in m["chain"] else -1
    return m

def save_product(d,actor="魏欣新",role="顾问"):
    """新建或编辑商品。下架不影响历史订单(见 bk-product 状态机 notes)。"""
    if role not in ("店长","总部运营"):
        return dict(ok=False,code="WRONG_ROLE",reason=f"商品维护须由店长及以上操作,当前角色:{role}")
    spu=(d.get("spu") or "").strip()
    name=(d.get("name") or "").strip()
    if not name: return dict(ok=False,code="NEED_NAME",reason="商品名称必填")
    try: price=float(d.get("base_price") or 0)
    except Exception: return dict(ok=False,code="BAD_PRICE",reason="基础价必须是数字")
    if price<=0: return dict(ok=False,code="BAD_PRICE",reason="基础价必须大于 0")
    cat=d.get("category") or ""
    if cat and not rows("SELECT 1 FROM category WHERE code=?",cat):
        return dict(ok=False,code="BAD_CATEGORY",reason=f"品类 {cat} 不存在")
    kind=d.get("kind") or "标品"
    tpl=d.get("template") or None
    if kind=="定制品" and not tpl:
        return dict(ok=False,code="NEED_TEMPLATE",reason="定制品必须关联量体模版")
    if tpl:
        code=tpl.split(" ")[0]
        t=rows("SELECT status FROM measure_tpl WHERE code=?",code)
        if not t: return dict(ok=False,code="BAD_TEMPLATE",reason=f"量体模版 {code} 不存在")
        if t[0]["status"]!="启用":
            return dict(ok=False,code="TPL_DISABLED",reason=f"量体模版 {code} 已停用,不可关联")
    new = not spu
    if new:
        n=rows("SELECT COUNT(*) c FROM product")[0]["c"]
        spu=f"lxys_{900000000+n*7919:09d}"[:14]
    old=rows("SELECT * FROM product WHERE spu=?",spu)
    with sqlite3.connect(DB) as c:
        if old:
            c.execute("""UPDATE product SET name=?,category=?,kind=?,base_price=?,template=?,
                         updated=datetime('now','localtime') WHERE spu=?""",
                      (name,cat,kind,price,tpl,spu))
        else:
            c.execute("""INSERT INTO product VALUES(?,?,?,?,'已下架',?,?,
                         datetime('now','localtime'),datetime('now','localtime'),?)""",
                      (spu,name,cat,kind,price,tpl,name[:2]))
            c.execute("INSERT INTO sku VALUES(?,?,?,?,?,?,0,0,'启用')",
                      (f"{spu}-01",spu,"默认/均码","默认","均码",price))
    log_op(actor,"product",spu,"新建" if new else "编辑","已保存",True,
           "CREATE" if new else "UPDATE",f"{name} · {kind} · ¥{price}",{"role":role})
    return dict(ok=True,code="CREATE" if new else "UPDATE",spu=spu,
      reason=(f"商品 {spu} 已创建,默认状态为「已下架」,补齐 SKU 与库存后再上架" if new
              else f"商品 {spu} 已更新"))

def save_block(d,actor="魏欣新"):
    """页面区块增删改与排序"""
    act=d.get("act"); page=d.get("page")
    if not rows("SELECT 1 FROM page WHERE code=?",page): return {"error":"页面不存在"}
    bs=rows("SELECT * FROM page_block WHERE page=? ORDER BY sort",page)
    with sqlite3.connect(DB) as c:
        if act=="add":
            if len(bs)>=10: return dict(ok=False,code="TOO_MANY",reason="单页最多 10 个内容区块")
            c.execute("INSERT INTO page_block(page,sort,kind,title,cfg) VALUES(?,?,?,?,?)",
                      (page,len(bs)+1,d.get("kind"),d.get("title") or d.get("kind"),d.get("cfg") or ""))
            msg=f"新增「{d.get('kind')}」区块"
        elif act=="del":
            c.execute("DELETE FROM page_block WHERE id=?",(d.get("id"),))
            for i,b in enumerate([x for x in bs if str(x["id"])!=str(d.get("id"))],1):
                c.execute("UPDATE page_block SET sort=? WHERE id=?",(i,b["id"]))
            msg=f"删除区块 {d.get('id')} 并重排序号"
        elif act=="edit":
            c.execute("UPDATE page_block SET title=?,cfg=? WHERE id=?",
                      (d.get("title"),d.get("cfg"),d.get("id")))
            msg=f"编辑区块 {d.get('id')}"
        elif act=="move":
            ids=[b["id"] for b in bs]; i=ids.index(int(d.get("id")))
            j=i+(1 if d.get("dir")=="down" else -1)
            if j<0 or j>=len(ids): return dict(ok=False,code="EDGE",reason="已在首位或末位")
            ids[i],ids[j]=ids[j],ids[i]
            for k,bid in enumerate(ids,1): c.execute("UPDATE page_block SET sort=? WHERE id=?",(k,bid))
            msg=f"区块 {d.get('id')} {'下移' if d.get('dir')=='down' else '上移'}"
        else: return dict(ok=False,code="BAD_ACT",reason="未知操作")
        c.execute("UPDATE page SET updated=datetime('now','localtime'),status='草稿' WHERE code=? AND status='已发布'",(page,))
    log_op(actor,"page_block",page,"—",act,True,"BLOCK",msg,{})
    return dict(ok=True,code="BLOCK",reason=msg+";页面已回到草稿状态,需重新发布")

def save_template(d,actor="魏欣新"):
    nm=(d.get("name") or "").strip()
    items=[x for x in (d.get("items") or "").split(",") if x.strip()]
    if not nm: return dict(ok=False,code="NEED_NAME",reason="模版名称必填")
    if not items: return dict(ok=False,code="NEED_ITEMS",reason="至少选择一个测量项")
    bad=[i for i in items if not rows("SELECT 1 FROM measure_item WHERE code=? AND status='启用'",i.strip())]
    if bad: return dict(ok=False,code="BAD_ITEM",reason=f"测量项不存在或已停用:{'、'.join(bad)}")
    n=rows("SELECT COUNT(*) c FROM measure_tpl")[0]["c"]+1
    code=f"MT{n:02d}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO measure_tpl VALUES(?,?,?,'启用','60000008',datetime('now','localtime'))",
                  (code,nm,d.get("descr") or ""))
        for j,it in enumerate(items,1):
            c.execute("INSERT INTO tpl_item VALUES(?,?,?)",(code,it.strip(),j))
    log_op(actor,"measure_tpl",code,"—","新建",True,"CREATE",f"{nm} · {len(items)} 个测量项",{})
    return dict(ok=True,code="CREATE",reason=f"量体模版 {code} 已创建,含 {len(items)} 个测量项")

def save_syscode(d,actor="魏欣新",role="顾问"):
    if role!="总部运营":
        return dict(ok=False,code="WRONG_ROLE",reason=f"系统编码维护须由总部运营操作,当前角色:{role}")
    for k in ("category","name","val"):
        if not (d.get(k) or "").strip():
            return dict(ok=False,code="NEED_FIELD",reason="分类、名称、值均为必填")
    dup=rows("SELECT code FROM sys_code WHERE category=? AND val=?",d["category"],d["val"])
    if dup: return dict(ok=False,code="DUP_VALUE",
        reason=f"同一分类下值「{d['val']}」已存在(编码 {dup[0]['code']})")
    pre={"订单来源":"SC-ORD","配送方式":"SC-DLV","预约方式":"SC-APT","退款失败码":"SC-REF"}.get(d["category"],"SC-OTH")
    n=rows("SELECT COUNT(*) c FROM sys_code WHERE category=?",d["category"])[0]["c"]+1
    code=f"{pre}-{n:02d}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO sys_code VALUES(?,?,?,?,?,'启用',?)",
                  (code,d["category"],d["name"],d["val"],n,d.get("note") or ""))
    log_op(actor,"sys_code",code,"—","新建",True,"CREATE",f"{d['category']} · {d['name']}={d['val']}",{"role":role})
    return dict(ok=True,code="CREATE",reason=f"系统编码 {code} 已创建")

def save_content(d,actor="魏欣新"):
    ti=(d.get("title") or "").strip()
    if not ti: return dict(ok=False,code="NEED_TITLE",reason="标题必填")
    n=rows("SELECT COUNT(*) c FROM content")[0]["c"]
    code=f"CT{100+n}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO content VALUES(?,?,?,'草稿',?,'60000009',date('now','localtime'),0)",
                  (code,ti,d.get("kind") or "品牌故事",d.get("channel") or "小程序首页"))
    log_op(actor,"content",code,"—","新建",True,"CREATE",ti,{})
    return dict(ok=True,code="CREATE",reason=f"内容 {code} 已创建,状态为草稿")

def kb_search(q):
    """领域知识检索 —— 这是 Agent 的 kb_search 工具,当前由页面直接调用"""
    kw=(q.get("q") or [""])[0].strip()
    cat=(q.get("cat") or [""])[0]
    src=(q.get("src") or [""])[0]          # public / scale / demo
    rs=rows("SELECT * FROM craft ORDER BY code")
    if cat: rs=[r for r in rs if r["cat"]==cat]
    # 按来源过滤 —— 顾问要对客户说话之前,先筛出「能说的那部分」
    if src: rs=[r for r in rs if r["src_type"]==src]
    if kw:
        rs=[r for r in rs if any(kw in str(r.get(k) or "")
            for k in ("name","alias","brief","detail","fit"))]
    for r in rs:
        if r["cat"]=="工艺":
            r["combo"]=rows("""SELECT c.material, c.verdict, c.reason, m.name mname
                               FROM craft_combo c LEFT JOIN craft m ON c.material=m.code
                               WHERE c.craft=?""",r["code"])
        elif r["cat"]=="材质":
            r["combo"]=rows("""SELECT c.craft material, c.verdict, c.reason, k.name mname
                               FROM craft_combo c LEFT JOIN craft k ON c.craft=k.code
                               WHERE c.material=?""",r["code"])
        else: r["combo"]=[]
    return dict(rows=rs,total=len(rs),
        cats=[r["v"] for r in rows("SELECT DISTINCT cat v FROM craft ORDER BY v")],
        srcs=[r["v"] for r in rows("SELECT DISTINCT src_type v FROM craft ORDER BY v")],
        src_note={"public":"公开来源,可溯源","scale":"公开资料量级,非本企业数据","demo":"演示数据"})

def combo_matrix():
    crafts=rows("SELECT code,name FROM craft WHERE cat='工艺' ORDER BY code")
    mats=rows("SELECT code,name FROM craft WHERE cat='材质' ORDER BY code")
    cell={(r["craft"],r["material"]):r for r in rows("SELECT * FROM craft_combo")}
    grid=[]
    for k in crafts:
        row=dict(code=k["code"],name=k["name"],cells=[])
        for m in mats:
            c=cell.get((k["code"],m["code"]))
            row["cells"].append(dict(mat=m["name"],mcode=m["code"],
                verdict=c["verdict"] if c else "未定义",
                reason=c["reason"] if c else "该组合在知识库中未定义,须人工评估"))
        grid.append(row)
    undef=sum(1 for r in grid for c in r["cells"] if c["verdict"]=="未定义")
    return dict(crafts=crafts,mats=mats,grid=grid,undef=undef,
      note="组合约束属企业 know-how,无公开来源,全部为演示数据;真实项目须由工艺负责人确认。")

def op_logs(n=200):
    return rows("SELECT * FROM op_log ORDER BY id DESC LIMIT ?",n)

def _page(all_rows, q):
    page=max(1,int(q.get("page",[1])[0])); per=min(100,max(5,int(q.get("per",[10])[0])))
    total=len(all_rows); st=(page-1)*per
    return dict(rows=all_rows[st:st+per], total=total, page=page, per=per,
                pages=max(1,(total+per-1)//per))

def _sort(rs,q,allow):
    k=(q.get("sort") or [None])[0]
    if k not in allow: return rs
    d=(q.get("dir") or ["asc"])[0]=="desc"
    return sorted(rs,key=lambda r:(r.get(k) is None, r.get(k)),reverse=d)

def task_list(q):
    typ=(q.get("type") or ["财务人工任务"])[0]
    kw=(q.get("q") or [""])[0].strip()
    stt=(q.get("status") or [""])[0]
    rs=rows("SELECT * FROM task WHERE type=?",typ)
    dr=load_drafts()
    for r in rs: r["draft"]=dr.get(r["id"],{}).get("status")
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["ref_id"] or "")]
    if stt: rs=[r for r in rs if r["status"]==stt]
    rs=_sort(rs,q,{"id","ref_id","created","status"})
    return _page(rs,q)

def customer_list(q):
    kw=(q.get("q") or [""])[0].strip()
    f={k:(q.get(k) or [""])[0] for k in ("lifecycle","shop","advisor","level")}
    rs=rows("""SELECT id,name,phone,lifecycle,shop,advisor,level,order_cnt,paid_amount,
               last_interact,idle_days,amount_12m,archived FROM customer""")
    for c in rs:
        p=c["phone"] or ""; c["phone_mask"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    if kw: rs=[c for c in rs if kw in c["id"] or kw in (c["name"] or "") or kw in (c["phone"] or "")]
    for k,v in f.items():
        if v: rs=[c for c in rs if c.get(k)==v]
    rs=_sort(rs,q,{"id","name","paid_amount","order_cnt","idle_days","last_interact"})
    d=_page(rs,q)
    for c in d["rows"]: c.pop("phone",None)
    d["facets"]=dict(
      lifecycle=[r["v"] for r in rows("SELECT DISTINCT lifecycle v FROM customer ORDER BY v")],
      shop=[r["v"] for r in rows("SELECT DISTINCT shop v FROM customer WHERE shop!='' ORDER BY v")],
      advisor=[r["v"] for r in rows("SELECT DISTINCT advisor v FROM customer WHERE advisor!='' ORDER BY v")],
      level=[r["v"] for r in rows("SELECT DISTINCT level v FROM customer ORDER BY v")])
    return d

def appt_list_q(q):
    kw=(q.get("q") or [""])[0].strip(); stt=(q.get("status") or [""])[0]; sh=(q.get("shop") or [""])[0]
    rs=rows("""SELECT a.*, c.name cname FROM appointment a
               LEFT JOIN customer c ON a.customer_id=c.id""")
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["cname"] or "") or kw in (r["customer_id"] or "")]
    if stt: rs=[r for r in rs if r["status"]==stt]
    if sh:  rs=[r for r in rs if r["shop"]==sh]
    rs=_sort(rs,q,{"id","start_ts","status","shop"}) or rs
    d=_page(sorted(rs,key=lambda r:r["start_ts"],reverse=True) if not (q.get("sort")) else rs,q)
    d["facets"]=dict(status=["已预约","已到店","已完成","已取消","已过期","爽约"],
                     shop=[r["v"] for r in rows("SELECT DISTINCT shop v FROM appointment ORDER BY v")])
    return d

def customer_detail(cid):
    r=rows("SELECT * FROM customer WHERE id=?",cid)
    if not r: return {"error":"客户不存在"}
    c=r[0]; p=c.get("phone") or ""
    c["phone_mask"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p; c.pop("phone",None)
    c["matched_list"]=[x for x in (c.get("matched") or "").split("/") if x]
    appts=rows("SELECT * FROM appointment WHERE customer_id=? ORDER BY start_ts DESC",cid)
    fus=rows("SELECT * FROM followup WHERE customer_id=? ORDER BY ts DESC",cid)
    deps=rows("""SELECT d.* FROM deposit d WHERE d.customer_id=? ORDER BY d.updated DESC""",cid)
    logs=rows("SELECT * FROM op_log WHERE target=? OR target LIKE ? ORDER BY id DESC LIMIT 50",
              cid,f"%{cid}%")
    return dict(customer=c,appts=appts,followups=fus,deposits=deps,logs=logs,
                measures=measure_of(cid))

def lifecycle_page(sel=None):
    types=["潜在","新客","活跃","高价值","忠诚","休眠","潜在流失","流失"]
    cnt={r["lifecycle"]:r["n"] for r in rows("SELECT lifecycle,COUNT(*) n FROM customer GROUP BY lifecycle")}
    cur=sel or types[0]
    cs=rows("""SELECT id,name,phone,lifecycle,shop,advisor,level,order_cnt,paid_amount,last_interact,
               idle_days,amount_12m,orders_12m,quarters_12m,matched,manual_lc,manual_at
               FROM customer WHERE lifecycle=? ORDER BY (manual_lc IS NULL), id LIMIT 60""",cur)
    for c in cs:
        p=c["phone"] or ""; c["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    # 判定规则来自后台 PRD 6.1
    RULE={"潜在":"无完成订单","新客":"首单后 30 天内","活跃":"90 天内有有效互动",
          "高价值":"近 12 个月实付满 15000 元","忠诚":"近 12 个月满 4 单且跨两个季度",
          "休眠":"无互动 91-180 天","潜在流失":"无互动 181-365 天","流失":"无互动超过 365 天"}
    PRI=["流失","潜在流失","休眠","忠诚","高价值","新客","活跃","潜在"]
    for c in cs:
        c["matched_list"]=[x for x in (c.get("matched") or "").split("/") if x]
        c["conflict"]=len(c["matched_list"])>1
        c["overridden"]=bool(c.get("manual_lc"))
    return dict(types=[dict(l=t,n=cnt.get(t,0),rule=RULE[t],pri=PRI.index(t)+1) for t in types],
                cur=cur, rule=RULE[cur], pri=PRI.index(cur)+1, customers=cs,
                priority=PRI, rules=RULE,
                conflicts=sum(1 for c in cs if c["conflict"]),
                overrides=sum(1 for c in cs if c["overridden"]),
                recalc="系统每日重算单一主状态;人工调整 30 天内优先并记录原因")

def appt_list():
    a=rows("""SELECT a.*, c.name cname FROM appointment a
              LEFT JOIN customer c ON a.customer_id=c.id ORDER BY a.start_ts DESC""")
    return a

def appt_detail(aid):
    r=rows("""SELECT a.*, c.name cname, c.phone cphone FROM appointment a
              LEFT JOIN customer c ON a.customer_id=c.id WHERE a.id=?""",aid)
    if not r: return {"error":"预约不存在"}
    a=r[0]
    p=a.get("cphone") or ""; a["cphone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    dep=rows("SELECT * FROM deposit WHERE id=?",a["deposit_id"])[0] if a.get("deposit_id") else None
    fu=rows("SELECT * FROM followup WHERE appt_id=? ORDER BY ts",aid)
    logs=[dict(ts=a["start_ts"],who=a["advisor"] or "系统",title="新建预约",src="后台")]
    if dep: logs.append(dict(ts=a["start_ts"],who=a["cname"],title="支付押金",src="小程序"))
    if a.get("checkin_ts"): logs.append(dict(ts=a["checkin_ts"],who=a["advisor"],title="到店签到",src="Pad"))
    if a["status"]=="已取消" and dep: logs.append(dict(ts=dep["updated"],who="客服",title="申请退押金",src="后台"))
    return dict(appt=a,deposit=dep,followups=fu,logs=logs)

def _u(x):
    """BaseHTTPRequestHandler 把 path 按 latin-1 解码,中文要转回 UTF-8。"""
    try: return x.encode("latin-1").decode("utf-8")
    except Exception: return x

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,obj,code=200):
        b=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("content-type","application/json; charset=utf-8")
        self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=_u(unquote(urlparse(self.path).path))
        if p in ("/","/index.html"):
            b=open(os.path.join(HERE,"web","index.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/acceptance":
            b=open(os.path.join(HERE,"web","acceptance.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/scheme":
            b=open(os.path.join(HERE,"web","scheme.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/chat":
            b=open(os.path.join(HERE,"web","chat.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/agent":
            b=open(os.path.join(HERE,"web","agent.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p=="/api/acceptance":
            # 验收器属于「异常场景与验收助手」那个项目,不在本仓库里。
            # 这条边是跨项目的,所以要么明确找到,要么明确报错 —— 不能静默失败。
            import time as _t
            _tool=os.environ.get("ACCEPTANCE_TOOL",
                    os.path.join(HERE,"..","..","异常场景与验收助手","tools"))
            if not os.path.isfile(os.path.join(_tool,"acceptance.py")):
                return self._send(dict(error="验收器不在这个项目里。它属于「异常场景与验收助手」,"
                    f"当前找的位置:{os.path.abspath(_tool)};可用 ACCEPTANCE_TOOL 指定。"
                    "本页显示的是上一次跑批的存档结果。"),503)
            sys.path.insert(0, _tool); os.environ.setdefault("TARGET", os.path.join(HERE,".."))
            import acceptance as _acc
            _t0=_t.time(); _rows=_acc.run(); _ms=(_t.time()-_t0)*1000
            return self._send(dict(rows=_rows, summary=_acc.summary(_rows), ms=round(_ms,1)))
        if p=="/api/workbench": return self._send(workbench())
        if p.startswith("/api/task/"): return self._send(task_detail(p.split("/api/task/")[1]))
        if p=="/api/lifecycle": 
            from urllib.parse import parse_qs
            q=parse_qs(urlparse(self.path).query)
            t=(q.get("t") or [None])[0]
            return self._send(lifecycle_page(_u(unquote(t)) if t else None))
        from urllib.parse import parse_qs
        Q={k:[_u(unquote(x)) for x in v] for k,v in parse_qs(urlparse(self.path).query).items()}
        if p=="/api/agent-tasks":
            _T=_truths()
            _out=[]
            for t in backend.list_tasks(None,"待处理"):
                cid = t["ref_id"] if t["type"]=="财务人工任务" else t["id"][1:]
                _out.append(dict(id=t["id"], type=t["type"], ref=t["ref_id"],
                                 bp="BP-01" if t["type"]=="财务人工任务" else "BP-02",
                                 has_truth=cid in _T))
            return self._send(dict(rows=_out))
        if p=="/api/agent-run":
            import time as _t
            tid=(Q.get("task") or [None])[0]
            t=[x for x in backend.list_tasks(None,"待处理") if x["id"]==tid]
            if not t: return self._send(dict(error="任务不存在"),404)
            t=t[0]
            _v1=_agent()
            if t["type"]=="财务人工任务":
                prompt=_v1.BP01.format(ref=t["ref_id"]); case=t["ref_id"]; bp="BP-01"
            else:
                a,b=t["ref_id"].split("|"); prompt=_v1.BP02.format(a=a,b=b); case=t["id"][1:]; bp="BP-02"
            try:
                pv=_v1.provider(); r=_v1.run_case(pv,prompt); r["model"]=pv["model"]
            except Exception as e:
                return self._send(dict(error=str(e)[:300], case=case, task_id=tid))
            # 答案是跑完之后才附上的 —— 模型上下文里从头到尾没有 truth
            _ev=_eval(); tr=_truths().get(case,{})
            _txt=json.dumps(r.get("finding"),ensure_ascii=False) if r.get("finding") else ""
            ok,why=_ev.hit(_txt,tr.get("root_cause",""),case) if r.get("finding") else (False,"未提交")
            r.update(task_id=tid, case=case, bp=bp, prompt=prompt, passed=ok, judge=why,
                     truth=dict(root_cause=tr.get("root_cause"),
                                expected_action=tr.get("expected_action"),
                                expected_evidence=tr.get("expected_evidence"),
                                note=tr.get("note")))
            return self._send(r)
        if p=="/api/agent-negative":
            f=os.path.join(HERE,"..","agent","negative-results.jsonl")
            if not os.path.exists(f): return self._send(dict(rows=[]))
            _nr=[json.loads(l) for l in open(f,encoding="utf-8")]
            return self._send(dict(rows=_nr, passed=sum(r.get("passed") for r in _nr),
                                   total=len(_nr),
                                   cost=round(sum(r.get("cost_local",0) for r in _nr),4)))
        if p=="/api/scheme-options":
            import scheme as _sch
            return self._send(_sch.options())
        if p=="/api/schemes":
            return self._send(scheme_list())
        if p=="/api/chat-eval":
            f=os.path.join(HERE,"..","agent","chat-eval-results.jsonl")
            if not os.path.exists(f): return self._send(dict(rows=[]))
            rs=[json.loads(l) for l in open(f,encoding="utf-8")]
            return self._send(dict(total=len(rs),passed=sum(r.get("passed") for r in rs),
                pos=sum(1 for r in rs if r["kind"]=="正向"),
                pos_ok=sum(r.get("passed") for r in rs if r["kind"]=="正向"),
                neg=sum(1 for r in rs if r["kind"]=="负向"),
                neg_ok=sum(r.get("passed") for r in rs if r["kind"]=="负向"),
                cost=round(sum(r.get("cost_local",0) for r in rs),4),
                model=rs[0].get("model") if rs else None, rows=rs))
        if p=="/api/agent-eval":
            f=os.path.join(HERE,"..","agent","eval-results.jsonl")
            if not os.path.exists(f): return self._send(dict(rows=[]))
            # 不要叫 rows —— 那会把整个 do_GET 里的模块级 rows() 函数遮蔽掉,
            # 后加的任何路由一用 rows() 就 UnboundLocalError,而且表现为连接重置不是 500
            _er=[json.loads(l) for l in open(f,encoding="utf-8")]
            return self._send(dict(rows=_er, passed=sum(r.get("passed") for r in _er),
                                   total=len(_er),
                                   cost=round(sum(r.get("cost_local",0) for r in _er),4),
                                   model=_er[0].get("model") if _er else None))
        if p.startswith("/api/export/"):
            kind=p.split("/api/export/")[1]
            data=export_csv(kind,Q).encode("utf-8-sig")
            self.send_response(200)
            self.send_header("content-type","text/csv; charset=utf-8")
            self.send_header("content-disposition",f'attachment; filename="{kind}.csv"')
            self.send_header("content-length",str(len(data))); self.end_headers()
            self.wfile.write(data); return
        if p=="/api/oplog": return self._send(op_logs())
        if p=="/api/tasks": return self._send(task_list(Q))
        if p=="/api/customers2": return self._send(customer_list(Q))
        if p.startswith("/api/customer/"): return self._send(customer_detail(p.split("/api/customer/")[1]))
        if p=="/api/appts2": return self._send(appt_list_q(Q))
        if p=="/api/shops": return self._send(shop_list(Q))
        if p.startswith("/api/shop/"): return self._send(shop_detail(p.split("/api/shop/")[1]))
        if p=="/api/staff": return self._send(staff_list(Q))
        if p=="/api/schedule": return self._send(schedule_list(Q))
        if p=="/api/orders": return self._send(order_list(Q))
        if p=="/api/products": return self._send(product_list(Q))
        if p.startswith("/api/product/"): return self._send(product_detail(p.split("/api/product/")[1]))
        if p=="/api/categories": return self._send(category_tree())
        if p=="/api/stock": return self._send(stock_list(Q))
        if p=="/api/measure-items": return self._send(measure_items(Q))
        if p=="/api/measure-tpls": return self._send(measure_tpls(Q))
        if p=="/api/contents": return self._send(content_list(Q))
        if p=="/api/activities": return self._send(activity_list(Q))
        if p.startswith("/api/activity/"): return self._send(activity_detail(p.split("/api/activity/")[1]))
        if p=="/api/invites": return self._send(invite_list(Q))
        if p=="/api/pages": return self._send(page_list(Q))
        if p.startswith("/api/page/"): return self._send(page_detail(p.split("/api/page/")[1]))
        if p=="/api/syscodes": return self._send(syscode_list(Q))
        if p=="/api/downloads": return self._send(download_list(Q))
        if p=="/api/approvals": return self._send(approvals())
        if p=="/api/approval-list": return self._send(approval_list(Q))
        if p=="/api/aftersales": return self._send(aftersale_list(Q))
        if p=="/api/maintains": return self._send(maintain_list(Q))
        if p=="/api/guide-perf": return self._send(guide_perf(Q))
        if p=="/api/stock-log": return self._send(stock_log_list(Q))
        if p=="/api/kb": return self._send(kb_search(Q))
        if p=="/api/kb-matrix": return self._send(combo_matrix())
        if p.startswith("/api/aftersale/"): return self._send(aftersale_detail(p.split("/api/aftersale/")[1]))
        if p.startswith("/api/maintain/"): return self._send(maintain_detail(p.split("/api/maintain/")[1]))
        if p=="/api/levels": return self._send(dict(rows=rows("SELECT * FROM level_cfg ORDER BY sort"),
            dist={r["level"]:r["n"] for r in rows("SELECT level,COUNT(*) n FROM customer GROUP BY level")}))
        if p=="/api/tags": return self._send(_simple("tag",Q,["code","name"],{"code","n","updated"},["grp","status"],"code"))
        if p=="/api/appts": return self._send(appt_list())
        if p.startswith("/api/appt/"): return self._send(appt_detail(p.split("/api/appt/")[1]))
        if p=="/api/customers": return self._send(rows("SELECT id,name,phone,shop,advisor,lifecycle,level,order_cnt,paid_amount FROM customer ORDER BY id LIMIT 200"))
        self._send({"error":"not found"},404)
    def do_POST(self):
        p=_u(unquote(urlparse(self.path).path))
        n=int(self.headers.get("content-length") or 0)
        body=json.loads(self.rfile.read(n) or "{}") if n else {}
        if p=="/api/transit":
            return self._send(transit(body.get("machine"),body.get("target"),
                                      body.get("to"),body.get("ctx") or {}))
        if p=="/api/scheme-check":
            # 只校验不落库,给页面做即时提示用。前端拿它染色,但它不是闸门。
            import scheme as _sch
            ok,iss=_sch.validate(xz=body.get("xz"),mt=body.get("mt"),
                                 kf=body.get("kf") or [],ps=body.get("ps") or [],color=body.get("color"))
            return self._send(dict(can_save=ok,issues=iss))
        if p=="/api/scheme-save":
            # 这里才是闸门。前端 disabled 只是体验 —— 绕过前端直接调这个接口,一样拦。
            import scheme as _sch
            ok,iss=_sch.validate(xz=body.get("xz"),mt=body.get("mt"),
                                 kf=body.get("kf") or [],ps=body.get("ps") or [],color=body.get("color"))
            if not ok:
                blocked=[i for i in iss if i["level"]=="block"]
                log_op("魏欣新","fe-scheme",body.get("id") or "新建","-","已保存",False,"INCOMPATIBLE",
                       ";".join(f"{i.get('pair','')} {i['msg'][:40]}" for i in blocked)[:200],{})
                return self._send(dict(ok=False,code="INCOMPATIBLE",
                    reason="选中的组合里有「不可」项,不能保存",issues=iss),409)
            sid=body.get("id") or f"SC{int(__import__('time').time())%100000:05d}"
            cur=rows("SELECT status FROM scheme WHERE id=?",sid)
            with sqlite3.connect(DB) as c:
                if cur:
                    if cur[0]["status"]!="草稿" and cur[0]["status"]!="已保存":
                        return self._send(dict(ok=False,code="NOT_EDITABLE",
                            reason=f"「{cur[0]['status']}」的方案不可再编辑"),409)
                    c.execute("""UPDATE scheme SET name=?,xz=?,mt=?,kf=?,color=?,ps=?,status='已保存',updated=?
                                 WHERE id=?""",
                              (body.get("name"),body.get("xz"),body.get("mt"),
                               ",".join(body.get("kf") or []),body.get("color"),
                               ",".join(body.get("ps") or []),_now(),sid))
                else:
                    c.execute("INSERT INTO scheme VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (sid,body.get("customer_id"),body.get("name") or "未命名方案","已保存",
                               body.get("xz"),body.get("mt"),",".join(body.get("kf") or []),
                               body.get("color"),",".join(body.get("ps") or []),
                               "A01 林岚",None,_now(),_now()))
            log_op("魏欣新","fe-scheme",sid,(cur[0]["status"] if cur else "-"),"已保存",True,"OK",
                   ";".join(f"{i.get('pair','')} {i['kind']}" for i in iss) or "无问题",{})
            return self._send(dict(ok=True,id=sid,issues=iss))
        if p=="/api/scheme-transit":
            if scheme_status(body.get("id")) is None:
                return self._send(dict(ok=False,reason="方案不存在"),404)
            return self._send(transit("fe-scheme",body.get("id"),body.get("to"),body))
        if p=="/api/chat":
            sys.path.insert(0, os.path.join(HERE,"..","agent"))
            import chat as _chat
            q=(body.get("q") or "").strip()
            if not q: return self._send(dict(error="问题是空的"),400)
            hist=[(m["role"],m["content"]) for m in (body.get("history") or [])
                  if m.get("role") in ("user","assistant") and isinstance(m.get("content"),str)][-8:]
            try: return self._send(_chat.ask(q, hist))
            except Exception as e: return self._send(dict(error=str(e)[:300]),500)
        if p=="/api/customer-create": return self._send(create_customer(body))
        if p.startswith("/api/customer-update/"):
            return self._send(update_customer(p.split("/api/customer-update/")[1],body,
                                              role=body.get("role") or "顾问"))
        if p=="/api/approval-apply":
            return self._send(apply_approval(body.get("kind"),body.get("target"),
                body.get("payload") or {},body.get("note"),role=body.get("role") or "顾问"))
        if p=="/api/approval-decide":
            return self._send(decide_approval(body.get("id"),body.get("to"),body.get("note"),
                                              role=body.get("role") or "顾问"))
        if p=="/api/import":
            return self._send(import_customers(body.get("text"),role=body.get("role") or "顾问",
                                               dry=bool(body.get("dry",True))))
        if p=="/api/appt-create": return self._send(create_appointment(body))
        if p=="/api/followup-create": return self._send(create_followup(body))
        if p=="/api/download-create":
            return self._send(create_download(body.get("kind"),body.get("filters")))
        if p=="/api/product-save":
            return self._send(save_product(body,role=body.get("role") or "顾问"))
        if p=="/api/block-save": return self._send(save_block(body))
        if p=="/api/template-save": return self._send(save_template(body))
        if p=="/api/syscode-save":
            return self._send(save_syscode(body,role=body.get("role") or "顾问"))
        if p=="/api/content-save": return self._send(save_content(body))
        if p=="/api/toggle":
            return self._send(toggle(body.get("table"),body.get("key"),body.get("val")))
        if p=="/api/transfer":
            ids=body.get("ids") or []; adv=body.get("advisor"); role=body.get("role") or "顾问"
            if role not in ("店长","总部运营"):
                log_op("魏欣新","customer","|".join(ids[:3]),"—","转移",False,"WRONG_ROLE",
                       f"客户转移须由店长及以上操作,当前角色:{role}",{})
                return self._send(dict(ok=False,code="WRONG_ROLE",
                    reason=f"客户转移须由店长及以上操作,当前角色:{role}"))
            with sqlite3.connect(DB) as c:
                for i in ids: c.execute("UPDATE customer SET advisor=? WHERE id=?",(adv,i))
                c.executemany("UPDATE appointment SET advisor=? WHERE customer_id=? AND status='已预约'",
                              [(adv,i) for i in ids])
            log_op("魏欣新","customer","|".join(ids[:5]),"—","转移",True,"TRANSFER",
                   f"{len(ids)} 人转至 {adv};同店转移已迁移未完成预约。{body.get('note','')}",{})
            return self._send(dict(ok=True,code="TRANSFER",
                reason=f"{len(ids)} 位客户已转至 {adv},未完成预约同步迁移"))
        if p=="/api/task-note":
            tid=body.get("id"); nt=body.get("note") or ""
            with sqlite3.connect(DB) as c:
                c.execute("UPDATE task SET summary=? WHERE id=?",(nt,tid))
            log_op("魏欣新","task",tid,"—","备注",True,"NOTE",nt[:80],{})
            return self._send(dict(ok=True,code="NOTE",reason="备注已保存"))
        if p=="/api/task-close":
            return self._send(close_task(body.get("id"),body.get("result"),body.get("note")))
        if p=="/api/merge":
            return self._send(merge_transit(body.get("id"),body.get("to"),
                                            body.get("note"),role=body.get("role") or "顾问"))
        if p=="/api/lifecycle-adjust":
            return self._send(adjust_lifecycle(body.get("id"),body.get("to"),body.get("reason")))
        if p.startswith("/api/draft/"): return self._send(gen_draft(p.split("/api/draft/")[1]))
        if p.startswith("/api/draft-status/"):
            return self._send(set_draft_status(p.split("/api/draft-status/")[1],
                                               body.get("status"),body.get("note","")))
        self._send({"error":"not found"},404)

if __name__=="__main__":
    port=int(os.environ.get("PORT","8760"))
    print(f"澜绣云裳管理后台 → http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1",port),H).serve_forever()
