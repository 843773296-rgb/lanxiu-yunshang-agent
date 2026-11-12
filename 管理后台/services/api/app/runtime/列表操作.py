#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流「列表操作」节点的规则 —— **校验器和执行器都调这一处**(照 Dify「列表操作」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 配置长什么样(全是选出来的,没有一处是表达式字符串)

    bindings: {"列表": <结构化引用>}                       上游给的那个列表
    filter:   {"conditions": [{"field": "金额", "op": "gt", "value": 100}, ...],
               "logic": "and" | "or"}                       可选;field 不写 = 拿这一项本身比
    sort:     {"field": "金额", "order": "asc" | "desc"}   可选;field 不写 = 拿这一项本身排
    limit:    5                                             可选;正整数,取前几个

顺序固定:**先过滤、再排序、再取前几个**。结果:结果(列表)/ 个数 / 第一个 / 最后一个
(列表空了,第一个 / 最后一个是 null —— 和「这一步没跑」那种取不到分得开,后面可以用「值是 null」判)。

## 为什么过滤只许选操作符、不许写表达式

一个能写 `item.金额 > 100 and ...` 的过滤框,就是一条在服务端执行表达式的通道(规格 §6.1、§17.4 白名单转换),
而它在界面上只是一个文本框。这里的操作符直接用条件分支那一套(`dsl.判`):**类型不对当场失败、不隐式转换** ——
文字「100」和数字 100 比大小,不悄悄转成数,也不悄悄当「不满足」。

## 为什么这么多情况是「这一步失败」而不是「跳过那一项」

排序时有的项有「金额」、有的没有;数字和文字混在一起排 —— 任何一种「猜」都会给出一个看着很整齐的顺序,
而后面「取前 3 个」拿到的就是猜出来的前 3 个。**猜错的结果在运行记录里看起来和对的一模一样**,所以失败、说清第几项。
过滤时某一项没有那个字段同理;真想先筛掉没有的,在前面加一条「字段存在」并用「且」连 —— 「且」是短路的,
前一条不满足就不再看后一条。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402


class 做不了(Exception):
    """这一步做不下去。执行器把它换成节点失败(走「失败」出口或整条失败)。"""

    def __init__(self, code, 消息, 建议):
        self.code, self.消息, self.建议 = code, 消息, 建议
        super().__init__(f"{code}: {消息}")


排序方向 = {"asc": "从小到大", "desc": "从大到小"}
_值类型说法 = {DS.数: "数字", DS.日: "日期(如 2026-11-12)", DS.列: "整数"}


def _操作符(名):
    return next((o for o in DS.操作符表 if o["名"] == 名), None)


def _值合适吗(o, v):
    """二元操作符右边那个固定值的类型对不对。只在校验期查得出来的那部分 —— 左边是运行时的数据。"""
    t = o["操作数类型"]
    if o["名"] in ("length_eq", "length_gt", "length_lt"):
        return isinstance(v, int) and not isinstance(v, bool)
    if t == DS.数:
        return DS._是数(v)
    if t == DS.日:
        return DS._是日(v)
    return True


def 配置问题(cfg):
    """返回 [(code, 消息, 建议, field_path)]。**只查形状**,不碰数据 —— 校验器调它,在冻结版本之前拦住。"""
    出 = []
    绑 = cfg.get("bindings") if isinstance(cfg.get("bindings"), dict) else {}
    if 绑 and "列表" not in 绑:
        出.append(("LIST_NO_INPUT", "还没选要处理哪个列表", "在右侧「用到的数据」里给「列表」选一个前面步骤给的列表",
                  "config.bindings.列表"))
    来 = 绑.get("列表")
    if isinstance(来, dict) and 来.get("source") == "constant" and not isinstance(来.get("value"), list):
        出.append(("LIST_NOT_ARRAY", "「列表」填的固定值不是列表", "改成一个列表,或者改选前面步骤给的列表",
                  "config.bindings.列表"))
    for k in sorted(set(绑) - {"列表"}):
        出.append(("LIST_EXTRA_BINDING", f"「用到的数据」里多了一项「{k}」,列表操作只用「列表」那一项,它不会被读",
                  f"删掉「{k}」", f"config.bindings.{k}"))

    f = cfg.get("filter")
    if f is not None:
        if not isinstance(f, dict) or not isinstance(f.get("conditions"), list) or not f["conditions"]:
            出.append(("LIST_FILTER_EMPTY", "开了过滤但一条条件都没有 —— 空条件不会当成全都留下",
                      "在右侧「基本」里加一条过滤条件,或者关掉过滤", "config.filter"))
        else:
            if f.get("logic") not in (None, "and", "or"):
                出.append(("LIST_FILTER_LOGIC", "过滤条件之间只能用「且」或「或」连", "在右侧「基本」里重新选", "config.filter.logic"))
            for j, w in enumerate(f["conditions"], 1):
                fp = f"config.filter.conditions[{j}]"
                w = w if isinstance(w, dict) else {}
                if "field" in w and not (isinstance(w["field"], str) and w["field"].strip()):
                    出.append(("LIST_FILTER_FIELD", f"第 {j} 条过滤条件「看哪一项」是空的",
                              "填上每一项里要看的那个名字;列表里是一个个数字或文字时,选「这一项本身」", fp))
                o = _操作符(w.get("op"))
                if not o:
                    出.append(("LIST_FILTER_OP", f"第 {j} 条过滤条件还没选「怎么比」", "在右侧「基本」里选一个比较方式", fp))
                    continue
                if o["元数"] == 1 and "value" in w:
                    出.append(("LIST_FILTER_VALUE", f"第 {j} 条「{o['中文']}」不用填比较值,填了也不会被读",
                              "把比较值清空", fp))
                elif o["元数"] == 2:
                    if "value" not in w:
                        出.append(("LIST_FILTER_VALUE", f"第 {j} 条「{o['中文']}」还没填跟什么比", "在右侧「基本」里填比较值", fp))
                    elif not _值合适吗(o, w["value"]):
                        出.append(("LIST_FILTER_VALUE",
                                  f"第 {j} 条「{o['中文']}」要跟一个{_值类型说法.get(o['操作数类型'], '合适的值')}比,填的是「{str(w['value'])[:30]}」",
                                  "改成对应类型的值;文字「100」和数字 100 不一样,不会悄悄转换", fp))

    s = cfg.get("sort")
    if s is not None:
        if not isinstance(s, dict) or s.get("order") not in 排序方向:
            出.append(("LIST_SORT_ORDER", "开了排序但还没选「从小到大」还是「从大到小」", "在右侧「基本」里选,或者关掉排序", "config.sort"))
        elif "field" in s and not (isinstance(s["field"], str) and s["field"].strip()):
            出.append(("LIST_SORT_FIELD", "排序「按哪一项」是空的", "填上每一项里要按它排的那个名字;列表里是一个个数字或文字时,选「这一项本身」",
                      "config.sort.field"))

    n = cfg.get("limit")
    if n is not None and not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
        出.append(("LIST_LIMIT", "「只要前几个」要填一个大于 0 的整数", "改成 1、3、10 这样的整数,或者清空表示全都要", "config.limit"))
    return 出


def _取(项, field, 第几):
    if field is None:
        return 项
    if not isinstance(项, dict):
        raise 做不了("LIST_ITEM_NOT_OBJECT", f"第 {第几} 项不是一条带名字的记录(是「{str(项)[:30]}」),没法看它的「{field}」",
                   "检查给进来的列表;列表里是一个个数字或文字时,把「看哪一项」改成「这一项本身」")
    return 项.get(field, DS.缺失)


def _过滤(列, f):
    条们, 连 = f["conditions"], ("or" if f.get("logic") == "or" else "and")
    留 = []
    for 第几, 项 in enumerate(列, 1):
        中 = 连 == "and"
        for w in 条们:
            左 = _取(项, w.get("field"), 第几)
            try:
                r = bool(DS.判(w["op"], 左, *([w["value"]] if "value" in w else [])))
            except DS.变量缺失:
                raise 做不了("LIST_FIELD_MISSING", f"第 {第几} 项没有「{w.get('field')}」,没法按它过滤",
                           f"要先筛掉没有「{w.get('field')}」的,在这一条前面加一条「字段存在」并用「且」连")
            except DS.类型不匹配 as e:
                raise 做不了("LIST_FILTER_TYPE", f"第 {第几} 项的「{w.get('field') or '值'}」是「{str(左)[:30]}」,和过滤条件类型对不上",
                           "核对这一项的类型和比较值;不会把文字悄悄转成数字(" + str(e)[:60] + ")")
            # 短路:「且」遇到不满足、「或」遇到满足就不再看后面 —— 「字段存在 且 金额 > 100」才写得出来
            if 连 == "and" and not r:
                中 = False
                break
            if 连 == "or" and r:
                中 = True
                break
        if 中:
            留.append(项)
    return 留


def _排序(列, s):
    field = s.get("field")
    键们 = []
    for 第几, 项 in enumerate(列, 1):
        k = _取(项, field, 第几)
        if k is DS.缺失 or k is None:
            raise 做不了("LIST_SORT_KEY_MISSING", f"第 {第几} 项没有「{field or '值'}」(或者是空),排不进去",
                       "先用过滤筛掉没有这一项的(「字段存在」「值不是 null」),再排序")
        键们.append(k)
    全数 = all(DS._是数(k) for k in 键们)
    全文 = all(isinstance(k, str) for k in 键们)
    if 键们 and not (全数 or 全文):
        坏 = next(i for i, k in enumerate(键们, 1) if not (DS._是数(k) if DS._是数(键们[0]) else isinstance(k, str)))
        raise 做不了("LIST_SORT_MIXED", f"「{field or '值'}」里数字和文字(或别的类型)混着,第 {坏} 项对不上,没法比大小",
                   "排序那一项要么全是数字、要么全是文字;是 / 否、列表、记录都不能排")
    # Python 的排序是稳定的(reverse=True 也稳定):一样大的保持原来的先后,同一份输入永远排出同一个顺序
    序 = sorted(range(len(列)), key=lambda i: 键们[i], reverse=s["order"] == "desc")
    return [列[i] for i in 序]


def 执行(列, cfg):
    """真跑一遍。`列` 是解出来的那个值。返回结果 dict;做不下去抛 `做不了`。"""
    if not isinstance(列, list):
        raise 做不了("LIST_NOT_ARRAY", f"给进来的不是列表(是{type(列).__name__}),没法做列表操作",
                   "在右侧「用到的数据」里给「列表」选一个列表类型的结果")
    结果 = list(列)
    if cfg.get("filter") is not None:
        结果 = _过滤(结果, cfg["filter"])
    if cfg.get("sort") is not None:
        结果 = _排序(结果, cfg["sort"])
    if cfg.get("limit") is not None:
        结果 = 结果[:cfg["limit"]]
    return {"结果": 结果, "个数": len(结果),
            "第一个": 结果[0] if 结果 else None, "最后一个": 结果[-1] if 结果 else None}
