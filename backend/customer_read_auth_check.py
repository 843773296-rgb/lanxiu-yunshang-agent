# -*- coding: utf-8 -*-
"""管理后台客户读接口:要登录,而且按门店划范围(用户 2026-10-23 拍「必须登录」)。

原来写操作要登录、读不要 —— 为了「不登录也能演示」留的口子。而客户详情里有地址、消费额、
预约,**谁都能翻全公司五千多位客户**。外部复审第 4 节 A 卡把这件事摆出来,用户选了要登录。

## ⚠️ 打路由,不调函数

`customer_detail()` / `customer_list()` 本身不管身份(别的检查直接调它们,也该如此)。
**闸在路由到函数之间那一段**,所以这里造一个最小的假 handler、直接调 `do_GET`,
看它回了什么 —— 和 `authgate_check.py` 同一个办法、同一个理由。

## 判据造它要验的形状,不靠库里碰巧有什么

挑一家**有客户的店**的店长(没有就是没扫到东西,明说),再挑一位**别家店**的客户、
一位本店客户;总部运营的身份也自造一个会话。
"""
import datetime as _dt, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth, server

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏 = 0

咬合 = [
    ("把客户读接口的登录检查去掉(回到「读不要登录」)", "没登录:客户详情拒(401)"),
    ("店长也当成跨店角色(不按门店划)", "店长看别家店的客户:拒(403)"),
    ("列表照用请求里传的门店(不按登录的店覆盖)", "店长翻列表时传别家店:照样只回本店"),
    ("从点名清单里删掉订单列表", "没登录:点名的带客户信息读接口全拒(401)"),
    ("把研判队列从 `要登录的读` 里删掉(回到 10-23 那个例外)",
     "没登录:点名的带客户信息读接口全拒(401)"),
    ("让运维平台服务端改回绕 HTTP 取研判队列",
     "运维平台服务端不绕 HTTP 取研判队列(绕了就必须给那个口留例外)"),
]


def ck(名, ok, 细=""):
    global 坏
    if not ok: 坏 += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {名}{'  ' + 细 if 细 else ''}")


class 假请求:
    def __init__(self, path, tok=None):
        self.path = path
        self.headers = {"cookie": f"lx_token={tok}"} if tok else {}
        self.wfile = io.BytesIO()
        self.码, self.回 = None, None
    def send_response(self, code, *a): self.码 = code
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打(path, tok=None):
    h = 假请求(path, tok)
    def _send(obj, code=200):
        h.码, h.回 = code, obj
    h._send = _send
    server.H.do_GET(h)
    return h.码, h.回


def 会话(人):
    tok = f"cust-read-check-{人['no']}"
    with auth._LOCK:
        auth._SESS[tok] = dict(人, at=_dt.datetime.now())
    return tok


def main():
    print("\n\033[1m▸ 客户读接口:要登录、按门店划范围 · 打 HTTP 层\033[0m")
    店长 = server.rows(
        "SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='店长' AND s.status='启用' "
        "AND EXISTS(SELECT 1 FROM customer c WHERE c.shop=s.shop) "
        "AND EXISTS(SELECT 1 FROM customer c WHERE c.shop<>s.shop) LIMIT 1")
    总部 = server.rows("SELECT no,name,role,shop FROM staff WHERE role IN "
                       f"({','.join('?' * len(server.backend.跨店角色))}) AND status='启用' LIMIT 1",
                       *server.backend.跨店角色)
    if not 店长 or not 总部:
        print(f"  {R}❌ 没扫到东西{D}:要一位「本店和别家店都有客户」的在职店长、一位跨店角色 —— "
              f"**这不是验过了,是没东西可验**")
        return 1
    店长, 总部 = 店长[0], 总部[0]
    本店客 = server.rows("SELECT id FROM customer WHERE shop=? LIMIT 1", 店长["shop"])[0]["id"]
    别店客, 别店 = (lambda r: (r["id"], r["shop"]))(
        server.rows("SELECT id, shop FROM customer WHERE shop<>? LIMIT 1", 店长["shop"])[0])
    t店, t总 = 会话(店长), 会话(总部)
    print(f"  店长 {店长['name']}({店长['shop']})· 跨店 {总部['name']}({总部['role']})· "
          f"本店客户 {本店客} · 别家店({别店})客户 {别店客}\n")

    # 判据名写死,不拼 —— 咬合记录要拿这个名字去脚本里找
    for 名, 路 in (("没登录:客户详情拒(401)", f"/api/customer/{本店客}"),
                   ("没登录:客户列表拒(401)", "/api/customers2"),
                   ("没登录:客户简表拒(401)", "/api/customers")):
        码, 回 = 打(路)
        ck(名, 码 == 401, f"回了 {码} {str(回)[:40]}")

    # 订单、预约等带客户信息的读接口(用户 10-23 第二次拍板)。
    # ⚠️ **这份清单故意手抄,不读 server 里那一份** —— 拿被测的清单去验被测的清单,
    # 从里面删掉一项,判据跟着少验一项,照样绿(同源谬误,CLAUDE.md 第 7 节第 2 条)。
    # 前缀类的随便给个号,闸在路由之前,号对不对不影响拦不拦。
    点名 = ["/api/workbench", "/api/tasks", "/api/lifecycle", "/api/wearers", "/api/wearer-plan",
            "/api/fit-customers", "/api/schemes", "/api/oplog", "/api/appts2", "/api/appts",
            "/api/orders", "/api/aftersales", "/api/maintains", "/api/guide-perf", "/api/approvals",
            "/api/approval-list", "/api/schedule", "/api/staff", "/api/factory-feed",
            "/api/task/X", "/api/export/X", "/api/appt/X", "/api/chat-order/X", "/api/aftersale/X",
            "/api/maintain/X", "/api/order-log/X",
            # 研判队列(2026-10-25 补)。10-23 收这批时它是**故意留的例外** ——
            # 理由是运维平台服务端不带 cookie 来取。它漏的是 `ai_root_cause`:
            # 模型写的研判根因,「同一客户跨店重复建档」那一类整句写着姓名、生日、详细地址。
            "/api/ops-queue"]
    漏 = [x for x in 点名 if 打(x)[0] != 401]
    ck("没登录:点名的带客户信息读接口全拒(401)", bool(点名) and not 漏,
       f"{len(点名)} 个" + (f",漏了 {漏[:4]}" if 漏 else ""))
    挡错 = []
    for x in server.要登录的读:
        try:
            if 打(x, t总)[0] == 401: 挡错.append(x)
        except Exception:
            pass   # 跑到业务函数里出错不是这条要验的事(page_smoke 管它跑不跑得通);要验的只是没被登录闸挡
    ck("登录了:这些接口不被登录闸挡", not 挡错, f"被挡的 {挡错[:4]}" if 挡错 else f"{len(server.要登录的读)} 个")

    # ── 研判队列那个口:闸收了之后,服务端那头**不能再绕 HTTP** ──────────────
    # 这条判据和上面那些不一样:它不打 HTTP,扫的是 `agentsite/app.py` 的源码。
    # 为什么要它:加闸和改调用方是**一对**,只做一半的后果不对称 ——
    #   · 只加闸、服务端还绕 HTTP → 自动研判当场坏,而坏法是「点研判没反应」,
    #     用户 10-14 为这个形状报过一次 bug,查了很久(那次是取到的单跑不了)。
    #   · 只改调用方、不加闸 → 什么都不坏,**于是没人会发现闸没加上**。
    # 所以把「不绕 HTTP」钉成判据:哪天有人图省事改回 urlopen,这条先红,
    # 而不是等自动研判在半夜的批量里挂掉。
    _站 = io.open(os.path.join(os.path.dirname(HERE), "agentsite", "app.py"), encoding="utf-8").read()
    # 查结构不查字面:任何一处把 ops-queue 拼进 URL 都算绕 HTTP(urlopen / Request / requests 都一样)
    _绕 = [l.strip()[:70] for l in _站.splitlines()
           if "ops-queue" in l and ("urlopen" in l or "Request(" in l or "BACKEND" in l)
           and not l.strip().startswith("#")]
    ck("运维平台服务端不绕 HTTP 取研判队列(绕了就必须给那个口留例外)", not _绕,
       f"还有 {len(_绕)} 处:{_绕[:2]}" if _绕 else "改成直接调 ops.队列载荷()")
    ck("研判队列在统一的 `要登录的读` 清单里(不是在路由里另写一道 if)",
       "/api/ops-queue" in server.要登录的读,
       f"清单里现在 {len(server.要登录的读)} 个")

    # ── 「这个库上有几条根因带客户信息」:只报数,**不判红** ─────────────────
    # 它取决于 triage 表里碰巧有什么,而 CI 上没有模型凭据 → 不造研判样本 → 这张表恒空。
    # 按 CLAUDE.md 那条教训拆开:**闸在不在**由上面两条硬断言守(两个环境都真验得到);
    # 这里只打印,让人看见「闸拦的是不是一个真的带 PII 的口」。
    try:
        import ops as _ops_m
        _行 = _ops_m.队列载荷()["rows"]
        _文 = json.dumps(_行, ensure_ascii=False)
        _名 = [r["name"] for r in server.rows("SELECT name FROM customer WHERE name<>''")]
        _中 = {n for n in _名 if n in _文}
        print(f"  ◻️  这个库上:研判队列 {len(_行)} 条,根因文本里出现了 {len(_中)} 位客户的姓名"
              f" —— **这一行不是判据**,它取决于库里有没有研判样本(CI 上 triage 表是空的)")
    except Exception as _e:
        print(f"  ◻️  这个库上的根因 PII 没数出来({type(_e).__name__})—— 同样不是判据")

    码, 回 = 打(f"/api/customer/{本店客}", t店)
    ck("店长看本店客户:看得到", 码 in (None, 200) and ((回 or {}).get("customer") or {}).get("id") == 本店客,
       f"回了 {码} {str(回)[:40]}")
    码, 回 = 打(f"/api/customer/{别店客}", t店)
    ck("店长看别家店的客户:拒(403)", 码 == 403, f"回了 {码} {str(回)[:40]}")
    码, 回 = 打(f"/api/customer/{别店客}", t总)
    ck("跨店角色看别家店的客户:看得到", 码 in (None, 200) and ((回 or {}).get("customer") or {}).get("id") == 别店客,
       f"回了 {码} {str(回)[:40]}")

    码, 回 = 打(f"/api/customers2?shop={别店}&size=200", t店)
    店们 = {x.get("shop") for x in (回 or {}).get("rows") or []}
    ck("店长翻列表时传别家店:照样只回本店", bool(店们) and 店们 == {店长["shop"]},
       f"回来的门店 {sorted(店们)[:4]}")
    码, 回 = 打("/api/customers", t店)
    店们2 = {x.get("shop") for x in (回 or [])} if isinstance(回, list) else set()
    ck("客户简表也只回本店", bool(店们2) and 店们2 == {店长["shop"]}, f"回来的门店 {sorted(店们2)[:4]}")
    码, 回 = 打(f"/api/customers2?size=200", t总)
    店们3 = {x.get("shop") for x in (回 or {}).get("rows") or []}
    ck("跨店角色翻列表:不止一家店", len(店们3) > 1, f"{len(店们3)} 家")

    with auth._LOCK:
        for t in (t店, t总): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{R}❌ 客户读接口 {坏} 处不符合预期{D}"); return 1
    print(f"{G}✅ 客户读接口:要登录、按门店划范围,全部符合预期{D}"); return 0


if __name__ == "__main__":
    sys.exit(main())
