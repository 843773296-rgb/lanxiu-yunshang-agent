#!/usr/bin/env python3
"""记录仪覆盖检查 —— 断言「每一个真正调模型的地方,都接了记录仪」。

## 为什么需要这个检查

这个项目栽过一次:从手写循环升到 Agent SDK 之后,**新那条路径一行日志都没记**。
`.feynman/llm-trace.jsonl` 停在升代那天,而且**不报错** ——
文件还在、还能打开、里面还有数据,只是日期不动了。
不特意去看时间戳,根本发现不了。

> **可观测性不会自动跟着架构走。** 换一代架构,记录仪要重新接一次。
> 而这件事没人会提醒你,因为漏了它的表现是「一切正常」。

所以把它变成一条结构检查:**新增任何一个调模型的地方,忘了接记录仪就红。**

## 什么算「调模型的地方」

只认真正发起调用的那一行,不认「用了 SDK 的类型」:
  · 调 claude_agent_sdk 的 query(...)
  · 往模型 API 端点发 HTTP(/v1/messages、api.deepseek.com、api.anthropic.com)

只是 import 了 HookMatcher、或者调用别人封装好的 run() 的文件,**不算**call site ——
它们不需要自己记,上游记过了。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP = (".git", ".venv", "__pycache__", "node_modules")

# 真正发起调用的指纹
CALL = [
    (re.compile(r"^\s*(?:async\s+)?for\s+\w+\s+in\s+query\s*\(", re.M), "调 Agent SDK 的 query()"),
    (re.compile(r"(?<!def )\bquery\s*\(\s*prompt\s*="), "调 Agent SDK 的 query(prompt=...)"),
    (re.compile(r"api\.deepseek\.com|api\.anthropic\.com|/v1/messages"), "直接打模型 API 端点"),
]
# 认「接了记录仪」要同时满足两条:导入了 trace 模块 + 调了 record()。
# 第一版只认字面的 `trace.record(`,结果把 `import trace as _trace` 的
# agent/v1.py 误报成没接 —— **和评测锚点同义词写窄了是同一类错**:
# 指纹按自己的写法定,而别人换个写法就漏了。
IMPORT_TRACE = re.compile(r"^\s*(?:import\s+trace\b|from\s+trace\s+import|"
                          r"from\s+\.?\s*trace\s+import)", re.M)
CALL_RECORD = re.compile(r"\.record\s*\(|(?<![\w.])record\s*\(")


def traced(src):
    return bool(IMPORT_TRACE.search(src) and CALL_RECORD.search(src))


def scan():
    sites, ok, bad = [], [], []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"): continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ROOT)
            if rel.endswith("trace_check.py"): continue          # 别把自己算进去
            src = open(p, encoding="utf-8", errors="ignore").read()
            hits = [why for rx, why in CALL if rx.search(src)]
            if not hits: continue
            sites.append((rel, hits))
            (ok if traced(src) else bad).append((rel, hits))
    return sites, ok, bad


if __name__ == "__main__":
    print("记录仪覆盖检查\n" + "=" * 76)
    sites, ok, bad = scan()
    for rel, hits in sites:
        good = any(r == rel for r, _ in ok)
        print(f"  {'✅' if good else '❌'} {rel:28s} {'、'.join(hits)}")
        if not good:
            print(f"       **这里调了模型但没有 trace.record** —— 这条路径的花费和耗时是黑的")
    print(f"\n共 {len(sites)} 处调用点,接了记录仪 {len(ok)} 处")
    if not sites:
        print("❌ 一处调用点都没识别出来 —— 指纹八成写错了,这个检查等于没有"); sys.exit(1)
    if bad:
        print("=" * 76)
        print("❌ 有调用点没接记录仪。**换架构最容易漏的就是这一步**,而漏了不会报错。")
        sys.exit(1)
    # 顺带看一眼日志里两代都在不在 —— 接了但从来没跑过,等于也没有
    log = os.path.join(ROOT, ".feynman", "llm-trace.jsonl")
    if os.path.exists(log):
        import json
        gens = {}
        for line in open(log, encoding="utf-8"):
            try: r = json.loads(line)
            except Exception: continue
            g = r.get("gen", "V1")
            gens[g] = max(gens.get(g, ""), r.get("ts", ""))
        print("  日志里各代最后一条:", {k: v for k, v in sorted(gens.items())})
        if len(gens) < 2:
            print("  ⚠ 只有一代有记录 —— 另一代接了但没跑过,横向对比还做不了")
    print("=" * 76)
    print("✅ 每个调模型的地方都接了记录仪")
