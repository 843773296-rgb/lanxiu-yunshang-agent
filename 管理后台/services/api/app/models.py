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

from sqlalchemy import (MetaData, Table, Column, Text, Integer, BigInteger, Boolean,
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
}


def _列(字段, 范围内=False):
    t = FT.类型(字段)                      # 认不出会抛 —— **不兜底**
    if t not in _映:
        raise ValueError(f"字段 {字段} 的类型 {t} 还没接到 SQLAlchemy —— "
                         f"**不猜一个近似的**:猜错的类型建表照样成功")
    return Column(字段, _映[t](), nullable=FT.可空(字段, 范围内))


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
    列 = [_列(f, 范围内) for f in 字段]
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
        # 只在这张表真的有那个列时才建外键 —— 登记表里字段名各异,不硬凑
        候选 = [c for c in (父字段, f"{父[:-1]}_id") if c in 字段]
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
            约束.append(UniqueConstraint(*组, name=f"uq_{名}_{'_'.join(组)}"))

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
