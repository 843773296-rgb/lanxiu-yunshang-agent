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

# ── 明写的例外 —— **排掉一个是个决定,漏掉一个是个事故** ─────────────────
#
# ⚠️ 每一条都要写清**为什么**,而且理由要是「它不是调用点」,
# 不是「它让门禁红了」。后一种理由等于把判据改松。
明写不算调用点 = {
    "管理后台/tests/e2e/test_exec_mode_flow.py":
        ("夹具里有一个 `http://127.0.0.1:9/v1/messages`(本机 discard 口,"
         "用来证明「真实调用失败不退回 mock」)—— 那是**夹具字符串,不是调用点**。"
         "真调用走 `runtime/真模型.py`,**那里接了记录仪**,"
         "所以这个文件属于这份文件头说的"
         "「调用别人封装好的 run() 的文件,不算 call site」那一类。"),
}

# 真正发起调用的指纹
CALL = [
    (re.compile(r"^\s*(?:async\s+)?for\s+\w+\s+in\s+query\s*\(", re.M), "调 Agent SDK 的 query()"),
    (re.compile(r"(?<!def )\bquery\s*\(\s*prompt\s*="), "调 Agent SDK 的 query(prompt=...)"),
    (re.compile(r"api\.deepseek\.com|api\.anthropic\.com|/v1/messages"), "直接打模型 API 端点"),
]

# ── 2026-10-03 放宽:**端点是从库里取的那种调用点,上面那条指纹看不见** ──────
#
# 并行会话报「这条判据红在一个测试文件上」,而真相更糟:
# `管理后台/services/api/app/runtime/真模型.py` 才是真正的调用点,
# 而它**对这条判据是隐形的** —— 它的端点来自模型连接那张表,
# 源码里一个 URL 都没有,所以上面那条「有没有端点字面量」的指纹扫不到它。
# 点中的那个测试文件只是因为夹具里写了一个 `http://127.0.0.1:9/v1/messages`。
#
# > **一个发现不了真正调用点、而点中了一个夹具字符串的探测器,
# > 和一个正确的,在那条红上长得一模一样。**
#
# 新指纹:**curl + 凭据定位符 + `-X POST`** —— 也就是
# 「带着凭据往外发一个 POST」。
#
# ⚠️ **放宽前先量过**(这个仓库放宽探测器的规矩):
#   · 先用宽版(curl + Authorization/x-api-key + POST)量 → 扫出 4 个,
#     其中 `tools/feishu_publish.py` 是**误报**(发飞书,不是模型)
#   · 收紧到「凭据定位符」(`secretref` / `SR.解析`)→ **正好 2 个**,
#     误报消失:`runtime/真模型.py`(已接)和
#     `connections_api.py`(**真漏** —— 连接探测真发请求而没记,当天补上了)
#   · 所以这次放宽**没有带进任何欠债**,不需要欠债表
# ⚠️⚠️ **用前瞻写成「两个条件都满足」,而不是 `"curl".*?secretref`。**
# 第一版就是后者 —— 它要求凭据**出现在 curl 之后**,而
# `runtime/真模型.py` 是先 `import secretref` 再用 curl,于是**它仍然是隐形的**。
# 当时判据是绿的(它扫到了另一个文件),而我要抓的那个根本没进名单。
# > 一个顺序相关的指纹,在「它扫到了别的文件、结果是绿的」时**看起来完全正常**。
# ⚠️⚠️⚠️ **前瞻必须锚在 `\\A` 上** —— 2026-10-09 这条判据把 CI 的主门禁挂死了 8 分钟,
# 直到 job 撞上 `timeout-minutes: 20` 被掐。表现是 CI 里一条 `cancelled`,
# 而 `cancelled` 和「新 push 把旧 run 掐掉了」**在 run 列表上长得一模一样**。
#
# 没锚点的 `search()` 会在**每一个起始位置**重试一遍;而 `(?s).*` 在
# 文件里不含那个字面量时,每次都要回溯扫完全文 —— 代价 O(n²)。
# 实测:`knowledge/reranker.py`(1.3 万字)约 20 秒,
# `backend/api.py`(28.8 万字)约 3 小时。
#
# > **它是跟着 `backend/api.py` 长大才引爆的** —— 加进来那天文件还小,
# > 一个 O(n²) 的判据和一个正常的判据,在小文件上长得一模一样。
#
# 语义上「全文同时满足两个条件」只需在位置 0 判一次,所以加 `\\A` 不改语义。
# 验过:全仓 656 个 py,加锚点后命中集合与直接写
# `'"curl"' in src and ('secretref' in src or 'SR.解析(' in src)` **完全一致**,
# 都正好是上面注释里说的那 2 个;全仓扫完 0.07 秒。
CALL += [
    (re.compile(r'(?s)\A(?=.*"curl")(?=.*(?:secretref|SR\.解析\())'),
     "带凭据往外发 POST"),
]
# 认「接了记录仪」要同时满足两条:导入了 trace 模块 + 调了 record()。
# 第一版只认字面的 `trace.record(`,结果把 `import trace as _trace` 的
# agent/v1.py 误报成没接 —— **和评测锚点同义词写窄了是同一类错**:
# 指纹按自己的写法定,而别人换个写法就漏了。
# ⚠️ 模块 2026-09-27 从 `trace` 改名成 `llmtrace` —— 和 Python 标准库的 `trace` 同名,
# 谁先 import 标准库那个,后面 `import trace` 就拿不到记录仪(实测:AttributeError,
# 而且只在某些 import 顺序下出现)。**旧名字也继续认**:
# 管理后台那边用的是自己那份、名字还叫 trace,而这条检查扫的是整个仓库。
IMPORT_TRACE = re.compile(r"^\s*(?:import\s+(?:llm)?trace\b|from\s+(?:llm)?trace\s+import|"
                          r"from\s+\.?\s*(?:llm)?trace\s+import)", re.M)
CALL_RECORD = re.compile(r"\.record\s*\(|(?<![\w.])record\s*\(")


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把 V1 里那句记录仪调用改名(调用点还在,记录仪没接上)',
     '有调用点没接记录仪'),
    ('把 IMPORT_TRACE 正则里的 (?:llm)? 去掉(改名之后它认不出记录仪了)',
     '有调用点没接记录仪'),
    ('把记录仪模块改回和标准库同名(判据去查 trace 而不是 llmtrace)',
     '最坏 import 顺序下'),
]


def 不和标准库撞名():
    """记录仪模块**不许和 Python 标准库同名**,而且要在最坏的 import 顺序下拿得到。

    2026-09-27:它本来叫 `agent/trace.py`,和标准库的 `trace`(跟踪代码执行那个)同名。
    实测:标准库那个先进 `sys.modules` 之后,`import trace` **拿到的还是标准库那个**,
    `trace.record(...)` 变成 `AttributeError` ——
    而触发条件是**别人的 import 顺序**(覆盖率工具 / profiler / 某个依赖顺手 import)。

    > **坏掉的后果特别贵:记录仪失灵 = 所有调模型的花费变成黑的。**
    > 而那是这个项目归因成本的唯一工具(V3 成本涨 38% 就是靠它照出来的)。

    判据不是「文件名对不对」,是**真的按最坏顺序 import 一遍,看拿到的有没有 record** ——
    只查名字的话,哪天有人加一个新的同名模块照样漏。
    """
    import subprocess, sys as _s
    码 = ("import sys, trace\n"                     # 先把标准库那个拉进来
          "sys.path.insert(0, %r)\n" % os.path.join(ROOT, "agent") +
          "import llmtrace\n"
          "assert hasattr(llmtrace, 'record'), '拿到的不是记录仪:' + llmtrace.__file__\n"
          "print('OK', llmtrace.__file__)\n")
    r = subprocess.run([_s.executable, "-c", 码], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-200:]

def traced(src):
    return bool(IMPORT_TRACE.search(src) and CALL_RECORD.search(src))


def scan():
    免 = []
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
            # ⚠️ **明写的例外单独列出来,不静默跳过。**
            # 静默跳过的话,这个清单会慢慢变成一个没人记得的洞 ——
            # 而「它被排掉了」和「它从来没被扫到」在输出上长得一样。
            if rel in 明写不算调用点:
                免.append((rel, hits, 明写不算调用点[rel]))
                continue
            sites.append((rel, hits))
            (ok if traced(src) else bad).append((rel, hits))
    return sites, ok, bad, 免


if __name__ == "__main__":
    print("记录仪覆盖检查\n" + "=" * 76)
    sites, ok, bad, 免 = scan()
    for rel, hits, 为什么 in 免:
        # ⚠️ 例外**印出来**,而且连理由一起印 —— 不印的话这个清单会变成
        # 一个没人记得的洞,而「它被排掉了」和「它从来没被扫到」在输出上长得一样。
        print(f"  ⏸ {rel}  {'、'.join(hits)} —— **明写不算调用点**")
        print(f"       {为什么}")
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
    # ── 记录仪模块本身拿不拿得到(和标准库撞名的话拿不到)──────────────
    好, 说 = 不和标准库撞名()
    print(f"  {'✅' if 好 else '❌'} 最坏 import 顺序下(标准库 trace 先进)仍然拿得到记录仪"
          f"  {说}")
    if not 好:
        print("=" * 76)
        print("❌ 记录仪被同名模块挡住了。**记录仪失灵 = 所有调模型的花费变成黑的**,"
              "而它只在某些 import 顺序下发作。")
        sys.exit(1)
    print("=" * 76)
    print("✅ 每个调模型的地方都接了记录仪")
