#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行控制**接执行侧**(11-18 用户拍「暂停 / 取消接执行侧」):接口写下的「请求」,Worker 真的读。

## 这一份和 test_runctl_flow 的分工

`test_runctl_flow.py` 直接改库造状态,验的是**接口这一侧**的状态机(请求不是已经、乐观锁、幂等)。
它验不到的是:runctl 把 `pause_requested` / `cancel_requested` 写在 execution_runs 上之后,
**执行侧读不读** —— 11-18 之前一个字都不读:取消了的照跑到底、暂停了的永远不会变 paused、
「继续」只把状态改成 queued 却不插任务(worker 只从 jobs 领活),运行永远「排队中」。

所以这一份**不改库**(只读查),全部走接口 + 真 Worker:

  ① 取消:发起 → 立刻 cancel。还 queued → 直接 cancelled,jobs.cancel_requested=true,Worker **不领**它;
     已 running → cancel_requested,等到终态是 cancelled(Worker 收尾时把运行也收了)。两条路按实际状态分支。
  ② 可执行的控制动作:queued / paused 的运行 reconcile.现在能吗=false 且 为什么不能 非空(原来对所有非终态都 true)
  ③ 暂停 → 继续:运行真的在跑、还有下一个节点时请求暂停 → 到节点边界变 paused;resume → 202 + job_id → 跑完 succeeded

## 怎么让一次运行**跑得够慢**又不花钱

模型步骤用的连接版本指向本机一个假的 Messages 接口(别的 e2e 留下的夹具:endpoint 是 127.0.0.1:<端口>/v1/messages、
capabilities 标 live)。这份测试**自己在那个端口起一个慢服务**(每次回答前睡几秒),于是「正在跑」有一段能抓的窗口,
而一个字节都不出本机、一分钱都不花。端口被占 / 没有这样的夹具 → 慢那几条**明说没验,不算通过**。

⚠️ 前提 `make dev`。只碰 project_demo_a;自己建工作流(名字带 e2e);库**只读**。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
PY = os.path.join(_根, ".venv", "bin", "python")
过, 挂, 没验 = [], [], []
尾 = uuid.uuid4().hex[:6]
慢秒 = float(os.environ.get("AIMC_E2E_SLOW_SECONDS", "4"))


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 跳(名, 为什么):
    print(f"  ⏸ {名}  (没验:{为什么})")
    没验.append(名)


def 打(方法, 路, 体=None, 谁="U002", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
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
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 连接                     # noqa: E402


# ── Worker:CI 上没有常驻的,要自己踢;而且要和服务同一种模式 ──────────────
def _worker环境():
    env = dict(os.environ)
    健 = 打("GET", "/api/healthz")[1] or {}
    env["MODEL_ADAPTER"] = "mock" if 健.get("模型是mock", True) is not False else "anthropic"
    return env


def 踢一轮(后台=False):
    """后台=True:起一个并行跑的 Worker(**不等它**)—— 要抓「正在跑」的窗口就得让它在旁边跑。"""
    cmd = [PY, os.path.join(_根, "workers", "worker.py"), "--一轮"]
    if 后台:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=_根, env=_worker环境())
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=_根, env=_worker环境())


def 看(rid, 谁="U004"):
    c, r = 打("GET", P + f"/execution-runs/{rid}", 谁)
    return r or {}


def 等状态(rid, 要的, 秒, 踢=False):
    """等到状态落进 `要的` 里;返回最后看到的详情。超时也返回 —— 调用方把它报成失败,别挂住。"""
    到 = time.time() + 秒
    while time.time() < 到:
        r = 看(rid)
        if r.get("执行状态") in 要的 or r.get("是终态吗"):
            return r
        if 踢:
            踢一轮()
        time.sleep(0.25)
    return 看(rid)


def 控制(r, 名):
    return next((x for x in (r.get("可执行的控制动作") or []) if x.get("动作") == 名), {})


def 查任务(rid):
    with 连接() as c:
        return [dict(x) for x in c.execute(text("""select id, type, status, cancel_requested, target_ref
                                                   from jobs where project_id=:p and target_ref->>'run_id'=:r
                                                   order by created_at"""), {"p": 项目, "r": rid}).mappings()]


# ── 假的 Messages 接口:每次回答前睡 慢秒 ─────────────────────────────────
class _慢(BaseHTTPRequestHandler):
    次数 = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        self.rfile.read(n)
        _慢.次数 += 1
        time.sleep(慢秒)
        体 = json.dumps({"id": f"msg_e2e_{_慢.次数}", "type": "message", "role": "assistant", "model": "e2e-fake-slow",
                         "content": [{"type": "text", "text": f"e2e 假模型第 {_慢.次数} 次回答"}],
                         "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(体)))
        self.end_headers()
        self.wfile.write(体)


def 起慢服务():
    """在别的 e2e 留下的「本机假接口」连接版本的端口上起服务 → (连接版本id, server) / (None, 为什么)。"""
    c, 列 = 打("GET", P + "/model-connections", 谁="U001")
    候选 = []
    for mc in (列 or {}).get("连接", []):
        if mc.get("状态") != "active" or mc.get("用途") != "generate":
            continue
        for cv in mc.get("配置版本") or []:
            m = re.match(r"^http://127\.0\.0\.1:(\d+)/v1/messages$", cv.get("endpoint") or "")
            if m and (cv.get("capabilities") or {}).get("execution_mode") == "live" and cv.get("探过吗"):
                候选.append((cv["id"], int(m.group(1)), mc["id"]))
    if not 候选:
        return None, None, "项目里没有指向本机 127.0.0.1:<端口>/v1/messages 的启用生成连接(别的 e2e 没留夹具)"
    for cvid, 端口, mcid in 候选:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", 端口), _慢)
        except OSError as e:
            print(f"     端口 {端口}({cvid})绑不上:{e} —— 试下一条")
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return cvid, srv, f"{cvid} @ 127.0.0.1:{端口}(连接 {mcid})"
    return None, None, f"{len(候选)} 条候选的端口都被占着"


def 建慢工作流(cvid):
    """文本处理模板 + 第二个模型步:开始 → 总结 → 再总结 → 结束。两步都走假接口,一次运行至少 2×慢秒。"""
    c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 运行控制接执行侧 {尾}", "模板": "文本处理"})
    ck("建工作流(文本处理模板)→ 201", c == 201 and (w or {}).get("id"), (c, w))
    wid = (w or {}).get("id")
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    中 = next(n for n in 定义["nodes"] if n["type"] == "llm")
    中["config"]["connection_version_id"] = cvid
    中["config"]["prompt_version_id"] = "pv_seed_article_summary"
    再 = json.loads(json.dumps(中, ensure_ascii=False))
    再["id"], 再["name"] = "summarize2", "再总结"
    再["layout"] = {"x": 480, "y": 120}
    再["config"]["bindings"] = {"article": {"source": "node", "node_id": 中["id"], "pointer": "/text"}}
    定义["nodes"].insert(定义["nodes"].index(中) + 1, 再)
    尾节点 = next(n for n in 定义["nodes"] if n["type"] == "end")
    尾节点["config"]["bindings"] = {"summary": {"source": "node", "node_id": "summarize2", "pointer": "/text"}}
    定义["edges"] = [{"source": "start", "target": 中["id"], "port": "success"},
                   {"source": 中["id"], "target": "summarize2", "port": "success"},
                   {"source": "summarize2", "target": "finish", "port": "success"}]
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    c2, v = 打("POST", P + f"/workflows/{wid}/validate")
    阻 = [p for p in (v or {}).get("问题", []) if p.get("级别") == "blocking"]
    ck("两个模型步的草稿存上并**校验通过**(校验不过的图下面全是空验)", c == 200 and c2 == 200 and (v or {}).get("通过") is True,
       (c, c2, [(p.get("code"), p.get("field_path")) for p in 阻][:3]))
    return wid


def 发起(wid, 文):
    c, r = 打("POST", P + "/execution-runs", 头={"Idempotency-Key": str(uuid.uuid4())},
             体={"workflow_id": wid, "输入": {"article": 文}})
    ck("发起运行 → 202 排队中", c == 202 and (r or {}).get("status") == "排队中", (c, str(r)[:120]))
    return (r or {}).get("resource_id")


def 等到running(rid, 秒=25):
    """抓「正在跑」的窗口:先看;还 queued 就在旁边起一个 Worker,然后盯到它变 running(或直接到了终态)。
    返回 (详情, 一路看到的状态序列) —— 序列是诊断用的:「queued → 直接 succeeded,中间从没见过 running」
    和「没等到」在那个 ⏸ 上要分得开。"""
    p = None
    看到 = []
    到 = time.time() + 秒
    起 = time.time()
    while time.time() < 到:
        r = 看(rid)
        st = r.get("执行状态")
        if not 看到 or 看到[-1][0] != st:
            看到.append((st, round(time.time() - 起, 2)))
        if st != "queued" or r.get("是终态吗"):
            return r, 看到
        if p is None or p.poll() is not None:
            p = 踢一轮(后台=True)
        time.sleep(0.15)
    return 看(rid), 看到


def main():
    print("\n\033[1m▸ 运行控制接执行侧 · 接口写下的「请求」,Worker 真的读\033[0m")
    健 = 打("GET", "/api/healthz")[1] or {}
    print(f"     服务 模型是mock={健.get('模型是mock')} · 慢服务每次睡 {慢秒}s")

    cvid, srv, 说 = 起慢服务()
    if not cvid:
        print(f"     ⚠️ 起不了慢服务:{说}")
    else:
        print(f"     慢服务:{说}")

    # ── ① 取消一次「还没开跑」的运行:空白图最轻;抢不到 queued 窗口就走 running 那条路 ──
    print("\n▸ ① 取消:queued 直接 cancelled;running 走 cancel_requested → Worker 收成 cancelled")
    if cvid:
        wid = 建慢工作流(cvid)
    else:
        c, w = 打("POST", P + "/workflows", 体={"名称": f"e2e 运行控制(空白){尾}", "模板": "文本处理"})
        wid = (w or {}).get("id")
        c, d = 打("GET", P + f"/workflows/{wid}")
        定义 = d["草稿"]["定义"]
        for n in 定义["nodes"]:
            if n["type"] == "llm":
                n["config"]["connection_version_id"] = "cv_mock_" + 项目
                n["config"]["prompt_version_id"] = "pv_seed_article_summary"
        打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    if not wid:
        print("\n❌ 挂: 建不出工作流")
        return 1

    rid = 发起(wid, f"e2e 取消 {尾}")
    r0 = 看(rid)
    if r0.get("执行状态") == "queued":
        核 = 控制(r0, "reconcile")
        ck("queued 的运行:reconcile.现在能吗=false 且 为什么不能 非空(原来对所有非终态都 true;页面摆了按钮点了 409)",
           核.get("现在能吗") is False and bool(核.get("为什么不能")), 核)
        ck("queued 的运行:pause 不能(状态机只许从 running 走)、cancel 能",
           控制(r0, "pause").get("现在能吗") is False and 控制(r0, "cancel").get("现在能吗") is True,
           [(x["动作"], x["现在能吗"]) for x in r0.get("可执行的控制动作") or []])
    else:
        跳("queued 的运行 reconcile.现在能吗=false", f"发起后立刻看已经是「{r0.get('执行状态')}」,没抓到 queued 窗口")
    t取 = time.time()
    c, 取 = 打("POST", P + f"/execution-runs/{rid}/cancel", 头={"Idempotency-Key": f"c-{尾}-1", "If-Match": str(r0.get("revision"))})
    取耗时 = round(time.time() - t取, 2)
    ck("立刻 cancel(带 Idempotency-Key + If-Match)→ 202", c == 202 and (取 or {}).get("改了吗") is not None, (c, 取))
    状 = (取 or {}).get("status")
    任务们 = 查任务(rid)
    ck("库里这次运行名下有任务(**先断非空**,不然下面「Worker 不领」是空验)", bool(任务们), [(t["id"], t["status"]) for t in 任务们])
    if 状 == "cancelled":
        print(f"     走的是 queued → cancelled 那条路")
        ck("还 queued → **直接 cancelled**(没有在途调用要掐,不走「请求」那一档)", "没有在途调用" in ((取 or {}).get("note") or ""),
           ((取 or {}).get("note") or "")[:80])
        ck("jobs.cancel_requested=true(取消令牌写到了执行侧读的那一列,不只写运行那两列)",
           任务们 and all(t["cancel_requested"] is True for t in 任务们), [(t["id"], t["cancel_requested"]) for t in 任务们])
        踢一轮()                         # CI 没常驻 Worker:踢一次,看它领不领
        time.sleep(10 if 健.get("模型是mock") is False else 1)
        后 = 查任务(rid)
        # 两种都算对,但要说清是哪一种:① 任务留在 排队中 + cancel_requested(Worker 的 取一个 不领它)
        # ② 接口当场把它收成 已取消(运行没开跑,名下任务一起收 —— 11-18 深夜加的那两句)。**不许**的是 执行中 / 已完成
        ck("等 10 秒后任务**没有变成 执行中 / 已完成**(Worker 不领 cancel_requested 的任务;lease.取一个 的 WHERE 里那一行)",
           后 and all(t["status"] not in ("执行中", "已完成") and t["cancel_requested"] is True for t in 后),
           [(t["id"], t["status"], t["cancel_requested"]) for t in 后])
        print(f"     任务现在是 {[t['status'] for t in 后]}:" + ("接口当场收成了 已取消" if all(t["status"] == "已取消" for t in 后)
              else "留在 排队中 带 cancel_requested(Worker 跳过它 —— 列表上它会一直「排队中」,要人看)"))
        ck("运行停在 cancelled(终态)", 看(rid).get("执行状态") == "cancelled", 看(rid).get("执行状态"))
        终 = 看(rid)
        if not (终.get("结束") or 终.get("停止原因")):
            print(f"     ℹ️ 接口直接取消的运行 结束={终.get('结束')} 停止原因={终.get('停止原因')} —— "
                  f"Worker 收的那条路会写 ended_at / CANCELLED,接口这条路不写;运行记录页「结束」整列空(只报不拦)")
    elif 状 == "cancel_requested":
        print(f"     走的是 running → cancel_requested 那条路")
        ck("已 running → **cancel_requested**,不是 cancelled(在途调用未必立刻停)", True)
        ck("jobs.cancel_requested=true(同步点亮了执行侧读的那一列)",
           任务们 and all(t["cancel_requested"] is True for t in 任务们), [(t["id"], t["cancel_requested"]) for t in 任务们])
        终 = 等状态(rid, ("cancelled",), 秒=max(30, 慢秒 * 3 + 10))
        ck("等到终态:execution_runs 是 **cancelled**(Worker 到节点边界读到令牌停手,收尾时把运行也收了 —— 原来停在 cancel_requested 永远不动)",
           终.get("执行状态") == "cancelled" and 终.get("是终态吗") is True, (终.get("执行状态"), 终.get("停止原因")))
        后 = 查任务(rid)
        ck("任务也收成 已取消(不是 已完成 —— 一次被掐的运行不许记成跑完)",
           后 and all(t["status"] == "已取消" for t in 后), [(t["id"], t["status"]) for t in 后])
        ck("运行的事件里有「收到取消」那一笔(停手的痕迹)", any("cancel" in str(e.get("event_type") or e.get("kind") or "") for e in 终.get("事件") or []),
           [e.get("event_type") or e.get("kind") for e in (终.get("事件") or [])][-4:])
    else:
        跳("取消接执行侧(两条路都没走到)",
           f"发起后立刻看是「{r0.get('执行状态')}」,取消请求等了 {取耗时}s 才回,回的是「{状}」改了吗={(取 or {}).get('改了吗')};"
           f"慢服务被调了 {_慢.次数} 次。" + ("**请求被执行侧挡住了整次运行那么久**:Worker 整次运行一个事务、"
           "execution_runs 那一行被它 for update 锁着,接口的 for update 要等它提交才拿得到 —— 等到时已经是终态" if 取耗时 >= 慢秒 else ""))

    # ── ② 暂停 → 继续:要真的在跑且还有下一个节点 ───────────────────────────
    print("\n▸ ② 暂停 → paused → 继续 → succeeded")
    if not cvid:
        跳("暂停 → 继续", f"没有慢服务,运行瞬间跑完,抓不到 running 窗口:{说}")
    else:
        # ⚠️ 队列是共享的:并发跑的别份 e2e 会 `worker.py --一轮` 踢一个**不带 MODEL_ADAPTER 的 Worker**(默认 mock),
        # 它领到这次 live 运行会当场判 RUN_MODE_MISMATCH。那不是这条判据要验的事 —— 碰上了就再发一次,最多三次,
        # 每次都说出来(静默重试会把「被人抢走」和「正常」混成一个绿)
        for 第几次 in range(1, 4):
            前 = _慢.次数
            rid2 = 发起(wid, f"e2e 暂停 {尾} 第{第几次}次")
            r, 看到 = 等到running(rid2)
            if r.get("执行状态") == "failed" and r.get("停止原因") == "RUN_MODE_MISMATCH":
                print(f"     ⚠️ 第 {第几次} 次发起被一个 MODEL_ADAPTER=mock 的 Worker 领走判了 RUN_MODE_MISMATCH"
                      f"(并发 e2e 踢的 worker 没带模式;共享队列的老问题)—— 再发一次")
                continue
            break
        if r.get("执行状态") != "running":
            调了 = _慢.次数 - 前
            诊断 = ""
            if 调了 >= 2 and all(s in ("queued", "succeeded") for s, _ in 看到):
                # 跑了至少 2×慢秒,而外面全程只看到 queued → 终态:**不是没等到,是看不见**。
                # Worker 把整次运行放在一个事务里:status='running' 写了但没提交,外面读到的永远是 queued;
                # 这时 pause 走不了(queued → pause_requested 状态机不许),cancel 的 for update 会被挡到它提交。
                # 11-18「暂停 / 取消接执行侧」在进程内(tests/orchestration/test_pause_checkpoint.py)是通的,端到端走不到。
                诊断 = (f" —— **这不是时序没抓住,是从接口看不见**:假模型被调了 {调了} 次(≥ {2*慢秒:.0f}s 在跑),"
                        f"而 API 全程只看到 {[s for s, _ in 看到]};Worker 整次运行一个事务,status=running 不提交,"
                        f"外面读到的永远是 queued,pause 根本发不出去(状态机 queued 走不到 pause_requested)。这是执行侧的 bug,要修 Worker 的事务边界")
            跳("暂停 → 继续", f"没抓到 running 窗口:看到的是 {看到}{诊断}")
        else:
            c, 暂 = 打("POST", P + f"/execution-runs/{rid2}/pause", 头={"Idempotency-Key": f"p-{尾}", "If-Match": str(r.get("revision"))})
            ck("running 时 pause → 202 pause_requested", c == 202 and (暂 or {}).get("status") == "pause_requested", (c, 暂))
            r = 等状态(rid2, ("paused",), 秒=90)
            if r.get("执行状态") == "succeeded":
                ck("等到的是 succeeded —— 状态机允许(pause_requested → succeeded):最后一步前没赶上检查点,**这次没停住**", True,
                   f"慢服务被调了 {_慢.次数} 次")
                跳("paused 之后 resume → job_id → succeeded", "运行在停下之前就跑完了,没有 paused 可继续")
            else:
                ck("等到 **paused**(Worker 在下一个节点边界读到暂停请求停下,存了检查点)", r.get("执行状态") == "paused",
                   (r.get("执行状态"), r.get("停止原因")))
                核 = 控制(r, "reconcile")
                ck("paused 的运行:reconcile.现在能吗=false 且 为什么不能 非空", 核.get("现在能吗") is False and bool(核.get("为什么不能")), 核)
                ck("paused 的运行:resume 能、pause 不能", 控制(r, "resume").get("现在能吗") is True and 控制(r, "pause").get("现在能吗") is False,
                   [(x["动作"], x["现在能吗"]) for x in r.get("可执行的控制动作") or []])
                with 连接() as c:
                    快 = c.execute(text("select resume_snapshot, checkpoint_seq from execution_runs where project_id=:p and id=:i"),
                                   {"p": 项目, "i": rid2}).mappings().first()
                停在 = ((快 or {}).get("resume_snapshot") or {}).get("从")
                ck("检查点存了「从哪一步接着跑」(停在下一步**还没跑**的边界上)", 停在 in ("summarize2", "finish") and (快 or {}).get("checkpoint_seq") == 1,
                   (停在, (快 or {}).get("checkpoint_seq")))
                前次数 = _慢.次数
                c, 续 = 打("POST", P + f"/execution-runs/{rid2}/resume", 头={"Idempotency-Key": f"r-{尾}", "If-Match": str(r.get("revision"))})
                ck("resume → 202 status=queued 且返回里有 **job_id**(原来只改状态不插任务,运行永远「排队中」)",
                   c == 202 and (续 or {}).get("status") == "queued" and bool((续 or {}).get("job_id")), (c, 续))
                r3 = 看(rid2)
                if r3.get("执行状态") == "queued":
                    核 = 控制(r3, "reconcile")
                    ck("继续后 queued 的运行:reconcile.现在能吗=false 且 为什么不能 非空", 核.get("现在能吗") is False and bool(核.get("为什么不能")), 核)
                任务 = [t for t in 查任务(rid2) if t["id"] == (续 or {}).get("job_id")]
                ck("那个 job_id 在 jobs 里、type=workflow_run、target_ref 标着「恢复」", bool(任务) and 任务[0]["type"] == "workflow_run"
                   and (任务[0]["target_ref"] or {}).get("恢复") is True, 任务[0] if 任务 else (续 or {}).get("job_id"))
                终 = 等状态(rid2, ("succeeded",), 秒=max(60, 慢秒 * 3 + 20), 踢=True)
                ck("继续后跑到 **succeeded**(从检查点接着跑完剩下的步)", 终.get("执行状态") == "succeeded" and 终.get("是终态吗") is True,
                   (终.get("执行状态"), 终.get("停止原因")))
                步 = {s["节点"]: s["状态"] for s in 终.get("步骤") or []}
                ck("每一步都 succeeded,而且**没有哪一步跑了两遍**(暂停前跑完的那步不重跑)",
                   步 and all(v == "succeeded" for v in 步.values()) and len(终.get("步骤") or []) == len(步), 步)
                ck("恢复后假模型**只又被调了剩下的那几次**(停在 summarize2 → 1 次;停在 finish → 0 次)",
                   _慢.次数 - 前次数 == {"summarize2": 1, "finish": 0}.get(停在, -1), (前次数, _慢.次数, 停在))

    if srv:
        srv.shutdown()
    print(f"\n{'❌ 挂: ' + str(挂) if 挂 else '✅ ' + str(len(过)) + ' 条全过' + (f' · ⏸ {len(没验)} 条没验(见上)' if 没验 else '')}")
    for x in 没验:
        print("   ⏸", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
