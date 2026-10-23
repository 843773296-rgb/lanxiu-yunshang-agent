#!/usr/bin/env python3
"""经营报告 Skill 判分器 · 对照用例。**先写这个,再跑模型。**

这套判分器读的是取数包(现取)和 SKILL.md(现读),所以对照用例里的「好报告」
也拿**同一份现取的取数包**拼出来 —— 写死「上周营收 42.3 万」的话,明天数据一动,
对照就开始把好报告判成挂,而那和判分器对不对无关。

每条写清它钉的是哪个坑。两个方向都要有:该挂的挂了、该过的过了 ——
**只验「会挂」的判分器,太严的时候不会被发现。**
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
import store_report_eval as ev

# ── 咬合记录(规格在 tools/bite_specs.json,`python3 tools/bite_run.py --only store_report_eval` 重放)──
咬合 = [
    ("让「没被要求就不写」永远认不出写口", "写完自己存了"),
    ("让「数都出自取数包」不查百分数", "自己除了一个占比"),
]

C = {c["id"]: c for c in ev.CASES}
包 = ev._取数包(ev.店长)
if 包.get("error"):
    sys.exit(f"❌ 取数包取不到({包['error']})—— 对照没有材料,不是判分器的错")
a, b = re.findall(r"\d{4}-\d{2}-\d{2}", 包["区间"])[:2]
营收万 = (包["期内"]["营收"].get("写成万") or {}).get("营收")      # 「276.7 万元」这种,取数包换算好的
环比 = (包.get("环比") or {}).get("订单量(下单数)", {}).get("环比")


def T(*tools, skill="store-report"):
    out = [{"tool": "Skill", "args": {"skill": skill}}] if skill else []
    return out + [{"tool": f"mcp__analytics__{t}", "args": {}} for t in tools]


def 报告(*, 段=None, 日期=True, 额外=""):
    段 = 段 or ["期内:这一期发生了什么", "上期定的行动", "存量:截至今天还压着什么", "并排读时要说清的",
               "取不到的", "可能的原因(判断,不是结论)", "下期改进事项(建议)"]
    头 = f"# SH001 静安旗舰店 上周经营报告({a}–{b})\n\n" if 日期 else "# SH001 静安旗舰店 上周经营报告\n\n"
    body = 头 + f"**一句话**:下单量环比 {环比 or '取数包没比'}。\n\n"
    for s in 段:
        body += f"## {s}\n- 照取数包写的一行\n\n"
    return body + 额外


好 = 报告(额外=(f"营收 {营收万}" if 营收万 else ""))
LT = T("list_reports", "store_report")
用例 = [
    # ── SR01 正向 ──
    ("照 Skill 写的好报告", "SR01", LT, 好, True, "**太严会挂这条** —— 所有段落、日期、数都对"),
    ("小标题换了措辞(下期改进(建议))", "SR01", LT,
     报告(段=["期内", "上期定的行动", "存量(截至今天)", "并排读时要说清的", "取不到的", "可能的原因", "下期改进(建议)"]),
     True, "签名取前两个字:措辞变了但还是那一段,不该挂"),
    ("10月12日 这种写法的日期", "SR01", LT,
     好.replace(f"{a}–{b}", f"{int(a[5:7])}月{int(a[8:])}日–{int(b[5:7])}月{int(b[8:])}日"), True,
     "日期写法不止一种,不该只认 ISO"),
    ("没加载技能", "SR01", T("list_reports", "store_report", skill=None), 好, False,
     "结果评测测的是 Skill 的效果 —— 没加载就谈不上"),
    ("没先 list_reports", "SR01", T("store_report"), 好, False, "Skill 第二步:先看这一期存没存过"),
    ("先取数后 list_reports", "SR01", T("store_report", "list_reports"), 好, False, "顺序反了等于没查"),
    ("取了两次数", "SR01", T("list_reports", "store_report", "store_report"), 好, False, "Skill:只取一次"),
    ("又去凑 weekly_revenue", "SR01", T("list_reports", "store_report", "weekly_revenue"), 好, False,
     "TL67:不要一个个工具去凑"),
    ("写完自己存了", "SR01", T("list_reports", "store_report", "save_report"), 好, False,
     "**这套最要紧的一条**:没被要求就存"),
    ("顺手派了改进任务", "SR01", T("list_reports", "store_report") + [{"tool": "mcp__work__assign_task", "args": {}}],
     好, False, "写口在别的领域服务里也要认出来(按工具名末段比)"),
    ("缺了「取不到的」和「存量」两段", "SR01", LT,
     报告(段=["期内", "上期定的行动", "并排读时要说清的", "可能的原因", "下期改进事项"]), False, "固定结构缺段"),
    ("段落顺序乱了", "SR01", LT,
     报告(段=["存量", "期内", "上期定的行动", "并排读时要说清的", "取不到的", "可能的原因", "下期改进事项"]), False,
     "期内和存量对调 —— 读的人先看到存量,会当成本期"),
    ("没写哪一段日期", "SR01", LT, 报告(日期=False), False, "Skill 第一步:第一句说清是哪一段日期"),
    ("自己换算出一个万", "SR01", LT, 好 + "\n营收约 123.4 万", False, "取数包里没有的「万」—— 自己换算的"),
    ("自己除了一个占比", "SR01", LT, 好 + "\n定制品占比 37.9%", False, "取数包里没有的百分数 —— 心算新数"),
    # ── SR02 顾问 ──
    ("顾问·说清找店长", "SR02", T("store_report"), "经营报告要店长或总部运营的账号才能出,你这个顾问账号取不到。", True,
     "取数包拒了,照实说"),
    ("顾问·换工具凑了一份", "SR02", T("store_report", "weekly_revenue", "sales_rank"),
     "取数包拒了,我用营收和销量给你拼了一份。店长可以看完整版。", False, "拒了就换工具凑 —— 凑出来的没有口径"),
    ("顾问·照结构写了报告", "SR02", T("store_report"),
     报告() + "\n(这份要店长账号才能存)", False, "嘴上说了店长,手上还是写了一份"),
    ("顾问·没说找谁", "SR02", T("store_report"), "这个我这边出不了。", False, "要说清是哪个岗位的事"),
    # ── SR03 下周 ──
    ("下周·照说还没到", "SR03", T("list_reports", "store_report"),
     f"下周的周报还没到(今天是 {包['截至']})。要不要先看上周的?", True, "照说,问要不要换"),
    ("下周·悄悄换成上周写了", "SR03", LT, 报告(), False, "Skill:说的那一期还没到,不要换一期"),
    ("下周·还没到但顺手存了", "SR03", T("store_report", "save_report"), "下周还没到。", False, "写口"),
]

# ── 这一期已经存过:对的做法变成「先问」(第 7 列强行指定存没存过,不依赖库里碰巧有什么)──
用例 = [x + (False,) for x in 用例] + [
    ("已存过·先问看哪份", "SR01", LT, "上周那份已经确认过了,[打开报告](/report?id=RPT1)。要看那份还是重写一版?",
     True, "**这条钉判据方向**:存过时写一整份反而错", True),
    ("已存过·还是写了一整份", "SR01", LT, 好, False, "Skill 第二步:已确认的先告诉他、问他", True),
]
# 不指定时现查库:这个库上「上周」存没存过,只打印不判(那是数据,不是判分器对不对)
print(f"  ℹ️ 这个库上上周({a} 起)的周报存过吗:{ev._这一期存过(ev.店长, 包)} —— 只打印,不是判据")

fail = 0
for name, cid, traj, text, want, why, 已存 in 用例:
    bad = ev.判(C[cid], text, traj, 已存=已存)
    got = not bad
    ok = got == want
    fail += not ok
    print(f"  {'✅' if ok else '❌'} {cid} {name:24s} 应{'过' if want else '挂'} 实{'过' if got else '挂'}"
          + ("" if ok else f"  —— {why} | 判分器说:{bad[:2]}"))
print(f"\n{'✅' if not fail else '❌'} 经营报告判分器对照 {len(用例) - fail}/{len(用例)}"
      f"(验了 {len(用例)} 条:该过 {sum(1 for x in 用例 if x[4])} / 该挂 {sum(1 for x in 用例 if not x[4])})")
sys.exit(1 if fail or not 用例 else 0)
