#!/usr/bin/env python3
"""数据规范检查 —— 逐条对着 `数据规范.md` 的编号验。

## 为什么单独一个文件

规范里每条都标了「谁来守」。标了**检查**的,就得真有一段代码守着 ——
否则那一栏写的是「检查」,实际是「暂无」,而**这两者在文档里长得一模一样**。

这个文件就是那一栏的兑现。红了要么是数据破了,要么是规范该改了,
**两种都得人看一眼**,不许直接把断言改松。

## 它和别的检查的分工

    member_order_check   订单/会员的勾稽与时间链
    lifecycle_check      着装人/同意/量体的业务完整性
    **spec_check**       **规范本身**:身份、关联、覆盖这三类跨表的硬规矩
"""
import os, sys, sqlite3
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import api

T = date(2026, 8, 31)
c = sqlite3.connect(api.DB); c.row_factory = sqlite3.Row
q = lambda s, *a: [dict(r) for r in c.execute(s, a)]
bad, note = [], []


def rule(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    if rows:
        for r in rows[:3]: print(f"       {r}")
        if len(rows) > 3: print(f"       …… 共 {len(rows)} 条")
        bad.append((no, why, len(rows)))


print("数据规范检查 · 对照《数据规范.md》\n" + "=" * 84)

# ── 一、身份 ────────────────────────────────────────────────────────────
rule("A3", "每个账户至少有一个着装人",
     q("""SELECT a.id FROM account a
          WHERE NOT EXISTS(SELECT 1 FROM wearer w WHERE w.account_id=a.id)"""),
     "一个连「衣服穿在谁身上」都答不出的账户,做定制没法用")

rule("A7", "账户持有人必须成年",
     [r for r in q("""SELECT a.id, w.birthday FROM account a
                      JOIN wearer w ON w.id=a.self_wearer_id WHERE w.birthday IS NOT NULL""")
      if (T - date.fromisoformat(r["birthday"])).days / 365.25 < 18],
     "拍过板的决定:孩子只做着装人,不做账户持有人 —— "
     "让未成年持有账户会把个保法 31 条的监护人同意义务拉进登录链路")

rule("A8", "每个账户有且只有一个「本人」,且 self_wearer_id 指向它",
     q("""SELECT a.id,
            (SELECT count(*) FROM wearer w WHERE w.account_id=a.id AND w.relation='本人') n,
            a.self_wearer_id
          FROM account a
          WHERE n <> 1 OR a.self_wearer_id IS NULL
             OR a.self_wearer_id NOT IN (SELECT id FROM wearer WHERE account_id=a.id
                                          AND relation='本人')"""),
     "「本人」要能指出来,而不是靠 relation 字符串去猜")

rule("A9", "旧号别名不得与现有登录号相撞",
     q("SELECT p.phone FROM phone_alias p JOIN account a ON a.phone=p.phone"),
     "别名是为了让旧号还能找到人;撞上现有登录号就成了两个人抢一个号")

# A10 是提示,不是错误 —— 着装人的联系号等于某账户的登录号,说明这人自己也有账户
_a10 = q("""SELECT w.id wearer, w.name, a.id acct FROM wearer w
            JOIN account a ON a.phone = w.phone
            WHERE w.account_id <> a.id""")
if _a10: note.append(("A10", f"{len(_a10)} 个着装人本人也有自己的账户(可关联,不是冲突)"))

# ── 二、关联 ────────────────────────────────────────────────────────────
REF = {"customer_id": "customer", "order_id": "ordr", "account_id": "account",
       "wearer_id": "wearer", "spu": "product", "sku": "sku", "pattern": "pattern",
       "artisan": "artisan", "task_id": "task", "deposit_id": "deposit",
       "self_wearer_id": "wearer", "parent_a": "wearer", "parent_b": "wearer"}
tabs = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not t[0].startswith("sqlite")]
dangling = []
for t in tabs:
    cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
    for col in cols:
        ref = REF.get(col)
        if not ref or ref not in tabs or ref == t: continue
        pk = [x[1] for x in c.execute(f"PRAGMA table_info({ref})")][0]
        n = c.execute(f"SELECT count(*) FROM {t} WHERE {col} IS NOT NULL "
                      f"AND {col} NOT IN (SELECT {pk} FROM {ref})").fetchone()[0]
        if n: dangling.append({"表": f"{t}.{col}", "指向": ref, "对不上": n})
rule("B2", "全库没有悬空引用", dangling, "指向不存在的对象")

rule("B3", "着装人的账户 == 它建档门店档案的账户",
     q("""SELECT w.id FROM wearer w JOIN customer k ON k.id=w.customer_id
          WHERE w.account_id <> k.account_id"""),
     "**「指向存在的对象」不等于「指向对的对象」** —— 错位那次指的也是真实客户,"
     "只有两条路径对账才抓得到")

rule("B4", "生产工单指向真实订单",
     q("SELECT id, ref FROM workorder WHERE ref IS NULL OR ref NOT IN (SELECT id FROM ordr)"),
     "不接真订单,「我的衣服做到哪了」就答不了,产能排期成孤岛")

# ── 三、属性一致 ────────────────────────────────────────────────────────
rule("D1", "地址串必须和省市一致",
     q("SELECT id, province, addr FROM customer "
       "WHERE addr IS NOT NULL AND province IS NOT NULL AND addr NOT LIKE province||'%'"),
     "同一个事实两个来源,必然漂 —— 地址跟着省市生成,只留一个来源")

# ── 四、覆盖 ────────────────────────────────────────────────────────────
# E2:两个维度不得完全相关。可测形式 = 按 A 分组后 B 是否恒定。
def corr(tab, a, b):
    rows = q(f"SELECT {a} ka, count(DISTINCT {b}) n FROM {tab} GROUP BY {a}")
    return [r for r in rows if r["n"] == 1] if len(rows) > 1 else []
_e2 = []
for tab, a, b in [("maintain", "status", "issue"), ("maintain", "issue", "status")]:
    if len(corr(tab, a, b)) == len(q(f"SELECT DISTINCT {a} x FROM {tab}")):
        _e2.append({"表": tab, "维度": f"{a} ↔ {b}", "问题": "完全相关"})
rule("E2", "两个维度不得完全相关(否则覆盖度悄悄坍缩)", _e2,
     "状态和问题都用 i%7 时,按状态筛出来的工单永远只有一类 —— "
     "**数据看起来正常,覆盖度却只剩 1/7**")

print("\n" + "=" * 84)
for no, msg in note: print(f"  ℹ {no}  {msg}")
if bad:
    print(f"\n❌ {len(bad)} 条规范没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    print("   **不要直接把断言改松** —— 要么数据破了,要么规范该改了,两种都得人看一眼。")
    sys.exit(1)
print(f"✅ 规范全部守住(A3/A7/A8/A9 · B2/B3/B4 · D1 · E2)")
