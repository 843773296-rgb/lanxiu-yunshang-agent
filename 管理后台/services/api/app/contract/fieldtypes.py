#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字段类型:**声明过的命名约定 + 显式覆盖**,认不出的当场抛。

## 为什么不给默认类型

最省事的写法是「认不出的字段就当 TEXT」。那是把**「我不知道这个字段是什么」
变成一句听起来很肯定的话** —— 一张全是 TEXT 的表能建起来、能跑、看着完全正常,
直到有人往 `amount` 里写了字符串,或者 `created_at` 按字典序排出了 2026 在 202 前面。

> **一个错的类型和一个对的类型,在建表成功那一刻长得一模一样。**

所以这里没有兜底分支:字段要么命中一条**写明了的**后缀约定,要么在覆盖表里点名。
两样都没有 → `类型(字段)` 抛异常,建表失败。**失败比默默建错强。**

## 约定为什么按后缀

因为后缀是这套契约里**已经在用**的命名习惯(`_at` / `_id` / `_hash` / `_count`),
不是我现编的规则。规格 §18 也是这么写字段的。
按后缀判等于把已有习惯写成可执行的,而不是新加一套要求。
"""

# 后缀约定 —— 顺序有意义:**长的先匹配**(`_version_id` 要先于 `_id`)。
后缀约定 = [
    ("_name",          "TEXT",        "名字(display_name)"),
    ("_output",        "JSONB",       "模型输出:留 {text, structured, refs} 的余地。"
                                     "**敏感原文按 §18 另存并单独授权**,这里只放可公开的部分"),
    ("_at",            "TIMESTAMPTZ", "时间点一律带时区:跨环境跨时区的系统里,不带时区的时间戳是个陷阱"),
    ("_until",         "TIMESTAMPTZ", "租约到期时间"),
    ("_id",            "TEXT",        "对象 ID;跨对象引用另外加含项目范围的外键"),
    ("_ids",           "JSONB",       "一串 ID"),
    ("_ref",           "TEXT",        "引用(如 secret_ref):**只存引用,不存内容**"),
    ("_hash",          "TEXT",        "内容哈希,认出「同一份内容」靠它"),
    ("_count",         "INTEGER",     "计数"),
    ("_attempts",      "INTEGER",     "次数上限(max_attempts)"),
    ("_code",          "TEXT",        "错误代码:**要能分「该不该重试」** —— "
                                     "格式错误/权限不足/预算禁止不许盲重试"),
    ("_detail",        "JSONB",       "错误细节(不进 code,因为 code 要能被当枚举用)"),
    ("_check",         "BOOLEAN",     "「要不要人来看」的标记(needs_human_check)。"
                                     "⚠️ 它**不是终态** —— 把它当成结束会让人去重跑"),
    ("_no",            "INTEGER",     "序号(version_no)"),
    ("_amount",        "NUMERIC(20,6)", "金额:**绝不用浮点** —— 钱的舍入误差会累积成对不上的账"),
    ("_known",         "BOOLEAN",     "「这个值知不知道」:配合 amount/value 用,**未知 ≠ 零**"),
    ("_requested",     "BOOLEAN",     "请求标记(cancel_requested)"),
    ("_map",           "JSONB",       "映射(split_map)"),
    ("_manifest",      "JSONB",       "清单(file_manifest)"),
    ("_schema",        "JSONB",       "JSON Schema(variable_schema / output_schema)"),
    ("_snapshot",      "JSONB",       "快照:建任务时固化,之后改配置不影响它"),
    # ⚠️ **这一条在 Workflow/Agent 规格进来之后翻过面:TEXT → JSONB。**
    # 老域里 `_policy` 是个名字(`retention_policy` = "30d"、`data_egress_policy` = "deny");
    # 编排域里它一律是结构化对象 —— `retry_policy` = {可重试类型, 次数, 退避}、
    # `confirmation_policy` = {谁批, 什么情况下要批}、`idempotency_strategy` = {键怎么算}。
    # 两个老字段在 显式类型 里被钉成 TEXT(显式优先于后缀),所以翻这一条**不会动到它们** ——
    # 而 spec_coverage 里有一条断言专门钉这件事:**翻了面不许把老字段悄悄带走**。
    ("_policy",        "JSONB",       "策略对象(重试 / 确认 / 幂等 / 上下文)"),
    ("_strategy",      "JSONB",       "策略对象(失败 / 无法完成 / 执行方式)"),
    ("_criteria",      "JSONB",       "判据清单(完成条件)"),
    ("_template",      "TEXT",        "模板文本(任务目标 / 规则模板)"),
    ("_revision",      "BIGINT",      "版本号(draft_revision / request_revision):"
                                     "乐观锁靠它,**不是时间戳**"),
    ("_note",          "TEXT",        "备注(变更说明 / 风险说明)"),
    ("_description",   "TEXT",        "说明文字(模型可见的工具说明)"),
    ("_type",          "TEXT",        "类型枚举(side_effect_type / event_type)"),
    ("_fields",        "JSONB",       "字段清单(允许编辑 / 实际编辑了哪些)"),
    ("_roles",         "JSONB",       "角色清单(候选审批人)"),
    ("_scopes",        "JSONB",       "允许的对象范围"),
    ("_endpoints",     "JSONB",       "允许的端点白名单"),
    ("_conditions",    "JSONB",       "适用条件"),
    ("_cases",         "JSONB",       "测试用例"),
    ("_report",        "JSONB",       "报告(校验报告)"),
    ("_arguments",     "JSONB",       "参数(服务端绑定参数)"),
    ("_lookup",        "JSONB",       "查询能力声明(external_status_lookup):"
                                     "**没有它就承诺不了 exactly-once**"),
    ("_seconds",       "INTEGER",     "秒(超时 / 期限)"),
    ("_ms",            "INTEGER",     "毫秒(耗时)"),
    ("_override",      "JSONB",       "覆盖项(acl_override)"),
    ("_digest",        "TEXT",        "镜像 digest:**固定它,不用 latest 标签**"),
    ("_key",           "TEXT",        "键(object_key / event_key / idempotency_key)"),
    ("_owner",         "TEXT",        "持有者(lease_owner)"),
    ("_path",          "TEXT",        "路径(section_path)"),
    ("_tokens",        "INTEGER",     "token 数(context_budget_tokens)"),
    ("_limit",         "INTEGER",     "上限(final_chunk_limit)"),
    ("_dim",           "INTEGER",     "维度:换 Embedding 模型前要校验它兼容"),
    ("_k",             "INTEGER",     "候选数(candidate_k)"),
    ("_grants",        "JSONB",       "专项授权清单"),
    ("_prices",        "JSONB",       "价目表"),
    ("_providers",     "JSONB",       "允许的提供商白名单"),
    ("_errors",        "JSONB",       "字段级错误"),
    ("_version",       "TEXT",        "外部版本号(scorer_version / parser_version)"),
    ("_mode",          "TEXT",        "模式(execution_mode=mock/live)"),
    ("_status",        "TEXT",        "状态:取值由 contract/states.py 管,**不在数据库里写死枚举** —— "
                                     "加一个状态不该需要一次迁移"),
    ("_by",            "TEXT",        "操作者"),
    ("_reason",        "TEXT",        "原因:失败/取消/结束的理由,**空着等于没记**"),
    ("_diff",          "JSONB",       "脱敏后的前后差异"),
    ("_seq",           "BIGINT",      "序号:SSE 断线后按它续传"),
]

# 显式覆盖 —— 不符合后缀约定的字段,在这里点名。
# **这张表短,说明约定管得住大多数**;它变长就说明约定该改了。
显式类型 = {
    # ⚠️ `embedding` 和 `dim` 是 2026-09-27 为 `embeddings` 表加的。
    # `embedding` **不能靠后缀推**:它没有后缀,而且它是这套登记里
    # 第一个不是 SQL 标准类型的列 —— 维度写死在类型里(见 entities.py 那段注释)。
    # `dim` 同理:三个字母,套不上任何后缀约定。
    "embedding": "VECTOR(1536)", "dim": "INTEGER",
    "id": "TEXT", "name": "TEXT", "status": "TEXT", "role": "TEXT",
    "purpose": "TEXT", "adapter": "TEXT", "endpoint": "TEXT", "revision": "BIGINT",
    "messages": "JSONB", "params": "JSONB", "capabilities": "JSONB",
    "acl": "JSONB", "text": "TEXT", "ordinal": "INTEGER", "format": "TEXT",
    "content": "JSONB", "source": "TEXT", "split": "TEXT", "objective": "TEXT",
    "kind": "TEXT", "usable": "BOOLEAN", "step": "INTEGER", "metrics": "JSONB",
    "dimension": "TEXT", "value": "NUMERIC(20,6)", "rationale": "TEXT",
    "at": "TIMESTAMPTZ", "by": "TEXT", "environment": "TEXT", "approval": "JSONB",
    "stage": "TEXT", "error": "JSONB", "verdict": "TEXT", "note": "TEXT",
    "resource": "TEXT", "quantity": "NUMERIC(20,6)", "unit": "TEXT",
    "currency": "TEXT", "scope": "TEXT", "period": "TEXT", "type": "TEXT",
    "attempts": "INTEGER", "topic": "TEXT", "payload": "JSONB", "actor": "TEXT",
    "action": "TEXT", "result": "TEXT", "reason": "TEXT", "owner": "TEXT",
    "budget": "NUMERIC(20,6)", "timezone": "TEXT", "fusion": "JSONB",
    "rerank": "JSONB", "recall_modes": "JSONB", "human_review": "JSONB",
    "seq": "BIGINT", "supersedes_score_id": "TEXT",
    "param_update_method": "TEXT", "base_model": "TEXT", "pipeline_type": "TEXT",
    "source_info": "JSONB", "effective_at": "TIMESTAMPTZ",
    "candidate_ref": "JSONB", "baseline_ref": "JSONB", "target_ref": "JSONB",
    # ⚠️ 这两个**必须留在这儿**:`_policy` 后缀已经翻成 JSONB,
    # 它们靠「显式优先于后缀」才保住 TEXT。删掉这两行不会报错 ——
    # 只会让库里两列从 TEXT 变成 JSONB,而迁移跑得好好的。
    "data_egress_policy": "TEXT", "retention_policy": "TEXT",
    # ── Workflow / Agent 编排域的增量 ────────────────────────────────
    # 图定义本体:节点、连线、布局、草稿定义
    "nodes": "JSONB", "edges": "JSONB", "layout": "JSONB", "definition": "JSONB",
    "dependencies": "JSONB", "tags": "JSONB",
    # Agent 版本上的结构化部分
    "tools": "JSONB", "limits": "JSONB", "redaction": "JSONB",
    "instructions": "TEXT", "trigger_point": "TEXT",
    # ⚠️ `_ref` 后缀是 TEXT(指针:secret_ref / payload_ref / state_ref)。
    # 这两个是**带类型的引用**({kind, id, version_id}),和 candidate_ref /
    # baseline_ref / target_ref 一样钉成 JSONB。
    "definition_ref": "JSONB", "release_ref": "JSONB",
    # 运行与人工介入
    "principal": "TEXT",        # 执行身份:**不由用户输入字段指定**(§6.1)
    "decision": "TEXT", "outcome": "TEXT", "attempt": "INTEGER",
    # **声明式的能力开关**:不声明可轮询,就不能拿「调用两次」判失控(§10.3)
    "pollable": "BOOLEAN",
    # ⚠️ 下面这几个是**跑了一遍派生才发现认不出的** —— 约定没覆盖到,所以点名。
    # 这正是「不给兜底」的收益:它们本来会被默默建成 TEXT,而 amount 建成 TEXT
    # 的后果是钱能被写进字符串,而且排序按字典序。
    "key": "TEXT",              # prompt 的稳定标识(不是 _key 后缀那种「键」)
    "provider": "TEXT",         # 供应商名
    # **金额一律 NUMERIC,绝不用浮点** —— 舍入误差会累积成对不上的账。
    # 它和 amount_known 是一对:未知时 amount 为 NULL 且 amount_known=false,
    # **不许写 0**(规格开头的数字约定)。
    "amount": "NUMERIC(20,6)",
}

# 这些字段**不许有默认值也不许可空**:少了它们,那一行就失去了意义。
必填 = {"id", "created_at"}
# 项目范围内的表:organization_id / project_id 也是必填 —— 它们是身份的一部分
# (进了复合主键)。⚠️ 这一条要和 models.py 的主键规则**对得上**:
# 契约说「可空」而库里是 NOT NULL 的话,`alembic check` 会永久报漂移,
# 而一个永久报漂移的检查等于没有检查。
范围内必填 = {"organization_id", "project_id"}


class 认不出字段(Exception):
    pass


def 类型(字段):
    """返回 PostgreSQL 类型。**认不出就抛** —— 不返回 TEXT 兜底。"""
    if 字段 in 显式类型:
        return 显式类型[字段]
    for 后缀, t, _ in sorted(后缀约定, key=lambda x: -len(x[0])):
        if 字段.endswith(后缀):
            return t
    raise 认不出字段(
        f"字段 `{字段}` 既不命中后缀约定、也不在显式类型表里 —— "
        f"**不给它 TEXT 兜底**:一个错的类型和一个对的类型,"
        f"在建表成功那一刻长得一模一样。要么改名跟上约定,要么在 显式类型 里点名")


def 可空(字段, 范围内=False):
    """范围内=True 表示这张表在项目范围里(项目级 / 挂父级)。"""
    if 字段 in 必填: return False
    if 范围内 and 字段 in 范围内必填: return False
    return True
