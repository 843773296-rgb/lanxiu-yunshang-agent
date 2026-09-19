# -*- coding: utf-8 -*-
"""商品平面图 · 第二版原型(不接入系统,只出对比图给用户看)。

和第一版的区别:图上画出来的东西全部来自这件商品自己的数据 ——
面料(锦缎暗纹 / 纱罗半透 / 棉麻织纹 / 丝绸光泽)、工艺(刺绣花样、襕边金带、补子、
珠绣、褶)、缘边。花样种类按商品编号确定性地挑,同形制的几款也不会长一样。
所有纹样都裁在衣服轮廓里面。
"""
import os, re, sys, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import img as V1

DB = os.path.join(ROOT, "backend", "lanxiu.db")

纱类 = ("纱", "罗", "绡", "雪纺", "乔其", "莨")
锦缎 = ("锦", "缎", "妆花", "织金", "缂丝", "提花")
棉麻 = ("棉", "麻", "竹节", "苎")
丝绸 = ("丝", "绸", "绫", "醋酸", "纺")
MOTIFS = ("云纹", "团花", "缠枝", "回纹")
绣色 = {"苏绣": ("#F4D9E4", "#BFD8C8", "#F7EBC8"), "粤绣": ("#E8B84A", "#C0392B", "#F2D06B"),
        "湘绣": ("#E9E2CF", "#7FA37A", "#C4553B"), "蜀绣": ("#F3C6A5", "#6B9E8F", "#E7D18A"),
        "默认": ("#F6E7C8", "#E8B7B0", "#CFE0D0")}


def _bbox(d):
    """只取 M / L 后面的坐标对 —— 弧线(a)的参数里有半径和标志位,当成坐标会把范围算错
    (第一版就这么错的:圆领袍的补子被画到了衣服外面,又被裁掉,图上什么都没有)"""
    pts = [(float(a), float(b)) for a, b in re.findall(r"[ML]\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", d)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _motif(kind, c1, c2, s=1.0):
    """一个单位纹样(以 0,0 为中心)"""
    if kind == "云纹":
        return (f'<path d="M{-18*s} 0 q{9*s} {-14*s} {18*s} 0 q{9*s} {-14*s} {18*s} 0" '
                f'fill="none" stroke="{c1}" stroke-width="{2.2*s:.1f}" stroke-linecap="round"/>'
                f'<circle cx="{-18*s}" cy="{3*s}" r="{3*s}" fill="none" stroke="{c1}" stroke-width="{1.6*s:.1f}"/>')
    if kind == "团花":
        petals = "".join(f'<ellipse cx="0" cy="{-9*s}" rx="{4.5*s}" ry="{8*s}" fill="{c1}" '
                         f'transform="rotate({a})"/>' for a in range(0, 360, 45))
        return petals + f'<circle r="{4.5*s}" fill="{c2}"/>'
    if kind == "缠枝":
        return (f'<path d="M{-20*s} {8*s} C{-8*s} {-16*s} {8*s} {16*s} {20*s} {-8*s}" fill="none" '
                f'stroke="{c1}" stroke-width="{2*s:.1f}"/>'
                f'<ellipse cx="{-6*s}" cy="{-4*s}" rx="{4*s}" ry="{7*s}" fill="{c2}" transform="rotate(-35)"/>'
                f'<ellipse cx="{8*s}" cy="{5*s}" rx="{4*s}" ry="{7*s}" fill="{c2}" transform="rotate(40)"/>')
    # 回纹
    return (f'<path d="M{-12*s} {12*s} V{-12*s} H{12*s} V{6*s} H{-6*s} V{-6*s} H{6*s}" fill="none" '
            f'stroke="{c1}" stroke-width="{2*s:.1f}"/>')


def _spray(cx, cy, s, cols):
    """一枝刺绣花样:花 + 叶 + 枝"""
    a, b, c = cols
    out = [f'<path d="M{cx} {cy+40*s} C{cx-10*s} {cy+10*s} {cx+14*s} {cy-6*s} {cx+4*s} {cy-30*s}" '
           f'fill="none" stroke="{b}" stroke-width="{3*s:.1f}"/>']
    for dx, dy, r in ((-14, 8, 11), (10, -16, 13), (4, -34, 9)):
        x, y = cx + dx*s, cy + dy*s
        out += [f'<ellipse cx="{x}" cy="{y-r*s*.6}" rx="{r*s*.55}" ry="{r*s*.9}" fill="{a}" '
                f'transform="rotate({a2} {x} {y})"/>' for a2 in range(0, 360, 60)]
        out.append(f'<circle cx="{x}" cy="{y}" r="{r*s*.35}" fill="{c}"/>')
    for dx, dy, ang in ((-16, 26, -40), (12, 14, 35)):
        x, y = cx + dx*s, cy + dy*s
        out.append(f'<ellipse cx="{x}" cy="{y}" rx="{6*s}" ry="{13*s}" fill="{b}" '
                   f'transform="rotate({ang} {x} {y})"/>')
    return "".join(out)


def features(spu):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    p = c.execute("SELECT name,kind,category,pattern FROM product WHERE spu=?", (spu,)).fetchone()
    pc = c.execute("SELECT mt_opts,kf_opts FROM product_custom WHERE spu=?", (spu,)).fetchone()
    mts = (pc["mt_opts"] if pc else "") or ""
    kfs = (pc["kf_opts"] if pc else "") or ""
    t = p["name"] + " " + mts + " " + kfs
    fab = ("纱" if any(k in t for k in 纱类) else "锦" if any(k in t for k in 锦缎)
           else "棉" if any(k in t for k in 棉麻) else "丝" if any(k in t for k in 丝绸) else "")
    绣 = next((k for k in ("苏绣", "粤绣", "湘绣", "蜀绣") if k in t), "默认" if "绣" in t else None)
    return dict(name=p["name"], text=t, fab=fab, 绣=绣,
                满工=any(k in t for k in ("满工", "重工", "婚服")),
                襕=("双襕" in t and 2) or ("襕" in t and 1) or 0,
                金=("金" in t), 补子=("补子" in t), 珠=any(k in t for k in ("珠绣", "钉珠", "缀珠")),
                褶=any(k in t for k in ("马面", "百迭", "褶")), 团花=("团花" in t))


def render(spu, variant="main"):
    base_svg = V1.render(spu, variant)          # 拿第一版的颜色、背景、机位
    # 去掉第一版的质感层(撒金点 / 妆花两片 / 纱罗白罩)—— 它们没裁在衣服轮廓里,会画到衣服外面
    base_svg = re.sub(r'<circle cx="\d+" cy="\d+" r="2.1" fill="#E8C766" opacity=".55"/>', "", base_svg)
    base_svg = re.sub(r'<path d="M300 (?:330|452) q75 -46 150 0 q-75 46 -150 0 Z"[^>]*/>', "", base_svg)
    base_svg = base_svg.replace('<rect x="180" y="180" width="390" height="390" fill="#FFFFFF" opacity=".16"/>', "")
    f = features(spu)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    d = V1._shape_by_pattern(c, spu) or V1._shape(
        (c.execute("SELECT category FROM product WHERE spu=?", (spu,)).fetchone() or [""])[0])
    x0, y0, x1, y1 = _bbox(d)
    h = V1._hue(spu)
    motif = MOTIFS[h % len(MOTIFS)] if not f["团花"] else "团花"
    base = re.search(r'stop-color="(#[0-9A-F]{6})"/><stop offset=".46" stop-color="(#[0-9A-F]{6})"',
                     base_svg)
    lit, mid = base.group(1), base.group(2)
    deep = V1._mix(mid, -.45)
    gold = "#D8B24A"
    layers = []
    # ① 面料质感
    if f["fab"] == "锦":
        s = 0.9 + (h % 5) * 0.12
        cell = int(64 * s)
        layers.append(f'<pattern id="br" width="{cell}" height="{cell}" patternUnits="userSpaceOnUse">'
                      f'<g transform="translate({cell/2} {cell/2})" opacity=".42">'
                      f'{_motif(motif, V1._mix(mid, .38), V1._mix(mid, .18), s)}</g></pattern>'
                      f'<rect x="0" y="0" width="750" height="750" fill="url(#br)"/>')
    elif f["fab"] == "棉":
        layers.append('<pattern id="wv" width="6" height="6" patternUnits="userSpaceOnUse">'
                      f'<path d="M0 3 H6 M3 0 V6" stroke="{deep}" stroke-width=".7" opacity=".28"/></pattern>'
                      '<rect width="750" height="750" fill="url(#wv)"/>')
    elif f["fab"] == "纱":
        layers.append('<pattern id="gz" width="4" height="4" patternUnits="userSpaceOnUse">'
                      '<path d="M0 0 L4 4 M4 0 L0 4" stroke="#FFFFFF" stroke-width=".5" opacity=".5"/></pattern>'
                      '<rect width="750" height="750" fill="url(#gz)"/>')
    if f["fab"] in ("丝", "锦", ""):
        layers.append('<linearGradient id="gl" x1="0" y1="0" x2="1" y2="1">'
                      '<stop offset=".35" stop-color="#FFF" stop-opacity="0"/>'
                      '<stop offset=".5" stop-color="#FFF" stop-opacity=".22"/>'
                      '<stop offset=".62" stop-color="#FFF" stop-opacity="0"/></linearGradient>'
                      '<rect width="750" height="750" fill="url(#gl)"/>')
    # ② 褶(马面 / 百迭)
    if f["褶"]:
        top = 300 if y0 >= 280 else y0 + (y1 - y0) * 0.35
        n = 14 + h % 6
        layers.append("".join(
            f'<path d="M{x0 + (x1-x0)*i/n:.0f} {top:.0f} L{x0 + (x1-x0)*i/n + (i-n/2)*3:.0f} {y1:.0f}" '
            f'stroke="{deep}" stroke-width="1.6" opacity=".35"/>' for i in range(1, n)))
    # ③ 襕边:下摆金带
    for k in range(f["襕"]):
        yb = y1 - 26 - k * 46
        layers.append(f'<rect x="{x0}" y="{yb-22}" width="{x1-x0}" height="22" fill="{gold}" opacity=".92"/>'
                      + "".join(f'<g transform="translate({x} {yb-11})">{_motif(motif, "#8A5A12", "#F4DE8A", .45)}</g>'
                                for x in range(int(x0) + 18, int(x1), 36)))
    # ④ 刺绣花样
    if f["绣"]:
        cols = 绣色[f["绣"]]
        # 有补子时胸前让给补子,刺绣挪到下摆 —— 两样叠在一起哪样都看不清
        cx, cy = 375, y0 + (y1 - y0) * (0.55 if f["褶"] else 0.72 if f["补子"] else 0.34)
        spots = [(cx, cy, 1.25)]
        if f["满工"]:
            spots += [(cx - (x1-x0)*0.28, cy + 90, 0.9), (cx + (x1-x0)*0.28, cy + 60, 0.95),
                      (cx - (x1-x0)*0.18, cy + 190, 0.8), (cx + (x1-x0)*0.2, cy + 200, 0.85)]
        for sx, sy, ss in spots:
            layers.append(_spray(sx, sy, ss, cols))
            if f["金"]:
                layers.append(f'<circle cx="{sx}" cy="{sy-10}" r="{48*ss}" fill="none" stroke="{gold}" '
                              f'stroke-width="2" stroke-dasharray="3 5" opacity=".8"/>')
    # ⑤ 补子
    if f["补子"]:
        bx, by = 375, y0 + 150
        layers.append(f'<rect x="{bx-52}" y="{by-52}" width="104" height="104" fill="{V1._mix(mid,-.25)}" '
                      f'stroke="{gold}" stroke-width="4"/>'
                      f'<g transform="translate({bx} {by})">{_motif("团花", gold, "#F4DE8A", 2.2)}</g>')
    # ⑥ 珠绣:下摆一排珠
    if f["珠"]:
        layers.append("".join(f'<circle cx="{x}" cy="{y1-10}" r="4" fill="#FDFBF4" stroke="#C9C1AE" stroke-width=".8"/>'
                              for x in range(int(x0) + 10, int(x1), 16)))
    clip = f'<clipPath id="cp"><path d="{d}"/></clipPath>'
    deco = f'<g clip-path="url(#cp)">{"".join(layers)}</g>'
    trim = f'<path d="{d}" fill="none" stroke="{deep}" stroke-width="5" opacity=".7"/>'
    # 纱类整件半透
    if f["fab"] == "纱":
        base_svg = base_svg.replace('fill="url(#cl)" filter="url(#sf)"',
                                    'fill="url(#cl)" filter="url(#sf)" fill-opacity=".78"')
    # 插到第一版衣服那一组(g)的末尾:沿用它的机位变换
    i = base_svg.rindex("</g></svg>")
    return base_svg[:i] + clip + deco + trim + base_svg[i:]


if __name__ == "__main__":
    import subprocess, base64, html, tempfile
    out = sys.argv[1]
    spus = sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    rows = []
    for spu in spus:
        pair = []
        for tag, fn in (("v1", V1.render), ("v2", render)):
            svgp = os.path.join(out, f"{spu}-{tag}.svg")
            open(svgp, "w").write(fn(spu, "main"))
            subprocess.run(["qlmanage", "-t", "-s", "420", "-o", out, svgp], capture_output=True)
            pair.append(base64.b64encode(open(svgp + ".png", "rb").read()).decode())
        f = features(spu)
        rows.append((f["name"], pair,
                     "、".join(x for x in (f["fab"] and {"锦": "锦缎暗纹", "纱": "纱罗半透", "棉": "棉麻织纹", "丝": "丝绸光泽"}[f["fab"]],
                                            f["绣"] and f"{f['绣'] if f['绣'] != '默认' else ''}刺绣" + ("(满工)" if f["满工"] else ""),
                                            f["襕"] and f"襕边×{f['襕']}", f["补子"] and "补子", f["珠"] and "珠绣",
                                            f["褶"] and "褶") if x)))
    page = ['<meta charset="utf-8"><title>商品平面图 · 新旧对比</title>'
            '<style>body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f6f4ef;margin:0;padding:24px;color:#2b2723}'
            'h1{font-size:20px}p{color:#6b645b;font-size:13px;max-width:880px}'
            '.row{display:flex;gap:16px;align-items:center;background:#fff;border-radius:10px;padding:14px;margin:12px 0;flex-wrap:wrap}'
            '.row img{width:240px;height:240px;border-radius:8px;border:1px solid #eee}'
            '.lab{font-size:12px;color:#8a8278;text-align:center}.info{min-width:220px;flex:1}'
            '.info b{font-size:15px}.tag{font-size:12px;color:#7a5c2e;margin-top:6px}</style>'
            '<h1>商品平面图 · 新旧对比(原型,未接入系统)</h1>'
            '<p>左边是现在系统里的图,右边是新版原型。新版图上画的每一样东西都来自这款商品自己的数据'
            '(面料、工艺、形制)—— 图上有襕边,这款就真的有襕边。</p>']
    for nm, (a, b), tags in rows:
        page.append(f'<div class="row"><div><img src="data:image/png;base64,{a}"><div class="lab">现在</div></div>'
                    f'<div><img src="data:image/png;base64,{b}"><div class="lab">新版原型</div></div>'
                    f'<div class="info"><b>{html.escape(nm)}</b><div class="tag">画上去的:{html.escape(tags) or "(无特殊工艺)"}</div></div></div>')
    open(os.path.join(out, "对比.html"), "w").write("".join(page))
    print(os.path.join(out, "对比.html"))
