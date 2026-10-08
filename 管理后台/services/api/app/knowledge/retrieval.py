#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索:向量召回 → Claude 精排 → 按预算截断 → 出证据链。

规格 §9.5:「必须看到**整条链路**:原问、改写、候选、融合分、选片、证据、Trace」。
所以这里返回的不是一个答案,是**一条能被复核的链** ——
每一步的中间结果都留着,因为「为什么是这几段」是这个功能的主要价值。

## 为什么召回和精排都要,而且顺序不能换

真语料上实测过一次(71 个片段,问「客户给了差评要怎么处理」):

    向量召回第 1 名:  | # | 要做的 | 判据 / 验法 |    ← 一个**表格头**,0.6849
    向量召回第 2 名:  ≤3 星算差评;差评自动进待处理清单   ← 真答案,0.6329

    Claude 精排:     真答案 9/10,表格头 **0/10**

embedding 的病是**短的、抽象的文本在语义空间里占据中心位置**,
而中心位置对任何查询都有中等相似度。它不报错 —— 检索永远返回 N 条。

**召回负责「别漏」,精排负责「排对」。** 两个换不了:
精排读不了 71 段全文(贵且慢),召回排不对(上面那个例子)。

## ⚠️ 首版没有的东西,写在这儿而不是等人发现

  · **查询改写**(§9.5 的「改写」)—— 没做。返回里 `改写` 恒为 None
    并带一句说明,**不是空字符串** ——「没做」和「改写结果是空」要分得开
  · **关键词召回 / 融合**(`recall_modes` 里的 keyword / hybrid)—— 没做。
    配置里要了 keyword 会**当场报错**,不静默退化成只走向量
    (静默退化会让人以为融合在生效)
  · **向量索引**(hnsw)—— 没建。71 个片段顺序扫够用,上真量之前必须补
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
if _这 not in sys.path:
    sys.path.insert(0, _这)

from sqlalchemy import text   # noqa: E402

_运行时 = os.path.join(os.path.dirname(_这), "runtime")
if _运行时 not in sys.path:
    sys.path.insert(0, _运行时)

import adapters as AD          # noqa: E402
import rewriter as RW          # noqa: E402
import 语料可见 as KV          # noqa: E402
import index_plan as IP        # noqa: E402
import reranker as RR          # noqa: E402

检索器版本 = "retrieve-1"
# 一个片段粗估多少 token。⚠️ 和 `chunker._粗估token` 同一个粗估,
# **不许拿它算钱** —— 真实 token 要问 tokenizer,而各模型不一样。
_每字token = 0.6


class 检索不了(Exception):
    """配置或索引不满足检索的前提。**当场抛,不降级** ——
    一个降级过的检索结果和一个正常结果长得一样。"""


def 证据串(片段):
    """「业务拍板 · 2026-09-27 / 一、什么时候请评价 · 第 3 段」

    ⚠️ 这不是装饰。顾问要能**照着它翻回原文核对** ——
    而一个查不回去的引用比没有引用糟:它看起来有出处。
    """
    return f"{片段['section_path']} · 第 {片段['ordinal']} 段"


def 检索(conn, *, 项目, 构建id, 问题, 这个人的角色们, 要精排=True):
    """跑一次检索。返回规格 §9.5 要的整条链路。

    ⚠️ `conn` 由调用方给 —— 这个模块**不自己开连接**:
    检索要和调用方在同一个事务里看到同一份数据
    (否则「刚建好的索引查不到」这种事会变成偶发)。

    ## ⚠️ `这个人的角色们` 是**必填的位置之后关键字参数**,没有默认值

    给它一个默认值(比如 `None` = 不过滤)就等于留了一条静默放开的路:
    > 一个「接了身份过滤」的检索,和一个「接了而某个调用方没传所以没过滤」的,
    > **在那条检索结果上长得一模一样** —— 而漏传的那个调用方把全部语料
    > 交给了一个没权限的人。

    必填之后漏传是 `TypeError`,**当场炸在那一行**。
    这比任何检查都可靠 —— 它不需要有人记得去跑。

    ⚠️ 传的是**角色**,不是 `身份.grants`(专项授权)。
    混进来会让专项授权成为绕过语料 ACL 的万能钥匙 —— 见 `语料可见` 模块头。
    """
    if not (问题 or "").strip():
        raise 检索不了("问题是空的 —— 空查询的向量没有意义,"
                     "而它会返回一批「离原点最近」的片段,看起来像正常结果")

    b = conn.execute(text("""select ib.*, rc.recall_modes, rc.candidate_k, rc.fusion,
                                   rc.rerank, rc.context_budget_tokens,
                                   rc.final_chunk_limit
                              from index_builds ib
                              left join retrieval_config_versions rc
                                on rc.project_id = ib.project_id
                               and rc.id = ib.retrieval_config_version_id
                             where ib.project_id=:p and ib.id=:i"""),
                    {"p": 项目, "i": 构建id}).mappings().first()
    if not b:
        raise 检索不了(f"没有这个索引构建:{构建id}")
    if b["status"] != "已就绪":
        # **不在没建好的索引上检索。** 那会返回一批不完整的结果,
        # 而「索引只建了一半」和「知识库里就这么点」在界面上长得一样。
        raise 检索不了(f"索引还不是「已就绪」,现在是「{b['status']}」—— "
                     f"**不在没建好的索引上检索**:结果会不完整,"
                     f"而那和「知识库里就这么点」长得一样")

    配置 = dict(recall_modes=b["recall_modes"], candidate_k=b["candidate_k"],
              fusion=b["fusion"], rerank=b["rerank"],
              context_budget_tokens=b["context_budget_tokens"],
              final_chunk_limit=b["final_chunk_limit"])
    问题们 = IP.校验检索配置(配置)
    if 问题们:
        raise 检索不了(f"检索配置不合格:{问题们}")
    模式 = list(配置["recall_modes"] or [])
    没做的 = [m for m in 模式 if m != "vector"]
    if 没做的:
        # **不静默退化成只走向量。** 那会让人以为融合在生效。
        raise 检索不了(
            f"配置里要了 {没做的},而这一版**只做了 vector** —— "
            f"不静默退化成只走向量:那会让人以为融合在生效。"
            f"要么把 `recall_modes` 改成 ['vector'],要么先实现关键词召回")

    EMB = AD.选(b["embedding_model_id"], 期望维度=b["embedding_dim"])

    # ── 查询改写(§9.5)· 业务 2026-10-08 拍:调模型改写 ──────────────
    # ⚠️ **改写失败降级成原问,但要说出来。**
    # > 一次「改写认为原问就是最好的」和一次「改写根本没跑成」,
    # > **在 `改写 is None` 上长得一模一样** —— 所以这两种用不同的说明。
    # 和精排不同:精排失败时排序不可靠所以抛;改写失败时用原问仍然检索得到。
    改写后, 改写说明, 改写了吗 = 问题, None, False
    try:
        改写后, _why = RW.改写(问题)
        改写了吗 = True
        改写说明 = f"调模型改写(temperature=0):{_why}"
    except RW.改写失败 as e:
        # ⚠️ **不静默** —— 降级这件事本身要出现在链路里
        改写说明 = (f"**改写没跑成,用的是原问** —— {str(e)[:160]}。"
                 f"召回可能因此变差,而这不是「改写认为原问最好」")
    except Exception as e:
        改写说明 = (f"**改写那一步炸了,用的是原问** —— "
                 f"{type(e).__name__}: {str(e)[:140]}")

    # ⚠️ `用途="查询"` —— BGE 非对称:查询加前缀、文档不加,搞错不报错
    q = EMB.算([改写后], 用途="查询")[0]

    # ── 权限:**检索前**过滤,不是召回后再筛 ─────────────────────────
    # 口径唯一源头在 `语料可见.where片段()`,它和纯判定由
    # `tests/orchestration/test_corpus_visible.py` 第 ⑥ 节对账(72 组合)。
    # ⚠️ 为什么必须是检索前:
    # > 一次「召回 10 条、丢掉 8 条、剩 2 条」和一次「库里本来就只有 2 条相关的」,
    # > 在那 2 条结果上长得一模一样 —— 用户和模型都看不出自己被过滤了。
    # 而更坏的后果是 top-k 被权限吃掉、模型上下文变少、答得更差,
    # **表现是「这个 RAG 不准」,没人会去查是权限吃掉了召回**。
    权限片段, 权限参 = KV.where片段(这个人的角色们=这个人的角色们)
    候选们 = conn.execute(text(f"""
        select ch.id, ch.text, ch.section_path, ch.ordinal, ch.text_hash,
               ch.token_count, ch.document_version_id,
               1 - (e.embedding <=> cast(:v as vector)) as 相似度
          from index_members im
          join chunks ch on ch.project_id = im.project_id and ch.id = im.chunk_id
          join embeddings e on e.project_id = im.project_id
                           and e.id = im.embedding_id
          join document_versions dv on dv.project_id = ch.project_id
                                   and dv.id = ch.document_version_id
          join documents d on d.project_id = dv.project_id
                          and d.id = dv.document_id
          join knowledge_bases kb on kb.project_id = d.project_id
                                 and kb.id = d.knowledge_base_id
         where im.project_id = :p and im.index_build_id = :b
           and d.disabled_at is null
           and {权限片段}
         order by e.embedding <=> cast(:v as vector)
         limit :k
    """), {"v": EMB.成SQL文本(q["向量"]), "p": 项目, "b": 构建id,
           "k": 配置["candidate_k"], **权限参}).mappings().all()
    候选 = [dict(x) for x in 候选们]
    if not 候选:
        # ⚠️ **这里必须分两种,不能合成一句。** 加了权限过滤之后:
        # > 一次「索引坏了」和一次「这个人一条都没权限看」,
        # > **在那个空候选上长得一模一样** —— 而前者要去查谁写了坏数据,
        # > 后者是完全正常的权限结果,去查数据是白费功夫。
        # 所以再查一次**不带权限过滤**的成员数来区分。
        有成员 = conn.execute(text("""
            select 1 from index_members im
             where im.project_id = :p and im.index_build_id = :b limit 1
        """), {"p": 项目, "b": 构建id}).first()
        if 有成员:
            raise 检索不了(
                f"这个索引里的语料**你一条都看不到** —— 不是索引的问题"
                f"(它有成员),是你的角色 {sorted(set(这个人的角色们))} "
                f"不在这些文档的可见范围里。要查为什么,看那个知识库的 "
                f"`acl` 和各文档的 `acl_override`(口径在 `语料可见`)")
        # 索引已就绪但一个成员都没有 —— 那本该在构建时被
        # `INDEX_INCOMPLETE` 拦住。走到这儿说明有别的路径写了坏数据。
        raise 检索不了(
            f"索引 {构建id} 是「已就绪」但一个成员都查不到 —— "
            f"这本该在构建时被 INDEX_INCOMPLETE 拦住,**去查是谁写的**")

    链 = dict(
        原问=问题,
        # ⚠️ **None 而不是空字符串** ——「没做」和「改写结果是空」要分得开。
        # 2026-10-08 起它真的做了:改写成功时这里是模型给的那句话;
        # 改写失败时仍是 None,而 `改写说明` 会写明「没跑成」——
        # 两种 None 靠说明文字分开。
        改写=(改写后 if 改写了吗 else None),
        改写说明=改写说明,
        召回方式=模式,
        候选=[dict(id=c["id"], 相似度=round(c["相似度"], 4),
                 证据=证据串(c), 文=c["text"][:200]) for c in 候选],
        召回数=len(候选),
        embedding=dict(模型=b["embedding_model_id"], 维度=b["embedding_dim"],
                       是mock=q["是mock"], 适配器版本=q["适配器版本"]),
        检索器版本=检索器版本,
    )

    # ── 精排 ────────────────────────────────────────────────────────
    if not 要精排:
        # 形状和精排那支一致 —— 否则前端要分两种情况处理,而那是漏判的入口
        排好 = [dict(**c, 分数=None, 引文=None, 引文可信=None, 引文问题=None,
                   没参与精排=None) for c in 候选]
        链["精排"] = dict(做了=False,
                       为什么="调用方传了 `要精排=False` —— "
                             "⚠️ 只走向量的排序**不可靠**:实测一个表格头"
                             "排到了第 1 名(0.6849),而真答案第 2(0.6329)")
    else:
        出 = RR.精排(问题, [dict(id=c["id"], text=c["text"],
                              section_path=c["section_path"],
                              ordinal=c["ordinal"]) for c in 候选])
        分表 = {x["id"]: x for x in 出["排好的"]}
        # ⚠️ **`引文可信` 必须带出来。**
        # `reranker.校验打分()` 会把「引文在片段里找不到」的那几条标记成
        # `引文可信=False`(单条标记、超 1/3 才失败)——
        # 而我第一版在这儿组装时**没把这个字段传出去**,于是
        # 判据标记了它,界面永远看不到。
        # **一个标记了却传不出去的判据,等于没有判据。**
        排好 = [dict(**c, 分数=分表[c["id"]]["分数"], 引文=分表[c["id"]]["引文"],
                   引文可信=分表[c["id"]].get("引文可信", True),
                   引文问题=分表[c["id"]].get("引文问题"),
                   没参与精排=分表[c["id"]].get("没参与精排", False))
              for c in 候选]
        # ⚠️ 没参与精排的排在**所有精排过的后面**(按向量分),而不是当成 0 分 ——
        # 「没排过」和「排了但不相关」是两件事。
        排好.sort(key=lambda x: (0 if not 分表[x["id"]].get("没参与精排") else 1,
                              -(x["分数"] or 0), -x["相似度"]))
        链["精排"] = dict(做了=True, 模型=出["模型"], 用量=出["用量"],
                       精排器版本=出["精排器版本"], 是mock=出["是mock"],
                       精排了几条=出.get("精排了几条"),
                       没参与精排的=出.get("没参与精排的"),
                       精排上限=出.get("精排上限"))
        if 出.get("没参与精排的"):
            链["精排"]["说明"] = (
                f"召回了 {len(候选)} 条,而精排一次最多 {出.get('精排上限')} 条 —— "
                f"**{出['没参与精排的']} 条没参与精排**,它们按向量分排在后面。"
                f"读 50 条 × 600 字又贵又慢(实测输出要 6000+ token),"
                f"而收益在前几十条就饱和了")

    # ── 截断:**两个上限都要,取更严的那个** ──────────────────────────
    # `final_chunk_limit` 管条数,`context_budget_tokens` 管总量。
    # 只看条数会在片段特别长时爆预算;只看预算会在片段特别短时塞太多条。
    限条 = 配置["final_chunk_limit"]
    限token = 配置["context_budget_tokens"]
    选中, 累计, 跳过的 = [], 0, []
    截断原因 = None
    for x in 排好:
        if len(选中) >= 限条:
            截断原因 = f"到条数上限 {限条}(final_chunk_limit)"
            break
        t = x["token_count"] or int(len(x["text"]) * _每字token)
        if 累计 + t > 限token:
            # ⚠️ **跳过它继续看后面的,不 break。**
            #
            # 上一版这里是 `break` —— 遇到第一个放不下的就停。而按相关性排序时
            # **第 1 名恰好是个长片段是很常见的**:实测 260 token 的预算下,
            # 第 1 名 327 token 放不下 → 整个循环立刻退出 → **选了 0 片**,
            # 尽管后面有 55 token 的能放。
            #
            # `break` 和 `continue` 的差别是「遇到放不下的就停」和
            # 「跳过它继续」—— 前者会因为**一个**大片段丢掉后面**所有**能放的。
            #
            # ⚠️⚠️ 但跳过**必须报出来**(下面 `因为太大跳过的`):
            # 「最相关的那条因为太大没进去」会静默发生,
            # 而人看到的是一组**看起来正常**的结果。
            跳过的.append(dict(id=x["id"], token=t, 证据=证据串(x),
                            分数=x["分数"], 相似度=round(x["相似度"], 4)))
            截断原因 = (f"到上下文预算 {限token}(context_budget_tokens),"
                     f"已用 {累计};有 {len(跳过的)} 片因为太大被跳过")
            continue
        选中.append(x)
        累计 += t

    # ⚠️ **一片都放不进去 → 当场报,不返回一个空结果。**
    #
    # 「检索返回 0 片」和「知识库里没有相关内容」在界面上**长得一模一样**。
    # 而候选是按向量取的、这里已经确认非空,所以选片为 0 **一定**是预算配置问题,
    # 不可能是「没有相关内容」—— 那就不该让它看起来像后者。
    #
    # (这是测试跑出来的:`预算=100 / 限片=4` 合法通过了配置校验
    #  (100 ≥ 4×20),但真片段平均 92 token、最大 327,第一片就放不下。
    #  `校验检索配置` 那条 `预算 < 限片×20` 是个**静态下限**,
    #  它看不到片段的实际长度。)
    if not 选中:
        最小片 = min((x["token_count"] or int(len(x["text"]) * _每字token))
                   for x in 排好)
        raise 检索不了(
            f"上下文预算 {限token} token **一片都放不下**"
            f"(候选里最小的那片 {最小片} token,而全部 {len(排好)} 片都超了)"
            f"—— 检索会返回空,"
            f"而「返回空」和「知识库里没有」在界面上长得一样。\n"
            f"       把 `context_budget_tokens` 调到至少 {最小片 * 2} 左右,"
            f"或者把片段切小一点。\n"
            f"       ⚠️ `校验检索配置` 的 `预算 < 限片×20` 是**静态下限**,"
            f"它看不到片段的实际长度 —— 所以配置能通过校验而这里仍然放不下")

    链["选片"] = [dict(id=x["id"], 相似度=round(x["相似度"], 4), 分数=x["分数"],
                    引文=x["引文"], 引文可信=x["引文可信"], 引文问题=x["引文问题"],
                    没参与精排=x["没参与精排"],
                    证据=证据串(x), 文=x["text"]) for x in 选中]
    # 汇总一条给界面用:**有几条引文没通过校验**。
    # 不汇总的话,人得逐条看才知道「这批结果里有几条的理由是不可信的」。
    不可信 = [x for x in 选中 if x["引文可信"] is False]
    链["引文没通过校验的"] = len(不可信)
    if 不可信:
        链["引文说明"] = (
            f"{len(不可信)} 条的引文在片段里找不到(模型改写了原话)—— "
            f"**那几条的分数仍然保留,但它给的理由不可信**。"
            f"界面上要能看出是哪几条")
    链["选了几片"] = len(选中)
    # ⚠️ 被跳过的要在链里**看得见** —— 见上面那段。
    链["因为太大跳过的"] = 跳过的
    if 跳过的:
        链["跳过说明"] = (
            f"{len(跳过的)} 片因为放不进剩余预算被跳过,**其中可能有最相关的那条** "
            f"(最大 {max(x['token'] for x in 跳过的)} token)。"
            f"要它们进来就调大 `context_budget_tokens`,或者把片段切小")
    链["用了多少token"] = 累计
    链["token是粗估"] = True          # ⚠️ **不许拿它算钱**
    # ⚠️ 截断要**说出来**。静默截断的后果是:被截掉的那几段和没检索到长得一样。
    链["截断"] = 截断原因 or "没截断(全部选中的都放进去了)"
    return 链
