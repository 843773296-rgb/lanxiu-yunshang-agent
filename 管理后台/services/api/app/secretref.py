#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `secret_ref` 这个**定位符**解析成真凭据 —— 只给探测和真调用用。

## 为什么在这之前没有这个文件,以及那意味着什么

`connections.py::检查密钥引用` 一直在验「它像不像一个定位符」,
**但全仓没有任何地方把它解析开** —— 也就是说这个后台从来没拿它调过任何东西。

而探测口(`POST /model-connections/{id}/probe`)写着 `探法: "真实端点"`,
却**全程没碰过网络**:它读适配器契约、写一行字、落库。

> **一个写着「真实端点」而从没发过一个请求的探测,和一个真探过的,
> 在 capabilities 上长得一模一样。**

这个文件是那句话的解法的一半(另一半是让探测真的发请求)。

## 三条硬规矩

**① 解析结果绝不进返回值、异常、日志、库。**
这个模块只返回**要加哪几个请求头**,而且:
  · 异常里只说「哪一种定位符解析失败」,**不带值、不带长度**
  · `遮(值)` 是唯一允许外露的形式,它只给前 0 位(= 什么都不给)
这条不是洁癖:仓库红线写着「**凭据绝不写进任何返回值或异常**」,
而 `errors.泄密检查` 会把带凭据字样的错误体整个变成 500 —— 今天已经触发过四次。

**② 只认白名单里的几种定位符,认不出就抛。**
`env://VAR` / `keychain://服务/账号`。`vault://` 和 `ref:` **明确不支持** ——
声明支持而其实没接,比不支持更坏:那会让「探过了」保一个没人接的通道。

**③ 不缓存。** 每次重新解析。缓存一个凭据意味着它在进程里多活一段时间,
而换掉一个泄露的凭据之后,缓存会让旧的继续生效。
"""
import json
import os
import re
import subprocess
import urllib.parse

_定位符 = re.compile(r"^(env|keychain)://(.+)$")


class 解析不了(Exception):
    """⚠️ 这个异常的文字里**绝不带凭据的值,也不带它的长度** —— 长度也是信息。"""


def 遮(值):
    """唯一允许外露的形式:**什么都不给**,只说有没有。"""
    return "(有值,已遮)" if 值 else "(空)"


def 解析(secret_ref):
    """定位符 → (请求头字典, 这凭据从哪来的一句人话)。

    ⚠️ **返回的头字典是要直接塞进请求的,不许往任何地方记。**
    """
    s = (secret_ref or "").strip()
    m = _定位符.match(s)
    if not m:
        # ⚠️ 不回显 s。只说它不是认得的那两种。
        raise 解析不了("这个定位符不是 `env://` 也不是 `keychain://` —— "
                   "`vault://` 和 `ref:` **这一版没接**:"
                   "声明支持而其实没接,比不支持更坏")
    种, 体 = m.group(1), m.group(2)
    if 种 == "env":
        v = os.environ.get(体)
        if not v:
            raise 解析不了(f"环境变量 `{体}` 在服务进程里是空的 —— "
                       f"⚠️ **起服务的那个 shell 设了不算**,要起服务时就在环境里")
        return {"x-api-key": v, "anthropic-version": "2023-06-01"}, f"env://{体}"
    # keychain://服务/账号 —— 照 `agent/v1.py::provider()` 那条路读,
    # 它已经在这台机器上用了几个月。**这里只调它、不复制它的解析**。
    if "/" not in 体:
        raise 解析不了("`keychain://` 要写成 `keychain://服务/账号`")
    服务, 账号 = 体.split("/", 1)
    # ⚠️ **百分号解码。** 定位符不许带空白(`connections._定位符` 要 `\S+`)——
    # 那条规矩是对的:带空格的定位符在日志和请求头里会有歧义。
    # 所以服务名里的空格写成 `%20`,在这儿解开。
    # (这台机器上那条是 `keychain://Claude%20Code-credentials/用户名`。)
    服务 = urllib.parse.unquote(服务)
    账号 = urllib.parse.unquote(账号)
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", 服务, "-a", 账号, "-w"],
            capture_output=True, text=True, timeout=10)
    except Exception as e:
        raise 解析不了(f"读钥匙串失败:{type(e).__name__}") from None
    if out.returncode != 0:
        # ⚠️ 不带 stderr —— 它可能回显条目名
        raise 解析不了(f"钥匙串里找不到这一条(服务 `{服务}`)")
    原 = (out.stdout or "").strip()
    if not 原:
        raise 解析不了("钥匙串那一条是空的")
    # Claude Code 的那一条存的是一段 JSON,token 在 claudeAiOauth.accessToken 里
    tok = 原
    if 原.startswith("{"):
        try:
            tok = (json.loads(原).get("claudeAiOauth") or {}).get("accessToken") or ""
        except Exception:
            raise 解析不了("钥匙串那一条是 JSON,但里面没有预期的字段") from None
    if not tok:
        raise 解析不了("钥匙串那一条里没有可用的令牌")
    return ({"authorization": "Bearer " + tok,
             "anthropic-version": "2023-06-01",
             "anthropic-beta": "oauth-2025-04-20"},
            f"keychain://{服务}/…")


# ── 一道结构性的闸:**凭据不许进任何要落库或返回的东西** ──────────────
#
# ⚠️ 这不是防御性编程。这个仓库记着:
# > 一条从没被攻击过的「结构性保证」,实际上仍然只是约定。
# 所以 `probe` 落 capabilities 之前过这一道,而 `boundary_audit` 那边会攻击它。

_可疑 = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{12,}"
    r"|eyJ[A-Za-z0-9._\-]{12,})")
# ⚠️ **这上面不许写出真实的匹配串** —— 被扫描的文件里写出真串会让
# `scan_secrets.sh` 匹配到自己。这几个是**形状**(前缀 + 长度),不是真值。
_可疑键 = ("authorization", "x-api-key", "api_key", "apikey",
          "access_token", "accesstoken", "secret", "password")


def 查有没有漏凭据(东西, 路径="capabilities"):
    """递归查一个将要落库/返回的结构里有没有凭据。返回问题列表(空 = 干净)。

    判两样:**键名像凭据**,和**值长得像凭据**。
    只判一样不够 —— 一个叫 `note` 的字段里塞一个 Bearer 串,键名那一关过得去。
    """
    坏 = []

    def 走(x, 路):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() in _可疑键:
                    坏.append(f"{路}.{k}:**键名像凭据**")
                走(v, f"{路}.{k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x):
                走(v, f"{路}[{i}]")
        elif isinstance(x, str) and _可疑.search(x):
            # ⚠️ **不把命中的那段写进问题里** —— 那就等于把凭据抄进了错误体
            坏.append(f"{路}:**值长得像凭据**(不回显)")

    走(东西, 路径)
    return 坏
