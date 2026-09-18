#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布《澜绣云裳agent-产品说明》到飞书,并把三张图**真画进画板**。

顺序不能反:发布脚本每次是**新建文档**再清同名旧版,
所以画板必须在发布之后画 —— 先画会被下一次发布连同文档一起换掉。

坐标是手写的。理由见 tools/feishu_board.py 顶部那段:
自动布局第一版把判定框和它的拒绝框排到同一行两端,线全部 45° 斜穿,
**而节点数量核对是全对的** —— 数量对上和画出来是对的,是两件事。
"""
import importlib.util, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
_s = importlib.util.spec_from_file_location("fb", ROOT / "tools/feishu_board.py")
fb = importlib.util.module_from_spec(_s); _s.loader.exec_module(fb)
API, fp = fb.API, fb.fp

标记 = ["【图一】Agent 四层架构", "【图二】写的闸", "【图三】数据信息流转"]

def N(key, text, x, y, w, h, shape="round_rect", 色=None):
    return dict(key=key, text=text, x=x, y=y, w=w, h=h, shape=shape, 色=色)
def E(a, b, 标=None, 起="bottom", 止="top"):
    return dict(a=a, b=b, 标=标, 起=起, 止=止)
def R(a, b, 标=None):   # 往右边甩的分支
    return dict(a=a, b=b, 标=标, 起="right", 止="left")

图 = [
  # ── 图一:四层架构 —— 模型分三路,工具那一路往下穿到库 ──────────────
  dict(节点=[
      N("m",  "模型\n(会说话)",                       380,   0, 300,  90),
      N("t",  "工具\n59 个 · 三个服务",                 40, 200, 300, 100),
      N("r",  "规矩\n49 条 · 按角色装配",              380, 200, 300, 100),
      N("g",  "闸\n读 / 写 / 答 三层",                 720, 200, 300, 100),
      N("k",  "口径模块 27 个\n规矩写在这里,不在工具里",  40, 400, 300, 110, 色="源"),
      N("db", "数据库 68 张表",                        40, 620, 300,  90, "rect", 色="库"),
  ], 边=[E("m","t"), E("m","r"), E("m","g"), E("t","k"), E("k","db")]),

  # ── 图二:写的闸 —— 主链一条直线,拒绝一律甩到右边 ──────────────────
  dict(节点=[
      N("a",  "模型想写",                              300,    0, 320,  80),
      N("b",  "① 是 9 个写工具之一?",                  300,  160, 380, 150, "diamond", 色="判"),
      N("x1", "拒",                                    820,  195, 200,  80, 色="拒"),
      N("c",  "② 预演一遍\n换成这个角色,允不允许?",     300,  400, 380, 160, "diamond", 色="判"),
      N("x2", "拒\n并说清缺什么",                       820,  440, 240,  90, 色="拒"),
      N("d",  "③ 四道行为闸\n连着写 / 同参数再试\n已成功过 / 试了三次", 300, 650, 420, 190, "diamond", 色="判"),
      N("x3", "拦",                                    820,  685, 200,  80, 色="拒"),
      N("e",  "④ 落库",                                300,  890, 320,  80, 色="过"),
      N("f",  "同时记一条操作日志\n谁·何时·改了什么·允不允许·为什么",
                                                       300, 1040, 380, 110, 色="记"),
  ], 边=[
      E("a","b"),
      R("b","x1","否"), E("b","c","是"),
      R("c","x2","不允许"), E("c","d","允许"),
      R("d","x3","踩中任一道"),
      E("d","e","四道都没踩"),
      E("e","f"),
  ]),

  # ── 图三:数据流转 —— 一条主链,写那一路从右边绕回库 ──────────────
  dict(节点=[
      N("md", "知识来源\n手写口径 13 份 md",            300,    0, 340, 100, 色="源"),
      N("dv", "推导\n把人写的规则变成机器能查的表",      300,  210, 340, 100),
      N("db", "数据库 68 张表\n四大主数据库 + 运营数据",  300,  420, 340, 100, "rect", 色="库"),
      N("kj", "口径模块 27 个",                        300,  630, 340,  80),
      N("mc", "MCP\nkb 11 · shop 43 · task 5",         300,  790, 340,  90),
      N("lm", "模型",                                  300,  950, 340,  80),
      N("w",  "写工具 9 个",                           820,  950, 240,  80),
      N("gd", "22 项回答体检",                         300, 1110, 340, 140, "diamond", 色="判"),
      N("re", "退回重答",                              820, 1140, 220,  80, 色="拒"),
      N("u",  "用户",                                  300, 1330, 340,  80, 色="过"),
      N("tr", "每轮落一条痕迹\n角色·问什么·调了几个工具\n走没走写路径·被拦几次",
                                                       300, 1480, 380, 120, 色="记"),
  ], 边=[
      E("md","dv","① 知识生成链:单向,永不回写"),
      E("dv","db"),
      E("db","kj","② 读:只读连接 + 三把锁"),
      E("kj","mc"), E("mc","lm"),
      E("lm","gd","③ 一次问答"),
      E("gd","u","过"), R("gd","re","拦下"),
      R("lm","w","④ 写"),
      dict(a="w", b="db", 标="落库", 起="top", 止="right"),
      E("u","tr"),
  ]),
]


def 做飞书版():
    """把 mermaid 代码块换成一行占位 —— 飞书不认 mermaid,留着只会变成代码块。"""
    src = (ROOT / "澜绣云裳agent-产品说明.md").read_text(encoding="utf-8")
    块 = re.findall(r"```mermaid\n.*?\n```", src, re.S)
    if len(块) != 3:
        sys.exit(f"❌ 预期 3 张图,源文件里有 {len(块)} 个 mermaid 块")
    for b, mk in zip(块, 标记):
        src = src.replace(b, mk, 1)
    out = pathlib.Path("/tmp/澜绣云裳agent-产品说明.md")
    out.write_text(src, encoding="utf-8")
    return out


def 找标记(tok, doc):
    d = fb._call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{doc}")
    kids = ((d.get("data") or {}).get("block") or {}).get("children") or []
    位 = {}
    for i, bid in enumerate(kids):
        r = fb._call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{bid}")
        blk = (r.get("data") or {}).get("block") or {}
        txt = "".join(e.get("text_run", {}).get("content", "")
                      for e in (blk.get("text") or {}).get("elements", []))
        for mk in 标记:
            if mk in txt:
                位[mk] = i
    return 位


def main():
    md = 做飞书版()
    print("① 发布(mermaid 换成占位段)")
    r = subprocess.run([sys.executable, "tools/feishu_publish.py", str(md)],
                       capture_output=True, text=True,
                       env={**os.environ, "FEISHU_FOLDER": "QexpfF7ejlotM8db6JEcZH5tnZf"})
    print("   " + "\n   ".join(r.stdout.strip().split("\n")[-3:]))
    mu = re.search(r"/docx/(\w+)", r.stdout)
    if not mu:
        sys.exit("❌ 没从发布输出里拿到文档 id")
    doc = mu.group(1)

    tok = fp.acquire_token()
    print("\n② 找占位段")
    位 = 找标记(tok, doc)
    for mk in 标记:
        print(f"   {mk}: {'第 '+str(位[mk])+' 个子块' if mk in 位 else '❌ 没找到'}")
    if len(位) != 3:
        sys.exit("❌ 占位段没找齐,停手 —— 插错位置比不插更糟")

    print("\n③ 插画板并画(从后往前,否则前面插完后面的序号全变了)")
    出图 = []
    for mk, g in sorted(zip(标记, 图), key=lambda x: -位[x[0]]):
        blk, wid = fb.建画板(tok, doc, index=位[mk] + 1)
        n, e = fb.画(tok, wid, g["节点"], g["边"])
        回 = fb.读回(tok, wid)
        ok = len(回) == n + e
        print(f"   {mk}:图形 {n} / 连线 {e} / 读回 {len(回)} {'✅' if ok else '❌ 对不上'}")
        出图.append((mk, wid))

    out = pathlib.Path(os.environ.get("BOARD_IMG_DIR", "/tmp"))
    print("\n④ 导出图片 —— **画完必须看一眼**,返回 0 只说明它收下了")
    for i, (mk, wid) in enumerate(reversed(出图), 1):
        p = fb.导出图片(tok, wid, out / f"board{i}.jpg")
        print(f"   {mk} → {p}({p.stat().st_size} 字节)")

    print(f"\n✅ https://aqvi2xbk5kd.feishu.cn/docx/{doc}")


if __name__ == "__main__":
    main()
