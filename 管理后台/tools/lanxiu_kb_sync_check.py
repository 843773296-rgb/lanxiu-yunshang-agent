#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台知识库里的那些文档,和仓库里的 md **真的一样吗**。

## 为什么需要它

`tools/ingest_lanxiu.py` 把澜绣的语料导进后台知识库(2026-10-02 做完,
搬家说明 `已搬走.md` 的第三条待办)。而导入是**单向**的:
**文件是真相源,知识库是它的可检索索引**。

于是最大的风险是:**文件改了,而知识库没跟上**。

那种不一致特别危险,因为后台那一页**看起来完全正常** ——
它显示着 18 篇文档和它们的版本历史,而内容已经是旧的。
顾问检索到的是旧片段,**而片段上带着「第几节第几段」的引用**,
看起来证据链完整。

> **一个显示着旧内容的知识库,比一个空的更坏** ——
> 空的会让人去找真东西,旧的让人以为自己查到的就是现在的规矩。

## 这条判据怎么判

对每一批语料(`ingest_lanxiu.语料批次`),比:
  · 文件系统里有哪些 md(减掉排除清单)
  · 知识库里有哪些文档(靠 `source_info->>'path'` 认)
  · **每一份的最新版本 `content_hash` 和文件现在的哈希**

四种红法:
  · **文件有、知识库没有**:红(新加的 md 没导)
  · **知识库有、文件没有**:红(文件删了而文档还在 ——
    那一份会在检索里一直被当成现行规矩)
  · **哈希不一样**:红,点名是哪几份(文件改了没重导)
  · **一批都没扫到**:红(**扫不到不是通过**)

## ⚠️ 哈希算法从导入脚本里拿,不抄一份

抄一份的话两边会在谁都没改它的那天开始不一致 ——
而那时这条判据会报出一片「不一致」,**而真实内容是一样的**。
(同一条今天在 `lanxiu_prompt_sync_check` 和冻结时的 Schema 校验上
都用过:**一份被抄成两处的清单,它的两份迟早分岔**。)

## 已知盲区

- **只比原文哈希,不比切片结果。** 切片器改了而文件没改时,
  这条判据是绿的,而库里的片段是旧切法。
  那一半要靠「切片器版本进快照」—— 现在没有,**写下来才和「忘了」分得开**。
- **不验向量。** 片段重切之后向量要重建,而这条判据看不见那件事。
- **只看澜绣那个项目。** 演示项目下同名的那个知识库是三份集成测试的
  夹具(`test_retrieval` / `test_index_build` / `test_vector_constraints`
  按名字找它),**故意不管**。
"""
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "tools"))

项目id = "project_lanxiu"


def main():
    print(f"\n\033[1m▸ 后台知识库和仓库里的 md 一致吗{D}")
    print("  ⚠️ 这条判据看的是**「索引里的 == 文件里的」** —— "
          "导入是单向的,文件改了知识库不会自己跟上,"
          "**而那时后台那一页看起来完全正常**")

    # ⚠️ 哈希算法和批次定义都从导入脚本里拿 —— 见文档串那一段。
    import ingest_lanxiu as ING

    from db import 连接          # noqa: E402
    from sqlalchemy import text as _t

    with 连接() as c:
        有项目 = c.execute(_t("select 1 from projects where id=:i"),
                        {"i": 项目id}).first()
        if not 有项目:
            print(f"  {R}❌ 后台里没有 `{项目id}` —— "
                  f"**这是数据没导入,不是判据坏了**{D}")
            print(f"     跑 `python3 tools/import_lanxiu_prompts.py` 建项目,"
                  f"再跑 `python3 tools/ingest_lanxiu.py --批次 … --项目 {项目id}`")
            return 1

        总共比了 = 0
        for 批名, 批 in sorted(ING.语料批次.items()):
            目录, kb名 = 批["目录"], 批["知识库名"]
            排除 = set(批.get("排除") or ())
            if not os.path.isdir(目录):
                print(f"  {R}❌ 找不到语料目录 {目录}(批次「{批名}」){D}")
                return 1
            文件们 = {f: open(os.path.join(目录, f), encoding="utf-8").read()
                   for f in sorted(os.listdir(目录))
                   if f.endswith(".md") and f not in 排除}
            if not 文件们:
                # ⚠️ 空集合上所有性质都成立。
                print(f"  {R}❌ 批次「{批名}」一份 md 都没扫到 —— "
                      f"**扫不到不是通过**{D}")
                return 1
            kb = c.execute(_t("""select id from knowledge_bases
                               where project_id=:p and name=:n
                                 and archived_at is null"""),
                          {"p": 项目id, "n": kb名}).scalar()
            if not kb:
                print(f"  {R}❌ 澜绣项目下没有知识库「{kb名}」(批次「{批名}」){D}")
                print(f"     跑 `python3 tools/ingest_lanxiu.py "
                      f"--批次 {批名} --项目 {项目id}`")
                return 1
            # 每篇文档的**最新**版本哈希。
            # ⚠️ 按 `revision` 取最大 —— 导入脚本就是按它递增的。
            行 = c.execute(_t("""select d.source_info->>'path' as 路,
                                      dv.content_hash as 哈, dv.revision as 号
                               from documents d
                               join document_versions dv
                                 on dv.project_id=d.project_id
                                and dv.document_id=d.id
                              where d.project_id=:p and d.knowledge_base_id=:k
                                and d.archived_at is null
                                and dv.revision = (
                                    select max(revision) from document_versions
                                     where project_id=d.project_id
                                       and document_id=d.id)"""),
                          {"p": 项目id, "k": kb}).mappings().all()
            库里 = {}
            for r in 行:
                名 = os.path.basename(r["路"] or "")
                库里[名] = (r["哈"], r["号"])
            少导 = sorted(set(文件们) - set(库里))
            多出 = sorted(set(库里) - set(文件们))
            不一致 = []
            for f in sorted(set(文件们) & set(库里)):
                if ING.内容哈希(文件们[f]) != 库里[f][0]:
                    不一致.append((f, 库里[f][1]))
            总共比了 += len(文件们 or {})
            print(f"\n  ▸ 「{批名}」→ 知识库「{kb名}」:"
                  f"文件 {len(文件们)} 份 · 库里 {len(库里)} 份"
                  + (f"(排除 {len(排除)})" if 排除 else ""))
            if 少导:
                print(f"  {R}❌ 文件有、知识库**没有**的 {len(少导)} 份:{少导}{D}")
                print(f"     跑 `python3 tools/ingest_lanxiu.py "
                      f"--批次 {批名} --项目 {项目id}`")
                return 1
            if 多出:
                print(f"  {R}❌ 知识库有、文件**没有**的 {len(多出)} 份:{多出}{D}")
                print(f"     文件删掉了而文档还在 —— "
                      f"**那一份会在检索里一直被当成现行规矩**。")
                return 1
            if 不一致:
                print(f"  {R}❌ 这 {len(不一致)} 份内容**对不上**"
                      f"(文件改了而没重导):{D}")
                for f, 号 in 不一致:
                    print(f"     · {f}(库里最新是 v{号})")
                print(f"     跑 `python3 tools/ingest_lanxiu.py "
                      f"--批次 {批名} --项目 {项目id}` —— "
                      f"它只给真变了的那几份出新版本。")
                print(f"     {Y}⚠️ 在这之前后台那一页看起来完全正常:"
                      f"它显示着文档和版本历史,而顾问检索到的是旧片段 —— "
                      f"**而片段上带着「第几节第几段」,看起来证据链完整**。{D}")
                return 1
            print(f"  {G}✅ 逐份对上了(比的是原文内容哈希){D}")

    if not 总共比了:
        print(f"  {R}❌ 一份都没比到 —— **扫不到不是通过**{D}")
        return 1
    print(f"\n  {G}✅ 两批共 {总共比了} 份,逐份对上{D}")
    print(f"  ⚠️ 盲区:**只比原文哈希,不比切片结果** —— "
          f"切片器改了而文件没改时这条是绿的,而库里的片段是旧切法。")
    print(f"     那一半要靠「切片器版本进快照」,现在没有。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
