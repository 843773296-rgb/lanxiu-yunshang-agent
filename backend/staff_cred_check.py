#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**谁都不许对 `staff` 用星号查** —— 除了登录验证那一处。

## 为什么要这条

`staff` 表带着 `pwd_algo` / `pwd_salt` / `pwd_hash`。项目铁律:
**账户凭据绝不能经工具层读到,凭据绝不写进任何返回值或异常。**

`api._rows` 里有一道锁专门防它(注释原话:「星号会把 pwd_* 带出来」)。
**但那道锁只保护走它那条路的调用。** 2026-10-27 一天里,同一个错出现在三个
互不相干、都不走 `api._rows` 的地方:

    · 我自己在终端上 `sqlite3 SELECT * FROM staff` —— 哈希打到了屏幕上
    · `backend/server.py` 自己开连接、自己写 `rows()`(只做 dict(r)、不剥列),
      而结果**直接拼进接口返回** —— 哈希和盐会进 HTTP 响应
    · `backend/booking.py` 按工号取员工,返回整行给调用方

> 一道装在某个函数里的守卫,和一条「这件事不许发生」的规矩,
> **在「我们防住了」这句话上长得一模一样** —— 而前者只保护走它那条路的调用。

所以这条检查**扫源码**,不管你走哪个函数、开哪个连接。

## 豁免只有一类,而且必须点名

**登录验证**需要 `pwd_hash` 才能比对密码 —— 那是它的工作。
豁免写成「文件:行」的白名单,**而且这个名单只许少不许多**(棘轮):
名单上有而源码里已经没有了,也要红 —— 否则一条过期的豁免会一直挂着,
而「豁免还需要」和「豁免早就不需要了」在名单上长得一样。
"""
import io, os, re, sys

# 咬合 —— **改坏的是什么、该红的是哪一条**。只写「测过了」和没写是一回事。
# (可执行的两条在 `tools/bite_specs.json`:
#  `python3 tools/bite_run.py --only "backend/staff_cred_check.py"`)
# ⚠️ 第一版这两条攻在**走不到的分支**上(攻「没扫到就报错」那一支,而正常情况有命中),
# 报「改坏了却没红」—— 而那个没红是对的。攻击点要落在**能让那条分支走到**的东西上。
咬合 = [
    ("把正则里的表名改掉,让它扫不到任何地方", "一处都没扫到"),
    ("往豁免名单里塞一条用不到的", "已经用不到了"),
]


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"

# ⚠️ 点名豁免:只有「登录验证要比对密码」这一类。加之前先问:它真的需要哈希吗?
豁免 = {
    "backend/auth.py": "登录验证:要拿 pwd_hash / pwd_salt 比对密码,这是它的工作",
}

# 扫的是「对 staff 用星号」。⚠️ 这里不写出真实的匹配串,用拼的 ——
# 否则这个文件自己会被自己扫出来(这个项目栽过:被扫描的文件里写出真实匹配串)。
星 = "*"
# ⚠️ 第一版写成 r"…\%s…",raw string 里那个反斜杠让模式变成 `\\*`
# (匹配「零个或多个反斜杠」),于是扫 904 个文件命中 0 处、**看起来全绿**。
# 救它的是下面「一处都没扫到就报判据坏了」那一条 —— 自己写的保护逮到自己的 bug。
模式 = re.compile(r"SELECT\s+" + re.escape(星) + r"\s+FROM\s+staff\b", re.I)

别的检出 = os.path.join(".claude", "worktrees")


def 跳过吗(目录, 根):
    """这个目录要不要跳过。**按相对仓库根的路径判,绝不按绝对路径。**

    ⚠️ 2026-11-05 夜栽在这一行上:原来写的是 `if os.path.join(".claude","worktrees") in d`,
    而 `d` 是 `os.walk` 给的**绝对路径**。那天这份 worktree 被挪进了
    `~/Desktop/澜绣云裳agent/.claude/worktrees/工` —— 于是**每一个目录的绝对路径里都含着那个名字**,
    条条命中、条条跳过,`查过` 变成 0。
    > 这条排除规则一个字都没改,而它的含义被挪目录改掉了 ——
    > 原来是「跳过别人的检出」,现在是「跳过我自己」。
    救它的是下面那条「扫到的文件数要够」—— 否则它会印「共 0 处」然后**绿着**。
    ⚠️ `tools/impact.py` 里**早就写着**这条教训(10-23 一个子任务踩过同样的坑,注释原话
    「按相对仓库根的路径判断,不按绝对路径」),而这个文件照旧按绝对路径写 ——
    **教训记在一个地方,而下一次踩它的人不在那个地方。**
    ⚠️ **别给这件事配「把它改回绝对路径」那种咬合**:`bite_run` 在临时目录的副本上重放,
    那个路径里不含 `.claude/worktrees`,所以那一刀在副本里**一点事都没有** ——
    破坏点不可观测,咬合会永远「没红」。判据要打在这个函数上(见下面的自测)。
    """
    rel = os.path.relpath(目录, 根)
    if rel == os.curdir:
        return False
    段 = rel.split(os.sep)
    if any(x in 段 for x in (".git", ".venv", "node_modules", "__pycache__")):
        return True
    # `.claude/worktrees/` 底下是子代理开的**别的检出**(各停在一个旧提交上),不是这份代码 ——
    # 2026-10-29 主检出里有 10 份,这条把它们的旧 server.py 也扫进来,红了 50 处,而 CI 和别的检出上没有这个目录。
    # **只跳这一层**:`agentsite/.claude/skills/` 里技能自己的脚本照样要扫(它们也可能查 staff)
    return rel == 别的检出 or rel.startswith(别的检出 + os.sep)


# ── 自测:拿 2026-11-05 那次翻车当试纸 ──────────────────────────────
# 这三条里**第二条**就是那次翻车。它在任何路径下都可观测(不像「改回绝对路径」那一刀)。
_挪进去了 = os.path.join(os.sep, "x", "proj", ".claude", "worktrees", "工")
_试纸 = [
    ("仓库根下的 .claude/worktrees 要跳(那是别人的检出)",
     跳过吗(os.path.join(ROOT, ".claude", "worktrees", "agent-a1"), ROOT) is True),
    ("**反向** · 自己就住在 .claude/worktrees 底下时,自己的目录**不许**被跳过 —— "
     "绝对路径里含那个名字,相对仓库根却不含(11-05 夜就栽在这里,扫到 0 个文件)",
     跳过吗(os.path.join(_挪进去了, "backend"), _挪进去了) is False),
    ("只跳那一层:agentsite/.claude/skills 照样要扫(技能脚本也可能查 staff)",
     跳过吗(os.path.join(ROOT, "agentsite", ".claude", "skills"), ROOT) is False),
]
_挂 = [名 for 名, 真 in _试纸 if not 真]
if _挂:
    print(f"{R}❌ 员工表凭据 · 判据自己的自测就不过 —— 下面扫出来的数一个都不能信:{D}")
    for 名 in _挂:
        print(f"  {R}❌{D} {名}")
    sys.exit(1)

命中, 查过 = [], 0
for d, _, fs in os.walk(ROOT):
    if 跳过吗(d, ROOT):
        continue
    for f in fs:
        if not f.endswith(".py"):
            continue
        p = os.path.join(d, f)
        rel = os.path.relpath(p, ROOT)
        if rel == os.path.join("backend", os.path.basename(__file__)):
            continue                      # 自己不算
        try:
            src = io.open(p, encoding="utf-8").read()
        except Exception:
            continue
        查过 += 1
        for i, line in enumerate(src.split("\n"), 1):
            if 模式.search(line):
                命中.append((rel, i))

坏 = [(f, i) for f, i in 命中 if f not in 豁免]
用到的豁免 = {f for f, _ in 命中 if f in 豁免}
过期豁免 = [f for f in 豁免 if f not in 用到的豁免]

print("员工表凭据 · 检查")
print(f"  扫了 {查过} 个 .py;对 staff 用星号的共 {len(命中)} 处,其中豁免 {len(命中) - len(坏)} 处")
# ⚠️ **地板,不是棘轮** —— 够高就行,不用跟着实际涨(项目里那条「分清地板和棘轮」)。
# 原来写的是 `查过 == 0`,而那只挡得住**全坏**:11-05 夜那次正好是全坏(0 个)所以被逮到了。
# 少跳一个目录那种**部分**失效,`查过` 还有几百,`== 0` 一声不响。
# 500 的来路:跟踪的 .py 是 977 个(CI 拿到的就是这些),本机扫到 976 —— 取一半出头,
# 删掉半个仓库才会误报,而少扫掉任何一个大目录都会红。
文件下限 = 500
if 查过 < 文件下限:
    print(f"{R}❌ 只扫到 {查过} 个 .py(下限 {文件下限})—— **判据坏了,不是「全都对」**。"
          f"先去看 跳过吗() 是不是把该扫的目录也跳了{D}")
    sys.exit(1)
if not 命中:
    print(f"{R}❌ 一处都没扫到(连豁免的登录验证也没有)—— 判据大概坏了:"
          f"**「没东西可验」要和「验过了」分开**{D}")
    sys.exit(1)

for f, i in 坏:
    print(f"  {R}❌{D} {f}:{i} 对 staff 用了星号 —— "
          f"**会把 pwd_algo / pwd_salt / pwd_hash 带出来**。改成列名写死")
for f in 过期豁免:
    print(f"  {R}❌{D} 豁免 {f} 已经用不到了 —— **只许少不许多**,删掉它。"
          f"一条过期的豁免会一直挂着,而「还需要」和「早就不需要了」在名单上长得一样")

if 坏 or 过期豁免:
    print(f"{R}❌ 员工表凭据 {len(坏) + len(过期豁免)} 条不过{D}")
    sys.exit(1)
print(f"{G}✅ 只有点名豁免的那处(登录验证)对 staff 用星号,别处一律列名写死{D}")
