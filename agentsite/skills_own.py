# -*- coding: utf-8 -*-
"""**哪些技能是我们自己的** —— 质量检查只管这些。

## 为什么需要这个文件

`agentsite/.claude/skills/` 下装着自有技能和从 Accio 提取的第三方技能
(**具体几个一律现数,别写在这句话里** —— 2026-11-06 发现这里原来写着「239 个目录、
其中 236 个第三方」,而那时实际只剩 13 个目录。凡是写在话里的条数都会漂,
而漂了的数和对的数在读的人眼里长得一模一样)
(用户明确要求全拿,装完拿评测量过:触发准确率 13/15、误触发 0,
代价是每轮多 2.7 万 token 常驻上下文)。

我们的质量检查(描述够不够长、段落齐不齐、有没有「出错了怎么办」)
是为**自己写的技能**定的。拿它去量别人的技能没有意义:
**别人的描述短不短,不归我们改。** 而且 136 条红会把真正该看的那几条淹掉 ——
**淹掉的红和没有红是一回事。**

## 边界为什么不能是「目录里有什么」

另一个会话诊断这件事时说了一句对的:
**这条检查的边界跟着「这个目录里有什么」走,而那个目录任何人都能往里写。**

他的方案是「只扫 git 跟踪的」。那能让 `git status` 干净,但绕过了真问题:
**该不该 commit 第三方文件,和该不该检查它们,是两件事。**
边界应该跟着**归属**走 —— 谁写的、谁负责改。

## 加一个自己的技能时

在下面这份清单里加一行。**清单是显式的,不是扫出来的** ——
扫出来的清单会把别人扔进来的东西算进你的分母,
而分母一旦被污染,「我们的技能质量」这个数就再也读不出来了。
"""

# 我们自己写的、要对质量负责的技能
OURS = ("quote", "growth-plan", "roster", "deadline-rescue", "exchange", "pattern-draft", "call-notes",
        "store-report",
        "rating-repair",    # 差评与维修研判(2026-10-23,intent/skill-new-batch.md ③)
        "customer-recall",  # 客户召回(2026-10-23,intent/skill-new-batch.md ②)
        # 2026-11-06 用户拍:「把这份第三方技能优化为我的技能,然后删除原来的内容」。
        # ⚠️ **进这份清单有两个连带后果,别只当成一行名单**:
        #   ① 放行的默认值翻面 —— `backend/skill_registry.默认状态`:自有 = 已发布(放行)、
        #      第三方 = 已安装待审查(拦)。库里 `skill_cfg` 一条登记都没有(库重建时丢了),
        #      所以它**从「拦」变成「放行」**。为此它的正文已改成**纯只读**(摘掉了派任务)。
        #   ② `tools/takeover_skills_check.py` 会要求管理后台的 `可接管技能` 也登记它。
        "stock-patrol-lanxiu",
        # 2026-11-17 按用户 11-12 拍的(业务拍板 十一)转自有:两个改造版「近 200 轮各被触发 4 次,是在用的」。
        # 同样的两个连带后果:默认放行(两份正文都是纯只读,只调 activity_roi / channel_compare /
        # weekly_revenue / sales_rank 这类读工具);管理后台 可接管技能 同步登记(takeover_skills_check 守)。
        # 正文里的「改造自」说明按拍板搬出正文,来源记在 frontmatter 的「来源」字段和 third_party_review.json。
        "activity-review-lanxiu",   # 活动投入产出复盘
        "metric-diagnostics-lanxiu")  # 指标异动诊断

# 从 Accio 提取的第三方技能:装了、注册了、能触发,但**不受我们的质量检查管**。
# 它们的来源、体量和验证结果见 accio索引/README.md 和 agentsite/evals/runs/all239.json。
# 2026-11-17 起审查判「不适用」的 212 个不再装在目录里(用户 11-12 拍,业务拍板 十):搬到仓外
# ~/Desktop/accio-拆解/skills-archived-20261117/,tools/install_accio_skills.py 装机时按 third_party_review.json 跳过;
# 留下的只有审查判「可借鉴 / 缺依赖 / 可适配」的。**几个一律现数**(skills_check 会印),这句话里不写数。
THIRD_PARTY_NOTE = "从 Accio 提取,不归我们改;审查判不适用的已归档仓外"


def is_ours(name):
    return name in OURS
