#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工待办按门店分开(11-21,用户拍:店长只看到、只处理本店的单子)—— 口径模块 runtime/门店范围.py 的纯逻辑自测,期望全部手写。

两件事:① 一张单子归哪个门店(输入 → 材料 → 发起人 → 定不出);② 谁看得到哪些。
另外一条**结构**判据:human_api 三条接口的 SQL 片段(_门店范围SQL)和 看得到吗 口径一致 —— 两边各写一套迟早分叉。
"""
import os
import sys

_这 = os.path.dirname(os.path.abspath(__file__))
根 = os.path.dirname(os.path.dirname(_这))
sys.path.insert(0, os.path.join(根, "services", "api", "app", "runtime"))
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
import 门店范围 as SS  # noqa: E402

过, 挂 = [], []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){'  ' + str(补)[:200] if 补 else ''}")
    (过 if 真 else 挂).append(名)


print("▸ ① 一张单子归哪个门店")
例 = [  # (输入, 材料, 发起人门店, 期望门店, 期望来源里含)
    ({"门店": "SH001", "摘要": "x"}, {"门店": "SH002"}, "SH003", "SH001", "输入"),
    ({"摘要": "x"}, {"门店": "sh002"}, "SH003", "SH002", "材料"),
    ({"摘要": "x"}, {"摘要": "y"}, " sh003 ", "SH003", "发起人"),
    ({"摘要": "x"}, {}, None, None, "定不出"),
    ({"X-Shop": "SH005"}, {}, None, "SH005", "输入"),          # Webhook 请求头那张表合进输入的键
    ({"store_id": "SH006"}, {}, None, "SH006", "输入"),
    ({"门店编号": ""}, {"shop": "SH007"}, None, "SH007", "材料"),   # 输入里门店是空串 → 不算,往下找
    ({"门店": 8}, {}, None, "8", "输入"),                        # 数字也认(转成文本比)
    (None, None, None, None, "定不出"),
]
坏 = []
for 输, 材, 发, 期, 源 in 例:
    门店, 来源 = SS.取门店(输, 材, 发)
    if 门店 != 期 or 源 not in 来源:
        坏.append((输, 材, 发, 门店, 来源))
ck("顺序是 输入 → 材料 → 发起人 → 定不出;键名不分大小写、值去空白统一大写、空串不算", not 坏, len(例), 坏)
ck("认的键:门店 / 门店编号 / store_id / shop_id / X-Shop 这几种,不认「门店名称」这种别的词", SS.取门店({"门店名称": "静安"}, {}, None)[0] is None
   and all(SS.取门店({k: "SH001"}, {}, None)[0] == "SH001" for k in ("门店", "门店编号", "store_id", "shop_id", "X-Shop", "SHOP")), 7)

print("\n▸ ② 谁看得到哪些")
表 = [  # (我的门店, 单子门店, 期望)
    (None, "SH001", True), (None, None, True),          # 不限门店:全看,包括定不出门店的
    ("SH001", "SH001", True), ("sh001", " SH001 ", True),  # 本店(不分大小写、空白)
    ("SH001", "SH002", False),                          # 别的店
    ("SH001", None, False),                             # 定不出门店的单子不给店长
    ("SH001", "", False),
]
坏 = [(a, b, SS.看得到吗(a, b)) for a, b, 期 in 表 if SS.看得到吗(a, b) != 期]
ck("不限门店看全部;登记了门店只看本店;定不出门店的单子只给不限门店的人", not 坏, len(表), 坏)
ck("看不到时说得清为什么(别的店 / 定不出门店)", "SH002" in SS.为什么看不到("SH001", "SH002") and "定不出" in SS.为什么看不到("SH001", None) and SS.为什么看不到(None, None) == "", 3)

print("\n▸ ③ 接口层的 SQL 片段和口径同一份(human_api._门店范围SQL)")
try:
    import human_api as HA  # noqa: E402

    class 我:
        def __init__(self, s):
            self.store_id = s
    片0, 参0 = HA._门店范围SQL(我(None))
    片1, 参1 = HA._门店范围SQL(我("SH001"))
    ck("不限门店 → 不加条件;登记了门店 → 加 upper(trim(coalesce(store_id,''))) = 我的门店(空的单子因此不匹配,和 看得到吗 一致)",
       片0 == "" and 参0 == {} and "upper(trim(coalesce(store_id, '')))" in 片1 and 参1 == {"my_store": "SH001"}, 2, (片0, 片1, 参1))
    import inspect
    源 = inspect.getsource(HA)
    ck("列表 / 详情 / 决定三处都走这段范围(列表拼进 where,详情和决定走 _按门店找),没有一处还在裸查 human_requests by id",
       源.count("_按门店找(c, project_id, req_id, me") == 3 and 源.count("{片}") >= 2 and "where project_id=:p and id=:i and archived_at is null\"\"\"" not in 源, 3,   # 3 = 定义 1 + 详情 / 决定各调 1
       (源.count("_按门店找(c, project_id, req_id, me"), 源.count("{片}")))
    ck("「他能碰这个对象吗」三处都用 看得到吗,不再写死 True", 源.count("他能碰这个对象吗=SS.看得到吗(me.store_id") == 3 and "他能碰这个对象吗=True" not in 源, 3)
except Exception as e:  # noqa: BLE001
    ck("human_api 能导入(接口层那三条判据要靠它)", False, 0, f"{type(e).__name__}: {e}")

print(f"\n{'❌ ' + str(len(挂)) + ' 条挂了' if 挂 else '✅ ' + str(len(过)) + ' 条全过'}")
sys.exit(1 if 挂 else 0)
