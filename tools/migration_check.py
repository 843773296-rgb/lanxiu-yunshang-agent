#!/usr/bin/env python3
"""库结构迁移 · 加列只许走 backend/migrations/;散落的 ALTER TABLE 只许少不许多;做过的迁移不许改。

为什么:见 backend/migrate.py 开头(用户 11-14 清单第 ④ 条)。这条检查守四件事:
  ① **新代码不许在迁移目录外面写 ALTER TABLE** —— 现存的按文件登记成欠债(棘轮),修掉一处就把数减一;
     少了却不改登记也红(豁免不许囤积 —— 囤着的和真欠着的在绿勾上长得一样)
  ② 迁移编号从 1 连续(真调 migrate.迁移们(),不在这里重写一份规则)
  ③ 迁移机制自测(真跑 migrate.py --自测:补齐 / 幂等 / 缺表不崩 / 失败回滚 / 改过能认出 / 跳号被拒)
  ④ 这台机器的库:做到了最新、做过的迁移文件没被改过 —— 「代码到了、列没到」正是要抓的那种
数法:AST 里**非文档字符串**的字符串字面量(含 f-string)里出现 ALTER TABLE 算一处 —— 注释和说明文字不算。

    python3 tools/migration_check.py
"""
import ast
import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import migrate  # noqa: E402

R, G, Y, D = "\033[31m", "\033[32m", "\033[33m", "\033[0m"
样本下限 = 350      # 11-14 实测 415 个 .py(不含检查 / 测试 / 管理后台)。掉到几百 = 检查自己瞎了(git ls-files 失败 / 路径错),不是代码变好了

# 不扫的:检查 / 测试(给临时库造夹具,不是给真库改结构)、迁移机制自己、另一套库(管理后台走它自己的 PG 迁移)
def 不扫(f):
    b = os.path.basename(f)
    return (f.startswith(("管理后台/", "backend/migrations/")) or f == "backend/migrate.py"
            or b.endswith(("_check.py", "_test.py", "_judgetest.py")) or b.startswith("test_"))

# 2026-11-14 实测的存量(文件 → 字面量处数)。**只许少不许多**:收进迁移一处,就把这里减一;减到 0 删掉那一行。
欠债 = {
    "agent/fingerprint.py": 1,          # 自测里在临时库上改列名,造「库结构变了」的样本 —— 不碰真库
    "backend/arrival_card.py": 2,
    "backend/asr.py": 5,                # 其中 _补列 已被 m0001 原样调用;函数还在原处(双保险)
    "backend/fix_advisor_ref.py": 2,
    "backend/fix_product_pattern.py": 1,
    "backend/merge.py": 1,              # _确保列 已被 m0001 调用
    "backend/opportunity_store.py": 1,
    "backend/ops.py": 5,                # 三个 _确保…列 已被 m0001 调用
    "backend/order_contract.py": 2,
    "backend/ownership_release.py": 1,
    "backend/refund_write.py": 1,
    "backend/relabel.py": 2,            # 确保列 已被 m0001 调用
    "backend/report_doc.py": 2,
    "backend/report_template.py": 2,
    "backend/seed.py": 1,
    "backend/seed_rating.py": 2,        # _补列 已被 m0001 调用
    "backend/seed_repair.py": 3,
    "backend/terms_store.py": 1,
    "backend/triage_config.py": 1,
    "fakedata/mkt_sop_seed.py": 1,
    "tools/add_cust_advisor.py": 2,
    "tools/add_shop_code.py": 4,
    "tools/migrate_appt_columns.py": 2,
    "tools/migrate_order_wearer.py": 1,
    "tools/seed_new_products.py": 1,
}


def 数(src):
    t = ast.parse(src)
    文档 = {id(n.value) for n in ast.walk(t)
           if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
    k = 0
    for n in ast.walk(t):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in 文档 and "ALTER TABLE" in n.value.upper():
            k += 1
        elif isinstance(n, ast.JoinedStr) and any(isinstance(v, ast.Constant) and "ALTER TABLE" in str(v.value).upper()
                                                 for v in n.values):
            k += 1
    return k


def 扫(根=ROOT):
    fs = subprocess.run(["git", "-C", 根, "ls-files", "*.py"], capture_output=True, text=True).stdout.split()
    fs += subprocess.run(["git", "-C", 根, "ls-files", "--others", "--exclude-standard", "*.py"],
                         capture_output=True, text=True).stdout.split()
    if not fs:
        # 咬合重放在**不带 .git 的副本**上跑,git 列不出文件 —— 退回遍历目录(否则样本 0,对照组恒红)。
        # 跳过的目录对齐 bite_run 副本不带 / 不该扫的那些
        for 根目录, 目录们, 文件们 in os.walk(根):
            目录们[:] = [d for d in 目录们 if d not in (".git", ".venv", "node_modules", "__pycache__", ".claude", "管理后台")]
            for n in 文件们:
                if n.endswith(".py"):
                    fs.append(os.path.relpath(os.path.join(根目录, n), 根))
    见, 崩, 结果 = 0, [], {}
    for f in sorted(set(fs)):
        if 不扫(f):
            continue
        try:
            src = open(os.path.join(根, f), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        见 += 1
        try:
            k = 数(src)
        except SyntaxError:
            崩.append(f); continue
        if k:
            结果[f] = k
    return 见, 崩, 结果


def 比(结果, 欠债):
    """(多了的, 少了没改登记的):多了 = 新文件或比登记多;少了 = 比登记少(含整个文件清掉了)。"""
    多 = [(f, k, 欠债.get(f, 0)) for f, k in sorted(结果.items()) if k > 欠债.get(f, 0)]
    少 = [(f, 结果.get(f, 0), v) for f, v in sorted(欠债.items()) if 结果.get(f, 0) < v]
    return 多, 少


def main():
    坏 = 0
    print("库结构迁移 · 加列走迁移目录、散落的只许少不许多、做过的迁移不许改")
    见, 崩, 结果 = 扫()
    print(f"  样本量:扫了 {见} 个 .py(git ls-files + 未跟踪;不含检查 / 测试 / 迁移目录 / 管理后台),语法崩 {len(崩)} 个")
    if 见 < 样本下限:
        print(f"  {R}❌ 只扫到 {见} 个(下限 {样本下限})—— 检查自己瞎了,不是代码变好了{D}"); 坏 += 1
    if 崩:
        print(f"  {R}❌ 解析不了的文件:{崩[:5]}{'…' if len(崩) > 5 else ''}(数不了 = 没验过,不是 0 处){D}"); 坏 += 1
    多, 少 = 比(结果, 欠债)
    总 = sum(结果.values())
    if 多:
        坏 += 1
        print(f"  {R}❌ 迁移目录外面多出了 ALTER TABLE(现在 {总} 处,登记 {sum(欠债.values())} 处):{D}")
        for f, k, v in 多:
            print(f"       · {f}:{k} 处(登记 {v})—— 加列请写成 backend/migrations/mNNNN_名字.py 的 up(c)")
    else:
        print(f"  {G}✅{D} 迁移目录外面没有新的 ALTER TABLE(存量 {总} 处在 {len(结果)} 个文件,全在登记里)")
    if 少:
        坏 += 1
        print(f"  {R}❌ 有欠债已经还了却没改登记 —— 把 tools/migration_check.py 的「欠债」照实改小:{D}")
        for f, k, v in 少:
            print(f"       · {f}:现在 {k} 处,登记 {v}")
    else:
        print(f"  {G}✅{D} 登记里没有囤着的(验了 {len(欠债)} 条,每条都还对得上)")
    try:
        全 = migrate.迁移们()
        print(f"  {G}✅{D} 迁移编号从 1 连续:{[f'{v}:{n}' for v, n, *_ in 全]}")
    except SystemExit as e:
        坏 += 1; print(f"  {R}{e}{D}")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "backend", "migrate.py"), "--自测"], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  {G}✅{D} 迁移机制自测过(补齐 / 幂等 / 缺表不崩 / 失败回滚 / 改过能认出 / 跳号被拒)")
    else:
        坏 += 1; print(f"  {R}❌ 迁移机制自测 rc={r.returncode}{D}\n{r.stdout[-800:]}{r.stderr[-800:]}")
    if os.path.exists(migrate.DB):
        c = sqlite3.connect(migrate.DB)
        有表 = c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
        if not 有表:
            坏 += 1; print(f"  {R}❌ 这台机器的库还没有 schema_version —— 跑 `python3 backend/migrate.py`(重建流水线会自动跑){D}")
        else:
            差, 改 = migrate.对账(c)
            if 差 or 改:
                坏 += 1
                print(f"  {R}❌ 库没做到最新:还差 {[v for v, *_ in 差]} · 做过后被改过 {[v for v, _ in 改]} —— "
                      f"还差就跑 `python3 backend/migrate.py`;被改过请把改动挪成新的一条迁移{D}")
            else:
                print(f"  {G}✅{D} 这台机器的库做到了第 {len(migrate.迁移们())} 条,做过的迁移文件都没改过")
        c.close()
    else:
        print(f"  {Y}⏸ 没有库({migrate.DB})—— 「库做到最新」这一项**不适用,不是通过**{D}")
    print(f"\n{G}✅ 库结构迁移检查全过{D}" if not 坏 else f"\n{R}❌ 库结构迁移检查 {坏} 项不过{D}")
    sys.exit(1 if 坏 else 0)


if __name__ == "__main__":
    main()
