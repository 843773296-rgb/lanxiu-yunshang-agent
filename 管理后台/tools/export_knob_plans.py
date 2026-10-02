#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把后台的旋钮方案导出成方案文件(库 → 文件,**单向**)。

## 为什么是导出脚本,而不是接口直接写文件

业界这套叫「控制面 + pull + 本地兜底」(LaunchDarkly / Langfuse 那一类的
标准形态):**文件是导出的产物,不是接口的副作用**。

让 API 服务去写仓库里的文件有两个坏处:一是它把「编辑」和「发布」
合成了一个动作(点一下保存就生效,没有中间确认);
二是后台和澜绣迟早不在同一台机器上,而那天这条路会**悄悄失效** ——
接口照样返回 200,文件没人写。

## ⚠️⚠️ 只改文件里的 `旋钮` 这一个键

方案文件装的不只是旋钮:

    号 / 建于 / 为什么 / 拷自(改提示词前的原文快照) / 改(提示词改动)
    / 验证(跑过的评测:时间、题数、过了几道、哪个模型、哪个提交) / 旋钮

后台**只管旋钮那一半**。整份覆盖会抹掉 `改` 和 `验证` ——
而 `验证` 是跑过的评测结果,**不可重建**(要重跑一遍评测,花钱而且结果会漂)。

> **一个只管一半的编辑器,在保存时会把另一半清掉** ——
> 而那在「保存成功」那一刻看不出来。

所以这里是**读 → 只改 `旋钮` → 写回**。文件不存在时才建一份新的
(带 `号` / `建于` / `为什么`,`拷自` / `改` / `验证` 留空)。

## 默认就写,没有 dry-run

10-02 一天栽了两次「默认 dry-run 而且退出码 0」。要只看用 `--看`。
> 一个默认不写、而且退出 0 的脚本,和一个写成功的脚本,
> **在 CI 日志的绿勾上长得一模一样。**

## 已知盲区

- **单向。** 手改了方案文件**不会回到库**。后台详情会报出来
  (比 `file_hash`),但不会自动合并 —— 合并要人决定留哪一份。
- **不验 V3 真读到了什么。** 它读的是文件,而这个脚本只保证
  「文件里的 `旋钮` == 库里的」。那一半归
  `tools/knob_plan_sync_check.py`。
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
仓 = os.path.dirname(根)
sys.path.insert(0, os.path.join(根, "services", "api", "app"))
sys.path.insert(0, 仓)

项目id = "project_lanxiu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true", help="只看不写(**默认是写**)")
    a = ap.parse_args()

    print(f"\n\033[1m▸ 把后台的旋钮方案导出成方案文件(库 → 文件){D}")
    from agent import knobs as K          # noqa: E402
    from db import 事务                    # noqa: E402
    from sqlalchemy import text as _t

    坏 = K.落点核对()
    if 坏:
        # ⚠️ **落点核对不过就不导。** 那几个旋钮可能是滑块 ——
        # 导出一个滑块方案,跑出来的分数**读起来完全合理**,
        # 而它和「没套方案」是一回事。
        print(f"  {R}❌ 落点核对不过,**不导**:{坏}{D}")
        print(f"     那几个旋钮可能是滑块 —— 导出一个滑块方案,"
              f"跑出来的分数读起来完全合理,**而它和没套方案是一回事**。")
        return 1
    print(f"  落点核对:{G}✅ {len(K.旋钮表)} 个旋钮都接上了{D}")
    os.makedirs(K.目录, exist_ok=True)

    with 事务() as c:
        行 = c.execute(_t("""select * from knob_plans
                           where project_id=:p and archived_at is null
                           order by key"""), {"p": 项目id}).mappings().all()
        行 = [dict(r) for r in 行]
        if not 行:
            print(f"  {Y}⚠️ 后台里一个方案都没有 —— 没东西可导。{D}")
            print(f"     (这不是失败:方案是在后台上建的。"
                  f"**而「没有方案」和「读不到库」要分得开** —— "
                  f"这里读到了库,只是里面是空的)")
            return 0
        print(f"  后台里 {len(行)} 个方案")

        if a.看:
            print(f"\n  {Y}⚠️ `--看`:一个文件都不写。{D}")
            for r in 行:
                f = os.path.join(K.目录, f"{r['key']}.json")
                print(f"     · {r['key']:18} 旋钮={r['params']} "
                      f"文件{'已在' if os.path.exists(f) else '要新建'}")
            return 0

        新建, 更新, 没动 = [], [], []
        for r in 行:
            号 = r["key"]
            f = os.path.join(K.目录, f"{号}.json")
            if os.path.exists(f):
                # ⚠️ **读出来,只改 `旋钮`,写回。** 见文档串那一段。
                旧 = json.load(open(f, encoding="utf-8"))
                原旋 = 旧.get("旋钮") or {}
                旧["旋钮"] = dict(r["params"] or {})
                # `为什么` 也跟着后台走(它是后台在编辑的那一栏),
                # 而 `拷自` / `改` / `验证` **一个字不动**。
                if r.get("change_note"):
                    旧["为什么"] = r["change_note"]
                体 = 旧
                动了 = (原旋 != 体["旋钮"])
            else:
                体 = {
                    "号": 号,
                    "建于": datetime.datetime.now().isoformat(timespec="seconds"),
                    "为什么": r.get("change_note") or "",
                    # 这三个留空:后台只管旋钮那一半。
                    "拷自": {}, "改": {}, "验证": [],
                    "旋钮": dict(r["params"] or {}),
                }
                动了 = True
            料 = json.dumps(体, ensure_ascii=False, indent=1) + "\n"
            现 = open(f, encoding="utf-8").read() if os.path.exists(f) else None
            if 现 == 料:
                没动.append(号)
            else:
                open(f, "w", encoding="utf-8").write(料)
                (更新 if 现 is not None else 新建).append(号)
            哈 = "sha256:" + hashlib.sha256(料.encode()).hexdigest()
            c.execute(_t("""update knob_plans
                set exported_at=now(), file_hash=:h,
                    updated_at=now(), revision=coalesce(revision,0)+1
                where project_id=:p and key=:k"""),
                      {"h": 哈, "p": 项目id, "k": 号})

    print(f"  {G}✅ 新建 {len(新建)} 份 · 改写 {len(更新)} 份 · "
          f"没动 {len(没动)} 份{D}")
    for 号 in 更新:
        print(f"     ↻ {号}(**`改` / `拷自` / `验证` 一个字没动**)")
    print(f"\n  ⚠️ 盲区:**单向**。手改了方案文件不会回到库 —— "
          f"后台详情会比 `file_hash` 报出来,但不会自动合并"
          f"(合并要人决定留哪一份)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
