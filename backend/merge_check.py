#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户软合并 · 检查 —— 在库的临时副本上跑,真库不动。

用户 2026-10-14 拍:做软合并,并把现有硬合并改成它。要守的:
  · **数据一行不搬**(合并前后各表里挂在副档上的行数不变)—— 硬合并最大的问题是搬了一半;
  · 保留**建档最早**的当主档;**能撤**,撤完恢复原样;
  · 只有**总部运营**能执行 / 撤销(两段确认的第二段),成功被拒都留痕;
  · 客户列表不再单列副档,按副档号搜得到主档;详情页:副档告诉页面主档是谁,主档列关联档案**各列各的不相加**;
  · 审批中心「已合并」走软合并、执行人从登录态取;研判「客户合并确认」凭合并记录办结。
⚠️ 要合并的那一对**自己造**(挑两条档案、副本上把建档时间摆成已知先后),不靠库里碰上的。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agent")]
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("并入时把副档的订单改指主档(变成硬合并)", "数据一行不搬:副档名下的订单 / 量体 / 预约行数不变"),
    ("主档挑建档较晚的那条", "保留建档最早的那条当主档"),
    ("执行合并不查角色", "店长不能执行合并(两段确认:执行只认总部运营)"),
    ("客户列表不标并入了谁", "客户列表照样列副档,并标上并入了谁(各店还要在本店那份上开单)"),
    ("AI 工具查订单只查主档(不连关联档)", "AI 工具:查副档的订单 → 两条档案的单一起列、每单标着原档案"),
    ("数人头不过滤已并入的档案", "数人头按人:合并后工作台客户数少一个(两条档案算一个人)"),
    ("并入时不压平", "并入时压平:挂在副档下的档案一并改指新主档"),
    ("撤销入口不要原因", "撤销入口:店长撤不了、不写原因撤不了(都没撤成)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


def 拒了吗(f):
    try:
        f(); return False
    except PermissionError:
        return True


print("客户软合并 · 检查(库的临时副本上跑,真库不动)")
print("=" * 80)
tmp = tempfile.mkdtemp(prefix="merge-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(HERE, "lanxiu.db"), db)
import merge as MG, ops, oplog, server as SV
MG.DB = ops.DB = oplog.DB = SV.DB = db
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
MG.确保列()


def 员工(角色):
    r = c.execute("SELECT no, name, role FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", (角色,)).fetchone()
    return dict(r) if r else None


店长, 总部 = 员工("店长"), 员工("总部运营")
# 挑两条**都有订单**的档案,建档时间摆成已知先后:甲早、乙晚
两条 = c.execute("SELECT customer_id FROM ordr GROUP BY customer_id HAVING COUNT(*)>=1 ORDER BY customer_id LIMIT 2").fetchall()
ck("有店长、总部运营、两条有订单的档案可拿来造(空集合上什么都成立)", bool(店长 and 总部 and len(两条) == 2))
if 店长 and 总部 and len(两条) == 2:
    甲, 乙 = 两条[0][0], 两条[1][0]
    c.execute("UPDATE customer SET created='2020-01-01', merged_into=NULL WHERE id=?", (甲,))
    c.execute("UPDATE customer SET created='2024-06-01', merged_into=NULL WHERE id=?", (乙,))
    # 乙用一个库里没有的名字:按名字搜的那条要验「认到主档」,而常见姓名在库里本来就有别的同名人(真重名)
    c.execute("UPDATE customer SET name='检查专用·乙' WHERE id=?", (乙,))
    c.commit()
    表们 = ("ordr", "measure_rec", "appointment", "followup", "deposit", "rating", "points_log")
    def 行数(cid):
        return {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE customer_id=?", (cid,)).fetchone()[0] for t in 表们}
    前乙 = 行数(乙)

    ck("没身份 → 拒", 拒了吗(lambda: MG.并入(乙, 甲, None)))
    ck("店长不能执行合并(两段确认:执行只认总部运营)", 拒了吗(lambda: MG.并入(乙, 甲, 店长)))
    ck("同一个档案号不能并", MG.并入(甲, 甲, 总部).get("code") == "SAME")
    r = MG.并入(乙, 甲, 总部)     # 故意把晚的放前面
    ck("保留建档最早的那条当主档", r.get("ok") and r.get("主档") == 甲 and r.get("副档") == 乙, r)
    ck("数据一行不搬:副档名下的订单 / 量体 / 预约行数不变", 行数(乙) == 前乙, (前乙, 行数(乙)))
    ck("副档记上了并入谁", c.execute("SELECT merged_into FROM customer WHERE id=?", (乙,)).fetchone()[0] == 甲)
    ck("主档 / 关联档 / 合并过吗 都认得出", MG.主档(乙) == 甲 and MG.关联档(甲) == [甲, 乙] and MG.合并过吗(甲, 乙))
    lg = c.execute("SELECT actor, code FROM op_log WHERE machine='customer-merge' ORDER BY rowid DESC LIMIT 1").fetchone()
    ck("合并写进 op_log,查得到是谁", lg and lg["code"] == "MERGE" and 总部["no"] in lg["actor"], dict(lg) if lg else None)
    ck("已经是同一个人的再并 → 不重复", MG.并入(甲, 乙, 总部).get("code") == "ALREADY")

    列 = {x["id"]: x for x in SV.customer_list({"size": ["100000"]})["rows"]}
    ck("客户列表照样列副档,并标上并入了谁(各店还要在本店那份上开单)",
       乙 in 列 and 列[乙].get("已并入") == 甲 and 甲 in 列 and not 列[甲].get("已并入"), 列.get(乙))
    详乙, 详甲 = SV.customer_detail(乙), SV.customer_detail(甲)
    ck("副档详情告诉页面主档是谁", 详乙.get("已并入") == 甲)
    关 = 详甲.get("关联档案") or []
    ck("主档详情列出关联档案,订单数各列各的(不相加)",
       len(关) == 1 and 关[0]["id"] == 乙 and 关[0]["订单数"] == 前乙["ordr"], 关)

    # ── 第 2 批:AI 工具按客户号 / 姓名认人,认得软合并 ─────────────────────
    import api as AP
    AP.DB = db
    名甲, 名乙 = (c.execute("SELECT name FROM customer WHERE id=?", (x,)).fetchone()[0] for x in (甲, 乙))
    人们, 注 = AP._认客户(乙)
    ck("AI 工具:给副档号 → 认成主档,并注明已并入", len(人们) == 1 and 人们[0]["id"] == 甲
       and 人们[0]["关联"] == [甲, 乙] and 乙 in (注 or ""), (人们, 注))
    ck("AI 工具:按副档的名字搜(和主档不同名)也认到主档", 名乙 != 名甲 and [x["id"] for x in AP._认客户(名乙)[0]] == [甲],
       (名乙, 名甲, AP._认客户(名乙)[0]))
    单 = AP.get_order(customer=乙)
    甲单 = c.execute("SELECT COUNT(*) FROM ordr WHERE customer_id=?", (甲,)).fetchone()[0]
    ck("AI 工具:查副档的订单 → 两条档案的单一起列、每单标着原档案",
       单.get("hit") == 甲单 + 前乙["ordr"] and {o["档案"] for o in 单["orders"]} == {甲, 乙}, {k: 单.get(k) for k in ("hit", "关联档案")})
    ck("AI 工具:合并过的客户,订单返回里提醒「金额别加总、积分等级各算」",
       "别替他加总" in (单.get("⚠合并") or ""), 单.get("⚠合并"))
    售 = AP.get_aftersale(customer=乙)
    售数 = c.execute("SELECT COUNT(*) FROM aftersale WHERE customer_id IN (?,?)", (甲, 乙)).fetchone()[0]
    ck("AI 工具:查副档的售后 → 两条档案的一起列", (售.get("hit") or 0) == 售数, (售.get("hit"), 售数))
    # 老库 = 一张**没有 merged_into 列**的 customer 表。⚠️ 不能拿真库副本 DROP COLUMN 造:
    # SQLite 按原 DDL 重建表,这个项目的建表语句注释极多,老版本 SQLite(CI 上那个)当场报
    # 「incomplete input」—— 本机版本新不崩,CI 崩(10-14 连红四次,数据工厂查出)。直接建一张最小的表,不靠版本。
    import tempfile as _tf
    _老 = os.path.join(_tf.mkdtemp(prefix="merge-old-"), "lanxiu.db")
    _o = sqlite3.connect(_老)
    _o.execute("CREATE TABLE customer(id TEXT PRIMARY KEY, name TEXT)")
    _o.execute("INSERT INTO customer(id,name) VALUES(?,?)", (甲, 名甲)); _o.commit(); _o.close()
    AP.DB = _老
    try:
        _人, _ = AP._认客户(甲); _好 = [x["id"] for x in _人] == [甲]
    except Exception as e:                                                  # noqa: BLE001
        _好 = False; _人 = repr(e)
    _o = sqlite3.connect(_老)
    _没写 = "merged_into" not in {r[1] for r in _o.execute("PRAGMA table_info(customer)")}
    _o.close()
    AP.DB = db
    ck("老库(没有并入列):AI 工具照常认人、而且一个字都不写(工具层是只读的)", _好 and _没写, _人)

    # ── 第 4 批:数人头按人算、归主档所在店(用户 10-14 拍)────────────────────
    # 合并状态下,两条档案只算一个人;按店数时这个人只算在主档那家店
    店甲 = c.execute("SELECT shop FROM customer WHERE id=?", (甲,)).fetchone()[0]
    店乙 = c.execute("SELECT shop FROM customer WHERE id=?", (乙,)).fetchone()[0]
    import server as _S
    def _工作台人数():
        return int(next(x for x in _S.workbench()["metrics2"] if x["label"] == "客户")["value"])
    MG.撤销(乙, 总部); 前人 = _工作台人数()
    前店乙 = _S.shop_detail((店乙 or "").split(" ")[0]).get("cust") if 店乙 else None
    MG.并入(甲, 乙, 总部); 后人 = _工作台人数()
    后店乙 = _S.shop_detail((店乙 or "").split(" ")[0]).get("cust") if 店乙 else None
    ck("数人头按人:合并后工作台客户数少一个(两条档案算一个人)", 后人 == 前人 - 1, (前人, 后人))
    if 店乙 and 店乙 != 店甲:
        ck("按店数归主档所在店:副档那家店少一个人", 后店乙 == 前店乙 - 1, (店乙, 前店乙, 后店乙))
    ck("AI 工具:某档多少人也按人数(不数副档)",
       all(x["id"] != 乙 for x in AP.get_lifecycle(lifecycle=c.execute(
           "SELECT lifecycle FROM customer WHERE id=?", (乙,)).fetchone()[0]).get("rows", [])))

    # ── 只有一层:并入时压平,而且**直接量这个保证**(不靠「每次都记得压平」)──────────
    丙 = c.execute("SELECT id FROM customer WHERE id NOT IN (?,?) AND (merged_into IS NULL OR merged_into='') "
                  "ORDER BY id LIMIT 1", (甲, 乙)).fetchone()[0]
    c.execute("UPDATE customer SET created='2025-01-01' WHERE id=?", (丙,)); c.commit()
    MG.撤销(乙, 总部)
    MG.并入(乙, 丙, 总部)            # 乙(2024)收了丙(2025)
    MG.并入(甲, 乙, 总部)            # 再把乙并进甲(2020)—— 丙必须跟着改指甲
    ck("并入时压平:挂在副档下的档案一并改指新主档", c.execute(
        "SELECT merged_into FROM customer WHERE id=?", (丙,)).fetchone()[0] == 甲)

    def _两层(con):
        return con.execute("SELECT a.id, a.merged_into, b.merged_into FROM customer a JOIN customer b "
                           "ON b.id=a.merged_into WHERE COALESCE(b.merged_into,'')<>'' LIMIT 3").fetchall()
    ck("全库扫:没有一条档案并到一个「自己也已并入别人」的档案上(副本)", not _两层(c), _两层(c))
    MG.撤销(丙, 总部)

    ck("店长不能撤销合并", 拒了吗(lambda: MG.撤销(乙, 店长)))
    r = MG.撤销(乙, 总部)
    ck("能撤:撤完恢复独立,数据照旧", r.get("ok") and MG.主档(乙) == 乙 and not MG.合并过吗(甲, 乙) and 行数(乙) == 前乙, r)
    ck("没并过的撤 → 说清没并过", MG.撤销(乙, 总部).get("code") == "NOT_MERGED")

    # ── 审批中心那条流转:改成软合并、执行人从登录态取 ──────────────────────
    c.execute("INSERT INTO task(id,type,ref_id,status,created,summary) VALUES('T-检查合并','客户合并确认',?,'待处理','2026-01-01','检查')",
              (f"{甲}|{乙}",)); c.commit()
    r1 = SV.merge_transit("T-检查合并", "待总部审批", "生日地址一致", me=店长)
    r2 = SV.merge_transit("T-检查合并", "已合并", "审批通过", me=店长)
    ck("审批中心:店长不能点「已合并」", r1.get("ok") and not r2.get("ok"), (r1.get("reason"), r2.get("reason")))
    r3 = SV.merge_transit("T-检查合并", "已合并", "审批通过", me=总部)
    ck("审批中心:总部运营点「已合并」→ 走软合并,数据不搬",
       r3.get("ok") and MG.合并过吗(甲, 乙) and 行数(乙) == 前乙, r3)
    lg = c.execute("SELECT actor FROM op_log WHERE machine='customer-merge' AND code='MERGE' ORDER BY rowid DESC LIMIT 1").fetchone()
    ck("审批中心那一笔的执行人是登录的那个人(不是写死的名字)", lg and 总部["no"] in lg["actor"], dict(lg) if lg else None)

    # ── 客户详情页「撤销合并」入口(10-20 补:原来只有函数,页面和接口都没处调)──────────────
    详主, 详副 = SV.customer_detail(甲), SV.customer_detail(乙)
    ck("客户详情:主档列出关联档,副档说清并入了谁(接口)",
       any(x["id"] == 乙 for x in 详主.get("关联档案") or []) and 详副.get("已并入") == 甲,
       (详主.get("关联档案"), 详副.get("已并入")))
    u1 = SV.customer_unmerge(乙, "检查", me=店长)
    u2 = SV.customer_unmerge(乙, "  ", me=总部)
    ck("撤销入口:店长撤不了、不写原因撤不了(都没撤成)",
       not u1.get("ok") and u2.get("code") == "NO_NOTE" and MG.合并过吗(甲, 乙), (u1, u2))
    u3 = SV.customer_unmerge(乙, "检查:认错人了", me=总部)
    lg = c.execute("SELECT * FROM op_log WHERE machine='customer-merge' AND code='UNMERGE' ORDER BY rowid DESC LIMIT 1").fetchone()
    ck("撤销入口:总部运营写了原因 → 撤成,操作日志记着谁撤的、为什么",
       u3.get("ok") and not MG.合并过吗(甲, 乙) and lg and 总部["no"] in lg["actor"] and "认错人了" in str(dict(lg)),
       (u3, dict(lg) if lg else None))
    页 = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    ck("客户详情页:显示「已并入 / 关联档案」,撤销按钮接到撤销接口",
       "d.已并入" in 页 and "d.关联档案" in 页 and 'doOp("/api/customer-unmerge"' in 页 and "[data-unmerge]" in 页)
    MG.并入(甲, 乙, 总部)

    # ── 研判:客户合并确认凭合并记录办结 ─────────────────────────────────
    MG.撤销(乙, 总部)
    tid = ops.save_triage("T-检查合并", "BP-02", "检查", "根因:检查\n建议动作:合并", [])
    ops.resolve(tid, "已采纳", 店长, 来源="检查")
    r = ops.办结(tid, f"{甲}|{乙}", 总部)
    ck("研判:还没合并 → 办结不了", r.get("code") == "NO_RECEIPT", r)
    MG.并入(甲, 乙, 总部)
    r = ops.办结(tid, f"{甲}|{乙}", 总部)
    ck("研判:合并了 → 凭合并记录办结", r.get("ok") and r.get("回执类型") == "合并记录", r)
c.close()
shutil.rmtree(tmp, ignore_errors=True)

# 真库也扫一遍(只读):这条保证不靠「每次 并入 都记得压平」—— 有人直接改库 / 导数据写了两层,这里会红
_真 = sqlite3.connect(f"file:{os.path.join(HERE, 'lanxiu.db')}?mode=ro", uri=True)
if "merged_into" in {r[1] for r in _真.execute("PRAGMA table_info(customer)")}:
    _坏 = _真.execute("SELECT a.id, a.merged_into FROM customer a JOIN customer b ON b.id=a.merged_into "
                     "WHERE COALESCE(b.merged_into,'')<>'' LIMIT 3").fetchall()
    _数 = _真.execute("SELECT COUNT(*) FROM customer WHERE COALESCE(merged_into,'')<>''").fetchone()[0]
    ck(f"全库扫:没有一条档案并到一个「自己也已并入别人」的档案上(真库,只读;扫了 {_数} 条合并记录)", not _坏, _坏)
    if not _数:
        # **空集合上什么都成立** —— 别让这一条的 ✅ 被读成「验过了」(数据工厂 10-14 提醒)。
        # 代码对不对那一半由上面副本里造「乙收丙、再并进甲」兜住;这一条只管库的现状
        print("     ℹ️ 真库里还没有任何合并记录 —— 上面这条**现在什么都没验**,等真有人合并之后它才开始起作用")
_真.close()

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 客户软合并:数据不搬、留最早、能撤、只认总部运营(验了 {n} 条){D}")
