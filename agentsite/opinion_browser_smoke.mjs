// 聊天页「有帮助 / 反馈问题 / 报告执行问题」在**真浏览器**里点一遍(无界面 Chrome,照 call_upload_browser_smoke.mjs;11-04)。
//
// 为什么要真浏览器:answer_feedback_check 验的是聊天站转发那几步,**这段页面 JS 从没被真执行过** ——
// 取框里的值、拼请求体、提交后改成「已提」、刷新后还在,错了在界面上的表现只是「点了没反应」(上次 draw() 就是这么漏的)。
//
// 走的是真的:登录本地测试账号 → 放一条挂着**这个账号自己那一轮**真 trace 的回答(和一条失败的)→ 点、填、提交 →
// 页面自己 fetch /api/answer-feedback → 聊天站核提问人、转给管理后台 → 库里一行。
// ⚠️ 会写真数据:两条挂一轮的意见(chat_trace_ref = 传进来的那两轮)+ 两条独立建议(说明以「浏览器冒烟」开头)。跑完由调用方删。要先 ./start.sh。不进 check.sh。
//   node agentsite/opinion_browser_smoke.mjs <临时目录> <自己那一轮的 trace> <自己那条失败轮的 trace>
import { spawn } from "node:child_process";

const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [dir, 好轮, 坏轮] = process.argv.slice(2);
if (!dir || !好轮 || !坏轮) { console.log("用法:node opinion_browser_smoke.mjs <临时目录> <trace> <失败轮 trace>"); process.exit(2); }
const p = spawn(CH, ["--headless=new", "--remote-debugging-port=9335", `--user-data-dir=${dir}/prof`, "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const wait = new Map();
async function connect() {
  for (let i = 0; i < 40; i++) {
    try { const l = await (await fetch("http://127.0.0.1:9335/json")).json(); const pg = l.find((x) => x.type === "page"); if (pg) return pg.webSocketDebuggerUrl; } catch {}
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
  // alert 会卡住页面 —— 换成记下来,检查里读
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__alerts=[];window.alert=(m)=>window.__alerts.push(String(m));" });
  await go("http://127.0.0.1:8770/login");
  const 登 = await ev(`fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({login_name:"60000011",password:"lanxiu@2026"})}).then(r=>r.status)`);
  ck("登录(本地测试账号 60000011)", 登 === 200, 登);
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`);
  const 放 = await ev(`(() => { const c = newConv("kb");
      c.msgs.push({role:"u", text:"只回复两个字:正常"});
      c.msgs.push({role:"assistant", text:"正常", trace_id:${JSON.stringify(好轮)}, trajectory:[]});
      c.msgs.push({role:"u", text:"再问一句"});
      c.msgs.push({role:"assistant", error:"TimeoutError: 调模型超时", trace_id:${JSON.stringify(坏轮)}});
      save(); drawStream();
      return [...document.querySelectorAll("[data-fb]")].map(b => b.dataset.fbv).join(","); })()`);
  ck("回答下有「有帮助 / 反馈问题」,失败那条有「报告执行问题」", 放 === "有帮助,反馈问题,反馈问题", 放);
  const 失败按钮 = await ev(`[...document.querySelectorAll("[data-fb]")].pop().textContent`);
  ck("失败那条的按钮写的是「报告执行问题」", 失败按钮 === "报告执行问题", 失败按钮);

  // 回答那条:点「反馈问题」→ 不填就提交 → 被页面拦下(不发请求)
  await ev(`document.querySelector('[data-fb="1"][data-fbv="反馈问题"]').click()`); await sleep(200);
  await ev(`document.querySelector('[data-fb="1"][data-fbv="提交问题"]').click()`); await sleep(300);
  const 拦 = await ev(`window.__alerts.slice(-1)[0] || ""`);
  ck("没选类就提交 → 页面先拦下", 拦.includes("先选是哪一类"), 拦);
  // 填齐:类 / 哪里有问题 / 期望 / 影响,提交
  await ev(`(() => { document.querySelector('[data-fbtype="1"]').value = "没答全";
      document.querySelector('[data-fbnote="1"]').value = "浏览器冒烟:少说了一句";
      document.querySelector('[data-fbwant="1"]').value = "应该再说一句";
      document.querySelector('[data-fbimpact="1"]').value = "反复出现";
      document.querySelector('[data-fb="1"][data-fbv="提交问题"]').click(); })()`);
  await sleep(2500);
  const 回 = await ev(`(document.querySelectorAll(".fb")[0] || {}).innerText || ""`);
  ck("提交后这一条变成「已提『有问题·没答全』—— 进了管理后台『意见』待受理」", 回.includes("有问题·没答全") && 回.includes("待受理"), 回 + " | " + await ev(`window.__alerts.join(" / ")`));

  // 失败那条:报告执行问题,类默认就是「太慢或失败」
  await ev(`document.querySelector('[data-fb="3"][data-fbv="反馈问题"]').click()`); await sleep(200);
  const 默认 = await ev(`document.querySelector('[data-fbtype="3"]').value`);
  ck("报告执行问题时,类默认选好「太慢或失败」", 默认 === "太慢或失败", 默认);
  await ev(`(() => { document.querySelector('[data-fbnote="3"]').value = "浏览器冒烟:等了三分钟";
      document.querySelector('[data-fb="3"][data-fbv="提交问题"]').click(); })()`);
  await sleep(2500);
  const 回2 = await ev(`(document.querySelectorAll(".fb")[1] || {}).innerText || ""`);
  ck("失败那条也提上了", 回2.includes("太慢或失败") && 回2.includes("待受理"), 回2 + " | " + await ev(`window.__alerts.join(" / ")`));

  // 停掉的那一轮(没有 trace):按钮还在,点了打开「意见与建议」,类和说明预填好
  await ev(`(() => { const c = cur(); c.msgs.push({role:"u", text:"帮我查一下上周营收"}); c.msgs.push({role:"assistant", error:"已停止"}); save(); drawStream(); })()`);
  const 停 = await ev(`document.querySelectorAll("[data-fbstop]").length`);
  ck("停掉的那一轮(没有 trace)也有「报告执行问题」", 停 === 1, 停);
  await ev(`document.querySelector("[data-fbstop]").click()`); await sleep(1500);
  const 预 = await ev(`({类: document.querySelector("#op-type").value, 说明: document.querySelector("#op-note").value})`);
  ck("点了打开「意见与建议」,类预选「太慢或失败」、说明带上当时问的那句", 预 && 预.类 === "太慢或失败" && 预.说明.includes("上周营收"), JSON.stringify(预));
  // 独立建议:提交 → 「我的意见」里出现,进度是「已收到」
  await ev(`(() => { document.querySelector("#op-note").value = "浏览器冒烟:停掉之后不知道有没有在跑"; document.querySelector("#op-send").click(); })()`);
  await sleep(3000);
  const 提后 = await ev(`({提示: document.querySelector("#op-why").textContent, 我的: document.querySelector("#op-mine").innerText})`);
  ck("独立建议提上了,「我的意见」里出现,进度写「已收到」", 提后 && 提后.提示.includes("收到了") && 提后.我的.includes("已收到")
     && 提后.我的.includes("停掉之后"), JSON.stringify(提后));
  // 同一个提交键重提(模拟网断了重试):不该多出一条
  const 重 = await ev(`fetch("/api/opinion",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({提交键:"smoke-retry-key",问题类型:"其他",说明:"浏览器冒烟:重试"})}).then(r=>r.json()).then(a=>fetch("/api/opinion",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({提交键:"smoke-retry-key",问题类型:"其他",说明:"浏览器冒烟:重试"})}).then(r=>r.json()).then(b=>[a.id,b.id,b.新建]))`);
  ck("同一个提交键连提两次 → 同一条,第二次不新建", Array.isArray(重) && 重[0] && 重[0] === 重[1] && 重[2] === false, JSON.stringify(重));
  await ev(`closeOrder()`);

  // 刷新:记在消息上,还在
  await go("http://127.0.0.1:8770/");
  await ev(`document.getElementById("arrival") && (document.getElementById("arrival").hidden=true)`); await sleep(500);
  const 刷 = await ev(`[...document.querySelectorAll(".fb")].slice(0, 2).map(e => e.innerText.includes("已提")).join(",")`);
  ck("刷新页面后两条都还显示「已提」", 刷 === "true,true", 刷);
  console.log();
  console.log(挂.length ? `❌ ${挂.length} 条不过:${挂.join(" / ")}` : `✅ 聊天页意见:${过.length} 条全过`);
  退出码 = 挂.length ? 1 : 0;
} catch (e) { console.log("出错", e); } finally { p.kill(); process.exit(退出码); }
