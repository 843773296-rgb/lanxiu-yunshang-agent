# -*- coding: utf-8 -*-
"""知识条目修订申请(2026-11-17,执行手册 W28;用户 11-12 拍「总部运营审,开发合并」—— 业务拍板 十八)。

## 为什么是这个形状

knowledge/*.md 是业务口径的真相源(推导脚本读它、工具只取数)。门店同学发现一条口径不对(「大袖衫必须配内搭」史料对不上),
原来只能口头告诉开发。现在:**谁都能提**(和提意见同一个能力),**只总部运营审**(用户否决「店长就能审」:三家店可能改出三个版本),
**审过不直接改 md** —— 采纳那一刻生成一段改动文本(新口径 + 括号注记,形状照 knowledge/01-形制.md 里 11-07 那 9 处),
开发照着改、重跑 derive、过门禁,再把这条标「已合并」。改 md 是人的活,这里只把「谁、凭什么、改成什么」记牢。

## 判据全是结构能验的

  · 指到的文件必须是 knowledge/ 下真有的 md;指到的段必须是那份文件里真有的标题(## / ###)
  · 「原来写的」必须在那份文件里**原样找得到**(≥ 4 字)—— 不然 patch 没法落到具体一行,开发只能猜
  · 「改成」不能和「原来写的」一样;「依据」不能空(≥ 4 字)
  · 驳回必须写为什么;不能审自己提的;只有待审能审,只有已采纳能标已合并(状态别的 → 409)
  · 库 CHECK 再钉一次(models.py / 迁移同一组)

没做:把 patch 自动写进 md(改 md 要重跑 derive 和门禁,是开发那一步的事);「66 条 biz 口径可勾表」(手册里另一件事)。
"""
import datetime as _dt
import json as _json
import os
import re
import uuid as _uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
上海 = ZoneInfo("Asia/Shanghai")
根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
知识目录 = os.path.join(根, "knowledge")
状态们 = ("待审", "已采纳", "已驳回", "已合并")
提权限 = "运行评测"            # 门店侧的人 —— 和提意见同一个能力(opinions_api)
审权限 = "受理意见"            # 总部运营 —— 和问题单 / 能力档案一致(用户 11-12 拍「与问题单权限一致」)
合并权限 = "生产审核/发布/回滚"   # 开发 / 发布那拨人:改完 md、过了门禁才标
最长 = 2000


def 知识文件们():
    if not os.path.isdir(知识目录):
        return []
    return sorted(f for f in os.listdir(知识目录) if f.endswith(".md") and f != "README.md")


def 段们(文件名):
    路 = os.path.join(知识目录, 文件名)
    if not os.path.isfile(路):
        return None
    出 = []
    for l in open(路, encoding="utf-8").read().split("\n"):
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", l)
        if m:
            出.append(m.group(2))
    return 出


def 校验(体):
    """→ (出, 坏)。出 = 列名 → 值;坏 = 请求体里的名字 → 为什么不行。"""
    def 字(k):
        v = 体.get(k)
        return v.strip() if isinstance(v, str) else None
    出, 坏 = {}, {}
    文件 = 字("知识文件")
    if not 文件 or 文件 not in 知识文件们():
        坏["知识文件"] = f"要是 knowledge/ 下真有的那份 md,现在有 {len(知识文件们())} 份(GET …/knowledge-revisions/files 取清单)"
    段 = 字("段")
    if 文件 and 文件 in 知识文件们():
        if not 段 or 段 not in (段们(文件) or []):
            坏["段"] = "要是那份文件里真有的一段标题(## 或 ###;GET …/knowledge-revisions/files?file=… 取清单)"
    原 = 字("原来写的")
    if not 原 or len(原) < 4:
        坏["原来写的"] = "至少 4 字 —— 要能在文件里原样找到那一句,改动才落得到具体一行"
    elif 文件 and 文件 in 知识文件们():
        if 原 not in open(os.path.join(知识目录, 文件), encoding="utf-8").read():
            坏["原来写的"] = "这句话在那份文件里原样找不到(多半是转述了)—— 从文件里原样复制过来"
    改 = 字("改成")
    if not 改:
        坏["改成"] = "必填:改成什么"
    elif 原 and 改 == 原:
        坏["改成"] = "和原来写的一样,没改"
    elif len(改) > 最长:
        坏["改成"] = f"最多 {最长} 字"
    依据 = 字("依据")
    if not 依据 or len(依据) < 4:
        坏["依据"] = "至少 4 字:史料 / 标准 / 业务拍板 —— 没依据的改口径就是另一个人的口径"
    elif len(依据) > 最长:
        坏["依据"] = f"最多 {最长} 字"
    出.update(knowledge_path=文件, section_name=段, current_text=原, proposed_text=改, basis_note=依据)
    return 出, 坏


def 注记(日期, 审的人, 编号, 依据, 原来):
    """括号注记,形状照 knowledge/01-形制.md 11-07 那 9 处:「(日期 用户拍「按史料改」;依据:…;原来写的是「…」)」。"""
    return f"({日期} 总部运营 {审的人} 审过的修订申请 {编号};依据:{依据};原来写的是「{原来}」)"


def 生成改动(r, 日期, 审的人):
    新句 = f"{r['proposed_text']} {注记(日期, 审的人, r['id'], r['basis_note'], r['current_text'])}"
    return (f"文件:knowledge/{r['knowledge_path']}\n段:{r['section_name']}\n"
            f"--- 原来写的(在文件里原样找这一句)\n{r['current_text']}\n"
            f"+++ 改成(连括号注记一起)\n{新句}\n"
            f"\n开发:照着改 md → 重跑 knowledge/derive_*.py → ./check.sh 绿 → 回来把这条标「已合并」(POST …/{r['id']}/merged)")


def _项目组织(c, project_id):
    org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
    if not org:
        raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
    return org


def _审计(c, me, action, target, reason=None):
    from apps_api import _审计 as _a
    _a(c, me, action, target, reason=reason)


async def _json体(request):
    try:
        体 = await request.json()
    except Exception:  # noqa: BLE001
        return None
    return 体 if isinstance(体, dict) else None


def _给人看(r):
    def t(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    return {"id": r["id"], "知识文件": r["knowledge_path"], "段": r["section_name"], "原来写的": r["current_text"],
            "改成": r["proposed_text"], "依据": r["basis_note"], "提的人": r["applicant_code"], "状态": r["status"],
            "审核说明": r["review_note"], "审的人": r["reviewed_by"], "审的时刻": t(r["reviewed_at"]),
            "改动文本": r["patch_text"], "合并的人": r["merged_by"], "合并时刻": t(r["merged_at"]),
            "提交时刻": t(r["created_at"]), "revision": r["revision"]}


@router.get(前缀 + "/knowledge-revisions/files")
def 知识文件清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")), file: str = Query(None)):
    """不带 file:knowledge/ 下的 md 清单;带 file:那份文件里的段标题。页面的两个下拉从这里取,不在前端抄一份。"""
    if file:
        段 = 段们(file)
        if 段 is None:
            raise _错(404, "NOT_FOUND", f"knowledge/ 下没有 {file}", "先取文件清单")
        return {"文件": file, "段": 段}
    return {"文件们": 知识文件们(), "note": "指到哪份 md、哪一段;「原来写的」要从文件里原样复制一句"}


@router.post(前缀 + "/knowledge-revisions", status_code=201)
async def 提修订(project_id: str, request: Request, me: 身份 = Depends(要权限(提权限))):
    """`{知识文件, 段, 原来写的, 改成, 依据}` → 201 {id, 状态: 待审}。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验(体)
    if 坏:
        raise _错(422, "VALIDATION", "修订申请的字段不合格", "见字段错误", field_errors=坏)
    rid = f"kr_{_uuid.uuid4().hex[:12]}"
    with 事务() as c:
        org = _项目组织(c, project_id)
        c.execute(text("""insert into knowledge_revisions (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                              knowledge_path, section_name, current_text, proposed_text, basis_note, applicant_code, status)
                          values (:i, :o, :p, now(), :u, now(), 1, :f, :s, :cur, :new, :b, :u, '待审')"""),
                  {"i": rid, "o": org, "p": project_id, "u": me.user_id, **{"f": 出["knowledge_path"], "s": 出["section_name"],
                   "cur": 出["current_text"], "new": 出["proposed_text"], "b": 出["basis_note"]}})
        _审计(c, me, "knowledge_revision.create", {"id": rid, "file": 出["knowledge_path"], "section": 出["section_name"]})
    return {"id": rid, "状态": "待审", "note": "提好了,等总部运营审。审过会生成改动文本,由开发改 md"}


@router.get(前缀 + "/knowledge-revisions")
def 修订清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")), status: str = Query(None),
         limit: int = Query(50, ge=1, le=200), cursor: int = Query(0, ge=0)):
    """契约登记为 列表=True,统一信封 items / next_cursor / total(§19.1):游标就是偏移量,翻到底给 null。"""
    if status and status not in 状态们:
        raise _错(422, "VALIDATION", f"状态只认 {' / '.join(状态们)}", "按这几个筛", field_errors={"status": "不认识"})
    with 连接() as c:
        rs = c.execute(text("""select count(*) over () 全量, * from knowledge_revisions
                               where project_id=:p and archived_at is null """ + ("and status=:s " if status else "") +
                            """order by (status='待审') desc, created_at desc limit :n offset :o"""),
                       {"p": project_id, "n": limit, "o": cursor, **({"s": status} if status else {})}).mappings().all()
    total = int(rs[0]["全量"]) if rs else 0
    return {"items": [_给人看(r) for r in rs], "total": total, "状态们": list(状态们),
            "next_cursor": str(cursor + len(rs)) if cursor + len(rs) < total else None,
            "note": "待审的排前面。**只总部运营审**;审过的改动文本由开发改进 md,改完回来标「已合并」"}


@router.get(前缀 + "/knowledge-revisions/{rid}")
def 修订详情(project_id: str, rid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        r = c.execute(text("select * from knowledge_revisions where project_id=:p and id=:i"), {"p": project_id, "i": rid}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", f"没有修订申请 {rid}", "回清单重新进入")
    出 = _给人看(r)
    出["能做的动作"] = ({"待审": ["采纳", "驳回"], "已采纳": ["已合并"]}.get(r["status"], []))
    return 出


@router.post(前缀 + "/knowledge-revisions/{rid}/review")
async def 审修订(project_id: str, rid: str, request: Request, me: 身份 = Depends(要权限(审权限))):
    """`{决定: 采纳 | 驳回, 说明?}`。驳回必须写说明;不能审自己提的;只有待审能审。采纳 → 生成改动文本。"""
    体 = await _json体(request) or {}
    决定 = (体.get("决定") or "").strip()
    说明 = (体.get("说明") or "").strip() or None
    if 决定 not in ("采纳", "驳回"):
        raise _错(422, "VALIDATION", "决定只能是 采纳 / 驳回", "见字段错误", field_errors={"决定": "必填"})
    if 决定 == "驳回" and not 说明:
        raise _错(422, "VALIDATION", "驳回要写为什么", "提的人看得到这句话", field_errors={"说明": "驳回必填"})
    if 说明 and len(说明) > 最长:
        raise _错(422, "VALIDATION", f"说明最多 {最长} 字", "精简一下", field_errors={"说明": "太长"})
    with 事务() as c:
        r = c.execute(text("select * from knowledge_revisions where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有修订申请 {rid}", "回清单重新进入")
        if r["status"] != "待审":
            raise _错(409, "NOT_PENDING", f"这条已经是「{r['status']}」,不能再审", "只有待审的能审")
        if r["applicant_code"] == me.user_id:
            raise _错(409, "SELF_REVIEW", "不能审自己提的修订", "找另一位总部运营")
        日期 = _dt.datetime.now(上海).strftime("%Y-%m-%d")
        新状态 = "已采纳" if 决定 == "采纳" else "已驳回"
        改动 = 生成改动(dict(r), 日期, me.user_id) if 决定 == "采纳" else None
        c.execute(text("""update knowledge_revisions set status=:s, review_note=:n, reviewed_by=:u, reviewed_at=now(),
                              patch_text=:pt, updated_at=now(), revision=revision+1 where project_id=:p and id=:i"""),
                  {"s": 新状态, "n": 说明, "u": me.user_id, "pt": 改动, "p": project_id, "i": rid})
        _审计(c, me, "knowledge_revision.review", {"id": rid, "决定": 决定}, reason=说明)
    return {"id": rid, "状态": 新状态, "改动文本": 改动,
            "note": "采纳了:把改动文本交给开发改 md,改完过门禁再标已合并" if 决定 == "采纳" else "驳回了,说明提的人看得到"}


@router.post(前缀 + "/knowledge-revisions/{rid}/merged")
async def 标已合并(project_id: str, rid: str, request: Request, me: 身份 = Depends(要权限(合并权限))):
    """开发把 md 改了、过了门禁,回来标一下。只有已采纳能标。"""
    with 事务() as c:
        r = c.execute(text("select status from knowledge_revisions where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有修订申请 {rid}", "回清单重新进入")
        if r["status"] != "已采纳":
            raise _错(409, "NOT_ACCEPTED", f"这条是「{r['status']}」,只有已采纳的能标已合并", "先审")
        c.execute(text("""update knowledge_revisions set status='已合并', merged_by=:u, merged_at=now(), updated_at=now(),
                              revision=revision+1 where project_id=:p and id=:i"""), {"u": me.user_id, "p": project_id, "i": rid})
        _审计(c, me, "knowledge_revision.merged", {"id": rid})
    return {"id": rid, "状态": "已合并"}
