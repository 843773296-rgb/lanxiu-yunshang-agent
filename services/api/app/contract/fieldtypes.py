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
    ("_policy",        "TEXT",        "策略名"),
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
    "data_egress_policy": "TEXT", "retention_policy": "TEXT",
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
