#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把澜绣在跑的工具导进后台的工具目录 —— **选型卡方案 A**(业务 10-02 拍板)。

## 为什么要有它

后台的工具目录里原来只有 **2 个演示工具**(搜索 / 写报告),
而澜绣 V3 实际在跑 **81 个**。

> **一个在 2 个工具上做的筛选器,它的召回率永远是 100%** —— 而那个数字毫无意义。

所以「工具筛选」这块真正的第一步不是写检索算法,是**让后台管上真工具**。

## 导出口在哪(卡里估错了一件事)

选型卡写「MCP 那三个服务器是裸手写 JSON-RPC,没有统一导出口」——
**那句话不对**。`mcp/kb_server.py` 只有一行:

    TOOLS = [(s["name"], s["description"], s["input_schema"], api.TOOLS[s["name"]])
             for s in api.KB_SCHEMAS]

真正的工具面在 `backend/api.py` 的三个 schema 列表里:
`SCHEMAS`(5) + `SHOP_SCHEMAS`(66) + `KB_SCHEMAS`(10) = **81 个**,
每个都带 name / description / input_schema。**那就是现成的导出口**,
所以方案 A 的工作量比卡里估的小得多。

## 副作用分级:**只读有硬依据,「不可逆」没有 —— 所以不猜**

| 档 | 依据 | 契约要求什么 |
|---|---|---|
| `read_only` | **不在 `api.WRITE_TOOLS` 里** —— 硬依据 | 无 |
| `write` | 在 `WRITE_TOOLS` 里 | 幂等键 + 外部状态查询 |
| `irreversible` | **没有现成依据** | 以上 + **人工确认** |

`dsl.py` 对「不可逆」的定义是「发消息、转账、删除这一类」,
而 24 个会写的工具里,我**说得出依据**的只有两个:

- `start_cutting` —— 工具说明的原话:「**云锦缂丝裁下去没有回头路**」
- `confirm_order` —— 业务 09-22:「**定制单确认即已付款**」

其余 22 个要业务判断。而两个方向的代价不对称、**都真**:

- 猜成 `write` → 真不可逆的那个**不要求确认**,后台的闸放过它
- 全标 `irreversible` → 24 个每次都要人点确认,而**人烦了就会开始乱点确认**

所以这个脚本**不给默认值**:会写的工具如果在 `不可逆口径` 里查不到,
它**拒导那一条并点名**。(「判不了就说判不了」。)

⚠️ 口径文件是 `docs/口径/工具不可逆口径.json`,格式
`{"不可逆": [...], "可撤": [...], "拍板日期": "...", "依据": "..."}` ——
**两边都要列全**,不许只列一边:只列「不可逆」的话,
新加一个工具会**静默落进「可撤」**,而那正是危险的那一边。

## 幂等

照 `import_lanxiu_prompts.py`:**内容哈希**。只有哈希变了才出新版本。
而**风险变大必须出新版本**(契约 §16.3):一个工具从只读变成会写,
而引用它的 Agent 还指着老的说明 —— **那份说明现在是错的**。
"""
import argparse
import hashlib
import json
import os
import sys
import uuid

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(_这)
仓库 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(仓库, "backend"))

口径文件 = os.path.join(根, "docs", "口径", "工具不可逆口径.json")


def 读工具面():
    """三个 schema 列表 → {名: (说明, 入参schema, 哪个服务)}。

    ⚠️ **哪个服务也要记**:`mcp/` 下三个服务器各取一份列表,
    而「这个工具挂在哪个 MCP 服务上」是后台 `adapter` 那一列该写的东西。
    写成一个笼统的 "lanxiu" 的话,**出问题时查不到是哪个服务**。
    """
    import api
    出 = {}
    for 列表名, 服务 in (("SCHEMAS", "lanxiu-task"),
                      ("SHOP_SCHEMAS", "lanxiu-shop"),
                      ("KB_SCHEMAS", "lanxiu-kb")):
        for s in getattr(api, 列表名):
            n = s["name"]
            if n in 出:
                # ⚠️ 同一个工具出现在两个列表里 —— **不静默取后一个**。
                # 那会让 adapter 那一列取决于循环顺序,而两次导入可能不一样。
                raise SystemExit(
                    f"❌ 工具 `{n}` 同时在 {出[n][2]} 和 {服务} 的列表里 —— "
                    f"**不静默取后一个**:那会让「它挂在哪个服务上」取决于循环顺序。"
                    f"先在 api.py 里定清楚它属于谁。")
            出[n] = (s["description"], s.get("input_schema") or {}, 服务)
    return 出


def 读口径():
    """读「哪几个是不可逆」。返回 (不可逆集合, 可撤集合, 元信息)。

    没有这个文件就返回三个空的 —— 调用方会因此拒导全部会写工具并点名。
    """
    if not os.path.exists(口径文件):
        return set(), set(), {}
    d = json.load(open(口径文件, encoding="utf-8"))
    return set(d.get("不可逆") or []), set(d.get("可撤") or []), d


def 分级(名, 写们, 不可逆, 可撤):
    """→ (档位, 为什么) 或 (None, 为什么判不了)。"""
    import dsl as DSL
    if 名 not in 写们:
        return DSL.只读, "不在 api.WRITE_TOOLS 里"
    if 名 in 不可逆 and 名 in 可撤:
        return None, "口径文件里**两边都列了它** —— 先在那份文件里定清楚"
    if 名 in 不可逆:
        return DSL.不可逆, "口径文件点名的"
    if 名 in 可撤:
        return DSL.写入, "口径文件点名「可撤」"
    return None, ("会写,而口径文件里**两边都没列它** —— "
                  "**不给默认值**:猜成「可撤」会让后台的闸不要求确认")


def 包一版(名, 说明, 入参, 服务, 档, 为什么):
    """一个工具 → tool_versions 的那一行该填什么。

    ⚠️ **按档位填契约要求的那几样,不是一律填满**。`dsl.副作用表` 写着:
    只读无要求;写入要幂等键 + 外部状态查询;不可逆再加人工确认。
    一律填满的话,只读工具上会出现一条没有意义的确认策略 ——
    **而那会让「哪些工具真要确认」看不出来**。
    """
    import dsl as DSL
    要 = DSL.找副作用(档)          # 认不出就抛,不兜底
    v = dict(
        model_description=说明,
        input_schema=入参,
        # ⚠️ **输出 schema 留空,不编一个。** MCP 那边没有声明输出形状,
        # 编一个出来会让「后台说它返回什么」和「它真返回什么」分家,
        # 而那种不一致在界面上看不出来。
        output_schema=None,
        side_effect_type=档,
        allowed_scopes=["project"],
        confirmation_policy=(
            {"谁批": "approver",
             "为什么": f"不可逆写入 —— 批准绑定参数摘要(§12.2);依据:{为什么}"}
            if 要["需确认"] else None),
        idempotency_strategy=({"键": "logical_action_id"} if 要["需幂等"] else None),
        external_status_lookup=(
            {"怎么查": "调同名只读工具复核(澜绣侧没有独立的状态查询接口)",
             "⚠️": "**这是声明,不是实现** —— 真要 exactly-once 得澜绣那边补一个查询口"}
            if 要["需外部查询"] else None),
        timeout_seconds=30,
        retry_policy=({"最多重试": 0,
                       "为什么": "写工具不盲重试 —— 超时不代表对方没做事(§8)"}
                      if 档 != DSL.只读 else {"最多重试": 2}),
        # ⚠️ 脱敏:澜绣的工具返回里有**手机号和地址**(`get_customer` 的说明
        # 自己写着「已脱敏」)。这里只声明**形状**,不声明「已经做了」——
        # 真正的脱敏在澜绣那一侧,后台只是记下该脱哪些。
        redaction={"要脱敏的字段": ["phone", "address", "手机号", "地址"],
                   "⚠️": "声明在后台,**落点在澜绣的 api.py** —— 两处不一致时以澜绣为准"},
        secret_ref=None,
        connection_id=None,
        server_bound_arguments={"project_id": "由服务端绑定,模型参数不许覆盖"},
        # ⚠️ **pollable 要显式声明**(契约):只读的可轮询;
        # 写的不可 —— 「调用两次就算无进展」会把正常轮询判成失控,
        # 而反过来不声明就默认可轮询也会放过真的失控。
        pollable=(档 == DSL.只读),
    )
    return v


def 哈希(定义, 版本):
    料 = json.dumps({"定义": 定义, "版本": 版本}, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(料.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--项目", required=True,
                    help="必须点名 —— 导错项目的工具目录,在列表上和导对了长得一样")
    ap.add_argument("--看", action="store_true", help="只看不写")
    a = ap.parse_args()

    import api
    import dsl as DSL
    工具面 = 读工具面()
    写们 = set(getattr(api, "WRITE_TOOLS", ()))
    不可逆, 可撤, 元 = 读口径()

    计划, 判不了 = [], []
    for 名 in sorted(工具面):
        说明, 入参, 服务 = 工具面[名]
        档, why = 分级(名, 写们, 不可逆, 可撤)
        if 档 is None:
            判不了.append((名, why)); continue
        计划.append((名, 说明, 入参, 服务, 档, why))

    按档 = {}
    for x in 计划: 按档[x[4]] = 按档.get(x[4], 0) + 1
    print("澜绣工具 → 后台工具目录")
    print("=" * 84)
    print(f"  工具面 {len(工具面)} 个(task {sum(1 for v in 工具面.values() if v[2]=='lanxiu-task')}"
          f" / shop {sum(1 for v in 工具面.values() if v[2]=='lanxiu-shop')}"
          f" / kb {sum(1 for v in 工具面.values() if v[2]=='lanxiu-kb')})")
    print(f"  会写的 {len(写们)} 个(api.WRITE_TOOLS)")
    for d in (DSL.只读, DSL.写入, DSL.不可逆):
        if 按档.get(d): print(f"    {DSL.找副作用(d)['中文']:8s} {按档[d]:3d} 个")
    if 判不了:
        print(f"\n  ⏸  这 {len(判不了)} 个**判不了,不导**:")
        for 名, why in 判不了[:6]:
            print(f"     · {名}")
        if len(判不了) > 6: print(f"     …… 还有 {len(判不了)-6} 个")
        print(f"     {判不了[0][1]}")
        print(f"     口径文件:{os.path.relpath(口径文件, 根)}")
        print(f"     ⚠️ **不给默认值** —— 猜成「可撤」会让后台的闸不要求确认,"
              f"而那是危险的那一边。")
    if not a.看:
        if not 计划:
            print("\n❌ 一个都导不了"); return 1
        n = 写库(a.项目, 计划)
        print(f"\n{n}")
    else:
        print("\n(只看不写。去掉 --看 才真写)")
    return 0


def 写库(项目, 计划):
    from sqlalchemy import text
    from db import 事务
    新增 = 出新版 = 没动 = 0
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        if not org:
            raise SystemExit(f"❌ 没有项目 {项目}")
        for 名, 说明, 入参, 服务, 档, why in 计划:
            定义 = dict(name=名, purpose=说明.strip().splitlines()[0][:200],
                      side_effect_type=档, adapter=服务, owner="lanxiu-import")
            版本 = 包一版(名, 说明, 入参, 服务, 档, why)
            h = 哈希(定义, 版本)
            旧 = c.execute(text("""select id, side_effect_type from tool_definitions
                                  where project_id=:p and name=:n
                                    and archived_at is null"""),
                           {"p": 项目, "n": 名}).mappings().first()
            if not 旧:
                did = "td_" + uuid.uuid4().hex[:16]
                c.execute(text("""insert into tool_definitions
                    (id, organization_id, project_id, name, purpose,
                     side_effect_type, adapter, owner, draft_revision, status,
                     created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:n,:pu,:se,:ad,:ow, 0,'active',
                            now(),'lanxiu-import', now(), 1)"""),
                          {"i": did, "o": org, "p": 项目, "n": 名,
                           "pu": 定义["purpose"], "se": 档, "ad": 服务,
                           "ow": "lanxiu-import"})
                新增 += 1
            else:
                did = 旧["id"]
                if 旧["side_effect_type"] != 档:
                    # ⚠️ **风险变化要出新版本**(契约 §16.3)。定义上那一列也要跟着改,
                    # 否则目录页显示的档位和最新版本的档位会分家。
                    c.execute(text("""update tool_definitions
                        set side_effect_type=:se, updated_at=now(),
                            revision=revision+1
                        where id=:i"""), {"se": 档, "i": did})
            有 = c.execute(text("""select max(version_no) from tool_versions
                                  where tool_definition_id=:d"""),
                           {"d": did}).scalar()
            同 = c.execute(text("""select 1 from tool_versions
                                  where tool_definition_id=:d and content_hash=:h
                                  limit 1"""), {"d": did, "h": h}).scalar()
            if 同:
                没动 += 1; continue
            c.execute(text("""insert into tool_versions
                (id, organization_id, project_id, tool_definition_id, version_no,
                 model_description, input_schema, output_schema, side_effect_type,
                 allowed_scopes, confirmation_policy, idempotency_strategy,
                 external_status_lookup, timeout_seconds, retry_policy, redaction,
                 secret_ref, connection_id, server_bound_arguments, pollable,
                 content_hash, created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d,:v,:md, cast(:ins as jsonb), cast(:outs as jsonb),
                        :se, cast(:sc as jsonb), cast(:cp as jsonb),
                        cast(:idem as jsonb), cast(:esl as jsonb), :to,
                        cast(:rp as jsonb), cast(:rd as jsonb), :sr, :ci,
                        cast(:sba as jsonb), :po, :h, now(),'lanxiu-import',
                        now(), 1)"""),
                      {"i": "tv_" + uuid.uuid4().hex[:16], "o": org, "p": 项目,
                       "d": did, "v": (有 or 0) + 1,
                       "md": 版本["model_description"],
                       "ins": json.dumps(版本["input_schema"], ensure_ascii=False),
                       "outs": None,
                       "se": 档,
                       "sc": json.dumps(版本["allowed_scopes"], ensure_ascii=False),
                       "cp": (json.dumps(版本["confirmation_policy"], ensure_ascii=False)
                              if 版本["confirmation_policy"] else None),
                       "idem": (json.dumps(版本["idempotency_strategy"], ensure_ascii=False)
                                if 版本["idempotency_strategy"] else None),
                       "esl": (json.dumps(版本["external_status_lookup"], ensure_ascii=False)
                               if 版本["external_status_lookup"] else None),
                       "to": 版本["timeout_seconds"],
                       "rp": json.dumps(版本["retry_policy"], ensure_ascii=False),
                       "rd": json.dumps(版本["redaction"], ensure_ascii=False),
                       "sr": None, "ci": None,
                       "sba": json.dumps(版本["server_bound_arguments"],
                                         ensure_ascii=False),
                       "po": 版本["pollable"], "h": h})
            出新版 += 1
    return (f"✅ 新增 {新增} 个工具 · 出新版 {出新版} 条 · 没动 {没动} 条\n"
            f"\n  ⚠️ 盲区:**单向**。在后台改这些工具**不会回到 api.py**,"
            f"执行层挂的还是澜绣那边的 schema ——\n"
            f"     「让它看得见」和「让它生效」是两步。")


if __name__ == "__main__":
    sys.exit(main())
