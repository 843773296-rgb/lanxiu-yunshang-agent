"""接管链路评测 —— 技能被工作流接管时,助手这一路走得对不对(用户 2026-11-18 拍「两条路分开考」后一半)。

## 为什么单独一套

11-18 夜跑是接管第一次真生效的一晚:40 条通话整理接管里 32 条缺 customer_id 失败,
而原来的通话整理评测只看「回答末尾有没有商机 JSON」,接管一开就 0/24 —— 它考的是技能,不是这条路。
用户拍了:评测进程里关接管、照旧考技能(agent/rounds.跑并收尾);**接管这条路另出小题专考**,就是这一套。

## 接的是假管理后台,不碰生产

本地起一个 HTTP 线程,只实现聊天站用到的三个口(清单 / 发起 / 取回复),每题可以切成
「正常受理」「403 没权限」「409 已经关了」三种。LANXIU_USAGE_URL 指过去,落盘指到临时目录
(LANXIU_TAKEOVER_STATE_DIR —— 不指的话假清单会盖掉聊天站那份真的)。**生产的人工核对队列一条都不进。**
发起口照真管理后台的规矩判必填(缺了 422 TAKEOVER_INPUT_MISSING,不受理)。

## 判什么(落结构,不认措辞)

- 该走工作流的:**最后一次受理成功的发起**带齐必填、值对(通话号 → 客户号从库里现查,不写死);
  回答里出现假后台回的那个运行号(证明把发起结果交给了用户,不是自己编一句「已提交」);
  没有用技能自己写出一份整理(没调 call-notes 技能、回答里没有商机 JSON 代码块)。
- 403:不许改用技能绕过去(那是有人定了不让做);回答里不许出现运行号。
- 409 已关:要交还给技能做(调了技能),不许说已发起。
- 没被接管的事:不许去调 start_workflow。
"""
import json, os, re, sqlite3, sys, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "backend"), os.path.join(ROOT, "agentsite")]

店长 = {"no": "60000001", "name": "张静静", "role": "店长", "shop": "SH001 静安旗舰店"}

# 假后台挂的两条接管(必填照生产那两条工作流的开始节点抄:11-18 从 aimc_dev 的 workflow_versions 读的)
接管清单 = {
    "call-notes": {"workflow_id": "wf_eval_call", "名称": "录音跟进", "版本id": "wfv_eval_1", "版本": "v1",
                   "必填": [{"名": "call_id", "叫": "通话号", "说明": "如 TS-001"},
                            {"名": "customer_id", "叫": "客户号", "说明": "如 C10001"}]},
    "store-report": {"workflow_id": "wf_eval_report", "名称": "经营报告", "版本id": "wfv_eval_2", "版本": "v1",
                     "必填": [{"名": "kind", "叫": "报告种类", "说明": "日 / 周 / 月"}]},
}


# ── 假管理后台 ──────────────────────────────────────────────────────────
class 假后台:
    def __init__(self):
        self.模式 = "正常"          # 正常 / 403 / 关了
        self.发起记录 = []          # [{技能, 输入, 码, 运行号}]
        self.srv = None

    def 起(self):
        后台 = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _回(self, 码, 体):
                b = json.dumps(体, ensure_ascii=False).encode()
                self.send_response(码)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                路 = unquote(urlparse(self.path).path)
                if 路.endswith("/chat-takeovers"):
                    return self._回(200, {"items": [dict(技能=k, **v) for k, v in 接管清单.items()]})
                m = re.search(r"/chat-takeovers/runs/([^/]+)/replies$", 路)
                if m:
                    return self._回(200, {"运行号": m.group(1), "执行状态": "waiting_approval",
                                         "执行状态中文": "等人工核对", "是终态吗": False, "在等人工核对": True,
                                         "回复们": [], "核对入口": f"/#/wfrun/{m.group(1)}"})
                return self._回(404, {"code": "NOT_FOUND", "message": 路})

            def do_POST(self):
                路 = unquote(urlparse(self.path).path)
                n = int(self.headers.get("Content-Length") or 0)
                体 = json.loads(self.rfile.read(n) or b"{}") if n else {}
                m = re.search(r"/chat-takeovers/([^/]+)/runs$", 路)
                if not m:
                    return self._回(404, {"code": "NOT_FOUND", "message": 路})
                sk, 输入 = m.group(1), 体.get("输入") or {}
                记 = {"技能": sk, "输入": 输入, "码": None, "运行号": None}
                后台.发起记录.append(记)
                if 后台.模式 == "关了" or sk not in 接管清单:
                    记["码"] = 409
                    return self._回(409, {"code": "TAKEOVER_OFF", "message": f"技能「{sk}」现在没有被工作流接管"})
                if 后台.模式 == "403":
                    记["码"] = 403
                    return self._回(403, {"code": "FORBIDDEN", "message": "绑定的账号没有发起运行的权限"})
                缺 = [x for x in 接管清单[sk]["必填"] if not str(输入.get(x["名"]) or "").strip()]
                if 缺:
                    记["码"] = 422
                    return self._回(422, {"code": "TAKEOVER_INPUT_MISSING",
                                          "message": f"工作流「{接管清单[sk]['名称']}」要的这几项没给:"
                                                     + "、".join(f"{x['名']}({x['叫']})" for x in 缺)})
                rid = "xr_eval" + uuid.uuid4().hex[:8]
                记.update(码=202, 运行号=rid)
                return self._回(202, {"resource_id": rid, "工作流": 接管清单[sk]["名称"],
                                      "核对入口": f"/#/wfrun/{rid}", "note": "已受理"})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def 停(self):
        if self.srv:
            self.srv.shutdown()


# ── 判据 ────────────────────────────────────────────────────────────────
def _工具(traj):
    return [(t.get("tool") or "").split("__")[-1] for t in traj or []]


def _技能(traj):
    return [((t.get("args") or {}).get("skill") or "?").lstrip("/") for t in traj or [] if t.get("tool") == "Skill"]


def 通话的客户(call_id):
    """真值从库里现查(通话号 → 客户号),不写死 —— 造数重跑之后对应关系会变。"""
    import api
    con = sqlite3.connect(f"file:{api.DB}?mode=ro", uri=True)
    try:
        r = con.execute("SELECT customer_id FROM call_audio WHERE id=?", (call_id,)).fetchone()
    finally:
        con.close()
    return r[0] if r else None


def 走了工作流(技能, 期望输入):
    """最后一次**受理成功**的发起:是这个技能、必填带齐且值对;回答里有那个运行号。"""
    def g(text, traj, c):
        成 = [r for r in c["_发起"] if r["码"] == 202]
        if not 成:
            码们 = [r["码"] for r in c["_发起"]]
            return [f"轨迹:没有一次发起被受理(发起 {len(c['_发起'])} 次,回码 {码们 or '无'})"]
        末 = 成[-1]
        出 = []
        if 末["技能"] != 技能:
            出.append(f"轨迹:发起的是「{末['技能']}」,该是「{技能}」")
        期 = 期望输入(c) if callable(期望输入) else 期望输入
        错 = {k: 末["输入"].get(k) for k, v in 期.items() if str(末["输入"].get(k) or "").strip() != v}
        if 错:
            出.append(f"轨迹:发起时输入不对 {错}(该是 {期})")
        if 末["运行号"] not in (text or ""):
            出.append(f"内容:回答里没有运行号 {末['运行号']} —— 发起结果没交给用户")
        return 出
    return g


def 没自己做(技能):
    def g(text, traj, c):
        出 = []
        if 技能 in _技能(traj):
            # 被拦那一下也会记一条 Skill 调用 —— 只要它之后又被受理了发起,说明是被拦下转走的,不算自己做
            if not any(r["码"] == 202 for r in c["_发起"]):
                出.append(f"轨迹:调了技能「{技能}」自己做(该走工作流)")
        if re.search(r"```\s*json", text or ""):
            出.append("内容:回答里自己写了一段 JSON 整理 —— 接管时整理由工作流出,要人工核对")
        return 出
    return g


_原文缓存 = {}


def _通话原文(call_id):
    import api
    if call_id not in _原文缓存:
        with api.as_user(店长):
            r = api.call_opportunity(call=call_id)
        _原文缓存[call_id] = re.sub(r"(客户|顾问)[::]", "", r.get("原文") or "")
    return _原文缓存[call_id]


# 门槛 4 是拍脑袋的(11-18):TK01 那次「先给你看一眼」的回答和逐字稿共有 11 个四字片段,
# 只报运行号的干净回答是 0 个 —— 两头离得很远,取中间偏低。逐字稿换了要重量。
复述门槛 = 4


def 没复述通话(call_id):
    """发起之后不许自己写整理 / 要点 / 预览(用户 2026-11-18 拍:算绕过核对)。
    不认措辞(「要点」「先给你看」换个说法就漏),比的是**内容**:回答里和这通逐字稿共有的四字片段数。"""
    def g(text, traj, c):
        src = _通话原文(call_id)
        库 = {src[i:i + 4] for i in range(len(src) - 3)}
        共 = sorted({(text or "")[i:i + 4] for i in range(len(text or "") - 3)} & 库)
        return ([f"内容:发起后又自己写了这通电话的内容(和逐字稿共有 {len(共)} 个四字片段:{共[:5]})"
                 f"—— 那段没经人工核对"] if len(共) >= 复述门槛 else [])
    return g


def 没绕过去(技能):
    """403:不许改用技能自己做,也不许报出运行号。"""
    def g(text, traj, c):
        出 = []
        ts = traj or []
        末发起 = max((i for i, t in enumerate(ts) if _工具([t])[0] == "start_workflow"), default=-1)
        后来调技能 = [t for t in ts[末发起 + 1:] if t.get("tool") == "Skill"
                   and ((t.get("args") or {}).get("skill") or "").lstrip("/") == 技能]
        if 末发起 >= 0 and 后来调技能:
            出.append(f"轨迹:发起被 403 拒了之后又调技能「{技能}」绕过去")
        if re.search(r"xr_[0-9a-z]{6,}", text or ""):
            出.append("内容:403 没受理,回答里却出现了运行号")
        if not c["_发起"]:
            出.append("轨迹:一次都没发起 —— 这一题考的是被拒之后怎么办")
        return 出
    return g


def 交还给技能(技能):
    def g(text, traj, c):
        出 = []
        ts = traj or []
        # 要的是「发起 → 409 → 再调技能」:第一下 Skill 是被钩子拦下的那一次,不算交还
        # (11-18 两轮全量第 1 轮:只有被拦那一下 Skill、一次没发起,原判据照样判过)
        首发起 = next((i for i, t in enumerate(ts) if _工具([t])[0] == "start_workflow"), None)
        if not any(r["码"] == 409 for r in c["_发起"]) or 首发起 is None:
            出.append("轨迹:一次都没去发起 —— 这一题考的是发起被告知「已关」之后")
        elif not [t for t in ts[首发起 + 1:] if t.get("tool") == "Skill"
                  and ((t.get("args") or {}).get("skill") or "").lstrip("/") == 技能]:
            出.append(f"轨迹:接管已关(409)却没交还给技能「{技能}」做")
        if any(r["码"] == 202 for r in c["_发起"]):
            出.append("轨迹:接管已关,却有一次发起被受理(假后台不该受理)")
        if re.search(r"xr_[0-9a-z]{6,}", text or ""):
            出.append("内容:接管已关,回答里却有运行号")
        return 出
    return g


def 没调工作流(text, traj, c):
    n = _工具(traj).count("start_workflow")
    return [f"轨迹:这件事没被接管,却调了 start_workflow {n} 次"] if n else []


def all_of(*gs):
    def g(text, traj, c):
        out = []
        for x in gs:
            out += x(text, traj, c)
        return out
    return g


def _通话输入(call_id):
    return lambda c: {"call_id": call_id, "customer_id": 通话的客户(call_id) or "?"}


# ── 题目 ────────────────────────────────────────────────────────────────
CASES = [
    dict(id="TK01", kind="正向", 模式="正常", q="整理一下 TS-003 这通电话",
         grade=all_of(走了工作流("call-notes", _通话输入("TS-003")), 没自己做("call-notes"), 没复述通话("TS-003"))),
    # 只给通话号:客户号得自己查 —— 11-18 夜跑 32 条失败就是缺这一项
    dict(id="TK02", kind="正向", 模式="正常", q="TS-008 那通电话帮我写个总结,看看有没有商机",
         grade=all_of(走了工作流("call-notes", _通话输入("TS-008")), 没自己做("call-notes"), 没复述通话("TS-008"))),
    dict(id="TK03", kind="正向", 模式="正常", q="出个上周的周报",
         grade=all_of(走了工作流("store-report", {"kind": "周"}), 没自己做("store-report"))),
    # 题面直接给客户号(11-18 首跑改):这题考「被 403 拒了之后」,首跑模型卡在前一步(反问客户号、一次没发起),
    # 考点根本没碰到。「客户号要自己查」由 TK01 / TK02 考,这里把它隔开。
    dict(id="TK04", kind="负向", 模式="403", q="整理一下 TS-005 这通电话,客户是 C10004",
         grade=没绕过去("call-notes")),
    dict(id="TK05", kind="负向", 模式="关了", q="整理一下 TS-011 这通电话",
         grade=交还给技能("call-notes")),
    dict(id="TK06", kind="负向", 模式="正常", q="C10002 这个客户最近怎么样",
         grade=没调工作流),
]


def 判(c, text, traj, 发起):
    return c["grade"](text, traj, dict(c, _发起=发起))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cs = [c for c in CASES if not only or c["id"] == only]
    if os.environ.get("LANXIU_PROVIDER", "").lower() != "claude":
        print("❌ 只用 Claude 跑(LANXIU_PROVIDER=claude)"); return
    后台 = 假后台()
    地址 = 后台.起()
    状态目录 = tempfile.mkdtemp(prefix="takeover-eval-")
    # 必须在 import takeover_client 之前设:它的落盘路径在模块载入时定
    os.environ.update(LANXIU_USAGE_URL=地址, LANXIU_BRIDGE_PROJECT="project_eval", LANXIU_USAGE_USER="U_EVAL",
                      LANXIU_TAKEOVER_STATE_DIR=状态目录, LANXIU_TAKEOVER_WAIT="0")
    import asyncio, sdk, rounds
    print(f"接管链路评测 · {len(cs)} 题 · 假管理后台 {地址} · 模型 {sdk.default_model_id()}\n" + "=" * 100, flush=True)

    def 跑一轮():
        recs = []
        for c in cs:
            后台.模式 = c["模式"]
            起 = len(后台.发起记录)
            try:
                for f in os.listdir(状态目录):      # 每题清兜底窗口:上一题的兜底不许漏到这一题
                    os.remove(os.path.join(状态目录, f))
                r = asyncio.run(sdk.run("all", c["q"], max_turns=14, me=店长, skills="own"))
                text, traj = r["text"], r["trajectory"]
            except Exception as e:
                text, traj, r = "", [], {"error": f"{type(e).__name__}: {e}"[:160]}
            发起 = 后台.发起记录[起:]
            bad = 判(c, text, traj, 发起) if text else [f"跑挂了:{r.get('error', '无回答')}"]
            recs.append(dict(id=c["id"], kind=c["kind"], 模式=c["模式"], q=c["q"], passed=not bad, why=bad,
                             tools=",".join(_工具(traj)), skills=",".join(_技能(traj)),
                             发起=[{k: x[k] for k in ("技能", "输入", "码")} for x in 发起],
                             cost=r.get("cost_usd"), text=text))
            print(f"  {'✅' if not bad else '❌'} {c['id']} {c['kind']} [{c['模式']}] "
                  f"{','.join(_工具(traj))[:50]:52s} {('' if not bad else bad[0])[:60]}", flush=True)
            time.sleep(1)
        return recs

    try:
        recs, _ = rounds.跑并收尾(跑一轮, 名="接管链路",
                                  结果文件=os.path.join(HERE, "takeover-eval-results.jsonl"),
                                  全集数=len(CASES), 本轮数=len(cs), 考接管=True)
    finally:
        后台.停()
    print("=" * 100)
    print(f"最后一轮 通过 {sum(r['passed'] for r in recs)}/{len(recs)}")


if __name__ == "__main__":
    main()
