/* 11-18 夜里新补的三页写操作**在页面代码里真走一遍**(11-19,还体检欠账「新按钮里没被端到端覆盖的写操作」)。
 *
 * 接口那一半早有人测(test_toolgroups_flow / test_lanxiu_knobs_flow / test_http_node_flow),
 * 这里验的是**页面把表单接对了没有**:
 *   ① 工具连接「登记这条连接」:表单上填的名字 / 适配器 / 白名单(一行一条)/ 鉴权 / 密钥引用,原样进了请求体,服务端真存上
 *   ② 工具组「建这个组」→ 详情「加一个成员」→「冻结成 v1」:走过页内两步确认,冻结体里的成员就是挑的那个工具版本,服务端多出 v1
 *   ③ 旋钮方案「建方案」→ 同一张表单「保存草稿」:新建发 POST;改的时候发 PATCH,If-Match 是刚读到的 draft_revision(写死的话第二次就 409)
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

const { ck, 组, 结束 } = 桩.计分(3);
const 建了 = { 连接: null, 组: null, 方案: null };

const 等 = async (条件, 毫秒 = 15000) => {
  const 起 = Date.now();
  while (Date.now() - 起 < 毫秒) { if (条件()) return true; await new Promise((r) => setTimeout(r, 100)); }
  return false;
};

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
    ck("没弹浏览器原生对话框", 弹过.length === 0, 弹过);
  } catch (e) {
    ck("跑完不抛错", false, e && e.stack);
  } finally {
    收尾();
    结束(弹过);
  }
})();
