#!/usr/bin/env python3
"""用户生命周期 · 数据体检

这一层管的是**人**,不是单。所以它的检查和订单勾稽不是一类:
订单错了会有人投诉,**人的数据错了没人会说** —— 孩子的生日填错一年,
所有推算跟着偏一岁,系统一句话都不会报,直到衣服做小了。

分两类输出,**分得很清**:

  ① 结构性错误 —— 数据自相矛盾或合规缺口,**必须红**。
     例:量体记录挂了个不存在的着装人;未成年人没有监护人同意。
  ② 业务信号  —— 数据是对的,但业务上需要有人动一下,**不该红**。
     例:某个孩子的量体记录已经过期,该约复量了。

把②做成红的,是这类系统最常见的设计错误 ——
体检天天红,人就不看了,最后①也一起漏掉。
"""
import os, sys, sqlite3
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import growth

DB = os.path.join(HERE, "lanxiu.db")
TODAY = date(2026, 8, 31)      # 和 seed.py 的 T 对齐


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把「监护人同意」那条体检的判定条件改成永远匹配不上(注进去的问题它再也发现不了)',
     '不满 14 周岁但没有监护人同意'),
]

def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


# ── ① 结构性错误 ────────────────────────────────────────────────────────
def structural(c):
    bad = []
    A = lambda tag, rows, how: [bad.append((tag, dict(r), how)) for r in rows]

    A("量体记录挂了不存在的着装人",
      c.execute("""SELECT m.id, m.customer_id, m.wearer_id FROM measure_rec m
                   LEFT JOIN wearer w ON w.id = m.wearer_id
                   WHERE m.wearer_id IS NULL OR w.id IS NULL""").fetchall(),
      "每条量体记录都要能答出「这是谁的尺寸」,答不出的记录不能参与任何推算"),

    # ── 账户层 ──────────────────────────────────────────────────────
    # 「账户 id 以手机号为主」这句话,落到数据上就是下面这几条必须成立。
    A("账户没有手机号,或手机号重复",
      c.execute("""SELECT id, phone FROM account
                   WHERE phone IS NULL OR phone=''
                      OR phone IN (SELECT phone FROM account GROUP BY phone HAVING count(*)>1)
                   """).fetchall(),
      "手机号是账户的主标识 —— 缺了这个账户就没有身份,重了就是两个人共用一个账户。"
      "⚠️ 这一条**平时永远不会触发**:`phone TEXT NOT NULL UNIQUE` 在表结构上就拦死了,"
      "数据库根本写不进去。留着它是守「哪天有人把 UNIQUE 删了」—— "
      "**约束是写不进去,检查是写进去之后发现**,两者不是一回事"),

    A("自设账号重复",
      c.execute("""SELECT id, login_name FROM account WHERE login_name IS NOT NULL
                   AND login_name IN (SELECT login_name FROM account
                                      WHERE login_name IS NOT NULL
                                      GROUP BY login_name HAVING count(*)>1)""").fetchall(),
      "自设账号也是登录凭据,重了就登不进正确的那个"),

    A("有密码却没有盐,或有盐却没有算法",
      c.execute("""SELECT id FROM account
                   WHERE (pwd_hash IS NOT NULL AND (pwd_salt IS NULL OR pwd_algo IS NULL))
                      OR (pwd_salt IS NOT NULL AND pwd_hash IS NULL)""").fetchall(),
      "哈希、盐、算法三者缺一就验不了密码 —— 而且**缺盐的哈希等于没加盐**"),

    A("密码看起来像明文(不是哈希)",
      c.execute("""SELECT id FROM account WHERE pwd_hash IS NOT NULL
                   AND (length(pwd_hash) < 40 OR pwd_hash GLOB '*[^0-9a-fA-F]*')""").fetchall(),
      "**只存 PBKDF2 哈希,绝不存明文** —— demo 数据也不例外"),

    A("着装人没绑账户,或绑了不存在的账户",
      c.execute("""SELECT w.id, w.account_id FROM wearer w
                   LEFT JOIN account a ON a.id = w.account_id
                   WHERE w.account_id IS NULL OR a.id IS NULL""").fetchall(),
      "**身份绑在账户上,不绑门店档案** —— 档案可能有好几条,账户只有一个"),

    # 已注销的排除:两边都是墓碑值(DELETED-<id>),本来就对不上 ——
    # **拿「删干净了」当违规,是规范少了例外,不是数据错了。**
    A("门店档案归错了账户(手机号对不上)",
      c.execute("""SELECT k.id, k.phone, a.phone FROM customer k
                   JOIN account a ON a.id = k.account_id
                   WHERE a.status <> '已注销' AND k.phone <> a.phone""").fetchall(),
      "账户是按手机号归的,归完之后两边手机号必须一致"),

    A("着装人的账户与它建档门店档案的账户不一致",
      c.execute("""SELECT w.id, w.account_id, k.account_id FROM wearer w
                   JOIN customer k ON k.id = w.customer_id
                   WHERE w.account_id <> k.account_id""").fetchall(),
      "两条路径指向同一个账户,对不上说明有一条是靠下标凑的"),

    A("着装人挂在不存在的账号下",
      c.execute("""SELECT w.id, w.customer_id FROM wearer w
                   LEFT JOIN customer k ON k.id = w.customer_id
                   WHERE k.id IS NULL""").fetchall(),
      "着装人必须有归属账号 —— 否则没人能对这份身体数据负责"),

    # ⚠️ 粒度必须是**账户**,不是门店档案。
    # 这条第一版写的是 `customer_id = w.customer_id` —— 账户层加进来之后就错了:
    # 一个账户可能有两条门店档案,本人挂在其中一条、配偶挂在另一条,
    # **它们本来就是一家人**,却被判成「跨账号引用」。
    # **模型一变,检查的粒度也得跟着变** —— 这类不一致是重播种逼出来的,不会自己冒头。
    A("父母指向了别的账户下的人",
      c.execute("""SELECT w.id, w.parent_a, w.parent_b FROM wearer w
                   WHERE (w.parent_a IS NOT NULL AND w.parent_a NOT IN
                            (SELECT id FROM wearer WHERE account_id = w.account_id))
                      OR (w.parent_b IS NOT NULL AND w.parent_b NOT IN
                            (SELECT id FROM wearer WHERE account_id = w.account_id))""").fetchall(),
      "靶身高会读父母身高。跨账户引用等于把别人家的身高算进这个孩子"),

    A("性别不是「男」或「女」",
      c.execute("SELECT id, name, gender FROM wearer WHERE gender NOT IN ('男','女')").fetchall(),
      "身高参照表按性别分列,性别缺失或写别的值,推算无从下手"),

    A("生日缺失或在未来",
      c.execute("SELECT id, name, birthday FROM wearer WHERE birthday IS NULL OR birthday > ?",
                (TODAY.isoformat(),)).fetchall(),
      "**存生日不存年龄**的前提是生日可信;生日错一年,所有推算偏一岁且不报错"),

    # 合规:敏感个人信息
    A("有身体数据但没有「身体数据」同意",
      c.execute("""SELECT DISTINCT w.id, w.name FROM wearer w
                   JOIN measure_rec m ON m.wearer_id = w.id
                   WHERE NOT EXISTS (SELECT 1 FROM consent s WHERE s.wearer_id = w.id
                                     AND s.scope = '身体数据' AND s.revoked_at IS NULL)""").fetchall(),
      "身体数据是敏感个人信息,需单独同意(个保法 28 条)"),

    kids = [r["id"] for r in c.execute("SELECT id, birthday FROM wearer").fetchall()
            if r["birthday"] and growth.age_at(r["birthday"], TODAY) < 14]
    if kids:
        q = ",".join("?" * len(kids))
        A("不满 14 周岁但没有监护人同意",
          c.execute(f"""SELECT w.id, w.name FROM wearer w WHERE w.id IN ({q})
                        AND NOT EXISTS (SELECT 1 FROM consent s WHERE s.wearer_id = w.id
                          AND s.scope = '未成年人' AND s.revoked_at IS NULL
                          AND s.relation LIKE '%监护人%')""", kids).fetchall(),
          "不满十四周岁未成年人信息须监护人同意并制定专门规则(个保法 31 条)")

    A("同意已撤回却仍留着推算记录",
      c.execute("""SELECT g.id, g.wearer_id FROM growth_forecast g
                   JOIN consent s ON s.wearer_id = g.wearer_id
                   WHERE s.revoked_at IS NOT NULL AND g.created > s.revoked_at""").fetchall(),
      "撤回后不得再用于推算与营销触达"),
    return bad


# ── ② 业务信号 ──────────────────────────────────────────────────────────
def signals(c):
    """数据没错,但需要有人动一下。**这些不该让体检变红。**"""
    out = []
    for w in c.execute("SELECT * FROM wearer WHERE birthday IS NOT NULL").fetchall():
        last = c.execute("""SELECT max(measured_at) a FROM measure_rec
                            WHERE wearer_id=? AND item='MI01'""", (w["id"],)).fetchone()["a"]
        if not last: continue
        e = growth.measure_expired(w["gender"], w["birthday"], last[:10], TODAY)
        if e["过期"]:
            out.append(dict(类型="该复量了", 着装人=w["name"], id=w["id"],
                            年龄=round(growth.age_at(w["birthday"], TODAY), 1),
                            已过=e["已过天数"], 上限=e["允许天数"], 原因=e["原因"]))
    return out


def conflicts(c):
    """靶身高和百分位推算差太多的 —— 转人工,**不自动挑一边**"""
    out = []
    for w in c.execute("SELECT * FROM wearer WHERE parent_a IS NOT NULL").fetchall():
        h = c.execute("""SELECT value v, measured_at t FROM measure_rec
                         WHERE wearer_id=? AND item='MI01' ORDER BY measured_at DESC LIMIT 1""",
                      (w["id"],)).fetchone()
        if not h: continue
        ph = [c.execute("SELECT height FROM wearer WHERE id=?", (p,)).fetchone()
              for p in (w["parent_a"], w["parent_b"])]
        if not all(ph) or not all(x["height"] for x in ph): continue
        r = growth.forecast(w["gender"], w["birthday"], h["v"], h["t"][:10],
                            TODAY.replace(year=TODAY.year + 1),
                            parents=(ph[0]["height"], ph[1]["height"]))
        v = r.get("靶身高校验") or {}
        if v.get("需人工确认"):
            out.append(dict(着装人=w["name"], 遗传身高=v["遗传身高"],
                            百分位推算=v["百分位推算成年身高"], 差值=v["差值"]))
    return out


def run(verbose=True):
    c = _c()
    bad, sig, conf = structural(c), signals(c), conflicts(c)
    if verbose:
        print("用户生命周期 · 数据体检\n" + "=" * 84)
        n = dict(wearer=c.execute("SELECT count(*) n FROM wearer").fetchone()["n"],
                 consent=c.execute("SELECT count(*) n FROM consent").fetchone()["n"],
                 measure=c.execute("SELECT count(*) n FROM measure_rec").fetchone()["n"])
        print(f"  着装人 {n['wearer']} · 同意记录 {n['consent']} · 量体记录 {n['measure']}")
        kids = c.execute("SELECT count(*) n FROM wearer WHERE relation IN ('子','女')").fetchone()["n"]
        print(f"  其中未成年着装人 {kids} 人 —— 这个模块真正要管的对象\n")

        print("① 结构性错误(必须为 0)")
        if bad:
            for tag, row, how in bad[:20]:
                print(f"  ❌ {tag}:{row}\n     → {how}")
        else:
            print("  ✅ 无")

        print(f"\n② 业务信号 —— 该复量的 {len(sig)} 人(**不算错误**)")
        for s in sorted(sig, key=lambda x: -x["已过"])[:8]:
            print(f"  · {s['着装人']}({s['年龄']}岁) 上次量体已过 {s['已过']} 天 "
                  f"/ 上限 {s['上限']} 天 —— {s['原因']}")
        if not sig: print("  (无)")

        print(f"\n③ 遗传身高与百分位推算冲突 {len(conf)} 人 —— 转人工,不自动挑边")
        for x in conf[:5]:
            print(f"  · {x['着装人']} 遗传 {x['遗传身高']} vs 推算 {x['百分位推算']} "
                  f"(差 {x['差值']}cm)")
        if not conf: print("  (无)")
    return bad, sig, conf


if __name__ == "__main__":
    bad, sig, conf = run()

    # ── 咬合:把数据弄坏,确认体检真的会红 ────────────────────────────
    # **没红过的检查等于没有。**
    print("\n" + "=" * 84 + "\n④ 咬合测试")
    c = _c()
    trials = [
        ("量体记录指向不存在的着装人",
         "UPDATE measure_rec SET wearer_id='W-NOBODY' WHERE id=(SELECT min(id) FROM measure_rec)",
         "UPDATE measure_rec SET wearer_id=(SELECT id FROM wearer WHERE customer_id="
         "(SELECT customer_id FROM measure_rec WHERE id=(SELECT min(id) FROM measure_rec)) "
         "AND relation='本人') WHERE wearer_id='W-NOBODY'"),
        ("撤掉一个孩子的监护人同意",
         "UPDATE consent SET revoked_at='2026-08-01' WHERE scope='未成年人' AND id="
         "(SELECT min(id) FROM consent WHERE scope='未成年人')",
         "UPDATE consent SET revoked_at=NULL WHERE scope='未成年人' AND revoked_at='2026-08-01'"),
        ("把一个孩子的生日改到未来",
         "UPDATE wearer SET birthday='2027-01-01' WHERE relation IN ('子','女') AND id="
         "(SELECT min(id) FROM wearer WHERE relation IN ('子','女'))",
         None),
    ]
    ok = True
    for name, break_sql, fix_sql in trials:
        snap = {r["id"]: dict(r) for r in c.execute("SELECT * FROM wearer")} if fix_sql is None else None
        before = len(structural(c))
        c.execute(break_sql); c.commit()
        after = len(structural(c))
        caught = after > before
        print(f"  {'✅' if caught else '❌'} {name} → 体检{'抓到了' if caught else '**没抓到**'}"
              f"({before} → {after} 条)")
        ok &= caught
        if fix_sql: c.execute(fix_sql)
        else:
            for wid, row in snap.items():
                c.execute("UPDATE wearer SET birthday=? WHERE id=?", (row["birthday"], wid))
        c.commit()
    left = len(structural(c))
    print(f"  {'✅' if left == 0 else '❌'} 咬合后数据已复原(剩余结构性错误 {left} 条)")

    print("\n" + "=" * 84)
    if bad or not ok or left:
        print("❌ 用户生命周期数据体检未通过"); sys.exit(1)
    print(f"✅ 结构性错误 0 条;业务信号 {len(sig)} 条(该复量)、{len(conf)} 条(需人工确认)")
