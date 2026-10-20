#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每条研判记下用的哪版提示词 · 检查(研判队列未做项第 5 项第一步,2026-10-19)。

库里 triage.prompt_ver 这一列早就有,产线从来没写过(10-19 主库 56 条全空)——
断在后台 /api/ops-triage 那一跳:站上没算、后台也没往下传。换了提示词之后,
新旧研判混在一起分不开,版本对比和回退都没有落脚点。要守的:
  · 版本号 = 真调 `研判提示词` 取的指纹 —— 改了提示词,版本号必须跟着变(不许另抄一份模板去算);
  · 三类研判各有各的版本;同一份提示词算两次一样;
  · 站上真跑那条路把版本号带上,后台往下传、真落库。
"""
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("版本号写死(不随提示词变)", "改了提示词(四段那条通用要求)→ 三类的版本号都变"),
    ("后台不往下传版本号", "后台 /api/ops-triage 把版本号往下传"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("每条研判记下用的哪版提示词 · 检查")
print("=" * 80)

import ops, oplog

类 = ("财务人工任务", "客户合并确认", "售后判责")
版 = {t: ops.研判提示词版本(t) for t in 类}
ck("三类研判各有各的版本号(12 位)", len(set(版.values())) == 3 and all(len(v) == 12 for v in 版.values()), 版)
ck("同一份提示词算两次一样", all(ops.研判提示词版本(t) == 版[t] for t in 类))
原 = ops.四段
try:
    ops.四段 = 原 + "\n(检查临时加的一句)"
    改 = {t: ops.研判提示词版本(t) for t in 类}
finally:
    ops.四段 = 原
ck("改了提示词(四段那条通用要求)→ 三类的版本号都变", all(改[t] != 版[t] for t in 类), (版, 改))

tmp = tempfile.mkdtemp(prefix="pver-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
ops.DB = oplog.DB = db
with sqlite3.connect(db) as c:
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-检查-版本','财务人工任务','P-x','待处理',"
              "'2026-01-01 10:00:00','检查')")
号 = f"研判:{版['财务人工任务']}·系统:abcdef123456"
tid = ops.save_triage("T-检查-版本", "BP-01", "检查-版本", "根因:检查\n建议动作:检查\n证据:无", [], prompt_ver=号)
存 = sqlite3.connect(db).execute("SELECT prompt_ver FROM triage WHERE id=?", (tid,)).fetchone()
ck("给了版本号就真落库", 存 and 存[0] == 号, 存)
shutil.rmtree(tmp, ignore_errors=True)

服 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
段 = 服[服.index('if p=="/api/ops-triage"'):]
段 = 段[:段.index("return self._send")]
ck("后台 /api/ops-triage 把版本号往下传", 'prompt_ver=body.get("prompt_ver")' in 段)
站 = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
ck("站上真跑研判时带上版本号(研判提示词模板 + 系统提示词各一个指纹)",
   # 10-19 研判设置之后:研判那段指纹 = 代码当前版本,或设置里发布的那一版(渲染用的就是它)
   '研判版 = _ops_bp.研判提示词版本(t["type"])' in 站 and "prompt, 研判版 = _tr_cfg().渲染(_用" in 站
   and 'f"研判:{研判版}·系统:' in 站 and "sdk.SYS_TRIAGE" in 站 and "prompt_ver=版))" in 站)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判记下提示词版本:改了就变、三类分开、真落库、产线那条路带上了(验了 {n} 条){D}")
