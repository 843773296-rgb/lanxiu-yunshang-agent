"""门禁里的库重定向:**凡是连真库的,一律连到门禁开头拷的那份副本上**(2026-11-12,执行手册 W02)。

只在 `check.sh` 里生效:它把这个目录放进 PYTHONPATH、并 export LANXIU_GATE_DB=<副本>、LANXIU_REAL_DB=<真库>。
⚠️ **不复用 LANXIU_DB**:那个变量已经有自己的意思(MCP 工具服务见到它就把各模块的 DB 改指过去、
`triage_trial_check` 专门验「不给它时什么都不改」)。门禁要是 export 它,这几条检查测的就成了另一件事。
Python 启动时自动 import `sitecustomize`,于是门禁里每一个 Python 进程(包括检查拉起的子进程、
MCP 工具服务、venv 里的解释器)的 `sqlite3.connect` 都先过这里。服务进程(8760 / 8770 / 8801)
不在门禁里,没有这两个变量,一个字节都不受影响。

为什么做在连接这一层,不去改 127 处 `DB = …lanxiu.db`:
  · 那 127 处写法五花八门(HERE 拼、ROOT 拼、realpath、烤进默认参数、函数里现拼),
    逐个改会漏,而**漏的那个不报错,只是照旧写真库**(10-19 台账假操作、11-03 丢 55 条评价都是这么来的);
  · 所有写法最后都落到 `sqlite3.connect(路径)` —— 只有这一个出口。`backend/check_copy.py` 早就说过:
    「断言落在连接上,不落在模块变量上」。这里是把同一个道理用在重定向上。

判据:连接目标(普通路径或 `file:…?mode=ro` 这种 URI)**解析软链之后**等于真库 → 换成副本,
URI 的查询参数原样保留(只读打开的仍是只读)。别的库(副本、临时库、:memory:)不动。
"""
import os
import sqlite3

_副本 = (os.environ.get("LANXIU_GATE_DB") or "").strip()
_真 = (os.environ.get("LANXIU_REAL_DB") or "").strip()

if _副本 and _真 and os.path.realpath(_副本) != os.path.realpath(_真):
    _真实 = os.path.realpath(_真)
    _原 = sqlite3.connect

    def _改(目标):
        if not isinstance(目标, (str, os.PathLike)):
            return 目标
        s = os.fspath(目标)
        if s.startswith("file:"):
            路, 问, 参 = s[5:].partition("?")
            if 路 and os.path.realpath(路) == _真实:
                return "file:" + _副本 + (问 + 参 if 问 else "")
            return 目标
        if s and s != ":memory:" and os.path.realpath(s) == _真实:
            return _副本
        return 目标

    def connect(database, *a, **kw):
        return _原(_改(database), *a, **kw)

    connect.__doc__ = _原.__doc__
    connect._门禁重定向 = True          # 给检查认:这一层确实挂上了
    sqlite3.connect = connect
    try:
        import sqlite3.dbapi2 as _d2      # `from sqlite3.dbapi2 import connect` 那条路也要盖住
        _d2.connect = connect
    except Exception:
        pass
