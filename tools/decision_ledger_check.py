#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拍板台账对账 —— 用户拍过的每一条都要有号、号要连得上、别处引用的号要真的存在。

## 为什么要有这个(执行手册 W35,2026-11-17)

用户的决定分两处记:`业务决策/业务拍板-20261112.md`(11-12 体检后那几张卡,「## 一、…」到「## 四十一、…」)
和 PRD 2.4.x 各段的表(「| 三十 | 定了什么 | 否决了什么 | 落地状态 |」,从第三十条接着记到现在)。
交接 / 执行手册 / 夜间汇总里到处写「台账第八十一条」—— 那个号是**唯一能把「用户说过」和「记在哪」接上的线**。

11-17 写这条检查时顺手逮到两处:2.4.4 的标题写「第五十九至六十二条」,段里实际记到六十七还夹着七十二;
2.4.5 标题写「六十八至七十一」,段里记到八十一。**标题是接手的人唯一会读的那一行**,它说少了十条,那十条等于没记。
文档不会因为过期而报错 —— 这条检查让它报。

## 查什么(全是结构,不判内容对不对)

1. PRD 每个 2.4.x 段:标题括号里声明的条号集合 == 段里表格实际的条号集合(两头都查:多记了没写进标题 / 标题说有段里没有)
2. 两处合起来的条号:不重号、从第一条到最大号**一个不缺**
3. 每行四格(条 / 定了什么 / 否决了什么 / 落地状态)都不许空
4. 别处(HANDOFF / 执行手册 / 夜间与白天汇总 / CLAUDE.md / 执行手册)引用的「台账第 N 条」:N 必须在已有的号里 —— 引一个不存在的号,读的人找不到
5. CLAUDE.md 点名的脚本路径都在仓库里(W35 的「CLAUDE.md 对账」那半;点名了一个不存在的脚本,接手的人会去跑它)

样本量先报:验了几段、几条、几处引用、几个路径。0 条就红 —— 「没东西可验」不是「验过了」。
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if "--根" in sys.argv:                       # 咬合 / 自测用:指到一份副本上
    ROOT = sys.argv[sys.argv.index("--根") + 1]
PRD = "澜绣云裳agent-产品需求文档.md"
卡 = "业务决策/业务拍板-20261112.md"
引用处 = ["HANDOFF.md", "CLAUDE.md", "澜绣云裳agent-执行手册-*.md", "澜绣云裳agent-夜间汇总-*.md", "澜绣云裳agent-白天汇总-*.md",
          "澜绣云裳agent-日间汇总-*.md"]
G, R, D = "\033[32m", "\033[31m", "\033[0m"

_数 = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
中文号 = r"[一二三四五六七八九十百零]+"   # 零:台账到一百零一条才第一次撞上(11-28)—— 转数() 认零,这里原来漏了


def 转数(s):
    """中文序号 → 整数:一 二 … 十 十一 … 二十 … 九十九 一百 一百零一。认不出回 None。"""
    s = s.replace("零", "")
    if not s or not re.fullmatch(中文号, s): return None
    n = 0
    if "百" in s:
        a, s = s.split("百", 1); n += (_数.get(a, 1) if a else 1) * 100
    if "十" in s:
        a, b = s.split("十", 1); n += (_数.get(a, 1) if a else 1) * 10 + (_数.get(b, 0) if b else 0)
        if b and b not in _数: return None
    elif s:
        if s not in _数: return None
        n += _数[s]
    return n


def 范围集(文):
    """标题括号里的声明 →「第五十九至六十七条、第七十二条」→ {59..67, 72}。认不出任何号回空集。"""
    出 = set()
    for a, b in re.findall(r"第?(" + 中文号 + r")(?:至(" + 中文号 + r"))?条?", 文):
        x, y = 转数(a), 转数(b) if b else None
        if x is None: continue
        出.update(range(x, (y if y is not None and y >= x else x) + 1))
    return 出


def 读(p):
    f = os.path.join(ROOT, p)
    return open(f, encoding="utf-8").read() if os.path.exists(f) else None


def 查(prd文, 卡文, 引用文们, claude文, 存在=os.path.exists):
    """纯函数。回 (bad 列表, 样本 dict)。文件文本都从外面喂,自测好喂假的。"""
    bad, 样 = [], {"段": 0, "条": 0, "引用": 0, "路径": 0}
    号们 = {}                                    # 号 → 第一次见到的位置(报重号用)
    # ── ① PRD 2.4.x 各段:标题声明 vs 段里的行 ──
    if prd文 is None:
        bad.append(f"读不到 {PRD}")
    else:
        段 = None
        段表 = {}                                 # 标题行 → (声明集, 实际集)
        for i, l in enumerate(prd文.split("\n"), 1):
            if re.match(r"^### 2\.4\.\d+ ", l):
                段 = l; 段表[段] = (范围集(l[l.find("（") + 1:] if "（" in l else l[l.find("(") + 1:]), set(), i)
                continue
            if re.match(r"^## ", l): 段 = None
            m = re.match(r"^\|\s*(" + 中文号 + r")\s*\|(.*)$", l)
            if m and 段:
                n = 转数(m.group(1))
                if n is None:
                    bad.append(f"{PRD}:{i} 条号「{m.group(1)}」认不出来"); continue
                格 = [c.strip() for c in m.group(2).strip().strip("|").split("|")]
                if len(格) < 3 or any(not c for c in 格[:3]):
                    bad.append(f"{PRD}:{i} 台账第 {n} 条四格没填满(定了什么 / 否决了什么 / 落地状态都要有,没有就写「无」)")
                段表[段][1].add(n); 样["条"] += 1
                if n in 号们: bad.append(f"台账第 {n} 条记了两次:{号们[n]} 和 {PRD}:{i}")
                else: 号们[n] = f"{PRD}:{i}"
        样["段"] = len(段表)
        for 标题, (声明, 实际, i) in 段表.items():
            if not 声明:
                bad.append(f"{PRD}:{i} 段标题没写台账条号范围:{标题[:60]}"); continue
            多 = sorted(实际 - 声明); 少 = sorted(声明 - 实际)
            if 多 or 少:
                bad.append(f"{PRD}:{i} 标题说的条号范围和段里的行对不上:{标题[:50]}…"
                           + (f" 段里多了 {多}(标题没提)" if 多 else "") + (f" 标题说有而段里没有 {少}" if 少 else ""))
    # ── ② 11-12 那几张卡:「## 一、…」 ──
    if 卡文 is None:
        bad.append(f"读不到 {卡}")
    else:
        for i, l in enumerate(卡文.split("\n"), 1):
            m = re.match(r"^## (" + 中文号 + r")(?:至(" + 中文号 + r"))?、", l)
            if not m: continue
            a, b = 转数(m.group(1)), 转数(m.group(2)) if m.group(2) else None
            if a is None: bad.append(f"{卡}:{i} 条号认不出:{l[:40]}"); continue
            for n in range(a, (b if b is not None else a) + 1):
                样["条"] += 1
                if n in 号们 and not 号们[n].startswith(PRD):
                    bad.append(f"台账第 {n} 条在 {卡} 里记了两次:{号们[n]} 和 第 {i} 行")
                号们.setdefault(n, f"{卡}:{i}")   # 和 PRD 重叠(三十至四十一两边都有)是历史形成的,不算重号
    # ── 连续性 ──
    if 号们:
        缺 = [n for n in range(1, max(号们) + 1) if n not in 号们]
        if 缺: bad.append(f"台账条号断了:缺 {缺[:12]}{'…' if len(缺) > 12 else ''}(最大 {max(号们)})—— 用户拍过的东西没地方记,或者号跳了")
    else:
        bad.append("一条台账都没读到 —— 不是「都对」,是没东西可验")
    # ── ④ 别处引用的号 ──
    for 名, 文 in 引用文们:
        for m in re.finditer(r"台账(?:第)?(" + 中文号 + r")(?:至(" + 中文号 + r"))?条?", 文):
            a, b = 转数(m.group(1)), 转数(m.group(2)) if m.group(2) else None
            if a is None: continue
            样["引用"] += 1
            for n in (a, b) if b is not None else (a,):
                if 号们 and n not in 号们:
                    bad.append(f"{名} 引了「台账第 {n} 条」,而台账里没有这一条(现有 1–{max(号们)})")
    # ── ⑤ CLAUDE.md 点名的路径 ──
    if claude文 is not None:
        for p in sorted(set(re.findall(r"`((?:tools|backend|agent|agentsite|knowledge|fakedata|mcp|管理后台)/[A-Za-z0-9_./\-]+\.(?:py|sh|js|json|plist|mjs))`", claude文))):
            样["路径"] += 1
            if not 存在(os.path.join(ROOT, p)):
                bad.append(f"CLAUDE.md 点名了 `{p}`,仓库里没有这个文件 —— 接手的人会去跑它")
    return bad, 样


def 自测():
    """人造夹具:一个全对的、再逐个弄坏,红的必须是指定那条。回 [] 或失败消息。"""
    好prd = ("## 2.4 关键产品决策\n\n### 2.4.1 2026-11-13 业务拍板（台账第三至四条）\n\n| 条 | 定了什么 | 否决了什么 | 落地状态 |\n|---|---|---|---|\n"
             "| 三 | 甲 | 乙 | 已做 |\n| 四 | 丙 | 丁 | 待做 |\n\n### 2.4.2 2026-11-14 业务拍板（台账第五条、第七至八条）\n\n| 条 | 定了什么 | 否决了什么 | 落地状态 |\n|---|---|---|---|\n"
             "| 五 | a | b | c |\n| 七 | a | b | c |\n| 八 | a | b | c |\n\n## 2.5 别的\n| 九 | 不在 2.4 里的表,不算 | x | y |\n")
    好卡 = "# 业务拍板\n## 一、第一件\n## 二、第二件\n## 三、第三件(和 PRD 重叠,允许)\n## 五至六、合记两条\n"
    好引 = [("HANDOFF.md", "用户拍了(台账第八条);另见 台账五至六")]
    好c = "跑 `tools/decision_ledger_check.py` 和 `tools/no_such_check.py`"
    存在 = lambda p: p.endswith("decision_ledger_check.py")
    bad = []
    b, 样 = 查(好prd, 好卡, 好引, 好c, 存在)
    预期 = [x for x in b if "no_such_check.py" in x]
    其它 = [x for x in b if "no_such_check.py" not in x]
    if 其它: bad.append(f"自测:全对的夹具不该红,红了 {其它}")
    if len(预期) != 1: bad.append("自测:CLAUDE.md 点名了不存在的脚本该红一条")
    if (样["段"], 样["条"], 样["引用"], 样["路径"]) != (2, 5 + 5, 2, 2):
        bad.append(f"自测:样本量不对 {样}")
    # 坏一:标题范围少说一条
    b, _ = 查(好prd.replace("台账第五条、第七至八条", "台账第五条、第七条"), 好卡, [], None)
    if not any("标题说的条号范围和段里的行对不上" in x and "[8]" in x for x in b):
        bad.append("自测:标题少说了第八条,该红「标题说的条号范围和段里的行对不上」并点名 8")
    # 坏二:号断了
    b, _ = 查(好prd, 好卡.replace("## 二、第二件\n", ""), [], None)
    if not any("台账条号断了" in x and "[2]" in x for x in b):
        bad.append("自测:删掉第二条,该红「台账条号断了」并点名 2")
    # 坏三:引了不存在的号
    b, _ = 查(好prd, 好卡, [("HANDOFF.md", "台账第九十九条")], None)
    if not any("引了「台账第 99 条」" in x for x in b):
        bad.append("自测:引用不存在的第 99 条该红")
    # 坏四:四格没填
    b, _ = 查(好prd.replace("| 四 | 丙 | 丁 | 待做 |", "| 四 | 丙 |  | 待做 |"), 好卡, [], None)
    if not any("四格没填满" in x and "第 4 条" in x for x in b):
        bad.append("自测:第四条否决格空着该红「四格没填满」")
    # 坏五:PRD 里同一号记两次
    b, _ = 查(好prd.replace("| 七 | a | b | c |", "| 七 | a | b | c |\n| 七 | 再来一次 | b | c |"), 好卡, [], None)
    if not any("记了两次" in x for x in b):
        bad.append("自测:同一号记两次该红")
    if 转数("一百零一") != 101 or 转数("二十") != 20 or 转数("十") != 10 or 转数("八十一") != 81 or 转数("壹") is not None:
        bad.append("自测:中文序号换算错了")
    if not re.fullmatch(中文号, "一百零一"):
        bad.append("自测:「一百零一」整串匹配不上中文号 —— 转数() 认零而正则漏了零,标题范围会被切成「一百」「一」(11-28)")
    return bad


# ── 咬合记录(规格在 tools/bite_specs.json)────────────────────────────────
咬合 = [
    ("把 PRD 2.4.3 标题里的「五十五至五十八」改成「五十五至五十七」(段里记了四条,标题只认三条)",
     "标题说的条号范围和段里的行对不上"),
]


def main():
    print("拍板台账对账\n" + "=" * 72)
    bad = 自测()
    if bad:
        for b in bad: print(f"  {R}❌ {b}{D}")
        print(f"{R}❌ 自测没过,真跑不算数{D}"); return 1
    引 = []
    for 模 in 引用处:
        for f in sorted(glob.glob(os.path.join(ROOT, 模))):
            引.append((os.path.relpath(f, ROOT), open(f, encoding="utf-8").read()))
    bad, 样 = 查(读(PRD), 读(卡), 引, 读("CLAUDE.md"))
    print(f"  验了 PRD {样['段']} 段 / 台账 {样['条']} 条(含两处重叠)/ 别处引用 {样['引用']} 处 / CLAUDE.md 点名路径 {样['路径']} 个;自测 7 组过")
    for b in bad: print(f"  {R}❌ {b}{D}")
    if bad:
        print(f"{R}❌ 拍板台账 {len(bad)} 处对不上{D}"); return 1
    print(f"{G}✅ 台账号连得上、标题和段一致、引用都找得到、CLAUDE.md 点名的脚本都在{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
