#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给老的 `document_versions` 补上 `source_info.存储` —— **让「不知道」变成「知道」**。

## 为什么要这个脚本

`object_key` 这一列有两个含义(对象存储键 / 仓库内相对路径)。
`b492bd798649` 加了 `source_info` 来说明是哪种,而**老行是 NULL**。
`knowledge/ingest.py` 的 `原文键()` 对 NULL **当场抛,不猜**。

所以在跑这个脚本之前,老那批资料**读不出原文** —— 这是有意的:
读不出来会当场报,而猜错会报「文件不存在」,那时没人会想到是列的含义问题。

## ⚠️ 判据:不按「看起来像」猜,而是**去文件系统核**

  · 仓库根下这个相对路径**存在** → 标「仓库相对路径」
  · 对象存储里这个键**存在**     → 标「对象存储」
  · **两个都在** → 不标,报出来让人看(一个键同时是两种,说明有别的问题)
  · **两个都不在** → 不标,报出来(原文真的丢了,而那不是这个脚本该偷偷决定的事)

「看起来像仓库路径」(比如带 `/` 或以 `.md` 结尾)是**形状**,不是事实 ——
而对象存储的键正好也带 `/` 也以 `.md` 结尾。**用形状猜这件事会全错。**

    python3 tools/backfill_object_keys.py          # 只报,不改
    python3 tools/backfill_object_keys.py --做     # 真的改
"""
import argparse
import json
import os
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/api/app", "services/api/app/contract", "services/api/app/knowledge"):
    sys.path.insert(0, os.path.join(根, d))

from sqlalchemy import text

import ingest as IN
import storage as OS_

# ⚠️ **仓库根从 ingest.py 来,不在这里再算一遍。**
# 第一版两处各算一次,当场就分叉了(那边少数了两层)——
# 而分叉的表现是「文件不存在」,看起来像资料丢了。
仓库根 = IN.仓库根
from db import 连接, 事务


def 判一行(键):
    """返回 (标什么, 为什么)。标什么是 None 表示**不标**。"""
    在仓库 = bool(键) and os.path.isfile(os.path.join(仓库根, 键))
    在存储 = bool(键) and OS_.有吗(键)
    if 在仓库 and 在存储:
        return None, ("**两边都有这个键** —— 一个键同时是两种含义,"
                      "这不是这个脚本该偷偷决定的事")
    if 在仓库:
        return IN.仓库路径标记, f"仓库根下找到了 {键}"
    if 在存储:
        return IN.存储标记, f"对象存储里找到了 {键}"
    return None, ("**两边都找不到** —— 原文真的不在了。"
                  "不标:标了之后读原文会报「文件不存在」,"
                  "而那句话会让人去查存储,根因其实是这一行的原文从来没被存过")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true")
    a = ap.parse_args()
    with 连接() as c:
        rs = c.execute(text("""
            select project_id, id, document_id, object_key, revision, source_info
              from document_versions
             where archived_at is null
             order by created_at
        """)).mappings().all()

    要改, 不改 = [], []
    for r in rs:
        已有 = ((r["source_info"] or {}).get("存储"))
        if 已有:
            continue
        标, 为什么 = 判一行(r["object_key"])
        (要改 if 标 else 不改).append((dict(r), 标, 为什么))

    print(f"▸ 文档版本共 {len(rs)} 行,没标存储的 {len(要改) + len(不改)} 行")
    for r, 标, 为什么 in 要改[:50]:
        print(f"  · {r['id']} v{r['revision']}  → 标「{标}」({为什么})")
    for r, _, 为什么 in 不改:
        print(f"  ⚠️ {r['id']} v{r['revision']}  **不标**:{为什么}")
    if not 要改:
        print("  没有能标的")
        # ⚠️ **有「不标」的就退非 0** —— 它们是要人看的。
        # 退 0 会让这个脚本在有问题的库上也「看起来跑成功了」。
        return 1 if 不改 else 0
    if not a.做:
        print("\n**这是 dry-run,一行都没改。** 加 `--做` 才真的改")
        return 1 if 不改 else 0

    n = 0
    with 事务() as c:
        for r, 标, 为什么 in 要改:
            # ⚠️ 合并进已有的 `source_info`,不覆盖 —— 覆盖会丢掉别人写的字段,
            # 而丢字段不报错。`coalesce` 处理 NULL。
            n += c.execute(text("""
                update document_versions
                   set source_info = coalesce(source_info, '{}'::jsonb)
                                     || cast(:add as jsonb),
                       updated_at = now()
                 where project_id=:p and id=:i
                   and (source_info->>'存储') is null
            """), {"add": json.dumps({"存储": 标, "补标": "backfill_object_keys"},
                                     ensure_ascii=False),
                   "p": r["project_id"], "i": r["id"]}).rowcount
    print(f"\n标了 {n} 行")
    if 不改:
        print(f"⚠️ 还有 {len(不改)} 行**没标**(上面列了)—— 退非 0,它们要人看")
    return 1 if 不改 else 0


if __name__ == "__main__":
    sys.exit(main())
