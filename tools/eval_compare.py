#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两家供应商的评测横向对比 —— **同一份代码、同一天跑出来的才算数。**

## 为什么要单独写这个

上一次对比表出过一个错,写在 `CLAUDE.md` 第 3 节里:成本那一栏用的是
记录仪里的**累计均价**,而它会被后来的调用稀释 ——
**两次对比表之间根本不可比**。

这次的风险是另一个:**两列不同源**。
DeepSeek 这一轮是今天跑的,而库里存着的 Claude 结果是几天前的,
中间工具变了(新增 kb_read / pattern_queue / grading_audit)、
规矩变了(TL25–TL27)、体检加了一条。
拿这两列并排,差出来的是**那几天的改动**,不是两家模型的差别。

> **一次动了多维就归不了因** —— 这个项目为这句话立过规矩,
> 那么并排两列数之前,先确认它们只差一维。

所以这个脚本**强制两边都带时间戳**,并且在表下面把「这两列是不是同源」
打印出来。不同源的时候它照样出表,**但会把结论那一行换成一句警告** ——
不出表的话人会去手抄,手抄比不可比更糟。

用法:
    LANXIU_PROVIDER=deepseek ./tools/run_evals.sh /tmp/evals-deepseek
    LANXIU_PROVIDER=claude   ./tools/run_evals.sh /tmp/evals-claude
    python3 tools/eval_compare.py /tmp/evals-deepseek /tmp/evals-claude
"""
import os, re, sys, datetime

# 两种打分行:多数套是「通过 x/y」,chat_eval 打的是「总命中 x/y」。
# **这个坑 run_evals.sh 里已经踩过一次** —— 只认前者的话 chat_eval 永远抓不到分。
分数行 = re.compile(r"^(?:通过|总命中)\s+(\d+)\s*/\s*(\d+)")
花费行 = re.compile(r"(?:花费|成本)\s*\$([\d.]+)")


def 读(d):
    out = {}
    if not os.path.isdir(d): return out
    for f in sorted(os.listdir(d)):
        if not f.endswith(".txt"): continue
        name = f[:-4]
        t = open(os.path.join(d, f), encoding="utf-8", errors="ignore").read()
        过 = 总 = None
        for line in t.split("\n"):
            m = 分数行.match(line.strip())
            if m: 过, 总 = int(m.group(1)), int(m.group(2))
        cost = sum(float(x) for x in 花费行.findall(t)[-1:]) or None
        mt = datetime.datetime.fromtimestamp(
            os.path.getmtime(os.path.join(d, f))).strftime("%m-%d %H:%M")
        # **抓不到分数要显式说「抓不到」,不许当成 0** ——
        # 一套跑挂了和一套考了 0 分,在表上长得一模一样。
        out[name] = dict(过=过, 总=总, cost=cost, 时间=mt)
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    A, B = sys.argv[1], sys.argv[2]
    a, b = 读(A), 读(B)
    na, nb = os.path.basename(A.rstrip("/")), os.path.basename(B.rstrip("/"))
    套 = sorted(set(a) | set(b))
    if not 套:
        print("两个目录里一套结果都没有 —— **这不叫打平,这叫没跑**"); return 1

    print(f"评测横向对比:{na}  vs  {nb}")
    print("=" * 92)
    print(f"{'套':22}{na:>22}{nb:>22}   差")
    print("-" * 92)
    ca = cb = 0.0
    for s in 套:
        x, y = a.get(s), b.get(s)
        def 格(v):
            if not v: return "(没跑)"
            if v["过"] is None: return "**抓不到分**"
            return f"{v['过']}/{v['总']}"
        d = ""
        if x and y and x["过"] is not None and y["过"] is not None and x["总"] == y["总"]:
            k = x["过"] - y["过"]
            d = f"{k:+d}" if k else "持平"
        elif x and y and x["总"] != y["总"]:
            d = "⚠️ 题数不同,不可比"
        print(f"{s:22}{格(x):>22}{格(y):>22}   {d}")
        ca += (x or {}).get("cost") or 0
        cb += (y or {}).get("cost") or 0
    print("-" * 92)
    print(f"{'花费合计':22}{'$%.4f' % ca:>22}{'$%.4f' % cb:>22}")

    # ── 同源判定:两列是不是同一份代码、同一天跑的 ────────────────────
    ta = sorted(v["时间"] for v in a.values() if v)
    tb = sorted(v["时间"] for v in b.values() if v)
    print()
    print(f"  {na} 跑于 {ta[0] if ta else '?'} – {ta[-1] if ta else '?'}")
    print(f"  {nb} 跑于 {tb[0] if tb else '?'} – {tb[-1] if tb else '?'}")
    同日 = bool(ta and tb and ta[0][:5] == tb[0][:5])
    print()
    if 同日:
        print("  ✅ 两列同一天跑的 —— 差出来的可以当成**两家模型的差别**来读,")
        print("     但仍然要带上那三条限定:题数小、各跑一遍、两家的提示词是同一份"
              "(**对谁都不是专门调过的**)。")
    else:
        print("  ⚠️ **两列不是同一天跑的,这张表不能当结论。**")
        print("     中间只要动过工具、规矩或体检,差出来的就是那些改动,不是模型的差别。")
        print("     **一次动了多维就归不了因** —— 要出结论,拿同一份代码把另一家重跑一遍。")
    抓不到 = [s for s in 套 for v in (a.get(s), b.get(s)) if v and v["过"] is None]
    if 抓不到:
        print(f"\n  ⚠️ {sorted(set(抓不到))} 抓不到分数 —— "
              f"**这不是 0 分,是没抓到**,去看那一套的输出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
