# -*- coding: utf-8 -*-
"""日志采集策略:保留多久 / 每个项目最多占多少 / 用到多少告警(用户 11-13 拍业务拍板第四十条「用建议值」)。

建议值 30 天 / 5 GB / 80%,**改设置页就行,不改代码**(拍板原话)。

## 管的是哪些日志
运行的五类原始记录(和「原始日志」那一页同一份,见 workflows_api._原始记录):
事件 run_events · 步骤尝试 run_steps · 工具调用 tool_invocations · 人工决定 human_decisions · 澜绣桥请求 bridge_calls。
**只算、只清装正文的那几列**(_正文列)—— 骨架(谁、何时、什么状态、指纹、幂等键)永远留着:
清掉的是客户原文,不是「这件事发生过」。和聊天站 traces 那边 runs_api.原文留天 同一个做法。

## 存在哪
项目表本来就有一列 retention_policy(初始表结构里留的,一直空着),这里存一小段 JSON。
空 = 用建议值,页面写明「用的是建议值」—— 「没设」和「设成了建议值」看起来一样,但前者改了建议值会跟着变。

## 到期清理默认关着
清正文**不可逆**。所以「到期清理」是策略里单独一个开关,默认关:
先在设置页看「到期会清哪些」(每类几条、多少字节),人看过再打开。worker 只在开关打开的项目上清。

## 用量怎么量
pg_column_size 求和 = 库里实际占的字节(压缩后),和「容量上限」是同一把尺子。
不算索引和骨架列 —— 上限管的是「采了多少正文」,骨架很小且不会被清,算进去只会让上限永远降不下来。
"""
import datetime as _dt
import json as _json
import os as _os
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"

建议值 = {"保留天数": 30, "容量上限GB": 5, "告警比例": 0.8, "到期清理": False}   # 拍板第四十条
上下限 = {"保留天数": (7, 365), "容量上限GB": (1, 100), "告警比例": (0.5, 0.95)}
GB = 1024 ** 3
每轮每类最多清 = 2000     # 一轮一类最多改这么多行:别让一次清理长时间锁住正在写日志的表

# 来源 → (表, [(列, 是jsonb)])。时间一律按 created_at(五张表都有、都不改)
_正文列 = {
    "事件": ("run_events", [("payload", True)]),
    "步骤尝试": ("run_steps", [("input_ref", False), ("output_ref", False), ("error_detail", True)]),
    "工具调用": ("tool_invocations", [("result_ref", False), ("error_detail", True)]),
    "人工决定": ("human_decisions", [("edited_fields", True), ("reason", False)]),
    "桥请求": ("bridge_calls", [("arguments_snapshot", True), ("result_output", True), ("error_detail", True)]),
}


def _到期说明(天):
    return f"采集策略保留 {天} 天,正文已到期删除(骨架留着)"


def _占位(列是jsonb, 天):
    return _json.dumps({"到期删除": _到期说明(天)}, ensure_ascii=False) if 列是jsonb else f"[到期删除] {_到期说明(天)}"


def 解析(原):
    """retention_policy 列 → (策略, 来源)。空 / 坏 → 建议值。坏的不报错不吞:来源写「存的值读不出,按建议值」。"""
    if not 原:
        return dict(建议值), "建议值"
    try:
        d = _json.loads(原)
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        return dict(建议值), "存的值读不出,按建议值"
    出 = dict(建议值)
    for k in 建议值:
        if k in d:
            出[k] = d[k]
    return 出, "已设置"


def 校验(体):
    """→ (策略, 坏)。四项都要给:这是产品配置,缺一项就默默补建议值等于替人做主。"""
    坏, 出 = {}, {}
    for k, (lo, hi) in 上下限.items():
        v = 体.get(k)
        try:
            v = float(v) if k == "告警比例" else int(v)
        except (TypeError, ValueError):
            坏[k] = f"要数字({lo}–{hi})"
            continue
        if isinstance(体.get(k), bool) or not (lo <= v <= hi):
            坏[k] = f"要在 {lo}–{hi} 之间"
            continue
        出[k] = v
    if not isinstance(体.get("到期清理"), bool):
        坏["到期清理"] = "要 true / false"
    else:
        出["到期清理"] = 体["到期清理"]
    return 出, 坏


def 取策略(c, project_id):
    r = c.execute(text("select retention_policy, revision from projects where id=:p"), {"p": project_id}).mappings().first()
    if not r:
        return None, None, None
    策, 来 = 解析(r["retention_policy"])
    return 策, 来, r["revision"]


def 用量(c, project_id):
    """→ {字节, 各来源:{来源:{条数, 字节}}}。只算正文列。"""
    各 = {}
    for 源, (表, 列们) in _正文列.items():
        和 = " + ".join(f"coalesce(pg_column_size({列}), 0)" for 列, _ in 列们)
        r = c.execute(text(f"select count(*) n, coalesce(sum({和}), 0) b from {表} where project_id=:p"),
                      {"p": project_id}).mappings().first()
        各[源] = {"条数": int(r["n"]), "字节": int(r["b"])}
    return {"字节": sum(x["字节"] for x in 各.values()), "各来源": 各}


def _到期条件(列们, 天):
    """「还有正文没清」= 任一正文列非空且不是占位。占位按列类型比:jsonb 比对象、text 比前缀。"""
    子 = []
    for 列, 是j in 列们:
        if 是j:
            子.append(f"({列} is not null and not ({列} ? '到期删除'))")
        else:
            子.append(f"({列} is not null and {列} not like '[到期删除]%')")
    return "(" + " or ".join(子) + ")"


def 到期清单(c, project_id, 天, 现在=None):
    """→ {截止, 各来源:{条数, 字节}, 合计条数, 合计字节}。只读 —— 打开「到期清理」之前给人看的就是这个。"""
    现在 = 现在 or _dt.datetime.now(_dt.timezone.utc)
    截止 = 现在 - _dt.timedelta(days=int(天))
    各 = {}
    for 源, (表, 列们) in _正文列.items():
        和 = " + ".join(f"coalesce(pg_column_size({列}), 0)" for 列, _ in 列们)
        r = c.execute(text(f"""select count(*) n, coalesce(sum({和}), 0) b from {表}
                                where project_id=:p and created_at < :t and {_到期条件(列们, 天)}"""),
                      {"p": project_id, "t": 截止}).mappings().first()
        各[源] = {"条数": int(r["n"]), "字节": int(r["b"])}
    return {"截止": 截止.isoformat(), "各来源": 各, "合计条数": sum(x["条数"] for x in 各.values()),
            "合计字节": sum(x["字节"] for x in 各.values())}


def 清一轮(c, project_id, 天, 现在=None, 每类最多=None):
    """把到期行的正文换成占位 → {来源: 改了几行}。**调用方负责确认「到期清理」开着** —— 这里不再看开关,
    这样检查能直接验「清的范围对不对」,而开关闸单独在 扫到期() 里验。"""
    现在 = 现在 or _dt.datetime.now(_dt.timezone.utc)
    截止 = 现在 - _dt.timedelta(days=int(天))
    限 = int(每类最多 or 每轮每类最多清)
    出 = {}
    for 源, (表, 列们) in _正文列.items():
        设 = ", ".join(f"{列} = case when {列} is null then null else "
                      + (f"cast(:z_j as jsonb)" if 是j else ":z_t") + " end" for 列, 是j in 列们)
        n = c.execute(text(f"""update {表} set {设}
                                where project_id=:p and id in (
                                  select id from {表} where project_id=:p and created_at < :t and {_到期条件(列们, 天)}
                                   order by created_at limit :lim)"""),
                      {"p": project_id, "t": 截止, "lim": 限, "z_j": _占位(True, 天), "z_t": _占位(False, 天)}).rowcount
        出[源] = n
    return 出


def 扫到期(现在=None):
    """worker 每 60 秒调一次:只在「到期清理」开着的项目上清一轮,有清就记一条审计。出错只回一句话,不拖垮 worker。"""
    出 = []
    with 连接() as c:
        项目们 = [(x["id"], x["organization_id"], x["retention_policy"]) for x in c.execute(text(
            "select id, organization_id, retention_policy from projects where archived_at is null")).mappings()]
    for pid, org, 原 in 项目们:
        策, _ = 解析(原)
        if 策.get("到期清理") is not True:
            continue
        try:
            with 事务() as c:
                改 = 清一轮(c, pid, 策["保留天数"], 现在)
                if sum(改.values()):
                    c.execute(text("""insert into audit_events (id, organization_id, project_id, actor, action, target_ref,
                                          environment, at, result, reason, created_at, created_by)
                                      values (:i, :o, :p, 'worker', '日志到期清理', :t, :e, now(), 'ok', :r, now(), 'worker')"""),
                              {"i": f"aud_{_uuid.uuid4().hex[:12]}", "o": org, "p": pid,
                               "t": _json.dumps(改, ensure_ascii=False), "e": _os.environ.get("APP_ENV", "development"),
                               "r": _到期说明(策["保留天数"])})
                    出.append(f"{pid} 清了 {sum(改.values())} 行正文({改})")
        except Exception as e:  # noqa: BLE001
            出.append(f"⚠️ {pid} 到期清理出错({type(e).__name__}: {e})—— 下一轮再试")
    return 出


def 占比(c, project_id):
    """告警指标「日志用量占比」→ (值%, 样本)。项目不在 → (None, 0)。"""
    策, _, _ = 取策略(c, project_id)
    if 策 is None:
        return None, 0
    上限 = float(策["容量上限GB"]) * GB
    return round(用量(c, project_id)["字节"] / 上限 * 100, 4), 1


def _样子(c, project_id, 策, 来, rev):
    量 = 用量(c, project_id)
    上限 = int(float(策["容量上限GB"]) * GB)
    return {"策略": 策, "来源": 来, "建议值": 建议值, "上下限": 上下限, "revision": rev,
            "用量": 量 | {"上限字节": 上限, "占比": round(量["字节"] / 上限 * 100, 4),
                        "告警线字节": int(上限 * float(策["告警比例"]))},
            "到期": 到期清单(c, project_id, 策["保留天数"]),
            "说明": "只算 / 只清五类原始记录里装正文的列;骨架(谁、何时、状态、指纹)永远留着。到期清理不可逆,默认关。"}


@router.get(前缀 + "/log-policy")
def 看策略(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        策, 来, rev = 取策略(c, project_id)
        if 策 is None:
            raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
        return _样子(c, project_id, 策, 来, rev)


@router.put(前缀 + "/log-policy")
async def 改策略(project_id: str, request: Request, if_match: str = Header(default=None, alias="If-Match"),
              me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{保留天数, 容量上限GB, 告警比例, 到期清理}` 四项都要。告警比例改了 → 系统种的那条「日志用量占比」规则阈值跟着改。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把读到的 revision 放进 If-Match 头")
    体 = await request.json()
    策, 坏 = 校验(体 if isinstance(体, dict) else {})
    if 坏:
        raise _错(422, "VALIDATION", "采集策略有项不对", "按提示改", field_errors=坏)
    with 事务() as c:
        r = c.execute(text("select retention_policy, revision, organization_id from projects where id=:p for update"),
                      {"p": project_id}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这个项目", "确认项目号")
        if str(r["revision"]) != str(if_match).strip('"'):
            raise _错(409, "REVISION_CONFLICT", "项目设置刚被改过", "刷新再改")
        旧, _ = 解析(r["retention_policy"])
        c.execute(text("""update projects set retention_policy=:v, revision=revision+1, updated_at=now()
                           where id=:p"""), {"v": _json.dumps(策, ensure_ascii=False), "p": project_id})
        c.execute(text("""update alert_rules set threshold_value=:th, revision=revision+1, updated_at=now()
                           where project_id=:p and metric_code='日志用量占比' and owner='system' and archived_at is null"""),
                  {"th": 阈值(策["告警比例"]), "p": project_id})
        c.execute(text("""insert into audit_events (id, organization_id, project_id, actor, action, target_ref, environment, at,
                              result, reason, created_at, created_by)
                          values (:i, :o, :p, :a, '改日志采集策略', :t, :e, now(), 'ok', null, now(), :a)"""),
                  {"i": f"aud_{_uuid.uuid4().hex[:12]}", "o": r["organization_id"], "p": project_id, "a": me.user_id,
                   "t": _json.dumps({"旧": 旧, "新": 策}, ensure_ascii=False), "e": _os.environ.get("APP_ENV", "development")})
        rev = c.execute(text("select revision from projects where id=:p"), {"p": project_id}).scalar()
        return _样子(c, project_id, 策, "已设置", rev)


def 阈值(比例):
    """「高于」是严格大于;占比按 4 位小数算 → 写 比例×100 − 0.0001,到线(等于 80%)就报。"""
    return round(float(比例) * 100 - 0.0001, 4)
