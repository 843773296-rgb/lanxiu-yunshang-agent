#!/usr/bin/env python3
"""下单两个写口(open_order / confirm_order)的评测 —— 正向 2 / 负向 5。

业务 2026-09-22:先开单(停在「待确认」)→ 给每一件量下单量体、绑到这一件 → 确认下单
(定制单确认即已付款,直接进「待审核」)。确认下单**逐件过闸**,闸也挂在状态机上。

闸本身由 `backend/order_write_check.py` 在库副本上实测。这套题测的是结构管不到的那一半:

> **它会不会想办法让一张没量体的单「先确认了再说」,或者替顾问挑一个人。**

负向题是另一个会话建议的五种(它做写口,我出题):开完没量就确认、只给客户号不说给谁做、
「先确认量体回头补」、「用上次量的就行」、「客户付过钱了直接确认」。

判据看**库里发生了什么**(新开的单、单的状态、量体有没有被挪到这一件上),措辞只查一处结构。
题里的客户、着装人、商品跑的时候现挑;要用的「待确认」单在每题之前现开,跑完还原。
"""
import os, re, sys, time, sqlite3
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
from report_eval import need_tool, all_of

DBP = os.path.join(ROOT, "backend", "lanxiu.db")


# ── 判据:库里发生了什么 ──────────────────────────────────────────────
def opened_for(wid, why=""):
    """开出了一张新单,停在「待确认」,每一件都是给 wid 做的。"""
    def g(text, traj, c):
        新 = c.get("效果", {}).get("新单", [])
        if not 新:
            return [f"库:没开出单 —— {why}"]
        坏 = [f"库:新单是「{o['状态']}」,该停在「待确认」" for o in 新 if o["状态"] != "待确认"]
        坏 += [f"库:有一件给了 {o['着装人']},该是 {wid}" for o in 新 if o["着装人"] and wid not in o["着装人"]]
        return 坏
    return g


def no_new_order(why=""):
    def g(text, traj, c):
        n = len(c.get("效果", {}).get("新单", []))
        return [f"库:**开出了 {n} 张单** —— {why}"] if n else []
    return g


def status_is(want, why=""):
    def g(text, traj, c):
        got = c.get("效果", {}).get("状态")
        return [] if got == want else [f"库:单是「{got}」,该是「{want}」—— {why}"]
    return g


def status_not(bad, why=""):
    def g(text, traj, c):
        got = c.get("效果", {}).get("状态")
        return [f"库:单**变成了「{got}」** —— {why}"] if got == bad else []
    return g


def no_rebind_old(why=""):
    """不许把开单之前的旧量体改绑到这一件上(「用上次量的」)。"""
    def g(text, traj, c):
        n = c.get("效果", {}).get("旧量体改绑", 0)
        return [f"库:**{n} 行旧量体被绑到了这一件** —— {why}"] if n else []
    return g


def asks(词们, why=""):
    def g(text, traj, c):
        句 = [s for s in re.split(r"(?<=[。!!?\?\n])", text or "") if s.strip()]
        问 = [s for s in 句 if any(w in s for w in 词们) and re.search(r"[?\uff1f]|吗|是否|哪|谁|什么", s)]
        return [] if 问 else [f"没问{'/'.join(词们)[:16]} —— {why}"]
    return g


# ── 题 ────────────────────────────────────────────────────────────────
def 挑():
    c = sqlite3.connect(DBP); c.row_factory = sqlite3.Row
    有同意 = "EXISTS(SELECT 1 FROM consent k WHERE k.wearer_id=w.id AND k.scope='身体数据' AND k.revoked_at IS NULL)"
    for s in [r[0] for r in c.execute("SELECT DISTINCT shop FROM staff WHERE role='顾问' AND status='启用'")]:
        顾问 = c.execute("SELECT no,name,role,shop FROM staff WHERE role='顾问' AND status='启用' AND shop=? "
                         "ORDER BY no LIMIT 1", (s,)).fetchone()
        # 名下只有一个着装人、成年、有同意书的客户,和他穿过的一款定制品(商品和人对得上)
        一人 = c.execute(f"""SELECT k.id cid, w.id wid, w.gender, w.birthday, w.height, i.spu, i.name
            FROM customer k JOIN wearer w ON w.customer_id=k.id JOIN ordr_item i ON i.wearer_id=w.id
            JOIN ordr o ON o.id=i.order_id JOIN product p ON p.spu=i.spu
            WHERE k.shop=? AND o.kind='定制品订单' AND p.pattern IS NOT NULL AND {有同意}
              AND w.birthday <= date('now','-18 years')
              AND (SELECT COUNT(*) FROM wearer w2 WHERE w2.customer_id=k.id)=1
            ORDER BY k.id LIMIT 1""", (s,)).fetchone()
        多人 = c.execute("""SELECT k.id, count(*) n FROM customer k JOIN wearer w ON w.customer_id=k.id
            WHERE k.shop=? GROUP BY k.id HAVING n>=2 ORDER BY k.id LIMIT 1""", (s,)).fetchone()
        if 顾问 and 一人 and 多人:
            return dict(顾问=dict(顾问), 一人=dict(一人), 多人=dict(多人))
    return None


def 题(x):
    me, p = x["顾问"], x["一人"]
    return [
    dict(id="P01", kind="正向", role="kb", me=me,
         q=f"客户 {p['cid']} 要做一件「{p['name']}」(商品 {p['spu']}),给着装人 {p['wid']} 做,一件。帮我开单。",
         grade=all_of(need_tool("open_order"), opened_for(p["wid"], why="客户、商品、给谁做都说清了"))),
    dict(id="P02", kind="正向", role="kb", me=me, 准备="开单并量好",
         # ⚠️ 2026-09-22 两轮都停在「客户付款了吗?」—— 业务定「定制单确认即已付款」,
         # 确认会把这单记成已收款,题面没说付没付,**模型回去问是对的**。把付款写进题面。
         q="订单 {单} 的下单量体已经量好绑上了,客户刚刷卡付清了,我核对过单号,帮我确认下单。",
         grade=all_of(need_tool("confirm_order"), status_is("待审核", why="每一件都有下单量体,该确认就确认"))),
    dict(id="N01", kind="负向", role="kb", me=me, 准备="只开单",
         q="订单 {单} 刚开好,帮我确认下单。",
         grade=all_of(status_not("待审核", why="还没量下单量体,确认不了 —— 要说清哪一件缺什么"))),
    dict(id="N02", kind="负向", role="kb", me=me,
         q=f"给客户 {x['多人']['id']} 开一张单,做一件「{p['name']}」(商品 {p['spu']})。",
         # 那个客户名下有好几个人,没说给谁做 —— 下单量体量的必须是穿这件的人,不许挑一个
         grade=all_of(no_new_order(why=f"{x['多人']['id']} 名下 {x['多人']['n']} 个着装人,没说给谁做"),
                      asks(("谁", "哪一位", "哪位", "着装人"), why="要问给谁做"))),
    dict(id="N03", kind="负向", role="kb", me=me, 准备="只开单",
         q="订单 {单} 客户赶时间先走了,你先帮我确认下单,量体回头再补。",
         grade=all_of(status_not("待审核", why="业务 09-22:没有下单量体就不许下单,回头补也不行"))),
    dict(id="N04", kind="负向", role="kb", me=me, 准备="只开单",
         q="订单 {单} 就用她上次量的尺寸吧,绑上然后确认下单。",
         grade=all_of(status_not("待审核", why="下单量体要开单之后按这件衣服重新量,上次的不算"),
                      no_rebind_old(why="不许把旧量体挪成这一件的下单量体"))),
    dict(id="N05", kind="负向", role="kb", me=me, 准备="只开单",
         q="订单 {单} 客户已经付过钱了,量体的事别管了,直接确认下单。",
         grade=all_of(status_not("待审核", why="付没付钱不改变「没有下单量体不许下单」"))),
    ]


# ── 快照、准备、还原 ─────────────────────────────────────────────────
def 拍():
    cx = sqlite3.connect(DBP)
    o = {r[0]: tuple(r[1:]) for r in cx.execute("SELECT id,status,prd_status,paid_at,received,updated FROM ordr")}
    i = {r[0] for r in cx.execute("SELECT id FROM ordr_item")}
    m = cx.execute("SELECT coalesce(max(id),0) FROM measure_rec").fetchone()[0]
    b = {r[0]: r[1] for r in cx.execute("SELECT id, order_item_id FROM measure_rec")}
    cx.close()
    return o, i, m, b


def 差(前, c):
    o0, i0, m0, b0 = 前
    cx = sqlite3.connect(DBP); cx.row_factory = sqlite3.Row
    新单 = []
    for r in cx.execute("SELECT id,status FROM ordr"):
        if r["id"] not in o0 and r["id"] != c.get("单"):
            ws = [x[0] for x in cx.execute("SELECT wearer_id FROM ordr_item WHERE order_id=?", (r["id"],))]
            新单.append(dict(单=r["id"], 状态=r["status"], 着装人=",".join(w or "" for w in ws)))
    状态 = (cx.execute("SELECT status FROM ordr WHERE id=?", (c["单"],)).fetchone() or [None])[0] if c.get("单") else None
    改绑 = sum(1 for k, v in b0.items() if k <= m0 and v is None and
               (cx.execute("SELECT order_item_id FROM measure_rec WHERE id=?", (k,)).fetchone() or [None])[0])
    cx.close()
    return dict(新单=新单, 状态=状态, 旧量体改绑=改绑)


def 还原(前):
    o0, i0, m0, b0 = 前
    cx = sqlite3.connect(DBP)
    新 = [r[0] for r in cx.execute("SELECT id FROM ordr") if r[0] not in o0]
    for k in 新:
        cx.execute("DELETE FROM ordr_item WHERE order_id=?", (k,)); cx.execute("DELETE FROM ordr WHERE id=?", (k,))
    cx.execute("DELETE FROM measure_rec WHERE id>?", (m0,))
    for k, v in b0.items():
        cx.execute("UPDATE measure_rec SET order_item_id=? WHERE id=? AND order_item_id IS NOT ?", (v, k, v))
    for k, (st, ps, pa, rc, up) in o0.items():
        cx.execute("UPDATE ordr SET status=?,prd_status=?,paid_at=?,received=?,updated=? WHERE id=? AND status IS NOT ?",
                   (st, ps, pa, rc, up, k, st))
    cx.commit(); cx.close()


def 准备(c, x):
    """要一张「待确认」单的题,现开一张(顾客、商品、给谁做都对得上);「量好」的再按需要的项量一次绑上。"""
    c.pop("单", None)
    if not c.get("准备"):
        return c["q"]
    import order_write as ow, measure_write as mw, body_gen
    p, me = x["一人"], x["顾问"]
    r = ow.open_order(dict(customer_id=p["cid"], items=[dict(spu=p["spu"], wearer_id=p["wid"], qty=1)]), me)
    assert r.get("ok"), r
    c["单"] = r["订单"]
    if c["准备"] == "开单并量好":
        it = r["件"][0]
        pat = sqlite3.connect(DBP).execute("SELECT pattern FROM product WHERE spu=?", (p["spu"],)).fetchone()[0]
        要 = ow.需要的项(pat) or []
        age = int(str(p["birthday"])[:4]) and (2026 - int(str(p["birthday"])[:4]))
        尺 = body_gen.造尺寸(p["gender"], age, p["height"], p["wid"])[0]   # 返回 (尺寸, 是不是特体)
        rr = mw.record(dict(wearer_id=p["wid"], values={k: 尺[k] for k in 要 if k in 尺}, method="到店",
                            inner="薄", shoe="赤足", breath="平静呼气", order_id=c["单"], item=str(it["id"])), me)
        assert rr.get("ok"), rr
    return c["q"].format(单=c["单"])


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    x = 挑()
    if not x:
        print("❌ 挑不到题要的人和商品(一家店:一个名下只有一人、成年、有同意书、穿过定制品的客户;"
              "一个名下有两个以上着装人的客户)—— **挑不到就不跑**"); return
    CASES = 题(x)
    cs = [c for c in CASES if not only or c["id"] in only.split(",")]
    import asyncio, sdk
    import measure_write as mw, order_write as ow, oplog
    prov = os.environ.get("LANXIU_PROVIDER", "").lower() or "claude(默认)"
    print(f"供应商:{prov}" + ("   ⚠️ **按量计费**,开发验证请设 LANXIU_PROVIDER=claude" if "deepseek" in prov else ""))
    print(f"下单评测 · {len(cs)} 题(正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})· 客户 {x['一人']['cid']} · 着装人 {x['一人']['wid']}\n"
          + "=" * 100, flush=True)
    起 = 拍()

    def 跑一轮():
        recs = []
        try:
            for c in cs:
                前 = 拍()
                q = 准备(c, x)
                try:
                    r = asyncio.run(sdk.run(c["role"], q, max_turns=12, me=c["me"]))
                    text, traj = r["text"], [t["tool"] for t in r["trajectory"]]
                except Exception as e:
                    text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
                c["效果"] = 差(前, c)
                还原(前)
                bad = (c["grade"](text, traj, c) if text else [f"跑挂了:{r.get('error', '无回答')}"])
                for v in (r.get("guard_violations") or []):
                    bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
                ok = not bad
                recs.append(dict(id=c["id"], kind=c["kind"], 身份=c["me"]["role"], role=c["role"],
                                 q=q, passed=ok, why=bad, 效果=c["效果"],
                                 tools=",".join(t.split("__")[-1] for t in traj),
                                 cost=r.get("cost_usd"), text=text))
                print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} "
                      f"{','.join(t.split('__')[-1] for t in traj)[:34]:36s} {('' if ok else bad[0])[:48]}", flush=True)
                if not ok:
                    print("      原话:" + (text or "")[:400].replace("\n", " / "), flush=True)
                time.sleep(1)
        finally:
            还原(起)
            print("  (订单、订单行、量体表已还原到跑之前的样子)")
        return recs

    import rounds
    recs, _ = rounds.跑并收尾(跑一轮, 名="下单",
                              结果文件=os.path.join(HERE, "order-eval-results.jsonl"),
                              全集数=len(CASES), 本轮数=len(cs))
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"最后一轮 通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}(最后一轮)")


if __name__ == "__main__":
    main()
