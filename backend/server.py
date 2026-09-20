#!/usr/bin/env python3
"""澜绣云裳管理后台 · 本地服务。数据全部来自 lanxiu.db,页面结构对齐 Figma 18 个页面。"""
import json, os, sqlite3, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "knowledge"))
import api as backend
import fsm, rules
import lifecycle as _lc     # 生命周期口径的唯一源头,页面不再自己抄一份
import auth                     # 员工登录:**角色只从服务端会话取,不从请求体读**


def _me(handler):
    """从 Cookie 里的 token 换出当前登录的员工。没登录返回 None。

    **这是整个权限体系的地基。** 在它之前,role 是请求体里的一个字符串 ——
    `check_write` 判「顾问不能补录、店长可以」判得再对,
    也拦不住任何人在请求里写上「店长」。
    **一条链上有一环是约定,整条链就只有约定那么强。**
    """
    ck = handler.headers.get("cookie") or ""
    tok = ""
    for part in ck.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "lx_token": tok = v
    return auth.who(tok)


def _role_of(handler, fallback="顾问"):
    """当前角色。**登录了就用登录身份,没登录就用最低权限** ——
    绝不读请求体里的 role(那是自称)。"""
    u = _me(handler)
    return (u or {}).get("role") or fallback


def _actor_of(handler, fallback="魏欣新"):
    u = _me(handler)
    return (u or {}).get("name") or fallback

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

# log_op 搬去 backend/oplog.py —— 智能体那侧的写工具也要记台账,
# 两处各写一份总有一边会漏,而漏记的那边**看起来完全正常**。
from oplog import log_op   # noqa: E402


def ensure_editlog():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS edit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT,
          actor_no TEXT, obj TEXT, target TEXT, title TEXT, source TEXT,
          changes TEXT)""")
ensure_editlog()


def diff_fields(old, new, 中文名):
    """算出**哪几个字段变了**,返回 [{字段, 改前, 改后}]。

    ⚠️ **只记真的变了的。** 把没改的字段也记一遍,日志会被噪声淹掉,
    而「淹掉」和「没记」在查的时候是一回事 —— 翻十屏找不到那一行。
    """
    out = []
    for k, cn in 中文名.items():
        a, b = old.get(k), new.get(k)
        if a is None and b is None:
            continue
        sa = "" if a is None else str(a)
        sb = "" if b is None else str(b)
        if sa != sb:
            out.append({"字段": cn, "改前": sa, "改后": sb})
    return out


def log_edit(actor, actor_no, obj, target, title, changes, source="后台"):
    """写一条资料编辑日志。

    ⚠️ **`changes` 为空时不写这条日志,而是记一条「什么都没改」。**
    悄悄不写会让「没改动」和「没记录」长得一样 —— 后者是 bug,前者不是,
    而在日志页面上它们都表现为「这次操作没留下痕迹」。
    """
    import json as _j
    if not changes:
        changes = [{"字段": "(无)", "改前": "", "改后": "",
                    "说明": "这次提交没有改动任何字段"}]
        title = title + "(无改动)"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO edit_log(ts,actor,actor_no,obj,target,title,source,changes)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?)",
                  (actor, actor_no, obj, target, title, source,
                   _j.dumps(changes, ensure_ascii=False)))


# 商品字段的中文名 —— **日志给人看,不给机器看**。
# 记 `base_price` 那一行,查的人还要去翻字段表才知道那是售价。
商品字段名 = {"name": "商品名称", "category": "商品类目", "kind": "商品类型",
              "base_price": "销售价", "tag_price": "吊牌价", "unit": "计量单位",
              "gender": "性别", "template": "量体模版", "pattern": "版型",
              "points": "兑换积分", "commission_type": "佣金分配方式",
              "commission_val": "佣金比例/金额", "remark": "备注",
              "status": "上架状态", "img_main": "主图",
              "img_detail": "轮播图", "img_intro": "详情图"}

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
    elif mid=="bk-order":
        r=rows("SELECT * FROM ordr WHERE id=?",target)
        if not r: return {"error":"订单不存在"}
        cur=r[0]["status"]; ctx.setdefault("kind",r[0]["kind"])
        # 标品不走方案审核和生产 —— 把这条写进 ctx,拒绝时的话才说得具体
        ctx.setdefault("amount",r[0]["amount"])
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
         "bk-order":"ordr","fe-scheme":"scheme"}[mid]
    key={"bk-shop":"code","bk-product":"spu","bk-activity":"code","bk-page":"code"}.get(mid,"id")
    with sqlite3.connect(DB) as c:
        c.execute(f"UPDATE {tbl} SET status=? WHERE {key}=?",(to,target))
        if mid=="bk-task" and to=="完结":
            c.execute("UPDATE schedule SET summary=? WHERE id=?",(ctx.get("summary") or "",target))
        if mid=="bk-task" and to=="取消":
            c.execute("UPDATE schedule SET cancel_reason=? WHERE id=?",(ctx.get("reason") or "",target))
        if mid=="bk-order":
            # **prd_status 由 status 派生,不单独流转。**
            # 让两套口径各自走,就是同一个事实两个来源 —— 而它们不一致时
            # 对账检查会红在「数据错」上,实际错的是「谁该跟着谁」。
            c.execute("UPDATE ordr SET prd_status=?,updated=datetime('now','localtime') WHERE id=?",
                      (fsm.ORDER_PRD.get(to, to), target))
            # 几个到点就该落的时间戳 —— 不落的话「什么时候发的货」只能靠 op_log 翻
            _stamp={"已生产":"produced_at","已发货":"shipped_at","完成":"finished_at",
                    "取消":"cancelled_at"}.get(to)
            if _stamp:
                c.execute(f"UPDATE ordr SET {_stamp}=datetime('now','localtime') WHERE id=?",(target,))
        if mid=="bk-deposit" and to=="退款处理中":
            c.execute("""INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,
                         resp_code,resp_msg,idem_key)
                         SELECT ?,COALESCE(MAX(attempt),0)+1,datetime('now','localtime'),'微信支付',
                         (SELECT amount FROM deposit WHERE id=?),'PENDING','处理中',?
                         FROM refund_trace WHERE deposit_id=?""",(target,target,ctx.get("idem_key"),target))
    # 商品的上下架也要进**资料编辑日志** —— 设计稿那块日志里写着「商品上架/下架」。
    # 状态流转本来就在 op_log 里,这里再记一条不是重复:
    # **两张表回答两个问题** —— op_log 回答「这次操作允不允许」(含被拒的),
    # edit_log 回答「这个商品被谁改过什么」。
    # 商品详情页上那块日志读的是后者,而**被拒的操作不该出现在商品的改动史里**
    # (它什么都没改)。所以这条只在流转成功之后写。
    if mid == "bk-product":
        log_edit(actor, ctx.get("actor_no"), "商品", target,
                 f"商品{to}",
                 [{"字段": "上架状态", "改前": cur, "改后": to,
                   "说明": ctx.get("note") or ""}],
                 ctx.get("source") or "后台")
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
        for f in ("phone","addr","shop","advisor_no","level"):
            if ra[f]!=rb[f]: conflicts.append(f"{f}: 取自 {fresh['id']}")
        with sqlite3.connect(DB) as c:
            # 合并标签、量体、跟进、预约、购买记录 → 关联迁移到主档
            c.execute("UPDATE appointment SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            c.execute("UPDATE followup    SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            c.execute("UPDATE deposit     SET customer_id=? WHERE customer_id=?",(main["id"],dup["id"]))
            # 冲突字段取最近确认的数据
            c.execute("""UPDATE customer SET phone=?,addr=?,shop=?,advisor_no=?,level=?,
                         last_interact=? WHERE id=?""",
                      (fresh["phone"],fresh["addr"],fresh["shop"],fresh["advisor_no"],fresh["level"],
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
    rs=填顾问名(rows("""SELECT s.*, c.name cname FROM schedule s
               LEFT JOIN customer c ON s.customer_id=c.id ORDER BY s.start_ts DESC"""))
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["cname"] or "")]
    if stt: rs=[r for r in rs if r["status"]==stt]
    if ty:  rs=[r for r in rs if r["type"]==ty]
    d=_page(rs,q)
    d["facets"]=dict(status=["有效","完结","取消","无效"],
                     type=[r["v"] for r in rows("SELECT DISTINCT type v FROM schedule ORDER BY v")])
    return d

# 设计稿的 10 个状态页签 vs 前端 PRD 11.1 的 6 个状态 —— 差集 D 实例
DESIGN_TABS=["全部","待付款","待审核","待生产","生产中","已生产","待发货","已发货","待完成","完成","取消"]
# 设计稿 10 个页签 → PRD 6 个状态的映射。**这不是「有 4 个没对应」,是多对一** ——
# 待审核/待生产/生产中 三个页签在 PRD 里都被归进「方案确认中」,
# 已生产/待发货 归进「待发货」,已发货/待完成 归进「待收货」。
# 订单表两个口径都存:status 是设计稿口径(页面筛选用),prd_status 是 PRD 口径(状态机用)。
TAB_MAP={"全部":None,
         "待付款":"待付款","待审核":"方案确认中","待生产":"方案确认中","生产中":"方案确认中",
         "已生产":"待发货","待发货":"待发货","已发货":"待收货","待完成":"待收货",
         "完成":"已完成","取消":"已关闭"}

def order_list(q):
    kw=(q.get("q") or [""])[0].strip()
    tab=(q.get("tab") or ["全部"])[0]
    kind=(q.get("kind") or [""])[0]; src=(q.get("source") or [""])[0]
    rs=填顾问名(rows("""SELECT o.*, c.name cname FROM ordr o LEFT JOIN customer c
               ON o.customer_id=c.id ORDER BY o.created DESC"""))
    for r in rs:
        r["items"]=rows("""SELECT sku,name,tag,price,qty,spu,base_amount,custom_amount,total
                           FROM ordr_item WHERE order_id=?""",r["id"])
    if kw: rs=[r for r in rs if kw in r["id"] or kw in (r["cname"] or "")]
    if kind: rs=[r for r in rs if r["kind"]==kind]
    if src:  rs=[r for r in rs if r["source"]==src]
    # status 存的就是设计稿口径,直接按页签筛
    unmapped = tab != "全部" and tab not in TAB_MAP
    if tab != "全部": rs=[r for r in rs if r["status"]==tab]
    d=_page(rs,q)
    d["tabs"]=[dict(name=t,mapped=(t in TAB_MAP),
                    prd=TAB_MAP.get(t) or ("全部" if t=="全部" else None)) for t in DESIGN_TABS]
    d["tab"]=tab; d["unmapped"]=unmapped
    d["facets"]=dict(kind=[r["v"] for r in rows("SELECT DISTINCT kind v FROM ordr")],
                     source=[r["v"] for r in rows("SELECT DISTINCT source v FROM ordr ORDER BY v")])
    d["prd_states"]=["待付款","方案确认中","待发货","待收货","已完成","已关闭"]
    d["counts"]={s:rows("SELECT COUNT(*) c FROM ordr WHERE prd_status=?",s)[0]["c"] for s in d["prd_states"]}
    # 每个设计稿页签下有多少单 —— 用来证明「多对一」而不是「筛不出数据」
    d["tab_counts"]={t:rows("SELECT COUNT(*) c FROM ordr WHERE status=?",t)[0]["c"]
                     for t in DESIGN_TABS if t!="全部"}
    d["tab_counts"]["全部"]=rows("SELECT COUNT(*) c FROM ordr")[0]["c"]
    return d

def cat_paths():
    """三级类目的全路径 —— 设计稿详情页写作「类目一-类目二-类目三」"""
    cs={r["code"]:r for r in rows("SELECT code,name,parent FROM category")}
    out={}
    for code,r in cs.items():
        parts=[]; cur=r
        while cur:
            parts.insert(0,cur["name"]); cur=cs.get(cur["parent"])
        out[code]="-".join(parts)
    return out

def product_list(q):
    kw=(q.get("q") or [""])[0].strip()
    f={k:(q.get(k) or [""])[0] for k in ("kind","status","category","gender")}
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
        if v: rs=[r for r in rs if r.get(k)==v]
    rs=_sort(rs,q,{"spu","name","base_price","stock","avail","updated"})
    d=_page(rs,q)
    # 只列末级类目(没有子节点的),否则筛选框里会混进一二级
    _leaf=[r["code"] for r in rows("""SELECT code FROM category c WHERE NOT EXISTS
             (SELECT 1 FROM category x WHERE x.parent=c.code) ORDER BY code""")]
    d["facets"]=dict(kind=["标品","定制品"],status=["上架","下架"],
      gender=["女","男","童","通用"],category=_leaf)
    d["catnames"]=cat_paths()
    return d

# ── 图片字段的两种形状 ────────────────────────────────────────────────
# 设计稿要的是:
#   轮播图  分**端**(小程序用 / ipad用),各一套
#   详情图  分**组**(商品信息 / 保养 / 送货与退货),组名可自定义、可加新组
# 而原来两个字段都是平数组,表达不了。
#
# ⚠️ **读的时候两种都认。** 换格式最容易出的事是「新代码 + 旧数据」——
# 而旧数据不会报错,只会让页面上少一块图,**看起来像没上传过**。
def 读轮播图(v):
    """→ {"小程序": [...], "ipad": [...]}。旧的平数组当成「小程序」那一套。"""
    try: d = json.loads(v or "[]")
    except Exception: return {"小程序": [], "ipad": []}
    if isinstance(d, list):
        return {"小程序": d, "ipad": []}
    return {"小程序": d.get("小程序") or [], "ipad": d.get("ipad") or []}


def 读详情图(v):
    """→ [{"组名": ..., "图": [...]}]。旧的平数组当成一个叫「商品信息」的组。"""
    try: d = json.loads(v or "[]")
    except Exception: return []
    if isinstance(d, list) and (not d or isinstance(d[0], str)):
        return [{"组名": "商品信息", "图": d}] if d else []
    return [g for g in d if isinstance(g, dict)]


def craft_doc(order_id):
    """**工艺文档** —— 车间照着做、客户照着核的那一张。

    设计交互稿里这张表的列叫「位置 / 工艺 / 颜色 / 定制部件金额」,
    而那一列的**值是「真丝」—— 那是面料,不是工艺**。
    库里 `craft` 把「工艺」(45 条)和「材质」(45 条)分得很清,
    混着叫会让车间不知道该看哪张表。所以这里这一列叫「**面料**」。

    位置用 `knowledge/part.py` 那一套 —— 2026-09-14 裁决:
    交互稿里 pad 写「上身 / 袖子」而这张文档写「领口 / 裙摆」,两套对不上,
    **以 part.py 为准**。
    """
    o = rows("SELECT * FROM ordr WHERE id=?", order_id)
    if not o:
        return {"error": "订单不存在"}
    o = dict(o[0])
    o["items"] = []
    for it in rows("SELECT * FROM ordr_item WHERE order_id=? ORDER BY id", order_id):
        it = dict(it)
        # 按**部位**归拢,一个部位一块 —— 而不是面料一串、工艺一串。
        # 车间是按部位干活的:做领口的人要一眼看到「领口用什么料、做什么绣」。
        _ch = rows("SELECT kind,part,material,color,amount,note FROM item_part_choice "
                   "WHERE item_id=? ORDER BY id", it["id"])
        _g = {}
        for x in _ch:
            b2 = _g.setdefault(x["part"], {"部位": x["part"], "面料": None,
                                           "颜色": None, "工艺": [], "金额": 0.0,
                                           "说明": None})
            if x["kind"] == "面料":
                b2["面料"], b2["颜色"], b2["说明"] = x["material"], x["color"], x["note"]
            else:
                b2["工艺"].append(x["material"])
            b2["金额"] = round(b2["金额"] + (x["amount"] or 0), 2)
        it["choices"] = _ch
        it["parts"] = list(_g.values())
        # 量体:按这一行的着装人取,**取不到要说「没量过」,不能显示空表** ——
        # 空表和「量过但都是 0」在纸上长得一样,而车间会照着裁。
        it["measures"] = rows(
            "SELECT mi.name, r.value, mi.unit FROM measure_rec r "
            "JOIN measure_item mi ON mi.code=r.item "
            "WHERE r.wearer_id=? ORDER BY mi.sort", it.get("wearer_id") or "-")
        w = rows("SELECT name,gender,birthday FROM wearer WHERE id=?",
                 it.get("wearer_id") or "-")
        it["wearer"] = dict(w[0]) if w else None
        # **车间照着这张纸裁,所以这张纸上必须写清用的是版型的哪一版。**
        # 版型是会改的(客户体型超出档差范围就要改版),而改完之后
        # 一张三个月前的工艺文档和今天的长得一模一样。
        # ⚠️ 版本取的是**订单行上的快照**,不是现在那一版 ——
        # 现算会给出「今天」那一版,而车间当初裁的是「那天」那一版。
        # 回填的要标出来:**一个回填的快照假装是当时记的,就是在撒谎。**
        _pv = rows("SELECT p.code, p.name, p.version FROM product pr "
                   "JOIN pattern p ON p.code=pr.pattern WHERE pr.spu=?",
                   it.get("spu") or "-")
        if _pv:
            用 = it.get("pattern_version")
            it["pattern"] = {
                "编码": _pv[0]["code"], "名称": _pv[0]["name"],
                "下单时的版本": (f"v{用}" if 用 else "**没记**"),
                "来源": it.get("pattern_version_src") or "下单时记的",
                "现在是": f"v{_pv[0]['version']}",
                "提醒": (None if (用 and 用 == _pv[0]["version"]) else
                         "⚠️ **这一单用的版本和现在的不是同一版** —— "
                         "按现在这一版裁会和当初不一致"),
            }
        o["items"].append(it)
    # 备注的署名从编辑日志派生 —— 和商品详情页同一条:不另存一份
    e = rows("SELECT ts,actor FROM edit_log WHERE target=? ORDER BY id DESC LIMIT 1",
             order_id)
    o["remark_by"] = e[0]["actor"] if e else None
    o["remark_at"] = e[0]["ts"] if e else None
    return o


def product_detail(spu):
    r=rows("""SELECT p.*, c.name cat_name FROM product p
              LEFT JOIN category c ON p.category=c.code WHERE p.spu=?""",spu)
    if not r: return {"error":"商品不存在"}
    p=r[0]
    p["cat_path"]=cat_paths().get(p["category"],"")
    # **备注是谁写的、什么时候写的 —— 从编辑日志派生,不加两列。**
    # 设计稿在备注旁边标着操作人和时间(李天芳 2025-07-20 03:50)。
    # 加 `remark_by` / `remark_at` 两列当然做得到,但那就是**同一个事实两个来源**:
    # 日志里已经记着「备注 X → Y、谁、什么时候」,再存一份必然会漂
    # —— 有人直接改库、或者某条写入路径忘了同步,两边就对不上,而**不会报错**。
    # 派生的代价是多一次查询,收益是**不可能不一致**。
    _rm = rows("SELECT ts,actor FROM edit_log WHERE obj='商品' AND target=? "
               "AND changes LIKE '%备注%' ORDER BY id DESC LIMIT 1", spu)
    p["remark_by"] = _rm[0]["actor"] if _rm else None
    p["remark_at"] = _rm[0]["ts"] if _rm else None
    # 设计稿右侧那块「量体模板」显示的是**适用模板 + 字段列表** ——
    # 只显示模板名的话,看的人还要跳到另一个页面才知道这件衣服要量哪几项。
    p["tpl_items"]=[]
    if p.get("template"):
        _tc=str(p["template"]).split(" ")[0]
        p["tpl_items"]=[r["name"] for r in rows(
            "SELECT mi.name FROM tpl_item ti JOIN measure_item mi ON mi.code=ti.item "
            "WHERE ti.tpl=? ORDER BY ti.sort",_tc)]
    # ── 分部位可选料(设计稿的「部件」块)──────────────────────────
    import importlib.util as _ilu, os as _os
    _ps = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                        "knowledge", "part.py")
    _sp = _ilu.spec_from_file_location("part", _ps); _part = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_part)
    _c2p = sqlite3.connect(DB)
    _po = rows("SELECT part,material,sort FROM part_option WHERE spu=? "
               "AND kind='面料' ORDER BY sort,material", spu)
    _by = {}
    for r in _po:
        _by.setdefault(r["part"], []).append(r["material"])
    # 每个部位吃多少米、这个数是估的还是版师核过的 —— **一起带出来**。
    # 只给米数不给来源的话,看的人会当成实测值去报价。
    _pt2 = p.get("pattern")
    p["parts"] = []
    for b in _part.部位顺序:
        if b not in _by:
            continue
        米, 源 = _part.部位用料(_c2p, _pt2, b) if _pt2 else (None, None)
        p["parts"].append(dict(部位=b, 可选材质=_by[b], 用料米=米, 用料来源=源))
    # **报价口径要跟着数据一起出** —— 只写在文档里的话,
    # 看页面的人不会去翻文档,而他会直接把这个价报给客户。
    p["part_note"] = _part.报价口径 if p["parts"] else ""
    if p["parts"]:
        # **按部位分摊算料费** —— 不再取「最贵那种料」当上限。
        # 每个部位取它自己可选料里最贵的(客户还没选),乘这个部位的米数。
        _prices = {r["name"]: r["price"] for r in rows("SELECT name,price FROM material")}
        _sum, _估 = 0.0, False
        for g in p["parts"]:
            _hit = [_prices[m] for m in g["可选材质"] if m in _prices]
            if _hit and g.get("用料米"):
                _sum += max(_hit) * g["用料米"]
            if g.get("用料来源") != "版师":
                _估 = True
        p["part_fabric_cost"] = round(_sum, 2)
        p["part_cost_est"] = _估
    _c2p.close()
    # ── 打版图 ──────────────────────────────────────────────────────
    # **不存文件,给的是现画的地址**:版型或号型一改,图跟着改。
    # 号型从 size_spec 现读 —— 写死 S/M/L 的话,童装(110–150)和均码就少一半。
    p["draft"]=None
    if p.get("pattern"):
        _sz=[r["size"] for r in rows(
            "SELECT DISTINCT size FROM size_spec WHERE pattern=? ORDER BY "
            "CASE size WHEN 'S' THEN 1 WHEN 'M' THEN 2 WHEN 'L' THEN 3 WHEN 'XL' THEN 4 ELSE 5 END, size",
            p["pattern"])]
        _pc=rows("SELECT name,qty FROM pattern_piece WHERE pattern=? ORDER BY name",p["pattern"])
        if _sz and _pc:
            p["draft"]=dict(pattern=p["pattern"], sizes=_sz,
                            pieces=[f"{r['name']}×{r['qty']}" for r in _pc],
                            url={z:f"/pattern/{p['pattern']}-{z}.svg" for z in _sz})
    p["banner"]=读轮播图(p.get("img_detail"))
    p["intro_groups"]=读详情图(p.get("img_intro"))
    p["skus"]=rows("SELECT * FROM sku WHERE spu=? ORDER BY code",spu)
    p["orders"]=rows("""SELECT o.id,o.status,o.created,o.amount FROM ordr o
                        JOIN ordr_item i ON i.order_id=o.id WHERE i.sku=?
                        ORDER BY o.created DESC LIMIT 10""",spu)
    p["logs"]=rows("SELECT * FROM op_log WHERE target=? ORDER BY id DESC LIMIT 20",spu)
    # **资料编辑日志** —— 和上面那条不是一回事:
    # `op_log` 回答「这次操作允不允许」(含被拒的),`edit_log` 回答
    # 「这个商品被谁改过什么」。商品详情页上那块日志要的是后者。
    p["edits"]=rows("SELECT ts,actor,title,source,changes FROM edit_log "
                    "WHERE obj='商品' AND target=? ORDER BY id DESC LIMIT 30",spu)
    # 定制品的可选项:形制 + 可选面料 + 可选工艺。
    # 每一对「面料 × 工艺」的相容判定一并带出来 —— 顾问在商品页就能看到哪些组合要留意,
    # 不必等到配置页被拦才知道。
    pc=rows("SELECT * FROM product_custom WHERE spu=?",spu)
    if pc:
        d=dict(pc[0])
        mts=[x for x in (d.get("mt_opts") or "").split(",") if x]
        kfs=[x for x in (d.get("kf_opts") or "").split(",") if x]
        n2c={r["name"]:r["code"] for r in rows("SELECT code,name FROM craft")}
        cb={(r["craft"],r["material"]):r for r in rows("SELECT * FROM craft_combo")}
        grid=[]
        for k in kfs:
            for m in mts:
                hit=cb.get((n2c.get(k),n2c.get(m)))
                grid.append(dict(craft=k,material=m,
                                 verdict=hit["verdict"] if hit else "未定义",
                                 reason=hit["reason"] if hit else "相容矩阵尚未录入这一格,须转工艺负责人确认"))
        d["combo"]=grid
        d["undef"]=sum(1 for g in grid if g["verdict"]=="未定义")
        p["custom"]=d
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
    # ⚠️ **量体人的名字要「造」出来,不是直接读。** 2026-09-16 全库删掉了名字列,
    # 而这里漏改了:`v[0]["measured_by"]` 当场抛 KeyError,客户详情页直接开不开。
    # 门禁 99 步 + CI 全绿都没发现 —— **没有一条检查真的调过这个函数**,
    # 只有 route_check 静态查过「这个 handler 存在」。
    # **「handler 存在」和「handler 跑得起来」是两件事。**
    填顾问名(rs)
    return [dict(tpl=k,name=names.get(k,k),at=v[0]["measured_at"],
                 # 取不到名字就退回工号,**不写空** —— 空白会让人以为「没人量过」,
                 # 而真实信息是「查不到这个工号对应的人」(advisor_name_check 管这件事)。
                 by=v[0].get("measured_by") or v[0].get("measured_by_no"),items=v)
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

def item_impact(code):
    """**停用/改这个测量项会影响谁。**"""
    return dict(
        模版=rows("SELECT COUNT(*) c FROM tpl_item WHERE item=?",code)[0]["c"],
        模版名=[r["name"] for r in rows(
            "SELECT t.name FROM tpl_item ti JOIN measure_tpl t ON t.code=ti.tpl "
            "WHERE ti.item=? LIMIT 4",code)],
        量体记录=rows("SELECT COUNT(*) c FROM measure_rec WHERE item=?",code)[0]["c"])


def _guard_measure_item(code, cur, to):
    """停用测量项的守卫。**停用是可逆的,但不是无害的。**

    一个还被模版引用的测量项被停掉之后:
      · 那几个模版**编辑时**才会报「测量项已停用」
      · 而**已经挂着这些模版的商品照样在用它** —— 量体页面还会量这一项
    两边就此不自洽,**而没有任何地方会报**。

    所以不是拦死 —— 是**要求先把它从模版里摘掉**:
    摘的那一步有自己的守卫(已经量过的不许摘),该拦的在那儿拦。
    """
    if to != "停用":
        return None
    imp = item_impact(code)
    if imp["模版"]:
        return (f"停不了:还有 {imp['模版']} 个模版引用着它"
                + (f"({'、'.join(imp['模版名'])})" if imp["模版名"] else "")
                + f",已有 {imp['量体记录']} 条量体记录。"
                  f"**停用之后这几个模版编辑时才会报错,而挂着它们的商品照样在量这一项** —— "
                  f"两边就此不自洽,而没有任何地方会报。"
                  f"请先把它从这几个模版里摘掉,再停用")
    return None


# 哪些表的状态切换要过守卫。**不在这张表里的照旧直接切** ——
# 加守卫是有代价的(多一次查询、多一条要维护的规则),只给真的会出事的加。
TOGGLE_GUARD = {"measure_item": _guard_measure_item}


def toggle(table,key,val,col="status",on="启用",off="停用",actor="魏欣新"):
    r=rows(f"SELECT {col} s FROM {table} WHERE {key}=?",val)
    if not r: return {"error":"记录不存在"}
    cur=r[0]["s"]; to=off if cur==on else on
    g=TOGGLE_GUARD.get(table)
    if g:
        why=g(val,cur,to)
        if why:
            log_op(actor,table,val,cur,to,False,"TOGGLE_BLOCKED",why[:80],{})
            return dict(ok=False,code="TOGGLE_BLOCKED",reason=why)
    with sqlite3.connect(DB) as c: c.execute(f"UPDATE {table} SET {col}=? WHERE {key}=?",(to,val))
    log_op(actor,table,val,cur,to,True,"TOGGLE",f"{table} 状态切换",{})
    return dict(ok=True,code="TOGGLE",frm=cur,to=to,reason=f"已从「{cur}」切换为「{to}」")


def save_measure_item(d,actor="魏欣新",role="顾问"):
    """新建或编辑测量项。

    ⚠️ **改单位是这一页最危险的动作。**
    `measure_rec` 存的是一个**数**,单位在测量项上。把 cm 改成寸之后,
    **所有历史数值的含义全变了,而数值本身一个都没动** ——
    没有任何东西会报错,而所有按这个数算的东西(推荐尺码、成长预测、
    版型比对)全错。

    所以:**已经有量体记录的测量项,不许改单位。**
    真要换单位,正确的做法是新建一个项 + 把历史数据换算迁过去,
    那是一次有据可查的迁移,不是一次静默的改写。
    """
    if role not in ("总部运营","店长"):
        return dict(ok=False,code="WRONG_ROLE",
                    reason=f"测量项维护须由总部运营或店长操作,当前角色:{role}")
    code=(d.get("code") or "").strip()
    nm=(d.get("name") or "").strip()
    unit=(d.get("unit") or "").strip()
    if not nm: return dict(ok=False,code="NEED_NAME",reason="测量项名称必填")
    if not unit: return dict(ok=False,code="NEED_UNIT",reason="单位必填(cm / kg …)")
    try: req=int(d.get("required") or 0); srt=int(d.get("sort") or 99)
    except Exception: return dict(ok=False,code="BAD_NUMBER",reason="必填与排序必须是数字")
    old=rows("SELECT * FROM measure_item WHERE code=?",code) if code else []
    if code and not old:
        return dict(ok=False,code="NOT_FOUND",reason=f"测量项 {code} 不存在")
    重名=rows("SELECT code FROM measure_item WHERE name=? AND code!=?",nm,code or "-")
    if 重名:
        return dict(ok=False,code="DUP_NAME",
                    reason=f"已经有一个叫「{nm}」的测量项({重名[0]['code']})—— "
                           f"**同名两项在量体页面上分不出来**,量的人只能猜")
    if old:
        o=dict(old[0]); imp=item_impact(code)
        if o["unit"]!=unit and imp["量体记录"]:
            return dict(ok=False,code="UNIT_LOCKED",
                        reason=f"「{o['name']}」已有 {imp['量体记录']} 条量体记录,"
                               f"**不许改单位**({o['unit']} → {unit})。"
                               f"记录里存的是一个数,单位在这儿 —— 改了之后"
                               f"**所有历史数值的含义全变了,而数值一个都没动**,"
                               f"没有任何东西会报错。"
                               f"真要换单位:新建一个项 + 把历史数据换算迁过去")
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE measure_item SET name=?,unit=?,required=?,sort=?,note=? "
                      "WHERE code=?",(nm,unit,req,srt,d.get("note") or "",code))
        ch=[{"字段":k2,"改前":str(o[k1] or ""),"改后":str(v2)}
            for k1,k2,v2 in (("name","名称",nm),("unit","单位",unit),
                             ("required","必填",req),("sort","排序",srt),
                             ("note","说明",d.get("note") or ""))
            if str(o[k1] or "")!=str(v2)]
        log_edit(actor,d.get("actor_no"),"测量项",code,"编辑测量项",ch,
                 d.get("source") or "后台")
        多 = ""
        if not o["required"] and req:
            缺=rows("SELECT COUNT(DISTINCT wearer_id) c FROM measure_rec WHERE wearer_id "
                    "NOT IN (SELECT wearer_id FROM measure_rec WHERE item=?)",code)[0]["c"]
            多=(f"。⚠️ 改成必填之后,**{缺} 个着装人会立刻缺这一项** —— "
                f"他们不是数据错了,是从来没量过")
        return dict(ok=True,code="UPDATE",
                    reason=f"测量项 {code} 已更新({imp['模版']} 个模版引用着它,"
                           f"{imp['量体记录']} 条量体记录){多}")
    n=rows("SELECT COUNT(*) c FROM measure_item")[0]["c"]+1
    code=f"MI{n:02d}"
    while rows("SELECT 1 FROM measure_item WHERE code=?",code):
        n+=1; code=f"MI{n:02d}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO measure_item VALUES(?,?,?,?,?,'启用',?)",
                  (code,nm,unit,req,srt,d.get("note") or ""))
    log_edit(actor,d.get("actor_no"),"测量项",code,"创建测量项",
             [{"字段":"名称","改前":"","改后":nm},{"字段":"单位","改前":"","改后":unit}],
             d.get("source") or "后台")
    log_op(actor,"measure_item",code,"—","新建",True,"CREATE",f"{nm} · {unit}",{})
    return dict(ok=True,code="CREATE",
                reason=f"测量项 {code} 已创建。**它还没被任何模版引用** —— "
                       f"要真的用上,去量体模版里把它加进去")

# ── 顾问名字:**工号是引用,名字现取** ──────────────────────────────────
#
# 那几张表的 `advisor` 列存的是「A04 陆微」这样的名字,而名字是 `staff` 的副本。
# **一个被钉住的缓存和一个自由漂移的副本,在表上长得一模一样** ——
# 这就是 `intent/advisor-columns.md` 要删掉它们的理由。
#
# 删列之前先把读的一侧收拢到这里:页面不再读那一列,而是**拿工号去员工表取**。
# 这样列删掉之后页面一个字都不用改 —— 而在这个函数之前,
# 删列的后果是**页面静默显示空名字**,没有人看得见。
#
# ⚠️ **只有一个来源。** 原来这件事散在 7 个页面函数的 SQL 里,
# 而散着的口径必然漂。
#
# 显示格式是「A04 陆微」—— 短号在 `staff.adv_code`。
# ⚠️ 38 个员工里 **29 个没有短号**(只有顾问角色才有),这时候**只显示名字**,
# **不许自己拼一个短号出来** —— 拼出来的编号会被当成真的拿去对人。
_号名 = {}


def _花名册():
    if not _号名:
        for r in rows("SELECT no,name,adv_code FROM staff"):
            _号名[r["no"]] = (r["name"], r["adv_code"])
    return _号名


def 顾问工号(显示串):
    """「A04 陆微」/「陆微」→ 工号。**认不出返回 None,不猜。**

    页面表单里填的是显示串,而库里要存的是工号 ——
    **名字是 `staff` 的副本,工号才是引用**。
    认不出来时返回 None 而不是挑一个最像的:
    **挑错的话这条客户会挂到另一个顾问名下,而页面上完全正常。**
    """
    v = (显示串 or "").strip()
    if not v: return None
    for no, (名, 短) in _花名册().items():
        if v == 名 or (短 and v == f"{短} {名}") or (短 and v == 短):
            return no
    return None


def 填顾问名(rs):
    """把每一行的顾问名字**按工号现取**填上。原地改,返回原列表。

    ⚠️ **取不到就保留原值,不写空。** 取不到有两种可能:工号是空的(老数据),
    或者这个人已经不在员工表里 —— **两种都不该让页面上那一栏变成空白**,
    那会让人以为「这单没有顾问」。而真正的信息是「查不到这个工号对应的人」,
    `advisor_name_check` 会把它抓出来。
    """
    nm = _花名册()
    for r in rs:
        try: 有 = set(r.keys())
        except Exception: continue
        for 名列, 号列 in (("advisor", "advisor_no"), ("measured_by", "measured_by_no")):
            # ⚠️ **名字列 2026-09-16 全库删除,所以这里要「造」出这个字段,不是「改写」它。**
            #
            # 原来的条件是「名字列和工号列都在才填」—— 那是列还没删时的写法。
            # 列删掉之后 `advisor` 这个 key 根本不存在,于是这段直接跳过,
            # **页面上那一栏整个消失** —— 而页面照常打开、表格照常有行。
            #
            # 这正是 `intent/advisor-columns.md` 警告的那句
            # 「删了页面会静默显示空名字」。**是 `advisor_name_check` 抓住的。**
            if 号列 not in 有:
                continue
            got = nm.get(r.get(号列))
            if not got:
                continue          # **保留原值** —— 见上面那段
            名, 短 = got
            r[名列] = f"{短} {名}" if 短 else 名
    return rs

def _simple(table,q,key,sortable,facet_cols,order=None):
    kw=(q.get("q") or [""])[0].strip()
    # **统一在这里填顾问名** —— `_simple` 是七八个列表页的共同入口,
    # 在这儿填一次,比每个页面各填一次少七处漏掉的机会。
    rs=填顾问名(rows(f"SELECT * FROM {table}" + (f" ORDER BY {order}" if order else "")))
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

# ── 四个写接口:路由一直挂着,函数从来没写过 ─────────────────────
# 发现方式:另一个会话用 AST 把 do_POST / do_GET 里被调用的裸函数名和模块里
# 定义过的名字对了一遍,四个对不上。实证 `GET /api/export/customers` → **HTTP 000**
# (handler 抛 NameError,连响应都没发出去,连接直接断)。
#
# 这类洞的可怕之处:**它不在任何检查的视野里**。ui_audit 查的是页面控件有没有绑定,
# 不解析 POST handler 的名字;页面上按钮好好的,后端一调就断。
# 所以这一轮同时加了结构检查 route_check.py:**路由调的函数必须真的存在**。
#
# 校验一律走 backend/rules.py —— 那是产品真实在用的规则,不在这儿另写一遍。

def _insert(table, vals, required):
    """按列名写一行。**必填列对不上就当场炸,不静默丢。**

    这个函数是补票买的。原来两个 create 里写的是:

        use = [k for k in cols if k in vals]      # 只写表里真有的列

    本意是「列名对不上也不炸」,实际效果是**把崩溃换成了静默丢数据**——
    create_appointment 的 vals 写了 `appt_at`,而表里是 `start_ts`/`end_ts`,
    于是**时间被严格校验了(补录权限那条就是它),然后没有被存下来**;
    create_followup 同样丢了 `ts`。建出来的记录一片 NULL,而接口返回 ok:true。

    **崩溃是好事,静默丢数据不是。** 现在必填列不在表里就直接抛,
    在开发期第一次调用就会炸出来,而不是在某天有人问「这条预约几点」时才发现。
    """
    with sqlite3.connect(DB) as c:
        cols = {x[1] for x in c.execute(f"PRAGMA table_info({table})")}
        miss = [k for k in required if k not in cols]
        if miss:
            raise RuntimeError(f"{table} 表没有这些列:{miss} —— 代码和库结构对不上,"
                               f"现有列:{sorted(cols)}")
        use = [k for k in vals if k in cols]
        dropped = [k for k in vals if k not in cols]
        if dropped:   # 非必填的对不上也要出声,别让它悄悄消失
            print(f"⚠ {table}: 字段 {dropped} 不在表里,已忽略", file=sys.stderr)
        c.execute(f"INSERT INTO {table}({','.join(use)}) VALUES({','.join('?' * len(use))})",
                  [vals[k] for k in use])


def resolve_combo(d, actor="魏欣新", _role=None):
    """**核实回填** —— 工艺负责人打样确认之后,把结论写回相容矩阵。

    这是待核实队列的另一半。队列只说「谁被问了」,答案要人去打样;
    打完样由这里写回去,那一格的依据就从「没有」变成「人工确认」,
    从此 kb_combo 会直接给结论,也不再进队列。

    **写在后台,不在工具层** —— 「工具层一个写接口都没有」那条保证靠
    mode=ro 连接结构性成立,不能为了方便就破。模型能看队列,不能回填。
    """
    # **名字和编码都收,而且回显名字。**
    # 演示时当场栽了一次:我手输编码 KF11 × MT44,以为那是「平绣×棉麻」,
    # 而它是另一个组合。旧版只检查「这一格存在」,不检查「是不是你要的那一格」——
    # 于是它老老实实给另一个组合盖了「人工确认」的章,还返回成功。
    #
    # **回填是把「没有依据」覆盖成「验证过」,写错格子等于给没人验过的组合发合格证。**
    # 现在走和 kb_combo 同一套名字解析(_resolve),而且返回里回显**名字**,
    # 让人一眼看得出自己填的是哪一格。
    _ck, _e1 = backend._resolve(d.get("craft"), "工艺")
    _mk, _e2 = backend._resolve(d.get("material"), "材质")
    if _e1: return dict(ok=False, code="BAD_CRAFT", reason=_e1)
    if _e2: return dict(ok=False, code="BAD_MATERIAL", reason=_e2)
    ck, mk = _ck["code"], _mk["code"]
    cname, mname = _ck["name"], _mk["name"]
    v = (d.get("verdict") or "").strip()
    role = _role or "顾问"
    if v not in ("可", "不可", "需评估"):
        return dict(ok=False, code="BAD_VERDICT",
                    reason="结论只能是「可 / 不可 / 需评估」三选一")
    if role not in ("工艺负责人", "店长", "总部运营"):
        return dict(ok=False, code="WRONG_ROLE",
                    reason=f"核实回填须由工艺负责人及以上操作,当前角色:{role}")
    if not (d.get("reason") or "").strip():
        return dict(ok=False, code="NEED_REASON",
                    reason="必须写明**打样看到了什么** —— 没有理由的结论和默认放行没区别")
    cur = rows("SELECT verdict,rule FROM craft_combo WHERE craft=? AND material=?", ck, mk)
    if not cur: return dict(ok=False, code="NO_CELL", reason=f"矩阵里没有 {ck} × {mk} 这一格")
    old = cur[0]
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE craft_combo SET verdict=?,reason=?,rule='人工确认',src_type='demo' "
                  "WHERE craft=? AND material=?", (v, d["reason"], ck, mk))
    log_op(actor, "combo", f"{cname}×{mname}", old["verdict"], v, True, "RESOLVE",
           f"核实回填 {ck}×{mk}:{old['rule'] or '无依据'} → 人工确认;{d['reason'][:50]}",
           {"role": role})
    return dict(ok=True, code="RESOLVE", 组合=f"{cname} × {mname}", 编码=f"{ck} × {mk}",
                reason=f"**{cname} × {mname}**({ck} × {mk})已回填为「{v}」,"
                       f"依据等级升为「人工确认」,这一格从待核实队列里消失。"
                       f"原来是「{old['verdict']} / {old['rule'] or '无依据'}」")


# 排任务的全部逻辑搬进 backend/tasks.py —— **HTTP 入口和智能体工具共用同一份**。
# 抄两份的话,「顾问不能替别人点完成」这条会有一份先被改松,
# 而松掉的那一份不会报错,只会悄悄多出一批别人代点的完结记录。
from tasks import (MANAGER_ROLES, my_staff, assign_task, dispatch, reassign,   # noqa: E402
                   my_tasks, finish_task, visible_scope)


def create_customer(d, actor="魏欣新", _role=None):
    """新建客户档案。PRD 6.2:姓名必填、手机号唯一、疑似重复要提示。"""
    import datetime
    # role 由调用方(路由)从**会话**取好传进来;d 里的 role 一律忽略。
    role = _role or "顾问"
    ex = rows("SELECT id,name,phone,shop,birthday,addr FROM customer")
    # validate_customer 返回的是 **4 个值**:(ok, code, reason, suspects)。
    # 第一版只解了 3 个,直接 ValueError —— 而且 suspects 是有业务含义的:
    # NEED_REVIEW 那条规则(姓名相似 + 尾号门店相同 → 转店长确认)
    # 要把疑似的那几条**带给人看**,不然店长凭什么确认。
    ok, code, why, suspects = rules.validate_customer(d, ex, actor_role=role)
    if not ok:
        log_op(actor, "customer", "-", "—", "新建", False, code, why,
               {"role": role, "suspects": [x["id"] for x in (suspects or [])]})
        return dict(ok=False, code=code, reason=why,
                    疑似重复=[dict(id=x["id"], name=x["name"], shop=x.get("shop"))
                              for x in (suspects or [])])
    ph = rules.norm_phone(d.get("phone"))
    n = rows("SELECT COUNT(*) c FROM customer")[0]["c"]
    cid = f"C{10000 + n + 1}"
    with sqlite3.connect(DB) as c:
        # ⚠️ **工号也要写。** 表单里填的是显示串,而库里要存的是引用。
        # 认不出来时 `顾问工号` 返回 None —— **不挑一个最像的**:
        # 挑错的话这条客户会挂到另一个顾问名下,而页面上完全正常。
        c.execute("""INSERT INTO customer(id,name,phone,phone_tail,shop,advisor_no,
                     lifecycle,
                     level,created,order_cnt,paid_amount,addr,birthday,archived,idle_days)
                     VALUES(?,?,?,?,?,?,'潜在','普通',?,0,0,?,?,0,0)""",
                  (cid, d.get("name"), ph, (ph or "")[-4:], d.get("shop"),
                   顾问工号(d.get("advisor")),
                   datetime.date.today().isoformat(), d.get("addr"), d.get("birthday")))
    log_op(actor, "customer", cid, "—", "潜在", True, "CREATE",
           f"新建客户 {d.get('name')};生命周期初始为「潜在」(无完成订单)", {"role": role})
    return dict(ok=True, code="CREATE", id=cid,
                reason=f"已建档 {cid}。**生命周期初始是「潜在」** —— 它由每日重算决定,不接受手工流转")


def create_appointment(d, actor="魏欣新", _role=None):
    """新建预约。PRD:早于当前时间的补录只有店长及以上能做 —— 判据在 rules.py。"""
    import datetime
    role = _role or "顾问"
    ok, code, why = rules.validate_appointment(d, actor_role=role)
    if not ok:
        log_op(actor, "appointment", "-", "—", "新建", False, code, why, {"role": role})
        return dict(ok=False, code=code, reason=why)
    n = rows("SELECT COUNT(*) c FROM appointment")[0]["c"]
    aid = f"AP{datetime.datetime.now():%y%m%d}{n + 1:04d}"
    # 列名以**表**为准:appointment 是 start_ts / end_ts,不是 appt_at。
    # 校验读的也是 d["start"] / d["end"](见 rules.validate_appointment),两头对齐。
    _insert("appointment",
            {"id": aid, "customer_id": d.get("customer_id"), "shop": d.get("shop"),
             "advisor": d.get("advisor"), "status": "待确认",
             "start_ts": (d.get("start") or "").replace("T", " "),
             "end_ts": (d.get("end") or "").replace("T", " ")},
            required=["id", "customer_id", "start_ts", "end_ts", "status"])
    log_op(actor, "appointment", aid, "—", "待确认", True, "CREATE",
           f"新建预约 {aid},客户 {d.get('customer_id')},"
           f"{d.get('start')} → {d.get('end')}", {"role": role})
    return dict(ok=True, code="CREATE", id=aid, reason=f"已建预约 {aid},状态「待确认」")


def create_followup(d, actor="魏欣新"):
    """新建跟进记录。跟进是**只增不改**的流水 —— 改跟进等于改历史。"""
    import datetime
    if not (d.get("customer_id") and (d.get("content") or d.get("note"))):
        return dict(ok=False, code="MISSING", reason="客户号和跟进内容都必填")
    if not rows("SELECT id FROM customer WHERE id=?", d["customer_id"]):
        return dict(ok=False, code="NO_CUSTOMER", reason=f"客户 {d['customer_id']} 不存在")
    n = rows("SELECT COUNT(*) c FROM followup")[0]["c"]
    fid = f"FU{datetime.datetime.now():%y%m%d}{n + 1:04d}"
    # followup 的列是 id / customer_id / appt_id / ts / channel / content / advisor
    _insert("followup",
            {"id": fid, "customer_id": d["customer_id"],
             "appt_id": d.get("appt_id"),
             "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "channel": d.get("channel") or "电话",
             "content": d.get("content") or d.get("note"),
             "advisor": d.get("advisor")},
            required=["id", "customer_id", "ts", "content"])
    log_op(actor, "followup", fid, "—", "已记录", True, "CREATE",
           f"跟进 {d['customer_id']}:{(d.get('content') or d.get('note'))[:40]}", {})
    return dict(ok=True, code="CREATE", id=fid, reason=f"已记录跟进 {fid}")


# CSV 导出。**不做全表 SELECT *** —— 手机号、地址这些字段导出去就脱离系统了,
# 只导页面上已经展示的那几列,而且沿用页面的脱敏。
_EXPORT = {
    # ⚠️ 名字列 2026-09-16 全库删除,这里漏改了 —— 整个导出功能报
    # `no such column: advisor`,而**没有任何检查调用过导出**(route_check 只静态查存在)。
    # 改成 join 员工表按工号取名,**同时保留工号**:取不到名字时那一栏不至于空白,
    # 空白会让人以为「这个客户没有顾问」,而真实信息是「查不到这个工号对应的人」。
    "customers": ("客户档案", "SELECT c.id 客户号,c.name 姓名,c.phone_tail 手机尾号,c.shop 门店,"
                  "c.advisor_no 顾问工号,s.name 顾问,c.lifecycle 生命周期,c.level 等级,"
                  "c.order_cnt 订单数,c.paid_amount 实付,c.created 建档日 "
                  "FROM customer c LEFT JOIN staff s ON s.no=c.advisor_no ORDER BY c.id"),
    "orders":    ("订单", "SELECT id 订单号,customer_id 客户号,status 状态,amount 金额,"
                  "created 下单时间 FROM ordr ORDER BY id"),
    "workorders":("在制工单", "SELECT id 工单号,artisan 师傅,craft 工艺,status 状态,"
                  "start_date 开工,due_date 交期 FROM workorder ORDER BY due_date"),
    # ⚠️ 这条按的是**早就不存在的老 schema**(obj / obj_id / detail),
    # 实际列是 machine / target / reason。整条导出一跑就 `no such column: obj` ——
    # **说明它从来没被跑过一次**。和上面那条一样,是这次冒烟检查揪出来的。
    "oplog":     ("操作日志", "SELECT ts 时间,actor 操作人,machine 对象,target 编号,"
                  "code 结果码,allowed 是否放行,reason 说明 FROM op_log "
                  "ORDER BY ts DESC LIMIT 5000"),
}

def export_csv(kind, q=None, actor="魏欣新"):
    """导出 CSV。kind 见 _EXPORT;未知 kind 返回可选清单,不静默给空文件。"""
    import csv, io
    if kind not in _EXPORT:
        return "错误\n" + f"没有「{kind}」这种导出,可选:{'、'.join(_EXPORT)}\n"
    name, sql = _EXPORT[kind]
    rs = rows(sql)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(rs[0].keys() if rs else ["(无数据)"])
    for r in rs: w.writerow([r[k] for k in r.keys()])
    log_op(actor, "download", kind, "—", "已导出", True, "EXPORT",
           f"{name} 导出 {len(rs)} 行", {})
    return buf.getvalue()


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
          dict(name=d.get("name"),phone=ph,shop=d.get("shop"),advisor_no=顾问工号(d.get("advisor")),
               addr=d.get("addr"),birthday=d.get("birthday")).items()
          if v and str(old.get(k))!=str(v)]
    if not diff: return dict(ok=True,code="NOCHANGE",reason="没有字段发生变化")
    with sqlite3.connect(DB) as c:
        c.execute("""UPDATE customer SET name=COALESCE(?,name),phone=?,phone_tail=?,
                     shop=COALESCE(?,shop),advisor_no=COALESCE(?,advisor_no),
                     addr=COALESCE(?,addr),birthday=COALESCE(?,birthday) WHERE id=?""",
                  (d.get("name"),ph,ph[-4:],d.get("shop"),顾问工号(d.get("advisor")),
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
                c.execute("""INSERT INTO customer(id,name,phone,phone_tail,shop,
                  advisor_no,lifecycle,
                  level,created,order_cnt,paid_amount,last_interact,addr,birthday,archived,
                  first_order,orders_12m,quarters_12m,amount_12m,idle_days,matched,manual_lc,manual_at)
                  VALUES(?,?,?,?,?,?,'潜在','普通',date('now','localtime'),0,0,date('now','localtime'),
                  '','',0,NULL,0,0,0,0,'潜在',NULL,NULL)""",
                  (nid,d["name"],d["phone"],d["phone"][-4:],d["shop"],
                   顾问工号(d["advisor"])))
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
                # ⚠️ 名字列已删 —— 转移写的是**工号**。页面传来的仍是显示串,
                # 用 `顾问工号()` 翻译;**翻不出来就写 None,不猜**。
                _to = 顾问工号(pl.get("to_advisor"))
                for i in ids: c.execute("UPDATE customer SET advisor_no=? WHERE id=?",(_to,i))
                c.executemany("UPDATE appointment SET advisor_no=? WHERE customer_id=? AND status='已预约'",
                              [(_to,i) for i in ids])
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
        # ⚠️ **按工号数,不按名字 LIKE。**
        # 原来是 `WHERE advisor LIKE '%林岚%'` —— 名字一改,这几个统计**当场归零**,
        # 而归零在页面上就是「这个顾问没有客户、没有订单」,
        # **看不出是坏了**。而且 LIKE 还会把「林岚岚」这样的名字一起数进来。
        no=a["no"]
        cust_n=rows("SELECT COUNT(*) c FROM customer WHERE advisor_no=?",no)[0]["c"]
        od=rows("""SELECT COUNT(*) n, COALESCE(SUM(amount),0) amt FROM ordr
                   WHERE advisor_no=? AND status IN ('已完成','待收货','待发货')""",no)[0]
        apt=rows("SELECT COUNT(*) c FROM appointment WHERE advisor_no=?",no)[0]["c"]
        arr=rows("SELECT COUNT(*) c FROM appointment WHERE advisor_no=? AND status IN ('已到店','已完成')",no)[0]["c"]
        fu=rows("SELECT COUNT(*) c FROM followup WHERE advisor_no=?",no)[0]["c"]
        sc=rows("SELECT COUNT(*) c FROM schedule WHERE advisor_no=?",no)[0]["c"]
        scd=rows("SELECT COUNT(*) c FROM schedule WHERE advisor_no=? AND status='完结'",no)[0]["c"]
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
    # 名字列 2026-09-16 已删,这里改取工号,名字交给 填顾问名() 现造
    cn=rows("SELECT id,name,phone,shop,advisor_no,level FROM customer WHERE id=?",a["customer_id"])
    填顾问名(cn)
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
    # 同上:按工号取,名字现造
    cn=rows("SELECT id,name,phone,shop,advisor_no FROM customer WHERE id=?",m["customer_id"])
    填顾问名(cn)
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
    """新建或编辑商品。下架不影响历史订单(见 bk-product 状态机 notes)。

    ⚠️ **只有总部运营。** 原来是「店长及以上」,那是个漏洞:

    商品是**全国一份的主数据** —— 它挂的版型决定用料基准、工期、
    能做哪些尺码、量体量哪些项。店长能改的话,同一个 SPU 在静安店挂 PT55、
    在徐汇店挂 PT57,于是:

      · 同一件衣服在两家店**报出不同的价**(用料基准 4.4 米 vs 3.78 米)
      · 量体模板也不同 → 两家店量的项目不一样
      · 而**报表上完全正常**,没有任何地方会报错

    判据和「等级调整 / 积分调整 / 客户转移 要总部运营审批」是同一条:
    **它绕过了一条本该全局统一的规则。**

    门店该定的是**这一单用哪个变体**(标准 / 加长 / 改良通勤)——
    客户身高体型不同,那是门店的判断;而「形制 + 性别」由总部定死。

    和 `save_syscode`(系统编码)同级,不和 `import_customers`(客户导入)同级 ——
    客户是门店的,商品和编码是全国的。
    """
    if role != "总部运营":
        return dict(ok=False,code="WRONG_ROLE",
                    reason=f"商品维护须由**总部运营**操作,当前角色:{role}。"
                           f"商品是全国一份的主数据 —— 它挂的版型决定用料、工期和量体项,"
                           f"门店各改一份会让同一件衣服在两家店报出不同的价。"
                           f"门店该定的是这一单用哪个变体(标准/加长/改良通勤)")
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
    # ── 设计稿基本信息块有 12 项,而编辑表单原来只写 5 个 ──────────────
    # 吊牌价 / 计量单位 / 性别 / 佣金方式 / 佣金比例 / 备注 / 主图
    # **只有新建时写一次,之后永远改不了** —— 而页面上照样显示它们,
    # 所以表现出来只是「点编辑,看到的字段比详情页少」,不报错。
    def _num(k, lo=None):
        v = d.get(k)
        if v in (None, ""): return None, None
        try: v = float(v)
        except Exception: return None, f"{商品字段名.get(k,k)}必须是数字"
        if lo is not None and v < lo: return None, f"{商品字段名.get(k,k)}不能小于 {lo}"
        return v, None
    tagp, e1 = _num("tag_price", 0)
    comv, e2 = _num("commission_val", 0)
    pts,  e3 = _num("points", 0)
    for e in (e1, e2, e3):
        if e: return dict(ok=False, code="BAD_NUMBER", reason=e)
    # **吊牌价低于销售价是错的** —— 吊牌价是划线价,低了页面上会出现
    # 「原价 ¥80 现价 ¥100」这种自相矛盾的展示,而它不会报错。
    if tagp is not None and tagp < price:
        return dict(ok=False, code="BAD_TAGPRICE",
                    reason=f"吊牌价 ¥{tagp:.0f} 低于销售价 ¥{price:.0f} —— "
                           f"吊牌价是划线价,低了页面上会出现「原价比现价还低」")
    ct = d.get("commission_type")
    if ct and ct not in ("按比例", "按金额"):
        return dict(ok=False, code="BAD_COMMISSION", reason="佣金分配方式只能是「按比例」或「按金额」")
    if ct == "按比例" and comv is not None and comv > 100:
        return dict(ok=False, code="BAD_COMMISSION", reason="按比例时佣金不能超过 100%")
    gd = d.get("gender")
    if gd and gd not in ("女", "男", "童", "通用"):
        return dict(ok=False, code="BAD_GENDER", reason="性别只能是 女 / 男 / 童 / 通用")

    new = not spu
    if new:
        n=rows("SELECT COUNT(*) c FROM product")[0]["c"]
        spu=f"lxys_{900000000+n*7919:09d}"[:14]
    old=rows("SELECT * FROM product WHERE spu=?",spu)
    with sqlite3.connect(DB) as c:
        if old:
            # **这条 SET 子句和下面的「写入覆盖的字段」必须一模一样**,
            # `edit_log_check` 第一条盯着 —— 不一样的话日志就会撒谎。
            c.execute("""UPDATE product SET name=?,category=?,kind=?,base_price=?,template=?,
                         tag_price=COALESCE(?,tag_price),unit=COALESCE(?,unit),
                         gender=COALESCE(?,gender),points=COALESCE(?,points),
                         commission_type=COALESCE(?,commission_type),
                         commission_val=COALESCE(?,commission_val),
                         remark=COALESCE(?,remark),img_main=COALESCE(?,img_main),
                         updated=datetime('now','localtime') WHERE spu=?""",
                      (name,cat,kind,price,tpl,tagp,d.get("unit") or None,gd,
                       int(pts) if pts is not None else None,ct,comv,
                       d.get("remark"),d.get("img_main") or None,spu))
        else:
            # 具名列 —— product 表已按设计稿扩到 21 列,位置参数插入会静默错位
            c.execute("""INSERT INTO product
                (spu,name,category,kind,status,base_price,template,created,updated,cover,
                 tag_price,unit,gender,points,commission_type,commission_val,remark,
                 img_main,img_detail,img_intro)
                VALUES(?,?,?,?,'下架',?,?,datetime('now','localtime'),
                       datetime('now','localtime'),?,?,?,?,?,?,?,?,?,?,?)""",
                      (spu,name,cat,kind,price,tpl,name[:2],
                       round(price*1.12,2),d.get("unit") or "件",d.get("gender") or "女",
                       int(price*100),d.get("commission_type") or "按比例",
                       float(d.get("commission_val") or 10),d.get("remark"),
                       f"/img/{spu}-main.svg",
                       json.dumps({"小程序":[f"/img/{spu}-d{k}.svg" for k in (1,2,3)],
                                   "ipad":[]}, ensure_ascii=False),
                       json.dumps([{"组名":"商品信息","图":[f"/img/{spu}-intro.svg"]}],
                                  ensure_ascii=False)))
            c.execute("""INSERT INTO sku(code,spu,spec,color,size,price,stock,locked,status,
                         spec_code,points,img)
                         VALUES(?,?,?,?,?,?,0,0,'启用',?,?,?)""",
                      (f"{spu}-01",spu,"默认/均码","默认","均码",price,
                       f"GG{spu[-5:]}01",int(price*100),f"/img/{spu}-sku1.svg"))
    # ⚠️ `op_log` 这一条**保留**,但它记的是「这次操作允不允许」那一层
    # (frm='编辑'、too='已保存' 其实不是状态流转,是历史包袱,先不动它);
    # **「改了什么」要落在 edit_log**,见那张表上方的说明。
    log_op(actor,"product",spu,"新建" if new else "编辑","已保存",True,
           "CREATE" if new else "UPDATE",f"{name} · {kind} · ¥{price}",{"role":role})
    # ⚠️ **只 diff「写入真的覆盖了的字段」。**
    # 第一版把表单没提交的字段也算进来,于是日志写出「吊牌价 20160 → 空」
    # 「主图 → 空」—— **而那几个字段根本没被改动**(UPDATE 只写下面这五个)。
    # **一条撒谎的日志比没有日志糟**:查账的人会照着它去追一个从没发生过的改动。
    # 这个列表要和上面那条 UPDATE 的 SET 子句**一模一样**,`edit_log_check` 盯着。
    写入覆盖的字段 = ("name", "category", "kind", "base_price", "template",
                      "tag_price", "unit", "gender", "points",
                      "commission_type", "commission_val", "remark", "img_main")
    新值 = dict(name=name, category=cat, kind=kind, base_price=price, template=tpl)
    # COALESCE 的语义是「没传就保持原值」,所以**没传的字段要拿旧值填进 新值**,
    # 否则 diff 会把它算成「改成空」——**日志又会撒谎**(第一版就是栽在这儿)。
    if old:
        for k, v in (("tag_price", tagp), ("unit", d.get("unit") or None),
                     ("gender", gd), ("points", int(pts) if pts is not None else None),
                     ("commission_type", ct), ("commission_val", comv),
                     ("remark", d.get("remark")), ("img_main", d.get("img_main") or None)):
            新值[k] = dict(old[0]).get(k) if v is None else v
    if new:
        # 创建时**把落库的初值记全** —— 一条只写「创建商品」的日志,
        # 回答不了「这个商品一开始是什么样」,而那正是查改动史的起点。
        # 创建时**把落库的初值记全**(不止上面五个 —— 新建那条 INSERT 写了更多列)。
        # 一条只写「创建商品」的日志,回答不了「这个商品一开始是什么样」,
        # 而那正是查改动史的起点。
        初值 = dict(新值, unit=d.get("unit") or "件", gender=d.get("gender") or "女",
                    tag_price=round(price * 1.12, 2), points=int(price * 100),
                    commission_type=d.get("commission_type") or "按比例",
                    commission_val=float(d.get("commission_val") or 10),
                    remark=d.get("remark"), status="下架")
        log_edit(actor, d.get("actor_no"), "商品", spu, "创建商品",
                 [{"字段": 商品字段名.get(k, k), "改前": "", "改后": str(v)}
                  for k, v in 初值.items() if v not in (None, "")],
                 d.get("source") or "后台")
    else:
        log_edit(actor, d.get("actor_no"), "商品", spu, "编辑商品资料",
                 diff_fields({k: dict(old[0]).get(k) for k in 写入覆盖的字段},
                             新值, 商品字段名),
                 d.get("source") or "后台")
    return dict(ok=True,code="CREATE" if new else "UPDATE",spu=spu,
      reason=(f"商品 {spu} 已创建,默认状态为「下架」,补齐 SKU 与库存后再上架" if new
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

def tpl_impact(code):
    """**改这个模版会影响谁。** 改之前先算出来,别改完再说。"""
    return dict(
        商品=rows("SELECT COUNT(*) c FROM product WHERE template LIKE ?",f"{code}%")[0]["c"],
        量体人次=rows("SELECT COUNT(DISTINCT wearer_id) c FROM measure_rec WHERE tpl=?",
                      code)[0]["c"],
        量体记录=rows("SELECT COUNT(*) c FROM measure_rec WHERE tpl=?",code)[0]["c"])


def save_template(d,actor="魏欣新",role="顾问"):
    """新建或编辑量体模版。

    ⚠️ **编辑一个已经被引用的模版是这块最危险的动作。**
    模版被 N 个商品挂着、被 M 条量体记录用过。从模版里**移掉一个测量项**,
    那些历史记录就指向一个模版已经不包含的项 ——
    **既不算错也不算对,而报表上完全正常**。

    所以移除测量项时:**已经量过的那一项不许移**。
    不是「提示一下还是让你移」—— 移了之后那批记录就悬空了,
    而悬空的数据**没有任何检查会报**(它不违反任何外键)。
    要停用整个模版走「停用」,那是可逆的;移一项是不可逆的。
    """
    if role not in ("总部运营","店长"):
        return dict(ok=False,code="WRONG_ROLE",
                    reason=f"量体模版维护须由总部运营或店长操作,当前角色:{role}")
    code=(d.get("code") or "").strip()
    nm=(d.get("name") or "").strip()
    items=[x.strip() for x in (d.get("items") or "").split(",") if x.strip()]
    if not nm: return dict(ok=False,code="NEED_NAME",reason="模版名称必填")
    if not items: return dict(ok=False,code="NEED_ITEMS",reason="至少选择一个测量项")
    bad=[i for i in items if not rows("SELECT 1 FROM measure_item WHERE code=? AND status='启用'",i)]
    if bad: return dict(ok=False,code="BAD_ITEM",reason=f"测量项不存在或已停用:{'、'.join(bad)}")
    old=rows("SELECT * FROM measure_tpl WHERE code=?",code) if code else []
    if code and not old:
        return dict(ok=False,code="NOT_FOUND",reason=f"量体模版 {code} 不存在")

    if old:
        旧项=[r["item"] for r in rows("SELECT item FROM tpl_item WHERE tpl=? ORDER BY sort",code)]
        移掉=[i for i in 旧项 if i not in items]
        # **已经量过的那一项不许移** —— 移了那批记录就悬空,而悬空不违反任何外键,
        # 没有检查会报。要整个停用走「停用」,那是可逆的。
        挡=[]
        for i in 移掉:
            n=rows("SELECT COUNT(*) c FROM measure_rec WHERE tpl=? AND item=?",code,i)[0]["c"]
            if n:
                nmi=(rows("SELECT name FROM measure_item WHERE code=?",i) or [{"name":i}])[0]["name"]
                挡.append(f"{nmi}({i})已有 {n} 条量体记录")
        if 挡:
            return dict(ok=False,code="ITEM_IN_USE",
                        reason="这几项不能从模版里移掉:"+"；".join(挡)+
                               "。**移掉之后那批记录会指向一个模版不再包含的项** —— "
                               "既不算错也不算对,而报表上完全正常。"
                               "要停用整个模版请走「停用」(可逆),移项不可逆")
        with sqlite3.connect(DB) as c:
            c.execute("UPDATE measure_tpl SET name=?,descr=?,"
                      "updated=datetime('now','localtime') WHERE code=?",
                      (nm,d.get("descr") or "",code))
            c.execute("DELETE FROM tpl_item WHERE tpl=?",(code,))
            for j,it in enumerate(items,1):
                c.execute("INSERT INTO tpl_item VALUES(?,?,?)",(code,it,j))
        ch=[]
        if old[0]["name"]!=nm: ch.append({"字段":"模版名称","改前":old[0]["name"],"改后":nm})
        if (old[0]["descr"] or "")!=(d.get("descr") or ""):
            ch.append({"字段":"描述","改前":old[0]["descr"] or "","改后":d.get("descr") or ""})
        if 旧项!=items:
            ch.append({"字段":"测量项","改前":"、".join(旧项),"改后":"、".join(items)})
        log_edit(actor,d.get("actor_no"),"量体模板",code,"编辑量体模板",ch,
                 d.get("source") or "后台")
        log_op(actor,"measure_tpl",code,"—","编辑",True,"UPDATE",
               f"{nm} · {len(items)} 个测量项",{})
        imp=tpl_impact(code)
        return dict(ok=True,code="UPDATE",
                    reason=f"量体模版 {code} 已更新,含 {len(items)} 个测量项。"
                           f"**影响面**:{imp['商品']} 个商品挂着它,"
                           f"已有 {imp['量体人次']} 人 / {imp['量体记录']} 条量体记录用过")

    n=rows("SELECT COUNT(*) c FROM measure_tpl")[0]["c"]+1
    code=f"MT{n:02d}"
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO measure_tpl VALUES(?,?,?,'启用','60000008',datetime('now','localtime'))",
                  (code,nm,d.get("descr") or ""))
        for j,it in enumerate(items,1):
            c.execute("INSERT INTO tpl_item VALUES(?,?,?)",(code,it,j))
    log_edit(actor,d.get("actor_no"),"量体模板",code,"创建量体模板",
             [{"字段":"模版名称","改前":"","改后":nm},
              {"字段":"测量项","改前":"","改后":"、".join(items)}],
             d.get("source") or "后台")
    log_op(actor,"measure_tpl",code,"—","新建",True,"CREATE",f"{nm} · {len(items)} 个测量项",{})
    return dict(ok=True,code="CREATE",reason=f"量体模版 {code} 已创建,含 {len(items)} 个测量项")


def del_template(d,actor="魏欣新",role="顾问"):
    """删模版 —— **被引用就不许删**,而且要说清被谁引用。

    「删不了」这三个字没用:看的人还要自己去翻是哪几个商品挂着它。
    """
    if role not in ("总部运营","店长"):
        return dict(ok=False,code="WRONG_ROLE",reason=f"量体模版维护须由总部运营或店长操作,当前角色:{role}")
    code=(d.get("code") or "").strip()
    if not rows("SELECT 1 FROM measure_tpl WHERE code=?",code):
        return dict(ok=False,code="NOT_FOUND",reason=f"量体模版 {code} 不存在")
    imp=tpl_impact(code)
    if imp["商品"] or imp["量体记录"]:
        ps=[r["name"] for r in rows("SELECT name FROM product WHERE template LIKE ? LIMIT 3",f"{code}%")]
        return dict(ok=False,code="IN_USE",
                    reason=f"删不了:{imp['商品']} 个商品挂着它"
                           + (f"(例如 {'、'.join(ps)})" if ps else "")
                           + f",已有 {imp['量体记录']} 条量体记录用过。"
                             f"**要停用请走「停用」** —— 停用是可逆的,删是不可逆的")
    with sqlite3.connect(DB) as c:
        c.execute("DELETE FROM tpl_item WHERE tpl=?",(code,))
        c.execute("DELETE FROM measure_tpl WHERE code=?",(code,))
    log_edit(actor,d.get("actor_no"),"量体模板",code,"删除量体模板",
             [{"字段":"整条","改前":code,"改后":"(已删除)"}],d.get("source") or "后台")
    log_op(actor,"measure_tpl",code,"—","删除",True,"DELETE","没有任何引用",{})
    return dict(ok=True,code="DELETE",reason=f"量体模版 {code} 已删除(它没有被任何商品或量体记录引用)")

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
    # ⚠️ **要把 advisor_no 一起取出来** —— 名字由 `填顾问名()` 现取,
    # 而它认的是工号。不取的话删列之后这一栏会静默变空。
    rs=rows("""SELECT id,name,phone,lifecycle,shop,advisor_no,level,order_cnt,
               paid_amount,last_interact,idle_days,amount_12m,archived FROM customer""")
    填顾问名(rs)
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
      # ⚠️ **筛选项也要从员工表来,不能读那一列。**
      # 实测:把名字列抹空之后这个下拉**直接变空**,而页面照常打开、
      # 表格照常有行 —— 少一个筛选框没有人会去跑测试。
      # 只列**真的有客户挂着的**顾问,不是全部员工 ——
      # 一个筛出 0 条的选项比没有这个选项更糟。
      advisor=[x for x in (
          (lambda nm: [f"{nm[no][1]} {nm[no][0]}" if nm[no][1] else nm[no][0]
                       for no in [r["v"] for r in rows(
                           "SELECT DISTINCT advisor_no v FROM customer "
                           "WHERE advisor_no IS NOT NULL AND advisor_no!='' ORDER BY v")]
                       if no in nm])(_花名册())) if x],
      level=[r["v"] for r in rows("SELECT DISTINCT level v FROM customer ORDER BY v")])
    return d

def appt_list_q(q):
    kw=(q.get("q") or [""])[0].strip(); stt=(q.get("status") or [""])[0]; sh=(q.get("shop") or [""])[0]
    rs=填顾问名(rows("""SELECT a.*, c.name cname FROM appointment a
               LEFT JOIN customer c ON a.customer_id=c.id"""))
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
    binds=rows("SELECT kind,target_id,target_name,ts FROM member_bind WHERE customer_id=? ORDER BY kind",cid)
    plog=rows("""SELECT behavior,delta,balance,reason,actor,ts FROM points_log
                 WHERE customer_id=? ORDER BY id DESC LIMIT 20""",cid)
    lv=rows("SELECT * FROM level_cfg WHERE name=?",c.get("level"))
    return dict(customer=c,appts=appts,followups=fus,deposits=deps,logs=logs,
                measures=measure_of(cid),binds=binds,points_log=plog,
                level_cfg=lv[0] if lv else None)

def lifecycle_page(sel=None):
    types=["潜在","新客","活跃","高价值","忠诚","休眠","潜在流失","流失"]  # 展示顺序,不是优先级
    cnt={r["lifecycle"]:r["n"] for r in rows("SELECT lifecycle,COUNT(*) n FROM customer GROUP BY lifecycle")}
    cur=sel or types[0]
    cs=rows("""SELECT id,name,phone,lifecycle,shop,advisor_no,level,order_cnt,
               paid_amount,last_interact,
               idle_days,amount_12m,orders_12m,quarters_12m,matched,manual_lc,manual_at
               FROM customer WHERE lifecycle=? ORDER BY (manual_lc IS NULL), id LIMIT 60""",cur)
    填顾问名(cs)
    for c in cs:
        p=c["phone"] or ""; c["phone"]=p[:3]+"****"+p[-4:] if len(p)>=11 else p
    # 判定规则和优先级都来自 knowledge/lifecycle.py —— 这里原来是第二份手抄件。
    # 页面写「优先级 3」而实际按第 4 位算,这种漂不会报错,只会让运营看不懂。
    RULE, PRI = _lc.RULES, _lc.PRIORITY
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
    # ⚠️ 这里和上面两处不同:SQL 写的是 a.*,**不会报 no such column**,
    # 要等取值时才抛 KeyError —— 同一个根因,两种长相。
    填顾问名([a])
    logs=[dict(ts=a["start_ts"],who=a.get("advisor") or a.get("advisor_no") or "系统",
               title="新建预约",src="后台")]
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
        if _u(unquote(urlparse(self.path).path)) == "/api/me":
            u = _me(self)
            return self._send(u or {"error": "没登录"}, 200 if u else 401)
        # 四个智能体页面已迁到独立站点(agentsite/,端口 8770)。
        # 后台只留一个入口链接,接口仍对外提供 —— 新站的 /api/* 反代过来。
        if p in ("/","/index.html"):
            b=open(os.path.join(HERE,"web","index.html"),"rb").read()
            self.send_response(200); self.send_header("content-type","text/html; charset=utf-8")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if p.startswith("/img/") and p.endswith(".svg"):
            import img as _img
            stem=p[len("/img/"):-4]; spu,_,variant=stem.rpartition("-")
            # **有出好的真图就用真图,没有才现画示意图。**
            # 出图是一批一批来的,所以这一层必须按「这一张有没有」判,不能按「这个功能开没开」——
            # 按开关判的话,开了之后没出图的商品会开天窗,而页面不会报错,只是空着。
            _gen=os.path.join(HERE,"static","img")
            for _ext,_ct in ((".png","image/png"),(".jpg","image/jpeg"),
                             (".jpeg","image/jpeg"),(".webp","image/webp")):
                _f=os.path.join(_gen,stem+_ext)
                if os.path.isfile(_f):
                    b=open(_f,"rb").read()
                    self.send_response(200)
                    # ⚠️ 地址结尾是 .svg 而发出去的是 png —— **看 content-type 的是浏览器,不是后缀**。
                    # 这么做是为了不动库里已经存着的那几千条图片地址(product.img_main 等)。
                    self.send_header("content-type",_ct)
                    self.send_header("cache-control","max-age=3600")
                    self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            b=_img.render(spu,variant).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type","image/svg+xml; charset=utf-8")
            self.send_header("cache-control","max-age=3600")
            self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        # 打版图:现画不存盘 —— 版型和号型一改,图必须跟着改。
        # 存成文件的话,库里改了尺寸而图还是旧的,**而旧图和新图长得一模一样**,
        # 车间照着旧图裁布才发现。/pattern/PT04-M.svg,也收款号(/pattern/lxys_xxx-M.svg)。
        if p.startswith("/pattern/") and p.endswith(".svg"):
            import sys as _sys
            _sys.path.insert(0, os.path.join(HERE,"..","tools","patterndraw"))
            import draft as _draft
            stem=p[len("/pattern/"):-4]; key,_,size=stem.rpartition("-")
            try:
                svg,_nm,_warn=_draft.render(key,size or "M")
            except Exception as e:
                b=str(e).encode("utf-8")
                self.send_response(404); self.send_header("content-type","text/plain; charset=utf-8")
                self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            b=svg.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type","image/svg+xml; charset=utf-8")
            # 警告也带在响应头里 —— 只画在图上的话,调接口的人看不到
            if _warn:
                self.send_header("x-draft-warnings",str(len(_warn)))
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
        # 这两条必须放在 Q 赋值**之后**。第一版插在 do_GET 开头,
        # 报的是 `UnboundLocalError: Q`,而不是「路由写错了」——
        # **错误信息指向的是症状发生的地方,不是原因所在的地方。**
        if p == "/api/my-tasks":
            return self._send(my_tasks(_me(self), (Q.get("status") or [None])[0]))
        if p == "/api/my-staff":
            return self._send({"rows": my_staff(_me(self))})
        if p == "/api/task-types":
            # 类型清单**由后端出**。界面自己写一份的话,加一个类型就要改两处,
            # 而漏改的那一处不会报错,只会少一个选项。
            import tasktypes as _tt
            return self._send({"rows": _tt.catalog()})
        if p == "/api/task-ref":
            # 填完单号立刻回一句「这是谁的单」。**让人在提交前就看见带出来的客户** ——
            # 提交后才发现挂错单,任务已经派下去了。
            import tasktypes as _tt
            _k = _tt.ref_of((Q.get("type") or [""])[0])
            _ok, _cid, _sh, _dsc = _tt.resolve_ref(_k, (Q.get("id") or [""])[0], rows)
            return self._send(dict(ok=_ok, customer_id=_cid, shop=_sh, desc=_dsc))
        if p == "/api/activities":
            return self._send({"rows": rows(
                "SELECT code,name,kind,status,shop FROM activity "
                "WHERE status='进行中' ORDER BY code")})
        if p.startswith("/api/task-file/"):
            # 取图。**权限跟着任务走** —— 能看这条任务的人才能看它的图。
            _u4 = _me(self)
            if not _u4: return self._send({"error": "请先登录"}, 401)
            try: _fid = int(p.rsplit("/", 1)[1])
            except ValueError: return self._send({"error": "文件号不对"}, 400)
            import files as _f
            _own = rows("SELECT s.assignee_no,s.shop FROM schedule_file f "
                        "JOIN schedule s ON s.id=f.schedule_id WHERE f.id=?", _fid)
            if not _own: return self._send({"error": "没有这个附件"}, 404)
            _o = _own[0]
            if not (_o["assignee_no"] == _u4["no"] or
                    (_u4.get("role") in MANAGER_ROLES and
                     (_u4["role"] == "总部运营" or _o["shop"] == _u4.get("shop")))):
                return self._send({"error": "这个附件不归你"}, 403)
            b4 = _f.blob(_fid)
            if not b4: return self._send({"error": "附件文件丢了"}, 404)
            self.send_response(200)
            self.send_header("content-type", b4[0])
            self.send_header("cache-control", "max-age=86400")
            self.send_header("content-length", str(len(b4[1])))
            self.end_headers(); self.wfile.write(b4[1]); return
        if p == "/api/unassigned":
            # 待分配池。顾问看不到 —— 他不负责分活,给他看只会让他以为该自己认领。
            _u2 = _me(self)
            if not _u2: return self._send({"error": "请先登录"}, 401)
            if _u2.get("role") not in MANAGER_ROLES:
                return self._send({"rows": [], "note": "待分配由店长处理"})
            import booking as _bk
            return self._send({"rows": _bk.unassigned(
                None if _u2["role"] == "总部运营" else _u2.get("shop"))})
        if p.startswith("/api/ops-"):
            # 智能运维平台的读接口。队列/积压/健康度都在 ops.py 里算,
            # 这里只负责转发 —— 路由层不放业务规则,SLA 改了不用翻两个文件。
            import ops as _ops
            if p=="/api/ops-queue":   return self._send(dict(rows=_ops.queue((Q.get("state") or [None])[0])))
            if p=="/api/ops-backlog": return self._send(_ops.backlog())
            if p=="/api/ops-health":  return self._send(_ops.health())
            if p=="/api/ops-detail":
                d=_ops.get_triage((Q.get("id") or [None])[0])
                return self._send(d or dict(error="没有这条研判"), 200 if d else 404)
            return self._send(dict(error="no ops route"),404)
        # ── 用户生命周期 ────────────────────────────────────────────
        # 注意别和上面的 /api/lifecycle 混了:那个是**会员**生命周期(新客/沉默/流失),
        # 这个是**着装人**的身体生命周期(长个儿、该复量、场景倒推)。
        # 两个都叫「生命周期」是业务里的真实歧义,所以路径分开写清楚。
        # ── 面料库 ──────────────────────────────────────────────────
        # 45 条材质 + 135 条物料 + 相容矩阵,原来一个页面都没展示 ——
        # **定制业务里客户第一个摸的是布,而系统里它一直只是个下拉选项。**
        if p=="/api/fabrics":
            import api as _api
            mats=_api._rows("""SELECT code,name,alias,brief,detail,fit,src_type
                               FROM craft WHERE cat='材质' ORDER BY code""")
            out=[]
            for m in mats:
                phy=_api._rows("""SELECT width_cm,price,loss_rate,lead_days,stock_qty,unit
                                  FROM material WHERE name=? OR name LIKE ?
                                  ORDER BY code LIMIT 1""", m["name"], f"%{m['name']}%")
                cb=_api._rows("""SELECT verdict,count(*) n FROM craft_combo
                                 WHERE material=? GROUP BY verdict""", m["code"])
                v={r["verdict"]:r["n"] for r in cb}
                d=dict(m); d.pop("detail",None)
                d.update(工艺=dict(可=v.get("可",0),需评估=v.get("需评估",0),
                                  不可=v.get("不可",0),未定义=v.get("未定义",0)),
                         规格=(dict(幅宽=phy[0]["width_cm"],单价=phy[0]["price"],
                                   损耗=phy[0]["loss_rate"],备料天=phy[0]["lead_days"],
                                   库存=phy[0]["stock_qty"],单位=phy[0]["unit"])
                              if phy else None),
                         细节=[x.strip() for x in (m["detail"] or "").split("/") if x.strip()])
                out.append(d)
            return self._send(dict(rows=out,
                说明="来源等级 public 可直接对客户说;scale 要注明「行业参考」;"
                     "demo 是内部演示数据,**不可作为对客户的承诺**。"
                     "「备料天」是下单到面料到位的天数,现货为 1–3 天。"))
        if p=="/api/wearers":
            import api as _api, ops as _o
            rl=_o.recheck_list()
            due={x["id"]:x for x in rl["该复量"]}
            _out=[]   # 别叫 rows —— 模块级已经有个 rows() 函数,遮蔽了后面就调不到
            for w in _api._rows("SELECT * FROM wearer ORDER BY customer_id,id"):
                d=_api.get_wearer(wearer_id=w["id"])["着装人"][0]
                d["该复量"]=w["id"] in due
                d["超期天数"]=(due[w["id"]]["已过"]-due[w["id"]]["上限"]) if w["id"] in due else None
                _out.append(d)
            return self._send(dict(rows=_out, 需人工确认=rl["需人工确认"],
                                   说明=rl["说明"]))
        if p=="/api/wearer-plan":
            import api as _api
            from urllib.parse import parse_qs as _pq
            q={k:[_u(unquote(x)) for x in v] for k,v in _pq(urlparse(self.path).query).items()}
            g=lambda k,d=None:(q.get(k) or [d])[0]
            cs=[x for x in (g("c") or "").split(",") if x]
            return self._send(_api.plan_for_event(g("w"), g("d"), g("p","PT04"),
                                                  g("m","云锦"), cs, g("s","局部")))
        if p=="/api/fit-customers": return self._send(backend.fit_customers())
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
        if p.startswith("/api/craft-doc/"): return self._send(craft_doc(p.split("/api/craft-doc/")[1]))
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
        if p=="/api/customers": return self._send(填顾问名(rows(
            "SELECT id,name,phone,shop,advisor_no,lifecycle,level,order_cnt,"
            "paid_amount FROM customer ORDER BY id LIMIT 200")))
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
                                 kf=body.get("kf") or [],ps=body.get("ps") or [],color=body.get("color"),
                                 pattern=body.get("pt"),size=body.get("size"),
                                 need_date=body.get("need_date"),
                                 scope=body.get("scope") or "局部",
                                 workers=int(body.get("workers") or 2))
            return self._send(dict(can_save=ok,issues=iss))
        if p=="/api/scheme-save":
            # 这里才是闸门。前端 disabled 只是体验 —— 绕过前端直接调这个接口,一样拦。
            import scheme as _sch
            ok,iss=_sch.validate(xz=body.get("xz"),mt=body.get("mt"),
                                 kf=body.get("kf") or [],ps=body.get("ps") or [],color=body.get("color"),
                                 pattern=body.get("pt"),size=body.get("size"),
                                 need_date=body.get("need_date"),
                                 scope=body.get("scope") or "局部",
                                 workers=int(body.get("workers") or 2))
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
        if p=="/api/ops-triage":
            # 智能体站跑完一条,把研判结果寄存到后台。**数据的家在后台**,
            # 站上不复制一份库 —— 否则两边一定会漂。
            import ops as _ops
            try:
                tid=_ops.save_triage(body.get("task_id"), body.get("bp"), body.get("case"),
                                     body.get("text") or "", body.get("trajectory") or [],
                                     cost=body.get("cost"), latency_ms=body.get("latency_ms"),
                                     model=body.get("model"), usage=body.get("usage"),
                                     guard_blocked=body.get("guard_blocked"),
                                     guard_violations=body.get("guard_violations"),
                                     answer_turns=body.get("answer_turns") or 1)
            except Exception as e:
                return self._send(dict(error=f"{type(e).__name__}: {e}"[:200]),400)
            return self._send(dict(ok=True, triage_id=tid, row=_ops.get_triage(tid)))
        if p=="/api/ops-reparse":
            # 解析规则改了之后重算历史条目。不重新调模型 —— ai_text 全文都存着。
            import ops as _ops
            f=_ops.reparse(only_failed=not body.get("all"))
            return self._send(dict(ok=True, 重算=len(f), rows=f))
        if p=="/api/ops-resolve":
            # 值班同学销账。改判会回流评测集 —— 这是整套东西唯一的自我改进通路。
            import ops as _ops
            try:
                return self._send(_ops.resolve(
                    body.get("triage_id"), body.get("decision"), body.get("handler") or "值班同学",
                    root_cause=body.get("root_cause"), action=body.get("action"),
                    note=body.get("note")))
            except Exception as e:
                return self._send(dict(error=f"{type(e).__name__}: {e}"[:200]),400)
        if p=="/api/fit":
            return self._send(backend.kb_fit(body.get("customer"),body.get("pattern")))
        if p=="/api/scheme-lead":
            import scheme as _sc
            return self._send(_sc.lead(body.get("xz"),body.get("mt"),body.get("kf"),
                                       body.get("pt"),body.get("size"),
                                       body.get("scope") or "局部",
                                       int(body.get("workers") or 2),
                                       body.get("need_date")))
        if p=="/api/scheme-cost":
            import scheme as _sc
            return self._send(_sc.estimate(body.get("xz"),body.get("mt"),body.get("kf"),
                                           body.get("pt"),body.get("size")))
        if p=="/api/judge":
            # 给「单条试跑」页用:它跑智能体,判分和标注答案留在后台(数据的家在这)。
            # 依旧遵守隔离:truth 只在**跑完之后**读,绝不进模型上下文。
            _ev=_eval(); case=(body.get("case") or "").strip(); txt=body.get("text") or ""
            tr=_truths().get(case)
            if not tr: return self._send(dict(error=f"没有 {case} 的标注答案"),404)
            ok,why=_ev.hit(txt,tr.get("root_cause",""),case)
            return self._send(dict(passed=ok,judge=why,truth=dict(
                root_cause=tr.get("root_cause"),expected_action=tr.get("expected_action"),
                expected_evidence=tr.get("expected_evidence"),note=tr.get("note"))))
        if p=="/api/chat":
            sys.path.insert(0, os.path.join(HERE,"..","agent"))
            import chat as _chat
            q=(body.get("q") or "").strip()
            if not q: return self._send(dict(error="问题是空的"),400)
            hist=[(m["role"],m["content"]) for m in (body.get("history") or [])
                  if m.get("role") in ("user","assistant") and isinstance(m.get("content"),str)][-8:]
            try: return self._send(_chat.ask(q, hist))
            except Exception as e: return self._send(dict(error=str(e)[:300]),500)
        if p=="/api/login":
            tok, r = auth.login(body.get("login_name"), body.get("password"))
            if not tok:
                # **登录失败不写日志正文**(别把口令或工号猜测留在台账里),只记一条计数
                return self._send(dict(ok=False, reason=r), 401)
            log_op(r["name"], "staff", r["no"], "—", "已登录", True, "LOGIN",
                   f"{r['name']}({r['role']} · {r['shop']})登录", {})
            # HttpOnly:JS 读不到这个 cookie,XSS 也偷不走
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("set-cookie",
                             f"lx_token={tok}; Path=/; HttpOnly; SameSite=Lax; Max-Age={12*3600}")
            data = _j.dumps(dict(ok=True, **r), ensure_ascii=False).encode()
            self.send_header("content-length", str(len(data))); self.end_headers()
            self.wfile.write(data); return
        if p=="/api/logout":
            ck = self.headers.get("cookie") or ""
            for part in ck.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "lx_token": auth.logout(v)
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("set-cookie", "lx_token=; Path=/; HttpOnly; Max-Age=0")
            data = b'{"ok":true}'
            self.send_header("content-length", str(len(data))); self.end_headers()
            self.wfile.write(data); return
        if p=="/api/combo-resolve":
            return self._send(resolve_combo(body, _actor_of(self), _role_of(self)))
        if p=="/api/task-assign": return self._send(assign_task(body, _me(self)))
        if p=="/api/task-finish": return self._send(finish_task(body, _me(self)))
        if p=="/api/task-dispatch": return self._send(dispatch(body, _me(self)))
        if p=="/api/task-reassign": return self._send(reassign(body, _me(self)))
        if p=="/api/task-file":
            # 单独补传附件(派单后想起来还有张图)。只有**看得见这条任务的人**能传:
            # 派给他的顾问,或者本店店长。
            _u3 = _me(self)
            if not _u3: return self._send(dict(ok=False, reason="请先登录"), 401)
            import files as _f
            _t3 = rows("SELECT * FROM schedule WHERE id=?", body.get("id") or "")
            if not _t3: return self._send(dict(ok=False, reason="没有这条任务"))
            _t3 = _t3[0]
            _mine = _t3.get("assignee_no") == _u3["no"]
            _boss = (_u3.get("role") in MANAGER_ROLES and
                     (_u3["role"] == "总部运营" or _t3.get("shop") == _u3.get("shop")))
            if not (_mine or _boss):
                return self._send(dict(ok=False, reason="这条任务不归你"), 403)
            ok4, why4 = _f.save(_t3["id"], body.get("kind") or "派单",
                                body.get("name"), body.get("data"), _u3["name"])
            return self._send(dict(ok=ok4, reason=why4))
        if p=="/api/book":
            # **唯一一个不要登录的写接口。** 客户没有员工账号,
            # 要求他登录等于要求他先注册,人不会为了约个量体去注册。
            # 敞开的代价由 booking.book() 自己的三道闸兜(格式/频次/派给谁不由请求决定)。
            import booking as _bk
            return self._send(_bk.book(body))
        if p=="/api/customer-create":
            return self._send(create_customer(body, _actor_of(self), _role_of(self)))
        if p.startswith("/api/customer-update/"):
            return self._send(update_customer(p.split("/api/customer-update/")[1],body,
                                              role=_role_of(self)))
        if p=="/api/approval-apply":
            return self._send(apply_approval(body.get("kind"),body.get("target"),
                body.get("payload") or {},body.get("note"),role=_role_of(self)))
        if p=="/api/approval-decide":
            return self._send(decide_approval(body.get("id"),body.get("to"),body.get("note"),
                                              role=_role_of(self)))
        if p=="/api/import":
            return self._send(import_customers(body.get("text"),role=_role_of(self),
                                               dry=bool(body.get("dry",True))))
        if p=="/api/appt-create":
            return self._send(create_appointment(body, _actor_of(self), _role_of(self)))
        if p=="/api/followup-create":
            return self._send(create_followup(body, _actor_of(self)))
        if p=="/api/download-create":
            return self._send(create_download(body.get("kind"),body.get("filters")))
        if p=="/api/product-save":
            return self._send(save_product(body,role=_role_of(self)))
        if p=="/api/block-save": return self._send(save_block(body))
        if p=="/api/template-save": return self._send(save_template(body,role=body.get("role") or "顾问"))
        if p=="/api/template-del": return self._send(del_template(body,role=body.get("role") or "顾问"))
        if p=="/api/mitem-save": return self._send(save_measure_item(body,role=body.get("role") or "顾问"))
        if p=="/api/syscode-save":
            return self._send(save_syscode(body,role=_role_of(self)))
        if p=="/api/content-save": return self._send(save_content(body))
        if p=="/api/toggle":
            return self._send(toggle(body.get("table"),body.get("key"),body.get("val")))
        if p=="/api/transfer":
            ids=body.get("ids") or []; adv=body.get("advisor"); role=_role_of(self)
            if role not in ("店长","总部运营"):
                log_op("魏欣新","customer","|".join(ids[:3]),"—","转移",False,"WRONG_ROLE",
                       f"客户转移须由店长及以上操作,当前角色:{role}",{})
                return self._send(dict(ok=False,code="WRONG_ROLE",
                    reason=f"客户转移须由店长及以上操作,当前角色:{role}"))
            with sqlite3.connect(DB) as c:
                _adv_no = 顾问工号(adv)
                for i in ids: c.execute("UPDATE customer SET advisor_no=? WHERE id=?",(_adv_no,i))
                c.executemany("UPDATE appointment SET advisor_no=? WHERE customer_id=? AND status='已预约'",
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
                                            body.get("note"),role=_role_of(self)))
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
