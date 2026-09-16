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
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
基线供应商 = "claude"
FAIL = []

咬合 = [
    ("把某份结果文件里一条记录的「供应商」字段删掉",
     "每条结果都记着是谁跑的"),
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
    ck("对比工具说得出「同一版跑两次也会差多少」",
       EC.同版波动_下限 >= 1 and "不是安全线" in EC.同版波动_实测, 1,
       "**这个数是实测下限,不是阈值** —— "
       "只跑了两次,真实波动只会更大;它的用途只有一句:"
       "**2 分以内的差别不许当成结论说出去**")

    print()
    if FAIL:
        print(f"\033[31m❌ 评测来路 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        print("   要补的话:用 Claude 重跑一轮(不花钱),结果会自动盖上来路。")
        sys.exit(1)
    print(f"\033[32m✅ {len(files)} 份结果、{条数} 条记录,来路都清楚\033[0m")


if __name__ == "__main__":
    main()
