#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""访问 API 聊天那一半,真跑(2026-11-03)。

**只在本机跑**(登记在 Makefile 的 E2E_CI跳过):它要真起着的聊天站(:8770)、本机那份内部凭证文件,
而且真调一轮模型 —— CI 里三样都没有。后台这一半的闸(没上生产 / 没接线 / 没绑工号 / 应用不对)不依赖聊天站,
也在这里一起验。

打的是店长助手(角色 task —— 现在唯一接上后台配置的角色)。问一句不会触发写的「只回复两个字」,
花钱最少、答案稳定。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 谁="U001", 体=None, 头=None):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体).encode() if 体 is not None else None)
    if 谁:
        req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


def 问(cid, 密, 问题, 会话=None):
    return 打("POST", f"/open/v1/chat-assistants/{cid}/messages", 谁=None, 体={"问题": 问题, "会话": 会话},
             头={"Authorization": "Bearer " + 密})


def main():
    c, l = 打("GET", P + "/chat-assistants")
    店长 = next((x for x in (l or {}).get("items", []) if x.get("角色键") == "task" or x.get("role_key") == "task"), None)
    cid = (店长 or {}).get("id")
    ck("找到店长助手(角色 task)", bool(cid), l)
    其他 = next((x for x in (l or {}).get("items", []) if x.get("id") != cid), None)

    print("\n▸ 后台这一半的闸(不依赖聊天站)")
    无绑 = "E2EAKC" + uuid.uuid4().hex[:4]
    打("POST", P + "/memberships", 体={"工号": 无绑, "角色": "admin"})
    c, k0 = 打("POST", P + f"/chat-assistants/{cid}/access-keys", 谁=无绑, 体={"名字": "e2e 没绑工号", "每天上限": 1})
    c, b = 问(cid, k0["原文"], "只回复两个字:正常")
    ck("**发密钥的人没绑澜绣工号 → 拒(403 NOT_BOUND)**:聊天站不知道以谁的身份取数", c == 403 and 码(b) == "NOT_BOUND", (c, b))
    c, k = 打("POST", P + f"/chat-assistants/{cid}/access-keys", 体={"名字": "e2e 店长助手", "每天上限": 1})
    密, kid = k["原文"], k["id"]
    ck("U001(已绑工号)发了一把店长助手的密钥", c == 201 and 密.startswith("lx-app-"), (c, k))
    if 其他:
        c, b = 问(其他["id"], 密, "只回复两个字:正常")
        ck("拿它去问别的助手 → 403 WRONG_APP", c == 403 and 码(b) == "WRONG_APP", (c, b))
    else:
        print("  ℹ️ 库里只有一个聊天助手 —— 「拿它去问别的助手」这条**没验**(工作流那一半 test_access_api_flow 验了同一个闸)")

    print("\n▸ 真问一轮(转给聊天站内部口)")
    c, r1 = 问(cid, 密, "只回复两个字:正常")
    ck("**问一轮 → 200,有回答、有会话号**", c == 200 and (r1 or {}).get("回答") and (r1 or {}).get("会话"), (c, r1))
    ck("跑的是后台生产那一版(用了哪一版 = 后台 vN)", str((r1 or {}).get("用了哪一版") or "").startswith("后台 v"), r1)
    ck("回答里写明这一轮写工具没挂", "没挂" in str((r1 or {}).get("写工具")), r1)
    会话 = (r1 or {}).get("会话")
    c, kb = 打("POST", P + f"/chat-assistants/{cid}/access-keys", 体={"名字": "e2e 乙", "每天上限": 1})
    c, b = 问(cid, kb["原文"], "接着刚才说", 会话)
    ck("**乙密钥续甲密钥的会话 → 拒(SESSION_NOT_YOURS)**,同一个人发的也不行", c == 403 and 码(b) == "SESSION_NOT_YOURS", (c, b))
    c, r2 = 问(cid, 密, "再只回复两个字:正常", 会话)
    ck("甲密钥自己续得上", c == 200 and (r2 or {}).get("会话"), (c, r2))

    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    with create_engine(url).connect() as cc:
        账 = cc.execute(text("""select u.amount, u.amount_known, u.trace_id, t.request_id from usage_ledger u
                                 join traces t on t.project_id=u.project_id and t.id=u.trace_id
                                where u.caller=:c order by u.created_at"""), {"c": f"访问密钥:{kid}"}).mappings().all()
    ck("**每轮一笔进用量账**(两轮两笔),挂在一条真 trace 上、记着聊天站那一轮的编号",
       len(账) == 2 and all(x["trace_id"] and x["request_id"] for x in 账), [dict(x) for x in 账])
    c, l = 打("GET", P + f"/chat-assistants/{cid}/access-keys")
    这把 = next((x for x in l["密钥"] if x["id"] == kid), {})
    ck("列表里「今天花了」把这两轮算进去了(和工作流共用每天上限)",
       这把.get("今天花了") is not None and 这把.get("今天花了") == round(sum(float(x["amount"] or 0) for x in 账), 6)
       or abs((这把.get("今天花了") or 0) - sum(float(x["amount"] or 0) for x in 账)) < 1e-6, 这把)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 访问 API · 聊天:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
