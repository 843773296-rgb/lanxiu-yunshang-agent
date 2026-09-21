#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《待办清单.md》—— **从 `intent/` 和库里现算,不手写。**

业务要一份「还有哪些没做」的文本。手写一份的下场这个项目见过:
`HANDOFF.md` 里那条「22 个形制没录」**早已清零,却在文档里挂了很久**,
而下一个人会照着去重做。

所以这份清单:

  **条目**   从 `intent/*.md` 读 —— 那是「这件事本身是什么」的唯一来源
  **数字**   从库里 / 检查里**现算** —— 欠多少条、还剩几个,一律不写死
  **顺序**   按「谁能动」分组:**要业务拍板的** / **等外部数据的** / **我能做的**

> 手写的清单会漂,而漂了不报错 —— 它只是安静地把一件做完的事留在上面。
"""
import datetime, glob, os, re, sqlite3, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "待办清单.md")


def _db():
    c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))
    c.row_factory = sqlite3.Row
    return c


def 现算():
    """每一条待办**现在**的数 —— 键是 intent 的文件名。"""
    d, c = {}, _db()
    try:
        # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
        n = c.execute("SELECT COUNT(*) FROM pattern_piece WHERE ratio IS NOT NULL").fetchone()[0]
        # 数的是登记行数(裁片**种类**数),不是要裁几块 —— 一片 qty=2 在表里也只有一行
        k = c.execute("SELECT COUNT(*) FROM pattern_piece WHERE ratio_src='版师'").fetchone()[0]
        d["piece-ratio-review"] = f"**{k}/{n}** 片到「版师核过」档(其余全是「复核」:规则核过、数没核过)"
    except Exception: pass
    try:
        sys.path.insert(0, os.path.join(ROOT, "knowledge"))
        import source as S
        欠 = sum(1 for r in c.execute("SELECT src_type,src_name,src_url FROM craft")
                 if not S.溯源(r["src_type"], r["src_name"], r["src_url"])[0])
        总 = c.execute("SELECT COUNT(*) FROM craft").fetchone()[0]
        d["knowledge-source-debt"] = f"还欠 **{欠}/{总}** 条(首次扫出 46,已还到这个数)"
    except Exception: pass
    try:
        童 = c.execute("SELECT COUNT(DISTINCT pattern) FROM size_spec WHERE caveat LIKE '%身高码%'").fetchone()[0]
        无幅 = c.execute("SELECT COUNT(*) FROM material WHERE width_cm IS NULL AND cat IN ('里料','衬料')").fetchone()[0]
        特体 = c.execute("SELECT COUNT(DISTINCT wearer_id) FROM body_feature").fetchone()[0]
        d["pattern-knowledge-gaps"] = (f"童装档差 **{童}** 个版型等着重推;"
                                       f"里料/衬料 **{无幅}** 种没门幅;"
                                       f"**{特体}** 位着装人有体型特征而无修版量")
    except Exception: pass
    try:
        九 = 0
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if any(x[1] == "advisor" for x in c.execute(f"PRAGMA table_info({t})")): 九 += 1
        d["advisor-columns"] = f"**{九}** 张表的名字列还留着(引用已全部建好,删列要先改 38 个页面)"
    except Exception: pass
    try:
        sh = open(os.path.join(ROOT, "check.sh"), encoding="utf-8").read()
        脚本 = set(re.findall(r"run .*?([\w/]+\.py)", sh))
        无 = sum(1 for m in 脚本
                 if os.path.isfile(os.path.join(ROOT, m))
                 and "\n咬合 = [" not in open(os.path.join(ROOT, m), encoding="utf-8").read())
        d["judge-audit"] = f"**{无}/{len(脚本)}** 个检查脚本还没写咬合记录"
    except Exception: pass
    c.close()
    return d


def 读(p):
    t = open(p, encoding="utf-8").read()
    题 = re.search(r"^#\s+(.+)$", t, re.M)
    def 取(k):
        m = re.search(rf"- \*\*{k}\*\*[::]\s*(.+?)(?=\n- \*\*|\Z)", t, re.S)
        if not m: return ""
        # ⚠️ **要把 intent 里的缩进剥掉。**
        # intent 文件里那几段是挂在 `- **要解决什么**:` 下面的,每行缩进两格;
        # 原样搬进新文档,markdown 会**把它们渲染成代码块** ——
        # 表格不成表格、加粗不加粗。生成的文档不是复制粘贴,**是重排版**。
        行 = m.group(1).split("\n")
        出 = [行[0].strip()]
        for x in 行[1:]:
            y = x[2:] if x.startswith("  ") else x
            出.append(y.rstrip())
        return "\n".join(出).strip()
    状 = re.search(r"\*\*状态\*\*[::]\s*`?([^`\n((]+)`?", t)
    return dict(name=os.path.basename(p)[:-3],
                题=(题.group(1) if 题 else os.path.basename(p)),
                状态=(状.group(1).strip() if 状 else "(没写)"),
                要解决=取("要解决什么"), 不做=取("明确不做什么"), 做完=取("怎么算做完"))


分组 = {
    "等人的活": ("① 要人做的 —— 我做不了,或不该替你做",
                "这几件**不是技术待办**。有的要业务拍板,有的要外部资料,"
                "有的是某个岗位本身的活。**替它猜出来的东西会一直被当成真的用。**"),
    "进行中":   ("② 我能接着做的", "有明确的完成判据,而且判据已经有检查盯着。"),
    "做完了":   ("③ 已经做完的(留档,别重做)",
                "**写在这儿是因为「做完了却还挂着」真的发生过**:"
                "「22 个形制没录」那条在交接文档里挂了很久,而它早已清零。"),
    "已否决":   ("④ 拍过板的「不做」", "**「还没做」和「决定不做」在代码里长得一模一样**,所以分开列。"),
}


def main():
    live = 现算()
    items = [读(p) for p in sorted(glob.glob(os.path.join(ROOT, "intent", "*.md")))
             if not p.endswith("README.md")]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    L = [f"# 待办清单",
         "",
         f"> **这份文件是生成的,不要手改** —— `python3 tools/make_todo.py`。",
         f"> 条目来自 `intent/`,数字**从库里现算**。",
         f"> 生成于 {datetime.datetime.now():%Y-%m-%d %H:%M} · 代码 `{head}`",  # 真实时钟:写的是 md 的生成时间,不进库
         "",
         "手写的清单会漂,而漂了不报错 —— 它只是安静地把一件做完的事留在上面。",
         "这个项目为这件事栽过:「22 个形制没录」在交接文档里挂了很久,**而它早已清零**。",
         ""]
    for 状, (标题, 说明) in 分组.items():
        这组 = [x for x in items if x["状态"] == 状]
        if not 这组: continue
        L += ["---", "", f"## {标题}", "", 说明, ""]
        for x in 这组:
            L += [f"### {x['题']}", ""]
            if x["name"] in live:
                L += [f"**现在的数**:{live[x['name']]}", ""]
            if x["要解决"]: L += ["**要解决什么**", "", x["要解决"], ""]
            if x["不做"]:   L += ["**明确不做什么**", "", x["不做"], ""]
            if x["做完"]:   L += ["**怎么算做完**", "", x["做完"], ""]
    L += ["---", "",
          f"共 {len(items)} 条。每一条的完整来龙去脉在 `intent/<名字>.md`,",
          "而「现在停在哪」在 `HANDOFF.md` —— **前者不该变,后者随时在变**。"]
    open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"生成 {OUT}:{len(items)} 条")
    for 状, (标题, _) in 分组.items():
        n = sum(1 for x in items if x["状态"] == 状)
        if n: print(f"   {标题.split('——')[0].strip():28} {n} 条")


if __name__ == "__main__":
    main()
