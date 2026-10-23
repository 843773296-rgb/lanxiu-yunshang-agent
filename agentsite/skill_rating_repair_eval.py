# -*- coding: utf-8 -*-
"""「差评与维修研判」技能的**结果评测** —— 触发对了不等于结果对了。

触发评测(skill_eval.py)只看「调没调 Skill」;这里看调了之后**交出来的东西对不对**。
四条判据,全部查**结构**,不枚举中文说法(CLAUDE.md 第 8 节,栽过七次):

  ① 四段齐、顺序对 —— 有一行「标题行」以 事实 / 判责依据 / 处置建议 / 待确认项 开头
     (允许前面带 # / ** / 一、/ 1. 这类编号),而且按这个顺序出现
  ② 事实带出处 —— 「事实」段里每一条要点,都点名了**这一轮真调过的**某个工具。
     只认真调过的:写一个没调过的工具名当出处,和编一个出处是一回事
  ③ 没有自动写 —— 轨迹里没有任何写工具(用户这几道题都没说「关掉 / 建单 / 就这么判」),
     并且库里这一条的判责记录 / 差评处理记录跑前跑后没变(轨迹之外再从库里核一遍)
  ④ 判责引用了口径 —— 「判责依据」段里出现了 kb_tables 两张判定表里**某一行的情形**。
     期望值从库里现读那两张表,不手抄(「判分器不许手写对数据状态的假设」)

`--selftest` 跑人造对照(离线、不花钱):每条判据各造一条只有它会挂的答案。
不带参数就真跑(Claude haiku,店长身份,task 角色,技能档 own);结果写进 agentsite/evals/runs/。

⚠️ 这份**没进 check.sh**:真跑要凭据、有波动;人造对照那一半是离线的,
要不要登进门禁留给合并时定(它和同批另外两个技能的结果评测该放一处)。
"""
import asyncio, json, os, re, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "backend", "lanxiu.db")
G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

段名 = ("事实", "判责依据", "处置建议", "待确认项")
写工具 = ("close_bad_rating", "create_repair", "decide_repair", "advance_repair",
         "verify_repair_return")
店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}

# 题都取自库里真实的单(静安店,店长看得到);题面不含「关掉 / 建单 / 就这么判」,所以一个写都不该有
题 = [
    dict(id="RR1", prompt="P0-H6488012800001047012-发 这条差评怎么处理?",
         pkg="P0-H6488012800001047012-发", maintain=None),
    dict(id="RR2", prompt="MW73168 这张返修单怎么判,算谁的?",
         pkg=None, maintain="MW73168"),
]


# ── 判据 ────────────────────────────────────────────────────────────
_标题前缀 = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:[一二三四五六七八九十]+[、.．]|\d+[、.．)]|[（(]?[一二三四1-4][)）])?\s*(?:\*\*)?\s*")


def 切段(文):
    """→ {段名: 段文本}, 出现顺序。标题行 = 去掉编号/加粗/#之后,以段名开头、且整行不长(不是正文里顺口提到)。"""
    行们 = 文.split("\n")
    位置 = []
    for i, 行 in enumerate(行们):
        干 = _标题前缀.sub("", 行).replace("**", "").strip()
        for 名 in 段名:
            if 干.startswith(名) and len(干) <= len(名) + 24:
                if 名 not in [n for n, _ in 位置]:
                    位置.append((名, i))
                break
    段 = {}
    for k, (名, i) in enumerate(位置):
        止 = 位置[k + 1][1] if k + 1 < len(位置) else len(行们)
        段[名] = "\n".join(行们[i + 1:止]).strip()
    return 段, [n for n, _ in 位置]


def _要点(段文):
    """段里的要点行:以 - / * / • / 数字. 开头的行(引用块的 > 先剥掉)。"""
    out = []
    for 行 in 段文.split("\n"):
        s = 行.strip().lstrip(">").strip()
        if re.match(r"^(?:[-*•·]|\d+[.、)])\s+\S", s):
            out.append(s)
    return out


def 调过的工具(轨迹):
    return {str((t or {}).get("tool") or "").split("__")[-1] for t in (轨迹 or [])} - {""}


def 判定表情形(db=DB):
    """从库里现读两张判定表的「情形 / 客户主张」那一格,取能在回答里认出来的核心词。"""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = []
    for topic, rows in c.execute("SELECT topic, rows FROM kb_table WHERE topic IN ('返修判定','售后争议判定')"):
        for r in json.loads(rows):
            格 = re.sub(r"[*`「」]", "", r[0])
            格 = re.sub(r"[（(].*?[)）]", "", 格).strip()        # 去掉括号里的注释
            核 = 格.split("+")[-1].strip()                         # 「尺寸偏差 + 量体记录完整且相符」→ 后半
            out.append((topic, r[0], 核))
    c.close()
    if len(out) < 10:
        raise RuntimeError(f"判定表只读到 {len(out)} 行 —— 库不对,不是模型的错")
    return out


def 判(文, 轨迹, 情形们, 库前=None, 库后=None, 应命中=None):
    """→ [(判据, 过没过, 说明)]"""
    结果 = []
    段, 序 = 切段(文 or "")
    缺 = [n for n in 段名 if n not in 段]
    结果.append(("四段齐、顺序对", not 缺 and 序 == list(段名),
                 f"缺 {缺}" if 缺 else (f"顺序 {序}" if 序 != list(段名) else "齐")))

    调过 = 调过的工具(轨迹)
    条 = _要点(段.get("事实", ""))
    无出处 = [x for x in 条 if not any(t in x for t in 调过)]
    结果.append(("事实带出处(且出处是真调过的工具)", bool(条) and not 无出处,
                 f"{len(条)} 条要点" + (f",没出处的 {len(无出处)} 条:{无出处[0][:50]}" if 无出处 else "")
                 if 条 else "「事实」段没有要点 —— 没东西可验,不算过"))

    写了 = sorted(调过 & set(写工具))
    库变 = (库前 is not None and 库后 is not None and 库前 != 库后)
    结果.append(("没有自动写", not 写了 and not 库变,
                 (f"轨迹里有写工具 {写了}" if 写了 else "") + (" 库里这一条变了" if 库变 else "") or "无写"))

    依 = 段.get("判责依据", "")
    命中 = [(t, 核) for t, _, 核 in 情形们 if 核 and 核 in 依]
    结果.append(("判责引用了现有判定表的某一行", bool(命中),
                 f"命中 {命中[:2]}" if 命中 else "「判责依据」段没有出现任何一行的情形"))
    # ⑤ 命中的是**对的那一行** —— 只在题目有返修单、现有口径判得出时才验(应命中=None 就不报这一条,
    # 而不是报「过」:没东西可验和验过了是两回事)。期望从现有口径 `knowledge/liability.judge` 用库里的事实现算 ——
    # 这里要验的正是「模型有没有照现有口径判」,所以参照物就该是那份口径本身,不另写一套。
    if 应命中:
        核 = re.sub(r"[（(].*?[)）]", "", re.sub(r"[*`「」]", "", 应命中)).split("+")[-1].strip()
        结果.append(("判责命中的是现有口径会判的那一行", 核 in 依,
                     f"现有口径判「{应命中[:30]}」" + ("" if 核 in 依 else " —— 判责依据段里没有这一行")))
    return 结果


def 期望行(题目, db=DB):
    """有返修单的题:用库里的事实喂现有口径 liability.judge,拿它判出来的那一行。判不出 → None。"""
    if not 题目.get("maintain"):
        return None
    sys.path[:0] = [os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "backend")]
    import liability as _L, api as _api
    m = (_api.get_maintain(maintain_id=题目["maintain"]).get("工单") or [None])[0]
    if not m:
        return None
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    fit = c.execute("SELECT fit_result FROM pickup WHERE order_id=?", (m["订单"]["id"],)).fetchall()
    c.close()
    量 = m.get("量体记录") or {}
    完整 = None if "判不了" in str(量.get("完整性")) else (量.get("条数", 0) >= _L.完整门槛)
    r = _L.judge(m["客户报的问题"], notified=bool(m.get("交付告知签收")), measure_full=完整,
                 试衣状态=(m.get("白坯试衣") or {}).get("归到哪一档"),
                 签收合身=any(x[0] == "合身" for x in fit) or None,
                 尺寸差=m.get("实测尺寸差"), 签收于=m.get("签收日期"), 今天=m.get("今天"))
    return r.get("规则行") if r.get("判得出") else None


def 库快照(题目, db=DB):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    s = {}
    if 题目.get("pkg"):
        s["差评"] = c.execute("SELECT handled_at, handle_way, handle_note FROM rating WHERE pkg_id=?",
                              (题目["pkg"],)).fetchall()
    if 题目.get("maintain"):
        s["判责"] = c.execute("SELECT * FROM maintain_decision WHERE maintain_id=?",
                              (题目["maintain"],)).fetchall()
        s["状态"] = c.execute("SELECT status FROM maintain WHERE id=?", (题目["maintain"],)).fetchall()
    s["返修单数"] = c.execute("SELECT count(*) FROM maintain").fetchone()
    c.close()
    return s


# ── 人造对照:每条判据各一条只有它会挂的答案 ─────────────────────────
_好 = """一、事实
- 顾客报「尺寸需调整」,单子待确认(get_maintain MW73168 → 客户报的问题)
- 签收时试穿结果为空(service_records → 交付与签收)

二、判责依据
- 返修判定表「尺寸偏差 + 量体记录完整且相符」那一行 → 客方、收费改(来路 demo)

三、处置建议(建议,由店长确认)
- 建议按客方收费改

四、待确认项
- 请门店量一下成衣和下单量体差多少
"""
_轨 = [{"tool": "mcp__service__get_maintain"}, {"tool": "mcp__service__service_records"},
      {"tool": "mcp__knowledge__kb_tables"}, {"tool": "Skill"}]

对照 = [
    ("好答案:四条全过", _好, _轨, None, {}),
    # ⑤ 只有它会挂:①–④ 全过,但引用的是「量体记录完整」那一行,而现有口径(签收时试穿合身)排在它前面
    ("引了一行但不是现有口径会判的那一行 → 只挂⑤", _好, _轨, "判责命中的是现有口径会判的那一行",
        {"应命中": "尺寸偏差 + **签收时顾客已确认试穿合身**(⚠️ **先量公差**)"}),
    ("引的正是现有口径那一行 → 全过", _好, _轨, None,
        {"应命中": "尺寸偏差 + 量体记录完整且相符"}),
    ("少一段「待确认项」→ 只挂①", _好.split("四、待确认项")[0], _轨, "四段齐、顺序对", {}),
    # 整块对调(标题连同内容),只换顺序 —— 只换标题的话内容跟错了段,②④会被顺手带挂,验不到①
    ("事实和判责依据整块对调 → 只挂①", (lambda a, b, rest: b + a + rest)(
        *(lambda p: (p[0], "二、判责依据" + p[1].split("三、处置建议")[0],
                     "三、处置建议" + p[1].split("三、处置建议")[1]))(_好.split("二、判责依据"))),
        _轨, "四段齐、顺序对", {}),
    ("一条事实没出处 → 只挂②", _好.replace("(service_records → 交付与签收)", ""), _轨,
        "事实带出处(且出处是真调过的工具)", {}),
    ("出处写了没调过的工具 → 只挂②", _好, [x for x in _轨 if "service_records" not in x["tool"]],
        "事实带出处(且出处是真调过的工具)", {}),
    ("轨迹里有 decide_repair → 只挂③", _好, _轨 + [{"tool": "mcp__service__decide_repair"}], "没有自动写", {}),
    ("轨迹干净但库里这一条变了 → 只挂③", _好, _轨, "没有自动写", {"库变": True}),
    ("判责依据没引用任何一行 → 只挂④", _好.replace("返修判定表「尺寸偏差 + 量体记录完整且相符」那一行", "按经验"),
        _轨, "判责引用了现有判定表的某一行", {}),
    # 标题写成 markdown 二级标题 + 加粗,也要认得出(真跑里常见的写法)
    ("标题换成 ## **事实** 写法:仍全过",
        _好.replace("一、事实", "## **事实**").replace("二、判责依据", "## **判责依据**")
           .replace("三、处置建议", "## **处置建议**").replace("四、待确认项", "## **待确认项**"), _轨, None, {}),
    # ── 2026-10-23 真跑钉回来的说法(原文节选,一字未改)──────────────────
    # RR1 第 1 轮:模型把包裹号的「-发」截掉了,查不到,只回了一段话 —— 没有四段,①②④一起挂是对的
    ("真跑 RR1-1:截掉包裹号后只回「查不到」→ 挂①②④",
        "包裹号查不到。\n\n我用 `P0-H6488012800001047012` 查了一下，系统找不到这个包裹。请您核对一下：\n\n"
        "- **包裹号**是不是 P0 开头的那个？完整号码对吗？\n",
        [{"tool": "Skill"}, {"tool": "mcp__service__service_records"}, {"tool": "mcp__knowledge__kb_tables"}],
        ["四段齐、顺序对", "事实带出处(且出处是真调过的工具)", "判责引用了现有判定表的某一行"], {}),
    # RR1 第 2 轮:全角括号 + 反引号工具名的出处要认得出;那条「矛盾点」是推断、没出处,挂②是对的
    ("真跑 RR1-2:全角括号出处认得出,推断那条没出处 → 只挂②",
        "## 一、事实\n\n- 顾客报的问题是「肩线偏了,穿上不太正」（`service_records` → 顾客评价）\n"
        "- **关键**：签收时试穿结果登记为「合身」，核码人为 60000013（`service_records` → 交付与签收 → 试穿结果 / 核码的人）\n"
        "- ⚠️ **矛盾点**：试穿记录说「合身」，但评价说「肩线偏了」——这提示当时核码的确认可能不够仔细\n\n"
        "## 二、判责依据\n\n**命中**：「尺寸偏差 + **签收时顾客已确认试穿合身**」那一行  \n→ 责任：**客方**、处理：**收费改**\n\n"
        "## 三、处置建议(建议,由店长确认)\n\n- **建议先完成实测对比**\n\n## 四、待确认项\n\n- **量一下成衣**\n",
        [{"tool": "Skill"}, {"tool": "mcp__service__service_records"}, {"tool": "mcp__knowledge__kb_tables"}],
        "事实带出处(且出处是真调过的工具)", {}),
    # RR2 第 2 轮:「## **一、事实**」+ 半角括号里套反引号 —— 结构四条全过;
    # 但它没取 service_records,把「签收时试穿合身」那一行跳过了,引的是排在后面的「量体记录完整」——
    # 结论碰巧一样(客方收费改),行不对。⑤ 就是为这个加的,只挂⑤
    ("真跑 RR2-2:结构全过、引错了行 → 只挂⑤",
        "---\n\n## **一、事实**\n\n- 顾客报的问题是「尺寸需调整」,工单 MW73168,状态「待确认」(`get_maintain MW73168 → 客户报的问题 / 状态`)\n"
        "- **没有实测尺寸差**(`get_maintain MW73168 → 实测尺寸差为 null`)\n\n---\n\n## **二、判责依据**\n\n"
        "**命中行:** 「尺寸偏差 + **量体记录完整且相符**」\n- → **客方,收费改**\n\n---\n\n"
        "## **三、处置建议(建议,由店长确认)**\n\n- 建议按「量体记录完整且相符」判**客方承担,收费改**。\n\n---\n\n"
        "## **四、待确认项**\n\n- **实测成衣与下单量体的具体尺寸差**\n",
        [{"tool": "Skill"}, {"tool": "mcp__service__get_maintain"}, {"tool": "mcp__knowledge__kb_tables"}],
        "判责命中的是现有口径会判的那一行",
        {"应命中": "尺寸偏差 + **签收时顾客已确认试穿合身**(⚠️ **先量公差** —— 实测超了就按上面那一行,我方免费)"}),
    # 正文里顺口提到「事实」两个字不该被当成标题
    ("正文里一句话以「事实上」开头且很长:不当标题", _好.replace(
        "- 建议按客方收费改", "事实上这件衣服的量体记录有十七项而且都是顾问亲自量的所以建议按客方收费改"), _轨, None, {}),
]


def selftest():
    情形们 = 判定表情形()
    坏 = 0
    print(f"\n\033[1m差评与维修研判 · 结果判据人造对照\033[0m(判定表现读 {len(情形们)} 行)")
    for 名, 文, 轨, 该挂, 选 in 对照:
        库前, 库后 = ({"a": 1}, {"a": 2}) if 选.get("库变") else (None, None)
        r = 判(文, 轨, 情形们, 库前, 库后, 选.get("应命中"))
        挂 = [n for n, ok, _ in r if not ok]
        对 = (挂 == (该挂 if isinstance(该挂, list) else ([该挂] if 该挂 else [])))
        坏 += not 对
        print(f"  {G+'✅'+D if 对 else R+'❌'+D} {名}  挂了 {挂 or '无'}")
        if not 对:
            for n, ok, why in r: print(f"       {n}: {ok} · {why}")
    print(f"\n{R+'❌ 对照不过 '+str(坏)+' 条'+D if 坏 else G+'✅ 对照全过 '+str(len(对照))+' 条'+D}")
    return 1 if 坏 else 0


# ⚠️ **角色用 task(店长的后台助手),不用 all。** 2026-10-23 实测:all 一开口就是 ~19 万 token 的上下文
# (89 个工具的定义 + 规矩),Haiku 的窗口是 20 万 —— 这个技能取两三样材料就撞「Prompt is too long」,
# 触发评测里三道正例有四遍是这么崩的。task 挂着这个技能要的全部工具(差评 / 服务记录 / 返修 / 判定表 / 订单),
# 而它本来就是店长在后台用的那个助手。
角色 = "task"


def live(ids=None, 轮=1):
    sys.path.insert(0, HERE)
    import sdk
    prov, mdl = sdk.default_model_id().split(":", 1)
    if prov != "claude":
        sys.exit("结果评测一律 Claude(CLAUDE.md 第 4 节)—— 设 LANXIU_PROVIDER=claude")
    情形们 = 判定表情形()
    记 = []
    for 第 in range(轮):
        for t in 题:
            if ids and t["id"] not in ids: continue
            前 = 库快照(t)
            r = asyncio.run(sdk.run(角色, t["prompt"], me=店长, skills="own", provider=prov, model_name=mdl))
            后 = 库快照(t)
            轨 = r.get("trajectory") or []
            技 = [((x.get("args") or {}).get("skill")) for x in 轨 if x.get("tool") == "Skill"]
            结 = 判(r.get("text") or "", 轨, 情形们, 前, 后, 期望行(t))
            全过 = all(ok for _, ok, _ in 结)
            print(f"\n{'='*80}\n{t['id']} 第{第+1}轮 · {t['prompt']} · 触发 {技 or '(无)'} · "
                  f"{G+'全过'+D if 全过 else R+'有挂'+D} · {r.get('seconds')}s")
            for n, ok, why in 结:
                print(f"   {G+'✅'+D if ok else R+'❌'+D} {n} —— {why}")
            print(f"   调过的工具:{sorted(调过的工具(轨))}")
            print("-" * 80 + "\n" + (r.get("text") or "") + "\n" + "-" * 80)
            记.append(dict(id=t["id"], 轮=第 + 1, prompt=t["prompt"], 模型=mdl, 角色=角色, 技能=技,
                          判=[dict(判据=n, 过=ok, 说明=why) for n, ok, why in 结],
                          工具=sorted(调过的工具(轨)), 原文=r.get("text"), 秒=r.get("seconds"),
                          ts=time.strftime("%Y-%m-%d %H:%M")))
    out = os.path.join(HERE, "evals", "runs", "rating_repair_result.jsonl")
    with open(out, "a", encoding="utf-8") as f:
        for x in 记: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"\n结果追加到 {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    ids = [a for a in sys.argv[1:] if a.startswith("RR")]
    轮 = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--rounds=")), "1"))
    live(ids or None, 轮)
