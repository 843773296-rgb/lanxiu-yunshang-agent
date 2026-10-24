#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真模型的出网环境 —— **常驻服务(launchd 起的、环境极简)也要带上代理**(2026-10-24)。

正式项目首跑撞到:从终端临时起的那份真调通了,常驻那份同一个请求回 http 403「Request not allowed」——
不是凭据错,是这台机器出去要走代理,而 launchd 不给。照澜绣聊天站 10-23 那次的修法:
进程里没有代理变量时,从 ~/.claude/settings.json 里**只取代理那几项**。

用临时 HOME 造一份设置,不碰真的 ~/.claude/settings.json。
"""
import json
import os
import sys
import tempfile

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path[:0] = [os.path.join(根, "services", "api", "app"), os.path.join(根, "services", "api", "app", "runtime")]
import 真模型 as M  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{'  ' + str(补)[:160] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


for k in M._代理键:
    os.environ.pop(k, None)
家 = tempfile.mkdtemp(prefix="proxyenv-")
os.makedirs(os.path.join(家, ".claude"))
with open(os.path.join(家, ".claude", "settings.json"), "w", encoding="utf-8") as f:
    json.dump({"env": {"HTTPS_PROXY": "http://设置里的代理:7890", "OTHER_SECRET": "不该被搬过来",
                       "no_proxy": "localhost"}}, f, ensure_ascii=False)
os.environ["HOME"] = 家

e = M.curl环境()
ck("进程里没有代理 → 从用户设置里补上 HTTPS_PROXY", e.get("HTTPS_PROXY") == "http://设置里的代理:7890", e.get("HTTPS_PROXY"))
ck("小写的 no_proxy 也补上(curl 认它)", e.get("no_proxy") == "localhost", e.get("no_proxy"))
ck("**只取代理那几项** —— 设置里别的变量不搬", "OTHER_SECRET" not in e)
os.environ["HTTPS_PROXY"] = "http://进程自己的:1"
e = M.curl环境()
ck("进程里已经有代理 → 用进程的,不拿设置里的覆盖", e.get("HTTPS_PROXY") == "http://进程自己的:1", e.get("HTTPS_PROXY"))
os.environ.pop("HTTPS_PROXY")
os.remove(os.path.join(家, ".claude", "settings.json"))
ck("用户设置不存在 → 不报错,照进程原样", "HTTPS_PROXY" not in M.curl环境())

print()
if 挂:
    print(f"❌ {len(挂)} 条不过:{挂}")
    sys.exit(1)
print(f"✅ 真模型的出网环境:常驻服务也带上代理,只搬代理那几项(验了 {len(过)} 条)")
