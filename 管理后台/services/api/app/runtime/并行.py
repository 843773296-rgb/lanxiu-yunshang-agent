#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并行与汇总(11-16 三期 3-2;规格 §6.1 / §6.3「并行」;11-12 拍「HTTP → 并行 → 子流 → 代码」顺序)。

一期**语义先立住、实现串行**:`max_concurrency` 固定 1,几条支路一条接一条跑;
但对外的契约和真并发时一样 ——
  · 每条支路一个入口(并行节点的「支路」出口 + 支路键),支路里面的步骤 `container` 指向并行节点;
  · 支路之间**互不引用**(独立状态命名空间,校验器拦;真并发时谁先写完是调度顺序,不是确定语义);
  · **全部必需支路结束才汇总**,不得完成一个就宣告整组成功;
  · 结果按支路键存:{"结果": {键: 该支路最后一步的输出}, "状态": {键: succeeded / failed}, "失败支路": [...]}。
等待策略两种(规格 §6.3「首版支持」):任一必需支路失败整步失败;或显式允许部分结果(失败的支路留空、状态记 failed,整步照样汇总)。

这个模块**不碰数据库、不看整张图**:只查这一步自己配置的形状(校验器)、算汇总(执行器)。支路之间有没有互引、
支路有没有连线、里面有没有套循环,要知道别的节点,由校验器看整张图再查。
"""

等待策略 = {"all_required": "等全部必需支路结束;任一必需支路失败,这一步失败(走「失败时」出口)",
            "allow_partial": "允许部分结果:失败的支路留空、状态记 failed,其余照样汇总(结果合不合格由后面的输出契约定)"}
一期并发上限 = 1       # 串行实现;填别的数在检查配置就拦 —— 不许「填了 4 看起来并发、实际还是串行」


def 支路们(cfg):
    """配置里的支路列表(只留 dict 项)。"""
    bs = (cfg or {}).get("branches")
    return [b for b in bs if isinstance(b, dict)] if isinstance(bs, list) else []


def 支路键们(cfg):
    return [str(b.get("key")) for b in 支路们(cfg) if b.get("key") not in (None, "")]


def 必需吗(cfg, 键):
    """没写 required 的支路按必需算(偏错的代价朝「多等一条」,不朝「少等一条就宣告成功」)。"""
    for b in 支路们(cfg):
        if str(b.get("key")) == str(键):
            return b.get("required") is not False
    return True


def 配置问题(cfg):
    """返回 [(code, 消息, 建议, field_path)]。只查这一步自己的配置形状。"""
    出 = []
    bs = (cfg or {}).get("branches")
    if bs in (None, "", []):
        pass    # 「必填」那条已经报了 branches 没填,不再报第二条
    elif not isinstance(bs, list):
        出.append(("PARALLEL_BRANCHES_SHAPE", "「支路」要是一张列表,每一项写支路名和要不要等它", "在右侧「基本」里用「加一条支路」添加", "config.branches"))
    else:
        见过 = set()
        for j, b in enumerate(bs, 1):
            if not isinstance(b, dict) or b.get("key") in (None, ""):
                出.append(("PARALLEL_BRANCH_NO_KEY", f"第 {j} 条支路没有名字 —— 结果是按支路名存的,没名字就不知道存到哪",
                          "在右侧「基本」里给这条支路起个名字(比如「查库存」)", f"config.branches[{j}]"))
                continue
            k = str(b.get("key"))
            if k in 见过:
                出.append(("PARALLEL_BRANCH_DUP", f"有两条支路都叫「{k}」—— 结果按支路名存,重名会互相覆盖",
                          "把其中一条改个名字", f"config.branches[{k}]"))
            见过.add(k)
            if "required" in b and not isinstance(b.get("required"), bool):
                出.append(("PARALLEL_REQUIRED_SHAPE", f"支路「{k}」的「必需」要是 是 / 否", "在右侧「基本」里重新勾选", f"config.branches[{k}].required"))
        if 见过 and not any(必需吗(cfg, k) for k in 见过):
            出.append(("PARALLEL_NO_REQUIRED", "所有支路都不是必需的 —— 那这一步等谁?什么都没做完就会宣告成功",
                      "至少把一条支路勾成必需;可选支路只是「做完了就带上,没做完不等」", "config.branches"))
    并 = (cfg or {}).get("max_concurrency")
    if 并 not in (None, "") and 并 != 一期并发上限:
        出.append(("PARALLEL_CONCURRENCY_UNSUPPORTED", f"并发上限现在只能是 {一期并发上限}(一期串行实现,几条支路一条接一条跑)",
                  f"把并发上限改成 {一期并发上限};真并发要等下一期,不许填一个数让它看起来是并发", "config.max_concurrency"))
    等 = (cfg or {}).get("wait_policy")
    if 等 not in (None, "") and 等 not in 等待策略:
        出.append(("PARALLEL_BAD_WAIT_POLICY", "「等待策略」系统不认识",
                  f"在右侧「基本」里重新选:{' / '.join(等待策略.values())}", "config.wait_policy"))
    return 出


def 汇总(帧):
    """帧 → 这一步的输出。结果按支路键存;没跑到的支路(不该有)留 None、状态 skipped。"""
    键们 = list(帧.get("支路") or [])
    结果, 状态 = dict(帧.get("结果") or {}), dict(帧.get("支路状态") or {})
    for k in 键们:
        结果.setdefault(k, None)
        状态.setdefault(k, "skipped")
    return {"结果": 结果, "状态": 状态, "失败支路": list(帧.get("失败支路") or [])}
