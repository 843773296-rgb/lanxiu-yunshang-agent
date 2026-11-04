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

    c, k2 = 打("POST", P + f"/workflows/{wid2}/access-keys", 谁=发人, 体={"名字": "没上生产那条的", "每天上限": 5, "有效期天数": 90})
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
    c, b = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=编, 体={"名字": "e2e", "每天上限": 5, "有效期天数": 90})
    ck("编辑者发不了(要「配置密钥与预算」)", c == 403, (c, b))
    c, k = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 主钥", "每天上限": 5, "有效期天数": 90})
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

    print("\n▸ 接入文档(按生产那一版的 schema 现生成)")
    c, doc = 打("GET", P + f"/workflows/{wid}/access-doc")
    with 库().connect() as cc:
        版 = cc.execute(text("select version_no, input_schema from workflow_versions where id=:i"), {"i": vid}).mappings().first()
    应有 = set(((版 or {}).get("input_schema") or {}).get("properties") or {})
    ck("上了生产的 → 有文档,标着生产版本号,输入字段就是生产那一版 input_schema 里的那几个",
       c == 200 and doc.get("有文档吗") and doc.get("生产版本号") == 版["version_no"]
       and {x["字段"] for x in doc.get("输入字段", [])} == 应有 and 应有, (c, doc and {k: doc.get(k) for k in ("生产版本号", "输入字段")}, 应有))
    ck("文档里写着四个对外接口和错误码(含过期)", all(t in doc.get("markdown", "") for t in
       (f"/apps/{doc.get('应用id')}/runs", "/events?after_seq=", "/cancel", "ACCESS_KEY_EXPIRED", "Idempotency-Key")), doc.get("markdown", "")[:300])
    c, doc2 = 打("GET", P + f"/workflows/{wid2}/access-doc")
    ck("没上生产的 → 明说没有文档(不拿草稿编一份)", c == 200 and doc2.get("有文档吗") is False and "生产" in doc2.get("为什么", ""), (c, doc2))

    print("\n▸ 发起 / 防重复 / 查结果")
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}})
    ck("不带幂等键 → 拒(409)", c == 409 and 码(b) == "IDEMPOTENCY_KEY_REQUIRED", (c, b))
    键 = str(uuid.uuid4())
    c, r1 = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, 键)
    ck("发起 → 202,带运行编号和跑的版本", c == 202 and (r1 or {}).get("运行编号"), (c, r1))
    c, r2 = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, 键)
    ck("**同一个幂等键再发 → 同一条运行**(不跑第二遍、不多花钱)",
       c == 202 and r2.get("运行编号") == r1.get("运行编号"), (c, r2))
    c, r3 = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "换了一段话"}}, 键)
    ck("**同一个幂等键、参数不同 → 409 IDEMPOTENCY_CONFLICT**(方案 C06:不默默返回旧的那一次)",
       c == 409 and 码(r3) == "IDEMPOTENCY_CONFLICT", (c, r3))
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
    c, kb = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 乙", "每天上限": 5, "有效期天数": 90})
    密b = kb["原文"]
    c, b = 外("GET", f"/open/v1/runs/{rid}", 密b)
    ck("**乙密钥查甲密钥发起的运行 → 404**(同一个人发的也不行)", c == 404, (c, b))
    c, b = 外("POST", f"/open/v1/apps/{k2['应用id']}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("拿这把密钥去调别的应用 → 403 WRONG_APP", c == 403 and 码(b) == "WRONG_APP", (c, b))
    c, b = 外("GET", f"/open/v1/runs/{rid}", "lx-app-" + "0" * 40)
    ck("不认识的密钥 → 401", c == 401 and 码(b) == "UNKNOWN_ACCESS_KEY", (c, b))

    print("\n▸ 每天花费上限(按用量账算)")
    c, kc = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 小额", "每天上限": 0.01, "有效期天数": 90})
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
    c, kd = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 算不出", "每天上限": 5, "有效期天数": 90})
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
    c, ke = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e 限流", "每天上限": 5, "有效期天数": 90})
    密e = ke["原文"]
    码们 = [外("GET", f"/open/v1/runs/{rid}", 密e)[0] for _ in range(30)]
    c, b = 外("GET", f"/open/v1/runs/{rid}", 密e)
    ck("前 30 次照常(404:这把查不到甲的运行),**第 31 次 → 429 RATE_LIMITED**",
       set(码们) == {404} and c == 429 and 码(b) == "RATE_LIMITED", (set(码们), c, b))
    with 库().connect() as cc:
        n = cc.execute(text("select count(*) from access_key_calls where access_key_id=:k"), {"k": ke["id"]}).scalar()
    ck("被拒的那一次也记了(31 行)—— 限流数的就是它", n == 31, n)

    print("\n▸ 有效期(用户 11-04 拍:发的时候必选、最长 1 年;Dify 对标 C05)")
    发 = lambda 名, **kw: 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": 名, "每天上限": 5, **kw})
    c, b = 发("e2e 没选有效期")
    ck("**没选有效期 → 422**(必选,不给「永不过期」)", c == 422 and "有效期天数" in ((b or {}).get("field_errors") or {}), (c, b))
    c, b = 发("e2e 45 天", 有效期天数=45)
    ck("不在 30 / 90 / 180 / 365 里 → 422", c == 422, (c, b))
    c, b = 发("e2e 两年", 有效期天数=730)
    ck("超过 1 年 → 422", c == 422, (c, b))
    c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
    主 = next((x for x in l["密钥"] if x["id"] == kid), {})
    ck("列表里给有效期至、还剩几天(90 天的那把:89–90)、没过期", 主.get("有效期至") and 主.get("还剩几天") in (89, 90)
       and 主.get("过期了吗") is False, 主)
    c, kx = 发("e2e 过期", 有效期天数=30)
    with 库().begin() as cc:
        cc.execute(text("""update access_keys set created_at = now() - interval '2 days', expires_at = now() - interval '1 hour'
                            where id=:i"""), {"i": kx["id"]})
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", kx["原文"], {"输入": {"article": "过期了还调"}}, str(uuid.uuid4()))
    ck("**过期了还调 → 401 ACCESS_KEY_EXPIRED**", c == 401 and 码(b) == "ACCESS_KEY_EXPIRED", (c, b))
    with 库().connect() as cc:
        记 = cc.execute(text("select outcome_code from access_key_calls where access_key_id=:k"), {"k": kx["id"]}).scalars().all()
        跑 = cc.execute(text("select count(*) from execution_runs where definition_ref->>'密钥id' = :k"), {"k": kx["id"]}).scalar()
    ck("**被拒的那一次记了原因「已过期」,一条运行都没建**(C05:不创建业务任务)", 记 == ["已过期"] and 跑 == 0, (记, 跑))
    c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
    ck("列表里标着已过期", next((x for x in l["密钥"] if x["id"] == kx["id"]), {}).get("过期了吗") is True)

    print("\n▸ 轮换(新钥绑同一个应用,旧的再留 24 小时)")
    c, kr = 发("e2e 轮换", 有效期天数=90)
    c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
    rv = next((x["revision"] for x in l["密钥"] if x["id"] == kr["id"]), None)
    轮 = lambda k, 体, rev: 打("POST", P + f"/access-keys/{k}/rotate", 体=体, 头=({"If-Match": str(rev)} if rev else {}))
    c, b = 轮(kr["id"], {"有效期天数": 90}, None)
    ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
    c, b = 轮(kr["id"], {"有效期天数": 7}, rv)
    ck("新钥有效期不在档里 → 422", c == 422, (c, b))
    c, b = 轮(kx["id"], {"有效期天数": 90}, 1)
    ck("已过期的不能轮换 → 409 NOT_ROTATABLE(直接重发)", c == 409 and 码(b) == "NOT_ROTATABLE", (c, b))
    c, rr = 轮(kr["id"], {"有效期天数": 180}, rv)
    新密, 新id = ((rr or {}).get("新的") or {}).get("原文", ""), ((rr or {}).get("新的") or {}).get("id")
    ck("轮换 → 201,给新钥原文(只这一次)", c == 201 and 新密.startswith("lx-app-") and 新id != kr["id"], (c, rr))
    with 库().connect() as cc:
        两 = {r["id"]: r for r in cc.execute(text("""select id, application_id, daily_cap_amount, expires_at, now() 此刻,
                                                       expires_at - created_at 长 from access_keys where id in (:a, :b)"""),
                                              {"a": kr["id"], "b": 新id}).mappings()}
    旧, 新 = 两.get(kr["id"]), 两.get(新id)
    ck("**旧钥的有效期缩到 24 小时内**,新钥绑同一个应用、同样上限、180 天",
       旧 and 新 and (旧["expires_at"] - 旧["此刻"]).total_seconds() <= 24 * 3600 + 60
       and 新["application_id"] == 旧["application_id"] and 新["daily_cap_amount"] == 旧["daily_cap_amount"]
       and 179 <= 新["长"].days <= 180, (dict(旧 or {}), dict(新 or {})))
    c, b = 外("GET", f"/open/v1/runs/{rid}", kr["原文"])
    ck("宽限期内旧钥照样认得(查别人的运行 → 404,不是 401)", c == 404, (c, b))
    c, rn = 外("POST", f"/open/v1/apps/{aid}/runs", 新密, {"输入": {"article": "新钥发起"}}, str(uuid.uuid4()))
    ck("新钥能发起", c == 202 and (rn or {}).get("运行编号"), (c, rn))

    print("\n▸ 订阅进度:按事件序号续传(Dify 对标 C07)")
    rn_id = (rn or {}).get("运行编号")
    等跑完(rn_id, 新密)
    c, 全 = 外("GET", f"/open/v1/runs/{rn_id}/events", 新密)
    号 = [e["序号"] for e in (全 or {}).get("事件", [])]
    ck(f"拉得到事件,序号严格递增(这次 {len(号)} 条),跑完了", c == 200 and 号 and 号 == sorted(set(号)) and 全.get("跑完了吗"), (c, 全))
    ck("事件只给类型 / 步骤 / 时间,**不给内容**", all(set(e) == {"序号", "类型", "步骤", "发生于"} for e in 全.get("事件", [])),
       全.get("事件", [])[:2])
    拼, 从 = [], 0
    for _ in range(len(号) + 2):
        c, 段 = 外("GET", f"/open/v1/runs/{rn_id}/events?after_seq={从}&limit=2", 新密)
        拼 += [e["序号"] for e in 段.get("事件", [])]
        从 = 段.get("下一次从这儿拉")
        if not 段.get("还有吗"):
            break
    ck("**两条一段、带「下一次从这儿拉」接着拉 → 拼起来和一次拉全的一模一样**(断了接上,不重不漏)", 拼 == 号, (拼, 号))
    c, b = 外("GET", f"/open/v1/runs/{rn_id}/events", 密)
    ck("别的密钥拉这次运行的事件 → 404", c == 404, (c, b))

    print("\n▸ 取消(规则和后台取消口同一份)")
    c, b = 外("POST", f"/open/v1/runs/{rn_id}/cancel", 密)
    ck("别的密钥取消 → 404", c == 404, (c, b))
    c, b = 外("POST", f"/open/v1/runs/{rn_id}/cancel", 新密)
    ck("**已经跑完的 → 202、什么都没改、保留真实终态「已完成」**(不谎报成已取消)",
       c == 202 and b.get("改了吗") is False and b.get("状态") == "已完成", (c, b))
    ck("说清已经发生的写入(这条流程没有业务写入 → 空清单,并写明)", b.get("已经发生的写入") == [] and "还没有" in b.get("note", ""), b)
    c, rq = 外("POST", f"/open/v1/apps/{aid}/runs", 新密, {"输入": {"article": "发起就取消"}}, str(uuid.uuid4()))
    c, b = 外("POST", f"/open/v1/runs/{rq['运行编号']}/cancel", 新密)
    ck("刚发起的就取消 → 202,状态是取消了 / 取消请求中(赶上它已经跑完就保留已完成)",
       c == 202 and b.get("状态") in ("已取消", "取消请求中", "已完成"), (c, b))
    with 库().connect() as cc:
        几次 = cc.execute(text("select count(*) from execution_runs where definition_ref->>'密钥id' = :k"), {"k": 新id}).scalar()
    ck("取消没有另起一次运行(这把新钥一共正好 2 次运行)", 几次 == 2, 几次)

    print("\n▸ 吊销 / 发密钥的人没权限了")
    c, b = 打("POST", P + f"/access-keys/{kb['id']}/revoke", 体={"理由": "e2e 验吊销"})
    ck("吊销 → 成", c == 200 and b.get("吊销了吗"), (c, b))
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密b, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**吊销后马上调 → 401 ACCESS_KEY_REVOKED**", c == 401 and 码(b) == "ACCESS_KEY_REVOKED", (c, b))
    c, b = 外("POST", f"/open/v1/runs/{rid}/cancel", 密b)
    ck("**吊销了的密钥去取消 → 401**(取消和发起过的是同一道闸,不是另写一份)", c == 401 and 码(b) == "ACCESS_KEY_REVOKED", (c, b))
    c, b = 外("GET", f"/open/v1/runs/{rid}/events", 密b)
    ck("吊销了的密钥去拉事件 → 401", c == 401 and 码(b) == "ACCESS_KEY_REVOKED", (c, b))
    c, m = 打("POST", P + "/memberships", 体={"工号": 发人, "角色": "viewer"})
    c, b = 外("POST", f"/open/v1/apps/{aid}/runs", 密, {"输入": {"article": "访问 API 端到端"}}, str(uuid.uuid4()))
    ck("**发密钥的人降成查看者 → 再调被拒(403 ISSUER_FORBIDDEN)**,权限每次重核",
       c == 403 and 码(b) == "ISSUER_FORBIDDEN", (c, b))
    c, b = 外("POST", f"/open/v1/runs/{rid}/cancel", 密)
    ck("**发密钥的人降成查看者 → 拿他的密钥取消也被拒(403)**:对外取消照样每次重核发密钥那个人的权限",
       c == 403 and 码(b) == "ISSUER_FORBIDDEN", (c, b))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 访问 API:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
