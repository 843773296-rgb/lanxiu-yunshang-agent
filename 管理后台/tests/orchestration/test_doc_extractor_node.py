#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档提取器(11-12,照 Dify「文档提取器」;用户 10-26 拍「workflow 直接复刻 dify」)。

## 判据(期望文字是手写的;文件读取用一个内存里的假适配器,形状和 Worker 的 document 适配器一样)

  ① 一个文件编号 → 文本是那段文字、文件名是那个名字;也认上传接口返回的那种对象(带 id)
  ② 一组编号 → 文本 / 文件名都是列表、顺序和给进来的一致
  ③ 取不了 → 这一步失败、码对、结束没跑(不给空串):
     格式取不了(.pdf)/ 没通过上传校验 / 找不到(含别的项目的编号)/ UTF-8 解不开 / 空文件 /
     不是文件引用 / 空列表 / 超过一步能读的份数 / 存储读不到 / 运行环境没接文件读取
  ④ 配了失败出口就走失败出口
  ⑤ 检查配置:缺文件、多一项绑定、固定值不是文件引用 —— 各报自己那一个码;取后面那一步的结果照样被支配关系拦
  ⑥ 运行记录里看得到这一步收到的文件编号、交出的文字
  ⑦ 上传那一关收的每一种格式,这一步都能取(上传收了 PDF 而这里没跟上时,这条红 —— 运行时照样是明确失败)
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "knowledge"))
import compiler as CP  # noqa: E402
import runner as RN  # noqa: E402
import validator as V  # noqa: E402
import 文档提取 as DE  # noqa: E402
import upload_rules as UR  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:300] if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)
    if n == 0:
        挂.append(名 + "(样本量 0)")


出S = {"type": "object", "properties": {"t": {}, "n": {}}, "required": ["t"], "additionalProperties": False}

# 假的上传库:编号 → 记录(和 Worker 的 _文档 适配器返回同一个形状;别的项目的编号它返回 None)
库 = {
    "up_a": {"id": "up_a", "file_name": "量体须知.md", "status": "已校验", "字节": "# 量体须知\n肩宽量两肩点之间。".encode("utf-8")},
    "up_b": {"id": "up_b", "file_name": "面料说明.txt", "status": "已校验", "字节": "香云纱:夏季,透气。".encode("utf-8")},
    "up_pdf": {"id": "up_pdf", "file_name": "报价.pdf", "status": "已校验", "字节": b"%PDF-1.4"},
    "up_wait": {"id": "up_wait", "file_name": "草稿.md", "status": "已上传", "字节": None},
    "up_bad": {"id": "up_bad", "file_name": "旧资料.txt", "status": "已校验", "字节": "旧资料".encode("gbk")},
    "up_blank": {"id": "up_blank", "file_name": "空.md", "status": "已校验", "字节": b"  \n\n "},
    "up_lost": {"id": "up_lost", "file_name": "丢了.md", "status": "已校验", "字节": None},
}
读过 = []


def 假读(号):
    读过.append(号)
    return 库.get(号)


def 图(绑=None, 失败出口=False):
    绑 = {"文件": {"source": "input", "pointer": "/文件"}} if 绑 is None else 绑
    节 = [
        {"id": "start", "type": "start", "config": {"input_schema": {"type": "object", "properties": {"文件": {}}, "required": ["文件"]}}},
        {"id": "doc", "type": "doc_extractor", "config": {"bindings": 绑, **({"failure_policy": "branch"} if 失败出口 else {})}},
        {"id": "end", "type": "end", "config": {"output_schema": 出S, "bindings": {
            "t": {"source": "node", "node_id": "doc", "pointer": "/文本"}, "n": {"source": "node", "node_id": "doc", "pointer": "/文件名"}}}}]
    边 = [{"source": "start", "target": "doc", "port": "success"}, {"source": "doc", "target": "end", "port": "success"}]
    if 失败出口:
        节.append({"id": "end2", "type": "end", "config": {"output_schema": 出S, "bindings": {"t": {"source": "constant", "value": "转人工"}}}})
        边.append({"source": "doc", "target": "end2", "port": "error"})
    return {"definition_schema_version": "1", "kind": "workflow", "output_schema": 出S, "nodes": 节, "edges": 边}


def 跑(g, 文件, 适配器=None):
    return RN.跑一张图(CP.编译(g, 依赖存在=lambda 种类, i: True), {"文件": 文件},
                    适配器={"document": 假读} if 适配器 is None else 适配器, run_id="r")


码 = lambda g: sorted(p["code"] for p in V.校验(g, 依赖存在=lambda 种类, i: True) if p["级别"] == V.阻断)
步 = lambda r: {s["node_id"]: s for s in r["步骤"]}

print("▸ ① 一个文件")
r = 跑(图(), "up_a")
d = 步(r)["doc"]
ck("取出原文、文件名", r["执行状态"] == "succeeded" and r["输出"] == {"t": "# 量体须知\n肩宽量两肩点之间。", "n": "量体须知.md"}, 1, (r["执行状态"], r["输出"], d.get("error_detail")))
ck("没调模型", r["用量"]["模型调用"] == 0, 1, r["用量"])
ck("⑥ 运行记录:收到的文件编号在 input、文字在 output", d.get("input") == {"文件": ["up_a"]} and str((d.get("output") or {}).get("文本")).startswith("# 量体须知"), 1, d)
r = 跑(图(), {"id": "up_b", "file_name": "面料说明.txt", "能引用吗": True})
ck("认上传接口返回的那种对象(带 id)", r["输出"] == {"t": "香云纱:夏季,透气。", "n": "面料说明.txt"}, 1, r["输出"])

print("▸ ② 一组文件")
r = 跑(图(), ["up_b", "up_a"])
ck("文本 / 文件名都是列表,顺序和给进来的一致", r["输出"] == {"t": ["香云纱:夏季,透气。", "# 量体须知\n肩宽量两肩点之间。"], "n": ["面料说明.txt", "量体须知.md"]}, 1, r["输出"])

print("▸ ③ 取不了就失败,不给空串")
for 名, 文件, 期 in [
        ("PDF(上传那关现在根本不收,这里也取不了)", "up_pdf", "DOC_FORMAT_UNSUPPORTED"),
        ("没通过上传校验(还是「已上传」)", "up_wait", "DOC_NOT_VERIFIED"),
        ("找不到 / 别的项目的编号", "up_其他项目", "DOC_NOT_FOUND"),
        ("不是 UTF-8(不退回 GBK 去猜)", "up_bad", "DOC_DECODE_FAILED"),
        ("只有空白", "up_blank", "DOC_EMPTY"),
        ("存储里读不到", "up_lost", "DOC_READ_FAILED"),
        ("给的不是文件引用(一个数字)", 42, "DOC_BAD_REF"),
        ("对象里没有 id", {"file_name": "x.md"}, "DOC_BAD_REF"),
        ("空列表", [], "DOC_NO_FILE"),
        ("一组里有一个取不了 → 整步失败(不交出缺一份的列表)", ["up_a", "up_pdf"], "DOC_FORMAT_UNSUPPORTED"),
        (f"超过一步能读的 {DE.最多几份} 份", ["up_a"] * (DE.最多几份 + 1), "DOC_TOO_MANY")]:
    r = 跑(图(), 文件)
    s = 步(r)
    ck(f"{名} → {期}、整条失败、结束没跑", r["执行状态"] == "failed" and s["doc"].get("error_code") == 期
       and s["end"]["status"] == "skipped" and "output" not in s["doc"], 1,
       (r["执行状态"], s["doc"].get("error_code"), s["doc"].get("error_detail")))
读过.clear()
跑(图(), ["up_a"] * (DE.最多几份 + 1))
ck("超过份数时一份都不读(先数再读)", 读过 == [], 1, 读过)
r = 跑(图(), "up_a", 适配器={})
ck("运行环境没接文件读取 → NO_ADAPTER(说清不是流程配错)", 步(r)["doc"].get("error_code") == "NO_ADAPTER", 1, 步(r)["doc"])
r = RN.跑一张图(CP.编译(图(), 依赖存在=lambda 种类, i: True), {"别的": 1}, 适配器={"document": 假读}, run_id="r")
ck("开始节点必填的文件没给 → 开始那一步就拦(INPUT_MISSING),一份都没读", 步(r)["start"].get("error_code") == "INPUT_MISSING", 1, 步(r)["start"])

print("▸ ④ 失败出口")
r = 跑(图(失败出口=True), "up_pdf")
s = 步(r)
ck("配了失败出口:走「转人工」那个结束", s["doc"]["status"] == "failed" and s["end2"]["status"] == "succeeded"
   and s["end"]["status"] == "skipped" and r["输出"] == {"t": "转人工"}, 1, {k: v["status"] for k, v in s.items()})
ck("失败那一步的运行记录里有收到的文件编号", s["doc"].get("input") == {"文件": ["up_pdf"]}, 1, s["doc"].get("input"))

print("▸ ⑤ 检查配置")
ck("正常那张图:没有阻断", 码(图()) == [], 1, 码(图()))
for 名, g, 期 in [
        ("「用到的数据」空着 → 必填缺失", 图(绑={}), ["NODE_MISSING_CONFIG"]),
        ("绑定里没有「文件」只有别的", 图(绑={"f": {"source": "input", "pointer": "/文件"}}), ["DOC_EXTRA_BINDING", "DOC_NO_INPUT"]),
        ("多绑了一项", 图(绑={"文件": {"source": "input", "pointer": "/文件"}, "x": {"source": "input", "pointer": "/文件"}}), ["DOC_EXTRA_BINDING"]),
        ("固定值不是文件引用", 图(绑={"文件": {"source": "constant", "value": 7}}), ["DOC_BAD_REF"]),
        ("固定值是空列表", 图(绑={"文件": {"source": "constant", "value": []}}), ["DOC_NO_FILE"]),
        ("填了不适用的超时(这一步不发外部调用)", 图(), None)]:
    if 期 is None:
        g["nodes"][1]["config"]["max_retries"] = 2
        期 = ["NODE_INAPPLICABLE_FIELD"]
    ck(f"{名} → {期}", 码(g) == 期, 1, 码(g))
ck("固定值是合法编号:不拦(在不在库里是运行时的事)", 码(图(绑={"文件": {"source": "constant", "value": "up_a"}})) == [], 1)
g = 图(绑={"文件": {"source": "node", "node_id": "end", "pointer": "/x"}})
ck("文件取的是后面那一步的结果 → BIND_MAYBE_MISSING", "BIND_MAYBE_MISSING" in 码(g), 1, 码(g))

print("▸ ⑦ 上传那一关收的格式,这一步都能取")
上传收 = tuple(UR.支持的后缀())
ck(f"上传收 {上传收} ⊆ 这一步能取 {DE.能提取的后缀}", bool(上传收) and set(上传收) <= set(DE.能提取的后缀), len(上传收),
   f"上传收了而这里取不了:{sorted(set(上传收) - set(DE.能提取的后缀))}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
for x in 挂:
    print(f"   · {x}")
sys.exit(1 if 挂 else 0)
