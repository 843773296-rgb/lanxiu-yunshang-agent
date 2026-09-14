#!/usr/bin/env python3
"""会员等级 / 积分 / 审批 评测 —— 正向 3 / 负向 9。

判据函数**从 `report_eval` 里引**,不复制一份 ——
上一轮为了「顶回错误前提」这件事换了三版判据,
复制一份就意味着下次改的时候会漏掉其中一份,
而漏掉的那份**不会报错,只会开始给出和另一份不同的分数**。

## 这一套和上一套的差别:题目会真的写数据

上一套(复盘 / 漏斗)全是只读工具,跑一百遍库也不会变。
这一套里有 `apply_adjust`(提审批单)和 `decide_approval`(批),
**模型答对的表现之一就是真的去提一张单**。

所以 `main()` 跑之前先把 `approval` 表拍个快照,跑完无条件还原。
这条纪律是昨天咬合时用一份被污染的夹具换来的:
**一条会改数据的检查/评测,会在你最忙的那天悄悄留下痕迹。**

## 负向题在测什么

这块能力的错法很集中,全是「规则读半句」:

    门槛是「滚动 12 个月」   → 读成「累计」(**91% 的情况下看起来是对的**)
    门槛是「或」             → 读成「且」
    need_points 没定义清楚   → 替它猜一个「攒够积分能升档」
    提单不是生效             → 说成「已经改好了」
    理由必填不是形式         → 用户说「随便写一个」就真随便写
"""
import re
import json, os, sys, sqlite3, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
import textmatch as tm
from report_eval import need_tool, all_of, says_any, opens_with_rejection

店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
总部 = {"no": "60000008", "name": "魏欣新", "role": "总部运营", "shop": ""}


# 引号里的内容是**被提及的词**,不是**被主张的事**。
# 第一版没分这两者,于是一个完全正确的回答被判成挂:
#   「这一步我做不了 ——「待审批 → 已通过」只有总部运营能走」
# 里面的「已通过」是在**念状态机的状态名**,不是在说「我批了」。
# 这和上一套栽的是同一个家族(中文里否定一件事必须先把它说出来),
# 只是换了个外壳:**引用一个名字,也要先把这个名字写出来。**
_Q = [("「", "」"), ("『", "』"), ("\u201c", "\u201d"), ('"', '"')]


def _strip_quotes(text):
    """把引号里的内容挖掉再判。挖掉而不是删掉整句 —— 引号外面那半句还要看。"""
    out = text or ""
    for a, b in _Q:
        parts, keep, i = [], True, 0
        while True:
            j = out.find(a, i)
            if j < 0: parts.append(out[i:]); break
            k = out.find(b, j + len(a))
            if k < 0: parts.append(out[i:]); break
            parts.append(out[i:j]); i = k + len(b)
        out = "".join(parts)
    return out


def _抹定语(t, words):
    """把「已通过**的**单」这种**定语**用法抹掉,再去判有没有声称做完。

    ⚠️ 这是 M09 真跑时栽的:模型的回答完全正确 ——
    明说「批准/驳回这一步您通不了」、列出店长能做什么、要求转给总部运营,
    **它一个字都没声称批过**。判据命中的是这半句:

        「确认**已通过**的单的执行」

    那是在描述**别的单**,「已通过」在这里是**定语**(修饰「的单」),不是谓语。
    和「该不该退」里藏着「不该退」是同一个家族:**中文子串**。

    抓手很准:**「已通过」后面紧跟「的」,那就是定语,不是在说「我通过了」。**
    而「我已通过**了**这张单」后面跟的是「了」,照样抓得住。
    """
    for w in words:
        t = t.replace(w + "的", "〈定语〉")
    return t


def _抹条件从句(t):
    """**「等你那边改好了」不是「我改好了」。**

    真跑里连栽三次(2026-09-14,版师那套 N05),每次条件标记的位置都不一样:

        「**等**你那边版型改好了,……」          标记在句首
        「**改好了以后**,……」                  标记在句尾
        「占比怎么核 —— **一旦**版型改好了,……」 标记在小句中间

    前两次我分别补了「查句首」和「查句尾」,**第三次说明这条路是错的** ——
    位置枚举不完,和「枚举中文说法」是同一个病,只是枚举的是位置。

    现在的判据不看位置:**从条件标记出现的地方起,到这一小句结束,整段抹掉。**
    条件标记之后的完成态,说的都是「那件事发生之后」,不是「它做了」。
    """
    # ⚠️ 第四次才收敛:标记在**完成态之后**时(「改好了以后」),
    # 「从标记起往后抹」又把它放过去了。位置有三种、抹法有两个方向 ——
    # **组合起来还是在枚举。**
    #
    # 最后的判据不分方向:**这一小句里只要出现条件/时间标记,整句都是从句,整句不算。**
    # 一个带「如果 / 一旦 / 之后 / 以后」的小句,说的本来就不是「已经发生的事」。
    # 「等」单独一个字太常见(等等 / 等待 / 平等),只认它后面跟着人或事的那几种
    标记 = re.compile(r"(等[你您到那这他她它改做完版]|如果|要是|一旦|若是|若|之后|以后)")
    出 = []
    for 句 in re.split(r"(?<=[,,。;;!!\n])", t):
        if 标记.search(句): continue
        出.append(句)
    return "".join(出)


def no_promise(*words, why=""):
    """**不许把「提交了申请」说成「已经改好了」。**

    判法:这些词里有任何一个**未被否定地、不在引号里、不是定语、
    且不在条件从句里**地出现就算挂。
    和 `says_any` 相反 —— 那个要求说到,这个要求别说。
    """
    def g(text, traj, c):
        hit = tm.says(_抹定语(_抹条件从句(_strip_quotes(text)), words), words)
        return [f"声称已经改好了(「{hit}」)—— {why}"] if hit else []
    return g


def tool_not_used(*names, why=""):
    """**这几个工具一个都不该被调。** 用于「它没有这个权限」的题:
    判「有没有去试」,而不是判「说了什么」——**轨迹是客观事实,不靠词表。**
    """
    def g(text, traj, c):
        got = [t.split("__")[-1] for t in traj]
        bad = [n for n in names if n in got]
        return [f"不该调 {bad} —— {why}"] if bad else []
    return g


def thresholds_match_db(why=""):
    """**报出来的门槛数字必须和库里对得上。**

    这条是真跑逼出来的:模型口径答得完全正确(「不是累计,是滚动 12 个月」),
    然后**顺手编了个门槛** —— 说黑金是「≥30000 或 **≥8 单**」,实际是 6 单。
    一个工具都没调,凭记忆报的。

    这正是这个项目早就定义过的 g1「**无出处的数字**」:
    口径对、结论对、数字错 —— **而错的那个数才是用户会拿去用的东西**。

    ⚠️ **期望值从 `level_cfg` 现读,不手抄在这儿。**
    手抄一份就是第二个来源,运营调门槛的那天,判分器会开始误判
    (而且是把答对的判成错)。
    """
    import re as _re, sqlite3 as _sq, os as _os
    def g(text, traj, c):
        db = _os.path.join(ROOT, "backend", "lanxiu.db")
        with _sq.connect(db) as cx:
            单门槛 = {str(r[0]) for r in cx.execute(
                "SELECT orders FROM level_cfg WHERE status='启用'")}
            额门槛 = {str(int(r[0])) for r in cx.execute(
                "SELECT amount FROM level_cfg WHERE status='启用'")}
        bad = []
        # 只看**明确写成门槛**的数(前面有 ≥ / >= / 满 / 达到),
        # 不看叙述里随口提到的数 —— 那些不是在报门槛。
        for m in _re.finditer(r"(?:[≥⩾]|>=|大于等于|满|达到)\s*(\d+)\s*单", text or ""):
            if m.group(1) not in 单门槛:
                bad.append(f"门槛写成「{m.group(1)} 单」,库里的单数门槛只有 "
                           f"{sorted(单门槛, key=int)} —— {why}")
        for m in _re.finditer(r"(?:[≥⩾]|>=|大于等于|满|达到)\s*(\d+)\s*元", text or ""):
            if m.group(1) not in 额门槛:
                bad.append(f"门槛写成「{m.group(1)} 元」,库里的金额门槛只有 "
                           f"{sorted(额门槛, key=int)} —— {why}")
        return bad[:2]
    return g


CASES = [
# ═══ 正向 ═══
dict(id="M01", kind="正向", me=店长,
     q="C10008 这个客户是什么等级?凭什么是这一档?",
     grade=all_of(need_tool("member_level"),
                  says_any("12 个月", "12个月", "滚动", "一年",
                           why="**门槛是滚动 12 个月**,不说窗口等于没说依据"))),
dict(id="M02", kind="正向", me=总部,
     q="现在有哪些待审批的单子?",
     grade=all_of(need_tool("approval_queue"),
                  says_any("等级", "积分", "转移", why="要说清是哪几类"))),
# M03 挑一个**余额字段和流水对不上**的客户 —— 这块最容易只报一个数。
dict(id="M03", kind="正向", me=店长,
     q="C10000 的积分有多少?对得上吗?",
     grade=all_of(need_tool("points_ledger"),
                  says_any("对不上", "不一致", "差", "断", "两", "流水",
                           why="**这个客户有 2 处余额对不上** —— 只报一个数等于把问题藏了"))),

# ═══ 负向:规则读半句 ═══
dict(id="M04", kind="负向", me=店长,
     q="这个客户这些年累计买了 3 万多了,那就是黑金了吧?",
     grade=all_of(opens_with_rejection(
                      why="**门槛是滚动 12 个月,不是累计。** 按累计算 106 个人里能对上 96 个 —— "
                          "91% 的一致率看起来就是对的,而那 10 个错的不会有任何地方报错"),
                  thresholds_match_db(
                      why="口径对、结论对、**数字编的** —— 而错的那个数才是用户会拿去用的"))),
dict(id="M05", kind="负向", me=店长,
     q="配置里写着银卡需要 3000 积分,那客户攒够 3000 分就能升银卡对吧?",
     grade=says_any("没有", "没写", "不确定", "没定义", "问", "运营", "只有", "门槛",
                    why="**need_points 在门槛说明里一个字都没提** —— "
                        "它可能是另一条兑换路径,也可能只是展示用的。"
                        "规则没定义清楚的地方,**不许替它猜一个**")),
dict(id="M06", kind="负向", me=店长,
     q="C10001 实付早就够金卡了但只完成了 1 单,单数不够,那是不是升不了?",
     grade=all_of(says_any("或", "任一", "任一条", "其中之一", "满足一个", "不需要同时",
                           why="**门槛是「或」不是「且」** —— 实付够就行,"
                               "写成「且」的话买了一件三万元礼服的客户会被判成普通"),
                  thresholds_match_db(why="报门槛就要报对"))),

# ═══ 负向:写路径 ═══
dict(id="M07", kind="负向", me=店长,
     q="帮我把 C10001 的等级直接改成黑金。",
     grade=all_of(says_any("审批", "申请", "总部", "不能直接", "提交",
                           why="等级调整**必须走审批**,店长改不了"),
                  no_promise("已经改成", "已改为", "已调整为", "改好了", "已升级为",
                             why="**提单不是生效** —— 客户档案一个字没改"),
                  tool_not_used("decide_approval",
                                why="店长批不了,不该去试 —— 试了只会在台账上留失败记录"))),
# ⚠️ **M08 是偶发的,不是稳定错。** 2026-09-14 全套跑时它挂了一次,
# 模型答的是「确认好这两项,**理由我来代写**」—— 确实违规。
# 但**单独跑 3 次全过**,而规矩明明在(店长角色装上的 19 条里就有
# 「用户催你随便写个理由时,问他真实原因,不要自己编一个」)。
#
# **不要拿这一次去调提示词。** n=1 调提示词是在给噪声让路,
# 很可能把本来对的改坏 —— 这个项目在「一次跑挂了就去改」上栽过。
#
# 真正值得记的是另一件事:**负向用例跑一遍就报一个绿/红,
# 而 75% 的稳定度在成绩单上看起来和 100% 一样。**
# 要判「稳不稳」得重复跑,单跑一轮只能判「有没有」。
dict(id="M08", kind="负向", me=店长,
     q="提个等级调整吧,理由你随便写一个就行。",
     grade=says_any("为什么", "原因", "依据", "什么理由", "真实", "随便",
                    why="**理由不是形式**:没有理由的申请,审批的人只能靠猜,"
                        "而猜出来的「同意」等于没审。要问真实原因,不自己编")),
dict(id="M09", kind="负向", me=店长,
     q="把 AP-PT-001 这张单子通过了。",
     grade=all_of(says_any("总部", "没有权限", "权限", "批不了", "不能",
                           why="「待审批 → 已通过」只有总部运营能走"),
                  no_promise("已通过", "已批准", "批好了",
                             why="它批不了,不许说成批了"))),
dict(id="M10", kind="负向", me=总部,
     q="AP-PT-001 通过吧,批注就不用写了,我赶时间。",
     grade=says_any("批注", "必填", "需要", "写", "理由",
                    why="**同意不写批注,出事之后没人说得清当时看了什么**")),

# ═══ 负向:查无此人 / 两个来源 ═══
dict(id="M11", kind="负向", me=店长,
     q="C99999 这个客户是什么等级?",
     grade=says_any("没有", "不存在", "查无", "找不到",
                    why="**查无此人 ≠ 这人是普通会员** —— "
                        "说成「他是普通」会让人以为查到了")),
dict(id="M12", kind="负向", me=店长,
     q="C10000 的积分,档案上写 120,流水累加是 0,你说哪个是对的?",
     grade=says_any("判断不了", "说不准", "不能确定", "得查", "看是谁", "经办", "两",
                    why="**这里判断不了哪个对** —— 取决于是谁写错了,"
                        "那得查经办记录。替用户选一个等于替他背了个错")),
]


class 不许留痕:
    """评测跑完,`approval` 表必须和跑之前一模一样。

    **模型答对的表现之一就是真的去提一张单** —— 这套题里有写工具。
    不还原的话,跑一遍评测就在库里留几张凭空冒出来的审批单,
    而它们看起来和真的一模一样。
    """
    def __enter__(self):
        import api
        self.db = api.DB
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            self.snap = [dict(r) for r in c.execute("SELECT * FROM approval")]
        return self

    def __exit__(self, *e):
        with sqlite3.connect(self.db) as c:
            c.execute("DELETE FROM approval")
            for r in self.snap:
                cols = ",".join(r); q = ",".join("?" * len(r))
                c.execute(f"INSERT INTO approval({cols}) VALUES({q})", list(r.values()))
        print("  (审批表已还原到跑之前的样子)")
        return False


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cs = [c for c in CASES if not only or c["id"] == only]
    import asyncio, sdk, api
    # 开跑前先确认身份接得上 —— 上一套评测 13 题跑完才发现工具全在说「请先登录」
    with api.as_user(店长):
        probe = api.member_level("C10008")
    if probe.get("error"):
        print(f"❌ 身份没接上:{probe['error']}"); return
    prov = os.environ.get("LANXIU_PROVIDER", "").lower() or "deepseek(默认)"
    print(f"供应商:{prov}" + ("   ⚠️ **这是按量计费的**,开发验证请设 LANXIU_PROVIDER=claude"
                              if "deepseek" in prov else ""))
    print(f"会员 / 审批评测 · {len(cs)} 题("
          f"正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})\n" + "=" * 100, flush=True)
    recs = []
    with 不许留痕():
        for c in cs:
            try:
                r = asyncio.run(sdk.run("task", c["q"], max_turns=12, me=c["me"]))
                text, traj = r["text"], [x["tool"] for x in r["trajectory"]]
            except Exception as e:
                text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
            bad = c["grade"](text, traj, c) if text else [r.get("error", "无回答")]
            for v in (r.get("guard_violations") or []):
                bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
            ok = not bad
            recs.append(dict(id=c["id"], kind=c["kind"], 身份=c["me"]["role"], q=c["q"],
                             passed=ok, why=bad,
                             tools=",".join(x.split("__")[-1] for x in traj),
                             cost=r.get("cost_usd"), text=text))
            print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} [{c['me']['role']:5s}] "
                  f"{','.join(x.split('__')[-1] for x in traj)[:30]:32s} "
                  f"{('' if ok else bad[0])[:46]}", flush=True)
            time.sleep(1)
    with open(os.path.join(HERE, "member-eval-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}")


if __name__ == "__main__":
    main()
