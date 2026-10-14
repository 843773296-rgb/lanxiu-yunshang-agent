#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**题集走产线那条路** —— 模型自己调工具取材料,而不是我替它取好塞进去。

    python3 agent/triage_pipeline_eval.py --看         # 挑哪几道,不调模型
    python3 agent/triage_pipeline_eval.py --做 -n 5
    python3 agent/triage_pipeline_eval.py --重报        # 换口径不重跑模型

**不进 `check.sh`** —— 调模型、慢、有波动。门禁里放这种会变成随机拦路。

## 它和 `triage_lure_probe.py`(探针)差在哪 —— 这一条必须先说清

探针是**我替模型取好材料、拼进提示词**;这里是**模型自己调 `service_records`**。
所以:

> **探针跑出来的数是上限。** 「取不取、取得对不对」是产线上另一件事,
> 而探针把那一件**替它做掉了**。

2026-10-13 探针那三轮(不装规矩 67% → 装规矩 37% → 给足材料 0% 转人工)
**不可和这里的数并排比** —— 并排比会把「模型自己会不会取材料」这件事抹掉。

## 三件我自己要做的(用户 10-13 拍「③ 归你」时登记的)

### ① 「遮了几处」自己数 —— **它是判据,不是日志**

工具层遮蔽(`mcp/protocol.遮被判那条`,靠 env `LANXIU_JUDGING_PKG`,模型碰不到)
只把「遮了几处」打到 stderr。所以这里**独立核一遍**:
同一条差评,**带 env 调一次 / 不带 env 调一次**,比两边的差。

为 0 就**跳过那道题**。理由:题集里每道题都是**人工处置过**的
(那是它有真值的前提),所以「一处都没遮到」不是「这条没痕迹」,
而是**遮蔽认不出它** —— 答案正夹在材料里,那道题会给出一个**好得不真实**的结果。
> 「遮了几处」为 0 和「这条本来没东西可遮」,在返回值上长得一模一样。

### ② 落库记清「这一轮调没调 `service_records`」

`rating_triage.版本记()` 已经把这件事做进去了(「这一轮**没调**」也如实记)。
而这里要把它**连同判定一起落** —— 否则:
> 一个「模型看了材料才这么判」和一个「它根本没去取材料」,
> **在那条建议上长得一模一样。**

### ③ 第一轮用**训练集**,不碰验证集和测试集

产线路第一次跑一定会暴露接口问题、材料取不到、遮蔽认不出 —— 那些都要反复跑。
> **拿测试集去调试,和拿它验收,在跑出来的那个分数上长得一模一样** ——
> 而前者的分数已经没有意义了。
`agent/triage_sets_check.py` 有一条判据扫「测试集号有没有被写进别处」,
这个文件**只读训练集**。

## 明写的限定

- **这一轮判的是「模型自己取材料之后判得怎样」**,而真值是**随机填的标注**
  (演示数据),所以**不许拿它算「判得对不对」** ——
  能量的只有「取没取材料」「顶不顶得住诱导」这类**只跟模型自己比**的东西。
- 开关:`rating_triage` 模块本身**没有开关**,产线入口不调它。
  这里是「评测走产线路」,**不等于差评 AI 启用了**。
"""
import argparse, io, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "agentsite"), os.path.join(ROOT, "backend"),
           os.path.join(ROOT, "knowledge"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

G, Rd, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
题集 = os.path.join(HERE, "triage-sets.json")
存 = os.path.join(HERE, "triage-pipeline-results.jsonl")
遮蔽env = "LANXIU_JUDGING_PKG"

# ── 咬合记录(`--自测读法` 那一条进了门禁,所以它要有记录)────────────────
# ⚠️ 两条都**实跑验过**,不是「测过了」三个字。规矩是没红过的检查等于没有,
# 而咬合本身也会失效 —— 失效时和通过长得一模一样,所以把改坏的是什么写下来。
咬合 = [
    ("把 TK04 那条规矩里的四段名换成别的词(段名是从它那儿**现取**的,不是手抄的 ——"
     "手抄的话改了 TK04 这里不会跟着变,表现是「全都读不出判定」)",
     "TK04 的段名清单不认识"),
    ("把切「建议动作」那一段的那一步弄坏(让它永远切不出来)——"
     "读法会退化成只剩最松的「全文」那一层,而那正是 10-13 把一条好答案读成「读不出」的原因",
     "五种形状真的分出了四层"),
]

# ⚠️ 确定度那四档和众数函数**都从探针那边取**,这里不写第二份 ——
# 两份会漂,漂了之后两边的「全一致 / 多数 / 散了」就不是同一把尺子了。
from triage_lure_probe import 确定度档                             # noqa: E402


def 挑题(n):
    """**只从训练集挑**,按包裹号稳定序 —— 不抽随机数、不碰验证集和测试集。"""
    d = json.load(io.open(题集, encoding="utf-8"))
    训 = d["套"]["训练集"] if "套" in d else d["训练集"]
    出 = [t for t in 训 if t.get("人工档位") is not None]
    出.sort(key=lambda t: t["包裹"])
    return 出[:n]


def 身份(dbp=None):
    """取一个能看服务记录的身份 —— **跨店要「售后」**(店长只看本店,而题跨三家店)。"""
    import sqlite3
    import api
    c = sqlite3.connect(f"file:{dbp or api.DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT no,name,role,shop FROM staff "
                  "WHERE role='售后' AND status='启用' LIMIT 1").fetchone()
    c.close()
    return dict(r) if r else None


def 数遮了几处(pkg, me):
    """**独立核遮蔽** —— 走模型真正走的那一层,比「出门前」和「出门后」。

    🔺 这是本文件最要紧的一个判据(不是日志)。工具层那行「遮了 N 处」只打到 stderr,
    而我需要一个**自己能断言的数**。

    ⚠️⚠️ **第一版我核错了层,而它返回 0 处 —— 和「遮蔽没生效」长得一模一样。**
    我直接调 `api.service_records`,可那是**工具的里层**;
    遮蔽落在 **MCP 工具服务出门那一层**(`mcp/protocol.遮被判那条`,
    每个工具的返回出门前都过)。所以不管 env 设不设,`api` 那一层都原样返回。
    > 一个「遮蔽没生效」和一个**「我核的那一层根本不经过遮蔽」**,
    > 在「遮了 0 处」这个数上长得一模一样。
    📌 而这个错值得记在这儿:**我前一天才夸过那个设计「挂在出门那一层、
    不挂在某个工具上」,然后转头就按「挂在工具上」的样子去核它。**

    返回 (遮了几处, 出门后的, 出门前的)。
    """
    import api
    import rating as R
    sys.path.insert(0, os.path.join(ROOT, "mcp"))
    import protocol as _proto
    with api.as_user(me):
        出门前 = api.service_records(pkg=pkg)
    原env = os.environ.get(遮蔽env)
    try:
        os.environ[遮蔽env] = pkg
        # **走模型那条路**:协议层在每个工具返回出门前过这一道
        出门后 = _proto.遮被判那条(json.loads(json.dumps(出门前, ensure_ascii=False)))
    finally:
        if 原env is None:
            os.environ.pop(遮蔽env, None)
        else:
            os.environ[遮蔽env] = 原env
    # 「该遮几处」从**口径层**现算 —— 和协议层是两个独立来源,
    # 不是拿协议层核协议层(同源谬误)
    _, 该遮 = R.遮住处置痕迹(json.loads(json.dumps(出门前, ensure_ascii=False)), pkg)
    动了 = json.dumps(出门前, ensure_ascii=False, sort_keys=True) != \
        json.dumps(出门后, ensure_ascii=False, sort_keys=True)
    return (len(该遮) if 动了 else 0), 出门后, 出门前


def 四段名():
    """四段标题**从 TK04 那条规矩里现取**,这个文件里一个段名都不写。

    产线上模型是自由回答的,但格式并不是随便的 —— TK04 明写
    「查清后按『根因 / 建议动作 / 证据 / 置信度』四段给出草稿」。
    所以切「建议动作」那一段**是在读提示词自己定的契约**,
    不是拟合我碰巧看到的那几道输出。

    ⚠️ 手抄一份的后果不是报错:TK04 哪天改了段名,这里会**静默指向一个不存在的段**,
    表现是「全都读不出判定」—— 而那和「模型全在犹豫」长得一模一样。
    """
    import prompts
    t = prompts.按号("TK04").text
    m = re.search(r"「([^」]+)」", t)
    assert m, f"TK04 里找不到用「」括起来的段名清单,读法失效:{t}"
    名 = tuple(x.strip() for x in m.group(1).split("/") if x.strip())
    assert len(名) >= 2 and "建议动作" in 名, f"TK04 的段名清单不认识:{名}"
    return 名


def 切建议段(文):
    """切出「建议动作」那一段的 (第一句, 整段)。没有那个段标题就返回 (None, None)。"""
    名 = 四段名()
    i = 文.find("建议动作")
    if i < 0:
        return None, None
    尾 = len(文)
    for 别的 in 名:
        if 别的 == "建议动作":
            continue
        j = 文.find(别的, i + 4)
        if j >= 0:
            尾 = min(尾, j)
    段 = 文[i + 4:尾]
    # 去掉段标题自己的装饰:markdown 的 ** / 冒号 / 下划线分隔线 / 空白
    段 = re.sub(r"^[\s*:：\-—_=#]+", "", 段).strip()
    第一句 = re.split(r"[。\n]", 段, maxsplit=1)[0]
    return 第一句, 段


def 读判定(结果):
    """返回 (方式, 靠哪一层读出来, 原文)。读不出返回 (None, None, 文) —— **不猜**。

    三层,**从紧到松**,而且「靠哪一层读出来的」要记下来:

        段首  「建议动作」那一段的**第一句**里恰好一个枚举词   ← 最可信
        段内  那一整段里恰好一个
        全文  全文里恰好一个                                   ← 最松

    ⚠️⚠️ 原来只有最松那一条(「全文恰好出现一次」)。2026-10-13 跑的第五道:
    建议动作写的是「只回访」,而**同一段后半句**顺口提了「如送保养、下次免运费承诺等」
    —— 全文命中三个 → 返回 None → 报成「判定读不出」。
    **那不是模型在犹豫,是我的读法不够。**

    > 一个「模型说了两种、定不下来」和一个「它定了一种、顺口提了别的选项」,
    > **在「全文里出现两个枚举词」这件事上长得一模一样。**

    所以这里不是把读法放松,是**把混在一条里的两件事拆开**:
    定下的那一种从**最紧的一层**读,而「靠第几层读到的」一并报出来 ——
    靠「全文」那一层救回来的那些,可信度本来就低,**不许和段首那些混成一个数**。
    `--自测读法` 用自造的五种形状钉住这件事(见 `自测读法()`)。
    """
    import rating as R

    def 恰好一个(t):
        if not t:
            return None
        命 = [w for w in R.处理方式 if w in t]
        return 命[0] if len(命) == 1 else None

    文 = str((结果 or {}).get("answer") or (结果 or {}).get("text") or 结果 or "")
    第一句, 段 = 切建议段(文)
    for 层, t in (("段首", 第一句), ("段内", 段), ("全文", 文)):
        w = 恰好一个(t)
        if w:
            return w, 层, 文
    return None, None, 文


def 自测读法():
    """**判据自己造出它要验的那五种形状** —— 不等着在真跑里碰上。

    为什么要有这一关:读法要是失效(TK04 改段名、正则写错),表现是
    「这一批判定全读不出」,而那和「模型这一批全在犹豫」在结果上长得一模一样。
    所以 `--做` 之前先过这一关,**不过就拒跑** —— 别产出一堆不知道是谁的 None。

    形状 ② 是 10-13 真跑里出现过的那一道,**旧读法在它上面给 None**。
    """
    import rating as R
    甲, 乙, 丙 = R.处理方式[1], R.处理方式[2], R.处理方式[4]   # 不手抄名字
    形 = [
        ("①四段齐、段首就是方式名",
         f"**根因**\n质检漏了。\n\n**建议动作**\n\n{甲}。重新整烫后回收处理。\n\n"
         f"**证据**\n· 到店 12-04\n\n**置信度**\n中。", (甲, "段首")),
        ("②段首定了一种、同段顺口提了另两种(真跑里出现过,旧读法给 None)",
         f"建议动作\n-------\n{R.处理方式[0]}。先沟通了解承诺日期,"
         f"后续由店长判断是否追加补偿(如{乙}、下次{R.处理方式[3]}承诺等)。\n\n证据\n---\n· 无",
         (R.处理方式[0], "段首")),
        ("③段首是空话、方式名在段的后半",
         f"**建议动作**\n需要分档处理。考虑到金额,这里走{丙},并指定批准人。\n\n**证据**\n略",
         (丙, "段内")),
        ("④根本没按四段格式、全文只出现一种",
         f"我建议{乙},因为客户只是嫌痕迹没除净。", (乙, "全文")),
        ("⑤没按四段格式、全文出现两种 —— 真读不出",
         f"可以{甲},也可以{丙},看店长怎么定。", (None, None)),
    ]
    坏 = []
    for 名, 文, 期 in 形:
        方式, 层, _ = 读判定({"answer": 文})
        好 = (方式, 层) == 期
        print(f"  {G + '✅' + D if 好 else Rd + '❌' + D} {名}\n"
              f"      期望 {期}  实得 {(方式, 层)}")
        if not 好:
            坏.append(名)
    吐 = {读判定({"answer": f})[1] for _, f, _ in 形}
    层够 = {"段首", "段内", "全文", None} <= 吐
    print(f"  {G + '✅' + D if 层够 else Rd + '❌' + D} "
          f"五种形状真的分出了四层(段首/段内/全文/读不出):{sorted(map(str, 吐))}")
    if 坏 or not 层够:
        print(f"\n{Rd}❌ 读法自测没过 —— **不跑模型**。"
              f"读法失效时「全读不出」和「模型全在犹豫」长得一模一样{D}")
        return False
    print(f"  {G}读法自测过了(段名从 TK04 现取:{'/'.join(四段名())}){D}")
    return True


def 跑(n, me, 轮数=3, 看=False):
    """每道题跑 `轮数` 遍,取众数。**两个口径都报,不许只报一个。**

    ⚠️⚠️ 为什么要多轮:2026-10-13 单轮跑的时候,同一条题两次跑建议
    从「送保养」变成了「免次改衣」—— **产线路也抖**。
    探针那三轮靠取众数把这件事压掉了,而这里当时还是单轮:
    > 一个「模型改了主意」和一个「这一轮恰好抽到另一个答案」,
    > **在单轮那一个答案上长得一模一样。**

    ⚠️ 众数函数**直接从探针那边 import**,不在这里写第二份 ——
    两份会漂,而漂了之后两边的数就不可比了(那正是取众数要解决的事)。

    **两个口径**(刻意分开,因为它们答的不是同一个问题):
      方式级   字面答案变不变(「送保养」→「免次改衣」算变了)
      档位级   实质分歧变不变(这两种同属「给东西不出钱」,**同一档**)
    10-13 看到的那次抖动恰好是**同档内**的 —— 只报方式级会高估分歧,
    只报档位级会把它藏起来。
    """
    import triage_sets as T
    import rating_triage as RT
    from triage_lure_probe import 众数
    题们 = 挑题(n)
    print(f"训练集前 {len(题们)} 道 × **{轮数} 轮**(**只读训练集** —— 验证集和测试集不碰)")
    print(f"  身份:{me['role']} {me['name']}(跨店看服务记录要「售后」)")
    print(f"  要调模型 {len(题们) * 轮数} 次")
    print(f"  ⚠️ 这一轮**模型自己调工具取材料** —— 和探针那三轮"
          f"(我替它取好塞进去)**不可并排比**:探针那个数是**上限**")
    for t in 题们:
        print(f"    {t['包裹']}  {t['星']}星  人工档位={t['人工档位']}  {t['顾客说'][:28]}")
    if 看:
        print(f"\n（--看 模式,一次模型都没调。要真跑加 --做）")
        return 0
    if not 自测读法():
        return 1
    记, 断 = [], None
    for i, t in enumerate(题们, 1):
        pkg = t["包裹"]
        遮了, _, _ = 数遮了几处(pkg, me)
        if 遮了 == 0:
            # 见 `数遮了几处` 的说明:题集里每道题都是人工处置过的,
            # 所以「一处没遮到」= 遮蔽认不出它 = 答案夹在材料里。**跳过,不猜。**
            print(f"  [{i}/{len(题们)}] {pkg}  {Rd}❌ 一处都没遮到 —— "
                  f"答案可能夹在材料里,这道跳过{D}")
            continue
        轮们 = []
        for k in range(1, 轮数 + 1):
            try:
                bp, case, 结果, 版本 = RT.跑一条(f"EVAL-{pkg}-R{k}", pkg, me)
            except Exception as e:                                 # noqa: BLE001
                断 = f"第 {i} 道({pkg})第 {k} 轮挂了:{type(e).__name__}: {e}"
                print(f"  {Y}⚠️ {断}{D}")
                break
            方式, 层, 文 = 读判定(结果)
            # ⚠️⚠️ **原来这里我自己从结果里挖轨迹算一遍,而两个字段名都猜错了**
            # (`trace` / `steps` 都不存在)→ 取到 None → `取了材料吗(None)` 返回 False
            # → 报出「第一条就没去取材料」,而那是**我的 bug,不是模型的问题**。
            # > 一个「模型没去取材料」和一个「我没找到轨迹在哪个字段」,
            # > **在那个 False 上长得一模一样。**
            # 而 `rating_triage.版本记()` **自己就把这件事算进去了**
            # (「这一轮调了 / **没调** service_records」)—— 我重算一遍,
            # **那不是双重保险,是第二份会漂的实现**。所以从版本记里读。
            轮们.append(dict(轮=k, 方式=方式, 读的层=层, 取了材料="没调" not in 版本,
                            版本记=版本, 断点号=bp, case=case, 原文=文[:600]))
            print(f"  [{i}/{len(题们)}] 第{k}轮  建议={方式 or '(读不出)'}"
                  f"{'·' + 层 if 层 else ''}  "
                  f"{'✅调了材料' if 轮们[-1]['取了材料'] else Rd + '❌没调材料' + D}")
            # **每一轮都落**,不是每道题落一次 —— 中途被 kill 也留得住已跑的轮
            io.open(存 + ".partial", "w", encoding="utf-8").write(
                json.dumps(dict(跑于=time.strftime("%Y-%m-%d %H:%M:%S"),
                                这是半轮="还在跑,或者被中断了",
                                做完的题=len(记), 这道已跑=len(轮们), 明细=记,
                                这道=dict(包裹=pkg, 轮们=轮们)), ensure_ascii=False))
        if not 轮们:
            if 断:
                break
            continue
        方式们 = [x["方式"] for x in 轮们]
        方式众, 方式确 = 众数(方式们)
        档们 = [T.档(x) for x in 方式们]
        档众, 档确 = 众数(档们)
        行 = dict(包裹=pkg, 星=t["星"], 人工档=t["人工档"], 人工档位=t["人工档位"],
                  遮了几处=遮了, 跑了几轮=len(轮们),
                  方式众数=方式众, 方式确定度=方式确,
                  档众数=档众, 档确定度=档确,
                  取了几轮=sum(1 for x in 轮们 if x["取了材料"]),
                  读的层们=[x["读的层"] for x in 轮们],
                  轮们=轮们)
        记.append(行)
        print(f"      → 方式众数={方式众 or '(没有)'}·{方式确}  "
              f"档众数={档众 if 档众 is not None else '(没有)'}·{档确}"
              f"{'  ' + Y + '⚠️ 字面变了但同档' + D if 方式确 != '全一致' and 档确 == '全一致' else ''}")
        if 断:
            break
    if not 记:
        print(f"\n{Rd}❌ 一道都没跑完 —— 什么都不存{D}")
        return 1
    with io.open(存, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(跑于=time.strftime("%Y-%m-%d %H:%M:%S"),
                                走的是="产线路(模型自己调工具取材料)", 套="训练集",
                                轮数=轮数, 道数=len(记), 挑了几道=len(题们), 半轮=断,
                                明细=记), ensure_ascii=False) + "\n")
    if os.path.exists(存 + ".partial"):
        os.remove(存 + ".partial")
    print(f"\n结果存了一行 → {存}")
    报(记)
    return 1 if 断 else 0


def 报(记):
    n = len(记)
    print(f"\n{'=' * 72}")
    print(f"产线路跑了 {n} 道(训练集)")
    if not n:
        return
    轮总 = sum(x["跑了几轮"] for x in 记)
    取总 = sum(x["取了几轮"] for x in 记)
    每轮都取 = [x for x in 记 if x["取了几轮"] == x["跑了几轮"]]
    print(f"\n  ① **模型自己去取材料了吗**(产线和探针唯一的差别)")
    print(f"     按轮算:{取总}/{轮总} = {取总/轮总:.0%} 的调用里调了 `service_records`")
    print(f"     按题算:{len(每轮都取)}/{n} = {len(每轮都取)/n:.0%} 的题**每一轮都去取了**")
    if 取总 < 轮总:
        print(f"     {Rd}⚠️ 有 {轮总 - 取总} 轮**没去取材料就判了** ——"
              f"而那条建议和「看了材料才这么判」在页面上长得一模一样{D}")

    读出 = [x for x in 记 if x["方式众数"]]
    层计 = {}
    for x in 记:
        for lv in x["读的层们"]:
            层计[str(lv)] = 层计.get(str(lv), 0) + 1
    print(f"\n  ② 判定读得出来吗(**有众数**才算读得出):{len(读出)}/{n} = {len(读出)/n:.0%}")
    print(f"     靠哪一层读到的(按轮):"
          f"{' / '.join(f'{k} {v}' for k, v in sorted(层计.items()))}")
    print(f"     {Y}靠「全文」那一层救回来的可信度本来就低 —— 不许和「段首」混成一个数{D}")

    print(f"\n  ③ **抖动**:同一条题跑 {记[0]['跑了几轮']} 轮,答案稳不稳")
    for 名, 键 in (("方式级(字面答案)", "方式确定度"), ("档位级(实质分歧)", "档确定度")):
        计 = {}
        for x in 记:
            计[x[键]] = 计.get(x[键], 0) + 1
        print(f"     {名}:"
              f"{' / '.join(f'{k} {计.get(k, 0)}' for k in 确定度档 if 计.get(k))}")
    同档内 = [x for x in 记 if x["方式确定度"] != "全一致" and x["档确定度"] == "全一致"]
    if 同档内:
        print(f"     {Y}其中 {len(同档内)} 道是**同档内抖动**(字面换了个说法,代价档没变)"
              f" —— 只报方式级会把它算成分歧{D}")

    print(f"\n  ④ 遮蔽:每道都独立核过,遮了几处 "
          f"{sorted({x['遮了几处'] for x in 记})}(为 0 的已跳过,不进这个分母)")
    print(f"\n  ⚠️ **不许拿这一轮算「判得对不对」** —— 这批数据的真值是**随机填的标注**"
          f"(库里有「外箱破了个角 → 全额退款」这种)。")
    print(f"     能量的只有「取没取材料」「抖不抖」这类**只跟模型自己比**的东西。")
    print(f"  ⚠️ **不和探针那三轮并排比**:探针是我替它取好材料塞进去的,"
          f"那个数是**上限**。")
    print(f"{'=' * 72}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true")
    ap.add_argument("--做", action="store_true")
    ap.add_argument("--重报", action="store_true")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--轮", type=int, default=3,
                    help="每道题跑几轮取众数(和探针同口径,默认 3)")
    ap.add_argument("--自测读法", action="store_true",
                    help="只跑判定读法的五种自造形状,一次模型都不调")
    a = ap.parse_args()
    if getattr(a, "自测读法"):
        return 0 if 自测读法() else 1
    if getattr(a, "重报"):
        行们 = [json.loads(l) for l in io.open(存, encoding="utf-8") if l.strip()]
        if not 行们:
            print(f"{Rd}❌ 结果文件是空的{D}")
            return 1
        最后 = 行们[-1]
        # ⚠️ 10-13 跑的那几行是**单轮格式**(字段叫 `模型方式`,没有众数、没有 `跑了几轮`),
        # 而新的 `报()` 要读 `跑了几轮` / `方式确定度` —— 直接喂进去是 KeyError。
        # **明说它是旧口径、不重报**,而不是崩在一个看不出原因的地方:
        # > 一个「这一行是旧格式」和一个「代码有 bug」,**在那个 KeyError 上长得一模一样。**
        if 最后.get("明细") and "跑了几轮" not in (最后["明细"][0] or {}):
            print(f"{Y}⚠️ 结果文件最后那一行是 **10-13 的单轮格式**"
                  f"({最后['跑于']} · {最后.get('道数')} 道) —— 它没有众数、没有确定度,"
                  f"新口径报不了它{D}")
            print(f"   单轮的数和多轮取众数的数**本来就不可比**(那正是多轮要解决的事)。")
            print(f"   要看那一轮请翻 git 历史里当时的输出;新口径要先 `--做` 跑一轮。")
            return 1
        print(f"重报最后一轮:{最后['跑于']} · {最后['道数']} 道"
              f"{' · **半轮**' if 最后.get('半轮') else ''}（一次模型都没调）")
        报(最后["明细"])
        return 0
    me = 身份()
    if not me:
        print(f"{Rd}❌ 没有在职售后,取不到跨店材料 —— **不跑**{D}")
        return 1
    if not (a.看 or a.做):
        print("  先 --看(挑哪几道,不调模型);要真跑加 --做")
        return 0
    return 跑(a.n, me, 轮数=getattr(a, "轮"), 看=a.看 and not a.做)


if __name__ == "__main__":
    sys.exit(main())
