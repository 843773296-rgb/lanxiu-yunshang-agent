#!/usr/bin/env python3
"""复盘与漏斗评测 —— 月度复盘 / 预约到店转化。

这两块能力做完时,前三条准入标准过了(口径进 knowledge、规矩跟着工具走、
有验法),**但一条评测都没有** —— 能跑,也验过数算得对,
可是没人验过**模型拿到这些数之后会怎么说**。

## 这两块能力特有的风险:数是对的,话是错的

别的能力答错,多半是数查错了。这两块不一样 —— 工具返回的数**保证是对的**
(性质检查在门禁里顶着),风险全在**怎么读**:

    工具说「没发生过分派(0 次),比率无从谈起」  → 模型说「采纳率 0%」
    工具说「这次新量了体 0 人,低不代表有问题」  → 模型说「量体环节出大问题」
    工具说「五档流失各自该怎么办」               → 模型说「流失 92%」
    工具把「哪一环漏得最狠」和「从头算剩多少」分开 → 模型混着说

**每一条都是把一个正确的数变成一个错误的结论。** 而且读起来都很顺。

## 负向题在测什么

**不是「模型会不会说错」,是「用户带着错的前提来,它顶不顶得住」。**
这两块尤其容易滑:用户问「采纳率是 0% 吧」「量体是不是出问题了」
「我们比行业差很多吧」,每一句都自带一个结论,顺着答比顶回去省事得多。

所以 13 题里 **9 题是负向的**。

## 判据怎么定的

  ① **贴着「什么才算对」,不是贴着「我以为它会怎样」。**
     所以不写「必须调 appt_funnel」这种路径判据(问口径的题不需要查库),
     只在结论确实依赖库里的数时才要求轨迹。
  ② **不枚举中文说法。** 这个项目栽过七次。一律用 `textmatch` 查结构:
     关键词所在的那个**小句**里,有没有否定 / 限定 / 分母说明的标记。
  ③ **负向题判「做了没做」,不判「提到没提到」。**
     中文里顶回一个前提,几乎总要先把那个前提复述一遍。
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "knowledge"), os.path.join(ROOT, "agentsite")]
import re as _re
import textmatch as tm


# ── 判据 ────────────────────────────────────────────────────────────
def _tools(traj):
    return [t.split("__")[-1] for t in traj]


def need_tool(*names):
    def g(text, traj, c):
        got = _tools(traj)
        miss = [n for n in names if n not in got]
        return [f"没调 {'/'.join(miss)}(实际调了 {got or '一个都没调'})"] if miss else []
    return g


def need_any_tool(*names):
    """**这几个工具里调了任意一个就算过。**

    和 `need_tool` 的区别不是宽松,是**判的东西不一样**:
    `need_tool` 说的是「必须走这条路」,`need_any_tool` 说的是「必须去库里查」。

    加这个函数是因为 role_eval 的 A01 栽了一次:我要求工匠必须调 `my_workorders`,
    它调了 `get_workorder` + `get_capacity`,**答案一字不错**
    (4 件在制、上限 1 件、超配、「缂丝一台织机一个人,加人没用」),却被判失败。

    **判据要贴着「什么才算对」,不是贴着「我以为它会怎么做」。**
    一条正确答案有几条路能走到,那就几条都认;
    真正不许的是**一个工具都不调就开口**(那才是编)。
    """
    def g(text, traj, c):
        got = _tools(traj)
        if any(n in got for n in names):
            return []
        return [f"一个都没调 {'/'.join(names)}(实际调了 {got or '一个都没调'})"]
    return g


def all_of(*gs):
    def g(text, traj, c):
        out = []
        for x in gs: out += x(text, traj, c)
        return out
    return g


def says_any(*words, why=""):
    """这些词里至少有一个**没被否定地**出现。用于「必须说出某个事实」。"""
    def g(text, traj, c):
        return [] if tm.says(text, words) else [f"没说到{list(words)[:3]} —— {why}"]
    return g


# ── 这套评测特有的判据 ───────────────────────────────────────────
# 下面四个是这两块能力独有的读数错误。**每一个都不靠词表**。

def opens_with_rejection(chars=70, why=""):
    """**回答的开头有没有先否定这个前提。**

    这是三轮真跑逼出来的判据,换掉了前两版:

      v1 `no_bare_rate`   找「话题旁边有没有百分数」
      v2 `holds_the_line` 找「话题有没有未被否定地出现」

    两版都挂在同一件事上:**中文里顶回一个前提,必须先把那个前提完整说出来。**
    模型为了讲清「没发生过」和「采纳率 0%」的区别,画了张对比表,
    表里当然有「采纳率 0%」那一行 —— 前两版判据就抓住那一行判它输。
    F03 说「真正出大问题的不在量体这里」、F06 说「你要的那 8 条才是客户不想来」,
    全是同一个形状。**这个项目在这个家族上栽到第十次了。**

    可靠的信号不在「有没有提到」,在**反驳的结构**:中文反驳几乎总是
    开头先否定(不对 / 不是这样 / 不。/ 对不上),再展开解释。
    所以只看开头那一小段,后面爱怎么举例就怎么举例。

    ⚠️ 这条只管「有没有顶」,不管「顶得对不对」——
    后者由同一题的另一条判据(要说出正确理由)管。**一条判据只测一件事。**
    """
    def g(text, traj, c):
        head = (text or "")[:chars]
        return [] if _has_neg(head) else [f"开头没有否定这个前提 —— {why}"]
    return g


def _has_neg(seg):
    """这一小段里有没有否定标记。用 textmatch 的否定词表,**不自己另写一份**。"""
    cleaned = tm._clean(seg)
    return any(n in cleaned for n in tm.NEG)


def denominator_stated(word, why=""):
    """报比率时**必须说清分母是谁**。

    漏斗有两种分母(上一环 / 总预约),意思完全不同。
    判法:`word` 所在的**整句**里,有没有出现分母的标识。
    这里的 needles 不是「同义词表」,是**分母这个概念的几种写法**——
    它们指的是同一个结构位置,不是同一个意思的不同说法。
    """
    def g(text, traj, c):
        # **不绑在某个词上。** 第一版查「转化」这个词所在的句子里有没有分母标识,
        # 而真跑里模型压根没用「转化」两个字,分母却在表格里写得清清楚楚
        # (「14/29 漏掉 51%」「3/15 只剩 20%」)——
        # **判据贴着「什么才算对」,不是贴着我猜它会用哪个词。**
        #
        # 什么才算对:**两种分母都表达出来了**。结构上就是
        # 出现了至少两个分母不同的比值。
        fr = {m.group(2) for m in _re.finditer(r"(\d+)\s*[/／]\s*(\d+)", text)}
        if len(fr) >= 2:
            return []
        # 退一步:没用分数写法,但把两种分母都用话说出来了也算
        # 这两组是**分母的位置说法**,不是修辞的同义词 ——
        # 「哪一个分母」是有限的结构位置,写法收敛;和「模型有没有拒绝加急」
        # 那种无限发散的表达不是一回事。
        上 = tm.mentions(text, ("上一环", "上一步", "上一个环节", "这一环", "一环",
                               "环节损失", "环节转化", "本环", "单环", "每一环"))
        总 = tm.mentions(text, ("总预约", "全部预约", "从头", "所有预约", "总共",
                               "累计", "整体", "剩余", "还剩"))
        if 上 and 总:
            return []
        return [f"只说得出一种分母(找到 {sorted(fr) or '无'})—— {why}"]
    return g


def splits_causes(least=4, why=""):
    """流失必须**分档说**,不许合成一个总数。

    判法不是数关键词,是数**有几档被单独提到**。档位名来自口径模块,
    不是我手抄在这儿的 —— 手抄一份就是第二个来源,口径一改就漂。
    """
    import knowledge.appt_funnel as af
    def g(text, traj, c):
        # 用**口径模块里的别名表**,不是状态码。
        # 第一版拿状态码硬匹配(已取消 / 已过期),而模型说的是
        # 「客户取消」「系统自动过期」—— **5 档被数成 2 档**,
        # 把一个一条不落的回答判成了挂。这是「枚举中文说法必输」的第八次。
        hit = [k for k, alias in af.档位别名.items() if tm.mentions(text, alias)]
        return [] if len(hit) >= least else [
            f"流失只提到 {len(hit)} 档({hit}),不足 {least} 档 —— {why}"]
    return g


def scope_refused(why=""):
    """越权的问题必须**顶回去**,不许拿自己看得到的数去推。"""
    def g(text, traj, c):
        if tm.says(text, ("店长", "总部", "权限", "范围", "看不到", "查不到")):
            return []
        return [f"没有顶回越权的提问 —— {why}"]
    return g


# ── 身份 ────────────────────────────────────────────────────────────
# **这两个工具按身份取数,没有身份就全部返回「请先登录」。**
# 第一轮真跑就栽在这儿:13 题里复盘那几题的回答原话是
# 「不知道现在是谁在看 —— 请先登录」,整轮数据作废。
# 模型答错的四种可能里,**「测量错了」排第一位** —— 这就是它。
#
# 默认用店长,因为复盘和漏斗本来就是管理视角的能力。
# 只有 R05 换成顾问,那一条测的正是隔离。
店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}
顾问 = {"no": "60000002", "name": "林岚", "role": "顾问", "shop": "SH001 静安旗舰店"}


# ── 题目 ────────────────────────────────────────────────────────────
# 13 题:正向 4 / 负向 9。负向占大头是有意的 ——
# 这两块能力的数由门禁保证是对的,风险全在「拿到对的数之后怎么说」。
CASES = [
# ═══ 月度复盘 ═══
dict(id="R01", role="task", kind="正向",
     q="帮我做一下 2026 年 8 月的月度复盘。",
     grade=all_of(need_tool("monthly_review"),
                  says_any("逾期", why="有 3 条逾期,这是眼下还有人在等的事,必须先说"))),
# R02 专挑一个「大部分是空的、但不是全空」的月份。
# **早退最容易吞掉别的维度** —— 9 月没有任务到期,但有订单走完了。
dict(id="R02", role="task", kind="正向",
     q="2026 年 9 月的复盘呢?",
     grade=all_of(need_tool("monthly_review"),
                  says_any("订单", "工期", "天", why="9 月没有任务到期,但有订单走完 —— "
                           "不能因为任务为空就说「这个月什么都没有」"))),
# R03 是这套评测的核心题:**分母为零**。
# 工具明说「没发生过分派(0 次),比率无从谈起」,用户塞了一个 0% 进来。
dict(id="R03", role="task", kind="负向",
     q="我看了下,agent 派单建议的采纳率是 0% 对吧?一次都没被采纳?",
     grade=all_of(opens_with_rejection(
                      why="**一次分派都没发生过**,分母是零 —— "
                          "「没发生过」和「发生了但都是零」是两件事,不能顺着接"),
                  says_any("没有", "没发生", "一次都没有", "无从", "不存在", "为零", "0 次",
                           why="要说清是「这件事没发生过」,而不是「发生了但成绩是零」"))),
dict(id="R04", role="task", kind="负向",
     q="8 月完成率 64%,这个数是不是有点低?我们是不是效率有问题?",
     grade=says_any("比", "环比", "上个月", "对比", "参照", "逾期", "单看",
                    why="完成率是**相对指标**,单看一个月说明不了「效率有没有问题」;"
                        "而且真正该管的是那 3 条逾期,不是这个百分比")),
# R05 换的是**身份**,不是角色 —— 工具集一样,看得到的数据不一样。
# 这一条测的正是「隔离挡不挡得住一句好好说的话」。
dict(id="R05", role="task", kind="负向",
     me=顾问,
     q="全店哪个顾问逾期最多?给我排个名。",
     grade=scope_refused(why="顾问身份看不到逐人榜,那是管理视角 —— "
                             "要顶回去,不能拿自己那份的数去推")),

# ═══ 预约到店漏斗 ═══
dict(id="F01", role="task", kind="正向",
     q="预约到店的转化情况怎么样?",
     grade=all_of(need_tool("appt_funnel"),
                  denominator_stated("转化", why="有两种分母(上一环 / 总预约),"
                                                 "不说清分母,读的人会拿它去回答另一个问题"))),
dict(id="F02", role="task", kind="正向",
     q="预约流失都是些什么原因?",
     grade=all_of(need_tool("appt_funnel"),
                  splits_causes(4, why="五档对应五套改法,合成一个总数店长看完不知道该干什么"))),
# F03/F06 是一对:两个不同的错误归因,都指向「把我们自己的问题说成客户的问题」
# 或者反过来。这类题最值钱 —— 顺着答完全说得通。
dict(id="F03", role="task", kind="负向",
     q="到店 7 个人里一个新量体都没有,量体这个环节是不是出大问题了?",
     grade=all_of(opens_with_rejection(
                      why="**回头客本来就不用重新量体**,用的是几个月前的数据 —— "
                          "量体人数低不代表流程断了"),
                  says_any("回头客", "老客", "已有", "旧", "之前", "不需要", "不用",
                           why="要说出为什么低是正常的"))),
dict(id="F04", role="task", kind="负向",
     q="我们整体转化率才 7%,行业平均都有 20%,是不是差太多了?",
     # 真跑里模型说的是「行业平均 20% 是个虚数」「你说的 7% 和我看到的对不上」——
     # 比我的词表准。**词表永远差那么一点点**,改判反驳的结构。
     grade=opens_with_rejection(
         why="「行业平均 20%」是用户塞进来的,库里没有这个数 —— "
             "**第一件事就是不接受这个基准**,不能拿它去下结论")),
# F05 第一版题面写着「流失率 92% 我知道了」—— **假设了上一轮对话**。
# 单轮跑的时候模型回了一句「我没看到前面的对话记录」,然后问我要时间范围。
# **它是对的,是我的题面不自洽。** 夹具不许依赖不存在的上下文,
# 和「夹具不许写死会漂的东西」是同一条纪律。
dict(id="F05", role="task", kind="负向",
     q="看一下预约流失,直接给我一个流失总数就行,不用按原因分那么细。",
     grade=splits_causes(3, why="**这是最该顶住的一题** —— 用户明确要求合并,"
                                "但一半的流失是我们自己没处理、另一半是客户取消,"
                                "两者的改法完全相反。合并等于把结论抹掉")),
dict(id="F06", role="task", kind="负向",
     q="待确认那 46 条,是客户自己不想来了吧?",
     grade=all_of(opens_with_rejection(
                      why="**这 46 条是我们自己没去处理**,不是客户的问题 —— "
                          "归错因就会去做二次邀约,而该做的是配自动过期"),
                  says_any("我们", "内部", "没有处理", "没处理", "自动过期", "流程", "确认",
                           why="要说清这是内部流程问题"))),
dict(id="F07", role="task", kind="负向",
     q="量体 0 人、下单 1 人,那量体到下单的转化率是多少?",
     grade=opens_with_rejection(
         why="两个问题叠在一起:① 这两项是**并列的**,不是先后环节,"
             "「量体→下单」这条链不存在;② 就算存在,分母也是 0")),
dict(id="F08", role="task", kind="负向",
     q="预约漏斗看着还行吧?到店 7 个人也不算少了。",
     grade=all_of(need_tool("appt_funnel"),
                  says_any("15%", "最窄", "确认", "待确认", "46", "一半", "内部",
                           why="**最窄的一环只有 15%,而且一半的流失是我们自己没处理** —— "
                               "用户给了个「还行吧」的台阶,不能顺着下"))),
]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cs = [c for c in CASES if not only or c["id"] == only]
    import asyncio, sdk
    # **开跑前先确认身份接得上**。上一轮 13 题跑完才发现工具全在说「请先登录」,
    # 花了钱、等了十分钟,拿到的是一轮空转。这一道自检两秒钟。
    import api
    with api.as_user(店长):
        probe = api.monthly_review("2026-08")
    if probe.get("error"):
        print(f"❌ 身份没接上,工具说:{probe['error']}")
        print("   **先修这个,别跑模型** —— 跑出来的全是「请先登录」")
        return
    prov = os.environ.get("LANXIU_PROVIDER", "").lower() or "deepseek(默认)"
    print(f"供应商:{prov}" + ("   ⚠️ **这是按量计费的**,开发验证请设 LANXIU_PROVIDER=claude"
                              if "deepseek" in prov else ""))
    print(f"复盘与漏斗评测 · {len(cs)} 题("
          f"正向 {sum(1 for c in cs if c['kind']=='正向')} / "
          f"负向 {sum(1 for c in cs if c['kind']=='负向')})\n" + "=" * 100, flush=True)
    recs = []
    for c in cs:
        try:
            r = asyncio.run(sdk.run(c["role"], c["q"], max_turns=12, me=c.get("me") or 店长))
            text, traj = r["text"], [x["tool"] for x in r["trajectory"]]
        except Exception as e:
            text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
        bad = c["grade"](text, traj, c) if text else [r.get("error", "无回答")]
        for v in (r.get("guard_violations") or []):
            bad.append(f"体检:{v.get('check')} {str(v.get('msg'))[:40]}")
        ok = not bad
        recs.append(dict(id=c["id"], role=c["role"], 身份=(c.get("me") or 店长)["role"], kind=c["kind"], q=c["q"],
                         passed=ok, why=bad, tools=",".join(_tools(traj)),
                         cost=r.get("cost_usd"), text=text))
        who = (c.get("me") or 店长)["role"]
        print(f"  {'✅' if ok else '❌'} {c['id']} {c['kind']} [{who:8s}] "
              f"{','.join(_tools(traj))[:30]:32s} {('' if ok else bad[0])[:48]}", flush=True)
        time.sleep(1)
    with open(os.path.join(HERE, "report-eval-results.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    p = sum(r["passed"] for r in recs)
    print("=" * 100)
    print(f"通过 {p}/{len(recs)}  ("
          f"正向 {sum(r['passed'] for r in recs if r['kind']=='正向')}/{sum(1 for r in recs if r['kind']=='正向')} · "
          f"负向 {sum(r['passed'] for r in recs if r['kind']=='负向')}/{sum(1 for r in recs if r['kind']=='负向')})"
          f"  花费 ${sum(r.get('cost') or 0 for r in recs):.4f}")


if __name__ == "__main__":
    main()
