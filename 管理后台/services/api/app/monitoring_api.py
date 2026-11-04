# -*- coding: utf-8 -*-
"""监测(Dify 对标方案 §8.1 / DF-04,2026-11-04;验收 C15)。

## 口径(用户 11-04 拍的那一条在最前面)

- **办成 = 跑完 + 每一处写入都拿到澜绣「已执行」的回执**(用户拍)。跑完了但写入没回执 → 「跑完·没证实」;
  这次本来就不需要写入(只出结果 / 分支走了不写的那一路)→ 「跑完·这次不需要写入」,**单列,不混进办成率**。
  写入回执来自 bridge_calls(走到写入那一步才建一行,澜绣执行完回执 已执行)。
- **业务和调试分开**,默认只看业务:业务 = 真跑(execution_mode=live)且不是连接测试 / 样例预览 / 集成验证。
  否则会把本地调试的成绩呈现成线上成绩(方案原话:「不能直接将当前本地五次调试结果呈现为线上成功率」)。
- **终态率只对已终结的算**:等人核对、等澜绣执行、在跑的,不算失败也不算成功,单列。
- **未知不补零**(C15):分母是 0 → None(页面写「—」不写 0%);金额算不出的那几笔单独数,费用写「至少 X」。
  每个办成任务的成本 = 窗口里**所有**运行(含失败、重试)的已知费用 ÷ 办成数 —— 失败的钱也是为了办成花的。
- 耗时分位数用 PostgreSQL percentile_cont(线性插值,常用口径);**样本少于 小样本线 条的标「样本少」**。
  ⚠️ 小样本线 20 是**产品默认值,业务没确认过** —— 方案原话:「所有阈值为产品配置,业务未确认前不可伪装行业标准」。
- 环境:访问 API 发起的运行把环境记在 definition_ref.环境(execution_runs.environment 那一列一律是 development),以前者为准。
"""
import datetime as _dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from db import 连接
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

小样本线 = 20          # 产品默认值,业务未确认(见文件头)
调试跑法 = ("连接测试", "样例预览", "集成验证")
终态 = ("succeeded", "failed", "cancelled", "incomplete")
范围们 = ("业务", "调试", "全部")

# 一次运行的几个维度怎么取 —— 写成一段 SQL 表达式,清单 / 汇总 / 分组都用这一份(改一处全改)
_维度 = """
    r.definition_ref->>'id' 应用,
    (r.definition_ref->>'version_no')::int 版本,
    coalesce(r.definition_ref->>'环境', r.environment) 环境,
    coalesce(r.definition_ref->>'发起', case when r.definition_ref->>'跑法' is not null then '后台:' || (r.definition_ref->>'跑法')
                                         else '后台' end) 入口,
    case when r.execution_mode = 'live' and coalesce(r.definition_ref->>'跑法', '正常') not in ('连接测试', '样例预览', '集成验证')
         then '业务' else '调试' end 范围"""


def 归类(状态, 写入数, 已执行数):
    """一次运行 → 监测里的那一类。**纯函数,判据真调它**(test_monitoring)。"""
    if 状态 == "succeeded":
        if 写入数 == 0:
            return "跑完·这次不需要写入"
        return "办成" if 已执行数 == 写入数 else "跑完·没证实"
    if 状态 in ("failed", "cancelled", "incomplete"):
        return {"failed": "失败", "cancelled": "取消", "incomplete": "没做完"}[状态]
    if 状态 == "waiting_approval":
        return "等人核对"
    if 状态 == "waiting_external":
        return "等澜绣执行"
    return "进行中"


def 比例(分子, 分母):
    """分母是 0 → None(未知),**不写 0**。"""
    return round(分子 * 100 / 分母, 1) if 分母 else None


@router.get(前缀 + "/monitoring")
def 监测(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
       范围: str = Query("业务"), 应用: str = Query(None), 环境: str = Query(None), 版本: int = Query(None),
       入口: str = Query(None), 天: int = Query(7, ge=1, le=90)):
    """监测页:可用性 / 业务办成 / 性能 / 成本,外加按 应用 × 版本 的分组。所有卡片同一个筛选、同一个时间窗。"""
    if 范围 not in 范围们:
        raise _错(422, "VALIDATION", f"范围只收 {list(范围们)}", "默认「业务」;要看连接测试和 mock 跑的选「调试」", field_errors={"范围": f"只收 {list(范围们)}"})
    参 = {"p": project_id, "d": 天}
    条件 = []
    for 名, 值 in (("应用", 应用), ("环境", 环境), ("版本", 版本), ("入口", 入口)):
        if 值 is not None and 值 != "":
            条件.append(f"{名} = :{名}")
            参[名] = 值
    if 范围 != "全部":
        条件.append("范围 = :范围")
        参["范围"] = 范围
    where = (" and " + " and ".join(条件)) if 条件 else ""
    with 连接() as c:
        行 = c.execute(text(f"""
            with 跑 as (
                select r.id, r.status, r.created_at, r.started_at, r.ended_at, r.trace_id, {_维度}
                  from execution_runs r
                 where r.project_id=:p and r.archived_at is null and r.kind in ('workflow', 'application')
                   and r.created_at > now() - make_interval(days => :d))
            select 跑.*,
                   (select count(*) from bridge_calls b where b.project_id=:p and b.execution_run_id=跑.id) 写入数,
                   (select count(*) from bridge_calls b where b.project_id=:p and b.execution_run_id=跑.id
                       and b.status='已执行') 已执行数,
                   (select coalesce(sum(u.amount) filter (where u.amount_known), 0) from usage_ledger u
                     where u.project_id=:p and u.trace_id=跑.trace_id) 已知费用,
                   (select count(*) filter (where not u.amount_known) from usage_ledger u
                     where u.project_id=:p and u.trace_id=跑.trace_id) 算不出笔数,
                   (select coalesce(sum(u.quantity) filter (where u.unit='token'), 0) from usage_ledger u
                     where u.project_id=:p and u.trace_id=跑.trace_id) token
              from 跑 where true {where}"""), 参).mappings().all()
        分位 = c.execute(text(f"""
            with 跑 as (
                select r.status, r.created_at, r.started_at, r.ended_at, {_维度}
                  from execution_runs r
                 where r.project_id=:p and r.archived_at is null and r.kind in ('workflow', 'application')
                   and r.created_at > now() - make_interval(days => :d))
            select count(*) filter (where ended_at is not null and started_at is not null and status in {终态}) 端到端n,
                   percentile_cont(0.5) within group (order by extract(epoch from ended_at - started_at))
                       filter (where ended_at is not null and started_at is not null and status in {终态}) 端到端p50,
                   percentile_cont(0.95) within group (order by extract(epoch from ended_at - started_at))
                       filter (where ended_at is not null and started_at is not null and status in {终态}) 端到端p95,
                   count(*) filter (where started_at is not null) 排队n,
                   percentile_cont(0.5) within group (order by extract(epoch from started_at - created_at))
                       filter (where started_at is not null) 排队p50,
                   percentile_cont(0.95) within group (order by extract(epoch from started_at - created_at))
                       filter (where started_at is not null) 排队p95
              from 跑 where true {where}"""), 参).mappings().first()
        选项 = c.execute(text(f"""
            select distinct {_维度} from execution_runs r
             where r.project_id=:p and r.archived_at is null and r.kind in ('workflow', 'application')
               and r.created_at > now() - make_interval(days => :d)"""), {"p": project_id, "d": 天}).mappings().all()

    类 = {}
    for x in 行:
        k = 归类(x["status"], x["写入数"], x["已执行数"])
        类[k] = 类.get(k, 0) + 1
    终态数 = sum(类.get(k, 0) for k in ("办成", "跑完·没证实", "跑完·这次不需要写入", "失败", "取消", "没做完"))
    跑完数 = sum(类.get(k, 0) for k in ("办成", "跑完·没证实", "跑完·这次不需要写入"))
    有写入的跑完 = 类.get("办成", 0) + 类.get("跑完·没证实", 0)
    已知 = sum(float(x["已知费用"] or 0) for x in 行)
    算不出 = sum(int(x["算不出笔数"] or 0) for x in 行)
    办成 = 类.get("办成", 0)

    def 秒(v):
        return round(float(v), 2) if v is not None else None

    def 分(n, p50, p95):
        return {"样本数": n, "P50秒": 秒(p50), "P95秒": 秒(p95), "样本少": n < 小样本线}

    组 = {}
    for x in 行:
        g = 组.setdefault((x["应用"], x["版本"]), {"应用": x["应用"], "版本": x["版本"], "接收": 0, "终态": 0, "跑完": 0,
                                                  "办成": 0, "有写入的跑完": 0, "已知费用": 0.0, "算不出笔数": 0})
        k = 归类(x["status"], x["写入数"], x["已执行数"])
        g["接收"] += 1
        g["终态"] += k in ("办成", "跑完·没证实", "跑完·这次不需要写入", "失败", "取消", "没做完")
        g["跑完"] += k in ("办成", "跑完·没证实", "跑完·这次不需要写入")
        g["办成"] += k == "办成"
        g["有写入的跑完"] += k in ("办成", "跑完·没证实")
        g["已知费用"] += float(x["已知费用"] or 0)
        g["算不出笔数"] += int(x["算不出笔数"] or 0)
    分组 = [dict(g, 终态成功率=比例(g["跑完"], g["终态"]), 写入办成率=比例(g["办成"], g["有写入的跑完"]),
               已知费用=round(g["已知费用"], 6), 样本少=g["接收"] < 小样本线)
          for g in sorted(组.values(), key=lambda g: (-g["接收"], str(g["应用"]), g["版本"] or 0))]

    说 = []
    if not 行:
        说.append("这个范围里一次运行都没有 —— 所有比例都是「未知」,不是 0")
    elif len(行) < 小样本线:
        说.append(f"⚠️ 只有 {len(行)} 次运行(少于 {小样本线}):比例波动大,别当结论用")
    if 算不出:
        说.append(f"⚠️ 有 {算不出} 笔花费算不出金额 —— 费用是「至少」这么多,每个办成任务的成本也是至少")
    if 范围 == "业务":
        说.append("默认只看业务运行;调试(连接测试 / 样例预览 / 集成验证 / mock)切到「调试」看")
    说.append(f"小样本线 {小样本线} 是产品默认值,业务还没确认过")

    return {
        "筛选": {"范围": 范围, "应用": 应用, "环境": 环境, "版本": 版本, "入口": 入口, "天": 天},
        "更新时刻": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "可用性": {"接收": len(行), "终态": 终态数, "跑完": 跑完数, "失败": 类.get("失败", 0), "取消": 类.get("取消", 0),
                 "没做完": 类.get("没做完", 0), "进行中": 类.get("进行中", 0), "等人核对": 类.get("等人核对", 0),
                 "等澜绣执行": 类.get("等澜绣执行", 0),
                 "终态成功率": 比例(跑完数, 终态数), "终态成功率分母": 终态数,
                 "说明": "终态成功率 = 跑完 ÷ 已终结的(等待中的不算失败也不算成功)"},
        "业务": {"办成": 办成, "跑完·没证实": 类.get("跑完·没证实", 0), "跑完·这次不需要写入": 类.get("跑完·这次不需要写入", 0),
               "写入办成率": 比例(办成, 有写入的跑完), "写入办成率分母": 有写入的跑完,
               "说明": "办成 = 跑完 + 每一处写入都拿到澜绣的「已执行」回执(用户 11-04 拍);"
                       "这次不需要写入的单列,不混进办成率"},
        "性能": {"端到端": 分(分位["端到端n"], 分位["端到端p50"], 分位["端到端p95"]),
               "排队": 分(分位["排队n"], 分位["排队p50"], 分位["排队p95"]), "小样本线": 小样本线},
        "成本": {"已知费用": round(已知, 6), "币种": "USD", "算不出金额的笔数": 算不出, "是至少吗": 算不出 > 0,
               "token": int(sum(float(x["token"] or 0) for x in 行)),
               "每个办成任务成本": (round(已知 / 办成, 6) if 办成 else None),
               "说明": "每个办成任务成本 = 窗口里所有运行(含失败、重试)的已知费用 ÷ 办成数;办成是 0 → 未知,不写 0 元"},
        "分组": 分组,
        "可选": {k: sorted({x[k] for x in 选项 if x[k] is not None}, key=str) for k in ("应用", "版本", "环境", "入口")},
        "note": ";".join(说),
    }
