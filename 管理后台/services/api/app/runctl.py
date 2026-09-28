#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行控制:暂停 / 继续 / 取消 / 核实外部状态 / 安全重试一步(§12.3、§17.1)。

## ⚠️ 这一组的每条接口都有同一件事要说清:**「请求」不是「已经」**

    pause   → `pause_requested`,**不是** `paused`
    cancel  → `cancel_requested`,**不是** `cancelled`

在途的调用未必立刻停。把「请求暂停」直接写成「已暂停」的后果:
界面显示已停,而模型还在跑、钱还在花 —— **而没有任何东西报错**。

## ⚠️ `cancel` 不能承诺撤销已发生的动作(§12.3)

取消只停**新调度**,并尝试掐掉在途请求。已经写出去的文件、
已经发出去的消息,取消不回来。所以返回里明说这件事 ——
一个让人以为「点了取消就没事了」的接口,比没有取消按钮危险。

## ⚠️ `reconcile` 去**查**真实外部状态,不直接重做动作

这条接口存在的全部理由:**HTTP 超时不代表对方没做事。**
超时之后重做一遍,可能就是第二次扣款。
"""
import json as _json
import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

import states as ST
from db import 事务, 连接
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
_机 = ST.找("execution_run")


def _新id(p):
    return f"{p}_{_uuid.uuid4().hex[:12]}"


def _取(c, 项目, rid, 锁=False):
    r = c.execute(text(f"""select * from execution_runs
                          where project_id=:p and id=:i and archived_at is null
                          {'for update' if 锁 else ''}"""),
                  {"p": 项目, "i": rid}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", "没有这次运行", "回运行列表重新进入")
    return dict(r)


def _要键和锁(idempotency_key, if_match, 体, 动作):
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  f"「{动作}」会改运行状态 —— 超时重发不许变成两次操作")
    rev = 体.get("revision")
    if rev is None and if_match:
        try:
            rev = int(str(if_match).strip('"'))
        except ValueError:
            rev = None
    if rev is None:
        raise _错(422, "VALIDATION", "要给 revision(或 If-Match 头)",
                  "**两个人同时操作一次运行,后到的不许静默覆盖** —— "
                  "输的那个人看不到自己的操作被盖掉了",
                  field_errors={"revision": "必填"})
    return int(rev)


def _换状态(c, 项目, rid, 老行, 新状态, 给的rev, *, 谁, 动作, 额外=None):
    """带乐观锁和状态机校验的状态流转。**流转不合法当场抛,不静默放行。**"""
    if int(给的rev) != int(老行["revision"] or 0):
        raise _错(409, "REVISION_CONFLICT",
                  f"这次运行已经被改过了(你拿到 {给的rev},现在 {老行['revision']})",
                  f"**另一个人已经操作过了**,当前状态「{老行['status']}」。"
                  f"刷新再决定 —— 不要用旧 revision 覆盖")
    if not ST.能不能走("execution_run", 老行["status"], 新状态):
        raise _错(409, "BAD_TRANSITION",
                  f"「{老行['status']}」不能走到「{新状态}」",
                  f"状态机(contract/states.py)允许的是:"
                  f"{_机['流转'].get(老行['status'], [])}。"
                  f"**不静默放行** —— 一个绕过状态机的流转会让后面每一步的前提都不成立")
    列 = ["status=:st", "updated_at=now()", "revision=:rev"]
    参 = {"st": 新状态, "rev": int(老行["revision"] or 0) + 1,
         "p": 项目, "i": rid, "old": 老行["revision"]}
    for k, v in (额外 or {}).items():
        列.append(f"{k}=:{k}")
        参[k] = v
    n = c.execute(text(f"""update execution_runs set {', '.join(列)}
                          where project_id=:p and id=:i and revision=:old"""),
                  参).rowcount
    if n == 0:
        raise _错(409, "REVISION_CONFLICT", "刚刚有人改了这次运行",
                  "并发:拿到行之后、写之前被人改了。刷新再试")
    c.execute(text("""insert into run_events (id, organization_id, project_id,
            execution_run_id, seq, event_type, payload, created_at, created_by)
        values (:i,:o,:p,:r,
                coalesce((select max(seq)+1 from run_events
                           where project_id=:p and execution_run_id=:r), 1),
                :et, cast(:pl as jsonb), now(), :by)"""),
              {"i": _新id("re"), "o": 老行["organization_id"], "p": 项目, "r": rid,
               "et": f"run.{动作}",
               "pl": _json.dumps({"从": 老行["status"], "到": 新状态, "谁": 谁},
                                 ensure_ascii=False), "by": 谁})
    return 参["rev"]


@router.post(前缀 + "/execution-runs/{run_id}/pause", status_code=202)
async def 请求暂停(project_id: str, run_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             if_match: str = Header(default=None, alias="If-Match"),
             me: 身份 = Depends(要权限("运行编排测试"))):
    """**是「请求」暂停,不是「已暂停」**(§12.3)。

    在途的调用未必立刻停。状态是 `pause_requested`,
    等执行器到下一个检查点才会变成 `paused` ——
    直接写 `paused` 的后果是界面显示已停而模型还在跑、钱还在花。
    """
    体 = await request.json() if await request.body() else {}
    rev = _要键和锁(idempotency_key, if_match, 体, "暂停")
    with 事务() as c:
        r = _取(c, project_id, run_id, 锁=True)
        if r["status"] == "pause_requested":
            return {"id": run_id, "status": r["status"], "改了吗": False,
                    "note": "已经在「暂停请求中」了 —— 重复请求不改变什么"}
        新rev = _换状态(c, project_id, run_id, r, "pause_requested", rev,
                     谁=me.user_id, 动作="pause",
                     额外={"pause_requested": True})
    return {"id": run_id, "status": "pause_requested", "改了吗": True,
            "revision": 新rev,
            "note": ("**这是「请求暂停」,不是「已暂停」** —— 在途调用未必立刻停。"
                     "等执行器走到下一个检查点才会变成 `paused`。"
                     "在那之前模型可能还在跑,钱可能还在花")}


@router.post(前缀 + "/execution-runs/{run_id}/resume", status_code=202)
async def 继续(project_id: str, run_id: str, request: Request,
           idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
           if_match: str = Header(default=None, alias="If-Match"),
           me: 身份 = Depends(要权限("运行编排测试"))):
    """从同一检查点继续。**保留用量和循环计数**,**重新鉴权**。

    ⚠️ **不把暂停期间更新的 Prompt 静默装入旧 Run**:
    Run 跑的是它启动时那一版定义(`definition_hash` 钉着)。
    静默换新版的后果是**同一次运行前后用了两套提示词**,而结果看起来正常。
    """
    体 = await request.json() if await request.body() else {}
    rev = _要键和锁(idempotency_key, if_match, 体, "继续")
    with 事务() as c:
        r = _取(c, project_id, run_id, 锁=True)
        # ⚠️ **`pause_requested` 上点「继续」不是继续,是「撤销暂停请求」。**
        # 状态机不允许 `pause_requested → queued`,而那是对的:
        # 它还**没真的停下来**,谈不上「从检查点继续」。
        #
        # 放宽状态机去让它过,是拿一个真实区别去换一次少写代码 ——
        # 而丢掉的那个区别正是「请求暂停」和「已暂停」的区别,
        # 这一组接口的全部意义就在那儿。
        if r["status"] == "pause_requested":
            raise _错(409, "NOT_PAUSED_YET",
                      "这次运行**还没真的停下来**(现在是「暂停请求中」)",
                      "它还在跑,只是收到了暂停请求 —— 谈不上「从检查点继续」。"
                      "要撤销暂停请求,那是另一个动作(现在还没做);"
                      "要等它停,刷新看状态变成 `paused` 再点继续")
        # ⚠️ **重新鉴权** —— 权限可能在暂停期间被撤回了。
        # 这里靠 `要权限` 依赖已经判过一次(每个请求都重判),
        # 但那判的是「能不能操作运行」。真正执行时工具网关还会再判一次。
        新rev = _换状态(c, project_id, run_id, r, "queued", rev,
                     谁=me.user_id, 动作="resume",
                     额外={"pause_requested": False})
    return {"id": run_id, "status": "queued", "revision": 新rev,
            "note": ("从同一检查点继续,**用量和循环计数保留**(没有重置)。"
                     "⚠️ 跑的仍然是启动时那一版定义 —— "
                     "**暂停期间更新的 Prompt 不会被静默装进来**:"
                     "同一次运行前后用两套提示词,结果看起来会很正常")}


@router.post(前缀 + "/execution-runs/{run_id}/cancel", status_code=202)
async def 请求取消(project_id: str, run_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             if_match: str = Header(default=None, alias="If-Match"),
             me: 身份 = Depends(要权限("运行编排测试"))):
    """停止新调度并尝试取消在途请求。

    ⚠️ **不能承诺撤销已发生的动作**(§12.3)。已经写出去的文件、
    已经发出去的消息,取消不回来 —— 要等执行器核实。
    一个让人以为「点了取消就没事了」的接口,比没有取消按钮危险。
    """
    体 = await request.json() if await request.body() else {}
    rev = _要键和锁(idempotency_key, if_match, 体, "取消")
    with 事务() as c:
        r = _取(c, project_id, run_id, 锁=True)
        if r["status"] in _机["终态"]:
            # ⚠️ **保留真实终态,不谎报成已取消**(§11.5)。
            # 和 `jobs.收尾` 那条同一个道理:一次已经成功的运行被标成
            # 「已取消」,会让人以为它的产物不存在。
            return {"id": run_id, "status": r["status"], "改了吗": False,
                    "note": (f"这次运行已经结束了(「{r['status']}」)—— "
                             f"**保留真实终态,不谎报成已取消**。"
                             f"它的产物是真的,取消不掉")}
        if r["status"] == "cancel_requested":
            return {"id": run_id, "status": r["status"], "改了吗": False,
                    "note": "已经在「取消请求中」了"}
        # ⚠️ **还没开跑的直接取消,不走「取消请求中」。**
        # 状态机里 `queued`/`paused`/`waiting_*` 只能直接到 `cancelled` ——
        # 那是对的:**没有在途调用要掐,所以没有「请求」这一档**。
        # 硬塞一个 `cancel_requested` 的坏法:界面上出现一个
        # 永远不会变成 `cancelled` 的中间态(没有执行器会去处理它)。
        直接取消 = "cancelled" in _机["流转"].get(r["status"], [])
        目标 = "cancelled" if 直接取消 else "cancel_requested"
        新rev = _换状态(c, project_id, run_id, r, 目标, rev,
                     谁=me.user_id, 动作="cancel",
                     额外={"cancel_requested": True})
        if 直接取消:
            return {"id": run_id, "status": "cancelled", "改了吗": True,
                    "revision": 新rev,
                    "note": (f"这次运行还没开跑(之前是「{r['status']}」),"
                             f"**没有在途调用要掐,所以直接取消了** —— "
                             f"不走「取消请求中」那一档。"
                             f"⚠️ 如果它之前跑过又暂停了,**已经发生的动作仍然撤不回来**")}
    return {"id": run_id, "status": "cancel_requested", "改了吗": True,
            "revision": 新rev,
            "note": ("**这是「请求取消」,不是「已取消」。** 它停的是**新调度**,"
                     "并尝试掐掉在途请求。⚠️ **已经发生的动作撤不回来** —— "
                     "写出去的文件、发出去的消息,取消不掉。"
                     "要知道到底做了什么,用 `/reconcile` 去查真实外部状态")}


@router.post(前缀 + "/execution-runs/{run_id}/reconcile", status_code=202)
async def 核实外部状态(project_id: str, run_id: str, request: Request,
               idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
               me: 身份 = Depends(要权限("运行编排测试"))):
    """去**查**真实外部状态,**不直接重做动作**(§17.1)。

    ⚠️ 这条接口存在的全部理由:**HTTP 超时不代表对方没做事。**
    超时之后重做一遍,可能就是第二次扣款、第二次发消息。
    所以这里做的是「去问一遍到底成没成」,而不是「再干一次」。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "核实会去查外部系统 —— 重发不许变成两次查询风暴")
    with 事务() as c:
        r = _取(c, project_id, run_id, 锁=True)
        if r["status"] in _机["终态"]:
            return {"id": run_id, "status": r["status"], "改了吗": False,
                    "note": "已经是终态了,没什么可核实的"}
        # 查这次运行里**有多少步处于「不确定」** —— 那些才是要核实的
        待核 = c.execute(text("""
            select id, node_id, status, error_code from run_steps
             where project_id=:p and execution_run_id=:r
               and status = any(:st)
        """), {"p": project_id, "r": run_id,
               "st": ["状态待核实", "reconciling", "incomplete"]}).mappings().all()
        新rev = _换状态(c, project_id, run_id, r, "reconciling",
                     int(r["revision"] or 0), 谁=me.user_id, 动作="reconcile")
    return {"id": run_id, "status": "reconciling", "revision": 新rev,
            "要核实的步数": len(待核),
            "要核实的步": [dict(x) for x in 待核],
            "note": ("**去查,不重做**(§17.1)。HTTP 超时不代表对方没做事 —— "
                     "超时之后重做一遍,可能就是第二次扣款。"
                     + ("⚠️ 这次运行**一步不确定的都没有** —— "
                        "那核实什么?这可能说明状态记漏了,值得看一眼"
                        if not 待核 else ""))}


@router.post(前缀 + "/execution-runs/{run_id}/steps/{step_id}/retry",
             status_code=202)
async def 安全重试这一步(project_id: str, run_id: str, step_id: str, request: Request,
                 idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
                 me: 身份 = Depends(要权限("运行编排测试"))):
    """重试一步。**「安全」两个字是判据,不是形容词。**

    ⚠️ 只有**确定没成功**的步才能重试。状态是「不确定」的(超时、待核实)
    **不许重试** —— 那正是 `/reconcile` 要先跑的原因:
    重试一个可能已经成功的写操作,就是第二次扣款。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "重试会真的再跑一次 —— 超时重发不许变成跑两次")
    with 事务() as c:
        r = _取(c, project_id, run_id, 锁=True)
        s = c.execute(text("""select * from run_steps
                             where project_id=:p and execution_run_id=:r and id=:s"""),
                      {"p": project_id, "r": run_id, "s": step_id}).mappings().first()
        if not s:
            raise _错(404, "NOT_FOUND", "这次运行里没有这一步", "回运行详情看步骤列表")
        s = dict(s)
        不确定 = {"状态待核实", "reconciling", "running", "waiting_input"}
        if s["status"] in 不确定:
            raise _错(409, "STEP_NOT_SAFE_TO_RETRY",
                      f"这一步现在是「{s['status']}」—— **状态不确定的不许重试**",
                      "先跑 `/reconcile` 去查真实外部状态。"
                      "**重试一个可能已经成功的写操作,就是第二次扣款** —— "
                      "「安全重试」里的「安全」是判据,不是形容词")
        if s["status"] == "succeeded":
            raise _错(409, "STEP_ALREADY_SUCCEEDED",
                      "这一步已经成功了,不重试",
                      "成功的步重试一遍只会产生第二次副作用。"
                      "要改结果请从这一步另开一次调试运行")
        # ⚠️ **attempt 从「这个逻辑动作一共试过几次」算,不是从被点的那一步算。**
        #
        # 第一版拿 `s["attempt"] + 1`,于是对同一步点两次重试会算出同一个
        # attempt、同一个 execution_key → **撞唯一键 500**。
        # 而人确实可能对同一步点两次重试(第一次重试又失败了)。
        #
        # `logical_action_id` 是**跨重试不变的锚** —— 用它数,才数得对。
        # ⚠️⚠️ **`= NULL` 永远为假。** 第一版写 `logical_action_id = :la`,
        # 而这批数据的 `logical_action_id` **是 NULL** —— 它匹配不到任何行
        # (包括那条自己也是 NULL 的),于是 count 永远 0、attempt 永远 2、
        # execution_key 永远一样 → **第二次重试撞唯一键 500**。
        # 而它**不报错**,只是每次算出同一个 key。
        #
        # 没有锚的时候要用别的东西数,而且**要把「没有锚」这件事说出来** ——
        # 它意味着外部系统认不出「这是同一件事」,那才是更大的问题。
        有锚 = s["logical_action_id"] is not None
        if 有锚:
            试过几次 = c.execute(text("""
                select count(*) from run_steps
                 where project_id=:p and execution_run_id=:r
                   and logical_action_id = :la
            """), {"p": project_id, "r": run_id,
                   "la": s["logical_action_id"]}).scalar() or 1
        else:
            # 退而求其次:按**同一个节点 + 同一条迭代路径**数。
            # 这不如逻辑动作 id 准(它不跨 run),但比 `= NULL` 强 ——
            # 至少它数得出来。
            试过几次 = c.execute(text("""
                select count(*) from run_steps
                 where project_id=:p and execution_run_id=:r
                   and node_id = :nd
                   and coalesce(iteration_path, '') = coalesce(:it, '')
            """), {"p": project_id, "r": run_id, "nd": s["node_id"],
                   "it": s["iteration_path"]}).scalar() or 1
        新id = _新id("rs")
        c.execute(text("""insert into run_steps (id, organization_id, project_id,
                execution_run_id, node_id, kind, iteration_path, attempt,
                execution_key, logical_action_id, input_ref, status,
                created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:r,:nd,:k,:it,:at,:ek,:la, cast(:ir as jsonb),
                    'queued', now(), :by, now(), 1)"""),
                  {"i": 新id, "o": r["organization_id"], "p": project_id, "r": run_id,
                   "nd": s["node_id"], "k": s["kind"], "it": s["iteration_path"],
                   # ⚠️ **attempt 加一,而 `logical_action_id` 不变** ——
                   # 逻辑动作 id 是幂等的锚:同一个逻辑动作重试多次,
                   # 外部系统靠它认出「这是同一件事」。换了它就等于换了一件事。
                   "at": 试过几次 + 1,
                   # ⚠️ 后缀加在**原始 key** 上,不是在上一次的 key 上叠。
                   # 第一版写 `f"{s['execution_key']}#retry{n}"`,而重试出来
                   # 的那一步**自己也是重试产物** —— key 变成
                   # `…#retry2#retry3`,越拼越长,而且第二次重同一步时
                   # **撞唯一键 → 500**。
                   # (`uq_run_steps_project_id_execution_key` 拦住了它 ——
                   #  **能用约束表达的不要用判据表达**,又一次。)
                   "ek": (str(s["execution_key"]).split("#retry")[0]
                          + f"#retry{试过几次 + 1}"),
                   "la": s["logical_action_id"],
                   "ir": _json.dumps(s["input_ref"], ensure_ascii=False)
                         if s["input_ref"] is not None else None,
                   "by": me.user_id})
    return {"id": run_id, "新的步": 新id, "重试的是": step_id,
            "attempt": 试过几次 + 1, "之前试过": 试过几次, "有幂等锚吗": 有锚,
            "note": ("**新建了一步,没有改旧那步** —— 旧那步的失败记录留着当证据。"
                     + ("⚠️ `logical_action_id` **没变**:它是幂等的锚,"
                        "外部系统靠它认出「这是同一件事」,换了就等于换了一件事"
                        if 有锚 else
                        "🔴 **这一步没有 `logical_action_id`** —— 那个幂等的锚是空的。"
                        "重试次数只能按「同一节点 + 同一迭代路径」数,而更要紧的是:"
                        "**外部系统认不出「这是同一件事」**,重试可能变成第二次副作用。"
                        "这要人看"))}
