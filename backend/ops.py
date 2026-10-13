#!/usr/bin/env python3
"""智能运维平台的数据层 —— 队列、研判台账、销账、回流、健康度。

和「展示件」的分界线全在这个文件里:

  展示件            平台
  ────────────────  ──────────────────────────────────────────
  你点它才跑         积压在那儿等着被跑完
  跑完显示一次       落库,谁都能回头看当时说了什么、花了多少钱
  有标准答案可判分   **上线后没有标准答案**,只有人采不采纳
  跑完就结束         人的裁决回流成新标注,下次回归用得上

最后一条是这套东西能不能越用越准的关键。评测集不是上线前写完就冻住的,
是值班同学每否掉一条就长一条。
"""
import json, os, sqlite3, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "lanxiu.db")
# 本库 = 模块载入时那个库。检查脚本会把 DB 指向临时副本,但改不到这个 ——
# 销账后的判读上报**只在本库上发生**(2026-10-12:ops_resolve_check 第一次在副本上销账,
# 两条假判读进了真投递箱;同 artifact_report.是本库 那次 10-10 的事故)
_本库 = DB

# 时效承诺。定在这里而不是散在页面上,是因为它是**业务承诺**,不是显示逻辑。
# 退款失败压着客户的钱,比客户合并急。
# ✅ **四个数都是业务拍过的**:差评 48(10-11);退款异常 24 / 售后判责 36 / 客户合并 48
#   (用户 2026-10-13 在三案里选「照现在的数定」,没选「一律 48」「都收紧一档」)。
#   在那之前这三个是开发按理由定的 —— 理由原样留在下面,它们就是拍板时给用户看的那几句。
# 🔻 **还没拍的**:按什么日历算(夜里、周末算不算)、等顾客回话时停不停表 —— 现在是自然小时、不停表。
SLA_HOURS = {"财务人工任务": 24, "客户合并确认": 48,
             # 售后判责比合并急:客户手里拿着一件坏了的衣服在等回话。
             # 但比退款松 —— 判责要查现场(面料工艺、量体记录、告知签收),
             # 24 小时逼出来的多半是「先答应免费返修」,那是最贵的错法。
             "售后判责": 36,
             # ✅ **业务 2026-10-11 拍了 48 小时**(用户代业务方)。
             #
             # 这一行的历史值得留着 —— 它是「代码里定的数会被当成业务定的数」的样本:
             # 2026-09-27 业务只说了差评「归店长跟」,**没给时长**,而我在这里
             # 写了 72 小时并标注「这个数业务没拍过」。那个标注救了它:
             # 2026-10-11 清点「哪些数是业务没拍过的」时,它是唯一被揪出来的。
             # > 一个业务拍过的数和一个开发定的数,**在报表上长得一模一样** ——
             # > 分开它们的只有一句注释。**所以这类注释不许省。**
             #
             # 为什么从 72 收到 48(拍板时给的理由):
             # · 差评**可以改分**(产品上这条路存在)、且**全部非匿名**(实测 214 条
             #   匿名 0 条、全来自自家小程序)—— 联系得上具体的人,及时跟进有机会挽回。
             # · 但不收到 24:**214 条全压在「售后」一个角色上**(它还要管售后判责),
             #   而处理方式是回访 / 补救,要和客户约时间 —— 24 小时会变成批量盖章,
             #   而「盖过章的」和「真处理过的」在记录上长得一模一样。
             # ⚠️ 原来 72 的理由(「不阻塞任何人,所以比兜底 48 还松」)**不是错的**,
             # 它只是只看了「有没有人在等」这一维,没看「这件事还救不救得回来」。
             # ⚠️ 实测数据里那组改分记录(往下改 28 条、往上 7 条,而且改分发生在处理
             # **之前** 50–75 小时)**不能当依据** —— 它是脚本造的,
             # 既证不实也证不伪「快点处理能挽回」。上面的理由是结构性的,不是这组数推的。
             #
             # **要改就改这一个数**(`ops.queue()` 会把它报在 `sla_h` 字段上,
             # 页面上看得见,不是隐形策略)。
             "评价差评": 48}
DEFAULT_SLA = 48

# ── 进不进「超时率」这个考核数 ────────────────────────────────────────
#
# 业务 2026-09-27 的原话:差评「能对到顾问但**不进考核,只给店长看**」。
# 而 `backlog()` 的 `已超时` 是**考核数** —— 所以差评落进去,
# 就是在执行一条和业务口径**相反**的规则。
#
# ⚠️ 这不是「多一个开关」,这是把口径写成可执行的。不这么做的后果实测过:
# 铺进 204 条差评工单之后,其中一条演示数据里故意留的老单挂了 114 天,
# **当场把超时率改了** —— 而看板上没有任何东西提示那个数的口径变了。
#
# ⚠️⚠️ 但**不进考核 ≠ 不用处理**。所以两个数都要报:
#   `已超时`      考核口径(不含下面这些类型)
#   `已超时_含不考核`  全部
# 只报第一个会让店长该跟的单子从看板上消失;只报第二个就是现在这个错。
# **一个数不够表达「要处理但不算账」。**
不进考核的类型 = {"评价差评"}


def 时效声明齐吗(出现的, 声明的=None, 不考核的=None):
    """库里出现的每个 task type 都在时效表里显式写着吗?

    返回 `(没声明的, 空转的排除, 囤着的死条目)`,三个都是排好序的清单。

    ## 为什么反过来判(从库里的 type 往表里找,不是相反)

    2026-09-27 并行会话往共用的 `task` 表加了一个新 type「评价差评」。
    它**没崩** —— `SLA_HOURS.get(type, DEFAULT_SLA)` 兜住了,于是
    204 条历史差评工单按默认 48 小时计时效,201 条立刻超时,
    **把超时率从 20% 改成 99%**,而没有任何东西报错。

    > **一张共用的清单,加一个新 type,会打到所有「全表扫 + 按 type 分流」的消费者。**
    > 而 `.get(x, 默认值)` 正是让这件事**不报错**的那个东西。

    想用默认值也得写进表里 —— **写一个 48 和不写,在代码上的差别正是「有人想过」。**

    ## 为什么是纯函数

    这样咬合**不用碰库、不用改文件**:传不同的参数就行。
    并行会话看不到任何中间态,也不存在「恢复失败」这回事 ——
    而「恢复失败」和「恢复成功」在输出上一模一样,要到下一次跑才看得出来。
    """
    声明的 = set(SLA_HOURS if 声明的 is None else 声明的)
    不考核的 = set(不进考核的类型 if 不考核的 is None else 不考核的)
    出现的 = set(出现的)
    return (sorted(出现的 - 声明的),        # 没声明 → 会被静默套上默认值
            sorted(不考核的 - 出现的),      # 排除规则排不掉任何东西 = 空转
            sorted(声明的 - 出现的))        # 声明了但库里没有 = 死条目(不算错)

DECISIONS = ("已采纳", "已改判", "已升级")


# ── 咬合记录 ──────────────────────────────────────────────────────────
# 左边「改坏了什么」,右边「预期红的那一条」。**每一条都在 tools/bite_specs.json 里
# 有一份可执行的规格**,`python3 tools/bite_run.py` 能重放:对照要先绿,改坏之后
# 要红,而且红的必须是右边这一条 —— 三关缺一关,这条记录就不算数。
咬合 = [
    ('把量体超期的拦截关掉(过期的尺码也放行下单)',
     '过期的没拦住'),
]

def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def _rows(sql, *a):
    with _c() as c: return [dict(r) for r in c.execute(sql, a)]


def now():
    """**世界的当下**,不是机器的当下。

    ⚠️ 2026-09-26 第八个。这个文件里它有三处用途,而**第一处的错最直接**:

        out, n = [], now()
        waited_h = (n - created).total_seconds() / 3600     # created 来自 task 表

    `task.created` 是**世界数据**(会被 shift_world 平移)。拿机器时间去减它,
    算出来的「等了几小时」就是错的 —— 而它在页面上是个很正常的数字,
    没有任何地方会报错。这和「生命周期按多久没互动算」是同一族。

    另两处(`triage.created` / `handled_at`)也会被平移,机器时钟写进去之后
    会被一天天推进未来。
    """
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
    import worldclock
    return worldclock.当下().replace(microsecond=0)


def _dt(s):
    if not s: return None
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return dt.datetime.strptime(s, f)
        except ValueError: continue
    return None


# ── 一、队列 ────────────────────────────────────────────────────────────
def queue(state=None):
    """值班队列。每条带:等了多久、离超时还有多久、智能体研判到哪一步了。

    「等了多久」是运维平台和展示件体感差别最大的一个字段 ——
    展示件里没有时间,平台里时间是压力。
    """
    latest = {}
    for t in _rows("SELECT * FROM triage ORDER BY id"):
        latest[t["task_id"]] = t          # 同一工单研判多次,取最后一次

    out, n = [], now()
    for t in _rows("SELECT * FROM task ORDER BY created"):
        created = _dt(t["created"]) or n
        waited_h = (n - created).total_seconds() / 3600
        sla = SLA_HOURS.get(t["type"], DEFAULT_SLA)
        tr = latest.get(t["id"])
        st = "未研判" if not tr else tr["status"]
        # ── done 有**两个权威来源**(业务 2026-09-28 拍板,见业务拍板-20260927 第四条)──
        #
        #     done = triage 有结论(已采纳/已改判/已升级) 或 task.status='已关闭'
        #
        # 为什么两个都要:它们说的是**不同的事**。
        #   · triage 有结论 → 研判走完了,有人给了处理意见
        #   · task 已关闭   → 这件事结束了,**而它可能从来没走过研判**
        # 只认前者,会让 201 条早已关闭的工单永远挂在待办上(实测 271 → 56);
        # 只认后者,会让研判完但没人去关单的那些被当成还没处理。
        #
        # ⚠️ **同时报「凭什么销账」,不把两者压成一个布尔值。**
        # 压平之后「研判过并采纳了」和「工单被关掉但一条研判都没走过」
        # 长得一模一样 —— 而后者要人看一眼:它可能是对的(有些事不需要研判),
        # 也可能是有人直接关单了事。**一个数不够表达两种闭环。**
        研判有结论 = st in DECISIONS
        工单已关闭 = (t["status"] == "已关闭")
        done = 研判有结论 or 工单已关闭
        凭什么 = None
        if 研判有结论 and 工单已关闭:
            凭什么 = "研判有结论且工单已关闭"
        elif 研判有结论:
            凭什么 = "研判有结论(工单还没关)"
        elif 工单已关闭:
            凭什么 = "工单已关闭(**没走过研判**)"
        if done:                       # 已销账的不再计时效
            level, left = "已销账", None
        else:
            left = sla - waited_h
            level = "已超时" if left <= 0 else ("临期" if left <= sla * 0.25 else "正常")
        out.append(dict(
            task_id=t["id"], type=t["type"], ref=t["ref_id"], created=t["created"],
            waited_h=round(waited_h, 1), sla_h=sla, left_h=None if left is None else round(left, 1),
            level=level, state=st, done=done, 凭什么销账=凭什么,
            研判有结论=研判有结论, 工单已关闭=工单已关闭,
            triage_id=tr["id"] if tr else None,
            ai_root_cause=tr["ai_root_cause"] if tr else None,
            ai_confidence=tr["ai_confidence"] if tr else None,
            cost=tr["cost"] if tr else None,
            # 已办结 = 有回执(用户 10-13 拍)。**和「已销账」是两层**:销账是复核完了,办结是现实里办完了
            已办结=bool(tr and tr.get("receipt")),
            回执=(f"{tr.get('receipt_kind')} {tr['receipt']}" if tr and tr.get("receipt") else None),
        ))
    if state == "待办":  out = [x for x in out if not x["done"]]
    elif state == "未研判": out = [x for x in out if x["state"] == "未研判"]
    elif state == "待复核": out = [x for x in out if x["state"] == "待复核"]
    elif state == "已销账": out = [x for x in out if x["done"]]
    # 超时的排最前,然后按等待时长倒序 —— 队列的排序本身就是一种业务规则
    rank = {"已超时": 0, "临期": 1, "正常": 2, "已销账": 3}
    out.sort(key=lambda x: (rank[x["level"]], -x["waited_h"]))
    return out


def backlog():
    """积压看板。看的是「今天还剩多少件」,不是「历史一共多少件」。"""
    q = queue()
    todo = [x for x in q if not x["done"]]
    by_state, by_type = {}, {}
    for x in todo:
        by_state[x["state"]] = by_state.get(x["state"], 0) + 1
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
    over_全部 = [x for x in todo if x["level"] == "已超时"]
    # **考核口径**:把业务明说「不进考核」的类型排掉(见文件头 `不进考核的类型`)
    over = [x for x in over_全部 if x["type"] not in 不进考核的类型]
    临期_全部 = [x for x in todo if x["level"] == "临期"]
    return dict(
        总量=len(q), 待办=len(todo), 已销账=len(q) - len(todo),
        已超时=len(over), 临期=len([x for x in 临期_全部
                                 if x["type"] not in 不进考核的类型]),
        # ⚠️ 这两个数**必须同时在**。只报考核口径,店长该跟的单子会从看板上消失;
        # 只报全部,就是 2026-09-27 那个「114 天的老差评改了超时率」。
        # **一个数不够表达「要处理但不算账」。**
        已超时_含不考核=len(over_全部), 临期_含不考核=len(临期_全部),
        不进考核的类型=sorted(不进考核的类型),
        # ⚠️ **超时的是哪几类,要报出来。**
        # 2026-09-28 改 done 判据之后剩 55 条超时,其中 51 条集中在
        # 售后判责 / 客户合并 / 财务 —— 那三类**一条研判都没有**。
        # 那是既有状况,不是评价功能带来的。
        # 只给一个「已超时 55」的数字,店长会去逐条翻;
        # 报了分布,他一眼看出「这是三类活没人接」而不是「55 件散单」。
        # **一个总数不足以让人知道下一步该做什么。**
        已超时_按类型=dict(sorted(
            ((k, sum(1 for x in over_全部 if x["type"] == k))
             for k in {x["type"] for x in over_全部}),
            key=lambda kv: -kv[1])),
        # 销账的依据分布 —— 「没走过研判就关掉」有多少,是个要看的数
        销账依据=dict(sorted(
            ((k, sum(1 for x in q if x["凭什么销账"] == k))
             for k in {x["凭什么销账"] for x in q if x["凭什么销账"]}),
            key=lambda kv: -kv[1])),
        # ⚠️ **把时效表也报出来,前端别手抄。**
        # `duty.html` 原来写死「财务 24h / 判责 36h / 合并 48h」——
        # 加了「评价差评 72h」之后那句话就漂了,而**漂了不报错**:
        # 页面上少一个类型,没有任何东西会红。
        时效表={**SLA_HOURS, "(其余)": DEFAULT_SLA},
        最久未处理小时=round(max([x["waited_h"] for x in todo], default=0), 1),
        # 「最久那条」超没超它**那一类自己的**时效 —— 页面按这个标红,不再用一条统一的 72 小时
        # (业务 2026-09-22 确认,附录 A-166:同一屏两张卡用两把尺子,会出现「已超时」红、「最久等待」不红)
        最久那条已超时=bool(todo) and max(todo, key=lambda x: x["waited_h"])["level"] == "已超时",
        按状态=by_state, 按类型=by_type,
        待复核=len([x for x in todo if x["state"] == "待复核"]),
        未研判=len([x for x in todo if x["state"] == "未研判"]),
    )


# ── 二、研判结果落库 ─────────────────────────────────────────────────────
SECTIONS = [("ai_root_cause", ("根因", "根本原因", "真因")),
            ("ai_action",     ("建议动作", "建议处理", "处理动作", "建议")),
            ("ai_evidence",   ("证据", "支撑证据", "依据")),
            ("_conf",         ("置信度", "信心"))]

# 段名后面允许跟的分隔符。**不允许跟正文** —— 这一条是踩出来的:
# 模型在「置信度」那段里写了一句「根因(金额超限)置信度高;……」,
# 旧规则把它当成新的「根因」标题,**把前面真正的根因段覆盖成了空**。
# 内容明明是对的,产品侧拿到的却是空字段 —— 这种失败不看解析结果根本发现不了。
_SEP = "：:／/|｜、-—– 	"
_WRAP = ("", "**", "##", "###", "-", "*", "#")


def _heading(line):
    """这一行是不是段标题?返回 (字段名, 同行正文) 或 None。"""
    for w in _WRAP:
        l = line[len(w):].lstrip() if w and line.startswith(w) else (line if not w else None)
        if l is None: continue
        l = l.rstrip("* ")
        for key, names in SECTIONS:
            for nm in names:
                if l == nm: return key, ""
                if l.startswith(nm) and l[len(nm)] in _SEP:
                    return key, l[len(nm):].lstrip(_SEP).strip(" *#")
    return None


def parse_draft(text):
    """把智能体的四段草稿切成字段。

    没有用「让模型调一个写工具交结构化结果」的做法 —— 那会给智能体开第一个写权限,
    而**工具全部只读**是这套系统最硬的一条保证,不值得为了省一段解析代码破掉。
    代价是解析会失败;解析失败不藏着,直接变成一个运维指标(见 health() 的协议失败率)。

    **先出现的段落算数**:同一个段名第二次出现时不覆盖已有内容。
    模型经常在结尾回顾时把段名再写一遍,那是复述,不是新段落。
    """
    got, cur = {}, None
    for raw in (text or "").split("\n"):
        l = raw.strip()
        h = _heading(l)
        if h:
            cur, body = h
            if got.get(cur): cur = None           # 这一段已经有内容了,后面的重复段名不算
            elif body: got[cur] = body
            else: got.setdefault(cur, "")
        elif cur and l:
            got[cur] = (got.get(cur, "") + " " + l).strip()
    return {k: got.get(k, "") for k, _ in SECTIONS}


def confidence(trajectory, parsed, need_tools=2):
    """置信度由**过程信号**推,不看模型自称,也不看答得对不对。

    上线后没有标准答案 —— 「对不对」这个信号在生产里根本拿不到。
    能拿到的只有:查了几次数据、有没有给出可核对的证据、四段是否齐全。
    模型自称的置信度不用,因为它高兴的时候什么都敢说「高」。
    """
    n = len([t for t in (trajectory or []) if t.get("tool")])
    full = all(parsed.get(k) for k in ("ai_root_cause", "ai_action", "ai_evidence"))
    if not parsed.get("ai_root_cause"):
        return "低"                                   # 连根因都没给,人必须看
    if n >= need_tools and full:
        return "高"
    if n >= 1 and parsed.get("ai_root_cause"):
        return "中"
    return "低"


# ── 研判的提示词和断点编号 —— **只有这一份** ─────────────────────────
#
# 这段原来长在 `agentsite/app.py` 的 HTTP 处理函数 `_triage_one` 里面。
# 2026-10-11 抽到这儿,因为配方要加一步「造 triage 样本」,
# 而那一步要是自己抄一份提示词,就会出现**两份提示词**:
# 页面上跑的和配方里跑的不是同一句话,而样本是按配方那句话产出的。
# > 一批「按线上提示词跑出来的」样本,和一批「按抄歪了的提示词跑出来的」,
# > **在 triage 表上长得一模一样** —— 四段齐、置信度也有,
# > 只有「它到底在替哪句话打分」这一点泄露了它。
# 这个仓库今天已经为「同一套口径手抄成两份」修了一整天。

断点 = {"财务人工任务": "BP-01", "客户合并确认": "BP-02", "售后判责": "BP-03"}
四段 = "按「根因 / 建议动作 / 证据 / 置信度」四段输出,每段单独起一行。"


# ── 差评研判:**接通,但默认不开**(用户 2026-10-13 拍「做产线那条路」)─────────────
#
# 业务 2026-10-10 拍的是「差评 AI 默认关闭,等专用取数和独立评测接通后再启用」——
# 这一步做的是**接通**,不是启用:产线入口(agentsite 的批量研判)不传 `开差评`,照旧当场说「默认关闭」;
# 只有显式传 `开差评=True` 的调用方(评测走产线路)才进这个分支。四道闸过完、用户拍了,才在产线入口打开。
#
# 和数据工厂探针的区别(**数不可比**):探针是它从库里读出材料拼进提示词;
# 这里模型要**自己调 service_records 取** —— 「取不取、取得对不对」是另一件事,所以探针那个 0% 是上限。
差评研判版本 = "差评研判 v1 · 2026-10-13 · 材料由模型调 service_records 自取"


def 差评研判提示词(ref):
    """→ (断点号, case_id, 提示词)。处理方式从 `rating.处理方式` 现拼 —— 不手抄,不写「后几种」。
    判差评的两条铁律(TK15 能看什么 / TK16 不许顺着问话改判)挂在 service_records 上,跟着工具走,这儿不抄。"""
    import rating as _R
    评 = (_rows("SELECT star, note FROM rating WHERE pkg_id=?", ref) or [None])[0]
    if not 评:
        raise ValueError(f"包裹 {ref} 没有评价 —— 判不了,不是跑挂了")
    方式 = " / ".join(_R.处理方式)
    return "BP-差评", ref, (
        f"任务类型:评价差评\n包裹号:{ref}\n评分:{评['star']} 星\n客户原话:{评['note'] or '(没写)'}\n\n"
        f"先用 service_records(pkg={ref}) 取这一单的交付签收、返修售后、这个客户历史上的差评,"
        "再判这条差评该怎么补救。\n"
        f"「建议动作」那一段**以处理方式开头**,只能从这几种里选一种:{方式}。\n"
        "你只出草稿,不对客户承诺任何金额或补救 —— 结论由店长 / 售后确认后执行。\n" + 四段)


def 研判提示词(任务类型, ref, task_id, 开差评=False):
    """返回 (断点号, case_id, 提示词)。类型没登记就**当场说清**,不套别的分支。

    ⚠️ **没有默认值。** 原来是 `断点.get(类型, "BP-02")` —— 于是「评价差评」
    (队列 266 条里 214 条,占八成)被当成客户合并,走进那条分支去
    `ref.split("|")`:差评的单据号是 `P0-H6488012800000022580-发`,
    **没有竖线,当场 ValueError**。而批量入口按条 catch 异常,
    所以它只显示成一行 failed,没人追问为什么。

    > 一个「这个类型还没接」的工单,和一个「这个类型接了但崩了」的,
    > **在那行 failed 上长得一模一样** —— 而前者该说出来,后者该修。

    立项文档里记的「差评错进客户合并分支」,产生它的就是那个默认值。
    """
    if 任务类型 == "评价差评" and 开差评:
        return 差评研判提示词(ref)
    if 任务类型 not in 断点:
        由 = ("差评的 AI 辅助**默认关闭** —— 等专用取数和独立评测接通后再启用"
             "(方案自己声明的不做项);差评由店长人工确认(业务 2026-10-10 拍)。"
             if 任务类型 == "评价差评" else
             "这个类型还没登记,按方案进「需配置/人工分流」视图,由主管明确分流 ——"
             "**不自动套用其他类型的分支**。")
        raise ValueError(f"「{任务类型}」没有 AI 研判分支,不是跑挂了。" + 由)
    bp = 断点[任务类型]
    if bp == "BP-03":
        return bp, ref, (
            f"任务类型:售后判责\n维修工单号:{ref}\n\n"
            "客户报修,需要判定责任归属并给出处理方式。"
            "先用 get_maintain 查现场,再用 kb_tables 取「售后争议判定」,"
            "对照 09-养护与售后.md 第五节的返修判定表给结论。\n"
            "两条硬规矩:①「交付告知签收」为 null 就是**没有书面告知**,"
            "特性类问题在这种情况下按「我方,让步处理」;"
            "② **你只出草稿,不对客户承诺任何金额或返修结果** —— "
            "结论必须由店长/客服确认后执行。\n" + 四段)
    if bp == "BP-01":
        return bp, ref, (
            f"任务类型:财务人工任务\n押金单号:{ref}\n\n"
            "这笔押金退款已连续失败并转入人工处理。请查清失败的根本原因,"
            "给出建议的处理动作,并列出支撑结论的证据。" + 四段)
    # BP-02 客户合并:ref 是「C21000|C21001」这样的一对
    甲, 乙 = str(ref).split("|")
    return bp, str(task_id)[1:], (
        f"任务类型:客户合并确认\n两条疑似重复的客户档案:{甲} 和 {乙}\n\n"
        "请判断是否为同一客户,给出合并或不合并的建议,并逐项列出比对依据。" + 四段)


def save_triage(task_id, breakpoint, case_id, text, trajectory,
                cost=None, latency_ms=None, model=None, usage=None,
                guard_blocked=False, guard_violations=None, answer_turns=1,
                trace_id=None, prompt_ver=None):
    """⚠️ `trace_id` 2026-09-28 补:它一直在 `sdk.run()` 的返回里,
    但到这一跳就丢了 —— 于是库里每条研判都答不出「它是哪一次调用的产物」。
    没有它,A3 的判读回流只能进总数,挂不到具体调用上。**空值合法,不许拿别的顶上。**"""
    p = parse_draft(text)
    conf = confidence(trajectory, p)
    with _c() as c:
        if prompt_ver:
            _确保回执列(c)
        cur = c.execute(
            "INSERT INTO triage(task_id,breakpoint,case_id,created,ai_root_cause,ai_action,"
            "ai_evidence,ai_confidence,ai_text,tool_calls,cost,latency_ms,model,"
            "in_tokens,out_tokens,cache_read,guard_blocked,guard_violations,answer_turns,"
            "trace_id,status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'待复核')",
            (task_id, breakpoint, case_id, now().strftime("%Y-%m-%d %H:%M:%S"),
             p["ai_root_cause"], p["ai_action"], p["ai_evidence"], conf, text,
             len(trajectory or []), cost, latency_ms, model,
             (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens"),
             (usage or {}).get("cache_read_input_tokens"),
             1 if guard_blocked else 0,
             json.dumps(guard_violations or [], ensure_ascii=False), answer_turns,
             trace_id))
        if prompt_ver:
            # **这条建议是哪版提示词、有没有取材料**(数据工厂 10-13:两轮之间动了两个变量就归因不干净,
            # 落库的这一行是事后唯一能分开它们的东西)
            c.execute("UPDATE triage SET prompt_ver=? WHERE id=?", (prompt_ver, cur.lastrowid))
        c.execute("UPDATE task SET status='待复核', summary=? WHERE id=?",
                  (p["ai_root_cause"][:60] or "(未解析出根因)", task_id))
        return cur.lastrowid


def reparse(only_failed=True):
    """解析器改好之后,把历史研判重新解析一遍 —— **不用重新调模型**。

    这就是把 ai_text 全文存下来的理由。展示件不存,因为跑完就不看了;
    平台必须存:解析规则、置信度规则以后一定会改,改完要能对历史重算,
    否则「协议失败率」这个指标在改规则那天会断档,前后不可比。
    只改解析出来的字段,**不动人工裁决**。
    """
    fixed = []
    with _c() as c:
        rows = c.execute("SELECT id,ai_text,ai_root_cause,tool_calls FROM triage").fetchall()
        for r in rows:
            if only_failed and r["ai_root_cause"]: continue
            p = parse_draft(r["ai_text"] or "")
            if p["ai_root_cause"] == (r["ai_root_cause"] or ""): continue
            conf = confidence([{"tool": 1}] * (r["tool_calls"] or 0), p)
            c.execute("UPDATE triage SET ai_root_cause=?,ai_action=?,ai_evidence=?,"
                      "ai_confidence=? WHERE id=?",
                      (p["ai_root_cause"], p["ai_action"], p["ai_evidence"], conf, r["id"]))
            fixed.append(dict(id=r["id"], root_cause=p["ai_root_cause"][:50], confidence=conf))
    for f in fixed:
        with _c() as c:
            c.execute("UPDATE task SET summary=? WHERE id=(SELECT task_id FROM triage WHERE id=?)",
                      (f["root_cause"][:60], f["id"]))
    return fixed


def get_triage(triage_id):
    r = _rows("SELECT * FROM triage WHERE id=?", triage_id)
    return r[0] if r else None


# ── 三、销账与回流 ───────────────────────────────────────────────────────
# ── 谁能销哪一类(业务 2026-10-10 晚 / 10-11 拍,原文在 intent/triage-queue.md)──────────
# ⚠️ 2026-10-12 之前**谁都能销账**:`/api/ops-resolve` 不查登录、`handler` 读请求体(默认「值班同学」),
# 而 `resolve` 不写 op_log —— 谁都能销、署名随便填、销完查不出是谁。用户拍「修,排在页面两步之前」。
# 门分两层:**会话 → 身份**在接口那层(造数脚本没有会话);**身份 → 能不能销**在这里(所有调用方都过)。
# ── 两段确认(业务 10-11「钱要出门就要两个人」;**顺序** 用户 2026-10-13 拍「复核 = 第一段、办结 = 第二段」)──
# 原来这张表是「店长或财务都能销」—— 两个角色谁都能一个人从头点到尾,「两个人」只写在规矩里。
# 现在借「已办结」(10-13 同日做的)把两段分开:**复核**(已采纳 / 已改判 / 已升级)只认第一段的角色,
# **办结**(凭回执)只认第二段的角色 —— 两段角色不同,所以退款必然经两个人的手。
# 代价用户拍板时知道:店里只有一个人在时,退款办不完,要等另一个人。
两段 = {
    "财务人工任务": {"复核": ("店长",), "办结": ("财务",)},        # 店长定该不该退 → 财务执行退款
    "客户合并确认": {"复核": ("店长",), "办结": ("总部运营",)},    # 店长认人 → 总部运营执行合并(执行合并还没做)
}
# 一段就完的类型:复核和办结是同一拨人
可销账角色 = {
    "售后判责":     ("售后",),              # 10-11:新建「售后」角色负责确认
}
# ⚠️「已升级」算复核那一段(第一段的人决定往上交)—— **开发按同一张表推的,业务没拍过**。


def 能销吗(task_type, role, 段="复核"):
    """→ (能不能, 为什么)。段:复核 / 办结。
    评价差评跟「关差评」用同一份名单(rating_write.能关差评的角色),不另抄;两段都是这拨人。"""
    if 段 not in ("复核", "办结"):
        return False, f"段只有 复核 / 办结,给的是「{段}」"
    if task_type == "评价差评":
        import rating_write as _rw
        许 = tuple(_rw.能关差评的角色)
    elif task_type in 两段:
        许 = 两段[task_type][段]
    else:
        许 = 可销账角色.get(task_type)
    if not 许:
        return False, f"「{task_type}」没登记谁能销账 —— 不猜,先去 ops.两段 / ops.可销账角色 登记"
    if role not in 许:
        头 = f"「{task_type}」是两段确认,{段}这一段" if task_type in 两段 else f"「{task_type}」"
        return False, f"{头}只能由 {' / '.join(许)} 做,你是「{role or '(没有角色)'}」"
    return True, ""


# ── 已办结:凭业务回执(用户 2026-10-13 拍「按类型各认一种系统单号」,对照表同日核过)──────────
#
# 复核结论(已采纳 / 已改判)说的是「AI 判得对不对、该怎么办」;**办没办完是另一件事**。
# 只认员工点一下的话,「已办结」和「已采纳」没区别 —— 嘴上说办了,查不到证据。
# 所以回执必须是**系统里查得到、而且状态真走完了**的那张单,不收照片、不收顾客口头确认
# (照片系统判不了拍的是什么;顾客不回就永远办不结 —— 用户当天在三案里选的)。
回执对照 = {
    "财务人工任务": "定金单",     # 工单挂的那笔定金,状态「已退」
    "售后判责":     "维保单",     # 工单挂的那张维保单,状态「已完成」
    "评价差评":     "按处理方式",  # 见下一张表
    "客户合并确认": None,         # ⚠️ 系统里**没有「执行合并」这个动作** —— 判了该合并也没地方真去合。
                                  # 用户 10-13 拍「先空着」,执行合并另行排期
}
# 差评按**当初登记的处理方式**认单。⚠️ 这张表必须盖住 `rating.处理方式` 的每一项 ——
# 枚举里新加一档而这里没登记,`回执对照没漏()` 会报出来:**新档该认什么单是要人定的,不许默认**。
差评回执 = {
    "部分退款": "售后单", "全额退款": "售后单",   # 售后退款单(仅退款 / 退货退款),已完成
    "送保养":   "维保单", "免次改衣": "维保单",   # 「免次改衣也认维保单」开发推的,用户 10-13 核过表
    "免运费":   None,     "只回访":   None,       # 没有对应单据 → 停在已采纳(用户拍板时接受的代价)
}


def 回执对照没漏():
    """→ 枚举里有、对照表里没登记的处理方式(应为空)。"""
    import rating as _R
    return [x for x in _R.处理方式 if x not in 差评回执]


def _确保回执列(c):
    有 = {r[1] for r in c.execute("PRAGMA table_info(triage)")}
    for col in ("receipt", "receipt_kind", "prompt_ver"):
        if col not in 有:
            c.execute(f"ALTER TABLE triage ADD COLUMN {col} TEXT")


def 回执行不行(c, 任务, 单号):
    """→ (行不行, 回执类型, 为什么)。只读。单号要**属于这件事**,而且那张单**真的走完了**。"""
    类型, ref = 任务["type"], 任务["ref_id"]
    单号 = (单号 or "").strip()
    if 类型 not in 回执对照:
        return False, None, f"「{类型}」没登记认什么回执 —— 不猜,先去 ops.回执对照 登记"
    要 = 回执对照[类型]
    if 要 is None:
        return False, None, f"「{类型}」现在进不了已办结:系统里还没有能证明它办完的单据(执行合并还没做)"
    if not 单号:
        return False, 要, "没给回执单号"
    if 要 == "定金单":
        if 单号 != ref:
            return False, 要, f"这件事挂的是定金 {ref},回执给的是 {单号}"
        r = c.execute("SELECT status FROM deposit WHERE id=?", (单号,)).fetchone()
        if not r: return False, 要, f"没有定金单 {单号}"
        return (r[0] == "已退", 要, "" if r[0] == "已退" else f"定金 {单号} 现在是「{r[0]}」,还没退成")
    if 要 == "维保单" and 类型 == "售后判责":
        if 单号 != ref:
            return False, 要, f"这件事挂的是维保单 {ref},回执给的是 {单号}"
        r = c.execute("SELECT status FROM maintain WHERE id=?", (单号,)).fetchone()
        if not r: return False, 要, f"没有维保单 {单号}"
        return (r[0] == "已完成", 要, "" if r[0] == "已完成" else f"维保单 {单号} 现在是「{r[0]}」,还没完成")
    # 评价差评:ref 是包裹号;按当初登记的处理方式认单,而且那张单必须是**同一张订单**的
    评 = c.execute("SELECT order_id, handle_way FROM rating WHERE pkg_id=?", (ref,)).fetchone()
    if not 评: return False, None, f"包裹 {ref} 没有评价"
    方式 = 评[1]
    if not 方式:
        return False, None, "这条差评还没登记处理方式 —— 先关差评、写清怎么处理的"
    if 方式 not in 差评回执:
        return False, None, f"处理方式「{方式}」没登记认什么回执 —— 不猜"
    要 = 差评回执[方式]
    if 要 is None:
        return False, None, f"处理方式是「{方式}」,没有对应单据 —— 停在已采纳"
    if 要 == "售后单":
        r = c.execute("SELECT order_id, kind, status FROM aftersale WHERE id=?", (单号,)).fetchone()
        if not r: return False, 要, f"没有售后单 {单号}"
        if r[1] not in ("仅退款", "退货退款"):
            return False, 要, f"售后单 {单号} 是「{r[1]}」,不是退款单"
    else:
        r = c.execute("SELECT order_id, '维保', status FROM maintain WHERE id=?", (单号,)).fetchone()
        if not r: return False, 要, f"没有维保单 {单号}"
    if str(r[0]) != str(评[0]):
        return False, 要, f"{要} {单号} 是订单 {r[0]} 的,这条差评是订单 {评[0]} 的"
    return (r[2] == "已完成", 要, "" if r[2] == "已完成" else f"{要} {单号} 现在是「{r[2]}」,还没完成")


def 办结(triage_id, 单号, me, 来源="页面"):
    """已采纳 / 已改判的研判,凭回执单号标成已办结。**不改复核结论**,只记回执。

    角色按**办结那一段**查(`能销吗(…, 段="办结")`:退款只认财务、合并只认总部运营);成功 / 被拒都写 op_log。
    已升级的不在这一层办(交上去了);待复核的先复核。"""
    from oplog import log_op as _log
    me = me or {}
    谁 = f"{me.get('name') or '?'}({me.get('no') or '?'})"
    def _记(ok, code, 话):
        _log(谁, "triage", f"triage#{triage_id}", "—", "已办结" if ok else "—", ok, code,
             f"[{来源}] {话}"[:200], {"role": me.get("role"), "no": me.get("no")})
    if not (me.get("no") and me.get("role")):
        _记(False, "NO_IDENTITY", "没有办结人身份(工号 + 角色)")
        raise PermissionError("没有办结人身份 —— 要登录")
    t = get_triage(triage_id)
    if not t:
        _记(False, "NO_TRIAGE", "没有这条研判")
        raise ValueError(f"没有 triage#{triage_id}")
    任务 = (_rows("SELECT type, ref_id FROM task WHERE id=?", t["task_id"]) or [None])[0]
    ok, 为什么 = 能销吗(任务["type"] if 任务 else None, me.get("role"), 段="办结")
    if not ok:
        _记(False, "ROLE", 为什么)
        raise PermissionError(为什么)
    if t["status"] not in ("已采纳", "已改判"):
        话 = f"这条研判是「{t['status']}」—— 只有已采纳 / 已改判的才能办结" + \
             ("(先复核)" if t["status"] == "待复核" else "")
        _记(False, "BAD_STATE", 话)
        return dict(ok=False, code="BAD_STATE", reason=话)
    if t.get("receipt"):
        话 = f"已经办结过了(回执 {t.get('receipt_kind')} {t['receipt']})"
        _记(False, "ALREADY", 话)
        return dict(ok=False, code="ALREADY", reason=话)
    with _c() as c:
        _确保回执列(c)      # 老库没有这两列(新建的库 seed 里就有);补列不改任何已有数据
        行, 类, 话 = 回执行不行(c, 任务, 单号)
        if not 行:
            _记(False, "NO_RECEIPT", 话)
            return dict(ok=False, code="NO_RECEIPT", reason=话, 回执类型=类)
        c.execute("UPDATE triage SET receipt=?, receipt_kind=? WHERE id=?", (单号.strip(), 类, triage_id))
    _记(True, "CLOSE", f"凭{类} {单号.strip()} 办结")
    return dict(ok=True, code="CLOSE", 回执类型=类, 回执=单号.strip(),
                reason=f"已办结:凭{类} {单号.strip()}。复核结论仍是「{t['status']}」")


def resolve(triage_id, decision, me, root_cause=None, action=None, note=None, 来源="页面"):
    """值班同学销账。**改判会回流成新的标注** —— 这是平台能越用越准的唯一通路。

    me = 销账的人 {no, name, role}(**调用方给,不在这里读会话**:接口层从登录态取,造数脚本传一个真员工)。
    角色不对 → 抛 PermissionError;成功 / 被拒 / 出错**都写 op_log**(machine='triage')。

    回流写的是 truth 表,标 src='人工改判'。为什么要分开标:
    回流条目只经过一个人的判断、没有第二个人复核过,
    如果和建库标注混在一起,一次判错的裁决会悄悄变成"标准答案",而且再也查不出来。
    """
    from oplog import log_op as _log
    me = me or {}
    谁 = f"{me.get('name') or '?'}({me.get('no') or '?'})"
    # reason 里**不带日期** —— op_log.ts 自己记时间;文本里一带日期就要去 shift_world 登记,否则每日平移拒跑
    def _记(ok, code, 话):
        _log(谁, "triage", f"triage#{triage_id}", "待复核", decision if ok else "—", ok, code,
             f"[{来源}] {话}"[:200], {"role": me.get("role"), "no": me.get("no")})
    if not (me.get("no") and me.get("role")):
        _记(False, "NO_IDENTITY", "没有销账人身份(工号 + 角色)")
        raise PermissionError("没有销账人身份 —— 要登录;造数脚本要传一个真员工")
    if decision not in DECISIONS:
        _记(False, "BAD_DECISION", f"decision={decision}")
        raise ValueError(f"decision 只能是 {DECISIONS},收到 {decision}")
    t = get_triage(triage_id)
    if not t:
        _记(False, "NO_TRIAGE", "没有这条研判")
        raise ValueError(f"没有 triage#{triage_id}")
    _任务 = _rows("SELECT type FROM task WHERE id=?", t["task_id"])
    ok, 为什么 = 能销吗(_任务[0]["type"] if _任务 else None, me.get("role"), 段="复核")
    if not ok:
        _记(False, "ROLE", 为什么)
        raise PermissionError(为什么)
    handler = 谁
    ts = now().strftime("%Y-%m-%d %H:%M:%S")
    flowed, conflict = False, None
    with _c() as c:
        c.execute("UPDATE triage SET status=?,human_root_cause=?,human_action=?,"
                  "human_note=?,handler=?,handled_at=? WHERE id=?",
                  (decision, root_cause, action, note, handler, ts, triage_id))
        c.execute("UPDATE task SET status=? WHERE id=?",
                  ("已升级" if decision == "已升级" else "已处理", t["task_id"]))
        if decision == "已改判" and t["case_id"] and root_cause:
            old = c.execute("SELECT root_cause,src FROM truth WHERE case_id=?",
                            (t["case_id"],)).fetchone()
            if old and old["src"] == "建库标注" and old["root_cause"] != root_cause:
                # **不覆盖**。上线前的标注是复核过的,值班同学的裁决只经一个人。
                # 谁对谁错这里定不了 —— 定不了的事就别偷偷替对方做决定,记下来给人裁。
                # 和相容矩阵里「人工确认 vs 规则不一致就列出来」是同一条处理原则。
                conflict = dict(case_id=t["case_id"], 建库标注=old["root_cause"], 人工改判=root_cause)
            elif old and old["root_cause"] == root_cause:
                flowed = True          # 和已有标注一致,不用重复写
            else:
                c.execute("INSERT OR REPLACE INTO truth(case_id,breakpoint,root_cause,"
                          "expected_action,expected_evidence,note,src) VALUES(?,?,?,?,?,?,'人工改判')",
                          (t["case_id"], t["breakpoint"], root_cause, action or "",
                           note or "", f"{handler} 于 {ts} 改判回流"))
                flowed = True
            if flowed: c.execute("UPDATE triage SET into_eval=1 WHERE id=?", (triage_id,))
    # ── A3:把这条判读投给管理后台(投本地箱,不在这里发 HTTP)────────────
    # ⚠️ 和 A1 同一条规矩(A2):**绝不能把销账这件事搞挂**。
    # 销账是业务动作,上报是附加的 —— 所以库先写完(上面那个 with 已经出块提交),
    # 再投递,而且整段包在 try 里,`排队()` 自己内部也不抛。
    #
    # 为什么在这里而不在页面那一头:**这里是唯一一处真正改状态的地方**。
    # 挂在按钮上的话,以后多一个入口(批量销账、脚本改判)就漏一条,
    # 而漏了不会报错 —— 只会让采纳率静静地偏低。
    try:
        import sys as _s, os as _os
        _s.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "agent"))
        if os.path.realpath(DB) != os.path.realpath(_本库):
            raise RuntimeError("副本上的销账不上报")    # 落到下面的 except:不上报、不影响销账
        import feedback_report as _fb, worldclock as _wc1
        # ⚠️ **`外部trace` 传的必须是 sdk 那个 trace id,不是 `triage#N`。**
        # 两个字段的定义不一样:`trace_id` 是**接收端**在 A1 上报时返回的号,
        # `外部trace` 是**我们这边**的号。而 A1 上报时传的 `外部trace` 正是 sdk trace id ——
        # 两边要 join 得上,A3 就必须传**同一个值**。
        # 传 `triage#N` 的话格式完全合法、接收端也收得下,但它在那边**匹配不到任何东西**,
        # 于是这条判读看起来挂上了、实际只进了总数。**「挂错了」比「没挂」更难发现。**
        # `trace_id` 这里给不了:那是接收端 201 返回里的号,销账这一刻我们手上没有。
        # ⚠️ **不传 root_cause / action / note —— 一个字都不传。**
        # 判「已改判」时 `root_cause` 正是上面写进 `truth` 的那个值,而 `truth` 是评测答案。
        # 顺着上报流出去 = 评测集泄露,而**评测集一旦泄露就不能再当评测集**。
        # 所以只传结构化的事实:谁、什么判读、智能体说没说话、回流了没有。
        # (发送端那边还有一道形状闸:附带值只收 bool/int/None/短 ASCII。**两道都要**,
        #  因为这一处是「不传」,那一处是「传了也进不去」——
        #  只有一道的话,下一个在这里加字段的人不会知道有这条规矩。)
        _fb.排队(trace_id=None, 外部trace=t.get("trace_id"),
                判读=decision,
                # 智能体这一次到底说没说话。**显式给,不让它默认** ——
                # 连根因都没给的那种(confidence 判「低」那条路),人处置了也不算改判。
                有结论=bool((t.get("ai_root_cause") or "").strip()),
                附带={"triage": str(triage_id)[:24],   # 短 ASCII,过得了形状闸
                     "回流了": bool(flowed),
                     "与建库标注冲突": bool(conflict),
                     "置信度": {"高": 3, "中": 2, "低": 1}.get(t.get("ai_confidence"), 0)},
                世界日期=str(_wc1.今天()))
    except Exception:
        pass                       # 上报出任何事都不许影响销账
    _记(True, "RESOLVE", f"{decision} · 工单 {t['task_id']}" + (" · 回流评测集" if flowed else "")
        + (" · 与建库标注冲突" if conflict else "") + (f" · {note[:40]}" if note else ""))
    return dict(triage_id=triage_id, decision=decision, 回流评测集=flowed, 与建库标注冲突=conflict)


# ── 五、生命周期提醒 ────────────────────────────────────────────────────
# **这一节刻意不进研判队列。**
#
# 研判队列是给「智能体先出草稿、人来采纳或改判」的事准备的 ——
# 前提是那件事**步骤枚举不完**,需要模型去查、去推。
#
# 「谁该复量了」不是这种事:年龄查表 → 周期查表 → 日期相减,三步走完。
# 这种事丢给模型,是花钱买不确定性 —— 这正是三代对比里 V2 打赢 V3 的那类任务。
#
# 所以它是一张**规则生成的提醒清单**,不是一条研判工单。
# 判断标准就一句:**步骤能不能提前枚举。能,就别用智能体。**
def recheck_list():
    """该复量的人。规则直出,0 次模型调用。"""
    import lifecycle_check as lc
    _, sig, conf = lc.run(verbose=False)
    return {"该复量": sorted(sig, key=lambda x: -(x["已过"] - x["上限"])),
            "需人工确认": conf,
            "说明": "规则直出,不经模型 —— 步骤能枚举的事不该花钱买不确定性"}


def order_block(wearer_id, today=None):
    """下单前的尺码失效拦截。**超期的量体记录不是参考值,是无效值。**"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__))), "knowledge"))
    import growth
    from datetime import date
    import worldclock as _wc
    today = today or _wc.今天()  # 世界的今天(world_meta),不写死 —— 2026-10-01 写死的 08-31 让量体过期判反了
    w = _rows("SELECT * FROM wearer WHERE id=?", wearer_id)
    if not w: return {"放行": False, "原因": f"着装人 {wearer_id} 不存在"}
    w = w[0]
    h = _rows("""SELECT value,measured_at FROM measure_rec WHERE wearer_id=? AND item='MI01'
                 ORDER BY measured_at DESC LIMIT 1""", wearer_id)
    if not h: return {"放行": False, "原因": "没量过身高,先约量体"}
    e = growth.measure_expired(w["gender"], w["birthday"], h[0]["measured_at"][:10], today)
    if e["过期"]:
        return {"放行": False, "着装人": w["name"], "原因": f"量体记录已过 {e['已过天数']} 天,"
                f"上限 {e['允许天数']} 天({e['原因']})", "处置": "拦下,要求复量"}
    return {"放行": True, "着装人": w["name"], "量体日": h[0]["measured_at"][:10]}


# ── 四、健康度 ──────────────────────────────────────────────────────────
def health():
    """智能体自己的运维指标。

    生产里衡量质量的不是「判对了几道」(没有标准答案),是 **人采纳了几条**。
    采纳率掉下来,不用等谁投诉,队列自己就会告诉你。
    """
    tr = _rows("SELECT * FROM triage")
    done = [t for t in tr if t["status"] in DECISIONS]
    adopted = [t for t in done if t["status"] == "已采纳"]
    costs = [t["cost"] for t in tr if t["cost"] is not None]
    lats = [t["latency_ms"] for t in tr if t["latency_ms"]]
    unparsed = [t for t in tr if not t["ai_root_cause"]]
    conf = {}
    for t in tr: conf[t["ai_confidence"]] = conf.get(t["ai_confidence"], 0) + 1
    # 高置信度里被人改判的 —— 最该盯的一个数:它说明置信度本身在骗人
    hi_wrong = [t for t in done if t["ai_confidence"] == "高" and t["status"] == "已改判"]
    ev = _rows("SELECT src,COUNT(*) n FROM truth GROUP BY src")
    # 值班裁决和上线前标注对不上的 case —— 这个数不该是 0,也不该一直涨。
    # 一直是 0 说明没人真在复核;一直涨说明标注或者业务规则该修了。
    clash = _rows("SELECT COUNT(*) n FROM triage t JOIN truth u ON u.case_id=t.case_id"
                  " WHERE t.status='已改判' AND u.src='建库标注'"
                  " AND t.human_root_cause IS NOT NULL AND t.human_root_cause<>u.root_cause")[0]["n"]
    return dict(
        研判总数=len(tr), 已销账=len(done),
        采纳率=f"{len(adopted)/len(done)*100:.0f}%" if done else "—",
        改判率=f"{len([t for t in done if t['status']=='已改判'])/len(done)*100:.0f}%" if done else "—",
        升级率=f"{len([t for t in done if t['status']=='已升级'])/len(done)*100:.0f}%" if done else "—",
        协议失败率=f"{len(unparsed)/len(tr)*100:.0f}%" if tr else "—",
        协议失败数=len(unparsed),
        高置信度被改判=len(hi_wrong),
        累计成本=round(sum(costs), 4) if costs else 0.0,
        单条均价=round(sum(costs)/len(costs), 4) if costs else None,
        中位耗时秒=round(sorted(lats)[len(lats)//2]/1000, 1) if lats else None,
        置信度分布=conf,
        体检打回率=(f"{sum(1 for t in tr if t['guard_blocked'])/len(tr)*100:.0f}%" if tr else "—"),
        体检打回数=sum(1 for t in tr if t["guard_blocked"]),
        缓存命中率=(f"{sum(t['cache_read'] or 0 for t in tr)/max(sum(t['in_tokens'] or 0 for t in tr),1)*100:.0f}%"
                if any(t["in_tokens"] for t in tr) else "—"),
        评测集来源={r["src"]: r["n"] for r in ev}, 与建库标注冲突=clash,
    )


if __name__ == "__main__":
    print("智能运维平台 · 数据层自测\n" + "=" * 70)
    b = backlog()
    print(f"积压 {b['待办']}/{b['总量']}  超时 {b['已超时']}  临期 {b['临期']}  "
          f"最久 {b['最久未处理小时']}h")
    print("  按类型:", b["按类型"])
    q = queue("待办")
    print(f"\n队列前 5(超时优先):")
    for x in q[:5]:
        print(f"  [{x['level']:4s}] {x['task_id']:8s} {x['type']:8s} "
              f"等了 {x['waited_h']:7.1f}h / SLA {x['sla_h']}h  状态 {x['state']}")
    print("\n四段解析自测:")
    demo = ("根因：渠道超时但实际已退款\n"
            "建议动作：不得重新发起退款，先向渠道核对流水 CH20260814001\n"
            "证据：refund_trace 显示第 3 次重试返回 TIMEOUT，payment_flow 有 direction=out 成功记录\n"
            "置信度：高")
    p = parse_draft(demo)
    for k, v in p.items(): print(f"  {k:15s} {v[:52]}")
    assert p["ai_root_cause"].startswith("渠道超时"), "根因没解析出来"
    assert "不得重新发起" in p["ai_action"], "动作没解析出来"
    assert confidence([{"tool": "a"}, {"tool": "b"}], p) == "高"
    assert confidence([], p) == "低", "一次数据都没查就下结论,不该给高/中"
    assert confidence([{"tool": "a"}], parse_draft("我觉得应该是超时")) == "低", "没有根因该判低"

    # 两条**线上真实踩过的**格式,加进自测防回归:
    # ① 段名独占一行、正文在下一行,而且结尾又提了一次段名(旧规则会把前面覆盖成空)
    a = parse_draft("根因\n金额写错为 2250 元,超过原收款\n\n建议动作\n按 1500 元重发\n\n"
                    "证据\nreq_amount 均为 2250\n\n置信度\n根因(金额超限)置信度高;来源待核")
    assert a["ai_root_cause"].startswith("金额写错"), f"结尾复述段名把正文覆盖了:{a['ai_root_cause']!r}"
    assert a["ai_action"].startswith("按 1500"), a["ai_action"]
    # ② 段名和正文同一行,用「 / 」分隔
    b = parse_draft("根因 / 三次重试用了三个不同幂等号\n\n建议动作 / 先查渠道单\n\n证据 / 无 out 流水")
    assert b["ai_root_cause"].startswith("三次重试"), b["ai_root_cause"]
    assert b["ai_evidence"].startswith("无 out"), b["ai_evidence"]
    print("  ✅ 两条线上真实格式(段名独占行+结尾复述 / 段名与正文同行)都能解析")
    print("\n健康度:", json.dumps(health(), ensure_ascii=False))
    print("\n生命周期提醒(规则直出,0 次模型调用):")
    rl = recheck_list()
    for x in rl["该复量"][:5]:
        print(f"  · {x['着装人']}({x['年龄']}岁) 超期 {x['已过'] - x['上限']:>3} 天 —— {x['原因']}")
    print(f"  需人工确认(遗传身高与推算冲突){len(rl['需人工确认'])} 人")
    assert rl["该复量"], "一条该复量的都没有 —— 提醒清单是死的?"
    # 拦截:同一个人,过期的拦下、没过期的放行
    blocked = [ (x["id"]) for x in rl["该复量"] ][0]
    b = order_block(blocked)
    assert not b["放行"] and "复量" in b["处置"], f"过期的没拦住:{b}"
    ok = _rows("""SELECT w.id FROM wearer w JOIN measure_rec m ON m.wearer_id=w.id
                  WHERE w.relation='本人' AND m.item='MI01'
                  AND w.id NOT IN ({})  LIMIT 1""".format(
                  ",".join("'%s'" % x["id"] for x in rl["该复量"])))
    if ok:
        p2 = order_block(ok[0]["id"])
        assert p2["放行"], f"没过期的被误拦:{p2}"
        print(f"  ✅ 拦截咬合:过期的拦下({b['着装人']})、没过期的放行({p2['着装人']})")

    # ── 新 type 必须有时效声明,而且要说清进不进考核 ────────────────────
    #
    # ⚠️ 2026-09-27 并行会话往共用的 `task` 表加了一个新 type「评价差评」。
    # 它**没崩** —— `SLA_HOURS.get(type, DEFAULT_SLA)` 兜住了,
    # 于是 204 条历史差评工单**按默认 48 小时计时效**,其中 201 条立刻超时,
    # 把超时率从 20% 改成 99%。而**没有任何东西报错**。
    #
    # > **一张共用的清单,加一个新 type,会打到所有「全表扫 + 按 type 分流」的消费者。**
    # > 而 `.get(x, 默认值)` 正是让这件事**不报错**的那个东西。
    #
    # 所以这里反过来判:**库里出现的每个 type 都要在 SLA_HOURS 里显式写着。**
    # 想用默认值也得写进来(写一个 48 和不写,在代码上的差别正是「有人想过」)。
    出现的 = {r["type"] for r in _rows("SELECT DISTINCT type FROM task")}
    没声明, 空转的, 多声明的 = 时效声明齐吗(出现的)
    assert not 没声明, (
        f"这些 task type 没有时效声明:{没声明} —— "
        f"`SLA_HOURS.get(…, DEFAULT_SLA)` 会**静默**给它们套 {DEFAULT_SLA} 小时,"
        f"而一批历史数据会因此整批超时(2026-09-27 实际发生过:201 条)。\n"
        f"       要加就在 `SLA_HOURS` 里写明几小时,并想一下它该不该进"
        f"`不进考核的类型`(超时率是考核数)")
    # 反过来也查:声明了但库里没有的,说明清单里囤了死条目
    if 多声明的:
        print(f"  ℹ️ 时效表里有 {len(多声明的)} 个库里还没出现的 type:{多声明的}"
              f" —— 不算错(可能是先声明后铺数据),但囤久了就是死条目")
    # `不进考核的类型` 里的必须是真实存在的 type,否则那条排除是空转
    assert not 空转的, (
        f"`不进考核的类型` 里 {空转的} 在库里不存在 —— "
        f"**一条排除不掉任何东西的排除规则**,而它看起来在生效")
    b2 = backlog()
    assert b2["已超时_含不考核"] >= b2["已超时"], "含不考核的超时数不该比考核口径小"
    if 不进考核的类型 & 出现的:
        assert b2["已超时_含不考核"] > b2["已超时"] or b2["已超时_含不考核"] == 0, (
            "有不进考核的类型在库里,但两个口径的超时数一样 —— "
            "要么那些单子一条都没超时(可能),要么排除没生效(要查)")
    print(f"\n  ✅ {len(出现的)} 个 task type 都有时效声明;"
          f"超时 {b2['已超时']}(考核口径)/ {b2['已超时_含不考核']}(全部),"
          f"差 {b2['已超时_含不考核'] - b2['已超时']} 件不计考核")
    print(f"     时效表:{b2['时效表']}")
    # 咬合 —— **纯函数,所以不碰库、不改文件、没有「恢复」这回事**。
    # (并行会话在同一个仓库上干活;原地改坏再改回来,中间那一瞬别人可能正好读到。
    #  而「恢复失败」和「恢复成功」在输出上一模一样,要到下一次跑才看得出来。)
    咬 = []
    没_, _, _ = 时效声明齐吗(出现的 | {"凭空多出来的新type"})
    咬.append(("多一个没声明的 type → 抓到", 没_ == ["凭空多出来的新type"]))
    _, 空_, _ = 时效声明齐吗(出现的, 不考核的={"库里没有这个"})
    咬.append(("排除规则指向不存在的 type → 抓到(那条排除是空转)", 空_ == ["库里没有这个"]))
    _, _, 死_ = 时效声明齐吗(出现的, 声明的=set(SLA_HOURS) | {"声明了但没用的"})
    咬.append(("声明了库里没有的 → 报成死条目(不算错)", 死_ == ["声明了但没用的"]))
    没2, _, _ = 时效声明齐吗(出现的)
    咬.append(("对照:现状不报(否则上面三条可能只是恒为真)", 没2 == []))
    for 名, 真 in 咬:
        print(f"     {'✅' if 真 else '❌'} 咬合:{名}")
    assert all(真 for _, 真 in 咬), "时效声明判据的咬合没过 —— **没红过的检查等于没有**"

    # ── done 判据的两个来源 —— **其中一个目前是空的,所以它需要断言** ────────
    #
    # 业务 2026-09-28 拍板:`done = triage 有结论 或 task.status='已关闭'`。
    #
    # ⚠️ 实测:201 条销账**全部**来自「工单已关闭」,`triage 有结论` 命中 0 条。
    # 也就是说这条判据现在完全靠 `task.status`。这不是错 ——
    # 但它意味着:**只写 `task.status` 那一半,现在看起来完全一样**。
    # 而一个「目前用不上的分支」正是以后悄悄失效也没人发现的那种。
    #
    # 所以这里判的不是「两个来源都有命中」(那会逼数据造假),
    # 而是**两个来源都还连着**:各自单独算一遍,和合起来的对得上。
    q = queue()
    只看研判 = [x for x in q if x["研判有结论"]]
    只看关闭 = [x for x in q if x["工单已关闭"]]
    合起来 = [x for x in q if x["done"]]
    assert len(合起来) == len({x["task_id"] for x in 只看研判 + 只看关闭}), (
        f"done 的两个来源合起来对不上:研判 {len(只看研判)} + 关闭 {len(只看关闭)} "
        f"≠ 并集 {len(合起来)} —— **说明 done 的算法和这两个字段脱钩了**")
    assert all(x["凭什么销账"] for x in 合起来), (
        "有销账的条目没写「凭什么销账」—— "
        "**一个不说依据的结论,事后分不清「研判过」和「直接关单」**")
    assert all(x["凭什么销账"] is None for x in q if not x["done"]), (
        "没销账的条目却写了销账依据")
    b3 = backlog()
    assert sum(b3["销账依据"].values()) == len(合起来), (
        f"销账依据的分布加起来 {sum(b3['销账依据'].values())} "
        f"≠ 销账数 {len(合起来)} —— 分布漏了一档")
    assert sum(b3["已超时_按类型"].values()) == b3["已超时_含不考核"], (
        f"超时按类型加起来 {sum(b3['已超时_按类型'].values())} "
        f"≠ 已超时_含不考核 {b3['已超时_含不考核']} —— 分布漏了一类")
    没走研判就关的 = sum(v for k, v in b3["销账依据"].items() if "没走过研判" in k)
    print(f"\n  ✅ done 判据两个来源都连着:研判有结论 {len(只看研判)}、"
          f"工单已关闭 {len(只看关闭)}、销账合计 {len(合起来)}")
    if 没走研判就关的:
        print(f"     ℹ️ 其中 {没走研判就关的} 条是「**没走过研判就关掉**」—— "
              f"不算错(有些事不需要研判),但这个数要有人看一眼")
    if not 只看研判:
        print(f"     ⚠️ `triage 有结论` 这一半**目前命中 0 条** —— "
              f"判据完全靠 task.status。它没坏,但**只写一半现在看起来一样**,"
              f"所以上面那条断言守的是「两个来源都还连着」")
    print(f"     超时分布:{b3['已超时_按类型']}")

    print("\n✅ 数据层自测通过")
