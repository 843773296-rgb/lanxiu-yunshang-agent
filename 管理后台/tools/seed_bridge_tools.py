#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频整理流程要的资源登记进后台(2026-10-24):澜绣桥的两个工具(取转写 / 写跟进)
+ 一份处理要求「客户需求提取」(用户 10-24 拍「带一份、默认选上」—— 建模板时自动选上它)。

    ./.venv/bin/python tools/seed_bridge_tools.py                         # 默认 project_demo_a(CI / 端到端用)
    ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_lanxiu   # 澜绣正式项目(常驻同步的桥只连它)

**重复跑不增加对象**:同名工具已在就不新建;契约(说明 / 入参 / 出参)变了才出新版本。

## 这两个工具后台**不执行**

`adapter = lanxiu_bridge`:工作流跑到它们时只在 `bridge_calls` 记一张单,运行挂起;
澜绣的 supervise_sync 拉回去用它自己的函数执行、回执(见 `services/api/app/bridge_api.py`)。
它们在这里登记,是为了工作流的工具步骤能选到一个**真实存在的工具版本** ——
选不到就只能手抄一个 id,而那正是改版要去掉的东西。
"""
import argparse
import hashlib
import json
import os
import sys
import uuid

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(根, "services", "api", "app"),
                os.path.join(根, "services", "api", "app", "contract")]

工具们 = [
    dict(name="取转写", side="read_only",
         purpose="按通话号取一通录音的转写原文(澜绣 call_transcript;人工改过的以改过的为准)",
         input_schema={"type": "object", "properties": {"call_id": {"type": "string", "description": "通话号,如 TS-001"}},
                       "required": ["call_id"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "text": {"type": "string"}, "call_id": {"type": "string"},
             "customer_id": {"type": "string"}, "顾问": {"type": "string"},
             "时长秒": {"type": "number"}, "人工改过": {"type": "boolean"}},
             "required": ["text", "call_id"]}),
    dict(name="写跟进", side="irreversible",
         # 不可逆写入必须有确认策略(校验器 TOOL_NO_CONFIRMATION)。这一条**不是摆设**:
         # 工作流里由「人工核对」节点承担,执行侧 runtime/桥闸.py 再查一遍(只认人工节点的批准)
         confirm={"方式": "人工确认", "绑定": "定稿内容", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="把人工核对过的定稿写成澜绣客户档案里的一条正式跟进(只追加;按幂等键去重,重试不写第二条)",
         input_schema={"type": "object", "properties": {
             "customer_id": {"type": "string"}, "内容": {"type": "string"},
             "call_id": {"type": "string"}},
             "required": ["customer_id", "内容"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "跟进号": {"type": "string"}, "customer_id": {"type": "string"},
             "是新写的": {"type": "boolean"}, "结果": {"type": "string"}},
             "required": ["跟进号", "结果"]}),
    # 经营报告(10-24,六条流程第一条)。名字就是澜绣 api.py 的工具名;正式项目里从澜绣导入过同名工具的,
    # **跳过、用导入的那份** —— 往导入的定义上追加版本,等于改了别人登记的东西
    dict(name="store_report", side="read_only",
         purpose="取门店经营报告的取数包(日 / 周 / 月;期内和存量分开,每项带口径)。桥回来时附「指纹」,保存前比它判数据变没变",
         input_schema={"type": "object", "properties": {
             "kind": {"type": "string", "description": "日 / 周 / 月;不给按模板默认"},
             "date": {"type": "string", "description": "那一期里的任意一天;不给就是上一个完整的那一期"}},
             "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
             "required": ["数据", "指纹"]}),
    # 录音加回电(10-24,用户拍「两个都要」):派「电话回电」。负责人和截止时间由核对人填,不让模型猜
    dict(name="assign_task", side="reversible",
         confirm={"方式": "人工确认", "绑定": "负责人 + 截止时间 + 定稿", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="派一条任务(录音流程里是「电话回电」),以核对人绑定的澜绣员工身份,权限判定和页面上派一样",
         input_schema={"type": "object", "properties": {
             "type": {"type": "string"}, "assignee": {"type": "string", "description": "工号或姓名"},
             "note": {"type": "string"}, "end": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
             "start": {"type": "string"}, "ref_id": {"type": "string", "description": "客户号"}},
             "required": ["type", "assignee", "note", "end"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "结果": {"type": "string"}}, "required": ["结果"]}),
    dict(name="save_report", side="reversible",
         confirm={"方式": "人工确认", "绑定": "定稿正文", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="把店长核对过的报告正文存成一版草稿(每存一次是新的一版,保存时澜绣冻结当时的取数包)",
         input_schema={"type": "object", "properties": {
             "body": {"type": "string"}, "kind": {"type": "string"}, "date": {"type": "string"}},
             "required": ["body"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "结果": {"type": "string"}}, "required": ["结果"]}),
]



# 处理要求:照澜绣现有的「通话整理」技能(agentsite/.claude/skills/call-notes)的口径写 ——
# 只用客户亲口说过的、原话逐字抄、拿不准的进「待确认项」、不给成单概率。**不新造一套口径。**
处理要求 = dict(
    key="customer_needs_extract",
    用途="客户需求提取:从一通录音的转写里整理客户要什么,原话为证,拿不准的列待确认",
    标签=["音频整理", "客户需求"],
    system=("你是汉服定制门店的通话整理助手。**只用转写里客户亲口说过的内容**:"
            "顾问说的「我们有红色的」不算客户的偏好,哪怕客户没反对。"
            "每条需求后面用引号逐字抄出客户的原话,抄不出原话的不要写。"
            "随口一提(「听起来不错,但我先不急」)不算需求。"
            "时间、预算、尺码这类没说清的,不要替客户补一个数 —— 写进「待确认项」。"
            "不给成单概率,不编店里有没有货。"),
    user=("客户号:{{客户}}\n\n通话转写:\n{{转写}}\n\n"
          "按 JSON 输出:需求(一段话,每条带原话)、时间、预算、待确认项(列表)、"
          "跟进草稿(顾问能直接存进客户档案的一段话:客户要什么、下一步做什么)、"
          "类别(只能是 明确需求 / 考虑中 / 无明确需求 / 信息不足 之一:「好看,但现在不买」是无明确需求,"
          "客户说「不方便联系」也不算有意向)。查不到的写「没提到」。"),
    变量=[{"名称": "转写", "必填": True, "来源": "上一步结果", "类型": "string", "说明": "取转写那一步的原文"},
          {"名称": "客户", "必填": True, "来源": "用户输入", "类型": "string", "说明": "客户号"}],
    输出={"格式": "json", "必含项": ["需求", "时间", "预算", "待确认项", "跟进草稿", "类别"],
          "未知值规则": "没提到就写「没提到」,**不要编一个数,也不要留空**"},
)


# 经营报告撰写(10-24):照澜绣「经营报告」技能(agentsite/.claude/skills/store-report)的口径 —— 不新造一套
报告撰写 = dict(
    key="store_report_write",
    用途="经营报告撰写:照取数包写一期门店经营报告,期内和存量分开,每个数带口径,原因标成判断",
    标签=["经营报告"],
    system=("你是汉服定制门店的经营报告撰写助手。**只用取数包里的数**,一个数都不许自己算或编。"
            "期内(这一期里发生的)和存量(截至今天还压着的)分开写,不许混在一句里。"
            "每个数后面带上它的口径(取数包里写着)。取数包「取不到的」照实列出来,不许略过。"
            "说原因时标明「这是判断」,不当成事实。下期改进只写建议,不替店长定。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:正文(一份店长能直接存的报告,分「期内 / 存量 / 取不到的 / 原因判断 / 下期建议」几段)、"
          "待确认项(列表:店长需要自己核一下的地方)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "store_report 那一步的数据"}],
    输出={"格式": "json", "必含项": ["正文", "待确认项"], "未知值规则": "取数包里没有的写「取不到」,不编"},
    变更说明="经营报告模板默认的处理要求(10-24)",
)

处理要求们 = (处理要求, 报告撰写)


def 登记处理要求(c, 项目, org, 处理要求=处理要求):
    """→ (版本 id, 怎么了)。内容没变不出新版本。"""
    from sqlalchemy import text
    m = {"用途": 处理要求["用途"], "标签": 处理要求["标签"], "system": 处理要求["system"],
         "user": 处理要求["user"], "变更说明": 处理要求.get("变更说明", "音频整理模板默认的处理要求(10-24)")}
    h = hashlib.sha256(json.dumps([m, 处理要求["变量"], 处理要求["输出"]], sort_keys=True,
                                  ensure_ascii=False).encode()).hexdigest()[:32]
    c.execute(text("""insert into prompt_drafts (id, organization_id, project_id, key, messages,
                          variable_schema, output_schema, params, revision, created_at, created_by, updated_at)
                      values (:i,:o,:p,:k, cast(:m as jsonb), cast(:vs as jsonb), cast(:os as jsonb),
                              '{}'::jsonb, 1, now(), 'seed-bridge', now())
                      on conflict (project_id, id) do nothing"""),
              {"i": f"pr_{处理要求['key']}", "o": org, "p": 项目, "k": 处理要求["key"],
               "m": json.dumps(m, ensure_ascii=False), "vs": json.dumps(处理要求["变量"], ensure_ascii=False),
               "os": json.dumps(处理要求["输出"], ensure_ascii=False)})
    末 = c.execute(text("""select id, version_no, content_hash from prompt_versions
                          where project_id=:p and key=:k order by version_no desc limit 1"""),
                   {"p": 项目, "k": 处理要求["key"]}).mappings().first()
    if 末 and 末["content_hash"] == h:
        return 末["id"], "没动"
    vid = "pv_" + uuid.uuid4().hex[:12]
    c.execute(text("""insert into prompt_versions (id, organization_id, project_id, key, version_no,
                          messages, variable_schema, output_schema, params, content_hash,
                          created_at, created_by, updated_at, revision)
                      values (:i,:o,:p,:k,:v, cast(:m as jsonb), cast(:vs as jsonb), cast(:os as jsonb),
                              '{}'::jsonb, :h, now(), 'seed-bridge', now(), 1)"""),
              {"i": vid, "o": org, "p": 项目, "k": 处理要求["key"], "v": (末["version_no"] if 末 else 0) + 1,
               "m": json.dumps(m, ensure_ascii=False), "vs": json.dumps(处理要求["变量"], ensure_ascii=False),
               "os": json.dumps(处理要求["输出"], ensure_ascii=False), "h": h})
    return vid, ("新版本" if 末 else "新建")


def _哈希(t):
    return "sha256:" + hashlib.sha256(json.dumps(t, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    # 默认演示项目:CI 是新库,seed_demo 只建演示项目 —— 默认正式项目的话,
    # seed_rerun_check 一跑就「没有项目」(正式项目由人显式点名)
    ap.add_argument("--项目", default="project_demo_a")
    a = ap.parse_args()
    from sqlalchemy import text
    from db import 事务
    出 = []
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": a.项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {a.项目}"); return 1
        for t in 工具们:
            旧行 = c.execute(text("""select id, adapter from tool_definitions where project_id=:p and name=:n
                                   and archived_at is null"""), {"p": a.项目, "n": t["name"]}).mappings().first()
            if 旧行 and 旧行["adapter"] != "lanxiu_bridge":
                出.append((t["name"], 旧行["id"], f"项目里已有导入的同名工具({旧行['adapter']}),用它、不动它")); continue
            旧 = 旧行["id"] if 旧行 else None
            if 旧:
                did = 旧
            else:
                did = "td_" + uuid.uuid4().hex[:16]
                c.execute(text("""insert into tool_definitions (id, organization_id, project_id, name,
                    purpose, side_effect_type, adapter, owner, draft_revision, status,
                    created_at, created_by, updated_at, revision)
                    values (:i,:o,:p,:n,:pu,:se,'lanxiu_bridge','lanxiu-bridge',0,'active',
                            now(),'seed-bridge', now(), 1)"""),
                          {"i": did, "o": org, "p": a.项目, "n": t["name"], "pu": t["purpose"],
                           "se": t["side"]})
            h = _哈希(t)
            末 = c.execute(text("""select id, version_no, content_hash from tool_versions
                                  where project_id=:p and tool_definition_id=:d
                                  order by version_no desc limit 1"""),
                           {"p": a.项目, "d": did}).mappings().first()
            if 末 and 末["content_hash"] == h:
                出.append((t["name"], 末["id"], "没动")); continue
            vid = "tv_" + uuid.uuid4().hex[:16]
            c.execute(text("""insert into tool_versions (id, organization_id, project_id,
                tool_definition_id, version_no, model_description, input_schema, output_schema,
                side_effect_type, allowed_scopes, confirmation_policy, idempotency_strategy, timeout_seconds,
                retry_policy, redaction, server_bound_arguments, pollable, content_hash,
                created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:d,:v,:md, cast(:ins as jsonb), cast(:outs as jsonb), :se,
                        cast('[]' as jsonb), cast(:cp as jsonb), cast(:idem as jsonb), 600, cast(:rp as jsonb),
                        cast('{}' as jsonb), cast('{}' as jsonb), false, :h,
                        now(),'seed-bridge', now(), 1)"""),
                      {"i": vid, "o": org, "p": a.项目, "d": did, "v": (末["version_no"] if 末 else 0) + 1,
                       "md": t["purpose"], "ins": json.dumps(t["input_schema"], ensure_ascii=False),
                       "outs": json.dumps(t["output_schema"], ensure_ascii=False), "se": t["side"],
                       "cp": json.dumps(t["confirm"], ensure_ascii=False) if t.get("confirm") else None,
                       "idem": json.dumps({"键": "(运行, 步骤, 第几次挂起)", "谁去重": "澜绣写跟进那一侧"},
                                          ensure_ascii=False),
                       "rp": json.dumps({"重试": "不重试 —— 等回执,不重发"}, ensure_ascii=False), "h": h})
            出.append((t["name"], vid, "新版本" if 末 else "新建"))
        for 要 in 处理要求们:
            v, how = 登记处理要求(c, a.项目, org, 要)
            出.append((f"处理要求「{要['用途'].split(':')[0]}」", v, how))
    for n, v, how in 出:
        print(f"  {n:4s} {v}  {how}")
    print(f"✅ 音频整理要的资源登记好了({a.项目},{len(出)} 项)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
