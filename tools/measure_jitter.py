#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖动测量 —— **同一份代码、同一个模型,连跑 N 次,看分数散成什么样。**

## 为什么要有它

`agent/evalrec.同版波动_下限 = 2` 这个数,是 **2026-09-16 只跑两次量出来的**。
两次能量出的只有「至少差这么多」,量不出分布 ——
而项目里到处在用它判断「这一版比上一版好没好」。

> **一个只跑两次得出的下限,和一个真实的波动范围长得一模一样**:
> 都是一个数字,都写在同一个变量名后面。

这个脚本把那个数从**猜测**变成**测量**。

## ⚠️ 它要求工作区干净

五次跑的必须是同一个世界。工作区脏的话 `evalrec.代码()` 会盖上 `+dirty` ——
**那一轮的代码谁也复现不了**,五个数放在一起也就没有意义了。
所以开跑前先查一次,脏就拒跑。

## ⚠️ 它报的不是「平均分」

平均分会把这件事讲反。要看的是三样:

    **极差**      最高分和最低分差多少 —— 这就是「多少分以内读不出东西」
    **每题的翻转** 哪些题在不同轮次里时对时错 —— **这比总分有用得多**
    **总是错的**   每一轮都错的题 —— **那才是真的能力缺口,不是抖动**

最后一条是这个脚本存在的主要理由:
**「一次跑错了」和「每次都跑错」在一张成绩单上长得一模一样**,
而前者该忽略,后者该去修提示词。

## 单题模式 —— **这个模式才让「多跑几次」在工程上可行**

跑整套 31 题一轮 11 分钟,跑 20 轮是 3.7 小时;而**只跑一道题**半分钟,
20 轮约 10 分钟。**同一个办法,差 20 倍。**

所以判断「我这版提示词有没有用」的正确做法是:

    ① 先单题跑 10 次,看这道题本来稳不稳
    ② 稳定错(0/10)   → 改完跑 1 次就够
       稳定对(10/10)  → 不用改
       抖动(比如 3/10)→ 改前改后各跑 N 次,比两个次数
    ③ N 要多大取决于你想确认多大的改善:
          大改善 20%→60%   各 10 次   (~10 分钟)   ✅
          中等   40%→60%   各 40 次   (~40 分钟)   ⚠️
          小改善 60%→70%   各 200 次+ (几小时)     ❌

> ⚠️ **所以在抖动的题上,只值得追大幅改善。** 小幅改善不是做不到,是不划算 ——
> 看到 3/10 别想着推到 4/10,要么找到能推到 8/10 的改法,要么别动它。

用法:  ./agentsite/.venv/bin/python tools/measure_jitter.py [轮数] [评测名] [题号]
       题号给了就**只跑那一道** —— 快 20 倍
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")


# 被测的那套东西涉及哪些路径 —— **只有这些脏了才算脏**。
#
# ⚠️ 原来查的是「整个仓库干净」,而这台机器上**常有别的会话在同时改别处**
# (第一次跑就撞上了:另一个会话正在写 `fakedata/target.py`)。
# 那时候有两条路,**只有一条是对的**:
#
#     ❌ 放宽成「不查了」        —— 于是真的混进别人改动时也不会拦
#     ✅ 查得更准:只查被测路径   —— 别人改别处不拦,改到被测路径上照样拦
#
# **一道会误拦的闸,迟早会被人关掉** —— 而关掉之后它连该拦的也不拦了。
被测路径 = ("agent/", "agentsite/", "backend/", "knowledge/", "prompts.py",
            "mcp/", "tools/")

# ⚠️ **产物不算代码。** 这几个是评测**自己跑出来的结果**,不是被测的东西。
#
# 不排掉的话这道闸会**自锁**:跑一次测量 → 产生结果文件 → 下次拒跑。
# 而它锁的不是别人,是**自己刚才留下的脚印** —— 第二次跑就撞上了。
#
# ⚠️ 排它们是**安全的**,理由要说清:被测的是「代码在同一个世界」,
# 而这几个文件**没有任何代码会读它们**(它们只被写、被人看)。
# 如果哪天有东西开始读结果文件,这条豁免就不再安全 —— 所以写下理由,别只写名单。
产物 = ("agent/ops-eval-results.jsonl", "agent/gen-compare-results.jsonl",
        "agentsite/evals/", "agent/growth-eval-results.jsonl",
        "agent/vision-eval-results.jsonl", "agent/liability-eval-results.jsonl")


def 干净吗():
    """**只看被测路径**。返回 (干净吗, 脏了什么, 别处脏了什么)。"""
    r = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                       capture_output=True, text=True).stdout.strip()
    线 = [x for x in r.split("\n") if x.strip()]
    def 路(x): return x[3:].strip().strip('"')
    脏 = [x for x in 线 if 路(x).startswith(被测路径)
          and not 路(x).startswith(产物)]
    别处 = [x for x in 线 if not 路(x).startswith(被测路径)
            or 路(x).startswith(产物)]
    return (not 脏), "\n".join(脏), "\n".join(别处)


def 跑一轮(评测, out, 题号=None):
    t0 = time.time()
    cmd = [PY, os.path.join(ROOT, "agent", f"{评测}.py")]
    if 题号: cmd.append(题号)          # 只跑这一道 —— 快 20 倍
    with open(out, "w", encoding="utf-8") as f:
        subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                       env={**os.environ, "LANXIU_PROVIDER": "claude"})
    txt = open(out, encoding="utf-8").read()
    m = re.search(r"通过 (\d+)/(\d+)", txt)
    # 每题对错:行首 ✅/❌ 后面跟题号。
    # ⚠️ **不许写成 `dict(findall(...))`** —— findall 给的是 (符号, 题号) 对,
    # 直接 dict() 会**按符号做键**,31 条当场压成 2 条:{'✅': 最后一个对的,
    # '❌': 最后一个错的}。而它**不报错**:汇总照常打印「每次都错:2 题」,
    # 看起来完全像个结论。
    # 第一版就是这么写的,是拿总题数对账才发现的 ——
    # **静默少算,而这个脚本本身就是为了量「看不见的东西」而写的。**
    题 = {q: (mk == "✅") for mk, q in re.findall(r"([✅❌])\s+(\w+)\s", txt)}
    n对, n总 = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    # **对账**:解析出来的题数必须等于总题数,不等就说出来,不许静默继续
    if n总 is not None and len(题) != n总:
        print(f"    ⚠️ 解析到 {len(题)} 题,而这轮总共 {n总} 题 —— "
              f"**每题统计不可信**,只有总分可用", flush=True)
    return n对, n总, 题, round(time.time() - t0)


def main():
    轮 = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    评测 = sys.argv[2] if len(sys.argv) > 2 else "ops_eval"
    题号 = sys.argv[3] if len(sys.argv) > 3 else None
    净, 脏, 别处 = 干净吗()
    if not 净:
        print("❌ **被测路径**不干净,拒跑 —— 五次跑的必须是同一个世界。\n"
              "   脏的话来路会盖成 +dirty,那一轮的代码谁也复现不了。\n   " +
              脏.replace("\n", "\n   "))
        return 1
    if 别处:
        # ⚠️ **不拦,但要说。** 别处的改动不影响这次测量,
        # 而「没拦」和「没看见」是两件事 —— 后者会让人以为工作区是干净的。
        print("ℹ️ 被测路径之外有改动(**不影响这次测量,但说一声**):\n   " +
              别处.replace("\n", "\n   "))
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import evalrec as er
    来路 = {"供应商": er.供应商(), "模型": er.模型(), "代码": er.代码()}
    print(f"抖动测量 · {评测}{('·' + 题号) if 题号 else ''} × {轮} 轮"
          + ("   (**单题模式**,比跑整套快约 20 倍)" if 题号 else ""))
    print(f"来路:{来路}")
    print("=" * 84, flush=True)

    结果 = []
    od = os.path.join(ROOT, ".feynman", "jitter")
    os.makedirs(od, exist_ok=True)
    for i in range(轮):
        标 = f"{评测}{('-' + 题号) if 题号 else ''}"
        对, 总, 题, 秒 = 跑一轮(评测, os.path.join(od, f"{标}-{i+1}.txt"), 题号)
        结果.append(dict(轮=i + 1, 对=对, 总=总, 题=题, 秒=秒))
        print(f"  第 {i+1} 轮:{对}/{总}  ({秒}s)", flush=True)

    分 = [r["对"] for r in 结果 if r["对"] is not None]
    if len(分) < 2:
        print("❌ 有效轮次不足 —— 去看 .feynman/jitter/ 下的原始输出")
        return 1

    极差 = max(分) - min(分)
    print("\n" + "=" * 84)
    print(f"  分数:{分}   **极差 {极差} 分**(最高 {max(分)} / 最低 {min(分)})")

    # 每题在各轮里的表现
    全题 = sorted({k for r in 结果 for k in r["题"]})
    翻转, 总错, 总对 = [], [], []
    for q in 全题:
        v = [r["题"].get(q) for r in 结果 if q in r["题"]]
        if not v: continue
        if all(v): 总对.append(q)
        elif not any(v): 总错.append(q)
        else: 翻转.append((q, sum(v), len(v)))

    print(f"\n  **每次都对**:{len(总对)} 题")
    print(f"  **每次都错**:{len(总错)} 题 —— {总错 or '(无)'}")
    print(f"     ⚠️ 这一档才是**真的能力缺口**,该去修提示词或判据")
    print(f"  **时对时错**:{len(翻转)} 题 —— "
          f"{[(q, f'{a}/{b}') for q, a, b in 翻转] or '(无)'}")
    print(f"     ⚠️ 这一档是**抖动**,单跑一次看到它红,不代表任何东西变坏了")

    print(f"\n  → 结论:**{极差} 分以内的差别读不出东西**。")
    print(f"     而 `evalrec.同版波动_下限` 现在是 "
          f"{er.同版波动_下限} —— "
          f"{'要往上改' if 极差 > er.同版波动_下限 else '这次没测出更大的,维持'}。")
    print(f"     ⚠️ **{轮} 轮仍然是小样本** —— 这个极差是下限,不是上限。")

    with open(os.path.join(od, f"{标}-summary.json"), "w", encoding="utf-8") as f:
        json.dump(dict(来路=来路, 评测=评测, 题号=题号, 轮数=轮, 分数=分, 极差=极差,
                       每次都错=总错,
                       时对时错=[dict(题=q, 对几轮=a, 共几轮=b) for q, a, b in 翻转],
                       记于=time.strftime("%Y-%m-%d %H:%M")),
                  f, ensure_ascii=False, indent=1)
    print(f"\n  明细:.feynman/jitter/{标}-*.txt  汇总:{标}-summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
