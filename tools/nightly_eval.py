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
# 按白天真跑的时长单独给(10-16):商机一套 41 分钟;运营 68 题×两轮,60 分钟跑不完,约 2 个多小时
单独上限分钟 = {"oppo_eval.py": 50, "ops_eval.py": 150}
# ⚠️ 影子跑那一项的上限在下面 `先跑` 那段旁边定义(`单独上限分钟_补`),
# 跑完在这儿并进来 —— 放一起写会让那段长注释插在这张表中间,读不下去
# 运营 150 分钟 + 其余 23 套约 3 小时 40 分,一晚(0:00–4:55)放不下 ——
# 用户 10-17 拍「每周一晚单跑运营」:周日凌晨(周六晚那一轮)只跑它,其余六晚跑另外 23 套
单跑那晚 = {"ops_eval.py": 6}   # 套名 → 星期几(周一=0 … 周日=6)
# 先跑最能回答「能力变没变」的两套,其余按名字
先跑 = [("gen_compare.py", []), ("tool_eval.py", []),
        # ── 闸四影子运行(用户 2026-10-21 拍「装进夜跑,全自动」)────────────
        #
        # 它不是一套评测,是**每天把新来的、还没影子跑过的未处置差评跑一遍并落账**。
        # 放进夜跑而不是新立一个定时任务,因为夜跑已经解决了它最怕的三件事:
        #   · **占库排队** —— PID 文件 + 看有没有门禁 / 咬合在跑(`有人在用()`);
        #   · **过了 04:30 不开新的** —— 它一条要一两分钟,别压到早上;
        #   · 🔺 **认证掉了不记「过」** —— 输出里有认证失败就算没跑成。
        #     影子轨最怕的正是「跑了但其实没调到模型,却被记成正常样本」,
        #     而那条规矩直接兜住它。
        #
        # ⚠️ **新量轨只能靠时间攒**:2026-10-20 量的速率是 8 天 3 条 ≈ 0.4 条/天,
        # 所以每晚通常 0–1 条、经常是「库里没有没跑过的了」直接返回 0。
        # **那不是失败** —— `--跑` 在挑不到题时打印一句并退 0。
        # ⚠️ 条数给 3 不给大数:一晚最多补三条,免得哪天造数批量产差评时
        # 它在夜里跑上一个钟头、把别的评测挤掉(「过了 04:30 不开新的」只拦**开始**,
        # 不拦**已经开跑的那一套**)。
        ("triage_shadow.py", ["--跑", "3"])]
额外参数 = {"scheme_eval.py": ["--run"]}
# 影子跑一晚最多三条、每条一两分钟 —— 给 15 分钟够宽,又不至于占住一晚
单独上限分钟_补 = {"triage_shadow.py": 15}


单独上限分钟.update(单独上限分钟_补)


def 说(*a):
    os.makedirs(FEY, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {' '.join(map(str, a))}\n")


# ── 「谁在用库」用 PID 文件判,不按名字搜进程(2026-10-20 改)──────────────────────────
# 原来是 `pgrep -f bite_run` / `pgrep -f check.sh` —— 匹配的是**整条命令行**,于是一条
# `ps … | grep -E "check.sh|bite_run|nightly_eval"`(查占用的诊断命令)自己就触发了闸:
# 白天 9 点多 bite_run 报「夜跑评测正在跑」拒跑。和「规则写进文档 → 文档匹配自己」同一个形状,第四次。
# 现在照 `backend/.rebuilding` 那个现成范式:写 PID 文件、`os.kill(pid, 0)` 验活,残留的不算。
# ⚠️ 文件放在**真库所在的目录**(两个检出共用那一份库;`.feynman/` 每个检出各有一份,放那里互相看不见)
PID目录 = os.path.dirname(os.path.realpath(os.path.join(ROOT, "backend", "lanxiu.db")))
夜跑PID = os.path.join(PID目录, ".nightly-eval.pid")
重放PID = os.path.join(PID目录, ".bite-run.pid")


def 活着(pid文件):
    """PID 文件在、而且那个进程还活着 → True。文件在但进程早没了(崩了留下的)→ False。"""
    try:
        pid = int(open(pid文件).read().strip().split()[0])
        os.kill(pid, 0)
        return True
    except Exception:                                                        # noqa: BLE001
        return False


def 有人在用():
    if os.path.exists(os.path.join(ROOT, "backend", ".rebuilding")):
        return "有重建在跑(backend/.rebuilding)"
    # 门禁:只认**真正在跑 check.sh 的那个 bash 进程**(命令行以它开头),提到这个词的别的命令不算
    r = subprocess.run(["pgrep", "-f", r"^(/bin/)?(ba)?sh \./check\.sh"], capture_output=True, text=True)
    if r.stdout.strip():
        return "有门禁在跑(check.sh)"
    # ⚠️ **咬合重放也算有人在用**(2026-10-19 加)。它每条规格都要拷一份库、
    #    再在副本上跑一遍检查 —— 全量 756 条要四个多小时,CPU 和磁盘全程满载。
    #    原来这里只看 `check.sh`,于是一次跨进夜里的重放**不会被拦**,
    #    而今晚这一轮是全量 23 个评测、含三代对比 —— 那张表里的
    #    「耗时/条」会被拖慢,**然后作为本轮的度量进版本库**。
    #
    # > 一个「跑过了但数被别的活拖慢了」的评测结果,和一个干净的结果,
    # > **在那个 jsonl 里长得一模一样** —— 而它会被拿去和上一轮同模型的那次比。
    #
    #    让开的代价是「今晚没跑」,而那是**在日志里看得见**的;
    #    不让开的代价是一份看起来正常的假数。**两种代价不对等。**
    if 活着(重放PID):
        return f"有咬合重放在跑({os.path.basename(重放PID)})"
    return None


# ── 每晚都要跑的,不参与「单跑那晚」那套调度 ──────────────────────────
#
# ⚠️⚠️ 「单跑那晚」是为**评测**定的调度:一晚放不下 24 套,所以周日让运营独占。
# 而影子跑不是评测,是**每天该补的一条账** —— 它跟着那套规则走的后果是
# **一周漏一天**,而在 0.4 条/天 的速率下,一周漏一天等于把三个月拖成三个半月。
# > 一个「每天都在攒」的台账和一个「一周漏一天」的,**在那个条数上长得一模一样** ——
# > 只是慢,而慢不报错。
# (这是「把一件东西塞进现成清单」的典型代价:它跟着那张清单的规则走,
#  而那套规则是为别的东西定的。)
每晚都跑 = ("triage_shadow.py",)


def 清单(星期=None):
    星期 = dt.date.today().weekday() if 星期 is None else 星期
    _每晚 = [x for x in 先跑 if x[0] in 每晚都跑]
    单跑 = [(f, 额外参数.get(f, [])) for f, 哪天 in 单跑那晚.items() if 哪天 == 星期]
    if 单跑:
        # 单跑那晚也带上「每晚都跑」的 —— 它们放在前面,免得被运营那 150 分钟挤到 04:30 之后
        return _每晚 + 单跑
    套 = [x for x in 先跑 if x[0] not in 单跑那晚]
    已 = {x for x, _ in 套}
    for f in sorted(os.listdir(os.path.join(ROOT, "agent"))):
        if f.endswith("_eval.py") and f not in 已 and f not in 单跑那晚:
            套.append((f, 额外参数.get(f, [])))
    return 套


按量计费的凭证 = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
要的路 = ("claude-oauth", "claude-haiku-4-5")


def _系统代理():
    """读 macOS 系统代理(`scutil --proxy`)—— 只取地址和端口,不带账号密码,仓库里不留任何密钥。"""
    try:
        t = subprocess.run(["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, timeout=10).stdout
    except Exception:                                                        # noqa: BLE001
        return None
    值 = dict(re.findall(r"^\s*(\w+)\s*:\s*(\S+)", t, re.M))
    if 值.get("HTTPSEnable") == "1" and 值.get("HTTPSProxy") and 值.get("HTTPSPort"):
        return f"http://{值['HTTPSProxy']}:{值['HTTPSPort']}"
    return None


def 评测环境():
    env = {k: v for k, v in os.environ.items() if k not in 按量计费的凭证}
    env.update(LANXIU_PROVIDER="claude", ANTHROPIC_MODEL="claude-haiku-4-5", PYTHONDONTWRITEBYTECODE="1")
    # ⚠️ 2026-10-17 查实夜跑 403 的根因:launchd 起的进程**没有代理环境变量**,而评测走的 SDK 那条路
    # 没代理就被拒(「403 Request not allowed」);白天在会话里跑,环境里带着代理,所以一直通。
    # 白天在 launchd 里复现过:同一个 SDK 调用,无代理 403、补上代理就通;命令行 claude -p 无代理也通 ——
    # 所以原来那道「开跑前用 claude -p 真问一句」测的不是评测走的路,两晚都放行了。
    # 环境里没有代理时,现读系统代理补上(系统代理不带密码)
    if not any(env.get(k) for k in ("HTTPS_PROXY", "https_proxy")):
        代理 = _系统代理()
        if 代理:
            env.update(HTTPS_PROXY=代理, HTTP_PROXY=代理, NO_PROXY="localhost,127.0.0.1,::1")
    return env


认证失败 = re.compile(r"Failed to authenticate|API Error: 40[13]|Invalid API key|Please run /login")


def 真问一句():
    """用**评测同一个环境、同一条路**(SDK 的 `sdk.run`)真调一次模型。返回 (通不通, 说明)。

    ⚠️ 原来走 `claude -p` 命令行 —— 它没代理也通,而评测走的 SDK 没代理就 403,
    于是 10-16、10-17 两晚这道闸都放行了、整晚空跑(2026-10-17 查实)。**测的必须是评测真走的那条路**。"""
    码 = ("import sys,asyncio; sys.path[:0]=['agentsite','backend','knowledge','agent']; import sdk; "
          "r=asyncio.run(sdk.run('kb','只回复两个字:正常')); print('回答:'+(r.get('text') or ''))")
    try:
        r = subprocess.run([PY, "-c", 码], cwd=ROOT, env=评测环境(),
                           capture_output=True, text=True, timeout=180)
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
    挪走夜跑的.认证失败 = 0
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
            # 评测把调用报错接住写进结果文件、屏幕上只打汇总 —— 认证失败只看输出是看不见的(10-17 那晚 17 套记成「过」)
            挪走夜跑的.认证失败 += len(认证失败.findall(新增.decode("utf-8", "replace")))
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


# ── 管理后台(8801)夜跑前拉起来(用户 2026-10-20 拍「要」)───────────────────────────
# 全文检索 kb_rag 要连它。10-20 那晚它没起,tool_eval T07 记成了「环境没验成」—— 分得开了,但每晚都验不成,
# 检索这块就永远没人在测。所以开跑前不在就拉起来;**是夜跑拉起来的,跑完就关掉**(本来就开着的不动)。
管理后台地址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")


def _管理后台在():
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "5", "-w", "%{http_code}", 管理后台地址 + "/api/healthz"],
                       capture_output=True, text=True)
    return r.stdout.strip() == "200"


def 确保管理后台(等秒=60):
    """→ (状态说明, 拉起来的进程或 None)。拉不起来不拦夜跑 —— 那几题会照实记成「环境没验成」。"""
    if _管理后台在():
        return "本来就开着", None
    脚本 = os.path.join(ROOT, "管理后台", "tools", "dev.sh")
    if not os.path.exists(脚本):
        return f"拉不起来:没有 {os.path.relpath(脚本, ROOT)}", None
    import getpass
    env = dict(os.environ)
    env.setdefault("USER", getpass.getuser())          # launchd 里可能没有 USER,而 dev.sh 拼库地址要用它
    日志 = open(os.path.join(FEY, "nightly-aimc.log"), "a", encoding="utf-8")
    进程 = subprocess.Popen(["bash", 脚本], cwd=os.path.dirname(os.path.dirname(脚本)), env=env,
                            stdout=日志, stderr=日志, start_new_session=True)   # 自成一组,跑完整组一起关
    for _ in range(等秒 // 2):
        time.sleep(2)
        if _管理后台在():
            return "夜跑前拉起来了(跑完关掉)", 进程
        if 进程.poll() is not None:
            break
    关掉(进程)
    return f"拉不起来:{等秒} 秒内没就绪(日志 .feynman/nightly-aimc.log)—— 用到 kb_rag 的题会记成「环境没验成」", None


def 关掉(进程):
    if 进程 is None or 进程.poll() is not None:
        return
    import signal
    try:
        os.killpg(进程.pid, signal.SIGTERM)
        进程.wait(timeout=15)
    except Exception:                                                        # noqa: BLE001
        try:
            os.killpg(进程.pid, signal.SIGKILL)
        except Exception:                                                    # noqa: BLE001
            pass


# ── 夜跑结果自动提交(用户 2026-10-20 拍「进版本库,每天早上自动提交」)──────────────────────
# 评测结果是「这个版本在这套题上考了多少分」的历史(CLAUDE.md 第 8 节),原来夜跑的那份一直只在本机 agent/nightly/。
# 运行日志副本 funnel(24 MB)、skill_usage(4 MB)用户 10-20 拍「需要」进仓库 ——
# ⚠️ **压成 .jsonl.gz 再进,原样的不进**:funnel 是从 10-07 起一直攒的,13 天 5.5 万行、每天约 +1.8 MB,
#    原样进库约六周后单个文件过 GitHub 的 100 MB 上限,**从那天起每晚推送都会失败**;压完 28 MB → 1.6 MB。
#    压缩不带时间戳(mtime=0、不记文件名):内容没变就是同一串字节,不会每晚白多一次改动。
# 失败只记日志不抛:提交不成不该让夜跑本身算失败;没提交的明早人看报告时还在。
# 只点名这两份(用户 10-20 说「需要」的就是它们)。⚠️ withheld 不进:那是体检扣下的答案原文,
# 10-06 起原件就在 .gitignore 里(b73baa9「日志含答案原文」)—— 挪到 nightly 换个名字不该绕过这条
进库的日志 = ("agentsite__evals__funnel.jsonl", "agentsite__evals__skill_usage.jsonl")


def 入库清单(根):
    """→ 这一晚要进仓库的文件(相对 根)。顺手把运行日志副本压成 .gz;原样的 .jsonl 不在清单里。"""
    import glob, gzip
    夜目录 = os.path.join(根, "agent", "nightly")
    for 原 in sorted(glob.glob(os.path.join(夜目录, "agentsite__evals__*.jsonl"))):
        if os.path.basename(原) not in 进库的日志:
            continue
        with open(原, "rb") as f:
            数据 = f.read()
        with open(原 + ".gz", "wb") as 出, gzip.GzipFile(filename="", mode="wb", fileobj=出, mtime=0, compresslevel=9) as z:
            z.write(数据)
    return sorted(os.path.relpath(f, 根) for f in
                  glob.glob(os.path.join(夜目录, "agent__*-results.jsonl"))
                  + glob.glob(os.path.join(夜目录, "agentsite__evals__*.jsonl.gz")))


def 提交夜跑结果(报告):
    路径 = [os.path.relpath(报告, ROOT)] + 入库清单(ROOT)
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=300)
    try:
        if not git("status", "--porcelain", "--", *路径).stdout.strip():
            return "没有新结果要提交"
        if git("add", "--", *路径).returncode:
            return "git add 失败"
        扫 = subprocess.run([os.path.join(ROOT, "tools", "scan_secrets.sh")], cwd=ROOT, capture_output=True, text=True)
        if 扫.returncode:
            return "扫密钥不过 —— 没提交,等人看(" + (扫.stdout + 扫.stderr).strip()[-120:] + ")"
        r = git("commit", "--only", "-m", f"夜跑评测结果 {os.path.basename(报告)[:-3]}(自动提交:评测结果、报告、压缩过的运行日志)\n\n"
                "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>", "--", *路径)
        if r.returncode:
            return "提交失败:" + (r.stdout + r.stderr).strip()[-160:]
        # ⚠️ **不拉、不变基、不动工作区**(用户 10-24 拍「有未保存改动就不拉,只提交自己的」)。
        # 原来是 pull --rebase --autostash:它会把并行会话**没保存的改动**收起来、拉完再放回 ——
        # 放回撞了冲突,那份从没提交过的改动就得人去救,而 git 历史里查不到它。
        # 现在只做一件不碰工作区的事:上游没有我没见过的提交(快进)就直接推;
        # 上游动过 → 本地这次提交留着,明早人工 pull --rebase 再推。代价是偶尔晚一天上去。
        r = git("fetch", "--quiet")
        if r.returncode:
            return "提交了没推上去(fetch 失败)—— 本地有这次提交,人工推一下:" + (r.stdout + r.stderr).strip()[-120:]
        if git("merge-base", "--is-ancestor", "@{u}", "HEAD").returncode:
            return ("提交了没推上去:上游有新提交,要变基 —— **夜跑不动工作区**(用户 10-24 拍),"
                    "本地留着这次提交,明早人工 pull --rebase 再推")
        r = git("push")
        if r.returncode:
            return "提交了没推上去(push 失败)—— 本地有这次提交,人工推一下:" + (r.stdout + r.stderr).strip()[-120:]
        return f"已提交并推送({len(路径)} 个文件)"
    except Exception as e:                                                   # noqa: BLE001
        return f"提交出错:{type(e).__name__}: {e}"


判定行 = re.compile(r"判定:(退步|持平|进步|没结论)")


def 归类(退出码, 输出):
    """一套评测跑完 → 结果。抽出来是为了让检查真调它(tools/eval_env_check.py)。
    · 输出里有认证失败 → 没跑成(开跑前那一问只证明开跑那一刻通;10-16 那晚 17 套就是这么「过」的)
    · 75 = 只有「环境没验成」的题没过(比如管理后台没起、kb_rag 查不了)—— 和「判红」分开报,
      不然模型老老实实说「查不了」和真答错长得一样(10-20 夜跑 tool_eval 就是这么红的)

    ## 「判定:X」那一行(2026-10-20 加)

    `agent/rounds.报()` 收尾打一行 `判定:退步 / 持平 / 进步 / 没结论`,这里读它。
    **约定只认这一行,不解析别的自由文本。**
    不走 `跑并收尾` 的那 5 套不会打这一行 → 落回按退出码判,**那是诚实的降级**。

    ⚠️ **只有一处会改红绿:`判定:退步` 而退出码是 0。**
    有十套评测**从不以非零退出**(它们压根没写 `sys.exit`),于是
    **退步会被报成「过」** —— 这一处是收紧,必须改。
    反过来「持平而退出码非 0」**照旧算判红**:把它摘出来是放宽,
    而用户 10-20 拍的点名式里「长期错的不红」是**和「白纸黑字记着为什么」绑在一起**的,
    那份名单还没建 —— 先摘出来就等于只要了放宽那一半。
    """
    if 认证失败.search(输出 or ""):
        return "没跑成(认证失败)"
    if 退出码 == 75:
        return "部分没验成(环境)"
    m = 判定行.search(输出 or "")
    if m and m.group(1) == "退步":
        return "退步"
    return "过" if 退出码 == 0 else "判红"


def 判定(输出):
    """那一行说的是什么 —— 给报告单独一栏用。打不出来就是「没打」。"""
    m = 判定行.search(输出 or "")
    return m.group(1) if m else "没打"


def 跑一套(名, 参数, 截止):
    env = 评测环境()
    限 = max(60, min(单独上限分钟.get(名, 每套上限分钟) * 60, int((截止 - dt.datetime.now()).total_seconds())))
    t0 = time.time()
    try:
        r = subprocess.run([PY, os.path.join("agent", 名), *参数], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=限)
        尾 = [x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip()][-3:]
        # 跑到一半登录掉了也算(开跑前那一问只证明开跑那一刻通)—— 输出里有认证失败就是**没跑成**,
        # 不记「过」:那套题一道都没真答,退出码 0 只说明脚本没崩(10-16 那晚 17 套就是这么「过」的)
        结 = 归类(r.returncode, r.stdout + r.stderr)
        return dict(套=名, 结果=结, 判定=判定(r.stdout + r.stderr),
                    退出码=r.returncode, 分钟=round((time.time() - t0) / 60, 1), 尾=尾)
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
    with open(夜跑PID, "w") as f:                # bite_run 读它决定要不要让开(见 活着());结束时在下面删
        f.write(f"{os.getpid()}\n")
    try:
        return _跑(现在, 套们, 试, 截止)
    finally:
        try:
            os.remove(夜跑PID)
        except OSError:
            pass


def _跑(现在, 套们, 试, 截止):
    后台状态, 后台进程 = 确保管理后台()
    说(f"管理后台:{后台状态}")
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
        # ⚠️ 这个元组和下面「全跑完」那个**必须同时改** —— 漏了「退步」的话,
        #    跑到一半掉登录、而那一套又判了退步,它就躲过了这条改判(2026-10-20 加「退步」)
        if 挪走夜跑的.认证失败 and r["结果"] in ("过", "判红", "退步", "部分没验成(环境)"):
            r["结果"] = "没跑成(认证失败)"
            r["尾"] = (r.get("尾") or []) + [f"结果文件里有 {挪走夜跑的.认证失败} 处认证失败"]
        结果.append(r)
        说(f"  {名}:{r['结果']}({r['分钟']} 分钟)")
    os.makedirs(报告目录, exist_ok=True)
    报 = os.path.join(报告目录, f"{现在:%Y-%m-%d}.md")
    计 = {}
    for r in 结果:
        计[r["结果"]] = 计.get(r["结果"], 0) + 1
    with open(报, "w", encoding="utf-8") as f:
        f.write(f"# 夜间评测 · {现在:%Y-%m-%d %H:%M}\n\n")
        f.write("模型:claude-haiku-4-5 · 这一晚的结果在 agent/nightly/(**跑完自动提交推送**,用户 10-20 拍;"
                "正式基线 agent/*-results.jsonl 不动)\n\n")
        f.write(f"管理后台(全文检索 kb_rag 要用):{后台状态}\n\n")
        f.write(" · ".join(f"{k} {v}" for k, v in 计.items()) + "\n\n")
        # 「判定」单独一栏(2026-10-20 加)—— **「结果」那一栏原来一个字混了四种状态**:
        # 真答错、环境没起、判分器认不出类、「这个对比说明不了任何事」。
        # 四种混在一起的后果:四套每晚都红 → 没人看 → **真的退步那天也没人看**。
        f.write("| 套 | 结果 | 判定 | 分钟 | 最后几行 |\n|---|---|---|---|---|\n")
        for r in 结果:
            f.write(f"| {r['套']} | {r['结果']} | {r.get('判定', '没打')} | {r['分钟']} "
                    f"| {' / '.join(x[:80] for x in r['尾']).replace('|', '¦')} |\n")
    关掉(后台进程)                     # 夜跑自己拉起来的才关;本来就开着的是 None,不动
    # ⚠️ **「退步」也算跑完了** —— 它是一次有效的测量,只是结果变差了。
    #    漏了它的话那个「成功过」的时间戳就不再更新,而按双时间戳的设计,
    #    「尝试过新、成功过旧」表示的是「**在跑但每次失败**」—— 那是另一回事。
    全跑完 = all(r["结果"] in ("过", "判红", "退步", "部分没验成(环境)") for r in 结果)
    if 全跑完:
        with open(OK, "w") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%dT%H:%M:%S}\n")
    说(f"结束:{json.dumps(计, ensure_ascii=False)} → {os.path.relpath(报, ROOT)}")
    if not 试:
        说(f"结果入库:{提交夜跑结果(报)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
