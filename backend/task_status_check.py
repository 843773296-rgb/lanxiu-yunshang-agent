#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 id 找一条人工任务,不许绑在某个状态上。

⚠️ **这条判据是一次实际故障换来的**(2026-10-15)。四处同一个病:

| 位置 | 它要干什么 | 绑了「待处理」之后实际 |
|---|---|---|
| `server.py` 的 `/api/agent-run` | 页面点「跑这个任务」,按 id 找 | 已处理的点下去报**「任务不存在」** |
| `v1.py` 的 `one()` | 同上,V1 的单任务口 | 同样 |
| `v1.py` 取样 | 取这两类 40 条工单 | **0 条 → IndexError,V1 跑不起来** |
| `eval.py` 的 `pick()` | 评测分层取样 | 空列表 —— **静默取空,不报错** |

四处都写着 `status="待处理"`,而那**当年是对的**:任务刚造出来时全部是待处理,
于是「待处理」和「全部」恰好相等。**一处理它就静默变 0**,而没有任何东西会红。

> 一个「这条任务不存在」和一个「这条任务不在我查的那个状态里」,
> **在「找不到」这个结果上长得一模一样。**

`selftest.py` 里记过同一个病的一次(`IndexError: list index out of range`),
而当时**只修了自测那一处** —— 另外四处带着同样的写法又活了四天。

────────────────────────────────────────────────────────────────────
**这条判据自己差点变成一次同源谬误。**

第一版在库副本上**自己重写了一份**「按 id 找一条」去验,于是把 `server.py`
改回 `status="待处理"`,这条判据照样全绿 —— 它验的是我重写的那份。

> 一个「验了那段代码」和一个「验了我重新实现的一份」,
> **在绿勾上长得一模一样。**

修法不是把判据写得更像那段代码,是**让那段逻辑只剩一份**:
`api.find_task()`,两个调用方都调它,判据**真调它**。
(CLAUDE.md 第 7 条第 2 项的「同源谬误」,这是它在判据侧的变体。)

**夹具怎么确保真的在副本上跑**:往副本插一条**真库里不存在**的 id。
这样「夹具没生效、其实读的是真库」会让第一条当场红,而不是悄悄变成空转 ——
否则拿一条真库里本来就是「已处理」的任务去验,两种情况的结果一模一样。

**为什么不直接在真库上找**:那它红不红就取决于这个库里碰巧有没有非待处理的
任务,而 `seed.py` 造出来的可能全是待处理,于是 CI 上这条等于什么都不验、
而且是绿的。这个仓库对这件事有定论(CLAUDE.md):**代码对不对 → 判据自己造
它要验的形状;这个库上有几种 → 另开一个只打印的口。**
"""
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api  # noqa: E402

咬合 = [
    # 三条全部实跑验过三关(对照先绿 / 改坏要红 / **红的只有点名那一条**),
    # 可执行规格在 `tools/bite_specs.json`。
    ("把 `api.find_task` 里的「看全部任务」改回「待处理」"
     "(这正是 2026-10-15 之前四处那个写法)",
     "`api.find_task` 找得到一条非待处理的任务"),
    ("把 `server.py` 里的 `backend.find_task(tid)` 改回自己手写一份"
     "(绕过那唯一一份实现 —— 而 `find_task` 本身还是好的,所以只有这一条该红)",
     "没有人绕过 `find_task` 重新手写"),
    ("从 `api.TASK_TYPES` 里删掉「评价差评」"
     "(库里 171 条是这一类,而常量里没了 —— schema 的 enum 从它现拼,"
     "漏一种模型就填不出来)",
     "库里出现的类型常量里都有"),
]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
n = 0
bad = []
这里 = os.path.dirname(os.path.abspath(__file__))


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


def 库况(名, 文):
    print(f"  {Y}📖 库况{D} {名}:{文}")


print("按 id 找人工任务,不许绑在某个状态上")
print("=" * 70)

库 = os.path.join(这里, "lanxiu.db")
if not os.path.exists(库):
    print(f"  {Y}⚠️  没有 {库} —— **这不叫通过,这叫没验到**。"
          f"先跑 `python3 backend/seed.py`{D}")
    raise SystemExit(1)

# ── 自造组:副本上插一条真库里没有的、非「待处理」的任务 ──────────────────
夹具号 = "TTEST-任务状态夹具-1"
假 = os.path.join(这里, "lanxiu.db")
cx = sqlite3.connect(f"file:{假}?mode=ro", uri=True)
已有 = cx.execute("SELECT 1 FROM task WHERE id=?", (夹具号,)).fetchone()
cx.close()
if 已有:
    print(f"  {R}❌ 真库里已经有 {夹具号} —— 这个号是夹具专用的,"
          f"真库里有它说明有人把夹具写进了真库{D}")
    raise SystemExit(1)

副目 = tempfile.mkdtemp(prefix="taskstatus-")
副本 = os.path.join(副目, "lanxiu.db")
shutil.copy2(库, 副本)          # 库是软链,copy2 跟随软链拿到真内容
真DB = api.DB
try:
    c = sqlite3.connect(副本)
    一条 = c.execute("SELECT * FROM task LIMIT 1").fetchone()
    if not 一条:
        print(f"  {Y}⚠️  task 表是空的 —— **这不叫通过,这叫没扫到东西**{D}")
        raise SystemExit(1)
    列 = [d[0] for d in c.execute("SELECT * FROM task LIMIT 1").description]
    行 = dict(zip(列, 一条))
    行["id"] = 夹具号
    行["status"] = api.TASK_STATES[2]        # 已处理
    c.execute(f"INSERT INTO task ({','.join(列)}) VALUES ({','.join('?' * len(列))})",
              [行[k] for k in 列])
    c.commit()
    c.close()

    api.DB = 副本                            # 夹具口:让被测代码读副本
    print(f"  （副本上插了一条真库没有的 {夹具号},状态「{api.TASK_STATES[2]}」）")

    # ① 真调 api.find_task —— 不是重写一份
    找到 = api.find_task(夹具号)
    ck("`api.find_task` 找得到一条非待处理的任务", bool(找到),
       f"找不到 —— 要么 `find_task` 又绑回了某个状态(页面表现是"
       f"「列表里明明有,点下去说任务不存在」),要么夹具没生效、其实读的是真库")
    # ② 反向对照 —— 少了它,万一两种写法都找得到,①的绿就是空转来的
    旧法 = [x for x in api.list_tasks(None, api.TASK_STATES[0]) if x["id"] == 夹具号]
    ck(f"绑「{api.TASK_STATES[0]}」的旧写法**找不到**它(反向对照)", not 旧法,
       "两种写法都找得到 —— 那第①条就没在验任何东西,**它的绿是空转来的**")
finally:
    api.DB = 真DB
    shutil.rmtree(副目, ignore_errors=True)

# ── 不许再手写那个形状(棘轮:现在 0 处,只许少不许多) ────────────────────
# ⚠️ 这一关盯的是**绕过 `find_task` 重新手写一份**。
# 它查结构不查词:`list_tasks(...)` 的结果后面紧跟着按 `["id"]==` 筛 ——
# 那就是「按 id 找一条」,而这件事只许有一份实现。
手写 = []
for 文件 in ("server.py", "selftest.py", "api.py", "../agent/v1.py", "../agent/eval.py"):
    路 = os.path.join(这里, 文件)
    if not os.path.exists(路):
        continue
    文本 = open(路, encoding="utf-8").read()
    for m in re.finditer(r'list_tasks\([^)]*\)[^\n]*?\["id"\]\s*==', 文本):
        行号 = 文本[:m.start()].count("\n") + 1
        if os.path.normpath(文件) == "api.py" and "def find_task" in 文本[:m.start()][-600:]:
            continue        # `find_task` 自己就是那一份,不算手写
        手写.append(f"{os.path.normpath(文件)}:{行号}")
ck(f"没有人绕过 `find_task` 重新手写(扫了 5 个文件)", not 手写,
   f"{手写} 又手写了一份「按 id 找一条」—— **两份本该一致的东西之间没有东西盯着**,"
   f"改用 `api.find_task()`")

# ── 取样那两处:下标不许越界 ────────────────────────────────────────
取样 = (api.list_tasks("财务人工任务", api.看全部任务)
        + api.list_tasks("客户合并确认", api.看全部任务))
ck(f"v1 取样够 subset 那八个下标用(要 ≥33,拿到 {len(取样)})", len(取样) >= 33,
   f"只拿到 {len(取样)} 条,而 `v1.py` 的 subset 取 [0,4,8,12,16,20,24,32] —— "
   f"**当场 IndexError**,而报出来的理由和工具层没有半点关系")

# ── enum 对账:库里出现的取值,常量里必须都有 ──────────────────────────
cx = sqlite3.connect(f"file:{库}?mode=ro", uri=True)
库状态 = {r[0] for r in cx.execute("SELECT DISTINCT status FROM task") if r[0]}
库类型 = {r[0] for r in cx.execute("SELECT DISTINCT type FROM task") if r[0]}
各状态 = dict(cx.execute("SELECT status, count(*) FROM task GROUP BY status"))
cx.close()

ck(f"库里出现的状态常量里都有(扫到 {len(库状态)} 种)", not (库状态 - set(api.TASK_STATES)),
   f"库里有 {sorted(库状态 - set(api.TASK_STATES))} 而 `api.TASK_STATES` 没登记 —— "
   f"**schema 的 enum 是从这个常量现拼的,漏一种模型就填不出来**")
ck(f"库里出现的类型常量里都有(扫到 {len(库类型)} 种)", not (库类型 - set(api.TASK_TYPES)),
   f"库里有 {sorted(库类型 - set(api.TASK_TYPES))} 而 `api.TASK_TYPES` 没登记 —— "
   f"这正是原来那次:描述手抄两种、库里实际四种,**模型照描述以为只有两种**")

# 反方向**只打印**:枚举里有而库里没样本,是库况不是错(那一档的写口和判据都验不到)
没样本 = [x for x in api.TASK_STATES if x not in 库状态]
if 没样本:
    库况("枚举里这几档这个库上没有样本", f"{没样本} —— **那几档的写口和判据都验不到**,不是错")

库况("各状态条数", f"{各状态};默认值「{api.TASK_STATES[0]}」占 "
     f"{各状态.get(api.TASK_STATES[0], 0)}/{sum(各状态.values())} 条")

print()
print(f"📌 **真调 `api.find_task`**,在一条真库里不存在的夹具任务上验 —— "
      f"所以它验的是那段代码,不是我重写的一份,也不是"
      f"「这个库里碰巧有没有非{api.TASK_STATES[0]}的任务」。")
print()
if bad:
    print(f"{R}❌ {len(bad)}/{n} 条没过:{bad}{D}")
    raise SystemExit(1)
print(f"{G}✅ 按 id 找任务没绑在状态上(验了 {n} 条,副本上自造了 1 条夹具任务){D}")
