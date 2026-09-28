#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灌一份**价目表快照** —— 注意是「参考价」,不是账单。

## ⚠️ 这是参考价,不是费用

用户 2026-09-28 定的:**计量按 token 算,价格只给参考**。理由在下面的
DeepSeek 那段里很清楚 —— 同样的 token,同一天不同时刻算出来的钱差一倍。

所以这份表算出来的数叫「**参考价**」:
  · token 数是**硬事实**(响应里的 usage,当时才有,过了就没了)
  · 金额是**按标价估的**,不是账单上的数

真账单还会受这些影响,而这里一概不管:
批量折扣、企业协议价、外部账单延迟、DeepSeek 的时段浮动、
数据驻留倍率(`inference_geo: us` 是 1.1x)、Batch API 的 5 折。

> **一个被当成账单用的估算,比没有估算糟。**
> 所以接口和界面上一律写「参考价」,不写「费用」。

## 为什么要快照而不是现价

契约:「计价要用**当时那一版价格的快照**,不用现价回算 ——
否则改一次价目表,历史成本全变了」。
所以这份表带 `effective_at`,而且**改价是新增一版,不是改这一版**。

## ⚠️ DeepSeek 的价随时段浮动 —— 这里取**高峰价**

    deepseek-v4-pro  输入(未命中) $0.66 非高峰 / $1.32 高峰
                     输出         $1.98 非高峰 / $3.96 高峰

高峰是 UTC 周一到周五 01:00–04:00 和 06:00–10:00(中国节假日除外)。
要算准就得知道那一刻算不算高峰,还得有中国节假日表 —— 而我们记的是真实时间戳。

**取高峰价(贵的那一边)是有意的**:取便宜那边会让人低估成本,
而**低估的代价比高估大** —— 高估让人多留预算,低估让人撞上账单。
这件事写进 `unit_prices.备注`,不藏在代码里。

## 价从哪来(2026-09-28 查的)

    Claude    https://platform.claude.com/docs/en/about-claude/pricing
    DeepSeek  https://api-docs.deepseek.com/quick_start/pricing

    python3 tools/seed_pricing.py          # 只报,不写
    python3 tools/seed_pricing.py --做     # 真的写
"""
import argparse
import hashlib
import json
import os
import sys
import uuid

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/api/app", "services/api/app/contract"):
    sys.path.insert(0, os.path.join(根, d))

from sqlalchemy import text

from db import 连接, 事务

查价日 = "2026-09-28"

# ⚠️ **单位是「每 token 多少美元」**,不是「每百万 token」——
# 折账那一步是 `quantity * 单价`,而 quantity 是 token 数。
# 存成每百万的话,那一步要多一次除法,而**那次除法迟早有人漏掉**,
# 算出来的数会大一百万倍 —— 大得离谱反而容易发现,可怕的是有人
# 「顺手」把它改小一千倍去凑一个看起来合理的数。
def 每百万(x):
    return x / 1_000_000


价目 = [
    dict(provider="anthropic", model_id="claude-haiku-4-5-20251001",
         currency="USD", 来源="https://platform.claude.com/docs/en/about-claude/pricing",
         备注="标价。不含:批量 5 折、企业协议价、inference_geo=us 的 1.1x 倍率",
         prices={
             "input_tokens": 每百万(1.0),
             "output_tokens": 每百万(5.0),
             # 5 分钟缓存写。1 小时那档是 $2/MTok,而我们没用 1h 缓存 ——
             # **认不出的档会被报出来**(usage.归一用量),所以少一档不会悄悄算漏
             "cache_creation_input_tokens": 每百万(1.25),
             "cache_read_input_tokens": 每百万(0.10),
         }),
    dict(provider="deepseek", model_id="deepseek-v4-pro",
         currency="USD", 来源="https://api-docs.deepseek.com/quick_start/pricing",
         备注="**取高峰价**(非高峰是一半)。高峰 = UTC 周一至周五 "
              "01:00–04:00 与 06:00–10:00,中国节假日除外。"
              "取贵的那边是有意的:低估的代价比高估大",
         prices={
             "input_tokens": 每百万(1.32),          # 未命中缓存,高峰
             "output_tokens": 每百万(3.96),         # 高峰
             "cache_read_input_tokens": 每百万(0.044),
         }),
    dict(provider="deepseek", model_id="deepseek-flash",
         currency="USD", 来源="https://api-docs.deepseek.com/quick_start/pricing",
         备注="**取高峰价**(非高峰是一半)。同 deepseek-v4-pro 的时段规则",
         prices={
             "input_tokens": 每百万(0.3),
             "output_tokens": 每百万(1.2),
             "cache_read_input_tokens": 每百万(0.006),
         }),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--做", action="store_true")
    a = ap.parse_args()

    with 连接() as c:
        已有 = {(r["provider"], r["model_id"]): r["id"] for r in c.execute(text(
            "select id, provider, model_id from pricing_versions "
            "where archived_at is null")).mappings()}

    print(f"▸ 价目表快照({查价日} 查的)—— **这是参考价,不是账单**")
    for p in 价目:
        键 = (p["provider"], p["model_id"])
        print(f"\n  {p['provider']} / {p['model_id']}"
              f"{'   ⚠️ 已经有一版了' if 键 in 已有 else ''}")
        for 档, v in sorted(p["prices"].items()):
            print(f"      {档:<30} ${v * 1_000_000:>7.3f} / 百万 token")
        print(f"      备注:{p['备注'][:88]}")

    print("\n⚠️ 算出来的金额叫「**参考价**」,不是费用 —— 真账单还受"
          "批量折扣、协议价、账单延迟、DeepSeek 时段浮动影响,这里一概不管。")
    if not a.做:
        print("\n**这是 dry-run,一行都没写。** 加 `--做` 才真的写")
        return 0

    写了 = 0
    with 事务() as c:
        for p in 价目:
            内容 = json.dumps({"prices": p["prices"], "来源": p["来源"],
                             "备注": p["备注"], "查价日": 查价日},
                            ensure_ascii=False, sort_keys=True)
            h = "sha256:" + hashlib.sha256(内容.encode("utf-8")).hexdigest()
            # ⚠️ **同一份内容不新建一版**(和文档版本一个道理):
            # 每跑一次就多一版的话,`effective_at` 会变成「最后一次跑脚本的时间」,
            # 而它本该是「这个价从什么时候开始生效」。
            重 = c.execute(text("select id from pricing_versions where content_hash=:h"),
                           {"h": h}).scalar()
            if 重:
                print(f"  · {p['model_id']}:内容没变,跳过(复用 {重})")
                continue
            c.execute(text("""
                insert into pricing_versions (id, provider, model_id, unit_prices,
                    currency, effective_at, content_hash, created_at, created_by,
                    updated_at, revision)
                values (:i,:pv,:m, cast(:u as jsonb), :cur, now(), :h, now(),
                        'seed_pricing', now(), 1)"""),
                      {"i": f"pv_{uuid.uuid4().hex[:10]}", "pv": p["provider"],
                       "m": p["model_id"],
                       "u": json.dumps({**p["prices"], "currency": p["currency"],
                                        "来源": p["来源"], "备注": p["备注"],
                                        "查价日": 查价日, "是参考价": True},
                                       ensure_ascii=False),
                       "cur": p["currency"], "h": h})
            写了 += 1
    print(f"\n✅ 新增 {写了} 版价目表快照。"
          f"⚠️ **改价是新增一版,不是改这一版** —— 否则历史成本会跟着变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
