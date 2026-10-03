#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把通话逐字稿里判出来的商机建成对象,并铺一遍生命周期(演示数据)。

**确定性**:判断走 `backend/opportunity.判断`(规则,不调模型),状态分布按通话号的稳定哈希定,不用随机。
**真值不参与**:用的是判断器的结论,不是 `truth` 里的标注 —— 系统里的商机就是判断器认出来的那些,
判错的也照建(那正是顾问「点头确认」那一步要拦的)。

状态怎么铺(演示形状,不是业务事实):
    哈希 0–1   待确认        判断器认了,顾问还没点头
    已转方案   顾问点过头、且客户名下有空着的已锁定 / 已保存方案的,优先转(只有一个客户有方案)
    哈希 6–7   已关闭        关闭原因写「看了不喜欢 / 嫌贵」
    哈希 8     搁置等供给    等的是第一条诉求(结构化)
    其余       跟进中
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
DB = os.path.join(ROOT, "backend", "lanxiu.db")


def _h(s):
    import seed
    return seed.稳定哈希(s)


def main(db=DB):
    import opportunity as J, opportunity_store as S, oppo_obj as K, oppo as KO
    c = sqlite3.connect(db)
    S.建表(c)
    c.execute("DELETE FROM opportunity_need"); c.execute("DELETE FROM opportunity")
    c.execute("UPDATE scheme SET opportunity_id=NULL")
    建 = 0
    计 = {}
    for aid, cust, t, created in c.execute(
            "SELECT a.id, a.customer_id, t.text, a.created FROM call_audio a "
            "JOIN call_transcript t ON t.audio_id=a.id ORDER BY a.id").fetchall():
        是, 码, _ = J.判断(t, cust)
        if not 是:
            continue
        行们 = KO.客户说的(t).splitlines()
        诉求 = [(维, 词, K.原话(行们, 词)) for 词, 维, _ in J.命中维度(KO.客户说的(t))]
        顾问 = (c.execute("SELECT advisor_no FROM customer WHERE id=?", (cust,)).fetchone() or [None])[0]
        oid = S.从通话建(c, aid, cust, 顾问, 诉求, created, 下一步=f"按「{码}」去查店里有没有对得上的款")
        建 += 1
        h = _h(aid) % 10
        if h <= 1:
            pass
        else:
            S.改状态(c, oid, "跟进中", created, 经手人=顾问)
            方案 = c.execute("SELECT id FROM scheme WHERE customer_id=? AND status IN ('已锁定','已保存') "
                             "AND opportunity_id IS NULL ORDER BY id LIMIT 1", (cust,)).fetchone()
            if 方案:      # 客户名下有空着的方案就转 —— 这批数据里只有一个客户有方案,不优先就一条都转不成
                S.改状态(c, oid, "已转方案", created, 方案=方案[0])
            elif h in (6, 7):
                S.改状态(c, oid, "已关闭", created, 关闭原因=("看了不喜欢" if h == 6 else "嫌贵"))
            elif h == 8:
                第一 = c.execute("SELECT dim, val FROM opportunity_need WHERE opp_id=? LIMIT 1", (oid,)).fetchone()
                if 第一:
                    S.改状态(c, oid, "搁置等供给", created, 等什么={第一[0]: 第一[1]})
        st = c.execute("SELECT status FROM opportunity WHERE id=?", (oid,)).fetchone()[0]
        计[st] = 计.get(st, 0) + 1
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM opportunity_need").fetchone()[0]
    print(f"  商机 {建} 条(从 {c.execute('SELECT COUNT(*) FROM call_audio').fetchone()[0]} 通通话里判出来),"
          f"诉求 {n} 条(每条带原话);状态:{计}")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
