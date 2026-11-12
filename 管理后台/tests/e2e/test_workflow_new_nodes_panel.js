/* 编排页 · 列表操作 / 文档提取器的配置面板(11-12),不起服务。
 *
 * 照 test_workflow_editor_actions.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,
 * 直接调面板函数 + 面板里挂的控件回调(控件表),验**写进定义的形状**和后端校验器认的一致:
 *   ① 两个节点在「添加」菜单 / 在此后添加里可选,默认配置是空绑定(检查配置报「还没选…」,不是「手写的」)
 *   ② 列表操作:加过滤条件 → 选「大于」→ 填 100 存成数字 100(不是文字「100」);一元比较方式不带比较值;
 *      加排序 → 选方向;「只要前几个」非法值不写进定义
 *   ③ 「用到的数据」只给固定那一项(列表 / 文件),清空来源是删掉那一项(不是留一个 null)
 *   ④ 下游能在「用到的数据」里选到它们的结果(结果 / 个数 / 第一个 / 最后一个;文本 / 文件名)
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
  定义: { nodes: [{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { 单: { type: "array" }, 附件: {} }, required: [] } } },
                  { id: "lo", type: "list_operator", config: JSON.parse(JSON.stringify(默认配置("list_operator"))) },
                  { id: "doc", type: "doc_extractor", config: JSON.parse(JSON.stringify(默认配置("doc_extractor"))) },
                  { id: "end", type: "end", config: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} } }],
          edges: [{ source: "start", target: "lo", port: "success" }, { source: "lo", target: "doc", port: "success" }, { source: "doc", target: "end", port: "success" }] },
  布局: { start: { x: 0, y: 0 }, lo: { x: 200, y: 0 }, doc: { x: 400, y: 0 }, end: { x: 600, y: 0 } },
  节点库: [{ 名: "list_operator", 端口: ["success", "error"], 可用: true, 必填: ["bindings"] },
           { 名: "doc_extractor", 端口: ["success", "error"], 可用: true, 必填: ["bindings"] },
           { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
  资源: { 模型: [], 处理要求: [], 工具: [], 角色: [] }, 报告: null, 版本们: [] };`);

// 找面板 HTML 里某个按钮 / 控件对应的回调:按钮文字 → data-k → 控件表
function 控件(html, 文字) {
  const m = new RegExp(`data-k="(\\d+)"[^>]*>${文字}<`).exec(html);
  const fn = m ? 跑(`控件表[${m[1]}]`) : null;
  if (!fn) { ck(`面板里有「${文字}」这个按钮`, false, html.slice(0, 200)); return () => {}; }
  return fn;
}
const 面板 = (id) => { 跑("控件表 = []"); return 跑(`表_设置(节点("${id}"))`); };

console.log("\n▸ ① 菜单与默认配置");
ck("「添加节点」菜单:列表操作、文档提取器都是可选项(不再置灰)",
   跑(`菜单节点组.flatMap((g) => g[1]).filter((x) => x[0] === "list_operator" || x[0] === "doc_extractor").length === 2`));
ck("步骤类型有中文名", 跑(`步类型名.list_operator === "列表操作" && 步类型名.doc_extractor === "文档提取器"`));
ck("默认配置的绑定是空对象(不是 { 列表: null } —— 那会被报成「手写的」)",
   跑(`JSON.stringify(默认配置("list_operator")) === '{"bindings":{}}' && JSON.stringify(默认配置("doc_extractor")) === '{"bindings":{}}'`));
ck("还缺:用到的数据", 跑(`缺项(节点("lo")).join() === "bindings"`));

console.log("\n▸ ② 列表操作的规则");
let h = 面板("lo");
ck("面板里说清顺序、没有表达式框", h.includes("先过滤、再排序、再取前几个") && !/textarea/.test(h), h.slice(0, 200));
控件(h, "加过滤条件")({});
ck("加过滤条件 → filter 里一条、默认且", 跑(`JSON.stringify(节点("lo").config.filter)`) === '{"conditions":[{"op":"equals","value":""}],"logic":"and"}',
   跑(`JSON.stringify(节点("lo").config.filter)`));
跑(`节点("lo").config.filter.conditions[0].op = "gt"`);
跑(`节点("lo").config.filter.conditions[0].value = 列表比较值("gt", "100", "")`);
ck("「大于」填 100 → 存成数字 100", 跑(`节点("lo").config.filter.conditions[0].value === 100`));
ck("「大于」填「很多」→ 原样留着(检查配置会说要填数字,不悄悄当 0)", 跑(`列表比较值("gt", "很多", 1) === "很多"`));
ck("「等于」现在按文字比 → 填 100 仍是文字", 跑(`列表比较值("equals", "100", "") === "100"`));
ck("「等于」现在按数字比 → 填 100 是数字", 跑(`列表比较值("equals", "100", 5) === 100`));
h = 面板("lo");
控件(h, "再加一条")({});
ck("再加一条 → 默认「有这一项」,不带比较值", 跑(`JSON.stringify(节点("lo").config.filter.conditions[1])`) === '{"op":"exists"}');
ck("一元比较方式清单和后端一致", 跑(`列表一元比法.join()`) === "exists,not_exists,is_null,is_not_null");
h = 面板("lo");     // 控件回调里会重画、清空控件表 —— 每点一次都重新画一遍再找
控件(h, "加排序")({});
ck("加排序 → sort 默认从小到大", 跑(`JSON.stringify(节点("lo").config.sort)`) === '{"order":"asc"}');
h = 面板("lo");
const 前几 = /data-k="(\d+)" value="" placeholder="留空 = 全都要"/.exec(h);
ck("有「只要前几个」的数字框", !!前几, h.slice(-400));
if (前几) {
  const fn = 跑(`控件表[${前几[1]}]`);
  const r0 = fn({ value: "0", parentNode: null });
  ck("填 0 → 不写进定义", r0 === false && 跑(`节点("lo").config.limit === undefined`));
  fn({ value: "3", parentNode: null });
  ck("填 3 → limit = 3", 跑(`节点("lo").config.limit === 3`));
}

console.log("\n▸ ③ 用到的数据");
跑("控件表 = []");
h = 跑(`表_输入(节点("lo"))`);
const 选 = /<label>列表<\/label><select data-k="(\d+)"/.exec(h);
ck("列表操作「用到的数据」只有「列表」那一项", !!选 && !h.includes("加一个字段"), h.slice(0, 300));
if (选) {
  const fn = 跑(`控件表[${选[1]}]`);
  fn({ value: "i:单" });
  ck("选「使用者输入 · 单」→ bindings.列表 是结构化引用", 跑(`JSON.stringify(节点("lo").config.bindings)`) === '{"列表":{"source":"input","pointer":"/单"}}',
     跑(`JSON.stringify(节点("lo").config.bindings)`));
  fn({ value: "" });
  ck("清空来源 → 删掉那一项(不留 null)", 跑(`JSON.stringify(节点("lo").config.bindings)`) === "{}");
}
跑(`节点("doc").config.bindings = { 文件: { source: "input", pointer: "/附件" }, 多余: null }`);
跑("控件表 = []");
h = 跑(`表_输入(节点("doc"))`);
ck("文档提取器「用到的数据」只有「文件」,多出来的标出来并能一键删", h.includes("<label>文件</label>") && h.includes("「多余」"), h.slice(0, 300));
控件(h, "删掉多出来的")({});
ck("删掉多出来的 → 只剩「文件」", 跑(`Object.keys(节点("doc").config.bindings).join()`) === "文件");
h = 面板("doc");
ck("文档提取器面板说清能取的格式和失败不给空串", h.includes(".md") && h.includes("这一步会失败"), h.slice(0, 300));

console.log("\n▸ ④ 下游能选到它们的结果");
const 源 = 跑(`JSON.stringify(上游字段("end").map((x) => x[0]))`);
ck("结束能选 列表操作 → 结果 / 个数 / 第一个 / 最后一个", ["n:lo:结果", "n:lo:个数", "n:lo:第一个", "n:lo:最后一个"].every((k) => 源.includes(k)), 源);
ck("结束能选 文档提取器 → 文本 / 文件名", ["n:doc:文本", "n:doc:文件名"].every((k) => 源.includes(k)), 源);

console.log(`\n${挂.length ? "❌ " + 挂.length + " 条挂了" : "✅ 新节点配置面板 " + 过 + " 条过"}`);
挂.forEach((x) => console.log("   · " + x));
process.exit(挂.length ? 1 : 0);
