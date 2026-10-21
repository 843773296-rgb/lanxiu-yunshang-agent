#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订单列表只给当前这一页取明细 · 检查(10-21)。

原来 `order_list` 对**全部**订单各查一次明细(26560 张 → 两万多次查询)、最后只显示 100 张:一页要 17 秒,
后台订单页和页面冒烟都被它拖住 —— 冒烟限时内翻不完 5 页,报成「找不到有确认书的单」,看着像缺数据。
真调 `server.order_list`,数它查了几次 `ordr_item`:不许超过这一页的张数。
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
咬合 = [("明细又对全部订单各查一次", "明细只给这一页取:查 ordr_item 的次数不超过这一页的张数")]
import server as S
真 = S.rows; 计 = [0]
def 数(sql, *a):
    if "FROM ordr_item" in sql: 计[0] += 1
    return 真(sql, *a)
S.rows = 数
try:
    r = S.order_list({"per": ["20"], "page": ["1"]})
finally:
    S.rows = 真
坏 = []
ok = len(r["rows"]) == 20 and 计[0] <= 20 and all("items" in x for x in r["rows"])
print(f"  {'✅' if ok else '❌'} 明细只给这一页取:查 ordr_item 的次数不超过这一页的张数" + ("" if ok else f"  查了 {计[0]} 次 / 这一页 {len(r['rows'])} 张"))
ok2 = r["total"] > 20 and all(x.get("advisor") is not None or not x.get("advisor_no") for x in r["rows"])
print(f"  {'✅' if ok2 else '❌'} 这一页照样带着明细和顾问名(总数 {r['total']})")
if not (ok and ok2):
    print("\033[31m❌ 订单列表又在给全部订单取明细\033[0m"); sys.exit(1)
print(f"\033[32m✅ 订单列表:只给当前页取明细(查了 {计[0]} 次 / 一页 20 张,共 {r['total']} 张)\033[0m")
