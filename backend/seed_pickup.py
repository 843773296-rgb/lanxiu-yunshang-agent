#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付签收的两张表,和演示数据里已经过了签收的单该有的签收记录。

    python3 backend/seed_pickup.py        # 重建第 9 步(在白坯试衣之后)

口径在 `knowledge/pickup.py`,写口在 `backend/pickup_write.py`(业务 2026-09-22)。

## 这里补的是什么

库里已经有一批定制单走到了「待完成」「完成」—— 按 09-22 的规矩,**它们都该签收过**
(顾客试穿合身、导购核验了码)。表是新的,这些单却没有任何签收记录,于是:

  · 「签收了才许进待完成」这条不变量在历史单上全红
  · 判责要查「签收时试穿合身了没」,历史单一条都查不到 —— 看起来像全都没签收

所以按订单自己的时间补一条签收记录:到店 = 发货后 2 天,试穿合身 = 到店后 1 天,
完成 = 订单的完成时间。**都不晚于订单自己记的完成时间** —— 否则就是签收比完成还晚。

⚠️ **为覆盖而选,不是为好看而选**(同 seed_fitting):
  · 每 5 单有 1 单是**转寄**(带物流单号)—— 全是到店取的话,转寄那一支永远没有样本
  · **历史的完成单一律记成顾客确认**:演示库里发货到完成最长 14 天,而追认要签收满 15 天 ——
    硬造一条追认就得改订单自己的完成时间。追认的活用例在「待完成」里:那批单签收都已满 15 天,
    顾问现在就能追认(下面数出来,一条都没有就红)
  · 「已发货」的单一半登记了到店代收、一半还在路上 —— 两种状态都要有活用例
  · 历史单**不造码**:码只在核验那一刻有用,事后留着的是签收记录本身

按订单号的稳定哈希挑,不用随机数 —— 重建多少次挑中的都是同一批。
"""
import os, sys, sqlite3, hashlib, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
# 「签收满 15 天」按**演示世界的今天**数,不按机器的今天 —— 后者每天都在变,
# 同一份代码今天和明天数出来不一样(重建可复现检查当场抓到第一版用了机器时钟)
from seed import TODAY

DDL = """
CREATE TABLE IF NOT EXISTS pickup(
  -- 定制品交付签收,一单一行。**签收 = 顾客确认试穿合身**(6 位码核验通过),不是导购点一下。
  order_id TEXT PRIMARY KEY,
  arrived_at TEXT, received_by TEXT,        -- 工厂发到店,哪位顾问代收(只存工号)
  mode TEXT,                                -- 到店取 / 转寄
  forwarded_at TEXT, tracking_no TEXT,      -- 转寄才有
  -- 合身 / 不合身 / NULL(还没试)。**不合身不算签收**,订单不动,转返修。
  fit_result TEXT,
  fit_at TEXT, fit_verified_by TEXT,        -- 核验通过的时间、输码的导购
  complete_at TEXT, complete_by TEXT,       -- 顾客 / 顾问追认
  ratify_note TEXT);                        -- 追认必须写理由
CREATE TABLE IF NOT EXISTS fit_code(
  -- 顾客在手机端点「试穿合身」拿到的 6 位码。**库里只存哈希**,明文只给顾客。
  order_id TEXT, code_hash TEXT, issued_at TEXT, expires_at TEXT,
  used_at TEXT, tries INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_fit_code_order ON fit_code(order_id);
"""


def _稳(s, n):
    return int(hashlib.sha256(("pickup:" + str(s)).encode()).hexdigest()[:8], 16) % n


def _t(s):
    s = str(s or "")
    for n, f in ((16, "%Y-%m-%d %H:%M"), (10, "%Y-%m-%d")):
        try:
            return datetime.datetime.strptime(s[:n], f)
        except ValueError:
            pass
    return None


def _f(t):
    return t.strftime("%Y-%m-%d %H:%M") if t else None


def main(db=None):
    c = sqlite3.connect(db or os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    # **不清表** —— 旅程脚本(第 3 步)开完的单是真走过签收流程的(到店、出码、核验),
    # 它的记录要留着。白坯试衣第一版整表 DELETE,把旅程真登记的试衣一起删了,
    # 于是一批「经系统开裁却查不到试衣」—— 同一个坑不踩第二次。这里只补**还没有记录**的单。
    已有 = {r[0] for r in c.execute("SELECT order_id FROM pickup")}
    行们, 计 = [], {"待完成": 0, "完成": 0, "转寄": 0, "已发货·到店": 0, "已发货·在路上": 0}
    for o in c.execute("SELECT id,status,advisor_no,shipped_at,finished_at,updated,created FROM ordr "
                       "WHERE kind='定制品订单' AND status IN ('已发货','待完成','完成') ORDER BY id").fetchall():
        if o["id"] in 已有:
            continue
        发 = _t(o["shipped_at"]) or _t(o["updated"]) or _t(o["created"])
        if not 发:
            continue
        到 = 发 + datetime.timedelta(days=2, hours=3)
        转寄 = _稳(o["id"], 5) == 0
        if o["status"] == "已发货":
            if _稳(o["id"], 2) == 0:
                行们.append((o["id"], _f(到), o["advisor_no"], None, None, None, None, None, None, None, None, None))
                计["已发货·到店"] += 1
            else:
                计["已发货·在路上"] += 1
            continue
        完 = _t(o["finished_at"]) if o["status"] == "完成" else None
        试 = 到 + datetime.timedelta(days=4 if 转寄 else 1)
        if 完 and 试 > 完:                       # 签收不许晚于完成
            试 = 完 - datetime.timedelta(hours=1); 到 = min(到, 试 - datetime.timedelta(hours=1))
        行们.append((o["id"], _f(到), o["advisor_no"], "转寄" if 转寄 else "到店取",
                     _f(到 + datetime.timedelta(hours=2)) if 转寄 else None,
                     f"SF{_稳(o['id'], 10 ** 10):010d}" if 转寄 else None,
                     "合身", _f(试), o["advisor_no"],
                     _f(完), "顾客" if 完 else None, None))
        计[o["status"]] += 1; 计["转寄"] += 转寄
    c.executemany("INSERT OR IGNORE INTO pickup(order_id,arrived_at,received_by,mode,forwarded_at,tracking_no,"
                  "fit_result,fit_at,fit_verified_by,complete_at,complete_by,ratify_note) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", 行们)
    c.commit(); c.close()
    print(f"交付签收:补了 {len(行们)} 行(旅程真走过签收的 {len(已有)} 单原样留着)—— 待完成 {计['待完成']} / 完成 {计['完成']}"
          f"(其中转寄 {计['转寄']});"
          f"已发货到店 {计['已发货·到店']}、还在路上 {计['已发货·在路上']}")
    # 覆盖要**按整张表数**,不按这一次补了几行 —— 第二次跑一行不补,按补的数会报「一条都没有」
    c = sqlite3.connect(db or os.path.join(HERE, "lanxiu.db"))
    全 = {"转寄": c.execute("SELECT COUNT(*) FROM pickup WHERE mode='转寄'").fetchone()[0],
         "可追认": c.execute("""SELECT COUNT(*) FROM pickup p JOIN ordr o ON o.id=p.order_id
                               WHERE o.status='待完成' AND p.fit_at <= datetime(?, '-15 days')""", (TODAY,)).fetchone()[0],
         "已发货·到店": c.execute("""SELECT COUNT(*) FROM pickup p JOIN ordr o ON o.id=p.order_id
                                   WHERE o.status='已发货'""").fetchone()[0],
         "已发货·在路上": c.execute("""SELECT COUNT(*) FROM ordr o WHERE o.kind='定制品订单' AND o.status='已发货'
                                     AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)""").fetchone()[0]}
    c.close()
    for k in 全:
        if not 全[k]:
            print(f"  ❌ 「{k}」一条都没有 —— 那一支没有活用例"); sys.exit(1)


if __name__ == "__main__":
    main()
