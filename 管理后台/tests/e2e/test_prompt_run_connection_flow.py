#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 调试运行**绑模型连接**(11-18 用户报「运行测试每次都排队、不给答案」)。

## 这一份守的一句话

> **没点名就不替你挑;点名了就得是这个项目里启用的那一条。**

查实的那条链(main._定调试连接 文件头):快照里**从来没有** `model_connection_id`,
真跑模式下 Worker 每一次都 `NO_MODEL_CONNECTION`,而页面只看到「排队中」。
修法不是「随便挑一条」—— demo 项目里有不止一条启用的生成连接,替人挑一条等于
**替他决定这次花谁的钱、拿谁的答案**,而界面上看不出是谁挑的。所以:

  · 点名一条不存在 / 已停用的  → 422 MODEL_CONNECTION_UNKNOWN,field_errors 指到 model_connection_id
  · 点名一条启用的             → 202,信封里「模型连接」就是它、说明是「调用方点名」;**快照里真有这个键**
  · 不点名、项目里不止一条     → 202 但「模型连接」是 null,说明里写明「不替你挑」(在这里就说会失败,别让人盯着排队中等)
  · 同一个幂等键换一条连接     → 409 IDEMPOTENCY_CONFLICT(连接也是「这次请求的配置」)
  · GET /jobs/{id} 带 error_code / error_detail(失败原因原来只在库里,页面拿到「失败」不知道为什么)

⚠️ 前提 `make dev`。只碰 project_demo_a;库**只读**(照 test_prompt_snapshot_flow 的写法查 jobs.config_snapshot)。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


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

import subprocess as _sp                # noqa: E402
_PY = os.path.join(_根, ".venv", "bin", "python")


def _worker环境():
    """踢出去的 Worker 要和常驻服务**同一种模式**:服务说自己不是 mock,就用 anthropic 起;
    不然我踢的那个 Worker 用 mock 把任务跑完,「真跑模式下没点名会失败」那条就验的不是线上那一支。"""
    env = dict(os.environ)
    try:
        健 = 打("GET", "/api/healthz")[1] or {}
        env["MODEL_ADAPTER"] = "mock" if 健.get("模型是mock", True) is not False else "anthropic"
    except Exception:
        pass
    return env


def 踢一轮():
    """CI 上没有常驻 Worker,光等是等不到的(test_api_flow 顶上那段)。"""
    _sp.run([_PY, os.path.join(_根, "workers", "worker.py"), "--一轮"],
            capture_output=True, text=True, timeout=120, cwd=_根, env=_worker环境())


def 等到终态(job_id, 秒=60):
    起 = time.time()
    最后 = None
    while True:
        踢一轮()
        c, j = 打("GET", P + f"/jobs/{job_id}")
        if c == 200 and (j or {}).get("是终态吗") is True:
            return j
        最后 = (c, j)
        if time.time() - 起 > 秒:
            return {"_没到终态": 最后}
        time.sleep(0.3)


def main():
    print("\n\033[1m▸ Prompt 调试运行绑模型连接 · 没点名不替你挑\033[0m")
    # ── 0. 前提:项目里有不止一条启用的生成连接(否则「不替你挑」那条是空验)──
    c, 列 = 打("GET", P + "/model-connections", 谁="U001")
    ck("GET /model-connections 200", c == 200, c)
    生成的 = [x for x in (列 or {}).get("连接", []) if x.get("用途") == "generate" and x.get("状态") == "active"]
    ck(f"**前提:项目里启用的生成连接不止一条**(现在 {len(生成的)} 条;只有一条时「不替你挑」这条没东西可验)",
       len(生成的) >= 2, [x["id"] for x in 生成的])
    if len(生成的) < 2:
        print("  ⛔ 前提不成立,后面的断言会连带红 —— 这不叫通过")
    # 停用的那几条:列表默认不列,`?含停用=true` 才列 —— 拿一条停用的当「已停用」的点名对象
    c, 全 = 打("GET", P + "/model-connections?含停用=true", 谁="U001")
    停用的 = [x for x in (全 or {}).get("连接", []) if x.get("用途") == "generate" and x.get("状态") == "archived"]

    c, 草们 = 打("GET", P + "/prompts")
    pid = next((x["id"] for x in (草们 or {}).get("items", []) if x.get("key") == "article_summary"), None)
    ck("夹具:拿到 article_summary 这条 Prompt(**先断它在**,不然下面全是空验)", bool(pid), pid)
    变量 = {"article": f"端到端:绑连接 {uuid.uuid4().hex[:6]}", "audience": "工程师"}

    # ── 1. 点名一条不存在的 → 422 ──────────────────────────────────────
    s, r = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量,
                                          "model_connection_id": f"mc_不存在_{uuid.uuid4().hex[:6]}"},
              头={"Idempotency-Key": uuid.uuid4().hex})
    ck("点名一条**不存在**的连接 → 422 MODEL_CONNECTION_UNKNOWN",
       s == 422 and (r or {}).get("code") == "MODEL_CONNECTION_UNKNOWN", (s, (r or {}).get("code")))
    ck("field_errors 指到 model_connection_id(点着能定位到那个字段)",
       "model_connection_id" in ((r or {}).get("field_errors") or {}), (r or {}).get("field_errors"))
    if 停用的:
        s, r = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量,
                                              "model_connection_id": 停用的[0]["id"]},
                  头={"Idempotency-Key": uuid.uuid4().hex})
        ck("点名一条**已停用**的连接 → 也是 422(停用的不算「启用的生成连接」)",
           s == 422 and (r or {}).get("code") == "MODEL_CONNECTION_UNKNOWN", (s, (r or {}).get("code"), 停用的[0]["id"]))
    else:
        ck("点名一条已停用的连接 → 422(**库里没有停用的生成连接,这条没验** —— 不是通过)", False, "停用的条数=0")

    # ── 2. 点名一条启用的 → 202,信封 + 快照都写了它 ─────────────────────
    选 = 生成的[0]["id"] if 生成的 else None
    键 = uuid.uuid4().hex
    s, r = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量, "model_connection_id": 选},
              头={"Idempotency-Key": 键})
    ck("点名一条启用的 → 202", s == 202, (s, str(r)[:120]))
    ck("信封里「模型连接」就是点名的那条", (r or {}).get("模型连接") == 选, ((r or {}).get("模型连接"), 选))
    ck("「模型连接说明」是「调用方点名」", (r or {}).get("模型连接说明") == "调用方点名", (r or {}).get("模型连接说明"))
    job = (r or {}).get("job_id")
    run = (r or {}).get("resource_id")
    ck("拿到了 job_id / resource_id(**先断非空**)", bool(job and run), (job, run))
    with 连接() as c:
        行 = c.execute(text("""select config_snapshot, snapshot_hash from jobs
                              where project_id=:p and id=:i"""), {"p": 项目, "i": job}).mappings().first()
    快照 = dict(行 or {}).get("config_snapshot") or {}
    ck("库里 jobs.config_snapshot 有 `model_connection_id` 且就是它(**存一个哈希还原不了内容,连接也一样**)",
       快照.get("model_connection_id") == 选, {k: 快照.get(k) for k in ("model_connection_id", "模型连接来源")})
    ck("快照里也留了「模型连接来源」", 快照.get("模型连接来源") == "调用方点名", 快照.get("模型连接来源"))

    # ── 3. 同一个幂等键换一条连接 → 409 ─────────────────────────────────
    另一条 = 生成的[1]["id"] if len(生成的) >= 2 else 选
    s2, r2 = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量, "model_connection_id": 另一条},
                头={"Idempotency-Key": 键})
    ck("**同一个 Idempotency-Key 换一条连接 → 409 IDEMPOTENCY_CONFLICT**(连接是「这次请求的配置」的一部分)",
       s2 == 409 and (r2 or {}).get("code") == "IDEMPOTENCY_CONFLICT", (s2, (r2 or {}).get("code")))
    s3, r3 = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量, "model_connection_id": 选},
                头={"Idempotency-Key": 键})
    ck("同一个键、同一条连接 → 202 复用原任务(对照:上一条不是恒 409)",
       s3 == 202 and (r3 or {}).get("job_id") == job, (s3, (r3 or {}).get("job_id"), job))

    # ── 4. 不点名、项目里不止一条 → 202 但不替你挑 ───────────────────────
    s4, r4 = 打("POST", P + "/prompt-runs", {"prompt_id": pid, "变量": 变量},
                头={"Idempotency-Key": uuid.uuid4().hex})
    ck("不点名、不止一条启用的 → 仍然 202(受理不等于能跑成)", s4 == 202, (s4, str(r4)[:120]))
    ck("「模型连接」是 **null**(不替你挑)", (r4 or {}).get("模型连接") is None, (r4 or {}).get("模型连接"))
    说明 = (r4 or {}).get("模型连接说明") or ""
    ck("说明里写明「不替你挑」而且**在这里就说会失败**(别让人盯着「排队中」等)",
       "不替你挑" in 说明 and "失败" in 说明, 说明[:120])
    with 连接() as c:
        行4 = c.execute(text("select config_snapshot from jobs where project_id=:p and id=:i"),
                        {"p": 项目, "i": (r4 or {}).get("job_id")}).scalar()
    ck("没点名时快照里 `model_connection_id` 是 null(键在、值空 —— 和「没这个键」分得开)",
       isinstance(行4, dict) and "model_connection_id" in 行4 and 行4["model_connection_id"] is None,
       {k: (行4 or {}).get(k) for k in ("model_connection_id", "模型连接来源")})

    # ── 5. GET /jobs/{id} 带失败原因两个键 ──────────────────────────────
    j = 等到终态(job)
    ck("点名那次运行到了终态(mock 模式跑完;真跑模式下按这条连接的真实情况成或败)",
       "_没到终态" not in j, str(j.get("status") if "_没到终态" not in j else j["_没到终态"])[:120])
    ck("GET /jobs/{id} 返回里有 `error_code` / `error_detail` 两个键(页面拿到「失败」要知道为什么)",
       "error_code" in j and "error_detail" in j, sorted(k for k in j if k in ("error_code", "error_detail", "status")))
    if j.get("status") in ("失败", "已失败"):
        ck("失败的任务 error_code **非空**(原来只在库里,页面看不见)", bool(j.get("error_code")),
           (j.get("error_code"), str(j.get("error_detail"))[:100]))
    else:
        ck("跑成的任务 error_code 是 null(不是空串、不是「ok」—— 没失败就没有失败原因)",
           j.get("error_code") is None, (j.get("status"), j.get("error_code")))
    j4 = 等到终态((r4 or {}).get("job_id"))
    健康 = 打("GET", "/api/healthz")[1] or {}
    if 健康.get("模型是mock") is False:
        ck("真跑模式下没点名那次 → 失败且 error_code=NO_MODEL_CONNECTION(信封里预告的那个)",
           j4.get("status") in ("失败", "已失败") and j4.get("error_code") == "NO_MODEL_CONNECTION",
           (j4.get("status"), j4.get("error_code")))
    else:
        print("  ⏸ 真跑模式下没点名那次会失败 NO_MODEL_CONNECTION —— 服务是 mock 模式,这条没验(mock 不要连接)")

    print(f"\n{'✅ ' + str(len(过)) + ' 条全过' if not 挂 else '❌ 挂: ' + str(挂)}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
