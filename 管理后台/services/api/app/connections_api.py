#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型与连接(规格 §17.4-5)。

    GET  /model-connections              连接列表(**secret_ref 只给形状**)
    POST /model-connections              建连接(**只收 secret_ref,不收明文**)
    POST /model-connections/{id}/probe   探测(**落 capabilities**)

## 为什么这一组排在这儿做

发布清单里**钉着一个连接配置版本**(`connection_version_id`)——
而在这之前,**没有任何接口能造出一个**。
一个被清单引用、却只能靠种子脚本产生的东西,等于这条链有一截是手工搭的。

## ⚠️ 这一组碰凭据,所以三条红线各有落点

| 红线 | 落在哪 |
|---|---|
| 明文密钥不许进请求体 | `connections.像明文密钥吗()` —— **当场拒,不是收下后忽略** |
| 错误信息不许回显凭据 | 判据**只返回字段名,不返回值**;`errors.泄密检查` 再兜一层 |
| 列表不许把 `secret_ref` 交出去 | 只给**形状**(有没有、什么协议、多长),不给内容 |

⚠️ 第一条为什么不能「收下后忽略」:契约原话 ——
**「明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报」。**
忽略它只是让这一次调用看起来干净,而那个值已经散出去了。

## ⚠️ 「没探过」不等于「支持一切」

契约原话:**「不探就默认全支持,会在真跑时变成一个说不清的 400」**。
所以:
  · 列表上「探过没有」看得见
  · **发到生产的清单,要求它的连接版本探过**(`release.可以发布吗` 里那一条)

「默认全支持」的坏处不是它错,是**它错的时候不在这里报** ——
报在几天后某一次真实调用上,而那时候没人会想到是连接配置的问题。
"""
import json as _json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract"))

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错

# ⚠️ **不能写 `import adapters`** —— 这个仓库里有**两个** `adapters.py`:
#
#     services/api/app/contract/adapters.py   适配器契约登记(我要的)
#     services/api/app/knowledge/adapters.py  Embedding 模型适配器
#
# 两个目录都在 `sys.path` 上,于是裸名 `adapters` **谁先 import 谁赢** ——
# 而 `knowledge_api.py` 先加载,所以 `sys.modules["adapters"]` 是知识层那份。
#
# 表现:`AttributeError: module 'adapters' has no attribute '找'`,
# 而**报错的地方离真因很远** —— 我单独跑同一段代码是好的(独立进程里
# 我的 sys.path 顺序不同,拿到的是契约那份),只在服务里炸。
# > **「同一段代码在两个进程里 import 到不同的模块」,而两边都不报导入错误。**
#
# 所以这里**按路径显式加载**,不靠 sys.path 的运气。
import importlib.util as _ilu

def _按路径加载(名, 相对路径):
    路 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 相对路径)
    规格 = _ilu.spec_from_file_location(名, 路)
    模 = _ilu.module_from_spec(规格)
    规格.loader.exec_module(模)
    return 模

AD = _按路径加载("契约_适配器登记", os.path.join("contract", "adapters.py"))
import connections as CN
import secretref as SR
import runtime_cfg as CFG

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"


def _新id(前缀字):
    return f"{前缀字}_{uuid.uuid4().hex[:12]}"


def _审计(c, me, action, target, result="ok", reason=None):
    c.execute(text("""
        insert into audit_events (id, organization_id, project_id, actor, action,
            target_ref, environment, at, result, reason, created_at, created_by)
        values (:i,:o,:p,:a,:ac,cast(:t as jsonb),:e, now(), :r, :rs, now(), :a)
    """), {"i": _新id("aud"), "o": me.org_id, "p": me.project_id, "a": me.user_id,
           "ac": action, "t": _json.dumps(target, ensure_ascii=False),
           "e": os.environ.get("APP_ENV", "development"), "r": result, "rs": reason})


def _引用形状(secret_ref):
    """**只给形状,不给内容。**

    给协议 + 长度就够回答「配没配、配的是哪一类存储」,
    而那是界面上唯一需要知道的事。
    ⚠️ 不做「截断到前 N 个字符」—— **截断之后那 N 个字符仍然是原文**。
    """
    s = (secret_ref or "").strip()
    if not s:
        return {"配了吗": False}
    协议 = s.split("://", 1)[0] if "://" in s else (s.split(":", 1)[0] if ":" in s else "?")
    return {"配了吗": True, "存在哪": 协议, "长度": len(s)}


@router.get(前缀 + "/model-connections")
def 连接列表(project_id: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """列表。**`secret_ref` 只给形状,不给内容。**"""
    with 连接() as c:
        行 = [dict(r) for r in c.execute(text("""
            select mc.id, mc.purpose, mc.adapter, mc.display_name, mc.status,
                   mc.revision, mc.created_at,
                   cv.id as ver_id, cv.endpoint, cv.secret_ref, cv.capabilities,
                   cv.config_hash
              from model_connections mc
              left join connection_versions cv
                on cv.project_id = mc.project_id and cv.connection_id = mc.id
             where mc.project_id=:p and mc.archived_at is null
             order by mc.created_at, cv.created_at"""),
            {"p": project_id}).mappings()]
    按连接 = {}
    for r in 行:
        d = 按连接.setdefault(r["id"], {
            "id": r["id"], "用途": r["purpose"],
            "用途中文": CN.用途中文.get(r["purpose"], "?"),
            "适配器": r["adapter"], "名字": r["display_name"],
            "状态": r["status"], "revision": r["revision"], "配置版本": [],
        })
        if r["ver_id"]:
            d["配置版本"].append({
                "id": r["ver_id"], "endpoint": r["endpoint"],
                "密钥": _引用形状(r["secret_ref"]),
                "探过吗": CN.探过吗(r),
                "capabilities": r["capabilities"],
                "配置哈希": r["config_hash"],
            })
    出 = list(按连接.values())
    没探的 = [f'{d["id"]}/{v["id"]}' for d in 出 for v in d["配置版本"] if not v["探过吗"]]
    # ── 表单要填的那两样,**由接口给,不让前端硬编** ────────────────────
    # ⚠️ 2026-09-29 补的。在这之前这条接口只给「已有哪些连接」,
    # 而建连接的表单要填**用途**和**适配器** —— 前端只能自己硬编一份清单。
    # 硬编的代价不是难看:**它和契约会漂**,而漂的表现是
    # 界面上少一个能用的选项、或者多一个已经不支持的 —— **两者都不报错**。
    #
    # ⚠️ 适配器**给不出穷尽清单,所以就不假装有**:
    # 契约只登记了**族**(`ModelProvider`),没有实现登记表;
    # 建连接那条闸判的是「名字里带不带 ModelProvider」。
    # 所以这里给**规则 + 这个项目已经在用的那几个**,并明说它不是下拉框。
    # > 「穷尽的清单」和「不穷尽但有规则」必须长得不一样 ——
    # > 把后者画成一个下拉框,人会以为不在里面的就不能用。
    # ⚠️ 状态值是 **`active`**,不是「启用」。第一版我按中文猜了一个,
    # 于是「这个用途占了吗」**全返回 false**,而库里明明有两条 ——
    # 一个猜错的字段值不会报错,它只会让判断**一直是同一个答案**。
    #
    # ⚠️ 而且要收成**列表**,不是一条:现实里 `generate` 上有**两条** active。
    # 那不是脏数据 —— `seed_demo.py` 故意建的,两条只在 capabilities 上不同
    # (一条支持原生工具调用、一条不支持),为的是演示
    # 「**不按模型家族名字推断兼容**」(附录 D.2)。
    #
    # 也就是说:**建连接那道闸拒绝创建的状态,正是 demo 数据现在所处的状态。**
    # 闸的理由讲的是「不同用途共用一条连接」,而它拦的是「同一用途有两条」——
    # **它盯错了不变量**。这件事留给业务拍板(见下面 `note` 里那句),
    # 这里先**如实报出来**:只给一条的话,界面会把第二条藏掉。
    占了的 = {}
    for c0 in 出:
        if c0.get("状态") == "active":
            占了的.setdefault(c0["用途"], []).append(c0["id"])
    with 连接() as c:
        在用的适配器 = sorted({r[0] for r in c.execute(text(
            """select distinct adapter from model_connections
                where project_id=:p and adapter is not null"""),
            {"p": project_id}) if r[0]})
    族 = AD.找("ModelProvider")
    return {"条数": len(出), "连接": 出,
            "可选用途": [{"值": u, "中文": CN.用途中文.get(u, u),
                       "这个项目占了吗": u in 占了的,
                       "占着的那几条": 占了的.get(u),
                       # ⚠️ **超过一条要单独标出来。** 把「一条」和「好几条」
                       # 画成同一个「占了」,那个矛盾就在界面上看不见了。
                       "不止一条": len(占了的.get(u) or []) > 1,
                       "为什么": ("**建连接那道闸只许一条启用的** —— "
                                "所以这个用途现在建不了新的;先把在用的那条停用或归档"
                                if u in 占了的 else None)}
                      for u in CN.用途们],
            "适配器怎么填": {
                "规则": "名字里必须带 `ModelProvider`(契约登记的那一族)",
                "族说明": 族.get("说明"),
                "这个项目已经在用的": 在用的适配器 or None,
                "⚠️": ("**这不是一份穷尽的下拉框。** 契约只登记了族,"
                       "没有实现登记表 —— 所以给的是规则 + 已经在用的那几个。"
                       "硬编一份完整清单会和契约漂,而漂的表现是"
                       "界面上少一个能用的或多一个不存在的,**两者都不报错**"),
            },
            "没探过的配置版本": 没探的 or None,
            # ⚠️ 把那个矛盾**说在接口上**,而不是只写在代码注释里 ——
            # 一条只有读代码的人才看得到的警告,对用这个后台的人等于不存在。
            "⚠️同用途多条": ([f"用途「{CN.用途中文.get(u, u)}」上有 {len(v)} 条启用的连接:"
                          f"{v} —— **而建连接那道闸只许一条**。"
                          f"这几条是 `seed_demo.py` 直接写库造的,"
                          f"故意让两条只在 capabilities 上不同"
                          f"(一条支持原生工具调用、一条不支持),"
                          f"用来演示「不按模型家族名字推断兼容」。"
                          f"**闸的理由讲的是「不同用途共用一条」,"
                          f"而它拦的是「同一用途有两条」—— 这两件事不是一回事**,"
                          f"要业务拍一次板"
                          for u, v in 占了的.items() if len(v) > 1] or None),
            "note": ("**`secret_ref` 只给形状**(配没配、存在哪、多长)—— "
                     "不做截断:截到前几个字符,那几个字符仍然是原文。"
                     + ("⚠️ 有配置版本**没探过 capabilities** —— "
                        "「没探过」不等于「支持一切」,而发到生产会被拦住。"
                        if 没探的 else ""))}


@router.post(前缀 + "/model-connections", status_code=201)
async def 建连接(project_id: str, request: Request,
           me: 身份 = Depends(要权限("配置密钥与预算"))):
    """建一条连接 + 它的第一个配置版本。

    入参 `{用途, 适配器, 名字?, endpoint, secret_ref}`。

    ⚠️ **只收 `secret_ref`,请求体里出现像明文凭据的字段就当场拒** ——
    不是「收下后忽略」:忽略只是让这一次看起来干净,而那个值已经散出去了。
    """
    体 = await request.json()
    用途 = (体.get("用途") or 体.get("purpose") or "").strip()
    适配器 = (体.get("适配器") or 体.get("adapter") or "").strip()
    名字 = (体.get("名字") or 体.get("display_name") or "").strip() or None
    端点 = (体.get("endpoint") or "").strip()
    引用 = (体.get("secret_ref") or "").strip()

    问 = CN.可以建吗(用途=用途, 适配器=适配器, endpoint=端点, secret_ref=引用, 体=体)
    if 问:
        # ⚠️ `问` 里**只有字段名,没有值** —— 见 `connections.像明文密钥吗()`。
        raise _错(422, "VALIDATION", "这条连接建不了",
                  "按下面每一条改。**密钥只放引用,不放本身**",
                  field_errors={"闸": 问})
    # 适配器要是登记过的(ModelProvider 那一族)
    族 = "ModelProvider"
    if 族 not in 适配器:
        # 不硬拦(允许将来有别的实现名),但要说清它按哪份契约被调用。
        pass
    cid = _新id("mc")
    vid = _新id("cv")
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": project_id}).scalar()
        # ⚠️ **同一个用途不许两条 active 连接。**
        # 共用/重复的坏处很具体:换生成模型时会顺手把 Embedding 也换掉,
        # 而 Embedding 一换,已经建好的索引全部不可比 ——
        # 那件事不报错,只是检索开始变差。
        撞 = c.execute(text("""select id from model_connections
                             where project_id=:p and purpose=:u and status='active'
                               and archived_at is null limit 1"""),
                       {"p": project_id, "u": 用途}).scalar()
        if 撞:
            raise _错(409, "PURPOSE_TAKEN",
                      f"用途「{CN.用途中文.get(用途, 用途)}」上已经有一条在用的连接({撞})",
                      "先把那条停用或归档。**用途不共用一条连接** —— "
                      "共用的话,换生成模型会顺手把 Embedding 也换掉,"
                      "而 Embedding 一换,已经建好的索引全部不可比(**而且不报错**)")
        c.execute(text("""insert into model_connections
            (id, organization_id, project_id, purpose, adapter, display_name,
             status, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:u,:ad,:dn,'active', now(), :by, now(), 1)"""),
                  {"i": cid, "o": org, "p": project_id, "u": 用途, "ad": 适配器,
                   "dn": 名字 or f"{CN.用途中文.get(用途, 用途)}连接", "by": me.user_id})
        哈 = CN.配置哈希(用途=用途, 适配器=适配器, endpoint=端点, capabilities=None)
        c.execute(text("""insert into connection_versions
            (id, organization_id, project_id, connection_id, endpoint, secret_ref,
             config_hash, created_at, created_by, updated_at, revision)
            values (:i,:o,:p,:c,:e,:s,:h, now(), :by, now(), 1)"""),
                  {"i": vid, "o": org, "p": project_id, "c": cid, "e": 端点,
                   "s": 引用, "h": 哈, "by": me.user_id})
        # ⚠️ 审计里**只记引用的形状**,不记引用本身 ——
        # 审计表是「事后查得到」的地方,也就是「事后读得到」的地方。
        _审计(c, me, "model_connection.create",
              {"connection_id": cid, "connection_version_id": vid,
               "用途": 用途, "适配器": 适配器, "密钥形状": _引用形状(引用)})
    return {"id": cid, "配置版本": vid, "用途": 用途, "配置哈希": 哈,
            "密钥": _引用形状(引用),
            "note": ("⚠️ **还没探过 capabilities** —— 「没探过」不等于「支持一切」。"
                     "先跑一次 `POST /model-connections/{id}/probe`;"
                     "不探的话,不支持的参数会在几天后某次真实调用上变成"
                     "一个说不清的 400。"
                     "⚠️ `config_hash` **不含密钥** —— 换密钥不算换配置,"
                     "而把密钥混进哈希会让哈希本身变成一条侧信道")}


def _真探(endpoint, secret_ref):
    """真发一个最小请求,把**实际发生的事**记下来。

    ## 为什么用「一定会被拒」的请求去探

    探的是「这个端点到底支持哪些参数」(契约原话)。
    而最便宜、最不会产生副作用的办法是:**发一个必定被参数校验拒掉的请求**,
    看它拒的理由 —— 那个理由就是它的参数校验在说话。

    这里发的是 `max_tokens: 1` + 一个空 messages:
      · 认得这套协议的端点会回 **400 + 一句关于 messages 的话**
      · 认不出协议的会回别的码,或者根本连不上
      · 没凭据会回 **401**

    三种都是**真信息**,而且这个请求**不会产生任何生成**(不花钱)。

    ⚠️ **不发一个能成功的请求** —— 那会真的生成一次,而「探测」不该花钱、
    不该留下一条用量记录。

    ## 凭据怎么走

    `secretref.解析` 返回**要加哪几个头**,这里直接塞进 curl 的参数,
    **不落任何变量名带凭据字样的地方,不进返回值**。
    走 curl 而不是 urllib:这台机器上 Python 的 TLS 会被拦
    (项目记着「TLS 拦截,联网用 curl」)。
    """
    import subprocess
    import time
    try:
        头, 来路 = SR.解析(secret_ref)
    except SR.解析不了 as e:
        # ⚠️ 异常文字来自 secretref,它保证不带值
        # ⚠️ **这一档不许用「真实端点」开头。** 第一版写的是
        # 「真实端点(**没探成**…)」—— 而这种情况下**一个请求都没发出去**,
        # 用「真实端点」打头会让人以为它至少试过连。
        return {"探法": "**没有发出请求**(凭据定位符解析不了)",
                "探成了吗": False, "发出请求了吗": False, "为什么没成": str(e)}
    cmd = ["curl", "-sS", "-o", "-", "-w", "\n%{http_code}",
           "--max-time", "20", "-X", "POST", endpoint,
           "-H", "content-type: application/json"]
    for k, v in 头.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["--data-binary", "@-"]
    探包 = _json.dumps({"model": "claude-haiku-4-5", "max_tokens": 1,
                      "messages": []}, ensure_ascii=False)
    t0 = time.time()
    try:
        out = subprocess.run(cmd, input=探包, capture_output=True,
                             text=True, timeout=25)
    except Exception as e:
        return {"探法": "**请求发不出去**(curl 挂了或超时)",
                "探成了吗": False, "发出请求了吗": False,
                "为什么没成": type(e).__name__}
    ms = int((time.time() - t0) * 1000)
    体 = (out.stdout or "").strip().splitlines()
    码 = 体[-1] if 体 else ""
    正文 = "\n".join(体[:-1])[:600] if len(体) > 1 else ""
    # 端点的参数校验在说什么 —— 那才是「支持哪些参数」的真答案
    错码 = 错话 = None
    try:
        j = _json.loads(正文)
        错码 = (j.get("error") or {}).get("type")
        错话 = (j.get("error") or {}).get("message")
    except Exception:
        pass
    return {
        "探法": f"真实端点 —— **真发过一个请求**(凭据来路 {来路})",
        "发出请求了吗": True,
        "探成了吗": 码.startswith(("2", "4")),   # 4xx 也算探成:端点在说话
        "http状态": 码, "往返毫秒": ms,
        "端点怎么拒的": {"类型": 错码, "说法": (错话 or "")[:200]},
        "⚠️ 这个请求": "max_tokens=1 + 空 messages —— **必定被参数校验拒掉**,"
                   "所以不产生生成、不花钱、不留用量记录。"
                   "拒的理由就是它的参数校验在说话",
        "判读": ("401/403 → 端点在、协议对,**但这个凭据不行**"
               if 码 in ("401", "403") else
               "400 → 端点在、协议对、凭据过了,**参数校验在说话**(这是最好的结果)"
               if 码 == "400" else
               f"{码} → 端点或协议不是预期的那个"),
    }


@router.post(前缀 + "/model-connections/{cid}/probe", status_code=202)
async def 探测连接(project_id: str, cid: str,
             idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
             me: 身份 = Depends(要权限("配置密钥与预算"))):
    """探一次,把 **capabilities** 落到配置版本上。

    ⚠️ **探出来的结果要标明是谁探的。** 本机 `MODEL_ADAPTER=mock` 时,
    探到的「支持哪些参数」是 mock 说的 —— 而一份 mock 的 capabilities
    在数据形状上和真的一模一样。不标的话,「探过了」这三个字保的是 mock。
    """
    if not idempotency_key:
        raise _错(409, "IDEMPOTENCY_KEY_REQUIRED", "要带 Idempotency-Key",
                  "探测是异步动作,超时重发是常态")
    with 事务() as c:
        mc = c.execute(text("""select id, purpose, adapter from model_connections
                             where project_id=:p and id=:i and archived_at is null"""),
                       {"p": project_id, "i": cid}).mappings().first()
        if not mc:
            raise _错(404, "NOT_FOUND", f"没有连接 {cid}", "回列表重新进入")
        cv = c.execute(text("""select id, endpoint, secret_ref, capabilities
                             from connection_versions
                            where project_id=:p and connection_id=:i
                            order by created_at desc limit 1"""),
                       {"p": project_id, "i": cid}).mappings().first()
        # ⚠️ **出了事务块就读不到行对象了**,所以当场转成 dict ——
        # 第一版在 `return` 里读 `cv["id"]`,那时连接已经关了,整条路径 500。
        cv = dict(cv) if cv else None
        if not cv:
            raise _错(422, "NO_VERSION", f"连接 {cid} 还没有配置版本",
                      "先建一个配置版本再探")
        坏引用 = CN.检查密钥引用(cv["secret_ref"])
        if 坏引用:
            raise _错(422, "BAD_SECRET_REF", "这个配置版本的密钥引用不合格",
                      坏引用)
        # ⚠️ 问的是 **`模型是mock()`**,不是 `演示模式()`。
        # `演示模式()` 是个「或」—— 训练适配器是 mock 也会让它为真,
        # 而那和一次模型探测毫无关系。
        # 2026-10-03 撞到:`MODEL_ADAPTER=anthropic` 起的实例,
        # 探测仍然自称 mock,因为 `TRAINING_ADAPTER` 默认还是 mock。
        是mock = CFG.模型是mock()
        契约 = AD.找("ModelProvider")
        # 探测结果:**照适配器契约登记的方法和必留字段**报,不自己编一套。
        能力 = {
            "探的人": me.user_id,
            "是mock探的": bool(是mock),
            "支持的方法": 契约["方法"],
            "必留字段": 契约["必留"],
            "endpoint": cv["endpoint"],
        }
        # ── 真探:**非 mock 就真发一个请求**(2026-10-03 加)────────────────
        #
        # ⚠️ 这一段之前**不存在**。那时非 mock 分支写的是 `探法: "真实端点"`,
        # 而它**全程没碰过网络** —— 读适配器契约、写一行字、落库。
        #
        # > **一个写着「真实端点」而从没发过一个请求的探测,
        # > 和一个真探过的,在 capabilities 上长得一模一样。**
        #
        # 而这条链上游还有一半:`secret_ref` 一直只被「验形状」,
        # **全仓没有任何地方把它解析开** —— 也就是这后台从没拿它调过东西。
        # 解析在 `secretref.py`。
        if not 是mock:
            实 = _真探(cv["endpoint"], cv["secret_ref"])
            能力.update(实)
            # ⚠️ **落库之前过一道「凭据漏没漏」。**
            # 不是防御性编程 —— 这仓库记着:
            # > 一条从没被攻击过的「结构性保证」,实际上仍然只是约定。
            漏 = SR.查有没有漏凭据(能力)
            if 漏:
                # ⚠️ 这里**不把 `能力` 放进异常** —— 那就是把凭据抄进错误体
                raise _错(500, "PROBE_LEAK",
                          "探测结果里可能带了凭据,**已拦住,没有落库**",
                          f"命中 {len(漏)} 处:{漏[:3]} —— "
                          f"这是 `secretref.查有没有漏凭据` 拦的")
        else:
            能力["探法"] = "mock 适配器(**没有发过任何请求**)"
            能力["发出请求了吗"] = False
        哈 = CN.配置哈希(用途=mc["purpose"], 适配器=mc["adapter"],
                    endpoint=cv["endpoint"], capabilities=能力)
        c.execute(text("""update connection_versions
                             set capabilities=cast(:c as jsonb), config_hash=:h,
                                 updated_at=now()
                           where project_id=:p and id=:i"""),
                  {"c": _json.dumps(能力, ensure_ascii=False), "h": 哈,
                   "p": project_id, "i": cv["id"]})
        _审计(c, me, "model_connection.probe",
              {"connection_id": cid, "connection_version_id": cv["id"],
               "是mock探的": bool(是mock)})
    return {"connection_id": cid, "配置版本": cv["id"], "配置哈希": 哈,
            "是mock探的": bool(是mock), "capabilities": 能力,
            "note": (("⚠️ **这是 mock 适配器探的** —— 一份 mock 的 capabilities "
                      "在数据形状上和真的一模一样,所以这里把它标出来:"
                      "「探过了」这三个字现在保的是 mock,不是那个端点。"
                      if 是mock else
                      "探到的是真实端点报的能力。")
                     + "⚠️ `config_hash` 跟着 capabilities 变了 —— "
                       "**探测会让配置版本的哈希变化**,所以引用它的发布清单"
                       "要重新出一份(而那是对的:能力变了就是配置变了)")}
