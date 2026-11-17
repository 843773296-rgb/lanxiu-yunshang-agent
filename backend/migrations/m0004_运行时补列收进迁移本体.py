"""第 4 条:把第 1 条「原样调用原函数」的那 7 处补列,**列清单搬进迁移本体**(2026-11-17,执行手册 W16 第一类)。

第 1 条(m0001)当时的做法是调 merge._确保列 / ops._确保等顾客列 / ops._确保后加的列 / ops._确保重开列 /
relabel.确保列 / asr._补列 / seed_rating._补列 这 7 个函数 —— 列清单还在各模块里,运行时照旧「第一次走到就 ALTER」,
迁移目录只是多了一条引用。tools/migration_check 把它们登记成欠债(15 处 ALTER TABLE)。
这一条把列清单**写在这里**,那 7 个函数改成空壳(m0001 还会调它们,不许改 m0001;空壳什么都不做),
写口改成「缺列就报 NO_COLUMN 叫人跑 migrate.py」(照 delivery_notice_write 的先例)。

⚠️ 不是把 ALTER 挪进辅助函数、运行时照旧调 —— 那样登记数降了、运行时补列一点没少,是骗计数(并行会话 11-17 01:3x 盘点时点的坑)。
这里之后,运行时**没有任何路径**会 ALTER 这些表。

幂等:每张表先读 PRAGMA,缺哪列加哪列;表不在就跳过(建表归 seed.py / ensure_tables)。
rating 的列清单从 seed_rating.DDL 现读(那张表的 DDL 就是它的真相源;抄一份到这里就会改一份漏一份)——
读的是 CREATE TABLE 文本,ALTER 只在这里发生。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

列们 = {
    # 客户合并(merge._确保列)
    "customer": (("merged_into", "TEXT"),),
    # 在等顾客(ops._确保等顾客列)
    "task": (("waiting", "TEXT"),),
    # 研判:回执 / 交付核对 / 扣下的草稿(ops._确保后加的列)、重开(ops._确保重开列)、改判复核(relabel.确保列)
    "triage": (("receipt", "TEXT"), ("receipt_kind", "TEXT"), ("prompt_ver", "TEXT"), ("delivery_check", "TEXT"),
               ("withheld_draft", "TEXT"),
               ("reopen_count", "INT DEFAULT 0"), ("reopen_note", "TEXT"),
               ("relabel_review", "TEXT"), ("relabel_by_no", "TEXT"), ("relabel_reviewer", "TEXT"),
               ("relabel_reviewed_at", "TEXT"), ("relabel_note", "TEXT")),
    # 录音流水线(asr._补列)
    "call_audio": (("channel", "TEXT"), ("status", "TEXT"), ("fail_reason", "TEXT"), ("uploaded_by", "TEXT"),
                   ("then_flow", "TEXT"), ("then_result", "TEXT")),
    "call_transcript": (("raw_text", "TEXT"), ("fixes", "TEXT"), ("speaker_src", "TEXT")),
}


def _rating列():
    """评价表的列从它自己的 DDL 现读 —— seed_rating._补列 原来就是这么算的,只是算完直接 ALTER。"""
    import seed_rating
    体 = re.search(r"CREATE TABLE IF NOT EXISTS rating\((.*?)\);", re.sub(r"--[^\n]*", "", seed_rating.DDL), re.S).group(1)
    出 = []
    for 段 in 体.split(","):
        字 = 段.split()
        if len(字) >= 2 and 字[0].upper() not in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK"):
            出.append((字[0], " ".join(字[1:])))
    return tuple(出)


def up(c):
    有表 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    全部 = dict(列们)
    if "rating" in 有表:
        全部["rating"] = _rating列()
    for 表, 列 in 全部.items():
        if 表 not in 有表:
            continue
        有 = {r[1] for r in c.execute(f"PRAGMA table_info({表})")}
        for 名, 型 in 列:
            if 名 not in 有:
                c.execute(f"ALTER TABLE {表} ADD COLUMN {名} {型}")
