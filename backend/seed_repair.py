#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""返修判责表(店长判了什么)。重建时建表;历史返修单**不补判责**。

    python3 backend/seed_repair.py

口径在 `knowledge/repair.py`,写口在 `backend/repair_write.py`(业务 2026-09-22)。

## 为什么历史单不补判责

库里的维保单是外部售后系统同步过来的(ext_system),那时候没有「店长判责、顾客同意才开工」这条规矩。
补一条判责就是替店长编了一次没发生过的拍板 —— 而判责表里最值钱的就是「谁、什么时候、凭什么」。
所以**新规挂在动作上,不挂在日期上**(同白坯试衣):
  · 经本系统新建的返修单(ext_system='澜绣')—— 必须有判责记录,状态机上的闸管着
  · 外部同步来的历史单 —— 没有判责记录是事实,不补、不追溯
"""
import os, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))

DDL = """
CREATE TABLE IF NOT EXISTS maintain_decision(
  -- 店长对一张返修单的判责。**只有本系统新建的返修单才有**;外部同步来的历史单没有,也不补。
  maintain_id TEXT PRIMARY KEY,
  source TEXT,                         -- 签收不合身 / 售后
  liable TEXT, plan TEXT,              -- 顾客 / 企业;返修 / 重做 —— 都由店长定(业务 09-22)
  fee_est REAL,                        -- 判给顾客的预估费用
  customer_agreed_at TEXT, agree_note TEXT,   -- 顾客同意付费的时间和凭据(同意在开工之前)
  decided_by TEXT, decided_at TEXT,    -- 判责的店长工号、时间
  return_fit_at TEXT, return_verified_by TEXT);  -- 修好回店,顾客试穿合身、导购核验码的时间和人
"""


def main(db=None):
    c = sqlite3.connect(db or os.path.join(HERE, "lanxiu.db"))
    c.executescript(DDL)
    n = c.execute("SELECT COUNT(*) FROM maintain_decision").fetchone()[0]
    h = c.execute("SELECT COUNT(*) FROM maintain WHERE COALESCE(ext_system,'')<>'澜绣'").fetchone()[0]
    c.close()
    print(f"返修判责表:{n} 行(本系统新建的返修单才有);外部同步的历史返修单 {h} 张不补判责")


if __name__ == "__main__":
    main()
