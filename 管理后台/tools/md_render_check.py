#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**页面上的 `**加粗**` 要真的渲染成加粗,别把星号显示给人看。**

2026-10-08 用户验收时一眼看到的:知识库页上写着

    资料、片段、索引。**有片段不等于能检索** —— 要有一个「已就绪」的索引。

那两个星号**是字面显示的**。原因是这些文案直接写进 HTML,
而把 `**` 变成 `<b>` 的是 `md()`,它们没经过它。全站量到 **30 处**。

> 一句「写了加粗」的文案,和一句「加粗真的生效了」的,
> **在源码上长得一模一样** —— 而页面上一个是粗体、一个是两个星号。

## 为什么没有任何检查抓到它

`page_smoke.js` 验「取到数、渲染了、节点被填充」;`page_render_check.js`
验「每个页面函数跑得起来」;`css_class_check.py` 验「class 在 CSS 里有」。
**没有一条验「这段文字在页面上长什么样」** ——
而这正是昨天那个 `[object Object]` 和今天这个星号的共同点:
**它们都要人用眼睛看一眼才看得见。**

这条检查把其中**可机检的那一半**接住:文案里写了 `**…**` 却没过 `md()`。
(另一半 —— 排版好不好看 —— 仍然要人看,这条不假装覆盖它。)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "apps", "web")
G, R, D = "\033[32m", "\033[31m", "\033[0m"


def main():
    p = os.path.join(WEB, "app.js")
    if not os.path.isfile(p):
        # ⚠️ 找不到文件要喊 —— 一次「扫过了没犯规」和一次「文件没找到」,
        # 在那个 0 上长得一模一样。
        print(f"  {R}❌ 找不到 {p} —— 这不是「通过」{D}")
        return 1
    t = open(p, encoding="utf-8").read()
    坏 = []
    for m in re.finditer(r'<div class="((?:sub|note)[^"]*)">([^<]{0,600})', t):
        内 = m.group(2)
        if "**" in 内 and "${md(" not in 内:
            坏.append((t[:m.start()].count("\n") + 1, m.group(1),
                       内.strip().replace("\n", " ")[:56]))
    print("\n\033[1m▸ 页面文案里的 `**加粗**` 真的渲染了吗\033[0m")
    print(f"  扫了 app.js 里的 .sub / .note 文案")
    if 坏:
        print(f"\n  {R}❌ {len(坏)} 处写了 `**…**` 却没过 `md()` —— "
              f"页面上显示的是**字面的星号**{D}")
        for 行, 类, 片 in 坏[:10]:
            print(f"     第 {行} 行 .{类}: {片}")
        print("     改法:把文案包进 `${md(`…`)}`。")
        return 1
    print(f"\n{G}  ✅ 没有写了加粗却不渲染的文案{D}")
    print("     ⚠️ 它只接住**可机检的那一半** —— 排版好不好看仍然要人看一眼")
    return 0


# ── 咬合(2026-10-08 实跑,预期红抄的真实输出)────────────────────────
#   ① 对照                                  → ✅ 没有写了加粗却不渲染的文案
#   ② 把一处 `${md(`…`)}` 还原成裸文案        → ❌ 1 处写了 `**…**` 却没过 `md()`
if __name__ == "__main__":
    sys.exit(main())
