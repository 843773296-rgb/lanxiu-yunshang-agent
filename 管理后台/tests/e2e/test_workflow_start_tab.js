/* 编排页 · 「开始」页签与多开始(11-20,工作流二期 2-3,照 Dify),不起服务。
 *
 * 照 test_workflow_new_nodes_panel.js 的办法把 wf_graph.js → wf_canvas.js → app.js 跑进 vm,直接调真函数,验**写进定义 / 布局的形状**:
 *   ① 「开始」页签从上到下:用户输入(标「最常用」)→ 定时触发器 → 自定义 Webhook;当前那种标「已添加」,别的能点
 *   ② 点一种 = 换开始方式(触发器和「用户输入」互斥,提示里说明):定时补上周一 8 点 + 统计起 / 止;离开定时删掉定时规则;能撤销
 *   ③ 没有「开始」时点一种 = 加一个那样开头的「开始」
 *   ④ 新建空白流程的标(布局.$开始待配置):画布上是虚线占位「点击配置开始节点」、没有出口;步骤列表标「还没配置」;面板下拉是「请选择」;
 *      选了方式标就摘掉,画布恢复成普通的「开始」卡
 *   ⑤ 引导弹窗三个选项、「先不选」;选一项走的是同一份 选开始方式
 *   ⑥ 面板下拉和「开始」页签改出来的定义一致(同一份 设开始方式)
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
const 池 = new Map(), 造过 = [];
const 取 = (sel) => { const k = String(sel); if (!池.has(k)) 池.set(k, 造(k)); return 池.get(k); };
const ctx = {
  console, setTimeout, clearTimeout, Promise, JSON, Math, String, Number, Array, Object, Map, Set, Date, Error, Event: function () {},
  encodeURIComponent, decodeURIComponent, URLSearchParams, CSS: { escape: (s) => s }, innerWidth: 1440,
  document: { querySelector: 取, querySelectorAll: () => [], getElementById: (id) => (id === "mask" ? null : 取(id)),
    createElement: () => { const e = 造("new"); 造过.push(e); return e; }, addEventListener() {}, removeEventListener() {}, activeElement: null,
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

// 一条新建的空白流程:开始(没写 start_mode = 用户输入)+ 结束,布局里带服务端打的 $开始待配置
function 装(选项 = {}) {
  const 待配 = 选项.待配 !== false, 有开始 = 选项.有开始 !== false;
  跑(`我的角色 = "editor";
  图态 = { wid: "wf_t", 名称: "t", 页签: "搭建", 视图: "步骤", revision: 1, 脏: false, 编辑序号: 0, 已存序号: 0, 保存态: "已保存", 选中: null, 面板页: "设置",
    定义: { nodes: [${有开始 ? `{ id: "start", type: "start", config: { input_schema: { type: "object", properties: { article: { type: "string" } }, required: ["article"] } } },` : ""}
                    { id: "finish", type: "end", config: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} } }],
            edges: [] },
    布局: { ${有开始 ? "start: { x: 40, y: 120 }," : ""} finish: { x: 620, y: 120 }${待配 && 有开始 ? ", $开始待配置: true" : ""} },
    节点库: [{ 名: "start", 端口: ["success"], 可用: true, 必填: ["input_schema"] }, { 名: "end", 端口: [], 可用: true }],
    资源: { 模型: [], 处理要求: [], 工具: [], 角色: [], 术语: [] }, 报告: null, 版本们: [] };
  图态.画 = null;`);
}
const 起 = () => 跑(`图态.定义.nodes.find((n) => n.type === "start")`);
const 开始页 = () => { 跑(`画态().库页 = "开始"; 画_库();`); return 取("#wf-lib").innerHTML; };
const 提示文 = () => (池.get("wf-toast") || {}).innerHTML || "";
const 面板 = () => { 跑("控件表 = []"); return 跑(`表_设置(节点("start"))`); };

console.log("\n▸ ① 「开始」页签:顺序、角标、「已添加」");
装({ 待配: false });
let h = 开始页();
const 位置 = ["用户输入", "定时触发器", "自定义 Webhook"].map((名) => h.indexOf(`<b>${名}</b>`));
ck("三项都在,从上到下:用户输入 → 定时触发器 → 自定义 Webhook", 位置.every((i) => i >= 0) && 位置[0] < 位置[1] && 位置[1] < 位置[2], 位置);
ck("「用户输入」标「最常用」", /最常用/.test(h.slice(位置[0], 位置[1])), h.slice(位置[0], 位置[1]));
ck("当前就是用户输入开头 → 「用户输入」标「已添加」、不能点;另两项能点(data-start)",
   /libit off[^>]*data-pv="用户输入"/.test(h) && /data-start="定时"/.test(h) && /data-start="Webhook"/.test(h) && !/data-start="用户输入"/.test(h), h.slice(0, 400));
ck("说明里写了互斥(触发器和「用户输入」不能同时存在)", /不能同时存在/.test(h));

console.log("\n▸ ② 点一种 = 换开始方式(互斥,可撤销)");
ck("点「定时触发器」→ 返回 true", 跑(`选开始方式("定时")`) === true);
let c = 起().config;
ck("定义里 start_mode=定时、补上默认周一 8 点、参数表换成统计起 / 止", c.start_mode === "定时" && c.schedule_rule && c.schedule_rule.周期 === "周" && c.schedule_rule.时刻 === "08:00"
   && Object.keys(c.input_schema.properties).sort().join() === "统计止,统计起", c);
ck("提示里说明了互斥、写了从哪种换到哪种", /不能同时存在/.test(提示文()) && /用户输入/.test(提示文()) && /定时触发器/.test(提示文()), 提示文());
ck("换完选中的是「开始」、面板到「设置」", 跑(`图态.选中`) === "start" && 跑(`图态.面板页`) === "设置");
ck("标脏(是一次真编辑)", 跑(`图态.脏`) === true);
h = 开始页();
ck("页签里现在「定时触发器」标「已添加」,「用户输入」能点了", /libit off[^>]*data-pv="定时触发器"/.test(h) && /data-start="用户输入"/.test(h), h.slice(0, 400));
ck("再点「定时触发器」→ 不动(已经是),返回 false", 跑(`选开始方式("定时")`) === false && /已经是/.test(提示文()), 提示文());
ck("点「自定义 Webhook」→ start_mode=Webhook、定时规则删掉、只剩统计字段的参数表清空",
   跑(`选开始方式("Webhook")`) === true && (c = 起().config).start_mode === "Webhook" && !("schedule_rule" in c) && Object.keys(c.input_schema.properties).length === 0, c);
跑(`撤销()`);
ck("撤销 → 回到定时(含定时规则)", (c = 起().config).start_mode === "定时" && !!c.schedule_rule, c);
ck("认不出的方式 → 不动", 跑(`选开始方式("邮件")`) === false && 起().config.start_mode === "定时");

console.log("\n▸ ③ 没有「开始」时点一种 = 加一个");
装({ 有开始: false });
ck("夹具:图里没有开始", !起());
ck("点「自定义 Webhook」→ 加了一个 Webhook 开头的「开始」,有布局、被选中",
   跑(`选开始方式("Webhook")`) === true && !!起() && 起().config.start_mode === "Webhook" && !!跑(`图态.布局[图态.定义.nodes.find((n) => n.type === "start").id]`) && 跑(`图态.选中`) === 起().id, 起());
ck("提示说「已添加「开始」」", /已添加「开始」/.test(提示文()), 提示文());

console.log("\n▸ ④ 新建空白流程:布局.$开始待配置 → 虚线占位、步骤标「还没配置」、下拉「请选择」;选了就摘标");
装();
ck("夹具:带 $开始待配置、定义里没写 start_mode", 跑(`开始待配置()`) === true && 起().config.start_mode === undefined);
ck("步骤列表的次级标签:还没配置怎么开始", /还没配置/.test(跑(`次级标签(节点("start"))`)), 跑(`次级标签(节点("start"))`));
h = 面板();
ck("面板:提示「还没配置怎么开始」,下拉选中的是「请选择」(三个选项都在、没有一个 selected)",
   /还没配置怎么开始/.test(h) && /<option value="">请选择<\/option>/.test(h) && !/value="用户输入" selected/.test(h) && /value="定时"/.test(h) && /value="Webhook"/.test(h), h.slice(0, 600));
h = 开始页();
ck("「开始」页签:三项都能点(没有一项「已添加」)", !/libit off/.test(h) && /data-start="用户输入"/.test(h), h.slice(0, 300));
let 画了 = false, 节点html = "";
try { 跑(`画态(); 画_节点();`); 画了 = true; 节点html = 取("#wf-nodes").innerHTML; } catch (e) { 节点html = String(e); }
ck("画布:开始画成虚线占位「点击配置开始节点」(class pending、data-pending),没有出口按钮",
   画了 && /class="wfnode2 pending"/.test(节点html) && /点击配置开始节点/.test(节点html) && !/data-out="start"/.test(节点html), 节点html.slice(0, 400));
ck("从引导里选「用户输入」→ 标摘掉、start_mode=用户输入、原来的参数表(article)保留", 跑(`选开始方式("用户输入")`) === true && 跑(`开始待配置()`) === false
   && 起().config.start_mode === "用户输入" && "article" in 起().config.input_schema.properties, 起().config);
ck("提示是「已配置成」,不是互斥那句(本来就没配)", /已配置成/.test(提示文()) && !/不能同时存在/.test(提示文()), 提示文());
try { 跑(`画_节点();`); 节点html = 取("#wf-nodes").innerHTML; } catch (e) { 节点html = String(e); }
ck("画布恢复成普通「开始」卡(有出口)", !/pending/.test(节点html) && /data-out="start"/.test(节点html), 节点html.slice(0, 400));
ck("次级标签:开始 · 用户输入", 跑(`次级标签(节点("start"))`) === "开始 · 用户输入", 跑(`次级标签(节点("start"))`));
跑(`撤销()`);
ck("撤销 → 标回来了(布局也在历史里)", 跑(`开始待配置()`) === true);

console.log("\n▸ ⑤ 引导弹窗");
装();
造过.length = 0;
跑(`弹_配置开始()`);
const 弹 = 造过.map((e) => e.innerHTML).join("\n");
ck("弹窗标题「这条流程怎么开始?」、三个选项(data-startpick)、「最常用」角标、「先不选」",
   /这条流程怎么开始/.test(弹) && (弹.match(/data-startpick="/g) || []).length === 3 && /最常用/.test(弹) && /先不选/.test(弹), 弹.slice(0, 400));
ck("弹窗里写了互斥文案", /不能同时存在/.test(弹));
跑(`我的角色 = "viewer"`); 造过.length = 0; 跑(`弹_配置开始()`);
ck("只读角色不弹", 造过.length === 0);
ck("只读角色点页签也不动", 跑(`选开始方式("定时")`) === false && 起().config.start_mode === undefined);

console.log("\n▸ ⑥ 面板下拉和页签改出来的定义一致(同一份 设开始方式)");
装({ 待配: false });
h = 面板();
const m = /<select data-k="(\d+)"/.exec(h);
const 下拉改 = (v) => { const fn = 跑(`控件表[${m[1]}]`); fn({ value: v }); };
下拉改("定时");
const 甲 = JSON.stringify(起().config);
装({ 待配: false }); 跑(`选开始方式("定时")`);
ck("下拉选「定时」和页签点「定时触发器」写出同一份配置", 甲 === JSON.stringify(起().config), [甲, JSON.stringify(起().config)]);
下拉改("");
ck("下拉选回「请选择」→ 不改定义", 起().config.start_mode === "定时");

console.log();
if (挂.length) { console.log(`❌ ${挂.length} 条没过:${挂.join(" / ")}`); process.exit(1); }
console.log(`✅ 「开始」页签与多开始 ${过} 条过`);
