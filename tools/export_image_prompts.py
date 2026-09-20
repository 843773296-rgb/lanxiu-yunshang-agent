#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出「每款商品的出图要求清单」—— 交给外部生图模型(GPT 等)按清单出图。

    python3 tools/export_image_prompts.py [输出目录]      # 默认 ~/Desktop/澜绣云裳agent-商品出图清单

只读库、只写本地文件,不调任何外部服务。

**提示词里的每个事实都从库或知识库里取,不在这里另抄一份:**
  · 形制结构 ← knowledge/01-形制.md 每个形制的「结构」那一行
  · 颜色(色名 + 色值) ← backend/img.py 的传统色表,和现在系统里的图是同一个颜色
  · 面料 / 工艺 ← 定制品取 product_custom 的第一项(默认款);标品从商品名里认 material / craft 表里的名字
抄一份就会漂:改了形制说明,出图要求还是旧的,生出来的图和系统说法对不上。

分三档(先出第一档就够上线用):
  ① 主图:每款一张
  ② 颜色图:同一款的其他颜色各一张(和主图同色的 SKU 直接用主图)
  ③ 细节图:面料特写 / 工艺特写 / 领袖结构 / 背面
"""
import csv, os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "knowledge")]
import img as V1
import motif as _motif

DB = os.path.join(ROOT, "backend", "lanxiu.db")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/澜绣云裳agent-商品出图清单")

# 全局风格:在 GPT 里先贴一次,之后每条只贴单条提示词
STYLE = """你是汉服电商的商品摄影师。接下来我会逐条发商品出图要求,每条出一张图,统一遵守:
1. 真实商品摄影质感(不是插画、不是 3D 渲染感),柔和棚拍光,面料纹理、光泽、垂坠清晰可见。
2. 服装类:整件穿在隐形人台上(看不到人台和模特,不出现人脸和手),正面、居中、完整入画,不裁掉下摆和袖子。
   配饰 / 面料类:按每条里写的摆放方式拍。
3. 背景:浅暖灰无缝背景纸,地面有很淡的投影。画面里不出现任何其他道具。
4. 颜色按条目里给的色名和色值还原,不要自行加滤镜、不要偏色。
5. 形制结构必须按条目里的「结构」来画 —— 领型、衽向(右衽 = 左襟压右襟)、袖型、裙褶位置都不能改;
   不要混入其他朝代或现代服装元素(无拉链外露、无纽扣排扣、无西式翻领)。
6. 画面里不出现任何文字、水印、logo、价签、尺寸标注、箭头和引线。
7. **一张图只拍一件事**:不要拼图、不要分格、不要把正面背面或多个角度并排放进同一张,
   也不要在主图旁边贴细节小图 —— 细节图我会单独下单。
8. 方图 1:1,至少 1024×1024。"""

# 没有形制的商品(配饰 / 面料 / 辅料):按品类定摆放方式
摆法 = [(("簪", "钗", "步摇", "璎珞", "项圈", "玉佩", "禁步", "花钿", "额饰", "冠", "盘扣"),
         "首饰特写:平放在浅灰细麻台面上,俯拍 45°,主体占画面六成,金属与珠玉的光泽要真实"),
        (("面料", "绣片", "滚边", "内衬", "织带"),
         "面料样:一块布料松松折叠成两层平铺,一角微微翻起露出背面,俯拍,纹样和织纹清晰可辨"),
        (("鞋",), "鞋履:一双并排,前侧 45° 视角,鞋面刺绣清晰"),
        (("袜",), "平铺俯拍,两双叠放"),
        (("扇",), "团扇 / 障扇:立在无缝背景前,正面,扇面图案完整"),
        (("香囊", "荷包"), "小件:平放俯拍,几只错落摆放,流苏自然垂落"),
        (("云肩",), "云肩:平铺展开成圆形俯拍,四合如意的四瓣对称完整"),
        (("腰封", "革带", "宫绦", "披帛", "抹额", "方巾", "幞头"),
         "服饰配件:平铺俯拍,长条形的自然弯成 S 形放置,系带散开")]

# 纹样名 → 怎么画。词是 knowledge/12-纹样.md 定的,这里只说画法
纹样怎么画 = {
    "云纹": "如意头连缀的云、带尾,多走在缘边和襕上",
    "团花": "圆形适合纹样,团内填花,散点排布",
    "缠枝": "枝蔓连绵不断、花叶相生,满地排布",
    "折枝": "截取一枝,不连续,只在主要部位",
    "宝相花": "多层花瓣放射对称的理想化大花",
    "回纹": "直线折成的连续方格边饰,只走边",
    "龟甲": "六边形连续骨架,格内填小花",
    "联珠": "圆珠串成环,环内置主纹",
    "柿蒂": "四瓣对称,置于领口肩部",
    "海水江崖": "下摆一圈水波加山石",
    "暗花": "同色提花,**不要用对比色**,只靠光泽差显出花形",
}

图位说明 = {
    "main": "主图:纯展示,只有这一件衣服,正面全身、居中、完整入画,不带任何细节小图和标注",
    "d1": "细节图 1(单独一张,只拍这一处):面料特写,取前身一块手掌大小的区域,微距,看清织纹与光泽",
    "d2": "细节图 2(单独一张,只拍这一处):工艺特写,对准刺绣 / 织金 / 镶边最精彩的一处,微距",
    "d3": "细节图 3(单独一张,只拍这一处):领口与袖口(或裙腰与褶)的结构细节,斜 30° 近景",
    "intro": "介绍图:背面全身,和主图同一件、同一光线",
}


def 形制结构():
    """knowledge/01-形制.md:「### XZ01 名称」下面那条「**结构**:…」"""
    s = open(os.path.join(ROOT, "knowledge", "01-形制.md"), encoding="utf-8").read()
    out, cur = {}, None
    for line in s.splitlines():
        m = re.match(r"###\s+(XZ\d+)", line)
        if m:
            cur = m.group(1)
        elif cur and "**结构**" in line:
            out[cur] = re.sub(r"\*\*|`", "", line.split("**结构**", 1)[1]).lstrip(":: ").strip()
            cur = None
    return out


def 认名字(text, names):
    """商品名里出现的面料 / 工艺名(长的优先,认到的短名如果是长名的一部分就不要)"""
    hit = []
    for n in sorted({x for x in names if x}, key=len, reverse=True):
        for part in re.split(r"\s*/\s*", n):          # 「绢 / 电力纺」这种按斜杠拆开认
            if len(part) >= 2 and part in text and not any(part in h for h in hit):
                hit.append(part)
    return hit


def 色(name):
    hexv = V1.colors().get(name) or V1.colors().get(name.replace("色", ""))
    return f"{name}({hexv})" if hexv else name


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    结构 = 形制结构()
    # 只认主料和真正的工艺 —— craft 表里还混着形制、材质、配饰(不筛的话「云肩」会被当成工艺)
    材 = [r[0] for r in c.execute("SELECT name FROM material WHERE cat='主料'")]
    艺 = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='工艺'")]
    # 面料 / 工艺的外观一句话(知识库里的 brief),让生图知道这门料 / 这门工艺长什么样
    外观 = {r[0]: r[1] for r in c.execute("SELECT name, brief FROM craft WHERE cat IN ('材质','工艺') AND brief!=''")}
    rows = c.execute("""
        SELECT p.spu, p.name, p.gender, p.kind, p.remark, cat.name AS cat,
               pt.xz, xz.name AS xzname, pc.mt_opts, pc.kf_opts
        FROM product p
        LEFT JOIN category cat ON cat.code = p.category
        LEFT JOIN pattern pt ON pt.code = p.pattern
        LEFT JOIN xingzhi xz ON xz.code = pt.xz
        LEFT JOIN product_custom pc ON pc.spu = p.spu
        ORDER BY p.kind DESC, cat.name, p.spu""").fetchall()

    out, 缺结构 = [], []
    for r in rows:
        spu, nm = r["spu"], r["name"]
        sks = c.execute("SELECT code, color, img FROM sku WHERE spu=? ORDER BY code", (spu,)).fetchall()
        # 颜色和系统现在的图一致:主图取第一个 SKU 的颜色;定制品按 SPU 固定挑一个传统色
        def 实色(x):
            return x if x not in ("定制", "默认", "", None) else V1.PALETTE[V1._hue(spu + "c") % len(V1.PALETTE)]
        主色 = 实色(sks[0]["color"] if sks else "")
        if r["mt_opts"]:
            面料 = [x.strip() for x in r["mt_opts"].split(",")][:1]
        else:
            面料 = 认名字(nm, 材)
        # 工艺取前两项 —— 样图那款是「苏绣,缂丝」,只取第一项的话图上就只有苏绣,缂丝没人画
        工艺 = [x.strip() for x in (r["kf_opts"] or "").split(",")][:2] if r["kf_opts"] else 认名字(nm, 艺)[:2]
        工艺 = [x for x in 工艺 if x and x not in 面料]

        parts = [f"商品:{nm}"]
        if r["xz"]:
            parts.append(f"形制:{r['xzname']}")
            if r["xz"] in 结构:
                parts.append(f"结构:{结构[r['xz']]}")
            else:
                缺结构.append(r["xz"])
            parts.append(f"穿着者:{'儿童' if '童款' in (r['xzname'] or '') else (r['gender'] or '女')}装,按{'儿童' if '童款' in (r['xzname'] or '') else '成人'}比例")
        else:
            # 先按商品名认,认不出再按品类 —— 团扇挂在「宫绦 / 玉佩」品类下,按品类会被当成首饰去拍
            摆 = next((how for keys, how in 摆法 if any(k in nm for k in keys)), None) \
                or next((how for keys, how in 摆法 if any(k in (r["cat"] or "") for k in keys)), None)
            parts.append(f"品类:{r['cat']}")
            # 认不出的(比如那件西装套装)按服装拍,不能留空 —— 留空时 GPT 会自己挑一个机位
            parts.append(f"摆放:{摆 or '服装:穿在隐形人台上,正面全身'}")
        def 带外观(xs):
            return "、".join(f"{x}({外观[x]})" if 外观.get(x) else x for x in xs)
        if 面料:
            parts.append("面料:" + 带外观(面料))
        if 工艺:
            parts.append("工艺:" + 带外观(工艺) + ",按这门工艺的真实外观表现,不要画成印花")
        # 纹样:口径在 knowledge/motif.py,和打版图上画的那个花**同一个来源**。
        # 推不出来的(补子这类按品级定的)**一个字都不写** —— 写一句猜的上去,
        # 生图模型会照着画,而画出来的是一件错的事,图上又看不出是猜的。
        纹, 纹源, _ = _motif.推(nm, "、".join(面料), "、".join(工艺))
        if 纹 == "无纹样":
            parts.append("纹样:素面,**整件没有任何花纹**,只靠面料本身的织纹和光泽,不要自行加花")
        elif 纹源 != _motif.待核:
            parts.append(f"纹样:{纹}({纹样怎么画[纹]})")
        if r["remark"] and r["remark"].startswith(("设计灵感", "风格定位")):
            parts.append(r["remark"].replace(":", ":", 1))

        def add(tier, slot, color, files, extra=""):
            说明 = 图位说明.get(slot, "颜色图:和主图同一件、同一机位,只换成这个颜色")
            if slot == "main" and not r["xz"]:
                说明 = "主图:纯展示,只有这一件,按上面的摆放方式完整入画,不带细节小图和标注"
            p = parts + [f"颜色:主色 {色(color)}", 说明]
            if extra:
                p.append(extra)
            out.append({"档": tier, "文件名": files[0], "SPU": spu, "商品名": nm, "图位": slot,
                        "颜色": color, "提示词": ";".join(p) + "。", "同图文件": " ".join(files[1:])})

        # ① 主图 —— 第一个颜色的 SKU 图和主图是同一张
        first = [s["img"] for s in sks if 实色(s["color"]) == 主色 and s["img"]]
        add("①主图", "main", 主色, [f"{spu}-main.png"] + [os.path.basename(f).replace(".svg", ".png") for f in first])
        # ② 其他颜色:同色多个尺码共用一张
        by_color = {}
        for s in sks:
            col = 实色(s["color"])
            if col != 主色 and s["img"]:
                by_color.setdefault(col, []).append(os.path.basename(s["img"]).replace(".svg", ".png"))
        for col, files in by_color.items():
            add("②颜色图", "sku", col, files)
        # ③ 细节图(配饰只要一张背面没意义,只出面料 / 工艺特写)
        for slot in (("d1", "d2", "d3", "intro") if r["xz"] else ("d1", "d2")):
            add("③细节图", slot, 主色, [f"{spu}-{slot}.png"])

    os.makedirs(OUT, exist_ok=True)
    cols = ["档", "文件名", "SPU", "商品名", "图位", "颜色", "提示词", "同图文件"]
    with open(os.path.join(OUT, "出图清单-全部.csv"), "w", newline="", encoding="utf-8-sig") as f:  # 带 BOM,Excel 直接打开不乱码
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(out)

    # 主图单独一份 Markdown,方便逐条复制
    主 = [o for o in out if o["图位"] == "main"]
    with open(os.path.join(OUT, "出图清单-主图.md"), "w", encoding="utf-8") as f:
        f.write(f"# 澜绣云裳 · 商品主图出图清单({len(主)} 条)\n\n先把《先读我》里的「统一要求」贴给 GPT 一次,再逐条贴下面的提示词。\n\n")
        for i, o in enumerate(主, 1):
            f.write(f"## {i}. {o['商品名']}\n\n存成:`{o['文件名']}`")
            if o["同图文件"]:
                f.write(f"(同一张再复制成:{o['同图文件']})")
            f.write(f"\n\n```\n{o['提示词']}\n```\n\n")

    n = {t: sum(1 for o in out if o["档"] == t) for t in ("①主图", "②颜色图", "③细节图")}
    with open(os.path.join(OUT, "00-先读我.md"), "w", encoding="utf-8") as f:
        f.write(f"""# 澜绣云裳 · 商品出图清单

由 `tools/export_image_prompts.py` 从商品库导出。共 {len(out)} 张图,分三档,**先出第一档就能替换掉现在的示意图**:

| 档 | 张数 | 说明 |
|---|---|---|
| ① 主图 | {n['①主图']} | 每款一张,正面全身。颜色和系统里第一个 SKU 一致 |
| ② 颜色图 | {n['②颜色图']} | 同一款的其他颜色,各一张(同色不同尺码共用) |
| ③ 细节图 | {n['③细节图']} | 面料特写 / 工艺特写 / 领袖结构 / 背面 |

## 怎么用

1. 在 GPT 里先贴下面的「统一要求」一次。
2. 打开 `出图清单-主图.md`,逐条复制代码框里的提示词发过去。
3. 出好的图按「存成」那一栏的文件名保存,全放进同一个文件夹。
   有「同一张再复制成」的,把这张图再复制几份、改成那些文件名(不用重新生成)。
4. 放好之后告诉我文件夹在哪,我来接进系统。

`出图清单-全部.csv` 是三档全部的表格(Excel 可直接打开),适合批量出图工具按行跑。

## 统一要求(贴一次)

```
{STYLE}
```

## 提示词里的内容从哪来

- 形制结构:知识库《形制》里每个形制的「结构」说明
- 颜色:系统传统色表的色名和色值,和现在系统里的示意图同一个颜色
- 面料、工艺:定制款取默认面料和工艺(可选项里的第一个);成品款从商品名里认
- 设计灵感:商品备注里的「设计灵感」或「风格定位」

## 出图时要留意

- 汉服结构 AI 容易画错,最常见的三个:**衽向画反**(应为右衽,即左襟压右襟)、
  **马面裙的褶画成一圈**(应是前后两片平整马面,褶只在两侧)、**褙子画出扣子**(褙子不施纽)。
  收图时重点看这三处。
- 这些是合成的商品示意图,不是实物照片。上线前需要按实物拍摄替换,或在页面上标注「效果示意」。
""")

    print(f"✅ 导出 {len(out)} 条 → {OUT}")
    for t, k in n.items():
        print(f"   {t}: {k}")
    if 缺结构:
        print(f"⚠️ 这些形制在知识库里找不到「结构」说明:{sorted(set(缺结构))}")


if __name__ == "__main__":
    main()
