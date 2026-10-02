#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一个对象**声明了依赖**,那条依赖要么建成外键,要么点名说清为什么不建。

## 为什么需要它

2026-10-02 查出来:`connection_versions.connection_id` 和
`tool_versions.connection_id` **一直没有外键** —— 而它们各自的
`entities.py` 里依赖是**声明着的**。

原因在 `models.py`:外键是从依赖表名推列名的
(`model_connections` → `model_connection_id`),而实际列名是短名
`connection_id`。推不出来,那里就 **静默 `continue`**。

> **「我声明了依赖所以有外键」和「我声明了依赖但列名推不出来所以没外键」,
> 在登记表上长得一模一样。**

而短名本身是有道理的:`connection_id` 在 `tool_versions` 指
capability_connections、在 `connection_versions` 指 model_connections ——
**同一个列名指向两张不同的父表**,靠列名永远分不开。
所以 `models.py` 里加了 `_依赖列` 显式映射,这条判据盯住余下的每一处。

当天我自己也踩了同一个坑:`selection_decisions` 第一版写了
`policy_version_id` / `catalog_snapshot_id` 两个短名,
于是 `alembic check` 的输出里那两列干干净净地没有 ForeignKey,
**而六张表全都「建对了」**。

## 这条判据怎么判

对每个实体的每条 `依赖`,照 `models.py` 的规则算一遍能不能建成外键:
先查 `_依赖列` 显式映射,再按表名推列名。算不出来的,
必须在下面 `说不建的理由` 里点名 + 写清为什么。

两种红法:
  · **算不出外键、而且没点名**:红。要么改列名、要么进 `_依赖列`、
    要么写进这里并说清理由。
  · **点了名、而它其实建得出来**:红(过期的豁免 ——
    一条不再需要的豁免会在有人改坏那个列名那天**悄悄放行它**)。

## ⚠️ 为什么不干脆让 `models.py` 推不出来就抛

因为有三类**合理的**推不出来,而它们的下一步完全不同:
  ① 列名是短名 / 一名多指 → **该进 `_依赖列`**(真的要外键)
  ② 引用存在 JSONB 里(`definition_ref` / `member_manifest`)→
     **加不了外键**,只能靠冻结时的服务端校验
  ③ 依赖是语义上的,根本不留指针(`prompt_versions` 不指回草稿)
直接抛会把 ② ③ 一起打断,于是人会去把依赖声明删掉 ——
**而那比没有外键更糟:连「它依赖谁」这件事都丢了。**

## 已知盲区(写下来,才和「忘了」分得开)

- **只看「算不算得出外键」,不看「外键建对了没有」。**
  ondelete 是 RESTRICT 还是 CASCADE、复合键有没有带上 project_id,
  这条判据都不管(那一半归 `alembic check` 和迁移评审)。
- **不验 JSONB 里那些 id 的有效性。** ② 类豁免靠服务端校验,
  而这条判据看不见那个校验在不在 —— 它只记下「这里有意不加外键」。
"""
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))

# ── 明写不建外键的,**点名 + 写理由** ──────────────────────────────────
# 说不清为什么不建的,就不是例外,是漏了。
说不建的理由 = {
    ("prompt_versions", "prompt_drafts"):
        "③ 冻结时从草稿生成,**不留回指指针** —— 依赖是语义上的。"
        "留指针反而会让人以为「改草稿会影响已冻结的版本」",
    ("tool_group_versions", "tool_versions"):
        "② 成员在 `member_manifest`(JSONB)里,一条一条带着加载角色和必要性,"
        "**不是单列** —— JSONB 里的 id 加不了外键。"
        "靠冻结时的服务端校验(同名 / 配套环 / 版本存在),见规格 §9.2",
    ("execution_runs", "applications"):
        "② 引用在 `definition_ref`(JSONB)里 —— 一次运行可能指向应用、"
        "也可能指向 Workflow 或 Agent,**存成一列会变成三个互斥的空列**",
    ("execution_runs", "release_manifests"):
        "② 引用在 `release_ref`(JSONB)里,同上 —— "
        "而且它要连带记下「当时那一版清单的哈希」,不只是 id",
}


def 算外键(名, 字段, 父, 显式映射):
    """照 `models.py` 的规则算:这条依赖能建成外键吗?返回用哪一列,或 None。"""
    if 父 == 名 or 父 in ("projects", "organizations"):
        return "不用建"          # 自引用 / 已被自动规则覆盖
    显式 = 显式映射.get((名, 父))
    if 显式 and 显式 in 字段:
        return 显式
    父字段 = f"{父.rstrip('s')}_id" if not 父.endswith("ies") else 父[:-3] + "y_id"
    for c in (父字段, f"{父[:-1]}_id"):
        if c in 字段:
            return c
    return None


def main():
    print(f"\n\033[1m▸ 声明了依赖的,外键真建上了吗{D}")
    print("  ⚠️ 这条判据看的是**「依赖声明有没有落成外键」** —— "
          "`alembic check` 看库和模型一致,**它不看「模型里本该有而没声明」**")

    import entities as EN
    import models as MD

    显式映射 = getattr(MD, "_依赖列", {})
    算不出的, 过期豁免 = [], []
    总依赖 = 0
    for e in EN.实体表:
        名 = e["名"]
        字段 = set(EN.该有的通用字段(e)) | set(e["关键字段"])
        for 父 in e["依赖"]:
            总依赖 += 1
            列 = 算外键(名, 字段, 父, 显式映射)
            有理由 = (名, 父) in 说不建的理由
            if 列 is None and not 有理由:
                算不出的.append((名, 父, 字段))
            elif 列 not in (None, "不用建") and 有理由:
                过期豁免.append((名, 父, 列))

    if not 总依赖:
        # ⚠️ 空集合上所有性质都成立。
        print(f"  {R}❌ 一条依赖都没扫到 —— **扫不到东西不是通过**{D}")
        return 1
    print(f"  依赖声明 {总依赖} 条;显式映射 {len(显式映射)} 条;"
          f"明写不建的 {len(说不建的理由)} 条")

    if 过期豁免:
        print(f"\n  {R}❌ 这 {len(过期豁免)} 条写了「不建外键」的理由,"
              f"而它其实建得出来:{D}")
        for 名, 父, 列 in 过期豁免:
            print(f"     · {名} → {父}(能用 `{列}` 建)")
        print(f"     一条不再需要的豁免,会在有人改坏那个列名那天"
              f"**悄悄放行它** —— 那时它看起来一直是绿的。")
        return 1

    if 算不出的:
        print(f"\n  {R}❌ 这 {len(算不出的)} 条依赖**算不出外键**,而且没点名:{D}")
        for 名, 父, 字段 in 算不出的:
            父字段 = (f"{父.rstrip('s')}_id" if not 父.endswith("ies")
                   else 父[:-3] + "y_id")
            print(f"     · {名} → {父}")
            print(f"       推出来的列名 `{父字段}` 不在它的字段里")
        print(f"\n     三条路,**选哪条取决于为什么推不出来**:")
        print(f"       ① 列名是短名 / 一名多指 → 进 `models.py` 的 `_依赖列`")
        print(f"       ② 引用存在 JSONB 里 → 写进这个脚本的 `说不建的理由`")
        print(f"       ③ 根本不留指针 → 同 ②,并说清为什么不留")
        print(f"     {Y}而「忘了」和「有意不建」在 entities.py 上"
              f"长得一模一样 —— 所以必须点名。{D}")
        return 1

    print(f"\n  {G}✅ {总依赖} 条依赖都落到位了{D}")
    for (名, 父), 为什么 in 说不建的理由.items():
        print(f"  {Y}⚠️ 明写不建:{名} → {父}{D}")
        print(f"     {为什么}")
    print(f"  ⚠️ 盲区:只看「算不算得出外键」,**不看外键建对了没有**"
          f"(ondelete / 复合键带不带 project_id 归 `alembic check` 和迁移评审)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
