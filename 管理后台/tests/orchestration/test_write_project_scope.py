#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写入侧跨项目隔离:每一句 UPDATE / DELETE 打到带 project_id 的表,条件里都要有 project_id(2026-11-05)。不要数据库。

## 为什么

原来交接里写「写入侧是结构:跨项目引用撞复合外键」—— 那只挡得住**把别家的记录挂进来**,
挡不住一句 `update … where id=:i` 漏了 project_id、**直接改掉别家项目的那一行**(取消别人的运行、改别人的评测状态)。
读取那一侧有按真路由表的攻击(test_cross_project_read);写入这一侧走 HTTP 攻不全:大多数写接口没有合法的请求体
在校验那一步就回 422,碰不到库 —— 「没改到」就分不清是隔离挡的还是校验挡的。

所以改查**源码里的每一句写 SQL**(AST 取字符串,**整句判,不按行** —— 多行 SQL 的条件常在下一行,按行扫会误报,
误报多了就有人放宽,放宽了真漏的也不报):句子打到的表要是带 project_id 的,那一句里就得出现 project_id。
新写的代码自动在扫的范围里,不靠人记得补。

  · 带 project_id 的表从 models.metadata 现读(和建表同一个来源),不写死
  · docstring 不算 SQL(里面常拿 `UPDATE … WHERE id=:i` 举例说明)
  · 真有理由不带的,登记在 豁免 里(棘轮:新冒出来没登记的 → 红;登记了但已经带上 / 那句没了 → 也红,逼人回来删)

已知不盖:运行时拼出来的表名(f-string 里表名是变量)、ORM 写法(这个后台全是 text() 手写 SQL)。
"""
import ast
import glob
import os
import re
import sys

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(_根, "services", "api", "app"), os.path.join(_根, "services", "api", "app", "contract")]
import models as MD  # noqa: E402

过, 挂 = [], []
句型 = re.compile(r"\b(update|delete\s+from)\s+\"?([a-z_][a-z0-9_]*)\"?", re.I)
# 登记:「文件:表」→ 理由。新的不许不写理由就加
豁免 = {}
# 试纸:逼出这条判据的那一种写法,判据要扫得到它(扫不到 = 判据的视野漏了,不是仓库干净)
试纸 = '''
def f(c, eid):
    c.execute(text("""update evaluations set status='已完成',
                      updated_at=now(), revision=revision+1 where id=:i"""), {"i": eid})
'''


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:500]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def _docstring们(树):
    ids = set()
    for n in ast.walk(树):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                ids.add(id(b.value))
    return ids


def 扫(src, 带项目):
    """→ (写语句数, [(行号, 表, 句子)]):打到带 project_id 的表、条件里却没有 project_id 的写语句。"""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        树 = ast.parse(src)
    文档 = _docstring们(树)
    总, 漏 = 0, []
    for n in ast.walk(树):
        if id(n) in 文档:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            段 = n.value
        elif isinstance(n, ast.JoinedStr):
            段 = "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{…}" for v in n.values)
        else:
            continue
        for m in 句型.finditer(段):
            表 = m.group(2).lower()
            if 表 not in 带项目:
                continue
            句 = 段[m.start():].split(";")[0]
            if not re.search(r"\bwhere\b", 句, re.I):
                continue
            总 += 1
            if "project_id" not in 句.lower():
                漏.append((getattr(n, "lineno", 0), 表, " ".join(句.split())[:120]))
    return 总, 漏


def main():
    带项目 = {t.name for t in MD.metadata.tables.values() if "project_id" in t.c}
    print(f"  ℹ️ 带 project_id 的表 {len(带项目)} 张(从 models 现读)")
    ck("带 project_id 的表不少于 60 张(从 models 现读;读少了就是表来源那一步坏了)", len(带项目) >= 60, len(带项目))

    _, 试 = 扫(试纸, 带项目)
    ck("判据自检:逼出这条判据的那一句(评测收尾 update … where id=:i)扫得到", len(试) == 1 and 试[0][1] == "evaluations", 试)

    文件们 = sorted(set(glob.glob(os.path.join(_根, "services", "api", "app", "**", "*.py"), recursive=True)
                     + glob.glob(os.path.join(_根, "workers", "**", "*.py"), recursive=True)
                     + glob.glob(os.path.join(_根, "tools", "*.py"))))
    文件们 = [f for f in 文件们 if "/.venv/" not in f and "__pycache__" not in f]
    总, 漏们, 坏 = 0, {}, []
    for f in 文件们:
        try:
            n, 漏 = 扫(open(f, encoding="utf-8").read(), 带项目)
        except SyntaxError as e:
            坏.append((os.path.relpath(f, _根), str(e)[:60]))
            continue
        总 += n
        for 行, 表, 句 in 漏:
            漏们[f"{os.path.relpath(f, _根)}:{表}"] = (行, 句)
    print(f"  ℹ️ 扫了 {len(文件们)} 个源文件、{总} 句打到带项目表的写语句")
    ck("源文件都解析得了(**解析不了 = 没扫到,不是没问题**)", not 坏, 坏)
    ck("扫到的写语句不少于 80 句(防「一句都没扫到所以一句都没漏」)", 总 >= 80, 总)
    新 = {k: v for k, v in 漏们.items() if k not in 豁免}
    ck("**每一句 UPDATE / DELETE 打到带项目的表,条件里都有 project_id**(没有又没登记理由 → 红)", not 新,
       [f"{k} 第{v[0]}行:{v[1]}" for k, v in 新.items()])
    ck("登记的豁免还都成立(那句已经带上 project_id / 已经没了 → 从 豁免 里删掉,豁免不许囤积)",
       not (set(豁免) - set(漏们)), sorted(set(豁免) - set(漏们)))

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 写入侧跨项目隔离:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
