"""端到端里「按演示模式写的那几条」在真模型模式的服务上怎么办(用户 2026-10-26 拍:跳过并写明原因)。

本机常驻的管理后台 10-24 起是真模型模式(MODEL_ADAPTER=anthropic,用户拍的),而有几条断言要靠 mock 模型把
调试运行跑完(看脱敏的阶段、看「费用未知」、看幂等不重跑)—— 在这台机器上它们**必然**红,而 CI 上是绿的。
每次都靠人认一遍「这几套是老问题」,真正的新红就会混在里面被一起忽略。

所以:
  · 真模型模式下这些断言**不判**,打一行 ⏸ 写明没验和为什么 —— **不算通过**,汇总那行也单独写「几条没验」
  · **CI 上不许跳**:CI 要是也成了真模型模式,这几条不能悄悄全变成 ⏸ 然后报绿 —— 那里直接判红
"""
import json
import os
import urllib.request

原因 = "常驻服务是真模型模式(MODEL_ADAPTER≠mock),这一条按演示模式写 —— 没验,不算通过;CI(演示模式)上照验"


def 模型是mock(基址):
    """问服务自己。问不到 / 老服务没这个字段 → 当成 mock(照常判,宁可红也不悄悄跳)。"""
    try:
        with urllib.request.urlopen(基址 + "/api/healthz", timeout=10) as r:
            return json.loads(r.read() or b"{}").get("模型是mock", True) is not False
    except Exception:
        return True


def 包一层(ck, 基址):
    """→ (ckm, 跳了的, CI上不许跳的问题)。ckm 和 ck 同签名:真模型模式下记成 ⏸,否则照常判。"""
    mock = 模型是mock(基址)
    在CI = bool(os.environ.get("CI"))
    跳 = []
    问题 = None
    if not mock and 在CI:
        问题 = "CI 上服务是真模型模式 —— 这几条按演示模式写,**不许靠跳过变绿**;CI 要用 MODEL_ADAPTER=mock"

    def ckm(名, 真, *a, **k):
        if not mock and not 在CI:
            print(f"  ⏸ {名}  (没验:{原因})")
            跳.append(名)
            return
        return ck(名, 真, *a, **k)
    return ckm, 跳, 问题


def 汇总尾行(过数, 跳):
    """绿的时候 Makefile 只打最后一行 —— 跳过的数必须在这一行里,不然「全过」和「过了一部分」长得一样。"""
    return f"✅ 过 {过数} 条 · ⏸ {len(跳)} 条没验(真模型模式,见上)" if 跳 else None
