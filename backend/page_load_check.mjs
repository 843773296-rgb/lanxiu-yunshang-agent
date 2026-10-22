/* 管理后台切页的加载状态(外部复审 3.5,2026-10-22)—— 不起服务,在 node 里真跑页面脚本。
 *
 * 复审看到的现象:「路由已切而内容仍旧」。查实是 `view()` 的写法 —— 先改地址栏,
 * 再等接口,接口回来才整块替换内容。于是:
 *   · 等的那段时间,旧页面原样摆着,看不出在载入;
 *   · 接口报错 / 服务关了,异常没人接,**旧页面就一直留着,地址栏却已经是新页**;
 *   · 连点两页,先点的那页慢、后回来,**把后点那页的内容盖掉**。
 * > 一个「新页载入成功了」和一个「新页根本没载入、摆着的是上一页」,
 * > **在屏幕上长得一模一样** —— 除了地址栏。
 *
 * 判据造出它要验的每一种形状(慢 / 接口报错 / 返回不是数据 / 服务关了 / 超时 / 连点 / 重试),
 * 不等服务碰巧出事。网络换成可控的假 fetch;页面的取数口 `get()` 和切页口 `view()` 是**真的**,
 * 只有 `route()` 换成一个最小的假页(取一次数、写进主区)—— 被测的是切页那一层,不是某一页。
 *
 * 用法:node backend/page_load_check.mjs     (不调模型、不读库、不起服务)
 */
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(HERE, "web", "index.html"), "utf8");
const js = src.split("<script>").slice(1).join("<script>").split("</script>")[0];
const ids = [...src.matchAll(/id="([^"]+)"/g)].map(m => m[1]);

const G = "\x1b[32m", R = "\x1b[31m", D = "\x1b[0m";
let 坏 = 0, 验 = 0;
const ck = (名, ok, 细 = "") => {
  验++; if (!ok) 坏++;
  console.log(`  ${ok ? G + "✅" : R + "❌"}${D} ${名}${ok || !细 ? "" : "\n      " + 细}`);
};

const el = (id) => ({
  id, _h: "", attrs: {}, dataset: {}, style: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {},
  setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  get innerHTML() { return this._h; }, set innerHTML(v) { this._h = String(v); },
  get textContent() { return this._h; }, set textContent(v) { this._h = String(v); },
  querySelectorAll() { return []; }, querySelector() { return null; },
  focus() {}, closest: () => null, value: "", hidden: false, title: "",
});

/* 假网络:每个请求挂起成一张「票」,由用例决定它怎么结束 —— 这样「谁先回来」完全可控。 */
function 搭页面() {
  const store = new Map(ids.map(i => [i, el(i)]));
  const 票们 = [];
  const fetch = (u, opt = {}) => new Promise((ok, no) => {
    if (String(u).startsWith("/api/me")) return ok({ ok: false, status: 401, json: async () => ({}) });
    const 票 = { u: String(u), ok, no, opt };
    opt.signal && opt.signal.addEventListener &&
      opt.signal.addEventListener("abort", () => no(Object.assign(new Error("aborted"), { name: "AbortError" })));
    票们.push(票);
  });
  const ctx = {
    console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    AbortController, Promise, JSON, Math, Date, String, Number, Array, Object, Error, Map, Set,
    encodeURIComponent, decodeURIComponent,
    fetch, alert() {}, confirm: () => false, localStorage: { getItem: () => null, setItem() {} },
    location: { hash: "", href: "", search: "", pathname: "/" }, navigator: { clipboard: { writeText: async () => {} } },
    document: {
      documentElement: el("html"), body: el("body"),
      getElementById: (i) => store.get(i) || null,
      querySelector: (s) => (s.startsWith("#") ? store.get(s.slice(1)) || null : el("?")),
      querySelectorAll: () => [], addEventListener() {}, createElement: () => el("new"),
    },
  };
  ctx.window = ctx;
  ctx.addEventListener = () => {};
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  // 最小假页:取一次数,写进主区。真页面也是这个形状(`x=await get(..)` 然后写 `M.innerHTML`)。
  ctx.route = async (v) => {
    const d = await ctx.get("/api/假页?" + v);
    store.get("main").innerHTML = `页面:${v}|${d.x}`;
  };
  // 页签栏要在真 DOM 里找子元素,桩里给不出 —— 它和加载状态无关,换成空的(只画 UI、不碰主区)。
  ctx.renderTabs = () => {};
  const 主 = store.get("main");
  const 等 = (ms = 0) => new Promise(r => setTimeout(r, ms));
  const 好 = (票, d) => 票.ok({ ok: true, status: 200, json: async () => d });
  return { ctx, 主, 票们, 等, 好 };
}

async function 跑() {
  console.log("管理后台切页的加载状态(外部复审 3.5)—— 自造七种形状,不起服务\n");

  // ── 先载入一页当「旧内容」,后面每一种都看它会不会被当成新页 ──
  async function 起手() {
    const P = 搭页面();
    await P.等(5);                                  // 让页面自己那次开机切页先走完
    P.票们.splice(0).forEach(t => P.好(t, { x: "开机" }));
    await P.等(5);
    const 开 = P.ctx.view("甲");
    await P.等(1); P.好(P.票们.shift(), { x: "旧" }); await 开;
    return P;
  }

  { // ① 慢:等的时候要看得出在载入,而且是在载入哪一页
    const P = await 起手();
    const 走 = P.ctx.view("乙");
    ck("① 慢响应:一点下去主区就标成「载入中」(不是摆着旧页当新页)",
       P.主.getAttribute("aria-busy") === "true", `aria-busy=${P.主.getAttribute("aria-busy")}`);
    await P.等(400);
    ck("① 慢响应:等久了主区换成「正在载入」并点名是哪一页,旧页内容不在了",
       P.主.innerHTML.includes("正在载入") && P.主.innerHTML.includes("乙") && !P.主.innerHTML.includes("页面:甲"),
       `主区=${P.主.innerHTML.slice(0, 80)}`);
    P.好(P.票们.shift(), { x: "新" }); await 走;
    ck("① 慢响应:回来之后是新页、载入标记撤掉",
       P.主.innerHTML === "页面:乙|新" && P.主.getAttribute("aria-busy") !== "true",
       `主区=${P.主.innerHTML.slice(0, 80)} aria-busy=${P.主.getAttribute("aria-busy")}`);
  }
  const 失败形状 = [
    ["② 接口报错(HTTP 500、回的不是数据)", t => t.ok({ ok: false, status: 500, json: async () => { throw new SyntaxError("bad"); } }), "接口报错"],
    ["③ 接口回 200 但不是数据", t => t.ok({ ok: true, status: 200, json: async () => { throw new SyntaxError("bad"); } }), "不是数据"],
    ["④ 服务关了(连不上)", t => t.no(new TypeError("Failed to fetch")), "连不上"],
  ];
  for (const [名, 结束, 因] of 失败形状) {
    const P = await 起手();
    const 走 = P.ctx.view("乙");
    await P.等(1); 结束(P.票们.shift()); await 走.catch(() => {});
    const h = P.主.innerHTML;
    ck(`${名}:标明「乙」没载入、说清是哪一类原因,旧页内容不在了`,
       h.includes("没有载入") && h.includes("乙") && h.includes(因) && !h.includes("页面:甲"),
       `主区=${h.slice(0, 160)}`);
    ck(`${名}:给了重试,载入标记撤掉`,
       h.includes("重试") && P.主.getAttribute("aria-busy") !== "true", `主区=${h.slice(0, 160)}`);
  }
  { // ⑤ 超时:服务一直不回,也要停下来说「没响应」,而不是永远转圈
    const P = await 起手();
    P.ctx.载入超时毫秒 = 60;
    const 走 = P.ctx.view("乙");
    await Promise.race([走.catch(() => {}), P.等(500)]);
    const h = P.主.innerHTML;
    ck("⑤ 一直不回:到点停下、标明没载入、原因是没响应、给重试",
       h.includes("没有载入") && h.includes("没响应") && h.includes("重试") && !h.includes("页面:甲"),
       `主区=${h.slice(0, 160)}`);
  }
  { // ⑥ 连点:先点的慢页后回来,不许盖掉后点的那页
    const P = await 起手();
    const 慢 = P.ctx.view("乙");
    await P.等(1);
    const 快 = P.ctx.view("丙");
    await P.等(1);
    const [乙票, 丙票] = [P.票们.find(t => t.u.endsWith("乙")), P.票们.find(t => t.u.endsWith("丙"))];
    P.好(丙票, { x: "丙的数" }); await 快.catch(() => {});
    P.好(乙票, { x: "乙的数" }); await 慢.catch(() => {}); await P.等(5);
    ck("⑥ 连点两页、先点的那页后回来:主区是后点那页(地址栏和内容对得上)",
       P.主.innerHTML === "页面:丙|丙的数" && P.ctx.location.hash === "丙",
       `主区=${P.主.innerHTML} 地址栏=${P.ctx.location.hash}`);
    ck("⑥ 连点:被取代的那次不显示成失败",
       !P.主.innerHTML.includes("没有载入"), `主区=${P.主.innerHTML}`);
  }
  { // ⑦ 重试:失败之后点重试,服务好了就载入成功
    const P = await 起手();
    const 走 = P.ctx.view("乙");
    await P.等(1); P.票们.shift().no(new TypeError("Failed to fetch")); await 走.catch(() => {});
    const 再 = typeof P.ctx.重试载入 === "function" ? P.ctx.重试载入() : null;
    if (再) { await P.等(1); P.好(P.票们.shift(), { x: "好了" }); await 再; }
    ck("⑦ 失败后点重试:重新载入同一页,这次成功",
       P.主.innerHTML === "页面:乙|好了", `主区=${P.主.innerHTML.slice(0, 120)}`);
  }
  { // 对照:正常快速返回,不留任何载入 / 失败痕迹
    const P = await 起手();
    ck("对照:正常切页 —— 新页内容、无载入标记、无失败提示",
       P.主.innerHTML === "页面:甲|旧" && P.主.getAttribute("aria-busy") !== "true",
       `主区=${P.主.innerHTML} aria-busy=${P.主.getAttribute("aria-busy")}`);
  }

  console.log(`\n${坏 ? R + "❌" : G + "✅"} 切页加载状态 ${验 - 坏}/${验}${D}` +
              (坏 ? "" : "(验了 7 种形状 + 对照)"));
  process.exit(坏 ? 1 : 0);
}
跑().catch(e => { console.error(`${R}❌ 判据自己崩了:${e.stack}${D}`); process.exit(2); });
