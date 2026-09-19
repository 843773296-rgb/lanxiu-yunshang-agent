# -*- coding: utf-8 -*-
"""Blender 场景:按参数搭一条马面裙并渲染(3D 效果图小样,未接入系统)。

用法(由 tools/render3d/render3d.py 调用,不要直接跑):
  Blender -b -P mamian_scene.py -- params.json out.png

结构按马面裙的真实裁片走:前后两片平整的「马面」,两侧褶裥,顶上一圈裙腰,
下摆比腰围大、褶在下摆自然张开。参数全部来自商品数据(腰围 / 裙长 / 马面宽 / 颜色 /
面料 / 襕边道数 / 刺绣),不是手调的。
"""
import bpy, bmesh, json, math, sys

argv = sys.argv[sys.argv.index("--") + 1:]
P = json.load(open(argv[0]))
OUT = argv[1]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple((int(h[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4)) + (1.0,)


# ── 清场 ─────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# ── 裙身网格 ─────────────────────────────────────────────────────────
waist = P["腰围"] / 100.0            # 周长 m
L = P["裙长"] / 100.0
mm = P["马面宽"] / 100.0
r0 = waist / (2 * math.pi) * 1.08    # 腰口半径(裙腰略松)
r1 = r0 * 2.1                         # 下摆半径:褶打开之后
N_A, N_Y = 480, 70
n_pleat = int(P.get("褶数", 26))
top_z = 0.95

bm = bmesh.new()
rows = []
for j in range(N_Y + 1):
    t = j / N_Y
    z = top_z - t * L
    # 腰臀处很快散开、往下基本垂直 —— 真的马面裙是这么挂的,不是一路张开的圆锥
    r = r0 + (r1 - r0) * (t ** 0.55)      # A 字形往下张开(第二版用指数,上半截鼓成了圆顶)
    # 马面在这一高度占的半角:马面宽固定,半径变大角度变小
    half = (mm / 2) / r
    ring = []
    for i in range(N_A):
        th = 2 * math.pi * i / N_A
        # 离前(0)或后(π)的角距
        dfront = min(abs(math.atan2(math.sin(th), math.cos(th))),
                     abs(math.atan2(math.sin(th - math.pi), math.cos(th - math.pi))))
        rr = r
        if dfront > half:                       # 褶区:锯齿形,越往下越深
            ph = (th * n_pleat / math.pi) % 1.0
            saw = abs(ph - 0.5) * 2 - 0.5
            rr = r + saw * (0.004 + 0.022 * t)
        ring.append(bm.verts.new((rr * math.cos(th), rr * math.sin(th), z)))
    rows.append(ring)
for j in range(N_Y):
    for i in range(N_A):
        a, b = rows[j][i], rows[j][(i + 1) % N_A]
        c, d = rows[j + 1][(i + 1) % N_A], rows[j + 1][i]
        f = bm.faces.new((a, b, c, d))
        t = (j + 0.5) / N_Y
        f.material_index = 0
        for k in range(P.get("襕", 0)):                       # 襕边:下摆一两道金带
            lo = 0.80 - k * 0.075
            if lo <= t <= lo + 0.045:
                f.material_index = 1
me = bpy.data.meshes.new("skirt")
bm.to_mesh(me)
bm.free()
skirt = bpy.data.objects.new("skirt", me)
sc.collection.objects.link(skirt)
bpy.context.view_layer.objects.active = skirt
skirt.select_set(True)
bpy.ops.object.shade_smooth()
sol = skirt.modifiers.new("thick", "SOLIDIFY")
sol.thickness = 0.003

# ── 材质 ─────────────────────────────────────────────────────────────
def fabric(name, color, kind):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bs = nt.nodes["Principled BSDF"]
    bs.inputs["Base Color"].default_value = color
    rough = {"丝": 0.32, "锦": 0.42, "纱": 0.5, "棉": 0.85}.get(kind, 0.5)
    bs.inputs["Roughness"].default_value = rough
    if "Sheen Weight" in bs.inputs:
        bs.inputs["Sheen Weight"].default_value = 0.6 if kind in ("丝", "锦") else 0.15
    if kind == "纱" and "Transmission Weight" in bs.inputs:
        bs.inputs["Transmission Weight"].default_value = 0.35
    if kind in ("锦", "棉"):
        # 锦缎暗纹 / 棉麻织纹:用噪声做凹凸
        tex = nt.nodes.new("ShaderNodeTexWave" if kind == "锦" else "ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 60.0 if kind == "锦" else 400.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.25 if kind == "锦" else 0.4
        nt.links.new(tex.outputs[0 if kind == "锦" else "Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return m


def gold():
    m = bpy.data.materials.new("gold")
    m.use_nodes = True
    bs = m.node_tree.nodes["Principled BSDF"]
    bs.inputs["Base Color"].default_value = hex_rgb("#D4AF37")
    bs.inputs["Metallic"].default_value = 0.85
    bs.inputs["Roughness"].default_value = 0.35
    tex = m.node_tree.nodes.new("ShaderNodeTexVoronoi")
    tex.inputs["Scale"].default_value = 180.0
    bump = m.node_tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.5
    m.node_tree.links.new(tex.outputs["Distance"], bump.inputs["Height"])
    m.node_tree.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return m


skirt.data.materials.append(fabric("body", hex_rgb(P["颜色"]), P.get("面料", "")))
skirt.data.materials.append(gold())

# ── 裙腰 ─────────────────────────────────────────────────────────────
bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=r0 * 1.01, depth=0.06,
                                    location=(0, 0, top_z + 0.03))
wb = bpy.context.active_object
wb.data.materials.append(fabric("waist", hex_rgb("#F3EEE3"), "棉"))
bpy.ops.object.shade_smooth()

# ── 刺绣:马面正中一枝花(花瓣是贴在裙面上的小扁球)──────────────────
if P.get("绣色"):
    cols = [hex_rgb(c) for c in P["绣色"]]
    z_c = top_z - L * 0.42

    def mat(col, rough=0.45):
        m = bpy.data.materials.new("thread")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = col
        b.inputs["Roughness"].default_value = rough
        if "Sheen Weight" in b.inputs:
            b.inputs["Sheen Weight"].default_value = 0.8      # 丝线的光泽
        return m
    for (dy, dz, s), col in zip(((-0.05, 0.03, 1.0), (0.04, -0.03, 1.25), (0.0, 0.10, 0.8)), cols):
        tt = (top_z - (z_c + dz)) / L
        rr = r0 + (r1 - r0) * (tt ** 0.55)
        for a in range(5):                                   # 五瓣,沿半径方向散开
            ang = a * 2 * math.pi / 5 + 0.3
            y = dy + math.cos(ang) * 0.024 * s
            z = z_c + dz + math.sin(ang) * 0.024 * s
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02 * s, location=(rr + 0.003, y, z))
            p = bpy.context.active_object
            p.scale = (0.12, 0.45, 1.0)
            p.rotation_euler = (math.pi / 2 - ang, 0, 0)
            p.data.materials.append(mat(col))
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.009 * s, location=(rr + 0.006, dy, z_c + dz))
        cc = bpy.context.active_object
        cc.scale = (0.4, 1, 1)
        cc.data.materials.append(mat(hex_rgb("#F4D35E"), 0.3))

# ── 棚拍:无缝背景 + 三盏灯 + 相机 ──────────────────────────────────────
# 无缝背景布:相机在 +x 看向 -x。地面从相机这一侧铺过来,到裙子后面弯上去成墙,
# 没有墙角那条线(第一版方向反了,弧面挡在相机和裙子中间)
bm2 = bmesh.new()
R, X0 = 1.3, -0.7
prof = [(4.0 - 0.25 * k, 0.0) for k in range(int((4.0 - X0) / 0.25) + 1)]
prof += [(X0 - R * math.sin(a / 24 * math.pi / 2), R - R * math.cos(a / 24 * math.pi / 2)) for a in range(1, 25)]
prof += [(X0 - R, R + 0.25 * k) for k in range(1, 14)]
vs = [[bm2.verts.new((x, -3 + 6 * u / 16, z)) for (x, z) in prof] for u in range(17)]
for u in range(16):
    for k in range(len(prof) - 1):
        bm2.faces.new((vs[u][k], vs[u][k + 1], vs[u + 1][k + 1], vs[u + 1][k]))
me2 = bpy.data.meshes.new("bg"); bm2.to_mesh(me2); bm2.free()
floor = bpy.data.objects.new("bg", me2)
floor.location = (0, 0, top_z - L - 0.001)
sc.collection.objects.link(floor)
bpy.context.view_layer.objects.active = floor
floor.select_set(True)
bpy.ops.object.shade_smooth()
fm = bpy.data.materials.new("floor")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = hex_rgb("#CFC8BD")
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
floor.data.materials.append(fm)
world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = hex_rgb("#D8D2C8")
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25

for name, loc, energy, size in (("key", (2.4, -1.4, 2.4), 220, 2.0),
                                ("fill", (1.6, 2.0, 1.2), 70, 2.4),
                                ("rim", (-1.4, 0.8, 2.2), 160, 1.4)):
    bpy.ops.object.light_add(type="AREA", location=loc)
    l = bpy.context.active_object
    l.data.energy = energy
    l.data.size = size
    d = l.location
    l.rotation_euler = (0, 0, 0)
    tr = l.constraints.new("TRACK_TO")
    tr.target = skirt
    tr.track_axis = "TRACK_NEGATIVE_Z"
    tr.up_axis = "UP_Y"

bpy.ops.object.camera_add(location=(2.35, -0.6, top_z - L * 0.42 + 0.2))
cam = bpy.context.active_object
tr = cam.constraints.new("TRACK_TO")
tgt = bpy.data.objects.new("tgt", None)
tgt.location = (0, 0, top_z - L * 0.48)
sc.collection.objects.link(tgt)
tr.target = tgt
tr.track_axis = "TRACK_NEGATIVE_Z"
tr.up_axis = "UP_Y"
cam.data.lens = 55
sc.camera = cam

# ── 渲染 ─────────────────────────────────────────────────────────────
sc.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for dv in prefs.devices:
        dv.use = True
    sc.cycles.device = "GPU"
except Exception:
    pass
sc.cycles.samples = int(P.get("samples", 96))
sc.cycles.use_denoising = True
sc.render.resolution_x = sc.render.resolution_y = int(P.get("size", 900))
sc.render.filepath = OUT
sc.view_settings.view_transform = "Standard"   # 商品图要颜色准:AgX / Filmic 会把胭脂红压成浅粉
bpy.ops.render.render(write_still=True)
print("RENDERED", OUT)
