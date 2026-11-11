# -*- coding: utf-8 -*-
"""写操作确认卡 · 聊天站这一半(用户 2026-11-11 拍)。存储与状态在 backend/pending_actions.py,拦截在 mcp/protocol.py。

这里做三件事:
  ① 卡给页面:页面要画的那几样(对象 / 参数 / 有效至 / 状态),不带内部指纹
  ② 点「确认」:核对 → 原子领取 → **用和模型同一个工具服务、同一份参数**再调一次(env 带参数指纹才放行)→ 记结局
  ③ 点「暂不执行」

为什么执行要走工具服务、不直接调 api 函数:写入判定、身份、角色名单收窄、出门遮挡全在那条路上,
直接调函数就是**第二条写入路径** —— 两条路迟早不一样,而不一样时不会报错。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))
import pending_actions as PA      # noqa: E402


def 卡库():
    """聊天站进程设了 LANXIU_CONFIRM_STORE 才开(plist 里);没设 = 这个功能关着,写操作照旧直接执行。"""
    return os.environ.get("LANXIU_CONFIRM_STORE") or None


def 评测环境(基=None, **加):
    """聊天站进程起**评测**子进程时用的环境:剥掉 LANXIU_CONFIRM_STORE(eureka-fc 11-11 提醒)。
    开关在聊天站的 plist 里,而子进程会继承 —— 不剥的话评测里的写操作全变成「已建卡,等人确认」,
    写操作题分数骤降,**和模型退步在成绩单上长得一模一样**,而评测自己分不出来(返回是合法的)。"""
    环 = {k: v for k, v in (os.environ if 基 is None else 基).items() if k != "LANXIU_CONFIRM_STORE"}
    环.update(加)
    return 环


def 卡给页面(卡):
    return {"id": 卡["id"], "工具": 卡["tool"], "参数": 卡["args"], "状态": 卡["status"],
            "有效至": 卡["expires_at"], "结果": 卡.get("result")}


def 本轮卡(trace):
    库 = 卡库()
    return [卡给页面(k) for k in PA.本轮的(库, trace)] if 库 and trace else []


def _调一次(卡, me):
    """→ (成功, 结果 dict)。起一个只挂这一个工具的服务进程,带上参数指纹,发一次 tools/call。"""
    import sdk
    全 = f"mcp__{卡['domain']}__{卡['tool']}" if 卡.get("domain") else 卡["tool"]
    配 = sdk.mcp_config(me, 名单=[全], trace=卡.get("trace"))
    if len(配) != 1:
        return False, {"error": f"找不到这个工具所在的服务({全})—— 没执行"}
    cfg = next(iter(配.values()))
    env = {**os.environ, **cfg["env"], "LANXIU_CONFIRMED": 卡["fingerprint"]}
    消息 = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "lanxiu-confirm", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": 卡["tool"], "arguments": 卡["args"]}}]
    try:
        p = subprocess.run([cfg["command"], *cfg["args"]], input="\n".join(json.dumps(m, ensure_ascii=False) for m in 消息) + "\n",
                           capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired:
        return False, {"error": "执行超时(120 秒)—— ⚠️ 这一笔**可能已经落库**,先查一下再决定要不要重来"}
    for 行 in p.stdout.splitlines():
        try:
            r = json.loads(行)
        except ValueError:
            continue
        if r.get("id") != 2:
            continue
        res = r.get("result") or {}
        txt = "".join(c.get("text", "") for c in (res.get("content") or []))
        try:
            out = json.loads(txt)
        except ValueError:
            out = {"text": txt}
        if res.get("isError") or (isinstance(out, dict) and out.get("error")):
            return False, out if isinstance(out, dict) else {"error": txt}
        if isinstance(out, dict) and "还没有执行" in str(out.get("text", "")):
            return False, {"error": "工具服务没认出这次确认(参数指纹对不上)—— 没执行"}
        return True, out
    return False, {"error": "工具服务没有回结果 —— 没执行(stderr:" + (p.stderr or "")[-300:] + ")"}


def 确认(aid, me):
    """→ (HTTP 码, 返回体)。"""
    库 = 卡库()
    if not 库:
        return 404, {"error": "确认卡功能没开"}
    卡, 错 = PA.领取(库, aid, me)
    if 错:
        return 错[0], {"error": 错[1]}
    try:
        成, 结果 = _调一次(卡, me)
    except Exception as e:
        成, 结果 = False, {"error": f"{type(e).__name__}: {e}"[:300]}
    PA.收尾(库, 卡["id"], 成, 结果)
    return 200, {"ok": 成, "卡": 卡给页面(PA.取(库, 卡["id"]))}


def 取消(aid, me):
    库 = 卡库()
    if not 库:
        return 404, {"error": "确认卡功能没开"}
    卡, 错 = PA.取消(库, aid, me)
    if 错:
        return 错[0], {"error": 错[1]}
    return 200, {"ok": True, "卡": 卡给页面(卡)}
