#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把澜绣的业务拍板记录导入成知识库。**用 parser + chunker,不自己写解析。**

## 为什么第一批语料是业务拍板记录

`~/Desktop/澜绣云裳agent/业务决策/业务拍板-*.md`。挑它们的理由:

  · 它们是**口径的原文**,而 `knowledge/*.py` 是口径的**实现** —— RAG 要引的是原文
  · 有小节结构,所以「片段能指回第几节第几段」天然可满足,不用靠行号
  · 里面有「我摆过的代价,业务知情后仍然这么选」这种段落 ——
    那正是顾问最需要查到、而问模型最容易被编出来的东西

## 幂等:靠内容哈希,不靠文件名也不靠时间

再跑一次同一份文件:`content_hash` 一样 → **不新建版本,不重新切片**。
文件改了 → `content_hash` 变 → **新建一个版本,并给新版本重新切片**。

⚠️ **片段绑的是文档版本,不是文档**(契约里 `chunks.document_version_id`)。
所以旧版本的片段**留着** —— 否则一条引用了旧版本的证据链会突然指向新内容,
而那比「查不到」糟得多:它看起来查到了。

## 首版没有对象存储

契约里 `document_versions.object_key` 是对象存储的键(§18:「原文放对象存储,
库里只存键和哈希」)。首版没有对象存储,这里放的是**仓库内的相对路径**。
写清是因为:以后接了对象存储,这一列的含义会变,
而**一列含义变了而没人知道**,比多一列糟。
"""
import hashlib
import os
import sys
import uuid

这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(这)
澜绣 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "knowledge"))

from sqlalchemy import create_engine, text   # noqa: E402
import parser as P                            # noqa: E402
import chunker as C                           # noqa: E402

语料目录 = os.path.join(澜绣, "业务决策")
知识库名 = "澜绣业务拍板"
URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"


def 新(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:12]}"


def 内容哈希(s):
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:40]


def 要哪个项目(c):
    """导到哪个项目。**不猜** —— 库里没有项目就报出来让人先建。

    ⚠️ 不自动建项目:一个自动出现的项目会让「这些数据属于谁」变得说不清,
    而项目是权限和隔离的单位(§18)。
    """
    r = c.execute(text("select organization_id, id, name from projects"
                       " where archived_at is null order by created_at limit 2")
                  ).mappings().all()
    if not r:
        raise SystemExit(
            "库里没有项目 —— **先 `make seed-demo` 建一个**。\n"
            "这里不自动建:项目是权限和隔离的单位,一个自动出现的项目\n"
            "会让「这些数据属于谁」变得说不清。")
    if len(r) > 1:
        print(f"⚠️ 库里有多个项目,导进第一个:{r[0]['name']}({r[0]['id']})")
    return r[0]["organization_id"], r[0]["id"]


def 拿或建知识库(c, org, proj):
    r = c.execute(text("select id from knowledge_bases where project_id=:p"
                       " and name=:n and archived_at is null"),
                  {"p": proj, "n": 知识库名}).scalar()
    if r:
        return r, False
    kb = 新("kb")
    c.execute(text("""insert into knowledge_bases
        (id, organization_id, project_id, name, status, created_at, created_by, revision)
        values (:i,:o,:p,:n,'active', now(), 'ingest', 1)"""),
              {"i": kb, "o": org, "p": proj, "n": 知识库名})
    return kb, True


def 导一份(c, org, proj, kb, 文件名):
    """导入一份文件。返回一句人话。"""
    路 = os.path.join(语料目录, 文件名)
    原文 = open(路, encoding="utf-8").read()
    h = 内容哈希(原文)
    相对路径 = os.path.relpath(路, 澜绣)

    doc = c.execute(text("select id from documents where project_id=:p"
                         " and knowledge_base_id=:k"
                         " and source_info->>'path' = :sp"),
                    {"p": proj, "k": kb, "sp": 相对路径}).scalar()
    if not doc:
        doc = 新("doc")
        # ⚠️ 下面那个 `cast(... as text)` 不能省:`jsonb_build_object` 收 `any`,
        # 给不出类型约束,PostgreSQL 会报 could not determine data type of parameter。
        # 这是第二次踩这一族(上一次是列表接口那个 500,要 cast 才能和 null 比)——
        # 共同点:**参数落在类型上下文不明确的位置**。
        #
        # ⚠️⚠️ 而这段说明写在**Python 注释里**,不写进 SQL 字符串:
        # SQLAlchemy 的 `text()` 对 `--` 注释**不透明**,它只做 `:name` 词法扫描。
        # 我刚试过把这段写进 SQL,里面一个 `:w` 当场变成缺失的绑定参数。
        # **SQL 字符串里不许出现 `:` 开头的自然语言。**
        c.execute(text("""insert into documents
            (id, organization_id, project_id, knowledge_base_id, source_info,
             created_at, created_by, revision)
            values (:i,:o,:p,:k,
                    jsonb_build_object('path', cast(:sp as text),
                                       '来源','仓库内的业务拍板记录'),
                    now(), 'ingest', 1)"""),
                  {"i": doc, "o": org, "p": proj, "k": kb, "sp": 相对路径})

    # **幂等靠内容哈希** —— 同一份内容不新建版本
    已有 = c.execute(text("select id from document_versions where project_id=:p"
                          " and document_id=:d and content_hash=:h"),
                     {"p": proj, "d": doc, "h": h}).scalar()
    if 已有:
        n = c.execute(text("select count(*) from chunks where project_id=:p"
                           " and document_version_id=:v"),
                      {"p": proj, "v": 已有}).scalar()
        return f"{文件名}:内容没变,跳过(版本 {已有[-8:]},{n} 个片段)"

    # 版本号:同一个文档往后加一个
    最大 = c.execute(text("select coalesce(max(revision),0) from document_versions"
                         " where project_id=:p and document_id=:d"),
                    {"p": proj, "d": doc}).scalar()
    dv = 新("dv")
    c.execute(text("""insert into document_versions
        (id, organization_id, project_id, document_id, object_key, content_hash,
         effective_at, revision, created_at, created_by)
        values (:i,:o,:p,:d,:ok,:h, now(), :rev, now(), 'ingest')"""),
              {"i": dv, "o": org, "p": proj, "d": doc,
               # ⚠️ 首版没有对象存储:这里是**仓库内相对路径**,不是对象键。
               "ok": 相对路径, "h": h, "rev": 最大 + 1})

    解析 = P.解析(原文, 文件名=文件名)
    切 = C.切(解析, 文档版本id=dv)
    for p in 切["片段们"]:
        c.execute(text("""insert into chunks
            (id, organization_id, project_id, document_version_id, section_path,
             ordinal, text, text_hash, token_count, created_at, created_by)
            values (:i,:o,:pj,:v,:sp,:ord,:t,:th,:tc, now(), 'ingest')"""),
                  {"i": 新("ch"), "o": org, "pj": proj, "v": dv,
                   "sp": p["section_path"], "ord": p["ordinal"], "t": p["text"],
                   "th": p["text_hash"], "tc": p["token_count"]})
    警 = ("  ⚠️ " + " / ".join(解析["警告"])) if 解析["警告"] else ""
    return (f"{文件名}:新版本 v{最大 + 1}({解析['块们'] and len(解析['块们'])} 块 → "
            f"{len(切['片段们'])} 片段,丢掉 {解析['丢掉的块数']} 块){警}")


def main():
    if not os.path.isdir(语料目录):
        raise SystemExit(f"找不到语料目录 {语料目录}")
    文件们 = sorted(f for f in os.listdir(语料目录) if f.endswith(".md"))
    if not 文件们:
        raise SystemExit(f"{语料目录} 里没有 .md —— **不静默导入 0 份**:"
                         f"「导完了」和「什么都没导」在输出上必须分得开")
    eng = create_engine(URL)
    with eng.begin() as c:
        org, proj = 要哪个项目(c)
        kb, 新建 = 拿或建知识库(c, org, proj)
        print(f"项目 {proj} · 知识库 {知识库名}({kb}{',新建' if 新建 else ''})")
        print(f"语料 {len(文件们)} 份:")
        for f in 文件们:
            print("  ·", 导一份(c, org, proj, kb, f))
        # 汇总。**从库里查,不累加内存里的计数** —— 累加的数字和库里的会漂。
        s = c.execute(text("""select
            (select count(*) from documents where project_id=:p and knowledge_base_id=:k),
            (select count(*) from document_versions dv join documents d
               on d.project_id=dv.project_id and d.id=dv.document_id
              where dv.project_id=:p and d.knowledge_base_id=:k),
            (select count(*) from chunks ch join document_versions dv
               on dv.project_id=ch.project_id and dv.id=ch.document_version_id
              join documents d on d.project_id=dv.project_id and d.id=dv.document_id
              where ch.project_id=:p and d.knowledge_base_id=:k)"""),
                     {"p": proj, "k": kb}).first()
    print(f"\n库里现在:{s[0]} 篇文档 · {s[1]} 个版本 · {s[2]} 个片段")
    print("⚠️ **旧版本的片段留着** —— 片段绑的是文档版本,不是文档。")
    print("   删掉旧片段会让一条引用旧版本的证据链突然指向新内容,")
    print("   而那比「查不到」糟:它看起来查到了。")


if __name__ == "__main__":
    main()
