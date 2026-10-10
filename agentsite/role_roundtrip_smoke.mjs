// 无界面 Chrome 真走一遍(用户 10-10 报的:「角色进入工作台再返回 chat 会丢失角色信息」):
//   登录 → 对话页选「工坊排产」助手 → 去后台运营(看右上角是不是登录的那个人)→ 回对话页(看顶上还是不是工坊排产)
// 要先 ./start.sh。不进 check.sh(依赖外部服务,同 js_smoke.js)。用法:
//   node agentsite/role_roundtrip_smoke.mjs <一个临时目录>
// 修之前 ④ 显示「澜绣云裳助手」而本地存的是 workshop;③ 显示「魏欣新 · 顾问」而登录的是苏彧。
import { spawn } from "node:child_process";
const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const dir = process.argv[2];
const p = spawn(CH, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${dir}/prof`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0; const wait = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try { const l = await (await fetch("http://127.0.0.1:9333/json")).json(); const pg = l.find(x => x.type === "page"); if (pg) return pg.webSocketDebuggerUrl; } catch {}
    await sleep(250);
  }
}
const send = (method, params = {}) => new Promise(r => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
const go = async (url) => { await send("Page.navigate", { url }); await sleep(2500); };
try {
  ws = new WebSocket(await connect());
  await new Promise(r => ws.onopen = r);
  ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id && wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); } };
  await send("Page.enable"); await send("Runtime.enable");
  await go("http://127.0.0.1:8770/login");
  console.log("登录:", await ev(`fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({login_name:"60000011",password:"lanxiu@2026"})}).then(r=>r.status)`));
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`);
  console.log("① 进对话页:", await ev(`document.getElementById("currole").textContent + " | me=" + document.getElementById("me").textContent`));
  await ev(`document.getElementById("currole").click()`); await sleep(500);
  console.log("   可选助手:", await ev(`[...document.querySelectorAll("#pick .role")].map(x=>x.innerText.replace(/\\s+/g," ").slice(0,30)).join(" / ")`));
  await ev(`(()=>{const bs=[...document.querySelectorAll("#pick .go")]; const b=bs[3]; b && b.click();})()`); await sleep(500);
  console.log("② 选了工坊之后:", await ev(`document.getElementById("currole").textContent`));
  console.log("   本地存的会话:", await ev(`Object.keys(localStorage).filter(k=>k.startsWith("lanxiu.chat")).map(k=>{const d=JSON.parse(localStorage[k]);const c=d.convs.find(x=>x.id===d.cur);return k+" cur="+d.cur+" kind="+(c&&c.kind)+" 共"+d.convs.length}).join(";")`));
  await go("http://127.0.0.1:8770/ops"); await sleep(1500);
  console.log("③ 工作台右上角:", await ev(`(document.getElementById("roleSw")||{}).innerText`));
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`);
  console.log("④ 回到对话页:", await ev(`document.getElementById("currole").textContent + " | me=" + document.getElementById("me").textContent`));
  console.log("   本地存的会话:", await ev(`Object.keys(localStorage).filter(k=>k.startsWith("lanxiu.chat")).map(k=>{const d=JSON.parse(localStorage[k]);const c=d.convs.find(x=>x.id===d.cur);return k+" cur="+d.cur+" kind="+(c&&c.kind)+" 共"+d.convs.length}).join(";")`));
} catch (e) { console.log("出错", e); } finally { p.kill(); process.exit(0); }
