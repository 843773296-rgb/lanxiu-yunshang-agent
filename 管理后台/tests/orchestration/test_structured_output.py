#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""要模型交 JSON 的那几步:解析不了重问一次、用量相加、还不行带着两次原文失败(用户 2026-11-02 拍「三步都做」)。

## 判据(真调 runtime/结构化输出.py,模型回答由这里假造)

  ① 第一次就是合法 JSON → 不重问(重问函数一次都没被调),用量就是第一次的
  ② 第一次不合法、第二次合法 → 用第二次的结果;**用量是两次之和**(重问花的钱不许从账上消失)
  ③ 两次都不合法 → 节点失败 OUTPUT_NOT_JSON,**`.出` 里两次原文都在**、用量也是两次之和
  ④ runner 失败那一支把 `.出` 落进这一步的输出:真跑一张「开始 → AI → 结束」的小图,AI 步骤抛带 `.出` 的失败,
     看这一步的记录里 output 是不是那份原文(原来失败时原文不落库,而建议写着「看这一步的原文」)
  ⑤ 引号:回答里字符串值带了没转义的英文双引号 → 解析不了(这就是 11-02 推断的那个病根的形状;
     🔮 失败那两次原文当时没存,所以「它就是病根」仍是推断)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import runner as RN  # noqa: E402
import 结构化输出 as 结  # noqa: E402

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{'  ' + str(补)[:300] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 答(文, 入=10, 出=5):
    return {"text": 文, "usage": {"input_tokens": 入, "output_tokens": 出}, "finish_reason": "end_turn",
            "actual_model": "假模型"}


def main():
    print("▸ ① 第一次就合法:不重问")
    次数 = []
    解, 出, 用, 重 = 结.要JSON(答('```json\n{"类别": "明确需求"}\n```'), lambda: 次数.append(1) or 答("{}"))
    ck("解析出类别、没重问、用量是第一次的", 解 == {"类别": "明确需求"} and not 重 and not 次数
       and 用 == {"input_tokens": 10, "output_tokens": 5}, (解, 重, 次数, 用))

    print("\n▸ ② 第一次不合法、第二次合法:用第二次,用量相加")
    解, 出, 用, 重 = 结.要JSON(答("好的,这是结果:类别是明确需求", 10, 5), lambda: 答('{"类别": "考虑中"}', 12, 7))
    ck("用第二次的结果", 解 == {"类别": "考虑中"} and 重 and 出["text"] == '{"类别": "考虑中"}', (解, 重))
    ck("用量是两次之和(重问花的钱在账上)", 用 == {"input_tokens": 22, "output_tokens": 12}, 用)

    print("\n▸ ③ 两次都不合法:失败,两次原文都挂在 .出 上")
    try:
        结.要JSON(答("第一次胡说", 3, 1), lambda: 答("第二次也胡说", 4, 2))
        ck("两次都不合法 → 抛节点失败", False, "没抛")
    except RN.节点失败 as e:
        ck("码是 OUTPUT_NOT_JSON", e.code == "OUTPUT_NOT_JSON", e.code)
        ck("两次原文都在、用量相加", (e.出 or {}).get("第一次原文") == "第一次胡说"
           and e.出.get("第二次原文") == "第二次也胡说" and e.出.get("usage") == {"input_tokens": 7, "output_tokens": 3},
           e.出)

    print("\n▸ ④ runner 失败那一支把 .出 落进这一步的输出")
    文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    定义 = {"nodes": [{"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {}}}},
                      {"id": "a", "type": "llm", "config": {"connection_version_id": "cv1", "prompt_version_id": "p1",
                                                           "output_schema": 文, "bindings": {}}},
                      {"id": "e", "type": "end", "config": {"output_schema": 文, "bindings": {
                          "text": {"source": "constant", "value": "完"}}}}],
            "edges": [{"source": "start", "target": "a", "port": "success"},
                      {"source": "a", "target": "e", "port": "success"}]}

    def 坏llm(cfg, 实参):
        x = RN.节点失败("OUTPUT_NOT_JSON", "模型没按要求输出 JSON 对象", "看原文")
        x.出 = {"第一次原文": "甲", "第二次原文": "乙"}
        raise x
    记录 = 跑(定义, 坏llm)
    a步 = [s for s in 记录 if s.get("node_id") == "a"]
    ck("AI 那一步记成失败,而且 output 里是两次原文", bool(a步) and a步[-1].get("output") == {"第一次原文": "甲", "第二次原文": "乙"},
       a步)

    print("\n▸ ⑤ 字符串里没转义的英文双引号 → 解析不了(推断的病根形状)")
    ck("没转义 → None", 结.解析('{"需求": "客户说"这个月要"的马面裙"}') is None)
    ck("用「」引 → 解析得了", 结.解析('{"需求": "客户说「这个月要」的马面裙"}') == {"需求": "客户说「这个月要」的马面裙"})

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ {len(过)} 条全过")
    return 0


def 跑(定义, llm):
    """用 runner 真跑一张小图,返回它记下的每一步(和 Worker 落 run_steps 用的是同一份)。"""
    import compiler as CP
    r = RN.跑一张图(CP.编译(定义, 依赖存在=lambda 种类, i: True), {}, 适配器={"llm": llm}, run_id="r")
    return r.get("步骤") or []


if __name__ == "__main__":
    sys.exit(main())
