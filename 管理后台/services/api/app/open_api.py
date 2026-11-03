# -*- coding: utf-8 -*-
"""访问 API(Dify 对标二期)—— 外部系统带一把密钥,跑某个应用**已上生产**的那一版。

用户拍板(2026-11-02 / 11-03,方案文档《澜绣云裳agent-访问API方案》):
  1. 一把密钥只绑一个应用,只跑它生产环境指着的那一版(草稿、候选永远调不到,审核那道闸绕不过去)
  2. 以**发密钥的那个人**的身份跑,每次调用前重核他还有没有「运行编排测试」(照定时运行)
  3. 先工作流、再聊天(聊天那一半要先有「管理后台调聊天站」的通道,现在没有)
  4. 限量:每把每分钟最多 30 次;每天花费到上限就拒,上限发密钥时填、只许改小、设了项目每日预算就不许超过它
  5. 先补记账,按金额封顶:花费 = 这把密钥发起的运行在 usage_ledger 里的金额(workers/worker._记这一段的账 记的)

## 两半

  · **后台这一半**(项目前缀下,要「配置密钥与预算」):发 / 列 / 改小上限 / 吊销。原文只在发出那一刻返回一次
  · **对外这一半**(`/open/v1`,带密钥):发起运行 / 查结果。**每一次调用都记一行 access_key_calls**,被拒的也记 ——
    限流数的就是它;而且被拒的那一行要在**另一个事务**里写:报错会把当前事务回滚,同一个事务里记的「被拒」会跟着没了

## ⚠️ 措辞

错误体会被 contract/errors 的泄密检查扫键名和值(token / api_key / authorization / bearer …命中就直接抛)。
所以这里的提示一律说「访问密钥」,不出现那几个词。
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import workflows_api as WF

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
对外 = "/open/v1"

密钥开头 = "lx-app-"
每分钟上限 = 30
币种 = "USD"                     # 价目表(pricing_versions)按美元登记;上限和花费要同一种币才比得了
本地时区 = timezone(timedelta(hours=8))   # 「今天」按门店所在的东八区算,不按 UTC —— 不然每天早上 8 点额度才清零


def _哈希(原文):
    return hashlib.sha256(原文.encode()).hexdigest()


def _今天起点():
    now = datetime.now(本地时区)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _金额(v, 名):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise _错(422, "VALIDATION", f"{名}要是一个数", "填美元金额,比如 5", field_errors={名: "要是数"})
    if not d.is_finite() or d <= 0:
        raise _错(422, "VALIDATION", f"{名}要大于 0", "「不限」不提供 —— 泄露或对方死循环时,上限就是最多损失一天的那个数",
                  field_errors={名: "要大于 0"})
    return d


def _项目日预算(c, project_id):
    """项目每日预算那一行;没有 = 没设上限(budgets 的老规矩:不建那一行才表示不限,不用 0 表示)。"""
    r = c.execute(text("""select limit_amount, currency from budgets
                           where project_id=:p and scope='project' and period='day' and archived_at is null
                           order by created_at desc limit 1"""), {"p": project_id}).mappings().first()
    return dict(r) if r else None


def _今天花了(c, project_id, kid):
    """→ (已知金额之和, 算不出金额的账有几行)。按东八区的今天、按这把密钥发起的运行。"""
    r = c.execute(text("""
        select coalesce(sum(u.amount) filter (where u.amount_known), 0) 花了,
               count(*) filter (where not u.amount_known) 算不出
          from usage_ledger u
          join execution_runs e on e.project_id=u.project_id and e.trace_id=u.trace_id
         where u.project_id=:p and e.definition_ref->>'密钥id' = :k and u.created_at >= :起"""),
        {"p": project_id, "k": kid, "起": _今天起点()}).mappings().first()
    return Decimal(r["花了"] or 0), int(r["算不出"] or 0)


def _键的样子(r, 花了=None, 算不出=None):
    return {"id": r["id"], "名字": r["name"], "开头": r["prefix_code"] + "…", "应用id": r["application_id"],
            "每天上限": float(r["daily_cap_amount"]), "币种": r["currency"], "发的人": r["created_by"],
            "发于": r["created_at"].isoformat() if r["created_at"] else None,
            "最后一次用": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "吊销于": r["revoked_at"].isoformat() if r["revoked_at"] else None, "吊销人": r["revoked_by"],
            "今天花了": float(花了) if 花了 is not None else None, "今天算不出金额的账": 算不出,
            "revision": r["revision"]}


# ══ 后台这一半 ════════════════════════════════════════════════════════════════

@router.get(前缀 + "/workflows/{wid}/access-keys")
def 密钥列表(project_id: str, wid: str, me: 身份 = Depends(要权限("配置密钥与预算"))):
    with 连接() as c:
        aid = WF._工作流应用(c, project_id, wid)
        if not aid:
            return {"应用id": None, "条数": 0, "密钥": [], "最近调用": [],
                    "note": "这条工作流还没有应用(从没发布过)—— 发密钥时会建;**但只跑生产那一版,没上生产的调用会被拒**"}
        行 = c.execute(text("""select * from access_keys where project_id=:p and application_id=:a
                                order by created_at desc"""), {"p": project_id, "a": aid}).mappings().all()
        密钥们 = [_键的样子(r, *_今天花了(c, project_id, r["id"])) for r in 行]
        调用 = c.execute(text("""select k.name 密钥, k.prefix_code 开头, x.endpoint_code 接口, x.outcome_code 结果,
                                       x.http_code 码, x.execution_run_id 运行, x.detail_note 说明, x.created_at 时间
                                  from access_key_calls x join access_keys k
                                    on k.project_id=x.project_id and k.id=x.access_key_id
                                 where x.project_id=:p and k.application_id=:a
                                 order by x.created_at desc limit 20"""), {"p": project_id, "a": aid}).mappings().all()
        生产 = WF._生产版本(c, project_id, wid)
    return {"应用id": aid, "条数": len(密钥们), "密钥": 密钥们,
            "最近调用": [dict(x, 时间=x["时间"].isoformat()) for x in 调用], "最近调用只列了": 20,
            "生产版本号": 生产 and 生产["版本号"],
            "调用地址": f"{对外}/apps/{aid}/runs",
            "note": ("**原文只在发出那一刻显示一次**,库里只有哈希 —— 忘了就吊销重发。"
                     "调用以**发密钥的那个人**的身份跑,他的权限每次都重核。")}


@router.get(前缀 + "/access-keys")
def 项目里的密钥(project_id: str, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """这个项目里所有的访问密钥(哪个应用的、今天花了多少、revision)。**原文从不返回**。
    改小上限要带的 If-Match 就从这里(或某条工作流的「访问入口」)拿。"""
    with 连接() as c:
        行 = c.execute(text("select * from access_keys where project_id=:p order by created_at desc"),
                      {"p": project_id}).mappings().all()
        密钥们 = [_键的样子(r, *_今天花了(c, project_id, r["id"])) for r in 行]
    return {"条数": len(密钥们), "密钥": 密钥们}


@router.post(前缀 + "/workflows/{wid}/access-keys", status_code=201)
async def 发密钥(project_id: str, wid: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{名字, 每天上限}` → 原文(只这一次)。**上限必填**;设了项目每日预算的话不许超过它。"""
    体 = await request.json()
    名 = (体.get("名字") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION", "名字不能空", "写清这把密钥给谁用,比如「门店小程序」", field_errors={"名字": "必填"})
    上限 = _金额(体.get("每天上限"), "每天上限")
    原文 = 密钥开头 + secrets.token_hex(20)
    with 事务() as c:
        w = c.execute(text("select name from workflows where project_id=:p and id=:w and archived_at is null"),
                      {"p": project_id, "w": wid}).mappings().first()
        if not w:
            raise _错(404, "NOT_FOUND", "没有这条工作流", "回列表重新进入")
        预 = _项目日预算(c, project_id)
        if 预:
            if (预["currency"] or "").upper() != 币种:
                raise _错(422, "VALIDATION", f"项目每日预算是 {预['currency']},而花费按 {币种} 记,比不了",
                          "把项目每日预算改成美元,或者先不设项目预算", field_errors={"每天上限": "币种对不上"})
            if 上限 > Decimal(预["limit_amount"]):
                raise _错(422, "VALIDATION", f"每天上限 {上限} 超过了项目每日预算 {预['limit_amount']}",
                          "改小,或者先调高项目预算", field_errors={"每天上限": "超过项目每日预算"})
        aid = WF._工作流应用(c, project_id, wid, me, w["name"])
        kid = WF._新id("ak")
        c.execute(text("""insert into access_keys (id, organization_id, project_id, application_id, name, prefix_code,
                              lookup_hash, daily_cap_amount, currency, created_at, created_by, updated_at, revision)
                          values (:i,:o,:p,:a,:n,:pc,:h,:cap,:cur, now(), :by, now(), 1)"""),
                  {"i": kid, "o": me.org_id, "p": project_id, "a": aid, "n": 名, "pc": 原文[:13],
                   "h": _哈希(原文), "cap": 上限, "cur": 币种, "by": me.user_id})
        WF._审计(c, me, "access_key.issue", {"密钥": kid, "应用": aid, "名字": 名, "每天上限": str(上限)})
    return {"id": kid, "名字": 名, "原文": 原文, "开头": 原文[:13] + "…", "应用id": aid,
            "每天上限": float(上限), "币种": 币种, "调用地址": f"{对外}/apps/{aid}/runs",
            "note": "**这是唯一一次看得到原文** —— 现在就存好;库里只有哈希,谁都找不回,忘了就吊销重发"}


@router.patch(前缀 + "/access-keys/{kid}")
async def 改小上限(project_id: str, kid: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{每天上限}`,**只许改小**(用户拍)—— 要调大就吊销重发,让「谁批的更大额度」留在审计里。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把列表里这把密钥的 revision 放进 If-Match 头")
    体 = await request.json()
    新 = _金额(体.get("每天上限"), "每天上限")
    with 事务() as c:
        r = c.execute(text("select * from access_keys where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": kid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这把密钥", "回列表重新进入")
        if str(r["revision"]) != str(if_match).strip('"'):
            raise _错(409, "REVISION_CONFLICT", "这把密钥已经被改过了", "刷新看一眼再改")
        if 新 >= Decimal(r["daily_cap_amount"]):
            raise _错(422, "VALIDATION", f"只许改小(现在是 {r['daily_cap_amount']})",
                      "要更大的额度:吊销这把、重发一把 —— 谁批的更大额度要留在审计里", field_errors={"每天上限": "只许改小"})
        c.execute(text("""update access_keys set daily_cap_amount=:cap, updated_at=now(), revision=revision+1
                           where project_id=:p and id=:i"""), {"cap": 新, "p": project_id, "i": kid})
        WF._审计(c, me, "access_key.lower_cap", {"密钥": kid, "从": str(r["daily_cap_amount"]), "到": str(新)})
    return {"id": kid, "每天上限": float(新), "revision": r["revision"] + 1}


@router.post(前缀 + "/access-keys/{kid}/revoke")
async def 吊销(project_id: str, kid: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """吊销**立刻生效**(每次调用都查)。行不删 —— 运行记录还指着它。"""
    体 = await request.json()
    理由 = (体.get("理由") or "").strip()
    if len(理由) < 2:
        raise _错(422, "VALIDATION", "要写吊销理由", "比如「门店小程序下线」「怀疑泄露」", field_errors={"理由": "必填"})
    with 事务() as c:
        r = c.execute(text("select revoked_at from access_keys where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": kid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这把密钥", "回列表重新进入")
        if r["revoked_at"]:
            return {"id": kid, "吊销了吗": True, "note": "早就吊销了,这次什么都没改"}
        c.execute(text("""update access_keys set revoked_at=now(), revoked_by=:u, updated_at=now(), revision=revision+1
                           where project_id=:p and id=:i"""), {"u": me.user_id, "p": project_id, "i": kid})
        WF._审计(c, me, "access_key.revoke", {"密钥": kid}, reason=理由)
    return {"id": kid, "吊销了吗": True, "note": "已吊销,从下一次调用起就拒"}


# ══ 对外这一半 ════════════════════════════════════════════════════════════════

class _拒(Exception):
    def __init__(self, http, code, 结果, message, 建议):
        self.http, self.code, self.结果, self.message, self.建议 = http, code, 结果, message, 建议


def _认密钥(c, 头):
    """`Authorization: Bearer lx-app-…` → 那一行;认不出就拒(401)。**按哈希查**,原文不落任何地方。"""
    v = (头 or "").strip()
    if v[:7].lower() == "bearer ":
        v = v[7:].strip()
    if not v.startswith(密钥开头):
        raise _拒(401, "NO_ACCESS_KEY", None, "没带访问密钥,或者格式不对", f"请求头里带上发给你的那把(以 {密钥开头} 开头)")
    r = c.execute(text("select * from access_keys where lookup_hash=:h"), {"h": _哈希(v)}).mappings().first()
    if not r:
        raise _拒(401, "UNKNOWN_ACCESS_KEY", None, "这把访问密钥不认识", "核对一下是不是抄错了;找后台的人重发一把")
    return dict(r)


def _记一笔(r, 接口, 结果, 码, 运行=None, 说明=None):
    """记一行调用。**单独开事务** —— 被拒时外层事务会回滚,同一个事务里记的「被拒」会跟着没了。"""
    if not r:
        return
    with 事务() as c:
        c.execute(text("""insert into access_key_calls (id, organization_id, project_id, created_at, created_by,
                              access_key_id, endpoint_code, outcome_code, http_code, execution_run_id, detail_note)
                          values (:i,:o,:p, now(), :by, :k, :e, :r, :h, :x, :d)"""),
                  {"i": WF._新id("akc"), "o": r["organization_id"], "p": r["project_id"], "by": r["created_by"],
                   "k": r["id"], "e": 接口, "r": 结果, "h": str(码), "x": 运行, "d": (说明 or "")[:300] or None})
        c.execute(text("update access_keys set last_used_at=now() where project_id=:p and id=:i"),
                  {"p": r["project_id"], "i": r["id"]})


def _过闸(c, r):
    """吊销 / 限流 / 发密钥的人还有没有权限 → 他的身份。"""
    if r["revoked_at"]:
        raise _拒(401, "ACCESS_KEY_REVOKED", "已吊销", "这把访问密钥已经吊销", "找后台的人重发一把")
    n = c.execute(text("""select count(*) from access_key_calls
                           where project_id=:p and access_key_id=:k and created_at > now() - interval '60 seconds'"""),
                  {"p": r["project_id"], "k": r["id"]}).scalar()
    if n >= 每分钟上限:
        raise _拒(429, "RATE_LIMITED", "限流", f"这把访问密钥一分钟内已经调了 {n} 次(上限 {每分钟上限})",
                  "隔一分钟再调;对方要是在死循环,先停掉它")
    本人 = WF._成员身份(c, r["project_id"], r["created_by"])
    if not 本人:
        raise _拒(403, "ISSUER_GONE", "没权限", f"发这把访问密钥的账号 {r['created_by']} 已经不是这个项目的成员",
                  "找后台的人用现在在职的账号重发一把")
    能, 为什么 = 本人.能("运行编排测试")
    if not 能:
        raise _拒(403, "ISSUER_FORBIDDEN", "没权限", f"发这把访问密钥的账号 {r['created_by']} 现在没有发起运行的权限",
                  为什么 or "找管理员核一下他的角色")
    return 本人


def _拒成错(e):
    return _错(e.http, e.code, e.message, e.建议)


@router.post(对外 + "/apps/{aid}/runs", status_code=202)
async def 对外发起(aid: str, request: Request,
               authorization: str = Header(default=None),
               idempotency_key: str = Header(default=None, alias="Idempotency-Key")):
    """发起一次运行,跑这个应用**生产环境指着的那一版**。入参 `{输入: {...}}` → `{运行编号, 状态, 查结果}`。"""
    r = None
    try:
        with 连接() as c:
            r = _认密钥(c, authorization)
            本人 = _过闸(c, r)
            if r["application_id"] != aid:
                raise _拒(403, "WRONG_APP", "应用不对", "这把访问密钥不是这个应用的", "一把密钥只能调它绑的那一个应用")
        if not idempotency_key:
            raise _拒(409, "IDEMPOTENCY_KEY_REQUIRED", "缺幂等键", "要带 Idempotency-Key",
                      "每次新请求自己生成一个;超时重发时带同一个,就不会跑第二遍、也不会多花一次钱")
        try:
            体 = await request.json()
        except ValueError:
            体 = None
        if not isinstance(体, dict) or not isinstance(体.get("输入", {}), dict):
            raise _拒(422, "VALIDATION", "参数不对", "请求体要是 JSON,形如 {\"输入\": {...}}", "照「访问入口」页上的样例改")
        键 = f"open:{r['id']}:{idempotency_key}"[:200]
        with 事务() as c:
            老 = c.execute(text("select target_ref from jobs where project_id=:p and idempotency_key=:k"),
                          {"p": r["project_id"], "k": 键}).mappings().first()
            if not 老:
                花了, 算不出 = _今天花了(c, r["project_id"], r["id"])
                if 算不出:
                    raise _拒(429, "COST_UNKNOWN", "超额", f"今天有 {算不出} 笔花费算不出金额(模型不在价目表里),上限没法判",
                              "请后台的人把那个模型登记进价目表;在那之前这把密钥今天不再受理")
                if 花了 >= Decimal(r["daily_cap_amount"]):
                    raise _拒(429, "DAILY_CAP_REACHED", "超额",
                              f"这把访问密钥今天已经花了 {花了:.4f} {r['currency']},到了上限 {r['daily_cap_amount']}",
                              "明天(东八区零点)再调;要更大的额度找后台的人")
            w = c.execute(text("""select a.workflow_id, w.name from applications a join workflows w
                                     on w.project_id=a.project_id and w.id=a.workflow_id
                                   where a.project_id=:p and a.id=:a and a.archived_at is null"""),
                          {"p": r["project_id"], "a": aid}).mappings().first()
            生产 = w and WF._生产版本(c, r["project_id"], w["workflow_id"])
            if not 生产:
                raise _拒(409, "NOT_IN_PRODUCTION", "没上生产", "这个应用还没有生产版本",
                          "要先在后台「版本与发布」审核并发布到生产;草稿和候选版本不对外")
            v = c.execute(text("select * from workflow_versions where project_id=:p and id=:i"),
                          {"p": r["project_id"], "i": 生产["版本id"]}).mappings().first()
            来源 = {"kind": "workflow_version", "id": w["workflow_id"], "version_id": 生产["版本id"],
                    "version_no": v["version_no"], "环境": "production", "清单id": 生产["清单id"],
                    "发起": "访问 API", "密钥id": r["id"], "密钥名": r["name"]}
            回 = WF._受理运行(c, 本人, r["project_id"], WF._版本定义(v), 来源, 体.get("输入") or {}, 键)
            重放 = str(回.get("note", "")).startswith("同一个幂等键")
    except _拒 as e:
        _记一笔(r, "发起运行", e.结果 or e.code, e.http, 说明=e.message)
        raise _拒成错(e)
    _记一笔(r, "发起运行", "重放" if 重放 else "受理", 202, 运行=回["resource_id"])
    return {"运行编号": 回["resource_id"], "状态": "排队中" if not 重放 else "这是之前那一次(同一个幂等键,没跑第二遍)",
            "跑的版本": v["version_no"], "查结果": f"{对外}/runs/{回['resource_id']}"}


_对外状态 = {"queued": "排队中", "running": "在跑", "waiting_approval": "在等人核对",
            "waiting_external": "在等澜绣执行", "succeeded": "已完成", "failed": "失败",
            "cancelled": "已取消", "incomplete": "没做完"}


@router.get(对外 + "/runs/{rid}")
def 对外查结果(rid: str, authorization: str = Header(default=None)):
    """查一次运行。**只查得到这把密钥发起的** —— 别的密钥(哪怕同一个人发的)查不到,回 404 不说它存不存在。"""
    r = None
    try:
        with 连接() as c:
            r = _认密钥(c, authorization)
            _过闸(c, r)
            e = c.execute(text("""select * from execution_runs where project_id=:p and id=:i
                                    and definition_ref->>'密钥id' = :k"""),
                          {"p": r["project_id"], "i": rid, "k": r["id"]}).mappings().first()
            if not e:
                raise _拒(404, "NOT_FOUND", "查不到", "这把访问密钥发起的运行里没有这一条", "核对运行编号;只查得到自己发起的")
            步 = [dict(s) for s in c.execute(text("""select node_id, status, error_detail from run_steps
                                                    where project_id=:p and execution_run_id=:i"""),
                                             {"p": r["project_id"], "i": rid}).mappings()]
    except _拒 as x:
        _记一笔(r, "查结果", x.结果 or x.code, x.http, 说明=x.message)
        raise _拒成错(x)
    _记一笔(r, "查结果", "查询", 200, 运行=rid)
    等 = {"种类": "human"} if e["status"] == "waiting_approval" else ({"种类": "external"} if e["status"] == "waiting_external" else None)
    结论 = WF._业务结论(e["status"], e["completion_reason"], 步, 等)
    出 = e["output_ref"]
    if isinstance(出, str):
        try:
            出 = json.loads(出)
        except ValueError:
            pass
    终 = e["status"] in ("succeeded", "failed", "cancelled", "incomplete")
    return {"运行编号": rid, "状态": _对外状态.get(e["status"], e["status"]), "跑完了吗": 终,
            "在等人核对": e["status"] == "waiting_approval",
            "结果": 出 if e["status"] in ("succeeded", "incomplete") else None,
            "结论": 结论.get("结论"), "说明": 结论.get("说明"),
            "失败原因": 结论.get("说明") if e["status"] == "failed" else None}
