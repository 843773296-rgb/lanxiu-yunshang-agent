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

店里眼下没有对得上的货时,下一步写 `{"做什么": "…", "搁置等": {"颜色": "白", "形制": "马面裙"}}` ——
等什么必须是诉求维度上的结构化字段,上新时回捞池拿它去匹配(和 `oppo_obj.搁置理由合格吗` 同一个口径)。

正文只做一件事:**正文里出现的编号也必须真在库里**(编号有固定形状,按形状找,不按说法找)。

## 八条判据(一律「查出坏的就返回一条话」,空 = 过;每条话以「类:」开头,对照按类核)

    格式   没交 JSON / JSON 里没有「商机」
    判断   商机判反了(和标注比;**标注只在判分器这边,绝不经工具给模型**)
    结构   判了是商机,却没有诉求、或下一步既不指向库里的东西也不写搁置等什么 / 搁置等的不是可匹配的维度
    原话   诉求的原话不在逐字稿里 / **是顾问说的不是客户说的** / 维度不在口径里 /
           叫得出名字的东西(形制、工艺、颜色……)原话里根本没提
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


# 「叫得出名字的东西」:值必须出现在原话里,否则这句原话撑不起这条诉求。
# 场合 / 预算 / 工期 / 尺码 / 性别 不要求 —— 客户说「我下个月结婚」,值写「婚礼婚服」是对的归类,不是编的
点名维度 = ("形制", "配饰", "工艺", "面料", "纹样", "版型", "颜色")


def _原话说到(维, 值, 原):
    if not 值 or 值 in 原:
        return True
    if 维 == "颜色":
        # 值可能是色系(「白」「金银」)—— 按色系认客户的说法,和商机判断同一套(knowledge/oppo.色字)
        return any(w in 原 for w in KO.色字(值))
    return False


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
        elif 维 in 点名维度 and not _原话说到(维, str(x.get("值") or ""), 原):
            坏.append(f"原话:「{原[:24]}」里没有「{x.get('值')}」—— 这句撑不起「{维}={x.get('值')}」"
                      f"(多半是顾问说的、客户顺着应了一句)")
        elif _规整(原) not in 客户:
            if _规整(原) in 全文:
                坏.append(f"原话:「{原[:24]}」是顾问说的,不是客户说的 —— 顾问介绍商品时一定会提颜色")
            else:
                坏.append(f"原话:「{原[:24]}」逐字稿里没有这句")
    return 坏


def 查指向(c, 下一步们, 客户):
    坏 = []
    for 步 in 下一步们:
        指 = 步.get("指向") or []
        if isinstance(指, dict):
            指 = [指]                  # 只指一样东西时常写成单个对象,宽容收下
        if not isinstance(指, list):
            坏.append(f"格式:「指向」要写成列表,实际是 {type(指).__name__}")
            continue
        for p in 指:
            if not isinstance(p, dict):
                坏.append(f"格式:「指向」里的每一项要写成 {{类, id}},实际是「{str(p)[:20]}」")
                continue
            类, i = p.get("类"), str(p.get("id") or "")
            if 类 == "商品":
                r = c.execute("SELECT status FROM product WHERE spu=?", (i,)).fetchone()
                if not i:
                    坏.append("指向:指了一件商品却没给编号 —— 「请顾问核实」该写在搁置等 / 做什么里,不是空着的指向")
                elif not r:
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
    if not isinstance(对上, dict):
        # 真跑见过写成列表 ["颜色", "形制"] —— 说不清对上了什么值,等于没说
        return [f"格式:{spu} 的「对上」要写成 {{维度: 值}},实际是 {type(对上).__name__}"]
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
        # 下一步要么指向库里的东西,要么写清「搁置等什么」—— 店里眼下没货时,搁置才是对的那一步
        # (客户要月白马面裙而库里一条都没有,硬指一件白色褙子是在凑数)
        if not any(x.get("指向") or x.get("搁置等") for x in 下一步们):
            坏.append("结构:判了是商机,下一步却既没指向库里任何东西、也没写搁置等什么 —— 顾问拿着不知道干什么")
    for 步 in 下一步们:
        if "搁置等" in 步:
            ok, 话 = K.搁置理由合格吗(步.get("搁置等"))
            if not ok:
                坏.append(f"结构:{话}")
    坏 += 查原话(诉求们, 逐字稿)
    c = _db()
    try:
        坏 += 查指向(c, 下一步们, 客户)
        坏 += 查正文编号(c, 答 or "")
    finally:
        c.close()
    坏 += 查概率(答, 诉求们)
    return 坏


# ══════════════════════════════════════════════════════════════════
# 真跑:24 通标注过的通话,每通请 call-notes 技能整理一次,两轮
# ══════════════════════════════════════════════════════════════════
#
#     LANXIU_PROVIDER=claude ANTHROPIC_MODEL=claude-haiku-4-5 \
#       ./agentsite/.venv/bin/python agent/oppo_eval.py [TS-001 …]
#
# 身份用**这位客户的归属顾问**(顾问整理自己名下的通话,是真实用法);没有在职顾问的退到总部。
# 标注从 truth 表读,**只在判分器这边** —— 模型拿到的只有通话号。

def 题面(通话):
    return f"帮我整理一下通话 {通话}:写个总结,判一下有没有商机,下一步怎么跟。"


def 题们():
    c = sqlite3.connect(DBP); c.row_factory = sqlite3.Row
    真值 = {r["case_id"]: r["root_cause"] == "是商机"
            for r in c.execute("SELECT case_id, root_cause FROM truth WHERE src='造数据标注' AND case_id LIKE 'TS-%'")}
    总部 = dict(c.execute("SELECT no,name,role,shop FROM staff WHERE role='总部运营' AND status='启用' "
                          "ORDER BY no LIMIT 1").fetchone())
    出 = []
    for r in c.execute("SELECT a.id, a.customer_id, t.text, cu.advisor_no FROM call_audio a "
                       "JOIN call_transcript t ON t.audio_id=a.id JOIN customer cu ON cu.id=a.customer_id "
                       "WHERE a.id LIKE 'TS-%' ORDER BY a.id"):
        if r["id"] not in 真值:
            continue
        顾问 = c.execute("SELECT no,name,role,shop FROM staff WHERE no=? AND role='顾问' AND status='启用'",
                         (r["advisor_no"],)).fetchone()
        出.append(dict(id=r["id"], 客户=r["customer_id"], 稿=r["text"], 应该=真值[r["id"]],
                       me=dict(顾问) if 顾问 else 总部))
    c.close()
    return 出


def main():
    import asyncio, time
    if os.environ.get("LANXIU_PROVIDER") != "claude":
        print("⚠ 规矩:一律用 Claude(月租,不额外花钱)。设 LANXIU_PROVIDER=claude")
        return 1
    sys.path[:0] = [HERE, os.path.join(ROOT, "agentsite")]
    import sdk, rounds, evalrec
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    全 = 题们()
    only = [x for x in sys.argv[1:] if x.startswith("TS-")]
    todo = [x for x in 全 if not only or x["id"] in only]
    if len(全) < 10:
        print(f"❌ 只有 {len(全)} 通标注过的通话 —— 没扫到东西,不算通过"); return 1
    print(f"通话整理(call-notes)· {len(todo)} 通 · 模型 {model} · "
          f"标注是商机 {sum(x['应该'] for x in todo)} / 不是 {sum(not x['应该'] for x in todo)}")
    print("=" * 104)

    def 跑一轮():
        rows = []
        for x in todo:
            t0 = time.time()
            try:
                r = asyncio.run(sdk.run("kb", 题面(x["id"]), max_turns=14, me=x["me"], skills="own"))
            except Exception as ex:
                # **「跑崩了」和「答错了」在成绩单里长得一模一样** —— 单独标
                rows.append(dict(case=x["id"], passed=False, why=[f"跑挂了:{type(ex).__name__}: {ex}"],
                                 tools="", cost=0, text="", 技能=None))
                print(f"[{x['id']}] ❌ 跑挂了:{type(ex).__name__}"); continue
            traj = r["trajectory"]
            技能 = next(((t.get("args") or {}).get("skill") for t in traj if t.get("tool") == "Skill"), None)
            try:
                why = 判(r["text"], x["稿"], x["客户"], x["应该"])
            except Exception as ex:
                # **判分器崩了 ≠ 模型答错了** —— 单独一类,而且别让它把整轮跑断(10-03 第一次全量就断在第 5 通)
                why = [f"判分器崩了:{type(ex).__name__}: {ex} —— 去补判分器,不是模型的错"]
            rows.append(dict(case=x["id"], passed=not why, why=why, 应该=x["应该"],
                             tools=",".join(t["tool"].split("__")[-1] for t in traj),
                             cost=r.get("cost_usd") or 0, text=r["text"], 技能=技能))
            print(f"[{x['id']}] {'✅' if not why else '❌'} {'是' if x['应该'] else '否'} "
                  f"{len(traj)}调 {time.time()-t0:5.1f}s 技能={技能 or '没走'}  {'' if not why else why[0][:60]}")
            for w in why[1:]:
                print(f"        {w[:92]}")
        return rows

    轮数 = 1 if os.environ.get("LANXIU_一轮") else 2
    多, 因, rows = [], [], []
    for i in range(轮数):
        print(f"  【第 {i + 1} 轮】")
        rows = 跑一轮()
        多.append({r["case"]: r["passed"] for r in rows})
        因.append({r["case"]: r["why"] for r in rows})
    过 = sum(多[-1].values())
    print("=" * 104)
    print(f"末轮通过 {过}/{len(todo)}  ·  走了技能 {sum(1 for r in rows if r['技能'] == 'call-notes')}/{len(rows)}"
          f"  ·  花费 ${sum(r['cost'] for r in rows):.4f}(末轮)")
    # 挂在哪一类 —— 判断错和格式错的下一步完全不同
    类 = {}
    for r in rows:
        for w in r["why"]:
            k = w.split(":", 1)[0]; 类[k] = 类.get(k, 0) + 1
    if 类:
        print("  末轮挂的类别:" + " · ".join(f"{k} {v}" for k, v in sorted(类.items(), key=lambda kv: -kv[1])))
    rounds.报(多, 名="通话整理", 原因=因)
    out = os.path.join(HERE, "oppo-eval-results.jsonl")
    if len(todo) < len(全):
        print(f"⚠️ 只跑了 {len(todo)}/{len(全)} 通,**不写结果文件**(部分结果覆盖完整基线,文件上看不出来)")
        # 原文还是要留 —— 不留的话失败了只能重跑才知道它说了什么(写到另一个文件,不碰基线)
        evalrec.dump(os.path.join(HERE, "oppo-eval-results.partial.jsonl"), rows)
    else:
        evalrec.dump(out, rows)
        print(f"明细写到 {out}")
    return 0 if 过 == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
