#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读接口按门店划范围 · 打 HTTP 层(用户 10-23 拍「必须登录,而且按门店划范围」;11-11 补齐 + 当天拍三件)。

11-11 实测:店长 / 顾问登录,20 个要登录的读接口里 **17 个漏别家门店的客户**(预约 2891 位、量体客户 2665 位…)。
用户 11-11 拍:财务也看全部门店;版师、工匠不看客户资料;跨店到访(记录在本店、档案在别店)的预约
只在「预约 → 到店完成 / 失效」期间对本店可见(「已到店」算进行中);订单 / 维保一直能看。

进程内假请求 + 注入会话(同 customer_read_auth_check),不起服务、不写库。
⚠️ 不打 /api/workbench、/api/ops-queue —— 读它们会顺手退回超时的升级单(ops.queue 的原有行为),会改库。
"""
import datetime as _dt
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth      # noqa: E402
import server    # noqa: E402

咬合 = [
    ("店长也当成跨店角色(读范围不按门店划)", "店长打列表接口:返回里没有别家门店"),
    ("财务没进读跨店角色(财务看不到全部门店)", "财务看全部门店"),
    ("跨店到访的预约结束后本店还看得到(进行中 / 已结束不分)", "跨店到访的预约结束后:本店列表里没有、详情 403"),
]

过, 挂 = [], []


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:300]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def 打(path, tok):
    class H:
        pass
    h = H(); h.path = path; h.headers = {"cookie": f"lx_token={tok}"}; h.wfile = io.BytesIO(); h.码 = h.回 = None
    h.send_response = lambda c, *a: None; h.send_header = lambda *a: None; h.end_headers = lambda: None
    h.log_message = lambda *a: None
    def _send(obj, code=200):
        h.码, h.回 = code, obj
    h._send = _send
    server.H.do_GET(h)
    return h.码, h.回


def 会话(人):
    tok = f"shop-scope-check-{人['no']}"
    with auth._LOCK:
        auth._SESS[tok] = dict(人, at=_dt.datetime.now())
    return tok


def 一个(角色, 店=None):
    q = "SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用'" + (" AND shop=?" if 店 else "") + " ORDER BY no LIMIT 1"
    r = server.rows(q, *( (角色, 店) if 店 else (角色,) ))
    return dict(r[0]) if r else None


列表接口 = ("/api/orders", "/api/appts", "/api/appts2", "/api/aftersales", "/api/maintains", "/api/schedule", "/api/staff",
          "/api/factory-feed", "/api/guide-perf", "/api/lifecycle", "/api/wearers", "/api/schemes", "/api/customers2")


def main():
    print("\n\033[1m▸ 读接口按门店划范围 · 打 HTTP 层\033[0m")
    店们 = [r["shop"] for r in server.rows("SELECT DISTINCT shop FROM staff WHERE role='店长' AND status='启用' ORDER BY shop")]
    if len(店们) < 2:
        ck("至少两家店才验得了「看不到别家店」", False, 店们); return 1
    本店 = 店们[0]; 别店 = [s for s in 店们 if s != 本店]
    店长 = 一个("店长", 本店); 总部 = 一个("总部运营"); 财务 = 一个("财务"); 版师 = 一个("版师")
    ck("夹具:本店店长 / 总部运营 / 财务 / 版师都找得到", all((店长, 总部, 财务, 版师)), (店长, 总部, 财务, 版师))
    if not all((店长, 总部, 财务, 版师)):
        return 1
    t店长, t总部, t财务, t版师 = (会话(x) for x in (店长, 总部, 财务, 版师))
    别名 = [s.split(" ")[0] for s in 别店]      # 门店码,如 SH002

    漏, 空 = [], []
    for p in 列表接口:
        码, 回 = 打(p, t店长)
        s = json.dumps(回, ensure_ascii=False, default=str)
        if 码 != 200: 漏.append(f"{p} HTTP {码}"); continue
        if len(s) < 40: 空.append(p)
        if any(k in s for k in 别名): 漏.append(p)
    ck(f"店长打列表接口:返回里没有别家门店(验了 {len(列表接口)} 个)", not 漏, 漏)
    ck("而且这些接口对本店店长不是空的(空集合上「没有别家店」自动成立)", len(空) <= 2, 空)

    码, 回 = 打(f"/api/orders?shop={别店[0]}", t店长)
    ck("店长传别家店参数:照样只回本店(范围跟登录走,不跟参数走)",
       码 == 200 and not any(k in json.dumps(回, ensure_ascii=False, default=str) for k in 别名))

    for 名, tok in (("总部运营", t总部), ("财务", t财务)):
        码, 回 = 打("/api/orders", tok)
        s = json.dumps(回, ensure_ascii=False, default=str)
        ck(f"{名}看全部门店(订单里有别家店)" if 名 == "总部运营" else "财务看全部门店",
           码 == 200 and any(k in s for k in 别名), 码)

    码, 回 = 打("/api/customers2", t版师)
    条 = (回 or {}).get("rows") if isinstance(回, dict) else 回
    ck("版师看不到客户资料(用户 11-11:「他们不用看客户资料」)", 码 in (200, 403) and not 条, (码, str(回)[:120]))

    别维保 = server.rows("SELECT id FROM maintain WHERE shop<>? ORDER BY id LIMIT 1", 本店)
    if 别维保:
        码, 回 = 打(f"/api/maintain/{别维保[0]['id']}", t店长)
        ck("别家店的维保单详情:403", 码 == 403, (码, str(回)[:120]))
        码, _ = 打(f"/api/maintain/{别维保[0]['id']}", t总部)
        ck("同一张单总部看得到(不是单子坏了)", 码 == 200, 码)
    else:
        ck("夹具:找得到别家店的维保单", False)

    # 跨店到访:记录在 A 店、档案在别店、已结束 → A 店看不到;总部看得到
    已结束 = server.rows(f"""SELECT a.id, a.shop FROM appointment a JOIN customer c ON c.id=a.customer_id
        WHERE c.shop<>a.shop AND a.status IN ({','.join('?' * len(server.预约状态_已结束))}) ORDER BY a.id LIMIT 1""",
        *server.预约状态_已结束)
    if 已结束:
        a = dict(已结束[0]); 那店店长 = 一个("店长", a["shop"])
        t那 = 会话(那店店长)
        码L, 回L = 打("/api/appts", t那)
        码D, _ = 打(f"/api/appt/{a['id']}", t那)
        ck("跨店到访的预约结束后:本店列表里没有、详情 403",
           码L == 200 and a["id"] not in json.dumps(回L, ensure_ascii=False, default=str) and 码D == 403, (a, 码L, 码D))
        码Z, _ = 打(f"/api/appt/{a['id']}", t总部)
        ck("同一条总部看得到(记录保留,不是删了)", 码Z == 200, 码Z)
    else:
        ck("夹具:库里有已结束的跨店到访预约(没有就验不了这一支)", False)

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 读接口按门店划范围:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
