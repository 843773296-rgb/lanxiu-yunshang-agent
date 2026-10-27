#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问题分类器(10-27;用户拍录音跟进分三路:有意向 / 没意向 / 说不清交人)。

## 判据(走哪一路是手写的,模型答什么由 mock 那一侧给)

  ① 模型答哪一类就走哪一类的出口,另两路跳过;这一步的结果里有「类别」「理由」
  ② 交给模型的东西里有每个类别的名字和说明,也有分类时要注意的那句话
  ③ 模型答了一个不在类别里的名字 → 这一步失败、不猜最像的;连了「失败」出口就走那条
  ④ 检查配置:少于两类 / 重名 / 没起名 / 某一类没连线 / 连线挂在不存在的类上,各报各的码;正常那张图没有阻断
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


文 = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
三类 = [{"key": "有意向", "说明": "客户问了价格、档期或约了到店"},
        {"key": "没意向", "说明": "客户明确说不需要"},
        {"key": "说不清", "说明": "前两类都不像"}]


def 图(类们=None, 接失败=False):
    类们 = 三类 if 类们 is None else 类们
    nodes = [{"id": "start", "type": "start", "config": {"input_schema": {
                 "type": "object", "properties": {"转写": {"type": "string"}}, "required": ["转写"]}}},
             {"id": "cls", "type": "classifier", "config": {
                 "connection_version_id": "cv1", "classes": 类们, "instruction": "只看客户说的话,别看顾问说的",
                 "bindings": {"录音转写": {"source": "input", "pointer": "/转写"}},
                 **({"failure_policy": "branch"} if 接失败 else {})}}]
    edges = [{"source": "start", "target": "cls", "port": "success"}]
    for j, c in enumerate(类们):
        k = c.get("key")
        nodes.append({"id": f"e{j}", "type": "end", "config": {"output_schema": 文, "bindings": {
            "text": {"source": "constant", "value": f"走了{k}"}}}})
        edges.append({"source": "cls", "target": f"e{j}", "port": "branch", "branch_key": k})
    if 接失败:
        nodes.append({"id": "人工", "type": "end", "config": {"output_schema": 文, "bindings": {
            "text": {"source": "constant", "value": "交人"}}}})
        edges.append({"source": "cls", "target": "人工", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 文, "nodes": nodes, "edges": edges}


def 跑(g, 答):
    看见 = []

    def 模型(cfg, 实参):
        看见.append((cfg, 实参))
        return {"类别": 答, "理由": "她问了下周六的档期", "execution_mode": "mock"}
    r = RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), {"转写": "下周六能来量吗"}, 适配器={"llm": 模型}, run_id="r")
    return r, 看见


print("▸ ① 按答案分路")
for 答, 终 in (("有意向", "e0"), ("没意向", "e1"), ("说不清", "e2")):
    r, _ = 跑(图(), 答)
    步 = {s["node_id"]: s for s in r["步骤"]}
    跳 = sorted(x for x in ("e0", "e1", "e2") if x != 终)
    ck(f"答「{答}」→ 走 {终}、另两路跳过、输出走了{答}",
       r["执行状态"] == "succeeded" and 步[终]["status"] == "succeeded" and r["输出"] == {"text": f"走了{答}"}
       and all(步[x]["status"] == "skipped" for x in 跳) and 步["cls"]["branch_key"] == 答
       and 步["cls"]["output"]["类别"] == 答 and 步["cls"]["output"]["理由"], 1,
       (r["执行状态"], r["输出"], {k: v["status"] for k, v in 步.items()}))
r, 看见 = 跑(图(), "有意向")
ck("模型调用计 1 次", r["用量"]["模型调用"] == 1, 1, r["用量"])

print("▸ ② 交给模型的东西")
cfg, 实参 = 看见[0]
类文 = next((v for k, v in 实参.items() if k.startswith("可选的类别")), "")
ck("每个类别的名字和说明都在,要注意的那句话也在,原始转写也在",
   all(c["key"] in 类文 and c["说明"] in 类文 for c in 三类) and 实参.get("分类时还要注意") == "只看客户说的话,别看顾问说的"
   and 实参.get("录音转写") == "下周六能来量吗", 3, 实参)
ck("结果形状限定成这三个名字之一", cfg["output_schema"]["properties"]["类别"]["enum"] == ["有意向", "没意向", "说不清"]
   and cfg["connection_version_id"] == "cv1", 1, cfg)

print("▸ ③ 答了不在类别里的")
r, _ = 跑(图(), "有点意向")
步 = {s["node_id"]: s for s in r["步骤"]}
ck("没接失败出口:这一步失败、整条失败,三路都没走(不猜最像的)",
   r["执行状态"] == "failed" and 步["cls"]["error_code"] == "CLASSIFY_OUT_OF_SET"
   and all(步[x]["status"] == "skipped" for x in ("e0", "e1", "e2")), 1, (r["执行状态"], {k: v["status"] for k, v in 步.items()}))
r, _ = 跑(图(接失败=True), "有点意向")
ck("接了失败出口:走去交人", r["执行状态"] == "succeeded" and r["输出"] == {"text": "交人"}, 1, (r["执行状态"], r["输出"]))

print("▸ ④ 检查配置")
码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
ck("正常那张图:没有阻断", 码(图()) == [], 1, 码(图()))
ck("只有一类 → 只报 CLASSIFY_TOO_FEW", 码(图([{"key": "有意向"}])) == ["CLASSIFY_TOO_FEW"], 1, 码(图([{"key": "有意向"}])))
g = 图([{"key": "有意向"}, {"key": "有意向"}, {"key": "没意向"}])
ck("重名 → 报 CLASSIFY_DUP", 码(g) == ["CLASSIFY_DUP"], 1, 码(g))
g = 图([{"key": "有意向"}, {"key": "没意向"}, {"key": ""}])
ck("没起名 → 报 CLASSIFY_NO_NAME", "CLASSIFY_NO_NAME" in 码(g), 1, 码(g))
g = 图(); g["edges"] = [e for e in g["edges"] if e.get("branch_key") != "说不清"]
g["nodes"] = [n for n in g["nodes"] if n["id"] != "e2"]
ck("「说不清」没连线 → 只报 CLASSIFY_NO_EDGE", 码(g) == ["CLASSIFY_NO_EDGE"], 1, 码(g))
g = 图(); g["nodes"][1]["config"]["classes"] = 三类[:2]
ck("删了类别线还挂着 → 只报 CLASSIFY_EDGE_NO_CLASS", 码(g) == ["CLASSIFY_EDGE_NO_CLASS"], 1, 码(g))
g = 图(); g["nodes"][1]["config"]["bindings"]["钥"] = {"source": "secret", "name": "k"}
ck("密钥绑进分类器 → 报 BIND_SECRET_INTO_MODEL", "BIND_SECRET_INTO_MODEL" in 码(g), 1, 码(g))

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
