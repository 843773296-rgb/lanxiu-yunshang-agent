#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力档案与改进看板(2026-11-12;口径照《意见收集与能力持续改进 PRD》10-24 §4.4 / §7.1 / §8)。
打真起着的管理后台,不调模型 —— 进 test-e2e-ci。

  ① 建档的字段:没名字 / 依赖种类不对 / 依赖在这个项目里找不到 / 适用角色不是一串 → 422;重名 → 409
  ② **没有依赖时,评测结果 / 样本数量 / 实际运行量都显示「没有数据」,不是 0**
  ③ 流转表每一条边各走一遍(期望表**手抄在下面**,不读 capability_flow.py —— 读它就成了拿被测系统算期望值);
     详情给的「能做的动作」和手抄表一致;改状态不写说明 → 422;开始试点 / 启用 / 解除限制 之前没写已验证范围 → 422
  ④ 非法动作 → 409 TRANSITION_NOT_ALLOWED
  ⑤ If-Match 不带 / 对不上 → 409(改状态和改字段都验)
  ⑥ 改字段:时间线一行「改字段」带前后值;值没变 → 422;已启用的不许清空已验证范围 → 422
  ⑦ 问题单关联能力:能力不存在 → 422;挂上之后档案详情列出、未解决单独数;已搁置算未解决、已重复不单独算、
     已验证关闭不算未解决(还成了「最近改进」);问题单改挂另一份能力 → 两份档案的详情都跟着变
  ⑧ 依赖与现查的数:依赖只存引用、读的时候现取名字;依赖的智能体没跑过 → 运行量「没有数据」;
     跑过一次(mock)→ 有数据、算在调试里;工作流的某一版被评测过 → 评测结果 / 样本数量有数据(题数照冻结的那一版);
     依赖被归档 → 详情里「找不到」
  ⑨ 看板:我这份能力那一行的总数 / 未解决 / 观察期复发过 / 关闭后重开过;分母 = 按状态的总数之和;
     行按口径顺序排(根因按 PRD 那 9 类 + 未分类),不按数量
  ⑩ 权限:查看者能读、不能建 / 改状态 → 403
  ⑪ 跨项目:演示项目里取正式项目的档案 → 404;演示项目的问题单挂正式项目的能力 → 422
  ⑫ 库这一层也拦:试点中没有已验证范围 / 改状态没写说明 / 依赖不是数组 —— CHECK 当场拒
  ⑬ 清单:按状态筛;筛选值不合格 → 422
  ⑭ 演示项目留一份样例(If-Match 可达性检查和详情页冒烟要从列表拿;正式项目不留)

跑完把自己造的行删掉(档案名字、问题单标题、工作流 / 智能体名字都以 e2e-cp- 开头)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque

基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = "project_lanxiu"
P = f"/api/v1/projects/{项目}"
PA = "/api/v1/projects/project_demo_a"
过, 挂 = [], []
标 = "e2e-cp-" + uuid.uuid4().hex[:8]
样例名字 = "e2e 样例能力档案(If-Match 可达性 / 详情页冒烟用)"

# ⚠️ **手抄的期望表**(和 capability_flow.流转 同义,但不从它读 —— 同源谬误:拿被测系统算期望值,实现错了期望跟着错)
期望流转 = {
    "配置中": {"提交验证": "待验证", "停用": "已停用"},
    "待验证": {"开始试点": "试点中", "退回配置": "配置中", "停用": "已停用"},
    "试点中": {"启用": "已启用", "限制使用": "受限", "退回配置": "配置中", "停用": "已停用"},
    "已启用": {"限制使用": "受限", "重新验证": "待验证", "停用": "已停用"},
    "受限": {"解除限制": "已启用", "退回配置": "配置中", "停用": "已停用"},
    "已停用": {"重新配置": "配置中"},
}
期望根因顺序 = ["需求理解", "知识问题", "业务数据问题", "Skill 问题", "工具选择/执行问题", "Workflow 问题",
          "模型生成问题", "权限或证据问题", "体验或流程问题", "未分类"]


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


def 码(d):
    return (d or {}).get("code") if isinstance(d, dict) else None


def 字段(d):
    return set(((d or {}).get("field_errors") or {}).keys()) if isinstance(d, dict) else set()


def 路径(到):
    """从「配置中」走到某个状态的最短动作序列 —— 在**手抄表**上 BFS。"""
    队, 来 = deque(["配置中"]), {"配置中": None}
    while 队:
        s = 队.popleft()
        for a, t in 期望流转[s].items():
            if t not in 来:
                来[t] = (s, a); 队.append(t)
    步, s = [], 到
    while 来[s]:
        s, a = 来[s][0], 来[s][1]
        步.append(a)
    return list(reversed(步))


def 是没有数据(块):
    """「没有数据」要明说,而且块里不许藏一个 0 冒充数。"""
    return (isinstance(块, dict) and 块.get("有数据") is False and 块.get("显示") == "没有数据"
            and not any(v == 0 and not isinstance(v, bool) for v in 块.values()))


def main():
    from sqlalchemy import create_engine, text
    url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev"
    库 = create_engine(url)
    with 库.connect() as cc:
        org = cc.execute(text("select organization_id from projects where id=:p"), {"p": 项目}).scalar()

    def 建(体, 谁="U001", 项=P):
        return 打("POST", 项 + "/capability-profiles", {"名字": f"{标} 默认", **体}, 谁=谁)

    def 档(cid, 项=P):
        return 打("GET", 项 + f"/capability-profiles/{cid}")[1] or {}

    def 动(cid, 动作, rev=None, 谁="U001", **额):
        rev = 档(cid).get("revision") if rev is None else rev
        头 = {"If-Match": str(rev)} if rev != "不带" else {}
        return 打("POST", P + f"/capability-profiles/{cid}/actions", {"动作": 动作, **额}, 头, 谁=谁)

    def 改(cid, 体, rev=None):
        rev = 档(cid).get("revision") if rev is None else rev
        return 打("PATCH", P + f"/capability-profiles/{cid}", 体, {"If-Match": str(rev)})

    def 问题单(体, 项=P):
        return 打("POST", 项 + "/issues", {"标题": f"{标} 问题单", **体})

    def 单动(iid, 动作, **额):
        rev = (打("GET", P + f"/issues/{iid}")[1] or {}).get("revision")
        return 打("POST", P + f"/issues/{iid}/actions", {"动作": 动作, **额}, {"If-Match": str(rev)})

    try:
        print("▸ ① 建档的字段")
        c, b = 打("POST", P + "/capability-profiles", {"业务目标": "x"})
        ck("没名字 → 422,定位到「名字」", c == 422 and "名字" in 字段(b), (c, b))
        c, b = 建({"依赖": [{"种类": "插件", "引用": "x"}]})
        ck("依赖种类不在 智能体 / 工作流 / Skill / 工具 里 → 422", c == 422 and "依赖" in 字段(b), (c, b))
        c, b = 建({"依赖": [{"种类": "工作流", "引用": "wf_不存在"}]})
        ck("依赖在这个项目里找不到 → 422(只能引用现有的)", c == 422 and "依赖" in 字段(b), (c, b))
        c, b = 建({"适用角色": "店长"})
        ck("适用角色不是一串 → 422", c == 422 and "适用角色" in 字段(b), (c, b))
        c, K = 建({"名字": f"{标} 单笔订单风险分析", "业务目标": "店长问一笔单有没有风险时给出依据",
                  "输入": "订单号", "输出": "风险点 + 依据", "适用角色": ["店长", "店长", "顾问"], "负责人": "总部运营"})
        ck("建一份 → 201,配置中,revision 1", c == 201 and K.get("状态") == "配置中" and K.get("revision") == 1, (c, K))
        k = K.get("id")
        d = 档(k)
        ck("详情:适用角色去重、依赖是空清单、时间线一行「新建」、**没有任何分数字段**",
           d.get("适用角色") == ["店长", "顾问"] and d.get("依赖") == [] and [e["动作"] for e in d.get("时间线", [])] == ["新建"]
           and not any("分" == key[-1:] for key in d), d)
        c, b = 建({"名字": f"{标} 单笔订单风险分析"})
        ck("同项目重名 → 409", c == 409 and 码(b) == "DUPLICATE_NAME", (c, b))

        print("\n▸ ② 没有依赖时,现查的三样都是「没有数据」")
        for 块名 in ("评测结果", "样本数量", "实际运行量"):
            ck(f"{块名}:「没有数据」(不是 0)", 是没有数据(d.get(块名)), d.get(块名))
        ck("问题单数:还没有关联", (d.get("问题单数") or {}).get("关联") == 0 and d.get("关联的问题单") == [], d.get("问题单数"))

        print("\n▸ ③ 流转表每一条边")
        c, b = 动(k, "提交验证")
        ck("改状态不写说明 → 422", c == 422 and "说明" in 字段(b), (c, b))
        边数 = 0
        for 从, 边们 in 期望流转.items():
            for 动作, 到 in 边们.items():
                c, x = 建({"名字": f"{标} 边 {从}-{动作}", "已验证范围": "已验证单笔订单风险分析,批量巡检未验证"})
                xid = x.get("id")
                ok = c == 201
                for a in 路径(从):
                    c2, b2 = 动(xid, a, 说明=f"走到{从}")
                    ok = ok and c2 == 200
                dd = 档(xid)
                能 = {a["动作"]: a["到"] for a in dd.get("能做的动作", [])}
                c3, b3 = 动(xid, 动作, 说明=f"测 {从} →{动作}")
                dd2 = 档(xid)
                ck(f"{从} —{动作}→ {到}", ok and dd.get("状态") == 从 and 能 == 边们 and c3 == 200 and b3.get("到") == 到
                   and dd2.get("状态") == 到 and (dd2.get("时间线") or [{}])[-1].get("动作") == 动作
                   and (dd2.get("时间线") or [{}])[-1].get("说明") == f"测 {从} →{动作}", (从, 能, c3, b3))
                边数 += 1
        ck(f"手抄表的边一条不漏走完({边数} 条)", 边数 == sum(len(v) for v in 期望流转.values()) == 16, 边数)
        c, b = 动(k, "提交验证", 说明="配好了")
        c, b = 动(k, "开始试点", 说明="想试")
        ck("**没写已验证范围就开始试点 → 422**", c == 422 and "已验证范围" in 字段(b), (c, b))

        print("\n▸ ④ 非法动作")
        c, b = 动(k, "启用", 说明="直接启用")
        ck("待验证 → 启用(跳过试点)→ 409", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))
        c, b = 动(k, "打满分", 说明="x")
        ck("不认识的动作 → 409", c == 409 and 码(b) == "TRANSITION_NOT_ALLOWED", (c, b))

        print("\n▸ ⑤ If-Match")
        c, b = 动(k, "退回配置", rev="不带", 说明="x")
        ck("改状态不带 If-Match → 409", c == 409 and 码(b) == "IF_MATCH_REQUIRED", (c, b))
        旧 = 档(k).get("revision")
        c, b = 改(k, {"下次验证事项": "批量巡检"}, rev=旧)
        c, b = 动(k, "退回配置", rev=旧, 说明="x")
        ck("拿旧 revision 改状态 → 409 REVISION_CONFLICT", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))
        c, b = 改(k, {"负责人": "别人"}, rev=旧)
        ck("拿旧 revision 改字段 → 409 REVISION_CONFLICT", c == 409 and 码(b) == "REVISION_CONFLICT", (c, b))

        print("\n▸ ⑥ 改字段")
        c, b = 改(k, {"已验证范围": "已验证单笔订单风险分析,批量巡检未验证"})
        d = 档(k)
        末 = (d.get("时间线") or [{}])[-1]
        ck("改已验证范围 → 时间线一行「改字段」带前后值", c == 200 and 末.get("动作") == "改字段"
           and (末.get("变化") or {}).get("已验证范围") == [None, "已验证单笔订单风险分析,批量巡检未验证"], 末)
        c, b = 改(k, {"已验证范围": "已验证单笔订单风险分析,批量巡检未验证"})
        ck("值没变 → 422", c == 422, (c, b))
        动(k, "开始试点", 说明="单笔分析在杭州店试")
        动(k, "启用", 说明="试点两周没问题")
        ck("写了已验证范围之后能试点、能启用", 档(k).get("状态") == "已启用", 档(k).get("状态"))
        c, b = 改(k, {"已验证范围": ""})
        ck("**已启用的不许清空已验证范围** → 422", c == 422 and "已验证范围" in 字段(b), (c, b))

        print("\n▸ ⑦ 问题单关联能力")
        c, b = 问题单({"能力": "cp_不存在"})
        ck("挂一份不存在的能力 → 422,定位到「能力」", c == 422 and "能力" in 字段(b), (c, b))
        c, I1 = 问题单({"标题": f"{标} 风险分析漏了退款", "能力": k})
        i1 = I1.get("id")
        c2, I2 = 问题单({"标题": f"{标} 风险分析答慢", "能力": k})
        i2 = I2.get("id")
        c3, I3 = 问题单({"标题": f"{标} 风险分析重复报", "能力": k})
        i3 = I3.get("id")
        ck("三张挂着这份能力的问题单建好了", c == c2 == c3 == 201, (c, c2, c3))
        ck("问题单详情里显示挂的是哪份能力", ((打("GET", P + f"/issues/{i1}")[1] or {}).get("能力") or {}).get("id") == k)
        d = 档(k)
        ck("档案详情:3 张关联、3 张未解决", d.get("问题单数", {}).get("关联") == 3 and d["问题单数"].get("未解决") == 3
           and {s["id"] for s in d.get("关联的问题单", [])} == {i1, i2, i3}, d.get("问题单数"))
        单动(i2, "暂不处理", 说明="等下个版本", 重新评估日期="2099-01-01")
        单动(i3, "标为重复", 说明="和漏退款是一件事", 主问题=i1)
        for a, 额 in (("确认问题", {}), ("开始处理", {}), ("提交验证", {}), ("验证通过", {}), ("发布生效", {}),
                     ("观察期复发", {"说明": "又漏了"}), ("提交验证", {}), ("验证通过", {}), ("发布生效", {}),
                     ("关闭", {"处理说明": "补了退款查询", "完成证据": "原案例复跑通过"}), ("关闭后复发", {"说明": "换个店又出现"}),
                     ("提交验证", {}), ("验证通过", {}), ("发布生效", {}),
                     ("关闭", {"处理说明": "第二次修", "完成证据": "两家店复跑通过"})):
            c, b = 单动(i1, a, **额)
            if c != 200:
                ck(f"问题单走「{a}」", False, (c, b)); break
        d = 档(k)
        ck("**已搁置算未解决、已重复不单独算、已验证关闭不算未解决**:关联 2、未解决 1、已重复 1",
           d["问题单数"].get("关联") == 2 and d["问题单数"].get("未解决") == 1 and d["问题单数"].get("已重复(不单独算)") == 1,
           d.get("问题单数"))
        ck("最近改进 = 那张关闭的问题单", (d.get("最近改进") or {}).get("问题单") == i1, d.get("最近改进"))
        c, K2 = 建({"名字": f"{标} 批量巡检"})
        k2 = K2.get("id")
        rev = (打("GET", P + f"/issues/{i2}")[1] or {}).get("revision")
        c, b = 打("PATCH", P + f"/issues/{i2}", {"能力": k2}, {"If-Match": str(rev)})
        ck("问题单改挂另一份能力 → 200,时间线记前后值", c == 200 and "能力" in (b or {}).get("改了", []), (c, b))
        ck("**两份档案的详情都跟着变**:原来那份未解决 0、新那份未解决 1",
           档(k)["问题单数"].get("未解决") == 0 and 档(k2)["问题单数"].get("未解决") == 1,
           (档(k).get("问题单数"), 档(k2).get("问题单数")))
        c, l = 打("GET", P + f"/issues?capability={k2}&limit=200")
        ck("问题单清单按能力筛(看板点进来用)", c == 200 and [i["id"] for i in l["items"]] == [i2], (c, l))

        print("\n▸ ⑧ 依赖与现查的数")
        wf, ag, wv, dv, ev, xr = (f"{标}-{s}" for s in ("wf", "ag", "wv", "dv", "ev", "xr"))
        with 库.begin() as cc:
            cc.execute(text("""insert into workflows (id, organization_id, project_id, name, status, created_at, updated_at, revision)
                               values (:i, :o, :p, :n, '草稿', now(), now(), 1)"""), {"i": wf, "o": org, "p": 项目, "n": f"{标} 风险分析流程"})
            cc.execute(text("""insert into agents (id, organization_id, project_id, name, status, created_at, updated_at, revision)
                               values (:i, :o, :p, :n, '草稿', now(), now(), 1)"""), {"i": ag, "o": org, "p": 项目, "n": f"{标} 风险助手"})
        c, b = 改(k, {"依赖": [{"种类": "Skill", "引用": f"{标}-没有这个skill"}]})
        ck("依赖里写一个这个项目没有的 Skill → 422", c == 422 and "依赖" in 字段(b), (c, b))
        c, b = 改(k, {"依赖": [{"种类": "工作流", "引用": wf}, {"种类": "智能体", "引用": ag}, {"种类": "工作流", "引用": wf}]})
        d = 档(k)
        ck("依赖存进去了(去重),读的时候现取名字", c == 200 and [(x["种类"], x["引用"], x["名字"]) for x in d.get("依赖", [])]
           == [("工作流", wf, f"{标} 风险分析流程"), ("智能体", ag, f"{标} 风险助手")], d.get("依赖"))
        ck("有依赖但没跑过 → 实际运行量「没有数据」(不是 0)", 是没有数据(d.get("实际运行量")), d.get("实际运行量"))
        ck("有依赖但没评测过 → 评测结果 / 样本数量「没有数据」",
           是没有数据(d.get("评测结果")) and 是没有数据(d.get("样本数量")), (d.get("评测结果"), d.get("样本数量")))
        with 库.begin() as cc:
            cc.execute(text("""insert into execution_runs (id, organization_id, project_id, kind, definition_ref, status,
                                   execution_mode, created_at, updated_at, revision)
                               values (:i, :o, :p, 'agent', cast(:dr as jsonb), 'succeeded', 'mock', now(), now(), 1)"""),
                       {"i": xr, "o": org, "p": 项目, "dr": json.dumps({"kind": "agent_version", "id": ag})})
            cc.execute(text("""insert into workflow_versions (id, organization_id, project_id, workflow_id, version_no, created_at)
                               values (:i, :o, :p, :w, 1, now())"""), {"i": wv, "o": org, "p": 项目, "w": wf})
            cc.execute(text("""insert into dataset_versions (id, organization_id, project_id, frozen_samples, created_at)
                               values (:i, :o, :p, cast(:fs as jsonb), now())"""),
                       {"i": dv, "o": org, "p": 项目, "fs": json.dumps([{"q": 1}, {"q": 2}, {"q": 3}])})
            cc.execute(text("""insert into evaluations (id, organization_id, project_id, candidate_ref, baseline_ref,
                                   dataset_version_id, scorer_version, status, executor_code, created_at, updated_at, revision)
                               values (:i, :o, :p, cast(:c as jsonb), cast(:b as jsonb), :dv, 's1', '已完成', '外部登记', now(), now(), 1)"""),
                       {"i": ev, "o": org, "p": 项目, "dv": dv,
                        "c": json.dumps({"ref": wv, "kind": "workflow_version", "名": "v1"}), "b": json.dumps({"ref": "人工基线"})})
        d = 档(k)
        运 = d.get("实际运行量") or {}
        行 = next((x for x in 运.get("按依赖", []) if x["引用"] == ag), {})
        ck("跑过一次(mock)→ 运行量有数据,算在调试里", 运.get("有数据") is True and 行.get("调试") == 1 and 行.get("业务") == 0, 运)
        ck("没跑过的工作流不列进运行量", not any(x["引用"] == wf for x in 运.get("按依赖", [])), 运)
        评 = d.get("评测结果") or {}
        ck("工作流 v1 被评测过 → 评测结果有数据,写明它在候选那边、能当结论",
           评.get("有数据") is True and [(e["id"], e["这项能力的工作流在哪一边"], e["能当结论吗"]) for e in 评.get("评测", [])]
           == [(ev, "候选", True)], 评)
        样 = d.get("样本数量") or {}
        ck("样本数量 = 那个冻结版本的题数 3", 样.get("有数据") is True and 样.get("按数据集版本") == [
            {"数据集版本": dv, "题数": 3, "用在几次评测": 1}], 样)
        with 库.begin() as cc:
            cc.execute(text("update agents set archived_at=now() where project_id=:p and id=:i"), {"p": 项目, "i": ag})
        d = 档(k)
        行 = next((x for x in d.get("依赖", []) if x["引用"] == ag), {})
        ck("依赖的智能体被归档 → 详情里「找不到」,引用还留着", 行.get("找得到") is False and "找不到" in (行.get("状态") or ""), 行)
        ck("依赖找不到了 → 它的运行量也不算进来(只剩工作流,没跑过 → 没有数据)", 是没有数据(d.get("实际运行量")), d.get("实际运行量"))

        print("\n▸ ⑨ 看板")
        c, B = 打("GET", P + "/capability-board")
        我 = next((r for r in (B or {}).get("按能力", []) if (r.get("能力") or {}).get("id") == k), {})
        ck("我这份能力那一行:总数 1(已重复不计、搁置的改挂走了)、未解决 0、观察期复发过 1、关闭后重开过 1",
           c == 200 and (我.get("总数"), 我.get("未解决"), 我.get("观察期复发过"), 我.get("关闭后重开过")) == (1, 0, 1, 1), 我)
        我2 = next((r for r in (B or {}).get("按能力", []) if (r.get("能力") or {}).get("id") == k2), {})
        ck("改挂过去的那份:总数 1、未解决 1(已搁置算未解决)", (我2.get("总数"), 我2.get("未解决")) == (1, 1), 我2)
        ck("每一行都带分母,分母 = 按状态的总数之和",
           B.get("分母") == sum(r["总数"] for r in B.get("按状态", []))
           and all(r.get("分母") == B.get("分母") for r in B.get("按根因", []) + B.get("按能力", [])), B and B.get("分母"))
        ck("按根因的行按 PRD 那 9 类 + 未分类的顺序,不按数量排", [r["根因类别"] for r in B.get("按根因", [])] == 期望根因顺序,
           [r["根因类别"] for r in B.get("按根因", [])])
        ck("已重复单独给数,不进分母", isinstance(B.get("已重复(不计入)"), int) and B["已重复(不计入)"] >= 1
           and "已重复" not in [r["状态"] for r in B.get("按状态", [])], B.get("已重复(不计入)"))
        def 所有键(v):
            if isinstance(v, dict):
                for kk, vv in v.items():
                    yield kk; yield from 所有键(vv)
            elif isinstance(v, list):
                for vv in v:
                    yield from 所有键(vv)
        键们 = set(所有键(B))
        ck("**看板上没有排名 / 打分字段**(查的是字段名,不是说明文字)",
           not any(w in kk for kk in 键们 for w in ("排名", "名次", "得分", "分数", "智能度")), sorted(键们))

        print("\n▸ ⑩ 权限")
        无权 = "E2ECPV" + uuid.uuid4().hex[:4]
        打("POST", P + "/memberships", {"工号": 无权, "角色": "viewer"})
        c, b = 建({"名字": f"{标} 无权"}, 谁=无权)
        ck("**查看者建档 → 403**", c == 403, (c, b))
        c, b = 动(k, "停用", 谁=无权, 说明="x")
        ck("查看者改状态 → 403", c == 403, (c, b))
        c, b = 打("GET", P + f"/capability-profiles/{k}", 谁=无权)
        ck("查看者能读详情", c == 200, (c, b))
        c, b = 打("GET", P + "/capability-board", 谁=无权)
        ck("查看者能看看板", c == 200, (c, b))

        print("\n▸ ⑪ 跨项目")
        c, b = 打("GET", PA + f"/capability-profiles/{k}")
        ck("演示项目里取正式项目的档案 → 404", c == 404, (c, b))
        c, b = 打("POST", PA + f"/capability-profiles/{k}/actions", {"动作": "停用", "说明": "x"}, {"If-Match": "1"})
        ck("演示项目里改正式项目档案的状态 → 404", c == 404, (c, b))
        c, b = 问题单({"能力": k}, 项=PA)
        ck("演示项目的问题单挂正式项目的能力 → 422", c == 422 and "能力" in 字段(b), (c, b))

        print("\n▸ ⑫ 库这一层也拦")
        def 库拒(sql, **参):
            try:
                with 库.begin() as cc:
                    cc.execute(text(sql), {"o": org, "p": 项目, **参})
                return False
            except Exception as e:
                return "check" in str(e).lower() or "violates" in str(e).lower()
        ck("试点中却没有已验证范围 → CHECK 拒", 库拒("""insert into capability_profiles (id, organization_id, project_id, name, status,
            dependencies, created_at) values (:i, :o, :p, :n, '试点中', '[]', now())""", i=f"{标}-db1", n=f"{标} 库1"))
        ck("依赖不是数组 → CHECK 拒", 库拒("""insert into capability_profiles (id, organization_id, project_id, name, status,
            dependencies, created_at) values (:i, :o, :p, :n, '配置中', '{"a": 1}', now())""", i=f"{标}-db2", n=f"{标} 库2"))
        ck("时间线里改状态没写说明 → CHECK 拒", 库拒("""insert into capability_profile_events (id, organization_id, project_id,
            capability_profile_id, action_code, to_status, created_at) values (:i, :o, :p, :c, '停用', '已停用', now())""",
            i=f"{标}-db3", c=k))
        ck("状态不在六个里 → CHECK 拒", 库拒("""insert into capability_profiles (id, organization_id, project_id, name, status,
            dependencies, created_at) values (:i, :o, :p, :n, '满分', '[]', now())""", i=f"{标}-db4", n=f"{标} 库4"))

        print("\n▸ ⑬ 清单")
        c, l = 打("GET", P + "/capability-profiles?status=已启用&limit=200")
        ck("按状态筛:那份已启用的在里面,全是已启用", c == 200 and any(i["id"] == k for i in l["items"])
           and all(i["状态"] == "已启用" for i in l["items"]), (c, l))
        行 = next((i for i in l.get("items", []) if i["id"] == k), {})
        ck("清单行带关联问题单数 / 未解决数 / 依赖数", (行.get("关联问题单数"), 行.get("未解决问题单数"), 行.get("依赖数")) == (1, 0, 2), 行)
        c, b = 打("GET", P + "/capability-profiles?status=很聪明")
        ck("状态筛选不在六个里 → 422", c == 422 and "status" in 字段(b), (c, b))

        print("\n▸ ⑭ 演示项目留一份样例(正式项目不留)")
        c, l = 打("GET", PA + "/capability-profiles?limit=200")
        if not any(i["名字"] == 样例名字 for i in (l or {}).get("items", [])):
            c, b = 打("POST", PA + "/capability-profiles", {"名字": 样例名字, "业务目标": "端到端测试留的样例"})
            ck("演示项目里建了一份样例能力档案", c == 201, (c, b))
        else:
            ck("演示项目里已经有样例能力档案(重复跑不会多出来)", True)
    finally:
        with 库.begin() as cc:
            for 项 in (项目, "project_demo_a"):
                我的单 = "select id from issues where project_id=:p and title like :t"
                cc.execute(text(f"delete from issue_events where project_id=:p and issue_id in ({我的单})"), {"p": 项, "t": 标 + "%"})
                # 重复单指着主问题:先清掉指向,再删
                cc.execute(text("update issues set duplicate_of_issue_id=null, status='待分析' where project_id=:p and title like :t"),
                           {"p": 项, "t": 标 + "%"})
                cc.execute(text("delete from issues where project_id=:p and title like :t"), {"p": 项, "t": 标 + "%"})
                我的档 = "select id from capability_profiles where project_id=:p and name like :t"
                cc.execute(text(f"delete from capability_profile_events where project_id=:p and capability_profile_id in ({我的档})"),
                           {"p": 项, "t": 标 + "%"})
                cc.execute(text("delete from capability_profiles where project_id=:p and name like :t"), {"p": 项, "t": 标 + "%"})
            cc.execute(text("delete from evaluations where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from dataset_versions where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from workflow_versions where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from execution_runs where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from workflows where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})
            cc.execute(text("delete from agents where project_id=:p and id like :t"), {"p": 项目, "t": 标 + "%"})

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 能力档案与改进看板:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
