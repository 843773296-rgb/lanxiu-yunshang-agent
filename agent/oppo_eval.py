#!/usr/bin/env python3
"""「总结 + 商机研判 + 下一步」技能的判分器 —— **先写判分器,绿了才跑模型**(intent `opportunity-and-call-notes` ④)。

## 判的是能机器判定的东西,不是「总结得好不好」

立项时就写死了这条:判「该不该识别出商机」「下一步指的那件事是不是真在库里」。
「总结写得漂不漂亮」判分器判不了,也不该判 —— 判不了的东西硬判,成绩单就是噪声。

## 为什么要技能交一段固定格式的结果,而不是从正文里抠

从正文里抠「她说了想要红色」「下一步推那件月白马面裙」,是在枚举中文说法 ——
**词表永远差一个词**(评价那套题四次证明过,「不让价」那套上个月证明过一次)。
所以技能的回答**末尾必须带一段 JSON**,判分器只读这一段:

    {"商机": true,
     "诉求": [{"维度": "颜色", "值": "白", "原话": "我想要月白色的"}],
     "下一步": [{"做什么": "约她来看这条", "指向": [{"类": "商品", "id": "lxys_…", "对上": {"颜色": "白"}}]}]}

正文只做一件事:**正文里出现的编号也必须真在库里**(编号有固定形状,按形状找,不按说法找)。

## 八条判据(一律「查出坏的就返回一条话」,空 = 过;每条话以「类:」开头,对照按类核)

    格式   没交 JSON / JSON 里没有「商机」
    判断   商机判反了(和标注比;**标注只在判分器这边,绝不经工具给模型**)
    结构   判了是商机,却没有诉求或没有下一步 —— 「是商机」却说不出下一步,顾问拿着没用
    原话   诉求的原话不在逐字稿里 / **是顾问说的不是客户说的** / 维度不在口径里
    指向   下一步指的东西库里没有 / 商品已下架 / **方案、订单是别的客户的**
    对上   说「这件对上了白色」,库里查它没有白色系
    正文   正文里出现的商品 / 方案 / 订单编号库里没有
    概率   给了成单的数字(「八成能成」「把握 70%」)—— 业务定的:**给依据,不给概率**

⚠️ **「顾问说的」那一条最要紧。** 顾问介绍商品时一定会提颜色,
「我们这次进了一批红色的」和「我想要红色的」在全文里长得一模一样 —— 原话只在客户那几行里找。

## 跑法

判分器本身:`python3 agent/oppo_eval_judgetest.py`(不调模型,进 check.sh)。
真跑技能的那一半等技能写好再接(下一步 ③),**连跑两轮,一轮不作数**。
"""
import json, os, re, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")]
import oppo as KO, oppo_obj as K

DBP = os.path.join(ROOT, "backend", "lanxiu.db")

# ── 编号的形状(按形状找,不按说法找)────────────────────────────────
# 订单号是 19 位雪花号;前后不许再是数字,免得从更长的数字串里截一段
编号形状 = {
    "商品": r"lxys_\d{6,}",
    "方案": r"(?<![A-Za-z0-9])SC\d{4}(?!\d)",
    "订单": r"(?<!\d)\d{19}(?!\d)",
}
# 成单的数字:百分比 / 「N 成」(中文数字也算 —— 只认阿拉伯数字就是假定模型只会写阿拉伯数字)
_数 = r"\d+(?:\.\d+)?\s*[%\uff05]|百分之[一二三四五六七八九十百\d]+|[一二三四五六七八九十\d]\s*成"
# ⚠️ 光有数字不算 —— 「先付 30% 定金」是正常的下一步。**同一句里**还得在说成单这件事
成单词 = ("成单", "成交", "把握", "可能", "概率", "胜率", "拿下", "会买", "能成", "意向")


def _db():
    c = sqlite3.connect(f"file:{DBP}?mode=ro", uri=True)
    return c


def 抠结果(答):
    """回答末尾那段 JSON。先找 ```json 块(取最后一块),再退到最后一个含「商机」的 {…}。抠不到返回 None。"""
    块 = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", 答 or "", re.S)
    候选 = list(reversed(块))
    if not 候选:
        # 从最后一个「{」往前试,直到解析得出来 —— 正文里可能也有花括号
        for m in reversed(list(re.finditer(r"\{", 答 or ""))):
            候选.append(答[m.start():答.rfind("}") + 1])
    for s in 候选:
        try:
            d = json.loads(s)
        except Exception:
            continue
        if isinstance(d, dict) and "商机" in d:
            return d
    return None


def _是(v):
    """「商机」可能写成 true / "是" / "有"。"""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "是", "有", "yes", "1")


def _规整(s):
    """比原话前先抹掉空白和全半角标点的差别 —— 模型抄原话时常把「,」写成「，」。"""
    s = re.sub(r"\s+", "", s or "")
    全 = "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\uff08\uff09"   # ,。!?;:() 的全角
    return s.translate(str.maketrans(全, ",.!?;:()")).replace("……", "…")


def _句(text):
    return [x for x in re.split(r"(?<=[。!?!?;;\n])", text or "") if x.strip()]


# ── 各条判据 ──────────────────────────────────────────────────────────
def 查原话(诉求们, 逐字稿):
    客户 = _规整(KO.客户说的(逐字稿))
    全文 = _规整(逐字稿)
    坏 = []
    for x in 诉求们:
        维, 原 = x.get("维度"), (x.get("原话") or "").strip()
        if 维 not in K.诉求维度:
            坏.append(f"原话:「{维}」不是诉求维度(口径里只有:{'、'.join(K.诉求维度)})")
            continue
        if not 原:
            坏.append(f"原话:「{维}={x.get('值')}」没给原话 —— 指不回原话的诉求,顾问一问「凭什么」就答不上")
        elif _规整(原) not in 客户:
            if _规整(原) in 全文:
                坏.append(f"原话:「{原[:24]}」是顾问说的,不是客户说的 —— 顾问介绍商品时一定会提颜色")
            else:
                坏.append(f"原话:「{原[:24]}」逐字稿里没有这句")
    return 坏


def 查指向(c, 下一步们, 客户):
    坏 = []
    for 步 in 下一步们:
        for p in 步.get("指向") or []:
            类, i = p.get("类"), str(p.get("id") or "")
            if 类 == "商品":
                r = c.execute("SELECT status FROM product WHERE spu=?", (i,)).fetchone()
                if not r:
                    坏.append(f"指向:商品 {i} 库里没有")
                elif r[0] != "上架":
                    坏.append(f"指向:商品 {i} 已{r[0]} —— 推给客户她也买不到")
                else:
                    坏 += 查对上(c, i, p.get("对上") or {})
            elif 类 in ("方案", "订单"):
                表 = {"方案": "scheme", "订单": "ordr"}[类]
                r = c.execute(f"SELECT customer_id FROM {表} WHERE id=?", (i,)).fetchone()
                if not r:
                    坏.append(f"指向:{类} {i} 库里没有")
                elif r[0] != 客户:
                    坏.append(f"指向:{类} {i} 是 {r[0]} 的,不是这位客户({客户})的")
            elif 类 == "版型":
                if not c.execute("SELECT 1 FROM pattern WHERE code=?", (i,)).fetchone():
                    坏.append(f"指向:版型 {i} 库里没有")
            else:
                坏.append(f"指向:不认识的指向类型「{类}」(只认 商品 / 方案 / 订单 / 版型)")
    return 坏


def 查对上(c, spu, 对上):
    # 只取查货那一个函数。这个文件现在**不调模型**;等真跑技能的那一半接进来,
    # rounds_check 会把它认成调模型的评测、要求跑两轮 —— 那是对的,别绕
    from opportunity_store import 满足吗
    坏 = []
    for 维, 值 in 对上.items():
        ok, _ = 满足吗(c, spu, 维, 值)
        if not ok:
            坏.append(f"对上:说 {spu} 对上了「{维}={值}」,库里查它没有")
    return 坏


def 查正文编号(c, 正文):
    坏 = []
    for 类, 形 in 编号形状.items():
        表, 列 = {"商品": ("product", "spu"), "方案": ("scheme", "id"), "订单": ("ordr", "id")}[类]
        for i in sorted(set(re.findall(形, 正文))):
            if not c.execute(f"SELECT 1 FROM {表} WHERE {列}=?", (i,)).fetchone():
                坏.append(f"正文:提到的{类} {i} 库里没有")
    return 坏


def 查概率(答, 诉求们):
    """成单的数字。客户原话里的数字不算(「降 20% 我就要」是她说的,不是我们给的概率)。"""
    文 = 答 or ""
    for x in 诉求们:
        if x.get("原话"):
            文 = 文.replace(x["原话"], "")
    for 句 in _句(文):
        if re.search(_数, 句) and any(w in 句 for w in 成单词):
            return [f"概率:给了成单的数字「{句.strip()[:30]}」—— 业务定的是给依据、不给概率"]
    return []


def 判(答, 逐字稿, 客户, 应该):
    """答 = 技能的整段回答;应该 = 标注(这通该不该识别出商机)。返回 [挂的理由],空 = 过。"""
    d = 抠结果(答)
    if d is None:
        return ["格式:回答末尾没有带「商机」的 JSON —— 判分器只读那一段,不从正文里抠"]
    是 = _是(d.get("商机"))
    诉求们 = [x for x in (d.get("诉求") or []) if isinstance(x, dict)]
    下一步们 = [x for x in (d.get("下一步") or []) if isinstance(x, dict)]
    坏 = []
    if 是 != 应该:
        坏.append(f"判断:判成{'是' if 是 else '不是'}商机,标注是{'是' if 应该 else '不是'}")
    if 是:
        if not 诉求们:
            坏.append("结构:判了是商机,却没列诉求 —— 说不出客户要什么")
        if not any(x.get("指向") for x in 下一步们):
            坏.append("结构:判了是商机,下一步却没指向库里任何东西 —— 顾问拿着不知道去推哪件")
    坏 += 查原话(诉求们, 逐字稿)
    c = _db()
    try:
        坏 += 查指向(c, 下一步们, 客户)
        坏 += 查正文编号(c, 答 or "")
    finally:
        c.close()
    坏 += 查概率(答, 诉求们)
    return 坏
