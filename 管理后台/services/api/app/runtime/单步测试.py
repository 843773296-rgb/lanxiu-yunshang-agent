#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单步测试 —— 只跑草稿里的某一步,不从头跑整条流程(用户 10-26「下一项」,方案 §8.1「单步测试」)。

## 做法:拼一张只有三步的小图,交给试运行那一整套去跑

    开始(这一步要的每一项都变成使用者输入) → 这一步(原样) → 结束

为什么不另写一个「直接调一次适配器」的口子:试运行那一套(编译 · 幂等键 · 排队 · Worker ·
按连接定 mock / 真跑 · 记用量 · 记每一步输入输出 · 打码)是一个整体,抄一份简化版的话,
下次改其中一条规矩只会改到一处 —— 而两处都「能跑」。小图里**这一步的 id 不变**,
所以运行详情、步骤标记、「上次试运行」都直接认得它。

## 哪些步骤能单测

只认「输入全部来自『用到的数据』(bindings)」的那几类:模型、知识检索、业务动作。
  · 条件 / 汇合 / 字段转换的输入写在各自的规则里,不在 bindings —— 拼小图要改写规则本身,
    改写出来的规则和原来的是不是一回事说不清,先不做,**明说不支持**而不是糊一个
  · 人工核对:单测它等于给人派一张假待办
  · Agent:它自己会多轮调工具,单测范围不在「一步」

⚠️ **写入类的业务动作不许单测。** 整条流程里写入前面有人工核对把关,单测把前面全切掉了 ——
这时候真写一次,就是一条没人核对过的真实业务记录。方案 §8.1「连接测试:业务写入保持禁用」。
"""
import copy

能单测的类型 = {"llm": "模型", "retrieve": "知识检索", "tool": "业务动作"}
_不支持说法 = {
    "start": "「开始」不用单独测 —— 它只是把使用者填的内容原样交给下一步",
    "end": "「结束」不用单独测 —— 它只是把前面的结果收拢起来",
    "condition": "条件分支暂时不能单独测:它的输入写在分支条件里,不在「用到的数据」里",
    "merge": "分支汇合暂时不能单独测:它的输入写在要汇合的几路里,不在「用到的数据」里",
    "transform": "字段转换暂时不能单独测:它的输入写在整理规则里,不在「用到的数据」里",
    "human": "人工核对不能单独测:单测它会给真人派一张假的待办",
    "agent": "Agent 不能单独测:它自己会多轮调用工具,不止「一步」",
}


class 不能单测(Exception):
    def __init__(self, 消息, 建议):
        super().__init__(消息)
        self.消息, self.建议 = 消息, 建议


def 拼小图(定义, node_id, *, 工具读写=None, 写入只演练=False):
    """返回 (小图, 要填的字段)。不能单测时抛 `不能单测`。

    `工具读写(tool_version_id) -> "read_only" / "write" / "irreversible" / None` 由调用方查库给 ——
    这个模块不碰数据库,夹具测试才跑得起来(和校验器同一条规矩)。
    """
    节点们 = (定义 or {}).get("nodes") or []
    n = next((x for x in 节点们 if x.get("id") == node_id), None)
    if n is None:
        raise 不能单测("草稿里没有这一步,可能刚被删了", "刷新页面,重新选一步")
    t = n.get("type")
    if t not in 能单测的类型:
        raise 不能单测(_不支持说法.get(t, "这类步骤暂时不能单独测"),
                     "点「试运行」从头跑一遍整条流程")
    # 「连接测试」跑法下写入类动作不发给澜绣、只记「本来会写什么」(10-26)—— 那时候单测它不会写出真记录,放行
    if t == "tool" and not 写入只演练:
        读写 = 工具读写(((n.get("config") or {}).get("tool_version_id"))) if 工具读写 else None
        if 读写 is None:
            # 查不到读写性质就当写入 —— 偏错的代价朝「少测一次」那边,不朝「多写一条真记录」那边
            raise 不能单测("还不知道这个业务动作会不会写数据,为安全起见不单独测",
                         "先在右侧「基本」里选好业务动作;选好了还这样,请联系平台管理员核对它的读写登记")
        if 读写 != "read_only":
            raise 不能单测("这个业务动作会写数据,不能单独测:单测会跳过前面的人工核对,写出一条没人核对过的真实记录",
                         "跑法选「连接测试」再测(不真写,只显示会写什么);或者点「试运行」从头跑,写入前会停在人工核对")

    步 = copy.deepcopy(n)
    cfg = 步.setdefault("config", {})
    绑 = cfg.get("bindings") or {}
    要填, 新绑 = [], {}
    for 字段, 引用 in 绑.items():
        src = 引用.get("source") if isinstance(引用, dict) else None
        if src in ("constant", "system"):
            新绑[字段] = 引用            # 固定值 / 系统注入的,单测时照旧,不让人填
            continue
        # 来自前面步骤 / 使用者输入的,一律改成「单测时手填」—— 字段名不变,
        # 所以上一次运行记下的这一步输入,能原样当默认值填回来
        要填.append(字段)
        新绑[字段] = {"source": "input", "pointer": "/" + 字段.replace("~", "~0").replace("/", "~1")}
    cfg["bindings"] = 新绑
    步.pop("container", None)

    开始id = "__单测开始" if node_id != "__单测开始" else "__单测开始2"
    结束id = "__单测结束" if node_id != "__单测结束" else "__单测结束2"
    入 = {"type": "object", "properties": {f: {"title": f} for f in 要填}, "required": list(要填)}
    出 = {"type": "object", "properties": {}, "required": []}
    小图 = {
        "definition_schema_version": (定义 or {}).get("definition_schema_version", "1"),
        "kind": "workflow",
        "input_schema": 入,
        # 结束不映射任何字段:这一步交出了什么,看它自己那一行的「输出」(每一步的输入输出已经在记)——
        # 映射的话要猜它的输出长什么样,猜错了单测就会因为「结束取不到值」而失败,怪到这一步头上
        "output_schema": 出,
        "nodes": [
            {"id": 开始id, "type": "start", "name": "单测输入", "config": {"input_schema": 入}},
            步,
            {"id": 结束id, "type": "end", "name": "单测结束", "config": {"output_schema": 出}},
        ],
        "edges": [
            {"source": 开始id, "target": node_id, "port": "success"},
            {"source": node_id, "target": 结束id, "port": "success"},
        ],
    }
    return 小图, 要填
