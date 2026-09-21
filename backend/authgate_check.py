# -*- coding: utf-8 -*-
"""写入口的身份闸:没登录不许改业务数据。

## 为什么单独一条检查

2026-09-20 外部审阅复现出一个漏洞:`/api/transit`(通用状态流转入口)
**直接把请求体喂给业务函数,没有取任何身份**,而那个函数的 `actor`
默认是「魏欣新」—— 一个**真实员工的名字**。

后果:一个没有 Cookie 的请求就能改商品状态,而审计记在他头上。

> **「他真做了」和「没人登录但系统记成他」,在审计日志里长得一模一样。**

## ⚠️ 这条必须打 HTTP 层,不能只测业务函数

`write_smoke_check` 测的是**模块级函数**(绕过路由),
而漏洞正好在**路由到函数之间那一段** —— 函数本身没问题,是入口没取身份。

> **「业务函数校验了」和「入口调它之前校验了」是两件事。**

所以这里构造一个**最小的假 handler**(有/没有 Cookie 两种),直接调 `do_POST`,
看它走到哪一步。

## ⚠️ 不用「门禁全绿」代替这条

外部审阅那句话说得对:**不要用「全部检查为绿」替代具体问题的验证证据**。
这个漏洞在 130 项检查全绿的情况下存在了很久 ——
**检查覆盖的是「已知要检查的东西」,不是「所有该检查的东西」。**
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

咬合 = [
    ('把 /api/transit 的身份检查去掉(回到审阅发现漏洞时的样子)',
     '没登录的流转请求被拒'),
]


class 假请求:
    """最小的假 handler:够 `do_POST` 跑起来,记下它回了什么。"""
    def __init__(self, path, body, cookie=None):
        self.path = path
        self._body = json.dumps(body, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._body))}
        if cookie:
            self.headers["cookie"] = cookie
        self.rfile = io.BytesIO(self._body)
        self.wfile = io.BytesIO()
        self.状态码 = None
        self.回了 = None

    # BaseHTTPRequestHandler 的那几个,够用就行
    def send_response(self, code, *a): self.状态码 = code
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打一次(path, body, cookie=None):
    import server
    h = 假请求(path, body, cookie)
    # 把 _send 换成记录版 —— 不真的写 socket
    def _send(obj, code=200):
        h.状态码 = code; h.回了 = obj
    h._send = _send
    try:
        server.H.do_POST(h)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:60]}"
    return h.状态码, h.回了


def ck(t, got, want, extra=""):
    global bad
    ok = got == want
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t:46s} 判为 {str(got):14s} 应为 {want}{extra}")


def main():
    global bad
    print("\n\033[1m▸ 写入口身份闸 · 打 HTTP 层(不是直接调业务函数)\033[0m")
    print("  " + "=" * 80)

    # ⚠️ target 用一个**不存在的对象** —— 万一身份闸失效,也不会改到真实数据。
    # 而判据看的是**在哪一步被拦下**:
    #   拦在身份 → 401;漏过身份 → 会走到业务层报「不存在」(那就是回归了)
    码, 回 = 打一次("/api/transit",
                    {"machine": "bk-product", "target": "AUTHGATE-NO-SUCH",
                     "to": "下架", "ctx": {}})
    ck("没登录的流转请求被拒", 码, 401,
       f"  ← 回的是 {str(回)[:46]}")
    if 码 != 401:
        print(f"      {R}⚠{D} **它走到业务层去了** —— 说明入口没取身份,"
              f"而那正是审阅复现出来的漏洞。")

    # 操作人不许来自请求体 —— **自报身份不算身份**
    码2, 回2 = 打一次("/api/transit",
                     {"machine": "bk-product", "target": "AUTHGATE-NO-SUCH",
                      "to": "下架", "ctx": {}, "actor": "张静静", "role": "店长"})
    ck("请求体里自报的身份不算数", 码2, 401,
       "  ← 请求体里写「我是店长」也一样拒 —— **自报身份不是身份**")

    print(f"\n  {Y}⚠ 这条检查的范围{D}:只验了**身份**(有没有登录),")
    print(f"     **没验权限**(这个人能不能走这条边)。")
    print(f"     「状态机允许这条边」不等于「当前这个人可以走它」——")
    print(f"     权限那一层还没做,**别把这条绿当成权限也守住了**。")

    print()
    if bad:
        print(f"{R}❌ 写入口身份闸 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 写入口身份闸符合预期{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
