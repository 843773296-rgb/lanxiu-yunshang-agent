/* 页面冒烟:用最小 DOM 桩**真跑一遍加载路径**,不是只看语法。
 *
 * ⚠️ 为什么非要这一步:上一轮我在另一个项目里验了模块、验了检查、验了 JS 语法,
 * **唯独没在浏览器里打开那一页** —— 而三个读接口写进了 do_POST,
 * 整块功能在浏览器里加载不出来,后端和所有静态检查都正常。
 * **「代码对」和「页面能用」是两回事。**
 */
const fs = require("fs"), path = require("path");
const 基址 = process.env.AIMC_BASE || "http://127.0.0.1:8801";
const 页面 = path.join(__dirname, "..", "..", "apps", "web");
const src = fs.readFileSync(path.join(页面, "app.js"), "utf8");
const html = fs.readFileSync(path.join(页面, "index.html"), "utf8");

const errs = [];
const 写过 = new Map();
function 造(id) {
  const o = {
    id, value: "", textContent: "", style: {}, dataset: {}, disabled: false,
    className: "", classList: { add() {}, remove() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {},
    querySelectorAll: () => [], querySelector: () => null, focus() {},
    set innerHTML(v) { this._h = String(v); 写过.set(id, String(v)); },
    get innerHTML() { return this._h || ""; },
  };
  return o;
}
const 池 = new Map();
function 取(sel) {
  const id = String(sel).replace(/^#/, "");
  if (!池.has(id)) 池.set(id, 造(id));
  return 池.get(id);
}
global.document = {
  querySelector: 取,
  querySelectorAll: () => [],
  body: { classList: { add() {}, remove() {}, contains: () => false } },
  createElement: () => 造("new"),
  addEventListener() {},
};
global.window = { addEventListener() {} };
global.location = { hash: process.argv[2] || "#/workbench" };
global.localStorage = {
  _d: {}, getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
global.crypto = { randomUUID: () => "11111111-2222-3333-4444-555555555555" };
global.alert = (m) => errs.push("alert():" + m);
global.confirm = () => true;
global.prompt = () => null;
const realFetch = global.fetch;
let 请求数 = 0, 请求们 = [];
global.fetch = (u, o) => {
  请求数++; 请求们.push((o && o.method || "GET") + " " + u);
  return realFetch(u.startsWith("http") ? u : 基址 + u, o);
};
process.on("unhandledRejection", (e) => errs.push("未捕获的 Promise:" + (e && e.message || e)));

console.log(`页面冒烟 · ${global.location.hash}\n` + "=".repeat(70));
try { new Function(src)(); }
catch (e) { errs.push("同步执行就挂了:" + e.message); }

setTimeout(() => {
  const 填过 = [...写过.entries()].filter(([, v]) => v && v.length > 12);
  const 字数 = 填过.reduce((n, [, v]) => n + v.length, 0);
  console.log(`  发了 ${请求数} 个请求`);
  请求们.slice(0, 8).forEach((r) => console.log("    " + r));
  console.log(`  写过内容的节点:${填过.length} 个 → ${填过.map(([k]) => "#" + k).join(", ")}`);
  console.log(`  实质内容共 ${字数} 字`);
  if (errs.length) {
    console.log("=".repeat(70));
    errs.forEach((e) => console.log("  ❌ " + e));
    console.log("❌ 页面跑不完 —— 浏览器里的表现就是「框架有,数据没有」");
    process.exit(1);
  }
  /* **占位符不许留在最终内容里** —— 一个永远显示「加载中」的节点在说谎。
   *
   * ⚠️ 但这个桩**不建模嵌套**:页面先往 #main 写一个
   * `<div id="tbl">加载中</div>`,再把表格渲进 #tbl —— 真浏览器里那句
   * 「加载中」已经被子节点替换了,而桩记的还是 #main 那次的原文。
   * 所以判据要排掉这种情况:**如果一个节点的 HTML 里点名了某个 id,
   * 而那个 id 后来也被写过,就说明它的占位已经被子渲染替换了。**
   * 不排的话,这条检查会在所有「壳 + 子容器」的页面上误报,而误报久了人就开始无视它。 */
  const 写过的 = new Set(填过.map(([k]) => k));
  const 占位 = 填过.filter(([k, v]) => {
    if (!/加载中|undefined|NaN|\[object Object\]/.test(v)) return false;
    const 子 = [...v.matchAll(/id="([\w-]+)"/g)].map((m) => m[1]);
    // 它提到的某个子容器后来被写过 → 这段占位已经被替换,不算
    return !子.some((id) => 写过的.has(id) && id !== k);
  });
  if (占位.length) {
    console.log("=".repeat(70));
    console.log(`  ❌ 这几个节点里还留着占位符或坏值:${占位.map(([k]) => "#" + k).join(", ")}`);
    process.exit(1);
  }
  if (请求数 < 2) {
    console.log(`\n❌ 只发了 ${请求数} 个请求 —— 加载路径没跑起来(页面没真的去取数)`);
    process.exit(1);
  }
  if (字数 < 400) {
    console.log(`\n❌ 只填了 ${字数} 字 —— 渲染路径没跑到底`);
    process.exit(1);
  }
  console.log("=".repeat(70));
  console.log(`✅ 页面跑通:${请求数} 个真请求,${填过.length} 个节点被真实数据填充`);
}, 3500);
