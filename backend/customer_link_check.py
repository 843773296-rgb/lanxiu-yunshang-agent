#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顾客一次性链接的检查(11-14,台账第四十四条)。在库副本上真调 customer_link 的 发 / 看 / 用,
它再去调 pickup_write.顾客确认完成 / rating_write.顾客追评 —— 都指到副本。

  ① 谁能发:只能给本店的单发(别店的人被拒);签收确认只给「待完成」的单;追评要先有评价
  ② 只能用一次:用过再用 → 失效;对外一律同一句话(不告诉试的人这个令牌存在过)
  ③ 7 天过期(按真实时钟);重发作废旧链接
  ④ 没办成就把占位还回去:顾客点了但订单状态不对,链接还能再用
  ⑤ 库里只存哈希,不存令牌明文
  ⑥ 真办成了:签收确认 → 订单「完成」;追评 → rating.followup_note 写上、星级不变
  ⑦ 入口:/api/c/look、/api/c/use 在匿名放行表里(顾客没账号),发链接那个不在
"""
from contextlib import closing
import os, re, sys, json, sqlite3, tempfile, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
FAIL = []

咬合 = [
    ('把 customer_link.用 的「先占位」去掉(用过的链接还能再用)', '② 两次几乎同时点:只有一次办得成(先占位)'),
    ('把 customer_link.发 的「只能给本店的单发」去掉', '① 别店的人发不了'),
    ('把「没办成就还占位」去掉(顾客点一下遇到状态不对,链接就废了)', '④ 没办成链接还能再用'),
]

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
    # ⚠️ 先切库再调任何写口:customer_link 一调就 CREATE TABLE IF NOT EXISTS —— 指着真库就在共享库建出表
    import customer_link, oplog, pickup_write, rating_write
    for m in (customer_link, oplog, pickup_write, rating_write):
        m.DB = 副本
    assert all(m.DB == 副本 for m in (customer_link, oplog, pickup_write, rating_write)), "库没切到副本"
    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as c:
            return [tuple(r) for r in c.execute(sql, a).fetchall()]
    def 人(sql, *a):
        r = q(sql, *a)
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3]) if r else None

    单 = q("SELECT id, shop_code FROM ordr WHERE status='待完成' AND kind='定制品订单' AND shop_code IS NOT NULL ORDER BY id LIMIT 3")
    ck("样本:三张待完成的定制单", len(单) == 3, len(单))
    if len(单) < 3: return
    oid, 码 = 单[0]
    本店 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? LIMIT 1", 码)
    别店 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code<>? LIMIT 1", 码)
    ck("样本:本店 / 别店各一位在职顾问", bool(本店 and 别店), 2)
    if not (本店 and 别店): return

    print("\n① 谁能发")
    r = customer_link.发(dict(order_id=oid, purpose="签收确认"), 别店)
    ck("① 别店的人发不了", r.get("code") == "OTHER_SHOP", 1, r.get("code"))
    完单 = q("SELECT id FROM ordr WHERE status='完成' AND shop_code=? LIMIT 1", 码)
    if 完单:
        r = customer_link.发(dict(order_id=完单[0][0], purpose="签收确认"), 本店)
        ck("① 已完成的单发不了签收确认链接", r.get("code") == "NOT_READY", 1, r.get("code"))
    r = customer_link.发(dict(order_id=oid, purpose="乱写"), 本店)
    ck("① 用途不在名单里被拒", r.get("code") == "BAD_PURPOSE", 1, r.get("code"))

    print("\n②⑤ 发 / 用一次")
    r = customer_link.发(dict(order_id=oid, purpose="签收确认"), 本店)
    令牌 = (r.get("链接") or "").split("/c/")[-1]
    ck("② 本店顾问发得出,令牌够长(≥40 字符)", r.get("ok") and len(令牌) >= 40, 1, json.dumps({k: r.get(k) for k in ("code", "有效到")}, ensure_ascii=False))
    存的 = q("SELECT token_hash FROM customer_link WHERE order_id=?", oid)
    ck("⑤ 库里只存哈希(不等于令牌、64 位十六进制)", len(存的) == 1 and 存的[0][0] != 令牌 and re.fullmatch(r"[0-9a-f]{64}", 存的[0][0] or ""), 1)
    看 = customer_link.看(令牌)
    ck("② 看:说得出是签收确认、只给订单尾号", 看.get("ok") and 看.get("用途") == "签收确认" and oid not in json.dumps(看, ensure_ascii=False)
       or (看.get("ok") and 看.get("订单尾号") == oid[-6:]), 1, json.dumps(看, ensure_ascii=False)[:120])
    r = customer_link.用(令牌, {})
    ck("⑥ 用:订单真成了「完成」", r.get("ok") and q("SELECT status FROM ordr WHERE id=?", oid) == [("完成",)], 1, r.get("code"))
    r2 = customer_link.用(令牌, {})
    坏 = customer_link.用("这个令牌根本不存在", {})
    ck("② 用过再用 → 失效;且和「根本不存在」回的是同一句话", r2.get("code") == "INVALID" and r2.get("reason") == 坏.get("reason"), 2)

    # 「先占位」防的是**两次几乎同时点**:两边都已经过了「找」那一步(看到的都是没用过),再抢着办。
    # 先后点两次看不出它 —— 第二次在「找」那一步就因为「已用过」被拦了(11-14 咬合没红,攻击点不可观测)。
    # 所以这里造出同时点的形状:让第二次的「找」看到的还是旧状态,再看是不是只办成一次
    oid3, 码3 = 单[2]
    本店3 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? LIMIT 1", 码3) or 本店
    t3 = (customer_link.发(dict(order_id=oid3, purpose="签收确认"), 本店3).get("链接") or "").split("/c/")[-1]
    第一次 = customer_link.用(t3, {})
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE ordr SET status='待完成' WHERE id=?", (oid3,))      # 让「办」这一步本身能再成一次,只剩占位在拦
    原找 = customer_link._找
    customer_link._找 = lambda c, token: ((c.execute("SELECT * FROM customer_link WHERE token_hash=?",
                                                     (customer_link._指纹(token),)).fetchone()), None)
    try:
        第二次 = customer_link.用(t3, {})
    finally:
        customer_link._找 = 原找
    ck("② 两次几乎同时点:只有一次办得成(先占位)", 第一次.get("ok") and 第二次.get("code") == "INVALID"
       and q("SELECT status FROM ordr WHERE id=?", oid3) == [("待完成",)], 2, json.dumps([第一次.get("code"), 第二次.get("code")]))

    print("\n③ 重发 / 过期")
    oid2 = 单[1][0]
    本店2 = 人("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop_code=? LIMIT 1", 单[1][1]) or 本店
    旧 = (customer_link.发(dict(order_id=oid2, purpose="签收确认"), 本店2).get("链接") or "").split("/c/")[-1]
    新r = customer_link.发(dict(order_id=oid2, purpose="签收确认"), 本店2)
    新 = (新r.get("链接") or "").split("/c/")[-1]
    ck("③ 重发:旧的作废、新的能看", 新r.get("作废旧链接") == 1 and not customer_link.看(旧).get("ok") and customer_link.看(新).get("ok"), 2)
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE customer_link SET expires_at=? WHERE token_hash=?",
                  ((dt.datetime.now() - dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"), customer_link._指纹(新)))
    ck("③ 过期了就失效", customer_link.用(新, {}).get("code") == "INVALID"
       and q("SELECT status FROM ordr WHERE id=?", oid2) == [("待完成",)], 1)
    发的 = q("SELECT created_at, expires_at FROM customer_link WHERE token_hash=?", customer_link._指纹(旧))
    if 发的:
        天 = (dt.datetime.fromisoformat(发的[0][1]) - dt.datetime.fromisoformat(发的[0][0])).days
        ck("③ 有效期 7 天", 天 == customer_link.有效天数 == 7, 1, f"{天} 天")

    print("\n④ 没办成还占位")
    再 = (customer_link.发(dict(order_id=oid2, purpose="签收确认"), 本店2).get("链接") or "").split("/c/")[-1]
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE ordr SET status='已发货' WHERE id=?", (oid2,))      # 模拟:点的时候订单状态不对
    r = customer_link.用(再, {})
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE ordr SET status='待完成' WHERE id=?", (oid2,))
    ck("④ 没办成链接还能再用", not r.get("ok") and customer_link.看(再).get("ok")
       and customer_link.用(再, {}).get("ok"), 2, r.get("code"))

    print("\n⑥ 追评")
    # 样本按「最后一件签收」挑:评价时间新不代表签收新(实测挑到过签收 151 天前、评价却是最近的)
    import rating_write as _rw0
    候选 = q("""SELECT r.pkg_id, r.order_id, r.star, o.shop_code FROM rating r JOIN ordr o ON o.id=r.order_id
               WHERE r.followup_note IS NULL AND o.shop_code IS NOT NULL ORDER BY r.rated_at DESC LIMIT 200""")
    评 = [x for x in 候选 if _rw0.追评闸(x[0])[0]][:1]
    超 = [x for x in 候选 if "超过" in _rw0.追评闸(x[0])[1]][:1]
    ck("样本:一条还能追评的评价", bool(评), len(评))
    if 超:
        发者0 = 人("SELECT no,name,role,shop FROM staff WHERE role IN ('顾问','店长') AND status='启用' AND shop_code=? LIMIT 1", 超[0][3])
        r = customer_link.发(dict(order_id=超[0][1], purpose="追评", pkg_id=超[0][0]), 发者0)
        ck("⑥ 签收超过 90 天的包裹发不出追评链接(发的时候就判,不让顾客点开才知道)", r.get("code") == "CANNOT_FOLLOWUP", 1, r.get("code"))
    if 评:
        pid, oid3, 星, 码3 = 评[0]
        发者 = 人("SELECT no,name,role,shop FROM staff WHERE role IN ('顾问','店长') AND status='启用' AND shop_code=? LIMIT 1", 码3)
        r = customer_link.发(dict(order_id=oid3, purpose="追评", pkg_id=pid), 发者)
        t = (r.get("链接") or "").split("/c/")[-1]
        r = customer_link.用(t, {"note": "穿了两次,领口很服帖"})
        行 = q("SELECT followup_note, star FROM rating WHERE pkg_id=?", pid)
        ck("⑥ 追评写上了、星级没变", r.get("ok") and 行 == [("穿了两次,领口很服帖", 星)], 1, json.dumps([r.get("code"), r.get("reason")], ensure_ascii=False)[:160])
        r = customer_link.发(dict(order_id=oid3, purpose="追评", pkg_id=pid), 发者)
        ck("⑥ 追评过的包裹不能再发追评链接", r.get("code") == "DONE", 1, r.get("code"))

    print("\n⑦ 入口")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    import ast
    放行 = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "POST_匿名放行" for t in n.targets):
            放行 = {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
    ck("⑦ /api/c/look、/api/c/use 在匿名放行表里;/api/customer-link 不在",
       {"/api/c/look", "/api/c/use"} <= 放行 and "/api/customer-link" not in 放行, 3, f"{sorted(放行)}")
    ck("⑦ /api/customer-link 交的是会话登录人", bool(re.search(r'_cl\.发\(body, 登录人\)', src)), 1)
    ck("⑦ 落地页不缓存、不带来源地址", 'send_header("cache-control","no-store")' in src and '"referrer-policy","no-referrer"' in src, 2)

    print()
    if FAIL:
        print(f"❌ 顾客一次性链接 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 顾客一次性链接全过")


if __name__ == "__main__":
    main()
