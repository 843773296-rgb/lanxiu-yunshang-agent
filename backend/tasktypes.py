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

# 完成时要不要现场照?**别一刀切成「都要」。**
# 电话回电没什么可拍的,硬性要求的结果不是多一张证据,是多一张桌面照 ——
# 人会拍点什么交差。**强制的证据会变成假证据**,而假证据比没证据更坏:
# 它让台账看起来是有据可查的。
# 所以只在「事情本身留下了可看的痕迹」时要求:去过现场、动过东西、修过件。
#
# (名称, 族, 是否必须挂客户, 派单方式, 完成时是否必须传图, 一句话说明)
TYPES = [
    ("预约到店", "客户", True,  "auto_or_agent", False, "客户约了时间到店,需要有人接待"),
    ("电话回电", "客户", True,  "auto_or_agent", False, "客户留了问题要回电"),
    ("上门沟通", "客户", True,  "auto_or_agent", True,  "顾问上门量体或沟通方案 —— 要有到场的照片"),
    ("接待任务", "客户", True,  "auto_or_agent", False, "客户到店后的接待与跟进"),

    ("团建培训", "运营", False, "manager",       True,  "店内培训、内部活动 —— 要有现场照"),
    ("日常运维", "运营", False, "manager",       True,  "陈列、盘点、卫生 —— 要有做完的样子"),
    ("订单跟踪", "运营", False, "manager",       False, "盯一张订单的进度"),
    ("维保任务", "运营", False, "manager",       True,  "成衣保养、返修 —— 要有件的照片"),
    ("售后任务", "运营", False, "manager",       True,  "投诉、退换、赔付 —— 要有问题件的照片"),
]

BY_NAME = {t[0]: dict(name=t[0], family=t[1], needs_customer=t[2], route=t[3],
                      needs_photo=t[4], desc=t[5])
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


def needs_photo(t):
    """完成时必须传现场照吗。认不出的类型一律**不强制** ——
    对一个不认识的类型硬加门槛,只会挡住正常的活。"""
    i = info(t)
    return bool(i and i["needs_photo"])


def catalog():
    """给界面用的清单。界面**不许自己写一份类型列表**。"""
    return [dict(BY_NAME[n], can_propose=agent_may_propose(n)) for n in BY_NAME]
