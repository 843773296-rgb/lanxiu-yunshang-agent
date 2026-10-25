#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**核出处** —— 链接指的,得真的是这一条。

## 为什么要有这个

`source_check` 查的是「声称可溯源的有没有出处」,查不到**出处对不对**。
而对不对是另一件事,并且错起来更难看:

    2026-09-15 核了一遍库里 9 条链接,**3 条指向完全不同的非遗项目**:
      · MT02 云锦   → 打开是「蚕丝织造技艺(杭罗织造技艺)」
      · KF02 妆花   → 同上,也是杭罗
      · KF03 苏绣   → 打开是「蚕丝织造技艺(杭州织锦技艺)」

**一个指向别的条目的链接,比没有链接更糟。** 没链接的时候顾问知道要去问;
有链接的时候他会点开、看到一个不相干的技艺,然后以为是自己理解错了。

而这三条在库里、在检查里、在模型眼里**都长得完全正常** ——
`source_check` 说它们「溯得了源」,因为它只看链接**在不在**。

## 判据从 md 自己的正文来,不是我定的

md 里每条出处上面那一行**写着这个非遗项目叫什么**
(「非遗:南京云锦木机妆花手工织造技艺,2006 年第一批国家级非遗名录」)。
拿那个名字去比页面标题 —— **期望值是手写的,实际值是现抓的**,
不是同一个来源,所以它抓得到实现错误(`pinned_check` 的同源谬误那一条)。

## 为什么不进 check.sh

**它要联网。** 依赖外部状态的检查放进门禁会变成随机拦路 ——
和 `js_smoke`(要服务在跑)同一个道理。手动跑:

    python3 tools/verify_sources.py           # 核现有链接
    python3 tools/verify_sources.py --find 云锦 苏绣    # 找正确的链接
"""
import os, re, sys, json, subprocess, urllib.parse, time, html

# ── 咬合记录 ────────────────────────────────────────────────────────
# ⚠️ 这个脚本原来**不在门禁里**(整体要联网),所以也没有咬合记录。
# 2026-10-25 给它加了一个**不联网**的 `--自测` 口并登进 check.sh,
# 守的是「抓不到的原因分不分得清」—— 所以那一半现在要有咬合。
# > 分不出「这半能守」和「整体不能守」的话,结果就是**整条线都没人守**。
咬合 = [
    # 攻的是**被守的那个东西**(分类函数自己),不是判据。
    # ⚠️ 攻击点挑在「4xx 和 5xx 说同一句话」上:四种形状**逐个看还都『对』**
    # (每个状态码都返回了一句含 HTTP 码的话),只有那条「两者说法必须不同」会红。
    ("让 4xx 和 5xx 返回同一句话(区分白做了,而四种形状逐个看还都『对』)",
     "4xx 和 5xx 说法不同"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
KN = os.path.join(HERE, "..", "knowledge")
MDS = ("02-面料.md", "03-工艺.md", "01-形制.md", "04-配饰.md", "16-竞品与行业.md",
       "05-颜色.md", "08-量体与版型.md", "09-养护与售后.md", "12-成长与生命周期.md")   # 后四篇:扩容第二轮(2026-10-02)


def _get(url, timeout=25, 重试=2):
    """**走 curl 不走 urllib** —— 这台机器上 Python 的证书校验会失败(见 CLAUDE.md)。

    ⚠️⚠️ **HTTP 错误页也是「内容」。** 2026-10-25 栽在这儿:苏州非遗网回 **502**,
    错误页 20KB(> 500 字节的下限),于是被当成页面正文 —— 搜不到关键词,
    报成「**链接指向的不是它自己**」。
    **而这两件事该触发相反的动作**:链接指错了要去换出处;站点 502 要等等再看。
    照着错的那个结论去改 md,**会换掉一条其实正确的出处**。
    > 下面这段注释从第一天就记着同一个教训(限流那次),**而状态码这一半漏了** ——
    > 两次是同一个形状:**抓到的东西不是页面,而它长得像页面。**

    ⚠️ **抓不到 ≠ 链接坏了。** 第一版一把梭,连着请求十来次之后被限流,
    于是三条**好好的链接**被报成「打不开」——
    而「打不开」和「指向了别的条目」在这份报告上都是一行红,
    照着它去改 md 的话,会把一条对的链接删掉。
    重试两次、每次退避,还不行就**明说是抓不到,不是判它坏**。
    """
    for i in range(重试 + 1):
        # 带 UA、解 gzip、按页面声明的编码解 —— 竞品篇(2026-10-02)撞到三样:
        # 有的站不带 UA 给空壳,明华堂移动版回 gzip,政府网转载页是 GBK(text=True 直接崩)
        r = subprocess.run(["curl", "-sL", "--compressed", "-A", "Mozilla/5.0",
                            "-m", str(timeout), "-w", "\n<<<CODE:%{http_code}>>>", url],
                           capture_output=True)
        b = r.stdout or b""
        # 把尾部那行状态码摘下来(`-w` 追加在响应体之后)
        _m = re.search(rb"\n<<<CODE:(\d{3})>>>\s*$", b)
        _码 = int(_m.group(1)) if _m else 0
        if _m:
            b = b[:_m.start()]
        _get.最近码 = _码          # 调用方的提示里带上它 —— **「被限流」和「502」要说清是哪一种**
        if _码 and not (200 <= _码 < 300):
            # 非 2xx:**不拿错误页去比关键词**(见本函数开头那段)。重试,最后当抓不到。
            time.sleep(1.5 * (i + 1))
            continue
        # PDF(故宫的研究文章正文只在 PDF 里):抽文字再比。没装 pymupdf 的机器上当「抓不到」,不当「链接坏了」
        if b[:5] == b"%PDF-":
            try:
                import pymupdf
                with pymupdf.open(stream=b, filetype="pdf") as d:
                    t = "\n".join(pg.get_text() for pg in d)
                if len(t) > 500:
                    return t
            except Exception:
                pass
            time.sleep(1.5 * (i + 1))
            continue
        cs = re.search(rb"charset=[\"']?([\w-]+)", b[:4000])
        try:
            t = b.decode((cs.group(1).decode() if cs else "utf-8"), errors="replace")
        except LookupError:
            t = b.decode("utf-8", errors="replace")
        if t and len(t) > 500:
            return t
        time.sleep(1.5 * (i + 1))
    return ""


def _抓不到的原因():
    """**说清是哪一种抓不到。** 「站点限流」和「HTTP 502」在上一版都打印成
    「可能被限流」,而它们下一步不同:限流隔一会儿再跑,502 是站点自己坏了、
    等它恢复;4xx 才是链接可能真的没了。"""
    码 = getattr(_get, "最近码", 0)
    if not 码:
        return "连不上 / 超时"
    if 400 <= 码 < 500:
        return f"HTTP {码} —— **这一类才可能是链接真的没了**"
    if 码 >= 500:
        return f"HTTP {码} —— 站点自己坏了,**不是链接指错了**"
    return "内容太短,像空壳页(有的站不带 UA 就给空壳)"


def _归一(t):
    """去空白、引号统一 —— 页面用中文弯引号、md 里手打直引号,是同一个字,不该判成「页面里没有」。"""
    return re.sub(r"\s+", "", t).translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))


def 页面标题(url):
    t = _get(url)
    if not t: return None
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    if not m: return None
    return html.unescape(m.group(1)).split(" - ")[0].strip()


def 搜(kw, limit=6):
    u = ("https://www.ihchina.cn/Article/Index/getProject.html?keywords="
         + urllib.parse.quote(kw) + f"&limit={limit}&p=1")
    try:
        d = json.loads(_get(u))
    except Exception:
        return []
    return [(x.get("id"), x.get("title")) for x in d.get("list", [])]


def 条目():
    """从 md 里抓 (文件, 编码, 条目名, 出处项目名, 链接)。

    出处项目名取「→ 链接」**上面那一段**里的第一个书名式短语 ——
    md 的写法是「**非遗**:南京云锦木机妆花手工织造技艺,2006 年……」。
    """
    out = []
    for fn in MDS:
        p = os.path.join(KN, fn)
        if not os.path.isfile(p): continue
        lines = open(p, encoding="utf-8").read().split("\n")
        code = name = None
        数字 = []
        for i, line in enumerate(lines):
            m = re.match(r"^###\s+((?:XZ|MT|KF|PS|SE)\d{2})\s+(.+?)\s+`\w+`\s*$", line.strip())
            if m: code, name = m.group(1), m.group(2)
            # 竞品篇没有编码,一条一个 `### 标题`;要点里的数字也要在页面上原样出现(数是这一篇的全部价值)
            # 不带编号的 `### 标题`(竞品篇的条目、各篇末尾「讲给顾客听」的详解)—— 一条一个标题,
            # 要点里的数字也要在页面上原样出现
            详解 = line.startswith("### ") and not m
            if 详解:
                code, name, 数字 = ("竞品" if fn.startswith("16-") else "详解"), line[4:].strip(), []
            mk = re.match(r"^-\s*要点\s*[::]\s*(.+)$", line.strip())
            if code in ("竞品", "详解") and mk:
                数字 = re.findall(r"\d+(?:\.\d+)?", mk.group(1))
            # 2026-10-01 新写法:`- **出处**:出处名:页面上应出现的标题 → 链接` —— 期望值就写在同一行
            mc = re.match(r"^-\s*\*\*出处\*\*\s*[::]\s*(.+?)\s*→\s*(https?://\S+)", line.strip())
            if mc:
                左 = mc.group(1)
                标题 = re.split(r"[::]", 左, maxsplit=1)[1].strip() if re.search(r"[::]", 左) else None
                out.append((fn, code, name, ("出处", 标题, tuple(数字) if code in ("竞品", "详解") else ()),
                            mc.group(2).rstrip(").,")))
                continue
            if not line.strip().startswith("→ http"): continue
            url = re.search(r"(https?://\S+)", line).group(1).rstrip(").,")
            # 往回找这一条出处说的是什么项目
            项目 = None
            for j in range(i - 1, max(-1, i - 5), -1):
                # ⚠️ **「A 属『B』组成部分」引的是 B,不是 A。**
                # MT03 那条写的是「杭罗织造技艺属「中国蚕桑丝织技艺」组成部分」,
                # 链接指向「中国传统桑蚕丝织技艺」—— **那是对的**,
                # 而第一版把整个从句当成项目名,判它指错了。
                # **一条误报会让人去改一个本来正确的链接**,比漏报贵。
                mm = re.search(r"属[「『\"]([^」』\"]+)[」』\"]\s*组成部分", lines[j])
                if mm: 项目 = mm.group(1).strip(); break
                mm = re.search(r"\*\*非遗[^*]*\*\*[::]\s*([^,,;;((]+)", lines[j])
                if mm: 项目 = mm.group(1).strip(); break
                mm = re.search(r"[::]\s*([^,,;;((]{4,30}技艺)", lines[j])
                if mm: 项目 = mm.group(1).strip(); break
            out.append((fn, code, name, 项目, url))
    return out


def main():
    if "--自测" in sys.argv:
        # ⚠️ **这个工具整体要联网,所以进不了门禁** —— 这个口只验不联网的那一半:
        # 「抓不到」的几种原因分不分得清。分错的后果很具体:
        #   · 把 502 说成「可能被限流」 → 人隔一会儿再跑,而该去查站点
        #   · 把 502 说成「链接指错了」 → **人会去换掉一条其实正确的出处**(上一版就是这样)
        # ⚠️ **这个口在门禁里**(`check.sh` 里有一行跑 `--自测`)——
        # 整个工具要联网所以进不去,**而这一半不联网,所以它进得去**。
        # 分不出「这半能守」和「整体不能守」的话,结果就是整条线都没人守。
        # ⚠️ **断言的名字在红和绿两种情况下必须一字不差。**
        # 2026-10-25 咬合当场逮住:第一版绿时打印「✅ 4xx 和 5xx 说法不同」、
        # 红时打印「❌ 4xx 和 5xx 说的是同一句话」—— 而 `bite_run` 按「预期红」
        # 那句话去输出里找,改坏之后那句话**不在输出里**,于是判成「改坏了却没红」。
        # > 项目里的 `ck()` 天生不犯这个错:name 原样打印,只有符号和说明变。
        # > **我手写 print 时把名字本身也改了。**
        坏 = 0

        def _一条(名, ok, 说=""):
            nonlocal_坏 = 0 if ok else 1
            print(f"  {'✅' if ok else '❌'} {名}{('  ' + 说) if 说 else ''}")
            return nonlocal_坏

        for 码, 该含 in [(0, "连不上"), (404, "HTTP 404"), (502, "HTTP 502"), (200, "空壳")]:
            _get.最近码 = 码
            得 = _抓不到的原因()
            坏 += _一条(f"状态码 {码} 说得出是哪一种", 该含 in 得, 得)

        # ⚠️ **比的是「那句解释」,不是整句话。** 整句话里带状态码
        # (「HTTP 404 ——」/「HTTP 502 ——」),所以两者**永远不同**,
        # `a == b` 恒为 False、这条断言恒绿 —— 第一版就是这么写的。
        _去码 = lambda s: s.replace("404", "").replace("502", "")
        _get.最近码 = 404; _a = _抓不到的原因()
        _get.最近码 = 502; _b = _抓不到的原因()
        坏 += _一条("4xx 和 5xx 说法不同", _去码(_a) != _去码(_b),
                   "一样的话这个区分就白做了:404 可能是链接真没了,502 是站点坏了")
        # 光「不同」不够 —— **两边都写错也会不同**,所以两头各钉一条
        _get.最近码 = 404
        坏 += _一条("4xx 那句说的是「链接可能真没了」", "链接真的没了" in _抓不到的原因())
        _get.最近码 = 502
        坏 += _一条("5xx 那句说的是「站点坏了,不是链接指错」", "不是链接指错了" in _抓不到的原因())

        print(f"  {坏} 处分错" if 坏 else "  ✅ 都分得清")
        sys.exit(1 if 坏 else 0)

    if "--find" in sys.argv:
        for kw in sys.argv[sys.argv.index("--find") + 1:]:
            print(f"\n== 搜「{kw}」==")
            for i, t in 搜(kw):
                print(f"   https://www.ihchina.cn/project_details/{i}.html  →  {t}")
            time.sleep(0.4)
        return 0

    rows = 条目()
    print("核出处 —— 链接指的,得真的是这一条")
    print("=" * 96)
    print(f"md 里共 {len(rows)} 条带链接的出处。**期望值是 md 自己写的项目名,"
          f"实际值现抓** —— 两边不同源,才抓得到实现错误。\n")
    坏, 疑 = [], []
    for fn, code, name, 项目, url in rows:
        if isinstance(项目, tuple):            # 「出处」字段:标题或正文里出现写明的那个标题就算对
            标 = 项目[1]
            页 = _get(url)
            if not 页:
                _怎么 = _抓不到的原因()
                疑.append((code, name, url, f"抓不到({_怎么})"))
                print(f"  ⚠ {code} {name:10} **抓不到,不代表链接坏了**({_怎么})"
                      f" —— 隔一会儿单独再跑一次:{url}")
                continue
            正文 = html.unescape(re.sub(r"<[^>]+>", " ", 页))
            if not 标:
                疑.append((code, name, url, "出处没写页面标题")); print(f"  ⚠ {code} {name:10} 出处没写页面标题")
            elif 标 in 正文 or _归一(标) in _归一(正文):
                缺数 = [n for n in (项目[2] if len(项目) > 2 else ()) if n not in 正文]
                if 缺数:
                    print(f"  ❌ {code} {name:10} 标题对得上,但要点里的数 {缺数} 页面上**没有**")
                    坏.append((code, name, 标, url, f"(要点的数 {缺数} 页面里找不到)"))
                else:
                    print(f"  ✅ {code} {name:10} 出处写「{标}」 → 页面里有"
                          + (f";要点的数 {list(项目[2])} 也都在" if len(项目) > 2 and 项目[2] else ""))
            else:
                print(f"  ❌ {code} {name:10} 出处写「{标}」 → 页面里**没有**这几个字")
                坏.append((code, name, 标, url, "(页面里找不到)"))
            time.sleep(1.2)
            continue
        t = 页面标题(url)
        if t is None:
            _怎么 = _抓不到的原因()
            疑.append((code, name, url, f"抓不到({_怎么})"))
            print(f"  ⚠ {code} {name:10} **抓不到,不代表链接坏了**({_怎么};重试过 2 次)"
                  f" —— 隔一会儿单独再跑一次:{url}")
            continue
        if not 项目:
            疑.append((code, name, url, f"md 里没写项目名,页面是「{t}」"))
            print(f"  ⚠ {code} {name:10} md 没写项目名 → 页面是「{t}」")
            continue
        # 名字互相包含就算对上(「南京云锦木机妆花手工织造技艺」vs 页面同名)
        ok = (项目 in t) or (t in 项目) or (项目[:4] and 项目[:4] in t)
        # ⚠️ **第三档:名字不一样,但明显是同一个东西。**
        # MT03 那条 md 写的是联合国名录上的名字「中国蚕桑丝织技艺」,
        # 而站点页面叫「中国**传统桑蚕**丝织技艺」—— 同一个项目的两种叫法。
        # 判成「指错了」的话,**会有人去改一个本来正确的链接** ——
        # 而误报比漏报贵,这个项目为这句话栽过好几次(单片 60%、一刀切的阈值)。
        # 判据:两个名字的字**重合度**高到这个地步,不可能是两个不同的非遗项目。
        像 = (len(set(项目) & set(t)) / max(1, min(len(set(项目)), len(set(t))))) >= 0.8
        if ok:
            print(f"  ✅ {code} {name:10} md 说「{项目}」 → 页面是「{t}」")
        elif 像:
            疑.append((code, name, url, f"名字两种写法:md「{项目}」/ 页面「{t}」"))
            print(f"  ⚠ {code} {name:10} **名字对不上但像同一个项目** —— "
                  f"md 说「{项目}」,页面是「{t}」。**要人看一眼**,别直接改")
        else:
            print(f"  ❌ {code} {name:10} md 说「{项目}」 → 页面是「{t}」")
            坏.append((code, name, 项目, url, t))
        time.sleep(1.2)

    print("\n" + "=" * 96)
    if 坏:
        print(f"❌ {len(坏)} 条链接指向的不是它自己:")
        for code, name, 项目, url, t in 坏:
            print(f"   · {code} {name}:该指「{项目}」,实际是「{t}」")
            for i, tt in 搜(项目[:6] or name):
                if 项目 in tt or tt in 项目:
                    print(f"       正确的应该是 https://www.ihchina.cn/project_details/{i}.html")
                    break
        print("\n**一个指向别的条目的链接,比没有链接更糟** —— "
              "没链接时顾问知道要去问,有链接时他会点开、看到不相干的技艺。")
    if 疑:
        print(f"⚠ {len(疑)} 条要人看一眼:{[(a, d) for a, b, c, d in 疑]}")
    if not 坏:
        print(f"✅ {len(rows) - len(疑)} 条链接指的都是它自己")
    return 1 if 坏 else 0


if __name__ == "__main__":
    sys.exit(main())
