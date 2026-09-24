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
  decided_by TEXT, decided_at TEXT,
  -- 金额授权(业务 2026-09-24):我方要出的钱超过店长权限(1000)时,报总部批了才能开工;
  -- 超过 5000 走专项。**批准人不是判责人** —— 同一个人既判又批,这条线等于没有。
  approved_by TEXT, approve_note TEXT,
    -- 判责的店长工号、时间
  return_fit_at TEXT, return_verified_by TEXT);  -- 修好回店,顾客试穿合身、导购核验码的时间和人
"""


def _造公差用例(c):
    """给 2026-09-24 新加的三行判据**造端到端用例**,并写上真值。

    ⚠️ **真值是业务给的,不是我推的**(2026-09-24 当场逐例确认):
        ① 腰围差 4cm(公差 1.5)、签收时确认过合身 → **我们免费**(超公差优先于签收确认)
        ② 裙长差 1cm(公差 2)                    → **顾客收费**
        ③ 没量具体差多少、量体记录不全、签收才 2 个月 → **我们免费**(举证期内)
    这一段和 `knowledge/liability.py` 仍然是**两套实现**:那边从 md 解析规则,
    这边是手写的判断 —— `backend/liability_check.py` 每次拿两边对账。
    没有这三条用例的话,新规则只有单元自测盖着,**端到端一次都没跑过**。
    """
    行 = c.execute("""SELECT m.id, m.order_id,
                            (SELECT COUNT(*) FROM measure_rec r WHERE r.customer_id=m.customer_id) 量体项,
                            (SELECT p.fit_at FROM pickup p WHERE p.order_id=m.order_id) 签收
                     FROM maintain m
                     WHERE m.status IN ('待确认','待处理','处理中') AND m.issue='尺寸需调整'
                     ORDER BY m.id""").fetchall()
    齐 = [r for r in 行 if r[2] >= 4 and r[3]]          # 量体记录完整、签收过的:拿来做 ① ②
    缺 = [r for r in 行 if r[2] < 4 and r[3]]           # 记录不全、签收过的:拿来做 ③
    造 = []
    if len(齐) >= 2:
        造.append((齐[0][0], '{"腰围": 4}', "尺寸偏差 · 超出公差 · 我方免费返修",
                  "实测腰围差 4cm,公差 ±1.5cm —— 超出公差,我方免费返修(业务 2026-09-24)"))
        造.append((齐[1][0], '{"裙长": 1}', "尺寸偏差 · 公差内 · 客方收费改",
                  "实测裙长差 1cm,公差 ±2cm —— 在公差内,顾客要改收费改(业务 2026-09-24)"))
    # 第三例不用另造:「记录不全 → 我方免费改」本来就有用例(seed.py 标注的),
    # 时间窗只是给它加了期限(6 个月内才成立),不是新结论 —— 见 09 md 五之二那段说明。
    for mid, 差, rc, ev in 造:
        if 差:
            c.execute("UPDATE maintain SET 尺寸差=? WHERE id=?", (差, mid))
        c.execute("UPDATE truth SET root_cause=?, expected_evidence=? WHERE case_id=? AND breakpoint='BP-03'",
                  (rc, ev, mid))
    if len(造) < 2:
        print(f"  ⚠️ 只造出 {len(造)} 条公差用例(要 2 条)—— 库里缺合适的尺寸类返修单")
    else:
        print(f"  公差用例:{len(造)} 条(真值是业务 2026-09-24 逐例给的:超公差我方 / 公差内顾客)")
    return len(造)


def main(db=None):
    c = sqlite3.connect(db or os.path.join(HERE, "lanxiu.db"))
    c.executescript(DDL)
    # **缺列就补**:CREATE TABLE IF NOT EXISTS 对**已经存在**的表一个字都不改 ——
    # 新加的列只有从零建库才有,已有的库跑起来会在写入时才报「no such column」,
    # 而那时候已经是业务动作中途了(2026-09-24 加金额授权两列时当场撞上)。
    有 = {r[1] for r in c.execute("PRAGMA table_info(maintain_decision)")}
    for 列 in ("approved_by", "approve_note"):
        if 列 not in 有:
            c.execute(f"ALTER TABLE maintain_decision ADD COLUMN {列} TEXT")
            print(f"  maintain_decision 补上缺的列:{列}")
    # 实测成衣和量体差多少 —— 这是**报修单自己的事实**(顾问量出来的),挂在 maintain 上;
    # 判责记录只记「谁判的、判成什么」。存 JSON:{"腰围": 4};**不填就是没量过**,
    # 判定会往下走,不会拿「没量」当「在公差内」(业务 2026-09-24 的公差判定要它)。
    if "尺寸差" not in {r[1] for r in c.execute("PRAGMA table_info(maintain)")}:
        c.execute("ALTER TABLE maintain ADD COLUMN 尺寸差 TEXT")
        print("  maintain 补上缺的列:尺寸差")
    _造公差用例(c)
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM maintain_decision").fetchone()[0]
    h = c.execute("SELECT COUNT(*) FROM maintain WHERE COALESCE(ext_system,'')<>'澜绣'").fetchone()[0]
    c.close()
    print(f"返修判责表:{n} 行(本系统新建的返修单才有);外部同步的历史返修单 {h} 张不补判责")


if __name__ == "__main__":
    main()
