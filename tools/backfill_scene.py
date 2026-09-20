#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场合维度:词表进 sys_code + 建商品↔场合关联表 + 回填默认值。

业务决策(D1,2026-09-20):
  本期在用   旅拍写真 · 日常通勤 · 婚礼婚服 · 节庆礼仪 · 正式场合
  为扩展预留 演出舞台 · 运动户外 · 居家休闲
  「允许日后加减」是硬要求 —— 所以词表是**数据**(进 sys_code),不是代码里的常量。
  业务加一个场合是运营动作,不该是一次发版。

  场合允许重叠:一件衣服可以既「运动户外」又「正式场合」。所以是多对多,不是一列。
  只有成品服装有场合;绣片/盘扣/配饰/面料部件都不给。

三个坑,都写在这儿免得下次再踩:

① **按类目规则挂,不按「252」这个数。**
   决策文档写的是「汉服成衣 252 个全挂」—— 我核过,252 = 成品服装 255 件里**上架的**那些。
   但 252 是**快照**,规则才是**意图**:下架的会重新上架、新品会进来。
   写死 252 的后果是新商品不会被挂上,**而查出来看着完全正常**。
   所以这里按 category 前缀挂,不按数字。

② **「不适用」和「还没标」不能都表现为「关联表里没记录」。**
   配饰(C04)/面料部件(C05) 是**类目决定不适用** —— 它们本来就不该有场合,
   所以「没记录」对它们是正确状态。
   而 C06(西式成衣)是**适用但本期没标** —— 它和汉服成衣一样是成衣,
   只是默认值「旅拍写真」按决策只给汉服。
   两者都表现为「没记录」,靠**类目**区分,不靠关联表里加标记。
   → 末尾的自检会把「适用但没标」单独数出来,不让它混进「不适用」。

③ **回填要能重跑。** 这个脚本由 rebuild.sh 调用,而重建是幂等的 ——
   所以先删自己写过的(source='回填默认'),再写。
   **不删业务手工标的** —— 那是人的输入,脚本无权覆盖。

技术约束(见 tools/determinism_check.py):
  不用 SQL 的 ORDER BY RANDOM()、不用 random(这里压根没有随机)、
  不拿机器的今天当基准 —— 时间用 seed.py 的 TODAY(世界的今天)。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")

# 「世界的今天」,不是机器的今天 —— 机器的今天每过一天就变一次,重建就不可复现了
from seed import TODAY

CATEGORY = "场合"
# (code, name, 本期在用?)  —— 顺序即 sort
SCENES = [
    ("SC-OCC-01", "旅拍写真", True),
    ("SC-OCC-02", "日常通勤", True),
    ("SC-OCC-03", "婚礼婚服", True),
    ("SC-OCC-04", "节庆礼仪", True),
    ("SC-OCC-05", "正式场合", True),
    ("SC-OCC-06", "演出舞台", False),
    ("SC-OCC-07", "运动户外", False),
    ("SC-OCC-08", "居家休闲", False),
]

# 成品服装 = 女装/男装/童装。配饰(C04)、面料部件(C05)不给场合。
# C06(西式/非汉服)是成衣,结构上允许挂,但默认值只给汉服 —— 见坑②
成品服装 = ("C01", "C02", "C03")
适用场合 = ("C01", "C02", "C03", "C06")
默认场合 = "SC-OCC-01"      # 旅拍写真
回填来源 = "回填默认"


def main():
    c = sqlite3.connect(DB)

    # ── 1. 词表进 sys_code ────────────────────────────────────
    # status 三值:启用(本期在用)/ 预留(结构上有、本期不用)/ 停用
    # 「预留」不能标成「启用」—— 否则**「业务在用的场合」和「我们留着的场合」长得一模一样**,
    # 而按 status='启用' 过滤的地方会把预留的也放出去。
    for i, (code, name, 在用) in enumerate(SCENES, 1):
        c.execute("""insert into sys_code(code,category,name,val,sort,status,note)
                     values(?,?,?,?,?,?,?)
                     on conflict(code) do update set
                       name=excluded.name, sort=excluded.sort,
                       status=excluded.status, note=excluded.note""",
                  (code, CATEGORY, name, code.lower().replace("sc-occ-", "occ"), i,
                   "启用" if 在用 else "预留",
                   "本期在用" if 在用 else "为扩展预留:接其他服装品类时启用,现在 0 命中是正常的"))

    # ── 2. 商品↔场合关联表(多对多,允许重叠) ──────────────────
    c.execute("""create table if not exists product_scene(
                   spu     TEXT not null,
                   scene   TEXT not null,
                   source  TEXT not null,     -- 回填默认 / 业务标注 —— 分开「系统填的」和「人标的」
                   created TEXT not null,
                   primary key(spu, scene))""")

    # ── 3. 回填 ───────────────────────────────────────────────
    # 只删自己写过的,不碰业务手工标的(见坑③)
    c.execute("delete from product_scene where source=?", (回填来源,))
    ph = ",".join("?" * len(成品服装))
    c.execute(f"""insert or ignore into product_scene(spu,scene,source,created)
                  select spu, ?, ?, ? from product
                  where substr(category,1,3) in ({ph})""",
              (默认场合, 回填来源, TODAY, *成品服装))
    c.commit()

    # ── 4. 自己证明干了活 ─────────────────────────────────────
    # 不报「成功」就完事 —— **一个什么都没回填的脚本,和一个回填完的脚本,输出长得一模一样**
    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    词表数 = q("select count(*) from sys_code where category=?", CATEGORY)
    在用数 = q("select count(*) from sys_code where category=? and status='启用'", CATEGORY)
    应挂 = q(f"select count(*) from product where substr(category,1,3) in ({ph})", *成品服装)
    已挂 = q("select count(distinct spu) from product_scene")

    if 词表数 != len(SCENES):
        sys.exit(f"❌ 场合词表应有 {len(SCENES)} 条,实际 {词表数} 条")
    if 已挂 < 应挂:
        sys.exit(f"❌ 成品服装 {应挂} 个,只挂上 {已挂} 个 —— 回填漏了")

    # 「适用但还没标」单独数出来,不让它混进「不适用」(见坑②)
    ph2 = ",".join("?" * len(适用场合))
    待标 = q(f"""select count(*) from product
                 where substr(category,1,3) in ({ph2})
                   and spu not in (select spu from product_scene)""", *适用场合)
    不适用 = q(f"""select count(*) from product
                   where substr(category,1,3) not in ({ph2})""", *适用场合)

    print(f"  场合词表 {词表数} 条(本期在用 {在用数}、为扩展预留 {词表数-在用数})")
    print(f"  成品服装 {应挂} 个已挂「旅拍写真」;适用但待业务标注 {待标} 个;类目决定不适用 {不适用} 个")
    c.close()


if __name__ == "__main__":
    main()
