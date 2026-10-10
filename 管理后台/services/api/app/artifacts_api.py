#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出监督(用户 2026-10-10:报告和 agent 建议「是怎么生成的」要能在 AI 管理平台上**看 + 打回**)。

    POST /artifacts                       澜绣推一份产出过来(幂等)
    GET  /artifacts                       列表(类型 / 状态筛选)
    GET  /artifacts/{id}                  详情:规矩、输入、输出、版本、打回历史、对应调用链
    POST /artifacts/{id}/reject           打回(只记决定,不执行)
    GET  /artifact-decisions              澜绣来拉「待执行」的打回
    POST /artifact-decisions/{id}/ack     澜绣执行完回一声

## 方向:推过来、拉回去 —— 这边一个字都不写进澜绣

和 A3 同一条判据:产出发生在应用层,而「这一版规矩 / 模型写出来的东西对不对」属于控制面。
管理后台**绝不反查澜绣的库**,所以产出只能澜绣推过来;
打回同理**不反写**:这里只记一条决定,澜绣拉回去、走它自己的正门执行
(建议:按打回理由重写一版并再推上来;报告:店长那边标「被管理平台打回」、不许确认)。

## 状态不存列,由最近一条决定推出来

    没有决定        → 正常
    最近一条待执行  → 已打回待执行
    最近一条已执行  → 已执行
    最近一条执行失败 → 执行失败

存一份的话,决定改了而状态没跟着改,两边都看起来完全正常。

## 手机号在入库那一刻就打码

建议的输入里有客户当初的原话,报告的输入是店里的经营数。澜绣那边发之前已经去掉了全名和电话 ——
但**发送方的守卫只护得住发送方**。所以这里入库前再扫一遍 11 位手机号,扫到就打码,
并在 `report_detail` 里记下打了几处:「发送方漏了」这件事要看得见,不能被这一层悄悄兜住。
"""
import json as _json
import os
import re as _re
import sys
import uuid as _uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

类型们 = ("报告", "建议")
生成方式们 = ("模型", "规则", "对话")
结果们 = {"已重写": "已执行", "已标记": "已执行", "执行失败": "执行失败"}
输入上限字节 = 256 * 1024
_手机号 = _re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")

# 打回给哪条能力:**「改训练样本」,不是「运行评测」**。
# 打回是一次「人判这份产出不行」—— 它会回流成评测样本,和标注员给样本打标签是同一件事
# (annotator / admin 默认有;approver 默认没有:审核者的职责是按门槛放行,不是判内容)。
# 上报和拉取用「运行评测」:那是澜绣的服务身份在推 / 拉,和 A3 /feedback 一致。
打回要的能力 = "改训练样本"

# 状态推导:**最近一条决定**说了算。写成一段 SQL 片段,列表和详情用同一段 —— 不各写一份
_状态片段 = """
    coalesce((select case d.status when '待执行' then '已打回待执行'
                                   when '已执行' then '已执行'
                                   when '执行失败' then '执行失败' end
                from artifact_decisions d
               where d.project_id = a.project_id and d.artifact_id = a.id
               order by d.created_at desc, d.id desc limit 1), '正常')
"""
_最近理由片段 = """
    (select d.reason from artifact_decisions d
      where d.project_id = a.project_id and d.artifact_id = a.id
      order by d.created_at desc, d.id desc limit 1)
"""


def _新id(前缀字):
    return f"{前缀字}_{_uuid.uuid4().hex[:12]}"


def _打码(值):
    """把值里的 11 位手机号打码。返回 (新值, 打了几处)。值可以是 str / dict / list。"""
    计 = [0]

    def _换(m):
        计[0] += 1
        return f"{m.group(1)}****{m.group(3)}"

    def _走(v):
        if isinstance(v, str):
            return _手机号.sub(_换, v)
        if isinstance(v, dict):
            return {k: _走(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_走(x) for x in v]
        return v
    return _走(值), 计[0]


def _项目组织(c, project_id):
    return c.execute(text("select organization_id from projects where id=:p"),
                     {"p": project_id}).scalar()


# ══════════════════════════════════════════════════════════════════════
# 上报
# ══════════════════════════════════════════════════════════════════════
@router.post(前缀 + "/artifacts", status_code=201)
async def 上报一份产出(project_id: str, request: Request,
                 idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
                 me: 身份 = Depends(要权限("运行评测"))):
    """澜绣推一份产出过来。(项目, 外部id, 版本) 唯一 —— 重复上报返回原记录。"""
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "同一份产出重复上报不许记两条 —— 打回会挂在其中一条上,另一条在列表里显示「正常」")
    try:
        体 = await request.json()
    except Exception:
        raise _错(422, "VALIDATION", "请求体不是 JSON", "按产出上报的字段清单发")
    if not isinstance(体, dict):
        raise _错(422, "VALIDATION", "请求体要是一个对象", "按产出上报的字段清单发")

    外部id = 体.get("外部id")
    类型 = 体.get("类型")
    版本 = 体.get("版本")
    标题 = 体.get("标题")
    门店 = 体.get("门店")
    世界日期 = 体.get("世界日期")
    模型 = 体.get("模型")
    生成方式 = 体.get("生成方式")
    规则 = 体.get("规则")
    输入 = 体.get("输入")
    输出 = 体.get("输出")
    外部trace = 体.get("外部trace")

    坏 = {}
    if not isinstance(外部id, str) or not 外部id.strip() or len(外部id) > 120:
        坏["外部id"] = "要一个非空字符串,不超过 120 字(澜绣那边这份产出的号,比如 报告:RPT000001)"
    if 类型 not in 类型们:
        坏["类型"] = f"只收 {list(类型们)} —— **不收任意字符串**:拼错的类型会自成一档,筛选时哪档都不算"
    if not isinstance(版本, int) or isinstance(版本, bool) or 版本 < 1:
        坏["版本"] = "要 ≥1 的整数(同一份产出改一版就 +1,旧版留着)"
    if not isinstance(标题, str) or not 标题.strip():
        坏["标题"] = "要一个非空字符串(列表上给人看的那一行)"
    if 门店 is not None and not isinstance(门店, str):
        坏["门店"] = "要字符串或不给"
    if 世界日期 is not None and (not isinstance(世界日期, str)
                              or not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", 世界日期)):
        坏["世界日期"] = "要 YYYY-MM-DD(演示世界的日历日,不是时刻)"
    if 模型 is not None and not isinstance(模型, str):
        坏["模型"] = "要字符串或不给"
    if 生成方式 is not None and 生成方式 not in 生成方式们:
        坏["生成方式"] = f"只收 {list(生成方式们)} 或不给"
    if (not isinstance(规则, list)
            or not all(isinstance(r, dict) and isinstance(r.get("编号"), str)
                       and isinstance(r.get("正文"), str) for r in 规则)):
        坏["规则"] = "要一个列表,每条 {编号, 正文} 都是字符串(没有规矩就给空列表 [],不许不给)"
    if not isinstance(输入, dict):
        坏["输入"] = "要一个对象(这份产出是照着什么数据写的)"
    elif len(_json.dumps(输入, ensure_ascii=False).encode("utf-8")) > 输入上限字节:
        坏["输入"] = f"超过 {输入上限字节 // 1024}KB —— 只放生成时用到的那份,不要整库导出"
    if not isinstance(输出, str) or not 输出.strip():
        坏["输出"] = "要一个非空字符串(写出来的正文)"
    if 外部trace is not None and (not isinstance(外部trace, str) or len(外部trace) > 200):
        坏["外部trace"] = "要字符串(澜绣那一轮对话的 trace id)或不给"
    if 坏:
        raise _错(422, "VALIDATION", "上报的字段不合格",
                  "见管理后台/HANDOFF.md「产出监督」那一节的字段清单", field_errors=坏)

    输入, 码1 = _打码(输入)
    输出, 码2 = _打码(输出)
    规则, 码3 = _打码(规则)

    with 事务() as c:
        老 = c.execute(text("""select id from artifacts
                             where project_id=:p and external_ref=:e and version_no=:v"""),
                       {"p": project_id, "e": 外部id, "v": 版本}).scalar()
        if 老:
            return _json_resp(200, {"id": 老, "记了吗": False,
                                    "note": "**同一份产出的同一版只记一条** —— 返回原记录"})
        aid = _新id("art")
        try:
            c.execute(text("""
                insert into artifacts (id, organization_id, project_id, external_ref, kind,
                    version_no, display_name, shop_name, world_date, model_name, generation_type,
                    rule_snapshot, input_snapshot, text, external_trace_ref, report_detail,
                    created_at, created_by, updated_at, revision)
                values (:i, :o, :p, :e, :k, :v, :t, :s, cast(:w as date), :m, :g,
                        cast(:r as jsonb), cast(:inp as jsonb), :out, :tr, cast(:rd as jsonb),
                        now(), :u, now(), 1)"""),
                      {"i": aid, "o": _项目组织(c, project_id), "p": project_id, "e": 外部id,
                       "k": 类型, "v": 版本, "t": 标题.strip(), "s": 门店, "w": 世界日期,
                       "m": 模型, "g": 生成方式,
                       "r": _json.dumps(规则, ensure_ascii=False),
                       "inp": _json.dumps(输入, ensure_ascii=False),
                       "out": 输出, "tr": 外部trace,
                       "rd": _json.dumps({"幂等键": idempotency_key,
                                          "入库时打码了几处手机号": 码1 + 码2 + 码3},
                                         ensure_ascii=False),
                       "u": me.user_id})
        except IntegrityError:
            # 并发的同一份同一版:另一条请求先插进去了 —— 当成重复上报,不报 500
            raise _错(409, "DUPLICATE", "这一版刚刚已经被另一条请求记下了", "重发一次会拿到原记录")
    return _json_resp(201, {"id": aid, "记了吗": True,
                            **({"打码": f"入库时把 {码1 + 码2 + 码3} 处完整手机号打了码 —— "
                                        "发送方漏了,请回头查发送方"} if 码1 + 码2 + 码3 else {})})


def _json_resp(code, body):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=code, content=body)


# ══════════════════════════════════════════════════════════════════════
# 列表 / 详情
# ══════════════════════════════════════════════════════════════════════
@router.get(前缀 + "/artifacts")
def 产出列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
         类型: str = Query(None), 状态: str = Query(None),
         limit: int = Query(50, ge=1, le=200)):
    if 类型 is not None and 类型 not in 类型们:
        raise _错(422, "VALIDATION", "类型筛选不对", f"只收 {list(类型们)}",
                  field_errors={"类型": f"只收 {list(类型们)}"})
    状态们 = ("正常", "已打回待执行", "已执行", "执行失败")
    if 状态 is not None and 状态 not in 状态们:
        raise _错(422, "VALIDATION", "状态筛选不对", f"只收 {list(状态们)}",
                  field_errors={"状态": f"只收 {list(状态们)}"})
    with 连接() as c:
        rs = c.execute(text(f"""
            select * from (
              select a.id, a.external_ref, a.kind, a.version_no, a.display_name, a.shop_name,
                     a.model_name, a.generation_type, a.world_date, a.created_at,
                     {_状态片段} as 状态, {_最近理由片段} as 最近打回理由
                from artifacts a
               where a.project_id = :p and a.archived_at is null
                 and (cast(:k as text) is null or a.kind = cast(:k as text))
            ) x
             where (cast(:s as text) is null or x.状态 = cast(:s as text))
        """), {"p": project_id, "k": 类型, "s": 状态}).mappings().all()
    # 总数在筛选**之后**、截断**之前**数 —— 截断后的条数不是总数
    全 = [dict(r) for r in sorted(rs, key=lambda r: (r["created_at"], r["id"]), reverse=True)]
    页 = []
    for r in 全[:limit]:
        页.append(dict(id=r["id"], 外部id=r["external_ref"], 类型=r["kind"], 版本=r["version_no"],
                       标题=r["display_name"], 门店=r["shop_name"], 模型=r["model_name"],
                       生成方式=r["generation_type"], 状态=r["状态"],
                       世界日期=(r["world_date"].isoformat() if r["world_date"] else None),
                       created_at=r["created_at"].isoformat(), 最近打回理由=r["最近打回理由"]))
    return {"items": 页, "next_cursor": None, "total": len(全),
            # 澜绣那侧约好的名字 —— 和 items / total 是同一份,不是另算的
            "rows": 页, "总数": len(全), "这一页几条": len(页)}


@router.get(前缀 + "/artifacts/{artifact_id}")
def 产出详情(project_id: str, artifact_id: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        a = c.execute(text(f"""
            select a.*, {_状态片段} as 状态 from artifacts a
             where a.project_id=:p and a.id=:i"""),
                      {"p": project_id, "i": artifact_id}).mappings().first()
        if not a:
            raise _错(404, "NOT_FOUND", "没有这份产出", "回到产出列表重新选")
        版本们 = c.execute(text(f"""
            select a.id, a.version_no, a.created_at, {_状态片段} as 状态 from artifacts a
             where a.project_id=:p and a.external_ref=:e
             order by a.version_no"""),
                          {"p": project_id, "e": a["external_ref"]}).mappings().all()
        决定们 = c.execute(text("""
            select id, action, reason, status, result, result_note, new_version_no,
                   created_at, created_by, acked_at
              from artifact_decisions
             where project_id=:p and artifact_id=:i
             order by created_at desc, id desc"""),
                          {"p": project_id, "i": artifact_id}).mappings().all()
        链 = None
        if a["external_trace_ref"]:
            # ⚠️ `spans.input_ref` 是 **TEXT**(`_ref` 后缀约定),里面放的是 JSON 字符串 ——
            # 直接 `->>` 当场报 `text ->> unknown`;整列 cast 成 jsonb 又会被某一行不是 JSON 的炸掉。
            # 所以先用 LIKE 粗筛,再在这边**逐条解析确认**「外部trace」那个键真的等于它
            # (粗筛命中的可能只是别的字段里恰好含这串字符)。
            for tid, ir in c.execute(text("""
                    select s.trace_id, s.input_ref from spans s
                     where s.project_id=:p and s.input_ref like :x
                     order by s.created_at limit 20"""),
                    {"p": project_id, "x": f"%{a['external_trace_ref']}%"}).all():
                try:
                    if (_json.loads(ir) or {}).get("外部trace") == a["external_trace_ref"]:
                        链 = tid
                        break
                except (ValueError, TypeError, AttributeError):
                    continue
    if 链:
        调用链 = {"trace_id": 链, "说明": "这份产出是在这一轮调用里生成的"}
    elif a["external_trace_ref"]:
        调用链 = {"trace_id": None,
                  "说明": ("这一轮的调用还没推过来(澜绣那边跑 tools/usage_push.py 之后才有)"
                         f" —— 澜绣那边的号是 {a['external_trace_ref']}")}
    else:
        调用链 = {"trace_id": None,
                  "说明": ("这份产出没有对应的对话调用"
                         + ("(是规则模板写的,没调模型)" if a["generation_type"] == "规则" else
                            "(上报时没带澜绣的 trace id)"))}
    return {
        "id": a["id"], "外部id": a["external_ref"], "类型": a["kind"], "版本": a["version_no"],
        "标题": a["display_name"], "门店": a["shop_name"], "模型": a["model_name"],
        "生成方式": a["generation_type"], "状态": a["状态"],
        "世界日期": a["world_date"].isoformat() if a["world_date"] else None,
        "规则": a["rule_snapshot"] or [], "输入": a["input_snapshot"], "输出": a["text"],
        "外部trace": a["external_trace_ref"], "关联调用链": 调用链,
        "入库时打码了几处手机号": (a["report_detail"] or {}).get("入库时打码了几处手机号", 0),
        "created_at": a["created_at"].isoformat(), "created_by": a["created_by"],
        "版本们": [dict(id=v["id"], 版本=v["version_no"], 状态=v["状态"],
                        created_at=v["created_at"].isoformat()) for v in 版本们],
        "打回历史": [dict(id=d["id"], 动作=d["action"], 理由=d["reason"], 状态=d["status"],
                          结果=d["result"], 结果说明=d["result_note"], 新版本=d["new_version_no"],
                          created_at=d["created_at"].isoformat(), created_by=d["created_by"],
                          acked_at=d["acked_at"].isoformat() if d["acked_at"] else None)
                     for d in 决定们],
        "打回后会发生什么": {
            "建议": "澜绣会照着你写的理由**自动重写一版**,新版本推回来出现在「版本历史」里",
            "报告": "店长那边这份报告会标「被管理平台打回」,**不许确认**,要店长重新生成再存一版",
        }[a["kind"]],
    }


# ══════════════════════════════════════════════════════════════════════
# 打回 → 拉取 → 确认
# ══════════════════════════════════════════════════════════════════════
@router.post(前缀 + "/artifacts/{artifact_id}/reject", status_code=201)
async def 打回一份产出(project_id: str, artifact_id: str, request: Request,
                 me: 身份 = Depends(要权限(打回要的能力))):
    try:
        体 = await request.json()
    except Exception:
        体 = {}
    理由 = (体.get("理由") if isinstance(体, dict) else None) or ""
    理由 = 理由.strip() if isinstance(理由, str) else ""
    if len(理由) < 4:
        raise _错(422, "VALIDATION", "打回要写理由", "至少 4 个字 —— 澜绣重写建议时会照着它改",
                  field_errors={"理由": "至少 4 个字,说清楚哪里不对"})
    with 事务() as c:
        a = c.execute(text("select id from artifacts where project_id=:p and id=:i"),
                      {"p": project_id, "i": artifact_id}).scalar()
        if not a:
            raise _错(404, "NOT_FOUND", "没有这份产出", "回到产出列表重新选")
        有 = c.execute(text("""select id from artifact_decisions
                             where project_id=:p and artifact_id=:i and status='待执行'"""),
                       {"p": project_id, "i": artifact_id}).scalar()
        if 有:
            raise _错(409, "ALREADY_PENDING", "这份产出已经有一条打回在等澜绣执行",
                      f"等它执行完再打回(决定 {有})")
        did = _新id("dec")
        try:
            c.execute(text("""
                insert into artifact_decisions (id, organization_id, project_id, artifact_id,
                    action, reason, status, created_at, created_by, updated_at, revision)
                values (:i, :o, :p, :a, '打回', :r, '待执行', now(), :u, now(), 1)"""),
                      {"i": did, "o": _项目组织(c, project_id), "p": project_id, "a": artifact_id,
                       "r": 理由, "u": me.user_id})
        except IntegrityError:
            # 部分唯一索引兜住的那种:两个人同时点打回
            raise _错(409, "ALREADY_PENDING", "这份产出刚刚已经被另一个人打回了", "刷新看看")
    return {"id": did, "状态": "待执行",
            "note": "已记下。澜绣下次拉取时会执行 —— 管理后台这边**不改澜绣的任何数据**"}


@router.get(前缀 + "/artifact-decisions")
def 打回决定列表(project_id: str, me: 身份 = Depends(要权限("运行评测")),
           状态: str = Query("待执行"), limit: int = Query(100, ge=1, le=500)):
    if 状态 not in ("待执行", "已执行", "执行失败"):
        raise _错(422, "VALIDATION", "状态不对", "只收 待执行 / 已执行 / 执行失败",
                  field_errors={"状态": "只收 待执行 / 已执行 / 执行失败"})
    with 连接() as c:
        rs = c.execute(text("""
            select count(*) over () 全量, d.id, d.artifact_id, a.external_ref, a.kind,
                   a.version_no, d.reason, d.created_by, d.created_at
              from artifact_decisions d
              join artifacts a on a.project_id=d.project_id and a.id=d.artifact_id
             where d.project_id=:p and d.status=:s
             order by d.created_at, d.id
             limit :n"""), {"p": project_id, "s": 状态, "n": limit}).mappings().all()
    页 = [dict(id=r["id"], artifact_id=r["artifact_id"], 外部id=r["external_ref"], 类型=r["kind"],
               版本=r["version_no"], 理由=r["reason"], created_by=r["created_by"],
               created_at=r["created_at"].isoformat()) for r in rs]
    总 = int(rs[0]["全量"]) if rs else 0
    return {"items": 页, "next_cursor": None, "total": 总, "rows": 页, "总数": 总}


@router.post(前缀 + "/artifact-decisions/{decision_id}/ack")
async def 确认执行了(project_id: str, decision_id: str, request: Request,
               me: 身份 = Depends(要权限("运行评测"))):
    try:
        体 = await request.json()
    except Exception:
        体 = {}
    体 = 体 if isinstance(体, dict) else {}
    结果 = 体.get("结果")
    说明 = 体.get("说明")
    新版本 = 体.get("新版本")
    坏 = {}
    if 结果 not in 结果们:
        坏["结果"] = f"只收 {list(结果们)}"
    if 说明 is not None and not isinstance(说明, str):
        坏["说明"] = "要字符串或不给"
    if 新版本 is not None and (not isinstance(新版本, int) or isinstance(新版本, bool) or 新版本 < 1):
        坏["新版本"] = "要 ≥1 的整数或不给(建议重写之后的那一版)"
    if 坏:
        raise _错(422, "VALIDATION", "确认的字段不合格", "结果 / 说明 / 新版本", field_errors=坏)
    with 事务() as c:
        d = c.execute(text("""select status from artifact_decisions
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": decision_id}).scalar()
        if d is None:
            raise _错(404, "NOT_FOUND", "没有这条决定", "重新拉一次待执行列表")
        if d != "待执行":
            raise _错(409, "NOT_PENDING", f"这条决定已经是「{d}」了,不能再确认",
                      "确认过的不许改 —— 要再打回就在管理后台对新版本另打一次")
        c.execute(text("""
            update artifact_decisions
               set status=:s, result=:r, result_note=:n, new_version_no=:v,
                   acked_at=now(), updated_at=now(), revision=revision+1
             where project_id=:p and id=:i"""),
                  {"s": 结果们[结果], "r": 结果, "n": 说明, "v": 新版本,
                   "p": project_id, "i": decision_id})
    return {"id": decision_id, "状态": 结果们[结果], "结果": 结果}
