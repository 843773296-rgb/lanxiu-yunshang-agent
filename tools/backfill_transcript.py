#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把造好的通话逐字稿灌进库,真值单独进 truth。

产物来自 `fakedata/gen_transcripts.py`(一次性,走模型,结果进版本库)。
**这一步是确定性的** —— 只读文件、按固定顺序分配,不调模型不用随机。

## 三个要分清的东西,它们在库里长得很像

**① 有录音 vs 没录音。**
这批逐字稿是**文本造的,没有对应音频**。所以 `call_audio.path` 留空,
`source` 写明「文本造的(无音频)」。
伪造一个 path 的话,「有录音」和「没录音」就分不开了 ——
而将来接真实录音时,第一件事就是要能分开这两批。

**② 真值不进业务表。**
「这条是不是商机」是**评测答案**,进 `truth`(它绝不能经任何 API 暴露,
`backend/selftest.py` 每次都验)。
放进 `call_transcript` 的话,**被判断的 agent 自己就能读到答案**。

**③ 造的 vs 真的。**
`truth.src` 写「造数据标注」,和建库标注区分开。
**拿造出来的对话测出的商机识别率,不代表真实通话上的表现** ——
造的对话里信号比真实通话清楚得多。
"""
import json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")
产物 = os.path.join(HERE, "..", "fakedata", "transcripts.json")
from seed import TODAY
import asr as _asr          # 借它的建表

来源 = "文本造的(无音频)"
真值来源 = "造数据标注"


def main():
    if not os.path.exists(产物):
        print(f"  ⏭ 没有 {产物} —— 跳过(跑 fakedata/gen_transcripts.py 生成)")
        return 0
    data = json.load(open(产物, encoding="utf-8"))
    条目 = data.get("条目", [])
    if not 条目:
        sys.exit("❌ 产物里一条都没有")

    c = sqlite3.connect(DB)
    _asr.建表(c)

    # 幂等:只清自己灌的
    c.execute("delete from call_transcript where audio_id like 'TS-%'")
    c.execute("delete from call_audio where id like 'TS-%'")
    c.execute("delete from truth where src=?", (真值来源,))

    # 确定性分配:按客户 id 排序取前 N 个,不用随机
    客户 = [r[0] for r in c.execute("select id from customer order by id limit ?", (len(条目),))]

    for i, 条 in enumerate(条目):
        tid = f"TS-{i+1:03d}"
        cid = 客户[i] if i < len(客户) else None
        c.execute("""insert into call_audio(id,customer_id,ref_kind,ref_id,path,seconds,source,created)
                     values(?,?,?,?,?,?,?,?)""",
                  (tid, cid, None, None, "", None, 来源, TODAY))
        c.execute("""insert into call_transcript(audio_id,text,engine,model,hotwords,cost_sec,trad,created)
                     values(?,?,?,?,?,?,?,?)""",
                  (tid, 条["逐字稿"], "造数据", data.get("模型", "?"), 0, None, None, TODAY))
        # 真值单独进 truth —— 业务表里不许有答案
        c.execute("""insert into truth(case_id,breakpoint,root_cause,expected_action,
                                       expected_evidence,note,src)
                     values(?,?,?,?,?,?,?)""",
                  (tid, "BP-商机", "是商机" if 条["是商机"] else "不是商机",
                   f"应判定为{'商机(' + (条.get('维度') or '') + ')' if 条['是商机'] else '不是商机'}",
                   条["剧本"], f"客户称呼:{条.get('客户称呼','')}", 真值来源))
    c.commit()

    q = lambda s, *a: c.execute(s, a).fetchone()[0]
    n = q("select count(*) from call_transcript where audio_id like 'TS-%'")
    正 = q("select count(*) from truth where src=? and root_cause='是商机'", 真值来源)
    负 = q("select count(*) from truth where src=? and root_cause='不是商机'", 真值来源)

    if n != len(条目):
        sys.exit(f"❌ 产物 {len(条目)} 条,库里只有 {n} 条")
    # **只有正例的评测集,会让「见什么都说是商机」的实现拿满分**
    if 负 == 0:
        sys.exit("❌ 一条负例都没有 —— 这样的评测集测不出误报")
    # 业务表里不许出现答案
    漏 = q("""select count(*) from call_transcript t
              where t.text like '%是商机%' or t.text like '%不是商机%'""")
    if 漏:
        sys.exit(f"❌ {漏} 条逐字稿的正文里出现了答案字样 —— 被判断的 agent 能直接读到")

    print(f"  通话逐字稿 {n} 条入库(正例 {正} / 负例 {负});真值进 truth,不在业务表里")
    print(f"  ⚠️ 这批是**文本造的,没有音频** —— call_audio.path 留空,source 写明")
    c.close()


if __name__ == "__main__":
    main()
