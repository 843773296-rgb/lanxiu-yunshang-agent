# -*- coding: utf-8 -*-
"""商机判断:这通电话里,有没有值得跟进的生意。

业务定的边界:**agent 只给参谋 —— 是不是需要去促活,是不是满足商机条件。**
所以这里和 `revive.py` 一样,输出是**一个布尔加一句人话**,顾问照着它去谈。

## 商机的三个条件(业务举的原例拆出来的)

业务原话:*「某个客户说想要红色的衣服,但最后没买成,或者买了蓝色,
近期上新了红色款的衣服,那么这也是商机」*。拆开是三段:

    ① 客户表达过一个偏好          「想要红色的」
    ② 那个偏好能归到某个维度      颜色 / 纹样 / 场合 / 形制
    ③ 当时没满足,而现在能满足了    「最后买了蓝色」+「近期上新了红色」

三条缺一不可。缺 ① 是没话可说,缺 ② 是查不到货,缺 ③ 是没有新理由联系他。

## 🔑 最要紧的一条判据:**分清是谁说的**

逐字稿里「红色」这两个字,可能是客户说的,也可能是顾问说的:

    顾问:我们这次进了一批红色的
    客户:我想要红色的

**在全文匹配里这两句长得一模一样** —— 都含「红色」。
而前者是推销,后者才是商机。

所以这里先按说话人切开,**只看客户说的那些行**。
这一条不做,一个「见颜色词就报商机」的实现会在正例上拿满分,
而它在负例上也会全报商机 —— 因为顾问介绍商品时一定会提到颜色。

## ⚠️ 不枚举中文说法

CLAUDE.md 记着这个项目为「枚举中文短语」栽过**七次**:
「想要」「喜欢」「要是有就好了」「看看有没有」…… 同一个意思的写法接近无限。

所以这里**不判「他有没有表达想要」**,改判**结构**:
客户说的话里出现了具体的维度词(某个颜色 / 某个形制 / 某个纹样 / 某个场合),
而且那个词**没有被否定**(用 `textmatch`,它钉死了中文否定的七个坑)。

「随便看看」「再想想」「帮朋友问问」之所以不算商机,
不是因为我枚举了这三句,而是因为**它们里面没有任何具体的维度词**。
"""
import os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
DB = os.path.join(HERE, "lanxiu.db")
import textmatch


def _rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


# ── 维度词表:**一律从库里现读**,不写死 ─────────────────────────
# 写死的后果:业务上新一个形制、加一个场合,判断就漏掉它 ——
# 而漏掉不报错,只是少报一条商机。
# ⚠️ **客户嘴里的词 ≠ 库里的词。这是第三套词汇。**
#
#     客户说      库里的色名     色系
#     烟紫色  →   藕荷      →   紫
#     拍照片  →   (无)      →   旅拍写真
#
# 今天做的 color_family 只连了后两套。这里补第一套 ——
# **不补的话,客户说「想拍照」而词表写「旅拍写真」,一个字都对不上,
# 判成「没提到任何偏好」,而这个结论看起来完全正常。**
#
# 颜色靠基本色字兜住(「烟紫色」含「紫」);场合得列同义说法。
# ⚠️ 这张同义表**应该进配置**(sys_code 的 note),现在先写在这儿 ——
# 写死的代价是业务加一个场合要改代码。记在 P2 待办里。
场合同义 = {
    "旅拍写真": ["旅拍", "写真", "拍照", "拍片", "摄影", "外拍"],
    "婚礼婚服": ["婚礼", "结婚", "喜宴", "办酒", "嫁衣", "新娘"],
    "节庆礼仪": ["过年", "春节", "中秋", "节日", "上巳", "元宵"],
    "正式场合": ["正式", "商务", "年会", "典礼", "看戏"],
    "日常通勤": ["日常", "通勤", "上班", "平时穿"],
    "演出舞台": ["演出", "舞台", "表演"],
    "运动户外": ["运动", "户外", "爬山"],
    "居家休闲": ["居家", "休闲", "在家"],
}


def 词表():
    颜色 = {}
    for r in _rows("select distinct family from color_family where family is not null"):
        颜色[r["family"]] = "颜色"
    # 形制:`xingzhi` 和 `craft` 两张表内容重复(都是形制名),只取一张 ——
    # **第一版把 craft 当纹样用,于是「大袖衫」被判成了纹样。**
    # 形制:库里是全称(「宋制褙子」),**客户说的是简称**(「褙子」)——
    # 又是第三套词汇。所以每个形制名同时收它去掉朝代前缀后的简称。
    # 不收的话,客户说「想定一条圆领袍」会被判成「没提到任何偏好」,
    # **而这个结论看起来完全正常**。
    形制 = {}
    for r in _rows("select name from xingzhi"):
        全 = r["name"]
        形制[全] = "形制"
        简 = re.sub(r"^(唐制|宋制|明制|汉制|清制)", "", 全)
        if 简 and 简 != 全 and len(简) >= 2:
            形制[简] = "形制"
    # 纹样:走口径模块,不自己列 —— 它是唯一真相源(knowledge/motif.py)
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    try:
        import motif
        纹样 = {w: "纹样" for w in motif.词表() if w != "无纹样"}
    except Exception:
        纹样 = {}
    场合 = {r["name"]: "场合" for r in _rows(
        "select name from sys_code where category='场合' and status='启用'")}
    return 颜色, 形制, 纹样, 场合


def 客户说的(逐字稿):
    """只取客户那几行。

    **「顾问提到红色」和「客户想要红色」在全文里长得一模一样** ——
    这个函数就是用来分开它们的。
    """
    出 = []
    for 行 in (逐字稿 or "").splitlines():
        行 = 行.strip()
        m = re.match(r"^(客户|顾客|王女士|李先生|客)\s*[:：](.*)$", 行)
        if m:
            出.append(m.group(2).strip())
    return "\n".join(出)


def 命中维度(客户话):
    """客户说的话里,出现了哪些维度词(未被否定的)。"""
    颜色, 形制, 纹样, 场合 = 词表()
    中 = []
    # 颜色:用基本色字,兜住「烟紫色」「明黄色」这类客户自己的说法
    for 色 in 颜色:
        for 字 in (色 if len(色) == 1 else [色]):
            if textmatch.says(客户话, [字]):
                中.append((色, "颜色", 字)); break
    for 表, 维度 in ((形制, "形制"), (纹样, "纹样")):
        for 词 in 表:
            if len(词) >= 2 and textmatch.says(客户话, [词]):
                中.append((词, 维度, 词))
    # 场合:客户不会说「旅拍写真」,他说「拍照」「想拍套片子」
    for 场, 同义 in 场合同义.items():
        if 场 not in 场合:
            continue
        命 = textmatch.says(客户话, [场] + 同义)
        if 命:
            中.append((场, "场合", 命))
    # 去重:同一个维度只留第一个
    seen, out = set(), []
    for 词, 维度, 命 in 中:
        if 维度 not in seen:
            seen.add(维度); out.append((词, 维度, 命))
    return out


def 现在有货(维度, 词):
    """这个偏好,现在店里满足得了吗 —— 条件③。"""
    if 维度 == "颜色":
        n = _rows("""select count(distinct s.spu) n from sku s
                     join color_family f on s.color=f.color
                     where f.family=?""", 词)
        return n[0]["n"] if n else 0
    if 维度 == "场合":
        n = _rows("""select count(*) n from product_scene ps
                     join sys_code c on c.code=ps.scene
                     where c.name=?""", 词)
        return n[0]["n"] if n else 0
    if 维度 == "形制":
        # ⚠️ 第一版查的是 `product.template` —— 那是**量体模版**(LT01 唐装模版),
        # 不是形制。查不到不报错,只是恒返回 0,于是所有形制商机都被判成「没货」。
        # 正确路径:product.pattern → pattern.code,形制在 pattern.xz
        # 用 like 而不是 = —— 客户说的简称要能查到全称的货
        n = _rows("""select count(*) n from product p join pattern t on p.pattern=t.code
                     where t.xz like ?""", f"%{词}%")
        m = _rows("select count(*) n from product_custom where xz like ?", f"%{词}%")
        return (n[0]["n"] if n else 0) + (m[0]["n"] if m else 0)
    if 维度 == "纹样":
        # 纹样是**算出来的**(knowledge/motif.py 从商品名和面料推),不落库。
        # 这里按商品名里有没有这个纹样词粗算 —— 够回答「店里有没有」这个问题。
        n = _rows("select count(*) n from product where name like ?", f"%{词}%")
        return n[0]["n"] if n else 0
    return 0


def 判断(逐字稿, customer_id=None):
    """这通电话里有没有商机。返回 (是不是, 码, 人话理由)。"""
    话 = 客户说的(逐字稿)
    if not 话:
        return False, "NO_CUSTOMER_LINE", "这份逐字稿里没有客户说的话 —— **分不清是谁说的就判不了**"

    中 = 命中维度(话)
    if not 中:
        return False, "NO_DIMENSION", (
            "客户没提到任何具体的偏好(颜色/形制/纹样/场合)—— "
            "**「随便看看」「再想想」这类话里没有可查的东西**,顾问跟进也没话说")

    理由 = []
    for 词, 维度, 命 in 中:
        n = 现在有货(维度, 词)
        if n:
            理由.append(f"客户提到**{命}**({维度}),店里现在有 {n} 款对得上")
        else:
            理由.append(f"客户提到**{命}**({维度}),但**店里现在没有对得上的货** —— 这条跟进也没用")

    有货的 = [r for r in 理由 if "没有对得上" not in r]
    if not 有货的:
        return False, "NO_STOCK", ";".join(理由) + " —— 三个条件里缺了「现在能满足」"
    return True, 中[0][1], ";".join(有货的)


if __name__ == "__main__":
    for r in _rows("select audio_id, text from call_transcript where audio_id like 'TS-%' limit 3"):
        ok, code, why = 判断(r["text"])
        print(f"{r['audio_id']} {'商机' if ok else '不是'} [{code}] {why[:90]}")
