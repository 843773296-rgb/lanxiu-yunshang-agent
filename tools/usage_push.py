#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把投递箱里的用量上报推给管理后台(分工 A1 的发送侧)。

    python3 tools/usage_push.py            # 推,最多 200 条
    python3 tools/usage_push.py --看        # 只报积压,一条都不发
    python3 tools/usage_push.py --限 50

## 报告必须回答三个问题,而不是「成功 / 失败」

    发出去几条  ·  还剩几条  ·  **发不出去的那些,分别为什么**

第三个是重点。这个项目栽过好几次同一个形状:**一个总数不足以让人知道下一步做什么。**
「还剩 37 条」可能是接收端没起、可能是没配地址、可能是那 37 条缺必填项 ——
三种的下一步完全不同,而它们在「还剩 37」这个数里长得一模一样。

## ⚠️ 「一条都没发」有两种,必须分开说

  · 投递箱是空的        —— 没有东西要发(正常)
  · 有东西但一条也没发出 —— 出事了

这两种如果都打印「已是最新」,那么**上报链整条断掉的那天,这里照样是绿的**。

2026-09-28 真出现过这个形状:V1 那条路上所有上报都因为供应商拼法不一致
(内部叫 `claude`、接收端的词表是 `anthropic`)而发不出去,而 `check.sh` 全绿 ——
**因为一条都没在发,没有任何判据会红。** 那个 bug 是读代码读出来的,不是跑出来的。
所以判据得钉在**能在「还没发过」的状态下就红**的地方:见 `agent/usage_report_check.py`。
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "agent")]
import usage_report as U


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--看", action="store_true", help="只报积压,不发")
    ap.add_argument("--限", type=int, default=200)
    a = ap.parse_args()

    cfg = U.配置()
    总, 确, 剩, 老 = U.积压()
    print(f"用量上报 · 投递 {总} 条 / 已确认 {确} 条 / **还没发出去 {len(剩)} 条**"
          + (f"(最老的排于 {老})" if 老 else ""))

    # 先把「发不出去的」按原因分开 —— 缺必填项的发了也会被接收端拒,
    # 而**拒的理由留在接收端,到不了这里**。所以在本地就要判出来。
    能发, 不能 = [], []
    for 行 in 剩:
        缺 = U.缺什么(行["载荷"])
        (不能 if 缺 else 能发).append((行, 缺))
    if 不能:
        print(f"\n  ⚠️ **{len(不能)} 条缺必填项,不发**(发了只会被拒,而理由到不了这里):")
        由 = {}
        for 行, 缺 in 不能:
            由.setdefault(" / ".join(缺), []).append(行["键"])
        for k, v in sorted(由.items(), key=lambda kv: -len(kv[1])):
            print(f"      {len(v)} 条:{k}")
            print(f"        例:{v[0]}")

    没配 = [k for k in ("地址", "项目", "工号") if not cfg[k]]
    if 没配:
        print(f"\n  ⚠️ **没配上报地址,一条都发不出去** —— 缺 {'/'.join(没配)}。"
              f"\n     投递箱照样攒着({len(剩)} 条),配好之后会一起补发 —— "
              f"**幂等键在投递那一刻就定死了,补发不会重复记账**。"
              f"\n     要配:LANXIU_USAGE_URL / LANXIU_USAGE_PROJECT / LANXIU_USAGE_USER")
        # ⚠️ 有东西要发却发不出去,**必须是个非 0**:「没配」不是「没事」。
        sys.exit(2 if 剩 else 0)

    if a.看:
        print(f"\n  (--看:一条都没发;能发的 {len(能发)} 条)")
        sys.exit(2 if 不能 else 0)

    成 = 败 = 0
    失败原因 = {}
    for 行, _ in 能发[:a.限]:
        ok, 说 = U.发一条(行, cfg)
        if ok:
            U.确认(行["键"], 说); 成 += 1
        else:
            败 += 1
            失败原因.setdefault(说.split(":")[0], []).append(行["键"])
            # ⚠️ 连着失败就停 —— 接收端没起时,硬跑完 200 条是 200 次白等,
            # 而报告里会多出 199 个一模一样的原因,**把真正的信息埋掉**。
            if 败 >= 3 and 成 == 0:
                print("  ⏸ 连着失败 3 条且一条没成,停下(剩下的留在箱里,下次再推)")
                break

    print(f"\n  发出去 {成} 条 · 失败 {败} 条")
    for k, v in sorted(失败原因.items(), key=lambda kv: -len(kv[1])):
        print(f"      {len(v)} 条:{k}")
    _, 确2, 剩2, _ = U.积压()
    print(f"  现在:已确认 {确2} / 还剩 {len(剩2)}")

    # 「有东西要发但一条没发出去」和「没东西要发」不是一回事
    if 剩 and 成 == 0:
        print(f"\n\033[31m❌ 有 {len(剩)} 条要发,一条都没发出去 —— 上报链现在是断的\033[0m")
        sys.exit(1)
    if 不能:
        sys.exit(2)


# ── 咬合记录 ──────────────────────────────────────────────────────────
# ⚠️ 这个脚本的咬合**挂在 `agent/usage_report_check.py` 上**:
# 它自己的输出依赖「接收端起没起」,而**咬合不许依赖外部服务** ——
# 依赖外部的咬合,在服务没起那天会红,而那个红和「代码真改坏了」长得一样。
咬合 = [
    ("(推送侧的咬合挂在 agent/usage_report_check.py 上,见那份的咬合清单)",
     "有东西要发但一条都没发出去"),
]

if __name__ == "__main__":
    main()
