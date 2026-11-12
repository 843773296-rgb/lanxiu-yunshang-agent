# -*- coding: utf-8 -*-
"""能力档案与改进看板(2026-11-12)。口径照《意见收集与能力持续改进 PRD》(10-24)§4.4 / §7.1 / §8。

## 能力档案是什么

一项业务能力一份:业务目标、输入输出、适用角色、负责人、状态、**已验证范围**(一段文字)、依赖清单(只存引用)、
下次验证事项。状态 / 流转只在 `capability_flow.py` 写一次,这里按它判(不在表里的 409),详情里「能做的动作」也从它算。

## 三样「现查不存」的数

评测结果 / 样本数量 / 实际运行量**不存进档案**,详情读的时候现查;**查不到就写「没有数据」,不给 0**:

- 评测结果:evaluations 里候选或基线是**依赖里那几条工作流的某个版本**的(后台派发记 candidate_ref.kind = workflow_version)。
  外部登记的评测只记了一段候选文字,对不上是哪个工作流 → 不算进来;智能体 / Skill / 工具没有评测关联 → 不显示。
  **只列评测本身(状态、能不能当结论),不在这里算分** —— 分数看评测中心。
- 样本数量:上面那些评测用的冻结数据集版本,每个版本各有几题(dataset_versions.frozen_samples 的长度)。
  **不跨版本加总**:两版之间可能有同一道题,加起来会重复数。
- 实际运行量:execution_runs 里 kind=workflow / agent 且 definition_ref.id 是依赖里那条工作流 / 智能体的,
  按监测的口径分「业务」和「调试」(那段 SQL 从 monitoring_api 取,不另写一份)。Skill / 工具的调用不按它们记运行 → 不显示。

## 看板

问题单按根因、能力、状态数:总数、未解决、观察期复发过、关闭后重开过。**只出数和分母,不出结论 / 排名 / 打分**:
行按口径里定义的顺序排(根因按 PRD 那 9 类、状态按流转顺序、能力按名字),不按数量排。已重复的单不计入(它指向主问题,
算主问题那张),单独给一个数。PRD §4.4 还要「按门店和版本」看 —— 问题单上没有门店 / 版本这两列,这次没做。

## 这次没做 / 暂定的(写清楚,别当成做了)

- **权限暂定**:读用「查看有权配置」,写**暂用「受理意见」**(总部运营)—— PRD §10 每项能力由谁负责没拍。
- 验证门槛、观察窗口:PRD §10 待定,这里一个数都不定。只钉一条结构:试点中 / 已启用 必须写了已验证范围(写得够不够不判)。
- 「依赖版本」只给依赖现在的名字和状态,不冻结「档案指的是哪一版」—— 绑发布版本是 PRD §4.3 的事。
"""
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import capability_flow as F

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 请求体里的名字 → 列。PATCH / 建档能写的就这些;状态只能走流转
文字字段 = {
    "名字": "name", "业务目标": "business_goal_note", "输入": "input_note", "输出": "output_note",
    "负责人": "owner", "已验证范围": "verified_scope_note", "下次验证事项": "next_verification_note",
}
清单字段 = {"适用角色": "applicable_roles", "依赖": "dependencies"}
可改字段 = {**文字字段, **清单字段}
短字段上限 = {"名字": 100, "负责人": 100}
长文上限 = 2000
说明最长 = 1000
角色上限, 依赖上限 = 20, 50


def _字(体, k):
    v = 体.get(k)
    return (str(v).strip() or None) if v is not None else None


def _给人看(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def 校验字段(体, 新建=False):
    """→ (列: 值, 坏字段)。纯函数,不碰库(依赖在不在库里另查);只看请求体里**给了**的键。空串 = 清空。"""
    出, 坏 = {}, {}
    for k, 列 in 文字字段.items():
        if k not in 体:
            continue
        v = _字(体, k)
        if v and len(v) > 短字段上限.get(k, 长文上限):
            坏[k] = f"最多 {短字段上限.get(k, 长文上限)} 字"
            continue
        出[列] = v
    if "适用角色" in 体:
        v = 体.get("适用角色")
        if v is None or v == "":
            出["applicable_roles"] = []
        elif not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            坏["适用角色"] = "要是一串角色名(例:[\"店长\", \"顾问\"])"
        elif len(v) > 角色上限 or any(len(x.strip()) > 50 for x in v):
            坏["适用角色"] = f"最多 {角色上限} 个,每个最多 50 字"
        else:
            出["applicable_roles"] = list(dict.fromkeys(x.strip() for x in v))
    if "依赖" in 体:
        v = 体.get("依赖")
        if v is None or v == "":
            出["dependencies"] = []
        elif not isinstance(v, list):
            坏["依赖"] = "要是一串 {种类, 引用}"
        elif len(v) > 依赖上限:
            坏["依赖"] = f"最多 {依赖上限} 条"
        else:
            清 = []
            for i, x in enumerate(v):
                种, 引 = (x.get("种类"), x.get("引用")) if isinstance(x, dict) else (None, None)
                if 种 not in F.依赖种类:
                    坏["依赖"] = f"第 {i + 1} 条的种类只收 {list(F.依赖种类)}"
                    break
                if not isinstance(引, str) or not 引.strip():
                    坏["依赖"] = f"第 {i + 1} 条没写引用(智能体 / 工作流 / 工具写编号,Skill 写名字)"
                    break
                项 = {"种类": 种, "引用": 引.strip()}
                if 项 not in 清:
                    清.append(项)
            else:
                出["dependencies"] = 清
    if 新建:
        if not 出.get("name"):
            坏["名字"] = "要写这项能力叫什么 —— 清单里只看得到这一句"
        出.setdefault("applicable_roles", [])
        出.setdefault("dependencies", [])
    elif "name" in 出 and not 出["name"]:
        坏["名字"] = "名字不能清空"
    return 出, 坏


def _核依赖(c, project_id, 依赖):
    """依赖清单里每一条在这个项目里真有吗 → 坏字段(空 = 都有)。**只核在不在,不复制定义**。"""
    for i, x in enumerate(依赖 or []):
        表, 列 = F.依赖种类[x["种类"]]
        n = c.execute(text(f"select count(*) from {表} where project_id=:p and {列}=:r and archived_at is null"),
                      {"p": project_id, "r": x["引用"]}).scalar()
        if not n:
            return {"依赖": f"第 {i + 1} 条:这个项目里没有{x['种类']}「{x['引用']}」(只能引用同一个项目里现有的)"}
    return {}


def _读依赖(c, project_id, 依赖):
    """读的时候现取依赖的名字和状态 —— 档案里只存引用。被删 / 归档了就照实写「找不到」。"""
    出 = []
    for x in 依赖 or []:
        种, 引 = x.get("种类"), x.get("引用")
        if 种 == "Skill":
            r = c.execute(text("""select name 名, review_status 状态, version_no from skill_versions
                                   where project_id=:p and name=:r and archived_at is null
                                   order by version_no desc limit 1"""), {"p": project_id, "r": 引}).mappings().first()
        elif 种 in F.依赖种类:
            表 = F.依赖种类[种][0]
            r = c.execute(text(f"select name 名, status 状态 from {表} where project_id=:p and id=:r and archived_at is null"),
                          {"p": project_id, "r": 引}).mappings().first()
        else:
            r = None
        出.append({"种类": 种, "引用": 引, "找得到": bool(r), "名字": r["名"] if r else None,
                  "状态": (r["状态"] if r else "找不到(被删或归档了)"),
                  **({"最新版本": f"v{r['version_no']}"} if r and "version_no" in r else {})})
    return 出


async def _json体(request):
    try:
        体 = await request.json()
    except Exception:
        return None
    return 体 if isinstance(体, dict) else None


def _项目组织(c, project_id):
    org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
    if not org:
        raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
    return org


def _记一步(c, org, project_id, me, cid, 动作, 从, 到, 说明, 变化=None):
    c.execute(text("""insert into capability_profile_events (id, organization_id, project_id, created_at, created_by,
                          capability_profile_id, action_code, from_status, to_status, note, change_snapshot)
                      values (:i, :o, :p, now(), :u, :c, :a, :f, :t, :n, cast(:ch as jsonb))"""),
              {"i": f"ce_{_uuid.uuid4().hex[:12]}", "o": org, "p": project_id, "u": me.user_id, "c": cid,
               "a": 动作, "f": 从, "t": 到, "n": 说明,
               "ch": _json.dumps(变化, ensure_ascii=False, default=str) if 变化 else None})


def _重名(c, project_id, 名, 除了=None):
    return c.execute(text("select id from capability_profiles where project_id=:p and name=:n and id <> coalesce(:x, '')"),
                     {"p": project_id, "n": 名, "x": 除了}).scalar()


# ── 建档 ────────────────────────────────────────────────────────────────
@router.post(前缀 + "/capability-profiles", status_code=201)
async def 建能力档案(project_id: str, request: Request, me: 身份 = Depends(要权限("受理意见"))):
    """`{名字, 业务目标?, 输入?, 输出?, 适用角色?: [..], 负责人?, 已验证范围?, 依赖?: [{种类, 引用}], 下次验证事项?, 说明?}`。
    新档案在「配置中」。依赖只收同项目里现有的智能体 / 工作流 / Skill(按名字)/ 工具。
    ⚠️ 写权限**暂用「受理意见」**:PRD §10 每项能力由谁负责没拍。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验字段(体, 新建=True)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "能力档案的字段不合格", "见字段错误", field_errors=坏)
    cid = f"cp_{_uuid.uuid4().hex[:12]}"
    with 事务() as c:
        org = _项目组织(c, project_id)
        坏 = _核依赖(c, project_id, 出["dependencies"])
        if 坏:
            raise _错(422, "VALIDATION", "依赖里有这个项目找不到的东西", "只能引用同一个项目里现有的", field_errors=坏)
        if _重名(c, project_id, 出["name"]):
            raise _错(409, "DUPLICATE_NAME", f"这个项目里已经有一份叫「{出['name']}」的能力档案",
                      "换个名字,或者去改那一份", field_errors={"名字": "重名"})
        列 = list(出)
        参 = {"c_" + k: (_json.dumps(v, ensure_ascii=False) if k in 清单字段.values() else v) for k, v in 出.items()}
        值 = ", ".join(f"cast(:c_{k} as jsonb)" if k in 清单字段.values() else f":c_{k}" for k in 列)
        c.execute(text(f"""insert into capability_profiles (id, organization_id, project_id, created_at, created_by,
                               updated_at, revision, status, {", ".join(列)})
                           values (:i, :o, :p, now(), :u, now(), 1, '配置中', {值})"""),
                  {"i": cid, "o": org, "p": project_id, "u": me.user_id, **参})
        _记一步(c, org, project_id, me, cid, "新建", None, "配置中", 说明)
    return {"id": cid, "状态": "配置中", "revision": 1, "note": "建好了,在「配置中」。验过什么写进「已验证范围」,再「提交验证」"}


# ── 清单 ────────────────────────────────────────────────────────────────
@router.get(前缀 + "/capability-profiles")
def 能力档案清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            status: str = Query(None), limit: int = Query(30, ge=1, le=200), page: int = Query(1, ge=1)):
    """按状态筛;同一档里最近动过的在前。每行带关联问题单数和未解决数(已搁置算未解决,已重复不单独算)。"""
    if status and status not in F.状态们:
        raise _错(422, "VALIDATION", "筛选条件不合格", "见字段错误", field_errors={"status": f"只收 {list(F.状态们)}"})
    条件 = "x.project_id=:p and x.archived_at is null"
    参 = {"p": project_id, "lim": limit, "off": (page - 1) * limit}
    if status:
        条件 += " and x.status=:st"; 参["st"] = status
    with 连接() as c:
        rs = c.execute(text(f"""
            select count(*) over () 全量, x.*,
                   (select count(*) from issues i where i.project_id=x.project_id and i.capability_profile_id=x.id
                       and i.archived_at is null and i.status <> '已重复') 问题单数,
                   (select count(*) from issues i where i.project_id=x.project_id and i.capability_profile_id=x.id
                       and i.archived_at is null and i.status not in {F.sql_枚举(F.不算未解决的问题单状态)}) 未解决数
              from capability_profiles x where {条件}
             order by x.updated_at desc, x.id desc limit :lim offset :off"""), 参).mappings().all()
        汇总 = c.execute(text("""select status, count(*) n from capability_profiles where project_id=:p and archived_at is null
                                group by 1"""), {"p": project_id}).mappings().all()
    出 = [{"id": x["id"], "名字": x["name"], "状态": x["status"], "负责人": x["owner"],
          "适用角色": x["applicable_roles"] or [], "已验证范围": x["verified_scope_note"],
          "依赖数": len(x["dependencies"] or []), "关联问题单数": int(x["问题单数"]), "未解决问题单数": int(x["未解决数"]),
          "最近更新": _给人看(x["updated_at"]), "revision": x["revision"]} for x in rs]
    from workflows_api import 分页信封
    return {"items": 出, **分页信封(rs, page, limit), "汇总": [dict(x) for x in 汇总], "可选状态": list(F.状态们),
            "note": "**没有任何「智能度」分数** —— 每项能力验过什么,看「已验证范围」那句话(PRD §4.4)"}


# ── 详情:三样现查的数 ────────────────────────────────────────────────────
def _没有数据(为什么):
    return {"有数据": False, "显示": "没有数据", "为什么": 为什么}


def _评测与样本(c, project_id, 工作流们):
    """→ (评测结果, 样本数量)。只认后台派发记了 workflow_version 的评测(候选或基线是这些工作流的某一版)。"""
    if not 工作流们:
        原因 = "依赖里没有工作流 —— 评测现在只关联得到工作流版本(智能体 / Skill / 工具没有评测关联)"
        return _没有数据(原因), _没有数据(原因)
    rs = c.execute(text("""
        select e.id, e.status, e.executor_code, e.created_at, e.ended_at, e.dataset_version_id, e.scorer_version,
               e.candidate_ref, e.baseline_ref,
               v.workflow_id 候选工作流, b.workflow_id 基线工作流,
               (select count(*) from evaluation_items i where i.project_id=e.project_id and i.evaluation_id=e.id) 逐题结果数,
               (select case when jsonb_typeof(d.frozen_samples) = 'array' then jsonb_array_length(d.frozen_samples) end
                  from dataset_versions d where d.project_id=e.project_id and d.id=e.dataset_version_id) 题数
          from evaluations e
          left join workflow_versions v on v.project_id=e.project_id and e.candidate_ref->>'kind' = 'workflow_version'
                                       and v.id = e.candidate_ref->>'ref'
          left join workflow_versions b on b.project_id=e.project_id and e.baseline_ref->>'kind' = 'workflow_version'
                                       and b.id = e.baseline_ref->>'ref'
         where e.project_id=:p and e.archived_at is null
           and (v.workflow_id = any(:w) or b.workflow_id = any(:w))
         order by e.created_at desc, e.id desc limit 50"""), {"p": project_id, "w": list(工作流们)}).mappings().all()
    if not rs:
        原因 = "依赖里那几条工作流的版本还没被评测过(只认后台派发记了工作流版本的评测;外部登记的评测对不上是哪个工作流)"
        return _没有数据(原因), _没有数据(原因)
    评测 = []
    for r in rs:
        能 = r["status"] == "已完成" and bool(r["baseline_ref"]) and bool(r["dataset_version_id"]) and bool(r["scorer_version"])
        评测.append({"id": r["id"], "状态": r["status"], "执行方式": r["executor_code"],
                   "候选": (r["candidate_ref"] or {}).get("名") or (r["candidate_ref"] or {}).get("ref"),
                   "基线": (r["baseline_ref"] or {}).get("名") or (r["baseline_ref"] or {}).get("ref"),
                   "这项能力的工作流在哪一边": ("候选" if r["候选工作流"] in 工作流们 else "") +
                                         ("基线" if r["基线工作流"] in 工作流们 else ""),
                   "数据集版本": r["dataset_version_id"], "判据版本": r["scorer_version"],
                   "逐题结果数": int(r["逐题结果数"]), "能当结论吗": 能,
                   "建于": _给人看(r["created_at"]), "结束于": _给人看(r["ended_at"])})
    按版本 = {}
    for r in rs:
        k = r["dataset_version_id"]
        if k not in 按版本:
            按版本[k] = {"数据集版本": k, "题数": (int(r["题数"]) if r["题数"] is not None else None), "用在几次评测": 0}
        按版本[k]["用在几次评测"] += 1
    样本 = list(按版本.values())
    return ({"有数据": True, "评测": 评测, "说明": "只列评测本身(状态、能不能当结论);分数看评测中心,这里不另算"},
            {"有数据": True, "按数据集版本": 样本,
             "说明": "每个冻结数据集版本各有几题;**不跨版本加总**(两版之间可能有同一道题)。题数为空 = 那一版没存下题目清单"})


def _运行量(c, project_id, 工作流们, 智能体们):
    if not 工作流们 and not 智能体们:
        return _没有数据("依赖里没有工作流 / 智能体 —— Skill / 工具的调用不按它们记运行,查不到运行量")
    from monitoring_api import _维度   # 业务 / 调试 怎么分,只在监测那里写一份
    rs = c.execute(text(f"""
        select 种类, 依赖, 范围, count(*) n, min(created_at) 最早, max(created_at) 最近 from (
            select case r.kind when 'workflow' then '工作流' else '智能体' end 种类, r.definition_ref->>'id' 依赖,
                   r.created_at, {_维度}
              from execution_runs r
             where r.project_id=:p and ((r.kind='workflow' and r.definition_ref->>'id' = any(:w))
                                     or (r.kind='agent' and r.definition_ref->>'id' = any(:a)))) t
         group by 1, 2, 3 order by 1, 2, 3"""), {"p": project_id, "w": list(工作流们), "a": list(智能体们)}).mappings().all()
    if not rs:
        return _没有数据("依赖里的工作流 / 智能体还没有运行记录")
    按依赖 = {}
    for r in rs:
        k = (r["种类"], r["依赖"])
        d = 按依赖.setdefault(k, {"种类": r["种类"], "引用": r["依赖"], "业务": 0, "调试": 0, "最早": None, "最近": None})
        d[r["范围"]] = int(r["n"])
        d["最早"] = min(filter(None, [d["最早"], r["最早"]]))
        d["最近"] = max(filter(None, [d["最近"], r["最近"]]))
    出 = [{**d, "最早": _给人看(d["最早"]), "最近": _给人看(d["最近"])} for d in 按依赖.values()]
    return {"有数据": True, "按依赖": 出,
            "说明": ("全部历史,不限窗口(观察窗口 PRD §10 待定)。业务 / 调试按监测的口径分:业务 = 真跑且不是连接测试 / "
                     "样例预览 / 集成验证 / 评测、不是草稿试运行 / 单步测试。没跑过的依赖不列")}


def _能做的动作(状态):
    return [{"动作": a, "到": 到, "要写说明": a in F.要说明的动作, "要先写已验证范围": a in F.要先写验证范围的动作}
            for a, 到 in F.能做的动作(状态)]


@router.get(前缀 + "/capability-profiles/{cid}")
def 能力档案详情(project_id: str, cid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一份档案 + 依赖(现取名字和状态)+ 关联的问题单(未解决单独数)+ 评测结果 / 样本数量 / 实际运行量(现查,
    查不到写「没有数据」)+ 能做的动作 + 时间线。改字段 / 改状态要带的 revision 从这里拿。"""
    with 连接() as c:
        x = c.execute(text("select * from capability_profiles where project_id=:p and id=:i"),
                      {"p": project_id, "i": cid}).mappings().first()
        if not x:
            raise _错(404, "NOT_FOUND", "没有这份能力档案", "回清单重新进")
        依赖 = _读依赖(c, project_id, x["dependencies"])
        单们 = c.execute(text("""select id, title, status, root_cause_type, reopen_count, last_closed_at, updated_at
                                  from issues where project_id=:p and capability_profile_id=:i and archived_at is null
                                 order by (status in ('已验证关闭', '已重复')) asc, updated_at desc, id desc"""),
                        {"p": project_id, "i": cid}).mappings().all()
        线 = c.execute(text("""select created_at, created_by, action_code, from_status, to_status, note, change_snapshot
                                from capability_profile_events where project_id=:p and capability_profile_id=:i
                               order by created_at, id"""), {"p": project_id, "i": cid}).mappings().all()
        找得到 = [d for d in 依赖 if d["找得到"]]
        工作流们 = tuple(d["引用"] for d in 找得到 if d["种类"] == "工作流")
        智能体们 = tuple(d["引用"] for d in 找得到 if d["种类"] == "智能体")
        评测, 样本 = _评测与样本(c, project_id, 工作流们)
        运行 = _运行量(c, project_id, 工作流们, 智能体们)
    未解决 = [s for s in 单们 if s["status"] not in F.不算未解决的问题单状态]
    关闭的 = [s for s in 单们 if s["status"] == "已验证关闭" and s["last_closed_at"]]
    最近改进 = max(关闭的, key=lambda s: s["last_closed_at"]) if 关闭的 else None
    return {"id": x["id"], "名字": x["name"], "状态": x["status"], "业务目标": x["business_goal_note"],
            "输入": x["input_note"], "输出": x["output_note"], "适用角色": x["applicable_roles"] or [],
            "负责人": x["owner"], "已验证范围": x["verified_scope_note"], "下次验证事项": x["next_verification_note"],
            "依赖": 依赖, "可选依赖种类": list(F.依赖种类),
            "关联的问题单": [{"id": s["id"], "标题": s["title"], "状态": s["status"], "根因类别": s["root_cause_type"],
                         "重开次数": s["reopen_count"], "未解决": s["status"] not in F.不算未解决的问题单状态}
                        for s in 单们],
            "问题单数": {"关联": len([s for s in 单们 if s["status"] != "已重复"]), "未解决": len(未解决),
                      "已重复(不单独算)": len([s for s in 单们 if s["status"] == "已重复"]),
                      "口径": "未解决 = 不是「已验证关闭」的(已搁置也算未解决,PRD §5.2);已重复的指向主问题,不单独算"},
            "最近改进": ({"问题单": 最近改进["id"], "标题": 最近改进["title"], "关闭于": _给人看(最近改进["last_closed_at"])}
                     if 最近改进 else None),
            "评测结果": 评测, "样本数量": 样本, "实际运行量": 运行,
            "能做的动作": _能做的动作(x["status"]),
            "时间线": [{"时间": _给人看(e["created_at"]), "谁": e["created_by"], "动作": e["action_code"],
                      "从": e["from_status"], "到": e["to_status"], "说明": e["note"], "变化": e["change_snapshot"]}
                     for e in 线],
            "建档时间": _给人看(x["created_at"]), "最近更新": _给人看(x["updated_at"]), "revision": x["revision"],
            "note": ("评测结果 / 样本数量 / 实际运行量是现查的,查不到写「没有数据」(不是 0);"
                     "没有任何「智能度」分数(PRD §4.4);验证门槛 PRD §10 待定;写权限暂用「受理意见」")}


def _锁一份(c, project_id, cid, if_match):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把这份档案详情里的 revision 放进 If-Match 头")
    x = c.execute(text("select * from capability_profiles where project_id=:p and id=:i for update"),
                  {"p": project_id, "i": cid}).mappings().first()
    if not x:
        raise _错(404, "NOT_FOUND", "没有这份能力档案", "回清单重新进")
    if str(x["revision"]) != str(if_match).strip('"'):
        raise _错(409, "REVISION_CONFLICT", "这份档案刚被别人改过", "刷新看一眼最新的再改")
    return x


# ── 改字段 ──────────────────────────────────────────────────────────────
@router.patch(前缀 + "/capability-profiles/{cid}")
async def 改能力档案(project_id: str, cid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("受理意见"))):
    """只改给了的键,带 If-Match;每次在时间线记一行「改字段」,带前后值。状态不在这里改(走 /actions)。
    试点中 / 已启用 的档案不许把「已验证范围」清空。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验字段(体)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if not 出 and not 坏:
        坏["字段"] = f"一个能改的字段都没给 —— 能改的:{list(可改字段)}(状态走「改状态」)"
    if 坏:
        raise _错(422, "VALIDATION", "能力档案的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        x = _锁一份(c, project_id, cid, if_match)
        变化 = {中: [_给人看(x[列]), _给人看(出[列])] for 中, 列 in 可改字段.items() if 列 in 出 and x[列] != 出[列]}
        if not 变化:
            raise _错(422, "VALIDATION", "给的值和现在一样,没有要改的", "改了再保存", field_errors={"字段": "没有变化"})
        if "verified_scope_note" in 出 and not 出["verified_scope_note"] and x["status"] in ("试点中", "已启用"):
            raise _错(422, "VALIDATION", f"「{x['status']}」的能力不能清空已验证范围", "先改状态,或者写清现在验过什么",
                      field_errors={"已验证范围": "试点中 / 已启用 必须写"})
        if "dependencies" in 出:
            坏 = _核依赖(c, project_id, 出["dependencies"])
            if 坏:
                raise _错(422, "VALIDATION", "依赖里有这个项目找不到的东西", "只能引用同一个项目里现有的", field_errors=坏)
        if "name" in 出 and _重名(c, project_id, 出["name"], 除了=cid):
            raise _错(409, "DUPLICATE_NAME", f"这个项目里已经有一份叫「{出['name']}」的能力档案", "换个名字",
                      field_errors={"名字": "重名"})
        设 = ", ".join(f"{列}=cast(:c_{列} as jsonb)" if 列 in 清单字段.values() else f"{列}=:c_{列}" for 列 in 出)
        参 = {"c_" + k: (_json.dumps(v, ensure_ascii=False) if k in 清单字段.values() else v) for k, v in 出.items()}
        r = c.execute(text(f"""update capability_profiles set {设}, revision=revision+1, updated_at=now()
                                where project_id=:p and id=:i returning revision"""),
                      {"p": project_id, "i": cid, **参}).mappings().first()
        _记一步(c, x["organization_id"], project_id, me, cid, "改字段", x["status"], x["status"], 说明, 变化)
    return {"id": cid, "revision": r["revision"], "改了": list(变化)}


# ── 改状态 ──────────────────────────────────────────────────────────────
@router.post(前缀 + "/capability-profiles/{cid}/actions")
async def 能力档案一步(project_id: str, cid: str, request: Request,
                 if_match: str = Header(default=None, alias="If-Match"),
                 me: 身份 = Depends(要权限("受理意见"))):
    """`{动作, 说明}`,带 If-Match。流转照 capability_flow.流转,不在表里的 409;**说明必填**(改状态要说为什么);
    开始试点 / 启用 / 解除限制 之前「已验证范围」要写了一句(缺了 422)。每一步追加一行时间线。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    动作, 说明 = _字(体, "动作"), _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        raise _错(422, "VALIDATION", "说明太长", "写短一点", field_errors={"说明": f"最多 {说明最长} 字"})
    with 事务() as c:
        x = _锁一份(c, project_id, cid, if_match)
        能 = F.流转.get(x["status"], {})
        if 动作 not in 能:
            raise _错(409, "TRANSITION_NOT_ALLOWED", f"「{x['status']}」的能力不能「{动作}」",
                      f"这一步能做的:{list(能)}", field_errors={"动作": f"只收 {list(能)}"})
        坏 = {}
        if 动作 in F.要说明的动作 and not 说明:
            坏["说明"] = "改状态要写为什么"
        if 动作 in F.要先写验证范围的动作 and not x["verified_scope_note"]:
            坏["已验证范围"] = "先写清验过什么(例:「已验证单笔订单风险分析,批量巡检未验证」)再进这一步"
        if 坏:
            raise _错(422, "VALIDATION", f"「{动作}」缺东西", "见字段错误", field_errors=坏)
        到 = 能[动作]
        r = c.execute(text("""update capability_profiles set status=:t, revision=revision+1, updated_at=now()
                               where project_id=:p and id=:i returning revision"""),
                      {"t": 到, "p": project_id, "i": cid}).mappings().first()
        _记一步(c, x["organization_id"], project_id, me, cid, 动作, x["status"], 到, 说明)
    return {"id": cid, "从": x["status"], "到": 到, "revision": r["revision"], "note": "记在时间线上了"}


# ── 看板 ────────────────────────────────────────────────────────────────
@router.get(前缀 + "/capability-board")
def 改进看板(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """问题单按根因 / 能力 / 状态数:总数、未解决、观察期复发过、关闭后重开过。**只出数和分母,不出结论 / 排名 / 打分**。
    行按口径定义的顺序排,不按数量排;已重复的不计入(单独给数)。"""
    import issue_flow as IF
    with 连接() as c:
        rs = c.execute(text("""
            select i.status, i.root_cause_type, i.capability_profile_id, i.reopen_count,
                   exists(select 1 from issue_events e where e.project_id=i.project_id and e.issue_id=i.id
                            and e.action_code='观察期复发') 观察期复发过
              from issues i where i.project_id=:p and i.archived_at is null"""), {"p": project_id}).mappings().all()
        能力们 = c.execute(text("""select id, name, status from capability_profiles where project_id=:p and archived_at is null
                                  order by name, id"""), {"p": project_id}).mappings().all()
    重复 = [r for r in rs if r["status"] == "已重复"]
    计 = [r for r in rs if r["status"] != "已重复"]
    分母 = len(计)

    def 数(行们):
        return {"总数": len(行们), "未解决": sum(1 for r in 行们 if r["status"] not in IF.算已解决的状态),
                "观察期复发过": sum(1 for r in 行们 if r["观察期复发过"]),
                "关闭后重开过": sum(1 for r in 行们 if (r["reopen_count"] or 0) > 0), "分母": 分母}

    按根因 = [{"根因类别": k, **数([r for r in 计 if (r["root_cause_type"] or "未分类") == k])}
            for k in IF.根因类别们 + ("未分类",)]
    按能力 = [{"能力": {"id": a["id"], "名字": a["name"], "状态": a["status"]},
             **数([r for r in 计 if r["capability_profile_id"] == a["id"]])} for a in 能力们]
    按能力.append({"能力": None, "说明": "没关联能力的问题单", **数([r for r in 计 if not r["capability_profile_id"]])})
    按状态 = [{"状态": k, "总数": sum(1 for r in 计 if r["status"] == k), "分母": 分母}
            for k in IF.状态们 if k != "已重复"]
    return {"分母": 分母, "已重复(不计入)": len(重复), "按根因": 按根因, "按能力": 按能力, "按状态": 按状态,
            "口径": {"分母": "这个项目里没归档、不是「已重复」的问题单数(重复单指向主问题,算主问题那张)",
                    "未解决": "不是「已验证关闭」的(已搁置也算未解决,PRD §5.2)",
                    "观察期复发过": "时间线里出现过「观察期复发」的问题单数(复发几次都算一张)",
                    "关闭后重开过": "重开次数 > 0 的问题单数",
                    "排序": "按口径里定义的顺序(根因按 PRD §4.2 那 9 类,状态按流转顺序,能力按名字),**不按数量排**"},
            "note": ("只出数和分母,不出结论 / 排名 / 打分。PRD §4.4 的「按门店、按版本」这次没做 —— "
                     "问题单上没有门店 / 版本这两列;分组数不等于根因已证实(看问题单上的「根因核实」)")}
