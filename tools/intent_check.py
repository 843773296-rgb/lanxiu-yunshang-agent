#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intent 的检查 —— **一份会漂的流程文档,和没有流程是一回事。**

2026-09-15 读 Anthropic 的《AI-Native SDLC Playbook》之后加的。
那篇文章建议的第一步是「写一份 intent.md,把原始意图留在文件里」,
而这个项目为「写下来但已经不对的说法」栽过好几次 ——
所以这里加的不是一份文档,是**让那份文档会红**。

## 它防的三种漂移,三种都不报错

**① 待办指向一个不存在的 intent。** 交接文档里写着「见 xxx」,而那份文件没有 ——
看的人会以为是自己没找到。

**② 做完了却还挂在待办上。** 实测撞到过:「22 个形制没录」那条在交接文档里
挂了很久,**而它早已清零**。下一个人会去重做一遍。

**③ 「怎么算做完」写成了一句没法验的话。** 「做好了就行」和没写是一回事。
所以判据里点名的检查,必须真的在 `check.sh` 里 ——
状态写着「做完了」的尤其要核:**一个自称做完、而判据已经不存在的 intent,
比没有这份文件更糟**,它会让人以为这件事有人盯着。

## 为什么不核「进行中」的判据

因为那条检查可能**正是这次要加的东西**,还没写出来。
只在状态变成「做完了」的时候才核 —— 那时候它必须在。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "intent")
必填 = ("要解决什么", "怎么算做完", "明确不做什么", "状态")
合法状态 = ("进行中", "做完了", "等人的活", "已否决")

# ── 咬合记录 ────────────────────────────────────────────────────────────
咬合 = [
    ("把 HANDOFF 里一条待办的 [intent: xxx] 删掉",
     "交接文档里每条待办都点名了一个 intent"),
    ("把一条待办的 intent 名改成一个不存在的",
     "点名的 intent 都真的存在"),
    ("把 check.sh 里的 guards_test.py 改名(判据点名的检查从门禁里消失)",
     "说「做完了」的,判据点名的检查真的在 check.sh 里"),
    ("把一份 intent 的「明确不做什么」那一栏改成别的标题",
     "每份 intent 的必填字段都在"),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 是门禁的一步(名, sh):
    """名字要整个出现在某条 `run ` 命令行上，不是在正文里出现过就算。

    子串匹配会放过 `_check.py` 这种**别人名字的一部分**，
    也会放过只写在注释里的名字 —— 两种都不是「门禁盯着它」。
    """
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        if re.search(r"(?:^|[ /])" + re.escape(名) + r"(?:\s|$)", line):
            return True
    return False


def main():
    print("intent · 检查")
    print("=" * 84)
    files = sorted(f for f in os.listdir(DIR)
                   if f.endswith(".md") and f != "README.md")
    docs = {f[:-3]: open(os.path.join(DIR, f), encoding="utf-8").read() for f in files}

    # ── ① 六个字段一个都不许省 ────────────────────────────────────────
    缺 = []
    for name, t in docs.items():
        miss = [k for k in 必填 if f"**{k}**" not in t]
        if miss: 缺.append(f"{name} 缺 {miss}")
    ck("每份 intent 的必填字段都在", not 缺, len(docs),
       "；".join(缺[:3]) if 缺 else
       "**「明确不做什么」是这里面最值钱的一栏** —— "
       "「还没做」和「决定不做」在代码里长得一模一样,而该触发的动作正好相反")

    # ── ② 状态得是这四种之一 ──────────────────────────────────────────
    野 = []
    状态 = {}
    for name, t in docs.items():
        m = re.search(r"\*\*状态\*\*[::]\s*`?([^`\n((]+)`?", t)
        s = (m.group(1).strip() if m else "(没写)")
        状态[name] = s
        if s not in 合法状态: 野.append(f"{name}:{s}")
    ck("状态只能是这四种之一", not 野, len(docs),
       "；".join(野[:3]) if 野 else f"{合法状态}")

    # ── ③ 「做完了」的,判据点名的检查必须真的在 ──────────────────────
    #
    # **这一条才是这套检查的价值所在。** 前两条查格式,这一条查「它说的是不是真的」。
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    断 = []
    n3 = 0
    for name, t in docs.items():
        if 状态.get(name) != "做完了": continue
        n3 += 1
        m = re.search(r"\*\*怎么算做完\*\*[::]\s*(.+?)(?=\n- \*\*|\Z)", t, re.S)
        判据 = m.group(1) if m else ""
        # 判据里点到的**脚本名**,必须能在 check.sh 里找到
        # 2026-09-16 收紧了两处，两处原来都贴着字面而不是含义：
        #
        #   ① 只认 `.py`。而门禁里现在也有 node 步骤（提交闸的自测），
        #      点名了它的 intent 被判成「没点名任何一条检查」——
        #      **判据查的是文件后缀，而它该查的是「这是不是门禁里的一步」。**
        #
        #   ② 只要名字在 check.sh 的正文里出现过就算数（`x in sh`）。
        #      于是注释里提一句、或者一个**名字是别人子串**的写法都能蒙混过去：
        #      `_check.py` 是 `route_check.py` 的子串，任何一份 intent 只要
        #      在判据里写个 `*_check.py` 就自动通过 —— `break-check-skill`
        #      第一版正是这样**碰巧**过的。现在要求它整名出现在 `run ` 那一行上。
        脚本 = set(re.findall(r"`?([a-z][\w-]*\.(?:py|mjs))`?", 判据))
        # `check.sh` 自己不算「门禁里的一步」——它就是门禁本身，提它等于什么都没说。
        脚本 = {x for x in 脚本 if x not in ("check.sh",)}
        # ⚠️ **要求「全部都在门禁里」是错的判据。**
        # 第一次跑就把 `pattern-eval-n04` 判成了错 —— 它的判据点了两条:
        # `pattern_eval.py`(**要花钱、不进 check.sh**)和 `guards_test.py`(在门禁里)。
        # 而「评测不进门禁」是这个项目早就定下的规矩(要凭据、要花钱、结果有波动,
        # 放进门禁会变成随机拦路)。
        #
        # 该验的是「**有没有一条是门禁盯着的**」:全靠手动跑的判据,
        # 等于没有人在盯 —— 而那正是这条检查要防的。
        在 = [x for x in 脚本 if 是门禁的一步(x, sh)]
        丢 = [x for x in 脚本 if not 是门禁的一步(x, sh)]
        if not 脚本:
            断.append(f"{name}:说做完了,而判据里没点名任何一条检查")
        elif not 在:
            断.append(f"{name}:判据点的 {丢} 一条都不在 check.sh 里 —— "
                      f"**全靠手动跑等于没人盯**")
        elif 丢:
            print(f"     ℹ {name} 的判据里 {丢} 不在门禁里(评测要花钱,本来就不进)"
                  f"—— 门禁盯着的是 {在}")
    ck("说「做完了」的,判据点名的检查真的在 check.sh 里", not 断, n3,
       "；".join(断[:3]) if 断 else
       "**一个自称做完、而判据已经不存在的 intent,比没有这份文件更糟** —— "
       "它会让人以为这件事有人盯着")

    # ── ④ 交接文档里每条待办都要点名一个 intent ──────────────────────
    hd = open(os.path.join(ROOT, "HANDOFF.md"), encoding="utf-8").read()
    段 = hd.split("## 没做完的")[1].split("## 别重做")[0] if "## 没做完的" in hd else ""
    待办 = re.findall(r"^\*\*([①②③④⑤⑥⑦⑧⑨].+?)\*\*", 段, re.M)
    指 = re.findall(r"\[intent:\s*([a-z0-9-]+)\]", 段)
    没指 = len(待办) - len(指)
    ck("交接文档里每条待办都点名了一个 intent", 没指 <= 0, len(待办),
       f"{len(待办)} 条待办,只有 {len(指)} 条点了名 —— "
       f"**没点名的那几条,它的来龙去脉会跟着这条待办一起被删掉**"
       if 没指 > 0 else f"{len(待办)} 条都点了")
    幽灵 = [x for x in 指 if x not in docs]
    ck("点名的 intent 都真的存在", not 幽灵, len(指) or 1,
       f"找不到 {幽灵}" if 幽灵 else
       "**写着「见 xxx」而那份文件不在,看的人会以为是自己没找到**")

    # ── ⑤ 《待办清单.md》必须是生成的,而且是**最新**的 ──────────────────
    #
    # 业务要一份「还有哪些没做」的文本。**手写一份的下场这个项目见过**:
    # 「22 个形制没录」那条在交接文档里挂了很久,**而它早已清零**,
    # 下一个人会照着去重做。
    #
    # 所以那份清单由 `tools/make_todo.py` 从 `intent/` 生成、数字从库里现算。
    # 这条检查确认它**没被手改,也没过期**:重新生成一遍,内容该一模一样
    # (只有那一行时间戳和提交号会变)。
    import subprocess, re as _re
    td = os.path.join(ROOT, "待办清单.md")
    if not os.path.isfile(td):
        ck("《待办清单.md》在", False, 0, "**没生成过** —— 跑 python3 tools/make_todo.py")
    else:
        旧 = open(td, encoding="utf-8").read()
        subprocess.run([sys.executable, os.path.join(HERE, "make_todo.py")],
                       capture_output=True, cwd=ROOT)
        新 = open(td, encoding="utf-8").read()
        剥 = lambda t: _re.sub(r"> 生成于 .*\n", "", t)
        同 = 剥(旧) == 剥(新)
        ck("《待办清单.md》是生成的,而且是最新的", 同, len(docs),
           "" if 同 else
           "**内容和现在的 intent/ 对不上** —— 要么有人手改了它,"
           "要么 intent 变了而没重新生成。**一份漂着的待办清单,"
           "会让人去做一件已经做完的事**"
           "\n     ℹ️ **刚刚已经替你重新生成了,记得把它一起提交。**"
           "再跑一次这条会是绿的 —— 那不是问题消失了,是文件已经改好了。"
           "(说这一句,是因为「第一次红、第二次绿」看起来很像门禁在抽风,"
           "而真相是它顺手把活干了却没说。)")

    # ── **重建步骤只许有一处** ────────────────────────────────────────
    # `HANDOFF.md` 原来手写着三步重建命令,而那三步是不全的 ——
    # 照着跑 `./check.sh` 红 26 项,**而库能一直绿只因为没人重建过**。
    #
    # 修法不是把步骤补全再抄一遍(抄的那份照样会漂),
    # 是**让文档指向脚本** —— 步骤只有 `tools/rebuild.sh` 里有一份。
    脚本 = os.path.join(ROOT, "tools", "rebuild.sh")
    交接 = open(os.path.join(ROOT, "HANDOFF.md"), encoding="utf-8").read()
    ck("有一条命令能从零重建",
       os.path.exists(脚本) and os.access(脚本, os.X_OK), 1,
       "`tools/rebuild.sh` —— **「库是可再生的」这句话要有东西兑现它**")
    ck("交接文档指向那个脚本,而不是手抄一遍步骤",
       "tools/rebuild.sh" in 交接, 1,
       "**抄一份步骤到文档里,那份就会漂** —— 而漂了的重建步骤"
       "比没有步骤更糟:人照着跑,以为重建成功了")

    print()
    print(f"  ℹ 现在 {len(docs)} 份:" +
          "、".join(f"{k}({状态[k]})" for k in sorted(docs)))
    if FAIL:
        print(f"\n\033[31m❌ intent {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\n\033[32m✅ intent 全部符合预期\033[0m")
    print("    **一份会漂的流程文档,和没有流程是一回事。**")


if __name__ == "__main__":
    main()
