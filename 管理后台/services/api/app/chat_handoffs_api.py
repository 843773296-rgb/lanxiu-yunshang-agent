# -*- coding: utf-8 -*-
"""聊天转人工(2026-11-09)。店长助手这一轮不让模型答、交给人处理时,在这里落一条待办。

## 为什么单独一张表,不塞进 human_requests

human_requests 是某次工作流运行的子对象,还绑着审批的参数摘要。聊天转人工不是工作流运行 ——
硬塞要么伪造一次运行,要么放松那张表的约束。

## 身份

和意见单同一条内部通道:服务账号 + X-Lanxiu-Internal + 只收本机;店长是谁由聊天站从登录会话换出来。

## 原话

处理的人要看到店长说了什么,所以存;但它是店长的原始输入:列表不给,详情只给有「受理意见」的人(处理这件事的人)。
不用「查看敏感输入」:那项默认谁都没有、要专门授权,用它的话处理的人默认看不到原话,待办办不了。

## 防重

同一轮(chat_trace_ref)只一条:聊天站重试不会变成两条待办,重试拿回的是原来那个编号。
"""
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
from opinions_api import 内部通道核对

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
状态们 = ("待处理", "已处理")
原话最长 = 4000
说明最长 = 1000


def 校验(体):
    """→ (干净的字段, 坏字段)。纯函数。"""
    坏, 出 = {}, {}
    def 字(k):
        v = 体.get(k)
        return (str(v).strip() or None) if v is not None else None
    出["聊天站trace"] = 字("聊天站trace")
    if not 出["聊天站trace"] or len(出["聊天站trace"]) > 200:
        坏["聊天站trace"] = "要给聊天站那一轮的号 —— 同一轮只建一条,靠它防重"
    出["会话号"] = 字("会话号")
    出["原话"] = 字("原话")
    if not 出["原话"]:
        坏["原话"] = "要给店长的原话 —— 处理的人得知道他问了什么"
    elif len(出["原话"]) > 原话最长:
        坏["原话"] = f"最多 {原话最长} 字"
    出["意图"] = 字("意图")
    出["原因"] = 字("原因")
    if not 出["原因"]:
        坏["原因"] = "要说为什么转人工(投诉 / 判不出 / 分类调用失败……)"
    人 = 体.get("提问人") if isinstance(体.get("提问人"), dict) else {}
    出["工号"] = str(人.get("工号") or "").strip()
    if not 出["工号"]:
        坏["提问人"] = "要给店长工号 —— 由聊天站从登录会话换出来"
    出["快照"] = {k: 人.get(k) for k in ("工号", "姓名", "角色", "门店")}
    return 出, 坏


def _列表行(r):
    return {"id": r["id"], "status": r["status"], "intent_name": r["intent_name"], "reason_note": r["reason_note"],
            "asker_snapshot": r["asker_snapshot"], "created_at": r["created_at"], "revision": r["revision"]}


@router.post(前缀 + "/chat-handoffs", status_code=201)
async def 建转人工(project_id: str, request: Request, me: 身份 = Depends(要权限("运行评测"))):
    行, 因 = 内部通道核对(request.headers.get("X-Lanxiu-Internal"), request.client.host if request.client else None)
    if not 行:
        raise _错(403, "INTERNAL_ONLY", 因, "这个口只收聊天站转来的 —— 店长是谁要由聊天站从登录会话换出来")
    try:
        体 = await request.json()
    except Exception:
        体 = None
    if not isinstance(体, dict):
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验(体)
    if 坏:
        raise _错(422, "VALIDATION", "转人工的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
        if not org:
            raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
        c.execute(text("""
            insert into chat_handoffs (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                   chat_trace_ref, session_ref, asker_staff_code, asker_snapshot, question_note, intent_name, reason_note, status)
            values (:i, :o, :p, now(), :u, now(), 1, :tr, :ss, :sc, cast(:snap as jsonb), :q, :it, :rs, '待处理')
            on conflict (project_id, chat_trace_ref) do nothing"""),
            {"i": f"ho_{_uuid.uuid4().hex[:12]}", "o": org, "p": project_id, "u": me.user_id, "tr": 出["聊天站trace"],
             "ss": 出["会话号"], "sc": 出["工号"], "snap": _json.dumps(出["快照"], ensure_ascii=False),
             "q": 出["原话"], "it": 出["意图"], "rs": 出["原因"]})
        r = c.execute(text("select id, status from chat_handoffs where project_id=:p and chat_trace_ref=:tr"),
                      {"p": project_id, "tr": 出["聊天站trace"]}).mappings().first()
    return {"id": r["id"], "status": r["status"]}


@router.get(前缀 + "/chat-handoffs")
def 转人工列表(project_id: str, status: str = Query(default=None), page: int = 1, page_size: int = 20,
          me: 身份 = Depends(要权限("查看有权配置"))):
    if status is not None and status not in 状态们:
        raise _错(422, "VALIDATION", f"status 只收 {list(状态们)}", "去掉或改对")
    page, page_size = max(page, 1), min(max(page_size, 1), 100)
    条件 = "project_id=:p" + (" and status=:s" if status else "")
    参 = {"p": project_id, "s": status}
    with 连接() as c:
        总 = c.execute(text(f"select count(*) from chat_handoffs where {条件}"), 参).scalar()
        行们 = c.execute(text(f"""select * from chat_handoffs where {条件}
                                 order by (status='待处理') desc, created_at desc limit :l offset :o"""),
                         {**参, "l": page_size, "o": (page - 1) * page_size}).mappings().all()
    return {"items": [_列表行(r) for r in 行们], "page": page, "page_size": page_size, "total": 总}


@router.get(前缀 + "/chat-handoffs/{handoff_id}")
def 转人工详情(project_id: str, handoff_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        r = c.execute(text("select * from chat_handoffs where project_id=:p and id=:i"),
                      {"p": project_id, "i": handoff_id}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", "没有这条转人工", "确认编号")
    能看, _ = me.能("受理意见")
    return {**_列表行(r), "chat_trace_ref": r["chat_trace_ref"], "session_ref": r["session_ref"],
            "handled_by": r["handled_by"], "handled_at": r["handled_at"], "note": r["note"],
            "question_note": r["question_note"] if 能看 else None,
            "原话看得到吗": bool(能看), "还能处理吗": r["status"] == "待处理" and bool(me.能("受理意见")[0])}


@router.post(前缀 + "/chat-handoffs/{handoff_id}/resolve")
async def 处理转人工(project_id: str, handoff_id: str, request: Request, if_match: str = Header(default=None, alias="If-Match"),
              me: 身份 = Depends(要权限("受理意见"))):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "先读详情拿 revision")
    try:
        体 = await request.json()
    except Exception:
        体 = None
    说明 = str((体 or {}).get("说明") or "").strip() if isinstance(体, dict) else ""
    if not 说明 or len(说明) > 说明最长:
        raise _错(422, "VALIDATION", "要写一句怎么处理的", f"1~{说明最长} 字", field_errors={"说明": "必填"})
    with 事务() as c:
        r = c.execute(text("select status, revision from chat_handoffs where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": handoff_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条转人工", "确认编号")
        if r["status"] != "待处理":
            raise _错(409, "ALREADY_HANDLED", "这条已经处理过了", "刷新看处理结果")
        if str(r["revision"]) != if_match.strip().strip('"'):
            raise _错(409, "REVISION_CONFLICT", "别人刚改过", "刷新后再处理")
        c.execute(text("""update chat_handoffs set status='已处理', handled_by=:u, handled_at=now(), note=:n,
                          updated_at=now(), revision=revision+1 where project_id=:p and id=:i"""),
                  {"u": me.user_id, "n": 说明, "p": project_id, "i": handoff_id})
    return {"id": handoff_id, "status": "已处理"}
