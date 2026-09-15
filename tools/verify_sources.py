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

HERE = os.path.dirname(os.path.abspath(__file__))
KN = os.path.join(HERE, "..", "knowledge")
MDS = ("02-面料.md", "03-工艺.md", "01-形制.md", "04-配饰.md")


def _get(url, timeout=25, 重试=2):
    """**走 curl 不走 urllib** —— 这台机器上 Python 的证书校验会失败(见 CLAUDE.md)。

    ⚠️ **抓不到 ≠ 链接坏了。** 第一版一把梭,连着请求十来次之后被限流,
    于是三条**好好的链接**被报成「打不开」——
    而「打不开」和「指向了别的条目」在这份报告上都是一行红,
    照着它去改 md 的话,会把一条对的链接删掉。
    重试两次、每次退避,还不行就**明说是抓不到,不是判它坏**。
    """
    for i in range(重试 + 1):
        r = subprocess.run(["curl", "-sL", "-m", str(timeout), url],
                           capture_output=True, text=True)
        if r.stdout and len(r.stdout) > 500:
            return r.stdout
        time.sleep(1.5 * (i + 1))
    return ""


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
        for i, line in enumerate(lines):
            m = re.match(r"^###\s+((?:XZ|MT|KF|PS|SE)\d{2})\s+(.+?)\s+`\w+`\s*$", line.strip())
            if m: code, name = m.group(1), m.group(2)
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
        t = 页面标题(url)
        if t is None:
            疑.append((code, name, url, "抓不到(可能被限流)"))
            print(f"  ⚠ {code} {name:10} **抓不到,不代表链接坏了** "
                  f"(重试过 2 次;站点会限流)—— 隔一会儿单独再跑一次:{url}")
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
