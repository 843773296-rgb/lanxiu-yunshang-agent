#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门店关联键 —— **shop_code 是真相,而它不许和 shop 串打架。**

来路:只读审计第 3 条,用户 2026-10-24 拍「根治」。口径在 `backend/shop_key.py`。

## 它买到了什么(在库副本上实测过)

把「静安旗舰店」在后台改个名(只改 `shop` 表,和真实操作一样):

    按串筛 SH001 的订单   12780 → **0 单**
    按码筛 SH001 的订单   12780 → 12780

**0 单,而且不报错。** 店长看到的是「我店里一单都没有」——
而「这家店今天确实没单」和「关联键对不上了」在页面上长得一模一样。

## 为什么两列并存必须有判据顶着

`shop` 继续装显示串给人看,`shop_code` 只管关联。
**两份数据说同一件事,就会漂** —— 而漂了不报错:

> 一列「还没回填」和一列「回填错了」,在页面上长得一模一样(都只是少几行)。

所以这条判据守「真相只有一个,而且两边对得上」。

## ⚠️ 最要紧的一条:**「空」不许是「不知道」**

这一列不只装门店 —— `staff.shop` 里有 12 个工坊名,`activity.shop` 里有「全渠道」。
它们没有门店编码,所以 `shop_code` 留空。
那么「留空」就有了两个可能的意思,而**它们该触发相反的动作**:

    「不归任何门店」(工坊 / 全渠道)  → 对的,别动它
    「不知道是哪家」(脏数据 / 漏填)    → 要去查

分开它们的办法是 `shop_key.不是门店的` 那张**明写名单**:
留空的行,它的 `shop` 必须落在名单里。于是「空」的意思变成
「不归门店,**而且我们知道它是哪一类不归**」。
冒出一个没登记的值就红 —— 而**一个新开的工坊和一个打错的字,
在「对不上 shop 表」这件事上长得一模一样**,所以判据只说「有这么个值」,
由人去看是该登记还是该改数据。

## 验六件

  ① 11 处都有 `shop_code` 列
  ② 每一行 `shop_code` 都等于口径算出来的那个(漏填 / 填错 / 该空没空,分类报)
  ③ 留空的行,它的 `shop` 在明写名单里(否则「空」= 「不知道」)
  ④ 名单里**没有一项是真门店的串** —— 否则有人能把真门店塞进名单来绕过 ②
  ⑤ 样本量:门店表非空、带键的行数够(空集上这几条全部恒成立)
  ⑥ 判据**自己造**五种形状去调同一个口径函数(真库里没有脏值,
     不自己造的话「不认识」那条分支永远走不到,而没走到和验过了长得一样)
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]

import shop_key as SK

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    # ⚠️ 四条攻击都打在**被守的那个东西**上,没有一条打在判据自己身上。
    # ⚠️ 第一版这里写的是「把一行的 shop_code 改成另一家门店的码」,攻击点落在
    # `tools/add_shop_code.py` 的 UPDATE 行上 —— **那是个空操作**:咬合重放只跑
    # 这个判据,那个脚本压根不会被执行,数据一个字都不会变。
    # (摘要里记过的四种咬合失效之一,它显示成「改坏了却没红」。)
    # 改成攻**口径的那一边**:库里的码是对的,把「串→码」的映射改成「串→名字」,
    # 两边就说不到一块去了。注意自造那几条用的是**字面假门店表**、不走 `门店表()`,
    # 所以它们照旧绿 —— 红的只会是逐行对账那一条。
    ("把「串→码」的映射改成「串→名字」(库里的码是对的,口径变了)",
     "每一行的 shop_code 都和它的 shop 串对得上"),
    # 这一条守的是**覆盖面**:把一张表从明写名单里删掉,判据会少验一张表而**照样全绿** ——
    # 「这张表没问题」和「这张表没人看」在绿勾上长得一模一样。
    ("把 ordr 从「带门店键的」名单里删掉(少验一张 2.6 万行的表,照样全绿)",
     "明写的「带门店键的」和库里真有 shop 列的表,一张不差"),
    # 第五条守**顺序**,它是 2026-10-24 CI 真红过的那一次:
    # 加列排在写口之后,从零重建当场炸,而本地怎么跑都是绿的
    # (已经存在的库上那一列永远都在)。
    ("把加列那一步往后挪一步(从零重建时写口跑在加列之前就炸,本地看不见)",
     "加列紧跟在 seed.py 之后"),
    # 第六条:流水线**中途**才建的表,列必须写在它自己的建表语句里。
    # 2026-10-24 CI 为这件事红了第二次 —— 第一次修的是「加列排在写口之后」,
    # 而 fitting 这张表是第 4 步才建的,加列在第 2 步**压根跳过了它**。
    ("把 fitting 建表语句里的 shop_code 删掉(靠流水线那一步 ALTER 补,就有缺口)",
     "流水线中途才建的表,建表语句里就带着 shop_code"),
    # 第七条守**第二阶段的进度**:棘轮,只许少不许多。
    # 「改了几处」和「改完了」在绿勾上长得一模一样,所以把剩下的登记成欠债。
    ("在 factory_inbox 里加回一处按门店串筛的查询(欠债涨了)",
     "生产代码里按门店串筛的只许少不许多"),
    # 第二条打的是那张明写名单 —— 名单一空,「留空」就退回「不知道」,
    # 而**真库全绿**:工坊那 21 行照样是留空的,只是没人能说清它们为什么空。
    # ⚠️ 删的是**苏州织造坊**,不是上海工坊 —— 后者在下面「自造五种形状」里用着,
    # 删它会让自造那条先红,于是「红的是点名那一条」就不成立了。
    ("把苏州织造坊从「不是门店的」名单里删掉(留空的行就没了来路)",
     "留空的那些行,它的 shop 都在明写名单里"),
    # 第三条打的是回填那一步的来路:删掉它,**本地库上完全隐形**
    # (列和数据早就在了),只有从零重建才会整列全空。
    ("把回填那一步从 rebuild.sh 的步骤清单里删掉(本地库上完全隐形)",
     "rebuild.sh 的步骤清单里真的有人跑回填"),
    # 第四条的**另一半**:重建那条路径有回填,每日那条没有 ——
    # 而后者的缺口当天隐形、第二天才红(2026-10-25 真红过)。
    ("把回填那一步从 daily_shift.sh 里删掉(当天全绿,第二天早上才红;"
     "⚠️ 那个文件的注释里**不许照抄**这条命令 —— 照抄过一次,"
     "删掉真正那一行之后判据照样绿)",
     "每日平移那条路径也跑回填"),
    ("派任务的写口不写 shop_code(10-25 用户在聊天站派的回电任务就是这么漏的)",
     "backend/ 里运行时的写口:写 shop 的地方都同时写 shop_code"),
]

坏, n = [], 0


def ck(名, ok, 说明=""):
    global n
    n += 1
    print(f"  {G + '✅' + D if ok else Rd + '❌' + D} {名}" + ("" if ok else f"  —— {说明}"))
    if not ok:
        坏.append(名)


print(f"\n\033[1m▸ 门店关联键 · shop_code 是真相,不许和 shop 串打架\033[0m")
print("  " + "=" * 80)

# ── ⑥ 先跑自造的那五种形状 ──────────────────────────────────────────────
# 放最前面:它不碰真库,而且它要是挂了,下面几条用的口径就是坏的。
假门店 = {"SH001 甲店": "SH001", "SH002 乙店": "SH002"}
样 = [
    ("SH001 甲店", "门店", "SH001"),
    ("上海工坊", "工坊", None),
    ("全渠道", "范围", None),
    ("", "空", None),
    (None, "空", None),
    ("SH001 甲店(旧名)", "不认识", None),   # ← 改名之后留在数据里的老串就长这样
]
对 = [SK.认得出(v, 假门店) for v, _, _ in 样]
ck("自造五种形状(门店 / 工坊 / 范围 / 空 / 不认识)都分得开",
   对 == [(类, code) for _, 类, code in 样],
   f"算出来 {对},该是 {[(c2, c3) for _, c2, c3 in 样]}")
ck("「不认识」单独一类,**不混进「不是门店」** "
   "(一个新开的工坊和一个打错的字,在对不上 shop 表这件事上长得一样)",
   SK.认得出("没见过的坊", 假门店)[0] == "不认识"
   and SK.认得出("上海工坊", 假门店)[0] == "工坊",
   "两者归成一类的话,脏数据会被当成合法的留空")
# ── 自造四种状态,直接拿 `门店条件()` 生成的 WHERE 去查 ────────────────────
# 内存库,不碰真库。四种状态里有**一种是已知破口**,连它一起断言 ——
# 不写出来的话,下一个人会以为四种都稳。
_mm = sqlite3.connect(":memory:")
_mm.executescript("CREATE TABLE shop(code TEXT, name TEXT);"
                  "CREATE TABLE t(shop TEXT, shop_code TEXT);")
# 具名列 —— `tools/insert_shape_check.py` 的棘轮逮过这两句:
# **列数恰好相等而顺序错了是不报错的**,值会整体挪一格。
_mm.execute("INSERT INTO shop(code,name) VALUES('SH001','甲店')")
_mm.execute("INSERT INTO t(shop,shop_code) VALUES('SH001 甲店','SH001')")


def _查():
    串 = next((k for k, v in SK.门店表(_mm).items() if v == "SH001"), None)
    片, 参 = SK.门店条件(_mm, 串)
    return _mm.execute(f"SELECT COUNT(*) FROM t WHERE {片}", 参).fetchone()[0] if 片 else -1


_态 = {}
_态["①回填过·没改名"] = _查()
_mm.execute("UPDATE shop SET name='乙店'")
_态["②回填过·改过名"] = _查()
_mm.execute("UPDATE t SET shop_code=NULL")
_态["④没回填·改过名"] = _查()
_mm.execute("UPDATE shop SET name='甲店'")
_态["③没回填·没改名"] = _查()
_mm.close()
ck(f"门店条件:回填过的改名也命中、没回填的按串兜住({_态})",
   _态["①回填过·没改名"] == 1 and _态["②回填过·改过名"] == 1 and _态["③没回填·没改名"] == 1,
   f"{_态} —— ①②③ 都该是 1。② 是这一笔买的东西(改名后按串筛会变 0);"
   f"③ 是 2026-10-24 CI 红的那一条:`--建列` 只加列不填值,"
   f"回填排在流水线最后,而中间就有查询在按码筛 —— "
   f"**「列还没回填」和「这家店真的没人」在查询结果上长得一模一样**")
ck(f"而「既没回填又改过名」确实查不到,这是**已知破口**,不是意外({_态['④没回填·改过名']} 行)",
   _态["④没回填·改过名"] == 0,
   f"④ 居然是 {_态['④没回填·改过名']} —— 那说明兜底比预期宽,"
   f"**而那更糟**:它会让「回填漏了」这件事也查得到,于是永远没人去回填")

ck("该填的码:只有门店给码,其余一律留空",
   [SK.该填的码(v, 假门店) for v, _, _ in 样] == [c for _, _, c in 样],
   f"{[SK.该填的码(v, 假门店) for v, _, _ in 样]}")

# ── ④ 名单里不许混进真门店 ──────────────────────────────────────────────
if not os.path.exists(SK.DB):
    print(f"  {Y}⏭{D} 库不在,跳过库上那几条 —— **跳过不是通过**")
else:
    c = sqlite3.connect(f"file:{SK.DB}?mode=ro", uri=True)
    门店 = SK.门店表(c)
    ck(f"门店表里有数据可用({len(门店)} 家)",
       len(门店) >= 1,
       "shop 表是空的 —— **这不是「没什么要验的」,是没有口径可用**,"
       "空口径下每一行都会被判成「不认识」")
    # 具名常量和名单是两份东西,**而对不上的时候两边都不报错** ——
    # SQL 里按串比「全部渠道」会稳定查出 0 行活动,看起来就像「这家店本期没投放」
    ck("「全渠道」这个具名常量登记在「不是门店的」名单里,归「范围」一类",
       SK.不是门店的.get(getattr(SK, "全渠道", None)) == "范围",
       f"`shop_key.全渠道` 现在是「{getattr(SK, '全渠道', '(没有这个名字)')}」,"
       f"而名单里给它的分类是「{SK.不是门店的.get(getattr(SK, '全渠道', None))}」 —— "
       f"两份说法对不上。api.py 查活动用的是这个常量,**对不上就稳定查出 0 条,不报错**")

    混 = sorted(set(SK.不是门店的) & set(门店))
    混2 = sorted(k for k in SK.不是门店的 if k in set(门店.values()))
    ck("「不是门店的」名单里没有一项是真门店(串或码)",
       not 混 and not 混2,
       f"{混 + 混2} 既在名单里又是真门店 —— **那就等于给它开了个后门**:"
       f"它的行可以永远留空,而上面那条「每行都对得上」看不见")

    # ── 覆盖面:明写名单和库里真有 shop 列的表,两头都要对上 ───────────
    # ⚠️ 这一条是**反向**的。上面那些都在问「名单里这几处对不对」,
    # 而**名单自己漏一张表,它们一条都不会红** —— 判据只是少验了一张表,
    # 而「这张表没问题」和「这张表没人看」在绿勾上长得一模一样。
    # (这就是 `table_origin_check` 今天刚补的那个不对称,换了个地方又出现一次。)
    库里带shop的 = set()
    for (表,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name NOT LIKE 'sqlite_%'"):
        if "shop" in [r[1] for r in c.execute(f"PRAGMA table_info({表})")]:
            库里带shop的.add(表)
    明写的 = {t for t, _ in SK.带门店键的}
    漏了 = sorted(库里带shop的 - 明写的)
    多了 = sorted(明写的 - 库里带shop的)
    ck("明写的「带门店键的」和库里真有 shop 列的表,一张不差",
       not 漏了 and not 多了,
       (f"库里有 shop 列而名单里没有:{漏了}(**这几张一行都没人验过**)" if 漏了 else "")
       + ("；" if 漏了 and 多了 else "")
       + (f"名单里有而库里没这一列:{多了}(表改名了?)" if 多了 else "")
       + "。名单在 `backend/shop_key.py` 的 `带门店键的`。"
         "⚠️ 新增一张带门店的表时**要来这儿加一行** —— "
         "不加的话这条判据只是安静地少验一张表。")

    # ── ① 列齐不齐 ─────────────────────────────────────────────────────
    缺列 = [t for t, _ in SK.带门店键的 if not SK.有列(c, t)]
    ck(f"带门店键的 {len(SK.带门店键的)} 处都有 shop_code 列",
       not 缺列,
       f"这几张缺列:{缺列} —— 缺一列**不报错,只会让按它筛的查询返回零行**。"
       f"修法:`python3 tools/add_shop_code.py --做`"
       f"(要先拿 `./tools/gate_lock.sh` 的锁,这个库是两个检出共享的)")

    if not 缺列:
        # ── ②③ 逐行对账,**失败分类报** ────────────────────────────────
        漏填, 填错, 该空没空, 空而没来路, 不认识 = [], [], [], [], []
        总行 = 0
        for 表, 列 in SK.带门店键的:
            for rid, 串, 码 in c.execute(f"SELECT rowid, {列}, shop_code FROM {表}"):
                总行 += 1
                类, 该 = SK.认得出(串, 门店)
                if 类 == "不认识":
                    不认识.append((表, rid, 串))
                    continue
                if 类 == "门店":
                    if 码 is None:
                        漏填.append((表, rid, 串))
                    elif 码 != 该:
                        填错.append((表, rid, 串, 码, 该))
                else:
                    if 码 is not None:
                        该空没空.append((表, rid, 串, 码))
                    elif 类 != "空" and 串 not in SK.不是门店的:
                        空而没来路.append((表, rid, 串))
        # **样本量** —— 空集上下面几条全部恒成立。
        # 下限只防「一行都没扫到」,不是说该有多少行(铺数据一多它就该涨)。
        ck(f"带门店键的行数够得上验(扫了 {总行} 行)",
           总行 >= 1000,
           f"只扫到 {总行} 行 —— **这不是通过,是没扫到东西**(下限 1000 只防空扫)")
        坏行 = 漏填 + 填错 + 该空没空
        ck(f"每一行的 shop_code 都和它的 shop 串对得上(验了 {总行} 行)",
           not 坏行,
           f"漏填 {len(漏填)} 行 · 填错 {len(填错)} 行 · 该留空却填了 {len(该空没空)} 行。"
           f"例:{(漏填 + 填错 + 该空没空)[:3]}。"
           f"**两份数据说同一件事就会漂,而漂了不报错**。"
           f"修法:`python3 tools/add_shop_code.py --做`")
        ck(f"留空的那些行,它的 shop 都在明写名单里"
           f"(工坊 / 范围 共 {len(SK.不是门店的)} 项)",
           not 不认识 and not 空而没来路,
           f"这 {len(不认识) + len(空而没来路)} 行的值既不是门店、也没登记:"
           f"{(不认识 + 空而没来路)[:4]} —— 没有名单的话「留空」就退回「不知道」,"
           f"而**「不归任何门店」和「不知道是哪家」该触发相反的动作**。"
           f"要么去 `backend/shop_key.py` 登记一行(说清它是工坊还是范围),"
           f"要么那是脏数据、该改。")
    c.close()

# ── 回填那一步真的挂在流水线上 ──────────────────────────────────────────
# ⚠️ 这条在本地库上**完全隐形**:列和数据早就在了,一路绿;
# 只有从零重建才会整列全空。所以要有一条**从文本上**看的判据。
# (同 `backend/query_index_check.py` 里那一条,同一个形状。)
import re as _re2

sh = os.path.join(ROOT, "tools", "rebuild.sh")
文 = open(sh, encoding="utf-8").read() if os.path.exists(sh) else ""
# ⚠️ 查的是**那一次调用**(带 `--做` 的回填),不是「这个脚本名出现过没有」。
# 2026-10-24 这条栽过一次:原来查的是脚本名,而后来加了两个 `--建列` 步骤
# **让那个名字永远都在** —— 于是删掉回填那一步,它照样绿。
# > 一条「查的是含义」和一条「恰好匹配上了」,在它变绿这件事上长得一模一样。
ck("rebuild.sh 的步骤清单里真的有人跑回填",
   "add_shop_code.py --做" in 文,
   "rebuild.sh 里没有 `tools/add_shop_code.py --做` —— **登记了但没人去跑回填**"
   "(只有 `--建列` 不算:它只加列、不填值)。"
   "这个缺口在本地完全隐形(列和数据早就在了),只有 CI 从零重建才会"
   "整列全空,而那时红的是别的检查。")

# ── **另一条路径**:每日平移也造带门店键的新行 ─────────────────────────
# ⚠️ 2026-10-25 门禁真红过一次,而**没有任何人改过代码**。
# 上面那条和下面那几条顺序断言,守的全是 `rebuild.sh` 里的位置 ——
# 而「回填排在最后」这句话**只在那条流水线里有意义**:
# 每日这条路径(`tools/daily_shift.sh`:平移 + `daily_fresh` 造新单 / 跟进 /
# 预约 / 评价)根本没有「最后」,它一步回填都不跑。
# 于是:重建完当天全绿 → 夜里平移 → 第二天红在「每一行的 shop_code 都和它的 shop 串对得上」,
# 而那时看起来像「数据漂了」,**不像「流程缺一步」** —— 当天两个会话都先去找谁动了数据。
# > **一个「重建得出来的库」,和一个「每天都还对得上的库」,是两件事。**
ds = os.path.join(ROOT, "tools", "daily_shift.sh")
文2 = open(ds, encoding="utf-8").read() if os.path.exists(ds) else ""
ck("每日平移那条路径也跑回填(它造新行,而新行没有门店码)",
   "add_shop_code.py --做" in 文2,
   "`tools/daily_shift.sh` 里没有 `tools/add_shop_code.py --做` —— "
   "它跑 `daily_fresh` 造新单 / 跟进 / 预约 / 评价,**那些行带着门店串而没有码**。"
   "这个缺口**当天完全隐形**(刚重建的库全有码),第二天早上才红。")

# ── **顺序**:加列要在建表之后、所有写口之前;回填要在所有造数之后 ─────
#
# ⚠️ 2026-10-24 CI 为这件事红了一次,而**本地怎么跑都是绿的**:
# `opportunity_store` 往 schedule 写 shop_code(第 15 步),而加列原来挂在第 41 步,
# 从零重建时写口跑在加列之前 ——
# `OperationalError: table schedule has no column named shop_code`。
#
# > 在一个已经存在的库上,那一列**永远都在**。只有「从零」才会让写口跑在加列之前。
#
# 所以这条判据不只问「有没有人跑」,还问「**跑在哪一步**」:
# 加列必须**紧跟在建表之后**(seed.py 建 SCHEMA 那批、ensure_tables 建另几张),
# 回填必须在**最后那一批**。挪动步骤的人会被它拦住。
_m = _re2.search(r"for STEP in (.+?); do", 文, _re2.S) if 文 else None
ck("取得到 rebuild.sh 的步骤清单(取不到就没法验顺序)",
   bool(_m), "rebuild.sh 的 `for STEP in …; do` 写法变了 —— **这条判据要跟着改**,别当成通过")
if _m:
    步 = [x.split()[0] for x in _re2.findall(r'"([^"]+)"', _m.group(1))]
    全 = _re2.findall(r'"([^"]+)"', _m.group(1))
    def 第几(名, 带=""):
        return [i for i, (p, q) in enumerate(zip(步, 全))
                if p == 名 and (带 in q if 带 else True)]
    建列 = 第几("tools/add_shop_code.py", "--建列")
    回填 = [i for i in 第几("tools/add_shop_code.py") if i not in 建列]
    seed = 第几("backend/seed.py")
    ens = 第几("tools/ensure_tables.py")
    ck(f"加列紧跟在 seed.py 之后(现在:seed 第 {[i+1 for i in seed]} 步、"
       f"加列第 {[i+1 for i in 建列]} 步)",
       bool(seed) and bool(建列) and min(建列) == seed[0] + 1,
       "加列那一步不是紧跟在 seed.py 后面 —— **中间插进来的任何步骤,"
       "只要它调了带 shop_code 的写口,从零重建就当场炸**,而本地看不见")
    ck(f"加列也紧跟在 ensure_tables.py 之后(roster / store_report_doc 是它建的)",
       bool(ens) and any(i == ens[0] + 1 for i in 建列),
       "ensure_tables 建的那几张表,后面没有紧跟一次加列 —— "
       "它们的列会一直缺到最后那次回填,中间谁写就谁炸")
    ck(f"回填排在最后那一批(现在第 {[i+1 for i in 回填]} 步 / 共 {len(步)} 步)",
       bool(回填) and max(回填) >= len(步) - 3,
       "回填排得太早 —— **它后面那些造数步骤写进去的行,"
       "门店码会一直是空的**,而缺一列不报错、只是按它筛返回零行")

# ── 流水线**中途**才建的表,列必须写在它自己的建表语句里 ─────────────────
#
# ⚠️ 2026-10-24 CI 为这件事红了**第二次**。第一次修的是「加列排在写口之后」,
# 把加列挪到第 2 步(seed 之后)和第 19 步(ensure_tables 之后)。
# 但 `fitting` 这张表是**第 4 步**才建的(run_journey 里执行 seed_fitting.DDL)——
# 第 2 步那轮加列时它还不存在,**被跳过了**;紧接着同一步里的写口就要写这一列,
# 当场抛,而 run_journey 把单条旅程的异常吞掉继续,**那一步的退出码还是 0**。
# 断在半路的那几条旅程没走到「把时间挪回过去」那一段,于是留下一批
# 落在「世界的未来」的记录,最后红在**平移**那一步 —— 离真因隔着 24 步。
#
# > 把列交给「流水线顺序」去保证,就永远有一个「表在这一步之后才建」的缺口。
# > **列应该是表定义的一部分。**
#
# 所以规则是:**不在 seed.py 的 SCHEMA 里(= 中途才建)的表,
# 它自己的建表语句里就得有 shop_code**。SCHEMA 里那几张不要求
# (它们在第 1 步就存在,第 2 步加列够得上;而给 SCHEMA 加列会打破
#  三处位置参数 INSERT 的列数 —— 那是另一笔账,登记在 insert_shape_check 的欠债表里)。
import re as _re3


def _建表列清单(src, 表):
    """从源码里取 `CREATE TABLE … 表(…)` 的列清单。**手工配括号**,不用正则 ——
    `references staff(no)` 这种嵌套括号会把非贪婪正则截断在第一个 `)` 上。"""
    出 = []
    for m in _re3.finditer(rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?{表}[\"`\]]?\s*\(",
                           src, _re3.I):
        i, 深 = m.end() - 1, 0
        for j in range(i, len(src)):
            if src[j] == "(": 深 += 1
            elif src[j] == ")":
                深 -= 1
                if 深 == 0:
                    出.append(src[i + 1:j])
                    break
    return 出


_seed2 = os.path.join(ROOT, "backend", "seed.py")
_m3 = _re3.search(r"SCHEMA\s*=\s*(?:r?\"\"\"|r?\'\'\')(.*?)(?:\"\"\"|\'\'\')",
                  open(_seed2, encoding="utf-8").read(), _re3.S)
ck("取得到 seed.py 的 SCHEMA(取不到就分不清哪张表是中途建的)",
   bool(_m3), "seed.py 里 SCHEMA 的写法变了 —— **这条判据要跟着改**,别当成通过")
if _m3:
    _mem2 = sqlite3.connect(":memory:")
    _mem2.executescript(_m3.group(1))
    _在SCHEMA = {r[0] for r in _mem2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _mem2.close()
    中途建的 = [t for t, _ in SK.带门店键的 if t not in _在SCHEMA]
    ck(f"认得出哪几张表是流水线中途才建的(现在 {中途建的})",
       bool(中途建的),
       "一张都没认出来 —— 要么 11 张全在 SCHEMA 里了(那挺好,但这条判据就该改),"
       "要么 SCHEMA 解析坏了。**这不是通过**")
    漏的 = []
    for t in 中途建的:
        找到, 带了 = False, False
        for d, ds, fs in os.walk(ROOT):
            ds[:] = [x for x in ds if x not in {".git", "__pycache__", ".venv", "node_modules"}
                     and not x.startswith(".")]
            for f in fs:
                if not f.endswith(".py"):
                    continue
                try:
                    src = open(os.path.join(d, f), encoding="utf-8").read()
                except Exception:
                    continue
                for 列 in _建表列清单(src, t):
                    找到 = True
                    if "shop_code" in 列:
                        带了 = True
        漏的.append((t, 找到, 带了))
    坏表 = [t for t, 找, 带 in 漏的 if not 找 or not 带]
    ck(f"流水线中途才建的表,建表语句里就带着 shop_code(验了 {len(中途建的)} 张)",
       not 坏表,
       f"这几张不行:{[(t, '找不到建表语句' if not 找 else '建表语句里没有 shop_code') for t, 找, 带 in 漏的 if not 找 or not 带]}"
       f" —— **加列那一步排在它们建表之前,会把它们整张跳过**,"
       f"而紧接着的写口要写这一列就当场抛;外层吞掉异常之后那一步退出码还是 0,"
       f"真因离红的地方隔着二十几步。把 `shop_code TEXT` 写进它自己的建表语句。")

# ── 第二阶段的棘轮:生产代码里「按门店串筛」只许少不许多 ─────────────────
#
# 第一阶段买的是保险(码建好了、回填了、新写的行带着码),**而读还没切** ——
# 查询仍然按显示串筛,那个保险就还没换上。
#
# > **「改了 8 处」和「改完了」在绿勾上长得一模一样。**
#
# ⚠️ **用 AST 取字符串常量,不按行扫正则。** 这条判据的第一版按行扫,
# 当场出了两类错,而它们方向相反:
#   · **假阳**:Python 的 `or shop == "全部门店"` 和 `and shop in r["试点"]`
#     被当成了 SQL 的 `OR shop =` / `AND shop IN`(report_doc / report_template 各一处);
#   · **假阴**:改成「必须在引号里」之后,**跨行三引号**里的真 SQL 被判成不在字符串里
#     (server.py 看板那句、api.py 报告模板那句)。
#     「这一行不在字符串里」和「这一行在一个跨行字符串里」,在单行引号计数上长得一样。
# 两类都修掉之后,数字从「25 处」变成「10 处」—— **原来那个数一多半是我的正则造的**。
# (`tools/insert_shape_check.py` 早就是 AST 取串 + 剥两层注释,照它来的。)
#
# ⚠️ 豁免**明写在这儿、带理由**,而且也上棘轮(只许少不许多)——
# 不然「加一条豁免」就是绕过这条判据的后门。
# 另配**反向检查**:豁免指的那段代码已经不在了,也要红(豁免不许囤积)。
import ast as _ast2
import warnings as _warn

_去SQL注释 = lambda t: _re2.sub(r"/\*.*?\*/", " ",
                              _re2.sub(r"--[^\n]*", " ", t), flags=_re2.S)
按串筛式 = _re2.compile(r"(?:WHERE|AND|OR)\s+(?:\w+\.)?shop\s*(?:=|IN|LIKE|<>|!=)", _re2.I)
生产文件 = ["backend/server.py", "backend/api.py", "backend/report_doc.py",
          "backend/booking.py", "backend/factory_inbox.py", "backend/report_template.py",
          "backend/tasks.py", "backend/roster.py"]
# 片段 → 为什么这一处**本来就该按串**。片段是能在那个文件的字符串常量里找到的一小段。
豁免 = {
    ("backend/server.py", "GROUP BY shop, shop_code"):
        "看板按门店显示名分组 —— 页面要拿它当标题;`shop!=''` 是「非空」判断,不是门店筛",
    ("backend/server.py", "SELECT DISTINCT shop v FROM customer"):
        "筛选下拉的选项,要的就是显示名",
}
欠债上限, 豁免上限 = 0, 2      # **2026-10-24 第三批(api.py 那 8 处)做完,清零。只许降不许涨。**
# ⚠️ 清零之后这条判据的性质变了:原来它是进度条(只许少),现在是**闸** ——
# 生产代码里再出现一处按门店串筛就红。要真有一处本来就该按串比(工坊 / 投放范围),
# 走 `门店条件()`(它认不出就退回按串),**别来加豁免** —— 豁免上限也是只许降不许涨的。

def _串们(文件):
    try:
        with _warn.catch_warnings():
            _warn.simplefilter("ignore", SyntaxWarning)
            树 = _ast2.parse(open(os.path.join(ROOT, 文件), encoding="utf-8").read())
    except Exception:
        return None
    return [_去SQL注释(n.value) for n in _ast2.walk(树)
            if isinstance(n, _ast2.Constant) and isinstance(n.value, str)]

欠, 读不了, 用过的豁免 = {}, [], set()
for _f in 生产文件:
    串 = _串们(_f)
    if 串 is None:
        读不了.append(_f)
        continue
    for t in 串:
        for m in 按串筛式.finditer(t):
            命中豁免 = [k for k in 豁免 if k[0] == _f and k[1] in t]
            if 命中豁免:
                用过的豁免.add(命中豁免[0])
            else:
                欠[_f] = 欠.get(_f, 0) + 1
# 读不了要单独报:**被吞掉的解析失败和「这个文件干净」长得一模一样**
ck("生产文件都解析得开(解析不开就不是「干净」)",
   not 读不了, f"这几个解析失败:{读不了} —— **没查过,不是没问题**")
现 = sum(欠.values())
ck(f"生产代码里按门店串筛的只许少不许多(现在 {现} 处,上限 {欠债上限})",
   现 <= 欠债上限,
   f"涨到 {现} 处了 —— **新写的查询不许再按门店串筛**,走 `shop_key.门店条件()`"
   f"(它认不出的值会退回按串比,工坊 / 全渠道照样查得到)。分布:{欠}")
ck(f"豁免也只许少不许多(现在 {len(豁免)} 条,上限 {豁免上限})",
   len(豁免) <= 豁免上限,
   f"豁免涨到 {len(豁免)} 条 —— **加一条豁免就是绕过这条判据的后门**,"
   f"要加得说清为什么那一处本来就该按串")
# **反向**:豁免指的那段已经不在了 → 红。囤积的豁免和真豁免长得一模一样。
过期豁免 = [k for k in 豁免 if k not in 用过的豁免]
ck("豁免指的那段代码都还在(改好了就把豁免删掉)",
   not 过期豁免,
   f"这几条豁免指不到任何代码了:{过期豁免} —— 那一处要么改过了、要么挪走了,"
   f"**把豁免删掉**。囤着的豁免和真豁免长得一模一样")
if 现:
    print(f"      ℹ️ 还欠 {现} 处(第二阶段没做完):{欠}")
    print(f"         ⚠️ 这不是豁免 —— 它说的是「这几处还没改」,不是「这几处不用改」。")
    print(f"         ⚠️ 降下来之后把 `欠债上限` 一起改小,不然空间会被下一个人悄悄用掉。")

# ── ⑨ api.py 那 8 处:**条件算出来了,还得真拼进执行的 SQL** ─────────────
#
# 上面那条棘轮守的是「别按门店串筛」,而它**看不见「压根没筛」**:
# 假如有人把 `+ (f" AND {_片}" if _片 else "")` 写丢了,
#   · 棘轮绿 —— SQL 里确实没有 `shop=?`
#   · 语法绿、接口照样返回数据 —— 只是**不分门店了**,店长看到的是全公司
#
# > **「算了门店条件」和「把门店条件用上了」在棘轮上长得一模一样。**
#
# 所以这一条**真调**那几个函数,抓它们实际执行过的 SQL,看里头有没有 `shop_code`。
# 身份是**自造**的(一个挂着真门店串的店长 dict)—— 不靠库里碰巧有哪个店长;
# 门店串必须是真的(认不出就会退回按串比),所以从 shop 表取,上面那条
# 「门店表里有数据可用」顶着这个前提。
# ⚠️ 不断言「查出几行」:那会变成在量库里碰巧有什么数据。只断言**条件进没进 SQL**,
# 这在空库上一样成立。
if not os.path.exists(SK.DB):
    print(f"  {Y}⏭{D} 库不在,跳过 api.py 那 8 处的真调 —— **跳过不是通过**")
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import api as _api, datetime as _dt9, sqlite3 as _sq9
    from seed import TODAY as _今9          # 业务今天。`api.TODAY` 只在函数里导,顶层没有
    _c9 = _sq9.connect(f"file:{SK.DB}?mode=ro", uri=True); _c9.row_factory = _sq9.Row
    _店9 = [f"{r['code']} {r['name']}" for r in _c9.execute("SELECT code, name FROM shop ORDER BY code")]
    _有表9 = {r[0] for r in _c9.execute(
        "SELECT name FROM sqlite_master WHERE name IN ('store_report_doc','report_action')")}
    _c9.close()
    if not _店9:
        ck("api.py 真调:取得到一个真门店串", False, "shop 表空 —— 没有口径可用,下面那几条验不了")
    else:
        _串9 = _店9[0]
        _我9 = {"no": "ZZ0001", "name": "(自造店长)", "role": "店长", "shop": _串9}
        # 抓所有执行过的 SQL。
        # ⚠️ **`sqlite3.Connection` 是不可变类型,它的 `execute` patch 不上**
        # (`TypeError: cannot set 'execute' attribute of immutable type`)。
        # 所以从 `connect` 这一层挂官方的 `set_trace_callback` —— api.py 自己开的那些
        # 连接也走这个函数,抓得全(它顶部 `import sqlite3`,和这里是同一个模块对象)。
        _原9 = _sq9.connect
        _捕9 = []
        def _探9(*a, **k):
            con = _原9(*a, **k)
            con.set_trace_callback(_捕9.append)
            return con

        def 真调(名, 指纹, f, 前提=True, 为什么=""):
            """调一次,断言**它自己那条** SQL 带上了 shop_code。

            ⚠️ **指纹是必需的,不能只问「这次调用里有没有谁按码筛」。**
            第一版就是那么写的,咬合当场报「改坏了却没红」:`factory_chase` 里还调了
            `factory_inbox.该催清单()`,**那边早就走 `门店条件()`**,它那条 SQL 带着
            shop_code —— 于是「有任一条带码」照旧成立,而被攻击的那条已经不筛门店了。
            > **「这个函数自己筛了」和「这次调用里有别人筛了」,在一次真调的输出上
            > 长得一模一样。** 这是咬合失效的第五型(攻击被别的条件顺手挡住)。
            所以指纹落在**表名 / 特征子句**上(结构,不会漂),只看它命中的那几条。
            ⚠️ 指纹一条都没命中也要红 —— 不然「没抓到那条 SQL」会伪装成「验过了」。
            ⚠️ **`set_trace_callback` 给的是参数已经展开的语句**(`kind='周'`,不是 `kind=?`),
            所以指纹里**不要写 `?`** —— 第一版的 ⑤ 指纹写成 `WHERE kind=?`,一条都没命中,
            而那条「命中 0 条也要红」的断言当场把它逮住了(不然它会显示成绿的)。"""
            if not 前提:
                print(f"  {Y}⏭{D} {名} —— 前提不成立({为什么}),**跳过不是通过**")
                return
            del _捕9[:]
            _sq9.connect = _探9
            try:
                f()
            except Exception as e:
                ck(f"api.py 真调:{名}", False, f"{type(e).__name__}: {e} —— **跑都跑不起来**")
                return
            finally:
                _sq9.connect = _原9
            规整 = [" ".join(q.split()) for q in _捕9]
            目标 = [q for q in 规整 if 指纹 in q]
            if not 目标:
                ck(f"api.py 真调:{名} —— 抓到了它那条 SQL", False,
                   f"指纹「{指纹}」在这一次执行的 {len(规整)} 条 SQL 里一条都没命中 —— "
                   f"**那就是什么都没验**(函数可能提前返回了,或者那条语句改了写法)")
                return
            漏 = [q for q in 目标 if "shop_code" not in q]
            ck(f"api.py 真调:{名} —— 门店条件进了执行的 SQL",
               not 漏,
               f"它那条 SQL(指纹「{指纹}」,命中 {len(目标)} 条)里有 {len(漏)} 条**不带 shop_code**:"
               f"{(漏 or [''])[0][:160]}… —— 条件算出来了却没拼进去。"
               f"**「算了」和「用上了」在棘轮上长得一模一样**:棘轮只看得见「按串筛」,"
               f"看不见「压根不筛」,而不筛的后果是一个店长看到全公司")

        真调("① lifecycle_entered(本店)", "FROM customer WHERE last_interact IS NOT NULL",
             lambda: _api.lifecycle_entered("休眠", month=_今9[:7], shop=_串9))
        with _api.as_user(_我9):
            真调("② activity_roi(店长)", "FROM activity WHERE",
                 lambda: _api.activity_roi())
            真调("④ factory_chase(店长)", "FROM factory_msg f LEFT JOIN ordr o",
                 lambda: _api.factory_chase())
            真调("⑦ deal_credit(店长)", "SELECT no FROM staff WHERE",
                 lambda: _api.deal_credit())
            真调("⑧ on_shift(店长)", "FROM staff WHERE role='顾问' AND status='启用'",
                 lambda: _api.on_shift(days=1))
        真调("③ search_fit_customers(店长)", "FROM customer c WHERE",
             lambda: _api.search_fit_customers("张", _我9))
        真调("⑤ _上期行动(本店)", "FROM store_report_doc WHERE kind=",
             lambda: _api._上期行动("周", _dt9.date.fromisoformat(_今9) - _dt9.timedelta(days=7),
                                  _串9, {}, {}, _今9),
             前提=len(_有表9) == 2, 为什么="store_report_doc / report_action 还没建,它会在执行那条 SQL 之前就返回")

        # ⑥ `_订单范围` **不执行 SQL**,只把片段交给调用方 —— 探针抓不到,直接看片段
        _片6, _参6, _话6, _no6 = _api._订单范围(_我9)
        ck("api.py 真调:⑥ _订单范围(店长)给出的片段按门店码",
           "shop_code" in _片6 and len(_参6) >= 1,
           f"它返回的片段是「{_片6}」参数 {_参6} —— 这个函数只给片段不执行,"
           f"所以上面那个探针抓不到它,得直接看片段")

# ── ⑩ 运行时写口:**写了 shop 串就得同时写 shop_code** ─────────────────────
#
# 回填只在重建和每日平移里跑,**白天用户在聊天站里派的任务没人补** ——
# 10-25 实测:派了一条回电任务,shop_code 空着,第二天店维度的查询就查不到它(按码筛不报错,只是少一行)。
# 判据落结构:扫 backend/ 生产文件里所有 INSERT 的列清单。seed.py 是流水线第一步、后面紧跟回填,不算运行时。
import glob as _gl10
_表10 = {x if isinstance(x, str) else x[0] for x in SK.带门店键的}
_漏10, _验10 = [], 0
for _f10 in sorted(_gl10.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.py"))):
    _名10 = os.path.basename(_f10)
    if _名10.endswith("_check.py") or _名10 in ("seed.py", "boundary_audit.py", "selftest.py"):
        continue
    _s10 = open(_f10, encoding="utf-8").read()
    for _m10 in _re2.finditer(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*\(([^)]*)\)", _s10):
        _列10 = [c.strip() for c in _m10.group(2).split(",")]
        if _m10.group(1) in _表10 and "shop" in _列10:
            _验10 += 1
            if "shop_code" not in _列10:
                _漏10.append(f"{_名10}:{_s10[:_m10.start()].count(chr(10)) + 1} {_m10.group(1)}")
ck(f"backend/ 里运行时的写口:写 shop 的地方都同时写 shop_code(验了 {_验10} 处)",
   _验10 > 0 and not _漏10,
   (f"这几处只写了门店串:{_漏10} —— 回填白天不跑,这一行的门店码会一直空着,按码筛的查询安静地少它一行"
    if _漏10 else "一处写口都没扫到 —— 是没扫到,不是都通过"))

print("  " + "=" * 80)
if 坏:
    print(f"  {Rd}❌ {len(坏)} 条没过:{坏}{D}")
    sys.exit(1)
print(f"  {G}✅ 门店关联键:shop_code 和 shop 串处处对得上,留空的都有来路(验了 {n} 条){D}")
print(f"      实测(库副本上改一次名):按串筛 12780 → **0 单**、不报错;按码筛 12780 → 12780。")
sys.exit(0)
