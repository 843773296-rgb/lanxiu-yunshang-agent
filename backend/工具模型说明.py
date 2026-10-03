#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具的「模型说明」—— **三样东西拼进 description 的唯一一处实现**。

## 这个文件存在的理由

2026-10-03 量出来一件事(`管理后台/docs/选型/结论-工具筛选-20261003.md`):

> **用户问的是业务,工具说明写的是系统。**

两个独立留出集在同一处失败 —— **5 道题的「需要的工具」和「用户的问法」
一个共同片段都没有**:

    藏青 S 码那件马面裙现在还能发几件?   需要「查现货」    零重叠
    灰缬能做在浅色棉麻上吗?              需要「相容矩阵」  零重叠
    我今天有什么活? / 今天该我核什么?                     零重叠
    PT01 这个版型的裁片用料占比是多少?                     零重叠

规格 §8.2 要的三样正好对着这件事:**别名**(业务话→系统话)、
**适用/不适用**(什么时候该用它)、**任务示例**(真实问法)。

## 真值在这边,后台是镜像(2026-10-03 业务拍板)

数据在 `工具模型说明.json`。后台 `管理后台/tools/import_lanxiu_tools.py`
把它导进 `tool_versions`,§8.2 那个页签**只读**。

反过来做(在后台界面上填)业务否掉了,理由是两条:
① 后台界面冻结出来的版本,内容哈希算法和导入那套**永远不可能相等** ——
   第三条同步判据会红,而它报的理由是「内容不一致,去跑导入」,指向一个错方向;
② 后台填的东西**澜绣线上读不到**(澜绣不从后台的库读工具说明)——
   那会出现「后台上看起来配好了,而线上一个字没变」。

## ⚠️ 拼法只许有一处

`拼进三份()` 必须在 **`api.py` 里**调用,也就是三个 SCHEMAS 列表的源头 ——
**不许改 `mcp/*_server.py` 那三行**。

理由是 `mcp/parity.py` 有一条判据盯着「MCP 这条路和直连那条路的
name/description/input_schema 必须一字不差」。只在 MCP 侧拼会让它当场红,
而那条判据是对的:两条路给模型的说明不一样,比两条路都没说明更糟 ——
**线上走哪条路取决于部署方式,而说明不同的那一天没人会注意到。**

## ⚠️ 这里决定了「填了到底有没有用」

这三样如果不进 `description`,后台那个页签就是一个
**看起来在配模型、而模型一个字也收不到**的界面 ——
库里有数据、页面上显示得好好的。

> **把「声明」当成了「生效」。** 这个仓库 10-03 一天里栽过三次。

所以 `已经拼进去了吗()` 是给判据用的:它答「现在跑着的 SCHEMAS 里
到底有没有这些内容」,而不是「文件里有没有」。
"""
import json
import os

_这儿 = os.path.dirname(os.path.abspath(__file__))
数据文件 = os.path.join(_这儿, "工具模型说明.json")

# 任务示例的来路。**枚举它是有意的** —— 一条编的例子和一条真实问法长得一样,
# 而它们在「值不值得照着优化」上差很远。
# ⚠️ 「评测题」和「记录仪」分开:那 121 条确实挖自 trace 日志,
# 但它们是评测题的问法,不是真实顾问问的。
# 和后台 `capabilities.来路们` 保持一致(后台那边有同一条枚举,
# 两处不一致时导入会被后台的闸拒 —— 那就是它该干的事)。
来路们 = ("记录仪", "业务口述", "评测题", "现编")


def 读():
    with open(数据文件, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("工具们") or {}


def 查(名):
    """一个工具的三样。没有就返回空字典(**不是三个空列表**)。

    ⚠️ 「没有这个键」和「这个键是空的一串」是两件事:
    前者是**没人说过**,后者是**有人看过、确认它不需要**。
    这一层不替任何人把前者变成后者。
    """
    一条 = 读().get(名) or {}
    return {k: 一条[k] for k in ("别名", "适用不适用", "任务示例") if k in 一条}


def 拼一段(说明, 名):
    """把三样拼进一条工具的 description。**后台的预览拼的是同一套顺序和字样。**

    ⚠️ 连「不适用」也发给模型:只发「适用」等于告诉模型「处处适用」,
    而上面那 5 道零重叠题缺的正是「什么时候**不**该用它」。

    ⚠️ 「现编」的示例也发 —— `来源` 那个枚举管的是**证据分量**
    (别拿现编的当评测真值),不是「能不能给模型看」。
    一句编得像的问法,对模型认出用户在问什么照样有用。
    """
    三样 = 查(名)
    段 = [(说明 or "").strip()]
    w = 三样.get("适用不适用") or {}
    if isinstance(w, dict):
        if w.get("适用"):
            段.append("适用于:" + ";".join(str(x) for x in w["适用"]))
        if w.get("不适用"):
            段.append("不适用于(这些情况下别调它):"
                      + ";".join(str(x) for x in w["不适用"]))
    if 三样.get("别名"):
        段.append("用户可能这么说:" + "、".join(str(x) for x in 三样["别名"]))
    例 = 三样.get("任务示例") or []
    问法 = [str(x.get("问法")) for x in 例 if isinstance(x, dict) and x.get("问法")]
    if 问法:
        段.append("真实问法举例:" + " | ".join(问法))
    return "\n".join(x for x in 段 if x)


def 拼进三份(*列表们):
    """给 `api.py` 用:按原顺序返回拼好的三份 SCHEMAS。

    ⚠️ **不原地改**(不 mutate 传进来的那几个 list):原地改的话,
    `api.py` 被重复导入或测试里重复调用会**拼两遍** ——
    而拼两遍的 description 看起来只是啰嗦了一点,
    模型那边却是同一句话说了两次,没有任何东西会报错。
    """
    出 = []
    for 列 in 列表们:
        出.append([{**s, "description": 拼一段(s.get("description"), s["name"])}
                   for s in 列])
    return tuple(出) if len(出) > 1 else 出[0]


def 已经拼进去了吗(schemas):
    """**现在跑着的 SCHEMAS 里到底有没有这些内容** —— 给判据用。

    回答的不是「文件里有没有」(那永远是「有」),而是
    「`api.py` 那一行接线还在不在」。没有它的话,这一整份数据
    **躺在仓库里而模型一个字都收不到**。

    返回 (拼了的工具数, 该拼的工具数, 没拼上的名字们)。
    """
    该 = 读()
    S = {s["name"]: (s.get("description") or "") for s in schemas}
    该的 = [n for n in 该 if n in S]
    漏 = []
    for n in 该的:
        想要 = 拼一段("", n)
        # 用「第一条真实问法」当探针:它够长够独特,不会碰巧出现在原说明里。
        例 = (该[n].get("任务示例") or [{}])[0].get("问法")
        if 例 and 例 not in S[n]:
            漏.append(n)
        elif not 例 and 想要 and 想要 not in S[n]:
            漏.append(n)
    return len(该的) - len(漏), len(该的), sorted(漏)


if __name__ == "__main__":
    import sys
    d = 读()
    条 = sum(len(v.get("任务示例") or []) for v in d.values())
    print(f"工具模型说明:{len(d)} 个工具 · {条} 条任务示例")
    坏 = []
    for 名, v in d.items():
        for i, x in enumerate(v.get("任务示例") or []):
            if x.get("来源") not in 来路们:
                坏.append(f"{名} 第 {i+1} 条的来源 {x.get('来源')!r} 不在枚举里")
            if not (x.get("问法") or "").strip():
                坏.append(f"{名} 第 {i+1} 条没写问法")
        w = v.get("适用不适用")
        if isinstance(w, dict) and bool(w.get("适用")) != bool(w.get("不适用")):
            坏.append(f"{名} 的适用/不适用只给了一边 —— 后台的闸会拒")
    有别名 = [n for n, v in d.items() if v.get("别名")]
    有场景 = [n for n, v in d.items() if v.get("适用不适用")]
    print(f"  有别名的:{len(有别名)} 个 · 有适用/不适用的:{len(有场景)} 个")
    if not 有别名:
        print("  ⚠️ **一个工具都没有真别名**(短词组那种)—— 这是真实状态,"
              "不是漏了。那 121 条是完整问法,进的是「任务示例」。")
    try:
        import api
        好, 该, 漏 = 已经拼进去了吗(api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS)
        if 漏:
            print(f"  ❌ **这 {len(漏)} 个没拼进 SCHEMAS**:{漏[:6]}")
            print("     `api.py` 末尾缺这一行(两条路共同的源头,不许改 mcp/*_server.py):")
            print("       import 工具模型说明 as _说明")
            print("       SCHEMAS, SHOP_SCHEMAS, KB_SCHEMAS = "
                  "_说明.拼进三份(SCHEMAS, SHOP_SCHEMAS, KB_SCHEMAS)")
            坏.append(f"{len(漏)} 个工具的说明没拼进 SCHEMAS —— 模型收不到")
        else:
            print(f"  ✅ {好}/{该} 个真的拼进 SCHEMAS 了(模型收得到)")
    except Exception as e:
        print(f"  ⏸ 没法验「拼进去了没」:{e}")
    for x in 坏:
        print("   ❌", x)
    sys.exit(1 if 坏 else 0)
