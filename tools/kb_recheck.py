#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识问题复验:拿原问题按**现在的**知识重跑一遍检索,存档前后命中对比(外部复审第 4 节 E,10-23)。

挑哪些(backend/kb_issue.复验对象):
  · 标了「已修订」的
  · 低分的(≤ kb_issue.低分线,卡片原话 ≤2)
  · 门店侧看得到的「证据不够」—— 检索零命中

⚠️⚠️ **复验只证明「找到了相关片段」,证明不了「答对了」。**
只跑检索(`kb_rag`,`要生成: False`),**不调大模型生成答案** —— 找到的片段对不对得上问题、
照着它答出来对不对,仍要人评。所以结论只有三种说法:找到了相关片段 / 仍然零命中 / 复验没跑成。
(管理后台那边的检索链本身带精排,精排会调模型 —— 那是检索算法的一部分,这里不改它。)

不改知识正文、不改检索算法和门槛、不写回任何知识 —— 只往 kb_recheck 存档。
管理后台(8801)没起时每一条都记「复验没跑成」,**不记成零命中**(查不了 ≠ 知识库里没有)。

用法:
  python3 tools/kb_recheck.py              挑出来、重跑、存档
  python3 tools/kb_recheck.py --列出        只列要复验哪些,不跑
  python3 tools/kb_recheck.py --只 rr_xxx   只复验这几条(逗号隔开)
"""
import argparse
import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
import kb_issue as KI  # noqa: E402

调用方 = "澜绣 知识复验"


def 检索(问题):
    """真的那一路:走 api.kb_rag(和 chat 同一个口,只拿证据不生成)。调用方标成复验,不混进 chat 的统计。"""
    import api
    os.environ["LANXIU_RAG_CALLER"] = 调用方
    return api.kb_rag(问题)


def 跑(检索口=检索, 只=None, 只列=False, db=None, 打印=print):
    """→ dict(批次, 条数, 结果们, 声明)。`检索口` 可换(检查里用自造的,免得依赖 8801 起没起)。"""
    对象 = KI.复验对象(db=db, 只=只)
    批次 = "rc-" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    打印(f"▸ 知识问题复验 · {len(对象)} 条要复验" + ("(只列,不跑)" if 只列 else f" · 批次 {批次}"))
    打印("  " + KI.不等于答对)
    结果们 = []
    for 记录, 为什么 in 对象:
        if 只列:
            打印(f"  · {记录['run_id']}  [{为什么}]  {记录['question'][:40]}")
            continue
        try:
            新 = 检索口(记录["question"])
        except Exception as e:     # 查不了 ≠ 零命中 —— 单独记
            新 = {"error": f"{type(e).__name__}: {e}"}
        r = KI.记复验(批次, 记录, 为什么, 新, db=db)
        r.update(编号=记录["run_id"], 为什么=为什么, 问题=记录["question"])
        结果们.append(r)
        前后 = f"{r['原来几段']} → {'—' if r['现在几段'] is None else r['现在几段']} 段"
        打印(f"  · {记录['run_id']}  [{为什么}]  {r['结论']}({前后}){'  ' + r['错'] if r['错'] else ''}")
        for x in r["新出现的出处"][:3]:
            打印(f"      + {x}")
        for x in r["不见了的出处"][:3]:
            打印(f"      − {x}")
    if 结果们:
        数 = {k: sum(1 for x in 结果们 if x["结论"] == k) for k in KI.复验结论们}
        打印("  合计:" + " · ".join(f"{k} {v}" for k, v in 数.items()))
    打印("  " + KI.不等于答对 + " 存档在 kb_recheck,后台「知识问题」详情页看得到前后对比。")
    return dict(批次=批次, 条数=len(对象), 结果们=结果们, 声明=KI.不等于答对)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--列出", action="store_true")
    ap.add_argument("--只", default="")
    a = ap.parse_args()
    只 = [x.strip() for x in a.只.split(",") if x.strip()] or None
    跑(只=只, 只列=a.列出)


if __name__ == "__main__":
    main()
