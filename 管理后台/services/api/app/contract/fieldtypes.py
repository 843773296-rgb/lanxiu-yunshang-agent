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
    # ⚠️ 2026-10-03 加。加后缀之前**先查过库里哪些列会被它命中** ——
    # 答案是**一个都没有**(除了同时加的 `chunks.section_titles`),所以不会误伤。
    # 这条规矩是因为 `_action` 那次:它差点把 `redaction`(JSONB)改成 TEXT,
    # 靠整名显式登记保住。
    ("_titles",        "JSONB",       "一串标题(section_titles)—— "
                                      "**路径的无歧义表示是列表**,"
                                      "不是用分隔符拼起来的字符串:"
                                      "全库 29 个标题名字里带 ` / `,"
                                      "而 `section_path` 正是用 ` / ` 拼的"),
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
    # ⚠️ 2026-10-03 加,为 §8.2「模型说明」页签(tool_versions 三个新字段)。
    # 加之前查过库里哪些列会被这两个后缀命中:**一个都没有**
    # (`_aliases` 0 列、`_examples` 0 列,整名 model_aliases / task_examples 也不存在)。
    # 这条「先查命中再加后缀」的规矩来自 `_action` 那次:
    # 它差点把 `redaction`(JSONB)改成 TEXT。**凭字段名猜类型**在这个仓库犯过四次。
    ("_aliases",       "JSONB",       "一串别名(model_aliases):**业务话到系统话的映射**。"
                                     "10-03 量到的病根 —— 用户问「还能发几件」,"
                                     "而工具说明写的是「查现货」,"
                                     "**5 道题的需要工具和问法一个共同片段都没有**"),
    ("_examples",      "JSONB",       "一串例子(task_examples),每条带来路。"
                                     "⚠️ **「现编」必须标出来** —— 10-03 栽过一次:"
                                     "拿反推出来的别名得到 21/21,那是先看答案再出题"),
    ("_report",        "JSONB",       "报告(校验报告)"),
    # ── 缓存那块的后缀(2026-10-04 加)─────────────────────────────────
    #
    # ⚠️ **加之前逐个量过**(这个仓库为「凭名字猜类型」栽过四次):
    # 拿契约里 306 个字段 + 库里 311 个列名对一遍,
    # 下面九个后缀里**只有 `_mode` 命中了已有列**
    # (`execution_mode` / `load_mode` / `selection_mode`),
    # 而那三个在**库里和契约里都是 TEXT** —— 所以登记它是确认现状,
    # 不会改掉任何一列。其余八个一个都没命中。
    #
    # ⚠️ 能用已有后缀的就没新加:
    # `usage_map`(用 `_map`)、`validation_report`(用 `_report`)、
    # `storage_ref`(用 `_ref` ——「**只存引用,不存内容**」正是它的语义)、
    # `warm_status`(用 `_status`)。少加四个后缀。
    ("_epoch",         "BIGINT",      "代次(authorization_epoch / data_epoch)—— "
                                      "**权威失效用的单调计数**,"
                                      "不是时间戳:时间戳在时钟回拨时会倒退"),
    ("_generation",    "BIGINT",      "命名空间代次(namespace_generation)。"
                                      "⚠️ **不复用 `_revision`** —— 那个是乐观锁用的,"
                                      "两件事混在一个数里,清空范围会被当成并发冲突"),
    ("_kind",          "TEXT",        "种类枚举(api_kind / mode_kind)"),
    ("_mode",          "TEXT",        "模式枚举(cache_mode)。"
                                      "**量过:已有的 execution_mode / load_mode / "
                                      "selection_mode 本来就是 TEXT**"),
    ("_layer",         "TEXT",        "哪一层缓存(提示词 / 答案)—— "
                                      "**两层的命中状态不是一套枚举**"
                                      "(答案命中时根本没有生成调用,"
                                      "那不叫提示词缓存未命中)"),
    ("_options",       "JSONB",       "可选项清单(ttl_options)—— "
                                      "**从能力快照派生**,不给供应商不支持的任意输入框"),
    ("_operations",    "JSONB",       "供应商 API 支持哪些操作"
                                      "(可列举 / 可删除 / 可关闭)。"
                                      "⚠️ **用 JSONB 而不是三个布尔**:每一项有三态 —— "
                                      "支持 / 不支持 / **没核查过**,"
                                      "而一个 NULL 布尔在大多数代码里读起来就是 false,"
                                      "于是「没核查过」会变成「不支持」"),
    ("_config",        "JSONB",       "策略配置(policy_config)"),
    ("_completeness",  "JSONB",       "用量完整性(规格 §17.2)—— "
                                      "**说清这次缺了哪几个字段**,"
                                      "而不是一个「完整/不完整」的布尔:"
                                      "缺哪一档决定了哪些指标还能算"),
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
    # ── 下面三条是 2026-10-02 为「工具筛选与按需加载」那份规格加的 ──────
    ("_action",        "TEXT",        "枚举动作(empty_result_action="
                                      "rediscover_then_stop):**是枚举不是对象** —— "
                                      "写成 JSONB 的话「没结果怎么办」会变成一段"
                                      "没人能当枚举查的配置"),
    ("_enabled",       "BOOLEAN",     "开关(independent_router_enabled)。"
                                      "⚠️ 不要起名 `xxx_flag` 然后存字符串:"
                                      "`\"false\"` 在 Python 里是真的"),
    ("_query",         "TEXT",        "检索查询文本(capability_query / "
                                      "normalized_query)。规范化那一份单独存 —— "
                                      "A-6 的「无进展」判定比的是规范化后的,"
                                      "只留原文的话每次大小写不同都算新查询"),
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
    #
    # ⚠️⚠️ **512,不是 1536。** 2026-09-27 当天改过一次:
    # 首版按 OpenAI 的 1536 建的(那时只有 mock 向量),而用户拍了本地模型
    # BGE-small-zh-v1.5,它的 hidden_size 是 **512**(读 config.json,不是猜的)。
    #
    # 这次改动正是「维度写死在列类型上」那个决定的**代价兑现** ——
    # 而它是个**会报错**的代价:插错维度当场被 PostgreSQL 拒
    # (实测 `expected N dimensions, not M`)。
    # 对面那个方案(无维度的 vector 列)允许 3 维和 4 维躺在同一张表里,
    # 混维度的索引算出来的距离没有意义,而且**一声不响**。
    # **下次换模型还要这么来一次,那是有意的。**
    "embedding": "VECTOR(512)", "dim": "INTEGER",
    # ⚠️ `gate_evidence` 是 2026-09-28 为 `deployments` 加的。
    # 套不上后缀约定(`_evidence` 没登记),而这套登记**不给 TEXT 兜底** ——
    # 那条规矩今天第二次当场拦住我,两次都是对的。
    #
    # 为什么是 JSONB 而不是 TEXT:它记的是「当时凭什么放行这次部署」
    # (产物是不是 mock 训练的、校验于何时、内容哈希、放行人)——
    # **事后要能按字段查**,比如「有没有哪次部署放行时 `是mock训练的` 是 null」。
    # 存成一段文字的话,那个问题只能靠人一条条读,而部署是不可逆的对外动作。
    "gate_evidence": "JSONB",
    # ⚠️ `frozen_samples` 是 2026-09-29 为 `dataset_versions` 加的,
    # 而**契约里一直没声明它** —— 库里有、模型里没有,
    # 于是 `alembic check` 从那天起一直红(而我从来没跑过它:
    # 它装在 `make test` 里,我跑的是 contract / test-e2e / progress)。
    # 10-01 新加的 CI job(从零建库)第一次跑就把它抓出来了。
    #
    # 为什么是 JSONB:它是「**冻结固化内容,不是存个指针**」那条约束的落点 ——
    # 冻结时把那一版用到的样本内容整份存下来。
    # 存成指针的话,后续改样本会**悄悄改掉历史上那一版评测用的题**,
    # 于是「同一批题、换个配置、分数变没变」这个问题问不成 ——
    # 而那个变化**不报错**,只会让两次的分数不可比而看起来可比。
    #
    # ⚠️ 这条规矩(不给 TEXT 兜底)今天第三次当场拦住我,三次都是对的。
    "frozen_samples": "JSONB",
    # ⚠️ `provider` / `caller` / `world_date` 是 2026-09-28 为 `usage_ledger` 加的。
    # 三个都套不上后缀约定,而这套登记**不给 TEXT 兜底** ——
    # 那条规矩今天当场拦住了我一次,是对的。
    #
    # `world_date` 用 **DATE 不是 TIMESTAMP**:它是演示世界里的**日历日**
    # (世界停在某一天),不是某个时刻。存成 timestamp 会让它带上一个
    # 无意义的 00:00:00,而那个零点看起来像真的时刻 ——
    # **一个假装自己有精度的值,比一个粗一点的值危险。**
    "provider": "TEXT", "caller": "TEXT", "world_date": "DATE",
    "id": "TEXT", "name": "TEXT", "status": "TEXT", "role": "TEXT",
    "purpose": "TEXT", "adapter": "TEXT", "endpoint": "TEXT", "revision": "BIGINT",
    "messages": "JSONB", "params": "JSONB", "capabilities": "JSONB",
    "acl": "JSONB", "text": "TEXT", "ordinal": "INTEGER", "format": "TEXT",
    # ⚠️ `rating` 点名登记成 INTEGER(2026-10-08,检索试跑的 5 档评价)。
    # **不叫 `rating_count`** —— 那样能命中 `_count` 后缀不用登记,
    # 而它会是一句谎话:5 档里的「4」是**档位**,不是「评了 4 次」。
    # > 一个名字骗人的列,和一个类型错的列,后果是同一类:
    # > 下一个人照着名字去读它,而**读出来的数看起来完全正常**。
    "rating": "INTEGER",
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
    # ⚠️ **第三个**要靠「显式优先于后缀」保住 TEXT 的:`redaction_policy`。
    # 它 2026-09-29 建进库时是 TEXT,而契约里一直没声明它 ——
    # 补上声明之后后缀约定把它判成了 JSONB,于是 `alembic check` 说类型不一致。
    #
    # 按**代码真实存的东西**定:它存的是一句话
    # (`无需脱敏:<理由>` / 或者一个脱敏器名字),不是结构化对象 ——
    # 导出那道闸判的就是这句话的内容。
    # 判成 JSONB 的后果:那句话要被当成 JSON 解析,而
    # `无需脱敏:演示数据` 不是合法 JSON —— **而这件事只在写入那一刻才炸**。
    "data_egress_policy": "TEXT", "retention_policy": "TEXT",
    "redaction_policy": "TEXT",
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
    # ⚠️ `namespace` 是 2026-10-04 为缓存评测扩展加的,**走整名点名**:
    # 它没有后缀可言(就一个词),而 `_namespace` 作为后缀没有第二个用例 ——
    # 加一条只有一个用户的后缀,等于把点名写成了约定。
    "namespace": "TEXT",
    # ⚠️ `when_to_use` 是 2026-10-03 为 §8.2「模型说明」页签加的,
    # **故意走点名,而不是加一条 `_use` 后缀**。
    #
    # 这个文件开头写了后缀约定的理由:「后缀是这套契约里**已经在用**的命名习惯」。
    # 而 `_use` 不是习惯,它是个**动词** —— 登记它等于宣布
    # 「以后任何以 use 结尾的列都是 JSONB」,于是将来一个 `last_use` / `token_use`
    # 会被默默建成 JSONB,而那种错在建表成功那一刻看不出来
    # (正是这个文件要防的那件事)。`when_to_use` 是一个**整名**,就该按整名登记。
    #
    # 为什么是 JSONB:它存 `{"适用": [...], "不适用": [...]}` —— **两边都要有**。
    # 只写「适用」的话,「不适用」会静默变成「没说过」,
    # 而那正是 10-03 那 5 道零重叠题的病根:缺的不是关键词,
    # 是「**什么时候该用它、什么时候不该**」。
    # 「两边都要有」由接口层的闸来拒(规格第 6 步),类型层只保证存得下。
    "when_to_use": "JSONB",
}

# 这些字段**不许有默认值也不许可空**:少了它们,那一行就失去了意义。
必填 = {"id", "created_at"}

# ── 按表点名的必填(2026-10-01 加)─────────────────────────────────────
#
# ⚠️ **为什么要按表点名,而不是加进上面那个全局 `必填`。**
# `status` / `environment` 这些名字在别的表上确实可以为空
# (比如一条还没开始的东西还没有状态)—— 加进全局会把那些表一起钉死。
#
# ⚠️ **这四列是 09-29 我手写迁移时建成 NOT NULL 的,而契约没登记** ——
# 于是 `alembic check` 一直红,而 10-01 我拿 autogenerate 去对齐时,
# 它生成的迁移**要把这四列改成可空**(因为模型说可空)。
#
# 照着跑一遍的后果很具体,而且正是这个仓库反复栽的那一族:
#   · 一条 `status` 为空的部署 —— **「没状态」和「正在部署」在列表上长得一样**
#   · 一条 `environment` 为空的部署 —— 「发到哪了」答不出来
#   · 一条 `application_id` 为空的候选 —— 它是**谁的**候选?
# 而这些行**插得进去**,只是每条读路径都捞不到或者显示成空白。
# (同一族:`memberships.status` 不给 'active' → 插进去了而每条读路径都捞不到。)
#
# > **库里是 NOT NULL 而契约说可空,这不是「库更严格」——
# > 这是契约在说一件假话,而 autogenerate 会照着那句假话改库。**
按表必填 = {
    "deployments": {"model_artifact_id", "environment", "status"},
    "application_drafts": {"application_id"},
    # 检索试跑记录(2026-10-08):这五列**一列都不能空**,否则那一行没有用 ——
    #   · `source` 空 → 分不出是实验室跑的还是 chat 跑的,而这张表存在的理由
    #     就是「哪些是 chat 的」(chat 现在还没接上这条链)
    #   · `user_query` 空 → 不知道问的是什么
    #   · `chain_snapshot` 空 → 「那次它找到了哪几段」没了,这是全部价值
    #   · 两个 id 空 → 答不出「在哪个库的哪一版索引上跑的」
    # ⚠️ 而它们**空着也插得进去** —— 表现是列表里多一行什么都没有的记录。
    "retrieval_runs": {"source", "user_query", "chain_snapshot",
                       "index_build_id", "knowledge_base_id"},
}
# 项目范围内的表:organization_id / project_id 也是必填 —— 它们是身份的一部分
# (进了复合主键)。⚠️ 这一条要和 models.py 的主键规则**对得上**:
# 契约说「可空」而库里是 NOT NULL 的话,`alembic check` 会永久报漂移,
# 而一个永久报漂移的检查等于没有检查。
范围内必填 = {"organization_id", "project_id"}


class 认不出字段(Exception):
    pass


def 类型(字段):
    """返回 PostgreSQL 类型。**认不出就抛** —— 不返回 TEXT 兜底。

    ⚠️ **整名优先于后缀,而这一条 2026-10-02 当场救了一次。**
    那天为新规格加 `_action` → TEXT 后缀,而 `tool_versions.redaction`
    **正好以 `action` 结尾、而且是 JSONB** —— 它靠整名显式登记保住了
    (`audit_events.action` 同理,它本来就是 TEXT)。
    如果 `redaction` 当初没被点名,这个改动会把它在新库上建成 TEXT,
    > **而建表成功那一刻,一个错的类型和一个对的类型长得一模一样。**
    加新后缀之前先查一遍库里有哪些列会被它命中 —— 那次查出了这两个。
    """
    if 字段 in 显式类型:
        return 显式类型[字段]
    for 后缀, t, _ in sorted(后缀约定, key=lambda x: -len(x[0])):
        if 字段.endswith(后缀):
            return t
    raise 认不出字段(
        f"字段 `{字段}` 既不命中后缀约定、也不在显式类型表里 —— "
        f"**不给它 TEXT 兜底**:一个错的类型和一个对的类型,"
        f"在建表成功那一刻长得一模一样。要么改名跟上约定,要么在 显式类型 里点名")


def 可空(字段, 范围内=False, 表=None):
    """范围内=True 表示这张表在项目范围里(项目级 / 挂父级)。

    `表` 给了的话,还查 `按表必填` —— 有些列只在某张表上是必填的
    (`status` 在部署上必填,在别的表上可以为空)。
    ⚠️ **`表` 不给就退化成老行为**,所以老调用点不受影响;
    而漏传 `表` 的表现是**那几列又变回可空** —— 见下面 `models.py` 里
    那句「`可空` 要带上表名」的注释。
    """
    if 字段 in 必填: return False
    if 范围内 and 字段 in 范围内必填: return False
    if 表 and 字段 in 按表必填.get(表, ()): return False
    return True
