# -*- coding: utf-8 -*-
"""上线验收(2026-11-12,执行手册 W41;业务拍板 11-12 第一条「做完 = 试点两周 + 十条验收签字 + 费用上限」)。

## 这一页答的是一个问题:**做完了没有**

三项都「通过」才算做完。三项的口径在 `acceptance_flow.py`(纯函数,这里只取数):
  ① 十条全签:PRD 13.4 的 S1–S10,每条结论「通过」并由店长签字
  ② 试点满两周:起算日 = 真数据导入日。**没设就是「未开始」,不默认成今天**
  ③ 月费用未超上限(150 美元,拍板第十三条):**澜绣项目读聊天站的门店用量账**(11-13 拍「只算门店真实使用」,
     走 8770 /internal/store-usage + 内部凭证;取不到 = 拿不到,不退回读别的账);
     别的项目照旧读 `usage_ledger`(「用量与成本」页那份账),这个月(上海时间自然月)、不算 mock;**一行算不出参考价 / 一笔不是美元 / 一笔都没有 → 拿不到**,不显示成通过
任何一项拿不到数据,页面上都写「拿不到 ≠ 通过」。

## 权限(复用现成的,不新造)

- 看:「查看有权配置」(谁都能看)
- 填验收记录(验的人 / 日期 / 结论 / 证据 / 备注):「受理意见」—— 总部运营(标注 / 测试角色)那拨人,
  和意见核实「答得对不对」是同一类活
- **店长签字、设真数据导入日:「审批工具动作」** —— 权限矩阵里唯一一条 approver(审核发布者)**默认就有**、
  而管理员**默认没有**(要显式专项授权)的能力。签字的意义是「另一个人看过、认了」:
  填记录的人(受理意见)默认签不了,配系统的管理员默认也签不了。
  另一条 approver 类能力「生产审核/发布/回滚」反过来 —— 管理员默认有、approver 要专项授权,用它就等于管理员自己填、自己签。
  起算日和签字同一道闸:把起算日往前挪就能让「满两周」提前成立,它和签字一样决定「做完」。

## 留痕

每次改记录 / 签字 / 签字作废 / 设起算日:`acceptance_events` 追加一行(带前后值),同一个事务里再写一行 `audit_events`
(审计记录页看得到)。**签过字之后改了结论 / 验的人 / 日期 / 证据,签字当场作废**(时间线记一行「签字作废」)——
店长签的是改之前那一版。

## 这次没做的(写清楚,别当成做了)

- 签于真实试点开始之前的签字(拍板第二十条「先虚拟试点签字」)**照样计入①**,只在行上标「签于真实试点前」——
  虚拟试点的签字到真实试点时算不算数,业务没拍,这里不替它判。
- 撤销签字没有单独的按钮:改记录就会作废签字;要撤,改一下结论再改回来(时间线两行都在)。
- 月费用只看这个项目的账;到 80% 提醒、到顶停 Opus 升级是执行手册 W22 的事,这页不做。
"""
import datetime as _dt
import json as _json
import os as _os
import uuid as _uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import acceptance_flow as F

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
上海 = ZoneInfo("Asia/Shanghai")
签字权限 = "审批工具动作"
记录权限 = "受理意见"

# 请求体里的名字 → 列
可改字段 = {"验的人": "tested_by", "验的日期": "tested_date", "结论": "verdict", "证据链接": "evidence_ref", "备注": "note"}
中文名 = {v: k for k, v in 可改字段.items()}
字上限 = {"验的人": 100, "证据链接": 1000, "备注": 2000}
说明最长 = 1000


def _今天():
    return _dt.datetime.now(上海).date()


def _新id(前缀字):
    return f"{前缀字}_{_uuid.uuid4().hex[:12]}"


def _字(体, k):
    v = 体.get(k)
    return (str(v).strip() or None) if v is not None else None


def _给人看(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


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


def _审计(c, me, action, target, reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action, target_ref, environment, at, result,
            reason, created_at, created_by)
        values (:i, :o, :p, :a, :ac, :t, :e, now(), 'ok', :rs, now(), :a)"""),
              {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id, "ac": action,
               "t": _json.dumps(target, ensure_ascii=False, default=str), "e": _os.environ.get("APP_ENV", "development"),
               "rs": reason})


def _记一步(c, org, project_id, me, item_id, 动作, 说明, 变化=None):
    c.execute(text("""insert into acceptance_events (id, organization_id, project_id, created_at, created_by,
                          acceptance_item_id, action_code, note, change_snapshot)
                      values (:i, :o, :p, now(), :u, :it, :a, :n, cast(:ch as jsonb))"""),
              {"i": _新id("ae"), "o": org, "p": project_id, "u": me.user_id, "it": item_id, "a": 动作, "n": 说明,
               "ch": _json.dumps(变化, ensure_ascii=False, default=str) if 变化 else None})


def 种上(c, project_id):
    """十条场景 + 一行试点设置,只给 `F.该种吗()` 的项目种(澜绣项目 + 测试临时项目);已经有的不动(on conflict do nothing,唯一键兜底)。
    第一次打开清单时种 —— 迁移里种不了:CI 的新库里跑迁移那一刻澜绣项目还没导进来。"""
    if not F.该种吗(project_id):
        return 0
    org = _项目组织(c, project_id)
    n = 0
    for 序, (编号, 场景, 标准) in enumerate(F.十条场景, 1):
        n += c.execute(text("""
            insert into acceptance_items (id, organization_id, project_id, created_at, created_by, updated_at, revision,
                                          scenario_code, scenario_name, expected_note, sort_no, verdict)
            values (:i, :o, :p, now(), 'system', now(), 1, :c, :n, :e, :s, '待验')
            on conflict (project_id, scenario_code) do nothing"""),
            {"i": _新id("acc"), "o": org, "p": project_id, "c": 编号, "n": 场景, "e": 标准, "s": 序}).rowcount
    c.execute(text("""
        insert into acceptance_pilots (id, organization_id, project_id, created_at, created_by, updated_at, revision)
        values (:i, :o, :p, now(), 'system', now(), 1)
        on conflict (project_id) do nothing"""), {"i": _新id("apl"), "o": org, "p": project_id})
    return n


def 门店费用汇总(体):
    """聊天站 /internal/store-usage 的返回 → 判_费用 吃的汇总形状。纯函数。
    体是 None / 带 error → None(拿不到);合计 None(有一笔金额未知 / 坏行)→ 拿不到并带账上那句说明 —— **不当 0 算**。"""
    if not isinstance(体, dict) or 体.get("error"):
        return None
    笔 = int(体.get("笔数") or 0)
    合 = 体.get("合计")
    汇 = {"月份": 体.get("月份"), "行数": 笔, "已知金额": None if 合 is None else round(float(合), 4),
          "金额未知的行数": 0, "币种们": [体.get("币种") or "USD"] if 笔 else [], "来源": "门店用量账"}
    if 合 is None:
        汇["拿不到"] = f"门店用量账:{体.get('账') or '合计拿不到'}"
    return 汇


def _问门店用量():
    """→ 聊天站 /internal/store-usage 的返回或 {error}。走 curl + 内部凭证,同 chat_assistants_api._问聊天站加载了什么。"""
    import json as _json
    import subprocess as _sp
    from open_api import _内部凭证, 聊天站
    凭 = _内部凭证()
    if not 凭:
        return {"error": "内部通道没开:本机没有凭证文件"}
    try:
        r = _sp.run(["curl", "-sS", "--noproxy", "*", "-m", "8", 聊天站.rstrip("/") + "/internal/store-usage",
                     "-H", f"X-Lanxiu-Internal: {凭}", "-w", "\n%{http_code}"], capture_output=True, text=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"error": f"调聊天站起不来:{type(e).__name__}"}
    体, _, 码 = r.stdout.rpartition("\n")
    if 码 != "200":
        return {"error": f"聊天站回 HTTP {码 or '连不上'}"}
    try:
        return _json.loads(体)
    except ValueError:
        return {"error": "聊天站回的不是 JSON"}


def 本月费用(c, project_id, 今天, 门店体=None):
    """**门店入口所在的项目(澜绣)读门店用量账**(用户 11-13 拍:只算门店真实使用 —— usage_ledger 混着评测 / 夜跑,
    而聊天站门店调用一笔都没进 usage_ledger);取不到就是 None(拿不到),**不退回去读 usage_ledger**。
    别的项目(没有门店入口,比如测试临时项目)照旧读 usage_ledger。"""
    if project_id in F.种子项目:
        return 门店费用汇总(门店体 if 门店体 is not None else _问门店用量())
    return 账本费用(c, project_id, 今天)


def 账本费用(c, project_id, 今天):
    """这个月(上海时间自然月)这个项目的真调用账:和「用量与成本」(knowledge_api.用量与成本)读同一张 usage_ledger、
    同一套口径 —— mock 不算钱,amount_known=False 是「算不出」不是 0。
    ⚠️ 两列可空,所以用 `is distinct from` / `is not true`:`source <> 'mock'` 会把 source 为空的真调用悄悄漏掉,
    `not amount_known` 会让 amount_known 为空的那行既不算已知、也不算算不出 —— 合计少了一笔而没有任何提示。"""
    月初 = _dt.datetime(今天.year, 今天.month, 1, tzinfo=上海)
    r = c.execute(text("""
        select count(*) 行数,
               coalesce(sum(amount) filter (where amount_known), 0) 已知金额,
               count(*) filter (where amount_known is not true) 金额未知的行数,
               coalesce(array_agg(distinct coalesce(currency, '(没写币种)')) filter (where amount_known), '{}') 币种们
          from usage_ledger
         where project_id=:p and source is distinct from 'mock' and created_at >= :b"""), {"p": project_id, "b": 月初}).mappings().first()
    return {"月份": f"{今天.year}-{今天.month:02d}", "行数": int(r["行数"] or 0),
            "已知金额": round(float(r["已知金额"] or 0), 4), "金额未知的行数": int(r["金额未知的行数"] or 0),
            "币种们": [x for x in (r["币种们"] or []) if x]}


def _行(x, 起算日):
    签时 = x["signed_at"]
    return {"id": x["id"], "编号": x["scenario_code"], "场景": x["scenario_name"], "通过标准": x["expected_note"],
            "验的人": x["tested_by"], "验的日期": _给人看(x["tested_date"]), "结论": x["verdict"],
            "证据链接": x["evidence_ref"], "备注": x["note"],
            "签字人": x["signed_by"], "签字时间": _给人看(签时),
            "签于真实试点前": F.签于试点前吗(签时.astimezone(上海).date() if 签时 else None, 起算日),
            "最近更新": _给人看(x["updated_at"]), "revision": x["revision"]}


# ── 清单 + 「做完」判定 ──────────────────────────────────────────────
@router.get(前缀 + "/acceptance")
def 上线验收(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """十条场景各一行 + 顶部「做完」判定(三项各自的状态)+ 试点设置。第一次打开时种上十条(只澜绣项目)。
    改记录 / 签字要带的 revision 在每一行;设起算日要带的在「试点.revision」。"""
    今天 = _今天()
    门店体 = _问门店用量() if project_id in F.种子项目 else None   # 网络调用放在事务外
    with 事务() as c:
        种上(c, project_id)
        rs = c.execute(text("""select count(*) over () 全量, * from acceptance_items where project_id=:p and archived_at is null
                                order by sort_no, scenario_code"""), {"p": project_id}).mappings().all()
        试 = c.execute(text("select * from acceptance_pilots where project_id=:p"), {"p": project_id}).mappings().first()
        费 = 本月费用(c, project_id, 今天, 门店体)
        线 = c.execute(text("""select e.created_at, e.created_by, e.action_code, e.note, e.change_snapshot, i.scenario_code
                                from acceptance_events e
                                left join acceptance_items i on i.project_id = e.project_id and i.id = e.acceptance_item_id
                               where e.project_id=:p order by e.created_at desc, e.id desc limit 50"""),
                       {"p": project_id}).mappings().all()
    起算日 = 试["pilot_start_date"] if 试 else None
    行们 = [_行(x, 起算日) for x in rs]
    判 = F.判_做完(F.判_十条(行们), F.判_试点(起算日, 今天), F.判_费用(费))
    # 不分页(一个项目最多十几行);total 取同一句查询的 count(*) over () —— 一行都没有就是真的 0 行
    return {"items": 行们, "next_cursor": None, "total": int(rs[0]["全量"]) if rs else 0,
            "做完判定": 判,
            "试点": ({"真数据导入日": _给人看(起算日), "说明": 试["note"], "revision": 试["revision"]} if 试 else None),
            "本月费用": 费,
            "可选结论": list(F.结论们),
            "签字要的权限": 签字权限, "填记录要的权限": 记录权限,
            "我能签吗": me.能(签字权限)[0], "我能填吗": me.能(记录权限)[0],
            "时间线": [{"时间": _给人看(e["created_at"]), "谁": e["created_by"], "动作": e["action_code"],
                      "场景": e["scenario_code"], "说明": e["note"], "变化": e["change_snapshot"]} for e in 线],
            "note": ("场景和通过标准抄自《产品需求文档》13.4;**只有三项都「通过」才算做完**,拿不到数据的不算通过。"
                     + ("" if F.该种吗(project_id) else "十条场景只种在澜绣项目里,这个项目没有。"))}


def _锁一行(c, project_id, item_id, if_match):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把这一行的 revision 放进 If-Match 头")
    x = c.execute(text("select * from acceptance_items where project_id=:p and id=:i and archived_at is null for update"),
                  {"p": project_id, "i": item_id}).mappings().first()
    if not x:
        raise _错(404, "NOT_FOUND", "没有这条验收场景", "回上线验收页重新进")
    if str(x["revision"]) != str(if_match).strip('"'):
        raise _错(409, "REVISION_CONFLICT", "这一行刚被别人改过", "刷新看一眼最新的再改")
    return x


def 校验记录(体):
    """→ (列: 值, 坏字段)。纯函数;只看给了的键。空串 = 清空(结论不许清空)。"""
    出, 坏 = {}, {}
    for k, 列 in 可改字段.items():
        if k not in 体:
            continue
        v = _字(体, k)
        if k == "验的日期" and v:
            try:
                v = _dt.date.fromisoformat(v)
            except ValueError:
                坏[k] = "要写成 2026-12-01 这样的日期"
                continue
        elif v and len(v) > 字上限.get(k, 200):
            坏[k] = f"最多 {字上限.get(k, 200)} 字"
            continue
        出[列] = v
    if "verdict" in 出 and 出["verdict"] not in F.结论们:
        坏["结论"] = f"只收 {list(F.结论们)}"
    return 出, 坏


# ── 改一条验收记录 ──────────────────────────────────────────────────
@router.patch(前缀 + "/acceptance/{item_id}")
async def 改验收记录(project_id: str, item_id: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限(记录权限))):
    """`{验的人?, 验的日期?, 结论?, 证据链接?, 备注?}`,带 If-Match。只改给了的键。
    结论「通过 / 不通过」要写验的人和日期(不写说不清谁在哪天验的);日期不能晚于今天。
    **签过字的,改了结论 / 验的人 / 日期 / 证据 → 签字作废**(时间线记一行「签字作废」带签字人和时间)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验记录(体)
    if not 出 and not 坏:
        坏["字段"] = f"一个能改的字段都没给 —— 能改的:{list(可改字段)}"
    if 出.get("tested_date") and 出["tested_date"] > _今天():
        坏["验的日期"] = "不能晚于今天 —— 还没验的不记"
    if 坏:
        raise _错(422, "VALIDATION", "验收记录的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        x = _锁一行(c, project_id, item_id, if_match)
        变化 = {中文名[列]: [_给人看(x[列]), _给人看(v)] for 列, v in 出.items() if x[列] != v}
        if not 变化:
            raise _错(422, "VALIDATION", "给的值和现在一样,没有要改的", "改了再保存", field_errors={"字段": "没有变化"})
        后 = {列: 出.get(列, x[列]) for 列 in 可改字段.values()}
        if 后["verdict"] in ("通过", "不通过"):
            缺 = {k: "下了结论要写" for k, 列 in (("验的人", "tested_by"), ("验的日期", "tested_date")) if not 后[列]}
            if 缺:
                raise _错(422, "VALIDATION", "下结论要写谁验的、哪天验的", "补上验的人和验的日期", field_errors=缺)
        作废 = bool(x["signed_by"]) and any(列 in 出 and x[列] != 出[列] for 列 in F.改了就作废签字的字段)
        设 = ", ".join(f"{列}=:c_{列}" for 列 in 出) + (", signed_by=null, signed_at=null" if 作废 else "")
        r = c.execute(text(f"""update acceptance_items set {设}, revision=revision+1, updated_at=now()
                                where project_id=:p and id=:i returning revision"""),
                      {"p": project_id, "i": item_id, **{"c_" + k: v for k, v in 出.items()}}).mappings().first()
        _记一步(c, x["organization_id"], project_id, me, item_id, "改记录", None, 变化)
        _审计(c, me, "acceptance.record", {"验收场景": item_id, "编号": x["scenario_code"], "变化": 变化})
        if 作废:
            旧签 = {"签字人": x["signed_by"], "签字时间": _给人看(x["signed_at"])}
            _记一步(c, x["organization_id"], project_id, me, item_id, "签字作废", "签字之后改了记录,店长签的是改之前那一版", 旧签)
            _审计(c, me, "acceptance.sign.void", {"验收场景": item_id, "编号": x["scenario_code"], **旧签})
    return {"id": item_id, "revision": r["revision"], "改了": list(变化), "签字作废了吗": 作废,
            "note": "签过的字作废了 —— 要店长重新签" if 作废 else "记在时间线上了"}


# ── 店长签字 ────────────────────────────────────────────────────────
@router.post(前缀 + "/acceptance/{item_id}/sign")
async def 店长签字(project_id: str, item_id: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限(签字权限))):
    """`{说明?}`,带 If-Match。签字人 = 当前登录的人,签字时间 = 现在(都不从请求里收,不能替别人签、不能倒签)。
    只签结论「通过」、写了验的人和日期的;已经签过的 409(要重签先让它作废)。"""
    体 = await _json体(request) or {}
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        raise _错(422, "VALIDATION", "说明太长", "写短一点", field_errors={"说明": f"最多 {说明最长} 字"})
    with 事务() as c:
        x = _锁一行(c, project_id, item_id, if_match)
        if x["signed_by"]:
            raise _错(409, "ALREADY_SIGNED", f"{x['scenario_code']} 已经由 {x['signed_by']} 签过了",
                      "要重签:先改记录让旧签字作废(时间线会记着)")
        坏 = {}
        if x["verdict"] != "通过":
            坏["结论"] = f"现在是「{x['verdict']}」—— 只签「通过」的(不通过的先修好再验)"
        for k, 列 in (("验的人", "tested_by"), ("验的日期", "tested_date")):
            if not x[列]:
                坏[k] = "没写 —— 签字之前要说清谁在哪天验的"
        if 坏:
            raise _错(422, "VALIDATION", "这一条还不能签", "见字段错误", field_errors=坏)
        r = c.execute(text("""update acceptance_items set signed_by=:u, signed_at=now(), revision=revision+1, updated_at=now()
                               where project_id=:p and id=:i returning revision, signed_at"""),
                      {"u": me.user_id, "p": project_id, "i": item_id}).mappings().first()
        签 = {"签字人": me.user_id, "签字时间": _给人看(r["signed_at"]), "结论": x["verdict"], "验的人": x["tested_by"],
             "验的日期": _给人看(x["tested_date"]), "证据链接": x["evidence_ref"]}
        _记一步(c, x["organization_id"], project_id, me, item_id, "签字", 说明, 签)
        _审计(c, me, "acceptance.sign", {"验收场景": item_id, "编号": x["scenario_code"], **签}, reason=说明)
    return {"id": item_id, "revision": r["revision"], "签字人": me.user_id, "签字时间": _给人看(r["signed_at"]),
            "note": "签上了;之后改结论 / 验的人 / 日期 / 证据会让这次签字作废"}


# ── 设真数据导入日(试点起算日)─────────────────────────────────────
@router.patch(前缀 + "/acceptance-pilot")
async def 设试点起算日(project_id: str, request: Request,
                 if_match: str = Header(default=None, alias="If-Match"),
                 me: 身份 = Depends(要权限(签字权限))):
    """`{真数据导入日: "2026-12-01" | null, 说明}`,带 If-Match(清单里「试点.revision」)。
    **说明必填**(这个日子决定「满两周」从哪天算);不能晚于今天(还没导入的不记);给 null = 清掉(回到「未开始」)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    坏 = {}
    if "真数据导入日" not in 体:
        坏["真数据导入日"] = "要给(清掉给 null)"
    日 = _字(体, "真数据导入日")
    if 日:
        try:
            日 = _dt.date.fromisoformat(日)
            if 日 > _今天():
                坏["真数据导入日"] = "不能晚于今天 —— 还没导入的不记"
        except ValueError:
            坏["真数据导入日"] = "要写成 2026-12-01 这样的日期"
    说明 = _字(体, "说明")
    if not 说明:
        坏["说明"] = "要写 —— 这个日子决定「满两周」从哪天算,改它要说清为什么"
    elif len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "真数据导入日不合格", "见字段错误", field_errors=坏)
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", "把上线验收页「试点.revision」放进 If-Match 头")
    with 事务() as c:
        if not F.该种吗(project_id):
            raise _错(404, "NOT_FOUND", "这个项目没有上线验收", "十条场景只在澜绣项目里")
        种上(c, project_id)
        x = c.execute(text("select * from acceptance_pilots where project_id=:p for update"), {"p": project_id}).mappings().first()
        if str(x["revision"]) != str(if_match).strip('"'):
            raise _错(409, "REVISION_CONFLICT", "试点设置刚被别人改过", "刷新看一眼最新的再改")
        if x["pilot_start_date"] == 日:
            raise _错(422, "VALIDATION", "和现在一样,没有要改的", "改了再保存", field_errors={"真数据导入日": "没有变化"})
        r = c.execute(text("""update acceptance_pilots set pilot_start_date=:d, note=:n, revision=revision+1, updated_at=now()
                               where project_id=:p returning revision"""), {"d": 日, "n": 说明, "p": project_id}).mappings().first()
        变化 = {"真数据导入日": [_给人看(x["pilot_start_date"]), _给人看(日)]}
        _记一步(c, x["organization_id"], project_id, me, None, "设试点起算日", 说明, 变化)
        _审计(c, me, "acceptance.pilot_start", 变化, reason=说明)
    return {"真数据导入日": _给人看(日), "revision": r["revision"],
            "note": "清掉了 —— 「试点满两周」回到未开始" if 日 is None else f"从 {日.isoformat()} 起算两周"}
