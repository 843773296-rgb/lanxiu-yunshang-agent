#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页面骨架检查 —— **一块放错了父容器,框架看起来完全正常,内容却整个不见了。**

## 为什么有这条检查

2026-09-24 用户报:对话页「提问不显示我发的字,回答也不显示回答的内容」,
而且说好在右边的侧栏跑到了左边。

查下来不是 JS、不是接口、不是样式写错,是**这块 DOM 放错了父容器**:

    body      display:flex            ← 一「行」:会话列表 | 主区 | 侧栏
    #main     flex-direction:column   ← 一「列」:顶栏 / 聊天流 / 输入框
    #ev       height:100vh; flex:none ← 按「行里的第三列」写的样式

`#ev` 被我加进了 `#main` 里面。同一段 CSS:
**放在行里是一条 380px 宽的右侧栏,放在列里是一堵占满整屏的墙** ——
它把聊天流和输入框整个顶出了可视区。

**三道已有的前端检查都抓不到它**:
  · `js_check` 只验语法 —— 这里根本没有 JS 错
  · `page_smoke_check` 在服务端拿真数据跑入口 —— 页面返回 200,内容也齐
  · `ui_audit` 查控件有没有绑定 —— 按钮都绑着,点了也真的有反应

它们查的都是「零件在不在」,而坏掉的是**零件挂在谁身上**。

## 这条检查怎么判

不看样式、不看像素,只判**父子关系**:用 HTMLParser 把页面的 div 树解出来,
断言几条「必须是兄弟 / 必须是后代」的关系。这些关系是布局成立的前提,
而它们在源码里只是缩进 —— 缩进不会报错。

⚠️ **只钉那些「放错了会静默坏掉」的**,不要把整棵树钉死:
钉死整棵树的话,任何一次正常重构都会红,于是这条检查会被人关掉。
"""
import os, sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

咬合 = [
    ("把 station.html 的 #ev 挪回 #main 里面(它的 height:100vh 会占满整屏,把聊天流顶出去)",
     "#ev 必须和 #main 平级"),
    ("把 #stream 挪出 #main", "#stream 必须在 #main 里"),
]

# (文件, 说明, [(谁, 关系, 谁, 为什么)])
#   平级 = 两者都不能是对方的后代;在内 = 前者必须是后者的后代
规矩 = [
    ("station.html", "对话页", [
        ("ev", "平级", "main",
         "#ev 的样式按「body 这一行的第三列」写(width 控开合、height:100vh)。"
         "放进 #main(列)里会占满整屏,**把聊天流和输入框顶出可视区**,"
         "而页面框架看起来完全正常(2026-09-24 用户实报)"),
        ("stream", "在内", "main", "聊天流要跟着主区伸缩;挪出去就不再受 flex:1 管"),
        ("composer", "在内", "main", "输入框要贴在主区底部"),
        ("side", "平级", "main", "会话列表是这一行的第一列"),
    ]),
]


class 树(HTMLParser):
    def __init__(self):
        super().__init__(); self.栈 = []; self.祖先 = {}

    def handle_starttag(self, t, a):
        if t not in ("div", "aside", "main", "section", "nav"): return
        i = dict(a).get("id")
        self.栈.append(i)
        if i: self.祖先[i] = [x for x in self.栈[:-1] if x]

    def handle_endtag(self, t):
        if t in ("div", "aside", "main", "section", "nav") and self.栈: self.栈.pop()


def 解(path):
    p = 树(); p.feed(open(path, encoding="utf-8").read()); return p


FAIL, N = [], [0]


def ck(名, 真, 补=""):
    N[0] += 1
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:180]) if 补 else ''}")
    if not 真: FAIL.append(名)


def 跑(源=None):
    for 文件, 页名, 条 in 规矩:
        path = os.path.join(WEB, 文件)
        if 源 and 文件 in 源:
            p = 树(); p.feed(源[文件])
        elif os.path.exists(path):
            p = 解(path)
        else:
            ck(f"{页名}:{文件} 在不在", False, "文件不见了"); continue
        缺 = [a for a, _, _, _ in 条 if a not in p.祖先] + \
            [b for _, _, b, _ in 条 if b not in p.祖先]
        if 缺:
            # ⚠️ **找不到不能当成通过。** 这块要是被改名或删了,
            # 「关系成立」和「这块根本不在」在布尔值上长得一样。
            ck(f"{页名}:该有的块都在", False, f"找不到:{sorted(set(缺))}")
            continue
        ck(f"{页名}:该有的块都在", True, f"{len(条)} 条关系要验")
        for a, 系, b, 为什么 in 条:
            祖a, 祖b = p.祖先[a], p.祖先[b]
            行 = (b not in 祖a and a not in 祖b) if 系 == "平级" else (b in 祖a)
            ck(f"#{a} 必须{'和' if 系=='平级' else '在'} #{b} {'平级' if 系=='平级' else '里'}",
               行, "" if 行 else f"现在 #{a} 的祖先是 {祖a} —— {为什么}")


def _自测():
    print("\n咬合:改坏了要红\n" + "-" * 84)
    好 = ('<div id="side"></div><div id="main"><div id="stream"></div>'
          '<div id="composer"></div></div><div id="ev"></div>')
    坏1 = ('<div id="side"></div><div id="main"><div id="stream"></div>'
           '<div id="composer"></div><div id="ev"></div></div>')      # ev 挪回 main 里
    坏2 = ('<div id="side"></div><div id="main"><div id="composer"></div></div>'
           '<div id="stream"></div><div id="ev"></div>')               # stream 挪出去
    过 = []
    for 名, 源, 应红 in (("对照(没改坏)", 好, None),
                        ("把 #ev 挪回 #main 里面", 坏1, "#ev 必须和 #main 平级"),
                        ("把 #stream 挪出 #main", 坏2, "#stream 必须在 #main 里")):
        FAIL.clear(); N[0] = 0
        跑({"station.html": 源})
        中 = (not FAIL) if 应红 is None else any(应红 in f for f in FAIL)
        过.append(中)
        print(f"  {'✅' if 中 else '❌'} 咬合「{名}」→ {FAIL or '全绿'}")
    FAIL.clear()
    return 0 if all(过) else 1


if __name__ == "__main__":
    print("页面骨架 · 谁必须挂在谁身上")
    print("=" * 84)
    跑()
    坏 = list(FAIL)
    rc = _自测()
    print()
    if 坏 or rc:
        print(f"\033[31m❌ 页面骨架 {len(坏)} 处不符合预期\033[0m")
        for f in 坏: print(f"   · {f}")
        print("   **这类错不会报错** —— 框架照常渲染,内容被顶出可视区")
        sys.exit(1)
    print(f"\033[32m✅ 页面骨架全过\033[0m —— 放错父容器的那几块钉住了")
