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
    ✅ 真路径   推进  transit("bk-order")   —— 一档一档走状态机,跳档会被拒

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
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, "backend", "lanxiu.db")

G, R, Y, B, D = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"

# 基准日:**从 seed.py 读,不在这儿抄一份**。
# idle_days 的口径是「建库那天的快照」,spec_check 的 C5 也从同一处读 ——
# 两边各抄一份的话,改了种子的基准日,造数据和检查就会在不同的日子上比。
import re as _re
try:
    _BASE_DAY = _re.search(r'TODAY\s*=\s*"(\d{4}-\d{2}-\d{2})"',
                           open(os.path.join(ROOT, "backend", "seed.py"),
                                encoding="utf-8").read()).group(1)
except Exception:
    _BASE_DAY = "2026-08-31"
REAL, RAW = f"{G}真路径{D}", f"{Y}直插{D}"
_BASE = datetime.date.fromisoformat(_BASE_DAY)

# **种子。** 原来这个脚本一次种子都没设,全局 random 每次跑都不一样 ——
# 于是同一份代码重建两次,数据不同:单号是随机取的,42 条旅程会占掉不同的号段,
# 后面 order_mix 的随机流跟着偏移。实测两次重建 **3481 张订单的状态/日期/金额不同**,
# 而取消单总数只差 12 —— **「净差 12」和「换掉 3481 单」在总数上长得一模一样**。
# 代价是 CI 上有一条显著性检查间歇红:它判「哪几档维保率值得注意」,
# 而最紧的一档离阈值只有 0.9% 余量,数据一抖就翻面。
# **判据对着一个会动的东西量,红绿就不再有意义。**
SEED = 20260920


def _门店渠道():
    """门店那个渠道在库里**怎么写的** —— 从数据取,不手写。

    ⚠️ 这里原来写死「门店Pad」(无空格),而 `ordr.source` 里是
    **「门店 Pad」(有空格)** —— 于是同一个渠道在统计里被算成**两个**,
    「渠道和活动共线」那条评测前提当场不成立。

    而这个笔误不是随手打的:**它照着 `sys_code` 的枚举表抄的**,
    而那张表和真实数据是两套东西 ——

        sys_code 说:微信小程序 / 门店Pad / 门店A / 门店B
        ordr 实际是:微信小程序 / 门店 Pad / 官网 / 客服代下单

    **只有一个对得上。** 这就是「同一个事实两个来源」,
    而两个来源都在,写的人照哪个都像是对的。
    """
    r = q("SELECT source FROM ordr WHERE source LIKE '%Pad%' "
          "GROUP BY source ORDER BY COUNT(*) DESC LIMIT 1")
    if not r:
        raise SystemExit("❌ 库里找不到门店那个渠道的写法 —— "
                         "**不许我编一个**,去查 ordr.source 有哪些值")
    return r[0]["source"]

def _拆定制明细(item_id, spu, 总额):
    """把定制加价拆成看得见的部位明细。

    ⚠️ **这不是重新算一遍价,是把一个已有的总额拆成看得见的项** ——
    拆出来对不上,就是**收的钱和记的账分家了**(`part_choice_check` 盯着)。

    口径和 `seed.py` 里那段一致:每个部位挑一个选项、按项数均摊、
    **最后一项吃舍入差**。挑法按 item_id 定,**重播种结果一样**。
    """
    if not item_id or not 总额 or 总额 <= 0:
        return
    opts = q("SELECT part, material, addon, colors FROM part_option "
             "WHERE spu=? AND kind='面料' ORDER BY sort, material", spu)
    if not opts:
        # ⚠️ **没得选就不该收这笔钱。** 这里不静默跳过 —— 静默跳过正是
        # 「有钱没项」那条检查要抓的东西。说出来,让人去看这个 SPU 为什么没选项。
        print(f"    ⚠️ SPU {spu} 没有面料部位选项,而订单行 {item_id} "
              f"收了 ¥{总额} 定制加价 —— **有钱没项**,这一单的明细拆不出来")
        return
    分组 = {}
    for o in opts:
        分组.setdefault(o["part"], []).append(o)
    选 = []
    for i, (部位, lst) in enumerate(sorted(分组.items())):
        o = lst[(item_id + i) % len(lst)]
        cs = [x for x in (o["colors"] or "").split("、") if x]
        选.append((部位, o["material"], cs[(item_id + i) % len(cs)] if cs else None))
    # ⚠️ **外层部位有面料就得有工艺** —— 而内衬和系带不配工艺。
    # 这条判据不在这儿重写:**口径在 `knowledge/part.py`**,这里只调它。
    # (里面那层和辅料本来就不做工艺:醋酸里布上不绣花、织带上不做缂丝;
    #  相容矩阵里也查不到「苏绣 × 醋酸里布」——**矩阵是主料 × 工艺的**。)
    import importlib.util as _iu, os as _os
    _sp = _iu.spec_from_file_location(
        "part", _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "knowledge", "part.py"))
    _pm = _iu.module_from_spec(_sp); _sp.loader.exec_module(_pm)
    外层 = {b for b in _pm.部位顺序 if _pm.部位可选料类(b) == ("主料",)}
    工艺可选 = [r["material"] for r in q(
        "SELECT DISTINCT material FROM part_option WHERE spu=? AND kind='工艺'", spu)]

    每项 = round(float(总额) / len(选), 2)
    for i, (部位, 料, 色) in enumerate(选):
        金 = 每项 if i < len(选) - 1 else round(float(总额) - 每项 * (len(选) - 1), 2)
        ex("INSERT INTO item_part_choice(item_id,kind,part,material,color,amount,note)"
           " VALUES(?,?,?,?,?,?,?)", item_id, "面料", 部位, 料, 色, 金, None)
        if 部位 not in 外层:
            continue
        # ⚠️ **挑不出相容的就不配工艺,不是随便塞一个** ——
        # 塞一个做不出来的组合,车间会拿着它去开工。
        相容 = [k for k in 工艺可选 if (q(
            "SELECT verdict v FROM craft_combo WHERE craft="
            "(SELECT code FROM craft WHERE name=? AND cat='工艺') AND material="
            "(SELECT code FROM craft WHERE name=? AND cat='材质')", k, 料)
            or [{"v": None}])[0]["v"] not in ("不可", None)]
        if not 相容:
            continue
        ex("INSERT INTO item_part_choice(item_id,kind,part,material,color,amount,note)"
           " VALUES(?,?,?,?,?,?,?)",
           item_id, "工艺", 部位, 相容[(item_id + i) % len(相容)], None, 0.0, None)

def q(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def ex(sql, *a):
    with sqlite3.connect(DB) as c:
        c.execute(sql, a)


def _抽(候选, n):
    """从候选里抽 n 个。**抽样必须用带种子的 rng,不能用 SQL 的 `ORDER BY RANDOM()`** ——
    后者不受 Python 种子管,于是同一份代码每次跑挑到的是不同的客户。

    这是 2026-09-20 查出来的那个「重建不确定」的根:挑到的客户不同 → 造出的订单挂在
    不同的人身上 → 后面按客户挑单改定制的那一步跟着偏 → **两次重建 3500 张订单的
    状态、金额、归属都不一样**,而订单总数、客户数、维保数全都一模一样。
    **总数相同掩盖了内容不同**,直到一条按比例判显著性的检查在 CI 上间歇变红。
    """
    候选 = sorted(候选, key=lambda r: r["id"])      # 先定序,再抽 —— 查询顺序本身不保证稳定
    return random.sample(候选, min(n, len(候选)))


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
    候选 = q("""SELECT c.id,c.name,c.phone,c.shop,c.advisor_no FROM customer c
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
                ORDER BY c.id""")
    return _抽(候选, n)


def pick_repeat(n):
    """**回头客**:已经走过一趟、现在手上没有在办预约的。

    加这条是因为一次性客户池会用完(31 个跑完就没了),而现实里
    **回头客本来就该有多次预约和多次订单** —— 一个只有一次消费的客户库,
    RFM 的 F(频次)这一维永远分不出层来。

    安全前提和 pick_customers 一样(排掉夹具/评测引用/一号多档),
    额外要求:上一趟的订单已经走到终态 —— **一个客户不该同时有两张在制的定制单**,
    那在现实里也不成立(版师手上一件一件做)。
    """
    候选 = q("""SELECT c.id,c.name,c.phone,c.shop,c.advisor_no FROM customer c
                WHERE c.archived=0 AND c.phone NOT LIKE 'DELETED%'
                  AND c.name<>'已注销用户'
                  AND c.id NOT LIKE 'E-%' AND c.id NOT LIKE 'C21%'
                  AND c.id NOT IN (SELECT customer_id FROM maintain
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='售后判责'))
                  AND c.id NOT IN (SELECT customer_id FROM deposit
                                   WHERE id IN (SELECT ref_id FROM task WHERE type='财务人工任务'))
                  AND c.id NOT IN (SELECT customer_id FROM aftersale)
                  AND (SELECT COUNT(*) FROM customer d
                       WHERE d.phone=c.phone AND d.archived=0) = 1
                  AND (SELECT COUNT(*) FROM schedule s
                       WHERE s.customer_id=c.id AND s.type='预约到店' AND s.status='有效') = 0
                  -- 走过一趟(量体记录连着上门任务的那种)
                  AND EXISTS (SELECT 1 FROM measure_rec m
                              WHERE m.customer_id=c.id AND m.schedule_id IS NOT NULL)
                  -- 上一趟的单已经收尾 —— 不该同时有两张在制的定制单
                  AND NOT EXISTS (SELECT 1 FROM ordr o WHERE o.customer_id=c.id
                                  AND o.status NOT IN ('完成','取消'))
                ORDER BY c.id""")
    return _抽(候选, n)


def journey(cust, dry=False):
    """走完一条。任何一步炸了都**说清楚炸在哪**,不让整批停下来。

    上一版没有这层:第 31 条订单号撞了,`UNIQUE constraint failed` 直接掀了整个进程,
    前 30 条的结果一行没打印,而库里留着半条旅程(量体写了、订单没写、时间没挪回过去)。
    **一个造数据的脚本崩在半路,留下的是看起来正常的残缺数据。**
    """
    try:
        return _journey(cust, dry)
    except Exception as e:
        return [("✗ 崩了", f"{R}异常{D}",
                 f"{type(e).__name__}: {e}  —— **这一条可能留了半截在库里**,"
                 f"跑 spec_check 看有没有孤儿")], None


def _journey(cust, dry=False):
    """走完一条。返回每一环的结果。"""
    import booking, tasks, tasktypes as tt
    steps = []
    now = datetime.datetime.now()   # 真实时钟:book() 拒绝过去的时间,只能按真实的未来报;落点另算

    # ── ① 预约(真路径:客户手机端那条)────────────────────────────
    #
    # **整条旅程往过去排,不往未来排。**
    # 第一版从今天往后排(预约 +2~9 天、上门再 +1、订单再走 30~45 天),
    # 于是整条链全在未来:客户「已经上门量过体」而那天还没到,
    # 订单「已完成」而完成日在 11 月。C4 检查当场抓到 248 条未来时间。
    #
    # 这不是时间戳填错,是**方向反了** ——
    # 一条「已完成」的旅程,它的每一步本来就都发生过了。
    #
    # 但 book() 会拒绝过去的时间(那是对的:客户不能预约昨天)。
    # 所以:**预约按未来下单,拿到单号之后把整条链的时间改写到过去** ——
    # 走的还是真路径,只是把这条旅程挪到它本来该在的时间上。
    # 往前挪多少 —— **不能挪到客户建档之前**。
    # 第一版固定挪 50~120 天,结果有客户是今年才建的档,预约被挪到了建档之前,
    # C3(任何记录不早于所属对象的创建时间)当场抓到 8 条。
    # **「往过去挪」有个下界,而这个下界因客户而异。**
    _created = q("SELECT created FROM customer WHERE id=?", cust["id"])[0]["created"]
    try:
        # 基准日用**演示世界的今天**,不是机器的今天 —— 后者每天都在变,
        # 于是同一份代码今天和明天造出来的数据不一样
        _room = (_BASE - datetime.date.fromisoformat(_created[:10])).days - 20
    except Exception:
        _room = 120
    # **两个下界会打架,打架时不许硬挑一个。**
    #   · 终点要落到过去 → 要挪得**多**(订单本身走 30~45 天)
    #   · 不能挪到客户建档之前 → 要挪得**少**
    # 老客户两条都满足;而今年才建档的客户**根本放不下一条完整旅程**。
    # 第一版在结尾处「取严的那个」,于是建档早的那个下界赢了,
    # 终点留在未来 —— C4 抓到 3 条量体记录落在 2026-09-17。
    #
    # **挑不出合规的位置,就别造这条数据。** 造一条违规的比不造更糟:
    # 它看起来和正常旅程一模一样,只有和「今天」比才看得出来。
    需要天数 = 45 + 9 + 3          # 订单最长工期 + 预约到上门的间隔 + 落到过去的余量
    if _room < 需要天数:
        steps.append(("① 预约", REAL,
                      f"{Y}跳过{D} —— {cust['id']} 是 {_created[:10]} 建的档,"
                      f"往前只有 {_room} 天可挪,而一条完整旅程要 {需要天数} 天。"
                      f"**挪不到过去就会造出未来日期**"))
        return steps, None
    span = random.randint(30, max(31, min(120, _room)))   # 这条旅程发生在多少天前(相对基准日)
    # **book() 要一个真实的未来时间**(它拒绝过去,那是对的),所以这里还是按机器的今天报;
    # 但**落点不由它决定** —— 挪回去多少天 = 报的那天 − 目标落点,目标落点只看基准日和 span。
    # 这样机器哪天跑,写进库的时间戳都一样。
    when = (now + datetime.timedelta(days=random.randint(2, 9))).replace(
        hour=random.choice([10, 11, 14, 15, 16]), minute=0, second=0, microsecond=0)
    目标 = _BASE - datetime.timedelta(days=span)
    shift = datetime.timedelta(days=(when.date() - 目标).days)
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
    w = q("SELECT id,name,height,gender,birthday FROM wearer WHERE customer_id=? ORDER BY id LIMIT 1", cust["id"])
    wid = w[0]["id"] if w else None
    tpl = random.choice(["LT01", "LT02", "LT03"])
    items = q("SELECT code,name,unit FROM measure_item WHERE status='启用' AND required=1 ORDER BY sort")
    mt = (v_start + datetime.timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M")
    # 量体值按这个人造(body_gen)。原来只有前五项有范围,**其余一律 30–60 之间随手取** ——
    # 通袖长 45、衣长 38 这种数进了库,判档位时全判全定制(2026-09-22)。
    import body_gen as _bg
    _体, _ = _bg.按编码((w[0]["gender"] if w else None) or "女",
                         _bg.周岁(w[0]["birthday"], mt) if w else None,
                         (w[0]["height"] if w else None), wid or cust["id"])
    n_item = 0
    for it in items:
        val = round(_体.get(it["code"], random.uniform(30, 60)), 1)
        ex("""INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by_no,
              measured_at,
              method,wearer_id,cond_inner,cond_shoe,cond_breath,schedule_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
           cust["id"], tpl, it["code"], val, adv["no"], mt,
           "上门", wid, "单层内衣", "赤足", "平静呼气", visit)
        n_item += 1
    steps.append(("④ 量体", RAW, f"{tpl} · {n_item} 项 · {adv['name']} 上门量 · 着装人 {wid or '(无)'}"))

    # ── ⑤ 上门任务完成(真路径:只能本人完成、总结必填、该传图的要传)────
    # 第一版没传图,三条全被拦:「上门沟通完成时要传现场照」。
    # **那是规矩在正常工作** —— 上门这种事本身留下了可看的痕迹,不传图完不了。
    # 脚本得像真顾问那样传一张,而不是把规矩绕过去。
    import files as _f, base64 as _b64, server as _srv0
    png = "data:image/png;base64," + _b64.b64encode(
        bytes.fromhex("89504e470d0a1a0a") + b"visit" * 24).decode()
    ok_img, why_img = _f.save(visit, "总结", "上门现场.png", png, adv["name"])
    r5 = tasks.finish_task(dict(
        id=visit,
        summary=f"已上门量体,{n_item} 项齐全,客户确认按 {tpl} 模板做,现场选定面料"), adv)
    steps.append(("⑤ 完成上门", REAL,
                  (f"✅ 传了现场照,任务完结" if r5.get("ok")
                   else R + str(r5.get("reason") or r5.get("error"))[:44] + D)))
    # 「顺带收尾预约」已经搬进 finish_task 了(见那里的注释)——
    # 脚本侧补等于只在造数据时对,真人走一遍还是会留一条。
    if r5.get("ok") and r5.get("顺带收尾"):
        steps.append(("⑥ 收尾预约", REAL, f"{r5['顺带收尾']} → 完结(finish_task 自动)"))
    if not r5.get("ok"):
        steps.append(("⑦ 下单", RAW, f"{Y}跳过{D} —— 上门任务没完成,不该下单"))
        return steps, None

    # ── 下单前置校验:**走统一口径,不在这儿自己写一遍** ──────────────
    # 这条判断原来只写在这个脚本里(「脚本自己不许造出这种数据」),
    # 于是系统允许、脚本不许 —— **两套规矩**,而系统那套才是真的。
    # 现在口径在 `knowledge/order_gate.py`,`api.can_order` 和这里共用它。
    #
    # ⚠️ 真正该拦的不是「有没有上门任务」,是**这个着装人的量体在不在有效期**。
    # 按「必须有上门任务」拦会误伤每一个老客户(回头客用的是几个月前的数据)。
    import api as _api
    with _api.as_user(adv):
        gate = _api.can_order(cust["id"], "定制品订单", wid or None)
    if gate.get("结论") != "可以":
        steps.append(("⑦ 下单", REAL,
                      f"{Y}拦下{D} —— {gate.get('结论')}:{str(gate.get('理由'))[:60]}"))
        return steps, None

    # ── ⑥ 下单(⚠️ 直插:没有写接口,也没有状态机)────────────────
    # 订单号:**取一个库里没有的**,不要靠随机撞运气。
    # 上一版是 random.randint 取 4 位后缀,跑到第 31 条时撞上已有的单号 ——
    # `UNIQUE constraint failed`,而且**整个脚本当场崩掉,半条旅程留在库里**
    # (量体写了、订单没写,时间也没挪回过去)。
    # 一个造数据的脚本崩在半路,留下的是**看起来正常的残缺数据**。
    _used = {r["id"] for r in q("SELECT id FROM ordr")}
    oid = None
    for _ in range(500):
        cand = str(random.randint(6488012719714560000, 6488012719714569999))
        if cand not in _used:
            oid = cand; break
    if not oid:
        steps.append(("⑦ 下单", RAW, f"{R}订单号取不到没被占的 —— 号段用满了{D}"))
        return steps, None
    # sku 表的主键叫 code 不叫 sku,商品名在 product 表里 —— **列名以表为准**,
    # 这个项目在「列名靠猜」上栽过(appt_at vs start_ts)
    # ⚠️ **这一单是定制单,所以 SKU 必须是定制品的。**
    #
    # 原来只写了 `WHERE s.status='启用'` —— 随机抽到什么算什么,
    # 实测 31 单里 **24 单抽到了标品**,然后给它加了一笔几百到两千的「定制加价」。
    #
    # 后果不是「数字不好看」,是**业务上讲不通**:标品是现货成衣按尺码卖的,
    # 它**没有部位选项**,那笔定制加价**拆不出明细** ——
    # 车间照着打印不出来,客户争议时也拿不出依据。
    # 而这 24 单在库里**看起来完全正常**:有订单、有金额、有状态。
    #
    # 再加一条 `part_option` 存在性:**有选项才拆得出明细**。
    # 只判 kind 不够 —— 146 个定制品里有 2 个没录部位选项。
    sk = q("""SELECT s.code,s.spu,s.price,s.spec,p.name FROM sku s
              JOIN product p ON p.spu=s.spu
              WHERE s.status='启用' AND p.kind='定制品'
                AND EXISTS(SELECT 1 FROM part_option WHERE spu=s.spu AND kind='面料')
              ORDER BY s.code""")          # 定序后用带种子的 rng 挑(见 _抽 上面那段)
    sk = [random.choice(sk)] if sk else []
    if not sk:
        # **不静默退回一个编出来的 SKU。** 原来这里有个 `dict(code="SKU0001", …)`
        # 的兜底 —— 它指向一个**库里不存在的商品**,而下出来的单看起来完全正常。
        raise SystemExit("❌ 找不到「启用 + 定制品 + 有部位选项」的 SKU —— "
                         "**下不了定制单**。这不是随机波动,是主数据缺了东西,"
                         "去查 product.kind 和 part_option。")
    sku = sk[0]
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
    # **这一单是哪次预约带来的** —— 业务 2026-09-21 拍板:定制品必须有预约,标品一律没有。
    # 这条旅程走的正是「预约 → 上门 → 量体 → 下单」,所以它**挂得上**;
    # 库里其余 3500 张定制单还挂不上,它们的 appt_src 留「未接入」——
    # **「未接入」和「无预约」必须分开**:前者是链路没接(要补),后者是确认过不该有(要排除),
    # 合成一个空值的话,两者看起来一样而处理方式相反。
    ex("""INSERT INTO ordr(id,customer_id,kind,status,advisor_no,shop,source,delivery,
          amount,payable,created,updated,prd_status,goods_amount,freight,received,
          refund_status,paid_at,appt_id,appt_src)
          VALUES(?,?,'定制品订单','待付款',?,?,?,'配送到店',?,?,?,?,?,?,0,?,'未退款',?,?,'已关联')""",
       oid, cust["id"], adv["no"], cust["shop"], _门店渠道(),
       amt, amt, created, created, ST2PRD["待付款"], sku["price"], amt, created, appt)
    # ⚠️ **下单时的版型版本是快照,不是现算。**
    # 版型改过之后回头看这一单,现算会给出**今天**那一版,
    # 而车间当初裁的是**那天**那一版 —— 两者在表上长得一模一样。
    _pvr = q("SELECT version FROM pattern WHERE code="
             "(SELECT pattern FROM product WHERE spu=?)", sku["spu"])
    _pv = _pvr[0]["version"] if _pvr else None
    ex("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,base_amount,
          custom_amount,total,pattern_version,pattern_version_src)
          VALUES(?,?,?,'定制品',?,1,?,?,?,?,?,?)""",
       oid, sku["code"], (sku.get("name") or "定制汉服") + (f"·{sku.get('spec')}" if sku.get("spec") else ""),
       sku["price"], sku["spu"], sku["price"], custom, amt,
       _pv, "下单时记的(run_journey)" if _pv is not None else None)
    _ir = q("SELECT MAX(id) m FROM ordr_item WHERE order_id=?", oid)
    _iid = _ir[0]["m"] if _ir else None
    # ⚠️ **收了定制加价,就必须有部位明细。**
    # 原来这里只写了金额:钱收了,而**选了什么部位、什么料、什么颜色一个字都没存** ——
    # 车间照着打印不出来,客户争议时也拿不出依据。
    # `seed.py` 里做对了这件事,而这条路径是后来加的,**没跟上** ——
    # 两条路径写同一张表,只有一条是对的,而库里看不出来。
    _拆定制明细(_iid, sku["spu"], custom)
    steps.append(("⑦ 下单", RAW, f"{oid[-6:]}… · {sku['name']} · ¥{amt}(定制加价 ¥{custom})"))

    # ── ⑦ 订单推进到完成(真路径:一档一档走状态机)──────────────────
    # 上一版直接 UPDATE 到终态,中间七档全跳过 —— 而**跳过的档在库里看不出来**,
    # 一张单子从「待生产」一步到「完成」和正常走完九档,最终长得一模一样。
    # 现在走 transit(),每一步都过状态机、都留台账。
    #
    # 装上状态机之后第一步就抓到我自己写错的东西:下单时我把初始状态填成了「待生产」,
    # 而定制品的链路第一档是「待付款」。**之前没有状态机的时候,这张单从一开始
    # 就跳过了两档,而没有任何东西说得出来** —— 状态机不只拦「往后跳」,
    # 还拦「起点就不对」,而起点不对在库里完全看不出来。
    import server as _srv
    PATH = ["待审核", "待生产", "生产中", "已生产", "待发货", "已发货", "待完成", "完成"]
    day = 0
    for st in PATH:
        day += random.randint(2, 6)
        if st == "生产中":
            _裁日 = day
            # ── 开裁前的白坯试衣(业务 2026-09-22:该试的要试过、客户签了字才许开裁)──
            # 闸挂在订单状态机上,**这条旅程也得照着走**:闸上线那天第一次重建,
            # 这里就被拦在「生产中」,脚本崩在半路 —— 时间没挪回过去,留下一批未来日期
            # (数据规范 C4 / A15 当场红)。**真路径的好处就在这:流程一变,造数据的人先撞上。**
            # 该试的由上门那位顾问登记一轮、客户签字;时间按剧本回填,不用机器时钟。
            import fitting_write as _fw, seed_fitting as _sfit
            # 试衣表是 seed_fitting(第 7 步)建的,旅程跑在它前面 —— **用同一份建表语句**先建上,
            # 不另抄一份表结构(第一版没建,这里「no such table」崩在半路,又留下一批未来日期)
            with sqlite3.connect(DB) as _cx: _cx.executescript(_sfit.DDL)
            _g, _w, _明细 = _fw.过闸(oid)
            if _g in ("不可以", "判不了"):
                # 判不了该不该试的也先试 —— 门店拿不准时本来就该先试一轮(已试已签即放行)
                _试 = (v_start + datetime.timedelta(days=day - 1)).strftime("%Y-%m-%d %H:%M")
                for _x in _明细:
                    if _x["能不能开裁"] == "可以": continue
                    _r = _fw.record(dict(order_id=oid, item=str(_x["订单行"]),
                                         adjust="无需调整", signed=True, note="旅程脚本"), adv)
                    if _r.get("ok"):
                        ex("UPDATE fitting SET ts=?, signed_at=? WHERE item_id=? AND round=?",
                           _试, _试, _x["订单行"], _r["第几轮"])
                steps.append(("⑦½ 白坯试衣", REAL, f"该试 {sum(1 for x in _明细 if x['能不能开裁'] != '可以')} 件"
                              f"({'、'.join(sorted({k for x in _明细 for k in (x.get('属于哪几类') or [])}))})"
                              f",{adv['name']} 陪试、客户签字"))
        # ── 交付签收(业务 2026-09-22):到店代收 → 顾客手机点「试穿合身」拿码 → 导购核验 → 待完成;
        #    完成由顾客确认。闸挂在状态机上,**旅程也照真路径走**,不然第一次重建就卡在「已发货」。
        #    签收表是 seed_pickup 建的,旅程跑在它前面 —— 用同一份建表语句先建上(同白坯试衣)。
        if st in ("待完成", "完成"):
            import pickup_write as _pw, seed_pickup as _spk
            with sqlite3.connect(DB) as _cx: _cx.executescript(_spk.DDL)
            _尾 = (q("SELECT phone_tail FROM customer WHERE id=(SELECT customer_id FROM ordr WHERE id=?)", oid)
                  or [{"phone_tail": ""}])[0]["phone_tail"]
            if st == "待完成":
                _pw.arrive({"order_id": oid}, adv)
                _pw.set_mode({"order_id": oid, "mode": "到店取"}, adv)
                _码 = _pw.customer_issue_code(oid, _尾).get("试穿合身码")
                rr = _pw.verify({"order_id": oid, "code": _码 or ""}, adv)
                steps.append(("⑧½ 交付签收", REAL, f"到店代收、顾客试穿合身、{adv['name']} 核验签收"
                              if rr.get("ok") else f"签收没过:{rr.get('reason','')[:30]}"))
            else:
                rr = _pw.customer_complete(oid, _尾)
            if not rr.get("ok"):
                steps.append(("⑧ 推进", REAL, f"{R}卡在 {st}:{rr.get('reason','')[:40]}{D}"))
                return steps, None
            continue
        # ── 生产和发货只认工厂回传(业务 2026-09-22)—— 旅程也照真路径走:由模拟工厂发回传、
        #    接收写口收下后推状态。闸上线后还直接 transit,这里第一次重建就会卡在「生产中」。
        #    时间先按机器时钟收(和 transit 落的一样),下面按剧本回填、再随整条旅程挪回过去。
        if st in ("已生产", "待发货", "已发货"):
            import factory_inbox as _fi
            _fi.ensure()
            # 时间取这张单自己的开裁时间(transit 落的),**不自己取机器时钟** —— 重建可复现检查查这一条;
            # 反正下面会按剧本回填
            _now = str(q("SELECT cut_at FROM ordr WHERE id=?", oid)[0]["cut_at"])[:16]
            _事 = {"已生产": "完工", "待发货": "质检通过", "已发货": "发出"}[st]
            _msgs = ([dict(消息号=f"J{oid}-接", 订单号=oid, 事件="接单", 时间=_now, 工厂="旅程工厂",
                          承诺完工日=_now[:10])]
                     if st == "已生产" else [])
            _msgs.append(dict(消息号=f"J{oid}-{_事}", 订单号=oid, 事件=_事, 时间=_now, 工厂="旅程工厂",
                              **({"物流单号": f"SFJ{oid[-8:]}"} if _事 == "发出" else {})))
            for _m in _msgs:
                rr = _fi.收(_m, _now[:10], actor="旅程脚本")
                if rr["结论"] != "收下":
                    steps.append(("⑧ 推进", REAL, f"{R}工厂回传没收下({_事}):{rr['理由'][:40]}{D}"))
                    return steps, None
            continue
        rr = _srv.transit("bk-order", oid, st, {"by": "旅程脚本", "actor_no": adv["no"]})
        if not rr.get("ok"):
            steps.append(("⑧ 推进", REAL, f"{R}卡在 {st}:{rr.get('reason','')[:40]}{D}"))
            return steps, None
    # 时间戳按剧本回填 —— transit 落的是「现在」,而这条旅程是有时间线的
    done = (v_start + datetime.timedelta(days=day)).strftime("%Y-%m-%d %H:%M")
    ex("""UPDATE ordr SET updated=?,produced_at=?,shipped_at=?,finished_at=? WHERE id=?""",
       done, (v_start + datetime.timedelta(days=day - 12)).strftime("%Y-%m-%d %H:%M"),
       (v_start + datetime.timedelta(days=day - 6)).strftime("%Y-%m-%d %H:%M"), done, oid)
    # 签收时间也按剧本回填:到店 = 发货后 2 天,试穿合身 = 发货后 3 天,完成 = 完成日
    _发 = v_start + datetime.timedelta(days=day - 6)
    ex("UPDATE pickup SET arrived_at=?, fit_at=?, complete_at=? WHERE order_id=?",
       (_发 + datetime.timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
       (_发 + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M"), done, oid)
    ex("UPDATE fit_code SET issued_at=?, used_at=?, expires_at=? WHERE order_id=?",
       (_发 + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M"),
       (_发 + datetime.timedelta(days=3, minutes=5)).strftime("%Y-%m-%d %H:%M"),
       (_发 + datetime.timedelta(days=4)).strftime("%Y-%m-%d %H:%M"), oid)
    # 工厂回传的时间也对齐到剧本:接单 = 开裁后 20 小时,完工 = 生产时间,质检 = 生产后 1 天,发出 = 发货时间
    _产 = v_start + datetime.timedelta(days=day - 12)
    for _e, _t in (("接单", v_start + datetime.timedelta(days=_裁日, hours=20)), ("完工", _产),
                   ("质检通过", _产 + datetime.timedelta(days=1)),
                   ("发出", v_start + datetime.timedelta(days=day - 6))):
        ex("UPDATE factory_msg SET at=?, received_at=? WHERE order_id=? AND event=?",
           _t.strftime("%Y-%m-%d %H:%M"), _t.strftime("%Y-%m-%d %H:%M"), oid, _e)
    ex("UPDATE factory_msg SET promise_date=date(?) WHERE order_id=? AND event='接单'",
       (v_start + datetime.timedelta(days=_裁日 + 40)).strftime("%Y-%m-%d"), oid)
    # 开裁时间也按剧本回填(transit 落的是「现在」)—— 放在已生产之前
    ex("UPDATE ordr SET cut_at=? WHERE id=? AND cut_at IS NOT NULL",
       (v_start + datetime.timedelta(days=_裁日)).strftime("%Y-%m-%d %H:%M"), oid)
    # ── 客户档案跟着动:三个字段必须一起对 ──────────────────────────
    # 第一版只更了 order_cnt / paid_amount / last_interact,栽了两处:
    #
    # ① **last_interact 填成了订单完成日,而那是一个月后的未来日期** ——
    #    库里出现了「上次联系客户是下个月」,而没有任何检查抓到它。
    #    互动的时间点是**上门那天**(人真的见了面),不是订单完成那天。
    # ② **idle_days 和 lifecycle 没跟着重算** —— 于是一个刚上门量过体的客户
    #    同时挂着「流失、380 天没互动」。**三个字段互相矛盾,而没人报错。**
    #
    # 生命周期的判定口径在 knowledge/lifecycle.py,这里**调它,不自己写一遍** ——
    # 自己写就是第二份口径,而两份口径迟早不一致。
    import knowledge.lifecycle as _lc  # noqa
    inter = v_start.date()                      # 互动 = 上门那天
    idle = max(0, (_BASE - inter).days)         # 稍后还会按挪回过去之后的日期重算一遍
    row = q("SELECT * FROM customer WHERE id=?", cust["id"])[0]
    nr = dict(row, order_cnt=(row["order_cnt"] or 0) + 1,
              paid_amount=round((row["paid_amount"] or 0) + amt, 2),
              amount_12m=round((row["amount_12m"] or 0) + amt, 2),
              orders_12m=(row["orders_12m"] or 0) + 1, idle_days=idle)
    lc, matched = _lc.decide(nr)["生命周期"], None
    try:
        d2 = _lc.decide(nr); lc, matched = d2["生命周期"], "/".join(d2.get("命中", []) or [])
    except Exception:
        pass
    # **会员等级也得跟着重算。** 又是同一个病的另一种形态:
    # 我加了订单金额,而等级是**从金额派生的** —— 不重算的话,
    # 一个 12 个月实付 3 万的客户还挂着「金卡」,而门槛表写着 3 万是黑金。
    # 门槛**从 level_cfg 读,不在这儿抄一份** —— 抄一份的话,
    # 运营改了门槛,造出来的数据就和对账检查对不上,而红的会是「数据错」。
    lvs = q("SELECT name,amount,orders,sort FROM level_cfg WHERE status='启用' ORDER BY sort DESC")
    level = lvs[-1]["name"] if lvs else "普通"
    for L in lvs:                      # 从高到低,任一满足即取
        if nr["amount_12m"] >= (L["amount"] or 0) or nr["orders_12m"] >= (L["orders"] or 0):
            level = L["name"]; break
    ex("""UPDATE customer SET order_cnt=?, paid_amount=?, amount_12m=?, orders_12m=?,
          last_interact=?, idle_days=?, lifecycle=?, level=?, matched=COALESCE(?,matched)
          WHERE id=?""",
       nr["order_cnt"], nr["paid_amount"], nr["amount_12m"], nr["orders_12m"],
       inter.isoformat(), idle, lc, level, matched or None, cust["id"])
    # ── 把整条旅程挪到过去 ─────────────────────────────────────────
    # book() 不收过去的时间(对的),所以先按未来下单、再整体前移。
    # **每一张表都要挪** —— 漏一张就成了「预约在三个月前、量体在下个月」。
    # **挪移要保证终点在过去,不是起点。**
    # 订单本身要走 30~45 天:起点挪到 33 天前,终点就还在未来 5 天 ——
    # C4 抓到过一条(8-09 下单、走 38 天、落到 9-16)。
    # 我盯着开头,而约束在结尾。
    _end = datetime.datetime.strptime(done, "%Y-%m-%d %H:%M")
    _need = (_end.date() - _BASE).days + 3     # 终点至少要落到基准日前 3 天
    if _need > shift.days:
        shift = datetime.timedelta(days=_need)
    # 但也不能挪过客户建档。两个下界**本来就不该打架** ——
    # 上面那道「放不下就跳过」已经把打架的客户挡在门外了。
    # 万一还是打架,**抛出来**,不要硬挑一个:硬挑的结果是
    # 一条日期落在未来的旅程,而它看起来和正常的一模一样。
    # ⚠️ **这条判据要对着「落点」写,不能对着「挪了多少天」写。**
    # 挪多少天里含着一段与业务无关的量:机器今天到基准日的距离(今天每过一天它就大一天)。
    # 拿它和「建档到现在」比,是两把不同的尺子 —— 第一版就这么写的,
    # 于是基准日锚定之后这条立刻误报:一条本来合规的旅程被判成打架,
    # 抛异常中断,**而前面已经写进库的预约和量体留在了那儿,时间还没挪回过去**。
    落点 = (when - shift).date()
    建档 = datetime.date.fromisoformat(_created[:10])
    if 落点 < 建档 + datetime.timedelta(days=20):
        raise AssertionError(
            f"{cust['id']}:整条旅程要落到 {落点},而客户 {建档} 才建档 —— "
            f"落点不能早于建档。**这条客户不该被选中造旅程**,门口那道检查漏了")
    _sh = f"-{shift.days} days"
    for _t, _cols, _key in (
            ("appointment", ("start_ts", "end_ts", "checkin_ts"), f"id='{appt}'"),
            ("schedule", ("start_ts", "end_ts", "assigned_at"), f"id IN ('{task}','{visit}')"),
            ("measure_rec", ("measured_at",), f"schedule_id='{visit}'"),
            ("schedule_file", ("uploaded_at",), f"schedule_id='{visit}'"),
            ("ordr", ("created", "updated", "paid_at", "audit_at", "produced_at",
                      "shipped_at", "finished_at", "cut_at"), f"id='{oid}'"),
            # 白坯试衣记录和开裁时间也要一起挪 —— 09-22 加白坯那一步时漏了,31 条试衣落在 10 月、
            # 开裁时间也在 10 月(对方会话提醒后查实;C4 当时没查这几列,所以没红 —— 已补上)
            ("fitting", ("ts", "signed_at"), f"order_id='{oid}'"),
            # 交付签收的时间也要一起挪 —— 第一版漏了这两张表,31 单的签收落在挪之前的「未来」,
            # 比订单自己的完成日还晚(pickup_write_check「签收不晚于完成」当场抓到)
            ("pickup", ("arrived_at", "fit_at", "complete_at"), f"order_id='{oid}'"),
            ("fit_code", ("issued_at", "used_at", "expires_at"), f"order_id='{oid}'"),
            # 工厂回传(09-22 加)—— 同上,漏了就是「工厂下个月才完工、订单上个月就完成了」
            ("factory_msg", ("at", "received_at"), f"order_id='{oid}'")):
        sets = ", ".join(f"{c2}=datetime({c2}, '{_sh}')" for c2 in _cols)
        ex(f"UPDATE {_t} SET {sets} WHERE {_key}")
    ex(f"UPDATE factory_msg SET promise_date=date(promise_date, '{_sh}') WHERE order_id='{oid}' "
       "AND promise_date IS NOT NULL")

    # ⚠️ **派单时间 / 上传时间的「时分秒」原来是机器的当前时刻。**
    # 这两列由生产代码(`backend/tasks.py`)写下,它在真实业务里理当记 now();
    # 但造库时跑的是**模拟过去**,于是库里躺着「2026-04-26 14:28:00」——
    # **日期是模拟世界的,时分是这台机器此刻的**。两次重建隔一分钟,它就差一分钟。
    #
    # 2026-09-21 比对两次重建时查出来的。扫写法那几条一条都碰不到它:
    # 时间不是这个脚本取的,是它调的生产代码取的。
    #
    # 只钉时分秒,不动日期 —— 日期是上面那段按落点算出来的,那部分本来就是确定的。
    for _t, _c3, _key in (("schedule", "assigned_at", f"id IN ('{task}','{visit}')"),
                          ("schedule_file", "uploaded_at", f"schedule_id='{visit}'")):
        _r3 = random.Random(f"{SEED}::{_t}::{_key}")
        _hm = f"{_r3.randint(9, 18):02d}:{_r3.randint(0, 59):02d}:00"
        ex(f"UPDATE {_t} SET {_c3} = date({_c3}) || ' {_hm}' "
           f"WHERE {_key} AND {_c3} IS NOT NULL")
    # 客户那三个字段也跟着挪,并按挪后的日期重算闲置天数
    inter2 = inter - shift
    # **idle_days 要按基准日算,不是按今天。**
    # 它是「建库那天的快照」这个口径(见 spec_check 的 C5)——
    # 我按今天算,和检查按基准日比,永远差 11 天。
    # 口径不统一时,两边各自都说得通,而对不上的时候不知道该改哪边。
    idle2 = max(0, (_BASE - inter2).days)
    nr2 = dict(nr, idle_days=idle2)
    lc2 = _lc.decide(nr2)["生命周期"]
    ex("UPDATE customer SET last_interact=?, idle_days=?, lifecycle=? WHERE id=?",
       inter2.isoformat(), idle2, lc2, cust["id"])
    done2 = (datetime.datetime.strptime(done, "%Y-%m-%d %H:%M") - shift).strftime("%Y-%m-%d")

    steps.append(("⑧ 推进到完成", REAL, f"走完 {len(PATH)} 档 · {done2} 完成"
                                      f"({span} 天前的一单)· 客户累计 +1 单 ¥{amt} · "
                                      f"生命周期 → {lc2} · 等级 → {level}"))
    return steps, dict(客户=cust["id"], 预约=appt, 预约任务=task, 上门任务=visit,
                       量体项=n_item, 订单=oid, 金额=amt)


def main():
    random.seed(SEED)          # 见 SEED 上面那段:不设种子 = 每次重建数据都不一样
    n = 3
    dry = "--dry" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit(): n = int(a)
    custs = pick_customers(n)
    if len(custs) < n:
        # 一次性客户不够了就补回头客 —— **说清楚补了几个**,
        # 不说的话下次看数据的人会以为这批全是新客
        more = pick_repeat(n - len(custs))
        if more:
            print(f"  一次性客户只剩 {len(custs)} 个,补 {len(more)} 个**回头客**"
                  f"(已走过一趟、上一单已收尾)")
            custs = custs + more
    if not custs:
        print(f"{R}挑不出客户{D} —— 可能都有在办预约了(那是 book() 的频次闸,是对的)")
        return
    print(f"\n{B}跑 {len(custs)} 条完整旅程{D}"
          f"{'(试跑,不写库)' if dry else ''}")
    print("=" * 86)
    done, 卡住 = [], []
    for c in custs:
        print(f"\n{B}▸ {c['name']}({c['id']}) · {c['shop']} · 归属 {c['advisor_no']}{D}")
        steps, out = journey(c, dry)
        for name, kind, txt in steps:
            print(f"    {kind}  {name:10s} {txt}")
        if out: done.append(out)
        if any(n.startswith("⑧") and "卡在" in t or "没收下" in t for n, _, t in steps):
            卡住.append(c["id"])

    # **订单推进卡住要让整步失败。** 09-22 工厂回传上线那次:31 条旅程全卡在「生产中」
    # (接单回传被按秒比成倒挂),而这一步照样退出 0、重建照样打「✅ 完成」——
    # 卡住只打一行红字,淹在几百行输出里。「挪不到过去」那种跳过是设计内的,不算卡住。
    if 卡住:
        print(f"\n{R}❌ {len(卡住)} 条旅程卡在订单推进上:{卡住[:5]} —— 流程变了、造数据的这一步没跟上{D}")
        sys.exit(1)
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
    print(f"  {Y}⚠️ 直插(但下单前有一道闸){D}  量体 · 订单完成")
    print()
    print(f"  {Y}但「没有写接口保护」不等于「没有任何东西检查」{D} —— 我一开始把这两件事混成了一句。")
    print("    实际上 backend/member_order_check.py 一直在对账,而且当场抓到了我造的两处错:")
    print("      · 订单两套状态口径的映射填反了(设计稿「完成」要映射到「已完成」)")
    print("      · goods_amount 填成了含定制加价的总额,而它的口径是**基本金额之和**")
    print()
    # ── 收尾:把着装人那条链补一遍 ────────────────────────────────
    # **这个脚本直插 `ordr_item`,不填 `wearer_id`。** 不补的话,
    # 新造的旅程订单全部落在「判不了」里 —— 而它们看起来和正常订单一模一样。
    # 实测重造 42 条之后有 8 行没人,而我上一条消息还跟用户说「只剩 1 行」。
    #
    # 逻辑在 `backend/fix_order_measure.py`,**和 seed.py 用同一份**。
    if not dry:
        import sqlite3 as _sq3, fix_order_measure as _fx
        _c = _sq3.connect(DB)
        _fx.ensure_wearers(_c, verbose=False)
        _fx.assign_item_wearers(_c, verbose=False)
        _fx.enforce_rows(_c, verbose=False)
        _c.execute("UPDATE ordr SET wearer_id=NULL")
        _fx.assign_wearers(_c, verbose=False)
        _fx.enforce(_c, verbose=False)
        # 顾问引用也要补 —— 这个脚本插 measure_rec 和 schedule,都带名字不带工号。
        import fix_advisor_ref as _far
        _far.link(_c, verbose=False)
        _c.commit(); _c.close()
        print(f"  {G}✅ 着装人链与顾问引用已补{D}(品类树定位 → 补档 → 量体 → 工号)")

    print(f"  {G}后来补上的{D}:")
    print("    · **下单前置** —— `api.can_order()` 在第 ⑦ 步之前真的拦一道:")
    print("      定制订单要有**这个着装人**下单前的量体,而且不能超期")
    print("      (复量周期:成人 12 个月 / 3–12 岁 6 个月 / 突增期 4 个月 / 0–3 岁 3 个月)")
    print("      口径在 `knowledge/order_gate.py`,**脚本和工具共用一份** ——")
    print("      原来这条判断只写在这个脚本里,于是系统允许、脚本不许,**两套规矩**")
    print(f"  {Y}真正还缺的{D}:")
    print("    · 量体的人是不是真去上门的那个人 —— 现在靠 task_id 连上了,但没有检查盯着")
    print("    · 订单能不能从「待生产」直接跳「完成」—— 没有状态机拦,中间几档可以跳过")
    print(f"  **对账检查抓得到「填错了」,抓不到「顺序错了」** —— 后者要状态机。")


if __name__ == "__main__":
    main()
