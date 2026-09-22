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
# ── 订单(设计稿 10 档)─────────────────────────────────────────────
# **为什么建在设计稿那 10 档上,而不是 PRD 的 6 档:**
# 产品文档第 7.5 节记着一个已知的口径冲突 —— 设计稿 10 个页签里有 4 个在 PRD 中
# 无对应状态,而 PRD 的「方案确认中」在设计稿里没有任何页签承载。
# 照哪一份写都会和另一份矛盾。
#
# 库里两套口径是**同时存的**(status 10 档 / prd_status 6 档),
# 而 member_order_check 里有一张映射表把它们钉在一起。
# 所以:**流转只在 status 上定义,prd_status 由映射派生** ——
# 让两边各自流转,就是同一个事实两个来源,而这个项目在这上面栽过五次。
#
# 主链路(定制品):待付款 → 待审核 → 待生产 → 生产中 → 已生产 → 待发货 → 已发货 → 待完成 → 完成
# 标品少两档(不用审方案、不用生产):待付款 → 待发货 → 已发货 → 待完成 → 完成
# 取消:只有**还没进生产**的能取消 —— 开工之后料已经裁了,取消是退款问题不是状态问题
SM["bk-order"]=dict(id="bk-order",name="订单",type="event",
  states=["待确认","待付款","待审核","待生产","生产中","已生产","待发货","已发货","待完成","完成","取消"],
  edges=[# 定制品(业务 2026-09-22):先开单停在「待确认」→ 每一件量下单量体并绑上 → 确认下单。
         # **付款默认在确认时已完成**,所以确认后跳过「待付款」直接进「待审核」;没定的直接取消。
         ["待确认","待审核"],["待确认","取消"],
         ["待付款","待审核"],            # 定制品老路径(系统接管下单之前的单):付了款先审方案
         ["待付款","待发货"],            # 标品:付了款直接备货
         ["待审核","待生产"],
         ["待生产","生产中"],
         ["生产中","已生产"],
         ["已生产","待发货"],
         ["待发货","已发货"],
         ["已发货","待完成"],
         ["待完成","完成"],
         # 取消只在开工前 —— 「生产中」及之后不给取消这条边
         ["待付款","取消"],["待审核","取消"],["待生产","取消"]],
  terminal=["完成","取消"],
  notes=["取消只在开工前:进了「生产中」料已经裁了,再要退是退款流程,不是改状态",
         "prd_status 由 status 派生,不单独流转 —— 两套口径各自流转就是两个来源"])

# 维保 / 返修(业务 2026-09-22:店长判责、顾客同意才开工、修好回店再走一遍 6 位码签收)。
# 状态沿用维保原有的六档,不加新状态;取消只在开工前。
SM["bk-maintain"]=dict(id="bk-maintain",name="返修单",type="event",
  states=["待确认","待入库","待处理","处理中","待签收","已完成","取消"],
  edges=[["待确认","待入库"],            # 店长判完责(判给顾客的:录了费用、顾客同意了)
         ["待入库","待处理"],            # 衣服收回来了
         ["待处理","处理中"],            # 送修
         ["处理中","待签收"],            # 修好回店
         ["待签收","已完成"],            # 顾客试穿合身、输码核验
         ["待确认","取消"],["待入库","取消"]],
  terminal=["已完成","取消"],
  notes=["判责和收费由店长确认;判给顾客的先录预估费用、记下顾客同意再开工 —— 改下去的衣服没有回头路",
         "修好回店要顾客本人试穿、输码核验才算完成 —— 不然返修后合不合身又没有凭据"])

# 订单两套口径的映射。**这里和 member_order_check 用的是同一张表** ——
# 抄两份的话,改一处另一处不跟,而不跟的时候对账检查会红在「数据错」上,
# 实际错的是映射表。
ORDER_PRD={"待确认":"待付款","待付款":"待付款","待审核":"方案确认中","待生产":"方案确认中",
           "生产中":"方案确认中","已生产":"待发货","待发货":"待发货",
           "已发货":"待收货","待完成":"待收货","完成":"已完成","取消":"已关闭"}

MERGE_ROLE={("待核验","待总部审批"):"店长",("待总部审批","已合并"):"总部运营",
            ("待总部审批","已驳回"):"总部运营",("待核验","已核验"):"店长"}

# 需要审批链的流转(后台 PRD 6.1 / 5.x)
APPROVAL={("bk-deposit","已付","退款审批中"):"须由客服或店长发起、店长复核;单笔≥1000元增加财务复核"}
# 需要幂等号的流转
IDEMPOTENT={("bk-deposit","退款审批中","退款处理中"),("bk-deposit","退款失败","退款处理中")}

# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('往订单状态机里加一条「待生产 → 完成」的边(中间七档全跳过,而库里看不出来)',
     '跳档 —— 中间七档全没走'),
]

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
        # ⚠️ **定制单开裁前必须过白坯试衣这道闸**(业务 2026-09-22)。
        #    闸放在状态机上、而不是只放在开裁那个写口里 —— 后台有一个通用的「改状态」入口
        #    (server.transit),只拦写口的话,从后台点一下就绕过去了。
        #    **没带过闸结果的一律拒绝**(fail closed):哪个入口忘了算,就哪个入口开不了裁,
        #    而不是悄悄放行。过闸怎么算在 backend/fitting_write.过闸。
        if (mid,frm,to)==("bk-order","待生产","生产中") and ctx.get("kind","定制品订单")=="定制品订单" \
                and ctx.get("白坯过闸")!="可以":
            return False,"MUSLIN_GATE",(ctx.get("白坯过闸_为什么")
                or "定制单开裁前必须过白坯试衣这道闸:该试的要试过并且客户签了字 —— 这次流转没带过闸结果,一律拒绝")
        # ⚠️ **定制单确认下单要过下单量体这道闸**(业务 2026-09-22):每一件都要有绑在它上面的、
        #    开单之后量的、够做这件衣服的下单量体。闸放在状态机上,后台通用改状态也绕不过;
        #    **没带过闸结果的一律拒绝**(fail closed),同 MUSLIN_GATE。过闸怎么算在 backend/order_write.过闸。
        if (mid,frm,to)==("bk-order","待确认","待审核") and ctx.get("下单过闸")!="可以":
            return False,"ORDER_GATE",(ctx.get("下单过闸_为什么")
                or "确认下单要每一件都有为它重新量的下单量体 —— 这次流转没带过闸结果,一律拒绝")
        # ⚠️ **定制单的生产和发货只认工厂回传**(业务 2026-09-22:「已生产」「发货」是工厂回传的数据,
        #    走供应链系统,不给门店推进入口)。「生产中→已生产→待发货→已发货」三条边,
        #    server.transit 从工厂回传收件箱现算有没有**收下了**的那条回传撑着,不信调用方传的结论;
        #    **没带的一律拒绝**(fail closed),同 MUSLIN_GATE。收回传在 backend/factory_inbox.py。
        #    标品不走工厂(待发货→已发货是仓库发货),不挂这道闸。
        if (mid,frm,to) in (("bk-order","生产中","已生产"),("bk-order","已生产","待发货"),("bk-order","待发货","已发货")) \
                and ctx.get("kind","定制品订单")=="定制品订单" and ctx.get("工厂回传")!="有":
            return False,"FACTORY_GATE",(f"定制单「{frm}→{to}」只认工厂回传 —— 生产和发货是工厂报的事实,"
                                         "门店和后台不能手动推;这一步还没有收下的工厂回传,一律拒绝")
        # ⚠️ **定制单签收要顾客确认试穿合身**(业务 2026-09-22):「已发货 → 待完成」只认核验通过的
        #    6 位码。闸放在状态机上,后台通用的改状态入口也绕不过(server.transit 从 pickup 表现算,
        #    不信调用方传的结论)。**没带核验结果的一律拒绝**(fail closed),同 MUSLIN_GATE。
        if (mid,frm,to)==("bk-order","已发货","待完成") and ctx.get("kind","定制品订单")=="定制品订单" \
                and ctx.get("试穿合身")!="已核验":
            return False,"FIT_GATE",("定制单签收要顾客确认试穿合身:顾客在手机上点「试穿合身」拿到 6 位码,"
                                     "导购输入核验通过才算签收 —— 这次流转没带核验结果,一律拒绝")
        # 完成要顾客确认,或签收满 15 天后顾问写理由追认(业务 2026-09-22)
        if (mid,frm,to)==("bk-order","待完成","完成") and ctx.get("kind","定制品订单")=="定制品订单" \
                and ctx.get("完成确认") not in ("顾客","顾问追认"):
            return False,"COMPLETE_GATE",("定制单完成要顾客自己确认;顾客一直不确认,签收满 15 天后由顾问写理由追认 —— "
                                          "这次流转两样都没有,一律拒绝")
        # 返修两道闸(业务 2026-09-22,fail closed):没判完不许开工,没核验顾客的码不许算完成
        if (mid,frm,to)==("bk-maintain","待确认","待入库") and ctx.get("判完了") is not True:
            return False,"REPAIR_GATE",("返修开工前要店长判完责:谁承担、返修还是重做;判给顾客的要录预估费用、"
                                        "记下顾客同意 —— 这次流转没带判责结果,一律拒绝")
        if (mid,frm,to)==("bk-maintain","待签收","已完成") and ctx.get("签收核验")!="已核验":
            return False,"REPAIR_FIT_GATE",("返修件回店要顾客本人试穿合身、输 6 位码核验才算完成 —— "
                                            "这次流转没带核验结果,一律拒绝")
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
    # 订单:**跳档和反向都要拦,而这两种在库里都看不出来**
    order_bad = []
    ocases=[
      (("bk-order","待付款","待审核",{}),  True,  "定制品:付款后审方案"),
      (("bk-order","待付款","待发货",{}),  True,  "标品:付款后直接备货"),
      (("bk-order","待生产","完成",{}),    False, "跳档 —— 中间七档全没走,而库里看不出来"),
      (("bk-order","待审核","待付款",{}),  False, "反向 —— 已经审了不能退回没付款"),
      (("bk-order","生产中","取消",{}),    False, "开工后取消 —— 料已经裁了,那是退款不是改状态"),
      (("bk-order","待生产","取消",{}),    True,  "开工前可以取消"),
      (("bk-order","待生产","生产中",{}),  False, "开裁没带白坯过闸结果 —— 一律拒绝(不许悄悄放行)"),
      (("bk-order","待确认","待审核",{}),  False, "确认下单没带下单量体过闸结果 —— 一律拒绝"),
      (("bk-order","待确认","待审核",{"下单过闸":"可以"}), True, "每件都有下单量体才许确认"),
      (("bk-order","待确认","待付款",{}),  False, "定制单确认即已付款,不走待付款"),
      (("bk-order","待确认","取消",{}),    True,  "没定的直接取消"),
      (("bk-order","待生产","生产中",{"白坯过闸":"不可以"}), False, "白坯没过闸不许开裁"),
      (("bk-order","待生产","生产中",{"白坯过闸":"可以"}),   True,  "过了白坯那道闸才许开裁"),
      (("bk-order","生产中","已生产",{}),  False, "定制单完工没有工厂回传 —— 一律拒绝(后台也不能手动推)"),
      (("bk-order","生产中","已生产",{"工厂回传":"有"}), True, "收下了工厂的完工回传才许到已生产"),
      (("bk-order","待发货","已发货",{}),  False, "定制单发货没有工厂回传 —— 一律拒绝"),
      (("bk-order","待发货","已发货",{"kind":"标品订单"}), True, "标品是仓库发货,不走工厂回传"),
      (("bk-order","完成","待发货",{}),    False, "终态再动"),
      (("bk-order","取消","待付款",{}),    False, "终态再动"),
    ]
    for (args, want, why) in ocases:
        got = check(*args)[0]
        mark = "✅" if got == want else "❌"
        print(f"  {mark} {args[1]:5s} → {args[2]:5s}  {'放行' if got else '拒绝'}  {why}")
        # **必须并进总的 bad**。第一版我设了个 bad_order 然后没人看它 ——
        # 8 条全错也不影响退出码,**等于没测**。
        # 「写了检查」和「检查会影响结果」是两件事,而它们在输出上长得一模一样:
        # 都是打印一行 ✅/❌。
        if got != want: order_bad.append(f"{args[1]}→{args[2]}")

    if order_bad:
        print(f"  ❌ 订单状态机 {len(order_bad)} 条不符合预期:{order_bad}")

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
    import sys; sys.exit(1 if (bad or order_bad) else 0)
