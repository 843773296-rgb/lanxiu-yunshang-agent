#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约登记的端点,**代码里真有那个路由吗**。

## 这条检查是怎么来的

2026-10-04:我往 `contract/endpoints.py` 加了三条端点、重跑 `gen_openapi.py`,
OpenAPI 从 101 条路径涨到 103 条 —— **而代码里一个路由都还没写。**

然后我去找「有没有东西会发现这件事」,结果是**没有**:

    spec_coverage 验的是  OpenAPI 是最新的 / 每条操作有权限 /
                          幂等落成了真 header
    全是**契约内部自洽**,没有一条问「代码里真有这个路由吗」

> **一份声称有 103 条路径的 OpenAPI,和一个真提供 103 条路径的服务,
> 在那份文档上长得一模一样。**

而后果是具体的:调用方照着文档打过来,拿到 404,
而**后台那一页、那份文档、那个契约表全是绿的**。

(澜绣那侧早有一条「路由 · handler 必须真的存在」——
管理后台这边一直没有对等的。这个形状在这个仓库里反复出现:
**判据只长在仓库的一半上**。)

## 判据

比两份清单:

    契约登记的   `contract/endpoints.py` 的 `接口表`(方法 + 前缀 + 路径)
    代码里真有的 `app.routes`(导入 `main`,**不起服务**)

· 契约有而代码没有 → **红**。这是「文档说有、实际 404」
· 代码有而契约没登记 → **也红**。那是一条没人声明过权限的接口,
  而 `endpoints.py` 开头就写着「点不出权限的接口不许登记」——
  反过来说,**没登记的接口等于没人检查过它的权限**

⚠️ 两个方向都要红。只验一个方向的话:
> 一条「契约漏登记」的接口和一条「契约和代码都有」的,
> **在那个绿勾上长得一模一样** —— 而前者是对所有人开放的。

## 它不做什么

- **不起服务、不连库。** 只导入 `main` 读 `app.routes`。
  (导入时 `main` 会建 FastAPI app,而那不需要数据库。)
- **不验 handler 行为。** 「路由在」不等于「它干对了事」——
  那由页面冒烟和集成测试管。
"""
import os
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 管理后台/
APP = os.path.join(根, "services", "api", "app")
# ⚠️ 契约登记表在 `app/contract/` 下,不是 `app/` —— 第一版就猜错了一次。
# (这个仓库为「凭名字猜路径」栽过十一次,所以这里写清它在哪。)
CONTRACT = os.path.join(APP, "contract")

# ── 已知欠账:**契约登记了而代码里还没有**,每条都要写清为什么 ─────────
#
# ⚠️ **这不是豁免,是记账。** 名单里每一条都是一个真的「文档说有、
# 实际 404」—— 写进来只是为了让**新增的**那种能红出来。
# > 一条长期红着的检查会被人忽略,然后它挡的东西一起漏掉;
# > 而一条没有名单的检查,在「有欠账」和「刚刚多了一笔」之间分不开。
#
# 下面七条全是**工具筛选**那条线的。那条线 2026-10-03 收口,结论是
# **「不开」**,而理由不是「它没用」,是「那套题分辨不出来」
# (见 `docs/选型/结论-工具筛选-20261003.md`)。
# 所以这些端点是「规格要求、而那条线停了」——
# **不是漏做,也不该由别的线顺手实现**。
#
# ⚠️ 名单**只许缩短不许加长**:要加一条进来,先问一句
# 「它是不是我自己刚登记而没实现的」——
# 那种情况该去写路由,不是来这儿记一笔。
已知欠账 = {
    ("GET", "/api/v1/projects/{project_id}/execution-runs/{id}/tool-selection"):
        "工具筛选线 10-03 收口「不开」",
    ("GET", "/api/v1/projects/{project_id}/tool-catalog-snapshots"):
        "工具筛选线 10-03 收口「不开」",
    ("POST", "/api/v1/projects/{project_id}/capability-connections/{id}"
             "/discovery-jobs"): "工具筛选线 10-03 收口「不开」",
    ("POST", "/api/v1/projects/{project_id}/tool-catalog-snapshots/build-jobs"):
        "工具筛选线 10-03 收口「不开」",
    ("POST", "/api/v1/projects/{project_id}/tool-discoveries/{id}/import"):
        "工具筛选线 10-03 收口「不开」",
    ("POST", "/api/v1/projects/{project_id}/tool-selection-previews"):
        "工具筛选线 10-03 收口「不开」",
    ("POST", "/api/v1/projects/{project_id}/tool-selection-test-runs"):
        "工具筛选线 10-03 收口「不开」",
}

# 代码里有而契约没登记的已知欠账 —— **同样是记账不是豁免**。
# ⚠️ `endpoints.py` 开头写着「点不出权限的接口不许登记」,
# 反过来说:**没登记的接口等于没人声明过它要什么权限**。
# 这五条是既有状态,**每条都该补登记** —— 记在这儿是为了让新增的能红。
没登记的欠账 = {
    ("GET", "/api/healthz"): "健康检查,不带项目范围;该不该进契约待定",
    ("GET", "/api/v1/projects"): "项目列表,权限靠成员表;**该补登记**",
    ("GET", "/api/v1/projects/{project_id}/prompts/{pid}"): "**该补登记**",
    ("GET", "/api/v1/projects/{project_id}/workbench"): "**该补登记**",
    ("POST", "/api/v1/projects/{project_id}/agent-runs"):
        "权宜路径 —— `agents_api` 里那段注释自己写着"
        "「契约登记表里的路径是 /execution-runs(kind=agent),"
        "这里另开一条是权宜」。**该合并成一条**",
}

# ⚠️ 不进契约比对的路径:FastAPI 自带的和静态资源。
# **写成前缀白名单而不是逐条枚举** —— 下一个 docs 路径不会自动进名单。
不比对前缀 = ("/api/docs", "/api/openapi", "/api/redoc", "/docs", "/openapi",
         "/redoc", "/static", "/ui", "/")


import re as _re

# ⚠️ **比对时把路径参数名抹掉。**
#
# 契约写 `/applications/{id}`,代码写 `/applications/{aid}` —— **同一条接口**,
# 而逐字比会报成「两边各缺一条」。第一版就这么报了 65 条假差异。
# > 一个「参数名不同」的差异,和一个「接口真的不存在」的差异,
# > **在那份对不上的清单里长得一模一样** —— 而前者是噪音,后者是 404。
#
# 参数名不一致本身**也是个真问题**(前端照 OpenAPI 生成类型),
# 但它是既有状态、涉及几十条 —— 单独报成提示,**不拦门禁**:
# 一条会误拦的闸迟早被人关掉,关掉之后它挡的那些错会一起回来。
def _抹参数名(路径):
    return _re.sub(r"\{[^}]*\}", "{}", 路径)


# ⚠️ **这条检查要 FastAPI,而它只装在 `管理后台/.venv` 里。**
# 根 `check.sh` 用的是系统 python —— 直接跑会 ImportError,
# 而 check.sh 会把它报成「**✗ 崩了(这条检查没验过)**」。
# > 一条崩溃了的检查,和一条真的查出问题的,在那个红上长得一样 ——
# > 而崩溃意味着它**什么都没验**。
# 所以这里自己转交给 venv 的解释器;没有 venv 就明说「不适用」。
def _转交给venv():
    venv = os.path.join(根, ".venv", "bin", "python")
    if not os.path.exists(venv):
        print("契约登记的端点,代码里真有那个路由吗")
        print("=" * 84)
        print(f"  ⏸ 没有 {venv} —— **不适用,不是通过**(这台机器没装那个 venv)")
        return 0
    import subprocess
    # ⚠️ **不接管道**(管道吞退出码),原样转交 stdout/stderr。
    return subprocess.call([venv, os.path.abspath(__file__), "--已在venv"])


def main():
    print("契约登记的端点,代码里真有那个路由吗")
    print("=" * 84)
    sys.path.insert(0, APP)
    sys.path.insert(0, CONTRACT)
    try:
        import endpoints as EP
    except Exception as e:
        print(f"  ❌ 读不到契约登记表:{type(e).__name__}: {e}")
        return 1
    try:
        import main as M
    except Exception as e:
        # ⚠️ **导入失败不叫「路由不存在」** —— 它是另一回事(代码炸了),
        # 混成一句的话,一次 import 错误会被当成「少了 40 个路由」。
        print(f"  ❌ 导入 `main` 就炸了:{type(e).__name__}: {e}")
        print("     ⚠️ 这**不是**「路由对不上」—— 先修导入,再看这条检查")
        return 1

    契约 = {(a["方法"].upper(), EP.前缀 + a["路径"]) for a in EP.接口表}

    # ⚠️ **从 `app.openapi()` 读,不从 `app.routes` 数。**
    #
    # 2026-10-04 第一版用的是 `len(app.routes)`,报「文档说有、代码里没有 120 条」。
    # 而那个 120 是假的:我拿探针确认过 ——
    # `include_router` **调了 18 次、装进去 111 条路由、装的就是同一个 app**,
    # 而 `len(app.routes)` 只有 35。`routes` 不是全部注册项的那个列表。
    # > 一个「读了一个代理视图」的计数,和一个「真数了全部路由」的,
    # > **在那个数字上长得一模一样** —— 只是数字本身反常。
    #
    # `app.openapi()` 是 FastAPI 自己算出来的权威清单(100 路径 / 123 操作),
    # 而且它正好是「调用方照着打」的那一份 —— 这条检查问的就是那件事。
    #
    # ⚠️ 这一次我**没有相信那个 120**(CLAUDE.md:数字反常得离谱时先怀疑尺子)——
    # 否则现在会在修 120 个不存在的路由。
    代码 = set()
    _sch = M.app.openapi() or {}
    for p, v in (_sch.get("paths") or {}).items():
        if any(p == x or (x != "/" and p.startswith(x)) for x in 不比对前缀):
            continue
        for m in v:
            if m.lower() in ("get", "post", "patch", "put", "delete"):
                代码.add((m.upper(), p))

    # ⚠️ **样本量下限**:空集合上「两份清单一致」恒为真。
    if not 契约:
        print("  ❌ 契约登记表是空的 —— 不叫「都对上了」,叫没读到")
        return 1
    if not 代码:
        print("  ❌ 一个路由都没扫到 —— **不叫「契约是空的」**,"
              "多半是 `app.routes` 读法变了")
        return 1

    print(f"  契约登记 {len(契约)} 条 · 代码里 {len(代码)} 条")

    # 用**抹掉参数名**的键比对 —— 见上面 `_抹参数名` 那段。
    契约键 = {(m, _抹参数名(p)): (m, p) for m, p in 契约}
    代码键 = {(m, _抹参数名(p)): (m, p) for m, p in 代码}
    _缺 = sorted(契约键[k] for k in (set(契约键) - set(代码键)))
    _多 = sorted(代码键[k] for k in (set(代码键) - set(契约键)))
    # 记过账的单独放一边 —— **它们仍然是欠账,只是不算「刚刚多了一笔」**。
    文档说有实际没有 = [x for x in _缺 if x not in 已知欠账]
    记过账的缺 = [x for x in _缺 if x in 已知欠账]
    代码有没登记 = [x for x in _多 if x not in 没登记的欠账]
    记过账的多 = [x for x in _多 if x in 没登记的欠账]
    # ⚠️ **名单里有而现在不缺了 → 也要报**(名单过期了)。
    # 一条已经实现了而名单还记着欠账的,和一条真欠着的,
    # **在那张名单上长得一模一样** —— 而前者会让下一个人以为还没做。
    名单过期 = ([x for x in 已知欠账 if x not in set(_缺)]
             + [x for x in 没登记的欠账 if x not in set(_多)])
    # 两边都有、而参数名拼得不一样的 —— **只提示,不拦**。
    名字不一致 = sorted(
        (契约键[k][1], 代码键[k][1]) for k in (set(契约键) & set(代码键))
        if 契约键[k][1] != 代码键[k][1])
    坏 = 0

    if 文档说有实际没有:
        坏 = 1
        print(f"\n  ❌ **文档说有、代码里没有** {len(文档说有实际没有)} 条 —— "
              f"调用方照着 OpenAPI 打过来会拿到 404,"
              f"而文档和契约表全是绿的:")
        for m, p in 文档说有实际没有[:12]:
            print(f"     · {m} {p}")
        if len(文档说有实际没有) > 12:
            print(f"     …… 还有 {len(文档说有实际没有) - 12} 条")
        print("     → 要么把路由写出来,要么把那条登记删掉。"
              "**别只改 OpenAPI** —— 它是生成的")
    else:
        print(f"  ✅ 契约登记的 {len(契约)} 条,代码里都有")

    if 代码有没登记:
        坏 = 1
        print(f"\n  ❌ **代码里有、契约没登记** {len(代码有没登记)} 条 —— "
              f"`endpoints.py` 开头写着「点不出权限的接口不许登记」,"
              f"反过来说:**没登记的接口等于没人检查过它的权限**:")
        for m, p in 代码有没登记[:12]:
            print(f"     · {m} {p}")
        if len(代码有没登记) > 12:
            print(f"     …… 还有 {len(代码有没登记) - 12} 条")
    else:
        print(f"  ✅ 代码里的 {len(代码)} 条,契约都登记了")

    if 记过账的缺 or 记过账的多:
        print(f"\n  📋 已记账的欠账 {len(记过账的缺) + len(记过账的多)} 条"
              f"(**仍然是欠账,只是不算「刚刚多了一笔」**):")
        for x in (记过账的缺 + 记过账的多)[:4]:
            理 = 已知欠账.get(x) or 没登记的欠账.get(x)
            print(f"     · {x[0]} {x[1].rsplit('/', 1)[-1]} —— {理}")
        if len(记过账的缺) + len(记过账的多) > 4:
            print(f"     …… 还有 {len(记过账的缺) + len(记过账的多) - 4} 条")

    if 名单过期:
        坏 = 1
        print(f"\n  ❌ 欠账名单里 {len(名单过期)} 条**已经不欠了** —— "
              f"把它从名单里删掉:")
        for x in 名单过期[:5]:
            print(f"     · {x[0]} {x[1]}")
        print("     ⚠️ 一条已经实现了而名单还记着欠账的,和一条真欠着的,"
              "**在那张名单上长得一模一样** —— 前者会让下一个人以为还没做")

    if 名字不一致:
        print(f"\n  🟡 {len(名字不一致)} 条**路径参数名两边拼得不一样**"
              f"(接口在,只是名字不同)—— **只提示,不拦门禁**:")
        for 契, 码 in 名字不一致[:5]:
            print(f"     · 契约 `{契}`  ←→  代码 `{码}`")
        if len(名字不一致) > 5:
            print(f"     …… 还有 {len(名字不一致) - 5} 条")
        print("     ⚠️ 这**也是个真问题**(前端照 OpenAPI 生成类型),"
              "而它是既有状态、涉及几十条 —— 单独修,别夹在别的改动里")

    if not 坏:
        print("\n  ✅ 两份清单对得上")
        print("     ⚠️ 它只验「**路由在**」—— 不验 handler 干对了事"
              "(那由页面冒烟和集成测试管)")
    return 1 if 坏 else 0


# ── 咬合记录 ──────────────────────────────────────────────────────────
#
# ⚠️ **两个方向都要咬** —— 只验一个方向的话:
# > 一条「契约漏登记」的接口和一条「契约和代码都有」的,
# > 在那个绿勾上长得一模一样 —— 而前者是对所有人开放的。
#
# 实测 2026-10-04:
#   ① 对照先绿                           → ✅ 两份清单对得上
#   ② 往 endpoints.py 加一条不存在的路由  → ❌ **文档说有、代码里没有**,点名它
#   ③ 把某个 router 的 include 注掉       → ❌ **文档说有、代码里没有**,点名那一组
咬合 = [
    ("往 contract/endpoints.py 加一条代码里没有的路径", "文档说有、代码里没有"),
    ("把 main.py 里某个 include_router 注掉", "文档说有、代码里没有"),
]


if __name__ == "__main__":
    # 没在 venv 里跑(认不出 fastapi)→ 转交。带 `--已在venv` 就不再转,
    # **避免无限转交** —— 一个自己转给自己的脚本,
    # 和一个正常跑的,在它没输出之前长得一模一样。
    if "--已在venv" not in sys.argv:
        try:
            import fastapi  # noqa: F401
        except ImportError:
            sys.exit(_转交给venv())
    sys.exit(main())
