#!/usr/bin/env python3
"""状态流转引擎 —— 按澜绣云裳 PRD 的状态机校验每一次流转。

规则来源:data/answer-set-lanxiu/state-machines.json + 产品文档 7.2-7.4
非法流转一律拒绝并给出可读理由,拒绝本身也要留痕。
"""
import json, os
HERE=os.path.dirname(os.path.abspath(__file__))
SM={m["id"]:m for m in json.load(open(os.path.join(HERE,"..","data","answer-set-lanxiu",
     "state-machines.json")))["machines"]}

# 产品文档 7.2:进入即产生不可逆副作用的状态
IRREVERSIBLE={"已付","退款处理中","已退","待发货","待收货","已完成","已关闭","已锁定","已失效",
              "已到店","爽约","已过期","完结","方案确认中","已确认","无效","取消"}
RETRYABLE={"退款失败"}
# 客户合并状态机(后台 PRD 6.2:由店长发起、总部运营审批)
MERGE_SM=dict(id="bk-merge",name="客户合并",type="event",
  states=["待核验","待总部审批","已合并","已核验","已驳回"],
  edges=[["待核验","待总部审批"],["待核验","已核验"],
         ["待总部审批","已合并"],["待总部审批","已驳回"],["已驳回","待核验"]],
  terminal=["已合并","已核验"])
SM["bk-merge"]=MERGE_SM
# 高风险操作审批单(后台 PRD 第 8 章:等级调整、积分调整、客户批量转移均需审计与审批)
SM["bk-approval"]=dict(id="bk-approval",name="审批单",type="event",
  states=["待审批","已通过","已驳回","已撤回"],
  edges=[["待审批","已通过"],["待审批","已驳回"],["待审批","已撤回"]],
  terminal=["已通过","已驳回","已撤回"])
APPROVAL_ROLE={("待审批","已通过"):"总部运营",("待审批","已驳回"):"总部运营"}
# 营销活动:未开始 → 进行中 → 已结束;未开始/进行中 可取消
SM["bk-activity"]=dict(id="bk-activity",name="营销活动",type="event",
  states=["未开始","进行中","已结束","已取消"],
  edges=[["未开始","进行中"],["进行中","已结束"],["未开始","已取消"],["进行中","已取消"]],
  terminal=["已结束","已取消"])
# 页面:草稿 ⇄ 已发布
SM["bk-page"]=dict(id="bk-page",name="页面",type="event",
  states=["草稿","已发布"],edges=[["草稿","已发布"],["已发布","草稿"]],terminal=[])
# 下载任务:生成中 → 已完成/失败;已完成 → 已过期
SM["bk-download"]=dict(id="bk-download",name="下载任务",type="event",
  states=["生成中","已完成","失败","已过期"],
  edges=[["生成中","已完成"],["生成中","失败"],["已完成","已过期"],["失败","生成中"]],
  terminal=["已过期"])
# 商品上下架(后台无独立 PRD 章节,按标签状态机形态定义;下架不影响历史订单)
SM["bk-product"]=dict(id="bk-product",name="商品",type="event",
  states=["上架","下架"],edges=[["上架","下架"],["下架","上架"]],terminal=[],
  notes=["下架后不可新增下单,历史订单与库存记录保留"])
MERGE_ROLE={("待核验","待总部审批"):"店长",("待总部审批","已合并"):"总部运营",
            ("待总部审批","已驳回"):"总部运营",("待核验","已核验"):"店长"}

# 需要审批链的流转(后台 PRD 6.1 / 5.x)
APPROVAL={("bk-deposit","已付","退款审批中"):"须由客服或店长发起、店长复核;单笔≥1000元增加财务复核"}
# 需要幂等号的流转
IDEMPOTENT={("bk-deposit","退款审批中","退款处理中"),("bk-deposit","退款失败","退款处理中")}

def machine(mid): return SM.get(mid)

def check(mid, frm, to, ctx=None):
    """返回 (allowed, code, reason)。ctx 可含 amount / approved_by / idem_key / retries"""
    ctx=ctx or {}
    m=SM.get(mid)
    if not m: return False,"NO_MACHINE",f"未知状态机 {mid}"
    if m["type"]!="event": return False,"ALGORITHMIC",\
        f"「{m['name']}」是算法型状态机,由每日重算决定,不接受流转请求"
    if frm not in m["states"]: return False,"BAD_FROM",f"「{frm}」不是「{m['name']}」的合法状态"
    if to  not in m["states"]: return False,"BAD_TO",  f"「{to}」不是「{m['name']}」的合法状态"

    edges={tuple(e) for e in m["edges"]}
    if mid=="bk-approval" and (frm,to) in edges:
        need=APPROVAL_ROLE.get((frm,to))
        if need and ctx.get("role")!=need:
            return False,"WRONG_ROLE",f"审批须由{need}操作,当前角色:{ctx.get('role') or '未指定'}"
        return True,"OK",""
    if mid=="bk-merge" and (frm,to) in edges:
        need=MERGE_ROLE.get((frm,to))
        if need and ctx.get("role")!=need:
            return False,"WRONG_ROLE",f"「{frm}」→「{to}」须由{need}操作,当前角色:{ctx.get('role') or '未指定'}"
        return True,"OK",""
    if (frm,to) in edges:
        # 合法边,再查附加约束
        key=(mid,frm,to)
        if key in APPROVAL and not ctx.get("approved_by"):
            return False,"NEED_APPROVAL",APPROVAL[key]
        if key in APPROVAL and ctx.get("amount",0)>=1000 and "财务" not in str(ctx.get("approved_by","")):
            return False,"NEED_FINANCE",f"单笔 ¥{ctx['amount']:,.2f} ≥ 1000,须增加财务复核"
        if mid=="bk-task" and to=="完结" and not (ctx.get("summary") or "").strip():
            return False,"NEED_SUMMARY","日程任务完成需填写总结"
        if mid=="bk-task" and to=="取消" and not (ctx.get("reason") or "").strip():
            return False,"NEED_REASON","日程任务取消需填写原因"
        if (mid,frm,to) in IDEMPOTENT and not ctx.get("idem_key"):
            return False,"NEED_IDEM","资金类流转必须携带幂等号"
        if ctx.get("retries",0)>=3 and to=="退款处理中":
            return False,"RETRY_LIMIT","已达重试上限 3 次,须转财务人工处理"
        return True,"OK",""

    # 非法边,给出具体是哪一类
    if frm in m.get("terminal",[]):
        return False,"TERMINAL",f"「{frm}」是终态,任何续流转都必须拒绝并留审计"
    if (to,frm) in edges:
        if frm in RETRYABLE: return True,"RETRY",f"「{frm}」→「{to}」是重试路径,允许"
        if frm in IRREVERSIBLE:
            return False,"IRREVERSIBLE",\
              f"进入「{frm}」已产生资金/资源/不可逆记录,回退到「{to}」会造成两边不一致"
        return False,"REVERSE",f"「{frm}」→「{to}」是 {to}→{frm} 的反向流转,未定义"
    # 是否跳跃
    mid_states=[x for x in m["states"] if (frm,x) in edges and (x,to) in edges]
    if mid_states:
        return False,"SKIP",f"不得从「{frm}」直接跳到「{to}」,跳过了「{'/'.join(mid_states)}」的校验与记账"
    return False,"UNDEFINED",f"「{m['name']}」未定义 {frm} → {to} 的流转"

if __name__=="__main__":
    cases=[("bk-deposit","已付","退款审批中",{}),
           ("bk-deposit","已付","退款审批中",{"approved_by":"店长","amount":500}),
           ("bk-deposit","已付","退款审批中",{"approved_by":"店长","amount":3000}),
           ("bk-deposit","已付","退款审批中",{"approved_by":"店长+财务","amount":3000}),
           ("bk-deposit","退款审批中","退款处理中",{}),
           ("bk-deposit","退款审批中","退款处理中",{"idem_key":"IDEM-x"}),
           ("bk-deposit","已付","已退",{}),
           ("bk-deposit","已退","退款处理中",{}),
           ("bk-deposit","退款失败","退款处理中",{"idem_key":"IDEM-x"}),
           ("bk-deposit","退款失败","退款处理中",{"idem_key":"IDEM-x","retries":3}),
           ("bk-appt","已完成","已预约",{}),
           ("bk-appt","已预约","已完成",{}),
           ("bk-lifecycle","活跃","高价值",{})]
    EXPECT=["NEED_APPROVAL","OK","NEED_FINANCE","OK","NEED_IDEM","OK",
            "UNDEFINED","TERMINAL","OK","RETRY_LIMIT","TERMINAL","SKIP","ALGORITHMIC"]
    print("状态流转引擎自测\n"+"="*76)
    bad=0
    for (mid,f,t,ctx),exp in zip(cases,EXPECT):
        ok,code,why=check(mid,f,t,ctx)
        hit = code==exp
        if not hit: bad+=1
        print(f"{'✅' if hit else '❗'} [{code:13s}] {SM[mid]['name']}: {f} → {t}"
              + ("" if hit else f"   期望 {exp}"))
    # 合并状态机的角色校验
    for f,t,role,exp in [("待核验","待总部审批","顾问","WRONG_ROLE"),
                         ("待核验","待总部审批","店长","OK"),
                         ("待总部审批","已合并","店长","WRONG_ROLE"),
                         ("待总部审批","已合并","总部运营","OK")]:
        ok,code,why=check("bk-merge",f,t,{"role":role})
        hit=code==exp
        if not hit: bad+=1
        print(f"{'✅' if hit else '❗'} [{code:13s}] 客户合并({role}): {f} → {t}")
    print("="*76)
    print(f"{'✅ 全部符合预期' if not bad else f'❌ {bad} 项与预期不符'}")
    import sys; sys.exit(1 if bad else 0)
