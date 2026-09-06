#!/usr/bin/env python3
"""提示词单一源头检查。

这个检查是补票买的。发现时的实况:同一个「后台人工任务助手」角色有 **3 份**
提示词(agent/v1.py 4 条铁律、agentsite/sdk.py 6 条、agent/chat.py 是另一个角色的 6 条),
互相之间漂了很久:

  · **评测跑的是 chat.py 那份,给出的分数评的不是产品**;
  · 三代对比里 V1 少带了「客户合并判定标准」——
    而那条是有实测的:不给 0/2,给了 2/2。V1 是少带一条已知能加分的规矩上的场。

一份手抄件不会自己告诉你它旧了。所以这里查四件事。
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "backend"))
import prompts, api

bad = []
def rule(no, desc, rows, why):
    print(f"  {'✅' if not rows else '❌'} {no}  {desc}")
    for r in rows[:6]: print(f"        · {r}")
    if rows: bad.append((no, why, len(rows)))

# ── P1:唯一源头 ────────────────────────────────────────────────────
# 角色开场白拼出来,**不写成一个完整字面量** —— 否则这个文件自己会被扫中。
# (密钥扫描在同一个坑里栽过四次:规则字符串写进被扫文件,自己匹配自己。)
OPEN = "你是澜绣" + "云裳"
SRC_OK = {"prompts.py", "prompts_check.py"}
hits = []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in (".git", ".venv", "__pycache__", "node_modules")]
    for fn in fns:
        if not fn.endswith(".py") or fn in SRC_OK: continue
        fp = os.path.join(dp, fn)
        src = open(fp, encoding="utf-8").read()
        for m in re.finditer(r'^([A-Za-z_]\w*)\s*=\s*"""(.*?)"""', src, re.S | re.M):
            if OPEN in m.group(2):
                n = len([l for l in m.group(2).splitlines() if re.match(r"^\d+\. ", l)])
                hits.append(f"{os.path.relpath(fp, ROOT)}:{m.group(1)}(铁律 {n} 条)")
rule("P1", "提示词只能有一处定义", hits,
     "手抄件不会自己告诉你它旧了 —— 要么 import prompts,要么它迟早和产品对不上")

# ── P2:needs / avoid 里的工具名必须真实存在 ────────────────────────
REAL = set(api.TOOLS) | {"图片", "submit_finding"}
ghost = [f"{r.id} 依赖 {n}(不存在这个工具)"
         for _, r in prompts.all_rules() for n in r.needs + r.avoid if n not in REAL]
rule("P2", "铁律依赖的工具必须真实存在", ghost,
     "工具名打错了不会报错,只会让那条铁律**永远装不上** —— 静默失效")

# ── P3:每条铁律至少被一个真实调用方装上 ────────────────────────────
# 调用方的工具清单从源码里取(不 import sdk:它要 claude_agent_sdk,没装就跑不了)。
SDK = open(os.path.join(ROOT, "agentsite", "sdk.py"), encoding="utf-8").read()
def wl(name):
    m = re.search(rf"^{name} = \[(.*?)\]", SDK, re.S | re.M)
    return {t.rsplit("__", 1)[-1] for t in re.findall(r'"([^"]+)"', m.group(1))} if m else set()
KB, SHOP, TASK = wl("KB_TOOLS"), wl("SHOP_TOOLS"), wl("TASK_TOOLS")
KBSET = {t["name"] for t in api.KB_SCHEMAS}
CALLERS = {
    "工作站·工艺顾问(sdk)":   ("kb",   KB | SHOP | {"图片"}),
    "工作站·任务助手(sdk)":   ("task", TASK | SHOP),
    "后台聊天(chat.py)":      ("kb",   KBSET),
    "一代任务循环(v1.py)":    ("task", {t["name"] for t in api.SCHEMAS} | {"submit_finding"}),
}
used = set()
print()
for nm, (role, have) in CALLERS.items():
    _, ids = prompts.assemble(role, have)
    used |= set(ids)
    print(f"     {nm:26s} {len(ids):2d} 条  {' '.join(ids)}")
print()
orphan = [f"{r.id}(需要 {r.needs or '—'},没有任何调用方满足)"
          for _, r in prompts.all_rules() if r.id not in used]
rule("P3", "每条铁律至少要有一个调用方装得上", orphan,
     "装不上的铁律等于不存在,而它看起来一直好好地躺在源码里 —— "
     "和「没有用例的规则」是同一个病")

# ── P4:稳定编号不得重复 ────────────────────────────────────────────
ids = [r.id for _, r in prompts.all_rules()]
dup = [f"{i} 出现 {ids.count(i)} 次" for i in sorted(set(ids)) if ids.count(i) > 1]
rule("P4", "稳定编号唯一", dup, "编号撞了,外部文档引用的就不知道是哪一条")

print("\n" + "=" * 84)
if bad:
    print(f"❌ {len(bad)} 条没守住:")
    for no, why, n in bad: print(f"   · {no}({n} 条):{why}")
    sys.exit(1)
print(f"✅ 提示词单一源头(P1–P4)· 共 {len(ids)} 条铁律,{len(CALLERS)} 个调用方")
