# -*- coding: utf-8 -*-
"""操作台账。**只有这一份** —— 抽出来是因为写任务的逻辑要被两个入口共用:
HTTP 接口(人在页面上点)和 MCP 工具(智能体代人做)。
两边各写一份 log_op 的话,总有一边会漏记,而漏记的那边**看起来完全正常**。
"""
import os, sqlite3, json

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")


def log_op(actor, mid, target, frm, to, ok, code, reason, ctx):
    with sqlite3.connect(DB) as c:
        # 真实时钟:操作台账记「谁在什么时候真的点了这一下」—— 那是运维痕迹,
        # 不是演示世界里的事。用世界时钟反而会让台账对不上真实的排查时间线。
        c.execute("INSERT INTO op_log(ts,actor,machine,target,frm,too,allowed,code,reason,ctx)"
                  " VALUES(datetime('now','localtime'),?,?,?,?,?,?,?,?,?)",
                  (actor, mid, target, frm, to, 1 if ok else 0, code, reason,
                   json.dumps(ctx, ensure_ascii=False)))
