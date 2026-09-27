#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理 API。**每个按钮对应真实接口、状态和失败反馈**(实施必须遵守第 2 条)。

## 这个文件里没有第二套规矩

权限从 `contract/perms.py` 判、错误按 `contract/errors.py` 造、
状态流转问 `contract/states.py`、接口形态查 `contract/endpoints.py`。
handler 只负责取数和写库。

**凡是 handler 里出现「第二套判断」的地方,都是将来会漂的地方。**
"""
import hashlib, json, os, sys, time, uuid
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import FastAPI, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import runtime_cfg as CFG
import errors as ER
import states as ST
import perms as PM
import endpoints as EP
from db import 连接, 事务
from deps import 身份, 取身份, 要权限, _错

# ── 启动自检:危险组合一律拒绝启动 ──────────────────────────────────
_坏 = CFG.启动自检()
if _坏:
    print("❌ 拒绝启动:", file=sys.stderr)
    for x in _坏: print("   ·", x, file=sys.stderr)
    raise SystemExit(1)

app = FastAPI(title="澜绣云裳 AI 管理后台 API", version="0.1.0", docs_url="/api/docs",
              openapi_url="/api/openapi-live.json")
前缀 = "/api/v1/projects/{project_id}"


from fastapi import HTTPException as _HE
from fastapi.exceptions import RequestValidationError as _RVE


@app.exception_handler(_HE)
async def _http错(request: Request, exc: _HE):
    """⚠️ **必须显式注册这个 handler。** FastAPI 自带的 HTTPException handler
    会把 detail 包成 `{"detail": ...}` —— 于是错误体变成两层,
    顶层没有 code/message/advice,**不符合 §19.1 的错误契约**。
    而它看起来「有错误信息」,前端也能显示出来,所以很容易一直没人发现。
    """
    d = exc.detail
    if isinstance(d, dict) and "code" in d:
        return JSONResponse(status_code=exc.status_code, content=d)
    return JSONResponse(status_code=exc.status_code, content=ER.错(
        "HTTP_ERROR", str(d), "看 message", http=exc.status_code
        if exc.status_code in ER.状态语义 else 500))


@app.exception_handler(_RVE)
async def _校验错(request: Request, exc: _RVE):
    """参数校验失败也要走错误契约,**而且要能定位到字段**(§5.3
    「错误在字段附近显示,并在提交时定位首个错误」)。"""
    fe = {}
    for e in exc.errors():
        路 = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        fe[路 or "body"] = e.get("msg", "无效")
    return JSONResponse(status_code=422, content=ER.错(
        "VALIDATION", "请求参数不对", "看 field_errors 里点名的那几个字段",
        http=422, field_errors=fe))


@app.exception_handler(Exception)
async def _兜底(request: Request, exc: Exception):
    """没预料到的错误也要符合错误契约 —— **包括 advice**。

    一个 500 只返回「Internal Server Error」的接口,把「服务器出问题了」
    和「你的请求有问题」压成了同一句话,而这两种的下一步动作完全不同。
    """
    return JSONResponse(status_code=500, content=ER.错(
        "INTERNAL", f"{type(exc).__name__}", "这是服务端问题,不是你的请求有问题;"
                                            "把 trace_id 给运维,他们能在日志里定位",
        http=500, retryable=True))


def _列表(items, total=None, next_cursor=None):
    """统一列表信封。**total 不知道就给 None,绝不给 0** ——
    0 会被读成「一条都没有」,而那是另一回事。"""
    return {"items": items, "next_cursor": next_cursor, "total": total}


def _异步(job_id, resource_id, project_id, status="排队中", trace_id=None):
    """异步信封。**status 不许写「已完成」** —— 那是用假完成冒充执行。"""
    return {"job_id": job_id, "status": status, "resource_id": resource_id,
            "status_url": f"/api/v1/projects/{project_id}/jobs/{job_id}",
            "trace_id": trace_id}


def _新id(前缀):
    return f"{前缀}_{uuid.uuid4().hex[:12]}"


def _哈希(d):
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True)
                          .encode()).hexdigest()[:32]


def _审计(c, me, action, target, result="ok", reason=None, diff=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, redacted_diff, created_at, created_by)
        values (:i,:o,:p,:a,:ac,:t,:e, now(), :r, :rs, :d, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result,
           "rs": reason, "d": json.dumps(diff, ensure_ascii=False) if diff else None})


# ── 路由记账(只在环境变量打开时生效)──────────────────────────────
#
# ## 为什么要它,以及它比「扫测试文件」强在哪
#
# 规格 §20 要求交付报告逐项写「**已实现且验证 / 已实现未验证 / 未实现**」,
# 并且「禁止用『所有页面都有了』代替完整功能验收」。
#
# 要算出「已实现**且验证**」就得知道「哪几条接口真的被测试打过」。
# 最省事的算法是**在测试文件里搜这条路径的字符串** —— 而那个判据比它声称的弱:
# 一条只是被注释提到、或者拼在某个没被执行的分支里的路径,也会算「验过」。
#
# 所以这里改成**运行时记账**:记 FastAPI **实际匹配到的路由模板**
# (`request.scope["route"].path`,不是原始 URL —— 后者带具体 ID,归不了类)。
# 于是「验过」= **测试真的打过这条路径**,而不是「某个文件里提到过它」。
#
# ⚠️ 它仍然**不证明断言是对的**:打过一次和「行为被断言对了」是两件事。
# 这条限制写在生成的报告里,不靠读的人自己想起来。
_路由账 = os.environ.get("AIMC_TRACE_ROUTES")
if _路由账:
    @app.middleware("http")
    async def _记路由(request: Request, call_next):
        resp = await call_next(request)
        r = request.scope.get("route")
        路 = getattr(r, "path", None)
        if 路:
            with open(_路由账, "a", encoding="utf-8") as f:
                f.write(f"{request.method} {路} {resp.status_code}\n")
        return resp
    print(f"▸ 路由记账开着,写到 {_路由账}", file=sys.stderr)


# ── 编排接口(Workflow 与 Agent 后台规格 §17.1)────────────────────
# 单独一个文件。**一个越长的 handler 文件越容易长出第二套规矩** ——
# 而这里的纪律是「权限从 contract/perms.py 判、状态问 contract/states.py」。
import workflows_api as _WF
import agents_api as _AG
app.include_router(_WF.router)
app.include_router(_AG.router)


# ── 健康 / 运行信息 ────────────────────────────────────────────────
@app.get("/api/healthz")
def healthz():
    return {"ok": True, "env": CFG.APP_ENV, "auth_mode": CFG.AUTH_MODE,
            # **演示模式要醒目** —— 一个看不出自己在演示模式的界面,
            # 会让人拿编出来的结果当真实结果
            "演示模式": CFG.演示模式(),
            "演示说明": ("模型/训练走的是 mock 适配器,结果是编的,"
                        "**不许计入真实评测或发布**") if CFG.演示模式() else None}


@app.get("/api/v1/projects")
def 项目们(x_dev_user: str = Header(default=None, alias="X-Dev-User")):
    if not x_dev_user:
        raise _错(401, "NO_IDENTITY", "没有身份", "带请求头 X-Dev-User:<工号>")
    with 连接() as c:
        rows = c.execute(text("""
            select p.id, p.name, p.status, m.role, m.special_grants
              from projects p
              join memberships m on m.organization_id = p.organization_id
                                and (m.project_id = p.id or m.project_id is null)
             where m.user_id = :u and m.status='active'
             order by p.name
        """), {"u": x_dev_user}).mappings().all()
    # **全局搜索/列表只返回有权访问的对象**(§4)
    return _列表([dict(r) for r in rows], total=len(rows))


# ── 工作台(§6)────────────────────────────────────────────────────
@app.get(前缀 + "/workbench")
def 工作台(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
          范围小时: int = Query(24, ge=1, le=720),
          环境: str = Query("development")):
    """卡片每项都要带**时间范围、分母、环境、数据来源、更新时间**(§6)。

    ⚠️ **质量分不能用 HTTP 成功率代替**,没有评测覆盖就显示「尚未评测」——
    **不显示 0 分**。一个 0 分会被读成「质量很差」,而真相是「没测过」。
    """
    with 连接() as c:
        q = lambda s, **kw: c.execute(text(s), dict(p=project_id, e=环境,
                                                    h=范围小时, **kw)).mappings()
        请求 = q("""select count(*) n,
                          count(*) filter (where end_reason='ok') ok
                     from traces
                    where project_id=:p and environment=:e
                      and started_at > now() - (:h || ' hours')::interval""").first()
        费用 = q("""select coalesce(sum(amount),0) 已知,
                          count(*) filter (where amount_known is not true) 未覆盖
                     from usage_ledger
                    where project_id=:p and created_at > now() - (:h || ' hours')::interval
                 """).first()
        任务 = q("""select count(*) filter (where status='失败') 失败
                     from jobs where project_id=:p
                       and created_at > now() - (:h || ' hours')::interval""").first()
        待审 = q("""select count(*) n from release_manifests
                    where project_id=:p and (approval->>'state') = '待审核'""").first()
        评测数 = q("""select count(*) n from evaluations where project_id=:p""").first()
        生产 = q("""select eb.release_manifest_id, eb.updated_at
                      from environment_bindings eb
                     where eb.project_id=:p and eb.environment=:e
                     order by eb.updated_at desc limit 1""").first()

    n = 请求["n"] or 0
    来源 = "traces 表(本后台自己记的)"
    def 卡(名, 值, 分母, 说明, 数据来源=来源, 未知=False):
        return {"名": 名, "值": 值, "未知": 未知, "分母": 分母,
                "时间范围": f"最近 {范围小时} 小时", "环境": 环境,
                "数据来源": 数据来源, "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "说明": 说明}

    卡片 = [
        卡("当前生产版本", (生产 or {}).get("release_manifest_id") or "未发布", None,
          "环境指针指向的发布清单;**没发布就是没发布,不是「用最新的」**",
          数据来源="environment_bindings 表"),
        卡("请求量", n, None, "按环境和时间范围过滤"),
        卡("请求成功返回率",
          (round((请求["ok"] or 0) * 100 / n, 1) if n else None), f"{n} 次请求",
          "**这是接口层面的成功率,不代表回答对不对**", 未知=(n == 0)),
        # ⚠️ 这一条是规格明确点出来的坑
        卡("业务质量分数", None, f"{评测数['n']} 个评测实验",
          "**尚未评测** —— 不显示 0 分:0 会被读成「质量很差」,而真相是「没测过」。"
          "质量分只能来自评测,不能用 HTTP 成功率代替",
          数据来源="evaluations 表", 未知=True) if not 评测数["n"] else
        卡("业务质量分数", None, f"{评测数['n']} 个评测实验",
          "有评测实验但还没接评分聚合 —— **不编一个数出来**",
          数据来源="evaluations 表", 未知=True),
        卡("已知费用", float(费用["已知"] or 0), None,
          "只算 amount_known 为真的那些", 数据来源="usage_ledger 表"),
        卡("费用未覆盖数量", 费用["未覆盖"] or 0, None,
          "**这些条目的钱是未知,不是 0** —— 外部账单有延迟",
          数据来源="usage_ledger 表"),
        卡("失败任务", 任务["失败"] or 0, None, "去任务中心看卡在哪一步",
          数据来源="jobs 表"),
        卡("待审核发布", 待审["n"] or 0, None, "发布要审核才能切生产指针",
          数据来源="release_manifests 表"),
    ]
    return {"卡片": 卡片, "环境": 环境, "范围小时": 范围小时,
            "演示模式": CFG.演示模式()}


# ── Prompt 列表(§8.1)────────────────────────────────────────────
@app.get(前缀 + "/prompts")
def prompt列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
              q: Optional[str] = None, 标签: Optional[str] = None,
              被生产引用: Optional[bool] = None,
              limit: int = Query(20, ge=1, le=100), cursor: Optional[str] = None):
    """**「最新保存版本」和「生产引用版本」并排出现**(§8.1)——
    避免以为保存就上线。这不是 UI 偏好:这个后台的立项痛点之一就是
    「知识更新后不知道何时生效」。
    """
    where, 参 = ["d.project_id = :p"], {"p": project_id, "lim": limit + 1}
    if q:
        where.append("(d.key ilike :q or coalesce(d.messages->>'用途','') ilike :q)")
        参["q"] = f"%{q}%"
    if cursor:
        where.append("(d.updated_at, d.id) < (:cu_t, :cu_i)")
        参["cu_t"], 参["cu_i"] = cursor.split("|", 1)
    with 连接() as c:
        rows = c.execute(text(f"""
            select d.id, d.key, d.revision, d.updated_at, d.created_by,
                   d.messages->>'用途' as 用途,
                   d.messages->'标签' as 标签,
                   -- 最新保存版本
                   (select max(v.version_no) from prompt_versions v
                     where v.project_id=d.project_id and v.key=d.key) as 最新版本,
                   -- 生产引用版本:**要穿过环境指针 → 发布清单**才算数,
                   -- 不能拿「最新版本」冒充
                   (select pv.version_no
                      from environment_bindings eb
                      join release_manifests rm
                        on rm.project_id=eb.project_id and rm.id=eb.release_manifest_id
                      join prompt_versions pv
                        on pv.project_id=rm.project_id and pv.id=rm.prompt_version_id
                     where eb.project_id=d.project_id and eb.environment='production'
                       and pv.key=d.key
                     order by eb.updated_at desc limit 1) as 生产版本,
                   (select count(*) from evaluations ev
                     where ev.project_id=d.project_id
                       and ev.candidate_ref->>'prompt_key' = d.key) as 评测次数
              from prompt_drafts d
             where {' and '.join(where)}
               and d.archived_at is null
             order by d.updated_at desc, d.id desc
             limit :lim
        """), 参).mappings().all()
    有更多 = len(rows) > limit
    rows = rows[:limit]
    出 = []
    for r in rows:
        d = dict(r)
        d["生产版本显示"] = d["生产版本"] if d["生产版本"] is not None else "未上线"
        d["评测状态"] = "尚未评测" if not d["评测次数"] else f"{d['评测次数']} 次"
        出.append(d)
    if 被生产引用 is not None:
        出 = [x for x in 出 if (x["生产版本"] is not None) == 被生产引用]
    下一页 = (f"{rows[-1]['updated_at'].isoformat()}|{rows[-1]['id']}"
             if 有更多 and rows else None)
    # **total 给 None**:没做 count(*) 就别编一个数。§19.1 明确允许 null
    return _列表(出, total=None, next_cursor=下一页)


@app.post(前缀 + "/prompts", status_code=201)
async def 建prompt(project_id: str, request: Request,
                  me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    体 = await request.json()
    key = (体.get("key") or "").strip()
    if not key:
        raise _错(422, "KEY_REQUIRED", "要给它一个稳定标识",
                  "填 key(项目内唯一,创建后不随意改) —— 它是被应用引用的那个名字",
                  field_errors={"key": "必填"})
    with 事务() as c:
        重 = c.execute(text("select 1 from prompt_drafts where project_id=:p and key=:k"),
                       {"p": project_id, "k": key}).first()
        if 重:
            raise _错(409, "KEY_TAKEN", f"标识 {key} 已经有了",
                      "换一个标识;要改现有的那条请去它的详情页")
        pid = _新id("pr")
        c.execute(text("""
            insert into prompt_drafts (id, organization_id, project_id, key, messages,
                variable_schema, output_schema, params, revision, created_at, created_by, updated_at)
            values (:i,:o,:p,:k,:m,:vs,:os,:pa, 1, now(), :u, now())
        """), {"i": pid, "o": me.org_id, "p": project_id, "k": key,
               "m": json.dumps({"用途": 体.get("用途", ""), "标签": 体.get("标签", []),
                                "system": 体.get("system", ""),
                                "user": 体.get("user", "")}, ensure_ascii=False),
               "vs": json.dumps(体.get("变量", []), ensure_ascii=False),
               "os": json.dumps(体.get("输出要求", {}), ensure_ascii=False),
               "pa": json.dumps(体.get("参数", {}), ensure_ascii=False), "u": me.user_id})
        _审计(c, me, "prompt.create", {"prompt": pid, "key": key})
    return {"id": pid, "key": key, "revision": 1}


@app.get(前缀 + "/prompts/{pid}")
def prompt详情(project_id: str, pid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        d = c.execute(text("""select * from prompt_drafts
                             where project_id=:p and id=:i"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条 Prompt",
                      "回列表看看是不是换了项目,或者它被归档了")
        vs = c.execute(text("""select id, version_no, content_hash, created_at, created_by,
                                     messages->>'变更说明' as 变更说明
                                from prompt_versions
                               where project_id=:p and key=:k
                               order by version_no desc"""),
                       {"p": project_id, "k": d["key"]}).mappings().all()
    return {"草稿": dict(d), "版本历史": [dict(x) for x in vs],
            # 前端底部固定区靠这个判断「保存为新版本」能不能点(§8.5)
            "能存版本吗": _能存版本(dict(d))}


def _能存版本(d):
    """§8.5:保存为新版本的前置是「静态校验通过 + **变更说明完整**」。

    ⚠️ 返回的是**逐条原因**,不是一个布尔 —— 一个只说「不能保存」的按钮,
    和一个坏掉的按钮对使用的人是一样的。
    """
    缺 = []
    m = d.get("messages") or {}
    if not (m.get("system") or "").strip() and not (m.get("user") or "").strip():
        缺.append("系统指令和用户模板不能都是空的")
    if not (m.get("变更说明") or "").strip():
        缺.append("**变更说明必填** —— 它是以后唯一能想起「为什么改」的地方")
    # 变量名和模板双向检查(§8.3「名称与模板双向检查」)
    模板 = (m.get("system") or "") + (m.get("user") or "")
    定义 = {v.get("名称") for v in (d.get("variable_schema") or []) if v.get("名称")}
    import re as _re
    用到 = set(_re.findall(r"\{\{\s*([A-Za-z_][\w]*)\s*\}\}", 模板))
    只定义没用 = sorted(定义 - 用到)
    只用没定义 = sorted(用到 - 定义)
    if 只用没定义:
        缺.append(f"模板里用了没定义的变量:{只用没定义} —— "
                  f"**定义变量不等于已经取得数据**,先把来源配上")
    if 只定义没用:
        缺.append(f"定义了但模板里没用到:{只定义没用}(不拦,但通常是漏了)")
    硬 = [x for x in 缺 if "不拦" not in x]
    return {"行": not 硬, "原因": 缺}


@app.patch(前缀 + "/prompts/{pid}/draft")
async def 改草稿(project_id: str, pid: str, request: Request,
               if_match: str = Header(default=None, alias="If-Match"),
               me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """**保存草稿不会修改生产**(实施必须遵守第 1 条)。

    If-Match 必填。不要的话就是「最后写的人赢」,而**输的那个人看不到
    自己的改动被覆盖了** —— 他下次打开看到的是别人的版本,还以为是自己存错了。
    """
    if not if_match:
        raise _错(428 if 428 in ER.状态语义 else 409, "IF_MATCH_REQUIRED",
                  "要带 If-Match", "把详情里的 revision 放进 If-Match 头再提交")
    体 = await request.json()
    with 事务() as c:
        d = c.execute(text("""select * from prompt_drafts
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条 Prompt", "回列表重新进入")
        if str(d["revision"]) != str(if_match):
            # 409 要带上**怎么继续** —— 不是让人自己猜
            raise _错(409, "REVISION_CONFLICT",
                      f"这条草稿已经被改过(你拿的是 {if_match},现在是 {d['revision']})",
                      "刷新看一眼别人改了什么再合并;**不要直接覆盖** —— "
                      "覆盖之后对方看不到自己的改动没了",
                      field_errors={"revision": f"当前 {d['revision']}"})
        m = dict(d["messages"] or {})
        for k in ("用途", "标签", "system", "user", "变更说明"):
            if k in 体: m[k] = 体[k]
        新版 = int(d["revision"]) + 1
        c.execute(text("""
            update prompt_drafts
               set messages=:m,
                   variable_schema=coalesce(:vs, variable_schema),
                   output_schema=coalesce(:os, output_schema),
                   params=coalesce(:pa, params),
                   revision=:r, updated_at=now()
             where project_id=:p and id=:i
        """), {"m": json.dumps(m, ensure_ascii=False),
               "vs": json.dumps(体["变量"], ensure_ascii=False) if "变量" in 体 else None,
               "os": json.dumps(体["输出要求"], ensure_ascii=False) if "输出要求" in 体 else None,
               "pa": json.dumps(体["参数"], ensure_ascii=False) if "参数" in 体 else None,
               "r": 新版, "p": project_id, "i": pid})
        新 = c.execute(text("select * from prompt_drafts where project_id=:p and id=:i"),
                       {"p": project_id, "i": pid}).mappings().first()
    return {"revision": 新版, "updated_at": 新["updated_at"].isoformat(),
            "能存版本吗": _能存版本(dict(新)),
            "note": "草稿已保存。**这不影响任何已保存版本,也不影响生产。**"}


@app.post(前缀 + "/prompts/{pid}/versions", status_code=201)
def 存新版本(project_id: str, pid: str, me: 身份 = Depends(要权限("改 Prompt/知识候选"))):
    """从草稿建**不可变**快照(§8.5)。内容不再原地修改。"""
    with 事务() as c:
        d = c.execute(text("""select * from prompt_drafts
                             where project_id=:p and id=:i for update"""),
                      {"p": project_id, "i": pid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条 Prompt", "回列表重新进入")
        判 = _能存版本(dict(d))
        if not 判["行"]:
            raise _错(422, "NOT_READY", "还不能存成正式版本",
                      "；".join(判["原因"]) or "补齐上面缺的内容",
                      field_errors={"原因": 判["原因"]})
        内容 = {"messages": d["messages"], "变量": d["variable_schema"],
                "输出要求": d["output_schema"], "参数": d["params"]}
        h = _哈希(内容)
        同 = c.execute(text("""select version_no from prompt_versions
                             where project_id=:p and key=:k and content_hash=:h"""),
                       {"p": project_id, "k": d["key"], "h": h}).first()
        if 同:
            # **一字没改就不给发新版本** —— 一串内容相同的版本号,
            # 会让「版本变了」失去含义,而版本号正是发布清单里那个确切引用
            raise _错(409, "NO_CHANGE",
                      f"内容和版本 {同[0]} 一模一样(content_hash 相同)",
                      "先改点东西再存版本;只想记一句说明的话,存草稿就够了")
        下一号 = (c.execute(text("""select coalesce(max(version_no),0)+1
                                  from prompt_versions where project_id=:p and key=:k"""),
                           {"p": project_id, "k": d["key"]}).scalar())
        vid = _新id("pv")
        c.execute(text("""
            insert into prompt_versions (id, organization_id, project_id, key, version_no,
                messages, variable_schema, output_schema, params, content_hash,
                created_at, created_by)
            values (:i,:o,:p,:k,:n,:m,:vs,:os,:pa,:h, now(), :u)
        """), {"i": vid, "o": me.org_id, "p": project_id, "k": d["key"], "n": 下一号,
               "m": json.dumps(d["messages"], ensure_ascii=False),
               "vs": json.dumps(d["variable_schema"], ensure_ascii=False),
               "os": json.dumps(d["output_schema"], ensure_ascii=False),
               "pa": json.dumps(d["params"], ensure_ascii=False), "h": h, "u": me.user_id})
        _审计(c, me, "prompt.version.create",
              {"prompt": pid, "key": d["key"], "version": 下一号}, diff={"content_hash": h})
    return {"id": vid, "version_no": 下一号, "content_hash": h,
            "note": "版本已固化,**内容不再原地修改**。要上生产还得走发布清单 + 审核。"}


# ── 调试运行(§8.4)+ 任务 ────────────────────────────────────────
def _mock生成(prompt, 变量):
    """mock 模型适配器。**记 execution_mode=mock**(§19.4)。

    ⚠️ 它故意**不装得像真的**:回答里明写这是 mock。
    规格 §19.4 要求 mock 和真实实现同一契约 —— 那是为了开发方便;
    而正因为契约相同,**标记必须显眼**,否则一份 mock 跑出来的报告
    和真实报告在数据形状上一模一样。
    """
    m = prompt.get("messages") or {}
    模板 = (m.get("user") or m.get("system") or "")
    展开 = 模板
    for k, v in (变量 or {}).items():
        展开 = 展开.replace("{{" + k + "}}", str(v))
    return {
        "text": f"【mock 适配器的回答,不是真实模型输出】\n"
                f"收到的展开后模板共 {len(展开)} 字。\n"
                f"变量:{list((变量 or {}).keys()) or '(无)'}",
        "finish_reason": "ok",
        "actual_model": "mock-echo-v0",
        "usage": {"input_tokens": max(1, len(展开) // 4), "output_tokens": 40,
                  "cached_tokens": 0},
        "execution_mode": "mock",
        "展开后模板": 展开,
    }


@app.post(前缀 + "/prompt-runs", status_code=202)
async def 跑一次(project_id: str, request: Request,
               idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
               me: 身份 = Depends(要权限("运行评测"))):
    """返回 **202 + 任务信封**,不直接给答案(§19.1)。

    调试也花钱,所以要过「运行评测」这条权限(编辑角色是「有额度时」)。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "前端为这一次点击生成一个 UUID 放进 Idempotency-Key 头 —— "
                  "网络超时重发时它保证不会跑第二遍(也不会多花一次钱)")
    体 = await request.json()
    pid, 变量 = 体.get("prompt_id"), 体.get("变量") or {}
    with 事务() as c:
        老 = c.execute(text("""select id, status, target_ref from jobs
                             where project_id=:p and idempotency_key=:k"""),
                       {"p": project_id, "k": idempotency_key}).mappings().first()
        if 老:
            # 相同键相同请求 → **返回原任务**,不新建(§19.1)
            return _异步(老["id"], (老["target_ref"] or {}).get("run_id"),
                        project_id, status=老["status"])
        d = c.execute(text("select * from prompt_drafts where project_id=:p and id=:i"),
                      {"p": project_id, "i": pid}).mappings().first()
        if not d:
            raise _错(404, "NOT_FOUND", "没有这条 Prompt", "先在列表里选一条")

        # **缺变量在调用前拦截**(§8.4)—— 不是跑完再说
        必填 = [v.get("名称") for v in (d["variable_schema"] or [])
                if v.get("必填") and v.get("名称")]
        缺 = [k for k in 必填 if not str(变量.get(k, "")).strip()]
        if 缺:
            raise _错(422, "MISSING_VARIABLES", f"缺必填变量:{缺}",
                      "在右侧「测试输入」里把这几个填上再跑 —— "
                      "**调用前拦住,比跑完拿一个缺东西的答案强**",
                      field_errors={k: "必填" for k in 缺})

        job, run, trace = _新id("job"), _新id("run"), _新id("tr")
        c.execute(text("""
            insert into jobs (id, organization_id, project_id, type, target_ref, status,
                attempts, max_attempts, snapshot_hash, idempotency_key,
                created_at, created_by, updated_at, revision)
            values (:i,:o,:p,'prompt_run',:t,'排队中',0,3,:sh,:k, now(), :u, now(), 1)
        """), {"i": job, "o": me.org_id, "p": project_id,
               "t": json.dumps({"run_id": run, "prompt_id": pid, "变量": 变量},
                               ensure_ascii=False),
               # 快照哈希:提交时那份配置 —— 任务建好之后改 Prompt 不影响它。
               # **「我改了配置所以结果不同」和「同一份配置结果不稳」是两回事。**
               "sh": _哈希({"messages": d["messages"], "变量": d["variable_schema"],
                          "参数": d["params"], "输入": 变量}),
               "k": idempotency_key, "u": me.user_id})
        c.execute(text("""
            insert into job_events (id, organization_id, project_id, job_id, seq, kind,
                payload, at, created_at, created_by)
            values (:i,:o,:p,:j,1,'已受理', :pl, now(), now(), :u)
        """), {"i": _新id("je"), "o": me.org_id, "p": project_id, "j": job,
               # ⚠️ 这一条是「**已受理**」,不是「开始」——
               # 到这一刻一个模型都还没调。写「开始」的话事件流上会出现两个开始
               # (API 一个、worker 一个),而**读事件的人分不清哪个是真的起点**,
               # 于是「从提交到真的开跑等了多久」这个数就没法算了。
               "pl": json.dumps({"阶段": "排队", "说明": "已受理,等 worker 捞"},
                                ensure_ascii=False), "u": me.user_id})

        # ── Job + Outbox **在同一个事务里** ────────────────────────
        # 规格 §18 / §19.3。如果「写库」和「发队列」是两件独立的事,
        # 它们之间一定有窗口:写库成功但没发出去 → 任务永远不会被跑,
        # 而库里它是「排队中」;发出去但写库回滚 → worker 捞到一个幽灵。
        # **两个方向的错都难查,因为库和队列各自看起来都自洽。**
        import sys as _s4
        _s4.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))
        import outbox as _OB
        _OB.入箱(c, org=me.org_id, 项目=project_id, job_id=job, topic="prompt_run",
                payload={"run_id": run, "prompt_id": pid}, 新id=_新id("ob"))
    # ⚠️ **到这里任务只是「排队中」,一个模型都还没调。**
    # 这正是 202 的含义 —— 规格 §19.1:「异步动作返回 202 与 job_id,
    # **不能返回「已经训练完成」**」。Worker 捞到之后才真的跑。
    return _异步(job, run, project_id, status="排队中")



@app.get(前缀 + "/jobs/{job_id}")
def 任务详情(project_id: str, job_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    with 连接() as c:
        j = c.execute(text("select * from jobs where project_id=:p and id=:i"),
                      {"p": project_id, "i": job_id}).mappings().first()
        if not j:
            raise _错(404, "NOT_FOUND", "没有这个任务", "回任务中心看列表")
        ev = c.execute(text("""select seq, kind, payload, at from job_events
                             where project_id=:p and job_id=:i order by seq"""),
                       {"p": project_id, "i": job_id}).mappings().all()
        tr = None
        t = (j["target_ref"] or {})
        if ev and (ev[-1]["payload"] or {}).get("trace_id"):
            tid = ev[-1]["payload"]["trace_id"]
            sp = c.execute(text("""select stage, input_ref, output_ref from spans
                                 where project_id=:p and trace_id=:t order by started_at"""),
                           {"p": project_id, "t": tid}).mappings().all()
            用 = c.execute(text("""select quantity, unit, amount, amount_known, source
                                 from usage_ledger where project_id=:p and trace_id=:t"""),
                           {"p": project_id, "t": tid}).mappings().all()
            # ⚠️ **原文默认脱敏,要专项权限才给**(§8.4 / §15.3)
            看原文 = me.看得到原文吗()
            段 = []
            for s in sp:
                段.append({"阶段": s["stage"],
                           "实际发送": (s["input_ref"] if 看原文 else
                                      {"_": "原文已脱敏 —— 要「查看敏感输入」专项权限"}),
                           "输出": s["output_ref"]})
            tr = {"trace_id": tid, "阶段": 段, "看得到原文": 看原文,
                  "用量": [dict(x) for x in 用],
                  # **未知费用显示「未知」,不用 0 代替**(规格开头的数字约定)
                  "费用说明": "mock 适配器没有真实计价 → 记为未知,**不是 0**"}
    状态 = j["status"]
    return {"id": j["id"], "type": j["type"], "status": 状态,
            "是终态吗": 状态 in ST.找("job")["终态"],
            "attempts": j["attempts"], "target_ref": t,
            "事件": [dict(x) for x in ev], "结果": tr,
            "演示模式": CFG.演示模式()}


@app.get(前缀 + "/jobs/{job_id}/events")
def 任务事件流(project_id: str, job_id: str, from_seq: int = Query(0, ge=0),
             me: 身份 = Depends(要权限("查看有权配置"))):
    """SSE。**按 seq 续传** —— 断线重连把上次收到的最后一个 seq 传进来。

    ⚠️ 为什么不用时间戳当游标:同一毫秒可以有两条事件,而
    **跳过一条和本来就没有那一条,在界面上长得一模一样**。

    ⚠️ 规格 §19.2:「**实时结果重新鉴权**」—— 授权在这个请求上判过一次,
    而流会开着很久。所以每一轮推送前**重新查一次成员记录**:
    权限被撤回之后,一条还开着的流不该继续送数据。
    """
    from fastapi.responses import StreamingResponse
    import sys as _s5, time as _t5
    _s5.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))
    import events as _EV

    def 流():
        seq = int(from_seq)
        止 = _t5.time() + 120                # 上限两分钟,别让连接无限挂着
        while _t5.time() < 止:
            with 连接() as c:
                # **重新鉴权**:成员记录还在吗
                仍然有权 = c.execute(text("""
                    select 1 from memberships
                     where user_id=:u and status='active'
                       and (project_id=:p or project_id is null) limit 1"""),
                    {"u": me.user_id, "p": project_id}).first()
                if not 仍然有权:
                    yield ("event: 无权\ndata: " + json.dumps(
                        {"说明": "权限已被撤回 —— 流到此为止(实时结果要重新鉴权)"},
                        ensure_ascii=False) + "\n\n")
                    return
                批 = _EV.读(c, project_id, job_id, 从seq=seq)
                j = c.execute(text("select status from jobs where project_id=:p and id=:i"),
                              {"p": project_id, "i": job_id}).first()
            for e in 批:
                seq = e["seq"]
                yield ("event: 进度\ndata: " + json.dumps(
                    {"seq": e["seq"], "kind": e["kind"], "payload": e["payload"],
                     "at": str(e["at"])}, ensure_ascii=False) + "\n\n")
            if j and j[0] in ST.找("job")["终态"]:
                yield ("event: 结束\ndata: " + json.dumps(
                    {"status": j[0], "最后seq": seq}, ensure_ascii=False) + "\n\n")
                return
            if not j:
                yield "event: 没有这个任务\ndata: {}\n\n"
                return
            _t5.sleep(0.4)
        yield ("event: 超时\ndata: " + json.dumps(
            {"说明": "流开了两分钟,断开 —— 带上 from_seq 再连,不会丢事件",
             "最后seq": seq}, ensure_ascii=False) + "\n\n")

    return StreamingResponse(流(), media_type="text/event-stream",
                             headers={"cache-control": "no-cache",
                                      "x-accel-buffering": "no"})


# ── 静态页面 ───────────────────────────────────────────────────────
# ⚠️ 少数一层 dirname 就指到 services/apps/web,而 StaticFiles 只会 404 ——
# **「路径算错」和「文件不存在」在 404 上长得一模一样**,所以下面顺带断言目录真的在。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))      # app → api → services → 项目根
_web = os.path.join(_ROOT, "apps", "web")
if not os.path.isdir(_web):
    print(f"⚠️ 找不到前端目录 {_web} —— 页面会 404(接口不受影响)", file=sys.stderr)
if os.path.isdir(_web):
    app.mount("/static", StaticFiles(directory=_web), name="static")

    @app.get("/")
    def 首页():
        return FileResponse(os.path.join(_web, "index.html"))
