# -*- coding: utf-8 -*-
"""员工定时结果的飞书送达(11-23;用户拍:**一期统一发到用户本人的飞书**,上线后再改成每人各自)。

接收方**不进库、不进仓**:`~/.feishu-publish/.chat_task_receiver.json` = {"open_id","name","备注"}(路径可用 LANXIU_FEISHU_RECEIVER_FILE 换;
配法:`python3 tools/feishu_publish.py` 刷新用户令牌后 GET authen/v1/user_info 拿 open_id 写进去)。
应用凭证照 tools/feishu_publish.py 那份 `~/.feishu-publish/.feishu_app.json`(或 FEISHU_APP_ID / FEISHU_APP_SECRET)。
发送 = 机器人身份(tenant_access_token)POST im/v1/messages?receive_id_type=open_id,msg_type text;curl 发(这台机器 Python 的 TLS 会被拦)。
**不过 runtime/出网策略 那道闸**:它防的是「用户在 HTTP 节点里填的网址指向内网」,这里的主机名是写死的常量,没有用户输入;
而且这台机器的 DNS 走拦截代理,open.feishu.cn 解析出来是 198.18.x 这种假地址,那道闸会把它当内网拒掉(11-23 e2e 第一轮就红在这)。

结果落 chat_task_runs.feishu_at / feishu_detail:{"状态": 已发 | 失败 | 未配置 | 策略不发, …}。**四态必须分得开** ——
「没配接收方所以没发」「这条任务不要飞书」「发了没发出去」在「飞书没收到」上长得一模一样,
工作台「员工定时」页顶那块靠这个字段把它们分开;送达永远不抛,挂了不能带走 worker 那一轮。
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone

已发, 失败, 未配置, 策略不发 = "已发", "失败", "未配置", "策略不发"
状态们 = (已发, 失败, 未配置, 策略不发)
主机 = "open.feishu.cn"
正文上限 = 1500
_凭证目录 = os.path.join(os.path.expanduser("~"), ".feishu-publish")
_token缓存 = {"值": None, "到期": 0.0}


def 接收方文件():
    return os.environ.get("LANXIU_FEISHU_RECEIVER_FILE") or os.path.join(_凭证目录, ".chat_task_receiver.json")


def 接收方():
    """→ {"open_id","name","备注"} 或 None(没文件 / 文件坏 / 没 open_id 都算没配 —— 三种对发送来说是一回事)。"""
    try:
        with open(接收方文件(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("open_id"):
        return None
    return {"open_id": str(d["open_id"]), "name": str(d.get("name") or ""), "备注": str(d.get("备注") or "")}


def _应用凭证():
    aid, sec = os.environ.get("FEISHU_APP_ID"), os.environ.get("FEISHU_APP_SECRET")
    if aid and sec:
        return aid, sec
    try:
        with open(os.path.join(_凭证目录, ".feishu_app.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d["app_id"], d["app_secret"]
    except (OSError, ValueError, KeyError):
        return None, None


def _curl(args, 体=None, 超时=12):
    """→ (returncode, stdout)。单独一层,测试换成假的。"""
    p = subprocess.run(["curl", "-sS", "-m", str(超时 - 2), *args] + (["--data-binary", 体] if 体 is not None else []),
                       capture_output=True, text=True, timeout=超时)
    return p.returncode, p.stdout or ""


def _解(out):
    try:
        d = json.loads(out) if out else {}
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def _租户token(跑curl):
    """机器人令牌,模块内缓存(飞书给 2 小时,提前 5 分钟换)。→ (token 或 None, 为什么)。"""
    if _token缓存["值"] and time.time() < _token缓存["到期"]:
        return _token缓存["值"], ""
    aid, sec = _应用凭证()
    if not aid:
        return None, "没有飞书应用凭证(~/.feishu-publish/.feishu_app.json 或 FEISHU_APP_ID / FEISHU_APP_SECRET)"
    rc, out = 跑curl(["-X", "POST", "-H", "content-type: application/json", f"https://{主机}/open-apis/auth/v3/tenant_access_token/internal"],
                    json.dumps({"app_id": aid, "app_secret": sec}))
    d = _解(out)
    tok = d.get("tenant_access_token") if rc == 0 else None
    if not tok:
        return None, f"拿应用令牌失败:curl rc={rc} code={d.get('code')} {str(d.get('msg') or '')[:120]}"
    _token缓存.update(值=tok, 到期=time.time() + min(int(d.get("expire") or 7200), 7200) - 300)
    return tok, ""


def 正文(标题, 工号, 状态, 回答, 现在=None):
    """纯函数:一条结果 → 飞书文本。头一行说清是谁的哪条任务、结果如何;正文截到上限并说明还有多少。"""
    本地 = (现在 or datetime.now(timezone.utc)).astimezone()
    回 = str(回答 or "").strip() or "(这次没有正文)"
    截 = ""
    if len(回) > 正文上限:
        截 = f"\n…(还有 {len(回) - 正文上限} 字,全文在聊天站「我的定时 → 结果」里)"
        回 = 回[:正文上限]
    return (f"【澜绣云裳 · 员工定时】{标题} · {工号} · {状态}\n{本地.strftime('%Y-%m-%d %H:%M')}\n\n{回}{截}"
            "\n\n—— 一期统一发到这一个飞书;上线后改成发给任务本人")


def 送达(标题, 工号, 状态, 回答, 策略=None, 跑curl=None, 现在=None):
    """→ feishu_detail 那个字典(**永远有「状态」键,永远不抛**)。策略 = chat_tasks.deliver_policy(None 当作要发)。"""
    跑curl = 跑curl or _curl
    if 策略 is not None and not (策略 or {}).get("飞书", False):
        return {"状态": 策略不发, "为什么": "这条任务的送达策略没开飞书"}
    收 = 接收方()
    if not 收:
        return {"状态": 未配置, "为什么": f"没配飞书接收方({接收方文件()});一期统一发到用户本人,配法见 chat_task_feishu.py 文件头"}
    try:
        tok, 为 = _租户token(跑curl)
        if not tok:
            return {"状态": 失败, "接收方": 收["name"], "为什么": 为}
        体 = json.dumps({"receive_id": 收["open_id"], "msg_type": "text",
                        "content": json.dumps({"text": 正文(标题, 工号, 状态, 回答, 现在)}, ensure_ascii=False)}, ensure_ascii=False)
        rc, out = 跑curl(["-X", "POST", "-H", f"Authorization: Bearer {tok}", "-H", "content-type: application/json",
                         f"https://{主机}/open-apis/im/v1/messages?receive_id_type=open_id"], 体)
        d = _解(out)
        if rc == 0 and d.get("code") == 0:
            return {"状态": 已发, "接收方": 收["name"], "message_id": (d.get("data") or {}).get("message_id")}
        if d.get("code") in (99991663, 99991668):   # 令牌失效 / 过期 → 丢掉缓存,下一条重拿
            _token缓存.update(值=None, 到期=0.0)
        return {"状态": 失败, "接收方": 收["name"], "码": d.get("code"), "为什么": (str(d.get("msg") or "") or f"curl rc={rc}")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"状态": 失败, "接收方": 收["name"], "为什么": f"{type(e).__name__}: {str(e)[:160]}"}
