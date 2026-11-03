#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼进 URL 的查询参数名不许是中文字面量 —— 要么用统一转码的出口,要么写成 %XX。

## 为什么有这一条(2026-11-03 端到端真跑撞到)

`backend/takeover_client.取回复` 拼的是 `/replies?澜绣工号=…`:参数名原样带着中文字节交给 curl,
管理后台(uvicorn)直接回 400「Invalid HTTP request」—— 聊天里追问「工作流怎么样了」**从来没取到过进度**。
单测把整个 `_curl` 换成了假的,所以一直绿。
> 一个「测过了」和一个「测的是假的那一段」,在绿勾上长得一模一样。

修法在出口:`takeover_client._curl` 统一转码(那一处由 agentsite/takeover_check.py 真调着验)。
这一条管的是**别处**:项目里还有好几个地方自己拼 curl / urllib 去打管理后台(spans_push、api 里那段……),
下一个中文参数名不一定走 `_curl`。所以查**结构**:Python 源码里的字符串(含 f-string 的字面量段)
出现 `?中文=` / `&中文=` 就红 —— 不枚举哪个参数名、不管它最后发给谁。

## 判据

- 只认**参数名**是中文的形状(`[?&]中文+=`)。参数**值**是中文不在这里管:值几乎都是变量,
  而且 backend 自己的 http.server 收得下;真正炸的是参数名写死在字面量里、又走了没转码的路。
- 用 AST 取字符串,不用正则扫行:f-string 里嵌着 `quote(x, safe='')` 这种带引号的表达式,
  行级正则会把它切碎、**恰好漏掉 11-03 那一行**(第一版就是这么漏的,试纸当场没扫到)。
- 棘轮:现存的登记成欠债(`欠债`),只许少不许多;修好的必须从欠债里删掉(反向检查)。

## 覆盖面的边界(并行会话 11-03 指出;登记成欠债)

这条只抓**源码里写出来的**中文参数名。**运行时拼出来的**(参数名是变量 / 常量)抓不到 ——
那一类只由 `takeover_client._curl` 出口统一转码兜住(agentsite/takeover_check.py 真调着验);
**不走 `_curl` 的出口**(api.py 里自己拼 curl 那段、tools/spans_push.py)目前没人兜。
所以它防的是「下一个人照抄字面量写法」,不是「任何中文参数名都会被逮住」。

## 试纸

`试纸` 是 11-03 出事那一行的原样。判据先扫它,**扫不到就红** —— 那说明判据瞎了,不是仓库干净。
"""
import ast
import os
import warnings
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G, R, D = "\033[32m", "\033[31m", "\033[0m"

中文 = r"[㐀-鿿]"
规则 = re.compile(rf"[?&]{中文}+=")

# 11-03 出事那一行(backend/takeover_client.py 取回复,a04199ce 之前)。原样,不改写。
试纸 = '''码, 体 = _curl("GET", f"/chat-takeovers/runs/{quote(rid, safe='')}/replies?澜绣工号={quote(str(澜绣工号 or ''), safe='')}", cfg)'''

# 现存的欠债:「文件 → 命中的字面量段」。只许少不许多;修好了要从这里删(否则反向检查红)。
欠债 = {
    # 这一份发请求走自己的 打():`urllib.parse.quote(路, safe="/?&=:%")` 统一转码,所以发出去是对的;
    # 登记在这里是因为判据只看字面量、看不出它走了哪个出口。改成 %XX 或别的写法后从这里删掉
    "管理后台/tests/e2e/test_chat_assistant_flow.py": ("/chat-assistants?含测试=true", "/switches?天=1"),
}

咬合 = [
    ("把 规则 改成永远匹配不到的东西", "判据自检:11-03 出事那一行扫得到"),
]


def 扫(src):
    """→ [(行号, 命中的字面量段)]。f-string 只看字面量段 —— 表达式里的东西不是 URL 的一部分。"""
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # 别人源码里的无效转义告警,不是这条判据的事,别刷屏
        树 = ast.parse(src)
    for n in ast.walk(树):
        段们 = []
        if isinstance(n, ast.JoinedStr):
            段们 = [v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            段们 = [n.value]
        for 段 in 段们:
            if 规则.search(段) and (n.lineno, 段) not in out:
                out.append((n.lineno, 段))
    return out


def main():
    print("URL 查询参数名 · 不许中文字面量(11-03:中文参数名原样发出,管理后台回 400)")
    print("=" * 76)
    坏 = []

    命中 = 扫(试纸)
    ok = bool(命中)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} 判据自检:11-03 出事那一行扫得到  {命中 if ok else '一处都没扫到 —— 判据瞎了,不是仓库干净'}")
    if not ok:
        坏.append("判据自检")

    # -z + quotepath=off:不然带中文的路径会被 git 转成 "\345\267…" 带引号的样子,一大半文件打不开 ——
    # 第一版就是这样,284 个文件没扫到,而判据照样绿(「没扫到」和「扫了没问题」长得一样)
    文件们 = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", "*.py"], cwd=ROOT,
                         capture_output=True, text=True).stdout.split("\0")
    文件们 = [f for f in 文件们 if f]
    来源 = "git 跟踪的"
    if not 文件们:
        # 不是 git 仓库(咬合执行器的副本就没有 .git)→ 退回直接走目录。**不退的话一个都没扫到,
        # 欠债表里的每一条都会被当成「已经修好了」**(第一版在副本里就是这样红的)
        来源 = "目录里的"
        跳过 = {".git", ".claude", "node_modules", ".venv", "venv", "__pycache__"}
        for 根, 目录们, 名们 in os.walk(ROOT):
            目录们[:] = [x for x in 目录们 if x not in 跳过]
            文件们 += [os.path.relpath(os.path.join(根, n), ROOT) for n in 名们 if n.endswith(".py")]
    文件们 = [f for f in 文件们 if not f.startswith(".claude/")]
    # 跳过自己:这个文件里的试纸和欠债表**故意**写着中文参数名(扫自己只会扫到自己的举例)
    自己 = os.path.relpath(os.path.abspath(__file__), ROOT)
    文件们 = [f for f in 文件们 if os.path.normpath(f) != os.path.normpath(自己)]
    扫了, 读不了, 现在 = 0, [], {}
    for f in 文件们:
        try:
            src = open(os.path.join(ROOT, f), encoding="utf-8").read()
            h = 扫(src)
        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            读不了.append(f"{f}({type(e).__name__})"); continue
        扫了 += 1
        for 行, 段 in h:
            现在.setdefault(f, set()).add(段)
    新增 = {f: sorted(s - set(欠债.get(f, ()))) for f, s in 现在.items()}
    新增 = {f: s for f, s in 新增.items() if s}
    修好 = {f: sorted(set(s) - 现在.get(f, set())) for f, s in 欠债.items()}
    修好 = {f: s for f, s in 修好.items() if s}

    ok = not 新增
    条 = "; ".join(f"{f}: {s[:2]}" for f, s in list(新增.items())[:5])
    多 = f"(还有 {len(新增) - 5} 个文件没列出)" if len(新增) > 5 else ""
    print(f"  {G + '✅' + D if ok else R + '❌' + D} 没有新增的中文查询参数名(扫了 {扫了} 个源文件)"
          + ("" if ok else f"  {条}{多} —— 参数名用 %XX,或走会统一转码的出口(takeover_client._curl)"))
    if not ok:
        坏.append("新增")
    ok = not 修好
    print(f"  {G + '✅' + D if ok else R + '❌' + D} 欠债表里没有已经修好的(只许少不许多,修好了要删)"
          + ("" if ok else f"  {修好} —— 从 欠债 里删掉这几条"))
    if not ok:
        坏.append("反向")
    ok = 扫了 > 0
    print(f"  {G + '✅' + D if ok else R + '❌' + D} 真扫到了源文件({来源} {扫了} 个)"
          + ("" if ok else "  一个都没扫到 —— **扫了 0 个 ≠ 都没问题**"))
    if not ok:
        坏.append("零文件")
    ok = not 读不了
    print(f"  {G + '✅' + D if ok else R + '❌' + D} 跟踪的源文件都读得了、解析得了(**没扫到 ≠ 没问题**)"
          + ("" if ok else f"  {len(读不了)} 个:{读不了[:5]}"))
    if not ok:
        坏.append("读不了")

    print()
    # 收尾汇总一行(门禁 run 成功时只印最后 3 行)
    print(f"  ℹ️ 扫 {扫了} 个源文件 · 欠债 {sum(len(v) for v in 欠债.values())} 处 · 试纸 {'扫到' if 扫(试纸) else '没扫到'}")
    if 坏:
        print(f"{R}❌ URL 参数名 {len(坏)} 处不符合预期{D}"); return 1
    print(f"{G}✅ URL 查询参数名没有中文字面量{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
