#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判设置 · 开发用的发布 / 退回 / 版本登记(用户 2026-10-19 拍「只有开发能发布」)。

总部运营在研判设置页上改草稿、试运行;发布和退回在这里做,**写明是哪位开发**:

    python3 tools/triage_config.py 看                          # 现在生效什么、有哪些草稿
    python3 tools/triage_config.py 发布 <配置号> --by <开发名字>   # 要先在页面上试运行过
    python3 tools/triage_config.py 退回 --by <开发名字>           # 撤下现在那一版,回到它之前那一版
    python3 tools/triage_config.py 登记版本                      # 把代码里现在的提示词登记成可选版本(未验证)
    python3 tools/triage_config.py 验证 <指纹> --说明 "<跑了哪套评测、几轮、多少分>"

参数拼错一律拒跑(不会悄悄按别的动作跑)。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import triage_config as TC  # noqa: E402

a = sys.argv[1:]


def 取(名):
    if 名 in a:
        i = a.index(名)
        if i + 1 < len(a):
            v = a[i + 1]; del a[i:i + 2]; return v
        sys.exit(f"{名} 后面要跟一个值")
    return None


by, 说明 = 取("--by"), 取("--说明")
if not a:
    sys.exit(__doc__)
动, 余 = a[0], a[1:]
if 动 == "看" and not 余:
    o = TC.概览()
    print(f"现在生效:配置#{o['生效版本'] or '(没发布过,用代码默认值)'}")
    print(f"  时限 {o['生效']['时限']} · 批量上限 {o['生效']['批量上限']} · 提示词 {o['生效']['提示词版本'] or '(代码当前)'}")
    for r in o["历史"][:10]:
        print(f"  #{r['id']:<4} {r['status']:<4} {r['payload']}  {'试运行过' if r['tried_at'] else '没试运行'}  {r['note'] or ''}")
elif 动 == "发布" and len(余) == 1 and 余[0].isdigit() and by:
    r = TC.发布(int(余[0]), by); print(r["reason"]); sys.exit(0 if r["ok"] else 1)
elif 动 == "退回" and not 余 and by:
    r = TC.退回上一版(by); print(r["reason"]); sys.exit(0 if r["ok"] else 1)
elif 动 == "登记版本" and not 余:
    print(TC.登记当前版本())
elif 动 == "验证" and len(余) == 1 and 说明:
    import sqlite3, ops
    from contextlib import closing
    with closing(sqlite3.connect(ops.DB)) as c, c:
        TC.确保表(c)
        n = c.execute("UPDATE triage_prompt SET verified=1, verified_note=? WHERE fp=?", (说明, 余[0])).rowcount
    if not n:
        sys.exit(f"没有版本 {余[0]}")
    print(f"版本 {余[0]} 标成已验证:{说明}")
else:
    sys.exit(f"不认识的用法:{sys.argv[1:]}\n" + __doc__)
