#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打版图:给一个版型和号型,按 GB/T 29863-2023《服装制图》的线型与标注画出每一片裁片。

    python3 tools/patterndraw/draft.py <spu 或 版型编码> [号型=M] [输出.svg]

规范依据见同目录 `制版规范.md`。**这不是版师画的图,是按公式从库里的尺寸推出来的初版** ——
公式写在图上(版师能逐条驳),数据推出不合理的值时在图上打警告,不静默画一张看着很对的图。

马面裙有专画(襕位、绣位、褶位都画出来);其余形制按 `pattern_piece` 登记的裁片清单画,
库里没登记裁片的版型报「画不了」,**不猜**。系统里走 `render()`,后台 `/pattern/<版型>-<号型>.svg`。
"""
import os, sys, sqlite3, math, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(ROOT, "backend", "lanxiu.db")

# ── 线型(GB/T 29863-2023 表 2)。图纸单位 mm,细线 0.25、粗线 0.6(细线的 2.4 倍)──
THIN, THICK = 0.25, 0.6
S = 2.0            # 1 cm 实物 = 2 mm 图面 → 比例 1:5(A3 横向打印时)
缝份 = dict(边=1.0, 下摆=3.0, 腰=1.0)   # cm。汉服下摆 2–3,平缝 1


def cm(v):
    return v * S


class Sheet:
    def __init__(self, w=420, h=297):
        self.w, self.h, self.el = w, h, []

    def line(self, x1, y1, x2, y2, kind="thin"):
        st = {"thin": f'stroke-width="{THIN}"', "thick": f'stroke-width="{THICK}"',
              "dash": f'stroke-width="{THIN}" stroke-dasharray="2 1.2"',            # 细虚线:明线 / 等分
              "dashthick": f'stroke-width="{THICK}" stroke-dasharray="3 1.5"',      # 粗虚线:下层轮廓
              "dashdot": f'stroke-width="{THIN}" stroke-dasharray="4 1 0.6 1"'}[kind]  # 点划线:对折
        self.el.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#1d1d1f" {st}/>')

    def rect(self, x, y, w, h, kind="thick"):
        for a in ((x, y, x + w, y), (x + w, y, x + w, y + h), (x + w, y + h, x, y + h), (x, y + h, x, y)):
            self.line(*a, kind=kind)

    def text(self, x, y, s, size=2.6, anchor="start", bold=False, color="#1d1d1f"):
        self.el.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" '
                       f'font-family="PingFang SC, Heiti SC, sans-serif" fill="{color}"'
                       f'{" font-weight=\"600\"" if bold else ""}>{s}</text>')

    def grain(self, x, y1, y2):
        """布纹线:经向、双箭头(无倒顺)"""
        self.line(x, y1, x, y2, "thin")
        for yy, d in ((y1, 1), (y2, -1)):
            self.el.append(f'<path d="M{x-1.2:.2f} {yy+2.2*d:.2f} L{x:.2f} {yy:.2f} L{x+1.2:.2f} {yy+2.2*d:.2f}" '
                           f'fill="none" stroke="#1d1d1f" stroke-width="{THIN}"/>')

    def notch(self, x, y, horizontal_edge=True, n=1):
        """剪口:垂直于边、深 0.5 cm;前一个,后两个(间距 1 cm)"""
        for k in range(n):
            o = cm(k * 1.0)
            if horizontal_edge:
                self.line(x + o, y, x + o, y + cm(0.5), "thick")
            else:
                self.line(x, y + o, x + cm(0.5), y + o, "thick")

    def dim(self, x1, y1, x2, y2, label, off=6):
        """尺寸线:细实线 + 箭头,数值居中;尺寸线不压结构线(往外偏 off)"""
        if abs(y1 - y2) < 1e-6:            # 水平
            y = y1 - off
            self.line(x1, y1, x1, y - 1.5); self.line(x2, y2, x2, y - 1.5)
            self.line(x1, y, x2, y)
            for xx, d in ((x1, 1), (x2, -1)):
                self.el.append(f'<path d="M{xx:.2f} {y:.2f} l{2*d} -0.8 l0 1.6 Z" fill="#1d1d1f"/>')
            self.text((x1 + x2) / 2, y - 1, label, 2.4, "middle")
        else:                               # 竖直
            x = x1 - off
            self.line(x1, y1, x - 1.5, y1); self.line(x2, y2, x - 1.5, y2)
            self.line(x, y1, x, y2)
            for yy, d in ((y1, 1), (y2, -1)):
                self.el.append(f'<path d="M{x:.2f} {yy:.2f} l-0.8 {2*d} l1.6 0 Z" fill="#1d1d1f"/>')
            self.el.append(f'<text x="{x-1.2:.2f}" y="{(y1+y2)/2:.2f}" font-size="2.4" text-anchor="middle" '
                           f'font-family="PingFang SC, sans-serif" transform="rotate(-90 {x-1.2:.2f} {(y1+y2)/2:.2f})">{label}</text>')

    def svg(self):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}mm" height="{self.h}mm" '
                f'viewBox="0 0 {self.w} {self.h}"><rect width="{self.w}" height="{self.h}" fill="#fff"/>'
                + "".join(self.el) + "</svg>")


def 裁片(sh, x, y, w_cm, h_cm, 名, 数量, 面料, 款号, 号型, sa=None, fold=None, grain=True):
    """画一片矩形裁片:外圈毛样(粗实线)、内圈净样(细实线)、布纹线、标注。返回净样框(mm)。
    sa:四边缝份 cm(上、右、下、左);fold:哪条边是对折边('left'…),对折边不加缝份、画点划线"""
    t, r, b, l = sa or (缝份["边"],) * 4
    if fold == "left":
        l = 0
    W, H = cm(w_cm + l + r), cm(h_cm + t + b)
    sh.rect(x, y, W, H, "thick")                                           # 毛样(裁剪线)
    nx, ny, nw, nh = x + cm(l), y + cm(t), cm(w_cm), cm(h_cm)
    sh.rect(nx, ny, nw, nh, "thin")                                         # 净样(完成线)
    if fold == "left":
        sh.line(x, y, x, y + H, "dashdot")
        sh.text(x + 1.5, y + H / 2, "对折", 2.4)
    if grain:
        sh.grain(nx + nw * 0.72, ny + nh * 0.15, ny + nh * 0.85)
    cx = nx + nw / 2
    ty = ny + nh * 0.38
    # 标注垫白底 —— 压在褶位线上时字看不清(第一版就是)
    bw = max(len(名) * 3.6, len(f"{面料} ×{数量}") * 2.7, 24)
    sh.el.append(f'<rect x="{cx-bw/2:.2f}" y="{ty-4.2:.2f}" width="{bw:.2f}" height="14" fill="#fff" opacity=".92"/>')
    sh.text(cx, ty, 名, 3.4, "middle", True)
    sh.text(cx, ty + 4.6, f"{面料} ×{数量}", 2.6, "middle")
    sh.text(cx, ty + 8.4, f"{号型}  {款号}", 2.2, "middle", color="#555")
    return nx, ny, nw, nh


def 取数(key, size):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    if key.startswith("PT"):
        pt, p = key, None
    else:
        p = c.execute("SELECT * FROM product WHERE spu=?", (key,)).fetchone()
        if not p:
            raise SystemExit(f"找不到商品 {key}")
        pt = p["pattern"]
    ptn = c.execute("SELECT p.*, z.name xzn FROM pattern p LEFT JOIN xingzhi z ON z.code=p.xz "
                    "WHERE p.code=?", (pt,)).fetchone()
    # 查不到就**明说查不到**。不加这一句时,下一行 dict(None) 抛的是 TypeError,
    # 调用方看到的是「NoneType is not iterable」—— 那句话不告诉任何人「这个版型库里没有」。
    if not ptn:
        raise ValueError(f"库里没有这个版型:{pt}")
    spec = {r["item"]: r["value"] for r in c.execute(
        "SELECT item,value FROM size_spec WHERE pattern=? AND size=?", (pt, size))}
    pieces = [dict(r) for r in c.execute("SELECT name,qty,note FROM pattern_piece WHERE pattern=?", (pt,))]
    pc = p and c.execute("SELECT mt_opts,kf_opts FROM product_custom WHERE spu=?", (p["spu"],)).fetchone()
    return dict(product=p and dict(p), pattern=dict(ptn), spec=spec, pieces=pieces,
                mt=(pc["mt_opts"].split(",")[0] if pc and pc["mt_opts"] else "面料"),
                kf=(pc["kf_opts"] if pc else "") or "")


# ── 纹样(定位纹样 / 襕纹 / 绣样)────────────────────────────────────────
# 用户 2026-09-19:「你没有把花纹纹样表示出来」。织金襕和刺绣是这类款的卖点,
# 打版图只画两道虚线框,版师和织造、绣工都不知道织什么、绣哪、绣多大。
# 行业里叫「定位纹样」:画出纹样线稿 + 纹样名 + 循环尺寸 / 外框尺寸 + 离边距离。
# **纹样种类和商品图用同一个挑法**(backend/img.py 的 _hue 按款号定),图和版对得上。
纹样色 = "#8a5a12"
MOTIFS = ("云纹", "团花", "缠枝", "回纹")
纹样全名 = {"云纹": "如意云纹", "团花": "团花", "缠枝": "缠枝莲", "回纹": "回纹"}


def _纹样种(key, 名称):
    if "团花" in 名称:
        return "团花"
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    import img as _img
    return MOTIFS[_img._hue(key) % len(MOTIFS)]


def _单元(kind, x, y, u):
    """一个纹样单元的线稿(只描线),中心 (x,y),单元尺寸 u(mm)。"""
    k = u / 20.0
    if kind == "云纹":
        return (f'<path d="M{x-9*k:.2f} {y+2*k:.2f} q{4.5*k:.2f} {-8*k:.2f} {9*k:.2f} 0 q{4.5*k:.2f} {-8*k:.2f} {9*k:.2f} 0 '
                f'q{3*k:.2f} {5*k:.2f} {-2*k:.2f} {6*k:.2f}"/><circle cx="{x-9*k:.2f}" cy="{y+4.5*k:.2f}" r="{2.4*k:.2f}"/>')
    if kind == "团花":
        pet = "".join(f'<ellipse cx="{x:.2f}" cy="{y-5.2*k:.2f}" rx="{2.6*k:.2f}" ry="{4.6*k:.2f}" '
                      f'transform="rotate({a} {x:.2f} {y:.2f})"/>' for a in range(0, 360, 45))
        return pet + f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{2.6*k:.2f}"/><circle cx="{x:.2f}" cy="{y:.2f}" r="{9.5*k:.2f}"/>'
    if kind == "缠枝":
        return (f'<path d="M{x-10*k:.2f} {y+3*k:.2f} C{x-5*k:.2f} {y-9*k:.2f} {x+5*k:.2f} {y+9*k:.2f} {x+10*k:.2f} {y-3*k:.2f}"/>'
                f'<ellipse cx="{x-3*k:.2f}" cy="{y-3*k:.2f}" rx="{2.2*k:.2f}" ry="{4*k:.2f}" transform="rotate(-35 {x-3*k:.2f} {y-3*k:.2f})"/>'
                f'<ellipse cx="{x+4*k:.2f}" cy="{y+3*k:.2f}" rx="{2.2*k:.2f}" ry="{4*k:.2f}" transform="rotate(40 {x+4*k:.2f} {y+3*k:.2f})"/>'
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{1.8*k:.2f}"/>')
    return (f'<path d="M{x-7*k:.2f} {y+7*k:.2f} V{y-7*k:.2f} H{x+7*k:.2f} V{y+4*k:.2f} H{x-3.5*k:.2f} '
            f'V{y-3.5*k:.2f} H{x+3.5*k:.2f}"/>')


def 画襕(sh, x, y, w, h, kind, 循环, 名, cid):
    """一条织金襕:上下边线(细实线)+ 纹样按循环排满 + 标注。x,y,w,h 都是图面 mm。"""
    sh.el.append(f'<clipPath id="{cid}"><rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/></clipPath>')
    sh.el.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#f7eed9"/>')
    sh.line(x, y, x + w, y, "thin"); sh.line(x, y + h, x + w, y + h, "thin")
    step = cm(循环)
    units = "".join(_单元(kind, x + step / 2 + i * step, y + h / 2, min(step, h) * 0.9)
                    for i in range(int(w / step) + 2))
    sh.el.append(f'<g clip-path="url(#{cid})" fill="none" stroke="{纹样色}" stroke-width="{THIN}">{units}</g>')
    lab = f"{名} · 织金{纹样全名[kind]} · 带高 {h / S:g} · 循环 {循环:g}"
    tw = len(lab) * 2.25
    sh.el.append(f'<rect x="{x + w / 2 - tw / 2:.2f}" y="{y + h / 2 - 2.4:.2f}" width="{tw:.2f}" height="3.6" fill="#fff" opacity=".9"/>')
    sh.text(x + w / 2, y + h / 2 + 0.6, lab, 2.1, "middle", color=纹样色)


def 绣样(sh, cx, y0, w, h, 名):
    """绣花定位:细虚线外框 + 折枝花线稿 + 外框尺寸 + 标注。"""
    x0 = cx - w / 2
    sh.rect(x0, y0, w, h, "dash")
    k = min(w, h) / 40.0
    cy = y0 + h * 0.55
    art = [f'<path d="M{cx:.2f} {cy+16*k:.2f} C{cx-4*k:.2f} {cy+4*k:.2f} {cx+6*k:.2f} {cy-2*k:.2f} {cx+2*k:.2f} {cy-12*k:.2f}"/>']
    for dx, dy, r in ((-6, 3, 4.5), (4, -6, 5.5), (2, -14, 3.8)):
        px, py = cx + dx * k, cy + dy * k
        art += [f'<ellipse cx="{px:.2f}" cy="{py - r*k*.6:.2f}" rx="{r*k*.5:.2f}" ry="{r*k*.85:.2f}" '
                f'transform="rotate({a} {px:.2f} {py:.2f})"/>' for a in range(0, 360, 60)]
        art.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{r*k*.3:.2f}"/>')
    for dx, dy, ang in ((-7, 10, -40), (5, 6, 35)):
        px, py = cx + dx * k, cy + dy * k
        art.append(f'<ellipse cx="{px:.2f}" cy="{py:.2f}" rx="{2.4*k:.2f}" ry="{5.2*k:.2f}" transform="rotate({ang} {px:.2f} {py:.2f})"/>')
    sh.el.append(f'<g fill="none" stroke="{纹样色}" stroke-width="{THIN}">{"".join(art)}</g>')
    sh.text(cx, y0 - 1.4, f"{名}定位 · 折枝花 · {w / S:g}×{h / S:g} · 居中", 2.1, "middle", color=纹样色)


# ── 马面裙 ─────────────────────────────────────────────────────────────
# 公式(来源:研究结论 §五,**来源互相矛盾处照实写**):
#   每侧褶区成品宽 P = (W − 2B) / 2         W 成品腰围,B 马面宽
#   褶数 n = P / 褶面宽(取 3 cm 左右),褶深 C = 褶面宽 × 1.5
#   褶裥片展开宽 = P + n × 2C                (顺褶:每个褶吃进 2 倍褶深)
#   裙腰长 = W + B(搭叠一个裙门),成品高 6 cm、对折裁
# 褶的倒向来源没有统一说法 —— 图上只标「褶位」和倒向**待版师定**,不硬编。
def draft_mamian(d, size):
    sp = d["spec"]
    W, L, B = sp.get("腰围"), sp.get("裙长"), sp.get("马面宽")
    if not (W and L and B):
        raise SystemExit(f"版型 {d['pattern']['code']} {size} 码缺腰围 / 裙长 / 马面宽,画不了")
    警告 = []
    腰高 = 6.0
    身长 = L - 腰高
    P = (W - 2 * B) / 2
    if P < 8:
        警告.append(f"按公式每侧褶区只剩 {P:.1f} cm(W−2B)/2 —— 库里马面宽 {B:.0f} 相对腰围 {W:.0f} 偏大"
                   f"(行业常见 20–24);褶区至少要盖住身体两侧。**请版师核马面宽**,图照数据画")
    面宽 = 3.0
    n = max(2, round(max(P, 6) / 面宽))
    C = 面宽 * 1.5
    展开 = max(P, 6) + n * 2 * C
    款号 = d["product"]["spu"][-6:] if d["product"] else d["pattern"]["code"]
    名称 = d["product"]["name"] if d["product"] else d["pattern"]["name"]
    面料 = d["mt"]
    襕 = 2 if "双襕" in 名称 else (1 if "襕" in 名称 or "织金" in d["kf"] else 0)

    sh = Sheet()
    sh.rect(5, 5, 410, 287, "thick")                                    # 图框
    x = 18
    # ① 马面 ×2(前后各一,光面不打褶)
    nx, ny, nw, nh = 裁片(sh, x, 24, B, 身长, "马面", 2, 面料, 款号, size,
                         sa=(缝份["腰"], 缝份["边"], 缝份["下摆"], 缝份["边"]))
    sh.dim(nx, ny, nx + nw, ny, f"B={B:g}", off=8)
    sh.dim(nx, ny, nx, ny + nh, f"L−腰高={身长:g}", off=8)
    sh.notch(nx + nw / 2, ny - cm(缝份["腰"]), True, 1)                  # 中点对位(前一个剪口)
    纹 = _纹样种(d["product"]["spu"] if d["product"] else d["pattern"]["code"], 名称)
    循环 = 8.0
    for k in range(襕):                                                 # 襕:膝襕 / 底襕,画出纹样
        yb = ny + nh - cm(10 + k * 32)
        hb = cm(8)
        画襕(sh, nx, yb - hb, nw, hb, 纹, 循环, ["底襕", "膝襕"][k], f"lan_m{k}")
        sh.dim(nx + nw, yb, nx + nw, ny + nh, f"{10 + k * 32:g}", off=-6)
    if "绣" in d["kf"]:                                                 # 刺绣定位:马面正中
        绣名 = next((w for w in ("苏绣", "粤绣", "湘绣", "蜀绣") if w in d["kf"]), "刺绣")
        bw, bh = min(B - 8, 20), 24
        绣样(sh, nx + nw / 2, ny + cm(8), cm(bw), cm(bh), 绣名)
        sh.dim(nx + nw, ny, nx + nw, ny + cm(8), "8", off=-6)
    x = nx + nw + cm(缝份["边"]) + 16
    # ② 褶裥片 ×2(左右裙门之间)
    px, py, pw, ph = 裁片(sh, x, 24, 展开, 身长, "褶裥片", 2, 面料, 款号, size,
                         sa=(缝份["腰"], 缝份["边"], 缝份["下摆"], 缝份["边"]))
    sh.dim(px, py, px + pw, py, f"展开 {展开:.1f}", off=8)
    for k in range(n):                                                  # 褶位:斜线表示倒向
        x0 = px + cm(max(P, 6) / n * 0.5 + k * (max(P, 6) / n + 2 * C))
        sh.line(x0, py, x0, py + ph, "dash")
        sh.line(x0 + cm(2 * C), py, x0 + cm(2 * C), py + ph, "dash")
        for yy in (py + 6, py + ph - 10):
            sh.line(x0 + 1, yy + 3, x0 + cm(2 * C) - 1, yy, "thin")
    sh.text(px + pw / 2, py + ph + cm(缝份["下摆"]) + 5, f"褶 {n} 个 · 褶面 {面宽:g} · 褶深 {C:g}(倒向待版师定)",
            2.4, "middle")
    for k in range(襕):          # 织金襕是织在布上的,横跨整条裙 —— 褶裥片上同一高度也要有
        yb = py + ph - cm(10 + k * 32)
        画襕(sh, px, yb - cm(8), pw, cm(8), 纹, 循环, ["底襕", "膝襕"][k], f"lan_p{k}")
    # ③ 裙腰 ×1(对折裁)④ 系带 ×2
    yx = py + ph + cm(缝份["下摆"]) + 14
    腰长 = W + B
    wx, wy, ww, wh = 裁片(sh, 18, yx, 腰长, 腰高 * 2, "裙腰", 1, "白棉布", 款号, size, grain=False)
    sh.line(wx, wy + wh / 2, wx + ww * 0.3, wy + wh / 2, "dashdot")      # 对折线让开中间的标注
    sh.line(wx + ww * 0.7, wy + wh / 2, wx + ww, wy + wh / 2, "dashdot")
    sh.text(wx + 3, wy + wh / 2 - 1, "对折", 2.2)
    sh.dim(wx, wy + wh, wx + ww, wy + wh, f"W+B={腰长:g}", off=-9)
    tx = 18
    ty = wy + wh + cm(1) + 16
    裁片(sh, tx, ty, 100, 3 * 2, "系带", 2, "白棉布", 款号, size, grain=False)

    # 标题栏 + 规格表 + 图例 + 警告
    bx, by = 290, 212
    sh.rect(bx, by, 120, 75, "thick")
    rows = [("款名", 名称), ("款号 / 版型", f"{款号} / {d['pattern']['code']} v{d['pattern'].get('version') or 1}"),
            ("号型", size), ("比例", "1:5(A3 横向)  单位 cm"),
            ("规格", f"腰围 W {W:g} · 裙长 L {L:g} · 马面宽 B {B:g}"),
            ("公式", "褶区 P=(W−2B)/2 · 展开=P+n·2C · 腰长=W+B"),
            ("制图", f"系统按公式初版 · {dt.date.today().isoformat()} · 复核:____")]
    for i, (k, v) in enumerate(rows):
        yy = by + 9 + i * 9.6
        sh.text(bx + 3, yy, k, 2.6, bold=True)
        sh.text(bx + 30, yy, v, 2.5)
        if i:
            sh.line(bx, yy - 6.6, bx + 120, yy - 6.6, "thin")
    lx, ly = 290, 150
    sh.text(lx, ly, "图例", 2.8, bold=True)
    for i, (k, lab) in enumerate((("thick", "毛样(裁剪线,含缝份)"), ("thin", "净样(完成线)"),
                                  ("dash", "褶位 / 襕位"), ("dashdot", "对折线"))):
        yy = ly + 5 + i * 5
        sh.line(lx, yy - 0.8, lx + 12, yy - 0.8, k); sh.text(lx + 15, yy, lab, 2.4)
    sh.grain(lx + 6, ly + 26, ly + 36); sh.text(lx + 15, ly + 32, "布纹线(经向,双箭头=无倒顺)", 2.4)
    sh.text(lx, ly + 44, f"缝份:边 {缝份['边']:g} · 腰 {缝份['腰']:g} · 下摆 {缝份['下摆']:g}", 2.4)
    if 襕:                       # 这一款没有襕就别在图例里立一条 —— 图例要和图上真有的东西对上
        sh.el.append(f'<rect x="{lx}" y="{ly + 48}" width="12" height="4" fill="#f7eed9" stroke="{纹样色}" stroke-width="{THIN}"/>')
        sh.text(lx + 15, ly + 51, f"织金襕(纹样按循环排满,织造前定)· 本款:{纹样全名[纹]}", 2.4)
    if "绣" in d["kf"]:
        sh.rect(lx, ly + 55, 12, 4, "dash")
        sh.text(lx + 15, ly + 58, "绣花定位框(框内线稿为绣样示意)", 2.4)
    if 警告:
        wy0 = 18
        sh.el.append(f'<rect x="{bx}" y="{wy0}" width="120" height="{12 + 5.2 * len(警告) * 3}" fill="#fff4e5" stroke="#d97706" stroke-width="{THIN}"/>')
        sh.text(bx + 3, wy0 + 6, "⚠ 数据核对", 2.8, bold=True, color="#b45309")
        for i, w in enumerate(警告):
            for j, seg in enumerate([w[k:k + 46] for k in range(0, len(w), 46)]):
                sh.text(bx + 3, wy0 + 12 + (i * 3 + j) * 5.2, seg.replace("**", ""), 2.3, color="#7c2d12")
    return sh, 警告


# ── 通用:按裁片清单画 ──────────────────────────────────────────────────
# 43 个形制一个个手写画法是写不完的,而且写完也维护不动。改成**按 `pattern_piece` 里
# 登记的裁片清单画** —— 库里说这个版型有哪几片,就画哪几片;每片的尺寸按下面这张
# 公式表从号型推。库里加一个新版型,不用改这里的代码。
#
# ⚠️ 公式是**按汉服十字型平面结构推的初版**(依据 `制版规范.md` §五),不是版师的定稿:
#   · 十字型:无肩缝、前后连裁、后中对折 —— 所以「后片 ×1」画成对折片
#   · 通袖长是指尖到指尖,减去背宽(≈胸围/2)再对半,才是一只袖子的长
#   · 交领要掩襟(前片比后片宽出一块),对襟不用
# 每片上都印着自己的公式,版师能逐条驳。推不出来的(缺尺寸、不认识的片名)**在图上报出来,不猜**。
布幅 = 50.0          # 传统织机幅宽,接袖的由来
掩襟 = {"交领": 15.0, "大襟": 12.0, "圆领": 12.0, "竖领": 12.0, "立领": 12.0, "对襟": 0.0, "方领": 0.0}


def _领型(xzn, pieces):
    名 = set(pieces)
    for k in ("立领", "竖领", "圆领", "方领"):
        if k in xzn or k in 名:
            return k
    if "交领" in xzn or "大襟贴边" in 名:
        return "交领" if "交领" in xzn else "大襟"
    return "对襟"


def 件表(名, g):
    """一片 → (宽 cm, 高 cm, 面料, 对折边, 公式)。返回 None = 这一片的公式还没有,不猜。
    g 是这一版型已经算好的量:半身宽、衣长、袖长…"""
    # 缺的量一律当 0 传下去 —— 算出 0 的那片会被上面判成「缺号型数据」报出来,
    # 而不是在这里整张表一起炸(一片缺数,其余片也画不成)
    z = {k: (v or 0) for k, v in g.items() if isinstance(v, (int, float)) or v is None}
    半 = z["半身"]; 衣长 = z["衣长"]; 领围 = z["领围"]
    g = {**g, **z}
    T = dict(
        # 衣身:后片连裁对折,前片加掩襟
        后片=(半, 衣长, "left", "宽=胸围/4+松量3(后中对折) 长=衣长"),
        前片=(半 + g["掩"], 衣长, None, f"宽=胸围/4+3+掩襟{g['掩']:g}({g['领型']}) 长=衣长"),
        袖片=(g["袖长"], g["袖肥"], None, "长=(通袖长−胸围/2)/2 宽=袖肥"),
        大袖片=(g["袖长"], 55.0, None, "长=(通袖长−胸围/2)/2 宽=大袖 55"),
        短袖片=(max(g["袖长"] * 0.35, 18.0), 34.0, None, "长=袖长×0.35(半臂) 宽=34"),
        # 领与缘
        领缘=(衣长 * 1.6 + 20, 12.0, None, "长=衣长×1.6+20(绕过领口通到下摆) 宽=12(对折 6)"),
        袖缘=(g["袖肥"] * 2, 12.0, None, "长=袖肥×2 宽=12(对折 6)"),
        立领=(领围 + 4, 10.0, None, "长=领围+4 高=10(对折 5)"),
        竖领=(领围 + 4, 12.0, None, "长=领围+4 高=12(对折 6)"),
        圆领=(领围 + 6, 8.0, None, "长=领围+6 宽=8"),
        # 摆与贴边
        摆片=(24.0, 衣长 * 0.55, None, "宽=24 长=衣长×0.55(两侧外摆)"),
        内摆=(24.0, 衣长 * 0.5, None, "宽=24 长=衣长×0.5(道袍内摆)"),
        侧摆=(20.0, 衣长 * 0.5, None, "宽=20 长=衣长×0.5"),
        大襟贴边=(12.0, 衣长, None, "宽=12 长=衣长"),
        门襟贴边=(8.0, 衣长, None, "宽=8 长=衣长"),
        方领贴边=(领围 + 10, 8.0, None, "长=领围+10 宽=8"),
        坦领贴边=(领围 + 10, 8.0, None, "长=领围+10 宽=8"),
        开衩贴边=(6.0, 衣长 * 0.4, None, "宽=6 长=衣长×0.4"),
        拉链贴边=(6.0, 50.0, None, "宽=6 长=50(隐形拉链 40+缩余)"),
        补子位贴边=(40.0, 40.0, None, "补子 40×40(明制方补),位置:前胸中心、后背中心"),
        横襕=(半 * 2, 20.0, None, "宽=胸围/2+6 高=20(襕衫横襕)"),
        # 裙与裤
        裙片=(g["裙片宽"], g["裙身"], None, g["裙片式"] or "缺腰围 / 裙长"),
        裙腰=(g["腰长"], 12.0, None, "长=腰围+搭叠12 高=12(对折 6)"),
        裙头=(g["腰长"], 12.0, None, "长=腰围+搭叠12 高=12(对折 6)"),
        裤腰=(g["腰长"], 12.0, None, "长=腰围+搭叠12 高=12(对折 6)"),
        裤前片=(g["裤宽"], g["裤长"], None, "宽=臀围/4+6 长=裤长"),
        裤后片=(g["裤宽"] + 4, g["裤长"], None, "宽=臀围/4+10(后片加量) 长=裤长"),
        系带=(100.0, 6.0, None, "长=100 宽=6(对折 3)"),
        襳带=(120.0, 8.0, None, "长=120 宽=8(杂裾飘带)"),
        垂髾=(22.0, 42.0, None, "三角燕尾,外接矩形 22×42;**按外框裁,尖角由版师定**"),
        诃子=(g["半身"] * 2, 35.0, None, "宽=胸围/2+6 高=35(诃子围合上身)"),
        腰接片=(g["腰长"] * 0.6, 14.0, None, "长=腰围×0.6+ 高=14(连衣裙腰接片)"),
        背子=(半, 衣长, "left", "宽=胸围/4+3(后中对折) 长=衣长"),
    )
    # 同一形状换个名字:上襦 / 袄 / 上身,衣长各按自己那条量
    for pre, ln, why in (("上襦", g["上襦长"], "上襦衣长"), ("袄", 衣长, "衣长"), ("上身", 衣长 * 0.45, "衣长×0.45(曳撒上身)")):
        for base in ("前片", "后片"):
            w, h, fold, f = T[base]
            T[pre + base] = (w, ln, fold, f.replace("长=衣长", f"长={why}"))
    # 曳撒下裳:马面 + 褶裥,按裙那套算
    T["下裳马面"] = (g.get("马面宽") or 22.0, 衣长 * 0.55, None, "宽=马面宽(缺则 22) 长=衣长×0.55")
    T["下裳褶裥"] = (g["裙片宽"], 衣长 * 0.55, None, "展开宽同裙片 长=衣长×0.55")
    T["下裳"] = (g["裙片宽"], 衣长 * 0.55, None, "展开宽同裙片 长=衣长×0.55")
    T["马面"] = (g.get("马面宽") or 22.0, g["裙身"], None, "宽=马面宽 长=裙长−腰高")
    T["褶裥片"] = (g["裙片宽"], g["裙身"], None, g["裙片式"] or "缺腰围 / 裙长")
    return T.get(名)


def 量(d, size):
    """把号型表翻成画图要用的量。缺哪条就是 None,画到需要它的片时才报。"""
    sp = d["spec"]
    xzn = d["pattern"].get("xzn") or d["pattern"].get("name") or ""
    names = [p["name"] for p in d["pieces"]]
    胸 = sp.get("胸围"); 衣长 = sp.get("衣长") or sp.get("上襦衣长"); 通袖 = sp.get("通袖长")
    腰 = sp.get("裙腰围") or sp.get("腰围"); 裙长 = sp.get("裙长")
    领型 = _领型(xzn, names)
    半 = (胸 / 4 + 3) if 胸 else None
    袖长 = max((通袖 - 胸 / 2) / 2, 20.0) if (通袖 and 胸) else None
    裙份 = max(1, sum(p["qty"] for p in d["pieces"] if p["name"] in ("裙片", "褶裥片", "下裳褶裥", "下裳")))
    估腰 = ""
    if not 腰 and 胸:
        腰, 估腰 = 胸 * 0.8, "(腰围库里没有,按胸围×0.8 估 —— 请版师核)"
    if 腰:
        展开 = 腰 * 2.2                                   # 褶裙常见 2–2.5 倍褶量,取 2.2
        裙片宽 = min(布幅, 展开 / 裙份)
        裙片式 = f"宽=腰围×2.2÷{裙份}片{估腰}(褶量 2.2 倍,不超布幅 {布幅:g}) 长=裙长−腰高6"
    else:
        裙片宽 = 裙片式 = None
    # 连衣裙没有「裙长」这一条(只有衣长),裙片是腰接片以下那一截
    裙身 = (裙长 - 6) if 裙长 else (衣长 * 0.55 if (衣长 and "腰接片" in names) else None)
    if 裙长 is None and 裙身:
        裙片式 = (裙片式 or "") + " ※长=衣长×0.55(连衣裙腰线以下,库里没有裙长)"
    return dict(半身=半, 衣长=衣长, 上襦长=sp.get("上襦衣长") or 衣长, 领围=sp.get("领围") or (胸 and 胸 * 0.38),
                袖长=袖长, 袖肥=(55.0 if "大袖" in xzn else 28.0), 掩=掩襟[领型], 领型=领型,
                裙身=裙身, 裙片宽=裙片宽, 裙片式=裙片式,
                腰长=(腰 + 12) if 腰 else None, 马面宽=sp.get("马面宽"),
                裤宽=(sp.get("臀围") / 4 + 6) if sp.get("臀围") else None, 裤长=sp.get("裤长"), xzn=xzn)


def draft_generic(d, size):
    global S
    g = 量(d, size)
    警告 = []
    件 = []
    for p in sorted(d["pieces"], key=lambda p: p["name"]):
        r = 件表(p["name"], g)
        if not r:
            警告.append(f"「{p['name']}」这一片的画法还没有,**图上没画** —— 别当成不需要这片")
            continue
        w, h, fold, f = r
        if not w or not h:
            警告.append(f"「{p['name']}」缺号型数据(要 {f.split(' ')[0]}),画不了")
            continue
        件.append((p["name"], p["qty"], w, h, fold, f))
    if not 件:
        raise SystemExit(f"❌ {d['pattern']['code']} 一片都画不出来:{'; '.join(警告) or '没有裁片登记'}")

    款号 = d["product"]["spu"][-6:] if d["product"] else d["pattern"]["code"]
    名称 = d["product"]["name"] if d["product"] else d["pattern"]["name"]
    面料 = d["mt"]
    # 排版:大片在前,一行行码;放不下就整体缩小重排(比例印在标题栏里)
    for scale in (2.0, 1.6, 1.3, 1.05, 0.85, 0.7, 0.55, 0.45):
        S = scale
        布局, x, y, 行高, 放得下 = [], 16.0, 24.0, 0.0, True
        for 名, qty, w, h, fold, f in sorted(件, key=lambda t: -t[3]):
            W, H = cm(w) + cm(2) + 6, cm(h) + cm(4) + 9
            if x + W > 404:
                x, y, 行高 = 16.0, y + 行高 + 8, 0.0
            if y + H > 196:
                放得下 = False
                break
            布局.append((名, qty, w, h, fold, f, x, y))
            x += W + 4
            行高 = max(行高, H)
        if 放得下:
            break
    if not 放得下:
        警告.append("裁片太多,一张 A3 排不下,图上只画了排得下的那些")

    sh = Sheet()
    sh.rect(5, 5, 410, 287, "thick")
    for 名, qty, w, h, fold, f, px, py in 布局:
        sa = (缝份["边"], 缝份["边"], 缝份["下摆"] if h > 40 else 缝份["边"], 缝份["边"])
        nx, ny, nw, nh = 裁片(sh, px, py, w, h, 名, qty, 面料, 款号, size, sa=sa, fold=fold)
        sh.dim(nx, ny, nx + nw, ny, f"{w:.1f}", off=5)
        sh.dim(nx, ny, nx, ny + nh, f"{h:.1f}", off=5)
        for i, seg in enumerate([f[k:k + 34] for k in range(0, len(f), 34)][:2]):
            sh.text(nx, ny + nh + cm(缝份["下摆"] if h > 40 else 缝份["边"]) + 4 + i * 3.4,
                    seg.replace("**", ""), 2.2, color="#555")
    _标题栏(sh, d, size, 名称, 款号, g, 警告)
    return sh, 警告


def _标题栏(sh, d, size, 名称, 款号, g, 警告):
    sp = d["spec"]
    规格 = " · ".join(f"{k} {v:g}" for k, v in sp.items())
    bx, by = 16, 206
    sh.rect(bx, by, 250, 80, "thick")
    rows = [("款名", 名称[:28]),
            ("款号 / 版型", f"{款号} / {d['pattern']['code']} v{d['pattern'].get('version') or 1} · {g['xzn']}"),
            ("号型", f"{size}   领型:{g['领型']}"),
            ("比例", f"1:{10 / S:.0f}(A3 横向)  单位 cm"),
            ("规格", 规格[:60]),
            ("结构", "十字型平面结构:无肩缝、后中对折、接袖按布幅 50"),
            ("制图", f"系统按公式初版 · {dt.date.today().isoformat()} · 复核:____")]
    for i, (k, v) in enumerate(rows):
        yy = by + 9 + i * 10.2
        sh.text(bx + 3, yy, k, 2.6, bold=True)
        sh.text(bx + 32, yy, v, 2.5)
        if i:
            sh.line(bx, yy - 7, bx + 250, yy - 7, "thin")
    lx, ly = 274, 212
    sh.text(lx, ly, "图例", 2.8, bold=True)
    for i, (k, lab) in enumerate((("thick", "毛样(裁剪线,含缝份)"), ("thin", "净样(完成线)"),
                                  ("dashdot", "对折线(后中 / 腰)"))):
        yy = ly + 5 + i * 5
        sh.line(lx, yy - 0.8, lx + 12, yy - 0.8, k)
        sh.text(lx + 15, yy, lab, 2.4)
    sh.grain(lx + 6, ly + 22, ly + 30)
    sh.text(lx + 15, ly + 27, "布纹线(经向)", 2.4)
    sh.text(lx, ly + 38, f"缝份:边 {缝份['边']:g} · 下摆 {缝份['下摆']:g}", 2.4)
    if 警告:
        sh.el.append(f'<rect x="{lx}" y="{ly + 42}" width="136" height="{8 + 5 * len(警告) * 2}" '
                     f'fill="#fff4e5" stroke="#d97706" stroke-width="{THIN}"/>')
        sh.text(lx + 3, ly + 48, "⚠ 版师请核", 2.6, bold=True, color="#b45309")
        k = 0
        for w in 警告:
            for seg in [w[j:j + 52] for j in range(0, len(w), 52)]:
                sh.text(lx + 3, ly + 53 + k * 4.6, seg.replace("**", ""), 2.2, color="#7c2d12")
                k += 1


FAMILIES = [("马面裙", lambda d: {"马面", "褶裥片"} <= {p["name"] for p in d["pieces"]}, draft_mamian),
            ("按裁片清单", lambda d: bool(d["pieces"]), draft_generic)]


def render(key, size="M"):
    """给系统调:返回 (svg 字符串, 画法名, 警告列表)。命令行和后台走同一条路,
    **不另写一份** —— 两条路各画各的,迟早出现「页面上看到的」和「打印出来的」不一样。"""
    d = 取数(key, size)
    for nm, hit, fn in FAMILIES:
        if hit(d):
            sh, 警告 = fn(d, size)
            return sh.svg(), nm, 警告
    raise ValueError(f"版型 {d['pattern']['code']}({d['pattern'].get('xzn')})没有登记裁片,画不了")


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "PT04"
    size = sys.argv[2] if len(sys.argv) > 2 else "M"
    out = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/打版-{key}-{size}.svg"
    try:
        svg, nm, 警告 = render(key, size)
    except ValueError as e:
        raise SystemExit(f"❌ {e} —— 不猜")
    open(out, "w", encoding="utf-8").write(svg)
    print(f"✅ {nm} · {key} · {size} → {out}")
    for w in 警告:
        print("  ⚠", w.replace("**", ""))


if __name__ == "__main__":
    main()
