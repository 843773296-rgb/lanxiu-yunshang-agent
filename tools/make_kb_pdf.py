# -*- coding: utf-8 -*-
"""把 knowledge/ 的业务知识合成一份中文 PDF,给 Dify 做 RAG 知识库。

    python3 tools/make_kb_pdf.py          # 给 Dify:7 篇 + 省模式 → 桌面「…-Dify切片用.pdf」
    python3 tools/make_kb_pdf.py --完整   # 给人看:18 篇 + 嵌字体 → 桌面「澜绣云裳知识库.pdf」

**两种模式的落点不同,所以不会互相覆盖** —— 用户 2026-10-26 两份都要:
完整版他自己看(「可以给我完整看看知识库里究竟有什么」),省版传 Dify。

## 省模式省掉了什么(用户 10-26:「mb 多了要收费」)

量过才动手的 —— 1.54 MB 里 **69% 是字体**,内容流只占 29.2%:
  · **不嵌字体**(改用 PDF 内置的 `STSong-Light` CID 字体)—— 省掉那 69%。
    reportlab 对中文 TTF 会切成 **10 多个子集字体**,每个都带一份完整表头 + ToUnicode。
    ⚠️ **动它之前先验了 8 个汉服生僻字还提不提得出**(膝襕 襈 襳 裲裆 縠 纻 羅 蒨)——
    全过才敢用。不嵌字体靠阅读器的字体,**而生僻字可能压根不在那套编码里**,
    那就是 subfontIndex 那个坑的翻版。
  · **字号 10.5 → 8、边距 18 → 10mm、篇间不另起页** —— 页数砍到 1/4。
  · **粗体标记直接去掉** —— Dify 只抽文本,粗体是纯成本(还要切字体、占内容流)。
实测:**214 页 / 1.54 MB → 47 页 / 0.28 MB**,可提取文本 12.9 万字,生僻字一个不缺。
⚠️ 省模式**不嵌字体**,在没装中文字体的阅读器里可能显示成方块 ——
   **文本层是完好的**(Dify 抽得出),要自己看就跑 `--完整`。

⚠️ **这个脚本要 `reportlab`,而项目其余部分是纯标准库的** ——
   它是个一次性产出工具,不进 `check.sh`。没装会给一句话说清怎么装,不会崩在 import 上。
   装:`python3 -m venv .kbenv && ./.kbenv/bin/pip install reportlab`

## 默认只收 7 篇(用户 2026-10-26 拍)

原来 18 篇出来是 214 页 / 25.6 万字,用户说「大了,砍一半」。
摆了三种砍法,他选了**只留「条目型」的 7 篇**:形制 / 面料 / 工艺 / 颜色 / 配饰 /
相容矩阵 / 纹样 —— 这几篇是一条一条的「是什么 / 适合什么 / 不适合什么」,
**分段最整齐,Dify 切块效果最好**。砍掉的 11 篇是「文档形」的
(营销与运营 SOP、养护售后、版型库、量体、物料 BOM、工期成本、销售话术、竞品、电商、成长周期)
—— 它们不是一问一答的形状,本来就不好检索。
实际结果:**108 页 / 13.0 万字**,正好一半。
代价说清:问「衣服怎么洗」「怎么量体」这类问题,在这一册里检索不到。

## 两件先验过才写这个脚本的事(顺序不能反)

1. **中文字形画得出来** —— Songti.ttc 要指定 `subfontIndex`(字体集合)。
2. **文本提得出来** —— 这份 PDF 的用途是被 Dify 抽文本,
   而「看着有字、提取是空的」PDF 和好的在屏幕上长得一模一样。
   小样实测:`真丝素罗` / `二经绞` / `盘金` / `杭罗织造技艺` 全部提得出。

## 筛掉什么(用户 2026-10-26 拍「去掉溯源注记,只留业务知识」)

去掉的是**工程注记**,不是业务事实:
  · `- **出处**:…` 整行(出处名 + 链接 + 现抓核对记录)
  · 行内以 ⚠️ 开头的核查说明(「该文没核到」「这是最该降档的一条」)
  · 档位标记 `` `public` `` / `` `biz` `` / `` `scale` ``(那是内部口径,不是业务知识)
留下的是:别名 / 织法 / 手感 / 适合 / 不适合 / 注意 / 常见误解 / 判断口诀……
→ 理由:Dify 检索时那些注记是**噪声** —— 问「真丝素罗适合做什么」,
  不该让「本条未做出处查证」成为答案的一部分。

## 为 RAG 做的三件事

· **标题层级保留**(# / ## / ###)—— Dify 按标题分段,层级就是分段依据
· **每条知识是一个独立块**,块内不跨页断开(`KeepTogether`)
· **文件名里的编号保留**(MT03 / XZ02 / KF04)—— 它们是检索锚点
"""
import argparse, os, re, glob, sys

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    PageBreak, KeepTogether)
except ModuleNotFoundError:
    # **崩在 import 上和「这台机器没装它」是两件事** —— 后者该给一句能照着做的话。
    sys.exit("这个脚本要 reportlab(项目其余部分不依赖它)。装:\n"
             "  python3 -m venv .kbenv && ./.kbenv/bin/pip install reportlab\n"
             "然后用 ./.kbenv/bin/python 跑这个脚本。")

# ⚠️ **按脚本自己的位置算,不写死绝对路径** —— 这个仓库有两个检出,
#    写死会让另一个检出悄悄读到别人的 knowledge/。
# ⚠️ 在 argparse 之前就得知道是哪种模式 —— 字体注册和样式表都在模块级建好,
#    等 main 里解析完再改就来不及了。argparse 照旧做正式解析(拼错参数会报错)。
省 = "--完整" not in sys.argv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = os.path.join(ROOT, "knowledge")
OUT = os.path.expanduser("~/Desktop/澜绣云裳知识库-Dify切片用.pdf" if 省
                         else "~/Desktop/澜绣云裳知识库.pdf")
TTC = "/System/Library/Fonts/Supplemental/Songti.ttc"

# ⚠️⚠️ **subfontIndex 必须是 6 / 1,不是 0。**
# Songti.ttc 里 `subfont=0` 是 **Songti SC Black**,它**缺 20/43 个汉服生僻字** ——
# 第一版用了 0,生成出来的 PDF 里 `襕` `襈` `襳` `裲` `縠` `繡` `纻` `羅` `網` `蒨`
# 全渲染成 `\x00`(空字形),**2442 处、73 个字符丢了**。
# 而丢的恰好是这份知识库最核心的术语:膝襕 / 底襕(形制)、縠 / 纻 / 绨(面料)、
# 蒨 / 藘(染料)—— RAG 检索「膝襕」会一条都搜不到。
# > 一份「中文显示正常」的 PDF 和一份「生僻字全是空白」的 PDF,
# > 在抽查几个常用词时**长得一模一样** —— 常用字那个 subfont 也有。
# 实测同一个 ttc 里 subfont 1–7 全部 0/43 缺失;挑 6(SC Regular)+ 1(SC Bold)。
if 省:
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    正, 粗 = "STSong-Light", "STSong-Light"       # CID 字体没有粗体变体,统一用一个
else:
    pdfmetrics.registerFont(TTFont("ST", TTC, subfontIndex=6))     # Songti SC Regular
    pdfmetrics.registerFont(TTFont("STB", TTC, subfontIndex=1))    # Songti SC Bold
    正, 粗 = "ST", "STB"
_号 = (13, 10.5, 9.5, 8, 8) if 省 else (20, 15, 12.5, 10.5, 11)
_距 = (16, 13, 12, 9.6, 10) if 省 else (30, 24, 20, 17, 20)
_边 = 10 if 省 else 18

S = dict(
    h1=ParagraphStyle("h1", fontName=粗, fontSize=_号[0], leading=_距[0], spaceAfter=4 if 省 else 10),
    h2=ParagraphStyle("h2", fontName=粗, fontSize=_号[1], leading=_距[1], spaceBefore=6 if 省 else 14, spaceAfter=2 if 省 else 6),
    h3=ParagraphStyle("h3", fontName=粗, fontSize=_号[2], leading=_距[2], spaceBefore=4 if 省 else 10, spaceAfter=1 if 省 else 4),
    p=ParagraphStyle("p", fontName=正, fontSize=_号[3], leading=_距[3], alignment=TA_LEFT),
    li=ParagraphStyle("li", fontName=正, fontSize=_号[3], leading=_距[3], leftIndent=6 if 省 else 12),
    toc=ParagraphStyle("toc", fontName=正, fontSize=_号[4], leading=_距[4]),
)

# ── 筛 ────────────────────────────────────────────────────────────────
# ⚠️ **不许按「出处」这个词筛** —— 第一版那么做,结果 PDF 里还剩 103 处,
# 而逐条看过之后发现**大多数是业务内容本身**:
#   · 「顾客如果担心曳撒『没有出处』,可以用这件实物回答」← **销售话术**,RAG 最该检索到
#   · 「《大元毡罽工物记》记有…四个出处」← 染料知识
#   · 「『双膝襕』指两道膝襕…;出处没有给各种襕排隆重程度」← 形制知识
# 全仓量过:含「出处」或 URL 的 491 行里,**101 行是正文内容**(该留)、
# 373 行是整行的出处引用(该删)、17 行是裸 URL(该删)。
# > 一个「工程注记」和一句「教顾问怎么跟客户讲出处」,**在含不含「出处」这个词上
# > 长得一模一样** —— 分开它们要看**行的结构**,不是看词。
出处行 = re.compile(r"^\s*[-*>]?\s*\*?\*?出处")      # 整行就是一条出处引用
裸链 = re.compile(r"^\s*(?:→\s*)?https?://")          # 单独一行的 URL(出处折行的下半截)
续行 = re.compile(r"^\s{2,}\S")
档位 = re.compile(r"\s*`(public|biz|scale|demo|实)`")
警 = re.compile(r"^\s*[-*>]?\s*⚠️")

def 清一篇(文本):
    出, 丢出处块 = [], False
    for 行 in 文本.splitlines():
        if 出处行.match(行.lstrip()) or 裸链.match(行):
            丢出处块 = True; continue
        if 丢出处块:
            if 续行.match(行) and not 行.lstrip().startswith(("-", "*", "#")):
                continue                  # 还在出处那一段的折行里
            丢出处块 = False
        if 警.match(行):                  # 整行的核查说明
            continue
        行 = 档位.sub("", 行)             # 档位标记从标题里摘掉
        # 行内括号里的核查注记:「(2026-10-25 现抓核对:…)」这类
        行 = re.sub(r"\(\s*(?:⚠️|已逐字核实|现抓核对|该文没有|未核到)[^)]*\)", "", 行)
        出.append(行)
    return "\n".join(出)

# 中文字体里没有的符号 —— 留着会渲染成 `\x00`(PDF 里是空白、提取出来是 NUL),
# 而 NUL 进了 Dify 的分段文本里是纯噪声。**换成等义的中文或直接删**,不是删整行。
符号 = {"⚠️": "注意:", "⚠": "注意:", "✅": "[是]", "❌": "[否]", "📌": "", "⏸": "",
        "🔺": "", "🏁": "", "◻️": "", "·": "·", "“": "「", "”": "」",
        "Ⅶ": "VII", "Ⅷ": "VIII", "▏": "", "️": "", "｜": "|", "？": "?",
        "−": "-", "↘": "→", "•": "·"}

def 洗符号(s):
    for a, b in 符号.items():
        s = s.replace(a, b)
    # 兜底:任何字体里没有的,统一去掉 —— 宁可少一个符号,不要留 NUL
    return "".join(c for c in s if c == "\n" or ord(c) < 0x2000 or 0x3000 <= ord(c) <= 0xFAFF)

def esc(s):
    s = 洗符号(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def 粗体(s):
    """Markdown 的 **x** → reportlab 的 <b>x</b>(先转义再替,顺序不能反)。

    ⚠️ 最后那个 `replace("**","")` 是兜底,不是多余:md 里有**跨行的粗体**
    (`**` 开头在一行、结尾在下一行,表格单元格里尤其多),逐行处理时
    这一行只看得见半边标记,正则配不上 —— 留着就会在 PDF 里printed 成裸的 `**`。
    实测这份知识库里有 3 处这种(都在成长曲线那一篇的表格里)。
    > 一处「**粗体渲染好了**」和一处「**标记原样印出来了**」,
    > 在「这一行有内容」上长得一模一样,得去数剩下的 `**` 才看得见。
    """
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s.replace("**", "")      # 跨行粗体的半边标记:去掉,不印出来

def 一篇(路径):
    """→ (这一篇的标题, [flowable...])"""
    原 = open(路径, encoding="utf-8").read()
    行们 = 清一篇(原).splitlines()
    块, 标题 = [], os.path.basename(路径)[:-3]
    缓 = []

    def 收缓():
        if 缓:
            块.append(Paragraph(粗体(" ".join(缓)), S["p"]))
            缓.clear()

    for 行 in 行们:
        r = 行.rstrip()
        if not r.strip():
            收缓(); continue
        if r.startswith("### "):
            收缓(); 块.append(Paragraph(粗体(r[4:]), S["h3"]))
        elif r.startswith("## "):
            收缓(); 块.append(Paragraph(粗体(r[3:]), S["h2"]))
        elif r.startswith("# "):
            收缓(); 标题 = re.sub(r"\*\*|`", "", r[2:]).strip() or 标题
            # md 的一级标题有时写成「13 · 销售话术 顾问面对客户时…」——
            # 目录里只留标题本体:编号由目录自己的序号给(两个编号并排会读成两层),
            # 副标题也去掉(目录要短才扫得动)。
            标题 = re.sub(r"^\d+\s*[·.、]\s*", "", 标题)
            标题 = re.split(r"\s{2,}|\s+「", 标题)[0].strip() or 标题
            块.append(Paragraph(粗体(r[2:]), S["h1"]))
        elif r.lstrip().startswith(("- ", "* ", "|")) or re.match(r"^\s*\d+[.、]", r):
            收缓()
            t = r.lstrip()
            if t.startswith("|"):                      # 表格行:原样一行一条
                t = t.strip("|").replace("|", " · ")
                if set(t.replace(" ", "").replace("·", "")) <= {"-", ":"}:
                    continue                            # 表格的分隔行丢掉
            else:
                t = "• " + t[2:] if t[:2] in ("- ", "* ") else t
            块.append(Paragraph(粗体(t), S["li"]))
        elif r.startswith("---"):
            收缓()
        else:
            缓.append(r.strip())
    收缓()
    return 标题, 块


def 自验收(pdf, 篇数):
    """生成完自己验一遍。**「没验」必须和「验过了」分开报** ——
    这份 PDF 的用途是被 Dify 抽文本,而「看着有字、提取是空的」和好的
    在屏幕上长得一模一样,所以最该验的恰恰是**文本提不提得出来**。"""
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        print("   ⚠️ 没装 pypdf,**这一版没被验过**(装了它才会验页数 / 缺字形 / "
              "裸标记 / URL 残留 / 生僻字)—— 别把「没验」当成「验过了」。")
        return 0
    r = PdfReader(pdf)
    t = "".join((p.extract_text() or "") for p in r.pages)
    生僻 = ["膝襕", "襈", "襳", "裲裆", "縠", "纻", "羅", "蒨"]
    缺 = [w for w in 生僻 if w not in t]
    坏 = []
    if t.count(chr(0)): 坏.append(f"{t.count(chr(0))} 处缺字形(subfontIndex 挑错了)")
    if re.search(r"\*\*", t): 坏.append(f"{len(re.findall(r'[*][*]', t))} 处裸粗体标记")
    if re.search(r"https?://", t): 坏.append(f"{len(re.findall(r'https?://', t))} 处 URL 没筛掉")
    if 缺: 坏.append(f"生僻字画不出:{缺}")
    if len(t) < 50000: 坏.append(f"可提取文本只有 {len(t):,} 字 —— **提取路径可能是坏的**")
    print(f"   验收:{len(r.pages)} 页 · 可提取 {len(t):,} 字 · 验了 "
          f"{4 + len(生僻)} 项")
    for x in 坏: print(f"   ❌ {x}")
    if not 坏:
        print("   ✅ 缺字形 0 · 裸标记 0 · URL 0 · 8 个汉服生僻字都画得出、提得出")
    return len(坏)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成澜绣云裳知识库 PDF")
    ap.add_argument("--完整", action="store_true",
                    help="18 篇 + 嵌字体 + 正常排版(给人看);默认是 7 篇 + 省模式(给 Dify)")
    ap.add_argument("--out", default=OUT, help=f"落点(默认 {OUT})")
    _a = ap.parse_args()
    OUT = _a.out

    # 用户 2026-10-26 拍:**只留「条目型」的 7 篇** —— 一条一条的
    # 「是什么 / 适合什么 / 不适合什么」,分段最整齐,Dify 切块效果最好。
    # 砍掉的 11 篇是「文档形」的(营销SOP、养护售后、量体、物料BOM、工期成本…),
    # 它们不是一问一答的形状,本来就不好检索。
    # ⚠️ **按文件名前缀点名,不按关键词筛** —— 篇名会改,而编号是稳的;
    #    而且**漏掉一篇不会报错,只会安静地少一篇**,所以下面要对数。
    只要 = ("01-", "02-", "03-", "04-", "05-", "06-", "12-纹样")
    全部 = sorted(p for p in glob.glob(os.path.join(KB, "*.md"))
                  if not p.endswith("README.md"))
    篇们 = 全部 if _a.完整 else [p for p in 全部
                                 if os.path.basename(p).startswith(只要)]
    if not _a.完整 and len(篇们) != 7:
        raise SystemExit(f"点名了 7 篇,实际匹配到 {len(篇们)} 篇:"
                         f"{[os.path.basename(x) for x in 篇们]} —— "
                         f"**少一篇不会报错,只会安静地少一篇**,所以这里拦住")
    doc = SimpleDocTemplate(OUT, pagesize=A4,
                            leftMargin=_边*mm, rightMargin=_边*mm,
                            topMargin=_边*mm, bottomMargin=(_边+2)*mm,
                            title="澜绣云裳知识库", author="澜绣云裳")
    _篇名 = [os.path.basename(x)[:-3] for x in 篇们]
    故事 = [Paragraph("澜绣云裳知识库", S["h1"]),
            Paragraph(粗体(f"汉服定制业务知识 · 本册收录 **{len(篇们)} 篇**"
                            "(面料 / 形制 / 工艺 / 颜色 / 配饰 / 纹样 / 相容矩阵)。\n"
                            "本册只含业务知识:每条知识的**出处与溯源记录不在本册内**,"
                            "**流程类文档(营销与运营 SOP、养护售后、量体、物料与工期)也不在本册内** —— "
                            "它们都在项目的 knowledge/ 原文里。"), S["p"]),
            Spacer(1, 8)]
    目录, 正文 = [], []
    for p in 篇们:
        标题, 块 = 一篇(p)
        目录.append(标题)
        正文.append(Spacer(1, 6) if 省 else PageBreak())
        正文.extend(块)
    故事.append(Paragraph("<b>目录</b>", S["h2"]))
    for i, t in enumerate(目录, 1):
        故事.append(Paragraph(f"{i}. {esc(t)}", S["toc"]))
    故事.extend(正文)
    doc.build(故事)
    print(f"✅ 写好 {OUT}")
    print(f"   {len(篇们)} 篇 · {os.path.getsize(OUT)/1024/1024:.2f} MB")
    sys.exit(1 if 自验收(OUT, len(篇们)) else 0)
