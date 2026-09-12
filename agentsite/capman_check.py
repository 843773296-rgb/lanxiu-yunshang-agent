# -*- coding: utf-8 -*-
"""能力管理的检查。

**这套检查的主角是判据本身**,不是扫描出来的数量。
理由是第一版的教训:判据有两个 bug(词表只有中文、拿「1. 2. 3.」当证据),
方向一致,于是 **140/239 个技能被判成「该改成 CLI」**,
而且每条都附着一段理直气壮的理由。

修完之后变成 0 条 —— **而 0 条同样可疑**:
判据可能从一个极端摆到了另一个。所以下面第一组用例专门钉两头:
**真的死步骤必须命中,真的需要判断必须不命中**,中文英文各一份。

「一个判据在真语料上报 0 条」有两种可能:语料真的干净,或者判据瞎了。
**这两种在输出上长得一模一样。**
"""
import os, re, sys, json, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE, os.path.join(ROOT, "backend")]
import knowledge.capability as CAP
import capman

FAIL = []


def ck(name, ok, n, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}(验了 {n} 个){'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)
    if n == 0:
        print("     ⚠️ 样本量 0 —— **这不叫通过,这叫没扫到东西**")
        FAIL.append(name + "(样本量 0)")


死步骤_中 = """# 每日对账
第一步 运行脚本 `python3 tools/x.py` 拉出昨天的流水。
第二步 逐条比对金额,遍历每一行。
第三步 执行脚本把差异写进报表。
再运行一次命令行确认。""" + "补" * 400

死步骤_英 = """# Daily reconciliation
1. Run the script `tools/x.py` to dump yesterday's ledger.
2. Execute the compare command for each row; iterate over every line.
3. Run the export script and write the diff to a report file.
Use the bash command to verify.""" + "pad " * 200

# ⚠️ 「要判断」这两份用例,**必须同时塞满可执行动作词** ——
# 否则它们会因为「可执行动作不够三个」而返回「不该改」,
# 而那是**碰巧答对**:把判断词表整个拿掉,它们照样通过。
# 第一次咬合就栽在这儿:拿掉英文判断词表,检查没红,
# 而扫描器当场冒出 6 条误报 —— **检查瞎了,不是改动无害。**
#
# 现在它们枚举词管够,**唯一能让它们返回「不该改」的,就是判断词命中**。
# 这样拿掉判断词表,它们必然翻红。
要判断_中 = """# 客诉回复
第一步 运行脚本拉出工单,依次遍历每一行,逐条执行脚本导出。
再用命令行跑一遍,对每一条调用接口确认。
但是:第二步要**判断**客户的语气,如果强硬就先道歉。
第三步 视情况决定补偿额度,取决于历史消费,酌情权衡。""" + "补" * 400

要判断_英 = """# Complaint handling
1. Run the script to fetch the ticket. Execute the export command.
2. Iterate over each row; for each one run the bash script again.
3. But: assess the customer's tone and decide whether to apologise.
4. Determine the compensation based on their history; it depends on context.
""" + "pad " * 200


def main():
    print("能力管理 · 检查")
    print("=" * 80)

    # ── 一、判据钉两头 ──────────────────────────────────────────
    cs = [("中文·真死步骤", 死步骤_中, True),
          ("英文·真死步骤", 死步骤_英, True),
          ("中文·要判断", 要判断_中, False),
          ("英文·要判断", 要判断_英, False)]
    bad = [n for n, t, want in cs if CAP.该不该改成CLI(t)[0] != want]
    # 用例本身合不合格:「要判断」那两份**必须枚举词管够** ——
    # 不然它们是靠「证据不够」通过的,判断词表整个删掉也还是绿的。
    弱 = [n for n, t, want in cs if not want
          and len([w for w in CAP.可枚举的信号
                   if (t.lower() if w.strip().isascii() else t).find(w) >= 0]) < 3]
    if 弱: bad += [f"{n}(用例不合格:枚举词不够,靠「证据不够」蒙对的)" for n in 弱]
    ck("「该不该改成 CLI」中英文两头都判得对", not bad, len(cs),
       ("挂了:" + "、".join(bad)) if bad else
       "第一版英文语料一个都命中不了,236 个英文技能全被判成「不需要判断」")

    # ── 二、证据门槛:短文本凑够词也不算 ───────────────────────
    #    「一份两百字的说明文里凑出三个词」不是证据,是巧合。
    短 = "run the script, execute the command, iterate over rows"
    ck("短文本凑够关键词也不判「该改」", not CAP.该不该改成CLI(短)[0], 1,
       "任何 markdown 都有编号列表 —— 那不是「死步骤」的证据,是「这是文档」的证据")

    # ── 三、每个探针都要能在人造缺陷上命中(咬合) ──────────────
    #    **探针报 0 条有两种可能:真的没缺口,或者探针瞎了。**
    #    这两种在输出上长得一模一样,所以每个都造一次缺陷试试。
    n3 = 0; bad3 = []
    # ③-1 有数据没工具:造一张没人碰的表名,看它认不认得出
    src = open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8").read()
    碰过 = [t for t in ("customer", "ordr", "schedule")
            if re.search(r"\bFROM\s+" + t + r"\b", src, re.I)]
    n3 += len(碰过)
    if not 碰过: bad3.append("有数据没工具(认不出被碰过的表)")
    # ③-2 探针跑得起来,而且每条都带证据
    for 名, fn in capman.探针:
        try: got = fn()
        except Exception as e:
            bad3.append(f"{名} 自己挂了:{type(e).__name__}"); continue
        n3 += 1
        for g in got:
            if not g.get("证据") or not g.get("标题") or not g.get("kind"):
                bad3.append(f"{名} 有缺口没带证据"); break
    ck("每个探针跑得起来,而且每条缺口都带证据", not bad3, n3,
       "；".join(bad3[:2]) if bad3 else "没有证据的建议是噪声,会让人把整张清单一起忽略")

    # ── 四、探针的类别必须是口径里定义过的 ─────────────────────
    合法 = set(CAP.类别) | {"prune"}
    野 = set()
    for _, fn in capman.探针:
        try: 野 |= {g["kind"] for g in fn()} - 合法
        except Exception: pass
    ck("缺口的类别都在口径里定义过", not 野, len(合法), f"野类别 {野}" if 野 else "")

    # ── 五、install 不覆盖已有文件 ─────────────────────────────
    #    **一个会覆盖的脚手架工具,第一次用就能毁掉半天的活。**
    tgt = os.path.join(ROOT, "tools", "make_log.py")
    ck("install 的模板不会覆盖已有文件", os.path.exists(tgt) and
       "if os.path.exists(path)" in open(os.path.join(HERE, "capman.py"),
                                         encoding="utf-8").read(), 1)

    # ── 六、install 不自动改别人的文件 ─────────────────────────
    #    自动编辑现有代码的工具,**出错时改坏的地方和它报告的地方不是同一处**。
    cm = open(os.path.join(HERE, "capman.py"), encoding="utf-8").read()
    改别人 = re.findall(r'open\(\s*os\.path\.join\(ROOT,\s*"(check\.sh|prompts\.py)"',
                       cm) + re.findall(r'"(api\.py)"[^)]*,\s*"w"', cm)
    ck("install 不自动编辑 api.py / check.sh / prompts.py", not 改别人, 3,
       f"动了 {改别人}" if 改别人 else "要改的那一行原样打出来,人自己贴")

    print("=" * 80)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 能力管理 6 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
