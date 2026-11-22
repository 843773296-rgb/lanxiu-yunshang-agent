#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测切库副本 · 懒加载的写口也得落在副本上(2026-11-19 夜跑查出)。

## 为什么要这一条

写库评测跑在库副本上:启动方给工具服务子进程 LANXIU_DB=副本,`mcp/protocol.指到副本()` 把已加载模块里
指着真库的 `DB` 改到副本。但**工具函数体里懒加载的写口**(`api_order.open_order` 里 `import order_write`)
在第一次调用时才进 sys.modules —— 扫描在工具执行**之前**跑,扫不到它,于是第一次开单写进了**真库**。
拆 api.py(11-16)把这类 import 挪进函数体之后,下单评测连 4 晚「没开出单」(判分读副本、单落真库),
真库里多出十几张评测单。

> 一个「模型没开单」和一个「单开到真库里去了」,在「库:没开出单」那一行上长得一模一样。

## 怎么判(真调 protocol.指到副本,子进程里做,不碰真库的数据)

  ① 给了 LANXIU_DB:指到副本() 之后**才** import、而且**还自己拼真库路径**的模块,拿它自己的 DB 路径去连 —— 连到的是副本
     ⚠️ 11-22 起 order_write 等写口改走 dbpath.路径()(W02 第③步),import 时自己就落在副本上,
     **再拿它当样本就验不到「连库改道」这一层了**(那次 ship 红在这里的前提上)。
     还没改走单源的模块仍有一百多个,所以改成子进程里现造一个「替身」模块:DB 写死真库路径、扫描之后才 import ——
     它就是那一类模块的原样。order_write 另验一条:它经单源直接落在副本上。
  ② file: URI 写法(只读打开 mode=ro)也改道
  ③ 没给 LANXIU_DB:照旧连真库(只读 pragma 看一眼路径,不写)

只读:真库只做 `PRAGMA database_list`,副本是临时空库。
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.pop("LANXIU_DB", None)          # 先摘掉,下面取的才是真库路径(dbpath 认 LANXIU_DB 优先)
from dbpath import 路径 as _库路径
真库 = os.path.realpath(_库路径())

# 咬合 —— 改坏的是什么、该红的是哪一条(可执行规格在 tools/bite_specs.json)
咬合 = [
    ("指到副本() 里不装连库改道(删掉 `_sq.connect = _连`)", "指到副本之后才 import、还自己拼真库路径的写口(替身)连到的是副本"),
]

FAIL = []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:200]) if (补 and not 真) else ''}")
    if not 真:
        FAIL.append(名)


子 = r'''
import os, sys, sqlite3, json
ROOT = sys.argv[1]
sys.path[:0] = [os.path.join(ROOT, "mcp"), os.path.join(ROOT, "backend")]
import protocol, tempfile
protocol.指到副本()
# 替身:还自己拼真库路径的懒加载写口(扫描之后才进来)—— 现造在临时目录里,不碰仓库
_替 = tempfile.mkdtemp(prefix="lazy-standin-")
with open(os.path.join(_替, "lazy_standin_mod.py"), "w", encoding="utf-8") as f:
    f.write("DB = " + repr(sys.argv[2]) + "\n")
sys.path.insert(0, _替)
import lazy_standin_mod
import order_write                       # 懒加载:扫描之后才进来(11-22 起经 dbpath 单源取路径)
def 连到(db):
    with sqlite3.connect(db) as c:
        return [r[2] for r in c.execute("PRAGMA database_list")][0]
out = {"替身.DB": os.path.realpath(lazy_standin_mod.DB), "直连": os.path.realpath(连到(lazy_standin_mod.DB)),
       "order_write直连": os.path.realpath(连到(order_write.DB))}
真 = os.path.realpath(lazy_standin_mod.DB)
out["uri"] = os.path.realpath(连到_uri := (lambda: [r[2] for r in sqlite3.connect("file:" + 真 + "?mode=ro", uri=True).execute("PRAGMA database_list")][0])())
print(json.dumps(out, ensure_ascii=False))
'''


def 跑(env_extra):
    env = {k: v for k, v in os.environ.items() if k != "LANXIU_DB"}
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", 子, ROOT, 真库], capture_output=True, text=True, env=env, timeout=60)
    if r.returncode:
        return None, r.stderr[-400:]
    import json
    return json.loads(r.stdout.strip().splitlines()[-1]), ""


def main():
    print("评测切库副本 · 懒加载的写口也落在副本上")
    if not os.path.exists(真库):
        print("  ℹ️ 这个检出没有 backend/lanxiu.db(CI 新库前)—— **没东西可验,不是通过**")
        return 0
    d = tempfile.mkdtemp(prefix="lazy-copy-")
    副 = os.path.join(d, "副本.db")
    import sqlite3
    sqlite3.connect(副).close()
    副 = os.path.realpath(副)

    有, 错 = 跑({"LANXIU_DB": 副})
    ck("子进程跑得起来(给了 LANXIU_DB)", 有 is not None, 错)
    if 有:
        ck("前提成立:替身自己的 DB 变量还指着真库(扫描时它还没加载)", 有["替身.DB"] == 真库, 有)
        ck("指到副本之后才 import、还自己拼真库路径的写口(替身)连到的是副本", 有["直连"] == 副, 有)
        ck("order_write(经 dbpath 单源)连到的也是副本", 有["order_write直连"] == 副, 有)
        ck("file: URI(只读打开)也改道到副本", 有["uri"] == 副, 有)

    没, 错 = 跑({})
    ck("子进程跑得起来(没给 LANXIU_DB)", 没 is not None, 错)
    if 没:
        # 门禁里 sitecustomize 会把真库改道到门禁自己的副本(tools/gate_db),所以这里不要求「连到真库」,
        # 只要求**没被这一层改到评测副本上**(11-19 第一次挂门禁时这样红过)
        ck("没给 LANXIU_DB 时照旧连真库(不改道)", 没["直连"] != 副 and 没["uri"] != 副
           and (没["直连"] == 真库 or "lanxiu-gate-db" in 没["直连"]), 没)

    print("=" * 80)
    if FAIL:
        print(f"\033[31m❌ 懒加载写口切副本 {len(FAIL)} 条不过\033[0m")
        return 1
    print("\033[32m✅ 懒加载的写口也落在副本上;没给副本时照旧连真库\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
