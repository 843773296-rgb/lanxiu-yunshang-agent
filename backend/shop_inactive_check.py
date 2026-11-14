#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「无效店铺不接新业务」的检查(用户 11-14 夜拍板:SH003 那个「无效」是错的,改回有效,
再把「无效店铺禁止新增业务」真拦上 —— 原来店铺标了无效,这个月照样建了 94 条预约、364 张单)。

**在库副本上真调五个新建入口**,每个入口都做一对:
  同一份输入,店是「有效」→ 不被这道闸拦(对照);把同一家店改成「无效」→ 被拦、代码是 SHOP_INACTIVE。
对照那一半是要紧的:一个永远返回「拦」的入口,在只验「无效被拦」的检查里也是全绿。

五个入口:后台新建客户 / 后台批量导入客户 / 后台新建预约 / 开定制单 / 顾客手机自助预约。
另验:顾客那头的拒绝理由不带内部状态字样(对外口子),已有的预约和单子不受影响(只拦新增)。
"""
from contextlib import closing
import os, sys, json, sqlite3, tempfile, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把 shop_key.停业理由 改成永远返回 None', '后台新建客户:无效店被拦、有效店不拦'),
    ('把开单入口里调停业理由那段去掉', '开定制单:无效店被拦、有效店不拦'),
    ('把顾客自助预约里调停业理由那段去掉', '顾客自助预约:无效店被拦、有效店不拦'),
    ('把批量导入里逐行拦无效店那句去掉', '后台批量导入客户:无效店被拦、有效店不拦'),
]
# 判据名写成字面量(咬合规格按名字在脚本里找,拼出来的名字找不到)
标题 = {
    "后台新建客户": "后台新建客户:无效店被拦、有效店不拦",
    "后台新建预约": "后台新建预约:无效店被拦、有效店不拦",
    "开定制单": "开定制单:无效店被拦、有效店不拦",
    "顾客自助预约": "顾客自助预约:无效店被拦、有效店不拦",
    "后台批量导入客户": "后台批量导入客户:无效店被拦、有效店不拦",
}


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    tmp = tempfile.mkdtemp()
    副本 = os.path.join(tmp, "lanxiu.db")
    with closing(sqlite3.connect(os.path.join(HERE, "lanxiu.db"))) as 真, closing(sqlite3.connect(副本)) as 副:
        真.backup(副)
    # 先把所有写口 import 进来再切库 —— 之后才 import 的模块会写真库
    import server, oplog, order_write, booking, shop_key
    server.DB = oplog.DB = order_write.DB = booking.DB = shop_key.DB = 副本
    assert server.DB == order_write.DB == booking.DB == oplog.DB == 副本, "库没切到副本"

    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as _c:
            return [tuple(r) for r in _c.execute(sql, a).fetchall()]

    def 设状态(code, st):
        with closing(sqlite3.connect(副本)) as _c, _c:
            _c.execute("UPDATE shop SET status=? WHERE code=?", (st, code))

    店 = q("SELECT code, name FROM shop ORDER BY code")
    ck("副本里有店铺", len(店) > 0, len(店))
    if not 店: return
    # 挑一家有顾问、有客户的店来验(哪家都行,闸不认店名)
    选 = None
    for code, nm in 店:
        串 = f"{code} {nm}"
        顾 = q("SELECT no, name, role, shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no LIMIT 1", 串)
        # 自助预约要「一个手机号只对应一条在用档案」且没挂满 3 张
        客 = q("SELECT c.id, c.phone FROM customer c WHERE c.shop=? AND c.archived=0 AND length(c.phone)=11 "
              "AND (SELECT COUNT(*) FROM customer x WHERE x.phone=c.phone AND x.archived=0)=1 "
              "AND (SELECT COUNT(*) FROM schedule s WHERE s.customer_id=c.id AND s.type='客户预约' AND s.status='有效')<2 "
              "ORDER BY c.id LIMIT 1", 串)
        if 顾 and 客:
            选 = (code, 串, dict(zip(("no", "name", "role", "shop"), 顾[0])), 客[0])
            break
    ck("找得到一家有在职顾问、有可自助预约客户的店", 选 is not None, len(店))
    if not 选: return
    code, 串, 顾问, (cid, phone) = 选
    原状态 = q("SELECT status FROM shop WHERE code=?", code)[0][0]

    明天 = (booking._now() + datetime.timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
    n号 = [0]
    def 新号():
        # 尾号每次都不同:尾号相同 + 姓名相似会触发查重转店长确认,那是另一道闸
        n号[0] += 1
        return f"199{os.getpid() % 10000:04d}{n号[0] * 37 % 10000:04d}"
    姓 = "赵钱孙李周吴郑王冯陈"

    入口 = {
        "后台新建客户": lambda: server.create_customer(
            dict(name=f"{姓[n号[0] % 10]}闸检{n号[0]}号", phone=新号(), shop=串, advisor=f"{顾问['no']} {顾问['name']}"),
            顾问["no"], _role="顾问"),
        "后台新建预约": lambda: server.create_appointment(
            dict(customer_id=cid, shop=串, advisor=f"{顾问['no']} {顾问['name']}",
                 start=明天.strftime("%Y-%m-%d %H:%M"),
                 end=(明天 + datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")),
            顾问["no"], _role="顾问"),
        # 不给商品:有效店走到下一步报 NO_ITEM,无效店在这之前被拦 —— 同一份输入,红在哪一步就看得出闸在不在
        "开定制单": lambda: order_write.open_order(dict(customer_id=cid, items=[]), 顾问),
        "顾客自助预约": lambda: booking.book(dict(phone=phone, when=明天.strftime("%Y-%m-%d %H:%M"))),
    }
    def 导入():
        r = server.import_customers(f"姓名,手机号,归属店铺,销售顾问\n{姓[(n号[0] + 5) % 10]}导入{n号[0]}号,{新号()},{串},{顾问['no']} {顾问['name']}",
                                    顾问["no"], role="店长", dry=True)
        拦 = any("SHOP_INACTIVE" in str(x[2]) for x in (r.get("detail") or {}).get("err", []))
        return dict(ok=r.get("ok"), code="SHOP_INACTIVE" if 拦 else r.get("code"),
                    可导=(r.get("counts") or {}).get("ok"), reason=r.get("reason"))
    入口["后台批量导入客户"] = 导入

    单前 = q("SELECT COUNT(*) FROM ordr WHERE shop=?", 串)[0][0]
    约前 = q("SELECT COUNT(*) FROM appointment WHERE shop=?", 串)[0][0]

    try:
        print(f"\n  用 {串} 验(原状态「{原状态}」)")
        for 名, f in 入口.items():
            设状态(code, "有效")
            r有 = f()
            设状态(code, "无效")
            r无 = f()
            ck(标题[名],
               # 批量导入是「行级错误、部分成功」,整批照样 ok —— 拦没拦看下面那条行数
               r有.get("code") != "SHOP_INACTIVE" and r无.get("code") == "SHOP_INACTIVE"
               and (not r无.get("ok") or 名 == "后台批量导入客户"),
               2, f"有效→{r有.get('code')} / 无效→{r无.get('code')}")
            if 名 == "开定制单":
                ck("开定制单:有效店的那一次走到了下一步(没商品),说明闸后面的逻辑照常",
                   r有.get("code") == "NO_ITEM", 1, str(r有.get("code")))
            if 名 == "后台批量导入客户":
                ck("批量导入:有效店能导 1 行、无效店能导 0 行", r有.get("可导") == 1 and r无.get("可导") == 0,
                   2, f"{r有.get('可导')} / {r无.get('可导')}")
            if 名 == "顾客自助预约":
                ck("顾客自助预约:拒绝理由不带「无效」这种内部状态字样", "无效" not in (r无.get("reason") or ""),
                   1, r无.get("reason") or "")
            if 名 == "后台新建客户":
                ck("后台新建客户:被拦的理由说清是哪家店、怎么恢复", code in (r无.get("reason") or "")
                   and "总部运营" in (r无.get("reason") or ""), 1, r无.get("reason") or "")

        # 只拦新增:已有的单子 / 预约一条没少,状态也没被动
        设状态(code, "无效")
        ck("只拦新增:店改成无效后,已有的单子一张没少", q("SELECT COUNT(*) FROM ordr WHERE shop=?", 串)[0][0] == 单前,
           单前)
        ck("只拦新增:已有的预约没少(多出来的只能是有效那几次建的)",
           q("SELECT COUNT(*) FROM appointment WHERE shop=?", 串)[0][0] >= 约前, 约前)
        # 工坊 / 范围这类不是门店的值不归这道闸管(混进来会把打错字误报成店停了)
        ck("不是门店的值(工坊 / 全渠道 / 空)不归这道闸管",
           all(shop_key.停业理由(sqlite3.connect(副本), v) is None for v in ("上海工坊", "全渠道", "", None)), 4)
    finally:
        设状态(code, 原状态)

    print()
    if FAIL:
        print(f"❌ 无效店铺不接新业务:{len(FAIL)} 条没过 —— " + ";".join(FAIL))
        sys.exit(1)
    print(f"✅ 无效店铺不接新业务:五个新建入口都拦、有效店照常、只拦新增(验了 {len(入口)} 个入口)")


if __name__ == "__main__":
    main()
