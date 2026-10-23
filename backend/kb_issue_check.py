# -*- coding: utf-8 -*-
"""知识问题处理入口(外部复审第 4 节 E,10-23):零命中也有编号、谁能改什么、改动留痕、复验不说「答对了」。

**在库副本上打 HTTP 层**(server.do_POST / do_GET,假 handler):身份只从登录会话来,请求体里自报的不认。
零命中那一支**真调 api.kb_rag**,只把它发给管理后台(8801)的那次 curl 换成自造的回包 ——
不依赖 8801 起没起(起没起是环境,不是代码)。复验同理:真调 tools/kb_recheck.跑,检索口换成自造的三种形状。

用法:./agentsite/.venv/bin/python backend/kb_issue_check.py   (不调模型;写的是库副本)
"""
import datetime as _dt, io, json, os, re, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
# ⚠️ 写口模块**先 import 再切库** —— 用副本只改已经加载的模块;之后才 import 的会写真库
import kb_issue as KI, server, auth, oplog, api, ops   # noqa: F401
sys.path.append(os.path.join(ROOT, "tools"))
import kb_recheck as RC
sys.path.append(os.path.join(ROOT, "agentsite"))
import check_copy
副本 = check_copy.用副本("kb-issue-")

G, Rd, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("零命中那一支又把试跑id 丢了", "零命中也带回记录编号(真调 kb_rag,管理后台回包零选片)"),
    ("改状态不查角色(谁都能改)", "顾问改状态:拒"),
    ("提问题类型不查是不是本人", "别人的检索记录:报不了类型"),
    ("指定维护人不留痕", "指定维护人留痕(带理由和署名)"),
    ("复验声明改成「就是答对了」", "复验输出写明「找到片段不等于答对」"),
    ("修订版本不校验形状(整串日期也收)", "修订版本整串是日期:拒写"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else Rd+'❌'+D} {名}{'  ' + str(细)[:200] if 细 else ''}")


class 假请求:
    def __init__(self, path, body=None, tok=None):
        self.path = path
        self._b = json.dumps(body or {}, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._b))}
        if tok: self.headers["cookie"] = f"lx_token={tok}"
        self.rfile, self.wfile = io.BytesIO(self._b), io.BytesIO()
    def send_response(self, *a): pass
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def _打(方法, path, body=None, tok=None):
    h = 假请求(path, body, tok); 回 = {}
    def _send(obj, code=200): 回.update(码=code, 体=obj)
    h._send = _send
    (server.H.do_POST if 方法 == "POST" else server.H.do_GET)(h)
    return 回.get("码"), 回.get("体") or {}


打 = lambda path, body, tok=None: _打("POST", path, body, tok)
读 = lambda path, tok=None: _打("GET", path, None, tok)


def 会话(role, 第几=0):
    r = server.rows("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no", role)
    if len(r) <= 第几: return None, None
    tok = f"kb-issue-{role}-{第几}"
    with auth._LOCK: auth._SESS[tok] = dict(r[第几], at=_dt.datetime.now())
    return tok, dict(r[第几])


def 假后台(回包):
    """把 kb_rag 发给管理后台的那次 curl 换成自造回包 —— kb_rag 本身照真跑。"""
    真 = api.subprocess
    假 = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout=json.dumps(回包, ensure_ascii=False), stderr=""))
    api.subprocess = 假
    return lambda: setattr(api, "subprocess", 真)


def main():
    print("\n\033[1m▸ 知识问题处理入口 · 库副本上打 HTTP 层\033[0m")
    if os.path.realpath(KI.DB) != os.path.realpath(副本) or os.path.realpath(oplog.DB) != os.path.realpath(副本):
        print(f"  {Rd}❌ 写口没切到副本(KI.DB={KI.DB} oplog.DB={oplog.DB})—— 不跑,免得写真库{D}"); return 1
    tH, 总部 = 会话("总部运营"); tG, 顾问 = 会话("顾问"); tG2, 顾问2 = 会话("顾问", 1)
    if not (tH and tG and tG2):
        print(f"  {Rd}❌ 库里找不到在职的总部运营 / 两个顾问 —— 没东西可验{D}"); return 1
    import sqlite3
    with sqlite3.connect(副本) as c:
        KI.确保表(c)
        for t in ("kb_rag_record", "kb_rag_record_log", "kb_recheck"):
            c.execute(f"DELETE FROM {t}")

    # ① 零命中也有编号 —— 真调 kb_rag
    还原 = 假后台({"试跑id": "rr_chk_zero", "选片": [], "知识库": "检查库", "改写": None})
    try:
        零 = api.kb_rag("一个知识库里没有的问题")
    finally:
        还原()
    ck("零命中也带回记录编号(真调 kb_rag,管理后台回包零选片)",
       零.get("hit") == 0 and 零.get("试跑id") == "rr_chk_zero", 零)
    还原 = 假后台({"试跑id": "rr_chk_hit", "选片": [{"证据": "第 9 篇 / 二、几星算差评 · 第 4 段", "文": "……", "分数": 0.9}],
                 "知识库": "检查库", "改写": "几星算差评"})
    try:
        中 = api.kb_rag("几星算差评")
    finally:
        还原()
    ck("命中那一支照旧带编号和出处", 中.get("hit") == 1 and 中.get("试跑id") == "rr_chk_hit", 中.get("试跑id"))

    # ② 轨迹 → 门店检索记录(智能运维平台那一段真跑,转发换成直接打后台的 do_POST)
    try:
        import app as 站
        站._post_回体 = lambda path, payload, cookie=None: 打(path, payload, cookie.split("=", 1)[1] if cookie else None)[1]
        轮 = {"trajectory": [{"tool": "mcp__knowledge__kb_rag", "result": 零},
                             {"tool": "mcp__knowledge__kb_rag", "result": 中},
                             {"tool": "mcp__knowledge__kb_rag", "result": {"error": "连不上管理后台", "怎么办": "照实说"}}]}
        ck("轨迹里零命中那条也挑得出来(不按 hit 过滤),查不了的那条不算",
           [x["试跑id"] for x in 站.知识检索记录们(轮)] == ["rr_chk_zero", "rr_chk_hit"], 站.知识检索记录们(轮))
        站._记知识检索(轮, f"lx_token={tG}")
    except ImportError as e:
        ck("轨迹里零命中那条也挑得出来(不按 hit 过滤),查不了的那条不算", False, f"app 导不进来:{e} —— 要用 venv 的 python 跑")
    with sqlite3.connect(副本) as c:
        c.row_factory = sqlite3.Row
        行 = {x["run_id"]: dict(x) for x in c.execute("SELECT * FROM kb_rag_record")}
    ck("零命中那条进了门店检索记录,提问人是登录的那个顾问",
       行.get("rr_chk_zero", {}).get("asker_no") == 顾问["no"] and 行["rr_chk_zero"]["hit"] == 0, 行.get("rr_chk_zero"))
    码, 体 = 打("/api/kb-rag-record", {"op": "记录", "记录们": [{"试跑id": "rr_chk_zero", "问的是": "改写别人的", "hit": 3}]}, tG2)
    ck("同一个编号别人再记一次:不改写原记录(提问人、问题都不变)",
       KI.详情("rr_chk_zero", 总部)["记录"]["question"] == "一个知识库里没有的问题"
       and KI.详情("rr_chk_zero", 总部)["记录"]["asker_no"] == 顾问["no"], 体)
    码, 体 = 打("/api/kb-rag-record", {"op": "记录", "记录们": []})
    ck("没登录记检索:拒(401)", 码 == 401, 码)

    # ③ 员工提问题类型
    码, 体 = 打("/api/kb-issue-type", {"试跑id": "rr_chk_zero", "类型": "答不上", "说明": "x"})
    ck("没登录报类型:拒(401)", 码 == 401, 码)
    码, 体 = 打("/api/kb-issue-type", {"试跑id": "rr_chk_zero", "类型": "答不上", "说明": "问差评几星,知识库没有"}, tG2)
    ck("别人的检索记录:报不了类型", not 体.get("ok") and "不是你问的" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-type", {"试跑id": "rr_chk_zero", "类型": "瞎填", "说明": "x"}, tG)
    ck("类型只能是那五种", not 体.get("ok"), 体)
    码, 体 = 打("/api/kb-issue-type", {"试跑id": "rr_chk_zero", "类型": "答不上", "说明": ""}, tG)
    ck("报类型不写说明:拒", not 体.get("ok") and "说明" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-type", {"试跑id": "rr_chk_zero", "类型": "答不上", "说明": "问差评几星,知识库没有"}, tG)
    ck("提问人本人报「答不上」:成,进待处理", 体.get("ok") and 体.get("状态") == "待处理", 体)

    # ④ 维护人 / 状态:只有总部运营
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_zero", "维护人工号": 顾问["no"], "理由": "我来"}, tG)
    ck("顾问(哪怕是提问人本人)指定维护人:拒", not 体.get("ok") and "总部运营" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_zero", "维护人工号": 顾问["no"], "理由": "我来", "role": "总部运营"}, tG)
    ck("请求体里自报「总部运营」不认", not 体.get("ok"), 体)
    码, 体 = 打("/api/kb-issue-status", {"试跑id": "rr_chk_zero", "到": "不处理", "理由": "不想处理"}, tG)
    ck("顾问改状态:拒", not 体.get("ok") and "总部运营" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-status", {"试跑id": "rr_chk_zero", "到": "处理中", "理由": "开始改"}, tH)
    ck("没指定维护人不能改成处理中(没人认领的待办)", not 体.get("ok") and "维护人" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_zero", "维护人工号": 总部["no"], "理由": ""}, tH)
    ck("指定维护人不写理由:拒", not 体.get("ok") and "理由" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_zero", "维护人工号": "NOBODY", "理由": "x"}, tH)
    ck("维护人要是在职员工", not 体.get("ok"), 体)
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_zero", "维护人工号": 总部["no"], "理由": "差评口径归总部"}, tH)
    ck("总部运营指定维护人:成", 体.get("ok"), 体)
    码, 体 = 打("/api/kb-issue-assign", {"试跑id": "rr_chk_hit", "维护人工号": 总部["no"], "理由": "x"}, tH)
    ck("没人报过类型的检索记录不能指定维护人(那还不是一条问题)", not 体.get("ok"), 体)
    码, 体 = 打("/api/kb-issue-status", {"试跑id": "rr_chk_zero", "到": "已修订", "理由": "改完了"}, tH)
    ck("改成已修订不写修订版本 / 说明:拒", not 体.get("ok") and "修订" in (体.get("reason") or ""), 体)
    码, 体 = 打("/api/kb-issue-status", {"试跑id": "rr_chk_zero", "到": "已修订", "理由": "补了几星算差评那节",
                                     "修订版本": "业务拍板 2026-10-23 版", "修订说明": "第 9 篇二节补一段"}, tH)
    ck("总部运营改成已修订(带版本):成", 体.get("ok") and 体.get("到") == "已修订", 体)

    # ⑤ 留痕
    d = KI.详情("rr_chk_zero", 总部)
    日 = d["日志"]
    ck("指定维护人留痕(带理由和署名)",
       any(x["what"] == "维护人" and x["why"] == "差评口径归总部" and x["by_name"] == 总部["name"] for x in 日), 日[:3])
    ck("改状态留痕(带理由和署名),修订版本单独一条",
       any(x["what"] == "状态" and x["after"] == "已修订" and x["why"] and x["by_name"] == 总部["name"] for x in 日)
       and any(x["what"] == "修订版本" for x in 日), [x["what"] for x in 日])
    ck("报类型留痕(说明就是理由)", any(x["what"] == "问题类型" and x["why"] and x["by_name"] == 顾问["name"] for x in 日))
    with sqlite3.connect(副本) as c:
        台 = c.execute("SELECT count(*) FROM op_log WHERE machine='kb_issue'").fetchone()[0]
    ck("写口成功 / 被拒都进操作日志", 台 >= 8, f"{台} 条")

    # ⑥ 读接口身份
    码, 体 = 读("/api/kb-issues")
    ck("没登录看清单:拒(401)", 码 == 401, 码)
    打("/api/kb-rag-record", {"op": "记录", "记录们": [{"试跑id": "rr_chk_other", "问的是": "另一个顾问问的", "hit": 2,
                                                   "出处们": ["甲", "乙"]}]}, tG2)
    打("/api/kb-issue-type", {"试跑id": "rr_chk_other", "类型": "过期", "说明": "说法过时了"}, tG2)
    码, 体 = 读("/api/kb-issues?scope=全部", tG)
    ck("顾问看清单:只看得到自己问的", 码 == 200 and {x["run_id"] for x in 体["rows"]} == {"rr_chk_zero", "rr_chk_hit"},
       [x["run_id"] for x in 体.get("rows", [])])
    码, 体 = 读("/api/kb-issue/rr_chk_other", tG)
    ck("顾问翻别人的详情:拒(403)", 码 == 403, 码)
    码, 体 = 读("/api/kb-issues?status=" + "待处理", tH)
    ck("总部运营按状态筛:看得到别人报的", 码 == 200 and [x["run_id"] for x in 体["rows"]] == ["rr_chk_other"],
       [x["run_id"] for x in 体.get("rows", [])])
    码, 体 = 读("/api/kb-issues?type=" + "答不上", tH)
    ck("总部运营按类型筛", 码 == 200 and [x["run_id"] for x in 体["rows"]] == ["rr_chk_zero"])

    # ⑦ 复验:挑谁、结论怎么说
    打("/api/kb-rag-record", {"op": "评分", "试跑id": "rr_chk_other", "评分": 2}, tG2)
    打("/api/kb-rag-record", {"op": "记录", "记录们": [{"试跑id": "rr_chk_fine", "问的是": "好好的一次", "hit": 1,
                                                   "出处们": ["丙"]}]}, tG)
    打("/api/kb-rag-record", {"op": "评分", "试跑id": "rr_chk_fine", "评分": 3}, tG)
    挑 = {r["run_id"]: 为 for r, 为 in KI.复验对象()}
    ck("复验挑:已修订 / 低分(≤2) / 零命中;3 分且有命中的不挑",
       set(挑) == {"rr_chk_zero", "rr_chk_other"} and "已修订" in 挑["rr_chk_zero"] and "低分" in 挑["rr_chk_other"], 挑)
    def 假检索(问):
        if "没有" in 问:
            return {"hit": 1, "试跑id": "rr_new1", "证据们": [{"出处": "第 9 篇 / 二节 · 第 5 段"}]}
        raise RuntimeError("管理后台连不上")
    输出 = []
    结 = RC.跑(检索口=假检索, 打印=输出.append)
    文 = "\n".join(输出)
    ck("复验输出写明「找到片段不等于答对」", "不等于答对" in 文 and "不等于答对" in 结["声明"], 文[:120])
    ck("复验输出里凡提到「答对」的行,都是在说「不等于答对」(不许把命中了说成答对了)",
       all("不等于答对" in l for l in 输出 if "答对" in l), [l for l in 输出 if "答对" in l and "不等于答对" not in l])
    ck("复验结论只有三种说法,没有一种是「答对 / 改好」",
       all(x["结论"] in KI.复验结论们 for x in 结["结果们"])
       and not any(re.search("答对|答得对|改好", k) for k in KI.复验结论们), [x["结论"] for x in 结["结果们"]])
    按 = {x["编号"]: x for x in 结["结果们"]}
    ck("修订后找到了相关片段:前后对比存档(0 → 1 段,新出现的出处列出来)",
       按.get("rr_chk_zero", {}).get("结论") == "找到了相关片段" and 按["rr_chk_zero"]["新出现的出处"], 按.get("rr_chk_zero"))
    ck("查不了的记「复验没跑成」,不记成零命中", 按.get("rr_chk_other", {}).get("结论") == "复验没跑成"
       and 按["rr_chk_other"]["现在几段"] is None and not 按["rr_chk_other"]["不见了的出处"], 按.get("rr_chk_other"))
    ck("复验存档进了详情页(带声明)", len(KI.详情("rr_chk_zero", 总部)["复验"]) == 1
       and "不等于答对" in KI.详情("rr_chk_zero", 总部)["复验声明"])

    # ⑦半 修订版本不许整串是日期(会被每日平移当日期挪走;数据工厂 10-23 提醒)
    _r日 = KI.改状态("rr_chk_zero", "已修订", "检查", 总部, 修订版本="2026-10-23")
    ck("修订版本整串是日期:拒写(要点分隔)", not _r日.get("ok") and "整串是个日期" in (_r日.get("reason") or ""), _r日)

    # ⑧ 知识流向只许 md → 表:这一层不写知识 md、不写任何推导表
    自己的表 = {"kb_rag_record", "kb_rag_record_log", "kb_recheck"}
    写了的 = set()
    for f in (os.path.join(HERE, "kb_issue.py"), os.path.join(ROOT, "tools", "kb_recheck.py")):
        源 = open(f, encoding="utf-8").read()
        写了的 |= {m.group(2) for m in re.finditer(r"(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", 源, re.I)}
        写了的 |= {"open(…, 写)"} if re.search(r"open\([^)]*['\"][wa]['\"]", 源) else set()
    ck("知识问题这一层只写自己的三张表,不写知识 md、不写推导表(流向只许 md → 表)",
       写了的 and 写了的 <= 自己的表, sorted(写了的))

    with auth._LOCK:
        for t in (tH, tG, tG2): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{Rd}❌ 知识问题处理入口 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ 知识问题:零命中也有编号,员工能报类型、只有总部运营能定维护人和状态,改动留痕,复验不说「答对了」{D}")
    print("  ⚠️ 盲区:没真连管理后台(8801)—— 它零命中时是否真给试跑id 由那边的 test_knowledge_flow 管;"
          "复验找到的片段对不对得上问题,仍要人评")
    return 0


if __name__ == "__main__":
    sys.exit(main())
