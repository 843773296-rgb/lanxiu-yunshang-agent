#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理后台读路由登记 · 每一条 `/api/` 读接口都必须归了类(执行手册 W47,2026-11-12)。

## 为什么

用户 2026-10-23 拍:带客户信息(姓名 / 手机号 / 地址 / 消费 / 预约)的读接口必须登录,并按门店划范围。
落法是 `server.py` 里一份点名清单 `要登录的读`,do_GET 开头统一拦。
**问题在于点名:新加一个读接口忘了登记,没有任何东西会报错** —— 它安安静静地匿名可读。

2026-11-12 逐条审 do_GET 的 91 条路由,不在清单里的 61 条里真漏了一批
(工艺文档带着装人生日和量体数据、研判详情带模型写的根因原文、单据说明拿客户号换客户姓名……)。
它们**全是这么漏的**:写的时候没人想起来登记。

## 这条检查做什么

1. 从 `server.py` 源码里抽出 do_GET 的全部 `/api/` 路由(字面量 `== "…"`、`startswith("…")`、`in ("…", …)`)。
   **抽到 0 条要红** —— 那是正则坏了,不是都通过。
2. 每一条必须**恰好**落在一类:要登录(`server._要登录`)/ 自查身份(`server.自查身份的读`)/
   匿名(`server.匿名的读`)。没分类的、落在两类里的,一条就红。两张表每条都要写理由。
3. **反向**:两张表里登记了、而 do_GET 里已经没有的路径要红;`要登录的读` 里的点名和前缀也一样
   (前缀一条路由都盖不到 = 死登记)。**豁免不许囤积。**
4. **真打 `do_GET`**(假 handler,同 customer_read_auth_check),不只看清单:
   · 不带 cookie 打每一条「要登录」路由 → 全部 401(验的是闸真的接在入口上)
   · 11-12 审出来的真漏,**手抄一份**再打一遍 → 401(不拿被测的清单验被测的清单)
   · 不带 cookie 打每一条「自查身份」和「匿名」路由 → 回包里不得出现库里任何一位客户 / 员工的
     姓名或手机号(判据是「库里的人名电话出没出现」,不是枚举字段名)
   · 店长打别家店的工艺文档 / 门店详情 / 单据说明 → 403;打本店的 → 不被挡
5. 全程在库副本上跑(`check_copy.用副本`)—— 有几个读口会顺手写台账。
"""
import ast, datetime as _dt, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth, server, ops, tasks, oplog  # noqa: E401,F401  切库前把会写库的模块先 import 进来
import check_copy

咬合 = [
    ("把 /api/craft-doc/ 从 `要登录的读_前缀` 里删掉(工艺文档又能匿名读)",
     "不带 cookie:11-12 审出来的真漏全拒(401)"),
    ("do_GET 开头那道登录闸关掉(`if _要登录(p) and not _me(self):` → `if False:`)",
     "不带 cookie 打每一条「要登录」路由:全部 401"),
    ("do_GET 里新加一条读路由、不登记",
     "每一条读路由都恰好归了一类(要登录 / 自查身份 / 匿名)"),
    ("匿名白名单里登记一条 do_GET 已经没有的路径",
     "白名单 / 点名清单里登记的路径在 do_GET 里都还在(豁免不许囤积)"),
    ("门店详情不按店划了(店长看得到别家店的员工花名册)",
     "店长看别家店的门店详情:拒(403)"),
    ("单据说明不按店划了(店长拿别家店的客户号换客户姓名)",
     "店长拿别家店的客户号换说明:拒(403)"),
]

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏 = []
验 = 0


def ck(名, ok, 细=""):
    global 验
    验 += 1
    if not ok: 坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}{'  ' + str(细)[:300] if 细 else ''}")


# ── 1. 从源码抽 do_GET 的路由 ─────────────────────────────────────────────
def 抽路由(源):
    """→ do_GET 里出现过的 `/api/` 路由字面量集合。用 AST 找 do_GET 那个函数,不靠缩进切字符串。"""
    树 = ast.parse(源)
    体 = None
    for n in ast.walk(树):
        if isinstance(n, ast.FunctionDef) and n.name == "do_GET":
            体 = ast.get_source_segment(源, n)
            break
    if not 体:
        return set()
    路 = set(re.findall(r'==\s*"(/api/[^"]*)"', 体))
    路 |= set(re.findall(r'\.startswith\(\s*"(/api/[^"]*)"', 体))
    for 组 in re.findall(r'\bin\s*\(([^()]*)\)', 体):
        路 |= set(re.findall(r'"(/api/[^"]*)"', 组))
    return 路


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
    if h.码 is None and h.wfile.getvalue():     # 直接写 wfile 的分支(CSV / 图片)
        h.回 = h.wfile.getvalue().decode("utf-8", "replace")
    return h.码, h.回


def 会话(人):
    tok = f"read-route-check-{人['no']}"
    with auth._LOCK:
        auth._SESS[tok] = dict(人, at=_dt.datetime.now())
    return tok


def 可打的(路, 例=None):
    """前缀路由补一个号;exact 路由原样。"""
    return 路 + (例 or "X") if 路.endswith("/") or 路.endswith("-") else 路


def main():
    副本 = check_copy.用副本("read-route-")
    print("\n\033[1m▸ 管理后台读路由登记 · 每一条 /api/ 读接口都归了类 · 打 HTTP 层\033[0m")
    print(f"  (库副本:{副本})")
    源 = open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
    路由 = 抽路由(源)
    ck("从 do_GET 抽到了读路由(0 条 = 正则坏了,不是都通过)", len(路由) > 0, f"抽到 {len(路由)} 条")
    if not 路由:
        return 1

    登录, 自查, 匿名 = server.要登录的读, server.自查身份的读, server.匿名的读
    分 = {"要登录": [], "自查身份": [], "匿名": []}
    没分, 多分 = [], []
    for p in sorted(路由):
        类 = [k for k, 中 in (("要登录", server._要登录(p)), ("自查身份", p in 自查), ("匿名", p in 匿名)) if 中]
        if not 类: 没分.append(p)
        elif len(类) > 1: 多分.append((p, 类))
        else: 分[类[0]].append(p)
    print(f"  分类:要登录 {len(分['要登录'])} · 自查身份 {len(分['自查身份'])} · 匿名 {len(分['匿名'])}"
          f" · 没分类 {len(没分)} · 落两类 {len(多分)}(共 {len(路由)} 条)")
    ck("每一条读路由都恰好归了一类(要登录 / 自查身份 / 匿名)", not 没分 and not 多分,
       (f"没分类 {len(没分)} 条:{没分[:8]}" if 没分 else "") + (f" 落两类:{多分[:4]}" if 多分 else ""))
    缺理由 = [k for d in (自查, 匿名) for k, v in d.items() if not str(v or "").strip()]
    ck("自查身份 / 匿名两张表每条都写了理由", not 缺理由, f"缺 {缺理由[:6]}" if 缺理由 else f"{len(自查) + len(匿名)} 条")

    # ── 反向:登记了、而 do_GET 里没有 ──
    死 = [k for k in list(自查) + list(匿名) + list(登录) if k not in 路由]
    死 += [f"前缀 {x}" for x in server.要登录的读_前缀 if not any(p.startswith(x) for p in 路由)]
    ck("白名单 / 点名清单里登记的路径在 do_GET 里都还在(豁免不许囤积)", not 死,
       f"死登记 {len(死)} 条:{死[:6]}" if 死 else f"核了 {len(自查) + len(匿名) + len(登录) + len(server.要登录的读_前缀)} 条")

    # ── 真打:要登录的全部 401 ──
    漏 = []
    for p in 分["要登录"]:
        码, _ = 打(可打的(p))
        if 码 != 401: 漏.append((p, 码))
    ck("不带 cookie 打每一条「要登录」路由:全部 401", bool(分["要登录"]) and not 漏,
       f"打了 {len(分['要登录'])} 条" + (f",没拦住 {漏[:6]}" if 漏 else ""))

    # 11-12 审出来的真漏 —— **故意手抄**,不读 server 里的清单(同源谬误,CLAUDE.md 第 7 节第 2 条):
    # 从清单里删掉一项,上面那条会跟着少验一项照样绿;这一份不会。
    真漏 = ["/api/task-ref?type=预约到店&id=C10000", "/api/agent-run", "/api/stock", "/api/stock-log",
            "/api/invites", "/api/downloads", "/api/shops", "/api/ops-detail?id=1", "/api/ops-manual",
            "/api/ops-backlog", "/api/ops-health", "/api/craft-doc/X", "/api/shop/SH001",
            "/api/activity/X", "/api/product/X"]
    漏2 = [(p, c) for p in 真漏 for c in [打(p)[0]] if c != 401]
    ck("不带 cookie:11-12 审出来的真漏全拒(401)", not 漏2,
       f"打了 {len(真漏)} 条" + (f",没拦住 {漏2[:6]}" if 漏2 else ""))

    # ── 自查身份 / 匿名:不带 cookie 的回包里不得有库里的人名电话 ──
    人名 = {r["name"] for r in server.rows("SELECT name FROM customer UNION SELECT name FROM staff")
            if r["name"] and len(r["name"]) >= 2}
    电话 = {re.sub(r"\D", "", r["phone"] or "") for r in server.rows("SELECT phone FROM customer")}
    电话 = {x for x in 电话 if len(x) >= 7}
    # 名字恰好也是商品 / 工艺词汇的不当探针(库里真有员工叫「镶三滚」、商品叫「素罗清欢」褙子)——
    # 那种撞上了说明不了泄露。词汇从库里现取,不手写
    词汇 = "\n".join(str(v or "") for r in server.rows(
        "SELECT name AS a, '' AS b, '' AS c, '' AS d FROM product UNION ALL "
        "SELECT name, alias, brief, detail FROM craft UNION ALL SELECT name, '', '', '' FROM material "
        "UNION ALL SELECT name, '', '', '' FROM category") for v in r.values())
    撞词 = {x for x in 人名 if x in 词汇}
    人名 -= 撞词
    ck("夹具:库里取得到客户 / 员工的姓名和电话(探针不是空的)", len(人名) >= 20 and len(电话) >= 20 and len(词汇) > 0,
       f"姓名 {len(人名)}(另有 {len(撞词)} 个和商品 / 工艺词汇撞名,不当探针)· 电话 {len(电话)}")
    探 = re.compile("|".join(re.escape(x) for x in sorted(人名 | 电话, key=len, reverse=True)))
    页 = (server.rows("SELECT code FROM page ORDER BY code LIMIT 1") or [{"code": "X"}])[0]["code"]
    泄, 打过 = [], 0
    for p in 分["自查身份"] + 分["匿名"]:
        码, 回 = 打(可打的(p, 页 if p == "/api/page/" else None))
        打过 += 1
        if 码 == 401: continue
        文 = 回 if isinstance(回, str) else json.dumps(回, ensure_ascii=False, default=str)
        m = 探.search(文 or "")
        if m: 泄.append((p, 码, m.group(0)))
    ck("不带 cookie:自查身份 / 匿名路由的回包里没有任何客户 / 员工的姓名或手机号", 打过 > 0 and not 泄,
       f"打了 {打过} 条 · 探针 {len(人名) + len(电话)} 个" + (f",泄了 {泄[:4]}" if 泄 else ""))

    # ── 门店范围:11-12 补的那几处 ──
    店长 = server.rows(
        "SELECT s.no,s.name,s.role,s.shop FROM staff s WHERE s.role='店长' AND s.status='启用' "
        "AND EXISTS(SELECT 1 FROM ordr o WHERE o.shop=s.shop) AND EXISTS(SELECT 1 FROM ordr o WHERE o.shop<>s.shop) "
        "AND EXISTS(SELECT 1 FROM customer c WHERE c.shop=s.shop) AND EXISTS(SELECT 1 FROM customer c WHERE c.shop<>s.shop) "
        "ORDER BY s.no LIMIT 1")
    ck("夹具:一位本店和别家店都有订单、客户的在职店长", bool(店长), "没扫到 —— 这不是验过了,是没东西可验" if not 店长 else 店长[0]["shop"])
    if 店长:
        店长 = dict(店长[0]); t = 会话(店长)
        with server._conn() as c:
            import shop_key as _SK
            我码 = _SK.码(c, 店长["shop"])
        别码 = server.rows("SELECT code FROM shop WHERE code<>? ORDER BY code LIMIT 1", 我码)[0]["code"]
        本单 = server.rows("SELECT id FROM ordr WHERE shop=? LIMIT 1", 店长["shop"])[0]["id"]
        别单 = server.rows("SELECT id FROM ordr WHERE shop<>? LIMIT 1", 店长["shop"])[0]["id"]
        本客 = server.rows("SELECT id FROM customer WHERE shop=? LIMIT 1", 店长["shop"])[0]["id"]
        别客 = server.rows("SELECT id FROM customer WHERE shop<>? LIMIT 1", 店长["shop"])[0]["id"]
        码, 回 = 打(f"/api/shop/{别码}", t)
        ck("店长看别家店的门店详情:拒(403)", 码 == 403, f"{别码} 回了 {码} {str(回)[:60]}")
        码, 回 = 打(f"/api/shop/{我码}", t)
        ck("店长看本店的门店详情:不被挡", 码 in (None, 200) and (回 or {}).get("code") == 我码, f"{我码} 回了 {码}")
        码, 回 = 打(f"/api/task-ref?type=预约到店&id={别客}", t)
        ck("店长拿别家店的客户号换说明:拒(403)", 码 == 403, f"{别客} 回了 {码} {str(回)[:60]}")
        码, 回 = 打(f"/api/task-ref?type=预约到店&id={本客}", t)
        ck("店长拿本店的客户号换说明:不被挡", 码 in (None, 200) and (回 or {}).get("customer_id") == 本客, f"{本客} 回了 {码}")
        码, 回 = 打(f"/api/craft-doc/{别单}", t)
        ck("店长看别家店订单的工艺文档:拒(403)", 码 == 403, f"{别单} 回了 {码} {str(回)[:60]}")
        码, 回 = 打(f"/api/craft-doc/{本单}", t)
        ck("店长看本店订单的工艺文档:不被挡", 码 != 403 and 码 != 401, f"{本单} 回了 {码}")
        with auth._LOCK:
            auth._SESS.pop(t, None)

    print()
    if 坏:
        print(f"{R}❌ 读路由登记 {len(坏)} 条不过(验了 {验} 条){D}")
        return 1
    print(f"{G}✅ 读路由登记:{len(路由)} 条路由全部归类,{验} 条判据全过{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
