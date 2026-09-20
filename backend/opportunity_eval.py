# -*- coding: utf-8 -*-
"""商机判断 · 规则版 vs 规则+模型版 的横向对比。

**不进 check.sh** —— 它要调模型(花钱、有随机性),而
「依赖外部状态的检查放进门禁会变成随机拦路」(CLAUDE.md)。

## ⚠️ 连跑两轮,一轮不作数

模型有随机性。这个项目为「拿单轮结果下结论」栽过四次
(评测跑的模型和产品不一致、单跑一次断定描述改坏了、13/15 就说装 236 个技能没影响、
三代对比表写单轮的 6/6/6 而那是三次抛硬币都正面)。

所以这里**每个版本跑两轮**,两轮都报。
**两轮之间的差,如果比两个版本之间的差还大,那这个对比说明不了任何事。**

跑:
    LANXIU_PROVIDER=claude python3 backend/opportunity_eval.py
"""
import json, os, sqlite3, sys, time, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import opportunity as op

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
DB = os.path.join(HERE, "lanxiu.db")
结果档 = os.path.join(HERE, "..", "agent", "opportunity-results.jsonl")


def 跑一轮(条, 真值, 用模型):
    对, 误报, 漏报, 失败 = 0, [], [], []
    for r in 条:
        应该 = 真值.get(r["audio_id"])
        if 应该 is None:
            continue
        try:
            判, 码, why = (op.判断_带模型(r["text"]) if 用模型 else op.判断(r["text"]))
        except Exception as e:
            # **「跑崩了」和「答错了」在准确率里长得一模一样** —— 单独记,不混进错的那堆
            失败.append((r["audio_id"], str(e)[:60])); continue
        if 判 == 应该:
            对 += 1
        elif 判:
            误报.append((r["audio_id"], 码))
        else:
            漏报.append((r["audio_id"], 码))
    return 对, 误报, 漏报, 失败


def main():
    if os.environ.get("LANXIU_PROVIDER") != "claude":
        print(f"{Y}⚠{D} 规矩:一律用 Claude(月租,不额外花钱)。设 LANXIU_PROVIDER=claude")
        return 1
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    真值 = {r["case_id"]: r["root_cause"] == "是商机"
            for r in c.execute("select * from truth where src='造数据标注'")}
    条 = list(c.execute("select audio_id,text from call_transcript "
                        "where audio_id like 'TS-%' order by audio_id"))
    n = len(条)
    print(f"\n\033[1m▸ 商机判断 · 规则版 vs 规则+模型版({n} 条,⚠️ 造的对话)\033[0m")
    print("  " + "=" * 80)

    记录 = {"跑于": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "模型": os.environ.get("ANTHROPIC_MODEL", "(默认)"), "条数": n, "轮": []}
    for 版本, 用模型 in (("规则版", False), ("规则+模型", True)):
        for 轮 in (1, 2):
            t0 = time.time()
            对, 误报, 漏报, 失败 = 跑一轮(条, 真值, 用模型)
            用时 = time.time() - t0
            率 = 对 * 100 // n
            记录["轮"].append({"版本": 版本, "轮次": 轮, "对": 对, "准确率": 率,
                             "误报": len(误报), "漏报": len(漏报), "失败": len(失败),
                             "用时秒": round(用时, 1)})
            额 = f" · {R}调用失败 {len(失败)}{D}" if 失败 else ""
            print(f"  【{版本} 第{轮}轮】{对}/{n} = **{率}%**  "
                  f"误报 {len(误报)} · 漏报 {len(漏报)}{额} · {用时:.0f}s")
            if 失败:
                print(f"     {R}⚠{D} **跑崩了和答错了在准确率里长得一样** —— "
                      f"这 {len(失败)} 条单独记,没混进错的那堆:{失败[0][1]}")
            if 版本 == "规则版":
                break        # 规则版是确定性的,跑一轮就够

    轮 = 记录["轮"]
    规 = [x for x in 轮 if x["版本"] == "规则版"][0]["准确率"]
    模 = [x["准确率"] for x in 轮 if x["版本"] == "规则+模型"]
    print("\n  " + "=" * 80)
    print(f"  规则版 {规}%(确定性,跑一轮就够)  →  规则+模型 {模[0]}% / {模[1]}%(两轮)")
    轮间差 = abs(模[0] - 模[1])
    版本差 = abs(sum(模) / 2 - 规)
    print(f"  两轮之间差 {轮间差} 个百分点;两个版本之间差 {版本差:.0f} 个百分点")
    if 轮间差 >= 版本差:
        print(f"  {Y}⚠ **两轮之间的差不小于两个版本之间的差 —— 这个对比说明不了任何事。**{D}")
        print(f"     n={n} 本来也分辨不出小差别。")
    else:
        print(f"  {G}✅{D} 版本差大于轮间抖动,这个对比有意义(但 n={n},只能说方向)")

    os.makedirs(os.path.dirname(结果档), exist_ok=True)
    with open(结果档, "a", encoding="utf-8") as f:
        f.write(json.dumps(记录, ensure_ascii=False) + "\n")
    print(f"\n  结果已追加到 {os.path.relpath(结果档, HERE+'/..')}(带来路:谁跑的、哪个模型、哪一天)")
    print(f"  {Y}⚠{D} 前提:逐字稿是**造的**,不是真实通话 —— 造的对话信号清楚得多。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
