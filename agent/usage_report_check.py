#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用量上报的检查(分工 A1 / A2 的发送侧)。

## 这份检查存在的理由,是一个躲过了 check.sh 的真 bug

2026-09-28 接线当天:`agent/v1.py` 的 `provider()` 返回 `id="claude"`,
`agentsite/sdk.py` 写死的是 `"anthropic"` —— **同一个供应商两个拼法**,
而接收端的词表只有 `anthropic` / `deepseek`。
后果是 V1/V2 那条路上**每一条上报都发不出去**,而 `check.sh` **全绿**。

> **因为一条都没在发,所以没有任何判据会红。**

那个 bug 是读代码读出来的,不是跑出来的。所以这份检查的判据必须满足一条:
**在「一条都还没发过」的状态下也要能红。** 具体做法是**静态扫调用点** ——
把每个 `provider=` 传的值、以及 `v1.provider()` 可能返回的每个 `id=`,
逐个喂进 `_供应商()`,要求全都落进规范词表。

## 顺带说清它**不**管什么

它不验「接收端收没收到」—— 那要服务起着,而**依赖外部服务的判据**
在服务没起那天会红,那个红和「代码真改坏了」长得一模一样。
联调是另一件事,手工跑 `tools/usage_push.py`。
"""
import json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE]
import usage_report as U

FAIL, N = [], [0]


def ck(名, 取, 说=""):
    """延迟求值 —— 判据自己崩了的时候,那条 ❌ 还打得出来。
    「崩了」和「判错了」下一步完全不同。"""
    N[0] += 1
    try:
        ok = bool(取())
    except Exception as e:
        ok, 说 = False, f"{说}  ← **崩了**:{type(e).__name__}: {e}"
    print(f"  {'✅' if ok else '❌'} {名}{('  ' + str(说)[:170]) if 说 else ''}")
    if not ok: FAIL.append(名)


def 扫出所有调用点传的供应商():
    """返回 [(哪个文件, 传的是什么字面值)]。

    两种写法都要认:
      · `provider="anthropic"`            —— 直接传字面值
      · `agent/v1.py` 里 `dict(id="…")`   —— `provider=pv.get("id")` 的实际来源

    ⚠️ **第二种不能漏。** 只扫 `provider=` 的话,`v1.py` 传的是个变量,
    扫出来是空的 —— 而**空的扫描结果和「全都合规」在输出上一模一样**,
    那正是这个 bug 当初躲过去的方式。
    """
    出 = []
    for 相对 in ("agent/v1.py", "agentsite/sdk.py"):
        p = os.path.join(ROOT, 相对)
        if not os.path.exists(p): continue
        t = open(p, encoding="utf-8").read()
        for m in re.finditer(r'provider\s*=\s*"([^"]+)"', t):
            出.append((相对, m.group(1)))
        # `provider()` 返回的那几个 id —— v1.py 把它当 provider 传出去
        if 相对.endswith("v1.py"):
            for m in re.finditer(r'\bdict\(\s*id\s*=\s*"([^"]+)"', t):
                出.append((相对 + " 的 provider() 返回", m.group(1)))
    return 出


def main():
    print("用量上报(发送侧)· 检查")
    print("=" * 92)

    # ── 一、供应商词表:调用点传的每一个值都得落进接收端的词表 ──────────
    调 = 扫出所有调用点传的供应商()
    ck("扫到了调用点传的供应商值(**扫不到 ≠ 全合规**,所以先断言扫得到)",
       lambda: len(调) >= 2, f"扫到 {len(调)} 处:{[v for _, v in 调]}")
    坏 = [(f, v) for f, v in 调 if U._供应商(v) not in U.规范供应商]
    ck(f"每个调用点传的供应商都能归一到接收端的词表 {'/'.join(U.规范供应商)}",
       lambda: not 坏,
       "；".join(f"{f} 传 {v!r} → {U._供应商(v)!r}" for f, v in 坏[:3]) if 坏
       else "；".join(f"{f} 传 {v!r} → {U._供应商(v)!r}" for f, v in 调))
    ck("内部叫 claude 的那个归一成 anthropic(**别名只写在边界这一处**)",
       lambda: U._供应商("claude") == "anthropic", f"claude → {U._供应商('claude')!r}")

    # ── 二、「没传」和「认不出」是两件事,报告里必须分得开 ─────────────
    基 = dict(gen="V3", purpose="人工任务研判", model="claude-sonnet-5",
              input_tokens=20, output_tokens=774, latency_ms=1840)
    没传 = U.缺什么(U.组载荷(基, 是mock=False, 世界日期="2026-09-28"))
    认不出 = U.缺什么(U.组载荷(基, 供应商="openai", 是mock=False, 世界日期="2026-09-28"))
    ck("供应商**没传** → 报「没传」,而且指向「哪个调用点漏了」",
       lambda: any("没传" in x for x in 没传), str(没传))
    ck("供应商**认不出** → 报「认不出」,而且报出拿到的是什么",
       lambda: any("认不出" in x and "openai" in x for x in 认不出), str(认不出))
    ck("这两种说的**不是同一句话**(混在一起会把人指向错的方向)",
       lambda: 没传 != 认不出, "")

    # ── 三、是mock 不许默认 False ────────────────────────────────────
    忘传 = U.缺什么(U.组载荷(基, 供应商="claude", 世界日期="2026-09-28"))
    ck("忘传 是mock → 红(**不默认 False**:默认会把 mock 记成真花钱)",
       lambda: any("是mock" in x for x in 忘传), str(忘传))
    ck("资源不在白名单 → 红",
       lambda: any("资源" in x for x in U.缺什么(
           U.组载荷(基, 供应商="claude", 是mock=False, 资源="chat"))), "")
    齐 = U.缺什么(U.组载荷(基, 供应商="claude", 是mock=False, 资源="generate",
                        世界日期="2026-09-28"))
    ck("四样齐了就该能发(**对照要绿**,否则上面几条红得没意义)",
       lambda: not 齐, str(齐) or "齐")

    # ── 四、A2:上报出任何事都不许把业务搞挂 ──────────────────────────
    # ⚠️ 真把投递箱换成一个**写不进去的路径**,而不是 mock 掉写操作 ——
    # mock 掉的话证明的是「我没让它出错」,不是「它出错了也不抛」。
    旧 = U.箱
    try:
        U.箱 = os.path.join(tempfile.gettempdir(), "一个不存在的目录",
                            "更深的一层", "outbox.jsonl")
        os.makedirs(os.path.dirname(os.path.dirname(U.箱)), exist_ok=True)
        # 把那一层做成**文件**,于是 makedirs 一定失败
        open(os.path.dirname(U.箱), "w").close()
        ck("投递箱写不进去时,排队() **不抛**(A2:不影响业务)",
           lambda: U.排队(基, 供应商="claude", 是mock=False) is None, "")
    finally:
        try: os.remove(os.path.dirname(U.箱))
        except Exception: pass
        U.箱 = 旧

    # ── 五、幂等键必须是 ASCII(它进 HTTP 头,头只能 latin-1)──────────
    # 这一族这个项目踩过三次:bash 不接受中文变量名、工具名必须 ASCII、
    # 现在是 HTTP 头。**凡是要过一层协议的标识符,一律 ASCII。**
    箱备, 确备 = U.箱, U.确
    try:
        U.箱 = os.path.join(tempfile.mkdtemp(), "outbox.jsonl")
        U.确 = U.箱 + chr(46)+chr(115)+chr(101)+chr(110)+chr(116)
        键 = U.排队(基, 供应商="claude", 是mock=False, 世界日期="2026-09-28")
        ck("幂等键生成出来了", lambda: bool(键), str(键))
        ck("幂等键是纯 ASCII(它进 HTTP 头,**头只能 latin-1**)",
           lambda: 键 is not None and 键.isascii(), str(键))
        ck("同一条记录排两次,拿到的是**两个不同的键**"
           "(键代表「这一次投递」,不是「这条记录长什么样」)",
           lambda: U.排队(基, 供应商="claude", 是mock=False) != 键, "")
        总, 确, 剩, _ = U.积压()
        ck("积压是**现算的差集**,不是某个字段(字段会漂,差集不会)",
           lambda: (总, 确, len(剩)) == (2, 0, 2), f"投递 {总} / 确认 {确} / 剩 {len(剩)}")
        U.确认(键, "{}")
        _, 确2, 剩2, _ = U.积压()
        ck("确认过一条之后,还剩的少一条",
           lambda: (确2, len(剩2)) == (1, 1), f"确认 {确2} / 剩 {len(剩2)}")
    finally:
        U.箱, U.确 = 箱备, 确备

    print("=" * 92)
    if FAIL:
        print(f"\033[31m❌ 用量上报 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 用量上报 {N[0]} 条全过\033[0m")


咬合 = [
    ("把 供应商别名 里 claude→anthropic 那条删掉(V1 那条路又发不出去了)",
     "每个调用点传的供应商都能归一到接收端的词表"),
    ("让 _供应商() 认不出时返回 None(「认不出」又混进「没传」)",
     "这两种说的"),
    ("让 缺什么() 在 是mock 缺失时不报(默认当成 False)",
     "忘传 是mock"),
    ("把 排队() 里那层 try 去掉(写不进去就抛,业务跟着挂)",
     "投递箱写不进去时"),
    ("让 排队() 用记录内容做幂等键(同一条排两次拿到同一个键)",
     "同一条记录排两次"),
    ("让 扫出所有调用点传的供应商() 不扫 v1.py 的 dict(id=...)(扫出来是空的)",
     "扫到了调用点传的供应商值"),
]

if __name__ == "__main__":
    main()
