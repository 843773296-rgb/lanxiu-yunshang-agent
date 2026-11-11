# -*- coding: utf-8 -*-
"""按款号列商品图(用户 2026-11-11 拍:版师核料、顾问都要能在聊天里看商品图)。

缘起:版师在聊天里要「调出商品照片或版型图原图」,助手答「我没有能取图的工具,找管理员」——
而图其实一直在系统里:`backend/static/img/` 下 2585 张出好的图,经业务后台 `/img/<款号>-<图位>.svg` 取
(有真图发真图,没有就按这款的颜色款式现画示意图,见 server.py 的 /img/ 那一段)。缺的只是一个查询口。

这里**只列、不画、不读库外的东西**:看这一款有哪些图位、每一位是**真图**还是**会现画的示意图** ——
两者在页面上长得都像一张图,而只有真图能拿来核料(示意图的颜色款式是推出来的,不能当实物看)。

图位命名(和 img.py / server.py 同一套):
  main 主图 · intro 详情 · d1–d3 细节 · skuN 第 N 个颜色的小图 · skuN-main / skuN-d1… 第 N 个颜色的整套
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
图目录 = os.path.join(HERE, "static", "img")
_后缀 = (".png", ".jpg", ".jpeg", ".webp")
_款号 = re.compile(r"^[A-Za-z0-9_]{1,40}$")
图位名 = {"main": "主图", "intro": "详情图", "d1": "细节图 1", "d2": "细节图 2", "d3": "细节图 3"}


def _图位中文(位):
    if 位 in 图位名:
        return 图位名[位]
    m = re.fullmatch(r"sku(\d+)(?:-(main|intro|d\d))?", 位)
    if m:
        return f"第 {m.group(1)} 个颜色" + (f"·{图位名.get(m.group(2), m.group(2))}" if m.group(2) else "小图")
    return 位


def 列图(spu, 目录=None):
    """→ {款号, 图: [{图位, 名称, 地址, 真图}], 真图数, 说明}。款号不合规 → {error}。纯函数(只看文件名)。"""
    spu = str(spu or "").strip()
    if not _款号.match(spu):
        return {"error": f"款号不像款号:{spu[:40]!r}(只收字母、数字、下划线)"}
    目录 = 目录 or 图目录
    真 = {}
    try:
        for f in os.listdir(目录):
            stem, ext = os.path.splitext(f)
            if ext.lower() in _后缀 and stem.startswith(spu + "-"):
                真[stem[len(spu) + 1:]] = True
    except FileNotFoundError:
        pass
    # 标准图位总列出来(没真图的会现画示意图),再补上这款额外有的真图位(多颜色整套)
    位们 = ["main", "intro", "d1", "d2", "d3"] + sorted(k for k in 真 if k not in 图位名)
    图 = [{"图位": 位, "名称": _图位中文(位), "地址": f"/img/{spu}-{位}.svg", "真图": bool(真.get(位))} for 位 in 位们]
    n = sum(1 for g in 图 if g["真图"])
    return {"款号": spu, "图": 图, "真图数": n,
            "说明": ("「真图」是出好的商品图;其余地址会按这款的颜色款式**现画示意图** —— 示意图不能当实物核料。"
                     + ("" if n else " ⚠️ 这一款一张真图都没有。"))}
