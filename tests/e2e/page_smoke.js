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
/* ⚠️ **hash 形状不对 = 夹具自己坏了,当场报。**
 * Makefile 里把 `#` 转义坏过一次:传进来的是 `\#/workflow/wf_x`,
 * 路由认不出 → 掉到「这一页还没实现」→ 冒烟**绿的**,
 * 而下面那条画布结构对账的正则匹配不上,于是它**一声没出就跳过了**。
 * 「跳过了」和「通过了」在输出上长得一模一样 —— 这条断言就是为了让它们不一样。 */
if (!/^#\//.test(global.location.hash)) {
  console.log(`  ❌ 传进来的 hash 是 ${JSON.stringify(global.location.hash)} —— `
    + `不是 #/… 的形状。**这是夹具/调用方的问题,不是页面的问题**:`
    + `路由认不出它会掉到「还没实现」那一页,然后一切看起来都正常。`);
  process.exit(1);
}
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
  /* ── 结构断言:**「有内容」不等于「画出来了」** ──────────────────
   *
   * 上面那几行只数字数。一个把 #cv 写成 `<svg></svg>` 的画布 ——
   * 节点一个没渲、连线一条没画 —— 在字数上完全正常,在「写过内容的节点」
   * 列表里也完全正常。**这正是「空壳」这种坏法能活下来的原因。**
   *
   * 所以画布页额外对账:API 说有几个节点几条边,#cv 里就该有几个 .wfnode
   * 和几条 <path>。数量从**接口返回的定义**里数,不从页面自己数 ——
   * 从页面数就是拿被测的东西算期望值(同源谬误)。 */
  if (/^#\/workflow\//.test(global.location.hash)) {
    const wid = decodeURIComponent(global.location.hash.slice(11));
    const 结构错 = [];
    realFetch(`${基址}/api/v1/projects/project_demo_a/workflows/${wid}`,
              { headers: { "X-Dev-User": "U002" } })
      .then((r) => r.json()).then((d) => {
        const 定义 = (d["草稿"] || {})["定义"] || { nodes: [], edges: [] };
        const cv = 写过.get("cv") || "";
        const 节点数 = (cv.match(/class="wfnode/g) || []).length;
        const 连线数 = (cv.match(/<path /g) || []).length;
        if (节点数 !== 定义.nodes.length)
          结构错.push(`画布上 ${节点数} 个节点,定义里有 ${定义.nodes.length} 个`);
        if (连线数 !== (定义.edges || []).length)
          结构错.push(`画布上 ${连线数} 条连线,定义里有 ${(定义.edges || []).length} 条`);
        const lib = 写过.get("lib") || "";
        const 可用数 = (d["节点库"] || []).filter((n) => n["可用"]).length;
        const 加入数 = (lib.match(/data-add=/g) || []).length;
        if (加入数 !== 可用数)
          结构错.push(`节点库 ${加入数} 个「加入」按钮,可用节点 ${可用数} 个 —— `
            + `**拖拽不能是唯一操作方法**(§3.3)`);
        if (!/未实现/.test(lib))
          结构错.push("节点库里没有标「未实现」的项 —— 那四个节点该显示但禁用");
        if (结构错.length) {
          console.log("=".repeat(70));
          结构错.forEach((e) => console.log("  ❌ " + e));
          console.log("❌ 画布是个空壳 —— **「有内容」不等于「画出来了」**");
          process.exit(1);
        }
        console.log(`  画布结构对账:${节点数} 个节点 / ${连线数} 条连线 / `
          + `${加入数} 个「加入」按钮,和接口返回的定义一致`);
      }).catch((e) => { console.log("  ⚠️ 结构对账没跑成:" + e.message); });
  }

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
