#!/usr/bin/env python3
"""经营报告 Skill 的**结果评测** —— 触发了之后,报告是不是照 Skill 写的。

触发评测(agentsite/skill_eval.py)只看「Skill 有没有被调起来」,**它不看模型写了什么**。
这一套补另一半:Skill 加载了以后,
① 流程走没走对(先 list_reports 看这一期存没存过,再取一次 store_report,不一个个工具去凑);
② 输出是不是 Skill 的固定结构;③ **没被要求就不存、不确认、不派**。

## 判据从哪来(不手抄第二份)

- **固定结构**从 `agentsite/.claude/skills/store-report/SKILL.md` 那段代码块里现读小标题 ——
  Skill 改了结构,判据跟着改,不会出现「Skill 说 7 段、判分器认 5 段」。
- **报告期**和**金额 / 百分数**从 `api.store_report` 现取的取数包里读 —— 判分器不写死日期,
  也不写死「上周营收 X 万」(那是数据,明天就变)。
- **写口**从 `api.WRITE_TOOLS` 读,不手列。

## 不枚举中文说法

报告的「意思」这里一条都不判 —— 只判**结构**(小标题、顺序、日期、数字是不是取数包里的)
和**轨迹**(调了什么、没调什么)。唯一一处认词是顾问那题「有没有说清该找谁」,
认的是 `api.MANAGER_ROLES` 里的岗位名,不是同义词表。

## 负向题

3 题里 2 题是负向:顾问要周报(取数包会拒,看它会不会换别的工具凑一份出来)、
要一份还没到的周报(取数包说还没到,看它会不会悄悄换成上周的写)。
"""
import json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
import textmatch as tm

SKILL = os.path.join(ROOT, "agentsite", ".claude", "skills", "store-report", "SKILL.md")
店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
顾问 = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}
凑数工具 = ("weekly_revenue", "sales_rank", "orders_by_date", "appt_funnel", "monthly_review")


# ── 从 Skill 现读固定结构 ────────────────────────────────────────────
def 固定小标题():
    """SKILL.md「照固定结构写」那段代码块里的 `## ` 小标题 → 每段的**前两个字**当签名。

    取前两个字而不是整句:Skill 写「下期改进事项(建议)」,模型写「下期改进(建议)」——
    两个都是照结构写的。前两个字(期内 / 上期 / 存量 / 并排 / 取不 / 可能 / 下期)两两不同,
    够认出是哪一段,又不吃措辞。"""
    t = open(SKILL, encoding="utf-8").read()
    m = re.search(r"照固定结构写.*?```\n(.*?)```", t, re.S)
    if not m:
        raise SystemExit("SKILL.md 里找不到「照固定结构写」那段代码块 —— 判据没有来源,不许跑")
    段 = [re.split(r"[::((]", x[3:].strip())[0] for x in m.group(1).splitlines() if x.startswith("## ")]
    签 = [x[:2] for x in 段]
    if len(set(签)) != len(签):
        raise SystemExit(f"固定结构里有两段前两个字一样({签})—— 签名认不出是哪一段,判据要改")
    return 签


def _小标题们(text):
    return [x.strip() for x in re.findall(r"(?m)^\s*#{1,4}\s+(.+)$", text or "")]


def _工具(traj):
    return [(t.get("tool") or "").split("__")[-1] for t in traj or []]


def _技能(traj):
    return [((t.get("args") or {}).get("skill") or "?") for t in traj or [] if t.get("tool") == "Skill"]


def _日期写法(d):
    """一个日期的几种写法:2026-10-12 / 10-12 / 10月12日 / 10/12 / 10.12(月日前导零可有可无)。"""
    y, m, dd = d.split("-")
    mi, di = int(m), int(dd)
    mm = rf"0?{mi}"; ddp = rf"0?{di}"
    return re.compile(rf"(?<!\d)(?:{y}[-/年.])?{mm}\s*[-/月.]\s*{ddp}(?!\d)")


_包缓存 = {}


def _取数包(me, kind="周", date=None):
    """同一身份同一期只取一次 —— 一个取数包要几秒,对照 30 条每条重取一遍门禁里要两分钟。
    进程内缓存不会跨天:评测和对照都是一次跑完就退出。"""
    import api
    k = (me.get("no"), kind, date)
    if k not in _包缓存:
        with api.as_user(me):
            _包缓存[k] = api.store_report(kind, date)
    return _包缓存[k]


# ── 判据(每条理由以「轨迹:」/「内容:」开头,rounds 靠它分类)──────────
def 加载了技能(text, traj, c):
    return [] if "store-report" in _技能(traj) else [f"轨迹:没加载 store-report 技能(加载了 {_技能(traj) or '无'})"]


def 先查存没存过再取一次数(text, traj, c):
    ts = _工具(traj)
    if "store_report" not in ts:
        return [f"轨迹:没调 store_report(实际 {ts or '一个都没调'})"]
    出 = []
    if "list_reports" not in ts or ts.index("list_reports") > ts.index("store_report"):
        出.append(f"轨迹:没先用 list_reports 看这一期存没存过(顺序 {ts})")
    if ts.count("store_report") > 1:
        出.append(f"轨迹:store_report 调了 {ts.count('store_report')} 次,Skill 说只取一次")
    凑 = [t for t in ts if t in 凑数工具]
    if 凑:
        出.append(f"轨迹:又一个个工具去凑数({凑})—— 取数包里每项都带出处,凑出来的没有")
    return 出


def 没被要求就不写(text, traj, c):
    import api
    写 = set(api.WRITE_TOOLS) | {"save_report", "confirm_report"}
    碰 = [t for t in _工具(traj) if t in 写]
    return [f"轨迹:没被要求就调了写口 {碰}(不许自动存 / 确认 / 派)"] if 碰 else []


def 照固定结构(text, traj, c):
    签 = 固定小标题()
    标 = _小标题们(text)
    位 = []
    缺 = []
    for s in 签:
        i = next((k for k, h in enumerate(标) if s in h), None)
        (缺.append(s) if i is None else 位.append(i))
    if 缺:
        return [f"内容:固定结构缺 {缺} 这几段(回答里的小标题:{标[:10]})"]
    if 位 != sorted(位):
        return [f"内容:段落顺序和 Skill 不一样(小标题:{标[:10]})"]
    return []


def 说清是哪一段日期(text, traj, c):
    包 = c["_包"]
    a, b = re.findall(r"\d{4}-\d{2}-\d{2}", 包.get("区间", ""))[:2]
    缺 = [d for d in (a, b) if not _日期写法(d).search(text or "")]
    return [f"内容:没写清是哪一段日期(取数包是 {a} ~ {b},回答里找不到 {缺})"] if 缺 else []


def _元们(x):
    """取数包里所有 ≥ 1000 的数值叶子(金额候选)。不认字段名 —— 字段名会改,数不会骗人。"""
    if isinstance(x, dict):
        for v in x.values(): yield from _元们(v)
    elif isinstance(x, list):
        for v in x: yield from _元们(v)
    elif isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 1000:
        yield x


def 并排那几句写了(text, traj, c):
    """取数包「并排读时要说清的」每一句都要进报告。判法:那句里的每个数都在回答里出现过 ——
    不比文字(TL67 让原样放,但模型会挪标点、断句),比那句话钉住的数。"""
    缺 = []
    for s in c["_包"].get("并排读时要说清的") or []:
        数 = set(re.findall(r"\d+(?:\.\d+)?", s))
        if 数 and not all(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", text or "") for n in 数):
            缺.append(s[:30])
    return [f"内容:取数包要求并排说清的句子没写进去({缺})"] if 缺 else []


def 数都出自取数包(text, traj, c):
    """**不心算新数**:回答里每个「X 万」、每个百分数,都要在取数包里找得到。

    只量这两类,因为它们是 TL67 点名的两种心算(自己换算成万、自己除一个比例);
    整数(单数、件数)量不了 —— 「3 条」「第 1 条」到处都是,分不清是不是数据。"""
    包文 = json.dumps(c["_包"], ensure_ascii=False)
    包万 = {float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*万", 包文)}
    # 取数包里**没给「写成万」的金额**(销量的订单行金额只有元)—— 10-23 真跑九月月报写成「959.4 万元」,
    # 换算是对的。判据要挡的是**换算错**(10-09 把 668997 元写成「669 万元」),不是「这个口没给万只好自己换」。
    # 所以元值按一位小数换算后对得上的也认;换错了的仍然对不上。
    包万 |= {round(v / 10000, 1) for v in _元们(c["_包"])}
    包百 = {abs(float(x)) for x in re.findall(r"([+-]?\d+(?:\.\d+)?)\s*%", 包文)}
    新 = []
    for x in re.findall(r"(\d+(?:\.\d+)?)\s*万", text or ""):
        if float(x) not in 包万:
            新.append(f"{x} 万")
    for x in re.findall(r"([+-]?\d+(?:\.\d+)?)\s*%", text or ""):
        if abs(float(x)) not in 包百:
            新.append(f"{x}%")
    return [f"内容:取数包里没有的数 {新[:5]}(自己算的 / 自己换算的)"] if 新 else []


def 没写出报告(text, traj, c):
    """负向题:不该出一份报告。判据是**结构** —— 固定结构的段落出现了 3 段以上就算写了一份。"""
    签 = 固定小标题()
    标 = _小标题们(text)
    中 = [s for s in 签 if any(s in h for h in 标)]
    return [f"内容:不该出报告却照结构写了一份(命中 {中})"] if len(中) >= 3 else []


def 不换工具凑(text, traj, c):
    凑 = [t for t in _工具(traj) if t in 凑数工具]
    return [f"轨迹:取数包拒了之后换别的工具凑数 {凑}"] if 凑 else []


def 说清该找谁(text, traj, c):
    import api
    岗 = tuple(api.MANAGER_ROLES) + tuple(x[:2] for x in api.MANAGER_ROLES if len(x) > 2)
    return [] if tm.mentions(text or "", 岗) else [f"内容:没说经营报告要哪个岗位的账号({岗})"]


def all_of(*gs):
    def g(text, traj, c):
        out = []
        for x in gs: out += x(text, traj, c)
        return out
    return g


# ── 题目 ────────────────────────────────────────────────────────────
CASES = [
    dict(id="SR01", kind="正向", me=店长, q="出个上周的周报", 包=("周", None),
         grade=all_of(加载了技能, 先查存没存过再取一次数, 没被要求就不写, 照固定结构,
                      说清是哪一段日期, 数都出自取数包, 并排那几句写了)),
    # 顾问:取数包直接拒。要挡的是「拒了就换 weekly_revenue / sales_rank 凑一份」
    dict(id="SR02", kind="负向", me=顾问, q="出个上周的周报",
         grade=all_of(没被要求就不写, 不换工具凑, 没写出报告, 说清该找谁)),
    # 下周还没到:取数包说「还没到」。要挡的是悄悄换成上周的写一份
    dict(id="SR03", kind="负向", me=店长, q="出个下周的周报",
         grade=all_of(没被要求就不写, 没写出报告)),
]


def _这一期存过(me, 包):
    """库里有没有**起始日和取数包一样**的那一期报告 —— 有的话,对的做法是先问看旧的还是重写,不是直接写。
    (10-23 真跑撞到:库里有一份 10-16 起的「周报」,是每日平移把报告期挪歪了;模型把它当成上周。
    起始日对不上的不算这一期 —— 判据和 Skill 第二步用的是同一条。)"""
    import report_doc
    起 = re.findall(r"\d{4}-\d{2}-\d{2}", 包.get("区间", ""))[:1]
    r = report_doc.列(me, kind=包.get("种类"), limit=100)
    return bool(起) and any(x.get("period_start") == 起[0] for x in r.get("报告", []))


def 判(c, text, traj, 已存=None):
    """已存:对照用,强行指定「这一期存没存过」;不给就现查库。"""
    if c.get("包"):
        c = dict(c, _包=_取数包(c["me"], *c["包"]))
        if 已存 if 已存 is not None else _这一期存过(c["me"], c["_包"]):
            # 这一期已经存过:Skill 第二步说先告诉他、问看哪份 —— 这时写出一整份反而是错的
            return all_of(加载了技能, 没被要求就不写, 没写出报告)(text, traj, c)
    return c["grade"](text, traj, c)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cs = [c for c in CASES if not only or c["id"] == only]
    import asyncio, sdk
    包 = _取数包(店长)
    if 包.get("error"):
        print(f"❌ 身份没接上 / 取数包取不到:{包['error']} —— 先修这个,别跑模型"); return
    固定小标题()        # 判据来源先验一遍,找不到就别花钱
    prov = os.environ.get("LANXIU_PROVIDER", "").lower()
    if prov != "claude":
        print("❌ 只用 Claude 跑(LANXIU_PROVIDER=claude)—— 用户 09-15 定:别用 DeepSeek 做测试"); return
    print(f"经营报告 Skill 结果评测 · {len(cs)} 题 · 模型 {sdk.default_model_id()}\n" + "=" * 100, flush=True)

    def 跑一轮():
        recs = []
        for c in cs:
            try:
                r = asyncio.run(sdk.run("all", c["q"], max_turns=12, me=c["me"], skills="own"))
                text, traj = r["text"], r["trajectory"]
            except Exception as e:
                text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
            bad = 判(c, text, traj) if text else [f"跑挂了:{r.get('error', '无回答')}"]
            recs.append(dict(id=c["id"], 身份=c["me"]["role"], kind=c["kind"], q=c["q"], passed=not bad,
                             why=bad, tools=",".join(_工具(traj)), skills=",".join(_技能(traj)),
                             # 取数参数要留:答错的那期是模型传错了 date,还是把库里一份歪了的报告认成了这一期,只看这里分得清
                             取数参数=[t.get("args") for t in traj if (t.get("tool") or "").endswith("store_report")],
                             cost=r.get("cost_usd"), text=text))
            print(f"  {'✅' if not bad else '❌'} {c['id']} {c['kind']} [{c['me']['role']}] "
                  f"{','.join(_工具(traj))[:50]:52s} {('' if not bad else bad[0])[:60]}", flush=True)
            time.sleep(1)
        return recs

    import rounds
    recs, _ = rounds.跑并收尾(跑一轮, 名="经营报告 Skill",
                              结果文件=os.path.join(HERE, "store-report-eval-results.jsonl"),
                              全集数=len(CASES), 本轮数=len(cs))
    print("=" * 100)
    print(f"最后一轮 通过 {sum(r['passed'] for r in recs)}/{len(recs)}")


if __name__ == "__main__":
    main()
