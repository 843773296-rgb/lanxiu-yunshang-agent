# -*- coding: utf-8 -*-
"""音频整理全流程 · 两边真接起来(2026-10-24)—— 管理后台真服务 + 澜绣真的 supervise_sync 那一半。

管理后台那边的端到端(`管理后台/tests/e2e/test_audio_flow.py`)里,澜绣是**测试扮演的**;
澜绣这边的 `backend/workflow_bridge_check.py` 里,管理后台是**不存在的**。
两份各自绿,不等于接得上 —— 字段名、状态值、回执形状任何一处对不上,两边都还是绿的。
这一份把两半真的接起来跑一遍:

  管理后台建「音频整理」→ 发起(通话号 + 这通录音的真客户)
  → **supervise_sync.跑桥** 拉单、用 workflow_bridge 取真转写、回执
  → 管理后台停在人工核对,待办里的原文 == 库里这通录音的转写
  → 批准(改定稿)→ 跑桥写跟进 → 运行成功,副本里多了**一条**内容是定稿的跟进
  → 再跑一次桥:没有待执行的单,跟进仍是一条

澜绣的库用**副本**(写跟进真写)。管理后台没起 → 明说「不适用,不是通过」,退出码 0(不进门禁的随机拦路)。
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "agent"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "tools")]
import server, oplog, workflow_bridge as WB   # noqa: E401 —— 先加载写口,用副本才改得到
import check_copy

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
WK = os.path.join(ROOT, "管理后台", "workers", "worker.py")
WPY = os.path.join(ROOT, "管理后台", ".venv", "bin", "python")
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("supervise_sync 执行了却不回执", "运行接着走,停在人工核对"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


def 打(方法, 路, 谁="U002", 体=None, 头=None):
    req = urllib.request.Request(基址 + 路, method=方法, data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 等到(rid, 想要, 最多=8):
    """有管理后台的 venv 就自己跑一轮 worker;没有(比如咬合在工作区副本里跑)就等常驻的那个 worker ——
    ⚠️ 原来没有 venv 就整条判「不适用」,于是咬合在副本里跑时这条检查**什么都没验就退 0**,读起来像「没红」。"""
    for _ in range(最多 * (1 if os.path.exists(WPY) else 6)):
        c, r = 打("GET", P + f"/execution-runs/{rid}", "U004")
        if (r or {}).get("执行状态") in 想要:
            return r["执行状态"]
        if os.path.exists(WPY):
            subprocess.run([WPY, WK, "--一轮"], capture_output=True, text=True, timeout=180,
                           cwd=os.path.join(ROOT, "管理后台"))
        else:
            time.sleep(1.5)
    return (打("GET", P + f"/execution-runs/{rid}", "U004")[1] or {}).get("执行状态")


def main():
    print("音频整理全流程 · 管理后台真服务 + 澜绣 supervise_sync 真跑桥")
    print("=" * 80)
    try:
        urllib.request.urlopen(基址 + "/", timeout=3)
    except Exception as e:
        print(f"⏸ 管理后台({基址})没起 —— **不适用,不是通过**:{type(e).__name__}")
        return 0
    副本 = check_copy.用副本("audio-live-")
    ck("夹具:写口都指到了副本", os.path.realpath(server.DB) == os.path.realpath(副本) == os.path.realpath(WB.DB))
    c = sqlite3.connect(副本)
    call, cust, 原文 = c.execute("""SELECT a.id, a.customer_id, t.text FROM call_audio a
                                     JOIN call_transcript t ON t.audio_id=a.id
                                     JOIN customer cu ON cu.id=a.customer_id ORDER BY a.id LIMIT 1""").fetchone()
    c.close()
    import supervise_sync as SS
    cfg = {"地址": 基址, "项目": 项目, "工号": "U004"}

    c1, w = 打("POST", P + "/workflows", 体={"名称": f"两边真接 {uuid.uuid4().hex[:6]}", "模板": "音频整理"})
    c2, d = 打("GET", P + f"/workflows/{w['id']}")
    定义 = d["草稿"]["定义"]
    for nd in 定义["nodes"]:
        if nd["type"] == "llm":
            nd["config"].update(connection_version_id="cv_mock_" + 项目, prompt_version_id="pv_seed_article_summary")
    打("PATCH", P + f"/workflows/{w['id']}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c3, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
              体={"workflow_id": w["id"], "输入": {"call_id": call, "customer_id": cust}})
    ck("发起运行 202", c3 == 202, (c3, r))
    # ⚠️ **`ck()` 只记一笔,它不中断** —— 这正是「打印 ❌ 和拦截是两件事」。
    # 2026-10-28 撞上:管理后台回 422(`intent.config.connec…` 有一处没配好),
    # 于是 `r` 里没有 resource_id,下一行 `KeyError`,
    # 而门禁把它算进「**崩了 1 条**」而不是「判定不过 1 条」——
    # 崩了的那条**一条都没验过**,两者处置完全不同。
    # > 一个「流程跑挂了」和一个「流程没被允许开始、而代码没检查这件事」,
    # > **在那个 KeyError 上长得一模一样** —— 堆栈指向 resource_id,
    # > 而真正的信息在上一行的 422 里。
    if c3 != 202 or not isinstance(r, dict) or "resource_id" not in r:
        _因 = ""
        if isinstance(r, dict):
            _因 = str(r.get("message") or r.get("code") or "")[:120]
            _场 = r.get("field_errors") or {}
            if _场:
                _因 += f" · 没配好的:{list(_场)[:3]}"
        print(f"  ⏸ 管理后台没让这次运行开始(HTTP {c3}){(' —— ' + _因) if _因 else ''}")
        print(f"     **这不是流程挂了,是它没被允许开始** —— 先把那处配置配好再跑这条检查")
        return 1 if 坏 else 0
    rid = r["resource_id"]
    ck("停在取转写等澜绣", 等到(rid, ("waiting_external", "failed")) == "waiting_external")

    张, 错 = SS.跑桥(cfg)
    ck("supervise_sync 跑桥:拉到单并回执(没报错)", 张 >= 1 and not 错, (张, 错))
    ck("运行接着走,停在人工核对", 等到(rid, ("waiting_approval", "failed")) == "waiting_approval")
    c4, b = 打("GET", P + "/human-requests?status=pending&limit=200", "U006")
    hs = [x for x in (b or {}).get("items") or [] if x.get("execution_run_id") == rid]
    c5, det = 打("GET", P + f"/human-requests/{hs[0]['id']}", "U006") if hs else (0, {})
    看 = (det or {}).get("核对材料") or {}
    ck("待办里的原文就是库里这通录音的转写(审核人能看全文 / 至少开头对得上)",
       原文[:40] in str(看.get("原文")), (原文[:40], str(看.get("原文"))[:80]))
    定稿 = f"两边真接:{call} 的需求已核(检查写的)"
    # 账号绑定(10-24):写跟进以**批准核对的人绑定的澜绣员工**名义记台账,没绑就不写 —— 这里临时给 U006 绑一个,跑完解绑
    打("DELETE", P + "/staff-bindings/U006", "U001")
    cb, bb = 打("PUT", P + "/staff-bindings/U006", "U001", 体={"澜绣工号": "60000001", "备注": "两边真接检查,跑完解绑"})
    ck("夹具:给核对人 U006 临时绑上澜绣工号 60000001", cb == 200, (cb, bb))
    c6, b = 打("POST", P + f"/human-requests/{hs[0]['id']}/decisions", "U006",
              体={"decision": "approved", "request_revision": det["请求"]["revision"], "edits": {"定稿": 定稿}},
              头={"Idempotency-Key": str(uuid.uuid4())})
    ck("批准记下", c6 == 201, (c6, b))
    ck("停在写跟进等澜绣", 等到(rid, ("waiting_external", "failed")) == "waiting_external")
    前 = sqlite3.connect(副本).execute("SELECT COUNT(*) FROM followup WHERE customer_id=?", (cust,)).fetchone()[0]
    张, 错 = SS.跑桥(cfg)
    ck("跑桥写跟进(没报错)", 张 >= 1 and not 错, (张, 错))
    ck("运行成功", 等到(rid, ("succeeded", "failed", "incomplete")) == "succeeded")
    行 = sqlite3.connect(副本).execute("SELECT id, content FROM followup WHERE customer_id=? AND content=?",
                                     (cust, 定稿)).fetchall()
    ck("副本里多了**一条**跟进,内容是人改过的定稿", len(行) == 1, 行)
    账 = sqlite3.connect(副本).execute("SELECT actor FROM op_log WHERE machine='followup' AND code='CREATE' AND target=?",
                                       (行[0][0] if 行 else "",)).fetchone()
    ck("**台账以核对人绑定的员工名义记(60000001),管理后台账号 U006 一起记上**",
       bool(账) and "60000001" in 账[0] and "U006" in 账[0], 账)
    打("DELETE", P + "/staff-bindings/U006", "U001")
    张, 错 = SS.跑桥(cfg)
    后 = sqlite3.connect(副本).execute("SELECT COUNT(*) FROM followup WHERE customer_id=?", (cust,)).fetchone()[0]
    ck("再跑一次桥:跟进仍只多一条(没有待执行的单 / 重复也不写)", 后 == 前 + 1, (前, 后))
    c7, rr = 打("GET", P + f"/execution-runs/{rid}", "U004")
    ck("运行输出里带着澜绣回来的跟进号", 行 and 行[0][0] in json.dumps(rr, ensure_ascii=False), 行)
    ck("真库没被写:真库里没有这条定稿",
       sqlite3.connect(check_copy.真库).execute("SELECT COUNT(*) FROM followup WHERE content=?", (定稿,)).fetchone()[0] == 0)

    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 两边真接起来了:取真转写 → 人工核对 → 写一条跟进,重跑不写第二条(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
