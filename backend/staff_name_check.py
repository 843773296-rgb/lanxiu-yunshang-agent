# -*- coding: utf-8 -*-
"""客户类工具里的工号旁边带上姓名和岗位(用户 2026-10-25 拍)。真调 api 的三个工具。

起因:派回访任务那一轮,模型只拿得到「60000012」,回答里写「经手 60000012」,派任务时说不出「派给她的顾问顾晚」;
而员工表里名字一直都在。**工号那一栏原样留着**(判分器和检查按工号对),名字另起一栏。
期望值从库里现读(哪个客户有归属顾问、那个工号叫什么),不写死某个客户。
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import api

坏, 数 = [], [0]

咬合 = [
    ("会员详情不给归属顾问", "会员详情带归属顾问:工号 + 「姓名(岗位)」,和员工表一致"),
    ("查不到的工号编一个名字", "工号在员工表里查不到 → 不编名字"),
    ("停用的员工不标停用", "归属顾问已停用 → 名字旁边标出停用、派不了任务"),
    ("客户档案只认客户号", "客户档案按姓名也认得到人(唯一命中 → 给档案并注明认到哪个客户号)"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:200]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("客户类工具 · 工号旁边带姓名和岗位")
    db = sqlite3.connect(f"file:{os.path.join(HERE, 'lanxiu.db')}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    有 = db.execute("SELECT c.id, c.advisor_no, c.shop, s.name, s.role FROM customer c JOIN staff s ON s.no = c.advisor_no "
                   "WHERE c.advisor_no IS NOT NULL ORDER BY c.id LIMIT 1").fetchone()
    没 = db.execute("SELECT id FROM customer WHERE advisor_no IS NULL OR advisor_no = '' ORDER BY id LIMIT 1").fetchone()
    ck("库里有「带归属顾问」的客户可验(样本量不能是 0)", 有 is not None)
    if 有 is None:
        print("❌ 没东西可验 —— 这不叫通过"); return 1
    称呼 = api._员工称呼(有["advisor_no"])
    ck("样本里的归属顾问名字从员工表来(不是编的)", (称呼 or "").startswith(f"{有['name']}({有['role']}"), 称呼)

    c = api.get_customer(有["id"])
    ck("客户档案:归属顾问是「姓名(岗位)」,工号那一栏原样还在",
       c.get("归属顾问") == 称呼 and c.get("advisor_no") == 有["advisor_no"], c.get("归属顾问"))
    m = api.get_member(有["id"])
    ck("会员详情带归属顾问:工号 + 「姓名(岗位)」,和员工表一致",
       m.get("归属顾问") == {"工号": 有["advisor_no"], "是谁": 称呼}, m.get("归属顾问"))
    if 没 is not None:
        m2 = api.get_member(没["id"])
        ck("没有归属顾问的客户 → 明说「没有归属顾问」(不空着、不编)", m2.get("归属顾问") == "没有归属顾问", m2.get("归属顾问"))
    # 按姓名认人(10-25:模型说「没有按姓名查的工具」)—— 唯一的名字和重名的名字都从库里现找
    唯 = db.execute("SELECT id, name FROM customer WHERE name IS NOT NULL AND name<>'' GROUP BY name HAVING COUNT(*)=1 ORDER BY name LIMIT 1").fetchone()
    重 = db.execute("SELECT name FROM customer WHERE name IS NOT NULL AND name<>'' GROUP BY name HAVING COUNT(*)>1 ORDER BY name LIMIT 1").fetchone()
    if 唯 is not None:
        c2 = api.get_customer(唯["name"])
        ck("客户档案按姓名也认得到人(唯一命中 → 给档案并注明认到哪个客户号)",
           c2.get("id") == api._认客户(唯["name"])[0][0]["id"] and 唯["name"] in (c2.get("认人") or ""), c2.get("error") or c2.get("认人"))
    if 重 is not None:
        c3 = api.get_customer(重["name"])
        ck("姓名重名 → 只给候选不给档案", "error" in c3 and len(c3.get("候选") or []) >= 1 and "phone" not in c3, c3)
    ck("客户号姓名都对不上 → 明说不存在", "error" in api.get_customer("不存在的人ZZ"))
    # 只看本店(10-25):本店的人照样看得到 —— 别家店翻不到的那一半在边界审计里真攻击
    _t = api._ME.set({"no": "ZZ0003", "name": "(自造顾问)", "role": "顾问", "shop": 有["shop"]})
    try:
        c4 = api.get_customer(有["id"])
    finally:
        api._ME.reset(_t)
    ck("挂着同一家店的顾问,看得到本店客户的档案(限店不能把自己店也挡掉)", c4.get("id") == 有["id"], c4.get("error"))
    停 = db.execute("SELECT no, name FROM staff WHERE status<>'启用' ORDER BY no LIMIT 1").fetchone()
    if 停 is not None:
        ck("归属顾问已停用 → 名字旁边标出停用、派不了任务",
           (api._员工称呼(停["no"]) or "").startswith(停["name"]) and "派不了任务" in (api._员工称呼(停["no"]) or ""),
           api._员工称呼(停["no"]))
    在 = db.execute("SELECT no FROM staff WHERE status='启用' ORDER BY no LIMIT 1").fetchone()
    ck("在职的员工不标停用(别把所有人都标上)", "派不了" not in (api._员工称呼(在["no"]) or "派不了"), 在 and api._员工称呼(在["no"]))
    ck("工号在员工表里查不到 → 不编名字", api._员工称呼("99999999") is None and api._员工称呼(None) is None)

    api._ME.set({"no": "60000008", "name": "检查", "role": "总部运营", "shop": ""})
    h = api.customer_history(有["id"], 5)
    行 = ([h.get("最近一次")] if h.get("最近一次") else []) + list(h.get("按时间") or [])
    ck("接触史有记录可验(样本量)", len(行) > 0, h.get("error"))
    对 = [x for x in 行 if x.get("谁")]
    ck("接触史:每条经手人旁边都有「是谁」,和员工表一致;工号「谁」原样在",
       bool(对) and all(x.get("是谁") == api._员工称呼(x["谁"]) and x.get("是谁") for x in 对
                        if db.execute("SELECT 1 FROM staff WHERE no=?", (x["谁"],)).fetchone()),
       [(x.get("谁"), x.get("是谁")) for x in 对[:3]])
    print()
    if 坏:
        print(f"❌ 工号带姓名 {len(坏)} 条不过(验了 {数[0]} 条)")
        return 1
    print(f"✅ 工号带姓名:客户档案 / 会员详情 / 接触史(验了 {数[0]} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
