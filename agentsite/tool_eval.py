# -*- coding: utf-8 -*-
"""工具路由评测 —— **合并工具的收益,不能靠「看起来更整齐」。**

## 起因

2026-09-19 把 9 个同族工具合成 3 个(60 → 54)。当时验的是
「合并后函数返回一模一样」—— 那只证明**没弄坏**,一个字都没说清收益。

合并的理由是官方那条判据:「如果一个人类工程师都说不准某个场景该用哪个工具,
AI 不可能做得更好」。所以要测的正是**模型在族内选不选得对**。

## 合并会引入一种新的失败方式,必须一起测

族内只剩一个工具,「选错工具」这件事确实不可能了 —— 但它带参数了。
**参数给错和选错工具一样答非所问**:
`get_tasks()` 不传 `scope=团队`,回的是「我的任务」,而那是另一个答案。

所以判的不是「调了哪个工具」,是「**调的那一次拿没拿到该拿的东西**」:
工具名 + 参数一起看。

## 怎么做对照

**不猴子补丁,跑真正的合并前那一版。**

系统提示词是 import 时按工具清单装配好的(`sdk.py` 里 `SYS_ALL` 那几行),
补丁改不了它 —— 那样跑出来是「旧工具 + 新规矩」,**一个从来没存在过的配置**。
所以对照组用 `git worktree` 检出合并前的提交整份跑。

## 题面刻意避开技能

每条都不碰报价/成长/排班/工期救援/换货 —— 否则测的是技能触发,那是另一份评测的事。

## ⚠️ 跑崩了不算答错了

`skill_eval` 2026-09-19 那次跑批暴露的:模型调用抛异常时,它把 `ERR:xxx`
当成「触发结果」记进准确率 —— 期望不触发的记成**误触发**,
期望触发的记成**漏触发**。**「跑崩了」和「答错了」在准确率里长得一模一样。**
而那批错是扎堆出现的(连着五条,之后自己恢复),明显是瞬时故障。

这里的做法:崩了就**重试**,重试还崩就**单独计一类,不进准确率分母** ——
并在汇总里明说有几条没测到。**没测到不叫通过,也不叫失败。**

## 用法

    ./agentsite/.venv/bin/python agentsite/tool_eval.py --check          # 结构体检,进门禁
    ./agentsite/.venv/bin/python agentsite/tool_eval.py --repeat 2 --save after

## 怎么重建对照组(下次再做这种对比时照抄)

    git worktree add -f ~/Desktop/lanxiu-before <合并前那个提交>
    ln -s <主仓>/backend/lanxiu.db   ~/Desktop/lanxiu-before/backend/lanxiu.db
    ln -s <主仓>/agentsite/.venv     ~/Desktop/lanxiu-before/agentsite/.venv
    cp agentsite/tool_eval.py agentsite/evals/tool_routing.json ~/Desktop/lanxiu-before/agentsite/…
    cd ~/Desktop/lanxiu-before && ./agentsite/.venv/bin/python -u agentsite/tool_eval.py \
        --repeat 2 --save before --label "合并前 · 60 个工具"
    cp ~/Desktop/lanxiu-before/agentsite/evals/runs/tool_before.json <主仓>/agentsite/evals/runs/
    cd <主仓> && ./agentsite/.venv/bin/python -u agentsite/tool_eval.py \
        --repeat 2 --save after --label "合并后 · 54 个工具" --diff before

数据库和 venv 是软链(它们都被 gitignore 了,不跟着 worktree 走);
**两边读同一个库**,否则比的是两份数据,不是两份代码。

## 2026-09-19 那次的结果(留着,免得下次又凭感觉合并)

    合并前 60 个:命中 11/11 · 首调即中 22/22 · 1.00 次/条 · 120,532 token/条
    合并后 54 个:命中 11/11 · 首调即中 22/22 · 1.00 次/条 · 119,706 token/条  (省 0.69%)

**准确率没有改进空间 —— 合并前就是满分。** 22 次调用 22 次第一下就调对,
包括预判最难的那几条。所以「同族工具容易选错」这个假设**在这九个工具上不成立**,
合并的理由被自己的数据推翻了。省 token 的预判也错了 5 倍
(预判降 20%,实际降 4.2%)—— 合并后的工具**必须把原工具的口径全带上**,
**字节没有消失,只是搬了家**。
"""
import argparse, asyncio, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
CASES = os.path.join(HERE, "evals", "tool_routing.json")
RUNS = os.path.join(HERE, "evals", "runs")
G, R, Y, B, D = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"

身份表 = {
    "店长":     {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"},
    "总部运营": {"no": "60000008", "name": "魏欣新", "role": "总部运营", "shop": ""},
    "版师":     {"no": "60000020", "name": "傅砚青", "role": "版师", "shop": ""},
}


def 合不合(调用, 期望):
    """一次工具调用满不满足期望。**工具名和参数一起看。**

    参数值写 "*" 表示只要求这个键在(值是什么不管);
    期望里没写的键不管 —— 多传参数不算错,**少传关键参数才是错**。
    """
    # ⚠️ 轨迹里的名字带服务前缀(`mcp__shop__get_tasks`),题面里写的是裸名。
    #    第一版直接比,控制组当场判 0/1 —— **它调对了,而我的判据说没调对**。
    #    一条判错的检查比没有检查更糟:它会让一次好的改动看起来是退化。
    if (调用.get("tool") or "").rsplit("__", 1)[-1] != 期望["工具"]:
        return False
    args = 调用.get("args") or {}
    for k, v in (期望.get("参数") or {}).items():
        if k not in args:
            return False
        if v != "*" and str(args[k]).strip() != str(v).strip():
            return False
    return True


def 业务调用(traj):
    """只看业务工具。**内置工具不算** —— ToolSearch / Skill 这类不是路由要测的东西。"""
    跳过 = {"Skill", "ToolSearch", "TodoWrite", "Task", "Agent"}
    return [t for t in (traj or []) if (t.get("tool") or "") not in 跳过]


async def _跑一次(sdk, c):
    import importlib
    _s = importlib.import_module("sdk")
    prov, mdl = _s.default_model_id().split(":", 1)
    me = 身份表[c["身份"]]
    return await sdk.run(c["角色"], c["prompt"], provider=prov, model_name=mdl,
                         me=me, skills="own")


def 评一次(c, r):
    traj = 业务调用(r.get("trajectory"))
    命中 = next((i for i, t in enumerate(traj)
                if any(合不合(t, e) for e in c["期望"])), None)
    return dict(命中=命中 is not None,
                首调即中=(命中 == 0),
                调用次数=len(traj),
                走过的=[t.get("tool") for t in traj][:6],
                秒=r.get("seconds"),
                token=sum(v for k, v in (r.get("usage") or {}).items()
                          if isinstance(v, int) and "token" in k))


def 体检():
    """**不调模型的结构体检,这一条进门禁。**

    真跑一轮要几分钟、要连模型,进不了门禁。但有一类失效是**静默**的,
    必须有人守着:**用例点名的工具改了名字,这条用例就永远被「跳过」** ——
    而跳过在汇总里长得和「没问题」一模一样。

    (`tool_eval.py` 里那个「期望的工具这一版一个都没挂 → 跳过」是**对的**:
     同一份题面要在合并前后两个版本上都能跑。但它只该在**对照那一版**上跳,
     在现版上一条都不该跳。)
    """
    import sdk
    有 = {t.rsplit("__", 1)[-1] for t in sdk._tools_for("all")} | \
         {t.rsplit("__", 1)[-1] for t in sdk._tools_for("pattern")}
    spec = json.load(open(CASES, encoding="utf-8"))
    cs = spec["cases"]
    坏 = []
    for c in cs:
        for k in ("id", "prompt", "期望", "why", "角色", "身份"):
            if k not in c: 坏.append(f"#{c.get('id','?')} 缺 {k}")
        if c.get("身份") not in 身份表: 坏.append(f"#{c.get('id')} 身份「{c.get('身份')}」不认识")
        if c.get("角色") not in ("all", "kb", "task", "pattern", "workshop", "finance"):
            坏.append(f"#{c.get('id')} 角色「{c.get('角色')}」不认识")
        够 = [e for e in c.get("期望") or [] if e.get("工具") in 有]
        if not 够:
            坏.append(f"#{c.get('id')} 期望的工具在现版一个都没挂 "
                      f"({[e.get('工具') for e in c.get('期望') or []]}) "
                      f"—— **这条永远会被跳过,而跳过看起来和没问题一样**")
    重 = [c["id"] for c in cs if [x["id"] for x in cs].count(c["id"]) > 1]
    if 重: 坏.append(f"用例号重复:{sorted(set(重))}")
    # **样本量下限。** 空集合上所有性质都成立 —— 用例被清空时,
    # 上面每一条检查都会通过,而那和「全都合格」长得一模一样。
    if len(cs) < 8:
        坏.append(f"只有 {len(cs)} 条用例,低于下限 8 —— **这不叫通过,这叫没题可测**")
    print(f"工具路由用例 · 体检({len(cs)} 条,现版挂着 {len(有)} 个工具)")
    for b in 坏: print(f"  ❌ {b}")
    if 坏: return 1
    print(f"  ✅ 每条都至少有一个期望工具在现版挂着;号不重;身份和角色都认识")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只做结构体检,不调模型。**这一条进门禁**")
    ap.add_argument("--only", type=int)
    ap.add_argument("--repeat", type=int, default=2,
                    help="每条跑几遍。**单跑一次是有噪声的**")
    ap.add_argument("--retry", type=int, default=2, help="跑崩了重试几次")
    ap.add_argument("--save")
    ap.add_argument("--diff")
    ap.add_argument("--label", default="", help="这一版叫什么(写进结果文件,免得两份结果分不清)")
    a = ap.parse_args()
    if a.check:
        return 体检()

    spec = json.load(open(CASES, encoding="utf-8"))
    cases = [c for c in spec["cases"] if not a.only or c["id"] == a.only]
    import sdk
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    有 = {t.rsplit("__", 1)[-1] for t in sdk._tools_for("all")} | \
         {t.rsplit("__", 1)[-1] for t in sdk._tools_for("pattern")}

    print(f"\n{B}工具路由评测 · {len(cases)} 条 × {a.repeat} 遍 · "
          f"模型 {sdk.default_model_id()} · 这一版挂着 {len(有)} 个工具{D}")
    if a.label: print(f"  版本标记:{a.label}")
    print("=" * 96)

    rows, 崩 = [], 0
    t0 = time.time()
    for c in cases:
        # **先说清楚这一版里哪些期望是够得着的。** 合并前只有老名字在,
        # 合并后只有新名字在 —— 同一份题面两边都能跑,但期望不都成立。
        够得着 = [e for e in c["期望"] if e["工具"] in 有]
        if not 够得着:
            print(f"  {Y}⏸{D} #{c['id']:<3} {c['prompt'][:26]:<28} "
                  f"期望里的工具这一版一个都没挂 —— **跳过,不算通过也不算失败**")
            rows.append(dict(id=c["id"], 跳过=True)); continue
        每遍 = []
        for _ in range(max(1, a.repeat)):
            for _t in range(a.retry + 1):
                try:
                    r = asyncio.run(_跑一次(sdk, c)); break
                except Exception as e:
                    r = {"__err": f"{type(e).__name__}"}
            每遍.append(r if "__err" not in r else r)
        好 = [x for x in 每遍 if "__err" not in x]
        坏 = len(每遍) - len(好)
        崩 += 坏
        if not 好:
            # ⚠️ **一次都没跑成 ≠ 答错了。** 不进准确率分母。
            print(f"  {R}✗{D} #{c['id']:<3} {c['prompt'][:26]:<28} "
                  f"{R}{a.repeat} 遍全崩({每遍[0]['__err']}),这条没测到{D}")
            rows.append(dict(id=c["id"], 没测到=True, 错=每遍[0]["__err"])); continue
        评 = [评一次(dict(c, 期望=够得着), x) for x in 好]
        中 = sum(1 for e in 评 if e["命中"])
        首 = sum(1 for e in 评 if e["首调即中"])
        ok = (中 == len(评))
        稳 = 0 < 中 < len(评)
        mark = f"{G}✅{D}" if ok else (f"{Y}〜{D}" if 稳 else f"{R}❌{D}")
        平均次数 = sum(e["调用次数"] for e in 评) / len(评)
        print(f"  {mark} #{c['id']:<3} {c['prompt'][:26]:<28} "
              f"命中 {中}/{len(评)} · 首调即中 {首}/{len(评)} · "
              f"平均调 {平均次数:.1f} 次 · {sum(e['秒'] or 0 for e in 评)/len(评):.0f} 秒"
              + (f" · {R}{坏} 遍崩了{D}" if 坏 else ""))
        if not ok:
            print(f"       走过:{评[0]['走过的']}  —— {c['why']}")
        rows.append(dict(id=c["id"], prompt=c["prompt"], 命中=中, 遍数=len(评),
                         首调即中=首, ok=ok, 不稳定=稳, 崩=坏,
                         平均调用次数=round(平均次数, 2),
                         平均秒=round(sum(e["秒"] or 0 for e in 评) / len(评), 1),
                         平均token=round(sum(e["token"] for e in 评) / len(评)),
                         走过的=评[0]["走过的"], 期望=够得着))

    真 = [x for x in rows if not x.get("跳过") and not x.get("没测到")]
    ok_n = sum(1 for x in 真 if x.get("ok"))
    首_n = sum(x.get("首调即中", 0) for x in 真)
    遍_n = sum(x.get("遍数", 0) for x in 真)
    print("=" * 96)
    print(f"  命中 {ok_n}/{len(真)} 条全对  ·  首调即中 {首_n}/{遍_n} 遍  ·  "
          f"平均调用 {sum(x['平均调用次数'] for x in 真)/max(len(真),1):.2f} 次/条  ·  "
          f"平均 {sum(x['平均token'] for x in 真)/max(len(真),1):.0f} token/条")
    跳 = [x['id'] for x in rows if x.get('跳过')]
    没 = [x['id'] for x in rows if x.get('没测到')]
    if 跳: print(f"  {Y}跳过 {跳}{D}(期望的工具这一版没挂)")
    if 没: print(f"  {R}没测到 {没}{D} —— **没测到不叫通过,也不叫失败**;共崩 {崩} 遍")
    print(f"  用时 {time.time()-t0:.0f} 秒")

    if a.save:
        os.makedirs(RUNS, exist_ok=True)
        p = os.path.join(RUNS, f"tool_{a.save}.json")
        json.dump(dict(标记=a.label, 挂着工具数=len(有),
                       命中=f"{ok_n}/{len(真)}", 首调即中=f"{首_n}/{遍_n}",
                       明细=rows), open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n  已存:{p}")
    if a.diff:
        p = os.path.join(RUNS, f"tool_{a.diff}.json")
        if not os.path.exists(p):
            print(f"\n  {R}没有 {p}{D}"); return 1
        base = json.load(open(p, encoding="utf-8"))
        老 = {x["id"]: x for x in base["明细"]}
        print(f"\n{B}和 {base.get('标记') or a.diff} 比({base['挂着工具数']} 个工具 → {len(有)} 个){D}")
        print("=" * 96)
        for x in 真:
            o = 老.get(x["id"])
            if not o or o.get("跳过") or o.get("没测到"):
                print(f"  #{x['id']:<3} 对照那边没数(跳过或没测到),**不作比较**"); continue
            def 记(now, was, 名, 高好=True):
                if now == was: return f"{名} 持平({now})"
                好 = (now > was) if 高好 else (now < was)
                c = G if 好 else R
                return f"{c}{名} {was} → {now}{D}"
            print(f"  #{x['id']:<3} "
                  f"{记(x['命中'], o['命中'], '命中')} · "
                  f"{记(x['首调即中'], o['首调即中'], '首调即中')} · "
                  f"{记(x['平均调用次数'], o['平均调用次数'], '调用次数', 高好=False)} · "
                  f"{记(x['平均token'], o['平均token'], 'token', 高好=False)}")
    return 0


咬合 = [
    ('把一条用例的期望工具改成一个不存在的名字(模拟「工具改名了,用例没跟着改」)',
     '期望的工具在现版一个都没挂'),
    ('把用例清空到只剩几条(**空集合上所有性质都成立**)',
     '低于下限'),
]
# ⚠️ 只有 `--check` 这一路进门禁 —— 真跑一轮要连模型、要几分钟。
# 咬合验的也只是这一路。**真跑那部分的正确性靠对照实验本身**:
# 2026-09-19 那次里,它当场抓到了我自己判据写错(按裸名比带前缀的工具名),
# 控制组判 0/1 —— **它调对了,而判据说没调对**。

if __name__ == "__main__":
    sys.exit(main())
