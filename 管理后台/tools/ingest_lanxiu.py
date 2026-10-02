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

# ── 能导哪几批语料:**点名,不扫整个仓库** ─────────────────────────────
#
# ⚠️ 2026-10-02 之前这两个是**硬编**的(只能导 `业务决策/`)。
# 而搬家说明(`已搬走.md`)留的第三条待办是「知识管理 → `knowledge/`」——
# 硬编的话那一条根本做不了。
#
# **为什么点名而不是扫整个仓库**:仓库里的 md 不都该进 RAG
# (交接、日志、README 是给人读的流程文档,进了检索只会稀释真正的知识)。
# > 一个「把所有 md 都导进去」的脚本,它导进去的东西会随仓库长大而变脏,
# > **而检索质量下降是没有告警的**。
#
# 每一批为什么选它,见各自的 `为什么` —— 那是下一个人判断
# 「这一批还该不该在里面」的唯一线索。
语料批次 = {
    "业务拍板": dict(
        目录=os.path.join(澜绣, "业务决策"), 知识库名="澜绣业务拍板",
        为什么="它们是**口径的原文**,而 `knowledge/*.py` 是口径的实现 —— "
               "RAG 要引的是原文。有小节结构,所以「片段能指回第几节第几段」"
               "天然可满足。而且里面有「我摆过的代价,业务知情后仍然这么选」"
               "这种段落 —— 那正是顾问最需要查到、而问模型最容易被编出来的。"
               "⚠️ **演示项目下那一份别删**:`test_retrieval` / "
               "`test_index_build` / `test_vector_constraints` 三份集成测试"
               "按名字找它。澜绣项目下另建一份 —— 同名但不同项目,"
               "而项目隔离是这个后台最硬的约束,所以那不是两份会漂的副本,"
               "是**两个项目各有自己的数据**"),
    "领域知识": dict(
        目录=os.path.join(澜绣, "knowledge"), 知识库名="澜绣领域知识",
        # ⚠️ **排除清单:点名,而且要写为什么。** 现在是空的 ——
        # 而它存在的理由见上面那段:仓库里的 md 不都该进 RAG。
        # 空清单不是「没想过」,是**这一批里确实每一份都该进**:
        #
        # `knowledge/README.md` **有意保留**(第一眼我以为它该排掉 ——
        # 我自己在上面写了「README 是给人读的流程文档」)。读了之后改主意:
        # 它定义了「三级来源标注」的规矩,原话是
        # 「**这是这个库最重要的规矩** —— 知识库最怕的不是内容少,
        # 是**真假混在一起而读的人分不出来**」,还带一张
        # 「哪一级能不能对客户说」的表。
        # 顾问问「这条知识靠不靠谱、能不能跟客户讲」时,**它就是答案** ——
        # 排掉它才是丢了一份真知识。
        排除=(),
        为什么="形制/面料/工艺/配饰/颜色/相容矩阵/工期/量体/养护/版型/BOM/"
               "成长/纹样/话术/SOP/电商 —— **手写的真相源**。"
               "⚠️ 它们**同时**是 `derive_*.py` 的输入:那几个脚本读 md、"
               "跑规则、生成 2000+ 条派生数据落库,`check.sh` 会对账。"
               "所以这里导进来的是**可检索的索引,不是真相源的搬家** —— "
               "文件仍然是源,改了文件要重导(`lanxiu_kb_sync_check.py` 盯着)"),
}
语料目录 = 语料批次["业务拍板"]["目录"]      # 默认那一批(向后兼容)
知识库名 = 语料批次["业务拍板"]["知识库名"]
URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"


def 新(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:12]}"


def 内容哈希(s):
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:40]


def 要哪个项目(c, 指定=None):
    """导到哪个项目。**不猜** —— 库里没有项目就报出来让人先建。

    ⚠️ 不自动建项目:一个自动出现的项目会让「这些数据属于谁」变得说不清,
    而项目是权限和隔离的单位(§18)。

    ## ⚠️ 2026-10-02 改掉了「导进第一个」

    原来多个项目时打一句警告然后**导进第一个**。那在 09-27 没问题
    (库里只有两个演示项目),而 10-02 建了 `project_lanxiu` 之后
    **「第一个」取决于 `order by created_at`** —— 也就是靠运气。

    实际后果已经发生过:09-27 那 5 篇业务拍板导进了 `project_demo_a`,
    而它们本该在澜绣项目里。
    > **一个靠「第一个」决定数据归属的脚本,它的结果取决于建项目的顺序** ——
    > 而那个顺序没有任何地方写着。

    现在:多个项目时**必须用 `--项目` 点名**,不点就报出来让人选。
    """
    if 指定:
        r = c.execute(text("""select organization_id, id, name from projects
                             where id=:i and archived_at is null"""),
                      {"i": 指定}).mappings().first()
        if not r:
            有 = [x["id"] for x in c.execute(text(
                "select id from projects where archived_at is null")).mappings()]
            raise SystemExit(f"没有项目 {指定} —— 库里有:{有}")
        return r["organization_id"], r["id"]
    r = c.execute(text("select organization_id, id, name from projects"
                       " where archived_at is null order by created_at")
                  ).mappings().all()
    if not r:
        raise SystemExit(
            "库里没有项目 —— **先 `make seed-demo` 建一个**。\n"
            "这里不自动建:项目是权限和隔离的单位,一个自动出现的项目\n"
            "会让「这些数据属于谁」变得说不清。")
    if len(r) > 1:
        raise SystemExit(
            f"库里有 {len(r)} 个项目,**不猜导哪个** —— 用 `--项目` 点名:\n"
            + "\n".join(f"    --项目 {x['id']}    # {x['name']}" for x in r)
            + "\n⚠️ 原来这里是「导进第一个」,而那取决于建项目的顺序 ——\n"
              "  09-27 那 5 篇业务拍板就是这么落进演示项目的。")
    return r[0]["organization_id"], r[0]["id"]


def 拿或建知识库(c, org, proj, 名字=None):
    """⚠️ **要带 `archived_at is null`。** 不带的话会拿到一个已归档的
    知识库然后往里导 —— 而归档的知识库在接口上看不见,
    于是「导进去了」和「什么都没导」在页面上长得一模一样。"""
    名字 = 名字 or 知识库名
    r = c.execute(text("select id from knowledge_bases where project_id=:p"
                       " and name=:n and archived_at is null"),
                  {"p": proj, "n": 名字}).scalar()
    if r:
        return r, False
    kb = 新("kb")
    c.execute(text("""insert into knowledge_bases
        (id, organization_id, project_id, name, status, created_at, created_by, revision)
        values (:i,:o,:p,:n,'active', now(), 'ingest', 1)"""),
              {"i": kb, "o": org, "p": proj, "n": 名字})
    return kb, True


def 导一份(c, org, proj, kb, 文件名, 目录=None):
    """导入一份文件。返回一句人话。"""
    路 = os.path.join(目录 or 语料目录, 文件名)
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
        # ⚠️ **切它的版本要记在行上。** 索引构建的输入指纹要用它 ——
        # 从代码常量读会隐含「库里的片段是当前版本切的」这个假设,
        # 而那个假设失效时**不报错**(见 chunks 的契约注释)。
        c.execute(text("""insert into chunks
            (id, organization_id, project_id, document_version_id, section_path,
             ordinal, text, text_hash, token_count,
             chunker_version, parser_version, created_at, created_by)
            values (:i,:o,:pj,:v,:sp,:ord,:t,:th,:tc,:cv,:pv, now(), 'ingest')"""),
                  {"i": 新("ch"), "o": org, "pj": proj, "v": dv,
                   "sp": p["section_path"], "ord": p["ordinal"], "t": p["text"],
                   "th": p["text_hash"], "tc": p["token_count"],
                   "cv": 切["切片器版本"], "pv": 切["解析器版本"]})
    警 = ("  ⚠️ " + " / ".join(解析["警告"])) if 解析["警告"] else ""
    return (f"{文件名}:新版本 v{最大 + 1}({解析['块们'] and len(解析['块们'])} 块 → "
            f"{len(切['片段们'])} 片段,丢掉 {解析['丢掉的块数']} 块){警}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--批次", default="业务拍板", choices=sorted(语料批次),
                    help="导哪一批语料(见 `语料批次`)")
    ap.add_argument("--项目", default=None,
                    help="导进哪个项目。**库里有多个项目时必须给** —— "
                         "原来是「导进第一个」,而那取决于建项目的顺序")
    a = ap.parse_args()
    批 = 语料批次[a.批次]
    目录, kb名 = 批["目录"], 批["知识库名"]
    print(f"\n▸ 导入语料:**{a.批次}** → 知识库「{kb名}」")
    print(f"  为什么选这一批:{批['为什么']}")
    if not os.path.isdir(目录):
        raise SystemExit(f"找不到语料目录 {目录}")
    排除 = set(批.get("排除") or ())
    全部 = sorted(f for f in os.listdir(目录) if f.endswith(".md"))
    文件们 = [f for f in 全部 if f not in 排除]
    跳过了 = [f for f in 全部 if f in 排除]
    if 跳过了:
        # ⚠️ **明说跳过了哪几份,不静默跳过。**
        # 「这一批就这么几份」和「有几份被排掉了」必须分得开。
        print(f"  ⚠️ 排除清单跳过 {len(跳过了)} 份:{跳过了}")
    if not 文件们:
        raise SystemExit(f"{目录} 里没有 .md —— **不静默导入 0 份**:"
                         f"「导完了」和「什么都没导」在输出上必须分得开")
    eng = create_engine(URL)
    with eng.begin() as c:
        org, proj = 要哪个项目(c, a.项目)
        kb, 新建 = 拿或建知识库(c, org, proj, kb名)
        print(f"项目 {proj} · 知识库 {kb名}({kb}{',新建' if 新建 else ''})")
        print(f"语料 {len(文件们)} 份:")
        for f in 文件们:
            print("  ·", 导一份(c, org, proj, kb, f, 目录))
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
