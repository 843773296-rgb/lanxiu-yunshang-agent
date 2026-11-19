/* 11-18 夜里新补的三页写操作**在页面代码里真走一遍**(11-19,还体检欠账「新按钮里没被端到端覆盖的写操作」)。
 *
 * 接口那一半早有人测(test_toolgroups_flow / test_lanxiu_knobs_flow / test_http_node_flow),
 * 这里验的是**页面把表单接对了没有**:
 *   ① 工具连接「登记这条连接」:表单上填的名字 / 适配器 / 白名单(一行一条)/ 鉴权 / 密钥引用,原样进了请求体,服务端真存上
 *   ② 工具组「建这个组」→ 详情「加一个成员」→「冻结成 v1」:走过页内两步确认,冻结体里的成员就是挑的那个工具版本,服务端多出 v1
 *   ③ 旋钮方案「建方案」→ 同一张表单「保存草稿」:新建发 POST;改的时候发 PATCH,If-Match 是刚读到的 draft_revision(写死的话第二次就 409)
 *   ④ 评测中心「发起」(11-20 补,体检欠账「评测发起没进测试」—— 原来以为要真模型,其实派发用「开始 → 结束」的工作流就不调模型):
 *      外部登记 → 体里四样齐、带 Idempotency-Key、服务端真建了一条;后台派发漏填超时 / 费用上限 → 422 逐字段摆在表单下;
 *      填齐 → 真派出 2 题 × 2 边 × 1 轮 = 4 次运行(不花钱),然后取消掉
 *      ⚠️ 后台派发的候选 / 基线下拉要把项目里**每个**有版本的工作流详情都取一遍(演示项目 1400 多个),
 *      这里不等它、直接往输入框里写版本 id —— 下拉本身没验,只验「提交时把选中的值和数字字段接对了」
 *
 * 只在演示项目 A 上跑(U001 是 admin)。建的东西名字都带 e2e,**进程退出时按 id / 方案号删掉**
 * (挂在 process.on("exit"):页面换页后晚到的读请求可能永远不结束、await 卡住,finally 不一定跑 —— 日志策略那份的教训)。
 * ⚠️ 桩不建模嵌套 DOM(querySelectorAll 恒空、取(id) 永远拿得到元素),所以:
 *   · 「加载角色 / 必不可少 / 配套」那几个下拉在这里收不到,冻结体只验成员 id;
 *   · 旋钮表单「是不是改表单」看的是 #kn-cancel 在不在 —— 桩里它永远在,所以「新建」那条路靠方案号还不存在来走。
 */
"use strict";
const fs = require("fs"), path = require("path");
const { execFileSync } = require("child_process");
const 桩 = require("./_页面桩.js");

const 项目 = "project_demo_a";
const P = 桩.P(项目);
const src = fs.readFileSync(path.join(__dirname, "..", "..", "apps", "web", "app.js"), "utf8");
const 库 = process.env.DATABASE_URL
  ? process.env.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
  : `postgresql://${process.env.USER}@localhost:5432/aimc_dev`;
const sql = (q) => execFileSync("psql", ["-X", "-q", "-A", "-t", 库, "-c", q], { encoding: "utf8" }).trim();
const 引 = (s) => String(s).replace(/'/g, "''");
const 尾 = Date.now().toString(16).slice(-6);

const { ck, 组, 结束 } = 桩.计分(4);
const 建了 = { 连接: null, 组: null, 方案: null, 评测们: [] };

const 等 = async (条件, 毫秒 = 15000) => {
  const 起 = Date.now();
  while (Date.now() - 起 < 毫秒) { if (条件()) return true; await new Promise((r) => setTimeout(r, 100)); }
  return false;
};

async function 造两版工作流() {
  // 照 test_eval_dispatch_flow:开始 → 结束,结束把输入里的 article 原样交出去;候选多交一个「回显」(逻辑一样的两版冻不出来)
  const [, w] = await 桩.直打("POST", `${P}/workflows`, { 名称: `e2e 页面发起评测 ${尾}`, 模板: "空白" }, "U001");
  const wid = w && w.id; if (!wid) return {};
  建了.工作流 = wid;
  const 改草稿 = async (改) => {
    const [, d] = await 桩.直打("GET", `${P}/workflows/${wid}`, null, "U001");
    const 定义 = d["草稿"]["定义"]; 改(定义);
    await 桩.直打("PATCH", `${P}/workflows/${wid}/draft`, { 定义 }, "U001", { "If-Match": String(d["草稿"].revision) });
  };
  await 改草稿((定义) => {
    定义.edges = [{ source: "start", target: "finish", port: "success" }];
    定义.nodes.forEach((n) => { if (n.type === "end") n.config.bindings = { summary: { source: "input", pointer: "/article" } }; });
  });
  const [, v1] = await 桩.直打("POST", `${P}/workflows/${wid}/versions`, { 变更说明: "e2e 页面发起 基线" }, "U001");
  await 改草稿((定义) => {
    定义.nodes.forEach((n) => { if (n.type === "end") {
      n.config.output_schema.properties["回显"] = { type: "string" };
      n.config.bindings["回显"] = { source: "input", pointer: "/article" }; } });
    定义.output_schema.properties["回显"] = { type: "string" };
  });
  const [, v2] = await 桩.直打("POST", `${P}/workflows/${wid}/versions`, { 变更说明: "e2e 页面发起 候选" }, "U001");
  return { v1: v1 && v1.id, v2: v2 && v2.id };
}

function 造题集() {
  // 冻结题集直接落库(照 test_eval_dispatch_flow 的 造题集):2 道题,都有工作流输入
  const did = `ds_e2e${尾}`, dv = `dsv_e2e${尾}`;
  const 题 = [1, 2].map((i) => ({ id: `smp_e2e${尾}${i}`, content: { 输入: { article: `页面发起第 ${i} 题` } } }));
  const org = `(select organization_id from projects where id='${项目}')`;
  try {
    sql(`insert into datasets (id, organization_id, project_id, name, format, purpose, created_at, created_by, updated_at, revision)
         values ('${did}', ${org}, '${项目}', 'e2e 页面发起评测 ${尾}', 'jsonl', '评测', now(), 'test', now(), 1)`);
    for (const t of 题) {
      sql(`insert into samples (id, organization_id, project_id, dataset_id, content, source, review_status, split, content_hash,
             created_at, created_by, updated_at, revision)
           values ('${t.id}', ${org}, '${项目}', '${did}', '${引(JSON.stringify(t.content))}'::jsonb, '自测', '已通过', '独立测试',
             md5('${t.id}'), now(), 'test', now(), 1)`);
    }
    sql(`insert into dataset_versions (id, organization_id, project_id, dataset_id, split_map, content_hash, sample_count,
           frozen_samples, created_at, created_by, revision)
         values ('${dv}', ${org}, '${项目}', '${did}', '{"独立测试": 2}'::jsonb, md5('${dv}'), 2, '${引(JSON.stringify(题))}'::jsonb,
           now(), 'test', 1)`);
    return dv;
  } catch (e) { console.log("  ⚠️ 造题集失败:" + e.message); return null; }
}

(async () => {
  console.log("\n\x1b[1m▸ 新补三页的写操作:工具连接 / 工具组冻结 / 旋钮方案\x1b[0m");
  let 收了 = false;
  const 收尾 = () => {
    if (收了) return; 收了 = true;
    try {
      if (建了.连接) sql(`delete from capability_connections where project_id='${项目}' and id='${引(建了.连接)}'`);
      if (建了.组) {
        sql(`delete from tool_group_versions where project_id='${项目}' and tool_group_id='${引(建了.组)}'`);
        sql(`delete from tool_groups where project_id='${项目}' and id='${引(建了.组)}'`);
      }
      if (建了.方案) sql(`delete from knob_plans where project_id='${项目}' and key='${引(建了.方案)}'`);
      // 评测是只追加的历史,不删;派发那一条在 ④ 里已经取消掉(子运行跟着取消),这里只兜「中途挂了没取消」
      for (const eid of 建了.评测们) {
        sql(`update execution_runs set status='cancelled', finished_at=now() where project_id='${项目}' and status in ('queued','running')
               and id in (select execution_run_id from evaluation_runs where project_id='${项目}' and evaluation_id='${引(eid)}')`);
      }
    } catch (e) { console.log("  ⚠️ 收尾没删干净:" + e.message); }
  };
  process.on("exit", 收尾);

  const { 取, 请求们, 弹过 } = 桩.装桩({ hash: "#/integrations/conns", 我: "U001", 项目 });
  global.document.getElementById = (id) => 取(id);
  global.document.body.appendChild = () => {};
  const 换到 = async (hash, 钮) => { 取(钮).onclick = null; location.replace(hash); return await 等(() => typeof 取(钮).onclick === "function"); };
  try {
    桩.跑页面(src);

    // ── ① 工具连接 ────────────────────────────────────────────────
    组("① 工具连接:表单上填的原样进请求体,服务端真存上");
    const 到了 = await 等(() => typeof 取("cc-go").onclick === "function");
    ck("工具连接页摆出了登记表单(U001 是 admin)", 到了);
    if (!到了) return;
    const 名 = `e2e 页面登记 ${尾}`;
    取("cc-nm").value = 名; 取("cc-ad").value = "http";
    取("cc-ep").value = "https://e2e.example.com/a\n\n  https://e2e.example.com/b  ";
    取("cc-au").value = "自定义头"; 取("cc-hd").value = "x-e2e-key"; 取("cc-sr").value = "env://E2E_PAGE_REF";
    await 取("cc-go").onclick();
    const 写1 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/capability-connections`)).pop();
    const 体1 = 写1 && JSON.parse(写1.体);
    ck("发了 POST /capability-connections", !!写1, 写1);
    ck("白名单按行拆、去空行去空格", 体1 && JSON.stringify(体1["允许的端点"]) === JSON.stringify(["https://e2e.example.com/a", "https://e2e.example.com/b"]), 体1);
    ck("鉴权带方式和头名,密钥只走引用字段", 体1 && 体1["鉴权"]["方式"] === "自定义头" && 体1["鉴权"]["头名"] === "x-e2e-key"
       && 体1.secret_ref === "env://E2E_PAGE_REF" && Object.keys(体1).length === 5, 体1);
    const [c1, 列1] = await 桩.直打("GET", `${P}/capability-connections`, null, "U001");
    const 行1 = c1 === 200 && (列1["连接"] || []).find((x) => x["名字"] === 名);
    if (行1) 建了.连接 = 行1.id;
    ck("服务端列表里有这一条,端点和鉴权都对", !!行1 && (行1["允许的端点"] || []).length === 2
       && (行1["鉴权"] || {})["头名"] === "x-e2e-key", 行1 || c1);
    ck("页面写出了「登记好了」", 取("ccmsg").innerHTML.includes("登记好了"), 取("ccmsg").innerHTML.slice(0, 200));

    // ── ② 工具组:建 → 加成员 → 冻结 ────────────────────────────────
    组("② 工具组:建组、挑一个成员、过两步确认冻结成 v1");
    ck("换到工具组列表页,建组表单摆出来了", await 换到("#/integrations/groups", "tg-go"));
    const 组名 = `e2e 页面冻结 ${尾}`;
    取("tg-nm").value = 组名; 取("tg-pu").value = "端到端:验页面冻结按钮的接线";
    await 取("tg-go").onclick();
    const 建组 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/tool-groups`)).pop();
    const [c2, 组列] = await 桩.直打("GET", `${P}/tool-groups`, null, "U001");
    const 组行 = c2 === 200 && (组列.items || []).find((x) => x["名称"] === 组名);
    if (组行) 建了.组 = 组行.id;
    ck("发了建组 POST,服务端有这个组", !!建组 && !!组行, 组行 || c2);
    if (!组行) return;
    ck("建完把地址指到了这个组的详情", String(location.hash) === `#/integrations/groups/${encodeURIComponent(组行.id)}`, location.hash);
    ck("详情页摆出了「加一个成员」", await 换到(location.hash, "tgf-add"));
    const [, 资] = await 桩.直打("GET", `${P}/workflow-resources`, null, "U001");
    const 工具 = ((资 || {})["工具"] || [])[0];
    ck("演示项目里至少有一个可选工具(没有就冻不了,是夹具问题不是页面问题)", !!工具, 资 && Object.keys(资));
    if (!工具) return;
    取("tgf-pick").value = 工具["版本id"];
    await 取("tgf-add").onclick();
    取("wq-ok").onclick = null;
    const 冻 = 取("tgf-go").onclick();
    const 问了 = await 等(() => typeof 取("wq-ok").onclick === "function", 5000);
    ck("冻结前走页内两步确认(不是浏览器原生对话框)", 问了 && 弹过.length === 0, 弹过);
    if (!问了) return;
    取("wq-ok").onclick();
    await 冻;
    const 冻体 = 请求们.filter((r) => r.方法 === "POST" && r.地址.includes(`/tool-groups/${组行.id}/versions`)).pop();
    const 体2 = 冻体 && JSON.parse(冻体.体);
    ck("冻结体里的成员就是挑的那一个工具版本", 体2 && (体2["成员"] || []).length === 1
       && 体2["成员"][0].tool_version_id === 工具["版本id"], 体2);
    const [c3, 详] = await 桩.直打("GET", `${P}/tool-groups/${encodeURIComponent(组行.id)}`, null, "U001");
    ck("服务端这个组多出 v1", c3 === 200 && (详["版本历史"] || []).length === 1 && 详["版本历史"][0]["版本"] === "v1",
       c3 === 200 ? (详["版本历史"] || []).map((v) => v["版本"]) : c3);
    ck("页面写出了「冻结了 v1」", 取("tgdmsg").innerHTML.includes("冻结了") && 取("tgdmsg").innerHTML.includes("v1"), 取("tgdmsg").innerHTML.slice(0, 200));

    // ── ③ 旋钮方案:建 → 改 ───────────────────────────────────────
    组("③ 旋钮方案:建方案发 POST;同一张表单改草稿发 PATCH,If-Match 是刚读到的 draft_revision");
    ck("换到旋钮页,方案表单摆出来了", await 换到("#/knobs", "kn-go"));
    const 号 = `e2e-旋钮页面${尾}`;
    取("kn-key").value = 号; 取("kn-why").value = "端到端:验页面建方案的接线";
    取("kn-v-effort").value = "high"; 取("kn-v-max_turns").value = "8";
    const 旧go = 取("kn-go").onclick;
    await 旧go();
    const 建 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/knob-plans`)).pop();
    const 体3 = 建 && JSON.parse(建.体);
    ck("发了 POST /knob-plans,体里是表单上填的(整数旋钮发成数字)", 体3 && 体3["方案号"] === 号
       && 体3["旋钮"].effort === "high" && 体3["旋钮"].max_turns === 8, 体3);
    const [c4, 方1] = await 桩.直打("GET", `${P}/knob-plans/${encodeURIComponent(号)}`, null, "U001");
    if (c4 === 200) 建了.方案 = 号;
    ck("服务端存上了,draft_revision 1", c4 === 200 && 方1["旋钮"].effort === "high" && String(方1.draft_revision) === "1", c4 === 200 ? 方1 : c4);
    if (c4 !== 200) return;
    // 建完页面整页重画、重新挂了 onclick(带着新的方案列表)—— 用新挂的那一个
    ck("建完页面重画并重新挂了提交按钮", await 等(() => typeof 取("kn-go").onclick === "function" && 取("kn-go").onclick !== 旧go, 5000));
    // ⚠️ 先在页面外改一次,把 draft_revision 推到 2,再重进这一页。不推的话刚建的方案恰好是 1,
    // 前端把 If-Match 写死成 1 也照样过 —— 11-19 咬合时这条就没红,判据看不出差别
    const [c推] = await 桩.直打("PATCH", `${P}/knob-plans/${encodeURIComponent(号)}/draft`, { 为什么: "端到端:页面外先改一次" }, "U001", { "If-Match": "1" });
    ck("页面外先改一次,draft_revision 推到 2", c推 === 200, c推);
    ck("重进旋钮页", await 换到("#/knobs", "kn-go"));
    const [, 方1b] = await 桩.直打("GET", `${P}/knob-plans/${encodeURIComponent(号)}`, null, "U001");
    取("kn-key").value = 号; 取("kn-why").value = "端到端:改成 low"; 取("kn-v-effort").value = "low"; 取("kn-v-max_turns").value = "8";
    await 取("kn-go").onclick();
    const 改 = 请求们.filter((r) => r.方法 === "PATCH" && r.地址.includes(`/knob-plans/${encodeURIComponent(号)}/draft`)).pop();
    ck("改草稿发的是 PATCH(不是又建一个)", !!改, 改);
    ck("**If-Match = 刚读到的 draft_revision(2,不是 1)**", 改 && String(方1b.draft_revision) === "2"
       && String(改.头["If-Match"]) === "2", 改 && [改.头["If-Match"], 方1b.draft_revision]);
    const [c5, 方2] = await 桩.直打("GET", `${P}/knob-plans/${encodeURIComponent(号)}`, null, "U001");
    ck("服务端改上了:effort=low,draft_revision 3", c5 === 200 && 方2["旋钮"].effort === "low" && String(方2.draft_revision) === "3", c5 === 200 ? 方2 : c5);

    // ── ④ 评测中心「发起」────────────────────────────────────────
    组("④ 评测发起:外部登记建一条;后台派发漏填 422 逐字段摆出来;填齐真派 4 次运行再取消");
    const 版 = await 造两版工作流();
    const 集 = 造题集();
    ck("夹具:一条「开始 → 结束」工作流冻了两版 + 一套 2 题的冻结题集", 版.v1 && 版.v2 && 集, [版, 集]);
    if (!(版.v1 && 版.v2 && 集)) return;
    ck("换到评测中心,发起表单摆出来了", await 换到("#/evals", "ev-go"));
    取("ev-mode").value = "外部登记";
    取("ev-cand").value = `e2e 候选 ${尾}`; 取("ev-base").value = `e2e 基线 ${尾}`;
    取("ev-dsv").value = 集; 取("ev-scorer").value = "e2e-判据@1";
    await 取("ev-go").onclick();
    const 登 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/evaluations`)).pop();
    const 体4 = 登 && JSON.parse(登.体);
    ck("外部登记:体里四样齐、不带派发字段", 体4 && 体4["执行方式"] === "外部登记" && 体4["候选"] === `e2e 候选 ${尾}`
       && 体4["数据集版本"] === 集 && 体4["判据版本"] === "e2e-判据@1" && !("超时分钟" in 体4), 体4);
    ck("带 Idempotency-Key(评测要花钱,超时重发不能再跑一遍)", 登 && /^[0-9a-f-]{36}$/.test(String(登.头["Idempotency-Key"] || "")), 登 && 登.头);
    const 行6 = sql(`select id || '|' || baseline_ref from evaluations where project_id='${项目}' and candidate_ref='${引(`e2e 候选 ${尾}`)}'`);
    if (行6) 建了.评测们.push(行6.split("|")[0]);
    ck("服务端真建了这条外部登记(基线也存上了)", !!行6 && 行6.endsWith(`|e2e 基线 ${尾}`), 行6);

    // 后台派发:**不触发切换下拉**(见文件头),直接把方式和版本 id 写进去
    ck("重进评测中心", await 换到("#/evals", "ev-go"));
    取("ev-mode").value = "后台派发";
    取("ev-cand").value = 版.v2; 取("ev-base").value = 版.v1; 取("ev-dsv").value = 集; 取("ev-scorer").value = "跑通-v1";
    取("ev-timeout").value = ""; 取("ev-cap").value = ""; 取("ev-rounds").value = "1"; 取("ev-judge").value = "";
    await 取("ev-go").onclick();
    const 漏 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/evaluations`)).pop();
    const 体5 = 漏 && JSON.parse(漏.体);
    ck("漏填:超时 / 费用上限留白送 null,轮数送数字 1", 体5 && 体5["超时分钟"] === null && 体5["费用上限"] === null && 体5["轮数"] === 1, 体5);
    const fb = 取("ev-fb").innerHTML;
    ck("422 逐字段摆在表单下面(超时分钟、费用上限都点名)", fb.includes("超时分钟") && fb.includes("费用上限") && fb.includes("<li>"), fb.slice(0, 300));
    ck("挂了之后「发起」按钮放开,能改了再点", 取("ev-go").disabled === false);

    取("ev-timeout").value = "30"; 取("ev-cap").value = "1";
    await 取("ev-go").onclick();
    const 派 = 请求们.filter((r) => r.方法 === "POST" && r.地址.endsWith(`${P}/evaluations`)).pop();
    const 体6 = 派 && JSON.parse(派.体);
    ck("填齐:超时 / 费用上限发成数字,候选 / 基线是选中的工作流版本", 体6 && 体6["超时分钟"] === 30 && 体6["费用上限"] === 1
       && 体6["候选"] === 版.v2 && 体6["基线"] === 版.v1 && !("评审连接" in 体6), 体6);
    const 号7 = sql(`select id from evaluations where project_id='${项目}' and dataset_version_id='${集}' and candidate_ref='${引(版.v2)}'`);
    const 行7 = 号7 ? { id: 号7 } : null;
    if (行7) 建了.评测们.push(行7.id);
    const 派次 = 行7 ? Number(sql(`select count(*) from evaluation_runs where project_id='${项目}' and evaluation_id='${引(行7.id)}'`)) : -1;
    ck("服务端真派了 2 题 × 2 边 × 1 轮 = 4 次运行", 派次 === 4, [号7, 派次]);
    const msg = 取("ev-msg").innerHTML;
    ck("页面写出「已建」和派了几次", msg.includes("已建") && msg.includes("派了"), msg.slice(0, 200));
    if (行7) {
      const 版7 = sql(`select revision from evaluations where project_id='${项目}' and id='${引(行7.id)}'`);
      const [c8] = await 桩.直打("POST", `${P}/evaluations/${encodeURIComponent(行7.id)}/cancel`, { 理由: "端到端:验完发起就取消" }, "U001",
        { "If-Match": 版7 });
      ck("收尾:派出去的这次评测取消掉(子运行跟着取消)", c8 === 200, c8);
    }

    ck("没弹浏览器原生对话框", 弹过.length === 0, 弹过);
  } catch (e) {
    ck("跑完不抛错", false, e && e.stack);
  } finally {
    收尾();
    结束(弹过);
  }
})();
