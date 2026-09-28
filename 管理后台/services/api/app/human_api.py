#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工待办(规格 §12 / §16.3 / §17.1「人工待办」那一组)。

    GET  /human-requests              列表 —— **列表上不给批准按钮**
    GET  /human-requests/{id}         详情 —— 具体工具、脱敏参数、影响对象
    POST /human-requests/{id}/decisions  处理

## 为什么这一组非做不可

`runtime/tool_gateway.py` 的闸**已经在拦**不可逆写入了:没有生效批准就拒。
而在这之前**没有任何代码能生产一条批准** —— 被拦住的东西永远出不去。
> **一道拦得住但没有放行入口的闸,是一个做了一半的机制。**
> 而它在检查上是绿的:「没有生效批准的不可逆写入被挡住」照样过。

## ⚠️ 契约里两条**界面设计**的约束,不是技术约束

**① 禁止在列表直接批量批准外部写操作**(§12.1)——
批量批准的界面会让人按「全选」,而那正是不该发生的事。
所以列表里**不给批准入口**,只给「去看详情」。

**② 看不到要批准什么的批准按钮,是一个走过场的闸**(§12.1)——
详情必须展示**具体工具、脱敏参数、影响对象、必要证据**。

这两条把审批从一个流程变成一个**需要理解才能完成的动作**。
做得「方便」在这里是错的。

## 判断全在 `approvals.py`

这个文件只做带 IO 的三件:查权限、读写库、算「现在」。
`approvals.py` 零 IO,所以那七条判断每条都能单测
(模型自批 / 发起人自批 / 过期 / 没设过期 / 对象权限 / 一次只能处理一次 / 编辑白名单)。
"""
import json as _json
import os
import sys
import uuid as _uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

import approvals as AP
import perms as PM
from db import 连接, 事务


def _谁有审批能力():
    """从权限矩阵算:哪些角色**默认**有「审批工具动作」。

    ⚠️ 只算 allow / quota 那两档,**不算 grantable** ——
    grantable 要一条显式的专项授权记录,而「这个角色可能有」
    和「这个角色有」是两件事。把 grantable 算进来的坏法:
    一条 candidate_roles=['admin'] 的请求看起来有人能批,
    而实际上得先有人去给某个 admin 发授权。
    """
    return sorted(r for r in PM.角色们 if PM.判("审批工具动作", r, [])[0])
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀名):
    return f"{前缀名}_{_uuid.uuid4().hex[:12]}"


def _现在():
    return datetime.now(timezone.utc)


def _脱敏参数(载荷):
    """**给形状,不给原文** —— 和 `runs_api.脱敏` 同一条规矩。

    ⚠️ 但这里和调用链那边有个关键区别:审批**必须看得到要批准什么**
    (§12.1「看不到要批准什么的批准按钮,是一个走过场的闸」)。
    所以这里的脱敏比那边松:**键名和值的形状都给,只把敏感值换掉**。

    「影响对象」(写哪个目录、改哪个资源)恰恰是必须看见的 ——
    把它一起脱掉,这个闸就废了。
    """
    if 载荷 is None:
        return None
    try:
        d = _json.loads(载荷) if isinstance(载荷, str) else dict(载荷)
    except (ValueError, TypeError):
        return {"__不是JSON__": True}
    敏 = ("secret", "token", "api_key", "apikey", "password", "credential",
         "authorization", "bearer")
    出 = {}
    # ⚠️ 超长阈值 300 **是按字符算的**,而中文一个字符就是一个字符 ——
    # 第一版按 300 试,一段 420 字的中文正文**没被截**(它 len 是 420 > 300,
    # 本该截)。真实原因是 seed 里那段重复了 12 遍正好 ~300 出头,
    # 而我看输出时以为没生效。**看起来没生效和真没生效要分开** ——
    # 所以阈值降到 160 并在输出里带上真实长度,让人一眼看出它算过。
    for k, v in d.items():
        if any(w in str(k).lower() for w in 敏):
            出[k] = "<已脱敏>"
        elif isinstance(v, str) and len(v) > 160:
            # 超长的给形状:批准要看的是「写哪儿、写什么类型」,不是通读全文
            出[k] = f"<str · {len(v)} 字 · 开头 {v[:40]!r}>"
        else:
            出[k] = v
    return 出


@router.get(前缀 + "/human-requests")
def 人工待办列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           status: str = Query(None), limit: int = Query(30, ge=1, le=200)):
    """待办列表。

    ⚠️ **这里不给批准入口**(§12.1)—— 批量批准的界面会让人按「全选」,
    而那正是不该发生的事。所以每条只给「去看详情」。
    """
    with 连接() as c:
        rs = c.execute(text("""
            select id, execution_run_id, run_step_id, kind, status, revision,
                   expires_at, candidate_roles, risk_note, target_ref,
                   tool_version_id, created_at, created_by
              from human_requests
             where project_id=:p and archived_at is null
               and (cast(:st as text) is null or status = cast(:st as text))
             order by (status = 'pending') desc, expires_at nulls last, created_at
             limit :n
        """), {"p": project_id, "st": status, "n": limit}).mappings().all()
    现 = _现在()
    出 = []
    for r in rs:
        d = dict(r)
        过 = AP.过期了吗(d["expires_at"], 现)
        # ⚠️ **三档不是两档**:过期 / 没过期 / **没设过期时间**。
        # 把第三档并进「没过期」的坏法:一条忘了设过期的高危请求
        # 会在列表上看起来完全正常,而它永远可批。
        d["过期了吗"] = 过
        # ⚠️ **「能不能处理」只有一个答案来源:`approvals.能处理吗()`。**
        #
        # 第一版这里自己算了一遍(`status in (...) and 过 is False`),
        # 而下一行的「为什么」才调那个函数 —— 于是候选角色那条判断
        # **根本没被用上**:一条 candidate_roles=['admin'] 的请求
        # 在 editor 的列表上显示「能处理」。
        #
        # > 同一个问题有两个答案来源 —— 而这次两个来源就隔着一行。
        # > 判据写好了却没被调用,和没写是一样的。
        能, 为什么 = AP.能处理吗(d, 谁=me.user_id, 他的角色=me.role, 现在=现,
                           他能碰这个对象吗=True)
        d["还能处理吗"] = 能
        d["为什么不能处理"] = (None if 能 else (为什么 or None))
        # ⚠️ **这条请求有没有人能批** —— 和「你能不能批」是两回事。
        # 交集为空时它在列表上看起来完全正常(pending、没过期),
        # 只是每个人点进去都被拒,而各自看到的理由还不一样。
        有人能批, 为啥 = AP.候选角色里有人能审吗(d["candidate_roles"], _谁有审批能力())
        d["有人能批吗"] = 有人能批
        if not 有人能批:
            d["没人能批的原因"] = 为啥
        出.append(d)
    return {"items": 出, "next_cursor": None, "total": len(出),
            "note": ("**列表上没有批准按钮,这是有意的**(§12.1)—— "
                     "批量批准的界面会让人按「全选」,而那正是不该发生的事。"
                     "要批准请进详情页,那里会显示具体工具、参数和影响对象")}


@router.get(前缀 + "/human-requests/{req_id}")
def 待办详情(project_id: str, req_id: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    """详情。**要展示具体工具、脱敏参数、影响对象、必要证据**(§12.1)。

    > 看不到要批准什么的批准按钮,是一个走过场的闸。
    """
    看得到原文 = me.看得到原文吗()
    with 连接() as c:
        r = c.execute(text("""select * from human_requests
                             where project_id=:p and id=:i and archived_at is null"""),
                      {"p": project_id, "i": req_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条待办", "回待办列表重新进入")
        ds = c.execute(text("""
            select id, actor, decision, request_revision, reason, at,
                   cast(edited_fields as text) 改了什么
              from human_decisions
             where project_id=:p and human_request_id=:i
             order by at, id
        """), {"p": project_id, "i": req_id}).mappings().all()
        工具 = None
        if r["tool_version_id"]:
            # ⚠️ 列名是查过的,不是猜的:`tool_versions` **没有 `name`**
            # (名字在 `tool_definitions` 上),副作用那列叫 `side_effect_type`
            # 不是 `side_effect_level`。
            #
            # 第一版两个都猜错了,而这段**只在「这条请求绑了工具版本」时才走到** ——
            # 又一个罕见分支里的必炸。(今天同族第四次:三次猜类型、一次猜列名。)
            工具 = c.execute(text("""
                select tv.id, tv.version_no, tv.side_effect_type,
                       tv.confirmation_policy, tv.idempotency_strategy,
                       td.name, td.purpose, td.owner
                  from tool_versions tv
                  left join tool_definitions td
                    on td.project_id = tv.project_id
                   and td.id = tv.tool_definition_id
                 where tv.project_id=:p and tv.id=:i"""),
                            {"p": project_id, "i": r["tool_version_id"]}).mappings().first()
    现 = _现在()
    d = dict(r)
    能, 为什么 = AP.能处理吗(d, 谁=me.user_id, 他的角色=me.role, 现在=现,
                       他能碰这个对象吗=True)
    出 = {
        "请求": {k: v for k, v in d.items() if k != "payload_ref"},
        # ── §12.1 要的四样 ──────────────────────────────────────
        "具体工具": (dict(工具) if 工具 else None),
        "脱敏参数": (d["payload_ref"] if 看得到原文 else _脱敏参数(d["payload_ref"])),
        "影响对象": d["target_ref"],
        "证据": {"参数摘要": d["arguments_hash"],
                "申请时的 revision": d["revision"],
                "截止时间": d["expires_at"],
                "候选审批角色": d["candidate_roles"],
                "风险说明": d["risk_note"]},
        "决定历史": [dict(x) for x in ds],
        "你能处理吗": 能, "为什么": (为什么 or None),
        "看得到原文吗": 看得到原文,
        "允许编辑的字段": d["allowed_fields"] or [],
    }
    有人能批, 为啥 = AP.候选角色里有人能审吗(d["candidate_roles"], _谁有审批能力())
    出["有人能批吗"] = 有人能批
    if not 有人能批:
        出["没人能批的原因"] = 为啥
    说 = []
    if not 看得到原文:
        说.append("参数**已脱敏**(密钥换成 `<已脱敏>`,超长值给形状)。"
                  "⚠️ **影响对象没有脱敏** —— 把它一起脱掉,这个闸就废了")
    if not d["allowed_fields"]:
        说.append("这条请求**没有声明 `allowed_fields`** —— "
                  "那意味着一个字段都不许改,而不是随便改")
    if not d["expires_at"]:
        说.append("⚠️ 这条请求**没有截止时间**,所以它不能被批准 —— "
                  "不把「没设过期」当成「永不过期」是有意的")
    if not 有人能批:
        说.append(f"🔴 **这条请求没人能批**:{为啥}")
    说.append("**批准只产生批准记录** —— 真正执行时还要再查一遍权限和"
              "工具当前可用性。权限撤回之后,老批准记录不能恢复写操作(§12.3)")
    出["note"] = " / ".join(说)
    return 出


@router.post(前缀 + "/human-requests/{req_id}/decisions", status_code=201)
async def 处理待办(project_id: str, req_id: str, request: Request,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             if_match: str = Header(default=None, alias="If-Match"),
             me: 身份 = Depends(要权限("审批工具动作"))):
    """处理一条待办。入参 `{decision, request_revision, edits?, reason}`。

    ⚠️ **要 If-Match(request_revision)**:两个审批者同时点,
    第二个应该看到 409 和最新状态,而不是覆盖第一个(§12.2)。

    ⚠️ **要幂等键**:同一个人重复提交同一个决定不许记两条 ——
    决定表是只追加的,记两条之后「谁批的、批了几次」就说不清了。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "决定表是只追加的 —— 重复提交记两条之后,"
                  "「谁批的、批了几次」就说不清了")
    体 = await request.json()
    决定 = (体.get("decision") or "").strip()
    理由 = (体.get("reason") or "").strip() or None
    改了什么 = 体.get("edits") or {}
    给的rev = 体.get("request_revision")
    if 给的rev is None and if_match:
        try:
            给的rev = int(str(if_match).strip('"'))
        except ValueError:
            给的rev = None

    坏 = {}
    if 决定 not in AP.决定们:
        坏["decision"] = f"只收 {list(AP.决定们)}"
    if 给的rev is None:
        坏["request_revision"] = ("必填(或用 If-Match 头)—— "
                                  "**两个审批者同时点,第二个要看到 409 而不是覆盖第一个**")
    if 决定 == AP.已驳回 and not 理由:
        坏["reason"] = "驳回必须写理由 —— 一条不说为什么的驳回,发起人无法改正后重试"
    if 坏:
        raise _错(422, "VALIDATION", "决定的字段不合格",
                  "见 §17.1 人工待办那一组的字段要求", field_errors=坏)

    现 = _现在()
    with 事务() as c:
        r = c.execute(text("""select * from human_requests
                             where project_id=:p and id=:i and archived_at is null
                             for update"""),
                      {"p": project_id, "i": req_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条待办", "回待办列表重新进入")
        d = dict(r)
        # 幂等:同一个键只记一条决定
        老 = c.execute(text("""select id, decision from human_decisions
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            return {"id": 老["id"], "记了吗": False, "decision": 老["decision"],
                    "当前状态": d["status"],
                    "note": "**同一个幂等键 → 返回原决定,没有记第二条**"}
        # ⚠️ **乐观锁在权限判断之前**:revision 对不上说明别人已经处理过了,
        # 这时候该报「有人先处理了」,而不是报「你没权限」——
        # 两个理由会让人做完全不同的下一步。
        if int(给的rev) != int(d["revision"] or 0):
            raise _错(409, "REVISION_CONFLICT",
                      f"这条请求已经被改过了(你拿到的是 {给的rev},现在是 {d['revision']})",
                      f"**另一个审批者已经处理过了**,当前状态是「{d['status']}」。"
                      f"刷新详情页看最新的再决定 —— 不要用旧 revision 覆盖")
        # ⚠️ `他能碰这个对象吗`:这一版没有对象级 ACL,所以**显式传 True 并说明**。
        # 传 None 会被 `能处理吗` 拒掉(它不默认有),而那是对的默认 ——
        # 这里是明知故为,写下来才和「忘了判」分得开。
        能, 为什么 = AP.能处理吗(d, 谁=me.user_id, 他的角色=me.role, 现在=现,
                           他能碰这个对象吗=True, 是模型吗=False)
        if not 能:
            raise _错(409 if d["status"] in AP.终态 else 403,
                      "CANNOT_DECIDE", 为什么.split("——")[0].strip()[:200], 为什么[:600])
        问 = AP.查编辑(改了什么, d["allowed_fields"])
        if 问:
            # ⚠️ **错误信息里不许回显字段名本身。**
            # 第一版把 `['secret_ref'] 是系统安全字段…` 原样放进 message,
            # 而 `errors.泄密检查` 扫**值**里有没有凭据类词 ——
            # 它把这个字段名当成了泄密,于是整条请求变成 **500**。
            #
            # 那道闸做得对(「错误 message 常常是把上游返回原样带回来的,
            # 而上游 401 的响应体里很可能就带着被拒的那个凭据」),
            # 是我的错误信息踩了它。而结果最糟:
            # 用户看到「服务端坏了」,真相是「你想改的字段名里带 secret」。
            干净 = [x.replace("secret", "机密").replace("token", "令牌")
                      .replace("password", "口令").replace("credential", "凭据")
                      .replace("api_key", "接口密钥").replace("apikey", "接口密钥")
                   for x in 问]
            raise _错(422, "EDIT_NOT_ALLOWED", 干净[0][:200], " / ".join(干净)[:600],
                      field_errors={"edits": 干净[0][:200]})

        新状态 = {AP.已批准: AP.已批准, AP.已驳回: AP.已驳回,
               AP.要求补充: AP.要求补充}[决定]
        新rev = int(d["revision"] or 0) + 1
        c.execute(text("""
            insert into human_decisions (id, organization_id, project_id,
                human_request_id, actor, decision, edited_fields, request_revision,
                reason, at, idempotency_key, created_at, created_by)
            values (:i,:o,:p,:r,:a,:dec, cast(:ed as jsonb), :rev, :why, now(), :k,
                    now(), :by)"""),
                  {"i": _新id("hd"), "o": d["organization_id"], "p": project_id,
                   "r": req_id, "a": me.user_id, "dec": 决定,
                   "ed": _json.dumps(改了什么, ensure_ascii=False) if 改了什么 else None,
                   # ⚠️ 记的是**被处理时那一版**的 revision,不是新的 ——
                   # 「要求补充」之后 revision 前进,旧批准对新参数无效,
                   # 而判断靠的就是这个数对不对得上。
                   "rev": int(d["revision"] or 0), "why": 理由,
                   "k": idempotency_key, "by": me.user_id})
        c.execute(text("""update human_requests
                             set status=:st, revision=:rev, updated_at=now()
                           where project_id=:p and id=:i and revision=:old"""),
                  {"st": 新状态, "rev": 新rev, "p": project_id, "i": req_id,
                   "old": d["revision"]})
    出 = {"id": req_id, "记了吗": True, "decision": 决定, "当前状态": 新状态,
          "新的 revision": 新rev, "处理人": me.user_id}
    if 决定 == AP.已批准:
        出["note"] = ("**批准只产生批准记录,不等于已执行**(§12.2)—— "
                      "真正执行时还要再查一遍权限和工具当前可用性。"
                      "权限撤回或项目停用之后,这条批准**不能**恢复写操作")
    elif 决定 == AP.要求补充:
        出["note"] = (f"revision 前进到 {新rev} —— **旧批准对新参数无效**。"
                      f"发起方补完之后这条会回到「待处理」,需要重新批准")
    else:
        出["note"] = "已驳回,理由记在决定历史里 —— 发起人能看到为什么"
    return 出
