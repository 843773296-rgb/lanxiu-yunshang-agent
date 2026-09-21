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
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'knowledge'))
import grading as _grading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "knowledge")]
import img as V1
import motif as _motif

DB = os.path.join(ROOT, "backend", "lanxiu.db")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/澜绣云裳agent-商品出图清单")
# 出好的图往哪儿放 —— **路径写死在文件里**,不要让人自己找:
# 「放进同一个文件夹」这句话,每个人理解的那个文件夹都不一样
存图 = os.path.expanduser("~/Desktop/澜绣云裳agent-出好的图")

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


def 号型(pattern):
    if not pattern:
        return []
    c = sqlite3.connect(DB)
    return [r[0] for r in c.execute("SELECT DISTINCT size FROM size_spec WHERE pattern=?", (pattern,))]


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
        SELECT p.spu, p.name, p.gender, p.kind, p.remark, cat.name AS cat, p.category AS 品类,
               p.pattern AS 版型, pt.xz, xz.name AS xzname, pc.mt_opts, pc.kf_opts
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
            # 大人还是小孩:**四个信号一起看,打架就明说打架** ——
            # 原来只看形制名,于是「童款交领襦裙」(名字说童款、形制挂的是成人版型)
            # 被静默判成成人比例。用户出图时发现的。
            # **不许投票决定**:三比一也是矛盾,真正的问题是这条数据错了,该报给业务核,
            # 而不是由出图清单替业务挑一个 —— 挑错了,出来的图看着完全正常。
            # 口径只有一份:`knowledge/grading.py`。门禁检查和假数据工厂的
            # 一致性引擎调的是同一个函数 —— 原来这里自己写了一份,
            # 判的是「童款」,于是「**男童**」明制道袍被判成了成人款。
            信号 = _grading.年龄段信号(r["xzname"], r["gender"], nm,
                                       r["品类"], 号型(r["版型"]))
            if len(set(信号.values())) > 1:
                打架 = "、".join(f"{k}说{'童装' if v == '童' else '成人'}" for k, v in 信号.items())
                parts.append(f"⚠️ **这一款先别出**:库里的数据自相矛盾({打架})。"
                             f"按哪种比例画要等业务核完,**不要自己挑一个** —— 挑错了图看着也正常")
            else:
                童 = 信号["形制"] == "童"
                parts.append(f"穿着者:{'儿童' if 童 else (r['gender'] or '女')}装,按{'儿童' if 童 else '成人'}比例")
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
                        "颜色": color, "提示词": ";".join(p) + "。", "同图文件": " ".join(files[1:]),
                        # 批次文件里「这一款的底」只写一次,每张图只写它自己那一句 ——
                        # 整段重复 6 遍要贴 6 遍,而人贴到第三遍就开始跳着贴了
                        "_共同": ";".join(parts) + "。", "_单图": f"{说明};颜色:主色 {色(color)}。"})

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
    os.makedirs(存图, exist_ok=True)      # 先把存图的文件夹建好,免得人自己猜该建在哪
    cols = ["档", "文件名", "SPU", "商品名", "图位", "颜色", "提示词", "同图文件"]
    with open(os.path.join(OUT, "出图清单-全部.csv"), "w", newline="", encoding="utf-8-sig") as f:  # 带 BOM,Excel 直接打开不乱码
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(out)

    # ── 按商品分批 ────────────────────────────────────────────────────
    # 一款一整套(主图 + 背面 + 三张细节 + 其他颜色)一次出完,**不要按图位横着出** ——
    # 同一款的几张图必须看着像同一件衣服,分几天出、中间隔着别的款,风格会飘。
    # 批次按**卖得多的排前面**:出图是有成本的,先换掉客户看得最多的那些。
    卖 = {r[0]: r[1] for r in c.execute("SELECT spu, COUNT(*) FROM ordr_item GROUP BY spu")}
    # **每批多少款,是业务定的,不是技术定的。**
    #   前四批  12 上下 —— 那时在试 GPT 的额度消耗(「两批烧掉 20% 额度」是当时实测)
    #   一度定为 50 —— 跑完四批节奏稳了
    #   **2026-09-21 改回 25** —— 50 款约 420 张,业务反馈「有点大了」
    # 留着环境变量覆盖:`每批=20 python3 tools/export_image_prompts.py`。
    每批 = int(os.environ.get("每批", 25))
    # **已经出好的不再列进批次** —— 出图是一批批补的,清单每次重导都该只剩「还没出的」。
    # 不剔掉的话,补到第三轮时人得自己记住哪些做过了,而**记错的代价是重复出一遍**。
    # 判据是「这张图在不在」,不是「这一批标没标完成」—— 标记会忘,文件不会。
    收图目录 = os.path.join(ROOT, "backend", "static", "img")
    已出 = set()
    if os.path.isdir(收图目录):
        for f in os.listdir(收图目录):
            stem = os.path.splitext(f)[0]
            sp, _, v = stem.rpartition("-")
            已出.add((sp, v))
    out = [o for o in out if (o["SPU"], o["图位"] if o["图位"] != "sku"
                              else os.path.splitext(o["文件名"])[0].rpartition("-")[2]) not in 已出]
    if not out:
        print("✅ 所有图都出齐了,没有要补的")
    按款 = {}
    序 = sorted({o["SPU"] for o in out}, key=lambda s: (-卖.get(s, 0), s))
    # 名次按**全库销量**算,不按这次剩下的重排 —— 出过的那些占着前面的名次,
    # 剩下的从第 26 名开始,这样「第几名」在两次重导之间是同一个意思
    全序 = [r[0] for r in c.execute(
        """SELECT p.spu FROM product p LEFT JOIN
           (SELECT spu, COUNT(*) n FROM ordr_item GROUP BY spu) s ON s.spu=p.spu
           ORDER BY COALESCE(s.n,0) DESC, p.spu""")]
    名次 = {spu: i for i, spu in enumerate(全序, 1)}
    # 命令行也能给:`python3 tools/export_image_prompts.py <输出目录> --前 38`
    上限 = int(os.environ.get("只要前几款", 0))       # 0 = 全部
    if "--前" in sys.argv:
        上限 = int(sys.argv[sys.argv.index("--前") + 1])
    if 上限:
        留 = set(序[:上限]); out = [o for o in out if o["SPU"] in 留]; 序 = 序[:上限]
    批 = [序[i:i + 每批] for i in range(0, len(序), 每批)]
    # 最后一批只剩零星几款就并进上一批 —— 一个只装 1 款的文件,打开的成本比它的内容还高
    #
    # ⚠️ **别写成 `批[-2] += 批.pop()`。** 负数下标在 pop 之后会重新解析:
    # pop 把列表变短了,`-2` 指向的已经不是原来那一批 —— 于是两批内容重叠,
    # 算出**同一个文件名**,后写的把先写的覆盖掉,而目录里只是少了一个文件,不报错。
    if len(批) > 1 and len(批[-1]) <= 每批 * 0.4:
        尾 = 批.pop()
        批[-1] = 批[-1] + 尾
    名字 = {o["SPU"]: o["商品名"] for o in out}
    for o in out:
        按款.setdefault(o["SPU"], []).append(o)
    图位序 = {"main": 0, "intro": 1, "d1": 2, "d2": 3, "d3": 4, "sku": 5}

    # **旧批次文件先归档,不直接删。**
    # 2026-09-20 踩过:用户的 GPT 正按那份清单出图,我重导时把文件删了、编号还从 01 重排,
    # 于是出现两个「批次-01」装着不同的东西。**那一刻它不是我的产物,是用户正在执行的工单。**
    旧 = [f for f in os.listdir(OUT) if f.startswith("批次-") and f.endswith(".md")] if os.path.isdir(OUT) else []
    if 旧:
        存 = os.path.join(OUT, "旧清单")
        os.makedirs(存, exist_ok=True)
        for f in 旧:
            os.replace(os.path.join(OUT, f), os.path.join(存, f))
        print(f"   旧的 {len(旧)} 个批次文件已挪到「旧清单」文件夹(没删)")

    进度, 写过 = [], set()
    for bi, spus in enumerate(批, 1):
        张数 = sum(len(按款[s]) for s in spus)
        # 文件名带**名次区间**,不用「第几批」—— 编号会复用,名次不会。
        # 「第 1 批」这个名字下一轮还会出现,而「第 26–37 名」永远指同一批货。
        起, 止 = 名次[spus[0]], 名次[spus[-1]]
        路径 = os.path.join(OUT, f"待出图-第{起}到{止}名.md")
        # 同名就是算错了 —— **宁可当场报错,也别静默覆盖**:
        # 覆盖之后目录里只是少一个文件,而少的那批货没有任何地方会提醒
        if 路径 in 写过:
            raise SystemExit(f"❌ 两批算出同一个文件名 {os.path.basename(路径)} —— 分批逻辑错了,不写")
        写过.add(路径)
        with open(路径, "w", encoding="utf-8") as f:
            f.write(f"# 待出图 · 第 {起} 到 {止} 名(按历史销量)—— {len(spus)} 款 · {张数} 张\n\n"
                    f"**图存到这个文件夹:**\n\n    {存图}\n\n"
                    f"(文件夹已经建好了,直接往里放;文件名按每条写的来,别改)\n\n"
                    f"先把《00-先读我》里的「统一要求」贴给 GPT 一次(每开一个新对话都要贴)。\n"
                    f"然后**一款一款来**:把一款底下的几条提示词依次发过去,这一款出完再下一款。\n\n")
            for pi, spu in enumerate(spus, 1):
                gs = sorted(按款[spu], key=lambda o: (图位序.get(o["图位"], 9), o["文件名"]))
                f.write(f"---\n\n## 第 {名次[spu]} 名 · {名字[spu]}\n\n"
                        f"`{spu}` · 这一款 {len(gs)} 张"
                        + (f" · 历史售出 {卖.get(spu, 0)} 件\n\n" if 卖.get(spu) else "\n\n"))
                f.write("**这一款的底(先发这一段)**\n\n```\n" + gs[0]["_共同"] + "\n```\n\n")
                for gi, o in enumerate(gs, 1):
                    f.write(f"**{gi})** 存成 `{o['文件名']}`")
                    if o["同图文件"]:
                        f.write(f" —— 同一张再复制成:{o['同图文件']}")
                    f.write(f"\n\n```\n{o['_单图']}\n```\n\n")
                f.write("> 第 1 张出好、你认可之后,**让它以第 1 张为参考**出后面几张 ——\n"
                        "> 这几张要看着是同一件衣服,不是同一个款式的几件。\n\n")
                进度.append(dict(批次=f"第{起}到{止}名", 序号=名次[spu], SPU=spu, 商品名=名字[spu],
                                 张数=len(gs), 历史售出=卖.get(spu, 0),
                                 文件名="; ".join(x["文件名"] for x in gs), 出完了=""))
    with open(os.path.join(OUT, "进度表.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["批次", "序号", "SPU", "商品名", "张数", "历史售出", "文件名", "出完了"])
        w.writeheader(); w.writerows(进度)

    n = {t: sum(1 for o in out if o["档"] == t) for t in ("①主图", "②颜色图", "③细节图")}
    with open(os.path.join(OUT, "00-先读我.md"), "w", encoding="utf-8") as f:
        f.write(f"""# 澜绣云裳 · 商品出图清单

由 `tools/export_image_prompts.py` 从商品库导出。**{len(序)} 款商品 · {len(out)} 张图 · 分 {len(批)} 批**,
一款一整套(主图 + 背面 + 三张细节 + 其他颜色),一次出完一款。

| 一套里有什么 | 张数 | 说明 |
|---|---|---|
| 主图 | {n['①主图']} | 每款一张,正面全身。颜色和系统里第一个 SKU 一致 |
| 介绍图(背面) | 见各款 | 和主图同一件、同一光线 |
| 细节图 | {n['③细节图']} | 面料特写 / 工艺特写 / 领袖或裙腰结构 |
| 颜色图 | {n['②颜色图']} | 这一款的其他颜色(同色不同尺码共用一张) |

配饰和面料部件只有主图 + 两张细节(背面对它们没意义),所以每款 3–8 张不等。

## 怎么用

图按**商品**分好了批,文件名是 `待出图-第 N 到 M 名.md`,每批 {每批} 款上下。
**名次 = 历史销量排名**,卖得最多的在最前面 —— 出图有成本,先换掉客户看得最多的那些。
⚠️ 文件名用名次不用「第几批」:**编号会复用,名次不会** ——
「第 1 批」下一轮还会出现,而「第 26 到 37 名」永远指同一批货。

**这两个文件夹都在桌面上,已经建好了:**

| 干什么用 | 文件夹 |
|---|---|
| 清单在这儿(就是你正在看的这份) | `{OUT}` |
| **出好的图放这儿** | `{存图}` |

1. 开一个新对话,先贴下面的「统一要求」(每开一个新对话都要贴一次)。
2. 打开名次最靠前的那个文件,**一款一款来**:把这一款底下的几条提示词依次发过去,出完再下一款。
3. 图按每条写的文件名存,**全放进上面那个「出好的图」文件夹**,不用建子文件夹。
   有「同一张再复制成」的,把这张图复制几份改名就行,不用重新生成。
4. 一批出完,在 `进度表.csv` 的「出完了」那一栏打个勾,下次从下一批接着来。
5. 出完几批就可以告诉我一声,我直接从那个文件夹收进系统 —— **不用等全部出完**。

⚠️ **一款的几张图要一次出完,别按图位横着出**(先出所有主图、改天再出所有细节图)——
同一款的几张必须看着像同一件衣服,隔着别的款出,风格会飘,而**单看每一张都挑不出毛病**。

`出图清单-全部.csv` 是全部 {len(out)} 张的表格(Excel 可直接打开),适合批量出图工具按行跑。

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
