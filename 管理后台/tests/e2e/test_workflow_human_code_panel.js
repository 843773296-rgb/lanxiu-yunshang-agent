/* 编排页 · 人工介入表单化 + 代码执行的配置面板(11-20 夜),不起服务。
 *
 * 照 test_workflow_retrieve_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,直接调面板函数 + 控件回调,验写进定义的形状:
 *   ① 人工介入:面板有说明框 / 字段表 / 按钮表 / 通知连接;「加一个按钮」写进 actions、画布出口按按钮分路(每个按钮一个「分支」口 + 失败时);
 *      改按钮标识把挂在它上面的线一起改;删按钮连线一起删;「加一个字段」写进 form_fields;结果字段名带字段名和 __action_id
 *   ② 代码执行:默认配置是能跑的骨架 + 空结果(检查配置会报);面板有代码框 / 返回什么 / 两个上限;非管理员看到提醒;
 *      菜单里非管理员置灰(说明「要管理员添加」)、管理员能点;「用到的数据」= input_mapping;结果字段名按 output_schema;能单测
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

function 装(角色 = "editor") {
  跑(`我的角色 = ${JSON.stringify(角色)};
  图态 = { wid: "wf_t", 名称: "t", 页签: "搭建", 视图: "步骤", revision: 1, 脏: false, 编辑序号: 0, 保存态: "已保存", 选中: "h", 面板页: "设置",
    定义: { nodes: [{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { 摘要: { type: "string" } }, required: ["摘要"] } } },
                    { id: "h", type: "human", config: { request_kind: "核对", candidate_roles: ["admin"], expires_at_policy: { 小时: 24, 到期: "fail" },
                                                        payload_binding: { 摘要: { source: "input", pointer: "/摘要" } } } },
                    { id: "c", type: "code", config: JSON.parse(JSON.stringify(默认配置("code"))) },
                    { id: "甲", type: "template", config: { template: "a", bindings: {} } },
                    { id: "end", type: "end", config: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} } }],
            edges: [{ source: "start", target: "h", port: "success" }, { source: "h", target: "c", port: "success" }, { source: "c", target: "end", port: "success" }] },
    布局: { start: { x: 0, y: 0 }, h: { x: 200, y: 0 }, c: { x: 400, y: 0 }, 甲: { x: 400, y: 120 }, end: { x: 600, y: 0 } },
    节点库: [{ 名: "start", 端口: ["success"], 可用: true }, { 名: "end", 端口: [], 可用: true },
             { 名: "human", 端口: ["success", "error", "branch"], 可用: true, 必填: ["request_kind", "candidate_roles", "expires_at_policy"] },
             { 名: "code", 端口: ["success", "error"], 可用: true, 必填: ["code", "output_schema"] },
             { 名: "template", 端口: ["success"], 可用: true }],
    资源: { 模型: [], 处理要求: [], 工具: [], 角色: [{ 码: "admin", 中文: "管理员", 能审批: true }], 术语: [], 工具连接: [{ id: "cc1", 名: "飞书群机器人", 允许的端点: ["https://open.feishu.cn/open-apis/bot/v2/hook"], 状态: "active" }] },
    报告: null, 版本们: [] };`);
}
const 面板 = (id) => { 跑("控件表 = []"); return 跑(`表_设置(节点("${id}"))`); };
const cfg = (id) => 跑(`节点("${id}").config`);
// 按按钮文字找控件回调(data-k 在按钮上)
function 按(html, 文字) {
  const m = new RegExp(`data-k="(\\d+)"[^>]*>${文字}<`).exec(html);
  if (!m) { ck(`面板里有「${文字}」`, false, html.slice(0, 300)); return () => {}; }
  return 跑(`控件表[${m[1]}]`);
}

console.log("\n▸ ① 人工介入表单化");
装();
let h = 面板("h");
ck("面板有:给核对人看的说明 / 要填的字段 / 按钮 / 飞书通知四块", /给核对人看的说明/.test(h) && /要核对人填的字段/.test(h) && /按钮\(照 Dify/.test(h) && /推一条飞书通知/.test(h), h.slice(0, 300));
ck("没配按钮时写明「通过 / 退回」照旧", /没配按钮/.test(h));
按(h, "加一个按钮")();
ck("「加一个按钮」→ actions 多一个 按钮1", JSON.stringify(cfg("h").actions) === JSON.stringify([{ id: "按钮1", 样式: "默认" }]), cfg("h").actions);
按(面板("h"), "加一个按钮")();
ck("再加 → 按钮2(不重名)", (cfg("h").actions || []).map((a) => a.id).join() === "按钮1,按钮2", cfg("h").actions);
let 口 = 跑(`图逻辑.出口们(节点("h"), 元)`);
ck("画布出口:每个按钮一个「分支」口 + 超时(11-21 照 Dify)+ 失败时", JSON.stringify(口.map((o) => [o.port, o.branch_key])) === JSON.stringify([["branch", "按钮1"], ["branch", "按钮2"], ["timeout", null], ["error", null]]), 口);
跑(`图态.定义.edges = 图态.定义.edges.filter((e) => e.source !== "h").concat([{ source: "h", target: "c", port: "branch", branch_key: "按钮1" }, { source: "h", target: "甲", port: "branch", branch_key: "按钮2" }])`);
let r = 跑(`图逻辑.人工按钮改名(图态.定义, "h", "按钮1", "顾客责任")`);
ck("改按钮标识 → 挂在它上面的线跟着改", r.可以 === true && 跑(`图态.定义.edges.filter((e) => e.source === "h").map((e) => e.branch_key).join()`) === "顾客责任,按钮2", r);
r = 跑(`图逻辑.人工按钮改名(图态.定义, "h", "按钮2", "顾客责任")`);
ck("改成重名 → 拒", r.可以 === false && /已经有/.test(r.为什么), r);
r = 跑(`图逻辑.删人工按钮(图态.定义, "h", 1)`);
ck("删按钮2 → 它那条线一起删、按钮只剩 顾客责任", r.键 === "按钮2" && r.删边.length === 1 && 跑(`图态.定义.edges.filter((e) => e.source === "h").length`) === 1 && (cfg("h").actions || []).map((a) => a.id).join() === "顾客责任", r);
h = 面板("h");
ck("配了按钮后面板不再写「没配按钮」,表里有 顾客责任", !/没配按钮/.test(h) && /顾客责任/.test(h), h.slice(0, 400));
按(h, "加一个字段")();
ck("「加一个字段」→ form_fields 多一个 字段1(段落、选填)", JSON.stringify(cfg("h").form_fields) === JSON.stringify([{ name: "字段1", type: "段落", required: false }]), cfg("h").form_fields);
const 出 = 跑(`结果字段名(节点("h"))`);
ck("结果字段名:决定 / 定稿 / 理由 / 处理人 + 字段1 + __action_id", JSON.stringify(出) === JSON.stringify(["决定", "定稿", "理由", "处理人", "字段1", "__action_id"]), 出);
ck("「通知连接」下拉列出工具连接", /飞书群机器人/.test(h), h.slice(h.indexOf("飞书通知"), h.indexOf("飞书通知") + 400));
ck("类型说明里写了按钮标识 / __action_id", /__action_id/.test(跑(`表_结果(节点("h"))`)));

console.log("\n▸ ② 代码执行");
装("editor");
const 默 = 跑(`默认配置("code")`);
ck("默认配置:python、main 骨架、空的 input_mapping、空结果、上限 5 秒 64 MB", 默.language === "python" && /def main\(\*\*inputs\)/.test(默.code) && JSON.stringify(默.input_mapping) === "{}"
   && Object.keys(默.output_schema.properties).length === 0 && 默.sub_limits.timeout_seconds === 5 && 默.sub_limits.memory_mb === 64, 默);
h = 面板("c");
ck("面板有代码框、「返回什么」表、两个上限", /data-lb="代码"/.test(h) && /返回什么/.test(h) && /限时\(秒,最多 5\)/.test(h) && /内存\(MB,最多 64\)/.test(h), h.slice(0, 400));
ck("非管理员看到「只有管理员能加或改代码」提醒", /只有<b>管理员<\/b>能加或改代码/.test(h));
ck("写明沙箱:不联网、不读写文件、不起进程", /不联网、不读写文件、不起进程/.test(h));
装("admin");
h = 面板("c");
ck("管理员没有那条提醒", !/只有<b>管理员<\/b>能加或改代码/.test(h));
ck("菜单项:管理员能点代码执行(不置灰)", !/libit off/.test(跑(`菜单项("code", "代码执行", "码", "蓝")`)), 跑(`菜单项("code", "代码执行", "码", "蓝")`).slice(0, 200));
装("editor");
const 项 = 跑(`菜单项("code", "代码执行", "码", "蓝")`);
ck("菜单项:编辑者置灰,说明「要管理员添加」", /libit off/.test(项) && /要管理员添加/.test(项), 项.slice(0, 200));
ck("「可加」清单里有 code;单测类型里有 code", 跑(`单测类型.code`) === "代码执行" && 跑(`步类型名.code`) === "代码执行");
h = 跑(`表_输入(节点("c"))`);
ck("用到的数据 = 输入变量(input_mapping),写明变量名 = main 的参数名", /main 的参数名/.test(h), h.slice(0, 200));
跑(`节点("c").config.output_schema = { type: "object", properties: { 和: { type: "integer" }, 话: { type: "string" } }, required: ["和"] }`);
ck("结果字段名按「返回什么」声明", JSON.stringify(跑(`结果字段名(节点("c"))`)) === JSON.stringify(["和", "话"]));

console.log();
if (挂.length) { console.log(`❌ ${挂.length} 条没过:${挂.join(" / ")}`); process.exit(1); }
console.log(`✅ 人工介入表单化 + 代码执行面板 ${过} 条过`);
