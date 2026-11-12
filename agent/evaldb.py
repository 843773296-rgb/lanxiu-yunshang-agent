"""写库评测在库副本上跑(2026-11-12,执行手册 W09)。

原来 12 套评测在共享真库上开单 / 写排班 / 报工,每题「拍一份 → 跑 → 还原」,只有两套核过还原干净了没有
(体检 C 报告 §4)。真库是生产库,评测写进去、还原漏了,下一题或并行会话就读到脏数据。

做法:评测开跑前调一次 `用副本()` ——
  ① `backend/check_copy.用副本()`:拷一份、把**已经 import 的**模块变量和函数默认参数都改指副本、断言连接落在副本上;
  ② 再把副本路径放进环境变量 `LANXIU_DB` —— 评测经 `agentsite/sdk.py` 拉起的 MCP 工具服务是**另外的进程**,
     sdk 见到这个变量会原样传下去(sdk.py「显式带上 LANXIU_DB」那段),子进程里 `mcp/protocol.py` 再把各模块改指副本。
  两步缺一步,模型调的写工具就还写真库,而**评测进程自己看着一切正常**。

⚠️ 调用顺序:**先 import 被测的写口模块,再调这里**(check_copy 只改已加载的模块;记忆「检查切库前先 import 写口」)。
每题之间的「拍 / 还原」照旧保留 —— 题和题之间仍然共用这一份副本。

    python3 agent/evaldb.py --自测
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "backend"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def 用副本(前缀="eval-", 先导入=()):
    """→ 副本路径。进程退出时 check_copy 会删掉它。
    先导入:评测里**在函数里懒加载**的写口模块名 —— 不先加载,check_copy 改不到它,它照样写真库。"""
    import importlib
    for 名 in 先导入:
        importlib.import_module(名)
    import check_copy
    真 = os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db"))
    副本 = check_copy.用副本(前缀=前缀)
    os.environ["LANXIU_DB"] = 副本
    # ⚠️ check_copy 只认叫 DB / DB_PATH 的模块变量,而评测自己读库用的变量叫 DBP(10 套都是)——
    # 11-13 夜跑:排班评测的写口和工具服务都切到了副本,**判分还读真库**,8 道挂 5 道「草稿期望 35 实际 0」,
    # 被判成「退步」。所以这里**不看变量名**:本项目里还指着真库的模块级路径,一律改指副本(含 __main__)
    补 = []
    for m in check_copy._本项目的模块():
        for 名, 值 in list(vars(m).items()):
            if not 名.startswith("__") and check_copy._是这个库(值, 真):
                setattr(m, 名, 副本)
                补.append(f"{getattr(m, '__name__', '?')}.{名}")
    print(f"  🗄  评测跑在库副本上:{副本}(真库不碰;工具服务子进程经 LANXIU_DB 跟着切)"
          + (f";另改指 {len(补)} 处别名变量:{'、'.join(补[:6])}" if 补 else ""))
    return 副本


咬合 = [("用副本() 不设 LANXIU_DB(工具服务子进程照旧写真库)", "工具服务子进程拿得到副本路径(LANXIU_DB)"),
        ("用副本() 只切 DB / DB_PATH,不管别的名字(评测的 DBP 照旧读真库)", "评测自己读库的变量(叫 DBP,不叫 DB)也指副本")]


def _自测():
    import sqlite3
    from contextlib import closing
    坏 = []

    def ck(名, 真, 补=""):
        print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 and not 真 else ''}")
        if not 真:
            坏.append(名)

    import api  # noqa: F401  先 import 写口 / 取数模块,再切(顺序见文件头)
    import roster_write  # noqa: F401
    真 = os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db"))
    os.environ.pop("LANXIU_DB", None)
    # 照评测的样子造一个模块:读库变量叫 DBP(11-13 夜跑栽在这里:check_copy 只认 DB / DB_PATH)
    import types
    假评测 = types.ModuleType("evaldb_假评测"); 假评测.__file__ = os.path.join(HERE, "evaldb_假评测.py")
    假评测.DBP = os.path.join(ROOT, "backend", "lanxiu.db")
    sys.modules["evaldb_假评测"] = 假评测
    副本 = 用副本("evaldb-selftest-")
    ck("评测自己读库的变量(叫 DBP,不叫 DB)也指副本", os.path.realpath(假评测.DBP) == os.path.realpath(副本), 假评测.DBP)
    ck("工具服务子进程拿得到副本路径(LANXIU_DB)", os.environ.get("LANXIU_DB") == 副本, os.environ.get("LANXIU_DB"))
    import api as _a
    with closing(_a._c()) as c:
        落 = c.execute("pragma database_list").fetchone()[2]
    ck("本进程取数口 api._c() 连的是副本", os.path.realpath(落) == os.path.realpath(副本), 落)
    ck("副本不是真库那个文件", os.path.realpath(副本) != 真, 副本)
    import roster_write as _rw
    ck("写口模块的库路径也指副本", os.path.realpath(getattr(_rw, "DB", 副本)) == os.path.realpath(副本), getattr(_rw, "DB", None))
    # 子进程这一跳:照 sdk 的做法把 env 传下去,子进程里 mcp/protocol 的切库函数应当真改到副本
    import subprocess
    r = subprocess.run([sys.executable, "-c",
                        "import sys,os;sys.path[:0]=['mcp','backend'];import api,protocol;"
                        "n=protocol.指到副本();"
                        "import sqlite3;c=api._c();print(c.execute('pragma database_list').fetchone()[2])"],
                       cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=60)
    子落 = (r.stdout.strip().splitlines() or ["?"])[-1]
    ck("子进程(照 sdk 传 env)里 api._c() 也连副本", os.path.realpath(子落) == os.path.realpath(副本), (子落, r.stderr[-160:]))
    print("✅ evaldb 自测全过" if not 坏 else f"❌ {len(坏)} 条不过")
    return 1 if 坏 else 0


if __name__ == "__main__":
    if "--自测" in sys.argv:
        sys.exit(_自测())
    print(__doc__)
