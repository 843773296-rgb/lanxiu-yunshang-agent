/* 编排页 · 知识检索的配置面板(11-20,三期 3-5 做通),不起服务。
 *
 * 照 test_workflow_new_nodes_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,直接调面板函数 + 控件回调,验写进定义的形状:
 *   ① 面板里能选资料库、检索配置版本(此前这个节点没有面板,「查哪个资料库」没地方选)
 *   ② 选资料库 → 顺手写 knowledge_base_id + index_build_id(最新就绪的索引);没就绪索引的库 → 不写索引、面板标红
 *   ③ 选了检索配置 → 「召回设置」只读块列候选数 / 最终片段数 / 召回方式 / 上下文预算;不摆改数的框
 *   ④ 「用到的数据」只给固定那一项「问题」(契约行,名字只读)
 *   ⑤ 下游能选到它的结果(片段 / 证据 / 召回数 / 选了几片 …)
 *   ⑥ 项目没有资料库 → 一句人话,不是空下拉
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
  return { id, value: "", textContent: "", style: { setProperty() {} }, dataset: {}, disabled: false, hidden: false, className: "", checked: false,
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

function 装(资源 = {}) {
  跑(`我的角色 = "editor";
  图态 = { wid: "wf_t", 名称: "t", 页签: "搭建", 视图: "步骤", revision: 1, 脏: false, 编辑序号: 0, 保存态: "已保存", 选中: "q", 面板页: "设置",
    定义: { nodes: [{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { 问题: { type: "string" } }, required: ["问题"] } } },
                    { id: "q", type: "retrieve", config: {} },
                    { id: "end", type: "end", config: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} } }],
            edges: [{ source: "start", target: "q", port: "success" }, { source: "q", target: "end", port: "success" }] },
    布局: { start: { x: 0, y: 0 }, q: { x: 200, y: 0 }, end: { x: 400, y: 0 } },
    节点库: [{ 名: "start", 端口: ["success"], 可用: true }, { 名: "end", 端口: [], 可用: true },
             { 名: "retrieve", 端口: ["success", "error"], 可用: true, 必填: ["knowledge_base_id", "retrieval_config_version_id"] }],
    资源: Object.assign({ 模型: [], 处理要求: [], 工具: [], 角色: [], 术语: [], 资料库: [], 检索配置: [] }, ${JSON.stringify(资源)}), 报告: null, 版本们: [] };`);
}
const 面板 = () => { 跑("控件表 = []"); return 跑(`表_设置(节点("q"))`); };
const cfg = () => 跑(`节点("q").config`);
// 资源选择器里的下拉:按「请选择xx」占位找到那个 select 的控件号
function 选(html, 种类, 值) {
  const re = new RegExp(`<select data-k="(\\d+)"><option value="">请选择${种类}</option>`);
  const m = re.exec(html);
  if (!m) { ck(`面板里有「${种类}」的下拉`, false, html.slice(0, 300)); return; }
  跑(`控件表[${m[1]}]`)({ value: 值 });
}

const 资源 = {
  资料库: [{ id: "kb1", 名: "澜绣领域知识", 状态: "active", 就绪索引: "ib1", 索引用的配置: "rc1" },
          { id: "kb2", 名: "空库", 状态: "active", 就绪索引: null, 索引用的配置: null }],
  检索配置: [{ id: "rc1", 名: "候选 12 条 · 最终 4 片 · vector", 候选数: 12, 最终片段数: 4, 召回方式: ["vector"], 上下文预算: 3000, 精排: null, 建于: "2026-11-20T10:00:00" }],
};

console.log("\n▸ ① 面板能选资料库 / 检索配置");
装(资源);
let h = 面板();
ck("有「查哪个资料库」和「怎么查(检索配置版本)」两个下拉", /请选择资料库/.test(h) && /请选择检索配置/.test(h), h.slice(0, 400));
ck("资料库选项里写明有没有就绪索引", /澜绣领域知识/.test(h) && /空库/.test(h));
ck("还没选 → 不摆「召回设置」块", !/召回设置/.test(h));

console.log("\n▸ ② 选资料库 → 顺手写索引(最新就绪)和默认检索配置");
选(h, "资料库", "kb1");
ck("knowledge_base_id=kb1、index_build_id=ib1、检索配置默认跟索引用的那一版 rc1", cfg().knowledge_base_id === "kb1" && cfg().index_build_id === "ib1" && cfg().retrieval_config_version_id === "rc1", cfg());
h = 面板();
ck("面板写明「用的索引:ib1」", /用的索引:ib1/.test(h), h.slice(0, 400));
选(h, "资料库", "kb2");
ck("换成没就绪索引的库 → index_build_id 删掉(不留旧的)、配置保留", cfg().knowledge_base_id === "kb2" && cfg().index_build_id === undefined && cfg().retrieval_config_version_id === "rc1", cfg());
h = 面板();
ck("面板标红「还没有「已就绪」的索引」", /ferr[^<]*<\/div>|还没有「已就绪」的索引/.test(h) && /还没有「已就绪」的索引/.test(h), h.slice(0, 600));
选(h, "资料库", "");
ck("清掉资料库 → 两个 id 都没了", cfg().knowledge_base_id === undefined && cfg().index_build_id === undefined, cfg());

console.log("\n▸ ③ 召回设置只读块");
选(面板(), "资料库", "kb1");
h = 面板();
ck("选了配置 → 「召回设置(只读…)」块列出候选数 12、最终片段数 4、vector、预算 3000",
   /召回设置\(只读/.test(h) && /<b>12<\/b>/.test(h) && /<b>4<\/b>/.test(h) && /<b>vector<\/b>/.test(h) && /<b>3000<\/b>/.test(h), h.slice(h.indexOf("召回设置"), h.indexOf("召回设置") + 600));
ck("精排没配 → 写「没配」;阈值写明我们没有这一项", /精排:没配/.test(h) && /分数阈值:我们没有这一项/.test(h));
const 块 = h.slice(h.indexOf("召回设置"), h.indexOf("要查的话在下面"));
ck("只读块里没有输入框(不在节点里改口径)", !/<input|<select|<textarea/.test(块), 块.slice(0, 300));
ck("写明要改去知识库建新版、重建索引", /新建一版检索配置并重建索引/.test(h));

console.log("\n▸ ④ 用到的数据:固定一项「问题」");
h = 跑(`表_输入(节点("q"))`);
ck("契约行「问题」·必填,名字只读(不是可改名的字段框)", /<b>问题<\/b>/.test(h) && /必填/.test(h), h.slice(0, 400));
ck("说明里写了绑什么", /要查的话/.test(h));

console.log("\n▸ ⑤ 下游能选到它的结果");
const 出 = 跑(`结果字段名(节点("q"))`);
ck("结果字段:片段 / 证据 / 召回数 / 选了几片 / 原问 / 改写 / 试跑id / execution_mode", JSON.stringify(出) === JSON.stringify(["片段", "证据", "召回数", "选了几片", "原问", "改写", "试跑id", "execution_mode"]), 出);
const 源 = 跑(`上游字段("end").map((x) => x[0])`);
ck("结束节点的「用到的数据」来源里有「q · 证据」", 源.some((v) => v === "n:q:证据"), 源);

console.log("\n▸ ⑥ 项目没有资料库 → 一句人话");
装({});
h = 面板();
ck("写「这个项目还没有资料库」,没有空下拉", /这个项目还没有资料库/.test(h) && !/请选择资料库/.test(h), h.slice(0, 400));
ck("检索配置也一样", /还没有检索配置版本/.test(h));

console.log();
if (挂.length) { console.log(`❌ ${挂.length} 条没过:${挂.join(" / ")}`); process.exit(1); }
console.log(`✅ 知识检索配置面板 ${过} 条过`);
