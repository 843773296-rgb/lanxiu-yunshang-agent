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

metadata = MetaData()

_映 = {
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
_额外唯一 = {
    # 任务外部 ID 唯一 + 幂等键唯一 —— **这两条是防重复训练/重复计费的命根子**
    "training_jobs": [("idempotency_key",), ("external_id",)],
    "jobs": [("idempotency_key",)],
    # 费用事件唯一键:唯一用量事件防重复计费
    "usage_ledger": [("event_key",)],
    # 版本内容哈希:同一份内容不该出现两个版本行
    "prompt_versions": [("key", "content_hash")],
    "document_versions": [("document_id", "content_hash")],
    "dataset_versions": [("dataset_id", "content_hash")],
    "release_manifests": [("application_id", "content_hash")],
    # 任务事件按 job 内 seq 单调:SSE 续传靠它,重号会让客户端丢事件或重放
    "job_events": [("job_id", "seq")],
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
