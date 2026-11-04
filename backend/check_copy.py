# -*- coding: utf-8 -*-
"""检查用的库副本:拷一份真库,把**已经 import 的那些**指着真库的库路径一次全改到副本上。

为什么要这一份(2026-10-19):门禁的台账闸(LANXIU_CHECK_LEAK)逮到 7 个检查往真库台账写。
其中 4 个已经把业务数据指到副本了,**只漏了 oplog.DB** —— 每个模块各有一个 `DB`,
一个个手指,总有一个会漏,而漏的那个不报错。另 3 个干脆在真库上「改了再还原」,
中途崩了就留在真库里(10-19 那条「张静静改派 SC21711」就是这么来的)。

用法:import 完被测模块之后调一次。之后才 import 的模块(函数里懒加载的)不会被改到 ——
那种漏写台账的,门禁那道闸照样会点名。

## ⚠️⚠️ 第二个窟窿:扫模块变量的那把扫帚,碰不到烤死在默认参数里的路径(2026-11-04 补)

    DB = os.path.join(HERE, "lanxiu.db")
    def 记一笔(db=DB):        # ← 默认值在 **def 执行的那一刻**就算定了
        c = sqlite3.connect(db)
    ...
    模块.DB = 副本             # ← 改不动上面那个 db
    模块.记一笔()              # ← 写真库

2026-11-03 共享库 `rating` 1319 → 1264、**55 条评价**就是这么丢的,
而且丢的那一刻另一个会话正在跑全量门禁,那一轮整个作废。

**这个窟窿在补之前是活的,不是理论上的。** 实测:import 四个写口再调 `用副本()`,
模块变量全都指到副本了,而**仍有 22 个函数的默认参数指着真库** ——
其中两个就叫 `记一笔`(`credit.记一笔` / `ownership.记一笔`,都是写函数)。

> 一个「改了库路径变量就会跟着走的写口」,和一个「在 def 那一刻就把当时的库捏在手里的写口」,
> **在 `模块.DB = 副本` 这一行上长得一模一样。**

所以 `用副本()` 现在做三件事,缺一不可:
① 换模块变量 ② **换函数默认参数** ③ 换完**断言切干净了**(两类都不许再指着真库)。

## ⚠️ 断言落在**连接**上,不落在模块变量上

`tools/db_switchable_check.py` 扫的是源码形状(库路径别当默认参数值),它自己写明了
「不验运行时真的连上了哪个文件」。这一份补的就是那一半,而判据是
**`PRAGMA database_list`** —— 它报的是文件描述符真正落在哪。

模块变量会在三种情况下撒谎,而连接不会:

    ① `def 记一笔(db=DB)` 默认值在 def 时烤死,之后改模块变量它不跟
    ② 切库**之前**就开好的连接,句柄还在老文件上
    ③ `backend/lanxiu.db` 是软链 —— `cp -R` 出来的「副本」指回真库,
       而变量上看着是副本路径

三种里**只有 ③** 能靠 `realpath(变量)` 发现;前两种只有问连接才问得出来。

⚠️ 比较时**期望那一边也要 realpath**:SQLite 把路径解到底才报
(传 `/var/folders/…` 它报 `/private/var/folders/…`,因为 macOS 上 `/var` 自己是软链)。
朴素写 `报的 == 期望` 会每次都不相等 —— 吵,但安全;
真正危险的是比 basename 或者比模块变量那种,**那种永远相等**。
"""
import atexit
import os
import shutil
import sqlite3
import sys
import tempfile
import types
from contextlib import closing

真库 = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db"))

# 哪些模块属性名算「库路径」。**不是枚举中文**,是这个项目的写法约定
# (`tools/db_switchable_check.py` 那条判据同时在守「别起别的名字」)。
库路径属性名 = ("DB", "DB_PATH")


class 连错库(AssertionError):
    """写之前断言没过:连接真正落在的那个文件,不是以为的那个。"""


# ── 连接层:问连接,不问模块变量 ──────────────────────────────────────


def 规范(路径):
    """→ 可比的形式。内存库统一成 ':memory:';其余 realpath 到底(软链 + macOS /var)。"""
    if 路径 in (None, "", ":memory:"):
        return ":memory:"
    return os.path.realpath(路径)


def 确认是另一份(副本, 真=None, 何处=""):
    """断言这份「副本」真的是另一个文件,不是一条解回真库的软链。→ 副本的规范路径。

    ⚠️⚠️ **这件事 `确认连的是(conn, 副本)` 构造性地验不了。** 那个断言两边都 realpath,
       而一条软链和它指向的文件 realpath 之后本来就相等 —— 于是它在 cp -R 那个坑上
       **永远通过**。第一版 `用副本` 里写的就是那条,写完自测 ⑤ 才把它揪出来。

    > 一条匹配不到任何东西的断言,和一条守住了的断言,**在绿勾上长得一模一样。**
    """
    真 = os.path.realpath(真 or 真库)
    副 = 规范(副本)
    if 副 == 真:
        raise 连错库(
            f"这份「副本」解回真库了{'(' + 何处 + ')' if 何处 else ''}:"
            f"{副本} → {副} —— 多半是用 `cp -R` / `copytree` 拷的,"
            f"那样拷的是**软链本身**,不是一份库")
    return 副


def 实际连的是(conn):
    """这个连接**真正打开**的那个文件。内存库 → ':memory:'。"""
    for _序, 名, 文件 in conn.execute("pragma database_list"):
        if 名 == "main":
            return 文件 or ":memory:"
    raise 连错库("这个连接没有 main 库 —— pragma database_list 一行都没返")


def 确认连的是(conn, 期望, 何处=""):
    """写之前拿这个断一下:连接真正落在的那个文件,就是以为的那个。→ 实际那个路径。

    ⚠️ 查连接,不查模块变量 —— 理由见文件头那三种撒谎的情况。
    """
    实 = 实际连的是(conn)
    期 = 规范(期望)
    if 实 != 期:
        raise 连错库(
            f"连错库了{'(' + 何处 + ')' if 何处 else ''}:"
            f"以为连的是 {期},**实际连上的是 {实}**")
    return 实


# ── 切库:两类都要换,换完要断言切干净了 ──────────────────────────────


def _本项目的模块():
    """只扫装在这个仓库里的模块 —— 标准库和 .venv 里不可能有指着这个库的默认参数,
    而全扫一遍要对上万个默认值做 realpath。"""
    # ⚠️⚠️ 根从**本文件**算,不从 `真库` 算。`真库` 是 realpath 之后的路径,
    #    而 `backend/lanxiu.db` 是条软链、指向**主检出** —— 拿它算根会算出主检出,
    #    于是这个 worktree 里每个模块的 `__file__` 都匹配不上,扫帚一声不响扫出 0 个模块。
    #    那时下面「切干净了」那条断言**必然通过**,因为它核的是同一个空集合。
    根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for m in list(sys.modules.values()):
        if not isinstance(m, types.ModuleType):
            continue
        f = getattr(m, "__file__", None)
        if isinstance(f, str) and (f.startswith(根) and ".venv" not in f):
            yield m
        elif f is None and getattr(m, "__name__", "") == "__main__":
            yield m


def _函数们(m):
    """模块里的函数:顶层的 + 类里一层的(含 static/classmethod)。"""
    for v in list(vars(m).values()):
        if isinstance(v, types.FunctionType):
            yield v
        elif isinstance(v, type):
            for w in list(vars(v).values()):
                if isinstance(w, (staticmethod, classmethod)):
                    w = w.__func__
                if isinstance(w, types.FunctionType):
                    yield w


def _是这个库(值, 真):
    return isinstance(值, str) and os.sep in 值 and os.path.realpath(值) == 真


def 换模块变量(真, 新):
    """→ 改了几处。原来这段写在 `用副本` 里,拆出来是为了让「还指着真库的」能照着同一组类别去核。"""
    真 = os.path.realpath(真)   # ⚠️ 见 `换默认参数` 里那段警告
    改 = 0
    for m in _本项目的模块():
        for 名 in 库路径属性名:
            if _是这个库(getattr(m, 名, None), 真):
                setattr(m, 名, 新)
                改 += 1
    return 改


def 换默认参数(真, 新):
    """把函数默认参数里**烤死**的库路径换成新的 → 改了几处。

    ⚠️ 这一支是 2026-11-04 补的,而它是那次丢 55 条评价的直接修法。
       少了它,`用副本()` 跑完仍有 22 个函数的默认参数指着真库。

    ⚠️ **`真` 必须先 realpath。** `_是这个库` 拿 `realpath(值) == 真` 比,
       传进来一个没解过的路径(`/var/folders/…`,而 macOS 上它解成 `/private/var/…`)
       就**一处都匹配不上** —— 而匹配 0 处的时候,下面「切干净了」那条断言自动成立。
       自测 ⑨⑪ 里那两个「至少改到几处」的下限就是为了逮这个。
    """
    真 = os.path.realpath(真)
    改 = 0
    for m in _本项目的模块():
        for f in _函数们(m):
            ds = f.__defaults__
            if ds:
                新组 = tuple(新 if _是这个库(v, 真) else v for v in ds)
                if 新组 != ds:
                    f.__defaults__ = 新组
                    改 += sum(1 for a, b in zip(ds, 新组) if a is not b)
            kw = f.__kwdefaults__
            if kw:
                for k, v in list(kw.items()):
                    if _是这个库(v, 真):
                        kw[k] = 新
                        改 += 1
    return 改


def 还指着真库的(真=None):
    """→ (模块变量清单, 函数默认参数清单)。切完拿它断言「切干净了」。

    ⚠️ 核的类别必须和上面两个 `换…` 覆盖的**完全一样**,否则这条断言要么漏、
       要么误报(比如本模块的 `真库` 本身就等于真库,但它不在 `库路径属性名` 里,
       扫帚不碰它,这里也就不该核它)。
    """
    真 = os.path.realpath(真 or 真库)
    变量们, 默认们 = [], []
    for m in _本项目的模块():
        名 = getattr(m, "__name__", "?")
        for a in 库路径属性名:
            if _是这个库(getattr(m, a, None), 真):
                变量们.append(f"{名}.{a}")
        for f in _函数们(m):
            坏 = [v for v in (f.__defaults__ or ()) if _是这个库(v, 真)]
            坏 += [v for v in (f.__kwdefaults__ or {}).values() if _是这个库(v, 真)]
            if 坏:
                默认们.append(f"{名}.{f.__name__}()")
    return sorted(set(变量们)), sorted(set(默认们))


def 用副本(前缀="chk-"):
    """→ 副本路径。进程退出时删掉。台账模块总是先 import 进来再改 —— 写口里常常懒加载它,
    不先加载的话改不到,台账照样写真库(membership_check 当场这样漏过)。"""
    import oplog  # noqa: F401
    目录 = tempfile.mkdtemp(prefix=前缀)
    副本 = os.path.join(目录, "lanxiu.db")
    # ⚠️ 用 shutil.copy 不用 copytree/cp -R:copy 跟着软链走、拷的是**内容**。
    #    `backend/lanxiu.db` 是条软链,拷「软链本身」拷出来的是一条指回真库的链。
    shutil.copy(真库, 副本)
    atexit.register(shutil.rmtree, 目录, True)

    换模块变量(真库, 副本)
    换默认参数(真库, 副本)

    # ① 这一份「副本」真的是另一个文件,不是一条解回真库的链
    #    ⚠️ 这里**不能**写 `确认连的是(c, 副本)` —— 那条两边都 realpath,
    #       软链和它指向的文件解完本来就相等,于是它在这个坑上永远通过。
    确认是另一份(副本, 真库, "用副本:刚拷出来的这一份")
    #    再从连接那一头核一遍:真写的时候落的就是副本,不是真库
    with closing(sqlite3.connect(副本)) as c:
        落在 = 实际连的是(c)
    if 落在 == 真库:
        raise 连错库(f"连接落在真库上:{副本} → {落在}")
    # ② 切干净了 —— 两类都不许再有指着真库的
    变量们, 默认们 = 还指着真库的()
    if 变量们 or 默认们:
        raise 连错库(
            "切库没切干净,**而这一步不拦的话下面每一次写都落在共享真库上**:"
            + (f"\n  模块变量 {len(变量们)} 处:{变量们[:6]}" if 变量们 else "")
            + (f"\n  函数默认参数 {len(默认们)} 处:{默认们[:6]}" if 默认们 else ""))
    return 副本

