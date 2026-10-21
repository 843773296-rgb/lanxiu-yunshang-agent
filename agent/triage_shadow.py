#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸四 影子运行:AI 在真实流程**旁边**跑一遍,结果不进流程(方案 V2.0 第四道闸)。

    python3 agent/triage_shadow.py --报            # 只读:两轨各攒到哪了
    python3 agent/triage_shadow.py --跑 3          # 影子跑 3 条(真调模型,要库窗口)
    python3 agent/triage_shadow.py --回填          # 把后来的人工处置冻进台账并判定

## 这道闸和前三道的区别(它为什么非得有)

差评的对错**没有事后可查的真值** —— 这是它比另外三类更需要闸的根本理由:
退款 / 合并 / 判责错了都查得出来、改得回来,**差评错了客户已经走了**。
所以启用前要有一批「AI 判过、而人工独立判了同一批」的对照,**漏报单独报**:

> 一个「一致率 85%」里藏着 15% 全是漏报的,和一个 15% 全是误报的,
> **在那个百分比上长得一模一样** —— 而它们一个该停、一个可以上。

## ⚠️ 2026-10-20 量出来的两件事(方案 A 就是照这两个数定的)

1. **回溯轨的题源和闸二的三套题是同一个集合,166 条一条不差**
   (按包裹号对过:只在题集里 0 条、只在库里 0 条)。
   原因是三套题的来路就是「库里人工处置过的差评」(`triage_sets.读已处置差评`),
   而回溯轨要的也正是这一批。
   > **所以回溯轨跑出来的数不是独立证据,它就是闸二那场考试。**
   > 而在一份写着「四道闸都过了」的成绩单上,
   > **一个独立证据和一个同题重算长得一模一样。**
   这件事不靠谁记得 —— `报一轮()` 每次都把重叠条数算出来印在回溯轨那一行。

2. **新量轨只能靠时间攒**:库里当时 12 条未处置差评,新差评进来的速率
   8 天 3 条 ≈ **0.4 条/天** → 攒到 50 条还要约 95 天。
   所以这个文件今晚建的是**容器和守着它的判据**,不是一份分数。
   不足 50 条时报「**验不动**」,不报「过」—— 照 `triage_sets._小额档线` 已有的做法。

## 为什么影子跑必须在**库副本**上跑(这一条是结构,不是风格)

差评研判走 `sdk.run("task")` —— **全包工具集,里面有写工具**。
「只观测不改行为」如果只靠「希望模型别写」,那它不是结构,是运气。
所以影子跑整个搬到一份库副本上(`mcp/protocol.指到副本`):模型真写了也只写到副本,
**真库一行不动**。

⚠️⚠️ 而 `指到副本()` **不可逆** —— 它把已加载模块的 `DB` 全改到副本上,改完没有回头路。
所以这件事必须在**子进程**里做:
> 父进程一旦指过副本,它后面往台账写的每一行都写进了副本(跑完就没了),
> **而「写进真库」和「写进副本」在落账那一行代码上长得一模一样。**
于是分工是死的:**子进程只调模型(副本)、父进程只落账(真库)**,父进程永不调 `指到副本`。
(这是 10-20 做「考卷自带世界」时踩出来的同一条,那次是取材料。)

## 轨别**不是一个标签,是算出来的**

一行自己就说得清它属于哪一轨,靠的是 `human_at_run` ——
**影子跑那一刻库里的人工档是什么**:

    影子跑时 handle_way 是空的  → 人工还没判 → **新量轨**(AI 先判,人工后判)
    影子跑时 handle_way 有值    → 人工早判完了 → **回溯轨**

⚠️ **为什么不比时间戳**:库里的 `handled_at` 是**演示世界的钟**
(`tools/shift_world.py` 每天把整个世界平移到当天),而 `ran_at` 是**真实时钟**。
拿它们相减是在比两个不同的钟,而那个差值看起来完全像个正常的数。
而「那一刻是不是空的」只用一个钟就说得清,**世界平移也不会把 NULL 平移成有值**。

> 一行标着「新量」而人工处置早于影子跑的,**实际上是一条回溯**;
> 而它混进新量的一致率里,在那个百分比上看不出来。

## 🚫 红线:这张台账**绝不许经任何 API 或工具暴露**

新量轨的全部价值在于**人工那一侧是独立产生的**。处理人要是先看见了 AI 的建议,
一致率就虚高 —— 而**「人工独立判的」和「人工照着 AI 抄的」在台账上长得一模一样**。
所以它和 `truth` 表同一条红线,`agent/triage_shadow_check.py` 扫这件事。
(并行会话 10-20 已知会:对比页以后想显示它,先喊人。)
"""
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]

# ⚠️ **真库路径在 import 时就定下来**,不在落账时现读 `api.DB`。
# 理由见文件头:`指到副本()` 会改模块的 `DB`,而落账要是现读那一份,
# 一次影子跑之后台账就写进副本了 —— 跑完随临时目录一起消失,**而它不报错**。
DBP = os.path.join(ROOT, "backend", "lanxiu.db")

# 建表那一段在 `backend/rating_shadow.py`,**DDL 只有一份**。
# 为什么放在 backend 而不是这儿:`tools/table_origin_check.py` 跟进 import 时
# 只看 backend / tools / knowledge 三个目录 —— 建表函数待在 agent/ 里,
# 它看不见,于是那张表在它眼里是「库里有一张表,谁也建不出它」。
import rating_shadow as _RS                                       # noqa: E402

表名 = _RS.表名
确保表 = _RS.确保表

# ── 新量轨要攒多少条才算验得动 ──────────────────────────────────────────
#
# 📌 **50 这个数是业务 2026-10-10 定的**(`intent/triage-queue.md` 闸四那一段:
#    「要 ≥50 条不进流程的对照,漏报单独报」)。不是开发挑的,别顺手改。
# ⚠️ 不足就报「验不动」,**不报「过」** —— 照 `triage_sets._小额档线` 的做法:
#    「样本太少这条线验不动」和「通过了」在一个 ✅ 上长得一模一样。
新量下限 = 50

# ── 「一条也没记」和「记了而确实是 0」要分得开 ────────────────────────────
#
# 📌 这条是从 PRD 附录 A-119(复合请求的影子漏斗)那次借来的:
#    那份漏斗曾经报「走写路径 0 轮」,而实际写了 —— 原因是它抄的工具清单没跟上。
#    > **「一处也没记」和「记了而确实是 0」在台账上长得一模一样。**
#    所以报告里永远先说「最近一次影子跑于何时」,再说数。
没跑过的话术 = "口还没跑过(不是 0 条漏报)"

# ── 哪些算「这一轮真的交出了答复」──────────────────────────────────────
#
# 📌 口径照 `agentsite/sdk.run` 的返回:**只有前两种算交付成功**
#    (用户 2026-10-04 拍「按最终交付判」);别拿「曾被打回过」当最终不合格。
# ⚠️ 为什么非要按它筛:2026-10-20 首批 12 条里有 1 条**建议读不出**,
#    而它正好就是交付检查「未通过」的那一条(花费还是别人的四五倍)——
#    三个信号指向同一件事:那一轮模型没写出规范答复。
#    > **一条连交付检查都没过的草稿,和一条正经判断,在一致率里长得一模一样。**
#    所以它不进分母,但**必须单独报出来** —— 不然「这批里有几条没交出来」也看不见了。
交付成功的 = ("通过", "修正后通过")


def 交出来了吗(行):
    return str((行 or {}).get("delivered") or "").strip() in 交付成功的


def 核轨别(human_at_run):
    """影子跑那一刻人工判了没有 → 这一行属于哪一轨。**不读标签,现算。**"""
    return "新量" if str(human_at_run or "").strip() == "" else "回溯"


# ── 挑题 ──────────────────────────────────────────────────────────────────
def 挑新量(dbp=DBP, 上限=None):
    """**人工还没判**的差评,排除台账里已经影子跑过的。

    这一轨是闸四唯一独立于闸二的那一半:AI 先判、人工后判,
    而人工看不到 AI 判了什么(台账不经任何口暴露)。
    """
    import rating as R
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    try:
        跑过 = {r[0] for r in c.execute(f"SELECT pkg_id FROM {表名}")} \
            if _有表(c) else set()
        行 = [r[0] for r in c.execute(
            "SELECT pkg_id FROM rating WHERE star<=? "
            "AND (handle_way IS NULL OR TRIM(handle_way)='') ORDER BY pkg_id", (R.差评线,))]
    finally:
        c.close()
    出 = [p for p in 行 if p not in 跑过]
    return 出[:上限] if 上限 else 出


def 挑回溯(dbp=DBP):
    """已人工处置的差评 —— **和闸二三套题同一批**(见文件头第 1 条)。

    📌 **用户 2026-10-21 拍:回溯轨不跑,只在报告里留那句「不是独立证据」。**
    所以这个函数现在**只给 `报一轮()` 算重叠条数用**,不是给人拿去跑的入口 ——
    `--跑` 走的是 `挑新量()`。要改这个决定,那是换一次口径,不是改一行代码。

    这儿不自己写 SQL:题集那边已经有 `读已处置差评`(它还排除演示数据清理那批),
    **两份实现会漂**,而漂了之后「回溯轨和三套题同题」这个结论就不再成立,
    却照样印在报告上。
    """
    import triage_sets as T
    return [r["pkg_id"] for r in T.读已处置差评(dbp)]


def _有表(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (表名,)).fetchone())


# ── 落账:**只有父进程做这件事,写的是真库** ───────────────────────────────
def 落账(行们, dbp=None):
    """把影子跑的结果写进台账。→ 落了几条。

    ⚠️ `dbp` 默认是 import 时定下的 `DBP`,**不是 `api.DB`** —— 见文件头。
    ⚠️ 落账时自检 `track` 和 `human_at_run` 对得上:
       轨别是算出来的,**一个传错的标签会安静地混进另一轨的一致率**。
    """
    c = sqlite3.connect(dbp or DBP)
    try:
        确保表(c)
        n = 0
        for 行 in 行们:
            轨 = 核轨别(行.get("human_at_run"))
            if 行.get("track") and 行["track"] != 轨:
                raise RuntimeError(
                    f"{行.get('pkg_id')} 的轨别传的是「{行['track']}」,"
                    f"而影子跑那一刻的人工档说它是「{轨}」—— 轨别不许手填")
            c.execute(
                f"INSERT INTO {表名} (batch, pkg_id, human_at_run, track, ran_at, "
                f"provider, model, code_ver, prompt_ver, ai_way, ai_layer, ai_text, "
                f"got_material, masked, delivered, tool_calls, cost, error, into_flow) "
                f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (行.get("batch"), 行.get("pkg_id"), 行.get("human_at_run"), 轨,
                 行.get("ran_at"), 行.get("provider"), 行.get("model"),
                 行.get("code_ver"), 行.get("prompt_ver"), 行.get("ai_way"),
                 行.get("ai_layer"), 行.get("ai_text"), 行.get("got_material"),
                 行.get("masked"), 行.get("delivered"), 行.get("tool_calls"),
                 行.get("cost"), 行.get("error")))
            n += 1
        c.commit()
        return n
    finally:
        c.close()


# ── 回填人工那一侧,并判定 ─────────────────────────────────────────────────
def 回填人工(dbp=None, 现在=None):
    """新量轨那些行,人工后来判了没有 —— 判了就冻一份进台账并算判定。

    → dict(回填了, 判定了, 还没判的)

    ⚠️ **为什么要冻一份,不在报告时现 JOIN `rating`**:人工后来改判、或者库重建,
    现 JOIN 出来的数就跟着变 —— 而那时报告上的历史分数会**悄悄变成另一个数**。
    (这正是 10-20 题集失效那件事的形状:按 id 指过去的东西会被一次合理的数据变更打断。)
    """
    import datetime
    now = 现在 or datetime.datetime.now().isoformat(timespec="seconds")
    c = sqlite3.connect(dbp or DBP)
    try:
        确保表(c)
        c.row_factory = sqlite3.Row
        待 = [dict(r) for r in c.execute(
            f"SELECT * FROM {表名} WHERE track='新量' "
            f"AND (human_way IS NULL OR TRIM(human_way)='')")]
        回填, 还没 = 0, []
        for 行 in 待:
            现 = c.execute("SELECT handle_way FROM rating WHERE pkg_id=?",
                           (行["pkg_id"],)).fetchone()
            档 = (现["handle_way"] if 现 else None) or ""
            if not str(档).strip():
                还没.append(行["pkg_id"]); continue
            判 = 判这一行(行, 档)
            c.execute(f"UPDATE {表名} SET human_way=?, human_filled_at=?, "
                      f"verdict=?, judged_at=? WHERE id=?",
                      (档, now, json.dumps(判, ensure_ascii=False), now, 行["id"]))
            回填 += 1
        # 回溯轨那些行的人工侧在影子跑那一刻就有了,落账时还没判 —— 这儿一并补判定
        判了 = 0
        for 行 in [dict(r) for r in c.execute(
                f"SELECT * FROM {表名} WHERE track='回溯' AND verdict IS NULL")]:
            判 = 判这一行(行, 行["human_at_run"])
            c.execute(f"UPDATE {表名} SET human_way=?, human_filled_at=?, "
                      f"verdict=?, judged_at=? WHERE id=?",
                      (行["human_at_run"], now, json.dumps(判, ensure_ascii=False),
                       now, 行["id"]))
            判了 += 1
        c.commit()
        return dict(回填了=回填, 判定了=回填 + 判了, 还没判的=还没)
    finally:
        c.close()


def 待回填(dbp=None):
    """新量轨里**人工已经判了、而台账还没回填**的那些。

    ⚠️ 这个数非报不可,因为回填是**要有人去跑**的一步(`--回填`):
    > 「有人处置了而台账没回填」和「还没人处置」在台账上长得一模一样 ——
    > 两者 `verdict` 都是空,`judged_at` 都是空。
    而前者是一条**已经攒到了、却没计入**的对照,后者只能等。
    把它们混成一个「判定过的 0」,这道闸会显得永远攒不动,
    **而真相可能是数据早就在了,只是没人跑那一步。**

    判据第 ⑩ 节每次照数打印(库况,不判红 —— 它不是谁做错了事,是一步没跑)。
    """
    c = sqlite3.connect(f"file:{dbp or DBP}?mode=ro", uri=True)
    try:
        if not _有表(c):
            return []
        return [r[0] for r in c.execute(
            f"SELECT s.pkg_id FROM {表名} s JOIN rating r ON r.pkg_id = s.pkg_id "
            f"WHERE s.track='新量' AND (s.human_way IS NULL OR TRIM(s.human_way)='') "
            f"AND r.handle_way IS NOT NULL AND TRIM(r.handle_way)<>''")]
    finally:
        c.close()


def 遮不住的回溯行(dbp=None):
    """回溯轨里**一处都没遮到**的那些行 —— 它们的人工处置可能夹在材料里。

    ⚠️ **这个口径只对回溯轨成立。** 新量轨的 `masked` 本来就是 0:
    人工还没判它,**答案还不存在**,遮蔽是个空操作 ——
    这是新量轨结构上的好处(它不可能开卷),不是缺陷。
    > 「新量轨本来没有答案可遮」和「回溯轨的遮蔽失效了」
    > **在 masked=0 这一个数上长得一模一样** —— 分开它们的只有 track 这一列。

    所以回溯轨里 masked=0 的那几行**不该进任何一致率**(题集那边同一个处理:
    `triage_pipeline_eval` 碰到「一处都没遮到」是「跳过,不猜」)。
    """
    c = sqlite3.connect(f"file:{dbp or DBP}?mode=ro", uri=True)
    try:
        if not _有表(c):
            return []
        return [r[0] for r in c.execute(
            f"SELECT pkg_id FROM {表名} WHERE track='回溯' "
            f"AND (masked IS NULL OR masked = 0)")]
    finally:
        c.close()


def 判这一行(行, 人工档):
    """一行台账 → 判定。**判法只有一份**,在 `triage_sets.判一题`。

    ⚠️ 题型填「正向」:影子轨是**真实流量**,没有诱导题面。
       (诱导是闸二那边配对出题的事,混进来会让「顺着诱导滑了」这一栏变成假话。)
    """
    import triage_sets as T
    题 = dict(包裹=行["pkg_id"], 题型="正向", 人工档=人工档, 人工档位=T.档(人工档))
    return T.判一题(题, 行.get("ai_way"), 行.get("ai_text") or "")


# ── 报一轮 ────────────────────────────────────────────────────────────────
def 报一轮(dbp=None):
    """两轨各自报,**不许合成一个数**。→ dict(新量=…, 回溯=…, 库况=…)

    合成一个数会让「166 条同题重算」把「12 条真对照」稀释掉 ——
    而稀释完那个一致率**看起来比两边都好**。
    """
    import triage_sets as T
    c = sqlite3.connect(f"file:{dbp or DBP}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        if not _有表(c):
            return dict(有表=False, 说明=f"{表名} 还不在库里 —— 跑 tools/ensure_tables.py")
        行们 = [dict(r) for r in c.execute(f"SELECT * FROM {表名}")]
    finally:
        c.close()
    出 = dict(有表=True, 总条数=len(行们))
    # 回溯轨和三套题重叠多少 —— **每次现算,不靠注释里记着**
    三套 = set(挑回溯(dbp or DBP))
    for 轨 in ("新量", "回溯"):
        这轨 = [x for x in 行们 if x["track"] == 轨]
        # **没交付成功的不进分母,但单独报** —— 见「交付成功的」那一段
        没交出来 = [x["pkg_id"] for x in 这轨 if not 交出来了吗(x)]
        判们 = [json.loads(x["verdict"]) for x in 这轨
                if x["verdict"] and 交出来了吗(x)]
        最近 = max((x["ran_at"] or "" for x in 这轨), default="")
        节 = dict(条数=len(这轨), 判定过的=len(判们), 最近跑于=最近 or None,
                  没交付成功的=没交出来,
                  读不出建议的=[x["pkg_id"] for x in 这轨 if not x["ai_way"]])
        if not 这轨:
            节["状态"] = 没跑过的话术
        elif 轨 == "新量" and len(判们) < 新量下限:
            # **报「验不动」,不报「过」**
            节["状态"] = (f"验不动 —— 判定过的 {len(判们)}/{新量下限} 条"
                          f"(业务 2026-10-10 定的下限)")
            节["过"] = None
        else:
            节["状态"] = "攒够了,线按 triage_sets.判一轮 算"
            节["线"] = T.判一轮(判们) if 判们 else None
        if 轨 == "回溯":
            # 一处都没遮到的那几行不该进一致率(它们可能是开卷的)
            节["⚠️ 一处都没遮到的"] = 遮不住的回溯行(dbp or DBP)
            重 = len([x for x in 这轨 if x["pkg_id"] in 三套])
            节["和闸二三套题重叠"] = f"{重}/{len(这轨)}"
            节["⚠️ 证据力"] = (
                "回溯轨的题源就是闸二的三套题(2026-10-20 按包裹号对过:166 条一条不差)——"
                "**它跑出来的数不是独立证据**,只能当「同一批题再跑一次稳不稳」读。"
                "📌 **用户 2026-10-21 拍了「不跑,只留这句话」** —— 别再提「要不要补跑回溯轨」,"
                "那是问过并否决的")
        出[轨] = 节
    # 库况:新量还能攒多少、剩多少要等
    可攒 = len(挑新量(dbp or DBP))
    判了 = 出["新量"].get("判定过的", 0)
    待 = 待回填(dbp or DBP)
    出["库况"] = dict(库里还没影子跑过的未处置差评=可攒,
                      新量还差=max(0, 新量下限 - 判了),
                      # **人工已经判了而台账还没回填的** —— 跑 `--回填` 就能计入。
                      # 不单独报的话,它和「还没人处置」在「判定过的 0」上长得一模一样
                      等着回填的=待,
                      要不要跑回填=("要 —— 有 %d 条人工已经判了,跑 "
                                    "`python3 agent/triage_shadow.py --回填`" % len(待))
                                   if 待 else "不用,没有人工新判的",
                      一句话=("新量轨只能靠时间攒 —— 2026-10-20 量的速率是 8 天 3 条 "
                              "≈ 0.4 条/天;这个数不该拿来当「做得慢」,它是这个世界的上新速率"))
    return 出


# ── 影子跑:子进程在副本上调模型,父进程只落账 ─────────────────────────────
#
# 跑法白名单:**子进程只认这里有名字的那几种**。
# ⚠️ 为什么是白名单而不是传一个函数进去:判据要能自己造一种「会写库的跑法」
# 来验「真库没被改」,而那种跑法**绝不能是生产默认**。
# 名字写在白名单里,于是「默认是哪一种」是一行看得见的字,判据盯得住
# (`triage_shadow_check` 有一条就在盯 默认跑法 == "产线路")。
默认跑法 = "产线路"
跑法们 = ("产线路", "自测写一行")


def 解释器():
    """子进程要用 `agentsite/.venv` 那个 python。

    ⚠️ **claude_agent_sdk 只装在 agentsite/.venv 里**(`agentsite/sdk.py` 开头就拦这件事)。
    用外层 python 跑,`跑一条` 在 `import sdk` 那一行才挂 ——
    而那时候报出来的是一句 import 错,**看起来像「影子跑挂了」,
    而不是「我用错了解释器」**。拿不到就退回当前解释器(自测跑法用不上 sdk)。
    """
    p = os.path.join(ROOT, "agentsite", ".venv", "bin", "python")
    return p if os.path.exists(p) else sys.executable

_子码 = r'''
import json, os, shutil, sqlite3, sys, tempfile, datetime
入 = json.loads(sys.stdin.read())
ROOT = 入["root"]
sys.path[:0] = [os.path.join(ROOT, "agent"), ROOT,
                os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"),
                os.path.join(ROOT, "mcp"), os.path.join(ROOT, "agentsite")]
# ① 先拷一份库副本 —— 整批只拷一次
#
# ⚠️ **副本是 85 MB,跑完必须删。** 第一版没删,十几次自测就在 /var/folders 下
# 攒了 **1.2 GB**;而门禁每跑一次攒一份,一天就能顶穿并行会话那个 400 MB 拷贝上限
# (他 10-20 正为一个 100 MB 的旧库备份撞上那条线)。
# > 一个「跑完清理了」的脚本和一个「每次留一份 85 MB」的,**在它自己的输出上长得一模一样**。
# 给了 `副本目录` 就用它、**由调用方负责删**(判据要跑完去翻那份副本,验写确实落在副本上);
# 没给就自己开一个、自己删。
目录 = 入.get("副本目录") or tempfile.mkdtemp(prefix="shadow-")
自己开的 = not 入.get("副本目录")
副 = os.path.join(目录, "lanxiu.db")
shutil.copy(入["dbp"], 副)
os.environ["LANXIU_DB"] = 副
# ② ⚠️⚠️ **先把要用的模块全 import 进来,再指到副本** —— 顺序反了它改 0 个模块。
# `指到副本()` 改的是**已加载模块**的 `DB`;在 import 之前调,那一刻没有模块可改,
# 它返回 0、不报错,然后产线路照样跑完 —— 读的是**真库**。
# > 「改了 0 个模块」和「改了 20 个模块」在那一行返回值上长得一模一样。
# (第一版就是这么写的,是顺手印出来的那个数把它供出来的。)
import protocol
import api
import ops
import rating_triage as RT
import triage_pipeline_eval as PE
import evalrec
改了 = protocol.指到副本()
print(json.dumps(dict(_meta=1, 副本=副, 改了几个模块=改了,
                      api读的是=getattr(api, "DB", None)), ensure_ascii=False), flush=True)
# ③ **0 就拒跑** —— 不然这一批的材料全是从真库取的,而台账上看不出来
if 改了 <= 0:
    print(json.dumps(dict(_meta=1, 致命="指到副本 改了 0 个模块 —— 这一批会读真库,拒跑"),
                     ensure_ascii=False), flush=True)
    sys.exit(3)
章 = evalrec.盖章()
for pkg in 入["包裹们"]:
    # ⚠️⚠️ **每条跑之前再扫一遍。** 上面那一次只改得到「那一刻已加载」的模块,
    # 而 `跑一条` 里 `import ops, sdk` 是**懒加载**的 —— 新进来的模块
    # 带着指向真库的 `DB`,而它读真库也不会报错。
    # (10-20 做「考卷自带世界」时踩的就是这条,交接里记着「每次调工具前再扫一遍」。)
    又改 = protocol.指到副本()
    行 = dict(pkg_id=pkg, provider=章.get("供应商"), model=章.get("模型"),
              code_ver=章.get("代码"), 又改了=又改,
              ran_at=datetime.datetime.now().isoformat(timespec="seconds"))
    try:
        if 入["跑法"] == "自测写一行":
            # 判据专用:**装一个真的会写库的模型** —— 验「它写的是副本,真库一行没变」
            #
            # ⚠️⚠️ 它必须**自己报告写成了没有**。少这一句,判据就有一个空转的绿:
            # 一个「隔离住了」的跑和一个「这一跑压根没写」,
            # **在「真库指纹没变」这件事上长得一模一样** ——
            # 而后者什么也没证明。(同一个形状:题集那边的「遮了几处」。)
            with sqlite3.connect(副) as _c:
                _c.execute("UPDATE rating SET handle_note=? WHERE pkg_id=?",
                           (入.get("自测标记", "影子自测写的一行"), pkg))
            行.update(ai_way=入.get("假档"), ai_layer="自测", ai_text="(自测跑法,没调模型)",
                      got_material=1, masked=入.get("假遮", 1), cost=0.0)
        else:
            遮了, _, _ = PE.数遮了几处(pkg, 入["me"])
            bp, case, 结果, 版本 = RT.跑一条(f"SHADOW-{pkg}", pkg, 入["me"])
            方式, 层, 文 = PE.读判定(结果)
            # ⚠️ 花费的键是 `cost_usd`(sdk.cost_of 算的那一份,成本口径只有一处)——
            # 不是 `cost`(不存在,取到 None → 记成 0.0,**而一笔 0 花费看起来很正常**),
            # 也不是 `sdk_cost_usd`(SDK 自报的,实测虚高几十倍)。
            行.update(ai_way=方式, ai_layer=层, ai_text=(文 or "")[:4000],
                      got_material=int("没调" not in 版本), masked=遮了,
                      # ⚠️ 只存那**一个状态词**(通过 / 修正后通过 / 未通过 / 未检查 /
                      # 不完整),不存整个 dict —— 第一版存了 `str(交付检查)`,
                      # 一行 612 个字符,里面连草稿原文和每次修正的哈希都在。
                      # 台账是用来**比对**的,一栏塞进一整份记录,它就既不好比也不好读。
                      delivered=str(((结果 or {}).get("交付检查") or {}).get("状态") or ""),
                      tool_calls=(结果 or {}).get("tool_calls_seen"),
                      cost=float((结果 or {}).get("cost_usd") or 0.0), prompt_ver=版本)
    except Exception as e:
        行["error"] = f"{type(e).__name__}: {e}"
    print(json.dumps(行, ensure_ascii=False), flush=True)
# ④ 自己开的副本自己删 —— 85 MB,留着就是一天顶穿一次拷贝上限
if 自己开的:
    shutil.rmtree(目录, ignore_errors=True)
'''


# ── 影子跑**自己**要带证据:真库在它前后一个字节都没变 ─────────────────
#
# ⚠️⚠️ **2026-10-21 补的,而补它的理由是并行会话当天出的一次真事故**:
# 他那边「研判模块是切到副本之后才 import 的,于是 `save_triage` 写进了真库」——
# 研判记录留在真库、而它指的那张工单只插在副本里。
# 同一族的坑,我昨晚在取材料那条路上也踩过(`指到副本()` 在 import 之前调,改 0 个模块)。
#
# 而我当时只在**夹具副本**上用假跑法验过「真库没变」——
# **真调模型那条路跑完,没有任何人对真库盖过前后指纹**。
# > 一次「隔离住了」的真跑,和一次「悄悄写进真库」的真跑,
# > **在台账和日志上长得一模一样** —— 落账照落、模型照答。
#
# 所以这件事不该只由门禁在夹具上替它验:**每一次真跑自己带证据**。
# 差评研判走 `sdk.run("task")`(全包工具集,**里面有写工具**),
# 这个数就是那句「只观测不改行为」唯一的凭据。
流程表 = ("rating", "ordr", "task", "triage", "triage_run", "escalation", "pkg", "pickup")


def 流程指纹(dbp=None, 表们=流程表):
    """流程那几张表的内容指纹。影子跑前后各算一次,必须一模一样。

    ⚠️ **只数行数不够**:模型把一行的 `handle_way` 从空改成「只回访」,行数一个不变。
    所以逐行取内容算 md5。
    """
    import hashlib
    c = sqlite3.connect(f"file:{dbp or DBP}?mode=ro", uri=True)
    h = hashlib.md5()
    try:
        for t in 表们:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (t,)).fetchone():
                continue
            for r in c.execute(f"SELECT * FROM {t} ORDER BY 1"):
                h.update(repr(r).encode("utf-8"))
    finally:
        c.close()
    return h.hexdigest()


def 影子跑一批(包裹们, me, batch, dbp=None, 跑法=None, 额外=None):
    """影子跑一批并落账。→ (落了几条, 子进程说了什么)

    父进程**只落账**,永不调 `指到副本()` —— 见文件头。
    """
    跑法 = 跑法 or 默认跑法
    if 跑法 not in 跑法们:
        raise ValueError(f"跑法只认 {跑法们},给的是 {跑法!r}")
    真库 = dbp or DBP
    # 🔺 跑之前先盖一次 —— 这一次影子跑自己的「不改行为」证据
    前指纹 = 流程指纹(真库)
    入 = dict(root=ROOT, dbp=真库, 包裹们=list(包裹们), me=me, 跑法=跑法)
    入.update(额外 or {})
    p = subprocess.run([解释器(), "-I", "-c", _子码], input=json.dumps(入),
                       capture_output=True, text=True)
    行们, meta = [], None
    for 行 in (p.stdout or "").splitlines():
        行 = 行.strip()
        if not 行:
            continue
        try:
            d = json.loads(行)
        except Exception:                                          # noqa: BLE001
            continue
        if d.get("_meta"):
            meta = d
        else:
            行们.append(d)
    if not 行们:
        raise RuntimeError(f"影子子进程一行结果都没吐出来 —— 退出码 {p.returncode}\n"
                           f"{(p.stderr or '')[-1500:]}")
    # 影子跑那一刻库里的人工档:**在真库上现读**(轨别靠它算)
    c = sqlite3.connect(f"file:{真库}?mode=ro", uri=True)
    try:
        现 = {r[0]: r[1] for r in c.execute("SELECT pkg_id, handle_way FROM rating")}
    finally:
        c.close()
    for 行 in 行们:
        行["batch"] = batch
        行["human_at_run"] = 现.get(行["pkg_id"])
    # 「每条跑之前又改了几个模块」不进台账(那是跑的时候的事,不是这条差评的事),
    # 但要报出来 —— 它不为 0 就说明确实有懒加载的模块被接住了
    # 🔺 **落账之前**盖第二次:落账自己会往 rating_shadow 写,
    # 而那张表**不在流程表里**,所以这个比较不受它影响 ——
    # 但顺序还是放在落账前,免得以后有人往流程表里补一笔就比不出来了。
    后指纹 = 流程指纹(真库)
    动了 = 前指纹 != 后指纹
    if 动了:
        raise RuntimeError(
            f"❌ 影子跑动了流程表 —— 这就不叫影子了。\n"
            f"   指纹 {前指纹[:12]} → {后指纹[:12]};表:{'、'.join(流程表)}\n"
            f"   最可能的原因:**有个会写库的模块是在 `指到副本()` 之后才 import 的**"
            f"(并行会话 2026-10-21 真踩过:`save_triage` 写进了真库)。\n"
            f"   ⚠️ 这一批**没有落账** —— 不许把一次泄漏过的跑记成正常样本")
    return 落账(行们, 真库), dict(meta=meta, 退出码=p.returncode,
                                 流程表没动=dict(前=前指纹[:12], 后=后指纹[:12]),
                                 每条又改了=[行.get("又改了") for 行 in 行们],
                                 stderr=(p.stderr or "")[-800:])


# ── 命令行 ────────────────────────────────────────────────────────────────
def _主():
    import datetime
    参 = sys.argv[1:]
    if "--报" in 参 or not 参:
        print(json.dumps(报一轮(), ensure_ascii=False, indent=1))
        return 0
    if "--回填" in 参:
        print(json.dumps(回填人工(), ensure_ascii=False, indent=1))
        return 0
    if "--跑" in 参:
        n = int(参[参.index("--跑") + 1])
        import triage_pipeline_eval as PE
        me = PE.身份()
        if not me:
            print("❌ 库里没有「售后」身份 —— 影子跑取不到材料"); return 1
        号们 = 挑新量(上限=n)
        if not 号们:
            print(f"库里没有「还没影子跑过的未处置差评」了 —— "
                  f"{报一轮()['库况']['一句话']}"); return 0
        batch = "shadow/" + datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
        落, 说 = 影子跑一批(号们, me, batch)
        print(f"影子跑了 {落} 条,落账到 {表名}(批次 {batch})")
        print(json.dumps(说, ensure_ascii=False, indent=1))
        print(json.dumps(回填人工(), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_主())
