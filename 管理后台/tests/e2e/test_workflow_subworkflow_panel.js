/* 编排页 · 子工作流的配置面板(11-16 三期 3-3),不起服务。
 *
 * 照 test_workflow_parallel_panel.js 的办法把三份前端跑进 vm,直接调面板函数和控件回调,验**写进定义的形状**;
 * 最后把面板写出来的图交给后端校验器真跑一遍(没给「取版本」能力,所以递归 / 等人那几条记成 CHECK_SKIPPED 警告,不算通过):
 *   ① 菜单里「子工作流」是真节点;默认配置 input_mapping 空、sub_limits 空;缺项只报「用哪一版子流程」
 *   ② 基本面板:只列**别的流程**的冻结版本(自己的不列);说明里每一版写着要什么 / 返回什么;选了版本 → input_mapping 清空
 *   ③ 「用到的数据」:没选版本只给提示;选了 → 按那一版要的输入出契约行(名字只读、必填的不能删)
 *   ④ 结果字段 = 那一版「最后返回什么」声明的字段;结束能选到
 *   ⑤ 上限两个数字框:非法值不写进定义;留空不写
 *   ⑥ 面板写出来的整张图,后端校验器一条阻断都没有;上限填成文字,后端报 SUBWORKFLOW_LIMIT_RANGE
 */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm"), cp = require("child_process");
const 读 = (f) => fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", f), "utf8");
const src = ["wf_graph.js", "wf_canvas.js", "app.js"].map(读).join("\n;\n");

let 过 = 0; const 挂 = [];
function ck(名, 真, 补) {
  console.log(`  ${真 ? "✅" : "❌"} ${名}${真 || 补 === undefined ? "" : "  " + JSON.stringify(补).slice(0, 260)}`);
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

跑(`图态 = { wid: "wf_me", 定义: { definition_schema_version: "1", kind: "workflow", nodes: [
    { id: "start", type: "start", config: { input_schema: { type: "object", properties: { sku: { type: "string" }, 门店: { type: "string" } }, required: ["sku"] } } },
    { id: "sub", type: "subworkflow", config: 默认配置("subworkflow") },
    { id: "end", type: "end", config: { output_schema: { type: "object", properties: { 结论: { type: "string" } }, required: ["结论"], additionalProperties: false }, bindings: {} } }],
  edges: [{ source: "start", target: "sub", port: "success" }, { source: "sub", target: "end", port: "success" }] },
  布局: { start: { x: 0, y: 0 }, sub: { x: 200, y: 0 }, end: { x: 400, y: 0 } },
  节点库: [{ 名: "subworkflow", 端口: ["success", "error"], 可用: true, 必填: ["workflow_version_id", "input_mapping"] },
           { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
  资源: { 模型: [], 处理要求: [], 工具: [], 角色: [], 工具连接: [],
          工作流版本: [
            { id: "wv_me1", 工作流id: "wf_me", 名: "我自己 v1", 版本: 1, 入参结构: { type: "object", properties: {}, required: [] }, 出参结构: { type: "object", properties: {} } },
            { id: "wv_stock2", 工作流id: "wf_stock", 名: "查库存 v2", 版本: 2,
              入参结构: { type: "object", properties: { sku: { type: "string" }, 备注: { type: "string" } }, required: ["sku"] },
              出参结构: { type: "object", properties: { 答: { type: "string" }, 库存数: { type: "integer" } }, required: ["答"] } },
            { id: "wv_stock1", 工作流id: "wf_stock", 名: "查库存 v1", 版本: 1, 入参结构: { type: "object", properties: {}, required: [] }, 出参结构: { type: "object", properties: {} } }] },
  报告: null, 版本们: [] };`);

const 面板 = (id) => { 跑("控件表 = []"); return 跑(`表_设置(节点("${id}"))`); };
const 选框 = (html, 前缀) => { const m = new RegExp(`${前缀}[\\s\\S]*?<select data-k="(\\d+)"`).exec(html); return m ? 跑(`控件表[${m[1]}]`) : null; };
const 框 = (html, 提示, 第几 = 0) => { const ms = [...html.matchAll(new RegExp(`data-k="(\\d+)"[^>]*placeholder="${提示}"`, "g"))]; return ms[第几] ? 跑(`控件表[${ms[第几][1]}]`) : null; };
const 配 = (k) => 跑(`JSON.stringify(节点("sub").config${k ? "." + k : ""})`);

console.log("▸ ① 菜单、默认配置、缺项");
ck("「添加节点」菜单:子工作流是真节点", 跑(`菜单节点组.flatMap((g) => g[1]).some((x) => x[0] === "subworkflow")`));
ck("步骤类型有中文名「子流程」", 跑(`步类型名.subworkflow === "子流程"`));
ck("默认配置:映射空、上限空(版本不预填)", 配() === '{"input_mapping":{},"sub_limits":{}}', 配());
ck("新放的子工作流只缺「用哪一版子流程」(映射空算没填 → 也在缺项里,选了版本后按那一版的输入再看)",
   跑(`缺项(节点("sub")).join()`) === "workflow_version_id,input_mapping", 跑(`缺项(节点("sub"))`));

console.log("\n▸ ② 基本面板:版本下拉");
let h = 面板("sub");
ck("只列别的流程的冻结版本(查库存 v1 / v2),不列这条流程自己的 v1", h.includes("查库存 v2") && h.includes("查库存 v1") && !h.includes("我自己 v1"), h.slice(0, 500));
ck("每一版说清要什么 / 返回什么", h.includes("要:sku、备注") && h.includes("返回:答、库存数"), h.slice(0, 600));
ck("说明里写清只能选版本、不能引自己、一期同步跑完不能等人", h.includes("已冻结") && h.includes("不能选这条流程自己") && h.includes("一口气跑完"), h.slice(0, 400));
跑(`节点("sub").config.input_mapping = { 旧: { source: "input", pointer: "/sku" } }`);
选框(h, "用哪一版子流程")({ value: "wv_stock2" });
ck("选了「查库存 v2」→ workflow_version_id 写进定义,旧的映射清空", 配("workflow_version_id") === '"wv_stock2"' && 配("input_mapping") === "{}", 配());

console.log("\n▸ ③ 用到的数据");
跑("控件表 = []");
h = 跑(`表_输入(节点("sub"))`);
ck("按那一版要的输入出契约行:sku(必填)、备注(选填),名字只读、没有「加一个字段」", h.includes("sku") && h.includes("备注") && !h.includes("加一个字段"), h.slice(0, 500));
跑(`节点("sub").config.input_mapping = { sku: 解引用("i:sku") }`);
ck("给 sku 选「使用者输入 · sku」→ input_mapping 是结构化引用", 配("input_mapping") === '{"sku":{"source":"input","pointer":"/sku"}}', 配("input_mapping"));
跑(`节点("sub").config.workflow_version_id = undefined`);
ck("没选版本时「用到的数据」只给提示", 跑(`表_输入(节点("sub"))`).includes("先在「基本」里选一版子流程"));
跑(`节点("sub").config.workflow_version_id = "wv_stock2"`);

console.log("\n▸ ④ 结果字段跟着那一版");
ck("结果字段 = 那一版声明的 答 / 库存数", 跑(`JSON.stringify(结果字段名(节点("sub")))`) === '["答","库存数"]', 跑(`JSON.stringify(结果字段名(节点("sub")))`));
const 末 = 跑(`JSON.stringify(上游字段("end").map((x) => x[0]))`);
ck("结束能选到 子流程 → 答 / 库存数", 末.includes('"n:sub:答"') && 末.includes('"n:sub:库存数"'), 末);
跑(`节点("end").config.bindings = { 结论: 解引用("n:sub:答") }`);
ck("「结果」页签写清返回的就是那一版「最后返回什么」", 跑(`表_结果(节点("sub"))`).includes("<b>答</b>") && 跑(`表_结果(节点("sub"))`).includes("子流程步骤"));

console.log("\n▸ ⑤ 上限");
h = 面板("sub");
const 模 = 框(h, "留空 = 跟父流程", 0), 工 = 框(h, "留空 = 跟父流程", 1);
ck("有两个上限数字框(模型 / 工具),默认空", !!模 && !!工 && 配("sub_limits") === "{}", h.slice(-600));
if (模) {
  ck("填 0 → 不写进定义", 模({ value: "0", parentNode: null }) === false && 配("sub_limits") === "{}");
  模({ value: "3", parentNode: null });
  ck("填 3 → sub_limits.max_model_turns = 3", 配("sub_limits") === '{"max_model_turns":3}', 配("sub_limits"));
}

console.log("\n▸ ⑥ 交给后端校验器");
const 校 = (定义) => {
  const py = path.join(__dirname, "..", "..", ".venv", "bin", "python");
  const code = `import sys, json; sys.path.insert(0, "services/api/app/runtime"); sys.path.insert(0, "services/api/app/contract"); import validator as V
d = json.loads(sys.stdin.read()); ps = V.校验(d, 依赖存在=lambda k, i: True)
print(json.dumps({"阻": sorted({p["code"] for p in ps if p["级别"] == V.阻断}), "跳过": [p["消息"] for p in ps if p["code"] == "CHECK_SKIPPED"]}, ensure_ascii=False))`;
  const r = cp.spawnSync(py, ["-c", code], { input: 定义, cwd: path.join(__dirname, "..", ".."), encoding: "utf8" });
  if (r.status !== 0) return { 阻: ["(校验器崩了) " + (r.stderr || "").slice(-300)] };
  return JSON.parse(r.stdout.trim());
};
const 结 = 校(跑(`JSON.stringify(图态.定义)`));
ck("面板写出来的整张图,后端校验器一条阻断都没有;并明说子流程那几条这次没查(没给取版本能力)",
   结.阻.length === 0 && 结.跳过.some((s) => s.includes("子流程")), 结);
跑(`节点("sub").config.sub_limits = { max_model_turns: "三" }`);
const 结2 = 校(跑(`JSON.stringify(图态.定义)`));
ck("上限填成文字 → 后端报 SUBWORKFLOW_LIMIT_RANGE", 结2.阻.includes("SUBWORKFLOW_LIMIT_RANGE"), 结2);

console.log(`\n${挂.length ? "❌ " + 挂.length + " 条挂了" : "✅ 子工作流配置面板 " + 过 + " 条过"}`);
挂.forEach((x) => console.log("   · " + x));
process.exit(挂.length ? 1 : 0);
