/* 发布链的四步**在页面代码里真走一遍**(§13.3)。
 *
 * ## 为什么要有它
 *
 * `page_smoke.js` 证明的是「取到数并渲染了」——**它不点任何东西**。
 * 而发布这四步最容易错的地方一个都不在渲染上:
 *
 * | 容易错的地方 | 错了会怎样 | 别的测试盖得到吗 |
 * |---|---|---|
 * | 改候选用了**指针**的 revision | 409,而 409 读起来像「别人改过了」 | ❌ |
 * | 切指针用了**候选**的 revision | 同上 | ❌ |
 * | 第一次绑定时硬塞一个 If-Match | 服务端拿它和不存在的行比 | ❌ |
 * | 幂等键在**渲染时**生成 | 「点了没反应再点一次」变成两个动作 | ❌ |
 * | 发布/回滚漏了幂等键 | 409 IDEMPOTENCY_KEY_REQUIRED | ❌ |
 *
 * `tests/e2e/test_release_flow.py` 打的是接口,它证明接口对 ——
 * **不证明页面把参数接对了**。而真浏览器那一份(`test_upload_page_firefox.py`)
 * 要弹一个 Firefox 窗口,所以不进门禁。
 *
 * > **「接口对」和「页面把它接对了」是两件事**,而后者错的时候
 * > 表现是「点了没反应」或者一个读不懂的 409。
 *
 * 所以这一份:用同一个最小 DOM 桩把 `app.js` 跑起来,然后**直接调**
 * `globalThis.发布链动作` 里那五个函数 —— 打的是真接口,验的是真接线。
 *
 * ⚠️ 它**不验界面长什么样**。那一半仍然只有 `page_smoke.js`(加载路径)
 * 和真浏览器那一份。这个盲区写在这儿,免得下一个人以为这一页全验过了。
 */
const fs = require("fs"), path = require("path");
const 基址 = process.env.AIMC_BASE || "http://127.0.0.1:8801";
const 项目 = process.env.AIMC_PROJECT || "project_demo_a";
const 页面 = path.join(__dirname, "..", "..", "apps", "web");
const src = fs.readFileSync(path.join(页面, "app.js"), "utf8");

let 过 = 0;
const 挂 = [];

/* ⚠️ **走过几组要数出来,而且有下限。**
 *
 * 第一版没有这个:`出清单` 那一步抛了异常,而 `结束()` 写在 `finally` 里,
 * 于是它**先 process.exit(0)** —— 测试跳过了大半断言然后报了 ✅。
 * 输出上唯一的迹象是「② 出清单」那行标题下面空着。
 *
 * > **「跳过了」和「通过了」在输出上长得一模一样。**
 *
 * 所以这里照这个仓库的成语走:**声明该跑几组,少一组就红** ——
 * 和「检查必须声明验了多少个,样本量为 0 要红」是同一条。
 * 这个数是**手写的字面量**,不许写成 `走过.length`(那样它永远等于现状)。
 */
const 该跑几组 = 7;
const 走过 = [];
function 组(名) { 走过.push(名); console.log(`\n▸ ${名}`); }
function ck(名, 真, 补) {
  const 补文 = 补 === undefined ? "" : "  " + String(
    typeof 补 === "object" ? JSON.stringify(补) : 补).slice(0, 150);
  console.log(`  ${真 ? "✅" : "❌"} ${名}${补文}`);
  if (真) 过++; else 挂.push(名);
}

/* ── 最小 DOM 桩(和 page_smoke.js 同一套思路)────────────────────── */
const 池 = new Map();
function 造(id) {
  return {
    id, value: "", textContent: "", style: {}, dataset: {}, disabled: false,
    className: "", classList: { add() {}, remove() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, remove() {},
    querySelectorAll: () => [], querySelector: () => null, focus() {},
    set innerHTML(v) { this._h = String(v); }, get innerHTML() { return this._h || ""; },
  };
}
function 取(sel) {
  const id = String(sel).replace(/^#/, "");
  if (!池.has(id)) 池.set(id, 造(id));
  return 池.get(id);
}
global.document = {
  querySelector: 取, querySelectorAll: () => [],
  body: { classList: { add() {}, remove() {}, contains: () => false } },
  createElement: () => 造("new"), addEventListener() {},
};
global.window = { addEventListener() {} };
global.location = { hash: "#/apps" };
global.localStorage = {
  _d: { "aimc.user": "U002", "aimc.proj": 项目 },
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
/* ⚠️ 幂等键**不能桩成固定值**。page_smoke 那份桩成了一个常量
 * (它只加载,不发写请求,所以无所谓);这一份真的要发两次不同的发布动作,
 * 固定值会让第二次命中第一次的幂等记录 ——
 * 于是「幂等生效了」和「我的桩坏了」长得一模一样。 */
let 发过的键 = [];
global.crypto = {
  randomUUID: () => {
    const k = "k" + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
    发过的键.push(k);
    return k;
  },
};
global.alert = (m) => 挂.push("alert():" + m);
global.confirm = () => true;
global.prompt = () => null;

/* 记下每一次真实请求,**连头一起记** —— 这一份的判据一多半在头上。 */
const realFetch = global.fetch;
const 请求们 = [];
global.fetch = (u, o) => {
  const url = String(u);
  请求们.push({ 方法: (o && o.method) || "GET", 地址: url,
                头: Object.assign({}, (o && o.headers) || {}) });
  return realFetch(url.startsWith("http") ? url : 基址 + url, o);
};

function 头里(片段, n) {
  // 倒数第 n 个匹配这个片段的请求(默认最后一个)
  const 命中 = 请求们.filter((r) => r.地址.includes(片段));
  return 命中.length ? 命中[命中.length - (n || 1)] : null;
}

async function 打(方法, 路, 体, 谁) {
  const h = { "X-Dev-User": 谁 || "U002" };
  if (体) h["content-type"] = "application/json";
  const r = await realFetch(`${基址}/api/v1/projects/${项目}${路}`, {
    method: 方法, headers: h,
    body: 体 ? JSON.stringify(体) : undefined,
  });
  let b = null;
  try { b = await r.json(); } catch (e) { b = null; }
  return [r.status, b];
}

(async () => {
  console.log("\n\x1b[1m▸ 发布链四步 · 在页面代码里真走一遍\x1b[0m");
  console.log("  ⚠️ 验的是**接线**(哪个 revision 进哪个头、幂等键怎么生成),"
    + "不验界面长什么样");

  // 把 app.js 跑起来,拿到那五个动作
  try { new Function(src)(); } catch (e) {
    ck("app.js 同步执行不挂", false, e.message);
    结束(); return;
  }
  const 动 = globalThis.发布链动作;
  ck("app.js 把 `发布链动作` 导出来了(导不出来的话这一份只能靠真浏览器)",
     动 && typeof 动.出清单 === "function" && typeof 动.发布 === "function",
     动 ? Object.keys(动) : null);
  if (!动) { 结束(); return; }

  // ── 夹具:自己建一个应用,别动现成的 ──────────────────────────────
  // ⚠️ 拿现成应用来点,会把别人的生产指针切走 ——
  // **攻击测试写脏了不还原,下一轮的结论就不可信,而且先害的是别人那份测试。**
  const 名 = `发布链页面-${Math.random().toString(16).slice(2, 8)}`;
  let [码, app] = await 打("POST", "/applications", { 名字: 名, 流水线: "prompt" });
  ck("建一个自己的应用当夹具 → 201", 码 === 201 && app && app.id, 码);
  if (!app || !app.id) { 结束(); return; }
  const aid = app.id;

  try {
    // ⚠️ 要的是 **Prompt 版本的 id**,不是 Prompt 的 id。
    // 第一版我拿 `GET /prompts` 的第一项当版本号填了进去 ——
    // `PATCH draft` 收下了(200),到出清单那一刻撞外键,**报 500**。
    // 那是个真缺陷(已修:填的时候就拦,422 指到字段上),
    // 而它同时也是我的错:两个前缀不同而肉眼很像。
    const [, 列] = await 打("GET", "/prompts");
    const 某prompt = ((列 || {}).items || [])[0] || {};
    const [, pd] = await 打("GET", `/prompts/${encodeURIComponent(某prompt.id)}`);
    // ⚠️ 字段叫 `版本历史`(不是 `版本`/`versions`)—— 猜错了上面那条断言
    // 会报「借不到」,而真因是字段名。所以**查过再写**,别猜。
    const 版本们 = ((pd || {})["版本历史"] || []);
    const PV = 版本们.find((v) => v && v.id) || null;
    let [, 详0] = await 打("GET", `/applications/${aid}`);
    // 连接版本:从任意一份已有清单里借一个确切版本
    const [, hist0] = await 打("GET", "/applications");
    let CV = null;
    for (const a of ((hist0 || {}).应用 || [])) {
      const [, h] = await 打("GET", `/applications/${a.id}/releases`);
      const m = ((h || {}).清单们 || [])[0];
      if (m && m.清单 && m.清单.connection_version_id) {
        CV = m.清单.connection_version_id; break;
      }
    }
    ck("借到一个确切的 Prompt **版本**和模型连接版本(借不到的话下面全是空跑)",
       Boolean(PV && PV.id && CV), { PV: PV && PV.id, CV });
    if (!(PV && PV.id && CV)) { return; }

    // ── ① 改候选:**建应用就把草稿建出来了,所以第一次也要带 If-Match** ──
    组("① 改候选:两个 revision 别拿错");
    // ⚠️ 这一组的第一版断言写的是「新应用的候选revision 是 null,第一次不带
    // If-Match」—— **量出来是 1**。`POST /applications` 会同时插入草稿行,
    // 而 `PATCH draft` 无条件要 If-Match。也就是说那个「第一次」的状态
    // **根本不会出现**,而接口注释和前端都照着它写了一段走不到的分支。
    // 判据抓到的是**我的假设错了**,不是代码错 —— 这一族今天第五次。
    ck("新应用的 `候选revision` 就是个数字(建应用时草稿一起建出来了,"
       + "**不存在「还没有草稿」这个状态**)",
       typeof (详0 || {}).候选revision === "number", (详0 || {}).候选revision);
    ck("而且它和**应用的** revision 不是一个数(拿错就是 409,"
       + "而 409 读起来像「别人改过了」)",
       typeof (详0 || {}).revision === "number", 
       { 候选: (详0 || {}).候选revision, 应用: (详0 || {}).revision });
    let r = await 动.改候选(aid, { prompt_version_id: PV.id,
                                connection_version_id: CV },
                          (详0 || {}).候选revision);
    ck("改候选 → 拿到新 revision", typeof r.revision === "number", r.revision);
    const 第一次 = 头里("/draft");
    ck("带的 If-Match 就是 `候选revision`",
       第一次 && 第一次.头["If-Match"] === String((详0 || {}).候选revision),
       { 带的: 第一次 && 第一次.头["If-Match"], 该带: (详0 || {}).候选revision });
    ck("候选现在能出清单了", r["现在能出清单吗"] === true, r["还差什么"]);

    // ⚠️ **填一个不存在的版本号要在这里就被拦住,不是到出清单才炸。**
    // 这一条是这份测试第一次跑时撞出来的真缺陷:候选愉快地收下(200),
    // 出清单时撞外键 → `IntegrityError` → **500**,而错误体里只有
    // 「这是服务端问题,把 trace_id 给运维」——**一个字都没说是哪个字段**。
    // 拿 Prompt 的 id 当 Prompt 版本的 id 填,是最容易犯的那种。
    let 坏填 = null;
    let [, 详半] = await 打("GET", `/applications/${aid}`);
    try {
      await 动.改候选(aid, { prompt_version_id: 某prompt.id },
                    (详半 || {}).候选revision);
    } catch (e) { 坏填 = e; }
    ck("把 **Prompt 的 id** 当版本号填 → **422 而不是 500**",
       坏填 && 坏填.码 === 422 && (坏填.体 || {}).code === "DEPENDENCY_NOT_FOUND",
       坏填 && { 码: 坏填.码, code: (坏填.体 || {}).code });
    ck("而且**指到那个字段上**(只说「填错了」的话人得自己猜是哪一个)",
       坏填 && Boolean(((坏填.体 || {}).field_errors || {}).prompt_version_id),
       坏填 && ((坏填.体 || {}).field_errors || {}).prompt_version_id);

    // ⚠️ **钉住那个「走不到的兜底」被换掉了这件事。**
    // 原来的写法是 revision 为 null 时**不带 If-Match 发出去** ——
    // 那个分支永远走不到,而它真被触发的那天做的是错的事:
    // 换来一个 409 IF_MATCH_REQUIRED,而那句话不告诉人真正发生了什么。
    // 现在它**当场本地报错并说清**:null 只可能是草稿行丢了。
    let 空rev = null;
    const draft数之前 = 请求们.filter((x) => x.地址.includes("/draft")).length;
    try { await 动.改候选(aid, { prompt_version_id: PV.id }, null); }
    catch (e) { 空rev = e; }
    ck("`候选revision` 是 null 时 → **当场本地报错**,"
       + "不拿它去发一个注定 409 的请求",
       空rev && (空rev.体 || {}).code === "NO_DRAFT_REVISION",
       空rev && { code: (空rev.体 || {}).code, 消息: 空rev.message.slice(0, 40) });
    // ⚠️ 量的是**这一次调用前后的差**,不是一个写死的总数。
    // 第一版写的是「总数 === 1」,而我后来在它前面又加了一条断言
    // (也发 /draft)—— 于是判据红了,而红的理由和它要守的性质无关。
    // > **写死一个会随上下文漂的期望值,等于给自己埋一次假红。**
    ck("而且它**根本没发出请求**(发出去再被 409 拒,和不发是两件事 ——"
       + "前者会在审计里留一条读不懂的失败)",
       请求们.filter((x) => x.地址.includes("/draft")).length === draft数之前,
       { 之前: draft数之前,
         之后: 请求们.filter((x) => x.地址.includes("/draft")).length });

    // 第二次改:这回**必须**带
    let [, 详1] = await 打("GET", `/applications/${aid}`);
    await 动.改候选(aid, { prompt_version_id: PV.id }, (详1 || {}).候选revision);
    const 第二次 = 头里("/draft");
    ck("第二次改候选**带上了 If-Match**,而且是`候选revision`(不是应用的)",
       第二次 && 第二次.头["If-Match"] === String((详1 || {}).候选revision),
       { 带的: 第二次 && 第二次.头["If-Match"],
         候选revision: (详1 || {}).候选revision,
         应用revision: (详1 || {}).revision });

    // ── ② 出清单 ───────────────────────────────────────────────
    组("② 出清单(冻结依赖)");
    const 出 = await 动.出清单(aid);
    ck("出清单 → 拿到清单 id,而且是新建的",
       Boolean(出.id) && 出["新建了吗"] === true, { id: 出.id, 新建: 出["新建了吗"] });
    const rid = 出.id;

    // ── ③ 发布:**权限在前,闸在后** ────────────────────────────
    组("③ 发布:权限先拦,然后才是「没审过」那道闸");
    // ⚠️ 这两件事**必须分开断**。第一版只断了「没审过 → 422」,
    // 而当时的身份是 editor,于是拿到的是 **403**,判据红了 ——
    // 而它红的理由(「生产只认审过的清单」失败)**指错了地方**:
    // 真相是请求连闸都没走到,在权限那一层就被拒了。
    // > 两条都成立才叫「拦住了」,而它们被拦的**位置**不同,下一步也不同。
    let 权限拦 = null;
    try { await 动.发布(rid, "production", null); } catch (e) { 权限拦 = e; }
    ck("editor 发生产 → **403**(权限在最外层,连闸都走不到)",
       权限拦 && 权限拦.码 === 403, 权限拦 && { 码: 权限拦.码, code: (权限拦.体 || {}).code });
    const 发1 = 头里("/deploy");
    ck("这一次发布**带了幂等键**(发布是异步 + 对外的动作,超时重发是常态)",
       发1 && typeof 发1.头["Idempotency-Key"] === "string",
       发1 && 发1.头["Idempotency-Key"]);
    ck("目标环境还没有绑定 → **没带 If-Match**"
       + "(硬塞一个的话服务端会拿它和一行不存在的记录比)",
       发1 && 发1.头["If-Match"] === undefined, 发1 && 发1.头);

    // 换成有审核/发布权限的身份 —— 页面靠 localStorage 记身份
    global.localStorage.setItem("aimc.user", "U001");
    try { new Function(src)(); } catch (e) { ck("换身份后重载 app.js", false, e.message); }
    const 动2 = globalThis.发布链动作;
    let 闸拦 = null;
    try { await 动2.发布(rid, "production", null); } catch (e) { 闸拦 = e; }
    ck("换成有权限的身份、清单还没审 → **422 CANNOT_DEPLOY**(这才是那道闸)",
       闸拦 && 闸拦.码 === 422 && (闸拦.体 || {}).code === "CANNOT_DEPLOY",
       闸拦 && { 码: 闸拦.码, code: (闸拦.体 || {}).code });
    ck("而且**逐条给了为什么**(只显示 message 的话,"
       + "人看到的是「不能发」而看不到为什么)",
       闸拦 && (((闸拦.体 || {}).field_errors || {})["闸"] || []).length > 0,
       闸拦 && ((闸拦.体 || {}).field_errors || {})["闸"]);

    // ── ④ 审核 ─────────────────────────────────────────────────
    组("④ 审核:记的是「审的哪一份内容」");
    const 审 = await 动2.审核(rid, "通过", "页面接线测试");
    ck("审核通过 → 记下**审的哈希**(不是一个布尔)",
       审["结论"] === "通过" && Boolean(审["审的哈希"]), 审);
    let [, one] = await 打("GET", `/releases/${rid}`, null, "U001");
    ck("详情里 `这次审核还算数吗` = true", (one || {})["这次审核还算数吗"] === true,
       (one || {})["为什么"]);

    // ── ⑤ 发布:第一次绑定 → 不带 If-Match;第二次 → 必须带 ─────────
    组("⑤ 发布:指针 revision 要带对");
    const 发 = await 动2.发布(rid, "production", null);
    ck("发生产 → 指针切到这一份", 发["到"] === rid, { 从: 发["从"], 到: 发["到"] });
    let [, 详2] = await 打("GET", `/applications/${aid}`, null, "U001");
    const rev = (((详2 || {}).各环境 || {}).production || {}).revision;
    ck("详情里**拿得到指针 revision**(拿不到就只能不带 If-Match 发,"
       + "而那正是「后到的悄悄覆盖先到的」那条路)",
       typeof rev === "number", rev);

    // 再出一份新清单 → 审 → 带着**过期的** revision 发,必须 409
    await 动2.改候选(aid, { evaluation_id: null }, (详2 || {}).候选revision);
    // ⚠️ 要的是第二个 **Prompt 版本**,不是第二个 Prompt。
    // 第一版在这儿又栽了同一个:拿 `GET /prompts` 的 id 当版本号,
    // 于是新加的那条「填错 id → 422」**正确地把它拦了**,
    // 而这一组就断在这里。**判据是对的,我的步骤不对 —— 今天第六次。**
    let 另一个PV = null;
    for (const pr of ((列 || {}).items || [])) {
      const [, x] = await 打("GET", `/prompts/${encodeURIComponent(pr.id)}`,
                            null, "U001");
      const 候 = ((x || {})["版本历史"] || []).map((v) => v.id)
        .find((v) => v && v !== PV.id);
      if (候) { 另一个PV = 候; break; }
    }
    ck("找得到第二个 Prompt **版本**(找不到的话下面几条是空跑)",
       Boolean(另一个PV), 另一个PV);
    if (另一个PV) {
      let [, 详3] = await 打("GET", `/applications/${aid}`, null, "U001");
      await 动2.改候选(aid, { prompt_version_id: 另一个PV }, (详3 || {}).候选revision);
      const 出2 = await 动2.出清单(aid);
      ck("依赖变了 → 另出一份新清单", 出2["新建了吗"] === true && 出2.id !== rid,
         { 新建: 出2["新建了吗"], 同一份: 出2.id === rid });
      await 动2.审核(出2.id, "通过", "第二份");
      let 冲 = null;
      try { await 动2.发布(出2.id, "production", 999); } catch (e) { 冲 = e; }
      ck("拿**过期的** If-Match 发 → 409 REVISION_CONFLICT"
         + "(这就是它挡住的那件事)",
         冲 && 冲.码 === 409 && (冲.体 || {}).code === "REVISION_CONFLICT",
         冲 && { 码: 冲.码, code: (冲.体 || {}).code });
      const 发2 = await 动2.发布(出2.id, "production", rev);
      ck("拿**对的** If-Match 发 → 切过去了", 发2["到"] === 出2.id,
         { 从: 发2["从"], 到: 发2["到"] });

      // ── ⑥ 回滚:是一次新的部署,不是把历史改回去 ──────────────────
      组("⑥ 回滚:新的部署动作,不是改历史");
      const 回 = await 动2.回滚(aid, rid, "production");
      ck("回滚提交了", Boolean(回), JSON.stringify(回).slice(0, 90));
      const 回请求 = 头里("/rollbacks");
      ck("回滚也带了幂等键", 回请求 && typeof 回请求.头["Idempotency-Key"] === "string",
         回请求 && 回请求.头["Idempotency-Key"]);
      let [, h2] = await 打("GET", `/applications/${aid}/releases`, null, "U001");
      ck("**两份清单都还在**(回滚没有把历史改回去 —— "
         + "改历史的话「上周二在跑哪一版」会变成现在这一版)",
         ((h2 || {}).清单们 || []).length >= 2, (h2 || {}).条数);
      let [, 详4] = await 打("GET", `/applications/${aid}`, null, "U001");
      ck("生产指针回到了老那一份",
         (((详4 || {}).各环境 || {}).production || {})["指着哪一版"] === rid,
         (((详4 || {}).各环境 || {}).production || {})["指着哪一版"]);
    }

    // ── ⑦ 幂等键:每次调用一个新的 ───────────────────────────────
    组("⑦ 幂等键");
    const 键们 = 请求们.filter((r) => r.头["Idempotency-Key"])
      .map((r) => r.头["Idempotency-Key"]);
    ck("每一次写动作都带了幂等键", 键们.length >= 3, 键们.length);
    ck("**每次都是新的键**(渲染时生成的话,「点了没反应再点一次」"
       + "会带着同一个键 —— 或者更糟,带着新键把一个动作变成两件事)",
       new Set(键们).size === 键们.length, { 发过: 键们.length, 不同: new Set(键们).size });
  } catch (e) {
    // ⚠️ **异常必须记成失败。** 第一版只有 finally,于是任何一步抛出来
    // 都会被 `结束()` 的 process.exit(0) 盖掉 —— 报绿,而大半断言没跑。
    ck(`跑到「${走过[走过.length - 1] || "开头"}」就抛了:${e.message}`, false,
       (e.体 && JSON.stringify(e.体).slice(0, 160)) || String(e.stack || "").slice(0, 200));
  } finally {
    // 收尾:归档这个夹具应用。
    // ⚠️ 归档不是删除 —— 这个后台没有硬删接口(而那是有意的)。
    // 所以这里**不假装清干净了**,只把它移出列表并说一句。
    const [码归] = await 打("PATCH", `/applications/${aid}/draft`,
                          { prompt_version_id: null }, "U001").catch(() => [0]);
    console.log(`\n▸ 收尾:夹具应用 ${aid} 留在库里(**这个后台没有硬删接口,`
      + `而那是有意的**)—— 它叫 ${名},和真实应用分得开`);
    结束();
  }
})();

function 结束() {
  console.log("");
  if (走过.length !== 该跑几组) {
    console.log(`  ❌ 只跑到第 ${走过.length} 组(该跑 ${该跑几组} 组)—— `
      + `**中间断了**。跑过的:${走过.join(" / ") || "一组都没跑"}`);
    console.log(`     ⚠️ 这条判据是为了让「跳过了」和「通过了」长得不一样 —— `
      + `第一版没有它,于是一次异常换来一个 ✅。`);
    挂.push(`只跑到第 ${走过.length}/${该跑几组} 组`);
  }
  if (挂.length) {
    console.log(`❌ ${挂.length} 条挂了`);
    挂.forEach((x) => console.log("   · " + x));
    process.exit(1);
  }
  console.log(`✅ 过 ${过} / 挂 0`);
  console.log("⚠️ 这一份验的是**接线**,不验界面长什么样 —— "
    + "那一半是 page_smoke.js(加载路径)和真浏览器那一份");
  process.exit(0);
}
