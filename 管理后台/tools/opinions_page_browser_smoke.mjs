// 管理后台「意见受理」页在**真浏览器**里点一遍(无界面 Chrome,照 agentsite/opinion_browser_smoke.mjs;11-04)。
// 为什么:test_opinions_flow 验的是接口;页面那段 JS(按「能做的动作」画按钮、带 If-Match 提交、刷新时间线)从没被真执行过。
// ⚠️ 会写真数据:一条意见(传进来的 id)被推到「已答复」、时间线三行、一条待复核样本。跑完由调用方删。要先 make dev / 起着 8801。不进门禁。
//   node 管理后台/tools/opinions_page_browser_smoke.mjs <临时目录> <意见 id>
import { spawn } from "node:child_process";
const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [dir, 意见] = process.argv.slice(2);
if (!dir || !意见) { console.log("用法:node opinions_page_browser_smoke.mjs <临时目录> <意见 id>"); process.exit(2); }
const p = spawn(CH, ["--headless=new", "--remote-debugging-port=9336", `--user-data-dir=${dir}/prof`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const wait = new Map();
async function connect() { for (let i = 0; i < 40; i++) { try { const l = await (await fetch("http://127.0.0.1:9336/json")).json(); const pg = l.find((x) => x.type === "page"); if (pg) return pg.webSocketDebuggerUrl; } catch {} await sleep(250); } }
const send = (method, params = {}) => new Promise((r) => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) return "页面里抛了:" + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text); return r.result?.result?.value; };
const 过 = [], 挂 = [];
const ck = (名, 真, 补 = "") => { console.log(`  ${真 ? "✅" : "❌"} ${名}${!真 && 补 ? "  " + String(补).slice(0, 300) : ""}`); (真 ? 过 : 挂).push(名); };
let 退出码 = 1;
try {
  ws = new WebSocket(await connect()); await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); } };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `localStorage.setItem("aimc.user","U001");localStorage.setItem("aimc.proj","project_lanxiu");window.alert=()=>{};` });
  await send("Page.navigate", { url: "http://127.0.0.1:8801/#/opinions" }); await sleep(3000);
  const 清单 = await ev(`({有: !!document.querySelector('[data-opopen="${意见}"]'), 菜单: [...document.querySelectorAll('a[href="#/opinions"]')].length, 头: (document.querySelector("#main h1")||{}).textContent})`);
  ck("左侧菜单有「意见受理」,清单页打开了,这条意见在清单里", 清单 && 清单.菜单 >= 1 && 清单.头 === "意见受理" && 清单.有, JSON.stringify(清单));
  await ev(`document.querySelector('[data-opopen="${意见}"]').click()`); await sleep(2000);
  const 钮 = await ev(`[...document.querySelectorAll("[data-opact]")].map(b => b.dataset.opact).join(",")`);
  ck("详情页的动作按钮照接口给的画(待受理:开始核实 / 请求补充)", 钮 === "开始核实,请求补充", 钮);
  await ev(`document.querySelector('[data-opact="开始核实"]').click()`); await sleep(2000);
  const 一 = await ev(`({状: document.querySelector(".sub b") && document.querySelector(".sub b").textContent, 钮: [...document.querySelectorAll("[data-opact]")].map(b => b.dataset.opact).join(",")})`);
  ck("点「开始核实」→ 页面刷新成核实中,按钮换成答复 / 不采纳 / 请求补充", 一 && 一.状 === "核实中" && 一.钮 === "答复,不采纳,请求补充", JSON.stringify(一));
  await ev(`document.querySelector('[data-opact="答复"]').click()`); await sleep(1500);
  const 拦 = await ev(`(document.querySelector("#op-act-why")||{}).textContent || ""`);
  ck("不写说明就点「答复」→ 页面显示服务端的拒绝理由(不装作成功)", 拦.includes("没处理上") && 拦.includes("说明"), 拦);
  await ev(`(() => { document.querySelector("#op-act-note").value = "浏览器冒烟:已核实,工期按 21 个工作日"; document.querySelector('[data-opact="答复"]').click(); })()`); await sleep(2000);
  const 二 = await ev(`({状: document.querySelector(".sub b") && document.querySelector(".sub b").textContent, 线: [...document.querySelectorAll("table")].pop().innerText})`);
  ck("写了说明再答复 → 已答复,时间线两行(开始核实、答复)、答复那句在", 二 && 二.状 === "已答复" && 二.线.includes("开始核实") && 二.线.includes("浏览器冒烟:已核实"), JSON.stringify(二).slice(0, 300));
  // 已答复的意见能提样本:填题面 / 标准答案 → 提 → 页面显示「待复核」
  const 表 = await ev(`({有: !!document.querySelector("#op-sm-send"), 预填: (document.querySelector("#op-sm-a")||{}).value})`);
  ck("已答复的意见有「提为样本」表单(这条没写期望结果,标准答案框是空的)", 表 && 表.有, JSON.stringify(表));
  await ev(`document.querySelector("#op-sm-send").click()`); await sleep(500);
  const 拦2 = await ev(`(document.querySelector("#op-sm-why")||{}).textContent || ""`);
  ck("题面 / 标准答案没写就点 → 页面先拦下", 拦2.includes("都要写"), 拦2);
  await ev(`(() => { document.querySelector("#op-sm-q").value = "浏览器冒烟:定制工期多少个工作日?"; document.querySelector("#op-sm-a").value = "21 个工作日"; document.querySelector("#op-sm-send").click(); })()`);
  await sleep(2500);
  const 样 = await ev(`({字: [...document.querySelectorAll(".note")].map(e => e.innerText).join(" | "), 还能提: !!document.querySelector("#op-sm-send")})`);
  ck("提完 → 页面显示「已提成样本 · 复核状态 待复核」、表单不见了", 样 && 样.字.includes("待复核") && !样.还能提, JSON.stringify(样).slice(0, 300));
  console.log(); console.log(挂.length ? `❌ ${挂.length} 条不过:${挂.join(" / ")}` : `✅ 意见受理页:${过.length} 条全过`);
  退出码 = 挂.length ? 1 : 0;
} catch (e) { console.log("出错", e); } finally { p.kill(); process.exit(退出码); }
