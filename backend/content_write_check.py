#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容 / 活动 / 品类 / 页面写口的检查(11-14,台账第四十五条:「本期未实现」按钮第二组)。

**在库副本上真调 server 里的写口和 transit**,不在夹具里重写判定。

  ① 角色闸:店长调五个写口、切内容状态都被拒,被拒也进 op_log,表一行没动
     (原来的 save_content 谁登录都能建,作者还写死成 60000009)
  ② 新建出来的一律先「不对外」:内容 / 页面草稿、活动未开始;作者 / 录入人记真操作的人
  ③ 活动:结束不能早于开始;投放范围只能是门店或「全渠道」,门店码经 shop_key 填上
  ④ 品类:最多三级;直接挂着商品的品类下不许建下级;还有上架商品时不许停用
  ⑤ 内容发布 / 下架走状态机,发布时记发布时间
  ⑥ 日志记的字段 = UPDATE 真写的字段;入口交的是会话登录人;页面上这七个按钮不再是「本期未实现」
"""
from contextlib import closing
import os, re, sys, json, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []

咬合 = [
    ('把 save_category 的「三级下面不能再建」去掉', '④ 三级下面不能再建'),
    ('把 save_activity 的「结束不能早于开始」去掉', '③ 结束早于开始被拒'),
    ('把 _主数据闸 的「只总部运营」改成谁都放行', '① 店长调五个写口都被拒,被拒也留痕,表没动'),
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
    import server, oplog
    server.DB = oplog.DB = 副本
    assert server.DB == 副本 and oplog.DB == 副本, "库没切到副本"
    def q(sql, *a):
        with closing(sqlite3.connect(副本)) as _c:
            return [tuple(r) for r in _c.execute(sql, a).fetchall()]
    def 人(role):
        r = q("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", role)
        return dict(no=r[0][0], name=r[0][1], role=r[0][2], shop=r[0][3]) if r else None
    总部, 店长 = 人("总部运营"), 人("店长")
    ck("身份找得到(总部运营 / 店长)", bool(总部 and 店长), 2)
    if not (总部 and 店长): return
    表们 = ("content", "activity", "activity_cost", "page", "category")
    快照 = lambda: {t: q(f"SELECT * FROM {t} ORDER BY 1") for t in 表们}
    拒数 = lambda: q("SELECT COUNT(*) FROM op_log WHERE allowed=0")[0][0]
    店1 = q("SELECT code||' '||name, code FROM shop ORDER BY code LIMIT 1")[0]
    已有活动 = q("SELECT code FROM activity ORDER BY code LIMIT 1")[0][0]
    已有内容 = q("SELECT code FROM content WHERE status='草稿' ORDER BY code LIMIT 1")

    print("\n① 角色闸")
    前, 拒前 = 快照(), 拒数()
    rs = [server.save_content(dict(title="店长建的"), 店长),
          server.save_activity(dict(name="店长建的", kind="门店", start_d="2026-12-01", end_d="2026-12-02", shop=店1[0]), 店长),
          server.add_activity_cost(dict(activity=已有活动, item="店长录的", amount=1), 店长),
          server.save_page(dict(name="店长建的", channel="小程序"), 店长),
          server.save_category(dict(name="店长建的"), 店长)]
    ck("① 店长调五个写口都被拒,被拒也留痕,表没动",
       all(r.get("code") == "WRONG_ROLE" for r in rs) and 拒数() - 拒前 == 5 and 快照() == 前, len(rs),
       json.dumps([r.get("code") for r in rs], ensure_ascii=False))
    if 已有内容:
        t = server.transit("bk-content", 已有内容[0][0], "已发布", {}, 店长["name"], me=店长)
        ck("① 店长发布内容被拒", t.get("code") == "WRONG_ROLE" and 快照() == 前, 1, t.get("code"))

    print("\n② 内容")
    最大 = max(int(c[2:]) for (c,) in q("SELECT code FROM content") if c[2:].isdigit())
    r = server.save_content(dict(title="检查新内容", kind="工艺科普", channel="门店Pad"), 总部)
    行 = q("SELECT code,status,author,published FROM content WHERE code=?", r.get("id") or "")
    ck("② 总部新建内容:草稿、作者是本人、编码接着最大号往下(不按条数推)",
       r.get("ok") and 行 == [(f"CT{最大 + 1}", "草稿", 总部["no"], None)], 1, json.dumps(行, ensure_ascii=False))
    ck("② 内容类型不在名单里被拒", server.save_content(dict(title="x", kind="乱写"), 总部).get("code") == "BAD_KIND", 1)
    新码 = r.get("id")
    r2 = server.save_content(dict(code=新码, title="检查新内容改", kind="工艺科普", channel="门店Pad"), 总部)
    最后 = q("SELECT changes FROM edit_log WHERE obj='内容' AND target=? ORDER BY id DESC LIMIT 1", 新码 or "")
    ck("② 只改标题 → 日志只记「标题」", r2.get("ok") and 最后 and [x["字段"] for x in json.loads(最后[0][0])] == ["标题"], 1)

    print("\n⑤ 发布 / 下架")
    t = server.transit("bk-content", 新码, "已发布", {}, 总部["name"], me=总部)
    发 = q("SELECT status, published FROM content WHERE code=?", 新码)
    ck("⑤ 总部发布:状态已发布,记了发布时间", t.get("ok") and 发[0][0] == "已发布" and bool(发[0][1]), 1, json.dumps(发, ensure_ascii=False))
    t = server.transit("bk-content", 新码, "草稿", {}, 总部["name"], me=总部)
    ck("⑤ 下架 = 退回草稿", t.get("ok") and q("SELECT status FROM content WHERE code=?", 新码)[0][0] == "草稿", 1)

    print("\n③ 活动")
    r = server.save_activity(dict(name="检查活动", kind="门店", start_d="2026-12-01", end_d="2026-12-31",
                                  shop=店1[0], budget="5000"), 总部)
    行 = q("SELECT status, shop_code, budget FROM activity WHERE code=?", r.get("id") or "")
    ck("③ 新活动「未开始」,门店码填上", r.get("ok") and 行 == [("未开始", 店1[1], 5000.0)], 1, json.dumps([r.get("code"), 行], ensure_ascii=False))
    r = server.save_activity(dict(name="全渠道活动", kind="线上", start_d="2026-12-01", end_d="2026-12-31", shop="全渠道"), 总部)
    ck("③ 全渠道活动门店码留空", r.get("ok") and q("SELECT shop_code FROM activity WHERE code=?", r["id"]) == [(None,)], 1)
    r = server.save_activity(dict(name="倒着的", kind="线上", start_d="2026-12-31", end_d="2026-12-01", shop="全渠道"), 总部)
    ck("③ 结束早于开始被拒", r.get("code") == "BAD_DATE", 1, r.get("code"))
    r = server.save_activity(dict(name="没这家店", kind="门店", start_d="2026-12-01", end_d="2026-12-02", shop="SH999 没这家店"), 总部)
    ck("③ 投放到不存在的门店被拒", r.get("code") == "BAD_SHOP", 1, r.get("code"))
    r0 = server.add_activity_cost(dict(activity=已有活动, item="x", amount=0), 总部)
    r1 = server.add_activity_cost(dict(activity=已有活动, item="检查费用", amount="123.456", note="已开票"), 总部)
    费 = q("SELECT amount, created_by FROM activity_cost WHERE activity=? AND item='检查费用'", 已有活动)
    ck("③ 费用:0 元被拒;正常一笔记两位小数、录入人是本人工号",
       r0.get("code") == "BAD_AMOUNT" and r1.get("ok") and 费 == [(123.46, 总部["no"])], 2, json.dumps(费, ensure_ascii=False))

    print("\n② 页面")
    r = server.save_page(dict(name="检查页", channel="小程序"), 总部)
    ck("② 新页面草稿", r.get("ok") and q("SELECT status FROM page WHERE code=?", r.get("id") or "") == [("草稿",)], 1)
    ck("② 同渠道重名被拒", server.save_page(dict(name="检查页", channel="小程序"), 总部).get("code") == "DUP_NAME", 1)

    print("\n④ 品类")
    三级 = q("SELECT code FROM category WHERE length(code)=7 LIMIT 1")
    挂商品的 = q("SELECT c.code FROM category c WHERE EXISTS(SELECT 1 FROM product p WHERE p.category=c.code) AND length(c.code)<7 LIMIT 1")
    二级空 = q("SELECT c.code FROM category c WHERE length(c.code)=5 AND NOT EXISTS(SELECT 1 FROM product p WHERE p.category=c.code) LIMIT 1")
    有上架 = q("SELECT c.code FROM category c WHERE length(c.code)=3 AND EXISTS(SELECT 1 FROM product p WHERE p.status='上架' AND p.category LIKE c.code||'%') LIMIT 1")
    ck("④ 样本都找得到(三级 / 空的二级 / 下面有上架商品的一级)", bool(三级 and 二级空 and 有上架), 3)
    if 三级:
        r = server.save_category(dict(name="第四级", parent=三级[0][0]), 总部)
        ck("④ 三级下面不能再建", r.get("code") == "TOO_DEEP", 1, r.get("code"))
    if 挂商品的:
        r = server.save_category(dict(name="下级", parent=挂商品的[0][0]), 总部)
        ck("④ 直接挂着商品的品类下面不能建下级", r.get("code") == "PARENT_HAS_PRODUCTS", 1, r.get("code"))
    else:
        print("  ℹ️ 库里没有「非末级却直接挂商品」的品类 —— 这条没东西可验(不是通过)")
    if 二级空:
        r = server.save_category(dict(name="检查三级", parent=二级空[0][0]), 总部)
        ck("④ 空的二级下面能建三级,编码 = 上级 + 两位", r.get("ok") and str(r.get("id", "")).startswith(二级空[0][0])
           and len(r.get("id", "")) == 7, 1, r.get("id"))
    if 有上架:
        r = server.save_category(dict(code=有上架[0][0], name=q("SELECT name FROM category WHERE code=?", 有上架[0][0])[0][0],
                                      status="停用"), 总部)
        ck("④ 还有上架商品时不许停用", r.get("code") == "HAS_ON_SHELF"
           and q("SELECT status FROM category WHERE code=?", 有上架[0][0]) == [("启用",)], 1, r.get("code"))

    print("\n⑥ 日志 / 入口 / 页面")
    src = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    for 表, 名单 in (("content", server.内容字段名), ("category", server.品类字段名)):
        # 认「⚠️ SET 的字段 = …字段名」那行注释下面的那条 —— 同一张表还有别的 UPDATE(发布时记发布时间)
        m = re.search(rf'# ⚠️ SET 的字段 = \w+字段名[^\n]*\n\s*c\.execute\("UPDATE {表} SET ([^"]+?) WHERE code=\?', src)
        写的 = sorted(x.split("=")[0].strip() for x in m.group(1).split(",")) if m else []
        ck(f"⑥ {表}:日志记的字段 = UPDATE 真写的字段", 写的 == sorted(名单), len(写的), f"{写的} / {sorted(名单)}")
    路由 = [("content-save", "save_content"), ("activity-save", "save_activity"),
            ("activity-cost-add", "add_activity_cost"), ("page-save", "save_page"), ("category-save", "save_category")]
    接 = [u for u, f in 路由 if re.search(rf'if p=="/api/{u}": return self\._send\({f}\(body, 登录人\)\)', src)]
    ck("⑥ 五个入口都把会话登录人交给写口", len(接) == len(路由), len(路由), f"接上的 {接}")
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    残 = [x for x in ("新建品类", "编辑品类", "编辑内容", "下架", "新建活动", "添加费用", "新增页面") if f"{x} · 本期未实现" in 页]
    ck("⑥ 页面上这七个按钮不再是「本期未实现」", not 残, 7, f"还剩 {残}")
    for u in ("category-save", "content-save", "activity-save", "activity-cost-add", "page-save"):
        if f'"/api/{u}"' not in 页:
            FAIL.append(f"页面没发 /api/{u}"); print(f"  ❌ 页面没有发往 /api/{u} 的地方")

    print()
    if FAIL:
        print(f"❌ 内容 / 活动 / 品类 / 页面写口 {len(FAIL)} 条不过:" + "、".join(FAIL)); sys.exit(1)
    print("✅ 内容 / 活动 / 品类 / 页面写口全过")


if __name__ == "__main__":
    main()
