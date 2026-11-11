# -*- coding: utf-8 -*-
"""正则字符集里「有半角标点、却缺它对应的全角」—— **NFKC 反查派生,不手写标点表**。

## 为什么有这条检查(2026-11-11)

并行会话在版师判分器上抓到 `re.split(r"(?<=[,,。;;!!\n])", t)` ——
逐字打码点:`,` 和 `,` 都是 U+002C,`;` 和 `;` 都是 U+003B,`!` 和 `!` 都是 U+0021。
**作者意图明显是「半角+全角成对」,实际把半角写了两遍。**

> **`;;`(两个半角分号)和 `;；`(半角+全角)在屏幕上长得几乎一模一样。**

code review 看不出来,语法检查也不报 —— 只有逐字打码点才认得出。
后果:**全角输入下小句切不开**,于是「否定跨小句」类判据换个说法就会判错;
而 `[^。;;!!?\n]` 这种「不跨句窗口」在全角文本里会跨过中文分号和叹号。

## 这条判据怎么不枚举

两层都是派生出来的,**本文件里没有一张「该成对的标点」表**:

1. **半角→全角的对应**:扫全角区 U+FF01–FF5E 做 NFKC 反查
   (和 `agent/textmatch.带句读()` 同一套做法),外加 NFKC 覆盖不到的
   CJK 标点(「。」U+3002 / 「、」U+3001 —— 它们没有半角对应,但中文里就是那个角色)。
2. **哪些全角「该要求」**:不是我说的,是**本仓数据说的** ——
   先扫一遍全仓字符串字面量,统计**真出现过**的全角标点,只对它们要求成对。
   实测:中文句号两万多次、顿号九千多、全角分号一百多、全角逗号几十次……而
   **全角的星号 / 下划线 / 等号 / 大于号 / 井号 / 美元号 / 连字符 / 反引号**
   那一类(markdown 与代码标记的全角版)**一次都没出现过** —— 噪声自己就排除了。

   ⚠️⚠️ **这里刻意不照抄那几个字符。** 本文件自己也会被这条检查扫,
   写出来就等于让它们「出现过」,于是**判据自己变严**。
   2026-11-11 我真的这么栽了一次:修完六处之后欠债从 50 **涨到** 54,
   而「真出现过的全角」从 15 种变成 23 种 —— 那 8 种新增的,
   **全部只出现在本文件的 docstring 里,各一次**。
   > 我在注释里写「这些全角一次都没出现过」—— **而写下这句话本身,就让它们出现了。**
   这是项目那条铁律的**第四次**,只是换了领域:
   「被扫描的文件里不许写出真实的匹配串,要举例就**描述**它」
   (前三次是密钥扫描:规则写进 CLAUDE.md → 文档匹配自己;挪进 `.secretscan` →
    规则文件匹配自己;在脚本注释里举例 → 脚本匹配自己)。
   ⚠️ 修法**不是**给本文件加一条排除 —— 那是打地鼠。修法是**不写出来**。
   底下主流程里有一条检查守着这件事。
   ⚠️ 这一层是**自我维护**的:哪天项目里真的开始用全角星号,这条检查
   自动开始要求它,不用改代码。

## ⚠️ 为什么是棘轮,而不是「全部修掉」

现存 50 处里**真假混杂**:`[^。;;!!?\n]`(不跨句窗口,缺全角分号叹号)是真 bug;
`[.、]`(切 markdown 序号「1. 」「2、」)要求全角句号就没道理。
**判据分不出这两者的语义** —— 它只看得见字符。
所以:现存的登记成欠债(`欠债下限`),**只许少不许多**;新写的代码不许再犯。
⚠️ 别为了「清零」去给那些 markdown 切分硬加全角 —— 那是为了让检查变绿而改代码。
"""
import ast, re, sys, unicodedata, pathlib
from collections import Counter

欠债下限 = 44     # 11-11 实测值。修掉一处就把它减一(只许少不许多)
                  # 11-11 傍晚:50 → 44。修掉的六处:guards.py:563(豁免判据,收紧)、
                  # member_eval.py:152、以及并行会话修的 pattern_eval 1 / chat_eval 2 /
                  # talk_eval 1(都在 main 里了)。50-6=44,数字对得上 —— 这本身是一次验算。
                  # ⚠️ 还有 guards.py:783 **等用户亲手跑**(那一处方向是放宽:它是拦截判据,
                  #    窗口变窄=拦得更少),所以 44 里有它一处。用户跑完就降到 43。

# ⚠️ 咬合:每条改坏一处,**红的必须是指定那一条**(不是「反正红了」)
咬合 = [
    # ⚠️ 这两条是**换过的**。第一版打在「只对标点反查」和「统计排除正则」上,
    #    两条都「改坏了却没红」—— 不是检查瞎了,是**破坏被第二层过滤吸收了**:
    #    让字母数字也要求成对 → 反查表多出全角字母,但第二层(本仓真出现过的全角)
    #    把它们滤掉了;不排除正则 → 正则里的全角只有分号叹号问号逗号,
    #    而它们在自然语言里本来就出现过,反查表一个字都没变。
    #    > **一个「检查看不见这处破坏」和一个「这处破坏被另一层设计吸收了」,
    #    > 在那句「改坏了却没红」上长得一模一样** —— 而下一步完全相反:
    #    > 前者要修检查,后者要换攻击点。这次是后者。
    ("去掉「集合里本来就有 CJK 标点」那个前置过滤(纯 ASCII 正则也要求成对)",
     "新代码又犯了同一个"),
    # ⚠️ 这一条验的是项目第八条要素:「没东西可验」必须和「验过了」分开
    ("把 `正则函数` 集合清空(一个正则模式都扫不到)",
     "这不叫通过,这叫没测到东西"),
]

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
跳目录 = (".git", "node_modules", ".venv", "site-packages", "__pycache__", "worktrees")
正则函数 = {"compile", "split", "findall", "finditer", "search",
            "match", "fullmatch", "sub", "subn"}
_集 = re.compile(r"\[\^?((?:\\.|[^\]\\])+)\]")


def 半到全派生():
    """{半角标点: {它的全角}} —— NFKC 反查,不手写表。"""
    t = {}
    for c in range(0xFF01, 0xFF5F):
        ch = chr(c)
        半 = unicodedata.normalize("NFKC", ch)
        if len(半) == 1 and unicodedata.category(半)[0] in ("P", "S"):
            t.setdefault(半, set()).add(ch)
    for 半, 全 in ((".", "。"), (",", "、")):   # NFKC 管不到的 CJK 标点
        t.setdefault(半, set()).add(全)
    return t


def 集里的字(集):
    """字符集字面量里的字符(转义序列不算一个字符)。"""
    字, i = set(), 0
    while i < len(集):
        if 集[i] == "\\":
            i += 2; continue
        字.add(集[i]); i += 1
    return 字


def 读树(根="."):
    out = {}
    崩 = []
    for p in pathlib.Path(根).rglob("*.py"):
        if any(x in p.parts or x in str(p) for x in 跳目录):
            continue
        try:
            src = p.read_text(encoding="utf-8")
            out[p] = (src, ast.parse(src))
        except Exception as e:
            崩.append((str(p), f"{type(e).__name__}"))
    return out, 崩


def 正则字面量们(tree):
    """这棵树里所有「被 `re.*()` 当模式用」的字符串字面量节点(按 id)。"""
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in 正则函数):
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(id(arg))
    return out


def 本仓出现过的全角(trees, 半到全):
    """第一层派生:本仓**自然语言文本**里真出现过的全角标点 → {半角: {全角}}。

    ⚠️⚠️ **统计时必须排除正则模式字面量本身。** 2026-11-11 栽过:
    第一版统计了**所有**字符串字面量,包括正则。于是修这个 bug 的动作
    (往字符集里补全角)**会让「真出现过的全角」变多** ——
    修完一轮,「该要求的全角」从 15 种涨到 23 种,报出的处数从 50 涨到 54。
    > **「欠债涨了因为有人写了新的坏代码」和「欠债涨了因为我修复时
    > 让判据自己变严了」,在那个数上长得一模一样。**
    排除正则之后,「该要求哪些全角」只由自然语言文本决定 ——
    **修正则永远不会改变判据的严格度**,棘轮才守得住。
    """
    全到半 = {全: 半 for 半, 全们 in 半到全.items() for 全 in 全们}
    见 = Counter()
    for src, tree in trees.values():
        跳 = 正则字面量们(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in 跳:
                for ch in n.value:
                    if ch in 全到半:
                        见[ch] += 1
    反查 = {}
    for 全 in 见:
        反查.setdefault(全到半[全], set()).add(全)
    return 反查, 见


def 扫(根="."):
    trees, 崩 = 读树(根)
    半到全 = 半到全派生()
    反查, 见 = 本仓出现过的全角(trees, 半到全)
    出, 模式数 = [], 0
    for p, (src, tree) in trees.items():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in 正则函数):
                continue
            for arg in node.args[:1]:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    continue
                模式数 += 1
                for m in _集.finditer(arg.value):
                    字们 = 集里的字(m.group(1))
                    # 只管「本来就在处理中文标点」的集合 —— 纯 ASCII 的正则不要求成对
                    if not any(ord(c) > 0x2000 and unicodedata.category(c)[0] in ("P", "S")
                               for c in 字们):
                        continue
                    缺 = [(半, "".join(sorted(反查[半])))
                          for 半 in sorted(字们)
                          if 半 in 反查 and not (反查[半] & 字们)]
                    if 缺:
                        出.append((str(p), node.lineno, m.group(0), 缺))
    return dict(文件=trees, 崩=崩, 模式数=模式数, 反查=反查, 见=见, 出=出)


def 自测():
    """→ 坏掉的条数。每条都钉着一次真栽过的坑。"""
    坏 = []
    半到全 = 半到全派生()
    # ① 反查是派生的:全角逗号/分号/叹号/问号都得查得到
    for 半, 该有 in ((",", "，"), (";", "；"), ("!", "！"), ("?", "？"), (":", "：")):
        if 该有 not in 半到全.get(半, set()):
            坏.append(f"半到全派生():{半!r} 查不到 {该有!r}")
    # ② CJK 标点要单独补(NFKC 反查给不出「。」,只给「．」)
    if "。" not in 半到全.get(".", set()):
        坏.append("「。」U+3002 不在 NFKC 全角区,必须单独补 —— 派生器丢过它")
    # ③ **字母数字不参与**:正则里没人要 Ａ Ｂ １
    for 半 in ("A", "a", "1"):
        if 半 in 半到全:
            坏.append(f"{半!r} 不该进反查表(第一版把 ASCII 字母也要求成对,报了 56680 处)")
    # ④ 转义不算一个字符
    if "n" in 集里的字(r"\n,"):
        坏.append(r"集里的字():`\n` 里的 n 被当成了一个字符")
    # ⑤ 判定:缺全角要认出来,成对了不许报(**反向** —— 爱误报的检查会被拆掉)
    反查 = {";": {"；"}, "!": {"！"}}
    def 查(集):
        字们 = 集里的字(集)
        return [(h, "".join(反查[h])) for h in sorted(字们)
                if h in 反查 and not (反查[h] & 字们)]
    if not 查("。;;!!"):
        坏.append("`。;;!!`(半角写两遍)必须报缺 —— 这是逼出这条检查的那个形状")
    if 查("。;；!！"):
        坏.append("已经半角+全角成对的集合**不许报** —— 误报比漏报贵")
    return 坏


if __name__ == "__main__":
    if "--自测" in sys.argv:
        print("字符集全角覆盖 · 咬合")
        坏 = 自测()
        for x in 坏:
            print(f"  ✗ {x}")
        print(f"{'❌ ' + str(len(坏)) + ' 条不过' if 坏 else '✅ ' + '每一条都咬得动'}")
        sys.exit(1 if 坏 else 0)

    r = 扫(".")
    n = len(r["出"])
    print("=" * 88)
    print(f"  样本量:扫了 {len(r['文件'])} 个 .py(语法崩 {len(r['崩'])} 个)、"
          f"{r['模式数']} 个正则模式字面量")
    print(f"  本仓真出现过的全角标点 {len(r['见'])} 种"
          f"(最多的:{''.join(c for c, _ in r['见'].most_common(4))})"
          f" —— **该要求哪些全角是数据说的,不是我写的表**")
    # ⚠️ 「没东西可验」必须和「验过了」分开
    if r["模式数"] == 0 or not r["文件"]:
        print(f"{R}❌ 一个正则模式都没扫到 —— 这不叫通过,这叫没测到东西{D}")
        sys.exit(1)
    坏 = []
    # ── 自指闸:**没有哪个全角标点该只由某一个文件贡献** ────────────────────
    # 那种形状说明「这个字符是被某份文档/注释举例举出来的」,不是项目真在用它 ——
    # 而它一旦进了统计,判据就凭空变严。本文件的 docstring 2026-11-11 干过这事。
    唯一来源 = {}
    for p2, (src2, tree2) in r["文件"].items():
        跳2 = 正则字面量们(tree2)
        for nd in ast.walk(tree2):
            if isinstance(nd, ast.Constant) and isinstance(nd.value, str) and id(nd) not in 跳2:
                for ch in nd.value:
                    if ch in r["见"]:
                        唯一来源.setdefault(ch, set()).add(str(p2))
    独家 = {ch: next(iter(fs)) for ch, fs in 唯一来源.items()
            if len(fs) == 1 and r["见"][ch] <= 2}
    自家 = {ch: f for ch, f in 独家.items() if "charset_fullwidth_check" in f}
    if 自家:
        坏.append(f"**本文件自己是 {len(自家)} 个全角标点的唯一来源** —— "
                  f"docstring 里照抄了字符,判据会凭空变严。改成**描述**它,别照抄"
                  f"(项目铁律:被扫描的文件里不许写出真实匹配串)")
    elif 独家:
        print(f"{Y}  ℹ️ 有 {len(独家)} 个全角标点只由单个文件贡献且总次数 ≤2 —— "
              f"看一眼是不是某份注释举例举出来的(是的话改成描述):"
              f"{' '.join(f'{c}←{f.split(chr(47))[-1]}' for c, f in list(独家.items())[:5])}{D}")

    if n > 欠债下限:
        坏.append(f"字符集缺全角从 {欠债下限} 处涨到 {n} 处 —— 新代码又犯了同一个")
    print(f"  {'❌' if 坏 else '✅'} 字符集缺对应全角:{n} 处(欠债下限 {欠债下限})")
    if n < 欠债下限:
        print(f"{Y}  ℹ️ 已经降到 {n} 处了 —— 把本文件的 `欠债下限` 改成 {n}"
              f"(不改的话,下次有人加回来也不会红){D}")
    印 = 12
    for f, l, s, 缺 in r["出"][:印]:
        print(f"       · {f}:{l}  {s[:44]}   缺:"
              + " ".join(f"{a}→{b}" for a, b in 缺))
    if n > 印:
        print(f"       …… 上面只印了 {印} 处,**一共 {n} 处**")
    print("=" * 88)
    for x in 坏:
        print(f"{R}❌ {x}{D}")
    print(f"{G}✅ 字符集全角覆盖符合预期{D}" if not 坏 else "")
    sys.exit(1 if 坏 else 0)
