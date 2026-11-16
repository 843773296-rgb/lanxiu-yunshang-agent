#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 请求节点执行核心(三期 3-1,11-16)—— **假发送函数 + 假 DNS,一个真请求都不发**;网关用真的 `tool_gateway.执行`。

验的是接线和边界,不是判据(判据在 test_outbound_policy):
  ① 合成契约:只读、方法 / 白名单 / 凭据全在服务端绑定里(模型 / 前端传同名键 → 网关闸②拒)
  ② 拼地址:相对路径拼到白名单那一项、完整地址原样、查询串编码、空白名单拒
  ③ 发送前就拦的四种(方法 / 白名单外 / 解析落内网 / 凭据取不到)→ **发送函数一次都没被调**
  ④ 🔑 凭据只从连接来:节点自带的 authorization 被丢掉,连接的头被装上;**结果里任何地方都不出现凭据原值**
  ⑤ 3xx 不跟 → 失败说清跳去哪;超过上限 → 失败;正常 JSON → 解析出来
  ⑥ curl 命令:不带 -L、带 --max-time / --max-filesize、HEAD 用 -I
  ⑦ 经真网关走一遍:记事里有 tool.started / tool.succeeded;服务端绑定键被模型覆盖 → SERVER_BOUND_OVERRIDE
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "contract"))
import HTTP请求 as H  # noqa: E402
import tool_gateway as G  # noqa: E402
import dsl as DS  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


os.environ["E2E_HTTP_KEY"] = "密钥值甲乙丙"          # ⚠️ 不用英文密钥形状,免得密钥扫描器认成真的
连接 = {"id": "cc_1", "name": "供应商库存", "allowed_endpoints": ["https://api.supplier.com/v1"],
      "secret_ref": "env://E2E_HTTP_KEY", "auth": {"方式": "header", "头名": "x-api-key"}}
假DNS = {"api.supplier.com": ["93.184.216.34"], "evil.nip.io": ["127.0.0.1"]}
解析 = lambda h: 假DNS[h] if h in 假DNS else (_ for _ in ()).throw(OSError("no such host"))
发过 = []


def 假发(方法, url, 头, 超时, 上限, *, 回=None):
    发过.append({"方法": 方法, "url": url, "头": dict(头), "超时": 超时, "上限": 上限})
    return 回 or {"status": 200, "headers": {"content-type": "application/json"}, "body": json.dumps({"库存": 12}).encode()}


print("▸ ① 合成契约")
契 = H.合成契约(连接, {"method": "get", "timeout_seconds": 7})
ck("只读、名字带连接 id、方法 / 白名单 / 凭据 / 超时都在服务端绑定里,不在 input_schema 里",
   契["side_effect_type"] == DS.只读 and 契["name"] == "http:cc_1" and 契["server_bound_arguments"]["method"] == "GET"
   and 契["server_bound_arguments"]["timeout_seconds"] == 7 and "secret_ref" not in 契["input_schema"]["properties"]
   and set(契["input_schema"]["properties"]) == {"path", "query", "headers"}, 1, 契)

print("\n▸ ② 拼地址")
ck("相对路径拼到白名单第一项;完整地址原样;查询串编码;带 ? 的接 &",
   H.拼地址(连接["allowed_endpoints"], "/stock", {"sku": "A 1", "n": 2}) == "https://api.supplier.com/v1/stock?sku=A+1&n=2"
   and H.拼地址(连接["allowed_endpoints"], "https://api.supplier.com/v1/x") == "https://api.supplier.com/v1/x"
   and H.拼地址(["https://a.com/v1?k=1"], "", {"b": 2}) == "https://a.com/v1?k=1&b=2", 3)
try:
    H.拼地址([], "/stock"); ck("空白名单 → 拒", False, 1)
except H.请求被拒 as e:
    ck("空白名单 → 拒,说去登记", e.code == "HTTP_NOT_IN_ALLOWLIST" and "登记" in e.为什么, 1, e.为什么)

print("\n▸ ③ 发送前就拦的 → 发送函数一次都没被调")
基 = {**契["server_bound_arguments"]}
for 名, 改, 码 in [("POST", {"method": "POST", "path": "/stock"}, "HTTP_METHOD_NOT_ALLOWED"),
                 ("白名单外", {"path": "https://evil.com/x"}, "HTTP_NOT_IN_ALLOWLIST"),
                 ("解析落内网", {"allowed_endpoints": ["https://evil.nip.io"], "path": "/x"}, "HTTP_TARGET_FORBIDDEN"),
                 ("凭据取不到", {"path": "/stock", "secret_ref": "env://NO_SUCH_VAR_E2E"}, "HTTP_SECRET_UNRESOLVED")]:
    发过.clear()
    try:
        H.发送({**基, **改}, 发=假发, 解析=解析); 得 = "放行了"
    except H.请求被拒 as e:
        得 = e.code
    ck(f"{名} → {码},没发", 得 == 码 and 发过 == [], 1, (得, 发过))

print("\n▸ ④ 凭据只从连接来,结果里不出现原值")
发过.clear()
r = H.发送({**基, "path": "/stock", "query": {"sku": "A1"}, "headers": {"Authorization": "Bearer 节点里偷写的", "Accept": "application/json"}}, 发=假发, 解析=解析)
真头 = 发过[0]["头"]
ck("连接的 x-api-key 装上了、节点自带的 Authorization 被丢掉、Accept 保留", 真头.get("x-api-key") == "密钥值甲乙丙" and "Authorization" not in 真头 and "authorization" not in {k.lower() for k in 真头} and 真头.get("Accept") == "application/json", 1, 真头)
整 = json.dumps(r, ensure_ascii=False)
ck("🔑 结果里任何地方都不出现凭据原值、请求头已打码、来路只说 env://", "密钥值甲乙丙" not in 整 and r["请求头"]["x-api-key"] == "(有值,已遮)" and r["凭据来路"] == "env://E2E_HTTP_KEY", 1, 整)
ck("正常 JSON:status 200、json 解析出来、url 拼对", r["status_code"] == 200 and r["json"] == {"库存": 12} and r["url"] == "https://api.supplier.com/v1/stock?sku=A1", 1, r)
ck("超时 / 上限按契约(7 秒 / 1 MB)传给发送", 发过[0]["超时"] == 7 and 发过[0]["上限"] == 1024 * 1024, 2, 发过[0])

print("\n▸ ⑤ 3xx 不跟 · 太大 · 不是 JSON")
try:
    H.发送({**基, "path": "/stock"}, 发=lambda *a: 假发(*a, 回={"status": 302, "headers": {"location": "https://evil.com/steal"}, "body": b""}), 解析=解析); ck("3xx → 失败", False, 1)
except H.请求失败 as e:
    ck("3xx → HTTP_REDIRECT_REFUSED,说清跳去哪", e.code == "HTTP_REDIRECT_REFUSED" and "evil.com/steal" in e.为什么, 1, e.为什么)
try:
    H.发送({**基, "path": "/stock", "max_bytes": 10}, 发=lambda *a: 假发(*a, 回={"status": 200, "headers": {}, "body": b"x" * 11}), 解析=解析); ck("太大 → 失败", False, 1)
except H.请求失败 as e:
    ck("超过上限 → HTTP_RESPONSE_TOO_LARGE", e.code == "HTTP_RESPONSE_TOO_LARGE", 1, e.为什么)
r = H.发送({**基, "path": "/stock"}, 发=lambda *a: 假发(*a, 回={"status": 404, "headers": {}, "body": b"not found"}), 解析=解析)
ck("4xx 不算失败(状态码交给下游判);不是 JSON 时 json 为空、body 原文", r["status_code"] == 404 and r["json"] is None and r["body"] == "not found", 1, r)

print("\n▸ ⑥ curl 命令")
cmd = H.curl命令("GET", "https://api.supplier.com/v1/stock", {"x-api-key": "k"}, 15, 1048576, "/tmp/h", "/tmp/b")
ck("不带 -L、带 --max-time 15 / --max-filesize / --proto 限 http(s)、头进 -H", "-L" not in cmd and "--max-time" in cmd and cmd[cmd.index("--max-time") + 1] == "15"
   and "--max-filesize" in cmd and "=http,https" in cmd and "x-api-key: k" in cmd, 1, cmd)
ck("HEAD 用 -I", "-I" in H.curl命令("HEAD", "https://a.com", {}, 5, 10, "/tmp/h", "/tmp/b"), 1)

print("\n▸ ⑦ 经真网关走一遍")
记 = []
发过.clear()
r = H.跑节点({"method": "GET"}, {"path": "/stock", "query": {"sku": "A1"}}, 连接=连接, 执行=G.执行, 记事=lambda k, v: 记.append(k), 发=假发, 解析=解析)
ck("网关放行、真发了一次、结果回来了;记事里有 tool.started / tool.succeeded(六道闸照旧)", r and r.get("status_code") == 200 and len(发过) == 1
   and "tool.started" in 记 and "tool.succeeded" in 记, 1, (记, r))
发过.clear()
try:
    H.跑节点({"method": "GET"}, {"path": "/stock", "method": "POST"}, 连接=连接, 执行=G.执行, 发=假发, 解析=解析); 得 = "放行了"
except G.拒绝 as e:
    得 = e.code
ck("🔑 模型 / 前端想覆盖 method(服务端绑定)→ 网关 SERVER_BOUND_OVERRIDE,没发", 得 == "SERVER_BOUND_OVERRIDE" and 发过 == [], 1, 得)
try:
    H.跑节点({"method": "GET"}, {"path": "/stock", "多出来的": 1}, 连接=连接, 执行=G.执行, 发=假发, 解析=解析); 得 = "放行了"
except G.拒绝 as e:
    得 = e.code
ck("多了没登记的参数 → 网关 ARGS_INVALID", 得 == "ARGS_INVALID", 1, 得)
发过.clear()
try:
    H.跑节点({"method": "GET"}, {"path": "https://evil.com/x"}, 连接=连接, 执行=G.执行, 发=假发, 解析=解析); 得 = "放行了"
except H.请求被拒 as e:
    得 = (e.code, "白名单" in e.为什么)
ck("白名单外走 跑节点 → 在网关外就拦,报 HTTP_NOT_IN_ALLOWLIST(不包成「待核实」),没发", 得 == ("HTTP_NOT_IN_ALLOWLIST", True) and 发过 == [], 1, 得)

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
