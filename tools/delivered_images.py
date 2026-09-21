#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付图清单 —— **图不进版本库,那就让「哪些图存在、长什么样」进版本库。**

    python3 tools/delivered_images.py 登记            # 按现有的图生成/更新清单
    python3 tools/delivered_images.py 验              # 核系统里那份
    python3 tools/delivered_images.py 验 --在 <目录>   # 核任意一份拷贝(比如桌面那个母本)

## 为什么要有它

商品图是二进制、几百 MB、而且一批批地换,所以 `backend/static/img/`
是 gitignore 的 —— 这个决定没问题。代价是:**这些图没有任何版本记录。**

2026-09-21 清理桌面时撞上了这个代价的实体:
「苏绣缂丝」明制马面裙那 5 张图**只存在于 `backend/static/img/`**,
桌面母本里没有。也就是说它们在这台机器上**只有一份**,
而重装、换机、或者谁跑一次清理,它们就没了 —— 重出一遍要烧掉大量出图额度。

> 图可以不进版本库。**但「这张图存在过、内容是这个」必须进。**

清单很小(一行一张图),进版本库之后:

  · 从任何一份拷贝恢复,都能逐张核对完整性
  · 图被悄悄换掉(重出一版、传错文件)看得出来 —— **内容哈希对不上**
  · 哪几张图丢了,一眼看得到,而且**和「图被改了」分开报**

## 判据:缺了 / 变了 / 多了,是三件事

  **缺了**  清单里有,目录里没有 —— 丢图了,从别的拷贝恢复
  **变了**  同名而内容哈希不同 —— 重出了一版,或者传错了。
            **这是最危险的一种**:页面照常显示,而客户看到的和你以为的不是同一张
  **多了**  目录里有,清单里没有 —— 新收了一批还没登记。不算错,但要提醒

三件事分开报,是因为**下一步动作完全不同**:缺了去恢复、变了去核对、多了去登记。
合在一起报一个「不一致 N 处」,人会往错的方向查。
"""
import argparse, hashlib, json, os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
清单档 = os.path.join(ROOT, "backend", "交付图清单.json")
默认目录 = os.path.join(ROOT, "backend", "static", "img")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

咬合 = [
    ("把某张图的内容改掉(字节变了,文件名没变)", "图的内容和登记的一致"),
    ("删掉某张登记过的图", "登记过的图都还在"),
    ("往目录里放一张没登记的图", "目录里没有未登记的图"),
]


def 摘要(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:32]


def 扫(目录):
    出 = {}
    if not os.path.isdir(目录):
        return 出
    for f in sorted(os.listdir(目录)):
        if f.startswith(".") or not f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        p = os.path.join(目录, f)
        出[f] = {"字节": os.path.getsize(p), "摘要": 摘要(p)}
    return 出


def 商品名():
    try:
        c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
        return {r[0]: r[1] for r in c.execute("SELECT spu,name FROM product")}
    except Exception:
        return {}


def 登记(a):
    现 = 扫(a.在 or 默认目录)
    if not 现:
        raise SystemExit(f"❌ {a.在 or 默认目录} 里一张图都没有 —— "
                         f"**登记一份空清单,和「没图可登记」在文件上长得一样**,这里直接拒绝")
    名 = 商品名()
    条目 = {}
    for f, v in 现.items():
        spu, _, 位 = os.path.splitext(f)[0].rpartition("-")
        条目[f] = dict(v, spu=spu, 图位=位, 商品名=名.get(spu, ""))
    旧 = 读()
    变 = [f for f in 条目 if f in 旧 and 旧[f]["摘要"] != 条目[f]["摘要"]]
    if 变 and not a.强制:
        print(f"{R}❌ 这 {len(变)} 张已经登记过,而内容变了:{D}")
        for f in 变[:6]:
            print(f"   {f}")
        raise SystemExit("   图变了意味着**外面那一版和现在这一版不是同一张** ——\n"
                         "   确认是有意重出的再加 --强制。")
    json.dump({"说明": "交付图的指纹。**图本身不进版本库(二进制、几百 MB、一批批换),"
                       "但「这张图存在过、内容是这个」必须进** —— 否则一份拷贝丢了,"
                       "没有任何东西能告诉你丢了哪几张、剩下的是不是原版。",
               "怎么用": "换机/重装之后:python3 tools/delivered_images.py 验 --在 <恢复出来的目录>",
               "母本在哪": "~/Desktop/澜绣云裳agent-出好的图(这些图唯一的备份,别删)",
               "登记于": "2026-09-21", "张数": len(条目), "图": 条目},
              open(清单档, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    款 = len({v["spu"] for v in 条目.values()})
    print(f"✅ 登记 {len(条目)} 张 / {款} 款 → {os.path.relpath(清单档, ROOT)}")
    return 0


def 读():
    if not os.path.isfile(清单档):
        return {}
    return json.load(open(清单档, encoding="utf-8")).get("图", {})


def 验(a):
    目录 = a.在 or 默认目录
    登 = 读()
    失败 = []

    def ck(ok, 名, 说明=""):
        print(("  ✅ " if ok else "  ❌ ") + 名 + (f" —— {说明}" if 说明 else ""))
        if not ok:
            失败.append(名)

    print(f"交付图清单 · 核 {os.path.relpath(目录, ROOT) if 目录.startswith(ROOT) else 目录}")
    if not 登:
        print(f"     ℹ️ 还没有清单({os.path.relpath(清单档, ROOT)})—— "
              f"**没东西可验**,不是验过了。先跑 `登记`")
        print(f"{G}✅ 交付图清单(没东西可验){D}")
        return 0
    现 = 扫(目录)
    if not 现:
        # CI / 新克隆上本来就没有图 —— 说清楚是「没东西可验」,别报成不合格
        print(f"     ℹ️ 这台机器上没有商品图(CI / 新克隆都是这样)—— "
              f"下面三条**没东西可验**。清单里登记着 {len(登)} 张,"
              f"恢复之后用 `验 --在 <目录>` 逐张核")
        print(f"{G}✅ 交付图清单(没东西可验){D}")
        return 0

    ck(True, "样本量:登记 / 现有", f"登记 {len(登)} 张 · 目录里 {len(现)} 张")

    缺 = sorted(f for f in 登 if f not in 现)
    变 = sorted(f for f in 登 if f in 现 and 登[f]["摘要"] != 现[f]["摘要"])
    多 = sorted(f for f in 现 if f not in 登)

    ck(not 缺, "登记过的图都还在",
       "、".join(缺[:5]) + (f"  ……**还有 {len(缺) - 5} 张**(共 {len(缺)})"
                           if len(缺) > 5 else "")
       + " —— **丢图了**,从母本恢复:~/Desktop/澜绣云裳agent-出好的图"
       if 缺 else f"{len(登)} 张都找得到")

    ck(not 变, "图的内容和登记的一致",
       "、".join(变[:5]) + (f"  ……**还有 {len(变) - 5} 张**(共 {len(变)})"
                           if len(变) > 5 else "")
       + " —— **同名而内容不同**:重出了一版,或者传错了。"
         "页面照常显示,而客户看到的和你以为的不是同一张。"
         "确认是有意重出的就跑 `登记 --强制`"
       if 变 else f"{len(登)} 张逐张对上(sha256)")

    ck(not 多, "目录里没有未登记的图",
       "、".join(多[:5]) + (f"  ……**还有 {len(多) - 5} 张**(共 {len(多)})"
                           if len(多) > 5 else "")
       + " —— 新收了一批还没登记。**不算错,但清单会漂**:跑 `登记` 补上"
       if 多 else "没有")

    print((f"{R}❌ 交付图清单 {len(失败)} 条不过{D}") if 失败 else f"{G}✅ 交付图清单{D}")
    return 1 if 失败 else 0


def 自测(a=None):
    """三条咬合各自都要红,而且红的是指定那一条。"""
    import io, contextlib, tempfile, shutil
    global 清单档
    原 = 清单档
    d = tempfile.mkdtemp()
    img = os.path.join(d, "img"); os.makedirs(img)
    for i in range(3):
        open(os.path.join(img, f"lxys_10000000{i}-main.png"), "wb").write(b"PNG" + bytes([i]) * 50)
    清单档 = os.path.join(d, "清单.json")

    class A: pass
    参 = A(); 参.在 = img; 参.强制 = False
    with contextlib.redirect_stdout(io.StringIO()):
        登记(参)
    坏 = []

    def 跑():
        b = io.StringIO()
        with contextlib.redirect_stdout(b):
            rc = 验(参)
        return rc, b.getvalue()

    def 关(名, 期望, 改, 还原):
        rc0, _ = 跑()
        if rc0 != 0:
            坏.append(f"{名}:对照就不绿"); return
        改()
        rc1, out = 跑()
        if rc1 == 0:
            坏.append(f"{名}:改坏了却没红")
        elif f"❌ {期望}" not in out:
            坏.append(f"{名}:红的不是「{期望}」")
        else:
            print(f"  ✓ 咬合:{名} → 红的正是「{期望}」")
        还原()
        if 跑()[0] != 0:
            坏.append(f"{名}:还原之后没回到绿")

    一 = os.path.join(img, "lxys_100000000-main.png")
    原内容 = open(一, "rb").read()
    关("把某张图的内容改掉(文件名没变)", "图的内容和登记的一致",
       lambda: open(一, "wb").write(b"NOPE" * 20),
       lambda: open(一, "wb").write(原内容))
    关("删掉某张登记过的图", "登记过的图都还在",
       lambda: os.remove(一), lambda: open(一, "wb").write(原内容))
    多 = os.path.join(img, "lxys_999999999-main.png")
    关("往目录里放一张没登记的图", "目录里没有未登记的图",
       lambda: open(多, "wb").write(b"X" * 30), lambda: os.remove(多))

    # 反向:空目录必须说「没东西可验」,不能报成通过
    参2 = A(); 参2.在 = os.path.join(d, "空"); os.makedirs(参2.在, exist_ok=True)
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        验(参2)
    if "没东西可验" not in b.getvalue():
        坏.append("空目录没说「没东西可验」—— 和「都对」分不开")
    else:
        print("  ✓ 空目录明说「没东西可验」,不冒充通过")

    清单档 = 原
    shutil.rmtree(d, ignore_errors=True)
    print("交付图清单 · 咬合")
    for x in 坏:
        print(f"  ✗ {x}")
    print((f"{R}❌ 交付图咬合 {len(坏)} 条不过{D}") if 坏 else f"{G}✅ 交付图咬合:三条都咬得动{D}")
    return 1 if 坏 else 0


def main():
    p = argparse.ArgumentParser(description="交付图清单:图不进版本库,指纹进")
    sub = p.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("登记"); a1.set_defaults(fn=登记)
    a1.add_argument("--在"); a1.add_argument("--强制", action="store_true")
    a2 = sub.add_parser("验"); a2.set_defaults(fn=验); a2.add_argument("--在")
    a3 = sub.add_parser("自测"); a3.set_defaults(fn=自测)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
