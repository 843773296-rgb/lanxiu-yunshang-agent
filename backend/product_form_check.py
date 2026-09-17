#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品表单检查 —— **详情页显示的字段,编辑表单里就得改得了。**

## 为什么要有这条

对照设计稿时查出来:详情页基本信息块有 12 项,而**编辑表单只有 5 项** ——
吊牌价 / 计量单位 / 性别 / 佣金方式 / 佣金比例 / 备注 / 主图
**只有新建时写一次,之后永远改不了**。

而这不会报错。表现出来只是「点编辑,看到的字段比详情页少」——
**一个只读的字段和一个「显示了但改不了」的字段,在页面上长得一样。**

所以这条检查把三处对起来,少一处就红:

    详情页渲染的字段   ←→   编辑表单的字段   ←→   写入语句真的覆盖的字段

三处都从**源码**取,不手抄 —— 手抄件不会自己告诉你它旧了。
"""
import os, re, sys, json, sqlite3, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
FAIL = []


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('往写入覆盖的字段清单里加一项,而编辑表单里没有它(能写却改不了)',
     '写入能改的字段,编辑表单里都要有'),
]

def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    srv = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    web = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()

    # ① 编辑表单的字段 ⊇ 写入真的覆盖的字段
    m = re.search(r"写入覆盖的字段 = \(([^)]*)\)", srv)
    写的 = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
    f = re.search(r"async function formProduct\(cur,after\)\{(.*?)\n\}", web, re.S)
    表单 = set(re.findall(r'\{k:"(\w+)"', f.group(1))) if f else set()
    缺 = 写的 - 表单
    ck("写入能改的字段,编辑表单里都要有", not 缺, len(写的),
       (f"表单里没有 {sorted(缺)} —— **改不了的字段等于只读**" if 缺 else
        "**一个只读的字段和一个「显示了但改不了」的字段,在页面上长得一样**"))

    # ② 详情页显示的字段,要么在表单里能改,要么是**明确只读**的那几个
    只读 = {"spu", "created", "updated", "on_shelf_at", "status", "pattern",
            "cat_path", "cat_name"}   # 编码、时间戳、状态(走上下架)、版型(走挂版型)
    显示 = set(re.findall(r'd\.(\w+)\|\|""', web)) | set(re.findall(r'esc\(d\.(\w+)', web))
    显示 &= {"name", "category", "kind", "base_price", "tag_price", "unit", "gender",
             "points", "commission_type", "commission_val", "remark", "template",
             "img_main", "spu", "created", "updated", "on_shelf_at", "status"}
    漏 = 显示 - 表单 - 只读
    ck("详情页显示的字段,要么能改、要么是明确只读的", not 漏, len(显示),
       (f"{sorted(漏)} 显示了但既改不了、也没被列为只读" if 漏 else
        f"只读的那几个是有理由的:编码 / 时间戳 / 状态(走上下架)/ 版型(走挂版型)"))

    # ③ 图片字段:两种形状都要读得出来(换格式最容易出「新代码 + 旧数据」)
    import server
    b_new = server.读轮播图(json.dumps({"小程序": ["a"], "ipad": ["b"]}, ensure_ascii=False))
    b_old = server.读轮播图(json.dumps(["a", "b"]))
    g_new = server.读详情图(json.dumps([{"组名": "保养", "图": ["a"]}], ensure_ascii=False))
    g_old = server.读详情图(json.dumps(["a"]))
    好 = (b_new["ipad"] == ["b"] and b_old["小程序"] == ["a", "b"] and not b_old["ipad"]
          and g_new[0]["组名"] == "保养" and g_old[0]["组名"] == "商品信息")
    ck("轮播图/详情图:新旧两种形状都读得出来", 好, 4,
       "" if 好 else f"{b_new} {b_old} {g_new} {g_old}",)
    if 好:
        print("       旧数据不会报错,只会让页面上少一块图 —— **看起来像没上传过**")

    # ④ 备注的署名**从日志派生,不许另存一列**
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    cols = {r[1] for r in c.execute("PRAGMA table_info(product)")}
    多余 = cols & {"remark_by", "remark_at"}
    ck("备注署名不许另存一列(从编辑日志派生)", not 多余, len(cols),
       (f"多了 {sorted(多余)} —— **同一个事实两个来源必然漂**" if 多余 else
        "日志里已经记着「备注 X → Y、谁、什么时候」,再存一份就会不一致而且不报错"))

    # ⑤ 供应商编码:标品该有,定制品**本来就不该有**
    标 = c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                   "WHERE p.kind='标品' AND (s.supplier_code IS NULL OR s.supplier_code='')"
                   ).fetchone()[0]
    定 = c.execute("SELECT COUNT(*) FROM sku s JOIN product p ON p.spu=s.spu "
                   "WHERE p.kind='定制品' AND s.supplier_code IS NOT NULL").fetchone()[0]
    n5 = c.execute("SELECT COUNT(*) FROM sku").fetchone()[0]
    ck("供应商编码:标品有、定制品没有", 标 == 0 and 定 == 0, n5,
       (f"标品缺 {标} 个 / 定制品多 {定} 个" if (标 or 定) else
        "**「没有供应商编码」和「还没填供应商编码」是两回事** —— "
        "定制品不是进的货,是自己做的"))
    c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 商品表单 5 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
