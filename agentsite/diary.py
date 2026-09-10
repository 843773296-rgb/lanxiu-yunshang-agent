# -*- coding: utf-8 -*-
"""长期记忆:把**被纠正的**和**踩过的坑**记下来,重要动作前先读一遍。

抄自 Accio 的 self-improvement 技能(534 行)。它记七类:命令失败、被用户纠正、
用户要一个不存在的能力、外部接口挂了、知识过时、发现了更好的做法、
完成重要工作后自评。**重大任务前先读日记。**

## 为什么这东西必须存在

这个项目的教训现在都记在 `项目日志.md` 里 —— 人读得过来,智能体读不到。
于是**同一个坑会被踩第二次**,而且第二次踩的时候没人觉得眼熟。
这一段里已经发生过三回:
  · 「同一个误报出现两次」才想起来该修检查
  · 「真值必须是最终数据的函数」在 BP-03 学过,注销脱敏那儿又栽一次
  · 「判据要贴着什么才算对」讲过,预算阈值那儿又按错的判据设了一遍

## 记什么、不记什么

**记**:被纠正的、失败的、发现更好做法的 —— 这三类有「下次别再这样」的价值。
**不记**:做成了什么。做成的事在 git 和台账里,记进日记只会把它冲淡 ——
        日记要短到**每次重要动作前都愿意读一遍**,长了就没人读,
        而没人读的日记和没有日记是一回事。
"""
import json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "..", ".feynman", "diary.jsonl")
KINDS = ("被纠正", "踩坑", "更好的做法", "能力缺口")
MAX = 60          # 只留最近 60 条 —— 读得完才有人读


def write(kind, what, why, how="", where=""):
    """记一条。

    what 一句话说发生了什么;why 说**为什么那个错看起来像对的**(这条最值钱);
    how 说下次该怎么做;where 是出处(文件/提交)。
    """
    if kind not in KINDS:
        return False, f"类型只能是 {KINDS}"
    if len((why or "").strip()) < 6:
        return False, "why 必填 —— **只记「做错了什么」没用**,要记「为什么那个错看起来像对的」"
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    row = dict(日期=datetime.date.today().isoformat(), 类型=kind,
               发生了什么=what, 为什么那个错看起来像对的=why,
               下次怎么做=how or None, 出处=where or None)
    lines = []
    if os.path.exists(LOG):
        lines = [l for l in open(LOG, encoding="utf-8") if l.strip()]
    lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    with open(LOG, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX:])
    return True, f"记下了({kind})"


def read(kind=None, n=12):
    """读日记。重要动作前调一次。"""
    if not os.path.exists(LOG):
        return dict(条数=0, 说明="还没有日记")
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]
    if kind: rows = [r for r in rows if r["类型"] == kind]
    return dict(条数=len(rows), 说明="**这些是踩过的坑,不是待办** —— 看有没有和眼下这件事同类的",
                日记=rows[-n:])


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv:
        # 把这一段真实发生过的三个「同一个坑第二次」种进去 ——
        # 日记空着的话,「重要动作前先读」这条永远验不了。
        for a in [
            ("踩坑", "死控件审计把 `.act button{cursor:pointer}` 记成「.act 没绑定」",
             "审计按选择器里最后一个**类名**记账,而这条规则落在标签上;"
             "误报两次我才想起来该修的是检查,第一次我改了页面去迁就它",
             "**同一个误报出现两次,就该修检查**,不是改代码去迁就它",
             "backend/ui_audit.py"),
            ("踩坑", "TMERGE-09 的真值标着「同名不同人」,而注销脱敏在真值之后才跑,把档案抹空了",
             "真值是在数据定型**之前**标的,而报错说的是「规则判不出」——"
             "指向的是规则,不是指向真值过期",
             "**真值必须是最终数据的函数**;这条在 BP-03 学过,这是第二次",
             "backend/seed.py"),
            ("被纠正", "花费闸的两个阈值设反了:给订阅制设紧的、给按量计费设松的",
             "我按「让阈值贴近真实计价口径」定,听起来完全合理 —— "
             "但用户的判据是「哪个花我的钱」,这两个判据给出相反的答案",
             "**判据要贴着「什么才算对」,不是贴着「我以为它该怎么衡量」**",
             "agentsite/sdk.py"),
            ("踩坑", "顾问问「周叙手上有几件活」,模型绕开任务查询去查工坊工单,0 条,答「他没活」",
             "**「查无此人」和「这人没活」返回的都是 0 条** —— "
             "而侧门给出的错误答案听起来完全合理",
             "隔离不能只做在该查的那条路上;空结果要说清是哪种空",
             "backend/api.py get_workorder"),
        ]:
            print(write(*a))
        sys.exit()
    d = read()
    print(f"\n\033[1m日记 · {d['条数']} 条\033[0m")
    print("=" * 76)
    for r in d.get("日记", []):
        print(f"\n  [{r['日期']}] 【{r['类型']}】{r['发生了什么']}")
        print(f"     为什么那个错看起来像对的:{r['为什么那个错看起来像对的']}")
        if r.get("下次怎么做"): print(f"     下次:{r['下次怎么做']}")
        if r.get("出处"): print(f"     出处:{r['出处']}")
