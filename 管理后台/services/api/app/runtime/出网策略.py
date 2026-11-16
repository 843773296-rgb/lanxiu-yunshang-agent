#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出网策略(三期 3-1「HTTP 请求」节点的地基;11-16 起写,**纯逻辑、不发请求、不碰库**)。

11-12 设计稿的 11 条安全决定用户已拍「按推荐」(《优化执行方案与新功能路线-20261112》第二张卡),这里落的是 HTTP 那六条:

| 决定 | 推荐(= 拍的) | 落在哪 |
|---|---|---|
| H1 能访问哪些地址 | 只能选已登记的工具连接(它的「允许的端点」白名单) | `白名单里吗` |
| H2 重定向跟不跟 | 不跟;3xx 这一步失败,显示跳去哪 | `遇到重定向` |
| H3 密钥怎么给 | 挂在连接上,发送那一刻才由 secretref 加请求头;节点里没地方写 | 这里不碰(调用方在发送前调 `secretref.解析`) |
| H4 超时 / 响应大小 / 重试 | 15 秒 / 1 MB / 只重试 GET | 下面三个常量 + `能重试吗` |
| H5 谁能加 HTTP 节点 | 能编辑工作流的都能加,把关在登记连接 | 不在这儿(连接登记那道闸在 tools_api) |
| H6 开不开写操作 | 一期只开 GET(HEAD 也算读) | `方法允许吗` |

外加设计稿 H2 的另一半 —— **SSRF**:解析出来的 IP 落回环 / 内网 / 链路本地 / 云元数据 / 保留段一律拒,
而且**先解析再查、查完才连**(白名单只看写法,`127.0.0.1.nip.io` 写法合法、解析出来是回环)。
解析函数由调用方注入(默认 `socket.getaddrinfo`),自测时注入假解析 —— 判据不靠这台机器的 DNS。

## 为什么是独立模块
`runtime/tool_gateway.py` 文件头:「如果 Agent 运行时能自己发一次 HTTP,那么『这个 Agent 能做什么』就没有任何地方能一次看全」。
HTTP 节点要走同一个门;而「这个地址能不能去」这一问,工具连接那边**只登记了白名单、运行时从没核过**
(11-16 grep:`allowed_endpoints` 只出现在登记和审计里)—— 又是「声明了 ≠ 生效了」。这个模块把那一问做成可调、可测的一份,
HTTP 节点先用,工具连接真调时也该用它。

⚠️ 每一条「拒」都带人话 + 该怎么改;**错误里不出现密钥**(这里根本碰不到密钥)。
"""
import ipaddress
import posixpath
import socket
import urllib.parse

默认超时秒 = 15
响应上限字节 = 1 * 1024 * 1024
允许的方法 = ("GET", "HEAD")
默认端口 = {"http": 80, "https": 443}


def _规范路径(p):
    """把 `/v1/../admin` 这类写法折平再比 —— 不折平的话前缀比对会放过它。"""
    p = posixpath.normpath(p or "/")
    return p if p.startswith("/") else "/" + p


def _拆(url):
    u = urllib.parse.urlsplit(str(url or "").strip())
    scheme = (u.scheme or "").lower()
    host = (u.hostname or "").lower().rstrip(".")
    try:
        port = u.port or 默认端口.get(scheme)
    except ValueError:
        port = None
    return scheme, host, port, _规范路径(u.path), u


def 方法允许吗(方法):
    """H6:一期只开读。→ (行不行, 为什么)"""
    m = str(方法 or "GET").upper()
    if m in 允许的方法:
        return True, ""
    return False, (f"HTTP 请求这一期只开 GET / HEAD(只读);{m} 会改外部系统的数据,算「写入」 —— "
                   f"要用的话等二期,而且前面必须有人工核对")


def 白名单里吗(url, 允许的端点):
    """H1:地址必须落在连接登记的「允许的端点」里 —— 协议、主机、端口都得对上,路径要以登记的前缀开头。
    → (行不行, 为什么)。登记项形如 `https://api.supplier.com/v1`;空白名单 = 哪儿都不许去。"""
    scheme, host, port, path, u = _拆(url)
    if scheme not in ("http", "https") or not host:
        return False, f"地址认不出(要以 http:// 或 https:// 开头,带主机名):{str(url)[:80]}"
    if u.username or u.password:
        # `https://api.x.com@evil.com/` 这种写法,浏览器会去 evil.com —— 人眼看着却像 api.x.com
        return False, "地址里不许夹用户名 / 密码(`用户@主机` 这种写法会把人看到的主机和真去的主机分开)"
    for 项 in 允许的端点 or []:
        s2, h2, p2, path2, _ = _拆(项)
        if not h2:
            continue
        if (scheme, host, port) != (s2, h2, p2):
            continue
        if path == path2 or path.startswith(path2.rstrip("/") + "/") or path2 == "/":
            return True, ""
    return False, (f"{scheme}://{host}{'' if port == 默认端口.get(scheme) else f':{port}'}{path} 不在这条连接登记的「允许的端点」里 —— "
                   f"要访问它,先到「工具连接」里把这个地址加进白名单(改白名单要「配置密钥与预算」权限)")


def 地址落禁区吗(ip):
    """回环 / 内网 / 链路本地(含云元数据 169.254.169.254)/ 保留 / 组播 / 未指定 / 本地 ULA → True。
    IPv4-mapped IPv6(::ffff:127.0.0.1)先还原成 IPv4 再判。"""
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return True          # 认不出的当禁区:宁可多拒
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    # ⚠️ Python 的 is_private 把文档用的 TEST-NET(203.0.113.0/24 这类)也算私有 —— 自测夹具别拿它们当「公网」举例
    return bool(a.is_loopback or a.is_private or a.is_link_local or a.is_reserved or a.is_multicast
                or a.is_unspecified or (isinstance(a, ipaddress.IPv6Address) and a.is_site_local)
                or a in ipaddress.ip_network("100.64.0.0/10"))      # 运营商 NAT 段:Python 3.11 前不算私有,点名


def 解析并核(主机, 解析=None):
    """把主机名解成 IP,逐个核禁区。→ (行不行, 为什么, ips)。
    `解析(主机)` → 一串 IP 字串;不给就用系统 DNS。解析失败也算拒(连不上和不许连,对这一步来说都是「别发」)。"""
    主机 = str(主机 or "").lower().rstrip(".")
    try:
        if 解析 is None:
            ips = sorted({x[4][0] for x in socket.getaddrinfo(主机, None)})
        else:
            ips = sorted(set(解析(主机)))
    except (socket.gaierror, OSError, ValueError) as e:
        return False, f"主机 {主机} 解析不出来:{type(e).__name__} —— 核对地址,或稍后再试", []
    if not ips:
        return False, f"主机 {主机} 解析不出任何地址", []
    坏 = [ip for ip in ips if 地址落禁区吗(ip)]
    if 坏:
        return False, (f"主机 {主机} 解析到 {坏[0]},那是内网 / 本机 / 云元数据这类不许出网访问的地址 —— "
                       f"HTTP 请求只能打外部服务;要查内部数据用「业务动作」步骤"), ips
    return True, "", ips


def 核请求(方法, url, 允许的端点, 解析=None):
    """发送前的全部核对,按序:方法 → 白名单 → 解析落禁区。→ (行不行, 错误码, 为什么)。
    顺序有意:白名单在解析之前 —— 不在白名单里的地址**连 DNS 都不去问**(问一次也是一次出网)。"""
    行, 为 = 方法允许吗(方法)
    if not 行:
        return False, "HTTP_METHOD_NOT_ALLOWED", 为
    行, 为 = 白名单里吗(url, 允许的端点)
    if not 行:
        return False, "HTTP_NOT_IN_ALLOWLIST", 为
    _, host, _, _, _ = _拆(url)
    行, 为, _ = 解析并核(host, 解析)
    if not 行:
        return False, "HTTP_TARGET_FORBIDDEN", 为
    return True, "", ""


def 遇到重定向(状态码, 跳去哪=""):
    """H2:不跟。→ (错误码, 人话);不是 3xx → (None, "")"""
    try:
        s = int(状态码)
    except (TypeError, ValueError):
        return None, ""
    if 300 <= s < 400:
        return "HTTP_REDIRECT_REFUSED", (f"对方回了 {s},要跳到 {str(跳去哪)[:120] or '(没说)'} —— 这一步不跟着跳(跳去的地址没过白名单)。"
                                         f"确认那个地址没问题的话,直接把它登记进白名单、改用它")
    return None, ""


def 响应太大吗(字节数, 上限=None):
    上 = 响应上限字节 if 上限 is None else int(上限)
    if int(字节数 or 0) > 上:
        return True, f"响应 {int(字节数) / 1024 / 1024:.1f} MB,超过上限 {上 / 1024 / 1024:.0f} MB —— 让对方分页,或在连接上调高上限"
    return False, ""


def 能重试吗(方法):
    """H4:只重试 GET(HEAD 也幂等)。写类方法本来就不开,这里只是把「为什么只重试读」写死在一处。"""
    return str(方法 or "GET").upper() in 允许的方法
