#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澜绣控制面:V3 的 6 个旋钮 + 旋钮方案。

    GET   /lanxiu-knobs            有哪些旋钮(**连落点核对**)
    GET   /knob-plans              方案列表
    POST  /knob-plans              建方案
    GET   /knob-plans/{key}        方案详情(带导出状态)
    PATCH /knob-plans/{key}/draft  改方案

## 这一块为什么存在

2026-09-27 后台并进澜绣仓库时,搬家说明(`已搬走.md`)留了三条待办:

| 后台的这一页 | 该接澜绣的什么 |
|---|---|
| Prompt 管理 | `prompts.py` 的铁律 ✅ 10-02 做了 |
| **Agent 配置** | **`agent/knobs.py` 的 6 个旋钮** ← 这一块 |
| 知识管理 | `knowledge/` |

它写明了后果:
> **一个管理后台管着自己造的演示数据,和没有这个后台差别不大。**

## ⚠️ 这不是第二套 Agent 配置

搬家说明批评过的正是「**仓库里有了两套「调 agent」的东西**」。
所以这一块**不碰** `agent_versions` —— 后者是后台自己的 Agent 模型,
这 6 个旋钮管的是**澜绣 V3**(`agentsite/sdk.py`)怎么跑。
分组也单独叫「澜绣控制面」,不和「Workflow 与 Agent」挨着摆。

## ⚠️ 旋钮定义**现读**,后台不存第二份

`GET /lanxiu-knobs` 从 `agent/knobs.py` 的 `旋钮表` 现读。
存一份在后台的话,它会和代码漂 —— 而漂开时后台上会多出一个
**拖了什么都不会变的滑块**。`knobs.py` 自己的原话:

> 一个旋钮如果只存在于这张表和页面上,它就是个滑块 ——
> 拖动它什么都不会变,而人会以为自己在调。

所以这条接口**必须带上 `落点核对()` 的结果**:
它回答「这个旋钮是真的吗」。一个显示着 6 个旋钮却不说它们接没接上的后台,
本身就在制造那种假象。

## 单向,而且这一步不碰 V3 的运行代码

库是编辑面,文件(`.feynman/prompt_candidates/{号}.json`)仍然是
V3 真正读的那一份。两者靠 `tools/export_knob_plans.py` 单向同步
(库 → 文件),**而导出只改文件里的 `旋钮` 这一个键**:
后台只管旋钮那一半,整份覆盖会抹掉 `改`(提示词改动)和
`验证`(跑过的评测结果)—— 后者不可重建。

> **一个只管一半的编辑器,在保存时会把另一半清掉** ——
> 而那在「保存成功」那一刻看不出来。

业界这套叫「控制面 + pull + 本地兜底」(LaunchDarkly / Langfuse 那一类的
标准形态)。第二步才是让 V3 从后台拉,**而那一步要改澜绣的运行代码**。
"""
import hashlib
import json as _json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))
# 仓库根 —— 为了 import 澜绣的 `agent/knobs.py`。
#
# ⚠️ **向上找到那个文件为止,不数层数。**
# 第一版我数 `dirname` 的层数,少数了一层(这个文件在
# `管理后台/services/api/app/`,到仓库根要五层),
# 于是接口报 `No module named 'agent'`。
# 数层数在文件被挪动时会错,**而错的时候报的是「找不到模块」** ——
# 看起来像依赖没装。这个仓库在同一个形状上栽过:
# 交接门禁那个 hook「第一版往上只走 4 层,没找到」。
def _找仓库根():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(12):
        if os.path.isfile(os.path.join(d, "agent", "knobs.py")):
            return d
        上 = os.path.dirname(d)
        if 上 == d:
            break
        d = 上
    return None


_仓 = _找仓库根()
if _仓 and _仓 not in sys.path:
    sys.path.insert(0, _仓)

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# ⚠️ **方案文件的目录从 `knobs.py` 拿,不在这里拼一遍。**
# 拼一遍的话,哪天那边改了目录,后台会读写一个**没人看的空目录** ——
# 而「读到 0 个方案」和「真的没有方案」长得一模一样。


def _旋钮模块():
    """import 澜绣的 `agent/knobs.py`。**拿不到就当场报,不给空表。**

    给空表的坏处:页面会显示「没有旋钮」,而真相是「后台读不到澜绣的代码」——
    那两件事下一步完全不同(一个是业务状态,一个是部署问题)。
    """
    if not _仓:
        raise _错(500, "LANXIU_KNOBS_UNREADABLE",
                 "向上找不到含 `agent/knobs.py` 的目录",
                 "后台在澜绣仓库里是 subtree(`管理后台/`)—— "
                 "**这是部署问题,不是「没有旋钮」**")
    try:
        from agent import knobs as K
        return K
    except Exception as e:
        raise _错(500, "LANXIU_KNOBS_UNREADABLE",
                 f"读不到 `agent/knobs.py`:{e}",
                 "后台要能看到澜绣的仓库根 —— 它们在同一个仓库里,"
                 "`管理后台/` 是 subtree。**不是「没有旋钮」,是读不到。**")


@router.get(前缀 + "/lanxiu-knobs")
def 旋钮定义(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """有哪些旋钮、取值、默认值,**以及它们真的接上了吗**。"""
    K = _旋钮模块()
    坏 = K.落点核对()
    return {
        "items": [{
            "名": k["名"], "中文": k["中文"], "类型": k["类型"],
            "取值": k["取值"], "默认": k["默认"],
            # ⚠️ `落点` 要给出来 —— 它是「这个旋钮接在哪一行代码上」。
            # 不给的话,人没法自己核对,只能信后台那句「核对过了」。
            "落点": k["落点"], "说明": k["说明"],
            "松": bool(k.get("松")),
        } for k in K.旋钮表],
        "默认值": K.默认(),
        # ⚠️⚠️ **这一栏是这条接口的要点。**
        "落点核对": {"过了吗": not 坏, "问题": 坏},
        "⚠️落点核对是什么": (
            "它验「每个旋钮声明的落点,在那个文件里真的搜得到那个名字」。"
            "**不过就说明那个旋钮可能是个滑块** —— "
            "拖动它什么都不会变,而人会以为自己在调。"
            "这一栏不过的时候,**界面上要把那几个旋钮标成不可信**,"
            "不能照常显示成可调"),
        "⚠️定义是现读的": (
            "定义来自 `agent/knobs.py` 的 `旋钮表`,后台**不存第二份** —— "
            "存一份会和代码漂,而漂开时页面上会多出一个假滑块"),
        "note": ("这 6 个旋钮管的是**澜绣 V3**(`agentsite/sdk.py`)怎么跑,"
                 "**不是后台自己的 Agent 配置** —— 后者在「Workflow 与 Agent」那组。"
                 "两件事混起来就是搬家说明批评的「两套调 agent 的东西」"),
    }


def _校验旋钮(K, 旋, 可用工具=None):
    """返回 (干净的旋钮, 人话说明)。**认不出的名字当场拒。**"""
    if not isinstance(旋, dict):
        raise _错(422, "VALIDATION_FAILED", "`旋钮` 要是个对象",
                 "形如 {\"effort\": \"high\"}")
    认得的 = {k["名"] for k in K.旋钮表}
    野 = sorted(set(旋) - 认得的)
    if 野:
        # ⚠️ **认不出的旋钮名要当场拒,不能存下来。**
        # 存下来的话它会安静地待在方案里什么都不做 ——
        # 而人以为自己调了一个旋钮。
        raise _错(422, "VALIDATION_FAILED",
                 f"认不出这些旋钮名:{野}",
                 f"认得的只有 {sorted(认得的)} —— "
                 f"**一个认不出的旋钮名存下来也不会生效**,"
                 f"而方案上看起来它在那儿",
                 field_errors={"旋钮": 野})
    try:
        干净, 松, 话 = K.校验(旋, 可用工具)
    except Exception as e:
        raise _错(422, "VALIDATION_FAILED", f"旋钮值不合法:{e}",
                 "看 `GET /lanxiu-knobs` 的 `取值`")
    return 干净, 话


def _方案出参(r, K):
    """一行 → 返回体。带**导出状态**。"""
    号 = r["key"]
    文件 = os.path.join(K.目录, f"{号}.json")
    在吗 = os.path.exists(文件)
    现哈 = None
    if 在吗:
        现哈 = "sha256:" + hashlib.sha256(
            open(文件, "rb").read()).hexdigest()
    出 = {
        "方案号": 号, "id": r["id"],
        "旋钮": dict(r["params"] or {}),
        "为什么": r.get("change_note"),
        "负责人": r.get("owner"), "状态": r.get("status"),
        "draft_revision": r.get("draft_revision") or 0,
        "导出过吗": bool(r.get("exported_at")),
        "导出时间": (r["exported_at"].isoformat()
                 if r.get("exported_at") else None),
        "方案文件在吗": 在吗,
    }
    # ⚠️ **「导出过」不等于「文件还是那一份」。**
    # 文件可以被人手改(它就在仓库里,而且 V3 真读的是它)。
    # 不比一下的话,后台显示的和 V3 真读到的可能不是一回事 ——
    # 而那种不一致**不报错**。
    if r.get("file_hash") and 现哈:
        一样 = (r["file_hash"] == 现哈)
        出["文件还是导出那一份吗"] = 一样
        if not 一样:
            出["⚠️文件被改过"] = (
                "方案文件的哈希和导出那一刻不一样 —— **有人手改过它**。"
                "V3 真读的是文件,所以现在后台显示的和它实际在用的"
                "**不是一回事**。要么重新导出(覆盖手改),"
                "要么把手改的内容先搬回后台")
    elif r.get("exported_at") and not 在吗:
        出["⚠️文件不见了"] = ("导出过,而方案文件现在**不在了** —— "
                        "V3 跑那个方案号会直接报错(`knobs.读()` 不退回源头)")
    return 出


@router.get(前缀 + "/knob-plans")
def 方案列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    K = _旋钮模块()
    with 连接() as c:
        行 = c.execute(text("""select * from knob_plans
                             where project_id=:p and archived_at is null
                             order by updated_at desc"""),
                      {"p": project_id}).mappings().all()
    return {
        "items": [_方案出参(dict(r), K) for r in 行],
        # ⚠️ 总数**不给 0 当未知**(规格:未知显示「未知」,不显示零)。
        "total": len(行),
        "note": ("方案是**单向**同步到文件的:库是编辑面,"
                 "而 V3 真读的是 `.feynman/prompt_candidates/{号}.json`。"
                 "改完要跑 `python3 tools/export_knob_plans.py` 才生效"),
    }


@router.post(前缀 + "/knob-plans", status_code=201)
async def 建方案(project_id: str, request: Request,
             me: 身份 = Depends(要权限("改筛选策略"))):
    K = _旋钮模块()
    体 = await request.json()
    号 = (体.get("方案号") or 体.get("key") or "").strip()
    if not 号:
        raise _错(422, "VALIDATION_FAILED", "没给方案号",
                 "方案号就是文件名(`.feynman/prompt_candidates/{号}.json`)",
                 field_errors={"方案号": ["必填"]})
    # ⚠️ 方案号会变成**文件名** —— 不许带路径分隔符或 `..`。
    # 不挡的话,一个 `../../x` 能让导出写到仓库外面去。
    if "/" in 号 or "\\" in 号 or 号.startswith(".") or ".." in 号:
        raise _错(422, "VALIDATION_FAILED",
                 f"方案号不能带路径(拿到 {号!r})",
                 "它会变成文件名 —— **带路径的名字能让导出写到别处去**",
                 field_errors={"方案号": ["不许带 / \\ 或 .."]})
    为什么 = (体.get("为什么") or 体.get("change_note") or "").strip()
    if not 为什么:
        # ⚠️ 这不是形式要求。方案文件里那个 `为什么` 字段是**下一个人
        # 判断「这个实验还要不要留着」的唯一线索** —— 现有两个方案都写了。
        raise _错(422, "VALIDATION_FAILED", "没写「为什么」",
                 "一个没说清为什么的方案,下次没人知道它还要不要留着",
                 field_errors={"为什么": ["必填"]})
    干净, 话 = _校验旋钮(K, 体.get("旋钮") or {})
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        if not org:
            raise _错(404, "NOT_FOUND", f"没有项目 {project_id}", "换一个项目")
        有 = c.execute(text("""select 1 from knob_plans
                             where project_id=:p and key=:k"""),
                      {"p": project_id, "k": 号}).first()
        if 有:
            raise _错(409, "ALREADY_EXISTS", f"方案号 {号} 已经有了",
                     "换个号,或者改那个方案的草稿")
        pid = f"kp_{号}"
        c.execute(text("""insert into knob_plans
            (id, organization_id, project_id, key, params, owner, status,
             change_note, draft_revision, created_at, created_by,
             updated_at, revision)
            values (:i,:o,:p,:k, cast(:pa as jsonb), :ow, 'draft', :cn, 1,
                    now(), :by, now(), 1)"""),
                  {"i": pid, "o": org, "p": project_id, "k": 号,
                   "pa": _json.dumps(干净, ensure_ascii=False),
                   "ow": me.user_id, "cn": 为什么, "by": me.user_id})
    return {"方案号": 号, "id": pid, "旋钮": 干净, "校验说明": 话,
            "note": "**还没生效** —— 跑 `python3 tools/export_knob_plans.py` "
                    "才会写进方案文件,而 V3 读的是文件"}


@router.get(前缀 + "/knob-plans/{key}")
def 方案详情(project_id: str, key: str,
         me: 身份 = Depends(要权限("查看有权配置"))):
    K = _旋钮模块()
    with 连接() as c:
        r = c.execute(text("""select * from knob_plans
                             where project_id=:p and key=:k"""),
                      {"p": project_id, "k": key}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", f"没有方案 {key}", "回方案列表看有哪些")
    出 = _方案出参(dict(r), K)
    出["note"] = ("**改草稿的 `If-Match` 认 `draft_revision`**。"
                  "改完要导出才生效 —— 库是编辑面,V3 读的是文件")
    return 出


@router.patch(前缀 + "/knob-plans/{key}/draft")
async def 改方案(project_id: str, key: str, request: Request,
             me: 身份 = Depends(要权限("改筛选策略"))):
    K = _旋钮模块()
    体 = await request.json()
    头 = request.headers.get("If-Match")
    if not 头:
        # ⚠️ **409,不是 428。** 428 Precondition Required 语义更准,
        # 而这个仓库的契约里**没有 428**(`deps._错` 当场抛
        # 「用了契约外的状态码」),而且 If-Match 缺失在另外四个模块里
        # 一律是 409 IF_MATCH_REQUIRED。
        # > 语义更准的那个码,如果不在契约里,
        # > 它就是**第五种和现有四处不一致的写法**。
        raise _错(409, "IF_MATCH_REQUIRED", "改方案要带 If-Match",
                 "把方案详情里的 `draft_revision` 放进 If-Match 头")
    with 事务() as c:
        r = c.execute(text("""select * from knob_plans
                             where project_id=:p and key=:k"""),
                      {"p": project_id, "k": key}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", f"没有方案 {key}", "回方案列表看有哪些")
        现 = r.get("draft_revision") or 0
        if str(现) != str(头).strip('"'):
            raise _错(409, "REVISION_CONFLICT",
                     f"这份草稿已经被改过(现在是 {现},你带的是 {头})",
                     "重新读一遍详情,拿新的 draft_revision 再提交")
        新旋 = 体.get("旋钮")
        改了 = {}
        if 新旋 is not None:
            干净, _话 = _校验旋钮(K, 新旋)
            改了["params"] = _json.dumps(干净, ensure_ascii=False)
        if (体.get("为什么") or 体.get("change_note")):
            改了["change_note"] = (体.get("为什么")
                                or 体.get("change_note")).strip()
        if not 改了:
            raise _错(422, "VALIDATION_FAILED", "没给要改的东西",
                     "能改的是 `旋钮` 和 `为什么`")
        套 = ", ".join(f"{k}=cast(:{k} as jsonb)" if k == "params"
                      else f"{k}=:{k}" for k in 改了)
        # ⚠️ **改了旋钮就把导出状态清掉。**
        # 不清的话,详情上会显示「导出过」而库里的值已经和文件不一样了 ——
        # 于是人以为改动已经生效,**而 V3 读的还是旧的那份**。
        c.execute(text(f"""update knob_plans
            set {套}, exported_at=null, file_hash=null,
                draft_revision=coalesce(draft_revision,0)+1,
                updated_at=now(), revision=coalesce(revision,0)+1
            where project_id=:p and key=:k"""),
                  {**改了, "p": project_id, "k": key})
        新r = c.execute(text("""select * from knob_plans
                              where project_id=:p and key=:k"""),
                       {"p": project_id, "k": key}).mappings().first()
    出 = _方案出参(dict(新r), K)
    出["note"] = ("改了之后**导出状态被清掉了** —— 这是有意的:"
                  "不清的话详情会显示「导出过」而库里的值已经和文件不一样,"
                  "于是人以为改动生效了,**而 V3 读的还是旧的那份**。"
                  "跑 `python3 tools/export_knob_plans.py` 才生效")
    return 出
