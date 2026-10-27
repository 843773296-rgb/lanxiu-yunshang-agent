#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给每家店存一份**上一个完整周的周报草稿** —— 重建时跑(2026-10-27 加)。

## 为什么要有它

经营报告原来**全靠人在聊天里存**:「生成上周周报」→「存一下」。重建库从零造数,
那些手存的报告不在任何一步里,于是 10-27 重建完 `store_report_doc` 一条都没有,
报告页冒烟当场红(「只填了 2 个节点」——页面只剩一句「还没有存过报告」)。
> 一次性在现库上做出来的数据,下一次重建就没了。(同一天确认书也是这么丢的,见 backfill_contracts.py)

## 怎么存

**走正门**:以那家店店长的身份调 `api.store_report` 取数、`api.save_report` 存草稿 ——
和聊天里存报告是同一个函数,不手写 INSERT(手写就是第二份实现,冻结的取数包、模板版本都会对不上)。

正文**不是模型写的**,是这里照取数包里的环比拼的,开头写明 —— 不冒充一份 AI 写的报告。
只存草稿、不确认:确认是店长的事。

    python3 tools/seed_reports.py          # 幂等:同一店同一期已经有报告就跳过
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"), ROOT]
import api  # noqa: E402


def 正文(pack):
    环 = pack.get("环比") or {}
    行 = [f"> 演示数据:这份草稿是重建库时由 tools/seed_reports.py 照取数包拼的,不是模型写的。",
          "", f"## {pack.get('范围')} · 周报 · {pack.get('区间')}", ""]
    for k, v in 环.items():
        if isinstance(v, dict) and "本期" in v:
            行.append(f"- {k}:本期 {v['本期']},上期 {v.get('上期')},环比 {v.get('环比') or '—'}")
    行 += ["", f"上一期:{环.get('上一期', '—')}。口径和出处见冻结的取数包。"]
    return "\n".join(行)


def main():
    c = sqlite3.connect(api.DB)
    店长们 = c.execute("""SELECT no, name, role, shop FROM staff
                          WHERE role='店长' AND coalesce(status,'启用')='启用' AND shop IS NOT NULL AND shop<>''
                          ORDER BY shop, no""").fetchall()
    有 = {(r[0], r[1]) for r in c.execute("SELECT shop, period_start FROM store_report_doc")}
    c.close()
    存了, 跳过, 一店一个 = [], [], set()
    for no, name, role, shop in 店长们:
        if shop in 一店一个:
            continue
        一店一个.add(shop)
        me = dict(no=no, name=name, role=role, shop=shop)
        with api.as_user(me):
            pack = api.store_report(kind="周")
            if pack.get("error"):
                sys.exit(f"❌ {shop} 取数失败:{pack['error']}")
            起 = (pack.get("区间") or "").split(" ~ ")[0]
            if (shop, 起) in 有:
                跳过.append(shop)
                continue
            r = api.save_report(body=正文(pack), kind="周")
        if not r or r.get("error") or r.get("ok") is False:
            sys.exit(f"❌ {shop} 存报告失败:{r}")
        存了.append((shop, r.get("报告号") or r.get("id") or r.get("report_id")))
    if not 存了 and not 跳过:
        sys.exit("❌ 一家店长都没有 —— 一份报告都没存(这不叫通过)")
    print(f"✅ 存了 {len(存了)} 份周报草稿:{存了}" + (f";已有、跳过 {len(跳过)} 家:{跳过}" if 跳过 else ""))


if __name__ == "__main__":
    main()
