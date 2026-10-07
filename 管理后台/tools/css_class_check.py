#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**页面上写的 class,CSS 里得真有。** 不然它就是一行普通文字。

2026-10-07 发现:`apps/web/app.js` 里有 **47 处** `class="tag ..."`,
而 `app.css` 里定义的是 **`.pill`** —— 没有 `.tag`。其中 14 处还用了
`crit`,而 CSS 里是 `.fail`。也就是说**47 个状态徽章一直是没样式的普通文字**。

> 一个 `class="pill ok"` 和一个 `class="tag ok"`,
> **在代码里长得几乎一样** —— 而后者什么样式都没有。
> 浏览器对不认识的 class **完全静默**:不报错、不警告、照样渲染。

这是「写了声明 ≠ 声明生效」在前端的一种形状,和这个项目栽过的那几次同族:
`allowed_tools` 不是排他白名单 · `.pyc` 的「防止产生」≠「防止使用」·
规矩写在提示词里 ≠ 结构上拦住。

## 为什么不是在 CSS 里加个 `.tag` 别名

那样会留下两套名字,而**两套名字迟早分叉** —— 分叉时两边各自都「有样式」,
只是不一样。这个仓库为「两套实现」栽过好几次,所以统一成一套。

## 判据

`class="…"` 里的每个**字面** class 名,都要在 CSS 里出现过(任何选择器里)。
动态拼接的部分(`class="pill ${…}"`)追不到 —— **计入「说不清」并钉住个数**,
照 `jsonb_cast_check.py` 的成语:现状几处就钉几处,多一处就红。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "apps", "web")
G, R, D = "\033[32m", "\033[31m", "\033[0m"

# 这些不是样式钩子,是 JS 选择器或语义标记 —— 豁免要写理由
豁免 = {
    # (没有。有了再加,**每条都要写为什么它不需要样式**)
}


def _class值们(行):
    """把**整个文件**里所有 `class="…"` 的值取出来,返回 [(起始偏移, 值)]。

    ⚠️ **按整个文件扫,不按行。** 插值会跨行:

        <td><span class="pill ${r.status === "pending" ? "warn"
                             : "ok"}">            ← `}` 在下一行

    按行扫的话深度永不归零,整行的 JS 片段(`===`、`?`、`"pending"`)
    都被当成 class 名报出来。

    ⚠️ 不能用 `class="([^"]*)"`。模板字符串里的 class 属性值常含嵌套双引号:

        class="wfnode ${g.选中 === n.id ? "sel" : ""} …"
                                          ↑ 正则在这儿就当属性结束了

    于是 `n.id` / `===` / `?` 这些 JS 片段被当成 class 名报出来。
    > 一条「报出 4 个不存在的 class」的检查,和一条「解析截断了所以误报」的,
    > **在那份输出上长得一模一样** —— 而照着误报去改代码是白费功夫,
    > 更糟的是它会让人开始不信这条检查。
    """
    出, i = [], 0
    while True:
        j = 行.find('class="', i)
        if j < 0:
            return 出
        k = j + 7
        深, 值 = 0, []
        while k < len(行):
            if 行[k:k + 2] == "${":
                深 += 1
                值.append(行[k:k + 2])
                k += 2
                continue
            if 深 and 行[k] == "}":
                深 -= 1
            elif not 深 and 行[k] == '"':
                break
            值.append(行[k])
            k += 1
        出.append((j, "".join(值)))
        i = k + 1


def css里定义过的():
    出 = set()
    for 名 in ("app.css",):
        p = os.path.join(WEB, 名)
        if not os.path.isfile(p):
            # ⚠️ 找不到就红 —— 一次「扫过了都对」和一次「CSS 没找到」,
            # 在那个 0 上长得一模一样。
            raise FileNotFoundError(p)
        文 = open(p, encoding="utf-8").read()
        # 去掉注释,免得注释里的 `.xxx` 被当成定义
        文 = re.sub(r"/\*.*?\*/", " ", 文, flags=re.S)
        # 只看选择器部分(每个 `{` 之前),免得属性值里的点被当 class
        for 块 in 文.split("{")[:-1]:
            选 = 块.rsplit("}", 1)[-1]
            出 |= set(re.findall(r"\.(-?[A-Za-z_][\w-]*)", 选))
    return 出


def 页面上用到的():
    """返回 (字面 class 们, [说不清的位置])。"""
    用, 说不清 = {}, []
    for 名 in ("app.js", "index.html"):
        p = os.path.join(WEB, 名)
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        文 = open(p, encoding="utf-8").read()
        换行位 = [i for i, ch in enumerate(文) if ch == "\n"]
        import bisect
        for 偏移, 值 in _class值们(文):
            n = bisect.bisect_right(换行位, 偏移) + 1
            if True:
                if "${" in 值:
                    # ⚠️ **插值里的字符串字面量也要查。** 原来只把 `${…}` 挖掉,
                    # 于是 `class="pill ${x.status === "失败" ? "crit" : "warn"}"`
                    # 里那个 `crit` **完全不在视野里** —— 而那正是它当初
                    # 藏身的地方之一。
                    # 判据很干净:插值里那些**看起来就是 class 名**的字面量
                    # (纯 ASCII、标识符形状)才查;`"已就绪"` 这种中文一眼
                    # 就不是 class,跳过。
                    # > 一个「查了字面部分」的检查,和一个「连插值里的
                    # > 修饰词一起查了」的,**在那行输出上长得一模一样** ——
                    # > 而前者放过的恰好是最容易写错的那一半(修饰词)。
                    for 插 in re.finditer(r"\$\{([^}]*)\}", 值):
                        # ⚠️ **只取 `?` 之后的字符串字面量。**
                        # `p["级别"] === "blocking" ? "b" : "w"` 里:
                        #   `blocking` 在比较位置 —— 它是个**状态值**,不是 class
                        #   `b` / `w` 在结果位置 —— 它们才是 class
                        # 不分开的话这条检查会报「.blocking 不存在」,
                        # > 而一条「报了个不该报的」的检查,和一条真抓到问题的,
                        # > **在那行红字上长得一模一样** ——
                        # > 区别是前者会让人开始不信它。
                        # 判据:**紧跟在 `?` 或 `:` 后面**的字符串字面量。
                        # 「第一个 `?` 之后的全部」不够精确 —— 嵌套三元
                        # `? "warn" : (x === "approved" ? "ok" : "fail")`
                        # 里那个 `approved` 也在第一个 `?` 之后,
                        # 而它仍然是个**比较值**。
                        for 串 in re.findall(
                                r"""[?:]\s*["']([^"']*)["']""", 插.group(1)):
                            if re.fullmatch(r"[a-z][\w-]*", 串):
                                用.setdefault(串, []).append((名, n))
                    说不清.append((名, n, 值[:46]))
                    值 = re.sub(r"\$\{[^}]*\}", " ", 值)
                for c in 值.split():
                    if c and not c.startswith("$"):
                        用.setdefault(c, []).append((名, n))
    return 用, 说不清


# 现状:动态拼 class 的地方有 **19 处**(2026-10-07 数出来的,不是猜的 ——
# 第一版我凭印象钉了 6,实际 19)。**多一处就红**:新增的追不到必须当场
# 被看见,而不是悄悄涨上去。
# ⚠️ 这 19 处里**字面部分和插值里的字符串字面量都查过了**,追不到的只剩
# 变量本身(`${cls}`、`${g.底Tab === …}` 这种)。所以它不是「19 处没查」,
# 是「19 处里各有一小段没查」—— 措辞要分得开,否则读起来像一大片盲区。
说不清上限 = 19


def main():
    print("\n\033[1m▸ 页面上写的 class,CSS 里得真有\033[0m")
    try:
        定义 = css里定义过的()
        用, 说不清 = 页面上用到的()
    except FileNotFoundError as e:
        print(f"  {R}❌ 找不到 {e} —— 这不是「通过」{D}")
        return 1
    print(f"  CSS 里定义了 {len(定义)} 个 class · 页面上用了 {len(用)} 个")
    野 = {c: v for c, v in sorted(用.items()) if c not in 定义 and c not in 豁免}
    if 说不清:
        print(f"  {len(说不清)} 处 class 是**拼出来的** —— "
              f"字面部分和插值里的字符串字面量都查了,只剩变量本身追不到:")
        for 名, n, 片 in 说不清[:8]:
            print(f"     {名}:{n}  class=\"{片}…\"")
    if len(说不清) > 说不清上限:
        print(f"\n  {R}❌ 拼出来的 class 有 {len(说不清)} 处,超过钉住的 {说不清上限} 处{D}")
        print("     新增的要么改成字面,要么确认过之后把上限改大**并写清为什么**。")
        return 1
    if 野:
        print(f"\n  {R}❌ {len(野)} 个 class 在 CSS 里不存在 —— "
              f"它们是**没有样式的普通文字**,而浏览器完全静默{D}")
        for c, 处 in 野.items():
            # ⚠️ 提示要么有用要么别说。原来按前 3 字符匹配,于是 `.btn`
            # 被提示成「是想写 ['n','b','t'] 吗?」—— 那三个是 CSS 里真有的
            # 单字母 class(`.kpi .n`、`input.t`),而这个提示毫无帮助。
            # > 一个没用的提示和没有提示,**在那行输出上长得差不多** ——
            # > 但前者更糟:它让人以为检查给了线索,去顺着查。
            近 = [x for x in 定义
                  if len(x) >= 3 and (x.startswith(c) or c.startswith(x))][:3]
            print(f"     .{c}  用了 {len(处)} 处(如 {处[0][0]}:{处[0][1]})"
                  + (f" —— 是想写 {近} 吗?" if 近 else ""))
        return 1
    print(f"\n{G}  ✅ 页面上每个字面 class 都在 CSS 里有定义;"
          f"拼出来的 {len(说不清)}/{说不清上限} 处{D}")
    return 0


# ── 咬合(2026-10-07 实跑,下面的「预期红」是**抄的真实输出**)────────────
#   ① 对照                                → ✅ …拼出来的 19/19 处
#   ② 把一处 `class="pill ok"` 改成 `tag`  → ❌ 1 个 class 在 CSS 里不存在
#                                             `.tag  用了 1 处(如 app.js:267)`
#   ③ 把 app.css 临时改名                  → ❌ 找不到 …/app.css —— 这不是「通过」
#
# ⚠️ 第 ② 关**没有**给出「是想写 pill 吗?」的提示 —— `tag` 和 `pill` 之间
# 没有包含关系,而提示判据收紧成了「长度≥3 且真有包含关系」。
# 这一行原来是我**凭想象写的**(以为它会提示),实跑之后改成了真实输出。
# > 一条凭记忆写的咬合记录,和一条抄下来的,**在注释里长得一模一样** ——
# > 而前者会让下一个人照着一个不存在的输出去判断检查有没有生效。
# 这个坑在这个项目里栽过三次,修法固定:**去跑一遍,抄它真说的那句话。**
if __name__ == "__main__":
    sys.exit(main())
