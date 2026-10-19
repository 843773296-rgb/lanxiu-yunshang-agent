#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录失效就去登录页 · 检查(用户 2026-10-19:「无论刷新还是点击任意按钮都前往登录页面」)。

两半:
  · 刷新 / 打开页面 —— 服务端(app.py)没登录直接 302;登录页和顾客预约页放行;**后台连不上不算没登录**。
  · 页面开着、会话过期 —— web/_auth_guard.js 注入到每一页最前面。这一半用 node 真跑那个文件,
    桩出 fetch / document / location,逐个情形看它跳没跳。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("守卫不管 401(只靠点按钮时查)", "请求回来 401 → 去登录页,并带上回来的地址"),
    ("登录页自己的 401 也被当成失效", "登录接口自己的 401(口令不对)不跳"),
    ("后台连不上也当成没登录", "服务端:后台连不上不算没登录(照常给页面)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))


print("登录失效就去登录页 · 检查")
print("=" * 80)

守卫 = open(os.path.join(HERE, "web", "_auth_guard.js"), encoding="utf-8").read()

# 每个情形:me 接口怎么回、先发什么请求、点几下 → 看 location.href 和点击有没有被拦
桩 = r"""
const 守卫 = require("fs").readFileSync(process.argv[2], "utf8");
const 情形 = JSON.parse(process.argv[3]);
const 听 = {click: [], visibilitychange: [], pageshow: []};
const location = {pathname: 情形.页 || "/queue", search: 情形.参数 || "", href: ""};
const 请求了 = [];
function 回(status) { return Promise.resolve({status, ok: status < 400}); }
const window = {
  fetch: (u) => { 请求了.push(String(u));
    if (String(u).startsWith("/api/me")) return 情形.me === "断" ? Promise.reject(new Error("连不上")) : 回(情形.me);
    return 回((情形.接口 || {})[String(u)] || 200); },
  addEventListener: (k, f) => (听[k] = 听[k] || []).push(f),
};
const document = {hidden: false, addEventListener: (k, f, cap) => (听[k] = 听[k] || []).push(f)};
new Function("window", "document", "location", 守卫)(window, document, location);
const 等 = () => new Promise(r => setTimeout(r, 5));
const 按钮 = {closest: (sel) => 按钮};
(async () => {
  for (const u of 情形.先请求 || []) { await window.fetch(u); await 等(); }
  let 拦了 = 0;
  for (let i = 0; i < (情形.点 || 0); i++) {
    const e = {target: 按钮, preventDefault: () => 拦了++, stopPropagation: () => {}};
    听.click.forEach(f => f(e)); await 等();
  }
  if (情形.切回) { 听.visibilitychange.forEach(f => f()); await 等(); }
  console.log(JSON.stringify({href: location.href, 拦了, 请求了}));
})();
"""
d = tempfile.mkdtemp(prefix="guard-")
桩f, 守f = os.path.join(d, "t.js"), os.path.join(d, "g.js")
open(桩f, "w", encoding="utf-8").write(桩)
open(守f, "w", encoding="utf-8").write(守卫)


def 跑(情形):
    r = subprocess.run(["node", 桩f, 守f, json.dumps(情形, ensure_ascii=False)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"err": (r.stderr or r.stdout)[-300:]}


o = 跑({"先请求": ["/api/ops-queue"], "接口": {"/api/ops-queue": 401}, "页": "/queue", "参数": "?x=1"})
ck("请求回来 401 → 去登录页,并带上回来的地址", o.get("href") == "/login?back=%2Fqueue%3Fx%3D1", o)
o = 跑({"先请求": ["/api/login"], "接口": {"/api/login": 401}})
ck("登录接口自己的 401(口令不对)不跳", o.get("href") == "", o)
o = 跑({"点": 1, "me": 401})
ck("点按钮时会话已过期(接口不报 401 那种)→ 去登录页", o.get("href", "").startswith("/login?back=") and "/api/me" in o.get("请求了", []), o)
o = 跑({"点": 2, "me": 401})
ck("知道失效之后再点,当场拦下不放行", o.get("拦了") == 1, o)
o = 跑({"点": 1, "me": 200})
ck("还登录着 → 点按钮不跳、不拦", o.get("href") == "" and o.get("拦了") == 0, o)
o = 跑({"点": 1, "me": "断"})
ck("后台连不上 → 不跳(连不上不等于没登录)", o.get("href") == "", o)
o = 跑({"切回": True, "me": 401})
ck("切回这个标签页时会话过期 → 去登录页", o.get("href", "").startswith("/login?back="), o)

# ── 服务端那一半 ───────────────────────────────────────────────────────
站 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ck("服务端:没登录打开页面 → 302 到登录页(登录页 / 顾客预约页放行)",
   'if p not in 免登录页 and _登录状态(self) == "没登录":' in 站 and '免登录页 = ("/login", "/m")' in 站
   and 'self.send_header("location", "/login?back="' in 站)
ck("服务端:后台连不上不算没登录(照常给页面)",
   re.search(r'except urllib\.error\.HTTPError as e:\s*\n\s*return "没登录" if e\.code == 401 else "连不上"', 站) is not None
   and re.search(r'except Exception:\s*\n\s*return "连不上"\s*\n\s*\n\s*\ndef _注入登录守卫', 站) is not None)
ck("服务端:每一页(登录页 / 顾客预约页除外)送出前都注入守卫", "html = _注入登录守卫(html)" in 站
   and "if p not in 免登录页:\n                html = _注入登录守卫(html)" in 站)
登录页 = open(os.path.join(HERE, "web", "login.html"), encoding="utf-8").read()
ck("登录页登录后只回本站路径(back 不会把人带去外站)", "/^\\/(?![\\/\\\\])/.test(back)" in 登录页)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 登录失效:刷新走服务端 302,点按钮 / 401 / 切回标签页走守卫,连不上不误跳(验了 {n} 条){D}")
