/* 编排页 · HTTP 请求节点的配置面板(11-16,三期 3-1),不起服务。
 *
 * 照 test_workflow_new_nodes_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,
 * 直接调面板函数 + 面板里挂的控件回调(控件表),验**写进定义的形状**和后端校验器(runtime/validator.py ⑤¾)认的一致:
 *   ① 菜单里「HTTP 请求」是真节点(不再是「还没做」占位);默认配置 method=GET、query/headers/bindings 空对象;缺项只报「用哪条工具连接」
 *   ② 基本:只能从登记过的工具连接里选;白名单多条时才出「用哪一条地址」;换连接清掉端点序号;
 *      方法下拉只有 GET / HEAD(没有 POST 可选 —— 校验器的 HTTP_METHOD_NOT_ALLOWED 是兜底,不是入口);
 *      路径去首尾空格、清空就删键(不留 "");查询串 / 请求头是键值表:加一项 → 改名 → 填值 → 删;上限字节非法值不写进定义
 *   ③ 用到的数据:只给 path / query / headers 三项契约行,没有「加一个字段」;绑 path 到使用者输入是结构化引用
 *   ④ 下游能选到它固定返回的那几项(url / json / status_code / execution_mode)
 *   ⑤ 次级标签带连接名;它是只读节点,不算敏感节点(删除时允许快捷桥接)
 */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const 读 = (f) => fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", f), "utf8");
const src = ["wf_graph.js", "wf_canvas.js", "app.js"].map(读).join("\n;\n");

let 过 = 0; const 挂 = [];
function ck(名, 真, 补) {
  console.log(`  ${真 ? "✅" : "❌"} ${名}${真 || 补 === undefined ? "" : "  " + JSON.stringify(补).slice(0, 240)}`);
  if (真) 过++; else 挂.push(名);
}
function 造(id) {
  return { id, value: "", textContent: "", style: {}, dataset: {}, disabled: false, hidden: false, className: "", checked: false,
    classList: { add() {}, remove() {}, contains: () => false }, addEventListener() {}, removeEventListener() {},
    appendChild() {}, remove() {}, querySelectorAll: () => [], querySelector: () => null, focus() {}, blur() {}, click() {},
    setAttribute() {}, getAttribute: () => null, insertAdjacentHTML() {}, scrollIntoView() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600 }),
    set innerHTML(v) { this._h = String(v); }, get innerHTML() { return this._h || ""; } };
}
const 池 = new Map();
const 取 = (sel) => { const k = String(sel); if (!池.has(k)) 池.set(k, 造(k)); return 池.get(k); };
const ctx = {
  console, setTimeout, clearTimeout, Promise, JSON, Math, String, Number, Array, Object, Map, Set, Date, Error, Event: function () {},
  encodeURIComponent, decodeURIComponent, URLSearchParams, CSS: { escape: (s) => s }, innerWidth: 1440,
  document: { querySelector: 取, querySelectorAll: () => [], getElementById: (id) => (id === "mask" ? null : 取(id)),
    createElement: () => 造("new"), addEventListener() {}, removeEventListener() {}, activeElement: null,
    body: { classList: { add() {}, remove() {}, contains: () => false }, appendChild() {} } },
  window: { addEventListener() {}, removeEventListener() {} }, location: { hash: "#/workflows" },
  localStorage: { getItem: (k) => ({ "aimc.user": "U002", "aimc.proj": "p" })[k] ?? null, setItem() {}, removeItem() {} },
  crypto: { randomUUID: () => "k" + Math.random() }, URL: { createObjectURL: () => "blob:x" }, Blob: function () {},
  alert() {}, confirm: () => true, prompt: () => "x", requestAnimationFrame: (f) => setTimeout(f, 0),
  fetch: () => Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({}), text: async () => "{}" }),
};
ctx.globalThis = ctx; ctx.window = Object.assign(ctx.window, ctx); ctx.addEventListener = () => {};
vm.createContext(ctx);
try { vm.runInContext(src, ctx); } catch (e) { /* 加载路径里碰到桩没覆盖的 DOM 不要紧 */ }
const 跑 = (code) => vm.runInContext(code, ctx);

跑(`我的角色 = "editor";
图态 = { wid: "wf_t", 名称: "t", 页签: "搭建", 视图: "步骤", revision: 1, 脏: false, 编辑序号: 0, 保存态: "已保存",
  定义: { nodes: [{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { sku: { type: "string" } }, required: [] } } },
                  { id: "h", type: "http_request", config: JSON.parse(JSON.stringify(默认配置("http_request"))) },
                  { id: "end", type: "end", config: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} } }],
          edges: [{ source: "start", target: "h", port: "success" }, { source: "h", target: "end", port: "success" }] },
  布局: { start: { x: 0, y: 0 }, h: { x: 200, y: 0 }, end: { x: 400, y: 0 } },
  节点库: [{ 名: "http_request", 端口: ["success", "error"], 可用: true, 必填: ["connection_id"] },
           { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
  资源: { 模型: [], 处理要求: [], 工具: [], 角色: [],
          工具连接: [{ id: "cc1", 名: "库存接口", 适配器: "http", 允许的端点: ["https://api.a.test/v1", "https://api.a.test/v2"], 状态: "active" },
                    { id: "cc2", 名: "物流接口", 适配器: "http", 允许的端点: ["https://api.b.test"], 状态: "active" }] },
  报告: null, 版本们: [] };`);

// 找面板 HTML 里某个按钮对应的回调:按钮文字 → data-k → 控件表;第几个(同名按钮有多个时)
function 控件(html, 文字, 第几 = 0) {
  const ms = [...html.matchAll(new RegExp(`data-k="(\\d+)"[^>]*>${文字}<`, "g"))];
  const m = ms[第几];
  const fn = m ? 跑(`控件表[${m[1]}]`) : null;
  if (!fn) { ck(`面板里有第 ${第几 + 1} 个「${文字}」按钮`, false, html.slice(0, 200)); return () => {}; }
  return fn;
}
// 按 placeholder 找输入框 / 按占位选项找下拉
function 框(html, 提示) {
  const m = new RegExp(`<input data-k="(\\d+)" value="([^"]*)" placeholder="${提示}"`).exec(html);
  if (!m) { ck(`面板里有「${提示}」输入框`, false, html.slice(0, 200)); return { fn: () => {}, 值: null }; }
  return { fn: 跑(`控件表[${m[1]}]`), 值: m[2] };
}
function 选(html, 占位) {
  const m = new RegExp(`<select data-k="(\\d+)"><option value="">${占位}<`).exec(html);
  if (!m) { ck(`面板里有「${占位}」下拉`, false, html.slice(0, 200)); return () => {}; }
  return 跑(`控件表[${m[1]}]`);
}
const 面板 = () => { 跑("控件表 = []"); return 跑(`表_设置(节点("h"))`); };
const 配 = (k) => 跑(`JSON.stringify(节点("h").config${k ? "." + k : ""})`);

console.log("\n▸ ① 菜单与默认配置");
ck("「添加节点」菜单里 HTTP 请求是真节点(类型 http_request,不再是「还没做」占位)",
   跑(`菜单节点组.flatMap((g) => g[1]).some((x) => x[0] === "http_request" && x[1] === "HTTP 请求")`));
ck("在此后添加 的可加清单也有它", 跑(`步类型名.http_request === "HTTP 请求"`) && 读("app.js").includes('"tool", "http_request", "human"'));
ck("默认配置:GET + 空查询串 / 请求头 / 绑定(连接、路径不预填 —— 检查配置会报「还没选」,不是手写的)",
   跑(`JSON.stringify(默认配置("http_request"))`) === '{"method":"GET","query":{},"headers":{},"bindings":{}}', 跑(`JSON.stringify(默认配置("http_request"))`));
ck("还缺:只有「用哪条工具连接」一项", 跑(`缺项(节点("h")).join()`) === "connection_id" && 跑(`中文名("connection_id")`) === "用哪条工具连接", 跑(`缺项(节点("h"))`));

console.log("\n▸ ② 基本:连接 / 地址 / 方法 / 路径 / 查询串 / 请求头 / 上限");
let h = 面板();
ck("没选连接时:有「请选择工具连接」下拉,没有「用白名单里的哪一条地址」", h.includes("请选择工具连接") && !h.includes("用白名单里的哪一条地址"), h.slice(0, 300));
ck("说清只许访问登记过的地址、一个字节都不出白名单", h.includes("登记过的地址") && h.includes("一个字节都不会发到白名单外"));
选(h, "请选择工具连接")({ value: "cc1" });
ck("选「库存接口」→ connection_id = cc1", 配("connection_id") === '"cc1"', 配());
h = 面板();
ck("这条连接白名单有两条 → 出「用白名单里的哪一条地址」,默认第一条", h.includes("用白名单里的哪一条地址") && h.includes("https://api.a.test/v2"), h.slice(0, 300));
选(h, "第一条")({ value: "1" });
ck("选第二条 → endpoint_index = 1", 配("endpoint_index") === "1", 配());
h = 面板();
选(h, "请选择工具连接")({ value: "cc2" });
ck("换成「物流接口」→ 端点序号清掉(新连接未必有第二条)", 配("connection_id") === '"cc2"' && 配("endpoint_index") === undefined, 配());
h = 面板();
ck("只有一条白名单 → 不出地址下拉", !h.includes("用白名单里的哪一条地址"));
const 方法段 = h.slice(h.indexOf("<label class=\"f\">方法</label>"), h.indexOf("<label class=\"f\">路径</label>"));
ck("方法下拉只有 GET / HEAD(没有 POST / PUT / DELETE 可选)", /value="GET"/.test(方法段) && /value="HEAD"/.test(方法段) && !/value="(POST|PUT|DELETE|PATCH)"/.test(方法段), 方法段.slice(0, 300));
const 方法 = /<select data-k="(\d+)"><option value="">GET<\/option>/.exec(方法段);
ck("方法下拉能找到", !!方法);
if (方法) { 跑(`控件表[${方法[1]}]`)({ value: "HEAD" }); ck("选 HEAD → method = HEAD", 配("method") === '"HEAD"'); }
h = 面板();
const 路径 = 框(h, "例如 /stock 或 /orders/123");
路径.fn({ value: "  /stock  " });
ck("路径去首尾空格写进定义", 配("path") === '"/stock"', 配());
路径.fn({ value: "" });
ck("路径清空 → 删掉键(不留空串;检查配置报 HTTP_PATH_MISSING 靠的就是这个)", 配("path") === undefined, 配());
路径.fn({ value: "/stock" });
h = 面板();
控件(h, "加一项", 0)({});
ck("查询串「加一项」→ 多一个占位键、值为空", 配("query") === '{"名字":""}', 配("query"));
h = 面板();
框(h, "例如 sku").fn({ value: "sku" });
ck("改名「名字」→「sku」", 配("query") === '{"sku":""}', 配("query"));
h = 面板();
框(h, "例如 A1").fn({ value: "A1" });
ck("填值 → query.sku = A1(原样存文字,不猜数字)", 配("query") === '{"sku":"A1"}', 配("query"));
h = 面板();
控件(h, "加一项", 1)({});
ck("请求头「加一项」→ headers 多一个占位键;查询串不受影响", 配("headers") === '{"名字":""}' && 配("query") === '{"sku":"A1"}', 配());
h = 面板();
const 删 = /data-k="(\d+)" aria-label="删掉 名字"/.exec(h);
ck("请求头那一行有「删」", !!删, h.slice(-600));
if (删) { 跑(`控件表[${删[1]}]`)(); ck("删掉 → headers 回到空对象", 配("headers") === "{}", 配("headers")); }
ck("面板说清鉴权头不用填、凭据只从连接来", h.includes("凭据只从连接来"));
h = 面板();
const 上限 = 框(h, "留空 = 1 MB");
const r0 = 上限.fn({ value: "很多", parentNode: null });
ck("上限字节填「很多」→ 不写进定义", r0 === false && 配("max_bytes") === undefined, 配());
const r1 = 上限.fn({ value: "0.5", parentNode: null });
ck("上限字节填 0.5 → 不写进定义(要整数)", r1 === false && 配("max_bytes") === undefined, 配());
上限.fn({ value: "2048", parentNode: null });
ck("上限字节填 2048 → max_bytes = 2048", 配("max_bytes") === "2048", 配());
上限.fn({ value: "", parentNode: null });
ck("上限字节清空 → 删键", 配("max_bytes") === undefined, 配());

console.log("\n▸ ③ 用到的数据:三项契约");
跑("控件表 = []");
h = 跑(`表_输入(节点("h"))`);
ck("只给 path / query / headers 三项,没有「加一个字段」", ["<b>path</b>", "<b>query</b>", "<b>headers</b>"].every((s) => h.includes(s)) && !h.includes("加一个字段"), h.slice(0, 400));
const 来源们 = [...h.matchAll(/<select data-k="(\d+)"><option value="">未设置来源</g)];
ck("三项都是「未设置来源」(默认一个都没绑,不留 null)", 来源们.length === 3 && 配("bindings") === "{}", [来源们.length, 配("bindings")]);
if (来源们.length === 3) {
  跑(`控件表[${来源们[0][1]}]`)({ value: "i:sku" });
  ck("path 绑到「使用者输入 · sku」→ 结构化引用", 配("bindings") === '{"path":{"source":"input","pointer":"/sku"}}', 配("bindings"));
}

console.log("\n▸ ④ 下游能选到固定返回");
const 源 = 跑(`JSON.stringify(上游字段("end").map((x) => x[0]))`);
ck("结束能选 HTTP 请求 → url / json / status_code / execution_mode", ["n:h:url", "n:h:json", "n:h:status_code", "n:h:execution_mode"].every((k) => 源.includes(k)), 源);
ck("「结果」页签说清六项固定返回", 跑(`表_结果(节点("h"))`).includes("<b>json</b>") && 跑(`表_结果(节点("h"))`).includes("<b>execution_mode</b>"));

console.log("\n▸ ⑤ 标签与敏感度");
ck("次级标签:HTTP 请求 · 只读 · 物流接口", 跑(`次级标签(节点("h"))`) === "HTTP 请求 · 只读 · 物流接口", 跑(`次级标签(节点("h"))`));
ck("只读节点不算敏感节点(删除时允许快捷桥接)", 跑(`是敏感节点(节点("h"))`) === false);

console.log(`\n${挂.length ? "❌ " + 挂.length + " 条挂了" : "✅ HTTP 请求配置面板 " + 过 + " 条过"}`);
挂.forEach((x) => console.log("   · " + x));
process.exit(挂.length ? 1 : 0);
