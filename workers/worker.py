#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台 Worker(规格 §19.3)。

## 它必须是幂等的,而且这不是「尽量」

Outbox 的设计**保证**会有重复投递(规格 §17.1:「重复投递是正常故障场景」)。
所以每个处理器进来第一件事是 **检查现有结果** —— 已经做完的不重做。
把重复投递当异常处理的 worker 一定会出错。

## 心跳在处理过程中打,不是跑完才打

一个只在开始和结束打心跳的 worker,中间那段时间**和卡死没有区别**。
所以处理器每推进一步就 `续租()`,顺便把「有人请求取消吗」读回来。

## 取消:令牌传给执行器,终态由后台确认

规格 §19.3:「取消令牌向执行器传递;后台确认终态。
**强制杀进程不能保证外部任务/费用立即停止**」。
所以这里的取消是**协作式**的:处理器在每个检查点看一眼令牌,自己收尾。
杀进程只会让租约过期、然后被别人接手 —— 那不是取消。

## 怎么跑

    make worker                  # 一直跑
    python3 workers/worker.py --一轮   # 只跑一轮(测试和 CI 用)
"""
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "services", "api", "app"),
                os.path.join(ROOT, "services", "api", "app", "jobs"),
                os.path.join(ROOT, "services", "api", "app", "contract")]

from sqlalchemy import text
import lease as L
import outbox as OB
import events as EV
from db import 事务, 连接

我是谁 = os.environ.get("WORKER_NAME") or f"worker-{os.getpid()}-{uuid.uuid4().hex[:4]}"


class 取消了(Exception):
    """取消令牌被置上 —— **由处理器自己抛**,不是被外面杀掉。"""


class 干不了(Exception):
    """带错误码的失败。code 决定该不该重试(见 lease.该重试吗)。"""
    def __init__(self, code, 细节=None):
        super().__init__(code)
        self.code, self.细节 = code, 细节


def _新(前缀): return f"{前缀}_{uuid.uuid4().hex[:12]}"


# ── 处理器登记表 ────────────────────────────────────────────────────
# ⚠️ **认不出的任务类型不许静默跳过。** 一个被跳过的任务会一直停在「排队中」,
# 而「没人处理」和「排在后面」在界面上长得一模一样。
处理器 = {}


def 处理(类型):
    def 包(f):
        处理器[类型] = f
        return f
    return 包


@处理("prompt_run")
def _跑一次prompt(c, job, 打点):
    """调试运行。**先看有没有做过** —— Outbox 保证会有重复投递。"""
    t = job["target_ref"] or {}
    run_id, pid = t.get("run_id"), t.get("prompt_id")
    做过 = c.execute(text("""select id from traces
                           where project_id=:p and session_id=:s limit 1"""),
                     {"p": job["project_id"], "s": run_id}).first()
    if 做过:
        # **幂等**:重复投递时不再跑一遍模型(那会多花一次钱)
        打点("跳过", {"为什么": "这个 run 已经有 trace 了 —— 重复投递,不重跑",
                     "trace_id": 做过[0]})
        return {"trace_id": 做过[0], "幂等命中": True}

    d = c.execute(text("select * from prompt_drafts where project_id=:p and id=:i"),
                  {"p": job["project_id"], "i": pid}).mappings().first()
    if not d:
        # 引用的对象不存在 —— **不重试**,它不会自己出现
        raise 干不了("NOT_FOUND", {"prompt_id": pid})

    打点("展开模板", {"阶段": "render"})
    if 打点.取消了:
        raise 取消了()

    import main as _api                       # 复用 mock 适配器,不抄第二份
    r = _api._mock生成(dict(d), t.get("变量") or {})

    打点("调模型", {"阶段": "generate", "execution_mode": r["execution_mode"]})
    if 打点.取消了:
        raise 取消了()

    trace = _新("tr")
    c.execute(text("""
        insert into traces (id, organization_id, project_id, session_id, request_id,
            environment, started_at, ended_at, end_reason, created_at, created_by)
        values (:i,:o,:p,:s,:rq,:e, now(), now(), :er, now(), :u)
    """), {"i": trace, "o": job["organization_id"], "p": job["project_id"],
           "s": run_id, "rq": job["id"], "e": os.environ.get("APP_ENV", "development"),
           "er": r["finish_reason"], "u": 我是谁})
    c.execute(text("""
        insert into spans (id, organization_id, project_id, trace_id, stage,
            input_ref, output_ref, started_at, ended_at, created_at, created_by)
        values (:i,:o,:p,:t,'generate',:ir,:orf, now(), now(), now(), :u)
    """), {"i": _新("sp"), "o": job["organization_id"], "p": job["project_id"],
           "t": trace,
           "ir": __import__("json").dumps({"展开后模板": r["展开后模板"]}, ensure_ascii=False),
           "orf": __import__("json").dumps(
               {"text": r["text"], "execution_mode": r["execution_mode"]},
               ensure_ascii=False), "u": 我是谁})
    # 费用:mock 没有真实计价 → **amount_known=false,不写 0**
    c.execute(text("""
        insert into usage_ledger (id, organization_id, project_id, event_key, trace_id,
            resource, quantity, unit, currency, amount, amount_known, source,
            created_at, created_by)
        values (:i,:o,:p,:ek,:t,'generate',:q,'token','CNY', null, false, :src,
                now(), :u)
        on conflict (event_key) do nothing
    """), {"i": _新("ul"), "o": job["organization_id"], "p": job["project_id"],
           "ek": f"{job['id']}:generate", "t": trace,
           "q": r["usage"]["input_tokens"] + r["usage"]["output_tokens"],
           "src": r["execution_mode"], "u": 我是谁})
    return {"trace_id": trace, "execution_mode": r["execution_mode"]}


class _打点器:
    """每一步:写事件 + 续租 + 把取消令牌读回来。"""
    def __init__(self, c, job):
        self.c, self.job, self.取消了, self.n = c, job, False, 0

    def __call__(self, kind, payload=None):
        self.n += 1
        EV.记一条(self.c, org=self.job["organization_id"], 项目=self.job["project_id"],
                 job_id=self.job["id"], kind=kind, payload=payload or {},
                 新id=_新("je"))
        好, 取消 = L.续租(self.c, self.job["project_id"], self.job["id"], 我是谁,
                        阶段=(payload or {}).get("阶段"), 已处理=self.n)
        if not 好:
            # 租约不在我手上了 —— **立刻停手**,别再往下写
            raise 干不了("LEASE_LOST", {"说明": "租约过期或被接手,停手不覆盖"})
        self.取消了 = 取消


def 跑一轮(类型=None, 项目=None):
    """捞一条跑完。返回一句人话(没活干就返回 None)。"""
    with 事务() as c:
        job = L.取一个(c, 我是谁, 类型=类型, 项目=项目)
    if not job:
        return None
    名 = f"{job['type']}#{job['id'][-8:]}"
    f = 处理器.get(job["type"])
    if f is None:
        # **认不出的类型不静默跳过** —— 它会一直停在「排队中」,
        # 而「没人处理」和「排在后面」在界面上一模一样
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="没有处理器",
                     payload={"type": job["type"], "已登记的": sorted(处理器)},
                     新id=_新("je"))
            L.收尾(c, job["project_id"], job["id"], 我是谁, "失败",
                  error_code="INCOMPATIBLE",
                  error_detail={"说明": f"没有 {job['type']} 的处理器"})
        return f"{名}:没有处理器 → 失败(**不静默跳过**)"

    try:
        with 事务() as c:
            打点 = _打点器(c, job)
            打点("开始", {"阶段": "start", "worker": 我是谁})
            出 = f(c, job, 打点)
            打点("完成", dict(出 or {}))
            ok, 说 = L.收尾(c, job["project_id"], job["id"], 我是谁, "已完成")
            if not ok:
                raise 干不了("LEASE_LOST", {"说明": 说})
        return f"{名}:已完成 {出}"
    except 取消了:
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="收到取消,停手", payload={}, 新id=_新("je"))
            # 先进「取消请求中」再到「已取消」—— 状态机不许直接跳
            c.execute(text("""update jobs set status='取消请求中', updated_at=now(),
                              revision=revision+1
                              where project_id=:p and id=:i and lease_owner=:me"""),
                      {"p": job["project_id"], "i": job["id"], "me": 我是谁})
            L.收尾(c, job["project_id"], job["id"], 我是谁, "已取消")
        return f"{名}:按取消令牌停手了"
    except 干不了 as e:
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="失败",
                     payload={"code": e.code, "细节": e.细节}, 新id=_新("je"))
            ok, 说 = L.退回重试(c, job["project_id"], job["id"], 我是谁, e.code, e.细节)
        return f"{名}:{e.code} —— {说}"
    except Exception as e:
        # 没预料到的异常:**当成可重试的瞬时故障,但记清是什么** ——
        # 不记的话,重试三次之后只剩一个「失败」,原因追不回来
        with 事务() as c:
            EV.记一条(c, org=job["organization_id"], 项目=job["project_id"],
                     job_id=job["id"], kind="崩了",
                     payload={"异常": f"{type(e).__name__}: {e}"}, 新id=_新("je"))
            L.退回重试(c, job["project_id"], job["id"], 我是谁, "TRANSIENT",
                      {"异常": f"{type(e).__name__}: {e}"})
        return f"{名}:崩了 {type(e).__name__}: {e}"


def main():
    一轮 = "--一轮" in sys.argv
    类型 = None
    for i, a in enumerate(sys.argv):
        if a == "--type" and i + 1 < len(sys.argv): 类型 = sys.argv[i + 1]
    print(f"worker 起来了:{我是谁}" + (f"(只跑 {类型})" if 类型 else ""))
    空转 = 0
    while True:
        with 事务() as c:
            发, 卡 = OB.发布一批(c)
        if 卡:
            print(f"  ⚠️ 发件箱里有 {卡} 条到了尝试上限还没发出去 —— **人要看一眼**:"
                  f"一条永远发不出去的消息会把发布器卡住,而卡住的发布器"
                  f"看起来只是「最近没有新任务」")
        话 = 跑一轮(类型=类型)
        if 话:
            print("  " + 话); 空转 = 0
        else:
            空转 += 1
        if 一轮:
            # 一轮模式:把当前能捞到的都跑完再退,方便测试和 CI
            if 话 is None:
                break
            continue
        time.sleep(min(5.0, 0.2 * 空转) if 空转 else 0.05)


if __name__ == "__main__":
    main()
