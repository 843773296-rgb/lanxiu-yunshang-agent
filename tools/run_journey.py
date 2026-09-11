#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑一条**完整的客户旅程**:预约 → 上门 → 量体 → 量体数据 → 订单 → 订单完成。

## 为什么不是「插几行数据」

插行只保证表里有东西,不保证**这些东西彼此对得上**。
走真实代码路径的数据,是被同一套校验挡过一遍的 ——
所以它既是数据,也是一次端到端验证:哪一环走不通,当场就知道。

## 哪些环走了真路径,哪些是直插

这条链上**有两环根本没有写入路径**:量体和订单。
系统里能读它们,但没有任何东西能创建它们。

    ✅ 真路径   预约  booking.book()        —— 客户手机端那条,带三道闸
    ✅ 真路径   派单  route() / dispatch()  —— 有归属顾问自动派,没有则落池
    ✅ 真路径   上门  tasks.assign_task()   —— 走类型规范、时段冲突检查
    ✅ 真路径   完成  tasks.finish_task()   —— 只能本人完成、总结必填
    ⚠️ 直插     量体  没有写接口
    ⚠️ 直插     订单  没有写接口
    ⚠️ 直插     完成  没有状态机

**直插的那三环不受任何业务规则约束** —— 这正是这个脚本要暴露的:
它们现在只能靠人手工保证一致,而手工保证的东西迟早会不一致。
脚本最后会把这份「哪些有保护、哪些没有」列出来。

用法:
    python3 tools/run_journey.py            跑 3 条
    python3 tools/run_journey.py 5          跑 5 条
    python3 tools/run_journey.py --dry      只看会发生什么,不写库
"""
import os, sys, json, random, sqlite3, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

G, R, Y, B, D = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
REAL, RAW = f"{G}真路径{D}", f"{Y}直插{D}"


def q(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def ex(sql, *a):
    with sqlite3.connect(DB) as c:
        c.execute(sql, a)


def pick_customers(n):
    """挑能安全跑旅程的客户。

    **四类**必须排除,每一类都栽过:

    · **反例夹具**(E-* 共 14 个)—— 种子里写着「⚠️ 不许补全」。
      我第一版挑到了 E-A4-01「人工调整 15 天前」,给它加了一笔订单、
      改了累计金额和最近互动 —— **而它的 last_interact 正是生命周期真值的依据**。
    · **客户合并用例**(C21* 共 32 个,对应 15 条 BP-02 真值)——
      那 16 对是「疑似重复档案」,改它们的字段会动到评测答案。
    · **被评测引用的客户** —— 这一类最难看见:它们**不是夹具**,就是普通客户,
      但某条评测用例的真值依赖它们身上的某个事实。
      栽过一次:C10017 原来只有 3 项量体记录(「记录不全」),
      我给他补了 5 项完整的 —— **售后判责那条用例的真值当场翻了**
      (「记录不全 · 我方免费改」变成规则算出的「客方 · 收费改」)。
      夹具和普通数据之间有边,**而那条边从客户这一侧看不见**。
      现在把四种引用都排掉:售后判责的维保单、客户合并、押金退款、truth 表提到的。
    · **一号多档**(库里有 16 个)—— book() 按手机号找人,
      多条时取最早建档那条,所以脚本挑的那条不一定是最后下单的那条,
      跑出来的数据会自相矛盾。这个 bug 已修(会记台账),但脚本仍然避开它们,
      **因为这里要的是干净数据,不是再验一次那个 bug**。

    **夹具被污染时不会报错** —— 它只是让某条评测下次给出一个不同的答案,
    而没人会想到去查是三周前一个造数据的脚本动的。
    """
    return q("""SELECT c.id,c.name,c.phone,c.shop,c.advisor FROM customer c
                WHERE c.archived=0 AND c.phone NOT LIKE 'DELETED%'
                  AND c.name<>'已注销用户'
                  AND c.id NOT LIKE 'E-%'          -- 反例夹具
                  AND c.id NOT LIKE 'C21%'         -- 客户合并用例
                  -- 被评测引用的:动它们身上的事实,会翻掉某条用例的真值
                  AND c.id NOT IN (SELECT customer_id FROM maintain
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='售后判责'))
                  AND c.id NOT IN (SELECT customer_id FROM deposit
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='财务人工任务'))
                  AND c.id NOT IN (SELECT customer_id FROM aftersale)
                  AND (SELECT COUNT(*) FROM customer d
                       WHERE d.phone=c.phone AND d.archived=0) = 1   -- 一号一档
                  AND (SELECT COUNT(*) FROM schedule s
                       WHERE s.customer_id=c.id AND s.type='预约到店' AND s.status='有效') = 0
                ORDER BY RANDOM() LIMIT ?""", n)


def journey(cust, dry=False):
    """走完一条。返回每一环的结果。"""
    import booking, tasks, tasktypes as tt
    steps = []
    now = datetime.datetime.now()

    # ── ① 预约(真路径:客户手机端那条)────────────────────────────
    when = (now + datetime.timedelta(days=random.randint(2, 9))).replace(
        hour=random.choice([10, 11, 14, 15, 16]), minute=0, second=0, microsecond=0)
    if dry:
        steps.append(("① 预约", REAL, f"会调 booking.book({cust['phone']}, {when:%m-%d %H:%M})"))
        return steps, None
    r = booking.book(dict(phone=cust["phone"], when=when.strftime("%Y-%m-%dT%H:%M"),
                          need="到店量体 · 定制"))
    if not r.get("ok"):
        steps.append(("① 预约", REAL, f"{R}被拒{D}:{r.get('reason','')[:60]}"))
        return steps, None
    appt, task = r["appt"], r["task"]
    who = "自动派给归属顾问" if r["assigned"] else f"{Y}落待分配池{D}({r['code']})"
    steps.append(("① 预约", REAL, f"{appt} / 任务 {task} · {who}"))

    # ── ② 没派出去的先分派(真路径)─────────────────────────────
    t = q("SELECT * FROM schedule WHERE id=?", task)[0]
    if not t.get("assignee_no"):
        sg = booking.suggest(t)
        if not sg:
            steps.append(("② 分派", REAL, f"{R}提不出建议{D} —— 这个门店没有在职顾问"))
            return steps, None
        mgr = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=?", t["shop"])
        if not mgr:
            steps.append(("② 分派", REAL, f"{R}{t['shop']} 没有店长{D}"))
            return steps, None
        r2 = tasks.dispatch(dict(id=task, assignee_no=sg["no"]), mgr[0])
        if not r2.get("ok"):
            steps.append(("② 分派", REAL, f"{R}{r2.get('reason','')[:50]}{D}"))
            return steps, None
        steps.append(("② 分派", REAL, f"{mgr[0]['name']}(店长)分给 {sg['name']} · {sg['why'][0][:34]}"))
        t = q("SELECT * FROM schedule WHERE id=?", task)[0]
    adv = q("SELECT no,name,role,shop,adv_code FROM staff WHERE no=?", t["assignee_no"])[0]

    # ── ③ 上门沟通(真路径:走类型规范和时段冲突)──────────────────
    mgr = q("SELECT no,name,role,shop FROM staff WHERE role='店长' AND shop=?", t["shop"])
    v_start = when + datetime.timedelta(days=1)
    v_end = v_start + datetime.timedelta(hours=2)
    r3 = tasks.assign_task(dict(
        type="上门沟通", assignee_no=adv["no"], ref_id=cust["id"],
        note=f"上门为 {cust['name']} 量体,带样布和版型册",
        start=v_start.strftime("%Y-%m-%d %H:%M"), end=v_end.strftime("%Y-%m-%d %H:%M")),
        mgr[0] if mgr else None)
    if not r3.get("ok"):
        steps.append(("③ 上门", REAL, f"{R}{r3.get('reason','')[:60]}{D}"))
        return steps, None
    visit = r3["id"]
    steps.append(("③ 上门", REAL, f"{visit} 派给 {adv['name']} · {v_start:%m-%d %H:%M}"))

    # ── ④ 量体数据(⚠️ 直插:没有写接口)────────────────────────
    w = q("SELECT id,name,height FROM wearer WHERE customer_id=? ORDER BY id LIMIT 1", cust["id"])
    wid = w[0]["id"] if w else None
    tpl = random.choice(["LT01", "LT02", "LT03"])
    items = q("SELECT code,name,unit FROM measure_item WHERE status='启用' AND required=1 ORDER BY sort")
    base = dict(MI01=random.uniform(158, 178), MI02=random.uniform(48, 72),
                MI03=random.uniform(82, 98), MI04=random.uniform(66, 84),
                MI05=random.uniform(88, 102))
    mt = (v_start + datetime.timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M")
    n_item = 0
    for it in items:
        val = round(base.get(it["code"], random.uniform(30, 60)), 1)
        ex("""INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,measured_at,
              method,wearer_id,cond_inner,cond_shoe,cond_breath,schedule_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
           cust["id"], tpl, it["code"], val,
           f"{adv.get('adv_code') or ''} {adv['name']}".strip(), mt,
           "上门", wid, "单层内衣", "赤足", "平静呼气", visit)
        n_item += 1
    steps.append(("④ 量体", RAW, f"{tpl} · {n_item} 项 · {adv['name']} 上门量 · 着装人 {wid or '(无)'}"))

    # ── ⑤ 上门任务完成(真路径:只能本人完成、总结必填、该传图的要传)────
    # 第一版没传图,三条全被拦:「上门沟通完成时要传现场照」。
    # **那是规矩在正常工作** —— 上门这种事本身留下了可看的痕迹,不传图完不了。
    # 脚本得像真顾问那样传一张,而不是把规矩绕过去。
    import files as _f, base64 as _b64
    png = "data:image/png;base64," + _b64.b64encode(
        bytes.fromhex("89504e470d0a1a0a") + b"visit" * 24).decode()
    ok_img, why_img = _f.save(visit, "总结", "上门现场.png", png, adv["name"])
    r5 = tasks.finish_task(dict(
        id=visit,
        summary=f"已上门量体,{n_item} 项齐全,客户确认按 {tpl} 模板做,现场选定面料"), adv)
    steps.append(("⑤ 完成上门", REAL,
                  (f"✅ 传了现场照,任务完结" if r5.get("ok")
                   else R + str(r5.get("reason") or r5.get("error"))[:44] + D)))
    if not r5.get("ok"):
        # **上门没完成就不该下单。** 这条链现在没有东西拦着,
        # 但脚本自己不许造出这种数据 —— 造出来就成了「库里本来就有这种」的先例。
        steps.append(("⑥ 下单", RAW, f"{Y}跳过{D} —— 上门任务没完成,不该下单"))
        return steps, None

    # ── ⑥ 下单(⚠️ 直插:没有写接口,也没有状态机)────────────────
    oid = str(random.randint(6488012719714560000, 6488012719714569999))
    # sku 表的主键叫 code 不叫 sku,商品名在 product 表里 —— **列名以表为准**,
    # 这个项目在「列名靠猜」上栽过(appt_at vs start_ts)
    sk = q("""SELECT s.code,s.spu,s.price,s.spec,p.name FROM sku s
              LEFT JOIN product p ON p.spu=s.spu
              WHERE s.status='启用' ORDER BY RANDOM() LIMIT 1""")
    sku = sk[0] if sk else dict(code="SKU0001", name="定制汉服", price=4800.0, spu="SPU001", spec="")
    custom = round(random.uniform(600, 2400), 2)
    amt = round((sku["price"] or 4800) + custom, 2)
    created = (v_start + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    # **两套状态口径有固定映射**(设计稿 10 档 ↔ PRD 状态机),
    # 而 goods_amount 是**基本金额之和,不含定制加价** ——
    # 第一版两处都填错了,被 member_order_check 当场抓到。
    # 我在脚本里写过「订单这一环没有任何规则挡着」,那句话是错的:
    # **没有写接口保护,不等于没有任何东西检查。** 对账检查一直在管。
    ST2PRD = {"待付款": "待付款", "待审核": "方案确认中", "待生产": "方案确认中",
              "生产中": "方案确认中", "已生产": "待发货", "待发货": "待发货",
              "已发货": "待收货", "待完成": "待收货", "完成": "已完成", "取消": "已关闭"}
    ex("""INSERT INTO ordr(id,customer_id,kind,status,advisor,shop,source,delivery,
          amount,payable,created,updated,prd_status,goods_amount,freight,received,
          refund_status,paid_at)
          VALUES(?,?,'定制品订单','待生产',?,?,'门店Pad','配送到店',?,?,?,?,?,?,0,?,'未退款',?)""",
       oid, cust["id"], f"{adv.get('adv_code') or ''} {adv['name']}".strip(), cust["shop"],
       amt, amt, created, created, ST2PRD["待生产"], sku["price"], amt, created)
    ex("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,
          custom_amount,total) VALUES(?,?,?,'定制',?,1,?,?,?,?)""",
       oid, sku["code"], (sku.get("name") or "定制汉服") + (f"·{sku.get('spec')}" if sku.get("spec") else ""),
       sku["price"], sku["spu"], sku["price"], custom, amt)
    steps.append(("⑥ 下单", RAW, f"{oid[-6:]}… · {sku['name']} · ¥{amt}(定制加价 ¥{custom})"))

    # ── ⑦ 订单完成(⚠️ 直插:没有状态机,直接跳到终态)──────────────
    done = (v_start + datetime.timedelta(days=random.randint(28, 45))).strftime("%Y-%m-%d %H:%M")
    ex("""UPDATE ordr SET status='完成',prd_status='已完成',updated=?,produced_at=?,
          shipped_at=?,finished_at=? WHERE id=?""",
       done, (v_start + datetime.timedelta(days=25)).strftime("%Y-%m-%d %H:%M"),
       (v_start + datetime.timedelta(days=27)).strftime("%Y-%m-%d %H:%M"), done, oid)
    ex("UPDATE customer SET order_cnt=order_cnt+1, paid_amount=paid_amount+?, last_interact=? WHERE id=?",
       amt, done[:10], cust["id"])
    steps.append(("⑦ 完成", RAW, f"{done[:10]} 完成 · 客户累计单数 +1、金额 +¥{amt}"))
    return steps, dict(客户=cust["id"], 预约=appt, 预约任务=task, 上门任务=visit,
                       量体项=n_item, 订单=oid, 金额=amt)


def main():
    n = 3
    dry = "--dry" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit(): n = int(a)
    custs = pick_customers(n)
    if not custs:
        print(f"{R}挑不出客户{D} —— 可能都有在办预约了(那是 book() 的频次闸,是对的)")
        return
    print(f"\n{B}跑 {len(custs)} 条完整旅程{D}"
          f"{'(试跑,不写库)' if dry else ''}")
    print("=" * 86)
    done = []
    for c in custs:
        print(f"\n{B}▸ {c['name']}({c['id']}) · {c['shop']} · 归属 {c['advisor']}{D}")
        steps, out = journey(c, dry)
        for name, kind, txt in steps:
            print(f"    {kind}  {name:10s} {txt}")
        if out: done.append(out)

    if dry: return
    print("\n" + "=" * 86)
    print(f"{B}跑完 {len(done)}/{len(custs)} 条{D}")
    for o in done:
        print(f"  {o['客户']} → 预约 {o['预约']} → 上门 {o['上门任务']} → "
              f"量体 {o['量体项']} 项 → 订单 …{o['订单'][-6:]} ¥{o['金额']}")

    print(f"\n{B}这条链上哪些有保护、哪些没有{D}")
    print("  " + "-" * 82)
    print(f"  {G}✅ 有业务规则挡着{D}  预约(手机号/营业时间/频次)· 派单(归属/离职/跨店)")
    print(f"                     上门(类型规范/时段冲突/权限)· 完成(本人/总结必填)")
    print(f"  {Y}⚠️ 直插,没有任何规则{D}  量体 · 下单 · 订单完成")
    print()
    print(f"  {Y}但「没有写接口保护」不等于「没有任何东西检查」{D} —— 我一开始把这两件事混成了一句。")
    print("    实际上 backend/member_order_check.py 一直在对账,而且当场抓到了我造的两处错:")
    print("      · 订单两套状态口径的映射填反了(设计稿「完成」要映射到「已完成」)")
    print("      · goods_amount 填成了含定制加价的总额,而它的口径是**基本金额之和**")
    print()
    print(f"  {Y}真正缺的是这些{D}:")
    print("    · 量体的人是不是真去上门的那个人 —— 现在靠 task_id 连上了,但没有检查盯着")
    print("    · 订单能不能从「待生产」直接跳「完成」—— 没有状态机拦,中间几档可以跳过")
    print("    · 上门任务没完成能不能下单 —— 没有东西拦(这个脚本自己不许,但系统允许)")
    print(f"  **对账检查抓得到「填错了」,抓不到「顺序错了」** —— 后者要状态机。")


if __name__ == "__main__":
    main()
