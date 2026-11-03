#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""访问 API 端到端(2026-11-03,方案文档第六节那张验收表,逐条)。

打真起着的 :8801(带 X-Dev-User 发 / 管密钥;对外那两个接口带访问密钥、不带 X-Dev-User)。
花费上限那两条要「今天这把密钥花了多少」—— mock 运行不花钱,所以**直接往用量账里记一笔**挂到这把密钥发起的运行上
(记账本身由 tests/orchestration/test_workflow_cost.py 真调 worker 那段验;这里验的是「按账封顶」这一半)。

没覆盖、写明:① 「设了项目每日预算就不许超过它」—— 改项目预算会影响别的测试,这一条现在只有代码、没有端到端;
② 「要人核对的步骤 API 调也照样要人核对」—— 走的是和后台发起同一个 `_受理运行`,
这里的测试工作流没有人工核对步骤;那一条由录音跟进的端到端(test_audio_flow)守着。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
# 澜绣正式项目:没设每日预算(demo_a 那条「每日预算 0」是 test_settings_flow 造的 —— 0 = 一分都不许花,密钥按规矩发不出来)
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")
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
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(d):
    return ((d or {}).get("error") or d or {}).get("code")


def 外(方法, 路, 密, 体=None, 键=None):
    头 = {"Authorization": "Bearer " + 密} if 密 else {}
    if 键:
        头["Idempotency-Key"] = 键
    return 打(方法, 路, 谁=None, 体=体, 头=头)


def 库():
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    return create_engine(url)


def 等跑完(rid, 密):
    """**等的时候走后台的运行详情**,不走对外查结果 —— 对外那一个每次都算进这把密钥的限流(每分钟 30 次),
    每秒轮询一次半分钟就会被限住(第一版就是这么把自己限住的)。等到了再用对外接口查一次。"""
    for _ in range(60):
        c, d = 打("GET", P + f"/execution-runs/{rid}")
        if c == 200 and d.get("是终态吗"):
            break
        time.sleep(1)
    return 外("GET", f"/open/v1/runs/{rid}", 密)[1]


def main():
    print("▸ 准备:一条发布到生产的测试工作流 + 一个发密钥的管理员账号")
    def 建一条(名):
        """空白模板 + 一条「开始 → 结束」,结束原样返回收到的那段文字 —— 不调模型,哪个项目都跑得了。"""
        c, w = 打("POST", P + "/workflows", 体={"名称": f"{名} {uuid.uuid4().hex[:6]}", "模板": "空白"})
        wid = (w or {}).get("id")
        c, d = 打("GET", P + f"/workflows/{wid}")
        定义 = d["草稿"]["定义"]
        定义["edges"] = [{"source": "start", "target": "finish", "port": "success"}]
        for n in 定义["nodes"]:
            if n["type"] == "end":
                n["config"]["bindings"] = {"summary": {"source": "input", "pointer": "/article"}}
        打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
        return wid
    wid = 建一条("e2e 访问API")
    ck("建了一条「开始 → 结束」工作流", bool(wid), wid)
    wid2 = 建一条("e2e 访问API·没上生产")
    发人 = "E2EAK" + uuid.uuid4().hex[:4]
    c, m = 打("POST", P + "/memberships", 体={"工号": 发人, "角色": "admin"})
    ck("建了一个管理员(专门用来发密钥,后面会被降级)", c in (200, 201), (c, m))

    c, k2 = 打("POST", P + f"/workflows/{wid2}/access-keys", 谁=发人, 体={"名字": "没上生产那条的", "每天上限": 5})
    密2 = (k2 or {}).get("原文")
    c, b = 外("POST", f"/open/v1/apps/{k2['应用id']}/runs", 密2, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**应用没上生产 → 拒(409 NOT_IN_PRODUCTION)**,草稿和候选版本不对外", c == 409 and 码(b) == "NOT_IN_PRODUCTION", (c, b))

    c, v = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e 访问API"})
    vid = (v or {}).get("id")
    ck("出了一版", c == 201 and vid, (c, v))
    def 发生产():
        return 打("POST", P + f"/workflows/{wid}/releases", 体={"版本id": vid, "环境": "production"},
                 头={"Idempotency-Key": str(uuid.uuid4())})
    c, b = 发生产()
    if c == 422:
        打("POST", P + f"/releases/{(b.get('field_errors') or {}).get('清单id')}/reviews", 体={"结论": "通过"})
        c, b = 发生产()
    ck("出了一版、审核、发到生产", c == 202, (c, b))

    print("\n▸ 发密钥:原文只这一次,库里只有哈希")
    c, b = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e"})
    ck("不填每天上限 → 拒(上限必填,「不限」不提供)", c == 422, (c, b))
    编 = "E2EAKE" + uuid.uuid4().hex[:4]
    打("POST", P + "/memberships", 体={"工号": 编, "角色": "editor"})
    c, b = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=编, 体={"名字": "e2e", "每天上限": 5})
    ck("编辑者发不了(要「配置密钥与预算」)", c == 403, (c, b))
    c, k = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 主钥", "每天上限": 5})
    密, kid, aid = (k or {}).get("原文", ""), (k or {}).get("id"), (k or {}).get("应用id")
    ck("发出来了,原文以 lx-app- 开头", c == 201 and 密.startswith("lx-app-") and kid and aid, (c, k))
    c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
    ck("**列表里没有原文**(只有开头几位)", c == 200 and 密 and 密 not in json.dumps(l, ensure_ascii=False)
       and any(x["id"] == kid for x in l["密钥"]), l)
    from sqlalchemy import text
    with 库().connect() as cc:
        行 = cc.execute(text("select * from access_keys where id=:i"), {"i": kid}).mappings().first()
    ck("**库里只有哈希**:没有一列存着原文", 行 and 密 not in json.dumps({k_: str(v_) for k_, v_ in dict(行).items()}),
       dict(行 or {}))

    print("\n▸ 发起 / 防重复 / 查结果")
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}})
    ck("不带幂等键 → 拒(409)", c == 409 and 码(b) == "IDEMPOTENCY_KEY_REQUIRED", (c, b))
    键 = str(uuid.uuid4())
    c, r1 = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, 键)
    ck("发起 → 202,带运行编号和跑的版本", c == 202 and (r1 or {}).get("运行编号"), (c, r1))
    c, r2 = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, 键)
    ck("**同一个幂等键再发 → 同一条运行**(不跑第二遍、不多花钱)",
       c == 202 and r2.get("运行编号") == r1.get("运行编号"), (c, r2))
    rid = r1.get("运行编号")
    d = 等跑完(rid, 密)
    ck("查结果:跑完了,状态「已完成」,结果原样带回", d.get("跑完了吗") and d.get("状态") == "已完成"
       and (d.get("结果") or {}).get("summary") == "访问 API 端到端", d)
    with 库().connect() as cc:
        来 = cc.execute(text("select definition_ref, principal from execution_runs where id=:i"), {"i": rid}).mappings().first()
    ck("**以发密钥的人的身份跑**、记下是访问 API 发起的、钉的是生产那一版",
       来 and 来["principal"] == 发人 and 来["definition_ref"].get("发起") == "访问 API"
       and 来["definition_ref"].get("密钥id") == kid and 来["definition_ref"].get("version_id") == vid, dict(来 or {}))

    print("\n▸ 别的密钥 / 别的应用")
    c, kb = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 乙", "每天上限": 5})
    密b = kb["原文"]
    c, b = 外("GET", f"/open/v1/runs/{rid}", 密b)
    ck("**乙密钥查甲密钥发起的运行 → 404**(同一个人发的也不行)", c == 404, (c, b))
    c, b = 外("POST", f"/open/v1/apps/{k2['应用id']}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("拿这把密钥去调别的应用 → 403 WRONG_APP", c == 403 and 码(b) == "WRONG_APP", (c, b))
    c, b = 外("GET", f"/open/v1/runs/{rid}", "lx-app-" + "0" * 40)
    ck("不认识的密钥 → 401", c == 401 and 码(b) == "UNKNOWN_ACCESS_KEY", (c, b))

    print("\n▸ 每天花费上限(按用量账算)")
    c, kc = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 小额", "每天上限": 0.01})
    密c, kidc = kc["原文"], kc["id"]
    c, rc = 外("POST", f"/open/v1/apps/{aid}/runs", 密c, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    等跑完(rc["运行编号"], 密c)
    with 库().begin() as cc:
        tr = cc.execute(text("select trace_id, organization_id from execution_runs where id=:i"),
                        {"i": rc["运行编号"]}).mappings().first()
        cc.execute(text("""insert into usage_ledger (id, organization_id, project_id, event_key, trace_id, resource,
                               quantity, unit, currency, amount, amount_known, source, created_at, created_by)
                           values (:i, :o, :p, :ek, :t, 'generate', 1000, 'token', 'USD', 0.02, true,
                                   'live', now(), 'e2e')"""),
                   {"i": "ul_" + uuid.uuid4().hex[:12], "o": tr["organization_id"], "ek": "e2e-cap-" + uuid.uuid4().hex,
                    "t": tr["trace_id"], "p": 项目})
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密c, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**当天花费到上限 → 拒(429 DAILY_CAP_REACHED)**", c == 429 and 码(b) == "DAILY_CAP_REACHED", (c, b))
    c, kd = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 算不出", "每天上限": 5})
    密d = kd["原文"]
    c, rd = 外("POST", f"/open/v1/apps/{aid}/runs", 密d, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    等跑完(rd["运行编号"], 密d)
    with 库().begin() as cc:
        tr = cc.execute(text("select trace_id, organization_id from execution_runs where id=:i"),
                        {"i": rd["运行编号"]}).mappings().first()
        cc.execute(text("""insert into usage_ledger (id, organization_id, project_id, event_key, trace_id, resource,
                               quantity, unit, currency, amount, amount_known, source, created_at, created_by)
                           values (:i, :o, :p, :ek, :t, 'generate', 1000, 'token', 'USD', null, false,
                                   'live', now(), 'e2e')"""),
                   {"i": "ul_" + uuid.uuid4().hex[:12], "o": tr["organization_id"], "ek": "e2e-unk-" + uuid.uuid4().hex,
                    "t": tr["trace_id"], "p": 项目})
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密d, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**今天有算不出金额的账 → 拒(COST_UNKNOWN)**,不按 0 算", c == 429 and 码(b) == "COST_UNKNOWN", (c, b))
    c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
    小 = next((x for x in l["密钥"] if x["id"] == kidc), {})
    ck("列表里看得到「今天花了多少」", abs((小.get("今天花了") or 0) - 0.02) < 1e-9, 小)

    print("\n▸ 上限只许改小")
    c, b = 打("PATCH", P + f"/access-keys/{kid}", 体={"每天上限": 50}, 头={"If-Match": "1"})
    ck("改大 → 拒(要更大额度就吊销重发)", c == 422, (c, b))
    c, b = 打("PATCH", P + f"/access-keys/{kid}", 体={"每天上限": 3}, 头={"If-Match": "1"})
    ck("改小 → 成", c == 200 and b.get("每天上限") == 3, (c, b))

    print("\n▸ 限流:一分钟第 31 次")
    c, ke = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 限流", "每天上限": 5})
    密e = ke["原文"]
    码们 = [外("GET", f"/open/v1/runs/{rid}", 密e)[0] for _ in range(30)]
    c, b = 外("GET", f"/open/v1/runs/{rid}", 密e)
    ck("前 30 次照常(404:这把查不到甲的运行),**第 31 次 → 429 RATE_LIMITED**",
       set(码们) == {404} and c == 429 and 码(b) == "RATE_LIMITED", (set(码们), c, b))
    with 库().connect() as cc:
        n = cc.execute(text("select count(*) from access_key_calls where access_key_id=:k"), {"k": ke["id"]}).scalar()
    ck("被拒的那一次也记了(31 行)—— 限流数的就是它", n == 31, n)

    print("\n▸ 吊销 / 发密钥的人没权限了")
    c, b = 打("POST", P + f"/access-keys/{kb['id']}/revoke", 体={"理由": "e2e 验吊销"})
    ck("吊销 → 成", c == 200 and b.get("吊销了吗"), (c, b))
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密b, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**吊销后马上调 → 401 ACCESS_KEY_REVOKED**", c == 401 and 码(b) == "ACCESS_KEY_REVOKED", (c, b))
    c, m = 打("POST", P + "/memberships", 体={"工号": 发人, "角色": "viewer"})
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**发密钥的人降成查看者 → 再调被拒(403 ISSUER_FORBIDDEN)**,权限每次重核",
       c == 403 and 码(b) == "ISSUER_FORBIDDEN", (c, b))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 访问 API:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
