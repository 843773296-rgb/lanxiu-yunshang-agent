# -*- coding: utf-8 -*-
"""意见单(DF-03 第 2 步,2026-11-04)。口径照《意见收集与能力持续改进 PRD》(10-24)§3 / §5.1 / §7.1;Dify 对标 C13。

## 为什么另起一张表,不往 feedback(A3)里塞

`feedback` 记的是**人对智能体结论的处置**(采纳 / 改判 / 升级 / 作废),口径是采纳率;
这里记的是**用的人提的意见**(有帮助 / 有问题 + 哪里有问题 + 期望的结果),后面要走受理、核实、关联问题单。
PRD §7.1 写明:「保留现有 feedback 的人工判读含义……不把新增功能建议强行记成作废」。
两件事的分母也不同:塞进同一张表,`智能体健康` 那页的采纳率会被意见撑大。

## 身份:记的是提问的那个人,不是服务账号

聊天站转来时带两道:
  ① `X-Dev-User`(服务账号,和执行记录推送同一套)—— 过 `要权限("运行评测")`,契约里点得出权限;
  ② `X-Lanxiu-Internal`(本机凭证文件,和访问 API 聊天那条通道同一份)+ 只收本机 ——
     **请求体里的「提问人」只在这道过了才采信**。只有服务账号、没有凭证的,一律拒:
     否则任何拿着服务账号的人都能以任意工号提意见。
提问人本人**不需要管理后台的任何权限**(PRD §1:「普通业务用户……不能为了收意见放开运行评测权限」)——
他是谁、这一轮是不是他问的,由聊天站从**登录会话**核对(agentsite/answer_feedback.py)。

## 挂在哪一轮上

存聊天站那一轮的号(chat_trace_ref)。管理后台那条调用记录按 `request_id = lanxiu-chat:<号>` **读的时候现对** ——
执行记录推送是轮末成批推的,意见常常比它先到;存一列「写入那一刻对不上就空着」的 trace_id,它会一直空下去。

## 不存原文

问题和回答的正文在调用记录里,谁看得到由「查看敏感输入」那条授权管。抄一份进意见单就绕过了那道授权。

## 还没做(PRD 第一阶段的另一半)

独立建议的入口(不挂任何一轮,要靠提交幂等键防重)、「我的意见」进度页、受理台。表里 source / status 的取值已按 PRD 留好,
这个口现在只收「问答」和「执行失败」两种来源。
"""
import hmac
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

# 下面几组和 models._额外检查 里的 CHECK 是同一份意思;问题类型还和聊天站、聊天页各有一份(answer_feedback_check ⑥ 盯着)
这个口收的来源 = ("问答", "执行失败")       # 「独立建议」库里留了位,入口还没做
评价们 = ("有帮助", "有问题")
问题类型们 = ("答错", "没答全", "证据不支持", "查错对象", "太慢或失败", "不好操作", "新增能力", "其他")
影响们 = ("仅影响本次", "反复出现", "影响业务办理")
状态们 = ("待受理", "待补充", "核实中", "已关联问题", "已答复", "不采纳", "已撤回")
本机 = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
聊天站来源 = "lanxiu-chat"     # 和 runs_api 导入执行记录时写的 request_id 前缀同一个
说明最长 = 1000


def 内部通道核对(头值, 对端, 读凭证=None):
    """→ (行不行, 为什么)。三种拒法分开说:通道没开 / 不是本机 / 凭证不对。"""
    if 读凭证 is None:
        from open_api import _内部凭证 as 读凭证
    真 = 读凭证()
    if not 真:
        return False, "内部通道没开(本机没有凭证文件)—— 提问人是谁没法采信,不退回成「信请求体」"
    if (对端 or "") not in 本机:
        return False, f"只收本机来的内部调用(对端是 {对端})"
    if not 头值 or not hmac.compare_digest(str(头值).encode(), 真.encode()):
        return False, "内部凭证不对"
    return True, ""


def _字(体, k):
    v = 体.get(k)
    return (str(v).strip() or None) if v is not None else None


def 校验(体):
    """→ (干净的字段, 坏字段)。纯函数。"""
    坏, 出 = {}, {}
    出["来源"] = _字(体, "来源") or "问答"
    if 出["来源"] not in 这个口收的来源:
        坏["来源"] = (f"这个口只收 {list(这个口收的来源)}" +
                    (" —— 独立建议的入口还没做(要带提交幂等键防重)" if 出["来源"] == "独立建议" else ""))
    出["聊天站trace"] = _字(体, "聊天站trace")
    if not 出["聊天站trace"] or len(出["聊天站trace"]) > 200:
        坏["聊天站trace"] = "要给聊天站那一轮的 trace 号 —— 挂不上哪一轮的意见,受理人不知道说的是哪句"
    出["会话号"] = _字(体, "会话号")
    出["评价"] = _字(体, "评价")
    if 出["评价"] not in 评价们:
        坏["评价"] = f"只收 {list(评价们)}"
    if 出["来源"] == "执行失败" and 出["评价"] == "有帮助":
        坏["评价"] = "执行失败的那一轮只能报问题"
    类 = _字(体, "问题类型")
    出["说明"] = _字(体, "说明")
    出["期望结果"] = _字(体, "期望结果")
    出["影响"] = _字(体, "影响")
    if 出["评价"] == "有问题":
        if 类 not in 问题类型们:
            坏["问题类型"] = f"「有问题」要说是哪一类:{list(问题类型们)} —— 不分类的问题受理人筛不出来"
        if not 出["说明"]:
            坏["说明"] = "要写一句哪里有问题 —— 只有「错了」两个字,受理人只能回头再问你"
        if 出["影响"] and 出["影响"] not in 影响们:
            坏["影响"] = f"只收 {list(影响们)}"
    elif 出["评价"] == "有帮助":
        if 类:
            坏["问题类型"] = "「有帮助」不带问题类型"
        if 出["期望结果"] or 出["影响"]:
            坏["期望结果"] = "「有帮助」不带期望结果 / 影响(原因写在说明里就行,可以不写)"
    for k in ("说明", "期望结果"):
        if 出[k] and len(出[k]) > 说明最长:
            坏[k] = f"最多 {说明最长} 字"
    出["问题类型"] = 类 if 出["评价"] == "有问题" else None
    人 = 体.get("提问人") if isinstance(体.get("提问人"), dict) else {}
    出["工号"] = str(人.get("工号") or "").strip()
    if not 出["工号"]:
        坏["提问人"] = "要给提问人的澜绣工号 —— 由聊天站从登录会话换出来,不是服务账号"
    出["快照"] = {k: 人.get(k) for k in ("工号", "姓名", "角色", "门店")}
    return 出, 坏


@router.post(前缀 + "/opinions", status_code=201)
async def 提交意见(project_id: str, request: Request, me: 身份 = Depends(要权限("运行评测"))):
    """聊天站转来一条意见。一个人对一轮只一条:再提 = 改那一条(旧版留在 history_snapshot);**受理之后不许再改**。

    入参:`{来源: 问答|执行失败, 聊天站trace, 会话号?, 评价: 有帮助|有问题, 问题类型?, 说明?, 期望结果?, 影响?,
           提问人: {工号, 姓名, 角色, 门店}}`
    """
    行, 因 = 内部通道核对(request.headers.get("X-Lanxiu-Internal"), request.client.host if request.client else None)
    if not 行:
        raise _错(403, "INTERNAL_ONLY", 因, "这个口只收聊天站转来的 —— 提问人是谁要由聊天站从登录会话换出来")
    try:
        体 = await request.json()
    except Exception:
        体 = None
    if not isinstance(体, dict):
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验(体)
    if 坏:
        raise _错(422, "VALIDATION", "意见的字段不合格", "见字段错误", field_errors=坏)

    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
        if not org:
            raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
        # 一句完成「没有就建 / 有且待受理就改(旧版追加进 history_snapshot)/ 受理了就不动」——
        # 先查再写的两步在并发提交时会撞唯一键
        r = c.execute(text("""
            insert into opinions (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                   source, chat_trace_ref, session_ref, verdict, problem_type, note, expected_note, impact_type,
                   asker_staff_code, asker_snapshot, status, history_snapshot)
            values (:i, :o, :p, now(), :u, now(), 1, :src, :tr, :ss, :v, :pt, :n, :ex, :im, :sc,
                    cast(:snap as jsonb), '待受理', '[]'::jsonb)
            on conflict (project_id, chat_trace_ref, asker_staff_code) do update
               set source = excluded.source, verdict = excluded.verdict, problem_type = excluded.problem_type,
                   note = excluded.note, expected_note = excluded.expected_note, impact_type = excluded.impact_type,
                   session_ref = coalesce(excluded.session_ref, opinions.session_ref),
                   asker_snapshot = excluded.asker_snapshot,
                   history_snapshot = coalesce(opinions.history_snapshot, '[]'::jsonb) || jsonb_build_array(jsonb_build_object(
                       'revision', opinions.revision, '来源', opinions.source, '评价', opinions.verdict,
                       '问题类型', opinions.problem_type, '说明', opinions.note, '期望结果', opinions.expected_note,
                       '影响', opinions.impact_type, '改之前的时间', opinions.updated_at)),
                   updated_at = now(), revision = opinions.revision + 1
             where opinions.status = '待受理'
            returning id, revision, (xmax = 0) as 新建"""),
            {"i": f"op_{_uuid.uuid4().hex[:12]}", "o": org, "p": project_id, "u": me.user_id,
             "src": 出["来源"], "tr": 出["聊天站trace"], "ss": 出["会话号"], "v": 出["评价"], "pt": 出["问题类型"],
             "n": 出["说明"], "ex": 出["期望结果"], "im": 出["影响"], "sc": 出["工号"],
             "snap": _json.dumps(出["快照"], ensure_ascii=False)}).mappings().first()
        if not r:
            老 = c.execute(text("""select id, status from opinions
                                  where project_id=:p and chat_trace_ref=:tr and asker_staff_code=:sc"""),
                           {"p": project_id, "tr": 出["聊天站trace"], "sc": 出["工号"]}).mappings().first()
            raise _错(409, "ALREADY_ACCEPTED", f"这条意见已经进了「{(老 or {}).get('status')}」,不能再改",
                      "受理人看的是你当时那句话 —— 改了的话他看的和库里的就不是同一句了;有补充请另外说明")
        后台trace = c.execute(text("select id from traces where project_id=:p and request_id=:r limit 1"),
                            {"p": project_id, "r": f"{聊天站来源}:{出['聊天站trace']}"}).scalar()
    return {"id": r["id"], "新建": bool(r["新建"]), "revision": r["revision"], "状态": "待受理",
            "评价": 出["评价"], "问题类型": 出["问题类型"], "管理后台trace": 后台trace,
            "note": ("收到了,进了管理后台「意见」待受理。期望的结果是**候选**,核实过才会变成评测样本;"
                     "**不会自动改线上答案**"
                     + ("" if 后台trace else "。这一轮的执行记录还没推过来,推过来之后清单里会自动对上"))}


@router.get(前缀 + "/opinions")
def 意见清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
         status: str = Query(None), verdict: str = Query(None),
         limit: int = Query(30, ge=1, le=200), page: int = Query(1, ge=1)):
    """受理台的清单:待受理的排前面,同状态里新的在前。每条带管理后台那条调用记录(读的时候现对)。"""
    坏 = {}
    if status and status not in 状态们:
        坏["status"] = f"只收 {list(状态们)}"
    if verdict and verdict not in 评价们:
        坏["verdict"] = f"只收 {list(评价们)}"
    if 坏:
        raise _错(422, "VALIDATION", "筛选条件不合格", "见字段错误", field_errors=坏)
    条件 = "f.project_id=:p and f.archived_at is null"
    参 = {"p": project_id, "lim": limit, "off": (page - 1) * limit}
    if status:
        条件 += " and f.status=:st"; 参["st"] = status
    if verdict:
        条件 += " and f.verdict=:v"; 参["v"] = verdict
    with 连接() as c:
        rs = c.execute(text(f"""
            with 这页 as (
                select count(*) over () 全量, f.* from opinions f where {条件}
                 order by (f.status = '待受理') desc, f.created_at desc, f.id desc
                 limit :lim offset :off)
            select 这页.*, (select t.id from traces t where t.project_id=这页.project_id
                              and t.request_id = '{聊天站来源}:' || 这页.chat_trace_ref limit 1) 后台trace
              from 这页 order by (这页.status = '待受理') desc, 这页.created_at desc, 这页.id desc"""), 参).mappings().all()
        汇总 = c.execute(text("""select status, verdict, count(*) n from opinions
                                where project_id=:p and archived_at is null group by 1, 2"""),
                         {"p": project_id}).mappings().all()
    出 = [{"id": x["id"], "来源": x["source"], "评价": x["verdict"], "问题类型": x["problem_type"], "说明": x["note"],
          "期望结果": x["expected_note"], "影响": x["impact_type"],
          "提问人": x["asker_snapshot"] or {"工号": x["asker_staff_code"]}, "状态": x["status"],
          "聊天站trace": x["chat_trace_ref"], "会话号": x["session_ref"], "管理后台trace": x["后台trace"],
          "改过几次": len(x["history_snapshot"] or []), "升成的样本": x["promoted_sample_id"],
          "提交时间": x["created_at"].isoformat(), "revision": x["revision"]} for x in rs]
    from workflows_api import 分页信封
    return {"items": 出, **分页信封(rs, page, limit),
            "汇总": [dict(x) for x in 汇总],
            "note": ("「有帮助」是提问人自己的感受,**不是准确率**(PRD §8:没人反馈不等于答对);"
                     "期望的结果是候选事实,核实过才升成评测样本")}
