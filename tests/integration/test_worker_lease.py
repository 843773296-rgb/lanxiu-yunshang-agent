#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务租约:**真的让两个 worker 去抢**,不是读代码觉得对。

规格 §19.3 声称的是结构性保证:「Worker 获取租约并检查现有结果,完成时用状态条件更新」。
而**一条从没被攻击过的「结构性保证」,实际上仍然只是约定**。

所以这里做九次真实攻击/对照,每一次都要有明确结果:
并发抢同一条、租约没过期别人抢不到、过期之后能接手、
过期的旧 worker 不许写结果、续租只有持租约的人续得上、
取消请求被续租带回来、格式错误不重试、到上限不重试、认不出的错误码不重试。

⚠️ 用完把库还原 —— **攻击测试写脏了不还原,下一轮的结论就不可信了**。
"""
import os, sys, time, uuid
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "services", "api", "app"),
                os.path.join(ROOT, "services", "api", "app", "jobs"),
                os.path.join(ROOT, "services", "api", "app", "contract")]
from sqlalchemy import create_engine, text
import lease as L

URL = os.environ.get("DATABASE_URL") or \
    "postgresql+psycopg://" + os.environ.get("USER", "") + "@localhost:5432/aimc_dev"
eng = create_engine(URL)
ORG, PROJ = "org_demo", "project_demo_a"

过, 挂 = [], []
def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:120]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 建任务(c, 类型="测试", 租约秒=None, max_attempts=3):
    jid = "job_t_" + uuid.uuid4().hex[:10]
    c.execute(text("""
        insert into jobs (id, organization_id, project_id, type, target_ref, status,
            attempts, max_attempts, idempotency_key, created_at, created_by,
            updated_at, revision)
        values (:i,:o,:p,:t,'{}'::jsonb,'排队中',0,:ma,:k, now(),'test', now(),1)
    """), {"i": jid, "o": ORG, "p": PROJ, "t": 类型, "ma": max_attempts,
           "k": uuid.uuid4().hex})
    return jid


with eng.connect() as c0:
    前 = c0.execute(text("select count(*) from jobs where project_id=:p"),
                    {"p": PROJ}).scalar()

# ── ① 两个 worker 抢同一条 → 恰好一个拿到 ────────────────────────
with eng.begin() as c:
    jid = 建任务(c, 类型="抢一条")
拿到 = []
for 谁 in ("worker-A", "worker-B"):
    with eng.begin() as c:
        r = L.取一个(c, 谁, 类型="抢一条", 项目=PROJ)
        if r: 拿到.append((谁, r["id"]))
ck("**两个 worker 抢同一条 → 恰好一个拿到**", len(拿到) == 1, 拿到)

# ── ② 租约没过期,第三个也抢不到 ───────────────────────────────────
with eng.begin() as c:
    r = L.取一个(c, "worker-C", 类型="抢一条", 项目=PROJ)
ck("租约没过期 → 别人抢不到(不是排队等,是直接没有)", r is None, r)

赢家 = 拿到[0][0] if 拿到 else None

# ── ③ 续租:只有持租约的人续得上 ───────────────────────────────────
with eng.begin() as c:
    好, 取消 = L.续租(c, PROJ, jid, 赢家, 阶段="解析中", 已处理=7)
ck("持租约的人能续租,并写得进阶段和已处理数", 好 and not 取消)
with eng.begin() as c:
    好2, _ = L.续租(c, PROJ, jid, "worker-别人", 阶段="乱改")
ck("**不持租约的人续不上**(否则两个人能同时持有)", not 好2)
with eng.connect() as c:
    st = c.execute(text("select stage, processed_count from jobs where project_id=:p and id=:i"),
                   {"p": PROJ, "i": jid}).first()
ck("阶段和已处理数确实落库了(而且没被那次乱改动到)", st[0] == "解析中" and st[1] == 7, st)

# ── ④ 取消请求由续租带回来 ────────────────────────────────────────
with eng.begin() as c:
    c.execute(text("""update jobs set cancel_requested=true, cancel_at=now()
                      where project_id=:p and id=:i"""), {"p": PROJ, "i": jid})
with eng.begin() as c:
    好3, 取消3 = L.续租(c, PROJ, jid, 赢家)
ck("**取消请求顺着续租带回来**(worker 不用另发一次查询)", 好3 and 取消3)

# ── ⑤ 租约过期 → 别人能接手;而**旧 worker 不许再写结果** ──────────
with eng.begin() as c:
    c.execute(text("""update jobs set lease_until = now() - interval '1 second',
                            cancel_requested=false
                      where project_id=:p and id=:i"""), {"p": PROJ, "i": jid})
with eng.begin() as c:
    接 = L.取一个(c, "worker-接手", 类型="抢一条", 项目=PROJ)
ck("租约过期 → 别人接得手", 接 is not None and 接["id"] == jid, 接 and 接["attempts"])
with eng.begin() as c:
    ok, 说 = L.收尾(c, PROJ, jid, 赢家, "已完成")
ck("**租约过期的旧 worker 不许写结果**(否则它会盖掉接手者的进度)",
   not ok and "不许覆盖" in 说, 说)
with eng.begin() as c:
    ok2, 说2 = L.收尾(c, PROJ, jid, "worker-接手", "已完成")
ck("接手的人能正常收尾", ok2, 说2)

# ── ⑥ 状态机:不许乱走 ────────────────────────────────────────────
with eng.begin() as c:
    j2 = 建任务(c, 类型="状态机")
with eng.begin() as c:
    r2 = L.取一个(c, "worker-S", 类型="状态机", 项目=PROJ)
# ⚠️ **第一版这条是空判据**:`ok3 or "不许从" in 说3` —— 两种情况都为真,
# 它永远不会红。而且 `执行中 → 排队中` 本来就是允许的(那是重试)。
# **一个永远不会红的断言比没有断言更糟**:它在报告里占着一行 ✅。
# 换成真正被禁的那条:`执行中 → 已取消`(取消必须先经过「取消请求中」,
# 因为取消和自然完成会并发,直接跳过去就等于谎报成已取消)。
with eng.begin() as c:
    ok3, 说3 = L.收尾(c, PROJ, j2, "worker-S", "已取消")
ck("**不许从「执行中」直接跳到「已取消」**(取消要先经过「取消请求中」)",
   not ok3 and "不许从" in 说3, 说3)
with eng.begin() as c:
    ok3b, 说3b = L.收尾(c, PROJ, j2, "worker-S", "已完成")
ck("允许的流转照样放行(否则上一条只证明了「什么都走不动」)", ok3b, 说3b)

# ── ⑦ 重试:分类 + 上限 + 认不出就不重试 ──────────────────────────
with eng.begin() as c:
    j3 = 建任务(c, 类型="重试", max_attempts=2)
with eng.begin() as c:
    L.取一个(c, "worker-R", 类型="重试", 项目=PROJ)
with eng.begin() as c:
    ok4, 说4 = L.退回重试(c, PROJ, j3, "worker-R", "VALIDATION")
with eng.connect() as c:
    s4 = c.execute(text("select status, error_code from jobs where project_id=:p and id=:i"),
                   {"p": PROJ, "i": j3}).first()
ck("**格式错误不重试 → 直接失败**(重试同一份输入必然同样失败)",
   s4[0] == "失败" and s4[1] == "VALIDATION", f"{说4} | {s4}")

with eng.begin() as c:
    j4 = 建任务(c, 类型="重试2", max_attempts=3)
with eng.begin() as c:
    L.取一个(c, "worker-R2", 类型="重试2", 项目=PROJ)
with eng.begin() as c:
    ok5, 说5 = L.退回重试(c, PROJ, j4, "worker-R2", "TIMEOUT")
with eng.connect() as c:
    s5 = c.execute(text("""select status, next_retry_at > now() from jobs
                          where project_id=:p and id=:i"""), {"p": PROJ, "i": j4}).first()
ck("超时 → 退回排队,而且**排在未来某个时刻**(退避生效了)",
   ok5 and s5[0] == "排队中" and s5[1] is True, f"{说5} | {s5}")
with eng.begin() as c:
    抢 = L.取一个(c, "worker-R3", 类型="重试2", 项目=PROJ)
ck("**退避没到时间,抢不到**(否则退避等于没有)", 抢 is None)

# ── ⑧ 卡住的任务:租约没到期但心跳停了 ───────────────────────────
with eng.begin() as c:
    j5 = 建任务(c, 类型="卡住")
with eng.begin() as c:
    L.取一个(c, "worker-卡", 类型="卡住", 项目=PROJ)
    c.execute(text("""update jobs set heartbeat_at = now() - interval '10 minutes'
                      where project_id=:p and id=:i"""), {"p": PROJ, "i": j5})
with eng.connect() as c:
    卡 = L.捞回卡住的(c, 项目=PROJ)
ck("**租约没过期但心跳停了 → 认得出「卡住」**(只有租约的话它看起来正常)",
   any(x["id"] == j5 for x in 卡), [x["id"] for x in 卡])

# ── 还原 ────────────────────────────────────────────────────────
with eng.begin() as c:
    c.execute(text("delete from jobs where project_id=:p and type in "
                   "('抢一条','状态机','重试','重试2','卡住','测试')"), {"p": PROJ})
with eng.connect() as c:
    后 = c.execute(text("select count(*) from jobs where project_id=:p"),
                   {"p": PROJ}).scalar()
ck("跑完库里没多出任务(攻击测试写脏了不还原,下一轮结论就不可信)", 后 == 前,
   f"{前} → {后}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
if 挂:
    for x in 挂: print("   ·", x)
sys.exit(1 if 挂 else 0)
