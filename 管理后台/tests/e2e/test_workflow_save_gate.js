/* 编排页:**草稿没存上,校验 / 冻结 / 试运行一律停下**(2026-10-24 外部方案核查出来的)。
 *
 * ## 为什么要有它
 *
 * 校验、冻结、试运行打的都是**服务端那份草稿**。原来 `做_存草稿` 失败时只弹个框、
 * 不告诉调用方,三个动作照样往下走 —— 页面上是改过的新图,**实际冻结 / 试跑的是旧稿**,
 * 而界面上看不出任何区别。冲突(409)时还会自动刷新,把这一页没存上的改动扔掉。
 *
 * 这一份不起服务:`fetch` 整个桩掉,PATCH 草稿一律回 500 或 409,
 * 然后数**后面有没有发出去任何请求**。存成功的那一组是对照 —— 它必须真发出后续请求,
 * 否则「被拦住了」和「桩坏了根本没走到」长得一模一样。
 */
const fs = require("fs"), path = require("path"), vm = require("vm");
const src = fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", "app.js"), "utf8");

let 过 = 0; const 挂 = [];
const 该跑几组 = 4; const 走过 = [];
function 组(名) { 走过.push(名); console.log(`\n▸ ${名}`); }
function ck(名, 真, 补) {
  console.log(`  ${真 ? "✅" : "❌"} ${名}${补 === undefined ? "" : "  " + JSON.stringify(补).slice(0, 160)}`);
  if (真) 过++; else 挂.push(名);
}

function 造(id) {
  return { id, value: "", textContent: "", style: {}, dataset: {}, disabled: false, className: "",
    classList: { add() {}, remove() {}, contains: () => false }, addEventListener() {},
    removeEventListener() {}, appendChild() {}, remove() {}, querySelectorAll: () => [],
    querySelector: () => null, focus() {}, scrollIntoView() {},
    set innerHTML(v) { this._h = String(v); }, get innerHTML() { return this._h || ""; } };
}
const 池 = new Map();
const 取 = (sel) => { const k = String(sel); if (!池.has(k)) 池.set(k, 造(k)); return 池.get(k); };

let 草稿回 = 500, 请求们 = [], 弹框 = [], 刷新了 = 0;
const 回 = (status, body) => Promise.resolve({ ok: status < 400, status,
  headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) });
const ctx = {
  console, setTimeout, clearTimeout, Promise, JSON, Math, String, Number, Array, Object, Map, Set, Date,
  encodeURIComponent, decodeURIComponent, URLSearchParams, Error,
  CSS: { escape: (s) => s },
  document: { querySelector: 取, querySelectorAll: () => [], getElementById: 取, createElement: () => 造("new"),
              addEventListener() {}, body: { classList: { add() {}, remove() {}, contains: () => false } } },
  window: { addEventListener() {} }, location: { hash: "#/apps" },
  localStorage: { getItem: (k) => ({ "aimc.user": "U002", "aimc.proj": "p" })[k] ?? null, setItem() {}, removeItem() {} },
  crypto: { randomUUID: () => "k" + Math.random() },
  alert: (m) => 弹框.push(String(m)), confirm: () => true, prompt: () => "测试说明",
  fetch: (u, o) => {
    const 方法 = (o && o.method) || "GET", 地址 = String(u);
    请求们.push(方法 + " " + 地址);
    if (方法 === "PATCH" && 地址.includes("/draft"))
      return 草稿回 === 200 ? 回(200, { revision: 8 })
        : 回(草稿回, { code: 草稿回 === 409 ? "REVISION_CONFLICT" : "BOOM", message: "桩", advice: "桩" });
    if (地址.includes("/validate")) return 回(200, { 通过: true, 问题: [] });
    if (地址.includes("/versions")) return 回(200, { 版本: "v9", 逻辑哈希: "x".repeat(30), 依赖: [], note: "" });
    if (地址.includes("/execution-runs") && 方法 === "POST") return 回(202, { resource_id: "r1", status: "queued" });
    return 回(200, {});
  },
};
ctx.globalThis = ctx; ctx.window = Object.assign(ctx.window, ctx);
ctx.addEventListener = () => {};
vm.createContext(ctx);
try { vm.runInContext(src, ctx); } catch (e) { /* 加载路径里碰到桩没覆盖的 DOM 不要紧,只要动作挂上了 */ }
const 动 = ctx.编排动作;
ck("页面脚本加载后挂出了编排动作(没挂上就是一条都没验)", !!动 && typeof 动.校验 === "function");
if (!动) { console.log("\n❌ 编排动作没挂出来"); process.exit(1); }

const 新图态 = () => ({ wid: "wf_x", 名称: "x", 定义: { nodes: [{ id: "s", type: "start",
  config: { input_schema: { required: [] } } }], edges: [] }, 布局: {}, revision: 7, 选中: null,
  报告: null, 脏: true, 节点库: [], 版本们: [], 底Tab: "问题" });
async function 跑(名, 动作) {
  请求们 = []; 弹框 = []; 动.设图态(新图态());
  try { await 动作(); } catch (e) { /* 后续渲染碰到桩外的 DOM 不要紧,只数请求 */ }
  return 请求们.filter((r) => !r.includes("/draft"));
}

(async () => {
  for (const 码 of [500, 409]) {
    草稿回 = 码;
    组(`草稿 PATCH 回 ${码}`);
    const 校 = await 跑("校验", 动.校验);
    ck(`校验:存失败(${码})后没发校验请求`, !校.some((r) => r.includes("/validate")), 校);
    const 冻 = await 跑("冻结", () => 动.冻结("测试说明"));
    ck(`冻结:存失败(${码})后没发冻结请求`, !冻.some((r) => r.includes("/versions")), 冻);
    const 试 = await 跑("试运行", () => 动.试运行({}));
    ck(`试运行:存失败(${码})后没发运行请求`, !试.some((r) => r.includes("/execution-runs")), 试);
    ck(`存失败(${码})时告诉了人(弹框)`, 弹框.length > 0);
  }
  组("冲突时不自动刷新(刷新会丢掉这页没存上的改动)");
  草稿回 = 409; 请求们 = []; 弹框 = []; 动.设图态(新图态());
  const ok = await 动.存草稿().catch(() => "抛了");
  ck("409 时存草稿返回 false", ok === false, ok);
  ck("409 后没有重新拉详情(没刷新)", !请求们.some((r) => r.startsWith("GET ")), 请求们);
  ck("409 的提示里说了改动还留在页面上", 弹框.some((m) => m.includes("还留在页面上")), 弹框);

  组("对照:存成功时三个动作照常发请求(不然「拦住了」和「桩坏了」分不开)");
  草稿回 = 200;
  ck("对照 · 校验照常发出", (await 跑("校验", 动.校验)).some((r) => r.includes("/validate")));
  ck("对照 · 冻结照常发出", (await 跑("冻结", () => 动.冻结("测试说明"))).some((r) => r.includes("/versions")));
  ck("对照 · 试运行照常发出", (await 跑("试运行", () => 动.试运行({}))).some((r) => r.includes("/execution-runs")));

  if (走过.length !== 该跑几组) 挂.push(`该跑 ${该跑几组} 组,只走了 ${走过.length} 组`);
  // ⚠️ 收尾两行的形状照这一组的规矩:**倒数第二行是结论**(make test-e2e-ci 取 tail -2 | head -1)。
  // 第一版结论前面带了个换行,CI 汇总那一栏就是一片空白 —— 绿了,却读不出是什么绿
  console.log("");
  console.log(挂.length ? `❌ ${挂.length} 条不过(验了 ${过 + 挂.length} 条):${挂.join(" / ")}`
                        : `✅ 过 ${过} / 挂 0 —— 草稿没存上就停:校验 / 冻结 / 试运行 × 500 / 409,冲突不刷新`);
  console.log(`(走了 ${走过.length} / ${该跑几组} 组)`);
  process.exit(挂.length ? 1 : 0);
})();
