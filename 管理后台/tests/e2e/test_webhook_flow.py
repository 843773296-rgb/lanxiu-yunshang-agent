#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook 触发端到端(2026-11-20,工作流二期 2-2;规格 11-15 已拍,验收三条照规划逐条)。

打真起着的 :8801。发 / 管密钥带 X-Dev-User;两个 Webhook 地址只带访问密钥。
测试流程是「开始(Webhook,两项参数)→ 结束(原样返回 article)」,不调模型,哪个项目都跑得了。

逐条:
  ① 调试地址只跑草稿:没发布也能跑,跑的是草稿、结果原样带回
  ② 参数类型不对 → 422 WEBHOOK_PARAM_INVALID,说明里点名那一项,**不建运行**;缺必填同样 422(契约里「输入无效」就是 422,没有 400)
  ③ 错密钥 → 401,**不建运行**
  ④ 正式地址:没上生产 → 409;发布后 → 202、钉生产那一版、以发密钥的人的身份跑、记「发起=Webhook」
  ⑤ 同一个幂等键:参数相同 → 同一条运行;参数不同 → 409 IDEMPOTENCY_CONFLICT
  ⑥ 不是 Webhook 开头的流程 → 409 WEBHOOK_NOT_START
  ⑦ 只收登记过的参数:多推的键不进流程输入

没覆盖、写明:「写数据的步骤前面必须有人工介入」那条检查打在离线自测 tests/orchestration/test_webhook_start.py
(要一个写入工具版本,这里的测试流程不带业务动作);它靠的读写查询接线由 test_failure_default ⑧ 守。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _清成员 as 成员  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_lanxiu")   # 同访问 API 那份:demo_a 每日预算 0,密钥发不出来
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


def 说(d):
    return json.dumps(d or {}, ensure_ascii=False)


def 外(路, 密, 体, 键=None):
    头 = {"Authorization": "Bearer " + 密} if 密 else {}
    if 键:
        头["Idempotency-Key"] = 键
    return 打("POST", 路, 谁=None, 体=体, 头=头)


def 库():
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    return create_engine(url)


def 这把发起的运行数(kid):
    from sqlalchemy import text
    with 库().connect() as cc:
        return cc.execute(text("select count(*) from execution_runs where definition_ref->>'密钥id'=:k"), {"k": kid}).scalar()


def 等跑完(rid):
    for _ in range(60):
        c, d = 打("GET", P + f"/execution-runs/{rid}")
        if c == 200 and d.get("是终态吗"):
            return d
        time.sleep(1)
    return d


建的工作流 = []


def 收尾():
    for wid in list(建的工作流):
        try:
            c, l = 打("GET", P + f"/workflows/{wid}/access-keys")
            for k in (l or {}).get("密钥") or []:
                if not (k.get("吊销于") or k.get("revoked_at")):
                    打("POST", P + f"/access-keys/{k['id']}/revoke", 体={"理由": "e2e 收尾"})
            c, b = 打("POST", P + f"/workflows/{wid}/archive", 体={"理由": "e2e 收尾"})
            if c != 200:
                print(f"  ⚠️ 收尾没归档成 {wid}:{c} {b}")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 收尾出错 {wid}:{type(e).__name__} {e}")
    建的工作流.clear()


参数表 = {"type": "object", "properties": {"article": {"type": "string", "title": "正文"},
                                         "份数": {"type": "integer", "title": "份数"}},
          "required": ["article"]}


def 建一条(名, 方式):
    c, w = 打("POST", P + "/workflows", 体={"名称": f"{名} {uuid.uuid4().hex[:6]}", "模板": "空白"})
    wid = (w or {}).get("id")
    if wid:
        建的工作流.append(wid)
    c, d = 打("GET", P + f"/workflows/{wid}")
    定义 = d["草稿"]["定义"]
    定义["edges"] = [{"source": "start", "target": "finish", "port": "success"}]
    for n in 定义["nodes"]:
        if n["type"] == "start":
            n.setdefault("config", {})["start_mode"] = 方式
            n["config"]["input_schema"] = 参数表
        if n["type"] == "end":
            n["config"]["bindings"] = {"summary": {"source": "input", "pointer": "/article"}}
    c, b = 打("PATCH", P + f"/workflows/{wid}/draft", 体={"定义": 定义}, 头={"If-Match": str(d["草稿"]["revision"])})
    return wid, c, b


def main():
    print("▸ 准备:一条 Webhook 开头的流程(先不发布)+ 一个发密钥的管理员")
    wid, c, b = 建一条("e2e Webhook", "Webhook")
    ck("建了「开始(Webhook)→ 结束」并存了草稿", bool(wid) and c == 200, (c, b))
    c, vb = 打("POST", P + f"/workflows/{wid}/validate")
    ck("检查配置:Webhook 开头认得(没有 START_MODE_UNKNOWN)", c == 200 and "START_MODE_UNKNOWN" not in 说(vb), (c, vb))
    发人 = 成员.记(项目, "E2EWH" + uuid.uuid4().hex[:4])
    c, m = 打("POST", P + "/memberships", 体={"工号": 发人, "角色": "admin"})
    ck("建了一个管理员(发密钥用)", c in (200, 201), (c, m))
    c, k = 打("POST", P + f"/workflows/{wid}/access-keys", 谁=发人, 体={"名字": "e2e webhook", "每天上限": 5, "有效期天数": 90})
    密, kid, aid = (k or {}).get("原文", ""), (k or {}).get("id"), (k or {}).get("应用id")
    ck("发了一把访问密钥", c == 201 and 密 and kid and aid, (c, k))
    调试址, 正式址 = f"/open/v1/apps/{aid}/webhook/debug", f"/open/v1/apps/{aid}/webhook"

    print("\n▸ ① 调试地址只跑草稿")
    c, r = 外(调试址, 密, {"article": "Webhook 调试", "份数": 2, "多推的": "不该进流程"}, str(uuid.uuid4()))
    ck("没发布也能用调试地址 → 202,跑的是草稿", c == 202 and r.get("跑的版本") == "草稿" and r.get("运行编号"), (c, r))
    d = 等跑完(r.get("运行编号"))
    ck("跑成功了", d.get("执行状态") == "succeeded", d.get("执行状态"))
    from sqlalchemy import text
    with 库().connect() as cc:
        来 = cc.execute(text("select definition_ref, input_snapshot, principal from execution_runs where id=:i"),
                       {"i": r.get("运行编号")}).mappings().first()
    ck("来源是草稿、记着「Webhook 调试」和这把密钥", 来 and 来["definition_ref"].get("kind") == "graph_draft"
       and 来["definition_ref"].get("发起") == "Webhook 调试" and 来["definition_ref"].get("密钥id") == kid, dict(来 or {}))
    ck("⑦ 只收登记过的参数:多推的键没进流程输入", 来 and set((来["input_snapshot"] or {})) == {"article", "份数"},
       (来 or {}).get("input_snapshot"))

    print("\n▸ ② 参数不对 → 422,不建运行")
    前 = 这把发起的运行数(kid)
    c, b = 外(调试址, 密, {"article": "x", "份数": "三份"}, str(uuid.uuid4()))
    ck("类型不对 → 422 WEBHOOK_PARAM_INVALID,说明里点名「份数」", c == 422 and 码(b) == "WEBHOOK_PARAM_INVALID" and "份数" in 说(b), (c, b))
    c, b = 外(调试址, 密, {"份数": 1}, str(uuid.uuid4()))
    ck("缺必填 → 422,点名「正文」", c == 422 and 码(b) == "WEBHOOK_PARAM_INVALID" and "正文" in 说(b), (c, b))
    c, b = 外(调试址, 密, ["不是对象"], str(uuid.uuid4()))
    ck("请求体不是 JSON 对象 → 422", c == 422 and 码(b) == "WEBHOOK_PARAM_INVALID", (c, b))
    ck("这三次一条运行都没建", 这把发起的运行数(kid) == 前, (前, 这把发起的运行数(kid)))

    print("\n▸ ③ 错密钥 → 401,不建运行")
    c, b = 外(调试址, "lx-app-" + "x" * 40, {"article": "x"}, str(uuid.uuid4()))
    ck("认不出的密钥 → 401", c == 401, (c, b))
    c, b = 外(调试址, "", {"article": "x"}, str(uuid.uuid4()))
    ck("不带密钥 → 401", c == 401, (c, b))
    c, b = 外(调试址, 密, {"article": "x"})
    ck("不带幂等键 → 409 IDEMPOTENCY_KEY_REQUIRED", c == 409 and 码(b) == "IDEMPOTENCY_KEY_REQUIRED", (c, b))
    ck("一条运行都没建", 这把发起的运行数(kid) == 前, (前, 这把发起的运行数(kid)))

    print("\n▸ ④ 正式地址")
    c, b = 外(正式址, 密, {"article": "x"}, str(uuid.uuid4()))
    ck("没上生产 → 409 NOT_IN_PRODUCTION", c == 409 and 码(b) == "NOT_IN_PRODUCTION", (c, b))
    c, v = 打("POST", P + f"/workflows/{wid}/versions", 体={"变更说明": "e2e Webhook"})
    vid = (v or {}).get("id")
    ck("出了一版", c == 201 and vid, (c, v))
    c, t = 打("POST", P + "/execution-runs", 体={"workflow_id": wid, "workflow_version_id": vid, "输入": {"article": "上生产前测一次"}},
             头={"Idempotency-Key": str(uuid.uuid4())})
    ck("上生产前照这一版试运行一次 → 成功", 等跑完((t or {}).get("resource_id")).get("执行状态") == "succeeded", (c, t))

    def 发生产():
        return 打("POST", P + f"/workflows/{wid}/releases", 体={"版本id": vid, "环境": "production"},
                 头={"Idempotency-Key": str(uuid.uuid4())})
    c, b = 发生产()
    if c == 422:
        打("POST", P + f"/releases/{(b.get('field_errors') or {}).get('清单id')}/reviews", 体={"结论": "通过"})
        c, b = 发生产()
    ck("审核、发到生产", c == 202, (c, b))
    键 = str(uuid.uuid4())
    c, r1 = 外(正式址, 密, {"article": "Webhook 正式"}, 键)
    ck("发布后 → 202,跑的是生产那一版", c == 202 and isinstance(r1.get("跑的版本"), int) and r1.get("运行编号"), (c, r1))
    d = 等跑完(r1.get("运行编号"))
    ck("跑成功了", d.get("执行状态") == "succeeded", d.get("执行状态"))
    with 库().connect() as cc:
        来 = cc.execute(text("select definition_ref, principal from execution_runs where id=:i"),
                       {"i": r1.get("运行编号")}).mappings().first()
    ck("**以发密钥的人的身份跑**、记「发起=Webhook」、钉生产那一版", 来 and 来["principal"] == 发人
       and 来["definition_ref"].get("发起") == "Webhook" and 来["definition_ref"].get("version_id") == vid, dict(来 or {}))

    print("\n▸ ⑤ 幂等键")
    c, r2 = 外(正式址, 密, {"article": "Webhook 正式"}, 键)
    ck("同一个键、同样的参数 → 同一条运行", c == 202 and r2.get("运行编号") == r1.get("运行编号"), (c, r2))
    c, r3 = 外(正式址, 密, {"article": "换了一段"}, 键)
    ck("同一个键、参数不同 → 409 IDEMPOTENCY_CONFLICT", c == 409 and 码(r3) == "IDEMPOTENCY_CONFLICT", (c, r3))

    print("\n▸ ⑥ 不是 Webhook 开头 → 拒")
    wid2, c, b = 建一条("e2e Webhook·用户输入开头", "用户输入")
    c, k2 = 打("POST", P + f"/workflows/{wid2}/access-keys", 谁=发人, 体={"名字": "e2e 非webhook", "每天上限": 5, "有效期天数": 90})
    c, b = 外(f"/open/v1/apps/{(k2 or {}).get('应用id')}/webhook/debug", (k2 or {}).get("原文", ""), {"article": "x"}, str(uuid.uuid4()))
    ck("用户输入开头的草稿 → 409 WEBHOOK_NOT_START", c == 409 and 码(b) == "WEBHOOK_NOT_START", (c, b))

    print("\n▸ 收尾:吊销密钥、归档工作流")
    收尾()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Webhook:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        收尾()
    sys.exit(rc)
