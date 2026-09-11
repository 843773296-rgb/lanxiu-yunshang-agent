# -*- coding: utf-8 -*-
"""会话归属的检查 —— **续聊不能续别人的**。

分两段,因为这条保证有两半,少哪一半都不成立:

  ① 判定本身对不对   —— `sessions.check` 的四种情形
  ② 判定真的挡在路上 —— chat 接口里,`check` 必须在 `sdk.run` **之前**跑,
                        而且拒绝时必须 return,不能只是记一笔然后接着跑

第 ② 段用 **AST 解析**,不用正则。理由是这个项目栽过的那次:
检查用正则读 `X = [...]` 字面量,而实际代码写的是 `X += [...]`,
**改动根本没进检查的视野,「没红」不代表守得住**。
顺序和「有没有 return」是语法结构,正则看不出来,AST 看得出来。
"""
import ast, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sessions

FAIL = []


def ck(name, ok, msg=""):
    print(f"  {'✅' if ok else '❌'} {name}{'  ' + msg if msg else ''}")
    if not ok: FAIL.append(name)


def part1():
    mgr = {"no": "60000001", "name": "张静静", "role": "店长"}
    adv = {"no": "60000002", "name": "林岚", "role": "顾问"}
    old = sessions.PATH
    fd, tmp = tempfile.mkstemp(suffix=".json"); os.close(fd); os.remove(tmp)
    sessions.PATH = tmp
    try:
        ck("新会话(没有 session_id)放行", sessions.check(None, adv)[0])
        sessions.own("sess-A", mgr)
        ck("本人续自己的,放行", sessions.check("sess-A", mgr)[0])
        ok, why = sessions.check("sess-A", adv)
        ck("**别人的会话,拒**", (not ok) and "别人的" in why, why)
        ok, why = sessions.check("sess-A", None)
        ck("没登录,拒", not ok, why)
        ok, why = sessions.check("sess-UNKNOWN", adv)
        ck("**查不到归属的,拒 —— 不猜**", (not ok) and "查不到" in why, why)
        # 归属表被删掉(服务重启/文件丢了)→ 兜底方向必须是拒,不是放行
        os.remove(tmp)
        ck("归属表没了,一律拒(兜底方向是拒不是放)",
           not sessions.check("sess-A", mgr)[0])
    finally:
        sessions.PATH = old
        if os.path.exists(tmp): os.remove(tmp)


def part2():
    """chat 接口里,check 必须挡在 sdk.run 前面,而且拒了要 return。"""
    src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
    tree = ast.parse(src)

    calls = []          # (行号, 名字)  按出现顺序
    returns_in_guard = []

    class V(ast.NodeVisitor):
        def visit_Call(self, node):
            f = node.func
            nm = None
            if isinstance(f, ast.Attribute):
                base = f.value
                if isinstance(base, ast.Name):
                    nm = f"{base.id}.{f.attr}"
            if nm in ("sessions.check", "sessions.own", "sdk.run"):
                calls.append((node.lineno, nm))
            self.generic_visit(node)

        def visit_If(self, node):
            # 形如 `if not ok_s:` 里面必须有 return
            if any(isinstance(n, ast.Return) for n in ast.walk(node)):
                returns_in_guard.append(node.lineno)
            self.generic_visit(node)

    V().visit(tree)
    calls.sort()
    order = [n for _, n in calls]
    ck("chat 接口里调了 sessions.check", "sessions.check" in order)
    ck("chat 接口里调了 sessions.own(跑完要记归属)", "sessions.own" in order)
    if "sessions.check" in order and "sdk.run" in order:
        ck("**check 在 sdk.run 之前** —— 判定要挡在路上,不能事后补",
           order.index("sessions.check") < order.index("sdk.run"))
    else:
        ck("check 在 sdk.run 之前", False, "少了其中一个")
    if "sessions.own" in order and "sdk.run" in order:
        ck("own 在 sdk.run 之后(session_id 是跑完才有的)",
           order.index("sessions.own") > order.index("sdk.run"))
    # 拒绝那一支必须 return
    chk_line = next((l for l, n in calls if n == "sessions.check"), None)
    ck("**拒绝时是 return,不是记一笔接着跑**",
       any(chk_line < r < chk_line + 8 for r in returns_in_guard) if chk_line else False)


def main():
    print("会话归属 · 续聊不能续别人的")
    print("=" * 72)
    print(" 一、判定本身")
    part1()
    print(" 二、判定挡在路上(AST,不是正则)")
    part2()
    print("=" * 72)
    if FAIL:
        print(f"❌ {len(FAIL)} 条没过:{FAIL}")
        return 1
    print("✅ 会话归属 10 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
