#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3D 效果图小样的驱动:从库里取一款商品的参数,交给 Blender 渲染。

    python3 tools/render3d/render3d.py <spu> <输出.png> [--samples 96]

**只做了马面裙**(结构最简单:前后马面 + 两侧褶 + 裙腰)—— 这是给用户看效果的小样,
全量 3D 建模等用户批准。参数(腰围 / 裙长 / 马面宽 / 颜色 / 面料 / 襕边 / 刺绣)全部
来自商品数据,和平面图第二版原型用的是同一套判断(tools/img_v2_proto.py 的 features)。
"""
import os, sys, json, sqlite3, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "tools")]
import img as V1
import img_v2_proto as V2

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def params(spu):
    c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    pt = c.execute("SELECT pattern FROM product WHERE spu=?", (spu,)).fetchone()[0]
    spec = {k: v for k, v in c.execute(
        "SELECT item, value FROM size_spec WHERE pattern=? AND size='M'", (pt,))}
    svg = V1.render(spu, "main")
    import re
    mid = re.search(r'offset=".46" stop-color="(#[0-9A-F]{6})"', svg).group(1)
    f = V2.features(spu)
    return {"腰围": spec.get("腰围") or spec.get("裙腰围") or 72.0,
            "裙长": spec.get("裙长") or 96.0, "马面宽": spec.get("马面宽") or 32.0,
            "颜色": mid, "面料": f["fab"], "襕": f["襕"],
            # 3D 里浅色花瓣会被灯光吃掉,刺绣用更饱和的一组
            "绣色": (["#E04F7A", "#F2B134", "#3E8E6E"] if f["绣"] else None),
            "褶数": 22 + V1._hue(spu) % 10, "名称": f["name"]}


def main():
    spu, out = sys.argv[1], os.path.abspath(sys.argv[2])
    p = params(spu)
    if "--samples" in sys.argv:
        p["samples"] = int(sys.argv[sys.argv.index("--samples") + 1])
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(p, f, ensure_ascii=False)
    r = subprocess.run([BLENDER, "-b", "-P", os.path.join(HERE, "mamian_scene.py"), "--", f.name, out],
                       capture_output=True, text=True, timeout=900)
    if "RENDERED" not in r.stdout:
        print(r.stdout[-2500:], r.stderr[-2500:])
        raise SystemExit("❌ Blender 没渲染出来")
    print(f"✅ {p['名称']} → {out}")


if __name__ == "__main__":
    main()
