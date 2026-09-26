#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""落点表 —— **规格 §16.1 那九个组件,各自落在哪个文件里,以及落了没有**。

## 为什么要有这张表

规格 §16.1 给了一张九行的组件职责表(Workflow Editor / Definition Validator /
Tool Gateway / Run Coordinator ……),每行还写了「边界」。这是一份很好的架构描述,
而架构描述有一个众所周知的毛病:**它不会告诉你哪几行还只是描述。**

这份规格自己也一直在防这件事。§20 最后一句:「交付报告逐项写
『**已实现且验证 / 已实现未验证 / 未实现**』,禁止用『所有页面都有了』代替完整功能验收」。
附录 D.1 每一行末尾都有一栏「已验证吗」,九行全是「未验」。

所以这张表把那句话变成可执行的:每个组件登记**落点**(哪个文件、哪个符号)
和 `已落地`。检查会去**真的翻那个文件**看符号在不在 ——

  · 标了已落地而文件/符号不存在 → **红**。这拦的是「我以为我写了」。
  · 还没落地的,数量有个**写死的上限**,只许降不许涨。

## 为什么上限要写死成数字

写成 `len([未落地的])` 就不是棘轮,是装饰 —— 新增一个未落地的组件,
上限跟着涨,检查照样绿。这个错法在这个项目里栽过一次,所以这里写死。

**每落地一个组件,把 已落地 改 True 并把下面那个数减一。** 改那个数会在 review 里被看见。
"""
import os

_根 = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))   # 仓库根


def C(名, 中文, 职责, 边界, 落点, 已落地, 阶段):
    return dict(名=名, 中文=中文, 职责=职责, 边界=边界, 落点=落点,
                已落地=bool(已落地), 阶段=阶段)


# 阶段名对齐规格 §18 那张表的第一列
契约扩展 = "契约扩展"
最小链 = "Workflow 最小链"
控制流 = "控制流"
AGENT链 = "Agent 最小链"
人工恢复 = "人工与恢复"
混合发布 = "混合与发布"
生产化 = "生产化"

组件表 = [
    C("Workflow Editor", "流程画布编辑器",
      "React Flow 画布、节点表单、引用选择、Diff 和校验展示",
      "**只编辑定义,不执行生产任务**",
      "apps/web/app.js::编排画布", False, 最小链),

    C("Agent Editor", "Agent 配置编辑器",
      "模型、目标、工具、上下文、限制、输出表单",
      "**不保存模型凭证,也不自行执行工具**",
      "apps/web/app.js::Agent配置", False, AGENT链),

    C("Definition Validator", "定义校验器",
      "校验图、Schema、变量可用性、依赖与权限",
      "**服务端权威**;前端可用同源生成的 Schema 提速,但不代替它",
      "services/api/app/runtime/validator.py::校验", False, 最小链),

    C("Definition Compiler", "定义编译器",
      "把允许的版本化定义编译成可执行图和节点配置",
      "**不把用户文本当 Python/JS eval**;模型不生成可执行后端代码",
      "services/api/app/runtime/compiler.py::编译", False, 最小链),

    C("Workflow Runner", "流程执行器",
      "调度预设路径、控制流、节点状态和检查点",
      "通过统一 NodeRunner / Tool Gateway 调用能力",
      "services/api/app/runtime/runner.py::推进", False, 最小链),

    C("Agent Runtime", "Agent 运行时",
      "组装上下文、模型回合、解释合法工具请求、检查终止",
      "**不绕过 Tool Gateway;不把模型输出当已执行**",
      "services/api/app/runtime/agent_loop.py::跑一轮", False, AGENT链),

    C("Tool Gateway", "工具网关",
      "Schema、当前权限、确认、幂等、连接与错误映射",
      "**所有 Workflow/Agent 工具调用的唯一执行入口**",
      "services/api/app/runtime/tool_gateway.py::执行", False, AGENT链),

    C("Run Coordinator", "运行协调器",
      "创建、排队、租约、人工等待、恢复、取消、事件",
      "队列可重复投递;**不重复实现节点图调度** —— "
      "一个 Run 只能有一个权威状态驱动者(§16.1)",
      "services/api/app/runtime/coordinator.py::受理", False, 最小链),

    C("Evaluation Adapter", "评测适配器",
      "执行测试输入、收集真实结果和评分",
      "复用原评测中心,**不把 mock 和 live 混在一份报告里**",
      "services/api/app/runtime/eval_adapter.py::跑一题", False, 混合发布),
]

# **写死的欠账上限。** 现在 9 个全未落地(契约阶段本该如此)。
# 每落地一个就减一。⚠️ 不许写成 len(...) —— 见模块开头。
未落地组件上限 = 9

_按名 = {c["名"]: c for c in 组件表}


def 找(名):
    if 名 not in _按名:
        raise KeyError(f"没有这个组件:{名} —— 现有 {list(_按名)}")
    return _按名[名]


def 落点核对():
    """标了「已落地」的,**真的去翻那个文件**。返回问题清单。

    判据故意只查「文件里有没有这个符号」,不查它对不对 ——
    对不对是测试的事。这一条防的是另一种错:**声明落地了但那个文件根本不存在**,
    或者符号名在某次重构里被改掉而这张表没跟上。
    那种错不会让任何测试变红,它只会让这张表慢慢变成一份过期的地图。
    """
    坏 = []
    for c in 组件表:
        if not c["已落地"]:
            continue
        路, _, 符号 = c["落点"].partition("::")
        f = os.path.join(_根, 路)
        if not os.path.exists(f):
            坏.append(f"{c['名']} 标了已落地,但 {路} 不存在")
            continue
        if 符号 and 符号 not in open(f, encoding="utf-8").read():
            坏.append(f"{c['名']} 标了已落地,但 {路} 里找不到 `{符号}`")
    return 坏


def 进度():
    """给 README 和交付报告用。**三档,不是两档**(§20)。"""
    return dict(
        总数=len(组件表),
        已落地=[c["名"] for c in 组件表 if c["已落地"]],
        未落地=[c["名"] for c in 组件表 if not c["已落地"]],
        按阶段={阶段: [c["名"] for c in 组件表 if c["阶段"] == 阶段]
                for 阶段 in (契约扩展, 最小链, 控制流, AGENT链, 人工恢复,
                            混合发布, 生产化)
                if any(c["阶段"] == 阶段 for c in 组件表)},
    )
