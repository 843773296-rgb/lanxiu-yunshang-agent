#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《knowledge/14-运营SOP.md》—— **门店的人照着做的流程,从代码现生成,不手写。**

知识库 B(intent `kb-b-ops-sop`)要解决的:流程已经在系统里了,只是**没有一处是人能读的** ——
「什么单不能下」写在 `knowledge/order_gate.py`,「什么单不许开裁」写在 `knowledge/muslin.py`,
判责表的数在 `knowledge/liability.py`,79 条铁律在 `prompts.py`。顾问无从得知。

## 为什么是生成的

手写一份 SOP 的下场:它会漂,而**漂了的 SOP 比没有更糟** —— 人照着它做,系统不认。
所以这里分两种取法:

  **判定**(能不能下单 / 能不能开裁)  **把真在用的那个函数调一遍**,把每一种情况的结论列成表 ——
                                      表里的「可以 / 不可以 / 判不了」就是系统会给的那个答案,不是我转述的
  **数**(公差、举证期、授权档、门槛)  从模块常量现读

`--check`:重新生成一遍和文件比,不一样就红(进 check.sh)。改了口径不重新生成,门禁拦。

## 明确不做

- **不补系统里没有的流程。** 抽已有的,新流程要业务定
- **不写成给模型看的。** 模型有铁律;这一份给人看(kb_read 也读得到,方便顾问问助手「这单为什么下不了」)
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "knowledge", "14-运营SOP.md")
sys.path[:0] = [ROOT, os.path.join(ROOT, "knowledge")]

# ── 咬合记录 ────────────────────────────────────────────────────────────
咬合 = [
    ("把判责的举证期从 6 个月改成 7 个月,但不重新生成", "SOP 和现在的代码对得上"),
    ("让开裁闸对「该试、试了、没签字」放行,但不重新生成", "SOP 和现在的代码对得上"),
]


def _短(理由):
    """理由取第一句(到「——」或句号),去掉加粗 —— 表格里放不下整段。"""
    t = re.sub(r"\*\*", "", 理由)
    return re.split(r"\s*——|。", t)[0].strip()


def _表(头, 行):
    out = ["| " + " | ".join(头) + " |", "|" + "---|" * len(头)]
    out += ["| " + " | ".join(str(x).replace("|", "/") for x in r) + " |" for r in 行]
    return "\n".join(out)


def 节_下单():
    import order_gate as G, growth
    例过期 = {"过期": True, "已过天数": 400, "允许天数": 365, "原因": "成人一年复量"}
    例有效 = {"过期": False, "已过天数": 30, "允许天数": 365, "原因": "成人一年复量"}
    情况 = [
        ("标品订单(现货成衣)", ("标品订单", None, None, None)),
        ("定制 · 不知道给谁做", ("定制品订单", None, None, None)),
        ("定制 · 着装人从没量过体", ("定制品订单", "着装人", None, None)),
        ("定制 · 量过,但复量周期算不出(缺生日或性别)", ("定制品订单", "着装人", "有", None)),
        ("定制 · 量体超期(例:成人过了 400 天)", ("定制品订单", "着装人", "有", 例过期)),
        ("定制 · 量体在有效期内(例:成人 30 天前量的)", ("定制品订单", "着装人", "有", 例有效)),
    ]
    行 = [(名, f"**{G.能不能下单(*参)[0]}**", _短(G.能不能下单(*参)[1])) for 名, 参 in 情况]
    周期 = []
    for 谁, 性别, 岁 in (("成人", "女", 30), ("孩子 6 岁", "女", 6), ("女孩 11 岁(突增期)", "女", 11),
                        ("男孩 13 岁(突增期)", "男", 13)):
        天, 为什么 = growth.recheck_cycle(性别, 岁)
        周期.append((谁, f"{天} 天", _短(为什么)))
    return f"""## 一、这一单能不能下 `出处:knowledge/order_gate.py · 能不能下单()`

**系统在下单时会自己判,下面这张表就是它的判法**(把那个函数在每种情况下真调了一遍)。
结论只有三种:**可以 / 不可以 / 判不了** —— **判不了不等于可以**。

{_表(("情况", "系统的结论", "为什么"), 行)}

- 需要量体的订单类型:{"、".join(G.需要量体的订单类型)};不需要的:{"、".join(G.无需量体的订单类型)}。
  **以后新增的订单类型默认算「要量体」** —— 漏拦一次是错尺寸,多拦一次只是多问一句
- 「不知道给谁做」时**不许挑一个候选顶上**:猜错了这一单会拿另一个人的尺寸去裁,而报表上完全正常
- 不按人裁的品类:{"、".join(f"{k}({v})" for k, v in G.不按人裁的顶级品类.items())}

### 量体多久算超期 `出处:knowledge/growth.py · recheck_cycle()`

{_表(("谁", "允许多久", "为什么"), 周期)}

超期的量体记录**不是参考值,是无效值** —— 要复量才能下单。
"""


def 节_开裁():
    import muslin as M
    行 = []
    for 该, 名 in ((True, "该试"), (None, "判不了该不该试"), (False, "不必试")):
        for 试, 签 in ((False, False), (True, False), (True, True)):
            结, 理 = M.能不能开裁(该, 试, 签)
            行.append((名, "试了" if 试 else "没试", "签了" if 签 else ("没签" if 试 else "—"),
                      f"**{结}**", _短(理)))
    return f"""## 二、什么单不许开裁 `出处:knowledge/muslin.py · 能不能开裁()`

开裁有两条路(版师点「开裁」、后台改状态),**都过同一道闸**,闸里算的就是下表。

{_表(("该不该做白坯试衣", "试了没", "客户签字没", "能不能开裁", "为什么"), 行)}

### 哪些单必须做白坯试衣

{M.范围_依据}

**重工**的门槛:装饰工序最慢 ≥ {M.装饰最慢门槛:g} 天,或单项工艺起步 ≥ {M.单项工艺门槛:g} 天。

⚠️ **判不了不等于不必试**:不知道体型标不标准,和体型标准是两件事。
"""


def 节_判责():
    import liability as L
    行 = list(L.table())      # 依据列保留 `demo` 标记 —— kb_read 按它给对客口径
    公差 = "、".join(f"{k} ±{v:g}cm" for k, v in L.公差_业务定.items())
    小, 大 = L.授权档
    拍板 = [(f"¥{钱}", *L.谁能拍板(钱)) for 钱 in (小, 大, 大 + 1)]
    拍板 = [(钱, 谁, _短(话)) for 钱, 谁, 话 in 拍板]
    return f"""## 三、售后问题谁负责 `出处:09-养护与售后.md 判定表 · knowledge/liability.py`

{_表(("问题", "谁负责", "怎么处理", "依据"), 行)}

- **公差**(业务 09-24):{公差};没单列的围度 ±{L.公差_同类默认["围度"]:g}cm、长度 ±{L.公差_同类默认["长度"]:g}cm
- **举证期**:签收起 **{L.举证期月数} 个月**内量体记录不全 → 默认我方
- 依据写 `demo` 的那几行是**演示口径**,业务没逐条确认过

### 我方要出钱时,谁能拍板 `出处:knowledge/liability.py · 谁能拍板()`

{_表(("我方支出", "谁定", "说明"), 拍板)}

**送检**:{L.送检}。

⚠️ **顾问不直接对客户承诺判责结果** —— 判责由店长定,顾问给建议。
"""


def _第一句(text):
    """规矩的第一句:开头是加粗就取加粗那段,否则取到第一个句号 —— 不在半句处切。"""
    t = text.strip()
    m = re.match(r"\*\*(.+?)\*\*", t, re.S)
    句 = m.group(1) if m else re.split(r"。|\n\n", t)[0]
    句 = _净(句)
    # 「下单前置条件,三条」这种只有标题的,把下面每一条的要点接上 —— 不然索引里看不出内容
    if re.search(r"[一二三四五六七八九十\d]+\s*(条|件事)", 句):
        要点 = []
        for l in t.split("\n"):
            m2 = re.match(r"\s*(?:-|\d+[.、)]|[①-⑩])\s*(.+)", l)
            if not m2: continue
            m3 = re.match(r"\*\*(.+?)\*\*", m2.group(1))
            要点.append(_净(m3.group(1) if m3 else re.split(r"。|——", m2.group(1))[0])[:40])
        if 要点:
            句 += ":" + ";".join(f"{i}) {x}" for i, x in enumerate(要点, 1))
    return 句


def _净(句):
    return re.sub(r"`|\*\*|\s+", lambda x: "" if x.group(0) in ("`", "**") else " ", 句).strip().rstrip("::。")


def 节_铁律():
    import prompts as P
    分组 = (("工艺顾问助手(门店)", P.KB_RULES), ("后台任务助手", P.TASK_RULES),
            ("排产助手(工坊)", P.WORKSHOP_RULES))
    见过, 段, 共 = set(), [], 0
    for 名, 规矩们 in 分组:
        行 = [(r.id, _第一句(r.text)) for r in 规矩们
              if r.scope == "铁律" and r.id not in 见过]
        见过.update(i for i, _ in 行)
        if 行:
            段.append(f"### {名}({len(行)} 条)\n\n" + _表(("编号", "规矩"), 行))
            共 += len(行)
    漏 = [r.id for r in P.ALL_RULES if r.scope == "铁律" and r.id not in 见过]
    if 漏:
        段.append("### 其他(" + str(len(漏)) + " 条)\n\n" + _表(("编号", "规矩"),
                 [(r.id, _第一句(r.text)) for r in P.ALL_RULES if r.id in 漏]))
        共 += len(漏)
    return f"""## 四、助手守的规矩(铁律索引)`出处:prompts.py`

助手不会越过下面这些线 —— 顾问知道了,就不会去要它做它不肯做的事。
共 {共} 条,只列第一句;全文在 `prompts.py`。

""" + "\n\n".join(段) + "\n"


def 生成():
    return "\n".join([
        "# 14 · 运营 SOP —— 「这种情况该走哪一步」",
        "",
        "> **这份文件是生成的,不要手改** —— `python3 tools/make_sop.py`。",
        "> 判定那几张表是**把系统真在用的函数调一遍**得出的,数从代码常量现读 ——",
        "> 改了口径不重新生成,门禁会拦(`make_sop.py --check`)。",
        "> 只抽系统里已有的流程,**不补新流程**(新流程要业务定)。",
        "",
        节_下单(), 节_开裁(), 节_判责(), 节_铁律(),
    ]).rstrip() + "\n"


def main():
    新 = 生成()
    if "--check" in sys.argv:
        print("运营 SOP · 检查")
        旧 = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else ""
        节数 = 新.count("\n## ")
        if 旧 != 新:
            差 = next((i for i, (a, b) in enumerate(zip(旧.split("\n"), 新.split("\n"))) if a != b),
                     min(len(旧.split("\n")), len(新.split("\n"))))
            print(f"  ❌ SOP 和现在的代码对得上(验了 {节数} 节)  第 {差 + 1} 行起不一样 —— "
                  "**口径改了而 SOP 没重新生成**;跑 `python3 tools/make_sop.py`")
            return 1
        for 必 in ("能不能下单", "能不能开裁", "谁负责"):
            if 必 not in 新:
                print(f"  ❌ SOP 覆盖「{必}」"); return 1
        print(f"  ✅ SOP 和现在的代码对得上(验了 {节数} 节)  下单 / 开裁 / 判责 / 铁律索引")
        return 0
    open(OUT, "w", encoding="utf-8").write(新)
    print(f"写了 {os.path.relpath(OUT, ROOT)}({len(新.splitlines())} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
