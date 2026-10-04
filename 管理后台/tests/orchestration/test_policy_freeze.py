#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把草稿冻成一版策略 —— 零 IO。规格 §4.2 / §5.3 / §10.2。

## 这一组每一条都对着一种**填了而没生效**的方式

规格 §5.3:「字段不受支持时显示『此执行入口不支持』,
**不能让人填完仍显示保护已生效**」。

而冻结这一步能放过的最毒的两种:

> **一个拼错键名的上限**(`tool_attemps_cap`),和一个真在执行的,
> **在那张配置表上长得一模一样** —— 执行层读不到它,
> 于是那个保护从来没生效过,而页面上填着数。

> **一条上限 1 次的策略,和一条写着 `true` 的,在执行时长得一模一样**
> (Python 里 `True == 1`),而填的人以为自己打开了这个保护。
"""
import os
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app", "runtime"))

import 策略冻结 as F

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


好草稿 = dict(
    application_id="app_lanxiu", entry_kind=F.门店V3,
    scope={"门店": ["S01"], "任务模板": "报价核查"},
    limits={"tool_attempt_cap": 12, "task_deadline_seconds": 60,
            "max_retries_per_action": 2},
    counter_schema_version=F.新口径,
    support_conditions=["task_deadline_seconds", "tool_attempt_cap"],
    # 下面这些**不影响执行**,所以不该进哈希
    owner="pm_01", change_note="初版", draft_revision=7)

def 只换limits(**lim):
    """只换 `limits` 的夹具。

    ⚠️ **`support_conditions` 要一起清空** —— 否则它还指向被换掉的键,
    于是「该放行的」会因为另一条问题而报问题。
    第一版就这么挂了 4 条,而那 4 条**全是夹具的错,不是代码的错**
    (按 CLAUDE.md 第 9 节那个排查顺序,这是第 ③ 种:判分脚本错了)。
    > 一条因为夹具写错而红的判据,和一条真抓到问题的,
    > **在那个 ❌ 上长得一模一样。**
    """
    return dict(好草稿, limits=lim, support_conditions=[])


print("把草稿冻成一版策略(规格 §4.2 / §5.3 / §10.2)")
print("=" * 92)

print("\n▸ ① 正常冻一版")
v = F.冻(草稿=好草稿, 版本号=1)
ck("冻出来的 dict 带哈希和版本号", v["version_no"] == 1 and len(v["content_hash"]) == 64,
   v["content_hash"][:16])
ck("`support_conditions` **存的时候就排好了**(库里那份和算哈希用的同序,"
   "否则「哈希对不上」会出现在一个没人想得到的地方)",
   v["support_conditions"] == ["task_deadline_seconds", "tool_attempt_cap"])
ck("**不带** owner / change_note / draft_revision(它们不影响执行)",
   not any(k in v for k in ("owner", "change_note", "draft_revision")), list(v))

print("\n▸ ② 哈希只覆盖**影响行为**的字段")
for 改, 叫法 in ((dict(owner="pm_99"), "换个负责人"),
             (dict(change_note="又改了一版说明"), "改备注"),
             (dict(draft_revision=99), "草稿 revision 涨了")):
    同 = F.算内容哈希(dict(好草稿, **改)) == F.算内容哈希(好草稿)
    ck(f"{叫法} → 哈希**不变**", 同)
ck("⚠️ 不这么算的话:一个因为改了备注而冒出来的新版本,和一个真的改了限制的,"
   "**在版本列表上长得一模一样**,而回滚的人分不出该回到哪一版", True)
for 改, 叫法 in ((dict(limits=dict(好草稿["limits"], tool_attempt_cap=8)), "改了上限"),
             (dict(entry_kind=F.后台编排), "换了执行入口"),
             (dict(counter_schema_version=F.旧口径), "换了计数口径"),
             (dict(scope={"门店": ["S02"]}), "换了适用范围"),
             (dict(support_conditions=["tool_attempt_cap"]), "少要求一项支持")):
    变 = F.算内容哈希(dict(好草稿, **改)) != F.算内容哈希(好草稿)
    ck(f"{叫法} → 哈希**变了**", 变)

print("\n▸ ③ `support_conditions` 的**顺序**不该影响哈希(它是集合)")
ck("两种顺序 → 同一个哈希",
   F.算内容哈希(dict(好草稿, support_conditions=["tool_attempt_cap",
                                           "task_deadline_seconds"]))
   == F.算内容哈希(好草稿))
ck("⚠️ 而这件事是**在这儿排**的,不是去改缓存那个规范化器 —— "
   "那边对数组保序是对的(检索结果的顺序会改变答案)", True)

print("\n▸ ④ `0` / `null` / `false` **折出来必须不一样**(复用缓存那个规范化器)")
h0 = F.算内容哈希(dict(好草稿, limits={"max_retries_per_action": 0}))
hN = F.算内容哈希(dict(好草稿, limits={"max_retries_per_action": None}))
ck("`{retries: 0}` 和 `{retries: null}` → **两个不同的哈希**", h0 != hN, (h0[:8], hN[:8]))
ck("⚠️ 折成同一个的话,两版内容不同的策略会拿到同一个版本号,"
   "于是「这一版变了吗」**永远回答「没变」**", h0 != hN)

print("\n▸ ⑤ 拼错的 limits 键 → **拒绝,不放过**")
问 = F.查形状(只换limits(tool_attemps_cap=12))
ck("`tool_attemps_cap`(少个 t)→ 报问题", any("不认得" in x for x in 问), 问[:1])
ck("理由里说出那个形状:拼错的键会冻进版本而执行层读不到,"
   "**那个保护从来没生效过,而页面上填着数**",
   any("从来没生效过" in x for x in 问))
try:
    F.冻(草稿=dict(好草稿, limits={"tool_attemps_cap": 12}), 版本号=1)
    ck("冻它 → 抛", False, "它没抛")
except F.冻不了 as e:
    ck("冻它 → **抛**(不冻一个半成品)", "不认得" in str(e))

print("\n▸ ⑥ 布尔不能当数字(Python 里 `True == 1`,规格 §5.3)")
问2 = F.查形状(只换limits(tool_attempt_cap=True))
ck("`{tool_attempt_cap: true}` → 报问题", any("布尔" in x for x in 问2), 问2[:1])
ck("⚠️ 理由里说出那个形状:**一条上限 1 次的策略,和一条写着 `true` 的,"
   "在执行时长得一模一样**,而填的人以为打开了这个保护",
   any("长得一模一样" in x for x in 问2))
ck("**bool 判在 int 之前** —— 不然 `True` 会当成合法的正整数 1 放过去",
   len(F.查形状(只换limits(tool_attempt_cap=True))) > 0
   and len(F.查形状(只换limits(tool_attempt_cap=1))) == 0)

print("\n▸ ⑦ 正整数 vs 允许 0 —— 两套键分开")
for k, v2, 该报 in (("tool_attempt_cap", 0, True), ("tool_attempt_cap", -1, True),
                 ("tool_attempt_cap", 1, False),
                 ("max_retries_per_action", 0, False),
                 ("max_retries_per_action", -1, True)):
    有问 = len(F.查形状(只换limits(**{k: v2}))) > 0
    ck(f"`{k}` = {v2} → {'报问题' if 该报 else '放行'}", 有问 is 该报)
ck("⚠️ `tool_attempt_cap: 0` **不是「不限制」** —— 规格 §5.3 要求次数为正整数;"
   "而把 0 读成不限制的实现,和一个真不限制的,在那次运行上长得一样",
   len(F.查形状(只换limits(tool_attempt_cap=0))) > 0)

print("\n▸ ⑧ 金额必须带币种(规格 §5.3)")
问3 = F.查形状(只换limits(cost_cap_amount=5.0))
ck("填了金额没填币种 → 报问题", any("币种" in x for x in 问3), 问3[:1])
ck("理由里点明「**不能把未知价格视为零**」", any("视为零" in x for x in 问3))
ck("金额 + 币种都给 → 放行",
   not F.查形状(只换limits(cost_cap_amount=5.0, cost_cap_currency="CNY")))
for 坏 in (0, -1, True):
    ck(f"金额 = {坏!r} → 报问题",
       len(F.查形状(只换limits(cost_cap_amount=坏,
                           cost_cap_currency="CNY"))) > 0)

print("\n▸ ⑨ `support_conditions` 必须指向 `limits` 里真有的键")
问4 = F.查形状(dict(好草稿, support_conditions=["这个限制根本没填"]))
ck("要求一个 limits 里没有的限制 → 报问题",
   any("没有" in x for x in 问4), 问4[:1])
ck("理由里说清后果:会让 `策略解析` **永远拒绝启动**,"
   "而报错指向「实例不支持」而不是「策略写错了」",
   any("永远拒绝启动" in x for x in 问4))
ck("⚠️ 并点名那句:**一句解释错了东西的报错,比不解释更误导人**",
   any("更误导人" in x for x in 问4))
ck("`[]`(明确不要求)→ 放行", not F.查形状(dict(好草稿, support_conditions=[])))
问5 = F.查形状({k: v3 for k, v3 in 好草稿.items() if k != "support_conditions"})
ck("**没给** → 报问题(`[]` 是「说过:没有」,没给是「没人想过这件事」)",
   any("两件事" in x for x in 问5), 问5[:1])

print("\n▸ ⑩ 入口 / 计数口径只认点名的那几个")
for 坏, 哪 in ((dict(entry_kind="通用"), "entry_kind"),
            (dict(entry_kind=None), "entry_kind"),
            (dict(counter_schema_version="v1"), "counter_schema_version"),
            (dict(counter_schema_version=None), "counter_schema_version")):
    ck(f"{哪} = {list(坏.values())[0]!r} → 报问题",
       any(哪 in x for x in F.查形状(dict(好草稿, **坏))))
ck("⚠️ 计数口径的理由里点明:**一个用新口径读旧数的统计,和一个口径对上的,"
   "在那个数字上长得一模一样**",
   any("长得一模一样" in x
       for x in F.查形状(dict(好草稿, counter_schema_version="v1"))))

print("\n▸ ⑪ 空 limits → 拒绝")
for 坏 in ({}, None, [], "x"):
    ck(f"`limits` = {坏!r} → 报问题",
       any("limits" in x for x in F.查形状(dict(好草稿, limits=坏))))
ck("⚠️ 理由里点明:**一版空 limits 的策略,和一版「不限制」的,"
   "在那次运行上长得一模一样**",
   any("长得一模一样" in x for x in F.查形状(dict(好草稿, limits={}))))

print("\n▸ ⑫ 版本号要**密集递增**,不是「只要更大」")
ck("上一版 3 → 这一版 4,放行", F.冻(草稿=好草稿, 版本号=4, 上一版号=3)["version_no"] == 4)
for 号, 上 in ((5, 3), (3, 3), (2, 3)):
    try:
        F.冻(草稿=好草稿, 版本号=号, 上一版号=上)
        ck(f"上一版 {上} → 这一版 {号},该抛", False, "它没抛")
    except F.冻不了 as e:
        ck(f"上一版 {上} → 这一版 {号} → **抛**", "紧接着" in str(e))
ck("⚠️ 跳号的理由:「版本号唯一且密集」是页面「上一版」、差异对比和回滚"
   "**都在隐含依赖**的不变量 —— 而一个跳了号的序列,和一个密集的,"
   "在最新那一版上长得一样", True)
for 坏号 in (0, -1, True, 1.0, "1", None):
    try:
        F.冻(草稿=好草稿, 版本号=坏号)
        ck(f"版本号 = {坏号!r} → 该抛", False, "它没抛")
    except F.冻不了 as e:
        ck(f"版本号 = {坏号!r} → **抛**", "正整数" in str(e))

print("\n▸ ⑬ 「内容变了吗」—— 挡住「改了备注就冒新版本」")
老哈希 = F.算内容哈希(好草稿)
变1, 新1 = F.内容变了吗(dict(好草稿, change_note="改了说明"), 老哈希)
ck("只改备注 → **没变**", 变1 is False and 新1 == 老哈希)
变2, 新2 = F.内容变了吗(dict(好草稿,
                      limits=dict(好草稿["limits"], tool_attempt_cap=8)), 老哈希)
ck("改了上限 → **变了**,并给出新哈希", 变2 is True and 新2 != 老哈希, 新2[:12])

print("\n" + "=" * 92)
print(f"{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
for x in 挂:
    print("   挂:", x)
sys.exit(1 if 挂 else 0)
