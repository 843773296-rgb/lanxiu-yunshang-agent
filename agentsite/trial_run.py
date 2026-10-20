#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离试运行:用某一版研判提示词,在**遮蔽过的库副本**上把一批真实工单跑一遍(用户 2026-10-19 拍)。

    ./agentsite/.venv/bin/python agentsite/trial_run.py --版本 <指纹|当前> --标准答案 6 --by <名字>
    ./agentsite/.venv/bin/python agentsite/trial_run.py --版本 <指纹|当前> --工单 TDQ9003,TMERGE-00 --by <名字>

  · 指纹 = 研判设置里登记过的提示词版本(没验证过的也能试 —— 试跑本来就是为了验证它);「当前」= 代码现在这一版
  · --标准答案 N:挑 N 张**能对上评测标准答案**的工单(三类轮着挑),对比页才算得出谁答对了
  · 结果只进 triage_trial 表,看对比页(研判质量看板最下面);**不写真实研判、不动工单状态**
  · 工具服务整个改读副本;每跑完一条核一次「副本生效」凭证 —— 没有凭证就停下、这一条不存
    (那说明工具读的可能是真库:顾客信息没遮、结果也不是在副本上跑出来的)
"""
import asyncio
import datetime as dt
import hashlib
import os
import shutil
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]


def 参数(名):
    if 名 in sys.argv:
        i = sys.argv.index(名)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    return None


def 主():
    版, 单, 数, 谁 = 参数("--版本"), 参数("--工单"), 参数("--标准答案"), 参数("--by")
    认识 = {"--版本", "--工单", "--标准答案", "--by"}
    多余 = [a for i, a in enumerate(sys.argv[1:], 1) if a.startswith("--") and a not in 认识]
    if 多余 or not 版 or not 谁 or bool(单) == bool(数) or (数 and not 数.isdigit()):
        sys.exit(__doc__)
    import ops, triage_config as TC, triage_trial as TT
    # 挑工单
    c = sqlite3.connect(ops.DB); c.row_factory = sqlite3.Row
    if 单:
        行 = [c.execute("SELECT id, type, ref_id FROM task WHERE id=?", (t,)).fetchone() for t in 单.split(",")]
        if not all(行):
            sys.exit(f"有工单号查不到:{单}")
    else:
        可 = c.execute("""SELECT t.id, t.type, t.ref_id FROM task t JOIN triage tr ON tr.task_id=t.id
                          JOIN truth u ON u.case_id=tr.case_id GROUP BY t.id ORDER BY t.type, t.id""").fetchall()
        按类 = {}
        for r in 可:
            按类.setdefault(r["type"], []).append(r)
        行, i = [], 0
        while len(行) < int(数) and any(按类.values()):    # 三类轮着挑
            类 = sorted(按类)[i % len(按类)]
            if 按类[类]:
                行.append(按类[类].pop(0))
            i += 1
    c.close()
    import sdk
    系统 = hashlib.sha256(sdk.SYS_TASK.encode("utf-8")).hexdigest()[:12]
    副 = TT.遮蔽副本()
    os.environ["LANXIU_DB"] = 副                       # sdk 拉起工具服务时显式带上(见 sdk.py 那段)
    凭证 = os.path.join(os.path.dirname(副), "副本生效.txt")
    批 = "试跑-" + dt.datetime.now().strftime("%m%d%H%M%S")    # 真实时钟:批次号只求不重
    print(f"批次 {批} · {len(行)} 张工单 · 版本 {版} · 副本 {副}")
    try:
        for r in 行:
            fp = TC.当前代码版本(r["type"])[0] if 版 == "当前" else 版
            提示 = ops.研判提示词(r["type"], r["ref_id"], r["id"])[2] if 版 == "当前" else \
                TC.渲染(fp, r["type"], r["ref_id"], r["id"])
            t0 = time.time()
            try:
                out = asyncio.run(asyncio.wait_for(sdk.run("task", 提示), 180))
                text, tools, cost, 错 = out["text"], [t["tool"].split("__")[-1] for t in out["trajectory"]], out.get("cost_usd"), None
            except Exception as e:                       # noqa: BLE001
                text, tools, cost, 错 = "", [], None, f"{type(e).__name__}: {e}"[:300]
            if not os.path.exists(凭证):
                sys.exit(f"❌ 没有「副本生效」凭证 —— 工具服务可能读的是真库(顾客信息没遮)。{r['id']} 这一条不存,整批停下")
            TT.存(批, r["id"], f"研判:{fp}·系统:{系统}", text, tools, cost, 谁, error=错)
            print(f"  {r['id']:<14} {'跑挂了' if 错 else '完成'}  {time.time() - t0:5.1f}s")
    finally:
        shutil.rmtree(os.path.dirname(副), ignore_errors=True)
    print(f"完成。对比页:研判质量看板最下面「版本对比」,批次 {批}")


if __name__ == "__main__":
    主()
