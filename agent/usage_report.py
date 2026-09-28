#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往管理后台上报「这次调模型花了多少」(分工 A1 / A2)。

    A1  门店助手每次调模型,往管理后台上报一条(谁调的、花了多少、多久)
    A2  上报失败**不影响业务**,但**必须留痕** —— 不许静默丢

## 为什么不在调模型那一刻直接 POST

`llmtrace.record()` 在**热路径**上 —— 门店助手每答一句都要过它。在那里同步发 HTTP:

  · 每次调模型多等一个往返;接收端慢,**业务跟着慢**
  · 接收端挂了要么阻塞要么丢 —— 而 A2 说「不影响业务」和「必须留痕」**两个都要**

所以拆成两步:**record 只往本地投递箱写一行**(追加一行 JSON,微秒级),
真正的 POST 由 `tools/usage_push.py` 另跑。于是三件事同时成立:

  ① 不阻塞 —— 写一行文件,和写日志一个量级
  ② 留痕 —— **投递箱本身就是痕迹**,不需要另造一份「丢了几条」的账
  ③ 重试天然幂等 —— 幂等键在**投递那一刻**生成一次并写死在行里,
     之后重发多少次都是同一个键(接收端按它去重)

## ⚠️ 两个文件都只追加,不原地改写

投递箱 `usage-outbox.jsonl` 只追加;确认过的键写进 `usage-sent.jsonl`,也只追加。
**没发出去的 = 投递箱里的键 - 确认过的键**,现算。

不在原行上打「已发」标记,因为那要原地改写整个文件 ——
写到一半断电就会**毁掉整条队列**,而队列是这里唯一的痕迹。
两个只追加的文件,最坏情况是重发一次(接收端幂等,所以无害)。

## ⚠️ 说不清的字段一律不猜,宁可不发

`供应商` 不从模型名猜、`是mock` 不默认 False —— 两者都由调用方显式传。
理由是队友刚踩的那个:`usage_ledger.source` 一列曾同时装着执行模式和供应商,
**两种值都是合法字符串,分组查询照样出结果,只是看起来像两个供应商**。

同一族的还有我自己量到的:Agent SDK 的 `total_cost_usd` 跨供应商时是错的
(实测差过 24 倍 / 135 倍)。**猜一个看起来对的值,比留空糟得多** ——
留空的时候人知道自己不知道。

所以缺必填项的行**照样进投递箱**(痕迹要留),但推的时候**不发**,
单独报「发不出去的,原因是什么」。
"""
import json, os, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
箱 = os.path.join(ROOT, ".feynman", "usage-outbox.jsonl")
确 = os.path.join(ROOT, ".feynman", "usage-sent.jsonl")
伤 = os.path.join(ROOT, ".feynman", "usage-report-errors.jsonl")

资源白名单 = ("generate", "rerank", "embed")     # 接收端也按这个判,拼错的会被拒


def 配置():
    """上报地址 / 项目号 / 工号。**没配就是没配,不给默认值。**

    给默认地址的毛病:一台没配过的机器会**安静地往一个不存在的服务发**,
    而「发了没人收」和「压根没发」在这边长得一样。没配时投递箱照样攒着,
    `tools/usage_push.py` 会明说「没配上报地址,N 条堆着」。
    """
    return dict(地址=os.environ.get("LANXIU_USAGE_URL") or None,
                项目=os.environ.get("LANXIU_USAGE_PROJECT") or None,
                工号=os.environ.get("LANXIU_USAGE_USER") or None)


# ── 供应商的词表 ────────────────────────────────────────────────────
# ⚠️ **我们内部叫 `claude`,接收端的词表是 `anthropic`** —— 同一个供应商两个拼法。
# 2026-09-28 接线当天就踩了:`agent/v1.py` 的 `provider()` 返回 `id="claude"`,
# 而 `agentsite/sdk.py` 我写死的是 `"anthropic"` ——
# **我自己两个调用点,用了两个名字指同一家。**
#
# 后果是 V1/V2 那条路上每一条上报都判成「供应商缺失」,一条也发不出去,
# 而 `check.sh` 全绿 —— **因为一条都没在发,没有任何判据会红**。
# (这和队友那次 `usage_ledger.source` 一列装两个含义是同一族的反面:
#  他那次是一个名字两个含义,我这次是一个含义两个名字。两种都是合法字符串。)
#
# 归一放在**边界这一处**,不去改 `v1.py` —— 「我们内部叫 claude」是内部的事,
# 改调用点等于把这件事散到两处,而两处早晚会各自演化。
规范供应商 = ("anthropic", "deepseek")
供应商别名 = {"claude": "anthropic", "claude-oauth": "anthropic"}


def _供应商(值):
    """归一到接收端的词表。**认不出就原样留着,不返回 None。**

    ⚠️ 返回 None 会让「**认不出这个名字**」混进「**压根没传**」那一类,
    而这两件事下一步完全不同:一个是在 `供应商别名` 里补一条,
    一个是有个调用点忘了传。混在一起的话,报告会把人指向错的方向 ——
    这个项目今天已经有过一次「红的理由指错方向」了。
    认不认得出交给 `缺什么()` 判,它能把两种分开说。
    """
    if not 值: return None
    v = str(值).strip().lower()
    return 供应商别名.get(v, v)


def 组载荷(row, *, 供应商=None, 是mock=None, 资源="generate", 世界日期=None):
    """把记录仪那一行翻成接收端的字段。**缺的就是 None,不填默认值。**"""
    return {
        "调用方": f"门店助手:{row.get('purpose')}" if row.get("gen") == "V3"
                else f"{row.get('gen')}:{row.get('purpose')}",
        "模型": row.get("model"),
        "供应商": _供应商(供应商),
        "资源": 资源 if 资源 in 资源白名单 else None,
        "用量": {"input_tokens": row.get("input_tokens", 0),
                "output_tokens": row.get("output_tokens", 0),
                "cache_read_input_tokens": row.get("cache_hit_tokens", 0),
                "cache_creation_input_tokens": row.get("cache_write_tokens", 0)},
        "耗时毫秒": row.get("latency_ms"),
        "成功": not row.get("error"),
        "是mock": 是mock,
        "世界日期": 世界日期,
        "外部trace": row.get("trace_id"),
    }


def 缺什么(载荷):
    """推之前判必填。返回缺项清单(空 = 能发)。"""
    缺 = []
    if not 载荷.get("调用方"): 缺.append("调用方")
    if not 载荷.get("模型"): 缺.append("模型")
    if 载荷.get("资源") not in 资源白名单:
        缺.append(f"资源(白名单 {'/'.join(资源白名单)},拿到 {载荷.get('资源')!r})")
    if 载荷.get("是mock") is None:
        缺.append("是mock(**不默认 False** —— 忘传会把 mock 记成真花钱)")
    # 真跑才要供应商;mock 可以省(接收端的规则)。
    # ⚠️ **「没传」和「认不出」分开报** —— 两者下一步不同,见 `_供应商()`。
    if 载荷.get("是mock") is False:
        供 = 载荷.get("供应商")
        if not 供:
            缺.append("供应商**没传**(真跑必填,而且不从模型名猜)"
                      " —— 去看是哪个调用点漏了 provider=")
        elif 供 not in 规范供应商:
            缺.append(f"**认不出的供应商** {供!r} —— 接收端的词表是 "
                      f"{'/'.join(规范供应商)};要么调用点传错了,"
                      f"要么该在 `供应商别名` 里补一条")
    return 缺


def 排队(row, **kw):
    """把一行记录投进投递箱。**任何情况下都不抛** —— A2:不影响业务。

    返回幂等键(投递成功)或 None。键在这里生成一次,**之后永不变**:
    重发同一个键接收端认得出是同一次调用。
    """
    try:
        # ⚠️ 键必须是 **ASCII** —— 它进 HTTP 头,而头只能 latin-1。
        # 队友实测过:拿中文拼键,报出来是「连不上服务」而服务好好的。
        # 同一族的坑这个项目踩过两次(bash 不接受中文变量名 / 工具名必须 ASCII)。
        键 = "lxys-" + uuid.uuid4().hex
        行 = dict(键=键, 排于=time.strftime("%Y-%m-%d %H:%M:%S"),
                  载荷=组载荷(row, **kw))
        os.makedirs(os.path.dirname(箱), exist_ok=True)
        with open(箱, "a", encoding="utf-8") as f:
            f.write(json.dumps(行, ensure_ascii=False) + "\n")
        return 键
    except Exception as e:
        # ⚠️ **连留痕都失败了才走到这里。** 那就退到 stderr ——
        # 静默返回是这里唯一不许做的事(A2:不许静默丢)。
        try:
            os.makedirs(os.path.dirname(伤), exist_ok=True)
            with open(伤, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                                        错=f"{type(e).__name__}: {e}"[:300]),
                                   ensure_ascii=False) + "\n")
        except Exception:
            print(f"⚠️ [usage] 上报投递失败且留痕也失败:{type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        return None


def _读(p):
    if not os.path.exists(p): return []
    out = []
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if not l: continue
        try: out.append(json.loads(l))
        except Exception: pass          # 半行(写的时候断了)跳过,但不当成没有
    return out


def 积压():
    """(投递总数, 确认数, 还没发出去的行, 最老的一条排了多久)。

    ⚠️ 「还剩几条」是**现算**的差集,不是某个字段。字段会漂,差集不会。
    """
    全 = _读(箱); 好 = {x.get("键") for x in _读(确)}
    剩 = [x for x in 全 if x.get("键") not in 好]
    老 = 剩[0]["排于"] if 剩 else None
    return len(全), len(好), 剩, 老


def 发一条(行, cfg):
    """真的 POST 一条。返回 (成功吗, 说明)。**走 curl 不走 urllib** ——
    这台机器有 TLS 拦截,Python urllib 会证书校验失败。"""
    url = f"{cfg['地址'].rstrip('/')}/api/v1/projects/{cfg['项目']}/model-calls"
    cmd = ["curl", "-sS", "-m", "10", "-X", "POST", url,
           "-H", "Content-Type: application/json",
           "-H", f"X-Dev-User: {cfg['工号']}",
           "-H", f"Idempotency-Key: {行['键']}",
           "-w", "\n%{http_code}",
           "--data-binary", "@-"]
    try:
        r = subprocess.run(cmd, input=json.dumps(行["载荷"], ensure_ascii=False),
                           capture_output=True, text=True)
    except Exception as e:
        return False, f"curl 起不来:{type(e).__name__}: {e}"
    if r.returncode != 0:
        return False, f"curl 退 {r.returncode}:{r.stderr.strip()[:160]}"
    体, _, 码 = r.stdout.rpartition("\n")
    if 码.strip() not in ("200", "201"):
        return False, f"HTTP {码.strip()}:{体.strip()[:160]}"
    return True, 体.strip()[:300]


def 确认(键, 回):
    with open(确, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(键=键, 确认于=time.strftime("%Y-%m-%d %H:%M:%S"),
                                回=回[:200]), ensure_ascii=False) + "\n")
