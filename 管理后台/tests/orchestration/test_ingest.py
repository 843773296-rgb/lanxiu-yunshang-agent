#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收资料的纯逻辑 —— **零 IO、不连库**(所以能跑在 CI 里)。

这一份只测 `knowledge/ingest.py` 里不碰库的那两块:

    检查上传可用()  —— 哪些上传能当资料用,**以及拒的理由说清了没有**
    原文键()       —— `object_key` 是哪种键,**不知道时当场抛而不猜**

写库那一块(`收一份资料`)在 `tests/e2e/test_knowledge_write_flow.py` 里
对着真库跑 —— 它的价值全在「事务边界对不对」,而那件事 mock 不出来。

## 为什么「拒的理由」也要断言

一条只说「不能用」的错误,和没有错误提示对使用的人是一样的 ——
他下一步不知道该干什么。而这三种拒法的下一步**完全不同**:
  · `已上传`   → 去调一次完成接口(还有救)
  · `校验失败` → 重新走一遍上传(这条没救了,终态)
  · `待上传`   → 先把字节传上去
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "knowledge"))

import ingest as IN

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:160]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("▸ ① 只有「已校验」的上传能当资料用")
for st, 该行 in (("已校验", True), ("已上传", False), ("校验失败", False),
              ("待上传", False), ("已放弃", False)):
    行, _ = IN.检查上传可用({"status": st, "verify_detail": {}})
    ck(f"{st} → {'能' if 该行 else '不能'}", 行 == 该行)
ck("没有这条上传 → 不能(而不是抛)", IN.检查上传可用(None)[0] is False)
ck("空字典 → 不能", IN.检查上传可用({})[0] is False)

print("▸ ② 拒的理由要指出**下一步**,三种拒法的下一步不同")
_, 为什么 = IN.检查上传可用({"status": "已上传"})
ck("`已上传` 的理由里说了「先调完成接口」(还有救)", "完成接口" in 为什么, 为什么[:80])
ck("而且点名 §17.1 —— 这条规则有出处,不是我定的", "17.1" in 为什么)
ck("并且说清放行的后果(建索引时才炸,错误指向解析器)",
   "解析器" in 为什么, 为什么[-60:])
_, 为什么 = IN.检查上传可用(
    {"status": "校验失败", "verify_detail": {"没过的规则": ["能按 UTF-8 严格解码"]}})
ck("`校验失败` 的理由里**带上没过的规则**(不是只说「失败了」)",
   "UTF-8" in 为什么, 为什么[:90])
ck("并且说了「重新走一遍上传」(这条是终态,没救)", "重新走" in 为什么)
_, 为什么 = IN.检查上传可用({"status": "校验失败", "verify_detail": None})
ck("`verify_detail` 是 None 也不炸(**报告失败的代码自己不许炸**)",
   "校验没过" in 为什么, 为什么[:60])

print("▸ ③ 原文键:不知道就当场抛,**不猜**")
ck("标了对象存储 → 认出来",
   IN.原文键({"object_key": "p/2026-09/up_x/a.md",
            "source_info": {"存储": IN.存储标记}}) ==
   (IN.存储标记, "p/2026-09/up_x/a.md"))
ck("标了仓库路径 → 认出来",
   IN.原文键({"object_key": "业务决策/x.md",
            "source_info": {"存储": IN.仓库路径标记}})[0] == IN.仓库路径标记)
for 坏 in ({"object_key": "x.md", "source_info": {}},
          {"object_key": "x.md", "source_info": None},
          {"object_key": "x.md"},
          {"object_key": "x.md", "source_info": {"存储": "别的"}}):
    try:
        IN.原文键(坏)
        ck(f"{坏} → 抛", False, "没抛!猜错的表现是「文件不存在」")
    except IN.键的含义不明:
        ck("没标存储的行 → **当场抛**(不退回「当相对路径试一次」)", True)
ck("None 也抛,不返回一个空键", True)
try:
    IN.原文键(None)
    ck("None → 抛", False, "没抛")
except IN.键的含义不明:
    ck("None → 抛", True)
_, 为什么 = IN.存储标记, ""
try:
    IN.原文键({"object_key": "x.md", "source_info": {}})
except IN.键的含义不明 as e:
    为什么 = str(e)
ck("理由里说清「猜对了没人知道,猜错了报的是文件不存在」",
   "文件不存在" in 为什么, 为什么[-70:])
ck("并且指了怎么补(backfill 脚本)", "backfill" in 为什么)

print("▸ ④ 仓库根只有一处定义")
# ⚠️ 第一版这里算了两遍(ingest.py 和 backfill 脚本各一份),**当场就分叉了**:
# ingest 少数了两层 dirname,于是读原文去找 `管理后台/services/业务决策/…`,
# 报出来的是「文件不存在」,看起来像资料丢了。
ck("`仓库根` 是 ingest.py 导出的绝对路径", os.path.isabs(IN.仓库根), IN.仓库根)
ck("它下面真的有 `管理后台/`(证明层数对,不是恰好存在的某个目录)",
   os.path.isdir(os.path.join(IN.仓库根, "管理后台")), IN.仓库根)
_backfill = open(os.path.join(_根, "tools", "backfill_object_keys.py"),
                 encoding="utf-8").read()
ck("backfill 脚本**不自己算**仓库根,而是 `IN.仓库根`",
   "仓库根 = IN.仓库根" in _backfill)
ck("而且它不再有自己那份 dirname 链",
   "仓库根 = os.path.dirname(根)" not in _backfill)

print("▸ ⑤ 两个标记值不许一样(否则「两个含义」又合成一个)")
ck("存储标记 != 仓库路径标记", IN.存储标记 != IN.仓库路径标记,
   f"{IN.存储标记} / {IN.仓库路径标记}")

print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
if 挂:
    for x in 挂:
        print("   挂:", x)
sys.exit(1 if 挂 else 0)
