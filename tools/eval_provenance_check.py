#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测结果的来路检查 —— **「这一版考了多少分」这句话得有主语。**

## 为什么

2026-09-15 用 DeepSeek 跑了一轮完整评测,跑到第六套被停。
停之前它已经**把六份 Claude 的基线结果覆盖掉了** ——
而结果文件里**一个字段都没记是哪家模型答的**,两份数在文件里长得一模一样。

评测结果是进版本库的(`CLAUDE.md` 第 8 节:「它是这个版本在这套题上考了多少分
的历史,是**可比对**的度量」)。
**一份分不清供应商的历史,不是历史,是一堆数。**

和这个项目反复撞的是同一件事 —— 两样东西长得一样而含义完全不同:

    估算 / 复核 / 版师 / BOM     四种可信度
    快照 / 现算                  成交价不许从配置表现算
    占位符 / 真出处              「演示数据」不是出处
    抓不到 / 零分                一套跑挂了和考了 0 分
    **这一次:哪家模型跑的**

## 三条

**① 每条记录都带来路。** 盖在每一条上而不是文件头 ——
文件头会被下一次覆盖写掉,而**跑到一半被停**的时候(这天正好就是),
文件头说的和内容里的就对不上了。

**② 一份文件里不许混两家。** 混了的话这份历史既不是 A 的也不是 B 的。

**③ 基线必须是 Claude。** 2026-09-15 业务拍板:**用 Claude 做实验**。
这一条不是技术偏好,是**决定** —— 写在这儿是因为
「下次别用 DeepSeek 跑」这种话只靠记是记不住的,
而记不住的代价是又花一次钱、再覆盖一次基线。
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
基线供应商 = "claude"
FAIL = []

咬合 = [
    ("把 evalrec.dump 里 `代码=c` 那一项去掉(结果就分不出判据换过没有)",
     "每条结果都盖着代码版本"),
    ("把 eval_compare 里读 evalrec 的那两行改回自己存一份 2",
     "对比工具是**取**这份口径,不是自己另存一份"),
    ("让 能不能当结论() 在模型不同时也返回可比",
     "模型变了就不可比"),
    ("让 能不能当结论() 一律返回不可比",
     "三样都一样、分差够大,才能当结论"),
    ("把口径里「claude-haiku-4-5」那个默认值删掉(只留一个)",
     "口径里说的默认模型和代码里的分支对得上"),
    ("把某份结果文件里一条记录的「供应商」字段删掉",
     "每条结果都记着是谁跑的"),
    ("把 盖章() 里的「方案」那一项去掉",
     "**方案**也盖在每条结果上(不挂方案时写 None,不是不写)"),
    ("让 盖章() 的模型不跟着旋钮走(还读环境变量)",
     "**方案把模型换掉时,章上记的是换过的那个**"),
    ("让 能不能当结论() 在只有方案不同时也说「条件一样」",
     "只有方案不同 → 说出来它是**最干净的对照**"),
    ("把某份结果文件里一条记录的供应商改成 deepseek(制造混跑)",
     "一份文件里不混两家"),
    ("把整份结果文件的供应商都改成 deepseek",
     "基线是 claude 跑的"),
]


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 读(p):
    if p.endswith(".json"):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except Exception: pass
    return out


def main():
    print("评测结果的来路 · 检查")
    print("=" * 84)
    # **只管评测套产出的那几份。** `agent/` 下还有别的 jsonl
    # (消融、野外巡检、V1 对比),它们不是「这一版在这套题上考了多少分」的历史,
    # 由别的地方管。**一条检查管到它管不着的东西,下场是被放宽到管不住任何东西。**
    套 = [l.split("agent/")[1].split("_eval.py")[0]
          for l in open(os.path.join(ROOT, "tools", "run_evals.sh"), encoding="utf-8")
          .read().split() if l.startswith("agent/") and l.endswith("_eval.py")]
    files = [p for p in (os.path.join(ROOT, "agent", f"{x}-eval-results.jsonl")
                         for x in 套) if os.path.isfile(p)]
    tj = os.path.join(ROOT, ".feynman", "tool-eval.json")
    if os.path.isfile(tj): files.append(tj)
    if not 套:
        print("  ❌ 从 run_evals.sh 里一套都没解析出来 —— **这不叫没问题,叫没扫到**")
        sys.exit(1)
    无, 混, 非基线 = [], [], []
    条数 = 0
    for p in files:
        rs = [r for r in 读(p) if isinstance(r, dict) and "_fingerprint" not in r]
        if not rs: continue
        条数 += len(rs)
        缺 = [r for r in rs if not r.get("供应商")]
        if 缺: 无.append(f"{os.path.basename(p)}({len(缺)}/{len(rs)} 条没记)")
        家 = {r.get("供应商") for r in rs if r.get("供应商")}
        if len(家) > 1: 混.append(f"{os.path.basename(p)}:{sorted(家)}")
        别家 = 家 - {基线供应商}
        if 别家: 非基线.append(f"{os.path.basename(p)}:{sorted(别家)}")

    # **代码版本也要盖上 —— 同一天 ≠ 同一份代码。**
    # 2026-09-21 撞上了:一轮用**旧判据**跑出来的结果覆盖了基线,
    # 而文件里只有供应商/模型/日期,**分不出判据换过**,
    # 于是下次比对时那几题的差会被当成「模型变了」。
    # `agent/evalrec.py` 的 `代码()` 早就写好了(注释里明写「同一天 ≠ 同一份代码」),
    # 只是**算出来的值一个字都没写进记录** —— 一个写好了但没接上的防护,
    # 和没有这个防护,在文件上长得一模一样。现在接上了,这条盯着它别再掉。
    缺码 = []
    for p2 in files:
        rs2 = [r for r in 读(p2) if isinstance(r, dict) and "_fingerprint" not in r]
        if rs2 and not any(r.get("代码") for r in rs2):
            缺码.append(os.path.basename(p2))
    ck("每条结果都盖着代码版本", not 缺码, len(files),
       "、".join(缺码[:4]) + (f"  ……还有 {len(缺码) - 4} 份(共 {len(缺码)})"
                             if len(缺码) > 4 else "")
       + " —— **同一天 ≠ 同一份代码**:判据改过一版,结果却分不出来。"
         "重跑一次这几套就会补上"
       if 缺码 else "每份都记着是哪个提交跑的,判据换过就看得出来")

    ck("每条结果都记着是谁跑的", not 无, 条数,
       "；".join(无[:3]) if 无 else
       "**盖在每一条上不是文件头** —— 跑到一半被停时,文件头说的和内容里的会对不上")
    ck("一份文件里不混两家", not 混, len(files),
       "；".join(混[:3]) if 混 else
       "**混了的话这份历史既不是 A 的也不是 B 的**")
    # ⚠️ **检查名要写死,不许用 f-string 拼。**
    # 咬合记录的全部作用就是「拿着这个名字去脚本里找到那条检查」——
    # 运行时才拼出来的名字,`tools/bite_check.py` 找不到。
    # 这条错了很久没人发现,因为**这个文件 2026-09-16 才第一次进 check.sh** ——
    # 一条没人跑的检查,连它自己的咬合记录是错的都没人知道。
    # (同一个坑昨天在 stock_check.py 里刚踩过一次。)
    ck("基线是 claude 跑的", not 非基线, len(files),
       "；".join(非基线[:3]) if 非基线 else
       "2026-09-15 业务拍板:**用 Claude 做实验** —— "
       "写在检查里,是因为「下次别用那家跑」这种话只靠记是记不住的")

    # ── ④ **同一版跑两次分数就不一样,这件事要有人说** ──────────────
    # 这套检查原来只管「是谁跑的」。而 2026-09-16 实测撞出另一件:
    # **同一提交、同一家模型跑两次 ops_eval,29/31 → 27/31,
    # 而且红的两批完全不重叠。**
    #
    # 这条路径不暴露 temperature / top_p / seed,**波动消不掉,只能承认**。
    # 而评测结果是进版本库的历史 —— **一份没说清波动有多大的历史,
    # 会让人把噪音读成回归**。而噪音和回归在表上长得一模一样:
    # 都是一个数变成了另一个数。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import eval_compare as EC
    sys.path.insert(0, os.path.join(ROOT, "agent"))
    import evalrec as ER
    ck("对比工具说得出「同一版跑两次也会差多少」",
       EC.同版波动_下限 >= 1 and "不是阈值" in EC.同版波动_实测, 1,
       "**这个数是实测下限,不是阈值** —— "
       "只跑了两次,真实波动只会更大;它的用途只有一句:"
       "**2 分以内的差别不许当成结论说出去**")

    # ── ⑤ **「这张表怎么读」的口径只许有一处** ────────────────────────
    # 两条规矩原来分散着:一条在 `tools/eval_compare.py`(同一版跑两次也会差),
    # 一条在 `agent/gen_compare.py`(换了模型两张表不可比)。
    # **散着的口径必然漂** —— 而这两条是同一件事的两面:
    # 一张分数表**既可能被噪音骗,也可能被换了的条件骗**,
    # **而两种情况下它长得都一样**(都是「27/31」这样一个数)。
    #
    # 现在都在 `agent/evalrec.py`。这里钉两件:口径在那儿、而且用的人是取不是抄。
    # 口径里说的默认模型,要和代码里真的那两条分支对得上 ——
    # **一份说错了的口径,比没有口径更糟**:它看起来是权威的。
    _v1 = open(os.path.join(ROOT, "agent", "v1.py"), encoding="utf-8").read()
    _默认 = set(re.findall(r'ANTHROPIC_MODEL["\']?\s*,\s*["\']([\w.-]+)', _v1))
    ck("口径里说的默认模型和代码里的分支对得上",
       bool(_默认) and all(m in ER.可比的三样["模型"] for m in _默认), len(_默认),
       f"代码里有 {sorted(_默认)} 这几个默认值 —— "
       f"**默认值不止一个,而读代码的人读到其中一条就以为读懂了**")

    ck("「这张表怎么读」的口径在 evalrec 里",
       hasattr(ER, "同版波动_下限") and hasattr(ER, "可比的三样")
       and hasattr(ER, "能不能当结论"), 3,
       f"可比的三样:{sorted(ER.可比的三样)} —— "
       f"**供应商、模型、代码,任意一样变了两张表就不可比**")
    # ⚠️ **不许用 `is` 比这个数。** 第一版写的是 `EC.同版波动_下限 is ER.同版波动_下限`,
    # 咬合当场没咬住 —— 因为 CPython 把小整数缓存成同一个对象,
    # **抄一份 2 和取一份 2 用 `is` 比是分不开的**。
    # 改成查源码:**eval_compare 里不许出现自己写死的那个赋值**。
    _ecsrc = open(os.path.join(HERE, "eval_compare.py"), encoding="utf-8").read()
    _自存 = re.search(r"^同版波动_下限\s*=\s*\d", _ecsrc, re.M)
    ck("对比工具是**取**这份口径,不是自己另存一份",
       not _自存 and "evalrec" in _ecsrc
       and ER.同版波动_实测 in EC.同版波动_实测, 1,
       f"源码里自己写死了 {_自存.group(0)}" if _自存 else
       "**同一个数抄两处,改一处就开始漂** —— 而漂了的那处照样印在表上")

    # 判据自己试一遍:三样都一样才算可比
    同 = {"供应商": "claude", "模型": "claude-haiku-4-5", "代码": "abc1234"}
    # ⚠️ **检查名要写死,不许用 f-string 拼。**
    # 咬合记录拿名字去脚本里找那条检查,运行时拼出来的名字它找不到。
    # **这个坑今天第三次了**(stock_check、这个文件的「基线是 claude 跑的」,
    # 以及现在这条)—— 所以它值得单独说一句:
    # **一个方便的写法,只要它让检查名变成动态的,就会让咬合记录失效。**
    for 名, 变, 说 in (("模型变了就不可比", "模型", "同一家也分型号,成本能差一个量级"),
                       ("供应商变了就不可比", "供应商", "两家的数覆盖过一次基线"),
                       ("代码变了就不可比", "代码", "同一天 ≠ 同一份代码")):
        能, _why = ER.能不能当结论(同, {**同, 变: "别的"}, 9)
        ck(名, not 能, 1, 说)
    能, _ = ER.能不能当结论(同, 同, 9)
    ck("三样都一样、分差够大,才能当结论", 能, 1,
       "**不是一律不给结论** —— 一律不给的话,这条口径咬合测不出它在判什么")
    能小, _ = ER.能不能当结论(同, 同, ER.同版波动_下限)   # 正好等于下限,也不给结论
    ck("三样都一样但分差在波动里,也不给结论", not 能小, 1,
       f"**条件一样不等于差别是真的** —— {ER.同版波动_下限_量自}")

    # ── 方案:来路的第四样(2026-09-25 加)───────────────────────────
    # 方案没记的话,两轮用不同提示词/旋钮跑出来的结果在文件里**长得一模一样**,
    # 而分数差会被归到代码或抖动头上。
    import json as _js
    _章 = ER.盖章()
    ck("**方案**也盖在每条结果上(不挂方案时写 None,不是不写)",
       "方案" in _章 and "旋钮" in _章, len(_章), str(list(_章)))
    # ⚠️ 「字段缺失」和「这一轮没用方案」在读的时候长得一样,而它们不是一回事:
    # 前者是旧文件(那会儿还没这个字段),后者是一次真的基线跑。
    ck("不挂方案时「方案」是 None(而不是漏掉这个键)",
       _章.get("方案") is None and "方案" in _章, 1)

    _目 = os.path.join(ROOT, ".feynman", "prompt_candidates")
    os.makedirs(_目, exist_ok=True)
    _f = os.path.join(_目, "_来路自测.json")
    _js.dump({"号": "_来路自测", "旋钮": {"model": "claude-opus-5", "effort": "high"}},
             open(_f, "w", encoding="utf-8"), ensure_ascii=False)
    _旧环 = dict(os.environ)
    try:
        os.environ["LANXIU_PROVIDER"] = "claude"; os.environ.pop("ANTHROPIC_MODEL", None)
        os.environ["LANXIU_PROMPT_CANDIDATE"] = "_来路自测"
        _章2 = ER.盖章()
    finally:
        os.environ.clear(); os.environ.update(_旧环); os.remove(_f)
    # **这一条防的是「写好了但没接上」。** `模型()` 读的是环境变量,而旋钮能把模型换掉 ——
    # 不接的话章上写默认模型、实际跑的是另一个,**两者在文件里长得一模一样**。
    ck("**方案把模型换掉时,章上记的是换过的那个**",
       _章2.get("模型") == "claude-opus-5", 1, str(_章2.get("模型")))
    ck("方案号和拧了哪些旋钮都进了章",
       _章2.get("方案") == "_来路自测" and "想多深" in (_章2.get("旋钮") or ""), 1,
       str(_章2.get("旋钮")))

    _同 = {"供应商": "claude", "模型": "haiku", "代码": "aaa"}
    _能, _说 = ER.能不能当结论(dict(_同, 方案=None),
                            dict(_同, 方案="X", 旋钮="想多深:medium → high"), 分差=9)
    ck("只有方案不同 → 说出来它是**最干净的对照**",
       _能 and "最干净的一种对照" in _说, 1, _说[:60])
    _能2, _说2 = ER.能不能当结论(dict(_同, 方案="X"), dict(_同, 方案="X"), 分差=9)
    ck("方案也一样 → 不说成对照(那就是同版抖动)", _能2 and "最干净" not in _说2, 1)
    _能3, _ = ER.能不能当结论(dict(_同, 方案=None), dict(_同, 模型="opus", 方案="X"))
    ck("换了模型 → 方案再干净也不可比(模型压过方案)", not _能3, 1)

    print()
    if FAIL:
        print(f"\033[31m❌ 评测来路 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        print("   要补的话:用 Claude 重跑一轮(不花钱),结果会自动盖上来路。")
        sys.exit(1)
    print(f"\033[32m✅ {len(files)} 份结果、{条数} 条记录,来路都清楚\033[0m")


if __name__ == "__main__":
    main()
