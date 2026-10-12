#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运费表 —— **配不出一张会静默免邮的表**。

    python3 backend/freight_check.py

库只读(`mode=ro`),写入那一路在**库副本**上跑。

## 这条检查在守什么

业务 2026-10-12 定了「分区固定价 + 满额免邮」,运营后台可配。
**而「可配」就是风险所在**:一张配坏的运费表不会报错,它只会少收钱 ——
而少收的钱**不可逆**(没收就是没收),且报表上完全正常。

最危险的三种配法,每一种都**不违反任何外键、不抛任何异常**:

    没有兜底区      一个没登记的省份就算不出运费 —— 回落到 0 就是整店静默免邮
    两个兜底区      命中哪个看顺序,而顺序会漂
    一个省登记两次  取到哪个价看顺序,同一个省今天 28 明天 48

所以判据不是「这张表能不能存下来」,是**「存下来之后它会不会静默免邮」**。

## 覆盖面要打印出来,因为它小得会误导人

这张表真正收得到运费的只有 **6.1% 的单**(江浙沪占客户 82% 免邮、满额又免一批)。
> 而**那不是理由把它配错** —— 收错钱的那几单里每一单都是一次客诉。

## 一条明写的边界:历史订单没有回溯

用户 2026-10-12 拍的是「**只管新单,历史不动**」。所以库里 9124 单带着 28 元运费,
其中大部分是江浙沪(按现行规则本该免邮)。**这不是错,是没回溯** ——
判据把这个数**报出来**,不判它红:
> 一个「规则配错了」和一个「历史没回溯」,在「订单运费和现行规则对不上」这件事上
> 长得一模一样 —— 分开它们的只有一句话,所以这句话要印在输出里。
"""
import os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "knowledge")]
import freight as F

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("让 save_freight 只校验这一行、不校验改完之后的整张表",
     "同一个省登记到第二个区 → **存不进去**"),
    # 这一条是**影响面最大**的那个错法:不做省份归一,「上海市」对不上登记的「上海」,
    # 于是 82% 的客户(江浙沪)从免邮变成收 28 元 —— 而它不抛任何异常。
    ("让 找区() 不做省份归一",
     "「上海」和「上海市」算同一个省"),
]


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        bad.append(名)


DB = os.path.join(HERE, "lanxiu.db")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("运费表 · 配不出一张会静默免邮的表")

# ── ① 两张表真的被建出来了(不是运行时建的)──────────────────────────────
print("\n① 表在,而且是从 schema 建的")
有 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name IN ('freight_zone','freight_rule')")}
ck("freight_zone / freight_rule 两张表都在", 有 == {"freight_zone", "freight_rule"},
   f"只有 {sorted(有)}")
种 = open(os.path.join(HERE, "seed.py"), encoding="utf-8").read()
# ⚠️ **这两条判据不许把要找的那串原文抄在这儿。** 第一版照抄了建表和插入语句,
# 于是 `tools/insert_shape_check.py` 在**这个文件的字符串字面量里**命中了
# 「位置参数 INSERT」,报了两处不存在的问题。
# > 这是密钥扫描那条踩过三次的坑的同一个形状:
# > **被扫描的文件里不要写出真实的匹配串** —— 要举例就描述它,别照抄。
# 所以这儿把关键字拼出来,不写成一个完整的字面量。
_建 = "CREATE" + " TABLE "
_插 = "INSERT" + " INTO "
ck("建表写在 seed.py 的 schema 里(运行时建表在 CI 上会缺 —— 本地绿 ≠ 从零建得起来)",
   (_建 + "freight_zone") in 种 and (_建 + "freight_rule") in 种)
ck("初始配置也在 seed.py 里灌(不然从零重建出来是一张空表,而空表会静默免邮)",
   (_插 + "freight_zone") in 种 and (_插 + "freight_rule") in 种)

if 有 != {"freight_zone", "freight_rule"}:
    print(f"\n{R}❌ 表都没有,后面全是空集合上的真{D}")
    sys.exit(1)

# ── ② 库里现在那张表,配得住 ─────────────────────────────────────────────
print("\n② 库里现在那张表")
zs = [dict(区域=r["zone"], 省份=r["provinces"] or "", 运费=float(r["fee"] or 0),
           兜底=bool(r["is_fallback"]), 排序=r["sort"])
      for r in c.execute("SELECT * FROM freight_zone WHERE status='启用' ORDER BY sort, zone")]
门 = c.execute("SELECT free_over FROM freight_rule WHERE id=1").fetchone()
门 = float(门["free_over"]) if 门 else None
ck(f"样本量:区域表 {len(zs)} 行(0 行的话下面全是空集合上的真)", len(zs) >= 2,
   f"只有 {len(zs)} 行")
行, 话 = F.查区域表(zs)
ck(f"整表校验通过({话})", 行, 话)
兜 = [z for z in zs if z["兜底"]]
ck("区域表里恰好有一个兜底区", len(兜) == 1,
   f"有 {len(兜)} 个 —— 没有的话没登记的省份算不出运费,多个的话命中哪个看顺序")
ck("满额免邮门槛是一个非负的数", isinstance(门, float) and 门 >= 0, str(门))
ck("江浙沪那一档免邮(业务 2026-10-12 定的那条)",
   any(z["运费"] == 0 and {"上海", "浙江", "江苏"} <= set(F.省份清单(z["省份"]))
       for z in zs),
   f"没找到一个同时含上海/浙江/江苏且运费为 0 的区:{[(z['区域'], z['运费']) for z in zs]}")

# ── ③ 算不出来的时候**不返回 0** —— 这条是整条检查的要害 ─────────────────
print("\n③ 算不出来的时候不返回 0(回落到免邮 = 不可逆地少收钱)")
坏 = [("区域表是空的", ("浙江省", 500, [], 门)),
      ("没有兜底区", ("广东省", 500, [z for z in zs if not z["兜底"]], 门)),
      ("货品金额不是数", ("浙江省", "两千", zs, 门)),
      ("货品金额是负数", ("浙江省", -1, zs, 门)),
      ("门槛不是数", ("浙江省", 500, zs, "两千"))]
for 名, 入 in 坏:
    r = F.算运费(*入)
    ck(f"{名} → 算不出来的时候不返回 0",
       r["运费"] is None and r["算得出来"] is False and r["要人确认"] is True,
       f"返回了 {r['运费']}")

# ── ④ 省份匹配:不许用子串包含 ───────────────────────────────────────────
print("\n④ 省份匹配")
# ⚠️ 攻击点**自己造**,不靠真实省名碰上:现实里「黑龙江」不包含任何真实省名,
# 所以拿真实区域表验「子串匹配是错的」**什么也验不到**(咬合当场证明过)。
怪表 = [dict(区域="怪区", 省份="龙江", 运费=5.0, 兜底=False),
        dict(区域="兜", 省份="", 运费=28.0, 兜底=True)]
ck("省份是**整名**匹配,不是子串匹配(「黑龙江」不许落进登记了「龙江」的区)",
   F.找区("黑龙江省", 怪表)[0]["区域"] == "兜",
   f"落到了 {F.找区('黑龙江省', 怪表)[0]['区域']}")
ck("而这个形状真的分辨得出来(不然上面那条等于没验)", "龙江" in F.规范省份("黑龙江省"))
ck("「上海」和「上海市」算同一个省",
   F.找区("上海", zs)[0]["区域"] == F.找区("上海市", zs)[0]["区域"])
ck("后缀表按长度从长到短排(按手顺排会让「新疆维吾尔自治区」归成「新疆维吾尔」)",
   list(F.省份后缀) == sorted(F.省份后缀, key=len, reverse=True))
ck("省份为空标成「没省份」,和「落兜底」**不是一回事**",
   F.找区("", zs)[1] == "没省份" and F.找区("广东省", zs)[1] == "兜底")
# 「要人确认」只许在没省份那一种响 —— 否则它在上千个正常单上响,真该响时没人看
响 = [sp for sp in ("上海市", "浙江省", "江苏省", "安徽省", "广东省", "北京市")
     if F.算运费(sp, 500, zs, 门)["要人确认"]]
ck("「要人确认」不在正常省份上响(在上千个正常单上响的标记,等于没有标记)",
   not 响, f"这些省份被标成要人确认:{响}")
ck("没有收货省份时**才**要人确认", F.算运费("", 500, zs, 门)["要人确认"] is True)

# ── ⑤ 真实客户省份跑一遍:每一个都算得出来 ────────────────────────────────
print("\n⑤ 库里真实的客户省份,逐个算得出来")
省们 = [r["province"] for r in c.execute(
    "SELECT province FROM customer WHERE COALESCE(province,'')<>'' GROUP BY province")]
ck(f"样本量:库里有 {len(省们)} 个不同省份", len(省们) >= 3, f"只有 {len(省们)} 个")
算不出 = [p for p in 省们 if not F.算运费(p, 500, zs, 门)["算得出来"]]
ck("每个真实省份都算得出运费(算不出来就是有单会卡住或静默免邮)",
   not 算不出, f"这些算不出来:{算不出[:5]}")
分布 = {}
for p in 省们:
    r = F.算运费(p, 500, zs, 门)
    分布.setdefault(f"{r['区域']} / {r['运费']:.0f} 元", []).append(p)
for k in sorted(分布):
    print(f"    {k}:{len(分布[k])} 个省 —— {'、'.join(分布[k][:4])}"
          + ("…" if len(分布[k]) > 4 else ""))
挂0 = []
for z in zs:
    这区 = [p for p in 省们 if F.找区(p, zs)[0]["区域"] == z["区域"]]
    if not 这区:
        挂0.append(z["区域"])
if 挂0:
    print(f"    {Y}📌 这几个区在这个库里一个省份都没命中:{'、'.join(挂0)} —— "
          f"**它们配得对不对验不到**(空集合上所有性质都成立)。"
          f"不是错,但别把「没报错」读成「配对了」{D}")

# ── ⑥ 覆盖面,以及历史没回溯那笔账 ────────────────────────────────────────
print("\n⑥ 覆盖面 / 历史没回溯")
# ⚠️ **覆盖面要走口径层算,不许在这儿手抄一份江浙沪名单。**
# 第一版就是写了一句
#   `WHERE ... province NOT IN ('上海市','浙江省','江苏省', ...)`
# —— 那是**第二份口径**:运营后台把江浙沪那一档改成含安徽,这句 SQL 不会跟着变,
# 而它算出来的覆盖面照样是一个看着很合理的百分比。
# > 这个项目的规矩:口径只有一处可以漂。而手抄的那一份**漂了不报错**。
# 一遍扫完,同时算「收得到运费的单数」和「和现行规则对不上的单数」。
总 = 收得到 = 对不上 = 0
for r in c.execute("SELECT o.freight, o.goods_amount, u.province FROM ordr o "
                   "LEFT JOIN customer u ON u.id=o.customer_id"):
    总 += 1
    算 = F.算运费(r["province"], r["goods_amount"] or 0, zs, 门)
    if not 算["算得出来"]:
        continue
    if 算["运费"] > 0:
        收得到 += 1
    if abs((r["freight"] or 0) - 算["运费"]) > 0.01:
        对不上 += 1
print(f"    这张表真正收得到运费的:{收得到} / {总} 单 = {100 * 收得到 / max(总, 1):.1f}%"
      f"(**按现行区域表现算的,不是手抄的省份名单**)")
ck("覆盖面算得出来而且不为 0(为 0 的话这张表配了也没人用)", 收得到 > 0)
ck("覆盖面那句话带着「不是理由把它配错」",
   "配错" in F.这张表管得到哪些单())
print(f"    {Y}📌 历史订单里和现行规则对不上的:{对不上} 单 —— "
      f"**这是「没回溯」不是「配错了」**。用户 2026-10-12 拍的是「只管新单,历史不动」:"
      f"老订单当时确实收了那笔运费,改了等于篡改账本。"
      f"所以这个数**不判红** —— 但它要印出来,因为"
      f"「规则配错了」和「历史没回溯」在这个数上长得一模一样{D}")
ck("这个「对不上」的数算得出来(算不出来的话这笔账就没人盯了)",
   isinstance(对不上, int))

# ── ⑦ 后台那条写入:存不进一张会静默免邮的表(库副本上真跑)─────────────────
print("\n⑦ 后台写入(在库副本上真跑,不碰真库)")
tmp = tempfile.mkdtemp(prefix="freight-")
副本 = os.path.join(tmp, "lanxiu.db")
shutil.copy2(DB, 副本)
try:
    import server as S
    _真 = S.DB if hasattr(S, "DB") else None
    S.DB = 副本
    兜底名 = next(z["区域"] for z in zs if z["兜底"])
    r1 = S.save_freight(dict(action="删", zone=兜底名), "检查", "总部运营")
    ck("后台删不掉兜底区(删了之后没登记的省份就算不出运费)",
       not r1.get("ok") and r1.get("code") == "NO_FALLBACK", str(r1)[:90])
    r2 = S.save_freight(dict(action="改", zone="江浙沪", provinces="上海,浙江,江苏",
                             fee="不要钱"), "检查", "总部运营")
    ck("运费填成文字 → 存不进去", not r2.get("ok") and r2.get("code") == "BAD_NUMBER",
       str(r2)[:90])
    r3 = S.save_freight(dict(action="加", zone="撞一个", provinces="浙江", fee=5),
                        "检查", "总部运营")
    ck("同一个省登记到第二个区 → **存不进去**(取到哪个价看顺序)",
       not r3.get("ok") and r3.get("code") == "BAD_TABLE", str(r3)[:110])
    r4 = S.save_freight(dict(action="改", zone="偏远", provinces="新疆,西藏", fee=55),
                        "检查", "顾问")
    ck("顾问改不了运费表(它是全店收钱的口径)",
       not r4.get("ok") and r4.get("code") == "WRONG_ROLE", str(r4)[:90])
    r5 = S.save_freight(dict(action="门槛", free_over="两千"), "检查", "总部运营")
    ck("门槛填成文字 → 存不进去", not r5.get("ok"), str(r5)[:90])
    # 正向:改得动,而且回话里带影响面
    r6 = S.save_freight(dict(action="改", zone="偏远", provinces="新疆,西藏,青海", fee=58),
                        "检查", "总部运营")
    ck("配得对的那一改存得进去", r6.get("ok"), str(r6)[:110])
    ck("存进去之后回话里说了「只对新单生效,历史不动」",
       "历史不动" in (r6.get("reason") or ""), str(r6.get("reason"))[:90])
    # ⚠️ 真正要验的是**它真的落进副本里了**,不是「返回了 ok」
    c2 = sqlite3.connect(副本)
    落 = c2.execute("SELECT fee FROM freight_zone WHERE zone='偏远'").fetchone()
    ck("而且真的写进去了(返回 ok 和真的落库是两件事)", 落 and abs(落[0] - 58) < 0.01,
       f"库里是 {落}")
    c2.close()
finally:
    if _真:
        S.DB = _真
    shutil.rmtree(tmp, ignore_errors=True)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    for x in bad:
        print(f"   · {x}")
    sys.exit(1)
print(f"{G}✅ 运费表配得住,而且配不出一张会静默免邮的表(验了 {n} 条){D}")
