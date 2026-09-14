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

    # ⑤·前 **部位词只能有一个来源。**
    # 2026-09-14 业务裁决:设计交互稿里部位的叫法**自己就不统一**
    # (pad 配置页写「上身 / 袖子 / 内衬」,工艺文档打印稿写「领口 / 裙摆」),
    # **以 `knowledge/part.py` 这套为准,交互稿按这套改**。
    #
    # 裁决写在代码里还不够 —— 下一个人照着交互稿改的时候,
    # 很可能顺手在页面上写一个「上身」。**单一来源不靠自觉,靠检查。**
    # 报错要说得出**该用哪个词**:光说「不许用」,人还得自己猜。
    # ⚠️ **只查「真的当部位值用」的地方,不查字符串出现过没有。**
    # 第一版直接 grep,三处里两处是误报:
    #   「采集**上身**与裙长」「仅**上身**,用于褙子」—— 那是**量体模板的描述**,
    #   「上身」在那儿是日常汉语(量哪个部位的尺寸),不是部位枚举值。
    # **判据贴着字面,不贴着含义** —— 这个项目为这句话栽过好几次。
    #
    # 现在只认这几种「当值用」的写法:引号包起来的、等号右边的、注释里当枚举列的。
    import re as _re
    扫 = ["backend/server.py", "backend/web/index.html", "backend/seed.py",
          "knowledge/part.py"]
    硬编 = []
    for rel in 扫:
        fp = os.path.join(os.path.dirname(HERE), rel)
        if not os.path.exists(fp):
            continue
        if rel.endswith("part.py"):
            continue                     # 唯一来源自己要列出旧称,不算硬编
        txt = open(fp, encoding="utf-8").read()
        for 旧, 新 in part.交互稿旧称.items():
            # 当值用:"上身" / '上身' / 「上身」 且左右不是裁片后缀
            pat = _re.compile(r'["\'「]' + 旧 + r'["\'」]')
            for m in pat.finditer(txt):
                行头 = txt.rfind("\n", 0, m.start()) + 1
                行 = txt[行头:txt.find("\n", m.end())]
                if "裁片" in 行 or "前片" in 行 or "后片" in 行:
                    continue             # 裁片名,是版房的词,本来就该在
                硬编.append(f"{rel}:{行.strip()[:40]} —— 「{旧}」该用「{新}」")
    # 库里的数据也不许有旧称
    野 = [r[0] for r in c.execute(
        "SELECT DISTINCT part FROM part_option UNION "
        "SELECT DISTINCT part FROM item_part_choice")
        if r[0] not in part.部位顺序]
    ck("库里的部位词都来自唯一来源", not 野,
       c.execute("SELECT COUNT(DISTINCT part) FROM part_option").fetchone()[0],
       (f"野词:{野} —— 该用 {part.部位顺序}" if 野 else
        "**单一来源不靠自觉,靠检查** —— 交互稿里那套(上身/袖子/裙摆)不采用"))
    ck("代码和页面里不许硬编交互稿那套部位词", not 硬编, len(part.交互稿旧称),
       ("；".join(硬编[:3]) if 硬编 else
        "报错会说得出该用哪个词 —— **光说「不许用」,人还得自己猜**"))

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
    print("✅ 分部位可选料 8 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
