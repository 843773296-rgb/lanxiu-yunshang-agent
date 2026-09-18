#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布《澜绣云裳agent-产品需求文档》到飞书，并把三张图画进画板。

和 publish_product_doc.py 同一套流程，区别只在：文档不同、图的文案是 PRD 口吻。
坐标复用，文案单列 —— 两份文档的图形状一样，说法不一样。
"""
import importlib.util, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
_s = importlib.util.spec_from_file_location("fb", ROOT / "tools/feishu_board.py")
fb = importlib.util.module_from_spec(_s); _s.loader.exec_module(fb)
API, fp = fb.API, fb.fp

标记 = ["【图一】系统协同架构", "【图二】写入控制机制", "【图三】数据流转地图"]

def N(key, text, x, y, w, h, shape="round_rect", 色=None):
    return dict(key=key, text=text, x=x, y=y, w=w, h=h, shape=shape, 色=色)
def E(a, b, 标=None, 起="bottom", 止="top"):
    return dict(a=a, b=b, 标=标, 起=起, 止=止)
def R(a, b, 标=None):
    return dict(a=a, b=b, 标=标, 起="right", 止="left")

图 = [
  dict(节点=[
      N("m",  "对话入口\n自然语言请求",                380,   0, 300,  90),
      N("t",  "工具服务层\n59 个 · 三个服务",            40, 200, 300, 100),
      N("r",  "业务规则\n49 条 · 按角色下发",           380, 200, 300, 100),
      N("g",  "控制层\n读 · 写 · 交付前",               720, 200, 300, 100),
      N("k",  "业务口径层\n27 个模块 · 判定规则集中于此",  40, 400, 300, 110, 色="源"),
      N("db", "数据层 68 张表",                        40, 620, 300,  90, "rect", 色="库"),
  ], 边=[E("m","t"), E("m","r"), E("m","g"), E("t","k"), E("k","db")]),

  dict(节点=[
      N("a",  "发起写入",                              300,    0, 320,  80),
      N("b",  "① 是否在写入白名单内",                   300,  160, 380, 150, "diamond", 色="判"),
      N("x1", "拒绝",                                  820,  195, 200,  80, 色="拒"),
      N("c",  "② 权限预演\n该角色是否被允许",            300,  400, 380, 160, "diamond", 色="判"),
      N("x2", "拒绝\n返回缺失项",                       820,  440, 240,  90, 色="拒"),
      N("d",  "③ 行为约束\n连续写入 / 重复参数重试\n已成功后再写 / 连续三次失败",
                                                       300,  650, 420, 190, "diamond", 色="判"),
      N("x3", "拦截",                                  860,  695, 200,  80, 色="拒"),
      N("e",  "④ 写入生效",                            300,  930, 320,  80, 色="过"),
      N("f",  "操作留痕\n操作人 · 时间 · 变更内容\n判定结果 · 理由",
                                                       300, 1080, 380, 110, 色="记"),
  ], 边=[
      E("a","b"), R("b","x1","否"), E("b","c","是"),
      R("c","x2","不允许"), E("c","d","允许"),
      R("d","x3","命中任一项"), E("d","e","全部通过"), E("e","f"),
  ]),

  dict(节点=[
      N("md", "知识内容\n人工维护 13 份",               300,    0, 340, 100, 色="源"),
      N("dv", "推导生成\n规则转为可查询数据表",          300,  210, 340, 100),
      N("db", "数据层 68 张表\n四类主数据 + 运营数据",    300,  420, 340, 100, "rect", 色="库"),
      N("kj", "业务口径层 27 个模块",                   300,  630, 340,  80),
      N("mc", "工具服务层\nkb 11 · shop 43 · task 5",   300,  790, 340,  90),
      N("lm", "对话入口",                              300,  950, 340,  80),
      N("w",  "写入工具 9 个",                          820,  950, 240,  80),
      N("gd", "交付前校验 22 项",                       300, 1110, 340, 140, "diamond", 色="判"),
      N("re", "退回重答",                              820, 1140, 220,  80, 色="拒"),
      N("u",  "员工",                                  300, 1330, 340,  80, 色="过"),
      N("tr", "每轮结构化记录\n角色 · 请求摘要 · 工具调用数\n是否写入 · 拦截次数",
                                                       300, 1480, 380, 120, 色="记"),
  ], 边=[
      E("md","dv","① 知识生成:单向,不反向写回"),
      E("dv","db"), E("db","kj","② 查询:只读连接 + 三项限制"),
      E("kj","mc"), E("mc","lm"),
      E("lm","gd","③ 答复"), E("gd","u","通过"), R("gd","re","未通过"),
      R("lm","w","④ 写入"),
      dict(a="w", b="db", 标="写入生效", 起="top", 止="right"),
      E("u","tr"),
  ]),
]


def 做飞书版():
    src = (ROOT / "澜绣云裳agent-产品需求文档.md").read_text(encoding="utf-8")
    块 = re.findall(r"```mermaid\n.*?\n```", src, re.S)
    if len(块) != 3:
        sys.exit(f"❌ 预期 3 张图，源文件里有 {len(块)} 个 mermaid 块")
    for b, mk in zip(块, 标记):
        src = src.replace(b, mk, 1)
    out = pathlib.Path("/tmp/澜绣云裳agent-产品需求文档.md")
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
    print("① 发布")
    r = subprocess.run([sys.executable, "tools/feishu_publish.py", str(md)],
                       capture_output=True, text=True,
                       env={**os.environ, "FEISHU_FOLDER": "QexpfF7ejlotM8db6JEcZH5tnZf"})
    print("   " + "\n   ".join(r.stdout.strip().split("\n")[-2:]))
    mu = re.search(r"/docx/(\w+)", r.stdout)
    if not mu:
        sys.exit("❌ 没拿到文档 id")
    doc = mu.group(1)

    tok = fp.acquire_token()
    print("\n② 找占位段")
    位 = 找标记(tok, doc)
    for mk in 标记:
        print(f"   {mk}: {'第 '+str(位[mk])+' 个子块' if mk in 位 else '❌ 没找到'}")
    if len(位) != 3:
        sys.exit("❌ 占位段没找齐，停手")

    print("\n③ 插画板并画（从后往前）")
    出图 = []
    for mk, g in sorted(zip(标记, 图), key=lambda x: -位[x[0]]):
        blk, wid = fb.建画板(tok, doc, index=位[mk] + 1)
        n, e = fb.画(tok, wid, g["节点"], g["边"])
        回 = fb.读回(tok, wid)
        print(f"   {mk}：图形 {n} / 连线 {e} / 读回 {len(回)} {'✅' if len(回)==n+e else '❌'}")
        出图.append((mk, wid))

    out = pathlib.Path(os.environ.get("BOARD_IMG_DIR", "/tmp"))
    print("\n④ 导出图片核对")
    for i, (mk, wid) in enumerate(reversed(出图), 1):
        p = fb.导出图片(tok, wid, out / f"prd{i}.jpg")
        print(f"   {mk} → {p}（{p.stat().st_size} 字节）")

    print(f"\n✅ https://aqvi2xbk5kd.feishu.cn/docx/{doc}")


if __name__ == "__main__":
    main()
