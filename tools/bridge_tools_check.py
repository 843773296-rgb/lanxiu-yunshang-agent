# -*- coding: utf-8 -*-
"""澜绣桥名单 · 两边一致,而且读写分得对(2026-10-24,六条业务工作流要的能力)。

两份名单:
  · 管理后台 `services/api/app/runtime/桥工具.py` 的 只读 / 要批准 —— 库约束、桥闸、worker 路由都从它取
  · 澜绣 `backend/workflow_bridge.py` 的执行表(取转写 / 写跟进 + 业务工具)—— 真去执行的那一份
对不上的后果,都不报错:
  · 管理后台有、澜绣没有 → 工作流能配、能记单,澜绣回「不接」,运行在半路失败
  · 澜绣有、管理后台没有 → 这项能力白接了,库约束记不进单
  · **一个写口被放进了管理后台的「只读」** → 桥闸放行,**不经人工核对就写进澜绣** —— 这是最要紧的一条
读写以澜绣自己的 `api.WRITE_TOOLS` 为准(那张表是隔离 / 写闸 / 漏斗共用的唯一登记),不以任何一边手写的分组为准。
只读源码取两份名单(管理后台那边要 sqlalchemy,不 import)。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏 = []

咬合 = [
    ("把一个写口(assign_task)从「要批准」挪进管理后台的「只读」", "管理后台「只读」里没有写口(放进去就不经核对写进澜绣)"),
    ("澜绣执行表多接一个管理后台名单里没有的工具", "两边名单一样(澜绣能执行的 == 管理后台能记单的)"),
]


def ck(名, ok, 附=""):
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {附}" if 附 and not ok else ""))
    if not ok:
        坏.append(名)


def _字面(路径, 名):
    树 = ast.parse(open(路径, encoding="utf-8").read())
    for 节 in ast.walk(树):
        if isinstance(节, ast.Assign) and any(getattr(t, "id", None) == 名 for t in 节.targets):
            return ast.literal_eval(节.value)
    raise SystemExit(f"{路径} 里找不到 {名} 的字面量 —— 这条判据读不到东西,不算通过")


def _迁移名单():
    """迁移链上最近一次定义 ck_bridge_calls_tool_name 的那一版里,名单是什么。"""
    import glob, re
    版 = {}
    for f in glob.glob(os.path.join(ROOT, "管理后台", "services", "api", "migrations", "versions", "*.py")):
        t = open(f, encoding="utf-8").read()
        rv = re.search(r"^revision[^=]*=\s*['\"]([^'\"]+)", t, re.M)
        dn = re.search(r"^down_revision[^=]*=\s*['\"]([^'\"]+)", t, re.M)
        if rv:
            版[rv.group(1)] = (dn.group(1) if dn else None, t)
    被指 = {v[0] for v in 版.values()}
    头 = [k for k in 版 if k not in 被指]
    if len(头) != 1:
        return None
    k = 头[0]
    while k in 版:
        下, t = 版[k]
        if "ck_bridge_calls_tool_name" in t:
            m = re.search(r"^_新 = (\(.*?\))\n", t, re.M | re.S)
            if m:
                return set(ast.literal_eval(m.group(1)))
            m = re.search(r"tool_name in \(([^)]*)\)", t)
            return set(re.findall(r"'([^']+)'", m.group(1))) if m else None
        k = 下
    return None


def main():
    print("澜绣桥名单 · 管理后台和澜绣两边一致、读写分得对")
    后台 = os.path.join(ROOT, "管理后台", "services", "api", "app", "runtime", "桥工具.py")
    只读, 要批准 = set(_字面(后台, "只读")), set(_字面(后台, "要批准"))
    _桥 = os.path.join(ROOT, "backend", "workflow_bridge.py")
    专用 = set(_字面(_桥, "专用工具"))           # 桥专门做的(取转写 / 写跟进 / 订单交付风险 / 召回名单 / 派回访任务),不在 api.TOOLS 里
    澜绣 = set(_字面(_桥, "业务工具")) | 专用
    import api
    写口 = set(api.WRITE_TOOLS) | {"写跟进", "派回访任务"}   # 桥专门做的两个写,不在 api 里(专用工具里只有它俩会写)
    print(f"  管理后台:只读 {len(只读)} · 要批准 {len(要批准)} ;澜绣执行表 {len(澜绣)}")
    if not (只读 and 要批准 and 澜绣):
        ck("两边名单都读到了东西", False, "有一边是空的 —— 没东西可比,不算通过")
    else:
        ck("两组不重叠(一个名字既只读又要批准,闸不知道按哪个判)", not (只读 & 要批准), sorted(只读 & 要批准))
        ck("两边名单一样(澜绣能执行的 == 管理后台能记单的)", 澜绣 == (只读 | 要批准),
           f"只在管理后台:{sorted((只读 | 要批准) - 澜绣)} · 只在澜绣:{sorted(澜绣 - 只读 - 要批准)}")
        ck("管理后台「只读」里没有写口(放进去就不经核对写进澜绣)", not (只读 & 写口), sorted(只读 & 写口))
        ck("管理后台「要批准」的都真是写口(只读的放进去,只是多一道没必要的核对 —— 但说明分组在漂)",
           要批准 <= 写口, sorted(要批准 - 写口))
        ck("名单里的业务工具在澜绣都真存在(api.TOOLS)",
           not [n for n in 澜绣 - 专用 if n not in api.TOOLS], [n for n in 澜绣 - 专用 if n not in api.TOOLS])
        # 库约束:模型里的 CHECK 从名单生成,但 alembic 不比较 CHECK 的内容 —— 改了名单忘了写迁移,
        # 新库(CI / 别人的机器)上的约束还是旧名单,记新工具的单会在库里被拒。沿迁移链从头往回找最近改它的那一版
        ck("最近一次改库约束的迁移,名单和现在一字不差(改了名单要连迁移一起写)",
           (_迁移名单() or set()) == (只读 | 要批准), f"迁移里:{sorted(_迁移名单() or [])}")
    print()
    if 坏:
        print(f"{R}❌ 澜绣桥名单 {len(坏)} 处不对{D}")
        return 1
    print(f"{G}✅ 澜绣桥名单两边一致、读写分得对({len(只读 | 要批准)} 项){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
