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
import argparse, json, os, shutil, subprocess, sys, tempfile

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
]

# 副本里**不**带的东西。
# ⚠️ 这里原来是白名单(列出要拷哪些),2026-09-17 改成黑名单。
# 起因:白名单漏了根目录的 `.mcp.json`,于是 `boundary_audit` 在副本里对照就是红的 ——
# 而「副本漏了文件」和「代码真的坏了」在报告里长得一模一样。
# **白名单会静默漏掉新加的文件,黑名单不会。**
不带 = {".git", ".venv", "__pycache__", ".pytest_cache", ".DS_Store", "node_modules"}

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
    out = ["agentsite/.venv", ".venv"]
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
                                "*.db-journal", "*.db-wal", "*.db-shm", "录音")
    def f(目录, 名字们):
        # 库的临时日志(-journal / -wal / -shm)不带:它们随写随删,复制到一半消失会让 copytree 报
        # Errno 2(10-03 队友撞到过)—— 而且带过去也没用,副本里的库是独立打开的。
        # 录音目录也不带:客户的声音,几十 MB 一通,检查用不到。
        丢 = set(基(目录, 名字们))
        rel = os.path.relpath(目录, ROOT)
        for n in 名字们:
            if os.path.normpath(os.path.join(rel, n)) in 软链:
                丢.add(n)
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
    if 拷了 > 顶:
        raise SystemExit(f"❌ 一份副本要拷 {拷了/2**20:.0f} MB,超过上限 {顶/2**20:.0f} MB ——"
                         f" 全量 {len(json.load(open(SPECS, encoding='utf-8'))) if os.path.exists(SPECS) else 0} 条"
                         f" 规格要拷这么多份。把新来的大目录登记进 `媒体大目录`,"
                         f"或者抬高 `拷贝上限` 并写明为什么")
    return dst


def 门禁怎么跑(script):
    """从 check.sh 里取这个脚本的原样命令。

    ⚠️ **不要自己拼 `python3 <脚本>`。** 门禁里有些步骤用的是 `agentsite/.venv/bin/python`，
    有些带 `--selftest` 参数。用另一种姿势去跑，验的就不是门禁验的那个东西 ——
    这个项目已经栽过一次同族的事：副本测试没软链 venv，7 项「失败」全是环境问题，
    和真的数据问题混在同一张报告里。
    """
    sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
    for line in sh.split("\n"):
        if not line.startswith("run "): continue
        if script not in line: continue
        # run "标题" cmd args...   —— 标题带引号，去掉它之后剩下的就是命令
        rest = line[4:].strip()
        if rest.startswith('"'):
            rest = rest[rest.index('"', 1) + 1:]
        parts = rest.split()
        if parts: return parts
    return [sys.executable, script]


def 跑(sand, script):
    cmd = 门禁怎么跑(script)
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
        global ROOT
        真根 = ROOT
        try:
            ROOT = 假
            假副本 = 建副本(os.path.join(base, "假副本"))
        finally:
            ROOT = 真根
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

        try:
            建副本(os.path.join(base, "顶"), 上限=1)
            print("  ❌ 字节上限设成 1 字节都没拦下来 —— 这条上限是摆设"); 坏 += 1
        except SystemExit as e:
            if "超过上限" in str(e): print("  ✅ 字节上限真的会拦(把上限设成 1 字节,它红了)")
            else: print(f"  ❌ 上限那条红了,但红的不是它:{e}"); 坏 += 1
    finally:
        shutil.rmtree(base, ignore_errors=True)
    if 坏:
        print(f"❌ 副本自测 {坏} 条没过")
        return 1
    print("✅ 副本自测 5 条全过")
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

    base = tempfile.mkdtemp(prefix="bite-")
    pristine = 建副本(os.path.join(base, "pristine"))
    print(f"副本:{base}")
    print("=" * 96)

    对照 = {}
    红 = []
    for i, s in enumerate(specs, 1):
        script, expect = s["script"], s["预期红"]
        work = os.path.join(base, "work")
        if os.path.isdir(work): shutil.rmtree(work)
        # ⚠️ **`symlinks=True` 不能省。** 省掉它,copytree 会**跟着软链走**,
        # 把 `商品图备份` / `backend/static/img*` 整份拷实 —— 一条规格 10.7 GB、19 秒,
        # 而 `pristine` 那一份是瘦的,**看上去一切正常**。
        # 2026-10-17 实测:加上这个参数,单条从 31 秒掉到 1 秒以内。
        shutil.copytree(pristine, work, symlinks=True)

        # ① 对照要绿
        if script not in 对照:
            rc0, out0 = 跑(work, script)
            对照[script] = (rc0, out0)
        rc0, out0 = 对照[script]
        if rc0 != 0:
            print(f"  ❌ [{i}/{len(specs)}] {script}  **对照就是红的** —— 这条咬合证明不了任何事")
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
    if 红:
        print(f"❌ {len(红)}/{len(specs)} 条咬合规格没过 —— **这些检查没被证明过**")
        return 1
    print(f"✅ {len(specs)} 条咬合规格全过(每条都验了:对照绿 → 改坏 → 红的是那一条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
