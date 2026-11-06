#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent 写工具当场审批(2026-11-06;用户拍:每次写都当场审批、店长批、24 小时作废、只能批或退回)。不要数据库、不发请求。

真跑 agent_loop.跑一个agent + tool_gateway;判据落在**独立记录**上(写工具真被执行几次、模型真被问几次)。

  ① 调用方说这个写工具走审批 → 过网关之前就挂起 waiting_approval,载荷 = 这一次的工具 / 参数 / 参数摘要;工具一次没执行
  ② 批了 → 带着绑定这一次参数摘要的批准过网关 → 交给桥再挂起(载荷带批准人)→ 回执 → 交卷;写工具只执行一次
  ③ 退回 → 模型收到 HUMAN_REJECTED + 理由,工具没执行;模型原样再申请 → 按「同一个被拒的动作」停(no_progress)
  ④ 批准绑定这一次:模型换了参数(另一个客户)→ 要重新批(又挂起),不拿上一次的批准放行
  ⑤ 调用方不给 要人批 → 照旧:按网关的规矩走(这个写入级工具不要求确认,直接执行),不挂起
  ⑥ 「批准」里没有处理人 → 当退回处理(不认匿名批准)
  ⑦ 副作用级别别名:登记成 reversible 的写工具按写入级认;真认不出的照旧挡
  ⑧ 桥闸只认库里查到的、参数摘要一模一样、有处理人的批准
"""
import json
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
for p in (("services", "api", "app", "runtime"), ("services", "api", "app", "contract"), ("services", "api", "app")):
    sys.path.insert(0, os.path.join(根, *p))
import agent_loop as A  # noqa: E402
import dsl as DS  # noqa: E402
import tool_gateway as G  # noqa: E402
import 桥闸 as BG  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


派 = {"name": "派回访任务", "model_description": "派一条回访", "adapter": "桥", "side_effect_type": DS.写入,
     "input_schema": {"type": "object", "properties": {"客户": {"type": "string"}}, "required": ["客户"]},
     "confirmation_policy": {"谁批": "店长"}, "idempotency_strategy": {"键": "logical_action_id"},
     "external_status_lookup": {"supported": True}}
目录 = {"派回访任务": 派}
配置 = {"instructions": "按工具查到的做", "task_template": "给 C1 派回访", "tools": ["派回访任务"],
        "limits": {"max_model_turns": 6, "max_tool_attempts": 6},
        "output_schema": {"type": "object", "properties": {"结果": {"type": "string"}}, "required": ["结果"]}}
交卷 = {"finish": {"结果": "派好了"}}


class 脚本模型:
    def __init__(self, 回答们):
        self.回答们, self.被调, self.看到 = list(回答们), 0, []

    def __call__(self, 消息们, 工具定义们):
        self.被调 += 1
        self.看到.append(json.loads(json.dumps(消息们, ensure_ascii=False, default=str)))
        if not self.回答们:
            raise AssertionError("脚本用完了")
        return dict(self.回答们.pop(0), usage={"input_tokens": 1, "output_tokens": 1})


class 桥:
    def __init__(self, 当场=False):
        self.交过, self.当场 = [], 当场

    def __call__(self, 参):
        self.交过.append(参)
        if self.当场:
            return {"任务": "tk1"}
        raise G.要等({"工具": "派回访任务", "参数": 参})


def 调(i, 客):
    return {"tool_calls": [{"id": i, "name": "派回访任务", "arguments": {"客户": 客}}]}


def 跑(m, *, 恢复=None, 账本=None, b=None, 要人批=lambda 调, 摘, 契: True):
    事件 = []
    b = b or 桥()
    r = A.跑一个agent(配置, {}, 适配器={"model": m, "桥": b}, 工具目录=目录, 有效范围={"paths": [], "hosts": [], "ids": []},
                    账本=账本, 记事=lambda k, v: 事件.append((k, v)), run_id="ap1", 恢复=恢复, 要人批=要人批)
    return r, 事件, b


def 存(r):
    return json.loads(json.dumps(r["检查点"], ensure_ascii=False, default=str))


def main():
    # ① + ②
    账 = G.内存账本()
    m = 脚本模型([调("c1", "C1"), 交卷])
    r1, ev1, b1 = 跑(m, 账本=账)
    载 = (r1.get("等待") or {}).get("载荷") or {}
    ck("① 走审批的写工具 → 过网关之前就挂起 waiting_approval(种类 human),载荷是这一次的工具 / 参数 / 参数摘要;工具一次没执行",
       r1["execution_status"] == "waiting_approval" and r1["等待"]["种类"] == "human" and 载.get("工具") == "派回访任务"
       and 载.get("参数") == {"客户": "C1"} and 载.get("参数摘要") and b1.交过 == [], (r1["execution_status"], r1.get("等待"), b1.交过))
    r2, ev2, b2 = 跑(m, 账本=账, 恢复={"检查点": 存(r1), "结果": {"决定": "approve", "处理人": "U_店长", "理由": ""}})
    ck("② 批了 → 带着批准过网关、交给桥 → 挂起等回执(载荷带批准人、参数摘要)", r2["execution_status"] == "waiting_external"
       and r2["等待"]["载荷"].get("批准人") == "U_店长" and r2["等待"]["载荷"].get("参数摘要") == 载["参数摘要"] and len(b2.交过) == 1,
       (r2["execution_status"], r2.get("等待"), b2.交过))
    r3, _, b3 = 跑(m, 账本=账, 恢复={"检查点": 存(r2), "结果": {"任务": "tk9"}})
    ck("② 回执 → 交卷 succeeded;写工具总共只执行一次、模型只被问了两次",
       r3["execution_status"] == "succeeded" and len(b1.交过) + len(b2.交过) + len(b3.交过) == 1 and m.被调 == 2,
       (r3["execution_status"], m.被调))

    # ③
    m = 脚本模型([调("c1", "C1"), 调("c2", "C1"), 交卷])
    r1, _, _ = 跑(m)
    r2, ev, b = 跑(m, 恢复={"检查点": 存(r1), "结果": {"决定": "reject", "处理人": "U_店长", "理由": "这位客户上周刚回访过"}})
    回 = m.看到[1][-1]["content"][0] if len(m.看到) > 1 else {}
    ck("③ 退回 → 模型收到 HUMAN_REJECTED 和理由,工具没执行",
       (回.get("rejected") or {}).get("code") == "HUMAN_REJECTED" and "上周刚回访过" in (回.get("rejected") or {}).get("reason", "")
       and b.交过 == [], 回)
    ck("③ 模型原样再申请同一个动作 → 按「同一个被拒的动作」停(no_progress),不再挂起等批",
       r2["execution_status"] == "incomplete" and r2["completion_reason"] == "no_progress", (r2["execution_status"], r2["completion_reason"]))

    # ④
    m = 脚本模型([调("c1", "C1"), 调("c2", "C2"), 交卷])
    r1, _, _ = 跑(m, b=桥(当场=True))
    r2, _, b = 跑(m, b=桥(当场=True), 恢复={"检查点": 存(r1), "结果": {"决定": "approve", "处理人": "U_店长"}})
    ck("④ 批准绑定这一次:模型换成另一个客户 → 又挂起等批(不拿上一次的批准放行)",
       r2["execution_status"] == "waiting_approval" and r2["等待"]["载荷"].get("参数") == {"客户": "C2"}
       and r2["等待"]["载荷"]["参数摘要"] != r1["等待"]["载荷"]["参数摘要"], (r2["execution_status"], r2.get("等待")))

    # ⑤
    m = 脚本模型([调("c1", "C1"), 交卷])
    r, _, b = 跑(m, 要人批=None, b=桥(当场=True))
    ck("⑤ 不走审批的调用方 → 照旧按网关的规矩走(写入级不要求确认 → 直接执行),不挂起等批",
       r["execution_status"] == "succeeded" and len(b.交过) == 1, (r["execution_status"], b.交过))

    # ⑥
    m = 脚本模型([调("c1", "C1"), 交卷])
    r1, _, _ = 跑(m)
    r2, _, b = 跑(m, 恢复={"检查点": 存(r1), "结果": {"决定": "approve", "处理人": ""}})
    回 = m.看到[1][-1]["content"][0] if len(m.看到) > 1 else {}
    ck("⑥ 「批准」里没有处理人 → 当退回(不认匿名批准),工具没执行",
       (回.get("rejected") or {}).get("code") == "HUMAN_REJECTED" and b.交过 == [], 回)
    # ⑦ 副作用级别别名:澜绣那 4 个写工具登记成 reversible(种子脚本写的)—— 网关要按写入级认,别的认不出的照旧挡
    m = 脚本模型([调("c1", "C1"), 交卷])
    目录["派回访任务"] = dict(派, side_effect_type="reversible")
    try:
        r1, _, _ = 跑(m, 账本=G.内存账本())
        r2, ev, b = 跑(m, 账本=G.内存账本(), b=桥(当场=True), 恢复={"检查点": 存(r1), "结果": {"决定": "approve", "处理人": "U_店长"}})
    finally:
        目录["派回访任务"] = 派
    ck("⑦ 登记成 reversible 的写工具:批了之后网关按写入级放行、真执行一次(原来「认不出的级别」一律挡)",
       r2["execution_status"] == "succeeded" and len(b.交过) == 1, (r2["execution_status"], [v for k, v in ev if k == "tool.rejected"]))
    m = 脚本模型([调("c1", "C1"), 交卷])
    目录["派回访任务"] = dict(派, side_effect_type="乱写的级别")
    try:
        r, ev, b = 跑(m, 要人批=None, b=桥(当场=True))
    finally:
        目录["派回访任务"] = 派
    ck("⑦ 真认不出的级别照旧一律挡(未知不等于安全)", b.交过 == [] and any(k == "tool.rejected" for k, _ in ev), b.交过)

    # ⑧ 桥闸只认库里查到的、参数摘要一模一样、有处理人的批准
    批 = [{"参数摘要": "sha256:甲", "处理人": "U006"}]
    ck("⑧ 桥闸认 Agent 批准:参数摘要一样 + 有处理人 → 放行;摘要不一样(批 A 执行 B)/ 没处理人 / 没批准 → 不放行",
       BG.Agent批准成立吗(批, "sha256:甲") and not BG.Agent批准成立吗(批, "sha256:乙")
       and not BG.Agent批准成立吗([{"参数摘要": "sha256:甲", "处理人": ""}], "sha256:甲") and not BG.Agent批准成立吗([], "sha256:甲")
       and BG.放行吗("派补货跟进", {}, {}, Agent批准=批, 参数摘要="sha256:甲")[0]
       and not BG.放行吗("派补货跟进", {}, {}, Agent批准=批, 参数摘要="sha256:乙")[0])

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ Agent 写工具当场审批:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
