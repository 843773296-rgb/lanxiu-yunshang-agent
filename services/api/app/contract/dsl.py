#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排 DSL 登记表 —— **节点、条件、变量、副作用分级的唯一来源**
(Workflow 与 Agent 规格 §6、§7、§9.6、§11.1、附录 A-1/A-3/A-9)。

## 为什么 DSL 要有一张登记表,而不是「节点想加什么字段就加什么字段」

规格 §16.5 最后一句:「**所有节点 Schema 应由版本化契约注册表声明,
不能接收任意自由字段**」。这句话在防的不是手滑,是一种很具体的腐烂:

一个节点的配置如果能收任意字段,那么「这个字段有没有被读」**没有任何地方能看出来**。
前端塞一个 `max_retries`,后端从来没读过它 —— 界面上那个输入框照样能填、能存、能显示,
只是填了不算。而这种坏法**不会报错**,它表现为「我配了重试三次,可它没重试」,
然后人去怀疑重试逻辑、怀疑网络、怀疑模型,最后才发现那个字段根本没人读。

> **一个从来没被读过的配置项,和一个坏了的配置项,在界面上长得一模一样。**

所以这里每个节点都要声明:有哪些配置字段、有哪些端口、
**通用字段里哪几条对它不生效**。最后那条是这张表最要紧的部分,见下。

## 通用字段的「不适用」为什么必须显式声明

规格 §6 开头给了一串节点通用字段(超时、可重试错误、最大重试次数、失败策略……),
紧接着写:「**无对应行为的字段隐藏或只读,不能出现全节点通用却不生效的设置**」。

「开始」节点上显示一个「单次超时 30 秒」就是这种设置 —— 它什么都不调用,
没有东西会超时。而它看起来和 LLM 节点上那个真的会生效的超时一模一样。

判据不能问「你声明了哪些不适用」(那是自说自话,同源谬误),
要从**另一头**判:每个节点单独声明它**会不会发起一次能超时的外部调用**(`调用外部`),
然后双向对账 ——

  · 不发外部调用的,超时/重试三件套**必须**在「不适用」里;
  · 发外部调用的,这三件套**不许**在「不适用」里。

两边都查,才拦得住「忘了声明」和「乱声明」两种错法。
"""
import hashlib
import json
import re

# ── 端口 ────────────────────────────────────────────────────────────
# 连线从「出端口」到「入端口」。**错误边要和成功边在结构上分开**(§5.2):
# 靠颜色区分的错误路径,在校验报告里没法引用,也没法在测试里断言。
成功 = "success"
失败 = "error"
分支 = "branch"        # 条件分支:每条分支一个出端口,ELSE 也是一个
循环体 = "loop_body"   # 有界循环 / 列表迭代:进子图
循环出 = "loop_exit"
支路 = "parallel"      # 并行:每条支路一个出端口

端口们 = (成功, 失败, 分支, 循环体, 循环出, 支路)

# ── 节点通用字段(规格 §6 开头那一段)──────────────────────────────
节点通用字段 = [
    ("name", "名称", "显示用;**不是执行 ID**(§5.2:稳定 node_id 创建后不随名称改变)"),
    ("description", "说明", "给人看的"),
    ("bindings", "输入绑定", "结构化引用,不是模板字符串(见 变量来源表)"),
    ("output_schema", "输出 Schema", "下游按它取值;**结构化解析失败是节点失败**,不当文本继续"),
    ("timeout_seconds", "单次超时", "只对真的会发起外部调用的节点生效"),
    ("retryable_errors", "允许重试的错误", "错误分类白名单;**认不出的错误不重试**"),
    ("max_retries", "最大重试次数", "传输重试不改变逻辑副作用键(§8)"),
    ("failure_policy", "失败策略", "失败了走错误边 / 整流程失败 / 允许部分结果"),
    ("output_retention", "输出保留策略", "多久、脱不脱敏 —— 和项目留存策略取交集"),
    ("required_capability", "所需权限", "**执行前服务端检查**,不是前端隐藏按钮"),
]
_通用名 = [f for f, _, _ in 节点通用字段]
# 会超时、会重试的那三件套 —— 判据双向对账就靠这个子集
_调用相关 = {"timeout_seconds", "retryable_errors", "max_retries"}

# 实现状态:**没实现的要标出来**(§6.1 结尾:「阶段中未完成的节点标『未实现』,
# 不得摆空按钮冒充可用」)。一个点了没反应的按钮比一个明写「未实现」的占位糟得多:
# 前者会让人以为是自己配错了,然后去改配置。
已实现 = "implemented"
未实现 = "not_implemented"


def N(名, 中文, *, 端口, 配置, 调用外部, 实现=未实现, 不适用=(), 说明="",
      可含子图=False, 唯一=False):
    """登记一个节点类型。

    `中文` 必须和规格 §6.1 那张表的第一列**一字不差** —— 覆盖检查拿它对账,
    改了规格而没改这里,检查当场红。
    """
    未知端口 = [p for p in 端口 if p not in 端口们]
    if 未知端口:
        raise ValueError(f"节点 {名} 用了不存在的端口 {未知端口} —— 现有 {端口们}")
    未知不适用 = [f for f in 不适用 if f not in _通用名]
    if 未知不适用:
        raise ValueError(
            f"节点 {名} 把 {未知不适用} 标成了「通用字段不适用」,"
            f"但通用字段里没有这几个 —— **拼错的字段名会让这条声明静默失效**")
    # ⚠️ 双向对账在这里就做掉,不留到检查里 —— 登记的时候就拦,错法活不过 import。
    缺 = sorted(_调用相关 - set(不适用)) if not 调用外部 else []
    多 = sorted(_调用相关 & set(不适用)) if 调用外部 else []
    if 缺:
        raise ValueError(
            f"节点 {名} 声明了不发外部调用,但没把 {缺} 标成不适用 —— "
            f"**界面上会出现一个拧了不算数的超时/重试设置**(§6)")
    if 多:
        raise ValueError(
            f"节点 {名} 会发外部调用,却把 {多} 标成不适用 —— "
            f"那它超时之后没有任何策略可依,只能挂在那里")
    return dict(名=名, 中文=中文, 端口=list(端口), 配置=list(配置),
                调用外部=bool(调用外部), 实现=实现, 不适用=list(不适用),
                说明=说明, 可含子图=bool(可含子图), 唯一=bool(唯一))


# ── 节点登记表(对齐规格 §6.1 那张表的每一行)────────────────────────
节点表 = [
    N("start", "开始",
      端口=[成功], 配置=["input_schema", "defaults", "size_limits"],
      调用外部=False, 实现=已实现, 唯一=True,
      不适用=["timeout_seconds", "retryable_errors", "max_retries",
              "bindings", "required_capability"],
      说明="每个顶层 Workflow **唯一一个**开始。"
           "**认证身份不由用户字段指定**(§6.1)—— 输入里写一个 user_id 就换身份,"
           "那整套授权等于不存在;身份来自认证上下文,走「系统注入」"),

    N("llm", "LLM",
      端口=[成功, 失败], 配置=["connection_version_id", "prompt_version_id",
                              "bindings", "sampling_params", "output_schema",
                              "max_output_tokens", "repair_policy"],
      调用外部=True, 实现=已实现,
      说明="**普通 LLM 节点不自动执行它提出的工具调用**(§6.1)—— 模型返回一个工具请求,"
           "这里只把它当一条「模型说想调工具」的记录。要真调工具得用 Agent 节点或工具节点。"
           "这条区分是 Workflow 和 Agent 的分界线本身。"
           "**修复输出的那次调用照样消耗 Run 的额度**(§6.2)"),

    N("retrieve", "知识检索",
      端口=[成功, 失败], 配置=["knowledge_base_id", "index_build_id",
                              "retrieval_config_version_id", "bindings", "filters"],
      调用外部=True, 实现=已实现,
      说明="**权限过滤由服务端强制**(§6.1)—— 检索结果里夹一篇他无权看的文档,"
           "就是一次越权读取,而它长得像一条普通证据。"
           "复用原有 RAG 后台,不在这儿重做一套"),

    N("tool", "工具",
      端口=[成功, 失败], 配置=["tool_version_id", "arguments", "connection_id",
                              "confirmation_policy", "idempotency_strategy"],
      调用外部=True, 实现=已实现,
      说明="执行前过四道:Schema、对象授权、确认、幂等(§6.1)。"
           "**服务端绑定参数不许被模型或前端覆盖** —— 输出目录、project_id、允许的库"),

    N("condition", "条件分支",
      端口=[分支], 配置=["branches", "else_policy"],
      调用外部=False, 实现=已实现,
      不适用=["timeout_seconds", "retryable_errors", "max_retries", "output_schema"],
      说明="**首个匹配的分支生效**,顺序即优先级;"
           "**必须配 ELSE 或显式终止策略**(§6.1)—— 没有兜底的条件在运行时是一条死路,"
           "而它在画布上看不出来"),

    N("transform", "字段转换",
      端口=[成功, 失败], 配置=["operations", "output_schema"],
      调用外部=False, 实现=已实现,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="**白名单转换,不许把任意 Python/JS 放进表达式直接执行**(§6.1、§17.4)。"
           "一个能 eval 的字段就是一条远程代码执行通道,而它在界面上只是个文本框"),

    N("merge", "分支汇合",
      端口=[成功], 配置=["candidates", "output_field", "optional_policy"],
      调用外部=False, 实现=已实现,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="条件分支**只取实际激活的那一路**;类型要兼容。"
           "未激活的支路既不阻塞汇合,也不算「完成了的工作」(§8)"),

    N("parallel", "并行与汇总",
      端口=[支路, 成功, 失败], 配置=["branches", "max_concurrency", "wait_policy",
                                   "failure_policy"],
      调用外部=False, 实现=未实现, 可含子图=True,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="**首版等全部必需支路结束;不得完成一个就宣告整组成功**(§6.1)。"
           "每条支路写**独立状态命名空间** —— 并发写同一个全局字段的结果取决于调度顺序,"
           "而那不是确定语义"),

    N("loop", "有界循环",
      端口=[循环体, 循环出, 失败], 配置=["condition", "loop_state", "max_iterations"],
      调用外部=False, 实现=未实现, 可含子图=True,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="**先判断后执行**(while 语义):进入条件为 false 时**零次执行**。"
           "循环计数和轮间状态进检查点,**恢复不清零**(§6.3)—— 清零的计数等于没有上限。"
           "达到上限但任务没达标,返回**受限停止**,不是成功"),

    N("foreach", "列表迭代",
      端口=[循环体, 循环出, 失败], 配置=["array_binding", "max_concurrency",
                                       "item_failure_policy"],
      调用外部=False, 实现=未实现, 可含子图=True,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="**输出保持输入索引**(§6.3):并发完成顺序不同,但第 3 项的结果必须在第 3 位。"
           "失败项**保留占位和原因**,不默默删除 —— 删掉一项会让后面全体错位,"
           "而错位之后的数据看起来完全正常"),

    N("human", "人工输入/审核",
      端口=[成功, 失败], 配置=["request_kind", "payload_binding", "allowed_fields",
                              "candidate_roles", "expires_at_policy"],
      调用外部=False, 实现=已实现,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="**等待不占用 Worker**(§6.1、§12.4):挂起时释放租约,靠事件恢复。"
           "一个挂在那里等人批的后台线程,等的是小时级 —— 那不是等待,那是泄漏。"
           "审批者必须**对那个对象**有权限,不是「有审批角色」就行"),

    N("agent", "Agent",
      端口=[成功, 失败], 配置=["agent_version_id", "task_binding", "input_mapping",
                              "allowed_capabilities", "sub_limits", "allow_human_wait"],
      调用外部=True, 实现=已实现,
      说明="**不能放大父流程的权限/预算**(§6.1、§13.2)—— 有效权限取交集,"
           "子任务消耗计入父任务额度。每嵌套一层重新拿一份完整预算,"
           "等于预算上限可以靠嵌套无限突破。"
           "**Agent 失败不能当成功文本继续**"),

    N("end", "结束",
      端口=[], 配置=["bindings", "output_schema", "terminal_policy"],
      调用外部=False, 实现=已实现,
      不适用=["timeout_seconds", "retryable_errors", "max_retries"],
      说明="必需字段**必须有合法来源**(§6.1);"
           "**「返回成功」和「任务达标」分开记** —— 一个返回了 200 的流程可能什么都没做成"),

    N("subworkflow", "子工作流",
      端口=[成功, 失败], 配置=["workflow_version_id", "input_mapping", "sub_limits"],
      调用外部=True, 实现=未实现,
      说明="只能引**已冻结**的子流程;**静态依赖图禁止递归引用**(§13.2)。"
           "运行时另设嵌套深度上限 —— 静态图拦不住动态构造出来的深度"),
]

_节点按名 = {n["名"]: n for n in 节点表}
_节点按中文 = {n["中文"]: n for n in 节点表}


def 找节点(名):
    if 名 not in _节点按名:
        raise KeyError(f"没有这个节点类型:{名} —— 现有 {list(_节点按名)}")
    return _节点按名[名]


def 节点中文们():
    return [n["中文"] for n in 节点表]


def 可用节点():
    """界面节点库里**能拖出来**的那些。未实现的要单独列成禁用项并写明原因。"""
    return [n for n in 节点表 if n["实现"] == 已实现]


# ── 条件操作符(规格 §6.3)────────────────────────────────────────────
#
# ## 为什么「字段不存在」要有一个专门的值
#
# 规格 §6.3 要求把这四件事分开:`exists`(字段存不存在)、`is_null`(值是不是 null)、
# `is_empty_string`(是不是空字符串)、空列表(用长度规则判)。§3.3 再强调一次:
# 「`0`、空字符串、`null`、字段不存在**必须区分**,不能统一用「空」模糊处理」。
#
# 用 Python 的 None 同时表示「没这个字段」和「值是 null」就做不到这个区分 ——
# 而这两件事的处置完全相反:值是 null 是**数据**,字段不存在是**配置错了**。
# 把后者当前者,等于把「我绑错了变量」显示成「上游没给值」,
# 然后人去查上游,查半天。
class _缺失:
    """「这个字段根本不存在」。**和 None 不是一回事。**"""
    _单例 = None

    def __new__(cls):
        if cls._单例 is None:
            cls._单例 = super().__new__(cls)
        return cls._单例

    def __repr__(self):
        return "<缺失:字段不存在>"

    def __bool__(self):
        # **不许被当成布尔值用** —— `if 值:` 会把缺失和 0、""、[] 混成一类,
        # 而这正是这个类存在的理由。
        raise TypeError("缺失不能当布尔值用 —— 它和 0/空字符串/空列表不是一回事")


缺失 = _缺失()


class 变量缺失(Exception):
    """引用的字段不存在。**不返回 False** —— 见下面 判() 的注释。"""


class 类型不匹配(Exception):
    """操作数类型和操作符要求的不一致。**不隐式转换**(§6.3)。"""


数 = "number"
文 = "string"
布 = "boolean"
日 = "datetime"
列 = "list"
任 = "any"


def OP(名, 中文, 元数, 操作数类型, 说明):
    return dict(名=名, 中文=中文, 元数=元数, 操作数类型=操作数类型, 说明=说明)


操作符表 = [
    OP("exists", "字段存在", 1, 任,
       "**只问「有没有这个字段」** —— 值是 null 也算存在"),
    OP("not_exists", "字段不存在", 1, 任, "和 exists 相反"),
    OP("is_null", "值是 null", 1, 任,
       "字段**必须存在**;不存在时抛「变量缺失」,不返回 true —— "
       "「没这个字段」和「值是 null」处置相反"),
    OP("is_not_null", "值不是 null", 1, 任, ""),
    OP("is_empty_string", "是空字符串", 1, 文,
       "**只接受字符串**;拿它去问一个列表是不是空的会抛类型错 —— "
       "空列表用 length_eq 0(§6.3)"),
    OP("equals", "等于", 2, 任,
       "**类型必须相同**:数字 1 和文本 \"1\" 不相等,而且**不隐式转换** —— "
       "要比就插一个显式转换节点(§6.3)"),
    OP("not_equals", "不等于", 2, 任, ""),
    OP("gt", "大于", 2, 数, "**只比数字**;布尔值不是数字(见下面那条注释)"),
    OP("gte", "大于等于", 2, 数, ""),
    OP("lt", "小于", 2, 数, ""),
    OP("lte", "小于等于", 2, 数, ""),
    OP("date_before", "早于", 2, 日, "**日期比较单独一组**:和数值比较不共用操作符,"
                                   "否则一个时间戳字符串会悄悄走进字典序比较"),
    OP("date_after", "晚于", 2, 日, ""),
    OP("length_eq", "长度等于", 2, 列, "列表/字符串/对象的长度;**空列表用它判**"),
    OP("length_gt", "长度大于", 2, 列, ""),
    OP("length_lt", "长度小于", 2, 列, ""),
    OP("contains", "包含", 2, 列, "列表包含某个元素,或字符串包含子串;类型要对得上"),
]

_操作符按名 = {o["名"]: o for o in 操作符表}
_单元 = {"exists", "not_exists", "is_null", "is_not_null", "is_empty_string"}
# exists / not_exists 是**唯一**允许接一个缺失值的操作符 —— 它们问的正是这件事。
_容许缺失 = {"exists", "not_exists"}


def _是数(v):
    # ⚠️ Python 里 `isinstance(True, int)` 是 **True**,`True > 0` 也成立。
    # 于是一个天真的数值检查会放过布尔值,然后 `gt(是否已付款, 0)` 一路跑到生产,
    # **而它永远返回 true**。这一行就是为了这个。
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _是日(v):
    # 只认 ISO 8601 字符串和 datetime —— 不认「看起来像日期」的自由文本。
    # 判据宽一点的代价是:一个排版怪的日期会被拿去做字典序比较,而结果看着像对的。
    import datetime as _dt
    if isinstance(v, (_dt.date, _dt.datetime)):
        return True
    return isinstance(v, str) and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
                     r"(Z|[+-]\d{2}:?\d{2})?)?", v))


def 判(操作符, 左, 右=None):
    """算一条条件。

    **认不出的操作符当场抛,不返回 False** —— 返回 False 的话,
    拼错一个操作符名就等于「这条条件不成立」,而那是另一回事,
    并且它会安静地把流程带去 ELSE 分支。

    **缺变量也抛**(§6.3:「缺变量不能默认 false 掩盖配置错误,按缺失策略处理」)。
    缺失策略是**调用方**的事 —— 编译器/执行器拿到这个异常,
    再按节点上声明的策略决定走哪条路。在这里默默当 false,
    就把「我绑错了变量」和「上游确实没给值」压成了同一件事。
    """
    if 操作符 not in _操作符按名:
        raise KeyError(f"没有这个操作符:{操作符} —— 现有 {list(_操作符按名)}")
    o = _操作符按名[操作符]
    if o["元数"] == 1 and 右 is not None:
        raise 类型不匹配(f"{操作符} 是单元操作符,不收右操作数")
    if o["元数"] == 2 and 操作符 not in _单元 and 右 is None and not isinstance(右, (int, float, str)):
        # 右操作数确实可以是 None(比如 equals(x, None) 判「值是不是 null」——
        # 但那件事有专门的 is_null,所以这里不特殊放行,交给下面的类型检查)
        pass

    if 左 is 缺失 and 操作符 not in _容许缺失:
        raise 变量缺失(
            f"{操作符} 的左操作数指向一个**不存在的字段** —— "
            f"这通常是绑定写错了,而不是上游没给值。"
            f"要判「有没有」用 exists,要判「是不是 null」先确认字段存在")

    if 操作符 == "exists":
        return 左 is not 缺失
    if 操作符 == "not_exists":
        return 左 is 缺失
    if 操作符 == "is_null":
        return 左 is None
    if 操作符 == "is_not_null":
        return 左 is not None
    if 操作符 == "is_empty_string":
        if not isinstance(左, str):
            raise 类型不匹配(
                f"is_empty_string 只接受字符串,给的是 {type(左).__name__} —— "
                f"**空列表用 length_eq 0 判**(§6.3),不共用「空」这个词")
        return 左 == ""

    if 操作符 in ("equals", "not_equals"):
        # **不隐式转换**:类型不同一律不相等?不行 —— 那会把「类型配错了」
        # 静默显示成「值不相等」,然后流程走 ELSE,而没有任何地方说过为什么。
        # 所以类型不同**抛**,让校验报告能指到那个字段。
        # 例外:和 null 比 —— 但那件事有 is_null,这里不给第二条路。
        if type(左) is not type(右) and not (_是数(左) and _是数(右)):
            raise 类型不匹配(
                f"equals 两边类型不同:{type(左).__name__} vs {type(右).__name__} —— "
                f"**数字 1 和文本 \"1\" 不相等,而且不隐式转换**;"
                f"要比就插一个显式转换节点(§6.3)")
        return (左 == 右) if 操作符 == "equals" else (左 != 右)

    if 操作符 in ("gt", "gte", "lt", "lte"):
        for v in (左, 右):
            if not _是数(v):
                raise 类型不匹配(
                    f"{操作符} 只比数字,给的是 {v!r}({type(v).__name__})—— "
                    f"**布尔值不是数字**:`True > 0` 在 Python 里成立,"
                    f"而那会让一个开关字段悄悄通过数值比较")
        return {"gt": 左 > 右, "gte": 左 >= 右,
                "lt": 左 < 右, "lte": 左 <= 右}[操作符]

    if 操作符 in ("date_before", "date_after"):
        for v in (左, 右):
            if not _是日(v):
                raise 类型不匹配(
                    f"{操作符} 只比日期(ISO 8601 或 datetime),给的是 {v!r} —— "
                    f"**不拿自由文本去做字典序比较**:那种比较的结果看着像对的")
        import datetime as _dt

        def _转(v):
            if isinstance(v, _dt.datetime):
                return v
            if isinstance(v, _dt.date):
                return _dt.datetime(v.year, v.month, v.day, tzinfo=_dt.timezone.utc)
            s = v.replace(" ", "T").replace("Z", "+00:00")
            d = _dt.datetime.fromisoformat(s)
            return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
        a, b = _转(左), _转(右)
        return a < b if 操作符 == "date_before" else a > b

    if 操作符 in ("length_eq", "length_gt", "length_lt"):
        if not isinstance(左, (list, tuple, str, dict)):
            raise 类型不匹配(f"{操作符} 要一个有长度的东西,给的是 {type(左).__name__}")
        if not isinstance(右, int) or isinstance(右, bool):
            raise 类型不匹配(f"{操作符} 的右操作数要整数,给的是 {右!r}")
        n = len(左)
        return {"length_eq": n == 右, "length_gt": n > 右, "length_lt": n < 右}[操作符]

    if 操作符 == "contains":
        if isinstance(左, (list, tuple)):
            return 右 in 左
        if isinstance(左, str):
            if not isinstance(右, str):
                raise 类型不匹配("字符串包含只接受字符串子串 —— 不把数字转成文本再找")
            return 右 in 左
        raise 类型不匹配(f"contains 要列表或字符串,给的是 {type(左).__name__}")

    raise AssertionError(f"操作符 {操作符} 登记了但没实现 —— **这一行不许存在**")


# ── 变量来源(规格 §7.1 那张表)──────────────────────────────────────
def V(名, 中文, 配置, 模型可改, 进模型上下文, 例子, 说明=""):
    return dict(名=名, 中文=中文, 配置=配置, 模型可改=bool(模型可改),
                进模型上下文=bool(进模型上下文), 例子=例子, 说明=说明)


变量来源表 = [
    V("constant", "常量", "有类型的固定值", False, True, "报告语言为中文"),
    V("input", "用户输入", "input 字段路径", False, True, "product_names"),
    V("node", "节点结果", "node_id + JSON Pointer", False, True, "搜索节点的结果数组"),
    V("scope", "循环/单项上下文", "所属作用域 + 字段", False, True, "当前产品名称",
      说明="跨容器引用局部变量是非法的(§7.2)—— 出了作用域那个值就不存在,"
           "而引用它的表达式在画布上看起来完全正常"),
    V("system", "系统注入", "由服务端提供", False, True, "project_id / 请求者 / release_id",
      说明="**模型不可改**(§7.1)。一个能被模型改写的 project_id "
           "就是一条跨项目越权通道,而它长得像一个普通变量绑定"),
    V("secret", "密钥引用", "secret_ref,仅连接层可用", False, False, "搜索服务凭证",
      说明="**绝不进模型上下文**(§7.1、§11.2)。密钥一旦进过一次提示词,"
           "它就已经进过日志、进过 Trace、可能进过导出文件 —— "
           "而「模型没说出来」不等于「没泄露」"),
]

_来源按名 = {v["名"]: v for v in 变量来源表}


def 找来源(名):
    if 名 not in _来源按名:
        raise KeyError(f"没有这种变量来源:{名} —— 现有 {list(_来源按名)}")
    return _来源按名[名]


# ── 副作用分级(规格 §11.1 的 side_effect_type)────────────────────────
只读 = "read_only"
写入 = "write"
不可逆 = "irreversible"


def SE(名, 中文, 需确认, 需幂等, 需外部查询, 说明):
    return dict(名=名, 中文=中文, 需确认=bool(需确认), 需幂等=bool(需幂等),
                需外部查询=bool(需外部查询), 说明=说明)


副作用表 = [
    SE(只读, "只读", False, False, False,
       "重复调用没有代价。**但重复读也可能拿到新资料** —— "
       "重放一个读节点要新建子运行,不能把新查到的数据贴回历史结果冒充当时事实(§8)"),
    SE(写入, "写入", False, True, True,
       "**必须有幂等键**:HTTP 超时不代表对方没做事(§8)。"
       "查不到结果时先置「待核实」,**不盲重试**"),
    SE(不可逆, "不可逆写入", True, True, True,
       "发消息、转账、删除这一类。**执行前必须有绑定了参数摘要的人工确认**(§12.2),"
       "而且**模型不能批准自己**(§9.6)。"
       "没有外部幂等或状态查询能力时,承诺不了 exactly-once —— "
       "那就标「待人工核实」,不许自动重复"),
]

_副作用按名 = {s["名"]: s for s in 副作用表}


def 可以执行吗(side_effect_type, *, 有幂等键, 有生效的批准, 能查外部状态):
    """工具网关的执行前闸。返回 (行不行, [挡住的理由])。

    **认不出的副作用类型当场挡** —— 未知不等于安全,
    一个没标级别的工具最可能的情况正是「它会写东西但没人标」。
    """
    挡 = []
    s = _副作用按名.get(side_effect_type)
    if s is None:
        return False, [f"side_effect_type={side_effect_type!r} 认不出 —— "
                       f"**没标级别的一律挡**(未知不等于安全)"]
    if s["需幂等"] and not 有幂等键:
        挡.append(f"{s['中文']}必须带幂等键 —— 超时重发一次的代价是重复做一遍")
    if s["需确认"] and not 有生效的批准:
        挡.append(f"{s['中文']}必须有**当前仍然有效**的人工批准 —— "
                  f"参数或目标变了,旧批准就失效(§12.2)")
    if s["需外部查询"] and not 能查外部状态:
        挡.append(f"{s['中文']}的工具契约没声明 external_status_lookup —— "
                  f"那么崩溃恢复时无法核实它到底做了没有,只能标「待人工核实」")
    return (not 挡), 挡


# ── Agent 运行限制(规格 §9.6 那张表)────────────────────────────────
#
# ## 为什么每条限制都要写「落点」
#
# 规格 §9.6 给每条限制单列了一栏「强制执行位置」。这一栏是整张表的重点:
# 一个只存在于配置表单里、没有任何地方读的上限,**和没有这条限制一模一样** ——
# 而界面上它是填好的,看起来像在生效。
#
# 所以这里每条都登记落点,并且诚实标 `已落地`。契约阶段全部是 False;
# 每落地一条,把它改成 True 并把下面那个欠账上限**减一**。
# 上限写死成数字(不是 `len(...)`)—— 一个跟着实际数量涨的上限不是棘轮,是装饰。
def L(名, 中文, 单位, 落点, 已落地, 说明):
    return dict(名=名, 中文=中文, 单位=单位, 落点=落点,
                已落地=bool(已落地), 说明=说明)


限制表 = [
    L("max_model_turns", "最大模型回合数", "次",
      "runtime/agent/loop.py::回合闸", False,
      "**一次模型请求算一回合,包括修复和 fallback 请求**(§9.6)—— "
      "只数「正常」请求的话,一个反复修格式的 Agent 可以无限跑"),
    L("max_tool_attempts", "最大工具调用数", "次",
      "runtime/tool_gateway/gate.py::调用闸", False,
      "**以实际尝试执行为单位**,同时把逻辑调用数和重试数**分开显示** —— "
      "合成一个数之后,「它试了 12 次」和「它做了 12 件事」就分不出来了"),
    L("deadline_seconds", "总执行期限", "秒",
      "runtime/checkpoints/deadline.py::到期检查", False,
      "墙钟上限;**等待人工也有截止时间**(§9.6)。"
      "人工等待的截止时间不能照搬活跃执行那个秒数(§9.6 结尾)"),
    L("max_active_compute_seconds", "活跃计算上限", "秒",
      "runtime/workflow/runner.py::活跃计时", False,
      "只算实际执行消耗 —— 和总期限分开,否则等人批一晚上就把上限耗完了"),
    L("budget_amount", "成本预算", "金额",
      "runtime/budget/reserve.py::原子预留", False,
      "**并发调用前分别预留**(§17.3),否则两路同时看到余额够、一起超。"
      "未知计价单列;**外部账单滞后,不保证绝对零超支**"),
    L("tool_timeout_retry", "单工具超时/重试", "秒/次",
      "runtime/tool_gateway/retry.py::退避", False,
      "可重试类型、次数、退避;**写操作必须满足幂等条件**才允许重试"),
    L("allowed_tools_and_scopes", "允许的工具与对象", "白名单",
      "runtime/tool_gateway/authz.py::有效权限", False,
      "**每次执行前**服务端检查(§9.6)—— 不是启动时查一遍就存下来:"
      "权限可能在运行中被撤回,而正在跑的 Run 照样在动"),
    L("write_confirmation", "写操作确认", "策略",
      "human_tasks/approval.py::批准绑定", False,
      "具体动作、目标和参数,由谁批准。**模型不能批准自己**(§9.6)"),
    L("max_concurrency", "并发调用", "个",
      "runtime/tool_gateway/gate.py::并发闸", False,
      "**首版串行**;并行只开给能证明独立的动作,而且**不能由模型绕过**"),
    L("stop_conditions", "停止与异常策略", "策略",
      "runtime/agent/stop.py::终止判定", False,
      "工具不可用、达到上限、无证据、重复无进展 —— Runtime 返回**明确的终止原因**,"
      "不是一个空的「已结束」"),
]

# **欠账上限,写死。** 现在 10 条全部未落地(契约阶段本该如此)。
# 每落地一条就把这个数减一;**只许降不许涨**。
# ⚠️ 不许写成 `len([...未落地...])` —— 那种「上限」会跟着实际数量一起涨,
# 于是新增一条未落地的限制照样绿。栽过一次。
未落地限制上限 = 10

_限制按名 = {l["名"]: l for l in 限制表}


def 找限制(名):
    if 名 not in _限制按名:
        raise KeyError(f"没有这条限制:{名} —— 现有 {list(_限制按名)}")
    return _限制按名[名]


# ── 逻辑哈希(附录 A-9)──────────────────────────────────────────────
#
# ## 判据:挪节点不改哈希,改条件改哈希
#
# 规格附录 A-9 要的是:「**仅对规范化语义字段和确切依赖算内容哈希,排除坐标/密钥**;
# Diff 按稳定 ID 对齐」。两个方向都要成立:
#
#   · 自动布局挪了一遍节点位置 → 哈希不变(否则每次整理画布都像改了执行逻辑,
#     人会开始忽略「版本变了」这个信号);
#   · 改了一个分支条件 → 哈希必变(否则发布清单指向的那一版和实际跑的不是一份)。
#
# 「哪些字段影响行为」这份清单必须显式维护 —— 它是这个哈希唯一的真相源。
#
# ## ⚠️ 这份清单**按位置剥,不按名字剥**
#
# 第一版是在整棵树上按键名剥的:凡是叫 `x` / `y` / `name` / `layout` 的键,
# 不管在哪一层,一律去掉。结果当场被冒烟撞到:一个**配置里**恰好叫 `x` 的业务字段,
# 改了它 **哈希不变** —— 于是那一版和上一版在发布清单上是同一份内容,而它们跑出来不一样。
#
# `name` 在**节点对象这一层**是显示名(改了不影响执行);在 `config` 里面完全可能是
# 业务字段 —— 一个字段转换节点输出一个叫 `name` 的字段、一个绑定指向 `/name`。
# 同一个词在不同位置是不同的东西,**而按名字匹配的判据看不出位置**。
#
# 所以剥的位置写死成三处:定义顶层、每个节点对象的顶层、每条连线对象的顶层。
# `config` / `bindings` / `arguments` 里面**一个字都不动**。
_节点顶层非语义 = {
    "layout", "position", "x", "y", "width", "height", "collapsed", "ui", "ui_meta",
    "name", "display_name", "description", "note", "comment", "label",
}
_定义顶层非语义 = {
    "layout", "viewport", "zoom", "ui", "ui_meta",
    "name", "display_name", "description", "note", "comment",
    "created_at", "created_by", "updated_at", "revision", "version_no",
}
_连线顶层非语义 = {"label", "note", "points", "waypoints", "style", "layout"}

# 定义里**一个都不许出现**的东西:密钥明文。
# 这里不写出真实的密钥匹配串(否则这个文件自己会被密钥扫描器命中)。
_密钥形状 = re.compile(
    r"(secret|token|api[_-]?key|apikey|authorization|bearer|password|passwd|"
    r"credential|private[_-]?key)", re.I)


class 定义里有密钥(Exception):
    """定义里出现了看起来像凭据的键。**抛,不是过滤掉。**"""


def _扫密钥(v, 路=""):
    """**全树深扫**密钥明文,只抛不改。

    ⚠️ 这个判据和上面「剥非语义键」**故意朝相反方向偏**:
    剥的那个要窄(剥多了 → 改了逻辑而哈希不变,**静默**);
    扫的这个要宽(漏了 → 密钥明文躺进库里,**也静默,而且更贵**)。
    宽了的代价是「拒绝冻结这一版」—— 吵闹,但当场就能改。

    `secret_ref` 之类的引用是允许的:它是指针,不是内容。
    """
    if isinstance(v, dict):
        for k in v:
            if _密钥形状.search(str(k)) and not str(k).endswith(("_ref", "_refs")):
                raise 定义里有密钥(
                    f"定义里出现了 `{路}{k}` —— **节点配置里不许有密钥明文**"
                    f"(§5.2:复制节点不能复制密钥明文);密钥走 secret_ref")
            _扫密钥(v[k], f"{路}{k}.")
    elif isinstance(v, (list, tuple)):
        for x in v:
            _扫密钥(x, f"{路}[].")


def _去(obj, 名单):
    """只在**这一层**去掉非语义键;里面的东西原样保留。"""
    if not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k not in 名单}


def 规范化(定义):
    """把定义整成「同一份内容 → 同一份表示」。

    nodes / edges **按稳定 ID 排序** —— 画布上先加哪个节点不该改变哈希,
    而 JSON 里它们的先后就是加入顺序。
    ⚠️ 条件分支的 `branches` **不排序**:那个列表的顺序就是优先级(§6.1
    「首个匹配分支生效」)—— 排了它,改优先级就不改哈希了。
    而 branches 在 config 里面,上面那条「config 一个字都不动」已经保证了这件事。
    """
    if not isinstance(定义, dict):
        raise TypeError(f"定义要是一个对象,给的是 {type(定义).__name__}")
    _扫密钥(定义)
    d = _去(定义, _定义顶层非语义)
    ns = d.get("nodes")
    if isinstance(ns, list):
        d["nodes"] = sorted((_去(n, _节点顶层非语义) for n in ns),
                            key=lambda n: str(n.get("id", "")) if isinstance(n, dict) else str(n))
    es = d.get("edges")
    if isinstance(es, list):
        d["edges"] = sorted((_去(e, _连线顶层非语义) for e in es),
                            key=lambda e: (str(e.get("source", "")), str(e.get("port", "")),
                                           str(e.get("target", "")), str(e.get("branch_key", "")))
                            if isinstance(e, dict) else (str(e), "", "", ""))
    return d


def 逻辑哈希(定义):
    """规范化之后的 SHA-256。`sort_keys` 保证键序无关。"""
    s = json.dumps(规范化(定义), sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"))
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()
