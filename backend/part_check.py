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
外层部位一律给全部可选主料,**由客户自己挑**(2026-09-14 拍板)——
而不是编一套「领口适合织金缎」出来假装业务拍过板。
⚠️ **这和「还没细分」不是一回事,虽然数据长得一模一样** ——
前者是欠着一件事,后者是已经决定不做那件事。

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


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把一种裁片改名成归并规则认不出来的名字',
     '每一种裁片都归得进某个部位'),
]

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
    # ⚠️ **这条判据改过两次,两次都是前提变了、不是代码错了。**
    #
    # 第一版守的是「不许替业务自动拆」—— 那时业务还没说要不要细分。
    # 后来加了工艺维度,拿混在一起的集合去比整件面料,红;改成按 `kind` 分开比。
    # 2026-09-14 业务说「还没细分,你直接分配」——**前提又变了**:
    # 现在要守的不是「不许分」,是「**分必须有依据**」。
    #
    # **一条判据的前提变了,要改的是它守什么,不是把它关掉。**
    # 它防的那件事(凭空编细分)依然要防,只是标准换了:
    #
    #   内衬 / 系带  按**材料类别**给(BOM 备注里版师写着「挂里→真丝里布」)
    #   其余外层部位 给**这个商品的全部可选主料** ——
    #                「领口适合织金缎、主身适合素缎」是审美判断不是结构事实,
    #                库里没有依据支持它,编一个就是假装业务拍过板
    坏 = []
    for r in c.execute("SELECT p.spu,p.name,pc.mt_opts,pc.kf_opts FROM product p "
                       "JOIN product_custom pc ON pc.spu=p.spu "
                       "WHERE p.kind='定制品' AND p.pattern IS NOT NULL"):
        for 维, 源 in (("面料", r["mt_opts"]), ("工艺", r["kf_opts"])):
            整 = {x.strip() for x in (源 or "").split(",") if x.strip()}
            if not 整:
                continue
            for b, in c.execute(
                    "SELECT DISTINCT part FROM part_option WHERE spu=? AND kind=?",
                    (r["spu"], 维)):
                有 = {x[0] for x in c.execute(
                    "SELECT material FROM part_option WHERE spu=? AND kind=? AND part=?",
                    (r["spu"], 维, b))}
                类 = part.部位可选料类(b)
                if 维 == "面料" and 类 != ("主料",):
                    # 有依据的那几个部位:验**都来自该类别**,不验等于整件可选
                    野2 = [m for m in 有 if (c.execute(
                        "SELECT cat FROM material WHERE name=?", (m,)).fetchone()
                        or ["?"])[0] not in 类]
                    if 野2:
                        坏.append(f"{r['name'][:14]}·{b}:{野2} 不是{类[0]} —— "
                                  f"依据是 BOM 备注(挂里→真丝里布)")
                    continue
                if 有 != 整:
                    坏.append(f"{r['name'][:14]}·{b}·{维}:{sorted(有)} ≠ 整件 {sorted(整)}")
    n3 = c.execute("SELECT COUNT(DISTINCT spu) FROM part_option").fetchone()[0]
    ck("部位的可选料要有依据(内衬走里料,外层不细分)", not 坏, n3,
       ("；".join(坏[:2]) if 坏 else
        "内衬 / 系带按材料类别(BOM 备注是版师写的);"
        "**外层部位不细分** —— 「领口适合织金缎」是审美判断不是结构事实,"
        "编一个就是假装业务拍过板"))

    # ④ 报价口径要跟着数据一起出现在页面上
    web = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
    # ⚠️ 判据原来写死了 `part_quote_base` 这个字段名,而报价从
    # 「整件按最贵的料」改成「按部位分摊」之后字段改叫 `part_fabric_cost` ——
    # 当场红。**判据贴着字段名,字段名一改它就误报。**
    # 改成验**这件事做到了没有**:页面上要有报价口径那段话,
    # 而且要把「这个数是估的还是版师核过的」显示出来。
    有口径 = "part_note" in web and "报价口径" in web
    有料费 = "part_fabric_cost" in web or "part_quote_base" in web
    有来源 = "用料来源" in web and "含估算" in web
    ck("报价口径和「估算/已核」要出现在页面上", 有口径 and 有料费 and 有来源, 3,
       "" if (有口径 and 有料费 and 有来源) else
       f"口径={有口径} 料费={有料费} 来源标记={有来源}")
    if 有口径 and 有料费 and 有来源:
        print("       **一个标着「实价」的估算值,比一个标着「上限」的估算值糟得多**")


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
