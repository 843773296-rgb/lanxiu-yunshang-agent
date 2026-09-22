#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白坯试衣两个写口的检查 —— **开裁那道闸真的会拦,而且绕不过去。**

业务 2026-09-22 定:重工 / 全定制 / 婚服三类必试,客户签字就行,**没签字不许开裁**。
原来这道闸「没有东西可拦」(系统里没有写口推进裁剪),看板上写着一句「拦不住」。
现在有两条路能开裁:版师的 `start_cutting`、后台通用的改状态(`server.transit`)。
**两条都要被拦** —— 只拦写口的话,从后台点一下就绕过去了,而绕过去在库里和正常开裁长得一样。

## 为什么在副本上测

这套检查**真的写库**(登记试衣、补签、开裁)。项目在「检查污染数据」上栽过
(piece_ratio_check 每跑一次把一行悄悄降级,而且降完照样全绿)。
所以这里**把库复制到临时目录**,所有模块指向副本 —— 真库一行都不碰,也就不存在「忘了还原」。

## 钉的几件事

    权限     顾问不能开裁、版师不能登记、别店不能登记
    闸       没试 / 试了没签 → 拒;全部签了 → 放行;**后台改状态同样被拦**
    签字     不写改了什么拒;不许撤销签字;补签只补一次
    新旧规   经系统开裁的单按新规;闸上线前裁的老单按旧规(不追溯)
"""
import os, sys, shutil, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), ROOT]

# ── 咬合记录 ────────────────────────────────────────────────────────────
# 每一条在 tools/bite_specs.json 里有可执行规格:对照先绿 → 改坏 → 红的必须是右边这一条。
咬合 = [
    ("把订单状态机上的白坯闸去掉(待生产→生产中不再看过闸结果)",
     "后台改状态同样被拦(不能绕)"),
    ("让后台改状态时直接把过闸结果写成「可以」(不真算)",
     "后台改状态同样被拦(不能绕)"),
    ("拆掉「签字不能撤销」那道拦截",
     "给已有轮次却不签 → 拒(签字不能撤销)"),
    ("让 能不能开裁() 在试了没签时放行",
     "试了没签 → 仍被拦"),
    ("把顾问也加进开裁角色",
     "顾问不能开裁"),
]

FAIL, N = [], [0]


def ck(name, ok, extra=""):
    N[0] += 1
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + str(extra)[:150]) if extra else ''}")
    if not ok: FAIL.append(name)


def main():
    print("白坯试衣写口 · 检查(在库的临时副本上跑,真库不动)")
    print("=" * 84)
    tmp = tempfile.mkdtemp(prefix="fitw-")
    T = os.path.join(tmp, "lanxiu.db")
    shutil.copy(os.environ.get("FITW_SRC") or os.path.join(HERE, "lanxiu.db"), T)
    try:
        run(T)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(f"\033[31m❌ 白坯试衣写口 {len(FAIL)} 处不符合预期(验了 {N[0]} 条)\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 白坯试衣写口 {N[0]} 条全过\033[0m —— 开裁那道闸会拦、绕不过、签字撤不掉")


def run(T):
    import api, oplog, tasks, fitting_write as fw, server
    for m in (api, oplog, tasks, fw, server): m.DB = T
    c = sqlite3.connect(T); c.row_factory = sqlite3.Row
    cols = {r["name"] for r in c.execute("PRAGMA table_info(ordr)")}
    if "cut_at" not in cols:
        ck("库里有开裁记录这一列", False, "没有 cut_at —— 要跑 ./tools/rebuild.sh 让 seed.py 的新列生效")
        return

    def 人(role, shop=None, 别店=None):
        sql = "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'"
        a = [role]
        if shop: sql += " AND shop=?"; a.append(shop)
        if 别店: sql += " AND shop!=?"; a.append(别店)
        r = c.execute(sql + " ORDER BY no LIMIT 1", a).fetchone()
        return dict(r) if r else None

    # **按性质挑单,不钉死单号**:要一张「待生产、被闸拦住、而且拦它的全是『该试没试』」的单
    # (判不了的那种补试衣也过不去,测不到放行那一半)
    挑 = None
    for o in c.execute("SELECT id,shop FROM ordr WHERE kind='定制品订单' AND status='待生产' ORDER BY id"):
        g, w, d = fw.过闸(o["id"])
        拦 = [x for x in d if x["能不能开裁"] != "可以"]
        if g == "不可以" and 拦 and all(x["属于哪几类"] for x in 拦):
            挑 = (o["id"], o["shop"], 拦); break
    ck("有一张被闸拦住、补齐试衣就能放行的待生产单", bool(挑),
       "没有 —— **放行那一半测不到**,而「只会拦」的闸和坏了的闸长得一样")
    if not 挑: return
    oid, shop, 拦 = 挑
    顾问, 版师, 别店顾问 = 人("顾问", shop), 人("版师"), 人("顾问", 别店=shop)
    ck("本店顾问、版师、别店顾问都找得到", bool(顾问 and 版师 and 别店顾问))
    if not (顾问 and 版师 and 别店顾问): return
    行 = [str(x["订单行"]) for x in 拦]

    # ── 权限 ───────────────────────────────────────────────────────────
    with api.as_user(顾问): r = api.start_cutting(oid)
    ck("顾问不能开裁", r.get("code") == "ROLE", r.get("reason"))
    with api.as_user(版师): r = api.record_fitting(oid, 行[0], "无需调整", True)
    ck("版师不能登记试衣", r.get("code") == "ROLE", r.get("reason"))
    with api.as_user(别店顾问): r = api.record_fitting(oid, 行[0], "无需调整", True)
    ck("别店顾问不能登记本店的单", r.get("code") == "OTHER_SHOP", r.get("reason"))
    r = api.record_fitting(oid, 行[0], "无需调整", True)
    ck("没登录不能登记", bool(r.get("error")), r)

    # ── 闸:没试 → 拒,两条路都拒 ─────────────────────────────────────
    with api.as_user(版师): r = api.start_cutting(oid)
    ck("没试没签 → 开裁被拦", r.get("code") == "MUSLIN_GATE", r.get("reason"))
    ck("被拦时列出了卡住的是哪几件", len(r.get("逐件") or []) >= len(行))
    r = server.transit("bk-order", oid, "生产中", {}, actor="检查")
    ck("后台改状态同样被拦(不能绕)", r.get("code") == "MUSLIN_GATE", r.get("reason"))
    ck("被拦之后订单还在待生产",
       c.execute("SELECT status FROM ordr WHERE id=?", (oid,)).fetchone()[0] == "待生产")

    # ── 登记与签字 ─────────────────────────────────────────────────────
    # ⚠️ **先把其余几件都试完签好,只留第一件。** 第一版顺序反了:测「试了没签 → 仍被拦」时
    # 另外几件还没试,整单本来就过不去 —— 把「没签也放行」改坏了照样绿(咬合当场抓到)。
    # **要测一件的判断,就得让别的件都不构成拦的理由。**
    for ln in 行[1:]:
        with api.as_user(顾问): api.record_fitting(oid, ln, "无需调整", True)
    with api.as_user(顾问): r = api.record_fitting(oid, 行[0], "", False)
    ck("新一轮不写改了什么 → 拒", r.get("code") == "NEED_ADJUST", r.get("reason"))
    with api.as_user(顾问): r = api.record_fitting(oid, 行[0], "腰围放 1cm", False)
    ck("登记一轮试衣(客户未签)", bool(r.get("ok")), r.get("reason"))
    轮 = r.get("第几轮")
    陪 = c.execute("SELECT advisor_no FROM fitting WHERE item_id=? AND round=?", (int(行[0]), 轮)).fetchone()
    ck("陪同人记的是登录的那个人", bool(陪) and 陪[0] == 顾问["no"])
    with api.as_user(版师): r = api.start_cutting(oid)
    ck("试了没签 → 仍被拦", r.get("code") == "MUSLIN_GATE"
       and [x["订单行"] for x in r.get("逐件") or [] if x["能不能开裁"] != "可以"] == [int(行[0])],
       r.get("reason"))
    with api.as_user(顾问): r = api.record_fitting(oid, 行[0], round=轮, signed=False)
    ck("给已有轮次却不签 → 拒(签字不能撤销)", r.get("code") == "NO_UNSIGN", r.get("reason"))
    with api.as_user(顾问): r = api.record_fitting(oid, 行[0], round=轮, signed=True, note="到店补签")
    ck("补签", r.get("code") == "FIT_SIGN", r.get("reason"))
    with api.as_user(顾问): r = api.record_fitting(oid, 行[0], round=轮, signed=True)
    ck("同一轮补签第二次 → 拒", r.get("code") == "ALREADY", r.get("reason"))

    # ── 闸:全部签了 → 放行 ──────────────────────────────────────────
    with api.as_user(版师): r = api.start_cutting(oid)
    ck("每一件都试过并签字 → 开裁成功", bool(r.get("ok")), r.get("reason"))
    o = dict(c.execute("SELECT status,prd_status,cut_at,cut_by FROM ordr WHERE id=?", (oid,)).fetchone())
    ck("开裁写了状态、PRD 口径和开裁记录",
       o["status"] == "生产中" and o["prd_status"] == "方案确认中" and o["cut_at"] and o["cut_by"] == 版师["no"], o)
    with api.as_user(版师): r = api.start_cutting(oid)
    ck("已经开裁的单再开 → 拒", r.get("code") == "BAD_STATE", r.get("reason"))

    # ── 新规 / 旧规 ───────────────────────────────────────────────────
    f = api._白坯试衣(oid, None, "生产中", item_id=int(行[0]))
    ck("经系统开裁的单按新规判", (f.get("按哪套规矩") or "").startswith("新规"), f.get("按哪套规矩"))
    老 = c.execute("SELECT i.id, i.order_id FROM ordr_item i JOIN ordr o ON o.id=i.order_id "
                  "WHERE o.kind='定制品订单' AND o.status='完成' AND o.cut_at IS NULL ORDER BY i.id LIMIT 1").fetchone()
    f = api._白坯试衣(老["order_id"], None, "完成", item_id=老["id"]) if 老 else {}
    ck("闸上线前裁的老单按旧规(不追溯判我方)", (f.get("按哪套规矩") or "").startswith("旧规"), f.get("按哪套规矩"))


if __name__ == "__main__":
    main()
