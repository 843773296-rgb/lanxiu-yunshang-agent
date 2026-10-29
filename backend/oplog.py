# -*- coding: utf-8 -*-
"""操作台账。**只有这一份** —— 抽出来是因为写任务的逻辑要被两个入口共用:
HTTP 接口(人在页面上点)和 MCP 工具(智能体代人做)。
两边各写一份 log_op 的话,总有一边会漏记,而漏记的那边**看起来完全正常**。
"""
from contextlib import closing   # ← 连接要显式关:sqlite3 的 with 只管事务,不关连接(2026-10-29)
import os, sqlite3, json

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
_真库 = os.path.realpath(DB)


def _检查漏写了真库(目标=None):
    """门禁里(check.sh 设了 LANXIU_CHECK_LEAK)往**真库**的台账写 → 记一笔漏、不写,返回 True。

    2026-10-19 发现:不少检查把业务数据写在库副本上,`oplog.DB` 却没跟着指过去 ——
    于是台账里出现「张静静把 SC21711 改派给周叙」这种**挂在真员工名下的假操作**。
    业务表干净、检查全绿,只有翻台账才看得出:**台账本来就该有新行,所以多几行假的没人会觉得怪。**
    人在页面上点(服务进程不在门禁里,没有这个环境变量)照常记。"""
    漏 = os.environ.get("LANXIU_CHECK_LEAK")
    if not 漏 or os.path.realpath(目标 or DB) != _真库:
        return False
    import sys
    try:
        with open(漏, "a", encoding="utf-8") as f:
            f.write(os.path.relpath(os.path.abspath(sys.argv[0])) + "\n")
    except Exception:
        pass
    return True


def log_op(actor, mid, target, frm, to, ok, code, reason, ctx, db=None):
    """`db` 不给就写真库(112 个调用方都是这样,全是位置参数,加这个参数不影响它们)。

    ⚠️ **给 `db` 是为了「自己带着库路径跑」的那几个脚本。** 它们的 `db` 是参数 ——
    自测和咬合都在**副本**上跑,而这个模块把真库路径**写死在模块级 `DB` 里**。
    在副本上跑却调 `log_op()` 不带 `db`,就会往**真库**塞一行假痕迹:
    业务表干净、检查全绿,只有翻台账才看得出 ——
    > **台账本来就该有新行,所以多几行假的没人会觉得怪。**
    (这正是下面 `_检查漏写了真库` 那段注释记的 2026-10-19 那个坑;
     那次是「`oplog.DB` 没跟着副本指过去」,而这次是反过来
     「脚本的 db 指着副本,而 log_op 指着真库」—— **同一个病的两头**。)
    漏写检查也跟着看 `db`:显式写副本是正当的,不算漏。

    ⚠️ 参数叫 `mid`,写进去的列叫 `machine`(2026-10-23 两个会话为这个各说对了一半)。
    那一列实际装的是**模块名** —— staff / schedule / download / approval / ordr / customer…
    """
    目标 = db or DB
    if _检查漏写了真库(目标):
        return
    with closing(sqlite3.connect(目标)) as c, c:
        # 真实时钟:操作台账记「谁在什么时候真的点了这一下」—— 那是运维痕迹,
        # 不是演示世界里的事。用世界时钟反而会让台账对不上真实的排查时间线。
        c.execute("INSERT INTO op_log(ts,actor,machine,target,frm,too,allowed,code,reason,ctx)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?,?,?)",
                  (actor, mid, target, frm, to, 1 if ok else 0, code, reason,
                   json.dumps(ctx, ensure_ascii=False)))
