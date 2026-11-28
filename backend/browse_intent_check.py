#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览意向回捞(系统每天盯商机)—— 库的临时副本上整条走一遍,真库一行不碰

    python3 backend/browse_intent_check.py

## 为什么要有这个
用户 2026-11-28 拍「做」:系统每天扫小程序浏览,**一周内同一件、加购或收藏了、又回来看了 ≥ 2 次、还没买** →
开一条「待确认」商机、给她的顾问派提醒;每位顾问每天最多 3 条(意向强的先);不同意营销 / 注销不推;
90 天冷却和另两种回捞合着算;提醒过期没人答和购买推断同一套收口;顾问点「客户想看」才转跟进中。

## 查什么(都真调 opportunity_store 里的函数,判据独立用 SQL 重算,不抄一份实现)
1. 扫出来的每一条:那一周真的「加购或收藏 + 看 ≥ 2 次 + 没买 + 在售」(独立 SQL 复核)、同意营销、
   之前不在冷却里、一人一条;每位顾问 ≤ 3;商机是「待确认」+ 来源「浏览意向」;提醒派了、结论清单是那一套
2. 同一天再扫 → 0 条(名额按天,不按次)
3. 第二天:昨天推过的人一个都不再推(冷却)
4. 过期:收口之后这批提醒取消、商机关掉,关闭原因写明「按小程序浏览推断」
5. 顾问答「客户想看,继续跟」→ 商机转跟进中
6. 接线:tools/daily_fresh.收口与放出 先调 推断提醒收口、再调 浏览意向回捞
"""
import ast
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import api                    # noqa: E402
import opportunity_store as S  # noqa: E402
import oppo_obj as K          # noqa: E402

G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, 说 = [], []


def 复核(c, cust, spu, 今):
    起 = (今 - dt.timedelta(days=K.浏览意向_窗口天 - 1)).isoformat()
    止 = (今 + dt.timedelta(days=1)).isoformat()
    看, 动 = c.execute("SELECT SUM(event='进入详情'), SUM(event IN ('加购','收藏')) FROM mp_event "
                     "WHERE customer_id=? AND spu=? AND ts>=? AND ts<?", (cust, spu, 起, 止)).fetchone()
    买 = c.execute("SELECT 1 FROM ordr o JOIN ordr_item i ON i.order_id=o.id WHERE o.customer_id=? AND i.spu=? "
                  "AND substr(o.created,1,10)>=? AND o.status NOT IN ('取消','已取消')", (cust, spu, 起)).fetchone()
    架 = c.execute("SELECT status FROM product WHERE spu=?", (spu,)).fetchone()
    return (看 or 0) >= K.浏览意向_最少看几次 and (动 or 0) > 0 and not 买 and 架 and 架[0] == "上架"


def 同意(c, cust):
    r = c.execute("SELECT a.status, a.marketing_consent FROM customer cu JOIN account a ON a.id=cu.account_id "
                  "WHERE cu.id=?", (cust,)).fetchone()
    return bool(r and r[1] and r[0] not in ("注销中", "已注销"))


def 跑():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "lanxiu.db")
    shutil.copy(api.DB, db)          # 跟着软链拷出一份真的库(不是拷软链)
    c = sqlite3.connect(db)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='mp_event'").fetchone():
            return ["没东西可验:库里没有 mp_event —— 先跑 python3 tools/backfill_browse.py"], True
        今 = dt.date.fromisoformat(c.execute("SELECT v FROM world_meta WHERE k='world_today'").fetchone()[0])
        S.建表(c); c.executescript(S.DDL)
        # 把库里已有的浏览意向清掉(重建 / 每日上新可能已经扫过),从干净的一天开始
        c.execute("DELETE FROM opportunity WHERE source='浏览意向'"); c.execute("DELETE FROM browse_intent_recall"); c.commit()
        之前 = {}
        for (u,) in c.execute("SELECT DISTINCT customer_id FROM mp_event"):
            之前[str(u)] = S._上次推送(c, str(u))
        with c:
            出 = S.浏览意向回捞(c, 今)
        说.append(f"世界今天 {今} 扫出 {len(出)} 条")
        if len(出) < 3:
            return [f"没东西可验:只扫出 {len(出)} 条(下限 3)—— 不是「都对」"], True
        人 = [x["客户"] for x in 出]
        if len(set(人)) != len(人):
            bad.append("一人一条:同一个人一次扫出了两条")
        per = {}
        for x in 出:
            per[x["顾问"]] = per.get(x["顾问"], 0) + 1
            if not 复核(c, x["客户"], x["商品"], 今):
                bad.append(f"信号:{x['客户']} × {x['商品']} 那一周并不是「加购或收藏 + 看 ≥ {K.浏览意向_最少看几次} 次 + 没买 + 在售」")
            if not 同意(c, x["客户"]):
                bad.append(f"营销同意:{x['客户']} 没同意营销 / 已注销,却被推了")
            上次 = 之前.get(x["客户"])
            if 上次 and K.冷却中(dt.date.fromisoformat(str(上次)[:10]), 今):
                bad.append(f"冷却:{x['客户']} 在 {str(上次)[:10]} 刚被推过,又推了")
            st = c.execute("SELECT status, source FROM opportunity WHERE id=?", (x["商机"],)).fetchone()
            if not st or st[0] != K.起始状态 or st[1] != "浏览意向":
                bad.append(f"商机:{x['商机']} 应是「{K.起始状态}」+ 来源「浏览意向」,得到 {st}")
            t = c.execute("SELECT schedule_id FROM opportunity_task WHERE opp_id=? AND kind='浏览意向回捞'", (x["商机"],)).fetchone()
            if not t:
                bad.append(f"提醒:{x['商机']} 没派「浏览意向回捞」提醒")
            elif S.可选结论(c, t[0]) != list(K.提醒结论["浏览意向回捞"]):
                bad.append(f"提醒:{x['商机']} 的结论清单不是浏览意向那一套")
        多 = {a: n for a, n in per.items() if n > K.浏览意向_每顾问每天}
        if 多:
            bad.append(f"名额:有顾问一天收到超过 {K.浏览意向_每顾问每天} 条:{多}")
        说.append(f"每位顾问 {sorted(per.values(), reverse=True)}")
        # 2. 同一天再扫
        with c:
            再 = S.浏览意向回捞(c, 今)
        if 再:
            bad.append(f"名额按天:同一天再扫又开了 {len(再)} 条")
        # 3. 第二天冷却
        with c:
            明 = S.浏览意向回捞(c, 今 + dt.timedelta(days=1))
        重 = set(人) & {x["客户"] for x in 明}
        if 重:
            bad.append(f"冷却:昨天推过的 {sorted(重)[:3]} 第二天又推了")
        说.append(f"第二天扫出 {len(明)} 条,和昨天重叠 {len(重)}")
        # 5. 顾问答「想看」(先挑一条,答完再测收口 —— 答过的不该被收)
        样 = 出[0]
        sid = c.execute("SELECT schedule_id FROM opportunity_task WHERE opp_id=?", (样["商机"],)).fetchone()[0]
        with c:
            ok, 话 = S.按结论处理(c, sid, "客户想看,继续跟", 样["顾问"] or "SYS", "她说想看看", 今.isoformat())
        st = c.execute("SELECT status FROM opportunity WHERE id=?", (样["商机"],)).fetchone()[0]
        if not ok or st != "跟进中":
            bad.append(f"答复:顾问答「客户想看」后商机应转跟进中,得到 {st}({话})")
        # 4. 过期收口
        with c:
            收 = S.推断提醒收口(c, 今 + dt.timedelta(days=K.提醒期限天 + 1))
        没收 = []
        for x in 出[1:]:
            r = c.execute("SELECT status, close_reason FROM opportunity WHERE id=?", (x["商机"],)).fetchone()
            if not r or r[0] != "已关闭" or "小程序浏览" not in (r[1] or ""):
                没收.append((x["商机"], r))
        if 没收:
            bad.append(f"收口:过期没人答的 {len(没收)} 条没关掉 / 关闭原因没写明浏览推断:{没收[:2]}")
        if c.execute("SELECT status FROM opportunity WHERE id=?", (样["商机"],)).fetchone()[0] != "跟进中":
            bad.append("收口:顾问已经答过「想看」的那条被收掉了")
        说.append(f"收口收了 {len(收)} 条(含别的推断提醒)")
        return bad, False
    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)


def 查接线():
    src = open(os.path.join(ROOT, "tools", "daily_fresh.py"), encoding="utf-8").read()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == "收口与放出":
            调 = [x.func.attr for x in ast.walk(n) if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                 and x.func.attr in ("推断提醒收口", "浏览意向回捞")]
            调 = sorted(set(调), key=调.index)
            if 调 != ["推断提醒收口", "浏览意向回捞"]:
                return [f"接线:daily_fresh.收口与放出 应先调 推断提醒收口 再调 浏览意向回捞,实际 {调} —— 每天没人去扫"]
            return []
    return ["接线:tools/daily_fresh.py 里没有 收口与放出()"]


咬合 = [
    ("扫描不查营销同意", "营销同意:"),
    ("去掉「看 ≥ 2 次」", "信号:"),
    ("名额只按这一次调用数(不算今天已派的)", "名额按天:同一天再扫"),
    ("收口不管浏览意向那一种提醒", "收口:过期没人答的"),
    ("每日上新不再调浏览意向回捞", "接线:daily_fresh.收口与放出"),
]


def main():
    print("浏览意向回捞 · 库副本上走一遍(真库不碰)\n" + "=" * 72)
    b, 空 = 跑()
    for x in 说: print(f"  · {x}")
    b += [] if 空 else 查接线()
    for x in b: print(f"  {R}❌ {x}{D}")
    if 空:
        print(f"{R}❌ 没东西可验 —— 不是「都对」{D}"); return 1
    if b:
        print(f"{R}❌ {len(b)} 处不对{D}"); return 1
    print(f"{G}✅ 浏览意向回捞:信号 / 同意 / 冷却 / 名额按天 / 答复 / 过期收口 / 每天有人扫{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
