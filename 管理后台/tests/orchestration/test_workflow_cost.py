#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流运行记账:每个真跑的 AI 步骤一笔,按实际型号查价目表算钱(2026-11-03,用户拍「先补记账,按金额封顶」)。

## 为什么有这一份

访问 API 要「每天花费到上限就拒」,而原来工作流每次运行只记一行 `quantity=模型调用次数, amount=null,
source='mock'`(**真跑的也写 mock**)—— 金额是空的,上限无从谈起。

## 判据(真调 workers/worker._记这一段的账,数据库换成假的、只认它发出的两种语句)

  ① 真跑的 AI 步骤 → 每个 token 档一行,金额 = token × 价目表单价;事件键带这一步的执行键
  ② mock 步骤、不是 AI 的步骤、没有 usage 的 → 一行都不写(没花钱 / 不是一笔花销)
  ③ 连接协议认不出(价目表里没有这个供应商)→ token 照记、金额记成「算不出」,**不写 0**
  ④ 协议对照:anthropic-messages → anthropic(价目表按供应商登记)
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(_根, "workers"), os.path.join(_根, "services", "api", "app"),
                os.path.join(_根, "services", "api", "app", "jobs"),
                os.path.join(_根, "services", "api", "app", "contract")]
import worker as W  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


价目 = {"anthropic": {"claude-haiku-4-5-20251001": {"currency": "USD", "input_tokens": 0.000001,
                                                    "output_tokens": 0.000005}}}


class 假结果:
    def __init__(self, 行=None, 数=1):
        self._行, self.rowcount = 行, 数

    def mappings(self):
        return self

    def first(self):
        return self._行


class 假库:
    """只认 写进库 发的两种语句:查价目表 / 插一行账。别的语句一律炸 —— 记账不该顺手干别的。"""
    def __init__(self):
        self.账 = []

    def execute(self, 语句, 参=None):
        sql = str(语句)
        if "from pricing_versions" in sql:
            p = 价目.get(参["pv"], {}).get(参["m"])
            return 假结果({"unit_prices": p, "id": "pv_1"} if p else None)
        if "insert into usage_ledger" in sql:
            self.账.append(dict(参))
            return 假结果(数=1)
        raise AssertionError(f"记账发了一条意料之外的语句:{sql[:80]}")


job = {"organization_id": "org", "project_id": "p"}
r = {"trace_id": "tr_1"}


def 步(键, kind="llm", 模式="live", usage=None, 型号="claude-haiku-4-5-20251001", 供应商="anthropic"):
    出 = {"execution_mode": 模式, "actual_model": 型号, "提供方": 供应商}
    if usage is not None:
        出["usage"] = usage
    return {"execution_key": 键, "kind": kind, "output": 出}


def main():
    print("▸ ④ 协议对照")
    ck("anthropic-messages → anthropic", W.连接协议到供应商.get("anthropic-messages") == "anthropic",
       W.连接协议到供应商)

    print("\n▸ ① 真跑的 AI 步骤按价目表算钱")
    库 = 假库()
    n = W._记这一段的账(库, job, r, "xr_1", [步("xr_1:3:/:1", usage={"input_tokens": 1000, "output_tokens": 200})], "U1")
    行 = {x["ek"]: x for x in 库.账}
    ck("记了 1 步、两档各一行(输入 / 输出单价差五倍,不合成一个数)",
       n == 1 and set(行) == {"xr_1:3:/:1:input_tokens", "xr_1:3:/:1:output_tokens"}, 行)
    ck("金额 = token × 单价(输入 1000×0.000001、输出 200×0.000005)",
       abs(行.get("xr_1:3:/:1:input_tokens", {}).get("amt", -1) - 0.001) < 1e-9
       and abs(行.get("xr_1:3:/:1:output_tokens", {}).get("amt", -1) - 0.001) < 1e-9
       and all(x["ak"] and x["src"] == "live" and x["prov"] == "anthropic" for x in 库.账), 库.账)
    ck("调用方记成「工作流运行」、带这次运行的 trace", all(x["call"] == "工作流运行" and x["t"] == "tr_1" for x in 库.账), 库.账)

    print("\n▸ ② 不该记的一行都不写")
    库 = 假库()
    n = W._记这一段的账(库, job, r, "xr_2", [
        步("a", 模式="mock", usage={"input_tokens": 5}),
        步("b", kind="tool", usage={"input_tokens": 5}),
        步("c", usage=None),
        步("d", usage={"input_tokens": 0, "output_tokens": 0}),
    ], "U1")
    ck("mock / 工具步骤 / 没有 usage / token 全是 0 → 0 步、0 行", n == 0 and not 库.账, 库.账)

    print("\n▸ ③ 认不出的供应商:token 照记,金额算不出")
    库 = 假库()
    n = W._记这一段的账(库, job, r, "xr_3", [步("e", usage={"input_tokens": 10}, 供应商=None)], "U1")
    ck("记了一行、amount=None、amount_known=False(**不是 0**)",
       n == 1 and len(库.账) == 1 and 库.账[0]["amt"] is None and 库.账[0]["ak"] is False
       and 库.账[0]["q"] == 10, 库.账)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ {len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
