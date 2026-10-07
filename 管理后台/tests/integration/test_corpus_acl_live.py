#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**语料权限:在真 PG 上验** —— 还一笔点名记在交接里的欠账。

欠账原文:
> `语料可见.where片段()` **从没在真库上跑过** —— 那 72 组合对账是照 SQL 语义
> **用 Python 算的**,jsonb 的 `?|` 行为没在 PG 上验过。
>
> 一份「两种表示对账过了」的测试,和一份「对账的另一侧是我自己模拟的」,
> **在那 32 条绿勾上长得一模一样。**

## 为什么单独一个文件,而不是塞进 `test_retrieval.py`

`test_retrieval.py` 开头有一道洁净度闸(非终态 index_build 任务必须为 0、
`embeddings` 必须为空),而 2026-10-07 量到库里积了 **209 条 `attempts=0`、
从没被租过**的「排队中」index_build —— 那是历次集成测试**跑到一半中断、
清理段没执行**留下的,日期从 09-27 到 10-02。
闸是对的(脏状态上的结论不可信),但它让那份测试现在**一条都跑不了**。

而这笔欠账的核心**不需要索引**:`?|` 的行为不需要任何数据,两种表示对账只要
`documents` 和 `knowledge_bases`。所以抽出来,它现在就能跑。

需要索引的那两条(admin 召回正常 / viewer 抛「一条都看不到」)留在
`test_retrieval.py` 第 ④ 节,等库干净了跟那份一起跑。

## ⚠️ 这个文件**一个字都不会留在库里**

两级 ACL 今天全库是空的(量过:`kb.acl` 全空、178 篇 `acl_override` 0 篇有值)。
所以这里**在一个事务里填、验完 rollback**:
> 一次「测完清理干净了」和一次「测完忘了清理、而恰好没人去看那张表」,
> 在那次绿勾上长得一模一样 —— 而 rollback 让「忘了清理」**不可能发生**。

留下脏 ACL 的代价不是报错,是**下一个去量「这个字段有没有人填过」的人得出错结论** ——
而那个结论会决定他要不要去写「填进去长什么样」。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))

from sqlalchemy import create_engine, text   # noqa: E402
import 语料可见 as KV                          # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("=" * 92)
print("语料权限 · 在真 PG 上验(两级 ACL 填完即 rollback,库里不留痕)")
print("=" * 92)

print("\n▸ ⓪ 最底层那个假设:`?|` 在空 ACL 上返回什么")
# 这一条是 `where片段` 整个写法的地基。**它不需要任何数据**,
# 所以它是这笔欠账里最该先还的部分。
with eng.connect() as c:
    r = c.execute(text("""
        select ('{"roles":["admin"]}'::jsonb -> 'roles') ?| array['admin'] 命中,
               ('{"roles":["admin"]}'::jsonb -> 'roles') ?| array['viewer'] 不中,
               (null::jsonb -> 'roles') ?| array['admin'] 空的,
               ('{}'::jsonb -> 'roles') ?| array['admin'] 没这个键,
               ('{"roles":[]}'::jsonb -> 'roles') ?| array['admin'] 空数组
    """)).first()
ck("角色在清单里 → true", r[0] is True, r[0])
ck("不在清单里 → false", r[1] is False, r[1])
ck("🔑 **空 ACL 上 `?|` 返回的是 NULL,不是 false** —— 这才是 `where片段` 里"
   "那个 `is null or` 不可省的理由:NULL 在 WHERE 里当假,少了那一支,"
   "「没说过」就变成了「谁都看不见」(两种读法后果正好相反)",
   r[2] is None, f"null→{r[2]!r}")
ck("`{}`(有 jsonb 没 roles 键)也是 NULL,和 null 同路", r[3] is None, r[3])
ck("⚠️ 而 `{\"roles\":[]}`(真的空数组)是 **false,不是 NULL** —— "
   "它走的是另一支。纯判定那边把空数组当「没说过」处理,"
   "**所以这一格是两种表示唯一可能分叉的地方**,下面第 ② 节专门对它对账",
   r[4] is False, f"[]→{r[4]!r}")

print("\n▸ ① 两种表示在真库上对账(填 ACL → 对账 → rollback)")
with eng.connect() as conn:
    proj, kb = conn.execute(text("""
        select d.project_id, d.knowledge_base_id from documents d
         where d.disabled_at is null
         group by d.project_id, d.knowledge_base_id
         order by count(*) desc limit 1""")).first()
    篇数 = conn.execute(text("""select count(*) from documents
                              where project_id=:p and knowledge_base_id=:k"""),
                      {"p": proj, "k": kb}).scalar()
ck("找到一个有文档的知识库", 篇数 > 1, f"{篇数} 篇")
if 篇数 < 2:
    print("\n❌ 这个库里文档太少,对账没有意义 —— **不在样本量不够时出结论**")
    sys.exit(1)

名单们 = {}
c = eng.connect()
tx = c.begin()
try:
    # ── ⓪.5 **两级都空 → 谁都看得到** ───────────────────────────────────
    # ⚠️ 这一节是咬合第三关抓出来的:原先第一个用例就把 `kb.acl` 填上了,
    # 于是每一篇的 `coalesce` 都取到有值的那一级 ——
    # **没有任何用例走到 `is null` 那一支**。去掉整个 `is null or` 分支,
    # 18 条照样全过。
    # > 一条「验了 `?|` 对 NULL 返回 NULL」的检查,和一条「验了片段在空 ACL 上
    # > 真的放行」的,**在那个绿勾上长得一模一样** ——
    # > 前者只验了 PG 的行为,没验**我的 SQL 用对了它**。
    # 而库的真实状态恰好就是两级全空,所以**填之前先对账一次**就覆盖了。
    for 角色 in ("admin", "viewer"):
        片段, 参 = KV.where片段(这个人的角色们=[角色], 知识库别名="kb2")
        空名单 = {x[0] for x in c.execute(text(f"""
            select d.id from documents d
              join knowledge_bases kb2 on kb2.project_id=d.project_id
                                      and kb2.id=d.knowledge_base_id
             where d.project_id=:p and d.knowledge_base_id=:k and {片段}
        """), {"p": proj, "k": kb, **参})}
        ck(f"🔑 两级 ACL 都空(库今天的真实状态)时 `{角色}` **看得到全部 "
           f"{篇数} 篇** —— 这一条覆盖 `is null` 那一支",
           len(空名单) == 篇数, f"{len(空名单)}/{篇数}")

    c.execute(text("update knowledge_bases set acl=:a where project_id=:p and id=:k"),
              {"a": json.dumps({"roles": ["admin", "approver", "editor"]}),
               "p": proj, "k": kb})
    # 两篇分别收紧成不同的范围 —— 名单必须因角色而异,否则对账是空洞的
    两篇 = [x[0] for x in c.execute(text("""
        select id from documents where project_id=:p and knowledge_base_id=:k
         order by id limit 2"""), {"p": proj, "k": kb})]
    c.execute(text("update documents set acl_override=:a where project_id=:p and id=:d"),
              {"a": json.dumps({"roles": ["admin"]}), "p": proj, "d": 两篇[0]})
    c.execute(text("update documents set acl_override=:a where project_id=:p and id=:d"),
              {"a": json.dumps({"roles": ["admin", "approver"]}),
               "p": proj, "d": 两篇[1]})

    for 角色 in ("admin", "approver", "editor", "viewer"):
        片段, 参 = KV.where片段(这个人的角色们=[角色], 知识库别名="kb2")
        sql名单 = {x[0] for x in c.execute(text(f"""
            select d.id from documents d
              join knowledge_bases kb2 on kb2.project_id=d.project_id
                                      and kb2.id=d.knowledge_base_id
             where d.project_id=:p and d.knowledge_base_id=:k and {片段}
        """), {"p": proj, "k": kb, **参})}
        纯名单 = set()
        for did, kacl, dacl in c.execute(text("""
            select d.id, kb2.acl, d.acl_override from documents d
              join knowledge_bases kb2 on kb2.project_id=d.project_id
                                      and kb2.id=d.knowledge_base_id
             where d.project_id=:p and d.knowledge_base_id=:k
        """), {"p": proj, "k": kb}):
            行, _ = KV.看得到吗(这个人的角色们=[角色], 知识库acl=kacl, 文档acl=dacl)
            if 行:
                纯名单.add(did)
        名单们[角色] = sql名单
        ck(f"🔑 `{角色}`:**真库上 SQL 过滤和纯判定给同一份名单**",
           sql名单 == 纯名单,
           f"SQL {len(sql名单)} / 纯 {len(纯名单)}"
           + (f" / 差 {sorted(sql名单 ^ 纯名单)[:3]}" if sql名单 != 纯名单 else ""))

    ck("🔑 对照:这几个角色的名单**不是全都一样** —— 全一样的话上面那组对账"
       "是空洞的(一个恒返回全部文档的 where 片段也能全过)",
       len({frozenset(v) for v in 名单们.values()}) > 1,
       {k2: len(v) for k2, v in 名单们.items()})
    ck("文档级那两笔真的收紧了:editor 看不到被收紧的那两篇",
       not ({两篇[0], 两篇[1]} & 名单们["editor"]),
       sorted({两篇[0], 两篇[1]} & 名单们["editor"]))
    ck("approver 看得到只收到 {admin,approver} 那篇、看不到只收到 {admin} 那篇",
       两篇[1] in 名单们["approver"] and 两篇[0] not in 名单们["approver"])
    ck("viewer 在**知识库那一级**就被拦住 —— 一篇都没有",
       not 名单们["viewer"], len(名单们["viewer"]))

    print("\n▸ ② 那个唯一可能分叉的格子:`acl_override = {\"roles\": []}`")
    # ⓪ 里量到:真的空数组在 PG 上 `?|` 返回 **false**(走另一支),
    # 而纯判定把空数组当「没说过」→ 继承知识库。**两边会不一样。**
    # > 一个「故意设成谁都看不见」的 ACL,和一个「前端传空了」的,
    # > 在那个 `[]` 上长得一模一样 —— 纯判定选了后一种读法。
    # 这一节不是「验它一致」,是**把不一致量出来并写在这儿**。
    c.execute(text("update documents set acl_override=:a where project_id=:p and id=:d"),
              {"a": json.dumps({"roles": []}), "p": proj, "d": 两篇[0]})
    片段, 参 = KV.where片段(这个人的角色们=["editor"], 知识库别名="kb2")
    sql看得到 = bool(c.execute(text(f"""
        select 1 from documents d
          join knowledge_bases kb2 on kb2.project_id=d.project_id
                                  and kb2.id=d.knowledge_base_id
         where d.project_id=:p and d.id=:d and {片段}
    """), {"p": proj, "d": 两篇[0], **参}).first())
    kacl, dacl = c.execute(text("""
        select kb2.acl, d.acl_override from documents d
          join knowledge_bases kb2 on kb2.project_id=d.project_id
                                  and kb2.id=d.knowledge_base_id
         where d.project_id=:p and d.id=:d"""),
        {"p": proj, "d": 两篇[0]}).first()
    纯看得到, 为什么 = KV.看得到吗(这个人的角色们=["editor"],
                            知识库acl=kacl, 文档acl=dacl)
    ck("🔑 **空数组这一格两种表示也一致** —— 2026-10-07 第一次在真 PG 上跑"
       "量到它们不一致(SQL 说看不到、纯判定说看得到),修法是 where 片段里的 "
       "`nullif(..., '[]'::jsonb)`:`coalesce` 只对 NULL 生效,而 `[]` 不是 NULL",
       sql看得到 == 纯看得到,
       f"SQL {sql看得到} / 纯判定 {纯看得到} —— 都该是 True(继承知识库,editor 在范围里)")
    ck("而且结论是**两边都看得到**(不是两边都看不到) —— "
       "口径在 `_规范()` 定过:空当「没说过」,因为它更可能是前端传了个空数组;"
       "真要谁都看不见,业务该用停用文档(`disabled_at`)",
       sql看得到 is True and 纯看得到 is True, (sql看得到, 纯看得到))
    ck("⚠️ 对照:这个分叉**不可能被 72 组合的纯逻辑对账抓到** —— "
       "那两边都调同一个 `_规范()`,对账的另一侧不是独立实现(同源谬误的变种)。"
       "它只能在真库上被量出来,而交接里那笔欠账正是为它记的",
       "nullif" in KV.where片段(这个人的角色们=["admin"])[0],
       KV.where片段(这个人的角色们=["admin"])[0][:60])
finally:
    # ⚠️ **rollback 而不是「改回去」** —— 改回去要写对每一个 UPDATE,
    # 而 rollback 不需要我记得改了几张表。
    tx.rollback()
    c.close()

with eng.connect() as c:
    留 = c.execute(text("select count(*) from knowledge_bases where acl is not null")
                   ).scalar()
    留2 = c.execute(text("select count(*) from documents where acl_override is not null")
                    ).scalar()
ck("跑完**全库一条 ACL 都没留下**(两级都空,和跑之前一样)",
   留 == 0 and 留2 == 0, f"kb.acl {留} 条 / acl_override {留2} 条")

print("\n" + "=" * 92)
print(f"{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
