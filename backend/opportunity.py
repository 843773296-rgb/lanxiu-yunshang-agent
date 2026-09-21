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
# 判定口径在 knowledge/oppo.py,这里只负责**取数**:词表从库里读、有没有货去查。
# (模块叫 oppo 不叫 opportunity:和这个文件同名的话 `import opportunity`
#  会先找到这个文件自己,而「导入成功了」和「导入对了」长得一样。)
sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
import oppo as _口径

场合同义 = _口径.场合同义          # 只有一份,这里是转发不是抄件
客户说的 = _口径.客户说的
模型提示 = _口径.模型提示


def _rows(sql, *a):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, a)]


# ── 维度词表:**一律从库里现读**,不写死 ─────────────────────────
# 写死的后果:业务上新一个形制、加一个场合,判断就漏掉它 ——
# 而漏掉不报错,只是少报一条商机。
# ⚠️ **客户嘴里的词 ≠ 库里的词**(「烟紫色」/「拍照片」)——
# 那套对应关系在 `knowledge/oppo.py`,不在这儿。


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


def 命中维度(客户话):
    """客户说的话里出现了哪些维度词 —— **判定在 `knowledge/oppo.py`,这里只给词表**。"""
    颜色, 形制, 纹样, 场合 = 词表()
    return _口径.命中维度(客户话, 颜色, 形制, 纹样, 场合)


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
    """这通电话里有没有商机。返回 (是不是, 码, 人话理由)。

    三个条件的组装在 `knowledge/oppo.判`,这里只把它要的两样东西查出来:
    客户说了什么(切说话人)、每个偏好店里现在有几款对得上。
    """
    话 = 客户说的(逐字稿)
    中 = 命中维度(话) if 话 else []
    有货 = {(词, 维度): 现在有货(维度, 词) for 词, 维度, _ in 中}
    return _口径.判(bool(话), 中, 有货)


if __name__ == "__main__":
    for r in _rows("select audio_id, text from call_transcript where audio_id like 'TS-%' limit 3"):
        ok, code, why = 判断(r["text"])
        print(f"{r['audio_id']} {'商机' if ok else '不是'} [{code}] {why[:90]}")


# ══════════════════════════════════════════════════════════════════
# 模型层:判断「未满足的需求」
# ══════════════════════════════════════════════════════════════════
#
# 规则版的天花板量出来了:24 条里误报 7 条,**全是同一个形状** ——
#
#     客户说「齐胸襦裙听起来不错啊。但是呢,我先不急着定,想再想想。」
#     规则看到维度词 + 店里有货 → 判成商机。而他只是随口一提。
#
# 要分开「想要」和「提到」,得判断**有没有一个当时没被满足的具体需求**。
# 而这件事**步骤枚举不出来** —— 同一个意思的中文写法接近无限
# (CLAUDE.md 记着这个项目为「枚举中文短语」栽过七次)。
#
# 按项目的判断标准:**步骤能枚举就停在规则,不能才上模型**。
# 所以分工是:
#
#     维度识别(提到了什么颜色/形制/纹样/场合)   → 规则。确定性、免费、进门禁
#     店里现在有没有对得上的货                   → 规则
#     **客户是真想要还是随口一提**                → 模型。只回答这一个问题
#
# ⚠️ 模型层**不进门禁**:它要花钱、有随机性,而
# 「依赖外部状态的检查放进门禁会变成随机拦路」(CLAUDE.md)。
# 它的评测单独跑,而且**连跑两轮** —— 一轮不作数。

def 模型判未满足(逐字稿, model=None):
    """返回 (是不是未满足的需求, 理由)。**调不通就抛** —— 不要静默当成 False:
    「模型说不是」和「没调成」长得一模一样,而前者是判断,后者是故障。"""
    import json as _json
    sys.path.insert(0, os.path.join(HERE, "..", "agent"))
    import v1
    pv = v1.provider()
    resp = v1.call(pv, dict(model=model or pv["model"], max_tokens=600,
                            system=模型提示,
                            messages=[{"role": "user", "content": 逐字稿[:8000]}]),
                   purpose="商机判断·未满足需求", gen="工具")
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"模型没给出 JSON:{text[:160]}")
    d = _json.loads(m.group(0))
    return bool(d.get("未满足")), (d.get("理由") or "").strip()


def 判断_带模型(逐字稿, customer_id=None, model=None):
    """规则先筛,模型再判。**两层都过才算商机。**

    这个顺序是有意的:规则层便宜且确定,先把「没提到任何维度」
    和「店里没货」这两种刷掉 —— 它们不需要模型也能断定。
    模型只处理剩下的那部分,**省下的是每一条都调一次模型的钱**。
    """
    规则判, 码, 规则理由 = 判断(逐字稿, customer_id)
    if not 规则判:
        return False, 码, 规则理由          # 规则就能断定的,不必花钱
    未满足, 模型理由 = 模型判未满足(逐字稿, model)
    if not 未满足:
        return False, "JUST_MENTIONED", (
            f"{规则理由};**但客户只是提到,没有明确的未满足需求** —— {模型理由}")
    return True, 码, f"{规则理由};{模型理由}"
