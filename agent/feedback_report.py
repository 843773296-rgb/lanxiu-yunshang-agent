#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人采纳 / 改判之后,往管理后台上报一条判读(分工 A3)。

A1 报的是「**这次调用花了多少**」,A3 报的是「**这次调用的结果,人认不认**」。
两件事分开报,因为它们发生在不同时刻:调用当场 vs 值班同学几小时后销账。

## 归属:数据在这边,看在那边,中间只能是上报

采纳 / 改判发生在**应用层**(研判队列是门店天天用的);
而「看某个 AI 配置改动之后采纳率变没变」属于**控制面**。
管理后台**绝不反过来查澜绣的库** —— 所以只能是澜绣推过去。

## ⚠️ 没有 trace 的判读,只能进总数

接收端的规则:`trace_id` 和 `外部trace` **至少给一个**,两个都没有就挂不到任何
一次调用上;给一个不存在的会被 422 拒掉,**不会静默改成 NULL 收下** ——
收下之后它看起来挂在一次调用上,而那次调用不存在,比拒掉糟得多。

⚠️ 2026-09-28 做这件事时才发现:`triage` 表**原来根本没有 trace_id 这一列**。
`sdk.run()` 一直返回它,到 `/api/ops-triage` 那一跳丢掉了。
> **一个字段在链路中间被丢掉,和它从来不存在,在下游看起来完全一样。**
所以老行没有 trace(空值合法),新行开始有。没有 trace 的照样上报 ——
但**在本地就标出来**,让「这条挂不上」这件事有地方可查,而不是被接收端默默算进总数。

## 形状照抄 A1(`agent/usage_report.py`)

投递箱 + 只追加两个文件 + 差集算积压 + 幂等键在投递那一刻定死。
**不抄第二份实现**:公共的那几件(读写、积压、发一条)直接复用 A1 那个模块,
这里只负责「判读」这件事自己的字段和判据。
抄一份的下场这个项目见过太多次 —— 两份同样的东西,改了一份忘了另一份。
"""
import json, os, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
import usage_report as U           # 共用:配置 / 读写 / 积压 / 发一条

箱 = os.path.join(ROOT, ".feynman", "feedback-outbox.jsonl")
确 = os.path.join(ROOT, ".feynman", "feedback-sent.jsonl")
伤 = os.path.join(ROOT, ".feynman", "feedback-report-errors.jsonl")

# 接收端的白名单。⚠️ **不收任意字符串**:一个拼错的判读在报表里
# 会看起来像一种新的处理方式,而它只是个错别字。
判读白名单 = ("采纳", "改判", "升级", "作废")

# 我们内部的状态名 → 接收端的词表。
# ⚠️ 和 A1 那个 `供应商别名` 同一个理由,而且 A1 那次是**踩出来的**:
# 内部叫 `已采纳`(`backend/ops.DECISIONS`),接收端叫 `采纳`。
# 两边各自合法,而对不上时的表现是「每一条都发不出去」,不是报错。
判读别名 = {"已采纳": "采纳", "已改判": "改判", "已升级": "升级", "已作废": "作废"}


def _判读(值):
    """归一到接收端的词表。**认不出就原样留着,不返回 None** ——
    返回 None 会把「认不出这个名字」混进「压根没传」,而两者下一步不同。"""
    if not 值: return None
    v = str(值).strip()
    return 判读别名.get(v, v)


# ── ⚠️ 形状闸:附带信息**不收自由文本** ────────────────────────────────
#
# 2026-09-28 并行会话量到的一件事,不是建议是漏洞:
# `ops.resolve()` 判「已改判」时,把人的裁决**写进 `truth` 表** —— 而 `truth` 是评测答案。
# 我的第一版上报传了 `说明=(root_cause or ...)`,那正是写进 truth 的那个值。
# 于是这条链成了 `truth` 的一个出口:答案顺着它流进管理后台的界面(那是给人看的)。
#
# > **评测集一旦泄露,就再也不能当评测集。**
# 而系统约束写得很清楚:`truth` 表不许经任何 API / 工具暴露。
#
# 修法不是「记得别传 root_cause」—— 那依赖谁记得。**结构上就不留这个口子**:
# 附带信息只收 bool / int / None / **短 ASCII 标识符**,中文散文进不来。
#
# ⚠️ **已知盲区,写下来**:哪天根因改成 `MEASURE_EXPIRED` 这种 ASCII 代码,
# 这道闸就挡不住了。所以配了一条判据(见 feedback_report_check):
# `truth.root_cause` 的每一行都必须被这道闸拒绝 —— 那天它会红。
# ⚠️ 那条判据的失败信息**只许打印长度,不许打印值**,否则判据自己成了泄漏口。
附带值上限 = 24


def 收得下吗(值):
    """这个附带值能不能进载荷。返回 (能不能, 为什么不能)。"""
    if 值 is None or isinstance(值, bool) or isinstance(值, int):
        return True, ""
    if not isinstance(值, str):
        return False, f"只收 bool / int / None / 短 ASCII,拿到 {type(值).__name__}"
    if not 值.isascii():
        return False, f"不是 ASCII(长 {len(值)})"        # **不回显值本身**
    if len(值) > 附带值上限:
        return False, f"ASCII 但太长({len(值)} > {附带值上限})"
    return True, ""


def 组载荷(*, trace_id=None, 外部trace=None, 判读=None, 有结论=None,
          附带=None, 世界日期=None):
    """翻成接收端的字段。**缺的就是 None,不填默认值。**

    `有结论`:智能体这一次到底说没说话。**必须显式传** —— 和 A1 那条
    `是mock` 不默认 False 同一个理由:忘传会把「智能体没给结论」记成「人改判了」,
    而那会把采纳率的**分母**撑大,让这个数无声地偏低。
    (并行会话量到的:`booking.suggest()` 返回 None 是正常结果 ——
     这个店没有在职顾问可派,店长手点一个人,**那不是改判,智能体一个字都没说**。)

    `附带`:结构化的附加信息,过形状闸。**不收自由文本**,见上面。
    """
    附 = {}
    for k, v in (附带 or {}).items():
        行, _ = 收得下吗(v)
        if 行: 附[k] = v
        # 过不了闸的**直接丢掉,不报错也不降级成字符串** ——
        # 这里是发送端,不是校验器;真要知道有没有被丢,`缺什么()` 会说。
    return {"trace_id": trace_id or None,
            "外部trace": 外部trace or None,
            "判读": _判读(判读),
            "有结论": 有结论,
            "附带": 附 or None,
            "世界日期": 世界日期}


def 缺什么(载荷):
    """推之前判必填。返回缺项清单(空 = 能发)。"""
    缺 = []
    判 = 载荷.get("判读")
    if not 判:
        缺.append("判读**没传**")
    elif 判 not in 判读白名单:
        缺.append(f"**认不出的判读** {判!r} —— 接收端的词表是 "
                  f"{'/'.join(判读白名单)};要么写错了,要么该在 `判读别名` 里补一条")
    # ⚠️ 两个 trace **至少要有一个**。这一条不是格式校验,是语义的:
    # 没有它,这条判读挂不到任何一次调用上,**只能进总数** ——
    # 而 A3 存在的理由正是「改了配置之后采纳率变没变」,那要挂得上才算数。
    if not (载荷.get("trace_id") or 载荷.get("外部trace")):
        缺.append("**两个 trace 一个都没有** —— 这条判读挂不到任何一次调用上,"
                  "只能进总数。多半是这条研判早于 triage.trace_id 那一列"
                  "(2026-09-28 才加),或者当时记录仪没记上")
    # ⚠️ `有结论` 不默认 False/True,必须显式传 —— 见 `组载荷` 的注释。
    if 载荷.get("有结论") is None:
        缺.append("**有结论没传** —— 不知道智能体这次说没说话。"
                  "默认任何一边都会把采纳率的分母算错,而**每条记录单看都正常**")
    # 载荷里不许出现过不了形状闸的东西(理论上 `组载荷` 已经滤掉了,
    # 这里是**第二道**:有人绕过 `组载荷` 直接构造载荷时也拦得住)
    坏 = [k for k, v in (载荷.get("附带") or {}).items() if not 收得下吗(v)[0]]
    if 坏:
        缺.append(f"附带里有过不了形状闸的字段:{sorted(坏)}(只看键名,**不回显值**)")
    return 缺


def 排队(**kw):
    """把一条判读投进投递箱。**任何情况下都不抛** —— A2:不影响业务。

    返回幂等键,或 None(连留痕都失败)。
    """
    try:
        键 = "lxfb-" + uuid.uuid4().hex     # ASCII:它进 HTTP 头,头只能 latin-1
        行 = dict(键=键, 排于=time.strftime("%Y-%m-%d %H:%M:%S"), 载荷=组载荷(**kw))
        os.makedirs(os.path.dirname(箱), exist_ok=True)
        with open(箱, "a", encoding="utf-8") as f:
            f.write(json.dumps(行, ensure_ascii=False) + "\n")
        return 键
    except Exception as e:
        try:
            os.makedirs(os.path.dirname(伤), exist_ok=True)
            with open(伤, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                                        错=f"{type(e).__name__}: {e}"[:300]),
                                   ensure_ascii=False) + "\n")
        except Exception:
            print(f"⚠️ [feedback] 判读上报投递失败且留痕也失败:{type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        return None


def 积压():
    """(投递总数, 确认数, 还没发出去的行, 最老的一条排了多久)。**差集现算。**"""
    全 = U._读(箱); 好 = {x.get("键") for x in U._读(确)}
    剩 = [x for x in 全 if x.get("键") not in 好]
    return len(全), len(好), 剩, (剩[0]["排于"] if 剩 else None)


def 发一条(行, cfg):
    """POST 一条判读。走 curl(这台机器 Python urllib 会证书校验失败)。"""
    import subprocess
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}/feedback"
    cmd = ["curl", "-sS", "-m", "10", "-X", "POST", url,
           "-H", "Content-Type: application/json",
           "-H", f"X-Dev-User: {cfg['工号']}",
           "-H", f"Idempotency-Key: {行['键']}",
           "-w", "\n%{http_code}", "--data-binary", "@-"]
    try:
        r = subprocess.run(cmd, input=json.dumps(行["载荷"], ensure_ascii=False),
                           capture_output=True, text=True)
    except Exception as e:
        return False, f"curl 起不来:{type(e).__name__}: {e}"
    if r.returncode != 0:
        return False, f"curl 退 {r.returncode}:{r.stderr.strip()[:160]}"
    体, _, 码 = r.stdout.rpartition("\n")
    码 = 码.strip()
    if 码 == "422":
        # ⚠️ **422 要单独说**:接收端拒掉的多半是「给了一个不存在的 trace_id」。
        # 它和「网络不通」完全不是一回事 —— 后者重试有用,前者重试一万次都一样。
        return False, f"HTTP 422(接收端拒收,多半是 trace 挂不上):{体.strip()[:160]}"
    if 码 not in ("200", "201"):
        return False, f"HTTP {码}:{体.strip()[:160]}"
    return True, 体.strip()[:300]


def 确认(键, 回):
    with open(确, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(键=键, 确认于=time.strftime("%Y-%m-%d %H:%M:%S"),
                                回=回[:200]), ensure_ascii=False) + "\n")
