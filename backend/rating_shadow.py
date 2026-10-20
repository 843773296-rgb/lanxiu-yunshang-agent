#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸四影子台账的**建表那一段**,只有建表。

口在 `agent/triage_shadow.py`(挑题 / 影子跑 / 回填 / 报一轮),建表在这儿。

## 为什么分开放,而不是和口写在一个文件里

两个检查各自要求一件事,而它们要求的位置不一样:

· `tools/ensure_tables.py` —— 「用到时才建」的表要在重建流水线里显式建出来。
  **本地建过就一直在,CI 每次从零**;不登记就是一张只在开发机上存在的表。
· `tools/table_origin_check.py` —— 「库里有一张表,谁也建不出它」要红。
  而它跟进 import 时**只看 `backend` / `tools` / `knowledge` 三个目录** ——
  建表函数待在 `agent/` 里,它看不见,于是那张表在它眼里是个孤儿。

把 DDL 放在这儿,两个检查都满足,而且 DDL **只有一份**(两份会漂)。

## 🚫 这张表绝不许经任何 API / 工具暴露

新量轨的全部价值在于**人工那一侧是独立产生的**。处理人要是先看见了 AI 的建议,
一致率就虚高 —— 而**「人工独立判的」和「人工照着 AI 抄的」在台账上长得一模一样**。
所以它和 `truth` 表同一条红线。

⚠️ **这个文件自己只建表,一个 SELECT 都不写** ——
`agent/triage_shadow_check.py` 第 ② 条扫整个 backend / mcp / agentsite,
只放过这一个文件,并且顺手断言它没有读口。读它的那一份在 `agent/` 下,
进不了任何对外的口。
"""

表名 = "rating_shadow"


def 确保表(c):
    """建影子台账。字段分四组:轨别 / AI 侧 / 人工侧 / 判定。

    ⚠️ **`human_at_run` 是轨别的唯一来路** —— 影子跑那一刻库里的人工档是什么。
    空 → 人工还没判 → 新量轨;有值 → 人工早判完了 → 回溯轨。
    为什么不比时间戳:库里的 `handled_at` 是**演示世界的钟**
    (`tools/shift_world.py` 每天把整个世界平移到当天),而 `ran_at` 是**真实时钟**。
    拿它们相减是在比两个不同的钟,**而那个差值看起来完全像个正常的数**。
    """
    # ⚠️⚠️ **表名在 DDL 里写死,不用 f-string。**
    # `tools/table_origin_check.py` 按正则从源码里找 `CREATE TABLE ... <表名>`,
    # 而 `{表名}` 里的 `{` 不是字母 —— **它看不见这张表叫什么**,
    # 于是这张表在它眼里是「库里有一张表,谁也建不出它」(第一版就红在这儿)。
    # > 一句「我把表名参数化了」和一句「这张表没人建得出来」,
    # > **在那条检查的输出上长得一模一样。**
    # 写死的那个名字和 `表名` 这个常量必须一致 ——
    # `agent/triage_shadow_check.py` 有一条就在对这两处。
    c.execute("""CREATE TABLE IF NOT EXISTS rating_shadow(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch TEXT NOT NULL,            -- 一次影子跑一个批次号
        pkg_id TEXT NOT NULL,
        human_at_run TEXT,              -- 影子跑那一刻库里的人工档;轨别由它现算
        track TEXT NOT NULL,            -- 回溯 / 新量。**算出来的,不许手填**
        -- ── AI 侧 ──
        ran_at TEXT NOT NULL,           -- **真实时钟**:影子跑是运维动作,不是演示世界里的事
        provider TEXT, model TEXT, code_ver TEXT, prompt_ver TEXT,
        ai_way TEXT,                    -- 读出来的处理方式;读不出是 NULL(≠ 只回访)
        ai_layer TEXT,                  -- 靠段首 / 段内 / 全文哪一层读出来的,不许混成一个数
        ai_text TEXT,
        got_material INTEGER,           -- 这一轮到底调没调 service_records
        -- 遮了几处。⚠️ **两轨对这个数的要求是反的**:
        --   回溯轨:必须 ≥1 —— 人工处置摆在材料里,遮不住就是开卷,那条不算数;
        --   新量轨:本来就是 0 —— 人工还没判,**答案还不存在**,遮蔽是个空操作。
        -- > 「新量轨本来没有答案可遮」和「回溯轨的遮蔽失效了」
        -- > **在 masked=0 这一个数上长得一模一样** —— 分开它们的只有 track 这一列。
        masked INTEGER,
        -- 这条 AI 答复**到底交付成功没有**(只有「通过 / 修正后通过」算成功)。
        -- ⚠️ 少这一列的话,一条连交付检查都没过的草稿,和一条正经判断,
        -- **在一致率里长得一模一样**;而「曾被打回过」不等于「最终不合格」。
        delivered TEXT, tool_calls INTEGER,
        cost REAL, error TEXT,
        -- ── 人工侧:**后来**独立产生的那一份(回填) ──
        human_way TEXT, human_filled_at TEXT,
        -- ── 判定:按 agent/triage_sets.判一题 算,不在这儿重算一份 ──
        verdict TEXT, judged_at TEXT,
        -- 这条影子结论有没有进过流程。**必须恒为 0** —— 影子的定义就是不改行为
        into_flow INTEGER NOT NULL DEFAULT 0)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_rating_shadow_pkg ON rating_shadow(pkg_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_rating_shadow_track ON rating_shadow(track)")
