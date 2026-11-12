#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改进验证与发布(2026-11-12;口径照《意见收集与能力持续改进 PRD》10-24 §4.3 / §5.2 / §7.1 / §7.2)。
打真起着的管理后台,不调模型 —— 进 test-e2e-ci。评测 / 清单 / 指针 / 运行直接写库造(见 _改进证据.py),验证 / 发布记录走接口。

  ① 建验证记录:缺 PRD 那七样 → 422;别的项目的评测 / 不存在的数据集版本 / 同一条评测当两组 → 422;问题单不存在 → 404
  ② **「验证通过」**:不带验证记录 → 422;三组缺一组 → 409(还差什么里点名缺的那组);评测没跑完 / 候选对不上 /
     保留组和复现组同一份数据集版本 → 409;详情里「能点验证通过吗」跟着变;**齐了 → 200,不看分数**(评测里一个分数都没有)
  ③ 改验证记录:If-Match 不带 / 对不上 → 409;时间线记「改验证记录」带前后值;下了结论的不许改 → 409
  ④ 建发布记录:缺批准人 → 422;带灰度开关 → 422;别的项目的清单 → 422;聊天助手没有那一版 → 422
  ⑤ **「发布生效」**:不带发布记录 → 422;生产指针没指着它 → 409;指着但切过去之后没有跑完的运行 → 409(**配置切过去不算**);
     只有切过去之前的运行 → 409;运行没跑完 → 409;聊天助手版本(聊天站不读这个角色)→ 409 并说清为什么;
     有一次切过去之后跑完的生产运行 → 200,回执里记着那次运行
  ⑥ 回滚:生产指针没指回去 → 409(后台不替人回滚);指回去之后 → 201,**新的一行**,原来那条内容不变;再记一次 → 409
  ⑦ **「关闭」**:发布被回滚了 → 409;旧单(验证通过 / 发布生效没绑记录)→ 409;下了结论的验证记录不能再拿来「验证通过」→ 409;
     新一轮验证 + 发布齐了 → 关闭缺完成证据仍 422 → 全齐 200,时间线那行「关闭」记着用的验证记录和发布记录
  ⑧ 问题单详情里列出验证记录和发布记录;「能做的动作」带前置条件那句话
  ⑨ 权限:查看者能读、不能建 → 403
  ⑩ 跨项目:演示项目里取正式项目的验证记录 / 发布记录 → 404
  ⑪ 库这一层也拦:通过却缺组 / 发布缺批准人 / 已生效没回执 / 回滚没指着被回滚的那条 / 三组同一条评测 —— CHECK 当场拒
  ⑫ 演示项目留一条验证记录、一条发布记录(If-Match 可达性检查从列表拿;正式项目不留)

跑完把自己造的行删掉(问题单标题、夹具 id 都以 e2e-iv- 开头)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _改进证据 as 证  # noqa: E402

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"
P = f"/api/v1/projects/{项目}"
PA = "/api/v1/projects/project_demo_a"
过, 挂 = [], []
标 = "e2e-iv-" + uuid.uuid4().hex[:8]
样例标 = "e2e-ivsample"
样例标题 = "e2e 样例问题单(改进验证 / 发布记录的 If-Match 可达性用)"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 头=None, 谁="U001"):
    req = urllib.request.Request(基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
                                 data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    for k, v in (头 or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None


def 码(b):
    return (b or {}).get("code") or ((b or {}).get("error") or {}).get("code")


def 字段(b):
    return (b or {}).get("field_errors") or ((b or {}).get("error") or {}).get("field_errors") or {}


def 话(b):
    return json.dumps(b, ensure_ascii=False)


def main():
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    with 库.connect() as cc:
        org = cc.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()
        orgA = cc.execute(text("select organization_id from projects where id='project_demo_a'")).scalar()

    def 单(iid, 项=P):
        return 打("GET", 项 + f"/issues/{iid}")[1] or {}

    def 动(iid, 动作, **额):
        return 打("POST", P + f"/issues/{iid}/actions", {"动作": 动作, **额}, {"If-Match": str(单(iid).get("revision"))})

    def 走到(iid, 动作们):
        for a, 额 in 动作们:
            c, b = 动(iid, a, **额)
            if c != 200:
                ck(f"问题单走「{a}」", False, (c, b))
                return False
        return True

    def 验(vid):
        return 打("GET", P + f"/issue-verifications/{vid}")[1] or {}

    def 发(rid):
        return 打("GET", P + f"/issue-releases/{rid}")[1] or {}

    def 改验(vid, 体, rev=None):
        rev = 验(vid).get("revision") if rev is None else rev
        return 打("PATCH", P + f"/issue-verifications/{vid}", 体, {"If-Match": str(rev)} if rev != "不带" else {})

    try:
        c, b = 打("POST", P + "/issues", {"标题": f"{标} 加急答错"})
        iid = (b or {}).get("id")
        ck("建一张问题单", c == 201 and iid, (c, b))
        with 库.begin() as cc:
            复, 回, 保, dv = 证.造评测与数据(cc, org, 项目, 标, "a")
            # 别的项目里的一条评测(拿来关联要被拒)
            外 = 证.造评测与数据(cc, orgA, "project_demo_a", 标, "x")[0]

        print("▸ ① 建验证记录的字段")
        体 = 证.验证记录体(复, 回, None, dv)
        c, b = 打("POST", P + f"/issues/{iid}/verifications", {k: v for k, v in 体.items() if k not in ("预期结果", "判分规则")})
        ck("缺预期结果 / 判分规则 → 422,点名这两样", c == 422 and {"预期结果", "判分规则"} <= set(字段(b)), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/verifications", {**体, "保留组评测": 外})
        ck("**关联别的项目的评测 → 422**", c == 422 and "保留组评测" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/verifications", {**体, "数据集版本": f"{标}-没有这版"})
        ck("数据集版本在这个项目里没有 → 422", c == 422 and "数据集版本" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/verifications", {**体, "保留组评测": 复})
        ck("同一条评测当两组用 → 422", c == 422 and "三组评测" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{标}-没有这张/verifications", 体)
        ck("问题单不存在 → 404", c == 404, (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/verifications", 体)
        vid = (b or {}).get("id")
        ck("只关联了两组也能建(评测可以后补)→ 201,待验证", c == 201 and (b or {}).get("状态") == "待验证", (c, b))

        print("\n▸ ② 「验证通过」的前置条件")
        走到(iid, [("确认问题", {}), ("开始处理", {}), ("提交验证", {})])
        c, b = 动(iid, "验证通过")
        ck("不带验证记录 → 422", c == 422 and "验证记录" in 字段(b), (c, b))
        c, b = 动(iid, "验证通过", 验证记录=f"{标}-没有这条")
        ck("验证记录不是这张单的 → 422", c == 422 and "验证记录" in 字段(b), (c, b))
        c, b = 动(iid, "验证通过", 验证记录=vid)
        ck("**三组缺一组(保留组)→ 409,点名缺的那组**", c == 409 and 码(b) == "VERIFICATION_EVIDENCE_INCOMPLETE"
           and "保留组" in 话(字段(b)), (c, b))
        d = 验(vid)
        ck("详情:能点验证通过吗 = 否,还差什么里有保留组", d.get("能点验证通过吗") is False
           and any("保留组" in x for x in d.get("还差什么", [])), d.get("还差什么"))
        ck("问题单还在待验证(被拒的那一步没动它)", 单(iid).get("状态") == "待验证")
        with 库.begin() as cc:
            同份保 = f"{标}-ev-same"
            cc.execute(text("""insert into evaluations (id, organization_id, project_id, candidate_ref, baseline_ref,
                                   dataset_version_id, scorer_version, status, executor_code, created_at, updated_at, revision)
                               values (:i, :o, :p, '{"ref": "候选v2"}', '{"ref": "基线v1"}', :dv, 's1', '已完成', '外部登记', now(), now(), 1)"""),
                       {"i": 同份保, "o": org, "p": 项目, "dv": dv})
        c, b = 改验(vid, {"保留组评测": 同份保})
        ck("补上保留组(If-Match)→ 200", c == 200 and "保留组评测" in (b or {}).get("改了", []), (c, b))
        c, b = 动(iid, "验证通过", 验证记录=vid)
        ck("保留组和复现组是同一份数据集版本 → 409(保留组要是没见过的题)", c == 409 and "同一份数据集版本" in 话(字段(b)), (c, b))
        with 库.begin() as cc:
            cc.execute(text("update evaluations set status='执行中' where project_id=:p and id=:i"), {"p": 项目, "i": 回})
        c, b = 改验(vid, {"保留组评测": 保})
        c, b = 动(iid, "验证通过", 验证记录=vid)
        ck("回归组的评测还没跑完 → 409,说它不能当结论", c == 409 and "回归组" in 话(字段(b)) and "已完成" in 话(字段(b)), (c, b))
        with 库.begin() as cc:
            cc.execute(text("update evaluations set status='已完成' where project_id=:p and id=:i"), {"p": 项目, "i": 回})
        c, b = 改验(vid, {"候选版本": "候选v3"})
        c, b = 动(iid, "验证通过", 验证记录=vid)
        ck("记录的候选版本和评测的候选对不上 → 409", c == 409 and "候选" in 话(字段(b)), (c, b))

        print("\n▸ ③ 改验证记录")
        c, b = 改验(vid, {"候选版本": "候选v2"}, rev="不带")
        ck("不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        c, b = 改验(vid, {"候选版本": "候选v2"}, rev=999)
        ck("If-Match 对不上 → 409", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 改验(vid, {"候选版本": "候选v2"})
        ck("改回候选v2 → 200", c == 200, (c, b))
        改行 = [e for e in 单(iid).get("时间线", []) if e["动作"] == "改验证记录"]
        ck("时间线记「改验证记录」带前后值", 改行 and (改行[-1].get("变化") or {}).get("候选版本") == ["候选v3", "候选v2"], 改行[-1:])
        d = 验(vid)
        ck("详情:三组齐、都能当结论 → 能点验证通过吗 = 是", d.get("能点验证通过吗") is True
           and all((g.get("评测") or {}).get("能当结论吗") for g in d.get("三组", [])), d.get("还差什么"))
        with 库.connect() as cc:
            分数 = cc.execute(text("select count(*) from scores where project_id=:p and evaluation_item_id in "
                                  "(select id from evaluation_items where project_id=:p and evaluation_id in (:a, :b, :c))"),
                             {"p": 项目, "a": 复, "b": 回, "c": 保}).scalar()
        c, b = 动(iid, "验证通过", 验证记录=vid, 说明="三组都过了,人看过原始输出")
        ck("**三组齐 → 验证通过 200(这三条评测一个分数都没有 —— 不按分数判)**", c == 200 and 分数 == 0, (c, b, 分数))
        d = 验(vid)
        ck("验证记录变成「通过」,审批人 = 点的人", d.get("状态") == "通过" and d.get("审批人") == "U001" and d.get("结论于"), d)
        c, b = 改验(vid, {"判分规则": "s2"})
        ck("下了结论的验证记录不许改 → 409", c == 409 and 码(b) == "VERIFICATION_CONCLUDED", (c, b))

        print("\n▸ ④ 建发布记录的字段")
        with 库.begin() as cc:
            rm = 证.造生产发布(cc, org, 项目, 标, "a", 跑完=False)
            外清单 = 证.造生产发布(cc, orgA, "project_demo_a", 标, "x", 跑完=False)
            ca, cav = f"{标}-ca", f"{标}-cav"
            cc.execute(text("""insert into chat_assistants (id, organization_id, project_id, role_key, name, production_version_no,
                                   created_at, updated_at) values (:i, :o, :p, :r, :n, 1, now(), now())"""),
                       {"i": ca, "o": org, "p": 项目, "r": 标, "n": f"{标} 测试助手"})
            cc.execute(text("""insert into chat_assistant_versions (id, organization_id, project_id, chat_assistant_id, version_no,
                                   head_template, tools, model_name, source_kind, content_hash, created_at)
                               values (:i, :o, :p, :a, 1, '你好', '[]', 'claude-haiku-4-5', '后台编辑', :i, now())"""),
                       {"i": cav, "o": org, "p": 项目, "a": ca})
        发体 = 证.发布记录体(rm)
        c, b = 打("POST", P + f"/issues/{iid}/releases", {k: v for k, v in 发体.items() if k != "批准人"})
        ck("缺批准人 → 422", c == 422 and "批准人" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", {**发体, "灰度开关": True})
        ck("**带灰度开关 → 422**(后台不支持,不摆)", c == 422 and "灰度" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", {**发体, "发布清单": 外清单})
        ck("**关联别的项目的发布清单 → 422**", c == 422 and "发布清单" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", {**发体, "种类": "聊天助手版本", "发布清单": None,
                                                           "聊天助手": ca, "聊天助手版本号": 7})
        ck("聊天助手没有那一版 → 422", c == 422 and "聊天助手版本号" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", 发体)
        rid = (b or {}).get("id")
        ck("建发布记录 → 201,待生效(只记,没发布任何东西)", c == 201 and (b or {}).get("状态") == "待生效", (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", {**发体, "种类": "聊天助手版本", "发布清单": None,
                                                           "聊天助手": ca, "聊天助手版本号": 1})
        rid聊 = (b or {}).get("id")
        ck("关联聊天助手版本的发布记录 → 201", c == 201, (c, b))

        print("\n▸ ⑤ 「发布生效」的前置条件 = 实际采用回执")
        c, b = 动(iid, "发布生效")
        ck("不带发布记录 → 422", c == 422 and "发布记录" in 字段(b), (c, b))
        with 库.begin() as cc:
            cc.execute(text("update environment_bindings set release_manifest_id=null where project_id=:p and id=:i"),
                       {"p": 项目, "i": f"{标}-envb-a"})
        c, b = 动(iid, "发布生效", 发布记录=rid)
        ck("生产指针没指着这份清单 → 409 ADOPTION_NOT_CONFIRMED", c == 409 and 码(b) == "ADOPTION_NOT_CONFIRMED"
           and "生产指针" in 话(b), (c, b))
        with 库.begin() as cc:
            cc.execute(text("update environment_bindings set release_manifest_id=:r where project_id=:p and id=:i"),
                       {"r": rm, "p": 项目, "i": f"{标}-envb-a"})
        c, b = 动(iid, "发布生效", 发布记录=rid)
        ck("**指针指着、但切过去之后没有跑完的运行 → 409(配置切过去不算)**", c == 409 and 码(b) == "ADOPTION_NOT_CONFIRMED"
           and "跑完" in 话(b), (c, b))
        d = 发(rid)
        ck("发布记录详情现查实际采用:确认了 = 否,说清为什么", (d.get("实际采用") or {}).get("现查") is True
           and (d.get("实际采用") or {}).get("确认了") is False and "跑完" in ((d.get("实际采用") or {}).get("为什么") or ""),
           d.get("实际采用"))
        with 库.begin() as cc:
            证.造生产运行(cc, org, 项目, f"{标}-run-early", rm)
            cc.execute(text("update execution_runs set created_at = now() - interval '1 hour' where project_id=:p and id=:i"),
                       {"p": 项目, "i": f"{标}-run-early"})
            证.造生产运行(cc, org, 项目, f"{标}-run-running", rm, 状态="running")
        c, b = 动(iid, "发布生效", 发布记录=rid)
        ck("只有切过去之前跑完的 + 一次还在跑的 → 409", c == 409 and 码(b) == "ADOPTION_NOT_CONFIRMED", (c, b))
        c, b = 动(iid, "发布生效", 发布记录=rid聊)
        ck("聊天助手版本:聊天站不读这个角色 → 409,说清取不到实际采用", c == 409 and 码(b) == "ADOPTION_NOT_CONFIRMED"
           and "聊天站不读" in 话(b), (c, b))
        ck("问题单还在待发布", 单(iid).get("状态") == "待发布")
        with 库.begin() as cc:
            证.造生产运行(cc, org, 项目, f"{标}-run-ok", rm)
        c, b = 动(iid, "发布生效", 发布记录=rid)
        ck("**切过去之后有一次跑完的生产运行 → 发布生效 200**", c == 200 and (b or {}).get("到") == "观察中", (c, b))
        d = 发(rid)
        ck("发布记录「已生效」,回执里记着那次运行", d.get("状态") == "已生效"
           and ((d.get("实际采用") or {}).get("回执") or {}).get("运行") == f"{标}-run-ok", d.get("实际采用"))
        生效行 = [e for e in 单(iid).get("时间线", []) if e["动作"] == "发布生效"]
        ck("时间线那行「发布生效」记着发布记录和回执", 生效行 and (生效行[-1].get("变化") or {}).get("发布记录") == rid
           and (生效行[-1]["变化"].get("实际采用回执") or {}).get("运行") == f"{标}-run-ok", 生效行[-1:])

        print("\n▸ ⑥ 回滚是新的一行")
        原 = 发(rid)
        c, b = 打("POST", P + f"/issue-releases/{rid}/rollbacks", {"回到": f"{标}-rm-old", "触发原因": "又承诺了交期"},
                  {"If-Match": str(原.get("revision"))})
        ck("回到的清单不存在 → 422", c == 422 and "回到" in 字段(b), (c, b))
        with 库.begin() as cc:
            cc.execute(text("""insert into release_manifests (id, organization_id, project_id, application_id, content_hash, created_at)
                               values (:i, :o, :p, :a, :i, now())"""), {"i": f"{标}-rm-old", "o": org, "p": 项目, "a": f"{标}-app-a"})
        c, b = 打("POST", P + f"/issue-releases/{rid}/rollbacks", {"回到": f"{标}-rm-old", "触发原因": "又承诺了交期"},
                  {"If-Match": str(原.get("revision"))})
        ck("**生产指针没指回去 → 409(后台不替人回滚)**", c == 409 and 码(b) == "ROLLBACK_NOT_DONE", (c, b))
        with 库.begin() as cc:
            cc.execute(text("update environment_bindings set release_manifest_id=:r where project_id=:p and id=:i"),
                       {"r": f"{标}-rm-old", "p": 项目, "i": f"{标}-envb-a"})
        c, b = 打("POST", P + f"/issue-releases/{rid}/rollbacks", {"回到": f"{标}-rm-old"}, {"If-Match": str(原.get("revision"))})
        ck("不写触发原因 → 422", c == 422 and "触发原因" in 字段(b), (c, b))
        c, b = 打("POST", P + f"/issue-releases/{rid}/rollbacks", {"回到": f"{标}-rm-old", "触发原因": "又承诺了交期"},
                  {"If-Match": str(原.get("revision"))})
        回滚id = (b or {}).get("id")
        ck("指针指回去了 → 记回滚 201,新的一行", c == 201 and 回滚id and 回滚id != rid, (c, b))
        后 = 发(rid)
        ck("**原来那条发布记录内容一个字没改**(状态、批准人、回执都在),只多了「被回滚」",
           后.get("状态") == "已生效" and 后.get("批准人") == 原.get("批准人")
           and (后.get("实际采用") or {}).get("回执") == (原.get("实际采用") or {}).get("回执") and 后.get("被回滚") == 回滚id, 后)
        rb = 发(回滚id)
        ck("回滚那一行:事件 = 回滚、状态 = 已回滚、指着被回滚的那条", (rb.get("事件"), rb.get("状态"), rb.get("回滚的是"))
           == ("回滚", "已回滚", rid), rb)
        c, b = 打("POST", P + f"/issue-releases/{rid}/rollbacks", {"回到": f"{标}-rm-old", "触发原因": "再记一次"},
                  {"If-Match": str(后.get("revision"))})
        ck("同一条发布再记一次回滚 → 409", c == 409 and 码(b) == "ALREADY_ROLLED_BACK", (c, b))

        print("\n▸ ⑦ 「关闭」要这一轮的验证记录 + 发布记录")
        c, b = 动(iid, "关闭", 处理说明="加急规则改按工序", 完成证据="三组评测都过了")
        ck("**发布被回滚了 → 关闭 409**", c == 409 and 码(b) == "CLOSE_EVIDENCE_MISSING" and "回滚" in 话(字段(b)), (c, b))
        走到(iid, [("观察期复发", {"说明": "回滚了,重新修"}), ("提交验证", {})])
        c, b = 动(iid, "验证通过", 验证记录=vid)
        ck("下了结论的验证记录不能再拿来「验证通过」→ 409", c == 409 and 码(b) == "VERIFICATION_CONCLUDED", (c, b))
        with 库.begin() as cc:
            复2, 回2, 保2, dv2 = 证.造评测与数据(cc, org, 项目, 标, "b")
            rm2 = 证.造生产发布(cc, org, 项目, 标, "b")
        c, b = 打("POST", P + f"/issues/{iid}/verifications", 证.验证记录体(复2, 回2, 保2, dv2))
        vid2 = (b or {}).get("id")
        c, b = 动(iid, "验证通过", 验证记录=vid2)
        ck("新一轮的验证记录 → 验证通过 200", c == 200, (c, b))
        c, b = 动(iid, "关闭", 处理说明="x", 完成证据="y")
        ck("待发布不能关闭 → 409(流转表)", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        c, b = 打("POST", P + f"/issues/{iid}/releases", 证.发布记录体(rm2))
        rid2 = (b or {}).get("id")
        c, b = 动(iid, "发布生效", 发布记录=rid2)
        ck("新一轮的发布记录 → 发布生效 200", c == 200, (c, b))
        c, b = 动(iid, "关闭", 处理说明="加急规则改按工序")
        ck("关闭缺完成证据(文字)→ 照旧 422", c == 422 and "完成证据" in 字段(b), (c, b))
        c, b = 动(iid, "关闭", 处理说明="加急规则改按工序", 完成证据="三组评测都过了,生产跑通一次")
        ck("**这一轮验证 + 发布都在 → 关闭 200**", c == 200 and (b or {}).get("到") == "已验证关闭", (c, b))
        关行 = [e for e in 单(iid).get("时间线", []) if e["动作"] == "关闭"]
        ck("时间线那行「关闭」记着这一轮的验证记录和发布记录(不是上一轮的)",
           关行 and (关行[-1].get("变化") or {}).get("验证记录") == vid2 and 关行[-1]["变化"].get("发布记录") == rid2, 关行[-1:])
        c, b = 打("POST", P + f"/issues/{iid}/verifications", 证.验证记录体(复2, 回2, 保2, dv2))
        ck("已关闭的单不能再挂验证记录 → 409", c == 409, (c, b))
        # 旧单:验证通过 / 发布生效 是验证记录上线之前点的(时间线里没绑记录)—— 直接写库造
        旧 = f"{标}-old"
        with 库.begin() as cc:
            cc.execute(text("""insert into issues (id, organization_id, project_id, title, status, root_cause_status, reopen_count,
                                   created_at, updated_at, revision) values (:i, :o, :p, :t, '观察中', '原因待核实', 0, now(), now(), 1)"""),
                       {"i": 旧, "o": org, "p": 项目, "t": f"{标} 旧单"})
            for k, (a, f, t) in enumerate((("提交验证", "处理中", "待验证"), ("验证通过", "待验证", "待发布"), ("发布生效", "待发布", "观察中"))):
                cc.execute(text("""insert into issue_events (id, organization_id, project_id, issue_id, action_code, from_status, to_status,
                                       created_at) values (:i, :o, :p, :s, :a, :f, :t, now() + make_interval(secs => :k))"""),
                           {"i": f"{旧}-e{k}", "o": org, "p": 项目, "s": 旧, "a": a, "f": f, "t": t, "k": k})
        c, b = 动(旧, "关闭", 处理说明="a", 完成证据="b")
        ck("**旧单(验证通过 / 发布生效没绑记录)→ 关闭 409,说清缺验证记录和发布记录**", c == 409 and 码(b) == "CLOSE_EVIDENCE_MISSING"
           and "验证记录" in 话(字段(b)) and "发布记录" in 话(字段(b)), (c, b))

        print("\n▸ ⑧ 问题单详情")
        d = 单(iid)
        ck("问题单详情列出两条验证记录、三条发布记录(含回滚那行)",
           [v["id"] for v in d.get("验证记录", [])] == [vid, vid2]
           and {r["id"] for r in d.get("发布记录", [])} == {rid, rid聊, 回滚id, rid2}, (d.get("验证记录"), d.get("发布记录")))
        c, x = 打("POST", P + "/issues", {"标题": f"{标} 看动作"})
        x = x["id"]
        走到(x, [("确认问题", {}), ("开始处理", {}), ("提交验证", {})])
        动作们 = {a["动作"]: a for a in 单(x).get("能做的动作", [])}
        ck("「能做的动作」:验证通过要验证记录、带前置条件那句话;验证失败可带验证记录",
           动作们.get("验证通过", {}).get("要的字段") == ["验证记录"] and "当结论" in (动作们["验证通过"].get("前置条件") or "")
           and 动作们.get("验证失败", {}).get("可带的字段") == ["验证记录"], 动作们)
        c, b = 打("POST", P + f"/issues/{x}/verifications", 证.验证记录体(复2, 回2, 保2, dv2))
        vx = (b or {}).get("id")
        c, b = 动(x, "验证失败", 说明="回归组挂了 3 题", 验证记录=vx)
        ck("验证失败带验证记录 → 200,那条记录标成未通过(失败的实验留着)", c == 200 and 验(vx).get("状态") == "未通过", (c, b))

        print("\n▸ ⑨ 权限")
        无权 = "E2EIVV" + uuid.uuid4().hex[:4]
        打("POST", P + "/memberships", {"工号": 无权, "角色": "viewer"})
        c, b = 打("POST", P + f"/issues/{x}/verifications", 证.验证记录体(复2, 回2, 保2, dv2), 谁=无权)
        ck("**查看者建验证记录 → 403**", c == 403, (c, b))
        c, b = 打("POST", P + f"/issues/{x}/releases", 证.发布记录体(rm2), 谁=无权)
        ck("查看者建发布记录 → 403", c == 403, (c, b))
        c, b = 打("GET", P + f"/issue-verifications/{vid}", 谁=无权)
        ck("查看者能读验证记录", c == 200, (c, b))
        c, b = 打("GET", P + f"/issue-releases?issue={iid}", 谁=无权)
        ck("查看者能读发布记录清单", c == 200 and len(b.get("items", [])) == 4, (c, b))

        print("\n▸ ⑩ 跨项目")
        c, b = 打("GET", PA + f"/issue-verifications/{vid}")
        ck("演示项目里取正式项目的验证记录 → 404", c == 404, (c, b))
        c, b = 打("GET", PA + f"/issue-releases/{rid}")
        ck("演示项目里取正式项目的发布记录 → 404", c == 404, (c, b))
        c, b = 打("POST", PA + f"/issues/{x}/verifications", 证.验证记录体(复2, 回2, 保2, dv2))
        ck("演示项目里往正式项目的问题单上挂验证记录 → 404", c == 404, (c, b))

        print("\n▸ ⑪ 库这一层也拦")
        def 库拒(sql, 约束, **参):
            """要红在**点名的那条 CHECK** 上 —— 被外键 / 别的约束拒不算(那样这条断言就没验到它说的东西)。"""
            try:
                with 库.begin() as cc:
                    cc.execute(text(sql), {"o": org, "p": 项目, **参})
                return False
            except Exception as e:
                return 约束 in str(e)
        底 = """insert into issue_verifications (id, organization_id, project_id, issue_id, defect_case_note, expected_result_note,
                    forbidden_behavior_note, baseline_version_ref, candidate_version_ref, dataset_version_id, scorer_version_ref,
                    repro_evaluation_id, regression_evaluation_id, holdout_evaluation_id, status, approver_ref, concluded_at, created_at)
                values (:i, :o, :p, :s, 'a', 'b', 'c', 'd', 'e', :dv, 'f', :r1, :r2, :r3, :st, :ap, now(), now())"""
        ck("验证记录「通过」却缺保留组 → CHECK 拒", 库拒(底, "ck_issue_verifications_passed", i=f"{标}-db1", s=x, dv=dv2, r1=复2, r2=回2, r3=None, st="通过", ap="U001"))
        ck("三组里两组是同一条评测 → CHECK 拒", 库拒(底, "ck_issue_verifications_distinct", i=f"{标}-db2", s=x, dv=dv2, r1=复2, r2=复2, r3=保2, st="待验证", ap=None))
        ck("验证记录状态不在三个里 → CHECK 拒", 库拒(底, "ck_issue_verifications_status", i=f"{标}-db3", s=x, dv=dv2, r1=None, r2=None, r3=None, st="满分", ap=None))
        发底 = """insert into issue_releases (id, organization_id, project_id, issue_id, event_code, rollback_of_id, target_type,
                      release_manifest_id, changed_deps_note, approver_name, entry_note, pilot_scope_note, rollback_version_note,
                      rollback_trigger_note, status, adoption_snapshot, effective_at, created_at)
                  values (:i, :o, :p, :s, :ev, :rb, '应用发布清单', :rm, 'a', :ap, 'c', 'd', 'e', 'f', :st, cast(:sn as jsonb), now(), now())"""
        ck("发布那一行缺批准人 → CHECK 拒", 库拒(发底, "ck_issue_releases_publish", i=f"{标}-db4", s=x, ev="发布", rb=None, rm=rm2, ap=None, st="待生效", sn=None))
        ck("已生效却没有实际采用回执 → CHECK 拒", 库拒(发底, "ck_issue_releases_effective", i=f"{标}-db5", s=x, ev="发布", rb=None, rm=rm2, ap="店长", st="已生效", sn=None))
        ck("回滚那一行没指着被回滚的那条 → CHECK 拒", 库拒(发底, "ck_issue_releases_rollback", i=f"{标}-db6", s=x, ev="回滚", rb=None, rm=rm2, ap="店长", st="已回滚",
                                                sn='{"a": 1}'))
        ck("时间线动作不在名单里 → CHECK 拒", 库拒("""insert into issue_events (id, organization_id, project_id, issue_id, action_code,
            to_status, created_at) values (:i, :o, :p, :s, '自动发布', '观察中', now())""", "ck_issue_events_action", i=f"{标}-db7", s=x))

        print("\n▸ ⑫ 演示项目留一条验证记录、一条发布记录(正式项目不留)")
        l = 打("GET", PA + "/issue-verifications")[1] or {}
        l2 = 打("GET", PA + "/issue-releases")[1] or {}
        if l.get("items") and l2.get("items"):
            ck("演示项目里已经有样例(重复跑不会多出来)", True)
        else:
            清单 = 打("GET", PA + "/issues?limit=200")[1] or {}
            样 = next((i["id"] for i in 清单.get("items", []) if i["标题"] == 样例标题), None)
            if not 样:
                样 = (打("POST", PA + "/issues", {"标题": 样例标题, "业务影响": "端到端测试留的样例"})[1] or {}).get("id")
            with 库.begin() as cc:
                有 = cc.execute(text("select count(*) from evaluations where project_id='project_demo_a' and id like :t"),
                               {"t": 样例标 + "-%"}).scalar()
                if not 有:
                    s复, s回, s保, sdv = 证.造评测与数据(cc, orgA, "project_demo_a", 样例标, "s")
                    srm = 证.造生产发布(cc, orgA, "project_demo_a", 样例标, "s", 跑完=False)
                else:
                    s复, s回, s保, sdv = (f"{样例标}-evre-s", f"{样例标}-evrg-s", f"{样例标}-evho-s", f"{样例标}-dv1-s")
                    srm = f"{样例标}-rm-s"
            c1, b1 = 打("POST", PA + f"/issues/{样}/verifications", 证.验证记录体(s复, s回, s保, sdv))
            c2, b2 = 打("POST", PA + f"/issues/{样}/releases", 证.发布记录体(srm))
            ck("演示项目里建了样例验证记录和发布记录", c1 == 201 and c2 == 201, (c1, b1, c2, b2))
    finally:
        with 库.begin() as cc:
            证.清掉(cc, 项目, 标)
            证.清掉(cc, "project_demo_a", 标)
            cc.execute(text("delete from issue_events where project_id=:p and issue_id in "
                            "(select id from issues where project_id=:p and title like :t)"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from issues where project_id=:p and title like :t"), {"p": 项目, "t": 标 + "%"})

    print(f"\n{'✅' if not 挂 else '❌'} 改进验证与发布:{len(过)} 条过,{len(挂)} 条挂")
    for x in 挂:
        print(f"  ❌ {x}")
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
