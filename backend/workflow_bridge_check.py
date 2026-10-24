# -*- coding: utf-8 -*-
"""澜绣桥 · 检查(2026-10-24,音频整理全流程:管理后台的工作流来要「取转写 / 写跟进」,这边用自己的函数执行)。

全在**库副本**上跑(写跟进真写 followup 和 op_log)。验:
  ① 取转写:有稿的回原文 + 客户号;没有这通录音 / 还没转写 → 失败且码分得开
  ② 写跟进:写一条,台账 ctx 带幂等键;**同一个键再来一次不写第二条**(followup 行数不变,回同一个跟进号)
  ③ 录音不是这个客户的 → 拒(CALL_CUSTOMER_MISMATCH),一行都不写
  ④ 没带幂等键 → 拒;客户不存在 → 拒;认不出的工具 → 不执行
  ⑤ 写进的是副本:真库的 followup 没多出这次检查写的那一条
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import server, oplog, workflow_bridge as WB   # noqa: E401 —— 写口先加载,用副本才改得到它们的 DB
import check_copy

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("写跟进之前不查幂等键", "同一个幂等键再来一次:不写第二条,回同一个跟进号"),
    ("写跟进不核录音是不是这个客户的", "录音不是这个客户的 → 拒,一行都不写"),
    ("取转写没有稿时也回成功", "还没转写的录音 → NO_TRANSCRIPT(不是笼统的失败)"),
    ("create_followup 写回 advisor(表上没有这一列,被静默丢掉)", "新写的跟进记在这位客户的顾问名下(advisor_no 不空、和客户档案一致)"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


def 数(db, sql, *a):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql, a).fetchone()[0]
    finally:
        c.close()


def main():
    print("澜绣桥(取转写 / 写跟进)· 检查")
    print("=" * 80)
    真库 = check_copy.真库
    副本 = check_copy.用副本("wf-bridge-")
    ck("夹具:写口的 DB 都指到了副本", os.path.realpath(server.DB) == os.path.realpath(副本)
       == os.path.realpath(oplog.DB) == os.path.realpath(WB.DB), (server.DB, oplog.DB, WB.DB))
    c = sqlite3.connect(副本)
    有稿 = c.execute("""SELECT a.id, a.customer_id FROM call_audio a JOIN call_transcript t ON t.audio_id=a.id
                         JOIN customer cu ON cu.id=a.customer_id ORDER BY a.id LIMIT 1""").fetchone()
    别的客户 = c.execute("SELECT id FROM customer WHERE id<>? ORDER BY id LIMIT 1", (有稿[1],)).fetchone()[0]
    # 造一通「还没转写」的录音(只在副本上)
    c.execute("INSERT INTO call_audio(id, customer_id, path, source, created, status) "
              "VALUES('TS-CHK-PENDING', ?, '/dev/null', '合成(测试用)', datetime('now'), '排队')", (有稿[1],))
    c.commit(); c.close()
    ck("夹具:库里有一通带转写稿的录音", bool(有稿), 有稿)

    print("\n▸ ① 取转写")
    r = WB.执行({"工具": "取转写", "参数": {"call_id": 有稿[0]}})
    ck("有稿的录音 → 已执行,带原文和这通录音的客户号",
       r[0] == "已执行" and r[1]["text"] and r[1]["customer_id"] == 有稿[1], r)
    r = WB.执行({"工具": "取转写", "参数": {"call_id": "TS-NOPE"}})
    ck("没有这通录音 → CALL_NOT_FOUND", r[0] == "执行失败" and r[2]["code"] == "CALL_NOT_FOUND", r)
    r = WB.执行({"工具": "取转写", "参数": {"call_id": "TS-CHK-PENDING"}})
    ck("还没转写的录音 → NO_TRANSCRIPT(不是笼统的失败)",
       r[0] == "执行失败" and r[2]["code"] == "NO_TRANSCRIPT" and "排队" in r[2]["消息"], r)

    print("\n▸ ② 写跟进 + 幂等")
    前 = 数(副本, "SELECT COUNT(*) FROM followup")
    单 = {"工具": "写跟进", "幂等键": "xr_chk:save:1", "办事人": "U006", "办事人澜绣工号": "60000001",
          "参数": {"customer_id": 有稿[1], "内容": "检查:顾客要宋制褙子", "call_id": 有稿[0]}}
    r1 = WB.执行(单, 谁="U006")
    ck("第一次 → 已执行,是新写的", r1[0] == "已执行" and r1[1]["是新写的"] is True, r1)
    ck("followup 多了一条", 数(副本, "SELECT COUNT(*) FROM followup") == 前 + 1)
    ck("新写的跟进记在这位客户的顾问名下(advisor_no 不空、和客户档案一致)",
       sqlite3.connect(副本).execute("""SELECT COUNT(*) FROM followup f JOIN customer c ON c.id=f.customer_id
                                        WHERE f.id=? AND f.advisor_no IS NOT NULL AND f.advisor_no=c.advisor_no""",
                                     (r1[1]["跟进号"],)).fetchone()[0] == 1, r1)
    ck("台账 ctx 带着幂等键,actor 说清是工作流核对后写的",
       数(副本, "SELECT COUNT(*) FROM op_log WHERE machine='followup' AND code='CREATE' "
                "AND ctx LIKE '%xr_chk:save:1%' AND actor LIKE '%工作流核对后%'") == 1)
    账 = sqlite3.connect(副本).execute("SELECT actor, ctx FROM op_log WHERE machine='followup' AND code='CREATE' "
                                       "AND ctx LIKE '%xr_chk:save:1%'").fetchone() or ("", "{}")
    ck("**台账以绑定员工的名义记,管理后台账号一起记上**(用户 10-24 拍「台账两个名字都记」)",
       "张静静(60000001)" in 账[0] and "U006" in 账[0]
       and json.loads(账[1]).get("澜绣工号") == "60000001" and json.loads(账[1]).get("管理后台账号") == "U006", 账)
    r2 = WB.执行(单, 谁="U006")
    ck("同一个幂等键再来一次:不写第二条,回同一个跟进号",
       r2[0] == "已执行" and r2[1]["是新写的"] is False and r2[1]["跟进号"] == r1[1]["跟进号"]
       and 数(副本, "SELECT COUNT(*) FROM followup") == 前 + 1, (r2, 数(副本, "SELECT COUNT(*) FROM followup") - 前))

    print("\n▸ ③④ 拒的几种")
    前 = 数(副本, "SELECT COUNT(*) FROM followup")
    r = WB.执行({"工具": "写跟进", "幂等键": "xr_chk:save:2",
                 "参数": {"customer_id": 别的客户, "内容": "x", "call_id": 有稿[0]}})
    ck("录音不是这个客户的 → 拒,一行都不写",
       r[0] == "执行失败" and r[2]["code"] == "CALL_CUSTOMER_MISMATCH"
       and 数(副本, "SELECT COUNT(*) FROM followup") == 前, r)
    r = WB.执行({"工具": "写跟进", "参数": {"customer_id": 有稿[1], "内容": "x"}})
    ck("没带幂等键 → 拒", r[0] == "执行失败" and r[2]["code"] == "NO_IDEMPOTENCY_KEY", r)
    r = WB.执行({"工具": "写跟进", "幂等键": "xr_chk:save:4", "办事人": "U001",
                 "参数": {"customer_id": 有稿[1], "内容": "x"}})
    ck("**核对人没绑定澜绣员工 → NOT_BOUND,不以服务身份顶替**",
       r[0] == "执行失败" and r[2]["code"] == "NOT_BOUND" and "U001" in r[2]["消息"], r)
    r = WB.执行({"工具": "写跟进", "幂等键": "xr_chk:save:5", "办事人": "U001", "办事人澜绣工号": "99999999",
                 "参数": {"customer_id": 有稿[1], "内容": "x"}})
    ck("绑定的工号在澜绣不存在 → STAFF_NOT_FOUND", r[0] == "执行失败" and r[2]["code"] == "STAFF_NOT_FOUND", r)
    r = WB.执行({"工具": "写跟进", "幂等键": "xr_chk:save:3", "办事人": "U006", "办事人澜绣工号": "60000001",
                 "参数": {"customer_id": "C-NOPE", "内容": "x"}})
    ck("客户不存在 → 拒", r[0] == "执行失败" and r[2]["code"] == "NO_CUSTOMER", r)
    r = WB.执行({"工具": "改订单", "参数": {}})
    ck("认不出的工具 → 不执行", r[0] == "执行失败" and r[2]["code"] == "UNKNOWN_TOOL", r)
    ck("拒的这几次一行都没写", 数(副本, "SELECT COUNT(*) FROM followup") == 前)

    print("\n▸ ⑥ 业务工具:照名单调澜绣现成的函数,以绑定员工的身份(10-24 六条流程要的能力)")
    店长 = "60000001"
    r = WB.执行({"工具": "get_customer", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"customer_id": 有稿[1]}})
    ck("读(get_customer)以绑定员工的身份执行 → 已执行,带工具原样的返回",
       r[0] == "已执行" and isinstance((r[1] or {}).get("数据"), dict) and not r[1]["数据"].get("error"), r)
    r = WB.执行({"工具": "get_customer", "办事人": "U001", "参数": {"customer_id": 有稿[1]}})
    ck("**读也要绑定**:没绑定 → NOT_BOUND(读的范围按身份定,不以服务身份顶替)",
       r[0] == "执行失败" and r[2]["code"] == "NOT_BOUND", r)
    r = WB.执行({"工具": "open_order", "办事人": "U001", "办事人澜绣工号": 店长, "幂等键": "xr_chk:x", "参数": {}})
    ck("名单外的写口(开单 open_order)→ UNKNOWN_TOOL,不执行", r[0] == "执行失败" and r[2]["code"] == "UNKNOWN_TOOL", r)
    任务前 = 数(副本, "SELECT COUNT(*) FROM schedule")
    派 = {"工具": "assign_task", "办事人": "U001", "办事人澜绣工号": 店长, "幂等键": "xr_chk:task:1",
          "参数": {"type": "电话回电", "assignee": "60000003", "note": "检查:回电确认宋制褙子尺寸", "end": "2026-12-31",
                   "ref_id": 有稿[1]}}
    r1 = WB.执行(dict(派))
    ck("写(assign_task 派回电)→ 已执行,任务表多一条", r1[0] == "已执行" and r1[1]["是新执行的"] is True
       and 数(副本, "SELECT COUNT(*) FROM schedule") == 任务前 + 1, (r1, 数(副本, "SELECT COUNT(*) FROM schedule") - 任务前))
    r2 = WB.执行(dict(派))
    ck("**同一个幂等键再来一次:不派第二条,回原来的结果**", r2[0] == "已执行" and r2[1]["是新执行的"] is False
       and 数(副本, "SELECT COUNT(*) FROM schedule") == 任务前 + 1, (r2, 数(副本, "SELECT COUNT(*) FROM schedule") - 任务前))
    ck("台账里 START / DONE 各一笔,actor 是绑定员工 + 管理后台账号",
       数(副本, "SELECT COUNT(*) FROM op_log WHERE machine='bridge' AND target='xr_chk:task:1' AND code='START' "
                "AND actor LIKE '%张静静(60000001)%U001%'") == 1
       and 数(副本, "SELECT COUNT(*) FROM op_log WHERE machine='bridge' AND target='xr_chk:task:1' AND code='DONE'") == 1)
    # 进程死在「写进去」和「记 DONE」之间:台账只有 START —— 重来不许盲目重做
    oplog.log_op("检查", "bridge", "xr_chk:task:2", "—", "assign_task", True, "START", "模拟写了一半", {})
    r3 = WB.执行(dict(派, 幂等键="xr_chk:task:2"))
    ck("**只见 START 不见 DONE → IN_DOUBT,不重做**(上一次可能写了一半,交给人核)",
       r3[0] == "执行失败" and r3[2]["code"] == "IN_DOUBT"
       and 数(副本, "SELECT COUNT(*) FROM schedule") == 任务前 + 1, r3)
    拒 = WB.执行(dict(派, 幂等键="xr_chk:task:4", 参数=dict(派["参数"], ref_id=None)))
    ck("**工具拒了(回电没给客户号,返回 ok=False)→ TOOL_REFUSED,台账记 FAIL 不记 DONE**(被拒不许当成成功)",
       拒[0] == "执行失败" and 拒[2]["code"] == "TOOL_REFUSED"
       and 数(副本, "SELECT COUNT(*) FROM op_log WHERE machine='bridge' AND target='xr_chk:task:4' AND code='DONE'") == 0, 拒)
    拒2 = WB.执行(dict(派, 幂等键="xr_chk:task:4", 参数=dict(派["参数"], ref_id=None)))
    ck("被拒之后同一个键再来:照样去判(没记 DONE,不会回一个假的「已经执行过」)",
       拒2[0] == "执行失败" and 拒2[2]["code"] == "TOOL_REFUSED", 拒2)
    r4 = WB.执行(dict(派, 幂等键=None))
    ck("写口没带幂等键 → 不执行", r4[0] == "执行失败" and r4[2]["code"] == "NO_IDEMPOTENCY_KEY", r4)
    r5 = WB.执行(dict(派, 幂等键="xr_chk:task:3", 参数={"type": "电话回电"}))
    ck("参数不对 → BAD_ARGS,一条都没派", r5[0] == "执行失败" and r5[2]["code"] == "BAD_ARGS"
       and 数(副本, "SELECT COUNT(*) FROM schedule") == 任务前 + 1, r5)

    print("\n▸ ⑤ 写进的是副本")
    ck("真库的台账里没有这次检查的幂等键",
       数(真库, "SELECT COUNT(*) FROM op_log WHERE ctx LIKE '%xr_chk:save:%'") == 0)

    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 澜绣桥:取转写分得清没稿 / 没录音;写跟进同一个键只写一条、不记到别人名下(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
