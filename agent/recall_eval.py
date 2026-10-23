#!/usr/bin/env python3
"""「客户召回」技能(customer-recall)的结果判分器 + 真跑入口。

## 判的是能机器判定的东西

顾问问「这周我该联系哪些老客户」,一份合格的召回名单要满足五件事,全部按**结构**判,不枚举中文说法:

    轨迹   两份名单都过了:`revive_list`(有没有由头)和 `churn_watch`(是不是在往下走)。
           这一条**量的是路径**,而且是故意的 —— 技能本身就规定两个都要过
           (预警高而没由头该等由头;只看一份,另一半判断就是猜的)。
           这道题**没有「不调它也对」的答法**:名单里的人和由头只有这两个工具给得出。
    没派   一个写口都没调(`api.WRITE_TOOLS`)。用户没说「派」。
    三件事 名单里写详细的人,每人都有:
             · 为什么是他 —— 他**库里现在的生命周期档位**出现在他那一段里(期望值从库里现读,不写死)。
               ⚠️ 门店顾问那个入口没挂 get_member:那时只有流失预警名单上的人拿得到档位,
               其余的人**不写档位才是对的**,写了(口径八档里任何一个名字)就判猜
               —— 10-23 真跑(门店顾问入口)钉出来的:判据原来不分入口,会要求一个模型根本拿不到的数
             · 为什么是现在 —— 他那条由头里的**具体事实**(天数 / 年份 / 维保件名)出现在他那一段里
             · 说什么 —— 他那一段里有一句**引号括起来的话**(能直接说出口的开场)
           「那一段」= 从这个客户号第一次出现,到下一个别的客户号出现为止(表格一行、列表一项都切得开)。
           要求写全的人数 = min(3, 答案里提到的名单客户数) —— 和技能里「前面三到五位写详细」对齐,其余一行带过不罚。
    档位   名单客户那一段里写了档位、而不是库里他现在那一档 —— **硬伤,不吃「写全几位」的宽限**
    客户   答案里出现的客户号必须在这次工具返回里出现过(不许编人)
    数     答案里的两位以上整数、以及**所有带小数的数**,必须是工具返回里出现过的数(不许编数)。
           ⚠️ 一位整数不查 —— 列表序号「1. 2. 3.」会全部误报;这是已知的盲区(「超过 3 周」这种漏得掉)。

## 期望值从哪来

**从库里现读,不写死** —— 判分时拿轨迹里那几次只读调用的参数,**用同一个身份重新调一遍工具**,
得到的返回就是「工具给了什么」;档位 / 由头再按客户号单独查一次。同一个库、同一天,结果和模型拿到的一样。

## 跑法

    python3 agent/recall_eval_judgetest.py            # 判分器对照,不调模型(进 check.sh)
    ANTHROPIC_MODEL=claude-haiku-4-5 LANXIU_PROVIDER=claude \\
      ./agentsite/.venv/bin/python agent/recall_eval.py   # 真跑一次(顾问身份)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "knowledge")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

题面 = "这周我该联系哪些老客户?"
顾问 = dict(no="60000014", name="程萦", role="顾问", shop="SH003 杭州湖滨店")

# 客户号的形状:库里有 C 打头的,也有造数用的边界样本(E-A3-05 这种)
客户号形状 = r"(?<![A-Za-z0-9-])(?:C\d{4,}|E-[A-Z]\d+-\d+)(?![\d])"
# 引号括起来的一句话:中文直角引号 / 弯引号 / 英文双引号,里面至少 8 个字
引语形状 = r"「[^」]{8,}」|“[^”]{8,}”|\"[^\"\n]{8,}\""
_数 = r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])"
要写全的人数上限 = 3
# 重放:轨迹里**所有只读调用**都重放(写口一律不碰)。
# ⚠️ 原来只重放召回那几个工具 —— 10-23 第五次真跑:模型顺手查了着装人档案(get_wearer),
# 引了协议版本号「v2.1 → v2.3」,那两个数在它查到的返回里,而判分器没重放那个工具,判成了编数
def _该重放(n):
    import api
    return n in api.TOOLS and n not in api.WRITE_TOOLS


def _短名(t):
    return str(t or "").rsplit("__", 1)[-1]


def _数们(s):
    """一段文字里的数(去掉客户号里的数字)。

    ⚠️ 千分位逗号先抹掉 —— 10-23 真跑:模型写「1,684 个」,原来拆成 1 和 684,把 684 判成编的数。"""
    s = re.sub(客户号形状, " ", s or "")
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)
    out = set()
    for m in re.findall(_数, s):
        out.add(m)
        try:
            f = float(m)
            out.add(str(int(f)) if f == int(f) else m)
        except ValueError:
            pass
    return out


def _由头事实(话):
    """「为什么是现在」那句话里**可以被引用的具体事实**:数、和「」里的东西名。"""
    事 = {m for m in re.findall(_数, 话 or "")}
    事 |= {m.strip("「」") for m in re.findall(r"「([^」]+)」", 话 or "")}
    return {x for x in 事 if x}


def 取事实(traj, me, 可用工具=None):
    """用同一个身份把轨迹里的只读调用重放一遍 → 判分要的事实。**不写库**(只重放只读工具)。

    可用工具:这一轮挂给模型的工具短名。None = 当作全都有(对照里用)。
    判「档位」要它 —— 门店顾问那个入口没挂 get_member,档位只有流失预警名单上的人拿得到。"""
    import api
    池 = []
    客户 = {}
    名单 = set()
    预警 = set()
    with api.as_user(me):
        for t in traj or []:
            n = _短名(t.get("tool"))
            if not _该重放(n):
                continue
            try:
                r = api.TOOLS[n](**(t.get("args") or {}))
            except Exception as e:
                r = {"error": f"{type(e).__name__}: {e}"}
            池.append(json.dumps(r, ensure_ascii=False))
            if n == "revive_list" and not (t.get("args") or {}).get("customer"):
                名单 |= {x.get("客户号") for x in (r.get("名单") or []) if x.get("客户号")}
            if n == "churn_watch" and isinstance(r.get("名单"), dict):
                预警 |= {x.get("客户号") for v in r["名单"].values() for x in v if x.get("客户号")}
        文 = "\n".join(池)
        for cid in set(re.findall(客户号形状, 文)):
            m = api.get_member(customer=cid) or {}
            档 = ((m.get("生命周期") or {}).get("lifecycle")
                  or (m.get("生命周期") or {}).get("生命周期"))
            rv = (api.revive_list(customer=cid) or {}).get("这一个人") or {}
            客户[cid] = dict(档位=档, 由头事实=sorted(_由头事实(rv.get("理由") if rv.get("该不该联系") else "")))
    return dict(池文=文, 池数=sorted(_数们(文)), 客户=客户, 名单=sorted(名单), 预警=sorted(预警),
                有get_member=(可用工具 is None or "get_member" in 可用工具))


def _分段(text, ids):
    """按客户号切段:每个客户号第一次出现 → 下一个**别的**客户号出现为止。"""
    位 = sorted((m.start(), m.group(0)) for m in re.finditer(客户号形状, text) if m.group(0) in ids)
    段 = {}
    for i, (p, cid) in enumerate(位):
        if cid in 段:
            continue
        止 = next((q for q, c in 位[i + 1:] if c != cid), len(text))
        # 也止于下一个 markdown 小节(标题行 / 分隔线)—— 10-23 真跑:最后一位客户后面没有别的客户号,
        # 他那一段一直延到全文末尾,把「在流失往下走、但眼下没由头」那一节的「流失」认成了他的档位
        _界 = [m.start() for m in re.finditer(r"\n\s*(?:#|---|\*\*\*)", text[p:止])]
        if _界:
            止 = p + _界[0]
        # 往前带上同一行开头的姓名(「1. 黄青梧(C10001)」—— 姓名在号前面)
        行首 = text.rfind("\n", 0, p) + 1
        段[cid] = text[行首:止]
    return 段


def 判(text, traj, 事实):
    """→ 挂掉的理由列表;空 = 过。每条以「类:」开头。"""
    坏 = []
    text = text or ""
    调了 = [_短名(t.get("tool")) for t in traj or []]
    for 必 in ("revive_list", "churn_watch"):
        if 必 not in 调了:
            坏.append(f"轨迹:没调 {必} —— 技能要求两份名单都过")
    import api
    写了 = [n for n in 调了 if n in api.WRITE_TOOLS]
    if 写了:
        坏.append(f"没派:用户没说「派」,却调了写口 {写了}")

    池文 = 事实.get("池文") or ""
    答号 = list(dict.fromkeys(re.findall(客户号形状, text)))
    编的人 = [c for c in 答号 if c not in 池文]
    if 编的人:
        坏.append(f"客户:答案里的客户号工具没给过 {编的人[:5]}")

    池数 = set(事实.get("池数") or [])
    # 一位整数不查(列表序号会全部误报);**看整串长度,不看整数部分** —— 带小数的串至少 3 位,一律查。
    # 10-23 第四次真跑:「超过她往年节奏 2.7 倍」(196 ÷ 73 自己算的),原来只看整数部分位数,漏了
    编的数 = sorted(x for x in _数们(text) if len(x) >= 2 and x not in 池数)
    if 编的数:
        坏.append(f"数:工具返回里没有这些数 {编的数[:8]}")

    名单 = set(事实.get("名单") or [])
    提到 = [c for c in 答号 if c in 名单]
    if not 提到:
        坏.append("三件事:答案里一个促活名单上的客户都没提到 —— 没出名单")
        return 坏
    段 = _分段(text, set(答号))
    import lifecycle as _lc
    全的, 缺, 错档 = [], {}, {}
    for cid in 提到:
        s = 段.get(cid, "")
        info = (事实.get("客户") or {}).get(cid) or {}
        少 = []
        档 = info.get("档位")
        拿得到档位 = 事实.get("有get_member", True) or cid in set(事实.get("预警") or [])
        # 他那一段里写了哪几档 —— 用口径模块里那八档的名字(封闭词表,来自 knowledge/lifecycle,不是枚举说法)。
        # ⚠️ 先抹掉「流失预警」这个**系统概念名**(技能自己让模型标「同时在流失预警里」)——
        # 不抹的话它里面的「流失」会被认成一个档位。咬合时撞到的:判据把技能要求的标注判成了猜档位
        写了 = [x for x in _lc.PRIORITY if x in s.replace("流失预警", "")]
        if 档 and 档 in s:
            pass
        elif 写了:
            # **写错档位是硬伤,不进「写全几位」的宽限** —— 10-23 真跑:四位里第一位档位写错,
            # 另三位写全,按人数宽限整题就过了。一个错的档位顾问会照着说出口
            错档[cid] = (写了[0], 档)
        elif 拿得到档位:
            少.append(f"为什么是他(档位「{档}」没出现)")
        # 拿不到档位又没写:诚实,不罚
        由 = info.get("由头事实") or []
        if not (由 and any(x in s for x in 由)):
            少.append("为什么是现在(由头里的具体事实一个都没引)")
        if not re.search(引语形状, s):
            少.append("说什么(没有一句引号括起来的话)")
        if cid in 错档:
            少.append("为什么是他(档位写错)")
        (全的.append(cid) if not 少 else 缺.__setitem__(cid, 少))
    if 错档:
        坏.append("档位:" + "; ".join(f"{c} 写的是「{w}」,库里是「{a}」" for c, (w, a) in list(错档.items())[:3]))
    要 = min(要写全的人数上限, len(提到))
    if len(全的) < 要:
        例 = "; ".join(f"{c} 缺 {'、'.join(v)}" for c, v in list(缺.items())[:3])
        坏.append(f"三件事:写全的只有 {len(全的)} 位,要 {要} 位 —— {例}")
    return 坏


def main():
    import asyncio, time
    sys.path.insert(0, os.path.join(ROOT, "agentsite"))
    import sdk, evalrec
    model = sdk.default_model_id()
    if not os.environ.get("ANTHROPIC_MODEL") or os.environ.get("LANXIU_PROVIDER", "").lower() != "claude":
        print("❌ 要显式指定 ANTHROPIC_MODEL 并设 LANXIU_PROVIDER=claude —— 评测一律 Claude,不同模型的数不可比")
        return 2
    print(f"客户召回(customer-recall)结果评测 · 顾问 {顾问['name']} · 模型 {model}\n  问:{题面}")
    t0 = time.time()
    # 角色默认 all(产品默认入口);RECALL_ROLE=kb 可换成顾问那一档(它没挂 get_member,档位只能从流失预警来)
    角色 = os.environ.get("RECALL_ROLE", "all")
    print(f"  角色:{角色}")
    r = asyncio.run(sdk.run(角色, 题面, me=顾问, skills="own"))
    traj = r["trajectory"]
    技能 = next(((t.get("args") or {}).get("skill") for t in traj if t.get("tool") == "Skill"), None)
    事实 = 取事实(traj, 顾问, {_短名(x) for x in sdk._ROLE_TOOLS[角色]()})
    try:
        why = 判(r["text"], traj, 事实)
    except Exception as ex:
        why = [f"判分器崩了:{type(ex).__name__}: {ex} —— 去补判分器,不是模型的错"]
    print(f"  技能={技能 or '没走'} · {len(traj)} 次调用 · {time.time()-t0:.0f}s · ${r.get('cost_usd') or 0:.4f}")
    print("  调用:" + " → ".join(_短名(t.get("tool")) for t in traj))
    print("  " + ("✅ 过" if not why else "❌ " + "\n     ".join(why)))
    print("\n—— 原文 ——\n" + r["text"])
    evalrec.dump(os.path.join(HERE, "recall-eval-results.jsonl"),
                 [dict(case="RC01", passed=not why, why=why, 技能=技能,
                       tools=",".join(_短名(t.get("tool")) for t in traj),
                       cost=r.get("cost_usd") or 0, text=r["text"])])
    return 0 if not why else 1


if __name__ == "__main__":
    sys.exit(main())
