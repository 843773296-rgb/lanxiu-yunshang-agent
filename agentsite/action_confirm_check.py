#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写操作确认卡 · 守得住吗(用户 2026-11-11 拍:写操作出卡、点了才执行、30 分钟过期、只回文字不算;2026-11-25 拍分三档,见 ⑨)。

判据真调被测代码(backend/pending_actions.py、mcp/protocol.Server.handle、agentsite/action_confirm.py),不在这里重实现。
库用临时文件,不碰任何共享库。

  ① 卡的生命周期:建 → 同一轮同参数拿回同一张;别人领不到(404)、本人领一次(原子,第二次 409)、过期 410、取消
  ② 参数指纹:任何一个参数变了指纹就变(卡上看到的 = 执行的)
  ③ 工具服务那一层(**结构**):带卡库时写工具**不执行**只出卡;指纹对得上才执行;参数被改过的不执行;
     读工具照常执行;**不带卡库(评测 / V1 / V2)写工具照旧直接执行** —— 行为不变
  ④ 办过的不再出卡:同一个人同一份参数 30 分钟内成功过 → 告诉模型「已经办过了」,不建新卡、不执行
  ⑤ 「只回文字不算」:执行只有一条路 —— 领取只在 action_confirm.确认 里被调(聊天文字没有任何路径能执行)
  ⑦ 评测别继承开关:聊天站起评测子进程剥掉 LANXIU_CONFIRM_STORE
  ⑥ 接线:聊天站有确认 / 取消两个口、sdk 把卡库路径透传给工具服务、页面每个写操作都有中文名(新加写工具漏了会红)
  ⑧ 11-21 复审两条(用户拍):长回执不截 JSON(卡上是摘要、完整另存带哈希);工具超时 / 没回执 → 「核对中」不记失败、
     同一份参数不再出新卡、页面写「可能已执行,正在核对」并转人工;找不到服务 / 指纹对不上 → 「未执行」
  ⑨ 11-25 用户拍**三档**(backend/pending_actions.风险档 唯一来源):高 每次出卡;中 本人点过一次就记住(按人 × 按工具)、
     以后直接做、能撤;低 直接做。直接做的留「直接执行」卡(谁 / 何时 / 参数 / 回执),并且先过「30 分钟同人同参数办过」那道闸;
     不认识的写工具按高;没有登录身份一律不执行
"""
import ast
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "mcp")]
import pending_actions as PA      # noqa: E402

# 咬合记录(可重放的规格在 tools/bite_specs.json,script 为这个文件的那几条)
咬合 = [
    ('工具服务的确认卡拦截被关掉', '带卡库:写工具**没执行**'),
    ('领取不认发起人', '别人领 → 404'),
    ('档位表的默认值从「高」改成「低」(没定档的写口直接执行)', '不认识的写工具按「高」'),
    ('领取时不再记住中档', '中档本人点过确认 → 记住'),
]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


店长 = {"no": "60000002", "name": "周店长", "role": "店长", "shop": "杭州店"}
顾问 = {"no": "60000011", "name": "林岚", "role": "门店顾问", "shop": "杭州店"}


def 生命周期(库):
    print("▸ ① 卡的生命周期")
    t0 = 1_000_000.0
    a = PA.建(库, "assign_task", "work", {"task": "T1", "to": "60000011"}, 店长, trace="tr1", 现在=t0)
    ck("建出来是「待确认」、有效 30 分钟", a["status"] == "待确认" and a["expires_at"] - a["created_at"] == 30 * 60, a)
    b = PA.建(库, "assign_task", "work", {"to": "60000011", "task": "T1"}, 店长, trace="tr1", 现在=t0 + 5)
    ck("同一轮同一份参数(键顺序不同)再调 → 拿回同一张,不多出卡", b["id"] == a["id"], (a["id"], b["id"]))
    卡, 错 = PA.领取(库, a["id"], 顾问, 现在=t0 + 10)
    ck("别人领 → 404(店长发起的,顾问点不了;不说「有这张卡」)", 卡 is None and 错[0] == 404, 错)
    卡, 错 = PA.领取(库, a["id"], None, 现在=t0 + 10)
    ck("没登录领 → 401", 卡 is None and 错[0] == 401, 错)
    卡, 错 = PA.领取(库, a["id"], 店长, 现在=t0 + 10)
    ck("本人领 → 执行中", 卡 and 卡["status"] == "执行中" and 错 is None, 错)
    卡2, 错2 = PA.领取(库, a["id"], 店长, 现在=t0 + 11)
    ck("再领一次(双击 / 并发)→ 409,不会执行第二次", 卡2 is None and 错2[0] == 409, 错2)
    PA.收尾(库, a["id"], True, {"ok": True})
    ck("收尾 → 已成功", PA.取(库, a["id"], 现在=t0 + 12)["status"] == "已成功")
    c = PA.建(库, "finish_task", "work", {"task": "T2"}, 店长, trace="tr2", 现在=t0)
    卡, 错 = PA.领取(库, c["id"], 店长, 现在=t0 + 30 * 60 + 1)
    ck("过了 30 分钟领 → 410,读出来也是「已过期」", 卡 is None and 错[0] == 410
       and PA.取(库, c["id"], 现在=t0 + 30 * 60 + 1)["status"] == "已过期", 错)
    d = PA.建(库, "finish_task", "work", {"task": "T3"}, 店长, trace="tr3", 现在=t0)
    卡, 错 = PA.取消(库, d["id"], 顾问, 现在=t0 + 1)
    ck("别人取消 → 404", 卡 is None and 错[0] == 404, 错)
    卡, 错 = PA.取消(库, d["id"], 店长, 现在=t0 + 1)
    卡2, 错2 = PA.领取(库, d["id"], 店长, 现在=t0 + 2)
    ck("本人取消 → 已取消;取消后再领 → 409", 卡 and 卡["status"] == "已取消" and 错2 and 错2[0] == 409, (卡, 错2))
    e = PA.建(库, "finish_task", "work", {"task": "T4"}, 店长, trace="tr4", 现在=t0)
    ck("换模型重答:先试那一遍的卡作废", PA.作废本轮(库, "tr4", 现在=t0 + 1) == 1
       and PA.取(库, e["id"], 现在=t0 + 2)["status"] == "已取消")
    try:
        PA.建(库, "finish_task", "work", {"task": "T5"}, None, trace="tr5")
        ck("没有登录身份建卡 → 抛(不建一张谁都能点的卡)", False)
    except PermissionError:
        ck("没有登录身份建卡 → 抛(不建一张谁都能点的卡)", True)


def 指纹():
    print("▸ ② 参数指纹")
    基 = PA.参数指纹("assign_task", {"task": "T1", "to": "60000011"})
    ck("键顺序不同 → 指纹相同", 基 == PA.参数指纹("assign_task", {"to": "60000011", "task": "T1"}))
    ck("换了负责人 → 指纹不同", 基 != PA.参数指纹("assign_task", {"task": "T1", "to": "60000012"}))
    ck("换了工具 → 指纹不同", 基 != PA.参数指纹("reassign_task", {"task": "T1", "to": "60000011"}))


def 工具服务那一层(库):
    print("▸ ③④ 工具服务那一层(结构:模型改得了参数,改不了 env)")
    import protocol
    调了 = []
    写 = ("assign_task", "派任务", {"type": "object"}, lambda **kw: 调了.append(("写", kw)) or {"ok": True, "kw": kw})
    读 = ("list_tasks", "查任务", {"type": "object"}, lambda **kw: 调了.append(("读", kw)) or {"rows": []})
    旧 = {k: os.environ.get(k) for k in ("LANXIU_CONFIRM_STORE", "LANXIU_CONFIRMED", "LANXIU_ME", "LANXIU_TRACE", "LANXIU_TOOLS")}
    try:
        for k in 旧:
            os.environ.pop(k, None)
        os.environ["LANXIU_ME"] = json.dumps(店长, ensure_ascii=False)
        os.environ["LANXIU_TRACE"] = "tr-proto"

        def 调(nm, args):
            s = protocol.Server("t", "1", [写, 读])
            r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nm, "arguments": args}})
            return "".join(c.get("text", "") for c in r["result"]["content"])

        参 = {"task": "T9", "to": "60000011"}
        调了.clear(); 文 = 调("assign_task", 参)
        ck("不带卡库(评测 / V1 / V2):写工具照旧直接执行 —— 行为不变", 调了 == [("写", 参)], (调了, 文[:120]))
        os.environ["LANXIU_CONFIRM_STORE"] = 库
        调了.clear(); 文 = 调("assign_task", 参)
        卡们 = PA.本轮的(库, "tr-proto")
        ck("带卡库:写工具**没执行**,建了一张待确认卡,回给模型的话说「还没有执行」",
           调了 == [] and len(卡们) == 1 and 卡们[0]["status"] == "待确认" and "还没有执行" in 文, (调了, 文[:160], 卡们))
        ck("卡记的是登录身份(env 里的),不是参数里写的", 卡们 and 卡们[0]["asker_no"] == 店长["no"], 卡们)
        调了.clear(); 调("list_tasks", {"shop": "杭州店"})
        ck("带卡库:读工具照常执行(只读不出卡)", 调了 == [("读", {"shop": "杭州店"})], 调了)
        os.environ["LANXIU_CONFIRMED"] = PA.参数指纹("assign_task", {"task": "T9", "to": "60000099"})
        调了.clear(); 文 = 调("assign_task", 参)
        ck("确认的指纹对应的是**另一份参数** → 不执行(卡上看到的才是会执行的)", 调了 == [], (调了, 文[:120]))
        os.environ["LANXIU_CONFIRMED"] = PA.参数指纹("assign_task", 参)
        调了.clear(); 调("assign_task", 参)
        ck("指纹对得上 → 执行", 调了 == [("写", 参)], 调了)
        os.environ.pop("LANXIU_CONFIRMED")
        # ④ 办过的不再出卡:把那张卡走完「点了、成功」
        if not 卡们:
            ck("④ 下一轮模型又调同一份参数 → 不执行、不建新卡,告诉它「已经办过了」", False, "前面没建出卡,这条没法验 —— 不是通过")
            return
        卡 = 卡们[0]
        PA.领取(库, 卡["id"], 店长); PA.收尾(库, 卡["id"], True, {"ok": True})
        os.environ["LANXIU_TRACE"] = "tr-proto-2"
        调了.clear(); 文 = 调("assign_task", 参)
        ck("④ 下一轮模型又调同一份参数 → 不执行、不建新卡,告诉它「已经办过了」",
           调了 == [] and "已经办过了" in 文 and PA.本轮的(库, "tr-proto-2") == [], (调了, 文[:160]))
        os.environ["LANXIU_ME"] = "null"
        调了.clear(); 文 = 调("assign_task", {"task": "T10"})
        ck("没有登录身份:建不了卡 → 不执行、报错(拦住是安全的那一边)", 调了 == [] and "没有执行" in 文, (调了, 文[:160]))
    finally:
        for k, v in 旧.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def 复审两条(库):
    print("▸ ⑧ 11-21 复审:长回执 / 结果不确定")
    import action_confirm as AC
    t0 = 1_700_000_000.0
    # P1-02:两万一千字的结果 —— 原来 json.dumps(...)[:20000] 截成坏 JSON,读回来 JSONDecodeError
    a = PA.建(库, "assign_task", "task", {"task": "L1", "to": "60000011"}, 店长, trace="tr-long", 现在=t0)
    PA.领取(库, a["id"], 店长, 现在=t0 + 1)
    长 = {"ok": True, "正文": "汉" * 21000, "清单": list(range(100)), "嵌": {"套": {"再": {"深": "x" * 500}}}}
    PA.收尾(库, a["id"], True, 长)
    读 = PA.取(库, a["id"], 现在=t0 + 2)
    ck("超两万字的结果:读回来是合法 JSON、状态已成功(原来这里 JSONDecodeError)", 读 is not None and 读["status"] == "已成功" and isinstance(读["result"], dict), 读 and 读["status"])
    ck("卡上是摘要:长字串截到开头 + 「已截短,共 21000 字」、长列表只留前 30 项 + 说明、结构不变",
       读["result"]["ok"] is True and 读["result"]["正文"].endswith("…(已截短,共 21000 字)") and len(读["result"]["正文"]) < 300
       and len(读["result"]["清单"]) == 31 and "共 100 项" in 读["result"]["清单"][-1] and 读["result"]["嵌"]["套"]["再"]["深"].startswith("xxxx"), 读["result"].keys())
    import hashlib
    全 = PA.取完整结果(库, a["id"])
    完整 = json.dumps(长, ensure_ascii=False, default=str)
    ck("完整结果另存:原样全文、sha256 对得上、字节数对得上、卡上的元信息标了「已截短」",
       全 and 全["完整"] == 完整 and 全["哈希"] == hashlib.sha256(完整.encode("utf-8")).hexdigest() and 全["字节"] == len(完整.encode("utf-8"))
       and 读["result_meta"]["已截短"] is True and 读["result_meta"]["哈希"] == 全["哈希"], 读.get("result_meta"))
    短 = PA.建(库, "assign_task", "task", {"task": "S1", "to": "60000011"}, 店长, trace="tr-short", 现在=t0)
    PA.领取(库, 短["id"], 店长, 现在=t0 + 1); PA.收尾(库, 短["id"], True, {"ok": True, "行": 3})
    读短 = PA.取(库, 短["id"], 现在=t0 + 2)
    ck("短结果:摘要 = 原文、标「没截短」", 读短["result"] == {"ok": True, "行": 3} and 读短["result_meta"]["已截短"] is False, 读短.get("result_meta"))
    # P0-01:没回执 / 超时 → 核对中
    ck("解读输出:没有 id=2 的结果 → 「不确定」(不是「没执行」)", AC.解读输出("", "boom")[0] == "不确定" and "stderr" in AC.解读输出("", "boom")[1])
    ck("解读输出:工具自己报错 → 失败;说「还没有执行」→ 未执行;正常结果 → 成功",
       AC.解读输出(json.dumps({"id": 2, "result": {"isError": True, "content": [{"type": "text", "text": "{\"error\": \"x\"}"}]}}))[0] == "失败"
       and AC.解读输出(json.dumps({"id": 2, "result": {"content": [{"type": "text", "text": json.dumps({"text": "这一步还没有执行"}, ensure_ascii=False)}]}}))[0] == "未执行"
       and AC.解读输出(json.dumps({"id": 2, "result": {"content": [{"type": "text", "text": "{\"ok\": true}"}]}})) == ("成功", {"ok": True}), 3)
    ck("状态字:不确定 → 核对中、未执行 → 未执行、失败 → 已失败、成功 → 已成功", AC.状态字 == {"成功": "已成功", "失败": "已失败", "未执行": "未执行", "不确定": "核对中"})
    参 = {"task": "U1", "to": "60000011"}
    b = PA.建(库, "assign_task", "task", 参, 店长, trace="tr-unsure", 现在=t0)
    PA.领取(库, b["id"], 店长, 现在=t0 + 1)
    PA.收尾(库, b["id"], False, {"error": "执行超时(120 秒)"}, 状态="核对中")
    读b = PA.取(库, b["id"], 现在=t0 + 2)
    ck("超时收尾成「核对中」(不是已失败);是终态,再领 → 409", 读b["status"] == "核对中" and 读b["status"] in PA.终态 and PA.领取(库, b["id"], 店长, 现在=t0 + 3)[1][0] == 409, 读b["status"])
    c = PA.建(库, "assign_task", "task", 参, 店长, trace="tr-unsure-2", 现在=t0 + 5)
    ck("核对中的那份参数下一轮再来 → 拿回同一张,不出新卡(重复派单的入口就在这儿)", c["id"] == b["id"] and c["status"] == "核对中", (c["id"], b["id"]))
    话 = PA.给模型的话(c)
    ck("给模型的话:说「还在核对、可能已落库、不要再做一遍」,不说「还没有执行」", "核对" in 话 and "可能已经落库" in 话 and "不要再做一遍" in 话 and "还没有执行" not in 话, 话[:160])
    try:
        PA.收尾(库, b["id"], False, {}, 状态="随便")
        ck("收尾只认四种结束状态", False)
    except ValueError:
        ck("收尾只认四种结束状态", True)
    确认码 = open(os.path.join(HERE, "action_confirm.py"), encoding="utf-8").read()
    段 = 确认码.split("def 确认(", 1)[1]
    ck("接线:确认 把「不确定」收尾成 状态字 里的「核对中」并调 _转人工核对(不是写死 True/False)", "状态=状态字[态]" in 段 and "_转人工核对(" in 段 and "PA.收尾(库, 卡[\"id\"], 成, 结果)" not in 段)
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    ck("页面:有「核对中」「未执行」两种状态的样子,核对中写「可能已执行」「不要重复操作」;成功卡能看完整结果",
       '态 === "核对中"' in 页 and "可能已执行" in 页 and "不要重复操作" in 页 and '态 === "未执行"' in 页 and "/api/action/result?id=" in 页)
    应用 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    ck("聊天站有 GET /api/action/result,调 action_confirm.完整结果、身份取登录会话", '"/api/action/result"' in 应用 and "_ac.完整结果(" in 应用)


def 接线():
    print("▸ ⑤⑥ 接线")
    确认码 = open(os.path.join(HERE, "action_confirm.py"), encoding="utf-8").read()
    领取的地方 = []
    for d, _, fs in os.walk(ROOT):
        # 只按**仓库内的相对路径**跳目录 —— 整条路径里找 ".claude" 的话,在 .claude/worktrees/工 这种检出里
        # 整棵树都会被跳过、一个文件都扫不到,判据红在「扫不到」上(eureka-fc 11-11 在它的检出里撞到)
        段 = os.path.relpath(d, ROOT).split(os.sep)
        if any(x in 段 for x in (".venv", "node_modules", ".claude", "__pycache__", ".git")):
            continue
        for f in fs:
            if f.endswith(".py") and f not in ("pending_actions.py", "action_confirm_check.py"):
                p = os.path.join(d, f)
                try:
                    if "PA.领取(" in open(p, encoding="utf-8").read() or "pending_actions.领取(" in open(p, encoding="utf-8").read():
                        领取的地方.append(os.path.relpath(p, ROOT))
                except (UnicodeDecodeError, OSError):
                    pass
    ck("⑤ 只回文字不算:能让卡执行的「领取」只在 action_confirm 里被调(聊天文字没有路径能执行)",
       领取的地方 == ["agentsite/action_confirm.py"] and "def 确认(" in 确认码, 领取的地方)
    应用 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    段 = 应用.split('"/api/action/confirm"', 1)[1].split("if p ", 1)[0] if '"/api/action/confirm"' in 应用 else ""
    ck("⑥ 聊天站 /api/action/confirm、/api/action/cancel 调的是 action_confirm.确认 / 取消,身份取登录会话",
       "_ac.确认" in 段 and "_ac.取消" in 段 and "_who(self)" in 段)
    ck("⑥ 聊天回答带上这一轮的卡(页面靠它画)", "r[\"待确认卡\"] = _ac.本轮卡(" in 应用)
    # ⑦ 评测别继承开关:聊天站起评测子进程(「跑验证集」)要剥掉 LANXIU_CONFIRM_STORE(eureka-fc 11-11 提醒)
    import action_confirm as AC
    环 = AC.评测环境({"LANXIU_CONFIRM_STORE": "/x", "PATH": "/bin"}, LANXIU_PROVIDER="claude")
    ck("⑦ 评测环境:剥掉确认卡开关、别的照留(不剥 → 评测写操作全变成出卡,分数骤降像模型退步)",
       "LANXIU_CONFIRM_STORE" not in 环 and 环.get("PATH") == "/bin" and 环.get("LANXIU_PROVIDER") == "claude", 环)
    验段 = 应用.split('if 动 == "跑验证集":', 1)[1].split("if 动 ==", 1)[0] if 'if 动 == "跑验证集":' in 应用 else ""
    ck("⑦ 聊天站「跑验证集」起评测用的是 评测环境()(不是 dict(os.environ…))",
       "评测环境(" in 验段 and "dict(os.environ" not in 验段, 验段[:200])
    其它 = [m.start() for m in re.finditer(r"dict\(os\.environ", 应用)]
    ck("⑦ 聊天站里没有别处用 dict(os.environ…) 起子进程(新加的起子进程要过 评测环境 或说明为什么不用)", not 其它, 其它)
    sdk码 = open(os.path.join(HERE, "sdk.py"), encoding="utf-8").read()
    m = re.search(r'for _k in \(([^)]*)\):\s*\n\s*if os\.environ\.get\(_k\)', sdk码)
    ck("⑥ sdk 把 LANXIU_CONFIRM_STORE 透传给工具服务(env 是显式拼的,不透传就到不了 → 卡不生效、写操作直接执行)",
       bool(m) and "LANXIU_CONFIRM_STORE" in m.group(1), m and m.group(1))
    import api
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    mm = re.search(r"const 写操作名 = \{(.*?)\};", 页, re.S)
    页里 = set(re.findall(r"(\w+):\s*\"", mm.group(1))) if mm else set()
    漏 = sorted(set(api.WRITE_TOOLS) - 页里)
    ck(f"⑥ 页面每个写操作都有中文名(登记的 {len(api.WRITE_TOOLS)} 个;新加写工具没起名会红)", mm and not 漏, 漏)
    ck("⑥ 页面:卡有「确认执行」「暂不执行」,点了发到 /api/action/,按钮绑了点击",
       'data-actv="confirm"' in 页 and 'data-actv="cancel"' in 页 and '"/api/action/confirm"' in 页 and '"/api/action/cancel"' in 页
       and 'querySelectorAll("[data-act]")' in 页)


def 三档(库):
    """⑨ 用户 2026-11-25 拍三档:高 每次出卡;中 本人点过一次就记住、以后直接做;低 直接做。直接做的留「直接执行」卡,
    并且先过「30 分钟内同人同参数办过」那道闸。档位表 backend/pending_actions.风险档 是唯一来源。"""
    print("▸ ⑨ 三档(11-25):高每次问 / 中记住 / 低直接做,直接做的留痕、过办过闸、能撤")
    import api
    import protocol
    ck("⑨ 不认识的写工具按「高」(新加写口没定档就先每次都问)", PA.档位("某个还没定档的新写口") == "高", PA.档位("某个还没定档的新写口"))
    漏 = sorted(set(api.WRITE_TOOLS) - set(PA.风险档))
    ck("⑨ 登记的每个写工具都定了档(没定的会按高,但得有人看一眼 —— 新加写工具没定档会红)", not 漏, 漏)
    多 = sorted(set(PA.风险档) - set(api.WRITE_TOOLS))
    ck("⑨ 档位表里没有已经下架的写工具(表漂了没人知道)", not 多, 多)
    ck("⑨ 三档各至少一个工具、钱货类在高", {PA.档位(t) for t in PA.风险档} == {"高", "中", "低"} and PA.档位("open_order") == "高"
       and PA.档位("confirm_order") == "高" and PA.档位("assign_task") == "中" and PA.档位("finish_task") == "低")
    调了 = []
    def 工(名, 中文):
        return (名, 中文, {"type": "object"}, lambda **kw: 调了.append((名, kw)) or {"ok": True, "kw": kw})
    工具们 = [工("open_order", "开单"), 工("assign_task", "派任务"), 工("finish_task", "完成任务")]
    旧 = {k: os.environ.get(k) for k in ("LANXIU_CONFIRM_STORE", "LANXIU_CONFIRMED", "LANXIU_ME", "LANXIU_TRACE", "LANXIU_TOOLS")}
    try:
        for k in 旧:
            os.environ.pop(k, None)
        os.environ["LANXIU_ME"] = json.dumps(店长, ensure_ascii=False)
        os.environ["LANXIU_CONFIRM_STORE"] = 库
        def 调(nm, args, trace):
            os.environ["LANXIU_TRACE"] = trace
            s = protocol.Server("t", "1", 工具们)
            r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nm, "arguments": args}})
            return "".join(c.get("text", "") for c in r["result"]["content"])
        # 低:直接做 + 留痕
        调了.clear(); 文 = 调("finish_task", {"task": "T1"}, "tr9-a")
        卡 = PA.本轮的(库, "tr9-a")
        ck("⑨ 低档(完成任务):**直接执行**,不出待确认卡;留一张「直接执行」卡,回执记在卡上", 调了 == [("finish_task", {"task": "T1"})]
           and len(卡) == 1 and 卡[0]["status"] == "直接执行" and (卡[0]["result"] or {}).get("isError") is False and "T1" in str(卡[0]["result"]), (调了, 卡))
        ck("⑨ 直接执行那张卡:发起人是登录身份、有决定时间、是终态(领不了)", 卡[0]["asker_no"] == 店长["no"] and 卡[0]["decided_at"]
           and 卡[0]["status"] in PA.终态 and PA.领取(库, 卡[0]["id"], 店长)[1][0] == 409, 卡[0])
        调了.clear(); 文 = 调("finish_task", {"task": "T1"}, "tr9-b")
        ck("⑨ 低档 30 分钟内同人同参数再来 → 不执行、不再留痕,告诉模型「已经直接执行过了,不要再做一遍」",
           调了 == [] and "直接执行过了" in 文 and "不要再做一遍" in 文 and PA.本轮的(库, "tr9-b") == [], (调了, 文[:160]))
        # 高:永远出卡,点过也不记
        调了.clear(); 文 = 调("open_order", {"c": "C1"}, "tr9-c")
        高卡 = PA.本轮的(库, "tr9-c")
        ck("⑨ 高档(开单):出卡、没执行", 调了 == [] and len(高卡) == 1 and 高卡[0]["status"] == "待确认", (调了, 高卡))
        PA.领取(库, 高卡[0]["id"], 店长); PA.收尾(库, 高卡[0]["id"], True, {"ok": True})
        ck("⑨ 高档点过确认**不记住**", not PA.记得吗(库, 店长, "open_order"))
        调了.clear(); 文 = 调("open_order", {"c": "C2"}, "tr9-d")
        ck("⑨ 高档换一份参数再来 → 还是出卡、没执行", 调了 == [] and PA.本轮的(库, "tr9-d") and PA.本轮的(库, "tr9-d")[0]["status"] == "待确认", 调了)
        # 中:第一次出卡,点过就记住,以后直接做;能撤
        调了.clear(); 文 = 调("assign_task", {"task": "T2", "to": "60000011"}, "tr9-e")
        中卡 = PA.本轮的(库, "tr9-e")
        ck("⑨ 中档(派任务)第一次:出卡、没执行", 调了 == [] and len(中卡) == 1 and 中卡[0]["status"] == "待确认", (调了, 中卡))
        ck("⑨ 中档没点确认之前不记住", not PA.记得吗(库, 店长, "assign_task"))
        PA.领取(库, 中卡[0]["id"], 店长); PA.收尾(库, 中卡[0]["id"], True, {"ok": True})
        ck("⑨ 中档本人点过确认 → 记住(按人 × 按工具)", PA.记得吗(库, 店长, "assign_task") and not PA.记得吗(库, {"no": "60000099"}, "assign_task"))
        调了.clear(); 文 = 调("assign_task", {"task": "T3", "to": "60000011"}, "tr9-f")
        卡f = PA.本轮的(库, "tr9-f")
        ck("⑨ 中档记住后换一份参数 → **直接执行**,留「直接执行」卡", 调了 == [("assign_task", {"task": "T3", "to": "60000011"})]
           and len(卡f) == 1 and 卡f[0]["status"] == "直接执行", (调了, 卡f))
        调了.clear(); 文 = 调("assign_task", {"task": "T2", "to": "60000011"}, "tr9-g")
        ck("⑨ 中档记住后,30 分钟内点卡办过的那份参数再来 → 不执行(办过闸在记住之前)", 调了 == [] and "办过" in 文, (调了, 文[:160]))
        ck("⑨ 撤记住:只撤自己的,撤了几行照实说", PA.忘掉(库, {"no": "60000099"}, "assign_task") == 0 and PA.忘掉(库, 店长, "assign_task") == 1
           and not PA.记得吗(库, 店长, "assign_task"))
        调了.clear(); 文 = 调("assign_task", {"task": "T4", "to": "60000011"}, "tr9-h")
        ck("⑨ 撤了以后再来 → 又先出卡", 调了 == [] and PA.本轮的(库, "tr9-h") and PA.本轮的(库, "tr9-h")[0]["status"] == "待确认", 调了)
        ck("⑨ 记住的清单只列自己的", PA.记住的(库, 店长) == [] and PA.记住(库, 店长, "dispatch_task") and [r["tool"] for r in PA.记住的(库, 店长)] == ["dispatch_task"])
        ck("⑨ 高 / 低 不进记住表(记住() 只收中档)", not PA.记住(库, 店长, "open_order") and not PA.记住(库, 店长, "finish_task"))
        os.environ["LANXIU_ME"] = "null"
        调了.clear(); 文 = 调("finish_task", {"task": "T5"}, "tr9-i")
        ck("⑨ 没有登录身份:低档也**不执行**(拦住是安全的那一边)", 调了 == [] and "没有执行" in 文, (调了, 文[:160]))
    finally:
        for k, v in 旧.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    应用 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    ck("⑨ 接线:页面画「直接执行」卡、中档卡有「以后还是先问我」(data-forget)并绑了点击;聊天站有 /api/action/forget 路由",
       '"直接执行"' in 页 and "data-forget" in 页 and 'querySelectorAll("[data-forget]")' in 页 and '"/api/action/forget"' in 页
       and '"/api/action/forget"' in 应用)


def 核对回写(库):
    """⑩ 用户 2026-11-25 拍「核对中要回写」:管理后台那条核对待办出了结论 → 写回卡。已执行 → 已成功;未执行 → 未执行;
    说不清 → 还是核对中但带上人的说明。只动「核对中」的卡;接线是聊天站拉(页面打开问一次),不是管理后台推。"""
    print("▸ ⑩ 核对中回写(11-25)")
    t0 = 1_700_000_000.0
    def 一张核对中(轮):
        a = PA.建(库, "assign_task", "task", {"task": 轮, "to": "60000011"}, 店长, trace=轮, 现在=t0)
        PA.领取(库, a["id"], 店长, 现在=t0 + 1)
        PA.收尾(库, a["id"], False, {"error": "超时", "转人工待办": "ho_" + 轮}, 状态="核对中")
        return a["id"]
    a = 一张核对中("hb1")
    ck("⑩ 已执行 → 已成功,结果里带核对结论 / 说明 / 人,原来的「转人工待办」还在", PA.核对回写(库, a, "已执行", "订单表里有", 处理人="U9") == 1
       and PA.取(库, a)["status"] == "已成功" and PA.取(库, a)["result"]["核对结论"] == "已执行" and PA.取(库, a)["result"]["核对人"] == "U9"
       and PA.取(库, a)["result"]["转人工待办"] == "ho_hb1", PA.取(库, a))
    b = 一张核对中("hb2")
    ck("⑩ 未执行 → 未执行", PA.核对回写(库, b, "未执行", "两张表都没有") == 1 and PA.取(库, b)["status"] == "未执行")
    c = 一张核对中("hb3")
    ck("⑩ 说不清 → 还是核对中,但说明带上了卡", PA.核对回写(库, c, "说不清", "查不到") == 1 and PA.取(库, c)["status"] == "核对中"
       and PA.取(库, c)["result"]["核对说明"] == "查不到")
    ck("⑩ 说不清之后再来一次「已执行」还能改(核对中没结束)", PA.核对回写(库, c, "已执行", "后来查到了") == 1 and PA.取(库, c)["status"] == "已成功")
    ck("⑩ 不在核对中的卡(已成功)不动 → 0 行", PA.核对回写(库, a, "未执行", "再来") == 0 and PA.取(库, a)["status"] == "已成功")
    try:
        PA.核对回写(库, b, "差不多", "x"); ck("⑩ 结论乱写 → 抛", False)
    except ValueError:
        ck("⑩ 结论乱写 → 抛", True)
    页 = open(os.path.join(HERE, "web", "station.html"), encoding="utf-8").read()
    应用 = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    胶 = open(os.path.join(HERE, "action_confirm.py"), encoding="utf-8").read()
    反馈 = open(os.path.join(HERE, "answer_feedback.py"), encoding="utf-8").read()
    ck("⑩ 接线:页面画核对中卡时问一次 /api/action/followup(每张卡一个会话只问一次)、聊天站有这条路由、胶水层去问管理后台待办详情",
       "/api/action/followup" in 页 and "核对已问" in 页 and '"/api/action/followup"' in 应用 and "def 跟进核对" in 胶
       and "def 查转人工" in 反馈 and "核对结论" in 胶)
    后台 = open(os.path.join(ROOT, "管理后台", "services", "api", "app", "chat_handoffs_api.py"), encoding="utf-8").read()
    ck("⑩ 管理后台那头:核对待办的意图名和聊天站建待办时带的一致、结论三选一、详情带「核对结论」",
       '核对意图 = "写操作结果核对"' in 后台 and '意图="写操作结果核对"' in 胶 and '"核对结论": _核对结论(r)' in 后台
       and all(x in 后台 for x in ("已执行", "未执行", "说不清")))


def main():
    with tempfile.TemporaryDirectory() as d:
        库 = os.path.join(d, "actions.db")
        生命周期(库)
        指纹()
        工具服务那一层(os.path.join(d, "actions2.db"))
        复审两条(os.path.join(d, "actions3.db"))
        三档(os.path.join(d, "actions4.db"))
        核对回写(os.path.join(d, "actions5.db"))
    接线()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 写操作确认卡:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
