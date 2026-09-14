#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分部位可选料的检查。

## 背景

2026-09-14 业务确认:**门店接单时客户分部位选料,记在 pad 上**。
pad 上那份不进报价、不进 BOM、不进工单,也和订单没有绑定关系 ——
**一个在 pad 上流转的字段,和一个不存在的字段,在系统里效果一样。**

本期做第一步:把结构立起来,**算料先不动**(见下面第 ④ 条)。

## 五条各防一种「不报错的错」

**① 裁片不许静默丢。** 部位是从裁片归并来的,归不进去的裁片会让那个部位
在配置页上**整个消失** —— 而页面上只是少一行,看起来像「这件衣服没有这个部位」。

**② 部位要随形制变。** 马面裙不该有领口。写死一份部位清单的话,
扩一个形制就错一次,而错的方式是**多出一个客户选不了的部位**。

**③ 不许自动把整件可选料拆到部位上。** 那等于替业务做了一次没人拍过的决定。
每个部位先给全部整件可选料,意思是「还没细分」,**不是假装已经细分过了**。

**④ 报价口径必须跟着数据一起出现在页面上。**
只写在文档里的话,看页面的人不会去翻文档,**而他会直接把这个价报给客户**。

**⑤ 相容矩阵不许加部位维度。** 现在 2025 格,乘上部位就是几万格。
而且没必要:「苏绣能不能做在真丝上」和做在哪个部位无关。
"""
import os, sys, sqlite3, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
_spec = importlib.util.spec_from_file_location(
    "part", os.path.join(os.path.dirname(HERE), "knowledge", "part.py"))
part = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(part)
FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok:
        FAIL.append(name)
    if n == 0:
        print("       ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(空)")


def main():
    c = sqlite3.connect(os.path.join(HERE, "lanxiu.db"))
    c.row_factory = sqlite3.Row

    # ① 每一种裁片都要归得进某个部位
    名 = [r[0] for r in c.execute("SELECT DISTINCT name FROM pattern_piece")]
    丢 = [n for n in 名 if part.归部位(n) is None]
    ck("每一种裁片都归得进某个部位", not 丢, len(名),
       (f"归不进去的:{丢[:5]}" if 丢 else
        "**归不进去的裁片会让那个部位在配置页上整个消失** —— "
        "而页面上只是少一行,看起来像「这件衣服没有这个部位」"))

    # ①·2 顺序有意义:「开衩贴边」在下摆,不在门襟
    ck("归并规则的顺序有意义(开衩贴边 → 下摆)",
       part.归部位("开衩贴边") == "下摆", 1,
       f"实得 {part.归部位('开衩贴边')} —— 第一版排反了,把它归进了门襟")

    # ② 部位随形制变
    裙 = set(part.形制的部位(c, "PT04"))        # 明制马面裙
    衫 = set(part.形制的部位(c, "PT06"))        # 明制立领长衫
    ck("部位随形制变(马面裙没有领口,立领长衫有)",
       "领口" not in 裙 and "领口" in 衫, 2,
       f"马面裙 {sorted(裙)} / 立领长衫 {sorted(衫)}")

    # ③ 没有哪个部位的可选料**少于**整件可选料 —— 少了就是被自动拆过
    坏 = []
    for r in c.execute("SELECT p.spu,p.name,pc.mt_opts FROM product p "
                       "JOIN product_custom pc ON pc.spu=p.spu "
                       "WHERE p.kind='定制品' AND p.pattern IS NOT NULL"):
        整 = {x.strip() for x in (r["mt_opts"] or "").split(",") if x.strip()}
        if not 整:
            continue
        for b, in c.execute("SELECT DISTINCT part FROM part_option WHERE spu=?",
                            (r["spu"],)):
            有 = {x[0] for x in c.execute(
                "SELECT material FROM part_option WHERE spu=? AND part=?",
                (r["spu"], b))}
            if 有 != 整:
                坏.append(f"{r['name'][:16]}·{b}:{sorted(有)} ≠ 整件 {sorted(整)}")
    n3 = c.execute("SELECT COUNT(DISTINCT spu) FROM part_option").fetchone()[0]
    ck("每个部位先给全部整件可选料(不自动拆)", not 坏, n3,
       ("；".join(坏[:2]) if 坏 else
        "**自动拆等于替业务做了一次没人拍过的决定** —— "
        "「还没细分」和「已经细分过了」是两回事"))

    # ④ 报价口径要跟着数据一起出现在页面上
    web = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    有 = "part_note" in web and "报价口径" in web and "part_quote_base" in web
    ck("报价口径要出现在页面上,不能只写在文档里", 有, 1,
       "" if 有 else "页面上没渲染 part_note / 报价基准")
    if 有:
        print("       **看页面的人不会去翻文档,而他会直接把这个价报给客户**")

    # ⑤ 相容矩阵不许多出部位维度
    cols = {r[1] for r in c.execute("PRAGMA table_info(craft_combo)")}
    ck("相容矩阵不许加部位维度", "part" not in cols and "部位" not in cols, len(cols),
       "现在 2025 格,乘上部位就是几万格 —— "
       "而且「苏绣能不能做在真丝上」和做在哪个部位无关")
    c.close()

    print("=" * 84)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 分部位可选料 6 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
