#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商机提醒进顾问待办 —— 回捞 / 满足确认 / 偏好回捞,**规则只提示,顾问选结论才改**(用户 2026-10-03 定)。

演示数据里没有「商机之后客户又下单」的(商机都是按今天的通话建的,订单都在之前),
所以**在库副本里造一整套场景**,照顾问真实会走的路走一遍:

    客户想要红色马面裙 → 买了一条蓝色马面裙 → 系统派「满足了吗」→ 顾问不选结论完成不了
    → 选「满足了」→ 商机已成交、红色进偏好 → 上新红色 → 派「偏好回捞」
    → 客户说不要了 → 偏好作废 → 再上新也不推

全部在库副本上跑,不碰主库。
"""
import datetime as _dt, json, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "knowledge")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

咬合 = [
    ("满足扫描直接把商机改成已成交(不等顾问)", "满足扫描只派提醒,商机状态不动"),
    ("结论不核清单(`if 结论 not in 表` 那一支去掉)", "选了不属于这种提醒的结论 → 不收"),
    ("回捞不看偏好作没作废(`WHERE retired_at IS NULL` 去掉)", "客户说不要了的偏好,再上新也不推"),
    ("完成商机提醒不要结论(tasks.finish_task 里那段跳过)", "不选结论完成不了"),
]

坏 = 0


def ck(名, ok, n, 说明=""):
    global 坏
    if n == 0:
        print(f"  {R}❌{D} {名} —— **没扫到东西**,不是通过"); 坏 += 1; return
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}(验了 {n} 个){'' if ok else '  ' + 说明}")
    坏 += 0 if ok else 1


def main():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
    import tasks, oplog, opportunity_store as S
    tasks.DB = db; oplog.DB = db
    c = sqlite3.connect(db); S.建表(c)
    今天 = _dt.date(2026, 10, 3)
    # 场景用的人和货,**现取**
    顾问 = c.execute("SELECT s.no, s.name, s.role, s.shop, cu.id FROM customer cu JOIN staff s ON s.no=cu.advisor_no "
                     "WHERE s.status='启用' AND s.role='顾问' ORDER BY cu.id LIMIT 2").fetchall()
    外人 = c.execute("SELECT no, name, role, shop FROM staff WHERE role='顾问' AND status='启用' AND no<>? LIMIT 1",
                     (顾问[0][0],)).fetchone()
    蓝马 = c.execute("SELECT s.spu, s.code FROM sku s JOIN color_family f ON f.color=s.color JOIN product p ON p.spu=s.spu "
                     "JOIN pattern t ON t.code=p.pattern JOIN craft k ON k.code=t.xz "
                     "WHERE f.family='蓝' AND k.name LIKE '%马面裙%' ORDER BY s.code LIMIT 1").fetchone()
    披帛 = c.execute("SELECT s.spu, s.code FROM sku s JOIN product p ON p.spu=s.spu JOIN category k ON k.code=p.category "
                     "WHERE k.name='披帛' ORDER BY s.code LIMIT 1").fetchone()
    红 = c.execute("SELECT p.spu FROM product p WHERE p.status='上架' AND EXISTS(SELECT 1 FROM sku s JOIN color_family f "
                   "ON f.color=s.color WHERE s.spu=p.spu AND f.family='红') ORDER BY p.spu LIMIT 1").fetchone()
    if len(顾问) < 2 or not (外人 and 蓝马 and 披帛 and 红):
        print(f"  {R}❌{D} 造场景要的人和货取不全 —— 没扫到东西,不是通过"); return 1
    me = dict(no=顾问[0][0], name=顾问[0][1], role=顾问[0][2], shop=顾问[0][3]); 客 = 顾问[0][4]
    me2 = dict(no=外人[0], name=外人[1], role=外人[2], shop=外人[3])

    def 建商机(cid, call, 状态, 等=None):
        oid = S.从通话建(c, call, cid, None, [("形制", "马面裙", "我想要一条马面裙"), ("颜色", "红", "要正红的那种")],
                        f"{今天} 10:00")
        S.改状态(c, oid, "跟进中", f"{今天} 10:00", 经手人="X")
        if 状态 == "搁置等供给":
            S.改状态(c, oid, "搁置等供给", f"{今天} 10:00", 等什么=等)
        return oid

    def 下单(cid, oid_r, spu, sku):
        c.execute("INSERT INTO ordr(id, customer_id, kind, status, created) VALUES(?,?,?,?,?)",
                  (oid_r, cid, "标品订单", "完成", f"{今天} 12:00"))
        c.execute("INSERT INTO ordr_item(order_id, spu, sku, qty) VALUES(?,?,?,?)", (oid_r, spu, sku, 1))

    任务 = lambda tid: c.execute("SELECT status, assignee_no, assigned_by, type, customer_id FROM schedule WHERE id=?",
                                 (tid,)).fetchone()
    商机 = lambda oid: c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()[0]

    print("\n\033[1m▸ 满足确认:客户想要红色马面裙,买了蓝色马面裙\033[0m")
    A = 建商机(客, "CT-A", "跟进中")
    下单(客, "OT-A1", 蓝马[0], 蓝马[1]); c.commit()
    派 = S.满足扫描(c, 今天); c.commit()
    ck("同形制的单 → 给归属顾问派「满足确认」,系统派的", len(派) == 1 and 任务(派[0])[1] == me["no"]
       and 任务(派[0])[2] == "SYS" and 任务(派[0])[3] == "商机提醒", len(派) or 1, str([任务(t) for t in 派]))
    ck("满足扫描只派提醒,商机状态不动(顾问点头才算)", 商机(A) == "跟进中", 1, 商机(A))
    tA = 派[0] if 派 else "?"
    细 = json.loads(c.execute("SELECT detail FROM opportunity_task WHERE schedule_id=?", (tA,)).fetchone()[0])
    ck("提醒里写清对上了什么、没对上什么(买的是蓝色,红色没对上)",
       {"维度": "颜色", "值": "红"} in 细["没对上"] and {"维度": "形制", "值": "马面裙"} in 细["对上"], 1, str(细))
    ck("同一张单不重复问", not S.满足扫描(c, 今天), 1)

    # ⚠️ 先测「选错」再测「不选」:顺序反了的话,拆掉结论闸时「不选」那一步先把任务完成了,
    #    「选错」那一步会因为「任务已完结」被拒 —— 看着照样绿,咬合咬不住(10-03 踩过)
    r = tasks.finish_task(dict(id=tA, summary="电话问过了客户", conclusion="客户不要了"), me)
    ck("选了不属于这种提醒的结论 → 不收", not r.get("ok") and 商机(A) == "跟进中", 1, str(r))
    r = tasks.finish_task(dict(id=tA, summary="电话问过了客户"), me)
    ck("不选结论完成不了,并告诉他能选哪几个", not r.get("ok") and r.get("可选结论") == ["满足了", "没满足,继续跟"]
       and 任务(tA)[0] == "有效", 1, str(r))
    r = tasks.finish_task(dict(id=tA, summary="电话问过了客户", conclusion="满足了"), me2)
    ck("别人的提醒完成不了(谁做的谁点)", not r.get("ok"), 1, str(r))
    r = tasks.finish_task(dict(id=tA, summary="客户说蓝色也很喜欢,这单就是这件事", conclusion="满足了"), me)
    偏 = c.execute("SELECT dim, val, quote, confirmed_by FROM customer_pref WHERE opp_id=?", (A,)).fetchall()
    ck("选「满足了」→ 商机已成交、任务完结", r.get("ok") and 商机(A) == "已成交" and 任务(tA)[0] == "完结", 1, str(r))
    ck("没对上的红色记进客户偏好,带原话、记着哪个顾问点的头",
       偏 == [("颜色", "红", "要正红的那种", me["no"])], len(偏) or 1, str(偏))

    print("\n\033[1m▸ 不该提示的\033[0m")
    B = 建商机(顾问[1][4], "CT-B", "跟进中")
    下单(顾问[1][4], "OT-B1", 披帛[0], 披帛[1]); c.commit()
    ck("诉求是马面裙,只买了一条披帛 → 不提示", not [t for t in S.满足扫描(c, 今天)
                                              if c.execute("SELECT opp_id FROM opportunity_task WHERE schedule_id=?",
                                                           (t,)).fetchone()[0] == B], 1)

    print("\n\033[1m▸ 偏好回捞:上新红色 → 再推一遍 → 客户说不要了 → 不再推\033[0m")
    出 = S.回捞(c, [红[0]], 今天); c.commit()
    pt = c.execute("SELECT schedule_id FROM opportunity_task WHERE opp_id=? AND kind='偏好回捞'", (A,)).fetchone()
    ck("上新对上了偏好 → 派「偏好回捞」给归属顾问", bool(pt) and 任务(pt[0])[1] == me["no"], 1, str(出))
    if pt:
        r = tasks.finish_task(dict(id=pt[0], summary="客户说红色不想要了,蓝色够了", conclusion="客户说不要了"), me)
        作废 = c.execute("SELECT retired_by FROM customer_pref WHERE opp_id=?", (A,)).fetchone()[0]
        ck("选「客户说不要了」→ 偏好作废(留着行,记着谁作废的)", r.get("ok") and 作废 == me["no"], 1, str(r))
    以后 = 今天 + _dt.timedelta(days=200)       # 过了 90 天冷却
    S.回捞(c, [红[0]], 以后); c.commit()
    ck("客户说不要了的偏好,再上新也不推",
       c.execute("SELECT COUNT(*) FROM opportunity_task WHERE opp_id=? AND kind='偏好回捞'", (A,)).fetchone()[0] == 1, 1)

    print("\n\033[1m▸ 回捞:搁置等红色 → 上新红色 → 客户想看\033[0m")
    C = 建商机(顾问[1][4], "CT-C", "搁置等供给", 等={"颜色": "红"}); c.commit()
    S.回捞(c, [红[0]], 以后); c.commit()
    ct = c.execute("SELECT schedule_id FROM opportunity_task WHERE opp_id=? AND kind='回捞'", (C,)).fetchone()
    ck("搁置的商机上新对上了 → 派「回捞」", bool(ct), 1)
    if ct:
        me_b = dict(no=顾问[1][0], name=顾问[1][1], role=顾问[1][2], shop=顾问[1][3])
        r = tasks.finish_task(dict(id=ct[0], summary="客户周末来看", conclusion="客户想看,继续跟"), me_b)
        ck("选「客户想看,继续跟」→ 商机回到跟进中", r.get("ok") and 商机(C) == "跟进中", 1, str(r))

    print("\n\033[1m▸ 偏好回捞 → 客户想看 → 按偏好新开一条商机\033[0m")
    me_b = dict(no=顾问[1][0], name=顾问[1][1], role=顾问[1][2], shop=顾问[1][3]); 客b = 顾问[1][4]
    E = 建商机(客b, "CT-E", "跟进中")
    下单(客b, "OT-E1", 蓝马[0], 蓝马[1]); c.commit()
    te = [t for t in S.满足扫描(c, 今天) if c.execute("SELECT opp_id FROM opportunity_task WHERE schedule_id=?",
                                                     (t,)).fetchone()[0] == E]
    c.commit()          # 完成任务走的是另一个连接 —— 不提交它看不见这条任务
    if te:
        tasks.finish_task(dict(id=te[0], summary="客户说这单就是这件事", conclusion="满足了"), me_b)
    再后 = 以后 + _dt.timedelta(days=100)
    S.回捞(c, [红[0]], 再后); c.commit()
    pe = c.execute("SELECT schedule_id FROM opportunity_task WHERE opp_id=? AND kind='偏好回捞'", (E,)).fetchone()
    新 = None
    if pe:
        r = tasks.finish_task(dict(id=pe[0], summary="客户想看看红色的", conclusion="客户想看,新开商机"), me_b)
        新 = c.execute("SELECT id, status, source FROM opportunity WHERE source='历史诉求' AND customer_id=?",
                      (客b,)).fetchone()
    ck("选「客户想看,新开商机」→ 新开一条「历史诉求」商机,直接跟进中(顾问已经点过头)",
       bool(新) and 新[1] == "跟进中", 1, str(新))
    if 新:
        q = c.execute("SELECT dim, val, quote FROM opportunity_need WHERE opp_id=?", (新[0],)).fetchall()
        ck("新商机的诉求带着当初那句原话", q == [("颜色", "红", "要正红的那种")], 1, str(q))

    c.close(); shutil.rmtree(tmp, ignore_errors=True)
    print()
    if 坏:
        print(f"{R}❌ 商机提醒 {坏} 条不过{D}"); return 1
    print(f"{G}✅ 商机提醒全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
