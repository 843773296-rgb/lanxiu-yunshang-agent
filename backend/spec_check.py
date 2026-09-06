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
          WHERE a.status <> '已注销'
            AND NOT EXISTS(SELECT 1 FROM wearer w WHERE w.account_id=a.id)"""),
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
          WHERE a.status <> '已注销' AND (n <> 1 OR a.self_wearer_id IS NULL
             OR a.self_wearer_id NOT IN (SELECT id FROM wearer WHERE account_id=a.id
                                          AND relation='本人'))"""),
     "「本人」要能指出来,而不是靠 relation 字符串去猜")

rule("A9", "旧号别名不得与现有登录号相撞",
     q("SELECT p.phone FROM phone_alias p JOIN account a ON a.phone=p.phone"),
     "别名是为了让旧号还能找到人;撞上现有登录号就成了两个人抢一个号")

# A10 是提示,不是错误 —— 着装人的联系号等于某账户的登录号,说明这人自己也有账户
_a10 = q("""SELECT w.id wearer, w.name, a.id acct FROM wearer w
            JOIN account a ON a.phone = w.phone
            WHERE w.account_id <> a.id""")
if _a10: note.append(("A10", f"{len(_a10)} 个着装人本人也有自己的账户(可关联,不是冲突)"))

rule("A11", "账户状态与注销时间一致",
     q("""SELECT id,status,closed_at,purge_at FROM account WHERE
            (status='注销中' AND (closed_at IS NULL OR purge_at IS NOT NULL))
         OR (status='已注销' AND (closed_at IS NULL OR purge_at IS NULL))
         OR (status IN ('正常','锁定') AND (closed_at IS NOT NULL OR purge_at IS NOT NULL))"""),
     "注销中是冷静期(数据还在),已注销是数据已删 —— 状态和时间戳对不上,"
     "就说不清这个账户到底在哪一步")

rule("A12", "已注销账户名下不得留有身体数据",
     q("""SELECT a.id,
            (SELECT count(*) FROM wearer w WHERE w.account_id=a.id) w,
            (SELECT count(*) FROM measure_rec m JOIN customer k ON k.id=m.customer_id
             WHERE k.account_id=a.id) m
          FROM account a WHERE a.status='已注销' AND (w>0 OR m>0)"""),
     "身体数据是敏感个人信息,注销后**没有保留依据** —— "
     "只清账户那一行会留下孤儿:人删了,尺寸还躺在库里")

rule("A13", "已注销账户的门店档案已去标识化,且订单仍在",
     q("""SELECT k.id, k.name, k.phone FROM customer k JOIN account a ON a.id=k.account_id
          WHERE a.status='已注销'
            AND (k.name <> '已注销用户' OR k.phone NOT LIKE 'DELETED-%'
                 OR k.addr IS NOT NULL OR k.birthday IS NOT NULL)"""),
     "**删多了违约,删少了违法** —— 个人标识必须去掉,订单这类经营记录必须留着")

rule("A14", "锁定账户必须有失败次数与解锁时间",
     q("""SELECT id FROM account WHERE status='锁定'
          AND (fail_count IS NULL OR fail_count=0 OR locked_until IS NULL)"""),
     "锁了却说不出为什么锁、什么时候解 —— 客服没法答复客户")

rule("A15", "有在办业务的账户不得注销",
     q("""SELECT a.id, a.status FROM account a JOIN customer k ON k.account_id=a.id
          WHERE a.status IN ('注销中','已注销') AND (
               EXISTS(SELECT 1 FROM maintain t WHERE t.customer_id=k.id
                      AND t.status NOT IN ('已完成','取消'))
            OR EXISTS(SELECT 1 FROM ordr o WHERE o.customer_id=k.id
                      AND o.status NOT IN ('完成','取消')))"""),
     "**冷静期存在的意义正是等这些事了结** —— 衣服还在做、维修还没交,"
     "人把账号注销了、身体数据一删,这单就没法收尾")

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

# ── C3:通用时间链 ──────────────────────────────────────────────────────
# 「任何记录的时间不得早于它所属对象的创建时间」——
# 原来是**逐表写死**的 8 处,新加一张带时间的表就没人记得补。
# 这里从**外键关系 + 列名**自动推出来,新表自动进入覆盖范围。
#
# 之所以值得做成通用:C1 那次就是因为漏了 `created` 这一环,
# 「付款早于下单」35/35 全错却长年没被发现 ——
# **一条链上少查一环,那一环就会长年错着。**
TIME_HINT = ("_at", "_ts", "created", "measured_at", "signed_at", "updated")
def _timecols(t):
    return [x[1] for x in c.execute(f"PRAGMA table_info({t})")
            if any(h in x[1] for h in TIME_HINT) and x[1] not in ("purge_at", "closed_at",
                                                                  "locked_until", "synced_at",
                                                                  "on_shelf_at")]
c3 = []
for t in tabs:
    cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
    for fk, ref in REF.items():
        # **父锚点只取业务对象。**
        # `wearer.created` / `account.created` 是**系统建档时间**,不是业务发生时间 ——
        # 真实迁移里所有着装人的建档时间都是「上线那天」,而量体可以是几个月前的事。
        # 拿建档时间当下限,会把 171 条正常的量体记录判成违规。
        # **建档时间 ≠ 业务发生时间**,这条分界线不划清,C3 就只会制造噪音。
        if ref not in ("customer", "ordr", "deposit", "product"): continue
        if fk not in cols or ref not in tabs or ref == t: continue
        if "created" not in [x[1] for x in c.execute(f"PRAGMA table_info({ref})")]: continue
        pk = [x[1] for x in c.execute(f"PRAGMA table_info({ref})")][0]
        for tc in _timecols(t):
            n = c.execute(f"""SELECT count(*) FROM {t} x JOIN {ref} p ON p.{pk}=x.{fk}
                              WHERE x.{tc} IS NOT NULL AND p.created IS NOT NULL
                                AND substr(x.{tc},1,10) < substr(p.created,1,10)""").fetchone()[0]
            if n: c3.append({"记录": f"{t}.{tc}", "早于": f"{ref}.created", "条数": n})
rule("C3", "任何记录的时间不得早于它所属对象的创建时间", c3,
     "**一条链上少查一环,那一环就会长年错着** —— "
     "C1 漏了 created,「付款早于下单」35/35 全错却长年没人发现")

# ── 四之二、身体数据 ────────────────────────────────────────────────────
rule("G1", "体型特征挂着装人,且不挂在未成年身上",
     q("""SELECT b.rowid, b.wearer_id FROM body_feature b
          WHERE b.wearer_id IS NULL OR b.wearer_id NOT IN (SELECT id FROM wearer)
             OR b.wearer_id IN (SELECT id FROM wearer WHERE relation IN ('子','女'))"""),
     "**它已经在算错尺码**:挂客户档案时,妈妈的「溜肩」会让 3 岁儿子被推成全定制。"
     "溜肩/含胸/高低肩/腹凸是成人体型问题,给孩子记等于造假数据")

rule("G2", "量体记录必须记全三件事(数值 + 条件 + 量体人和时间)",
     q("""SELECT id, item FROM measure_rec
          WHERE value IS NULL OR measured_by IS NULL OR measured_at IS NULL
             OR cond_inner IS NULL OR cond_shoe IS NULL OR cond_breath IS NULL"""),
     "08 第四节:「**缺一件就等于没量**」。没记条件的尺寸,"
     "返修时无法判断是量错了还是穿法变了 —— 争议只能靠嗓门解决")

rule("G3", "推算留档能追到它依据的那次量体",
     q("""SELECT g.id, g.wearer_id, g.base_at FROM growth_forecast g
          WHERE NOT EXISTS(SELECT 1 FROM measure_rec m
                           WHERE m.wearer_id=g.wearer_id AND m.item='MI01'
                             AND substr(m.measured_at,1,10)=g.base_at)"""),
     "留档存的**不是结果,是当时怎么推的** —— 追不到依据的那次量体,"
     "事后客户问「你们当时说什么」就答不了")

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

# E3:**反例必须还在。**
# 「把数据补齐」是一类看起来永远正确的改动,而它会静默清空反例:
# 量体一补全,判责规则「记录不全 · 我方免费改」就再也没有用例;
# 父母身高一规整,「靶身高冲突需人工确认」就再也不会触发。
# 没有用例的规则可以是错的,而且永远不会被发现 —— 所以反例要当资产来守。
_e3 = []
if not q("""SELECT m.id FROM maintain m
            WHERE m.issue='尺寸需调整' AND m.status IN ('待确认','待处理','处理中')
              AND (SELECT count(*) FROM measure_rec r WHERE r.customer_id=m.customer_id) < 4
            LIMIT 1"""):
    _e3.append({"缺": "量体记录不全的尺寸类在办工单", "影响": "判责「记录不全 · 我方免费改」无用例"})
if not q("""SELECT k.id FROM wearer k JOIN wearer f ON f.id=k.parent_a
                                     JOIN wearer m ON m.id=k.parent_b
            WHERE f.height IS NOT NULL AND m.height IS NOT NULL
              AND (f.height + m.height) / 2 < 160 LIMIT 1"""):
    _e3.append({"缺": "父母中亲值明显偏低的孩子", "影响": "靶身高「需人工确认」无用例"})
if not q("SELECT id FROM workorder WHERE status='在制' AND due_date < date('now') LIMIT 1"):
    _e3.append({"缺": "已逾期的在制工单", "影响": "get_workorder 的「已逾期」分支无用例"})
rule("E3", "反例夹具必须还在(别好心把不完整的数据补全)", _e3,
     "补数据是看起来永远正确的改动,但它会顺手把反例清零 —— "
     "**seed.py 里那段「反例夹具」不许删,也不许补全**")

# ── 六、工具返回 ────────────────────────────────────────────────────────
# T1:**工具不许把空字段发给模型。**
# 换模型对照时露出来的:同一个问题,一个模型走 kb_lead 答「香云纱备料 12 天」,
# 另一个走 kb_detail 答「知识库里还没录入」—— 因为 craft.lead_days 对材质恒空,
# 而真正的备料天在 material 表里。**工具说了假话,模型没错。**
# 更普遍的一半是 cost_level:它只对工艺条目有意义,对形制/材质就是「不适用」,
# 可 null 把「未录入」和「不适用」说成了同一件事,模型只能照字面讲。
import api as _api
_t1 = []
for _r in q("SELECT code FROM craft ORDER BY code"):
    _d = _api.kb_detail(_r["code"])
    for _k, _v in _d.items():
        if _v in (None, ""):
            _t1.append({"编码": _r["code"], "字段": _k})
rule("T1", "工具返回里不许有空字段(null 会被如实报成「未录入」)", _t1,
     "少一个字段模型不会提它;给一个空字段模型一定会提它 —— "
     "而它分不清「未录入」和「这一类根本没这项」")

print("\n" + "=" * 84)
for no, msg in note: print(f"  ℹ {no}  {msg}")
if bad:
    print(f"\n❌ {len(bad)} 条规范没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    print("   **不要直接把断言改松** —— 要么数据破了,要么规范该改了,两种都得人看一眼。")
    sys.exit(1)
print("✅ 规范全部守住(A3/A7/A8/A9/A11–A15 · G1–G3 · B2/B3/B4 · D1 · E2/E3 · T1)")
