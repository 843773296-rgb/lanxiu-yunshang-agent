#!/usr/bin/env python3
"""相容矩阵 · 待核实队列。

## 为什么有它

矩阵 2025 格里有 1274 格的依据是空的 —— 那是「没命中任何禁止规则」的兜底结果,
**没有人验证过**,而它们原来一律返回「可以做」。

改成不给结论(返回「待核实」)只解决了一半:**系统会永远停在「不知道」**,
因为没有任何机制让它从不知道变成知道。

所以配一条回流:**被真正问到的那一格,自动记一笔进待办**,运营核实后回填。
这样待办量由**真实需求**决定,而不是由矩阵大小决定 ——
1274 格全丢给运营是核不完的(一天核 10 格要 4 个月),
而顾问真正会问到的那几十格,一周就核完了,**而且最常被问的自然排在最前面**。

## 为什么写的是日志文件,不是业务库

这个项目最硬的保证是「**工具层一个写接口都没有**」,而且它靠 `mode=ro` 连接
**结构性**成立 —— 不是靠「这里没人写 INSERT」的自觉。

让模型的工具去写待办,那条保证当场就破。所以把两件事分开:

  · **记一笔**  —— 系统在旁边追加一行日志,不碰业务库(和记录仪同一个形态)
  · **改结论**  —— 运营在后台做,那边本来就有写权限和审批链

**模型自己一个字都写不了。**
"""
import json, os, threading, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "combo-review.jsonl")
_LOCK = threading.Lock()          # 多线程服务里可能并发追加


def record_ask(craft, material, craft_name=None, material_name=None, asked_by=None):
    """有人问到了这一格 —— 追加一行。**只追加,不改不删。**

    追加式的好处和记录仪一样:并发安全、可回放、坏了一行不影响其他行。
    聚合(问了几次、谁先核)一律从明细现算,不做增量累加 ——
    明细在,统计就永远能重建。
    """
    row = {"ts": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "craft": craft, "material": material,
           "craft_name": craft_name, "material_name": material_name,
           "asked_by": asked_by}
    try:
        with _LOCK, open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass      # 记不上待办不能影响回答本身 —— 这是旁路,不是主路
    return row


def queue(top=None, resolved=None):
    """待办队列。按**被问的次数**排序 —— 最常被问的最该先核。

    resolved:已核实的格子集合(craft, material),由调用方从库里查了传进来。
    这个模块**不连数据库** —— 它只管日志。谁核完了是业务库的事。
    """
    if not os.path.exists(LOG): return []
    agg = {}
    for line in open(LOG, encoding="utf-8"):
        try: r = json.loads(line)
        except Exception: continue
        k = (r.get("craft"), r.get("material"))
        a = agg.setdefault(k, {"craft": k[0], "material": k[1],
                               "craft_name": r.get("craft_name"),
                               "material_name": r.get("material_name"),
                               "被问次数": 0, "首次": r.get("ts"), "最近": r.get("ts")})
        a["被问次数"] += 1
        a["最近"] = r.get("ts")
        if r.get("craft_name"): a["craft_name"] = r["craft_name"]
        if r.get("material_name"): a["material_name"] = r["material_name"]
    rows = list(agg.values())
    if resolved:
        for r in rows: r["已核实"] = (r["craft"], r["material"]) in resolved
        rows = [r for r in rows if not r["已核实"]]
    rows.sort(key=lambda r: (-r["被问次数"], r["首次"] or ""))
    return rows[:top] if top else rows


if __name__ == "__main__":
    q = queue()
    print(f"待核实队列 · {len(q)} 格(按被问次数排)")
    for r in q[:15]:
        print(f"  {r['被问次数']:3d} 次  {r.get('craft_name') or r['craft']} × "
              f"{r.get('material_name') or r['material']}   首次 {r['首次']}")
    if not q: print("  (空 —— 还没有人问到没依据的格子)")
