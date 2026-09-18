#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把产品说明发到飞书,并把三张图**真画进画板**。

顺序不能反:发布脚本每次是**新建文档**再清同名旧版,
所以画板必须在发布之后画 —— 先画会被下一次发布连同文档一起换掉。
"""
import importlib.util, json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path.home() / "Desktop/澜绣云裳agent"
os.chdir(ROOT)
spec = importlib.util.spec_from_file_location("fb", ROOT / "tools/feishu_board.py")
fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
fp, API = fb.fp, fb.API

标记 = ["【图一】Agent 四层架构", "【图二】写的闸", "【图三】数据信息流转"]

# ── 三张图的节点与边 ───────────────────────────────────────────────
图 = [
 dict(nodes=[
   dict(key="m",  text="模型\n(会说话)"),
   dict(key="t",  text="工具\n59 个 · 三个服务"),
   dict(key="r",  text="规矩\n49 条 · 按角色装配"),
   dict(key="g",  text="闸\n读 / 写 / 答 三层"),
   dict(key="k",  text="口径模块 27 个\n规矩写在这里,不在工具里"),
   dict(key="db", text="数据库 68 张表", shape="rect"),
 ], edges=[("m","t"),("m","r"),("m","g"),("t","k"),("k","db")]),

 dict(nodes=[
   dict(key="a",  text="模型想写"),
   dict(key="b",  text="① 是 9 个写工具之一?", shape="diamond"),
   dict(key="x1", text="拒"),
   dict(key="c",  text="② 预演一遍\n换成这个角色,允不允许?", shape="diamond"),
   dict(key="x2", text="拒\n并说清缺什么"),
   dict(key="d",  text="③ 四道行为闸\n连着写好几条 / 同参数再试\n已成功过还写 / 试了三次没成", shape="diamond"),
   dict(key="x3", text="拦"),
   dict(key="e",  text="④ 落库"),
   dict(key="f",  text="同时记一条操作日志\n谁·何时·改了什么·允不允许·为什么"),
 ], edges=[("a","b"),("b","x1"),("b","c"),("c","x2"),("c","d"),
           ("d","x3"),("d","e"),("e","f")]),

 dict(nodes=[
   dict(key="md", text="知识来源\n手写口径 13 份 md"),
   dict(key="dv", text="推导\n把人写的规则变成机器能查的表"),
   dict(key="db", text="数据库 68 张表\n四大主数据库 + 运营数据", shape="rect"),
   dict(key="kj", text="口径模块 27 个"),
   dict(key="mc", text="MCP\nkb 11 · shop 43 · task 5"),
   dict(key="lm", text="模型"),
   dict(key="gd", text="22 项回答体检", shape="diamond"),
   dict(key="u",  text="用户"),
   dict(key="re", text="退回重答"),
   dict(key="w",  text="写工具 9 个"),
   dict(key="tr", text="每轮落一条痕迹\n角色·问什么·调了几个工具\n走没走写路径·被拦几次"),
 ], edges=[("md","dv"),("dv","db"),("db","kj"),("kj","mc"),("mc","lm"),
           ("lm","gd"),("gd","u"),("gd","re"),("lm","w"),("u","tr")]),
]


def 做飞书版():
    """把 mermaid 代码块换成一行占位 —— 飞书不认 mermaid,留着只会变成代码块。"""
    src = (ROOT / "澜绣云裳agent-产品说明.md").read_text(encoding="utf-8")
    块 = re.findall(r"```mermaid\n.*?\n```", src, re.S)
    assert len(块) == 3, f"预期 3 张图,实际 {len(块)}"
    for b, mk in zip(块, 标记):
        src = src.replace(b, mk, 1)
    out = pathlib.Path("/tmp/澜绣云裳agent-产品说明.md")
    out.write_text(src, encoding="utf-8")
    return out


def 找标记(tok, doc):
    """在文档里找占位段,返回 {标记: 它在根块子块中的序号}。"""
    d = fb._call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{doc}")
    kids = (((d.get("data") or {}).get("block")) or {}).get("children") or []
    位 = {}
    for i, bid in enumerate(kids):
        r = fb._call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{bid}")
        blk = (r.get("data") or {}).get("block") or {}
        txt = "".join(e.get("text_run", {}).get("content", "")
                      for e in (blk.get("text") or {}).get("elements", []))
        for mk in 标记:
            if mk and mk in txt:
                位[mk] = i
    return 位


def main():
    md = 做飞书版()
    print("① 发布(mermaid 换成占位段)")
    r = subprocess.run([sys.executable, "tools/feishu_publish.py", str(md)],
                       capture_output=True, text=True,
                       env={**os.environ, "FEISHU_FOLDER": "QexpfF7ejlotM8db6JEcZH5tnZf"})
    print("   " + "\n   ".join(l for l in r.stdout.strip().split("\n")[-3:]))
    mu = re.search(r"/docx/(\w+)", r.stdout)
    if not mu:
        sys.exit("❌ 没从发布输出里拿到文档 id")
    doc = mu.group(1)

    tok = fp.acquire_token()
    print("\n② 找占位段")
    位 = 找标记(tok, doc)
    for mk in 标记:
        print(f"   {mk}: {'第 ' + str(位[mk]) + ' 个子块' if mk in 位 else '❌ 没找到'}")
    if len(位) != 3:
        sys.exit("❌ 占位段没找齐,停手 —— 插错位置比不插更糟")

    print("\n③ 依次插画板并画(从后往前,否则前面插完后面的序号全变了)")
    for mk, g in sorted(zip(标记, 图), key=lambda x: -位[x[0]]):
        print(f"   {mk}")
        blk, wid = fb.建画板(tok, doc, index=位[mk] + 1)
        n, e = fb.画(tok, wid, g["nodes"], g["edges"])
        回 = fb.读回(tok, wid)
        ok = len(回) == n + e
        print(f"     图形 {n} / 连线 {e} / 读回 {len(回)}  {'✅' if ok else '❌ 对不上'}")

    print(f"\n✅ 完成:https://aqvi2xbk5kd.feishu.cn/docx/{doc}")


if __name__ == "__main__":
    main()
