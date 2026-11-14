#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店名整库改名的检查(用户 11-14 夜拍板,台账第五十八条)。**全在库副本上真调 shop_rename**。

各条防的坏法:
  ① 只总部运营:店长 / 顾问预览、改名、撤销都被拒,库一行没动
  ② 预览一行不写;预览的「合计」= 真改的行数
  ③ 真改:登记的列里老串一行不剩、新串行数 = 预览;门店码一行没变;改完新店名换得出门店码
  ④ 历史快照(签过的合同正文)一个字没动
  ⑤ 台账和改动同生同死:改成了正好一行 RENAME,里面记着每张表改了几行
  ⑥ 预览之后又进了新数据 → 拒改(PREVIEW_STALE),什么都没动
  ⑦ 改到一半对账对不上 → 整个回滚(造法:副本上加个触发器,改客户门店串时顺手动门店码)
  ⑧ 冒出没登记的列也装着整串老店名 → 预览报出来、真改拒绝
  ⑨ 撤销:按台账原样改回,行数回到原样;只许撤最近一次;店名又被改过就不许撤
  ⑩ 店名校验:空格 / 逗号 / 重名 / 没变 都拒
  ⑪ 改完作废这家店员工的登录会话(会话里存的门店串是登录时的)
"""
from contextlib import closing
import os, sys, json, sqlite3, tempfile, hashlib, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把改名的角色闸改成「店长也放行」', '① 店长 / 顾问预览、改名、撤销都被拒,库一行没动'),
    ('把对账那段去掉(差 永远为空)', '⑦ 改到一半对账对不上 → 整个回滚,店名和各表都是原样'),
    ('把「预览后又有新数据」那道比对去掉', '⑥ 预览之后又进了新数据 → 拒改,什么都没动'),
    ('把没登记列里「夹着整串老店名」那条扫描改成只认整列相等', '⑧ 没登记的列文字里夹着整串老店名 → 预览报出来、真改拒绝'),
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
    import shop_rename as R, oplog, auth, shop_key
    R.DB = oplog.DB = shop_key.DB = auth.DB = 副本
    auth._文件 = lambda: os.path.join(tmp, "sessions.json")      # 别碰真会话文件
    assert R.DB == oplog.DB == 副本

    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as _c:
            return [tuple(r) for r in _c.execute(sql, a).fetchall()]
    def 指纹():
        """各登记列 + 快照列 + shop 表的内容指纹 —— 「什么都没动」就拿它比"""
        h = hashlib.sha256()
        for t, col in sorted(set(R.要改的列) | set(R.快照列) | {("shop", "name")}):
            if t == "op_log": continue      # 台账本来就该多行(撤销、被拒都留痕),不算「动了业务数据」
            try:
                for (v,) in q(f'SELECT "{col}" FROM "{t}" ORDER BY rowid'): h.update(str(v).encode())
            except sqlite3.Error:
                pass
        return h.hexdigest()
    def 人(role):
        r = q("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", role)
        return dict(zip(("no", "name", "role", "shop"), r[0])) if r else None
    总部, 店长, 顾问 = 人("总部运营"), 人("店长"), 人("顾问")
    ck("三种身份都找得到", all((总部, 店长, 顾问)), 3)
    if not all((总部, 店长, 顾问)): return
    # 挑员工最多的那家店改(会话作废那条才有人可验)
    码, 老名, _n = q("SELECT s.code, s.name, COUNT(t.no) n FROM shop s LEFT JOIN staff t ON t.shop = s.code || ' ' || s.name "
                    "GROUP BY s.code ORDER BY n DESC, s.code LIMIT 1")[0]
    老串, 新名 = f"{码} {老名}", 老名 + "检查"
    新串 = f"{码} {新名}"
    指0 = 指纹()

    print(f"\n① 角色闸(用 {老串})")
    rs = [f(dict(code=码, new_name=新名, expect_total=1), p) for f in (R.预览, R.改名) for p in (店长, 顾问)] + \
         [R.撤销(dict(code=码), p) for p in (店长, 顾问)]
    拒痕 = q("SELECT COUNT(*) FROM op_log WHERE machine=? AND allowed=0 AND code='WRONG_ROLE'", R.机)[0][0]
    ck("① 店长 / 顾问预览、改名、撤销都被拒,库一行没动",
       all(r.get("code") == "WRONG_ROLE" for r in rs) and 指纹() == 指0,
       len(rs), json.dumps([r.get("code") for r in rs]))
    ck("① 被拒也留痕(每次越权一行)", 拒痕 == len(rs), len(rs), f"{拒痕} 行")

    print("\n② 预览")
    p = R.预览(dict(code=码, new_name=新名), 总部)
    ck("② 预览成功、一行不写", p.get("ok") and 指纹() == 指0, 1, (p.get("reason") or "")[:160])
    if not p.get("ok"): return
    要改 = {(r["表"], r["列"]): r["行数"] for r in p["要改"]}
    ck("② 预览覆盖了全部登记列(含账户表常去门店那一列)",
       all(k in 要改 for k in R.要改的列) and ("account", "home_shop") in 要改, len(要改))

    print("\n⑩ 店名校验")
    别家 = q("SELECT name FROM shop WHERE code<>? LIMIT 1", 码)[0][0]
    坏 = [("带 空格", "BAD_NAME"), ("带,逗号", "BAD_NAME"), (别家, "NAME_TAKEN"), (老名, "SAME_NAME"), ("", "NEED_NAME")]
    rs = [R.改名(dict(code=码, new_name=n, expect_total=p["合计"]), 总部).get("code") for n, _ in 坏]
    ck("⑩ 空格 / 逗号 / 重名 / 没变 / 空 都拒", rs == [c for _, c in 坏] and 指纹() == 指0, len(坏), str(rs))

    print("\n⑥ 预览过期")
    r = R.改名(dict(code=码, new_name=新名, expect_total=p["合计"] - 1), 总部)
    ck("⑥ 预览之后又进了新数据 → 拒改,什么都没动", r.get("code") == "PREVIEW_STALE" and 指纹() == 指0, 1, str(r.get("code")))

    print("\n⑦ 对账不上就回滚")
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("CREATE TRIGGER _检查坏账 AFTER UPDATE OF shop ON customer BEGIN "
                  "UPDATE customer SET shop_code='SH999' WHERE rowid=NEW.rowid; END")
    r = R.改名(dict(code=码, new_name=新名, expect_total=p["合计"]), 总部)
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("DROP TRIGGER _检查坏账")
    ck("⑦ 改到一半对账对不上 → 整个回滚,店名和各表都是原样",
       r.get("code") == "RECONCILE_FAILED" and 指纹() == 指0 and q("SELECT name FROM shop WHERE code=?", 码)[0][0] == 老名
       and not q("SELECT 1 FROM op_log WHERE machine=? AND target=? AND allowed=1", R.机, 码), 1, (r.get("reason") or "")[:160])

    print("\n⑧ 没登记的列")
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("CREATE TABLE _检查设置(k TEXT, v TEXT)")
        c.execute("INSERT INTO _检查设置(k, v) VALUES('试运行门店', ?)", (json.dumps([老串, "别的"], ensure_ascii=False),))
    p8 = R.预览(dict(code=码, new_name=新名), 总部)
    r8 = R.改名(dict(code=码, new_name=新名, expect_total=p["合计"]), 总部)
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("DROP TABLE _检查设置")
    ck("⑧ 没登记的列文字里夹着整串老店名 → 预览报出来、真改拒绝",
       p8.get("code") == "UNREGISTERED_COLUMN" and any(x["表"] == "_检查设置" for x in p8.get("没登记", []))
       and r8.get("code") == "UNREGISTERED_COLUMN" and 指纹() == 指0, 2, f"{p8.get('code')} / {r8.get('code')}")

    print("\n③④⑤⑪ 真改")
    合同前 = q("SELECT group_concat(body, '|') FROM (SELECT body FROM order_contract ORDER BY rowid)")[0][0]
    码前 = {t: q(f'SELECT COUNT(*) FROM "{t}" WHERE shop_code=?', 码)[0][0] for t, _ in shop_key.带门店键的
            if 码 in [x[0] for x in q("SELECT code FROM shop")] and "shop_code" in [x[1] for x in q(f'PRAGMA table_info("{t}")')]}
    这店人 = [x[0] for x in q("SELECT no FROM staff WHERE shop=?", 老串)]
    假 = "检查用会话"
    if 这店人:
        auth._SESS[假] = dict(no=这店人[0], name="?", role="顾问", shop=老串, at=dt.datetime.now())
    r = R.改名(dict(code=码, new_name=新名, expect_total=p["合计"]), 总部)
    ck("③ 改名成功", r.get("ok") and r.get("code") == "RENAMED", 1, (r.get("reason") or "")[:160])
    剩老 = sum(q(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}"=?', 老串)[0][0] for t, col in R.要改的列)
    新各 = {(t, col): q(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}"=?', 新串)[0][0] for t, col in R.要改的列}
    ck("③ 登记的列里老串一行不剩、新串行数 = 预览", 剩老 == 0 and all(新各[k] == 要改[k] for k in 新各), len(新各),
       f"剩老 {剩老}")
    ck("③ 门店码一行没变", all(q(f'SELECT COUNT(*) FROM "{t}" WHERE shop_code=?', 码)[0][0] == n for t, n in 码前.items()),
       len(码前))
    with closing(sqlite3.connect(副本)) as c:
        ck("③ 改完新店名换得出门店码、老店名换不出", shop_key.码(c, 新串) == 码 and shop_key.码(c, 老串) is None, 2)
    ck("④ 签过的合同正文一个字没动",
       q("SELECT group_concat(body, '|') FROM (SELECT body FROM order_contract ORDER BY rowid)")[0][0] == 合同前, 1)
    台 = q("SELECT code, ctx FROM op_log WHERE machine=? AND target=? AND allowed=1 ORDER BY id", R.机, 码)
    ck("⑤ 台账正好一行 RENAME,记着每张表改了几行、合计对得上",
       len(台) == 1 and 台[0][0] == "RENAME" and json.loads(台[0][1]).get("合计") == p["合计"], len(台))
    if 这店人:
        ck("⑪ 这家店员工的旧登录会话已作废", 假 not in auth._SESS, 1)
    else:
        print("  ⚠️ ⑪ 这家店没有员工,会话作废没验到(不算通过)")

    print("\n⑨ 撤销")
    r = R.撤销(dict(code=码), 总部)
    ck("⑨ 撤销:店名、各表行数、门店码都回到原样",
       r.get("code") == "UNDONE" and 指纹() == 指0, 1, (r.get("reason") or "")[:160])
    ck("⑨ 只许撤最近一次:撤过再撤被拒", R.撤销(dict(code=码), 总部).get("code") == "ALREADY_UNDONE", 1)
    R.改名(dict(code=码, new_name=新名, expect_total=p["合计"]), 总部)
    p2 = R.预览(dict(code=码, new_name=新名 + "二"), 总部)
    R.改名(dict(code=码, new_name=新名 + "二", expect_total=p2.get("合计")), 总部)
    with closing(sqlite3.connect(副本)) as c, c:
        c.execute("UPDATE shop SET name='手改了' WHERE code=?", (码,))      # 绕过写口直接改,模拟店名被别处动过
    ck("⑨ 店名又被改过就不许撤", R.撤销(dict(code=码), 总部).get("code") == "NAME_CHANGED", 1)

    print()
    if FAIL:
        print(f"❌ 店名整库改名:{len(FAIL)} 条没过 —— " + ";".join(FAIL))
        sys.exit(1)
    print(f"✅ 店名整库改名:只总部、先预览、一个事务、对账不上就回滚、快照不动、能撤销(验了 {p['合计']} 行)")


if __name__ == "__main__":
    main()
