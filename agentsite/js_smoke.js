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
/* ⚠️⚠️ 2026-10-14:原来是 `/id="([\w-]+)"/` —— **`\w` 不匹配中文**,
   于是 `id="关钮"` / `id="展"` / `id="g日"` 这类**一个都扫不到**,
   `$("#关钮")` 在桩里返回 null。

   而这个缺口**至今没人发现**,因为页面大多写成 `const b=$("#展"); if(b) b.onclick=…`
   —— 有 `if(b)` 保护的就**静默跳过**了:它不报错,只是让那几段代码从来没被冒烟跑过。
   > 一个「这段代码冒烟验过了」和一个「桩取不到那个元素所以整段被跳过了」,
   > **在冒烟的那个 ✅ 上长得一模一样。**

   全站现有 5 个中文 id(`g日` / `g月` / `g周` / `关钮` / `展`),这一改它们才进冒烟视野。 */
const ids = [...src.matchAll(/id="([^"]+)"/g)].map(m => m[1]);

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
for (const m of src.matchAll(/<select[^>]*id="([^"]+)"[\s\S]*?<\/select>/g)) {
  const first = /<option[^>]*value="([^"]*)"/.exec(m[0]);
  if (first && store.has(m[1])) store.get(m[1]).value = first[1];
}
global.document = {
  documentElement:{ setAttribute(){}, getAttribute:()=>null },
  querySelector(s){
    if (s.startsWith("#")) return store.get(s.slice(1)) || null;
    return el("?");
  },
  /* 2026-10-15 补:桩里原来**没有 getElementById** —— report.html / scheme.html 直接调它,
     第一行就抛「不是函数」,冒烟红,而浏览器里好好的(数据工厂 10-14 查出)。
     它和上面的 querySelector("#x") 取的是**同一份**元素表,别各存一份。 */
  getElementById(i){ return store.get(i) || null; },
  querySelectorAll(){ return []; },
  addEventListener(){}, createElement:()=>el("new"), body: el("body"),
};
global.window = { __CONF: [] };
/* alert:tasks.html 等页会调 —— 桩不给就抛「不是函数」,而浏览器里只是弹个框(10-15 补)。 */
global.alert = () => {};
const BASE = process.env.BASE || "http://127.0.0.1:8770";
const realFetch = global.fetch;
/* **要登录的页面先登录**(用户 2026-10-15 拍:配测试账号自动登录)。
   这几页第一件事是 fetch("/api/me"),401 就 location.href="/login" 然后 return ——
   桩里给 href 赋值既不跳转也不报错,**加载路径在那一行静默终止**,冒烟永远「填了 0 个」,
   而那几页的加载代码从来没被冒烟跑过。
   账号**不抄**:工号从登录页的演示账号清单里按岗位取(role_check 也读这一段),
   口令从 seed.py 的 DEMO_PW 读(公开的演示口令,本来就写在 seed 里)。抄一份,改了那边这边就过期。 */
const 要登录 = {"contract.html": "店长", "pad.html": "工匠", "report.html": "店长", "tasks.html": "店长",
                "triage-settings.html": "总部运营", "triage-board.html": "总部运营"};   // 研判设置(10-19):只有总部运营改,读要登录
let 饼 = "";
async function 登录() {
  const 岗 = process.env.SMOKE_ROLE || 要登录[page];
  if (!岗) return;
  const 段 = (/class="demo"([\s\S]*?)<\/div>/.exec(fs.readFileSync(path.join(__dirname, "web", "login.html"), "utf8")) || [])[1] || "";
  const 号 = (new RegExp(">\\s*" + 岗 + "\\s*<code>(\\d{8})</code>").exec(段) || [])[1];
  const 口令 = (/DEMO_PW\s*=\s*"([^"]+)"/.exec(fs.readFileSync(path.join(__dirname, "..", "backend", "seed.py"), "utf8")) || [])[1];
  if (!号 || !口令) { errs.push(`要登录却取不到演示账号(岗位 ${岗}:工号${号 ? "有" : "没有"}、口令${口令 ? "有" : "没有"})`); return; }
  const r = await realFetch(BASE + "/api/login", {method: "POST", headers: {"content-type": "application/json"},
                                                  body: JSON.stringify({login_name: 号, password: 口令})});
  const c = (r.headers.get("set-cookie") || "").split(";")[0];
  if (!r.ok || !c) { errs.push(`用演示账号(${岗})登录失败:HTTP ${r.status}`); return; }
  饼 = c;
  console.log(`  以演示账号「${岗}」登录后再跑(这一页要登录才加载)`);
}
global.fetch = (u, o = {}) => realFetch(u.startsWith("http") ? u : BASE + u,
  饼 ? {...o, headers: {...(o.headers || {}), cookie: 饼}} : o);
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
/* **要网址参数的页面,参数运行时现取**(10-15):合同页没有 ?order= 时按设计只显示一句「没有订单」——
   那是对的,但等于没测加载路径。订单号**不写死**(夹具写死会漂的 id,数据一变就过期),
   每次现找一张「本店的、有确认书的」:翻订单列表前几页,筛登录者门店,逐个问 /api/contract/ 直到有一张能看。 */
const 现取参数 = {
  "contract.html": async () => {
    const me = await (await fetch("/api/me")).json();
    for (let pg = 1; pg <= 5; pg++) {
      // ⚠️ **每页要 100 条**:`/api/orders` 默认每页只有 10 条(server.py 的 `_page`),
      // 翻 5 页才 50 条 —— 而订单按 `created` 倒序,前面全是每天上新造的标品单,
      // 静安第一张有确认书的排在第 185 位,**根本够不着**。
      // 2026-10-15 补完 56 份确认书之后这一页仍然红,红的理由正是这个,
      // 不是「库里没有确认书」。
      const os = (await (await fetch("/api/orders?per=100&page=" + pg)).json()).rows || [];
      for (const o of os.filter(o => o.shop === me.shop)) {
        const r = await fetch("/api/contract/" + encodeURIComponent(o.id));
        if (r.ok) return "?order=" + encodeURIComponent(o.id);
      }
    }
    errs.push(`在「${me.shop}」的前 5 页订单里找不到一张有确认书的 —— 没法测合同页的加载路径(不是页面坏了)`);
    return "";
  },
};
global.__E = errs;
(async () => {
await 登录();
if (现取参数[page]) {
  location.search = await 现取参数[page]();
  if (location.search) console.log(`  网址参数现取:${location.search}`);
}
/* 本站的外部脚本(`<script src="/md.js">`)也要跑。
   ⚠️ 上面取内联脚本用的是 `src.split("<script>")` —— **精确匹配,不含属性**,
   所以 `<script src="…">` 根本切不中,整个被忽略。
   表现是 contract.html 当场 `ReferenceError: md is not defined`,
   而那不是页面坏了:浏览器里 md.js 是真的加载了的。
   > 一个「页面用了一个不存在的函数」和一个「桩没加载它依赖的脚本」,
   > **在那条 ReferenceError 上长得一模一样。**
   只取本站的绝对路径(`/xxx.js`),CDN 不碰 —— 冒烟不该依赖外网。
   拼在内联脚本**前面**一起跑,这样它定义的东西内联脚本看得见。 */
let 外部 = "";
for (const m of src.matchAll(/<script\s+src="(\/[^"]+)"\s*><\/script>/g)) {
  try {
    外部 += await fetch(BASE + m[1]).then(r => r.ok ? r.text() : "") + "\n;";
    console.log(`  外部脚本:${m[1]}`);
  } catch (e) { errs.push(`取不到外部脚本 ${m[1]}:${e.message}`); }
}
try { new Function(外部 + js + "\n;" + driver)(); }
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
  /* **没有加载路径的页面**(10-15):登录页、手机预约页是纯表单 —— 脚本只绑提交回调,不点按钮就什么都不该填。
     拿「填了几个节点」判它们,红的理由就是错的(「加载路径没跑起来」,而它本来就没有加载路径)。
     ⚠️ 修法**不是把下面的 3 / 400 调小**(那是放宽,下次真没加载也照样绿),是把这一类单列、在输出里说清。
     单列的页面仍然要过上面那关:脚本**同步执行不许挂**(errs 非空照样红)。 */
  const 纯表单 = {"login.html": "登录表单,点「登录」才发请求", "m.html": "手机端预约表单,点「提交」才发请求"};
  if (纯表单[page]) {
    console.log("\n" + "=".repeat(68));
    console.log(`✅ 脚本跑通(这一页没有加载路径:${纯表单[page]} —— 不按「填了几个节点」判)`);
    return;
  }
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
})();
