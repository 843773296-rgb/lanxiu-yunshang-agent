#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLAlchemy 表定义 —— **从契约登记表派生,不手写**。

## 为什么不手写模型

手写一遍 36 张表的后果不是抄错,是**它会和契约分家**,而分家时两边都能建表成功。
所以这里只做一件事:把 `contract/entities.py` 的登记翻译成 SQLAlchemy Table。
改表请改契约。

## 两条落成结构的规矩

① **跨对象引用用含项目范围的复合外键。**
   规格 §18:「跨对象引用使用包含项目/组织范围的外键或等效约束;
   **仅靠前端传 project_id 不够**」。
   所以项目级表的主键是 `(project_id, id)`,外键也是复合的 ——
   这样「拿 A 项目的 ID 去 B 项目下引用」在**数据库层**就不成立,
   而不是靠每个 handler 记得检查。

   > 一道靠「每个人都记得检查」成立的边界,等于没有边界。

② **只追加的表不给 UPDATE 留位置。**
   审计/Trace/用量/任务事件没有 `revision` 也没有 `archived_at` ——
   字段都不存在,改它就得先改表(而改表会被看见)。
   规格 §15.4:「审计追加写入,不允许普通编辑删除」。
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
import entities as EN, fieldtypes as FT

from sqlalchemy import (Date, MetaData, Table, Column, Text, Integer, BigInteger, Boolean,
                        Numeric, TIMESTAMP, Index, UniqueConstraint,
                        ForeignKeyConstraint, PrimaryKeyConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType

metadata = MetaData()

class _向量(UserDefinedType):
    """pgvector 的 `vector(n)`。**故意不 import pgvector 那个包。**

    CI 的 `admin` job 只装 sqlalchemy(实测 0.24 秒跑完 93 条契约检查),
    契约层多一个依赖就会让它在 CI 里直接炸。
    而契约层的职责是**说清结构** —— 说清「这一列是 1536 维向量」
    不需要一个能算向量的库。

    ⚠️ 维度写在类型里是有意的:插错维度**当场报错**。
    无维度的 `vector` 列允许 3 维和 4 维躺在同一张表里(量过,一声不响),
    而混维度的索引算出来的距离没有意义 —— 那是不报错的那种坏。
    """

    cache_ok = True

    def __init__(self, 维度):
        if not isinstance(维度, int) or isinstance(维度, bool) or 维度 <= 0:
            raise ValueError(f"向量维度要是正整数,给的是 {维度!r} —— "
                             f"**不许缺省**:没有维度的 vector 列建不了索引,"
                             f"而且允许混维度")
        self.维度 = 维度

    def get_col_spec(self, **kw):
        return f"vector({self.维度})"


_映 = {
    "VECTOR(512)": lambda: _向量(512),
    "TEXT": lambda: Text(),
    "INTEGER": lambda: Integer(),
    "BIGINT": lambda: BigInteger(),
    "BOOLEAN": lambda: Boolean(),
    "JSONB": lambda: JSONB(),
    "NUMERIC(20,6)": lambda: Numeric(20, 6),
    "TIMESTAMPTZ": lambda: TIMESTAMP(timezone=True),
    # ⚠️ **DATE 不是 TIMESTAMPTZ。** 2026-09-28 为 `usage_ledger.world_date` 加的:
    # 那是演示世界里的**日历日**,不是某个时刻。用 timestamp 存会让它带上一个
    # 无意义的 00:00:00,而那个零点看起来像真的时刻 ——
    # **一个假装自己有精度的值,比一个粗一点的值危险。**
    "DATE": lambda: Date(),
}


def _列(字段, 范围内=False, 表=None):
    t = FT.类型(字段)                      # 认不出会抛 —— **不兜底**
    if t not in _映:
        raise ValueError(f"字段 {字段} 的类型 {t} 还没接到 SQLAlchemy —— "
                         f"**不猜一个近似的**:猜错的类型建表照样成功")
    # ⚠️ **`可空` 要带上表名。** 有些列只在某张表上必填
    # (`status` 在 `deployments` 上必填,在别的表上可以为空)——
    # 漏传 `表` 的表现是那几列**又变回可空**,而建表照样成功,
    # 只是 `alembic check` 会永久报漂移,而**一个永久报漂移的检查等于没有检查**。
    return Column(字段, _映[t](), nullable=FT.可空(字段, 范围内, 表=表))


# 规格 §18「索引建议」那一段,落成代码。
#
# ## ⚠️ 项目范围内的唯一约束**必须带上 project_id**
#
# 第一版这里写的是 `"prompt_versions": [("key", "content_hash")]` —— 没带 project_id。
# 而项目级表的主键是 `(project_id, id)`:**id 只在项目内唯一**。
# 于是那条约束悄悄变成了一条**跨项目**的约束:
# A 项目冻结了一条内容为 X 的 Prompt,B 项目再冻结一份一模一样的就撞唯一键 ——
# 报错里还带着另一个项目的那一行,**连「那份内容存在」都泄露了**。
#
# 这类漏是复合主键的连带后果,而且它**不报错**:同一个项目里跑测试永远撞不到。
# 规矩:**凡是拿 id / key 做唯一键的,都要先带 project_id**;
# 例外只有供应商给的全局 ID(`external_id`)—— 那个本来就是全局唯一的,
# 带上 project_id 反而会放过「两个项目登记同一个外部任务」。
# 判据落在 tools/spec_coverage.py 的「项目内的唯一约束都带了 project_id」那条,
# 豁免数量有写死的上限。
# ── 依赖 → 用哪个列建外键:**点名,因为推不出来** ────────────────────────
# 外键默认从依赖表名推列名(`model_connections` → `model_connection_id`)。
# 推不出来的两种情况:
#   ① **同一个列名指向两张不同的父表** —— `connection_id` 在
#      `tool_versions` 指 capability_connections、在 `connection_versions`
#      指 model_connections。靠列名永远分不开,只能点名。
#   ② 引用存在 JSONB 里(`definition_ref` / `release_ref` /
#      `member_manifest`)—— 那种加不了外键,靠冻结时的服务端校验,
#      理由写在 `tools/fk_dep_check.py` 的豁免表里。
#
# ⚠️ ① 这两处 2026-10-02 之前**一直没有外键**,而 entities 里依赖是声明着的。
# > 「我声明了依赖所以有外键」和「我声明了依赖但列名推不出来所以没外键」,
# > **在登记表上长得一模一样。**
_依赖列 = {
    ("tool_versions", "capability_connections"): "connection_id",
    ("connection_versions", "model_connections"): "connection_id",
    # ⚠️ ② 2026-10-03 加的两处。筛选策略版本上那两列是**一名多指**的反面:
    # 列名里没有被依赖表的名字(`router_evidence_ref` 不叫 `evaluation_id`),
    # 所以按表名推列名**推不出来** —— 而推不出来是**静默 continue**。
    # > 「我声明了依赖所以有外键」和「我声明了依赖但列名推不出来所以没外键」,
    # > 在登记表上长得一模一样。
    ("tool_selection_policy_versions", "evaluations"): "router_evidence_ref",
    ("tool_selection_policy_versions", "model_connections"):
        "router_connection_id",
}

# ## 唯一约束叫什么名字 —— **这个名字必须和迁移里那个一个字不差**
#
# 默认是 `uq_{表}_{列}_{列}…`,而 PostgreSQL 的标识符上限是 **63 字符**。
# 2026-10-04 撞上了:
#     uq_execution_policy_versions_project_id_application_id_entry_kind_version_no
#     = 78 字符 → SQLAlchemy 直接抛 IdentifierError
#
# 超长时**不能随便截**,也**不能加随机后缀** —— 这个名字要能被手写进迁移,
# 所以缩短必须是**确定性**的:超过上限就按「去掉每个列名里的 `_` 之后的首字母缩写」
# 兜底,而那个结果对同一组列永远一样。
# > 一个每次算出不同名字的约束,和一个稳定的,**在它建成功那一次上长得一模一样** ——
# > 而下一次 `alembic check` 会说「删掉这个、建那个」。
#
# ⚠️ 兜底的名字也**登记在这儿的注释里**,因为写迁移的人要照抄它:
#     execution_policy_versions + (project_id, application_id, entry_kind,
#     version_no) → `uq_execution_policy_versions_pi_ai_ek_vn`
_上限 = 63


def _唯一名(表, 组):
    长 = f"uq_{表}_{'_'.join(组)}"
    if len(长) <= _上限:
        return 长
    # 确定性缩写:每个列名取各段首字母(project_id → pi)。
    短 = f"uq_{表}_" + "_".join(
        "".join(seg[0] for seg in c.split("_") if seg) for c in 组)
    if len(短) > _上限:
        # 连缩写都超长 —— **抛,不截**。截出来的名字会和另一组列撞上,
        # 而撞名字的两条约束里只有一条建得起来。
        raise ValueError(
            f"唯一约束名 {短!r} 还是超过 {_上限} 字符 —— "
            f"**不截断**(截出来可能和另一组列撞名,而撞名时只有一条建得起来)。"
            f"给 {表} 换个短表名,或者在这儿加一条显式映射")
    return 短


_额外唯一 = {
    # 任务幂等键 —— **防重复训练/重复计费的命根子**。项目内唯一就够:
    # 幂等键是客户端给的,两个项目用同一个字符串是正常的。
    "training_jobs": [("project_id", "idempotency_key"), ("external_id",)],
    "jobs": [("project_id", "idempotency_key")],
    # 费用事件唯一键:唯一用量事件防重复计费
    "usage_ledger": [("project_id", "event_key")],
    # 索引成员:**同一个片段在一个构建里只出现一次。**
    # ⚠️ 这不是防御性编程,是 **Outbox 语义的必要配套** ——
    # `worker.py` 开头就写着「Outbox 的设计**保证**会有重复投递」,
    # 而没有这条约束,重复投递会造出两条同 (build, chunk) 的成员行:
    # `index_plan.算待做()` 会把同一个片段算两次,「陈旧成员」体检也会误报。
    # 有了它,写入才能用 `on conflict do nothing`(PostgreSQL 要求冲突目标
    # **精确匹配**一个唯一约束)。
    "index_members": [("project_id", "index_build_id", "chunk_id")],
    # ── 下面两条是 2026-10-01 补登记的,**补的是两条真约束差点被删掉** ─────
    #
    # 09-29 我手写迁移时**在库里建了这两条唯一约束,而没在这儿登记** ——
    # 于是 `alembic check` 一直红,而 10-01 我拿 `alembic revision --autogenerate`
    # 去对齐时,它生成的迁移**要把这两条删掉**(因为模型里没有它们)。
    #
    # > **autogenerate 做的是「让库跟上模型」—— 模型漏声明的时候,
    # > 它会安静地删掉一条真约束。** 照着跑一遍,库是「对齐」了,
    # > 而幂等和「一个应用只有一份候选」这两件事没了,**一句话都不会报**。
    #
    # `deployments` 的幂等键:`POST /deployments` 先按它查「这次是不是重发」。
    # 没有这条约束,两条同幂等键的部署能同时存在 ——
    # 而那时「这次部署是哪一条」有两个答案,**而且两次都返回成功**。
    "deployments": [("project_id", "idempotency_key")],
    # 一个应用**只有一份候选** —— 这条就是 `entities.py` 里那句
    # 「两份的话『出发布』出的是哪一份?」的落点。
    # 它原来只写在约束说明里,**而说明不建约束**。
    "application_drafts": [("project_id", "application_id")],
    # 向量:同一段文本 + 同一个模型 **只存一份**。
    # 这条约束就是「已完成片段不重复 Embedding」(§19.3)在**跨构建**层面的地基:
    # 检索配置改了要新建构建,但那次新建的向量可以全部复用 —— 一次都不用重跑。
    # ⚠️ 不带 `dim`:维度由 `model_id` 决定,把它放进唯一键等于承认
    # 「同一个模型可以产两种维度」,那正是要防的事。
    "embeddings": [("project_id", "text_hash", "model_id")],
    # 版本内容哈希:同一份内容不该在**同一个项目里**出现两个版本行
    # ⚠️ **两条,不是一条。** content_hash 那条防「同一份内容出现两个版本行」;
    # version_no 这条防「同一个 key 出现两个 v1」—— 后者原来是**缺的**,
    # 于是一段写死 version_no=1 的演示数据安静地造出了两个 v1,
    # 而抓到它的是一条测别的事情的断言(它拿「版本条数」当「最大版本号」的替身)。
    # 「版本号唯一且密集」是一堆地方都在隐含依赖的不变量 —— 依赖它就该钉住它。
    "prompt_versions": [("project_id", "key", "content_hash"),
                        ("project_id", "key", "version_no")],
    "document_versions": [("project_id", "document_id", "content_hash")],
    "dataset_versions": [("project_id", "dataset_id", "content_hash")],
    "release_manifests": [("project_id", "application_id", "content_hash")],
    # 任务事件按 job 内 seq 单调:SSE 续传靠它,重号会让客户端丢事件或重放
    "job_events": [("project_id", "job_id", "seq")],

    # ── 执行上限与防循环域(2026-10-04)──────────────────────────────
    #
    # ⚠️ **这四条是补登记的,而我是照着上面那段注释的原样又踩了一遍。**
    # 我手工把约束写进迁移、没登记在这儿,于是 CI 的 `alembic check` 报
    # `remove_constraint` —— **它想删掉我刚建的那四条真约束**。
    # 而那段教训(09-29 / 10-01 那两条)就躺在上面,离这儿不到 60 行。
    # > autogenerate 做的是「让库跟上模型」—— 模型漏声明的时候,
    # > **它会安静地删掉一条真约束**。
    #
    # 版本号在 (应用, 入口) 内单调:两个 v3 会让「生产引用哪一版」失去意义。
    # ⚠️ 带 `entry_kind` —— 门店 V3 和后台编排是**不同执行入口**(规格 §2.2),
    # 它们各自的版本号序列不该互相挤号。
    "execution_policy_versions": [
        ("project_id", "application_id", "entry_kind", "version_no")],
    # **一个任务一本账,所有 Run 段共享**(规格 §5.1)。
    # 不唯一的话,「重启后又开了一本」和「本来就是两个任务」长得一样 ——
    # 而前者正是规格 §6.3 点名禁止的「恢复时重新初始化成零」。
    "task_budget_ledgers": [("project_id", "task_ref")],
    # 额度追加的幂等键(规格 C45):同一个追加请求发两次,
    # **额度不许累计两份**。和上面 `deployments` / `jobs` 同一个形状。
    "budget_topups": [("project_id", "idempotency_key")],

    # ── Workflow / Agent 编排域 ─────────────────────────────────────
    # 版本号在父对象内单调:两个 v3 会让「生产引用哪一版」这句话失去意义
    "workflow_versions": [("project_id", "workflow_id", "version_no")],
    "agent_versions": [("project_id", "agent_id", "version_no")],
    "tool_versions": [("project_id", "tool_definition_id", "version_no")],
    "skill_versions": [("project_id", "name", "version_no")],
    "policy_versions": [("project_id", "name", "version_no")],
    # **运行事件 seq 在 Run 内单调唯一** —— SSE 按 after_seq 补发靠它(§17.2);
    # 重号会让前端丢事件,而丢掉的恰好可能是那条 tool.approval_required
    "run_events": [("project_id", "execution_run_id", "seq")],
    "run_checkpoints": [("project_id", "execution_run_id", "seq")],
    # **唯一执行键**(§8):(Run, node_id, 循环路径, 列表项, 尝试次数)算出来的键。
    # 它是「同一个节点不被执行两次」在数据库层的落点 —— 不靠调度器记得。
    "run_steps": [("project_id", "execution_key")],
    # **逻辑动作键唯一**(§17.3):传输重试复用同一行,不是插第二行。
    # 这一条唯一约束就是「恢复后不重复写」的地基 —— 没有它,
    # 幂等只存在于代码的 if 里,而进程可以死在那个 if 之前。
    "tool_invocations": [("project_id", "logical_action_id"),
                         ("project_id", "idempotency_key")],
    "execution_runs": [("project_id", "idempotency_key")],
    # **一个 revision 只能有一个决定**(§12.2):两个审批者同时点批准,
    # 第二个撞唯一键 → 返回冲突和最新状态,而不是两条都记下来。
    # 「要求补充」之后 revision 前进,于是下一轮还能再批 —— 这正是想要的。
    "human_decisions": [("project_id", "human_request_id", "request_revision")],
    # 一个对象一份草稿。PostgreSQL 把多个 NULL 当互不相同,所以
    # (project_id, workflow_id) 唯一**不会**妨碍一堆 workflow_id 为空的 agent 草稿。
    "graph_drafts": [("project_id", "workflow_id"), ("project_id", "agent_id")],
}


def _建一张(e):
    名 = e["名"]
    字段 = list(dict.fromkeys(EN.该有的通用字段(e) + e["关键字段"]))
    范围内 = e["范围"] in (EN.项目级, EN.子对象)
    列 = [_列(f, 范围内, 表=名) for f in 字段]
    约束 = []

    # ── 主键:项目范围内的表用 (project_id, id) 复合主键 ────────────
    # 这样外键也能带上项目范围,**跨项目引用在数据库层就不成立**。
    #
    # ⚠️ 判据是 **范围**,不是「字段里有没有 project_id」。第一版按字段判,
    # 于是 memberships 也被拖进了复合主键 —— 而它是组织级的,按设计
    # **允许 project_id 为空**(一个人可以是组织级成员)。主键列不能为空,
    # 于是契约说「可空」、库里却是 NOT NULL,`alembic check` 每次都报漂移。
    # 这是「判据恰好长这样,而不是按含义」的一个实例。
    if e["范围"] in (EN.项目级, EN.子对象):
        约束.append(PrimaryKeyConstraint("project_id", "id", name=f"pk_{名}"))
    else:
        约束.append(PrimaryKeyConstraint("id", name=f"pk_{名}"))
        if 名 == "memberships":
            # 组织级成员:project_id 可空。唯一性按 (组织, 项目, 人) ——
            # PostgreSQL 的唯一约束把多个 NULL 当成互不相同,所以这里
            # **拦不住「同一个人两条组织级成员记录」** —— 那条要靠部分唯一索引,
            # 留给实现权限那一步(§17.4 第 3 步),现在先把话写在这儿。
            约束.append(UniqueConstraint("organization_id", "project_id", "user_id",
                                         name="uq_memberships_org_proj_user"))

    # ── 每张带 project_id 的表,自动挂一条指向 projects 的复合外键 ──
    # ⚠️ **这条不能靠登记表里的「依赖」**。第一版只从 依赖 建外键,结果是:
    # 大多数项目级表根本没有指向 projects 的外键 —— 攻击测试里
    # 「编一个不存在的 project_id」**直接写进去了**。
    # 于是「跨项目引用在数据库层不成立」这句话对大部分表根本不成立,
    # 而表建得好好的,什么都看不出来。
    # 现在改成**结构性的**:带 project_id 就必须能证明这个项目存在、且属于那个组织。
    if 名 not in ("organizations", "projects") and "project_id" in 字段:
        约束.append(ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"],
            name=f"fk_{名}_projects", ondelete="RESTRICT"))
    elif 名 == "projects":
        # 子表要按 (organization_id, id) 引用它,所以这一对必须唯一
        约束.append(UniqueConstraint("organization_id", "id", name="uq_projects_org_id"))

    # ── 外键:能带项目范围的就带 ───────────────────────────────────
    for 父 in e["依赖"]:
        try: 父e = EN.找(父)
        except KeyError: continue
        if 父 == 名: continue                      # 自引用(如清单指向上一版)先不加约束
        # projects 已经被上面那条**自动规则**覆盖了 —— 再从依赖表建一次会撞名字
        # (memberships 同时把 projects 列成依赖,于是生成了两个 fk_memberships_projects)
        if 父 in ("projects", "organizations"): continue
        父字段 = f"{父.rstrip('s')}_id" if not 父.endswith("ies") else 父[:-3] + "y_id"
        # ⚠️ **先查显式映射** —— 见文件末尾 `_依赖列` 那段。
        # 按表名推列名推不出「同一个列名指向两张不同父表」的情况
        # (`connection_id` 在 `tool_versions` 指 capability_connections、
        #  在 `connection_versions` 指 model_connections),
        # 而推不出来的表现是下面那句 `continue` —— **静默不建外键**。
        # 2026-10-02 查出来这两处因此**一直没有外键**(库里实测:
        # 46 行有效引用、0 行坏引用,所以补外键是安全的收紧)。
        # 盯这件事的判据是 `tools/fk_dep_check.py`:
        # 每一处「声明了依赖却没建成外键」都要在那里点名 + 写理由。
        显式 = _依赖列.get((名, 父))
        候选 = ([显式] if 显式 and 显式 in 字段
              else [c for c in (父字段, f"{父[:-1]}_id") if c in 字段])
        if not 候选: continue
        本列 = 候选[0]
        父有项目 = "project_id" in EN.该有的通用字段(父e)
        if 父有项目 and "project_id" in 字段:
            约束.append(ForeignKeyConstraint(
                ["project_id", 本列], [f"{父}.project_id", f"{父}.id"],
                name=f"fk_{名}_{父}", ondelete="RESTRICT"))
        else:
            约束.append(ForeignKeyConstraint(
                [本列], [f"{父}.id"], name=f"fk_{名}_{父}", ondelete="RESTRICT"))

    for 组 in _额外唯一.get(名, []):
        if all(c in 字段 for c in 组):
            约束.append(UniqueConstraint(*组, name=_唯一名(名, 组)))

    t = Table(名, metadata, *列, *约束)

    # ── 索引(规格 §18「索引建议」)──────────────────────────────────
    if "project_id" in 字段 and "updated_at" in 字段:
        Index(f"ix_{名}_proj_updated", t.c.project_id, t.c.updated_at.desc())
    if "project_id" in 字段 and "status" in 字段:
        Index(f"ix_{名}_proj_status", t.c.project_id, t.c.status)
    if 名 == "traces":
        # Trace 时间 + 应用:排查问题总是「这个应用最近出了什么事」
        Index("ix_traces_started_app", t.c.started_at.desc(), t.c.application_id)
    if "content_hash" in 字段:
        Index(f"ix_{名}_hash", t.c.content_hash)
    if 名 == "index_builds":
        # 「这份输入有没有构建过」—— 续做判定(§19.3)的主查询走它。
        # ⚠️ 这条**必须和迁移里那条同名同列**:少声明它,`alembic check` 会说
        # 「检测到新的 remove_index」—— 那是好的红,它逼着契约和迁移对齐。
        # (2026-09-27 就是这么红的一次:我在迁移里建了索引,契约里忘了声明。)
        Index("ix_index_builds_proj_kb_input", t.c.project_id,
              t.c.knowledge_base_id, t.c.input_hash)
    # ⚠️ 下面两条同样是**补登记的**(2026-10-04),原因和 `_额外唯一` 末尾那段一样:
    # 我在迁移里建了索引、这儿忘了声明,`alembic check` 就报 `remove_index`。
    # 这个文件里**同一个坑记了两次**(09-27 索引、10-01 约束),而我是第三次。
    if 名 == "policy_instance_receipts":
        # 「这个实例最近报的是哪一版」—— 策略解析每次都要查它,
        # 而它还要按 `loaded_at` 算回执年龄(规格 §10.2 的「过期回执标陈旧」)。
        Index("ix_receipt_by_instance", t.c.project_id, t.c.instance_ref,
              t.c.loaded_at)
    if 名 == "traces":
        # 「这个任务的所有 Run 段」—— 预算账本按任务共享,
        # 查「这一本账被哪几段用过」走它。
        Index("ix_traces_task", t.c.project_id, t.c.task_ref)
    return t


# 建表顺序按依赖拓扑 —— 外键要求父表先存在
def _排序():
    剩, 出, 已 = list(EN.实体表), [], set()
    while 剩:
        动 = False
        for e in list(剩):
            if all(d in 已 or d == e["名"] for d in e["依赖"]):
                出.append(e); 已.add(e["名"]); 剩.remove(e); 动 = True
        if not 动:
            # **环要当场报出来**,不许静默按原顺序建 —— 那样只会在建表时炸一个
            # 看不懂的外键错误,而真正的问题是依赖成环
            raise ValueError(f"实体依赖成环,建不出来:{[e['名'] for e in 剩]}")
    return 出


表们 = {e["名"]: _建一张(e) for e in _排序()}


def 概况():
    return dict(表数=len(表们),
                列数=sum(len(t.columns) for t in 表们.values()),
                外键数=sum(len(t.foreign_key_constraints) for t in 表们.values()),
                唯一约束数=sum(1 for t in 表们.values() for c in t.constraints
                              if c.__class__.__name__ == "UniqueConstraint"),
                索引数=len(metadata.info.get("_", [])) or sum(len(t.indexes) for t in 表们.values()))
