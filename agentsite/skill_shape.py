# -*- coding: utf-8 -*-
"""技能的**形状**检查 —— 一份成熟的技能该有哪几段。

不是凭感觉定的:拆了 Accio 262 份技能里「发育完全」的那 60 份
(≥200 行且带附件目录),统计它们的二级标题分布。出现最多的几段是:

    Dependencies / MCP Tool Usage   9× / 7×   —— 依赖哪些工具
    Intent Routing                  8×        —— 进来之后怎么分流
    When to Use / NOT to Use        7× / 3×   —— 边界
    General Rules / 核心规则(不可跳过) 7× / 4×  —— 不许跳的硬规矩
    Workflow / 工作流                6×        —— 步骤
    Examples                        5×        —— 例子
    Error Handling / 错误处理与降级交付 4× / 3×  —— **出错了怎么办**
    Boundaries / Safety Constraints  4× / 3×  —— 不能做什么

**我们三份技能里,「出错了怎么办」一段都没有。** 它们都只写了顺利时怎么做 ——
而顺利时怎么做是模型本来就会的,不顺利时怎么办才是技能存在的理由。

另一条结构上的差距:他们 50/60 用 `references/` 分层 ——
正文只放**路由和铁律**,具体做法放参考文件,用到哪份加载哪份。
而且明写一条「Reference Loading Contract」:
**不许照着路由表行动,必须去加载对应的参考文件。**
我们三份全塞在正文里(95–132 行),现在还塞得下,长到 300 行就塞不下了。
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, ".claude", "skills")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# (段名, 认哪些写法, 必须有吗, 为什么要有)
WANT = [
    ("什么时候用", r"什么时候用|何时使用|When to [Uu]se", True,
     "**路由责任在这里** —— 不写清楚,模型只能靠描述那一句猜"),
    ("什么时候不用", r"不[要该]用|不走这个|What NOT|NOT to [Uu]se|不是每次", True,
     "边界。只说什么时候用,它会把相邻的活也吃进来"),
    ("步骤", r"第[一二三四五六]步|步骤|Workflow|工作流|Step\s*\d", True,
     "技能的价值就是把一件事拆成固定的几步 —— 没有步骤就只是一段说明"),
    ("硬规矩", r"不[许能]|必须|一律|绝不|核心规则|General Rules", True,
     "**不许跳的那几条**。混在正文里说一句,和单列一段被遵守的程度不一样"),
    ("出错了怎么办", r"出错|错误处理|查不到|失败|降级|拿不到|Error Handling", True,
     "**顺利时怎么做是模型本来就会的,不顺利时怎么办才是技能存在的理由**"),
    ("用哪些工具", r"用什么工具|依赖|Dependencies|`mcp__|kb_|get_|_tasks\(", False,
     "写明依赖,少一个工具时才知道是缺工具还是不会用"),
    ("例子", r"例[::]|例如|比如|示例|Examples", False,
     "给一个长什么样的样本,比描述十句有用"),
]


def check_one(path):
    body = open(path, encoding="utf-8", errors="ignore").read()
    m = re.search(r"(?ms)^description:\s*(.*?)\n(?=^\w+:|^---)", body)
    desc = re.sub(r"\s+", " ", (m.group(1) if m else "")).strip()
    return dict(
        行数=body.count("\n") + 1, 描述字数=len(desc),
        有=[n for n, pat, _, _ in WANT if re.search(pat, body)],
        缺=[(n, why) for n, pat, must, why in WANT if must and not re.search(pat, body)],
        用了references=os.path.isdir(os.path.join(os.path.dirname(path), "references")))


def main():
    # Accio 那 60 份的中位数,拿来做参照 —— **不是标准,是坐标**
    print(f"\n\033[1m技能形状检查\033[0m")
    print("=" * 84)
    print(f"  参照:Accio 发育完全的 60 份技能,正文中位数 ~247 行、描述 ~425 字、"
          f"50/60 用 references/ 分层\n")
    bad = 0
    for n in sorted(os.listdir(SKILLS)):
        f = os.path.join(SKILLS, n, "SKILL.md")
        if not os.path.exists(f): continue
        r = check_one(f)
        mark = f"{G}✅{D}" if not r["缺"] else f"{R}❌{D}"
        print(f"  {mark} {n:14s} {r['行数']:4d} 行 · 描述 {r['描述字数']:3d} 字 · "
              f"references {'有' if r['用了references'] else '无'}")
        print(f"       有:{'、'.join(r['有'])}")
        for name, why in r["缺"]:
            bad += 1
            print(f"       {R}缺「{name}」{D} —— {why}")
    print()
    if bad:
        print(f"{R}❌ 共缺 {bad} 段{D}")
        sys.exit(1)
    print(f"{G}✅ 三份技能的段落都齐了{D}")


if __name__ == "__main__":
    main()
