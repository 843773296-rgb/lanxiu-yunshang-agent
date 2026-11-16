#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 请求节点(三期 3-1)的执行核心 —— 11-16 起写;**发送之外的每一步都能离线测**。

怎么接进运行时(定下来的,见 HANDOFF 11-16):
  worker 给 跑一张图 的 适配器 加 "http_request" → 本模块 `跑节点`;它**不自己发**,
  而是拿连接合成一份契约交给 `tool_gateway.执行`(六道闸、记事、账本照旧;只读级不记账本),
  网关的 适配器["http"] 才是 `发送`。`runtime/tool_gateway.py` 文件头:运行时能自己发一次 HTTP,边界就没了。

安全决定(11-12 设计稿 H1–H6,用户 11-12 拍「按推荐」)在 `出网策略.py`;密钥在 `secretref.凭据头`。
这里只管:拼地址 → 核 → 装头 → 发(curl,这台机器 Python 的 TLS 会被拦)→ 收(不跟重定向、限大小)→ 打码落记录。

⚠️ 节点配置里**没有任何地方能写密钥**:节点自己带的请求头里凭据类的键一律丢掉(H3),凭据只从连接的 secret_ref 来。
⚠️ 返回值、异常、记录里**不出现凭据**:请求头经 `secretref.遮头` 才放进结果。
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE), os.path.join(os.path.dirname(HERE), "contract")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import dsl as DS  # noqa: E402
import secretref as SR  # noqa: E402
import 出网策略 as 策略  # noqa: E402


class 请求被拒(Exception):
    """发送**之前**就拦下的(方法 / 白名单 / 禁区 / 凭据取不到)—— 一个字节都没出去。"""
    def __init__(self, code, 为什么):
        super().__init__(为什么)
        self.code, self.为什么 = code, 为什么


class 请求失败(Exception):
    """发出去了、但结果不能用(重定向 / 太大 / 发不出)—— 对方可能已经收到请求(只读,所以无副作用)。"""
    def __init__(self, code, 为什么):
        super().__init__(为什么)
        self.code, self.为什么 = code, 为什么


def 合成契约(连接, cfg):
    """连接(工具连接那一行:id / name / allowed_endpoints / secret_ref / auth)+ 节点配置 → 交给网关的契约。
    方法、超时、大小上限、白名单、凭据都在 **server_bound_arguments** 里 —— 模型 / 前端传了同名键会被网关闸②拒。"""
    方法 = str((cfg or {}).get("method") or "GET").upper()
    return {
        "name": f"http:{连接['id']}", "adapter": "http", "side_effect_type": DS.只读,
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["path"],
                         # query / headers 是任意键值(网关的 Schema 校验默认不收额外字段,这两处要明说收)
                         "properties": {"path": {"type": "string"},
                                        "query": {"type": "object", "additionalProperties": True},
                                        "headers": {"type": "object", "additionalProperties": True}}},
        "server_bound_arguments": {
            "method": 方法, "allowed_endpoints": list(连接.get("allowed_endpoints") or []),
            "endpoint_index": int((cfg or {}).get("endpoint_index") or 0),
            "secret_ref": 连接.get("secret_ref"), "auth": 连接.get("auth") or {},
            "timeout_seconds": int((cfg or {}).get("timeout_seconds") or 策略.默认超时秒),
            "max_bytes": int((cfg or {}).get("max_bytes") or 策略.响应上限字节),
            "connection_name": 连接.get("name")},
        "external_status_lookup": {"supported": False},
        "说明": f"HTTP {方法}(只读)经连接「{连接.get('name')}」",
    }


def 拼地址(允许的端点, path, query=None, endpoint_index=0):
    """path 是完整地址就原样用;是相对路径就拼到白名单第几项(默认第一项)后面;query 编成查询串。"""
    p = str(path or "").strip()
    if p.lower().startswith(("http://", "https://")):
        url = p
    else:
        端 = list(允许的端点 or [])
        if not 端:
            raise 请求被拒("HTTP_NOT_IN_ALLOWLIST", "这条连接没有登记任何「允许的端点」,拼不出地址 —— 先到「工具连接」里登记白名单")
        i = int(endpoint_index or 0)
        base = 端[i if 0 <= i < len(端) else 0].rstrip("/")
        url = base + ("/" + p.lstrip("/") if p else "")
    if query:
        if not isinstance(query, dict):
            raise 请求被拒("HTTP_QUERY_INVALID", "查询参数要是一组「名字: 值」")
        q = urllib.parse.urlencode({str(k): ("" if v is None else str(v)) for k, v in query.items()})
        url += ("&" if "?" in url else "?") + q
    return url


def curl命令(方法, url, 头, 超时秒, 上限字节, 头文件, 体文件):
    """只读 GET / HEAD;**不带 -L**(不跟重定向);--max-filesize 在传输层就掐住大小;超时按节点配置。"""
    cmd = ["curl", "-sS", "-o", 体文件, "-D", 头文件, "-w", "%{http_code}",
           "--max-time", str(int(超时秒)), "--max-filesize", str(int(上限字节)),
           "--proto", "=http,https", "-X", str(方法).upper(), url]
    if str(方法).upper() == "HEAD":
        cmd.insert(cmd.index("-X"), "-I")
    for k, v in (头 or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    return cmd


def _curl发(方法, url, 头, 超时秒, 上限字节):
    """真发送 → {"status": int, "headers": {小写名: 值}, "body": bytes}。走 curl + 项目的出网环境(代理)。"""
    import 真模型 as _真
    with tempfile.TemporaryDirectory() as td:
        头文件, 体文件 = os.path.join(td, "h"), os.path.join(td, "b")
        cmd = curl命令(方法, url, 头, 超时秒, 上限字节, 头文件, 体文件)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=int(超时秒) + 5, env=_真.curl环境())
        except subprocess.TimeoutExpired:
            raise 请求失败("HTTP_TIMEOUT", f"等了 {超时秒} 秒对方没回完 —— 对方慢或网络不通;要等更久在节点上调超时")
        if out.returncode == 63:
            raise 请求失败("HTTP_RESPONSE_TOO_LARGE", 策略.响应太大吗(上限字节 + 1, 上限字节)[1])
        if out.returncode == 28:
            raise 请求失败("HTTP_TIMEOUT", f"等了 {超时秒} 秒对方没回完 —— 对方慢或网络不通;要等更久在节点上调超时")
        if out.returncode != 0:
            # ⚠️ 不带 stderr 原文(可能回显地址里的东西),只给 curl 的退出码
            raise 请求失败("HTTP_SEND_FAILED", f"请求发不出去(curl 退出码 {out.returncode})—— 核对地址、网络和代理")
        try:
            status = int((out.stdout or "0").strip()[-3:])
        except ValueError:
            status = 0
        头们 = {}
        try:
            for 行 in open(头文件, encoding="latin-1").read().splitlines():
                if ":" in 行 and not 行.startswith("HTTP/"):
                    k, v = 行.split(":", 1)
                    头们[k.strip().lower()] = v.strip()
        except OSError:
            pass
        try:
            体 = open(体文件, "rb").read()
        except OSError:
            体 = b""
    return {"status": status, "headers": 头们, "body": 体}


def 发送(实参, *, 发=None, 解析=None):
    """网关放行后的真执行(网关 适配器["http"] 指向它)。实参 = 节点给的 path / query / headers + 契约绑的服务端参数。
    → {"status_code", "headers"(打码), "body", "json", "url", "请求头"(打码), "凭据来路"};拒 / 失败抛上面两个异常。"""
    方法 = str(实参.get("method") or "GET").upper()
    白 = 实参.get("allowed_endpoints") or []
    url = 拼地址(白, 实参.get("path"), 实参.get("query"), 实参.get("endpoint_index") or 0)
    行, 码, 为 = 策略.核请求(方法, url, 白, 解析)
    if not 行:
        raise 请求被拒(码, 为)
    鉴 = 实参.get("auth") or {}
    try:
        凭头, 来路 = SR.凭据头(实参.get("secret_ref"), 鉴.get("方式"), 鉴.get("头名"))
    except SR.解析不了 as e:
        raise 请求被拒("HTTP_SECRET_UNRESOLVED", f"这条连接的凭据取不到:{e} —— 到「工具连接」里核对凭据定位符和鉴权方式")
    # H3:节点自己带的头里,凭据类的键一律丢掉 —— 密钥只从连接来,节点里没地方写
    自带 = {str(k): str(v) for k, v in (实参.get("headers") or {}).items()
            if str(k).lower() not in SR._敏感头 and "token" not in str(k).lower() and "secret" not in str(k).lower()}
    全头 = {**自带, **凭头}
    超时, 上限 = int(实参.get("timeout_seconds") or 策略.默认超时秒), int(实参.get("max_bytes") or 策略.响应上限字节)
    r = (发 or _curl发)(方法, url, 全头, 超时, 上限)
    状态 = int(r.get("status") or 0)
    回头 = {str(k).lower(): str(v) for k, v in (r.get("headers") or {}).items()}
    码, 话 = 策略.遇到重定向(状态, 回头.get("location", ""))
    if 码:
        raise 请求失败(码, 话)
    体 = r.get("body") or b""
    太大, 话 = 策略.响应太大吗(len(体), 上限)
    if 太大:
        raise 请求失败("HTTP_RESPONSE_TOO_LARGE", 话)
    文本 = 体.decode("utf-8", "replace") if isinstance(体, (bytes, bytearray)) else str(体)
    try:
        j = json.loads(文本) if 文本.strip() else None
    except ValueError:
        j = None
    return {"status_code": 状态, "headers": SR.遮头(回头), "body": 文本, "json": j, "url": url,
            "请求头": SR.遮头(全头), "凭据来路": 来路, "execution_mode": "live"}


def 跑节点(cfg, 实参, *, 连接, 执行, 记事=None, 发=None, 解析=None):
    """runner 适配器["http_request"] 的实现:合成契约 → 经网关 `执行` → 结果。
    `执行` = tool_gateway.执行(注入,好测);`连接` = 这个节点选的工具连接那一行(dict)。"""
    契约 = 合成契约(连接, cfg)
    绑 = 契约["server_bound_arguments"]
    # 先在网关外核一遍地址(拼地址 + 方法 / 白名单 / 禁区):拦下的报它自己的码(HTTP_NOT_IN_ALLOWLIST 这类),
    # 不让网关把「一个字节都没发」包成「TOOL_ERROR 结果待核实」。发送函数里还会再核一次 —— 两道,不靠这一道
    url = 拼地址(绑["allowed_endpoints"], (实参 or {}).get("path"), (实参 or {}).get("query"), 绑["endpoint_index"])
    行, 码, 为 = 策略.核请求(绑["method"], url, 绑["allowed_endpoints"], 解析)
    if not 行:
        raise 请求被拒(码, 为)
    # 参数**原样**交给网关 —— 模型 / 前端带了服务端绑定的键(method 这类)由网关闸②拒,多了没登记的键由闸③拒;这里不先替它过滤
    请求 = {"name": 契约["name"], "arguments": dict(实参 or {})}
    回 = 执行(请求, 工具目录={契约["name"]: 契约}, 有效范围={}, 记事=记事,
           适配器={"http": lambda 实: 发送(实, 发=发, 解析=解析)})
    return 回.get("结果") if isinstance(回, dict) else 回
