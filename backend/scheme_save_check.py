#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案保存 · 客户和版型真的存进去了 · 检查(10-20 外部复审 3.1)。

原来校验读 `pt`(页面发的就是它),新建入库却读 `customer_id` / `pattern` —— 页面从来不发这两个名字,
于是按选中的版型校验通过、库里客户和版型是空的;编辑那条不碰这两列;执行人写死「魏欣新」、顾问写死「A01 林岚」。
**接口返回 ok 不算数,回读库里那一行才算。** 全在库副本上跑。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("新建时又去读 customer_id(页面不发这个名字)", "新建:页面发的客户和版型都存进去了(回读库里那一行)"),
    ("编辑那条不更新客户和版型", "编辑:换了客户和版型,库里跟着变"),
    ("选了库里没有的客户也照存", "选了一个库里没有的客户 → 拒,而且一行都没写"),
    ("保存时不把名字翻成编码(页面发什么存什么)", "照页面的发法(按钮发名字)存"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


print("方案保存 · 客户和版型真的存进去了")
print("=" * 80)
import oplog, scheme as SCH, server as SV   # noqa: E401 —— 先加载,用副本才改得到它们的 DB
import check_copy
db = check_copy.用副本("scheme-save-")

# 夹具:固定组合(编号来自知识库推导,不取库里碰巧存着的方案);先确认它仍然合法,不合法就明说
组 = dict(xz="XZ04", mt="MT02", kf=["KF02", "KF03"], color="胭脂", ps=["云肩", "腰封"])
合法, _ = SCH.validate(**组, pattern="PT06", size=None, need_date=None, scope="局部", workers=2)
c = sqlite3.connect(db)
客 = [r[0] for r in c.execute("SELECT id FROM customer ORDER BY id LIMIT 2")]
c.close()
if not 合法 or len(客) < 2:
    ck("夹具:固定组合仍合法、库里有两位客户 —— 不是这样就没验,不算通过", False, (合法, 客))
else:
    甲, 乙 = 客
    me = {"no": "60000002", "name": "检查顾问", "role": "顾问"}
    def 行(sid):
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM scheme WHERE id=?", (sid,)).fetchone(); con.close()
        return dict(r) if r else None

    r1 = SV.scheme_save(dict(组, id="SC-检查1", name="检查", cust=甲, pt="PT06"), me=me)
    l1 = 行("SC-检查1")
    ck("新建:页面发的客户和版型都存进去了(回读库里那一行)",
       r1.get("ok") and l1 and l1["customer_id"] == 甲 and l1["pattern"] == "PT06", (r1.get("reason"), l1))
    ck("新建:顾问是登录的那个人的工号(不是写死的 A01 林岚)", l1 and l1["advisor_no"] == "60000002", l1 and l1["advisor_no"])
    ck("接口回的 saved 就是库里那一行(页面据此告诉人存了什么)",
       (r1.get("saved") or {}).get("customer_id") == 甲 and (r1.get("saved") or {}).get("pattern") == "PT06", r1.get("saved"))

    r2 = SV.scheme_save(dict(组, id="SC-检查1", name="检查", cust=乙, pt="PT03"), me=me)
    l2 = 行("SC-检查1")
    ck("编辑:换了客户和版型,库里跟着变", r2.get("ok") and l2 and l2["customer_id"] == 乙 and l2["pattern"] == "PT03",
       (r2.get("reason"), l2))

    SV.scheme_save(dict(组, id="SC-检查2", name="检查甲", cust=甲, pt="PT06"), me=me)
    SV.scheme_save(dict(组, id="SC-检查3", name="检查乙", cust=乙, pt="PT03"), me=me)
    l2a, l3 = 行("SC-检查2"), 行("SC-检查3")
    ck("两个客户各存一套,不串", l2a and l3 and (l2a["customer_id"], l2a["pattern"]) == (甲, "PT06")
       and (l3["customer_id"], l3["pattern"]) == (乙, "PT03"), (l2a, l3))

    r4 = SV.scheme_save(dict(组, id="SC-检查4", name="检查", cust="C-不存在", pt="PT06"), me=me)
    ck("选了一个库里没有的客户 → 拒,而且一行都没写", not r4.get("ok") and r4.get("code") == "NO_CUSTOMER"
       and 行("SC-检查4") is None, r4)

    r5 = SV.scheme_save(dict(组, id="SC-检查5", name="检查", cust="", pt=None), me=me)
    l5 = 行("SC-检查5")
    ck("不选客户(试算)照旧能存,客户和版型就是空,不猜一个", r5.get("ok") and l5 and l5["customer_id"] is None
       and l5["pattern"] is None, (r5.get("reason"), l5))

    # ── 照**页面真发的**样子存(10-22 加):页面按钮发的是名字,不是编码 ──
    # 上面那几条的夹具发的是编码(XZ04 / MT02),而页面从来不这么发 —— 所以 10-20 那次修完一直绿,
    # 页面真存一次库里落的却是名字。名字从库里现取(不手抄,改名了这里跟着变)。
    con = sqlite3.connect(db)
    名 = {k: con.execute("SELECT name FROM craft WHERE code=?", (k,)).fetchone()[0] for k in ("XZ04", "MT02", "KF02", "KF03")}
    con.close()
    r6 = SV.scheme_save(dict(组, id="SC-检查6", name="检查", cust=甲, pt="PT06",
                             xz=名["XZ04"], mt=名["MT02"], kf=[名["KF02"], 名["KF03"]]), me=me)
    l6 = 行("SC-检查6")
    ck("照页面的发法(按钮发名字)存:库里形制 / 面料 / 工艺落的是编码,不是名字",
       r6.get("ok") and l6 and (l6["xz"], l6["mt"], l6["kf"]) == ("XZ04", "MT02", "KF02,KF03"),
       (r6.get("reason"), l6 and (l6["xz"], l6["mt"], l6["kf"]), 名))
    r7 = SV.scheme_save(dict(组, id="SC-检查7", name="检查", cust=甲, pt="PT06", mt="一种库里没有的面料"), me=me)
    ck("发一个认不出的面料名 → 拒(说清是哪一样认不出),而且一行都没写",
       not r7.get("ok") and r7.get("code") == "BAD_OPTION" and "一种库里没有的面料" in (r7.get("reason") or "")
       and 行("SC-检查7") is None, r7)

    con = sqlite3.connect(db)
    谁 = con.execute("SELECT actor FROM op_log WHERE machine='fe-scheme' AND target='SC-检查1' ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    ck("操作日志的执行人是登录的那个人(不是写死的魏欣新)", 谁 and "60000002" in 谁[0], 谁)

源 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
ck("保存接口走 scheme_save、身份从登录态取", 'r=scheme_save(body, me=_me(self))' in 源)
页 = open(os.path.join(ROOT, "agentsite", "web", "scheme.html"), encoding="utf-8").read()
ck("方案页说清哪些会存、哪些只是试算;方案列表显示客户和版型",
   'id="savedNote"' in 页 and "只用来试算、不会存" in 页 and "r.customer_id?" in 页 and "r.pattern?" in 页)

print()
if 坏:
    print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 方案保存:客户和版型存得进、改得动、不串单、挂错人会拒、按钮发名字也落编码(验了 {n} 条){D}")
