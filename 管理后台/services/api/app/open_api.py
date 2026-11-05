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
    # 两路账:① 工作流运行(按运行的 trace 连回这把密钥)② 聊天(每轮一笔,caller 记成「访问密钥:<id>」)
    r = c.execute(text("""
        select coalesce(sum(u.amount) filter (where u.amount_known), 0) 花了,
               count(*) filter (where not u.amount_known) 算不出
          from usage_ledger u
         where u.project_id=:p and u.created_at >= :起
           and (u.caller = :ck
                or exists (select 1 from execution_runs e where e.project_id=u.project_id and e.trace_id=u.trace_id
                             and e.definition_ref->>'密钥id' = :k))"""),
        {"p": project_id, "k": kid, "ck": f"访问密钥:{kid}", "起": _今天起点()}).mappings().first()
    return Decimal(r["花了"] or 0), int(r["算不出"] or 0)


def _键的样子(r, 花了=None, 算不出=None):
    return {"id": r["id"], "名字": r["name"], "开头": r["prefix_code"] + "…", "应用id": r["application_id"],
            "聊天助手id": r["chat_assistant_id"],
            "每天上限": float(r["daily_cap_amount"]), "币种": r["currency"], "发的人": r["created_by"],
            "发于": r["created_at"].isoformat() if r["created_at"] else None,
            "最后一次用": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "吊销于": r["revoked_at"].isoformat() if r["revoked_at"] else None, "吊销人": r["revoked_by"],
            "有效期至": r["expires_at"].isoformat() if r.get("expires_at") else None,
            "过期了吗": bool(r.get("expires_at") and r["expires_at"] <= datetime.now(timezone.utc)),
            "还剩几天": (max(0, (r["expires_at"] - datetime.now(timezone.utc)).days) if r.get("expires_at") else None),
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


# 有效期(用户 11-04 拍:必选、最长 1 年;页面默认 90)。**只收这几档** —— 任意天数会让「最多活一年」靠每个人自觉
有效期档 = (30, 90, 180, 365)
轮换宽限小时 = 24       # 轮换后旧钥还能用多久:给对方把新钥换上去的时间


def _有效期(体):
    v = 体.get("有效期天数")
    try:
        天 = int(v)
    except (TypeError, ValueError):
        天 = None
    if 天 not in 有效期档:
        raise _错(422, "VALIDATION", f"有效期要从 {list(有效期档)} 天里选", "页面默认 90 天;最长 1 年(用户 11-04 拍)",
                  field_errors={"有效期天数": f"只收 {list(有效期档)}"})
    return 天


def _发一把(c, project_id, me, 名, 上限, 天数, 应用id=None, 助手id=None):
    """建一行密钥 → (id, 原文)。上限、项目日预算、有效期由调用方先判;**原文只从这里返回一次**。"""
    原文 = 密钥开头 + secrets.token_hex(20)
    kid = WF._新id("ak")
    c.execute(text("""insert into access_keys (id, organization_id, project_id, application_id, chat_assistant_id, name,
                          prefix_code, lookup_hash, daily_cap_amount, currency, created_at, created_by, updated_at, revision,
                          expires_at)
                      values (:i,:o,:p,:a,:ca,:n,:pc,:h,:cap,:cur, now(), :by, now(), 1, now() + make_interval(days => :d))"""),
              {"i": kid, "o": me.org_id, "p": project_id, "a": 应用id, "ca": 助手id, "n": 名, "pc": 原文[:13],
               "h": _哈希(原文), "cap": 上限, "cur": 币种, "by": me.user_id, "d": 天数})
    WF._审计(c, me, "access_key.issue", {"密钥": kid, "应用": 应用id, "聊天助手": 助手id, "名字": 名, "每天上限": str(上限),
                                         "有效期天数": 天数})
    return kid, 原文


def _判上限(c, project_id, 上限):
    预 = _项目日预算(c, project_id)
    if 预:
        if (预["currency"] or "").upper() != 币种:
            raise _错(422, "VALIDATION", f"项目每日预算是 {预['currency']},而花费按 {币种} 记,比不了",
                      "把项目每日预算改成美元,或者先不设项目预算", field_errors={"每天上限": "币种对不上"})
        if 上限 > Decimal(预["limit_amount"]):
            raise _错(422, "VALIDATION", f"每天上限 {上限} 超过了项目每日预算 {预['limit_amount']}",
                      "改小,或者先调高项目预算", field_errors={"每天上限": "超过项目每日预算"})


@router.post(前缀 + "/workflows/{wid}/access-keys", status_code=201)
async def 发密钥(project_id: str, wid: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{名字, 每天上限}` → 原文(只这一次)。**上限必填**;设了项目每日预算的话不许超过它。"""
    体 = await request.json()
    名 = (体.get("名字") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION", "名字不能空", "写清这把密钥给谁用,比如「门店小程序」", field_errors={"名字": "必填"})
    上限 = _金额(体.get("每天上限"), "每天上限")
    天数 = _有效期(体)
    with 事务() as c:
        w = c.execute(text("select name from workflows where project_id=:p and id=:w and archived_at is null"),
                      {"p": project_id, "w": wid}).mappings().first()
        if not w:
            raise _错(404, "NOT_FOUND", "没有这条工作流", "回列表重新进入")
        _判上限(c, project_id, 上限)
        aid = WF._工作流应用(c, project_id, wid, me, w["name"])
        kid, 原文 = _发一把(c, project_id, me, 名, 上限, 天数, 应用id=aid)
    return {"id": kid, "名字": 名, "原文": 原文, "开头": 原文[:13] + "…", "应用id": aid,
            "每天上限": float(上限), "币种": 币种, "调用地址": f"{对外}/apps/{aid}/runs", "有效期天数": 天数,
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


@router.post(前缀 + "/access-keys/{kid}/rotate", status_code=201)
async def 轮换(project_id: str, kid: str, request: Request,
             if_match: str = Header(default=None, alias="If-Match"),
             me: 身份 = Depends(要权限("配置密钥与预算"))):
    """`{有效期天数}`(带 If-Match)→ 一把**绑同一个应用 / 聊天助手、同样上限**的新钥(原文只这一次);
    旧的有效期缩到 24 小时后(原本更早到期的不拉长),给对方把新钥换上去。吊销了 / 已过期的不能轮换 —— 重发。"""
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把列表里这把密钥的 revision 放进 If-Match 头")
    体 = await request.json() if await request.body() else {}
    天数 = _有效期(体)
    with 事务() as c:
        r = c.execute(text("select * from access_keys where project_id=:p and id=:i for update"),
                      {"p": project_id, "i": kid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这把密钥", "回列表重新进入")
        if str(r["revision"]) != str(if_match).strip('"'):
            raise _错(409, "REVISION_CONFLICT", "这把密钥已经被改过了", "刷新看一眼再轮换")
        if r["revoked_at"] or r["expires_at"] <= datetime.now(timezone.utc):
            raise _错(409, "NOT_ROTATABLE", "这把密钥已经" + ("吊销" if r["revoked_at"] else "过期") + "了,不能轮换",
                      "直接重发一把新的 —— 轮换是给还在用的那把留切换时间的")
        _判上限(c, project_id, Decimal(r["daily_cap_amount"]))
        新id, 原文 = _发一把(c, project_id, me, r["name"], Decimal(r["daily_cap_amount"]), 天数,
                         应用id=r["application_id"], 助手id=r["chat_assistant_id"])
        旧到期 = c.execute(text(f"""update access_keys set expires_at = least(expires_at, now() + interval '{轮换宽限小时} hours'),
                                     updated_at=now(), revision=revision+1
                               where project_id=:p and id=:i returning expires_at"""),
                          {"p": project_id, "i": kid}).scalar()
        WF._审计(c, me, "access_key.rotate", {"旧密钥": kid, "新密钥": 新id, "旧的到期": 旧到期.isoformat()})
    return {"新的": {"id": 新id, "原文": 原文, "开头": 原文[:13] + "…", "有效期天数": 天数},
            "旧的": {"id": kid, "有效期至": 旧到期.isoformat()},
            "note": (f"**新钥原文只这一次看得到**。旧的还能用到 {旧到期:%m-%d %H:%M}(最多 {轮换宽限小时} 小时),"
                     "让对方在那之前换上新钥;到点自动拒,不用再手动吊销")}


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
    if r["expires_at"] <= datetime.now(timezone.utc):
        # Dify 对标 C05:过期 → 拒绝并记原因(调用记录里记「已过期」),不建任何运行
        raise _拒(401, "ACCESS_KEY_EXPIRED", "已过期", f"这把访问密钥 {r['expires_at']:%Y-%m-%d %H:%M} 已经过期",
                  "找后台的人轮换一把新的(轮换后旧的还能用 24 小时,给你换上去)")
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
            if 老:
                # 方案 C06(Dify 四页对标 §6.3):**同一个幂等键、参数不同 → 冲突**,不默默返回旧的那一次 ——
                # 对方重复用了编号而参数变了,拿到的会是一个答非所问的旧结果,而它看起来完全正常
                原 = c.execute(text("select input_snapshot from execution_runs where project_id=:p and idempotency_key=:k"),
                              {"p": r["project_id"], "k": 键}).scalar()
                if isinstance(原, str):
                    原 = json.loads(原)
                if 原 is not None and (原 or {}) != (体.get("输入") or {}):
                    raise _拒(409, "IDEMPOTENCY_CONFLICT", "幂等键冲突",
                              "这个幂等键之前用过,而那一次的输入和这次不一样",
                              "新请求换一个新的幂等键;只有超时重发同一个请求时才带同一个")
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
            "cancelled": "已取消", "incomplete": "没做完", "cancel_requested": "取消请求中",
            "paused": "暂停中", "pause_requested": "暂停请求中"}


def _我的运行(c, r, rid, 锁=False):
    """这把密钥发起的那一次运行;别的(哪怕同一个人发的)→ 404,不说它存不存在。"""
    e = c.execute(text(f"""select * from execution_runs where project_id=:p and id=:i
                            and definition_ref->>'密钥id' = :k {'for update' if 锁 else ''}"""),
                  {"p": r["project_id"], "i": rid, "k": r["id"]}).mappings().first()
    if not e:
        raise _拒(404, "NOT_FOUND", "查不到", "这把访问密钥发起的运行里没有这一条", "核对运行编号;只查得到自己发起的")
    return e


@router.get(对外 + "/runs/{rid}/events")
def 对外事件(rid: str, authorization: str = Header(default=None), after_seq: int = 0, limit: int = 200):
    """订阅进度(Dify 对标 §6.3 / C07):**按事件序号续传**。断网不等于任务失败 —— 连回来带上
    「下一次从这儿拉」那个 after_seq 接着拉,一条不重、一条不漏;运行本身不会因为没人在听而停。
    做成一轮一请求的补拉(和后台那条同一个理由):**每一轮都重新过密钥的闸**,密钥吊销了 / 过期了下一轮就拒。
    **只给事件类型、步骤、时间,不给内容** —— 结果在 GET /runs/{id};步骤里的工具参数是内部的东西。"""
    r = None
    if after_seq < 0 or not (1 <= limit <= 1000):
        raise _错(422, "VALIDATION", "after_seq 不能小于 0,limit 要在 1–1000", "after_seq 用上一次返回的「下一次从这儿拉」;第一次从 0 开始", field_errors={"after_seq": "≥ 0", "limit": "1–1000"})
    try:
        with 连接() as c:
            r = _认密钥(c, authorization)
            _过闸(c, r)
            e = _我的运行(c, r, rid)
            行 = [dict(x) for x in c.execute(text("""select seq, event_type, step_id, occurred_at from run_events
                                                    where project_id=:p and execution_run_id=:i and seq > :a
                                                    order by seq limit :lim"""),
                                           {"p": r["project_id"], "i": rid, "a": after_seq, "lim": limit}).mappings()]
            最大 = c.execute(text("select coalesce(max(seq), 0) from run_events where project_id=:p and execution_run_id=:i"),
                           {"p": r["project_id"], "i": rid}).scalar()
    except _拒 as x:
        _记一笔(r, "订阅进度", x.结果 or x.code, x.http, 说明=x.message)
        raise _拒成错(x)
    _记一笔(r, "订阅进度", "查询", 200, 运行=rid)
    终 = e["status"] in ("succeeded", "failed", "cancelled", "incomplete")
    return {"运行编号": rid, "状态": _对外状态.get(e["status"], e["status"]), "跑完了吗": 终,
            "事件": [{"序号": x["seq"], "类型": x["event_type"], "步骤": x["step_id"],
                    "发生于": x["occurred_at"].isoformat() if x["occurred_at"] else None} for x in 行],
            "after_seq": after_seq, "最新序号": 最大, "下一次从这儿拉": (行[-1]["seq"] if 行 else after_seq),
            "还有吗": bool(行) and 行[-1]["seq"] < 最大,
            "note": ("断了就带 `下一次从这儿拉` 那个数作为 after_seq 接着拉;**连接断了不等于运行失败**,"
                     "状态以 `状态` / GET /runs/{id} 为准" + ("" if 行 or 终 else "。这一轮没有新事件,隔几秒再拉"))}


@router.post(对外 + "/runs/{rid}/cancel", status_code=202)
def 对外取消(rid: str, authorization: str = Header(default=None)):
    """取消这把密钥发起的一次运行(Dify 对标 §6.3)。**规则和后台那个取消口是同一份**(runctl.取消一次):
    已结束的保留真实终态、没开跑的直接取消、在跑的是「请求取消」。
    **说清已经发生的写入**:这次运行已经让澜绣执行过的业务写入,取消不回来 —— 逐条列出来,不承诺撤销。"""
    import runctl as RC
    r = None
    try:
        with 事务() as c:
            r = _认密钥(c, authorization)
            本人 = _过闸(c, r)
            e = _我的运行(c, r, rid, 锁=True)
            出 = RC.取消一次(c, r["project_id"], rid, dict(e), e["revision"], 谁=f"访问密钥:{r['id']}")
            写了 = [dict(x) for x in c.execute(text("""select tool_name, acked_at from bridge_calls
                                                     where project_id=:p and execution_run_id=:i and status='已执行'
                                                     order by acked_at"""), {"p": r["project_id"], "i": rid}).mappings()]
    except _拒 as x:
        _记一笔(r, "取消", x.结果 or x.code, x.http, 说明=x.message)
        raise _拒成错(x)
    _记一笔(r, "取消", "取消" if 出.get("改了吗") else "没改", 202, 运行=rid, 说明=出.get("note"))
    return {"运行编号": rid, "状态": _对外状态.get(出["status"], 出["status"]), "改了吗": 出.get("改了吗"),
            "已经发生的写入": [{"工具": w["tool_name"], "什么时候": w["acked_at"].isoformat() if w["acked_at"] else None}
                           for w in 写了],
            "note": (出.get("note", "") + (f"。⚠️ 这次运行已经让澜绣执行过 {len(写了)} 次业务写入(上面逐条列着),**取消撤不回它们**"
                                          if 写了 else "。这次运行还没有让澜绣执行过任何业务写入"))}


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


# ══ 聊天助手那一半(11-03 第二步)═══════════════════════════════════════════════
# 管理后台跑不了聊天对话,所以核完密钥 / 限量 / 花费 / 身份之后,转给聊天站的内部口(agentsite/internal_call.py)跑一轮。
# 那一轮**写工具不挂**:机器调的不许直接写(网页上那张「动手前先确认」的卡,API 那头没人看)。

import os as _os
import subprocess as _sp
import chat_assistants_api as CA

聊天站 = _os.environ.get("LANXIU_AGENTSITE_URL", "http://127.0.0.1:8770")
单轮最多秒 = 240           # 一轮聊天(含难题分流、技能)常见 20~90 秒;再长多半是卡住了


def _内部凭证():
    路 = _os.environ.get("LANXIU_INTERNAL_FILE") or _os.path.expanduser("~/.lanxiu/internal-call")
    try:
        with open(路, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _问聊天站(体):
    """→ (http 码, dict)。走 curl(这台机器 Python 的 TLS 会被拦,本地 http 也统一走一处)。凭证只进 curl 的参数。"""
    凭 = _内部凭证()
    if not 凭:
        return None, {"error": "内部通道没开:本机没有凭证文件(~/.lanxiu/internal-call)"}
    try:
        r = _sp.run(["curl", "-sS", "-m", str(单轮最多秒), "-X", "POST", 聊天站.rstrip("/") + "/internal/chat",
                     "-H", "Content-Type: application/json", "-H", f"X-Lanxiu-Internal: {凭}",
                     "--data-binary", "@-", "-w", "\n%{http_code}"],
                    input=json.dumps(体, ensure_ascii=False), capture_output=True, text=True, timeout=单轮最多秒 + 10)
    except Exception as e:
        return None, {"error": f"调聊天站起不来:{type(e).__name__}"}
    if r.returncode != 0:
        return None, {"error": f"连不上聊天站(curl 退 {r.returncode})"}
    正文, _, 码 = r.stdout.rpartition("\n")
    try:
        return 码.strip(), json.loads(正文 or "null") or {}
    except ValueError:
        return 码.strip(), {"error": 正文[:200]}


@router.get(前缀 + "/chat-assistants/{cid}/access-keys")
def 聊天助手的密钥(project_id: str, cid: str, me: 身份 = Depends(要权限("配置密钥与预算"))):
    with 连接() as c:
        行 = c.execute(text("""select * from access_keys where project_id=:p and chat_assistant_id=:a
                                order by created_at desc"""), {"p": project_id, "a": cid}).mappings().all()
        密钥们 = [_键的样子(r, *_今天花了(c, project_id, r["id"])) for r in 行]
        a = c.execute(text("select role_key, production_version_no from chat_assistants where project_id=:p and id=:i"),
                      {"p": project_id, "i": cid}).mappings().first()
    if not a:
        # 11-05 跨项目攻击判据扫出来的:原来这个项目里没有这个助手也回 200 + 一个拼好的调用地址 —— 不漏数据,但会让人以为它存在
        raise _错(404, "NOT_FOUND", "这个项目里没有这个聊天助手", "回聊天助手列表重新选")
    return {"条数": len(密钥们), "密钥": 密钥们, "调用地址": f"{对外}/chat-assistants/{cid}/messages",
            "生产版本号": a and a["production_version_no"], "聊天站读后台配置吗": bool(a and CA._接线(a["role_key"])[0]),
            "note": "原文只在发出那一刻显示一次;**API 调的这一轮写工具不挂** —— 只能查、不能改,要改的会说「它想做什么」"}


@router.post(前缀 + "/chat-assistants/{cid}/access-keys", status_code=201)
async def 给聊天助手发密钥(project_id: str, cid: str, request: Request, me: 身份 = Depends(要权限("配置密钥与预算"))):
    体 = await request.json()
    名 = (体.get("名字") or "").strip()
    if not 名:
        raise _错(422, "VALIDATION", "名字不能空", "写清这把密钥给谁用,比如「企业微信机器人」", field_errors={"名字": "必填"})
    上限 = _金额(体.get("每天上限"), "每天上限")
    天数 = _有效期(体)
    with 事务() as c:
        if not c.execute(text("select 1 from chat_assistants where project_id=:p and id=:i"), {"p": project_id, "i": cid}).first():
            raise _错(404, "NOT_FOUND", "没有这个聊天助手", "回列表重新进入")
        _判上限(c, project_id, 上限)
        kid, 原文 = _发一把(c, project_id, me, 名, 上限, 天数, 助手id=cid)
    return {"id": kid, "名字": 名, "原文": 原文, "开头": 原文[:13] + "…", "聊天助手id": cid,
            "每天上限": float(上限), "币种": 币种, "调用地址": f"{对外}/chat-assistants/{cid}/messages", "有效期天数": 天数,
            "note": "**这是唯一一次看得到原文** —— 现在就存好;库里只有哈希,谁都找不回,忘了就吊销重发"}


def _记聊天账(r, 回, 本人):
    """一轮一笔进用量账,挂在管理后台自己建的一条 trace 上(trace_id 是真外键:查不到出处的钱和真的一样);
    聊天站那一轮的编号记在 trace.request_id 上。花费算不出 → amount_known=false,不写 0。"""
    花 = 回.get("花费usd")
    with 事务() as c:
        tid = WF._新id("tr")
        c.execute(text("""insert into traces (id, organization_id, project_id, created_at, created_by, session_id,
                              request_id, entry_kind, started_at, ended_at)
                          values (:i,:o,:p, now(), :by, :s, :rq, '访问 API 聊天', now(), now())"""),
                  {"i": tid, "o": r["organization_id"], "p": r["project_id"], "by": 本人.user_id,
                   "s": 回.get("会话"), "rq": 回.get("trace_id")})
        c.execute(text("""insert into usage_ledger (id, organization_id, project_id, event_key, trace_id, resource,
                              quantity, unit, currency, amount, amount_known, source, caller, created_at, created_by)
                          values (:i,:o,:p,:ek,:t,'chat',1,'turn','USD',:a,:k,'live',:ca, now(), :by)
                          on conflict (project_id, event_key) do nothing"""),
                  {"i": WF._新id("ul"), "o": r["organization_id"], "p": r["project_id"],
                   "ek": f"open-chat:{r['id']}:{回.get('trace_id') or tid}", "t": tid,
                   "a": 花, "k": 花 is not None, "ca": f"访问密钥:{r['id']}", "by": 本人.user_id})


@router.post(对外 + "/chat-assistants/{cid}/messages")
async def 对外聊天(cid: str, request: Request, authorization: str = Header(default=None)):
    """问一轮。入参 `{问题, 会话?}` → `{回答, 会话, 用了哪一版}`。跑的是这个助手**生产指着的那一版**;
    以发密钥那个人绑的澜绣工号取数;**写工具不挂**。会话归这把密钥:别的密钥(哪怕同一个人发的)续不了。"""
    r = None
    try:
        with 连接() as c:
            r = _认密钥(c, authorization)
            本人 = _过闸(c, r)
            if r["chat_assistant_id"] != cid:
                raise _拒(403, "WRONG_APP", "应用不对", "这把访问密钥不是这个聊天助手的", "一把密钥只能调它绑的那一个")
            花了, 算不出 = _今天花了(c, r["project_id"], r["id"])
            if 算不出:
                raise _拒(429, "COST_UNKNOWN", "超额", f"今天有 {算不出} 笔花费算不出金额,上限没法判",
                          "请后台的人查一下那几轮的花费;在那之前这把密钥今天不再受理")
            if 花了 >= Decimal(r["daily_cap_amount"]):
                raise _拒(429, "DAILY_CAP_REACHED", "超额",
                          f"这把访问密钥今天已经花了 {花了:.4f} {r['currency']},到了上限 {r['daily_cap_amount']}",
                          "明天(东八区零点)再调;要更大的额度找后台的人")
            a = c.execute(text("select role_key, production_version_no from chat_assistants where project_id=:p and id=:i"),
                          {"p": r["project_id"], "i": cid}).mappings().first()
            if not a or a["production_version_no"] is None:
                raise _拒(409, "NOT_IN_PRODUCTION", "没上生产", "这个聊天助手还没有生产版本",
                          "先在后台审核上生产;草稿和没上生产的版本不对外")
            if not CA._接线(a["role_key"])[0]:
                raise _拒(409, "NOT_WIRED", "没接线", "这个角色聊天站还没读后台的配置",
                          "现在只有店长助手接上了;这个角色接上之前,API 跑出来的和后台配的不是一回事")
            工号 = c.execute(text("""select lanxiu_staff_code from staff_bindings where project_id=:p and user_id=:u
                                     and archived_at is null"""), {"p": r["project_id"], "u": 本人.user_id}).scalar()
            if not 工号:
                raise _拒(403, "NOT_BOUND", "没权限", f"发密钥的账号 {本人.user_id} 没有绑澜绣工号,聊天站不知道以谁的身份取数",
                          "请管理员在「账号绑定」里给他绑上")
        try:
            体 = await request.json()
        except ValueError:
            体 = None
        问 = (体 or {}).get("问题") if isinstance(体, dict) else None
        if not isinstance(问, str) or not 问.strip():
            raise _拒(422, "VALIDATION", "参数不对", "请求体要是 JSON,形如 {\"问题\": \"…\", \"会话\": null}", "照「访问入口」页上的样例改")
        码, 回 = _问聊天站({"角色键": a["role_key"], "问题": 问.strip(), "会话": (体 or {}).get("会话"),
                         "密钥id": r["id"], "澜绣工号": 工号})
        if 码 is None:
            raise _拒(502, "CHAT_UNREACHABLE", "聊天站不通", 回.get("error") or "聊天站不通", "稍后再试;一直不通就找后台的人")
        if 码 != "200":
            映射 = {"403": (403, "SESSION_NOT_YOURS" if 回.get("code") == "SESSION_NOT_YOURS" else (回.get("code") or "CHAT_DENIED"))}
            http, code = 映射.get(码, (502, "CHAT_FAILED"))
            raise _拒(http, code, "聊天站拒了", 回.get("error") or f"聊天站回 {码}", "会话续不了就开一条新的(不带会话)")
    except _拒 as e:
        _记一笔(r, "聊天", e.结果 or e.code, e.http, 说明=e.message)
        raise _拒成错(e)
    _记聊天账(r, 回, 本人)
    _记一笔(r, "聊天", "受理", 200, 说明=f"会话 {回.get('会话')}")
    return {"回答": 回.get("回答"), "会话": 回.get("会话"), "用了哪一版": 回.get("用了哪一版"),
            "写工具": "这一轮没挂 —— API 只能查,不能改;要改的事回答里会说「它想做什么」,由人在聊天页或后台办"}


# ══ 接入文档(Dify 对标 §6.3「接入文档按发布 schema 生成」,11-04)═══════════════════════════════
# 字段表 / 请求示例**从生产那一版的 input_schema / output_schema 现生成** —— 手写的文档会和发布出去的那一版对不上,
# 而对不上的表现是对方按文档填了字段、调用照样失败。错误码的说明是人写的(要说清什么时候会遇到、怎么办),
# 但**哪些码存在不靠人记**:test_access_doc 扫这个文件里每一处 `_拒(...)`,少一条说明就红。
对外错误码 = {
    "NO_ACCESS_KEY": (401, "没带密钥,或者不是 Bearer lx-app-… 这个格式", "请求头带 Authorization: Bearer <密钥原文>"),
    "UNKNOWN_ACCESS_KEY": (401, "密钥认不出(抄错了 / 不是这个系统发的)", "核对原文;找后台的人重发"),
    "ACCESS_KEY_REVOKED": (401, "密钥被吊销了", "找后台的人重发一把"),
    "ACCESS_KEY_EXPIRED": (401, "密钥过期了(有效期最长 1 年)", "找后台的人轮换:新钥发给你,旧的还能用 24 小时"),
    "RATE_LIMITED": (429, "这把密钥一分钟内调了 30 次(查结果、拉事件也算)", "隔一分钟再调;轮询请隔几秒"),
    "DAILY_CAP_REACHED": (429, "这把密钥今天花到上限了", "明天再调,或者找后台的人调整上限"),
    "COST_UNKNOWN": (429, "今天有算不出金额的花费,这把今天不再受理", "找后台的人核一下价目表"),
    "ISSUER_GONE": (403, "发这把密钥的人已经不是项目成员", "找后台的人用在职的账号重发"),
    "ISSUER_FORBIDDEN": (403, "发这把密钥的人现在没有发起运行的权限", "找管理员核一下他的角色"),
    "NOT_BOUND": (403, "发密钥的人没绑澜绣工号(聊天助手那种要按工号取数)", "找后台的人先绑工号"),
    "WRONG_APP": (403, "拿这把密钥去调别的应用 / 助手了 —— 一把只绑一个", "用发给这个应用的那把"),
    "NOT_IN_PRODUCTION": (409, "这个应用还没有生产版本", "等后台审核发布到生产;草稿和候选版本不对外"),
    "NOT_WIRED": (409, "这个聊天助手的角色聊天站还没接上后台配置", "找后台的人确认接线"),
    "IDEMPOTENCY_KEY_REQUIRED": (409, "发起没带 Idempotency-Key", "每次发起自己生成一个编号放进请求头;网断了重发带同一个"),
    "IDEMPOTENCY_CONFLICT": (409, "同一个 Idempotency-Key、参数不一样", "这是另一件事 —— 换一个新的编号"),
    "NOT_FOUND": (404, "查不到(只查得到这把密钥自己发起的)", "核对运行编号"),
    "VALIDATION": (422, "请求体的字段不合格", "看返回里的 field_errors"),
    "CHAT_UNREACHABLE": (502, "聊天站这一轮没跑起来", "过一会儿再问;一直这样找后台的人"),
}


def _示例(schema, 深=0):
    """按 JSON Schema 造一个看得懂的示例值(只用来填文档里的请求示例,不拿去跑)。"""
    s = schema or {}
    if "enum" in s and s["enum"]:
        return s["enum"][0]
    t = s.get("type")
    if t == "object" or "properties" in s:
        return {k: _示例(v, 深 + 1) for k, v in (s.get("properties") or {}).items()} if 深 < 3 else {}
    if t == "array":
        return [_示例(s.get("items") or {}, 深 + 1)] if 深 < 3 else []
    return {"integer": 1, "number": 1.5, "boolean": True}.get(t, s.get("description") or "……")


def _字段表(schema):
    s = schema or {}
    要 = set(s.get("required") or [])
    return [{"字段": k, "类型": (v or {}).get("type") or ("枚举" if (v or {}).get("enum") else "?"),
             "必填": k in 要, "可选值": (v or {}).get("enum"), "说明": (v or {}).get("description") or (v or {}).get("title")}
            for k, v in (s.get("properties") or {}).items()]


@router.get(前缀 + "/workflows/{wid}/access-doc")
def 接入文档(project_id: str, wid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """这条工作流对外的接入文档:**按生产那一版的 input_schema / output_schema 现生成**(字段表、请求示例、返回示例),
    外加四个对外接口、状态、错误码。没上生产就没有文档 —— 草稿和候选版本不对外,写了也调不通。"""
    with 连接() as c:
        aid = WF._工作流应用(c, project_id, wid)
        生产 = WF._生产版本(c, project_id, wid)
        v = c.execute(text("""select version_no, input_schema, output_schema, logical_hash from workflow_versions
                               where project_id=:p and id=:i"""), {"p": project_id, "i": 生产["版本id"]}).mappings().first() if 生产 else None
    if not (aid and v):
        return {"有文档吗": False,
                "为什么": "这条工作流还没有生产版本 —— 对外只跑生产那一版,先在「版本与发布」审核并发布到生产"}
    入, 出 = v["input_schema"] or {}, v["output_schema"] or {}
    入表, 出表 = _字段表(入), _字段表(出)
    请求例 = {"输入": _示例(入)}
    行 = lambda t: "\n".join("| " + " | ".join(str(x if x is not None else "—") for x in r) + " |" for r in t)
    md = f"""# 接入文档 · 应用 `{aid}`(按生产 v{v['version_no']} 生成)

> 这份文档是**按生产那一版的定义现生成的**(定义哈希 `{(v['logical_hash'] or '')[:12]}`)。生产换版本之后重新打开这页,字段会跟着变。

## 认证
每个请求带 `Authorization: Bearer <访问密钥原文>`。密钥有有效期(最长 1 年),到期找后台轮换。
限量:每把每分钟 30 次(查结果、拉事件也算);每天花费到上限就拒。以**发密钥的那个人**的身份跑,他的权限每次都重核。

## 1. 发起一次运行
`POST {对外}/apps/{aid}/runs` · 请求头加 `Idempotency-Key: <你自己生成的编号>`(网断了重发带同一个,不会跑两遍)

输入字段(`输入` 里):

| 字段 | 类型 | 必填 | 可选值 | 说明 |
|---|---|---|---|---|
{行([(x["字段"], x["类型"], "是" if x["必填"] else "否", "、".join(map(str, x["可选值"])) if x["可选值"] else None, x["说明"]) for x in 入表]) or "| (这一版没有声明输入字段) | | | | |"}

请求示例:
```json
{json.dumps(请求例, ensure_ascii=False, indent=2)}
```
返回 `202 {{"运行编号": "xr_…", "状态": "排队中", "查结果": "{对外}/runs/xr_…"}}` —— **202 只是收下了,不是做完了**。

## 2. 查结果
`GET {对外}/runs/{{运行编号}}` → `状态` / `跑完了吗` / `结果`。跑完时的 `结果`:

| 字段 | 类型 | 说明 |
|---|---|---|
{行([(x["字段"], x["类型"], x["说明"]) for x in 出表]) or "| (这一版没有声明输出字段) | | |"}

## 3. 订阅进度(断了接着拉)
`GET {对外}/runs/{{运行编号}}/events?after_seq=0` → `事件`(序号 / 类型 / 步骤 / 时间)、`下一次从这儿拉`、`还有吗`。
断了就带上一次的 `下一次从这儿拉` 作为 `after_seq` 接着拉,不重不漏。**连接断了不等于运行失败**,以 `状态` 为准。

## 4. 取消
`POST {对外}/runs/{{运行编号}}/cancel` → 已结束的保留真实终态;在跑的是「取消请求中」。
返回里逐条列出**已经发生的业务写入** —— 取消撤不回它们。

## 状态
{"、".join(dict.fromkeys(_对外状态.values()))}。HTTP 200/202、模型说「已完成」都不是业务完成的证据 —— 以 `状态` 为准。

## 错误码(返回体 `code`)
| code | HTTP | 什么时候 | 怎么办 |
|---|---|---|---|
{行([(k, h, 何, 办) for k, (h, 何, 办) in 对外错误码.items()])}
"""
    return {"有文档吗": True, "应用id": aid, "生产版本号": v["version_no"], "定义哈希": v["logical_hash"],
            "输入字段": 入表, "输出字段": 出表, "请求示例": 请求例, "markdown": md}
