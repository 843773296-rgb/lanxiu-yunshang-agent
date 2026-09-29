#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务事件流(SSE)端到端:`GET /jobs/{id}/events`(规格 §19.2)。

## 为什么单独一份

交接里这条接口长期挂在「**已实现未验**」那一栏 —— 全后台最后一条。
而「未验」在一张 95 行的清单上是**看不出来的**:它和验过的那 94 条
长得一模一样,都只是一行接口名。

SSE 又是最容易「看起来通了」的一种:连上了、有字往外吐,
就很像是对的。而这条接口真正担责任的四件事,**吐字都不证明**:

| 要担的事 | 错了会怎样 | 错了看起来怎样 |
|---|---|---|
| 按 `seq` 续传 | 断线重连**丢一条**事件 | 界面少一行,而没人知道少了 |
| 终态要发「结束」 | 客户端永远等着 | 转圈,像「还在跑」 |
| 流开着也要**重新鉴权** | 权限撤回后还在送数据 | 没有任何迹象 |
| 任务不存在要**说出来** | 空流 | **和「什么都没发生」长得一模一样** |

最后那一行是这份测试的核心:**空的返回是最危险的返回值** ——
「什么都没有」和「成功地什么都没有」必须长得不一样。

⚠️ 这一份**不碰 U002**(别的测试在用它)。它自己造一个临时工号,
撤权只撤这一个,而且在 `finally` 里还原 —— 攻击测试写脏了不还原,
下一轮的结论就不可信,而且先害的是别人那份测试。
"""
import json, os, sys, threading, time, urllib.error, urllib.request, uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
A, B = "project_demo_a", "project_demo_b"
P = f"/api/v1/projects/{A}"
ORG = "org_demo"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "services", "api", "app")]
from sqlalchemy import text                                   # noqa: E402
from db import 事务                                            # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:130]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路径, 用户=None):
    req = urllib.request.Request(基址 + 路径, method=方法)
    if 用户:
        req.add_header("X-Dev-User", 用户)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def 读流(路径, 用户, 直到=None, 至多=None, 秒=10):
    """读 SSE,**读到就走** —— 这条流自己能开两分钟,不能等它。

    ⚠️ `秒` 是上限不是窗口:到了就返回已经收到的,让断言自己去说
    「该来的那条没来」。不在这里抛,是为了让失败信息是
    「收到了 [...]、缺 X」而不是一句 timeout。
    """
    req = urllib.request.Request(基址 + 路径, method="GET")
    if 用户:
        req.add_header("X-Dev-User", 用户)
    事件, 种 = [], None
    止 = time.time() + 秒
    try:
        with urllib.request.urlopen(req, timeout=秒) as r:
            for 原 in r:
                行 = 原.decode("utf-8", "replace").rstrip("\r\n")
                if 行.startswith("event: "):
                    种 = 行[7:]
                elif 行.startswith("data: "):
                    try:
                        体 = json.loads(行[6:] or "{}")
                    except Exception:
                        体 = {"_原文": 行[6:][:80]}
                    事件.append((种, 体))
                    if 直到 and 种 == 直到:
                        break
                    if 至多 and len(事件) >= 至多:
                        break
                if time.time() > 止:
                    break
    except urllib.error.HTTPError as e:
        return [("_HTTP", {"code": e.code})]
    except Exception as e:
        事件.append(("_断了", {"为什么": f"{type(e).__name__}: {e}"}))
    return 事件


# ── 夹具:一个**非终态**的任务 + 三条事件 + 一个临时 viewer ──────────────
# ⚠️ 类型故意用 `测试`:没有任何 Worker 认得它,所以 `取一个()` 按
# `能处理的类型们` 过滤时会跳过它 —— 它会稳稳停在「排队中」。
# 换成 prompt_run 就会被常驻 Worker 捞走跑完,于是「非终态」这个前提
# **在测试跑到一半的时候消失**,而红的理由会指向完全无关的地方。
临时工号 = "Usse" + uuid.uuid4().hex[:6]
任务 = "job_sse_" + uuid.uuid4().hex[:10]
成员 = "mem_" + uuid.uuid4().hex[:12]
终态任务 = "job_sse_done_" + uuid.uuid4().hex[:6]

print("\n\033[1m▸ 任务事件流(SSE)· 全后台最后一条「已实现未验」\033[0m")
print("  ⚠️ 空流和「什么都没发生」长得一样 —— 这份测试主要在打这一点")

try:
    with 事务() as c:
        # ⚠️ memberships 两个字段今天各咬过一次:
        #    `id` 是 NOT NULL(不给 → 当场报错,还算好认);
        #    `status` 可空(不给 'active' → **插进去了**,而每条读路径都捞不到,
        #    表现是别的地方 404)。
        c.execute(text("""insert into memberships
            (id, user_id, organization_id, project_id, role, status,
             special_grants, created_at, created_by, updated_at, revision)
            values (:i,:u,:o,:p,'viewer','active', cast('[]' as jsonb),
                    now(),'test-sse', now(), 1)"""),
                  {"i": 成员, "u": 临时工号, "o": ORG, "p": A})
        for jid, 状态 in ((任务, "排队中"), (终态任务, "已完成")):
            c.execute(text("""insert into jobs
                (id, organization_id, project_id, type, target_ref, status,
                 attempts, max_attempts, idempotency_key,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,'测试', cast('{}' as jsonb), :s, 0, 3, :k,
                        now(),'test-sse', now(), 1)"""),
                      {"i": jid, "o": ORG, "p": A, "s": 状态, "k": uuid.uuid4().hex})
        for n, kind in enumerate(("已受理", "开始", "展开模板"), start=1):
            c.execute(text("""insert into job_events
                (id, organization_id, project_id, job_id, seq, kind, payload,
                 at, created_at, created_by)
                values (:i,:o,:p,:j,:q,:k, cast(:pl as jsonb),
                        now(), now(), 'test-sse')"""),
                      {"i": "je_" + uuid.uuid4().hex[:12], "o": ORG, "p": A,
                       "j": 任务, "q": n, "k": kind,
                       "pl": json.dumps({"第几条": n}, ensure_ascii=False)})
        c.execute(text("""insert into job_events
            (id, organization_id, project_id, job_id, seq, kind, payload,
             at, created_at, created_by)
            values (:i,:o,:p,:j,1,'完成', cast(:pl as jsonb),
                    now(), now(), 'test-sse')"""),
                  {"i": "je_" + uuid.uuid4().hex[:12], "o": ORG, "p": A,
                   "j": 终态任务, "pl": json.dumps({"说明": "终态"}, ensure_ascii=False)})

    # ── ① 全量:三条事件都送到 ─────────────────────────────────────────
    print("\n▸ ① 不带游标:三条事件都送到")
    事 = 读流(f"{P}/jobs/{任务}/events", 临时工号, 至多=3, 秒=8)
    种们 = [k for k, _ in 事]
    序们 = [v.get("seq") for k, v in 事 if k == "进度"]
    ck("送出来的是「进度」事件", 种们[:3] == ["进度"] * 3, 种们)
    ck("三条按 seq 顺序都到了", 序们 == [1, 2, 3], 序们)
    ck("每条都带 kind 和 payload(只有 seq 的话界面上没东西可显示)",
       all(v.get("kind") and v.get("payload") is not None
           for k, v in 事 if k == "进度"),
       [v.get("kind") for k, v in 事 if k == "进度"])

    # ── ② 断线续传:不重发,也不跳过 ────────────────────────────────────
    print("\n▸ ② 带 from_seq 重连:**不重发,也不跳过**")
    # ⚠️ 这一条要同时钉住两个方向。只钉一个方向的判据会漏掉另一半:
    #   · 只断「没重发」→ 把 seq 3 也跳掉的实现照样过
    #   · 只断「收到了 3」→ 把 1、2 又送一遍的实现照样过
    # 而**多送一条**在界面上是重复一行(有人会发现),
    # **少送一条**是界面少一行(**没人会发现**)—— 后者更贵。
    事 = 读流(f"{P}/jobs/{任务}/events?from_seq=2", 临时工号, 至多=1, 秒=8)
    序们 = [v.get("seq") for k, v in 事 if k == "进度"]
    ck("from_seq=2 → **收到 seq 3**(没跳过它)", 3 in 序们, 序们)
    ck("from_seq=2 → **没重发 1 和 2**(重连不该让界面出现重复行)",
       1 not in 序们 and 2 not in 序们, 序们)
    # ⚠️ 这一条第一版是对着**非终态**那个任务打的,于是它什么都收不到、
    # 读流超时抛异常,而断言只写了「进度不在收到的里面」—— 于是它**绿了**,
    # 绿的理由是「流炸了」,不是「没送进度」。
    # > 一条只断「某个东西不在」的判据,任何一种失败都会让它绿。
    # 改成对**终态**任务打:这样一定会收到「结束」,于是能同时断两件事 ——
    # 收到了该收的、且一条进度都没有。**空手而归和成功地没有东西,分开了。**
    事 = 读流(f"{P}/jobs/{终态任务}/events?from_seq=99", 临时工号, 直到="结束", 秒=8)
    种们 = [k for k, _ in 事]
    ck("from_seq 比现有的都大 → **照样收到「结束」**(流本身是通的)",
       "结束" in 种们, 种们)
    ck("而且一条进度都不送(不是从头来一遍)", "进度" not in 种们, 种们)

    # ── ③ 终态:必须发「结束」,不能让客户端一直等 ───────────────────────
    print("\n▸ ③ 任务已经是终态:必须**说一声结束**")
    事 = 读流(f"{P}/jobs/{终态任务}/events", 临时工号, 直到="结束", 秒=8)
    种们 = [k for k, _ in 事]
    ck("发了「结束」事件(不发的话客户端会一直转圈,像「还在跑」)",
       "结束" in 种们, 种们)
    结 = dict((k, v) for k, v in 事).get("结束") or {}
    ck("「结束」里带最终 status(客户端要知道是完成还是失败)",
       结.get("status") == "已完成", 结)
    ck("「结束」里带**最后一个 seq**(断线重连的起点就是它)",
       isinstance(结.get("最后seq"), int), 结)

    # ── ④ 任务不存在:**要说出来**,不能是空流 ──────────────────────────
    print("\n▸ ④ 不存在的任务:空流是最危险的返回值")
    # ⚠️ 这个 id **必须是 ASCII**。第一版写的是 `job_根本没有这一条`,
    # 于是 `urllib` 在拼 URL 那一步就抛了 —— 判据红了,而红的理由
    # (「没说『没有这个任务』」)**指向接口**,真因在测试自己身上。
    # 用 curl 打同一个地址,接口第一时间就吐了 `event: 没有这个任务`。
    # 「协议边界上的中文」这一族今天第 6 次。
    事 = 读流(f"{P}/jobs/job_nope_{uuid.uuid4().hex[:8]}/events", 临时工号, 至多=1, 秒=6)
    种们 = [k for k, _ in 事]
    ck("**明说「没有这个任务」**,而不是开一条空流 —— "
       "空流和「这个任务还没产生事件」长得一模一样",
       "没有这个任务" in 种们, 种们 or "什么都没送")

    # ── ⑤ 跨项目:不确认「它在别的项目里存在」 ─────────────────────────
    print("\n▸ ⑤ 换个项目号拿同一个任务 id")
    # ⚠️ 这一条也不能只断「进度不在」—— 那样流炸了它也绿。
    # 量过(2026-09-29):这个临时工号只在 A 项目有成员记录,
    # 拿 B 项目的地址打,返回 **404 NO_MEMBERSHIP**。
    # 404 是有意的:403 会确认「这个任务在别的项目里存在」。
    事 = 读流(f"/api/v1/projects/{B}/jobs/{任务}/events", 临时工号, 至多=1, 秒=6)
    ck("换项目号 → **404**(不是 403 —— 403 等于确认「它在别的项目里存在」)",
       事 and 事[0][0] == "_HTTP" and 事[0][1].get("code") == 404, 事[:1])
    ck("而且一条进度都没送出去", "进度" not in [k for k, _ in 事], [k for k, _ in 事])

    # ── ⑥ 身份:没身份 → 401 ──────────────────────────────────────────
    print("\n▸ ⑥ 没身份")
    事 = 读流(f"{P}/jobs/{任务}/events", None, 至多=1, 秒=6)
    ck("没身份 → 401(在建流**之前**就拒,不是先建流再说无权)",
       事 and 事[0][0] == "_HTTP" and 事[0][1].get("code") == 401, 事[:1])

    # ── ⑦ §19.2 实时结果重新鉴权:流开着的时候撤权,它要停 ────────────────
    print("\n▸ ⑦ **流开着的时候把权限撤掉**(规格 §19.2「实时结果重新鉴权」)")
    # ⚠️ 这一条是这份测试里唯一一条**没法靠一次请求测出来**的:
    # 授权在请求进来那一刻判过一次,而流会开着很久。
    # 所以必须真的在流开着的时候动成员记录 ——
    # 「开流前就没权 → 403」测的是另一件事(而且它已经是 ⑥ 那条了)。
    收 = {}

    def 读到无权():
        收["事"] = 读流(f"{P}/jobs/{任务}/events?from_seq=3", 临时工号,
                      直到="无权", 秒=20)

    t = threading.Thread(target=读到无权, daemon=True)
    t.start()
    time.sleep(1.5)                       # 让流先开起来,进到轮询循环里
    with 事务() as c:
        撤 = c.execute(text("""update memberships set status='revoked',
                 updated_at=now(), revision=revision+1
               where id=:i returning user_id"""), {"i": 成员}).first()
    ck("撤权这一步真的改到了那条成员记录(改不到的话下面那条是空跑)",
       撤 is not None, 撤 and 撤[0])
    t.join(timeout=25)
    事 = 收.get("事") or []
    种们 = [k for k, _ in 事]
    ck("**流自己停了,并且说清为什么**(「无权」)—— "
       "权限撤回之后一条还开着的流不该继续送数据",
       "无权" in 种们, 种们 or "什么都没送")
    无 = dict((k, v) for k, v in 事).get("无权") or {}
    ck("「无权」里有人话说明(只断开不说明,看的人会当成网络抖动)",
       bool(无.get("说明")), 无)

finally:
    # ── 收尾:还原 ────────────────────────────────────────────────────
    # ⚠️ 放在 finally 里:上面任何一条断言抛了,这些也得清 ——
    # 一个被撤权的临时工号留在库里不要紧,**一条排队中的任务留着会进别人的积压数**。
    with 事务() as c:
        c.execute(text("delete from job_events where project_id=:p and job_id = any(:j)"),
                  {"p": A, "j": [任务, 终态任务]})
        c.execute(text("delete from jobs where project_id=:p and id = any(:j)"),
                  {"p": A, "j": [任务, 终态任务]})
        c.execute(text("delete from memberships where id=:i"), {"i": 成员})
    with 事务() as c:
        剩 = c.execute(text("""select count(*) from jobs
             where project_id=:p and id = any(:j)"""),
                      {"p": A, "j": [任务, 终态任务]}).scalar()
        剩员 = c.execute(text("select count(*) from memberships where id=:i"),
                       {"i": 成员}).scalar()
    print(f"\n▸ 收尾:造的任务剩 {剩} 条、临时工号剩 {剩员} 个"
          f"{'(都清干净了)' if not (剩 or 剩员) else ' ⚠️ **没清干净**'}")
    if 剩 or 剩员:
        挂.append("收尾没清干净")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ 过 ' + str(len(过)) + ' / 挂 0(夹具已清)'}")
if 挂:
    for x in 挂:
        print("   ·", x)
sys.exit(1 if 挂 else 0)
