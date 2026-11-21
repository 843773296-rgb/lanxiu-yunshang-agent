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
            "有效至": 卡["expires_at"], "结果": 卡.get("result"), "结果元": 卡.get("result_meta")}


def 完整结果(aid, me):
    """→ (HTTP 码, 返回体)。只给发起人本人;完整结果是原样 JSON 文本 + 哈希 + 字节(复审 P1-02:摘要不能替代完整回执)。"""
    库 = 卡库()
    if not 库:
        return 404, {"error": "确认卡功能没开"}
    卡 = PA.取(库, aid)
    if not 卡 or str(卡["asker_no"]) != str((me or {}).get("no")):
        return 404, {"error": "没有这张确认卡,或者它不是你发起的"}
    r = PA.取完整结果(库, aid)
    if not r:
        return 404, {"error": "这张卡还没有执行结果"}
    return 200, {"id": aid, "状态": 卡["status"], **r}


def 本轮卡(trace):
    库 = 卡库()
    return [卡给页面(k) for k in PA.本轮的(库, trace)] if 库 and trace else []


def 解读输出(stdout, stderr=""):
    """工具服务回了什么 → (状态, 结果)。状态 ∈ 成功 / 失败 / 未执行 / 不确定(复审 P0-01,用户 11-21 拍):
    · 有 id=2 的结果:isError 或带 error → 失败;文本说「还没有执行」→ 未执行(工具服务自己说的,指纹对不上);否则 成功
    · **没有 id=2 的结果** → 不确定:进程回来了却没回执,不能证明没落库(原来写「没执行」—— 缺回执不等于没做)"""
    for 行 in (stdout or "").splitlines():
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
            return "失败", out if isinstance(out, dict) else {"error": txt}
        if isinstance(out, dict) and "还没有执行" in str(out.get("text", "")):
            return "未执行", {"error": "工具服务没认出这次确认(参数指纹对不上)—— 没执行"}
        return "成功", out
    return "不确定", {"error": "工具服务没有回结果 —— **不知道做没做**(进程回来了却没回执,不能当成没执行)", "stderr": (stderr or "")[-300:]}


def _调一次(卡, me):
    """→ (状态, 结果 dict),状态 ∈ 成功 / 失败 / 未执行 / 不确定。起一个只挂这一个工具的服务进程,带上参数指纹,发一次 tools/call。"""
    import sdk
    全 = f"mcp__{卡['domain']}__{卡['tool']}" if 卡.get("domain") else 卡["tool"]
    配 = sdk.mcp_config(me, 名单=[全], trace=卡.get("trace"))
    if len(配) != 1:
        return "未执行", {"error": f"找不到这个工具所在的服务({全})—— 没执行"}
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
        return "不确定", {"error": "执行超时(120 秒)—— ⚠️ 这一笔**可能已经落库**,不要重来;已转人工核对"}
    return 解读输出(p.stdout, p.stderr)


状态字 = {"成功": "已成功", "失败": "已失败", "未执行": "未执行", "不确定": "核对中"}


def _转人工核对(卡, me, 结果):
    """结果不确定 → 建一条「聊天转人工」待办让人去业务库核对(复审 P0-01「无法核对的接口转人工」)。建不成只记在结果里,不改卡的状态。"""
    try:
        import answer_feedback as AF
        编号, 错 = AF.建转人工(me, 原话=f"确认卡 {卡['id']}:{卡['tool']} {json.dumps(卡.get('args') or {}, ensure_ascii=False)[:300]}",
                             轮号=卡.get("trace") or f"card:{卡['id']}", 会话号=卡.get("session"), 意图="写操作结果核对",
                             原因=f"店员点了确认,工具没有及时回结果({str((结果 or {}).get('error') or '')[:120]})—— 可能已落库,请到业务系统核对后告诉店员;卡上已拦住重复操作")
        return {"转人工待办": 编号} if 编号 else {"转人工失败": 错}
    except Exception as e:  # noqa: BLE001 —— 转人工挂了不改「核对中」这个结论,只把原因带回卡上
        return {"转人工失败": f"{type(e).__name__}: {e}"[:200]}


def 确认(aid, me):
    """→ (HTTP 码, 返回体)。ok 只在「已成功」为真;「核对中」给 ok=False + 状态,页面按状态显示,不按 ok 猜。"""
    库 = 卡库()
    if not 库:
        return 404, {"error": "确认卡功能没开"}
    卡, 错 = PA.领取(库, aid, me)
    if 错:
        return 错[0], {"error": 错[1]}
    try:
        态, 结果 = _调一次(卡, me)
    except Exception as e:
        # 自己这边炸了(配置 / 进程起不来)—— 工具可能一下都没碰到,但也可能是回来之后才炸;照「不确定」处理,拦住重复
        态, 结果 = "不确定", {"error": f"{type(e).__name__}: {e}"[:300]}
    if 态 == "不确定":
        结果 = {**(结果 or {}), **_转人工核对(卡, me, 结果)}
    PA.收尾(库, 卡["id"], 态 == "成功", 结果, 状态=状态字[态])
    卡 = PA.取(库, 卡["id"])
    return 200, {"ok": 态 == "成功", "状态": 卡["status"], "卡": 卡给页面(卡)}


def 取消(aid, me):
    库 = 卡库()
    if not 库:
        return 404, {"error": "确认卡功能没开"}
    卡, 错 = PA.取消(库, aid, me)
    if 错:
        return 错[0], {"error": 错[1]}
    return 200, {"ok": True, "卡": 卡给页面(卡)}
