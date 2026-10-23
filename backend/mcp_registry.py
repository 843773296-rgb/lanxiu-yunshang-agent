# -*- coding: utf-8 -*-
"""MCP 服务与工具管理:总览、体检、三个可配的开关(用户 2026-10-23 拍「做,带配置」)。

外部《MCP 与 Skill 现状核查及建设方案》6.1 列了七个配置区域。**页面上能改的只开三样**,其余只读:

    能改   启用 / 停用某个工具 · 单次调用超时(秒)· 每分钟最多调几次
    只读   服务、工具目录(归哪个领域、读还是写、哪些角色挂着)、最近调用和报错
    不开   身份传递、写入审批、幂等、权限 —— 这些是写口里的业务规则(写入判定、状态机、两人复核),
           页面上一次误配就能让一个人绕过「两个人把关」;改它们走代码提交。同 triage_config 的取舍

**开关在协议层生效**(mcp/protocol.Server):停用的工具 tools/list 不列、tools/call 拒;
超时到点返回错误;超过限流返回错误。三样都只能让工具**更少、更慢地**被用 —— 页面上没有一个开关能放大权限。
没登记过的工具 = 启用、不限时、不限流,和原来一模一样。

⚠️ 超时是「不等了」,不是「停下来」:Python 线程杀不掉,超时那次调用会在后台跑完。
所以只读工具才适合靠它兜住;写工具超时返回错误时**写可能已经落库** —— 返回里写明这一点。
"""
import collections
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DB = os.path.join(HERE, "lanxiu.db")

可编辑角色 = ("总部运营",)
超时范围 = (1, 600)        # 秒
限流范围 = (1, 600)        # 次 / 分钟


def _now():
    import ops
    return ops.now().strftime("%Y-%m-%d %H:%M:%S")


def 确保表(c):
    c.execute("""CREATE TABLE IF NOT EXISTS mcp_tool_cfg(
        name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, timeout_s INTEGER, rate_per_min INTEGER,
        version INTEGER NOT NULL DEFAULT 0, updated TEXT, updated_by TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mcp_tool_cfg_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, before TEXT, after TEXT, why TEXT,
        by_no TEXT, by_name TEXT, at TEXT)""")


def 配置(db=None):
    """→ {工具: {启用, 超时, 限流}}。**只读连接;读不到就是空**(= 全部启用、不限时不限流,和原来一样)。
    协议层每几秒读一次,所以这里不能建表、不能写。"""
    try:
        with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True, timeout=3)) as c:
            return {r[0]: dict(启用=bool(r[1]), 超时=r[2], 限流=r[3])
                    for r in c.execute("SELECT name, enabled, timeout_s, rate_per_min FROM mcp_tool_cfg")}
    except sqlite3.Error:
        return {}


# ── 总览 ────────────────────────────────────────────────────────────
def _全部工具():
    import api
    return [s["name"] for s in api.SCHEMAS + api.SHOP_SCHEMAS + api.KB_SCHEMAS]


_角色缓存 = {"mtime": None, "值": None}


def 角色挂载():
    """{工具: [挂着它的角色]} —— **现算**,用运维平台的 venv 去问 sdk(后台这边是系统 python,载不进 sdk)。
    按 sdk.py 的修改时间缓存;问不到就返回 None,页面明说「这一栏取不到」,不拿旧快照顶。"""
    sdk = os.path.join(ROOT, "agentsite", "sdk.py")
    py = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
    try:
        mt = os.path.getmtime(sdk)
    except OSError:
        return None
    if _角色缓存["mtime"] == mt:
        return _角色缓存["值"]
    码 = ("import sys,json;sys.path.insert(0,'agentsite');import sdk;"
          "print(json.dumps({k:sorted({t.split('__',2)[2] for t in sdk._tools_for(k) if t.startswith('mcp__')})"
          " for k in sdk._ROLE_TOOLS},ensure_ascii=False))")
    try:
        r = subprocess.run([py, "-c", 码], cwd=ROOT, capture_output=True, text=True, timeout=60)
        按角色 = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    out = collections.defaultdict(list)
    for 角, ts in 按角色.items():
        for t in ts:
            out[t].append(角)
    _角色缓存.update(mtime=mt, 值=dict(out))
    return _角色缓存["值"]


def 最近调用(尾=6 * 1024 * 1024):
    """读调用记录(.feynman/spans.jsonl)的**最后 6MB**:每个工具调了几次、平均多久、报错几次、最后一次。
    只看尾巴 —— 整个文件几十 MB,每次打开页面全扫一遍不值;页面上写明「最近一段」。"""
    p = os.path.join(ROOT, ".feynman", "spans.jsonl")
    统 = collections.defaultdict(lambda: dict(次数=0, 报错=0, 耗时=[], 最近=None))
    try:
        with open(p, "rb") as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 尾))
            块 = f.read().decode("utf-8", "ignore").splitlines()[1:]
    except OSError:
        return {}
    for l in 块:
        if '"execute_tool' not in l:
            continue
        try:
            r = json.loads(l)
        except ValueError:
            continue
        a = r.get("attr") or {}
        t = (a.get("gen_ai.tool.name") or "").rsplit("__", 1)[-1]
        if not t:
            continue
        s = 统[t]; s["次数"] += 1
        if a.get("error.type") or str(a.get("gen_ai.tool.call.result") or "").startswith(("参数不对", "没有名为")):
            s["报错"] += 1
        if r.get("end") and r.get("start"):
            s["耗时"].append((r["end"] - r["start"]) * 1000)
        s["最近"] = r.get("start")
    out = {}
    for t, s in 统.items():
        out[t] = dict(次数=s["次数"], 报错=s["报错"],
                      平均毫秒=round(sum(s["耗时"]) / len(s["耗时"])) if s["耗时"] else None,
                      最近=time.strftime("%m-%d %H:%M", time.localtime(s["最近"])) if s["最近"] else None)
    return out


def 总览(db=None):
    import api, domains
    配 = 配置(db)
    角 = 角色挂载()
    用 = 最近调用()
    工具们 = []
    for t in _全部工具():
        c = 配.get(t) or {}
        工具们.append(dict(
            名称=t, 领域=domains.归属.get(t), 领域名=domains.领域说明.get(domains.归属.get(t)),
            读写="写" if t in api.WRITE_TOOLS else "读", 启用=c.get("启用", True),
            超时=c.get("超时"), 限流=c.get("限流"),
            角色=(角 or {}).get(t, []) if 角 is not None else None, 使用=用.get(t)))
    服务们 = [dict(领域=d, 名=domains.领域说明[d], 工具数=len(ts),
                  停用=sum(1 for t in ts if not (配.get(t) or {}).get("启用", True)))
             for d, ts in domains.领域.items()]
    return dict(服务=服务们, 工具=工具们, 角色取得到=角 is not None,
                说明="调用和报错只看调用记录最近一段;角色那一栏是现算的(问运维平台的 sdk),取不到时明说")


def 体检():
    """真起一遍八个服务:握手、列工具。**不调任何工具**(体检不该有副作用)。"""
    import domains
    out = []
    for d in domains.领域:
        t0 = time.time()
        try:
            p = subprocess.run(
                [sys.executable, os.path.join(ROOT, "mcp", "domain_server.py"), d], cwd=ROOT,
                input="\n".join(json.dumps(x) for x in (
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "体检", "version": "0"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n",
                capture_output=True, text=True, timeout=30)
            行 = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
            名 = next((x["result"]["serverInfo"]["name"] for x in 行 if x.get("id") == 1), None)
            列 = next((x["result"]["tools"] for x in 行 if x.get("id") == 2), None)
            out.append(dict(领域=d, 起得来=bool(名), 服务名=名, 列出工具=len(列 or []),
                            应有=len(domains.领域[d]), 毫秒=round((time.time() - t0) * 1000)))
        except Exception as e:
            out.append(dict(领域=d, 起得来=False, 错误=f"{type(e).__name__}: {e}"[:120]))
    return out


# ── 写 ──────────────────────────────────────────────────────────────
def 改工具(name, 启用, 超时, 限流, 理由, 我, db=None):
    if not 我 or not 我.get("no"):
        return dict(ok=False, reason="没登录 —— 改工具配置要登录,署名用登录的人")
    if 我.get("role") not in 可编辑角色:
        return dict(ok=False, reason=f"只有{'/'.join(可编辑角色)}能改工具配置,你是{我.get('role')}")
    if name not in _全部工具():
        return dict(ok=False, reason=f"没有这个工具:{name}")
    if not (理由 or "").strip():
        return dict(ok=False, reason="改工具配置要写理由 —— 以后有人问「这个工具怎么调不动了」,答案在这里")

    def _数(v, 范, 名):
        if v in (None, "", "不限"):
            return None, None
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None, f"{名}要填整数"
        if not 范[0] <= v <= 范[1]:
            return None, f"{名}只能在 {范[0]}–{范[1]} 之间(不限就留空)"
        return v, None
    t, e1 = _数(超时, 超时范围, "超时(秒)")
    r, e2 = _数(限流, 限流范围, "每分钟次数")
    if e1 or e2:
        return dict(ok=False, reason=e1 or e2)
    新 = dict(启用=bool(启用), 超时=t, 限流=r)
    with closing(sqlite3.connect(db or DB, timeout=10)) as c:
        确保表(c)
        旧行 = c.execute("SELECT enabled, timeout_s, rate_per_min FROM mcp_tool_cfg WHERE name=?", (name,)).fetchone()
        旧 = dict(启用=bool(旧行[0]), 超时=旧行[1], 限流=旧行[2]) if 旧行 else dict(启用=True, 超时=None, 限流=None)
        if 旧 == 新:
            return dict(ok=False, reason="和现在一样,没有要改的")
        c.execute("""INSERT INTO mcp_tool_cfg(name,enabled,timeout_s,rate_per_min,version,updated,updated_by)
                     VALUES(?,?,?,?,1,?,?) ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled,
                     timeout_s=excluded.timeout_s, rate_per_min=excluded.rate_per_min, version=version+1,
                     updated=excluded.updated, updated_by=excluded.updated_by""",
                  (name, int(新["启用"]), t, r, _now(), 我["name"]))
        c.execute("INSERT INTO mcp_tool_cfg_log(name,before,after,why,by_no,by_name,at) VALUES(?,?,?,?,?,?,?)",
                  (name, json.dumps(旧, ensure_ascii=False), json.dumps(新, ensure_ascii=False),
                   理由.strip(), 我["no"], 我["name"], _now()))
        c.commit()
    return dict(ok=True, 从=旧, 到=新, 生效="新开的对话立即生效;已经开着的对话最多 5 秒内跟上")


def 改动记录(name=None, db=None, n=50):
    try:
        with closing(sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True, timeout=3)) as c:
            c.row_factory = sqlite3.Row
            q = "SELECT name,before,after,why,by_name,at FROM mcp_tool_cfg_log"
            rs = c.execute(q + (" WHERE name=?" if name else "") + " ORDER BY id DESC LIMIT ?",
                           ((name, n) if name else (n,))).fetchall()
            return [dict(x) for x in rs]
    except sqlite3.Error:
        return []
