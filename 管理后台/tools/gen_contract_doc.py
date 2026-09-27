#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从契约登记表生成 docs/契约.md —— **生成的,不要手改**。

手写一份实体表的后果不是抄错,是**它会和代码分家,而分家时两边都看着很正常**。
所以这份文档只有一个来源:`services/api/app/contract/`。
`tools/spec_coverage.py` 会验它是不是最新的(和待办清单那条一个道理)。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "services", "api", "app", "contract"))
import entities as EN, perms as PM, states as ST, errors as ER

出 = os.path.join(ROOT, "docs", "契约.md")


# ⚠️ **这份文档里刻意不写生成时间和 git 短哈希。**
# 第一版写了,结果是:每次提交之后哈希就变,文档立刻又「脏」——
# 而一个**永远脏的生成文件会训练人忽略「脏」这件事**,
# 于是真正该被注意的那次改动也就没人看见了。
# 「这份文档对应哪一版代码」由 git 自己回答(它和代码在同一个提交里)。


def 写():
    L = ["# 开发契约(生成的,不要手改)", "",
         "> 来源:`services/api/app/contract/`。改契约请改那里,然后 `python3 tools/gen_contract_doc.py`。",
         f"> 实体 {len(EN.实体表)} 个 · 状态机 {len(ST.状态机表)} 条 · "
         f"能力 {len(PM.能力们)} 条 · 约束 {sum(len(e['约束']) for e in EN.实体表)} 条", "",
         "手写的表会和代码分家,**而分家时两边都看着很正常** —— 所以这份是生成的。", ""]

    L += ["## 一、实体与约束", "",
          "| 实体 | 中文 | 范围 | 可变性 | 内容寻址 | 依赖 |", "|---|---|---|---|---|---|"]
    范 = {EN.组织级: "组织级", EN.项目级: "项目级", EN.子对象: "挂父级", EN.全局级: "全局"}
    变 = {EN.可改: "可改", EN.不可变: "不可变", EN.只追加: "只追加"}
    for e in EN.实体表:
        L.append(f"| `{e['名']}` | {e['中文']} | {范[e['范围']]} | {变[e['可变性']]} | "
                 f"{'是' if e['内容寻址'] else '否'} | {'、'.join(e['依赖']) or '—'} |")
    L += ["", "### 不按项目隔离的实体(每个都要有理由)", ""]
    for e in EN.实体表:
        if e["范围"] in (EN.组织级, EN.全局级):
            L.append(f"- **`{e['名']}`** — {e['范围理由']}")
    L += ["", "### 逐条约束", ""]
    for e in EN.实体表:
        if not e["约束"]: continue
        L.append(f"**`{e['名']}`({e['中文']})**")
        L += [f"- {c}" for c in e["约束"]] + [""]

    L += ["## 二、状态机", ""]
    for m in ST.状态机表:
        L += [f"### `{m['名']}` · {m['中文']}", "",
              f"起点:**{m['起点']}** · 终态:{'、'.join(f'**{x}**' for x in m['终态'])}", "",
              "| 从 | 能走到 |", "|---|---|"]
        for s in m["状态"]:
            到 = m["流转"].get(s, [])
            L.append(f"| {s} | {'、'.join(到) if 到 else '（终态）'} |")
        if m["备注"]:
            L += [""] + [f"- ⚠️ {b}" for b in m["备注"]]
        L.append("")
    L += [f"「不确定」类状态:{'、'.join(ST.不确定状态)} —— **不是终态**,必须能查回真实状态。", ""]

    L += ["## 三、权限矩阵", "",
          "档位:**是**=默认有 / **否**=不给(要给就得改角色定义)/ "
          "**可授权**=默认关闭,要显式专项授权 / **有额度**=有权限但受配额闸限制", "",
          "| 能力 | " + " | ".join(PM.角色中文[r] for r in PM.角色们) + " |",
          "|---|" + "---|" * len(PM.角色们)]
    档 = {PM.是: "是", PM.否: "否", PM.可授权: "可授权", PM.有额度: "有额度"}
    for c in PM.能力们:
        L.append(f"| {c} | " + " | ".join(档[PM.矩阵[c][r]] for r in PM.角色们) + " |")
    L += ["", "**不能通过邀请获得自己没有的权限** —— 落点在 `perms.可以授予吗()`:"
          "要给的那套权限,在每一条能力上都不能超过授予人自己有的。", ""]

    L += ["## 四、错误结构", "",
          "必含:`code` / `message` / `field_errors` / `retryable` / `trace_id` / "
          "`advice`(**可执行建议,必填**)。", "",
          "| 状态码 | 含义 |", "|---|---|"]
    for k in sorted(ER.状态语义):
        L.append(f"| {k} | {ER.状态语义[k]} |")
    L += ["",
          "- **`advice` 写不出来就说明还没搞清失败原因** —— 不要发一个「请稍后再试」出去。",
          "- **`retryable` 必须显式**:猜错的两个方向代价都很大"
          "(不该重试的重试了 = 重复计费/重复训练;该重试的没重试 = 任务白丢)。",
          "- **错误体不许带凭据**:上游 401 的响应常常把被拒的那个凭据带回来,"
          "原样转出去就是一条泄露通道。`errors.泄密检查()` 连**值**一起扫。", ""]

    os.makedirs(os.path.dirname(出), exist_ok=True)
    open(出, "w", encoding="utf-8").write("\n".join(L))
    return 出


if __name__ == "__main__":
    print("写好了:" + 写())
