#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写操作确认卡 · 守得住吗(用户 2026-11-11 拍:29 个写操作全部出卡、点了才执行、30 分钟过期、只回文字不算)。

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


def main():
    with tempfile.TemporaryDirectory() as d:
        库 = os.path.join(d, "actions.db")
        生命周期(库)
        指纹()
        工具服务那一层(os.path.join(d, "actions2.db"))
    接线()
    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 写操作确认卡:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
