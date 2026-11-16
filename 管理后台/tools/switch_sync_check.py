#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具开关两边对账(执行手册 W38,拍板 9「先对账不迁」,11-16 晚)。

## 守的那句话

同一个业务工具有**两处开关**:
  · 业务后台(8760)「系统 → MCP 服务与工具」:停用 / 超时 / 限流,**真正生效的是这一处**(协议层每几秒读 `mcp_tool_cfg`);
  · 管理后台(8801)工具目录:`tool_definitions.status`(active / disabled),**Agent 和工作流能不能选它看这一处**。

两边各管各的,改一边另一边不会跟上 —— 而那时两个页面看起来都很正常:
一边写着「已停用」,另一边照样列成「可用」,工作流里照样选得到、受理照样过,**跑到那一步才被 8760 拒**。

> **一个控制面说停了、另一个控制面说能用,比两个都说能用更坏** —— 看的人会以为自己看的那一个就是真的。

用户 11-12 拍「先对账不迁」:不把开关合成一处,只在门禁里盯着两边一致;页面上标出对面的状态另排。

## 红法

  · **业务后台停用了、管理后台还 active**:红,点名(工作流里还能选到一个必定被拒的工具)
  · **管理后台 disabled 了、业务后台还启用**:红,点名(Agent 选不到它,可桥那边照放 —— 别处直接调还是能调)
  · **管理后台有这个桥工具、业务后台的工具面里没有**:红(下架了没同步;lanxiu_tool_sync_check 也会报,这里只补开关这一角)
  · **一个都没扫到**:红(扫不到不是通过)
  · 限流 / 超时只报不判:管理后台的 timeout_seconds 是版本上的、业务后台的是运行时的,两个数的含义不同,硬比会误报

比对本体是纯函数 `比对()`,`--自测` 用手写的两边状态跑一遍 —— 咬合打它。
"""
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"
根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓库 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(仓库, "backend"))

项目id = os.environ.get("AIMC_LANXIU_PROJECT", "project_lanxiu")


def 比对(后台工具, 业务配置, 业务工具面):
    """后台工具 = {名: status};业务配置 = {名: {启用, 超时, 限流}};业务工具面 = 业务后台登记的全部工具名。
    → {"业务停了后台没停": [...], "后台停了业务没停": [...], "业务没有这个工具": [...], "限流中": [...], "扫了": n}"""
    出 = {"业务停了后台没停": [], "后台停了业务没停": [], "业务没有这个工具": [], "限流中": [], "扫了": 0}
    面 = set(业务工具面 or [])
    for 名, 状态 in sorted((后台工具 or {}).items()):
        出["扫了"] += 1
        if 面 and 名 not in 面:
            出["业务没有这个工具"].append(名)
            continue
        配 = (业务配置 or {}).get(名) or {}
        业启用 = bool(配.get("启用", True))        # 没配过 = 启用(和 mcp_registry.配置 同一条默认)
        后启用 = (状态 or "active") == "active"
        if not 业启用 and 后启用:
            出["业务停了后台没停"].append(名)
        if 业启用 and not 后启用:
            出["后台停了业务没停"].append(名)
        if 配.get("限流"):
            出["限流中"].append(f"{名}(每分钟 {配['限流']})")
    return 出


def _列(xs, n=8):
    xs = list(xs)
    return str(xs) if len(xs) <= n else f"{xs[:n]}…还有 {len(xs) - n} 个(共 {len(xs)})"


def 判(出, 来路):
    print(f"\n\033[1m▸ 工具开关两边对账({来路})\033[0m")
    print(f"  {Y}⚠️ 真正生效的是业务后台那一处;这里盯的是「两个控制面说的一样」—— 先对账不迁(用户 11-12 拍){D}")
    坏 = 0
    if 出["扫了"] == 0:
        print(f"  {R}❌ 一个从澜绣导入的业务工具都没扫到 —— 扫不到不是通过(项目 {项目id} 里没导过?先跑 import_lanxiu_tools){D}")
        坏 += 1
    for 键, 话 in (("业务停了后台没停", "业务后台已停用,管理后台还标「可用」(工作流里选得到一个必定被拒的工具)"),
                 ("后台停了业务没停", "管理后台已停用,业务后台还在放行(Agent 选不到它,别处直接调还是能调)"),
                 ("业务没有这个工具", "管理后台列着、业务后台的工具面里没有(下架了没同步)")):
        if 出[键]:
            print(f"  {R}❌ {话}:{_列(出[键])}{D}")
            坏 += 1
        else:
            print(f"  {G}✅ 没有「{键}」的{D}")
    print(f"  ℹ️ 限流中(只报不判):{_列(出['限流中']) if 出['限流中'] else '没有'}")
    print(f"  扫了 {出['扫了']} 个从澜绣导入的业务工具")
    return 坏


def 自测():
    出 = 比对({"a": "active", "b": "active", "c": "disabled", "d": "active"},
              {"a": {"启用": True}, "b": {"启用": False}, "c": {"启用": True, "限流": 30}},
              ["a", "b", "c"])
    期 = {"业务停了后台没停": ["b"], "后台停了业务没停": ["c"], "业务没有这个工具": ["d"], "限流中": ["c(每分钟 30)"], "扫了": 4}
    好 = 出 == 期
    print(f"  {'✅' if 好 else '❌'} 自测:三种不一致各抓到一个、限流只报、扫了 4 个  {'' if 好 else 出}")
    空 = 比对({}, {}, [])
    好2 = 空["扫了"] == 0
    print(f"  {'✅' if 好2 else '❌'} 自测:空集合扫了 0(调用方要把它判红,不是通过)")
    return 0 if (好 and 好2) else 1


def main():
    # 自测**每次都先跑**(不只 --自测 时):比对本体是纯函数,真跑时两边状态碰巧一致看不出它坏没坏 ——
    # 先拿手写的两边状态过一遍,坏了当场红;咬合规格也打这里(bite_run 对 管理后台/ 下的脚本只会按原样路径跑,不带参数)
    if 自测():
        sys.exit(1)
    if "--自测" in sys.argv:
        sys.exit(0)
    import mcp_registry as MR
    from sqlalchemy import text as _t
    from db import 连接
    with 连接() as c:
        # 只比**从澜绣导入的业务工具**(adapter lanxiu-shop / lanxiu-kb / lanxiu-task,名字就是 api.py 里的工具名,也就是 mcp_tool_cfg 的键);
        # 早先专门做的 `lanxiu_bridge`(取转写 / 写跟进那 26 条桥能力)不是 MCP 工具,业务后台那边没有它们的开关,不在这张账里
        行 = c.execute(_t("""select name, status from tool_definitions
                             where project_id=:p and archived_at is null and adapter in ('lanxiu-shop', 'lanxiu-kb', 'lanxiu-task')"""),
                       {"p": 项目id}).all()
    后台 = {r[0]: r[1] for r in 行}
    配置 = MR.配置()
    try:
        面 = MR._全部工具()
    except Exception as e:        # 业务后台的工具面读不到(比如 api 模块起不来):只比开关,不判「业务没有这个工具」
        print(f"  {Y}⚠️ 业务后台的工具面读不到({type(e).__name__}),这次不判「业务没有这个工具」—— 这不算通过,是没查{D}")
        面 = []
    出 = 比对(后台, 配置, 面)
    坏 = 判(出, f"管理后台 {项目id} × 业务后台 mcp_tool_cfg")
    sys.exit(1 if 坏 else 0)


if __name__ == "__main__":
    main()
