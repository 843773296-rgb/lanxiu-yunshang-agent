# -*- coding: utf-8 -*-
"""会员等级 / 积分 / 审批的验法。

**和复盘、漏斗那两套不一样:这里的主角是绝对判定。**
等级门槛是白纸黑字的数(实付 ≥5000 或 完成 ≥2 单),
所以**逐例标真值,而且专挑边界** —— 正好 5000 算不算、正好 2 单算不算。
相对指标在这块几乎没有,只有审批通过率那一个。

## 为什么边界值得单独挑

差一块钱的两个客户拿不同的等级,这是规则决定的、也是对的。
错的是**边界挪了一格而没人发现**:把 `>=` 写成 `>`,
那么正好卡在 5000 的客户会掉一档 —— 他不会来投诉「我算错了」,
他只会觉得这家店不认账。**边界上的错不会报错,只会静静地得罪人。**

## 口径对账那一条,验的是「另一个口径会错」

光验「按滚动 12 个月算全对」不够 —— 那只说明实现和自己一致。
还要验**按累计算会错**:如果两种算法结果一样,
这条口径就是白写的,而「滚动 12 个月」这五个字也就没有意义。
**一条区分不出任何东西的规则,等于没有这条规则。**
"""
import os, sys, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import api
import knowledge.member as mb

MGR = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把一个客户的等级改成门槛表里没有的档',
     '库里每个客户的等级都算得出来'),
]

class 不许留痕:
    """在这个块里对 `approval` 表做的任何改动,出块时**一律还原**。

    为什么需要它:下面几条验的是「越权的人批不了」,**正常情况下一个字都不会改**。
    但咬合的时候把角色判定拿掉,那一批就**真的批下去了** —— 实测把
    AP-LV-001 从「待审批」改成了「已通过」,还留了条「店长试着批一张」的批注。

    **一条在被测代码坏掉时会改数据的检查,比没有这条检查更糟** ——
    它会在你最忙的那天(代码刚坏)悄悄污染一份夹具,
    而你正忙着看红的那一条,不会注意到它。

    这和「造数据污染夹具」是同一个病(见 CLAUDE.md):
    **夹具和普通数据之间有边,而那条边从写的这一侧看不见。**
    """
    def __enter__(self):
        with sqlite3.connect(api.DB) as c:
            c.row_factory = sqlite3.Row
            self.snap = [dict(r) for r in c.execute("SELECT * FROM approval")]
        return self

    def __exit__(self, *e):
        with sqlite3.connect(api.DB) as c:
            c.execute("DELETE FROM approval")
            for r in self.snap:
                cols = ",".join(r); q = ",".join("?" * len(r))
                c.execute(f"INSERT INTO approval({cols}) VALUES({q})", list(r.values()))
        return False
ADV = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
HQ = {"no": "60000008", "name": "魏欣新", "role": "总部运营", "shop": ""}
FAIL = []
SNAP0 = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def cfg():
    return api._rows("SELECT code,name,amount,orders,sort,need_points FROM level_cfg "
                     "WHERE status='启用'")


def main():
    print("会员等级 / 积分 / 审批 · 检查")
    print("=" * 78)
    global SNAP0
    SNAP0 = [tuple(r.values()) for r in api._rows("SELECT * FROM approval ORDER BY id")]
    C = cfg()

    # ① 逐例:库里每个客户的档,和按门槛算的一致。
    n1 = bad1 = 0
    for r in api._rows("SELECT id,level,amount_12m,orders_12m FROM customer"):
        n1 += 1
        if mb.判档(r["amount_12m"], r["orders_12m"], C) != r["level"]: bad1 += 1
    ck("库里每个客户的等级都算得出来", bad1 == 0, n1, f"对不上 {bad1}")

    # ② **边界逐例标真值** —— 银卡门槛 5000 / 2 单。
    #    差一块钱掉一档是对的;边界挪一格没人会发现,只会静静地得罪人。
    cs = [(4999.99, 0, "普通", "差一分钱 → 还是普通"),
          (5000.00, 0, "银卡", "**正好 5000 → 够了**(含端)"),
          (5000.01, 0, "银卡", "多一分 → 银卡"),
          (0, 1, "普通", "1 单 → 不够"),
          (0, 2, "银卡", "**正好 2 单 → 够了**(含端)"),
          (0, 6, "黑金", "6 单 → 直接黑金(门槛是**或**,金额可以是 0)"),
          (30000, 0, "黑金", "3 万 0 单 → 黑金(同上,反过来)"),
          (14999, 3, "银卡", "金额差一点、单数也差一点 → 只够银卡"),
          (0, 0, "普通", "什么都没有 → 普通")]
    bad2 = [c[3] for c in cs if mb.判档(c[0], c[1], C) != c[2]]
    ck("等级门槛的边界", not bad2, len(cs), ("挂了:" + "；".join(bad2)) if bad2 else "")

    # ③ **另一个口径必须会错** —— 否则「滚动 12 个月」这五个字没有意义。
    diff = 0; n3 = 0
    for r in api._rows("SELECT level,amount_12m,orders_12m,paid_amount,order_cnt FROM customer"):
        n3 += 1
        if mb.判档(r["paid_amount"], r["order_cnt"], C) != r["level"]: diff += 1
    ck("按「累计」算会算错(说明这条口径真的在区分东西)", diff > 0, n3,
       f"累计口径错 {diff} 个 —— **一条区分不出东西的规则等于没有**")

    # ④ 积分对账:口径函数在人造数据上必须**既抓得到断点、又不误报**。
    ok4 = (mb.积分对账([{"balance": 100, "delta": 0}, {"balance": 150, "delta": 50}]) == []
           and len(mb.积分对账([{"balance": 100, "delta": 0},
                               {"balance": 999, "delta": 50}])) == 1)
    ck("积分对账:连得上不报、断了要报", ok4, 2)

    # ④·2 全库积分链:**修过一次之后,一处断点都不许有**。
    #     这条和 ④ 分开:④ 验的是「口径函数会不会判」,这条验的是「数据对不对」。
    #     合成一条的话,数据坏了会被报成「口径函数坏了」—— **红错理由比不红更费事**。
    n42 = bad42 = 0; 例42 = ""
    for cid, in api._rows2("SELECT DISTINCT customer_id FROM points_log"):
        rows = api._rows("SELECT behavior,delta,balance,ts FROM points_log "
                         "WHERE customer_id=? ORDER BY ts,rowid", cid)
        n42 += 1
        b = mb.积分对账(rows)
        if b:
            bad42 += 1
            例42 = 例42 or f"{cid} 有 {len(b)} 处"
    ck("全库积分链一处断点都没有", bad42 == 0, n42,
       例42 or "修过一次(中间余额曾被截断),现在链条是通的")

    # ④·3 **两个来源在终点必须一致** —— 修中间的时候不许把终点改掉。
    #     这条是上一条的对照:光把链条修通很容易(全写成 0 也通),
    #     **同时还要和档案上的余额对得上**,才说明修对了。
    n43 = bad43 = 0
    for cid, in api._rows2("SELECT DISTINCT customer_id FROM points_log"):
        rows = api._rows("SELECT balance FROM points_log WHERE customer_id=? "
                         "ORDER BY ts,rowid", cid)
        p = api._rows("SELECT points FROM customer WHERE id=?", cid)
        n43 += 1
        if not p or rows[-1]["balance"] != p[0]["points"]: bad43 += 1
    ck("档案上的余额 = 流水最后一条(两个来源在终点一致)", bad43 == 0, n43,
       "光把链条修通不算修对 —— 全写成 0 链条也是通的")

    # ⑤ 审批的角色判定**只有一处** —— 工具不许自己再判一遍。
    #    验法:拿非总部运营去批,必须被拒,而且**理由要来自状态机**。
    r5 = None
    pend = api._rows("SELECT id FROM approval WHERE status='待审批' LIMIT 1")
    n5 = len(pend)
    if pend:
        with 不许留痕(), api.as_user(MGR):
            r5 = api.decide_approval(pend[0]["id"], True, "店长试着批一张")
    ck("非总部运营批不了(判定在状态机里)",
       bool(r5) and not r5.get("ok") and r5.get("code") == "WRONG_ROLE", n5,
       (r5 or {}).get("reason", "")[:50])

    # ⑥ 终态不许续流转 —— 批过的再批一次必须拒。
    done = api._rows("SELECT id FROM approval WHERE status IN ('已通过','已驳回') LIMIT 1")
    r6 = None
    if done:
        with 不许留痕(), api.as_user(HQ):
            r6 = api.decide_approval(done[0]["id"], True, "已经批过了,再来一次")
    ck("批过的单子不许再批(终态)",
       bool(r6) and not r6.get("ok") and r6.get("code") == "TERMINAL", len(done),
       (r6 or {}).get("reason", "")[:40])

    # ⑦ 隔离:顾问提不了审批单,也批不了。
    with 不许留痕(), api.as_user(ADV):
        a7 = api.apply_adjust("等级调整", "C10001", {"to": "黑金"}, "顾问试着提一张")
        b7 = api.decide_approval((pend or [{"id": "AP-LV-001"}])[0]["id"], True, "顾问试着批")
    ck("顾问既提不了也批不了",
       (not a7.get("ok")) and (not b7.get("ok")), 2,
       f"{a7.get('code')} / {b7.get('code')}")

    # ⑧ 查无此人 ≠ 这人没资格。**这两种混在一起,模型会答「他不够格」**。
    with 不许留痕(), api.as_user(MGR):
        e8 = api.member_level("C99999")
        f8 = api.apply_adjust("等级调整", "C99999", {"to": "黑金"}, "给一个不存在的人升档")
    ck("查无此人要说「查无此人」,不能说成「没资格」",
       "查无此人" in str(e8.get("error", "")) and f8.get("code") == "NO_CUSTOMER", 2)

    # ⑨ 必填项真的拦得住 —— 理由、批注、payload。
    with 不许留痕(), api.as_user(MGR):
        g = [api.apply_adjust("等级调整", "C10001", {"to": "黑金"}, "短"),
             api.apply_adjust("等级调整", "C10001", {}, "payload 是空的"),
             api.apply_adjust("发红包", "C10001", {"x": 1}, "不受理的类型")]
    codes = [x.get("code") for x in g]
    ck("必填与类型白名单拦得住", codes == ["NEED_REASON", "NEED_PAYLOAD", "BAD_KIND"],
       len(g), str(codes))

    # ⑩ **这条检查自己不许留痕。** 上面几条越权用例,正常情况下一个字都不改;
    #    但被测代码一旦坏掉就会真的写进去 —— 所以跑完再对一遍。
    after = [tuple(r.values()) for r in api._rows("SELECT * FROM approval ORDER BY id")]
    ck("检查跑完,审批表和跑之前一模一样", after == SNAP0, len(after),
       "一条在代码坏掉时会改数据的检查,比没有这条检查更糟")

    print("=" * 78)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 会员等级 / 积分 / 审批 12 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
