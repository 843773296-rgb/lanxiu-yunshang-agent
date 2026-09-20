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
import os, sqlite3, datetime

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")

# ── 待校准的参数(见上面的警告) ────────────────────────────────────
断节奏倍数 = 2.0      # 闲置超过「他自己节奏」的几倍算断了
刚联系过 = 14         # 几天内联系过就不再打扰
刚下过单 = 14         # 几天内下过单就不再推新
回访窗口 = (7, 45)    # 上一单完成后第几天到第几天适合回访
生日提前 = 30         # 生日前几天算「临近」

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


# ── 判断(纯函数,不写库,可以单独测) ──────────────────────────────
def should_revive(cust, today=None):
    """这个客户现在需不需要促活。

    返回 (需不需要, 码, 人话理由)。
    **False 不是「这人没价值」** —— 多数 False 是「现在不是时候」。
    """
    today = today or _today()
    cid = cust.get("id")
    name = cust.get("name") or cid

    # ── 第一层:硬门槛 ────────────────────────────────────────
    #
    # ⚠️ 这里原来写的是「手上有任何订单在做就不促」,**改了**。
    # 定制周期长,一个客户常年有单在做是常态(这批数据里 89% 的客户都有),
    # 拿它当门槛等于把绝大多数人永久挡在外面。
    # 真正不该促的是**刚下过单** —— 人家刚买完,让他消停会儿。
    # 「在做的单」不是门槛,它是**聊进度的由头**,那属于服务不属于促活。
    刚买过 = _rows("""SELECT created FROM ordr WHERE customer_id=?
                      AND status NOT IN (?,?) AND created >= ?
                      ORDER BY created DESC LIMIT 1""",
                   cid, *订单终态, (today - datetime.timedelta(days=刚下过单)).isoformat())
    if 刚买过:
        return False, "JUST_BOUGHT", (
            f"{name}刚下过单 —— **刚买完就推新会掉价**"
            f"(门槛 {刚下过单} 天是**待校准的默认值**)")

    ph = ",".join("?" * len(售后终态))
    未结售后 = _rows(f"""SELECT id FROM aftersale WHERE customer_id=?
                        AND status NOT IN ({ph}) LIMIT 1""", cid, *售后终态)
    if 未结售后:
        return False, "AFTERSALE", f"{name}有未结的售后 —— **这时候推销是火上浇油**,先把售后办完"

    最近跟进 = _rows("""SELECT ts FROM followup WHERE customer_id=?
                        ORDER BY ts DESC LIMIT 1""", cid)
    if 最近跟进:
        d = _d(最近跟进[0]["ts"])
        if d and (today - d).days < 刚联系过:
            return False, "RECENT_CONTACT", (
                f"{(today-d).days} 天前刚联系过{name} —— 防骚扰,也防两个顾问撞车"
                f"(门槛 {刚联系过} 天是**待校准的默认值**)")

    # ── 第二层:由头(有一个就够,按强弱排) ──────────────────────
    理由 = []

    # ① 历史同期 —— 汉服的节庆性很强,而「他自己的历史同期」比一张节庆表更准,
    #    也不用维护农历。他去年这个月买过,今年这个月就是由头。
    # 这里只排除「取消」——「完成」的订单正是历史购买记录,不能排除。
    #
    # ⚠️ **必须排除今年**。第一版只写了 `created < 今天`,于是「今年这个月刚买过」
    # 也被算成「往年同期」,理由那句话自相矛盾:
    #     「他在 2026 年的这个月都下过单 —— 今年到现在还没动静」
    # **是那句人话把错误暴露出来的** —— 只看数量或只看布尔值,这个 bug 藏得住。
    同期 = _rows("""SELECT created, amount FROM ordr WHERE customer_id=?
                    AND status<>'取消'
                    AND CAST(strftime('%m', created) AS INTEGER)=?
                    AND CAST(strftime('%Y', created) AS INTEGER)<?
                    ORDER BY created DESC""",
                 cid, today.month, today.year)
    if 同期:
        年份 = sorted({_d(r["created"]).year for r in 同期 if _d(r["created"])})
        if 年份:
            理由.append(("ANNIVERSARY",
                        f"他在 {'、'.join(str(y) for y in 年份)} 年的这个月都下过单 —— 今年到现在还没动静"))

    # ② 生日临近
    bd = _d(cust.get("birthday"))
    if bd:
        今年生日 = bd.replace(year=today.year)
        差 = (今年生日 - today).days
        if 0 <= 差 <= 生日提前:
            理由.append(("BIRTHDAY", f"{差} 天后是{name}的生日"))

    # ③ 上一单做完该回访了
    完成单 = _rows("""SELECT finished_at FROM ordr WHERE customer_id=? AND finished_at IS NOT NULL
                      ORDER BY finished_at DESC LIMIT 1""", cid)
    if 完成单:
        d = _d(完成单[0]["finished_at"])
        if d and 回访窗口[0] <= (today - d).days <= 回访窗口[1]:
            理由.append(("POST_ORDER", f"上一单 {(today-d).days} 天前做完,到回访的时候了"))

    # ④ 维保到期
    维保 = _rows("""SELECT id, item FROM maintain WHERE customer_id=?
                    AND status NOT IN ('已完成','已关闭') LIMIT 1""", cid)
    if 维保:
        理由.append(("MAINTAIN", f"有一件「{维保[0]['item']}」的维保还没办完"))

    # ⑤ 断了自己的节奏 —— **不是「超过 N 天」,是「超过他自己的 N 倍」**
    节奏 = 他自己的节奏(cust)
    闲置 = cust.get("idle_days")
    if 节奏 and 闲置 is not None:
        if 闲置 > 节奏 * 断节奏倍数:
            理由.append(("RHYTHM_BREAK",
                        f"他平均 {节奏:.0f} 天来一次,这次已经 {闲置} 天了"
                        f"(**{断节奏倍数} 倍这个门槛是待校准的默认值**)"))
    elif 节奏 is None:
        # 算不出节奏。**「从没买过」和「买过但一年没买了」是两回事** —— 用首单区分
        if not cust.get("first_order"):
            pass        # 从来没下过单 —— 他不是「冷了」,是还没热过,不归促活管
        # 买过但 12 个月内 0 单的,已经由 ANNIVERSARY / RHYTHM 之外的路径覆盖不到,
        # 这里**不编一个理由出来** —— 没有由头就是没有由头

    if not 理由:
        return False, "NO_REASON", (
            f"{name}没有可说的由头 —— **闲置久本身不是理由**,"
            f"打过去不知道说什么,只会消耗关系")

    码, 话 = 理由[0]
    其余 = f";另外{'、'.join(t for _, t in 理由[1:])}" if len(理由) > 1 else ""
    return True, 码, 话 + 其余


def 一个人的判断(customer_id):
    r = _rows("SELECT * FROM customer WHERE id=?", customer_id)
    if not r:
        return None
    return should_revive(r[0])
