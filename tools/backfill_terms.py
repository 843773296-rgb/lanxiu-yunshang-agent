#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铺条款接受记录(演示数据)—— 从账户上的 `tos_version` 推出「哪一版、什么时候接受的」。

⚠️ **接受时间是推的,不是记下来的**:账户表只存了「现在是哪一版」,没存什么时候点的同意。
    还停在旧版(v2.1)的 → 记成注册那天接受;已是新版的 → 记成最近一次登录时重新确认(改版后要重新确认才能用)。
    `via` 一律写「演示数据推的」,和真实的「小程序注册 / 小程序重新确认」分得开。
**确定性**:不用随机。重跑先清空再铺。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
DB = os.path.join(ROOT, "backend", "lanxiu.db")


def main(db=DB):
    import terms_store as S, recording_terms as K
    c = sqlite3.connect(db)
    S.建表(c)
    c.execute("DELETE FROM terms_accept WHERE via LIKE '演示数据推的%'")
    n = 0
    for aid, v, created, last in c.execute(
            "SELECT id, tos_version, created, last_login FROM account WHERE tos_version IS NOT NULL ORDER BY id").fetchall():
        新 = K.含录音条款吗(v)
        时 = (max(created or "", last or "") if 新 else created) or created
        if not 时:
            continue
        c.execute("INSERT OR IGNORE INTO terms_accept(account_id, doc, version, accepted_at, via) VALUES(?,?,?,?,?)",
                  (aid, K.条款文档, v, str(时)[:10],
                   "演示数据推的:" + ("最近一次登录时重新确认" if 新 else "注册时")))
        n += 1
    # 已有的通话(造的逐字稿)也补上同意依据 —— 按客户现在接受过的版本推(演示数据,没有「录的那一刻」可查)
    列 = {r[1] for r in c.execute("PRAGMA table_info(call_audio)")}
    补 = 0
    if 列:
        for aid, cid in c.execute("SELECT id, customer_id FROM call_audio WHERE consent_basis IS NULL").fetchall():
            c.execute("UPDATE call_audio SET consent_basis=? WHERE id=?", (S.依据(c, cid), aid)); 补 += 1
    c.commit()
    含 = c.execute("SELECT COUNT(*) FROM terms_accept WHERE version>=?", (K.录音条款起始版本,)).fetchone()[0]
    print(f"  条款接受 {n} 条(含录音条款的 {含} 条,其余停在旧版 → 录音按默认同意);补了 {补} 通录音的同意依据")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
