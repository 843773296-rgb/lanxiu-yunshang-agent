"""修存量:一个账户只归一位导购(用户 2026-10-26 拍)。

规则在 backend/account_owner.py(定归属):最近接触那条的导购,停用的顺延,打平取建档更晚的;
跨店的整户搬到赢的那家店。历史订单的「经手导购」由 add_cust_advisor 的触发器跟着换(和客户转移同一口径)。

  python3 tools/unify_account_advisor.py              # 演练:只列出每个账户归谁,不写
  python3 tools/unify_account_advisor.py --做         # 真改(写库前先拿锁:./tools/gate_lock.sh)
  python3 tools/unify_account_advisor.py --库 <路径>  # 指定库(演练副本用)
"""
import os
import sqlite3
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(根, "backend"))
import account_owner as AO  # noqa: E402


def main(argv):
    做 = "--做" in argv
    库 = argv[argv.index("--库") + 1] if "--库" in argv else os.path.join(根, "backend", "lanxiu.db")
    c = sqlite3.connect(库)
    名 = {r[0]: r[1] for r in c.execute("SELECT no, name || '(' || role || CASE WHEN COALESCE(status,'启用')!='启用' THEN '·' || status ELSE '' END || ')' FROM staff")}
    结果 = AO.统一(c, 做=做)
    if 做:
        c.commit()
    print(f"{'已改' if 做 else '演练(没写库)'}:冲突账户 {len(结果)} 个" + ("" if 结果 else " —— 没有要改的"))
    for r in 结果:
        if r["没法定"]:
            print(f"  ⚠️ {r['账户']}  {'、'.join(r['档案们'])}  —— 名下导购都已停用,没法定,交人处理")
            continue
        原 = " / ".join(f"{i} {名.get(a, a)}@{s}" for i, (a, s) in r["原来"].items())
        print(f"  {r['账户']}  → {名.get(r['归谁'], r['归谁'])} · {r['门店']}{' · 整户搬店' if r['搬店'] else ''}"
              f"   (按 {r['按']};原来 {原})")
    剩 = AO.冲突账户(c)
    if 做 and 剩:
        print(f"❌ 改完还剩 {len(剩)} 个冲突账户:{剩[:5]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
