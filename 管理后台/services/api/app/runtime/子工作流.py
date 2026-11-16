#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子工作流(11-16 三期 3-3;规格 §6.1「子工作流」/ §13.2;11-12 拍「HTTP → 并行 → 子流 → 代码」顺序)。

一期的边界(语义先立住):
  · **只能引已冻结的版本**(workflow_version_id),引草稿的话父流程冻结之后子流程还会变 —— 版本不再是版本;
  · **静态禁递归**:校验时顺着「这一版引了谁、谁又引了谁」走一遍,走回本工作流就拦;
  · **动态深度上限**:静态图拦不住运行时才构造出来的深度(别人改了子流程的新版本再被引),执行时按层数再拦一道;
  · **预算随父**:这一步的上限不许超过父流程(校验器 ⑦ 已有),真跑时再取「这一步的上限」和「父流程还剩的」里更严的那个;
  · **子流程里不许停下等人 / 等外部**(一期):子流程是在父流程的一步里同步跑完的,没有它自己的检查点 ——
    校验时按子流程定义静态拦(人工核对 / Agent / 写数据的业务动作),执行时真要等了也拦成这一步失败,不冒充成功;
  · 子流程的输出就是这一步的输出(照子流程「最后返回什么」的结构);子流程里每一步的记录折成一份摘要落在这一步的输出里
    (一期不另开子运行,所以子流程里的步骤不逐条进 run_steps —— 记在这里,别让人以为它们没跑)。

这个模块不碰数据库、不看整张图:配置形状 / 合上限 / 顺着「取版本」走递归链是纯函数,校验器和执行器都从这里拿。
"""

深度上限 = 3            # 嵌套层数:子(1)/ 孙(2)/ 曾孙(3)可以;第 4 层拦。动态和静态用同一个数
_上限键 = ("max_model_turns", "max_tool_calls")
不许等的节点 = {"human": "人工核对", "agent": "Agent"}


def 配置问题(cfg):
    """返回 [(code, 消息, 建议, field_path)]。只查这一步自己配置的形状。"""
    出 = []
    v = (cfg or {}).get("workflow_version_id")
    if v not in (None, "") and not isinstance(v, str):
        出.append(("SUBWORKFLOW_VERSION_SHAPE", "「用哪一版子流程」要是一个版本编号", "在右侧「基本」里从下拉重新选", "config.workflow_version_id"))
    m = (cfg or {}).get("input_mapping")
    if m not in (None, "") and not isinstance(m, dict):
        出.append(("SUBWORKFLOW_INPUT_SHAPE", "「交给子流程什么」要是一组「子流程的输入项: 从哪来」", "在右侧「用到的数据」里重新选", "config.input_mapping"))
    限 = (cfg or {}).get("sub_limits")
    if 限 not in (None, "", {}):
        if not isinstance(限, dict):
            出.append(("SUBWORKFLOW_LIMITS_SHAPE", "「这一步的上限」要是一组「名字: 整数」", "在右侧「高级」里重新填", "config.sub_limits"))
        else:
            for k, x in 限.items():
                if k not in _上限键:
                    出.append(("SUBWORKFLOW_LIMIT_UNKNOWN", f"上限里有系统不认识的一项「{k}」", f"只认:{' / '.join(_上限键)}", f"config.sub_limits.{k}"))
                elif not (isinstance(x, int) and not isinstance(x, bool) and x >= 1):
                    出.append(("SUBWORKFLOW_LIMIT_RANGE", f"上限「{k}」要填 1 以上的整数", "在右侧「高级」里改", f"config.sub_limits.{k}"))
    return 出


def 合上限(子限, 父剩余):
    """这一步给子流程的额度 = 「这一步配的上限」和「父流程还剩的」里各取更严的那个(§13.2:嵌套不能重新拿一份完整预算)。"""
    出 = {}
    for k in _上限键:
        a = (子限 or {}).get(k)
        b = (父剩余 or {}).get(k)
        候 = [x for x in (a, b) if isinstance(x, int) and not isinstance(x, bool)]
        if 候:
            出[k] = max(0, min(候))
    return 出


def 递归链(起点版本id, 取版本, *, 本工作流=None, 最深=深度上限):
    """顺着「这一版引了哪些子流程版本」往下走。返回 (问题码 or None, 深度, 路径)。
    `取版本(版本id) -> {"workflow_id", "nodes"} 或 None`,由调用方给(校验器不自己查库)。
    问题码:SUBWORKFLOW_RECURSION(走回本工作流,或链上同一个工作流出现两次)/ SUBWORKFLOW_TOO_DEEP(超过深度上限)。
    深度从 1 数:直接引的那一版是第 1 层。"""
    见过工作流 = {本工作流} if 本工作流 else set()
    路径 = []

    def 走(vid, 层):
        if 层 > 最深:
            return "SUBWORKFLOW_TOO_DEEP"
        v = 取版本(vid)
        if not v:
            return None                    # 版本不存在由 REF_NOT_FOUND 那条报,这里不重复
        w = v.get("workflow_id")
        路径.append((vid, w))
        if w and w in 见过工作流:
            return "SUBWORKFLOW_RECURSION"
        if w:
            见过工作流.add(w)
        for n in v.get("nodes") or []:
            if isinstance(n, dict) and n.get("type") == "subworkflow":
                子 = ((n.get("config") or {}).get("workflow_version_id"))
                if 子:
                    r = 走(子, 层 + 1)
                    if r:
                        return r
        if w:
            见过工作流.discard(w)         # 回溯:兄弟分支引同一个工作流不算递归
        return None

    码 = 走(起点版本id, 1)
    return 码, len(路径), 路径


def 不能等的步骤(子定义, 工具读写=None):
    """子流程定义里哪些步骤会停下等人 / 等外部(一期子流程里不许有)。返回 [(node_id, 中文原因)]。
    写数据的业务动作要经澜绣桥回执 —— 也是等;读写不明的按写入算(偏错的代价朝「少放一步」)。"""
    出 = []
    for n in (子定义 or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        if t in 不许等的节点:
            出.append((n.get("id"), 不许等的节点[t]))
        elif t == "tool":
            读写 = 工具读写(((n.get("config") or {}).get("tool_version_id"))) if 工具读写 else None
            if 读写 != "read_only":
                出.append((n.get("id"), "会写数据的业务动作" if 读写 else "读写不明的业务动作"))
    return 出


def 步骤摘要(步们, 最多=30):
    """子流程的步骤折成摘要进这一步的输出。超过的说清还有几步。"""
    行 = [{"步骤": s.get("node_id"), "种类": s.get("kind"), "状态": s.get("status"), **({"错误码": s.get("error_code")} if s.get("error_code") else {})}
         for s in (步们 or [])[:最多]]
    出 = {"子流程步骤": 行, "子流程步数": len(步们 or [])}
    if len(步们 or []) > 最多:
        出["还有几步没列"] = len(步们) - 最多
    return 出
