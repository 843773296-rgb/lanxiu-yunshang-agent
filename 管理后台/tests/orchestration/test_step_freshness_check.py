#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试结果还算不算数(DF-01,2026-11-05;方案 §5.2 第 2 / 6 条,验收 C02)。不要数据库。

真调 runtime/单步测试.py::结果还算数吗 / 对着的草稿哈希,哈希真调 contract/dsl.py::逻辑哈希
(和受理时、冻结时算的是同一个函数 —— 夹具里不重算一份)。

  ① 单步测试对着的草稿 = 现在的草稿 → 算数
  ② 只挪位置(布局不在定义里)、改节点显示名 → 哈希不变 → 仍算数
  ③ 改了流程(结束多交一项)→ 不算数,说法里写「改过了」
  ④ 单步测试没记草稿哈希(11-05 之前的)→ 不算数,而且说清是「没记」,不是「改过了」
  ⑤ 整条试运行用它自己的 definition_hash 比;别的来源(聊天、对外 API 没有 kind)→ 说不清 → 不算数
  ⑥ 现在的哈希算不出 → 不算数(不当成「一样」)
  ⑦ 发布闸(用户 11-05 拍:生产强制,测试 / 预发不管):没跑通 → 生产拦、预发不拦;没判(None)→ 不拦
  ⑨ 依赖指纹(DF-01 欠债):那次跑通时的连接设置和现在不是同一份(探测原地改了 capabilities)→ 不算;没记指纹 → 不算
  ⑩ 用到的模型连接事后被停用 / 归档(父行 status,不在哈希和指纹里)→ 生产拦
  ⑧ 「用模型连接的步骤」= 节点表里配置带 connection_version_id 的那几类(受理定 mock/live 和闸都用它;新加一类模型步骤忘了登记 → 红)
"""
import copy
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "contract"))
import dsl as DS  # noqa: E402
import 单步测试 as ST1  # noqa: E402
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import release as RL  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


草稿 = {"definition_schema_version": "1", "kind": "workflow",
        "input_schema": {"type": "object", "properties": {"article": {"type": "string"}}, "required": ["article"]},
        "output_schema": {"type": "object", "properties": {}, "required": []},
        "nodes": [{"id": "start", "type": "start", "name": "开始"},
                  {"id": "m", "type": "llm", "name": "写摘要", "config": {"bindings": {"原文": {"source": "input", "pointer": "/article"}}}},
                  {"id": "finish", "type": "end", "name": "结束", "config": {"output_schema": {"type": "object", "properties": {}}}}],
        "edges": [{"source": "start", "target": "m", "port": "success"}, {"source": "m", "target": "finish", "port": "success"}]}


def main():
    H = DS.逻辑哈希(草稿)
    单测 = {"kind": "step_test", "id": "wf_x", "node_id": "m", "草稿哈希": H}
    ok, 说 = ST1.结果还算数吗(单测, "sha256:小图自己的哈希", H)
    ck("① 单步测试对着的就是现在的草稿 → 算数(用记下的草稿哈希,不用小图自己的哈希)", ok is True, 说)

    改名 = copy.deepcopy(草稿)
    改名["nodes"][1]["name"] = "写一段摘要"
    ok, 说 = ST1.结果还算数吗(单测, None, DS.逻辑哈希(改名))
    ck("② 只改显示名 → 哈希不变 → 仍算数(挪一下、改个名就全判过期,人就不再信这个标记)", ok is True, 说)

    改流程 = copy.deepcopy(草稿)
    改流程["nodes"][2]["config"]["output_schema"]["properties"]["回显"] = {"type": "string"}
    ok, 说 = ST1.结果还算数吗(单测, None, DS.逻辑哈希(改流程))
    ck("③ 改了流程 → 不算数,说法写「改过了」", ok is False and "改过" in 说, 说)

    ok, 说 = ST1.结果还算数吗({"kind": "step_test", "id": "wf_x", "node_id": "m"}, H, H)
    ck("④ 老单步测试没记草稿哈希 → 不算数,说法是「没记下」(即使它自己的哈希碰巧一样也不拿来顶)",
       ok is False and "没记下" in 说, 说)

    ok, _ = ST1.结果还算数吗({"kind": "graph_draft", "id": "wf_x"}, H, H)
    ok2, _ = ST1.结果还算数吗({"kind": "graph_draft", "id": "wf_x"}, H, DS.逻辑哈希(改流程))
    ck("⑤ 整条试运行用它自己的 definition_hash 比:一样算数、不一样不算", ok is True and ok2 is False, (ok, ok2))
    ok, 说 = ST1.结果还算数吗({"kind": "chat"}, H, H)
    ck("⑤ 认不出来源的 → 说不清 → 不算数", ok is False and ST1.对着的草稿哈希({"kind": "chat"}, H) is None, 说)
    ok, 说 = ST1.结果还算数吗(None, H, H)
    ck("⑤ 来源是空的 → 不算数", ok is False, 说)

    ok, 说 = ST1.结果还算数吗(单测, None, None)
    ck("⑥ 现在的哈希算不出 → 不算数(None == None 不算「一样」)", ok is False and "算不出" in 说, 说)
    ok, 说 = ST1.结果还算数吗({"kind": "step_test", "草稿哈希": None}, None, None)
    ck("⑥ 两边都是 None → 不算数", ok is False, 说)

    审过 = {"审核人": "U001", "审的哈希": "h", "结论": "通过"}
    清单 = {"content_hash": "h"}
    问 = RL.可以发布吗(环境="production", 清单=清单, 审核=审过, 跑通过吗=False)
    ck("⑦ 审过了、但这一版没跑通过 → 生产拦,说清怎么办", len(问) == 1 and "跑通过" in 问[0] and "试运行" in 问[0], 问)
    ck("⑦ 同样没跑通 → 预发 / 测试不拦(那正是边改边试的地方)",
       RL.可以发布吗(环境="staging", 清单=清单, 审核=None, 跑通过吗=False) == []
       and RL.可以发布吗(环境="test", 清单=清单, 审核=None, 跑通过吗=False) == [])
    ck("⑦ 跑通过 → 生产放行;不是工作流的清单(None)→ 不判这一条",
       RL.可以发布吗(环境="production", 清单=清单, 审核=审过, 跑通过吗=True) == []
       and RL.可以发布吗(环境="production", 清单=清单, 审核=审过, 跑通过吗=None) == [])

    ck("⑦ 有模型步骤:只有演示模型跑通 → 不够;有一次真模型跑通 → 够(用户 11-05 改口)",
       RL.跑通够不够(["mock"], True) is False and RL.跑通够不够(["live"], True) is True
       and RL.跑通够不够(["live", "mock"], True) is True and RL.跑通够不够([], True) is False)
    ck("⑦ 一步模型都没有:演示模式跑通就够(不然永远发不了生产);没跑通照样不够",
       RL.跑通够不够(["mock"], False) is True and RL.跑通够不够([], False) is False)
    ck("⑨ 连接设置没变 → 依赖没变;这一版不用连接 → 没什么可变的",
       RL.依赖没变吗({"cv1": "a"}, {"cv1": "a"}, ["cv1"]) is True and RL.依赖没变吗(None, {}, []) is True)
    ck("⑨ 探测把那个连接的设置改了(指纹变了)→ 那次跑通不算",
       RL.依赖没变吗({"cv1": "a", "cv2": "b"}, {"cv1": "a", "cv2": "改过"}, ["cv1", "cv2"]) is False)
    ck("⑨ 那次没记指纹(11-05 之前受理的)/ 现在查不到那个连接 → 说不清,不算",
       RL.依赖没变吗(None, {"cv1": "a"}, ["cv1"]) is False and RL.依赖没变吗({"cv1": "a"}, {}, ["cv1"]) is False
       and RL.依赖没变吗({"cv1": None}, {"cv1": None}, ["cv1"]) is False)
    问 = RL.可以发布吗(环境="production", 清单=清单, 审核=审过, 跑通过吗=True, 停用的连接=["演示连接"])
    ck("⑩ 跑通过了、但用到的模型连接事后被停用 → 生产拦,点名是哪条连接",
       len(问) == 1 and "停用" in 问[0] and "演示连接" in 问[0], 问)
    ck("⑩ 同样的情况发预发 → 不拦;没有停用的 → 不拦",
       RL.可以发布吗(环境="staging", 清单=清单, 审核=None, 停用的连接=["演示连接"]) == []
       and RL.可以发布吗(环境="production", 清单=清单, 审核=审过, 跑通过吗=True, 停用的连接=[]) == [])
    import workflows_api as WA
    带连接 = sorted(n["名"] for n in DS.节点表 if "connection_version_id" in (n.get("配置") or []))
    ck("⑧ 「用模型连接的步骤」和节点表一致(至少 3 类:模型 / 问题分类器 / 参数提取器)",
       sorted(WA.用模型连接的步骤) == 带连接 and len(带连接) >= 3, (WA.用模型连接的步骤, 带连接))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 测试结果还算不算数:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
