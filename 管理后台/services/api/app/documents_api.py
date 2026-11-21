# -*- coding: utf-8 -*-
"""工作流产出的文档(11-21,「Markdown 导出」节点;用户拍第一个业务定时任务 = 经营日报草稿 + Markdown 导出)。

    GET /workflow-documents                 列表(?run_id= 只看某次运行;登记了门店的成员只看本店或不限门店的)
    GET /workflow-documents/{id}            元信息(哈希 / 字节 / 统计期 / 流程版本 / 生成与存成时刻)
    GET /workflow-documents/{id}/download   原文(text/markdown; charset=utf-8,带 Content-Disposition)—— **交出系统,逐次审计**

写入只在 worker 的适配器里(runtime/文档导出 算名字 / 哈希,storage 存字节,这里不提供上传口):
一份文档是**某次运行的产物**,不是人手传的文件 —— 要改就重跑那一步,旧的留着当证据。
门店范围和人工待办同一份口径(runtime/门店范围.看得到吗):定不出门店的文档只给不限门店的人。
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"))

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text

import storage as ST
import 门店范围 as SS
from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _门店片(me):
    if me.store_id is None:
        return "", {}
    return " and (store_id is null and false or upper(trim(coalesce(store_id, ''))) = :my_store) ", {"my_store": me.store_id}


def _行(d):
    d = dict(d)
    d["下载"] = f"/api/v1/projects/{d['project_id']}/workflow-documents/{d['id']}/download" if d.get("status") == "已存" else None
    return d


@router.get(前缀 + "/workflow-documents")
def 文档列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
         run_id: str = Query(None), limit: int = Query(50, ge=1, le=200)):
    片, 参 = _门店片(me)
    with 连接() as c:
        rs = c.execute(text(f"""
            select count(*) over () 全量, id, project_id, execution_run_id, node_id, workflow_version_id, kind, title, file_name, content_type,
                   byte_count, content_hash, status, period_detail, template_version, owner, store_id, generated_at, stored_at, created_at
              from workflow_documents
             where project_id=:p and archived_at is null
               and (cast(:r as text) is null or execution_run_id = cast(:r as text)) {片}
             order by created_at desc, id desc
             limit :n"""), {"p": project_id, "r": run_id, "n": limit, **参}).mappings().all()
    出 = []
    for r in rs:
        d = _行(r); d.pop("全量", None); 出.append(d)
    return {"items": 出, "total": (int(rs[0]["全量"]) if rs else 0), "这一页几条": len(出), "我的门店": me.store_id,
            "note": "每一份是某次运行里「Markdown 导出」那一步存下来的;**只有 status=已存(回读核过哈希)的才有下载地址**。"
                    + (f" 你登记在 {me.store_id} 门店,只列本店的文档" if me.store_id else "")}


def _取(c, project_id, did, me):
    片, 参 = _门店片(me)
    r = c.execute(text(f"""select * from workflow_documents where project_id=:p and id=:i and archived_at is null {片}"""),
                  {"p": project_id, "i": did, **参}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", "没有这份文档", "回运行详情重新进入" + (";你只看得到本店的文档" if me.store_id else ""))
    return r


@router.get(前缀 + "/workflow-documents/{did}")
def 文档详情(project_id: str, did: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        r = _取(c, project_id, did, me)
    return {"文档": _行(r), "看得到吗": SS.看得到吗(me.store_id, r["store_id"])}


@router.get(前缀 + "/workflow-documents/{did}/download")
def 下载文档(project_id: str, did: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """原文。**读出来再算一次哈希,和库里记的不一样就 500 不给**(存储和库两边对不上,不是「文件坏了」能糊过去的事)。"""
    with 事务() as c:
        r = _取(c, project_id, did, me)
        if r["status"] != "已存" or not r["object_key"]:
            raise _错(409, "DOCUMENT_NOT_STORED", "这份文档还没存成(生成了正文,文件没落下)", "看运行详情里这一步的事件;重跑那一步会出一份新的")
        try:
            字节 = ST.读出(r["object_key"])
        except ST.存不了 as e:
            raise _错(500, "OBJECT_STORE_FAILED", str(e)[:200], "存储里没有库里记的那个对象 —— 两边不一致,请技术管理员看存储")
        哈 = hashlib.sha256(字节).hexdigest()
        if 哈 != r["content_hash"]:
            raise _错(500, "DOCUMENT_HASH_MISMATCH", "文件内容和登记的哈希对不上,不给下载", "存储里的字节被改过或写坏了;重跑那一步出一份新的")
        from workflows_api import _审计
        _审计(c, me, "workflow_document.download", {"document_id": did, "file_name": r["file_name"], "byte_count": r["byte_count"], "content_hash": 哈})
    文件名 = (r["file_name"] or f"{did}.md").replace('"', "")
    from urllib.parse import quote
    return Response(content=字节, media_type=r["content_type"] or "text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(文件名)}", "X-Content-Hash": 哈})
