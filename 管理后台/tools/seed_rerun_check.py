#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铺数据的脚本必须**跑得起第二遍**。

## 为什么需要它

2026-09-29 一天之内,**两个** seed 脚本栽了同一个错:

    tools/seed_training.py   先删 model_artifacts,后删引用它的 deployments
    tools/seed_datasets.py   删 dataset_versions,而 training_jobs 引用着它

两处都是**外键冲突**,两处都**只有第二次起才炸**:

  · 第一次跑:库是干净的,没有东西引用那些行 → 过
  · 之后每一次:测试自己造出了引用 → ForeignKeyViolation → **整条门禁当场死**

而这一族最难发现的地方是:**第一次跑完全正常。**
> 「第一次能跑」和「跑得起第二遍」是两件事,而前者看起来完全正常。

报出来的也不是真因 —— 是一句 `ForeignKeyViolation`,
离「这个脚本不可重复跑」隔着好几层。第一次撞上时我把它记成了
「端到端间歇性假红」,而它一点都不间歇,是**第二次起必红**。

## 这条判据守的性质

每个登记的 seed 脚本,**连着跑两遍都要退 0**。

⚠️ 关键在「**两遍**」。只跑一遍的判据在这一族上是**结构性空跑** ——
坏脚本第一遍照样退 0。

⚠️ 它**会写库**,所以不进 `make contract`(那条不需要数据库)。
放在 `make test` / 手动跑。写的是 seed 数据本身 ——
这些脚本的职责就是「把夹具铺成已知状态」,再铺一遍不会弄脏别人的东西。

## 已知盲区(写下来,才和「忘了」分得开)

- **只测「能不能跑」,不测「跑完对不对」。** 一个把所有夹具都删光、
  什么都不建的脚本,连跑两遍也是绿的。真正的内容对账在各自的
  端到端测试里(它们会断言夹具的形状)。
- **顺序依赖测不出来。** 这里每个脚本自己跑两遍,不测「A 跑完再跑 B」。
  真实的 `make progress` 是按固定顺序跑的,那个顺序里的耦合
  要靠 `make progress` 自己跑一遍才暴露 —— 事实上这两个 bug
  就是那么暴露出来的。
"""
import os
import subprocess
import sys

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(根, ".venv", "bin", "python")

# ── 名单:**手写,而且每一条写清它铺什么** ─────────────────────────────
# ⚠️ 不用 glob 自动扫 `tools/seed_*.py`:那样新增一个脚本会自动进来,
# 听起来更好,实际上会让这个判据在某天变成「跑一堆不该跑的东西」。
# 手写名单的代价是要记得加 —— 所以下面额外对账:
# `tools/` 和 `services/api/app/` 里叫 seed_* 的脚本,不在名单里就报。
# 第三栏是**会造出引用行的那份端到端测试**(没有就 None)。
#
# ⚠️ **这一栏是这条判据的命门。** 第一版没有它,只是「连跑两遍」——
# 而咬合当场证明那是空跑:把 `seed_training.py` 的修复拿掉,判据照样绿。
# 因为那个 bug 要**库里先有一条 deployments 引用着那个产物**才会炸,
# 而那条引用是**测试**造出来的。前几轮跑下来引用行刚好被清掉了,
# 于是「跑两遍」这一轮什么都没验证到。
#
# > 一条「有就判、没有就跳过」的判据,在条件不具备那天会安静地变成空跑 ——
# > 而它在清单上是绿的,更难发现。
#
# 真实那次失败是**三步**:seed → 跑测试(测试造出引用)→ seed 再一遍。
# 所以判据得把中间那一步自己造出来,不能指望库恰好处在对的状态。
# ⚠️ **名单的顺序也有讲究:数据集要排在训练之前。**
# `test_training_flow` 要一个**已冻结的数据集版本**,而冻结是
# `test_datasets_flow` 干的。训练排前面的话,它靠的就是库里恰好还有
# 上一轮的残留 —— **判据自己靠残留成立,是这条判据最不该犯的错**。
名单 = [
    ("tools/seed_datasets.py", "五个数据集(考导出七道闸各自的反例)",
     "tests/e2e/test_datasets_flow.py"),
    ("tools/seed_training.py", "训练任务 + 四种模型产物(考「只有一种能部署」)",
     "tests/e2e/test_training_flow.py"),
    ("services/api/app/seed_demo.py", "演示数据:项目/成员/Prompt/知识库", None),
    ("tools/seed_evals.py", "评测题集与结果夹具", None),
    ("tools/seed_human_requests.py", "人工介入请求夹具", None),
    ("tools/seed_pricing.py", "计价表夹具", None),
    # 2026-10-08 加。⚠️ 这一份和上面几个**不是同一种 seed**:
    # 它不往库里写夹具,而是**走产品自己的接口**(建索引 → 等 Worker →
    # 跑一次试跑),为的是让三条判据在 CI 上有东西可验
    # (试跑栏目的 e2e / ifmatch 的样例 id / `#/rrun/{id}` 详情页冒烟)。
    # 所以它**要服务在跑**,而这个目标里服务是起着的。
    # 第三栏是 None:它造的东西没有别的测试去引用,
    # 「第二遍」考的是它自己的幂等(已经齐了就什么都不做)。
    ("tools/seed_retrieval_demo.py",
     "演示项目的「已就绪索引 + 一条试跑」(CI 要这份数据)", None),
]

# 名单外的 seed 脚本:**点名 + 写理由**,不许静默跳过
不跑的 = {
    # (暂时没有。有了就写在这里,并说清为什么不该连跑两遍)
}


def 找全部seed脚本():
    出 = []
    for d in ("tools", os.path.join("services", "api", "app")):
        full = os.path.join(根, d)
        if not os.path.isdir(full):
            continue
        for f in sorted(os.listdir(full)):
            # ⚠️ **把判据排掉 —— 不只是把「自己」排掉。**
            # 这个文件也叫 `seed_*.py`,于是第一版一跑就把**判据自己**
            # 报成了「没登记的 seed 脚本」。这个形状在这个仓库里反复出现过
            # (密钥扫描的规则文件匹配自己、文档匹配自己)——
            # **一个按名字选目标的判据,会选中自己。**
            #
            # 2026-10-02 又中一次,而且是另一种形状:那一版排的是
            # `f == basename(__file__)` —— **只排掉自己这一个文件**。
            # 于是新加的 `tools/seed_flag_check.py` 一进来就被报成
            # 「没登记的 seed 脚本」,CI 当场红。
            # > 它防的是「选中自己」,而真正的规则是
            # > **「判据不是被测对象」**。排掉一个文件名只解决那一个实例。
            # 所以改成按后缀排掉所有 `*_check.py`(这也顺带覆盖了自己)。
            if f.endswith("_check.py"):
                continue
            if f.startswith("seed_") and f.endswith(".py"):
                出.append(os.path.join(d, f).replace(os.sep, "/"))
    return 出


def main():
    print(f"\n\033[1m▸ 铺数据的脚本能不能跑第二遍 · 一天栽了两次的那一族{D}")
    print(f"  ⚠️ **必须跑两遍** —— 只跑一遍的判据在这一族上是结构性空跑:"
          f"坏脚本第一遍照样退 0")

    # ① 名单对账:别漏了新加的脚本
    全部 = 找全部seed脚本()
    在名单 = {p for p, _, _ in 名单}
    漏登记 = [p for p in 全部 if p not in 在名单 and p not in 不跑的]
    幽灵 = [p for p in 在名单 if not os.path.isfile(os.path.join(根, p))]
    幽灵 += [t for _, _, t in 名单
             if t and not os.path.isfile(os.path.join(根, t))]
    if not 全部:
        print(f"  {R}❌ 一个 seed 脚本都没扫到 —— **扫不到东西不是通过**{D}")
        return 1
    print(f"  扫到 {len(全部)} 个 seed 脚本,名单里 {len(名单)} 个")
    if 幽灵:
        print(f"  {R}❌ 名单里这些文件不存在了:{幽灵}{D}")
        print(f"     一条指向不存在文件的登记,会在有人重用这个名字那天悄悄放行它。")
        return 1
    if 漏登记:
        print(f"  {R}❌ 这些 seed 脚本没登记:{漏登记}{D}")
        print(f"     加进 `名单`,或者写进 `不跑的` 并**说清为什么**。")
        return 1
    if 不跑的:
        print(f"  {Y}⚠️ 明写不跑的 {len(不跑的)} 个(**点名跳过,不是没看见**):{D}")
        for p, 为什么 in 不跑的.items():
            print(f"     · {p} —— {为什么}")

    # ② 每个连跑两遍
    def 跑(相对路径, 标题, 超时=600):
        r = subprocess.run([PY, os.path.join(根, 相对路径)],
                           capture_output=True, text=True, timeout=超时, cwd=根)
        标 = f"{G}✅{D}" if r.returncode == 0 else f"{R}❌{D}"
        print(f"     {标} {标题}:退出码 {r.returncode}")
        if r.returncode != 0:
            for 行 in (r.stderr or r.stdout or "").strip().splitlines()[-4:]:
                print(f"        {行[:150]}")
        return r.returncode

    挂, 只跑了两遍 = [], []
    for 相对, 铺什么, 端到端 in 名单:
        print(f"\n  ▸ {相对} —— {铺什么}")
        if 跑(相对, "① 铺一遍") != 0:
            # ⚠️ 这条标签**不许写成「脚本本身坏了,不是可重复性问题」**。
            # 咬合时量到的正是反例:把 `seed_training.py` 的修复拿掉之后,
            # 它挂在**第 1 遍**上 —— 因为上一个脚本那一轮已经造出了引用行。
            # 同一个病,只是残留来自更早,而那条标签会把人往错的方向推。
            挂.append((相对, "**第 1 遍就挂** —— 要么脚本本身坏了,"
                            "要么库里已经有它清不掉的引用"
                            "(后者是同一个可重复性问题,只是残留来自更早的一轮;"
                            "看上面那几行报的是不是 ForeignKeyViolation)"))
            continue
        if 端到端:
            # 中间这一步是判据的**前提制造器**:让测试去造出引用行。
            # 它自己挂了也要报 —— 但要说清「挂在测试上」,别记成 seed 的错。
            if 跑(端到端, f"② 跑 {os.path.basename(端到端)}(造出引用行)") != 0:
                挂.append((相对, f"**中间那份测试 {os.path.basename(端到端)} 挂了** —— "
                                f"于是这一轮没造出引用行,"
                                f"**「第 2 遍能跑」这个结论不算数**"))
                continue
        else:
            只跑了两遍.append(相对)
        if 跑(相对, "③ 再铺一遍") != 0:
            挂.append((相对, "**第 1 遍过、第 2 遍挂 —— 不可重复跑**"
                            "(修法几乎总是清理顺序)"))
            continue
        if 端到端:
            # ④ **重铺之后再跑一遍测试。** 两个作用,都不能省:
            #
            # · 补上这条判据本来的盲区 ——「能不能跑」和「跑完对不对」是两件事。
            #   一个把夹具全删光、什么都不建的脚本,连铺两遍也是绿的。
            #
            # · 把库留在**可用状态**。少了这一步,判据自己会咬到自己:
            #   `seed_datasets` 的重铺会删掉 `test_datasets_flow` 冻结的那一版,
            #   于是下一个脚本(训练)的测试报「没有固化过的数据集版本」——
            #   **判据把前提破坏掉,然后指着后面那个说它坏了**。
            if 跑(端到端, f"④ 重铺之后再跑 {os.path.basename(端到端)}"
                        f"(夹具还是对的吗)") != 0:
                挂.append((相对, "**重铺之后夹具不对了** —— "
                                "脚本跑得起第二遍,但铺出来的东西和第一遍不等价"))

    if 挂:
        print(f"\n  {R}❌ {len(挂)} 个脚本跑不起两遍{D}")
        for 相对, 哪 in 挂:
            print(f"     {相对}:{哪}")
        print(f"\n     「第 2 遍挂」这一族的修法几乎总是**清理顺序**:"
              f"先删引用方,再删被引用方,整条外键链都要走。")
        print(f"     ⚠️ 别拿 ON DELETE CASCADE 去糊 —— 生产上那个外键"
              f"正该拦住「删掉一个还被引用的东西」。")
        return 1

    if 只跑了两遍:
        print(f"\n  {Y}⚠️ 这 {len(只跑了两遍)} 个只做了弱验证"
              f"(连铺两遍,**中间没有测试去造引用行**):{D}")
        for p in 只跑了两遍:
            print(f"     · {p}")
        print(f"     它们绿**不代表**可重复 —— 只代表这一轮库里恰好没有东西引用它们铺的行。"
              f"给它们各配一份会造出引用的端到端,这一栏才算真的验过。")
    强 = len(名单) - len(只跑了两遍)
    print(f"\n  {G}✅ {len(名单)} 个 seed 脚本过了;其中 {强} 个是"
          f"**强验证**(铺 → 跑测试造引用 → 再铺){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
