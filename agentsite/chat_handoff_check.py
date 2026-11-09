#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天转人工的短路(11-09)。走真入口 sdk.run,不是只验纯函数 —— 假的只有管理后台和模型那两头。

  ① 开关关着:判不出也不转人工,不建待办
  ② 开关开着 + 判不出 → 不进模型循环、建一条待办、回答里有编号、轨迹一条 handoff.human
  ③ 分类调用失败同样转;④ 路由规则点名转人工(意图判出)同样转
  ⑤ 判出且规则没点名 → 不转
  ⑥ 建待办失败 → 不短路,照常进模型循环,返回里记下失败
  ⑦ 没有登录身份 / 机器调用(只读)→ 不转
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "backend"), os.path.join(os.path.dirname(HERE), "agent")]
import sdk  # noqa: E402
import glossary_client as G  # noqa: E402
import answer_feedback as AF  # noqa: E402
import assistant_client as AC  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


class 进了模型循环(Exception):
    pass


店长 = {"no": "E001", "name": "测试店长", "role": "店长", "shop": "测试店"}
规则 = {"规则": [{"名称": "投诉转人工", "条件": {"种类": "意图", "值": "投诉"}, "去向": "转人工", "说明": "投诉"}]}
建了 = []
建待办结果 = [("ho_1", None)]


def 跑(开, 意图结果, me=店长, 只读=False, 路由=None):
    """真调 sdk.run。过了短路点之后第一件事抛 进了模型循环,证明没短路(不发任何模型请求)。"""
    建了.clear()
    if 开:
        os.environ["LANXIU_CHAT_HANDOFF"] = "1"
    else:
        os.environ.pop("LANXIU_CHAT_HANDOFF", None)
    sdk._术语状态 = lambda 角色: {"术语": [], "实体识别": None, "路由": {"配置": 路由}, "意图": {"配置": {"意图": [{"名称": "投诉"}]}}}
    AC.生产版 = lambda 角色: {"版": None}
    G.判意图 = lambda 文本, 配置: 意图结果
    G.名单 = lambda: {}

    def 假建(*a, **k):
        建了.append(a)
        return 建待办结果[0]
    AF.建转人工 = 假建

    def 拦(*a, **k):
        raise 进了模型循环()
    sdk.mcp_config = 拦          # 短路点之后才用得到它
    try:
        return asyncio.run(sdk.run("task", "这单我要投诉", me=me, 后台配置=True, 只读=只读)), False
    except 进了模型循环:
        return None, True


def main():
    判不出 = {"意图": None, "态": "判不出", "原因": "哪个都不像"}
    失败 = {"意图": None, "态": "调用失败", "原因": "超时"}
    投诉 = {"意图": "投诉", "态": "判出", "原因": "把握:高"}
    print("① 开关关着")
    r, 进 = 跑(False, 判不出)
    ck("判不出也进模型循环,不建待办", 进 and not 建了, (r, 建了))
    print("② 判不出")
    r, 进 = 跑(True, 判不出)
    ck("不进模型循环", not 进 and r is not None, 进)
    if r:
        ck("回答里有待办编号", "ho_1" in r["text"], r["text"])
        ck("轨迹正好一条 handoff.human", [x["tool"] for x in r["trajectory"]] == ["handoff.human"], r["trajectory"])
        ck("建了一条待办,记的是登录店长和原话", len(建了) == 1 and 建了[0][0] is 店长 and 建了[0][1] == "这单我要投诉", 建了)
        ck("返回里有转人工和意图", r["转人工"]["待办编号"] == "ho_1" and r["意图"] is 判不出, r)
    print("③ 调用失败")
    r, 进 = 跑(True, 失败)
    ck("调用失败也转,原因写明", not 进 and r and "调用失败" in r["转人工"]["原因"], r)
    print("④ 路由规则点名")
    r, 进 = 跑(True, 投诉, 路由=规则)
    ck("意图判出 + 规则转人工 → 转", not 进 and r and "投诉" in r["转人工"]["原因"], (进, r))
    print("⑤ 判出但规则没点名")
    r, 进 = 跑(True, 投诉)
    ck("不转,进模型循环", 进 and not 建了, (r, 建了))
    print("⑥ 建待办失败")
    建待办结果[0] = (None, "后台连不上")
    r, 进 = 跑(True, 判不出)
    ck("不短路,照常进模型循环", 进 and len(建了) == 1, (r, 建了))
    建待办结果[0] = ("ho_1", None)
    print("⑦ 没人等答复的路")
    r, 进 = 跑(True, 判不出, me=None)
    ck("没有登录身份 → 不转", 进 and not 建了, (r, 建了))
    r, 进 = 跑(True, 判不出, 只读=True)
    ck("机器调用 → 不转", 进 and not 建了, (r, 建了))
    print(f"\n样本 {len(过) + len(挂)} 条:{len(过)} 过 / {len(挂)} 挂")
    return 1 if 挂 or len(过) + len(挂) < 10 else 0


if __name__ == "__main__":
    sys.exit(main())
