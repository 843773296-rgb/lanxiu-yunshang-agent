#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编辑器「上次运行」页签(11-15,工作流一期第三件;照 Dify)。

## 判据(真调 runtime/上次运行.py,不在夹具里重写一份)
  ① 手机号只露后四位:11 位连写、带空格 / 连字符的写法都打;订单号里夹着的 11 位数字不打;嵌套的 dict / list 也打;报打了几处
  ② 没跑过 → 「有记录=否」并说清怎么让它有
  ③ 有「查看敏感输入」授权 → 给原文,但手机号已打码;没授权 → 只给形状,形状里不出现原值
  ④ 按默认值继续那一步 → 标出来,错误细节里顶上的值同样打码
  ⑤ 来源说得出是整条试运行还是单独测这一步;耗时按起止算
  ⑥ 接线:接口真调 上次运行.整理、权限和运行详情同一档、契约登记了、编辑器面板真去请求这个接口
"""
import datetime as dt
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import 上次运行 as LR  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


print("▸ ① 手机号只露后四位")
例 = [("顾客 13912345678 要改尺寸", "顾客 *******5678 要改尺寸", 1),
      ("电话 139 1234 5678", "电话 *******5678", 1),
      ("电话 139-1234-5678。", "电话 *******5678。", 1),
      ("订单号 A13912345678X", "订单号 A13912345678X", 0),
      ("金额 13912345678.5", "金额 13912345678.5", 0),
      ("两个号 13800001111、15900002222", "两个号 *******1111、*******2222", 2)]
for 原, 应, 几 in 例:
    出, n = LR.打码(原)
    ck(f"「{原}」→「{应}」", 出 == 应 and n == 几, 1, (出, n))
嵌, n = LR.打码({"客户": {"手机": "13912345678", "备注": ["回电 15900002222"]}, "件数": 3})
ck("嵌套 dict / list 也打,数字原样", 嵌 == {"客户": {"手机": "*******5678", "备注": ["回电 *******2222"]}, "件数": 3} and n == 2, 1, (嵌, n))

print("▸ ② 没跑过")
x = LR.整理(None, None, 看原文=True, 形状=lambda v: "形状", 解析=json.loads)
ck("有记录=否,并说清怎么让它有", x["有记录"] is False and "试运行" in x["说法"], 1, x)

起 = dt.datetime(2026, 11, 15, 22, 0, 0)
步 = {"status": "succeeded", "attempt": 2, "error_code": None, "error_detail": None,
      "input_ref": json.dumps({"手机": "13912345678", "问": "改袖长"}, ensure_ascii=False),
      "output_ref": json.dumps({"text": "已记下,回电 13912345678"}, ensure_ascii=False),
      "started_at": 起, "ended_at": 起 + dt.timedelta(milliseconds=1500)}
运行 = {"id": "run_1", "definition_ref": {"kind": "step_test", "id": "wf", "node_id": "llm"}}
形状 = lambda v: {"__形状__": True, "长度": len(str(v))}

print("▸ ③ 有授权给原文但打码;没授权只给形状")
x = LR.整理(步, 运行, 看原文=True, 形状=形状, 解析=json.loads)
文 = json.dumps(x, ensure_ascii=False, default=str)
ck("有授权:输入里的手机号是 *******5678", x["输入"]["手机"] == "*******5678" and x["输入"]["问"] == "改袖长", 1, x["输入"])
ck("有授权:整包里一个完整号码都没有,报打了 2 处", "13912345678" not in 文 and x["打码了几处手机号"] == 2, 1, 文)
y = LR.整理(步, 运行, 看原文=False, 形状=形状, 解析=json.loads)
文y = json.dumps(y, ensure_ascii=False, default=str)
ck("没授权:输入输出都是形状,原值不出现", y["输入"].get("__形状__") and "改袖长" not in 文y and "13912345678" not in 文y, 1, 文y)
ck("没授权:说清要什么授权", "查看敏感输入" in y.get("说明", ""), 1, y)

print("▸ ④ 按默认值继续那一步")
默步 = {**步, "status": "failed", "error_code": "RATE_LIMIT",
        "error_detail": {"消息": "限流", "处理": "按默认值继续", "默认值": {"text": "请回电 13912345678"}}}
z = LR.整理(默步, 运行, 看原文=True, 形状=形状, 解析=lambda v: v if isinstance(v, dict) else json.loads(v))
ck("标出按默认值继续", z["按默认值继续"] is True and z["状态"] == "failed", 1, z)
ck("顶上的值同样打码", z["错误细节"]["默认值"]["text"] == "请回电 *******5678", 1, z["错误细节"])

print("▸ ⑤ 来源与耗时")
ck("单独测这一步、用时 1500 毫秒、第 2 次", x["来源"] == "单独测这一步" and x["耗时毫秒"] == 1500 and x["尝试"] == 2, 1, x)
w = LR.整理(步, {"id": "r2", "definition_ref": {"kind": "graph_draft"}}, 看原文=True, 形状=形状, 解析=json.loads)
ck("整条试运行", w["来源"] == "整条试运行", 1, w["来源"])

print("▸ ⑥ 接线")
源 = open(os.path.join(根, "services", "api", "app", "workflows_api.py"), encoding="utf-8").read()
i = 源.index('"/workflows/{wid}/nodes/{nid}/last-run"')
段 = 源[i:源.index("\ndef _解析json", i)]
ck("接口真调 上次运行.整理、权限是「查看有权配置」、原文按「查看敏感输入」给",
   "LR.整理(" in 段 and '要权限("查看有权配置")' in 段 and 'me.能("查看敏感输入/独立测试答案")' in 段, 1)
ck("只认这条流程、跳过的不算", "definition_ref->>'id'=:w" in 段 and "'skipped'" in 段, 1)
约 = open(os.path.join(根, "services", "api", "app", "contract", "endpoints.py"), encoding="utf-8").read()
ck("契约登记了这条接口", '"/workflows/{id}/nodes/{nid}/last-run"' in 约, 1)
前 = open(os.path.join(根, "apps", "web", "app.js"), encoding="utf-8").read()
ck("编辑器面板打开时真去请求它(填上次运行 被面板调用)",
   "/last-run`" in 前 and "填上次运行(n);" in 前 and "async function 填上次运行" in 前, 1)

print()
if 挂:
    print(f"❌ {len(挂)} 条没过:{挂}")
    sys.exit(1)
print(f"✅ {len(过)} 条全过")
