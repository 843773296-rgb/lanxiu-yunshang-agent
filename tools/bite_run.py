#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""咬合执行器 —— 把「我测过了」变成一条**下次还能再跑一遍**的规格。

## 为什么要有这个

`tools/bite_check.py` 已经要求每个检查脚本写一份 `咬合 = [...]` 记录:
左边「改坏了什么」,右边「预期红的是哪一条」。但那是**散文** ——
散文不会在回归的时候自己变红。记录写完那一刻是真的,半年后代码改了,
它还是那句话,而**「仍然成立的记录」和「已经失效的记录」长得一模一样**。

这个脚本把同一件事写成可执行的规格(`tools/bite_specs.json`),随时能重放。

## 一条咬合必须过三关,少一关就不算

1. **对照要绿**:不动任何东西,脚本跑出来是通过的。
   ⚠️ 这一关最容易省,而省掉它就会出现这个项目栽过的那种事 ——
   **攻击自己跑不起来,于是任何异常都被读成「被拦下」**。
   本来就红的脚本,改坏之后还是红的,证明不了任何事。
2. **改坏之后要红**:退出码非 0。
3. **红的是那一条**:输出里带 ❌ 的那些行中,有一行含着规格写的「预期红」。
   只看退出码不够 —— 一个脚本可能因为**完全不相干的另一条**红了,
   而「我的攻击被抓到了」和「它为别的事红了」同样长得一模一样。

## 在副本里做,不碰主工作区

常有并行会话在同一个仓库上干活。在原地改坏再改回来,中间那一瞬别人可能正好读到、
甚至提交。所以每次都在 `$TMPDIR` 下的副本里做。
⚠️ 副本必须带上库(`backend/lanxiu.db`,gitignored),否则脚本读不到数据 ——
而「读不到数据」和「数据有问题」在报告里也长得一样。

⚠️ **而「带上库」不等于「带上一份库」。** 2026-10-17 查出来:这个 worktree 的
`backend/lanxiu.db` 是一条指向主检出的软链(两个检出共用一个库),
`copytree(symlinks=True)` 把链原样带进副本,于是 69 条 `sql` 型规格
**改的是共享的那个真库** —— 边界从头没成立,而且不报错:
`os.path.exists()` 跟着软链走,「副本里没有库就红」那条断言照样是绿的。

## 用法

    python3 tools/bite_run.py                 # 跑全部规格
    python3 tools/bite_run.py --only role_check    # 只跑名字里带这个的
    python3 tools/bite_run.py --list          # 只列不跑
    python3 tools/bite_run.py --自测          # 只验副本本身的四条保证(进门禁)
"""
import argparse, atexit, io, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPECS = os.path.join(HERE, "bite_specs.json")

# ── 这份执行器自己的咬合 ──────────────────────────────────────────────
# 2026-10-17 加的。起因:它**自己**就是那种「声明过但没人验」的东西 ——
# 副本「不碰主工作区」这条保证写在文档里一个月,而这个 worktree 的库是条软链,
# 69 条改库型规格一直在改**共享的真库**,没有任何东西会红。
咬合 = [
    ("把 `_拷实外指的软链(dst, 软链)` 那一行从 `建副本` 里删掉(库的软链照旧带进副本)",
     "副本里的库还指着外面"),   # 红的是 `建副本` 自己那道断言 —— 它比自测先一步拦下
    ("把 `媒体大目录` 清空(商品图备份 / 库备份 又被整份拷进副本)",
     "超过上限"),
    # 2026-10-17 全量重放挖出来的:supplier_check 那 5 条把破坏写在 `db` 键里,
    # 执行器只认 `sql`,于是一处破坏都没施加,却被报成「检查看不见这处破坏」。
    ("把 `验规格` 里「一处破坏都没声明」那一支删掉(规格没写破坏动作也照跑)",
     "一处破坏都没声明"),
    ("把 `验规格` 里「带着执行器不认的键」那一支删掉(把 sql 拼成别的名字就静默跳过)",
     "执行器不认的键"),
    ("把 `验规格` 里「找不到要改的那段」那一支删掉(破坏点过期了也照跑两个钟头)",
     "破坏点已经过期"),
    # 2026-11-05:自己拿锁那一套。**破坏点打在「凭什么算在锁里」上** ——
    # 放宽成「有锁就算」等于回到那个被否决的环境变量方案:谁都算在锁里,于是谁都不拿锁。
    ("把 `在锁里吗` 放宽成「有锁主就算」(不再查它在不在我的祖先链上)",
     "活着、但不在我的祖先链上"),
    # ⚠️⚠️ **给这一套再写咬合时当心反方向那一刀:** 把 `在锁里吗` 改成恒 `False`,
    #    副本里那个子进程就会去抢**同一把**锁(锁目录是绝对路径,副本不影响它),
    #    而锁正被外面这一轮握着 —— 于是它会一路等到封顶(默认 3600 秒)。
    #    要咬那一侧,得先把 `LANXIU_LOCK_CAP` 调小,否则这条咬合看起来是「卡死了」。
    #    (现在这一刀是安全的:放宽成「有锁主就算」只会让它**跳过**拿锁,不会去等。)
    # 2026-10-17 夜:主检出里 `.fakedata` 1.9 GB,那边一跑自测就撞上限,
    # 而这个 worktree 没有这个目录、一直是绿的 —— 又一次「两个检出长得不一样」。
    ("把 `.fakedata` 从 `不带` 里删掉(输出目录又被拷进副本)",
     "进了副本"),
    # 2026-10-17 夜加的「前置步骤」:有一类咬合要先把库建成某个状态才验得到,
    # 当天三次独立撞到(rating_rebuild 的指纹 / seed.py 的登记 / 同段那条 assert)。
    ("把 `前置` 的形状检查删掉(写成字符串也放过,于是 for 把它拆成单个字母)",
     "前置"),
]

# 副本里**不**带的东西。
# ⚠️ 这里原来是白名单(列出要拷哪些),2026-09-17 改成黑名单。
# 起因:白名单漏了根目录的 `.mcp.json`,于是 `boundary_audit` 在副本里对照就是红的 ——
# 而「副本漏了文件」和「代码真的坏了」在报告里长得一模一样。
# **白名单会静默漏掉新加的文件,黑名单不会。**
# ⚠️ **`.fakedata` 不能软链,只能不带。** 2026-10-17 夜:主检出里它有 1.9 GB,
# 于是那边一跑 `--自测` 就撞拷贝上限(2304 MB),而**我的 worktree 里根本没有这个目录,
# 所以我这边一直是绿的** —— 又一次「两个检出长得不一样」。
# 为什么不照大目录那样软链进来:**它是输出目录,门禁会往里写**
# (`fakedata/checkup.py`、`fakedata/stability.py` 都写 `.fakedata/*.json`;
#  `runlog_check` 的注释原话「那是输出目录(gitignore,随时清掉)」)。
# 软链进副本,副本里的写就落到**真的** `.fakedata` 上 —— 那正是软链那条前提要排除的情况。
# 不带它是安全的,而且有现成证据:我的 worktree 本来就没有它,门禁一直全绿。
不带 = {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store", "node_modules",
      ".fakedata"}

# 软链进副本、不落第二份字节的大目录(项目根下的)。
# 2026-10-17 量出来的账:整份拷贝 **10.77 GB / 6335 个文件,其中 10.74 GB 是图** ——
# 商品图备份 + backend/static 下那两个 img 目录。一条规格拷一份,709 条就是 7.4 TB;
# 按实测 572 MB/s,**光拷字节要 3.7 小时**。排掉图之后是 0.03 GB / 1164 个文件。
媒体大目录 = ("商品图备份", "库备份")

# 拷进副本的字节上限。超了直接红 —— 不是洁癖:
# 全量重放要拷 700 多次,**每多拷 100 MB 就多搭两分钟**,
# 而慢到跑不完的下场是「全量重放」被悄悄放弃(2026-10-16 夜就是这么没跑起来的)。
# 新来的大目录:要么登记进 `媒体大目录`(前提是门禁只读它),
# 要么把这个数抬上去**并写明为什么**。
拷贝上限 = 400 * 2**20


def 该软链的():
    """软链(而不是拷贝)进副本的目录。

    ⚠️ **为什么是软链,不是干脆「不拷」。** 不拷会**静默改变被测行为**:
    `vision_eval_judgetest` 那条规格改的 `backend/img.py` 会去 `static/img/` 找真图,
    图不在就走另一条分支 —— 于是「改坏了却没红」,而那个「没红」是副本漏了图造成的。
    **它和「检查看不见这处破坏」在报告里长得一模一样。**
    软链让这些路径照旧读得到,只是不落第二份字节。
    前提是门禁里没有任何一步往它们**写**(核过:写图的 `import_images.py` 不在门禁里,
    `img.py` 的缓存落在 `backend/.imgcache`,不在 static 下)。
    """
    out = ["agentsite/.venv", ".venv",
           # 管理后台的 venv(11-04 加):管理后台测试的咬合要用它跑 alembic / sqlalchemy。**只读** ——
           # 被咬的测试只执行里面的解释器和 alembic,不往里装东西;门禁里也没有任何一步往它写
           os.path.join("管理后台", ".venv"),
           # 本地 BGE 模型(主检出 91 MB,不进 git)。**只读**:读它的只有
           # `管理后台/.../embedder_bge.py`,而写它的 `tools/fetch_model.sh`
           # 在门禁里**只被 Makefile echo 提了一句**,没有任何一步真执行它
           # (2026-10-29 核过)。所以软链安全,而且路径照旧存在 ——
           # 「模型没就位」那条判法在副本里和真检出一样。
           # ⚠️ **只软链它这一层,`管理后台/` 整份照旧拷**:有 2 条咬合规格的
           # 破坏点就在它下面(`runtime/桥工具.py`、`workflows_api.py`),
           # 软链进去的话那两条**改的是真检出里的文件**。
           os.path.join("管理后台", ".models")]
    out += list(媒体大目录)
    # backend/static 下**每一个**子目录都是图(img / img.待删-YYYYMMDD / 以后还会有)。
    # 逐个点名会把日期写进代码,下次清图就漂 —— 所以按位置认,不按名字认。
    静 = os.path.join(ROOT, "backend", "static")
    if os.path.isdir(静):
        out += [os.path.join("backend", "static", n) for n in sorted(os.listdir(静))
                if os.path.isdir(os.path.join(静, n))]
    return [p for p in out if os.path.isdir(os.path.join(ROOT, p))]


def _忽略(软链):
    基 = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".venv",
                                "*.db-journal", "*.db-wal", "*.db-shm", "录音",
                                # 换库前留的旧库备份(`lanxiu.db.重建前`,100 MB,不进版本库)——
                                # 检查一个字节都不读它,而它一拷进副本就撞拷贝上限(10-20:401 MB > 400 MB,全量重放拒跑)
                                "*.重建前",
                                # 轮转出来的旧执行记录(`.feynman/spans.jsonl.1`,主检出 64 MB)——
                                # `spans` 超过阈值就 `os.replace(p, p + ".1")`,而**全仓库没有
                                # 任何代码读 `.jsonl.1`**(2026-10-29 核过:它只出现在 .gitignore 一处)。
                                # 只有写、没有读 → 不带它不会造出「读不到数据」。
                                # ⚠️ 这一条和下面那个模型目录的处理**刻意不同**:
                                # 没人读的整份不带,只读的走软链 —— 分开它们的是
                                # 「有没有代码会去读它」,不是大小。
                                "spans.jsonl.1")
    def f(目录, 名字们):
        # 库的临时日志(-journal / -wal / -shm)不带:它们随写随删,复制到一半消失会让 copytree 报
        # Errno 2(10-03 队友撞到过)—— 而且带过去也没用,副本里的库是独立打开的。
        # 录音目录也不带:客户的声音,几十 MB 一通,检查用不到。
        丢 = set(基(目录, 名字们))
        rel = os.path.relpath(目录, ROOT)
        for n in 名字们:
            if os.path.normpath(os.path.join(rel, n)) in 软链:
                丢.add(n)
        # 并行子任务的 git 工作区(`.claude/worktrees/`,10-23 起)不带:每个都是整份仓库,
        # 四个就把副本撑到 820 MB、撞拷贝上限、全量重放拒跑;检查一个字节都不读它们
        if rel == ".claude" and "worktrees" in 名字们:
            丢.add("worktrees")
        return 丢
    return f


def _拷实外指的软链(dst, 软链):
    """副本里不许有指向副本外面的软链 —— 上面声明过的那几个除外。

    ⚠️ 这条守的是 2026-10-17 查出来的一个洞。这个 worktree 的 `backend/lanxiu.db`
    是一条**指向主检出的软链**(两个检出共用一个库),而 `copytree(symlinks=True)`
    把这条链原样带进了副本 —— 于是 69 条 `sql` 型规格的 UPDATE / DELETE
    **改的是共享的那个真库**。「在副本里做破坏,不碰主工作区」这条边界从头就没成立。
    而它不报错也不留痕:`os.path.exists()` 跟着软链走,
    所以原来那句「副本里没有库就红」照样是绿的 ——
    **「副本里有一份库」和「副本里有一条指着真库的链」,在那条断言上长得一模一样。**
    """
    for root, 目录们, 文件们 in os.walk(dst):      # 不跟软链走,所以声明过的大目录不会被遍历进去
        for n in list(目录们) + 文件们:
            p = os.path.join(root, n)
            if not os.path.islink(p): continue
            真 = os.path.realpath(p)
            if 真 == os.path.realpath(dst) or 真.startswith(os.path.realpath(dst) + os.sep):
                continue                            # 指到副本内部,随它
            if os.path.isdir(真):
                if os.path.relpath(p, dst) in 软链: continue
                raise SystemExit(f"❌ 副本里有一条没登记的目录软链指着外面:"
                                 f"{os.path.relpath(p, dst)} → {真} —— 在副本里改它会改到主工作区")
            os.remove(p)
            if os.path.exists(真): shutil.copy2(真, p)


def 建副本(dst, 上限=None):
    软链 = set(该软链的())
    if os.path.isdir(dst): shutil.rmtree(dst)
    os.makedirs(dst)
    for name in sorted(os.listdir(ROOT)):
        if name in 不带: continue
        if name in 软链: continue
        src = os.path.join(ROOT, name)
        d = os.path.join(dst, name)
        if os.path.isdir(src):
            shutil.copytree(src, d, ignore=_忽略(软链), symlinks=True)
        else:
            shutil.copy2(src, d)
    for rel in sorted(软链):
        link = os.path.join(dst, rel)
        if os.path.isdir(link) and not os.path.islink(link): shutil.rmtree(link)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if not os.path.exists(link): os.symlink(os.path.join(ROOT, rel), link)
    _拷实外指的软链(dst, 软链)

    # ── 借主检出的 `管理后台/.venv`,**软链回副本里它原来的位置** ──────────────
    #
    # ⚠️ 2026-11-06 的第二跳。第一跳是「外层用哪个解释器跑这个脚本」(见 `管理后台解释器`),
    # 修完 19 条里 15 条过了;而 `管理后台/tests/e2e/test_orchestration_flow.py` 照旧红,
    # 因为**它自己也要起 `根/管理后台/.venv/bin/python`** 去跑 worker ——
    # 只把绝对路径递给执行器,够不到被测脚本内部那一句。
    # > 「这台机器上有那份 venv」和「副本里那个路径存在」是两件事,
    # > 而只修了前者的时候,报出来还是「对照就是红的」。
    # 只读:副本里的测试只执行它里面的解释器,不往里装东西(和 `该软链的()` 对这份 venv 的判断同源)。
    借py = 管理后台解释器()
    if 借py and not 借py.startswith(os.path.realpath(ROOT) + os.sep) \
             and not 借py.startswith(ROOT + os.sep):
        目的 = os.path.join(dst, "管理后台", ".venv")
        if not os.path.exists(目的) and os.path.isdir(os.path.join(dst, "管理后台")):
            os.symlink(os.path.dirname(os.path.dirname(借py)), 目的)

    库 = os.path.join(dst, "backend", "lanxiu.db")
    if not os.path.exists(库):
        raise SystemExit("❌ 副本里没有 backend/lanxiu.db —— 拷贝漏了库,跑出来的全是环境问题")
    if os.path.islink(库) or not os.path.realpath(库).startswith(os.path.realpath(dst) + os.sep):
        raise SystemExit(f"❌ 副本里的库还指着外面({os.path.realpath(库)})"
                         f" —— 改库型的规格会改到**共享的真库**上")

    拷了 = sum(os.path.getsize(os.path.join(r, f))
              for r, _, fs in os.walk(dst) for f in fs
              if not os.path.islink(os.path.join(r, f)))
    顶 = 拷贝上限 if 上限 is None else 上限
    # ⚠️⚠️ **过了也要把这个数印出来。** 原来只在超限那一支报数,于是
    # 「降到 250 MB」和「只是没超过 400 MB」**在那条绿上长得一模一样** ——
    # 下一个人想知道到底降到多少,只能自己再 du 一遍。
    # 2026-10-29 并行会话就是这么卡住的:排掉两个大件之后它只能报
    # 「验到了不超限,具体数没量到」。照项目一贯的规矩:**先报样本量,再报结论**。
    # 不满 1 MB 就按字节印 —— 自测里有个「上限 1 字节」的人造用例,
    # 按 MB 四舍五入会印成「上限 0 MB」,**那看起来像个 bug 而不是像个用例**。
    _量 = lambda n: f"{n / 2**20:.0f} MB" if n >= 2**20 else f"{n} 字节"
    print(f"  📦 这一份副本实拷 {_量(拷了)}(上限 {_量(顶)})")
    if 拷了 > 顶:
        # ⚠️ **报数不报号,下一个人得自己 du 一遍。** 2026-10-17 夜实测:
        # 这条在主检出上报「2304 MB 超过 400 MB」,而**占掉它的是谁一个字都没说** ——
        # 并行会话只能自己去翻才找到是 `.fakedata`。所以把前几名打出来。
        按顶层 = {}
        for r, _, fs in os.walk(dst):
            一级 = os.path.relpath(r, dst).split(os.sep)[0]
            for f in fs:
                fp = os.path.join(r, f)
                if not os.path.islink(fp):
                    按顶层[一级] = 按顶层.get(一级, 0) + os.path.getsize(fp)
        大户 = "、".join(f"{k} {v/2**20:.0f} MB"
                       for k, v in sorted(按顶层.items(), key=lambda kv: -kv[1])[:3])
        raise SystemExit(f"❌ 一份副本要拷 {拷了/2**20:.0f} MB,超过上限 {顶/2**20:.0f} MB ——"
                         f" 全量 {len(json.load(open(SPECS, encoding='utf-8'))) if os.path.exists(SPECS) else 0} 条"
                         f" 规格要拷这么多份。**最占地方的:{大户}**。"
                         f" 只读的大目录登记进 `媒体大目录`(软链进副本);"
                         f" 会被写的输出目录加进 `不带`(软链会让副本里的写落到真目录上);"
                         f" 两样都不是就抬高 `拷贝上限` 并写明为什么")
    return dst


def 管理后台解释器(根=None):
    """跑 `管理后台/` 那些端到端测试要用的解释器。**找不到就返回 None,不退回系统 python。**

    ⚠️ **2026-11-06 第一次整轮咬合重放,1258 条里 23 条没过,而其中 19 条跟判据一点关系都没有。**
    那 19 条全是 `管理后台/tests/` 下的,报的是「对照就是红的」;把对照的原始输出打出来,
    红的是一行 `ModuleNotFoundError: No module named 'sqlalchemy'` ——
    `管理后台/.venv` 只装在**主检出**,子 worktree 里没有,而这里原来
    `os.path.exists` 为假就退回 `sys.executable`。

    > 「用对的解释器验过一遍」和「这台检出没有那个 venv、于是崩在 import 上」,
    > **在「对照就是红的」那一行上长得一模一样** —— 而后者会把人指向判据。

    这是这个项目那条「别让兜底把『我不知道』变成一句听起来很肯定的话」的又一次:
    11-04 加那一支时注释已经写明「拿系统 python 跑,红的是 ImportError,
    和『改坏了之后它红没红』混在一起分不开」,**漏的是兜底那一半**。

    三步,顺序固定:
      ① 本检出自己的 `管理后台/.venv`
      ② 借**共享真库所在那个检出**的那一份(`锁目录()` 已经是这么认「主检出」的,不另立一套)。
         只读 —— 只执行里面的解释器,不往它装东西(和 `该软链的()` 里对这份 venv 的判断同源)
      ③ 两个都没有 → **None**,由调用方单独报一类「这台检出验不了」:
         不混进「对照就是红的」,也不报成通过
    """
    根 = 根 or ROOT
    近 = os.path.join(根, "管理后台", ".venv", "bin", "python")
    if os.path.exists(近):
        return 近
    # 真库是条绝对路径软链,指向主检出 —— 顺着它找那个检出(`锁目录()` 同一套认法)
    主 = os.path.dirname(os.path.dirname(os.path.realpath(
        os.path.join(根, "backend", "lanxiu.db"))))
    借 = os.path.join(主, "管理后台", ".venv", "bin", "python")
    # `借 != 近` 挡住「库不是软链(就在主检出里跑)」那种情况下的空转
    return 借 if 借 != 近 and os.path.exists(借) else None


def 门禁怎么跑(script):
    """从 check.sh 里取这个脚本的原样命令。

    ⚠️ **不要自己拼 `python3 <脚本>`。** 门禁里有些步骤用的是 `agentsite/.venv/bin/python`，
    有些带 `--selftest` 参数。用另一种姿势去跑，验的就不是门禁验的那个东西 ——
    这个项目已经栽过一次同族的事：副本测试没软链 venv，7 项「失败」全是环境问题，
    和真的数据问题混在同一张报告里。
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    候选 = []
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        if script not in line: continue
        # run "标题" cmd args...   —— 标题带引号，去掉它之后剩下的就是命令
        rest = line[4:].strip()
        if rest.startswith('"'):
            rest = rest[rest.index('"', 1) + 1:]
        parts = rest.split()
        if parts: 候选.append(parts)
    # ⚠️ 同一个脚本在门禁里挂两行(一行 `--自测`、一行真跑)时,**取真跑那行**(11-14 加)。
    #    原来取「第一行」,而 sealed_tier_check 的 `--自测` 行恰好在前 —— 自测只验它自己造的夹具,
    #    规格改的是真题集 / 真结果文件,于是 3 条规格全报「改坏了却没红」,
    #    长相和「判据死了」一模一样,实际是**跑错了那一行**。
    #    自测行只在**只有它**的时候才用(那时它就是门禁验的东西)。
    if 候选:
        真跑 = [c for c in 候选 if not ({"--自测", "--selftest"} & set(c))]
        return (真跑 or 候选)[0]
    # 不在 check.sh 里的管理后台脚本(端到端测试之类):用管理后台自己的 venv 跑 —— 它的依赖(sqlalchemy / alembic)
    # 只装在那里;拿系统 python 跑,红的是 ImportError,和「改坏了之后它红没红」混在一起分不开(11-04 加)
    #
    # ⚠️ **找不到解释器就返回 None,绝不退回系统 python** —— 退回的正是上面这句话要避免的姿势。
    #    (2026-11-06 第一次整轮重放逮到:19 条全报「对照就是红的」。详见 `管理后台解释器`。)
    # JS 测试用 node 跑(11-12:列表迭代面板那 3 条是规格库里头一批 .js 规格,原来一律交给 python,
    # 对照恒红「这条咬合证明不了任何事」—— 和 11-06 那次同一个形状:姿势错了,红的不是判据)
    if script.endswith(".js"):
        nd = shutil.which("node")
        return [nd, script] if nd else None
    if script.startswith("管理后台/"):
        py = 管理后台解释器()
        return [py, script] if py else None
    return [sys.executable, script]


def 跑不了的理由(script):
    """这条规格在**这台检出**上压根跑不了的理由;跑得了就返回 None。

    ⚠️ 这是项目里那条「『没东西可验』必须和『验过了』分开」的第三面:
    「没被验」既不等于「验过了」,也不等于「判据死了」—— **三件事,三种下一步动作**
    (去装依赖 / 什么都不用做 / 去修判据)。把它们报成同一句话,人就会修错东西。
    2026-11-06 整轮重放里 19 条就是这么被报成「对照就是红的」的。
    """
    if script.startswith("管理后台/") and 门禁怎么跑(script) is None:
        return ("这台检出没有 `管理后台/.venv`,主检出也借不到 —— 它的依赖(sqlalchemy / alembic)"
                "只装在那里。**这条咬合没被验:不是通过,也不是判据坏了**")
    return None


def 跑(sand, script):
    cmd = 门禁怎么跑(script)
    if cmd is None:
        # 走到这里说明调用方漏了「这台检出验不了」那一支 —— **崩在这里比拿系统 python 糊过去好**
        raise SystemExit(f"❌ {script} 没有可用的解释器(缺 管理后台/.venv)—— "
                         f"调用方必须先用 跑不了的理由() 挑出来,别退回系统 python")
    p = subprocess.run(cmd, cwd=sand, capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def 改文件(sand, path, old, new):
    f = os.path.join(sand, path)
    s = open(f, encoding="utf-8").read()
    if old not in s:
        return f"要改的那段在 {path} 里找不到 —— **注入没进检查的视野,这条规格本身是坏的**"
    open(f, "w", encoding="utf-8").write(s.replace(old, new, 1))
    return None


def 改库(sand, sqls):
    import sqlite3
    c = sqlite3.connect(os.path.join(sand, "backend", "lanxiu.db"))
    动 = 0
    try:
        for q in sqls:
            动 += c.execute(q).rowcount
        c.commit()
    finally:
        c.close()
    # ⚠️ 影响 0 行的 UPDATE/DELETE 不报错,而「改坏了」和「什么都没改」
    #    在后面的结果里长得一模一样 —— 必须在这里拦住。
    if 动 <= 0:
        return "SQL 影响 0 行 —— **什么都没改坏**,后面就算红了也跟这条规格无关"
    return None


def 锁目录():
    """两个 PID 文件放哪 —— **真库所在的那个目录**,不放各自的 `.feynman`。

    数据工厂在另一个 worktree,**只有 `lanxiu.db` 是软链**,`.feynman` 两边各有一份。
    放 `.feynman` 的话两边永远读不到对方的锁,这道闸会**恰好恒不拦** ——
    而那种失效**和「装好了」长得一模一样**:它什么都不会说。
    """
    return os.path.dirname(os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db")))


def 锁还活着(锁文件):
    """锁文件里那个进程还活着吗。**残留的不算。**

    崩了留下的锁不该把后面所有轮次挡死 —— `backend/.rebuilding` 早就是这么处理的
    (读 PID 再 `os.kill(pid, 0)`),这里照抄同一个范式。

    ⚠️ **不用 `pgrep -f`。** 上一版判夜跑写的是 `pgrep -f nightly_eval`,
    它匹配**整条命令行**,于是我自己那句 `ps … | grep -E "…|nightly_eval"`
    (用来看占用的)**把那道闸触发了**:白天九点多也报「夜跑正在跑」、拒绝开跑。
    这个形状本项目连踩四次 —— 规则写进 CLAUDE.md → 文档匹配自己;挪进 `.secretscan`
    → 规则文件匹配自己;写在脚本注释里举例 → 脚本匹配自己;**进程名写进命令行
    → 命令匹配自己**。PID 文件一个字符串都不用匹配。
    """
    try:
        pid = int(open(锁文件).read().strip() or 0)
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False                 # 残留:进程早没了
    except PermissionError:
        return True                  # 别人家的进程:存在,只是不归我管
    return True


def 占上锁(锁文件):
    """**在干活之前**写自己的 PID —— 写在后面的话,挂在中途就根本没写过。"""
    try:
        with open(锁文件, "w") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        # 写不了也照跑(锁是协作用的,不是正确性必需),**但必须出声** ——
        # 静默的话,对面以为「没人在跑」而开起来,两边一起拷库。
        print(f"⚠️ 写不了 {锁文件}({e})—— 夜跑看不见我,这一轮没有互斥保护")
        return
    atexit.register(lambda: _放锁(锁文件))


def _放锁(锁文件):
    try:
        if 锁还活着(锁文件) and int(open(锁文件).read().strip() or 0) == os.getpid():
            os.unlink(锁文件)
    except (OSError, ValueError):
        pass


def 验规格(specs, 根=None):
    """跑之前先验一遍**规格自己** —— 一条没声明破坏动作的规格,跑起来和「检查瞎了」长得一模一样。

    给了 `根` 还会验**破坏点在不在**:`改文件` 的 old 在目标文件里找不到,
    这条规格就过期了 —— 而过期的规格跑起来**和「检查瞎了」长得一模一样**。
    这一关是静态的(只读文件、不建副本、不跑检查),716 条几秒钟验完;
    全量重放要近两个钟头,**这类过期不该等它来发现**。
    2026-10-17 实测:`triage_sets_check` 那条咬合钉死了一个包裹号,
    而测试集重新冻结时 40 个号整批换 —— 那个号成了谁都不认识的字符串,
    判据扫不到它,这条咬合静默变绿。(它的 old 本身还在,所以这一关抓不到它;
    抓得到的是另一类:**要改的那一行本身被改掉或删掉了**。)

    2026-10-17 第一次全量重放(714 条)实测:`supplier_check` 那 5 条把破坏写在
    `db` 键里,而执行器只认 `sql` —— 于是那 5 条**一处破坏都没施加**,
    后面照旧跑检查、看见绿的,被报成「改坏了却没红 —— 检查看不见这处破坏」。
    **5 个判据被冤枉了一整轮,而真相是规格的键名拼错了。**

    执行器本来已经为两种「什么都没改坏」各立了一条断言(`改文件` 的「要改的那段找不到」、
    `改库` 的「SQL 影响 0 行」),偏偏漏了最外面那层:**一处破坏都没声明。**

    两个要点:
    · 不止检「有没有 sql/file」,还检「**有没有执行器不认的键**」——
      否则下次拼成 `sqls` / `files` 又是静默跳过,拦的要是这一类,不是某个拼写。
    · 这一关在**开跑之前对所有规格做完**:全量重放要跑近两个钟头,
      等跑到第 320 条才发现规格是坏的,前面那一个钟头已经花掉了。
    """
    认得的键 = {"script", "改坏", "预期红", "sql", "file", "前置"}
    坏, 提示 = [], []
    for i, s in enumerate(specs, 1):
        缺 = [k for k in ("script", "改坏", "预期红") if not s.get(k)]
        if 缺:
            坏.append((i, s.get("script", "?"), f"缺字段 {'/'.join(缺)}")); continue
        野 = sorted(set(s) - 认得的键)
        if not s.get("sql") and not s.get("file"):
            坏.append((i, s["script"], "一处破坏都没声明" +
                       (f",而它带着执行器不认的键 {'/'.join(野)} —— 破坏大概写在那里了" if 野 else "")))
        elif 野:
            坏.append((i, s["script"], f"带着执行器不认的键 {'/'.join(野)}"))
        前 = s.get("前置")
        if 前 is not None and (not isinstance(前, list) or not all(
                isinstance(x, str) and x.strip() for x in 前)):
            坏.append((i, s["script"], "`前置` 要是一串非空命令(列表),现在是 "
                       f"{type(前).__name__}"))
        if not 根:
            continue
        for f in s.get("file", []):
            fp = os.path.join(根, f["path"])
            if not os.path.isfile(fp):
                坏.append((i, s["script"], f"要改的文件不在:{f['path']}")); continue
            try:
                src = io.open(fp, encoding="utf-8", errors="ignore").read()
            except OSError as e:
                坏.append((i, s["script"], f"{f['path']} 读不了:{e}")); continue
            n = src.count(f["old"])
            if n == 0:
                坏.append((i, s["script"],
                           f"{f['path']} 里找不到要改的那段 —— **破坏点过期了**,"
                           f"它跑起来会报「改坏了却没红」,而那不是判据的错"))
            elif n > 1:
                # ⚠️ 只提示不判红。`改文件` 用 `replace(old, new, 1)` 只换**第一处**,
                # 出现多次时破坏可能落在不是你要的那一处(2026-10-17 `make_handoff`
                # 那条正是这么静默失效的:必填段标题重复,换掉第一个、第二个顶上)。
                # 但全量重放实测这 8 条里 7 条照旧有效 —— **判红要确定有害**,
                # 这里只把风险说出来,最终裁判是重放。
                提示.append((i, s["script"],
                             f"{f['path']} 里「要改的那段」出现 {n} 次,只会换第一处 ——"
                             f"确认改的是你要的那一处"))
    for i, sc, why in 提示:
        print(f"     ℹ️ [{i}] {sc}  {why}")
    return 坏


# ── 自己把共享资源锁拿上(2026-11-05 加)────────────────────────────────
#
# **逼出这一段的事**:2026-11-05 07:0x,另一个会话拿着锁在跑全量门禁,
# 我在同一台机器上跑了两轮 `bite_run`(每轮 `copytree` 一份 168 MB 的副本,
# 再把那条检查在副本里跑 N+1 遍)。他那一轮的**挂钟多出了约 2000 秒**,
# 而「各项之和」没有一项变慢 —— 门禁末尾那张计时表把它判成「机器停了 / I/O 卡顿」。
#
# > 判对了。只是那个「机器」是我。
# > 而**「电脑睡过去了」和「有人在旁边拷 336 MB 并跑了 20 遍检查」,
# > 在那个数上长得一模一样。**
#
# 项目规矩本来就写着「写库**和跑门禁**都算占用」,而咬合重放就是在跑检查。
# 我知道这条规矩,也照它提醒过别人 —— 还是漏了。所以不靠记性:
#
#     一个每次都要记得加的安全参数,等于没有这道防护。
#
# 这条今天上午刚用来否决「让 196 个写口各自加一句断言」,而这次**我自己就是那个忘了加的人**。
def 锁主pid(锁目录=None):
    """锁文件里那个 pid;没锁 / 读不出来回 None。"""
    d = 锁目录 or os.environ.get("LANXIU_LOCK_DIR") or "/tmp/lanxiu-gate.lock"
    try:
        头 = io.open(os.path.join(d, "owner"), encoding="utf-8").read().split()
        return int(头[0]) if 头 else None
    except (OSError, ValueError):
        return None


def 祖先链(pid=None):
    """我这个进程往上的 pid 链(含自己)。**问系统,不问环境变量。**"""
    链, p = [], pid or os.getpid()
    for _ in range(64):                       # 封顶防环
        链.append(p)
        if p <= 1:
            break
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(p)],
                             capture_output=True, text=True).stdout.strip()
        if not out.isdigit():
            break
        p = int(out)
        if p in 链:
            break
    return 链


def 在锁里吗(主人, 链):
    """锁的主人是我、或者是我的祖先 → 我已经在那把锁里了。**纯函数,好验。**

    ⚠️⚠️ **凭据是「锁文件里那个 pid 在我的祖先链上」,不是「有人说我在锁里」。**
       另一个会话建议用一个环境变量(`已经在锁里=1`)当凭据,我不用那个:
       一个「真在锁里」和一个「变量漏在某个 shell 里了」(上一轮 export 过、
       或者谁手动设过)**在那个变量上长得一模一样**,而第二种会把这道防护
       **静默关掉** —— 后果就是上面那 2000 秒,而那个数在计时表上
       和「电脑睡了」一模一样。查真状态分得开,查声明分不开。
    """
    return 主人 is not None and 主人 in 链


def 先把锁拿上(argv):
    """没在锁里就把自己重新挂到 `gate_lock.sh` 底下跑(`execv`,不是再开一个进程)。

    ⚠️ **不需要「别再套一层」的标记。** 重新挂上之后,`gate_lock` 的 pid 就在我的
       祖先链上,`在锁里吗()` 自然回 True —— **防递归靠的是同一条判据,不是另一个开关。**
       (多一个开关就多一个会漏下来的东西,那正是上面不用环境变量的理由。)
    """
    if 在锁里吗(锁主pid(), 祖先链()):
        return
    锁 = os.path.join(ROOT, "tools", "gate_lock.sh")
    if not os.access(锁, os.X_OK):
        print(f"⚠️ 找不到可执行的 {锁} —— **这一轮不拿锁就往下跑了**。"
              f"要是这台机器上有别人在跑门禁,他的挂钟会莫名多出一大截"
              f"(2026-11-05 实测约 2000 秒),而那个数看起来像「机器卡了一下」")
        return
    谁 = ("咬合重放 " + " ".join(argv[1:]))[:48] or "咬合重放"
    os.execv(锁, [锁, "--who", 谁, sys.executable, os.path.abspath(__file__), *argv[1:]])


def 自测():
    """验 `建副本` 的五条保证 —— **真跑一次 `建副本`**,不另写一份照着样子重实现的夹具。

    这四条每一条都对应一次「两种状态长得一模一样」:
    ① 库是真文件(不是指着共享真库的软链)—— 否则改库型规格破坏的是生产数据
    ② 声明过的大目录在副本里是软链、而且底下的文件照旧读得到 —— 否则「漏了图」会被读成「检查看不见破坏」
    ③ 规格要改的每个文件在副本里都是**真文件** —— 落在软链底下的话,`改文件` 改的是主工作区
    ④ 字节上限**真的会拦** —— 打印一句话和拦下来是两件事(这个项目栽过)
    """
    import tempfile as _tf
    坏 = 0
    base = _tf.mkdtemp(prefix="bite-自测-")
    try:
        dst = 建副本(os.path.join(base, "s"))

        # ── ① 库必须是副本自己的一份 ──────────────────────────────────
        #
        # ⚠️ **这一条要自备夹具,不能靠「这个检出碰巧是什么样」。**
        # 第一版直接看真工作区拷出来的那份库,当场栽了:咬合时把 `_拷实外指的软链`
        # 那一行删掉,**自测照旧是绿的** —— 因为副本里的库已经是真文件了,
        # 软链那个形状在副本里根本不存在,破坏**进不了判据的视野**。
        # 而主检出里的库本来就是真文件,所以在那边这一条**永远验不到**。
        #
        # 所以这里自己造出那个形状:一个小根目录,库是一条指向外面的软链。
        假 = os.path.join(base, "假根")
        os.makedirs(os.path.join(假, "backend"))
        外 = os.path.join(base, "外面的真库.db")
        open(外, "wb").write(b"SQLite format 3\x00" + b"x" * 64)
        os.symlink(外, os.path.join(假, "backend", "lanxiu.db"))
        open(os.path.join(假, "随便.py"), "w").write("# 占位\n")
        # 输出目录也造一个:**它不该进副本**(门禁会往 `.fakedata` 写,
        # 软链或拷贝进来都不对 —— 拷进来撞上限、软链进来写到真目录上)。
        # ⚠️ 这一条**必须自备夹具**:主检出里 `.fakedata` 有 1.9 GB,
        # 而这个 worktree 里根本没有这个目录 —— 靠「这个检出碰巧有没有它」来验,
        # 等于在我这边永远验不到(2026-10-17 夜就是这么漏过去的)。
        os.makedirs(os.path.join(假, ".fakedata"))
        open(os.path.join(假, ".fakedata", "产物.json"), "w").write("{}")
        global ROOT
        真根 = ROOT
        try:
            ROOT = 假
            假副本 = 建副本(os.path.join(base, "假副本"))
        finally:
            ROOT = 真根
        if os.path.exists(os.path.join(假副本, ".fakedata")):
            print("  ❌ 输出目录 `.fakedata` 进了副本 —— 它是门禁会往里写的地方:"
                  "拷进来撞拷贝上限,软链进来副本里的写会落到真目录上"); 坏 += 1
        else:
            print("  ✅ 输出目录 `.fakedata` 没进副本(自备夹具验的,不靠这个检出有没有它)")

        假库 = os.path.join(假副本, "backend", "lanxiu.db")
        if os.path.islink(假库) or not os.path.realpath(假库).startswith(os.path.realpath(假副本) + os.sep):
            print(f"  ❌ 副本里的库指着副本外面:{os.path.realpath(假库)} ——"
                  f" 改库型规格的 UPDATE / DELETE 会落在那个库上"); 坏 += 1
        elif open(假库, "rb").read() != open(外, "rb").read():
            print("  ❌ 库拷实了但内容不对 —— 副本里的库和原库不是同一份数据"); 坏 += 1
        else:
            print("  ✅ 指向外面的库软链被拷实成副本自己的一份(自备夹具验的,不靠这个检出碰巧长什么样)")

        库 = os.path.join(dst, "backend", "lanxiu.db")
        if os.path.islink(库) or not os.path.realpath(库).startswith(os.path.realpath(dst) + os.sep):
            print(f"  ❌ 副本里的库指着副本外面:{os.path.realpath(库)}"); 坏 += 1
        else:
            print(f"  ✅ 这个检出拷出来的库也是副本自己的一份({os.path.getsize(库)/2**20:.1f} MB)")

        软链 = 该软链的()
        少 = [p for p in 软链 if not os.path.islink(os.path.join(dst, p))]
        if 少:
            print(f"  ❌ 这些大目录没软链成,是整份拷进来的:{少}"); 坏 += 1
        else:
            print(f"  ✅ {len(软链)} 个大目录是软链({', '.join(软链)})")
        瞎 = [p for p in 软链 if not os.path.isdir(os.path.join(dst, p))]
        if 瞎:
            print(f"  ❌ 软链建了但读不到(断链):{瞎} —— 路径在、内容不在,比没有更糟"); 坏 += 1
        else:
            print("  ✅ 软链底下的内容读得到(路径照旧,只是不落第二份字节)")

        规格 = json.load(open(SPECS, encoding="utf-8")) if os.path.exists(SPECS) else []
        假 = []
        for sp in 规格:
            for f in sp.get("file", []):
                p = os.path.join(dst, f["path"])
                if os.path.islink(p) or not os.path.isfile(p):
                    假.append(f["path"])
        if 假:
            print(f"  ❌ {len(set(假))} 个规格要改的文件在副本里不是真文件:{sorted(set(假))[:5]}"); 坏 += 1
        else:
            n = len({f["path"] for sp in 规格 for f in sp.get("file", [])})
            print(f"  ✅ 规格要改的 {n} 个文件在副本里都是真文件(改它们碰不到主工作区)")

        # ── ⑤ 互斥锁:三种情形各自要说对话(2026-10-20 加)────────────────
        #
        # ⚠️ **最要紧的是「残留的锁不许挡」那一条。** 把 `锁还活着` 改成
        #    `os.path.exists` 一样能过前两条 —— 而那样一个崩掉的夜跑留下的锁
        #    会**把此后所有重放永久挡死**,日志里只写「夜跑正在跑」,
        #    看起来完全像是闸在正常工作。
        _锁base = os.path.join(base, "锁")
        os.makedirs(_锁base, exist_ok=True)
        _活 = os.path.join(_锁base, "活.pid")
        _死 = os.path.join(_锁base, "死.pid")
        _空 = os.path.join(_锁base, "没有.pid")
        open(_活, "w").write(str(os.getpid()))        # 我自己,必然活着
        open(_死, "w").write("999999999")             # 不可能存在的进程号
        for 名, 路, 该 in (("活着的锁要判在跑", _活, True),
                           ("**残留的锁(进程早没了)要判不在跑**", _死, False),
                           ("没有锁文件要判不在跑", _空, False)):
            实 = 锁还活着(路)
            if 实 is not 该:
                print(f"  ❌ {名} —— 实际判成 {实}"); 坏 += 1
            else:
                print(f"  ✅ {名}")
        # ⚠️ 锁要放在**真库那边**:两个检出各有一份 `.feynman`,放那儿等于恒不拦
        if os.path.realpath(锁目录()) != os.path.realpath(
                os.path.dirname(os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db")))):
            print("  ❌ 锁目录不是「真库所在的那个目录」—— 两个检出会各锁各的"); 坏 += 1
        else:
            print(f"  ✅ 锁放在真库那边({锁目录()})—— 两个检出锁的是同一个地方")

        try:
            建副本(os.path.join(base, "顶"), 上限=1)
            print("  ❌ 字节上限设成 1 字节都没拦下来 —— 这条上限是摆设"); 坏 += 1
        except SystemExit as e:
            if "超过上限" in str(e): print("  ✅ 字节上限真的会拦(把上限设成 1 字节,它红了)")
            else: print(f"  ❌ 上限那条红了,但红的不是它:{e}"); 坏 += 1

        # ── ⑤⑥ 规格自己要先过关 ──────────────────────────────────────────
        #
        # **真调 `验规格`**,不另写一份照着样子的夹具(判据要真调被测代码)。
        #
        # ⚠️ **两个夹具,各自只能被一条规则抓到。** 第一版只用一个
        # (带 `db` 键、又没有 sql/file),而它**同时**命中两条规则 ——
        # 于是把其中任一支删掉,它照旧被另一支抓住,**咬合当场假绿**。
        # 要验的两条规则必须各有一个「只有它抓得住」的观测点。
        甲 = [{"script": "x.py", "改坏": "一条没声明破坏动作的规格", "预期红": "随便"}]
        if not 验规格(甲):
            print("  ❌ 一条**一处破坏都没声明**的规格没被挑出来 —— "
                  "它跑起来会被报成「检查看不见这处破坏」,冤枉一个好判据"); 坏 += 1
        else:
            print(f"  ✅ 没声明破坏动作的规格,开跑前就被挑出来({验规格(甲)[0][2]})")

        乙 = [{"script": "x.py", "改坏": "破坏写在执行器不认的键里", "预期红": "随便",
               "file": [{"path": "x.py", "old": "a", "new": "b"}], "拼错的键名": "UPDATE t SET a=1"}]
        if not 验规格(乙):
            print("  ❌ 带着**执行器不认的键**的规格没被挑出来 —— "
                  "下次把 sql 拼成 sqls,那处破坏又会被静默跳过"); 坏 += 1
        else:
            print(f"  ✅ 带着执行器不认的键的规格也被挑出来({验规格(乙)[0][2]})")

        丁 = [{"script": "x.py", "改坏": "前置写成了字符串而不是一串命令", "预期红": "随便",
               "file": [{"path": "x.py", "old": "a", "new": "b"}],
               "前置": "python3 一条字符串不是列表.py"}]
        if not 验规格(丁):
            print("  ❌ `前置` 写成字符串没被挑出来 —— 字符串会被 for 拆成单个字符,"
                  "于是「前置」变成一串跑不起来的单字母命令"); 坏 += 1
        else:
            print(f"  ✅ `前置` 的形状不对也会被挑出来({验规格(丁)[0][2][:30]}…)")

        # 破坏点过期的(要改的那段在文件里已经找不到)。
        # ⚠️ **那串「找不到的文本」必须在运行时拼出来。** 写成字面量的话,
        # 它就**出现在这个文件里**了 —— 而夹具的 path 指的正是这个文件,
        # 于是「找不到」变成「找到 1 次」,这一条当场假绿。
        # (bite-debt.md 记过这个形状:判据的搜索范围盖住了被测的东西自己。)
        没有这段 = "咬合夹具·" + "这段文本不在任何源码里" + f"·{os.getpid()}"
        丙 = [{"script": "x.py", "改坏": "破坏点过期:要改的那段在文件里已经找不到", "预期红": "随便",
               "file": [{"path": os.path.join("tools", "bite_run.py"),
                         "old": 没有这段, "new": "x"}]}]
        if not 验规格(丙, 根=ROOT):
            print("  ❌ 一条**破坏点已经过期**的规格没被挑出来 —— "
                  "它跑起来会报「改坏了却没红」,冤枉一个好判据"); 坏 += 1
        else:
            print(f"  ✅ 破坏点过期的规格,开跑前就被挑出来({验规格(丙, 根=ROOT)[0][2][:38]}…)")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    # ── ⑦ 自己拿锁那一套(2026-11-05 加)────────────────────────────
    我 = os.getpid()
    链 = 祖先链()
    睡 = subprocess.Popen(["sleep", "30"])          # 活着,但**不是**我的祖先
    try:
        锁例 = [
            ("没有锁 → 不算在锁里", (None, 链), False),
            ("锁主是我自己 → 算", (我, 链), True),
            ("锁主是我的祖先 → 算", (链[-1], 链), True),
            ("**反向** · 活着、但不在我的祖先链上 → **不算**(这条顶掉了「环境变量说我在锁里」那种凭据)",
             (睡.pid, 链), False),
        ]
        for 名, (主, 条), 期 in 锁例:
            实 = 在锁里吗(主, 条)
            if 实 is not 期:
                print(f"  ❌ 自己拿锁:{名} —— 期望 {期} 实得 {实}")
                坏 += 1
        # 接线:真读一次锁文件、真走一次祖先链,不许崩;链至少要有两层(自己 + 一个祖先)
        if len(链) < 2 or 链[0] != 我:
            print(f"  ❌ 自己拿锁:祖先链不成形 {链[:4]} —— **ps 问不出来的时候这一套会整个失灵**,"
                  f"而失灵的样子是「我总是不在锁里」(于是每次都去抢锁)或者"
                  f"「我总是在锁里」(于是永远不拿锁)")
            坏 += 1
        else:
            print(f"  ✅ 自己拿锁 {len(锁例)} 种情况都对(含一条反向:活着但不是祖先的 pid 不算),"
                  f"祖先链 {len(链)} 层、真读过锁文件(现在的锁主:{锁主pid()})")
    finally:
        睡.terminate()
        try: 睡.wait(timeout=5)
        except Exception: pass
    # ── ⑧ 管理后台的解释器:找不到要**拒跑**,不许退回系统 python(2026-11-06 加)──
    #
    # 逼出这条判据的那次翻车:**第一次整轮重放**,19 条 `管理后台/tests/` 的咬合全报
    # 「对照就是红的」,而真相是这份检出没有 `管理后台/.venv`,`os.path.exists` 为假
    # 就退回了系统 python,红在 `ModuleNotFoundError: No module named 'sqlalchemy'` 上。
    # **试纸拿那次的形状去喂**:一个没有 venv 的子检出 + 一条库软链指向有 venv 的主检出。
    # (项目里那条:拿「逼出这条判据的那次翻车」当试纸 —— 扫不到它就是判据的视野漏了。)
    基8 = tempfile.mkdtemp(prefix="bite-自测8-")
    try:
        def _做根(名, 带venv, 库指向=None):
            r = os.path.join(基8, 名)
            os.makedirs(os.path.join(r, "backend"), exist_ok=True)
            open(os.path.join(r, "check.sh"), "w").close()   # `门禁怎么跑` 要读它
            if 带venv:
                os.makedirs(os.path.join(r, "管理后台", ".venv", "bin"), exist_ok=True)
                open(os.path.join(r, "管理后台", ".venv", "bin", "python"), "w").close()
            if 库指向:
                os.symlink(库指向, os.path.join(r, "backend", "lanxiu.db"))
            else:
                open(os.path.join(r, "backend", "lanxiu.db"), "w").close()
            return r

        主8 = _做根("主检出", True)
        子8 = _做根("子检出", False, os.path.join(主8, "backend", "lanxiu.db"))
        孤8 = _做根("孤检出", False)
        借到的 = os.path.join(主8, "管理后台", ".venv", "bin", "python")
        # ⚠️ 比的是 `realpath`:macOS 的临时目录 `/var/folders/...` 本身是条软链
        # (解成 `/private/var/...`),而这个函数顺着库软链找主检出时会解开它 ——
        # 拿字面串比会**一处都对不上**。项目里早有这一刀(「去掉切库前对真库路径的
        # realpath」那条咬合),这次是在自测的夹具这一头又撞到同一件事。
        def _同一个(a, b):
            return bool(a) and bool(b) and os.path.realpath(a) == os.path.realpath(b)
        试纸8 = [
            ("本检出有 venv → 用自己那一份", _同一个(管理后台解释器(主8), 借到的)),
            ("**反向** · 本检出没有、而库软链指向的那个检出有 → **借它那一份**"
             "(11-06 夜 19 条就栽在这里:原来直接退回系统 python,红在 ImportError 上,"
             "而那和「检查看不见这处破坏」长得一模一样)",
             _同一个(管理后台解释器(子8), 借到的)),
            ("两边都没有 → **None**,绝不退回系统 python", 管理后台解释器(孤8) is None),
        ]
        for 名, 真 in 试纸8:
            if not 真:
                print(f"  ❌ 管理后台解释器:{名}"); 坏 += 1
        if all(真 for _, 真 in 试纸8):
            print(f"  ✅ 管理后台解释器 {len(试纸8)} 条都对(含一条反向:子检出借主检出那一份)")

        # 接线:拒跑这件事要真的走到调用方 —— **光有纯函数不算**(项目里那条「破坏点在接线上」)
        旧根 = globals()["ROOT"]
        try:
            globals()["ROOT"] = 孤8
            脚 = os.path.join("管理后台", "tests", "e2e", "test_cross_project_read.py")
            if 门禁怎么跑(脚) is not None:
                print("  ❌ 缺 venv 时 `门禁怎么跑` 还是给出了命令 —— 它会拿系统 python 去跑,"
                      "红的是 ImportError"); 坏 += 1
            elif not 跑不了的理由(脚):
                print("  ❌ `跑不了的理由` 没把它挑出来 —— 主循环会照旧跑对照,"
                      "报成「对照就是红的」,把人指向判据"); 坏 += 1
            else:
                print("  ✅ 接线:缺 venv 时 `门禁怎么跑` 返回 None、`跑不了的理由` 给得出话 —— "
                      "主循环报「这台检出验不了」,不报「对照就是红的」")
        finally:
            globals()["ROOT"] = 旧根
    finally:
        shutil.rmtree(基8, ignore_errors=True)
    if 坏:
        print(f"❌ 副本自测 {坏} 条没过")
        return 1
    # ⚠️ 这里原来写死「5 条全过」,而实际打印的 ✅ 已经是 6 条 ——
    #    **盯着值的描述会漂,而漂了不会报错**。每一条自己都打了 ✅,数字去掉不丢信息。
    print("✅ 副本自测全过")
    return 0


def main():
    # 库正在重建时不跑:对照会是红的,每一条咬合都会报「对照就不绿」(见 tools/rebuild.sh 的互斥标记)
    _mk = os.path.join(ROOT, "backend", ".rebuilding")
    if os.path.exists(_mk):
        try:
            _pid = int(open(_mk).read().strip() or 0)
            os.kill(_pid, 0)
            print(f"⏸  库正在重建(pid {_pid}),这时候跑咬合,对照一定是红的 —— 等它跑完再跑")
            return 3
        except (ValueError, ProcessLookupError, PermissionError):
            pass          # 残留的标记(重建崩了留下的),当没看见
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--specs", default=SPECS)
    # 探测模式:只改坏、把实际红的那几条打出来,用来写「预期红」。
    # 对照绿那一关照走 —— 所以打出来的红,必然是这次破坏造成的。
    ap.add_argument("--discover", action="store_true")
    # 副本本身的保证由 `--自测` 盯着(进门禁):库是副本自己的、大目录是软链、
    # 规格要改的文件是真文件、字节上限真会拦。
    ap.add_argument("--自测", action="store_true", dest="自测")
    a = ap.parse_args()
    # ⚠️ `--list` 不拷副本、不跑检查,不占资源,所以不拿锁;其余一律先拿锁。
    #    这一句之后的代码可能**已经不是原来那个进程**了(execv 挂到 gate_lock 底下)。
    if not a.list:
        先把锁拿上(sys.argv)
    if a.自测: return 自测()

    specs = json.load(open(a.specs, encoding="utf-8")) if os.path.exists(a.specs) else []
    if a.only:
        specs = [s for s in specs if a.only in s["script"] or a.only in s.get("改坏", "")]
    if a.list:
        for s in specs: print(f"  {s['script']:<42} {s['改坏']}")
        print(f"共 {len(specs)} 条")
        return 0

    if not specs:
        print("没有规格可跑"); return 1

    # 先验规格自己,再建副本 —— 规格坏了就别花一个钟头去跑
    坏规格 = 验规格(specs, 根=ROOT)
    if 坏规格:
        print(f"❌ {len(坏规格)} 条规格自己是坏的 —— 它们跑起来会被报成"
              f"「改坏了却没红」,而真相是**破坏根本没施加**:")
        for i, sc, why in 坏规格:
            print(f"     [{i}] {sc}  {why}")
        return 1

    # ⚠️ **夜跑在跑的时候不开始拷库**(2026-10-19 加)—— 这是 `nightly_eval.有人在用()`
    #    那道闸的**另一半**。夜跑会让开重放了,可重放原来不看夜跑:
    #    **谁先开谁赢,后开的那个把前一个的数污染掉。** 只补一半等于把问题换个方向。
    #    评测在调模型,被抢 CPU 的后果是「耗时/条」偏大 —— 而那个数进版本库,
    #    还会被拿去和上一轮同模型的那次比。
    #
    # ⚠️⚠️ **这道闸卡在「开始拷库」这一刻,不卡在「这个脚本被调用」那一刻。**
    #    放到 argparse 之前写过一版,那会连 `--自测` 和 `--list` 一起拦住 ——
    #    而 `--自测` **是进门禁的**,于是夜里跑一次门禁就会红在一个
    #    和改动毫无关系的理由上。一道闸要问两遍:它对什么变严了,
    #    **以及有没有严到不该严的地方**。
    #    (2026-10-20:判「在不在跑」从 `pgrep -f` 换成 PID 文件,理由见 `锁还活着`)
    _锁 = 锁目录()
    if 锁还活着(os.path.join(_锁, ".nightly-eval.pid")):
        print("⏸  夜跑评测正在跑(.nightly-eval.pid 里那个进程还活着)—— 这时候拷库"
              "跑重放会把它的「耗时/条」拖慢,而那个数会进版本库。"
              "等夜里那个窗口过去(到 4:55)再跑。")
        return 3
    # 反过来也要让夜跑看得见我 —— `nightly_eval.有人在用()` 读的就是这个文件
    占上锁(os.path.join(_锁, ".bite-run.pid"))

    base = tempfile.mkdtemp(prefix="bite-")
    pristine = 建副本(os.path.join(base, "pristine"))
    print(f"副本:{base}")
    print("=" * 96)

    对照 = {}
    红 = []
    验不了 = []          # 「这台检出跑不了」—— 和「判据死了」分开记
    for i, s in enumerate(specs, 1):
        script, expect = s["script"], s["预期红"]
        work = os.path.join(base, "work")
        if os.path.isdir(work): shutil.rmtree(work)
        # ⚠️ **`symlinks=True` 不能省。** 省掉它,copytree 会**跟着软链走**,
        # 把 `商品图备份` / `backend/static/img*` 整份拷实 —— 一条规格 10.7 GB、19 秒,
        # 而 `pristine` 那一份是瘦的,**看上去一切正常**。
        # 2026-10-17 实测:加上这个参数,单条从 31 秒掉到 1 秒以内。
        shutil.copytree(pristine, work, symlinks=True)

        # ① 前置:把库建成这条咬合需要的状态(可选)
        #
        # ⚠️ **为什么要有它。** 有一类咬合「破坏要生效必须先把库建成某个状态」——
        # 2026-10-17 一天里**三次独立撞到**:
        #   · `rating_rebuild_check` 只在「库里记了造数输入指纹」时才硬判,
        #     而这个检出的库是加指纹**之前**造的 → 那条咬合在本机永远验不到;
        #   · `seed.py` 的「注销后关闭合并工单」登记,要先建一次库才看得见;
        #   · 同一段那条 assert 同理。
        # 三次都只能记进账、配不了咬合。而缺的其实只是「跑之前先做几步」。
        #
        # **这是增强,不是放宽**:它让原本验不到的咬合真的能验,
        # 而不是给咬合开一个「验不到就不判红」的出口 —— 那两件事当天被我混过一次。
        #
        # ⚠️ **有前置的规格不能共用对照缓存**:前置改了库,对照自然和别人不同。
        # 所以缓存的键是 (脚本, 前置),不是脚本。
        前置 = tuple(s.get("前置", ()))
        if 前置:
            挂 = None
            for cmd in 前置:
                try:
                    pp = subprocess.run(cmd, shell=True, cwd=work, capture_output=True,
                                        text=True, timeout=1800)
                except subprocess.TimeoutExpired:
                    挂 = f"`{cmd}` 跑了 30 分钟还没完"; break
                if pp.returncode != 0:
                    尾 = (pp.stdout + pp.stderr).strip().split("\n")[-1][:120]
                    挂 = f"`{cmd}` 退出码 {pp.returncode}:{尾}"; break
            if 挂:
                # **单独报,不混进「改坏了却没红」** —— 这是今天最贵的那个教训:
                # 三种失败报同一句话,13 条里有 5 条把人指向了错误的修复对象。
                print(f"  ❌ [{i}/{len(specs)}] {script}  前置步骤没跑成:{挂}")
                print(f"       —— **这不是判据的错**,是这条咬合需要的库状态没建起来")
                红.append(s); continue

        # ①·5 **这台检出压根跑不了的,单独报一类。**
        #     不混进「对照就是红的」—— 后者会把人指向判据,而这里要做的是去装依赖。
        不行 = 跑不了的理由(script)
        if 不行:
            print(f"  ⛔ [{i}/{len(specs)}] {script}  **这台检出验不了** —— {不行}")
            验不了.append(s); continue

        # ② 对照要绿
        键 = (script, 前置)
        if 键 not in 对照:
            rc0, out0 = 跑(work, script)
            对照[键] = (rc0, out0)
        rc0, out0 = 对照[键]
        if rc0 != 0:
            print(f"  ❌ [{i}/{len(specs)}] {script}  **对照就是红的** —— 这条咬合证明不了任何事"
                  + ("(它有前置步骤,先怀疑前置把库建成了判据不认的样子)" if 前置 else ""))
            红.append(s); continue

        # ② 改坏
        err = None
        if s.get("sql"):   err = 改库(work, s["sql"])
        if not err and s.get("file"):
            for f in s["file"]:
                err = 改文件(work, f["path"], f["old"], f["new"])
                if err: break
        if err:
            print(f"  ❌ [{i}/{len(specs)}] {script}  {err}")
            红.append(s); continue

        # ③ 红的必须是那一条
        rc, out = 跑(work, script)
        # 红有两种长相:自己打 ❌ 的,和直接 assert 抛出来的。
        # 只认前者的话,用 assert 的脚本会被判成「红的不是那一条」——
        # 而那是**判据贴着字面(找 ❌ 这个符号)而不是含义(这一条失败了)**。
        def 是红行(l):
            # 失败的写法不止一种:❌ / ✗ / assert 抛出 / 「失败」二字。
            # 只认某一个符号,就是**判据贴着字面而不是含义** —— 这道执行器自己栽过两次:
            # 先是只认 ❌(用 assert 的脚本判不出),再是漏了 ✗(fakedata 那套用的是它)。
            return any(k in l for k in ("❌", "✗", "AssertionError", "Error:"))
        命中 = [l for l in out.split("\n") if 是红行(l) and expect in l]
        if a.discover:
            reds = [l.strip() for l in out.split("\n") if 是红行(l)][:3]
            print(f"  🔍 [{i}/{len(specs)}] {script}  rc={rc}  {s['改坏']}")
            for l in reds: print(f"       红:{l[:120]}")
            if rc == 0: print("       ⚠️ 改坏了却没红 —— 这处破坏检查看不见"); 红.append(s)
            continue
        if rc == 0:
            print(f"  ❌ [{i}/{len(specs)}] {script}  改坏了却**没红** —— 检查看不见这处破坏")
            红.append(s)
        elif not 命中:
            别的 = [l.strip() for l in out.split("\n") if 是红行(l)][:2]
            print(f"  ❌ [{i}/{len(specs)}] {script}  红了,但**红的不是那一条**")
            print(f"       预期:{expect}")
            for l in 别的: print(f"       实际:{l[:110]}")
            红.append(s)
        else:
            print(f"  ✅ [{i}/{len(specs)}] {script}  {s['改坏']}")

    print("=" * 96)
    shutil.rmtree(base, ignore_errors=True)
    if 验不了:
        脚本们 = sorted({s["script"] for s in 验不了})
        print(f"⛔ {len(验不了)}/{len(specs)} 条**在这台检出上验不了**(涉及 {len(脚本们)} 个脚本)"
              f" —— 没被验,**不是通过**,也不是判据坏了")
        for n in 脚本们[:6]:
            print(f"     · {n}")
        if len(脚本们) > 6:
            print(f"     · ……还有 {len(脚本们) - 6} 个(共 {len(脚本们)})")
    if 红:
        print(f"❌ {len(红)}/{len(specs)} 条咬合规格没过 —— **这些检查没被证明过**")
        return 1
    if 验不了:
        # 退非零:**别把「没验」读成「全过」**。没有一条判据在这一轮里被证伪,
        # 而上面那几条也没有被证明过 —— 这两件事都要留在退出码上。
        print(f"✅ 跑得了的 {len(specs) - len(验不了)} 条全过;⛔ 上面那 {len(验不了)} 条没被验 —— **退非零**")
        return 1
    print(f"✅ {len(specs)} 条咬合规格全过(每条都验了:对照绿 → 改坏 → 红的是那一条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
