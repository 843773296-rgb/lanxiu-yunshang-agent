#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保留期 · 检查 —— **验「清理真的删得掉」,不是验「库里现在干净」**。

用户 2026-10-27 拍:操作日志 3 年 / 附件 1 年。

## 为什么不能只扫真库

演示库的 `op_log` **只有当天的数据**(每次重建都从头造),所以扫真库永远是「超期 0 条」。

> 一个「清理在工作」和一个「还没有东西需要清」,**在那条绿色上长得一模一样。**

这正是项目那条「**『没东西可验』必须和『验过了』分开**」。所以这里**造夹具**:
在库副本上塞几条确凿超期的台账,跑清理,验它们真的消失了、而没超期的一条都没少。

## 跑在副本上

用 `sqlite3.backup()` 做副本(`lanxiu.db` 是软链,不能 cp),清理只对副本执行。
**真库一个字节都不动** —— 这条检查自己就是「删数据」那一类,更不能碰真库。
"""
import io, os, sqlite3, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
真DB = os.path.join(HERE, "lanxiu.db")
# 咬合 —— 改坏的是什么、该红的是哪一条。
# (可执行的在 `tools/bite_specs.json`:
#  `python3 tools/bite_run.py --only "backend/retention_check.py"`)
咬合 = [
    ("把 purge_expired 的 `--执行` 判断去掉(默认就删)", "默认只报告 → **一条都没删**"),
    ("把删除条件从 `< 界` 改成 `<= 今天`(把没超期的也删了)", "**没超期的一条都没少**"),
    ("让 purge_expired 读不到 world_today 时退回真实时钟", "不拿真实时钟顶替"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0


def ck(名, 得, 应):
    global n
    n += 1
    ok = (得 == 应)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  得到={得!r} 应={应!r}"))
    if not ok:
        坏.append(名)


if not os.path.exists(真DB):
    print("ℹ️ 库不在 —— **这一轮没验**(不是验过了)")
    sys.exit(0)

副本 = os.path.join(tempfile.mkdtemp(), "lanxiu.db")
_s, _d = sqlite3.connect(f"file:{真DB}?mode=ro", uri=True), sqlite3.connect(副本)
with _d:
    _s.backup(_d)
_s.close(); _d.close()
assert 副本 != 真DB

print("保留期 · 检查(在库副本上)")

c = sqlite3.connect(副本)
今天 = c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()[0]
年 = int(今天[:4])
# 夹具:3 条确凿超期(4 年前)+ 1 条确凿没超期(今天)
超期们 = [f"{年-4}-01-0{i} 10:00:00" for i in (1, 2, 3)]
不超期 = f"{今天} 10:00:00"
cols = [d[1] for d in c.execute("PRAGMA table_info(op_log)")]
可空 = [x for x in cols if x not in ("id",)]
for ts in 超期们 + [不超期]:
    c.execute(f"INSERT INTO op_log ({','.join(可空)}) VALUES ({','.join('?' * len(可空))})",
              [ts if x == "ts" else ("保留期夹具" if x == "actor" else None) for x in 可空])
c.commit()
前_超期 = c.execute("SELECT COUNT(*) FROM op_log WHERE ts < ?", (f"{年-3}{今天[4:]}",)).fetchone()[0]
前_总 = c.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
c.close()
ck("夹具塞进去了(副本里有 3 条确凿超期的)", 前_超期, 3)

# ── 只报告模式:一条都不许删 ───────────────────────────────────────
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "purge_expired.py"), "--db", 副本],
                   capture_output=True, text=True)
c = sqlite3.connect(副本)
中_总 = c.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
c.close()
ck("默认只报告 → **一条都没删**(删不可逆,默认不删)", 中_总, 前_总)
ck("只报告时退出码 0", r.returncode, 0)
ck("只报告时说清了「没删」", "没删" in r.stdout, True)
ck("报出了超期条数(不是只说「跑完了」)", "超期 3 条" in r.stdout, True)

# ── 执行模式:超期的删掉,没超期的一条不少 ─────────────────────────
r2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "purge_expired.py"),
                     "--db", 副本, "--执行"], capture_output=True, text=True)
c = sqlite3.connect(副本)
后_超期 = c.execute("SELECT COUNT(*) FROM op_log WHERE ts < ?", (f"{年-3}{今天[4:]}",)).fetchone()[0]
后_总 = c.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
后_那条 = c.execute("SELECT COUNT(*) FROM op_log WHERE ts=?", (不超期,)).fetchone()[0]
c.close()
ck("`--执行` → 超期的真删掉了", 后_超期, 0)
ck("**没超期的一条都没少**(删多了比不删更糟)", 后_总, 前_总 - 3)
ck("那条今天的记录还在", 后_那条 >= 1, True)
ck("执行时退出码 0", r2.returncode, 0)

# ── 读不到演示世界的今天 → 必须抛,不许退回真实时钟 ───────────────
# ⚠️ 这一条是为了让那条分支**走得到**才加的:咬合攻击「退回真实时钟」时,
# 正常库里 world_today 好好地在,那个 raise 根本不执行 ——
# **而攻一条走不到的分支,结果和「检查看不见」长得一模一样**(今晚栽了三次)。
副本2 = os.path.join(tempfile.mkdtemp(), "lanxiu.db")
_s2, _d2 = sqlite3.connect(f"file:{副本}?mode=ro", uri=True), sqlite3.connect(副本2)
with _d2:
    _s2.backup(_d2)
_s2.close(); _d2.close()
c = sqlite3.connect(副本2)
c.execute("DELETE FROM world_meta WHERE k='world_today'")
c.commit(); c.close()
r3 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "purge_expired.py"), "--db", 副本2],
                    capture_output=True, text=True)
ck("读不到演示世界的今天 → **退出码非 0**(不拿真实时钟顶替)", r3.returncode != 0, True)
ck("而且说清了为什么(台账的时间戳是演示世界的)",
   "不拿真实时钟顶替" in (r3.stdout + r3.stderr), True)

# ── 真库一个字节都没动 ────────────────────────────────────────────
c = sqlite3.connect(f"file:{真DB}?mode=ro", uri=True)
真_夹具 = c.execute("SELECT COUNT(*) FROM op_log WHERE actor='保留期夹具'").fetchone()[0]
c.close()
ck("**真库里没有夹具的痕迹**(这条检查自己是「删数据」那一类,更不能碰真库)", 真_夹具, 0)

print(f"  (验了 {n} 条)")
if n == 0:
    print(f"{R}❌ 一条都没验{D}"); sys.exit(1)
if 坏:
    print(f"{R}❌ 保留期 {len(坏)} 条不过{D}"); sys.exit(1)
print(f"{G}✅ 保留期:默认不删 / `--执行` 删超期的 / 没超期的一条不少 / 真库没碰"
      f"(**造夹具验的,不是靠「库里现在干净」**){D}")
