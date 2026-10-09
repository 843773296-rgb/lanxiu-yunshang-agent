#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整库平移的**端到端**:在副本上挪几百天,验「一切相对关系不变」真的成立。

## 为什么要有这一条

`tools/shift_world.py` 的 `--selftest` 用的是合成夹具:**4 张表、11 个日期列**。
它守得住挪法本身(样式、单位数小时、幂等、没登记就拒绝动手),
**守不住整库**:真库有 127 个日期列 + 5 个文字列、67 万个值,
而平移的卖点是一句很强的话 ——

    「平移保持一切相对关系不变:两单相隔几天、签收满没满 15 天、量体过没过期,
      挪多少天都一样。」

这句话以前只在**三条间接证据**上验过(`as_of` 整体 +200 后三支码没变),
整库从没挪过。欠账挂了很久,卡的不是难度,是 `shift_world` 当时没有 `--db`
(2026-10-10 加上了)—— 没有它就得另搭一套临时目录。

## 验的是什么(四样,都要求**逐项相同**,不是总数相同)

  ① 每个人的流失预警码 —— 7900+ 人逐个比。**码分布一样不够**:
     「两个人互换了码」和「一个没变」在直方图上长得一模一样。
  ② 逾期的**那几条单**(不是条数)—— 同上。而且逾期是算出来的
     (`status='有效'` 且 `end_ts[:10] < 世界今天`),两头都挪才守恒。
  ③ 每张订单「离世界今天几天」—— 这是上面那句话最直接的形式。
  ④ 档位历史的每个时点各自正好 +N 天。

## ⚠️ 还有一条反向对照,它和上面四条一样重要

四条全绿有两种读法:**平移真的守恒**,或者**这套量根本量不出变化**。
两者在输出上完全一样。所以最后故意改坏一个人的存量(只动 `lifecycle_history`
末时点的 idle/单数/金额,**不动任何日期**),要求:
**他的码必须变,而别人一个都不许变。** 量不出来就是红的。

(这个项目为「判据在当前状态下恰好无法区分对与错」栽过三次 ——
 固定行数的窗口、两边一起改的常量、空表上的登记。形状都一样。)

## 不动真库

副本放在 `tempfile.mkdtemp()`,**不放 backend/**:
`.shifting` 互斥标记是按被平移的库所在目录推的,副本搁在 backend/ 里
会和真库抢同一个标记。跑完就删。
"""
import os, shutil, sqlite3, sys, tempfile, collections
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
DB = os.path.join(ROOT, "backend", "lanxiu.db")
挪几天 = 200          # 挪得够远才有意义:跨年、跨闰月、跨所有的季度边界

import shift_world as SW      # noqa: E402
import slipping as SL         # noqa: E402

FAIL = []


def ck(名, 真, n, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}(验了 {n} 个){('  ' + str(补)[:170]) if 补 else ''}")
    if not 真: FAIL.append(名)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(名 + "(样本量 0)")


# 咬合记录:**五条都在 2026-10-10 真跑过**,不是推的。
# 第二条原来写的是「把 idle_days 当日期挪了」—— 那是猜的,而且是错的:
# 那一列是整数,`平移()` 只碰 TEXT 里长得像日期的值,**永远挪不到它**。
# 真正能咬动「码一个没变」的是**半挪**(1294 人的码当场变),
# 而那恰好就是 `.shifting` 互斥标记存在的理由 —— 一个平移到一半的库。
咬合 = [
    ('让 `平移()` 只写回一半的行(`批` 后面加 `and rid % 2`,模拟挪到一半被中断)',
     '每个人的流失预警码一个没变'),          # 实测:1294 人的码变了
    ('把 `schedule.end_ts` 登记进 `整列日期不挪`(漏挪一列)',
     '逾期的那几条单一模一样'),              # 实测:19 → 22 条
    ('把 `ordr.created` 登记进 `整列日期不挪`',
     '每张订单「离世界今天几天」不变'),      # 实测:600 张全变(21 天 → 221 天)
    ('把 `lifecycle_history.as_of` 登记进 `整列日期不挪`',
     '档位历史的每个时点各自正好 +200 天'),  # 实测:时点停在原处
    ('把反向对照那条 update 改成只动 `as_of`、不动存量',
     '反向对照:只改一个人的存量,他的码就变了'),   # 实测:码还是 STABLE → 红
]


def 量(db):
    """只读地量四样。**不判定,只取数** —— 判在 main 里一处做。"""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    今 = c.execute("select v from world_meta where k='world_today'").fetchone()[0]
    判 = SL.一批人的判断(con=c)
    码 = {cid: (v or {}).get("码") for cid, v in 判.items()}
    逾期 = sorted(r[0] for r in c.execute(
        "select id from schedule where type<>'到店' and status='有效' "
        "and substr(end_ts,1,10)<?", (今,)))
    任务 = c.execute("select count(*) from schedule where type<>'到店'").fetchone()[0]
    时点 = sorted({r[0] for r in c.execute("select distinct as_of from lifecycle_history")})
    # 「离世界今天几天」—— 平移那句承诺最直接的形式。按 id 取样,前后同一批。
    零 = date.fromisoformat(今)
    隔 = {}
    for r in c.execute("select id, created from ordr where created is not null "
                       "order by id limit 600"):
        try: 隔[r[0]] = (零 - date.fromisoformat(str(r[1])[:10])).days
        except ValueError: pass
    c.close()
    return dict(今=今, 码=码, 逾期=逾期, 任务=任务, 时点=时点, 隔=隔)


def main():
    print(f"整库平移 · 端到端(在副本上挪 {挪几天} 天)")
    print("=" * 72)
    if not os.path.exists(DB):
        # 照 `shift_world.查()` 的先例:没库就说清是「没查」,不假装通过
        print("  ⚠ 还没有库(没重建过)—— 跳过。**这不代表验过了**")
        return 0
    工 = tempfile.mkdtemp(prefix="shift_e2e_")
    副 = os.path.join(工, "lanxiu.db")
    assert os.path.realpath(副) != os.path.realpath(DB)      # 真库一个字都不许动
    try:
        shutil.copy2(DB, 副)
        前 = 量(副)
        到 = (date.fromisoformat(前["今"]) + timedelta(days=挪几天)).isoformat()
        r = SW.平移(副, 到, 说=lambda *a: None)
        if r.get("错"):
            print(f"  ❌ 平移本身没跑成:{r['错'][:200]}")
            return 1
        后 = 量(副)
        print(f"  世界今天 {前['今']} → {后['今']}(挪了 {r['天']} 天 · "
              f"{r['改']} 个值 · {r['列']} 列)")

        变 = {k: (前["码"][k], 后["码"].get(k)) for k in 前["码"]
              if 前["码"][k] != 后["码"].get(k)}
        ck("每个人的流失预警码一个没变", not 变 and len(前["码"]) == len(后["码"]),
           len(前["码"]),
           f"变了 {len(变)} 人:{list(变.items())[:3]}" if 变 else
           f"{len(set(前['码'].values()))} 支码都在")
        ck("逾期的那几条单一模一样", 前["逾期"] == 后["逾期"], len(前["逾期"]),
           f"{len(前['逾期'])}→{len(后['逾期'])};进出 "
           f"{sorted(set(前['逾期']) ^ set(后['逾期']))[:5]}"
           if 前["逾期"] != 后["逾期"] else "")
        ck("派单任务数不变", 前["任务"] == 后["任务"], 前["任务"],
           f"{前['任务']}→{后['任务']}")
        差 = {k: (v, 后["隔"].get(k)) for k, v in 前["隔"].items() if 后["隔"].get(k) != v}
        ck("每张订单「离世界今天几天」不变", not 差, len(前["隔"]),
           f"{len(差)} 张变了:{list(差.items())[:3]}" if 差 else "")
        期望 = [(date.fromisoformat(x) + timedelta(days=r["天"])).isoformat()
                for x in 前["时点"]]
        ck(f"档位历史的每个时点各自正好 +{r['天']} 天", 期望 == 后["时点"], len(前["时点"]),
           # ⚠️ 红的时候**不要只打末值** —— 半挪的情形里时点会从 5 个变 10 个,
           # 而末值恰好对得上,于是输出长成「得到 X(期望 X)」却是个 ❌。
           f"{len(前['时点'])} 个时点 → {len(后['时点'])} 个;对不上的 "
           f"{sorted(set(期望) ^ set(后['时点']))[:6]}"
           if 期望 != 后["时点"] else f"{前['时点'][-1]} → {后['时点'][-1]}")

        # ── 反向对照 ────────────────────────────────────────────────
        # 上面全绿有两种读法,**它们在输出上完全一样**:平移真守恒,
        # 或者这套量量不出变化。所以在同一个副本上把一个人弄坏,看量不量得出来。
        候选 = [k for k, v in 后["码"].items() if v in ("STABLE", "RECOVERED")]
        if not 候选:
            ck("反向对照:只改一个人的存量,他的码就变了", False, 0,
               "库里没有 STABLE / RECOVERED 的人可改 —— 挑不到对照就等于没对照")
        else:
            人 = 候选[0]
            c = sqlite3.connect(副)
            行 = c.execute("select id from lifecycle_history where customer_id=? "
                           "order by as_of desc limit 1", (人,)).fetchone()
            # **只动存量,一个日期都不动** —— 不然就分不清是量到了存量还是量到了日期
            c.execute("update lifecycle_history set idle_days=400, orders_12m=0, "
                      "amount_12m=0 where id=?", (行[0],))
            c.commit(); c.close()
            坏 = 量(副)
            他变了 = 坏["码"][人] != 后["码"][人]
            别人 = sum(1 for k, v in 后["码"].items() if k != 人 and 坏["码"].get(k) != v)
            ck("反向对照:只改一个人的存量,他的码就变了", 他变了, 1,
               f"{后['码'][人]} → {坏['码'][人]}" if 他变了 else
               f"码还是 {坏['码'][人]} —— **那上面那几条绿的说明不了任何事**")
            ck("反向对照:而别人一个都没跟着变(这套量是逐人的)", 别人 == 0,
               len(后["码"]) - 1, f"{别人} 个人跟着变了" if 别人 else "")
    finally:
        shutil.rmtree(工, ignore_errors=True)

    print()
    if FAIL:
        print(f"\033[31m❌ {len(FAIL)} 条:{FAIL}\033[0m"); return 1
    print("\033[32m✅ 整库挪 %d 天,相对关系逐项不变(而且量得出变化)\033[0m" % 挪几天)
    return 0


if __name__ == "__main__":
    sys.exit(main())
