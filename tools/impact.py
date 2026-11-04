#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改动影响面 —— **动手之前问一句「这一改会破坏什么」。**

## 为什么是这个形状,而不是一份 plan.md 模板

读 Anthropic 那篇《AI-Native SDLC Playbook》时,Build 阶段的核心动作是
「先进 Plan Mode,列出准备改哪些文件、可能影响什么、要跑哪些测试,
**工程师接受之前不许改代码**」。

这个项目照抄一份 `plan.md` 模板是没用的 —— 它会变成第三份漂着的文档。
**真正有价值的是那一问:「这一改会破坏什么?」** 而它可以机械回答。

## 证据:2026-09-15 一天翻车四次,每一次这一问都能挡住

    把 seed 的真值标注改成调口径模块   → 破坏了**故意的双实现**,跑红三条检查。
                                       那段注释明写着「独立解析出来的另一套」,**我没读**
    咬合测试把 239 个技能删了          → 源和目标变成同一个路径,rmtree 删的是真目录
    给评测题补了个工具查不了的单号     → 造出一道无解的题
    把判据从 162 改成 152              → **往危险的那一侧放宽**:让判分器开始接受报短的工期

四次的共同点:**我改的时候只看这句话读着顺不顺,没看它连着什么。**

## 它报三样

**① 你这次碰到的「⚠️ 警示段落」。** 这个项目里有 21 处写着
「不许 / 别在这儿 / 故意 / 不要」的段落 —— 它们是前人(或前几个小时的我)
用一次事故换来的。**改到它附近而没读它,是这些事故复发的主要方式。**

**② 覆盖这些文件的检查有哪几条。** 改完至少要跑它们
(`check.sh` 会全跑,但**知道哪几条该红**和「全绿就完事」是两回事)。

**③ 这次改动有没有删东西。** 删除是不可逆的那一类,单独拎出来。

用法:

    python3 tools/impact.py           # 看工作区还没提交的改动
    python3 tools/impact.py HEAD~3    # 看最近三次提交动了什么
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
警示 = re.compile(r"⚠️?.{0,40}(不许|别在|别去|故意|不要|千万|永远不)")

# ⚠️ 这份记录我第一次写错过:右边那句写的是「这次碰到的警示段落」,
# 而脚本里那句是「**这次碰到 {n} 处警示段落**」——**差在那个占位符上**,
# `bite_check` 当场抓住(它要求「预期红的那一条」真的在脚本里出现过)。
# **一份写错了的咬合记录,和没有记录一样没用** —— 它指的那句话不存在。
咬合 = [
    ("把找警示段落的正则改窄(只留「千万」)",
     "找得到的警示段落"),
    ("把某个文件里的 ⚠️ 警示行删掉,再改它附近",
     "处警示段落 —— 改之前先把它们读一遍"),
]


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                          text=True).stdout


def 改动(base=None):
    """返回 {文件: [(起, 止), …]} —— 改动落在哪些行区间。"""
    args = ["diff", "-U0"] + ([base] if base else [])
    out, cur, res = _git(*args), None, {}
    for line in out.split("\n"):
        if line.startswith("+++ b/"):
            cur = line[6:]; res.setdefault(cur, [])
        elif line.startswith("@@") and cur:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                a = int(m.group(1)); n = int(m.group(2) or 1)
                res[cur].append((a, a + max(n, 1) - 1))
    return {k: v for k, v in res.items() if k.endswith(影响面认的扩展名)}


# ⚠️⚠️ **这个白名单漏过一次,而漏的那天报告照样是干净的。**
# 2026-11-04 查出来:原来只写 (".py", ".md", ".sh"),而门禁里跑着
# **7 个 `.mjs`**(四个 hook + 三个检查脚本)和 **1 个 `.js`** ——
# 它们的改动**从来不在影响面里**。而 hook 是能拦住收工的东西:
# 改坏一个 hook,影响面一个字都不会说。
# > 一份少算了文件的影响面,和一份完整的影响面,**在报告干净这件事上长得一模一样。**
影响面认的扩展名 = (".py", ".md", ".sh", ".mjs", ".js")

# 豁免:门禁 run 行里出现、但**不是源码**的文件。
# ⚠️ 每一条都要写理由,而且下面 自检扩展名() 会**反向查**它还成不成立 ——
#    没有这一半,豁免表会慢慢攒满早就不存在的条目,而囤积的豁免和真豁免长得一样。
影响面不认的 = {
    ".db": "SQLite 库文件:二进制,而且 backend/lanxiu.db 是条软链",
}


def 自检扩展名():
    """门禁实际在跑的那些文件,影响面认不认它们的扩展名?

    ⚠️ **不枚举扩展名** —— `.mjs` 正是枚举漏掉的。改问**结构**:
       `check.sh` 的 run 行里真实存在的文件,扩展名要么在白名单里,
       要么在豁免表里有理由。将来有人加个 `.ts` 检查,这条会自己报出来。
    ⚠️ 同时**反向查豁免**:豁免表里的扩展名,门禁里还真有这种文件吗?
    回 (扫了几个文件, 没认的, 豁免里已经没用的)
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    见到 = {}
    for line in sh.split("\n"):
        if not line.strip().startswith("run "):
            continue
        # ⚠️ 这里故意扫整行而不只扫 run 的标题:`\` 续行把真命令挪到了下一行
        #    (agentsite/js_smoke.js 就是这样),但那种情况标题里通常也写了文件名。
        for m in re.findall(r"([\w/.\-]+\.[a-z]{1,4})\b", line):
            p = os.path.join(ROOT, m)
            if os.path.isfile(p):
                见到.setdefault(os.path.splitext(m)[1], set()).add(m)
    没认 = sorted((e, sorted(fs)) for e, fs in 见到.items()
                  if e not in 影响面认的扩展名 and e not in 影响面不认的)
    白费 = sorted(e for e in 影响面不认的 if e not in 见到)
    return sum(len(v) for v in 见到.values()), 没认, 白费


def 覆盖(path):
    """check.sh 里哪几条检查跑到了这个文件。

    分三档,**因为「没直接点名」和「没人管」是两件事**:

      直接   check.sh 那一行里就写着这个文件
      间接   有检查 import 它(顺着 import 找一层)
      全局   `backend/seed.py` 这种 —— 没有任何一条直接点名,
             **而所有检查都跑在它生成的库上**

    ⚠️ 第一版只认「直接点名」,于是给 `seed.py` 打出
    「**覆盖它的检查:一条都没有 —— 改坏了不会有任何地方报**」——
    **吓人且不准**。那正是今天反复说的那种错:
    **一个判据只看它看得见的那一维,然后把「我没看到」说成「没有」。**
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    base = os.path.basename(path)
    直接, 间接 = [], []
    脚本 = []
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        m = re.search(r'run "([^"]+)"', line)
        名 = m.group(1) if m else line[:40]
        if path in line or base in line: 直接.append(名); continue
        脚本 += [(名, x) for x in re.findall(r"([\w/]+\.py)", line)]
    # 顺着 import 找一层
    mod = base[:-3] if base.endswith(".py") else None
    if mod:
        for 名, sp in 脚本:
            f = os.path.join(ROOT, sp)
            if not os.path.isfile(f): continue
            try: t = open(f, encoding="utf-8").read()
            except Exception: continue
            if re.search(rf"\bimport +{re.escape(mod)}\b|\bfrom +{re.escape(mod)} +import", t):
                间接.append(名)
    if 直接 or 间接:
        return [f"{x}(直接)" for x in 直接] + [f"{x}(间接)" for x in dict.fromkeys(间接)]
    # 数据生成器:没人点名,但所有检查都跑在它生成的库上
    if base in ("seed.py",) or path.startswith("knowledge/derive_"):
        return ["**全员** —— 它生成的是所有检查跑的那个库,改坏了哪一条先红说不准"]
    return []


def 自检():
    """**这个工具自己会不会变瞎。**

    它靠一个正则去找「⚠️ + 不许/别在/故意」的警示段落。
    而正则会因为措辞变化而漏 —— **漏的那天它照样输出一份干净的报告**,
    而那正是它该报警的时候。

    所以钉一个下限:全库里找得到的警示段落不许少于这个数。
    (和来源欠账、咬合欠账一样:**钉住,只许涨不许掉**。)
    """
    import glob
    n = 0
    for p in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
        # ⚠️ 按**相对仓库根**的路径判断,不按绝对路径 —— 并行子任务的工作区本身在 `.claude/worktrees/` 下,
        # 拿绝对路径判 `/.claude/` 会把整个工作区都跳过,于是「找得到 0 处」、自测红(10-23 子任务 A 查出)
        r = os.path.relpath(p, ROOT)
        if ".venv" in r.split(os.sep) or r.startswith(".claude" + os.sep): continue
        try: t = open(p, encoding="utf-8").read()
        except Exception: continue
        n += sum(1 for line in t.split("\n") if 警示.search(line))
    return n


# 全库警示段落的**下限** —— 2026-09-15 扫出来 21 处。
# 少于这个数,多半是正则漏了(措辞变了),不是警示真的被删了 ——
# **而漏的那天它照样输出一份干净的报告。**
#
# ⚠️⚠️ **原来这里写死 `警示下限 = 21`,而实际找得到三百多处 —— 棘轮装好了,
#    但没有东西推它。** 2026-11-04 发现,和同一天查出的交接门禁那条「写死 80%,
#    而压缩在 30% 就来」是**同一个病**:
#
#      写死的那天它是对的。它不是写错了,是**没人回来看它** ——
#      而没人回来看的时候,它和一条守得住的下限长得一模一样。
#
#    所以改成自己会走的棘轮:基线存在 `tools/影响面基线.json`(进版本库,CI 也读得到),
#    **只许涨不许降**,涨了自动写进去并提示提交。
#
# ⚠️ **方向只能单向自动,这是这个机制的命门。** 少了后半句它会变成「永远绿」:
#    警示段落被删一批 → 基线跟着降 → 下限跟着降 → 永远满足。
#    > 一个会自动放宽的棘轮,和一道守得住的下限,**在绿勾上长得一模一样。**
#    所以「掉下来时不许自动降」那条判据比「涨了要提」更重要。
保底 = 21                 # 2026-09 首次钉的数,留着当地板 —— 基线文件丢了也不会归零
基线文件 = os.path.join(ROOT, "tools", "影响面基线.json")


def 读基线():
    try:
        return int(json.load(open(基线文件, encoding="utf-8"))["警示段落"])
    except Exception:
        return 0          # 文件没了/坏了 → 退回保底,不崩


def 判基线(当前, 基线, 保底值):
    """纯函数,好验。回 (下限, 该红吗, 要不要提基线)

    ⚠️ 写成纯函数**就是为了能单独验它** —— 三种情况(持平/掉了/涨了)的下一步
       动作完全不同,而混在打印逻辑里就只能靠眼睛看。
    """
    下限 = max(保底值, int(基线 * 0.9))
    return 下限, 当前 < 下限, 当前 > 基线


def 写基线(n):
    """只在涨了的时候调。**这个函数不负责判断方向** —— 调它之前必须先问过 判基线()。"""
    import datetime
    with open(基线文件, "w", encoding="utf-8") as f:
        json.dump({"警示段落": n, "更新于": datetime.date.today().isoformat()},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    if "--selftest" in sys.argv:
        # ── 先验棘轮自己(纯函数,四种情况)──────────────────────────────
        # ⚠️ 第二条是**反向**的,而且是这组里最要紧的一条:
        #    少了它,这个棘轮会自动放宽,然后永远绿。
        棘轮用例 = [
            ("持平 → 不红、不用提",      (336, 336, 21), (302, False, False)),
            ("掉到九成以下 → 红,**而且不许自动把基线降下去**",
                                         (200, 336, 21), (302, True,  False)),
            ("涨了 → 不红,该把基线提上去", (400, 336, 21), (302, False, True)),
            ("基线文件没了 → 退回保底,不崩,并记下当前值",
                                         (100, 0,   21), (21,  False, True)),
            # ⚠️ 这一条是为了**把两种破坏分开**加的:它让「该红吗」正确、
            #    而「要不要提基线」有机会出错。少了它,「把 `当前 > 基线` 写成
            #    `当前 != 基线`」和「把下限判断改成只看保底」会红在同一条用例上,
            #    于是咬合的第三关(红的必须是指定那一条)分辨不出是哪处坏了。
            ("比基线低、但还在下限之上 → 不红,**也不该提基线**(正常波动不是涨)",
                                         (320, 336, 21), (302, False, False)),
        ]
        棘轮坏 = []
        for 名, 入, 期 in 棘轮用例:
            实 = 判基线(*入)
            if 实 != 期:
                棘轮坏.append(f"{名}  期望{期} 实得{实}")
        if 棘轮坏:
            print(f"  ❌ 基线棘轮本身坏了 {len(棘轮坏)} 处:")
            for x in 棘轮坏:
                print(f"     {x}")
            return 1
        # ⚠️ 条数**算出来,不写死**。原来这儿写「四种情况」,而加了第五条之后
        #    它当场就漂了 —— 我同一天在 `check.sh` 的 run 标题和一条记忆里
        #    各踩过一次同样的事。**凡是写在话里的条数都会漂,而漂了没人会发现。**
        print(f"  ✅ 基线棘轮 {len(棘轮用例)} 种情况都对(含「掉下来不许自动降」那条反向的)")

        n = 自检()
        基线 = 读基线()
        警示下限, 该红, 要提 = 判基线(n, 基线, 保底)
        ok = not 该红
        print(f"  {'✅' if ok else '❌'} 找得到的警示段落 {n} 处(下限 {警示下限},基线 {基线 or '还没记'})")
        if not ok:
            print("     **正则多半漏了** —— 措辞一变它就找不着,")
            print("     而漏的那天它照样输出一份干净的报告,那正是该报警的时候。")
            print(f"     ⚠️ 基线是 {基线},**不会**因为这次掉下来就跟着降 —— 棘轮只许涨。")
            return 1
        if 要提:
            写基线(n)
            print(f"     ℹ️ 基线从 {基线 or 0} 提到 {n} —— **已经替你写进 {os.path.relpath(基线文件, ROOT)} 了,"
                  f"记得把它一起提交。** 下限随之变成 {int(n * 0.9)}")
        else:
            print("     **钉住下限,只许涨不许掉** —— 和来源欠账、咬合欠账同一个办法")

        # ── 门禁跑的文件,影响面认不认(2026-11-04 加)──────────────────
        共, 没认, 白费 = 自检扩展名()
        坏 = False
        # ⚠️ 先报样本量:**空集合上这条性质自动成立**。
        #    扫不到文件时「全认了」和「什么都没扫」在输出上一模一样。
        if 共 < 50:
            print(f"  ❌ 只在 check.sh 的 run 行里扫到 {共} 个真实文件(下限 50)——"
                  f" **这是扫描失败,不是全认了**")
            坏 = True
        else:
            print(f"  ✅ 门禁 run 行里扫到 {共} 个真实存在的文件")
        if 没认:
            坏 = True
            for e, fs in 没认:
                例 = "、".join(fs[:4]) + (f"  ……还有 {len(fs) - 4} 个(共 {len(fs)})" if len(fs) > 4 else "")
                print(f"  ❌ 门禁在跑 {len(fs)} 个 `{e}` 文件,而影响面**不认这个扩展名**:{例}")
            print("     改它们的时候影响面一个字都不会说 —— 加进 影响面认的扩展名,")
            print("     或者加进 影响面不认的 并写清为什么它不是源码。")
        else:
            print("  ✅ 门禁跑的每种扩展名,影响面都认(或有豁免理由)")
        if 白费:
            坏 = True
            print(f"  ❌ 豁免表里这些扩展名门禁里已经没有了,删掉:{'、'.join(白费)}")
            print("     **囤积的豁免和真豁免长得一模一样** —— 所以这一半必须反着查。")
        else:
            print(f"  ✅ 豁免表 {len(影响面不认的)} 条都还成立(反向查过)")
        return 1 if 坏 else 0
    base = sys.argv[1] if len(sys.argv) > 1 else None
    ch = 改动(base)
    print("改动影响面 —— **动手之前问一句「这一改会破坏什么」**")
    print("=" * 88)
    if not ch:
        print("  工作区没有改动。(看历史:python3 tools/impact.py HEAD~3)")
        return 0

    print(f"\n【碰到的文件】{len(ch)} 个\n")
    警 = 删 = 0
    for f, spans in sorted(ch.items()):
        p = os.path.join(ROOT, f)
        cov = 覆盖(f)
        print(f"  {f}")
        print(f"      覆盖它的检查:"
              f"{('、'.join(cov[:3]) + ('…' if len(cov) > 3 else '')) if cov else '**一条都没有** —— 改坏了不会有任何地方报'}")
        if not os.path.isfile(p): 
            print("      **这个文件没了(删除?)** —— 删除是不可逆的那一类"); 删 += 1; continue
        lines = open(p, encoding="utf-8").read().split("\n")
        # 改动行附近 12 行内的警示段落
        碰 = []
        for a, b in spans:
            for i in range(max(0, a - 12), min(len(lines), b + 12)):
                if 警示.search(lines[i]) and lines[i] not in 碰:
                    碰.append(lines[i])
        if 碰:
            警 += len(碰)
            print(f"      ⚠️ **这次碰到 {len(碰)} 处警示段落 —— 改之前先把它们读一遍**:")
            for x in 碰[:4]:
                print(f"         {x.strip()[:84]}")

    # ⚠️ **分母要干净。** 2026-11-03:这个数原来把 `agentsite/evals/` 那两个
    # **滚动截断副本**算了进去 —— 它们每跑一轮评测就整体重写,于是一次纯 +10 行的
    # 改动在这儿报成「删掉 880 行,确认每一段都是有意删的」。
    # > 一次真的大量删除,和一次滚动副本的例行截断,**在那句警告上长得一模一样**。
    # 而危害不在这一次读错:**平时天天响的警告,真有人删掉 880 行代码时不会有人看。**
    # 同一个病这个项目记过一次(归因时按日期聚合 token,把另一个会话当天的 66 次调用
    # 混进了同一个分母,**分母不干净,归因就全错**)。
    # 判据**不枚举文件名**:滚动副本的结构特征是「**被 git 跟踪、同时又命中 .gitignore**」
    # —— 这个矛盾状态正是「本来不该进版本库、而历史上已经进去了」的定义
    # (gitignore 对已跟踪的文件无效,所以它们一直显示成 modified)。
    # 以后多一个会自动认出来;哪天有人 `git rm --cached` 掉,这个集合自动变空 ——
    # **留不下一份过期的硬编码豁免名单**(这是「豁免不许囤积」的免疫版:现算的名单囤不起来)。
    # ⚠️ 必须 `core.quotepath=false`:这个仓库大半文件名是中文,git 默认转义输出,
    # 路径比对永远对不上 —— `bite_replay_touched` 为这条栽过,实测少算一半。
    滚动副本 = set(_git("-c", "core.quotepath=false",
                    "ls-files", "-i", "-c", "--exclude-standard").splitlines())
    d = _git("-c", "core.quotepath=false", "diff", "--numstat",
             *( [base] if base else [] ))
    删行 = 滚动删行 = 0
    for x in d.strip().split("\n"):
        列 = x.split("\t")
        if len(列) < 3 or not 列[1].isdigit():
            continue
        if 列[2] in 滚动副本:
            滚动删行 += int(列[1])
        else:
            删行 += int(列[1])
    print(f"\n【删掉的行】{删行} 行")
    # **排除了什么必须印出来** —— 悄悄缩小分母是同一个病的另一半
    if 滚动删行:
        print(f"      (另有 {滚动删行} 行来自滚动截断副本,**不计入**:"
              f"{'、'.join(sorted(滚动副本))} —— 它们每跑一轮评测整体重写,"
              f"删除行数天天几百,混进来这个警告就废了)")
    if 删行 > 200:
        print("      ⚠️ **删得不少。** 删除是不可逆的那一类 —— "
              "确认每一段都是有意删的,不是顺手清掉的")

    print("\n" + "=" * 88)
    print(f"  碰到 {警} 处警示段落。**它们是前人用一次事故换来的** ——")
    print("  这个项目 2026-09-15 一天翻车四次,每一次「这一改会破坏什么」都能挡住,")
    print("  而四次的共同点是:**只看了这句话读着顺不顺,没看它连着什么。**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
