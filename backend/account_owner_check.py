"""账户归属检查 —— 一个账户只归一位导购(用户 2026-10-26 拍)。

两件事分开验:
  ① **代码对不对**:自己造的小库上真调 account_owner(定归属的四种情形、同户档案、整户转、修存量)——
     造的样本永远在,本机和 CI 都真验得到;
  ② **这个库现在守没守住**:真库里「一个账户两位导购」必须是 0,并报验了多少个账户(0 个账户 → 红)。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import account_owner as AO  # noqa: E402

# 咬合(10-26 用 tools/bite_run.py 真重放过,规格在 tools/bite_specs.json)
咬合 = [
    ("定归属不再跳过停用的导购(删掉 `and 在职.get(...)`)",
     "最近那位已停用 → 顺延给下一位在职的(不归给派不了任务的人)"),
    ("改导购退回成只改点名的那一条(`全 = list(ids)`)",
     "转一位 = 整户转(c3 转给 B,同户的 c4 也跟着)"),
]

过, 挂 = [0], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}" + ("" if 真 or not 补 else f"  {补}"))
    if 真:
        过[0] += 1
    else:
        挂.append(名)


def 小库():
    c = sqlite3.connect(":memory:")
    c.executescript("""
      CREATE TABLE staff(no TEXT, name TEXT, role TEXT, status TEXT);
      CREATE TABLE customer(id TEXT, account_id TEXT, advisor_no TEXT, last_interact TEXT, created TEXT,
                            shop TEXT, shop_code TEXT, merged_into TEXT);
      CREATE TABLE appointment(customer_id TEXT, advisor_no TEXT, status TEXT);
      INSERT INTO staff(no, name, role, status) VALUES('A','甲','顾问','启用'),('B','乙','顾问','启用'),('X','停','顾问','停用'),('Y','停二','顾问','停用');
      -- U1 跨店:最近接触在 S2 → 整户归 B、搬到 S2
      INSERT INTO customer(id, account_id, advisor_no, last_interact, created, shop, shop_code, merged_into) VALUES('c1','U1','A','2026-09-01','2025-01-01','一店','S1',''),
                                 ('c2','U1','B','2026-10-01','2026-01-01','二店','S2','');
      -- U2 最近那位已停用 → 顺延给 A
      INSERT INTO customer(id, account_id, advisor_no, last_interact, created, shop, shop_code, merged_into) VALUES('c3','U2','X','2026-10-20','2026-01-01','一店','S1',''),
                                 ('c4','U2','A','2026-08-01','2025-01-01','一店','S1','');
      -- U3 全停用 → 没法定
      INSERT INTO customer(id, account_id, advisor_no, last_interact, created, shop, shop_code, merged_into) VALUES('c5','U3','X','2026-10-20','2026-01-01','一店','S1',''),
                                 ('c6','U3','Y','2026-08-01','2025-01-01','一店','S1','');
      -- U4 只有一条,没冲突;c8 已被合并掉,不算同户
      INSERT INTO customer(id, account_id, advisor_no, last_interact, created, shop, shop_code, merged_into) VALUES('c7','U4','A','2026-08-01','2025-01-01','一店','S1',''),
                                 ('c8','U4','B','2026-08-01','2025-01-01','一店','S1','c7');
      INSERT INTO appointment(customer_id, advisor_no, status) VALUES('c1','A','已预约'),('c1','A','已完成');
    """)
    return c


def main():
    print("账户归属 · 一个账户只归一位导购")
    在职 = {"A": True, "B": True, "X": False, "Y": False}
    d = lambda i, a, li, cr="2026-01-01": dict(id=i, advisor_no=a, last_interact=li, created=cr)
    print("▸ ① 定归属(自造样本)")
    ck("最近接触那条的导购赢", AO.定归属([d("1", "A", "2026-09-01"), d("2", "B", "2026-10-01")], 在职)["id"] == "2")
    ck("最近那位已停用 → 顺延给下一位在职的(不归给派不了任务的人)",
       AO.定归属([d("1", "X", "2026-10-20"), d("2", "A", "2026-08-01")], 在职)["id"] == "2")
    ck("同一天打平 → 取建档更晚的", AO.定归属([d("1", "A", "2026-10-01", "2025-01-01"), d("2", "B", "2026-10-01", "2026-03-01")], 在职)["id"] == "2")
    ck("一个在职的都没有 → None(交人定,不猜)", AO.定归属([d("1", "X", "2026-10-20"), d("2", "Y", "2026-08-01")], 在职) is None)

    print("▸ ② 同户 / 整户转 / 修存量(自造小库)")
    c = 小库()
    ck("同户档案:带上同账户的另一条,不带已合并掉的", AO.同户档案(c, ["c1"]) == ["c1", "c2"] and AO.同户档案(c, ["c7"]) == ["c7"])
    ck("修存量前:冲突账户 = U1、U2、U3", AO.冲突账户(c) == ["U1", "U2", "U3"], AO.冲突账户(c))
    结果 = {r["账户"]: r for r in AO.统一(c, 做=True)}
    ck("U1 跨店 → 整户归 B、搬到二店", [tuple(r) for r in c.execute("SELECT advisor_no, shop_code FROM customer WHERE account_id='U1'")] == [("B", "S2")] * 2)
    ck("U2 最近的已停用 → 整户归 A", {r[0] for r in c.execute("SELECT advisor_no FROM customer WHERE account_id='U2'")} == {"A"})
    ck("U3 全停用 → 标「没法定」、一个字没改", 结果["U3"]["没法定"] and AO.冲突账户(c) == ["U3"], AO.冲突账户(c))
    ck("未完成的预约跟着迁,已完成的不动",
       sorted(tuple(r) for r in c.execute("SELECT advisor_no, status FROM appointment")) == [("A", "已完成"), ("B", "已预约")])
    AO.改导购(c, ["c3"], "B")
    ck("转一位 = 整户转(c3 转给 B,同户的 c4 也跟着)", {r[0] for r in c.execute("SELECT advisor_no FROM customer WHERE account_id='U2'")} == {"B"})

    print("▸ ③ 真库现在守没守住")
    库 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanxiu.db")
    r = sqlite3.connect(库)
    n = r.execute("SELECT COUNT(DISTINCT account_id) FROM customer WHERE COALESCE(account_id,'')!='' AND COALESCE(merged_into,'')=''").fetchone()[0]
    ck(f"验了 {n} 个有档案的账户(0 个 → 是没扫到东西,不是都通过)", n > 0)
    冲 = AO.冲突账户(r)
    ck("没有「一个账户两位导购」", not 冲, f"{len(冲)} 个:{冲[:5]} —— 跑 python3 tools/unify_account_advisor.py 看归谁")
    print()
    print(f"{'❌' if 挂 else '✅'} 账户归属 过 {过[0]} / 挂 {len(挂)}" + (f":{' / '.join(挂)}" if 挂 else ""))
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
