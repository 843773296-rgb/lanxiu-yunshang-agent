"""门禁库重定向真的生效了吗(2026-11-12,执行手册 W02)。

门禁开头拷一份真库,`tools/gate_db/sitecustomize.py` 把门禁里所有连真库的 `sqlite3.connect` 改连到副本。
这条检查验的不是「代码写了」,是**连接真落在哪个文件**(`PRAGMA database_list`):

  ① 自己拷一份副本、自己起子进程(系统 Python + agentsite 的 venv 各一个)——
     连真库路径 / 连只读 URI / 经业务模块 `api._c()` 连,**全都落在副本上**;
  ② 在子进程里往「真库路径」写一行 → 那一行在副本里,**真库里没有**(写了才算数,不能只看路径);
  ③ 不给变量时一个字节都不动(服务进程不在门禁里,不能被影响);
  ④ 在门禁里跑时(有 LANXIU_GATE_DB),本进程自己也挂上了,而且副本不是真库那个文件。

①–③ 自己造环境,所以单独跑、咬合重放都能验;④ 只在门禁里有意义,不在门禁里明说「不适用」。
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
真 = os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db"))
钩子目录 = os.path.join(ROOT, "tools", "gate_db")
VENV = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")

咬合 = [
    ("重定向不换普通路径(连真库路径照旧连真库)", "门禁里连真库的路径落在副本上"),
    ("重定向不换 file: URI(只读打开照旧连真库)", "只读 URI 也落在副本上"),
]

坏 = []


def ck(名, 真假, 补=""):
    print(f"  {'✅' if 真假 else '❌'} {名}{('  ' + str(补)[:200]) if 补 and not 真假 else ''}")
    if not 真假:
        坏.append(名)


探针 = r"""
import sqlite3, sys, json
sys.path.insert(0, 'backend')
out = {}
def 落在(c): return c.execute('pragma database_list').fetchone()[2]
with sqlite3.connect('backend/lanxiu.db') as c: out['普通'] = 落在(c)
c = sqlite3.connect('file:backend/lanxiu.db?mode=ro', uri=True); out['URI'] = 落在(c); c.close()
try:
    import api; c = api._c(); out['api'] = 落在(c); c.close()
except Exception as e:
    out['api'] = '崩了:' + str(e)[:80]
if len(sys.argv) > 1:
    c = sqlite3.connect('backend/lanxiu.db'); c.execute('create table if not exists _gate_probe(x)'); c.execute("insert into _gate_probe values('门禁探针')"); c.commit(); c.close()
print(json.dumps(out, ensure_ascii=False))
"""


def 跑(py, env, 写=False):
    r = subprocess.run([py, "-c", 探针] + (["写"] if 写 else []), cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    import json
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"崩了": (r.stderr or r.stdout)[-200:]}


def main():
    print("\n\033[1m▸ 门禁库重定向 · 连真库的一律落在副本上(看连接真落在哪,不看代码写了什么)\033[0m")
    if not os.path.exists(真):
        print(f"  ❌ 真库 {真} 不在 —— 这不叫通过")
        return 1
    with tempfile.TemporaryDirectory(prefix="gatedb-") as 临:
        副 = os.path.join(临, "copy.db")
        with closing(sqlite3.connect(f"file:{真}?mode=ro", uri=True)) as 源, closing(sqlite3.connect(副)) as 目:
            源.backup(目)
        副 = os.path.realpath(副)
        环境 = dict(os.environ, LANXIU_GATE_DB=副, LANXIU_REAL_DB=真,
                  PYTHONPATH=钩子目录 + os.pathsep + os.environ.get("PYTHONPATH", ""))
        环境.pop("LANXIU_DB", None)
        解释器们 = [("系统 Python", sys.executable)] + ([("agentsite venv", VENV)] if os.path.exists(VENV) else [])
        for 名, py in 解释器们:
            o = 跑(py, 环境)
            ck(f"{名}:门禁里连真库的路径落在副本上", os.path.realpath(o.get("普通", "")) == 副, o)
            ck(f"{名}:只读 URI 也落在副本上", os.path.realpath(o.get("URI", "")) == 副, o)
            ck(f"{名}:经业务模块 api._c() 连也落在副本上", os.path.realpath(o.get("api", "")) == 副, o)
        跑(sys.executable, 环境, 写=True)
        with closing(sqlite3.connect(副)) as c:
            副里 = c.execute("select count(*) from sqlite_master where name='_gate_probe'").fetchone()[0]
        with closing(sqlite3.connect(f"file:{真}?mode=ro", uri=True)) as c:
            真里 = c.execute("select count(*) from sqlite_master where name='_gate_probe'").fetchone()[0]
        ck("往「真库路径」写的那一行在副本里", 副里 == 1, 副里)
        ck("真库里没有那一行(写了才算数)", 真里 == 0, 真里)
        干净 = {k: v for k, v in 环境.items() if k not in ("LANXIU_GATE_DB", "LANXIU_REAL_DB")}
        o = 跑(sys.executable, 干净)
        ck("不给变量时一个字节都不动", os.path.realpath(o.get("普通", "")) == 真, o)

    门禁副本 = os.environ.get("LANXIU_GATE_DB")
    if 门禁副本:
        ck("④ 门禁里:本进程的 sqlite3.connect 挂上了重定向", getattr(sqlite3.connect, "_门禁重定向", False))
        ck("④ 门禁里:副本不是真库那个文件", os.path.realpath(门禁副本) != 真, 门禁副本)
    else:
        print("  ℹ️ ④ 不在门禁里跑(没有 LANXIU_GATE_DB)—— 这一项**不适用,不是通过**")
    print(f"\n{'❌ ' + str(len(坏)) + ' 条不过:' + '、'.join(坏) if 坏 else '✅ 门禁库重定向生效'}")
    return 1 if 坏 else 0


if __name__ == "__main__":
    sys.exit(main())
