#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打版图:给一个版型和号型,按 GB/T 29863-2023《服装制图》的线型与标注画出每一片裁片。

    python3 tools/patterndraw/draft.py <spu 或 版型编码> [号型=M] [输出.svg]

规范依据见同目录 `制版规范.md`。**这不是版师画的图,是按公式从库里的尺寸推出来的初版** ——
公式写在图上(版师能逐条驳),数据推出不合理的值时在图上打警告,不静默画一张看着很对的图。

现在支持的形制:明制马面裙(马面 + 褶裥片 + 裙腰 + 系带)。其余形制报「还没做」,不猜。
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
    spec = {r["item"]: r["value"] for r in c.execute(
        "SELECT item,value FROM size_spec WHERE pattern=? AND size=?", (pt, size))}
    pieces = [dict(r) for r in c.execute("SELECT name,qty,note FROM pattern_piece WHERE pattern=?", (pt,))]
    pc = p and c.execute("SELECT mt_opts,kf_opts FROM product_custom WHERE spu=?", (p["spu"],)).fetchone()
    return dict(product=p and dict(p), pattern=dict(ptn), spec=spec, pieces=pieces,
                mt=(pc["mt_opts"].split(",")[0] if pc and pc["mt_opts"] else "面料"),
                kf=(pc["kf_opts"] if pc else "") or "")


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
    for k in range(襕):                                                 # 襕位:膝襕 / 底襕
        yb = ny + nh - cm(10 + k * 32)
        hb = cm(8)
        sh.line(nx, yb - hb, nx + nw, yb - hb, "dash"); sh.line(nx, yb, nx + nw, yb, "dash")
        sh.text(nx + nw / 2, yb - hb / 2 + 1, ["底襕(织金)", "膝襕(织金)"][k], 2.4, "middle", color="#8a5a12")
        sh.dim(nx + nw, yb, nx + nw, ny + nh, f"{10 + k * 32:g}", off=-6)
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
    if 警告:
        wy0 = 18
        sh.el.append(f'<rect x="{bx}" y="{wy0}" width="120" height="{12 + 5.2 * len(警告) * 3}" fill="#fff4e5" stroke="#d97706" stroke-width="{THIN}"/>')
        sh.text(bx + 3, wy0 + 6, "⚠ 数据核对", 2.8, bold=True, color="#b45309")
        for i, w in enumerate(警告):
            for j, seg in enumerate([w[k:k + 46] for k in range(0, len(w), 46)]):
                sh.text(bx + 3, wy0 + 12 + (i * 3 + j) * 5.2, seg.replace("**", ""), 2.3, color="#7c2d12")
    return sh, 警告


FAMILIES = [("马面裙", lambda d: {"马面", "褶裥片"} <= {p["name"] for p in d["pieces"]}, draft_mamian)]


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "PT04"
    size = sys.argv[2] if len(sys.argv) > 2 else "M"
    out = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/打版-{key}-{size}.svg"
    d = 取数(key, size)
    for nm, hit, fn in FAMILIES:
        if hit(d):
            sh, 警告 = fn(d, size)
            open(out, "w", encoding="utf-8").write(sh.svg())
            print(f"✅ {nm} · {d['pattern']['code']} · {size} → {out}")
            for w in 警告:
                print("  ⚠", w.replace("**", ""))
            return
    raise SystemExit(f"❌ 版型 {d['pattern']['code']}({d['pattern'].get('xzn')})的形制还没做 —— 不猜")


if __name__ == "__main__":
    main()
