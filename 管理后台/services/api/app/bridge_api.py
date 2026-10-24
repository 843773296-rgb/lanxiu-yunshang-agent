#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澜绣桥(2026-10-24,用户拍「音频整理全流程」+「核对即定稿,直接写跟进」)。

    GET  /bridge-calls                 澜绣来拉「待执行」的请求(取转写 / 写跟进)
    POST /bridge-calls/{id}/ack        澜绣用它自己的函数执行完,回执结果

## 方向:这边记请求、那边拉去执行 —— 和产出打回同一个形状

工作流里的工具步骤要读澜绣的转写、要往澜绣写一条跟进。管理后台**绝不碰澜绣的库**,
所以工具步骤只在这里记一张单,运行挂起(waiting_external);澜绣的 supervise_sync
拉回去、走它自己的正门执行(那条路上有身份、台账、去重),再回执。回执到了,运行才排回队列接着走。

> 一张「发出去了」就当办成的单,和一张真办成了的,**在运行记录上长得一模一样** ——
> 所以没回执就一直挂着待执行,运行也一直停在那一步。

## 白名单在库里

`tool_name` 只收 取转写 / 写跟进,是表上的 CHECK —— 这条桥不是一个能让工作流
调澜绣任意函数的通道。要加一种,得改契约、出迁移,而那会被看见。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

import run_resume as RR
from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
状态们 = ("待执行", "已执行", "执行失败")


@router.get(前缀 + "/bridge-calls")
def 桥请求列表(project_id: str, me: 身份 = Depends(要权限("运行评测")),
          状态: str = Query("待执行"), execution_run_id: str = Query(None),
          limit: int = Query(100, ge=1, le=500)):
    if 状态 not in 状态们:
        raise _错(422, "VALIDATION", "状态不对", "只收 待执行 / 已执行 / 执行失败",
                  field_errors={"状态": "只收 待执行 / 已执行 / 执行失败"})
    with 连接() as c:
        rs = c.execute(text("""
            select count(*) over () 全量, id, execution_run_id, node_id, tool_name,
                   arguments_snapshot, idempotency_key, status, result_output, error_detail,
                   created_at, acked_at, created_by
              from bridge_calls
             where project_id=:p and status=:s
               and (cast(:r as text) is null or execution_run_id = cast(:r as text))
             order by created_at, id
             limit :n"""), {"p": project_id, "s": 状态, "r": execution_run_id,
                            "n": limit}).mappings().all()
    页 = [dict(id=r["id"], 运行=r["execution_run_id"], 步骤=r["node_id"], 工具=r["tool_name"],
               参数=r["arguments_snapshot"] or {}, 幂等键=r["idempotency_key"], 状态=r["status"],
               结果=r["result_output"], 失败=r["error_detail"], created_by=r["created_by"],
               created_at=r["created_at"].isoformat(),
               acked_at=r["acked_at"].isoformat() if r["acked_at"] else None) for r in rs]
    总 = int(rs[0]["全量"]) if rs else 0
    return {"items": 页, "next_cursor": None, "total": 总, "rows": 页, "总数": 总}


@router.post(前缀 + "/bridge-calls/{call_id}/ack")
async def 桥回执(project_id: str, call_id: str, request: Request,
           me: 身份 = Depends(要权限("运行评测"))):
    """入参 `{结果: 已执行|执行失败, 输出?: {...}, 失败?: {code, 消息, 建议?}}`。"""
    try:
        体 = await request.json()
    except Exception:
        体 = {}
    体 = 体 if isinstance(体, dict) else {}
    结果, 输出, 失败 = 体.get("结果"), 体.get("输出"), 体.get("失败")
    坏 = {}
    if 结果 not in ("已执行", "执行失败"):
        坏["结果"] = "只收 已执行 / 执行失败"
    if 结果 == "已执行" and not isinstance(输出, dict):
        坏["输出"] = "已执行要带输出(对象)—— 下一步要拿它当这一步的结果"
    if 结果 == "执行失败" and not (isinstance(失败, dict) and 失败.get("code")):
        坏["失败"] = "执行失败要带 {code, 消息} —— 一条不说为什么的失败,运行页上只能写「出错」"
    if 坏:
        raise _错(422, "VALIDATION", "回执的字段不合格", "结果 / 输出 / 失败", field_errors=坏)
    import json as _j
    with 事务() as c:
        r = c.execute(text("""select status, execution_run_id from bridge_calls
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": call_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这张桥请求", "重新拉一次待执行列表")
        if r["status"] != "待执行":
            raise _错(409, "NOT_PENDING", f"这张单已经是「{r['status']}」了,不能再回执",
                      "回执过的不许改 —— 同一步要重做就重新发起一次运行")
        c.execute(text("""
            update bridge_calls
               set status=:s, result_output=cast(:o as jsonb), error_detail=cast(:e as jsonb),
                   acked_at=now(), updated_at=now(), revision=revision+1
             where project_id=:p and id=:i"""),
                  {"s": 结果, "o": _j.dumps(输出, ensure_ascii=False) if 结果 == "已执行" else None,
                   "e": _j.dumps(失败, ensure_ascii=False) if 结果 == "执行失败" else None,
                   "p": project_id, "i": call_id})
        job, 说 = RR.排恢复(c, project_id=project_id, run_id=r["execution_run_id"],
                          为什么=f"澜绣回执 {call_id}:{结果}", 谁=me.user_id)
    return {"id": call_id, "状态": 结果, "恢复任务": job, "说明": 说}
