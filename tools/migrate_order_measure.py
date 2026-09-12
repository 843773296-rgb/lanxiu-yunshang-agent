#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把老库里**意外产生**的超期量体挪到合规位置,同时**留着那个反例夹具**。

逻辑在 `backend/fix_order_measure.py`,`seed.py` 末尾也调它 ——
**一份代码两个调用方**,老库新库两条路都对。

默认 dry-run,`--go` 才真改。
"""
import os, sys, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import fix_order_measure as F


def main():
    go = "--go" in sys.argv
    db = os.path.join(ROOT, "backend", "lanxiu.db")
    c = sqlite3.connect(db)
    print(f"{'真跑' if go else 'dry-run(加 --go 才真改)'}")
    if not go:
        c.execute("BEGIN")
    n, kept = F.enforce(c)
    if go:
        c.commit(); print(f"  已提交,修了 {n} 条")
    else:
        c.rollback(); print(f"  (已回滚)会修 {n} 条")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
