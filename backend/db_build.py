"""这个库是谁、用哪一版造数逻辑建出来的 —— 记在库自己身上(world_meta),任何读库的人都查得到。

为什么(10-26 并行会话提的,两边商定):评测基线的「来路」记了供应商 / 模型 / 时间 / 代码 sha,**没记库**。
那天合并题改按账户、新增 IT- 测试客户之后,
> 一份「同样条件下跑出来的」基线,和一份「库已经换了内容」的基线,在「来路」上长得一模一样。
新代码 + 旧库跑出的成绩单也一样看不出来。记在评测结果里只有写结果的那个脚本知道;记在库里,
夜跑、门禁、合并评测、技能触发评测都能读。

字段(world_meta 的键,**名字只在这里定一次**,读的人用 读() 取,别手抄键名):
  build_commit     重建时的提交号(工作区有没提交的造数改动时带 +dirty)
  build_at         重建完成时刻
  build_logic_fp   造数逻辑的内容指纹:rebuild.sh 步骤清单里的每个脚本 + knowledge/ 下的 .py / .md,按内容算
  build_logic_n    算进指纹的文件数(0 说明没找到文件 —— 那不是指纹,是空集合)

**造数逻辑不变,指纹就不变**:每日平移、评测运行时写进库的行都不影响它 —— 比「关键表行数」稳。

    python3 backend/db_build.py --盖章    # rebuild.sh 最后调;单独跑就是给当前库补盖
    python3 backend/db_build.py           # 看当前库盖的章,和现在的造数逻辑比一比
"""
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "lanxiu.db")
键 = ("build_commit", "build_at", "build_logic_fp", "build_logic_n")


def 造数文件():
    """rebuild.sh 步骤清单里的脚本 + knowledge/ 下的 .py / .md(排序后的相对路径)。"""
    文 = set()
    try:
        sh = open(os.path.join(ROOT, "tools", "rebuild.sh"), encoding="utf-8").read()
        for m in re.finditer(r'"((?:backend|tools)/[^"\s]+\.py)', sh):
            文.add(m.group(1))
    except OSError:
        pass
    kd = os.path.join(ROOT, "knowledge")
    for n in (os.listdir(kd) if os.path.isdir(kd) else []):
        if n.endswith((".py", ".md")):
            文.add(f"knowledge/{n}")
    return sorted(x for x in 文 if os.path.isfile(os.path.join(ROOT, x)))


def 当前指纹():
    """→ (指纹, 文件数, 提交号)。指纹按**文件内容**算(工作区里没提交的改动也算进去)。"""
    h = hashlib.sha256()
    文 = 造数文件()
    for p in 文:
        h.update(p.encode()); h.update(b"\0")
        h.update(open(os.path.join(ROOT, p), "rb").read()); h.update(b"\0")
    try:
        头 = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"],
                           capture_output=True, text=True, timeout=10).stdout.strip() or "(取不到)"
        脏 = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", *文],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        头, 脏 = "(取不到)", ""
    return h.hexdigest()[:16], len(文), 头 + ("+dirty" if 脏 else "")


def 读(db=None):
    """库上盖的章 → {build_commit, build_at, build_logic_fp, build_logic_n};没盖过的键值是 None。"""
    c = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    try:
        有 = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_meta'").fetchone()
        行 = dict(c.execute(f"SELECT k, v FROM world_meta WHERE k IN ({','.join('?' * len(键))})", 键).fetchall()) if 有 else {}
    finally:
        c.close()
    return {k: 行.get(k) for k in 键}


def 盖章(db=None):
    fp, n, 头 = 当前指纹()
    if not n:
        sys.exit("❌ 一个造数文件都没找到 —— 算出来的不是指纹,不盖")
    c = sqlite3.connect(db or DB)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS world_meta(k TEXT PRIMARY KEY, v TEXT)")
        建于 = datetime.now().isoformat(timespec="seconds")   # 真实时钟:记库在真实世界里什么时候建的,和演示世界日期无关
        for k, v in zip(键, (头, 建于, fp, str(n))):
            c.execute("INSERT INTO world_meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        c.commit()
    finally:
        c.close()
    return 读(db)


if __name__ == "__main__":
    if "--盖章" in sys.argv:
        r = 盖章()
        print(f"✅ 库已盖章:提交 {r['build_commit']} · 造数指纹 {r['build_logic_fp']}({r['build_logic_n']} 个文件)· {r['build_at']}")
    else:
        r, (fp, n, 头) = 读(), 当前指纹()
        print(f"库上的章:{r}")
        print(f"现在的造数逻辑:指纹 {fp}({n} 个文件)· 提交 {头}")
        if not r["build_logic_fp"]:
            print("⚠️ 这个库没盖过章 —— 不知道是哪一版造数逻辑建的(10-26 之前建的库都这样)")
        elif r["build_logic_fp"] != fp:
            print("⚠️ **库是旧造数逻辑建的**,和现在的代码对不上 —— 在它上面跑出的评测不能和新库上的比")
        else:
            print("✅ 库和现在的造数逻辑一致")
