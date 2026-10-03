#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实模型适配器 —— 和 `_mock生成` **同一个契约**,而它真的发请求。

## 为什么是 curl 而不是 urllib / SDK

这台机器上 Python 的 TLS 会被拦(项目记着「TLS 拦截,联网用 curl」)。
`connections_api._真探` 已经靠 curl 真发过请求并拿到过真实响应 ——
**这条路验证过**,所以照它走,不另开一条。

## 为什么不装 SDK

契约登记的是 `ModelProvider` **这一族**,不是某家的 SDK。
装一个 SDK 会把「协议长什么样」藏进它的版本里,
而这个后台要能在页面上**逐条解释一次调用发生了什么**
(审阅 §5.3 那张表:实际返回型号、每次尝试、token 用量、计价来源)——
那要求请求和响应都是看得见的。

## ⚠️ 失败就是失败

这里**没有任何退回 mock 的分支**。审阅 §5.4:
「真实调用失败不能静默降级为 mock」。
降级之后那次运行照样出一份答案,而那份答案和真模型给的形状一样。

> **一次悄悄换了模型的运行,比一次失败的运行难查得多。**

## ⚠️ 凭据

头从 `secretref.解析` 来,**只塞进 curl 的参数**,不落进返回值、
不进异常文字、不写日志。
"""
import json as _json
import os
import subprocess
import sys
import time

_这儿 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_这儿))
import secretref as SR  # noqa: E402


class 调不动(Exception):
    """真实调用失败。**不退回 mock** —— 带上够排查的东西,但不带凭据。"""

    def __init__(self, 码, 细节):
        self.码 = 码
        self.细节 = 细节
        super().__init__(f"{码}: {细节}")


def 生成(*, 连接, 系统, 用户, 参数=None, 超时=60):
    """真发一次生成。返回的形状和 `main._mock生成` **一致**。

    形状一致是有意的(规格 §19.4:mock 和真实实现同一契约),
    而**正因为形状一致,`execution_mode` 这个标记必须显眼** ——
    否则一份 mock 跑出来的报告和真实报告在数据形状上一模一样。
    """
    端点 = (连接 or {}).get("endpoint")
    引用 = (连接 or {}).get("secret_ref")
    型号 = ((参数 or {}).get("model")
            or (连接 or {}).get("model")
            or "claude-haiku-4-5")
    if not 端点 or not 引用:
        raise 调不动("MODEL_CONNECTION_INCOMPLETE",
                   f"连接里缺 {[k for k in ('endpoint', 'secret_ref') if not (连接 or {}).get(k)]}")
    try:
        头, 来路 = SR.解析(引用)
    except Exception as e:
        # ⚠️ 异常文字来自 secretref,它保证不带值
        raise 调不动("SECRET_UNRESOLVED", f"凭据定位符解析不了:{e}")

    包 = {"model": 型号,
          "max_tokens": int((参数 or {}).get("max_tokens") or 1024),
          "messages": [{"role": "user", "content": 用户 or ""}]}
    if 系统:
        包["system"] = 系统
    if (参数 or {}).get("temperature") is not None:
        包["temperature"] = (参数 or {})["temperature"]

    cmd = ["curl", "-sS", "-o", "-", "-w", "\n%{http_code}",
           "--max-time", str(超时), "-X", "POST", 端点,
           "-H", "content-type: application/json"]
    for k, v in 头.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["--data-binary", "@-"]

    t0 = time.time()
    try:
        out = subprocess.run(cmd, input=_json.dumps(包, ensure_ascii=False),
                             capture_output=True, text=True, timeout=超时 + 5)
    except Exception as e:
        # ⚠️ **发不出去也是失败,不是「那就跑 mock」。**
        raise 调不动("REQUEST_NOT_SENT", f"请求发不出去:{type(e).__name__}")
    ms = int((time.time() - t0) * 1000)

    行 = (out.stdout or "").strip().splitlines()
    码 = 行[-1] if 行 else ""
    正文 = "\n".join(行[:-1]) if len(行) > 1 else ""
    if not 码.startswith("2"):
        错 = None
        try:
            错 = ((_json.loads(正文) or {}).get("error") or {}).get("message")
        except Exception:
            pass
        # ⚠️ **非 2xx 当场抛。** 这个仓库 10-03 栽过一次反例:
        # 「接口非 2xx 就直写库」—— 而接口返的是「没权限」,
        # 于是一个被拒的动作被当成「接口不支持」绕过去了。
        raise 调不动("MODEL_CALL_FAILED",
                   f"http {码}(往返 {ms}ms):{(错 or 正文)[:200]}")
    try:
        j = _json.loads(正文)
    except Exception:
        raise 调不动("MODEL_BAD_JSON", f"2xx 而正文不是 JSON(前 120 字):{正文[:120]}")

    文 = "".join(b.get("text") or "" for b in (j.get("content") or [])
                 if isinstance(b, dict))
    u = j.get("usage") or {}
    return {
        "text": 文,
        "finish_reason": j.get("stop_reason") or "ok",
        # ⚠️ **报端点实际返回的型号,不报我们请求的那个。**
        # 审阅 §5.3 那张表要「模型连接版本、**实际返回型号**、每次尝试」——
        # 两者不同的时候(别名、路由、降级)**只有实际返回的那个是真的**。
        "actual_model": j.get("model") or 型号,
        "请求的型号": 型号,
        "usage": {
            "input_tokens": u.get("input_tokens"),
            "output_tokens": u.get("output_tokens"),
            # ⚠️ 缓存读写**分开记**,而且**没给就是 None,不填 0** ——
            # 「没有缓存命中」和「这个端点没告诉我们」是两件事,
            # 而填 0 会让后者看起来像前者。
            "cache_read_tokens": u.get("cache_read_input_tokens"),
            "cache_write_tokens": u.get("cache_creation_input_tokens"),
        },
        "execution_mode": "live",
        "往返毫秒": ms,
        "凭据来路": 来路,          # 来路(env:// / keychain://),**不是值**
        "展开后模板": 用户 or "",
    }
