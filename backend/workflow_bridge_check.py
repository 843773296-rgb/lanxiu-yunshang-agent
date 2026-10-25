# -*- coding: utf-8 -*-
"""澜绣桥 · 检查(2026-10-24,音频整理全流程:管理后台的工作流来要「取转写 / 写跟进」,这边用自己的函数执行)。

全在**库副本**上跑(写跟进真写 followup 和 op_log)。验:
  ① 取转写:有稿的回原文 + 客户号;没有这通录音 / 还没转写 → 失败且码分得开
  ② 写跟进:写一条,台账 ctx 带幂等键;**同一个键再来一次不写第二条**(followup 行数不变,回同一个跟进号)
  ③ 录音不是这个客户的 → 拒(CALL_CUSTOMER_MISMATCH),一行都不写
  ④ 没带幂等键 → 拒;客户不存在 → 拒;认不出的工具 → 不执行
  ⑤ 写进的是副本:真库的 followup 没多出这次检查写的那一条
  ⑧ 召回名单 / 派回访任务(六条第五条,10-25):交叉对得上逐人真调的两份名单;派的时候逐人跳过(不在名单 / 顾问不在职 /
     已有未完成回访 / 派之前已没由头 / 上次开始了没结果),同一个键重来不派第二条
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "knowledge")]
import server, oplog, workflow_bridge as WB   # noqa: E401 —— 写口先加载,用副本才改得到它们的 DB
import api, tasks, revive, slipping, alert_dispatch, rating_write, repair_write   # noqa: E401,F401 —— 召回的两份名单在函数里懒加载 revive / slipping,不先加载就读真库
import check_copy

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("写跟进之前不查幂等键", "同一个幂等键再来一次:不写第二条,回同一个跟进号"),
    ("写跟进不核录音是不是这个客户的", "录音不是这个客户的 → 拒,一行都不写"),
    ("取转写没有稿时也回成功", "还没转写的录音 → NO_TRANSCRIPT(不是笼统的失败)"),
    # 10-25:_insert 改成对不上的列名直接抛(0069803)之后,这处破坏在写的那一刻就崩 —— 红在「第一次已执行」,比原来那条更早
    ("create_followup 写回 advisor(表上没有这一列,被静默丢掉)", "第一次 → 已执行,是新写的"),
    ("派回访任务不查客户号在不在召回名单里", "不在这次召回名单里的客户号 → 跳过,不派"),
    ("派回访任务不查已有未完成的回访", "已有未完成回访任务的客户 → 跳过,不派第二条"),
    ("召回名单只看促活那一页,不逐人问流失预警", "名单上每个人的「同时在流失预警里」都和单独问流失预警的结果一致"),
    ("差评处置不先查金额授权(超店长权限照样建单)", "判给企业、预估 2000 元(超店长权限)→ OVER_AUTHORITY,返修单一张没多"),
    ("补货跟进绕过预警派单直接派(派的那一刻不重算档位)", "卖不动的 SKU 硬派 → 拒(不在要补货的预警里)"),
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
    报1 = WB.执行({"工具": "store_report", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"kind": "周"}})
    报2 = WB.执行({"工具": "store_report", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"kind": "周"}})
    ck("读回的数据带指纹:连取两次经营数据 → 指纹一样(经营报告保存前靠它判「核对期间数据变了没有」)",
       报1[0] == "已执行" and 报1[1].get("指纹") and 报1[1]["指纹"] == (报2[1] or {}).get("指纹"), (报1[1] or {}).get("指纹"))
    ck("数据不同 → 指纹不同(同一个函数,不是恒等)",
       WB.数据指纹({"营收": 100}) != WB.数据指纹({"营收": 101}) and WB.数据指纹({"a": 1, "b": 2}) == WB.数据指纹({"b": 2, "a": 1}))
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

    print("\n▸ ⑦ 订单交付风险(六条第三条,用户 10-25 拍「全用规则分档」):只查这一单、以绑定员工身份")
    在产 = sqlite3.connect(副本).execute(
        "SELECT o.id FROM ordr o JOIN staff s ON s.no=? WHERE o.kind='定制品订单' AND o.prd_status='待发货' "
        "AND o.shop_code=s.shop_code ORDER BY o.id LIMIT 1", (店长,)).fetchone()
    ck("夹具:店长那家店有一笔在产的定制单", bool(在产), 在产)
    if 在产:
        r = WB.执行({"工具": "订单交付风险", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"order_id": 在产[0]}})
        数据 = (r[1] or {}).get("数据") or {}
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "knowledge"))
        import delivery_risk as _DR
        ck("查到 → 已执行,订单号就是这一单,档是六档之一,带指纹",
           r[0] == "已执行" and 数据.get("订单号") == 在产[0] and 数据.get("风险", {}).get("档") in _DR.档们
           and (r[1] or {}).get("指纹"), (r[0], 数据.get("订单号"), 数据.get("风险")))
        ck("**取数包里只有这一单**(不把「该催工厂」全店那张清单拼进来)",
           (数据.get("订单") or {}).get("订单") in (在产[0], None) and "该催" not in 数据,
           list(数据.keys()))
        ck("要不要跟踪由档决定(已延期 / 需关注才要)",
           数据.get("要跟踪吗") == (数据.get("风险", {}).get("档") in _DR.要跟踪的档), 数据.get("要跟踪吗"))
    r = WB.执行({"工具": "订单交付风险", "办事人": "U001", "参数": {"order_id": "6488012800001279984"}})
    ck("没绑定 → NOT_BOUND,不以服务身份顶替", r[0] == "执行失败" and r[2]["code"] == "NOT_BOUND", r)
    r = WB.执行({"工具": "订单交付风险", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"order_id": "NOPE"}})
    ck("没有这一单 → 拒,不编", r[0] == "执行失败" and r[2]["code"] == "TOOL_REFUSED", r)

    print("\n▸ ⑧ 召回名单 / 派回访任务(六条第五条,10-25;交叉复用「客户召回」技能第二步)")
    r = WB.执行({"工具": "召回名单", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"上限": 6}})
    召 = (r[1] or {}).get("数据") or {}
    人 = 召.get("名单") or []
    ck("店长 → 已执行,列出 ≤ 上限,带指纹,样本至少 5 人(下面派的五种情形要用)",
       r[0] == "已执行" and len(人) == 召.get("列出") and 5 <= len(人) <= 6 and r[1].get("指纹"), (r[0], len(人), r[2]))
    with api.as_user(WB.员工身份(店长)):
        逐 = {p["客户号"]: (api.churn_watch(customer=p["客户号"]) or {}).get("这一个人") or {} for p in 人}
        等 = [(w["客户号"], (api.revive_list(customer=w["客户号"]) or {}).get("这一个人") or {})
             for w in 召.get("在流失、等由头") or []]
    ck("真库上:名单上每个人的标注和单独问流失预警一致",
       all(p["同时在流失预警里"] == bool(逐[p["客户号"]].get("在不在往下走")) for p in 人),
       [(p["客户号"], p["同时在流失预警里"], 逐[p["客户号"]].get("在不在往下走")) for p in 人])
    ck("「在流失、等由头」里的人单独问促活都是没由头的(有由头的应该进名单)",
       all(not x.get("该不该联系") for _, x in 等), 等[:3])
    ck("两份都在的排在前面(同时在流失的不会排在只在促活的后面)",
       [p["同时在流失预警里"] for p in 人] == sorted([p["同时在流失预警里"] for p in 人], reverse=True))
    ck("每个人带归属顾问和在不在职、名单文字里有每个客户号",
       all("归属顾问在职" in p and p["客户号"] in 召.get("名单文字", "") for p in 人))
    # 自造两页,真调交叉那一份:真库上两页的头部往往是同一批人,「没逐人问」的破坏被截断盖住(10-25 咬合当场没红)
    促页 = [{"客户号": "A", "客户": "甲", "由头": "BIRTHDAY"}, {"客户号": "B", "客户": "乙", "由头": "RHYTHM_BREAK"},
           {"客户号": "C", "客户": "丙", "由头": "SAME_SEASON"}]
    流页 = {"高": [{"客户号": "D", "客户": "丁", "走到哪一步": "忠诚 → 沉睡"}],
           "中": [{"客户号": "B", "客户": "乙"}, {"客户号": "E", "客户": "戊", "走到哪一步": "活跃 → 沉睡"}]}
    在流失 = {"A": "低", "B": "中", "D": "高", "E": "中"}           # A 在流失但不在流失那一页(页外)
    有由头 = {"A", "B", "C", "D"}                                  # D 有由头但不在促活那一页
    名, 等, 截 = WB.交叉(促页, 流页, lambda x: {"在不在往下走": x in 在流失, "严重程度": 在流失.get(x)},
                      lambda x: {"该不该联系": x in 有由头, "码": "BIRTHDAY" if x in 有由头 else "NO_REASON", "理由": "造的"}, 10)
    标 = {p["客户号"]: (p["同时在流失预警里"], p["流失严重程度"]) for p in 名}
    ck("名单上每个人的「同时在流失预警里」都和单独问流失预警的结果一致",
       标 == {"A": (True, "低"), "B": (True, "中"), "C": (False, None), "D": (True, "高")}, 标)
    ck("流失页上有由头的(D)进名单、没由头的(E)进「在流失、等由头」",
       "D" in 标 and [w["客户号"] for w in 等] == ["E"], ([*标], 等))
    ck("两份都在的按严重程度排前面,只在促活的(C)排最后", [p["客户号"] for p in 名] == ["D", "B", "A", "C"],
       [p["客户号"] for p in 名])
    名, _, 截 = WB.交叉(促页, 流页, lambda x: {"在不在往下走": x in 在流失, "严重程度": 在流失.get(x)},
                     lambda x: {"该不该联系": x in 有由头}, 2)
    ck("截到上限时,被挤出去的人数报出来(不然「还有没列出的」少算)", [p["客户号"] for p in 名] == ["D", "B"] and 截 == 2, (名, 截))
    r = WB.执行({"工具": "召回名单", "办事人": "U001", "参数": {}})
    ck("召回名单没绑定 → NOT_BOUND", r[0] == "执行失败" and r[2]["code"] == "NOT_BOUND", r)

    if len(人) >= 5:
        a, b, c_, e, f = (p["客户号"] for p in 人[:5])
        c = sqlite3.connect(副本)
        c.execute("UPDATE customer SET advisor_no='69999999' WHERE id=?", (b,))          # 顾问不在了
        c.execute("INSERT INTO schedule(id,type,advisor_no,customer_id,start_ts,end_ts,status,shop,assignee_no,note) "
                  "VALUES('SC-CHK-OPEN','电话回电',?,?,'2026-10-01 10:00','2026-12-31 18:00','有效','x',?,'检查造的')",
                  (人[2]["归属顾问工号"], c_, 人[2]["归属顾问工号"]))                       # 已有未完成回访
        c.execute("INSERT INTO followup(id,customer_id,ts,content) VALUES('FU-CHK-RECENT',?,?,'检查造的:刚联系过')",
                  (e, str(__import__("worldclock").今天())[:10] + " 09:00"))                 # 派之前已经没由头了
        c.commit(); c.close()
        oplog.log_op("检查", "bridge", f"xr_chk:recall:1:{f}", "—", "派回访任务", True, "START", "检查造的:开始了没结果", {})
        前 = 数(副本, "SELECT COUNT(*) FROM schedule")
        参 = {"客户号们": f"{a},{b}, {c_},C00000000,{e},{f}", "截止": "2026-12-31", "名单": 人,
             "话术": [{"客户号": a, "开口说什么": "检查造的开口话"}]}
        单 = {"工具": "派回访任务", "幂等键": "xr_chk:recall:1", "办事人": "U001", "办事人澜绣工号": 店长, "参数": 参}
        r = WB.执行(单)
        出 = (r[1] or {}).get("数据") or {}
        跳 = " ".join(出.get("跳过") or [])
        ck("正常的那个 → 派了一条「电话回电」给归属顾问,挂客户号,描述带由头和话术",
           r[0] == "已执行" and 数(副本, "SELECT COUNT(*) FROM schedule WHERE type='电话回电' AND customer_id=? AND assignee_no=? "
                                  "AND status='有效' AND note LIKE '%检查造的开口话%' AND end_ts='2026-12-31 18:00'",
                                  a, 人[0]["归属顾问工号"]) == 1, (r, 出))
        ck("不在这次召回名单里的客户号 → 跳过,不派", "C00000000:不在这次的召回名单里" in 跳, 跳)
        ck("归属顾问不在职 → 跳过,说转店长分配", f"{b}:" in 跳 and "转店长分配" in 跳, 跳)
        ck("已有未完成回访任务的客户 → 跳过,不派第二条", f"{c_}:已有未完成的回访任务 SC-CHK-OPEN" in 跳, 跳)
        ck("派之前再核一次已经没由头了(刚联系过)→ 跳过", f"{e}:派之前再核一次" in 跳, 跳)
        ck("上次开始了没记结果 → 不重做,请人核实", f"{f}:上一次开始派了但没记下结果" in 跳, 跳)
        ck("这一轮只多了一条任务", 数(副本, "SELECT COUNT(*) FROM schedule") == 前 + 1, 数(副本, "SELECT COUNT(*) FROM schedule") - 前)
        r = WB.执行(单)
        ck("同一个键再来一次 → 不派第二条,说之前派过", 数(副本, "SELECT COUNT(*) FROM schedule") == 前 + 1
           and "没派第二遍" in " ".join(((r[1] or {}).get("数据") or {}).get("派了") or []), r)
        r = WB.执行({**单, "幂等键": None})
        ck("没幂等键 → 不派", r[0] == "执行失败" and r[2]["code"] == "NO_IDEMPOTENCY_KEY", r)
        r = WB.执行({**单, "幂等键": "xr_chk:recall:2", "参数": {**参, "名单": []}})
        ck("没带召回名单 → 一个都不派(不知道哪些人是核过的)", r[0] == "执行失败" and r[2]["code"] == "MISSING", r)

    print("\n▸ ⑨ 补货预警 / 派补货跟进(六条第六条,10-25;档和防重复派都用澜绣现成的预警派单)")
    cc = sqlite3.connect(副本); cc.row_factory = sqlite3.Row
    档们 = alert_dispatch.全部sku档(cc)
    sh = cc.execute("SELECT shop FROM staff WHERE no=?", (店长,)).fetchone()[0]
    cc.close()
    快 = next((k for k, v in sorted(档们.items()) if v == "快没了"), None)
    压 = next((k for k, v in sorted(档们.items()) if v == "卖不动"), None)
    ck("夹具:库里有「快没了」和「卖不动」的 SKU", bool(快 and 压), (快, 压))
    r = WB.执行({"工具": "补货预警", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"sku": 快}})
    ck("快没了 → 要派,带库存和指纹", r[0] == "已执行" and r[1]["数据"]["要派吗"] is True and r[1].get("指纹"), r)
    r = WB.执行({"工具": "补货预警", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"sku": 压}})
    ck("卖不动(压货)→ 不派补货,说明只出处理建议", r[0] == "已执行" and r[1]["数据"]["要派吗"] is False
       and "压货" in r[1]["数据"]["说明"], r)
    前 = 数(副本, "SELECT COUNT(*) FROM schedule WHERE type='补货跟进'")
    单 = {"工具": "派补货跟进", "幂等键": "xr_chk:restock:1", "办事人": "U001", "办事人澜绣工号": 店长,
         "参数": {"sku": 快, "负责人": 店长, "截止": "2026-12-31", "note": "检查造的补货"}}
    r = WB.执行(单)
    ck("派补货跟进 → 派了一条,挂这个 SKU", r[0] == "已执行" and
       数(副本, "SELECT COUNT(*) FROM schedule WHERE type='补货跟进' AND ref_id=? AND status='有效'", 快) >= 1
       and 数(副本, "SELECT COUNT(*) FROM schedule WHERE type='补货跟进'") == 前 + 1, r)
    r = WB.执行(单)
    ck("同一张单再来一次 → 不派第二条", 数(副本, "SELECT COUNT(*) FROM schedule WHERE type='补货跟进'") == 前 + 1
       and r[1] and r[1].get("是新执行的") is False, r)
    r = WB.执行({**单, "幂等键": "xr_chk:restock:2"})
    ck("同一个 SKU 换一张单再派 → 拒(上一条没办完)", r[0] == "执行失败" and
       数(副本, "SELECT COUNT(*) FROM schedule WHERE type='补货跟进'") == 前 + 1, r)
    r = WB.执行({**单, "幂等键": "xr_chk:restock:3", "参数": {**单["参数"], "sku": 压}})
    ck("卖不动的 SKU 硬派 → 拒(不在要补货的预警里)", r[0] == "执行失败" and "不在要补货的预警里" in r[2]["消息"], r)

    print("\n▸ ⑩ 差评研判 / 差评处置(六条第四条,10-25;用户拍「超店长权限的停下报总部,不写」)")
    cc = sqlite3.connect(副本)
    待 = [x[0] for x in cc.execute("""SELECT r.pkg_id FROM task t JOIN rating r ON r.task_id=t.id JOIN ordr o ON o.id=r.order_id
                                     WHERE t.type='评价差评' AND t.status='待处理' AND o.shop=? ORDER BY r.pkg_id LIMIT 3""", (sh,))]
    外 = cc.execute("""SELECT r.pkg_id FROM task t JOIN rating r ON r.task_id=t.id JOIN ordr o ON o.id=r.order_id
                      WHERE t.type='评价差评' AND o.shop<>? LIMIT 1""", (sh,)).fetchone()
    cc.close()
    ck("夹具:本店有 3 条待处理差评、别店有 1 条", len(待) == 3 and 外, (待, 外))
    if len(待) == 3 and 外:
        r = WB.执行({"工具": "差评研判", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"pkg": 待[0]}})
        ck("研判 → 带差评、服务记录、判责建议(判得出就引判定表,判不出说交店长)",
           r[0] == "已执行" and "判责建议" in r[1]["数据"] and ("判定表" in r[1]["数据"]["说明"]), r)
        r = WB.执行({"工具": "差评研判", "办事人": "U001", "办事人澜绣工号": 店长, "参数": {"pkg": 外[0]}})
        ck("别店的差评 → 拒", r[0] == "执行失败", r)
        修前 = 数(副本, "SELECT COUNT(*) FROM maintain")
        r = WB.执行({"工具": "差评处置", "幂等键": "xr_chk:rating:1", "办事人": "U001", "办事人澜绣工号": 店长,
                    "参数": {"pkg": 待[0], "处置": "返修", "责任方": "企业", "预估费用": 2000}})
        ck("判给企业、预估 2000 元(超店长权限)→ OVER_AUTHORITY,返修单一张没多",
           r[0] == "已执行" and r[1]["数据"].get("写了") is False and r[1]["数据"].get("停在") == "OVER_AUTHORITY"
           and "报总部" in r[1]["结果"]
           and 数(副本, "SELECT COUNT(*) FROM maintain") == 修前, r)
        r = WB.执行({"工具": "差评处置", "幂等键": "xr_chk:rating:2", "办事人": "U001", "办事人澜绣工号": 店长,
                    "参数": {"pkg": 待[1], "处置": "说明后关闭", "关闭方式": "全额退款", "说明": "x"}})
        ck("关闭方式要出钱(全额退款)→ 不关,回澜绣办", r[0] == "已执行" and r[1]["数据"].get("停在") == "MONEY_NOT_IN_FLOW"
           and 数(副本, "SELECT COUNT(*) FROM task t JOIN rating r ON r.task_id=t.id WHERE r.pkg_id=? AND t.status='待处理'", 待[1]) == 1, r)
        关单 = {"工具": "差评处置", "幂等键": "xr_chk:rating:3", "办事人": "U001", "办事人澜绣工号": 店长,
               "参数": {"pkg": 待[1], "处置": "说明后关闭", "关闭方式": "只回访", "说明": "检查造的:已电话回访,顾客接受说明"}}
        r = WB.执行(关单)
        ck("说明后关闭(只回访)→ 差评关了", r[0] == "已执行", r)
        r2 = WB.执行(关单)
        ck("同一张单再来一次 → 不做第二遍", r2[0] == "已执行" and r2[1].get("是新执行的") is False, r2)
        r = WB.执行({"工具": "差评处置", "幂等键": "xr_chk:rating:4", "办事人": "U001", "办事人澜绣工号": 店长,
                    "参数": {"pkg": 待[2], "店长定的": {"处置": "返修", "责任方": "企业", "预估费用": "300", "决定": "approve"}}})
        ck("判给企业、300 元(店长权限内,店长定的整包传进来)→ 建了返修单并判责", r[0] == "已执行" and r[1]["数据"].get("返修单")
           and 数(副本, "SELECT COUNT(*) FROM maintain") == 修前 + 1, r)

    print("\n▸ ⑤ 写进的是副本")
    ck("真库的台账里没有这次检查的幂等键",
       数(真库, "SELECT COUNT(*) FROM op_log WHERE ctx LIKE '%xr_chk:save:%' OR target LIKE 'xr_chk:%'") == 0)

    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 澜绣桥:取转写分得清没稿 / 没录音;写跟进同一个键只写一条、不记到别人名下(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
