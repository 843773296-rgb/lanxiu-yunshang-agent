#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台页面里不许再用浏览器原生的 alert / confirm / prompt(10-26 换完,方案 §10.2 点名)。

原生弹框的三个毛病:**露内部码**(用户 10-26 截图里就是 `VALIDATION write2.config.connection_version_id`)、
**加粗不渲染**(满屏星号)、**整页卡住**。页面里有 `提示()` / `问一句()` / `报错()` 三个替代。

判据落在「调用」这个结构上:去掉注释之后,`alert(` / `confirm(` / `prompt(` 前面不是标识符字符、不是点
(`window.confirm(` 也算,`x.alert(` 这种别的对象的方法不算 —— 但 `window.` 开头的照样拦)。
样本量:扫了几个文件、几行,先报出来 —— 一个文件都没扫到不叫「没有」。
"""
import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
目录 = os.path.join(根, "apps", "web")
调用 = re.compile(r"(?:(?<![\w.$])|window\.)(alert|confirm|prompt)\s*\(")
咬合 = [("在 app.js 里塞回一句 alert(\"x\")", "后台页面没有原生弹框")]


def 去注释(行, 在块注释):
    """粗剥注释:/* … */ 跨行、// 到行尾。字符串里的 // 会被误剥 —— 只会少报不会多报,配合咬合验得到真调用。"""
    出 = ""
    i = 0
    while i < len(行):
        if 在块注释:
            j = 行.find("*/", i)
            if j < 0:
                return 出, True
            i, 在块注释 = j + 2, False
            continue
        if 行.startswith("/*", i):
            在块注释 = True
            i += 2
            continue
        if 行.startswith("//", i) and (i == 0 or 行[i - 1] != ":"):
            break
        出 += 行[i]
        i += 1
    return 出, 在块注释


def main():
    文件们 = sorted(f for f in os.listdir(目录) if f.endswith(".js"))
    行数, 坏 = 0, []
    for f in 文件们:
        块 = False
        for n, 行 in enumerate(open(os.path.join(目录, f), encoding="utf-8"), 1):
            行数 += 1
            码, 块 = 去注释(行.rstrip("\n"), 块)
            for m in 调用.finditer(码):
                坏.append(f"{f}:{n}  {m.group(1)}(  ← {行.strip()[:80]}")
    print(f"▸ 后台页面原生弹框:扫了 {len(文件们)} 个 JS 文件、{行数} 行")
    if not 文件们 or 行数 == 0:
        print("  ❌ 一个文件都没扫到 —— 这不叫没有,叫没查")
        return 1
    if 坏:
        print(f"  ❌ 还有 {len(坏)} 处原生弹框 —— 换成页面里的 提示() / 问一句() / 报错():")
        for x in 坏[:10]:
            print("     ·", x)
        return 1
    print("  ✅ 后台页面没有原生弹框(alert / confirm / prompt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
