#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带 `limit` 的列表接口,**不许把 `len(rows)` 当总数报**。

## 为什么需要它(这个病 2026-10-08 真咬到人了)

澜绣那侧的 `get_lifecycle` 被 `LIMIT 40` 截住,而返回里的「有多少个」报的是
`len(rows)` —— 于是模型照着说「休眠 40 个」,**实际 1395 个**。差 35 倍。

> 一个「真的只有 N 条」和一个「被截断成 N 条」,
> **在那个数字上长得一模一样** —— 而人(和模型)会拿它去做决定,
> 那个决定事后追不回到这个数上。

顺着扫管理后台,**九处同一个病**(知识库列表 / 索引构建 / 试跑记录 /
Agent / 工具 / 待办 / 调用链 / 评测 / 上传)—— 真实数是 98 / 1417 / 73 / 714…
而页面上写着「共 20 条」(默认 limit)。

## 判据

一个函数里只要同时有
   ① SQL 里的 `limit`(`limit :n` 这类绑定,或写死的 `limit 数字`)
   ② 返回里 `"total": len(...)`
就红。**正确写法是 `count(*) over () 全量`** —— 它在同一个查询里算,
而另写一句 `select count(*)` 是**第二份 WHERE**,改条件时会只改一边。

⚠️ 已知盲区(写下来,才和「忘了」分得开):
  · 只认 `"total": len(` 这一种写法 —— 换个键名(`"条数": len(...)`)它看不见。
    **所以这是下限,不是全量**(澜绣那侧的扫法也是这个性质,见 api.py 的
    `factory_chase` —— 那边扫出来一个同病的 `"要人看的回传·条数"`)。
  · 不验「那个 `全量` 真的被用上了」—— 查出来不往返回里放,它照样是绿的。
  · 不验分页游标对不对(`next_cursor` 恒为 None 是另一笔欠账)。
"""
import io
import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
应用 = os.path.join(根, "services", "api", "app")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# 明写豁免:**点名 + 写理由**,不许只写名字
豁免 = {
    # (暂时没有。有了就写在这里,并说清为什么那个 len 就是总数)
}


def main():
    print("\n\033[1m▸ 带 limit 的列表不许把 len(rows) 当总数\033[0m")
    坏, 查了, 用了窗口 = [], 0, 0
    for f in sorted(os.listdir(应用)):
        if not f.endswith(".py"):
            continue
        行们 = io.open(os.path.join(应用, f), encoding="utf-8").read().split("\n")
        for i, L in enumerate(行们):
            if not re.search(r'"total":\s*len\(', L):
                continue
            查了 += 1
            # 往上找这个函数的开头,把函数体切出来
            j = i
            while j > 0 and not 行们[j].lstrip().startswith(("def ", "async def ")):
                j -= 1
            段 = "\n".join(行们[j:i + 1])
            有limit = bool(re.search(r"limit\s+:\w+|limit\s+\d+|LIMIT\s+\d+", 段))
            键 = f"{f}:{i + 1}"
            if 有limit and 键 not in 豁免:
                坏.append((键, 行们[j].strip()[:52]))
    # 顺带数一下正确写法用了几处 —— **样本量为 0 要喊**:
    # 一个「没人犯这个错」和一个「这条检查没扫到任何东西」,在那句 ✅ 上长得一样。
    for f in sorted(os.listdir(应用)):
        if f.endswith(".py"):
            用了窗口 += io.open(os.path.join(应用, f), encoding="utf-8").read().count(
                "count(*) over ()")
    print(f"  扫了 {查了} 处 `\"total\": len(…)` · "
          f"用了 `count(*) over ()` 的地方 {用了窗口} 处")
    if 用了窗口 == 0:
        print(f"  {R}❌ 一处正确写法都没扫到 —— **这不叫「都对」,叫没扫到东西**{D}")
        print(f"     (九处修好之后这个数应该是 9 左右;为 0 多半是路径或后缀变了)")
        return 1
    if 坏:
        print(f"\n  {R}❌ {len(坏)} 处把截断后的条数当成了总数{D}")
        for 键, 谁 in 坏:
            print(f"     {键}  {谁}")
        print(f"\n     改法:在**同一个查询**里加 `count(*) over () 全量`,"
              f"`total` 取它;`len(出)` 另给一个键(`这一页几条`)。")
        print(f"     ⚠️ 别另写一句 `select count(*)` —— 那是**第二份 WHERE**,"
              f"改条件时会只改一边,而两个数不一致**不报错**。")
        print(f"     真不是这个病的,写进这个脚本的 `豁免` 并**说清为什么**。")
        return 1
    print(f"\n{G}  ✅ 没有把 len(rows) 当总数的列表接口{D}")
    print(f"  {Y}⚠️ 盲区:只认 `\"total\": len(` 这一种写法 —— "
          f"换个键名它看不见,所以这是**下限不是全量**{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
