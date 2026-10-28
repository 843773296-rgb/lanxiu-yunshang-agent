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

# ⚠️ **台账写到副本上,别写真库**(2026-10-27)。这个检查**真走 HTTP 接口**
# (`server.H.do_GET`),而带客户信息的读接口按设计会记一笔审计
# (「谁查看了客户资料」)—— 那是功能,不是 bug。但审计落在**真库**台账里,
# 就会出现「张静静查看了某客户」这种没人做过的操作,
# 而**台账本来就该有新行,多几行假的没人会觉得怪**(check.sh 第 23 行那条)。
#
# ⚠️ 这个漏子一直没被发现,**是因为被测接口一直是坏的**:
# `server.py` 里有两处**拿星号查员工表**的写法(这里刻意不写出那个串 ——
# `staff_cred_check.py` 扫的是字符,写出来这个文件自己就被扫出来了;
# 铁律:被扫描的文件里要举例就描述它),把 pwd_* 塞进返回,接口走不到底、
# 也就写不到台账那一步。2026-10-27 把那两处改成列名写死之后,接口跑通了,
# 这 5 笔审计才冒出来、被门禁的台账闸逮住。
# > 一个「接口没写台账因为它不该写」和一个「接口没写台账因为它根本没跑完」,
# > **在台账里长得一模一样** —— 都是什么都没有。
#
# 做法照 `arrival_card_check.py`:台账指到真库的一份副本上。
# 接口照旧读真库(这个检查验的是**权限**,要真数据),只有写台账那一头改道。
import sqlite3 as _sq3, tempfile as _tf
import oplog as _oplog


def _台账改道():
    """把台账写到副本上,**只在这个检查自己跑的时候调** —— 不放模块级。

    ⚠️ 2026-10-28 的教训:这段原来在**模块级**,而 `boundary_audit.py` 有三处
    `import customer_read_auth_check`(复用它打 HTTP 层的办法)。
    模块级代码在 **import 那一刻就执行**,于是 boundary_audit 一 import 它,
    `oplog.DB` 就被改掉了;而它后面那条攻击的切库逻辑是
    「把所有 DB **指向真库**的模块切到副本」—— `oplog.DB` 已经不指真库,
    **于是不在要切的名单里**,断言失败,报「这条攻击自己跑不起来」。
    > 一个「模块被 import 了」和一个「模块的副作用被执行了」,
    > **在那行 `import` 上长得一模一样。**
    一句话:**全局状态的修改不许放模块级** —— 别人 import 你是为了用你的函数,
    不是为了接受你改环境。
    """
    副本 = os.path.join(_tf.mkdtemp(), "oplog-only.db")
    _s0, _d0 = _sq3.connect(f"file:{server.DB}?mode=ro", uri=True), _sq3.connect(副本)
    with _d0:
        _s0.backup(_d0)                 # 用 backup 不用 cp —— lanxiu.db 是软链
    _s0.close(); _d0.close()
    _oplog.DB = 副本
    assert _oplog.DB != server.DB, "台账没改道 —— 下面会往真库写审计"

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
    _台账改道()          # ← 副作用只在自己跑时生效(见那个函数的注释)
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
