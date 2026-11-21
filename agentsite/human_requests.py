# -*- coding: utf-8 -*-
"""聊天站里的「人工待办」—— 管理后台的人工介入单,在门店这边看、填、点按钮(四期 4-1 聊天站一半,11-22)。

    GET  /api/human-requests            我能处理的(默认)/ 已过期的(?status=expired)
    GET  /api/human-request?id=…        一张单的表单:说明 / 字段 / 按钮 / 已填内容 / revision
    POST /api/human-request/decide      {id, decision=按钮id, revision, edits?, reason?, key}

## 以谁的身份去管理后台

**登录工号 → 管理后台「账号绑定」→ 绑定的那个后台账号**,拿它作 X-Dev-User 去调列表 / 详情 / 决定。
所以决定行上记的是真人,门店范围、能不能批都是管理后台**同一套**判定(人工介入按门店分开,用户 11-21 拍「要分,先改后台」)。
这里一条权限都不另判 —— 两边各判一遍,迟早分叉。

查绑定用的是服务账号(`AIMC_USER`,只读那张绑定表);**没绑定就不调,不拿服务账号顶替**:
> 用服务账号去批,决定行上记的是 U001,出了事查不到是谁点的 —— 和工作流接管那条口同一个规矩。

## 四种「点不了」要分开说(它们让人做完全不同的下一步)

| 管理后台回的 | 门店这边说 | 下一步 |
|---|---|---|
| 404 NO_MEMBERSHIP | 你绑定的后台账号没登记进这个项目 | 找管理员登记成员 |
| 404 NOT_FOUND     | 这张单不在你店里,或已经没了       | 回列表刷新 |
| 409 CANNOT_DECIDE | 这张单已经结束(过期 / 处理过了),不能再处理 | 不用再点 |
| 409 REVISION_CONFLICT | 别人刚处理过这张单            | 刷新看最新的再决定 |

⚠️ **revision 由前端带上它看到的那一版,这里不替它重读。** 评分那条口(`_评一次检索`)先读详情再带 If-Match,
是因为评分没有「看过的内容」;而批一张单,人是**对着某一版内容**点的 —— 这里替他重读最新版再提交,
等于让他批了一版他没看过的,乐观锁就形同虚设。
"""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
服务身份 = os.environ.get("AIMC_USER", "U001")


def _调(方法, 路径, 身份, 体=None, 头=None, timeout=20):
    """→ (http 码, 回体 dict)。连不上 → (0, {})。4xx/5xx 也把回体读回来(要按 code 分开说)。"""
    h = {"X-Dev-User": 身份, **(头 or {})}
    data = None
    if 体 is not None:
        data = json.dumps(体, ensure_ascii=False).encode()
        h["content-type"] = "application/json"
    q = urllib.request.Request(f"{基址}/api/v1/projects/{项目}{路径}", data=data, method=方法, headers=h)
    try:
        with urllib.request.urlopen(q, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"_异常": type(e).__name__}


def 人话(码, d):
    """管理后台的错误 → `{error, 怎么办, code}`。四种「点不了」分开说(见文件头那张表)。"""
    d = d if isinstance(d, dict) else {}
    c, msg, adv = d.get("code") or "", d.get("message") or "", d.get("advice") or ""
    if 码 == 0:
        return {"code": "UNREACHABLE", "error": f"连不上管理后台({基址})",
                "怎么办": "管理后台没起或网络断了 —— 这张单的状态没变,过一会儿再试"}
    if 码 == 404 and c == "NO_MEMBERSHIP":
        return {"code": c, "error": "你绑定的管理后台账号还没登记进这个项目",
                "怎么办": "请管理员在管理后台「成员」里把它登记上(登记时可以填门店)"}
    if 码 == 404:
        return {"code": c or "NOT_FOUND", "error": "这张待办不在你店里,或者已经没了",
                "怎么办": "回待办列表刷新一下 —— 你只看得到本店的单子"}
    if 码 == 409 and c == "CANNOT_DECIDE":
        return {"code": c, "error": "这张待办已经结束了(过期或已经有人处理过),不能再处理",
                "怎么办": "不用再点。" + (adv[:200] if adv else "")}
    if 码 == 409 and c == "REVISION_CONFLICT":
        return {"code": c, "error": "别人刚处理过这张待办",
                "怎么办": "刷新看最新的状态再决定 —— 不会拿你看到的旧版本盖掉别人的决定"}
    if 码 == 403 and c == "CANNOT_DECIDE":
        return {"code": c, "error": f"你现在不能处理这张:{msg[:160]}", "怎么办": adv[:300] or "找能批这一类单子的人处理"}
    if 码 == 403:
        return {"code": c or "FORBIDDEN", "error": f"没有权限:{msg[:160]}", "怎么办": adv[:300] or "找管理员确认你的角色"}
    if 码 == 422:
        fe = d.get("field_errors") or {}
        return {"code": c or "VALIDATION", "error": (msg or "填的内容不合格")[:200],
                "怎么办": ";".join(f"{k}:{v}" for k, v in fe.items())[:300] or adv[:300] or "按提示改了再提交",
                "字段错": fe}
    return {"code": c or f"HTTP_{码}", "error": f"管理后台没办成({码}):{msg[:160]}",
            "怎么办": adv[:300] or "过一会儿再试;一直不行就去管理后台待办里处理"}


def 绑定账号(工号):
    """澜绣工号 → (后台账号 | None, 错误 | None)。用服务账号读绑定表;没绑定 → (None, None)。"""
    工号 = str(工号 or "").strip()
    if not 工号:
        return None, None
    码, d = _调("GET", "/staff-bindings", 服务身份)
    if 码 != 200:
        return None, 人话(码, d)
    for x in d.get("items") or []:
        if str(x.get("澜绣工号") or "").strip() == 工号:
            return x.get("账号"), None
    return None, None


def _以本人(me):
    """→ (后台账号, None) 或 (None, (http, 回体))。没登录 / 没绑定 / 查绑定失败都在这里挡掉。"""
    if not me or not me.get("no"):
        return None, (401, {"error": "没登录", "code": "NOT_LOGGED_IN"})
    账号, 错 = 绑定账号(me.get("no"))
    if 错:
        return None, (502, 错)
    if not 账号:
        return None, (403, {"code": "NOT_BOUND", "error": f"你的工号 {me.get('no')} 没有绑定管理后台账号",
                            "怎么办": "去管理后台的待办里处理;或请管理员在「账号绑定」里把你绑上,之后就能在这里处理"})
    return 账号, None


def 列表(me, 状态=None):
    """默认只列「我现在能处理的」(mine=true);状态=expired 列已过期的(看看错过了什么,不能处理)。"""
    账号, 挡 = _以本人(me)
    if 挡:
        return 挡
    if 状态 == "expired":
        码, d = _调("GET", "/human-requests?status=expired&limit=50", 账号)
    else:
        码, d = _调("GET", "/human-requests?mine=true&limit=50", 账号)
    if 码 != 200:
        return (码 or 502), 人话(码, d)
    项 = [{"id": x.get("id"), "类型": x.get("kind"), "状态": x.get("status"), "截止": x.get("expires_at"),
          "门店": x.get("门店"), "风险说明": x.get("risk_note"), "还能处理吗": x.get("还能处理吗"),
          "为什么不能处理": x.get("为什么不能处理"), "发起时间": x.get("created_at")}
         for x in d.get("items") or []]
    return 200, {"ok": True, "items": 项, "我的门店": d.get("我的门店"), "以谁的身份": 账号,
                 "只看我能处理的": 状态 != "expired"}


def _表单(核对材料):
    """核对材料 → (表单 | None, 已填内容)。表单 = {说明, 字段[], 按钮[]};已填 = 其余键(人要对着它核)。"""
    m = 核对材料 if isinstance(核对材料, dict) else {}
    f = m.get("__表单") if isinstance(m.get("__表单"), dict) else None
    已填 = {k: v for k, v in m.items() if not str(k).startswith("__")}
    if not f:
        return None, 已填
    return {"说明": f.get("说明") or "",
            "字段": [x for x in (f.get("字段") or []) if isinstance(x, dict) and x.get("name")],
            "按钮": [x for x in (f.get("按钮") or []) if isinstance(x, dict) and x.get("id")]}, 已填


def 详情(me, rid):
    账号, 挡 = _以本人(me)
    if 挡:
        return 挡
    rid = str(rid or "").strip()
    if not rid:
        return 400, {"error": "缺待办编号", "code": "BAD_REQUEST"}
    码, d = _调("GET", "/human-requests/" + quote(rid, safe=""), 账号)
    if 码 != 200:
        return (码 or 502), 人话(码, d)
    请 = d.get("请求") or {}
    表单, 已填 = _表单(d.get("核对材料"))
    终态 = 请.get("status") in ("expired", "approved", "rejected", "cancelled")
    能 = bool(d.get("你能处理吗")) and not 终态
    return 200, {"ok": True, "id": 请.get("id") or rid, "类型": 请.get("kind"), "状态": 请.get("status"),
                 "revision": 请.get("revision"), "截止": (d.get("证据") or {}).get("截止时间"),
                 "门店": d.get("门店"), "风险说明": 请.get("risk_note"),
                 "表单": 表单, "已填": 已填, "允许编辑的字段": d.get("允许编辑的字段") or [],
                 # 已过期 / 已处理 → 只读:页面不画按钮。能不能点仍由管理后台在决定时再判一次
                 "能处理吗": 能, "为什么": (None if 能 else (d.get("为什么") or ("这张单已经结束了" if 终态 else None))),
                 "决定历史": d.get("决定历史") or [], "以谁的身份": 账号}


def 决定(me, 体):
    """体 = {id, decision, revision, edits?, reason?, key}。decision 原样透传(按钮 id / approved / rejected)。"""
    账号, 挡 = _以本人(me)
    if 挡:
        return 挡
    体 = 体 if isinstance(体, dict) else {}
    rid = str(体.get("id") or "").strip()
    决 = str(体.get("decision") or "").strip()
    键 = str(体.get("key") or "").strip()
    rev = 体.get("revision")
    缺 = [n for n, v in (("id", rid), ("decision", 决), ("key", 键)) if not v]
    if rev is None or isinstance(rev, bool) or not isinstance(rev, int):
        缺.append("revision")
    if 缺:
        return 400, {"code": "BAD_REQUEST", "error": "缺 " + " / ".join(缺),
                     "怎么办": "从待办详情里点按钮提交 —— revision 是你看到的那一版,没有它就分不清你批的是哪一版"}
    edits = 体.get("edits") if isinstance(体.get("edits"), dict) else {}
    # 幂等键带上工号和单号:同一个人对同一张单的同一次点击只记一条;别人的键撞不上
    幂等 = f"chat:{me.get('no')}:{rid}:{键}"[:200]
    码, d = _调("POST", "/human-requests/" + quote(rid, safe="") + "/decisions", 账号,
               体={"decision": 决, "request_revision": rev, "edits": edits,
                   "reason": (str(体.get("reason") or "").strip() or None)},
               头={"Idempotency-Key": 幂等})
    if 码 not in (200, 201):
        return (码 or 502), 人话(码, d)
    return 200, {"ok": True, "记了吗": d.get("记了吗"), "当前状态": d.get("当前状态"), "decision": d.get("decision"),
                 "新的revision": d.get("新的 revision"), "处理人": d.get("处理人") or 账号,
                 "说明": ("同一次点击重复提交,没有记第二条" if d.get("记了吗") is False else (d.get("note") or ""))}
