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
const page = process.argv[2] || "panels.html";
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
process.on("unhandledRejection", e => errs.push("未捕获的 Promise:" + e));

console.log(`页面脚本冒烟 · ${page}\n` + "=".repeat(68));
/* 光跑首屏不够 —— 其它屏是**切屏才加载**的,而合并动的正是那几屏。
   在脚本末尾追加几次 show(),把每条加载路径都真的走一遍。
   station.html 换成对话助手之后没有 show():它的加载路径在脚本末尾就跑完了,
   所以驱动列表给空 —— **不是不测,是那一页不需要切屏就已经全跑过**。 */
const DEFAULT_DRIVE = {"panels.html": "fabric,wearer,health", "station.html": ""};
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
  if (filled.length < 3) {
    console.log("\n❌ 几乎没有节点被填充 —— 加载路径没跑起来");
    process.exit(1);
  }
  console.log("\n" + "=".repeat(68));
  console.log(`✅ 脚本跑通,${filled.length} 个节点被真实数据填充`);
}, 4000);
