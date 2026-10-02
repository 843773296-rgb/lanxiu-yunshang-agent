#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把澜绣 `prompts.py` 的 79 条铁律导进后台,一条一个 Prompt。

## 为什么需要它

2026-09-27 这个后台从 `~/Desktop/产品经理面试/output/ai-management-console/`
并进澜绣仓库时,搬家说明(`已搬走.md`)留了三条待办,并写明了后果:

> **一个管理后台管着自己造的演示数据,和没有这个后台差别不大。**

| 后台的这一页 | 该接澜绣的什么 |
|---|---|
| Prompt 管理 | `prompts.py` 的铁律 |
| Agent 配置 | `agent/knobs.py` 的 6 个旋钮 |
| 知识管理 | `knowledge/` |

10-02 核对:**三条一件都没做**。后台里只有「演示项目 A / B」,
Prompt 是 `article_summary` / `ticket_classify` —— 全是它自己造的演示数据,
而澜绣真正在跑的是 `prompts.py` 的 **79 条 Rule**(1534 行)。

这个脚本做第一条的**前半**:让后台**看得见**那 79 条。
执行层(`agent/` 那套)仍然从文件读 —— **这一步不动它**。
> 「让它看得见」和「让它生效」是两步,而前者不碰运行代码、风险小得多。

## 一条铁律为什么是一个 Prompt,而不是整份一个版本

那 79 条里 **38 条只有一个角色用、36 条两个、5 条三个角色都用**
(顾问 / 任务 / 工坊 / 版型 / 财务)。而这个项目一直在做的事正是
「**这一条规矩值多少分**」的归因 —— `prompts.py` 里就记着
「不给标准时模型 0/2,给了 2/2」那种实测。

整份一个版本会让这种归因做不了:改一个字就是新一版,
而「这一版和上一版差在哪条规矩上」只能靠人读差异。

⚠️ **一条铁律被多个角色共用时,这里只存一份。**
按角色各存一份的话,同一条会有三个副本 ——
**改一处、另两处不变**,而那正是这个仓库反复栽的那个形状
(`prompts.py` 收成单一源头之前就是这么漂的)。
「哪些角色用它」是它的一个属性,不是复制的理由。

## 幂等:只有正文真改了才出新版本

版本历史的全部价值是「**这次改了什么**」。每跑一次出一版的话,
它会变成噪音 —— 而噪音里找不出那条真的改动。

所以按**内容哈希**判:哈希没变就一个字不动(草稿和版本都不动)。
这也让这个脚本天然跑得起第二遍
(10-02 在 seed 那一族上栽过两次「跑第二遍会堆」)。

## ⚠️ 默认就写,**没有 dry-run**

有意的。10-02 一天栽了两次「默认 dry-run 而且退出码 0」——
`seed_pricing` 和 `seed_human_requests` 在 CI 里打着绿勾什么都没灌。
> **一个默认不写、而且退出 0 的脚本,和一个写成功的脚本,
> 在 CI 日志的绿勾上长得一模一样。**
要只看不写,用 `--看`(反过来,看是显式的)。

## 已知盲区(写下来,才和「忘了」分得开)

- **单向。** 这是「文件 → 后台」。在后台改了那 79 条**不会回到文件**,
  执行层读的还是文件。双向(或让执行层从后台读)是下一步,
  而那一步要改澜绣的运行代码 —— 那边有并行会话在改。
- **不导 `agent/knobs.py` 和 `knowledge/`。** 那是搬家说明里另外两条,
  各自要单独的映射决定。
- **不验「导进去的和文件里的一字不差」** —— 那一半归
  `tools/lanxiu_prompt_sync_check.py`(同一轮加的判据)。
"""
import argparse
import hashlib
import json
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, 仓)                      # 为了 import prompts

项目id = "project_lanxiu"
项目名 = "澜绣云裳"


def 读铁律():
    """从 `prompts.py` 拿 79 条,外加「哪些角色用它」。"""
    import prompts as P
    角色组 = [("顾问", P.KB_RULES), ("任务", P.TASK_RULES),
            ("工坊", P.WORKSHOP_RULES), ("版型", P.PATTERN_RULES),
            ("财务", P.FINANCE_RULES)]
    用它的 = {}
    for 名, rs in 角色组:
        for r in rs:
            用它的.setdefault(r.id, []).append(名)
    全 = {}
    for r in P.ALL_RULES:
        # ⚠️ `ALL_RULES` 里同一条可能出现多次(多个角色组拼起来的)。
        # 这里按 id 去重 —— **按出现次数存多份就是上面说的那个副本问题**。
        全[r.id] = r
    # ⚠️ **对账:角色组里的每一条都要在 ALL_RULES 里。**
    # 不对账的话,哪天有人往某个角色组加了一条而忘了进 ALL_RULES,
    # 这里会**静默少导一条** —— 而少导一条和导全了在输出上长得一样。
    漏 = sorted(set(用它的) - set(全))
    return 全, 用它的, 漏


def 包一条(r, 角色们):
    """一条 Rule → (messages, params)。"""
    messages = {"system": r.text}
    params = {
        "铁律编号": r.id,
        # ⚠️ **`范围` 要保留。** `Rule` 的文档串专门解释过为什么分两种:
        # 「这个工具怎么用」不该混在铁律列表里 —— 列表越长,
        # 每一条被稀释得越厉害。合成一类就把那个设计抹掉了。
        "范围": r.scope,
        "装了这些工具才发": list(r.needs),
        "装了这些工具就不发": list(r.avoid),
        "管哪件事的口径": list(r.管),
        "哪些角色用它": 角色们,
        "来路": "从 prompts.py 导入(单向:在这里改不会回到文件)",
    }
    return messages, params


def 哈希(messages, params):
    """内容哈希 —— **只有它变了才出新版本**。"""
    料 = json.dumps({"messages": messages, "params": params},
                   ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(料.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true",
                    help="只看不写(**默认是写** —— 见文档串里那段)")
    a = ap.parse_args()

    print(f"\n\033[1m▸ 把澜绣的铁律导进后台(一条一个 Prompt){D}")
    全, 用它的, 漏 = 读铁律()
    if 漏:
        print(f"  {R}❌ 这些条目在角色组里,而 `ALL_RULES` 里没有:{漏}{D}")
        print(f"     **少导一条和导全了在输出上长得一样** —— 所以这里当场红。")
        return 1
    if not 全:
        print(f"  {R}❌ 一条铁律都没读到 —— **读不到不是通过**{D}")
        return 1
    共用 = {}
    for i, 组 in 用它的.items():
        共用[len(组)] = 共用.get(len(组), 0) + 1
    print(f"  读到 {len(全)} 条(去重后)。"
          f"被 1/2/3 个角色用的:{共用.get(1,0)} / {共用.get(2,0)} / {共用.get(3,0)}")
    范围分布 = {}
    for r in 全.values():
        范围分布[r.scope] = 范围分布.get(r.scope, 0) + 1
    print(f"  范围:{范围分布}(**两种要分开** —— 见 `包一条()` 里那段)")

    from db import 事务          # noqa: E402
    from sqlalchemy import text as _t

    if a.看:
        print(f"\n  {Y}⚠️ `--看`:一行都不写。{D}")
        for i in sorted(全)[:5]:
            r = 全[i]
            print(f"     · {i:6} 范围={r.scope:4} 角色={用它的[i]} "
                  f"正文 {len(r.text)} 字")
        print(f"     …(共 {len(全)} 条)")
        return 0

    建了项目, 新成员 = False, []
    新增, 更新, 没动 = [], [], []
    with 事务() as c:
        org = c.execute(_t("select id from organizations limit 1")).scalar()
        if not org:
            print(f"  {R}❌ 库里没有组织 —— 先跑 seed_demo.py{D}")
            return 1
        # ① 项目
        有 = c.execute(_t("select 1 from projects where id=:i"),
                      {"i": 项目id}).first()
        if not 有:
            c.execute(_t("""insert into projects
                (id, organization_id, name, owner, status, timezone,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:n,'seed','active','Asia/Shanghai',
                        now(),'import', now(), 1)"""),
                      {"i": 项目id, "o": org, "n": 项目名})
            建了项目 = True
        # ② 成员 —— ⚠️ **建项目不建成员,等于建了一个没人能进的项目。**
        #
        # 第一版漏了这一步,表现特别隐蔽:`GET /prompts` 返回 **200 + 0 条**,
        # 不是 403。于是那 79 条躺在库里,而**任何人打开后台都看不见**。
        # > 一个「没人能进」的项目和一个「里面没东西」的项目,
        # > **在接口上长得一模一样。**
        #
        # ⚠️ **只给 admin,不照搬演示项目那 7 个角色。** 这是个决定:
        # 那 79 条是澜绣真正在跑的规矩 ——
        # **把看它的权限默认发给 7 个角色,不该由这个脚本决定。**
        # 谁还该有权限是业务的事,在后台的成员页上加。
        管理员们 = [r[0] for r in c.execute(_t(
            """select distinct user_id from memberships
                where role='admin' and coalesce(status,'active')='active'""")).all()]
        for uid in 管理员们:
            c.execute(_t("""insert into memberships
                (id, organization_id, project_id, user_id, role, status,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:u,'admin','active',
                        now(),'import', now(), 1)
                on conflict do nothing"""),
                      {"i": f"mb_lanxiu_{uid}", "o": org, "p": 项目id, "u": uid})
        新成员 = 管理员们

        # ── 基线方案:「什么都不改」那一份 ────────────────────────────
        # ⚠️ **这不是为了喂判据,它有业务理由。**
        # 规格 §13.2 讲「全部加载」时的原话:「**保留作为旧配置兼容及对比基线**」。
        # 同一个道理在旋钮上:
        # > **没有基线,就没法说「改了旋钮之后好了多少」。**
        # 而它的旋钮值就是 `knobs.默认()` 里非 None 的那几个 ——
        # 也就是**现在实际在跑的那一份**的快照。
        #
        # 顺带也解决一件事:`ifmatch_reachable_check` 要从
        # `/knob-plans` 列表取一个样例 id 去验「界面拿得到 revision 吗」,
        # 而 CI 是从零建库 —— 一个方案都没有的话那条判据
        # **什么都没验到**(它自己明说这不算通过)。
        try:
            from agent import knobs as _K
            默认 = {k: v for k, v in (_K.默认() or {}).items() if v is not None}
        except Exception:
            默认 = {}
        c.execute(_t("""insert into knob_plans
            (id, organization_id, project_id, key, params, owner, status,
             change_note, draft_revision, created_at, created_by,
             updated_at, revision)
            values (:i,:o,:p,'基线-默认', cast(:pa as jsonb), 'import', 'active',
                    :cn, 1, now(),'import', now(), 1)
            on conflict do nothing"""),
                  {"i": "kp_基线-默认", "o": org, "p": 项目id,
                   "pa": json.dumps(默认, ensure_ascii=False),
                   "cn": "**基线:什么都不改**(`knobs.默认()` 的快照)—— "
                         "没有基线就没法说「改了旋钮之后好了多少」"})

        # ② 79 条
        for i in sorted(全):
            r, 角色们 = 全[i], 用它的[i]
            messages, params = 包一条(r, 角色们)
            h = 哈希(messages, params)
            did = f"pr_{i.lower()}"
            旧 = c.execute(_t("""select p.id, v.content_hash, v.version_no
                               from prompt_drafts p
                               left join prompt_versions v
                                 on v.project_id=p.project_id and v.key=p.key
                               where p.project_id=:p and p.id=:i
                               order by v.version_no desc limit 1"""),
                          {"p": 项目id, "i": did}).mappings().first()
            if 旧 and 旧["content_hash"] == h:
                # ⚠️ **哈希没变就一个字不动。** 见文档串「幂等」那段:
                # 每跑一次出一版的话,版本历史会变成噪音。
                没动.append(i)
                continue
            jm = json.dumps(messages, ensure_ascii=False)
            jp = json.dumps(params, ensure_ascii=False)
            if not 旧:
                c.execute(_t("""insert into prompt_drafts
                    (id, organization_id, project_id, key, messages,
                     variable_schema, output_schema, params,
                     created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:k, cast(:m as jsonb),
                            cast('{}' as jsonb), null, cast(:pa as jsonb),
                            now(),'import', now(), 1)"""),
                          {"i": did, "o": org, "p": 项目id, "k": i,
                           "m": jm, "pa": jp})
                新增.append(i)
            else:
                c.execute(_t("""update prompt_drafts
                    set messages=cast(:m as jsonb), params=cast(:pa as jsonb),
                        updated_at=now(), revision=coalesce(revision,0)+1
                    where project_id=:p and id=:i"""),
                          {"m": jm, "pa": jp, "p": 项目id, "i": did})
                更新.append(i)
            号 = (旧["version_no"] + 1) if (旧 and 旧["version_no"]) else 1
            c.execute(_t("""insert into prompt_versions
                (id, organization_id, project_id, key, version_no, messages,
                 variable_schema, output_schema, params, content_hash,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:k,:n, cast(:m as jsonb),
                        cast('{}' as jsonb), null, cast(:pa as jsonb), :h,
                        now(),'import', now(), 1)"""),
                      {"i": f"pv_{i.lower()}_v{号}", "o": org, "p": 项目id,
                       "k": i, "n": 号, "m": jm, "pa": jp, "h": h})

    if 建了项目:
        print(f"\n  {G}✅ 建了项目 `{项目id}`({项目名}){D}")
        print(f"     ⚠️ 后台原来只有「演示项目 A / B」—— "
              f"**这是第一个真实项目**")
    if 新成员:
        print(f"  {G}✅ 给 {len(新成员)} 个管理员建了成员记录:{新成员}{D}")
        print(f"     ⚠️ **只给 admin** —— 那 79 条是澜绣在跑的规矩,"
              f"把看它的权限默认发给 7 个角色不该由脚本决定;"
              f"谁还该有,在成员页上加")
    print(f"  {G}✅ 新增 {len(新增)} 条 · 出新版 {len(更新)} 条 · "
          f"没动 {len(没动)} 条{D}")
    if 没动 and not 新增 and not 更新:
        print(f"     (全都没动 = **这个脚本跑得起第二遍**:"
              f"内容哈希没变就不出新版本)")
    print(f"\n  ⚠️ 盲区:**单向**。在后台改这 79 条**不会回到文件**,"
          f"执行层读的还是 `prompts.py` ——")
    print(f"     「让它看得见」和「让它生效」是两步,"
          f"后者要改澜绣的运行代码(那边有并行会话)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
