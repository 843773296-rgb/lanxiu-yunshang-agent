#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「用到时才建」的表,在重建流水线里显式建出来。

## 为什么需要这一步 —— 今天踩了两次

有些模块的表是在第一次调用时建的(`create table if not exists`)。
在开发机上这没问题:跑过一次,表就一直在。

**但 CI 每次从零建库 —— 那些表根本不存在。**

    2026-09-20 第一次:call_audio / call_transcript(ASR 的两张)
    2026-09-20 第二次:cust_owner_log(客户归属的那张)

两次都是同一个形状,而且**两次都是文档表数对账抓到的**(本地 76、CI 75)。

> **「表存在」和「表被建过」不是一回事** —— 本地建过就一直在,CI 每次从零。

第一次我把建表挂到了 `backfill_transcript` 上(它顺带建),
**那是打补丁** —— 下一个只查不改的模块还会再犯。所以这次集中到这一步。

## 什么表该登记在这里

**只查不改的模块的表** —— 它们没有对应的 backfill 脚本,
所以没有任何一步会建它们。有 backfill 的表不必登记(那一步自己会建)。
"""
import os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
DB = os.path.join(HERE, "..", "backend", "lanxiu.db")

# ⚠️ **静态 import,不用 `__import__`。**
# `tools/table_origin_check.py` 要从**文本**上看出「这张表是谁建的」——
# 动态导入的话,那条检查扫不到,一张只在本地存在的表就会溜过去。
# (写这行注释时它正好抓到了 cust_owner_log —— 当时这里还是 `__import__`。)
import ownership, asr, credit, roster, seed_rating
import seed_quote
import report_doc
import arrival_card
import motif_review
import order_contract
import escalation
import triage_run
import refund_write
import triage_config
import triage_trial
import rating_shadow
import grade_diff          # 版师核档差的登记表(2026-10-23,P2)
import tasks
import skill_registry
import mcp_registry
import alert_dispatch
import kb_issue
import report_template
import query_index          # 为真实查询加的索引(2026-10-24,只读审计第 4 条)

# (模块, 建表函数名, 这个模块建的表)  —— **表名列出来是为了能自检**
登记 = [
    (ownership, "建表", ["cust_owner_log"]),
    (asr, "建表", ["call_audio", "call_transcript"]),
    (credit, "建表", ["deal_credit"]),
    (roster, "建表", ["shift_tpl", "roster", "leave_req"]),
    (roster, "建预留表", ["slot_hold"]),
    # 评价表(2026-09-27):**这一版只建表,不铺数据**(业务:造数先别铺)。
    # 挂在这里而不是新加一步 —— 它正是这份文档说的那种「只查不改、没有 backfill 脚本」的表,
    # 没有任何别的一步会建它,而**本地建过就一直在,CI 每次从零**。
    (seed_rating, "建表", ["rating"]),
    # 报价表(2026-09-27):**只建表,不铺数据** —— 报价是 skill 真跑出来的东西,
    # 造一批假报价等于给评测喂一批没人报过的价。
    (seed_quote, "建表", ["quote"]),
    # 经营报告(2026-10-09):店长存的日报 / 周报 / 月报 —— 运行时才写,没有任何一步铺数据
    (report_doc, "建表", ["store_report_doc"]),
    # 上新卡片的 agent 建议(2026-10-10):绑定那一刻写一次 —— 运行时才写
    (arrival_card, "建表", ["recall_advice", "recall_advice_log"]),
    # 纹样业务核定(2026-10-27):**只建表,不铺数据** —— 核定是人做的,造不出来。
    # 登记在这里而不是挂某个 backfill:纹样本来就不落库(是算出来的),
    # 所以没有任何一步会顺带建它。
    (motif_review, "建表", ["product_motif"]),
    # 定制订单确认书(2026-10-10):确认下单时在同一事务里写 —— 运行时才写
    (order_contract, "建表", ["order_contract"]),
    # 研判升级记录(2026-10-17):第一次有人点「升级」时才建 —— 而造研判样本那步(真调模型)会升级一条,
    # 于是**本机从零建库有这张表、CI(调不到模型)没有**,表数随「有没有人升级过」漂。在这里建死
    (escalation, "确保表", ["escalation"]),
    # 研判运行记录(2026-10-18):第一次有人点「研判」、或执行线程第一次报心跳时才建 —— 同上,建死免得表数漂
    (triage_run, "确保表", ["triage_run", "triage_worker"]),
    # 退押金两人复核(2026-10-16 做的写口,10-19 补登记):第一次有人在页面上发起退押金才建 ——
    # 10-19 主库有人真点过,表数 115 → 116、文档对账当场红;CI 从零建没人点过,就是 115。同 escalation 那次
    (refund_write, "建表", ["refund_approval"]),
    # 研判设置(2026-10-19):配置版本 + 提示词版本登记。第一次有人打开设置页才建 —— 同上,建死免得表数漂
    (triage_config, "确保表", ["triage_config", "triage_prompt"]),
    # 隔离试运行的结果(2026-10-20):第一次有人试跑才建 —— 同上,建死免得表数漂
    (triage_trial, "确保表", ["triage_trial"]),
    # 闸四影子台账(2026-10-20):AI 在真实流程旁边跑一遍、结果不进流程。
    # 只有 `agent/triage_shadow.py` 写它,**没有任何对外的口读它**(和 truth 表同一条红线:
    # 处理人先看见 AI 的建议,新量轨那一致率就虚高,而「人工独立判的」和
    # 「人工照着 AI 抄的」在台账上长得一模一样)。登记在这儿的理由和上面几张一样:
    # 第一次有人影子跑才建 —— **本地建过就一直在,CI 每次从零**
    (rating_shadow, "确保表", ["rating_shadow"]),
    # 经营改进 → 报告的哪一项(2026-10-21,经营复盘闭环):第一次有人派「经营改进」才建 —— 同上,建死免得表数漂。
    # 只有一列日期(created,世界的钟,整列日期 → 平移自动挪),其余三列是编号和指标名,不用登记进平移
    (tasks, "建表", ["report_action"]),
    # Skill 管理(2026-10-23,用户拍「做完整配置页」):第一次有人打开 Skill 管理页、或执行闸第一次查状态才建 ——
    # 同上,建死免得表数漂。没登记过的技能按来源取默认状态,所以空表就是「和原来一样」
    (skill_registry, "确保表", ["skill_cfg", "skill_cfg_log"]),
    # MCP 工具开关(2026-10-23,用户拍「MCP 管理带配置」):第一次有人在页面上改才建 —— 同上,建死免得表数漂
    (mcp_registry, "确保表", ["mcp_tool_cfg", "mcp_tool_cfg_log"]),
    # 预警 → 任务的来源(2026-10-23,复审第 4 节 D):第一次有人从预警那一行派单才建 —— 同上,建死免得表数漂。
    # 两列日期:key_date(超期的承诺完工日)、created(世界的钟),都是整列日期、系统写的,不是人填的自由文本
    (alert_dispatch, "建表", ["alert_task"]),
    # 知识问题(2026-10-23,外部复审第 4 节 E):门店检索记录 / 改动日志 / 复验存档。
    # chat 第一次查知识库、或有人打开「知识问题」页才建 —— 同上,建死免得表数漂
    (kb_issue, "确保表", ["kb_rag_record", "kb_rag_record_log", "kb_recheck"]),
    # 报告模板(2026-10-23,复审第 4 节 C):第一次有人打开报告模板页、或取报告时才建 —— 同上,建死免得表数漂。
    # 空表 = 代码默认(全部显示),和模板上线前一样。日期列只有 at(世界时间,整列日期);why 是人填的自由文本。
    # 10-23 加状态线(草稿 → 试运行 → 已发布 / 已撤下):补列在 report_template.确保表 的 `后加列` 里走 ALTER(同 report_doc),
    # 老库加列时 status 默认「已发布」。新日期列 trial_at / publish_at / withdraw_at 是世界时间、整列日期(平移自动挪);
    # trial_why / publish_why / withdraw_why 和 why 一样是人填的原话;trial_shops 是 JSON 门店标识(不含日期)
    (report_template, "确保表", ["report_template_ver"]),
    # 版师核档差的登记(2026-10-23,业务需求池 P2):第一次有版师核一条档差才建 ——
    # 同上,建死免得表数漂。
    # ⚠️ 这张表**不存档差本身**(档差在 `knowledge/10-版型库.md` 里,这个口不改 md),
    # 它存的是「谁、什么时候、凭什么核过的」+ **核的时候那个值是多少** ——
    # 少了最后那样,md 改过之后「核过」会漂到一个没人核过的新值上。
    # 日期只有 `checked_at`(世界的钟,整列日期 → 平移自动挪);
    # ⚠️ 而 `why` 是**人当时写下的原话**,里面的日期不许挪 —— 已登记进
    # `shift_world` 的「文字里不挪」(同 skill_cfg_log.why)。
    (grade_diff, "确保表", ["grade_diff_check"]),
]


def main():
    c = sqlite3.connect(DB)
    建了 = []
    for 模块, 函数名, 表们 in 登记:
        getattr(模块, 函数名)(c)
        建了 += 表们
    c.commit()

    # 索引和上面那些表是**同一个毛病**:本地建过就一直在,CI 每次从零。
    # 而索引比表更难发现 —— 缺一张表会抛异常,**缺一条索引只是慢**。
    新索引 = query_index.建索引(c)
    c.commit()

    # 自检:登记的表**真的存在**。
    # 光调建表函数不够 —— 函数名写错、表名改过,都会静默什么都不做。
    有 = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    缺 = [t for t in 建了 if t not in 有]
    if 缺:
        sys.exit(f"❌ 登记了但没建出来:{缺} —— 多半是建表函数改了名或表名改了")

    print(f"  确保 {len(建了)} 张「用到时才建」的表存在:{'、'.join(建了)}")
    # 索引也自检一次:调了建索引函数不等于索引真的建出来了(名字写错、DDL 语法错都会静默)。
    有索引 = {r[0] for r in c.execute("select name from sqlite_master where type='index'")}
    缺索引 = [ix["名"] for ix in query_index.索引 if ix["名"] not in 有索引]
    if 缺索引:
        sys.exit(f"❌ 登记了但没建出来的**索引**:{缺索引} —— 见 backend/query_index.py")
    print(f"  确保 {len(query_index.索引)} 条查询索引存在(这次新建 {新索引} 条):"
          f"{'、'.join(ix['名'] for ix in query_index.索引)}")
    print(f"  ⚠️ 这一步存在的理由:**本地建过就一直在,CI 每次从零** —— 今天为这个红过两次")
    c.close()


if __name__ == "__main__":
    main()
