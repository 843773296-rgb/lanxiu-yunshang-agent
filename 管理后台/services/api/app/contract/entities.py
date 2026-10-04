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
    # ⚠️ **`uploads` 规格 §18 的实体表里没有,是 2026-09-27 补的**(和 `embeddings`
    # 同一形状:两条接口登记在 §17.1 而没有对应实体)。
    #
    # 规格 §17.1 对这两条接口的说明是:
    # 「**服务端校验之后才算文件引用** —— 上传成功不等于内容可用」。
    # 那句话需要一个**能记「校验没校验过」的地方**,不能只靠返回值 ——
    # 返回值是一次性的,而「这个文件能不能用」以后每次引用都要问。
    #
    # 所以状态机里 `已上传` **不是**终态,也**不等于可用**:
    # 只有 `已校验` 才算文件引用。一个把「上传成功」当「内容可用」的系统,
    # 会在引用一个坏文件时报「解析失败」,而根因是它从来没被校验过。
    E("uploads", "上传", 项目级, 可改,
      ["file_name", "byte_count", "content_type", "object_key", "content_hash",
       "status", "verify_detail"],
      ["**上传成功不等于内容可用**(§17.1)—— 只有 `已校验` 才算文件引用;"
       "`已上传` 只是「字节到了」",
       "`content_hash` 是**服务端校验时算的**,不信客户端报的 ——"
       "客户端算的哈希证明不了服务端收到的是同一份",
       "**校验失败要留着,不删** —— 一条「传过但没通过」的记录是证据;"
       "删掉之后用户只会再传一次同一个坏文件"]),

    E("knowledge_bases", "知识库", 项目级, 可改,
      ["name", "acl", "status", "embedding_purpose_connection_id"],
      ["知识库级 ACL 是上限,文档可以再收紧但不能放宽(§18「文档父级权限可收紧」)"]),
    E("documents", "文档", 子对象, 可改,
      ["knowledge_base_id", "source_info", "acl_override", "disabled_at"],
      ["**内容版本与权限状态分开** —— 停用一篇文档不该改它的历史版本"],
      依赖=["knowledge_bases"]),
    # `source_info` 是 2026-09-27 加的(M2)。**为了消掉一列有两个含义这件事:**
    # `object_key` 在 `tools/ingest_lanxiu.py` 灌的那批里是**仓库内相对路径**,
    # 在界面上传来的那批里是**对象存储键**。
    #
    # 今天没有任何代码读这一列(正文在 `chunks` 里),所以矛盾是**潜伏的** ——
    # 它会咬第一个想读原文的人(「查看原文」、重新切片),
    # 而那时报出来的是「文件不存在」,根因却是这一列有两个含义。
    #
    # ⚠️ **它必须在版本上,不在文档上。** 同一篇文档完全可以第一版是脚本灌的、
    # 第二版是界面传的。放在 `documents` 上就等于假设一篇文档所有版本来源相同,
    # 而那个假设失效时**不报错**,只是读原文时读错一个文件。
    E("document_versions", "文档版本", 子对象, 不可变,
      ["document_id", "object_key", "content_hash", "effective_at", "revision",
       "source_info"],
      ["原文放对象存储,库里只存键和哈希",
       "content_hash 决定「这份资料变没变」,不靠文件名也不靠时间",
       "**`source_info.存储` 说明 `object_key` 是哪种键** —— "
       "对象存储键 / 仓库相对路径。没有这个字段的行 `knowledge/ingest.py` "
       "**当场抛,不猜**:猜对了没人知道,猜错了报出来的是「文件不存在」"],
      依赖=["documents"]),
    # `chunker_version` / `parser_version` 是 2026-09-27 加的。**为了消掉一个
    # 会静默失效的假设:** 索引构建的输入指纹要含切片器版本(否则续做会产出
    # 一半旧边界一半新边界的混血索引),而那个版本原本只能从**当前代码的常量**读 ——
    # 隐含假设「库里的片段是当前版本切的」。
    #
    # 那个假设现在成立(只有 seg-1),但它会在第一次改 chunker 时失效,**而且不报错**:
    # 指纹算出 seg-2、判定说「输入变了,新建」,看起来正常 ——
    # 实际那些旧片段仍然是 seg-1 切的。
    #
    # 记在行上之后,指纹从**片段实际记的版本**算,判据从「假设」变成「读数据」。
    # 而且混着切的片段(一批 seg-1 一批 seg-2)能当场被发现。
    E("chunks", "片段", 子对象, 不可变,
      ["document_version_id", "section_path", "ordinal", "text", "text_hash",
       "token_count", "chunker_version", "parser_version",
       # ⚠️ 2026-10-03 加。`section_path` 是用 ` / ` 把各级标题**拼起来**的,
       # 而全库有 **29 个标题自己的名字里带 ` / `**,比如
       # `## 二、里料 / 衬料常见门幅(生产商规格为主,无标准原文)`。
       # 拿 ` / ` 拆它,一级会变成两级 ——
       # **而多出来的那一级在数据形状上完全合法**。
       # 实测:802 个片段里 44 个(5.5%)拆不回去,其中 43 个在 knowledge/
       # (= 导进后台那批语料)。
       #
       # > **路径的无歧义表示是列表,不是用分隔符拼起来的字符串。**
       #
       # `section_path` 保留(对外引用、显示都用它,一个字不改),
       # 要按级别做事的一律读 `section_titles`。
       "section_titles"],
      ["片段绑的是**文档版本**,不是文档 —— 否则文档一改,历史证据链就指向了新内容",
       "**记下切它的解析器和切片器版本** —— 索引构建的输入指纹要用它,"
       "从代码常量读会隐含「库里的片段是当前版本切的」这个假设,而它失效时不报错",
       "**`section_path` 拼起来就拆不回去**(29 个标题名字里带 ` / `)—— "
       "要按级别做事的读 `section_titles`(列表),不许 split 那个字符串"],
      依赖=["document_versions"]),
    # `input_hash` 是 2026-09-27 加的(规格 §19.3 要「输入版本变化则创建新构建」——
    # 没有它就判不出「输入变没变」)。名字用 `_hash` 后缀是为了命中已有的类型约定;
    # 代码里叫「输入指纹」,处理器里显式映射一次(`knowledge/index_plan.py`)。
    #
    # ⚠️ 它覆盖的**不只是**文档和配置,还有**切片器版本和解析器版本** ——
    # 文档没变、配置没变,但 chunker 的合并规则改了,片段边界就变了。
    # 少这两项,续做会产出一半旧边界一半新边界的**混血索引**:
    # 检索照样能跑,只是答得怪,而且没有一处会报错。
    E("index_builds", "索引构建", 项目级, 可改,
      ["knowledge_base_id", "retrieval_config_version_id", "embedding_model_id",
       "embedding_dim", "status", "job_id", "input_hash"],
      ["**向量维度兼容**要在构建前校验:换了 Embedding 模型,旧向量不能混用",
       "构建是后台任务,状态要能看见、能取消、能恢复",
       "`input_hash` 覆盖**文档版本集合 + 检索配置 + Embedding 模型与维度 + "
       "切片器版本 + 解析器版本** —— 少一项就会在变过的输入上续做(§19.3)",
       "**没有「已完成片段数」这种计数器** —— 检查点是 `index_members` 本身。"
       "计数器和产物会漂,而漂了不报错"],
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
    # (2026-09-27 当天就兑现了一次:1536 → **512**,因为用户拍了本地模型 BGE-small-zh-v1.5。)
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
      # ⚠️ `redaction_policy` 是 2026-09-29 的迁移加进库的,**而契约里漏了声明** ——
      # 于是 `alembic check` 从那天起一直红,而我**从来没跑过它**
      # (它装在 `make test` 里,我跑的是 contract / test-e2e / progress)。
      # > 一条判据装在一个我从来没跑过的目标里,等于没装。
      # CI 的 `admin-e2e` job 第一次跑就把它抓出来了 —— 那是加那个 job 的价值。
      ["name", "format", "purpose", "redaction_policy"],
      ["用途(训练 / 验证 / 独立测试)和格式分开登记"]),
    E("dataset_versions", "数据集冻结版本", 子对象, 不可变,
      # ⚠️ `frozen_samples` 就是上面那条约束(「冻结时要固化内容,不能只存一个指针」)
      # 的落点 —— 同样是 09-29 加进库而契约漏了声明的。
      # **一条写在约束里却没有列承载它的规矩,实现之后也没人知道它实现了。**
      ["dataset_id", "split_map", "content_hash", "sample_count", "revision",
       "frozen_samples"],
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
    # ⚠️ 2026-09-28 新加。**部署是第四个状态,不是产物上的第四个字段。**
    # 规格开篇第 4 条:训练完成 → 有产物 → 产物可用 → 在服务用户,四件事。
    # 之所以要一张表而不是 `model_artifacts.deployed` 一个布尔:
    # 同一个产物可以部署到不同环境、可以回滚、可以部署两次 ——
    # 一个布尔答不出「它现在在哪儿跑、是谁在哪天放上去的」,
    # 而那正是出事时唯一要问的问题。
    # ⚠️ **只追加,不是「不可变」。** 第一版标了 `不可变`,而门禁当场红:
    # 「内容寻址的实体都有哈希」—— 这套登记里 `不可变` 的意思是
    # **内容寻址**(靠哈希认「同一份内容」),而一次部署是**事件**不是内容:
    # 同一个产物部署到同一个环境两次,是**两件事**,不是同一份内容的两个副本。
    # 分类错了的后果不是少一列哈希,是**把「事件」当成了「版本」** ——
    # 而那会让人以为「重复部署」可以靠内容去重。
    E("deployments", "部署", 项目级, 只追加,
      ["model_artifact_id", "environment", "status", "endpoint_ref",
       "idempotency_key", "gate_evidence"],
      ["**mock 训练出的产物不许部署**(§17.4 铁律)—— 而「说不清是不是 mock」"
       "**也不许**:未知不是「不是」",
       "`gate_evidence` 记的是「当时凭什么放行」—— 部署是不可逆的对外动作,"
       "放行依据不能只留在某个人的记忆里",
       "「部署请求中」不是「在服务用户」:和取消那边同一个道理,真实状态由后台确认"],
      依赖=["model_artifacts"]),

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
    # ⚠️ 2026-09-28 新加。**候选配置和发布清单是两张表。**
    # 发布清单是「不可变」的(写下不许改,靠内容哈希认同一份);
    # 而候选天天在改 —— 塞进同一张表的话,那张表**同时是可变的和不可变的**,
    # 而「这一行能不能改」要靠 `approval` 是不是空来推。一张表两个含义。
    E("application_drafts", "应用候选配置", 子对象, 可改,
      ["application_id", "definition"],
      ["候选里挑的每一项依赖**都是确切版本的 id**,不是「最新」",
       "一个应用**只有一份候选**(唯一约束)—— 两份的话「出发布」出的是哪一份?",
       "改候选**不影响正在跑的那一版**:要切生产得出清单、审核、再发布"],
      依赖=["applications"]),
    E("release_manifests", "发布清单", 项目级, 不可变,
      ["application_id", "prompt_version_id", "connection_version_id",
       "index_build_id", "retrieval_config_version_id", "model_artifact_id",
       "evaluation_id", "approval", "content_hash", "revision",
       # ⚠️ **2026-10-02 补的,补的是一个洞。**
       #
       # 这张清单记了 prompt / 连接 / 索引 / 检索配置 / 模型产物的确切版本,
       # **唯独没有 Agent 版本** —— 而 Agent 版本里装着 `tools`
       # (它能用哪些工具)。
       #
       # 后果是具体的:做工具详情那一页时要回答
       # 「**停用这个工具会不会影响线上**」,而**整个库答不出来**
       # (实查:全库带 agent 字样的列只有 `agent_versions.agent_id`
       #  和 `graph_drafts.agent_id`)。
       #
       # > 一张自称「完整依赖清单」的表,少一样就答不全它自己承诺的问题。
       #
       # ⚠️⚠️ **这一列为空 = 那次发布没绑 Agent**,不是「数据坏了」。
       # 清单是**不可变**的 —— 已有的清单这一列永远是 NULL,不可能回去补。
       # 读成「数据坏了」然后报错的话,**所有历史发布记录会一起失效**,
       # 而建表、迁移、`alembic check` 全是绿的。
       # (今天第二次做这个决定:`agent_versions.tool_loading_type`
       #  那一列定的是「空 = 全部加载」,同一个形状。)
       "agent_version_id"],
      ["**完整依赖清单,全部是确切版本**(实施必须遵守第 1 条)——"
       "不许出现「用最新的那个」",
       "**不把任意模块的「最新版本」静默用于生产**(§2)",
       "**`agent_version_id` 为空 = 那次发布没绑 Agent**,不是数据坏了 —— "
       "清单不可变,历史清单那一列永远是 NULL",
       "⚠️ **「有一份清单记着它」不等于「生产正指着那一份」** —— "
       "生产在跑哪一版的真相源是 `environment_bindings`(环境指针),"
       "而一份三个月前回滚掉的清单照样记着它"],
      依赖=["applications", "prompt_versions", "release_manifests",
          "agent_versions"]),
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
    # ⚠️ `report_detail` 是 2026-09-28 加的(A3 上报链)。**不往 `note` 里塞。**
    # `note` 在 `fieldtypes.显式类型` 里被钉成 **TEXT**,那是个有意的决定:
    # 它是给人看的一句话。把幂等键、外部 trace、世界日期塞进去的后果是
    # **查不了** —— `note->>'幂等键'` 当场报
    # `operator does not exist: text ->> unknown`。
    #
    # 而幂等键必须查得了:查不了就没法判「这条判读上报过没有」,
    # 于是重复上报会**把采纳率的分母撑大**。
    #
    # (同一族第二次:前一次是我把裸字符串塞进 JSONB 的 `spans.error`。
    #  共同点是**没查列的真实类型就用了它** —— 而这个仓库恰好有一套
    #  很强的类型登记,今天还因为我加新列没登记类型当场拦过一次。)
    E("feedback", "反馈样本", 子对象, 可改,
      ["trace_id", "verdict", "note", "promoted_sample_id", "report_detail"],
      ["打了「答错了」要能回流成评测样本 —— 记下回流到哪条"],
      依赖=["traces"]),

    # ⑩ 用量与费用
    # ⚠️ `依赖=["traces"]` 是 2026-09-28 加的 —— 在这之前 `trace_id` **不是外键**,
    # 于是那一列可以填任何字符串,而**没有任何一层会发现**。
    # (和 `index_members.embedding_id` 指向一张不存在的表是同一个形状,
    #  那次也是补真外键解决的。)
    #
    # 一条账目的 `trace_id` 指向空处的后果:算账时它照样被计入总额,
    # 而点进去看「这笔钱花在哪次调用上」**查不到** ——
    # 钱是真的,而它的出处是假的。
    #
    # > 能用约束表达的,不要用判据表达:外键在**每次 INSERT** 上生效,
    # > 判据只在有人调用时生效。
    # 加之前量过:现有 96 行 trace_id 全部指向真 trace,0 行为空、0 行悬空。
    # ⚠️ `provider` / `caller` / `world_date` 是 2026-09-28 加的。**起因是一个我自己犯的错:**
    #
    # `source` 这一列当时有**两个含义** —— Worker 写的 100 行是 `execution_mode`
    # (mock / live,是不是真跑的),而我前一天写的 12 行塞的是**提供方**(anthropic)。
    # 两种值都是合法字符串,分组查询照样出结果,只是「mock」和「anthropic」
    # 被并排列在同一列里,**看起来像两个供应商**。
    #
    # (这正是前一天修 `document_versions.object_key` 时写下的那句话:
    #  「一列有两个含义而没人知道,比缺一列糟得多」—— 写完第二天自己跳进去了。
    #  **写在注释里对当下不起作用,起作用的是检查。**)
    #
    # Worker 的含义在先,所以 `source` 归还给「执行模式」,缺的维度各给一列:
    #
    #   `provider`    谁提供的(anthropic / deepseek)。**成本必须按供应商算** ——
    #                 并行会话实测 SDK 的总价跨供应商差过 24 倍、135 倍
    #   `caller`      **谁花的**(门店助手 / 检索实验室 / 试跑)。没有它,
    #                 「门店助手今天花了多少」答不出来,只答得出「一共花了多少」
    #   `world_date`  演示世界里的日期。门店助手跑在演示世界(停在某一天),
    #                 而记录的时间戳是真实时间 —— **两个时钟混在一张表里而且不报错**
    E("usage_ledger", "用量账目", 项目级, 只追加,
      ["event_key", "trace_id", "resource", "quantity", "unit", "currency",
       "pricing_version_id", "amount", "amount_known", "source",
       "provider", "caller", "world_date"],
      ["**唯一用量事件防重复计费**(§18):event_key 唯一约束",
       "**unknown 区分 zero** —— amount_known=False 时前端显示「未知」,**不许显示 0**",
       "外部账单有延迟,费用上限**不得宣称绝对零超支**(§11.5)",
       "**`trace_id` 是真外键** —— 一笔查不到出处的钱,在总额里和真的一样",
       "**`source` 是执行模式(mock/live),`provider` 才是供应商** —— "
       "这两件事混在一列里过,而混了不报错",
       "**`caller` 不能省** —— 没有它只答得出「一共花了多少」,"
       "答不出「门店助手花了多少」"],
      依赖=["traces"]),
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
       # ⚠️ `config_snapshot` 是 2026-10-03 加的,补的是一句**写在注释里而没兑现**的话。
       #
       # 原来只存 `snapshot_hash`,而提交那条接口的注释写着
       # 「快照哈希:提交时那份配置 —— **任务建好之后改 Prompt 不影响它**」。
       # 那句话是假的:Worker 执行时按 id **重查 `prompt_drafts`**,
       # 既不核那个哈希、也拿不到提交时的正文。
       # 于是「提交 A → 排队 → 有人把草稿改成 B → Worker 跑的是 B」,
       # 而界面上那次运行看起来就是 A 的结果。
       #
       # > **一句声称自己已经做到的注释,比没有注释更糟** —— 它让读代码的人不去核。
       #
       # **存一个哈希还原不了内容。** 所以这里存内容本身,
       # 而 `snapshot_hash` 变成它的校验和(执行前比一次)。
       "config_snapshot",
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
       "input_schema", "content_hash", "change_note",
       # ── 工具筛选(2026-10-02 第三份规格 §13.2)──────────────────
       # 「提供给模型的方式:全部加载 / 固定工具组 / 按任务发现」。
       # ⚠️⚠️ **这一列为空必须被读成「全部加载」,不是「没配置」。**
       # 这是规格 §16 第一阶段那条兼容性要求的唯一落点:
       # 「旧 Agent 默认继续原加载方式」。
       # `agent_versions` 是**不可变**的 —— 已有的版本这一列**永远是 NULL**。
       # 实现要是把 NULL 当「未配置」然后报错,
       # **所有历史 Agent 版本会在升级那一刻一起失效** —— 而建表时一切正常。
       # 规格原话也说「全部加载……**保留作为旧配置兼容及对比基线**」:
       # 它不是过渡态,是个永久选项(没有基线就没法说筛选是不是更好)。
       "tool_loading_type",
       # 选了「固定工具组」或「按任务发现」时指向确切的策略版本。
       # 列名是全称 —— 短名推不出外键,见 `selection_decisions` 那段。
       "tool_selection_policy_version_id"],
      ["工具与策略都是**确切版本**;**已发布内容不可修改**(§16.3)",
       "**`tool_loading_type` 为空 = 全部加载**(规格 §13.2 的兼容要求)—— "
       "旧版本这一列永远是 NULL,把 NULL 当「未配置」会让历史版本一起失效",
       "**筛选策略不许扩大授权**(规格 §13.2):策略里的必要工具"
       "不在这个 Agent 的 `tools` 里时**阻止冻结并定位冲突**,"
       "**不能自动勾上** —— 自动勾上就等于让筛选策略成了一条发权限的路,"
       "而规格 §3 明写「筛选得分高不授予权限」",
       "**limits 是结构化状态,不是提示词里的一句话**(§9.5)—— "
       "硬权限、批准记录、步骤计数、剩余额度存在这里,"
       "靠模型摘要保存的上限等于没有上限",
       "context_policy.long_term_memory **首版默认关闭**(§9.5):"
       "未经审核就持久化的错误事实会跨任务传染",
       "`tools` 是 JSONB 里的一串 tool_version_id —— **没有外键**,冻结时服务端逐个验"],
      依赖=["agents", "prompt_versions", "connection_versions",
          "tool_selection_policy_versions"]),

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
       "server_bound_arguments", "pollable", "content_hash",
       # ── §8.2「模型说明」页签的三个字段(2026-10-03 加)──────────
       # ⚠️ **不是替 `model_description`,是在它之外补的。**
       # 那一个是「模型可见的工具说明」,这三个回答的是它回答不了的问题:
       # 用什么别的说法指这件事 / 什么时候该用它 / 真人是怎么问的。
       #
       # 为什么它们非得跟着**版本**走:`tool_versions` 是不可变子对象,
       # 所以改一条别名就是出一个新版本 —— 而这正是要的,
       # 因为**别名是模型实际会读到的内容**,改了它等于改了工具说明,
       # 而规格 §16.3 的既有约定是「说明变了要出新版本」
       # (否则引用老版本的 Agent 指着的那份说明已经不是现在这份)。
       "model_aliases", "when_to_use", "task_examples"],
      ["**服务端绑定参数**(输出目录 / project_id / 允许的文档库)"
       "模型参数不许覆盖(§9.4)",
       "**pollable 要显式声明**(§10.3):相同参数的重复读取可能是合法轮询,"
       "「调用两次就算无进展」会把正常轮询判成失控 —— "
       "反过来,不声明就默认可轮询也会放过真的失控",
       "**不可逆写入必须有 confirmation_policy**;落点在 dsl.可以执行吗()",
       "redaction 说清哪些字段在 Trace 和导出里要脱敏",
       # ── 下面三条是 §8.2 那三个字段的约束(2026-10-03)──────────
       "**`when_to_use` 要么两边都给,要么一边都不给**:"
       "只写「适用」而不写「不适用」时,"
       "「不适用」会静默变成「没说过」—— 而**一个没说过不适用的工具,"
       "和一个处处适用的工具,在模型眼里长得一模一样**。"
       "10-03 量到的 5 道零重叠题缺的不是关键词,是「什么时候不该用它」",
       "**`task_examples` 每条必须带来路**(记录仪 / 业务口述 / 现编),"
       "而「现编」要标出来:10-03 栽过一次 —— "
       "拿反推出来的别名跑出 21/21,那是**先看答案再出题**。"
       "不带来路的话,一条编的例子和一条真实问法在这张表里长得一样",
       "**这三个字段是模型会读到的内容,不是后台的备注** —— "
       "所以「预览模型所见内容」要显示模型实际收到的那一段,"
       "而不是把三个字段并排列出来(否则「后台显示的」和「模型收到的」会分家)"],
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
    # ── 澜绣 V3 的旋钮方案(2026-10-02,搬家说明 `已搬走.md` 的第二条)──
    #
    # ⚠️ **这是「控制面」,不是第二套 Agent 配置。**
    # 搬家说明批评过的正是「仓库里有了两套『调 agent』的东西」——
    # 所以这个对象**不碰** `agent_versions`:后者是后台自己的 Agent 模型,
    # 而这 6 个旋钮管的是**澜绣 V3**(`agentsite/sdk.py`)怎么跑。
    # 两件事塞一个对象里,那句批评就会再犯一次。
    #
    # ## 为什么它只有一张表(没有版本表)
    #
    # 一个「方案」本身就是一次实验(`.feynman/prompt_candidates/{号}.json`):
    # 它记着「改了什么、为什么改、跑出来什么分」。
    # 改一个方案就是改那次实验;要做新实验就建新方案 ——
    # **再套一层版本表只会多一个没人用的维度。**
    #
    # ## ⚠️ 旋钮的**定义**不存在这里
    #
    # 「有哪6个旋钮、取值是什么、默认多少」在 `agent/knobs.py` 的 `旋钮表`,
    # 接口从那儿现读。**不在后台复制一份** ——
    # 复制的那份会和代码漂,而漂开时后台上会多出一个
    # **拖了什么都不会变的滑块**(`knobs.py` 自己的话:
    # 「一个旋钮如果只存在于这张表和页面上,它就是个滑块」)。
    # ── 缓存管理(2026-10-04 加,规格 `产品经理面试/output/cache-management/`)──
    #
    # ⚠️⚠️ **只登记了阶段 1–2 要的五个对象,不是规格 §15.1 那九个。**
    #
    # 规格 §4 把交付分成五个阶段(接入与观测 → 提示词缓存策略 →
    # 精确答案缓存 → 运维与评测 → 语义缓存)。九个对象横跨全部阶段 ——
    # 一次全登记会建出**四张没人写的表**(答案条目目录、失效代次、
    # 清理任务、评测扩展)。
    #
    # 这个仓库的教训:「**摆七个壳子、三个是空的,比摆两个满的糟**」——
    # 空的那几个让人以为「这里没东西」,而真相是「这里还没做」。
    #
    # **所以这是个决定,不是漏登。** 等阶段 3(精确答案缓存)开工时再加:
    #   · `answer_cache_entries`      条目目录
    #   · `cache_namespace_states`    失效代次(权威)
    #   · `cache_invalidation_jobs`   清理任务
    #   · `cache_evaluation_extensions` 评测扩展
    # 它们的字段后缀**已经登记好了**(`_generation` / `_epoch` / `namespace` …),
    # 所以那一步不会再碰 `fieldtypes.py`。
    E("cache_policy_drafts", "缓存策略草稿", 项目级, 可改,
      ["kind", "policy_config", "owner", "status", "change_note",
       "draft_revision"],
      ["`kind` 分**提示词缓存**和**答案缓存** —— 规格 §3 把两者的边界列成了一张表,"
       "**它们不是一个开关的两个档**:提示词缓存命中后仍然生成,"
       "答案缓存命中后这次根本没有生成调用",
       "**保存草稿不影响生产**(规格 §8.2)—— 生产跑的是冻结版本;"
       "而「保存了」和「生效了」是两件事,页面上要分开显示",
       "**答案缓存默认不覆盖整个 Agent**(规格 §10):只收明确登记过的"
       "**只读**任务。涉及客户实时状态、价格库存、审批、发送、扣款的,"
       "默认不进答案缓存 —— 而「它是只读的」这件事不许由模型自己声明"]),
    E("cache_policy_versions", "缓存策略版本", 子对象, 不可变,
      ["cache_policy_draft_id", "version_no", "policy_config", "content_hash",
       "schema_version", "capability_snapshot_ref"],
      ["冻结;被引用时不得物理删除(和 `prompt_versions` / `tool_versions` 同形状)",
       "**版本里钉着当时的能力快照**(`capability_snapshot_ref`)—— "
       "不钉的话,连接能力变了之后这一版的配置可能已经不成立,"
       "而**版本本身看不出来**(规格 §8.2:无证据显示「配置已保存,运行接入未验证」)",
       "⚠️ **冻结不等于发布**(规格 §16)—— 发布引用由现有发布清单管"]),
    E("cache_capability_snapshots", "缓存能力快照", 项目级, 不可变,
      ["connection_id", "connection_revision", "api_kind", "cache_mode",
       "ttl_options", "min_prefix_tokens", "supported_operations", "usage_map",
       "evidence_at",
       # ⚠️ `content_hash` 是契约检查逼出来的,而**它逼对了**:
       # 不可变实体要么内容寻址(有哈希),要么进那个上限 3 个的白名单。
       # 而这张表确实该内容寻址 —— 它能回答一个真问题:
       # **「这次探测和上次比,能力变了吗」**。
       # 没有哈希的话,每次探测都得新建一行,
       # 而「能力真变了」和「只是又探了一次」在表上长得一模一样。
       "content_hash"],
      ["**事实和未验证分开**(规格 §15.1)—— 这张表记的是"
       "「**核查那一刻**这个连接能做什么」,`evidence_at` 就是那一刻;"
       "过时了要重新核查,**不许把旧快照当现状**",
       "`supported_operations` 是三态的(支持 / 不支持 / **没核查过**)—— "
       "用 JSONB 而不是三个布尔:一个 NULL 布尔在大多数代码里读起来就是 false,"
       "于是「没核查过」会变成「不支持」,而那两件事在界面上该显示不同的话",
       "⚠️ **供应商维护的前缀缓存不等于后台拥有它的物理条目**(规格 §9):"
       "没有列举/删除 API 时,界面上**不许出现**「查看供应商缓存正文」"
       "「立即删除供应商缓存」—— 那是两个点不动的按钮",
       "**用户不能把运行接入模式自行改成「支持」**(规格 §9)—— "
       "它从适配器能力返回,而适配器的依据就是这张快照"]),
    E("cache_runtime_overrides", "缓存运行覆盖", 项目级, 可改,
      ["scope", "status", "disabled_reason", "operator_id", "expires_at",
       "revision"],
      ["**只允许收窄复用,不允许放宽**(规格 §15.1)—— 和工具筛选那条"
       "「只许收窄」是同一条:一个能放宽的紧急开关,在出事的时候会被用来放宽",
       "**和普通保存草稿不同**(规格 §13):它写的是服务端运行覆盖,"
       "**立即生效**,并且要记操作者、原因、期限和恢复条件",
       "⚠️ **恢复使用必须重新检查资料及权限**(规格 §13)—— "
       "不因为清理任务被取消就自动复活旧答案"]),
    # ⚠️ **这里原来写的是「不可变」,而契约检查当场把它顶回来了** ——
    # 它报「内容寻址的实体都有哈希」时点名了这张表。
    # 判据逼对了:**不可变和只追加不是一回事**。
    #   不可变 = **内容寻址的制品**(同样的内容就是同一个,所以要哈希)
    #   只追加 = **事件日志**(两条内容相同的决定是两次不同的事件)
    # 给事件日志加内容哈希会让「同一个请求被判了两次」变成一行,
    # 而那正是要查的东西。
    E("cache_decisions", "缓存决定", 项目级, 只追加,
      ["trace_id", "cache_layer", "decision", "reason",
       "actual_policy_version", "source_trace_id", "usage_completeness"],
      ["**只追加**;查询权限继承 Trace(规格 §15.1)",
       "⚠️ **两层的决定是两套枚举,不许合成一套**(规格 §15.2):"
       "答案层是 `exact_hit / semantic_hit / miss / bypass / invalidated / "
       "backend_error`;提示词层是 `hit / miss / unknown / not_called / "
       "not_supported`。**「答案命中」时根本没有生成调用,"
       "那不叫提示词缓存未命中**(附录 A-8 点名的错法)",
       "`actual_policy_version` 是**运行时实际采用的那一版**,"
       "不是配置里写的那一版 —— 规格 §2 要求"
       "「配置保存、发布绑定、运行时实际采用、供应商实际命中**分别记录**」,"
       "而这四件事混在一起时,**页面上没有任何地方能看出配置没生效**",
       "`usage_completeness` 说清这次**缺了哪几个用量字段**,"
       "不是一个「完整/不完整」的布尔 —— 缺哪一档决定了哪些指标还能算"]),
    E("knob_plans", "旋钮方案", 项目级, 可改,
      ["key", "params", "owner", "status", "change_note",
       "exported_at", "file_hash", "draft_revision"],
      ["`params` 装的是**旋钮值**(`{\"effort\": \"high\"}` 这种),"
       "只写要改的那几个 —— **没写的保持调用方传进来的值**,"
       "不是用默认去覆盖(`knobs.应用()` 的注释:那会把显式传参吃掉,"
       "是一类很难查的 bug)",
       "**`key` 就是方案号**,和 `.feynman/prompt_candidates/{号}.json` 对应",
       "**导出只改文件里的 `旋钮` 这一个键**,保留 `改` / `拷自` / `验证` —— "
       "后台只管旋钮那一半,整份覆盖会抹掉提示词改动和**跑过的评测结果**,"
       "而后者不可重建。> 一个只管一半的编辑器,在保存时会把另一半清掉 —— "
       "而那在「保存成功」那一刻看不出来",
       "`file_hash` 记的是**导出那一刻文件的哈希**:"
       "用来判「文件后来被人手改过」—— 那种不一致不报错,"
       "只是后台显示的和 V3 真读到的不是一回事"]),

    # ── 工具筛选与按需加载(2026-10-02 第三份规格 §14.1)────────────────
    # ⚠️ **这六个对象的分界线是「谁决定它」**,见那份规格 §3 的状态表:
    #   已登记 → Agent 允许范围 → 当前可用 → 本轮候选 → 实际加载 → 实际调用
    # 工具组和策略决定的是**前两格**(配置);快照和筛选决定记的是**后三格**
    # (运行时发生过什么)。混成一个对象的话,
    # 「这个 Agent 可以用它」和「这一轮给模型看了它」就分不开了 ——
    # 而规格 §3 明写:**「本轮未加载」不等于「无权限」;
    # 「筛选得分高」不授予权限。**
    E("tool_groups", "工具组", 项目级, 可改,
      ["name", "purpose", "owner", "status", "draft_revision"],
      ["**组只是一份搭配,不是一份授权**(规格 §3)—— "
       "Agent 绑定了某个组版本,执行权仍要过 `tool_gateway` 的实时查验",
       "**停用组不回收模型已经见过的说明**:历史加载记录照留,"
       "而后续执行必须被拦 —— 这两件事要分开记"]),
    E("tool_group_versions", "工具组版本", 子对象, 不可变,
      ["tool_group_id", "version_no", "member_manifest", "companion_map",
       "content_hash", "change_note"],
      ["**成员是确切的 tool_version_id,不是工具名**(规格 §3)—— "
       "指向工具名的话,工具出了新版本这一组的行为就悄悄变了",
       "`member_manifest` 一条一条写「加载角色 + 必不可少吗」:"
       "**「这组里有它」和「这一轮必须给它」是两件事**(A-5 按必要性先放必需的)",
       "`companion_map` 的配套关系**要能查出环**(A-4)—— "
       "A 配套 B、B 配套 A 的话,预算算法会反复把两个都算进同一组",
       "**同名校验在冻结时做**:两个工具版本在模型眼里同名,"
       "模型发出的调用就分不清是哪一个 —— 而它看起来只是少了一个工具"],
      依赖=["tool_groups", "tool_versions"]),
    E("tool_selection_policies", "筛选策略", 项目级, 可改,
      ["name", "purpose", "owner", "status", "draft_revision"],
      ["**策略必须评测过才能进生产**(规格 §4.1)—— "
       "换一套筛选规则会改变模型看得见什么,而那件事在接口上一声不响"]),
    E("tool_selection_policy_versions", "筛选策略版本", 子对象, 不可变,
      ["tool_selection_policy_id", "version_no", "selection_mode",
       "catalog_snapshot_ref", "default_group_version_ref", "limits",
       "loading_type", "empty_result_action", "catalog_error_action",
       "independent_router_enabled", "candidate_cache_enabled",
       # ⚠️ 2026-10-03 加。`independent_router_enabled` 在这之前**一道闸都没有** ——
       # 而规格 §4.2 给的是**条件**不是开关:
       # 「**只有实验证明额外分类有价值时,才启用独立路由节点**」。
       # 这两列是那个条件的落点:指一次已完成的评测,和规格 §9.6 要的模型连接。
       # > 一个没有实验撑着的「已启用」,和一个有实验撑着的,在策略页上长得一模一样。
       "router_evidence_ref", "router_connection_id",
       "release_criteria", "content_hash", "change_note"],
      ["**身份、真实授权、密钥、对象范围不进这里**(规格 §14.3)—— "
       "它们由服务端绑定;放进策略就等于放进了模型可填的参数",
       "`limits` 的初值见规格 §14.3(候选 5 / 新增定义 4000 token / "
       "活动 12000 / 补搜 2 次 / 超时 3000ms)—— **是设计初值,不是实测出来的**",
       "**`empty_result_action` 和 `catalog_error_action` 要分开**:"
       "「目录里没有合适的工具」和「目录本身取不到」下一步完全不同 —— "
       "前者该补搜或停止,后者该退回固定组;合成一个的话,"
       "一次索引故障会被当成「这个任务没有可用工具」",
       "**`candidate_cache_enabled` 首版关闭**(A-7):"
       "缓存命中也只复用候选 ID,权限、启停和版本仍要实时复核"],
      # 依赖里加 evaluations / capability_connections:那两列是跨对象引用,
      # 而「声明了依赖」要落成外键(`fk_dep_check` 在守)。
      # `router_evidence_ref` 的列名推不出来(它不叫 evaluation_id),
      # 所以进了 `models.py::_依赖列` 的显式映射。
      # ⚠️ 这里第一版写的是 `capability_connections`(**工具**连接)—— **接错了表**。
      # 规格 §9.6 要的是「**模型连接**」,而后台有两张:
      #   `capability_connections` 工具连接(没有探测口)
      #   `model_connections`      模型连接(有 `POST /model-connections/{id}/probe`)
      # 是撞见探测口才发现的。**外键建错了表,在列表上完全看不出来。**
      依赖=["tool_selection_policies", "evaluations", "model_connections"]),
    E("tool_catalog_snapshots", "工具目录快照", 项目级, 不可变,
      ["catalog_hash", "tool_version_ids", "tokenizer_ref", "embedder_ref",
       "status", "build_detail", "activated_at"],
      ["**只有 ready 的快照能被绑定**(规格 §14.4),切指针要原子完成 —— "
       "半建好的索引被绑上去,表现是「某些工具搜不到」而不是报错",
       "**分词器/向量器版本要冻结在快照里**(A-7):"
       "换了分词实现而快照哈希不变,同一个查询会召回不同的工具,"
       "而两次运行的记录看起来完全一致",
       "**索引可重建,它不是真值** —— 真值是 `tool_versions`;"
       "重建不该改变任何一次历史运行的记录"]),
    E("selection_decisions", "筛选决定", 子对象, 可改,
      # ⚠️ 这两个列名**是全称,不是 `policy_version_id` / `catalog_snapshot_id`**。
      # 外键是从依赖表名推列名的(`models.py`),短名推不出来 ——
      # 而推不出来的表现是**静默不建外键**:
      # > 一个没有外键的引用列,和一个有外键的引用列,
      # > **在表结构上长得一模一样** —— 直到某天它存进一个不存在的版本 id。
      # 第一版我就是写了短名,`alembic check` 的输出里那两列干干净净地
      # 没有 ForeignKey,而六张表全都「建对了」。
      ["execution_run_id", "run_step_id", "tool_selection_policy_version_id",
       "tool_catalog_snapshot_id", "capability_query", "normalized_query",
       "candidate_ids", "loaded_version_ids", "budget_detail",
       "not_loaded_detail", "authz_fingerprint_hash", "status", "error_code",
       "rediscovery_no", "parent_decision_id"],
      ["**每一阶段的证据都留着,后一阶段不覆盖前一阶段**(规格 §14.4:"
       "requested → eligible → ranked → loaded,或 empty/blocked/failed)—— "
       "只留最终结果的话,「漏召回」和「召回了但没加载」长得一模一样,"
       "而这两种的下一步完全不同(改索引 vs 改预算)",
       "**`empty` 不是 `failed`**:「没有合适的工具」是一个有效答案,"
       "把它记成请求失败,会让人去查一个没坏的接口",
       "**补搜另起一行并指向父决定**(`parent_decision_id`),"
       "不覆盖首次候选 —— 否则「第一次就漏了」这件事再也查不出来",
       "**`authz_fingerprint_hash` 不存明文**(A-7):"
       "它是用来判「换了身份就不能复用候选」的,哈希不是加密"],
      依赖=["execution_runs", "run_steps", "tool_selection_policy_versions",
          "tool_catalog_snapshots"]),

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
