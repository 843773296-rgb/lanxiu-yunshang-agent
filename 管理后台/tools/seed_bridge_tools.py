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
    # 订单交付风险(10-25,六条第三条,用户拍「全用规则分档,模型只写建议」):桥专门做的读,只查这一单
    dict(name="订单交付风险", side="read_only",
         purpose="查这一笔订单的交付风险:档(已延期 / 需关注 / 暂无已识别风险 / 无法判断 / 已结束 / 不适用)由规则判,带依据和缺什么",
         input_schema={"type": "object", "properties": {
             "order_id": {"type": "string", "description": "订单号"},
             "临近天数": {"type": "integer", "description": "离承诺完工日几天内算需关注,默认 3"}},
             "required": ["order_id"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
             "required": ["数据", "指纹"]}),
    # 老客召回(10-25,六条第五条):交叉规则复用澜绣「客户召回」技能第二步,桥专门做 —— 两份名单一次最多 100 个,
    # 拿两页去交叉会漏,所以逐人核实
    # 每周交付风险清单(11-22,用户拍方案 §3.5 第二个业务定时任务):全店口径直接用澜绣现成的两个只读工具,不另造桥工具。
    # 正式项目里这两个是从澜绣导入的(adapter lanxiu-shop),种子看到同名导入的就用它不动;演示项目没导入,这里登记成桥工具让 e2e 能跑
    dict(name="factory_chase", side="read_only",
         purpose="该催工厂的单 + 要人看的工厂回传(全店,只读):开工超期没回接单的、承诺完工日临近 / 已过的,带生产方和承诺完工日",
         input_schema={"type": "object", "properties": {}, "additionalProperties": False},
         output_schema={"type": "object", "properties": {"数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
                        "required": ["数据"]}),
    dict(name="delay_pending", side="read_only",
         purpose="工厂延期了、还没告诉顾客的单(全店,只读):原定完工日、延到什么时候、为什么、归属顾问",
         input_schema={"type": "object", "properties": {}, "additionalProperties": False},
         output_schema={"type": "object", "properties": {"数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
                        "required": ["数据"]}),
    dict(name="召回名单", side="read_only",
         purpose="有由头的回访名单:促活名单和流失预警逐人交叉(两份都在的排前面、标严重程度;只在流失的单列「在流失、等由头」),"
                 "每人带归属顾问、在不在职、有没有未完成的回访任务;范围跟着绑定员工(顾问看自己名下、店长看本店)",
         input_schema={"type": "object", "properties": {
             "上限": {"type": "integer", "description": "最多列几个人,默认 20,最多 100"}},
             "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
             "required": ["数据", "结果"]}),
    dict(name="派回访任务", side="reversible",
         confirm={"方式": "人工确认", "绑定": "要派的客户号 + 回访截止", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="给店长勾了的客户各派一条「电话回电」给客户的归属顾问;不在名单里 / 顾问离职或没有 / 已有未完成回访 / "
                 "派之前再核已经没由头的,逐人跳过并写明",
         input_schema={"type": "object", "properties": {
             "客户号们": {"type": "string", "description": "逗号分隔"},
             "截止": {"type": "string", "description": "YYYY-MM-DD 或 YYYY-MM-DD HH:MM"},
             "名单": {"type": "array", "description": "召回名单那一步的「名单」"},
             "话术": {"type": "array", "description": "模型逐人写的(可选)"}},
             "required": ["客户号们", "截止", "名单"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "结果": {"type": "string"}}, "required": ["结果"]}),
    # 库存补货(10-25,六条第六条):档用澜绣现成的库存预警口径;派走现成的预警派单(防重复派、只派店长 / 总部)
    dict(name="补货预警", side="read_only",
         purpose="这一个 SKU 现在在哪一档(发不出 / 断货 / 快没了 / 卖不动 / 够,库存预警同一把尺)、要不要派补货跟进、有没有没办完的补货跟进",
         input_schema={"type": "object", "properties": {"sku": {"type": "string", "description": "SKU 号"}},
                       "required": ["sku"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
             "required": ["数据", "结果"]}),
    dict(name="派补货跟进", side="reversible",
         confirm={"方式": "人工确认", "绑定": "补货负责人 + 补货截止", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="从库存预警派一条「补货跟进」(澜绣现成的预警派单:档位当场重算、不在预警里不派、同一件事没办完不重派、只派店长 / 总部运营)",
         input_schema={"type": "object", "properties": {
             "sku": {"type": "string"}, "负责人": {"type": "string", "description": "工号"},
             "截止": {"type": "string", "description": "YYYY-MM-DD 或 YYYY-MM-DD HH:MM"}, "note": {"type": "string"}},
             "required": ["sku", "负责人", "截止"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "结果": {"type": "string"}}, "required": ["结果"]}),
    # 差评返修(10-25,六条第四条):判责复用现成的返修判定表;用户拍「超店长权限的停下报总部,不写」
    dict(name="差评研判", side="read_only",
         purpose="这一条差评的事实(差评、这一单的服务记录和售后)+ 按现成返修判定表给的判责建议;判定表没覆盖就说交店长判",
         input_schema={"type": "object", "properties": {"pkg": {"type": "string", "description": "差评的包裹号"}},
                       "required": ["pkg"], "additionalProperties": False},
         output_schema={"type": "object", "properties": {
             "数据": {"type": "object"}, "指纹": {"type": "string"}, "结果": {"type": "string"}},
             "required": ["数据", "结果"]}),
    dict(name="差评处置", side="irreversible",
         confirm={"方式": "人工确认", "绑定": "店长定的处置 / 责任方 / 费用", "由谁承担": "工作流里的人工核对节点",
                  "执行侧再查": "runtime/桥闸.py —— 这次运行里没有人工节点的批准就不记单"},
         purpose="店长定了之后办:返修(建返修单 → 判责)或说明后关闭差评;我方出钱超店长权限、或关闭方式要出钱 → 不写,报总部 / 回澜绣办",
         input_schema={"type": "object", "properties": {
             "pkg": {"type": "string"}, "店长定的": {"type": "object", "description": "人工核对节点的整个输出"}},
             "required": ["pkg", "店长定的"], "additionalProperties": False},
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

# 经营日报草稿(11-22,用户拍「按方案 §5.3 的六段另写一套日报处理要求」;方案《业务定时与项目定期审查及 Markdown 交付》):
# 和月度 / 周度「经营报告」不是一回事 —— 日报是**草稿**给人看,六段里「建议动作(尚未执行)」「数据来源与执行证据」正是草稿该有的
日报草稿撰写 = dict(
    key="store_daily_draft_write",
    用途="经营日报草稿撰写:照取数包写一份门店经营日报草稿,六段固定结构,只用取数包里的数,缺的写「待补数据」",
    标签=["经营日报草稿"],
    system=("你是汉服定制门店的经营日报撰写助手,写的是**草稿**,店长会再核。**只用取数包里的数**,一个数都不许自己算或编;"
            "每个数后面带口径和取数时间(取数包里写着)。「截至现在还压着的存量」不许写成「昨天新增」。"
            "取数包里没有的必选指标写「待补数据」并单独列出来 —— 数字 0 和没取到是两回事,分开写。"
            "说原因时标明「这是判断」,不当成事实;建议动作只写建议,**全部标「尚未执行」**,不替店长定、不说已经做了。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:正文(Markdown,**固定六段、段名照抄**:「## 经营概况」「## 关键指标与口径」「## 异常与待处理事项」"
          "「## 建议动作(尚未执行)」「## 缺失数据与限制」「## 数据来源与执行证据」;最后一段写取数包来自哪个工具、取数时间、统计起止)、"
          "待确认项(列表:店长需要自己核一下的地方,缺的必选指标也放这里)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "store_report(kind=日)那一步的数据"}],
    输出={"格式": "json", "必含项": ["正文", "待确认项"], "未知值规则": "取数包里没有的写「待补数据」,不编;0 不当缺失"},
    变更说明="经营日报草稿模板默认的处理要求(11-22,用户拍六段结构)",
)

# 每周交付风险清单(11-22,用户拍方案 §3.5):**存量口径**(截至本次查询),不套「上周新增」;只整理原因和建议,不承诺交期、不派单
交付风险清单撰写 = dict(
    key="delivery_risk_list_write",
    用途="交付风险清单撰写:照「该催工厂」和「延期未告知」两份取数包,整理成店长看的每周交付风险清单草稿",
    标签=["每周交付风险清单"],
    system=("你是汉服定制门店的交付风险整理助手。**只用两份取数包里的单和数**,一单都不许编;每一单写清:订单号、顾问、生产方、承诺完工日 / 延到几号、为什么(取数包里的理由)。"
            "口径写明**「截至本次查询的风险存量」**,不写成「本周新增」。"
            "不写「预计某日完成」这类没有依据的承诺;不建议改交期、退款、通知客户;建议动作只有「催工厂」「告知顾客」「请店长核实」三类,**全部标「尚未执行」**,催不催、派不派由店长决定。"
            "两份取数包里重复出现的单只写一次,注明两头都有。"),
    user=("该催工厂(JSON):\n{{该催}}\n\n延期未告知(JSON):\n{{延期未告知}}\n\n"
          "按 JSON 输出:正文(Markdown,固定段:「## 结论」(几单该催、几单延期没告知、最紧的一单)「## 该催的单」「## 延期还没告诉顾客的单」"
          "「## 建议动作(尚未执行)」「## 缺失数据与限制」「## 数据来源与执行证据」(写两个工具名、截至日期、范围))、"
          "待确认项(列表:店长要核实的 —— 比如回传可疑、承诺完工日缺失的单)。"),
    变量=[{"名称": "该催", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "factory_chase 那一步的数据"},
        {"名称": "延期未告知", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "delay_pending 那一步的数据"}],
    输出={"格式": "json", "必含项": ["正文", "待确认项"], "未知值规则": "取数包里没有的写「取不到」,不编单号不编日期"},
    变更说明="每周交付风险清单模板默认的处理要求(11-22,用户拍第二个业务定时任务)",
)

风险建议 = dict(
    key="order_risk_advise",
    用途="订单风险建议:照规则判出的风险档和依据,写给店长的处理建议和要核实的问题",
    标签=["订单风险"],
    system=("你是汉服定制门店的交付风险助手。**风险档已经由规则判好了,你不改档、不重新判**。"
            "只用取数包里的事实:承诺完工日、离承诺完工日几天、该催的理由、订单时间线。"
            "不写「预计某日完成」这类没有依据的承诺;不建议改交期、退款、通知客户 —— 那些不在这个流程里。"
            "建议的动作只有一种:派一条「订单跟踪」任务,写清跟踪人要去核实什么。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:建议(给店长的一段话:为什么是这一档、建议跟踪人去做什么)、"
          "需要核实(列表:跟踪人要去问清的事)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "订单交付风险那一步的数据"}],
    输出={"格式": "json", "必含项": ["建议", "需要核实"], "未知值规则": "取数包里没有的写「不知道」,不编日期"},
    变更说明="订单风险模板默认的处理要求(10-25)",
)

# 召回话术:照澜绣「客户召回」技能的口径 —— 只引用这位客户自己的记录,不编;名单和由头由规则给,模型不增删人
召回话术 = dict(
    key="recall_script",
    用途="召回话术:给名单上的每个人写为什么是他、为什么是现在、开口说什么(只引用他自己的记录)",
    标签=["老客召回"],
    system=("你是汉服定制门店的客户召回助手。**名单和由头已经由规则定好了,你不增人、不删人、不改由头**。"
            "每个人只用取数包里他自己那一行的事实(由头、为什么是现在、流失严重程度)写;"
            "取数包里没有的事 —— 他喜欢什么、上次买了什么、家里有什么喜事 —— 一律不写,不编。"
            "流失预警里写的是「曾经是」的标签,不要说成「现在仍然是」。"
            "「在流失、等由头」那一段的人眼下没由头,不写话术,不建议打。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:逐人(列表,每项:客户号、为什么是他、为什么是现在、开口说什么)、"
          "摘要(给店长的一段话:这次列了几个、几个同时在流失、还有多少没列出、在流失等由头几个 —— 数字照取数包抄)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "召回名单那一步的数据"}],
    输出={"格式": "json", "必含项": ["逐人", "摘要"], "未知值规则": "取数包里没有的写「没查到」,不编"},
    变更说明="老客召回模板默认的处理要求(10-25)",
)

补货建议 = dict(
    key="restock_advise",
    用途="补货建议:照规则判出的库存档和库存明细,写给店长 / 总部的补货建议和要核实的问题",
    标签=["库存补货"],
    system=("你是汉服定制门店的库存助手。**档已经由规则判好了,你不改档**。只用取数包里的数:在手、占用、可用、卖过几件。"
            "补货量只给区间和依据,不给精确下单量 —— 下单量由店长或总部定。"
            "「发不出」是库存被未完成订单占住了:先建议核这些订单是不是真在做,不直接建议补货。"
            "没有销量数据就写「无法估算可售天数」,不编速度。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:建议(给店长的一段话:为什么是这一档、补不补、补多少的区间和依据)、需要核实(列表)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "补货预警那一步的数据"}],
    输出={"格式": "json", "必含项": ["建议", "需要核实"], "未知值规则": "取数包里没有的写「不知道」,不编数"},
    变更说明="库存补货模板默认的处理要求(10-25)",
)

差评研判要求 = dict(
    key="rating_review",
    用途="差评研判:照这一条差评的事实和判定表的判责建议,写「事实 / 判责依据 / 处置建议 / 待确认项」四段",
    标签=["差评返修"],
    system=("你是汉服定制门店的售后研判助手。**判责以取数包里判定表给的建议为准,你不改判、不自拟标准**;"
            "判定表没覆盖的,写「判定表没覆盖,交店长判」,不套最近的一行。"
            "事实只用这一单的服务记录和售后,同一客户别的单不进判责依据。事实互相矛盾的列出来,不替店长选边。"
            "涉及钱的(返修费用、退款)只写「需店长 / 总部定」,不给金额。"),
    user=("取数包(JSON):\n{{取数包}}\n\n"
          "按 JSON 输出:事实、判责依据(引判定表的那一行;没覆盖就照实说)、处置建议(返修 / 说明后关闭,给理由)、待确认项(列表)。"),
    变量=[{"名称": "取数包", "必填": True, "来源": "上一步结果", "类型": "object", "说明": "差评研判那一步的数据"}],
    输出={"格式": "json", "必含项": ["事实", "判责依据", "处置建议", "待确认项"], "未知值规则": "取数包里没有的写「没查到」,不编"},
    变更说明="差评返修模板默认的处理要求(10-25)",
)

处理要求们 = (处理要求, 报告撰写, 日报草稿撰写, 交付风险清单撰写, 风险建议, 召回话术, 补货建议, 差评研判要求)


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
