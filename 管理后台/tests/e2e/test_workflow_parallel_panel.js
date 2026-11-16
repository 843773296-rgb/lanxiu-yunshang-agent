/* 编排页 · 并行与汇总的配置面板(11-16 三期 3-2),不起服务。
 *
 * 照 test_workflow_foreach_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,直接调面板函数和控件回调,
 * 验**写进定义的形状**;最后把面板写出来的那张图交给后端校验器真跑一遍(python3 子进程调 runtime/validator.py),不另写判据:
 *   ① 菜单里「并行与汇总」是真节点;默认配置 branches 空、并发上限 1、等待策略 all_required;缺项只报「支路」
 *   ② 出口 = 每条支路一个(支路名就是出口名)+ 全部做完后 + 失败时;支路改名,挂在它上面的连线跟着改
 *   ③ 基本面板:加一条支路 / 删 / 改必需可选 / 等待策略两种 / 并发上限固定 1 不给填
 *   ④ 「用到的数据」:并行自己不取数;里面的步骤的上游选项里没有另一条支路的步骤(校验器拦的那条,面板先不摆出来)
 *   ⑤ 「放在哪个循环 / 迭代里」:普通步骤能选并行;并行自己 / 循环 / 迭代不给(不许套娃)
 *   ⑥ 结束能选到并行的 结果 / 状态 / 失败支路
 *   ⑦ 面板写出来的整张图,后端校验器一条阻断都没有;把一条支路的连线删掉,后端报的正是 PARALLEL_BRANCH_NO_EDGE
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

const 文本 = { type: "object", properties: { text: { type: "string" } }, required: ["text"], additionalProperties: false };
跑(`图态 = { 定义: { definition_schema_version: "1", kind: "workflow", nodes: [
    { id: "start", type: "start", config: { input_schema: { type: "object", properties: { sku: { type: "string" } }, required: ["sku"] } } },
    { id: "pa", type: "parallel", config: 默认配置("parallel") },
    { id: "a", type: "llm", container: "pa", config: { connection_version_id: "cv1", prompt_version_id: "p1", output_schema: ${JSON.stringify(文本)}, bindings: { 问: { source: "input", pointer: "/sku" } } } },
    { id: "b", type: "llm", container: "pa", config: { connection_version_id: "cv1", prompt_version_id: "p1", output_schema: ${JSON.stringify(文本)}, bindings: { 问: { source: "input", pointer: "/sku" } } } },
    { id: "lp", type: "loop", config: { max_iterations: 2 } },
    { id: "end", type: "end", config: { output_schema: { type: "object", properties: { 汇: { type: "object" } }, required: ["汇"], additionalProperties: false }, bindings: {} } }],
  edges: [{ source: "start", target: "pa", port: "success" }, { source: "pa", target: "end", port: "success" }] },
  布局: { start: { x: 0, y: 0 }, pa: { x: 200, y: 0 }, a: { x: 200, y: 200 }, b: { x: 400, y: 200 }, lp: { x: 600, y: 400 }, end: { x: 800, y: 0 } },
  节点库: [{ 名: "parallel", 端口: ["parallel", "success", "error"], 可用: true, 必填: ["branches", "max_concurrency", "wait_policy"] },
           { 名: "llm", 端口: ["success", "error"], 可用: true, 必填: [] }, { 名: "loop", 端口: ["loop_body", "loop_exit", "error"], 可用: true, 必填: [] },
           { 名: "foreach", 端口: ["loop_body", "loop_exit", "error"], 可用: true, 必填: [] },
           { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
  资源: { 模型: [], 处理要求: [], 工具: [], 角色: [], 工具连接: [] }, 报告: null, 版本们: [] };`);

const 面板 = (id) => { 跑("控件表 = []"); return 跑(`表_设置(节点("${id}"))`); };
const 控件 = (html, 文字, 第几 = 0) => {
  const re = new RegExp(`data-k="(\\d+)"[^>]*>${文字}`, "g"); const ms = [...html.matchAll(re)];
  return ms[第几] ? 跑(`控件表[${ms[第几][1]}]`) : null;
};
const 选框 = (html, 前缀) => { const m = new RegExp(`${前缀}[\\s\\S]*?<select data-k="(\\d+)"`).exec(html); return m ? 跑(`控件表[${m[1]}]`) : null; };
const 框 = (html, 提示, 第几 = 0) => { const ms = [...html.matchAll(new RegExp(`data-k="(\\d+)"[^>]*placeholder="${提示}"`, "g"))]; return ms[第几] ? 跑(`控件表[${ms[第几][1]}]`) : null; };
const 配 = (k) => 跑(`JSON.stringify(节点("pa").config${k ? "." + k : ""})`);

console.log("▸ ① 菜单、默认配置、缺项");
ck("「添加节点」菜单:并行与汇总是真节点(不是「还没做」占位)", 跑(`菜单节点组.flatMap((g) => g[1]).some((x) => x[0] === "parallel")`));
ck("步骤类型有中文名「并行」", 跑(`步类型名.parallel === "并行"`));
ck("默认配置:支路空、并发上限 1、等待策略 all_required", 配() === '{"branches":[],"max_concurrency":1,"wait_policy":"all_required"}', 配());
ck("新放的并行只缺「支路」", 跑(`缺项(节点("pa")).join()`) === "branches", 跑(`缺项(节点("pa"))`));

console.log("\n▸ ② 基本面板:支路增删改、等待策略、并发上限");
let h = 面板("pa");
ck("还没有支路时说清要加,并给「加一条支路」按钮;没有表达式框", h.includes("还没有支路") && h.includes("加一条支路") && !/textarea/.test(h), h.slice(0, 300));
控件(h, "加一条支路")(); h = 面板("pa"); 控件(h, "加一条支路")(); h = 面板("pa");
ck("加两条 → branches 有两条默认名(支路1 / 支路2),没写 required(默认必需)", 配("branches") === '[{"key":"支路1"},{"key":"支路2"}]', 配("branches"));
框(h, "例如 查库存")({ value: "查库存" }); h = 面板("pa");
ck("改第一条支路名 → key 跟着改", 配("branches") === '[{"key":"查库存"},{"key":"支路2"}]', 配("branches"));
let 选 = 选框(h, "要不要等它"); 选 && 选({ value: "false" }); h = 面板("pa");
ck("第一条改成「可选」→ required=false 写进定义;改回「必需」→ 这个键删掉(默认就是必需)",
   配("branches") === '[{"key":"查库存","required":false},{"key":"支路2"}]', 配("branches"));
选 = 选框(h, "要不要等它"); 选 && 选({ value: "true" }); h = 面板("pa");
ck("改回必需后键被删掉", 配("branches") === '[{"key":"查库存"},{"key":"支路2"}]', 配("branches"));
选 = 选框(h, '<label class="f">等待策略</label>');   // 「等待策略」四个字在支路的必需 / 可选说明里也出现,锚在标签上
ck("等待策略只有两种:等全部必需 / 允许部分结果(没有「任一完成即成功」)",
   h.includes('value="all_required"') && h.includes('value="allow_partial"') && !h.includes('value="any"'));
选 && 选({ value: "allow_partial" });
ck("选「允许部分结果」→ wait_policy = allow_partial", 跑(`节点("pa").config.wait_policy`) === "allow_partial");
h = 面板("pa");
ck("并发上限固定 1、不给填(没有并发上限的输入框),文案说明一期串行", !框(h, "并发上限") && h.includes("固定 <b>1</b>") && 配("max_concurrency") === "1", h.slice(-400));
ck("说清不会完成一条就宣告整组成功、支路之间不能互取", h.includes("不会完成一条就宣告整组成功") && h.includes("不能互相取结果"));

console.log("\n▸ ③ 出口与连线");
let 口 = 跑(`JSON.stringify(出口们(节点("pa")).map((o) => [o.port, o.branch_key, o.名]))`);
ck("出口 = 两条支路(支路名就是出口名)+ 全部做完后 + 失败时",
   口 === '[["parallel","查库存","支路 · 查库存"],["parallel","支路2","支路 · 支路2"],["success",null,"全部做完后"],["error",null,"失败时"]]', 口);
跑(`图态.定义.edges.push({ source: "pa", target: "a", port: "parallel", branch_key: "查库存" }, { source: "pa", target: "b", port: "parallel", branch_key: "支路2" })`);
h = 面板("pa");
框(h, "例如 查库存", 1)({ value: "查物流" });
ck("第二条支路改名「查物流」→ 挂在它上面的连线 branch_key 跟着改(不留孤线)",
   配("branches") === '[{"key":"查库存"},{"key":"查物流"}]' && 跑(`图态.定义.edges.find((e) => e.target === "b").branch_key`) === "查物流",
   [配("branches"), 跑(`JSON.stringify(图态.定义.edges)`)]);
ck("连线的口名给人看是「支路 · 查物流」", 跑(`图逻辑.口名(图态.定义.edges.find((e) => e.target === "b"))`) === "支路 · 查物流");

console.log("\n▸ ④ 用到的数据 / 上游");
跑("控件表 = []");
ck("并行自己的「用到的数据」只说明不取数(没有加字段按钮)", 跑(`表_输入(节点("pa"))`).includes("自己不取数") && !跑(`表_输入(节点("pa"))`).includes("加一个字段"));
const 上游b = 跑(`JSON.stringify(上游字段("b").map((x) => x[0]))`);
ck("支路里的步骤能取并行外面(使用者输入),但选项里没有另一条支路的步骤 a", 上游b.includes('"i:sku"') && !上游b.includes('"n:a:'), 上游b);

console.log("\n▸ ⑤ 放在哪个循环 / 迭代里");
跑(`图态.定义.nodes.push({ id: "t2", type: "llm", config: { bindings: {} } }); 图态.布局.t2 = { x: 0, y: 600 };`);
跑("控件表 = []");
h = 跑(`表_高级(节点("t2"))`);
ck("普通步骤:能选把它放进并行(选项标了「并行」),也能放进循环", h.includes('value="pa"') && h.includes("(并行)") && h.includes('value="lp"'), h.slice(0, 400));
跑("控件表 = []");
ck("并行自己不给「放进循环」的选项(不许套娃)", !跑(`表_高级(节点("pa"))`).includes("放在哪个循环 / 迭代里"));
跑("控件表 = []");
ck("循环自己也选不到并行(不许套娃)", !跑(`表_高级(节点("lp"))`).includes("放在哪个循环 / 迭代里"));
跑(`图态.定义.nodes = 图态.定义.nodes.filter((x) => x.id !== "t2" && x.id !== "lp")`);

console.log("\n▸ ⑥ 下游");
const 末 = 跑(`JSON.stringify(上游字段("end").map((x) => x[0]))`);
ck("结束能选到并行的 结果 / 状态 / 失败支路", 末.includes('"n:pa:结果"') && 末.includes('"n:pa:状态"') && 末.includes('"n:pa:失败支路"'), 末);
跑(`节点("end").config.bindings = { 汇: 解引用("n:pa:结果") }`);

console.log("\n▸ ⑦ 交给后端校验器");
跑(`节点("pa").config.wait_policy = "all_required"`);
const 校 = (定义) => {
  const py = path.join(__dirname, "..", "..", ".venv", "bin", "python");
  const code = `import sys, json; sys.path.insert(0, "services/api/app/runtime"); sys.path.insert(0, "services/api/app/contract"); import validator as V
d = json.loads(sys.stdin.read()); print(json.dumps(sorted({p["code"] for p in V.校验(d, 依赖存在=lambda k, i: True) if p["级别"] == V.阻断})))`;
  const r = cp.spawnSync(py, ["-c", code], { input: 定义, cwd: path.join(__dirname, "..", ".."), encoding: "utf8" });
  if (r.status !== 0) return ["(校验器崩了) " + (r.stderr || "").slice(-300)];
  return JSON.parse(r.stdout.trim());
};
const 阻 = 校(跑(`JSON.stringify(图态.定义)`));
ck("面板写出来的整张图,后端校验器一条阻断都没有", Array.isArray(阻) && 阻.length === 0, 阻);
const 阻2 = 校(跑(`JSON.stringify(Object.assign({}, 图态.定义, { edges: 图态.定义.edges.filter((e) => e.target !== "b") }))`));
ck("删掉一条支路的连线 → 后端报的正是 PARALLEL_BRANCH_NO_EDGE", Array.isArray(阻2) && 阻2.includes("PARALLEL_BRANCH_NO_EDGE"), 阻2);

console.log(`\n${挂.length ? "❌ " + 挂.length + " 条挂了" : "✅ 并行与汇总配置面板 " + 过 + " 条过"}`);
挂.forEach((x) => console.log("   · " + x));
process.exit(挂.length ? 1 : 0);
