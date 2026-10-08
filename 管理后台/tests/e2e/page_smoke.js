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
  // ⚠️ 允许从环境变量预置身份和项目 —— **为了能验「换个身份看另一个项目」**。
  // 不能预置的话,页面桩永远跑默认身份(U002)能看到的那个项目,
  // 而**一个新建的项目默认不被任何冒烟盖住**(和「新页面不被冒烟盖住」同形)。
  _d: Object.fromEntries([
    ["aimc.user", process.env.AIMC_USER], ["aimc.proj", process.env.AIMC_PROJECT],
  ].filter(([, v]) => v)),
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
global.crypto = { randomUUID: () => "11111111-2222-3333-4444-555555555555" };
global.alert = (m) => errs.push("alert():" + m);
global.confirm = () => true;
global.prompt = () => null;
// ⚠️ **对账要比「同一个身份看同一个项目」** —— 别硬编(2026-10-02 改)。
//
// 原来三处都硬编 `project_demo_a` + 自己挑一个身份。那时只有演示项目,
// 所以从来没错位过。10-02 导入澜绣那 79 条铁律、建了 `project_lanxiu`
// 之后,这件事变成了一个**靠巧合成立**的对账:
//   · 页面桩的默认身份是 U002(`app.js` 里 `let 我 = … || "U002"`)
//   · 而我只给 admin 建了澜绣的成员 —— 于是 U002 看不到澜绣,
//     页面仍然渲 demo_a,对账也查 demo_a,**碰巧一致**
//
// 两层脆弱:
//   ① **项目错位** —— U002 哪天被加进澜绣,页面渲澜绣而对账查 demo_a,
//      报出来是「这几条的 id 没出现在页面上」,**看起来像页面渲错了**
//   ② **身份错位** —— 页面用 U002 渲、对账用 U001 查。权限不同的话
//      U001 看得到的条数更多,于是对账说「这几条没渲」而页面完全正确
//
// > **一条对账如果不是比「同一个身份看同一个项目」,它迟早会报一个假错。**
//
// 页面正好把这两样都写进了 localStorage(`aimc.proj` / `aimc.user`),
// 而桩的 localStorage 是可读的 —— 所以直接取页面实际用的那两个值。
const 页面用的项目 = () => localStorage.getItem("aimc.proj") || "project_demo_a";
const 页面用的身份 = () => localStorage.getItem("aimc.user") || "U002";
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
    realFetch(`${基址}/api/v1/projects/${页面用的项目()}/workflows/${wid}`,
              { headers: { "X-Dev-User": 页面用的身份() } })
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

  /* Agent 配置页的结构对账 —— 同一条道理:**「有内容」不等于「填上了」**。
   * 一个连接下拉框渲染成空的(只有「(没选)」那一项)在字数上完全正常,
   * 而它的表现是「这个 Agent 选不了模型」—— 而人会去怀疑接口。
   * 数量从**接口返回的可选项**里数,不从页面自己数。 */
  if (/^#\/agent\//.test(global.location.hash)) {
    const aid = decodeURIComponent(global.location.hash.slice(8));
    realFetch(`${基址}/api/v1/projects/${页面用的项目()}/agents/${aid}`,
              { headers: { "X-Dev-User": 页面用的身份() } })
      .then((r) => r.json()).then((d) => {
        const body = 写过.get("body") || "";
        const 坏 = [];
        // 下拉框:可选连接数 + 一个「(没选)」
        const opt = (body.match(/<option /g) || []).length;
        const 应 = (d["可选连接"] || []).length + 1;
        if (opt !== 应)
          坏.push(`连接下拉框 ${opt} 项,接口给了 ${应 - 1} 条连接(+1 个「没选」)`);
        // **能力那一栏必须写出来**:附录 D.2「不按模型家族名字推断兼容」
        if (!/原生工具调用/.test(body))
          坏.push("连接那一栏没写「原生工具调用」—— "
                  + "**那一栏显示的必须是探测回来的能力,不是模型叫什么**(附录 D.2)");
        if (坏.length) {
          console.log("=".repeat(70));
          坏.forEach((e) => console.log("  ❌ " + e));
          console.log("❌ Agent 配置页是个空壳");
          process.exit(1);
        }
        console.log(`  Agent 页结构对账:连接下拉框 ${opt} 项(含「没选」),`
          + `能力那一栏写了「原生工具调用」`);
      }).catch((e) => { console.log("  ⚠️ 结构对账没跑成:" + e.message); });
  }

  /* ── 列表页的**行级对账**:「渲染了」不等于「渲的是那些东西」 ──────────
   *
   * ⚠️ 上面那些判据能抓「空壳」(一个字都没渲),抓不住**渲错了对象** ——
   * 一个把第 2 页的数据渲到第 1 页、或者漏了三条、或者把 id 写成别人的列表,
   * 在字数和节点数上**完全正常**。
   * 交接里那条欠账写的就是这个:「页面冒烟分不出『这一页对不对』」。
   *
   * 做法照画布那两个特例的思路,但**改成声明式** ——
   * 写死两个特例的代价是:第三页来的时候没人会想起要加一个。
   *
   * 每条声明回答三个问题:
   *   · 这一页的数据从哪条接口来(`接口`)
   *   · 列表在响应里的哪个字段(`列表`)
   *   · 每一行的身份是哪个字段(`身份`,默认 `id`)
   *
   * 然后断三件:
   *   ① **接口返回的每一条,身份都要出现在渲染出来的 HTML 里** ——
   *      这一条最值钱:它抓「渲的是别的对象」和「漏了几条」。
   *      期望值来自**接口**,不从页面自己数(从页面数就是同源谬误)。
   *   ② 渲出来的行数不少于接口给的条数(页面可以多画表头,不许少画行)。
   *   ③ **列表为空时必须有一句人话** ——
   *      「什么都没有」和「成功地什么都没有」必须长得不一样。
   *
   * ⚠️ 没声明的页面**不算通过,算「这一页只验了加载路径」** ——
   * 并且在输出里明说。一个静悄悄跳过的对账,和没有对账是一回事。
   */
  const 对账表 = {
    "#/prompts": { 接口: "/prompts", 列表: "items" },
    "#/workflows": { 接口: "/workflows", 列表: "items" },
    "#/agents": { 接口: "/agents", 列表: "items" },
    "#/tools": { 接口: "/tools", 列表: "items" },
    "#/human": { 接口: "/human-requests", 列表: "items" },
    "#/apps": { 接口: "/applications", 列表: "应用" },
    "#/conns": { 接口: "/model-connections", 列表: "连接" },
    "#/members": { 接口: "/memberships", 列表: "成员", 身份: "工号" },
    "#/datasets": { 接口: "/datasets", 列表: "数据集" },
    "#/artifacts": { 接口: "/model-artifacts", 列表: "产物" },
    // ⚠️ 这个列表字段叫 `任务` 不是 `items` —— 我第一版猜了 `items`,
    // 而判据**点名说清那是对账表自己写错**(不是指着页面说它渲错了)。
    // > 一个把自己的错报成被测对象的错的判据,会把人送去查一个没坏的东西。
    "#/training": { 接口: "/training-jobs", 列表: "任务" },
    "#/kb": { 接口: "/knowledge-bases", 列表: "items" },
  };
  const 声明 = 对账表[global.location.hash];
  if (声明) {
    const 全文 = [...写过.values()].join("\n");
    realFetch(`${基址}/api/v1/projects/${页面用的项目()}${声明.接口}`,
              { headers: { "X-Dev-User": 页面用的身份() } })
      .then((r) => r.json()).then((d) => {
        const 列 = (d || {})[声明.列表];
        const 坏 = [];
        if (!Array.isArray(列)) {
          // ⚠️ **字段名猜错了不算通过。** 猜错的表现是「列表是 undefined」,
          // 而那时候「页面渲错了」和「我写错了字段名」长得一模一样。
          坏.push(`接口 ${声明.接口} 的响应里没有 \`${声明.列表}\` 这个列表 —— `
            + `**这是对账表自己写错了,不是页面的问题**。`
            + `顶层有:${Object.keys(d || {}).join(", ")}`);
        } else {
          const 身份字段 = 声明.身份 || "id";
          const 行数 = (全文.match(/<tr/g) || []).length;
          if (列.length === 0) {
            // ③ 空列表要有人话 —— **按结构判,不按词表判**
            //
            // ⚠️ 2026-10-02 改的。原来判的是 `/还没有|一个都没有|还没|没有任何/`
            // 命中全文,两头都错:
            //   · `#/human` 写的是「**没有待办**」+「Agent 请求不可逆写入时
            //     会在这里出现」—— 一句完全合格的人话,而词表里没有它,于是报红。
            //     **判据和页面都没错,红的是判据的定位方式。**
            //   · 反过来更糟:它搜的是**整个页面**。哪一页的页头说明里
            //     碰巧有「还没」,它就在页面真的一片空白时**打绿勾**。
            // > **一个按词表判「有没有说人话」的判据,
            // > 它真正判的是「用了我这几个词吗」。**
            //
            // 现在判结构:必须有一个 `状态()` 块(`<div class="state">`)
            // 带着**非空的标题和非空的说明**。
            //   · 「加载中…」那个块没有 `<h3>`,所以认不出来 → 仍然红(对的)
            //   · `class="state err"` 是错误块 → 单独报,别和「空」混起来
            //     (接口给了空列表而页面显示错误,是另一件事)
            const 错块 = /<div class="state err"/.test(全文);
            const 空块 = /<div class="state\s*">\s*<h3>([^<]+)<\/h3>\s*<p>([\s\S]*?)<\/p>/
              .exec(全文);
            const 说明 = 空块 ? 空块[2].replace(/<[^>]*>/g, "").trim() : "";
            if (错块) {
              坏.push("接口返回**空列表**,而页面显示的是**错误块** —— "
                + "**「没有东西」和「取不到东西」必须分得开**");
            } else if (!空块) {
              坏.push("接口返回**空列表**,而页面上没有一个带标题和说明的"
                + "空状态块(`<div class=\"state\"><h3>…</h3><p>…</p>`)—— "
                + "**「什么都没有」和「成功地什么都没有」必须长得不一样**");
            } else if (说明.length < 6) {
              // 只有标题不够:「没有待办」四个字答不了「那我该干什么」。
              坏.push(`空状态只有标题「${空块[1]}」而说明是空的 —— `
                + "**一个只说「没有」的空页面,不告诉人「它什么时候会有」**");
            }
          } else {
            // ① 每一条的身份都要出现
            const 没渲的 = 列.map((x) => String((x || {})[身份字段] || ""))
              .filter((v) => v && !全文.includes(v));
            if (没渲的.length) {
              坏.push(`接口给了 ${列.length} 条,而这 ${没渲的.length} 条的`
                + `\`${身份字段}\` **没出现在页面上**:`
                + `${没渲的.slice(0, 4).join(", ")}${没渲的.length > 4 ? " …" : ""}`
                + ` —— 漏渲 / 渲成了别的对象,**在字数上完全正常**`);
            }
            // ② 行数不许少于条数
            if (行数 > 0 && 行数 < 列.length) {
              坏.push(`页面上 ${行数} 个 <tr>,接口给了 ${列.length} 条 —— `
                + `**少画了行**(多画表头可以,少画行不行)`);
            }
          }
        }
        if (坏.length) {
          console.log("=".repeat(70));
          坏.forEach((e) => console.log("  ❌ " + e));
          console.log("❌ 行级对账没过 —— **「渲染了」不等于「渲的是那些东西」**");
          process.exit(1);
        }
        // ⚠️ **0 条的时候别说「每一条都在页面上」** —— 空集合上所有性质都成立,
        // 那句话听起来像验过了一批东西,而它一条都没验。
        // 这一页在 CI 上**恰好总是 0 条**(待办挂在运行上,而运行是测试跑出来的),
        // 所以那句措辞不是小事:它会让人以为 CI 盖住了列表渲染。
        console.log((列 || []).length === 0
          ? `  行级对账:接口 ${声明.接口} 给了 **0 条** —— 验的是`
            + `「空列表有一句人话」,**没有验任何一行的渲染**`
          : `  行级对账:接口 ${声明.接口} 给了 ${列.length} 条,`
            + `每一条的 ${声明.身份 || "id"} 都在页面上`);
      }).catch((e) => { console.log("  ⚠️ 行级对账没跑成:" + e.message); });
  } else if (/^#\/[a-z]+$/.test(global.location.hash)) {
    // ⚠️ **明说没对账,不静悄悄跳过。**
    console.log(`  ⚠️ 这一页**没有行级对账**(对账表里没声明)—— `
      + `只验了加载路径,**渲错了对象看不出来**`);
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
    // ⚠️ **报出命中的那一段,别只报节点名。** 2026-10-07 加:
    // 一条「#tdbody 里还留着占位符」的报错,和一条「#tdbody 第 N 字处是
    // `undefined`,上下文是 …」的,**在那行红字上长得一模一样** ——
    // 而前者让人去翻几千字的 HTML(实测那一页 12701 字),后者直接指出位置。
    for (const [k, v] of 占位) {
      for (const 坏 of ["加载中", "undefined", "NaN", "[object Object]"]) {
        let i = v.indexOf(坏);
        let 报过 = 0;
        while (i >= 0 && 报过 < 3) {
          const 上下文 = v.slice(Math.max(0, i - 90), i + 50)
            .replace(/\s+/g, " ").trim();
          console.log(`     · #${k} 第 ${i} 字处是 \`${坏}\`:…${上下文}…`);
          报过 += 1;
          i = v.indexOf(坏, i + 1);
        }
      }
    }
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
