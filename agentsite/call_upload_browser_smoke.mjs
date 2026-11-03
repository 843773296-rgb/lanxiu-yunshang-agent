// 聊天页的「上传录音」卡片在**真浏览器**里点一遍(无界面 Chrome,照 role_roundtrip_smoke.mjs 的做法;用户 11-03 要「全部做」)。
//
// 为什么要真浏览器:call_flow_check 验的是后端那几步(进程内调同一套函数),**卡片这段 JS 从来没被真正执行过** ——
// FileReader 读文件、拼请求体、点上传、轮询进度、刷新后不再冒出按钮,这些错法在后端检查里全都看不出来,
// 而它们在界面上的表现是「点了没反应」。
//
// 走的是真的:登录(本地测试账号,和 role_roundtrip_smoke 同一个)→ 对话里放一条带 offer_call_upload **真返回值**的消息
// (卡片数据由真工具算出来,通过参数传进来 —— 不现场调模型:花钱、而且每次答得不一样)→ 设文件、选沟通方式、点「上传」
// → 页面自己 fetch /api/call-upload(经聊天站转给后台)→ 后台转写工人真转写、转完真去管理后台发起录音跟进 → 卡片上的状态。
//
// ⚠️ 会写真数据:一通 CA- 录音 + 一条停在人工核对的录音跟进运行(合成录音)。跑完由调用方退回那条核对。
// 要先 ./start.sh。不进 check.sh(依赖外部服务,同 js_smoke / role_roundtrip_smoke)。用法:
//   node agentsite/call_upload_browser_smoke.mjs <临时目录> <录音文件> <卡片 JSON 文件>
import { spawn } from "node:child_process";
import fs from "node:fs";

const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [dir, 录音, 卡片文件] = process.argv.slice(2);
if (!dir || !录音 || !卡片文件) { console.log("用法:node call_upload_browser_smoke.mjs <临时目录> <录音文件> <卡片 JSON>"); process.exit(2); }
const 卡片结果 = JSON.parse(fs.readFileSync(卡片文件, "utf8"));
const p = spawn(CH, ["--headless=new", "--remote-debugging-port=9334", `--user-data-dir=${dir}/prof`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const wait = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try { const l = await (await fetch("http://127.0.0.1:9334/json")).json(); const pg = l.find((x) => x.type === "page"); if (pg) return pg.webSocketDebuggerUrl; } catch {}
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
  await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable");
  await go("http://127.0.0.1:8770/login");
  const 登 = await ev(`fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({login_name:"60000011",password:"lanxiu@2026"})}).then(r=>r.status)`);
  ck("登录(本地测试账号 60000011)", 登 === 200, 登);
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`);

  // 放一条带真工具返回值的助手消息,按页面自己的重绘函数画出来
  const 放 = await ev(`(() => { const c = cur() || newConv("kb");
      c.msgs.push({role:"u", text:"刚跟李书言通完电话,帮我提交一下跟进"});
      c.msgs.push({role:"a", text:"好的,请在下面上传这通录音。", trajectory:[{tool:"mcp__work__offer_call_upload", args:{customer_id:"C10007"}, result:${JSON.stringify(卡片结果)}}]});
      save(); drawStream(); return document.querySelectorAll("[data-callup]").length; })()`);
  ck("卡片画出来了,有一个「上传」按钮", 放 === 1, 放);
  const 文 = await ev(`document.querySelector(".callcard") && document.querySelector(".callcard").innerText.replace(/\\s+/g," ").slice(0,200)`);
  ck("卡片写着是哪位客户、传完会自动走录音跟进、要人核对才写进系统",
     typeof 文 === "string" && 文.includes("李书言") && 文.includes("录音跟进") && 文.includes("核对"), 文);

  // 先不选文件就点 → 应该说「先选一个录音文件」,不发请求
  await ev(`document.querySelector("[data-callup]").click()`); await sleep(300);
  const 空 = await ev(`document.querySelector(".callcard").innerText`);
  ck("没选文件就点上传 → 提示先选文件(不发请求)", typeof 空 === "string" && 空.includes("先选一个录音文件"), 空);

  // 设文件(走真的文件选择那条路:DOM.setFileInputFiles),选「上门」,点上传
  const doc = await send("DOM.getDocument", { depth: -1 });
  const q = await send("DOM.querySelector", { nodeId: doc.result.root.nodeId, selector: ".callcard input[type=file]" });
  await send("DOM.setFileInputFiles", { nodeId: q.result.nodeId, files: [录音] });
  await ev(`(() => { const s = document.querySelector(".callcard select"); s.value = "上门"; return s.value; })()`);
  await ev(`document.querySelector("[data-callup]").click()`);

  // 等卡片上的状态走到终点(已发起 / 没发起 / 转写失败)—— 页面自己每 5 秒轮询一次
  let 标 = "", 话 = "";
  for (let i = 0; i < 60; i++) {
    await sleep(3000);
    标 = await ev(`(document.querySelector(".callcard .st")||{}).textContent || ""`);
    话 = await ev(`(document.querySelector(".callcard .ln:last-child")||{}).textContent || ""`);
    if (/已发起录音跟进|录音跟进没发起|转写失败|没传上/.test(标)) break;
  }
  ck("点上传之后,卡片走到「已发起录音跟进」(转写 + 发起都真做了)", 标 === "已发起录音跟进", `${标} | ${话}`);
  const 运行 = (话.match(/xr_[0-9a-f]+/) || [])[0];
  ck("卡片上给出了运行号", Boolean(运行), 话);
  ck("传完后卡片里不再有「上传」按钮(不能把同一通再传一遍)",
     (await ev(`document.querySelectorAll("[data-callup]").length`)) === 0);

  // 刷新页面:录音号记在消息上,卡片应直接进「查进度」,不再冒出上传按钮
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`);
  await sleep(6000);
  const 刷后 = await ev(`({按钮: document.querySelectorAll("[data-callup]").length, 标: (document.querySelector(".callcard .st")||{}).textContent})`);
  ck("刷新页面后:没有上传按钮,状态还是「已发起录音跟进」", 刷后 && 刷后.按钮 === 0 && 刷后.标 === "已发起录音跟进", JSON.stringify(刷后));
  if (运行) console.log(`RUN=${运行}`);
  console.log();
  console.log(挂.length ? `❌ ${挂.length} 条不过:${挂.join(" / ")}` : `✅ 上传录音卡片:${过.length} 条全过`);
  退出码 = 挂.length ? 1 : 0;
} catch (e) { console.log("出错", e); } finally { p.kill(); process.exit(退出码); }
