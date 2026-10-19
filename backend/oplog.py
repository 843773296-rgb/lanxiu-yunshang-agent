# -*- coding: utf-8 -*-
"""操作台账。**只有这一份** —— 抽出来是因为写任务的逻辑要被两个入口共用:
HTTP 接口(人在页面上点)和 MCP 工具(智能体代人做)。
两边各写一份 log_op 的话,总有一边会漏记,而漏记的那边**看起来完全正常**。
"""
import os, sqlite3, json

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
_真库 = os.path.realpath(DB)


def _检查漏写了真库():
    """门禁里(check.sh 设了 LANXIU_CHECK_LEAK)往**真库**的台账写 → 记一笔漏、不写,返回 True。

    2026-10-19 发现:不少检查把业务数据写在库副本上,`oplog.DB` 却没跟着指过去 ——
    于是台账里出现「张静静把 SC21711 改派给周叙」这种**挂在真员工名下的假操作**。
    业务表干净、检查全绿,只有翻台账才看得出:**台账本来就该有新行,所以多几行假的没人会觉得怪。**
    人在页面上点(服务进程不在门禁里,没有这个环境变量)照常记。"""
    漏 = os.environ.get("LANXIU_CHECK_LEAK")
    if not 漏 or os.path.realpath(DB) != _真库:
        return False
    import sys
    try:
        with open(漏, "a", encoding="utf-8") as f:
            f.write(os.path.relpath(os.path.abspath(sys.argv[0])) + "\n")
    except Exception:
        pass
    return True


def log_op(actor, mid, target, frm, to, ok, code, reason, ctx):
    if _检查漏写了真库():
        return
    with sqlite3.connect(DB) as c:
        # 真实时钟:操作台账记「谁在什么时候真的点了这一下」—— 那是运维痕迹,
        # 不是演示世界里的事。用世界时钟反而会让台账对不上真实的排查时间线。
        c.execute("INSERT INTO op_log(ts,actor,machine,target,frm,too,allowed,code,reason,ctx)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?,?,?)",
                  (actor, mid, target, frm, to, 1 if ok else 0, code, reason,
                   json.dumps(ctx, ensure_ascii=False)))
