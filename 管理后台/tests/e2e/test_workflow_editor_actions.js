/* 编排页 · 编辑器的保存与命令层(交互控件详细设计 V1.0 §10 · T13 T14 T20,外加撤销 / 只读),不起服务。
 *
 * 照 index.html 的顺序把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,fetch 整个桩掉:
 *   · 草稿 PATCH 可以「挂住」—— 用来造「保存发出去之后用户又改了」(T13)
 *   · 可以回 500 / 409 —— 失败和冲突时本页修改不许丢、不许自动刷新(T14)
 * 拖拽、连线这些手势在 test_workflow_editor_browser.py 里用真浏览器验;这一份验的是**状态对不对**。
 */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const 读 = (f) => fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", f), "utf8");
const src = ["wf_graph.js", "wf_canvas.js", "app.js"].map(读).join("\n;\n");

let 过 = 0; const 挂 = []; let 跑完了 = false;
// ⚠️ 某个保存永远等不到返回时,脚本到不了结尾,而 node 会在事件循环空了之后**以 0 退出** ——
// 「卡住了」和「全过了」在退出码上一模一样(咬合重放时逮到的)。没跑到结尾一律算失败
process.on("exit", (码) => { if (!跑完了 && 码 === 0) { console.log("\n❌ 没跑到结尾(有个等待永远没回来)—— 不算通过"); process.exitCode = 1; } });
function ck(名, 真, 补) {
  console.log(`  ${真 ? "✅" : "❌"} ${名}${真 || 补 === undefined ? "" : "  " + JSON.stringify(补).slice(0, 200)}`);
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
let 请求们 = [], 草稿回 = 200, 挂住 = null, 弹层们 = [], 弹框 = [];
const 回 = (status, body) => Promise.resolve({ ok: status < 400, status, headers: { get: () => "application/json" },
  json: async () => body, text: async () => JSON.stringify(body) });
const ctx = {
  console, setTimeout, clearTimeout, Promise, JSON, Math, String, Number, Array, Object, Map, Set, Date, Error, Event: function () {},
  encodeURIComponent, decodeURIComponent, URLSearchParams, CSS: { escape: (s) => s }, innerWidth: 1440,
  document: { querySelector: 取, querySelectorAll: () => [], getElementById: (id) => (id === "mask" ? null : 取(id)),
    createElement: () => 造("new"), addEventListener() {}, removeEventListener() {}, activeElement: null,
    body: { classList: { add() {}, remove() {}, contains: () => false }, appendChild: (el) => 弹层们.push(String(el.innerHTML || "")) } },
  window: { addEventListener() {}, removeEventListener() {} }, location: { hash: "#/workflows" },
  localStorage: { getItem: (k) => ({ "aimc.user": "U002", "aimc.proj": "p" })[k] ?? null, setItem() {}, removeItem() {} },
  crypto: { randomUUID: () => "k" + Math.random() }, URL: { createObjectURL: () => "blob:x" }, Blob: function () {},
  alert: (m) => 弹框.push(String(m)), confirm: () => true, prompt: () => "x",
  requestAnimationFrame: (f) => setTimeout(f, 0),
  fetch: (u, o) => {
    const 方法 = (o && o.method) || "GET", 地址 = String(u);
    请求们.push({ 方法, 地址, 体: o && o.body ? JSON.parse(o.body) : null, 头: (o && o.headers) || {} });
    if (方法 === "PATCH" && 地址.includes("/draft")) {
      if (挂住) return new Promise((r) => { 挂住.放 = () => r(回(200, { revision: 挂住.rev })); });
      if (草稿回 !== 200) return 回(草稿回, { code: 草稿回 === 409 ? "REVISION_CONFLICT" : "BOOM", message: "桩", advice: "桩" });
      return 回(200, { revision: (请求们.filter((x) => x.方法 === "PATCH").length) + 10 });
    }
    return 回(200, {});
  },
};
ctx.globalThis = ctx; ctx.window = Object.assign(ctx.window, ctx); ctx.addEventListener = () => {};
vm.createContext(ctx);
try { vm.runInContext(src, ctx); } catch (e) { /* 加载路径里碰到桩没覆盖的 DOM 不要紧 */ }
const 跑 = (code) => vm.runInContext(code, ctx);

ck("三份脚本加载后,命令层和保存都挂出来了", 跑("typeof 改图 === 'function' && typeof 做_存草稿 === 'function' && typeof 图逻辑 === 'object'"));

function 新图态() {
  跑(`我的角色 = "editor";`);     // 桩里没走登录那一步;只读那条下面单独验
  跑(`图态 = { wid: "wf_t", 名称: "t", 页签: "概览", 视图: "步骤", revision: 7, 脏: false, 编辑序号: 0, 保存态: "已保存",
    定义: { nodes: [{ id: "start", type: "start", config: {} }, { id: "llm_1", type: "llm", name: "整理", config: {} },
                    { id: "end", type: "end", config: {} }],
            edges: [{ source: "start", target: "llm_1", port: "success" }, { source: "llm_1", target: "end", port: "success" }] },
    布局: { start: { x: 0, y: 0 }, llm_1: { x: 200, y: 0 }, end: { x: 400, y: 0 } },
    节点库: [{ 名: "llm", 端口: ["success", "error"], 可用: true }, { 名: "start", 端口: ["success"] }, { 名: "end", 端口: [] }],
    资源: { 模型: [], 处理要求: [], 工具: [], 角色: [] }, 报告: null, 版本们: [] };`);
}

(async () => {
  console.log("\n▸ 命令层:改图记撤销、标未保存;撤销 / 重做回到完整状态");
  新图态();
  跑(`改图("改名称", () => { 节点("llm_1").name = "整理问题"; })`);
  ck("改了 → 标未保存、记一条历史", 跑("图态.脏 && 图态.保存态 === '未保存' && 历史().条数() === 1"));
  跑(`改图("什么都没改", () => {})`);
  ck("什么都没改 → 不记历史", 跑("历史().条数() === 1"));
  跑(`改图("校验没过", () => { 节点("llm_1").name = "坏的"; return false; })`);
  ck("fn 返回 false → 回到改之前(不留半次修改)", 跑("节点('llm_1').name === '整理问题' && 历史().条数() === 1"));
  try { 跑(`改图("抛错", () => { 节点("llm_1").name = "半截"; throw new Error("x"); })`); } catch (e) { /* 预期 */ }
  ck("fn 抛错 → 也回到改之前", 跑("节点('llm_1').name === '整理问题'"));
  跑("撤销()");
  ck("撤销 → 名称回到原来", 跑("节点('llm_1').name === '整理'"));
  跑("重做()");
  ck("重做 → 又回来", 跑("节点('llm_1').name === '整理问题'"));

  console.log("\n▸ 删除步骤:默认不桥接;无影响的直接删 + 可撤销(W28)");
  新图态();
  跑(`弹_删除(["llm_1"])`);
  ck("有连线的步骤 → 先弹影响,不直接删", 跑("!!节点('llm_1')") && 弹层们.some((h) => h.includes("2</b> 条连线")), 弹层们.slice(-1));
  跑(`关弹层(); 图逻辑.删节点(图态.定义, 图态.布局, ["llm_1"]); `);
  ck("默认删除 → 开始 和 结束 之间没有被自动接上", 跑("!图态.定义.edges.some((e) => e.source === 'start' && e.target === 'end')"));
  新图态();
  跑(`图态.定义.nodes.push({ id: "llm_9", type: "llm", config: {} }); 弹_删除(["llm_9"])`);
  ck("没有连线、没人引用的步骤 → 直接删,不弹确认,能撤销", 跑("!节点('llm_9') && 历史().能撤()"));
  跑("撤销()");
  ck("撤销 → 它回来了", 跑("!!节点('llm_9')"));

  console.log("\n▸ T13 保存中继续编辑:旧响应不覆盖新内容");
  新图态();
  跑(`改图("改名称", () => { 节点("llm_1").name = "第一版"; })`);
  挂住 = { rev: 8 };
  const p = 跑("做_存草稿()");
  ck("保存发出 → 状态「保存中」", 跑("图态.保存态 === '保存中'"));
  const 发的 = 请求们.filter((r) => r.方法 === "PATCH").pop();
  ck("发出去的是发起那一刻的快照(If-Match 带着当时的 revision)", 发的.体.定义.nodes[1].name === "第一版" && 发的.头["If-Match"] === "7");
  跑(`改图("又改", () => { 节点("llm_1").name = "第二版"; })`);
  const p2 = 跑("做_存草稿()");
  ck("保存中再点保存 → 不并发发第二个 PATCH", 请求们.filter((r) => r.方法 === "PATCH").length === 1);
  挂住.放(); 挂住 = null;
  ck("第一个保存成功", await p === true);
  await p2;
  const 两次 = 请求们.filter((r) => r.方法 === "PATCH");
  ck("第一个回来后,才接着存第二版(串行),而且带的是新 revision",
     两次.length === 2 && 两次[1].体.定义.nodes[1].name === "第二版" && 两次[1].头["If-Match"] === "8", 两次.map((x) => x.头["If-Match"]));
  ck("第二版也存上了 → 已保存", 跑("!图态.脏 && 图态.保存态 === '已保存'"));
  新图态();
  跑(`改图("改名称", () => { 节点("llm_1").name = "A"; })`);
  挂住 = { rev: 8 };
  const p3 = 跑("做_存草稿()");
  跑(`改图("保存中又改", () => { 节点("llm_1").name = "B"; })`);
  挂住.放(); 挂住 = null; await p3;
  ck("保存期间又改了 → 成功回来后仍标「有未保存的修改」(不被成功响应盖掉)", 跑("图态.脏 && 图态.保存态 === '未保存' && 节点('llm_1').name === 'B'"));

  console.log("\n▸ T14 保存失败 / 冲突:本页修改保留,不自动刷新,不冒充已保存");
  for (const 码 of [500, 409]) {
    新图态(); 草稿回 = 码; 弹层们 = []; 弹框 = [];
    跑(`改图("改名称", () => { 节点("llm_1").name = "未存的"; })`);
    const 前 = 请求们.length;
    const r = await 跑("做_存草稿()");
    ck(`${码}:保存返回 false`, r === false);
    ck(`${码}:本页修改还在、仍标未保存`, 跑("节点('llm_1').name === '未存的' && 图态.脏"));
    ck(`${码}:没有自动重新拉详情`, !请求们.slice(前).some((x) => x.方法 === "GET"));
    ck(`${码}:状态写成${码 === 409 ? "冲突" : "失败"},不是已保存`, 跑(`图态.保存态 === '${码 === 409 ? "冲突" : "失败"}'`));
  }
  ck("409 → 弹「查看差异 / 保留本地副本 / 重新载入」,没有强制覆盖", 弹层们.some((h) => h.includes("查看差异") && h.includes("保留本地副本") && h.includes("重新载入"))
     && !弹层们.some((h) => h.includes("强制")));
  草稿回 = 200;

  console.log("\n▸ 检查报告过期 / 只读");
  新图态();
  跑(`图态.报告 = { 问题: [] }; 图态.报告定义 = JSON.stringify(图态.定义);`);
  ck("刚检查完 → 不过期", !跑("检查过期()"));
  跑(`改图("挪位置", () => { 图态.布局.llm_1 = { x: 999, y: 0 }; })`);
  ck("只挪位置 → 检查报告不过期(布局不进逻辑)", !跑("检查过期()"));
  跑(`改图("改连线", () => { 图逻辑.删边(图态.定义, "llm_1|success||end"); })`);
  ck("改了连线 → 「配置已修改,需重新检查」", 跑("检查过期()"));
  跑("撤销()");
  ck("撤销回到检查时的图 → 又不过期了(按内容判,不按「改过没有」)", !跑("检查过期()"));
  跑(`我的角色 = "viewer"`);
  const 前名 = 跑("节点('llm_1').name");
  ck("只读角色 → 改图被拒,定义不动", 跑(`改图("x", () => { 节点("llm_1").name = "改了"; }) === false`) && 跑("节点('llm_1').name") === 前名);
  跑(`我的角色 = "editor"`);

  console.log("\n▸ T20 运行结果固定到发起时的定义");
  新图态();
  跑(`图态.最近测试 = "r1"; 图态.最近测试定义 = JSON.stringify(图态.定义);`);
  ck("没改过 → 不算旧版本结果", 跑("图态.最近测试定义 === JSON.stringify(图态.定义)"));
  跑(`改图("改", () => { 节点("llm_1").name = "新"; })`);
  ck("改了图 → 这份运行结果是修改前版本的(页面会标出来)", 跑("图态.最近测试定义 !== JSON.stringify(图态.定义)"));

  跑完了 = true;
  console.log(`\n${挂.length ? "❌" : "✅"} 编辑器保存与命令层 ${过} 条过${挂.length ? `,挂 ${挂.length} 条:${挂.join(" / ")}` : ""}`);
  process.exit(挂.length ? 1 : 0);
})();
