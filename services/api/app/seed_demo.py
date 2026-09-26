#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成演示数据 —— **只在开发环境跑,重复执行不增加重复对象**(规格 §17.5)。

## 两条规格明写的约束

① **仅在开发环境导入**:生产库灌演示数据之后,「这条是真的还是演示的」
   就再也分不清了 —— 而它们在表上长得一模一样。
② **重复执行不增加重复对象**:幂等。一个每跑一次就多一份数据的 seed,
   会让「库里有 3 个项目」变成一句没有含义的话。
③ **不连接收费提供商** —— 这份数据全是本地造的。

## 为什么两个项目

跨项目隔离要能**被演示**:A 项目的人看不到 B 项目的东西。
只有一个项目的话,那条边界在界面上根本无从验证。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runtime_cfg as CFG
from sqlalchemy import text
from db import 事务

if CFG.APP_ENV != CFG.开发:
    # **当场退出,不是打印一句警告** —— 警告会被脚本的 tail 吃掉
    raise SystemExit(f"❌ seed-demo 只在开发环境跑,现在 APP_ENV={CFG.APP_ENV}。"
                     f"演示数据进了非开发库,「真的还是演示的」就再也分不清了")

ORG = "org_demo"
A, B = "project_demo_a", "project_demo_b"

人 = [
    # (工号, 项目, 角色, 专项授权)
    ("U001", A, "admin", []),
    ("U002", A, "editor", []),
    ("U003", A, "viewer", []),
    # ⚠️ 这一位有「查看敏感输入」专项授权 —— 用来演示**字段级权限**的差别:
    # 同一个 trace,他看得到原文,U002 看到的是脱敏版
    ("U004", A, "annotator", ["查看敏感输入/独立测试答案"]),
    ("U005", B, "editor", []),      # 只在 B 项目 —— 用来演示跨项目隔离
]

PROMPTS = [
    dict(key="article_summary", 用途="把文章整理成结论、依据、待核实事项",
         标签=["摘要", "通用"],
         system="你是严谨的资料整理助手。**只使用给定文章里的内容**,"
                "查不到的写「文章未提及」,不要补充外部知识。",
         user="文章:\n{{article}}\n\n读者:{{audience}}\n\n"
              "请输出三段:结论 / 依据(引用原文) / 待核实事项。",
         变量=[dict(名称="article", 说明="要整理的文章正文", 类型="string",
                   来源="用户输入", 必填=True, 长度上限=20000),
               dict(名称="audience", 说明="读者是谁", 类型="string",
                    来源="用户输入", 必填=False, 默认值="普通读者")],
         输出要求=dict(格式="markdown", 必含项=["结论", "依据", "待核实事项"],
                     未知值规则="查不到就写「文章未提及」,**不要写 0 也不要留空**"),
         变更说明="初版"),
    dict(key="ticket_classify", 用途="把工单分类并给出依据",
         标签=["分类"],
         system="按给定类别表分类。**类别表之外的一律归到「其他」并说明原因**,"
                "不要自己新造类别。",
         user="工单:{{ticket}}\n类别表:{{categories}}",
         变量=[dict(名称="ticket", 说明="工单内容", 类型="string",
                   来源="用户输入", 必填=True),
               dict(名称="categories", 说明="可选类别", 类型="array",
                    来源="受控系统字段", 必填=True)],
         输出要求=dict(格式="json", 必含项=["category", "reason"]),
         变更说明="初版"),
    # 这一条**故意留着缺陷**:模板里用了没定义的变量 —— 用来演示
    # 「保存为新版本」被前置校验挡住的样子(§8.5),而不是让人以为总是能存
    dict(key="draft_with_gap", 用途="演示:前置校验会挡住什么",
         标签=["演示"],
         system="", user="请根据 {{context}} 和 {{未定义的变量}} 作答。",
         变量=[dict(名称="context", 说明="上下文", 类型="string",
                   来源="检索上下文", 必填=True)],
         输出要求={}, 变更说明=""),
]


def 跑():
    with 事务() as c:
        c.execute(text("""
            insert into organizations (id, name, status, created_at, created_by)
            values (:i,'演示组织','active', now(), 'seed')
            on conflict (id) do nothing"""), {"i": ORG})
        for p, n in ((A, "演示项目 A"), (B, "演示项目 B(用来验跨项目隔离)")):
            c.execute(text("""
                insert into projects (id, organization_id, name, owner, status,
                    timezone, created_at, created_by, updated_at, revision)
                values (:i,:o,:n,'U001','active','Asia/Shanghai', now(),'seed', now(),1)
                on conflict (id) do nothing"""), {"i": p, "o": ORG, "n": n})
        for u, p, role, g in 人:
            # 幂等:唯一约束是 (organization_id, project_id, user_id)
            c.execute(text("""
                insert into memberships (id, organization_id, project_id, user_id, role,
                    special_grants, status, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:u,:r,:g,'active', now(),'seed', now(),1)
                on conflict (organization_id, project_id, user_id) do update
                   set role=excluded.role, special_grants=excluded.special_grants"""),
                      {"i": f"mb_{u}_{p}", "o": ORG, "p": p, "u": u, "r": role,
                       "g": json.dumps(g, ensure_ascii=False)})
        for d in PROMPTS:
            c.execute(text("""
                insert into prompt_drafts (id, organization_id, project_id, key, messages,
                    variable_schema, output_schema, params, revision,
                    created_at, created_by, updated_at)
                values (:i,:o,:p,:k,:m,:vs,:os,'{}'::jsonb, 1, now(),'seed', now())
                on conflict (project_id, id) do update
                   set messages=excluded.messages,
                       variable_schema=excluded.variable_schema,
                       output_schema=excluded.output_schema"""),
                      {"i": f"pr_{d['key']}", "o": ORG, "p": A, "k": d["key"],
                       "m": json.dumps({"用途": d["用途"], "标签": d["标签"],
                                        "system": d["system"], "user": d["user"],
                                        "变更说明": d["变更说明"]}, ensure_ascii=False),
                       "vs": json.dumps(d["变量"], ensure_ascii=False),
                       "os": json.dumps(d["输出要求"], ensure_ascii=False)})
        # B 项目也放一条,名字一样 —— 这样「改 URL 里的项目号」能被演示成查不到
        c.execute(text("""
            insert into prompt_drafts (id, organization_id, project_id, key, messages,
                variable_schema, output_schema, params, revision,
                created_at, created_by, updated_at)
            values (:i,:o,:p,'article_summary',
                    '{"用途":"B 项目自己的摘要 Prompt","标签":[],"system":"B","user":"{{x}}","变更说明":""}'::jsonb,
                    '[]'::jsonb,'{}'::jsonb,'{}'::jsonb,1, now(),'seed', now())
            on conflict (project_id, id) do nothing"""),
                  {"i": "pr_article_summary_b", "o": ORG, "p": B})
    with 事务() as c:
        n = {t: c.execute(text(f"select count(*) from {t}")).scalar()
             for t in ("organizations", "projects", "memberships", "prompt_drafts")}
    return n


if __name__ == "__main__":
    n = 跑()
    print("✅ 演示数据就绪(**重复跑不会增加对象**):", n)
    print("   身份用请求头 X-Dev-User,可选:" + "、".join(
        f"{u}({r}{'+专项' if g else ''}@{p.split('_')[-1]})" for u, p, r, g in 人))
