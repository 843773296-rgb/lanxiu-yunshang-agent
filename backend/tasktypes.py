# -*- coding: utf-8 -*-
"""任务类型 —— **谁能派、能不能让 agent 建议,是类型自带的性质,不是界面上的选项。**

分两族,因为这两族的责任来源根本不同:

  客户相关   预约到店 / 电话回电 / 上门沟通 / 接待任务
             —— 事情是**客户发起的**,门店只是响应。谁负责取决于「这个客户是谁的」。
  店铺运营   团建培训 / 日常运维 / 订单跟踪 / 维保任务 / 售后任务
             —— 事情是**店里自己安排的**,和某个客户没有归属关系,
                所以只能由店长派:没有第二个信息源能替他决定谁去。

派单的三条路,按「决定权在谁」排:

  ① 系统自动派   客户相关 + 客户有归属顾问
                 —— 归属关系就是答案,不需要任何人判断
  ② agent 建议 + 店长确认
                 客户相关 + 客户没有归属顾问
                 —— agent 能算出「谁最合适」,但**算出来的不是决定**。
                    建议和决定必须分开存:合在一起的话,从 agent 写下建议
                    到店长点确认之间,这张单在库里看起来已经有人负责了,
                    而实际上没有任何人看过它。
  ③ 店长指派     店铺运营
                 —— agent 不建议。它不知道这周谁该轮培训、谁家里有事,
                    这些信息根本不在库里。**没有依据的建议比没有建议更糟**:
                    店长会以为它算过。
"""

# ── 数据规范:每一族有自己的必填项 ─────────────────────────────────
# **族和数据规范是两根轴,别合成一根。**
#   族      —— 决定**谁派**(客户相关能自动派/agent 建议;运营只能店长派)
#   数据规范 —— 决定**必须挂哪张单据**
# 订单跟踪由店长派(族=运营),但它盯的是某一张单,当然得知道是谁的单。
# 上一版把两者合成了一个 needs_customer,于是「运营=不挂客户」,
# 订单跟踪、维保、售后就都成了无主的任务。
#
# ref 的取值 = **挂哪种单据**:
#   customer   客户号        —— 客户主动找上门的那四种
#   order      订单号        —— 盯一张单的进度
#   maintain   维保单号      —— 某件衣服的保养/返修
#   aftersale  售后单号      —— 某张单的退换赔付
#   None       不挂          —— 店内自己的事,本来就没有「给谁做」
#
# **客户号只在 ref=customer 时手填,其余一律从单据带出来。**
# 让人手填的话就有两个来源:单子上写的客户,和人填的客户。两者不一致时
# 没有任何地方会报错 —— 任务上写着 C10001,单子其实是 C10007 的,
# 顾问照着任务去联系。同一个事实存两遍,必然漂。

# 完成时要不要现场照?**别一刀切成「都要」。**
# 电话回电没什么可拍的,硬性要求的结果不是多一张证据,是多一张桌面照 ——
# **强制的证据会变成假证据**,而假证据比没证据更坏:
# 它让台账看起来是有据可查的。
# 所以只在「事情本身留下了可看的痕迹」时要求:去过现场、动过东西、修过件。
#
# (名称, 族, 挂哪种单据, 派单方式, 完成时是否必须传图, 一句话说明)
TYPES = [
    ("预约到店", "客户", "customer",  "auto_or_agent", False, "客户约了时间到店,需要有人接待"),
    ("电话回电", "客户", "customer",  "auto_or_agent", False, "客户留了问题要回电"),
    ("上门沟通", "客户", "customer",  "auto_or_agent", True,  "顾问上门量体或沟通方案 —— 要有到场的照片"),
    ("接待任务", "客户", "customer",  "auto_or_agent", False, "客户到店后的接待与跟进"),

    ("团建培训", "运营", None,        "manager",       True,  "店内培训、内部活动 —— 要有现场照"),
    ("日常运维", "运营", None,        "manager",       True,  "陈列、盘点、卫生 —— 要有做完的样子"),
    ("订单跟踪", "运营", "order",     "manager",       False, "盯一张订单的进度 —— 填订单号,客户从单上带出"),
    ("维保任务", "运营", "maintain",  "manager",       True,  "成衣保养、返修 —— 填维保单号,要有件的照片"),
    ("售后任务", "运营", "aftersale", "manager",       True,  "投诉、退换、赔付 —— 填售后单号,要有问题件的照片"),
]

# 单据种类 → (库表, 主键列, 界面上叫什么, 举例)
REF_SOURCE = {
    "customer":  ("customer",  "id", "客户号",   "C10001"),
    "order":     ("ordr",      "id", "订单号",   "6488012719714560000"),
    "maintain":  ("maintain",  "id", "维保单号", "MW73020"),
    "aftersale": ("aftersale", "id", "售后单号", "AS64880127"),
}

BY_NAME = {t[0]: dict(name=t[0], family=t[1], ref=t[2], route=t[3],
                      needs_photo=t[4], desc=t[5],
                      ref_label=(REF_SOURCE[t[2]][2] if t[2] else None),
                      ref_eg=(REF_SOURCE[t[2]][3] if t[2] else None))
           for t in TYPES}
CUSTOMER_TYPES = [t[0] for t in TYPES if t[1] == "客户"]
OPS_TYPES = [t[0] for t in TYPES if t[1] == "运营"]

# 旧数据里的四个类型 → 新分类。**迁移表必须写下来** ——
# 不写的话,老单子的 type 在新界面上会落进「未知」,而未知会被当成新的一类,
# 于是同一件事在库里有两个名字。
LEGACY = {
    "客户预约": "预约到店",
    "回访跟进": "电话回电",
    "订单任务": "订单跟踪",
    "企业任务": "日常运维",
}


def norm(t):
    """把任何写法归一到当前类型名。认不出来就原样返回 —— **不许猜**。"""
    t = (t or "").strip()
    return LEGACY.get(t, t)


def info(t):
    return BY_NAME.get(norm(t))


def family(t):
    i = info(t)
    return i["family"] if i else "未知"


def who_assigns(t):
    """这个类型该由谁派。返回 'manager' / 'auto_or_agent' / 'unknown'。"""
    i = info(t)
    return i["route"] if i else "unknown"


def agent_may_propose(t):
    """agent 能不能对这个类型出建议。

    只有客户相关的才行。运营任务的依据(谁该轮培训、谁家里有事)不在库里,
    **没有依据的建议比没有建议更糟** —— 它看起来像算过。
    """
    return who_assigns(t) == "auto_or_agent"


def ref_of(t):
    """这个类型该挂哪种单据。None = 店内自己的事,不挂。"""
    i = info(t)
    return i["ref"] if i else None


def needs_customer(t):
    """要不要**手填**客户号 —— 只有客户主动找上门的那四种才要。

    订单跟踪/维保/售后也是有客户的,但那个客户**从单据带出来**,
    不由人填。这两件事一定要分开说,否则「有客户」会被理解成「要填客户」。
    """
    return ref_of(t) == "customer"


def needs_photo(t):
    """完成时必须传现场照吗。认不出的类型一律**不强制** ——
    对一个不认识的类型硬加门槛,只会挡住正常的活。"""
    i = info(t)
    return bool(i and i["needs_photo"])


def catalog():
    """给界面用的清单。界面**不许自己写一份类型列表**。"""
    return [dict(BY_NAME[n], can_propose=agent_may_propose(n)) for n in BY_NAME]


def resolve_ref(kind, ref_id, q):
    """把单据号换成 (客户号, 门店, 人话说明)。

    `q(sql, *args)` 由调用方传进来 —— 这个模块**不自己连库**:
    类型表是规矩,规矩不该知道数据库在哪。

    返回 (ok, customer_id, shop, 说明)。查不到就说清楚查的是什么单,
    「单据不存在」这五个字会让人反复核对一个根本不该填在这儿的号。
    """
    src = REF_SOURCE.get(kind)
    if not src:
        return True, None, None, ""            # 不挂单据的类型
    table, key, label, eg = src
    rid = (ref_id or "").strip()
    if not rid:
        return False, None, None, f"{label}必填(例:{eg})"

    if kind == "customer":
        r = q(f"SELECT id,name,shop FROM customer WHERE {key}=?", rid)
        if not r: return False, None, None, f"没有这个{label}:{rid}"
        return True, r[0]["id"], r[0]["shop"], f"{r[0]['name']}({rid})"

    r = q(f"SELECT * FROM {table} WHERE {key}=?", rid)
    if not r: return False, None, None, f"没有这个{label}:{rid}"
    row = r[0]
    cid = row.get("customer_id")
    if not cid:
        # 单子上没有客户 —— **不许在这里猜一个**。
        # 这种单本身就是坏数据,派下去只会把坏数据传下去。
        return False, None, None, f"{label} {rid} 上没有客户,这张单据本身要先修"
    nm = q("SELECT name FROM customer WHERE id=?", cid)
    who = f"{nm[0]['name']}({cid})" if nm else cid
    extra = row.get("item") or row.get("kind") or row.get("reason") or ""
    return True, cid, row.get("shop"), f"{who}的{label} {rid}" + (f" · {extra}" if extra else "")
