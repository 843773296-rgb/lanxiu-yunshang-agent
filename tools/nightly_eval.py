#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜里自动把全套评测跑一遍(用户 2026-10-14 拍:「等晚上没有安排活的时候自动跑」)。

    python3 tools/nightly_eval.py            # 定时任务调的就是这个(每天 0 点)
    python3 tools/nightly_eval.py --试 2     # 白天手动试:只跑前 2 套,不看时间窗

## 为什么要跑

10-07 之后加了一批功能(工具 82 → 93、提示词 100 → 130 KB),而能力评测大多停在 10-07 ~ 10-11。
**「加一个工具的代价不在那个工具上,在此后每一次调用上」**(CLAUDE.md 第 3 节)——
能力没变而负担变重,就是退步,而它在功能清单上看不出来。

## 几条刻意的设计

  ① **只在夜里跑**:0 点起(用户 10-14 拍);04:30 后不开新的一套,04:55 前强停 —— 05:10 是每日世界平移,
     平移中途被评测读到的是平移到一半的库。笔记本睡着错过了、醒来已经过了 05:00 → **今晚不跑**,
     不在白天补(白天跑会和人抢库窗口)。
  ② **有人在用就让开**:门禁在跑、重建在跑 → 整晚不跑,日志里写为什么。
  ③ **一律 Claude Haiku**(CLAUDE.md 第 4 节:评测一律用 Claude;不指定模型会因凭证不同跑出别的模型)。
  ④ **不提交、不推送**:结果只落本地(各评测自己的 results.jsonl + 一份夜报),
     第二天有人看过再提交 —— 自动推送是对外动作。
  ⑤ 两个时间戳:`nightly-eval-tried`(干活之前记)/ `nightly-eval-ok`(全套跑完才记)——
     「任务没在跑」和「在跑但每次失败」分得开(同 daily_shift.sh)。
  ⑥ 每套单独限时,一套卡死不拖垮整晚;**崩了 / 超时 / 判红分开记** —— 三种在「没过」上长得一模一样。
  ⑦ **开跑前断言走的是 Claude 月租**(钥匙串登录态 claude-oauth + Haiku),不是就整晚不跑、日志告警。
     `v1.provider()` 的路取决于环境里有什么凭证:有 ANTHROPIC_API_KEY 就走**按量计费**,
     而 launchd 的环境和交互 shell 不是一套 —— 23 套 × 每天 × 自动,走错一天都发现不了,账单一直走。
     所以传给评测的环境**剥掉所有按量计费的凭证变量**,再用同一个环境真问一次 provider(数据工厂 10-14 提醒)。
  ⑨ **开跑前真调一次模型,不只问「配的是哪条路」**(2026-10-16 补)。10-16 那晚 ⑦ 绿着(配置确实是 claude-oauth + Haiku),
     而每一次调用都被拒:「Failed to authenticate. API Error: 403」—— 24 套全 0 分、一分钱没花,其中 17 套还记成「过」
     (脚本没崩、退出码 0)。白天同一台机器调用正常,夜里后台任务登录不上(多半是锁屏后读不到钥匙串)。
     > 一个「配的是对的路」和一个「这条路走得通」,在 ⑦ 那条检查上长得一模一样。
     所以:开跑前用评测同一个环境真问一句,不通就整晚不跑;每套跑完再看输出里有没有认证失败,有就记「没跑成」,不记「过」。
  ⑧ **夜跑的分数不进基线文件**:每套跑完,把它往 agent/*.jsonl、agentsite/evals/*.jsonl 里新增的内容
     挪到 `agent/nightly/`,原文件**恢复原样**。基线是从那些文件读的 —— 人工基线曾被一轮
     用错模型的结果盖过(CLAUDE.md 第 4 节)。「不提交」不够:文件已经被改了,而基线是读文件的。
"""
import datetime as dt, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
FEY = os.path.join(ROOT, ".feynman")
LOG = os.path.join(FEY, "nightly-eval.log")
TRIED = os.path.join(FEY, "nightly-eval-tried")
OK = os.path.join(FEY, "nightly-eval-ok")
报告目录 = os.path.join(FEY, "nightly-eval")

窗口开始, 不开新的, 强停 = dt.time(0, 0), dt.time(4, 30), dt.time(4, 55)   # 0 点开跑:用户 10-14 拍「放在12点跑」
每套上限分钟 = 25
# 先跑最能回答「能力变没变」的两套,其余按名字
先跑 = [("gen_compare.py", []), ("tool_eval.py", [])]
额外参数 = {"scheme_eval.py": ["--run"]}


def 说(*a):
    os.makedirs(FEY, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {' '.join(map(str, a))}\n")


def 有人在用():
    if os.path.exists(os.path.join(ROOT, "backend", ".rebuilding")):
        return "有重建在跑(backend/.rebuilding)"
    r = subprocess.run(["pgrep", "-f", "check.sh"], capture_output=True, text=True)
    if r.stdout.strip():
        return "有门禁在跑(check.sh)"
    return None


def 清单():
    套 = list(先跑)
    已 = {x for x, _ in 套}
    for f in sorted(os.listdir(os.path.join(ROOT, "agent"))):
        if f.endswith("_eval.py") and f not in 已:
            套.append((f, 额外参数.get(f, [])))
    return 套


按量计费的凭证 = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
要的路 = ("claude-oauth", "claude-haiku-4-5")


def 评测环境():
    env = {k: v for k, v in os.environ.items() if k not in 按量计费的凭证}
    env.update(LANXIU_PROVIDER="claude", ANTHROPIC_MODEL="claude-haiku-4-5", PYTHONDONTWRITEBYTECODE="1")
    return env


认证失败 = re.compile(r"Failed to authenticate|API Error: 40[13]|Invalid API key|Please run /login")


def 真问一句():
    """用**评测同一个环境**真调一次模型(走 Claude Code 命令行 —— 评测的 SDK 底下就是它)。返回 (通不通, 说明)。"""
    try:
        r = subprocess.run(["claude", "-p", "只回复两个字:正常", "--model", 要的路[1]], cwd=ROOT, env=评测环境(),
                           capture_output=True, text=True, timeout=120)
    except Exception as e:                                                   # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"[:160]
    出 = (r.stdout + r.stderr).strip()
    if r.returncode == 0 and "正常" in r.stdout and not 认证失败.search(出):
        return True, "真调一次通了"
    return False, 出[-160:] or f"退出码 {r.returncode}"


def 走的哪条路():
    """用**评测同一个环境**真问一次 v1.provider() —— 返回 (id, 模型) 或报错文本。"""
    r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0,'agent'); import v1; p=v1.provider();"
                        " print(p['id'], p['model'])"], cwd=ROOT, env=评测环境(),
                       capture_output=True, text=True, timeout=60)
    return tuple(r.stdout.split()) if r.returncode == 0 else ("出错", (r.stderr or r.stdout).strip()[-120:])


基线目录 = ("agent", os.path.join("agentsite", "evals"))


def 拍快照():
    快 = {}
    for d in 基线目录:
        for f in os.listdir(os.path.join(ROOT, d)):
            if f.endswith(".jsonl"):
                p = os.path.join(ROOT, d, f)
                with open(p, "rb") as h:
                    快[p] = h.read()
    return 快


def 挪走夜跑的(快, 名):
    """把这一套往基线文件里加的东西挪到 agent/nightly/,原文件恢复原样。返回挪了哪些。"""
    挪 = []
    夜 = os.path.join(ROOT, "agent", "nightly")
    for d in 基线目录:
        for f in os.listdir(os.path.join(ROOT, d)):
            p = os.path.join(ROOT, d, f)
            if not f.endswith(".jsonl"):
                continue
            with open(p, "rb") as h:
                现 = h.read()
            旧 = 快.get(p)
            if 现 == 旧:
                continue
            os.makedirs(夜, exist_ok=True)
            去 = os.path.join(夜, os.path.relpath(p, ROOT).replace(os.sep, "__"))
            新增 = 现[len(旧):] if 旧 is not None and 现.startswith(旧) else 现
            with open(去, "ab") as h:
                h.write(新增)
            if 旧 is None:
                os.remove(p)
            else:
                with open(p, "wb") as h:
                    h.write(旧)
            挪.append(os.path.relpath(p, ROOT) + ("" if 旧 is not None and 现.startswith(旧) else "(整个改写了)"))
    if 挪:
        说(f"    {名} 写了基线文件,已挪到 agent/nightly/ 并恢复原样:{'、'.join(挪)}")
    return 挪


def 跑一套(名, 参数, 截止):
    env = 评测环境()
    限 = max(60, min(每套上限分钟 * 60, int((截止 - dt.datetime.now()).total_seconds())))
    t0 = time.time()
    try:
        r = subprocess.run([PY, os.path.join("agent", 名), *参数], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=限)
        尾 = [x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip()][-3:]
        # 跑到一半登录掉了也算(开跑前那一问只证明开跑那一刻通)—— 输出里有认证失败就是**没跑成**,
        # 不记「过」:那套题一道都没真答,退出码 0 只说明脚本没崩(10-16 那晚 17 套就是这么「过」的)
        结 = "没跑成(认证失败)" if 认证失败.search(r.stdout + r.stderr) else ("过" if r.returncode == 0 else "判红")
        return dict(套=名, 结果=结, 退出码=r.returncode, 分钟=round((time.time() - t0) / 60, 1), 尾=尾)
    except subprocess.TimeoutExpired:
        return dict(套=名, 结果="超时", 退出码=None, 分钟=round((time.time() - t0) / 60, 1), 尾=[f"超过 {限 // 60} 分钟被停"])
    except Exception as e:                                                   # noqa: BLE001
        return dict(套=名, 结果="崩了", 退出码=None, 分钟=round((time.time() - t0) / 60, 1), 尾=[f"{type(e).__name__}: {e}"])


def main():
    试 = "--试" in sys.argv
    只跑 = int(sys.argv[sys.argv.index("--试") + 1]) if 试 and len(sys.argv) > sys.argv.index("--试") + 1 else None
    现在 = dt.datetime.now()
    if not 试 and not (窗口开始 <= 现在.time() < 不开新的):
        说(f"跳过:现在 {现在:%H:%M} 不在夜里的窗口({窗口开始:%H:%M}–{不开新的:%H:%M})—— 多半是笔记本睡着、醒来补跑,白天不跑")
        return 0
    谁 = 有人在用()
    if 谁:
        说(f"跳过:{谁} —— 今晚整晚不跑")
        return 0
    if not os.path.exists(PY):
        说(f"❌ 没有 {PY}(要先 ./start.sh 建 venv)")
        return 1
    路 = 走的哪条路()
    if 路 != 要的路:
        说(f"❌ **整晚不跑**:评测环境走的是 {路},要的是 {要的路}(Claude 月租 + Haiku)。"
           f"走错一天就是一天的按量账单,而定时任务的失败默认没人看 —— 人来查这一行")
        return 1
    通, 话 = 真问一句()
    if not 通:
        说(f"❌ **整晚不跑**:配置是对的({路}),可真调一次模型不通 —— {话}。"
           f"不跑是为了不造出 24 套「全 0 分」的假结果;这**不是能力 0 分**,是登录不上(多半是锁屏后后台读不到钥匙串)")
        return 1
    with open(TRIED, "w") as f:
        f.write(f"{现在:%Y-%m-%dT%H:%M:%S}\n")
    截止 = dt.datetime.combine(现在.date(), 强停) if not 试 else 现在 + dt.timedelta(hours=3)
    套们 = 清单()[: 只跑] if 只跑 else 清单()
    说(f"开始:{len(套们)} 套{'(试跑)' if 试 else ''}")
    结果 = []
    for 名, 参数 in 套们:
        if not 试 and dt.datetime.now().time() >= 不开新的:
            结果.append(dict(套=名, 结果="没开(过了 04:30)", 退出码=None, 分钟=0, 尾=[]))
            continue
        谁 = 有人在用()
        if 谁:
            结果.append(dict(套=名, 结果=f"没开({谁})", 退出码=None, 分钟=0, 尾=[]))
            continue
        快 = 拍快照()
        r = 跑一套(名, 参数, 截止)
        r["挪走"] = 挪走夜跑的(快, 名)
        结果.append(r)
        说(f"  {名}:{r['结果']}({r['分钟']} 分钟)")
    os.makedirs(报告目录, exist_ok=True)
    报 = os.path.join(报告目录, f"{现在:%Y-%m-%d}.md")
    计 = {}
    for r in 结果:
        计[r["结果"]] = 计.get(r["结果"], 0) + 1
    with open(报, "w", encoding="utf-8") as f:
        f.write(f"# 夜间评测 · {现在:%Y-%m-%d %H:%M}\n\n")
        f.write("模型:claude-haiku-4-5 · **没提交没推送**,看过再提交(各评测的分数在 agent/*-results.jsonl 末行)\n\n")
        f.write(" · ".join(f"{k} {v}" for k, v in 计.items()) + "\n\n")
        f.write("| 套 | 结果 | 分钟 | 最后几行 |\n|---|---|---|---|\n")
        for r in 结果:
            f.write(f"| {r['套']} | {r['结果']} | {r['分钟']} | {' / '.join(x[:80] for x in r['尾']).replace('|', '¦')} |\n")
    全跑完 = all(r["结果"] in ("过", "判红") for r in 结果)
    if 全跑完:
        with open(OK, "w") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S}\n")
    说(f"结束:{json.dumps(计, ensure_ascii=False)} → {os.path.relpath(报, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
