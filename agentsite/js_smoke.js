/* 页面脚本冒烟 —— 用最小 DOM 桩在 node 里**真跑一遍加载路径**。
 *
 * 为什么要有:`node --check` 只验语法,验不了「x is not a function」这类运行时错。
 * 而前端这类错的表现和语法错一样阴 —— **框架照常渲染,数据一个都不加载**。
 *
 * 它需要服务在跑(要打真接口),所以**不进 check.sh** ——
 * 一个依赖外部状态的检查放进门禁,迟早变成随机拦路。
 * 用法:./start.sh 之后 `node agentsite/js_smoke.js [页面]`
 */
const fs = require("fs"), path = require("path");
/* 默认页原来写死 panels.html —— 那一页 2026-09-25 按业务要求删掉了,
   于是这个脚本**一跑就 ENOENT 崩在读文件上**,而崩的地方看起来像是环境问题。
   ⚠️ 写死一个会被删掉的文件名,和写死一个会漂的 id 是同一个病。
   现在默认页改成**现挑**:web/ 下有哪些页就在哪些页里挑第一个带 <script> 的。 */
const page = process.argv[2] || (() => {
  const 有 = fs.readdirSync(path.join(__dirname, "web")).filter(f => f.endsWith(".html"))
    .filter(f => fs.readFileSync(path.join(__dirname, "web", f), "utf8").includes("<script>"));
  if (!有.length) { console.error("web/ 下没有带脚本的页面 —— 挑不到就不跑"); process.exit(1); }
  return 有.includes("ai.html") ? "ai.html" : 有[0];
})();
const file = path.join(__dirname, "web", page);
const src = fs.readFileSync(file, "utf8");
const js = src.split("<script>").slice(1).join("<script>").split("</script>")[0];
const ids = [...src.matchAll(/id="([\w-]+)"/g)].map(m => m[1]);

const errs = [];
const el = (id) => ({
  id, _h: "", classList: { add(){}, remove(){}, toggle(){}, contains:()=>false },
  addEventListener(){}, removeEventListener(){}, appendChild(){}, remove(){},
  setAttribute(){}, getAttribute:()=>null, focus(){}, dataset:{}, style:{},
  get innerHTML(){ return this._h; }, set innerHTML(v){ this._h = String(v); },
  get textContent(){ return this._h; }, set textContent(v){ this._h = String(v); },
  value:"", disabled:false, scrollTop:0, closest:()=>null, children:[],
  // 元素身上也能再查子元素 —— 页面里 `s.querySelectorAll(".sug button")` 是常规写法,
  // 桩不给就会报「不是函数」,而浏览器里好好的。**桩不够真,冒烟就会报假警。**
  querySelectorAll(){ return []; }, querySelector(){ return null; },
  scrollHeight:0, hidden:false, onclick:null, title:"",
});
const store = new Map(ids.map(i => [i, el(i)]));
/* select 要给它默认值 —— 浏览器里 <select> 的 value 是第一个 option 的值。
   桩不给的话,像 CHIPS[$("#agkind").value] 这种会拿到 undefined 然后炸,
   **那是桩的错,不是页面的错**。桩不够真,冒烟就会报假警。 */
for (const m of src.matchAll(/<select[^>]*id="([\w-]+)"[\s\S]*?<\/select>/g)) {
  const first = /<option[^>]*value="([^"]*)"/.exec(m[0]);
  if (first && store.has(m[1])) store.get(m[1]).value = first[1];
}
global.document = {
  documentElement:{ setAttribute(){}, getAttribute:()=>null },
  querySelector(s){
    if (s.startsWith("#")) return store.get(s.slice(1)) || null;
    return el("?");
  },
  querySelectorAll(){ return []; },
  addEventListener(){}, createElement:()=>el("new"), body: el("body"),
};
global.window = { __CONF: [] };
const BASE = process.env.BASE || "http://127.0.0.1:8770";
const realFetch = global.fetch;
global.fetch = (u, o) => realFetch(u.startsWith("http") ? u : BASE + u, o);
/* location:调控中心那些页靠 `location.pathname` 判断自己在哪个模块 ——
   桩里没有它,脚本第一行就抛 ReferenceError,而那是**桩的缺口,不是页面的错**。
   路径按页面名推(ai.html → /ai),第四个参数可以指定别的(比如 /ai/runs 进某个模块)。 */
const 路径 = process.argv[4] || "/" + page.replace(/\.html$/, "").replace(/^index$/, "");
global.location = { pathname: 路径, search: "", hash: "", href: BASE + 路径,
                    origin: BASE, host: "127.0.0.1", protocol: "http:" };
process.on("unhandledRejection", e => errs.push("未捕获的 Promise:" + e));

console.log(`页面脚本冒烟 · ${page}\n` + "=".repeat(68));
/* 光跑首屏不够 —— 其它屏是**切屏才加载**的,而合并动的正是那几屏。
   在脚本末尾追加几次 show(),把每条加载路径都真的走一遍。
   station.html 换成对话助手之后没有 show():它的加载路径在脚本末尾就跑完了,
   所以驱动列表给空 —— **不是不测,是那一页不需要切屏就已经全跑过**。 */
const DEFAULT_DRIVE = {"station.html": "", "ai.html": ""};   // panels.html 已删,别再列
const drive = (process.argv[3] !== undefined ? process.argv[3]
              : (DEFAULT_DRIVE[page] !== undefined ? DEFAULT_DRIVE[page] : "")).split(",").filter(Boolean);
const driver = drive.map(s => `try{show(${JSON.stringify(s)})}catch(e){__E.push("show(${s}) 挂了:"+e.message)}`).join(";");
global.__E = errs;
try { new Function(js + "\n;" + driver)(); }
catch (e) { errs.push("同步执行就挂了:" + e.message); }

setTimeout(() => {
  const filled = [...store.entries()].filter(([, v]) => v._h && v._h.length > 12);
  console.log(`  接口 ${BASE} · 页面有 ${ids.length} 个 id`);
  console.log(`  被脚本填过内容的:${filled.length} 个 → ${filled.slice(0,8).map(([k])=>k).join(", ")}`);
  if (errs.length) {
    console.log("\n" + "=".repeat(68));
    errs.forEach(e => console.log("  ❌ " + e));
    console.log("❌ 脚本跑不完 —— 浏览器里的表现就是「框架有,数据没有」");
    process.exit(1);
  }
  /* 原来这里只数「填过的节点个数 < 3 就红」。那个数对**单壳多容器**的页面不成立:
     调控中心那一页所有内容都嵌在 #nav 和 #main 两个容器里,其余 29 个 id 是
     innerHTML 动态生成的,**本来就不会作为独立节点存在** —— 它只有 2 个,而加载路径
     跑得好好的。
     ⚠️ 修法**不是把 3 改小**(那是放宽判据,下次真没加载也照样绿)。
     改成换个问法:节点少的时候,**看填进去的到底是不是实质内容** ——
     加载真没跑起来的页面写不出几百个字符,而且占位符会留在里面。 */
  const 字数 = filled.reduce((n, [, v]) => n + v._h.length, 0);
  const 占位 = filled.filter(([, v]) => /加载中|undefined|NaN|\[object Object\]/.test(v._h))
                     .map(([k]) => k);
  if (占位.length) {
    console.log(`\n❌ 这几个节点里还留着占位符或坏值:${占位.join(", ")}`);
    console.log("   **一个永远不会被填上的占位符在说谎** —— 它看起来像在加载。");
    process.exit(1);
  }
  if (filled.length < 3 && 字数 < 400) {
    console.log(`\n❌ 只填了 ${filled.length} 个节点、共 ${字数} 字 —— 加载路径没跑起来`);
    process.exit(1);
  }
  if (filled.length < 3) {
    console.log(`  （这一页是单壳多容器:内容全嵌在 ${filled.map(([k])=>"#"+k).join(" / ")} 里,`
      + `共 ${字数} 字实质内容）`);
  }
  console.log("\n" + "=".repeat(68));
  console.log(`✅ 脚本跑通,${filled.length} 个节点被真实数据填充`);
}, 4000);
