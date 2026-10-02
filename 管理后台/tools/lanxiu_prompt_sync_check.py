#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台里那 79 条铁律,和 `prompts.py` 里的**真的一样吗**。

## 为什么需要它

`tools/import_lanxiu_prompts.py` 把澜绣 `prompts.py` 的铁律导进后台
(2026-10-02,搬家说明 `已搬走.md` 留的第一条待办)。而导入是**单向**的,
于是最大的风险是:**文件改了,而后台没跟上**。

那种不一致特别危险,因为后台那一页**看起来完全正常** ——
它显示着 79 条铁律和它们的版本历史,而其中某几条
已经不是执行层真正在用的那一版了。

> **一个显示着旧内容的控制面,比一个空的控制面更坏** ——
> 空的会让人去找真东西,旧的让人以为自己看到的就是在跑的东西。

## 这条判据怎么判

读 `prompts.py` 的 `ALL_RULES`,和库里 `project_lanxiu` 的
最新 Prompt 版本逐条比**内容哈希**(算法和导入脚本共用一个函数 ——
抄一份的话两边会在谁都没改它的那天开始不一致)。

四种红法:
  · **文件里有、后台没有**:红(新加了铁律没导)
  · **后台有、文件里没有**:红(文件里删了而后台还留着 —— 那条会在
    后台上一直显示成「在用的规矩」)
  · **哈希不一样**:红,并点名是哪几条(文件改了没重导)
  · **一条都没扫到**:红(**扫不到不是通过**)

## ⚠️ 这条判据不进 `make contract`

它要**数据库**,而 `contract` 那一组是「不需要数据库」的。
放进去会让 contract 在没有库的机器上红 —— 而那种红和真问题混在一起。
进的是 `make test`(要库那一组)。
> 一条装在跑不起来的地方的判据,和没装一样。

## 已知盲区

- **只比哈希,不比「哪一个字不一样」。** 报出来是「这几条不一致」,
  要看具体差别得自己 diff。哈希够用:它的作用是**当场拦住**,
  不是替人读差异。
- **不验执行层读的是哪一份。** 现在执行层(`agent/` 那套)读的仍然是
  **文件**,后台只是看得见。等哪天改成从后台读,这条判据要跟着改成
  「执行层读到的 == 后台里那一版」。
"""
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "tools"))
sys.path.insert(0, os.path.dirname(根))


def main():
    print(f"\n\033[1m▸ 后台里的铁律和 `prompts.py` 一致吗{D}")
    print("  ⚠️ 这条判据看的是**「控制面显示的 == 文件里的」** —— "
          "导入是单向的,文件改了后台不会自己跟上,"
          "**而那时后台那一页看起来完全正常**")

    # ⚠️ **哈希算法从导入脚本里拿,不抄一份。**
    # 抄一份的话,两边会在谁都没改它的那天开始不一致 ——
    # 而那时这条判据会报出一片「不一致」,而真实内容是一样的。
    import import_lanxiu_prompts as IMP

    try:
        全, 用它的, 漏 = IMP.读铁律()
    except Exception as e:
        print(f"  {R}❌ 读不到 `prompts.py` 的铁律:{e}{D}")
        return 1
    if 漏:
        print(f"  {R}❌ 这些在角色组里而 `ALL_RULES` 里没有:{漏}{D}")
        return 1
    if not 全:
        print(f"  {R}❌ 一条铁律都没读到 —— **读不到不是通过**{D}")
        return 1

    from db import 事务          # noqa: E402
    from sqlalchemy import text as _t
    with 事务() as c:
        有项目 = c.execute(_t("select 1 from projects where id=:i"),
                        {"i": IMP.项目id}).first()
        if not 有项目:
            print(f"  {R}❌ 后台里没有 `{IMP.项目id}` 这个项目 —— "
                  f"先跑 `python3 tools/import_lanxiu_prompts.py`{D}")
            return 1
        行 = c.execute(_t("""select key, content_hash, version_no
                           from prompt_versions v
                          where project_id=:p
                            and version_no = (select max(version_no)
                                              from prompt_versions
                                             where project_id=v.project_id
                                               and key=v.key)"""),
                      {"p": IMP.项目id}).mappings().all()
    库里 = {r["key"]: (r["content_hash"], r["version_no"]) for r in 行}
    print(f"  文件里 {len(全)} 条 · 后台里 {len(库里)} 条")

    少导 = sorted(set(全) - set(库里))
    多出 = sorted(set(库里) - set(全))
    不一致 = []
    for i in sorted(set(全) & set(库里)):
        m, p = IMP.包一条(全[i], 用它的[i])
        if IMP.哈希(m, p) != 库里[i][0]:
            不一致.append((i, 库里[i][1]))

    if 少导:
        print(f"\n  {R}❌ 文件里有、后台**没有**的 {len(少导)} 条:{少导}{D}")
        print(f"     跑 `python3 tools/import_lanxiu_prompts.py` 导进去。")
        return 1
    if 多出:
        print(f"\n  {R}❌ 后台有、文件里**没有**的 {len(多出)} 条:{多出}{D}")
        print(f"     文件里删掉了而后台还留着 —— "
              f"**那条会在后台上一直显示成「在用的规矩」**。")
        return 1
    if 不一致:
        print(f"\n  {R}❌ 这 {len(不一致)} 条内容**对不上**"
              f"(文件改了而后台没重导):{D}")
        for i, 号 in 不一致:
            print(f"     · {i}(后台最新是 v{号})")
        print(f"     跑 `python3 tools/import_lanxiu_prompts.py` —— "
              f"它只给真变了的那几条出新版本。")
        print(f"     {Y}⚠️ 在这之前后台那一页看起来完全正常:"
              f"它显示着版本历史,而内容已经不是执行层在用的那一版。{D}")
        return 1

    print(f"\n  {G}✅ {len(全)} 条逐条对上了(比的是内容哈希){D}")
    print(f"  ⚠️ 盲区:**不验执行层读的是哪一份** —— "
          f"现在它读的仍然是**文件**,后台只是看得见。")
    print(f"     等哪天改成从后台读,这条判据要跟着改成"
          f"「执行层读到的 == 后台里那一版」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
