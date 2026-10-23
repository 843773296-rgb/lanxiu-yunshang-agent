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
