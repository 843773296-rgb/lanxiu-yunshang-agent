#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出监督的同步(用户 10-10:AI 管理平台「能看 + 能打回」)—— 一次做两件事:

    ① 推:产出投递箱(报告 / 建议)里还没送到的,推给管理后台
    ② 拉:管理后台上「打回、待执行」的决定拉回来,**用这边自己的函数执行**,再回执
    ③ 桥:管理后台工作流记下的「取转写 / 写跟进」单拉回来,交给 backend/workflow_bridge.py 执行,再回执
       (2026-10-24,音频整理全流程;回执到了,那次运行才从停下的那一步接着走)

    python3 tools/supervise_sync.py            # 推 + 拉,各做一轮
    python3 tools/supervise_sync.py --看        # 只报积压和待执行,什么都不发、不执行
    python3 tools/supervise_sync.py --循环 30   # 每 30 秒一轮(start.sh 里配了地址才起)

地址 / 项目 / 工号和 A1 用同一组环境变量(LANXIU_USAGE_URL / _PROJECT / _USER)。**没配就明说没配**,不给默认值。

## 为什么打回由这边执行

管理后台**绝不反过来改澜绣的库**:它只记下「谁、为什么打回哪一版」;
执行(报告标打回、建议带着理由重写)走这边的正门 —— 那条路上有身份、台账和「打回的不许确认」那道闸。
执行完回执(ack),管理后台上那条决定才变成「已执行」—— **没回执的就一直挂着「待执行」**,
而不是「点了打回」就显示成功、这边其实什么都没发生。
"""
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "agent"), os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import artifact_report as AR
import usage_report as U


def 执行(决定):
    """一条打回决定 → (结果, 说明, 新版本)。外部id 的形状由这边定:报告:RPT… / 建议:商机号:款号。"""
    外部 = 决定.get("外部id") or ""
    谁 = f"{决定.get('created_by') or '?'}(AI 管理平台)"
    理由 = (决定.get("理由") or "").strip() or "(没写理由)"
    try:
        if 外部.startswith("报告:"):
            import report_doc
            ok, 说 = report_doc.打回(外部.split(":", 1)[1], 谁, 理由)
            return ("已标记" if ok else "执行失败"), 说, None
        if 外部.startswith("建议:"):
            import arrival_card
            _, oid, spu = 外部.split(":", 2)
            ok, 说, 新 = arrival_card.打回重写(oid, spu, 谁, 理由)
            return ("已重写" if ok else "执行失败"), 说, 新
        return "执行失败", f"认不出外部id「{外部}」是哪种产出", None
    except Exception as e:
        return "执行失败", f"{type(e).__name__}: {e}"[:200], None


def 跑桥(cfg):
    """③ 桥:拉待执行的桥请求 → workflow_bridge 执行 → 回执。返回 (执行了几张, 错误)。

    回执没送到的单**下一轮还会被拉到** —— 写跟进靠幂等键不写第二条,取转写本来就无害。
    """
    import workflow_bridge as WB
    码, 体 = AR._curl("GET", "/bridge-calls?%E7%8A%B6%E6%80%81=%E5%BE%85%E6%89%A7%E8%A1%8C", cfg)  # 状态=待执行
    if 码 == "404":
        return 0, None          # 管理后台还没有这条接口(老版本)—— 不算错
    if 码 != "200":
        return 0, f"HTTP {码}:{(体 or '')[:160]}" if 码 else 体
    try:
        单们 = json.loads(体).get("rows") or []
    except Exception as e:
        return 0, f"返回不是 JSON:{e}"
    for 单 in 单们:
        结果, 输出, 失败 = WB.执行(单, 谁=单.get("created_by") or "AI 管理平台")
        ok, 回 = AR._curl("POST", f"/bridge-calls/{单['id']}/ack", cfg,
                          {k: v for k, v in dict(结果=结果, 输出=输出, 失败=失败).items() if v is not None})
        说 = (输出 or {}).get("结果") or (失败 or {}).get("消息") or ""
        print(f"   桥 {单.get('工具')} {单['id']} → {结果}:{str(说)[:60]}"
              + ("" if ok in ("200", "201") else f"(⚠️ 回执没送到:{ok} {(回 or '')[:80]})"))
    return len(单们), None


def 补上报(db=None):
    """这个功能上线之前就存下的报告 / 写好的建议,也推一份上去(同一版只排一次,重复跑无害)。返回排了几条。"""
    import json as _j, sqlite3, report_doc, arrival_card as AC
    c = sqlite3.connect(db or report_doc.DB)
    try:
        report_doc.建表(c); AC.建表(c)
        n = 0
        for rid, shop, 版, body, pack, tr in c.execute(
                "SELECT id, shop, revision, body, pack, trace_id FROM store_report_doc").fetchall():
            report_doc.上报监督(rid, shop, _j.loads(pack), body, 版, tr); n += 1
        for oid, spu, 版, 正文, 来源, 模型, 材料, 号 in c.execute(
                "SELECT opp_id, spu, version, text, source, model, input, trace_id FROM recall_advice").fetchall():
            商 = AC._商品(c, spu) or {"名称": spu}
            AC._上报监督(oid, spu, 版, 材料 or "{}", 正文, 来源, 模型, 号, 商, {}, 库=c)
            n += 1
        return n
    finally:
        c.close()


# ── 店长派的任务 → 被派的人的定时提醒(11-22,用户拍 ⑥:自动建、默认截止前 1 小时、被派的人能改能关)────────────────
# 澜绣这边派任务写的是 schedule 表(assignee_no / end_ts);管理后台的「员工定时任务」是另一套库。管理后台**绝不反过来读澜绣的库**,
# 所以由这边推:每轮把新派的、带截止时间的任务 POST 成一条「一次性」提醒(source_ref=task:<单号>,后台按来源去重);
# 任务完结 / 取消了就把那条提醒归档。推过的记在 .feynman/chat_task_pushes.json(**不改澜绣的表**)。
提前分钟 = 60
_推账 = os.path.join(ROOT, ".feynman", "chat_task_pushes.json")


def _读推账():
    try:
        return json.load(open(_推账, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _写推账(d):
    os.makedirs(os.path.dirname(_推账), exist_ok=True)
    tmp = _推账 + ".part"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(tmp, _推账)


def 提醒体(行, 现在=None):
    """一条派单行(schedule)→ 管理后台 POST /chat-tasks 的体;→ None = 不建(没截止 / 截止已过)。
    时刻 = 截止前 提前分钟;要是那一刻已经过了但截止还没到 → 现在 + 1 分钟(马上提醒一次);截止本身过了 → 不建。"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    现在 = 现在 or datetime.now(ZoneInfo("Asia/Shanghai"))
    end = str(行.get("end_ts") or "").strip()
    if not end or not 行.get("assignee_no"):
        return None
    try:
        截 = datetime.strptime(end[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    except ValueError:
        return None
    if 截 <= 现在:
        return None
    提 = 截 - timedelta(minutes=提前分钟)
    if 提 <= 现在:
        提 = 现在 + timedelta(minutes=1)
    备注 = (行.get("note") or "").strip()
    return {"staff_code": 行["assignee_no"], "store_id": 行.get("shop_code") or None,
            "title": f"任务提醒 · {行.get('type') or '任务'}",
            "instruction": (f"店长 {行.get('assigned_by') or ''} 派给你的「{行.get('type') or '任务'}」" + (f":{备注}" if 备注 else "")
                            + (f"(关联 {行['ref_id']})" if 行.get("ref_id") else "") + f",截止 {end}。这是截止前 {提前分钟} 分钟的提醒;提前量在「我的定时」里能改能关。"),
            "task_mode": "提醒", "规则": {"周期": "一次", "时刻": 提.isoformat()},
            "source_ref": f"task:{行['id']}", "note": "店长派任务自动建"}


def _后台(cfg, 项目, 方法, 路径, 体=None, 头=None):
    import urllib.request, urllib.error
    h = {"X-Dev-User": cfg["工号"], **(头 or {})}
    data = None
    if 体 is not None:
        data = json.dumps(体, ensure_ascii=False).encode(); h["content-type"] = "application/json"
    q = urllib.request.Request(f"{cfg['地址'].rstrip('/')}/api/v1/projects/{项目}{路径}", data=data, method=方法, headers=h)
    try:
        with urllib.request.urlopen(q, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": type(e).__name__}


def 推派任务提醒(cfg, 项目, db=None, 现在=None, 看几天=2):
    """→ (新建几条, 归档几条, 说明)。只看最近 看几天 派的(老任务不补提醒);每轮幂等:推过的记账,后台按 source_ref 也去重。"""
    import sqlite3
    from contextlib import closing
    import api
    账 = _读推账()
    新, 归, 错 = 0, 0, []
    # 真实时钟:这段跑在真实世界的 launchd 里,「最近两天派的」按真实日历看;assigned_at 本身就是机器时钟写的
    # (booking.py / fitting_write.py 的注释写明了,每日平移跟着挪),拿世界时钟去比反而对不上。
    with closing(sqlite3.connect(db or api.DB)) as c, c:
        c.row_factory = sqlite3.Row
        行们 = c.execute("""SELECT id, type, assignee_no, assigned_by, end_ts, status, shop_code, note, ref_id FROM schedule
                           WHERE assignee_no IS NOT NULL AND assignee_no <> '' AND end_ts IS NOT NULL AND end_ts <> ''
                             AND assigned_at >= datetime('now', 'localtime', ?)  -- 真实时钟:见上面两行
                           ORDER BY assigned_at""", (f"-{int(看几天)} days",)).fetchall()
    for 行 in 行们:
        行 = dict(行)
        记 = 账.get(行["id"])
        if 行["status"] == "有效" and not 记:
            体 = 提醒体(行, 现在)
            if not 体:
                账[行["id"]] = {"跳过": "没截止或截止已过"}; continue
            码, d = _后台(cfg, 项目, "POST", "/chat-tasks", 体)
            if 码 in (200, 201) and d.get("id"):
                账[行["id"]] = {"chat_task_id": d["id"], "staff_code": 体["staff_code"], "pushed_at": time.strftime("%F %T")}; 新 += 1
            else:
                错.append(f"{行['id']}: {码} {str(d)[:80]}")
        elif 行["status"] != "有效" and 记 and 记.get("chat_task_id") and not 记.get("archived"):
            # 任务完结 / 取消了 → 提醒也收掉(要 revision:先拉一下)
            码, l = _后台(cfg, 项目, "GET", f"/chat-tasks?staff_code={记['staff_code']}&limit=200")
            条 = next((x for x in (l or {}).get("items") or [] if x["id"] == 记["chat_task_id"]), None)
            if 条:
                码, d = _后台(cfg, 项目, "POST", f"/chat-tasks/{记['chat_task_id']}/archive?staff_code={记['staff_code']}", 头={"If-Match": str(条["revision"])})
                if 码 == 200:
                    记["archived"] = time.strftime("%F %T"); 归 += 1
                else:
                    错.append(f"{行['id']} 归档: {码}")
            else:
                记["archived"] = "后台已没有"
    _写推账(账)
    return 新, 归, ("" if not 错 else ";".join(错[:3]))


def 一轮(只看=False):
    cfg = U.配置()
    总, 好, 剩, 老 = AR.积压()
    print(f"产出投递箱:共 {总} 条 · 已送到 {好} · 还剩 {len(剩)}" + (f"(最老的排于 {老})" if 老 else ""))
    if not all(cfg.values()):
        缺 = [k for k, v in cfg.items() if not v]
        print(f"⚠️ 没配管理后台地址({'、'.join(缺)})—— 一条都不会发,也拉不到打回;"
              f"配 LANXIU_USAGE_URL / LANXIU_USAGE_PROJECT / LANXIU_USAGE_USER")
        return 1 if 剩 else 0
    if 只看:
        行们, 错 = AR.待执行的决定(cfg)
        print(f"管理后台上待执行的打回:{len(行们)} 条" + (f"(拉取失败:{错})" if 错 else ""))
        return 0
    发了, 原因 = 0, {}
    for 行 in 剩:
        ok, 说 = AR.发一条(行, cfg)
        if ok:
            AR.确认(行["键"], 说); 发了 += 1
        else:
            原因[说[:60]] = 原因.get(说[:60], 0) + 1
    print(f"推:发出 {发了} 条 · 没发出 {len(剩) - 发了} 条")
    for k, v in 原因.items():
        print(f"   {v} 条:{k}")
    行们, 错 = AR.待执行的决定(cfg)
    if 错:
        print(f"拉:取不到待执行的打回 —— {错}")
        return 1
    print(f"拉:待执行的打回 {len(行们)} 条")
    桥项目 = os.environ.get("LANXIU_BRIDGE_PROJECT")
    if 桥项目:
        # **桥只连澜绣自己的正式项目**(2026-10-24):这一侧写的是真库,而管理后台的端到端测试
        # 在演示项目里造单子、自己扮演澜绣 —— 两边共用一个项目的话,常驻同步会抢测试的单,
        # 把测试编的跟进写进真客户档案。所以单独一个变量,没配就不跑桥(不给默认值)
        n桥, 错桥 = 跑桥({**cfg, "项目": 桥项目})
        print(f"桥({桥项目}):待执行的取转写 / 写跟进 {n桥} 张" + (f"(拉取失败:{错桥})" if 错桥 else ""))
        # 店长派的任务 → 被派的人的一次性提醒(11-22):同样只连正式项目;出错只打印,不影响别的步
        try:
            n新, n归, 说提 = 推派任务提醒(cfg, 桥项目)
            print(f"派任务提醒({桥项目}):新建 {n新} 条 · 归档 {n归} 条" + (f"(⚠️ {说提})" if 说提 else ""))
        except Exception as e:  # noqa: BLE001
            print(f"派任务提醒:这一轮没推成({type(e).__name__}: {str(e)[:120]})")
    else:
        print("桥:没配 LANXIU_BRIDGE_PROJECT —— 不拉工作流的取转写 / 写跟进单")
    for d in 行们:
        结果, 说, 新 = 执行(d)
        ok, 回 = AR.回执(cfg, d["id"], 结果, 说, 新)
        print(f"   {d.get('外部id')} 第 {d.get('版本')} 版 → {结果}:{说}" + ("" if ok else f"(⚠️ 回执没送到:{回})"))
    # 打回重写出来的新版建议刚进投递箱 —— 这一轮顺手推掉,管理后台上马上看得到新版
    if 行们:
        for 行 in AR.积压()[2]:
            ok, 说 = AR.发一条(行, cfg)
            if ok: AR.确认(行["键"], 说)
    return 0 if not 原因 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true")
    ap.add_argument("--循环", type=int, default=0)
    ap.add_argument("--补", action="store_true", help="把上线之前就有的报告 / 建议也排进投递箱")
    a = ap.parse_args()
    if a.补:
        print(f"补排了 {补上报()} 份产出(已排过的同一版不会重复)")
    if a.循环:
        # 循环模式顺带推用量(A1):产出详情页「对应调用链」要靠用量先到 —— 用量没推过去,
        # 报告那头的 trace 在管理后台就找不到,页面上只能显示「这一轮的调用还没推过来」
        import subprocess as _sp
        while True:
            try:
                r = _sp.run([sys.executable, os.path.join(ROOT, "tools", "usage_push.py")], capture_output=True, text=True)
                末 = [l for l in (r.stdout or "").splitlines() if l.strip()]
                if 末: print("用量:" + 末[-1].strip(), flush=True)
            except Exception as e:
                print(f"⚠️ 用量这一轮没推:{type(e).__name__}: {e}", flush=True)
            # 执行记录(证据中心第四个工作包,10-25):聊天站每一轮收尾后推一次,管理后台「运行记录」页才看得到
            try:
                r = _sp.run([sys.executable, os.path.join(ROOT, "tools", "spans_push.py")], capture_output=True, text=True)
                末 = [l for l in (r.stdout or "").splitlines() if l.strip()]
                if 末 and r.returncode != 0 or (末 and "推了" in 末[-1]): print("执行记录:" + 末[-1].strip(), flush=True)
            except Exception as e:
                print(f"⚠️ 执行记录这一轮没推:{type(e).__name__}: {e}", flush=True)
            try: 一轮()
            except Exception as e: print(f"⚠️ 这一轮出错:{type(e).__name__}: {e}", flush=True)
            sys.stdout.flush(); time.sleep(max(10, a.循环))
    sys.exit(一轮(只看=a.看))
