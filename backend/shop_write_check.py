#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店铺资料写口的检查(11-14,台账第四十五条:「本期未实现」按钮第一组)。

**在库副本上真调 `server.save_shop` / `server.transit`**,不在夹具里重写一份判定。

各条防的坏法:

  ① 角色闸:顾问、店长调新增 / 编辑 / 启停都被拒,**被拒也留了 op_log**,店铺表一行没动
     —— 启停那条原来谁登录都能点(状态机 bk-shop 不带角色)
  ② 新店默认「无效」(验收集「新建对象的初始状态未定义」那条)
  ③ 店名不许改:改名会让 5 万多条「编码 + 店名」写法的记录换不出门店码(shop_key.py 文件头)
  ④ 店长只能指给这家店在职的店长
  ⑤ 日志只记真改了的字段,而且「日志记的字段 = UPDATE 真写的字段」(两边从源码取)
  ⑥ 入口真接上了:/api/shop-save 交的是会话里的登录人,不是请求体
"""
import os, re, sys, json, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把 save_shop 的角色闸改成「店长也放行」', '① 顾问 / 店长新增、编辑店铺都被拒,被拒也留痕'),
    ('把 transit 里 bk-shop 那道角色闸去掉', '① 顾问 / 店长启停店铺被拒'),
    ('把编辑时的「店名不许改」那段去掉', '③ 改店名被拒,店名没动'),
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
    # .backup 而不是 cp:backend/lanxiu.db 在另一个检出里是软链(CLAUDE.md §7-5.5)
    with sqlite3.connect(os.path.join(HERE, "lanxiu.db")) as 真, sqlite3.connect(副本) as 副:
        真.backup(副)
    import server, oplog
    server.DB = oplog.DB = 副本
    assert server.DB == 副本 and oplog.DB == 副本, "库没切到副本"
    q = lambda sql, *a: [tuple(r) for r in sqlite3.connect(副本).execute(sql, a).fetchall()]
    def 人(role):
        r = q("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", role)
        if not r: return None
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3])
    总部, 店长, 顾问 = 人("总部运营"), 人("店长"), 人("顾问")
    ck("三种身份都找得到(总部运营 / 店长 / 顾问)", all((总部, 店长, 顾问)), 3)
    if not all((总部, 店长, 顾问)): return
    店前 = q("SELECT * FROM shop ORDER BY code")
    ck("副本里有店铺", len(店前) > 0, len(店前))
    if not 店前: return
    码0 = 店前[0][0]
    日志数 = lambda: q("SELECT COUNT(*) FROM op_log WHERE machine='bk-shop' AND allowed=0")[0][0]

    print("\n① 角色闸")
    拒前 = 日志数()
    rs = [server.save_shop(dict(new=1, code="SH901", name="检查新店"), p) for p in (顾问, 店长)] + \
         [server.save_shop(dict(code=码0, phone="021-0000-0000"), p) for p in (顾问, 店长)]
    ck("① 顾问 / 店长新增、编辑店铺都被拒,被拒也留痕",
       all(r.get("code") == "WRONG_ROLE" for r in rs) and 日志数() - 拒前 == 4
       and q("SELECT * FROM shop ORDER BY code") == 店前, len(rs), json.dumps([r.get("code") for r in rs], ensure_ascii=False))
    拒前 = 日志数()
    st0 = q("SELECT status FROM shop WHERE code=?", 码0)[0][0]
    到 = "无效" if st0 == "有效" else "有效"
    ts = [server.transit("bk-shop", 码0, 到, {"note": "检查"}, p["name"], me=p) for p in (顾问, 店长)]
    ck("① 顾问 / 店长启停店铺被拒",
       all(r.get("code") == "WRONG_ROLE" for r in ts) and q("SELECT status FROM shop WHERE code=?", 码0)[0][0] == st0
       and 日志数() - 拒前 == 2, len(ts), json.dumps([r.get("code") for r in ts], ensure_ascii=False))
    t = server.transit("bk-shop", 码0, 到, {"note": "检查"}, 总部["name"], me=总部)
    ck("① 总部运营启停照常", t.get("ok") is True and q("SELECT status FROM shop WHERE code=?", 码0)[0][0] == 到, 1,
       json.dumps(t, ensure_ascii=False)[:200])

    print("\n② 新增")
    坏 = [(dict(new=1, code="X1", name="甲"), "BAD_CODE"),
          (dict(new=1, code=码0, name="甲"), "DUP_CODE"),
          (dict(new=1, code="SH902", name="有 空格"), "BAD_NAME"),
          (dict(new=1, code="SH902", name="上海工坊"), "BAD_NAME"),
          (dict(new=1, code="SH902", name=店前[0][1]), "DUP_NAME"),
          (dict(new=1, code="SH902", name="甲店", manager=店长["name"]), "NO_STAFF_YET"),
          (dict(new=1, code="SH902", name="甲店", phone="abc"), "BAD_PHONE")]
    got = [server.save_shop(d, 总部).get("code") for d, _ in 坏]
    ck("② 坏输入各被它该被的理由拒", got == [c for _, c in 坏], len(坏), json.dumps(got, ensure_ascii=False))
    r = server.save_shop(dict(new=1, code="sh903", name="检查店", phone="021-1234-5678", addr="某路 1 号"), 总部)
    行 = q("SELECT code,name,status FROM shop WHERE code='SH903'")
    ck("② 总部运营能建,编码转大写,新店默认「无效」", r.get("ok") and 行 == [("SH903", "检查店", "无效")], 1, json.dumps(r, ensure_ascii=False)[:200])
    ck("② 新建留了编辑日志(初值记全)",
       bool(q("SELECT 1 FROM edit_log WHERE obj='店铺' AND target='SH903' AND changes LIKE '%检查店%'")), 1)

    print("\n③ 店名不许改")
    r = server.save_shop(dict(code=码0, name=店前[0][1] + "改", phone=店前[0][4]), 总部)
    ck("③ 改店名被拒,店名没动", r.get("code") == "NAME_LOCKED" and q("SELECT name FROM shop WHERE code=?", 码0)[0][0] == 店前[0][1], 1,
       r.get("code"))
    r = server.save_shop(dict(code=码0, name=店前[0][1], manager=店前[0][3], phone=店前[0][4],
                              province=店前[0][5], addr=店前[0][6]), 总部)
    ck("③ 带着原店名提交(表单原样回传)不算改名", r.get("ok") is True, 1, r.get("code"))

    print("\n④ 店长")
    别店店长 = q("SELECT s.name FROM staff s WHERE s.role='店长' AND s.status='启用' AND s.shop_code IS NOT NULL AND s.shop_code<>? LIMIT 1", 码0)
    本店店长 = q("SELECT s.name FROM staff s WHERE s.role='店长' AND s.status='启用' AND s.shop_code=? LIMIT 1", 码0)
    ck("④ 有别店店长 / 本店店长可试", bool(别店店长) and bool(本店店长), len(别店店长) + len(本店店长))
    if 别店店长 and 本店店长:
        r1 = server.save_shop(dict(code=码0, manager=别店店长[0][0]), 总部)
        r2 = server.save_shop(dict(code=码0, manager="查无此人"), 总部)
        r3 = server.save_shop(dict(code=码0, manager=本店店长[0][0], phone="021-9999-0000",
                                   province=店前[0][5], addr=店前[0][6]), 总部)
        ck("④ 别店店长 / 不存在的人被拒,本店店长可以",
           r1.get("code") == "BAD_MANAGER" and r2.get("code") == "BAD_MANAGER" and r3.get("ok") is True, 3,
           json.dumps([r1.get("code"), r2.get("code"), r3.get("code")], ensure_ascii=False))

        print("\n⑤ 日志")
        最后 = q("SELECT changes FROM edit_log WHERE obj='店铺' AND target=? ORDER BY id DESC LIMIT 1", 码0)
        字段 = sorted(x["字段"] for x in json.loads(最后[0][0])) if 最后 else []
        ck("⑤ 只改了电话(店长原样)→ 日志只记「联系方式」", 字段 == ["联系方式"], 1, json.dumps(字段, ensure_ascii=False))
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    m = re.search(r'UPDATE shop SET ([^"]+?)WHERE code=\?', src)
    写的 = sorted(x.split("=")[0].strip() for x in m.group(1).split(",") if x.strip() and not x.strip().startswith("updated")) if m else []
    ck("⑤ 日志记的字段 = UPDATE 真写的字段", 写的 == sorted(server.店铺字段名), len(写的),
       f"UPDATE 写 {写的} / 日志记 {sorted(server.店铺字段名)}")

    print("\n⑥ 入口")
    m = re.search(r'if p=="/api/shop-save":\s*\n\s*return self\._send\(save_shop\(body, *登录人\)\)', src)
    ck("⑥ /api/shop-save 交给 save_shop 的是会话登录人", bool(m), 1)
    ck("⑥ /api/shop-save 不在匿名放行 / 内部口里",
       "/api/shop-save" not in getattr(server, "POST_匿名放行", ()) and "/api/shop-save" not in getattr(server, "POST_内部口", ()), 1)

    print("\n⑦ 页面")
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    编 = re.search(r'modal\(`编辑店铺 · .*?\],\s*v=>doOp\("/api/shop-save"', 页, re.S)
    表单 = sorted(re.findall(r'\{k:"(\w+)"', 编.group(0))) if 编 else []
    ck("⑦ 编辑店铺表单的字段 = 写入真写的字段(能写的都改得了,表单里没有写不进的)",
       表单 == sorted(server.店铺字段名), len(表单), f"表单 {表单}")
    建 = re.search(r'modal\("新增店铺",.*?v=>doOp\("/api/shop-save",\{\.\.\.v,new:1\}', 页, re.S)
    ck("⑦ 新增店铺表单发到 /api/shop-save、带 new,有编码和名称",
       bool(建) and '{k:"code"' in 建.group(0) and '{k:"name"' in 建.group(0), 1)
    ck("⑦ 页面上不再有「新增店铺 / 编辑店铺 / 编辑门店 · 本期未实现」",
       not any(f"{x} · 本期未实现" in 页 for x in ("新增店铺", "编辑店铺", "编辑门店")), 3)

    print()
    if FAIL:
        print(f"❌ 店铺写口 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 店铺写口全过")


if __name__ == "__main__":
    main()
