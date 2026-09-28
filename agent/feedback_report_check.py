#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判读回流上报的检查(分工 A3 的发送侧)。

## 这份检查盯的三件事,每一件都对应一个「不报错的错」

**① 词表对不上。** 内部叫 `已采纳`(`backend/ops.DECISIONS`),接收端叫 `采纳`。
A1 那次是**踩出来的**:同一个供应商两个拼法,结果每一条都发不出去而 `check.sh` 全绿 ——
因为一条都没在发,没有任何判据会红。所以这里**静态扫 `ops.DECISIONS`**,
要求每一个内部状态名都能归一到接收端的词表。这条能在「一条都还没发过」时就红。

**② trace 挂不上。** 接收端的规则:两个 trace 至少给一个,否则这条判读只能进总数。
⚠️ 而 `triage.trace_id` 这一列 **2026-09-28 才加** —— 在那之前的行全是空的。
所以「挂不上」是个**真实且常见**的状态,不是异常:判据要的是**它被说出来**,
不是它不发生。

**③ 传错了比没传更难发现。** `外部trace` 必须是 sdk 那个 trace id,
不是 `triage#N` —— 后者格式合法、接收端也收得下,但在那边匹配不到任何东西,
于是这条判读**看起来挂上了、实际只进了总数**。

## 它不验什么

不验接收端收没收到 —— 那要服务起着,而**依赖外部服务的判据**在服务没起那天会红,
那个红和「代码真改坏了」长得一模一样。
"""
import os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "backend")]
import feedback_report as F

FAIL, N = [], [0]


def ck(名, 取, 说=""):
    """延迟求值 —— 判据自己崩了的时候那条 ❌ 还打得出来。
    「崩了」和「判错了」下一步完全不同。"""
    N[0] += 1
    try:
        ok = bool(取())
    except Exception as e:
        ok, 说 = False, f"{说}  ← **崩了**:{type(e).__name__}: {e}"
    print(f"  {'✅' if ok else '❌'} {名}{('  ' + str(说)[:170]) if 说 else ''}")
    if not ok: FAIL.append(名)


def main():
    print("判读回流上报(A3 发送侧)· 检查")
    print("=" * 92)

    # ── 一、词表:内部每一个销账状态都要归一得到 ──────────────────────
    # **从 ops.DECISIONS 现读,不在这儿抄一份** —— 抄一份的话那边加一种判读,
    # 这里不会知道,而表现是「那一种判读全都发不出去」。
    import ops as _ops
    内部 = list(_ops.DECISIONS)
    ck("读到了内部的销账状态清单(**读不到 ≠ 全合规**,先断言读得到)",
       lambda: len(内部) >= 3, f"{内部}")
    坏 = [d for d in 内部 if F._判读(d) not in F.判读白名单]
    ck(f"内部每一个销账状态都能归一到接收端的词表 {'/'.join(F.判读白名单)}",
       lambda: not 坏,
       "；".join(f"{d!r} → {F._判读(d)!r}" for d in 坏[:3]) if 坏
       else "；".join(f"{d} → {F._判读(d)}" for d in 内部))

    # ── 二、「没传」和「认不出」要分得开 ────────────────────────────
    没传 = F.缺什么(F.组载荷(外部trace="t-1", 世界日期="2026-09-28"))
    认不出 = F.缺什么(F.组载荷(外部trace="t-1", 判读="已忽略", 世界日期="2026-09-28"))
    ck("判读**没传** → 报「没传」", lambda: any("没传" in x for x in 没传), str(没传))
    ck("判读**认不出** → 报「认不出」,而且报出拿到的是什么",
       lambda: any("认不出" in x and "已忽略" in x for x in 认不出), str(认不出))
    ck("这两种说的**不是同一句话**", lambda: 没传 != 认不出, "")

    # ── 三、两个 trace 都没有 → 必须说出来 ──────────────────────────
    无trace = F.缺什么(F.组载荷(判读="已采纳", 世界日期="2026-09-28"))
    ck("两个 trace 都没有 → 报「挂不到任何一次调用上」",
       lambda: any("挂不到" in x for x in 无trace), str(无trace))
    # ⚠️ 这两条**要把别的必填项补齐**,否则它们红在「有结论没传」上 ——
    # 那样它们验的就不是 trace 那条规矩了。
    # 「用例名字和它真正测的不是一回事」这个坑,这个项目踩过四次。
    ck("只有 外部trace 也算够(接收端的规则是**至少给一个**)",
       lambda: not F.缺什么(F.组载荷(判读="已改判", 外部trace="t-9", 有结论=True,
                                  世界日期="2026-09-28")), "")
    ck("只有 trace_id 也算够",
       lambda: not F.缺什么(F.组载荷(判读="已改判", trace_id="r-9", 有结论=True,
                                  世界日期="2026-09-28")), "")

    # ── 四、⚠️ 传错了比没传更难发现:外部trace 必须是 sdk 那个号 ────────
    # 这条**静态扫 ops.resolve 的源码**:它给 `外部trace=` 传的必须是
    # triage 行里那个 trace_id,不能是现编的字符串(比如 f"triage#{...}")。
    # 为什么非得静态扫:传 `triage#N` 的话,**发得出去、接收端也收得下** ——
    # 只是在那边匹配不到任何东西。运行时看不出来,只有读源码看得出来。
    src = open(os.path.join(ROOT, "backend", "ops.py"), encoding="utf-8").read()
    m = re.search(r"外部trace\s*=\s*([^,\n]+)", src)
    ck("ops.resolve 有往 A3 传 外部trace", lambda: m is not None,
       m.group(1).strip() if m else "一处都没有")
    ck("外部trace 传的是 **triage 行里的 trace_id**,不是现编的字符串",
       lambda: m is not None and 'trace_id' in m.group(1) and not m.group(1).strip().startswith('f"'),
       m.group(1).strip() if m else "")

    # ── 五、triage 表真的有 trace_id 这一列(不然上面全是空谈)──────────
    建表 = open(os.path.join(ROOT, "backend", "seed.py"), encoding="utf-8").read()
    段 = 建表[建表.index("CREATE TABLE triage("):]
    段 = 段[:段.index(");")]
    ck("`triage` 表有 trace_id 列(2026-09-28 补的 —— 在那之前这条链是断的)",
       lambda: "trace_id" in 段, "")
    ck("save_triage 收 trace_id 并落库",
       lambda: "trace_id=None" in open(os.path.join(ROOT, "backend", "ops.py"),
                                       encoding="utf-8").read(), "")

    # ── 五点五、⚠️ 形状闸:`truth` 的内容一行都不许流出去 ────────────
    #
    # `ops.resolve()` 判「已改判」时把人的裁决写进 `truth`,而 `truth` 是评测答案。
    # 上报载荷里只要能塞进自由文本,这条链就是 `truth` 的一个出口 ——
    # **而评测集一旦泄露就不能再当评测集。**
    #
    # ⚠️ **这条判据的失败信息只打印长度,不打印值** —— 否则判据自己成了泄漏口。
    # 这不是多虑:检查的输出会进 CI 日志,而 CI 日志比库好读得多。
    import sqlite3 as _sq
    _db = os.path.join(ROOT, "backend", "lanxiu.db")
    漏 = []
    真值行数 = 0
    try:
        _c = _sq.connect(_db)
        for (rc,) in _c.execute("SELECT root_cause FROM truth WHERE root_cause IS NOT NULL"):
            真值行数 += 1
            if F.收得下吗(rc)[0]:
                漏.append(len(rc or ""))        # **只留长度**
    except Exception as e:
        漏 = [-1]; 真值行数 = 0
        print(f"     ℹ 读不到 truth:{type(e).__name__}(这条判据这次没验到)")
    ck("样本量:truth 里有东西可验(**扫不到 ≠ 都安全**)",
       lambda: 真值行数 >= 10, f"{真值行数} 行")
    ck("`truth.root_cause` 每一行都**过不了**形状闸(答案流不出去)",
       lambda: not 漏,
       f"有 {len(漏)} 行能通过形状闸,长度分别是 {sorted(漏)[:8]} —— "
       f"**只报长度不报值**。多半是根因改成了 ASCII 代码"
       f"(比如 MEASURE_EXPIRED),那样这道闸就挡不住了,得另加办法"
       if 漏 else f"{真值行数} 行,一行都通不过(都是中文,而闸只收短 ASCII)")
    ck("形状闸认得出该拒的:中文 / 超长 ASCII / 非标量",
       lambda: (not F.收得下吗("押金退款连续失败")[0]
                and not F.收得下吗("A" * 40)[0]
                and not F.收得下吗(["x"])[0]
                and F.收得下吗("MEASURE-1")[0] and F.收得下吗(True)[0]
                and F.收得下吗(None)[0]), "")
    ck("`组载荷` 会把过不了闸的附带字段**滤掉**(不是降级成字符串)",
       lambda: (F.组载荷(判读="已采纳", 外部trace="t", 有结论=True,
                       附带={"好": 1, "坏": "押金退款连续失败"})["附带"] == {"好": 1}), "")
    ck("**第二道**:有人绕过 `组载荷` 直接塞自由文本,`缺什么` 也拦得住",
       lambda: any("形状闸" in x for x in F.缺什么(
           {"判读": "采纳", "外部trace": "t", "有结论": True,
            "附带": {"x": "押金退款连续失败"}})), "")

    # ── 五点六、`有结论` 必须显式传 ─────────────────────────────────
    ck("忘传 `有结论` → 红(**不默认** —— 默认会把采纳率的分母算错)",
       lambda: any("有结论" in x for x in F.缺什么(
           F.组载荷(判读="已采纳", 外部trace="t-1", 世界日期="2026-09-28"))), "")
    ck("`有结论=False` 是合法值,不许被当成「没传」",
       lambda: not F.缺什么(F.组载荷(判读="已采纳", 外部trace="t-1",
                                 有结论=False, 世界日期="2026-09-28")), "")
    ck("ops.resolve 把 `有结论` 显式传出去了(不是让它默认)",
       lambda: "有结论=bool(" in open(os.path.join(ROOT, "backend", "ops.py"),
                                    encoding="utf-8").read(), "")
    # ⚠️ 把 `_fb.排队(...)` 那一段源码抠出来,逐个字看有没有自由文本字段。
    # **静态扫,不是跑一遍看看** —— 跑一遍只证明「这次没带」,
    # 而这条规矩要管的是「以后有人在这儿加一行」。
    ops源 = open(os.path.join(ROOT, "backend", "ops.py"), encoding="utf-8").read()
    段 = ops源[ops源.index("_fb.排队("):]
    段 = 段[:段.index("世界日期")]
    禁 = [w for w in ("root_cause", "human_note", "note", "action", "ai_text", "说明")
          if w in 段.replace("ai_root_cause", "")]
    ck("⚠️ ops.resolve 的上报里**一个自由文本字段都没有**(truth 的内容不许出去)",
       lambda: not 禁, f"这几个出现在上报参数里:{禁} —— "
                      f"`root_cause` 正是写进 truth 的那个值" if 禁
                      else "只有 判读 / 有结论 / 结构化附带")

    # ── 六、A2:上报出任何事都不许把销账搞挂 ────────────────────────
    旧 = F.箱
    try:
        F.箱 = os.path.join(tempfile.gettempdir(), "不存在的一层", "更深", "o.jsonl")
        os.makedirs(os.path.dirname(os.path.dirname(F.箱)), exist_ok=True)
        open(os.path.dirname(F.箱), "w").close()      # 把那一层做成文件,makedirs 必失败
        ck("投递箱写不进去时,排队() **不抛**(A2:不影响业务)",
           lambda: F.排队(判读="已采纳", 外部trace="t-1") is None, "")
    finally:
        try: os.remove(os.path.dirname(F.箱))
        except Exception: pass
        F.箱 = 旧

    # ── 七、幂等键 + 积压是差集 ────────────────────────────────────
    # ⚠️ **投递箱和确认账要一起重定向。**A1 那份检查第一版只挪了投递箱,
    # 于是确认写进了真文件,下一次跑漏进来 —— **第一次绿,第二次才红**。
    箱备, 确备 = F.箱, F.确
    try:
        临 = tempfile.mkdtemp()
        F.箱, F.确 = os.path.join(临, "o.jsonl"), os.path.join(临, "s.jsonl")
        k1 = F.排队(判读="已采纳", 外部trace="t-1", 世界日期="2026-09-28")
        k2 = F.排队(判读="已采纳", 外部trace="t-1", 世界日期="2026-09-28")
        ck("幂等键是纯 ASCII(它进 HTTP 头,**头只能 latin-1**)",
           lambda: k1 and k1.isascii(), str(k1))
        ck("同一条判读排两次,拿到**两个不同的键**(键代表这一次投递)",
           lambda: k1 != k2, "")
        总, 确, 剩, _ = F.积压()
        ck("积压是**现算的差集**,不是某个字段",
           lambda: (总, 确, len(剩)) == (2, 0, 2), f"投递 {总} / 确认 {确} / 剩 {len(剩)}")
        F.确认(k1, "{}")
        _, 确2, 剩2, _ = F.积压()
        ck("确认一条之后还剩的少一条", lambda: (确2, len(剩2)) == (1, 1),
           f"确认 {确2} / 剩 {len(剩2)}")
        ck("投递箱和 A1 的**不是同一个文件**(两条链的积压要分开数)",
           lambda: os.path.basename(箱备) != os.path.basename(U箱()),
           f"{os.path.basename(箱备)} vs {os.path.basename(U箱())}")
    finally:
        F.箱, F.确 = 箱备, 确备

    print("=" * 92)
    if FAIL:
        print(f"\033[31m❌ 判读回流上报 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 判读回流上报 {N[0]} 条全过\033[0m")


def U箱():
    import usage_report as U
    return U.箱


咬合 = [
    ("把 判读别名 里 已采纳→采纳 那条删掉(内部状态名发不出去了)",
     "内部每一个销账状态都能归一到接收端的词表"),
    ("让 _判读() 认不出时返回 None(「认不出」又混进「没传」)",
     "这两种说的"),
    ("让 缺什么() 不再检查两个 trace(挂不上的判读被当成正常)",
     "两个 trace 都没有"),
    ("把 ops.resolve 的 外部trace 改回现编的 f\"triage#...\"(格式合法但那边匹配不到)",
     "外部trace 传的是"),
    ("把 排队() 里那层 try 去掉(写不进去就抛,销账跟着挂)",
     "投递箱写不进去时"),
    ("让 A3 和 A1 共用同一个投递箱文件(两条链的积压混在一起数)",
     "投递箱和 A1 的"),
    ("让形状闸放行中文(truth 的内容就能顺着上报流出去了)",
     "truth.root_cause"),
    ("让 缺什么() 不再要求显式传 有结论(采纳率的分母会被算错)",
     "忘传 `有结论`"),
    ("在 ops.resolve 的上报里加回 说明=root_cause(评测答案的出口)",
     "一个自由文本字段都没有"),
]

if __name__ == "__main__":
    main()
