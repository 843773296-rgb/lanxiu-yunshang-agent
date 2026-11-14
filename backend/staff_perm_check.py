#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编辑员工权限的检查(11-14,台账第四十五条第四组)。在库副本上真调 `server.save_staff_perm`。

  ① 用户拍的三条:只总部运营;**不能改自己**;不能给别人提到比自己高(店长自报总部也不行)
  ② 归属对得上角色:门店角色挂门店、总部角色不挂门店
  ③ 名下还有客户 / 没办完的任务:不许换门店、不许从顾问改走、不许停用
  ④ 现任店长先在店铺资料里换人,才能降级
  ⑤ 改成功后**这个人的旧会话全作废**(会话里的角色是登录时存的)
  ⑥ 日志记的字段 = UPDATE 里记日志的那几个;入口交会话登录人
"""
import os, re, sys, json, sqlite3, tempfile, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把 save_staff_perm 的「不能改自己」去掉', '① 总部运营改不了自己'),
    ('把改权限之后的「作废旧会话」去掉', '⑤ 改成功后这个人的旧会话全作废'),
    ('把「名下还有客户不许改」那道闸去掉', '③ 名下有客户的顾问:换门店、改角色、停用都被拒'),
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
    with sqlite3.connect(os.path.join(HERE, "lanxiu.db")) as 真, sqlite3.connect(副本) as 副:
        真.backup(副)
    import server, oplog, auth
    server.DB = oplog.DB = 副本
    # 会话落盘也挪到临时目录 —— 这条检查要往会话表里塞假会话,别碰真登录态
    auth._文件 = lambda: os.path.join(tmp, "sessions.json")
    assert server.DB == 副本 and oplog.DB == 副本
    q = lambda sql, *a: [tuple(r) for r in sqlite3.connect(副本).execute(sql, a).fetchall()]
    def 人(sql, *a):
        r = q(sql, *a)
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3]) if r else None
    总部 = 人("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' ORDER BY no LIMIT 1")
    店长 = 人("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' ORDER BY no LIMIT 1")
    有客顾问 = 人("SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='顾问' AND s.status='启用' "
                "AND EXISTS(SELECT 1 FROM customer c WHERE c.advisor_no=s.no) ORDER BY s.no LIMIT 1")
    空顾问 = 人("SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='顾问' AND s.status='启用' "
               "AND NOT EXISTS(SELECT 1 FROM customer c WHERE c.advisor_no=s.no) "
               "AND NOT EXISTS(SELECT 1 FROM schedule x WHERE x.assignee_no=s.no AND x.status='有效') ORDER BY s.no LIMIT 1")
    if not 空顾问 and 有客顾问:
        # 库里每个顾问都有客户时,在副本上造一个空的(只在副本)
        with sqlite3.connect(副本) as c:
            c.execute("INSERT INTO staff(no,name,role,shop,status,shop_code) SELECT '69999999','检查空顾问','顾问',shop,'启用',shop_code "
                      "FROM staff WHERE no=?", (有客顾问["no"],))
        空顾问 = 人("SELECT no,name,role,shop FROM staff WHERE no='69999999'")
    ck("样本:总部 / 店长 / 有客户的顾问 / 没客户没任务的顾问", all((总部, 店长, 有客顾问, 空顾问)), 4)
    if not all((总部, 店长, 有客顾问, 空顾问)): return
    别店 = q("SELECT code||' '||name FROM shop WHERE code<>(SELECT shop_code FROM staff WHERE no=?) ORDER BY code LIMIT 1", 空顾问["no"])[0][0]

    print("\n① 三条拍过的")
    前 = q("SELECT * FROM staff ORDER BY no")
    r1 = server.save_staff_perm(dict(no=空顾问["no"], role="店长"), 店长)
    r2 = server.save_staff_perm(dict(no=店长["no"], role="总部运营", shop=""), 店长)
    ck("① 店长改不了别人、也给自己提不了权", r1.get("code") == "WRONG_ROLE" and r2.get("code") == "WRONG_ROLE"
       and q("SELECT * FROM staff ORDER BY no") == 前, 2, json.dumps([r1.get("code"), r2.get("code")]))
    r = server.save_staff_perm(dict(no=总部["no"], status="停用"), 总部)
    ck("① 总部运营改不了自己", r.get("code") == "SELF_EDIT" and q("SELECT * FROM staff ORDER BY no") == 前, 1, r.get("code"))
    r = server.save_staff_perm(dict(no=空顾问["no"], role="店长", shop=空顾问["shop"]), dict(店长, role="财务"))
    ck("① 低级别(自称财务)不能把别人提成店长", r.get("code") in ("WRONG_ROLE", "ABOVE_ME"), 1, r.get("code"))

    print("\n② 归属")
    r1 = server.save_staff_perm(dict(no=空顾问["no"], role="总部运营"), 总部)       # 还挂着门店
    r2 = server.save_staff_perm(dict(no=空顾问["no"], shop=""), 总部)                 # 顾问不挂门店
    ck("② 总部岗位不能挂门店、门店岗位不能不挂", r1.get("code") == "HQ_NO_SHOP" and r2.get("code") == "NEED_SHOP", 2,
       json.dumps([r1.get("code"), r2.get("code")]))

    print("\n③ 名下有客户")
    rs = [server.save_staff_perm(dict(no=有客顾问["no"], shop=别店), 总部),
          server.save_staff_perm(dict(no=有客顾问["no"], role="店长"), 总部),
          server.save_staff_perm(dict(no=有客顾问["no"], status="停用"), 总部)]
    ck("③ 名下有客户的顾问:换门店、改角色、停用都被拒", all(r.get("code") == "HAS_WORK" for r in rs), 3,
       json.dumps([r.get("code") for r in rs]))

    print("\n④ 现任店长")
    是店长 = q("SELECT 1 FROM shop WHERE manager=?", 店长["name"])
    r = server.save_staff_perm(dict(no=店长["no"], role="顾问"), 总部)
    ck("④ 现任店长不能直接降级", bool(是店长) and r.get("code") in ("IS_MANAGER", "HAS_WORK"), 1, r.get("code"))

    print("\n⑤ 会话")
    假 = "检查用假令牌"
    auth._SESS[假] = dict(no=空顾问["no"], name=空顾问["name"], role="顾问", shop=空顾问["shop"], at=dt.datetime.now())
    ck("⑤ 前提:旧会话换得出身份", auth.who(假) is not None, 1)
    r = server.save_staff_perm(dict(no=空顾问["no"], shop=别店), 总部)
    ck("⑤ 改成功后这个人的旧会话全作废", r.get("ok") and auth.who(假) is None, 1, json.dumps(r, ensure_ascii=False)[:160])
    行 = q("SELECT shop, shop_code, updated_by FROM staff WHERE no=?", 空顾问["no"])
    ck("⑤ 门店码跟着归属改,修改人是操作的人", 行 and 行[0][0] == 别店 and 行[0][1] == 别店.split(" ")[0] and 行[0][2] == 总部["no"],
       1, json.dumps(行, ensure_ascii=False))

    print("\n⑥ 日志 / 入口 / 页面")
    最后 = q("SELECT changes FROM edit_log WHERE obj='员工' AND target=? ORDER BY id DESC LIMIT 1", 空顾问["no"])
    ck("⑥ 只换了门店 → 日志只记「归属」", 最后 and [x["字段"] for x in json.loads(最后[0][0])] == ["归属"], 1)
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    m = re.search(r'c\.execute\("UPDATE staff SET ([^"]+?) WHERE no=\?"', src)
    写的 = sorted(x.split("=")[0].strip() for x in m.group(1).split(",")) if m else []
    记日志的 = sorted(x for x in 写的 if x not in ("shop_code", "updated_by", "updated"))
    ck("⑥ 日志记的字段 = UPDATE 里除戳和门店码之外的字段", 记日志的 == sorted(server.员工字段名), len(写的), f"{写的}")
    ck("⑥ /api/staff-perm 交会话登录人", bool(re.search(r'if p=="/api/staff-perm":\s*\n\s*return self\._send\(save_staff_perm\(body, 登录人\)\)', src)), 1)
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    ck("⑥ 页面不再有「编辑权限 · 本期未实现」,真发 /api/staff-perm",
       "编辑权限 · 本期未实现" not in 页 and '"/api/staff-perm"' in 页, 2)

    print()
    if FAIL:
        print(f"❌ 编辑权限 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 编辑权限全过")


if __name__ == "__main__":
    main()
