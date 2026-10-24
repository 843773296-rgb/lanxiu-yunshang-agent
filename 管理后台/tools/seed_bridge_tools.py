#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频整理流程要的资源登记进后台(2026-10-24):澜绣桥的两个工具(取转写 / 写跟进)
+ 一份处理要求「客户需求提取」(用户 10-24 拍「带一份、默认选上」—— 建模板时自动选上它)。

    ./.venv/bin/python tools/seed_bridge_tools.py                   # 默认 project_lanxiu
    ./.venv/bin/python tools/seed_bridge_tools.py --项目 project_demo_a

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
          "跟进草稿(顾问能直接存进客户档案的一段话:客户要什么、下一步做什么)。查不到的写「没提到」。"),
    变量=[{"名称": "转写", "必填": True, "来源": "上一步结果", "类型": "string", "说明": "取转写那一步的原文"},
          {"名称": "客户", "必填": True, "来源": "用户输入", "类型": "string", "说明": "客户号"}],
    输出={"格式": "json", "必含项": ["需求", "时间", "预算", "待确认项", "跟进草稿"],
          "未知值规则": "没提到就写「没提到」,**不要编一个数,也不要留空**"},
)


def 登记处理要求(c, 项目, org):
    """→ (版本 id, 怎么了)。内容没变不出新版本。"""
    from sqlalchemy import text
    m = {"用途": 处理要求["用途"], "标签": 处理要求["标签"], "system": 处理要求["system"],
         "user": 处理要求["user"], "变更说明": "音频整理模板默认的处理要求(10-24)"}
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
    ap.add_argument("--项目", default="project_lanxiu")
    a = ap.parse_args()
    from sqlalchemy import text
    from db import 事务
    出 = []
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"), {"p": a.项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {a.项目}"); return 1
        for t in 工具们:
            旧 = c.execute(text("""select id from tool_definitions where project_id=:p and name=:n
                                   and archived_at is null"""), {"p": a.项目, "n": t["name"]}).scalar()
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
        v, how = 登记处理要求(c, a.项目, org)
        出.append(("处理要求「客户需求提取」", v, how))
    for n, v, how in 出:
        print(f"  {n:4s} {v}  {how}")
    print(f"✅ 音频整理要的资源登记好了({a.项目},{len(出)} 项)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
