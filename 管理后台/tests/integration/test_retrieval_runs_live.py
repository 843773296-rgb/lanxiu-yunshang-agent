#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索试跑记录 —— **真的去攻击那几条 CHECK**(真 PG)。业务 2026-10-08 的栏目。

## 为什么这一份必须存在

接口里写着「评分要是 1-5 的整数」,而那是**一个写入方的 if**。
下一个写入方(补数据的 SQL、将来 chat 那条链、某个脚本)不经过那个 if ——
而写进去的 `7 分` 在列表上和 `4 分` 长得一模一样,平均分照样算得出来。

> **规矩写在代码的 if 里 ≠ 结构上拦住。**
> 而一条**从没被攻击过的「结构性保证」,实际上仍然只是约定。**

所以这一份绕开接口,**直接用 SQL 去写坏值**,看库拦不拦。

## ⚠️ 正向对照不是客套

四条「拦住了」后面必须跟一条「合法值写得进去」——
> 一次「CHECK 拦住了坏值」和一次「这张表根本写不进任何东西」,
> **在那四个 ✅ 上长得一模一样。**

## 清理

全程在一个事务里,**最后 rollback** —— 库里一个字不留
(这一份自己持连接,所以 rollback 做得到;`test_chunk_browse` 测的是接口函数,
它内部自己开连接看不到我的事务,那边只能 try/finally,差别写在那个文件头)。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

from sqlalchemy import create_engine, text   # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("=" * 92)
print("检索试跑记录 · 真的去攻击那几条 CHECK(真 PG,跑完 rollback)")
print("=" * 92)

with eng.connect() as c:
    t = c.begin()
    try:
        底 = c.execute(text("""
            select ib.organization_id, ib.project_id, ib.id ib_id,
                   ib.knowledge_base_id
              from index_builds ib
             where ib.status = '已就绪'
             order by ib.created_at desc limit 1""")).mappings().first()
        if not 底:
            # ⚠️ **不静默跳过。**「跳过了」和「通过了」在输出上长得一模一样。
            print("\n❌ 库里没有「已就绪」的索引构建 —— 这一份要一条真的外键目标。")
            print("   先跑一次索引构建(make test 里那条,或界面上建一次)。")
            sys.exit(1)
        基 = {"o": 底["organization_id"], "p": 底["project_id"],
             "ib": 底["ib_id"], "kb": 底["knowledge_base_id"]}
        print(f"  拿 {基['p']} / {基['ib']} 当外键目标")

        def 插(**改):
            """插一行试跑。`改` 覆盖默认值。返回 (成了吗, 错误类型名)。"""
            # ⚠️⚠️ **`**改` 必须排在最后。**
            # 第一版写的是 `{..., **改, **基}` —— 而 `基` 里有 `ib`,
            # 于是第 ⑥ 组「编一个不存在的索引 id」被 `基` **覆盖回了合法值**:
            # 判据报「外键没拦住」,而真相是**那个坏值根本没被插进去**。
            # > 一次「约束没拦住」和一次「注入根本没发生」,
            # > **在那个 ❌ 上长得一模一样** —— 而两边的下一步完全相反
            # > (前者去补外键,后者去修判据)。
            参 = {"i": f"rr_自测{os.getpid()}{len(过) + len(挂)}",
                 "src": "检索实验室", "q": "自测用的问题",
                 # ⚠️ 这里存的是**对象**,`json.dumps` 放到 execute 那一行 ——
                 # 不是风格:`tools/jsonb_cast_check.py` 用 ast 看
                 # **同一个 execute 调用里**那个值表达式是不是 dumps,
                 # 跨变量它追不动(追不动的时候判据会开始猜)。
                 # 写在变量里的话它报「说不清」,而那一档是钉死 0 段的。
                 "链对象": {"原问": "自测用的问题"},
                 "ast": "这次没要", "rating": None, **基, **改}
            sp = c.begin_nested()
            try:
                c.execute(text("""
                    insert into retrieval_runs (id, organization_id, project_id,
                        index_build_id, knowledge_base_id, source, user_query,
                        chain_snapshot, answer_status, rating,
                        created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:ib,:kb,:src,:q, cast(:chain as jsonb),
                            :ast,:rating, now(), 'u_自测', now(), 1)"""),
                          {**参,
                           # None 要留成 None(验 NOT NULL 那一条要它),
                           # 而 `json.dumps(None)` 是字符串 "null" —— 那是**合法的
                           # jsonb**,于是 NOT NULL 永远测不到。
                           "chain": (None if 参["链对象"] is None
                                     else json.dumps(参["链对象"], ensure_ascii=False))})
                sp.commit()
                return True, None
            except Exception as e:
                sp.rollback()
                return False, type(e).__name__

        print("\n▸ ① 对照先绿 —— 合法的一行必须插得进去")
        成, 错 = 插()
        ck("🔑 合法行写得进去(**不先验这条,下面四个 ✅ 可能只是「什么都写不进」**)",
           成, 错 or "")
        成, 错 = 插(rating=4)
        ck("带 4 分的也写得进去", 成, 错 or "")

        print("\n▸ ② 评分:5 档是**库层**的事,不是接口的 if")
        for 值, 说 in ((7, "7 分(越界)"), (0, "0 分(0 不是档位)"), (-1, "-1 分")):
            成, 错 = 插(rating=值)
            ck(f"{说} 被库拦住", not 成, 错 or "**写进去了**")
        成, 错 = 插(rating=None)
        ck("而 NULL **允许**(还没人评)—— "
           "「还没人评」和「评了最低档」在一个 0 上长得一模一样,所以不能拿 0 当没评",
           成, 错 or "")

        print("\n▸ ③ 来源:取值是枚举,而 chat 那一支**还没接上这条链**")
        成, 错 = 插(src="随便编的")
        ck("编一个来源被库拦住", not 成, 错 or "**写进去了**")
        成, 错 = 插(src="chat")
        ck("🔑 而 `chat` 现在就是合法值(接上那天不用改库,只要开始往里写)",
           成, 错 or "")

        print("\n▸ ④ 答案四档:后两档都让答案空着,**而一个是选择、一个是故障**")
        成, 错 = 插(ast="没有")
        ck("编一个档位被库拦住", not 成, 错 or "**写进去了**")
        for 档 in ("答了", "证据不够", "这次没要", "跑不成"):
            成, 错 = 插(ast=档)
            ck(f"「{档}」是合法档位", 成, 错 or "")

        print("\n▸ ⑤ 必填列:空着插进去的话,列表上就是一行什么都没有的记录")
        for 列, 说 in (("src", "来源"), ("q", "问题"), ("链对象", "链路快照")):
            成, 错 = 插(**{列: None})
            ck(f"{说} 为空被库拦住(NOT NULL)", not 成, 错 or "**写进去了**")

        print("\n▸ ⑥ 跨项目引用:拿别的项目的索引 id 来填")
        成, 错 = 插(ib="ib_根本不存在")
        ck("编一个索引构建 id 被外键拦住 —— "
           "**跨项目引用在数据库层就不成立**,不靠 handler 记得检查",
           not 成, 错 or "**写进去了**")

        print("\n▸ ⑦ 这一份自己留下的行:**一条都不许留**")
        剩 = c.execute(text("select count(*) from retrieval_runs "
                           "where created_by = 'u_自测'")).scalar()
        ck("rollback 之前先数一遍(事务里应当看得见刚插的那几条)", 剩 > 0, f"{剩} 条")
    finally:
        t.rollback()

with eng.connect() as c:
    留 = c.execute(text("select count(*) from retrieval_runs "
                       "where created_by = 'u_自测'")).scalar()
# ⚠️ 这一条量的是**这个文件有没有写脏库**,不是「全表必须是空的」——
# 后者在这个栏目真用起来之后永远红(10-07 在 test_vector_constraints 上栽过:
# 收尾断言写成「全库 embeddings 必须为 0」,建完索引它永远红)。
ck("跑完库里**一行自测数据都没留**(rollback 真的生效了)", 留 == 0, f"{留} 条")

print("\n" + "=" * 92)
if 挂:
    print(f"❌ 过 {len(过)} / 挂 {len(挂)}")
    for x in 挂:
        print(f"   · {x}")
    sys.exit(1)
print(f"✅ 过 {len(过)} 条全过")
