#!/usr/bin/env python3
"""库结构迁移 —— 加列 / 改列从此按编号走一处,库自己记着做到第几条。

## 为什么(用户 11-14 列进 12 小时清单第 ④ 条)

建表早就集中了(`tools/ensure_tables.py` + `table_origin_check`),**加列没有**:
约 25 处「PRAGMA 看有没有 → 没有就 ALTER TABLE」散在 20 个模块,多数在**第一次调用时**才跑。
> 「这一列还没加」和「这条路还没人走过」在库上长得一模一样 —— 直到有人走那条路,写入撞 no such column。

两个检出共用一个库、服务跑主检出的代码:代码先到、列没到,是这个项目反复栽的形状
(记忆「未提交代码会被别人重启上线」「建新表要连代码一起推」)。

## 做法

- `backend/migrations/mNNNN_名字.py`,每个一个 `up(c)`,**必须幂等**(PRAGMA 判断,老库跑一遍不出错)。
- `schema_version` 表记「做过哪几条 + 当时文件的内容指纹」。编号必须从 1 连续,不许跳号、不许重号。
- **已经做过的迁移文件不许再改**:改了的话老库不会重跑它,新库会跑改过的版本 —— 两个库悄悄分叉。
  指纹对不上就报出来,要改结构请新加一条。
- 每条迁移一个事务(显式 BEGIN):`up` 中途抛异常就整条回滚,版本表不记。

    python3 backend/migrate.py            # 补齐缺的迁移(重建流水线在 ensure_tables 之后调)
    python3 backend/migrate.py --看       # 只列:做到第几条、还差哪几条、有没有被改过的
    python3 backend/migrate.py --自测     # 临时库上验:补齐 / 幂等 / 缺表不崩 / 改过能认出 / 跳号能认出

⚠️ 第一步只收了 7 个**纯加列**的函数(见 m0001)。建表顺带加列的(各模块的 `建表(c)`)和
重建流水线里的一次性脚本还在原处 —— `tools/migration_check.py` 把它们登记成欠债,只许少不许多。
"""
import datetime as _dt
import hashlib
import importlib.util
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
目录 = os.path.join(HERE, "migrations")
DB = os.path.join(HERE, "lanxiu.db")
名式 = re.compile(r"^m(\d{4})_(.+)\.py$")

DDL = """CREATE TABLE IF NOT EXISTS schema_version(
    ver INTEGER PRIMARY KEY,      -- 迁移编号(文件名里的 NNNN)
    name TEXT NOT NULL,           -- 文件名里编号后面那段
    fp TEXT NOT NULL,             -- 做的时候那份文件的内容指纹(sha256 前 16 位)
    applied_at TEXT NOT NULL      -- 机器的真实时间(不是世界的钟:这是「库什么时候被改了结构」,不随造数平移)
)"""


def _指纹(路径):
    return hashlib.sha256(open(路径, "rb").read()).hexdigest()[:16]


def 迁移们(目录=目录):
    """[(编号, 名字, 路径, 指纹)],按编号排。跳号 / 重号直接抛 —— 那不是能「先跑着」的状态。"""
    有 = []
    for f in sorted(os.listdir(目录)) if os.path.isdir(目录) else []:
        m = 名式.match(f)
        if m:
            p = os.path.join(目录, f)
            有.append((int(m.group(1)), m.group(2), p, _指纹(p)))
    有.sort()
    号 = [x[0] for x in 有]
    if 号 != list(range(1, len(号) + 1)):
        raise SystemExit(f"❌ 迁移编号必须从 1 连续、不重号:现在是 {号}(目录 {目录})")
    return 有


def 建表(c):
    c.execute(DDL)


def 已做(c):
    建表(c)
    return {r[0]: (r[1], r[2]) for r in c.execute("SELECT ver, name, fp FROM schema_version")}


def 对账(c, 目录=目录):
    """(还差的, 被改过的):还差 = 文件有、库没记;被改过 = 库记的指纹和现在文件的不一样。"""
    做过 = 已做(c)
    全 = 迁移们(目录)
    差 = [x for x in 全 if x[0] not in 做过]
    改 = [(x[0], x[1]) for x in 全 if x[0] in 做过 and 做过[x[0]][1] != x[3]]
    return 差, 改


def _载(路径):
    spec = importlib.util.spec_from_file_location("迁移_" + os.path.basename(路径)[:-3], 路径)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not callable(getattr(m, "up", None)):
        raise SystemExit(f"❌ {路径} 没有 up(c)")
    return m


def 补齐(c, 目录=目录, 说=print):
    """按编号补跑还差的迁移,返回这次做了几条。每条一个事务。"""
    差, 改 = 对账(c, 目录)
    for ver, name in 改:
        说(f"  ⚠️ 第 {ver} 条({name})做过之后文件被改了 —— 老库不会重跑它,新库会跑改过的版本。要改结构请新加一条")
    c.commit()                      # 进事务之前把建版本表那一步落掉
    for ver, name, 路径, fp in 差:
        m = _载(路径)
        c.execute("BEGIN")
        try:
            m.up(c)
            c.execute("INSERT INTO schema_version(ver, name, fp, applied_at) VALUES (?,?,?,?)",
                      (ver, name, fp, _dt.datetime.now().isoformat(timespec="seconds")))  # 真实时钟:记库结构什么时候被改,运维痕迹,不随世界平移(同 op_log.ts)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        说(f"  ✅ 做了第 {ver} 条:{name}")
    return len(差)


def _自测():
    """临时库 + 临时迁移目录,不碰真库。"""
    坏 = 0
    def ck(ok, 话):
        nonlocal 坏
        print(f"  {'✅' if ok else '❌'} {话}")
        坏 += 0 if ok else 1
    d = tempfile.mkdtemp(prefix="migrate-自测-")
    库 = os.path.join(d, "t.db")
    c = sqlite3.connect(库)
    # 只有主键的空壳表:m0001 要补的列一个都没有;rating 故意不建 —— 缺表要跳过,不许崩
    for t in ("customer", "task", "triage", "call_audio", "call_transcript"):
        c.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY)")
    c.commit()
    n = 补齐(c, 说=lambda *_: None)
    ck(n == len(迁移们()), f"新库补齐:做了 {n} 条 = 目录里的条数 {len(迁移们())}")
    列 = lambda t: {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
    ck({"merged_into"} <= 列("customer") and {"waiting"} <= 列("task")
       and {"receipt", "reopen_count", "relabel_review"} <= 列("triage")
       and {"then_flow", "channel"} <= 列("call_audio") and {"raw_text", "speaker_src"} <= 列("call_transcript"),
       "m0001 的列真的加上了(customer / task / triage / call_audio / call_transcript 各抽查)")
    ck("rating" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}, "缺的表(rating)跳过、没被顺手建出来")
    ck(补齐(c, 说=lambda *_: None) == 0, "再跑一遍:0 条(幂等,版本表记住了)")
    # 失败整条回滚:造一条会抛异常的迁移,版本表不许记它、它加的列不许留下
    d2 = tempfile.mkdtemp(prefix="migrate-坏-")
    for ver, name, p, _ in 迁移们():
        open(os.path.join(d2, os.path.basename(p)), "wb").write(open(p, "rb").read())
    下一号 = len(迁移们()) + 1
    open(os.path.join(d2, f"m{下一号:04d}_会崩.py"), "w").write(
        "def up(c):\n    c.execute('ALTER TABLE customer ADD COLUMN 半截 TEXT')\n    raise RuntimeError('故意')\n")
    try:
        补齐(c, 目录=d2, 说=lambda *_: None); ck(False, "中途抛异常的迁移应该抛出来")
    except RuntimeError:
        ck("半截" not in 列("customer") and 下一号 not in 已做(c), "中途抛异常:整条回滚(列没留下、版本表没记)")
    # 改过能认出
    open(os.path.join(d2, f"m{下一号:04d}_会崩.py"), "w").write("def up(c):\n    pass\n")
    c.execute("UPDATE schema_version SET fp='0000000000000000' WHERE ver=1"); c.commit()
    _, 改 = 对账(c, d2)
    ck([v for v, _ in 改] == [1], "做过之后文件被改了能认出来(第 1 条指纹对不上)")
    # 跳号能认出
    os.rename(os.path.join(d2, f"m{下一号:04d}_会崩.py"), os.path.join(d2, f"m{下一号 + 1:04d}_跳号.py"))
    try:
        迁移们(d2); ck(False, "跳号应该被拒")
    except SystemExit:
        ck(True, "编号跳号被拒(不许「先跑着」)")
    c.close()
    print("✅ 迁移机制自测全过" if not 坏 else f"❌ 迁移机制自测 {坏} 条不过")
    return 0 if not 坏 else 1


def main():
    a = sys.argv[1:]
    if "--自测" in a:
        sys.exit(_自测())
    c = sqlite3.connect(DB)
    if "--看" in a:
        差, 改 = 对账(c)
        做过 = 已做(c)
        print(f"  库 {DB}:做过 {len(做过)} 条(到第 {max(做过) if 做过 else 0} 条),目录里 {len(迁移们())} 条")
        print(f"  还差:{[f'{v}:{n}' for v, n, *_ in 差] or '无'}")
        print(f"  被改过:{[f'{v}:{n}' for v, n in 改] or '无'}")
        sys.exit(1 if 改 else 0)
    n = 补齐(c)
    print(f"  迁移:这次做了 {n} 条,库现在做到第 {max(已做(c)) if 已做(c) else 0} 条")
    c.close()


if __name__ == "__main__":
    main()
