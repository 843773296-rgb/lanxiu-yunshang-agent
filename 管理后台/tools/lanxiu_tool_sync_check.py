#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台的工具目录 和 澜绣在跑的工具面 一致吗 —— **第三条同步判据**。

## 这条判据守的那句话

工具导入是**单向**的:`backend/api.py` 的三个 schema 列表 → 后台的工具目录。
文件改了后台不会自己跟上,**而那时后台那一页看起来完全正常** ——
它显示着 81 个工具、它们的版本历史和副作用分级。

> **一个显示着旧工具说明的控制面,比一个空的控制面更坏** ——
> 空的会让人去找真东西,旧的让人以为自己看到的就是模型在用的那一份。

而这条链上的错**特别贵**:后台上标着「只读」的工具,
如果澜绣那边已经把它改成会写了,那后台的闸会**放过它**。
(契约原话:「一个工具从只读变成会写东西,而引用它的 Agent 还指着老的说明 ——
**那份说明现在是错的**」。)

## 五种红法

  · **文件里有、后台没有**:红(新加了工具没导)
  · **后台有、文件里没有**:红(澜绣那边下架了而后台还列着 ——
    那条会在后台上一直显示成「能用的工具」)
  · **哈希不一样**:红,点名是哪几个(说明或入参 schema 改了没重导)
  · **副作用档位对不上**:红,**而且这一档单独报** ——
    「说明改了一个字」和「从只读变成会写」在哈希上长得一模一样,
    而后者是这条链上唯一会**拆掉一道闸**的改动
  · **一个都没扫到**:红(**扫不到不是通过**)

## ⚠️ 「会写的工具没在口径里」也要红

口径文件(`docs/口径/工具不可逆口径.json`)管的是「哪几个算不可逆」。
澜绣那边新加一个写工具时,它**两边都不在** ——
导入脚本会拒导它并点名,但**那条红只在跑导入的时候出现**。
这条判据把它变成常态检查:**新写工具一出现就红**,不等到谁想起来跑导入。

## ⚠️ 不验「执行时真的拦住了」

后台记着某个工具要人确认,**不等于执行时真的拦住了** ——
真正拦住的是澜绣那边 `agentsite/sdk.py` 的 Hook 和 `backend/fsm.py` 的几道闸。
「让它看得见」和「让它生效」是两步,这条判据只管第一步。
"""
import importlib.util
import json
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"
根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓库 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
sys.path.insert(0, os.path.join(仓库, "backend"))
sys.path.insert(0, os.path.join(根, "tools"))

# ⚠️ **哈希算法和分级规则从导入脚本里拿,不抄一份。**
# 抄一份的话两边会在谁都没改它的那天开始不一致 ——
# 而那时这条判据会报出一片「不一致」,**而真实内容是一样的**。
_s = importlib.util.spec_from_file_location(
    "imp_tools", os.path.join(根, "tools", "import_lanxiu_tools.py"))
IMP = importlib.util.module_from_spec(_s)
_s.loader.exec_module(IMP)

项目id = os.environ.get("AIMC_LANXIU_PROJECT", "project_lanxiu")


def main():
    import api
    import dsl as DSL
    from sqlalchemy import text as _t
    from db import 事务

    print(f"\n\033[1m▸ 后台的工具目录和澜绣在跑的工具面一致吗\033[0m")
    print(f"  {Y}⚠️ 这条判据看的是**「控制面显示的 == 澜绣在跑的」** —— "
          f"导入是单向的,文件改了后台不会自己跟上,"
          f"**而那时后台那一页看起来完全正常**{D}")

    工具面 = IMP.读工具面()
    写们 = set(getattr(api, "WRITE_TOOLS", ()))
    不可逆, 可撤, 元 = IMP.读口径()

    # ① 会写的工具必须在口径里有位置 —— **新写工具一出现就红**
    没口径 = sorted(n for n in 写们 if n in 工具面
                 and n not in 不可逆 and n not in 可撤)
    两边都在 = sorted(不可逆 & 可撤)
    口径里不存在的 = sorted((不可逆 | 可撤) - set(工具面))

    with 事务() as c:
        行 = c.execute(_t("""select d.name, d.side_effect_type 档, v.content_hash,
                                   v.version_no, v.side_effect_type 版档
                            from tool_definitions d
                            join tool_versions v on v.tool_definition_id=d.id
                           where d.project_id=:p and d.archived_at is null
                             and v.version_no = (select max(version_no)
                                                 from tool_versions
                                                where tool_definition_id=d.id)"""),
                      {"p": 项目id}).mappings().all()
    库里 = {r["name"]: (r["content_hash"], r["version_no"], r["档"], r["版档"])
          for r in 行}
    print(f"  澜绣在跑 {len(工具面)} 个 · 后台里 {len(库里)} 个"
          f"(会写的 {len(写们)} 个:不可逆 {len(不可逆)} / 可撤 {len(可撤)})")

    if 两边都在:
        print(f"\n  {R}❌ 口径文件里这几个**两边都列了**:{两边都在}{D}")
        print(f"     先在 {os.path.relpath(IMP.口径文件, 根)} 里定清楚 —— "
              f"**一个既不可逆又可撤的工具,分级取决于读文件的顺序**。")
        return 1
    if 口径里不存在的:
        print(f"\n  {R}❌ 口径文件点名了澜绣那边**没有的工具**:{口径里不存在的}{D}")
        print(f"     改名或下架了?口径里留着一个不存在的名字,"
              f"**看起来像「这个工具管好了」**,而它根本不在场。")
        return 1
    if 没口径:
        print(f"\n  {R}❌ 这 {len(没口径)} 个**会写的工具没在口径里**:{没口径}{D}")
        print(f"     澜绣那边新加了写工具 —— 先在 "
              f"{os.path.relpath(IMP.口径文件, 根)} 里判它「不可逆」还是「可撤」,"
              f"**两边都要列**。")
        print(f"     {Y}⚠️ 猜成「可撤」会让后台的闸不要求确认 —— 那是危险的那一边。{D}")
        return 1

    少导 = sorted(set(工具面) - set(库里))
    多出 = sorted(set(库里) - set(工具面))
    if 少导:
        print(f"\n  {R}❌ 澜绣在跑、后台**没有**的 {len(少导)} 个:{少导[:8]}{D}")
        print(f"     跑 `python3 tools/import_lanxiu_tools.py --项目 {项目id}`。")
        return 1
    if 多出:
        print(f"\n  {R}❌ 后台有、澜绣那边**没有**的 {len(多出)} 个:{多出[:8]}{D}")
        print(f"     澜绣下架了而后台还列着 —— "
              f"**那条会在后台上一直显示成「能用的工具」**。")
        return 1

    换档, 不一致 = [], []
    for n in sorted(set(工具面) & set(库里)):
        说明, 入参, 服务 = 工具面[n]
        档, why = IMP.分级(n, 写们, 不可逆, 可撤)
        h库, v号, 目录档, 版档 = 库里[n]
        # ⚠️ **换档单独报。** 「说明改了一个字」和「从只读变成会写」
        # 在哈希上长得一模一样,而后者是这条链上唯一会**拆掉一道闸**的改动。
        if 档 != 版档 or 档 != 目录档:
            换档.append((n, f"{版档 or 目录档} → {档}"))
            continue
        定义 = dict(name=n, purpose=说明.strip().splitlines()[0][:200],
                  side_effect_type=档, adapter=服务, owner="lanxiu-import")
        版本 = IMP.包一版(n, 说明, 入参, 服务, 档, why)
        if IMP.哈希(定义, 版本) != h库:
            不一致.append((n, v号))

    if 换档:
        print(f"\n  {R}❌ 这 {len(换档)} 个**副作用档位变了**:{D}")
        for n, 变 in 换档:
            print(f"     · {n}:{变}")
        print(f"     {Y}⚠️ 这一档比「说明改了」严重得多:后台上标着「只读」的工具,"
              f"澜绣那边已经会写了 —— **后台的闸会放过它**。{D}")
        print(f"     跑 `python3 tools/import_lanxiu_tools.py --项目 {项目id}` —— "
              f"**风险变化要出新版本**(契约 §16.3)。")
        return 1

    if 不一致:
        # 和另外两条同步判据一样:先分清「该导」还是「等别人提交」。
        # 判断在 `tools/_未提交.py`(三条判据共用一份实现)。
        import _未提交 as U
        查得出, 脏 = U.脏文件们(仓库, "backend/api.py")
        if 查得出 and 脏:
            print(f"\n  {Y}⏸  这 {len(不一致)} 个对不上,"
                  f"**而 `backend/api.py` 有未提交的改动**:{D}")
            for n, v in 不一致[:8]:
                print(f"     · {n}(后台最新是 v{v})")
            print(f"     {Y}⚠️ **先别跑导入。** 并行会话很可能正在改它 ——"
                  f"导下去就是把半成品灌进后台,还给它发版本号。{D}")
            print(f"     {Y}这一档**不算红** —— CI 从提交的代码建库,撞不到它。{D}")
        else:
            if not 查得出:
                print(f"\n  {Y}⚠️ 分不清是哪一种(git 查不出未提交的改动)——"
                      f"**当成「真该导」处理**。{D}")
            print(f"\n  {R}❌ 这 {len(不一致)} 个内容**对不上**"
                  f"(说明或入参 schema 改了而没重导):{D}")
            for n, v in 不一致[:10]:
                print(f"     · {n}(后台最新是 v{v})")
            if len(不一致) > 10: print(f"     …… 还有 {len(不一致)-10} 个")
            print(f"     跑 `python3 tools/import_lanxiu_tools.py --项目 {项目id}`。")
            print(f"     {Y}⚠️ 在这之前后台那一页看起来完全正常:"
                  f"它显示着工具和版本历史,而模型收到的是另一份说明。{D}")
            return 1

    if not 库里:
        print(f"\n  {R}❌ 一个都没比到 —— **扫不到不是通过**{D}")
        return 1

    等 = len(不一致)
    if 等:
        print(f"\n  {G}✅ {len(库里) - 等} 个逐个对上了{D}"
              f"(另 {等} 个在等别人提交,见上面的 ⏸ —— **不是「全对」**)")
    else:
        print(f"\n  {G}✅ {len(库里)} 个逐个对上了(比的是内容哈希 + 副作用档位){D}")
    print(f"  {Y}⚠️ 盲区:**不验「执行时真的拦住了」** —— 后台记着某个工具要人确认,"
          f"不等于执行时真的拦住了。{D}")
    print(f"     真正拦住的是澜绣那边 `agentsite/sdk.py` 的 Hook 和 "
          f"`backend/fsm.py` 的闸。「看得见」和「生效」是两步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
