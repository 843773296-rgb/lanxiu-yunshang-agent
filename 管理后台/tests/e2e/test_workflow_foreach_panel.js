/* 编排页 · 列表迭代的配置面板(11-12),不起服务。
 *
 * 照 test_workflow_new_nodes_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,
 * 直接调面板函数 + 面板里挂的控件回调(控件表),验**写进定义的形状**;最后把面板写出来的那张图
 * **交给后端校验器真跑一遍**(python3 子进程调 runtime/validator.py),不在这里另写一份判据:
 *   ① 迭代在「添加」菜单里可选;默认配置只带「整步失败」,**「最多做几项」不给默认值**(那是业务的事);出口三个
 *   ② 基本面板:每一项交出什么只列迭代里面步骤的结果;某一项失败时两种;最多做几项非法值不写进定义;里面空着时说清
 *   ③ 用到的数据只给「列表」那一项
 *   ④ 迭代里面的步骤能选「迭代 · 当前项 / 下标」,迭代自己和外面的步骤选不到;写出来的引用后端认得
 *   ⑤ 「放在哪个循环 / 迭代里」:普通步骤能选迭代;循环、迭代自己不给这个选项(不许套娃)
 *   ⑥ 结束能选到迭代的 结果 / 个数 / 失败项
 *   ⑦ 面板写出来的整张图,后端校验器一条阻断都没有;把「最多做几项」删掉,后端报的正是那一项
 */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), cp = require("child_process");
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
  定义: { definition_schema_version: "1", kind: "workflow",
          output_schema: { type: "object", properties: { r: {} }, required: ["r"], additionalProperties: false },
          nodes: [{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { 单: { type: "array" } }, required: ["单"] } } },
                  { id: "fe", type: "foreach", config: JSON.parse(JSON.stringify(默认配置("foreach"))) },
                  { id: "w", type: "llm", container: "fe", config: { connection_version_id: "cv1", prompt_version_id: "p1", bindings: {},
                    output_schema: { type: "object", properties: { text: { type: "string" } }, required: ["text"], additionalProperties: false } } },
                  { id: "lp", type: "loop", config: { max_iterations: 2, condition: { op: "exists", left: { source: "scope", pointer: "/还要" } }, loop_state: { 还要: { initial: true } } } },
                  { id: "end", type: "end", config: { output_schema: { type: "object", properties: { r: {} }, required: ["r"], additionalProperties: false }, bindings: {} } }],
          edges: [{ source: "start", target: "fe", port: "success" }, { source: "fe", target: "w", port: "loop_body" },
                  { source: "fe", target: "end", port: "loop_exit" }] },
  布局: { start: { x: 0, y: 0 }, fe: { x: 200, y: 0 }, w: { x: 200, y: 200 }, lp: { x: 400, y: 400 }, end: { x: 600, y: 0 } },
  节点库: [{ 名: "foreach", 端口: ["loop_body", "loop_exit", "error"], 可用: true, 必填: ["bindings", "item_output", "item_failure_policy", "max_items"] },
           { 名: "llm", 端口: ["success", "error"], 可用: true, 必填: [] }, { 名: "loop", 端口: ["loop_body", "loop_exit", "error"], 可用: true, 必填: [] },
           { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
  资源: { 模型: [], 处理要求: [], 工具: [], 角色: [] }, 报告: null, 版本们: [] };`);

const 面板 = (id) => { 跑("控件表 = []"); return 跑(`表_设置(节点("${id}"))`); };
const 选框 = (html, 前缀) => { const m = new RegExp(`${前缀}[\\s\\S]*?<select data-k="(\\d+)"`).exec(html); return m ? 跑(`控件表[${m[1]}]`) : null; };

console.log("\n▸ ① 菜单、默认配置、出口");
ck("「添加节点」菜单:迭代是可选项", 跑(`菜单节点组.flatMap((g) => g[1]).some((x) => x[0] === "foreach")`));
ck("步骤类型有中文名「迭代」", 跑(`步类型名.foreach === "迭代"`));
ck("默认配置只带「整步失败」和空绑定 —— 最多做几项不给默认值",
   跑(`JSON.stringify(默认配置("foreach"))`) === '{"bindings":{},"item_failure_policy":"fail"}', 跑(`JSON.stringify(默认配置("foreach"))`));
ck("新放的迭代还缺:用到的数据 / 每一项交出什么 / 最多做几项", 跑(`缺项(节点("fe")).join()`) === "bindings,item_output,max_items", 跑(`缺项(节点("fe")).join()`));
ck("出口三个:每一项做 / 全部做完后 / 失败时(端口和有界循环同一套)",
   跑(`JSON.stringify(出口们(节点("fe")).map((o) => [o.port, o.名]))`) === '[["loop_body","每一项做"],["loop_exit","全部做完后"],["error","失败时"]]',
   跑(`JSON.stringify(出口们(节点("fe")))`));

console.log("\n▸ ② 基本面板");
let h = 面板("fe");
ck("说清一次一项、里面能取当前项 / 下标;没有表达式框", h.includes("一次一项") && h.includes("迭代 · 当前项") && !/textarea/.test(h), h.slice(0, 200));
ck("「每一项交出什么」只列迭代里面步骤的结果(AI 处理 → text),不列外面的", h.includes('value="n:w:text"') && !h.includes('value="i:单"'), h.slice(0, 400));
let fn = 选框(h, "每一项做完交出什么");
if (fn) { fn({ value: "n:w:text" }); }
ck("选了 → item_output 是指向里面那一步的结构化引用",
   跑(`JSON.stringify(节点("fe").config.item_output)`) === '{"source":"node","node_id":"w","pointer":"/text"}', 跑(`JSON.stringify(节点("fe").config.item_output)`));
h = 面板("fe");
fn = 选框(h, "某一项失败时");
ck("某一项失败时有两种:整步失败 / 留空位接着做(没有「去掉失败项」)",
   h.includes('value="fail"') && h.includes('value="continue"') && !h.includes('value="remove"'));
if (fn) fn({ value: "continue" });
ck("选「留空位」→ item_failure_policy = continue", 跑(`节点("fe").config.item_failure_policy`) === "continue");
h = 面板("fe");
const 最多 = /data-k="(\d+)" value="" placeholder="按这条流程一次该处理多少条填"/.exec(h);
ck("有「最多做几项」的数字框,而且是空的", !!最多, h.slice(-500));
if (最多) {
  const f = 跑(`控件表[${最多[1]}]`);
  ck("填 0 → 不写进定义", f({ value: "0", parentNode: null }) === false && 跑(`节点("fe").config.max_items === undefined`));
  ck("填 2.5 → 不写进定义(不静默截成 2)", f({ value: "2.5", parentNode: null }) === false && 跑(`节点("fe").config.max_items === undefined`));
  f({ value: "30", parentNode: null });
  ck("填 30 → max_items = 30", 跑(`节点("fe").config.max_items === 30`));
}
跑(`图态.定义.nodes.push({ id: "fe2", type: "foreach", config: 默认配置("foreach") })`);
h = 面板("fe2");
ck("迭代里面还没步骤时,说清先往里放步骤(而不是给一个空下拉)", h.includes("迭代里面还没有步骤"), h.slice(0, 300));
跑(`图态.定义.nodes = 图态.定义.nodes.filter((x) => x.id !== "fe2")`);

console.log("\n▸ ③ 用到的数据");
跑("控件表 = []");
h = 跑(`表_输入(节点("fe"))`);
const 选 = /<label>列表<\/label><select data-k="(\d+)"/.exec(h);
ck("迭代「用到的数据」只有「列表」那一项", !!选 && !h.includes("加一个字段"), h.slice(0, 300));
if (选) {
  跑(`控件表[${选[1]}]`)({ value: "i:单" });
  ck("选「使用者输入 · 单」→ bindings.列表 是结构化引用", 跑(`JSON.stringify(节点("fe").config.bindings)`) === '{"列表":{"source":"input","pointer":"/单"}}',
     跑(`JSON.stringify(节点("fe").config.bindings)`));
}

console.log("\n▸ ④ 当前项 / 下标");
const 里 = 跑(`JSON.stringify(上游字段("w").map((x) => x[0]))`);
ck("迭代里面的步骤能选「迭代 · 当前项」「迭代 · 下标」", 里.includes('"s:当前项"') && 里.includes('"s:下标"'), 里);
ck("迭代自己、外面的结束都选不到当前项 / 下标",
   !跑(`JSON.stringify(上游字段("fe"))`).includes("s:当前项") && !跑(`JSON.stringify(上游字段("end"))`).includes("s:当前项"));
跑(`节点("w").config.bindings = { 这一条: 解引用("s:当前项"), 第几条: 解引用("s:下标") }`);
ck("选「当前项」写进定义是 scope 引用 /当前项", 跑(`JSON.stringify(节点("w").config.bindings.这一条)`) === '{"source":"scope","pointer":"/当前项"}');

console.log("\n▸ ⑤ 放在哪个循环 / 迭代里");
跑(`图态.定义.nodes.push({ id: "t2", type: "llm", config: { bindings: {} } }); 图态.布局.t2 = { x: 0, y: 600 };`);
跑("控件表 = []");
h = 跑(`表_高级(节点("t2"))`);
ck("普通步骤:能选把它放进迭代(也能放进循环)", h.includes("放在哪个循环 / 迭代里") && h.includes('value="fe"') && h.includes('value="lp"'), h.slice(0, 300));
跑("控件表 = []");
ck("循环自己不给「放进迭代」的选项(不许套娃)", !跑(`表_高级(节点("lp"))`).includes("放在哪个循环 / 迭代里"));
跑("控件表 = []");
ck("迭代自己不给「放进循环」的选项(不许套娃)", !跑(`表_高级(节点("fe"))`).includes("放在哪个循环 / 迭代里"));
跑(`图态.定义.nodes = 图态.定义.nodes.filter((x) => x.id !== "t2" && x.id !== "lp")`);

console.log("\n▸ ⑥ 下游能选到迭代的结果");
const 源 = 跑(`JSON.stringify(上游字段("end").map((x) => x[0]))`);
ck("结束能选 迭代 → 结果 / 个数 / 失败项", ["n:fe:结果", "n:fe:个数", "n:fe:失败项"].every((k) => 源.includes(k)), 源);
ck("结束选不到迭代里面那一步的结果(出了迭代就没有)", !源.includes("n:w:text"), 源);
跑(`节点("end").config.bindings = { r: 解引用("n:fe:结果") }`);

console.log("\n▸ ⑦ 面板写出来的图,交给后端校验器真跑");
const 校验 = (定义) => {
  const py = `import json,sys\nsys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "..", "services", "api", "app", "runtime"))})\n` +
    `import validator as V\nd=json.load(sys.stdin)\nprint(json.dumps(sorted({p["code"]+"@"+str(p.get("field_path")) for p in V.校验(d, 依赖存在=lambda a,b: True) if p["级别"]==V.阻断}), ensure_ascii=False))`;
  const r = cp.spawnSync("python3", ["-c", py], { input: JSON.stringify(定义), encoding: "utf8" });
  if (r.status !== 0) return ["校验器没跑起来:" + (r.stderr || "").slice(-300)];
  return JSON.parse(r.stdout);
};
const 定义 = JSON.parse(跑(`JSON.stringify(图态.定义)`));
let 码 = 校验(定义);
ck("一条阻断都没有(面板写的形状就是后端认的形状)", Array.isArray(码) && 码.length === 0, 码);
const 去 = JSON.parse(JSON.stringify(定义)); delete 去.nodes.find((n) => n.id === "fe").config.max_items;
码 = 校验(去);
ck("把「最多做几项」删掉 → 后端只报这一项还没填(NODE_MISSING_CONFIG@config.max_items)",
   JSON.stringify(码) === '["NODE_MISSING_CONFIG@config.max_items"]', 码);
const 错 = JSON.parse(JSON.stringify(定义)); 错.nodes.find((n) => n.id === "w").config.bindings.这一条 = { source: "scope", pointer: "/item" };
码 = 校验(错);
ck("里面取了 /item(照抄 Dify 的名字)→ 后端报 FOREACH_SCOPE_UNKNOWN", 码.some((x) => x.startsWith("FOREACH_SCOPE_UNKNOWN")), 码);

console.log(`\n${挂.length ? "❌ " + 挂.length + " 条挂了" : "✅ 列表迭代配置面板 " + 过 + " 条过"}`);
挂.forEach((x) => console.log("   · " + x));
process.exit(挂.length ? 1 : 0);
