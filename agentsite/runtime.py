#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能体的**运行目录** —— 故意放在项目之外。

## 为什么单独一个文件

这段逻辑本来写在 `sdk.py` 里,而 `sdk.py` 要 `claude_agent_sdk`(只装在 venv)。
边界审计跑在系统 python3 上,`import sdk` 直接炸 —— 于是那条攻击**一次都没跑过**,
而它每次都绿。**跑不起来的攻击不叫「被拦下」,它什么都没验。**

所以这份**不 import 任何重东西**,谁都拿得起来。

## 这个目录解决的是什么

CLI 会从工作目录**一路往上找 CLAUDE.md**,当成项目记忆塞进系统提示词。
`cwd` 原来是 `agentsite/`,于是项目根那份**工程手册**
(安全红线的描述、密钥文件路径、踩过的坑)整份进了模型的提示词。

不是推断,是问出来的:直接问它「你的提示词里有没有一份叫 CLAUDE.md 的文件」,
它答「有」,并原样抄出了第一行。

两个代价:**评测会失真**(它可以从手册里答题,而不是从知识库,
TL01「只说知识库里查到的」被架空),以及内部信息暴露给模型。

两条路试过,代价不一样:

    setting_sources=[]          泄露没了,**但 Skill 也不上场了**
                                (实测:同一句报价问题,设 project 时轨迹里有
                                 `Skill`,设空时没有)
    cwd 挪出项目 + 链 .claude   **两头都拿到了** ← 现在这条

**放在项目外是这条方案的前提,不是随手选的位置**:
只要它还在项目里,往上一走就又撞见 CLAUDE.md。

目录自动建,所以**「克隆下来就能跑」没有被牺牲**。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.expanduser("~/.lanxiu-runtime")


def ensure():
    """建好运行目录,并把 `.claude` 指回项目里的那一份,返回目录路径。

    **用软链不用拷贝** —— 拷一份的下场这个项目见过好几次:
    同一个事实两个来源,改了这边不改那边,而**不一致时不报错**。
    软链建不起来的系统退回拷贝。
    """
    src = os.path.join(HERE, ".claude")
    dst = os.path.join(RUNTIME, ".claude")

    # ── 三道护栏。**第一版没有,而它当场把技能目录删了。** ──────────────
    #
    # 怎么发生的:咬合测试把 `RUNTIME` 改成了 `HERE`(为了验「运行目录挪回
    # 项目里会不会红」)。于是 src 和 dst **变成了同一个路径** ——
    # 那一行 `shutil.rmtree(dst)` 删掉的是**真的技能目录**,
    # 紧接着 `os.symlink(src, dst)` 又建了一个指向自己的链。
    # 239 个技能没了,`ls` 报「Too many levels of symbolic links」。
    #
    # 三个自己写的字都没错,错在**没有一行拦住「src 就是 dst」这种情况**。
    # 这个项目的规矩里本来就有一条:**删之前先看一眼要删的是什么**。
    # 而这段代码每次起服务都会跑。
    #
    # (技能是从 git + `tools/install_accio_skills.py` 恢复的,一个没少。)
    # ⚠️ 比的是**路径本身,不是它指到哪**。
    # 第一版用 `realpath` 比 src 和 dst —— 而正常情况下 dst 本来就是
    # 一条**指向 src 的软链**,realpath 一解析,两边当然相等,
    # 于是护栏在**正确的状态下**就开火了。
    # **护栏拦住正确的情况,和护栏不存在,都会让人把它拆掉。**
    项目根 = os.path.realpath(os.path.dirname(HERE))
    if os.path.realpath(RUNTIME) == 项目根 or \
            os.path.realpath(RUNTIME).startswith(项目根 + os.sep):
        raise RuntimeError(
            f"运行目录 {RUNTIME} 落在项目里({项目根})—— **拒绝动手**。"
            "两个理由,每一个都够:① 这条路径下一步会把源目录删掉,"
            "而它就是技能本体;② 运行目录在项目里的话,"
            "CLI 往上一走就又撞见 CLAUDE.md —— **在项目之外是这个方案的前提**")
    if os.path.abspath(dst) != os.path.join(os.path.abspath(RUNTIME), ".claude"):
        raise RuntimeError(f"要动的目标 {dst} 不在运行目录里 —— **拒绝动手**")
    if not os.path.isdir(src):
        raise RuntimeError(f"项目里的 {src} 不在 —— 先确认它是不是被删了,"
                           "**不要在这种状态下建链**(会建出一个指向空处的链,"
                           "而服务照样起得来,只是一个技能都不上场)")

    os.makedirs(RUNTIME, exist_ok=True)
    if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(src):
        return RUNTIME
    if os.path.islink(dst) or os.path.exists(dst):
        import shutil
        (os.unlink if os.path.islink(dst) else shutil.rmtree)(dst)
    try:
        os.symlink(src, dst)
    except OSError:
        import shutil
        shutil.copytree(src, dst)
    return RUNTIME


def 往上找(起点=None, 名="CLAUDE.md"):
    """从运行目录一路走到根,把撞见的都列出来。**给边界审计用。**"""
    d, out = os.path.realpath(起点 or ensure()), []
    while True:
        f = os.path.join(d, 名)
        if os.path.exists(f): out.append(f)
        nd = os.path.dirname(d)
        if nd == d: return out
        d = nd


if __name__ == "__main__":
    print("运行目录:", ensure())
    print("往上撞见的 CLAUDE.md:", 往上找() or "一个都没有 ✅")
    sk = os.path.join(RUNTIME, ".claude", "skills")
    print("技能:", len(os.listdir(sk)) if os.path.isdir(sk) else "**没有** ❌")
