#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导航 —— **一份清单,所有页面共用。**

## 为什么要有这个文件

2026-09-25 用户报:「运维平台为什么有两个,而且两个的头部 tab 也不一致,很多功能还缺入口,
chat 进入平台后就回不来了」。查下来比他看到的更乱:

    · 17 个页面里**只有 7 个**带统一顶栏
    · 导航第一项写着「值班台」,点进去是 **station.html(智能助手对话页)**;
      而真正的值班台 duty.html **压根不在导航里** —— 名字和目标不是一回事
    · 面板 / 任务 / 着装人 / AI 调控中心 / 调试后台 / 实验对比,都有页面,导航上没有

根因是**导航是手写在 _shell.txt 里的一段 HTML**:加页面的人不会想起来去改它,
而漏改**不会报错** —— 只会让那个页面从此没人点得到。

所以改成登记制:**这份清单是唯一来源**,顶栏由它现渲染,
并且有一条检查断言「PAGES 里每一条都在这份清单里」——
新增页面不登记就红,而新增的那个人正是最需要被拦住的。

## 分组照用户定的信息架构(2026-09-25)

    顶栏   AI 那一层(对话 / 值班 / 研判 / 面板 / 方案 / 试跑 / 验收 / 着装人 / 健康 / 调控)
    /ops   业务后台那一套(它自己带左侧 10 大类菜单)—— 并到同一个端口上,不再是「另一个平台」

⚠️ **「不挂顶栏」必须写理由。** 手机端、平板端、登录页是**另一批人**用的入口,
挂到员工的顶栏上只会让人点进去一脸茫然;而调试后台和实验对比从 /ai 进,
不占顶栏是为了别让门店同学误入。**这些都是决定,不是遗漏** —— 写下来才分得开。
"""

# (路径, 顶栏上的名字, 一句话它是什么)
顶栏 = [
    ("/",            "对话",       "智能助手主对话页(station)—— 五个角色都从这儿进"),
    ("/duty",        "值班台",     "今天该看什么:积压、超时、等你复核的"),
    ("/queue",       "研判队列",   "智能体交草稿、你签字;改判会回流评测集"),
    ("/fabric",      "面料学堂",   "面料学习 / 速记卡 / 现场练习 —— 从原来那个「面板」里拆出来的"),
    ("/scheme",      "方案配置",   "客户的定制方案(一个客户可以多条同时锁定)"),
    ("/workbench",   "单条试跑",   "拿一条真任务试智能体,不落库"),
    ("/acceptance",  "回归验收",   "改完之后跑一遍,看有没有退步"),
    ("/wearers",     "着装人",     "身体的生命周期(和会员生命周期不是一回事)"),
    ("/health",      "智能体健康", "上线之后没有标准答案,能拿到的是采纳率"),
    ("/ai",          "AI 调控中心", "trace / span / 判分器 —— 自己调试用"),
    ("/ops",         "后台运营",   "业务后台(客户 / 商品 / 交易 / 售后 / 系统…),自带左侧 10 大类"),
]

# ── 删掉的页面(2026-09-25,用户:「后台合并后,废弃的页面帮我删干净」)──────
# `/chat`(工艺顾问单页)**已删**。判定依据 —— 逐条查过才删的:
#   · 它只支持 `kb` 一个角色,而 station 支持全部五个 —— **功能上是真子集**
#   · 它唯一独有的是一个评分条(读 `/api/chat-eval` 显示工艺问答的分数),
#     而 `/ai/evals` 现在把**所有**评测都列了,严格更强
#   · 没有任何检查依赖它;唯一还链着它的是 duty.html 那张卡,已改指主对话
# ⚠️ **留这条注释是为了防止有人又建一个。** 删掉的东西不写下来,
# 下一个人看不到「这条路走过、走不通」,只会重新走一遍。
删掉的 = {
    "/chat": "工艺顾问单页 —— station 支持全部五个角色,它只有一个;评分条由 /ai/evals 取代",
    # 用户 2026-09-25 看截图发现的:**面板和顶栏叠了两条导航**,而且比样式问题更深 ——
    # 面板里那条 nav 不是跳页面,是**页内切五个视图**:值班台 / 研判队列 / 面料学堂 /
    # 着装人 / 智能体健康。其中四个**已经有独立页了,取的还是同一批接口** ——
    # 同一件事两个入口、两个实现,而两边会各自演化。
    # 独立页那一版做得更全(研判队列有采纳/改判/升级整套、值班台能批量研判),
    # 所以删面板、把它独有的「面料学堂」拆成 /fabric。**一件事一个入口。**
    "/panels": "五合一的旧看板 —— 四个视图都有独立页了(同一批接口),独有的面料学堂已拆成 /fabric",
}

# 路径 → 为什么不挂顶栏。**每一条都是决定,不是遗漏。**
不挂 = {
    "/login":       "登录页 —— 没登录的时候才看得见它,挂在顶栏上是循环",
    "/m":           "**客户**手机端自助预约(唯一不用登录的入口)—— 不是给员工的",
    "/pad":         "顾问在平板上看单子的那一版 —— 换设备用,不换页面",
    "/tasks":       "任务列表 —— 从对话页顶栏和值班台进,不再占一格顶栏",
    "/debug":       "单次运行的调用树 —— 从 AI 调控中心进;不挂是**不想让门店同学误入**",
    "/experiments": "实验对比 —— 同上,从 AI 调控中心进",
}


# 导航的样式也在这儿 —— **结构和样式同一个来源**。
# 2026-09-25 之前它有 5 份拷贝(_shell.txt + chat/scheme/workbench/acceptance 各一份),
# 而拷贝之间已经漂了:四个页面的导航都还是 7 项的旧版,第一项还指着错页面。
# 那几个变量(--paper/--ink-2/…)由各页自己的配色定义提供,所以这段样式到哪都成立。
样式 = """.sitenav{display:flex;align-items:center;gap:4px;flex-wrap:wrap;padding:0 26px;height:52px;
 background:var(--paper);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:50;
 font-family:var(--sans);font-size:13.5px}
.sitenav a{color:var(--ink-2);text-decoration:none;padding:6px 12px;border-radius:4px}
.sitenav a:hover{background:var(--paper-2);color:var(--dye)}
.sitenav a[aria-current]{background:var(--dye-soft);color:var(--dye);font-weight:600}
.sitenav .brand{font-weight:600;color:var(--ink);margin-right:10px;padding-left:0}
/* 占位符没被替换时(比如这份页面被旧端口直接吐出来),整条自己藏起来。
   CSS 的 :empty 不把注释算成内容,所以 `<nav><!--占位--></nav>` 正好是空的。 */
.sitenav:empty{display:none}
.sitenav a.ops{margin-left:8px;border:1px solid var(--line);color:var(--dye)}
.sitenav a.ops:hover{background:var(--dye-soft)}
.sitenav .core{margin-left:auto;color:var(--ink-3);font-size:11.5px;font-family:var(--mono)}
.sitenav a.ops{margin-left:8px;border:1px solid var(--line);color:var(--dye)}
.sitenav a.ops:hover{background:var(--dye-soft)}"""


def 顶栏html(当前=None, 带样式=True):
    """现渲染顶栏。**不生成文件** —— 生成物会漂,而漂了不报错。"""
    def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;")
    出 = ['<a class="brand" href="/">澜绣云裳 · 智能运维平台</a>']
    for 路, 名, 说 in 顶栏:
        cur = ' aria-current="page"' if 路 == 当前 else ""
        外 = ' class="ops"' if 路 == "/ops" else ""
        出.append(f'<a href="{路}" data-p="{路}" title="{esc(说)}"{cur}{外}>{esc(名)}</a>')
    出.append('<span class="core">内核 Claude Agent SDK · 工具经 MCP 挂载</span>')
    头 = f"<style>{样式}</style>\n  " if 带样式 else ""
    return 头 + "\n  ".join(出)


def 全部登记的():
    return {路 for 路, _, _ in 顶栏} | set(不挂)


if __name__ == "__main__":
    print(f"顶栏 {len(顶栏)} 项:", "、".join(名 for _, 名, _ in 顶栏))
    print(f"明确不挂 {len(不挂)} 项:")
    for 路, 为什么 in 不挂.items():
        print(f"   {路:14s} {为什么}")
