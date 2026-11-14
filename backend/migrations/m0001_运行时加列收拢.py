"""第 1 条:把 7 个「运行时才补列」的函数收进迁移(2026-11-14)。

原来这些列在**第一次走到那条路**时才加(合并客户 / 等顾客 / 研判回执 / 重开 / 改判复核 / 录音流水线 / 评价)。
这里**原样调用原函数**,不抄一份列清单 —— 抄两份就会改一份漏一份;原函数照旧留在原处被调用(双保险),
等以后逐个把调用处换成「迁移做过就不用再查」再删。

全部幂等:原函数都是先读 PRAGMA 再 ALTER。表不存在就跳过(新库那张表还没建,建的时候 DDL 里已经带全列,
或者之后建表那一步会补)—— 不在这里顺手建表,建表归 tools/ensure_tables.py。
例外一处:`asr._补列` 原函数里顺带 `CREATE TABLE IF NOT EXISTS asr_verified_pair` —— 原样调用就原样带上,
那张表本来也登记在 ensure_tables(asr.建表 → _补列),所以不会多出一张没人认领的表。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def up(c):
    import merge, ops, relabel, asr, seed_rating
    有 = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    步 = [
        ({"customer"}, merge._确保列),
        ({"task"}, ops._确保等顾客列),
        ({"triage"}, ops._确保后加的列),
        ({"triage"}, ops._确保重开列),
        ({"triage"}, relabel.确保列),
        ({"call_audio", "call_transcript"}, asr._补列),
        ({"rating"}, seed_rating._补列),
    ]
    for 要, f in 步:
        if 要 <= 有:
            f(c)
