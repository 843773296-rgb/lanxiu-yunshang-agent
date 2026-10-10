#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出监督的同步(用户 10-10:AI 管理平台「能看 + 能打回」)—— 一次做两件事:

    ① 推:产出投递箱(报告 / 建议)里还没送到的,推给管理后台
    ② 拉:管理后台上「打回、待执行」的决定拉回来,**用这边自己的函数执行**,再回执

    python3 tools/supervise_sync.py            # 推 + 拉,各做一轮
    python3 tools/supervise_sync.py --看        # 只报积压和待执行,什么都不发、不执行
    python3 tools/supervise_sync.py --循环 30   # 每 30 秒一轮(start.sh 里配了地址才起)

地址 / 项目 / 工号和 A1 用同一组环境变量(LANXIU_USAGE_URL / _PROJECT / _USER)。**没配就明说没配**,不给默认值。

## 为什么打回由这边执行

管理后台**绝不反过来改澜绣的库**:它只记下「谁、为什么打回哪一版」;
执行(报告标打回、建议带着理由重写)走这边的正门 —— 那条路上有身份、台账和「打回的不许确认」那道闸。
执行完回执(ack),管理后台上那条决定才变成「已执行」—— **没回执的就一直挂着「待执行」**,
而不是「点了打回」就显示成功、这边其实什么都没发生。
"""
import argparse, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import artifact_report as AR
import usage_report as U


def 执行(决定):
    """一条打回决定 → (结果, 说明, 新版本)。外部id 的形状由这边定:报告:RPT… / 建议:商机号:款号。"""
    外部 = 决定.get("外部id") or ""
    谁 = f"{决定.get('created_by') or '?'}(AI 管理平台)"
    理由 = (决定.get("理由") or "").strip() or "(没写理由)"
    try:
        if 外部.startswith("报告:"):
            import report_doc
            ok, 说 = report_doc.打回(外部.split(":", 1)[1], 谁, 理由)
            return ("已标记" if ok else "执行失败"), 说, None
        if 外部.startswith("建议:"):
            import arrival_card
            _, oid, spu = 外部.split(":", 2)
            ok, 说, 新 = arrival_card.打回重写(oid, spu, 谁, 理由)
            return ("已重写" if ok else "执行失败"), 说, 新
        return "执行失败", f"认不出外部id「{外部}」是哪种产出", None
    except Exception as e:
        return "执行失败", f"{type(e).__name__}: {e}"[:200], None


def 补上报(db=None):
    """这个功能上线之前就存下的报告 / 写好的建议,也推一份上去(同一版只排一次,重复跑无害)。返回排了几条。"""
    import json as _j, sqlite3, report_doc, arrival_card as AC
    c = sqlite3.connect(db or report_doc.DB)
    try:
        report_doc.建表(c); AC.建表(c)
        n = 0
        for rid, shop, 版, body, pack, tr in c.execute(
                "SELECT id, shop, revision, body, pack, trace_id FROM store_report_doc").fetchall():
            report_doc.上报监督(rid, shop, _j.loads(pack), body, 版, tr); n += 1
        for oid, spu, 版, 正文, 来源, 模型, 材料, 号 in c.execute(
                "SELECT opp_id, spu, version, text, source, model, input, trace_id FROM recall_advice").fetchall():
            商 = AC._商品(c, spu) or {"名称": spu}
            AC._上报监督(oid, spu, 版, 材料 or "{}", 正文, 来源, 模型, 号, 商, {}, 库=c)
            n += 1
        return n
    finally:
        c.close()


def 一轮(只看=False):
    cfg = U.配置()
    总, 好, 剩, 老 = AR.积压()
    print(f"产出投递箱:共 {总} 条 · 已送到 {好} · 还剩 {len(剩)}" + (f"(最老的排于 {老})" if 老 else ""))
    if not all(cfg.values()):
        缺 = [k for k, v in cfg.items() if not v]
        print(f"⚠️ 没配管理后台地址({'、'.join(缺)})—— 一条都不会发,也拉不到打回;"
              f"配 LANXIU_USAGE_URL / LANXIU_USAGE_PROJECT / LANXIU_USAGE_USER")
        return 1 if 剩 else 0
    if 只看:
        行们, 错 = AR.待执行的决定(cfg)
        print(f"管理后台上待执行的打回:{len(行们)} 条" + (f"(拉取失败:{错})" if 错 else ""))
        return 0
    发了, 原因 = 0, {}
    for 行 in 剩:
        ok, 说 = AR.发一条(行, cfg)
        if ok:
            AR.确认(行["键"], 说); 发了 += 1
        else:
            原因[说[:60]] = 原因.get(说[:60], 0) + 1
    print(f"推:发出 {发了} 条 · 没发出 {len(剩) - 发了} 条")
    for k, v in 原因.items():
        print(f"   {v} 条:{k}")
    行们, 错 = AR.待执行的决定(cfg)
    if 错:
        print(f"拉:取不到待执行的打回 —— {错}")
        return 1
    print(f"拉:待执行的打回 {len(行们)} 条")
    for d in 行们:
        结果, 说, 新 = 执行(d)
        ok, 回 = AR.回执(cfg, d["id"], 结果, 说, 新)
        print(f"   {d.get('外部id')} 第 {d.get('版本')} 版 → {结果}:{说}" + ("" if ok else f"(⚠️ 回执没送到:{回})"))
    # 打回重写出来的新版建议刚进投递箱 —— 这一轮顺手推掉,管理后台上马上看得到新版
    if 行们:
        for 行 in AR.积压()[2]:
            ok, 说 = AR.发一条(行, cfg)
            if ok: AR.确认(行["键"], 说)
    return 0 if not 原因 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true")
    ap.add_argument("--循环", type=int, default=0)
    ap.add_argument("--补", action="store_true", help="把上线之前就有的报告 / 建议也排进投递箱")
    a = ap.parse_args()
    if a.补:
        print(f"补排了 {补上报()} 份产出(已排过的同一版不会重复)")
    if a.循环:
        # 循环模式顺带推用量(A1):产出详情页「对应调用链」要靠用量先到 —— 用量没推过去,
        # 报告那头的 trace 在管理后台就找不到,页面上只能显示「这一轮的调用还没推过来」
        import subprocess as _sp
        while True:
            try:
                r = _sp.run([sys.executable, os.path.join(ROOT, "tools", "usage_push.py")], capture_output=True, text=True)
                末 = [l for l in (r.stdout or "").splitlines() if l.strip()]
                if 末: print("用量:" + 末[-1].strip(), flush=True)
            except Exception as e:
                print(f"⚠️ 用量这一轮没推:{type(e).__name__}: {e}", flush=True)
            try: 一轮()
            except Exception as e: print(f"⚠️ 这一轮出错:{type(e).__name__}: {e}", flush=True)
            sys.stdout.flush(); time.sleep(max(10, a.循环))
    sys.exit(一轮(只看=a.看))
