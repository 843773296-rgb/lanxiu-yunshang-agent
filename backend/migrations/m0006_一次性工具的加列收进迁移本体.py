"""第 6 条:重建 / 日平移流水线里那几个「一次性工具」顺带加的列,收进迁移本体(2026-11-17,执行手册 W16 第三类)。

这些工具(tools/add_shop_code、add_cust_advisor、migrate_appt_columns、migrate_order_wearer、seed_new_products、
backend/fix_advisor_ref、fix_product_pattern、seed_repair)各自在跑之前「缺列就 ALTER」—— 本意是给已经存在的库补列,
新库靠 seed.py 的建表语句。16 处 ALTER 散在 8 个文件里,哪条库做到了哪一步谁也说不清(迁移版本表管不到它们)。
现在列清单写在这里;工具只管回填 / 建触发器 / 造数,**缺列就明说「先跑 migrate.py」**,不再偷偷补。
重建流水线在 seed.py 之后立刻跑 migrate.py,所以这些列在第一个工具跑之前就在了。

两处清单从它们的真相源现读、不抄第二份:
  · shop_code 加在 backend/shop_key.带门店键的 那张登记表的每张表上(那是「哪些表带门店键」唯一的一份)
  · 顾问工号列按 backend/fix_advisor_ref.映射(表, 名列, 号列):名列在的表才加号列
读的是列表,ALTER 只在这里发生。

幂等:每张表先读 PRAGMA,缺哪列加哪列;表不在就跳过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

列们 = {
    # tools/add_cust_advisor:订单上冗余「客户现在归谁」(触发器照旧由那个工具建)
    "ordr": (("cust_advisor_no", "TEXT"),
             # tools/migrate_order_wearer:这一单给谁穿
             ("wearer_id", "TEXT")),
    # tools/migrate_appt_columns:预约点名三态 + 渠道;客户来源渠道(用户 11-12 拍「三列都加」,台账第十二条)
    "appointment": (("named_advisor_no", "TEXT"),
                    ("named_state", "TEXT CHECK(named_state IS NULL OR named_state IN ('点名','没点','不详'))"),
                    ("channel", "TEXT")),
    "customer": (("source_channel", "TEXT"),),
    # tools/seed_new_products / backend/fix_product_pattern
    "product": (("plan_on_shelf", "TEXT"), ("pattern", "TEXT")),
    # backend/seed_repair:金额授权两列(业务 2026-09-24)+ 报修单自己量出来的尺寸差
    "maintain_decision": (("approved_by", "TEXT"), ("approve_note", "TEXT")),
    "maintain": (("尺寸差", "TEXT"),),
}


def up(c):
    有表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def 加(表, 名, 型):
        有 = {r[1] for r in c.execute(f"PRAGMA table_info({表})")}
        if 名 not in 有:
            c.execute(f"ALTER TABLE {表} ADD COLUMN {名} {型}")

    for 表, 列 in 列们.items():
        if 表 in 有表:
            for 名, 型 in 列:
                加(表, 名, 型)
    import shop_key, fix_advisor_ref
    for 表, _ in shop_key.带门店键的:
        if 表 in 有表:
            加(表, "shop_code", "TEXT")
    for 表, 名列, 号列 in fix_advisor_ref.映射:
        if 表 in 有表 and 名列 in {r[1] for r in c.execute(f"PRAGMA table_info({表})")}:
            加(表, 号列, "TEXT")
