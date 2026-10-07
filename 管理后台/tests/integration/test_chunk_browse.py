#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**切片栏目**(列表 + 详情)—— 在真 PG 上验。业务 2026-10-07 要的那个栏目。

切片级**权限**那一拍是不做(要收紧就拆成独立文档),但**看得见**是要做的:
一个人要能回答「我导进去的那段话到底被切成了什么样」「为什么搜不到」。

## 这一组每一条对着一种「看起来对了而实际漏了」

   ① 列表不过滤权限 → **它成了绕开检索权限的后门**(不检索,直接翻列表)
   ② 列表给了所有历史版本的片段 → 含已被改掉的内容,而数量看着也像对的
   ③ 混版本告警受 document_id 筛选影响 → **筛一下,一条真告警就消失了**
   ④ 「看不到」和「不存在」回不同的错 → 它成了一个存在性探测器
   ⑤ 分页顺序不确定 → 翻页重复或漏,而「漏了一条」和「那条不存在」长得一样
   ⑥ 「为什么检索不到」只说一句笼统的 → 旧版本和没进索引是两件事,去查的方向相反

## ⚠️ 这个文件为什么不能用 rollback(和 test_corpus_acl_live 不同)

那份是**自己持连接**,所以能「填 ACL → 验 → rollback」,库里一个字不留。
而这里测的是**接口函数**,它内部用 `连接()` 自己开连接 ——
**看不到我的事务**,填在事务里它读不到。

所以这里只能 try/finally + 收尾断言。**这个妥协要写出来**:
> 一次「清干净了」和一次「中途炸了、而 finally 之前就炸」,
> 在那次失败的输出上长得一模一样 —— 后者会留下脏 ACL。
清理写在 `finally` 里(不是末尾),收尾再断言一次「库里一条都没留下」。
"""
import json
import os
import sys

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


def 我是(角色, org, proj):
    return 身份(user_id="u_test", org_id=org, project_id=proj, role=角色, grants=[])


print("=" * 92)
print("切片栏目 · 列表 + 详情(真 PG)")
print("=" * 92)

with eng.connect() as c:
    org, proj, kb, 篇数 = c.execute(text("""
        select d.organization_id, d.project_id, d.knowledge_base_id, count(*)
          from documents d
         where d.disabled_at is null and d.archived_at is null
         group by 1, 2, 3 order by count(*) desc limit 1""")).first()
    片段数 = c.execute(text("""
        select count(*) from chunks ch
          join document_versions dv on dv.project_id=ch.project_id
                                   and dv.id=ch.document_version_id
          join documents d on d.project_id=dv.project_id and d.id=dv.document_id
         where d.project_id=:p and d.knowledge_base_id=:k"""),
        {"p": proj, "k": kb}).scalar()
ck("找到一个有片段的知识库", 片段数 > 5, f"{篇数} 篇 · {片段数} 个片段(含历史版本)")
if 片段数 < 5:
    print("\n❌ 片段太少,验不出分页和筛选 —— **不在样本量不够时出结论**")
    sys.exit(1)

print("\n▸ ① 列表:只给最新那一版")
全 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj), limit=200)
ck("列表跑通", 全["total"] > 0, f"total={全['total']} · 返回 {len(全['items'])} 条")
with eng.connect() as c:
    最新数 = c.execute(text("""
        select count(*) from chunks ch
          join document_versions dv on dv.project_id=ch.project_id
                                   and dv.id=ch.document_version_id
          join documents d on d.project_id=dv.project_id and d.id=dv.document_id
         where d.project_id=:p and d.knowledge_base_id=:k
           and d.archived_at is null and dv.archived_at is null
           and d.disabled_at is null
           and dv.revision = (select max(dv2.revision) from document_versions dv2
                               where dv2.project_id=dv.project_id
                                 and dv2.document_id=dv.document_id
                                 and dv2.archived_at is null)"""),
        {"p": proj, "k": kb}).scalar()
ck("🔑 `total` 等于**最新版**片段数,不是全部版本的",
   全["total"] == 最新数, f"接口 {全['total']} / 最新版 {最新数} / 全部 {片段数}")
ck("每条都带得翻回原文的东西(节路径 + 第几段)",
   all(x["section_path"] is not None and x["ordinal"] is not None
       for x in 全["items"]))
ck("每条都标了**在役索引数** —— 回答「我明明导入了为什么搜不到」",
   all("在役索引数" in x for x in 全["items"]),
   f"在役的 {sum(1 for x in 全['items'] if x['在役索引数'])} / {len(全['items'])}")
ck("正文只给预览(不是全文)+ 标了真实长度",
   all(len(x["正文预览"] or "") <= 120 and x["正文长度"] >= len(x["正文预览"] or "")
       for x in 全["items"]))

print("\n▸ ② 分页:顺序确定,翻页不重不漏")
一 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj),
             limit=3, offset=0)
二 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj),
             limit=3, offset=3)
再一 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj),
              limit=3, offset=0)
ck("同一页**两次结果一样**(顺序确定) —— 不确定的话翻页会重复或漏,"
   "而「漏了一条」和「那条不存在」在界面上长得一模一样",
   [x["id"] for x in 一["items"]] == [x["id"] for x in 再一["items"]])
ck("第 1 页和第 2 页**没有交集**",
   not ({x["id"] for x in 一["items"]} & {x["id"] for x in 二["items"]}),
   f"{[x['ordinal'] for x in 一['items']]} / {[x['ordinal'] for x in 二['items']]}")
ck("两页拼起来等于 limit=6 那一页",
   [x["id"] for x in 一["items"]] + [x["id"] for x in 二["items"]]
   == [x["id"] for x in KA.切片列表(project_id=proj, kb_id=kb,
                                me=我是("admin", org, proj), limit=6)["items"]])

print("\n▸ ③ 混版本告警:**整库一起看,不受 document_id 筛选影响**")
某篇 = 全["items"][0]["文档id"]
筛 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj),
             document_id=某篇, limit=200)
ck("筛某篇文档:条数变少", 筛["total"] < 全["total"], f"{筛['total']} < {全['total']}")
ck("🔑 **筛选后那条告警和不筛时一样** —— 第一版我拿带筛选的查询算告警,"
   "于是「这个库建不出索引」这条真告警会在筛选状态下**消失**",
   筛["混着切的吗"] == 全["混着切的吗"]
   and 筛["切片器版本们"] == 全["切片器版本们"],
   f"全库 {全['切片器版本们']} / 筛后 {筛['切片器版本们']}")
ck("不混的时候「混了会怎样」是 None(不是空字符串)——「没混」和「混了但说不出」要分得开",
   (全["混了会怎样"] is None) == (not 全["混着切的吗"]),
   f"混={全['混着切的吗']} 说明={全['混了会怎样']!r}")

print("\n▸ ④ 详情")
一条 = 全["items"][0]["id"]
详 = KA.切片详情(project_id=proj, chunk_id=一条, me=我是("admin", org, proj))
ck("详情给全文(不是预览)", len(详["text"]) == 全["items"][0]["正文长度"],
   f"{len(详['text'])} 字")
ck("说清**谁看得到**,而且理由是 `语料可见` 给的",
   详["谁看得到"] and 详["为什么是这些人"], 详["为什么是这些人"][:60])
ck("🔑 明说**不能单独设这一段的权限**,并给出替代动作(拆成独立文档)——"
   "否则界面上的「谁看得到」会被当成「可以在这里改」",
   详["能单独设这一段的权限吗"] is False and "拆成独立文档" in 详["为什么不能"])
ck("「检索得到吗」是个明确的布尔,不让人从 0 里猜",
   isinstance(详["检索得到吗"], bool))
ck("🔑 检索不到时**分开说是哪一种** —— 旧版本 vs 没进索引,"
   "这两件事去查的方向相反",
   详["检索得到吗"] or ("旧版本" in 详["为什么检索不到"]
                   or "不在任何已就绪的索引里" in 详["为什么检索不到"]),
   详["为什么检索不到"])
ck("检索得到时「为什么检索不到」是 None",
   (详["为什么检索不到"] is None) == 详["检索得到吗"])
ck("不泄露原文件的对象存储键之外的东西(没有把 acl 原样吐出来)",
   "知识库acl" not in 详 and "acl_override" not in 详, sorted(详)[:6])

print("\n▸ ⑤ 权限:列表和详情**都**过滤,而且「看不到」和「不存在」同形")
# ⚠️ 这里要填 ACL 才验得到。而接口自己开连接,**看不到我的事务** ——
# 所以不能像 test_corpus_acl_live 那样 rollback。清理放在 finally 里。
试了 = False
try:
    with eng.begin() as c:
        c.execute(text("update knowledge_bases set acl=:a where project_id=:p and id=:k"),
                  {"a": json.dumps({"roles": ["admin"]}), "p": proj, "k": kb})
    试了 = True
    看不见 = KA.切片列表(project_id=proj, kb_id=kb, me=我是("viewer", org, proj),
                    limit=200)
    ck("🔑 **列表按权限过滤** —— viewer 一条都看不到(库限 admin)。"
       "不过滤的话这个接口就是绕开检索权限的后门:不检索,直接翻列表",
       看不见["total"] == 0, f"viewer 看到 {看不见['total']} 条")
    ck("而 admin 照旧看得到",
       KA.切片列表(project_id=proj, kb_id=kb, me=我是("admin", org, proj),
                limit=200)["total"] == 最新数)
    try:
        KA.切片详情(project_id=proj, chunk_id=一条, me=我是("viewer", org, proj))
        ck("详情该挡住 viewer", False, "**没挡住**")
    except Exception as e:
        码 = getattr(e, "status_code", None)
        ck("🔑 **详情对 viewer 回 404(和「不存在」同形)** —— 回 403 的话"
           "拿 id 枚举一遍就知道哪些 id 存在,而那本身是信息",
           码 == 404, f"status={码}")
    try:
        KA.切片详情(project_id=proj, chunk_id="ch_根本没有这个",
                 me=我是("admin", org, proj))
        ck("不存在的 id 该 404", False, "没抛")
    except Exception as e:
        ck("对照:不存在的 id 也是 404 —— **两者同形**",
           getattr(e, "status_code", None) == 404)
    # 知识库列表那个「片段数」也该跟着过滤
    kbs = KA.知识库列表(project_id=proj, me=我是("viewer", org, proj), limit=100)
    这个 = [x for x in kbs["items"] if x["id"] == kb]
    ck("🔑 知识库列表的**片段数**也按权限过滤 —— 不过滤的话那个数在"
       "泄露他看不到的文档有多少内容",
       这个 and 这个[0]["片段数"] == 0, 这个[0]["片段数"] if 这个 else "没找到")
finally:
    if 试了:
        with eng.begin() as c:
            c.execute(text("update knowledge_bases set acl=null "
                           "where project_id=:p and id=:k"), {"p": proj, "k": kb})

with eng.connect() as c:
    留 = c.execute(text("select count(*) from knowledge_bases where acl is not null")
                   ).scalar()
ck("跑完库里一条 ACL 都没留下(清理在 finally 里,不在末尾)", 留 == 0, f"{留} 条")

print("\n" + "=" * 92)
print(f"{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print("   ·", x)
sys.exit(1 if 挂 else 0)
