#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库路径单源 · 新代码不许再自己拼 lanxiu.db 的路径(执行手册 W02 第一步;存量登记成欠债,只许少不许多)

## 为什么要有这个
2026-11-17 盘点:133 个模块各自 `DB = os.path.join(HERE, "lanxiu.db")`,71 处直接 `sqlite3.connect(…lanxiu.db)`,
57 个检查用 82 处 `m.DB = 副本` 把它们一个个指到库副本上。漏指一个,检查就写进真库 ——
11-04「检查切库前先 import 写口」那次就是这么栽的,而那种错**没有任何检查会报**。
133 个一起改是一轮全量门禁、还会撞一批咬合锚,所以分三步走(执行手册 W02);这条守第一步:
**新代码走 `backend/dbpath.路径()`,老账只许少不许多。**

## 查什么
扫 git 跟踪的 .py(不含虚拟环境),数「自己拼**项目**库路径」的行:行里有 lanxiu.db,**且**用项目锚点拼
(HERE / ROOT / 根 / __file__ / os.path.dirname)。临时副本(tmp / 副本目录 / 随便一个 d)不算 —— 那本来就该各自拼。
期望值不是从代码算的,是**登记的存量**(`欠债下限`):比它多就红;比它少就提示把下限改小。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, R, D, Y = "\033[32m", "\033[31m", "\033[0m", "\033[33m"

豁免 = {"backend/dbpath.py", "tools/dbpath_check.py"}   # 单源本身,和这条检查自己(docstring 里举了例子)
欠债下限 = 224     # 2026-11-17 实测 327 处 / 290 个文件(含 DB = … 和直接 connect 两种写法);11-19 评测切库 / 夜跑那几处改走 dbpath.真库() 降到 324;11-23 写口四个(返修 / 退款 / 排班 / 标签等级)降到 303、读写六个(信用 / 归属 / 客户关联 / 接触点 / 商机 / 流失)降到 297、再六个(告警派发 / 到店卡 / 预约过期 / 工坊收件 / 知识问题 / 召回)降到 291、再六个(语音转写 / 示例池 / 文件 / 图片 / 纹样审核 / 查询索引)降到 285、再六个(订单合同 / 商品摘要 / 报告文档 / 报告模板 / 排班 / 定向运营)降到 279、建库 / 迁移 / 注册 / 改名 / 桥六个降到 273;11-24 费用提醒 / 简体对照 / 商机评测 / 归属释放 / 两个修数脚本六个降到 267;11-25 试衣 / 报价 / 评价 / 返修四个造数脚本降到 263、建库主脚本和签收造数降到 259、重建配方里六个回填(业务字段 / 颜色 / 信用 / 排班 / 场景 / 转写)降到 253、再五个回填(客户关联 / 商机 / 订单量体 / 条款 / 归因)降到 248、覆盖率 / 出图提示词导出 / 坏时间戳 / 支付流水号 / 夹具清理五个工具降到 243、造客户 / 历史修剪 / 档位历史 / 操作日志回挪 / 打版待办五个降到 238;11-26 重建配方里八个造数(流失 / 客户任务 / 派单 / 工坊来料 / 上新 / 待下单 / 接触历史 / 青少年同意)降到 230、出图原型 / 刷知识 / 收图三个降到 227、改期夹紧 / 每日上新 / 评价回填三个降到 224;降了就改小(只许少不许多)

行判 = re.compile(r"lanxiu\.db")
锚判 = re.compile(r"\b(HERE|ROOT|根|__file__)\b|dirname\(")


def 查(样本):
    """纯函数:样本 = [(路径, 源码)],回 ([(路径, 行号, 那一行)], 扫了几个文件)。注释掉的那半行不算。"""
    出 = []
    for p, s in 样本:
        if p in 豁免:
            continue
        for i, line in enumerate(s.split("\n"), 1):
            code = line.split("#", 1)[0]
            if 行判.search(code) and 锚判.search(code):
                出.append((p, i, code.strip()[:90]))
    return 出, len(样本)


def 自测():
    """人造夹具:好的不该红;坏的红且落在那一行;临时副本和注释不算;豁免的不算。"""
    bad = []
    出, n = 查([])
    if n != 0 or 出: bad.append("空样本该报 0 个")
    好 = [("backend/新模块.py", "from dbpath import 路径\nDB = 路径()\n"),
          ("backend/某检查.py", 'tmp = tempfile.mkdtemp()\nT = os.path.join(tmp, "lanxiu.db")\n'),
          ("backend/另一个.py", '# DB = os.path.join(HERE, "lanxiu.db")  注释里提一句不算\n'),
          ("backend/dbpath.py", 'return os.environ.get("LANXIU_DB") or os.path.join(HERE, "lanxiu.db")\n')]
    出, n = 查(好)
    if 出 or n != 4: bad.append(f"四个好样本不该红:{出}")
    坏 = 好 + [("backend/又拼了.py", 'import os\nHERE = os.path.dirname(__file__)\nDB = os.path.join(HERE, "lanxiu.db")\n'),
               ("tools/直连.py", 'c = sqlite3.connect(os.path.join(ROOT, "backend", "lanxiu.db"))\n')]
    出, n = 查(坏)
    if len(出) != 2 or {x[0] for x in 出} != {"backend/又拼了.py", "tools/直连.py"} or 出[0][1] != 3:
        bad.append(f"两个坏样本该各红一行、且落在拼路径那一行:{出}")
    return bad


def 取样本():
    r = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 and os.environ.get("LANXIU_SRC_ROOT"):
        # 咬合副本不带 .git(11-22 查实:这条咬合的对照因此一直是红的,样本 0 个)——
        # 文件清单向原检出要,**内容照旧读副本里的**(改坏的是副本)
        r = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "*.py"],
                           cwd=os.environ["LANXIU_SRC_ROOT"], capture_output=True, text=True)
    files = [f for f in r.stdout.split("\n") if f and "/.venv/" not in f and "node_modules" not in f]
    样本 = []
    for f in files:
        try:
            样本.append((f, open(os.path.join(ROOT, f), encoding="utf-8").read()))
        except Exception:
            pass
    return 样本


# ── 咬合记录(规格在 tools/bite_specs.json,bite_run 能重放)────────────────
咬合 = [
    ("给一个没有自己拼路径的模块加一行 DB = os.path.join(dirname(__file__), 'lanxiu.db')", "自己拼库路径的行比登记的欠债多"),
]


def main():
    print("库路径单源 · 新代码不许再自己拼 lanxiu.db 的路径(存量登记成欠债,只许少不许多)\n" + "=" * 72)
    bad = 自测()
    if bad:
        for b in bad: print(f"  {R}❌ {b}{D}")
        print(f"{R}❌ 自测没过,真跑不算数{D}"); return 1
    样本 = 取样本()
    出, n = 查(样本)
    文件数 = len({x[0] for x in 出})
    print(f"  样本量:扫了 {n} 个 .py(来路:git ls-files);自己拼项目库路径的行 {len(出)} 处、涉及 {文件数} 个文件;自测过")
    if n == 0:
        print(f"{R}❌ 一个都没扫到 —— 不是「都对」,是没东西可验{D}"); return 1
    按文件 = {}
    for p, _, _ in 出: 按文件[p] = 按文件.get(p, 0) + 1
    print("  拼得最多的:" + "、".join(f"{p}({c})" for p, c in sorted(按文件.items(), key=lambda x: -x[1])[:6]))
    坏 = []
    if len(出) > 欠债下限:
        坏.append(f"自己拼库路径的行比登记的欠债多:{欠债下限} → {len(出)} —— 新代码请用 backend/dbpath.路径()(检查切副本设 LANXIU_DB 或照旧 m.DB = 副本)")
        印 = 12
        for p, i, line in 出[:印]: print(f"       · {p}:{i}  {line[:70]}")
        if len(出) > 印: print(f"       …… 上面只印了 {印} 处,**一共 {len(出)} 处**")
    print(f"  {'❌' if 坏 else '✅'} 自己拼库路径:{len(出)} 处(欠债下限 {欠债下限})")
    if len(出) < 欠债下限:
        print(f"{Y}  ℹ️ 已经降到 {len(出)} 处了 —— 把本文件的 `欠债下限` 改成 {len(出)}(不改的话,下次有人加回来也不会红){D}")
    for x in 坏: print(f"{R}❌ {x}{D}")
    print(f"{G}✅ 库路径单源符合预期{D}" if not 坏 else "")
    return 1 if 坏 else 0


if __name__ == "__main__":
    sys.exit(main())
