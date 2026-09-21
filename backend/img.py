#!/usr/bin/env python3
"""商品图生成 —— 设计稿要求 750×750。

没有实物照片,所以按商品自身的属性合成一张棚拍风格的图:
  · 颜色取自 SKU 的真实颜色字段,色值来自 knowledge/05-颜色.md 的传统色表
  · 款式剪影按三级类目走(裙装 / 上装 / 外套 / 头饰 / 鞋履 / 面料 …)
  · 质感按面料与工艺加(织金撒金点、妆花提花纹、纱罗半透)
同一个 SPU 每次生成都一样(确定性),不同商品颜色和款式明显不同。

图里不写「示意图」字样(要求做成照片观感),但 SVG 里留了一条
<desc>,说明这是合成图而非实物照片 —— 页面好看,元数据不撒谎。
"""
import os, re, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
KB = os.path.join(HERE, "..", "knowledge", "05-颜色.md")

_COLOR_CACHE = None
FALLBACK = {"素": "#F2EFE8", "金": "#C9A227", "银": "#C0C4CC", "点翠": "#1F6F8B",
            "玉白": "#E8EFE6", "绛": "#8C4356", "妃色": "#ED5736", "定制": "#B9AEA0",
            "墨蓝": "#2E4E7E", "绛红": "#9D2933", "黛蓝": "#4A4266", "红色": "#C0392B",
            "默认": "#CFC7BA"}


def colors():
    """传统色表直接从知识库读 —— 色值只维护一份"""
    global _COLOR_CACHE
    if _COLOR_CACHE is None:
        m = {}
        try:
            s = open(KB, encoding="utf-8").read()
            m = {k: v for k, v in re.findall(r"\|\s*([一-龥]{1,4})\s*\|\s*`(#[0-9A-Fa-f]{6})`", s)}
        except Exception:
            pass
        m.update(FALLBACK)
        _COLOR_CACHE = m
    return _COLOR_CACHE


def _hue(seed):
    v = 0
    for ch in seed: v = (v * 16777619 ^ ord(ch)) & 0xFFFFFFFF
    v ^= v >> 16; v = (v * 0x85EBCA6B) & 0xFFFFFFFF
    v ^= v >> 13; v = (v * 0xC2B2AE35) & 0xFFFFFFFF
    return (v ^ (v >> 16)) % 360


def _hsl_hex(h, s_, l_):
    """HSL → #RRGGBB。**兜底色也要是十六进制** —— 见 `render()` 里的说明。"""
    h = (h % 360) / 360.0; s_ = s_ / 100.0; l_ = l_ / 100.0
    if s_ == 0:
        r = g = b = l_
    else:
        q = l_ * (1 + s_) if l_ < .5 else l_ + s_ - l_ * s_
        p_ = 2 * l_ - q
        def t2c(t):
            t = t % 1.0
            if t < 1/6: return p_ + (q - p_) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p_ + (q - p_) * (2/3 - t) * 6
            return p_
        r, g, b = t2c(h + 1/3), t2c(h), t2c(h - 1/3)
    return "#%02X%02X%02X" % (round(r*255), round(g*255), round(b*255))


def _mix(hex_, f):
    """f>0 提亮,f<0 压暗"""
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    if f >= 0: r, g, b = (int(c + (255-c)*f) for c in (r, g, b))
    else:      r, g, b = (int(c * (1+f)) for c in (r, g, b))
    return "#%02X%02X%02X" % (r, g, b)


# ── 款式剪影(750×750 画布)────────────────────────────────────────
# 只按三级类目分派。第一版掺了名称关键词,结果 `A or B and C` 的优先级
# 让「明制袄裙」这件上装被判成了裙子 —— 类目本来就是权威,不该再靠名字猜。
SHAPES = {
 "C010101": ("M375 214 C344 214 331 226 326 242 L236 274 L214 350 L266 366 L282 316 "   # 襦/衫:短上襦
             "L276 470 L474 470 L468 316 L484 366 L536 350 L514 274 L424 242 "
             "C419 226 406 214 375 214 Z"),
 "C010102": ("M375 200 C342 200 328 214 322 232 L220 268 L194 356 L252 374 L270 314 "   # 袄:长上衣
             "L262 536 L488 536 L480 314 L498 374 L556 356 L530 268 L428 232 "
             "C422 214 408 200 375 200 Z"),
 "C010103": ("M375 196 C340 196 326 210 320 228 L214 264 L188 354 L248 374 L266 306 "   # 褙子:对襟长衫,中缝开
             "L258 596 L360 596 L368 306 Z M382 306 L390 596 L492 596 L484 306 "
             "L502 374 L562 354 L536 264 L430 228 C424 210 410 196 375 196 Z"),
 "C010104": ("M375 222 C348 222 337 232 333 246 L258 272 L240 330 L286 344 L298 306 "   # 半臂:短袖短衣
             "L294 428 L456 428 L452 306 L464 344 L510 330 L492 272 L417 246 "
             "C413 232 402 222 375 222 Z"),
 "C0102":   ("M375 206 L302 228 L288 248 L462 248 L448 228 Z "                          # 裙装:马面/百迭
             "M288 248 L248 600 L502 600 L462 248 Z"),
 "C0103":   ("M375 192 C336 192 322 206 316 224 L186 262 L154 362 L224 384 L246 300 "   # 外套:大袖衫
             "L240 606 L510 606 L504 300 L526 384 L596 362 L564 262 L434 224 "
             "C428 206 414 192 375 192 Z"),
 "C0201":   ("M375 190 C338 190 324 206 320 226 L212 262 L184 356 L246 376 L264 306 "   # 男装圆领袍
             "L256 626 L494 626 L486 306 L504 376 L566 356 L538 262 L430 226 "
             "C426 206 412 190 375 190 Z"),
 "C03":     ("M375 258 C350 258 340 268 336 280 L268 304 L252 360 L296 374 L306 336 "   # 童装
             "L302 542 L448 542 L444 336 L454 374 L498 360 L482 304 L414 280 "
             "C410 268 400 258 375 258 Z"),
 "C0401":   ("M375 166 L390 234 L375 606 L360 234 Z "                                   # 头饰:簪
             "M375 166 m-36 46 a36 36 0 1 0 72 0 a36 36 0 1 0 -72 0"),
 "C0402":   ("M214 336 L536 336 L536 414 L214 414 Z "                                   # 腰饰:腰封 + 垂绦
             "M362 414 L362 566 L388 566 L388 414 Z"),
 "C0403":   ("M375 236 C298 236 240 282 240 340 C240 402 300 452 375 502 "              # 颈肩饰:云肩
             "C450 452 510 402 510 340 C510 282 452 236 375 236 Z "
             "M375 300 C338 300 316 322 316 346 C316 372 342 396 375 420 "
             "C408 396 434 372 434 346 C434 322 412 300 375 300 Z"),
 "C0404":   ("M228 476 C228 424 266 402 322 408 L468 432 C526 442 540 476 532 508 "     # 鞋履
             "L228 508 Z"),
 "C05":     ("M182 208 L568 208 L568 542 C504 574 440 516 375 546 "                     # 面料/部件:布样
             "C310 576 246 516 182 546 Z"),
}


# ── 按**形制**生成剪影(不是按品类) ──────────────────────────────────
# 品类只有 16 个叶子,296 个商品挤在 13 种剪影里 —— **同品类的全长一样**。
# 而每个商品现在都挂上了版型,版型下面有**结构数据**:
#
#     size_spec     基码衣长 36–152cm、通袖长 96–252cm、胸围 86–126cm、裙长 68–122cm
#     pattern_piece 裙片 / 大袖片 / 系带 / 马面 / 横襕 / 立领 / 圆领 …
#     形制名        交领 / 立领 / 方领 / 圆领 / 直领 / 对襟
#
# **这些全部已经在库里** —— 又一次不必另造一套。
# 手画 43 条形制路径既慢又会错,**按结构参数生成**才跟得上形制表扩容。
#
# ⚠️ 这改变了这批图能承载多少信息,**因此也动到了 `vision_eval` 的前提**
# (那套评测原来靠的是「图分不出大袖衫和褙子」)—— 见文件末尾 `png()` 上方的说明。
PART_LO, PART_HI = 36.0, 152.0          # 衣长的实际取值范围,用来定纵向比例
Y_SHOULDER, Y_MAX = 200.0, 636.0
K_LEN = (Y_MAX - Y_SHOULDER) / PART_HI   # ≈ 2.87 px/cm


def _pattern_geom(conn, spu):
    """从版型的结构数据取画图要用的几个数。取不到就返回 None(走老的品类剪影)。"""
    r = conn.execute(
        "SELECT p.pattern FROM product p WHERE p.spu=?", (spu,)).fetchone()
    if not r or not r[0]:
        return None
    pt = r[0]
    spec = {x[0]: x[1] for x in conn.execute(
        "SELECT item,value FROM size_spec WHERE pattern=? AND size='M'", (pt,))}
    if not spec:
        spec = {x[0]: x[1] for x in conn.execute(
            "SELECT item,value FROM size_spec WHERE pattern=? ORDER BY size", (pt,))}
    pieces = {x[0] for x in conn.execute(
        "SELECT name FROM pattern_piece WHERE pattern=?", (pt,))}
    if not spec and not pieces:
        return None
    zn = (conn.execute("SELECT z.name FROM pattern p JOIN xingzhi z ON z.code=p.xz "
                       "WHERE p.code=?", (pt,)).fetchone() or [""])[0]
    return dict(衣长=spec.get("衣长") or spec.get("上襦衣长") or 100.0,
                上襦衣长=spec.get("上襦衣长"),
                裙长=spec.get("裙长"), 通袖长=spec.get("通袖长") or 180.0,
                胸围=spec.get("胸围") or 100.0, 裁片=pieces, 形制名=zn)


def _neck(g, cx, y):
    """领口 —— 领型是形制最显眼的区分项,画出来才看得出两件衣服不一样。"""
    n = g["形制名"]; P = g["裁片"]
    if "交领" in n:                       # 两襟交叠,斜向右
        return f"M{cx-34} {y} L{cx} {y+52} L{cx+34} {y} L{cx+8} {y-4} L{cx} {y+16} L{cx-8} {y-4} Z"
    if "立领" in n or "竖领" in n or "立领" in "".join(P):
        return f"M{cx-22} {y-14} L{cx+22} {y-14} L{cx+22} {y+18} L{cx-22} {y+18} Z"
    if "方领" in n:
        return f"M{cx-30} {y} L{cx+30} {y} L{cx+30} {y+40} L{cx-30} {y+40} Z"
    if "圆领" in n or "圆领" in "".join(P) or "盘领" in n:
        return f"M{cx-30} {y+4} a30 26 0 1 0 60 0 a30 26 0 1 0 -60 0 Z"
    return ""                             # 直领 / 对襟:靠下面那条中缝表达


def _shape_by_pattern(conn, spu):
    """按形制的结构参数拼一张剪影。返回路径字符串,拼不出来返回 None。"""
    g = _pattern_geom(conn, spu)
    if not g:
        return None
    cx = 375.0
    P = g["裁片"]
    有裙 = any("裙" in x or "马面" in x or "褶裥" in x for x in P)
    有上装 = any(("前片" in x or "后片" in x or "上襦" in x) for x in P)
    # **只有裙、没有上装 ⇒ 只画裙。** 马面裙的裁片是「马面 / 褶裥片 / 裙腰 / 系带」,
    # 一件上装裁片都没有 —— 第一版按「有裙片就两截」画,给马面裙硬加了一件上襦。
    只有裙 = 有裙 and not 有上装
    两截 = 有裙 and 有上装
    阔袖 = any("大袖" in x for x in P)
    无袖 = not any("袖" in x for x in P)
    半身 = max(58.0, min(128.0, g["胸围"] / 4 * 3.4))
    半袖 = max(90.0, min(312.0, g["通袖长"] / 2 * 2.45))
    袖厚 = 150.0 if 阔袖 else 92.0
    ys = Y_SHOULDER
    出 = []

    if 只有裙:
        yw = 300.0                                        # 裙腰位置
        y2 = min(Y_MAX, yw + (g["裙长"] or g["衣长"] or 100.0) * K_LEN)
        出.append(f"M{cx-半身*0.86:.0f} {yw:.0f} L{cx+半身*0.86:.0f} {yw:.0f} "
                  f"L{cx+半身*1.62:.0f} {y2:.0f} L{cx-半身*1.62:.0f} {y2:.0f} Z")
        出.append(f"M{cx-半身*0.90:.0f} {yw-16:.0f} L{cx+半身*0.90:.0f} {yw-16:.0f} "
                  f"L{cx+半身*0.86:.0f} {yw:.0f} L{cx-半身*0.86:.0f} {yw:.0f} Z")  # 裙腰
        if "马面" in P:
            出.append(f"M{cx-46} {yw+12:.0f} L{cx+46} {yw+12:.0f} "
                      f"L{cx+54} {y2-8:.0f} L{cx-54} {y2-8:.0f} Z")
        return " ".join(出)

    if 两截:
        上 = g["上襦衣长"] or min(g["衣长"], 62.0)
        y1 = ys + 上 * K_LEN
        y2 = min(Y_MAX, y1 + (g["裙长"] or 100.0) * K_LEN)
        出.append(f"M{cx-半身} {ys} L{cx+半身} {ys} L{cx+半身} {y1:.0f} "
                  f"L{cx-半身} {y1:.0f} Z")                       # 上襦
        出.append(f"M{cx-半身*0.92:.0f} {y1:.0f} L{cx+半身*0.92:.0f} {y1:.0f} "
                  f"L{cx+半身*1.55:.0f} {y2:.0f} L{cx-半身*1.55:.0f} {y2:.0f} Z")  # 裙
        if "马面" in P:                                            # 正面一块马面
            出.append(f"M{cx-44} {y1+10:.0f} L{cx+44} {y1+10:.0f} "
                      f"L{cx+52} {y2-6:.0f} L{cx-52} {y2-6:.0f} Z")
    else:
        yh = min(Y_MAX, ys + g["衣长"] * K_LEN)
        出.append(f"M{cx-半身} {ys} L{cx+半身} {ys} "
                  f"L{cx+半身*1.18:.0f} {yh:.0f} L{cx-半身*1.18:.0f} {yh:.0f} Z")
        if "横襕" in P:                                            # 膝部一道横襕
            ym = ys + (yh - ys) * 0.72
            出.append(f"M{cx-半身*1.10:.0f} {ym:.0f} L{cx+半身*1.10:.0f} {ym:.0f} "
                      f"L{cx+半身*1.13:.0f} {ym+16:.0f} L{cx-半身*1.13:.0f} {ym+16:.0f} Z")

    if not 无袖:
        出.append(f"M{cx-半身} {ys} L{cx-半袖:.0f} {ys+24:.0f} "
                  f"L{cx-半袖:.0f} {ys+袖厚:.0f} L{cx-半身} {ys+袖厚*0.86:.0f} Z")
        出.append(f"M{cx+半身} {ys} L{cx+半袖:.0f} {ys+24:.0f} "
                  f"L{cx+半袖:.0f} {ys+袖厚:.0f} L{cx+半身} {ys+袖厚*0.86:.0f} Z")
    elif "系带" in P:                                              # 抹胸:肩上两条系带
        出.append(f"M{cx-30} {ys-58} L{cx-22} {ys-58} L{cx-14} {ys} L{cx-22} {ys} Z")
        出.append(f"M{cx+22} {ys-58} L{cx+30} {ys-58} L{cx+14} {ys} L{cx+22} {ys} Z")

    ne = _neck(g, cx, ys)
    if ne:
        出.append(ne)
    if "对襟" in g["形制名"] or "对襟" in "".join(P):               # 中缝开到底
        底 = (ys + (g["上襦衣长"] or 60.0) * K_LEN) if 两截 else \
             min(Y_MAX, ys + g["衣长"] * K_LEN)
        出.append(f"M{cx-4} {ys} L{cx+4} {ys} L{cx+4} {底:.0f} L{cx-4} {底:.0f} Z")
    return " ".join(出)


def _shape(cat, name=None):
    c = cat or ""
    for k in ("C010101","C010102","C010103","C010104"):
        if c.startswith(k): return SHAPES[k]
    for k in ("C0102","C0103","C0201","C0401","C0402","C0403","C0404"):
        if c.startswith(k): return SHAPES[k]
    for k in ("C03","C05"):
        if c.startswith(k): return SHAPES[k]
    return SHAPES["C010102"]


PALETTE = ["胭脂","藏青","竹青","月白","缃色","黛","赭","青碧","藕荷","秋香","靛青","玄色","茜色","天青"]


def 商品颜色(spu, sku色):
    """这一款在页面上和图上**实际显示**的颜色名。

    定制品的 SKU 颜色列写的是「定制」,落不到色表 —— 按 SPU 从传统色里挑一个固定的,
    免得 35 个定制品全是同一个兜底色。

    ⚠️ **这条规则原来有两份实现**:这里一份,`backend/draft_check.py` 判
    「钉住的颜色没被挪动」时又抄了一份。而它俩一旦分家,检查会说绿、页面是另一个色 ——
    偏偏这条检查存在的理由就是「图和数据不许对不上」。收成一处。
    """
    if sku色 in ("定制", "默认", "") or sku色 is None:
        return PALETTE[_hue(spu + "c") % len(PALETTE)]
    return sku色


def 各款颜色(conn):
    """每一款实际显示的颜色 —— 给 `fakedata/anchor.py` 当取法用。

    锚定要比的是「**消费方看到的那个值**」,而它常常不是某一列,是算出来的。
    与其在锚文件里用 SQL 把规则重写一遍(那就是第二份实现),不如直接调这里。
    """
    out = {}
    for (spu,) in conn.execute("SELECT spu FROM product"):
        r = conn.execute("SELECT color FROM sku WHERE spu=? ORDER BY code LIMIT 1",
                         (spu,)).fetchone()
        out[spu] = 商品颜色(spu, r[0] if r else None)
    return out


def render(spu, variant):
    nm = spu; kind = ""; cat = ""; color = ""; mts = ""; kfs = ""
    try:
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        r = c.execute("SELECT name,kind,category FROM product WHERE spu=?", (spu,)).fetchone()
        if r: nm, kind, cat = r["name"], r["kind"], r["category"]
        idx = 1
        m = re.match(r"sku(\d+)", variant or "")
        if m: idx = int(m.group(1))
        sk = c.execute("SELECT color FROM sku WHERE spu=? ORDER BY code", (spu,)).fetchall()
        if sk: color = sk[min(idx, len(sk)) - 1]["color"]
        pc = c.execute("SELECT mt_opts,kf_opts FROM product_custom WHERE spu=?", (spu,)).fetchone()
        if pc: mts, kfs = pc["mt_opts"] or "", pc["kf_opts"] or ""
    except Exception:
        pass

    color = 商品颜色(spu, color)
    # ⚠️ **兜底必须也是十六进制。** 原来兜底返回 `hsl(...)` 字符串,
    # 而下一行的 `_mix()` 只认 `#RRGGBB` —— 色表查不到就当场 ValueError,
    # **整张图渲染不出来**。一张颜色不准的图,比一张渲染不出来的图好得多。
    # (根因另修:`sku.color` 原来填的是面料名,见 seed 里那段说明。)
    base = colors().get(color) or colors().get(color.replace("色", "")) \
        or _hsl_hex(_hue(spu), 34, 54)
    lit, dim, deep = _mix(base, .30), _mix(base, -.18), _mix(base, -.42)
    bg = _hue(spu + "bg") % 24 + 32                      # 棚拍底:极低饱和的暖灰
    # 细节图换机位:放大并偏移,像同一件衣服的另一张
    v = variant or "main"
    zoom, dx, dy = (1.0, 0, 0)
    if v.startswith("d"):
        k = int(v[1:] or 1); zoom, dx, dy = (1.35 + .18*k, -40*k, 30*k)
    elif v == "intro": zoom, dx, dy = (.86, 0, -18)

    tex = ""
    if "织金" in kfs or "织金缎" in mts or color == "金":
        tex = "".join('<circle cx="%d" cy="%d" r="2.1" fill="#E8C766" opacity=".55"/>'
                      % (200 + (i*83) % 350, 250 + (i*137) % 320) for i in range(26))
    elif "妆花" in kfs or "云锦" in mts:
        tex = ('<path d="M300 330 q75 -46 150 0 q-75 46 -150 0 Z" fill="%s" opacity=".34"/>'
               '<path d="M300 452 q75 -46 150 0 q-75 46 -150 0 Z" fill="%s" opacity=".26"/>' % (lit, lit))
    elif "纱" in mts or "罗" in mts or "绡" in mts:
        tex = '<rect x="180" y="180" width="390" height="390" fill="#FFFFFF" opacity=".16"/>'

    # **先按形制画,拼不出来再退回品类剪影。**
    # 退回的那 42 个是配饰和面料部件 —— 它们本来就不该有版型,
    # 品类剪影(簪 / 腰封 / 云肩 / 鞋 / 布样)对它们才是对的。
    d = None
    try:
        _c2 = sqlite3.connect(DB); _c2.row_factory = sqlite3.Row
        d = _shape_by_pattern(_c2, spu)
        _c2.close()
    except Exception:
        d = None
    if not d:
        d = _shape(cat, nm)
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" width="750" height="750" viewBox="0 0 750 750">'
      '<desc>合成商品图,非实物照片(由 backend/img.py 按商品属性生成)</desc>'
      '<defs>'
      '<radialGradient id="bg" cx=".5" cy=".38" r=".78">'
      '<stop offset="0" stop-color="hsl(%d,14%%,97%%)"/><stop offset="1" stop-color="hsl(%d,12%%,86%%)"/>'
      '</radialGradient>'
      '<linearGradient id="cl" x1=".18" y1="0" x2=".86" y2="1">'
      '<stop offset="0" stop-color="%s"/><stop offset=".46" stop-color="%s"/>'
      '<stop offset="1" stop-color="%s"/></linearGradient>'
      '<radialGradient id="sh" cx=".5" cy=".5" r=".5">'
      '<stop offset="0" stop-color="#000" stop-opacity=".22"/>'
      '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>'
      '<filter id="sf" x="-25%%" y="-25%%" width="150%%" height="150%%">'
      '<feDropShadow dx="6" dy="14" stdDeviation="16" flood-color="#000" flood-opacity=".2"/></filter>'
      '</defs>'
      '<rect width="750" height="750" fill="url(#bg)"/>'
      '<ellipse cx="375" cy="632" rx="212" ry="42" fill="url(#sh)"/>'
      '<g transform="translate(%d %d) translate(375 400) scale(%.2f) translate(-375 -400)">'
      '<path d="%s" fill="url(#cl)" filter="url(#sf)"/>'
      '<path d="%s" fill="none" stroke="%s" stroke-width="2.4" opacity=".55"/>'
      '%s</g></svg>'
    ) % (bg, bg, lit, base, deep, dx, dy, zoom, d, d, dim, tex)


# ── 栅格化:SVG → PNG ────────────────────────────────────────────────────
# 视觉模型不吃 SVG(Anthropic 只收 png/jpeg/gif/webp),所以要先转成位图。
#
# ⚠️ **这一步依赖 macOS 自带的 qlmanage**,换台 Linux 就没有。
# 没有引入 cairosvg 之类的依赖,是因为这个项目的底线是「无第三方依赖」;
# 但这个取舍要写出来,**不能等别人在别的机器上跑挂了才发现**。
#
# 更要紧的一句:**这批图是合成剪影,不是实物照片。**
#
# ⚠️ **这段话改过一次。** 原来写的是「只画得出上装 / 裙装 / 外套这种粗轮廓,
# **分不出唐制大袖衫和宋制褙子**」。剪影改成按形制的结构参数生成之后
# (见上面 `_shape_by_pattern`),**袖展、衣长、领型、有没有下裙都画出来了** ——
# 大袖衫和褙子现在确实不一样了,那句话不再成立。
#
# 但**仍然不能拿它测「识别准确率」**:多个形制共用同一套几何
# (唐制交领襦裙和晋制交领襦裙的剪影几乎一样),而且图里
# **没有面料质感、没有朝代标记**。变的是「信息不足」的程度,不是这个事实本身。
#
# 它能评测的仍然是另一件事:**信息不足时,模型会不会硬编一个自信的答案。**
import subprocess, shutil, tempfile

CACHE = os.path.join(HERE, ".imgcache")


def png(spu, variant="main", size=750):
    """把商品图渲染成 PNG,返回文件路径。同一个 spu 结果确定,带缓存。"""
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{spu}-{variant}-{size}.png")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    if not shutil.which("qlmanage"):
        raise RuntimeError("找不到 qlmanage —— 本机没有 SVG 栅格化能力。"
                           "这一步依赖 macOS 自带工具,换平台需要另接渲染服务。")
    svg = render(spu, variant)
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, f"{spu}.svg")
        open(f, "w", encoding="utf-8").write(svg)
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", td, f],
                       capture_output=True, timeout=60)
        got = os.path.join(td, f"{spu}.svg.png")
        if not os.path.exists(got):
            raise RuntimeError(f"qlmanage 没能渲染 {spu} —— SVG 可能有问题")
        shutil.copy(got, out)
    return out


if __name__ == "__main__":
    import sys
    print(render(sys.argv[1] if len(sys.argv) > 1 else "lxys_100007919",
                 sys.argv[2] if len(sys.argv) > 2 else "main")[:200])

    # --png:渲染成位图给视觉模型用
    if "--png" in sys.argv:
        _spu = [a for a in sys.argv[1:] if a.startswith("lxys")]
        _p = png(_spu[0] if _spu else "lxys_100617682")
        print(f"{_p}  {os.path.getsize(_p)//1024} KB")
