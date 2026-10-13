#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""差评研判产线路 · 检查 —— **不调模型、不花钱**,库只在临时副本上动。

    ./agentsite/.venv/bin/python agentsite/rating_triage_check.py

用户 2026-10-13 拍「做产线那条路」,而业务 10-10 拍过「差评 AI 默认关闭」——
所以这条路是**接通、不启用**。要守的四件事:

  ① **开关默认关**:产线入口照旧当场说「默认关闭」,只有显式 `开差评=True` 才进分支
  ② **遮蔽在工具层、而且只遮被判那一条**:被判那条的人工处置抹成 None,
     同一个客户的**别的**差评原样给(那是「第一次还是第三次」的依据,遮了就没材料了);
     不设 `LANXIU_JUDGING_PKG` 时一处都不遮(人在后台复核要看全)
  ③ `被判包裹` 真的传到了**每个**工具服务的 env 里(只传给一个,另两个就是漏洞)
  ④ 落库记下「哪版提示词 + 这一轮调没调取材料的工具」

⚠️ 遮蔽要攻击的形状**自己造**(副本上给同一个客户摆两条已处置的差评),不靠库里碰上的 ——
CI 上库是从零建的,碰上的样本不一定在(10-13 销账那条就是这么本地绿、CI 红的)。
"""
import json, os, shutil, sqlite3, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "mcp")):
    sys.path.insert(0, _p)
G, R, D = "\033[32m", "\033[31m", "\033[0m"
bad, n = [], 0

咬合 = [
    ("协议层不遮(遮被判那条原样返回)", "工具层:被判那条的人工处置抹成 None"),
    ("遮蔽不看被判的包裹号,同一客户的差评全遮", "工具层:同一客户的另一条差评原样给(那是「第几次」的依据)"),
    ("被判包裹没传进工具服务的 env", "被判包裹传进了每一个工具服务的 env"),
    ("产线入口不经开关直接判差评(研判提示词对差评不再拦)", "开关默认关:不带 开差评 → 照旧当场说「默认关闭」"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        bad.append(名)
    print(f"  {'✅' if ok else '❌'} {名}" + (f"  {str(附)[:160]}" if 附 and not ok else ""))


print("差评研判产线路 · 检查(不调模型;库只在临时副本上动)")
print("=" * 80)
tmp = tempfile.mkdtemp(prefix="ratetri-")
db = os.path.join(tmp, "lanxiu.db")
shutil.copy(os.path.join(ROOT, "backend", "lanxiu.db"), db)
import api, ops, oplog, rating as RT
api.DB = ops.DB = oplog.DB = db
c = sqlite3.connect(db); c.row_factory = sqlite3.Row

# ── ① 开关 ──────────────────────────────────────────────────────────
评 = c.execute("SELECT pkg_id, order_id, customer_id FROM rating WHERE star<=3 ORDER BY pkg_id LIMIT 1").fetchone()
ck("库里有差评可拿来造形状(空集合上什么都成立)", bool(评))
if 评:
    try:
        ops.研判提示词("评价差评", 评["pkg_id"], "T-检查"); 关着 = False; 话 = ""
    except ValueError as e:
        关着, 话 = True, str(e)
    ck("开关默认关:不带 开差评 → 照旧当场说「默认关闭」", 关着 and "默认关闭" in 话, 话)
    bp, case, 提示 = ops.研判提示词("评价差评", 评["pkg_id"], "T-检查", 开差评=True)
    ck("显式打开 → 进差评分支,要模型自己调 service_records 取材料",
       bp == "BP-差评" and case == 评["pkg_id"] and "service_records" in 提示, 提示[:120])
    ck("提示词里的处理方式从 rating.处理方式 现拼(每一档都在,不手抄)",
       all(x in 提示 for x in RT.处理方式), [x for x in RT.处理方式 if x not in 提示])
app_src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ck("产线入口(app.py 批量研判)没有打开开关", "开差评" not in app_src and "rating_triage" not in app_src)

# ── ② 遮蔽:副本上给同一个客户摆两条已处置的差评 ──────────────────────
if 评:
    被判, 别的 = 评["pkg_id"], "CHK-PKG-同客户另一条"
    c.execute("UPDATE rating SET handle_way='送保养', handle_note='检查造的处置' WHERE pkg_id=?", (被判,))
    cols = [r[1] for r in c.execute("PRAGMA table_info(rating)")]
    行 = dict(c.execute("SELECT * FROM rating WHERE pkg_id=?", (被判,)).fetchone())
    行.update(pkg_id=别的, handle_way="全额退款", handle_note="另一条的处置")
    c.execute(f"INSERT INTO rating({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [行[k] for k in cols])
    c.commit()
    店长 = c.execute("SELECT no, name, role, shop FROM staff WHERE role='店长' AND status='启用' "
                   "AND shop=(SELECT shop FROM customer WHERE id=?) LIMIT 1", (评["customer_id"],)).fetchone() \
        or c.execute("SELECT no, name, role, shop FROM staff WHERE role='售后' AND status='启用' LIMIT 1").fetchone()
    ck("有一个能看服务记录的员工(店长 / 售后)", bool(店长))
    import protocol
    srv = protocol.Server("chk", "0", [("service_records", "", {}, api.service_records)])

    def 调(被判包裹):
        if 被判包裹: os.environ["LANXIU_JUDGING_PKG"] = 被判包裹
        else: os.environ.pop("LANXIU_JUDGING_PKG", None)
        with api.as_user(dict(店长)):
            r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "service_records", "arguments": {"pkg": 被判}}})
        os.environ.pop("LANXIU_JUDGING_PKG", None)
        return json.loads(r["result"]["content"][0]["text"])

    def 找(x, pkg):
        """在返回里找带这个包裹号的评价行(不管它嵌在哪一层)。"""
        out = []
        if isinstance(x, dict):
            if pkg in (str(x.get("pkg_id")), str(x.get("包裹")), str(x.get("pkg"))) and \
                    any(k in x for k in ("handle_way", "处理方式")):
                out.append(x)
            for v in x.values(): out += 找(v, pkg)
        elif isinstance(x, list):
            for v in x: out += 找(v, pkg)
        return out

    def 处置(行们):
        return [r.get("handle_way", r.get("处理方式")) for r in 行们]

    if 店长:
        全 = 调(None)
        ck("不设被判包裹:被判那条的人工处置照给(人在后台复核要看全)",
           "送保养" in 处置(找(全, 被判)), 处置(找(全, 被判)) or str(全)[:160])
        ck("取材料样本:返回里看得到同一客户的另一条差评(否则下一条验不到)", bool(找(全, 别的)), str(全)[:160])
        遮 = 调(被判)
        ck("工具层:被判那条的人工处置抹成 None", 找(遮, 被判) and all(v is None for v in 处置(找(遮, 被判))),
           找(遮, 被判))
        ck("工具层:同一客户的另一条差评原样给(那是「第几次」的依据)", "全额退款" in 处置(找(遮, 别的)),
           找(遮, 别的))
        ck("遮的是值不是键(上线那天新差评的形状:键在、值是空)",
           找(遮, 被判) and all("handle_way" in r or "处理方式" in r for r in 找(遮, 被判)))

# ── ③ env 传到每一个工具服务 ─────────────────────────────────────────
import sdk
有 = sdk.mcp_config({"no": "X", "role": "店长"}, None, 被判包裹="P-检查")
无 = sdk.mcp_config({"no": "X", "role": "店长"}, None)
ck("被判包裹传进了每一个工具服务的 env", 有 and all(v["env"].get("LANXIU_JUDGING_PKG") == "P-检查" for v in 有.values()),
   {k: v["env"].get("LANXIU_JUDGING_PKG") for k, v in 有.items()})
_带 = sdk.mcp_config({"no": "X", "role": "店长"}, None, trace="T-检查")
ck("trace_id 真的进了每一个工具服务的 env(supervise_check 只能验结构,行为在这儿验)",
   _带 and all(v["env"].get("LANXIU_TRACE") == "T-检查" for v in _带.values()))
ck("不给被判包裹 → 哪个服务的 env 里都没有(聊天、复核不遮)",
   all("LANXIU_JUDGING_PKG" not in v["env"] for v in 无.values()))

# ── ④ 落库记版本 + 调没调取材料的工具 ─────────────────────────────────
import rating_triage as RTR
ck("轨迹里调过 service_records → 认作取了材料",
   RTR.取了材料吗([{"tool": "mcp__shop__bad_ratings"}, {"tool": "mcp__shop__service_records"}]))
ck("只调了别的工具 → 认作没取材料(不是「有工具调用就算」)",
   not RTR.取了材料吗([{"tool": "mcp__shop__bad_ratings"}, {"tool": "mcp__kb__kb_tables"}]))
def _拒了(f):
    try:
        f(); return False
    except PermissionError:
        return True


ck("没身份不跑(service_records 没身份取不到材料,跑了只会得到一条没材料的建议)",
   _拒了(lambda: RTR.跑一条("T", "P", None)))
if 评:
    t = c.execute("SELECT id FROM task WHERE type='评价差评' ORDER BY id LIMIT 1").fetchone()
    if t:
        版 = RTR.版本记([{"tool": "mcp__shop__service_records"}])
        tid = ops.save_triage(t["id"], "BP-差评", 评["pkg_id"], "根因:检查\n建议动作:送保养", [], prompt_ver=版)
        存 = c.execute("SELECT prompt_ver FROM triage WHERE id=?", (tid,)).fetchone()
        ck("落库记下哪版提示词 + 这一轮调没调 service_records",
           存 and ops.差评研判版本 in (存[0] or "") and "调了" in 存[0], 存 and 存[0])
c.close()
shutil.rmtree(tmp, ignore_errors=True)

print()
if bad:
    print(f"{R}❌ {len(bad)} 条不过(验了 {n} 条){D}")
    sys.exit(1)
print(f"{G}✅ 差评研判产线路:接通、默认关、只遮被判那一条(验了 {n} 条){D}")
