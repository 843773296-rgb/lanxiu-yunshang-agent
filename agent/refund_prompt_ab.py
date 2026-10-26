#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B:财务研判提示词里那个「点名根因后果」的括号,去掉之后会怎样。

用户 2026-10-26 拍:「先跑 A/B 拿数据再定」。

## 比的是哪一句

`backend/ops.py` 的 BP-01 提示词里:

    建议动作这一段**必须**写明:① 按你查到的根因,**哪一步不能做、做了会有什么后果**
    (钱可能已经出账的,再发会不会重复出账;收款方那头还在不在、重试会不会注定失败)

那个括号举的两个例子,**正好是 DQ9001 和 DQ9002 两道题的答案**。
(紧挨着它的注释原来写着「只写原则、不点名任何一种根因该怎么答」——
 注释和代码对不上,2026-10-26 已改成实话。)

    A 版 = 现状,点名两种根因各自的后果
    B 版 = **把那个括号整个删掉** —— 仍要求「说明哪一步不能做、做了会有什么后果」,
           只是不再举例说哪种根因对应哪种后果(两版唯一的差别就是这个举例)

## 这个实验分辨得出什么

n = **3 题 × 2 轮 × 2 版 = 12 次调用**。这个样本量只分辨得出**大差别**:
两版都接近满分、或者 B 版明显塌下来,才算有信号;差一两题是抖动。
这个仓库为「拿单轮结果下结论」栽过四次(CLAUDE.md 第 3 节那张表),
所以报告里**两版各自的两轮都单独写出来,不许只报一个平均数**。

## 它分辨不出什么 —— 这一条必须和结论一起说

B 版如果分数掉了,掉的原因有两种,而**下一步动作相反**:

    不知道该说风险        → 该把「必须说后果」这条原则写得更清楚
    知道该说、但不知道哪种根因对应哪种后果 → **恰恰说明这道题有鉴别力**,
                                            而提示词不该继续替它答

这两者在分数上长得一模一样,只能看原文分。所以两版的**原文全部落盘**。

## 跑法(必须显式指定模型,而且用 venv 的 python)

    ANTHROPIC_MODEL=claude-haiku-4-5 LANXIU_PROVIDER=claude \\
      ./agentsite/.venv/bin/python agent/refund_prompt_ab.py

只补一版(另一版从它的结果文件读回最后一行):`AB_ONLY=B`(**ASCII 名字**,见下面那条坑)

⚠️ 结果**不写**基线文件 `agent/refund-sets-results.jsonl` ——
各自写 `agent/refund-prompt-ab-A.jsonl` / `-B.jsonl`。
基线是「这一版代码在这套题上考了多少分」的历史,实验数混进去就再也分不开了。
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import ops                                                    # noqa: E402
import refund_sets as RS                                       # noqa: E402

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

点名 = ("(钱可能已经出账的,再发会不会重复出账;"
        "收款方那头还在不在、重试会不会注定失败)")
# ⚠️ B 版是**直接删掉那个括号**,不是换成另一句话。
# 第一版写的是「(按你查到的根因判断是哪一种后果)」,而前半句本来就有
# 「按你查到的根因」—— 拼起来是「按你查到的根因,…做了会有什么后果
# (按你查到的根因判断是哪一种后果)」,**同一句话说了两遍**。
# 那样 B 版要是掉分,掉的可能是「话说绕了」而不是「没点名」——
# > 一个因为少了举例而掉的分,和一个因为句子变笨拙而掉的分,
# > **在那张对比表上长得一模一样。**
# 删掉括号的话,两版之间**唯一的差别就是有没有举例**。
不点名 = ""

_原 = ops.研判提示词


def _B版提示词(*a, **k):
    bp, case, p = _原(*a, **k)
    # ⚠️ **这个断言是实验的前提**,不是防御性代码。
    # 产品那头把括号改了之后,replace 会静默什么都不换,
    # 于是 B 版和 A 版跑的是同一份提示词 ——
    # > 一个「两版没差别」的结论,和一个「两版其实是同一版」的 bug,
    # > **在那张对比表上长得一模一样**。
    assert 点名 in p, (
        "提示词里找不到那个要被替换掉的括号 —— 产品那头改过了,"
        "这个实验的前提不成立。先去看 backend/ops.py 的 BP-01 分支,"
        "确认现在那句写的是什么,再决定 B 版该换什么。")
    return bp, case, p.replace(点名, 不点名)


def 读回(名):
    """这一版这次没跑 —— 从它自己的结果文件里读**最后一行**。

    ⚠️ 读回来的是**另一次跑的数**,所以报告里要能看出来:返回的 dict 带 `读回的=True`
    和那一行的时间。不标的话,一份「两版同一批条件下跑的对比」和一份
    「一版今天跑、一版昨天跑」**在那张表上长得一模一样**。
    """
    路 = os.path.join(HERE, f"refund-prompt-ab-{名}.jsonl")
    assert os.path.isfile(路), f"{名} 版没跑过,也没有结果文件可读:{路}"
    行 = [l for l in io.open(路, encoding="utf-8") if l.strip()]
    assert 行, f"{名} 版的结果文件是空的:{路}"
    d = json.loads(行[-1])
    print(f"\n{Y}【{名} 版】这次没跑,读回 {os.path.basename(路)} 的最后一行"
          f"(跑于 {d.get('跑于')}){D}")
    return dict(d.get("报") or {}, 读回的=True, 那一行跑于=d.get("跑于"))


def 跑一版(名, 补丁, 轮数):
    存回 = RS.存
    RS.存 = os.path.join(HERE, f"refund-prompt-ab-{名}.jsonl")
    if 补丁:
        # `跑一题` 里写的是 `import ops as _ops`(**函数内** import),而 Python
        # 从 `sys.modules` 取同一个模块对象 —— 所以 patch 模块属性就够了。
        # ⚠️ 第一版还多写了一行 `RS._ops.研判提示词 = ...`,当场 AttributeError:
        # `refund_sets` 根本没有模块级的 `_ops`(那是函数里的局部名)。
        # A 版已经跑完才炸,**白烧了六次调用** —— 下次动这类注入,
        # 先拿一次不调模型的 dry-run 把注入点验通(这个脚本的替换本身验过了,
        # 验漏的是「patch 哪个对象」这一半)。
        ops.研判提示词 = _B版提示词
    try:
        print(f"\n{'='*74}\n【{名} 版】{'括号换成不点名' if 补丁 else '现状(点名两种根因后果)'}"
              f" —— 跑 {轮数} 轮,落 {os.path.basename(RS.存)}\n{'='*74}")
        return RS.做(轮数)
    finally:
        RS.存 = 存回
        ops.研判提示词 = _原


def 一版怎么样(报):
    """两轮各自的数 —— **不给平均**。平均会把「两轮都 2/3」和「一轮 3/3 一轮 1/3」
    压成同一个数,而后者是抖动、前者是能力。"""
    出 = []
    for k in ("第一轮", "第二轮"):
        d = 报.get(k) or {}
        出.append(dict(轮=k, 答成几题=d.get("答成几题"), 过=d.get("过"),
                      没过的=[x["押金单"] for x in (d.get("没过的") or [])],
                      没答成的=[x["押金单"] for x in (d.get("没答成的") or [])]))
    return dict(这次跑的=not 报.get("读回的"), 那一行跑于=报.get("那一行跑于"),
                两轮=出, 两轮都全过=报.get("两轮都全过"),
                两轮没过的是不是同一批=报.get("两轮没过的是不是同一批"),
                一句话=报.get("一句话"))


if __name__ == "__main__":
    轮 = int(os.environ.get("AB轮数", "2"))
    assert os.environ.get("ANTHROPIC_MODEL"), (
        "没指定模型 —— 不同凭证下默认模型不同(月租默认 haiku、API key 默认 opus),"
        "而两版跑在不同模型上就完全不可比。照文件头那条命令跑。")
    # 只跑一版:`AB_ONLY=A` / `AB_ONLY=B`。
    # ⚠️ **变量名必须 ASCII。** 第一版写的是 `AB只跑`,而 shell **不支持非 ASCII
    # 变量名** —— `AB只跑=B cmd` 在 zsh 里不报错、也不赋值,Python 那头
    # `os.environ.get("AB只跑")` 拿到 None,于是「只跑 B」静默变成「两版都跑」,
    # **又白烧了 A 版那 6 次调用**。
    # > 一条「环境变量没传进去」和一条「我本来就想两版都跑」,
    # > **在那份输出上长得一模一样** —— 它照样把 A 版跑得好好的。
    # 同一个坑 `tools/gate_lock.sh` 文件头警告过(它第一版用中文变量名,
    # 结果所有变量都是空的、在 `mkdir ""` 上无限打转)。注释和输出照旧中文,**变量名不行**。
    只跑 = (os.environ.get("AB_ONLY") or "").strip().upper()
    A = 跑一版("A", False, 轮) if 只跑 in ("", "A") else 读回("A")
    B = 跑一版("B", True, 轮) if 只跑 in ("", "B") else 读回("B")
    报 = dict(模型=os.environ.get("ANTHROPIC_MODEL"), 每版轮数=轮,
              A_现状点名=一版怎么样(A), B_不点名=一版怎么样(B),
              限定=["n = 3 题 × %d 轮 × 2 版,只分辨得出大差别;差一两题是抖动" % 轮,
                    "B 版掉分的两种原因(不知道该说 / 不知道哪种根因对应哪种后果)"
                    "在分数上分不开,要看原文",
                    "两版原文分别在 refund-prompt-ab-A.jsonl / -B.jsonl,没动基线文件"])
    out = os.path.join(HERE, "refund-prompt-ab-报告.json")
    io.open(out, "w", encoding="utf-8").write(json.dumps(报, ensure_ascii=False, indent=1) + "\n")
    print("\n" + json.dumps(报, ensure_ascii=False, indent=1))
    print(f"\n{G}报告{D} {out}")
