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
    # ⚠️ **U006 / U007 是 2026-09-28 做人工待办时补的 —— 在那之前
    # 演示数据里一个能审批的人都没有**,于是那道闸装好了而谁都放行不了。
    #
    # 权限矩阵里「审批工具动作」这条是这么分的(查过矩阵,不是猜的):
    #
    #     viewer / editor / annotator / trainer   deny       给不了
    #     approver                                 allow      角色默认有
    #     admin                                    grantable  **要显式授权**
    #
    # ⚠️ **连管理员默认也批不了** —— 这个设计很讲究:审批权不是「级别高就有」,
    # 它是一次**显式的授权动作**。和「模型不能批准自己」「发起人不能自批」
    # 同一条思路 —— **审批这件事被刻意做得不方便。**
    #
    # ⚠️ 还有一条我栽过的:**专项授权只能打开「可授权」的格子,打不开「否」**,
    # 否则专项授权就成了万能钥匙。给 viewer 发「审批工具动作」是**无效的**,
    # 而 `perms.判()` 会明说「要给就得改角色定义,不是发专项授权」。
    ("U006", A, "approver", []),            # 角色默认就有审批权
    ("U007", A, "admin", ["审批工具动作"]),   # 管理员 + 显式授权(grantable 那一档)
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
        # ── 模型连接(mock)──────────────────────────────────────────
        # ⚠️ 没有这一段的话,**Workflow 的 LLM 节点根本配不出来** ——
        # 它必填 connection_version_id,而演示数据里一条连接都没有。
        # 当时表现成:建一张图 → 点校验 → 两条「缺必填配置」,而人以为是模板坏了。
        #
        # **这条连接是 mock 的,而且它自己说自己是 mock**:capabilities 里写着
        # execution_mode=mock。规格 §19.4:mock 和真实实现同一个契约,
        # 正因为无缝,标记才是必需的 —— 否则「我们测过了」这句话没有含义。
        for p in (A, B):
            c.execute(text("""
                insert into model_connections (id, organization_id, project_id, purpose,
                    adapter, display_name, status, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,'generate','MockModelProvider','演示用 mock 生成连接',
                        'active', now(),'seed', now(), 1)
                on conflict (project_id, id) do nothing"""),
                      {"i": f"mc_mock_{p}", "o": ORG, "p": p})
            c.execute(text("""
                insert into connection_versions (id, organization_id, project_id,
                    connection_id, endpoint, secret_ref, capabilities, config_hash,
                    revision, created_at, created_by, updated_at)
                values (:i,:o,:p,:c,'mock://local','secret://none',:cap,:h,1,
                        now(),'seed', now())
                on conflict (project_id, id) do nothing"""),
                      {"i": f"cv_mock_{p}", "o": ORG, "p": p, "c": f"mc_mock_{p}",
                       # **不存密钥明文**,只存引用(§18)。
                       "cap": json.dumps({"execution_mode": "mock",
                                          "支持的参数": ["temperature", "max_tokens"],
                                          "原生工具调用": False,
                                          "说明": "合成适配器 —— **不代表真实智能能力**"
                                                  "(附录 D.2)"},
                                         ensure_ascii=False),
                       "h": f"mockhash_{p}"})
        # ── 第二条连接:**声明支持原生工具调用** ──────────────────────
        # 两条连接是有意的:一条支持、一条不支持。
        # 于是「§9.3 的原生工具调用能力检查」在界面上**能被看见** ——
        # 在 Agent 配置里选那条不支持的,校验会当场挡住并说清为什么。
        # 附录 D.2:「**不按模型家族名字推断兼容**」—— 这两条连接的差别
        # 只在 capabilities 上,名字上看不出来,**而那正是重点**。
        for p in (A, B):
            c.execute(text("""
                insert into model_connections (id, organization_id, project_id, purpose,
                    adapter, display_name, status, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,'generate','MockToolModelProvider',
                        '演示用 mock 工具调用连接','active', now(),'seed', now(), 1)
                on conflict (project_id, id) do nothing"""),
                      {"i": f"mc_tool_{p}", "o": ORG, "p": p})
            c.execute(text("""
                insert into connection_versions (id, organization_id, project_id,
                    connection_id, endpoint, secret_ref, capabilities, config_hash,
                    revision, created_at, created_by, updated_at)
                values (:i,:o,:p,:c,'mock://tools','secret://none',:cap,:h,1,
                        now(),'seed', now())
                on conflict (project_id, id) do nothing"""),
                      {"i": f"cv_tool_{p}", "o": ORG, "p": p, "c": f"mc_tool_{p}",
                       "cap": json.dumps({"execution_mode": "mock",
                                          "支持的参数": ["temperature", "max_tokens"],
                                          "原生工具调用": True,
                                          "说明": "合成适配器 —— **不代表真实智能能力**"
                                                  "(附录 D.2)"},
                                         ensure_ascii=False),
                       "h": f"mocktoolhash_{p}"})

        # ── 两个演示工具:一个只读、一个不可逆写入 ────────────────────
        # 不可逆那个是为了让「确认闸」和「ADAPTER_MISSING」都能被看见:
        # Worker 的 mock 只给只读工具接实现,**写工具故意不接** ——
        # 于是网关会报 ADAPTER_MISSING,而那是要被看见的(§14.1)。
        工具们 = [
            dict(id="tool_search", 名="search", 用途="按关键词搜官方资料",
                 级="read_only", 适配器="MockSearch",
                 说明="按关键词搜官方资料,返回带来源的条目。**价格找不到就返回 null,不要编**",
                 入={"type": "object",
                     "properties": {"q": {"type": "string", "minLength": 1}},
                     "required": ["q"], "additionalProperties": False},
                 出={"type": "object", "properties": {"items": {"type": "array"}}},
                 范围={"hosts": ["*.example.com"], "受管参数": []},
                 确认=None, 绑定={}, 查外部={"supported": True}, 可轮询=True),
            dict(id="tool_write_report", 名="write_report",
                 用途="把报告写进已授权目录下的一个文件",
                 级="irreversible", 适配器="MockWriteFile",
                 说明="把报告写到一个文件。**路径只能在已授权目录下**",
                 入={"type": "object",
                     "properties": {"path": {"type": "string"},
                                    "content": {"type": "string"}},
                     "required": ["path", "content"], "additionalProperties": False},
                 出={"type": "object",
                     "properties": {"artifact_ref": {"type": "string"}}},
                 范围={"paths": ["/out"], "受管参数": ["path"]},
                 确认={"谁批": "approver",
                       "为什么": "不可逆写入 —— 批准绑定参数摘要(§12.2)"},
                 # **服务端绑定**:输出根目录不让模型碰(§9.4)
                 绑定={"root": "/out"},
                 查外部={"supported": True}, 可轮询=False),
        ]
        for t in 工具们:
            c.execute(text("""
                insert into tool_definitions (id, organization_id, project_id, name,
                    purpose, side_effect_type, adapter, owner, draft_revision, status,
                    created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:n,:pu,:se,:ad,'seed',1,'active', now(),'seed', now(), 1)
                on conflict (project_id, id) do nothing"""),
                      {"i": t["id"], "o": ORG, "p": A, "n": t["名"], "pu": t["用途"],
                       "se": t["级"], "ad": t["适配器"]})
            c.execute(text("""
                insert into tool_versions (id, organization_id, project_id,
                    tool_definition_id, version_no, model_description, input_schema,
                    output_schema, side_effect_type, allowed_scopes,
                    confirmation_policy, idempotency_strategy, external_status_lookup,
                    timeout_seconds, retry_policy, redaction, server_bound_arguments,
                    pollable, content_hash, created_at, created_by)
                values (:i,:o,:p,:t,1,:md,:isc,:osc,:se,:sc,:cp,:ids,:esl,30,:rp,
                        '{}'::jsonb,:sba,:pl,:h, now(),'seed')
                on conflict (project_id, id) do nothing"""),
                      {"i": f"tv_{t['名']}", "o": ORG, "p": A, "t": t["id"],
                       "md": t["说明"],
                       "isc": json.dumps(t["入"], ensure_ascii=False),
                       "osc": json.dumps(t["出"], ensure_ascii=False),
                       "se": t["级"],
                       "sc": json.dumps(t["范围"], ensure_ascii=False),
                       "cp": json.dumps(t["确认"], ensure_ascii=False) if t["确认"] else None,
                       "ids": json.dumps({"键": "logical_action_id"}, ensure_ascii=False),
                       "esl": json.dumps(t["查外部"], ensure_ascii=False),
                       "rp": json.dumps({"可重试": ["TIMEOUT"], "次数": 2},
                                        ensure_ascii=False),
                       "sba": json.dumps(t["绑定"], ensure_ascii=False),
                       "pl": t["可轮询"], "h": f"seedtoolhash_{t['名']}"})

        # ── 演示工具组:一个只读 + 一个会写(2026-10-02 加)────────────────
        #
        # ⚠️ **它有业务理由,不是为了喂判据。**
        # 规格 §9 要工具组是「**稳定搭配**」。而演示项目这两个工具
        # (搜索 = 只读、写报告 = 不可逆)正是最常见的那种搭配:
        # **先查后写**。配套关系也有自然落点:写报告之前该先搜一下。
        # > 一个为了喂判据而存在的数据,和一个有业务理由的数据 ——
        # > **前者会在下次清理时被删掉**。
        #
        # 顺带也解决一件事:`ifmatch_reachable_check` 要从 `/tool-groups`
        # 列表取一个样例 id 去验「界面拿得到 revision 吗」,
        # 而 CI 是**从零建库** —— 一个组都没有的话那条判据
        # **什么都没验到**(它自己明说这不算通过)。
        c.execute(text("""insert into tool_groups
            (id, organization_id, project_id, name, purpose, owner, status,
             draft_revision, created_at, created_by, updated_at, revision)
            values ('tg_先查后写',:o,:p,'先查后写',
                    '最常见的搭配:先搜一下再写报告。'
                    '一个只读 + 一个不可逆,正好也是配套关系的落点',
                    'seed','active', 1, now(),'seed', now(), 1)
            on conflict (project_id, id) do nothing"""),
                  {"o": ORG, "p": A})
        # ⚠️ **连一个冻结版本一起铺** —— 没有版本的组 Agent 引用不了,
        # 而「有组没版本」和「没有组」在 Agent 配置页上长得一样。
        c.execute(text("""insert into tool_group_versions
            (id, organization_id, project_id, tool_group_id, version_no,
             member_manifest, companion_map, content_hash, change_note,
             created_at, created_by, updated_at, revision)
            values ('tgv_先查后写_v1',:o,:p,'tg_先查后写',1,
                    cast(:mm as jsonb), cast(:cm as jsonb),
                    'seedtgvhash_先查后写',
                    '首版:搜索(只读)+ 写报告(不可逆),写之前先搜',
                    now(),'seed', now(), 1)
            on conflict (project_id, id) do nothing"""),
                  {"o": ORG, "p": A,
                   "mm": json.dumps([
                       {"tool_version_id": "tv_search", "加载角色": "常驻",
                        "必不可少吗": True},
                       {"tool_version_id": "tv_write_report",
                        "加载角色": "候选", "必不可少吗": False},
                   ], ensure_ascii=False),
                   # 写报告之前该先搜 —— **单向,不成环**
                   # (成环的话预算算法会反复把两个都算进同一组)。
                   "cm": json.dumps({"tv_write_report": ["tv_search"]},
                                    ensure_ascii=False)})

        # Prompt 正式版本:Workflow 的 LLM 节点要引用**确切版本**,不是草稿。
        #
        # ⚠️ **version_no 要算 max+1,不能写死 1。**
        # 第一版写死 1,而这个 key 已经有 v1 了 —— 于是同一个 key 出现两个 v1。
        # 库里**拦不住**这件事(唯一约束是 (project_id, key, content_hash),
        # 没有 (project_id, key, version_no)),所以它安静地活了下来。
        # 抓到它的是一条**看起来无关**的端到端断言:那条断言拿「版本条数+1」
        # 当「最大版本号+1」的替身,而这两个数只在版本号**密集且唯一**时才相等。
        # 报出来的理由是「版本号没前进一格」,而真相是「演示数据里有两个 v1」——
        # **又一次指错方向。** 所以这次连同那条缺失的唯一约束一起补上。
        c.execute(text("""
            insert into prompt_versions (id, organization_id, project_id, key, version_no,
                messages, variable_schema, output_schema, params, content_hash,
                created_at, created_by, updated_at, revision)
            select :i,:o,:p, d.key,
                   coalesce((select max(v.version_no) from prompt_versions v
                              where v.project_id=:p and v.key=d.key), 0) + 1,
                   d.messages, d.variable_schema, d.output_schema, d.params,
                   'seedhash_article_summary', now(),'seed', now(), 1
              from prompt_drafts d where d.project_id=:p and d.id='pr_article_summary'
            on conflict (project_id, id) do nothing"""),
                  {"i": "pv_seed_article_summary", "o": ORG, "p": A})

    with 事务() as c:
        n = {t: c.execute(text(f"select count(*) from {t}")).scalar()
             for t in ("organizations", "projects", "memberships", "prompt_drafts",
                       "model_connections", "connection_versions", "prompt_versions",
                       "tool_definitions", "tool_versions")}
    return n


if __name__ == "__main__":
    n = 跑()
    print("✅ 演示数据就绪(**重复跑不会增加对象**):", n)
    print("   身份用请求头 X-Dev-User,可选:" + "、".join(
        f"{u}({r}{'+专项' if g else ''}@{p.split('_')[-1]})" for u, p, r, g in 人))
