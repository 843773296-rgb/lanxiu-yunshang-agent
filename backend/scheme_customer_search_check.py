# -*- coding: utf-8 -*-
"""方案页 · 客户搜索按本店划范围 + 着装人必须明确点选 · 检查(复审第 4 节 B,用户 10-23 拍)。

原来方案页的客户是一个 5155 项的平铺下拉框,不分门店;选了客户也不问「给谁做」——
名下不止一个着装人时后台拒绝出码,页面只能干看着。这一刀改成:
① 输入搜索(姓名 / 手机尾号 / 客户号),**要登录,顾问 / 店长只搜得到本店的**;
② 选定客户后列出名下的着装人,**顾问必须明确点选一个,不默认第一个**;没选不出尺码、不让保存;
③ 尺码按选中的那个人出,而且那个人必须在这位客户名下(前端发什么后台都照推,就等于没闸)。

## 判据造它要验的形状,不靠库里碰巧有什么

在**库副本**里自造两家店、两位量过体的客户(一位名下两个着装人、一位名下一个),
身份也自造会话 —— 两个环境都真验得到,不取决于真库里有没有「两家店都有量过体客户的店长」。

## 页面那一半在 node 里真跑页面脚本

「不默认选第一个」是页面行为,读源码找不到「默认」两个字证明不了什么。
所以照 `page_load_check.mjs` 的办法:node vm 里跑 scheme.html 的真脚本,网络换成假的,
真走「选客户 → 取着装人 → (不点选)→ 看尺码请求发没发、保存按钮能不能点」。
"""
import datetime as _dt, io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import auth, server            # noqa: E401 —— 先加载,用副本才改得到它们的 DB
import api as backend
import check_copy

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("店长也当成跨店角色(搜索不按门店划)", "店长按客户号搜别家店的客户:搜不到"),
    ("搜索接口从登录闸清单里拿掉", "没登录:搜客户拒(401)"),
    ("选了客户就默认选中第一个着装人", "名下两个着装人:选了客户之后一个都没预选"),
    ("没点选着装人也照发尺码请求", "没点选着装人:不发尺码请求"),
    ("kb_fit 不核着装人是不是这位客户名下的", "传一个别家客户的着装人:不推码"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok: 坏.append(名)
    print(f"  {G+'✅'+D if ok else R+'❌'+D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


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
    tok = f"scheme-search-check-{人['no']}"
    with auth._LOCK:
        auth._SESS[tok] = dict(人, at=_dt.datetime.now())
    return tok


def 造形状(db):
    """两家店、两位量过体的客户;甲名下两个着装人(都量过体),乙名下一个。全在副本里。"""
    import sqlite3
    c = sqlite3.connect(db)
    now = "2026-10-01 10:00"
    for acc, ph, cid, nm, shop, ws in (
        ("UA-CHK-甲", "19900001234", "CK-甲", "检查搜客户甲", "检查甲店", [("WK-甲-0", "本人", "女"), ("WK-甲-1", "女", "女")]),
        ("UA-CHK-乙", "19900005678", "CK-乙", "检查搜客户乙", "检查乙店", [("WK-乙-0", "本人", "男")]),
    ):
        c.execute("INSERT INTO account(id,phone,self_wearer_id,created) VALUES(?,?,?,?)", (acc, ph, ws[0][0], now))
        c.execute("INSERT INTO customer(id,name,phone,phone_tail,shop,account_id,created) VALUES(?,?,?,?,?,?,?)",
                  (cid, nm, ph, ph[-4:], shop, acc, now))
        for wid, rel, sex in ws:
            c.execute("INSERT INTO wearer(id,customer_id,account_id,name,gender,birthday,relation,status,created)"
                      " VALUES(?,?,?,?,?,?,?,'在用',?)", (wid, cid, acc, nm + rel, sex, "1995-01-01", rel, now))
            # 一整次亲自量的量体(照真库里一位客户的项抄一份,不手编尺寸)
            for item, val in c.execute("SELECT item,value FROM measure_rec WHERE wearer_id=("
                                       "SELECT wearer_id FROM measure_rec WHERE method='到店' LIMIT 1)").fetchall():
                c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by_no,measured_at,method,wearer_id)"
                          " VALUES(?,?,?,?,?,?,'到店',?)", (cid, "LT01", item, val, "60000005", now, wid))
    c.commit(); c.close()


# ── 页面那一半:node vm 里跑 scheme.html 的真脚本 ────────────────────────────
页面判据 = r"""
import fs from "node:fs"; import vm from "node:vm";
const src = fs.readFileSync(process.env.PAGE, "utf8");
const js = src.split("<script>").slice(1).join("<script>").split("</script>")[0];
const 记 = [];
const store = new Map();
const el = (id) => ({ id, _h: "", disabled: false, value: "", dataset: {}, style: {},
  classList: { add() {}, remove() {} }, addEventListener() {},
  get innerHTML() { return this._h; }, set innerHTML(v) { this._h = String(v); },
  get textContent() { return this._h; }, set textContent(v) { this._h = String(v); } });
const $ = (id) => { if (!store.has(id)) store.set(id, el(id)); return store.get(id); };
const 着装人 = { "C-两人": [{ id: "W-一", name: "妈妈", relation: "本人", 量过体: true },
                            { id: "W-二", name: "女儿", relation: "女", 量过体: true }],
                "C-一人": [{ id: "W-独", name: "本人", relation: "本人", 量过体: true }] };
const 回 = (o, s = 200) => Promise.resolve({ ok: s < 400, status: s, json: async () => o });
const fetch = (u, opt = {}) => {
  u = String(u); 记.push({ u, body: opt.body ? JSON.parse(opt.body) : null });
  if (u.startsWith("/api/scheme-options")) return 回({ 形制: [], 材质: [], 工艺: [], 配饰: [], 颜色: [], 版型: {} });
  if (u.startsWith("/api/scheme-check")) return 回({ issues: [] });
  if (u.startsWith("/api/schemes")) return 回({ rows: [] });
  if (u.startsWith("/api/scheme-wearers")) {
    const c = decodeURIComponent(u.split("customer=")[1] || "");
    return 回({ customer: c, rows: 着装人[c] || [] });
  }
  if (u.startsWith("/api/fit")) return 回({ 档位: "标准码", 推荐尺码: "M", 理由: "", 量体方式: "到店", 明细: [] });
  return 回({ skip: true });
};
const ctx = { console, setTimeout, clearTimeout, Promise, JSON, Math, Date, String, Number, Array, Object,
  Error, Map, Set, encodeURIComponent, decodeURIComponent, fetch,
  document: { getElementById: $, querySelectorAll: () => [], querySelector: () => null } };
ctx.window = ctx; vm.createContext(ctx); vm.runInContext(js, ctx);
const 等 = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setTimeout(r, 0)); };
const 跑 = (s) => vm.runInContext(s, ctx);
const 发了尺码 = () => 记.filter(x => x.u.startsWith("/api/fit"));
const 按下的人 = () => [...$("cfg").innerHTML.matchAll(/data-g="wearer"\s+data-v="([^"]+)" aria-pressed="true"/g)].map(m => m[1]);
const out = [];
const ck = (名, ok, 细 = "") => out.push({ 名, ok: !!ok, 细: String(细) });
await 等();
跑(`SEL.pt="PT04"; CUS=[{id:"C-两人",name:"两人客户"},{id:"C-一人",name:"一人客户"}]`);
await ctx.pickCus("C-两人"); await 等();
ck("名下两个着装人:选了客户之后一个都没预选", 跑("SEL.wearer") === "" && 按下的人().length === 0,
   `SEL.wearer=${跑("SEL.wearer")} 按下的 ${按下的人()}`);
ck("名下两个着装人:两个都列出来让人点", (($("cfg").innerHTML.match(/data-g="wearer"\s+data-v=/g)) || []).length === 2,
   $("cfg").innerHTML.slice(0, 160));
ck("没点选着装人:不发尺码请求", 发了尺码().length === 0, JSON.stringify(发了尺码()));
ck("没点选着装人:保存按钮不可点", $("save").disabled === true, `disabled=${$("save").disabled}`);
ctx.pickWearer("W-二"); await 等();
const f = 发了尺码().at(-1);
ck("点选第二个之后:尺码按她出(请求里带的是 W-二)", f && f.body && f.body.wearer === "W-二", JSON.stringify(f));
ck("点选之后:保存按钮可点", $("save").disabled === false, `disabled=${$("save").disabled}`);
await ctx.pickCus("C-一人"); await 等();
ck("换一位客户:原来点选的着装人清掉;名下只有一个也不替人点", 跑("SEL.wearer") === "" && 按下的人().length === 0,
   `SEL.wearer=${跑("SEL.wearer")}`);
console.log(JSON.stringify(out));
"""


def 页面():
    page = os.path.join(ROOT, "agentsite", "web", "scheme.html")
    try:
        p = subprocess.run(["node", "--input-type=module", "-"], input=页面判据, text=True,
                           capture_output=True, timeout=60, env=dict(os.environ, PAGE=page))
        rs = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        ck("页面脚本在 node 里跑起来了(没跑起来就是一条都没验)", False,
           f"{type(e).__name__}: {e} · {(locals().get('p') and p.stderr or '')[:300]}")
        return
    if not rs:
        ck("页面判据至少验了一条", False)
    for r in rs:
        ck(r["名"], r["ok"], r["细"])


def main():
    print("方案页 · 客户搜索按本店划范围 + 着装人必须明确点选")
    print("=" * 80)
    造形状(check_copy.用副本("scheme-search-"))
    店长 = dict(no="CHK-店长", name="检查店长", role="店长", shop="检查甲店")
    顾问 = dict(no="CHK-顾问", name="检查顾问", role="顾问", shop="检查甲店")
    跨店 = dict(no="CHK-总部", name="检查总部", role=backend.跨店角色[0], shop="")
    t店, t顾, t总 = 会话(店长), 会话(顾问), 会话(跨店)

    print("\n▸ 没登录")
    ck("没登录:搜客户拒(401)", 打("/api/scheme-customers?q=CK-甲")[0] == 401)
    ck("没登录:列着装人拒(401)", 打("/api/scheme-wearers?customer=CK-甲")[0] == 401)

    print("\n▸ 搜索按本店划范围")
    ids = lambda r: [x["id"] for x in (r or {}).get("rows") or []]
    _, r = 打("/api/scheme-customers?q=CK-乙", t店)
    ck("店长按客户号搜别家店的客户:搜不到", "CK-乙" not in ids(r), ids(r))
    _, r = 打("/api/scheme-customers?q=5678", t店)
    ck("店长按手机尾号搜别家店的客户:搜不到", "CK-乙" not in ids(r), ids(r))
    _, r = 打("/api/scheme-customers?q=检查搜客户", t店)
    店们 = {x["shop"] for x in (r or {}).get("rows") or []}
    ck("店长按姓名搜:只回本店的(本店那位搜得到)", "CK-甲" in ids(r) and 店们 == {"检查甲店"}, (ids(r), 店们))
    _, r = 打("/api/scheme-customers?q=检查搜客户", t顾)
    ck("顾问按姓名搜:只回本店的", ids(r) == ["CK-甲"], ids(r))
    _, r = 打("/api/scheme-customers?q=1234", t店)
    ck("按手机尾号搜得到本店那位", "CK-甲" in ids(r), ids(r))
    ck("搜索结果不带完整手机号(只给尾号)",
       r and all("phone" not in x and len(str(x.get("尾号") or "")) <= 4 for x in r.get("rows") or []), r)
    _, r = 打("/api/scheme-customers?q=CK-乙", t总)
    ck("跨店角色按客户号搜别家店的客户:搜得到", "CK-乙" in ids(r), ids(r))
    _, r = 打("/api/scheme-customers?q=检查搜客户", t总)
    ck("跨店角色按姓名搜:两家店都回", {"CK-甲", "CK-乙"} <= set(ids(r)), ids(r))

    print("\n▸ 着装人")
    码, r = 打("/api/scheme-wearers?customer=CK-乙", t店)
    ck("店长看别家店客户名下的着装人:拒(403)", 码 == 403, (码, r))
    码, r = 打("/api/scheme-wearers?customer=CK-甲", t店)
    ck("本店客户名下两个着装人都列出来", 码 == 200 and [x["id"] for x in r.get("rows") or []] == ["WK-甲-0", "WK-甲-1"], (码, r))
    d = backend.kb_fit("CK-甲", "PT04", wearer="WK-乙-0")
    ck("传一个别家客户的着装人:不推码", d.get("档位") == "判不了" and not d.get("推荐尺码"), d)
    d = backend.kb_fit("CK-甲", "PT04", wearer="WK-甲-1")
    ck("传本客户名下的着装人:照常推码(上一条不是一律拒)", d.get("档位") not in (None, "判不了"), d)
    d = backend.kb_fit("CK-甲", "PT04")
    ck("名下两人量过体、不传着装人:不猜(后台那道闸还在)", d.get("档位") == "判不了", d)

    print("\n▸ 页面:着装人不默认、不点选就不出码(node 里真跑 scheme.html)")
    页面()

    with auth._LOCK:
        for t in (t店, t顾, t总): auth._SESS.pop(t, None)
    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 方案页客户搜索与着装人点选:按本店划范围、要登录、不默认选人(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
