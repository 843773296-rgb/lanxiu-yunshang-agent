#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研判设置 · 检查(研判队列未做项第 5 项第二步 · 用户 2026-10-19 拍)。库副本上真调,从草稿走到发布、退回。

要守的:
  · 切换提示词版本不许悄悄换掉内容:按登记的版本渲染出来,和代码直接生成的**逐字一致**;
  · 时限按**建单那一刻**生效的版本:发布之前建的单照旧,之后建的才用新时限(方案原文「进行中的不受影响」);
  · 只开放三样:角色权限类的键拒收;没验证的提示词版本选不了;批量 / 时限超范围拒收;
  · 只有总部运营能存草稿、试运行;**没试运行过的发布不了**;发布 / 退回要写明是哪位开发,页面接口不收「发布」;
  · 退回 = 再发布上一版,历史只增不改。
"""
import datetime as dt
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("时限按「现在生效的」算(发布一下在办的全跟着变)", "发布之前建的单照旧 24 小时,之后建的才按新时限 2 小时"),
    ("没试运行也能发布", "没试运行过的发布不了"),
    ("渲染时漏换占位单号", "按登记的版本渲染,三类都和代码直接生成的逐字一致"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


def 抛(f):
    try:
        f(); return None
    except Exception as e:                   # noqa: BLE001
        return e


print("研判设置 · 检查")
print("=" * 80)

import ops, oplog, check_copy
import triage_config as TC
db = check_copy.用副本("tcfg-")
with sqlite3.connect(db) as c:              # 副本里先清掉主库上真实的设置记录 —— 「生效哪一版」不许取决于主库被怎么用过
    TC.确保表(c)
    c.execute("DELETE FROM triage_config"); c.execute("DELETE FROM triage_prompt")
c = sqlite3.connect(db)
人 = lambda role: c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1",
                            (role,)).fetchone()
部, 长 = (dict(zip(("no", "name", "role"), 人(r))) for r in ("总部运营", "店长"))
c.close()

# ① 渲染 = 代码
fps = TC.登记当前版本(验证="检查:基线")
样 = {"财务人工任务": ("D2000", "TDQ9003"), "客户合并确认": ("C21000|C21001", "TMERGE-00"), "售后判责": ("MW73030", "TAS-1")}
ck("按登记的版本渲染,三类都和代码直接生成的逐字一致",
   all(TC.渲染(fps[k], k, *v) == ops.研判提示词(k, *v)[2] for k, v in 样.items()))
ck("登记的指纹就是每条研判记的那个版本号", all(fps[k] == ops.研判提示词版本(k) for k in fps))

# ② 校验 / 权限
ck("店长存不了草稿(只有总部运营能改)", isinstance(抛(lambda: TC.草拟({"批量上限": 5}, 长)), PermissionError))
r = TC.草拟({"复核角色": {"财务人工任务": ["店长"]}}, 部)
ck("角色权限类的键拒收(用户 10-19 拍:一律不开放)", r.get("ok") is False and "不开放" in "".join(r.get("错", [])), r)
with sqlite3.connect(db) as cx:
    cx.execute("INSERT INTO triage_prompt(fp,task_type,template,created,verified) VALUES('未验证000000','财务人工任务','x','2026-01-01',0)")
r = TC.草拟({"提示词版本": {"财务人工任务": "未验证000000"}}, 部)
ck("没验证过的提示词版本选不了", r.get("ok") is False and "没验证" in "".join(r.get("错", [])), r)
r = TC.草拟({"批量上限": 0, "时限": {"财务人工任务": 0}}, 部)
ck("批量 / 时限超范围拒收", r.get("ok") is False and len(r.get("错", [])) == 2, r)

# ③ 草稿 → 没试运行发布不了 → 试运行 → 发布(开发)
r = TC.草拟({"时限": {"财务人工任务": 2}, "批量上限": 4}, 部, note="检查")
号 = r.get("id")
ck("没试运行过的发布不了", TC.发布(号, "检查开发").get("ok") is False and TC.生效(db=db)[1] is None)
试 = TC.试运行(号, 部)
ck("试运行说清「在办的不受影响,新建的才按新时限」", 试.get("ok") and any("不受影响" in x for x in 试.get("报告", [])), 试)
ck("发布要写明是哪位开发", isinstance(抛(lambda: TC.发布(号, "")), PermissionError))
import time as _t
def 建单(tid):                               # 按**真实先后**造单:建单时刻 = 世界此刻
    with sqlite3.connect(db) as cx:
        cx.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES(?,?,?,?,?,?)",
                   (tid, "财务人工任务", "P-x", "待处理", ops.now().strftime("%Y-%m-%d %H:%M:%S"), "检查"))
    _t.sleep(1.1)                            # 时刻精确到秒:两件事之间隔开一秒,先后才分得清
建单("T-检查-设置-旧")
发 = TC.发布(号, "检查开发")
_t.sleep(1.1)
建单("T-检查-设置-新")
行 = {x["task_id"]: x for x in ops.queue() if x["task_id"].startswith("T-检查-设置-")}
ck("发布之前建的单照旧 24 小时,之后建的才按新时限 2 小时",
   发.get("ok") and 行.get("T-检查-设置-旧", {}).get("sla_h") == 24 and 行.get("T-检查-设置-新", {}).get("sla_h") == 2,
   {k: v.get("sla_h") for k, v in 行.items()})
ck("批量上限按现在生效的那一版", TC.生效(db=db)[0]["批量上限"] == 4)

# ④ 退回
退 = TC.退回上一版("检查开发")
_t.sleep(1.1)
建单("T-检查-设置-退回后")
行 = {x["task_id"]: x for x in ops.queue() if x["task_id"].startswith("T-检查-设置-")}
ck("退回 = 再发布上一版(新记一行),之后批量回到默认 10",
   退.get("ok") and TC.生效(db=db)[0]["批量上限"] == 10 and TC.生效(db=db)[1] == 退.get("id") != 号, 退)
ck("退回之后:已建的单不变(按建单那一刻的版本),退回之后新建的回到 24 小时",
   行.get("T-检查-设置-新", {}).get("sla_h") == 2 and 行.get("T-检查-设置-退回后", {}).get("sla_h") == 24,
   {k: v.get("sla_h") for k, v in 行.items()})

# ⑤ 接口 / 站上 / 命令 / 平移登记
服 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
段 = 服[服.index('if p=="/api/triage-config":\n            # 研判设置:总部运营存草稿'):]
段 = 段[:段.index('if p=="/api/ops-reopen"')]
ck("页面接口只收草拟 / 试运行,不收发布(只有开发能发布)", "发布(" not in 段 and "退回上一版(" not in 段 and "草拟 / 试运行" in 段)
站 = open(os.path.join(ROOT, "agentsite", "app.py"), encoding="utf-8").read()
ck("站上:「研判 N 条」按配置的上限截;研判用配置的提示词版本",
   '_tr_cfg().生效()[0]["批量上限"]' in 站 and "_tr_cfg().渲染(_用" in 站)
p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "triage_config.py"), "发布", "1"],
                   capture_output=True, text=True)
ck("开发命令:不写 --by 不让发布(参数不对一律拒跑)", p.returncode != 0, p.returncode)
import importlib.util
_s = importlib.util.spec_from_file_location("sw", os.path.join(ROOT, "tools", "shift_world.py"))
sw = importlib.util.module_from_spec(_s); _s.loader.exec_module(sw)
ck("研判运行记录的机器时钟列登记成「平移不挪」(挪了心跳落在未来,死线程显示活着)",
   {"triage_worker.beat", "triage_run.created", "triage_run.stage_at"} <= set(sw.整列日期不挪))

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 研判设置:版本渲染逐字一致、时限按建单时的版本、只开放三样、试运行才能发布、只有开发发布(验了 {n} 条){D}")
