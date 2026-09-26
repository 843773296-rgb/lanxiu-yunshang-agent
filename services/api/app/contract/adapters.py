#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""适配器契约(规格 §19.4)。

## 一条贯穿所有适配器的规矩:execution_mode

规格:「模拟适配器与真实适配器**实现同一契约**,但记录 `execution_mode=mock/live`。
**生产发布拒绝 mock 产物和 mock 验收报告**。」

这两句必须一起读。前半句让 mock 可以无缝替换真实实现 —— 这是好事,
开发不需要凭证也能跑通整条链路。**而正因为无缝,后半句才是必需的**:
一份 mock 跑出来的评测报告,和真实报告在数据形状上一模一样,
唯一的区别就是那个字段。没有它,「我们测过了」这句话没有任何含义。

> **让 mock 和真实长得一样,是为了开发方便;标记它们的区别,是为了结论可信。**
> 只做前一半,就是给自己造了一台印假证据的机器。

## 每个适配器「必须保留的结果」也不是可选项

规格给每个适配器列了一栏「必须保留的结果」。这些不是日志偏好,
是**出错之后唯一能定位问题的东西**。比如 ModelProvider 那一行要
「请求 ID、结束原因、**实际模型**、用量、原始错误类别」——
少了「实际模型」,你就永远说不清那次回答是哪个模型给的
(而默认模型会随凭证类型变,这件事在别处栽过)。
"""
MOCK = "mock"
LIVE = "live"
执行模式 = (MOCK, LIVE)


def AD(名, 中文, 方法, 必留, 说明="", 可选能力=()):
    return dict(名=名, 中文=中文, 方法=list(方法), 必留=list(必留),
                说明=说明, 可选能力=list(可选能力))


适配器表 = [
    AD("ModelProvider", "模型提供方",
       ["capabilities", "generate", "stream", "embed", "rerank"],
       ["request_id", "finish_reason", "actual_model", "usage", "error_class"],
       说明="按用途挑方法:生成用 generate/stream,Embedding 用 embed,重排用 rerank。"
            "**capabilities 要先问**:不支持的参数要返回明确错误,不许静默忽略 —— "
            "一个被静默忽略的参数,和一个生效了的参数,在响应上长得一模一样。"
            "**actual_model 必须记**:默认模型会随凭证类型变,不记就说不清那次是谁答的"),

    AD("DocumentParser", "文档解析",
       ["validate", "parse"],
       ["text", "structure", "source_location", "warnings", "parser_version"],
       说明="**source_location 是证据链的一环**:片段要能指回原文第几页第几段,"
            "否则「有出处」只是一句话。**parser_version 要记** —— "
            "升级解析器会改变切片结果,而那会让旧索引和新索引不可比"),

    AD("Retriever", "检索",
       ["build", "search", "health"],
       ["index_version", "chunk_ids", "score_meaning", "filter_meta", "recall_meta"],
       说明="**score_meaning 必须说清**:余弦相似度、BM25 分、融合分不是一回事,"
            "混着显示会让人拿两个不可比的数去比。"
            "规格 §17.1 专门提醒:**不要把 PostgreSQL 默认全文评分宣传成 BM25**"),

    AD("TrainingProvider", "训练提供方",
       ["validate", "estimate", "submit", "status", "cancel", "list_artifacts"],
       ["external_id", "real_status", "cost_source", "file_manifest"],
       可选能力=["resume"],
       说明="**resume 是单独声明的能力**,不许假设都支持。"
            "**external_id 是防重复训练的命根子**:网络超时但对方可能已经收下了,"
            "必须能按它查回真实状态。对方没有查询能力时标「待人工核实」,"
            "**禁止自动重复不可逆动作**(§19.3)。"
            "cost_source 要记:成本是估的还是账单上的,这两个数不能混"),

    AD("DeploymentProvider", "部署提供方",
       ["validate_artifact", "deploy", "health", "undeploy"],
       ["model_combo", "endpoint", "resources", "readiness"],
       说明="**validate_artifact 先跑**:不是所有模型/适配器组合都能用同一个运行时。"
            "readiness 和 deploy 成功是两件事 —— 部署返回 200 不等于能服务"),

    AD("Evaluator", "评分器",
       ["validate_rubric", "score"],
       ["rubric_version", "score", "rationale", "error", "cost"],
       说明="**rubric_version 必须记**:换了判据的两轮不可比,而分数表上看不出来。"
            "rationale 要留:一个说不出为什么的分数,改不了任何东西"),
]

_按名 = {a["名"]: a for a in 适配器表}


def 找(名):
    if 名 not in _按名:
        raise KeyError(f"没有这个适配器:{名} —— 现有 {list(_按名)}")
    return _按名[名]


def 可以发布吗(依赖们):
    """发布前闸:**任何一处是 mock 就不许发生产**(§19.4)。

    `依赖们` 是 [(是什么, execution_mode)] —— 产物、评测报告、部署都算。
    返回 (行不行, [挡住的理由])。
    """
    挡 = []
    for 什么, 模式 in 依赖们:
        if 模式 not in 执行模式:
            # 认不出的模式**当场挡**,不放行 —— 未知不等于安全。
            # 一个没标模式的产物,最可能的情况正是「它是 mock 但没人标」。
            挡.append(f"{什么}:execution_mode 是 {模式!r},认不出 —— "
                      f"**没标模式的一律挡**(未知不等于安全)")
        elif 模式 == MOCK:
            挡.append(f"{什么}:是 mock 的 —— 生产发布拒绝 mock 产物和 mock 验收报告")
    return (not 挡), 挡
