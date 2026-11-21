#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「标注回复」后台一半(11-21;用户 10-27 拍第 7 条,11-21 拍三条口径)—— 纯函数 + 登记,不碰库不起服务。

  ① 可标注吗:只调知识类只读工具(kb_*)或没调工具 → 能标;ToolSearch / Skill 元工具不算;调过取数 / 写 / 队列类工具 → 不能,原因里点名;
     认不出的工具按实时处理;mcp__ 前缀剥掉再判
  ② 问答与工具:从 span 行取 提问 / 角色 / 回答 / 调过的工具;原文到期的认出来;没有根步骤 → 提问 None
  ③ 工具归属表读的是 backend/domains.py 那一份(不抄);知识类只读 ⊂ knowledge 且全是 kb_ 开头;写工具和队列类不在里面
  ④ 登记:endpoints 七条(权限对)、开关们 有 chat_annotation.switch、main 挂了路由、entities 有表、迁移建了表 + 项目开关列、
     运行详情真调 标注块、POST 真调 可标注吗(规则只有一份)
"""
import json
import os
import re
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
APP = os.path.join(根, "services", "api", "app")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "contract"))
import chat_annotations_api as CA  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:240] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


def 读(*p):
    return open(os.path.join(根, *p), encoding="utf-8").read()


print("▸ ① 可标注吗")
能 = [[], ["kb_read"], ["kb_read", "kb_combo", "ToolSearch", "Skill"], ["mcp__knowledge__kb_size"], ["ToolSearch"]]
不能 = {"get_order": "取数", "get_customer": "取数", "get_stock": "取数", "list_tasks": "取数", "set_piece_ratio": "写",
      "assign_task": "写", "pattern_queue": "队列", "get_review_queue": "队列", "store_report": "统计"}
ck("知识类只读 / 没调工具 / 只有元工具 → 能标,原因 None", all(CA.可标注吗(x) == (True, None) for x in 能), len(能),
   [(x, CA.可标注吗(x)) for x in 能])
坏 = [(t, CA.可标注吗(["kb_read", t])) for t in 不能 if CA.可标注吗(["kb_read", t])[0] or t not in (CA.可标注吗(["kb_read", t])[1] or "")]
ck("混了取数 / 写 / 队列 / 统计工具 → 不能,原因里点名那个工具", not 坏, len(不能), 坏)
可, 因 = CA.可标注吗(["kb_read", "foo_bar", "mcp__x__baz"])
ck("认不出的工具 → 不能,原因说「认不出」并点名(mcp__ 前缀剥掉)", not 可 and "认不出" in 因 and "foo_bar" in 因 and "baz" in 因 and "mcp__" not in 因, 1, 因)
可, 因 = CA.可标注吗(["get_order", "get_order", "foo"])
ck("同一个工具调多次只点名一次;取数和认不出两段都在", not 可 and 因.count("get_order") == 1 and "foo" in 因, 1, 因)

print("\n▸ ② 问答与工具")
行 = lambda stage, parent=None, 入=None, 出=None: {"stage": stage, "parent_span_id": parent,  # noqa: E731
                                              "入": json.dumps(入, ensure_ascii=False) if 入 is not None else None,
                                              "出": json.dumps(出, ensure_ascii=False) if 出 is not None else None}
q = CA.问答与工具([行("invoke_agent 门店顾问", 入={"提问": "香云纱能水洗吗", "角色": "门店顾问"}, 出={"回答": "不能机洗"}),
                 行("chat claude-haiku", "r"), 行("execute_tool kb_read", "r"), 行("execute_tool mcp__k__kb_combo", "r")])
ck("取到 提问 / 角色 / 回答 / 工具们(按出现顺序,带前缀原样留给 可标注吗 去剥)",
   q == {"提问": "香云纱能水洗吗", "角色": "门店顾问", "回答": "不能机洗", "工具们": ["kb_read", "mcp__k__kb_combo"], "原文到期了吗": False}, 1, q)
q = CA.问答与工具([行("invoke_agent 门店顾问", 入={"提问": "x"})])
ck("入里没角色 → 角色从 stage 取;没出 → 回答 None", q["角色"] == "门店顾问" and q["回答"] is None, 1, q)
q = CA.问答与工具([行("invoke_agent 门店顾问", 入={"到期删除": "聊天站原文保留 30 天,已删"}), 行("execute_tool kb_read", "r")])
ck("根步骤原文到期 → 原文到期了吗 True、提问 None、工具照取", q["原文到期了吗"] and q["提问"] is None and q["工具们"] == ["kb_read"], 1, q)
q = CA.问答与工具([行("chat claude"), 行("execute_tool get_order", "r")])
ck("没有 invoke_agent 根步骤 → 提问 None(不是聊天站的一轮)", q["提问"] is None and not q["原文到期了吗"], 1, q)
q = CA.问答与工具([行("invoke_agent a", "父", 入={"提问": "子"}), 行("invoke_agent b", None, 入={"提问": "根"})])
ck("有父步骤的 invoke_agent 不算根(子智能体)", q["提问"] == "根", 1, q)

print("\n▸ ③ 工具归属表")
ck("读的是仓库 backend/domains.py 那一份", CA.领域表来自仓库 is True and len(CA.已知工具) > 80, len(CA.已知工具))
ck("知识类只读全是 kb_ 开头且都在 knowledge 领域里", CA.知识类只读 and all(t.startswith("kb_") and t in CA.领域["knowledge"] for t in CA.知识类只读), len(CA.知识类只读))
ck("knowledge 领域里的写 / 队列类(set_piece_ratio / pattern_queue / get_review_queue)**不在**知识类只读里",
   not ({"set_piece_ratio", "set_grade_diff", "pattern_queue", "get_review_queue", "grading_audit"} & CA.知识类只读), 5)

print("\n▸ ④ 登记")
ep = 读("services", "api", "app", "contract", "endpoints.py")
期 = [('"GET", "/chat-annotations"', "查看有权配置"), ('"GET", "/chat-annotations/active"', "运行评测"),
     ('"POST", "/chat-annotations"', "改 Prompt/知识候选"), ('"PATCH", "/chat-annotations/{id}"', "改 Prompt/知识候选"),
     ('"POST", "/chat-annotations/{id}/archive"', "改 Prompt/知识候选"), ('"PUT", "/chat-annotations/switch"', "改 Prompt/知识候选"),
     ('"POST", "/chat-annotations/{id}/hits"', "运行评测")]
漏 = []


def 登记段(头):
    """这一条 A(...) 的全文:从它的头到下一条 `    A(` 之前(中文说明里有半角括号,不能用「第一个右括号」截)。"""
    m = re.search(r"A\(" + re.escape(头) + r".*?(?=\n    A\(|\n\])", ep, re.S)
    return m.group(0) if m else ""


for 头, 权 in 期:
    if 权 not in 登记段(头):
        漏.append((头, 权))
ck("endpoints 七条都登记了,权限按拍板(列表 / 命中给聊天站那档;建 / 改 / 归档 / 开关要「改 Prompt/知识候选」)", not 漏, len(期), 漏)
ck("PATCH / 归档 带乐观锁;建 / 改 / 归档 / 开关 带审计;命中不审计",
   all("乐观锁=True" in 登记段(h) for h in ('"PATCH", "/chat-annotations/{id}"', '"POST", "/chat-annotations/{id}/archive"'))
   and all("审计=True" in 登记段(h) for h in ('"POST", "/chat-annotations"', '"PUT", "/chat-annotations/switch"', '"PATCH", "/chat-annotations/{id}"'))
   and "审计=True" not in 登记段('"POST", "/chat-annotations/{id}/hits"') and 登记段('"POST", "/chat-annotations/{id}/hits"'), 7)
wf = 读("services", "api", "app", "workflows_api.py")
ck("开关们 登记了 chat_annotation.switch(工作台「开关」那块才看得见)", '"chat_annotation.switch":' in wf, 1)
ca = 读("services", "api", "app", "chat_annotations_api.py")
ck("拨总开关的函数里真写了 _审计(c, me, \"chat_annotation.switch\"", re.search(r"def 拨总开关.*?_审计\(c, me, \"chat_annotation\.switch\"", ca, re.S) is not None, 1)
ck("main.py 挂了路由", "chat_annotations_api as _ANN" in 读("services", "api", "app", "main.py") and "_ANN.router" in 读("services", "api", "app", "main.py"), 1)
en = 读("services", "api", "app", "contract", "entities.py")
ck("entities 有 chat_annotations(项目级)且 projects 多了 chat_annotation_enabled", 'E("chat_annotations"' in en and '"chat_annotation_enabled"' in en, 2)
迁 = [f for f in os.listdir(os.path.join(根, "services", "api", "migrations", "versions")) if f.endswith(".py") and "聊天标注" in f]
迁文 = 读("services", "api", "migrations", "versions", 迁[0]) if 迁 else ""
ck("迁移建了 chat_annotations(project_id + trace_id 唯一)和 projects.chat_annotation_enabled",
   迁 and "op.create_table('chat_annotations'" in 迁文 and "uq_chat_annotations_project_id_trace_id" in 迁文
   and "op.add_column('projects', sa.Column('chat_annotation_enabled'" in 迁文, len(迁) or 1, 迁)
ra = 读("services", "api", "app", "runs_api.py")
ck("运行详情真调 chat_annotations_api.标注块(只给聊天站那一轮)", "from chat_annotations_api import 标注块" in ra and "标注块(c, project_id, trace_id, me, ss)" in ra, 1)
ck("规则只有一份:POST 和 标注块 都调 可标注吗,模块里再没第二处判工具名的 if", ca.count("可标注吗(q[\"工具们\"])") == 2 and ca.count("def 可标注吗") == 1, 2)
sw = 读("tools", "switch_registry_check.py")
ck("开关检查认得 chat_annotation_enabled 这处写开关", "chat_annotation_enabled" in sw, 1)
js = 读("apps", "web", "app.js")
ck("前端:菜单 / 路由 / 调用树页标注块 / 标注回复页 四处都有", all(s in js for s in ('["#/annotations", "标注回复"', 'h === "#/annotations"', "画标注块(d[\"标注\"])", "async function 页_标注回复")), 4)

print()
if 挂:
    print(f"❌ {len(挂)} 条挂了:{挂}")
    sys.exit(1)
print(f"✅ 标注回复 {len(过)} 条全过")
