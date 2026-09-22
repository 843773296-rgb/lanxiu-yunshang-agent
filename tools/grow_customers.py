#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补客户 —— 把客户盘子从 108 个补到 1000 个。

## 为什么要补

用户 2026-09-18:「客户太少了,订单太少了」,拍板到**客户 1000 / 订单约 2.5 万**。

原来 108 个客户里,能安全挂单的只有约 60 个 —— 其余是边界夹具、合并用例、评测写死的。
于是 3826 单模拟销量摊在 45 个人头上,人均 85 单:
**按商品看像一家店,按客户看不像任何一家店**,而这两种视角在库里长得一模一样。
要让「按客户看」也能用(顾问业绩、客户资产、回购率、会员分层),先得有人。

## 造的是什么

每个新客户都是**完整的一个人**,不是一行孤零零的档案 —— 只有档案没有账户的客户,
在「账户在门店档案之上」的模型里不成立(lifecycle_check A3/A8 会当场红):

    客户档案  门店 / 本店顾问 / 地址(以省开头)/ 生日 / 画像
    账户      一人一个;四成自设了账号密码(**只存 PBKDF2 哈希 + 独立的盐**)
    着装人    本人一个(成年);三成是一家人 —— 配偶 + 一个孩子
    同意      量过体的着装人有「身体数据」同意;孩子另有监护人签的「未成年人」同意
    量体      七成本人量过 1–3 次;孩子按复量周期量(90–180 天就得重量)

汇总字段(单数 / 实付 / 等级 / 生命周期)先按 0 单填,**由 order_mix 按订单重算**。

## 来路

新客户一律 `C3xxxx`,账户 `U3xxxx`,着装人 `W3xxxx-n`,同意 `CS5xxxxx` ——
**前缀就是来路**,回滚按前缀删,不另建表(数据表数是文档里写着的,多一张就要改文档)。
种子的客户不动;固定种子 `seed.py` 的随机数一个都不吃 —— 这里用自己的随机源。

## 用法

    python3 tools/grow_customers.py            先按前缀删掉旧的,再造
    python3 tools/grow_customers.py --rollback 只删

再生顺序见 `tools/rebuild.sh`:排在旅程之后、模拟销量之前(模拟销量要从这批人里挑客户)。
"""
import os, sys, random, sqlite3, hashlib, argparse, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")

SEED = 20260919
# 用户拍板「客户 1000」,又说「数量别是 5000、100 这种,要有随机性,看起来真实」——
# 所以是**一千上下的一个不整的数**,由固定种子定下来(重建多少次都是同一个数)
目标客户数 = 1000 + random.Random(SEED).randrange(-60, 80)
T = dt.date(2026, 8, 31)          # 建库基准日
量体截止 = T                       # 演示世界的「今天」—— 量体不能晚于它

SURN = "陈林黄张李王吴刘蔡杨赵周徐孙朱胡郭何高罗郑梁谢宋唐许韩冯邓曹彭曾肖田董潘袁蒋蔡余杜叶程魏苏吕丁沈任姚卢傅钟姜崔谭廖范汪陆金石戴贾韦夏邱方侯邹熊孟秦白江阎薛尹段雷黎史龙陶贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
GIVEN_F = ["雨桐", "知微", "书言", "子衿", "望舒", "青梧", "清禾", "若曦", "念安", "婉清", "芷若",
           "语嫣", "晚晴", "安然", "锦书", "如意", "静姝", "思齐", "梦溪", "初夏", "听雪", "南乔",
           "映月", "采薇", "素心", "云舒", "婉兮", "昭华", "檀音", "知意", "嘉禾", "疏影", "沐晴",
           "念慈", "清欢", "楚楚", "诗涵", "可馨", "一诺", "星遥"]
GIVEN_M = ["砚清", "子墨", "承宇", "景行", "修远", "明哲", "怀瑾", "思远", "亦舟", "云帆", "君浩",
           "一鸣", "知行", "泽宇", "逸尘", "长风", "嘉树", "牧之", "晏清", "北辰"]
KID_F = ["星芜", "昭昭", "令仪", "清和", "若薇", "小满", "朵朵", "悠悠"]
KID_M = ["砚舟", "望舒", "知许", "星野", "小川", "一一", "嘉言", "安安"]
PLACES = [("上海市", "上海市", d) for d in ("静安区", "徐汇区", "黄浦区", "长宁区", "浦东新区", "闵行区")] + \
         [("浙江省", "杭州市", d) for d in ("西湖区", "上城区", "拱墅区", "滨江区")] + \
         [("江苏省", "苏州市", d) for d in ("姑苏区", "工业园区")] + \
         [("江苏省", "南京市", "鼓楼区"), ("浙江省", "宁波市", "海曙区"), ("广东省", "广州市", "越秀区"),
          ("北京市", "北京市", "朝阳区"), ("安徽省", "合肥市", "蜀山区")]
ROADS = ["南京西路", "淮海中路", "衡山路", "文三路", "平江路", "延安西路", "中山北路", "解放路", "人民路"]
OCC = ["室内设计师", "中学教师", "注册会计师", "三甲医院医师", "自由摄影师", "品牌运营", "律师",
       "软件工程师", "茶艺师", "大学讲师", "公务员", "民宿主理人", "学生", "产品经理", "舞蹈老师"]
INCOME = ["10w 以下", "10w-20w", "20w-30w", "30w-50w", "50w 以上", "不愿透露"]
# 量体理想值(女 / 男),加上每个人自己的偏移和每次量的误差
IDEAL = {"女": {"MI01": 162, "MI02": 52, "MI03": 86, "MI13": 80, "MI04": 68, "MI05": 92, "MI06": 38,
                "MI14": 158, "MI09": 98, "MI08": 110, "MI10": 34},
         "男": {"MI01": 175, "MI02": 68, "MI03": 95, "MI13": 88, "MI04": 80, "MI05": 96, "MI06": 45,
                "MI14": 176, "MI09": 102, "MI08": 120, "MI10": 39}}
PWD_ITER = 120_000


def rollback(c):
    n = c.execute("SELECT COUNT(*) FROM customer WHERE id LIKE 'C3%'").fetchone()[0]
    c.execute("DELETE FROM measure_rec WHERE customer_id LIKE 'C3%'")
    c.execute("DELETE FROM consent WHERE id LIKE 'CS5%'")
    c.execute("DELETE FROM wearer WHERE id LIKE 'W3%'")
    c.execute("DELETE FROM account WHERE id LIKE 'U3%'")
    c.execute("DELETE FROM customer WHERE id LIKE 'C3%'")
    return n


def main():
    ap = argparse.ArgumentParser(description="补客户到 1000 个(可按前缀回滚)")
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    with c:
        n0 = rollback(c)
        if a.rollback:
            print(f"已删掉 {n0} 个补的客户(连同账户 / 着装人 / 同意 / 量体)")
            return
        rng = random.Random(SEED)
        have = c.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
        要补 = 目标客户数 - have
        # 本店顾问:客户在静安店,顾问就不能是徐汇店的人
        adv = {}
        for r in c.execute("SELECT no, shop FROM staff WHERE role='顾问' AND status='启用'"):
            adv.setdefault(r["shop"], []).append(r["no"])
        shops = sorted(adv)
        用过的号 = {r[0] for r in c.execute("SELECT phone FROM customer")} | \
                   {r[0] for r in c.execute("SELECT phone FROM account")} | \
                   {r[0] for r in c.execute("SELECT phone FROM phone_alias")}
        # **名字不重** —— 同名会进「疑似重复客户」的队列,那是客户合并用例的地盘
        用过的名 = {r[0] for r in c.execute("SELECT name FROM customer")}
        tpls = {r["code"]: r for r in c.execute("SELECT code, status FROM measure_tpl")}
        TPL_ITEMS = {"LT01": ["MI01", "MI02", "MI03", "MI13", "MI04", "MI05", "MI06", "MI14", "MI09"],
                     "LT02": ["MI01", "MI02", "MI04", "MI05", "MI09"],
                     "LT03": ["MI01", "MI02", "MI03", "MI04", "MI05", "MI06", "MI14", "MI08", "MI10"],
                     "LT04": ["MI01", "MI03", "MI06", "MI14", "MI08"]}
        TPL_ITEMS = {k: v for k, v in TPL_ITEMS.items() if k in tpls and tpls[k]["status"] == "启用"}
        n_cs, stats = 0, dict(客户=0, 账户带密码=0, 着装人=0, 量体次=0, 孩子=0)

        def phone():
            while True:
                p = rng.choice(["13", "15", "17", "18", "19"]) + f"{rng.randrange(10**9):09d}"
                if p not in 用过的号:
                    用过的号.add(p)
                    return p

        def name(g):
            while True:
                n = rng.choice(SURN) + rng.choice(GIVEN_F if g == "女" else GIVEN_M)
                if n not in 用过的名:
                    用过的名.add(n)
                    return n

        def consent(wid, scope, by, rel, at):
            nonlocal n_cs
            n_cs += 1
            c.execute("INSERT INTO consent VALUES(?,?,?,?,?,?,?,?)",
                      (f"CS5{n_cs:05d}", wid, scope, by, rel, rng.choice(["门店纸质", "电子签"]), at, None))

        def measure(cid, wid, g, start, every, offset, shop, items_tpl=None, kid_h=None):
            """从 start 起每隔 every 天量一次,直到截止日。返回量了几次。"""
            n, d = 0, start
            tpl = items_tpl or rng.choice(sorted(TPL_ITEMS))
            while d <= 量体截止 and n < 4:
                who = rng.choice(adv[shop])
                # 业务 09-22:不准远程量体,必须顾问亲自服务。原来 12% 远程,改成上门
                how = "上门" if rng.random() < 0.12 else "到店"
                cond = (rng.choice(["无", "薄", "厚"]), rng.choice(["赤足", "平底", "高跟"]))
                if kid_h:        # 孩子:量五项,身高随时间长
                    h = kid_h + (d - start).days / 365 * 6
                    vals = {"MI01": h, "MI03": h * 0.47, "MI04": h * 0.42, "MI09": h * 0.55,
                            "MI14": h * 1.03}
                else:
                    vals = {it: IDEAL[g][it] + offset.get(it, 0) + rng.uniform(-1.2, 1.2)
                            for it in TPL_ITEMS[tpl]}
                for it, v in vals.items():
                    c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by_no,"
                              "measured_at,method,wearer_id,cond_inner,cond_shoe,cond_breath) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                              (cid, tpl, it, round(v, 1), who,
                               f"{d.isoformat()} {rng.randrange(10, 19):02d}:{rng.choice(['00', '30'])}",
                               how, wid, cond[0], cond[1], "平静呼气"))
                n += 1
                d = d + dt.timedelta(days=int(every * rng.uniform(0.8, 1.2)))
            return n

        for i in range(要补):
            cid, aid = f"C{30000 + i}", f"U{30000 + i}"
            g = "女" if rng.random() < 0.78 else "男"   # 〔种下 S13〕
            nm = name(g)
            ph = phone()
            shop = rng.choices(shops, weights=[5, 3, 2][:len(shops)])[0]
            prov, city, dist = rng.choice(PLACES)
            addr = f"{prov}{'' if city == prov else city}{dist}{rng.choice(ROADS)}{rng.randrange(1, 999)}号"
            # 建档越近越多(门店在长),最早两年前
            created = T - dt.timedelta(days=int(730 * rng.random() ** 1.6))
            bd = dt.date(rng.randrange(1972, 2005), rng.randrange(1, 13), rng.randrange(1, 29))
            last = created + dt.timedelta(days=rng.randrange(0, max(1, (T - created).days + 1)))
            c.execute("""INSERT INTO customer(id,name,phone,phone_tail,shop,advisor_no,lifecycle,level,
                         created,order_cnt,paid_amount,last_interact,addr,birthday,archived,first_order,
                         orders_12m,quarters_12m,amount_12m,idle_days,matched,gender,email,wechat,
                         occupation,income,car,province,city,district,points,account_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (cid, nm, ph, ph[-4:], shop, rng.choice(adv[shop]), "潜在", "普通",
                       created.isoformat(), 0, 0.0, last.isoformat(), addr, bd.isoformat(), 0, None,
                       0, 0, 0.0, (T - last).days, "潜在", g, f"{cid.lower()}@163.com",
                       f"wx_{cid.lower()}", rng.choice(OCC), rng.choice(INCOME),
                       "无" if rng.random() < 0.6 else "有", prov, city, dist, 0, aid))
            # 账户:四成自设了账号密码,**只存哈希 + 独立的盐**(盐从随机源来,可重现)
            login = salt = h = algo = None
            if rng.random() < 0.4:
                login = f"lx_{ph[-6:]}_{i}"
                salt = f"{rng.getrandbits(128):032x}"
                h = hashlib.pbkdf2_hmac("sha256", f"demo-{ph[-4:]}-pwd".encode(),
                                        bytes.fromhex(salt), PWD_ITER).hex()
                algo = f"pbkdf2_sha256${PWD_ITER}"
                stats["账户带密码"] += 1
            wself = f"W{30000 + i}-0"
            c.execute("INSERT INTO account VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, ph, login, algo, salt, h, "正常", created.isoformat(),
                       last.isoformat() if rng.random() < 0.7 else None, nm,
                       rng.choice(["微信", "电话", "短信"]), addr, shop, wself,
                       "v2.1" if rng.random() < 0.12 else "v2.3",
                       "v1.4" if rng.random() < 0.08 else "v1.5",
                       1 if rng.random() < 0.65 else 0, None, None, 0, None))
            # 本人
            off = {it: rng.gauss(0, 3) for it in IDEAL[g]}
            c.execute("INSERT INTO wearer VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (wself, cid, aid, nm, g, bd.isoformat(), "本人", ph, None, None,
                       round(IDEAL[g]["MI01"] + off["MI01"], 1), "在用", created.isoformat()))
            stats["着装人"] += 1
            if rng.random() < 0.7:
                m0 = max(created, dt.date(2025, 5, 1)) + dt.timedelta(days=rng.randrange(0, 120))
                if m0 <= 量体截止:
                    consent(wself, "身体数据", nm, "本人", m0.isoformat())
                    stats["量体次"] += measure(cid, wself, g, m0, rng.randrange(150, 260), off, shop)
            # 三成是一家人:配偶 + 一个孩子
            if rng.random() < 0.3:
                sg = "男" if g == "女" else "女"
                wsp = f"W{30000 + i}-1"
                spn = nm[0] + ("先生" if sg == "男" else "女士")
                sbd = dt.date(bd.year + rng.randrange(-3, 4), rng.randrange(1, 13), rng.randrange(1, 29))
                soff = {it: rng.gauss(0, 3) for it in IDEAL[sg]}
                c.execute("INSERT INTO wearer VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (wsp, cid, aid, spn, sg, sbd.isoformat(), "配偶", phone(), None, None,
                           round(IDEAL[sg]["MI01"] + soff["MI01"], 1), "在用", created.isoformat()))
                stats["着装人"] += 1
                if rng.random() < 0.5:
                    m1 = max(created, dt.date(2025, 5, 1)) + dt.timedelta(days=rng.randrange(0, 150))
                    if m1 <= 量体截止:
                        consent(wsp, "身体数据", spn, "本人", m1.isoformat())
                        stats["量体次"] += measure(cid, wsp, sg, m1, rng.randrange(180, 300), soff, shop)
                # 孩子 3–14 岁;父母都得比孩子大至少 20 岁
                age = rng.randrange(3, 15)
                kbd = T - dt.timedelta(days=int(age * 365.25) + rng.randrange(0, 300))
                if max(bd, sbd).year + 20 <= kbd.year:
                    kg = "女" if rng.random() < 0.55 else "男"
                    wk = f"W{30000 + i}-2"
                    kn = nm[0] + rng.choice(KID_F if kg == "女" else KID_M)
                    pa, pb = (wself, wsp) if g == "男" else (wsp, wself)
                    c.execute("INSERT INTO wearer VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (wk, cid, aid, kn, kg, kbd.isoformat(), "女" if kg == "女" else "子",
                               None, pa, pb, None, "在用", created.isoformat()))
                    stats["着装人"] += 1
                    stats["孩子"] += 1
                    rel = "监护人(母)" if g == "女" else "监护人(父)"
                    # 「未成年人」同意**登记孩子那天就签** —— 和量没量过体无关。
                    # 第一版只给量过体的孩子签,18 个没量过的孩子挂在档案里没有监护人同意,
                    # lifecycle_check 当场红:不满 14 周岁的个人信息,登记本身就要监护人点头
                    consent(wk, "未成年人", nm, rel, created.isoformat())
                    k0 = max(created, dt.date(2025, 6, 1)) + dt.timedelta(days=rng.randrange(0, 90))
                    if k0 <= 量体截止:
                        consent(wk, "身体数据", nm, rel, k0.isoformat())
                        base = 88 + (k0 - kbd).days / 365.25 * 6.2
                        # 孩子按复量周期量:3 岁以下 90 天、其余大多 120–180 天
                        stats["量体次"] += measure(cid, wk, kg, k0, 150, {}, shop, "LT01",
                                                   kid_h=base + rng.uniform(-4, 4))
            stats["客户"] += 1
    print(f"补了 {stats['客户']} 个客户(现在共 {have + stats['客户']} 个)· "
          f"着装人 {stats['着装人']}(其中孩子 {stats['孩子']})· 量体 {stats['量体次']} 次 · "
          f"账户里自设密码的 {stats['账户带密码']}")


if __name__ == "__main__":
    main()
