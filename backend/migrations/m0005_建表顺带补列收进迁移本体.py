"""第 5 条:各模块「建表时顺带给老表补列」的 13 处收进迁移本体(2026-11-17,执行手册 W16 第二类)。

原来九个模块的 建表() / 确保表() 里都是「CREATE TABLE IF NOT EXISTS → PRAGMA 看列 → 没有就 ALTER」:新库建出来就全,
老库靠第一次调用时补。这一条把老库补列写在这里,建表函数只建表(建表语句直接带全列,新库不需要补);
运行时不再有任何路径 ALTER 这些表。重建流水线在 seed.py 之后立刻跑一次 migrate.py(再在 ensure_tables 之后跑一次):
seed 建的老式表(scheme / refund_trace)在后面的 backfill 写新列之前就补齐。

pool_notice.shop_code 补完还要按 shop 回填门店码 —— 原来写在 ownership_release.建表 里,一起搬过来(数据修补也归迁移)。

幂等:每张表先读 PRAGMA,缺哪列加哪列;表不在就跳过(建表归各模块 / ensure_tables)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

列们 = {
    # arrival_card:回捞建议第几版 / 发给模型的材料 / 记录仪 trace(10-10 产出监督)
    "recall_advice": (("version", "INTEGER NOT NULL DEFAULT 1"), ("input", "TEXT"), ("trace_id", "TEXT")),
    # opportunity_store:方案挂到哪条商机
    "scheme": (("opportunity_id", "TEXT"),),
    # order_contract:顾客单独勾「不适用七天无理由退货」(业务 10-10 晚 #7)
    "order_contract": (("no7_ack_at", "TEXT"), ("no7_ack_by", "TEXT")),
    # ownership_release:公海知会的门店码(11-14)
    "pool_notice": (("shop_code", "TEXT"),),
    # refund_write:渠道退款流水号(唯一索引在 refund_write.建表 里建,列要先在)
    "refund_trace": (("refund_no", "TEXT"),),
    # report_doc:哪一轮对话生成的 / 打回 / 用的哪版模板(10-10 产出监督、复审第 4 节 C)
    "store_report_doc": (("trace_id", "TEXT"), ("rejected_at", "TEXT"), ("rejected_by", "TEXT"), ("reject_reason", "TEXT"),
                         ("template_ver", "INTEGER")),
    # report_template:模板版本的状态线(10-23)
    "report_template_ver": (("status", "TEXT NOT NULL DEFAULT '已发布'"), ("trial_shops", "TEXT"),
                            ("trial_at", "TEXT"), ("trial_by", "TEXT"), ("trial_why", "TEXT"),
                            ("publish_at", "TEXT"), ("publish_by", "TEXT"), ("publish_why", "TEXT"),
                            ("withdraw_at", "TEXT"), ("withdraw_by", "TEXT"), ("withdraw_why", "TEXT")),
    # terms_store:这一通录音的同意依据,上传那一刻定下来
    "call_audio": (("consent_basis", "TEXT"),),
    # triage_config:发布那一刻完整的一份配置(10-19 当天先建过一版没有这列的表)
    "triage_config": (("snapshot", "TEXT"),),
}


def up(c):
    有表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for 表, 列 in 列们.items():
        if 表 not in 有表:
            continue
        有 = {r[1] for r in c.execute(f"PRAGMA table_info({表})")}
        for 名, 型 in 列:
            if 名 not in 有:
                c.execute(f"ALTER TABLE {表} ADD COLUMN {名} {型}")
                if (表, 名) == ("pool_notice", "shop_code"):
                    # 补完按 shop 回填门店码(原 ownership_release.建表 里的那段):shop 表不在就留空,下次有人写的时候补
                    if "shop" in 有表:
                        import shop_key as _SK
                        门店 = _SK.门店表(c)
                        for (店,) in c.execute("SELECT DISTINCT shop FROM pool_notice").fetchall():
                            c.execute("UPDATE pool_notice SET shop_code=? WHERE shop IS ?", (_SK.该填的码(店, 门店), 店))
