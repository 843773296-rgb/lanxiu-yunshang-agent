"""账户归属 —— **一个账户只归一位导购**(用户 2026-10-26 拍)。

一个账户 = 一个手机号 = 一位主要联系人;下面可以有好几位绑定的家人(着装人),
还可能有几条门店档案(同一个人建了两次档 —— 那是「客户合并」的事)。
**不管几条档案、几位家人,都归同一位导购。** 原来导购记在每条档案上、各配各的,
库里有 16 个账户底下两条档案归两位导购(11 个还跨店)。

**只管账户这一层,不往上合**(用户 10-26 拍):一个手机号 = 一个账户,导购只认账户。同一个人换了号、
有三个号,就是三个账户 —— 在三家店跟三位不同的导购是**合理的**,不按姓名生日去认「这是同一个人」再统一导购。

这里是这条规矩的唯一一份:转移(审批生效 / 后台直转)、修存量、门禁检查都调它,不各写一遍。
"""
import sqlite3


def 同户档案(c, ids):
    """客户号们 → 连同**同一账户下**的其它在用档案一起(保序、去重)。没有账户的就只是它自己。"""
    出 = []
    for i in ids:
        i = str(i).strip()
        if not i:
            continue
        r = c.execute("SELECT account_id FROM customer WHERE id=?", (i,)).fetchone()
        acc = r[0] if r else None
        同 = [i]
        if acc:
            同 += [x[0] for x in c.execute(
                "SELECT id FROM customer WHERE account_id=? AND COALESCE(merged_into,'')='' AND id!=? ORDER BY id",
                (acc, i))]
        for x in 同:
            if x not in 出:
                出.append(x)
    return 出


def 定归属(档案们, 在职):
    """一个账户底下的档案 → 该归哪一条档案的导购(用户 10-26 拍:按最近在跟的导购定)。

    档案们:[{id, advisor_no, last_interact, created, shop, shop_code}];在职:导购工号 → 是否在职。
    规则:**最近接触**那条的导购;打平取**建档更晚**的;那位已停用就顺延下一条(停用的派不了任务,
    归给他等于没人管)。一个在职的都没有 → None,交人定,不猜。
    """
    候 = [d for d in 档案们 if d.get("advisor_no") and 在职.get(d["advisor_no"])]
    if not 候:
        return None
    return max(候, key=lambda d: (d.get("last_interact") or "", d.get("created") or "", d["id"]))


def 冲突账户(c):
    """库里「一个账户两位以上导购」的账户号 —— 门禁要它是空的。"""
    return [r[0] for r in c.execute(
        "SELECT account_id FROM customer WHERE COALESCE(merged_into,'')='' AND COALESCE(account_id,'')!='' "
        "GROUP BY account_id HAVING COUNT(DISTINCT COALESCE(advisor_no,''))>1 ORDER BY account_id")]


def 改导购(c, ids, adv_no, shop=None, shop_code=None):
    """把这几位**连同同户的档案**一起归到 adv_no;给了门店就整户搬店。未完成的预约跟着迁。→ 实际改了的客户号。"""
    全 = 同户档案(c, ids)
    for i in 全:
        if shop:
            c.execute("UPDATE customer SET advisor_no=?, shop=?, shop_code=? WHERE id=?", (adv_no, shop, shop_code, i))
        else:
            c.execute("UPDATE customer SET advisor_no=? WHERE id=?", (adv_no, i))
    c.executemany("UPDATE appointment SET advisor_no=? WHERE customer_id=? AND status='已预约'",
                  [(adv_no, i) for i in 全])
    return 全


def 统一(c, 做=False):
    """修存量:每个冲突账户按 定归属 选一条,整户归到那位导购和那家店。→ [{账户, 归谁, 门店, 档案们, 搬店, 没法定}]"""
    c.row_factory = sqlite3.Row
    在职 = {r["no"]: (r["status"] or "启用") == "启用" for r in c.execute("SELECT no, status FROM staff")}
    出 = []
    for acc in 冲突账户(c):
        档 = [dict(r) for r in c.execute(
            "SELECT id, advisor_no, last_interact, created, shop, shop_code FROM customer "
            "WHERE account_id=? AND COALESCE(merged_into,'')=''", (acc,))]
        赢 = 定归属(档, 在职)
        if 赢 is None:
            出.append(dict(账户=acc, 归谁=None, 门店=None, 档案们=[d["id"] for d in 档], 搬店=False, 没法定=True))
            continue
        搬店 = any(d["shop_code"] != 赢["shop_code"] for d in 档)
        if 做:
            改导购(c, [赢["id"]], 赢["advisor_no"], 赢["shop"], 赢["shop_code"])
        出.append(dict(账户=acc, 归谁=赢["advisor_no"], 门店=赢["shop"], 按=赢["id"],
                       档案们=[d["id"] for d in 档], 原来={d["id"]: (d["advisor_no"], d["shop_code"]) for d in 档},
                       搬店=搬店, 没法定=False))
    return 出
