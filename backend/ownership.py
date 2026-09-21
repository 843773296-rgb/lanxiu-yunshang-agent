# -*- coding: utf-8 -*-
"""客户归属:谁长期跟这个客户,以及这件事是怎么发生的。

业务 2026-09-20 定:**归属在「首次到店接待完成」时确立**,不在预约时。
理由:75 条预约里 27 条已取消(36%)。预约时就定归属,会留下一批
「归了名但从没见过面」的客户 —— **而他们和真建立了关系的客户,在库里分不开**。

## 查库查出来的三件事(这个模块要解决的)

**① 归属只有结果,没有过程。**
`customer` 表关于顾问**只有一个字段**:现在归谁。
没有「什么时候归的」「谁定的」「之前归谁」。变更日志 542 条**全是商品**。
→ 「这个客户为什么是张三的」——系统答不上来。

**② 「有归属顾问」和「有人管」不是一回事。**
一个停用的顾问名下还挂着 3 个客户,他接待的预约是 0,
而他名下客户的预约全由别人接待。**这 3 个客户实际无人管理,
但任何按「有没有顾问」筛的逻辑都查不出他们** —— 因为字段非空。

**③ 「无主」这个状态一次都没发生过**(965 个客户 100% 有顾问),
而结构是允许为空的 —— 所以是**数据没造,不是系统不支持**。

## ⚠️ 这个模块**不自动改数据**

业务定的边界:**agent 只给参谋。**
「这个客户的归属顾问已离职」是一个**事实**,该做的是**把它摆出来**;
改不改归属是店长的业务动作 —— 他可能想等交接、想指给特定的人、
也可能这个客户马上要复购不宜此时换人。

所以这里只有两样:**查出来**、**变更时留痕**。没有一行自动 update。
"""
import os, sqlite3, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 判定口径在 knowledge/owner.py,这里只取数 —— **口径不许在这里再抄一份**。
# (模块叫 owner 不叫 ownership:和这个文件同名的话,`import ownership`
#  会先找到这个文件自己,而「导入成功了」和「导入对了」长得一样。)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
import owner as _口径
DB = os.path.join(HERE, "lanxiu.db")

# 归属确立/变更的依据 —— **必须记,因为将来一定有人问「凭什么是他的」**
依据 = ("客户点名", "首次接待确立", "店长指定", "顾问离职重分", "客户要求更换")


def 建表(c):
    # ⚠️ 外键显式写(假数据工厂靠它认引用);**不加复合唯一约束** ——
    # 工厂认单列 UNIQUE 但不认复合的,踩过一次(见 roster.py 的说明)。
    c.execute("""create table if not exists cust_owner_log(
                   id INTEGER primary key autoincrement,
                   customer_id TEXT not null references customer(id),
                   frm      TEXT,              -- 空 = 原来无主
                   too      TEXT,              -- 空 = 进公海
                   action   TEXT not null,     -- 确立 / 转移 / 进公海
                   basis    TEXT not null,     -- 依据(见上面那个元组)
                   actor    TEXT not null,
                   ts       TEXT not null)""")


def 实际无人管理(db=DB):
    """归属字段非空,但那个人管不了 —— **口径在 `knowledge/owner.py`,这里只取数**。

    五种码(2026-09-21 从四种加到五种,多的是 NO_SHOP),
    分开的唯一理由是**下一步动作不同**;码的含义和优先级看那个模块。
    """
    return [(r["id"], r["name"], r["码"], r["说法"]) for r in 明细(db)]


def 明细(db=DB):
    """同上,但带「下一步该做什么」—— 工具层要的是这一份。

    **分成几种码的全部理由就是下一步不同**,所以给人/给模型看的那一份
    必须把动作带上;只给一个码,读的人还得自己去翻这几个码是什么意思。
    """
    out = []
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        for r in c.execute("""
            select cu.id, cu.name, cu.shop, cu.advisor_no, s.name adv_name,
                   s.status adv_status, s.shop adv_shop, s.no adv_no
            from customer cu left join staff s on s.no = cu.advisor_no"""):
            判 = _口径.判({"advisor_no": r["advisor_no"],
                          # ⚠️ 用 `s.no is not None` 判「查到了没有」,**不用姓名** ——
                          # 姓名为空的员工和不存在的员工,在 `adv_name is None` 下长得一样。
                          "adv_found": r["adv_no"] is not None,
                          "adv_name": r["adv_name"], "adv_status": r["adv_status"],
                          "cust_shop": r["shop"], "adv_shop": r["adv_shop"]})
            if 判:
                out.append({"id": r["id"], "name": r["name"],
                            "门店": r["shop"], **判})
    return out


def 待确立(db=DB):
    """到店接待完成、但归属还没确立的客户 —— **归属该在这一刻定**。

    判据:有「已到店」或「已完成」的预约,而 `cust_owner_log` 里没有确立记录。
    """
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        建表(c)
        return [dict(r) for r in c.execute("""
            select a.customer_id, cu.name, cu.shop 门店, a.advisor_no 接待人,
                   a.start_ts, a.status
            from appointment a join customer cu on cu.id = a.customer_id
            where a.status in ('已到店','已完成')
              and not exists (select 1 from cust_owner_log g
                              where g.customer_id = a.customer_id and g.action='确立')
            order by a.start_ts""")]


def 记一笔(customer_id, frm, too, action, basis, actor, ts=None, db=DB):
    """记录一次归属变更。**只记,不改 customer 表** —— 改不改是店长的动作。"""
    if basis not in 依据:
        raise ValueError(f"依据必须是 {依据} 之一,给的是「{basis}」—— "
                         f"**不写依据等于把过程又丢了一次**")
    ts = ts or datetime.date.today().isoformat()
    with sqlite3.connect(db) as c:
        建表(c)
        c.execute("""insert into cust_owner_log(customer_id,frm,too,action,basis,actor,ts)
                     values(?,?,?,?,?,?,?)""",
                  (customer_id, frm, too, action, basis, actor, ts))


def 给店长的清单(db=DB):
    """一句话版本,给人看的。"""
    无人 = 实际无人管理(db)
    待 = 待确立(db)
    按码 = {}
    for _, _, 码, _ in 无人:
        按码[码] = 按码.get(码, 0) + 1
    return {"实际无人管理": 按码, "总数": len(无人), "待确立归属": len(待)}


if __name__ == "__main__":
    d = 给店长的清单()
    print("实际无人管理:", d["总数"], "人", d["实际无人管理"] or "(无)")
    print("到店接待完成、归属还没确立:", d["待确立归属"], "人")
