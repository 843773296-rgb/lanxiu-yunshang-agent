# -*- coding: utf-8 -*-
"""第三方 Skill 的**机器初筛** + 对人工清单的对账(intent/skill-third-party.md,用户 2026-10-23 拍)。

## 分工

  · 机器只判它判得了的:**依赖齐不齐**(skill_registry.依赖() 现算:缺脚本 / 要外部平台)
    和**描述里有没有点名别人的平台**(Amazon / 国际站 / Shopify / 跨境 B2B / SEO ……)
  · 「和汉服门店业务对不对得上」「有没有可借鉴的方法」「能不能改造」—— 人判,写在
    agentsite/third_party_review.json 的 分类 / 理由 里

初筛规则(故意简单,**它是人工复核的起点,不是结论**):
    描述点名别人的平台          → 不适用(补齐依赖也用不上,所以排在前面)
    否则依赖没就绪              → 缺依赖
    其余                        → 可借鉴方法
它永远不给「可适配」—— 能不能改造要看本系统有没有对应的工具,机器判不了。

## 用法

    python3 tools/third_party_screen.py                      # 扫本工作区装着的技能,和清单对账
    python3 tools/third_party_screen.py --dir <技能目录>      # 扫别处(只读),比如主检出那 236 个
    python3 tools/third_party_screen.py --dir <技能目录> --write   # 把初筛结果回写进清单的「初筛」栏

⚠️ --dir 只读:这个脚本不往技能目录里写任何东西。--write 只改清单文件。
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
import skill_registry as R   # noqa: E402

清单 = os.path.join(ROOT, "agentsite", "third_party_review.json")
别人的平台 = re.compile(r"Amazon|ASIN|Alibaba|阿里巴巴|国际站|ICBU|Accio|跨境|cross-border|B2B|[Ss]upplier|"
                       r"[Bb]uyer|买家|Shopify|DTC|SEO|GEO|Jungle Scout|TikTok|Instagram|YouTube|SaaS|淘宝|天猫|拼多多|抖店|抖音|京东|1688")


def 初筛(name):
    """先看业务、再看依赖:点名别人平台的,补齐依赖也用不上,所以「不适用」排在「缺依赖」前面。"""
    依 = R.依赖(name)
    正文, 述 = R._说明(name)
    # 描述常写成 YAML 多行块(`description: |`),单行正则只取到一个「|」—— 所以连正文开头一起看
    if 别人的平台.search(述 + "\n" + 正文[:1500]):
        return "不适用", 依
    if not 依["就绪"]:
        return "缺依赖", 依
    return "可借鉴方法", 依


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="技能目录(只读);不给就是本工作区的 agentsite/.claude/skills")
    ap.add_argument("--write", action="store_true", help="把初筛结果写回清单的「初筛」栏")
    a = ap.parse_args()
    if a.dir:
        R.技能目录 = os.path.abspath(a.dir)
    try:
        单 = json.load(open(清单, encoding="utf-8"))
    except (OSError, ValueError):
        单 = {}
    自 = R._ours()
    第三方 = [n for n in R.装了哪些() if n not in 自]
    print(f"\n▸ 第三方技能初筛 · 目录 {R.技能目录}")
    print(f"  装着 {len(第三方)} 个第三方 · 清单里 {len(单)} 条")
    不一致, 计 = [], {}
    for n in 第三方:
        机, _ = 初筛(n)
        if n in 单:
            if a.write:
                单[n]["初筛"] = 机
            人 = 单[n].get("分类")
            计[人] = 计.get(人, 0) + 1
            if 人 != 机:
                不一致.append((n, 机, 人, 单[n].get("与初筛不同") or ""))
    没进清单 = [n for n in 第三方 if n not in 单]
    print(f"  人工分类:" + " · ".join(f"{k} {v}" for k, v in sorted(计.items(), key=lambda x: -x[1])))
    print(f"  初筛和人工结论不一致 {len(不一致)} 个(每个都该在「与初筛不同」里写理由):")
    for n, 机, 人, 因 in 不一致:
        print(f"    {n}:初筛 {机} → 人工 {人}" + (f" —— {因[:70]}" if 因 else "  ⚠️ 没写理由"))
    if 没进清单:
        print(f"  ⚠️ 装着却没进清单 {len(没进清单)} 个:{没进清单[:10]}")
    if a.write:
        json.dump(单, open(清单, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(清单, "a", encoding="utf-8").write("\n")
        print(f"  已写回 {清单}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
