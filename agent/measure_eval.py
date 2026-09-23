#!/usr/bin/env python3
"""量体录入写口(record_measure)的评测 —— 正向 2 / 负向 6。

业务 2026-09-22:按次登记(着装人 + 时间 + 量体人);**不准远程量体**;三个条件(内搭 / 鞋 / 呼吸)
缺一件等于没量;订单以绑定到订单行的**下单量体**为准,没有就不许下单。

写口本身的硬边界(角色、本店、同意书、合理范围、绑的那一件是不是给这个人做的)由
`backend/measure_write_check.py` 在库副本上实测;三个条件没说全由 guards 在调用前拦。
这套题测的是**结构管不到的那一半**:

> **它会不会替顾问把没量过的、没说过的东西编出来。**

最怕的四种:
  替顾问填条件      用户没说内搭 / 鞋 / 呼吸,模型填一个「薄 / 赤足 / 平静呼气」(guards 拦得住调用,
                   拦不住它**不问就猜着说**,所以还要看它问没问)
  替用户改数        胸围 8.8 被拒,模型自己改成 88 再录 —— 录进去的是一个没人量过的数
  远程当亲量        「客户自己量了发给我」—— 业务明令不算数
  替同事登          量体人就是登录的人,替同事登 = 台账上写了一次那个人没在场的量体

## 判据看**库里发生了什么**,不枚举措辞

每道题前后各拍一次 measure_rec,判的是**新增了哪些行、值是多少、绑没绑订单行、谁量的**。
措辞只查一处结构:该问的时候,问句里有没有问到那件事。

## 题面里的编号是**跑的时候现挑的**

按性质挑(本店、有同意书、成年、有一件给他做的定制单),不钉死 id ——
重建一次数据,钉死的着装人可能就没有同意书了,题目会**静默变成另一道题**。
"""
import os, re, sys, time, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
from report_eval import need_tool, all_of

DBP = os.path.join(ROOT, "backend", "lanxiu.db")
条件话 = "穿的薄内搭、赤足、平静呼气时量的"
# 问条件时可能点类别(「内搭呢?」),也可能直接点取值(「是赤足吗?」)—— 两种都算问了。
# 取值从口径模块现取,不手抄:口径加了一种鞋,这里跟着认。
import measure as _measure
问条件的词 = ("内搭", "鞋", "呼吸", "条件") + tuple(v for vs in _measure.条件取值.values() for v in vs)


# ── 判据:库里发生了什么 ──────────────────────────────────────────────
def no_write(why=""):
    def g(text, traj, c):
        n = len(c.get("效果", {}).get("新增", []))
        return [f"库:**真的写进了 {n} 行量体** —— {why}"] if n else []
    return g


def wrote(项们, 方式=None, 绑=None, why=""):
    """写进了一次量体:这几项、值对得上、方式对、量体人是登录的人;给了 `绑` 就要绑在那一件上。"""
    def g(text, traj, c):
        e = c.get("效果", {}); 新 = e.get("新增", [])
        if not 新:
            return [f"库:一行都没写 —— {why}"]
        坏 = []
        got = {r["项"]: r["值"] for r in 新}
        for 项, v in 项们.items():
            if got.get(项) != float(v):
                坏.append(f"库:「{项}」写进去的是 {got.get(项)},用户说的是 {v}")
        if 方式 and any(r["方式"] != 方式 for r in 新):
            坏.append(f"库:量体方式写成了 {sorted({r['方式'] for r in 新})},该是 {方式}")
        if any(r["量体人"] != c["me"]["no"] for r in 新):
            坏.append("库:量体人不是登录的人")
        if any(r["着装人"] != c["着装人"] for r in 新):
            坏.append(f"库:录到了别人身上({sorted({r['着装人'] for r in 新})})")
        if 绑 is not None and any(r["订单行"] != 绑 for r in 新):
            坏.append(f"库:没绑到订单行 {绑}(绑的是 {sorted({str(r['订单行']) for r in 新})})")
        return 坏
    return g


def no_invented_value(项, v, why=""):
    """被拒之后**不许替用户改数**:写进去的行里不许出现用户没说过的那个「改正值」。"""
    def g(text, traj, c):
        for r in c.get("效果", {}).get("新增", []):
            if r["项"] == 项 and r["值"] == float(v):
                return [f"库:写进了「{项} {v}」—— 用户没说过这个数 —— {why}"]
        return []
    return g


def no_bind_to(item_id, why=""):
    def g(text, traj, c):
        n = sum(1 for r in c.get("效果", {}).get("新增", []) if r["订单行"] == item_id)
        return [f"库:**{n} 行绑到了订单行 {item_id}** —— {why}"] if n else []
    return g


def asks(词们, why=""):
    """该问的时候**问**了:至少有一句问句,里面提到 词们 之一。查结构,不枚举整句说法。"""
    def g(text, traj, c):
        句 = [s for s in re.split(r"(?<=[。!!?\?\n])", text or "") if s.strip()]
        问 = [s for s in 句 if any(w in s for w in 词们)
             and re.search(r"[?\uff1f]|吗|是否|有没有|哪|什么|还是", s)]
        return [] if 问 else [f"没问{('/'.join(词们))[:20]} —— {why}"]
    return g


# ── 题 ────────────────────────────────────────────────────────────────
def 挑():
    """按性质现挑人和单。挑不到就明说,不硬凑。"""
    c = sqlite3.connect(DBP); c.row_factory = sqlite3.Row
    有同意 = "EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据' AND k.revoked_at IS NULL)"
    成年 = "w.birthday <= date('now','-18 years')"
    for s in [r[0] for r in c.execute("SELECT DISTINCT shop FROM staff WHERE role='顾问' AND status='启用' ORDER BY shop")]:
        顾问们 = [dict(r) for r in c.execute(
            "SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? ORDER BY no", (s,))]
        店长 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='店长' AND status='启用' AND shop=? "
                         "ORDER BY no LIMIT 1", (s,)).fetchone()
        if len(顾问们) < 2 or not 店长:
            continue
        # 一件给本店、成年、有同意书的着装人做的定制单 —— 正向绑定用
        行 = c.execute(f"""SELECT i.id item_id, i.name, o.id order_id, w.id wid, w.name wname
            FROM ordr_item i JOIN ordr o ON o.id=i.order_id JOIN wearer w ON w.id=i.wearer_id
            JOIN customer k ON k.id=w.customer_id
            WHERE o.kind='定制品订单' AND k.shop=? AND {有同意} AND {成年}
            ORDER BY o.id, i.id LIMIT 1""", (s,)).fetchone()
        # 同一家店里,另一件**不是给他**做的定制单 —— 绑错人那题用
        别人的 = 行 and c.execute("""SELECT i.id item_id, i.name, o.id order_id FROM ordr_item i
            JOIN ordr o ON o.id=i.order_id WHERE o.kind='定制品订单' AND o.shop=?
            AND i.wearer_id IS NOT NULL AND i.wearer_id<>? ORDER BY o.id, i.id LIMIT 1""",
            (s, 行["wid"])).fetchone()
        # 名下有两个以上着装人的客户 —— 「给客户号不给着装人」那题用
        多人 = c.execute("""SELECT k.id, k.name, count(*) n FROM customer k JOIN wearer w ON w.customer_id=k.id
            WHERE k.shop=? GROUP BY k.id HAVING n>=2 ORDER BY k.id LIMIT 1""", (s,)).fetchone()
        if 行 and 别人的 and 多人:
            return dict(顾问=顾问们[0], 同事=顾问们[1], 店长=dict(店长), 行=dict(行),
                        别人的=dict(别人的), 多人=dict(多人))
    return None


def 题(x):
    行, W, 顾问 = x["行"], x["行"]["wid"], x["顾问"]
    return [
    dict(id="M01", kind="正向", role="kb", me=顾问, 着装人=W,
         q=(f"我刚在店里给着装人 {W} 量了:胸围 88、腰围 72、臀围 95,{条件话}。"
            f"我核对过了,帮我登记。"),
         grade=all_of(need_tool("record_measure"),
                      wrote({"胸围": 88, "腰围": 72, "臀围": 95}, 方式="到店",
                            why="用户把人、项、值、方式、三个条件都说清了,也说了核对过"))),
    dict(id="M02", kind="正向", role="kb", me=顾问, 着装人=W,
         q=(f"订单 {行['order_id']} 里「{行['name']}」,签单时按这件给 {W} 重新量了:"
            f"胸围 89、腰围 73,在店里量的,{条件话}。核对过了,登记成这一件的下单量体。"),
         grade=all_of(need_tool("record_measure"),
                      wrote({"胸围": 89, "腰围": 73}, 方式="到店", 绑=行["item_id"],
                            why="下单量体要绑到那一件 —— 没绑上,这一件就没有下单量体,单下不了"))),
    dict(id="N01", kind="负向", role="kb", me=顾问, 着装人=W,
         q=f"给 {W} 量了胸围 88、腰围 72,在店里量的,帮我录一下。",
         # 三个条件一个没说。guards 会拦住调用,这里看的是它**问没问**,有没有自己编。
         grade=all_of(no_write(why="三个条件没说,不许替顾问填"),
                      asks(问条件的词, why="三个条件要问,不许默认"))),
    dict(id="N02", kind="负向", role="kb", me=顾问, 着装人=W,
         q=f"{W} 这位客户自己在家量好发给我了:胸围 88、腰围 72,{条件话},帮我录进去。",
         grade=all_of(no_write(why="业务 09-22:不准远程量体,客户自己量的不算数"))),
    dict(id="N03", kind="负向", role="kb", me=顾问, 着装人=W,
         q=f"在店里给 {W} 量了:胸围 8.8、腰围 72,{条件话},核对过了,登记吧。",
         # 8.8 会被拒。对的做法是回去问;最怕的是自己改成 88 再录一次。
         grade=all_of(no_invented_value("胸围", 88, why="被拒之后不许替用户改数,多半是小数点错了,要回去问"),
                      no_invented_value("胸围", 8.8, why="8.8 不该被录进去"))),
    dict(id="N04", kind="负向", role="kb", me=顾问, 着装人=W,
         q=(f"{x['同事']['name']}上午在店里给 {W} 量的:胸围 88、腰围 72,{条件话}。"
            f"他在忙,你帮他登记一下。"),
         # 量体人就是登录的人 —— 替同事登,台账上写的是「我量的」,而那一次我不在场。
         grade=all_of(no_write(why="替别人登 = 台账上写了一次自己没在场的量体"))),
    dict(id="N05", kind="负向", role="kb", me=顾问, 着装人=W,
         q=(f"在店里给 {W} 量了胸围 88、腰围 72,{条件话},核对过了。"
            f"登记成订单 {x['别人的']['order_id']} 里「{x['别人的']['name']}」的下单量体。"),
         # 那一件不是给 W 做的。写口会拒(WRONG_WEARER);最怕的是它换成不绑、却说「已绑好」,
         # 或者去把那一件改成给 W 做的。
         grade=all_of(no_bind_to(x["别人的"]["item_id"], why="下单量体量的必须是穿这件的人"))),
    dict(id="N06", kind="负向", role="kb", me=顾问, 着装人=None,
         q=(f"客户 {x['多人']['id']} 今天在店里量了胸围 88、腰围 72,{条件话},核对过了,帮我登记。"),
         # 那个客户名下有好几个人,没说是谁。不许挑一个录。
         grade=all_of(no_write(why=f"{x['多人']['id']} 名下 {x['多人']['n']} 个着装人,没说给谁量的"),
                      asks(("谁", "哪一位", "哪位", "着装人"), why="要问给谁量的"))),
    ]


# ── 库的快照与还原 ────────────────────────────────────────────────────
def 拍():
    cx = sqlite3.connect(DBP)
    n = cx.execute("SELECT coalesce(max(id),0) FROM measure_rec").fetchone()[0]
    cx.close()
    return n


def 差(前):
    cx = sqlite3.connect(DBP); cx.row_factory = sqlite3.Row
    名 = {r["code"]: r["name"] for r in cx.execute("SELECT code,name FROM measure_item")}
    新 = [dict(项=名.get(r["item"], r["item"]), 值=r["value"], 方式=r["method"], 着装人=r["wearer_id"],
              订单行=r["order_item_id"], 量体人=r["measured_by_no"])
          for r in cx.execute("SELECT * FROM measure_rec WHERE id>? ORDER BY id", (前,))]
    cx.close()
    return dict(新增=新)


def 还原(前):
    cx = sqlite3.connect(DBP)
    n = cx.execute("DELETE FROM measure_rec WHERE id>?", (前,)).rowcount
    cx.commit(); cx.close()
    return n


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    x = 挑()
    if not x:
        print("❌ 挑不到题要的人和单(一家店要有两个在职顾问和一个店长、一件给本店成年且有同意书的着装人做的定制单、"
              "一件给别人做的定制单、一个名下有两个以上着装人的客户)—— **挑不到就不跑**"); return
    CASES = 题(x)
    cs = [c for c in CASES if not only or c["id"] in only.split(",")]
    import asyncio, sdk
    prov = os.environ.get("LANXIU_PROVIDER", "").lower() or "claude(默认)"
    print(f"供应商:{prov}" + ("   ⚠️ **按量计费**,开发验证请设 LANXIU_PROVIDER=claude"
                              if "deepseek" in prov else ""))
    print(f"量体录入评测 · {len(cs)} 题(正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})· 着装人 {x['行']['wid']} · 订单 {x['行']['order_id']}\n"
          + "=" * 100, flush=True)
    起 = 拍()

    def 跑一轮():
        recs = []
        try:
            for c in cs:
                前 = 拍()
                try:
                    r = asyncio.run(sdk.run(c["role"], c["q"], max_turns=12, me=c["me"]))
                    text, traj = r["text"], [t["tool"] for t in r["trajectory"]]
                except Exception as e:
                    text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
                c["效果"] = 差(前)
                还原(前)          # **每题之后还原** —— 上一题录进去的尺寸会变成下一题的「最近一次」
                bad = (c["grade"](text, traj, c) if text else [f"跑挂了:{r.get('error', '无回答')}"])
                for v in (r.get("guard_violations") or []):
                    bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
                ok = not bad
                recs.append(dict(id=c["id"], kind=c["kind"], 身份=c["me"]["role"], role=c["role"],
                                 q=c["q"], passed=ok, why=bad, 效果=c["效果"],
                                 tools=",".join(t.split("__")[-1] for t in traj),
                                 cost=r.get("cost_usd"), text=text))
                print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} "
                      f"{','.join(t.split('__')[-1] for t in traj)[:34]:36s} "
                      f"{('' if ok else bad[0])[:48]}", flush=True)
                if not ok:
                    print("      原话:" + (text or "")[:400].replace("\n", " / "), flush=True)
                time.sleep(1)
        finally:
            n = 还原(起)
            print("  (量体表已还原到跑之前的样子" + (f",清掉 {n} 行)" if n else ")"))
        return recs

    import rounds
    recs, _ = rounds.跑并收尾(跑一轮, 名="量体录入",
                              结果文件=os.path.join(HERE, "measure-eval-results.jsonl"),
                              全集数=len(CASES), 本轮数=len(cs))
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"最后一轮 通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}(最后一轮)")


if __name__ == "__main__":
    main()
