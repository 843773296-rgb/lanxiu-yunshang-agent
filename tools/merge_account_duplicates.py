"""修存量:同一个账户底下的重复档案,按合并标准判过的软合并(用户 2026-10-26 拍「还是合并」)。

账户统一导购之后,有些账户底下挂着两条没合并的门店档案。这里逐对用 merge.判同一人(提示词 TK05 的代码版)判:
  · 同一人   → merge.并入(软合并:副档标 merged_into,一行数据不搬,能撤,写 op_log)
  · 不同人 / 判不了 → 不动,列出来交人

⚠️ 其中有 C21* —— 造数时故意建的「客户合并」评测用例,和真实客户 C100xx 同名同号,账户统一后落进了同一个账户。
用户知道合并会让那一组评测题的标准答案对不上、要另外重造,仍然拍了合并(10-26)。

  python3 tools/merge_account_duplicates.py            # 演练:只列出每对怎么判,不写
  python3 tools/merge_account_duplicates.py --做       # 真合并(写库前先拿锁:./tools/gate_lock.sh)
  python3 tools/merge_account_duplicates.py --库 <路径> # 指定库(演练副本用)
"""
import os
import sqlite3
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "backend"))
import merge as MG  # noqa: E402

执行人 = {"name": "账户重复档案批量合并", "no": "SYS-MERGE", "role": "总部运营"}   # op_log 署名;两段确认的「认人」那段是用户 10-26 拍的


def 待合并(c):
    """返回 [(账户, [档案 dict…])]:同一账户下还有 >1 条独立(没归档、没并入别人)的档案。"""
    MG._确保列(c)
    c.row_factory = sqlite3.Row
    accs = [r[0] for r in c.execute("""SELECT account_id FROM customer
            WHERE account_id IS NOT NULL AND COALESCE(archived,0)=0 AND (merged_into IS NULL OR merged_into='')
            GROUP BY account_id HAVING COUNT(*) > 1""")]
    return [(a, [dict(r) for r in c.execute("""SELECT id, name, phone, birthday, addr, shop, created FROM customer
              WHERE account_id=? AND COALESCE(archived,0)=0 AND (merged_into IS NULL OR merged_into='')
              ORDER BY created, id""", (a,))]) for a in accs]


def main(argv):
    做 = "--做" in argv
    if "--库" in argv:
        MG.DB = argv[argv.index("--库") + 1]
    c = sqlite3.connect(MG.DB)
    组们 = 待合并(c)
    c.close()
    并, 留 = [], []
    for 账户, 档 in 组们:
        主 = 档[0]
        for 另 in 档[1:]:
            结论, 理由 = MG.判同一人(主, 另)
            (并 if 结论 == "同一人" else 留).append((账户, 主["id"], 另["id"], 结论, 理由))
    print(f"{'真合并' if 做 else '演练(没写库)'}:账户 {len(组们)} 个 · 能合 {len(并)} 对 · 不合 / 判不了 {len(留)} 对")
    for 账户, a, b, _, 理由 in 并:
        r = MG.并入(a, b, 执行人, 来源="批量合并") if 做 else {"ok": True, "reason": "(演练)"}
        print(f"  {'✅' if r.get('ok') else '❌'} {a} + {b}  ← {理由}" + ("" if r.get("ok") else f"  拒:{r.get('reason')}"))
    for 账户, a, b, 结论, 理由 in 留:
        print(f"  ⏸ {a} / {b}  {结论}:{理由} —— 不动,交人")
    if 做:
        c = sqlite3.connect(MG.DB)
        剩 = [g for g in 待合并(c) if any(MG.判同一人(g[1][0], x)[0] == "同一人" for x in g[1][1:])]
        if 剩:
            print(f"❌ 合完还剩 {len(剩)} 个账户有能合没合的:{[g[0] for g in 剩][:5]}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
