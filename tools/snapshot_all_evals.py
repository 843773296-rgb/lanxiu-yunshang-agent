#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全项目评测快照 · 跑一夜(用户 2026-11-08 晚拍「安排 12 小时的长期任务」,选了「全项目评测快照」)。

    python3 tools/snapshot_all_evals.py --截止 04:55          # 正式跑
    python3 tools/snapshot_all_evals.py --截止 04:55 --只看    # 只打印日程,不跑
    python3 tools/snapshot_all_evals.py --试 2                # 先拿两套验通路

## 这个脚本**不是**第二份夜跑

核心全部复用 `tools/nightly_eval.py`:`跑一套()`(单套限时 / 崩·超时·判红·认证失败分开归类)、
`评测环境()`(剥掉按量计费凭证、钉死 Claude Haiku)、`拍快照()` + `挪走夜跑的()`
(把这一轮写进基线文件的东西挪到 `agent/nightly/`,原文件恢复原样)、`真问一句()`
(开跑前用评测真走的那条路调一次模型)。那九条设计每一条都是一次事故换来的,别重写。

**只换三件调度策略**:

  ① **每套自己拿锁**(用户 11-08 拍「分段占锁」)。`nightly_eval` 原来的策略是
     「有人在用就整晚让开」—— 那在无人值守的半夜是对的,但今晚并行会话也在跑 12 小时的活,
     它要反复跑整轮门禁。让开就整夜跑不了,独占就把它堵死(今天真出过事故:
     我占锁 150 分钟 → 它的门禁等锁 60 分钟超时 → 迁移那一步没跑 → 服务 500)。
     所以每套跑完放锁,它抢到就跑,自然交替。
     ⚠️ 等锁封顶压到 **15 分钟**(`LANXIU_LOCK_CAP`,默认 3600):抢不到就跳过、记下来,
     这一遍末尾统一重试 —— 否则一套白等一小时,一夜的日程就垮了。

  ② **跑两遍。** 项目那条「单轮结果不算结论」一直只用在**题**这一级,
     而它在**套**这一级同样成立:
     > **一份全项目快照也是一次抛硬币。**
     跑一遍只得到「29 套各考了多少分」,没有任何依据说明这些数里多少是真实水平、
     多少是今晚的运气。两遍之间的差异才是**这套评测体系的噪声底噪** —— 这个数从没人量过,
     而有了它,以后任何「项目水平提升了」的说法才读得出来(提升必须大于它)。

  ③ **整夜不连管理后台。** 显式剥掉 `LANXIU_USAGE_URL` / `LANXIU_BRIDGE_PROJECT` /
     `LANXIU_USAGE_USER` —— 并行会话今晚要跑 e2e,它会往共享 PG 建测试术语、
     改聊天助手的生产版指针,而那些**直接进模型读的上下文**。
     > 一份「跑在干净上下文上的快照」和一份「跑在别人 e2e 测试数据上的快照」,
     > 在结果文件里长得一模一样 —— 每套都有分数、都有来路、都绿。
     剥变量是**结构上**挡住它,不靠对方记得避开(和今天 v6 那轮同口径:按「全关」跑)。

## 两个硬约束,都不是我定的

· **04:55 强停。** 05:10 是每日世界平移,跨过它的两份结果库章不同,
  拼在一张表里就不是快照了(这条约束来自 `nightly_eval` 的设计 ①)。
  所以「12 小时」实际可用约 7 小时 —— 排下来是「全套一遍 + 快的那批第二遍」。
· **固定代码版本。** 这一夜不拉并行会话的提交:评测结果盖的来路章里有代码指纹,
  中途拉代码就等于把一张快照拆成两批,而那张表看起来和真快照一模一样。

## 为什么排除技能触发那套

它今天刚跑过(v6,46/50),而**那一版是 `claude-sonnet-5` 跑的**,这一夜统一 Haiku ——
混进来会是一行不可比的数,而它在表里和别的行长得一样。见 `agentsite/evals/runs/v6.json`。
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⚠️⚠️ **剥变量必须在 import nightly_eval 之前** —— 它的 `评测环境()` 是从
# `os.environ` 继承的(只剥按量计费凭证)。import 之后再 pop 也行,
# 但那依赖「它每次调用时才读 environ」这个实现细节;放在前面是结构上的。
为了不连后台 = ("LANXIU_USAGE_URL", "LANXIU_BRIDGE_PROJECT", "LANXIU_USAGE_USER")
剥掉了 = {k: os.environ.pop(k) for k in 为了不连后台 if k in os.environ}


def 不连后台这句话():
    """**「剥掉 0 个」有两个意思,而两种的下一步动作不同。**

    ⚠️ 2026-11-09 起跑前查实:这个 shell 里那三个变量**本来就没有**,所以这一行印的是
    「剥掉 0 个」—— 而我原先把这个 0 读成了「整夜不连后台」的保证。**它不是那个保证。**

    > 一句「剥掉 0 个」,可能是**这个 shell 本来就没有那三个变量**(不连后台这件事成立,
    > 但成立的理由在 shell 那边,不在这段代码),也可能是**这段剥离装错了地方、一个都没剥着**
    > (不连后台根本不成立)—— **两种在这一行字上长得一模一样**,
    > 而后者会让人拿着一份连过后台、混进了并行会话 e2e 测试数据的快照当干净数据。

    真正让工具服务进程连不上后台的是 sdk 里拼服务环境那一段(`mcp_config`):
    那三个变量**只在父进程有值时才显式拼进去**,不指望继承。所以父进程没有 = 服务进程拿不到。
    这段剥离是为「起跑的 shell 带了这些变量」那种情形装的,
    已单独验过:给三个假值,它报「剥掉 3 个」。
    """
    if 剥掉了:
        return ("剥掉了 %d 个后台变量(%s)—— 并行会话今晚跑 e2e 会往共享 PG 写测试术语"
                % (len(剥掉了), "、".join(剥掉了)))
    return ("这个 shell 本来就没有那三个后台变量,**所以这段剥离一个都没剥着** —— "
            "不连后台今晚仍然成立(服务进程只拿显式拼进去的那几个),"
            "但它是**这个 shell 碰巧没有**换来的,不是这段剥离换来的")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import nightly_eval as N          # noqa: E402

报告目录 = os.path.join(ROOT, ".feynman")
# 从夜跑历史(.feynman/nightly-eval/*.md)数出来的最长耗时,单位分钟 —— 用来排序和估时。
# ⚠️ 这是**历史最长**,不是保证值;真实耗时由 `跑一套()` 自己限时。
历史分钟 = {
    "ops_eval.py": 71.0, "oppo_eval.py": 46.9, "tool_eval.py": 18.8, "pattern_eval.py": 18.3,
    "report_eval.py": 13.6, "talk_eval.py": 12.7, "growth_eval.py": 11.7, "pickup_eval.py": 10.0,
    "liability_eval.py": 9.3, "member_eval.py": 9.1, "factory_eval.py": 8.8, "repair_eval.py": 8.5,
    "role_eval.py": 7.7, "chat_eval.py": 7.5, "order_eval.py": 7.2, "fitting_eval.py": 6.9,
    "measure_eval.py": 6.9, "rating_eval.py": 6.3, "workshop_eval.py": 5.4, "gen_compare.py": 4.6,
    "vision_eval.py": 4.2, "store_report_eval.py": 3.6, "recall_eval.py": 3.2,
    "triage_shadow.py": 2.6, "scheme_eval.py": 2.6, "select_eval.py": 0.1,
    "triage_pipeline_eval.py": 0.1,
}
# 这一夜不跑的,各自写明理由 —— **「没跑」和「跑了没过」在报告里不许混成一个字**
不跑 = {"skill_eval.py": "今天刚跑过 v6(46/50),而那一版是 sonnet-5 跑的;"
                        "这一夜统一 Haiku,混进来是一行不可比的数"}


def 日程(截止):
    """按历史耗时**从小到大**排。

    ⚠️ 为什么不按「重要性」排:万一时间不够,先跑完的应当是**成对的两遍**而不是
    「几套慢的各一遍」—— 这一夜的产出是噪声底噪,而噪声要两遍才读得出来。
    慢的那两套(运营 71 分、商机 47 分)放最后,它们只有一遍也不影响别套成对。
    """
    套们 = [(f, N._参数(f)) for f in sorted(历史分钟, key=lambda x: 历史分钟[x])
            if f not in 不跑 and os.path.exists(os.path.join(ROOT, N.别处的套.get(f) or
                                                             os.path.join("agent", f)))]
    return 套们


def 跑一套拿着锁(名, 参数, 遍, 截止):
    """`nightly_eval.跑一套()` 包在 `gate_lock.sh` 里 —— 每套自己拿锁、跑完放锁。

    ⚠️ 退出码 3 是**拿不到锁**(gate_lock 的约定),不是评测失败。
    这两件事的下一步动作相反(重试 / 去查那套),所以分开记。
    """
    码 = ("import sys, json, datetime as dt\n"
          f"sys.path.insert(0, {os.path.join(ROOT, 'tools')!r})\n"
          "import nightly_eval as N\n"
          f"r = N.跑一套({名!r}, {参数!r}, dt.datetime.fromisoformat({截止.isoformat()!r}))\n"
          "print('<<<R>>>' + json.dumps(r, ensure_ascii=False))\n")
    cmd = [os.path.join(ROOT, "tools", "gate_lock.sh"),
           "--who", f"工:全项目快照 第{遍}遍 {名}", sys.executable, "-c", 码]
    t0 = time.time()
    # ⚠️⚠️ **`errors="replace"` 不许去掉 —— 它是这一夜 10 小时的保命绳。**
    # 2026-11-09 起跑前实测:`gate_lock.sh` 等锁超时那条路径吐出的 stderr
    # **不是合法 UTF-8**(`"$LOCK_DIR。"` 把中文句号的首字节吃进了变量名,
    # 根因已修),而默认的 `text=True` 遇到非法字节**当场抛 UnicodeDecodeError**。
    # 那一抛不是「这一套没跑成」,是**整个调度崩死、这一夜全丢** ——
    # 而留下的 traceback 看不出和锁有任何关系。
    # 根因修掉了,这一道仍然留着:**被包的命令是别人写的脚本,它们吐什么字节不由我决定**,
    # 而「解不开一个字节」和「这一夜白跑」之间不该只隔一个默认参数。
    # (`snapshot_check` ⑨ 按结构钉住它还在。)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace",
                       env=dict(os.environ, LANXIU_LOCK_CAP="900"))
    # ⚠️⚠️ **先找结果行,再看退出码 —— 这个顺序反了会把跑完的那一套记成「没抢到锁」。**
    # `gate_lock.sh` 把**被包命令的退出码原样传回**(它自己的自测第 ② 条就在钉这件事:
    # 「一个吃掉退出码的包装器,比没有包装器危险得多」),而它拿不到锁时**也**退 3。
    # 于是「退 3」有两个来源:
    #   ① 真的没抢到锁 —— 那一套**一步都没跑**
    #   ② 被包的那段码自己退了 3 —— 那一套**跑过了**,gate_lock 只是把码传回来
    # 这两件事的下一步动作相反(这一遍末尾重试 / 去查那套),
    # **而它们在 `returncode` 这个数上长得一模一样。**
    # 结果行是唯一分得开它们的东西:拿到了就说明那套真跑完了,退出码是几都不改变这一点。
    # (今天这段之所以没出事,只因为上面那段码碰巧只会退 0 或 1 —— **那是偶然,不是保证**,
    #  而判据得守的是后者;`snapshot_check` ⑦ 按行号钉住这个先后。)
    for l in r.stdout.splitlines():
        if l.startswith("<<<R>>>"):
            return json.loads(l[len("<<<R>>>"):])
    if r.returncode == 3:
        return dict(套=名, 结果="没抢到锁", 判定="没打", 退出码=3,
                    分钟=round((time.time() - t0) / 60, 1),
                    尾=["等锁 15 分钟没等到 —— 并行会话在跑它的门禁,这一遍末尾重试"])
    # 连结果行都没拿到 —— 调度自己的问题,**别记成那套评测失败**
    return dict(套=名, 结果="没跑成(调度)", 判定="没打", 退出码=r.returncode,
                分钟=round((time.time() - t0) / 60, 1),
                尾=[x for x in (r.stdout + r.stderr).strip().splitlines() if x.strip()][-3:])


def 写报告(记录, 截止, 开始, 代码, 库章, 完了=False):
    """**每套跑完就重写一次** —— 别攒到最后:这一夜随时可能被中断(笔记本睡着、
    我这边上下文满了换会话),而攒着写等于中断一次全丢。"""
    p = os.path.join(报告目录, f"全项目快照-{开始:%Y%m%d}.md")
    L = [f"# 全项目评测快照 · {开始:%Y-%m-%d %H:%M} 起(截止 {截止:%H:%M})", "",
         f"> 用户 2026-11-08 晚拍「12 小时长期任务」→ 选了「全项目评测快照」。",
         f"> 一律 Claude **Haiku**(`nightly_eval.评测环境()` 钉死),**整夜不连管理后台**"
         f"({不连后台这句话()}),",
         f"> 固定代码 `{代码}`、库章 `{(库章 or {}).get('build_logic_fp', '?')}`。",
         f"> **夜跑分数不进基线**:每套写进基线文件的东西都挪到 `agent/nightly/`,原文件恢复原样。", "",
         "⚠️ **这份表怎么读**:「没跑」「没抢到锁」「超时」「崩了」「判红」是**五件不同的事**,",
         "下一步动作各不相同,所以分开记 —— 它们在「没过」上长得一模一样。", ""]
    if 不跑:
        L += ["**这一夜刻意不跑的**:", ""] + [f"- `{k}` —— {v}" for k, v in 不跑.items()] + [""]
    for 遍 in sorted({x["遍"] for x in 记录}):
        这遍 = [x for x in 记录 if x["遍"] == 遍]
        L += [f"## 第 {遍} 遍({len(这遍)} 套)", "",
              "| 套 | 结果 | 判定 | 分钟 | 最后一行 |", "|---|---|---|---|---|"]
        for x in 这遍:
            尾 = (x.get("尾") or ["—"])[-1].replace("|", "/")[:90]
            L.append(f"| `{x['套']}` | {x['结果']} | {x.get('判定') or '没打'} "
                     f"| {x.get('分钟')} | {尾} |")
        L.append("")
    # 核心产出:同一套两遍之间判定不一样的,就是这套评测体系的噪声
    两遍 = {}
    for x in 记录:
        两遍.setdefault(x["套"], {})[x["遍"]] = x
    成对 = {k: v for k, v in 两遍.items() if len(v) >= 2}
    L += ["---", "", "## 噪声底噪:两遍之间翻面的套", ""]
    if not 成对:
        L += ["ℹ️ **还没有任何一套跑满两遍** —— 这一栏**没东西可报**,不是「没有噪声」。", ""]
    else:
        翻 = [k for k, v in 成对.items()
              if (v[1].get("结果"), v[1].get("判定")) != (v[2].get("结果"), v[2].get("判定"))]
        L += [f"跑满两遍的 **{len(成对)}** 套里,**{len(翻)}** 套两遍结果不一样"
              f"({len(翻) * 100 // max(len(成对), 1)}%):", ""]
        for k in 翻:
            v = 成对[k]
            L.append(f"- `{k}`:第一遍 {v[1]['结果']}/{v[1].get('判定')} → "
                     f"第二遍 {v[2]['结果']}/{v[2].get('判定')}")
        L += ["", "> **同一份代码、同一份库、同一个模型,两遍之间就能翻面** —— ",
              "> 这个比例就是底噪。任何「项目水平提升了」的说法,提升必须大于它才读得出来。", ""]
        单遍 = sorted(set(两遍) - set(成对))
        if 单遍:
            L += [f"⚠️ 另有 **{len(单遍)}** 套只跑了一遍,**它们读不出噪声**:"
                  + "、".join(f"`{x}`" for x in 单遍[:8])
                  + (f" ……还有 {len(单遍) - 8} 套" if len(单遍) > 8 else ""), ""]
    if not 完了:
        L += ["---", "", f"⏳ **还在跑**(这份报告每套跑完重写一次,{dt.datetime.now():%H:%M} 时的样子)。", ""]
    with open(p, "w", encoding="utf-8") as h:
        h.write("\n".join(L))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--截止", default="04:55")
    ap.add_argument("--只看", action="store_true")
    ap.add_argument("--试", type=int, default=0)
    a = ap.parse_args()

    开始 = dt.datetime.now()
    时, 分 = (int(x) for x in a.截止.split(":"))
    截止 = dt.datetime.combine(开始.date(), dt.time(时, 分))
    if 截止 <= 开始:
        截止 += dt.timedelta(days=1)          # 跨午夜
    套们 = 日程(截止)
    if a.试:
        套们 = 套们[:a.试]
    估 = sum(历史分钟.get(f, 5) for f, _ in 套们)
    print(f"\n全项目评测快照 · {开始:%m-%d %H:%M} → {截止:%m-%d %H:%M}"
          f"(可用 {(截止 - 开始).total_seconds() / 3600:.1f} 小时)")
    print(f"  这一夜跑 {len(套们)} 套,单遍估 {估:.0f} 分({估 / 60:.1f} 小时);两遍估 {估 * 2 / 60:.1f} 小时")
    print(f"  整夜不连管理后台:{不连后台这句话()}")
    for k, v in 不跑.items():
        print(f"  ⏸ 不跑 {k}:{v}")
    if a.只看:
        print("\n  顺序(按历史耗时从小到大 —— 先成对,慢的放最后):")
        for i, (f, 参) in enumerate(套们, 1):
            print(f"    {i:>2}. {f:<26} 估 {历史分钟.get(f, 5):>5.1f} 分"
                  + (f" · 参数 {参}" if 参 else ""))
        return 0

    # ⚠️ 开跑前**真调一次模型**(10-16 那晚的教训:配置绿着、每次调用 403,
    # 24 套全 0 分,其中 17 套还记成「过」)。
    通, 说明 = N.真问一句()
    print(f"\n  开跑前真调一次模型:{'通' if 通 else '不通'} —— {说明}")
    if not 通:
        print("  ❌ 不通,**整夜不跑**(跑了也是 0 分,而 0 分和真实 0 分长得一样)")
        return 1
    代码 = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import evalrec as _er                                      # noqa: E402
    库章 = _er._库章()
    记录 = []
    for 遍 in (1, 2):
        没抢到 = []
        for f, 参 in 套们:
            if dt.datetime.now() >= 截止:
                print(f"  ⏰ 到截止 {截止:%H:%M},停。第 {遍} 遍没跑完的不算失败")
                break
            快 = N.拍快照()
            r = 跑一套拿着锁(f, 参, 遍, 截止)
            挪 = N.挪走夜跑的(快, f)
            r.update(遍=遍, 挪=len(挪))
            记录.append(r)
            print(f"  [{遍}] {f:<26} {r['结果']:<14} {r.get('判定') or '没打':<6} "
                  f"{r.get('分钟')} 分 · 挪 {len(挪)} 份")
            if r["结果"] == "没抢到锁":
                没抢到.append((f, 参))
            p = 写报告(记录, 截止, 开始, 代码, 库章)
        # 这一遍末尾重试抢不到锁的(并行会话那轮门禁多半跑完了)
        for f, 参 in 没抢到:
            if dt.datetime.now() >= 截止:
                break
            快 = N.拍快照()
            r = 跑一套拿着锁(f, 参, 遍, 截止)
            挪 = N.挪走夜跑的(快, f)
            r.update(遍=遍, 挪=len(挪), 重试=True)
            记录 = [x for x in 记录 if not (x["套"] == f and x["遍"] == 遍)] + [r]
            print(f"  [{遍}·重试] {f:<20} {r['结果']}")
            p = 写报告(记录, 截止, 开始, 代码, 库章)
        if dt.datetime.now() >= 截止:
            break
    p = 写报告(记录, 截止, 开始, 代码, 库章, 完了=True)
    print(f"\n✅ 收工 {dt.datetime.now():%H:%M} —— 报告 {os.path.relpath(p, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
