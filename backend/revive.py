# -*- coding: utf-8 -*-
"""促活判断:这个客户现在需不需要联系。

业务定的边界(2026-09-20):**我们的 agent 只面对顾问,只给参谋。**
所以这里的产出是**一个判断加一句人话**,不是一个动作,也不是一个分数 ——
顾问要照着它打电话,「87 分」没法照着说,理由可以。

## 核心判据:「很久没买」不是理由,是筛子

促活判断要同时回答两件事:**为什么是他,为什么是现在。**
只按闲置天数筛,顾问拿到名单也不知道说什么,打过去就是尬聊 —— 而且会骚扰。

所以:**没有由头的,不进名单。** 哪怕他闲置 300 天。

## 三层

    第一层 硬门槛   不满足直接不促(手上有单在做 / 有未结售后 / 最近刚联系过)
    第二层 由头     必须有至少一个 —— 这是「为什么是现在」
    第三层 排序     有由头的人可能很多,按价值和由头强度排(不在本模块)

## ⚠️ 时间要「相对他自己」,不是一个全局阈值

一个每季度买一次的人,90 天不买是**异常**;
一个一年买一次的人,90 天不买是**正常**。

用全局阈值会把「这个人本来就买得少」和「这个人变了」混成同一件事 ——
**而后者才是该管的那个。**

所以 RHYTHM_BREAK 这一条比的是「他自己的节奏」:
365 / 他过去 12 个月的单数 = 他平均多少天来一次。

## ⚠️ 两个参数是**拍的**,不是算出来的

`断节奏倍数` 和 `刚联系过的天数` 现在的取值没有依据 —— 是我定的默认值。
**它们看起来和有出处的数一模一样**,所以在这儿写明:**等真实数据来校准**。
输出里也会标出来,不让下游把它当成结论。
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
# 判定口径在 knowledge/reactivate.py,这里只取数。
# (名字避开 revive:和这个文件同名的话 `import revive` 会先找到它自己,
#  而「导入成功了」和「导入对了」长得一样。)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import reactivate as _口径

# ── 待校准的参数:**只有一份,在口径模块里** ──────────────────────
# 这里转发,不抄。抄一份的后果是改一处漏一处,而**两份参数不一致时,
# 判断照样跑得出结果** —— 名单看起来完全正常。
断节奏倍数 = _口径.断节奏倍数
刚联系过 = _口径.刚联系过
刚下过单 = _口径.刚下过单
回访窗口 = _口径.回访窗口
生日提前 = _口径.生日提前
他自己的节奏 = lambda cust: _口径.他自己的节奏((cust or {}).get("orders_12m"))

# ── 订单状态:**写死在这儿的每个值,都必须在库里真实存在** ──────────
#
# 2026-09-20 踩过:我按「已完成」「已取消」写,而库里是「完成」「取消」——
# 多一个字,结果 23499 张已完成的订单全被判成「在做」。
# **不报错,只是判断全错** —— 「状态值写错了」和「这个客户真的有单在做」,
# 在判断结果里长得一模一样。
#
# → `revive_check.py` 会拿这两个元组和库里的实际值对账,写错了当场红。
订单终态 = ("完成", "取消")

# 售后终态只有两个。**「退款失败」不在里面** —— 它听起来像终点(失败了就结束了),
# 实际上是**最需要人处理**的状态:库里那两条卡了 20 多天没动。
# 把它当终态,等于在客户最不满的时候给他推新品。
售后终态 = ("已完成", "审批拒绝")


def _rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


def _today():
    """世界的今天,不是机器的今天 —— 机器的今天每过一天就变,判断结果就不可复现。"""
    from seed import TODAY
    return datetime.date.fromisoformat(TODAY)


def _d(s):
    """宽松解析日期;解析不出来返回 None(**不猜**)。"""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def 他自己的节奏(cust):
    """他平均多少天来一次。算不出来返回 None —— **算不出和「节奏很慢」是两回事**。"""
    n = cust.get("orders_12m") or 0
    if n <= 0:
        return None
    return 365.0 / n


def 查事实(cust, today):
    """把口径要的那些事实查出来。**这里一条判定都没有。**"""
    cid = cust.get("id")
    刚买过 = _rows("""SELECT created FROM ordr WHERE customer_id=?
                      AND status NOT IN (?,?) ORDER BY created DESC LIMIT 1""",
                   cid, *订单终态)
    d = _d(刚买过[0]["created"]) if 刚买过 else None
    ph = ",".join("?" * len(售后终态))
    未结售后 = _rows(f"""SELECT id FROM aftersale WHERE customer_id=?
                        AND status NOT IN ({ph}) LIMIT 1""", cid, *售后终态)
    跟进 = _rows("SELECT ts FROM followup WHERE customer_id=? ORDER BY ts DESC LIMIT 1", cid)
    跟进d = _d(跟进[0]["ts"]) if 跟进 else None
    # 往年同期:**SQL 里就排除今年** —— 口径里还会再滤一次,两道都留着。
    # 「今年这个月刚买过」被算成往年同期的话,理由那句话会自相矛盾。
    同期 = _rows("""SELECT created FROM ordr WHERE customer_id=?
                    AND status<>'取消'
                    AND CAST(strftime('%m', created) AS INTEGER)=?
                    AND CAST(strftime('%Y', created) AS INTEGER)<?""",
                 cid, today.month, today.year)
    完成单 = _rows("""SELECT finished_at FROM ordr WHERE customer_id=? AND finished_at IS NOT NULL
                      ORDER BY finished_at DESC LIMIT 1""", cid)
    完成d = _d(完成单[0]["finished_at"]) if 完成单 else None
    维保 = _rows("""SELECT item FROM maintain WHERE customer_id=?
                    AND status NOT IN ('已完成','已关闭') LIMIT 1""", cid)
    return {
        "id": cid, "name": cust.get("name") or cid,
        "刚买过天数": (today - d).days if d else None,
        "有未结售后": bool(未结售后),
        "最近跟进天数": (today - 跟进d).days if 跟进d else None,
        "往年同期年份": sorted({_d(r["created"]).year for r in 同期 if _d(r["created"])}),
        "生日": _d(cust.get("birthday")),
        "上一单完成天数": (today - 完成d).days if 完成d else None,
        "维保件": 维保[0]["item"] if 维保 else None,
        "orders_12m": cust.get("orders_12m"),
        "idle_days": cust.get("idle_days"),
        "有过首单": bool(cust.get("first_order")),
    }


def should_revive(cust, today=None):
    """这个客户现在需不需要促活 —— **判定在 `knowledge/reactivate.py`**。

    返回 (需不需要, 码, 人话理由)。
    **False 不是「这人没价值」** —— 多数 False 是「现在不是时候」。
    """
    today = today or _today()
    return _口径.判(查事实(cust, today), today)


def 一个人的判断(customer_id):
    r = _rows("SELECT * FROM customer WHERE id=?", customer_id)
    if not r:
        return None
    return should_revive(r[0])
