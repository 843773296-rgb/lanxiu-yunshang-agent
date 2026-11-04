// 聊天页「待我复核的样本」(店长)在**真浏览器**里点一遍(照 opinion_browser_smoke.mjs;11-04)。
// 验:店长看得到提问人门店的待复核样本、退回不写理由被页面拦下、点通过之后它从清单里消失(真走聊天站 → 管理后台)。
// ⚠️ 会写真数据:传进来的那条样本被推到「已通过」。样本由调用方先造好、跑完删。要先 ./start.sh。不进门禁。
//   node agentsite/review_browser_smoke.mjs <临时目录> <待复核样本号>
import { spawn } from "node:child_process";

const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [dir, 样本] = process.argv.slice(2);
if (!dir || !样本) { console.log("用法:node review_browser_smoke.mjs <临时目录> <待复核样本号>"); process.exit(2); }
const p = spawn(CH, ["--headless=new", "--remote-debugging-port=9337", `--user-data-dir=${dir}/prof`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const wait = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try { const l = await (await fetch("http://127.0.0.1:9337/json")).json(); const pg = l.find((x) => x.type === "page"); if (pg) return pg.webSocketDebuggerUrl; } catch {}
    await sleep(250);
  }
}
const send = (method, params = {}) => new Promise((r) => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) return "页面里抛了:" + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
const go = async (url) => { await send("Page.navigate", { url }); await sleep(2500); };
const 过 = [], 挂 = [];
const ck = (名, 真, 补 = "") => { console.log(`  ${真 ? "✅" : "❌"} ${名}${!真 && 补 ? "  " + String(补).slice(0, 300) : ""}`); (真 ? 过 : 挂).push(名); };

let 退出码 = 1;
try {
  ws = new WebSocket(await connect());
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); } };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__alerts=[];window.alert=(m)=>window.__alerts.push(String(m));" });
  await go("http://127.0.0.1:8770/login");
  // 店长测试账号:演示口令写在 backend/seed.py(DEMO_PW,公开的演示密码),只在本机用
  const 登 = await ev(`fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({login_name:"60000001",password:"lanxiu@2026"})}).then(r=>r.status)`);
  ck("登录(本地演示店长 60000001,静安旗舰店)", 登 === 200, 登);
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`); await sleep(1500);
  await ev(`document.querySelector("#opbtn").click()`); await sleep(3000);
  const 有 = await ev(`({区: !!document.querySelector("#op-review"), 这条: !!document.querySelector('[data-rvok="${样本}"]'), 字: (document.querySelector("#op-review")||{}).innerText || ""})`);
  ck("店长打开「意见与建议」看得到「待我复核的样本」,这条在里面(题面 / 标准答案都显示)",
     有 && 有.区 && 有.这条 && 有.字.includes("题面") && 有.字.includes("标准答案"), JSON.stringify(有).slice(0, 300));
  await ev(`document.querySelector('[data-rvno="${样本}"]').click()`); await sleep(500);
  const 拦 = await ev(`(document.querySelector('[data-rvwhy="${样本}"]')||{}).textContent || ""`);
  ck("退回不写理由 → 页面先拦下(不发请求)", 拦.includes("退回要写理由"), 拦);
  await ev(`document.querySelector('[data-rvok="${样本}"]').click()`); await sleep(2500);
  const 后 = await ev(`({还在: !!document.querySelector('[data-rvok="${样本}"]'), 字: (document.querySelector("#op-review")||{}).innerText || ""})`);
  ck("点「通过」→ 这条从「待我复核」里消失", 后 && !后.还在, JSON.stringify(后).slice(0, 300));
  console.log(); console.log(挂.length ? `❌ ${挂.length} 条不过:${挂.join(" / ")}` : `✅ 店长复核:${过.length} 条全过`);
  退出码 = 挂.length ? 1 : 0;
} catch (e) { console.log("出错", e); } finally { p.kill(); process.exit(退出码); }
