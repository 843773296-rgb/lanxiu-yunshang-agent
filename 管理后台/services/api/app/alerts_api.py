# -*- coding: utf-8 -*-
"""告警:规则 / 站内待办 / 评估(DF-04 第二步,2026-11-04;Dify 对标 §8.1 / C16)。

判定在 alert_rules.下一步(纯函数,用户拍的判法);指标取 monitoring_api.算(和监测页同一份);这里只管落库和接口。
评估由 worker 每 60 秒扫一次(规则自己 5 分钟评一次),也能在页面上「立即评估」。
**先做站内待办**(方案原话),外部通知这一版不做 —— 不在页面上摆一个「发微信」却发不出去的开关。
"""
import datetime as _dt
import json as _json
import uuid as _uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import alert_rules as AR

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
评估间隔分钟 = 5
筛选键 = ("范围", "应用", "环境", "版本", "入口")
上下限 = {"窗口分钟": (5, 10080), "最小样本": (1, 100000), "连续越线才报": (1, 20), "连续正常才恢复": (1, 20), "去重分钟": (5, 10080)}


def _状态(r):
    return {"连续越线": r["breach_count"], "连续正常": r["normal_count"], "触发中": r["firing_since_at"] is not None,
            "上次提醒": r["last_notified_at"]}


def _规则(r):
    return {"方向": r["direction_code"], "阈值": float(r["threshold_value"]), "最小样本": r["min_sample_count"],
            "连续越线才报": r["trigger_count"], "连续正常才恢复": r["recover_count"], "去重分钟": r["dedupe_minutes"]}


def 评估一条(c, r, 现在=None):
    """评一次 → (动作, 为什么)。r = 已经 for update 锁住的规则行。**判定只调 AR.下一步**,这里不另写一份规则。"""
    import monitoring_api as MON
    现在 = 现在 or _dt.datetime.now(_dt.timezone.utc)
    筛 = r["filter_snapshot"] or {}
    if r["metric_code"] in AR.外部指标们:
        值, 样本 = _外部取值(r["metric_code"])
    else:
        监 = MON.算(c, r["project_id"], 范围=筛.get("范围") or "业务", 应用=筛.get("应用"), 环境=筛.get("环境"),
                   版本=筛.get("版本"), 入口=筛.get("入口"), 分钟=r["window_minutes"])
        值, 样本 = AR.取指标(监, r["metric_code"])
    新, 动, 因 = AR.下一步(_状态(r), 值, 样本, _规则(r), 现在)
    快 = {"值": 值, "样本": 样本, "窗口分钟": r["window_minutes"], "窗口止": 现在.isoformat(),
          "窗口起": (现在 - _dt.timedelta(minutes=r["window_minutes"])).isoformat(), "筛选": 筛, "结论": 因, "动作": 动}
    c.execute(text("""update alert_rules set breach_count=:b, normal_count=:n,
                          firing_since_at = case when :f then coalesce(firing_since_at, :t) else null end,
                          last_notified_at=:ln, last_evaluated_at=:t, last_eval_snapshot=cast(:s as jsonb)
                       where project_id=:p and id=:i"""),
              {"b": 新["连续越线"], "n": 新["连续正常"], "f": 新["触发中"], "t": 现在, "ln": 新["上次提醒"],
               "s": _json.dumps(快, ensure_ascii=False, default=str), "p": r["project_id"], "i": r["id"]})
    开着 = c.execute(text("""select id from alert_incidents where project_id=:p and alert_rule_id=:r and status='触发中'
                            order by created_at desc limit 1"""), {"p": r["project_id"], "r": r["id"]}).scalar()
    if 动 == "开待办" and not 开着:
        c.execute(text("""insert into alert_incidents (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                              alert_rule_id, status, eval_snapshot, reminded_count)
                          values (:i, :o, :p, :t, 'worker', :t, 1, :r, '触发中', cast(:s as jsonb), 0)"""),
                  {"i": f"ai_{_uuid.uuid4().hex[:12]}", "o": r["organization_id"], "p": r["project_id"], "t": 现在,
                   "r": r["id"], "s": _json.dumps(快, ensure_ascii=False, default=str)})
    elif 动 == "提醒" and 开着:
        c.execute(text("""update alert_incidents set reminded_count = coalesce(reminded_count, 0) + 1, updated_at=:t,
                              revision=revision+1 where project_id=:p and id=:i"""), {"t": 现在, "p": r["project_id"], "i": 开着})
    elif 动 == "恢复" and 开着:
        c.execute(text("""update alert_incidents set status='已恢复', recovered_at=:t, updated_at=:t, revision=revision+1
                           where project_id=:p and id=:i"""), {"t": 现在, "p": r["project_id"], "i": 开着})
    return 动, 因


def _外部取值(指标, 取=None):
    """→ (值, 样本)。门店月费用:聊天站 /internal/store-usage(同上线验收页那一路)。
    取不到 / 合计拿不到(有一笔金额未知)→ (None, 0):判定当「这一轮算不出、不算」,**不当 0**(当 0 会把触发中的告警误判成恢复)。"""
    if 指标 == "门店月费用":
        import acceptance_api as ACC
        体 = (取 or ACC._问门店用量)()
        if not isinstance(体, dict) or 体.get("error") or 体.get("合计") is None:
            return None, 0
        return float(体["合计"]), int(体.get("笔数") or 0)
    return None, 0


门店费用规则名 = "门店月费用到上限 80%(业务拍板第三十八条)"


def 种上门店费用规则(c, project_id):
    """澜绣项目(有门店入口的那个)种一条「门店月费用」规则,已有就不动 → 种了几条。
    阈值 = 上线验收页那个上限 × 0.8(acceptance_flow.月费用上限,单一来源);方向「高于」是严格大于,
    所以写 上限×0.8 − 0.0001:门店账金额按 4 位小数记,> 119.9999 等价于 ≥ 120,和聊天站费用闸「到 80% 就提醒」一致。
    连续 1 次就报 / 1 次正常就恢复(月初清零自然恢复,下个月还能再报);去重一天。"""
    import acceptance_flow as F
    if project_id not in F.种子项目:
        return 0
    有 = c.execute(text("select 1 from alert_rules where project_id=:p and metric_code='门店月费用' and archived_at is null"),
                  {"p": project_id}).first()
    if 有:
        return 0
    org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
    if not org:
        return 0
    c.execute(text("""insert into alert_rules (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                          name, filter_snapshot, metric_code, direction_code, threshold_value, window_minutes, min_sample_count,
                          trigger_count, recover_count, dedupe_minutes, owner, breach_count, normal_count)
                      values (:i, :o, :p, now(), 'system', now(), 1, :n, '{}'::jsonb, '门店月费用', '高于', :th, 1440, 1, 1, 1, 1440,
                              'system', 0, 0)"""),
              {"i": f"ar_{_uuid.uuid4().hex[:12]}", "o": org, "p": project_id, "n": 门店费用规则名,
               "th": Decimal(str(F.月费用上限)) * Decimal("0.8") - Decimal("0.0001")})
    return 1


def 扫告警(现在=None):
    """worker 每 60 秒调一次:到点(上次评估过了 评估间隔分钟)的、没暂停的规则各评一次。**一条评挂了不拖垮别的、也不拖垮 worker**。"""
    现在 = 现在 or _dt.datetime.now(_dt.timezone.utc)
    出 = []
    try:
        import acceptance_flow as F
        with 事务() as c:
            for p in F.种子项目:
                if 种上门店费用规则(c, p):
                    出.append(f"种上了「{门店费用规则名}」({p})")
    except Exception as e:
        出.append(f"⚠️ 种门店费用规则出错({type(e).__name__}: {e})—— 下一轮再试")
    with 连接() as c:
        ids = [(x["project_id"], x["id"]) for x in c.execute(text(f"""
            select project_id, id from alert_rules where archived_at is null and paused_at is null
               and (last_evaluated_at is null or last_evaluated_at <= :t - interval '{评估间隔分钟} minutes')"""),
            {"t": 现在}).mappings()]
    for p, i in ids:
        try:
            with 事务() as c:
                r = c.execute(text("select * from alert_rules where project_id=:p and id=:i for update"), {"p": p, "i": i}).mappings().first()
                动, 因 = 评估一条(c, r, 现在)
            if 动 != "不动":
                出.append(f"告警「{r['name']}」:{动} —— {因}")
        except Exception as e:
            出.append(f"⚠️ 告警规则 {i} 评估出错({type(e).__name__}: {e})—— 这一轮跳过,下一轮再评")
    return 出


def _整数(体, 键, 坏):
    lo, hi = 上下限[键]
    try:
        v = int(体.get(键))
    except (TypeError, ValueError):
        坏[键] = f"要整数({lo}–{hi})"
        return None
    if not (lo <= v <= hi):
        坏[键] = f"要在 {lo}–{hi} 之间"
    return v


@router.post(前缀 + "/alert-rules", status_code=201)
async def 建规则(project_id: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{名字, 筛选:{范围,应用,环境,版本,入口}, 指标, 方向, 阈值, 窗口分钟, 最小样本, 连续越线才报, 连续正常才恢复, 去重分钟, 负责人?}`。
    **每一项都要填**,不给默认值 —— 这些都是产品配置,系统替人填一个数等于把它伪装成标准。"""
    体 = await request.json()
    体 = 体 if isinstance(体, dict) else {}
    坏 = {}
    名 = str(体.get("名字") or "").strip()
    if not 名:
        坏["名字"] = "必填"
    if 体.get("指标") not in AR.指标们 and 体.get("指标") not in AR.外部指标们:
        坏["指标"] = f"只收 {list(AR.指标们) + list(AR.外部指标们)}"
    if 体.get("方向") not in AR.方向们:
        坏["方向"] = f"只收 {list(AR.方向们)}"
    try:
        阈 = Decimal(str(体.get("阈值")))
    except (InvalidOperation, ValueError):
        阈 = None
        坏["阈值"] = "要是数字"
    数 = {k: _整数(体, k, 坏) for k in 上下限}
    筛 = 体.get("筛选") if isinstance(体.get("筛选"), dict) else {}
    筛 = {k: 筛.get(k) for k in 筛选键 if 筛.get(k) not in (None, "")}
    if 筛.get("范围", "业务") not in ("业务", "调试", "全部"):
        坏["筛选"] = "范围只收 业务 / 调试 / 全部"
    if 坏:
        raise _错(422, "VALIDATION", "告警规则的字段不合格", "每一项都要填;阈值和次数是产品配置,没有系统默认值", field_errors=坏)
    负责人 = str(体.get("负责人") or me.user_id)
    rid = f"ar_{_uuid.uuid4().hex[:12]}"
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": project_id}).scalar()
        c.execute(text("""insert into alert_rules (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                              name, filter_snapshot, metric_code, direction_code, threshold_value, window_minutes, min_sample_count,
                              trigger_count, recover_count, dedupe_minutes, owner, breach_count, normal_count)
                          values (:i, :o, :p, now(), :u, now(), 1, :n, cast(:f as jsonb), :m, :d, :th, :w, :ms, :tc, :rc, :dm, :ow, 0, 0)"""),
                  {"i": rid, "o": org, "p": project_id, "u": me.user_id, "n": 名, "f": _json.dumps(筛, ensure_ascii=False),
                   "m": 体["指标"], "d": 体["方向"], "th": 阈, "w": 数["窗口分钟"], "ms": 数["最小样本"],
                   "tc": 数["连续越线才报"], "rc": 数["连续正常才恢复"], "dm": 数["去重分钟"], "ow": 负责人})
    return {"id": rid, "note": f"建好了;worker 每 {评估间隔分钟} 分钟评估一次,也可以点「立即评估」"}


def _规则样子(r):
    return {"id": r["id"], "名字": r["name"], "筛选": r["filter_snapshot"], "指标": r["metric_code"], "方向": r["direction_code"],
            "阈值": float(r["threshold_value"]), "窗口分钟": r["window_minutes"], "最小样本": r["min_sample_count"],
            "连续越线才报": r["trigger_count"], "连续正常才恢复": r["recover_count"], "去重分钟": r["dedupe_minutes"],
            "负责人": r["owner"], "暂停了吗": r["paused_at"] is not None, "触发中": r["firing_since_at"] is not None,
            "连续越线": r["breach_count"], "连续正常": r["normal_count"],
            "上次评估": r["last_evaluated_at"].isoformat() if r["last_evaluated_at"] else None,
            "上次评估结果": r["last_eval_snapshot"], "revision": r["revision"]}


@router.get(前缀 + "/alert-rules")
def 规则列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        rs = c.execute(text("select * from alert_rules where project_id=:p and archived_at is null order by created_at desc"),
                       {"p": project_id}).mappings().all()
    return {"items": [_规则样子(r) for r in rs], "评估间隔分钟": 评估间隔分钟,
            "note": "阈值 / 次数 / 窗口都是产品配置,不是行业标准;外部通知这一版不做,只开站内待办"}


@router.post(前缀 + "/alert-rules/{rule_id}/evaluate")
def 立即评估(project_id: str, rule_id: str, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """立刻评一次(不等 worker)。和 worker 走同一个 评估一条。"""
    with 事务() as c:
        r = c.execute(text("select * from alert_rules where project_id=:p and id=:i and archived_at is null for update"),
                      {"p": project_id, "i": rule_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条告警规则", "回告警列表重新进")
        动, 因 = 评估一条(c, r)
        r2 = c.execute(text("select * from alert_rules where project_id=:p and id=:i"), {"p": project_id, "i": rule_id}).mappings().first()
    return {"动作": 动, "为什么": 因, "规则": _规则样子(r2)}


@router.post(前缀 + "/alert-rules/{rule_id}/pause")
async def 暂停(project_id: str, rule_id: str, request: Request, if_match: str = Header(default=None, alias="If-Match"),
            me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{暂停: true|false}`。暂停 = 不评估;恢复评估时**连续次数清零**(暂停期间没评,接着数会把两段不相连的窗口当成连续)。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把规则列表里的 revision 放进 If-Match 头")
    体 = await request.json()
    停 = bool((体 or {}).get("暂停"))
    with 事务() as c:
        r = c.execute(text("select revision from alert_rules where project_id=:p and id=:i and archived_at is null for update"),
                      {"p": project_id, "i": rule_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条告警规则", "回告警列表重新进")
        if str(r["revision"]) != str(if_match).strip('"'):
            raise _错(409, "REVISION_CONFLICT", "这条规则刚被改过", "刷新再操作")
        c.execute(text(f"""update alert_rules set paused_at = {"now()" if 停 else "null"},
                               breach_count = case when :停 then breach_count else 0 end,
                               normal_count = case when :停 then normal_count else 0 end,
                               revision=revision+1, updated_at=now() where project_id=:p and id=:i"""),
                  {"停": 停, "p": project_id, "i": rule_id})
    return {"id": rule_id, "暂停了吗": 停}


@router.get(前缀 + "/alert-incidents")
def 告警待办(project_id: str, me: 身份 = Depends(要权限("查看有权配置")), status: str = Query(None),
         limit: int = Query(50, ge=1, le=200), page: int = Query(1, ge=1)):
    """站内待办:触发中的排前面。每条带开单那一窗的 值 / 样本 / 窗口起止 / 筛选 —— 页面据此跳到监测页下钻那一窗的运行。"""
    if status and status not in ("触发中", "已恢复", "已处理"):
        raise _错(422, "VALIDATION", "status 只收 触发中 / 已恢复 / 已处理", "不填就是全部", field_errors={"status": "只收三种"})
    with 连接() as c:
        rs = c.execute(text("""select count(*) over () 全量, i.*, r.name 规则名, r.owner 负责人, r.metric_code, r.direction_code,
                                      r.threshold_value from alert_incidents i
                                 join alert_rules r on r.project_id=i.project_id and r.id=i.alert_rule_id
                                where i.project_id=:p and (cast(:s as text) is null or i.status=:s)
                                order by (i.status='触发中') desc, i.created_at desc, i.id desc limit :lim offset :off"""),
                       {"p": project_id, "s": status, "lim": limit, "off": (page - 1) * limit}).mappings().all()
    from workflows_api import 分页信封
    return {"items": [{"id": x["id"], "规则": x["alert_rule_id"], "规则名": x["规则名"], "负责人": x["负责人"], "状态": x["status"],
                       "指标": x["metric_code"], "条件": f"{x['direction_code']} {float(x['threshold_value'])}",
                       "开单那一窗": x["eval_snapshot"], "又提醒了几次": x["reminded_count"] or 0,
                       "开单时间": x["created_at"].isoformat(),
                       "恢复时间": x["recovered_at"].isoformat() if x["recovered_at"] else None,
                       "处理人": x["handled_by"], "处理说明": x["note"], "revision": x["revision"]} for x in rs],
            **分页信封(rs, page, limit)}


@router.post(前缀 + "/alert-incidents/{incident_id}/handle")
async def 处理告警(project_id: str, incident_id: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{说明}` → 已处理。触发中的也能标(人已经处理了,不等它自己恢复);标过的不能再改。"""
    体 = await request.json()
    说 = str((体 or {}).get("说明") or "").strip()
    if len(说) < 2:
        raise _错(422, "VALIDATION", "要写一句怎么处理的", "比如「重启了澜绣写入服务」「阈值设太高,改规则」", field_errors={"说明": "必填"})
    with 事务() as c:
        x = c.execute(text("select status, alert_rule_id from alert_incidents where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": incident_id}).mappings().first()
        if not x:
            raise _错(404, "NOT_FOUND", "没有这条告警", "回告警列表重新进")
        if x["status"] == "已处理":
            raise _错(409, "ALREADY_HANDLED", "这条已经处理过了", "要补充就在规则上改,或者等它下一次触发")
        c.execute(text("""update alert_incidents set status='已处理', handled_by=:u, handled_at=now(), note=:n,
                              updated_at=now(), revision=revision+1 where project_id=:p and id=:i"""),
                  {"u": me.user_id, "n": 说, "p": project_id, "i": incident_id})
        # 规则的评估状态一起清零:不清的话规则停在「触发中」,之后再越线也不会开新单(只会等它恢复)——
        # 人标了已处理,而问题其实没好,就再也没人知道。清零之后还越线,连续够了就重新开一条
        c.execute(text("""update alert_rules set firing_since_at=null, breach_count=0, normal_count=0, updated_at=now(),
                              revision=revision+1 where project_id=:p and id=:r"""), {"p": project_id, "r": x["alert_rule_id"]})
    return {"id": incident_id, "状态": "已处理",
            "note": "规则的连续次数清零了:要是问题其实没好,连续越线够了会重新开一条"}
