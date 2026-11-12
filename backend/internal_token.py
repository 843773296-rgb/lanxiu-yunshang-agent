# -*- coding: utf-8 -*-
"""本机内部口令牌:智能运维平台(8770)的服务端线程调后台(8760)那两个内部口时带的凭证。

## 为什么要它(W01,2026-11-12)

后台 `do_POST` 从这一版起**默认要登录**。而 `/api/triage-run-worker`(研判执行线程领活 /
心跳 / 收尾)和 `/api/ops-triage`(研判结果寄存回后台)是 `agentsite/app.py` 的**后台线程**
调的 —— 那里没有浏览器、没有 cookie。原来这两个口**谁都能打**,只靠「后台只绑 127.0.0.1」:
本机任何一个进程(或者本机浏览器里一段跨站脚本)都能伪造一条研判结果、领走一条研判任务,
而伪造的研判会进看板、进评测回流。

所以给它们一把**本机令牌**:一个只有同一用户读得到的文件(600),两个服务同一用户跑,都读得到。
请求头 `X-Lanxiu-Internal` 带对了才放行,比较用 `hmac.compare_digest`(不给逐字节计时猜测留口子)。

> 「只绑 127.0.0.1」和「只有这台机器上这个用户的进程能打」是两件事 ——
> 前者挡的是别的机器,挡不住本机浏览器里的一段脚本。

## 文件在哪

默认 `~/.lanxiu-internal-token`;检查脚本用环境变量 `LANXIU_INTERNAL_TOKEN_FILE` 指到临时文件,
**不去碰家目录里那一份**。文件不存在就现生成(32 字节随机数的 hex),`O_EXCL` 建、权限 600。

⚠️ **每次现读,不缓存**:令牌文件被删掉重生成之后,两边下一次请求就自动对上;
缓存的话后台会一直拿着旧令牌,而研判线程拿到的是新的 —— 两边都不报错,只是研判全部 401。
"""
import hmac
import os
import secrets

请求头 = "X-Lanxiu-Internal"


def 文件():
    return os.environ.get("LANXIU_INTERNAL_TOKEN_FILE") or os.path.expanduser("~/.lanxiu-internal-token")


def 读():
    """→ 令牌串。文件不存在就生成一份(600)。两个进程同时生成时,输的那个读赢的那个写下的。"""
    路径 = 文件()
    try:
        with open(路径, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    except FileNotFoundError:
        pass
    t = secrets.token_hex(32)
    try:
        fd = os.open(路径, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(路径, encoding="utf-8") as f:
            return f.read().strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(t)
    return t


def 对得上(给的):
    """请求头里带的那个串对不对。空串 / 没带一律不对(不拿空串去和任何东西比)。"""
    if not 给的 or not isinstance(给的, str):
        return False
    return hmac.compare_digest(给的.strip().encode("utf-8"), 读().encode("utf-8"))
