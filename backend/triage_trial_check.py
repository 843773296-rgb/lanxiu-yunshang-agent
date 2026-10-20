#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离试运行 + 版本对比 · 检查(研判队列未做项第 6 项后两块 · 用户 2026-10-19 拍:副本遮掉顾客信息)。

要守的:
  · 遮蔽:顾客姓名 / 手机 / 地址 / 微信 / 邮箱在副本里一个原值都不剩;**同一个值换成同一个代号**
    (两条档案名字一样,遮完还一样 —— 客户合并要比的那件事没丢);
  · **真起一个工具服务**,给它 LANXIU_DB = 副本:查客户拿到的是代号,而且它留下了「副本生效」凭证;
    不给 LANXIU_DB 时什么都不改;
  · 试跑没有凭证就停下、那一条不存;参数不对拒跑;
  · 对比:用评测同一个判分函数算两版谁答对;跑挂了的单独数,不算答错。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("遮蔽漏了手机号", "遮蔽:顾客姓名 / 手机 / 地址在副本里一个原值都不剩"),
    ("工具服务不改读副本", "真起一个工具服务、给它副本:查客户拿到的是代号,并且留了「副本生效」凭证"),
    ("对比把跑挂了算成答错", "对比:跑挂了的单独数,不算答错"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:180]}" if 附 and not ok else ""))


print("隔离试运行 + 版本对比 · 检查")
print("=" * 80)
import triage_trial as TT

# ① 遮蔽
副 = TT.遮蔽副本()
真 = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
遮 = sqlite3.connect(副)
原 = {r[0]: r[1:] for r in 真.execute("SELECT id, name, phone, addr FROM customer")}
后 = {r[0]: r[1:] for r in 遮.execute("SELECT id, name, phone, addr FROM customer")}
原值 = {v for t in 原.values() for v in t if v}
剩 = [v for t in 后.values() for v in t if v in 原值]
ck("遮蔽:顾客姓名 / 手机 / 地址在副本里一个原值都不剩", len(原) > 100 and not 剩, 剩[:3])
ck("遮蔽:同一个值换成同一个代号(名字相同的档案,遮完还相同;不同的还不同)",
   all((原[a][0] == 原[b][0]) == (后[a][0] == 后[b][0]) for a in list(原)[:300] for b in list(原)[:300]))
ck("遮蔽:着装人的姓名也遮了", not ({r[0] for r in 遮.execute("SELECT name FROM wearer WHERE name IS NOT NULL")}
                                  & {r[0] for r in 真.execute("SELECT name FROM wearer WHERE name IS NOT NULL")}))
真.close(); 遮.close()

# ② 真起一个工具服务
def 问服务(env_db):
    env = dict(os.environ, LANXIU_ME=json.dumps({"no": "60000008", "name": "检查", "role": "总部运营", "shop": ""}))
    env.pop("LANXIU_DB", None)
    if env_db:
        env["LANXIU_DB"] = env_db
    请 = "\n".join(json.dumps(x) for x in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_customer", "arguments": {"customer_id": "C21000"}}},
    ]) + "\n"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "task_server.py")], input=请, capture_output=True,
                       text=True, env=env, timeout=60)
    for l in p.stdout.splitlines():
        try:
            m = json.loads(l)
        except Exception:
            continue
        if m.get("id") == 2:
            return json.dumps(m, ensure_ascii=False)
    return p.stderr[-300:]

凭证 = os.path.join(os.path.dirname(副), "副本生效.txt")
回 = 问服务(副)
真名 = sqlite3.connect(os.path.join(HERE, "lanxiu.db")).execute("SELECT name FROM customer WHERE id='C21000'").fetchone()[0]
ck("真起一个工具服务、给它副本:查客户拿到的是代号,并且留了「副本生效」凭证",
   "姓名#" in 回 and 真名 not in 回 and os.path.exists(凭证), 回[:160])
回2 = 问服务(None)
ck("不给副本时工具服务照旧读真库(什么都不改)", 真名 in 回2 and "姓名#" not in 回2, 回2[:160])
shutil.rmtree(os.path.dirname(副), ignore_errors=True)
sd = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
ck("智能体拉起工具服务时显式带上 LANXIU_DB(不指望继承)", 'env = {**env, "LANXIU_DB": os.environ["LANXIU_DB"]}' in sd)

# ③ 试跑命令
tr = open(os.path.join(ROOT, "agentsite", "trial_run.py"), encoding="utf-8").read()
ck("试跑:每条跑完核凭证,没有就停、这一条不存", "if not os.path.exists(凭证):" in tr
   and tr.index("if not os.path.exists(凭证):") < tr.index("TT.存(批"))
p = subprocess.run([sys.executable, os.path.join(ROOT, "agentsite", "trial_run.py"), "--版本", "当前"], capture_output=True, text=True)
ck("试跑:参数不全拒跑(不会悄悄挑一批去跑)", p.returncode != 0)

# ④ 对比
import check_copy
db = check_copy.用副本("trial-chk-")
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
样 = c.execute("""SELECT tr.task_id, tr.case_id, u.root_cause FROM triage tr JOIN truth u ON u.case_id=tr.case_id
                 JOIN task t ON t.id=tr.task_id WHERE t.type='售后判责' ORDER BY tr.id LIMIT 1""").fetchone()
c.close()
if not 样:
    ck("库里有一条能对上标准答案的售后研判 —— 没有就没验,不算通过", False)
else:
    TT.存("检查批", 样["task_id"], "研判:x·系统:y", f"根因:{样['root_cause']}\n建议动作:按判定表\n证据:无", [], 0, "检查", db=db)
    TT.存("检查批", 样["task_id"], "研判:x·系统:y", "", [], None, "检查", error="ResultError: 403", db=db)
    o = TT.对比("检查批", db=db)
    ck("对比:跑挂了的单独数,不算答错", o["汇总"]["跑挂"] == 1 and o["汇总"]["可比"] == 1, o["汇总"])
    ck("对比:用评测的判分函数算对错(照标准答案写的草稿判对)", o["行"][0]["试版"]["对"] is True, o["行"][0])
服 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
段 = 服[服.index('if p=="/api/triage-compare":'):]; 段 = 段[:段.index('if p=="/api/triage-board":')]
ck("对比接口要登录、只给总部运营和店长", "请先登录" in 段 and "_tb.全部可见 + _tb.本店可见" in 段)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 隔离试运行:遮干净、同值同代号、工具服务真改读副本、没凭证就停、对比不把跑挂算答错(验了 {n} 条){D}")
