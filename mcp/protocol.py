#!/usr/bin/env python3
"""最小 MCP stdio 服务端 —— 纯标准库,不引任何依赖。

协议是 JSON-RPC 2.0 走 stdin/stdout,方法就这几个:
  initialize / notifications/initialized / ping / tools/list / tools/call

协议版本与字段结构是从本机已装的官方 SDK
(@modelcontextprotocol/sdk/dist/esm/types.js)里核实的,不是凭印象写的:
  LATEST_PROTOCOL_VERSION = '2025-11-25'
  SUPPORTED = ['2025-11-25','2025-06-18','2025-03-26','2024-11-05','2024-10-07']
  tools/list  → {"tools":[{name, description, inputSchema}]}   inputSchema 根必须是 type:"object"
  tools/call  → {"content":[{"type":"text","text":...}], "isError":bool}

⚠️ **stdout 只能有 JSON-RPC。** 任何 print / 日志都必须走 stderr ——
   往 stdout 打一行调试信息,客户端就会解析失败,而且报错信息完全看不出是这个原因。
"""
import json, os, sys, traceback

# ── 隔离试运行:整个服务改读一份库副本(研判队列未做项第 6 项 · 用户 2026-10-19 拍:副本遮掉顾客信息)──
# 启动方在 env 里给 LANXIU_DB(副本路径)→ 把**每个已加载模块**里指着真库的 `DB` 改到副本上。
# 55 个文件各自写死了真库路径,一个个改不现实,也一定会漏;所以每次执行工具之前**再扫一遍** ——
# 工具里懒加载的模块启动时还没有,漏掉它们读到的就是没遮蔽的顾客信息。
# 生效了就在副本旁边留一行凭证:env 到没到这个进程「没有证据」的话,试跑那头拒绝认结果(和遮蔽台账同一个理由)。
_真库 = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "lanxiu.db"))


def 指到副本():
    """→ 这次改了几个模块的 DB。没给 LANXIU_DB → 0,什么都不动。"""
    副 = (os.environ.get("LANXIU_DB") or "").strip()
    if not 副 or os.path.realpath(副) == _真库:
        return 0
    n = 0
    for m in list(sys.modules.values()):
        db = getattr(m, "DB", None)
        if isinstance(db, str) and os.path.realpath(db) == _真库:
            m.DB = 副; n += 1
    if not getattr(指到副本, "_留过", False):
        try:
            with open(os.path.join(os.path.dirname(副), "副本生效.txt"), "a", encoding="utf-8") as f:
                f.write(f"{os.getpid()}\t{os.path.basename(sys.argv[0])}\t改了 {n} 个模块\n")
            指到副本._留过 = True
        except Exception:
            pass
    return n


LATEST = "2025-11-25"
SUPPORTED = [LATEST, "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"]


def 遮被判那条(out):
    """**正在被判的那条差评,它自己的人工处置痕迹一律抹成 None** —— 每个工具的返回出门前都过这一道。

    启动方(`agentsite/sdk.mcp_config`)把被判的包裹号放进这个服务进程的 env `LANXIU_JUDGING_PKG`;
    没设就原样返回(人在后台复核、顾问聊天,照旧全给)。

    为什么放在这一层、而不是让各个工具自己遮:
    · `service_records` 分不出调用方是人还是模型(模型是以某个员工身份跑的)——
      > 一个「人在复核」和一个「模型在被考」,**在工具的入参上长得一模一样**。
      所以「这一轮在判哪条」只能由**启动方**说,而 env 是模型改不了的(它只能按 schema 调工具)。
    · 放在协议这一层,**每个工具都过** —— `bad_ratings` 那张清单里也有「处理过没有」,
      以后新加一个会带出处置字段的工具,不用记得再遮一次。
    遮法、盲区都在 `knowledge/rating.遮住处置痕迹`,这儿不抄(数据工厂 10-13 建议,用户同日拍的产线路)。
    """
    被判 = (os.environ.get("LANXIU_JUDGING_PKG") or "").strip()
    if not 被判:
        return out
    _k = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
    if _k not in sys.path:
        sys.path.insert(0, _k)
    import rating as _R
    遮完, 遮了 = _R.遮住处置痕迹(out, 被判)
    if 遮了:
        log(f"[遮蔽] 被判 {被判}:遮了 {len(遮了)} 处")    # 只进 stderr,不进给模型的材料
    return 遮完


_出事于缓存 = {}


def 遮被判那笔押金(out):
    """**正在被判的那笔押金单,它自己的处置痕迹一律按「出事时」还原** —— 和差评那道并列。

    启动方把押金单号放进 env `LANXIU_JUDGING_DEPOSIT`;没设就原样返回。

    为什么和差评分成两个函数、而不是合成一个:两边**认记录的办法不一样**
    (差评按包裹号 + 长得像评价行;押金按时刻晚不晚于出事那一刻),
    而合起来写就得在里面分流 —— 分流条件写错时,表现是「另一类一处也没遮」,
    **而它不报错**。

    ⚠️ `出事于` 要查库(`财务人工任务.created`),所以这里**只读打开**、并且**缓存** ——
    每个工具的每次返回都过这一道,不缓存就是一次调用几十次查询。
    查不到工单时**什么都不遮**并且**打一行到 stderr**:
    > 一个「这笔单没有处置痕迹」和一个「我没找到分界点所以没遮」,
    > **在返回值上长得一模一样**。
    """
    单 = (os.environ.get("LANXIU_JUDGING_DEPOSIT") or "").strip()
    if not 单:
        return out
    _k = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
    if _k not in sys.path:
        sys.path.insert(0, _k)
    import refund_replay as _RR
    if 单 not in _出事于缓存:
        import sqlite3
        db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "backend", "lanxiu.db")
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            _出事于缓存[单] = _RR.出事于(c, 单)
        finally:
            c.close()
    出事 = _出事于缓存[单]
    if not 出事:
        log(f"[遮蔽] 被判押金 {单}:**找不到它的人工任务,分界点取不到 —— 一处也没遮**")
        return out
    遮完, 遮了 = _RR.遮住处置痕迹(out, 单, 出事)
    if 遮了:
        log(f"[遮蔽] 被判押金 {单}(出事于 {出事}):遮了 {len(遮了)} 处")
    _记台账(单, 出事, len(遮了))
    return 遮完


def _记台账(单, 出事, 遮了几处):
    """遮蔽**在这个进程里开过口**,往台账写一行。没设 `LANXIU_MASK_LEDGER` 就什么都不做。

    🔺 为什么要有它:这个函数跑在 MCP 服务进程里,而那个进程是 claude CLI 拉起的 ——
    **它的 stderr 评测读不到**。于是「遮蔽到底有没有生效」在评测那头没有任何证据,
    而没有证据的时候分数照样出得来,**而且更好看**(材料里还写着闭环之后的「已退」,
    三道题全送分)。
    > 一个「遮蔽生效了」和一个「env 根本没到服务进程」,**在分数上长得一模一样。**
    评测那头的规矩是:**台账里没有这一轮的行,就不许给这一轮记分**
    (`agent/refund_sets.做()`,失败即关闭)。

    写文件失败**不许把工具调用带下去** —— 台账是旁证,不是业务;
    它坏了的后果应该是「这一轮不记分」,而不是「这一轮答不出来」。
    """
    路径 = (os.environ.get("LANXIU_MASK_LEDGER") or "").strip()
    if not 路径:
        return
    try:
        with open(路径, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(押金单=单, 出事于=出事, 遮了几处=遮了几处,
                                    pid=os.getpid()), ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"[遮蔽] 台账写不进去({type(e).__name__}: {e})—— 不影响这次调用")


def log(*a):
    """日志一律走 stderr"""
    print(*a, file=sys.stderr, flush=True)


# ── 后台可配的三个开关(用户 2026-10-23 拍「MCP 管理带配置」,backend/mcp_registry.py)──────────────
# 停用 / 超时 / 限流。**三样都只能让工具更少、更慢地被用**,没有一个能放大权限。
# 每 5 秒重读一次(只读连接):新开的对话立即生效,开着的对话 5 秒内跟上。读不到 = 全部启用、不限(和原来一样)。
_配 = {"值": {}, "时": 0.0}


def _工具配置():
    import time as _t
    if _t.time() - _配["时"] > 5:
        try:
            import importlib.util as _u
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "mcp_registry.py")
            sp = _u.spec_from_file_location("mcp_registry", _p)
            m = _u.module_from_spec(sp); sp.loader.exec_module(m)
            _配["值"] = m.配置(os.environ.get("LANXIU_DB") or None)
        except Exception:
            _配["值"] = {}
        _配["时"] = _t.time()
    return _配["值"]


def _是写(nm):
    try:
        import api
        return nm in api.WRITE_TOOLS
    except Exception:
        return True    # 判不了就当写 —— 宁可多提醒一句「可能已落库」


class Server:
    def __init__(self, name, version, tools):
        """tools: [(name, description, input_schema, fn), ...]"""
        self.name, self.version = name, version
        self.tools = {t[0]: t for t in tools}
        # ── 按角色只挂这个角色的工具(2026-09-22)──────────────────────────
        # 启动方把这个角色能用的工具名放进 LANXIU_TOOLS(逗号分隔)。不在名单里的
        # **既不列出、也调不了** —— 原来三个服务不分角色整包挂上,按角色的名单只进了
        # allowed_tools,而那不是排他白名单:后台运营调了只发给工坊的「算工期」,还据此作答;
        # 财务(名义 5 个工具)每轮带的工具说明反而比后台运营(41 个)还多。
        # 没设这个变量(自测、直连)就照旧全挂 —— 名单为空串时一个都不挂。
        指到副本()
        self._近调 = {}
        # 这一次工具调用实际读了哪些库表(证据中心第五个工作包,10-25):这个进程里新开的每个 sqlite 连接都挂观测。
        # 装不上(没有 backend 路径的直连自测)就不观测 —— 观测是证据,不是业务,它坏了不许拦住工具
        try:
            import db_observe as _dbo
            _dbo.装上()
            self._观测 = _dbo
        except Exception:
            self._观测 = None
        only = os.environ.get("LANXIU_TOOLS")
        if only is not None:
            keep = {x for x in only.split(",") if x}
            self.tools = {k: v for k, v in self.tools.items() if k in keep}

    # ── JSON-RPC ────────────────────────────────────────────────
    def _ok(self, rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _err(self, rid, code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

    def handle(self, req):
        m, rid, p = req.get("method"), req.get("id"), req.get("params") or {}
        指到副本()                      # 每次都扫:上一个工具里懒加载进来的模块,这一次要接着改

        if m == "initialize":
            want = p.get("protocolVersion")
            return self._ok(rid, {
                "protocolVersion": want if want in SUPPORTED else LATEST,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
            })
        if m in ("notifications/initialized", "initialized"):
            return None                                   # 通知,不回
        if m == "ping":
            return self._ok(rid, {})
        if m == "tools/list":
            配 = _工具配置()
            return self._ok(rid, {"tools": [
                {"name": n, "description": d, "inputSchema": s}
                for n, d, s, _ in self.tools.values() if (配.get(n) or {}).get("启用", True)]})
        if m == "tools/call":
            nm = p.get("name"); args = p.get("arguments") or {}
            t = self.tools.get(nm)
            if not t:
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"没有名为 {nm} 的工具。可用:{list(self.tools)}"}], "isError": True})
            c = _工具配置().get(nm) or {}
            if not c.get("启用", True):
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"工具 {nm} 已在后台停用(MCP 服务与工具管理),这一轮用不了 —— 照实告诉用户,不要换别的工具硬凑"}],
                    "isError": True})
            if c.get("限流"):
                import time as _t, collections as _c
                q = self._近调.setdefault(nm, _c.deque())
                while q and _t.time() - q[0] > 60: q.popleft()
                if len(q) >= c["限流"]:
                    return self._ok(rid, {"content": [{"type": "text",
                        "text": f"工具 {nm} 一分钟内已经调了 {len(q)} 次,到了后台设的上限 —— 先用已经拿到的结果"}],
                        "isError": True})
                q.append(_t.time())
            import contextlib as _cl
            观 = self._观测.一次调用(nm, args) if self._观测 else _cl.nullcontext()
            with 观:
                return self._执行一次(rid, nm, args, t, c)
        if rid is None:
            return None                                   # 未知通知,忽略
        return self._err(rid, -32601, f"未实现的方法 {m}")

    def _执行一次(self, rid, nm, args, t, c):
        """tools/call 真正执行那一段(拆出来是为了整段包在库表观测里)。"""
        if c.get("超时"):
            import threading as _th
            结果 = {}
            def _跑():
                try: 结果["out"] = t[3](**args)
                except Exception as e: 结果["err"] = e
            # 线程不继承 contextvars —— 不在复制的上下文里跑的话,这一次读了什么表就**悄悄**记不到
            import contextvars as _cv
            th = _th.Thread(target=_cv.copy_context().run, args=(_跑,), daemon=True); th.start(); th.join(c["超时"])
            if th.is_alive():
                return self._ok(rid, {"content": [{"type": "text",
                    "text": f"工具 {nm} {c['超时']} 秒没回(后台设的超时),不等了"
                            + ("。⚠️ 这是写工具,**这一笔可能已经落库**,先查一下再决定要不要重试" if _是写(nm) else "")}],
                    "isError": True})
        try:
            if c.get("超时"):
                if "err" in 结果: raise 结果["err"]
                out = 遮被判那笔押金(遮被判那条(结果["out"]))
            else:
                out = 遮被判那笔押金(遮被判那条(t[3](**args)))
            return self._ok(rid, {"content": [{"type": "text",
                "text": json.dumps(out, ensure_ascii=False, indent=1)}], "isError": False})
        except TypeError as e:
            return self._ok(rid, {"content": [{"type": "text",
                "text": f"参数不对:{e}"}], "isError": True})
        except Exception as e:
            log("工具执行失败", nm, traceback.format_exc())
            return self._ok(rid, {"content": [{"type": "text",
                "text": f"{type(e).__name__}: {e}"}], "isError": True})

    def run(self):
        log(f"[{self.name}] 就绪,{len(self.tools)} 个工具")
        for line in sys.stdin:
            line = line.strip()
            if not line: continue
            try:
                req = json.loads(line)
            except Exception:
                log("收到非 JSON:", line[:120]); continue
            for r in ([req] if isinstance(req, dict) else req):
                resp = self.handle(r)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
