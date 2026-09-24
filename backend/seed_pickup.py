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
  -- order_id 这一列是**码的键**:订单签收放单号、返修放 "R:返修单号"、包裹放 "P:包裹号" —— 三者同一张表不串。
  order_id TEXT, code_hash TEXT, issued_at TEXT, expires_at TEXT,
  used_at TEXT, tries INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_fit_code_order ON fit_code(order_id);
-- ── 分批发货(业务 2026-09-23)────────────────────────────────────────────
-- 工厂可以分几个包裹发,**每个包裹独立**:各自到店、各自取件方式、各自一个码。
-- 包裹本身(件清单、快递单号、发出时间)在 pkg / pkg_item,由工厂侧维护,这一侧只读。
CREATE TABLE IF NOT EXISTS pkg_pickup(
  pkg_id TEXT PRIMARY KEY, order_id TEXT,
  arrived_at TEXT, received_by TEXT,        -- 这个包裹到店、哪位顾问代收
  mode TEXT, forwarded_at TEXT, tracking_no TEXT);   -- 到店取 / 转寄(转寄要单号)
CREATE INDEX IF NOT EXISTS ix_pkg_pickup_order ON pkg_pickup(order_id);
-- **签收落到「件」**:业务 2026-09-23 定,一个包裹里两件合身一件不合身时,
-- 合身的当场让顾客拿走、不合身那件留店转返修 —— 所以签收记录不能按包裹记,要按件记。
CREATE TABLE IF NOT EXISTS pickup_item(
  order_item_id INTEGER PRIMARY KEY, order_id TEXT, pkg_id TEXT,
  fit_result TEXT,                          -- 合身 / 不合身 / NULL(还没试)
  fit_at TEXT, fit_verified_by TEXT,        -- 核验通过的时间、输码的导购
  issue TEXT, maintain_id TEXT);            -- 不合身时:哪里不合身、转出去的返修单号
CREATE INDEX IF NOT EXISTS ix_pickup_item_order ON pickup_item(order_id);
CREATE INDEX IF NOT EXISTS ix_pickup_item_pkg ON pickup_item(pkg_id);
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


def _有包裹表(c):
    """包裹表由**工厂那一步**建(seed_factory_feed,在重建里排在本步之后)。
    第一次重建跑到这里时它还不存在 —— 那时候只补订单级的签收记录,
    等工厂那步把包裹造出来之后,本脚本会被再跑一次(`--铺到包裹`)把记录铺到包裹和件上。
    **不是「有就补、没有就算了」** —— 没补上的话「整单签收完了没有」会把每一件都当成没签收。
    """
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pkg'").fetchone())


def _铺到包裹和件(c):
    """把**订单级**的老签收记录铺到**包裹**和**件**上(业务 2026-09-23 改成分批发货之后补的)。

    老记录是一单一行(那时候还没有包裹)。工厂侧已经给每张老单补了恰好一个包裹,
    所以这里按包裹把同一行抄下去、再按件铺开:**每件的签收结果就是那一单当时的结果**。
    ⚠️ 只补**还没有**记录的(INSERT OR IGNORE 之外还先查一遍)—— 旅程脚本真走过签收的单,
    它写的是真记录,不许被这一步盖掉。
    """
    有包 = {r[0] for r in c.execute("SELECT pkg_id FROM pkg_pickup")}
    有件 = {r[0] for r in c.execute("SELECT order_item_id FROM pickup_item")}
    包行, 件行 = [], []
    for p in c.execute("""SELECT k.pkg_id, k.order_id, u.arrived_at, u.received_by, u.mode, u.forwarded_at,
                                 u.tracking_no, u.fit_result, u.fit_at, u.fit_verified_by
                          FROM pkg k JOIN pickup u ON u.order_id=k.order_id
                          WHERE k.void_at IS NULL ORDER BY k.pkg_id""").fetchall():
        if p["pkg_id"] not in 有包 and p["arrived_at"]:
            包行.append((p["pkg_id"], p["order_id"], p["arrived_at"], p["received_by"],
                        p["mode"], p["forwarded_at"], p["tracking_no"]))
        if not p["fit_result"]:
            continue                     # 还没试穿的单,件上也不该有结果
        for (it,) in c.execute("SELECT item_id FROM pkg_item WHERE pkg_id=?", (p["pkg_id"],)):
            if it in 有件:
                continue
            件行.append((it, p["order_id"], p["pkg_id"], p["fit_result"], p["fit_at"], p["fit_verified_by"]))
    c.executemany("INSERT OR IGNORE INTO pkg_pickup(pkg_id,order_id,arrived_at,received_by,mode,forwarded_at,"
                  "tracking_no) VALUES(?,?,?,?,?,?,?)", 包行)
    c.executemany("INSERT OR IGNORE INTO pickup_item(order_item_id,order_id,pkg_id,fit_result,fit_at,"
                  "fit_verified_by) VALUES(?,?,?,?,?,?)", 件行)
    return len(包行), len(件行)


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
    c.commit()
    包, 件 = _铺到包裹和件(c) if _有包裹表(c) else (0, 0)
    c.commit(); c.close()
    if 包 or 件:
        print(f"分批发货:按包裹补了 {包} 行取件记录、按件补了 {件} 行签收记录(业务 09-23:签收落到件)")
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
                                     AND NOT EXISTS(SELECT 1 FROM pickup p WHERE p.order_id=o.id)""").fetchone()[0],
         }

    # 已经签收过的包裹,**每一件都要有按件的签收记录** —— 对方(工厂侧)验不了这条,归这边验。
    # 缺了的话「整单签收完了没有」会把没记录的件当成没签收,整单永远进不了待完成。
    漏 = 0 if not _有包裹表(c) else c.execute("""SELECT COUNT(*) FROM pkg k JOIN pkg_item i ON i.pkg_id=k.pkg_id
                     JOIN pickup u ON u.order_id=k.order_id
                     WHERE k.void_at IS NULL AND u.fit_result IS NOT NULL
                       AND NOT EXISTS(SELECT 1 FROM pickup_item t WHERE t.order_item_id=i.item_id)""").fetchone()[0]
    if not _有包裹表(c):
        print("  ℹ️ 包裹表还没建(工厂那一步在本步之后)—— 这一轮只补订单级记录,"
              "铺到包裹和件由重建里的 `seed_pickup.py --铺到包裹` 那一步做")
    c.close()
    for k in 全:
        if not 全[k]:
            print(f"  ❌ 「{k}」一条都没有 —— 那一支没有活用例"); sys.exit(1)
    print("  覆盖:" + " / ".join(f"{k} {v}" for k, v in 全.items()))
    if 漏:
        print(f"  ❌ 有 {漏} 件在已签收的包裹里,却没有按件的签收记录 —— 整单永远进不了待完成"); sys.exit(1)
    print("  ✅ 已签收包裹里的每一件都有按件记录")


def 铺(db=None):
    """重建里工厂那一步之后再跑一次:把订单级的签收记录铺到包裹和件上。"""
    c = sqlite3.connect(db or os.path.join(HERE, "lanxiu.db")); c.row_factory = sqlite3.Row
    c.executescript(DDL)
    if not _有包裹表(c):
        print("❌ 包裹表还不在 —— 这一步要排在工厂那一步之后"); sys.exit(1)
    包, 件 = _铺到包裹和件(c); c.commit()
    漏 = c.execute("""SELECT COUNT(*) FROM pkg k JOIN pkg_item i ON i.pkg_id=k.pkg_id
                     JOIN pickup u ON u.order_id=k.order_id
                     WHERE k.void_at IS NULL AND u.fit_result IS NOT NULL
                       AND NOT EXISTS(SELECT 1 FROM pickup_item t WHERE t.order_item_id=i.item_id)""").fetchone()[0]
    分 = c.execute("""SELECT COUNT(*) FROM (SELECT order_id FROM pkg WHERE void_at IS NULL
                     GROUP BY order_id HAVING COUNT(*)>1)""").fetchone()[0]
    c.close()
    print(f"分批发货:按包裹补了 {包} 行取件记录、按件补了 {件} 行签收记录;分批发的单 {分} 张")
    if 漏:
        print(f"  ❌ 有 {漏} 件在已签收的包裹里却没有按件记录 —— 整单永远进不了待完成"); sys.exit(1)
    if not 分:
        print("  ❌ 一张分批发的单都没有 —— 「一个包裹一个码」那一支没有活用例"); sys.exit(1)
    print("  ✅ 已签收包裹里的每一件都有按件记录")


if __name__ == "__main__":
    铺() if "--铺到包裹" in sys.argv else main()
