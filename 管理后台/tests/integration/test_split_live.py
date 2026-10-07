#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**真的拆一次** —— 在 PG 上执行「把几个切片拆成独立文档」。

判定那一层的自测在 `tests/orchestration/test_split_document.py`(54 条、零 IO)。
这一份验的是**执行**:写进去的东西对不对、原数据有没有被动过、清不清得干净。

## ⚠️ 这份测试真的写库,所以清理是它最要紧的一部分

接口内部用 `事务()` 自己 commit —— **拿不到我的事务**,所以不能像
`test_corpus_acl_live.py` 那样 rollback。清理放 `finally`,并在结尾
**把原文档的版次和切片数和开跑前对一遍**:
> 一次「清干净了」和一次「清了一半」,**在那句「跑完了」上长得一模一样** ——
> 而留下的半截会让索引构建取到错的 max(revision),
> 表现是「检索结果少了几段」,没人会归因到一次测试。

## 这一组每一条对着一种「写进去了但不对」

   ① 原切片被动过 → 已建的索引、已发生的问答,证据链一起指向了新内容
   ② 搬过去的片段读了当前 chunker 常量 → **整个知识库从此建不出索引**
   ③ 原文档没新建版本(或者新版还含着拆走的段)→ 权限根本没收紧
   ④ content_hash 照抄上一版 → 那一列从此骗人(原文件没变,内容变了)
   ⑤ 重复提交拆出第二篇 → 一次网络超时后的重试就多一篇文档
   ⑥ 返回里有个能当「做完了」用的键 → 调用方以为权限已经生效
"""
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app"))

from sqlalchemy import create_engine, text   # noqa: E402
import knowledge_api as KA                    # noqa: E402
from deps import 身份                          # noqa: E402

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


class 假请求:
    """只给 `await request.json()` 用 —— 不起服务(起服务的测试要外部状态)。"""
    def __init__(self, 体):
        self._体 = 体

    async def json(self):
        return self._体


def 跑(体, key, me):
    import asyncio
    return asyncio.run(KA.拆成独立文档(
        project_id=proj, doc_id=doc, request=假请求(体),
        idempotency_key=key, me=me))


print("=" * 92)
print("真的拆一次 · 执行层(真 PG,跑完清干净)")
print("=" * 92)

with eng.connect() as c:
    # 挑一篇片段最多的文档(拆走一部分还剩得下)
    r = c.execute(text("""
        select d.project_id, d.id, d.knowledge_base_id, dv.id, dv.revision,
               count(ch.id)
          from documents d
          join document_versions dv on dv.project_id=d.project_id
                                   and dv.document_id=d.id
          join chunks ch on ch.project_id=dv.project_id
                        and ch.document_version_id=dv.id
         where d.archived_at is null and d.disabled_at is null
           and dv.revision = (select max(x.revision) from document_versions x
                               where x.project_id=dv.project_id
                                 and x.document_id=dv.document_id)
         group by 1,2,3,4,5 having count(ch.id) >= 4
         order by count(ch.id) desc limit 1""")).first()
if not r:
    print("\n❌ 找不到片段数 >= 4 的文档 —— **不在样本量不够时出结论**")
    sys.exit(1)
proj, doc, kb, 版id, 原版次, 片数 = r[0], r[1], r[2], r[3], r[4], r[5]
ck("找到一篇够拆的文档", 片数 >= 4, f"{doc} v{原版次} · {片数} 段")

with eng.connect() as c:
    原片段 = [dict(x) for x in c.execute(text("""
        select id, ordinal, text_hash, chunker_version, parser_version, text
          from chunks where project_id=:p and document_version_id=:v
         order by ordinal"""), {"p": proj, "v": 版id}).mappings()]
    原哈希 = c.execute(text("""select content_hash from document_versions
                             where project_id=:p and id=:v"""),
                     {"p": proj, "v": 版id}).scalar()
    原文档数 = c.execute(text("select count(*) from documents where project_id=:p"),
                     {"p": proj}).scalar()
原快照 = {x["id"]: (x["ordinal"], x["text_hash"], x["chunker_version"]) for x in 原片段}
拆谁 = [x["id"] for x in 原片段[:2]]
me = 身份(user_id="u_test", org_id=None, project_id=proj, role="admin", grants=[])
key = "split-test-" + uuid.uuid4().hex[:10]
建了 = {"doc": None, "dv": [], }

try:
    print("\n▸ ① 拆一次")
    out = 跑({"要拆走的切片ids": 拆谁, "新文档acl": ["admin"]}, key, me)
    建了["doc"] = out["新文档id"]
    建了["dv"] = [out["新文档版本id"], out["原文档新版本id"]]
    ck("拆成功,返回新文档和两个新版本", bool(out["新文档id"]),
       f"搬走 {out['搬过去几段']} 段 · 原文档还剩 {out['原文档还剩几段']} 段")
    ck("搬走 + 留下 == 原来的总数",
       out["搬过去几段"] + out["原文档还剩几段"] == 片数,
       f"{out['搬过去几段']}+{out['原文档还剩几段']} vs {片数}")
    ck("🔑 返回里**没有任何能当「做完了」用的键**,而 `欠账` 非空 —— "
       "在役索引是快照,拆完那个人照旧检索得到",
       not ({"成功", "ok", "done", "已生效"} & set(out)) and bool(out["欠账"]),
       f"{len(out['欠账'])} 条欠账 · 键 {sorted(out)[:4]}")
    ck("「下一步」明说了在那之前权限没有生效",
       "没有生效" in out["下一步"], out["下一步"][:60])

    print("\n▸ ② 原切片一条都没动")
    with eng.connect() as c:
        现 = {x[0]: (x[1], x[2], x[3]) for x in c.execute(text("""
            select id, ordinal, text_hash, chunker_version from chunks
             where project_id=:p and document_version_id=:v"""),
            {"p": proj, "v": 版id})}
    ck("🔑 原版本的片段 **id / ordinal / 哈希 / 切片器版本全都没变** —— "
       "chunks 不可变,改它就把已建索引和已发生问答的证据链指向了新内容",
       现 == 原快照, f"原 {len(原快照)} 条 / 现 {len(现)} 条")
    with eng.connect() as c:
        旧哈希2 = c.execute(text("""select content_hash from document_versions
                                 where project_id=:p and id=:v"""),
                         {"p": proj, "v": 版id}).scalar()
    ck("原版本的 content_hash 也没动", 旧哈希2 == 原哈希)

    print("\n▸ ③ 新文档:沿用版本号 · 序号重排 · 权限写死")
    with eng.connect() as c:
        新片 = [dict(x) for x in c.execute(text("""
            select ordinal, text_hash, chunker_version, parser_version
              from chunks where project_id=:p and document_version_id=:v
             order by ordinal"""),
            {"p": proj, "v": out["新文档版本id"]}).mappings()]
        新文 = c.execute(text("""select acl_override, source_info,
                                      knowledge_base_id from documents
                               where project_id=:p and id=:i"""),
                       {"p": proj, "i": out["新文档id"]}).mappings().first()
        新版 = c.execute(text("""select revision, object_key, content_hash,
                                      source_info from document_versions
                               where project_id=:p and id=:v"""),
                       {"p": proj, "v": out["新文档版本id"]}).mappings().first()
    搬的原片 = [x for x in 原片段 if x["id"] in set(拆谁)]
    ck("🔑 搬过去的片段**沿用源片段记的切片器/解析器版本**(不是当前常量)—— "
       "重切一遍的话 MIXED_CHUNKER_VERSION 会让这个库从此建不出索引,"
       "而那要到下一次重建才炸",
       [x["chunker_version"] for x in 新片] == [x["chunker_version"] for x in 搬的原片]
       and [x["parser_version"] for x in 新片] == [x["parser_version"] for x in 搬的原片],
       f"新 {[x['chunker_version'] for x in 新片]} / 源 {[x['chunker_version'] for x in 搬的原片]}")
    ck("正文哈希一字不差(是复制,不是重切)",
       [x["text_hash"] for x in 新片] == [x["text_hash"] for x in 搬的原片])
    ck("序号重排成 0..n-1 连续", [x["ordinal"] for x in 新片] == list(range(len(新片))))
    ck("新文档的 acl_override 是**写死的字面量**(不是 null 继承)",
       (新文["acl_override"] or {}).get("roles") == ["admin"], 新文["acl_override"])
    ck("新版本 revision=1、没有 object_key(它解析不出来)、source_info 标派生",
       新版["revision"] == 1 and 新版["object_key"] is None
       and (新版["source_info"] or {}).get("存储") == "拆分派生",
       f"rev={新版['revision']} ok={新版['object_key']}")
    ck("新文档记下了拆自哪篇、哪一版、幂等键",
       (新文["source_info"] or {}).get("拆自文档") == doc
       and (新文["source_info"] or {}).get("幂等键") == key)

    print("\n▸ ④ 原文档:新建一版,只含剩下的;哈希不照抄")
    with eng.connect() as c:
        原新版 = c.execute(text("""select revision, object_key, content_hash,
                                        source_info from document_versions
                                 where project_id=:p and id=:v"""),
                        {"p": proj, "v": out["原文档新版本id"]}).mappings().first()
        剩片 = [dict(x) for x in c.execute(text("""
            select ordinal, text_hash from chunks
             where project_id=:p and document_version_id=:v order by ordinal"""),
            {"p": proj, "v": out["原文档新版本id"]}).mappings()]
    ck("原文档新版次 = 上一版 + 1", 原新版["revision"] == 原版次 + 1,
       f"{原版次} → {原新版['revision']}")
    ck("新版里**不含被拆走的那几段**",
       not (set(x["text_hash"] for x in 剩片)
            & set(x["text_hash"] for x in 搬的原片)),
       f"剩 {len(剩片)} 段")
    ck("🔑 content_hash **不照抄上一版** —— `object_key` 指的原文件没变"
       "(还含着拆走的几段),而「这份资料变没变」全靠那一列",
       原新版["content_hash"] != 原哈希,
       f"旧 {(原哈希 or '')[:18]} / 新 {(原新版['content_hash'] or '')[:18]}")
    ck("而 object_key **照抄**上一版(原文件确实没变)",
       原新版["object_key"] is not None)
    ck("新版的 source_info 标成派生 —— 否则「查看原文」会从原文件"
       "拿到完整内容,**含着他已经没权限的那几段**",
       (原新版["source_info"] or {}).get("存储") == "拆分派生")

    print("\n▸ ⑤ 幂等 + 拒绝的那几种")
    再 = 跑({"要拆走的切片ids": 拆谁, "新文档acl": ["admin"]}, key, me)
    ck("🔑 同一个 Idempotency-Key 重复提交:**回上次的结果,不拆第二篇**",
       再.get("已经拆过了") is True and 再["新文档id"] == out["新文档id"])
    with eng.connect() as c:
        现文档数 = c.execute(text("select count(*) from documents where project_id=:p"),
                        {"p": proj}).scalar()
    ck("文档总数只 +1(重复那次没建)", 现文档数 == 原文档数 + 1,
       f"{原文档数} → {现文档数}")
    for 说, 体, 期 in (
            ("不带 acl → 拒(不许留空继承)",
             {"要拆走的切片ids": 拆谁}, "SPLIT_REFUSED"),
            ("一个都没选 → 拒", {"要拆走的切片ids": [], "新文档acl": ["admin"]},
             "VALIDATION"),
            ("拿已经拆走的 id 再拆 → 拒(它不在最新版里了)",
             {"要拆走的切片ids": 拆谁, "新文档acl": ["admin"]}, "SPLIT_REFUSED")):
        try:
            跑(体, "k-" + uuid.uuid4().hex[:8], me)
            ck(说, False, "**没拒**")
        except Exception as e:
            码 = (getattr(e, "detail", None) or {}).get("code") if hasattr(e, "detail") else None
            ck(说, getattr(e, "status_code", None) in (409, 422),
               f"status={getattr(e, 'status_code', None)} code={码}")
    try:
        跑({"要拆走的切片ids": 拆谁, "新文档acl": ["admin"]}, None, me)
        ck("不带 Idempotency-Key → 拒", False, "**没拒**")
    except Exception as e:
        ck("不带 Idempotency-Key → 409(重试必须能被认出来)",
           getattr(e, "status_code", None) == 409)
finally:
    # ⚠️ **清理按外键倒序**,而且**不管上面成功到哪一步都要跑**。
    with eng.begin() as c:
        for v in [x for x in 建了["dv"] if x]:
            c.execute(text("delete from chunks where project_id=:p "
                           "and document_version_id=:v"), {"p": proj, "v": v})
            c.execute(text("delete from document_versions where project_id=:p "
                           "and id=:v"), {"p": proj, "v": v})
        if 建了["doc"]:
            c.execute(text("delete from documents where project_id=:p and id=:i"),
                      {"p": proj, "i": 建了["doc"]})

print("\n▸ ⑥ 清干净了吗 —— **和开跑前逐项对一遍**")
with eng.connect() as c:
    后版次 = c.execute(text("""select max(revision) from document_versions
                             where project_id=:p and document_id=:i
                               and archived_at is null"""),
                    {"p": proj, "i": doc}).scalar()
    后片段 = {x[0]: (x[1], x[2], x[3]) for x in c.execute(text("""
        select id, ordinal, text_hash, chunker_version from chunks
         where project_id=:p and document_version_id=:v"""),
        {"p": proj, "v": 版id})}
    后文档数 = c.execute(text("select count(*) from documents where project_id=:p"),
                    {"p": proj}).scalar()
ck("原文档的 max(revision) 回到开跑前", 后版次 == 原版次, f"{原版次} → {后版次}")
ck("原版本的片段一条没少、一个字段没变", 后片段 == 原快照,
   f"{len(原快照)} → {len(后片段)}")
ck("文档总数回到开跑前", 后文档数 == 原文档数, f"{原文档数} → {后文档数}")

print("\n" + "=" * 92)
print(f"{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
