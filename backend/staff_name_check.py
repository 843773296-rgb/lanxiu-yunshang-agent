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
    有 = db.execute("SELECT c.id, c.advisor_no, s.name, s.role FROM customer c JOIN staff s ON s.no = c.advisor_no "
                   "WHERE c.advisor_no IS NOT NULL ORDER BY c.id LIMIT 1").fetchone()
    没 = db.execute("SELECT id FROM customer WHERE advisor_no IS NULL OR advisor_no = '' ORDER BY id LIMIT 1").fetchone()
    ck("库里有「带归属顾问」的客户可验(样本量不能是 0)", 有 is not None)
    if 有 is None:
        print("❌ 没东西可验 —— 这不叫通过"); return 1
    称呼 = f"{有['name']}({有['role']})"

    c = api.get_customer(有["id"])
    ck("客户档案:归属顾问是「姓名(岗位)」,工号那一栏原样还在",
       c.get("归属顾问") == 称呼 and c.get("advisor_no") == 有["advisor_no"], c.get("归属顾问"))
    m = api.get_member(有["id"])
    ck("会员详情带归属顾问:工号 + 「姓名(岗位)」,和员工表一致",
       m.get("归属顾问") == {"工号": 有["advisor_no"], "是谁": 称呼}, m.get("归属顾问"))
    if 没 is not None:
        m2 = api.get_member(没["id"])
        ck("没有归属顾问的客户 → 明说「没有归属顾问」(不空着、不编)", m2.get("归属顾问") == "没有归属顾问", m2.get("归属顾问"))
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
