#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具网关 —— **所有 Workflow/Agent 工具调用的唯一执行入口**
(规格 §9.4、§10.3、§11.1、§12.2、§16.1、§17.3、附录 A-6)。

## 为什么必须是「唯一入口」

规格 §16.1 给这个组件写的边界就是这句话。它不是架构洁癖:

模型输出「调用工具」是**请求**;真正执行接口、写文件、创建记录的是服务端运行时(§2)。
如果 Agent 运行时能自己发一次 HTTP,那么「这个 Agent 能做什么」就没有任何地方能一次看全 ——
权限、确认、幂等、账本全都变成「希望调用方记得」。

> **一道靠「每个人都记得检查」成立的边界,等于没有边界。**

所以这里不导出任何「跳过检查」的口子。`执行()` 是唯一的门,门上六道闸:
**注册 → 服务端绑定 → Schema → 范围 → 确认 → 幂等**,顺序是有意的,见下。

## 六道闸的顺序为什么是这个

① **工具名是否已注册**(§9.4:「未注册工具名一律拒绝」)。第一道,因为认不出的名字
   后面四道都没法查:没有 Schema、没有 allowed_scopes、没有 side_effect_type。
   **不能让模型凭一个名字临时发网络请求。**

② **Schema**。在权限之前,因为权限要按**参数里的对象**判 —— 参数形状不对的话,
   「它要写哪个目录」这个问题本身没有答案。

④ **权限 = 交集**(§13.2、附录 A-6):请求者 ∩ 应用允许范围 ∩ Agent 授权 ∩ 工具允许范围。
   取交集而不是取并集,是「调用者不能借子流程获得更高权限」的全部含义。

⑤ **确认**(§12.2)。绑定的是**参数摘要**,不是「这个工具」——
   批准 A 之后改成 B,旧批准失效。**模型不能批准自己**(§9.6)。

⑥ **幂等 / 账本**(§17.3):**先登记 intent,再调外部,收到响应再登记结果**。
   进程死在中间两步之间时去**核实**,不盲重放。

## 拒绝要返回「安全的拒绝原因」,不能伪造成功

§10.3 原话。两头都要守:
· 不能把拒绝包装成成功(那样 Agent 会以为事情做完了,继续往下推);
· 拒绝原因不能把它无权知道的东西说出来(比如「那个目录属于项目 B」——
  那句话本身就泄露了项目 B 有这个目录)。
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "contract"))
import dsl as DS  # noqa: E402


class 拒绝(Exception):
    """网关拒绝执行。**这是一个正常结果,不是异常情况** ——
    Agent 会收到它并在剩余合法范围内改方案(§12.2)。"""

    def __init__(self, code, 给模型看的, 给人看的, 建议=""):
        self.code = code
        # ⚠️ **两套文案是故意的。**
        # 给模型看的那句不许包含它无权知道的东西:
        # 「那个目录属于项目 B」会泄露项目 B 有这个目录。
        # 给人看的那句进审计和 Trace,可以写全。
        self.给模型看的 = 给模型看的
        self.给人看的 = 给人看的
        self.建议 = 建议
        super().__init__(f"{code}: {给人看的}")


def 参数摘要(参数):
    """规范化之后的哈希。**批准绑定的是这个,不是「这个工具」**(§12.2)。

    规范化 = 键排序 + 紧凑分隔符。少了它,`{"a":1,"b":2}` 和 `{"b":2,"a":1}`
    会算出两个摘要 —— 于是一次合法的重试会被判成「参数变了,批准失效」,
    而人完全看不出为什么。
    """
    return "sha256:" + hashlib.sha256(
        json.dumps(参数, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def 实际参数(契约, 参数):
    """模型给的 + 服务端绑定的 = **真正要执行的那一份**。"""
    出 = dict(参数 or {})
    出.update(契约.get("server_bound_arguments") or {})
    return 出


def 执行参数摘要(契约, 参数):
    """**批准绑定用的摘要,只有这一个出口。**

    ⚠️ 这个函数存在的理由是一个真漏:原来摘要在两处各算一遍 ——
    网关按 **实参**(含服务端绑定的 `root`)算,而 Agent 循环递给审批查询的是
    **模型给的那份**(不含 root)。两边各自都对,但它们算的不是同一个东西,
    结果是**一条合法的批准永远匹配不上**。
    而这种坏法在测试里的表现是「模型被多调了一次」—— 完全指不到原因。
    
    摘要必须按**真正要执行的那份参数**算,因为那才是给审批人看的东西:
    批准绑定的是「往 /out 写这个内容」,不是「模型说它想写」。
    """
    return 参数摘要(实际参数(契约, 参数))


# ── 极简 JSON Schema 校验(只支持契约里用到的那些)────────────────────
#
# 为什么不装一个 jsonschema 库:这里**故意只支持已登记的关键字**。
# 一个能吃下任意 Schema 的校验器会让人往工具契约里写越来越复杂的 Schema,
# 而复杂的 Schema 里那些「模型该填什么」就没人读得懂了 —— 而模型也读不懂。
_支持的关键字 = {"type", "properties", "required", "additionalProperties",
                "enum", "minLength", "maxLength", "minimum", "maximum",
                "items", "minItems", "maxItems", "description"}
_类型 = {"object": dict, "array": (list, tuple), "string": str,
        "number": (int, float), "integer": int, "boolean": bool, "null": type(None)}


def 校验Schema(值, schema, 路="") -> list:
    """返回错误清单(空 = 过)。**认不出的关键字当场报**,不静默忽略 ——
    一个被静默忽略的 `required` 和一个生效了的 `required` 长得一模一样。"""
    错 = []
    野 = set(schema) - _支持的关键字
    if 野:
        return [f"{路 or '根'}:工具契约的 Schema 用了这个校验器不支持的关键字 "
                f"{sorted(野)} —— **不静默忽略**:被忽略的约束和生效的约束长得一样"]
    t = schema.get("type")
    if t:
        期 = _类型.get(t)
        if 期 is None:
            return [f"{路 or '根'}:认不出的 type {t!r}"]
        # ⚠️ bool 是 int 的子类:`isinstance(True, int)` 为真。
        # 不排掉的话,一个开关值能通过 number/integer 校验。
        if t in ("number", "integer") and isinstance(值, bool):
            return [f"{路 or '根'}:要 {t},给的是布尔值(**布尔不是数字**)"]
        if not isinstance(值, 期):
            return [f"{路 or '根'}:要 {t},给的是 {type(值).__name__}"]
    if "enum" in schema and 值 not in schema["enum"]:
        错.append(f"{路 or '根'}:只能是 {schema['enum']} 之一,给的是 {值!r}")
    if isinstance(值, str):
        if "minLength" in schema and len(值) < schema["minLength"]:
            错.append(f"{路}:至少 {schema['minLength']} 个字")
        if "maxLength" in schema and len(值) > schema["maxLength"]:
            错.append(f"{路}:最多 {schema['maxLength']} 个字")
    if isinstance(值, (int, float)) and not isinstance(值, bool):
        if "minimum" in schema and 值 < schema["minimum"]:
            错.append(f"{路}:不能小于 {schema['minimum']}")
        if "maximum" in schema and 值 > schema["maximum"]:
            错.append(f"{路}:不能大于 {schema['maximum']}")
    if isinstance(值, dict):
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in 值:
                错.append(f"{路}/{k}:必填")
        # **默认拒绝多余字段。** 契约没写 additionalProperties 时按 False 算 ——
        # 默认放行的话,模型多塞一个 `project_id` 进来就悄悄过了这一关,
        # 而它下一关能不能被挡住取决于别的地方记不记得。
        if not schema.get("additionalProperties", False):
            多 = sorted(set(值) - set(props))
            if 多:
                错.append(f"{路 or '根'}:多了没登记的字段 {多} —— "
                          f"**工具契约默认不接收额外字段**")
        for k, v in 值.items():
            if k in props:
                错 += 校验Schema(v, props[k], f"{路}/{k}")
    if isinstance(值, (list, tuple)):
        if "minItems" in schema and len(值) < schema["minItems"]:
            错.append(f"{路}:至少 {schema['minItems']} 项")
        if "maxItems" in schema and len(值) > schema["maxItems"]:
            错.append(f"{路}:最多 {schema['maxItems']} 项")
        if "items" in schema:
            for i, v in enumerate(值):
                错 += 校验Schema(v, schema["items"], f"{路}/{i}")
    return 错


def 检查契约Schema(schema, 路="") -> list:
    """只看**契约本身**合不合法,不需要任何值。返回错误清单(空 = 过)。

    ## 为什么要有它(2026-10-02 加)

    `校验Schema(值, schema)` 要有一个值才跑得起来 —— 它是**调用时**那道闸。
    于是「这份契约用了校验器不支持的关键字」这件事,
    **一直要等到模型第一次真的调用它那一刻才被发现**:

        界面上保存成功 → 冻结成版本成功 → 绑进 Agent 成功 → 发布成功
        → 模型第一次调用 → 网关报「不支持的关键字」

    而那时报出来的是**「工具调用失败」**,不是「这个 Schema 当初就不该被接受」。
    第三份规格 §8.3 的最后一句说的正是这件事:
    > 「现有网关为有限 Schema 校验实现。首版不能默认任意 JSON Schema 都被支持;
    > **界面必须用真实能力清单校验,不能静默忽略约束。**」

    ## ⚠️ 为什么放在这个文件里,和 `_支持的关键字` 挨着

    **那份清单只能有一份。** 冻结那头自己抄一份的话,
    它迟早和校验器真支持的那份漂开 —— 而漂开的表现就是上面那条链:
    冻结接受了,调用拒绝。
    > **一份被抄成两处的清单,它的两份会在谁都没改它的那天开始不一致。**
    (同一条教训在这个仓库里栽过:前端硬编部署环境、冒烟名单抄第二份。)
    """
    if not isinstance(schema, dict):
        return [f"{路 or '根'}:Schema 要是个对象,给的是 "
                f"{type(schema).__name__}"]
    错 = []
    野 = sorted(set(schema) - _支持的关键字)
    if 野:
        错.append(f"{路 or '根'}:用了这个校验器**不支持**的关键字 {野} —— "
                f"认得的只有 {sorted(_支持的关键字)}。"
                f"**不静默忽略**:被忽略的约束和生效的约束长得一样")
    t = schema.get("type")
    if t is not None and t not in _类型:
        错.append(f"{路 or '根'}:认不出的 type {t!r} —— "
                f"认得的只有 {sorted(_类型)}")
    # `required` 里点名的字段,`properties` 里得有 —— 不然它永远填不上。
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        错.append(f"{路 or '根'}/properties:要是个对象")
        props = None
    req = schema.get("required")
    if req is not None:
        if not isinstance(req, list):
            错.append(f"{路 or '根'}/required:要是个数组")
        elif props is not None:
            缺 = [k for k in req if k not in props]
            if 缺:
                # ⚠️ 这一条不是 JSON Schema 标准要求的,是这里加的。
                # 标准允许 required 点名一个没在 properties 里声明的字段,
                # 而在**工具契约**里那等于「必填一个模型不知道怎么填的参数」——
                # 表现是每次调用都被拒,而契约本身看起来完全正常。
                错.append(f"{路 or '根'}:`required` 点名了 {缺},"
                        f"而 `properties` 里没有它们 —— "
                        f"**那是一个模型不知道怎么填的必填参数**")
    # 递归:子属性和数组项
    for k, v in (props or {}).items():
        错 += 检查契约Schema(v, f"{路}/{k}")
    if "items" in schema:
        错 += 检查契约Schema(schema["items"], f"{路}/items")
    return 错


# ── 对象范围(allowed_scopes)──────────────────────────────────────
#
# 规格 §17.4:「HTTP/MCP/网页读取执行**域名、重定向和最终目标**检查,
# 防止访问未授权内部地址;**文件路径做规范化和允许范围校验**,防路径穿越」。
def _规范路径(p):
    """规范化再比 —— **`a/../../etc` 这种要先算出它到底指哪**。

    ⚠️ 顺序很要紧:**先规范化,后比前缀**。反过来的话
    `允许 /out` + 参数 `/out/../../etc/passwd` 会通过前缀检查。
    """
    return os.path.normpath("/" + str(p).replace("\\", "/")).rstrip("/") or "/"


def 范围内吗(值, 范围):
    """`范围` = {"paths": [...], "hosts": [...], "ids": [...]},只要有一条命中就算。"""
    for 前缀 in 范围.get("paths") or []:
        p, q = _规范路径(值), _规范路径(前缀)
        if p == q or p.startswith(q.rstrip("/") + "/"):
            return True
    for h in 范围.get("hosts") or []:
        m = re.match(r"^[a-z]+://([^/:]+)", str(值), re.I)
        主机 = (m.group(1) if m else str(值)).lower()
        h = h.lower()
        # 允许 `*.example.com` 这种;**不允许裸后缀匹配** ——
        # 否则 `evil-example.com` 会命中 `example.com`。
        if 主机 == h or (h.startswith("*.") and 主机.endswith(h[1:])):
            return True
    if str(值) in (范围.get("ids") or []):
        return True
    return False


def 取交集(*几套):
    """有效权限 = 交集(§13.2、附录 A-6)。

    ⚠️ `paths` 取交集的含义是「**取更窄的那个**」,不是「合并两个列表」——
    合并就是取并集,而那正好是反的:嵌套一层反而权限变大。

    ⚠️ **某一层没声明某个轴 = 它对这个轴没有意见,不收窄**(不是「不授予」)。
    否则每一层都得把所有轴列全,而那种要求在真实配置里只会被绕过。
    兜底在**使用时**:一个从来没被任何层声明过的轴最后是 `[]`,
    而空的轴让 `范围内吗()` 一律返回 False —— **fail closed**。
    """
    出 = {"paths": None, "hosts": None, "ids": None}
    for 套 in 几套:
        if not 套:
            continue
        for k in 出:
            v = 套.get(k)
            if v is None:
                continue
            if 出[k] is None:
                出[k] = list(v)
            else:
                if k == "paths":
                    # 一条路径只有在**两边都覆盖它**时才留下 ——
                    # 用「更深的那一条」代表交集
                    留 = []
                    for a in 出[k]:
                        for b in v:
                            if 范围内吗(a, {"paths": [b]}):
                                留.append(a)
                            elif 范围内吗(b, {"paths": [a]}):
                                留.append(b)
                    出[k] = sorted(set(留))
                else:
                    出[k] = sorted(set(出[k]) & set(v))
    return {k: (v if v is not None else []) for k, v in 出.items()}


# ── 账本(副作用的唯一真相)────────────────────────────────────────
#
# 规格 §17.3:「每次写动作**先登记 intent 和稳定 logical_action_id**,
# 再调用外部系统,收到响应后登记结果。进程在两步之间崩溃时进行**核实**,不盲重放。」
#
# 这个接口刻意做得很小(四个方法),因为测试要能给一份**内存账本**,
# 而 Worker 给的是 `tool_invocations` 表。附录 C.3 对副作用工具的要求是
# 「**独立账本**……真值来源:工具真实写入次数,**独立于 Run 自报**」。
class 内存账本:
    """给夹具测试用。**它和被测的运行时是两份记录** ——
    断言要落在这一份上,不能听运行时自己说「我做了一次」。"""

    def __init__(self):
        self.条目 = {}          # logical_action_id → dict
        self.顺序 = []

    def 查(self, 逻辑动作id):
        return self.条目.get(逻辑动作id)

    def 登记意图(self, 逻辑动作id, *, 工具, 参数摘要, 幂等键):
        if 逻辑动作id in self.条目:
            return False
        self.条目[逻辑动作id] = dict(状态="intent_registered", 工具=工具,
                                   参数摘要=参数摘要, 幂等键=幂等键, 结果=None)
        self.顺序.append(逻辑动作id)
        return True

    def 标已提交(self, 逻辑动作id):
        self.条目[逻辑动作id]["状态"] = "submitted"

    def 登记结果(self, 逻辑动作id, *, 状态, 结果=None, 错误码=None):
        e = self.条目[逻辑动作id]
        e["状态"], e["结果"], e["错误码"] = 状态, 结果, 错误码


# ── 主入口 ─────────────────────────────────────────────────────────
def 执行(请求, *, 工具目录, 有效范围, 批准=None, 账本=None, 适配器=None,
        记事=None, 逻辑动作id=None, 幂等键=None, 谁在调=None, 能查外部状态=None):
    """唯一的门。返回 dict(结果, execution_mode, 复用了吗);拒绝时抛 `拒绝`。

    `请求` = {"name": 工具名, "arguments": {...}}  —— 模型给的原样。
    `工具目录` = {工具名: 工具版本契约}  —— **只有这里面的名字能被执行**。
    `有效范围` = 已经取过交集的对象范围(调用方负责取交集,这里只校验)。
    `批准` = {"参数摘要":..., "批准人":..., "过期了吗": bool} 或 None。
    """
    记事 = 记事 or (lambda 种类, 载荷: None)
    名 = (请求 or {}).get("name")
    参数 = (请求 or {}).get("arguments")
    if 参数 is None:
        参数 = {}

    # ── 闸 ①:名字必须已注册 ──────────────────────────────────────
    契约 = (工具目录 or {}).get(名)
    if 契约 is None:
        记事("tool.rejected", {"name": 名, "code": "TOOL_NOT_REGISTERED"})
        raise 拒绝("TOOL_NOT_REGISTERED",
                 f"没有叫 {名!r} 的工具。可用的是:{sorted(工具目录 or {})}",
                 f"模型请求了一个未注册的工具名 {名!r} —— "
                 f"**不能让它凭一个名字临时发网络请求**(§9.4)",
                 建议="如果这个工具本该存在,去工具目录注册并授权给这个 Agent")

    # ── 闸 ②:服务端绑定参数不许被覆盖(§9.4)。**在 Schema 之前** ──
    # 输出目录、project_id、允许的文档库这些由服务端绑定。
    #
    # ⚠️ **顺序是被测试推出来的。** 原来它排在 Schema 之后,而绑定键本来就不在
    # input_schema 里(那是对的 —— 模型不该看见它们),于是 Schema 那道闸
    # 先把它当「多余字段」拒了,这道闸**几乎永远不会触发**。
    # 两次拒绝都安全,但:
    #   · 报出来的理由是「多了没登记的字段」,而人要知道的是「这个参数由服务端决定」;
    #   · 更要紧的是 **一道只在另一道闸配错时才触发的闸,是一道没被测过的闸**。
    # 这道闸只看**键名**,不需要参数形状合法,所以放最前面没有代价。
    #
    # 判据是「模型**提到**了这个键」,不是「值不一样」——
    # 模型恰好填对了一次也不放行:那意味着下一次它可以填错,
    # 而**「这次值是对的」不是一条安全性质**。
    绑定 = 契约.get("server_bound_arguments") or {}
    抢 = sorted(set(参数) & set(绑定))
    if 抢:
        记事("tool.rejected", {"name": 名, "code": "SERVER_BOUND_OVERRIDE", "键": 抢})
        raise 拒绝("SERVER_BOUND_OVERRIDE",
                 f"{抢} 这几个参数由服务端决定,不接受传入",
                 f"模型试图覆盖服务端绑定参数 {抢} —— "
                 f"**「这次它填对了」不是一条安全性质**",
                 建议="这些键不该出现在工具的 input_schema 里(模型不该看见);"
                      "服务端绑定值在 server_bound_arguments 上")

    # ── 闸 ③:Schema。**在权限之前** ─────────────────────────────
    # 因为权限要按参数里的对象判 —— 参数形状不对的话,
    # 「它要写哪个目录」这个问题本身没有答案。
    错 = 校验Schema(参数, 契约.get("input_schema") or {})
    if 错:
        记事("tool.rejected", {"name": 名, "code": "ARGS_INVALID", "错": 错[:4]})
        raise 拒绝("ARGS_INVALID",
                 f"{名} 的参数不合法:{'; '.join(错[:4])}",
                 f"参数不过 input_schema:{错}",
                 建议="看工具详情里的参数 Schema;必填项和类型都要对得上")
    实参 = 实际参数(契约, 参数)

    # ── 闸 ④:对象范围 ──────────────────────────────────────────
    for 键 in 契约.get("scoped_arguments") or []:
        if 键 not in 实参:
            continue
        if not 范围内吗(实参[键], 有效范围 or {}):
            记事("tool.rejected", {"name": 名, "code": "OUT_OF_SCOPE", "键": 键})
            raise 拒绝("OUT_OF_SCOPE",
                     # ⚠️ 给模型看的那句**不说出它无权知道的东西**:
                     # 「那个目录属于项目 B」会泄露项目 B 有这个目录。
                     f"{键} 指的对象不在这次任务允许的范围内",
                     f"{键}={实参[键]!r} 不在有效范围 {有效范围} 内 —— "
                     f"路径已规范化再比(防 ../ 穿越)",
                     建议="要放宽范围就去 Agent 的「权限与限制」里改,并重新冻结版本")

    # ── 闸 ⑤:确认(§12.2)──────────────────────────────────────
    级 = 契约.get("side_effect_type")
    摘要 = 参数摘要(实参)
    行, 挡 = DS.可以执行吗(
        级,
        有幂等键=bool(幂等键) or 级 == DS.只读,
        有生效的批准=bool(批准 and not 批准.get("过期了吗")
                        and 批准.get("参数摘要") == 摘要),
        能查外部状态=bool(能查外部状态 if 能查外部状态 is not None
                       else (契约.get("external_status_lookup") or {}).get("supported")),
    )
    if not 行:
        # 批准存在但摘要对不上 —— 这是「批准 A 却执行 B」,要单独说清
        if 批准 and 批准.get("参数摘要") != 摘要:
            记事("tool.rejected", {"name": 名, "code": "APPROVAL_MISMATCH"})
            raise 拒绝("APPROVAL_MISMATCH",
                     "这次的参数和被批准的那次不一样,需要重新申请",
                     f"批准绑定的摘要是 {批准.get('参数摘要')},这次是 {摘要} —— "
                     f"**批准 A 之后改成 B,旧批准失效**(§12.2)",
                     建议="重新发起一次人工确认;不要改参数复用旧批准")
        if 批准 and 批准.get("过期了吗"):
            记事("tool.rejected", {"name": 名, "code": "APPROVAL_EXPIRED"})
            raise 拒绝("APPROVAL_EXPIRED", "那条批准已经过期了,需要重新申请",
                     "批准已过期 —— **过期时间在点批准的那一刻比,不是建请求的时候**",
                     建议="重新申请确认")
        记事("tool.rejected", {"name": 名, "code": "CONFIRMATION_REQUIRED",
                             "挡": 挡})
        raise 拒绝("CONFIRMATION_REQUIRED",
                 f"这个动作需要先满足:{'; '.join(挡)}",
                 f"副作用级别 {级} 的前置条件没满足:{挡}",
                 建议="不可逆写入要有幂等键 + 当前仍然有效的人工批准 + "
                      "工具声明了外部状态查询能力")

    # ── 闸 ⑥:幂等 / 账本(§17.3)────────────────────────────────
    if 级 != DS.只读:
        if 账本 is None:
            raise 拒绝("LEDGER_REQUIRED", "这个动作要记账本,但没有账本",
                     "**有副作用的调用必须有账本** —— "
                     "没有账本就无法在崩溃后核实它做了没有",
                     建议="调用方要传 账本")
        动作id = 逻辑动作id or f"{名}:{摘要}"
        老 = 账本.查(动作id)
        if 老:
            if 老["参数摘要"] != 摘要:
                raise 拒绝("IDEMPOTENT_KEY_REUSED",
                         "同一个动作键配了不一样的参数",
                         f"逻辑动作 {动作id} 已登记过,但参数摘要不同 —— "
                         f"**相同键不同参数返回 409**(§17.1)",
                         建议="换一个动作键,或者确认是不是重复提交")
            if 老["状态"] == "succeeded":
                # **已经做过了** —— 复用结果,不再调外部
                记事("tool.reused", {"name": 名, "logical_action_id": 动作id})
                return {"结果": 老["结果"], "execution_mode": "reused",
                        "复用了吗": True, "logical_action_id": 动作id}
            if 老["状态"] in ("submitted", "needs_verification"):
                # **提交了但没收到响应** —— 去核实,不重发(§17.3)
                记事("tool.needs_verification", {"name": 名,
                                               "logical_action_id": 动作id})
                raise 拒绝("NEEDS_VERIFICATION",
                         "上一次这个动作提交了但结果不明,要先核实",
                         f"逻辑动作 {动作id} 停在 {老['状态']} —— "
                         f"**禁止自动重复不可逆动作**(§19.3);先查外部状态",
                         建议="调 /execution-runs/{id}/reconcile 去查真实外部状态")
        else:
            账本.登记意图(动作id, 工具=名, 参数摘要=摘要, 幂等键=幂等键)
        账本.标已提交(动作id)
    else:
        动作id = None

    # ── 真的调 ───────────────────────────────────────────────────
    fn = (适配器 or {}).get(契约.get("adapter")) or (适配器 or {}).get(名)
    if fn is None:
        if 动作id:
            账本.登记结果(动作id, 状态="failed", 错误码="ADAPTER_MISSING")
        raise 拒绝("ADAPTER_MISSING", f"{名} 没有可用的适配器",
                 f"工具 {名} 的 adapter={契约.get('adapter')!r} 没接 —— "
                 f"**缺适配器要报出来**,不能当成这一步不需要做",
                 建议="接上适配器,或者先把这个工具停用")
    记事("tool.started", {"name": 名, "参数摘要": 摘要,
                        "logical_action_id": 动作id})
    try:
        r = fn(实参)
    except Exception as e:
        if 动作id:
            # ⚠️ **抛异常不等于外部没做事。** 标「待核实」,不标失败。
            账本.登记结果(动作id, 状态="needs_verification",
                       错误码=type(e).__name__)
        记事("tool.error", {"name": 名, "错": str(e)[:120],
                          "为什么是待核实": "**HTTP 超时不代表对方没做事**(§8)"})
        raise 拒绝("TOOL_ERROR", f"{名} 执行出错了,结果待核实",
                 f"适配器抛了 {type(e).__name__}:{e} —— "
                 f"**已标待核实,不自动重试**",
                 建议="先核实外部状态再决定要不要重试")
    if 动作id:
        账本.登记结果(动作id, 状态="succeeded", 结果=r)
    记事("tool.succeeded", {"name": 名, "logical_action_id": 动作id,
                          "execution_mode": (r or {}).get("execution_mode")})
    return {"结果": r, "execution_mode": (r or {}).get("execution_mode"),
            "复用了吗": False, "logical_action_id": 动作id}
