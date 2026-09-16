#!/usr/bin/env python3
"""自测用的接口靶子 —— 壳是假的,**校验和响应约定都照着项目真实那一份**。

⚠️ 一开始这个靶子的响应是我自己拍的(`{"error": ...}` / `{"id": ...}`),
而 `backend/server.py` 里真实的写接口返回的是 `{ok, code, id, reason}`。
**靶子是我造的、规格也是我写的,两者一致证明不了规格对** —— 那是个自我确认的闭环。
真实现补上之后照着改的,顺带发现驱动会把每一次业务拒绝记成成功。

`backend/rules.py` 里的 `validate_customer` / `validate_appointment` 是纯函数,
这里只读地 import 进来用。所以自测验的不是我编的规则,是产品真实在用的规则。

为什么不去打真正跑着的那个服务(:8760):
它写的是 `backend/lanxiu.db` —— 四个数据检查的真值源,不能碰(闸门也拦着)。
而且 check.sh 不该依赖一个得先手动起起来的服务。
"""
import json, os, re, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "backend"))
import rules as _rules       # 只读引用:产品真正的写入校验


class Store:
    def __init__(self): self.customer, self.appointment, self.n = [], [], 0
    def nid(self, p): self.n += 1; return f"{p}{self.n:05d}"


def _make_handler(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, doc, code=200):
            b = json.dumps(doc, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send({"ok": False, "code": "BAD_JSON", "reason": "请求体不是 JSON"}, 400)
            p = self.path

            if p == "/api/customer-create":
                ok, code, reason, _s = _rules.validate_customer(body, store.customer)
                # 顾问是**选填**,但填了就必须是在职工号。
                #
                # 这条规则的作用是让「删掉某个字段之后请求反而成功」**真实存在**。
                # 没有它,削最小时永远不会有变体建成,于是那条
                # 「探测也是写入,建成的变体要记进回滚清单」的检查一辈子走不到 ——
                # **看着是绿的,其实一次都没验过。**(咬合时发现的:破坏它也不红。)
                #
                # 顺序也是有讲究的:必须排在基础校验**之后**。
                # 排在前面的话,削最小会先把 name/phone 删光(反正一直报 BAD_ADVISOR),
                # 等轮到删 advisor 时 name 已经没了 —— 结果是 NEED_NAME,还是不会成功。
                # ⚠️ **2026-09-16:这条判据以前判的和它说的不是一回事。**
                #
                # 原来写的是 `re.match(r"^A0\d ", adv)` —— 判的是**「A04 陆微」
                # 这种显示串**,而注释和报错都说「必须是在职工号」。
                # 两者一直对不上,只是送进来的正好是显示串,所以没人发现。
                #
                # 名字列全库删除之后,送进来的变成真工号(`60000014`),
                # 它匹配不上 `A0\d ` → 报「不是在职工号」——
                # **这句报错第一次说了实话,而它一直是错的判据。**
                #
                # 现在判的是真的:**8 位数字工号**。
                #
                # ⚠️ 改这一条是**被迫的,不是顺手**:列删了 → 映射必须改成
                # `advisor_no` → 送进来的就是工号 → 而旧判据判显示串,
                # **工号会被全部拒掉(成功 0 条)**。三样是连着的,动不了一样。
                #
                # ⚠️ **而削最小那条夹具跟着失效了**(`selftest.py:407` 种的
                # 「已离职 张三」在新判据下仍被拒,但「删掉 advisor 就成功」
                # 这条路径的建成数变成 0)。**夹具怎么调是这个工厂自己的设计**,
                # 我不在隔壁猜 —— 已登记在 `intent/advisor-columns.md`。
                adv = body.get("advisor")
                if ok and adv is not None and not re.match(r"^\d{8}$", str(adv)):
                    return self._send({"ok": False, "code": "BAD_ADVISOR",
                                       "reason": f"顾问「{adv}」不是在职工号"})
                if not ok: return self._send({"ok": False, "code": code, "reason": reason})
                rid = store.nid("SVR-C")
                store.customer.append(dict(body, id=rid))
                return self._send({"ok": True, "code": "CREATE", "id": rid,
                                   "reason": f"已建档 {rid}"})

            if p == "/api/customer-delete":
                # **还有预约挂着就不许删。** 加这条不是为了拟真,是为了让
                # 「回滚必须先孩子后父亲」这件事**可观测** ——
                # 顺序错了就删不掉,而不是"删掉了但没人知道顺序对不对"。
                cid = body.get("id")
                if any(a.get("customer_id") == cid for a in store.appointment):
                    return self._send({"ok": False, "code": "HAS_APPT",
                                       "reason": f"客户 {cid} 名下还有预约,不能删"})
                store.customer = [c for c in store.customer if c["id"] != cid]
                return self._send({"ok": True, "code": "DELETE"})

            if p == "/api/appt-create":
                if not any(c["id"] == body.get("customer_id") for c in store.customer):
                    return self._send({"ok": False, "code": "NO_CUSTOMER",
                                       "reason": f'客户 {body.get("customer_id")} 不存在'})
                d = {"way": body.get("way") or "到店量体",
                     "start": body.get("start"), "end": body.get("end")}
                # 真实现是 `role = d.get("role") or "顾问"` —— 靶子漏了这一句,
                # 于是 BACKFILL_LIMIT(店长补录超过 7 天)这条路**根本不存在**,
                # 而我一直以为是"规格字段面缺 role"。**靶子比真实现宽松,等于少测一块。**
                ok, code, reason = _rules.validate_appointment(
                    d, actor_role=body.get("role") or "顾问")
                if not ok: return self._send({"ok": False, "code": code, "reason": reason})
                rid = store.nid("SVR-AP")
                store.appointment.append(dict(body, id=rid))
                return self._send({"ok": True, "code": "CREATE", "id": rid,
                                   "reason": f"已建预约 {rid}"})

            if p == "/api/appt-delete":
                store.appointment = [a for a in store.appointment if a["id"] != body.get("id")]
                return self._send({"ok": True, "code": "DELETE"})

            return self._send({"ok": False, "code": "NO_ROUTE",
                               "reason": f"没有这个路由: {p}"}, 404)
    return H


def serve(port=0):
    """起在后台线程上。返回 (base_url, store, 关掉它的函数)。port=0 让系统挑空端口。"""
    store = Store()
    srv = HTTPServer(("127.0.0.1", port), _make_handler(store))
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return f"http://127.0.0.1:{srv.server_address[1]}", store, srv.shutdown


SPEC = {
    "base": "",     # 由调用方填真实端口
    "endpoints": {
        "customer": {
            # ⚠️ **2026-09-16:`advisor` 这一列全库删了**(名字是 staff 的副本、会漂)。
            # 而**接口字段名没变** —— 页面传的还是「A04 陆微」这种显示串,
            # 只是它落到 `advisor_no` 列,中间经过 `server.顾问工号()` 翻译。
            #
            # 所以这里左右不再是同一个词:**左边是接口字段,右边是存储列**。
            # 这是接口和存储在这个项目里**第一次分家**,写下来免得下一个人
            # 以为是笔误又把它改回去。
            "create": {"method": "POST", "path": "/api/customer-create",
                       "fields": {"name": "name", "phone": "phone", "shop": "shop",
                                  "advisor": "advisor_no"},
                       "id_path": "id", "ok_field": "ok"},
            # 这个接口能返回的**全部**业务码。前四个来自 backend/rules.py 的
            # validate_customer,BAD_ADVISOR 是这个靶子自己的。
            # 声明全集,报告才说得出「哪几条规则这批数据从没撞到」。
            "codes": ["NEED_NAME", "BAD_PHONE", "DUP_PHONE", "NEED_REVIEW", "BAD_ADVISOR"],
            # 业务上必须唯一的字段。schema 里 customer.phone **不唯一**,
            # 但业务规则要求它唯一 —— 定向构造要靠这条才能把基线弄干净,
            # 否则 DUP_PHONE 抢先返回,把后面的规则全遮住。
            "fresh_fields": ["phone"],
            "delete": {"method": "POST", "path": "/api/customer-delete", "id_field": "id"},
        },
        "appointment": {
            "create": {"method": "POST", "path": "/api/appt-create",
                       # customer_id 是外键:驱动会把方案里的假 id 翻译成服务端真实 id
                       "fields": {"customer_id": "customer_id", "shop": "shop",
                                  "start": "start_ts", "end": "end_ts"},
                       # **上下文字段**:不对应任何列,但接口收、而且影响判定。
                       # role / actor / 幂等键都是这一类 —— 只用列映射表达不了它们。
                       "const_fields": {"role": "顾问"},
                       "id_path": "id", "ok_field": "ok"},
            "codes": ["BAD_TIME", "END_BEFORE_START", "NO_BACKFILL", "BACKFILL_LIMIT",
                      "LEAD_TIME", "NO_CUSTOMER"],
            # 换一个**合法的**取值(而不是改坏它)也能触发规则 —— 权限类字段就是这样:
            # 同一份数据、只换角色,落到两个不同的码上。
            "alt_values": {"role": ["店长", "总部运营"]},
            "delete": {"method": "POST", "path": "/api/appt-delete", "id_field": "id"},
        },
    },
}
