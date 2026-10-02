#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交割六页里那四条接口的断言(调用链详情 / A3 接收端 / 实验对比 / 人工待办)。

## 为什么单独有这一份:**手工 curl 过一次不算「验过」**

这四条 09-28 之前在 `docs/实现进度.md` 上标着 ✅,而**没有任何可重跑的断言打过它们** ——
那个 ✅ 来自我自己在开着路由记账的服务上手敲的几下 curl。
换了一台机器、换了一个人、或者只是重跑一次报告,它们就变回 🟡。

> **「验过」= 有可重跑的断言打过,不是「有人手工试过一次」。**
> 手工试过一次和从没试过,在报告上长得一模一样,而**报告是给不在场的人看的**。

(发现的经过也值得记:我加了五条数据集接口之后重跑报告,「验过」从 50 掉到 49。
 掉下去的不是我改坏的东西,而是**那个 50 本来就虚**。
 棘轮拦住了它 —— 而正确的修法是把断言补上,不是把下限调低。)

## 这一份守的四句话

**① 脱敏是给形状,不是截断。** 没有那条专项授权时,`GET /traces/{id}` 里
   真实业务内容只给键名和长度 —— 而**截断到 100 字,那 100 字仍然是原文**。
   所以断言是「有授权的看到的内容,在无授权的响应里一个字都找不到」。

**② 挂不上调用的判读,拒掉比静默收下好。** `POST /feedback` 给一个不存在的
   `trace_id` → 422,**不是**悄悄存成 NULL —— 存下来之后这条判读看起来挂在
   一次调用上,而那次调用不存在。

**③ 换了题或换了判据的两轮不可比。** 分数的差别可能全来自题目或评分方式,
   而两个数字并排放着**看起来**就是可比的。

**④ 列表上不给批准按钮(§12.1)。** 在接口上的形式是:
   **批准需要的材料(证据 / 脱敏参数 / 允许编辑的字段)只在详情里** ——
   看不到材料就批不了,而这正是那条界面约束想拦的事。

⚠️ 前提 `make dev`。连不上就退非 0,不静默跳过。
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

尾 = uuid.uuid4().hex[:8]

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁="U001", 头=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    for k, v in (头 or {}).items():
        req.add_header(k, v)
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


from sqlalchemy import text            # noqa: E402
from db import 事务, 连接                # noqa: E402


def 造一条待办():
    """直接写库造前提:一条 `execution_run` + 一条 pending 待办。**全链自建。**

    ⚠️ **不消耗库里现成的 pending。** 用现成的话这一份跑一次就消耗掉一条
    (批准是终态),跑三次之后它开始报「没有待办」——
    而那种红看起来像功能坏了。**判据不许依赖会被自己消耗掉的资源。**

    ## ⚠️ 2026-10-02 改掉的三件(上一版只做到「不消耗」)

    **(一) 它还是要「读」一条现成的 pending 当模板。** 于是在 CI 上
    (**从零建库**)库里一条 pending 都没有,它 `sys.exit(1)` ——
    **整份测试一条断言都不跑**,而报出来的是「先跑 seed_human_requests.py」。
    那份 seed 在 CI 里**注定灌不上**:它要求库里先有一次 `execution_run`,
    而运行是测试跑出来的,灌数据那一步必然还没有。
    > 「不消耗别人的数据」和「不读别人的数据」**是两件事**。

    **(二) 照抄的那条是随机的** —— `limit 1` 不带 `order by`。
    而 seed 的六条里**故意有一条「没人能批」**(候选角色 `["editor","viewer"]`)。
    哪天抄到那一条,批准那条断言就会红 —— **而那种红看起来像功能坏了**。
    所以这里把角色**写死**成正常那条的 `["approver", "admin"]`,不靠运气。

    **(三) 它不清理。** 本地库里积到了 42 条 `hr_test_*`
    (48 条待办里只有 6 条是真 seed 的),`human_decisions` 同样 42 条。
    每次用新 id,所以「跑得起第二遍」是绿的 —— 而它一直在往库里堆。
    > **「跑得起第二遍」和「不留垃圾」是两件事**,而第一条绿着的时候
    > 第二条完全看不见。现在 `清掉待办()` 在收尾里删。
    """
    rid = f"hr_test_{尾}"
    运行id = f"run_test_{尾}"
    载荷 = {"path": "/out/报价单-李明明.pdf",
           "content": "云锦礼服定制报价:九米料,工期五个月……" * 12,
           # ⚠️ **故意放一个 `secret_ref`** —— 详情接口该把它显示成
           # `<已脱敏>`。照抄 seed 的蓝本,这样两条路验的是同一件事。
           "secret_ref": "conn:deepseek#key"}
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        # `tool_version_id` 有外键 → `tool_versions`。**只读一条,不消耗它**
        # (工具版本不是终态资源)。拿不到就留 None —— 它可空。
        tv = c.execute(text("""select id from tool_versions where project_id=:p
                             order by created_at limit 1"""), {"p": 项目}).scalar()
        # ⚠️ `trace_id` 留空:它可空,而造一条 trace 只为满足外键没意义。
        c.execute(text("""insert into execution_runs
            (id, organization_id, project_id, kind, status, execution_mode,
             created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'agent','running','live', now(),'test', now(), 1)"""),
                  {"i": 运行id, "o": org, "p": 项目})
        # ⚠️ `payload_ref` 这一列是 **TEXT**(不是 JSONB)—— 塞 json 串,
        # 不要 `cast(... as jsonb)`。seed 那边写的是 cast,它靠一次隐式转换
        # 落进 text 列;这里直接给串,少一次转换也少一个会漂的地方。
        c.execute(text("""insert into human_requests (id, organization_id, project_id,
                              execution_run_id, kind, payload_ref,
                              allowed_fields, candidate_roles, status, expires_at,
                              arguments_hash, tool_version_id, target_ref, risk_note,
                              created_at, created_by, updated_at, revision)
                         values (:i,:o,:p,:r,'tool_write',:pr,
                                 cast(:af as jsonb), cast(:cr as jsonb),
                                 'pending', now() + interval '6 hours',
                                 :ah,:tv, cast(:tg as jsonb), :rn,
                                 now(), 'test', now(), 1)"""),
                  {"i": rid, "o": org, "p": 项目, "r": 运行id,
                   "pr": json.dumps(载荷, ensure_ascii=False),
                   "af": json.dumps(["content"], ensure_ascii=False),
                   # **写死**,不照抄 —— 见上面 (二)。
                   "cr": json.dumps(["approver", "admin"], ensure_ascii=False),
                   "ah": "sha256:" + hashlib.sha256(
                       json.dumps(载荷, ensure_ascii=False,
                                  sort_keys=True).encode()).hexdigest(),
                   "tv": tv,
                   "tg": json.dumps({"资源": "/out/报价单-李明明.pdf",
                                     "动作": "写文件"}, ensure_ascii=False),
                   "rn": "[夹具] 往 /out 写一个客户可见的报价单 —— "
                         "**不可逆**:写出去之后顾客可能已经看到了"})
    return rid


def 清掉待办():
    """删掉这一轮造的待办、它的决定行和那条运行。**按外键顺序。**

    ⚠️ 顺序错了的后果是收尾里抛一个 FK 错 —— 而**失败发生在收尾里,
    最容易被当成没事**(主体断言已经打完绿勾了)。
    """
    with 事务() as c:
        c.execute(text("delete from human_decisions where project_id=:p "
                       "and human_request_id=:i"), {"p": 项目, "i": f"hr_test_{尾}"})
        c.execute(text("delete from human_requests where project_id=:p and id=:i"),
                  {"p": 项目, "i": f"hr_test_{尾}"})
        c.execute(text("delete from execution_runs where project_id=:p and id=:i"),
                  {"p": 项目, "i": f"run_test_{尾}"})


def 两个实验(同不同):
    """挑两个评测实验:`同不同=True` 要同一个数据集版本,False 要不同的。"""
    with 连接() as c:
        rs = [dict(r) for r in c.execute(text("""
            select id, dataset_version_id from evaluations
             where project_id=:p order by id"""), {"p": 项目}).mappings()]
    按版 = {}
    for r in rs:
        按版.setdefault(r["dataset_version_id"], []).append(r["id"])
    if 同不同:
        for v, ids in 按版.items():
            if len(ids) >= 2:
                return ids[0], ids[1]
        return None, None
    版 = [v for v in 按版 if 按版[v]]
    if len(版) < 2:
        return None, None
    return 按版[版[0]][0], 按版[版[1]][0]


def main():
    print("\n\033[1m▸ 交割四条接口 · 把「手工 curl 过」换成可重跑的断言\033[0m")

    # ── 一、调用链详情:脱敏给形状,不是截断 ──────────────────────────
    码, 体 = 打("GET", f"{P}/traces")
    ck("GET /traces 200", 码 == 200, 码)
    条 = (体 or {}).get("items") or (体 or {}).get("运行记录") or []
    if not 条:
        print("     一条 trace 都没有 —— 先 make seed-demo"); sys.exit(1)
    tid = 条[0].get("id")

    码无, 无授权 = 打("GET", f"{P}/traces/{tid}", 谁="U002")     # editor:没有那条授权
    码有, 有授权 = 打("GET", f"{P}/traces/{tid}", 谁="U004")     # annotator:有
    ck("GET /traces/{id} 两个身份都 200", 码无 == 200 and 码有 == 200, (码无, 码有))
    ck("有授权和没授权拿到的**不是同一份**", 无授权 != 有授权,
       "一样就说明那条专项授权没起作用")
    # 形状不是截断:有授权那份里的业务内容,在无授权那份里**一个字都不该出现**
    无文 = json.dumps(无授权, ensure_ascii=False)
    有文 = json.dumps(有授权, ensure_ascii=False)
    长串 = sorted(set(_长字符串(有授权)) - set(_长字符串(无授权)), key=len, reverse=True)
    ck("脱敏是给形状不是截断(原文的片段在无授权那份里找不到)",
       all(s[:24] not in 无文 for s in 长串[:5]) if 长串 else True,
       [s[:24] for s in 长串[:2]])
    ck("无授权那份里出现了形状标记(键名 + 长度)", "字>" in 无文 or "·" in 无文,
       无文[:110])
    del 有文

    # ── 二、A3 接收端:挂不上的判读拒掉,不静默收下 ─────────────────────
    键 = f"lxfb-test-{uuid.uuid4().hex[:10]}"
    码, 体 = 打("POST", f"{P}/feedback",
              {"判读": "改判", "trace_id": tid, "世界日期": "2026-09-28"},
              谁="U004", 头={"Idempotency-Key": 键})
    ck("POST /feedback 201", 码 == 201 and (体 or {}).get("记了吗") is True,
       (码, (体 or {}).get("记了吗")))
    第一个 = (体 or {}).get("id")
    码, 体 = 打("POST", f"{P}/feedback",
              {"判读": "改判", "trace_id": tid, "世界日期": "2026-09-28"},
              谁="U004", 头={"Idempotency-Key": 键})
    ck("同一个幂等键再发 → 返回原记录,**采纳率的分母没被撑大**",
       (体 or {}).get("id") == 第一个 and (体 or {}).get("记了吗") is False,
       ((体 or {}).get("id"), (体 or {}).get("记了吗")))
    码, 体 = 打("POST", f"{P}/feedback", {"判读": "改判", "trace_id": tid},
              谁="U004")
    ck("不带幂等键 → 409(同一条判读重复上报不许算两次)",
       码 == 409 and (体 or {}).get("code") == "IDEMPOTENCY_KEY_REQUIRED",
       (码, (体 or {}).get("code")))
    码, 体 = 打("POST", f"{P}/feedback",
              {"判读": "改判", "trace_id": "tr_不存在的号", "世界日期": "2026-09-28"},
              谁="U004", 头={"Idempotency-Key": f"lxfb-test-{uuid.uuid4().hex[:8]}"})
    ck("不存在的 trace_id → 422 TRACE_NOT_FOUND(**不静默存成 NULL**)",
       码 == 422 and (体 or {}).get("code") == "TRACE_NOT_FOUND",
       (码, (体 or {}).get("code")))
    码, 体 = 打("POST", f"{P}/feedback",
              {"判读": "已改判", "外部trace": "x1", "世界日期": "2026-09-28"},
              谁="U004", 头={"Idempotency-Key": f"lxfb-test-{uuid.uuid4().hex[:8]}"})
    ck("词表外的判读(`已改判`)→ 422(一个拼错的判读会自成一档)", 码 == 422, 码)

    # ── 三、实验对比:换了题或换了判据的两轮不可比 ──────────────────────
    a, b = 两个实验(True)
    if a:
        码, 体 = 打("GET", f"{P}/evaluations/compare?a={a}&b={b}")
        ck("同一个数据集版本的两轮 → 200 且给出可比性判断",
           码 == 200 and "可比吗" in (体 or {}) and (体 or {}).get("为什么"),
           (码, (体 or {}).get("可比吗")))
    a2, b2 = 两个实验(False)
    if a2:
        码, 体 = 打("GET", f"{P}/evaluations/compare?a={a2}&b={b2}")
        ck("**跨数据集版本 → 可比吗=false**,并说清「跑的不是同一套题」",
           码 == 200 and (体 or {}).get("可比吗") is False
           and "同一套题" in str((体 or {}).get("为什么")),
           (码, str((体 or {}).get("为什么"))[:70]))
    else:
        ck("跨数据集版本的一对", False, "库里凑不出来 —— 先 python3 tools/seed_evals.py")
    码, 体 = 打("GET", f"{P}/evaluations/compare?a={a or 'ev_x'}")
    ck("只给一个 id → 422(对比必须两边都给)", 码 == 422, 码)

    # ── 四、人工待办:列表不给批准的材料;批准要幂等键 + 乐观锁 ──────────
    rid = 造一条待办()
    码, 列 = 打("GET", f"{P}/human-requests", 谁="U006")
    ck("GET /human-requests 200", 码 == 200, 码)
    行 = [x for x in (列 or {}).get("items", []) if x.get("id") == rid]
    ck("刚造的那条在列表里", bool(行), rid)
    if 行:
        材料 = [k for k in ("证据", "脱敏参数", "允许编辑的字段") if k in 行[0]]
        ck("**列表上不给批准要用的材料**(§12.1:列表上不给批准按钮)",
           not 材料, 材料 or "列表里只有状态和能不能处理")
    码, 详 = 打("GET", f"{P}/human-requests/{rid}", 谁="U006")
    ck("GET /human-requests/{id} 200", 码 == 200, 码)
    有材料 = [k for k in ("证据", "脱敏参数", "允许编辑的字段") if k in (详 or {})]
    ck("详情里**有**那些材料(看不到材料就批不了)", len(有材料) == 3, 有材料)
    rev = ((详 or {}).get("请求") or {}).get("revision")

    码, 体 = 打("POST", f"{P}/human-requests/{rid}/decisions",
              {"decision": "approved", "request_revision": rev}, 谁="U006")
    ck("批准不带幂等键 → 409", 码 == 409, 码)
    码, 体 = 打("POST", f"{P}/human-requests/{rid}/decisions",
              {"decision": "approved", "request_revision": rev}, 谁="U003",
              头={"Idempotency-Key": f"hd-{uuid.uuid4().hex[:8]}"})
    ck("viewer 批准 → 403(**专项授权也打不开这个格子**:有专门的 approver 角色)",
       码 == 403, 码)
    码, 体 = 打("POST", f"{P}/human-requests/{rid}/decisions",
              {"decision": "已批准", "request_revision": rev}, 谁="U006",
              头={"Idempotency-Key": f"hd-{uuid.uuid4().hex[:8]}"})
    ck("中文的 decision → 422(词表是 approved/rejected/info_requested)", 码 == 422, 码)
    键2 = f"hd-{uuid.uuid4().hex[:10]}"
    码, 体 = 打("POST", f"{P}/human-requests/{rid}/decisions",
              {"decision": "approved", "request_revision": rev}, 谁="U006",
              头={"Idempotency-Key": 键2})
    ck("approver 批准 → 201", 码 == 201, (码, (体 or {}).get("code")))
    码, 体2 = 打("POST", f"{P}/human-requests/{rid}/decisions",
               {"decision": "approved", "request_revision": rev}, 谁="U006",
               头={"Idempotency-Key": 键2})
    # ⚠️ 比的是 `决定id`,而**这一条第一次跑就抓到一个真 bug**:
    # 上一版新建那条返回 `id = 待办id`,幂等重放返回 `id = 决定行的 id` ——
    # 同一个接口、同一个字段名、两种 id,而两种都长得像合法 id。
    ck("同一个幂等键再批一次 → 同一条决定,不算第二条",
       码 in (200, 201) and (体2 or {}).get("决定id") == (体 or {}).get("决定id")
       and (体2 or {}).get("记了吗") is False,
       ((体 or {}).get("决定id"), (体2 or {}).get("决定id")))
    ck("两条路径的字段名一样(前端读 `新的 revision`,重放时拿不到会显示 rev undefined)",
       set(体 or {}) - {"处理人"} == set(体2 or {}) - {"处理人"},
       (sorted(set(体 or {}) ^ set(体2 or {}))))
    码, 详2 = 打("GET", f"{P}/human-requests/{rid}", 谁="U006")
    ck("批完之后状态是终态,且决定历史里有那一条",
       ((详2 or {}).get("请求") or {}).get("status") == "approved"
       and len((详2 or {}).get("决定历史") or []) >= 1,
       (((详2 or {}).get("请求") or {}).get("status"),
        len((详2 or {}).get("决定历史") or [])))

    清掉待办()
    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}(夹具已清)")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


def _长字符串(x, 出=None):
    """把响应里所有「看起来是业务内容」的长字符串收集起来(≥12 字)。"""
    出 = [] if 出 is None else 出
    if isinstance(x, str):
        if len(x) >= 12:
            出.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            _长字符串(v, 出)
    elif isinstance(x, list):
        for v in x:
            _长字符串(v, 出)
    return 出


if __name__ == "__main__":
    sys.exit(main())
