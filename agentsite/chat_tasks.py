# -*- coding: utf-8 -*-
"""聊天站里的「我的定时」—— 员工交给助手的定时任务(11-22,用户拍七条;方案《澜绣云裳agent-员工定时agent任务方案-20261122》)。
    GET  /api/chat-tasks              我的任务(本人工号)
    GET  /api/chat-task-templates     三个模板按钮
    GET  /api/chat-task-runs?id=…     一条任务的执行记录
    GET  /api/chat-task-inbox         站内收件箱(未读数 + 最近结果)
    POST /api/chat-task               建 {title, instruction, task_mode, role_key?, 规则}
    POST /api/chat-task/update        改 {id, revision, …要改的字段}
    POST /api/chat-task/archive       归档 {id, revision}
    POST /api/chat-task/run-now       立即跑一次 {id}
    POST /api/chat-task-run/read      标已读 {run_id}
## 身份
任务归**登录工号**(staff_code);去管理后台用服务账号(AIMC_USER)调,但每一条都带 `staff_code=本人工号`——
列表只拿他的、改 / 归档 / 跑一次服务端按 staff_code 核(不是他的 → 404),这里一条权限都不另判。
到点那一轮是管理后台 worker 调 /internal/chat 以这个工号跑的(只读),不经过这里。
"""
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
服务身份 = os.environ.get("AIMC_USER", "U001")


def _调(方法, 路径, 体=None, 头=None, timeout=20):
    """→ (http 码, 回体 dict)。连不上 → (0, {})。"""
    h = {"X-Dev-User": 服务身份, **(头 or {})}
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
    except Exception as e:  # noqa: BLE001
        return 0, {"_异常": type(e).__name__}


def 人话(码, d):
    d = d if isinstance(d, dict) else {}
    c, msg, adv = d.get("code") or "", d.get("message") or "", d.get("advice") or ""
    if 码 == 0:
        return {"code": "UNREACHABLE", "error": f"连不上管理后台({基址})", "怎么办": "管理后台没起或网络断了,过一会儿再试"}
    if 码 == 404:
        return {"code": c or "NOT_FOUND", "error": "没有这条定时任务,或它不是你的", "怎么办": "回「我的定时」刷新"}
    if 码 == 409 and c == "CHAT_TASK_BUSY":
        return {"code": c, "error": "这条任务已经有一次在排队 / 进行中", "怎么办": "等它跑完再点「跑一次」"}
    if 码 == 409:
        return {"code": c or "CONFLICT", "error": "这条任务刚被改过", "怎么办": "刷新看最新的再改"}
    if 码 == 422:
        字段 = d.get("field_errors") or {}
        return {"code": c or "VALIDATION", "error": msg or "填的内容不对", "怎么办": ";".join(f"{k}:{v}" for k, v in 字段.items()) or adv}
    if 码 == 403:
        return {"code": c or "FORBIDDEN", "error": "服务账号没权限调这条接口", "怎么办": "找管理员看管理后台成员权限"}
    return {"code": c or f"HTTP_{码}", "error": msg or f"管理后台回了 {码}", "怎么办": adv or "过一会儿再试"}


def _要登录(me):
    if not me or not me.get("no"):
        return 401, {"ok": False, "error": "没登录 —— 定时任务是记在你工号上的", "怎么办": "先登录"}
    return None


_码样 = re.compile(r"^[A-Za-z0-9]{2,32}$")


def _门店码(me):
    """登录身份里 shop 是「SH001 静安旗舰店」这种文字(backend/auth.who),门店编号取第一段;有 shop_code 就直接用。认不出 → None(不限门店)。"""
    c = (me or {}).get("shop_code")
    if c and _码样.match(str(c)):
        return str(c).upper()
    头 = str((me or {}).get("shop") or "").split()
    return 头[0].upper() if 头 and _码样.match(头[0]) else None


def 是店长(me):
    return (me or {}).get("role") == "店长"


def _范围参数(me):
    """改 / 归档 / 跑一次 带的身份:本人工号;店长再带本店编号(服务端:是他的或在他店里才认 —— 用户拍 ⑦)。"""
    参 = {"staff_code": me["no"]}
    if 是店长(me) and _门店码(me):
        参["store_id"] = _门店码(me)
    return 参


def 列表(me, 范围=None):
    """范围="本店":店长看本店所有人的(用户拍 ⑦);别人传了也只回自己的。"""
    e = _要登录(me)
    if e: return e
    本店 = 范围 == "本店" and 是店长(me) and _门店码(me)
    参 = {"store_id": _门店码(me), "limit": 100} if 本店 else {"staff_code": me["no"], "limit": 100}
    码, d = _调("GET", "/chat-tasks?" + urlencode(参))
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, "items": d.get("items") or [], "总数": d.get("total"), "note": d.get("note"), "工号": me["no"],
                 "范围": ("本店 " + _门店码(me)) if 本店 else "我的", "是店长": 是店长(me), "门店": _门店码(me)}


def 模板(me):
    e = _要登录(me)
    if e: return e
    码, d = _调("GET", "/chat-task-templates")
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, "items": d.get("items") or []}


def 建(me, body):
    e = _要登录(me)
    if e: return e
    体 = {k: body.get(k) for k in ("title", "instruction", "task_mode", "role_key", "规则", "note") if body.get(k) is not None}
    体["staff_code"] = me["no"]
    体["store_id"] = _门店码(me)
    码, d = _调("POST", "/chat-tasks", 体)
    if 码 != 201:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 201, {"ok": True, **d}


def 改(me, body):
    e = _要登录(me)
    if e: return e
    tid, rev = str(body.get("id") or ""), body.get("revision")
    if not tid or rev is None:
        return 400, {"ok": False, "error": "要带 id 和 revision", "怎么办": "刷新列表再改"}
    体 = {k: body[k] for k in ("title", "instruction", "task_mode", "role_key", "规则", "status", "note") if k in body}
    码, d = _调("PATCH", f"/chat-tasks/{quote(tid)}?" + urlencode(_范围参数(me)), 体, 头={"If-Match": str(rev)})
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, **d}


def 归档(me, body):
    e = _要登录(me)
    if e: return e
    tid, rev = str(body.get("id") or ""), body.get("revision")
    if not tid or rev is None:
        return 400, {"ok": False, "error": "要带 id 和 revision", "怎么办": "刷新列表再试"}
    码, d = _调("POST", f"/chat-tasks/{quote(tid)}/archive?" + urlencode(_范围参数(me)), 头={"If-Match": str(rev)})
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, **d}


def 跑一次(me, body):
    e = _要登录(me)
    if e: return e
    tid = str(body.get("id") or "")
    if not tid:
        return 400, {"ok": False, "error": "要带 id", "怎么办": ""}
    码, d = _调("POST", f"/chat-tasks/{quote(tid)}/run-now?" + urlencode(_范围参数(me)))
    if 码 != 202:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 202, {"ok": True, **d}


def 结果(me, tid):
    e = _要登录(me)
    if e: return e
    if not tid:
        return 400, {"ok": False, "error": "要带 id", "怎么办": ""}
    码, d = _调("GET", f"/chat-tasks/{quote(tid)}/runs?" + urlencode({"staff_code": me["no"], "limit": 30}))
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, "items": d.get("items") or []}


def 收件箱(me):
    e = _要登录(me)
    if e: return e
    码, d = _调("GET", "/chat-task-inbox?" + urlencode({"staff_code": me["no"], "limit": 30}))
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, "未读": d.get("未读", 0), "items": d.get("items") or []}


def 已读(me, body):
    e = _要登录(me)
    if e: return e
    rid = str(body.get("run_id") or "")
    if not rid:
        return 400, {"ok": False, "error": "要带 run_id", "怎么办": ""}
    码, d = _调("POST", f"/chat-task-runs/{quote(rid)}/read?" + urlencode({"staff_code": me["no"]}))
    if 码 != 200:
        return (码 or 502), {"ok": False, **人话(码, d)}
    return 200, {"ok": True, **d}
