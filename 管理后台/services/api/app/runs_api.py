#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行记录与调用链(规格 §17.1「运行记录」那一组)。

    GET /traces        运行记录列表
    GET /traces/{id}   运行详情 —— **调用树(trace / span)**

## M5:调用链页

交割文档里 `/debug`(调试后台 —— 单次运行的调用树)要在管理后台重建。
**重建不是搬**:澜绣那一页读的是澜绣自己的 span 表,
这里读的是管理后台自己的 `traces` / `spans` ——
而那两张表 2026-09-28 之前基本是空的(只有 Worker 的 mock 运行写过)。
是精排记账和 A1 上报让它们有了真内容。

## ⚠️ 「看得到 trace」不等于「看得到原文」

契约给 `GET /traces/{id}` 登记了字段权限 `查看敏感输入/独立测试答案`,
而 `deps.身份.看得到原文吗()` 早就写好了 —— **只差没有接口引用它**。
> 一条登记了却没被任何接口引用的能力,在权限矩阵上和「没实现」长得一模一样。

`input_ref` / `output_ref` 里是**真实业务内容**:检索实验室问的那句话、
门店助手上报的调用参数。所以默认**脱敏**:只给形状(有哪些键、多长),
不给内容。有那条专项授权才给原文。

⚠️ 脱敏不是「截断到 100 字」—— 截断之后前 100 字仍然是原文。
这里给的是**键名和长度**,那是形状不是内容。
"""
import json as _json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 一次调用树最多展开多少个 span。**写死是故意的**(棘轮):
# 一棵几千个节点的树在界面上打不开,而「打不开」和「没有数据」长得一样。
最多几个span = 200


def 脱敏(值):
    """把一段 JSON 内容换成**形状**:有哪些键、每个多长。

    ⚠️ **不是截断。** 截断到 100 字之后,那 100 字仍然是原文 ——
    而原文里第一句往往正是最敏感的那句(客户姓名、订单号)。
    形状能回答「这里有没有东西、大概多大」,而不泄露任何一个字。
    """
    if 值 is None:
        return None
    try:
        d = _json.loads(值) if isinstance(值, str) else 值
    except (ValueError, TypeError):
        return {"__不是JSON__": True, "字符数": len(str(值))}
    if isinstance(d, dict):
        return {k: (f"<{type(v).__name__} · {len(str(v))} 字>" if v is not None else None)
                for k, v in d.items()}
    if isinstance(d, list):
        return {"__列表__": len(d)}
    return {"__标量__": f"<{type(d).__name__} · {len(str(d))} 字>"}


@router.get(前缀 + "/traces")
def 运行记录列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            limit: int = Query(30, ge=1, le=200),
            end_reason: str = Query(None)):
    """运行记录列表。**每条要带「花了多少」和「有几步」** ——

    一个只有 id 和时间的列表,回答不了「哪次贵、哪次慢」,
    而那正是人打开这一页要找的东西。
    """
    with 连接() as c:
        rs = c.execute(text("""
            select t.id, t.request_id, t.environment, t.started_at, t.ended_at,
                   t.end_reason, t.created_by,
                   (select count(*) from spans s
                     where s.project_id=t.project_id and s.trace_id=t.id) 步数,
                   (select count(*) from spans s
                     where s.project_id=t.project_id and s.trace_id=t.id
                       and s.error is not null) 出错的步数,
                   (select coalesce(sum(u.quantity), 0) from usage_ledger u
                     where u.project_id=t.project_id and u.trace_id=t.id) token数,
                   (select count(*) filter (where not u.amount_known)
                      from usage_ledger u
                     where u.project_id=t.project_id and u.trace_id=t.id) 金额未知的行数,
                   (select coalesce(sum(u.amount) filter (where u.amount_known), 0)
                      from usage_ledger u
                     where u.project_id=t.project_id and u.trace_id=t.id) 已知金额,
                   (select max(u.caller) from usage_ledger u
                     where u.project_id=t.project_id and u.trace_id=t.id) 调用方
              from traces t
             where t.project_id=:p
               and (cast(:er as text) is null or t.end_reason = cast(:er as text))
             order by t.started_at desc
             limit :n
        """), {"p": project_id, "er": end_reason, "n": limit}).mappings().all()
    出 = []
    for r in rs:
        d = dict(r)
        # ⚠️ **金额未知就是 None,不是 0**(和 `/usage` 同一条规矩)。
        # 在这里填 0 的话,列表按金额排序会把「不知道花了多少」的排在最便宜那头。
        d["金额"] = (float(d["已知金额"]) if not d["金额未知的行数"] else None)
        d["金额是未知吗"] = bool(d["金额未知的行数"])
        d["成功吗"] = (d["end_reason"] not in ("failed", "error"))
        出.append(d)
    return {"items": 出, "next_cursor": None, "total": len(出),
            "note": ("**「金额未知」不是 0** —— 库里还没有价目表快照。"
                     "按金额排序时未知的那些不参与排序")}


@router.get(前缀 + "/traces/{trace_id}")
def 运行详情(project_id: str, trace_id: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    """一次运行的**调用树**。默认脱敏(§17.1 的字段权限)。

    ⚠️ 看得到 trace **不等于**看得到原文:`input_ref` / `output_ref` 里是
    真实业务内容。要原文得有 `查看敏感输入/独立测试答案` 这条专项授权。
    """
    看得到原文 = me.看得到原文吗()
    with 连接() as c:
        t = c.execute(text("""select * from traces
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": trace_id}).mappings().first()
        if not t:
            # 404 而不是 403:**不泄露「这个 ID 在别的项目里存在」**
            raise _错(404, "NOT_FOUND", "没有这条运行记录", "回运行记录列表重新进入")
        ss = c.execute(text("""
            select id, parent_span_id, stage, started_at, ended_at,
                   cast(input_ref as text) 入, cast(output_ref as text) 出,
                   cast(error as text) 错, created_by
              from spans
             where project_id=:p and trace_id=:i
             order by started_at, id
             limit :n
        """), {"p": project_id, "i": trace_id, "n": 最多几个span + 1}).mappings().all()
        账 = c.execute(text("""
            select resource, source, provider, caller, world_date,
                   sum(quantity) token数,
                   count(*) filter (where not amount_known) 金额未知的行数,
                   coalesce(sum(amount) filter (where amount_known), 0) 已知金额
              from usage_ledger
             where project_id=:p and trace_id=:i
             group by 1,2,3,4,5
        """), {"p": project_id, "i": trace_id}).mappings().all()

    截断了 = len(ss) > 最多几个span
    ss = ss[:最多几个span]
    步们 = []
    for s in ss:
        d = {k: s[k] for k in ("id", "parent_span_id", "stage", "started_at",
                               "ended_at", "created_by")}
        d["出错了吗"] = s["错"] is not None
        if 看得到原文:
            d["入"] = s["入"]
            d["出"] = s["出"]
            d["错"] = s["错"]
        else:
            # **形状,不是截断** —— 见文件头
            d["入_形状"] = 脱敏(s["入"])
            d["出_形状"] = 脱敏(s["出"])
            d["错_形状"] = 脱敏(s["错"])
        步们.append(d)

    出 = {"trace": dict(t), "步们": 步们, "步数": len(步们),
         "用量": [dict(x) for x in 账],
         "看得到原文吗": 看得到原文}
    out_note = []
    if not 看得到原文:
        out_note.append(
            "**默认脱敏** —— `入`/`出` 只给了形状(有哪些键、每个多长),"
            "不是原文截断:截断之后前几十字仍然是原文,而原文第一句"
            "往往正是最敏感的那句。要原文需要「查看敏感输入/独立测试答案」这条授权")
    if 截断了:
        # ⚠️ **截断要报出来。** 一棵被悄悄砍掉一半的调用树,
        # 看起来就像「这次运行只有这么多步」。
        out_note.append(f"⚠️ **这次运行超过 {最多几个span} 个步骤,只显示了前 "
                        f"{最多几个span} 个** —— 后面的没显示,不是没有")
        出["被截断了"] = True
    if not 步们:
        out_note.append("这条运行记录**一个步骤都没有** —— "
                        "trace 写进去了而 span 没有,那是服务端不一致,要人看")
    出["note"] = " / ".join(out_note) if out_note else None
    return 出


# ══════════════════════════════════════════════════════════════════════
# A3 接收端 + 智能体健康(M4 的第三页)
#
# ## 为什么「采纳率」要走上报,不能直接查澜绣的库
#
# 采纳/改判这件事**发生在应用层**(人在研判队列里签字或改判),
# 而「看某个 AI 配置改动的效果」按归属判据③属于**控制面**。
# 数据在那边、看在这边 —— 中间只能是一条上报链。
#
# 管理后台**绝不反过来查澜绣的库**:那会让两个台互相依赖,
# 而「谁先起来」这种问题会在部署时才暴露。
#
# ⚠️ 这也是交割文档里那条未定项(「改判回流走哪条路」)的答案 ——
# **判据推出来的,不用另外拍一次板**:和调用记录一样走上报。
#
# ## 为什么不能用「没有标准答案就不算」
#
# 上线之后**没有标准答案**(线上问题不是评测集里的题)。
# 能拿到的只有「人采纳了没有」。所以这一页的指标是采纳率,
# 而它**不是质量分** —— 采纳率高可能是因为人懒得改。
# 这件事要写在返回里,否则它会被当成质量分用。
# ══════════════════════════════════════════════════════════════════════

_判读 = {"采纳": "人直接用了智能体给的结论",
        "改判": "人改了结论 —— **这条最有价值**,它能回流成评测样本",
        "升级": "人没法判,升级给了别人",
        "作废": "这条根本不该由智能体处理"}


@router.post(前缀 + "/feedback", status_code=201)
async def 上报一次人工判读(project_id: str, request: Request,
                 idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
                 me: 身份 = Depends(要权限("运行评测"))):
    """应用层上报一次**人对智能体结论的处置**(A3)。

    入参:`{trace_id?, 外部trace?, 判读, 说明?, 世界日期?}`

    ⚠️ **`trace_id` 和 `外部trace` 至少给一个。** 前者是管理后台自己的
    trace(A1 上报时返回的那个),后者是澜绣自己的 id。
    两个都没有的话,这条判读**挂不到任何一次调用上** ——
    而一条挂不上的判读只能进总数,进不了「哪一版改配置之后采纳率变了」。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "同一条判读重复上报不许算两次 —— 采纳率的分母会被撑大")
    体 = await request.json()
    判读 = (体.get("判读") or "").strip()
    tid = (体.get("trace_id") or "").strip() or None
    外部 = (体.get("外部trace") or "").strip() or None
    说明 = (体.get("说明") or "").strip() or None
    世界日期 = (体.get("世界日期") or "").strip() or None

    坏 = {}
    if 判读 not in _判读:
        坏["判读"] = f"只收 {sorted(_判读)} —— **不收任意字符串**:一个拼错的判读会自成一档"
    if not tid and not 外部:
        坏["trace_id"] = ("`trace_id` 和 `外部trace` 至少给一个 —— "
                         "挂不上调用的判读进不了「改了配置之后采纳率变没变」")
    if 世界日期:
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", 世界日期):
            坏["世界日期"] = "要 YYYY-MM-DD(演示世界的日历日,不是时刻)"
    if 坏:
        raise _错(422, "VALIDATION", "上报的字段不合格",
                  "见 `澜绣云裳agent-两个台的功能交割.md` 里 A3 那一节", field_errors=坏)

    from db import 事务
    import uuid as _uuid
    import json as _j
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        if tid:
            有 = c.execute(text("select 1 from traces where project_id=:p and id=:i"),
                           {"p": project_id, "i": tid}).first()
            if not 有:
                # ⚠️ **不静默改成 NULL 收下。** 收下之后这条判读看起来挂在
                # 一次调用上,而那次调用不存在 —— 比拒掉糟得多。
                raise _错(422, "TRACE_NOT_FOUND",
                          f"没有 trace {tid}", "确认 A1 上报时返回的 trace_id;"
                          "只有澜绣自己的 id 就放进 `外部trace`",
                          field_errors={"trace_id": "这个项目里没有这条运行记录"})
        # 幂等:同一个键只记一条
        # ⚠️ 查的是 `report_detail`(JSONB)不是 `note`(TEXT)——
        # `note->>` 当场报 `operator does not exist: text ->> unknown`。
        老 = c.execute(text("""select id from feedback
                             where project_id=:p
                               and (report_detail->>'幂等键') = :k
                             limit 1"""),
                       {"p": project_id, "k": idempotency_key}).scalar()
        if 老:
            return {"id": 老, "记了吗": False,
                    "note": "**同一个幂等键 → 返回原记录**,采纳率的分母没有被撑大"}
        fid = f"fb_{_uuid.uuid4().hex[:12]}"
        c.execute(text("""
            insert into feedback (id, organization_id, project_id, trace_id,
                verdict, note, report_detail, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:t,:v,:note, cast(:rd as jsonb), now(), :u, now(), 1)"""),
                  {"i": fid, "o": org, "p": project_id, "t": tid, "v": 判读,
                   # `note` 是 TEXT,**给人看的一句话**;结构化的进 report_detail
                   "note": 说明,
                   "rd": _j.dumps({"幂等键": idempotency_key, "说明": 说明,
                                   "外部trace": 外部, "世界日期": 世界日期},
                                  ensure_ascii=False),
                   "u": me.user_id})
    return {"id": fid, "记了吗": True, "判读": 判读, "它的意思": _判读[判读],
            "挂在": ("管理后台的 trace" if tid else "只有外部 id(挂不到调用链上)"),
            "note": ("**采纳率不是质量分** —— 采纳率高也可能是因为人懒得改。"
                     "最有价值的是「改判」那一档:它能回流成评测样本")}


@router.get(前缀 + "/agent-health")
def 智能体健康(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
           天: int = Query(30, ge=1, le=365)):
    """上线之后的健康度。**指标是采纳率,而它不是质量分。**

    ⚠️ 线上问题不在评测集里,所以**没有标准答案** —— 能拿到的只有
    「人采纳了没有」。这一页要说清这个区别,否则采纳率会被当成质量分用。
    """
    with 连接() as c:
        总 = c.execute(text("""
            select count(*) 判读数,
                   count(*) filter (where verdict = '采纳') 采纳数,
                   count(*) filter (where verdict = '改判') 改判数,
                   count(*) filter (where trace_id is not null) 挂上调用链的,
                   count(distinct trace_id) 涉及几次调用
              from feedback
             where project_id=:p and archived_at is null
               and created_at > now() - (:d || ' days')::interval
        """), {"p": project_id, "d": 天}).mappings().first()
        分档 = c.execute(text("""
            select verdict 判读, count(*) n from feedback
             where project_id=:p and archived_at is null
               and created_at > now() - (:d || ' days')::interval
             group by 1 order by n desc
        """), {"p": project_id, "d": 天}).mappings().all()
        调用数 = c.execute(text("""
            select count(*) from traces
             where project_id=:p and started_at > now() - (:d || ' days')::interval
        """), {"p": project_id, "d": 天}).scalar()

    n = 总["判读数"] or 0
    出 = {"时间范围": f"最近 {天} 天",
         "判读数": n, "这段时间的调用数": 调用数 or 0,
         "分档": [dict(x) for x in 分档],
         "挂上调用链的": 总["挂上调用链的"] or 0,
         # ⚠️ **没有判读时采纳率是 None,不是 0。**
         # 0 会被读成「一条都没被采纳」,而真相是「还没有人判过」。
         "采纳率": (round((总["采纳数"] or 0) * 100 / n, 1) if n else None),
         "改判率": (round((总["改判数"] or 0) * 100 / n, 1) if n else None),
         "采纳率是未知吗": (n == 0)}
    说 = ["**采纳率不是质量分** —— 采纳率高也可能是因为人懒得改。"
         "上线之后没有标准答案(线上问题不在评测集里),能拿到的只有这个"]
    if n == 0:
        说.append("**还没有任何人工判读** —— 采纳率显示「未知」而不是 0:"
                  "0 意味着「一条都没被采纳」,未知意味着「还没有人判过」。"
                  "要有数据,澜绣那边得接上 A3 上报(`POST /feedback`)")
    elif 调用数 and n < 调用数 * 0.1:
        # ⚠️ 覆盖率低的时候要说,否则一个 90% 的采纳率会被当成全局结论,
        # 而它可能只来自被人挑出来看的那几条。
        说.append(f"⚠️ **覆盖率低**:{调用数} 次调用里只有 {n} 条有判读。"
                  f"这个采纳率只代表被看过的那些,**不能当成全局结论**")
    未挂上 = n - (总["挂上调用链的"] or 0)
    if 未挂上:
        说.append(f"{未挂上} 条判读**没挂到调用链上**(只有外部 id)—— "
                  f"它们进得了总数,进不了「改了配置之后采纳率变没变」")
    出["说明"] = " / ".join(说)
    return 出
