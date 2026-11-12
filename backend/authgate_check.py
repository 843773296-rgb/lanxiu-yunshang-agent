# -*- coding: utf-8 -*-
"""写入口的身份闸:没登录不许改业务数据 —— **逐条打 do_POST 的每一个路径**。

## 为什么单独一条检查

2026-09-20 外部审阅复现出一个漏洞:`/api/transit`(通用状态流转入口)
**直接把请求体喂给业务函数,没有取任何身份**,而那个函数的 `actor`
默认是「魏欣新」—— 一个**真实员工的名字**。

后果:一个没有 Cookie 的请求就能改商品状态,而审计记在他头上。

> **「他真做了」和「没人登录但系统记成他」,在审计日志里长得一模一样。**

那次只修了 `/api/transit` 一个口,这条检查也只打它一条。2026-11-12 全项目体检
(reports/全项目体检-20261112/A-backend.md §1.2 / §3.3)查出**同一个形状还有 14 个以上**:
不登录能建客户、建预约、停用任意员工(`/api/toggle` 把表名 / 键名从请求体拼进 SQL)、
改方案状态、伪造研判;量体模版 / 量体项三个口的角色直接读请求体。

> **只打一条的检查,守得住的也只有那一条** —— 剩下十几个口在它全绿的时候一直敞着。

所以 W01 把闸挪到 `do_POST` 入口(默认要登录,例外只有两张带理由的表),
而这条检查改成**从源码现抽全部路径、一条一条不带 cookie 打一遍**:
新加一个写口不用记得来这里登记 —— 它一出现就被打。

## ⚠️ 这条必须打 HTTP 层,不能只测业务函数

`write_smoke_check` 测的是**模块级函数**(绕过路由),
而漏洞正好在**路由到函数之间那一段** —— 函数本身没问题,是入口没取身份。

> **「业务函数校验了」和「入口调它之前校验了」是两件事。**

所以这里构造一个**最小的假 handler**(有/没有 Cookie、有/没有内部令牌),直接调 `do_POST`。
全程在**库副本**上跑(`check_copy.用副本()`)—— 万一闸失效、请求漏进业务层,写的也是副本。

## ⚠️ 不用「门禁全绿」代替这条

外部审阅那句话说得对:**不要用「全部检查为绿」替代具体问题的验证证据**。
这个漏洞在 130 项检查全绿的情况下存在了很久 ——
**检查覆盖的是「已知要检查的东西」,不是「所有该检查的东西」。**
"""
import ast, datetime as _dt, importlib, io, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

G, R, Y, D = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

咬合 = [
    ('把 do_POST 入口身份闸的「没登录就 401」删掉(登录人照取,取不到也往下走 —— 回到每个分支自己决定拦不拦的样子)',
     '不登录打 do_POST 的每一条路径 → 必须 401(豁免名单除外)'),
    ('把 toggle() 里的 TOGGLE_ALLOW 白名单判断删掉(表名 / 键名又从请求体拼进 SQL)',
     'toggle 表名不在白名单 → 拒,员工状态一个字没动'),
    ('把 toggle() 的店长以上判定删掉(顾问又能停用全店的量体项 / 编码)',
     '顾问切开关 → 拒(TOGGLE_ROLE),状态没动'),
    ('把 /api/template-save 的 role 改回读请求体(body.get("role"))',
     '角色只从会话取:顾问登录、请求体自称总部运营 → 三个口都按顾问拒'),
]

# 令牌文件指到临时目录:**不碰家目录里那一份**(两个常驻服务正在用它)
_令牌目录 = tempfile.mkdtemp(prefix="authgate-token-")
os.environ["LANXIU_INTERNAL_TOKEN_FILE"] = os.path.join(_令牌目录, "internal-token")

匿名放行上限 = 3      # 棘轮:只许少不许多。豁免一多,「默认要登录」就名存实亡
路径数地板 = 60       # 地板:防「抽路径的判据瞎了、一条没抽到,于是所有断言在空集合上成立」


def 抽路径():
    """从 server.py 的 do_POST 里现抽全部路径 → (精确路径集合, 前缀集合, do_POST 里全部 /api/ 字面量, 懒加载模块名)。

    认三种形状:`p=="..."` / `p in ("...", ...)` / `p.startswith("...")`。
    **不手抄一份清单** —— 手抄件不会自己告诉你它旧了。
    另把 do_POST 里**所有** `/api/` 开头的字面量也收上来,和抽到的对一遍:
    多出来的那一个,就是这里认不得的新形状(咬合失效类型 ①「注入没进检查的视野」的预防)。
    """
    tree = ast.parse(open(os.path.join(HERE, "server.py"), encoding="utf-8").read())
    post = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "do_POST"), None)
    if post is None:
        raise SystemExit(f"{R}❌ server.py 里找不到 do_POST —— 这道检查已经失明{D}")
    精确, 前缀, 全部字面, 模块 = set(), set(), set(), set()
    for n in ast.walk(post):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/api/"):
            全部字面.add(n.value)
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "p":
            for op, c in zip(n.ops, n.comparators):
                if isinstance(op, ast.Eq) and isinstance(c, ast.Constant) and isinstance(c.value, str):
                    精确.add(c.value)
                elif isinstance(op, ast.In) and isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                    精确 |= {e.value for e in c.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "startswith"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "p"
                and n.args and isinstance(n.args[0], ast.Constant)):
            前缀.add(n.args[0].value)
        if isinstance(n, ast.Import):
            模块 |= {a.name for a in n.names}
    return 精确, 前缀, 全部字面, 模块


class 假请求:
    """最小的假 handler:够 `do_POST` 跑起来,记下它回了什么。"""
    def __init__(self, path, body, cookie=None, 令牌=None):
        self.path = path
        self._body = json.dumps(body, ensure_ascii=False).encode()
        self.headers = {"content-length": str(len(self._body))}
        if cookie:
            self.headers["cookie"] = cookie
        if 令牌 is not None:
            import internal_token
            self.headers[internal_token.请求头.lower()] = 令牌
        self.rfile = io.BytesIO(self._body)
        self.wfile = io.BytesIO()
        self.状态码 = None
        self.回了 = None

    # BaseHTTPRequestHandler 的那几个,够用就行
    def send_response(self, code, *a): self.状态码 = code
    def send_header(self, *a): pass
    def end_headers(self): pass
    def log_message(self, *a): pass


def 打一次(path, body, cookie=None, 令牌=None):
    import server
    h = 假请求(path, body, cookie, 令牌)
    # 把 _send 换成记录版 —— 不真的写 socket
    def _send(obj, code=200):
        h.状态码 = code; h.回了 = obj
    h._send = _send
    try:
        server.H.do_POST(h)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:60]}"
    return h.状态码, h.回了


def 码之(回):
    """回包里的 code。回包不是 dict(打一次抛了异常,回的是错误串)也不崩 —— 崩了等于这条没验。"""
    return 回.get("code") if isinstance(回, dict) else f"(没回 dict:{str(回)[:40]})"


def ck(t, ok, extra=""):
    global bad
    if not ok: bad += 1
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {t}{'  ' + extra if extra else ''}")


def 会话(server, auth, role):
    r = server.rows("SELECT no,name,role,shop FROM staff WHERE role=? AND status='启用' ORDER BY no LIMIT 1", role)
    if not r:
        return None, None
    tok = f"authgate-{role}"
    with auth._LOCK:
        auth._SESS[tok] = dict(r[0], at=_dt.datetime.now())
    return f"lx_token={tok}", dict(r[0])


def main():
    global bad
    print("\n\033[1m▸ 写入口身份闸 · 逐条打 do_POST 的每一个路径(HTTP 层,库副本上)\033[0m")
    print("  " + "=" * 80)

    精确, 前缀, 全部字面, 懒模块 = 抽路径()
    # 先把 do_POST 里懒加载的模块 import 进来,再切副本 —— 不先加载的,切库扫不到它,
    # 万一闸失效、请求漏进去,它会写真库(CLAUDE.md「检查切库前先 import 写口」)
    for m in sorted(懒模块):
        try:
            importlib.import_module(m)
        except Exception:
            pass
    import server, auth, check_copy
    副本 = check_copy.用副本("authgate-")
    assert os.path.realpath(server.DB) == os.path.realpath(副本), "server.DB 没指到副本 —— 停手"

    # 前缀路径造一个不存在的尾巴,打的是同一个分支
    全部 = sorted(精确 | {x + "AUTHGATE-NO-SUCH" for x in 前缀})
    print(f"  抽到 {len(精确)} 条精确路径 + {len(前缀)} 条前缀路径,共打 {len(全部)} 条")

    # ── ⓪ 抽取判据自己没瞎 ──────────────────────────────────────────
    认不得 = sorted(全部字面 - 精确 - 前缀)
    ck("do_POST 里每个 /api/ 字面量都被抽成了路径(抽取判据没漏形状)", not 认不得,
       f"认不得:{认不得[:5]} —— 那是一种新的路由写法,这里抽不到就打不到" if 认不得 else
       f"{len(全部字面)} 个字面量全部对上")
    ck(f"抽到的 POST 路径不少于 {路径数地板} 条(样本量地板)", len(全部) >= 路径数地板,
       f"只有 {len(全部)} 条 —— **这不叫通过,这叫没扫到东西**" if len(全部) < 路径数地板 else f"{len(全部)} 条")

    # ── ① 豁免名单:每条有理由、不囤积、不过期 ─────────────────────────
    匿名, 内部 = server.POST_匿名放行, server.POST_内部口
    没理由 = [k for k, v in {**匿名, **内部}.items() if len(str(v or "").strip()) < 10]
    ck("每条豁免都写了理由(不少于 10 个字)", not 没理由, f"没写理由:{没理由}" if 没理由 else
       f"匿名 {len(匿名)} 条 + 内部口 {len(内部)} 条")
    过期 = sorted((set(匿名) | set(内部)) - 精确)
    ck("豁免名单里的路径都还在 do_POST 里(不许囤积过期豁免)", not 过期, f"已经没有这个路由:{过期}" if 过期 else "")
    ck(f"匿名放行不超过 {匿名放行上限} 条(只许少不许多)", len(匿名) <= 匿名放行上限,
       f"现在 {len(匿名)} 条:{sorted(匿名)}")

    # ── ② 主判据:不登录逐条打 → 必须 401 ─────────────────────────────
    # 请求体故意给空的 / 不存在的对象:万一闸失效,也只会走到业务层报「不存在」,而且写的是副本
    漏了 = []
    for p in 全部:
        if p in 匿名 or p in 内部:
            continue
        码, 回 = 打一次(p, {"id": "AUTHGATE-NO-SUCH", "target": "AUTHGATE-NO-SUCH"})
        if 码 != 401:
            漏了.append(f"{p} → {码} {str(回)[:40]}")
    要登录 = len([p for p in 全部 if p not in 匿名 and p not in 内部])
    ck("不登录打 do_POST 的每一条路径 → 必须 401(豁免名单除外)", not 漏了 and 要登录 > 0,
       (f"{len(漏了)}/{要登录} 条漏过闸:" + ";".join(漏了[:4]) + (f" ……还有 {len(漏了) - 4} 条" if len(漏了) > 4 else ""))
       if 漏了 else f"打了 {要登录} 条,条条 401")
    if 漏了:
        print(f"      {R}⚠{D} **它们走到业务层去了** —— 说明入口闸没拦住,"
              f"而那正是体检查出来的那一类洞(匿名建客户 / 停用员工 / 伪造研判)。")
    # 体检点名的那一个,单独印一行,出事时一眼看得到
    码, 回 = 打一次("/api/customer-create", {"name": "AUTHGATE 匿名建档", "phone": "13900000009"})
    ck("不登录建客户 → 必须 401", 码 == 401, f"回的是 {码} {str(回)[:46]}")
    码, 回 = 打一次("/api/transit", {"machine": "bk-product", "target": "AUTHGATE-NO-SUCH", "to": "下架",
                                     "ctx": {}, "actor": "张静静", "role": "店长"})
    ck("请求体里自报的身份不算数", 码 == 401, "请求体里写「我是店长」也一样拒 —— **自报身份不是身份**")
    ck("没登录时回的形状是 {error: 没登录}", isinstance(回, dict) and 回.get("error") == "没登录", str(回)[:60])

    # 对照:登录了的请求过得了闸 —— 否则「条条 401」也可能是闸把所有人都拦了
    ck_顾, 顾问 = 会话(server, auth, "顾问")
    ck_总, 总部 = 会话(server, auth, "总部运营")
    if not (ck_顾 and ck_总):
        ck("副本里有启用的顾问和总部运营(样本量 0 不叫通过)", False, "staff 表里取不到")
    else:
        码, 回 = 打一次("/api/scheme-check", {"xz": "XZ04", "mt": "MT02"}, cookie=ck_顾)
        ck("登录了的请求过得了闸(对照:闸不是把所有人都拦了)", 码 == 200, f"顾问打只读校验口回 {码} {str(回)[:40]}")

        # ── ③ 内部口:只认本机令牌头 ─────────────────────────────────
        import internal_token
        对的 = internal_token.读()
        for p in sorted(内部):
            码1, _ = 打一次(p, {"op": "handed"})
            码2, _ = 打一次(p, {"op": "handed"}, 令牌="0" * 64)
            码3, _ = 打一次(p, {"op": "handed"}, cookie=ck_总)       # 登录 cookie 也不顶令牌
            码4, 回4 = 打一次(p, {"op": "handed"}, 令牌=对的)
            ck(f"内部口 {p}:不带令牌 / 带错令牌 / 只带登录 cookie → 401", (码1, 码2, 码3) == (401, 401, 401),
               f"回的是 {码1} / {码2} / {码3}")
            ck(f"内部口 {p}:带对令牌 → 放行(不是 401)", 码4 not in (401, None), f"回的是 {码4} {str(回4)[:40]}")

        # ── ④ toggle 白名单:表名 / 键名不许从请求体拼进 SQL ────────────
        前态 = server.rows("SELECT no,status FROM staff WHERE status='启用' ORDER BY no LIMIT 1")
        if not 前态:
            ck("副本里有启用的员工(样本量 0 不叫通过)", False)
        else:
            号 = 前态[0]["no"]
            码a, 回a = 打一次("/api/toggle", {"table": "staff", "key": "no", "val": 号}, cookie=ck_总)
            码b, 回b = 打一次("/api/toggle", {"table": "sys_code", "key": "code OR 1=1 --", "val": "x"}, cookie=ck_总)
            后态 = server.rows("SELECT status FROM staff WHERE no=?", 号)[0]["status"]
            ck("toggle 表名不在白名单 → 拒,员工状态一个字没动",
               码之(回a) == "TOGGLE_NOT_ALLOWED" and 码之(回b) == "TOGGLE_NOT_ALLOWED" and 后态 == "启用",
               f"停用员工:{码之(回a)};键名注入:{码之(回b)};员工 {号} 现在「{后态}」")
            # 对照:白名单里的照样切得动(否则「拒」也可能是 toggle 整个坏了)
            码 = server.rows("SELECT code, status FROM sys_code LIMIT 1")
            ck_店, 店长 = 会话(server, auth, "店长")
            if 码 and ck_店:
                # 台账第二十七条:开关限店长以上 —— 顾问来切 → 拒,状态一个字没动
                rg = 打一次("/api/toggle", {"table": "sys_code", "key": "code", "val": 码[0]["code"]}, cookie=ck_顾)[1]
                rg = rg if isinstance(rg, dict) else {}
                后 = server.rows("SELECT status FROM sys_code WHERE code=?", 码[0]["code"])[0]["status"]
                ck("顾问切开关 → 拒(TOGGLE_ROLE),状态没动", rg.get("code") == "TOGGLE_ROLE" and 后 == 码[0]["status"],
                   f"{str(rg)[:60]};现在「{后}」")
                # 对照 + 署名用**店长**的会话验:副本里第一位总部运营恰好就是「魏欣新」,用他验署名分不出真假
                r1 = 打一次("/api/toggle", {"table": "sys_code", "key": "code", "val": 码[0]["code"]}, cookie=ck_店)[1]
                r1 = r1 if isinstance(r1, dict) else {}
                打一次("/api/toggle", {"table": "sys_code", "key": "code", "val": 码[0]["code"]}, cookie=ck_店)  # 切回去
                ck("白名单里的(系统编码)店长照样切得动(对照)", bool(r1.get("ok")), str(r1)[:60])
                最近 = server.rows("SELECT actor FROM op_log WHERE code='TOGGLE' ORDER BY id DESC LIMIT 1")
                ck("toggle 的台账署名是登录的人,不是写死的真实员工",
                   bool(最近) and 最近[0]["actor"] == 店长["name"] != "魏欣新",
               f"记的是 {(最近 or [{}])[0].get('actor')},登录的是 {店长['name']}")
            else:
                ck("副本里有系统编码和启用的店长(样本量 0 不叫通过)", False)

        # ── ⑤ 角色只从会话取:顾问登录、请求体自称总部运营 ────────────────
        # 三个口原来读 `body.get("role")`。判据看的是**被谁拒**:按会话 → 顾问 → WRONG_ROLE
        模版 = server.rows("SELECT t.code, t.name, group_concat(i.item) items FROM measure_tpl t "
                           "JOIN tpl_item i ON i.tpl=t.code GROUP BY t.code ORDER BY t.code LIMIT 1")
        量项 = server.rows("SELECT code, name, unit FROM measure_item LIMIT 1")
        回们 = {}   # 口 → code
        if 模版:
            回们["template-save"] = 打一次("/api/template-save", {"code": 模版[0]["code"], "name": 模版[0]["name"] + "·改",
                                         "items": 模版[0]["items"], "role": "总部运营"}, cookie=ck_顾)[1]
            回们["template-del"] = 打一次("/api/template-del", {"code": 模版[0]["code"], "why": "试", "role": "总部运营"},
                                        cookie=ck_顾)[1]
        if 量项:
            回们["mitem-save"] = 打一次("/api/mitem-save", {"code": 量项[0]["code"], "name": 量项[0]["name"],
                                      "unit": 量项[0]["unit"], "role": "总部运营"}, cookie=ck_顾)[1]
        ck("角色只从会话取:顾问登录、请求体自称总部运营 → 三个口都按顾问拒",
           len(回们) == 3 and all(码之(r) == "WRONG_ROLE" for r in 回们.values()),
           "; ".join(f"{k}:{码之(r)}" for k, r in 回们.items()) or "副本里没有模版 / 量体项 —— 样本量 0")

    # 静态兜一层:do_POST 里一处 `body.get("role")` 都不许有(上面只打得到三个口,新口子靠这一条)
    tree = ast.parse(open(os.path.join(HERE, "server.py"), encoding="utf-8").read())
    post = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
    读角色 = [n.lineno for n in ast.walk(post)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
              and isinstance(n.func.value, ast.Name) and n.func.value.id == "body"
              and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "role"]
    ck("do_POST 里不读请求体的 role(自报的角色不是角色)", not 读角色, f"server.py 第 {读角色} 行" if 读角色 else "")

    print(f"\n  {Y}⚠ 这条检查的范围{D}:验的是**身份**(有没有登录、角色从哪来)和 toggle 白名单;")
    print(f"     **没验每个口的权限细则**(这个人能不能做这件事)—— 那在各写口自己的检查里。")
    print(f"     `/api/book` 有意匿名;它的「按手机号能探出是不是老客」那条另记欠账,不在这一条里。")

    print()
    if bad:
        print(f"{R}❌ 写入口身份闸 {bad} 处不符合预期{D}")
        return 1
    print(f"{G}✅ 写入口身份闸符合预期{D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
