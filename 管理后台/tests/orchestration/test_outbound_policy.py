#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出网策略(三期 HTTP 请求节点的地基,11-16)—— **期望全部手写**,解析函数注入假 DNS,不靠这台机器的网络。

每条拒绝都要连理由一起断(「拒了但理由是别的」和「拒对了」在布尔值上一模一样)。
攻击样本挑的是 SSRF 里最常见的几种写法:回环 / 内网 / 云元数据 / 域名解析到内网 / 用户名夹主机 / 路径折平 / 子域名假冒 / 端口不同 / 协议不同。
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import 出网策略 as O  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:220] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


白 = ["https://api.supplier.com/v1", "https://cdn.example.org"]
# 公网样本用真公网段(8.8.8.8 / 1.1.1.1 / 2606:4700::);203.0.113.x 这种文档专用段 Python 算私有,拿它当公网会假红
假DNS = {"api.supplier.com": ["93.184.216.34"], "cdn.example.org": ["8.8.8.8", "2606:4700:4700::1111"],
         "evil.nip.io": ["127.0.0.1"], "meta.example.net": ["169.254.169.254"], "两面.example": ["93.184.216.34", "10.0.0.5"],
         "v6loop.example": ["::1"], "mapped.example": ["::ffff:192.168.1.1"], "cgnat.example": ["100.64.0.1"]}
解析 = lambda h: 假DNS[h] if h in 假DNS else (_ for _ in ()).throw(OSError("no such host"))

print("▸ H6 方法:一期只开读")
ck("GET / HEAD 放行,大小写不论", all(O.方法允许吗(m)[0] for m in ("GET", "head", "Get")), 3)
拒 = [O.方法允许吗(m) for m in ("POST", "PUT", "PATCH", "DELETE")]
ck("POST / PUT / PATCH / DELETE 拒,理由说清是「写入」要等二期", all(not r[0] and "写入" in r[1] and "二期" in r[1] for r in 拒), 4, 拒)

print("\n▸ H1 白名单:协议、主机、端口、路径前缀都得对")
对 = ["https://api.supplier.com/v1/stock?sku=1", "https://API.Supplier.com./v1", "https://api.supplier.com:443/v1/x/y", "https://cdn.example.org/", "https://cdn.example.org/a/b"]
ck("写法合法的几种都放行(大小写 / 末尾点 / 显式 443 / 白名单项没路径)", all(O.白名单里吗(u, 白)[0] for u in 对), len(对),
   [(u, O.白名单里吗(u, 白)) for u in 对 if not O.白名单里吗(u, 白)[0]])
错 = [("http://api.supplier.com/v1", "协议不同"), ("https://api.supplier.com:8443/v1", "端口不同"), ("https://api.supplier.com/v2", "路径前缀不同"),
      ("https://api.supplier.com/v1/../admin", "路径折平后越界"), ("https://api.supplier.com.evil.com/v1", "子域名假冒"),
      ("https://evil.com/api.supplier.com/v1", "主机放进路径"), ("https://api.supplier.com@evil.com/v1", "用户名夹主机"),
      ("ftp://api.supplier.com/v1", "协议认不出"), ("api.supplier.com/v1", "没协议"), ("https://api.supplier.com/v10", "前缀相似但不是子路径")]
坏 = [(u, 为, O.白名单里吗(u, 白)) for u, 为 in 错 if O.白名单里吗(u, 白)[0]]
ck("十种越界写法全拒", not 坏, len(错), 坏)
ck("拒的理由带「允许的端点」和怎么加白名单", "允许的端点" in O.白名单里吗("https://api.supplier.com/v2", 白)[1] and "白名单" in O.白名单里吗("https://api.supplier.com/v2", 白)[1], 1)
ck("空白名单 = 哪儿都不许去", not O.白名单里吗("https://api.supplier.com/v1", [])[0] and not O.白名单里吗("https://api.supplier.com/v1", None)[0], 2)

print("\n▸ SSRF:解析出来的地址落禁区就拒")
禁 = ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:10.0.0.1", "100.64.0.1", "224.0.0.1", "not-an-ip"]
ck("回环 / 内网 / 链路本地 / 云元数据 / 未指定 / v6 回环 / v6 链路本地 / ULA / v4-mapped / CGNAT / 组播 / 认不出的 都算禁区",
   all(O.地址落禁区吗(x) for x in 禁), len(禁), [x for x in 禁 if not O.地址落禁区吗(x)])
公 = ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111", "1.1.1.1"]
ck("公网地址不算禁区", not any(O.地址落禁区吗(x) for x in 公), len(公))
ck("域名解析到回环(evil.nip.io → 127.0.0.1)→ 拒,理由点名内网 / 本机", (lambda r: not r[0] and "内网" in r[1])(O.解析并核("evil.nip.io", 解析)), 1, O.解析并核("evil.nip.io", 解析))
ck("解析到云元数据地址 → 拒", not O.解析并核("meta.example.net", 解析)[0], 1)
ck("**一个域名解析出两个地址、一个落内网 → 整个拒**(不能挑好的那个连)", not O.解析并核("两面.example", 解析)[0], 1, O.解析并核("两面.example", 解析))
ck("v6 回环 / v4-mapped 内网 / CGNAT 也拒", all(not O.解析并核(h, 解析)[0] for h in ("v6loop.example", "mapped.example", "cgnat.example")), 3)
ck("解析不出来也算拒(连不上和不许连,对这一步来说都是「别发」)", not O.解析并核("nothing.invalid", 解析)[0], 1)
ck("正常公网域名放行,给出解析到的地址", (lambda r: r[0] and r[2] == ["93.184.216.34"])(O.解析并核("api.supplier.com", 解析)), 1, O.解析并核("api.supplier.com", 解析))

print("\n▸ 发送前总核(顺序:方法 → 白名单 → 解析)")
问过 = []
记着的解析 = lambda h: (问过.append(h), 解析(h))[1]
r = O.核请求("GET", "https://api.supplier.com/v1/stock", 白, 记着的解析)
ck("合规请求 → 放行", r == (True, "", ""), 1, r)
r = O.核请求("POST", "https://api.supplier.com/v1/stock", 白, 记着的解析)
ck("方法不对 → HTTP_METHOD_NOT_ALLOWED", r[1] == "HTTP_METHOD_NOT_ALLOWED", 1, r)
问过.clear()
r = O.核请求("GET", "https://evil.com/x", 白, 记着的解析)
ck("**不在白名单的地址连 DNS 都不问**(问一次也是一次出网)→ HTTP_NOT_IN_ALLOWLIST", r[1] == "HTTP_NOT_IN_ALLOWLIST" and 问过 == [], 1, (r, 问过))
r = O.核请求("GET", "https://evil.nip.io/", ["https://evil.nip.io"], 解析)
ck("白名单里但解析落内网 → HTTP_TARGET_FORBIDDEN(白名单只看写法,解析才看得到真去哪)", r[1] == "HTTP_TARGET_FORBIDDEN", 1, r)

print("\n▸ H2 重定向不跟 · H4 大小 / 超时 / 重试")
码, 话 = O.遇到重定向(302, "https://evil.com/steal")
ck("3xx → HTTP_REDIRECT_REFUSED,话里说清跳去哪、该怎么办", 码 == "HTTP_REDIRECT_REFUSED" and "evil.com/steal" in 话 and "白名单" in 话, 1, (码, 话))
ck("200 / 404 / 500 不算重定向;状态码认不出也不算", all(O.遇到重定向(s)[0] is None for s in (200, 404, 500, None, "x")), 5)
ck("默认 15 秒 / 1 MB(H4 拍的两个数)", O.默认超时秒 == 15 and O.响应上限字节 == 1024 * 1024, 2)
ck("响应 1 MB + 1 字节 → 太大,说清上限和怎么办;正好 1 MB 不算", O.响应太大吗(1024 * 1024 + 1)[0] and "上限" in O.响应太大吗(1024 * 1024 + 1)[1] and not O.响应太大吗(1024 * 1024)[0], 2)
ck("只重试 GET / HEAD", O.能重试吗("GET") and O.能重试吗("HEAD") and not O.能重试吗("POST"), 3)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
