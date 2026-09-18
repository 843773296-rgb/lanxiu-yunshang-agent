#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布《澜绣云裳agent-产品需求文档》到飞书，并把三张图画进画板。

和 publish_product_doc.py 同一套流程，区别只在：文档不同、图的文案是 PRD 口吻。
坐标复用，文案单列 —— 两份文档的图形状一样，说法不一样。
"""
import importlib.util, os, pathlib, re, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
_s = importlib.util.spec_from_file_location("fb", ROOT / "tools/feishu_board.py")
fb = importlib.util.module_from_spec(_s); _s.loader.exec_module(fb)
API, fp = fb.API, fb.fp

# 图 ← 章节。**用章节号配对，不用「第几张」** ——
# 靠序号配对时，两张图对调之后**都画得出来、都读得回、不报任何错**，
# 只有人打开文档才看得出图放错了地方。这是「数量对上 ≠ 放对了」的又一例。
图序 = ["2.1", "2.6", "3.3", "3.5"]
标记文本 = {
    "2.1": "【图一】系统协同架构",
    "2.6": "【图二】写入控制机制",
    "3.3": "【图三】数据流转地图",
    "3.5": "【图四】一轮对话的运行过程",
}

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
  # ── 图四:一轮对话的运行过程 ──────────────────────────────────
  # 这张图的全部信息量在颜色上:紫=我们插进去的四个介入点,蓝=运行时框架转的。
  # 三条回边(拦截理由 / 工具结果 / 退回重答)是「循环」二字的实体。
  dict(节点=[
      N("lg1","▨ 运行时框架托管",                    1500,   0, 320,  60, "rect", 色="托"),
      N("lg2","▨ 本系统实现的介入点",                 1500,  80, 320,  60, "rect", 色="我"),
      N("q",  "员工提问",                              300,    0, 400,  80),
      N("h1", "① 开场注入\n当前日期 + 最近三条工作记录", 300,  150, 400, 100, 色="我"),
      N("m",  "模型判断\n下一步做什么",                300,  330, 400,  90, 色="托"),
      N("d1", "需要调用工具吗",                        280,  500, 440, 140, "diamond", 色="判"),
      N("h2", "② 调用前约束\n白名单 · 权限预演 · 行为约束", 880, 510, 420, 110, 色="我"),
      N("d2", "放行吗",                                880,  700, 420, 130, "diamond", 色="判"),
      N("bk", "把拦截理由交回模型",                    1440,  715, 320, 100, 色="拒"),
      N("ex", "工具执行",                              900,  900, 400,  80, 色="托"),
      N("h3", "③ 调用后记录\n回填本次写入是否成功",     880, 1050, 420, 100, 色="我"),
      N("ans","生成答复",                              300, 1020, 400,  80, 色="托"),
      N("h4", "④ 交付前校验 22 项",                    280, 1180, 440, 140, "diamond", 色="我"),
      N("re", "退回重答\n（只允许一次）",              -320, 1190, 320, 100, 色="拒"),
      N("u",  "员工",                                  300, 1420, 400,  80, 色="过"),
      N("tr", "每轮结构化记录",                        300, 1570, 400,  80, 色="记"),
  ], 边=[
      E("q","h1"), E("h1","m"), E("m","d1"),
      R("d1","h2","需要"), E("h2","d2"),
      R("d2","bk","拦截"),
      dict(a="bk", b="m", 标="回边一 · 拦截理由", 起="top", 止="right", 标位=(1560, 420)),
      E("d2","ex","放行"), E("ex","h3"),
      dict(a="h3", b="m", 标="回边二 · 工具结果（这就是「轮」）", 起="left", 止="right",
           标位=(960, 430)),
      E("d1","ans","不需要"), E("ans","h4"),
      dict(a="h4", b="re", 标="未通过", 起="left", 止="right"),
      dict(a="re", b="m", 标="回边三 · 退回重答", 起="top", 止="left", 标位=(150, 700)),
      E("h4","u","通过"), E("u","tr"),
  ]),
]


def 做飞书版():
    """把每个 mermaid 块换成它所属章节的占位符。

    先核对「每个图落在哪一章」和规格是否一致 —— 对不上直接停手，
    因为图放错位置之后画板照样画得出来、读得回，没有任何一环会报错。
    """
    src = (ROOT / "澜绣云裳agent-产品需求文档.md").read_text(encoding="utf-8")
    行 = src.split("\n")
    当前, 命中, i = None, [], 0
    while i < len(行):
        m = re.match(r"^#{1,2} (\d+(?:\.\d+)?) ", 行[i])
        if m:
            当前 = m.group(1)
        if 行[i].strip() == "```mermaid":
            j = i + 1
            while j < len(行) and 行[j].strip() != "```":
                j += 1
            命中.append((当前, i, j))
            i = j
        i += 1

    落在 = [c for c, _, _ in 命中]
    if 落在 != 图序:
        sys.exit("❌ mermaid 块落在的章节是 %s，规格里写的是 %s。\n"
                 "   图和章节对不上时两边都画得出来也不报错，所以这里停手。"
                 % (落在, 图序))

    for 章, a, b in reversed(命中):          # 从后往前，行号不失效
        行[a:b + 1] = [标记文本[章]]
    out = pathlib.Path("/tmp/澜绣云裳agent-产品需求文档.md")
    out.write_text("\n".join(行), encoding="utf-8")
    return out

def 找标记(tok, doc):
    """返回 {章节号: 该占位段在根块子块里的序号}。

    ⚠️ **一次列完所有块,不要一块一个 GET。** 文档现在 233 个块,
    逐块请求要跑四分钟,上一版就是这么超时的 —— 而超时和「没找到」
    在调用方看来是同一件事。
    """
    d = fb._call(tok, "GET", f"{API}/docx/v1/documents/{doc}/blocks/{doc}")
    kids = ((d.get("data") or {}).get("block") or {}).get("children") or []

    文本 = {}
    页 = ""
    while True:
        u = f"{API}/docx/v1/documents/{doc}/blocks?page_size=500"
        if 页:
            u += f"&page_token={页}"
        r = fb._call(tok, "GET", u)
        data = r.get("data") or {}
        for blk in data.get("items") or []:
            文本[blk.get("block_id")] = "".join(
                e.get("text_run", {}).get("content", "")
                for e in (blk.get("text") or {}).get("elements", []))
        页 = data.get("page_token") or ""
        if not data.get("has_more"):
            break

    位 = {}
    for i, bid in enumerate(kids):
        txt = 文本.get(bid, "")
        for 章, mk in 标记文本.items():
            if mk in txt:
                位[章] = i
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

    # ⚠️ **导入是异步的。** 接口返回文档 id 的那一刻,块可能一个都还没写进去 ——
    # 这时去找占位段会「一个都没找到」,而那和「文档里真的没有占位段」长得一模一样。
    # 栽过一次:四个标记全报没找到,文档其实好好的,只是还没写完。
    print("\n② 等导入写完")
    上次, 稳定 = -1, 0
    for i in range(60):
        n = fb.根块子块数(tok, doc)
        if n > 0 and n == 上次:
            稳定 += 1
            if 稳定 >= 2:            # 连续两次读到同一个数才算写完
                break
        else:
            稳定 = 0
        上次 = n
        time.sleep(2)
    else:
        sys.exit(f"❌ 等了 120 秒,子块数仍在变(最后 {上次} 个)—— 停手,别对着半份文档插图")
    print(f"   子块 {上次} 个,连续两次不变")

    print("\n③ 找占位段")
    位 = 找标记(tok, doc)
    for 章 in 图序:
        有 = 章 in 位
        print("   %s（§%s）: %s" % (标记文本[章], 章,
                                  ("第 %d 个子块" % 位[章]) if 有 else "❌ 没找到"))
    if len(位) != len(图序):
        sys.exit("❌ 占位段没找齐，停手")

    print("\n④ 插画板并画（从后往前）")
    出图 = []
    for 章, g in sorted(zip(图序, 图), key=lambda x: -位[x[0]]):
        blk, wid = fb.建画板(tok, doc, index=位[章] + 1)
        n, e = fb.画(tok, wid, g["节点"], g["边"])
        回 = fb.读回(tok, wid)
        print("   %s：图形 %d / 连线 %d / 读回 %d %s"
              % (标记文本[章], n, e, len(回), "✅" if len(回) == n + e else "❌"))
        出图.append((章, wid))

    out = pathlib.Path(os.environ.get("BOARD_IMG_DIR", "/tmp"))
    print("\n⑤ 导出图片核对")
    for i, (章, wid) in enumerate(reversed(出图), 1):
        pth = fb.导出图片(tok, wid, out / ("prd%d.jpg" % i))
        print("   %s → %s（%d 字节）" % (标记文本[章], pth, pth.stat().st_size))

    print("\n✅ https://aqvi2xbk5kd.feishu.cn/docx/%s" % doc)


if __name__ == "__main__":
    main()
