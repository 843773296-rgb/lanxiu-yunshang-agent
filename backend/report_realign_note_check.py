# -*- coding: utf-8 -*-
"""经营报告「统计期已校正」标注 · 检查(用户 2026-10-23 拍:正文不改写,页面上标注)。

每日平移把报告期挪歪过,数据工厂的 tools/realign_report_periods.py 把 period 两列掰回日历边界,
并在 op_log 落一条痕迹(machine='report_period'、code='REALIGN'、target=报告号,ctx 里结构化的四个日期)。
这一半是**读痕迹、在报告页上挂标注**。验:
  ① 没痕迹的报告:不标(None)
  ② 有痕迹:按**最后一条**取,字段从 ctx 读(不从 reason 里抠)
  ③ 页面(node 里真跑 report.html 的 画单份):有痕迹就挂;正文 / 取数包没改时说清「是校正前生成的」;
     两样都改过了就不再说那句;没痕迹不挂
全在**库副本**上;痕迹用 oplog.log_op(..., db=副本) 写 —— 不带 db 就会往真库塞一行假痕迹,
让真页面给一份没被校正过的报告挂上「已校正」(数据工厂 10-23 提醒)。
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "knowledge")]
import api, report_doc, oplog, server   # noqa: E401 —— 先加载,用副本才改得到它们的 DB
import check_copy

G, R, D = "\033[32m", "\033[31m", "\033[0m"
坏, n = [], 0

咬合 = [
    ("取痕迹时取第一条而不是最后一条", "有两条痕迹:按最后一条取,字段从 ctx 读"),
    ("页面不看「正文已改」,一律说是校正前生成的", "页面:正文和取数包都改过了,不再说「校正前生成的」"),
    ("后台不把痕迹带给页面", "有两条痕迹:按最后一条取,字段从 ctx 读"),
]


def ck(名, ok, 附=""):
    global n
    n += 1
    if not ok:
        坏.append(名)
    print(f"  {G + '✅' + D if ok else R + '❌' + D} {名}" + (f"  {str(附)[:220]}" if 附 and not ok else ""))


页面判据 = r"""
import fs from "node:fs"; import vm from "node:vm";
const src = fs.readFileSync(process.env.PAGE, "utf8");
const js = src.split("<script>").slice(1).join("<script>").split("</script>")[0];
const store = new Map();
const el = () => ({ _h: "", get innerHTML() { return this._h; }, set innerHTML(v) { this._h = String(v); },
  addEventListener() {}, classList: { add() {}, remove() {} }, style: {}, dataset: {} });
const q = (s) => { if (!store.has(s)) store.set(s, el()); return store.get(s); };
const 回 = (o) => Promise.resolve({ ok: true, status: 200, json: async () => o });
const ctx = { console, setTimeout, Promise, JSON, Math, String, Number, Array, Object, encodeURIComponent,
  decodeURIComponent, URLSearchParams, md: (s) => String(s || ""),
  location: { search: "", href: "" }, fetch: () => 回({ rows: [] }),
  document: { querySelector: q, querySelectorAll: () => [], getElementById: q, title: "" } };
ctx.window = ctx; vm.createContext(ctx);
try { vm.runInContext(js, ctx); } catch (e) {}
const 基 = { id: "RPT-CHK", kind: "周", shop: "检查店", period_start: "2026-10-12", period_end: "2026-10-18",
  revision: 1, status: "草稿", created_at: "x", created_by: "x", body: "正文", pack: {} };
const 画 = (校) => { vm.runInContext("画单份", ctx)({ ...基, 统计期校正: 校 }); return q("#main").innerHTML; };
const 没改 = { 于: "2026-10-23 20:30:00", 校正天数: -4, 种类: "周", 正文已改: false, 取数包已改: false };
const 都改 = { ...没改, 正文已改: true, 取数包已改: true };
const out = { 没改: 画(没改), 都改: 画(都改), 没痕迹: 画(null) };
console.log(JSON.stringify(out));
"""


def main():
    print("经营报告「统计期已校正」标注 · 检查")
    print("=" * 80)
    副本 = check_copy.用副本("rpt-realign-")
    店 = server.rows("SELECT shop FROM ordr WHERE shop IS NOT NULL GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 1")[0]["shop"]
    店长 = dict(no="SM-REALIGN", name="检查店长", role="店长", shop=店)
    with api.as_user(店长):
        A = api.save_report(body="## 检查周报", kind="周")
    rid = A.get("报告号")
    ck("夹具:存出一份周报", bool(rid), A)
    if not rid:
        return 1

    ck("没痕迹的报告:不标", report_doc.取(店长, rid, db=副本).get("统计期校正") is None)

    for 天, 起 in ((-3, "2026-10-13"), (-4, "2026-10-12")):
        oplog.log_op("系统", "report_period", rid, "2026-10-16~2026-10-22", f"{起}~2026-10-18", True, "REALIGN",
                     "检查:平移后重对齐", {"kind": "周", "校正天数": 天, "旧起": "2026-10-16", "旧止": "2026-10-22",
                                     "新起": 起, "新止": "2026-10-18", "正文已改": False, "取数包已改": False}, db=副本)
    校 = report_doc.取(店长, rid, db=副本).get("统计期校正") or {}
    ck("有两条痕迹:按最后一条取,字段从 ctx 读",
       校.get("校正天数") == -4 and 校.get("新起") == "2026-10-12" and 校.get("种类") == "周"
       and 校.get("正文已改") is False and bool(校.get("于")), 校)

    ck("痕迹写进了副本(真库的 op_log 不会多出这份检查报告的痕迹)",
       os.path.realpath(oplog.DB) == os.path.realpath(副本) or not server.rows(
           "SELECT 1 FROM op_log WHERE machine='report_period' AND target=? AND reason LIKE '检查:%'", rid), oplog.DB)

    page = os.path.join(ROOT, "agentsite", "web", "report.html")
    try:
        p = subprocess.run(["node", "--input-type=module", "-"], input=页面判据, text=True,
                           capture_output=True, timeout=60, env=dict(os.environ, PAGE=page))
        o = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        ck("页面脚本在 node 里跑起来了(没跑起来就是一条都没验)", False, f"{type(e).__name__}: {e}")
        o = None
    if o:
        ck("页面:有痕迹就挂「统计期已于 X 校正」,说清挪了几天、按整周对齐",
           "data-realign" in o["没改"] and "2026-10-23 20:30:00" in o["没改"] and "往前挪了 4 天" in o["没改"]
           and "整周" in o["没改"], o["没改"][:300])
        ck("页面:正文 / 取数包没改时,说清它们是校正前生成的", "校正前生成" in o["没改"], o["没改"][:300])
        ck("页面:正文和取数包都改过了,不再说「校正前生成的」",
           "data-realign" in o["都改"] and "校正前生成" not in o["都改"], o["都改"][:300])
        ck("页面:没痕迹不挂", "data-realign" not in o["没痕迹"], o["没痕迹"][:200])

    print()
    if 坏:
        print(f"{R}❌ {len(坏)} 条不过(验了 {n} 条){D}")
        return 1
    print(f"{G}✅ 统计期已校正:有痕迹就标、取最后一条、没改正文时说清楚、没痕迹不标(验了 {n} 条){D}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
