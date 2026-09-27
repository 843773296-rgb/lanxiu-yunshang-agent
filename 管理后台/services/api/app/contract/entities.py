#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实体与约束登记表 —— **数据模型的唯一来源**。

## 为什么是一份登记表,而不是直接写 ORM 模型

规格 §18 写着「关系和约束**不得省略**」。如果把它抄成 ORM 模型、再抄一份进文档、
再抄一份进 OpenAPI,就有了三份会各自漂的说法 —— 而**漂了不报错**:
三份里哪一份错了,读的人都看不出来,直到某一天约束在生产上不成立。

所以这里只登记一次:实体、关键字段、约束、项目范围。
ORM 模型和文档都从这份表派生;`tools/spec_coverage.py` 还会去**解析规格原文的表格**,
比对有没有漏掉实体 —— 规格改了,检查当场红。

## 三条登记纪律

① **`项目范围` 必须显式写出来。** 规格 §19.1:「后端重新检查项目权限与对象范围」,
   §18:「仅靠前端传 project_id 不够」。所以每个实体都要说清它**归哪一级**
   (组织级 / 项目级 / 挂在别的对象上),不许留空 —— 留空的那个就是将来被越权读到的那个。

② **不可变的东西要标出来。** 版本、快照、审计事件一旦写下就不许改。
   规格 §18 反复强调「正式版本不可变」「原始结果不被复核覆盖」「审计追加写入」——
   这不是风格,是**可追溯性的地基**:能改的历史不是历史。

③ **`未知 ≠ 零`。** 费用、指标、total 这类字段必须能表达「不知道」,
   而且**不许用 0 代替**(规格开头的数字约定 + §21 结尾「不得用假数据补齐未知项」)。
   一个把「没测」显示成 0 的字段,会让人以为测过了。
"""

# 范围:这个实体归哪一级。**不许留空。**
组织级 = "organization"        # 只挂组织(如 organizations 自己、成员)
项目级 = "project"             # 必须带 project_id,且外键要含项目范围
子对象 = "parent"              # 挂在别的项目级对象上,范围随父级
全局级 = "global"              # 不属于任何组织(如价格表版本)

# 可变性
可改 = "mutable"               # 普通对象,可编辑、可归档
不可变 = "immutable"           # 写下就不许改(版本、快照)
只追加 = "append_only"         # 只能往后加,不能改也不能删(审计、事件)


# 不可变的东西分两种,而**它们对哈希的需求相反**:
#   · 内容寻址(版本 / 快照 / 配置):身份就是它的内容 → **必须有内容哈希**。
#     没有哈希就认不出「这一版和那一版是不是同一份」,而发布清单和评测对比全靠这个。
#   · 一次写入的记录(评分、连接项、检查点索引):身份是「谁在什么时候写的」,
#     内容哈希对它没有意义 —— 强加一个,只会变成一个没人看的列。
#
# ⚠️ 这个标记是**显式登记**,不是检查里的豁免名单。
# 第一版我把豁免写在 `tools/spec_coverage.py` 的一个 tuple 里 ——
# **藏在检查里的豁免是看不见的知识**:读实体的人不知道它被放过了,
# 而放过的理由(以及理由还成不成立)没有任何地方记着。
# ⚠️ **默认就该是项目级。** 声明成组织级或全局级的,必须写 `范围理由` ——
# 因为「这张表不按项目隔离」是这套系统里最容易造成越权读取的一个决定,
# 而它在代码里只是一个单词的差别。
#
# 这条规矩的判据**不能从范围本身算出来**。第一版我写的是
# 「项目级实体都带 project_id」—— 而 project_id 正是依据「范围==项目级」加上去的,
# 于是把一张表改成组织级之后,它直接从被检查的集合里消失,**检查永远不会红**。
# 咬合测试当场抓到。这就是 **同源谬误**:期望值用被测的东西算出来,
# 实现错了期望值跟着一起错。
def E(名, 中文, 范围, 可变性, 关键字段, 约束, 依赖=(), 内容寻址=None, 范围理由=None):
    if 内容寻址 is None:
        内容寻址 = (可变性 == 不可变)
    if 范围 in (组织级, 全局级) and not (范围理由 or "").strip():
        raise ValueError(
            f"{名} 声明成了 {范围},但没写 `范围理由` —— "
            f"**不按项目隔离是个要写明的决定**,不是默认值")
    # ⚠️ **范围理由必须进返回值。** 第一版守卫写了、但返回的 dict 里没这个键 ——
    # 于是检查读到的永远是 None,而守卫看起来「已经在拦了」。
    # 这是个「写好了但没接上」的防护:它和没有这个防护,在代码上长得一模一样。
    return dict(名=名, 中文=中文, 范围=范围, 可变性=可变性,
                关键字段=list(关键字段), 约束=list(约束), 依赖=list(依赖),
                内容寻址=bool(内容寻址), 范围理由=范围理由)


# ── 实体登记表(对齐规格 §18 的每一行)─────────────────────────────
实体表 = [
    # ① 组织 / 项目 / 成员
    E("organizations", "组织", 组织级, 可改,
      ["name", "status"],
      ["项目归属明确,服务端从认证上下文校验"],
      范围理由="组织自己就是最外层范围,没有更外的东西可以挂"),
    E("projects", "项目", 组织级, 可改,
      ["organization_id", "name", "owner", "status", "retention_policy",
       "timezone", "budget", "allowed_providers", "data_egress_policy"],
      ["项目必须属于一个组织",
       "改动涉及实际外发范围时要展示影响对象(§15.4)"],
      依赖=["organizations"], 范围理由="项目挂在组织下;它自己就是项目范围的定义者"),
    E("memberships", "成员与角色", 组织级, 可改,
      ["organization_id", "project_id", "user_id", "role",
       "special_grants", "status", "last_login_at"],
      ["**不能通过邀请获得自己没有的权限**(§15.3)—— 授予集合必须是授予人权限的子集",
       "专项权限(敏感输入 / 独立测试答案 / 审计 / 密钥预算)单独登记,不随角色默认给"],
      依赖=["projects"], 范围理由="成员是组织级对象:一个人可以在同组织的多个项目里有角色,project_id 可空表示组织级成员。**授权判定仍然每次带项目上下文**"),

    # ② 模型连接
    E("model_connections", "模型连接", 项目级, 可改,
      ["purpose", "adapter", "display_name", "status"],
      ["用途(生成 / Embedding / 重排 / 微调推理)要分开,不共用一条连接"]),
    E("connection_versions", "连接配置版本", 子对象, 不可变,
      ["connection_id", "endpoint", "secret_ref", "capabilities", "config_hash",
       "revision"],
      ["**密钥只存引用**(secret_ref),绝不存明文也不存密文本体",
       "配置版本不可原地改 —— 改就是新版本",
       "capabilities 要记「这个端点到底支持哪些参数」,不支持的参数要能返回明确错误(§17.4-5)",
       "**config_hash 不含 secret_ref 指向的内容** —— 换了密钥不算换了配置,"
       "而把密钥混进哈希会让哈希本身变成一条侧信道"],
      依赖=["model_connections"]),

    # ③ Prompt
    E("prompt_drafts", "Prompt 草稿", 项目级, 可改,
      ["key", "messages", "variable_schema", "output_schema", "params", "revision"],
      ["草稿并发控制:PATCH 要 If-Match / expected_revision,冲突返 409(§19.1)",
       "**保存草稿不会修改生产**(实施必须遵守第 1 条)"]),
    E("prompt_versions", "Prompt 正式版本", 项目级, 不可变,
      ["key", "version_no", "messages", "variable_schema", "output_schema",
       "params", "content_hash", "created_by"],
      ["正式版本不可变;content_hash 用来认出「同一份内容」",
       "生成参数属于 Prompt 版本的一部分 —— 换了参数就是换了版本"],
      依赖=["prompt_drafts"]),

    # ④ 知识与 RAG
    E("knowledge_bases", "知识库", 项目级, 可改,
      ["name", "acl", "status", "embedding_purpose_connection_id"],
      ["知识库级 ACL 是上限,文档可以再收紧但不能放宽(§18「文档父级权限可收紧」)"]),
    E("documents", "文档", 子对象, 可改,
      ["knowledge_base_id", "source_info", "acl_override", "disabled_at"],
      ["**内容版本与权限状态分开** —— 停用一篇文档不该改它的历史版本"],
      依赖=["knowledge_bases"]),
    E("document_versions", "文档版本", 子对象, 不可变,
      ["document_id", "object_key", "content_hash", "effective_at", "revision"],
      ["原文放对象存储,库里只存键和哈希",
       "content_hash 决定「这份资料变没变」,不靠文件名也不靠时间"],
      依赖=["documents"]),
    E("chunks", "片段", 子对象, 不可变,
      ["document_version_id", "section_path", "ordinal", "text", "text_hash",
       "token_count"],
      ["片段绑的是**文档版本**,不是文档 —— 否则文档一改,历史证据链就指向了新内容"],
      依赖=["document_versions"]),
    E("index_builds", "索引构建", 项目级, 可改,
      ["knowledge_base_id", "retrieval_config_version_id", "embedding_model_id",
       "embedding_dim", "status", "job_id"],
      ["**向量维度兼容**要在构建前校验:换了 Embedding 模型,旧向量不能混用",
       "构建是后台任务,状态要能看见、能取消、能恢复"],
      依赖=["knowledge_bases", "retrieval_config_versions"]),
    # ⚠️ **`embeddings` 规格 §18 没点名,是查出来补的。**
    # `index_members.embedding_id` 本来指向一张**不存在的表** ——
    # 它不是数据库外键,所以那一列可以填任何字符串,而没有任何一层会发现。
    # 后果:「登记了向量」可以是纯粹的谎话,索引构建照样报成功,
    # 而那一段内容在检索里永远不命中。
    #
    # 应用层判据(`knowledge/index_plan.py` 的 `已经做完的()`)只能查「非空」;
    # **能用约束表达的不要用判据表达** —— 判据只在有人调用它时生效,
    # 外键在每一次 INSERT 上生效,包括我没想到的那些写入路径。
    #
    # ## 身份是 (文本, 模型),不是 (构建, 片段)
    #
    # 同一段文本用同一个模型算出来的向量,**换了检索配置不需要重算**。
    # 所以唯一约束落在 (project_id, text_hash, model_id):
    # 检索配置改了要新建构建(§19.3),但那次新建可以把全部向量复用 ——
    # 一次 Embedding 都不用重跑。绑构建就做不到这件事。
    #
    # ## 维度固定在列类型上(vector(1536)),不用无维度的 vector
    #
    # 量过:无维度的 `vector` 列**允许 3 维和 4 维存在同一张表**(试过,一声不响),
    # 而且建不了 hnsw 索引(`column does not have dimensions`)。
    # 规格 §18 要求「换了 Embedding 模型,旧向量不能混用」——
    # 固定维度让**数据库直接执行**这条,插错维度当场报错。
    # 代价是换模型要一次迁移;那是个**会报错**的代价,
    # 对面那个是「混维度静默存进去,检索时距离算出来没有意义」。
    E("embeddings", "向量", 子对象, 不可变,
      ["text_hash", "model_id", "dim", "embedding"],
      ["身份是 (文本, 模型) —— **换检索配置不用重算向量**,新构建可以全部复用",
       "维度固定在列类型上:插错维度当场报错,而不是混进去等检索时算出没意义的距离",
       "**首版没有向量索引**(hnsw):几十个片段顺序扫够用。"
       "上真量之前必须补 —— 这是欠账,不是设计",
       "**和 chunk 没有外键**:关系是 text_hash 相等,而那不是一对一 ——"
       "同一段文本会在多个片段里出现(重复的小标题、表格分隔行都踩过)。"
       "指向某一个 chunk 就要在多个里挑一个,而挑哪个是随机的"],
      依赖=()),
    # 内容寻址=False:连接行:身份是(构建, 片段),没有独立内容 —— 内容哈希对它没有意义。
    E("index_members", "索引清单项", 子对象, 不可变,
      ["index_build_id", "chunk_id", "embedding_id"],
      ["**索引清单只引用确切片段版本**(§18)—— 这是证据链能追回原文的前提",
       "`embedding_id` 现在是**真外键**(指向 embeddings)——"
       "在这之前它指向一张不存在的表,那一列可以填任何字符串"],
      依赖=["index_builds", "chunks", "embeddings"], 内容寻址=False),
    E("retrieval_config_versions", "检索配置版本", 项目级, 不可变,
      ["recall_modes", "candidate_k", "fusion", "rerank", "context_budget_tokens",
       "final_chunk_limit", "content_hash", "revision"],
      ["**校验最终片段数不超过可用候选限制**(§18)—— 配了 20 片但只召回 10 候选,"
       "那 20 是句空话",
       "重排可关闭(§21「先实现关键词/向量与可关闭重排」)",
       "**要有内容哈希**:它被发布清单引用,而「这次检索配置和上次是不是同一份」"
       "不能靠版本号猜 —— 版本号会因为无关字段的改动而前进"]),

    # ⑤ 数据集
    E("datasets", "数据集", 项目级, 可改,
      ["name", "format", "purpose"],
      ["用途(训练 / 验证 / 独立测试)和格式分开登记"]),
    E("dataset_versions", "数据集冻结版本", 子对象, 不可变,
      ["dataset_id", "split_map", "content_hash", "sample_count", "revision"],
      ["**冻结版本不能被样本后续编辑改变**(§18)—— 冻结时要固化内容,不能只存一个指针",
       "分集(训练/验证/独立测试)在冻结时定,之后不许重分"],
      依赖=["datasets"]),
    E("samples", "样本", 子对象, 可改,
      ["dataset_id", "content", "source", "review_status", "split",
       "group_id", "content_hash"],
      ["**group_id 用来防泄漏**:同一组的样本不许跨分集(改写、同源、同客户都算一组)",
       "content_hash 用来查重"],
      依赖=["datasets"]),

    # ⑥ 微调
    E("training_jobs", "训练任务", 项目级, 可改,
      ["config_snapshot", "dataset_version_id", "base_model", "objective",
       "param_update_method", "external_id", "image_digest", "status",
       "idempotency_key", "cancel_requested"],
      ["**目标(SFT/DPO)和参数更新方式(LoRA/全量)分别选**(§2 重要区分),"
       "不许做成三选一",
       "**任务唯一幂等键** —— 供应商超时后先按外部 ID 查,避免重复训练(§11.5)",
       "镜像固定 digest,不用 latest(§17.4 结尾)",
       "config_snapshot 是快照:任务建好之后改配置不影响已提交的任务"],
      依赖=["dataset_versions"]),
    E("checkpoints", "检查点", 子对象, 不可变,
      ["training_job_id", "step", "metrics", "object_key", "file_hash"],
      ["指标要带 step,不能只存最后一个数",
       "file_hash 是**文件内容**的哈希:检查点要能验「下载到的和训练出的是同一个」"],
      依赖=["training_jobs"]),
    E("model_artifacts", "模型产物", 项目级, 不可变,
      ["training_job_id", "kind", "base_model", "tokenizer_ref", "file_manifest",
       "content_hash", "verified_at", "usable"],
      ["**产物校验后才能登记可用**(§18)—— 训练完成只代表得到产物(实施必须遵守第 4 条)",
       "基座和 Tokenizer 要记下来:适配器离开它们就没有意义"],
      依赖=["training_jobs"]),

    # ⑦ 评测
    E("evaluations", "评测实验", 项目级, 可改,
      ["candidate_ref", "baseline_ref", "dataset_version_id", "scorer_version",
       "status", "job_id"],
      ["**候选与基线都要记**:没有基线的分数不能当结论",
       "数据版本和评分版本都要记 —— 换了判据的两轮不可比"]),
    # 内容寻址=False:一次写入的记录:身份是(实验, 样本) —— 内容哈希对它没有意义。
    E("evaluation_items", "评测逐题结果", 子对象, 不可变,
      ["evaluation_id", "sample_id", "raw_output", "trace_id", "finished_at"],
      ["**原始结果不被复核覆盖**(§18)—— 所以这张表里**没有分数**:"
       "分数在 scores 里,人工改判是**新增一条**,不是改这一行",
       "raw_output 要能追回 trace:「模型实际收到什么」是这个后台的立项痛点之一"],
      # 内容寻址=False:一次写入的记录,身份是(实验, 样本) —— 同一条题重跑就是新的一行,
      # 不是「同一份内容」。内容哈希对它没有意义。
      依赖=["evaluations"], 内容寻址=False),
    # ⚠️ **scores 必须是独立一张表**(规格 §18 单列了它),第一版我把它合进了
    # evaluation_items —— 检查当场抓出来。合进去表达不了两件事:
    #   ① 一条题会有**好几个评分**(确定性规则 / 模型评分 / 人工复核),各有来源和版本;
    #   ② 人工复核要是改同一行,**原始结果就被覆盖了** —— 而规格明确禁止。
    # 「一条题只有一个分数」这个隐含假设,是把复核做成覆盖的根源。
    # 内容寻址=False:一次写入的记录:身份是「谁在什么时候用哪一版判据打的」 —— 内容哈希对它没有意义。
    E("scores", "评分", 子对象, 不可变,
      ["evaluation_item_id", "dimension", "value", "value_known", "source",
       "scorer_version", "rationale", "by", "at", "supersedes_score_id"],
      ["**评分有来源与版本**(§18):source ∈ {确定性规则, 模型评分, 人工};"
       "模型评分要记是哪个模型哪一版打的",
       "人工改判 = **新增一条并指向被它取代的那条**(supersedes_score_id),"
       "不是改旧那条 —— 这样「原始结果」永远还在",
       "**value_known 区分「没打分」和「打了 0 分」** —— 用 0 表示没测过,"
       "会让人以为测过了(规格开头的数字约定)"],
      依赖=["evaluation_items"], 内容寻址=False),

    # ⑧ 应用与发布
    E("applications", "应用", 项目级, 可改,
      ["name", "pipeline_type"],
      ["首版只有「Prompt 生成」和「RAG 问答」两种流水线(§3 结尾)"]),
    E("release_manifests", "发布清单", 项目级, 不可变,
      ["application_id", "prompt_version_id", "connection_version_id",
       "index_build_id", "retrieval_config_version_id", "model_artifact_id",
       "evaluation_id", "approval", "content_hash", "revision"],
      ["**完整依赖清单,全部是确切版本**(实施必须遵守第 1 条)——"
       "不许出现「用最新的那个」",
       "**不把任意模块的「最新版本」静默用于生产**(§2)"],
      依赖=["applications", "prompt_versions", "release_manifests"]),
    E("environment_bindings", "环境指针", 项目级, 可改,
      ["application_id", "environment", "release_manifest_id", "revision"],
      ["**指针变更原子化**(§18);PATCH 要 expected_revision",
       "候选与生产分离 —— 生产指针只认审核过的清单(§17.4-9)"],
      依赖=["release_manifests"]),

    # ⑨ 运行记录
    E("traces", "运行记录", 项目级, 只追加,
      ["session_id", "request_id", "application_id", "release_manifest_id",
       "environment", "started_at", "ended_at", "end_reason"],
      ["记的是**实际收到什么**:清单版本要落在 trace 上,不能事后去查「当时是哪一版」",
       "**不承诺展示模型完整的内部思考过程**(§2)",
       "⚠️ **application_id / release_manifest_id 必须有复合外键** —— "
       "攻击测试里「拿 A 项目的应用 ID 在 B 项目下建 trace」原来是能写进去的,"
       "因为这个实体一开始没登记依赖,于是一个外键都没建"],
      依赖=["applications", "release_manifests"]),
    E("spans", "阶段", 子对象, 只追加,
      ["trace_id", "parent_span_id", "stage", "input_ref", "output_ref",
       "started_at", "ended_at", "error"],
      ["**敏感原文独立存储 + 授权查询**(§18)—— span 上只放引用",
       "阶段要能拼成一棵树:父子关系不能靠时间顺序猜"],
      依赖=["traces"]),
    E("feedback", "反馈样本", 子对象, 可改,
      ["trace_id", "verdict", "note", "promoted_sample_id"],
      ["打了「答错了」要能回流成评测样本 —— 记下回流到哪条"],
      依赖=["traces"]),

    # ⑩ 用量与费用
    E("usage_ledger", "用量账目", 项目级, 只追加,
      ["event_key", "trace_id", "resource", "quantity", "unit", "currency",
       "pricing_version_id", "amount", "amount_known", "source"],
      ["**唯一用量事件防重复计费**(§18):event_key 唯一约束",
       "**unknown 区分 zero** —— amount_known=False 时前端显示「未知」,**不许显示 0**",
       "外部账单有延迟,费用上限**不得宣称绝对零超支**(§11.5)"]),
    E("pricing_versions", "价格版本", 全局级, 不可变,
      ["provider", "model_id", "unit_prices", "currency", "effective_at",
       "content_hash"],
      ["计费要用**当时那一版价格的快照**,不用现价回算 ——"
       "否则改一次价目表,历史成本全变了"],
      范围理由="价格表是**供应商的事实**,不属于任何项目 —— 各项目引用同一份快照,否则同一天同一个模型会算出不同的钱"),
    E("budgets", "预算与额度", 项目级, 可改,
      ["scope", "period", "limit_amount", "reserved_amount", "currency"],
      ["两层控制:提交前预估并预留,执行中按用量监测(§11.5)"]),

    # ⑪ 任务底座
    E("jobs", "后台任务", 项目级, 可改,
      # 规格 §19.3 逐个点名了「任务至少保存」的东西 —— 原来漏了六个,补齐:
      #   stage(具体阶段)/ heartbeat_at / processed_count(已处理数量)
      #   / error_code / snapshot_hash(快照哈希)/ next_retry_at
      ["type", "target_ref", "status", "stage", "attempts", "max_attempts",
       "lease_until", "lease_owner", "heartbeat_at", "processed_count",
       "cancel_requested", "cancel_at", "idempotency_key", "external_id",
       "error_code", "error_detail", "snapshot_hash", "next_retry_at",
       "needs_human_check"],
      ["**数据库事务内写 Job + Outbox**(§18)—— 不许先发队列再写库",
       "lease 保证同一任务不被两个 worker 同时拿走;**重复投递是正常故障场景**(§17.1)",
       "取消请求与自然完成并发时,**保留真实最终状态及取消未生效原因**(§11.5),"
       "UI 不强行覆盖成「已取消」",
       "**heartbeat_at 和 lease_until 是两件事**:租约管「谁有权改它」,"
       "心跳管「它还活着吗」。只有租约的话,一个卡死但租约没到期的 worker "
       "会让任务看起来正常;只有心跳的话,两个 worker 能同时改同一条",
       "**error_code 要能分「该不该重试」** —— 格式错误、权限不足、预算禁止"
       "**不许盲重试**(§19.3):重试一个注定失败的任务只是在烧钱和占位",
       "**needs_human_check**:网络超时但对方可能已经成功,而对方没有幂等或查询能力 —— "
       "这时候**禁止自动重复不可逆动作**,标「待人工核实」。"
       "⚠️ 它**不是终态**:和「状态待核实」同一个道理,把它当成结束会让人去重跑",
       "snapshot_hash:提交时那份配置的哈希 —— 任务建好之后改配置不影响它,"
       "而**「我改了配置所以结果不同」和「同一份配置结果不稳」是两回事**"]),
    E("job_events", "任务事件", 子对象, 只追加,
      ["job_id", "seq", "kind", "payload", "at"],
      ["**事件有序、可重放**(§18):seq 在 job 内单调,SSE 断线后能从 seq 续"],
      依赖=["jobs"]),
    E("outbox", "事务发件箱", 项目级, 可改,
      ["job_id", "topic", "payload", "published_at", "attempts"],
      ["和 Job 在同一个事务里写;发布失败要能重试,发布成功要幂等"],
      依赖=["jobs"]),

    # ⑫ 审计
    E("audit_events", "审计事件", 项目级, 只追加,
      ["actor", "action", "target_ref", "environment", "at", "result", "reason",
       "redacted_diff", "request_id"],
      ["**追加写入,普通编辑不许删**(§15.4)",
       "Diff 要脱敏:审计本身不该变成一条泄露通道"]),

    # ═══ 以下是 Workflow 与 Agent 后台规格 §16.3 的增量 ═══════════════
    #
    # ## 一条贯穿这一段的注意事项:**JSONB 里的引用,数据库拦不住**
    #
    # 这一段里有好几处「确切版本引用」是存在 JSONB 数组里的:
    # `agent_versions.tools` 是一串 tool_version_id,`execution_runs.definition_ref`
    # 是一个 {kind,id,version_id} 对象。**这些引用没有外键。**
    #
    # 规格 §16.3 最后一句给了退路:「所有引用都要有项目/组织约束**或等效服务端验证**」。
    # 选 JSONB 是因为一个 Agent 版本引用 N 个工具版本,拆成连接表会让「冻结一个版本」
    # 变成写好几张表 —— 而那正是不可变对象最怕的事(写一半)。
    #
    # **代价要写在这里,不能只记在脑子里**:这几处必须由服务端在冻结时逐个验
    # (存在、同项目、有权限、能力兼容),而且**它是真的会被漏掉的那一类** ——
    # 因为漏了之后,库里那一行看起来完全正常。前一轮的攻击测试里,
    # 「项目级表根本没有指向 projects 的外键」就是这么活下来的。

    # ① Workflow
    E("workflows", "工作流", 项目级, 可改,
      ["name", "purpose", "owner", "tags", "draft_revision", "validation_status",
       "status"],
      ["**不能跨项目引用**;**名称不等于执行 ID**(§16.3)—— "
       "node_id 和 workflow id 稳定,改名不影响任何引用",
       "draft_revision 给乐观锁用:两个人同时编一张图,后写的会悄悄盖掉前一个"]),
    E("workflow_versions", "工作流版本", 子对象, 不可变,
      ["workflow_id", "version_no", "definition_schema_version", "nodes", "edges",
       "logical_hash", "dependencies", "layout", "input_schema", "output_schema",
       "change_note"],
      ["**图校验必须过**才能冻结;依赖一起冻结(§16.3)",
       "**布局坐标不参与 logical_hash**(§16.3、附录 A-9)—— "
       "自动布局挪一遍位置不该看起来像改了执行逻辑。"
       "坐标仍然存在这张表上(否则看历史版本的画布只能看到一团重叠的节点),"
       "但它进不了哈希:哈希的输入清单在 contract/dsl.py 的 规范化() 里,"
       "**按位置剥,不按名字剥**",
       "`nodes` / `edges` 里的 tool_version_id、prompt_version_id 这些引用"
       "**没有外键** —— 冻结时必须服务端逐个验(见这一段开头)"],
      依赖=["workflows"]),

    # ② Agent
    E("agents", "智能体", 项目级, 可改,
      ["name", "purpose", "owner", "tags", "draft_revision", "validation_status",
       "status"],
      ["和 Workflow 共用对象基础能力(草稿/版本/校验/引用关系)(§16.3)",
       "**不按工具数量给 Agent 打「能力强弱分」**(§9.1)—— "
       "工具数只表示授权候选集合的规模"]),
    E("agent_versions", "智能体版本", 子对象, 不可变,
      ["agent_id", "version_no", "prompt_version_id", "connection_version_id",
       "task_template", "tools", "context_policy", "limits", "output_schema",
       "completion_criteria", "incomplete_strategy", "execution_strategy",
       "input_schema", "content_hash", "change_note"],
      ["工具与策略都是**确切版本**;**已发布内容不可修改**(§16.3)",
       "**limits 是结构化状态,不是提示词里的一句话**(§9.5)—— "
       "硬权限、批准记录、步骤计数、剩余额度存在这里,"
       "靠模型摘要保存的上限等于没有上限",
       "context_policy.long_term_memory **首版默认关闭**(§9.5):"
       "未经审核就持久化的错误事实会跨任务传染",
       "`tools` 是 JSONB 里的一串 tool_version_id —— **没有外键**,冻结时服务端逐个验"],
      依赖=["agents", "prompt_versions", "connection_versions"]),

    # ③ 工具 / 连接 / 指南 / 规则
    E("tool_definitions", "工具", 项目级, 可改,
      ["name", "purpose", "side_effect_type", "adapter", "owner", "draft_revision",
       "status"],
      ["**未注册的工具名一律拒绝**(§9.4)—— 不能让模型凭一个名字临时发网络请求",
       "**风险变化要出新版本**(§16.3):一个工具从只读变成会写东西,"
       "而引用它的 Agent 还指着老的说明 —— 那份说明现在是错的"]),
    E("tool_versions", "工具版本", 子对象, 不可变,
      ["tool_definition_id", "version_no", "model_description", "input_schema",
       "output_schema", "side_effect_type", "allowed_scopes", "confirmation_policy",
       "idempotency_strategy", "external_status_lookup", "timeout_seconds",
       "retry_policy", "redaction", "secret_ref", "connection_id",
       "server_bound_arguments", "pollable", "content_hash"],
      ["**服务端绑定参数**(输出目录 / project_id / 允许的文档库)"
       "模型参数不许覆盖(§9.4)",
       "**pollable 要显式声明**(§10.3):相同参数的重复读取可能是合法轮询,"
       "「调用两次就算无进展」会把正常轮询判成失控 —— "
       "反过来,不声明就默认可轮询也会放过真的失控",
       "**不可逆写入必须有 confirmation_policy**;落点在 dsl.可以执行吗()",
       "redaction 说清哪些字段在 Trace 和导出里要脱敏"],
      依赖=["tool_definitions", "capability_connections"]),
    E("capability_connections", "工具连接", 项目级, 可改,
      ["name", "adapter", "allowed_endpoints", "secret_ref", "capability_snapshot",
       "status", "owner", "last_health_at", "health_detail"],
      ["**密钥不返回、不在前端回显**(§11.2);凭证轮换记审计,"
       "但**密钥内容不混入版本哈希** —— 混进去哈希本身就变成一条侧信道",
       "**停用即时生效**(§16.3):正在跑的 Run 也要被拦,"
       "不能等它跑完 —— 「停用」如果只对新 Run 生效,那它不叫停用",
       "**连接发现新工具不自动增加生产 Agent 的权限**(§11.2)—— "
       "MCP 发现回来的说明和返回值仍然是外部输入,要先审"]),
    E("skill_versions", "Skill 指南版本", 项目级, 不可变,
      ["name", "purpose", "version_no", "instructions", "applicable_conditions",
       "dependencies", "file_manifest", "review_status", "load_mode",
       "content_hash"],
      ["**指南不授予权限**(§11.3、§16.3)—— 「启用了指南」被读成「给了脚本权限」"
       "是这一块最容易出的误解;首版只支持 Markdown 指南和**只读**参考文件",
       "**按需加载要记实际加载了什么、什么时候加载的**(§11.3)—— "
       "只显示「已挂载」的话,没人知道模型到底读到了没有",
       "Skill **不是微调,也不保证模型一定遵循**"]),
    E("policy_versions", "规则策略版本", 项目级, 不可变,
      ["name", "purpose", "version_no", "rule_template", "params", "trigger_point",
       "failure_strategy", "test_cases", "content_hash"],
      ["**策略由后端运行**(§11.4):首版只开白名单规则模板 + 配置参数,"
       "**不开放网页任意代码**",
       "界面要写清「**指令约定**」和「**程序强制**」的区别 —— "
       "提示词里写「不要删文件」是约定,规则拦住 delete 才是强制"]),

    # ④ 运行
    E("execution_runs", "执行运行", 项目级, 可改,
      ["kind", "definition_ref", "release_ref", "input_snapshot", "definition_hash",
       "principal", "status", "limits", "parent_run_id", "environment",
       "execution_mode", "completion_reason", "quality_evaluation_status",
       "started_at", "ended_at", "deadline_at", "current_step_id", "output_ref",
       "usage_snapshot", "checkpoint_seq", "pause_requested", "cancel_requested",
       "idempotency_key", "trace_id"],
      ["**完整快照**:启动时固定发布清单和输入(§3.2);"
       "**正在执行的 Run 保持原版本**,但当前权限和停用开关**仍须实时检查**",
       "**status 和 quality_evaluation_status 是两件事**(§16.4):"
       "`succeeded` 只表示「定义要求的执行和确定性输出检查过了」,"
       "**不表示里面的事实都对**",
       "**execution_mode 分 mock/live**(§14.1)—— 一份 mock 跑出来的报告"
       "和真实报告在数据形状上一模一样,唯一的区别就是这个字段",
       "parent_run_id:子调用的额度和费用**计入父任务**,"
       "不是每嵌套一层重新拿一份完整预算(§13.2)",
       "**`definition_ref` / `release_ref` 是 JSONB,没有外键** —— 见这一段开头"],
      依赖=["applications", "release_manifests", "traces"]),
    E("run_steps", "运行步骤", 子对象, 可改,
      ["execution_run_id", "node_id", "kind", "iteration_path", "attempt",
       "execution_key", "logical_action_id", "input_ref", "output_ref", "status",
       "branch_key", "skipped_reason", "started_at", "ended_at", "error_code",
       "error_detail", "span_id"],
      ["**每次 attempt 保留一行,不覆盖旧结果**(§16.3、§8)—— "
       "「同一个节点重试了三次」和「它只跑了一次」必须能分出来",
       "**execution_key 含 (Run, node_id, 循环路径, 列表项, 尝试次数)**(§8);"
       "**逻辑副作用键不因普通传输重试而改变** —— 网络重发不该变成第二次写入",
       "**`skipped` 和 `failed` 不是一回事**(§8):未激活的支路既不阻塞汇合,"
       "也不能作为「完成了的工作」计入"],
      依赖=["execution_runs"]),
    E("run_checkpoints", "运行检查点", 子对象, 只追加,
      ["execution_run_id", "seq", "state_ref", "content_hash", "engine_version"],
      ["**只追加,用户不能任意替换**;恢复时**必须匹配引擎版本**(§16.3)—— "
       "换了执行内核还去读旧检查点,恢复出来的状态是什么没人知道",
       "检查点保存的是**位置和计数**,不是「把历史文本重新原样塞给模型」(§9.5)",
       "**重试计数、循环计数、模型回合和费用不因恢复归零**(§17.3)"],
      依赖=["execution_runs"], 内容寻址=True),
    E("tool_invocations", "工具调用", 子对象, 可改,
      ["run_step_id", "tool_version_id", "side_effect_type", "arguments_hash",
       "approval_ref", "idempotency_key", "logical_action_id", "external_id",
       "outcome", "status", "execution_mode", "result_ref", "intent_at",
       "responded_at", "duration_ms", "error_code", "error_detail",
       "needs_human_check"],
      ["**先登记 intent 再调外部,收到响应再登记结果**(§17.3)—— "
       "进程死在这两步之间时去**核实**,不盲重放",
       "**参数摘要和审批绑定**(§12.2):批准 A 之后改成 B,旧批准失效",
       "**needs_human_check 不是终态**:对方没有幂等也没有查询能力时,"
       "禁止自动重复不可逆动作 —— 但也不许把它显示成「已结束」"],
      依赖=["run_steps", "tool_versions"]),

    # ⑤ 人工介入
    E("human_requests", "人工请求", 子对象, 可改,
      ["execution_run_id", "run_step_id", "kind", "payload_ref", "allowed_fields",
       "candidate_roles", "status", "expires_at", "arguments_hash",
       "tool_version_id", "target_ref", "risk_note"],
      ["**一次请求只能被处理一次**(§16.3);重复提交同一决定要幂等,"
       "另一个人已经处理过则返回冲突和最新状态(§12.2)",
       "**参数改变则旧批准失效** —— 批准绑定的是"
       "(项目, Run, step, 工具版本, 目标资源, 参数摘要, 申请 revision, 截止时间, 批准人)",
       "**审批者必须对那个对象有权限**,不是「有审批角色」就行;"
       "**模型不能批准自己**(§9.6)",
       "**等待不占用 Worker**(§12.4):挂起时释放租约,靠事件恢复"],
      依赖=["execution_runs", "tool_versions"]),
    E("human_decisions", "人工决定", 子对象, 只追加,
      ["human_request_id", "actor", "decision", "edited_fields", "request_revision",
       "reason", "at", "idempotency_key"],
      ["**只追加,不能直接改历史决定**(§16.3)",
       "**「批准」只产生批准记录** —— 真正执行时仍然再查一遍权限和工具当前可用性"
       "(§12.2)。权限撤回或项目停用之后,老批准记录**不能**恢复写操作",
       "编辑过字段要重新检查权限、参数和额度,并保存前后 Diff;"
       "**系统安全字段、密钥和对象归属不可编辑**"],
      依赖=["human_requests"], 内容寻址=False),
    E("run_events", "运行事件", 子对象, 只追加,
      ["execution_run_id", "seq", "event_type", "step_id", "payload_ref", "payload",
       "occurred_at"],
      ["**seq 在 Run 内单调唯一,SSE 可按 after_seq 补发**(§16.3、§17.2)",
       "**事件只表达已记录的事实**(§17.2):"
       "**不能在外部返回成功之前先发 tool.succeeded** —— "
       "一个提前发出的成功事件会让前端和读日志的人都认为那件事做完了",
       "前端按 seq 去重补齐,**不用消息到达顺序猜运行进度**"],
      依赖=["execution_runs"], 内容寻址=False),

    # ⑥ 图草稿与布局(§16.3 最后一行)
    E("graph_drafts", "图草稿与布局", 子对象, 可改,
      ["workflow_id", "agent_id", "definition", "layout", "validation_report"],
      ["**定义与 UI 布局分开**(§16.3):布局改动不产生新语义版本",
       "一行只挂 workflow 或 agent 之一(两列都可空)。"
       "⚠️ **这条「二选一」数据库拦不住** —— 要 CHECK 约束才行,"
       "而这里的表是从登记派生的、暂不支持 CHECK。"
       "所以它现在靠服务端校验,**写在这里是因为它是个会被忘掉的约定**",
       "**浏览器离线时本地未提交的修改不能伪装成已保存**(§5.2)"],
      依赖=["workflows", "agents"]),
]

_按名 = {e["名"]: e for e in 实体表}

# ── 通用字段(规格 §18「通用字段」那一段)──────────────────────────
通用字段 = ["id", "created_at", "created_by", "updated_at", "revision", "archived_at"]
# 只追加的实体没有 updated_at / revision / archived_at —— 它们不该被改也不该被归档。
只追加豁免 = ["updated_at", "revision", "archived_at"]


def 该有的通用字段(e):
    出 = ["id"]
    # ⚠️ **「挂父级」的表也要带 project_id。** 第一版没带,后果是建表直接失败:
    # 项目级父表的主键是 (project_id, id),而子表的外键只有 parent_id ——
    # PostgreSQL 要求被引用列必须唯一,`traces.id` 单独并不唯一。
    #
    # 而这不只是让外键能建起来:规格 §18 要的是「跨对象引用使用**包含项目范围**
    # 的外键」。子表自己带 project_id,「拿 A 项目的 ID 到 B 项目下引用」
    # 在**数据库层**就不成立 —— 不靠每个 handler 记得检查。
    # 顺带也让按项目过滤不必每次 join 回父表。
    if e["范围"] in (项目级, 子对象): 出 += ["organization_id", "project_id"]
    if e["范围"] == 组织级: 出 += ["organization_id"]
    出 += ["created_at", "created_by"]
    if e["可变性"] != 只追加:
        出 += ["updated_at", "revision", "archived_at"]
    return 出


def 找(名):
    if 名 not in _按名:
        raise KeyError(f"没有这个实体:{名} —— 现有 {len(_按名)} 个")
    return _按名[名]
