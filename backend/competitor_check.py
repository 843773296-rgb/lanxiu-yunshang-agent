#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞品与行业(知识库 D)· 检查 —— **每条有日期,过期会自己说,而且真有人读它。**

intent `kb-d-competitor` 的三条做完判据,这里管不联网的那几样:

  ① 每条都有 要点 / 来源类型 / 发布日期 / 抓取日期 / 出处(出处要写页面标题)
     —— 「一条没有日期的行业数据,和一条编的,在文档里长得一模一样」
     **链接对不对要联网,在 `tools/verify_sources.py`(不进门禁),加条目后手动跑**
  ② 它是原料:话术(13)或电商运营(15)至少一篇引用了它
  ③ 超过 6 个月(业务 09-29)的条目,`kb_read` 读它时会自己说出来 —— 用合成条目验两个方向
"""
import datetime as dt, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]

咬合 = [
    ("把 16 篇第一条的抓取日期删掉", "每条都带齐五样"),
    ("让过期判定永远说「没过期」", "超过 6 个月的条目会被说出来"),
    ("把 13 篇和 15 篇里对 16 篇的引用都删掉", "它是原料:话术或电商运营引用了它"),
]

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


def 过期自测(C):
    """合成条目验两个方向 —— 「今天」是夹具自己的,和库、和世界日期都无关。"""
    今 = dt.date(2026, 10, 2)        # 合成夹具的「今天」,和库无关
    假 = ("## 一、x\n\n### 老的\n- 要点:x\n- 抓取日期:2026-03-01\n\n"
          "### 新的\n- 要点:x\n- 抓取日期:2026-09-01\n\n### 坏的\n- 要点:x\n- 抓取日期:去年\n")
    话 = C.过期提示(今, 假) or ""
    ck("超过 6 个月的条目会被说出来", "老的" in 话 and "新的" not in 话, 2, 话[:60])
    ck("抓取日期认不出的也会被说出来(认不出不等于没过期)", "坏的" in 话, 1)
    ck("6 个月整那天不算过期(边界)", C.过期了吗("2026-04-02", 今) is False
       and C.过期了吗("2026-04-01", 今) is True, 2)


def main():
    import competitor as C
    print("竞品与行业 · 检查")
    print("=" * 84)
    es = C.条目()
    缺 = [f"{e['标题'][:16]} 缺{'、'.join(k for k in C.必填 if not e.get(k))}"
         for e in es if any(not e.get(k) for k in C.必填)]
    ck("每条都带齐五样(要点 / 来源类型 / 发布日期 / 抓取日期 / 出处)", not 缺, len(es),
       f"共 {len(缺)} 条:" + "；".join(缺[:3]) if 缺 else f"{len(es)} 条")
    坏型 = [e["标题"][:16] for e in es if e.get("来源类型") not in ("一手", "二手")]
    ck("来源类型只许一手 / 二手(二手不许冒充一手)", not 坏型, len(es), f"共 {len(坏型)} 条:" + "、".join(坏型[:3]) if 坏型 else "")
    无题 = [e["标题"][:16] for e in es
            if not re.match(r"^.+?[::].+?→\s*https?://", e.get("出处", ""))]
    ck("出处写了「出处名:页面标题 → 链接」(verify_sources 靠页面标题核)", not 无题, len(es),
       f"共 {len(无题)} 条:" + "、".join(无题[:3]) if 无题 else "")
    认不出 = [e["标题"][:16] for e in es if C.过期了吗(e.get("抓取日期", ""), dt.date(2000, 1, 1)) is None]
    ck("抓取日期都认得出(YYYY-MM-DD)", not 认不出, len(es), f"共 {len(认不出)} 条:" + "、".join(认不出[:3]) if 认不出 else "")

    # ② 被引用
    引 = [f for f in ("13-销售话术.md", "15-电商运营.md")
         if "16-竞品与行业" in open(os.path.join(ROOT, "knowledge", f), encoding="utf-8").read()]
    ck("它是原料:话术或电商运营引用了它", bool(引), 2, "、".join(引) or "**没人引用** —— 它是一堆没人看的资料")

    过期自测(C)

    import api
    r = api.kb_read("16")
    ck("kb_read 读得到这一篇", bool(r.get("小节")), len(r.get("小节") or []))

    print()
    if FAIL:
        print(f"\033[31m❌ 竞品与行业 {len(FAIL)} 处不符合预期\033[0m")
        for f in FAIL: print(f"   · {f}")
        sys.exit(1)
    print(f"\033[32m✅ 竞品与行业全部符合预期\033[0m({len(es)} 条,过期线 {C.过期月数} 个月)")


if __name__ == "__main__":
    main()
