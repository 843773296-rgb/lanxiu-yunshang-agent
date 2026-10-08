#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询改写 —— **零 IO、不调模型**。业务 2026-10-08 拍的「调模型改写」。

调模型那一步真不真跑得起来,由 `make test-live` / 手动验;
这一份验的是**它周围那些不该出错的东西**:

   ① `temperature=0` —— 拍板时我提过「改写结果不稳定」是这个方案的缺点,
      而它是**用结构拦的**,不是写在注释里
   ② 空改写**不许当结果** —— 「模型给了空串」和「改写成空」要分得开
   ③ 失败**抛**,不自己降级 —— 降级是调用方的决定(它要把这件事写进链路)
   ④ 每条出口都接记录仪
   ⑤ 检索链里:**「改写失败」和「没做改写」用不同的说明文字**
"""
import os
import re
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_k = os.path.join(_根, "services", "api", "app", "knowledge")
sys.path.insert(0, _k)

G, R, D = "\033[32m", "\033[31m", "\033[0m"
过, 挂 = 0, 0


def ck(说, ok, 附=""):
    global 过, 挂
    if ok:
        过 += 1
        print(f"  {G}✅{D} {说}  {附}")
    else:
        挂 += 1
        print(f"  {R}❌{D} {说}  {附}")


源 = open(os.path.join(_k, "rewriter.py"), encoding="utf-8").read()
检索源 = open(os.path.join(_k, "retrieval.py"), encoding="utf-8").read()

print("=" * 92)
print("查询改写 · 周围那些不该出错的东西(零 IO)")
print("=" * 92)

print("\n▸ ① 稳定性是用结构拦的,不是写在注释里")
ck("🔑 请求体里 `temperature` 明确设成 0 —— 拍板时我提过"
   "「改写结果不稳定」是这个方案的缺点,它要有个落点",
   re.search(r'"temperature":\s*0\b', 源) is not None)
ck("而且模块文档写清了 temperature=0 **不保证**完全确定,所以还有别的措施",
   "不保证" in 源 and "完全确定" in 源)

print("\n▸ ② 空改写不许当结果")
ck("空的 query 当场抛,并说明「不拿空串当改写结果」",
   "不拿空串当改写结果" in 源)
# ⚠️ 这条判据第一版写成 `re.search(r'_记\(False[^)]*空', 源)` —— **挂了**,
# 而代码是对的:那一行是 `_记(False, 用量=…, 细节={"空": True})`,
# 「空」在 `细节=` 里,中间隔着 `用量=…`,`[^)]*` 跨不过去。
# > 一条「判据发现了真问题」的红,和一条「判据自己写错了」的红,
# > **在那个 ❌ 上长得一模一样** —— 所以红了要先去核代码,别直接改代码迎合判据。
# 改成:看「空的那条 raise」之前两行里有没有 `_记(False`。
_空行 = next(i for i, L in enumerate(源.split("\n")) if "不拿空串当改写结果" in L)
ck("而且空那条也记了记录仪(失败的那些才是以后要查的)",
   any("_记(False" in L for L in 源.split("\n")[max(0, _空行 - 3):_空行]))

print("\n▸ ③ 失败抛,降级交给调用方")
ck("模块里一处都没有「失败就返回原问」(那是调用方的决定)",
   "return 问题" not in 源)
ck("失败一律 `raise 改写失败`", 源.count("raise 改写失败") >= 4,
   f"{源.count('raise 改写失败')} 处")
ck("模块文档写清了为什么和精排不同(精排失败抛、改写失败可降级)",
   "和精排不同" in 源)

print("\n▸ ④ 每条出口都接记录仪")
ck("有 `trace.record`(管理后台那个叫 llmtrace,见 reranker 文件头)",
   "trace.record" in 源)
# 粗数:每个 raise 前面都该有一次 _记
ck("`_记(` 的次数不少于 `raise 改写失败` 的次数",
   源.count("_记(") >= 源.count("raise 改写失败"),
   f"_记 {源.count('_记(')} 次 / raise {源.count('raise 改写失败')} 次")

print("\n▸ ⑤ 检索链:「改写失败」和「没做改写」要分得开")
ck("🔑 改写失败时 `改写` 仍是 None,**而说明里写明「没跑成」** —— "
   "否则它和「这一版没做」长得一模一样",
   "改写没跑成" in 检索源 and "这不是「改写认为原问最好」" in 检索源)
ck("成功时 `改写` 是模型给的那句话(不再恒为 None)",
   "改写=(改写后 if 改写了吗 else None)" in 检索源)
ck("算向量用的是**改写后**的查询(否则改写白做)",
   re.search(r'EMB\.算\(\[改写后\]', 检索源) is not None)
ck("原问一直带着(返回里 `原问` 和 `改写` 并列,能对照)",
   "原问=问题" in 检索源)
ck("改写那一步炸了也不让整条检索挂(except Exception 兜底 + 写进说明)",
   "改写那一步炸了" in 检索源)

print("\n▸ ⑥ 不假装解决的事")
ck("模块文档写清了**不做**多查询 / HyDE,以及为什么",
   "多查询" in 源 and "HyDE" in 源)
ck("也写清了不自己判断「要不要改写」,以及为什么",
   "不自己判断" in 源)

print("\n" + "=" * 92)
if 挂:
    print(f"{R}❌ 过 {过} / 挂 {挂}{D}")
    sys.exit(1)
print(f"{G}✅ 过 {过} / 挂 {挂}{D}")
