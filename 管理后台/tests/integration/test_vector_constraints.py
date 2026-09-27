#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""向量表的约束:**真的去插坏数据**,不是读一遍迁移说「看起来拦住了」。

## 为什么这个文件必须存在

`knowledge/index_plan.py` 里有一条判据 `已经做完的()`:
`embedding_id` 空的算没做完。写它的时候我发现了一件更糟的事 ——
**`embedding_id` 指向的表根本不存在**,它不是外键,那一列可以填任何字符串。

于是我把修法从「把判据写得更复杂」换成「加一个真外键」,理由是:

> **能用约束表达的不要用判据表达。**
> 判据只在有人调用它时生效;约束在每一次 INSERT 上生效,
> 包括我没想到的那些写入路径。

但这句话本身是个**声称**。而(这个仓库反复学到的):

> 一条从没被攻击过的「结构性保证」,实际上仍然只是约定。

所以这里对着真库插四种坏数据,每一种都必须被 PostgreSQL 拒绝。
用完还原 —— 写脏了库不还原,下一轮的结论就不可信。

## 四种坏数据,各自对应一种「不报错的坏」

① **维度不对的向量** → 混维度的索引,检索时算出没有意义的距离
② **指向不存在向量的成员** → 「登记了向量」是谎话,那段内容永不命中
③ **同一段文本同一模型两份向量** → 检索时同一段话占掉两个名额
④ **跨项目引用向量** → A 项目的索引指着 B 项目的向量(§18)

④ 是顺手测的,但它其实是最容易漏的那个:
`(project_id, embedding_id)` 这个复合外键是**唯一**能挡住它的东西 ——
单列外键 `embedding_id → embeddings.id` 在这里挡不住,
因为 `embeddings` 的主键是 `(project_id, id)`,单列引用根本建不起来。
换句话说:这条保证是主键形状**顺带**给的,而不是有人专门想到的。
那更该测:没人专门想到的保证,也没人会专门维护。
"""
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

from sqlalchemy import create_engine, text          # noqa: E402
from sqlalchemy.exc import IntegrityError, DataError, DBAPIError  # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:130]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 新(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:8]}"


def 拒绝吗(连, sql, **值):
    """跑一条该被拒的写入。返回 (被拒了吗, 数据库说了什么)。

    ⚠️ 收 `DBAPIError` 而不只是 `IntegrityError`:
    维度不符是 pgvector 抛的**数据错误**,不是完整性约束错误 ——
    只收 IntegrityError 的话,①那条会以「抛了别的异常」的形式**崩掉**,
    而崩掉和「没拦住」在结果表上长得不一样,容易被当成环境问题放过去。
    """
    # ⚠️ 第一个参数叫 `连` 而不是 `c` —— 撞过:调用处要传 `c=片段id`,
    # 而 `c` 正是连接那个位置参数的名字,于是 `TypeError: got multiple values`。
    # 第一条测试没暴露它(那条没传 `c=`)。**第一条绿不代表形状对。**
    sp = 连.begin_nested()
    try:
        连.execute(text(sql), 值)
        sp.rollback()
        return False, "**写进去了** —— 这条边界没有成立"
    except (IntegrityError, DataError, DBAPIError) as e:
        sp.rollback()
        return True, str(getattr(e, "orig", e)).split("\n")[0][:110]


# ⚠️ **512,跟着 `embeddings.embedding` 的列类型走**(2026-09-27 从 1536 改过来,
# 因为用户拍了本地模型 BGE-small-zh-v1.5)。
# 下面「插 3 维 / 插 768 维被拒」那两条仍然有效 —— 它们要的是「≠ 列维度」。
维度 = 512
真向量 = "[" + ",".join(["0.1"] * 维度) + "]"

# ⚠️ **不用 `eng.begin()`。** 它在正常退出时 **commit** ——
# 而这个文件插的全是测试数据,提交上去就把库写脏了,
# 下一轮跑出来的结论从此不可信(而且脏数据本身不报错)。
# 显式开事务 + `finally` 里 rollback:还原这件事要在代码里**看得见**。
c = eng.connect()
tx = c.begin()
try:
    org, pa, pb = 新("org"), 新("projA"), 新("projB")
    c.execute(text("insert into organizations (id, name, status, created_at)"
                   " values (:i,'测试组织','active', now())"), {"i": org})
    for p, n in ((pa, "A 项目"), (pb, "B 项目")):
        c.execute(text("insert into projects (id, organization_id, name, status, created_at)"
                       " values (:i,:o,:n,'active', now())"), {"i": p, "o": org, "n": n})

    def 摆一套(proj, 后缀):
        """在某个项目里摆出 知识库→文档→版本→片段→构建 一条链。"""
        kb, doc, dv, ch, ib = (新("kb"), 新("doc"), 新("dv"), 新("ch"), 新("ib"))
        c.execute(text("insert into knowledge_bases (id, organization_id, project_id, name,"
                       " created_at) values (:i,:o,:p,'澜绣业务拍板', now())"),
                  {"i": kb, "o": org, "p": proj})
        c.execute(text("insert into documents (id, organization_id, project_id,"
                       " knowledge_base_id, created_at) values (:i,:o,:p,:k, now())"),
                  {"i": doc, "o": org, "p": proj, "k": kb})
        c.execute(text("insert into document_versions (id, organization_id, project_id,"
                       " document_id, content_hash, created_at) values (:i,:o,:p,:d,:h, now())"),
                  {"i": dv, "o": org, "p": proj, "d": doc, "h": "ch" + 后缀})
        c.execute(text("insert into chunks (id, organization_id, project_id,"
                       " document_version_id, text, text_hash, ordinal, created_at)"
                       " values (:i,:o,:p,:v,:t,:h,1, now())"),
                  {"i": ch, "o": org, "p": proj, "v": dv,
                   "t": "签收当场就请评价", "h": "文本哈希" + 后缀})
        c.execute(text("insert into index_builds (id, organization_id, project_id,"
                       " knowledge_base_id, embedding_dim, status, created_at)"
                       " values (:i,:o,:p,:k,:d,'running', now())"),
                  {"i": ib, "o": org, "p": proj, "k": kb, "d": 维度})
        return kb, ch, ib

    kbA, chA, ibA = 摆一套(pa, "A")
    kbB, chB, ibB = 摆一套(pb, "B")

    # 一个合法向量,给后面几条当参照
    embA = 新("emb")
    c.execute(text("insert into embeddings (id, organization_id, project_id, text_hash,"
                   " model_id, dim, embedding, created_at)"
                   " values (:i,:o,:p,:h,'emb-mock',:d, :v, now())"),
              {"i": embA, "o": org, "p": pa, "h": "文本哈希A", "d": 维度, "v": 真向量})
    embB = 新("emb")
    c.execute(text("insert into embeddings (id, organization_id, project_id, text_hash,"
                   " model_id, dim, embedding, created_at)"
                   " values (:i,:o,:p,:h,'emb-mock',:d, :v, now())"),
              {"i": embB, "o": org, "p": pb, "h": "文本哈希B", "d": 维度, "v": 真向量})

    print("▸ ① 维度不对的向量(混维度的索引 → 距离算出来没有意义)")
    for 坏维度, 描述 in ((3, "3 维"), (1536, "1536 维,换模型前那种")):
        坏 = "[" + ",".join(["0.1"] * 坏维度) + "]"
        行, 说 = 拒绝吗(c, "insert into embeddings (id, organization_id, project_id,"
                          " text_hash, model_id, dim, embedding, created_at)"
                          " values (:i,:o,:p,:h,'emb-other',:d,:v, now())",
                       i=新("emb"), o=org, p=pa, h=新("h"), d=坏维度, v=坏)
        ck(f"往 vector({维度}) 列里插 {描述} → 被拒", 行, 说)

    print("\n▸ ② 指向不存在向量的成员(「登记了向量」是谎话)")
    行, 说 = 拒绝吗(c, "insert into index_members (id, organization_id, project_id,"
                      " index_build_id, chunk_id, embedding_id, created_at)"
                      " values (:i,:o,:p,:b,:c,'根本不存在的向量id', now())",
                   i=新("im"), o=org, p=pa, b=ibA, c=chA)
    ck("`embedding_id` 填一个不存在的 id → 被拒"
       "(在加这个外键之前,这一列可以填任何字符串,没有任何一层会发现)", 行, 说)

    print("\n▸ ③ 同一段文本 + 同一个模型两份向量(检索时同一段话占两个名额)")
    行, 说 = 拒绝吗(c, "insert into embeddings (id, organization_id, project_id, text_hash,"
                      " model_id, dim, embedding, created_at)"
                      " values (:i,:o,:p,'文本哈希A','emb-mock',:d,:v, now())",
                   i=新("emb"), o=org, p=pa, d=维度, v=真向量)
    ck("同项目里 (text_hash, model_id) 重复 → 被拒"
       "(这条唯一约束就是「换检索配置不用重算向量」的地基)", 行, 说)

    print("\n▸ ④ 跨项目引用向量(A 项目的索引指着 B 项目的向量)")
    行, 说 = 拒绝吗(c, "insert into index_members (id, organization_id, project_id,"
                      " index_build_id, chunk_id, embedding_id, created_at)"
                      " values (:i,:o,:p,:b,:c,:e, now())",
                   i=新("im"), o=org, p=pa, b=ibA, c=chA, e=embB)
    ck("A 项目的成员引用 B 项目的向量 → 被拒"
       "(挡住它的是复合外键 `(project_id, embedding_id)`;"
       "单列外键在这儿根本建不起来,所以这条保证是主键形状顺带给的)", 行, 说)

    print("\n▸ ⑤ 正向对照:**合法的那条必须写得进去**")
    # ⚠️ 没有这一条,上面四个「被拒」可能只是因为**整条链根本插不进去** ——
    # 那样这个文件会在什么都没验到的情况下全绿。
    imA = 新("im")
    c.execute(text("insert into index_members (id, organization_id, project_id,"
                   " index_build_id, chunk_id, embedding_id, created_at)"
                   " values (:i,:o,:p,:b,:c,:e, now())"),
              {"i": imA, "o": org, "p": pa, "b": ibA, "c": chA, "e": embA})
    有 = c.execute(text("select embedding_id from index_members where project_id=:p and id=:i"),
                  {"p": pa, "i": imA}).scalar()
    ck("同项目、维度正确、向量存在 → 写得进去(**否则上面四条可能什么都没验到**)",
       有 == embA, 有)

    # 不同项目可以有相同的 (text_hash, model_id) —— 唯一键带 project_id 就是为这个
    ok = c.execute(text("select count(*) from embeddings where text_hash in"
                        " ('文本哈希A','文本哈希B')")).scalar()
    ck("两个项目各自存同名文本的向量互不干扰(唯一键带 project_id)", ok == 2, ok)

finally:
    # ── 还原:**插进去的一条都不留** ────────────────────────────
    tx.rollback()
    c.close()

剩 = eng.connect()
try:
    脏 = 剩.execute(text("select count(*) from embeddings")).scalar()
finally:
    剩.close()
# ⚠️ 这一条不是仪式。回滚写错(比如用了 `eng.begin()`)时,上面每条判据**照样全绿** ——
# 唯一能看出来的地方就是库里多了几行,而那要有人去数。这里替人数一次。
ck("跑完之后 embeddings 表是空的(**测试数据一条都没留**)", 脏 == 0,
   f"还剩 {脏} 行 —— 回滚没生效,库被这个文件写脏了" if 脏 else "0 行")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}"
      f" —— 四种坏数据都被 PostgreSQL 拒了,合法那条写得进去")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
