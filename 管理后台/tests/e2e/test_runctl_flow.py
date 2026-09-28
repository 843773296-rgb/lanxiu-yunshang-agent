#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行控制端到端:暂停 / 继续 / 取消 / 核实 / 安全重试(§12.3)。

## 这一份守的一句话:**「请求」不是「已经」**

    pause  → `pause_requested`,**不是** `paused`
    cancel → `cancel_requested`,**不是** `cancelled`

把「请求暂停」直接写成「已暂停」的后果:界面显示已停,
而模型还在跑、钱还在花 —— **而没有任何东西报错**。

⚠️ 前提 `make dev`。连不上就退非 0,不静默跳过。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:170]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 键=None, 谁="U002"):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 键:
        req.add_header("Idempotency-Key", 键)
    if 体 is not None:
        req.add_header("content-type", "application/json")
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


from sqlalchemy import text
from db import 事务, 连接
import time
唯一 = str(int(time.time()))[-7:]


def 设状态(rid, st):
    """直接改库造前提 —— **这是测试夹具,不是接口能做的事**。"""
    with 事务() as c:
        c.execute(text("update execution_runs set status=:s, revision=revision+1 "
                       "where project_id=:p and id=:i"),
                  {"s": st, "i": rid, "p": 项目})
    with 连接() as c:
        return c.execute(text("select revision from execution_runs where id=:i"),
                         {"i": rid}).scalar()


with 连接() as c:
    rid = c.execute(text("""select id from execution_runs where project_id=:p
                          and archived_at is null order by created_at desc limit 1"""),
                    {"p": 项目}).scalar()
if not rid:
    print("❌ 库里没有 execution_run —— **这不叫跳过**")
    sys.exit(1)

print("▸ ① 要幂等键 + 要 revision")
rev = 设状态(rid, "running")
码, r = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": rev})
ck("不带 Idempotency-Key → 409", 码 == 409 and r.get("code") == "IDEMPOTENCY_KEY_REQUIRED", 码)
码, r = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={}, 键=f"a{唯一}")
ck("不给 revision → 422", 码 == 422, 码)
ck("理由说清「后到的不许静默覆盖」",
   "静默覆盖" in ((r or {}).get("advice") or ""), (r or {}).get("advice"))
码, r = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": 99999}, 键=f"b{唯一}")
ck("revision 对不上 → 409", 码 == 409 and r.get("code") == "REVISION_CONFLICT", 码)

print("▸ ② 暂停是「请求」,不是「已经」")
码, p1 = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": rev}, 键=f"p{唯一}")
ck("202", 码 == 202, 码)
ck("状态是 **pause_requested**,不是 paused", p1["status"] == "pause_requested", p1["status"])
ck("note 明说「在途调用未必立刻停,钱可能还在花」",
   "还在花" in (p1.get("note") or ""), p1.get("note"))
码, p2 = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": p1["revision"]},
          键=f"p2{唯一}")
ck("再暂停一次 → 改了吗=False(重复请求不改变什么)", p2["改了吗"] is False)

print("▸ ③ **还没停下来时点「继续」不是继续**")
码, r = 打("POST", f"{P}/execution-runs/{rid}/resume", 体={"revision": p1["revision"]},
         键=f"r{唯一}")
ck("409 NOT_PAUSED_YET", 码 == 409 and r.get("code") == "NOT_PAUSED_YET", 码)
ck("理由说清「它还在跑,谈不上从检查点继续」",
   "还在跑" in ((r or {}).get("advice") or ""), (r or {}).get("advice"))

print("▸ ④ 真停了之后才能继续")
rev2 = 设状态(rid, "paused")
码, r2 = 打("POST", f"{P}/execution-runs/{rid}/resume", 体={"revision": rev2}, 键=f"r2{唯一}")
ck("202 → queued", 码 == 202 and r2["status"] == "queued", f"{码} {r2.get('status')}")
ck("note 说「用量和循环计数保留」", "保留" in (r2.get("note") or ""))
ck("而且说清**不把暂停期间更新的 Prompt 静默装进来**",
   "静默装进来" in (r2.get("note") or ""), r2.get("note"))

print("▸ ⑤ 取消:两条路,而且都不承诺撤销已发生的动作")
rev3 = 设状态(rid, "queued")
码, c1 = 打("POST", f"{P}/execution-runs/{rid}/cancel", 体={"revision": rev3}, 键=f"c1{唯一}")
ck("还没开跑 → **直接 cancelled**(没有在途调用要掐)",
   码 == 202 and c1["status"] == "cancelled", f"{码} {c1.get('status')}")
ck("而且仍然提醒「已经发生的动作撤不回来」",
   "撤不回来" in (c1.get("note") or ""), c1.get("note"))
rev4 = 设状态(rid, "running")
码, c2 = 打("POST", f"{P}/execution-runs/{rid}/cancel", 体={"revision": rev4}, 键=f"c2{唯一}")
ck("跑着的 → **cancel_requested**,不是 cancelled",
   码 == 202 and c2["status"] == "cancel_requested", c2.get("status"))
ck("note 明说「停的是新调度」且「写出去的文件取消不掉」",
   "新调度" in (c2.get("note") or "") and "取消不掉" in (c2.get("note") or ""))

print("▸ ⑥ 终态:**保留真实终态,不谎报成已取消**")
rev5 = 设状态(rid, "succeeded")
码, c3 = 打("POST", f"{P}/execution-runs/{rid}/cancel", 体={"revision": rev5}, 键=f"c3{唯一}")
ck("终态上取消 → 改了吗=False,状态还是 succeeded",
   c3["改了吗"] is False and c3["status"] == "succeeded", c3)
ck("理由说「它的产物是真的,取消不掉」", "产物是真的" in (c3.get("note") or ""))
码, r = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": rev5}, 键=f"c4{唯一}")
ck("终态上暂停 → 409 BAD_TRANSITION(**状态机不许,不静默放行**)",
   码 == 409 and r.get("code") == "BAD_TRANSITION", 码)
ck("而且把状态机允许的流转列出来", "states.py" in ((r or {}).get("advice") or ""))

print("▸ ⑦ 核实:**去查,不重做**")
rev6 = 设状态(rid, "running")
码, rc = 打("POST", f"{P}/execution-runs/{rid}/reconcile", 体={}, 键=f"rc{唯一}")
ck("202 → reconciling", 码 == 202 and rc["status"] == "reconciling", rc.get("status"))
ck("note 点明「HTTP 超时不代表对方没做事」",
   "超时不代表" in (rc.get("note") or ""), rc.get("note"))
ck("报了要核实几步", "要核实的步数" in rc, sorted(rc))
if rc["要核实的步数"] == 0:
    ck("一步不确定的都没有时**也说出来**(那可能是状态记漏了)",
       "核实什么" in (rc.get("note") or ""), rc.get("note")[-60:])

print("▸ ⑧ 安全重试:「安全」是判据不是形容词")
with 连接() as c:
    步 = c.execute(text("""select id, status from run_steps
                         where project_id=:p and execution_run_id=:r limit 1"""),
                   {"p": 项目, "r": rid}).mappings().first()
if not 步:
    ck("这次运行没有步骤,重试那条测不了(**报出来,不假装测过**)", True)
else:
    with 事务() as c:
        c.execute(text("update run_steps set status='状态待核实' where id=:i"),
                  {"i": 步["id"]})
    码, r = 打("POST", f"{P}/execution-runs/{rid}/steps/{步['id']}/retry",
             体={}, 键=f"t1{唯一}")
    ck("状态不确定的步 → 409 不许重试",
       码 == 409 and r.get("code") == "STEP_NOT_SAFE_TO_RETRY", f"{码} {r.get('code')}")
    ck("理由说「重试一个可能已经成功的写操作,就是第二次扣款」",
       "第二次扣款" in ((r or {}).get("advice") or ""), (r or {}).get("advice"))
    with 事务() as c:
        c.execute(text("update run_steps set status='succeeded' where id=:i"), {"i": 步["id"]})
    码, r = 打("POST", f"{P}/execution-runs/{rid}/steps/{步['id']}/retry", 体={}, 键=f"t2{唯一}")
    ck("已经成功的步 → 409 不重试", 码 == 409 and r.get("code") == "STEP_ALREADY_SUCCEEDED", 码)
    with 事务() as c:
        c.execute(text("update run_steps set status='failed' where id=:i"), {"i": 步["id"]})
    码, r = 打("POST", f"{P}/execution-runs/{rid}/steps/{步['id']}/retry", 体={}, 键=f"t3{唯一}")
    ck("失败的步 → 202,**新建一步而不是改旧那步**",
       码 == 202 and r.get("新的步") and r["新的步"] != 步["id"], f"{码} {r.get('新的步')}")
    ck("attempt 加一", (r or {}).get("attempt", 0) >= 1, (r or {}).get("attempt"))
    ck("note 说清 **logical_action_id 没变**(它是幂等的锚)",
       "logical_action_id" in (r.get("note") or ""), r.get("note"))

print("▸ ⑨ 权限")
rev7 = 设状态(rid, "running")
码, r = 打("POST", f"{P}/execution-runs/{rid}/pause", 体={"revision": rev7},
         键=f"v{唯一}", 谁="U003")
ck("viewer 暂停 → 403", 码 == 403, 码)

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
