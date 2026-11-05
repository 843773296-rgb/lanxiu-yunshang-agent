#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测派发前检查(DF-05,2026-11-05)。不要数据库,真调 eval_dispatch.派发前检查 / 题的输入。

**一个模型都还没调的时候把能查的全查了** —— 派出去再红,钱已经花了。

  ① 合格的题 + 两版都没有人工核对 → 能派(field_errors 空)
  ② 有一道题没有工作流输入(聊天记录形状)→ 点名那一道
  ③ 题的输入不合某一版的输入格式 → 点名那一道、那一边
  ④ 有一版带人工核对步骤 → 拒(评测不往真人的待办里塞单)
  ⑤ 空题集 → 拒(空集合上「全过」恒成立)
  ⑥ 超过一次评测的派发上限 → 拒,且说清算式
  ⑦ 输入 Schema 里的 title / description(给人看的)不让校验器报「不支持的关键字」
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
import eval_dispatch as ED  # noqa: E402

过, 挂 = [], []
SCH = {"type": "object", "required": ["article"], "additionalProperties": False,
       "properties": {"article": {"type": "string", "minLength": 1, "title": "正文", "description": "给人看的"}}}
版 = {"nodes": [{"id": "start", "type": "start"}, {"id": "finish", "type": "end"}], "input_schema": SCH}
人工版 = {"nodes": 版["nodes"] + [{"id": "核对", "type": "human"}], "input_schema": SCH}


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 题(i, 内容):
    return {"id": f"smp_{i}", "content": 内容}


def main():
    好 = [题(1, {"输入": {"article": "一"}}), 题(2, {"输入": {"article": "二"}})]
    坏 = ED.派发前检查(好, {"候选": 版, "基线": 版}, 2)
    ck("① 合格的题、两版都没有人工核对 → 能派", 坏 == {}, 坏)
    sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))
    import tool_gateway as TG
    原样 = TG.校验Schema({"article": "一"}, SCH)
    ck("⑦ 不剥 title / description 时校验器会报不支持(所以 ① 能过是因为剥掉了,不是校验器放过了)",
       bool(原样) and 坏 == {}, (原样, 坏))

    坏 = ED.派发前检查(好 + [题(3, {"问": "聊天", "答": "形状"})], {"候选": 版, "基线": 版}, 2)
    ck("② 第 3 道没有工作流输入 → 只点名它", set(坏) == {"题[smp_3]"}, 坏)

    坏 = ED.派发前检查(好 + [题(4, {"输入": {"article": ""}})], {"候选": 版, "基线": 版}, 2)
    ck("③ 第 4 道的输入不合格式(空串过不了 minLength)→ 两边各点名一次", set(坏) == {"题[smp_4].候选", "题[smp_4].基线"}, 坏)

    坏 = ED.派发前检查(好, {"候选": 人工版, "基线": 版}, 2)
    ck("④ 候选那一版带人工核对 → 拒,点名是哪一边", set(坏) == {"候选版本"} and "核对" in 坏["候选版本"], 坏)

    坏 = ED.派发前检查([], {"候选": 版, "基线": 版}, 2)
    ck("⑤ 空题集 → 拒", "数据集版本" in 坏, 坏)

    n = ED.派发上限 // 4 + 1                      # × 2 边 × 2 轮 刚好超上限
    坏 = ED.派发前检查([题(i, {"输入": {"article": "x"}}) for i in range(n)], {"候选": 版, "基线": 版}, 2)
    ck("⑥ 超过派发上限 → 拒,说明里写着算式", "数据集版本" in 坏 and str(n * 4) in 坏["数据集版本"], 坏)
    坏 = ED.派发前检查([题(i, {"输入": {"article": "x"}}) for i in range(n - 1)], {"候选": 版, "基线": 版}, 2)
    ck("⑥ 正好在上限内 → 能派(边界)", 坏 == {}, 坏)

    ck("题的输入:content 是字符串 JSON 也认得", ED.题的输入({"content": '{"输入": {"a": 1}}'}) == {"a": 1})
    ck("题的输入:输入不是对象 → None(不是当成空对象)", ED.题的输入({"content": {"输入": "一段字"}}) is None)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 评测派发前检查:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
