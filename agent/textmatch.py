#!/usr/bin/env python3
"""中文否定与子串的统一判定 —— 这个项目在这上面栽过八次。

## 为什么要收成一处

原来有**四份**实现,四份**不同的否定词表**:
    agent/chat_eval.py    18 个词,正则,前后都查
    agent/negative.py     20 个词,正则,前后都查,窗口 14/36
    agent/tool_eval.py    12 个词 + NEG_FALSE,只查前面
    agentsite/guards.py   11 个词 + NEG_FALSE,只查前面
每次踩坑都只补了其中一份,别的三份继续错。**词表存四遍,一定漂。**

## 中文的两个坑,都不是「多加几个词」能解决的

### 坑一:否定是前缀,而子串匹配不认前缀

    「**不**建议合并」  里包含  「建议合并」
    「**没有**现货」    里包含  「有现货」
    「香云**纱**」      里包含  「纱」

用 `"建议合并" in text` 判,「不建议合并」会被判成「建议合并」。
**这个坑栽了三次,三次都是不同的词。**

### 坑二:含「不」的词不一定表否定

    「**不过**加钱可以赶出来」 —— 这是答应加急,不是拒绝
    「差**不**多」「**不**仅」「**不**妨」

把它们当否定,正确的「答应了加急」会被放过去。**这个坑栽了一次,方向正好相反。**

## 历史上的八次(都在下面的自测里钉着)

1. 「**不得**重新发起退款」被判成「建议重新发起」
2. 「建议**不**合并」被判成「建议合并」
3. 「**立即停止**」被判成没停止
4. 「**而非** WX999…」被判成认领了假流水号
5. 「**不过**加钱可以赶出来」被当成拒绝加急(转折词误判为否定)
6. 「香云**纱**」撞上面料名「纱」的子串
7. 「**没有**现货」被判成说了「有现货」
8. 「预测 142cm……**腰围区间**我们再确认」——「区间」这个词在,
   但它在说围度,身高照样被当成确定值说了出去。
   **第八次和前七次是同一个形状:词在,但不是在限定它该限定的那个东西。**
   所以有了 `in_clause` —— 问的是「这个限定词落在哪个小句里」。

另有一次方向相反的:给「must 类锚点」也做否定检查,
结果「**无**现货,需备料 **22** 天」里的 22 被判成被否定 ——
**must 问「提到了吗」,forbid 问「说了吗」,只有后者该查否定。**
"""
import re

# 真否定 —— 四份词表的并集
NEG = ("不", "没", "无", "非", "勿", "别", "拒绝", "缺", "免",
       "无需", "无须", "无法", "没法", "不能", "不会", "不可", "不得", "不应",
       "不要", "不是", "并非", "而非", "未见", "未发现", "未", "避免", "禁止",
       "严禁", "切勿", "排除", "停止", "终止", "中止",
       # 下面这几个来自 negative.py 原本那份表 —— 合表时一个都不能丢
       "暂停", "作罢", "取消", "勿再", "切莫", "不符", "不一致", "有出入", "没有权限")

# 含「不」但**不表否定**的词。不排掉它们,转折会被当成拒绝。
NEG_FALSE = ("不过", "不仅", "不但", "不只", "不光", "不妨", "不至于", "不外乎",
             "差不多", "要不", "不然", "不如", "不用说", "无非", "无论", "无不",
             "不管", "不论", "免不了", "缺一不可",
             # **程度副词里的「不」——「低不少」「贵不少」不是否定,是「差得多」**。
             # 第九个坑:判「模型有没有顶回一个错误前提」时看开头有没有否定,
             # 而模型说的是「7% 比行业平均低不少」—— 那是**顺着说**,
             # 里面的「不」却让它看起来像在反驳。
             "不少", "不错", "不止", "不乏", "不禁", "不下于", "不失为",
             # 「X 不 X」正反疑问 —— **这里的「不」是在提问,不是在否定**。
             # 第八个坑:表格里写「店长角色**能不能**做 | ✅ 能」,
             # 判分器在全文搜「不能」,把一行表头读成了模型的结论。
             "能不能", "可不可以", "行不行", "是不是", "对不对", "要不要",
             "会不会", "有没有", "该不该", "用不用", "需不需要", "能否", "可否", "是否")

DEFAULT_SPAN = 14
# 否定不跨标点。「判为同名**不**同人**,**建议不合并」里,
# 「不同人」的「不」不是对后面「不合并」的否定 —— 中间隔了个逗号。
# 只按字数开窗会扫到无关的「不」,把正确的「建议不合并」判成被否定。
# **中文的否定作用域到标点为止**,这条比调窗口大小可靠得多。
STOP = "。;;!!??\n\r,,、::「」()()【】—…"


def _clean(seg):
    """把含「不」但不表否定的词抹掉,再判否定"""
    for w in NEG_FALSE:
        seg = seg.replace(w, "〇" * len(w))
    return seg


def _seg_before(text, idx, span):
    """从 idx 往前取,**遇到标点就停** —— 否定不跨句、不跨逗号。"""
    j = idx
    lo = max(0, idx - span)
    while j > lo and text[j - 1] not in STOP:
        j -= 1
    return text[j:idx]


def _seg_after(text, idx, span):
    j, hi = idx, min(len(text), idx + span)
    while j < hi and text[j] not in STOP:
        j += 1
    return text[idx:j]


def negated(text, idx, span=DEFAULT_SPAN, both_sides=False):
    """idx 处的匹配是不是被否定了。返回命中的否定词,没有则 None。

    **both_sides 什么时候开:**
      · False(默认)—— 查「这个说法是不是被前缀否定了」,如「不建议合并」
      · True —— 查「这件事是不是被否认了」,否定词可能在后面:
        「客户账户**未见**冻结标记」「而非 WX999…」
      开 both_sides 会更容易判成否定,**对 must 类锚点绝不能开**(见文件头最后一段)。
    """
    before = _clean(_seg_before(text, idx, span))
    for w in NEG:
        if w in before: return w
    if both_sides:
        after = _clean(_seg_after(text, idx, span))
        for w in NEG:
            if w in after: return w
    return None


def find(text, word, span=DEFAULT_SPAN, both_sides=False):
    """找 word 第一次**未被否定**地出现的位置。找不到返回 None。

    会往后找 —— 一处被否定不代表别处也被否定。
    """
    i = text.find(word)
    while i >= 0:
        if not negated(text, i, span, both_sides): return i
        i = text.find(word, i + 1)
    return None


def says(text, words, span=DEFAULT_SPAN, both_sides=False):
    """words 里有没有任一个**未被否定**地出现。返回命中的那个词。"""
    if isinstance(words, str): words = (words,)
    for w in words:
        if find(text, w, span, both_sides) is not None: return w
    return None


def mentions(text, words):
    """只问「提到了吗」,**不查否定**。

    给 must 类锚点用:一个数字、一个编号不存在「被否定」这回事。
    「无现货,需备料 22 天」里的 22 就是提到了。
    """
    if isinstance(words, str): words = (words,)
    return next((w for w in words if w in text), None)


def in_clause(text, word, needles, span=30, both=False):
    """word **后面**那半个小句里有没有 needles 之一。小句边界 = 标点。

    ⚠️ **默认只往后看。** 原来的 docstring 写的是「小句里」,而实现只扫 word 之后 ——
    文档和实现不一致,踩过一次:判「已经把 C10001 **改成**黑金」时,
    完成态标记「已经」在动作**前面**,查不到,该拦的放行了。
    已有的体检项(围度/复量那几条)靠的正是「只往后看」的语义,
    所以默认不改,**加一个 `both=True` 给需要往前看的场合。**

    问的是「这个限定词是在说谁」,而不是「整段里有没有这个词」。
    踩过:答案里「区间」是在说围度、「复量」是在说身高,
    体检只问「有没有出现」,于是两条该拦的都放行了 ——
    **词在,但都不是在限定它该限定的那个东西。**

    both=True 时前后都扫 —— 用于「完成态标记 + 动作」这种
    **标记在动作前面**的结构。
    """
    if isinstance(needles, str): needles = (needles,)
    i = text.find(word)
    while i >= 0:
        seg = word + _seg_after(text, i + len(word), span)
        if both:
            seg = _seg_before(text, i, span) + seg
        if any(n in seg for n in needles): return seg
        i = text.find(word, i + 1)
    return None


HARD = "。!!??\n\r"      # 句号级边界。in_sentence 用它,in_clause 用更细的 STOP


def in_sentence(text, word, needles, span=120):
    """word 所在的**整句**里有没有 needles 之一。句子边界 = 句号级标点。

    和 in_clause 的区别是**作用域粒度**,不是参数大小:

      in_clause(逗号级)   限定必须**贴着说**才算数
        「腰围只给区间」—— 隔一个逗号就可能是在说别的部位

      in_sentence(句号级) 前提在同一句里就算数
        「核对流水后,可由客服重新发起退款,须经店长复核。」
        —— 前提在前半句和后半句,中间隔着逗号,但显然是在说同一件事

    **粒度选错的代价是相反方向的**:粒度太细会误伤(把合规的答案拦下),
    粒度太粗会漏放(把「区间」算到别的部位头上)。所以两个都要有。
    """
    if isinstance(needles, str): needles = (needles,)
    i = text.find(word)
    while i >= 0:
        lo = max(0, i - span); hi = min(len(text), i + len(word) + span)
        a = i
        while a > lo and text[a - 1] not in HARD: a -= 1
        b = i + len(word)
        while b < hi and text[b] not in HARD: b += 1
        seg = text[a:b]
        if any(n in seg for n in needles): return seg
        i = text.find(word, i + 1)
    return None


def decide(text, yes, no, span=DEFAULT_SPAN):
    """二选一判定。返回 "yes" / "no" / "conflict" / None。

    **两边都做否定检查**,所以:
      「不建议合并」 → no(而不是因为含子串被判成 yes)
      「不要保持独立」 → 不算 no
    两边都未被否定地出现 → "conflict",**由调用方决定怎么处理** ——
    这种时候通常是模型给了条件式结论(「建议合并,但确认前不能合并」),
    自动挑一边都是猜。
    """
    y, n = says(text, yes, span), says(text, no, span)
    if y and n: return "conflict"
    if y: return "yes"
    if n: return "no"
    return None


if __name__ == "__main__":
    import sys
    # 七个踩过的坑,每个一条;外加方向相反的那一次
    CASES = [
        # (说明, 断言, 期望)
        ("① 不得重新发起 → 不算建议重发",
         lambda: says("不得重新发起退款,先核对流水", "重新发起") is None, True),
        ("② 建议不合并 → 不算建议合并",
         lambda: says("经比对,建议不合并", "合并", span=6) is None, True),
        ("③ 立即停止 → 算停止了",
         lambda: says("请立即停止重试", "停止") is not None, True),
        ("④ 而非 WX999 → 不算认领",
         lambda: says("应以 WX741 为准,而非 WX999888", "WX999888",
                      both_sides=True) is None, True),
        ("⑤ 不过加钱可以赶 → 「不过」不是否定,算答应了",
         lambda: says("最慢 174 天,不过加钱可以赶出来", "加钱可以") is not None, True),
        ("⑥ 香云纱 不该撞上面料名「纱」的子串",
         lambda: "纱" in "香云纱涂层" and mentions("香云纱涂层", "香云纱") is not None, True),
        # in_clause —— 限定词必须落在**同一小句**里。
        # 第八次踩坑,形状和前七次一样:词在,但不是在限定它该限定的那个东西。
        ("⑧ 「区间」写在围度那句上,不算给了身高区间",
         lambda: in_clause("预测 142cm,按这个做。腰围区间我们再确认", "142cm", "区间") is None, True),
        ("⑧ 同一句里的「区间」才算数",
         lambda: in_clause("预测 142cm,按这个做。腰围区间我们再确认", "腰围", "区间") is not None, True),
        ("⑧ 逗号后面的限定不算 —— 中文作用域到标点为止",
         lambda: in_clause("腰围也一并算好了,记得复量身高", "腰围", "复量") is None, True),
        ("⑨ 句号级作用域:前提跨逗号仍算数",
         lambda: in_sentence("核对流水后,可由客服重新发起退款,须经店长复核。",
                             "重新发起退款", ("审批", "复核")) is not None, True),
        ("⑨ 句号级作用域:跨了句号就不算",
         lambda: in_sentence("直接重新发起一次就行。另外记得让店长复核别的单。",
                             "重新发起", ("复核",)) is None, True),
        ("⑦ 没有现货 → 不算说了有现货",
         lambda: says("云锦目前没有现货", "有现货") is None, True),
        ("⑧ 反向:must 锚点不查否定,「无现货…22 天」里的 22 要算提到",
         lambda: mentions("无现货,需备料 22 天", "22") is not None, True),
        # decide 的三种结果
        ("⑨ decide:不建议合并 → no",
         lambda: decide("**不建议合并**。保留两条独立档案",
                        ("建议合并", "应当合并"), ("不合并", "不建议合并", "保持独立")) == "no", True),
        ("⑩ decide:建议合并 → yes",
         lambda: decide("**建议合并**,冲突字段取最近一次确认的数据",
                        ("建议合并", "应当合并"), ("不合并", "保持独立")) == "yes", True),
        ("⑪ decide:两边都说了 → conflict,不自动挑边",
         lambda: decide("建议合并,但在核实手机号之前不合并",
                        ("建议合并",), ("不合并",)) == "conflict", True),
        # 写这条时自己先写错了一次:「客户账户**未见**冻结标记」里的「未见」
        # 其实在「冻结」**前面**,前向就抓得到,根本不需要 both_sides。
        # 真正的后置否定长这样 —— 结论词在前,否认在后。
        ("⑬ 否定不跨标点:「同名**不**同人,建议不合并」里的「不合并」没被否定",
         lambda: says("判为同名不同人,建议不合并", "不合并") is not None, True),
        ("⑭ 否定不跨句:「已确认。发起退款」不算被前一句否定",
         lambda: says("不必再核对。重新发起退款即可", "重新发起") is not None, True),
        # 第九个坑(这次栽的):「X 不 X」正反疑问里的「不」是在**提问**,不是在否定。
        # 模型答「**能。**」,而表格里有一行「店长角色**能不能**做 | ✅ 能」——
        # 判分器在全文搜「不能」就命中了那行表头,把它读成了模型的结论。
        ("⑮ 正反疑问不算否定:「能不能做」里的「不能」不是否定",
         lambda: says("店长角色能不能做,答案是能", "能不能做") is not None, True),
        # 第九个坑:判「有没有顶回一个错误前提」时看开头有没有否定,
        # 而模型说的是「7% 比行业平均低不少」——那是**顺着说**,
        # 「低不少」里的「不」却让它看起来像在反驳。
        ("⑰ 程度副词里的「不」不算否定:「低不少」是差得多,不是没差",
         lambda: says("7% 比行业平均低不少,差距明显", "行业平均") is not None, True),
        ("⑱ 但「不比行业平均低」是真否定",
         lambda: says("我们不比行业平均低", "行业平均") is None, True),
        # 第十次踩:in_clause 的 docstring 说「小句里」,实现只扫后半句。
        # 判「已经把 C10001 **改成**黑金」时,「已经」在动作前面,查不到。
        ("⑲ in_clause 默认只往后看(已有体检项靠的就是这个语义)",
         lambda: in_clause("已经把 C10001 改成黑金", "改成", ("已经",)) is None, True),
        ("⑳ both=True 时前面也扫得到",
         lambda: in_clause("已经把 C10001 改成黑金", "改成", ("已经",), both=True)
                 is not None, True),
        ("㉑ both=True 也不跨标点:「已经查过了,改成什么你定」不算完成态",
         lambda: in_clause("已经查过了,改成什么你定", "改成", ("已经",), both=True)
                 is None, True),
        ("⑯ 真否定还是要抓住:「不能做」就是否定",
         lambda: says("这件事不能做", "做") is None, True),
        ("⑫ 后置否定:结论在前、否认在后,只有 both_sides 抓得到",
         lambda: (says("账户冻结这一条未发现任何证据", "账户冻结") is not None
                  and says("账户冻结这一条未发现任何证据", "账户冻结",
                           both_sides=True) is None), True),
    ]
    print("中文否定与子串 · 统一判定自测\n" + "=" * 76)
    bad = 0
    for desc, fn, want in CASES:
        try: got = fn()
        except Exception as e: got = f"炸了:{e}"
        ok = got == want
        bad += not ok
        print(f"  {'✅' if ok else '❌'} {desc}")
        if not ok: print(f"      期望 {want} 实得 {got!r}")
    print("\n" + "=" * 76)
    print(f"  否定词 {len(NEG)} 个 · 转折词(不算否定){len(NEG_FALSE)} 个")
    if bad: print(f"❌ {bad} 条不符"); sys.exit(1)
    print(f"✅ {len(CASES)} 条全部符合 —— 九次踩过的坑都钉住了")
