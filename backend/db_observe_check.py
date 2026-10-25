# -*- coding: utf-8 -*-
"""这一次工具调用实际读了哪些库表 · 观测 + 对位(证据中心第五个工作包,用户 10-25 拍「实际记录每次查询」)。

真调 backend/db_observe.py(装上 / 一次调用 / 读 / 参数指纹),在临时库和真业务工具上各跑一次;
聊天页的 库表对位 从 station.html 原样抠出来用 node 跑。观测日志写临时文件,不碰真日志。
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import contextvars

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db_observe as O

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, 数 = [], [0]

咬合 = [
    ("授权回调不记 SQLITE_READ(只数语句)", "联表查询读到的两张表、用到的列都记下了"),
    ("证据面板库表按先后对、不看参数指纹", "两次调用顺序和观测顺序不一样:按参数指纹各对各的"),
    ("连接照旧缓存准备好的语句", "同一个连接第二次跑同样的查询,读的表照样记全(不被语句缓存吃掉)"),
]


def ck(名, ok, 附=""):
    数[0] += 1
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def main():
    print("库表观测 · 这一次工具调用实际读了哪些表")
    O.装上()
    d = tempfile.mkdtemp()
    日志 = os.path.join(d, "db.jsonl")
    库 = os.path.join(d, "t.db")
    c = sqlite3.connect(库)
    c.executescript("CREATE TABLE customer(id TEXT, name TEXT, phone TEXT); CREATE TABLE ordr(id TEXT, customer_id TEXT, amt REAL);"
                    "INSERT INTO customer(id,name,phone) VALUES('C1','甲','13812345678'); INSERT INTO ordr(id,customer_id,amt) VALUES('O1','C1',9);")
    c.commit(); c.close()
    with O.一次调用("mcp__crm__get_customer", {"customer": "C1"}, trace="TQ", 路径=日志):
        c = sqlite3.connect(库)
        行 = c.execute("SELECT c.name, o.amt FROM customer c JOIN ordr o ON o.customer_id=c.id WHERE c.phone=?",
                      ("13812345678",)).fetchall()
        c.close()
    外 = sqlite3.connect(库); 外.execute("SELECT id FROM ordr").fetchall(); 外.close()
    记 = O.读("TQ", 日志)
    读了 = (记[0].get("读了") or {}).get("t.db", {}) if 记 else {}
    ck("联表查询读到的两张表、用到的列都记下了", set(读了) == {"customer", "ordr"} and {"name", "phone", "id"} <= set(读了.get("customer", []))
       and {"amt", "customer_id"} <= set(读了.get("ordr", [])), 读了)
    ck("观测不改查询结果", 行 == [("甲", 9.0)], 行)
    ck("只记一次调用里面的读;外面那条不算进去", len(记) == 1 and 记[0]["语句数"] >= 1, 记)
    ck("**不记 SQL 参数值**(那里面是客户资料)", "13812345678" not in open(日志, encoding="utf-8").read())
    # 线程:复制上下文跑才记得到(协议层的超时线程就是这么跑的)
    with O.一次调用("get_order", {"o": 1}, trace="TT", 路径=日志):
        def 跑():
            cc = sqlite3.connect(库); cc.execute("SELECT amt FROM ordr").fetchall(); cc.close()
        th = threading.Thread(target=contextvars.copy_context().run, args=(跑,)); th.start(); th.join()
    ck("在复制的上下文里开的线程,读的表也记得到", "ordr" in ((O.读("TT", 日志) or [{}])[0].get("读了") or {}).get("t.db", {}))
    # 真业务工具:促活名单查一个客户
    import api
    真 = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
    cid = 真.execute("SELECT id FROM customer LIMIT 1").fetchone()[0]; 真.close()
    with O.一次调用("revive_list", {"customer": cid}, trace="TR", 路径=日志):
        with api.as_user({"no": "60000008", "name": "x", "role": "总部运营", "shop": None}):
            api.revive_list(customer=cid)
    真读 = set(((O.读("TR", 日志) or [{}])[0].get("读了") or {}).get("lanxiu.db", {}))
    ck("真工具(促活查一个客户)记到它实际读的表:customer、ordr、followup …", {"customer", "ordr", "followup"} <= 真读, sorted(真读))
    with O.一次调用("revive_list", {"customer": cid}, trace="TR2", 路径=日志):
        with api.as_user({"no": "60000008", "name": "x", "role": "总部运营", "shop": None}):
            api.revive_list(customer=cid)
    再读 = set(((O.读("TR2", 日志) or [{}])[0].get("读了") or {}).get("lanxiu.db", {}))
    # 不比「两次一模一样」:第二次真的不读 world_meta(「今天」在内存里缓存了)—— 比的是每个客户都要查的那几张
    ck("同一个连接第二次跑同样的查询,读的表照样记全(不被语句缓存吃掉)",
       {"customer", "ordr", "followup", "aftersale", "maintain"} <= 再读, (sorted(真读), sorted(再读)))
    ck("参数指纹:键的先后、服务前缀不影响;参数不同就不同",
       O.参数指纹("mcp__a__x", {"a": 1, "b": 2}) == O.参数指纹("x", {"b": 2, "a": 1}) != O.参数指纹("x", {"a": 1, "b": 3}))
    # 聊天页的对位(node 真跑)
    src = open(os.path.join(os.path.dirname(HERE), "agentsite", "web", "station.html"), encoding="utf-8").read()
    m = re.search(r"function 库表对位\(spans, 库表\)\{.*?\n\}", src, re.S)
    if not m:
        ck("station.html 里找得到 库表对位", False); return 1
    sp = lambda fp: {"attr": {"gen_ai.tool.name": "get_order", "lanxiu.args_fp": fp}}
    观测 = [{"工具": "mcp__x__get_order", "参数指纹": "B", "读了": {"x": {"b": []}}},
            {"工具": "get_order", "参数指纹": "A", "读了": {"x": {"a": []}}}]
    js = m.group(0) + f"\nconsole.log(JSON.stringify(库表对位({json.dumps([sp('A'), sp('B'), {'attr': {}}])}, {json.dumps(观测)})));"
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    out = json.loads(r.stdout) if r.returncode == 0 else None
    ck("两次调用顺序和观测顺序不一样:按参数指纹各对各的", out and list(out[0]["读了"]["x"]) == ["a"] and list(out[1]["读了"]["x"]) == ["b"], (out, r.stderr[-200:]))
    ck("没有指纹的那一步 → 对不上就是对不上(null),不拿别人的顶上", out and out[2] is None, out)
    # 接线
    根 = os.path.dirname(HERE)
    proto = open(os.path.join(根, "mcp", "protocol.py"), encoding="utf-8").read()
    sdk = open(os.path.join(根, "agentsite", "sdk.py"), encoding="utf-8").read()
    ck("工具服务:启动装上观测,每次调用包在 一次调用 里,超时线程复制上下文",
       "_dbo.装上()" in proto and "self._观测.一次调用(nm, args)" in proto and "copy_context().run" in proto)
    ck("聊天站:工具调用打上同一个参数指纹", '_dbo.参数指纹(getattr(b, "name", ""), getattr(b, "input", {}))' in sdk)
    ig = open(os.path.join(根, ".gitignore"), encoding="utf-8").read()
    ck("观测日志在 .gitignore 里", ".feynman/db-access.jsonl" in ig)
    print()
    if 坏:
        print(f"{R}❌ 库表观测 {len(坏)} 条不过(验了 {数[0]} 条){D}")
        return 1
    print(f"{G}✅ 库表观测:联表读到的表和列都在、不记参数值、真工具记得到、按参数指纹对位(验了 {数[0]} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
