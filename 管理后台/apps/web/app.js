/* 澜绣云裳 AI 管理后台 · 前端
 *
 * ⚠️ 这是**记录在案的偏离**:规格 §17.1 默认前端是 React + TS + Vite + Ant Design。
 * 这里用无构建步骤的原生 JS。理由写在 README:API 已经是契约边界,
 * 前端换成 React 只需重写 apps/web/;而把预算花在 build 工具链上,
 * 换来的是更少的可验证功能。**不假装这是默认方案。**
 *
 * ⚠️ 规格 §5.2 有一句很硬的话:**「不可把「禁用前端按钮」当后端授权。」**
 * 所以下面所有「按权限显示/隐藏」只是提示;真正的拦截在服务端每个请求上,
 * 而那条已经被 tests/e2e 的 35 条断言验过(viewer 建 Prompt → 403 等)。
 */
"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
  .replace(/`(.+?)`/g, "<code>$1</code>");

/* ⚠️ **`title=` 属性里渲染不了粗体** —— 而后端那些说明文案里带着 `**`。
 * 原样塞进 title,用户在 tooltip 里看到的就是两个星号。
 * 所以属性里**去掉标记**(内容一个字不少),不是去渲染它。
 * 2026-10-08 页面冒烟那条「渲染后不许有字面星号」接上退出码之后,
 * 一次就抓出 8 页 —— 其中三页是 tooltip,就是这一类。*/
const 去粗 = (s) => String(s ?? "").replace(/\*\*/g, "");

/* ⚠️ **`esc()` 拿到对象会给出 `[object Object]`,而那是个合法字符串。**
 * 2026-10-07 页面冒烟第一次打工具详情页就抓到:版本历史那一列写的是
 *     esc(v["确认策略"] || "—")
 * 而 `确认策略` 是 jsonb(`{"谁批":"approver","为什么":"…"}`)——
 * 界面上真的显示着那六个字。
 * > 一个「esc 了一个字符串」和一个「esc 了一个对象」,
 * > **在那行代码上长得一模一样** —— 而 `|| "—"` 的兜底**不会触发**,
 * > 因为对象是 truthy。
 * 这一页从没被冒烟打过(名单 21 个全是一级页),所以它一直在那儿。 */
function _策略文(p) {
  if (!p) return "—";
  if (typeof p === "string") return esc(p);
  const 谁 = p["谁批"] || p.approver || "";
  const 为 = p["为什么"] || p.reason || "";
  if (!谁 && !为) return esc(JSON.stringify(p));   // 形状没见过:原样给出,别吞
  return esc(谁 || "—") + (为 ? ` <span class="k">${esc(为)}</span>` : "");
}

/* 身份:开发模式从请求头来(生产要接 OIDC) */
const 人们 = [
  ["U001", "U001 管理员"], ["U002", "U002 编辑"], ["U003", "U003 查看者"],
  ["U004", "U004 标注+敏感授权"], ["U005", "U005 只在 B 项目"],
];
let 我 = localStorage.getItem("aimc.user") || "U002";
let 项目 = localStorage.getItem("aimc.proj") || "";
let 环境 = "development";
let 能力 = [];          // 当前身份在当前项目有哪些能力(服务端给的)
let 我的角色 = "";      // ⚠️ **只用来决定「摆不摆按钮 + 说不说为什么」**。
                        // 规格 §5.2:「不可把「禁用前端按钮」当后端授权」——
                        // 真拦截在服务端每个请求上,这里错了也只是多一个 403。

/* ── 请求 ─────────────────────────────────────────────────────────
 * 失败一律走错误契约:code / message / advice。
 * **advice 必须显示出来** —— 一个只说「失败了」的提示,和没有提示是一回事。 */
/* 换页序号(10-28):每进一次路由加一。**读数据的请求回来时已经换过页 → 不交回去**(返回一个永远不结束的 Promise),
 * 那一页后面的渲染就不会跑 —— 不然上一页晚到的数据会把新页盖掉(浏览器测试「#/conns → #/studio/chat」撞到过)。
 * 只拦 GET:提交 / 保存这类写的结果照常交回,哪怕人已经走开了 —— 写成功了却不告诉调用方,比盖掉一页糟得多 */
let 换页序 = 0;
async function 请求(path, opt = {}) {
  const h = Object.assign({ "X-Dev-User": 我 }, opt.headers || {});
  if (opt.body) h["content-type"] = "application/json";
  const 读 = !opt.method || String(opt.method).toUpperCase() === "GET", 序 = 换页序;
  const r = await fetch(path, Object.assign({}, opt, { headers: h }));
  if (读 && 序 !== 换页序) return new Promise(() => {});
  let b = null;
  try { b = await r.json(); } catch (e) { b = null; }
  if (!r.ok) {
    const err = new Error((b && b.message) || `HTTP ${r.status}`);
    err.体 = b || {}; err.码 = r.status;
    throw err;
  }
  return b;
}

/* ── 必备状态(§5.4)────────────────────────────────────────────── */
function 状态(kind, 标题, 说明, 动作) {
  const 按 = 动作 ? `<button class="pri" id="st-act">${esc(动作.文)}</button>` : "";
  const html = `<div class="state ${kind === "err" ? "err" : ""}">
    <h3>${esc(标题)}</h3><p>${md(说明)}</p>${按}</div>`;
  // 11-18:原来写 `onclick = 动作.做`,点击事件会被当成第一个参数传进去 —— 页函数第一个参数是页码的那几页
  // (运行记录 / 调用链 / 评测…)重试时请求 `?page=[object MouseEvent]`,后端 422,**重试永远失败且报的是另一个错**
  return { html, 挂: () => { if (动作) $("#st-act").onclick = () => 动作.做(); } };
}
function 错误块(e, 重试) {
  const b = e.体 || {};
  // **接口失败要保留已有数据并标明最后更新时间**(§5.4)—— 这里没有已有数据,
  // 所以至少把「怎么继续」显示出来:advice 是服务端明确给的下一步
  return 状态("err", `${b.code || "出错了"} · ${e.message}`,
    (b.advice ? `**下一步:**${b.advice}` : "服务端没给建议 —— 这本身是个契约问题") +
    (b.retryable ? "\n\n(服务端说这个错**可以重试**)" : "") +
    (b.trace_id ? `\n\n请求号 \`${b.trace_id}\`` : ""),
    重试 ? { 文: "重试", 做: 重试 } : null);
}

/* ── 侧栏(§4 的信息架构)─────────────────────────────────────────
 * 还没实现的入口**保留但标「未实现」**,不藏起来 ——
 * 规格 §3:「不能因为没有 GPU,就从需求中删除微调模块」。 */
// 10-28 照 Dify 改(用户 10-27 拍第 8 条「导航一次改完,旧路径自动跳到新位置」;适配分析 5.5):
// 主页 / 工作室(应用 + 工作流 + 智能体)/ 知识库(加资料 + 召回测试)/ 集成(模型 + 工具),
// 再加 Dify 没有、我们保留的几组。旧地址(#/workflows #/agents #/apps #/conns #/tools)在路由里跳到新位置
const 导航 = [
  ["#/workbench", "主页", true],
  ["#/studio", "工作室", true],
  ["#/prompts", "Prompt 管理", true, true],
  ["#/glossaries", "术语配置", true, true],
  ["#/kb", "知识库", true],
  ["#/uploads", "加资料", true, true],
  ["#/retrieval", "召回测试", true, true],
  ["#/integrations", "集成", true],
  // 11-18:工具选择策略(selection_api.py 那套接口此前前端零引用)。挂在「集成」底下 —— 它配的是「Agent 怎么从工具目录里挑工具」,
  // 和「集成 → 工具」是同一批对象;⚠️ 后端明说**还没有任何东西在消费它**,页面顶上原样显示那句话
  ["#/selection", "工具选择策略", true, true],
  // 11-24 用户拍(体检「AI 治理分两个后台」):数据后台 8760 里管 AI 的三页收到这里来 —— 调 AI 的人不用在两个后台之间跳,
  // 门店员工也不再在 8760 看到和自己无关的页。页面本体仍由 8760 提供(嵌进来;同一个登录),8760 的侧栏不再列它们
  ["grp", "澜绣 AI 治理"],
  ["#/lanxiu-skills", "Skill 管理", true, true],
  ["#/lanxiu-mcp", "MCP 服务与工具", true, true],
  ["#/lanxiu-kb-issues", "知识问题", true, true],
  // 11-08 用户拍:「查询理解」(Query Understanding)只是个分组、没有自己的页面;下属实体识别 / 查询路由 / 意图识别,各自列表-详情-配置
  ["grp", "查询理解"],
  ["#/entities", "实体识别", true, true],
  ["#/routes", "查询路由", true, true],
  ["#/intents", "意图识别", true, true],
  ["grp", "待办与定时"],
  ["#/human", "人工待办", true, true],
  ["#/schedules", "定时", true, true],
  ["#/chat-tasks", "员工定时", true, true],
  ["grp", "日志与监测"],
  ["#/runs", "运行记录", true, true],
  ["#/opinions", "意见受理", true, true],
  ["#/issues", "问题单", true, true],
  ["#/knowledge-revisions", "知识修订", true, true],
  ["#/capabilities", "能力档案", true, true],
  ["#/capability-board", "改进看板", true, true],
  ["#/acceptance", "上线验收", true, true],
  ["#/monitoring", "监测", true, true],
  ["#/alerts", "告警", true, true],
  ["#/traces", "调用链", true, true],
  ["#/annotations", "标注回复", true, true],
  ["#/outputs", "产出监督", true, true],
  // 11-24 包二「做了要像做了」第一件:定时日报等「Markdown 导出」存下来的文件,此前只能从某次运行详情里点到 —— 不知道运行号就找不到
  ["#/documents", "报告与文件", true, true],
  ["#/health", "智能体健康", true, true],
  ["#/usage", "用量与成本", true, true],
  ["grp", "评测与训练"],
  ["#/evals", "评测中心", true, true],
  ["#/compare", "实验对比", true, true],
  ["#/tryout", "单条试跑", true, true],
  ["#/datasets", "数据集", true, true],
  ["#/training", "训练任务", true, true],
  ["#/artifacts", "模型产物", true, true],
  ["grp", "设置"],
  ["#/knobs", "澜绣旋钮与方案", true, true],
  ["#/members", "成员与权限", true, true],
  ["#/audit", "审计记录", true, true],
];
/* 工作室、集成的页签(照 Dify:工作室按应用类型分、集成分模型供应商 / 工具)。
 * 没接上的类型**留着入口、写明为什么**,不藏(侧栏同一条规矩) */
// 10-28 工作室做成卡片(二期第 2 项):页签照 Dify 的筛选 —— 全部 / 工作流 / 对话流 / 聊天助手 / Agent / 文本生成;
// 「应用与发布」不是一种应用类型(它答的是「哪一版在给用户跑」),放在最右
const 工作室类型 = [["all", "全部", (pg) => 页_工作室("all", pg)], ["workflow", "工作流", (pg) => 页_工作室("workflow", pg)],
  ["chatflow", "对话流", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["chat", "聊天助手", (pg) => 页_工作室("chat", pg)],
  ["agent", "Agent", (pg) => 页_工作室("agent", pg)],
  ["completion", "文本生成", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["app", "应用与发布", () => 页_应用与发布()]];
// 11-18 体检:工具组 / 工具连接两页原来**只有接口没有页面**(HTTP 请求节点提示「去工具连接登记」而那一页不存在;
// 工具详情说「配套只能在冻结工具组版本时给」而没有任何页面能冻结)。页签参数走 页_分页签 的第二段(#/integrations/groups/{gid} = 组详情)
const 集成类型 = [["models", "模型供应商", () => 页_模型与连接()], ["tools", "工具", () => 页_工具目录()],
  ["groups", "工具组", (gid) => 页_工具组(gid)], ["conns", "工具连接", () => 页_工具连接()]];
const 旧地址跳 = { "#/workflows": "#/studio/workflow", "#/agents": "#/studio/agent", "#/apps": "#/studio/app",
  "#/conns": "#/integrations/models", "#/tools": "#/integrations/tools",
  "#/studio": "#/studio/all", "#/integrations": "#/integrations/models" };
async function 页_分页签(根, 表, 路) {
  const [键, 参] = String(路).split("/");   // #/studio/agent/3 → 第 3 页(页码进地址:后退、刷新都还在那一页)
  const 项 = 表.find((x) => x[0] === 键);
  const 条 = `<div class="subtabs" role="tablist">${表.map(([k, 名, fn, 为什么]) => fn
    ? (k === 键 ? `<a role="tab" href="${根}/${k}" class="on" aria-selected="true">${esc(名)}</a>`
                : `<a role="tab" href="${根}/${k}" aria-selected="false">${esc(名)}</a>`)
    : `<a role="tab" class="todo" title="${esc(为什么 || "")}" aria-disabled="true">${esc(名)}</a>`).join("")}</div>`;
  $("#subnav").innerHTML = 条; $("#subnav").hidden = false;
  if (!项 || !项[2]) { $("#main").innerHTML = 状态("", "这一类还没接上", (项 && 项[3]) || "换一个页签看看").html; return; }
  return await 项[2](参);
}
function 画侧栏() {
  const cur = location.hash || "#/workbench";
  $("#side").innerHTML = 导航.map((x) => {
    if (x[0] === "grp") return `<div class="grp">${esc(x[1])}</div>`;
    const [href, 名, 做了, 子] = x;
    const cls = [做了 ? "" : "todo", 子 ? "sub" : "", href === cur || cur.startsWith(href + "/") ? "on" : ""]
      .filter(Boolean).join(" ");
    return 做了 ? `<a href="${href}" class="${cls}">${esc(名)}</a>`
                : `<a class="${cls}" title="规格里有这一页,但还没实现 —— 保留入口是有意的">${esc(名)}</a>`;
  }).join("");
}

/* ── 顶栏 ─────────────────────────────────────────────────────── */
async function 画顶栏() {
  $("#who").innerHTML = 人们.map(([v, t]) =>
    `<option value="${v}"${v === 我 ? " selected" : ""}>${esc(t)}</option>`).join("");
  $("#who").onchange = (e) => {
    我 = e.target.value; localStorage.setItem("aimc.user", 我);
    // **切身份要重新校验权限,不能沿用**(§4 对切项目的要求,同理)
    项目 = ""; localStorage.removeItem("aimc.proj"); 起();
  };
  const h = await 请求("/api/healthz").catch(() => null);
  if (h) {
    环境 = h.env;
    // 顶栏的环境标签**只在生产环境显示**(红框加文字,§4 —— 那是防止在生产上误操作的提醒)。
    // ⚠️ 2026-09-29 用户要求去掉那条占满一行的演示黄条,当时把「演示」标记挪进了这个标签;
    // 10-25 用户又说「development · 演示的标签也不要」—— 开发 / 演示环境下顶栏什么都不挂。
    // **接口里的演示标记一个字没动**(`/api/healthz` 的 `演示模式` / `演示说明`,test_api_flow 验它),
    // 只是界面上不再显示。
    const 生产 = h.env === "production";
    $("#env").hidden = !生产;
    $("#env").textContent = 生产 ? h.env : "";
    $("#env").className = "envtag" + (生产 ? " prod" : "");
    if (h.演示模式) document.body.classList.add("demo");
  }
  let ps = [];
  try { ps = (await 请求("/api/v1/projects")).items || []; }
  catch (e) { $("#proj").innerHTML = `<option>取不到项目</option>`; return false; }
  if (!ps.length) {
    $("#proj").innerHTML = `<option>没有有权访问的项目</option>`;
    $("#main").innerHTML = 状态("", "没有你能访问的项目",
      "全局搜索和列表**只返回有权访问的对象**。要访问请让管理员在「成员与权限」里加你。").html;
    return false;
  }
  // 没记住项目(或记住的已不可见)时**优先澜绣云裳**,看不到它才退回列表第一个(用户 11-18 拍)。
  // 原来直接取第一个 = 演示项目 A(假向量、只有 9 月拍板),用户在那儿做召回测试以为召回坏了。
  // 人手动切过的照旧记住;演示项目留着(集成测试按名字找它)。
  const 首选 = "project_lanxiu";
  if (!ps.some((p) => p.id === 项目)) 项目 = (ps.find((p) => p.id === 首选) || ps[0]).id;
  localStorage.setItem("aimc.proj", 项目);
  $("#proj").innerHTML = ps.map((p) =>
    `<option value="${p.id}"${p.id === 项目 ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  $("#proj").onchange = (e) => {
    项目 = e.target.value; localStorage.setItem("aimc.proj", 项目);
    // **切项目后清掉旧项目的对象选择**(§4)—— 不能带着上个项目的 ID 过去
    location.hash = "#/workbench"; 路由();
  };
  const me = ps.find((p) => p.id === 项目);
  // 11-18:原来只拿 special_grants —— 那只是专项授权,不是能力;管理员默认有的能力一条都不在里面,
  // 产出监督「打回」对管理员不摆。接口现在给「实际能做的」(按角色 + 专项授权现算),老接口没有时退回专项授权
  能力 = (me && (me["实际能做的"] || me.special_grants)) || [];
  我的角色 = (me && me.role) || "";
  $("#whoami").textContent = `${我} · ${(me && me.role) || "?"}`;
  return true;
}

const P = () => `/api/v1/projects/${encodeURIComponent(项目)}`;

/* ── 工作台(§6)──────────────────────────────────────────────────
 * 每张卡要带**时间范围、分母、环境、数据来源、更新时间**。
 * **质量评分不能用 HTTP 成功率代替;没有评测覆盖显示「尚未评测」,不显示 0 分。** */
async function 页_工作台() {
  const 头 = `<div class="crumb">主页</div>
    <div class="head"><div>
      <h1>工作台</h1>
      <div class="sub">${md(`先知道哪里需要处理。每张卡都写清它**算的是什么范围、分母是什么、数据从哪来** ——
        一个没有分母的比率没法判断它可不可信。`)}</div>
    </div><div class="acts">
      <select id="wb-h" style="height:32px">
        <option value="24">最近 24 小时</option><option value="168">最近 7 天</option>
        <option value="720">最近 30 天</option></select>
      <a href="#/runs"><button>查看运行记录</button></a>
    </div></div>`;
  // ⚠️ 右上**不放全局「一键优化」按钮**(§6 明确点出来)——
  // 那种按钮承诺了一件系统做不到的事
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const 画 = async () => {
    const h = $("#wb-h") ? $("#wb-h").value : 24;
    let d;
    try { d = await 请求(`${P()}/workbench?范围小时=${h}&环境=${encodeURIComponent(环境)}`); }
    catch (e) {
      const s = 错误块(e, 画); $("#main").innerHTML = 头 + s.html; s.挂(); return;
    }
    const 卡 = (c) => {
      const 值 = c.未知
        ? `<div class="n unknown">未知</div>`
        : `<div class="n">${esc(c.值)}</div>`;
      // 「失败任务」>0 要能点过去(11-18):说明里写着「去任务中心看」,而卡上没有任何入口
      const 去看 = c.名 === "失败任务" && !c.未知 && Number(c.值) > 0
        ? `<div class="k"><a href="#/runs">去运行记录看 →</a></div>` : "";
      return `<div class="card kpi">
        <div class="k">${esc(c.名)}</div>${值}
        ${c.说明 ? `<div class="why">${md(c.说明)}</div>` : ""}${去看}
        <div class="meta">
          ${c.分母 ? `分母:${esc(c.分母)}<br>` : ""}
          ${esc(c.时间范围)} · 环境 ${esc(c.环境)}<br>
          来源:${esc(c.数据来源)}<br>更新:${esc(c.更新时间)}
        </div></div>`;
    };
    $("#main").innerHTML = 头
      + `<div class="cards">${(d.卡片 || []).map(卡).join("")}</div>`
      + `<div class="note warn">${md(`**「未知」不是 0。** 费用未知是因为 mock 适配器没有真实计价;
         质量分未知是因为还没有评测覆盖 —— 显示 0 会被读成「质量很差」,而真相是「没测过」。`)}</div>`
      + `<div id="wb-sw"><div class="state">在取开关…</div></div>`;
    $("#wb-h").value = h;
    $("#wb-h").onchange = 画;
    画_开关($("#wb-sw"));
  };
  await 画();
}

/* 开关现状 + 最近 7 天谁改了什么(10-28 用户拍「开关监督」)。
 * 起因:并行会话三个技能被一个默认值弄得没挂上,功能测试全绿、两天没人知道 —— 改了线上行为的设置,变了要有人看得见。
 * 只摆这个后台记着的;「聊天站真按它在跑吗」由 tools/takeover_effect_check.py 真调聊天站代码核对,这里不冒充 */
async function 画_开关(根) {
  let d;
  try { d = await 请求(`${P()}/switches`); }
  catch (e) { 根.innerHTML = `<div class="note">${esc("开关现状没取到:" + e.message)}</div>`; return; }
  const x = d["现状"], 变 = d["最近变动"] || [];
  const 列 = (名, xs, f) => `<div class="card swcard" data-sw="${esc(名)}"><div class="k">${esc(名)}</div>${xs.length
    ? `<ul>${xs.map((i) => `<li>${f(i)}</li>`).join("")}</ul>` : `<div class="k">一个都没有</div>`}</div>`;
  // 接管只列**开着**的:登记了对应技能而关着的(测试项目里有几百条)摆出来会把真开着的那一两条淹掉 —— 关着的只报个数
  const 关着 = x["聊天接管"].filter((i) => !i["开着"]).length;
  根.innerHTML = `<h2>开关 · 改了会换掉线上行为的设置</h2>
    <div class="cards">
      ${列("聊天接管", x["聊天接管"].filter((i) => i["开着"]), (i) => `<a href="#/workflow/${encodeURIComponent(i.workflow_id)}/概览">${esc(i["工作流"])}</a>
        · ${esc(i["技能中文"] || i["技能"])} ${i["开着"] ? '<span class="pill ok">开着</span>' : '<span class="pill">关着</span>'}`)}
      ${列("生产版本", x["生产版本"], (i) => `<a href="#/workflow/${encodeURIComponent(i.workflow_id)}/版本与发布">${esc(i["工作流"])}</a> · <b>${esc(i["版本"])}</b>`)}
      ${列("开着的定时", x["开着的定时"], (i) => `<a href="#/workflow/${encodeURIComponent(i.workflow_id)}/设置">${esc(i["工作流"])}</a> · ${esc(i["规则"])}`)}
    </div>
    ${关着 ? `<div class="k">另有 ${关着} 条工作流登记了对应技能、接管关着(交给 harness)</div>` : ""}
    <h3>最近 ${d["天数"]} 天谁改了什么(${变.length} 次)</h3>
    ${变.length ? `<table class="swlog"><thead><tr><th>时间</th><th>谁</th><th>开关</th><th>哪一条</th><th>从</th><th>到</th><th>理由</th></tr></thead><tbody>
      ${变.slice(0, 30).map((v) => `<tr><td class="k">${时间(v["时间"])}</td><td>${esc(v["谁"])}</td><td>${esc(v["开关"])}</td>
        <td>${esc(v["对象"])}</td><td>${esc(v["从"])}</td><td><b>${esc(v["到"])}</b></td><td class="k">${esc(v["理由"] || "")}</td></tr>`).join("")}
      </tbody></table>${变.length > 30 ? `<div class="k">只列最近 30 次,全部在「审计记录」里</div>` : ""}`
      : `<div class="k">这几天没人动过这些开关。</div>`}
    <div class="note">${md(`**这里是后台记着的状态**;聊天站是不是真按它在跑,另由核对脚本真调聊天站的代码去看(\`tools/takeover_effect_check.py\`)。`)}
      <br>也会改线上行为、但开关不在这个后台的:${(d["别处的开关"] || []).map((o) =>
        `<b>${esc(o["开关"])}</b>(${esc(o["在哪"])})`).join("、")}。</div>`;
}

/* ── Prompt 列表(§8.1)─────────────────────────────────────────── */
async function 页_prompt列表() {
  const 头 = `<div class="crumb">工作室 / Prompt 管理</div>
    <div class="head"><div>
      <h1>Prompt 管理</h1>
      <div class="sub">${md(`「最新保存版本」和「生产引用版本」**并排显示** ——
        避免以为保存就上线了。生产用哪一版由**发布清单 + 环境指针**决定,不是「最新的那个」。`)}</div>
    </div><div class="acts">
      <button id="np" class="pri">新建 Prompt</button>
    </div></div>
    <div class="filters">
      <input id="f-q" placeholder="搜名称或用途…">
      <select id="f-prod"><option value="">生产引用:全部</option>
        <option value="1">只看已上线</option><option value="0">只看未上线</option></select>
      <div class="right"><button id="f-reset">重置</button></div>
    </div>
    <div id="tbl"><div class="state">加载中…</div></div>`;
  $("#main").innerHTML = 头;
  let 游标 = null;                       // 11-18 接上翻页:服务端一直给 next_cursor,按钮原来点了只提示「还没接」
  const 画 = async () => {
    const q = $("#f-q").value.trim(), pr = $("#f-prod").value;
    let u = `${P()}/prompts?limit=20`;
    if (游标) u += `&cursor=${encodeURIComponent(游标)}`;
    if (q) u += `&q=${encodeURIComponent(q)}`;
    if (pr !== "") u += `&被生产引用=${pr === "1" ? "true" : "false"}`;
    let d;
    try { d = await 请求(u); }
    catch (e) { const s = 错误块(e, 画); $("#tbl").innerHTML = s.html; s.挂(); return; }
    const rs = d.items || [];
    if (!rs.length) {
      // **筛选无结果给重置,空数据给本页入口**(§5.4)—— 这两种是不同的空
      const 有筛选 = q || pr !== "";
      const s = 有筛选
        ? 状态("", "这个筛选下没有 Prompt", "换个词,或者把筛选清掉。",
               { 文: "重置筛选", 做: () => { $("#f-q").value = ""; $("#f-prod").value = ""; 画(); } })
        : 状态("", "这个项目还没有 Prompt",
               "Prompt 是把任务规范、输入和输出要求配置成**可复用版本**的地方。",
               { 文: "新建 Prompt", 做: 新建 });
      $("#tbl").innerHTML = s.html; s.挂(); return;
    }
    $("#tbl").innerHTML = `<table><thead><tr>
        <th>标识</th><th>用途(管哪部分)</th><th>标签</th>
        <th>最新保存版本</th><th>生产引用版本</th>
        <th>最近评测</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td>
          <td>${(() => {
            // 从 prompts.py 导入的规矩,用途第一行是「哪几个助手｜这条讲什么」(导入脚本现拼),
            // 只取第一行、放宽到 70 字 —— 原来截 40 字常把「讲什么」那半截掉;全文悬停看
            const 全 = r.用途 || "", 首 = 全.split("\n")[0];
            return 全 ? `<span title="${esc(全)}">${esc(首.length > 70 ? 首.slice(0, 70) + "…" : 首)}</span>`
                      : '<span style="color:var(--faint)">—</span>';
          })()}</td>
          <td>${(r.标签 || []).map((t) => `<span class="pill">${esc(t)}</span>`).join(" ") || "—"}</td>
          <td>${r.最新版本 != null ? `v${r.最新版本}` : '<span class="pill none">还没存过版本</span>'}</td>
          <td>${r.生产版本 != null ? `<span class="pill ok">v${r.生产版本}</span>`
                                 : `<span class="pill none">未上线</span>`}</td>
          <td>${r.评测状态 === "尚未评测" ? `<span class="pill none">尚未评测</span>`
                                       : `<span class="pill">${esc(r.评测状态)}</span>`}</td>
          <td class="num">${esc(String(r.updated_at || "").slice(0, 16))}</td>
          <td><a href="#/prompt/${encodeURIComponent(r.id)}">查看 / 调试</a></td></tr>`).join("")}
      </tbody></table>
      <div class="pager">
        <span>共 ${d.total == null ? "未知条(没做全量计数 —— <b>不编一个数</b>)" : d.total + " 条"}</span>
        <div class="right">${游标 ? `<button id="first">回第一页</button> ` : ""}${d.next_cursor ? `<button id="more">下一页</button>` : ""}</div>
      </div>`;
    if (d.next_cursor) $("#more").onclick = () => { 游标 = d.next_cursor; 画(); };
    if (游标 && $("#first")) $("#first").onclick = () => { 游标 = null; 画(); };
  };
  const 新建 = async () => {
    const key = await 问一句("新建 Prompt", "给它一个稳定标识:项目内唯一,建好之后不随意改。", { 输入: "比如 customer_needs_extract", 确定: "新建", 必填: true });
    if (!key) return;
    try {
      await 请求(`${P()}/prompts`, {
        method: "POST",
        body: JSON.stringify({ key, 用途: "", 标签: [], system: "", user: "" }),
      });
      画();
    } catch (e) {
      报错(e);
    }
  };
  $("#np").onclick = 新建;
  $("#f-q").oninput = (() => { let t; return () => { clearTimeout(t); t = setTimeout(() => { 游标 = null; 画(); }, 300); }; })();
  $("#f-prod").onchange = () => { 游标 = null; 画(); };
  $("#f-reset").onclick = () => { $("#f-q").value = ""; $("#f-prod").value = ""; 游标 = null; 画(); };
  await 画();
}

/* 模型连接下拉(Prompt 详情页 + 单条试跑共用,11-18):只列这个项目里**启用的生成连接**;恰好一条就默认选中
 * (服务端没点名时也会选它,两边一致);零条明说「运行会失败」而不是摆一个空下拉;mock 适配器的连接标出来 —— 它返回的是编出来的回答。 */
async function 画模型连接(容器, 选id) {
  const 盒 = $(容器); if (!盒) return;
  let d;
  try { d = await 请求(`${P()}/model-connections`); }
  catch (e) {
    盒.innerHTML = `<div class="note warn">读不到模型连接:${esc(e.message)} —— 不传连接的话,服务端会用项目里唯一那条;没有就会失败</div>`;
    return;
  }
  const 们 = (d["连接"] || []).filter((c) => c["用途"] === "generate" && c["状态"] === "active");
  if (!们.length) {
    盒.innerHTML = `<div class="note warn">${md("这个项目**没有启用的生成连接** —— 运行测试会失败(NO_MODEL_CONNECTION)。去「集成 → 模型供应商」建一条并探测过。")}</div>`;
    return;
  }
  const 是mock = (c) => /mock/i.test(String(c["适配器"] || ""));
  盒.innerHTML = `<label class="f">这次用哪条模型连接</label>
    <select id="${选id}">${们.map((c) => `<option value="${esc(c.id)}">${esc(c["适配器"])} · ${esc(c.id)}${是mock(c) ? "(mock,答案是编的)" : ""}</option>`).join("")}</select>
    <div class="k">${们.length === 1 ? "项目里只有这一条启用的生成连接,默认就用它" : `有 ${们.length} 条启用的,选一条 —— 服务端不替你挑`}</div>
    ${们.some(是mock) ? `<div class="note warn">${md("mock 适配器返回的是**编出来的回答**,不许计入真实评测或发布;跑不跑 mock 由服务的 MODEL_ADAPTER 决定")}</div>` : ""}`;
}
const 选中的连接 = (选id) => { const s = $("#" + 选id); return s && s.value ? s.value : undefined; };

/* 等一个任务到终态(11-18):原来页面派完任务**只查一次**,看到的永远是「排队中」—— 用户报「每次都排队、不给答案」。
 * 两秒一问,最多两分钟;`写状态` 每一轮回一次,让人看见它真在等而不是卡住。超时就把最后一次看到的交回去,**标明没结束**。
 * 人换了页,`请求` 对 GET 返回一个永不结束的 Promise,这个循环就自然停了,不会往新页面上写。 */
async function 等任务(job, 写状态, 最多毫秒 = 120000) {
  const 起 = Date.now();
  for (;;) {
    const j = await 请求(`${P()}/jobs/${encodeURIComponent(job)}`);
    if (j["是终态吗"] || Date.now() - 起 > 最多毫秒) return j;
    if (写状态) 写状态(j, Math.round((Date.now() - 起) / 1000));
    await new Promise((r) => setTimeout(r, 2000));
  }
}

/* 一次运行的结果卡(Prompt 详情页 + 单条试跑共用)。失败要把**为什么**摆出来 —— 接口 11-18 起带 error_code / error_detail,
 * 原来页面拿到「失败」两个字就没了。 */
function 运行结果html(j) {
  const 果 = j["结果"] || {};
  const 段 = 果["阶段"] || [];
  const 用 = 果["用量"] || [];
  const 败 = j.status === "失败" || !!j["error_code"];
  const 细 = j["error_detail"] || {};
  const 原因 = 败 ? `<div class="note warn">${md("**失败:" + (j["error_code"] || "没给错码") + "** —— "
      + (typeof 细 === "object" && 细["为什么"] ? 细["为什么"] : JSON.stringify(细)))}</div>` : "";
  return `
      <div style="font-weight:600;margin-bottom:6px">实际输出
        <span class="vtag">· ${esc(j.status)}${j["是终态吗"] ? "(终态)" : "(<b>还没结束</b>)"}</span></div>
      ${原因}
      ${段.map((s) => `
        <div class="vtag">阶段:${esc(s["阶段"])}</div>
        <pre class="io" data-raw="原文">${esc(typeof s["输出"] === "string" ? s["输出"]
                                : (s["输出"] && s["输出"].text) || JSON.stringify(s["输出"], null, 2))}</pre>
        <details><summary>应用实际发送给模型的内容${果["看得到原文"] ? "" : "(已脱敏)"}</summary>
          <pre class="io" data-raw="原文">${esc(JSON.stringify(s["实际发送"], null, 2))}</pre>
          ${果["看得到原文"] ? "" : `<div class="note">${md(`**默认脱敏。** 看原文要
            「查看敏感输入/独立测试答案」专项权限 —— 换成 U004 能看到差别。`)}</div>`}
        </details>`).join("")}
      <div class="two" style="margin-top:8px">
        <div><div class="vtag">用量</div>
          ${用.map((u) => `<div style="font-size:12.5px">
            ${esc(u.resource || "")} ${esc(u.quantity)} ${esc(u.unit || "")} ·
            费用 ${u.amount_known ? esc(u.amount) : "<b>未知</b>"} (来源 ${esc(u.source || "")})
          </div>`).join("") || "—"}
          <div class="note">${md(果["费用说明"] || "")}</div></div>
        <div><div class="vtag">事件</div>
          ${(j["事件"] || []).map((e) => `<div style="font-size:12.5px">
            #${e.seq} ${esc(e.kind)} ${esc(String(e.at || "").slice(0, 19))}</div>`).join("")}
          <div class="note">Trace <code>${esc(果["trace_id"] || "—")}</code></div></div>
      </div>
      <div class="note">${md(`跑完可以「加入问题集」「保存为评测样本」—— 新样本**先进待审核**,
        避免把错误答案当成真值。(这两个按钮还没实现)`)}</div>`;
}

/* ── Prompt 详情(§8.2 / §8.3 / §8.4 / §8.5)──────────────────────
 * 左约 60%:任务与指令 / 消息模板 / 变量 / 输出要求
 * 右约 40%:模型与参数 / 测试输入 / 运行测试 / 实际输出
 * 底部固定区:左侧校验/保存状态,右侧 取消 / 保存草稿 / 保存为新版本
 *
 * ⚠️ **编辑内容和测试输入独立保存,运行结果不覆盖模板**(§8.2 最后一句)。 */
async function 页_prompt详情(pid) {
  $("#main").innerHTML = `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/prompts/${encodeURIComponent(pid)}`); }
  catch (e) {
    const s = 错误块(e, () => 页_prompt详情(pid)); $("#main").innerHTML = s.html; s.挂(); return;
  }
  const 草 = d.草稿, m = 草.messages || {};
  // 11-18:变量表改成可编辑,所以这里拿的是**自己的一份拷贝**(页面上改的是它,保存时整份发回去)。
  // ⚠️ 从 prompts.py 导入的那 20 条,variable_schema 存的是 `{}` 不是 `[]` —— 不归一化成数组,下面 .map 当场崩;
  // 每个变量对象还可能带页面不认识的字段(比如「长度上限」),拷贝整个对象、只改编辑过的键,别把它们丢了
  const 变量 = (Array.isArray(草.variable_schema) ? 草.variable_schema : []).map((v) => Object.assign({}, v));
  let rev = 草.revision;                 // 乐观锁:每次保存后要更新它
  let 脏 = false;                        // 未保存标记(§5.4「未保存」状态)
  const 出要 = 草.output_schema || {};
  const 类型们 = ["string", "number", "boolean", "array", "object"];
  const 来源们 = ["用户输入", "上一步结果", "检索上下文", "受控系统字段"];   // 和下面说明文字里那四种是同一份
  // 默认值可能不是字串(number / object);显示用 JSON 文本,**别让 esc 吃到对象**(会显示成 [object Object])
  const 默认文 = (v) => v.默认值 == null ? "" : (typeof v.默认值 === "string" ? v.默认值 : JSON.stringify(v.默认值));

  const 版本行 = (d.版本历史 || []).map((v) => `
    <tr><td class="num">v${v.version_no}</td>
      <td class="num">${esc(String(v.content_hash || "").slice(0, 12))}</td>
      <td>${esc(v.变更说明 || "—")}</td>
      <td class="num">${esc(String(v.created_at || "").slice(0, 16))}</td>
      <td>${esc(v.created_by || "")}</td></tr>`).join("");

  $("#main").innerHTML = `
    <div class="crumb">工作室 / <a href="#/prompts">Prompt 管理</a> / ${esc(草.key)}</div>
    <div class="head"><div>
      <h1>${esc(草.key)}</h1>
      <div class="sub">草稿 revision <code id="rev">${rev}</code>
        ${(d.版本历史 || []).length ? ` · 已有 ${d.版本历史.length} 个正式版本`
                                    : " · <b>还没存过正式版本</b>"}
        <br>${md("**保存草稿不会影响任何已保存版本,也不影响生产。**")}</div>
    </div></div>

    <div class="split">
      <div class="card">
        <label class="f">用途 / 面向谁 / 完成标准</label>
        <textarea class="t" id="e-用途" placeholder="比如:把文章整理成结论、依据、待核实事项">${esc(m.用途 || "")}</textarea>

        <label class="f">系统指令</label>
        <textarea class="t mono" data-raw="原文" id="e-system" rows="6">${esc(m.system || "")}</textarea>

        <label class="f">用户模板　<span style="color:var(--ink3)">变量写成 <code>{{名称}}</code></span></label>
        <textarea class="t mono" data-raw="原文" id="e-user" rows="6">${esc(m.user || "")}</textarea>

        <label class="f">输入变量　<span style="color:var(--ink3)">名称要和模板里的 <code>{{名称}}</code> 一一对上,改完点「保存草稿」才算</span></label>
        <div id="vars"></div>
        <div class="note">${md(`**定义变量不等于已经取得数据。** 每个变量都要说清来源
          (用户输入 / 上一步结果 / 检索上下文 / 受控系统字段)—— 来源没绑上,
          它在运行时就是空的。`)}</div>

        <label class="f">输出要求　<span style="color:var(--ink3)">JSON 对象;不合法不会发请求</span></label>
        <textarea class="t mono" id="e-out" data-raw="原文" rows="8">${esc(JSON.stringify(出要, null, 2))}</textarea>

        <label class="f">变更说明 <span class="req">*</span>
          <span style="color:var(--ink3)">保存正式版本必填 —— 它是以后唯一能想起「为什么改」的地方</span></label>
        <textarea class="t" id="e-why" rows="2">${esc(m.变更说明 || "")}</textarea>

        <div class="footbar">
          <span class="msg" id="fb"></span>
          <button id="b-cancel">取消</button>
          <button id="b-draft">保存草稿</button>
          <button id="b-ver" class="pri">保存为新版本</button>
        </div>
      </div>

      <div>
        <div class="card">
          <div style="font-weight:600;margin-bottom:6px">模型与参数</div>
          <div id="mconn"><div class="k">读模型连接…</div></div>
          <label class="f">测试输入　<span style="color:var(--ink3)">和模板独立保存,运行结果不会覆盖模板</span></label>
          <div id="testvars"></div>
          <div style="margin-top:10px">
            <button class="pri" id="b-run">运行测试</button>
            <span class="msg" id="runmsg" style="font-size:12.5px;color:var(--ink2)"></span>
          </div>
          <div class="note">${md(`期望答案放在**独立的评分区域**,不会自动传给被测模型 ——
            否则等于把答案给了考生。`)}</div>
        </div>
        <div class="card" id="runout" style="display:none"></div>
      </div>
    </div>

    <div class="card">
      <div style="font-weight:600;margin-bottom:8px">版本历史</div>
      ${版本行 ? `<table><thead><tr><th>版本</th><th>内容哈希</th><th>变更说明</th>
          <th>时间</th><th>谁</th></tr></thead><tbody>${版本行}</tbody></table>`
        : `<div class="state" style="padding:20px">还没有正式版本 —— 左边补齐之后点「保存为新版本」。</div>`}
    </div>`;

  /* 变量表(左,可编辑)+ 测试输入(右)—— 同一份变量定义,两个用途。
   * 11-18 体检:原来左边是只读表,而后端 PATCH 早就收「变量」—— 模板里写了 {{x}} 没地方定义,
   * 「保存为新版本」永远灰,页面还提示「先把来源配上」而无处可配。
   * 左右分开画:每敲一个字只重画右边(重画左边会把焦点打掉);加 / 删一行才重画左边。 */
  const 选项 = (们, 当前, 空文) => {
    const 列 = 们.slice();
    if (当前 && !列.includes(当前)) 列.push(当前);   // 库里已有、但不在这几种里的值:照样列出来,别静默改掉
    return (空文 ? `<option value=""${当前 ? "" : " selected"}>${esc(空文)}</option>` : "")
      + 列.map((x) => `<option value="${esc(x)}"${x === 当前 ? " selected" : ""}>${esc(x)}</option>`).join("");
  };
  const 画变量表 = () => {
    $("#vars").innerHTML = (变量.length ? `<table><thead><tr>
        <th>名称</th><th>说明</th><th>类型</th><th>来源</th><th>必填</th><th>默认值</th><th></th>
      </tr></thead><tbody>${变量.map((v, i) => `<tr>
        <td><input class="t mono" data-raw="原文" data-vi="${i}" data-vk="名称" placeholder="article" value="${esc(v.名称 || "")}"></td>
        <td><input class="t" data-raw="原文" data-vi="${i}" data-vk="说明" value="${esc(v.说明 || "")}"></td>
        <td><select class="t" data-vi="${i}" data-vk="类型">${选项(类型们, v.类型 || "string")}</select></td>
        <td><select class="t" data-vi="${i}" data-vk="来源">${选项(来源们, v.来源 || "", "(没配来源)")}</select></td>
        <td style="text-align:center"><input type="checkbox" data-vi="${i}" data-vk="必填"${v.必填 ? " checked" : ""}></td>
        <td><input class="t mono" data-raw="原文" data-vi="${i}" data-vk="默认值" value="${esc(默认文(v))}"></td>
        <td><button data-vdel="${i}" title="删掉这个变量">删</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="note">${md(`还没定义变量。模板里写了 \`{{x}}\` 但没定义的话,
          「保存为新版本」会被拦住 —— 那不是刁难:**没定义来源的变量在运行时是空的**。`)}</div>`)
      + `<div style="margin-top:6px"><button id="b-addvar">加一个变量</button></div>`;
  };
  const 画测试输入 = () => {
    // 重画会清掉右边已经敲进去的测试值 —— 先按行号存下来,画完放回去(改名称不该把人刚敲的内容吃掉)
    const 旧 = {};
    document.querySelectorAll("[data-tv]").forEach((t) => { if (t.dataset.ti != null) 旧[t.dataset.ti] = t.value; });
    $("#testvars").innerHTML = 变量.length ? 变量.map((v, i) => `
      <label class="f">${esc(v.名称 || "(还没起名)")}${v.必填 ? ' <span class="req">*</span>' : ""}
        <span style="color:var(--ink3)">${esc(v.说明 || "")}</span></label>
      <textarea class="t" data-tv="${esc(v.名称 || "")}" data-ti="${i}" rows="${v.名称 === "article" ? 4 : 1}"
        placeholder="${esc(默认文(v))}"></textarea>`).join("")
      : `<div class="note">这条 Prompt 没有变量 —— 直接点运行测试。</div>`;
    document.querySelectorAll("[data-tv]").forEach((t) => { if (旧[t.dataset.ti] != null) t.value = 旧[t.dataset.ti]; });
  };
  const 画变量 = () => { 画变量表(); 画测试输入(); };
  画变量();
  // 这次运行用哪条模型连接(11-18):原来这儿是一句写死的「当前是 mock 适配器」,而真跑模式下快照里没绑连接,
  // 每一次都 NO_MODEL_CONNECTION;现在列出项目里启用的生成连接,唯一那条默认选中(和服务端没点名时的选法一致)
  await 画模型连接("#mconn", "m-conn");

  const 标脏 = () => { 脏 = true; $("#fb").textContent = "有未保存的改动"; $("#fb").className = "msg"; };
  ["#e-用途", "#e-system", "#e-user", "#e-why", "#e-out"].forEach((s) => { $(s).oninput = 标脏; });

  // 默认值那一格敲的是文本,按「类型」转回去:number 转数、boolean 转真假、array / object 按 JSON 解;
  // 转不动就**原样存字串**(不吞、不报错 —— 它只是默认值,运行时按 string 用也不会崩)
  const 按类型 = (类型, 文) => {
    if (文 === "") return undefined;
    if (类型 === "number") { const n = Number(文); return Number.isFinite(n) ? n : 文; }
    if (类型 === "boolean") return 文 === "true" ? true : (文 === "false" ? false : 文);
    if (类型 === "array" || 类型 === "object") {
      try { const j = JSON.parse(文); if (Array.isArray(j) === (类型 === "array") && typeof j === "object" && j) return j; } catch (e) { /* 不是 JSON,原样存 */ }
    }
    return 文;
  };
  // 事件挂在 #vars 容器上(委托):行是重画出来的,逐个绑会在每次重画后丢掉
  const 改变量 = (e) => {
    const t = e.target, i = Number(t.dataset.vi), k = t.dataset.vk;
    if (!k || !变量[i]) return;
    if (k === "必填") 变量[i].必填 = !!t.checked;
    else if (k === "默认值") { const 值 = 按类型(变量[i].类型 || "string", t.value); if (值 === undefined) delete 变量[i].默认值; else 变量[i].默认值 = 值; }
    else 变量[i][k] = t.value;
    标脏();
    if (k !== "类型" && k !== "来源") 画测试输入();   // 右边只用到名称 / 说明 / 必填 / 默认值
  };
  $("#vars").oninput = 改变量;
  $("#vars").onchange = 改变量;    // select / checkbox 在有些浏览器只发 change
  $("#vars").onclick = (e) => {
    const t = e.target;
    if (t.id === "b-addvar") {
      变量.push({ 名称: "", 说明: "", 类型: "string", 来源: "", 必填: false });
      标脏(); 画变量();
      const 新 = document.querySelector(`#vars [data-vi="${变量.length - 1}"][data-vk="名称"]`);
      if (新) 新.focus();
    } else if (t.dataset.vdel != null) {
      变量.splice(Number(t.dataset.vdel), 1);
      标脏(); 画变量();
    }
  };
  // 保存前的本地校验 —— 只拦服务端那条「模板里用了没定义的变量」**查不出来**的两种坏法:空名、重名
  // (名字和模板对不对得上,交给服务端 _能存版本 判,页面不再判一遍 —— 两份规矩会不一致)
  const 查变量 = () => {
    const 见 = new Set();
    for (let i = 0; i < 变量.length; i++) {
      const n = String(变量[i].名称 || "").trim();
      if (!n) return `第 ${i + 1} 个变量**还没起名** —— 要么填上,要么删掉这一行`;
      if (见.has(n)) return `变量名 **${n}** 重复了 —— 同名两行,运行时不知道该用哪一个`;
      见.add(n); 变量[i].名称 = n;
    }
    return "";
  };
  // 输出要求:textarea 里是 JSON 文本;空着算 {}。不是合法 JSON、或不是对象(数组 / 数字),都不发请求
  const 解析输出要求 = () => {
    const 文 = $("#e-out").value.trim();
    if (!文) return {};
    let j;
    try { j = JSON.parse(文); } catch (e) { throw new Error(`输出要求不是合法 JSON:${e.message}`); }
    if (!j || typeof j !== "object" || Array.isArray(j)) throw new Error("输出要求要是一个 JSON **对象**(花括号包起来的键值对),不能是数组或单个值");
    return j;
  };

  const 校验提示 = (判) => {
    const ok = 判 && 判.行;
    $("#b-ver").disabled = !ok;
    // ⚠️ **不能只显示「不能保存」** —— 一个只说不行的按钮和一个坏掉的按钮
    // 对使用的人是一样的。所以把**逐条原因**摆出来。
    $("#fb").innerHTML = ok
      ? "静态校验通过,可以保存为新版本"
      : `<b>还不能存正式版本:</b>${((判 && 判.原因) || []).map((x) => "<br>· " + md(x)).join("")}`;
    $("#fb").className = "msg" + (ok ? "" : " bad");
  };
  校验提示(d.能存版本吗);

  $("#b-cancel").onclick = async () => {
    // **未保存离开时提示**(§5.2)
    if (脏 && !(await 问一句("离开这一页?", "有没保存的改动,离开会丢掉。", { 确定: "丢掉并离开", 取消: "留下" }))) return;
    location.hash = "#/prompts";
  };

  $("#b-draft").onclick = async () => {
    // 先在本地把形状查对,**查不过不发请求** —— 发过去一个坏的 output_schema 会写进库,运行时才炸
    let 输出要求;
    const 变量错 = 查变量();
    try { if (!变量错) 输出要求 = 解析输出要求(); }
    catch (e) { $("#fb").innerHTML = `<b>没保存:</b>${md(e.message)}`; $("#fb").className = "msg bad"; return; }
    if (变量错) { $("#fb").innerHTML = `<b>没保存:</b>${md(变量错)}`; $("#fb").className = "msg bad"; return; }
    $("#b-draft").disabled = true;
    try {
      const r = await 请求(`${P()}/prompts/${encodeURIComponent(pid)}/draft`, {
        method: "PATCH",
        headers: { "If-Match": String(rev) },      // **必填** —— 否则就是「最后写的人赢」
        body: JSON.stringify({
          用途: $("#e-用途").value, system: $("#e-system").value,
          user: $("#e-user").value, 变更说明: $("#e-why").value,
          变量, 输出要求,                           // 11-18 起一起发:后端 PATCH 本来就收这两项,只是前端一直没发
        }),
      });
      rev = r.revision; $("#rev").textContent = rev; 脏 = false;
      校验提示(r.能存版本吗);
      // **保存成功保持编辑位置**(§5.2)—— 不跳走、不重载
    } catch (e) {
      const b = e.体 || {};
      if (e.码 === 409) {
        // **并发冲突**(§5.4):不覆盖,让人先看别人改了什么
        $("#fb").innerHTML = `<b>${esc(b.message || "被别人改过了")}</b><br>${md(b.advice || "")}
          <br><button id="b-reload">刷新看最新的</button>`;
        $("#fb").className = "msg bad";
        $("#b-reload").onclick = () => 页_prompt详情(pid);
      } else {
        $("#fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
        $("#fb").className = "msg bad";
      }
    }
    $("#b-draft").disabled = false;
  };

  $("#b-ver").onclick = async () => {
    if (脏 && !(await 问一句("先保存草稿?", "有没保存的改动。正式版本是从<b>已保存的草稿</b>建的 —— 不先保存,这些改动不会进这一版。", { 确定: "照旧存版本", 取消: "回去先保存" }))) return;
    $("#b-ver").disabled = true;
    try {
      const r = await 请求(`${P()}/prompts/${encodeURIComponent(pid)}/versions`, { method: "POST" });
      $("#fb").innerHTML = `已存为 <b>v${r.version_no}</b>(内容哈希 <code>${esc(r.content_hash.slice(0, 12))}</code>)
        <br>${md(r.note || "")}`;
      $("#fb").className = "msg";
      setTimeout(() => 页_prompt详情(pid), 900);
    } catch (e) {
      const b = e.体 || {};
      $("#fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
      $("#fb").className = "msg bad";
      $("#b-ver").disabled = false;
    }
  };

  $("#b-run").onclick = async () => {
    const 变 = {};
    document.querySelectorAll("[data-tv]").forEach((t) => {
      if (t.value.trim()) 变[t.dataset.tv] = t.value;
    });
    $("#b-run").disabled = true; $("#runmsg").textContent = "跑着…";
    try {
      const r = await 请求(`${P()}/prompt-runs`, {
        method: "POST",
        // **幂等键**:这一次点击一个键 —— 超时重发不会跑第二遍(也不会多花一次钱)
        headers: { "Idempotency-Key": (crypto.randomUUID ? crypto.randomUUID()
                                        : String(Date.now()) + Math.random()) },
        body: JSON.stringify({ prompt_id: pid, 变量: 变, model_connection_id: 选中的连接("m-conn") }),
      });
      $("#runmsg").textContent = `任务 ${r.job_id} · ${r.status}`
        + (r["模型连接"] ? "" : ` · ⚠️ ${r["模型连接说明"] || "没绑模型连接"}`);
      // 原来这里只查一次任务状态就停了 —— 任务刚受理当然是「排队中」,于是页面上永远是排队(11-18 用户报的就是这个)
      const j = await 等任务(r.job_id, (x, 秒) => {
        $("#runmsg").textContent = `任务 ${r.job_id} · ${x.status} · 等了 ${秒} 秒`;
      });
      $("#runout").style.display = "";
      $("#runout").innerHTML = 运行结果html(j);
      $("#runmsg").textContent = `任务 ${r.job_id} · ${j.status}` + (j["是终态吗"] ? "" : " · 两分钟还没结束,去「运行记录」看");
    } catch (e) {
      const b = e.体 || {};
      // 缺变量这类**调用前就被拦住**的错,要指到字段上(§5.3)
      const fe = b.field_errors || {};
      Object.keys(fe).forEach((k) => {
        const el = document.querySelector(`[data-tv="${k}"]`);
        if (el) el.style.borderColor = "var(--fail)";
      });
      $("#runmsg").innerHTML = `<b style="color:var(--fail)">${esc(b.message || e.message)}</b>
        ${b.advice ? "<br>" + md(b.advice) : ""}`;
    }
    $("#b-run").disabled = false;
  };

}

/* ── 术语配置(11-06;用户拍「后台页面这次一起做」)────────────────────────────
 * 和 Prompt 同一个形状:草稿随便改(带 If-Match)、冻结的版本不可变;工作流 / Agent 引用的是冻结版本。
 * **检查(阻断 / 提醒)全在服务端算**(glossaries_api._详情),页面只摆出来,不自己再判一遍 ——
 * 自己判就成了第二份规矩,而两份规矩不一致的表现是「页面说能冻、点了被拒」。
 * 「试一下」打的是 preview 接口,和运行时同一个函数;页面不自己匹配叫法。 */
async function 页_术语列表() {
  const 头 = `<div class="crumb">工作室 / 术语配置</div>
    <div class="head"><div>
      <h1>术语配置</h1>
      <div class="sub">${md(`把店里的叫法统一成一个标准词,写清它是什么意思;指标还要写清**怎么算**(分子 / 分母 / 时间)。
        模型只收到这次对话里**提到的那几条**。改草稿不影响在跑的东西,**冻结成版本、在流程里选这一版**才生效。`)}</div>
    </div><div class="acts">
      <button id="g-new" class="pri">新建术语表</button>
    </div></div>
    <div id="tbl"><div class="state">加载中…</div></div>`;
  $("#main").innerHTML = 头;
  const 新建 = async () => {
    const key = await 问一句("新建术语表", "给它起一个标识:项目内唯一,建好之后不随意改。", { 输入: "比如 store-terms", 确定: "新建", 必填: true });
    if (!key) return;
    try {
      const r = await 请求(`${P()}/glossaries`, { method: "POST", body: JSON.stringify({ key, 术语: [] }) });
      location.hash = `#/glossary/${encodeURIComponent(r.id)}`;   // 建好直接进编辑页 —— 空表留在列表里没有用
    } catch (e) { 报错(e); }
  };
  $("#g-new").onclick = 新建;
  const 画 = async () => {
    let d;
    try { d = await 请求(`${P()}/glossaries`); }
    catch (e) { const s = 错误块(e, 画); $("#tbl").innerHTML = s.html; s.挂(); return; }
    const rs = d.items || [];
    if (!rs.length) {
      const s = 状态("", "这个项目还没有术语表",
        "术语表把「到店转化」「预约到店比」这类叫法统一成一个标准词,并写清定义和口径 —— **模型按这里的意思理解,不按它自己猜的**。",
        { 文: "新建术语表", 做: 新建 });
      $("#tbl").innerHTML = s.html; s.挂(); return;
    }
    $("#tbl").innerHTML = `<table><thead><tr>
        <th>标识</th><th>条数</th><th>最新冻结版本</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td>
          <td class="num">${esc(r.条数 ?? 0)}</td>
          <td>${r.最新冻结版本 ? `<span class="pill ok">${esc(r.最新冻结版本)}</span>`
                               : '<span class="pill none">还没冻结过</span>'}</td>
          <td class="num">${时间(r.更新时间)}</td>
          <td><a href="#/glossary/${encodeURIComponent(r.id)}">打开编辑</a></td></tr>`).join("")}
      </tbody></table>
      <div class="pager"><span>共 ${rs.length} 张</span></div>`;
  };
  await 画();
}

/* ── 实体识别(11-08;用户拍「拆分词典需要有配置的地方」→「新开实体识别页」+「大名单实时取,小的冻版本」)──
 * 一句话先拆:哪几个字是客户名 / 员工名 / 着装人名,哪几个是术语 —— 名字占掉的字不再算术语,再各自去该去的地方。
 * 照术语配置同一个形状:草稿随便改(If-Match)、冻结版本不可变、聊天助手里选一版才生效。
 * 借的是 RAGFlow 分类组件(类别 / 说明 / 例句 / 去哪 / 试一句)、Elasticsearch 同义词集(大名单不进版本)、spaCy / HanLP 词典条目。
 * **检查全在服务端算**(entity_dicts_api._详情);「试一句」打 preview,和运行时同一个函数,页面不自己拆。 */
async function 页_实体识别列表() {
  $("#main").innerHTML = `<div class="crumb">查询理解 / 实体识别</div>
    <div class="head"><div>
      <h1>实体识别</h1>
      <div class="sub">${md(`**实体识别**(Named Entity Recognition,基于实体词典):在模型拿到店长那句话之前,先认出哪几个字是**人名**(客户、员工、着装人),剩下的才去找**术语**:
        人名先占位(实体占位),不再被当成面料或工艺词;认出来之后去哪,由「查询路由」决定。客户、着装人这种大名单**只存「从哪张表取」**,运行时从业务库现取,名字不复制进后台。
        改草稿不影响在跑的东西,**冻结成版本、在聊天助手里选这一版**才生效。`)}</div>
    </div><div class="acts"><button id="s-new" class="pri">新建实体词典</button></div></div>
    <div id="tbl"><div class="state">加载中…</div></div>`;
  const 新建 = async () => {
    const key = await 问一句("新建实体词典", "给它起一个标识:项目内唯一,建好之后不随意改。", { 输入: "比如 store-entities", 确定: "新建", 必填: true });
    if (!key) return;
    try {
      const r = await 请求(`${P()}/entity-dicts`, { method: "POST", body: JSON.stringify({ key }) });
      location.hash = `#/entity/${encodeURIComponent(r.id)}`;
    } catch (e) { 报错(e); }
  };
  $("#s-new").onclick = 新建;
  const 画 = async () => {
    let d;
    try { d = await 请求(`${P()}/entity-dicts`); }
    catch (e) { const s = 错误块(e, 画); $("#tbl").innerHTML = s.html; s.挂(); return; }
    const rs = d.items || [];
    if (!rs.length) {
      const s = 状态("", "这个项目还没有实体词典",
        "没有实体词典时,术语按整句去找 —— 客户「宋锦书」名字里的「宋锦」会被当成面料。建一份,把客户名、员工名这些放进来。",
        { 文: "新建实体词典", 做: 新建 });
      $("#tbl").innerHTML = s.html; s.挂(); return;
    }
    $("#tbl").innerHTML = `<table><thead><tr><th>标识</th><th>几本词典</th><th>最新冻结版本</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td><td class="num">${esc(r.本数 ?? 0)}</td>
          <td>${r.最新冻结版本 ? `<span class="pill ok">${esc(r.最新冻结版本)}</span>` : '<span class="pill none">还没冻结过</span>'}</td>
          <td class="num">${时间(r.更新时间)}</td><td><a href="#/entity/${encodeURIComponent(r.id)}">打开编辑</a></td></tr>`).join("")}
      </tbody></table><div class="pager"><span>共 ${rs.length} 份</span></div>`;
  };
  await 画();
}

/* 实体词典编辑页:一本本词典 + 拿不准规则 → 保存草稿(If-Match)→ 冻结 → 试一句。
 * ⚠️ 检查结果是**上次保存的草稿**的;有没保存的改动时明说。 */
async function 页_实体识别详情(sid) {
  $("#main").innerHTML = `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/entity-dicts/${encodeURIComponent(sid)}`); }
  catch (e) { const s = 错误块(e, () => 页_实体识别详情(sid)); $("#main").innerHTML = s.html; s.挂(); return; }
  let rev = d.revision, 脏 = false, 版本们 = d.版本 || [];
  let 配 = JSON.parse(JSON.stringify(d.配置 || {}));
  if (!Array.isArray(配.词典)) 配.词典 = [];
  if (!配.拿不准) 配.拿不准 = JSON.parse(JSON.stringify(d.默认拿不准 || {}));
  const 表列们 = d.可选业务表列 || [];
  const 拆 = (s) => [...new Set(String(s || "").split(/[,，、;；\n\r]+/).map((x) => x.trim()).filter(Boolean))];

  $("#main").innerHTML = `
    <div class="crumb">查询理解 / <a href="#/entities">实体识别</a> / ${esc(d.key)}</div>
    <div class="head"><div><h1>${esc(d.key)}</h1>
      <div class="sub">草稿 revision <code id="s-rev">${esc(rev)}</code> · <span id="s-vcount"></span><br>${md(d.note || "")}</div></div></div>
    <div id="s-check"></div>
    <div class="card">
      <div style="font-weight:600;margin-bottom:6px">词典(<span id="s-n"></span> 本)</div>
      <div class="note">${md("每本词典是一类名字。**同样长时**:名字和某个术语一字不差时谁赢(默认让给术语 —— 有客户就叫「宋锦」,说「宋锦」照样当面料)。**最短字数**默认 2:单字名字会把「罗」「纱」这类单字术语全吃掉。")}</div>
      <div id="s-list"></div>
      <div style="margin-top:10px"><button id="s-add">加一本词典</button></div>
    </div>
    <div class="card" id="s-doubt"></div>
    <div class="card"><div class="footbar">
      <span class="msg" id="s-fb"></span>
      <button id="s-back">回列表</button><button id="s-save">保存草稿</button><button id="s-freeze" class="pri">冻结版本</button>
    </div></div>
    <div class="card" id="s-vers"></div>
    <div class="card" id="s-try"></div>`;

  const 选 = (i, f, 值, 项) => `<select class="t" data-i="${i}" data-f="${f}">${项.map(([v, 名]) =>
    `<option value="${esc(v)}"${String(v) === String(值) ? " selected" : ""}>${esc(名)}</option>`).join("")}</select>`;
  const 框 = (i, f, 值, 提示) => `<input class="t" data-i="${i}" data-f="${f}" value="${esc(值 ?? "")}" placeholder="${esc(提示)}">`;
  const 画一本 = (x, i) => {
    const 业务 = (x.来源 || "业务表") === "业务表";
    return `<div class="card" data-row="${i}">
      <div class="two">
        <div><label class="f">名称 <span class="req">*</span></label>${框(i, "名称", x.名称, "比如 客户名")}</div>
        <div><label class="f">类别 <span class="req">*</span> <span style="color:var(--ink3)">客户 / 员工 / 着装人 / 商品…(「术语」「通称」留给术语表)</span></label>${框(i, "类别", x.类别, "比如 客户")}</div>
      </div>
      <label class="f">说明 <span style="color:var(--ink3)">选填;这本词典装的是谁</span></label>${框(i, "说明", x.说明, "比如 门店客户档案里的姓名")}
      <label class="f">例句 <span style="color:var(--ink3)">选填;店长会怎么提到他们,逗号分开(试一句时可以直接拿来试)</span></label>
      <textarea class="t" rows="1" style="min-height:36px" data-i="${i}" data-f="例句">${esc((x.例句 || []).join(","))}</textarea>
      <div class="two">
        <div><label class="f">来源</label>${选(i, "来源", x.来源 || "业务表", [["业务表", "业务表(运行时现取,名字不进后台)"], ["手工", "手工词条(随版本冻结)"]])}</div>
        <div>${业务 ? `<label class="f">从哪张表哪一列取</label>${选(i, "表列", x.表列 || "", [["", "请选择"], ...表列们.map((t) => [t.值, t.名])])}`
                    : `<label class="f">词条 <span style="color:var(--ink3)">逗号或回车分开</span></label>
                       <textarea class="t" rows="2" style="min-height:44px" data-i="${i}" data-f="词条">${esc((x.词条 || []).join(","))}</textarea>`}</div>
      </div>
      <div class="two">
        <div><label class="f">最短字数</label><input class="t" type="number" min="1" max="10" data-i="${i}" data-f="最短字数" value="${esc(x.最短字数 ?? 2)}"></div>
        <div><label class="f">同样长时</label>${选(i, "同样长时", x.同样长时 || "让给术语", [["让给术语", "让给术语(默认)"], ["压过术语", "压过术语"]])}</div>
      </div>
      <div class="k">认出来之后去哪(只占位 / 提示一句 / 先调工具 / 交给技能),在「查询路由」里配。</div>
      <div style="margin-top:8px;text-align:right"><button class="danger" data-del="${i}">删掉这本</button></div>
    </div>`;
  };
  const 画列表 = () => {
    $("#s-n").textContent = String(配.词典.length);
    $("#s-list").innerHTML = 配.词典.length ? 配.词典.map(画一本).join("")
      : 状态("", "还没有词典", "点「加一本词典」:比如客户名(业务表 · 客户表姓名)、员工名(手工词条)。").html;
  };
  const 画拿不准 = () => {
    const q = 配.拿不准 || {};
    $("#s-doubt").innerHTML = `<div style="font-weight:600;margin-bottom:6px">歧义消解(拿不准的时候)</div>
      <div class="note">${md("名单里没有、词典判不了的情况:**单字术语紧挨着称呼**(「小罗」「罗姐」)。这时术语照带,但附一句提醒,让模型自己判断是不是在叫人。称呼词是 11-08 随做法一起定的,**拍脑袋的**,按店里的说法改。")}</div>
      <label class="f"><input type="checkbox" id="q-on"${q.开 === false ? "" : " checked"}> 开着</label>
      <div class="two">
        <div><label class="f">术语前面是这些字 <span style="color:var(--ink3)">逗号分开</span></label><input class="t" id="q-pre" value="${esc((q.称呼前 || []).join(","))}"></div>
        <div><label class="f">术语后面是这些字 <span style="color:var(--ink3)">逗号分开;别放「总」「工」(「纱总共」「纱工艺」会误报)</span></label><input class="t" id="q-post" value="${esc((q.称呼后 || []).join(","))}"></div>
      </div>
      <label class="f">给模型的提醒 <span style="color:var(--ink3)">{片段} 换成那个字,{标准词} 换成那条术语</span></label>
      <textarea class="t" id="q-msg" rows="2" style="min-height:44px">${esc(q.提醒 || "")}</textarea>`;
    $("#q-on").onchange = (e) => { 配.拿不准.开 = e.target.checked; 标脏(); };
    $("#q-pre").oninput = (e) => { 配.拿不准.称呼前 = 拆(e.target.value); 标脏(); };
    $("#q-post").oninput = (e) => { 配.拿不准.称呼后 = 拆(e.target.value); 标脏(); };
    $("#q-msg").oninput = (e) => { 配.拿不准.提醒 = e.target.value; 标脏(); };
  };
  const 画检查 = (检) => {
    const 阻 = (检 && 检.阻断) || [], 醒 = (检 && 检.提醒) || [];
    const 旧 = 脏 ? `<div class="k">⚠️ 下面是<b>上次保存的草稿</b>的检查结果;你有没保存的改动,保存之后会重新检查。</div>` : "";
    $("#s-check").innerHTML = (阻.length
      ? `<div class="card bad"><div style="font-weight:600;color:var(--fail)">要改完这 ${阻.length} 处才能冻结</div><ul>${阻.map((x) => `<li>${md(x)}</li>`).join("")}</ul>${旧}</div>`
      : `<div class="note">${md("**检查通过,没有挡住冻结的问题。**")}${旧}</div>`)
      + (醒.length ? `<div class="note warn"><b>提醒(不挡冻结,建议看一眼):</b><ul>${醒.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>` : "");
  };
  const 画版本 = () => {
    $("#s-vcount").innerHTML = 版本们.length ? `已有 ${版本们.length} 个冻结版本(最新 ${esc(版本们[0].版本)})` : "<b>还没冻结过版本</b>";
    $("#s-vers").innerHTML = `<div style="font-weight:600;margin-bottom:8px">冻结的版本</div>`
      + (版本们.length ? `<table><thead><tr><th>版本</th><th>几本词典</th><th>内容哈希</th><th>冻结于</th><th>冻结人</th></tr></thead><tbody>
          ${版本们.map((v) => `<tr><td class="num">${esc(v.版本)}</td><td class="num">${esc(v.本数 ?? "")}</td>
            <td class="num">${esc(String(v.内容哈希 || "").slice(0, 19))}</td><td class="num">${时间(v.冻结于)}</td><td>${esc(v.冻结人 || "")}</td></tr>`).join("")}
          </tbody></table><div class="note">${md("冻结的版本**内容不再改**。聊天助手要用哪一版,在聊天助手的配置里选,出版本、上生产才生效。")}</div>`
        : `<div class="state" style="padding:20px">还没有冻结的版本 —— 上面写好、保存之后点「冻结版本」。</div>`);
    const 业务本 = 配.词典.filter((x) => (x.来源 || "业务表") === "业务表");
    $("#s-try").innerHTML = `<div style="font-weight:600;margin-bottom:6px">试一句(实体识别会把这句话认成什么)</div>`
      + (版本们.length ? `<div class="note">${md("输入一句店长会说的话,看它**拆成哪几段、每段去哪、模型实际收到什么**。和正式运行是同一个函数。业务表那几本后台连不到业务库,**在下面填几个名字代替**。")}</div>
          <div class="two">
            <div><label class="f">用哪个实体识别版本</label><select class="t" id="s-tv">${版本们.map((v) => `<option value="${esc(v.id)}">${esc(v.版本)}(${esc(v.本数 ?? "")} 本 · ${时间(v.冻结于)})</option>`).join("")}</select></div>
            <div><label class="f">连哪版术语一起看</label><select class="t" id="s-tg"><option value="">不带术语(只看名字怎么拆)</option>${(d.可选术语 || []).map((v) => `<option value="${esc(v.id)}">${esc(v.名称)} · ${esc(v.版本)} · ${esc(v.条数)} 条</option>`).join("")}</select></div>
          </div>
          ${业务本.map((x, k) => `<label class="f">「${esc(x.名称 || "")}」试用名单 <span style="color:var(--ink3)">逗号分开</span></label>
            <input class="t" data-try="${esc(x.名称 || "")}" placeholder="比如 宋锦书,罗晓雯">`).join("")}
          <label class="f">一句话</label>
          <textarea class="t" id="s-tt" rows="2" style="min-height:44px" placeholder="比如:宋锦书想做一条宋锦马面,小罗帮她量过了吗?"></textarea>
          <div style="margin-top:8px"><button class="pri" id="s-tgo">试一句</button> <span class="k" id="s-tmsg"></span></div>
          <div id="s-tout"></div>`
        : `<div class="state" style="padding:20px">要先冻结一个版本才能试 —— 试的是冻结版本,和聊天助手真正用的是同一份。</div>`);
    if (版本们.length) $("#s-tgo").onclick = 试一句;
  };
  const 标脏 = () => {
    if (!脏) { 脏 = true; 画检查(d.检查); }
    $("#s-fb").textContent = "有没保存的改动"; $("#s-fb").className = "msg";
  };
  const 写回 = (el) => {
    const i = Number(el.dataset.i), f = el.dataset.f, x = 配.词典[i];
    if (!x || !f) return;
    if (f === "例句" || f === "词条") x[f] = 拆(el.value);
    else if (f === "最短字数") x[f] = Number(el.value);
    else x[f] = el.value;
  };
  $("#s-list").oninput = (e) => { if (e.target && e.target.dataset && e.target.dataset.f) { 写回(e.target); 标脏(); } };
  $("#s-list").onchange = (e) => {
    const f = e.target && e.target.dataset ? e.target.dataset.f : "";
    if (f === "来源") { 写回(e.target); 标脏(); 画列表(); }
  };
  $("#s-list").onclick = async (e) => {
    const i = e.target && e.target.dataset ? e.target.dataset.del : undefined;
    if (i === undefined) return;
    const x = 配.词典[Number(i)] || {};
    if (!(await 问一句("删掉这本词典?", `「${esc(x.名称 || "没写名称的这本")}」会从草稿里拿掉;要点「保存草稿」才真的存下来。`, { 确定: "删掉", 取消: "留着" }))) return;
    配.词典.splice(Number(i), 1); 标脏(); 画列表();
  };
  $("#s-add").onclick = () => { 配.词典.push({ 名称: "", 类别: "", 来源: "业务表", 表列: "", 最短字数: 2, 同样长时: "让给术语" }); 标脏(); 画列表(); };

  /* 存之前整理:业务表来源不带词条、手工来源不带表列;没选「占位并提示」不带提示(界面上看不到的东西不该悄悄存进去) */
  const 整理 = () => Object.assign({}, 配, { 词典: 配.词典.map((x) => {
    const o = Object.assign({}, x);
    ["名称", "类别", "说明", "提示"].forEach((k) => { if (o[k] !== undefined) o[k] = String(o[k] || "").trim(); });
    if (!o.说明) delete o.说明;
    o.例句 = 拆((o.例句 || []).join(",")); if (!o.例句.length) delete o.例句;
    o.来源 = o.来源 || "业务表";
    if (o.来源 === "业务表") delete o.词条; else { delete o.表列; o.词条 = 拆((o.词条 || []).join(",")); }
    o.最短字数 = Number.isFinite(Number(o.最短字数)) ? Number(o.最短字数) : 2;
    if ((o.命中后 || "占位") !== "占位并提示") delete o.提示;
    return o;
  }) });

  $("#s-back").onclick = async () => {
    if (脏 && !(await 问一句("离开这一页?", "有没保存的改动,离开会丢掉。", { 确定: "丢掉并离开", 取消: "留下" }))) return;
    location.hash = "#/entities";
  };
  const 存草稿 = async () => {
    try {
      const r = await 请求(`${P()}/entity-dicts/${encodeURIComponent(sid)}/draft`, {
        method: "PATCH", headers: { "If-Match": String(rev) }, body: JSON.stringify({ 配置: 整理() }) });
      rev = r.revision; $("#s-rev").textContent = String(rev);
      d.检查 = r.检查; 配 = JSON.parse(JSON.stringify(r.配置 || {})); if (!Array.isArray(配.词典)) 配.词典 = [];
      if (!配.拿不准) 配.拿不准 = JSON.parse(JSON.stringify(d.默认拿不准 || {}));
      版本们 = r.版本 || 版本们; 脏 = false; 画列表(); 画拿不准(); 画检查(r.检查); 画版本();
      $("#s-fb").innerHTML = md(r.note || "草稿已保存。"); $("#s-fb").className = "msg";
      return true;
    } catch (e) {
      const b = e.体 || {};
      if (e.码 === 409) {
        $("#s-fb").innerHTML = `<b>这份词典被别人改过了,刷新再合并,不要直接覆盖。</b><br>${esc(b.message || "")}
          <br><button id="s-reload">刷新看最新的</button>
          <details><summary>我这边没保存的内容(刷新会丢,先复制下来)</summary><pre class="io">${esc(JSON.stringify(整理(), null, 2))}</pre></details>`;
        $("#s-fb").className = "msg bad";
        $("#s-reload").onclick = () => 页_实体识别详情(sid);
      } else { $("#s-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`; $("#s-fb").className = "msg bad"; }
      return false;
    }
  };
  $("#s-save").onclick = async () => { $("#s-save").disabled = true; await 存草稿(); $("#s-save").disabled = false; };
  $("#s-freeze").onclick = async () => {
    if (脏) {
      if (!(await 问一句("先保存草稿?", "冻结的是<b>已保存的草稿</b>。你有没保存的改动 —— 先保存,再冻结。", { 确定: "保存并冻结", 取消: "先不冻" }))) return;
      if (!(await 存草稿())) return;
    }
    $("#s-freeze").disabled = true;
    try {
      const r = await 请求(`${P()}/entity-dicts/${encodeURIComponent(sid)}/versions`, { method: "POST" });
      $("#s-fb").innerHTML = `已冻结为 <b>${esc(r.版本)}</b>(内容哈希 <code>${esc(String(r.内容哈希 || "").slice(0, 19))}</code>)<br>${md(r.note || "")}`;
      $("#s-fb").className = "msg";
      setTimeout(() => 页_实体识别详情(sid), 900);
    } catch (e) {
      const b = e.体 || {}, 阻 = (b.field_errors && b.field_errors.阻断) || [];
      if (e.码 === 422 && 阻.length) $("#s-fb").innerHTML = `<b>还冻不了,先改这 ${阻.length} 处:</b>${阻.map((x) => "<br>· " + md(x)).join("")}`;
      else if (b.code === "NO_CHANGE") $("#s-fb").innerHTML = `<b>${esc(b.message || "内容和上一版一样")}</b> —— 不用再冻一版。<br>${md(b.advice || "")}`;
      else $("#s-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
      $("#s-fb").className = "msg bad"; $("#s-freeze").disabled = false;
    }
  };
  async function 试一句() {
    const 文 = $("#s-tt").value.trim();
    if (!文) { $("#s-tmsg").textContent = "先写一句话。"; return; }
    const 试用名单 = {};
    document.querySelectorAll("[data-try]").forEach((el) => { const v = 拆(el.value); if (v.length) 试用名单[el.dataset.try] = v; });
    $("#s-tgo").disabled = true; $("#s-tmsg").textContent = "在试…";
    try {
      const r = await 请求(`${P()}/entity-dict-versions/${encodeURIComponent($("#s-tv").value)}/preview`, {
        method: "POST", body: JSON.stringify({ 文本: 文, 术语版本: $("#s-tg").value || null, 试用名单 }) });
      const 段们 = r.分段 || [];
      const 字 = Array.from(文), 标 = {};
      段们.forEach((x) => { const n = Array.from(String(x.片段 || "")).length; if (Number.isInteger(x.位置) && n) 标[x.位置] = [n, x.类别]; });
      let 句 = "", i = 0;
      while (i < 字.length) {
        if (标[i]) { const [n, 类] = 标[i]; 句 += `<mark title="${esc(类)}">${esc(字.slice(i, i + n).join(""))}</mark><sub>${esc(类)}</sub>`; i += n; }
        else { 句 += esc(字[i]); i += 1; }
      }
      $("#s-tout").innerHTML = `<div class="note">${句}</div>`
        + (段们.length ? `<table><thead><tr><th>片段</th><th>类别</th><th>哪本词典</th><th>去哪</th></tr></thead><tbody>${段们.map((x) => `
            <tr><td>${esc(x.片段)}</td><td>${esc(x.类别)}</td><td>${esc(x.词典 || (x.类别 === "术语" || x.类别 === "通称" ? "术语表" : ""))}</td><td class="k">由查询路由决定 → 去<a href="#/routes">「查询路由」</a>试</td></tr>`).join("")}</tbody></table>`
          : `<div class="state" style="padding:12px">这句话没认出任何名字或术语。</div>`)
        + ((r.没试到的词典 || []).length ? `<div class="note warn">${(r.没试到的词典 || []).map((x) => `「${esc(x.名称)}」没试到:${esc(x.说明)}`).join("<br>")}</div>` : "")
        + `<label class="f">模型会收到</label><pre class="io">${esc(r.模型会收到 || "(什么都不收到 —— 这句话没有要带的术语或提示)")}</pre>`;
      $("#s-tmsg").textContent = "";
    } catch (e) { const b = e.体 || {}; $("#s-tmsg").textContent = b.message || e.message; }
    $("#s-tgo").disabled = false;
  }
  画列表(); 画拿不准(); 画检查(d.检查); 画版本();
}

/* ── 查询路由(11-08 第二期;用户拍「查询理解」下三样各自列表-详情-配置、各自冻版本;去向 6 种全要)──
 * 一条规则 = 条件(某类实体 / 某个意图 / 拿不准)→ 去向;从上往下,第一条对上的生效;都没对上走默认(和第一期一样)。
 * 「转人工」这一版冻结时服务端会拦(还没接上店长助手主循环),页面上照实写明,不藏。
 * 检查全在服务端(routes_api._详情);「试一句」打 preview,和运行时同一套函数。 */
async function 页_路由列表() {
  $("#main").innerHTML = `<div class="crumb">查询理解 / 查询路由</div>
    <div class="head"><div><h1>查询路由</h1>
      <div class="sub">${md(`**查询路由**(Query Routing):实体识别认出来的东西,各自**去哪**。比如认出客户名 → 提示模型先调客户档案工具;
        认出「报价」意图 → 交给报价技能;拿不准 → 提示模型自己判断。从上往下,**第一条对上的规则生效**;都没对上走默认:术语带定义、人名只占位、拿不准提示一句。
        冻结成版本、在聊天助手里选这一版才生效。`)}</div>
    </div><div class="acts"><button id="r-new" class="pri">新建路由</button></div></div>
    <div id="tbl"><div class="state">加载中…</div></div>`;
  const 新建 = async () => {
    const key = await 问一句("新建路由", "给它起一个标识:项目内唯一,建好之后不随意改。", { 输入: "比如 store-routes", 确定: "新建", 必填: true });
    if (!key) return;
    try { const r = await 请求(`${P()}/routes`, { method: "POST", body: JSON.stringify({ key }) }); location.hash = `#/route/${encodeURIComponent(r.id)}`; }
    catch (e) { 报错(e); }
  };
  $("#r-new").onclick = 新建;
  const 画 = async () => {
    let d;
    try { d = await 请求(`${P()}/routes`); }
    catch (e) { const s = 错误块(e, 画); $("#tbl").innerHTML = s.html; s.挂(); return; }
    const rs = d.items || [];
    if (!rs.length) {
      const s = 状态("", "这个项目还没有查询路由", "没有路由时全走默认:术语带定义、人名只占位、拿不准提示一句。建一份,就能让「认出客户名」「判出某个意图」各自去该去的地方。", { 文: "新建路由", 做: 新建 });
      $("#tbl").innerHTML = s.html; s.挂(); return;
    }
    $("#tbl").innerHTML = `<table><thead><tr><th>标识</th><th>几条规则</th><th>最新冻结版本</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td><td class="num">${esc(r.本数 ?? 0)}</td>
          <td>${r.最新冻结版本 ? `<span class="pill ok">${esc(r.最新冻结版本)}</span>` : '<span class="pill none">还没冻结过</span>'}</td>
          <td class="num">${时间(r.更新时间)}</td><td><a href="#/route/${encodeURIComponent(r.id)}">打开编辑</a></td></tr>`).join("")}
      </tbody></table><div class="pager"><span>共 ${rs.length} 份</span></div>`;
  };
  await 画();
}

async function 页_路由详情(rid) {
  $("#main").innerHTML = `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/routes/${encodeURIComponent(rid)}`); }
  catch (e) { const s = 错误块(e, () => 页_路由详情(rid)); $("#main").innerHTML = s.html; s.挂(); return; }
  let rev = d.revision, 脏 = false, 版本们 = d.版本 || [];
  let 配 = JSON.parse(JSON.stringify(d.配置 || {})); if (!Array.isArray(配.规则)) 配.规则 = [];
  const 去向们 = d.去向们 || [], 没接上 = d.还没接上的去向 || [], 种类们 = d.条件种类们 || [];
  $("#main").innerHTML = `
    <div class="crumb">查询理解 / <a href="#/routes">查询路由</a> / ${esc(d.key)}</div>
    <div class="head"><div><h1>${esc(d.key)}</h1>
      <div class="sub">草稿 revision <code id="r-rev">${esc(rev)}</code> · <span id="r-vcount"></span><br>${md(d.note || "")}</div></div></div>
    <div id="r-check"></div>
    <div class="card">
      <div style="font-weight:600;margin-bottom:6px">规则(<span id="r-n"></span> 条,从上往下第一条对上的生效)</div>
      <div class="note">${md(`条件:**实体**(写类别:客户 / 员工 / 着装人 / 术语 / 通称)、**意图**(第三期「意图识别」接上后才生效)、**歧义**(拿不准的时候)。
        去向:带术语定义 / 只占位 / 提示一句 / 提示先调工具 / 交给技能 / 转人工。提示里可以写 {片段}、{标准词}。
        ⚠️ 「交给技能」是**强提示**,技能仍由模型挑;「转人工」${没接上.includes("转人工") ? "**还没接上店长助手**(要改主循环),这一版冻结时会被拦住" : "已接上"}。`)}</div>
      <div id="r-list"></div>
      <div style="margin-top:10px"><button id="r-add">加一条规则</button></div>
    </div>
    <div class="card"><div class="footbar">
      <span class="msg" id="r-fb"></span>
      <button id="r-back">回列表</button><button id="r-save">保存草稿</button><button id="r-freeze" class="pri">冻结版本</button>
    </div></div>
    <div class="card" id="r-vers"></div>
    <div class="card" id="r-try"></div>`;
  const 选 = (i, f, 值, 项) => `<select class="t" data-i="${i}" data-f="${f}">${项.map(([v, 名]) =>
    `<option value="${esc(v)}"${String(v) === String(值) ? " selected" : ""}>${esc(名)}</option>`).join("")}</select>`;
  const 框 = (i, f, 值, 提示) => `<input class="t" data-i="${i}" data-f="${f}" value="${esc(值 ?? "")}" placeholder="${esc(提示)}">`;
  const 画一条 = (r, i) => {
    const 条 = r.条件 || {}, 去 = r.去向 || "提示一句";
    return `<div class="card" data-row="${i}">
      <div class="two">
        <div><label class="f">名称 <span class="req">*</span></label>${框(i, "名称", r.名称, "比如 客户名先查档案")}</div>
        <div style="text-align:right;padding-top:22px"><button data-up="${i}"${i === 0 ? " disabled" : ""}>上移</button> <button data-down="${i}"${i === 配.规则.length - 1 ? " disabled" : ""}>下移</button></div>
      </div>
      <div class="two">
        <div><label class="f">条件</label>${选(i, "条件.种类", 条.种类 || "实体", 种类们.map((x) => [x, x]))}</div>
        <div>${(条.种类 || "实体") === "歧义" ? '<label class="f">值</label><div class="k">拿不准的时候(不用填)</div>'
          : `<label class="f">${(条.种类 || "实体") === "实体" ? "哪类实体" : "哪个意图"} <span class="req">*</span></label>${框(i, "条件.值", 条.值, (条.种类 || "实体") === "实体" ? "客户 / 员工 / 着装人 / 术语 / 通称" : "比如 报价")}`}</div>
      </div>
      <div class="two">
        <div><label class="f">去向</label>${选(i, "去向", 去, 去向们.map((x) => [x, 没接上.includes(x) ? `${x}(还没接上)` : x]))}</div>
        <div>${去 === "提示先调工具" ? `<label class="f">工具名 <span class="req">*</span> <span style="color:var(--ink3)">要是店长助手开着的工具</span></label>${框(i, "工具", r.工具, "比如 customer_profile")}`
          : 去 === "交给技能" ? `<label class="f">技能名 <span class="req">*</span> <span style="color:var(--ink3)">要是店长助手放行的技能</span></label>${框(i, "技能", r.技能, "比如 quote")}`
          : 去 === "转人工" ? `<label class="f">说明</label>${框(i, "说明", r.说明, "比如 投诉一律转店长")}` : ""}</div>
      </div>
      ${["提示一句", "提示先调工具", "交给技能"].includes(去) ? `<label class="f">给模型的提示 ${去 === "提示一句" ? '<span class="req">*</span>' : '<span style="color:var(--ink3)">选填,不写用默认那句</span>'}</label>
        <textarea class="t" rows="2" style="min-height:44px" data-i="${i}" data-f="提示">${esc(r.提示 || "")}</textarea>` : ""}
      <div style="margin-top:8px;text-align:right"><button class="danger" data-del="${i}">删掉这条</button></div>
    </div>`;
  };
  const 画列表 = () => {
    $("#r-n").textContent = String(配.规则.length);
    $("#r-list").innerHTML = 配.规则.length ? 配.规则.map(画一条).join("")
      : 状态("", "还没有规则", "一条都没有时全走默认。点「加一条规则」:比如「实体 · 客户 → 提示先调工具」。").html;
  };
  const 画检查 = (检) => {
    const 阻 = (检 && 检.阻断) || [], 醒 = (检 && 检.提醒) || [];
    const 旧 = 脏 ? `<div class="k">⚠️ 下面是<b>上次保存的草稿</b>的检查结果;你有没保存的改动,保存之后会重新检查。</div>` : "";
    $("#r-check").innerHTML = (阻.length
      ? `<div class="card bad"><div style="font-weight:600;color:var(--fail)">要改完这 ${阻.length} 处才能冻结</div><ul>${阻.map((x) => `<li>${md(x)}</li>`).join("")}</ul>${旧}</div>`
      : `<div class="note">${md("**检查通过,没有挡住冻结的问题。**")}${旧}</div>`)
      + (醒.length ? `<div class="note warn"><b>提醒(不挡冻结,建议看一眼):</b><ul>${醒.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>` : "");
  };
  const 画版本 = () => {
    $("#r-vcount").innerHTML = 版本们.length ? `已有 ${版本们.length} 个冻结版本(最新 ${esc(版本们[0].版本)})` : "<b>还没冻结过版本</b>";
    $("#r-vers").innerHTML = `<div style="font-weight:600;margin-bottom:8px">冻结的版本</div>`
      + (版本们.length ? `<table><thead><tr><th>版本</th><th>几条规则</th><th>内容哈希</th><th>冻结于</th><th>冻结人</th></tr></thead><tbody>
          ${版本们.map((v) => `<tr><td class="num">${esc(v.版本)}</td><td class="num">${esc(v.本数 ?? "")}</td>
            <td class="num">${esc(String(v.内容哈希 || "").slice(0, 19))}</td><td class="num">${时间(v.冻结于)}</td><td>${esc(v.冻结人 || "")}</td></tr>`).join("")}
          </tbody></table>` : `<div class="state" style="padding:20px">还没有冻结的版本 —— 上面写好、保存之后点「冻结版本」。</div>`);
    $("#r-try").innerHTML = `<div style="font-weight:600;margin-bottom:6px">试一句(每段会走哪条规则)</div>`
      + (版本们.length ? `<div class="note">${md("先用选的实体识别版本认出名字和术语,再用这一版路由决定每段去哪。业务表那几本在下面填几个名字代替;意图在第三期接上前**手填**。")}</div>
          <div class="two">
            <div><label class="f">路由版本</label><select class="t" id="r-tv">${版本们.map((v) => `<option value="${esc(v.id)}">${esc(v.版本)}(${esc(v.本数 ?? "")} 条)</option>`).join("")}</select></div>
            <div><label class="f">实体识别版本</label><select class="t" id="r-te"><option value="">不认名字(只认术语)</option>${(d.可选实体识别 || []).map((v) => `<option value="${esc(v.id)}">${esc(v.名称)} · ${esc(v.版本)}</option>`).join("")}</select></div>
            <div><label class="f">术语版本</label><select class="t" id="r-tg"><option value="">不带术语</option>${(d.可选术语 || []).map((v) => `<option value="${esc(v.id)}">${esc(v.名称)} · ${esc(v.版本)} · ${esc(v.条数)} 条</option>`).join("")}</select></div>
            <div><label class="f">意图(手填,选填)</label><input class="t" id="r-ti" placeholder="比如 报价"></div>
          </div>
          <label class="f">试用名单 <span style="color:var(--ink3)">一行一本:词典名称: 名字,名字(比如「客户名: 宋锦书,罗晓雯」)</span></label>
          <textarea class="t" id="r-tn" rows="2" style="min-height:44px"></textarea>
          <label class="f">一句话</label><textarea class="t" id="r-tt" rows="2" style="min-height:44px" placeholder="比如:宋锦书想做一条宋锦马面,小罗帮她量过了吗?"></textarea>
          <div style="margin-top:8px"><button class="pri" id="r-tgo">试一句</button> <span class="k" id="r-tmsg"></span></div><div id="r-tout"></div>`
        : `<div class="state" style="padding:20px">要先冻结一个版本才能试。</div>`);
    if (版本们.length) $("#r-tgo").onclick = 试一句;
  };
  const 标脏 = () => { if (!脏) { 脏 = true; 画检查(d.检查); } $("#r-fb").textContent = "有没保存的改动"; $("#r-fb").className = "msg"; };
  const 写回 = (el) => {
    const i = Number(el.dataset.i), f = el.dataset.f, r = 配.规则[i];
    if (!r || !f) return;
    if (f.startsWith("条件.")) { r.条件 = Object.assign({}, r.条件 || {}, { [f.slice(3)]: el.value }); }
    else r[f] = el.value;
  };
  $("#r-list").oninput = (e) => { if (e.target && e.target.dataset && e.target.dataset.f) { 写回(e.target); 标脏(); } };
  $("#r-list").onchange = (e) => { const f = e.target && e.target.dataset ? e.target.dataset.f : ""; if (f === "去向" || f === "条件.种类") { 写回(e.target); 标脏(); 画列表(); } };
  $("#r-list").onclick = async (e) => {
    const ds = (e.target && e.target.dataset) || {};
    if (ds.up !== undefined || ds.down !== undefined) {
      const i = Number(ds.up ?? ds.down), j = ds.up !== undefined ? i - 1 : i + 1;
      if (j < 0 || j >= 配.规则.length) return;
      [配.规则[i], 配.规则[j]] = [配.规则[j], 配.规则[i]]; 标脏(); 画列表(); return;
    }
    if (ds.del === undefined) return;
    const r = 配.规则[Number(ds.del)] || {};
    if (!(await 问一句("删掉这条规则?", `「${esc(r.名称 || "没写名称的这条")}」会从草稿里拿掉;要点「保存草稿」才真的存下来。`, { 确定: "删掉", 取消: "留着" }))) return;
    配.规则.splice(Number(ds.del), 1); 标脏(); 画列表();
  };
  $("#r-add").onclick = () => { 配.规则.push({ 名称: "", 条件: { 种类: "实体", 值: "" }, 去向: "提示一句", 提示: "" }); 标脏(); 画列表(); };
  /* 存之前整理:去向用不到的参数不发(界面上看不到的东西不该悄悄存进去) */
  const 整理 = () => ({ 规则: 配.规则.map((r) => {
    const o = { 名称: String(r.名称 || "").trim(), 条件: { 种类: (r.条件 || {}).种类 || "实体" }, 去向: r.去向 || "提示一句" };
    if (o.条件.种类 !== "歧义") o.条件.值 = String((r.条件 || {}).值 || "").trim();
    if (["提示一句", "提示先调工具", "交给技能"].includes(o.去向) && String(r.提示 || "").trim()) o.提示 = String(r.提示).trim();
    if (o.去向 === "提示先调工具") o.工具 = String(r.工具 || "").trim();
    if (o.去向 === "交给技能") o.技能 = String(r.技能 || "").trim();
    if (o.去向 === "转人工" && String(r.说明 || "").trim()) o.说明 = String(r.说明).trim();
    return o;
  }) });
  $("#r-back").onclick = async () => { if (脏 && !(await 问一句("离开这一页?", "有没保存的改动,离开会丢掉。", { 确定: "丢掉并离开", 取消: "留下" }))) return; location.hash = "#/routes"; };
  const 存草稿 = async () => {
    try {
      const r = await 请求(`${P()}/routes/${encodeURIComponent(rid)}/draft`, { method: "PATCH", headers: { "If-Match": String(rev) }, body: JSON.stringify({ 配置: 整理() }) });
      rev = r.revision; $("#r-rev").textContent = String(rev);
      d.检查 = r.检查; 配 = JSON.parse(JSON.stringify(r.配置 || {})); if (!Array.isArray(配.规则)) 配.规则 = [];
      版本们 = r.版本 || 版本们; 脏 = false; 画列表(); 画检查(r.检查); 画版本();
      $("#r-fb").innerHTML = md(r.note || "草稿已保存。"); $("#r-fb").className = "msg"; return true;
    } catch (e) {
      const b = e.体 || {};
      if (e.码 === 409) {
        $("#r-fb").innerHTML = `<b>这份路由被别人改过了,刷新再合并,不要直接覆盖。</b><br>${esc(b.message || "")}<br><button id="r-reload">刷新看最新的</button>
          <details><summary>我这边没保存的内容(刷新会丢,先复制下来)</summary><pre class="io">${esc(JSON.stringify(整理(), null, 2))}</pre></details>`;
        $("#r-reload").onclick = () => 页_路由详情(rid);
      } else $("#r-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
      $("#r-fb").className = "msg bad"; return false;
    }
  };
  $("#r-save").onclick = async () => { $("#r-save").disabled = true; await 存草稿(); $("#r-save").disabled = false; };
  $("#r-freeze").onclick = async () => {
    if (脏) { if (!(await 问一句("先保存草稿?", "冻结的是<b>已保存的草稿</b>。你有没保存的改动 —— 先保存,再冻结。", { 确定: "保存并冻结", 取消: "先不冻" }))) return; if (!(await 存草稿())) return; }
    $("#r-freeze").disabled = true;
    try {
      const r = await 请求(`${P()}/routes/${encodeURIComponent(rid)}/versions`, { method: "POST" });
      $("#r-fb").innerHTML = `已冻结为 <b>${esc(r.版本)}</b>(内容哈希 <code>${esc(String(r.内容哈希 || "").slice(0, 19))}</code>)<br>${md(r.note || "")}`; $("#r-fb").className = "msg";
      setTimeout(() => 页_路由详情(rid), 900);
    } catch (e) {
      const b = e.体 || {}, 阻 = (b.field_errors && b.field_errors.阻断) || [];
      if (e.码 === 422 && 阻.length) $("#r-fb").innerHTML = `<b>还冻不了,先改这 ${阻.length} 处:</b>${阻.map((x) => "<br>· " + md(x)).join("")}`;
      else if (b.code === "NO_CHANGE") $("#r-fb").innerHTML = `<b>${esc(b.message || "内容和上一版一样")}</b> —— 不用再冻一版。`;
      else $("#r-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
      $("#r-fb").className = "msg bad"; $("#r-freeze").disabled = false;
    }
  };
  async function 试一句() {
    const 文 = $("#r-tt").value.trim();
    if (!文) { $("#r-tmsg").textContent = "先写一句话。"; return; }
    const 试用名单 = {};
    String($("#r-tn").value || "").split(/\n/).forEach((行) => { const m = 行.split(/[:：]/); if (m.length >= 2) { const v = m.slice(1).join(":").split(/[,，、]/).map((x) => x.trim()).filter(Boolean); if (v.length) 试用名单[m[0].trim()] = v; } });
    $("#r-tgo").disabled = true; $("#r-tmsg").textContent = "在试…";
    try {
      const r = await 请求(`${P()}/route-versions/${encodeURIComponent($("#r-tv").value)}/preview`, { method: "POST",
        body: JSON.stringify({ 文本: 文, 实体识别版本: $("#r-te").value || null, 术语版本: $("#r-tg").value || null, 意图: $("#r-ti").value.trim() || null, 试用名单 }) });
      const 走 = r.走了 || [];
      $("#r-tout").innerHTML = (走.length ? `<table><thead><tr><th>对象</th><th>走了哪条规则</th><th>去向</th></tr></thead><tbody>${走.map((x) => `
          <tr><td>${esc(x.对象)}</td><td>${esc(x.规则)}</td><td>${esc(x.去向)}</td></tr>`).join("")}</tbody></table>` : `<div class="state" style="padding:12px">这句话没认出任何实体,也没有意图。</div>`)
        + (r.技能 ? `<div class="note">这一句会被<b>强提示</b>交给技能「${esc(r.技能)}」(技能仍由模型挑)。</div>` : "")
        + ((r.没试到的词典 || []).length ? `<div class="note warn">${(r.没试到的词典 || []).map((x) => `「${esc(x.名称)}」没试到:${esc(x.说明)}`).join("<br>")}</div>` : "")
        + `<label class="f">模型会收到</label><pre class="io">${esc(r.模型会收到 || "(什么都不收到)")}</pre>`;
      $("#r-tmsg").textContent = "";
    } catch (e) { const b = e.体 || {}; $("#r-tmsg").textContent = b.message || e.message; }
    $("#r-tgo").disabled = false;
  }
  画列表(); 画检查(d.检查); 画版本();
}

async function 页_意图列表() {
  $("#main").innerHTML = `<div class="crumb">查询理解 / 意图识别</div>
    <div class="head"><div><h1>意图识别</h1>
      <div class="sub">${md(`**意图识别**(Intent Recognition):每轮先让最便宜那档模型判一次「店长想干什么」,判出的意图交给查询路由决定去哪。每个意图写清名称、说明、例句 —— 模型就靠这些判。冻结成版本、在聊天助手里选这一版才生效。`)}</div>
    </div><div class="acts"><button id="in-new" class="pri">新建意图配置</button></div></div>
    <div id="tbl"><div class="state">加载中…</div></div>`;
  const 新建 = async () => {
    const key = await 问一句("新建意图配置", "给它起一个标识:项目内唯一,建好之后不随意改。", { 输入: "比如 store-intents", 确定: "新建", 必填: true });
    if (!key) return;
    try { const r = await 请求(`${P()}/intents`, { method: "POST", body: JSON.stringify({ key }) }); location.hash = `#/intent/${encodeURIComponent(r.id)}`; }
    catch (e) { 报错(e); }
  };
  $("#in-new").onclick = 新建;
  const 画 = async () => {
    let d;
    try { d = await 请求(`${P()}/intents`); }
    catch (e) { const s = 错误块(e, 画); $("#tbl").innerHTML = s.html; s.挂(); return; }
    const rs = d.items || [];
    if (!rs.length) {
      const s = 状态("", "这个项目还没有意图配置", "没有意图配置时,店长助手不做意图分类。", { 文: "新建意图配置", 做: 新建 });
      $("#tbl").innerHTML = s.html; s.挂(); return;
    }
    $("#tbl").innerHTML = `<table><thead><tr><th>标识</th><th>几个意图</th><th>最新冻结版本</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td><td class="num">${esc(r.本数 ?? 0)}</td>
          <td>${r.最新冻结版本 ? `<span class="pill ok">${esc(r.最新冻结版本)}</span>` : '<span class="pill none">还没冻结过</span>'}</td>
          <td class="num">${时间(r.更新时间)}</td><td><a href="#/intent/${encodeURIComponent(r.id)}">打开编辑</a></td></tr>`).join("")}
      </tbody></table><div class="pager"><span>共 ${rs.length} 份</span></div>`;
  };
  await 画();
}

async function 页_意图详情(iid) {
  $("#main").innerHTML = `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/intents/${encodeURIComponent(iid)}`); }
  catch (e) { const s = 错误块(e, () => 页_意图详情(iid)); $("#main").innerHTML = s.html; s.挂(); return; }
  let rev = d.revision, 脏 = false, 版本们 = d.版本 || [], 配 = JSON.parse(JSON.stringify(d.配置 || {}));
  if (!Array.isArray(配.意图)) 配.意图 = [];
  const 拆 = (t) => [...new Set(String(t || "").split(/[\n\r]+/).map((x) => x.trim()).filter(Boolean))];
  $("#main").innerHTML = `<div class="crumb">查询理解 / <a href="#/intents">意图识别</a> / ${esc(d.key)}</div>
    <div class="head"><div><h1>${esc(d.key)}</h1><div class="sub">草稿 revision <code id="i-rev">${esc(rev)}</code><br>${md(d.note || "")}</div></div></div>
    <div id="i-check"></div>
    <div class="card"><div style="font-weight:600;margin-bottom:6px">意图(<span id="i-n"></span> 个)</div>
      <div class="note">${md(`说明写清「什么情况算这个意图」,例句一行一句 —— 模型靠这些判。分类模型默认 ${d.默认模型 || ""}(最便宜那档)。`)}</div>
      <div id="i-list"></div><div style="margin-top:10px"><button id="i-add">加一个意图</button></div></div>
    <div class="card"><div class="footbar"><span class="msg" id="i-fb"></span><button id="i-back">回列表</button><button id="i-save">保存草稿</button><button id="i-freeze" class="pri">冻结版本</button></div></div>
    <div class="card" id="i-vers"></div>`;
  const 画列表 = () => { $("#i-n").textContent = String(配.意图.length);
    $("#i-list").innerHTML = 配.意图.map((x, i) => `<div class="card"><div class="two">
      <div><label class="f">名称 <span class="req">*</span></label><input class="t" data-i="${i}" data-f="名称" value="${esc(x.名称 || "")}"></div>
      <div><label class="f">对应技能 <span style="color:var(--ink3)">选填</span></label><input class="t" data-i="${i}" data-f="对应技能" value="${esc(x.对应技能 || "")}"></div></div>
      <label class="f">说明 <span class="req">*</span></label><textarea class="t" rows="2" data-i="${i}" data-f="说明">${esc(x.说明 || "")}</textarea>
      <label class="f">例句 <span style="color:var(--ink3)">一行一句</span></label><textarea class="t" rows="3" data-i="${i}" data-f="例句">${esc((x.例句 || []).join("\n"))}</textarea>
      <div style="margin-top:8px;text-align:right"><button class="danger" data-del="${i}">删掉这个</button></div></div>`).join("")
      || 状态("", "还没有意图", "点「加一个意图」开始写。").html; };
  const 画检查 = (检) => { const 阻 = (检 && 检.阻断) || [], 醒 = (检 && 检.提醒) || [];
    $("#i-check").innerHTML = (阻.length ? `<div class="card bad"><div style="font-weight:600;color:var(--fail)">要改完这 ${阻.length} 处才能冻结</div><ul>${阻.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>` : `<div class="note">${md("**检查通过,没有挡住冻结的问题。**")}</div>`)
      + (醒.length ? `<div class="note warn"><ul>${醒.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>` : "")
      + (脏 ? `<div class="k">⚠️ 上面是上次保存的结果,你有没保存的改动。</div>` : ""); };
  const 画版本 = () => { $("#i-vers").innerHTML = `<div style="font-weight:600;margin-bottom:8px">冻结的版本</div>` + (版本们.length
      ? `<table><thead><tr><th>版本</th><th>几个意图</th><th>冻结于</th><th>冻结人</th></tr></thead><tbody>${版本们.map((v) => `<tr><td class="num">${esc(v.版本)}</td><td class="num">${esc(v.本数 ?? "")}</td><td class="num">${时间(v.冻结于)}</td><td>${esc(v.冻结人 || "")}</td></tr>`).join("")}</tbody></table>
        <label class="f">试一句(看模型会收到什么,这里不真调模型)</label><textarea class="t" id="i-tt" rows="2"></textarea>
        <div style="margin-top:8px"><button class="pri" id="i-tgo">试一句</button></div><pre class="io" id="i-tout" hidden></pre>`
      : `<div class="state" style="padding:20px">还没有冻结的版本。</div>`);
    if (版本们.length) $("#i-tgo").onclick = async () => { try { const r = await 请求(`${P()}/intent-versions/${encodeURIComponent(版本们[0].id)}/preview`, { method: "POST", body: JSON.stringify({ 文本: $("#i-tt").value }) });
      const o = $("#i-tout"); o.hidden = false; o.textContent = `【用 ${r.模型}】\n${r.系统提示}\n\n${r.用户消息}`; } catch (e) { 报错(e); } }; };
  const 标脏 = () => { if (!脏) { 脏 = true; 画检查(d.检查); } $("#i-fb").textContent = "有没保存的改动"; };
  $("#i-list").oninput = (e) => { const t = e.target; if (!t.dataset || !t.dataset.f) return; const x = 配.意图[Number(t.dataset.i)]; x[t.dataset.f] = t.dataset.f === "例句" ? 拆(t.value) : t.value; 标脏(); };
  $("#i-list").onclick = async (e) => { const i = e.target.dataset && e.target.dataset.del; if (i === undefined) return;
    if (!(await 问一句("删掉这个意图?", `「${esc(配.意图[Number(i)].名称 || "")}」要点保存草稿才真的存下来。`, { 确定: "删掉" }))) return; 配.意图.splice(Number(i), 1); 标脏(); 画列表(); };
  $("#i-add").onclick = () => { 配.意图.push({ 名称: "", 说明: "", 例句: [] }); 标脏(); 画列表(); };
  $("#i-back").onclick = async () => { if (脏 && !(await 问一句("离开这一页?", "有没保存的改动,离开会丢掉。", { 确定: "丢掉并离开" }))) return; location.hash = "#/intents"; };
  const 存 = async () => { try { const r = await 请求(`${P()}/intents/${encodeURIComponent(iid)}/draft`, { method: "PATCH", headers: { "If-Match": String(rev) }, body: JSON.stringify({ 配置: 配 }) });
      rev = r.revision; $("#i-rev").textContent = String(rev); d.检查 = r.检查; 版本们 = r.版本 || 版本们; 脏 = false; 画检查(r.检查); 画版本(); $("#i-fb").innerHTML = md(r.note || "已保存"); return true;
    } catch (e) { const b = e.体 || {}; $("#i-fb").innerHTML = e.码 === 409 ? `<b>被别人改过了,刷新再合并。</b><details><summary>我这边没保存的内容</summary><pre class="io">${esc(JSON.stringify(配, null, 2))}</pre></details>` : `<b>${esc(b.message || e.message)}</b>`; return false; } };
  $("#i-save").onclick = 存;
  $("#i-freeze").onclick = async () => { if (脏 && !(await 存())) return; try { const r = await 请求(`${P()}/intents/${encodeURIComponent(iid)}/versions`, { method: "POST" }); $("#i-fb").innerHTML = `已冻结为 <b>${esc(r.版本)}</b>`; setTimeout(() => 页_意图详情(iid), 900); }
    catch (e) { const b = e.体 || {}, 阻 = (b.field_errors && b.field_errors.阻断) || []; $("#i-fb").innerHTML = 阻.length ? 阻.map((x) => "· " + md(x)).join("<br>") : `<b>${esc(b.message || e.message)}</b>`; } };
  画列表(); 画检查(d.检查); 画版本();
}

/* 术语表编辑页:逐条增删改 → 保存草稿(If-Match)→ 冻结版本 → 选一个版本试一句话。
 * ⚠️ 检查结果是**上次保存的草稿**的,不是输入框里的 —— 有没保存的改动时要明说,不然人会以为「改完了检查还红」是改错了。 */
async function 页_术语详情(gid) {
  $("#main").innerHTML = `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/glossaries/${encodeURIComponent(gid)}`); }
  catch (e) { const s = 错误块(e, () => 页_术语详情(gid)); $("#main").innerHTML = s.html; s.挂(); return; }
  let rev = d.revision;                  // 乐观锁:每次保存后换成服务端给的新值
  let 脏 = false;
  let 条们 = JSON.parse(JSON.stringify(d.术语 || []));
  let 版本们 = d.版本 || [];
  const 拆叫法 = (s) => [...new Set(String(s || "").split(/[,，、;；\n\r]+/).map((x) => x.trim()).filter(Boolean))];

  $("#main").innerHTML = `
    <div class="crumb">工作室 / <a href="#/glossaries">术语配置</a> / ${esc(d.key)}</div>
    <div class="head"><div>
      <h1>${esc(d.key)}</h1>
      <div class="sub">草稿 revision <code id="g-rev">${esc(rev)}</code> · <span id="g-vcount"></span>
        <br>${md(d.note || "")}</div>
    </div></div>
    <div id="g-check"></div>
    <div class="card">
      <div style="font-weight:600;margin-bottom:6px">术语(<span id="g-n"></span> 条)</div>
      <div class="note">${md("叫法用逗号或回车分开。类别选「指标」时要写**口径**(分子 / 分母 / 时间)—— 不写的话模型会按它自己的理解算;**取数工具**要填项目里真有、而且开着的工具名。")}</div>
      <div id="g-list"></div>
      <div style="margin-top:10px"><button id="g-add">加一条术语</button></div>
      <div class="footbar">
        <span class="msg" id="g-fb"></span>
        <button id="g-back">回列表</button>
        <button id="g-save">保存草稿</button>
        <button id="g-freeze" class="pri">冻结版本</button>
      </div>
    </div>
    <div class="card" id="g-vers"></div>
    <div class="card" id="g-try"></div>`;

  const 画一条 = (t, i) => {
    const 指标 = (t.类别 || "名词") === "指标", 口 = t.口径 || {}, 取 = t.取数口 || {};
    const 框 = (f, 值, 提示) => `<input class="t" data-i="${i}" data-f="${f}" value="${esc(值 || "")}" placeholder="${esc(提示)}">`;
    return `<div class="card" data-row="${i}">
      <div class="two">
        <div><label class="f">标准词 <span class="req">*</span></label>${框("标准词", t.标准词, "比如 到店率")}</div>
        <div><label class="f">类别</label>
          <select class="t" data-i="${i}" data-f="类别">
            <option value="名词"${指标 ? "" : " selected"}>名词(说清是什么)</option>
            <option value="指标"${指标 ? " selected" : ""}>指标(还要说清怎么算)</option></select></div>
      </div>
      <label class="f">叫法 <span style="color:var(--ink3)">店里、客户会怎么说它;逗号或回车分开</span></label>
      <textarea class="t" rows="2" style="min-height:44px" data-i="${i}" data-f="叫法" placeholder="比如 到店转化,预约到店比">${esc((t.叫法 || []).join(","))}</textarea>
      <label class="f">通称 <span style="color:var(--ink3)">好几款共用的名字(比如「圆领袍」),可以同时写在好几条上;说到它时这几条一起带,并提醒先问清是哪一款</span></label>
      <textarea class="t" rows="1" style="min-height:36px" data-i="${i}" data-f="通称" placeholder="选填,比如 圆领袍">${esc((t.通称 || []).join(","))}</textarea>
      <label class="f">定义 <span class="req">*</span></label>
      <textarea class="t" rows="2" style="min-height:44px" data-i="${i}" data-f="定义" placeholder="一句话说清它是什么">${esc(t.定义 || "")}</textarea>
      ${指标 ? `<label class="f">口径 <span class="req">*</span> <span style="color:var(--ink3)">分子 / 分母 / 时间至少写清楚,特殊规定写在「其它」</span></label>
        <div class="two">
          <div>${框("口径.分子", 口.分子, "分子:比如 到店的预约数")}</div>
          <div>${框("口径.分母", 口.分母, "分母:比如 预约数(不含已取消)")}</div>
          <div>${框("口径.时间", 口.时间, "时间:比如 按预约日期")}</div>
          <div>${框("口径.其它", 口.其它, "其它(选填)")}</div>
        </div>
        <label class="f">取数口 <span style="color:var(--ink3)">选填;要算这个数调哪个工具 —— 填了就必须是项目里真有、开着的工具</span></label>
        <div class="two">
          <div>${框("取数口.工具", 取.工具, "工具名:比如 appt_funnel")}</div>
          <div>${框("取数口.说明", 取.说明, "怎么取:比如 按门店 / 周取")}</div>
        </div>` : ""}
      <label class="f">出处 <span style="color:var(--ink3)">选填;这个说法从哪来(制度文件、业务口头约定…)</span></label>
      ${框("出处", t.出处, "比如 门店运营手册 2026 版")}
      <div style="margin-top:8px;text-align:right"><button class="danger" data-del="${i}">删掉这一条</button></div>
    </div>`;
  };
  const 画列表 = () => {
    $("#g-n").textContent = String(条们.length);
    $("#g-list").innerHTML = 条们.length ? 条们.map(画一条).join("")
      : 状态("", "这张表还没有术语", "点下面「加一条术语」开始写。至少要有一条才能冻结版本。").html;
  };
  const 画检查 = (检) => {
    const 阻 = (检 && 检.阻断) || [], 醒 = (检 && 检.提醒) || [];
    const 旧 = 脏 ? `<div class="k">⚠️ 下面是<b>上次保存的草稿</b>的检查结果;你有没保存的改动,保存之后会重新检查。</div>` : "";
    $("#g-check").innerHTML = (阻.length
      ? `<div class="card bad"><div style="font-weight:600;color:var(--fail)">要改完这 ${阻.length} 处才能冻结</div>
          <ul>${阻.map((x) => `<li>${md(x)}</li>`).join("")}</ul>${旧}</div>`
      : `<div class="note">${md("**检查通过,没有挡住冻结的问题。**")}${旧}</div>`)
      + (醒.length ? `<div class="note warn"><b>提醒(不挡冻结,建议看一眼):</b><ul>${醒.map((x) => `<li>${md(x)}</li>`).join("")}</ul></div>` : "");
  };
  const 画版本 = () => {
    $("#g-vcount").innerHTML = 版本们.length ? `已有 ${版本们.length} 个冻结版本(最新 ${esc(版本们[0].版本)})` : "<b>还没冻结过版本</b>";
    $("#g-vers").innerHTML = `<div style="font-weight:600;margin-bottom:8px">冻结的版本</div>`
      + (版本们.length ? `<table><thead><tr><th>版本</th><th>条数</th><th>内容哈希</th><th>冻结于</th><th>冻结人</th></tr></thead><tbody>
          ${版本们.map((v) => `<tr><td class="num">${esc(v.版本)}</td><td class="num">${esc(v.条数 ?? "")}</td>
            <td class="num">${esc(String(v.内容哈希 || "").slice(0, 19))}</td><td class="num">${时间(v.冻结于)}</td><td>${esc(v.冻结人 || "")}</td></tr>`).join("")}
          </tbody></table>
          <div class="note">${md("冻结的版本**内容不再改**。工作流 / Agent 要用哪一版,在它们的配置里选。")}</div>`
        : `<div class="state" style="padding:20px">还没有冻结的版本 —— 上面写好、保存之后点「冻结版本」。</div>`);
    // 「试一下」只摆在有版本的时候 —— 没有版本时摆一个按钮,点了只会被拒,那是死按钮
    $("#g-try").innerHTML = `<div style="font-weight:600;margin-bottom:6px">试一下</div>`
      + (版本们.length ? `<div class="note">${md("输入一句店员或客户会说的话,看这一版会认出哪些术语、**模型实际会收到什么**。和正式运行用的是同一套匹配。")}</div>
          <label class="f">用哪个版本</label>
          <select class="t" id="g-tv">${版本们.map((v) => `<option value="${esc(v.id)}">${esc(v.版本)}(${esc(v.条数 ?? "")} 条 · ${时间(v.冻结于)})</option>`).join("")}</select>
          <label class="f">一句话</label>
          <textarea class="t" id="g-tt" rows="2" style="min-height:44px" placeholder="比如:上周到店转化怎么掉了这么多?"></textarea>
          <div style="margin-top:8px"><button class="pri" id="g-tgo">试一下</button> <span class="k" id="g-tmsg"></span></div>
          <div id="g-tout"></div>`
        : `<div class="state" style="padding:20px">要先冻结一个版本才能试 —— 试的是冻结版本,和流程里真正用的是同一份。</div>`);
    if (版本们.length) $("#g-tgo").onclick = 试一下;
  };
  const 标脏 = () => {
    if (!脏) { 脏 = true; 画检查(d.检查); }
    $("#g-fb").textContent = "有没保存的改动"; $("#g-fb").className = "msg";
  };

  /* 输入框 → 条们(不重画,免得光标跳走);只有切类别 / 增删要重画 */
  const 写回 = (el) => {
    const i = Number(el.dataset.i), f = el.dataset.f, t = 条们[i];
    if (!t || !f) return;
    if (f === "叫法" || f === "通称") t[f] = 拆叫法(el.value);
    else if (f.includes(".")) { const [组, 键] = f.split("."); t[组] = Object.assign({}, t[组] || {}, { [键]: el.value }); }
    else t[f] = el.value;
  };
  $("#g-list").oninput = (e) => { if (e.target && e.target.dataset && e.target.dataset.f) { 写回(e.target); 标脏(); } };
  $("#g-list").onchange = (e) => {
    if (e.target && e.target.dataset && e.target.dataset.f === "类别") { 写回(e.target); 标脏(); 画列表(); }
  };
  $("#g-list").onclick = async (e) => {
    const i = e.target && e.target.dataset ? e.target.dataset.del : undefined;
    if (i === undefined) return;
    const t = 条们[Number(i)] || {};
    if (!(await 问一句("删掉这一条?", `「${esc(t.标准词 || "没写标准词的这条")}」会从草稿里拿掉;要点「保存草稿」才真的存下来。`, { 确定: "删掉", 取消: "留着" }))) return;
    条们.splice(Number(i), 1); 标脏(); 画列表();
  };
  $("#g-add").onclick = () => {
    条们.push({ 标准词: "", 叫法: [], 类别: "名词", 定义: "" }); 标脏(); 画列表();
  };

  /* 存之前整理:空的口径项 / 取数口不发;名词不带口径和取数口(界面上看不到的东西不该悄悄存进去) */
  const 整理 = () => 条们.map((t) => {
    const o = Object.assign({}, t);
    o.标准词 = String(o.标准词 || "").trim(); o.定义 = String(o.定义 || "").trim();
    o.叫法 = 拆叫法((o.叫法 || []).join(","));
    o.通称 = 拆叫法((o.通称 || []).join(",")); if (!o.通称.length) delete o.通称;
    o.类别 = o.类别 || "名词";
    const 清 = (x) => { const r = {}; Object.entries(x || {}).forEach(([k, v]) => { if (String(v || "").trim()) r[k] = String(v).trim(); }); return r; };
    if (o.类别 === "指标") {
      const 口 = 清(o.口径), 取 = 清(o.取数口);
      if (Object.keys(口).length) o.口径 = 口; else delete o.口径;
      if (Object.keys(取).length) o.取数口 = 取; else delete o.取数口;
    } else { delete o.口径; delete o.取数口; }
    if (String(o.出处 || "").trim()) o.出处 = String(o.出处).trim(); else delete o.出处;
    return o;
  });

  $("#g-back").onclick = async () => {
    if (脏 && !(await 问一句("离开这一页?", "有没保存的改动,离开会丢掉。", { 确定: "丢掉并离开", 取消: "留下" }))) return;
    location.hash = "#/glossaries";
  };

  const 存草稿 = async () => {
    try {
      const r = await 请求(`${P()}/glossaries/${encodeURIComponent(gid)}/draft`, {
        method: "PATCH",
        headers: { "If-Match": String(rev) },      // **必填** —— 否则就是「最后写的人赢」,输的人看不到自己被盖掉了
        body: JSON.stringify({ 术语: 整理() }),
      });
      rev = r.revision; $("#g-rev").textContent = String(rev);
      d.检查 = r.检查; 条们 = JSON.parse(JSON.stringify(r.术语 || [])); 版本们 = r.版本 || 版本们;
      脏 = false; 画列表(); 画检查(r.检查); 画版本();
      $("#g-fb").innerHTML = md(r.note || "草稿已保存。"); $("#g-fb").className = "msg";
      return true;
    } catch (e) {
      const b = e.体 || {};
      if (e.码 === 409) {
        // 并发冲突:**不覆盖**。把自己这边没存的内容摆出来,刷新之后照着合并
        $("#g-fb").innerHTML = `<b>这张表被别人改过了,刷新再合并,不要直接覆盖。</b><br>${esc(b.message || "")}
          <br><button id="g-reload">刷新看最新的</button>
          <details><summary>我这边没保存的内容(刷新会丢,先复制下来)</summary><pre class="io">${esc(JSON.stringify(整理(), null, 2))}</pre></details>`;
        $("#g-fb").className = "msg bad";
        $("#g-reload").onclick = () => 页_术语详情(gid);
      } else {
        $("#g-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
        $("#g-fb").className = "msg bad";
      }
      return false;
    }
  };
  $("#g-save").onclick = async () => { $("#g-save").disabled = true; await 存草稿(); $("#g-save").disabled = false; };

  $("#g-freeze").onclick = async () => {
    if (脏) {
      if (!(await 问一句("先保存草稿?", "冻结的是<b>已保存的草稿</b>。你有没保存的改动 —— 先保存,再冻结。", { 确定: "保存并冻结", 取消: "先不冻" }))) return;
      if (!(await 存草稿())) return;
    }
    $("#g-freeze").disabled = true;
    try {
      const r = await 请求(`${P()}/glossaries/${encodeURIComponent(gid)}/versions`, { method: "POST" });
      $("#g-fb").innerHTML = `已冻结为 <b>${esc(r.版本)}</b>(内容哈希 <code>${esc(String(r.内容哈希 || "").slice(0, 19))}</code>)<br>${md(r.note || "")}`;
      $("#g-fb").className = "msg";
      setTimeout(() => 页_术语详情(gid), 900);
    } catch (e) {
      const b = e.体 || {};
      const 阻 = (b.field_errors && b.field_errors.阻断) || [];
      if (e.码 === 422 && 阻.length) {
        $("#g-fb").innerHTML = `<b>还冻不了,先改这 ${阻.length} 处:</b>${阻.map((x) => "<br>· " + md(x)).join("")}`;
      } else if (b.code === "NO_CHANGE") {
        $("#g-fb").innerHTML = `<b>${esc(b.message || "内容和上一版一样")}</b> —— 不用再冻一版。<br>${md(b.advice || "")}`;
      } else {
        $("#g-fb").innerHTML = `<b>${esc(b.message || e.message)}</b><br>${md(b.advice || "")}`;
      }
      $("#g-fb").className = "msg bad";
      $("#g-freeze").disabled = false;
    }
  };

  async function 试一下() {
    const 文 = $("#g-tt").value.trim(), vid = $("#g-tv").value;
    if (!文) { $("#g-tmsg").textContent = "先写一句话。"; return; }
    $("#g-tgo").disabled = true; $("#g-tmsg").textContent = "在试…";
    try {
      const r = await 请求(`${P()}/glossary-versions/${encodeURIComponent(vid)}/preview`, {
        method: "POST", body: JSON.stringify({ 文本: 文 }) });
      const 命 = r.命中 || [];
      // 原句里把命中的那几处加粗(位置按字算;只标服务端报的那几处,页面不自己再找一遍)
      const 字 = Array.from(文), 标 = {};
      命.forEach((h) => { const n = Array.from(String(h.命中的叫法 || "")).length; if (Number.isInteger(h.位置) && n) 标[h.位置] = n; });
      let 句 = "";
      for (let i = 0; i < 字.length;) {
        if (标[i]) { 句 += `<b>${esc(字.slice(i, i + 标[i]).join(""))}</b>`; i += 标[i]; }
        else { 句 += esc(字[i]); i += 1; }
      }
      $("#g-tmsg").textContent = "";
      $("#g-tout").innerHTML = `<label class="f">认出了 ${命.length} 条术语</label>
        <div class="note">${句}</div>
        ${命.length ? `<table><thead><tr><th>标准词</th><th>句子里的说法</th><th>在第几个字</th></tr></thead><tbody>
          ${命.map((h) => `<tr><td>${esc(h.标准词)}</td><td>${esc(h.命中的叫法)}</td><td class="num">${Number.isInteger(h.位置) ? h.位置 + 1 : "—"}</td></tr>`).join("")}
          </tbody></table>` : ""}
        <label class="f">模型会收到</label>
        ${r.模型会收到 ? `<pre class="io">${esc(r.模型会收到)}</pre>`
          : `<div class="note">这句话一条术语都没提到 —— <b>模型这次什么都不会收到</b>。</div>`}
        ${r.note ? `<div class="note">${md(r.note)}</div>` : ""}`;
    } catch (e) {
      const b = e.体 || {};
      $("#g-tmsg").innerHTML = `<b style="color:var(--fail)">${esc(b.message || e.message)}</b>${b.advice ? " " + md(b.advice) : ""}`;
    }
    $("#g-tgo").disabled = false;
  }

  画列表(); 画检查(d.检查); 画版本();
}

/* ── 监测(11-04;Dify 对标 §8.1 / DF-04)────────────────────────────────────────────
 * **口径全在服务端**(monitoring_api):办成 = 跑完 + 每处写入都有澜绣回执(用户拍);分母是 0 显示「—」不显示 0%;
 * 算不出金额的单独数、费用写「至少」。页面只负责把同一个筛选同时作用到所有卡片上,不另算一遍。 */
let 监测筛 = { 范围: "业务", 天: 7 };
async function 页_监测() {
  const 头 = `<div class="crumb">日志与监测 / 监测</div><div class="head"><div><h1>监测</h1>
    <div class="sub">${md("按应用 / 环境 / 版本 / 入口看运行、办成和花费。**办成 = 跑完 + 每一处写入都拿到澜绣的回执**;等人核对的不算失败也不算成功;算不出的显示「—」,不显示 0。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const q = Object.entries(监测筛).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  let d;
  try { d = await 请求(`${P()}/monitoring?${q}`); }
  catch (e) { const s = 错误块(e, 页_监测); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 率 = (v, 分母) => v == null ? `— <span class="k">(分母 0,未知)</span>` : `${esc(String(v))}% <span class="k">(分母 ${esc(String(分母))})</span>`;
  const 秒 = (x) => x["P50秒"] == null ? "—" : `P50 ${esc(String(x["P50秒"]))}s · P95 ${esc(String(x["P95秒"]))}s <span class="k">(${esc(String(x["样本数"]))} 条${x["样本少"] ? ",样本少" : ""})</span>`;
  const 选 = (名, 值们) => `<label class="f">${esc(名)}</label><select data-monf="${esc(名)}"><option value="">全部</option>`
    + 值们.map((v) => `<option${String(监测筛[名] ?? "") === String(v) ? " selected" : ""}>${esc(String(v))}</option>`).join("") + `</select>`;
  const 可 = d["可用性"], 业 = d["业务"], 性 = d["性能"], 本 = d["成本"];
  $("#main").innerHTML = 头 + `<div>${["业务", "调试", "全部"].map((t) => `<button data-monscope="${t}"${t === 监测筛.范围 ? ' class="on"' : ""}>${t}</button>`).join(" ")}
      ${[1, 7, 30].map((n) => `<button data-mondays="${n}"${n === 监测筛.天 ? ' class="on"' : ""}>${n} 天</button>`).join(" ")}</div>
    <div>${选("应用", d["可选"]["应用"])}${选("版本", d["可选"]["版本"])}${选("环境", d["可选"]["环境"])}${选("入口", d["可选"]["入口"])}</div>
    ${d.note ? `<div class="note">${md(d.note)}</div>` : ""}
    <h2>可用性</h2><table><tbody>
      <tr><td class="k">接收</td><td>${esc(String(可["接收"]))}</td><td class="k">终态成功率</td><td>${率(可["终态成功率"], 可["终态成功率分母"])}</td></tr>
      <tr><td class="k">跑完 / 失败 / 取消 / 没做完</td><td>${[可["跑完"], 可["失败"], 可["取消"], 可["没做完"]].join(" / ")}</td>
          <td class="k">进行中 / 等人核对 / 等澜绣执行</td><td>${[可["进行中"], 可["等人核对"], 可["等澜绣执行"]].join(" / ")}</td></tr></tbody></table>
    <h2>业务办成</h2><table><tbody>
      <tr><td class="k">办成</td><td>${esc(String(业["办成"]))}</td><td class="k">写入办成率</td><td>${率(业["写入办成率"], 业["写入办成率分母"])}</td></tr>
      <tr><td class="k">跑完·没证实</td><td>${esc(String(业["跑完·没证实"]))}</td><td class="k">跑完·这次不需要写入</td><td>${esc(String(业["跑完·这次不需要写入"]))}</td></tr></tbody></table>
    <h2>性能</h2><table><tbody><tr><td class="k">端到端</td><td>${秒(性["端到端"])}</td><td class="k">排队</td><td>${秒(性["排队"])}</td></tr></tbody></table>
    <h2>成本</h2><table><tbody>
      <tr><td class="k">已知费用</td><td>${本["是至少吗"] ? "至少 " : ""}$${esc(String(本["已知费用"]))}${本["算不出金额的笔数"] ? ` <span class="k">另有 ${esc(String(本["算不出金额的笔数"]))} 笔算不出</span>` : ""}</td>
          <td class="k">每个办成任务</td><td>${本["每个办成任务成本"] == null ? `— <span class="k">(没有办成的,未知)</span>` : `${本["是至少吗"] ? "至少 " : ""}$${esc(String(本["每个办成任务成本"]))}`}</td></tr>
      <tr><td class="k">token</td><td>${esc(String(本["token"]))}</td><td></td><td></td></tr></tbody></table>
    <h2>按应用 × 版本</h2>
    ${(d["分组"] || []).length ? `<table><thead><tr><th>应用</th><th>版本</th><th>接收</th><th>终态成功率</th><th>办成</th><th>写入办成率</th><th>已知费用</th></tr></thead><tbody>`
      + d["分组"].map((g) => `<tr><td>${esc(String(g["应用"] || "—"))}</td><td>${g["版本"] == null ? "—" : "v" + esc(String(g["版本"]))}</td>
          <td>${esc(String(g["接收"]))}${g["样本少"] ? ' <span class="k">样本少</span>' : ""}</td><td>${率(g["终态成功率"], g["终态"])}</td>
          <td>${esc(String(g["办成"]))}</td><td>${率(g["写入办成率"], g["有写入的跑完"])}</td><td>$${esc(String(g["已知费用"]))}${g["算不出笔数"] ? " 起" : ""}</td></tr>`).join("") + `</tbody></table>`
      : 状态("", "这个范围里没有运行", "换个时间窗或范围看看;「调试」里是连接测试和 mock 跑的那些。").html}
    <div class="k">更新于 ${esc(String(d["更新时刻"]).slice(0, 19).replace("T", " "))}</div>`;
  $("#main").querySelectorAll("[data-monscope]").forEach((b) => { b.onclick = () => { 监测筛.范围 = b.dataset.monscope; 页_监测(); }; });
  $("#main").querySelectorAll("[data-mondays]").forEach((b) => { b.onclick = () => { 监测筛.天 = +b.dataset.mondays; 页_监测(); }; });
  $("#main").querySelectorAll("[data-monf]").forEach((sel) => { sel.onchange = () => { 监测筛[sel.dataset.monf] = sel.value; 页_监测(); }; });
}

/* ── 告警(11-04;DF-04 第二步 / C16;用户拍:连续 N 次越线才报、连续 M 次正常才恢复、样本不够那轮不算)──────────
 * 判定全在服务端(alert_rules.下一步)。建规则时**每一项都要填**:阈值和次数是产品配置,页面不替人填默认数。
 * 站内待办能跳回监测页看开单那一窗(同一组筛选)。外部通知这一版不做,页面上也不摆那个开关。 */
async function 页_告警() {
  const 头 = `<div class="crumb">日志与监测 / 告警</div><div class="head"><div><h1>告警</h1>
    <div class="sub">${md("**连续 N 次越线才报、连续 M 次正常才自动恢复**;样本不够最小样本量的那一轮不算。每 5 分钟评估一次,只开站内待办(外部通知这一版不做)。阈值和次数都是你们定的产品配置,不是行业标准。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let 规, 单;
  try { [规, 单] = await Promise.all([请求(`${P()}/alert-rules`), 请求(`${P()}/alert-incidents`)]); }
  catch (e) { const s = 错误块(e, 页_告警); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 单表 = !(单.items || []).length ? `<div class="note">现在没有告警待办。</div>`
    : `<table><thead><tr><th>开单时间</th><th>规则</th><th>状态</th><th>开单那一窗</th><th></th></tr></thead><tbody>`
      + 单.items.map((x) => { const 窗 = x["开单那一窗"] || {};
        return `<tr><td class="k">${esc(String(x["开单时间"]).slice(5, 16).replace("T", " "))}</td><td>${esc(x["规则名"])}<div class="k">${esc(x["指标"])} ${esc(x["条件"])}</div></td>
          <td>${x["状态"] === "触发中" ? '<span class="pill fail">触发中</span>' : `<span class="pill">${esc(x["状态"])}</span>`}${x["又提醒了几次"] ? `<div class="k">又提醒 ${esc(String(x["又提醒了几次"]))} 次</div>` : ""}</td>
          <td>值 ${esc(String(窗["值"] ?? "—"))} · ${esc(String(窗["样本"] ?? 0))} 条 · 最近 ${esc(String(窗["窗口分钟"] || ""))} 分钟
            <div><button data-alrdrill="${esc(x.id)}">去监测页看这一窗</button></div></td>
          <td>${x["状态"] === "已处理" ? esc(x["处理说明"] || "") : `<input data-alrnote="${esc(x.id)}" placeholder="怎么处理的(必填)"> <button data-alrhandle="${esc(x.id)}">标已处理</button>`}</td></tr>`; }).join("") + `</tbody></table>`;
  const 规表 = !(规.items || []).length ? `<div class="note">还没有告警规则。</div>`
    : `<table><thead><tr><th>规则</th><th>条件</th><th>判法</th><th>现在</th><th></th></tr></thead><tbody>`
      + 规.items.map((r) => `<tr><td>${esc(r["名字"])}<div class="k">${esc(JSON.stringify(r["筛选"] || {}))}</div></td>
          <td>${esc(r["指标"])} ${esc(r["方向"])} ${esc(String(r["阈值"]))} · 最近 ${esc(String(r["窗口分钟"]))} 分钟 · 至少 ${esc(String(r["最小样本"]))} 条</td>
          <td>连续 ${esc(String(r["连续越线才报"]))} 次才报 · 连续 ${esc(String(r["连续正常才恢复"]))} 次正常才恢复 · ${esc(String(r["去重分钟"]))} 分钟内不重复提醒</td>
          <td>${r["暂停了吗"] ? "暂停中" : r["触发中"] ? '<span class="pill fail">触发中</span>' : "正常"}<div class="k">${esc((r["上次评估结果"] || {})["结论"] || "还没评估过")}</div></td>
          <td><button data-alreval="${esc(r.id)}">立即评估</button> <button data-alrpause="${esc(r.id)}" data-rev="${esc(String(r.revision))}" data-to="${r["暂停了吗"] ? "0" : "1"}">${r["暂停了吗"] ? "恢复评估" : "暂停"}</button></td></tr>`).join("") + `</tbody></table>`;
  const 指标们 = ["终态成功率", "写入办成率", "失败次数", "端到端P95秒", "每个办成任务成本", "算不出金额笔数", "门店月费用", "意见超时条数", "日志用量占比"];   // 门店月费用:值从聊天站门店用量账取(11-13),澜绣项目由 worker 自动种一条
  $("#main").innerHTML = 头 + `<h2>待办</h2>${单表}<h2>规则</h2>${规表}
    <h3>建一条规则(每一项都要填)</h3>
    <label class="f">名字</label><input id="alr-n" placeholder="比如:回电流程成功率掉了">
    <label class="f">只看哪个应用(选填,不填 = 全部)</label><input id="alr-app" placeholder="应用 id,监测页里能看到">
    <label class="f">指标</label><select id="alr-m">${指标们.map((m) => `<option>${esc(m)}</option>`).join("")}</select>
    <label class="f">方向 / 阈值</label><select id="alr-d"><option>低于</option><option>高于</option></select> <input id="alr-th" placeholder="比如 90">
    <label class="f">窗口(分钟,5–10080)/ 最小样本</label><input id="alr-w" placeholder="比如 60"> <input id="alr-ms" placeholder="比如 20">
    <label class="f">连续几次越线才报 / 连续几次正常才恢复(1–20)</label><input id="alr-tc" placeholder="比如 3"> <input id="alr-rc" placeholder="比如 2">
    <label class="f">去重周期(分钟,5–10080)</label><input id="alr-dm" placeholder="比如 60">
    <div><button class="pri" id="alr-new">建规则</button> <span class="k" id="alr-why"></span></div>`;
  $("#alr-new").onclick = async () => {
    const v = (id) => ($("#" + id).value || "").trim();
    const 体 = { 名字: v("alr-n"), 筛选: v("alr-app") ? { 范围: "业务", 应用: v("alr-app") } : { 范围: "业务" }, 指标: v("alr-m"), 方向: v("alr-d"),
      阈值: v("alr-th"), 窗口分钟: v("alr-w"), 最小样本: v("alr-ms"), 连续越线才报: v("alr-tc"), 连续正常才恢复: v("alr-rc"), 去重分钟: v("alr-dm") };
    try { await 请求(`${P()}/alert-rules`, { method: "POST", body: JSON.stringify(体) }); 页_告警(); }
    catch (e) { $("#alr-why").textContent = "没建上:" + ((e.体 && (e.体.message + " " + Object.values(e.体.field_errors || {}).join(";"))) || e.message); }
  };
  $("#main").querySelectorAll("[data-alreval]").forEach((b) => { b.onclick = async () => {
    try { const r = await 请求(`${P()}/alert-rules/${encodeURIComponent(b.dataset.alreval)}/evaluate`, { method: "POST", body: "{}" }); 提示(`评估了一次:${r["动作"]}`, esc(r["为什么"] || "")); 页_告警(); }
    catch (e) { 报错(e); } }; });
  $("#main").querySelectorAll("[data-alrpause]").forEach((b) => { b.onclick = async () => {
    try { await 请求(`${P()}/alert-rules/${encodeURIComponent(b.dataset.alrpause)}/pause`, { method: "POST", headers: { "If-Match": b.dataset.rev }, body: JSON.stringify({ 暂停: b.dataset.to === "1" }) }); 页_告警(); }
    catch (e) { 报错(e); } }; });
  $("#main").querySelectorAll("[data-alrhandle]").forEach((b) => { b.onclick = async () => {
    const 话 = (([...document.querySelectorAll("[data-alrnote]")].find((e) => e.dataset.alrnote === b.dataset.alrhandle) || {}).value || "").trim();
    try { await 请求(`${P()}/alert-incidents/${encodeURIComponent(b.dataset.alrhandle)}/handle`, { method: "POST", body: JSON.stringify({ 说明: 话 }) }); 页_告警(); }
    catch (e) { 报错(e); } }; });
  $("#main").querySelectorAll("[data-alrdrill]").forEach((b) => { b.onclick = () => {
    const x = (单.items || []).find((i) => i.id === b.dataset.alrdrill) || {}, 筛 = (x["开单那一窗"] || {})["筛选"] || {};
    监测筛 = Object.assign({ 范围: "业务", 天: 1 }, 筛); location.hash = "#/monitoring"; }; });
}

/* ── 意见受理(11-04;意见收集 PRD §4.1 / §5.1;用户拍:总部运营统一受理、1 个工作日首次处理、跳周末和法定假日)──
 * 清单:待受理排前,超时标红(**只标红,不当成已解决**)。详情:原话、时间线、这一步能做的动作 ——
 * 动作按钮照接口给的「能做的动作」画,页面不另写一份流转规则(两份迟早分叉)。 */
/* ── 知识修订申请(11-17,W28):谁都能提、只总部运营审、采纳生成带注记的改动文本、开发改 md 后标已合并 ── */
async function 页_知识修订清单(筛 = "") {
  const 头 = `<div class="crumb">日志与监测 / 知识修订</div>
    <div class="head"><div><h1>知识修订申请</h1>
      <div class="sub">${md("门店对 knowledge/*.md 里某一段口径提修订。**只总部运营审**(三家店各审会审出三个版本);审过不直接改文件 —— 生成一段带括号注记的改动文本,由开发改 md、过门禁,再标「已合并」。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d, 文件;
  try {
    d = await 请求(`${P()}/knowledge-revisions?limit=100` + (筛 ? `&status=${encodeURIComponent(筛)}` : ""));
    文件 = await 请求(`${P()}/knowledge-revisions/files`);
  } catch (e) { const s = 错误块(e, () => 页_知识修订清单(筛)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 筛条 = `<div>` + ["", ...(d.状态们 || [])].map((t) => `<button data-krf="${esc(t)}"${t === 筛 ? ' class="on"' : ""}>${esc(t || "全部")}</button>`).join("") + `</div>`;
  const 表 = !d.items.length ? 状态("", "还没有修订申请", "下面可以提一条:指到哪份 md、哪一段,原来写的那句从文件里原样复制。").html
    : `<table><thead><tr><th>什么时候</th><th>文件 · 段</th><th>原来写的 → 改成</th><th>提的人</th><th>状态</th><th></th></tr></thead><tbody>`
      + d.items.map((x) => `<tr>
          <td class="k">${esc(String(x.提交时刻 || "").slice(5, 16).replace("T", " "))}</td>
          <td>${esc(x.知识文件)}<div class="k"><span data-raw="原文">${esc(x.段)}</span></div></td>
          <td><span data-raw="原文">${esc(String(x.原来写的 || "").slice(0, 40))}</span><div class="k">→ <span data-raw="原文">${esc(String(x.改成 || "").slice(0, 40))}</span></div></td>
          <td class="k">${esc(x.提的人)}</td>
          <td>${x.状态 === "待审" ? '<span class="pill warn">' : '<span class="pill">'}${esc(x.状态)}</span></td>
          <td><button data-kropen="${esc(x.id)}">打开</button></td></tr>`).join("") + `</tbody></table>`;
  const 提 = `<h2>提一条修订</h2>
    <div><select id="kr-file"><option value="">选文件</option>${(文件.文件们 || []).map((f) => `<option>${esc(f)}</option>`).join("")}</select>
      <select id="kr-sec"><option value="">先选文件再选段</option></select></div>
    <textarea id="kr-cur" rows="2" placeholder="原来写的(从文件里原样复制一句,至少 4 字)" style="width:100%"></textarea>
    <textarea id="kr-new" rows="2" placeholder="改成什么" style="width:100%"></textarea>
    <input id="kr-why" placeholder="依据(史料 / 标准 / 业务拍板,至少 4 字)" style="width:100%">
    <div><button id="kr-go">提交</button> <span class="k" id="kr-msg"></span></div>`;
  $("#main").innerHTML = 头 + 筛条 + 表 + 提;
  $("#main").querySelectorAll("[data-krf]").forEach((b) => { b.onclick = () => 页_知识修订清单(b.dataset.krf); });
  $("#main").querySelectorAll("[data-kropen]").forEach((b) => { b.onclick = () => { location.hash = "#/knowledge-revision/" + encodeURIComponent(b.dataset.kropen); }; });
  $("#kr-file").onchange = async () => {
    const f = $("#kr-file").value; const sel = $("#kr-sec");
    sel.innerHTML = `<option value="">选段</option>`;
    if (!f) return;
    try { const r = await 请求(`${P()}/knowledge-revisions/files?file=${encodeURIComponent(f)}`);
      sel.innerHTML += (r.段 || []).map((s) => `<option>${esc(s)}</option>`).join(""); } catch (e) { $("#kr-msg").textContent = String(e.message || e); }
  };
  $("#kr-go").onclick = async () => {
    $("#kr-msg").textContent = "提交中…";
    try {
      await 请求(`${P()}/knowledge-revisions`, { method: "POST", body: JSON.stringify({
        知识文件: $("#kr-file").value, 段: $("#kr-sec").value, 原来写的: $("#kr-cur").value, 改成: $("#kr-new").value, 依据: $("#kr-why").value }) });
      页_知识修订清单(筛);
    } catch (e) { const fe = (e.体 || {}).field_errors; $("#kr-msg").textContent = (fe ? Object.entries(fe).map(([k, v]) => `${k}:${v}`).join(";") : "") || String(e.message || e); }
  };
}

async function 页_知识修订详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/knowledge-revisions">知识修订</a> / ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/knowledge-revisions/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_知识修订详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  /* 原来写的 / 改成 / 段名 / 改动文本 都是 knowledge/*.md 的原文(本身就是 Markdown,常带 **),
   * 要能逐字对回源文件,所以原样显示并标 data-raw="原文" —— 冒烟的「字面星号」判据对它豁免(11-18 远端冒烟红在这)。 */
  const kv原文 = (k, v) => `<tr><td class="k">${esc(k)}</td><td data-raw="原文">${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  const 动作 = d.能做的动作 || [];
  const 钮 = 动作.map((a) => `<button data-kract="${esc(a)}">${esc(a)}</button>`).join(" ");
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>${esc(d.知识文件)} · <span data-raw="原文">${esc(d.段)}</span></h1>
      <div class="sub">提的人 ${esc(d.提的人)} · 状态 <b>${esc(d.状态)}</b></div></div></div>
    <table><tbody>${kv原文("原来写的", d.原来写的)}${kv原文("改成", d.改成)}${kv("依据", d.依据)}
      ${kv("审的人 / 时刻", d.审的人 ? `${d.审的人} · ${String(d.审的时刻 || "").slice(0, 16).replace("T", " ")}` : "")}${kv("审核说明", d.审核说明)}
      ${kv("合并的人 / 时刻", d.合并的人 ? `${d.合并的人} · ${String(d.合并时刻 || "").slice(0, 16).replace("T", " ")}` : "")}</tbody></table>
    ${d.改动文本 ? `<h2>改动文本(给开发)</h2><pre data-raw="原文">${esc(d.改动文本)}</pre>` : ""}
    ${钮 ? `<h2>处理</h2><textarea id="kr-act-note" rows="2" placeholder="说明(驳回必填,提的人看得到)"></textarea><div>${钮}</div><div class="k" id="kr-act-why"></div>` : `<div class="note">这一步没有能做的动作(已是终态)。</div>`}`;
  $("#main").querySelectorAll("[data-kract]").forEach((b) => {
    b.onclick = async () => {
      const a = b.dataset.kract; const 说明 = $("#kr-act-note").value;
      try {
        if (a === "已合并") await 请求(`${P()}/knowledge-revisions/${encodeURIComponent(id)}/merged`, { method: "POST", body: "{}" });
        else await 请求(`${P()}/knowledge-revisions/${encodeURIComponent(id)}/review`, { method: "POST", body: JSON.stringify({ 决定: a, 说明 }) });
        页_知识修订详情(id);
      } catch (e) { const fe = (e.体 || {}).field_errors; $("#kr-act-why").textContent = (fe ? Object.entries(fe).map(([k, v]) => `${k}:${v}`).join(";") : "") || String(e.message || e); }
    };
  });
}

async function 页_意见受理(页 = 1, 筛 = "") {
  const 头 = `<div class="crumb">日志与监测 / 意见受理</div>
    <div class="head"><div><h1>意见受理</h1>
      <div class="sub">${md("聊天站里提的意见。**分三级第一次处理**:紧急(影响业务办理)4 个工作小时、一般 2 个工作日、建议 7 天(工作时间跳过周末和法定假日),超时标红、告警页同时开一条待办。「有帮助」是提的人自己的感受,**不是准确率**。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/opinions?limit=30&page=${页}` + (筛 ? `&status=${encodeURIComponent(筛)}` : "")); }
  catch (e) { const s = 错误块(e, () => 页_意见受理(页, 筛)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 态们 = ["", "待受理", "待补充", "核实中", "已关联问题", "已答复", "不采纳", "已撤回"];
  const 筛条 = `<div>` + 态们.map((t) => `<button data-opf="${esc(t)}"${t === 筛 ? ' class="on"' : ""}>${esc(t || "全部")}</button>`).join("") + `</div>`;
  const 超 = d.items.filter((x) => x.超时).length;
  const 表 = !d.items.length ? 状态("", "还没有意见", "聊天站回答下面点「反馈问题」、左栏「意见与建议」提的都会到这里。").html
    : (超 ? `<div class="note">${md(`**这一页有 ${超} 条超时还没处理。**`)}</div>` : "")
      + `<table><thead><tr><th>什么时候</th><th>谁提的</th><th>来源 · 评价</th><th>说了什么</th><th>状态</th><th>首次处理截止</th><th></th></tr></thead><tbody>`
      + d.items.map((x) => `<tr>
          <td class="k">${esc(String(x.提交时间 || "").slice(5, 16).replace("T", " "))}</td>
          <td>${esc((x.提问人 || {}).姓名 || (x.提问人 || {}).工号 || "")}<div class="k">${esc((x.提问人 || {}).门店 || "")}</div></td>
          <td>${esc(x.来源)} · ${esc(x.评价)}${x.问题类型 ? `<div class="k">${esc(x.问题类型)}</div>` : ""}</td>
          <td>${esc(String(x.说明 || "").slice(0, 60))}</td>
          <td>${x.状态 === "待受理" ? '<span class="pill warn">' : '<span class="pill">'}${esc(x.状态)}</span></td>
          <td class="k">${x.级别 ? `<span class="pill">${esc(x.级别)}</span> ` : ""}${x.超时 ? `<span class="pill fail">超时</span> ` : ""}${esc(String(x.首次处理截止 || "—").slice(5, 16).replace("T", " "))}
            ${x.截止依据 && x.截止依据 !== "2026放假表" ? `<div class="k">${esc(x.截止依据)}</div>` : ""}</td>
          <td><button data-opopen="${esc(x.id)}">处理</button></td></tr>`).join("") + `</tbody></table>`;
  $("#main").innerHTML = 头 + 筛条 + 表 + 页码条(d);
  $("#main").querySelectorAll("[data-opf]").forEach((b) => { b.onclick = () => 页_意见受理(1, b.dataset.opf); });
  $("#main").querySelectorAll("[data-opopen]").forEach((b) => { b.onclick = () => { location.hash = "#/opinion/" + encodeURIComponent(b.dataset.opopen); }; });
  挂页码($("#main"), (n) => 页_意见受理(n, 筛));
}

async function 页_意见详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/opinions">意见受理</a> / ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/opinions/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_意见详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  const 人 = d.提问人 || {};
  const 钮 = (d.能做的动作 || []).map((a) => `<button data-opact="${esc(a.动作)}">${esc(a.动作)} → ${esc(a.到)}</button>`).join(" ");
  // 11-12 问题单:「关联问题」要指定一张单(接口用「要指定问题单」告诉页面);也可以从这条意见直接建一张并关联
  const 能关联 = (d.能做的动作 || []).some((a) => a.要指定问题单);
  const 单 = d.问题单;
  const 单块 = 单 ? `<div class="note">${md(`已关联问题单 **${单.标题}**,问题单现在是「**${单.状态}**」`
      + (单.指向主问题 ? `(这张是重复单,主问题 \`${单.指向主问题}\` 现在是「${单.主问题状态 || "?"}」)` : ""))}
      <a href="#/issue/${encodeURIComponent(单.id)}">打开问题单</a></div>` : "";
  const 关联块 = 能关联 ? `<div>关联到已有问题单:<input id="op-act-issue" placeholder="问题单编号(is_…)">(填了再点「关联问题」)</div>
      <h2>从这条意见建问题单</h2>
      <input id="op-is-title" placeholder="问题单标题(必填)" style="width:100%">
      <div><button id="op-is-new">建问题单并关联</button> <span class="k" id="op-is-why"></span></div>` : "";
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>${esc(d.评价)}${d.问题类型 ? " · " + esc(d.问题类型) : ""}</h1>
      <div class="sub">${esc(d.来源)} · ${esc(人.姓名 || 人.工号 || "")} ${esc(人.角色 || "")} ${esc(人.门店 || "")} · 状态 <b>${esc(d.状态)}</b>
        ${d.超时 ? ' · <span class="pill fail">超时未处理</span>' : ""}</div></div></div>
    <table><tbody>${kv("哪里有问题 / 建议", d.说明)}${kv("期望的结果(候选,不是真值)", d.期望结果)}${kv("影响", d.影响)}
      ${kv("首次处理截止", String(d.首次处理截止 || "").slice(0, 16).replace("T", " ") + (d.截止依据 ? `(${d.截止依据})` : ""))}
      ${kv("首次处理时刻", d.首次处理时刻 && String(d.首次处理时刻).slice(0, 16).replace("T", " "))}
      ${kv("给提的人的答复", d.答复)}${kv("改过几次", (d.改之前的版本 || []).length)}</tbody></table>
    ${d.管理后台trace ? `<button data-optrace="${esc(d.管理后台trace)}">看这一轮的调用树</button>`
      : d.聊天站trace ? `<div class="note">${md("这一轮的执行记录**还没推过来**,推过来之后这里会出现调用树入口。")}</div>` : ""}
    ${单块}
    <h2>处理</h2>
    ${钮 ? `<textarea id="op-act-note" rows="2" placeholder="说明:不采纳 / 答复 / 请求补充 / 重开 / 重新归并要写;答复、不采纳、请求补充写的这句话提的人看得到"></textarea>
      <div>${钮}</div><div class="k" id="op-act-why"></div>${关联块}` : `<div class="note">这一步没有能做的动作(已是终态)。</div>`}
    <h2>评测样本</h2>
    ${d.样本 ? `<div class="note">${md(`已提成样本 \`${d.样本.id}\` · 复核状态 **${d.样本.复核状态}**`
        + (d.样本.复核状态 === "待复核" ? "(等提问人所在门店的店长在聊天站里复核;**复核通过之前它不算标准答案**)" : ""))}</div>` : ""}
    ${d.能提样本 ? `<div class="sub">${md("把这条意见变成一道评测题:**题面和标准答案由你写**(意见单不存原话,看调用树里的原文再写)。提的人写的「期望结果」只是候选。")}</div>
      <input id="op-sm-q" placeholder="题面:这道题问的是什么" style="width:100%">
      <textarea id="op-sm-a" rows="2" placeholder="标准答案(必填)" style="width:100%">${esc(d.期望结果 || "")}</textarea>
      <input id="op-sm-n" placeholder="说明(选填)" style="width:100%">
      <div><button id="op-sm-send">提为样本</button> <span class="k" id="op-sm-why"></span></div>` : ""}
    <h2>时间线</h2>
    ${(d.时间线 || []).length ? `<table><thead><tr><th>什么时候</th><th>谁</th><th>动作</th><th>从 → 到</th><th>说明</th></tr></thead><tbody>`
      + d.时间线.map((e) => `<tr><td class="k">${esc(String(e.时间).slice(5, 16).replace("T", " "))}</td><td>${esc(e.谁 || "")}</td>
          <td>${esc(e.动作)}</td><td>${esc(e.从 || "")} → ${esc(e.到)}</td><td>${esc(e.说明 || "")}</td></tr>`).join("") + `</tbody></table>`
      : `<div class="note">还没有人处理过。</div>`}`;
  $("#main").querySelectorAll("[data-optrace]").forEach((b) => { b.onclick = () => { location.hash = "#/trace/" + encodeURIComponent(b.dataset.optrace); }; });
  if ($("#op-sm-send")) $("#op-sm-send").onclick = async () => {
    const 题 = ($("#op-sm-q").value || "").trim(), 答 = ($("#op-sm-a").value || "").trim(), 注 = ($("#op-sm-n").value || "").trim();
    if (!题 || !答) { $("#op-sm-why").textContent = "题面和标准答案都要写"; return; }
    $("#op-sm-send").disabled = true;
    try {
      await 请求(`${P()}/opinions/${encodeURIComponent(id)}/promote`,
        { method: "POST", headers: { "If-Match": String(d.revision) }, body: JSON.stringify({ 题面: 题, 期望答案: 答, 说明: 注 }) });
      页_意见详情(id);
    } catch (e) { $("#op-sm-send").disabled = false; $("#op-sm-why").textContent = "没提上:" + ((e.体 && (e.体.message + " " + (e.体.advice || ""))) || e.message); }
  };
  $("#main").querySelectorAll("[data-opact]").forEach((b) => {
    b.onclick = async () => {
      const 话 = ($("#op-act-note") || {}).value || "";
      // 11-08 用户拍:「不采纳」「答复」写的话提意见的人看得到 → 先确认
      if (["不采纳", "答复"].includes(b.dataset.opact) && !(await 问一句(`确定${b.dataset.opact}?`, `提意见的人会看到这个决定${话 ? "和你写的这句话" : ""}。`, { 确定: b.dataset.opact }))) return;
      const 体 = { 动作: b.dataset.opact, 说明: 话 };
      const 这步 = (d.能做的动作 || []).find((a) => a.动作 === b.dataset.opact) || {};
      if (这步.要指定问题单) 体.问题单 = (($("#op-act-issue") || {}).value || "").trim();
      b.disabled = true;
      try {
        await 请求(`${P()}/opinions/${encodeURIComponent(id)}/actions`,
          { method: "POST", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
        页_意见详情(id);
      } catch (e) { b.disabled = false; $("#op-act-why").textContent = "没处理上:" + ((e.体 && (e.体.message + " " + (e.体.advice || ""))) || e.message); }
    };
  });
  if ($("#op-is-new")) $("#op-is-new").onclick = async () => {
    const 题 = ($("#op-is-title").value || "").trim();
    if (!题) { $("#op-is-why").textContent = "标题要写"; return; }
    $("#op-is-new").disabled = true;
    try {
      const r = await 请求(`${P()}/issues`, { method: "POST",
        body: JSON.stringify({ 标题: 题, 来自意见: id, 意见revision: d.revision, 说明: ($("#op-act-note") || {}).value || null }) });
      location.hash = "#/issue/" + encodeURIComponent(r.id);
    } catch (e) { $("#op-is-new").disabled = false; $("#op-is-why").textContent = "没建上:" + ((e.体 && (e.体.message + " " + (e.体.advice || ""))) || e.message); }
  };
}

/* ── 问题单(11-12;意见收集 PRD §4.2 / §5.2)──
 * 意见是用的人说的话,问题单是要修的那件事。流转表只在后端 issue_flow.py:
 * 按钮照详情接口给的「能做的动作」画(连这一步要写说明 / 要带什么字段也是接口说的),筛选条照清单接口给的「可选状态」画 ——
 * 页面不另抄一份。处理时限过了不标超时(PRD §10 待定)。
 * 11-12 改进验证与发布(PRD §4.3):验证通过 / 发布生效 / 关闭 的前置条件由接口查,页面只把它给的那句话写在按钮下面;
 * 「验证记录」「发布记录」两个字段画成下拉,选项是这张单上待验证 / 待生效的那几条。 */
async function 页_问题单清单(页 = 1, 筛 = {}) {
  const 头 = `<div class="crumb">日志与监测 / 问题单</div>
    <div class="head"><div><h1>问题单</h1>
      <div class="sub">${md("要修的那件事。多条意见可以并进同一张单;**已解决只算「已验证关闭」**,已搁置不算。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  const 查 = (筛.状态 ? `&status=${encodeURIComponent(筛.状态)}` : "") + (筛.根因 ? `&root_cause=${encodeURIComponent(筛.根因)}` : "");
  try { d = await 请求(`${P()}/issues?limit=30&page=${页}` + 查); }
  catch (e) { const s = 错误块(e, () => 页_问题单清单(页, 筛)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 条 = (名, 值们, 当前) => `<div>${esc(名)}:` + [""].concat(值们 || []).map((t) =>
    `<button data-isf-k="${esc(名)}" data-isf="${esc(t)}"${t === (当前 || "") ? ' class="on"' : ""}>${esc(t || "全部")}</button>`).join("") + `</div>`;
  const 建 = `<h2>新建问题单</h2>
    <input id="is-new-title" placeholder="标题:一句话说清是什么问题(必填)" style="width:100%">
    <textarea id="is-new-impact" rows="2" placeholder="业务影响(选填)" style="width:100%"></textarea>
    <div><button id="is-new-send">建问题单</button> <span class="k" id="is-new-why"></span></div>
    <div class="k">${md("从一条意见建:去那条意见的详情页点「从这条意见建问题单」,会同时把意见关联上。")}</div>`;
  const 表 = !d.items.length ? 状态("", "还没有问题单", "从意见受理台把核实过的意见并进问题单,或者在下面直接建。").html
    : `<table><thead><tr><th>标题</th><th>状态</th><th>根因</th><th>负责人</th><th>处理时限</th><th>关联意见</th><th></th></tr></thead><tbody>`
      + d.items.map((x) => `<tr>
          <td>${esc(x.标题)}${x.重开次数 ? `<div class="k">重开过 ${esc(String(x.重开次数))} 次</div>` : ""}</td>
          <td>${x.状态 === "已验证关闭" ? '<span class="pill ok">' : '<span class="pill">'}${esc(x.状态)}</span>${x.指向主问题 ? `<div class="k">→ ${esc(x.指向主问题)}</div>` : ""}</td>
          <td>${esc(x.根因类别 || "未分类")}<div class="k">${esc(x.根因核实 || "")}</div></td>
          <td>${esc(x.负责人 || "—")}</td>
          <td class="k">${esc(x.处理时限 || "—")}</td>
          <td>${esc(String(x.关联意见数))}</td>
          <td><button data-isopen="${esc(x.id)}">打开</button></td></tr>`).join("") + `</tbody></table>`;
  $("#main").innerHTML = 头 + 条("状态", d.可选状态, 筛.状态) + 条("根因", d.可选根因类别, 筛.根因) + 表 + 页码条(d) + 建;
  $("#main").querySelectorAll("[data-isf]").forEach((b) => {
    b.onclick = () => 页_问题单清单(1, Object.assign({}, 筛, b.dataset.isfK === "状态" ? { 状态: b.dataset.isf } : { 根因: b.dataset.isf }));
  });
  $("#main").querySelectorAll("[data-isopen]").forEach((b) => { b.onclick = () => { location.hash = "#/issue/" + encodeURIComponent(b.dataset.isopen); }; });
  挂页码($("#main"), (n) => 页_问题单清单(n, 筛));
  $("#is-new-send").onclick = async () => {
    const 题 = ($("#is-new-title").value || "").trim(), 影 = ($("#is-new-impact").value || "").trim();
    if (!题) { $("#is-new-why").textContent = "标题要写"; return; }
    $("#is-new-send").disabled = true;
    try {
      const r = await 请求(`${P()}/issues`, { method: "POST", body: JSON.stringify({ 标题: 题, 业务影响: 影 || null }) });
      location.hash = "#/issue/" + encodeURIComponent(r.id);
    } catch (e) { $("#is-new-send").disabled = false; $("#is-new-why").textContent = "没建上:" + ((e.体 && (e.体.message + " " + (e.体.advice || ""))) || e.message); }
  };
}

async function 页_问题单详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/issues">问题单</a> / ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/issues/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_问题单详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  const 选 = (fid, 值们, 当前, 可空) => `<select id="${fid}">` + (可空 ? [""] : []).concat(值们 || []).map((t) =>
    `<option value="${esc(t)}"${t === (当前 || "") ? " selected" : ""}>${esc(t || "(未分类)")}</option>`).join("") + `</select>`;
  // 「能改的字段」:页面上的输入框 ↔ 请求体里的名字;只把改了的那几样发出去
  const 改 = [["标题", "is-e-title"], ["业务影响", "is-e-impact"], ["复现条件", "is-e-repro"], ["方案", "is-e-solution"],
    ["验收标准", "is-e-accept"], ["目标版本", "is-e-version"], ["依赖", "is-e-dep"], ["负责人", "is-e-owner"],
    ["处理时限", "is-e-due"], ["根因类别", "is-e-rc"], ["根因核实", "is-e-rcs"], ["能力", "is-e-cap"]];
  // 11-12 能力档案:详情给的「能力」是 {id, 名字, 状态},改的时候只发编号
  const 现值 = (名) => 名 === "能力" ? ((d.能力 || {}).id || "") : (d[名] || "");
  const 框 = (名, fid) => 名 === "能力" ? `<input id="${fid}" value="${esc(现值(名))}" placeholder="能力档案编号(cp_…),空着 = 不挂" style="width:100%">`
    : 名 === "根因类别" ? 选(fid, d.可选根因类别, d.根因类别, true)
    : 名 === "根因核实" ? 选(fid, d.可选核实状态, d.根因核实, false)
    : 名 === "处理时限" ? `<input id="${fid}" type="date" value="${esc(d.处理时限 || "")}">`
    : `<input id="${fid}" value="${esc(d[名] || "")}" style="width:100%">`;
  const 编辑 = d.能改字段 ? `<h2>改字段</h2><table><tbody>`
      + 改.map(([名, fid]) => `<tr><td class="k">${esc(名)}</td><td>${框(名, fid)}</td></tr>`).join("")
      + `</tbody></table><input id="is-e-note" placeholder="说明(改根因类别 / 核实状态时必填:调整理由入日志)" style="width:100%">
      <div><button id="is-e-save">保存</button> <span class="k" id="is-e-why"></span></div>`
    : `<div class="note">${md(`「${d.状态}」的问题单不能改字段(已关闭的要改先「关闭后复发」;重复的去改主问题)。`)}</div>`;
  // 动作要带的字段:哪一步要什么由接口说(要的字段 / 可带的字段),这里只管画成输入框
  const 要的 = [...new Set((d.能做的动作 || []).flatMap((a) => (a.要的字段 || []).concat(a.可带的字段 || [])))];
  const 待验 = (d.验证记录 || []).filter((v) => v.状态 === "待验证"), 待生 = (d.发布记录 || []).filter((r) => r.事件 === "发布" && r.状态 === "待生效");
  const 下拉 = (名, 项们, 文) => `<div>${esc(名)}:<select data-isx="${esc(名)}"><option value="">(不选)</option>`
    + 项们.map((x) => `<option value="${esc(x.id)}">${esc(x.id)} · ${esc(文(x))}</option>`).join("") + `</select></div>`;
  const 字段框 = (名) => 名 === "重新评估日期" ? `<div>${esc(名)}:<input data-isx="${esc(名)}" type="date"></div>`
    : 名 === "主问题" ? `<div>${esc(名)}:<input data-isx="${esc(名)}" placeholder="主问题单编号(is_…)"></div>`
    : 名 === "验证记录" ? 下拉(名, 待验, (v) => `候选 ${v.候选版本} · 三组关联了 ${v.三组关联了几组} 组`)
    : 名 === "发布记录" ? 下拉(名, 待生, (r) => `${r.种类} ${r.关联的发布}`)
    : `<div>${esc(名)}:<textarea data-isx="${esc(名)}" rows="2" style="width:100%"></textarea></div>`;
  const 钮 = (d.能做的动作 || []).map((a) => `<button data-isact="${esc(a.动作)}">${esc(a.动作)} → ${esc(a.到)}</button>`).join(" ");
  const 前置 = (d.能做的动作 || []).filter((a) => a.前置条件).map((a) => `<div class="k">「${esc(a.动作)}」要:${esc(a.前置条件)}</div>`).join("");
  const 处理 = 钮 ? `<textarea id="is-act-note" rows="2" placeholder="说明:暂不处理(理由)/ 标为重复 / 验证失败 / 发布失败(错误)/ 复发 / 重新评估 要写" style="width:100%"></textarea>
      ${要的.map(字段框).join("")}<div>${钮}</div>${前置}<div class="k" id="is-act-why"></div>`
    : `<div class="note">这一步没有能做的动作(${esc(d.状态)})。</div>`;
  // 改进验证与发布(PRD §4.3):这张单上的验证记录 / 发布记录,点进去看详情、补三组评测、记回滚
  const 验表 = (d.验证记录 || []).length ? `<table><thead><tr><th>验证记录</th><th>状态</th><th>候选 / 基线</th><th>三组</th><th>建于</th></tr></thead><tbody>`
      + d.验证记录.map((v) => `<tr><td><a href="#/verification/${encodeURIComponent(v.id)}">${esc(v.id)}</a></td><td>${esc(v.状态)}</td>
          <td>${esc(v.候选版本)} / ${esc(v.基线版本)}</td><td>关联了 ${esc(String(v.三组关联了几组))} / 3 组</td>
          <td class="k">${esc(String(v.建于 || "").slice(5, 16).replace("T", " "))}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有验证记录。</div>`;
  const 发表 = (d.发布记录 || []).length ? `<table><thead><tr><th>发布记录</th><th>事件 · 状态</th><th>关联的发布</th><th>回滚关系</th><th>建于</th></tr></thead><tbody>`
      + d.发布记录.map((r) => `<tr><td><a href="#/rollout/${encodeURIComponent(r.id)}">${esc(r.id)}</a></td><td>${esc(r.事件)} · ${esc(r.状态)}</td>
          <td>${esc(r.种类)} <span class="k">${esc(r.关联的发布)}</span></td>
          <td class="k">${r.回滚的是 ? "回滚的是 " + esc(r.回滚的是) : ""}${r.被回滚 ? "被 " + esc(r.被回滚) + " 回滚" : ""}</td>
          <td class="k">${esc(String(r.建于 || "").slice(5, 16).replace("T", " "))}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有发布记录。</div>`;
  const 验框 = [["原缺陷案例", "必填:原来错在哪(文字)"], ["关联意见", "选填:意见编号"], ["关联trace", "选填:聊天站那一轮"],
    ["预期结果", "必填"], ["禁止行为", "必填"], ["基线版本", "必填:和评测里的基线一致"], ["候选版本", "必填:和评测里的候选一致"],
    ["数据集版本", "必填:冻结过的数据集版本编号(复现组用的那份)"], ["判分规则", "必填:复现组评测的判据版本号(只存引用)"],
    ["复现组评测", "评测编号,可以后补"], ["回归组评测", "评测编号,可以后补"], ["保留组评测", "评测编号,可以后补(别和复现组用同一份数据集版本)"]];
  const 发框 = [["改了哪些依赖版本", "必填"], ["批准人", "必填"], ["采用新版本的入口", "必填:例如 聊天站店长助手 / 访问 API"],
    ["试点范围", "必填:先在哪个范围手动启用(后台不支持按门店 / 用户灰度)"], ["观察指标", "选填(观察窗口 / 样本量待定)"],
    ["回退版本", "必填"], ["回退触发条件", "必填"]];
  const 建记录 = d.能改字段 ? `<details><summary>建一条验证记录</summary><table><tbody>`
      + 验框.map(([名, 提示]) => `<tr><td class="k">${esc(名)}</td><td><input data-ivn="${esc(名)}" placeholder="${esc(提示)}" style="width:100%"></td></tr>`).join("")
      + `</tbody></table><div><button id="is-iv-new">建验证记录</button> <span class="k" id="is-iv-why"></span></div></details>
    <details><summary>建一条发布记录(只记,不发布 —— 真发布在发布页做)</summary><table><tbody>
      <tr><td class="k">种类</td><td><select id="is-ir-kind"><option>应用发布清单</option><option>聊天助手版本</option></select></td></tr>
      <tr><td class="k">发布清单</td><td><input data-irn="发布清单" placeholder="种类是应用发布清单时填清单编号" style="width:100%"></td></tr>
      <tr><td class="k">聊天助手</td><td><input data-irn="聊天助手" placeholder="种类是聊天助手版本时填助手编号" style="width:100%"></td></tr>
      <tr><td class="k">聊天助手版本号</td><td><input id="is-ir-vno" type="number" min="0" placeholder="v3 就填 3"></td></tr>`
      + 发框.map(([名, 提示]) => `<tr><td class="k">${esc(名)}</td><td><input data-irn="${esc(名)}" placeholder="${esc(提示)}" style="width:100%"></td></tr>`).join("")
      + `</tbody></table><div><button id="is-ir-new">建发布记录</button> <span class="k" id="is-ir-why"></span></div></details>` : "";
  const 意见表 = (d.关联的意见 || []).length ? `<table><thead><tr><th>意见</th><th>谁</th><th>说了什么</th><th>状态</th></tr></thead><tbody>`
      + d.关联的意见.map((o) => `<tr><td><a href="#/opinion/${encodeURIComponent(o.id)}">${esc(o.id)}</a><div class="k">${esc(o.评价)}${o.问题类型 ? " · " + esc(o.问题类型) : ""}</div></td>
          <td>${esc((o.提问人 || {}).姓名 || (o.提问人 || {}).工号 || "")}</td><td>${esc(String(o.说明 || "").slice(0, 60))}</td><td>${esc(o.状态)}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有意见关联到这张单。</div>`;
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>${esc(d.标题)}</h1>
      <div class="sub">状态 <b>${esc(d.状态)}</b>${d.已解决 ? ' · <span class="pill ok">已解决</span>' : ""}
        · ${esc(d.根因类别 || "根因未分类")} · ${esc(d.根因核实)}${d.重开次数 ? ` · 重开过 ${esc(String(d.重开次数))} 次` : ""}</div></div></div>
    ${d.能力 ? `<div class="note">挂在能力 <a href="#/capability/${encodeURIComponent(d.能力.id)}">${esc(d.能力.名字)}</a>(${esc(d.能力.状态)})上。</div>` : ""}
    ${d.主问题 ? `<div class="note">这是重复单,指向主问题 <a href="#/issue/${encodeURIComponent(d.主问题.id)}">${esc(d.主问题.标题)}</a>(${esc(d.主问题.状态)})。关联在这张单上的意见留在这里(保留来源)。</div>` : ""}
    <table><tbody>${kv("业务影响", d.业务影响)}${kv("复现条件", d.复现条件)}${kv("方案", d.方案)}${kv("验收标准", d.验收标准)}
      ${kv("目标版本", d.目标版本)}${kv("依赖", d.依赖)}${kv("负责人", d.负责人)}${kv("处理时限(过了不标超时:几天算超时待定)", d.处理时限)}
      ${kv("搁置理由", d.搁置理由)}${kv("重新评估日期", d.重新评估日期)}
      ${kv("处理说明", d.处理说明)}${kv("完成证据(文字;关闭时还要这一轮的验证记录 + 发布记录,见下)", d.完成证据)}
      ${kv("最近一次关闭", d.最近一次关闭 && String(d.最近一次关闭).slice(0, 16).replace("T", " "))}
      ${kv("受影响问答数(含重复单,按那一轮去重)", d.受影响问答数)}</tbody></table>
    ${(d.重复指向它的 || []).length ? `<div class="note">重复指向它的:` + d.重复指向它的.map((r) =>
      `<a href="#/issue/${encodeURIComponent(r.id)}">${esc(r.标题)}</a>(${esc(String(r.关联意见数))} 条意见)`).join(" · ") + `</div>` : ""}
    <h2>处理</h2>${处理}
    <h2>改进验证与发布</h2>
    <div class="k">${md("验证通过要三组(复现 / 回归 / 保留)都关联能当结论的评测 —— **不按分数判**,齐了由人判;发布生效要从新版本的实际运行回执确认用上了,配置保存成功不算。")}</div>
    <h3>验证记录</h3>${验表}<h3>发布记录</h3>${发表}${建记录}
    ${编辑}
    <h2>关联的意见</h2>${意见表}
    <h2>时间线</h2>
    ${(d.时间线 || []).length ? `<table><thead><tr><th>什么时候</th><th>谁</th><th>动作</th><th>从 → 到</th><th>说明</th><th>改了什么</th></tr></thead><tbody>`
      + d.时间线.map((e) => `<tr><td class="k">${esc(String(e.时间).slice(5, 16).replace("T", " "))}</td><td>${esc(e.谁 || "")}</td>
          <td>${esc(e.动作)}</td><td>${esc(e.从 || "")} → ${esc(e.到)}</td><td>${esc(e.说明 || "")}</td>
          <td class="k">${e.变化 ? esc(JSON.stringify(e.变化)) : ""}</td></tr>`).join("") + `</tbody></table>`
      : `<div class="note">还没有记录。</div>`}`;
  const 错话 = (e) => (e.体 && (e.体.message + " " + (e.体.advice || "") + (e.体.field_errors ? " " + JSON.stringify(e.体.field_errors) : ""))) || e.message;
  $("#main").querySelectorAll("[data-isact]").forEach((b) => {
    b.onclick = async () => {
      const 动作 = b.dataset.isact, 体 = { 动作, 说明: ($("#is-act-note") || {}).value || "" };
      const 这步 = (d.能做的动作 || []).find((a) => a.动作 === 动作) || {};
      (这步.要的字段 || []).forEach((名) => { const el = $("#main").querySelector(`[data-isx="${名}"]`); 体[名] = el ? el.value : ""; });
      (这步.可带的字段 || []).forEach((名) => { const el = $("#main").querySelector(`[data-isx="${名}"]`); if (el && el.value) 体[名] = el.value; });
      if (动作 === "关闭" && !(await 问一句("确定关闭?", "关闭之后关联的意见会跟着显示「已验证关闭」。复发了可以重开,这次的关闭记录会留着。", { 确定: "关闭" }))) return;
      b.disabled = true;
      try {
        await 请求(`${P()}/issues/${encodeURIComponent(id)}/actions`,
          { method: "POST", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
        页_问题单详情(id);
      } catch (e) { b.disabled = false; $("#is-act-why").textContent = "没处理上:" + 错话(e); }
    };
  });
  if ($("#is-iv-new")) $("#is-iv-new").onclick = async () => {
    const 体 = {};
    $("#main").querySelectorAll("[data-ivn]").forEach((el) => { const v = (el.value || "").trim(); if (v) 体[el.dataset.ivn] = v; });
    $("#is-iv-new").disabled = true;
    try {
      const r = await 请求(`${P()}/issues/${encodeURIComponent(id)}/verifications`, { method: "POST", body: JSON.stringify(体) });
      location.hash = "#/verification/" + encodeURIComponent(r.id);
    } catch (e) { $("#is-iv-new").disabled = false; $("#is-iv-why").textContent = "没建上:" + 错话(e); }
  };
  if ($("#is-ir-new")) $("#is-ir-new").onclick = async () => {
    const 体 = { 种类: $("#is-ir-kind").value };
    $("#main").querySelectorAll("[data-irn]").forEach((el) => { const v = (el.value || "").trim(); if (v) 体[el.dataset.irn] = v; });
    const 号 = ($("#is-ir-vno").value || "").trim();
    if (号) 体.聊天助手版本号 = parseInt(号, 10);
    $("#is-ir-new").disabled = true;
    try {
      const r = await 请求(`${P()}/issues/${encodeURIComponent(id)}/releases`, { method: "POST", body: JSON.stringify(体) });
      location.hash = "#/rollout/" + encodeURIComponent(r.id);
    } catch (e) { $("#is-ir-new").disabled = false; $("#is-ir-why").textContent = "没建上:" + 错话(e); }
  };
  if ($("#is-e-save")) $("#is-e-save").onclick = async () => {
    const 体 = {};
    改.forEach(([名, fid]) => { const v = ($("#" + fid).value || "").trim(); if (v !== 现值(名)) 体[名] = v; });
    if (!Object.keys(体).length) { $("#is-e-why").textContent = "没有改动"; return; }
    体.说明 = ($("#is-e-note").value || "").trim();
    $("#is-e-save").disabled = true;
    try {
      await 请求(`${P()}/issues/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
      页_问题单详情(id);
    } catch (e) { $("#is-e-save").disabled = false; $("#is-e-why").textContent = "没保存上:" + 错话(e); }
  };
}

/* ── 上线验收(11-12,执行手册 W41;业务拍板 11-12 第一条「做完 = 试点两周 + 十条验收签字 + 费用上限」)──
 * 三项状态、能不能签、能不能填全由接口算(acceptance_flow.py),页面只照画;**只有「通过」画成绿**,
 * 未开始 / 拿不到 / 进行中 / 不通过 一律不绿,而且每项底下照写接口给的那句话(里面写着「拿不到 ≠ 通过」)。
 * 十条场景和通过标准是接口种的(抄自 PRD 13.4),页面不另抄一份。 */
async function 页_上线验收() {
  const 头 = `<div class="crumb">日志与监测 / 上线验收</div>
    <div class="head"><div><h1>上线验收</h1>
      <div class="sub">${md("十条核心场景(产品需求文档 13.4)逐条验、店长逐条签字;顶上算「做完了没有」—— **三项都通过才算,拿不到数据的不算通过**。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/acceptance`); }
  catch (e) { const s = 错误块(e, 页_上线验收); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 判 = d.做完判定 || { 三项: [] };
  const 绿 = (状) => 状 === "通过" ? '<span class="pill ok">' : (状 === "不通过" ? '<span class="pill warn">' : '<span class="pill">');
  const 总 = (判.做完了吗 ? `<div class="note">` : `<div class="state">`)
    + `<h3>${判.做完了吗 ? "做完了" : "还没做完"}</h3><p>${md(判.说明 || "")}</p></div>`;
  const 三项 = `<table><thead><tr><th>判定项</th><th>状态</th><th>依据</th></tr></thead><tbody>`
    + (判.三项 || []).map((x) => `<tr><td>${esc(x.项)}</td><td>${绿(x.状态)}${esc(x.状态)}</span></td><td>${md(x.说明 || "")}</td></tr>`).join("")
    + `</tbody></table>`;
  const 试 = d.试点;
  const 试点块 = !试 ? "" : `<h2>真数据导入日(试点从这天算两周)</h2>
    <div>现在:<b>${esc(试.真数据导入日 || "没设 —— 真实试点还没开始")}</b>${试.说明 ? ` <span class="k">${esc(试.说明)}</span>` : ""}</div>`
    + (d.我能签吗 ? `<div><input id="acc-pilot-date" type="date" value="${esc(试.真数据导入日 || "")}">
        <input id="acc-pilot-note" placeholder="说明(必填:哪天导入的真数据、谁确认的)" style="width:60%">
        <button id="acc-pilot-save">保存</button> <span class="k" id="acc-pilot-why"></span></div>
        <div class="k">${md("清空日期再保存 = 回到「未开始」。不能填将来的日子。")}</div>`
      : `<div class="k">${md(`设这个日子要「${d.签字要的权限}」权限(和店长签字同一道闸)。`)}</div>`);
  const 费 = d.本月费用 || {};
  const 费块 = !d.本月费用
    ? `<div class="k">${md("本月门店用量账取不到(聊天站没连上或内部通道没开)—— 拿不到 ≠ 通过。")}</div>`
    : 费.来源 === "门店用量账"
    ? `<div class="k">${md(`本月(${费.月份 || ""})门店用量账:门店真实调用 ${费.行数 ?? "—"} 笔,参考价合计 ${费.已知金额 ?? "拿不到"} 美元`
      + ` —— 只算门店聊天,评测 / 夜跑 / 开发不算(11-13 拍);参考价不是账单。`)}</div>`
    : `<div class="k">${md(`本月(${费.月份 || ""})用量账:真调用 ${费.行数 ?? "—"} 行,`
    + `参考价合计 ${费.已知金额 ?? "—"} 美元,算不出参考价的 ${费.金额未知的行数 ?? "—"} 行 —— 和「用量与成本」页同一份账,参考价不是账单。`)}</div>`;
  const 框 = (x, 名, 类型) => 名 === "结论"
    ? `<select data-accf="${esc(x.id)}" data-acck="结论">` + (d.可选结论 || []).map((t) =>
        `<option value="${esc(t)}"${t === x.结论 ? " selected" : ""}>${esc(t)}</option>`).join("") + `</select>`
    : `<input data-accf="${esc(x.id)}" data-acck="${esc(名)}"${类型 ? ` type="${类型}"` : ""} value="${esc(x[名] || "")}" style="width:100%">`;
  const 签字格 = (x) => x.签字人
    ? `${esc(x.签字人)}<div class="k">${esc(String(x.签字时间 || "").slice(0, 16).replace("T", " "))}${x.签于真实试点前 ? " · 签于真实试点前" : ""}</div>`
    : (d.我能签吗 && x.结论 === "通过" && x.验的人 && x.验的日期 ? `<button data-accsign="${esc(x.id)}">签字</button>` : `<span class="k">未签</span>`);
  const 表 = !(d.items || []).length ? 状态("", "这个项目没有上线验收场景", d.note || "十条场景只种在澜绣项目里。").html
    : `<table><thead><tr><th>编号</th><th>场景 / 通过标准</th><th>验的人</th><th>验的日期</th><th>结论</th><th>证据链接</th><th>备注</th><th>店长签字</th><th></th></tr></thead><tbody>`
      + d.items.map((x) => `<tr data-accrow="${esc(x.id)}">
          <td>${esc(x.编号)}</td>
          <td>${esc(x.场景)}<div class="k">${esc(x.通过标准)}</div></td>`
        + (d.我能填吗
          ? `<td>${框(x, "验的人")}</td><td>${框(x, "验的日期", "date")}</td><td>${框(x, "结论")}</td><td>${框(x, "证据链接")}</td><td>${框(x, "备注")}</td>`
          : `<td>${esc(x.验的人 || "—")}</td><td>${esc(x.验的日期 || "—")}</td><td>${绿(x.结论)}${esc(x.结论)}</span></td>
             <td>${x.证据链接 ? esc(x.证据链接) : "—"}</td><td>${esc(x.备注 || "")}</td>`)
        + `<td>${签字格(x)}</td>
          <td>${d.我能填吗 ? `<button data-accsave="${esc(x.id)}">保存</button>` : ""}<div class="k" data-accwhy="${esc(x.id)}"></div></td></tr>`).join("")
      + `</tbody></table>
      <div class="k">${md(`填记录要「${d.填记录要的权限}」,签字要「${d.签字要的权限}」。**签过字之后改结论 / 验的人 / 日期 / 证据,签字会作废**,要店长重签。`)}</div>`;
  const 线 = (d.时间线 || []).length ? `<table><thead><tr><th>什么时候</th><th>谁</th><th>动作</th><th>场景</th><th>说明</th><th>改了什么</th></tr></thead><tbody>`
      + d.时间线.map((e) => `<tr><td class="k">${esc(String(e.时间).slice(5, 16).replace("T", " "))}</td><td>${esc(e.谁 || "")}</td>
          <td>${esc(e.动作)}</td><td>${esc(e.场景 || "—")}</td><td>${esc(e.说明 || "")}</td>
          <td class="k">${e.变化 ? esc(JSON.stringify(e.变化)) : ""}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有记录。</div>`;
  $("#main").innerHTML = 头 + 总 + 三项 + 费块 + 试点块 + `<h2>十条核心场景</h2>` + 表 + `<h2>时间线(最近 50 条)</h2>` + 线;
  const 错话 = (e) => (e.体 && (e.体.message + " " + (e.体.advice || "") + (e.体.field_errors ? " " + JSON.stringify(e.体.field_errors) : ""))) || e.message;
  const 行 = (id) => (d.items || []).find((x) => x.id === id) || {};
  $("#main").querySelectorAll("[data-accsave]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.accsave, 原 = 行(id), 体 = {};
      $("#main").querySelectorAll(`[data-accf="${id}"]`).forEach((el) => {
        const v = (el.value || "").trim();
        if (v !== (原[el.dataset.acck] || "")) 体[el.dataset.acck] = v;
      });
      const 提示 = $("#main").querySelector(`[data-accwhy="${id}"]`);
      if (!Object.keys(体).length) { 提示.textContent = "没有改动"; return; }
      if (原.签字人 && ["结论", "验的人", "验的日期", "证据链接"].some((k) => k in 体)
          && !(await 问一句("这一条已经签过字", "改了结论 / 验的人 / 日期 / 证据,店长的签字会作废,要重新签。", { 确定: "改,签字作废" }))) return;
      b.disabled = true;
      try {
        await 请求(`${P()}/acceptance/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(原.revision) }, body: JSON.stringify(体) });
        页_上线验收();
      } catch (e) { b.disabled = false; 提示.textContent = "没保存上:" + 错话(e); }
    };
  });
  $("#main").querySelectorAll("[data-accsign]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.accsign, 原 = 行(id);
      if (!(await 问一句(`签 ${原.编号}「${原.场景}」?`, `结论「${原.结论}」,${原.验的人} 在 ${原.验的日期} 验的。签字人记成你、时间记成现在。`, { 确定: "签字" }))) return;
      b.disabled = true;
      try {
        await 请求(`${P()}/acceptance/${encodeURIComponent(id)}/sign`, { method: "POST", headers: { "If-Match": String(原.revision) }, body: JSON.stringify({}) });
        页_上线验收();
      } catch (e) { b.disabled = false; const 提示 = $("#main").querySelector(`[data-accwhy="${id}"]`); if (提示) 提示.textContent = "没签上:" + 错话(e); }
    };
  });
  if ($("#acc-pilot-save")) $("#acc-pilot-save").onclick = async () => {
    const 日 = ($("#acc-pilot-date").value || "").trim(), 说 = ($("#acc-pilot-note").value || "").trim();
    if (!说) { $("#acc-pilot-why").textContent = "说明要写"; return; }
    $("#acc-pilot-save").disabled = true;
    try {
      await 请求(`${P()}/acceptance-pilot`, { method: "PATCH", headers: { "If-Match": String(试.revision) },
        body: JSON.stringify({ 真数据导入日: 日 || null, 说明: 说 }) });
      页_上线验收();
    } catch (e) { $("#acc-pilot-save").disabled = false; $("#acc-pilot-why").textContent = "没保存上:" + 错话(e); }
  };
}

/* ── 改进验证记录 / 发布记录(11-12;意见收集 PRD §4.3)──
 * 三组评测、能不能当结论、实际采用回执全是接口现查的;页面照写它给的「还差什么 / 为什么」,**不按分数画过没过**。
 * 发布记录页只记、只核:没有「发布」「回滚」按钮去动生产 —— 真发布 / 真回滚在发布页做,这里记回滚前接口会核生产指针。 */
async function 页_验证记录详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/issues">问题单</a> / 验证记录 ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/issue-verifications/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_验证记录详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  const 组表 = `<table><thead><tr><th>组</th><th>证明什么</th><th>评测</th><th>状态</th><th>候选 / 基线</th><th>数据集版本 · 判据</th><th>能当结论吗</th></tr></thead><tbody>`
    + (d.三组 || []).map((g) => { const e = g.评测; return `<tr><td>${esc(g.组)}</td><td class="k">${esc(g.证明什么)}</td>
        <td class="k">${e ? esc(e.id) : "没关联"}</td><td>${e && e.找得到 ? esc(e.状态) : (e ? "找不到了" : "—")}</td>
        <td>${e && e.找得到 ? esc(e.候选 || "") + " / " + esc(e.基线 || "") : ""}</td>
        <td class="k">${e && e.找得到 ? esc(e.数据集版本 || "") + " · " + esc(e.判据版本 || "") : ""}</td>
        <td>${e && e.找得到 ? (e.能当结论吗 ? "能" : "不能") : ""}${e && (e.为什么不能 || []).concat(e.和记录对不上的 || []).length
          ? `<div class="k">${esc((e.为什么不能 || []).concat(e.和记录对不上的 || []).join(";"))}</div>` : ""}</td></tr>`; }).join("") + `</tbody></table>`;
  const 改 = [["原缺陷案例", "defect"], ["关联意见", "op"], ["关联trace", "trace"], ["预期结果", "expect"], ["禁止行为", "forbid"],
    ["基线版本", "base"], ["候选版本", "cand"], ["数据集版本", "dv"], ["判分规则", "scorer"],
    ["复现组评测", "g1"], ["回归组评测", "g2"], ["保留组评测", "g3"]];
  const 现值 = (名) => 名 === "关联意见" ? ((d.关联意见 || {}).id || "") : 名 === "数据集版本" ? ((d.数据集版本 || {}).id || "")
    : /组评测$/.test(名) ? ((((d.三组 || []).find((g) => g.组 + "评测" === 名) || {}).评测 || {}).id || "") : (d[名] || "");
  const 编辑 = d.能改 ? `<h2>改(补三组评测多半在这里)</h2><table><tbody>`
      + 改.map(([名, k]) => `<tr><td class="k">${esc(名)}</td><td><input id="iv-e-${k}" value="${esc(现值(名))}" style="width:100%"></td></tr>`).join("")
      + `</tbody></table><input id="iv-e-note" placeholder="说明(选填)" style="width:100%">
      <div><button id="iv-e-save">保存</button> <span class="k" id="iv-e-why"></span></div>`
    : `<div class="note">${md(`这条验证记录是「${d.状态}」,不能再改 —— 下了结论的实验原样留着;要重新验证就在问题单上新建一条。`)}</div>`;
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>改进验证记录</h1>
      <div class="sub">状态 <b>${esc(d.状态)}</b> · 问题单 <a href="#/issue/${encodeURIComponent(d.问题单.id)}">${esc(d.问题单.标题)}</a>(${esc(d.问题单.状态)})</div></div></div>
    ${d.状态 === "待验证" ? (d.能点验证通过吗 ? `<div class="note">三组证据齐了 —— 可以去问题单上点「验证通过」(算不算通过由你判,不按分数)。</div>`
      : `<div class="note">还不能点「验证通过」:${esc((d.还差什么 || []).join(";"))}</div>`) : ""}
    <table><tbody>${kv("原缺陷案例", d.原缺陷案例)}${kv("关联意见", d.关联意见 && `${d.关联意见.id}(${d.关联意见.评价} · ${d.关联意见.状态})`)}
      ${kv("关联trace", d.关联trace)}${kv("预期结果", d.预期结果)}${kv("禁止行为", d.禁止行为)}
      ${kv("基线版本", d.基线版本)}${kv("候选版本", d.候选版本)}
      ${kv("固定数据集版本", (d.数据集版本 || {}).id && `${d.数据集版本.id}(${d.数据集版本.题数 == null ? "没存下题目清单" : d.数据集版本.题数 + " 题"})`)}
      ${kv("判分规则(引用)", d.判分规则)}${kv("结论说明", d.结论说明)}${kv("审批人", d.审批人)}
      ${kv("结论于", d.结论于 && String(d.结论于).slice(0, 16).replace("T", " "))}</tbody></table>
    <h2>三组评测(现查)</h2>${组表}
    ${编辑}`;
  const 错话 = (e) => (e.体 && (e.体.message + " " + (e.体.advice || "") + (e.体.field_errors ? " " + JSON.stringify(e.体.field_errors) : ""))) || e.message;
  if ($("#iv-e-save")) $("#iv-e-save").onclick = async () => {
    const 体 = {};
    改.forEach(([名, k]) => { const v = ($("#iv-e-" + k).value || "").trim(); if (v !== 现值(名)) 体[名] = v; });
    if (!Object.keys(体).length) { $("#iv-e-why").textContent = "没有改动"; return; }
    体.说明 = ($("#iv-e-note").value || "").trim() || null;
    $("#iv-e-save").disabled = true;
    try {
      await 请求(`${P()}/issue-verifications/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
      页_验证记录详情(id);
    } catch (e) { $("#iv-e-save").disabled = false; $("#iv-e-why").textContent = "没保存上:" + 错话(e); }
  };
}

async function 页_发布记录详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/issues">问题单</a> / 发布记录 ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/issue-releases/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_发布记录详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  const 对象 = d.关联的发布现在 || {};
  const 对象块 = !对象.找得到 ? `<div class="note">关联的发布找不到了。</div>` : `<table><tbody>`
    + (d.种类 === "应用发布清单"
      ? kv("应用", `${(对象.应用 || {}).名字 || ""}(${(对象.应用 || {}).id || ""})`) + kv("清单", d.发布清单)
        + kv("清单钉的版本", Object.entries(对象.清单钉的版本 || {}).map(([k, v]) => `${k}:${v}`).join(";"))
        + kv("清单审核", 对象.清单审核 && `${对象.清单审核.审核人 || ""} · ${对象.清单审核.结论 || ""}`)
        + kv("生产现在指着", `${对象.生产现在指着 || "(没有)"}${对象.生产指着它吗 ? "(就是它)" : "(不是它)"}`)
      : kv("聊天助手", `${(对象.聊天助手 || {}).名字 || ""}(${(对象.聊天助手 || {}).角色键 || ""})`) + kv("版本", "v" + d.聊天助手版本号)
        + kv("这一版挂的", Object.entries(对象.这一版挂的 || {}).filter(([, v]) => v).map(([k, v]) => `${k}:${v}`).join(";"))
        + kv("生产现在是", `${对象.生产现在是 || "(没有)"}${对象.生产是它吗 ? "(就是它)" : "(不是它)"}`))
    + `</tbody></table>`;
  const 采 = d.实际采用 || {};
  const 采块 = `<div class="note">${采.现查 ? "现查" : "当时记下的"}:${采.确认了 ? "已确认实际用上了" : "还确认不了"}${采.为什么 ? " —— " + esc(采.为什么) : ""}</div>`
    + (采.回执 ? `<div class="k">回执:${esc(JSON.stringify(采.回执))}</div>` : "");
  const 文 = ["改了哪些依赖版本", "批准人", "采用新版本的入口", "试点范围", "观察指标", "回退版本", "回退触发条件"];
  const 编辑 = d.能改 ? `<h2>改</h2><table><tbody>`
      + 文.map((名, i) => `<tr><td class="k">${esc(名)}</td><td><input id="ir-e-${i}" value="${esc(d[名] || "")}" style="width:100%"></td></tr>`).join("")
      + `</tbody></table><input id="ir-e-note" placeholder="说明(选填)" style="width:100%">
      <div><button id="ir-e-save">保存</button> <span class="k" id="ir-e-why"></span></div>` : "";
  const 回滚 = d.能记回滚 ? `<h2>记一次回滚</h2>
      <div class="k">${md("**这里不回滚任何东西**:先在发布页 / 聊天助手页把生产真切回去,再来记 —— 接口会核生产指针确实指回去了。已经发生的业务写入不会跟着撤销。")}</div>
      <input id="ir-rb-to" placeholder="${d.种类 === "应用发布清单" ? "回到哪一份清单(编号)" : "回到哪一版(版本号,数字)"}" style="width:100%">
      <textarea id="ir-rb-why" rows="2" placeholder="触发原因(必填,对照上面的回退触发条件)" style="width:100%"></textarea>
      <div><button id="ir-rb-send">记回滚</button> <span class="k" id="ir-rb-err"></span></div>` : "";
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>改进${esc(d.事件)}记录</h1>
      <div class="sub">${esc(d.事件)} · <b>${esc(d.状态)}</b> · 问题单 <a href="#/issue/${encodeURIComponent(d.问题单.id)}">${esc(d.问题单.标题)}</a>(${esc(d.问题单.状态)})</div></div></div>
    ${d.回滚的是 ? `<div class="note">这是一次回滚,回滚的是 <a href="#/rollout/${encodeURIComponent(d.回滚的是)}">${esc(d.回滚的是)}</a>。</div>` : ""}
    ${d.被回滚 ? `<div class="note">这条发布已经被 <a href="#/rollout/${encodeURIComponent(d.被回滚)}">${esc(d.被回滚)}</a> 回滚(这一行内容没改)。</div>` : ""}
    <table><tbody>${文.map((名) => kv(名, d[名])).join("")}${kv("生效于", d.生效于 && String(d.生效于).slice(0, 16).replace("T", " "))}
      ${kv("失败说明", d.失败说明)}</tbody></table>
    <h2>关联的发布(现在)</h2>${对象块}
    <h2>实际采用</h2>${采块}
    ${编辑}${回滚}
    <div class="k">${md(d.note || "")}</div>`;
  const 错话 = (e) => (e.体 && (e.体.message + " " + (e.体.advice || "") + (e.体.field_errors ? " " + JSON.stringify(e.体.field_errors) : ""))) || e.message;
  if ($("#ir-e-save")) $("#ir-e-save").onclick = async () => {
    const 体 = {};
    文.forEach((名, i) => { const v = ($("#ir-e-" + i).value || "").trim(); if (v !== (d[名] || "")) 体[名] = v; });
    if (!Object.keys(体).length) { $("#ir-e-why").textContent = "没有改动"; return; }
    体.说明 = ($("#ir-e-note").value || "").trim() || null;
    $("#ir-e-save").disabled = true;
    try {
      await 请求(`${P()}/issue-releases/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
      页_发布记录详情(id);
    } catch (e) { $("#ir-e-save").disabled = false; $("#ir-e-why").textContent = "没保存上:" + 错话(e); }
  };
  if ($("#ir-rb-send")) $("#ir-rb-send").onclick = async () => {
    const 到原 = ($("#ir-rb-to").value || "").trim();
    const 体 = { 回到: d.种类 === "应用发布清单" ? 到原 : parseInt(到原, 10), 触发原因: ($("#ir-rb-why").value || "").trim() };
    $("#ir-rb-send").disabled = true;
    try {
      const r = await 请求(`${P()}/issue-releases/${encodeURIComponent(id)}/rollbacks`, { method: "POST", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
      location.hash = "#/rollout/" + encodeURIComponent(r.id);
    } catch (e) { $("#ir-rb-send").disabled = false; $("#ir-rb-err").textContent = "没记上:" + 错话(e); }
  };
}

/* ── 能力档案与改进看板(11-12;意见收集 PRD §4.4)──
 * 状态流转表只在后端 capability_flow.py:按钮照详情接口给的「能做的动作」画,筛选条照清单接口给的「可选状态」画 ——
 * 页面不另抄一份。**没有任何「智能度」分数**:验过什么看「已验证范围」那句话。
 * 评测结果 / 样本数量 / 实际运行量是接口现查的,查不到它给「没有数据」—— 页面照抄那四个字,不把它画成 0。 */
async function 页_能力档案清单(页 = 1, 筛 = "") {
  const 头 = `<div class="crumb">日志与监测 / 能力档案</div>
    <div class="head"><div><h1>能力档案</h1>
      <div class="sub">${md("每项业务能力验过什么、靠哪些智能体 / 工作流 / Skill / 工具、还有多少问题没解决。**不打「智能度」分**。")}
        <a href="#/capability-board">看改进看板</a></div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/capability-profiles?limit=30&page=${页}` + (筛 ? `&status=${encodeURIComponent(筛)}` : "")); }
  catch (e) { const s = 错误块(e, () => 页_能力档案清单(页, 筛)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 条 = `<div>状态:` + [""].concat(d.可选状态 || []).map((t) =>
    `<button data-cpf="${esc(t)}"${t === 筛 ? ' class="on"' : ""}>${esc(t || "全部")}</button>`).join("") + `</div>`;
  const 表 = !d.items.length ? 状态("", "还没有能力档案", "在下面建一份:写清这项能力做什么、给谁用、验过什么。").html
    : `<table><thead><tr><th>能力</th><th>状态</th><th>已验证范围</th><th>负责人</th><th>依赖</th><th>问题单(未解决 / 关联)</th><th></th></tr></thead><tbody>`
      + d.items.map((x) => `<tr>
          <td>${esc(x.名字)}<div class="k">${esc((x.适用角色 || []).join("、"))}</div></td>
          <td><span class="pill">${esc(x.状态)}</span></td>
          <td>${esc(x.已验证范围 || "还没写")}</td>
          <td>${esc(x.负责人 || "—")}</td>
          <td>${esc(String(x.依赖数))}</td>
          <td>${esc(String(x.未解决问题单数))} / ${esc(String(x.关联问题单数))}</td>
          <td><button data-cpopen="${esc(x.id)}">打开</button></td></tr>`).join("") + `</tbody></table>`;
  const 建 = `<h2>新建能力档案</h2>
    <input id="cp-new-name" placeholder="名字:这项能力叫什么(必填)" style="width:100%">
    <textarea id="cp-new-goal" rows="2" placeholder="业务目标(选填)" style="width:100%"></textarea>
    <div><button id="cp-new-send">建档案</button> <span class="k" id="cp-new-why"></span></div>`;
  $("#main").innerHTML = 头 + 条 + 表 + 页码条(d) + 建;
  $("#main").querySelectorAll("[data-cpf]").forEach((b) => { b.onclick = () => 页_能力档案清单(1, b.dataset.cpf); });
  $("#main").querySelectorAll("[data-cpopen]").forEach((b) => { b.onclick = () => { location.hash = "#/capability/" + encodeURIComponent(b.dataset.cpopen); }; });
  挂页码($("#main"), (n) => 页_能力档案清单(n, 筛));
  $("#cp-new-send").onclick = async () => {
    const 名 = ($("#cp-new-name").value || "").trim(), 目标 = ($("#cp-new-goal").value || "").trim();
    if (!名) { $("#cp-new-why").textContent = "名字要写"; return; }
    $("#cp-new-send").disabled = true;
    try {
      const r = await 请求(`${P()}/capability-profiles`, { method: "POST", body: JSON.stringify({ 名字: 名, 业务目标: 目标 || null }) });
      location.hash = "#/capability/" + encodeURIComponent(r.id);
    } catch (e) { $("#cp-new-send").disabled = false; $("#cp-new-why").textContent = "没建上:" + ((e.体 && (e.体.message + " " + (e.体.advice || ""))) || e.message); }
  };
}

async function 页_能力档案详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/capabilities">能力档案</a> / ${esc(id)}</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/capability-profiles/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_能力档案详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const kv = (k, v) => `<tr><td class="k">${esc(k)}</td><td>${v == null || v === "" ? "—" : esc(String(v))}</td></tr>`;
  // 现查的三样:接口说「没有数据」就照写「没有数据」+ 为什么,**不画成 0**
  const 没有 = (块) => `<div class="note">${esc(块.显示 || "没有数据")}:${esc(块.为什么 || "")}</div>`;
  const 评测块 = !(d.评测结果 || {}).有数据 ? 没有(d.评测结果 || {})
    : `<table><thead><tr><th>评测</th><th>状态</th><th>候选 / 基线</th><th>这项能力在哪一边</th><th>数据集版本</th><th>逐题结果</th><th>能当结论吗</th></tr></thead><tbody>`
      + d.评测结果.评测.map((e) => `<tr><td class="k">${esc(e.id)}</td><td>${esc(e.状态)}</td><td>${esc(e.候选 || "")} / ${esc(e.基线 || "")}</td>
          <td>${esc(e.这项能力的工作流在哪一边)}</td><td class="k">${esc(e.数据集版本 || "")}</td><td>${esc(String(e.逐题结果数))}</td>
          <td>${e.能当结论吗 ? "能" : "不能"}</td></tr>`).join("") + `</tbody></table><div class="k">${esc(d.评测结果.说明 || "")}</div>`;
  const 样本块 = !(d.样本数量 || {}).有数据 ? 没有(d.样本数量 || {})
    : `<table><thead><tr><th>数据集版本</th><th>题数</th><th>用在几次评测</th></tr></thead><tbody>`
      + d.样本数量.按数据集版本.map((s) => `<tr><td class="k">${esc(s.数据集版本 || "")}</td><td>${s.题数 == null ? "没存下题目清单" : esc(String(s.题数))}</td>
          <td>${esc(String(s.用在几次评测))}</td></tr>`).join("") + `</tbody></table><div class="k">${esc(d.样本数量.说明 || "")}</div>`;
  const 运行块 = !(d.实际运行量 || {}).有数据 ? 没有(d.实际运行量 || {})
    : `<table><thead><tr><th>依赖</th><th>业务</th><th>调试</th><th>最早 / 最近</th></tr></thead><tbody>`
      + d.实际运行量.按依赖.map((r) => `<tr><td>${esc(r.种类)} <span class="k">${esc(r.引用)}</span></td><td>${esc(String(r.业务))}</td><td>${esc(String(r.调试))}</td>
          <td class="k">${esc(String(r.最早 || "").slice(0, 10))} / ${esc(String(r.最近 || "").slice(0, 10))}</td></tr>`).join("") + `</tbody></table><div class="k">${esc(d.实际运行量.说明 || "")}</div>`;
  const 依赖表 = (d.依赖 || []).length ? `<table><thead><tr><th>种类</th><th>引用</th><th>名字</th><th>现在的状态</th></tr></thead><tbody>`
      + d.依赖.map((x) => `<tr><td>${esc(x.种类)}</td><td class="k">${esc(x.引用)}</td><td>${esc(x.名字 || "—")}</td><td>${esc(x.状态 || "")}${x.最新版本 ? " · " + esc(x.最新版本) : ""}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有登记依赖。</div>`;
  const 问 = d.问题单数 || {};
  const 单表 = (d.关联的问题单 || []).length ? `<table><thead><tr><th>问题单</th><th>状态</th><th>根因</th><th></th></tr></thead><tbody>`
      + d.关联的问题单.map((s) => `<tr><td><a href="#/issue/${encodeURIComponent(s.id)}">${esc(s.标题)}</a>${s.重开次数 ? `<div class="k">重开过 ${esc(String(s.重开次数))} 次</div>` : ""}</td>
          <td>${esc(s.状态)}</td><td>${esc(s.根因类别 || "未分类")}</td><td>${s.未解决 ? "未解决" : ""}</td></tr>`).join("") + `</tbody></table>`
    : `<div class="note">还没有问题单挂到这项能力上(在问题单详情的「能力」里填这份档案的编号)。</div>`;
  const 钮 = (d.能做的动作 || []).map((a) => `<button data-cpact="${esc(a.动作)}">${esc(a.动作)} → ${esc(a.到)}</button>`).join(" ");
  // 能改的字段:页面上的输入框 ↔ 请求体里的名字;只发改了的。适用角色用顿号分隔;依赖一行一条「种类:引用」
  const 角色文 = (d.适用角色 || []).join("、");
  const 依赖文 = (d.依赖 || []).map((x) => `${x.种类}:${x.引用}`).join("\n");
  const 改 = [["名字", "cp-e-name"], ["业务目标", "cp-e-goal"], ["输入", "cp-e-in"], ["输出", "cp-e-out"], ["负责人", "cp-e-owner"],
    ["已验证范围", "cp-e-scope"], ["下次验证事项", "cp-e-next"]];
  $("#main").innerHTML = 头 + `<div class="head"><div><h1>${esc(d.名字)}</h1>
      <div class="sub">状态 <b>${esc(d.状态)}</b> · 负责人 ${esc(d.负责人 || "未定")} · 未解决问题单 ${esc(String(问.未解决))} / 关联 ${esc(String(问.关联))}</div></div></div>
    <table><tbody>${kv("业务目标", d.业务目标)}${kv("输入", d.输入)}${kv("输出", d.输出)}${kv("适用角色", 角色文)}
      ${kv("已验证范围", d.已验证范围 || "还没写 —— 写了才能进试点 / 启用")}${kv("下次验证事项", d.下次验证事项)}
      ${kv("最近改进", d.最近改进 && `${d.最近改进.标题}(${String(d.最近改进.关闭于 || "").slice(0, 10)} 关闭)`)}</tbody></table>
    <h2>改状态</h2>
    ${钮 ? `<textarea id="cp-act-note" rows="2" placeholder="说明(必填):为什么改这个状态" style="width:100%"></textarea><div>${钮}</div><div class="k" id="cp-act-why"></div>`
      : `<div class="note">这一步没有能做的动作。</div>`}
    <h2>依赖(只存引用,名字和状态是现取的)</h2>${依赖表}
    <h2>关联的问题单</h2><div class="k">${esc(问.口径 || "")}</div>${单表}
    <h2>评测结果</h2>${评测块}
    <h2>样本数量</h2>${样本块}
    <h2>实际运行量</h2>${运行块}
    <h2>改字段</h2><table><tbody>`
      + 改.map(([名, fid]) => `<tr><td class="k">${esc(名)}</td><td><input id="${fid}" value="${esc(d[名] || "")}" style="width:100%"></td></tr>`).join("")
      + `<tr><td class="k">适用角色</td><td><input id="cp-e-roles" value="${esc(角色文)}" placeholder="用顿号分开:店长、顾问" style="width:100%"></td></tr>
      <tr><td class="k">依赖</td><td><textarea id="cp-e-deps" rows="3" placeholder="一行一条「种类:引用」,种类:${esc((d.可选依赖种类 || []).join(" / "))};Skill 写名字,其余写编号" style="width:100%">${esc(依赖文)}</textarea></td></tr>
    </tbody></table><input id="cp-e-note" placeholder="说明(选填)" style="width:100%">
    <div><button id="cp-e-save">保存</button> <span class="k" id="cp-e-why"></span></div>
    <h2>时间线</h2>
    ${(d.时间线 || []).length ? `<table><thead><tr><th>什么时候</th><th>谁</th><th>动作</th><th>从 → 到</th><th>说明</th><th>改了什么</th></tr></thead><tbody>`
      + d.时间线.map((e) => `<tr><td class="k">${esc(String(e.时间).slice(5, 16).replace("T", " "))}</td><td>${esc(e.谁 || "")}</td>
          <td>${esc(e.动作)}</td><td>${esc(e.从 || "")} → ${esc(e.到)}</td><td>${esc(e.说明 || "")}</td>
          <td class="k">${e.变化 ? esc(JSON.stringify(e.变化)) : ""}</td></tr>`).join("") + `</tbody></table>`
      : `<div class="note">还没有记录。</div>`}`;
  const 错话 = (e) => (e.体 && (e.体.message + " " + (e.体.advice || "") + (e.体.field_errors ? " " + JSON.stringify(e.体.field_errors) : ""))) || e.message;
  $("#main").querySelectorAll("[data-cpact]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try {
        await 请求(`${P()}/capability-profiles/${encodeURIComponent(id)}/actions`,
          { method: "POST", headers: { "If-Match": String(d.revision) }, body: JSON.stringify({ 动作: b.dataset.cpact, 说明: ($("#cp-act-note") || {}).value || "" }) });
        页_能力档案详情(id);
      } catch (e) { b.disabled = false; $("#cp-act-why").textContent = "没改上:" + 错话(e); }
    };
  });
  $("#cp-e-save").onclick = async () => {
    const 体 = {};
    改.forEach(([名, fid]) => { const v = ($("#" + fid).value || "").trim(); if (v !== (d[名] || "")) 体[名] = v; });
    const 角色 = ($("#cp-e-roles").value || "").trim();
    if (角色 !== 角色文) 体.适用角色 = 角色 ? 角色.split(/[、,,]/).map((s) => s.trim()).filter(Boolean) : [];
    const 依 = ($("#cp-e-deps").value || "").trim();
    if (依 !== 依赖文) 体.依赖 = 依 ? 依.split("\n").map((s) => s.trim()).filter(Boolean).map((s) => {
      const i = s.search(/[::]/); return i < 0 ? { 种类: s, 引用: "" } : { 种类: s.slice(0, i).trim(), 引用: s.slice(i + 1).trim() };
    }) : [];
    if (!Object.keys(体).length) { $("#cp-e-why").textContent = "没有改动"; return; }
    体.说明 = ($("#cp-e-note").value || "").trim() || null;
    $("#cp-e-save").disabled = true;
    try {
      await 请求(`${P()}/capability-profiles/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(d.revision) }, body: JSON.stringify(体) });
      页_能力档案详情(id);
    } catch (e) { $("#cp-e-save").disabled = false; $("#cp-e-why").textContent = "没保存上:" + 错话(e); }
  };
}

async function 页_改进看板() {
  const 头 = `<div class="crumb">日志与监测 / 改进看板</div>
    <div class="head"><div><h1>改进看板</h1>
      <div class="sub">${md("问题单按根因、能力、状态的数。**只出数和分母,不出结论、不排名、不打分**;行按固定顺序排,不按数量排。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/capability-board`); }
  catch (e) { const s = 错误块(e, () => 页_改进看板()); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 列 = `<th>总数</th><th>未解决</th><th>观察期复发过</th><th>关闭后重开过</th><th>分母</th>`;
  const 数 = (r) => ["总数", "未解决", "观察期复发过", "关闭后重开过", "分母"].map((k) => `<td>${esc(String(r[k]))}</td>`).join("");
  const 口 = d.口径 || {};
  $("#main").innerHTML = 头 + `<div class="note">${md(`分母 **${d.分母}** 张问题单;已重复的 ${d["已重复(不计入)"]} 张不计入(算在它指向的主问题上)。`)}</div>
    <h2>按根因</h2><table><thead><tr><th>根因类别</th>${列}</tr></thead><tbody>`
      + (d.按根因 || []).map((r) => `<tr><td>${esc(r.根因类别)}</td>${数(r)}</tr>`).join("") + `</tbody></table>
    <h2>按能力</h2><table><thead><tr><th>能力</th>${列}</tr></thead><tbody>`
      + (d.按能力 || []).map((r) => `<tr><td>${r.能力 ? `<a href="#/capability/${encodeURIComponent(r.能力.id)}">${esc(r.能力.名字)}</a> <span class="k">${esc(r.能力.状态)}</span>` : esc(r.说明 || "没关联能力")}</td>${数(r)}</tr>`).join("") + `</tbody></table>
    <h2>按状态</h2><table><thead><tr><th>状态</th><th>总数</th><th>分母</th></tr></thead><tbody>`
      + (d.按状态 || []).map((r) => `<tr><td>${esc(r.状态)}</td><td>${esc(String(r.总数))}</td><td>${esc(String(r.分母))}</td></tr>`).join("") + `</tbody></table>
    <h2>口径</h2><table><tbody>` + Object.keys(口).map((k) => `<tr><td class="k">${esc(k)}</td><td>${md(口[k])}</td></tr>`).join("") + `</tbody></table>
    <div class="k">${esc(d.note || "")}</div>`;
}

/* ── 运行记录(10-25 起是聊天站 trace 列表,点进调用树;原「占位」注释过期)────── */
async function 页_运行记录(页 = 1) {
  // 证据中心第四个工作包(10-25):原来是占位页。现在列**聊天站**推过来的每一轮(entry_kind=聊天站),
  // 点进去是同一个调用树页 —— 原文看不看得到由那边的字段权限管(查看敏感输入),这一页不另判
  const 头 = `<div class="crumb">日志与监测 / 运行记录</div>
    <div class="head"><div><h1>运行记录</h1>
      <div class="sub">${md("聊天站每一轮实际调了哪些工具、传了什么、回了什么。**原文要「查看敏感输入」授权**,没有的只看到形状。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces?limit=50&page=${页}&entry_kind=${encodeURIComponent("聊天站")}`); }
  catch (e) { const s = 错误块(e, 页_运行记录); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  // 执行故障上报(用户 10-25 拍「换模型也没用的直接上报」「上报给平台管理员」):只有能「配置密钥与预算」的人拿得到,
  // 拿不到(403)就不显示这一块 —— 前端隐藏不是授权,接口那边照样判
  let 故 = null;
  try { 故 = await 请求(`${P()}/trace-incidents?status=${encodeURIComponent("待处理")}`); }
  catch (e) { 故 = e.码 === 403 ? null : { 错: e }; }
  const 故障块 = !故 ? "" : 故.错 ? `<div class="note">${esc("执行故障上报没取到:" + 故.错.message)}</div>`
    : !故.items.length ? `<div class="note">${md("**执行故障上报:没有待处理的。** 库连不上、撞花费上限这类换模型也没用的问题,聊天站会直接报到这里。")}</div>`
    : `<h2>执行故障上报 · 待处理 ${故["待处理"]} 条</h2>
       <div class="sub">${md("换模型也没用、店里的人修不了的:**库连不上 / 锁住**、**撞花费上限**。处理完写一句怎么处理的再标。")}</div>
       <table><thead><tr><th>什么时候</th><th>什么故障</th><th>为什么</th><th></th></tr></thead><tbody>`
      + 故.items.map((i) => `<tr>
          <td class="k">${esc(String(i.created_at || "").slice(5, 19).replace("T", " "))}</td>
          <td><span class="pill fail">${esc(i.kind)}</span></td>
          <td>${esc(i.reason)}</td>
          <td><button data-tr="${esc(i.trace_id)}">看调用树</button>
            <input data-note="${esc(i.id)}" placeholder="怎么处理的(必填)">
            <button data-handle="${esc(i.id)}">标已处理</button></td>
        </tr>`).join("") + `</tbody></table>`;
  const 挂故障 = () => { $("#main").querySelectorAll("[data-tr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/trace/" + encodeURIComponent(b.dataset.tr); };
  }); $("#main").querySelectorAll("[data-handle]").forEach((b) => {
    b.onclick = async () => {
      const 话 = ($("#main").querySelector(`[data-note="${b.dataset.handle}"]`) || {}).value || "";
      b.disabled = true;
      try {
        await 请求(`${P()}/trace-incidents/${encodeURIComponent(b.dataset.handle)}/handle`,
          { method: "POST", body: JSON.stringify({ note: 话 }) });
        页_运行记录();
      } catch (e) { b.disabled = false; b.textContent = "没标上:" + ((e.体 && e.体.advice) || e.message); }
    };
  }); };
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 故障块 + 状态("", "还没有聊天站的运行记录",
      "聊天站每一轮跑完(或断了)之后,由澜绣的同步程序推过来;刚上线时这里是空的,在聊天页问一句再回来看。").html;
    挂故障();
    return;
  }
  const 状 = { running: "进行中", interrupted: "中断", failed: "出错", completed: "完成" };
  $("#main").innerHTML = 头 + 故障块 + `<h2>每一轮</h2><table><thead><tr>
      <th>什么时候</th><th>会话</th><th class="num">步</th><th>结果</th><th></th>
    </tr></thead><tbody>`
    + d.items.map((r) => { const t = 状[r.end_reason] || r.end_reason || "?";
      return `<tr>
        <td class="k">${esc(String(r.started_at || "").slice(5, 19).replace("T", " "))}
          <div class="k">${esc(String(r.request_id || "").replace("lanxiu-chat:", "聊天站 ").slice(0, 26))}</div></td>
        <td class="k">${esc(String(r.session_id || "—").slice(0, 12))}</td>
        <td class="num">${r["步数"]}${r["出错的步数"] ? ` <span class="pill fail">${r["出错的步数"]} 步出错</span>` : ""}</td>
        <td>${r.end_reason === "completed" ? `<span class="pill ok">${esc(t)}</span>`
            : r.end_reason === "running" ? `<span class="pill warn">${esc(t)}</span>`
            : `<span class="pill fail">${esc(t)}</span>`}</td>
        <td><button data-tr="${esc(r.id)}">看调用树</button></td>
      </tr>`; }).join("")
    + `</tbody></table>${页码条(d)}<div class="note">${md("「进行中」超过半小时没收尾的,聊天站那边会判成「中断」再推一次。")}</div>`;
  挂页码($("#main"), (n) => 页_运行记录(n));
  $("#main").querySelectorAll("[data-tr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/trace/" + encodeURIComponent(b.dataset.tr); };
  });
  挂故障();
}

/* ══════════════════════════════════════════════════════════════════
 * 工作流 Workflow(Workflow 与 Agent 后台规格 §4、§5)
 * ══════════════════════════════════════════════════════════════════
 *
 * ## 这三页里最要紧的两条
 *
 * ① **「最新冻结版本」和「生产引用版本」并排显示**(§4.1)。只显示一个的话,
 *    「我改完了」和「线上在跑的是这个」会被当成同一件事 —— 而那正是这个后台
 *    要解决的痛点之一。生产那一栏现在是「还没接」,**不是「—」**:
 *    一个「—」会被读成「线上没在用」。
 *
 * ② **拖拽不是唯一操作方法**(§3.3)。节点库里每个节点有「加入」按钮、
 *    右侧面板有 X/Y 数字输入框、画布上节点可以 Tab 聚焦 + 方向键移动。
 *    一个只能拖的画布,键盘用户和读屏用户完全用不了 ——
 *    而这件事在开发机上永远不会被发现。
 */
/* ── 工作流(2026-10-24 改版:用户拍「页面结构加上音频整理全流程全部做完」)───────────
 *
 * 依据外部方案《Workflow 深度研究与配置改版方案 V1.0》:配置的人知道自己想做什么,
 * 却不知道 `connection_version_id` 该填什么。所以这一版的形状是:
 *
 *   列表(每行 编辑 / 运行 / 看记录)→ 详情六个页签:概览 · 搭建 · 测试 · 运行记录 · 版本与发布 · 设置
 *   搭建 = 左边按执行顺序排好的步骤 + 右边中文表单(设置 / 输入数据 / 结果字段 / 高级)
 *
 * ## 三条在这一页必须成立的规矩
 *
 * ① **界面上只出现业务说法,内部标识进「技术详情」**。模型、处理要求、业务动作一律从下拉里选
 *    (`GET /workflow-resources`),不让人抄 ID。选不到就说「去哪儿补、找谁」。
 * ② **两种视图操作同一份定义**:步骤列表和流程图改的都是 `图态.定义`,不各存一份 ——
 *    各存一份的话,两边迟早不一样,而各自看起来都完整。
 * ③ **挪位置不改执行顺序,改执行顺序必须是明确操作**(「在此后添加」「下一步」那一栏)。
 *    坐标只影响画法,不进逻辑哈希(附录 A-9)。
 *
 * ⚠️ class 一律写**整段字面量**(两种写法各写一整段标签,三元选其一),不在 class 属性里拼变量 ——
 * 拼出来的 class 由 css_class_check 钉着只许少不许多;浏览器对不认识的 class 完全静默。
 */
const 工作流页签 = ["概览", "搭建", "测试", "运行记录", "版本与发布", "访问入口", "设置"];
// 10-27 照 Dify 改了两个名字(适配分析 5.1 定的):结束 →「输出」、分支汇合 →「变量聚合器」;其余保留业务叫法
const 步类型名 = { start: "开始", end: "输出", llm: "AI 处理", tool: "业务动作", retrieve: "查资料",
  // 11-15 文案对齐 Dify(规划一期第五件最后一项):「按条件分流」→「条件分支」、「人工核对」→「人工介入」(待办页里仍叫核对 —— 那边是处理人的动作)
  condition: "条件分支", transform: "整理字段", merge: "变量聚合器", loop: "循环", human: "人工介入", agent: "Agent", answer: "直接回复", classifier: "问题分类器", template: "模板转换", extractor: "参数提取器", assigner: "变量赋值",
  list_operator: "列表操作", doc_extractor: "文档提取器", foreach: "迭代", http_request: "HTTP 请求", parallel: "并行", subworkflow: "子流程", code: "代码执行", markdown_export: "Markdown 导出" };
const 结果类型们 = [["string", "文本"], ["number", "数字"], ["integer", "整数"], ["boolean", "是 / 否"],
  ["array", "列表"], ["object", "对象"]];

function 弹层(标题, 内容) {
  关弹层();
  const el = document.createElement("div");
  el.id = "mask"; el.className = "mask";
  el.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(标题)}">
      <div class="mh"><b>${esc(标题)}</b><button id="mx" aria-label="关闭">×</button></div>
      <div class="mb" id="mb">${内容}</div></div>`;
  document.body.appendChild(el);
  $("#mx").onclick = 关弹层;
  el.onclick = (e) => { if (e.target === el) 关弹层(); };
  return el;
}
function 关弹层() { const m = document.getElementById("mask"); if (m) m.remove(); }
/* 页面里的「告诉你一件事」和「问你一句」—— 换掉浏览器原生的 alert / confirm / prompt(10-26,方案 §10.2 点名)。
 * 原生的三个毛病:露出内部码、**加粗**不渲染成了星号、整页卡住点不了别的 */
function 提示(标题, 内容html) {
  弹层(标题, `${内容html}<div class="acts" style="margin-top:12px"><button class="pri" id="tsok">知道了</button></div>`);
  $("#tsok").onclick = 关弹层; $("#tsok").focus();
}
// → Promise:给了 `输入` 就返回填的字(取消 → null);没给就是确认框,返回 true / false
function 问一句(标题, 说明html, { 输入 = null, 多行 = false, 默认 = "", 确定 = "确定", 取消 = "取消", 必填 = false } = {}) {
  return new Promise((done) => {
    const 框 = 输入 === null ? "" : 多行
      ? `<textarea id="wq-in" rows="3" style="width:100%" placeholder="${esc(输入)}">${esc(默认)}</textarea>`
      : `<input id="wq-in" style="width:100%" placeholder="${esc(输入)}" value="${esc(默认)}">`;
    const el = 弹层(标题, `<div>${说明html}</div>${框}<div id="wq-err" class="k"></div>
      <div class="acts" style="margin-top:12px"><button class="pri" id="wq-ok">${esc(确定)}</button> <button id="wq-no">${esc(取消)}</button></div>`);
    let 完 = false;
    const 结 = (v) => { if (完) return; 完 = true; 关弹层(); done(v); };
    $("#wq-ok").onclick = () => {
      if (输入 === null) return 结(true);
      const v = $("#wq-in").value.trim();
      if (必填 && !v) { $("#wq-err").textContent = "这一项要填。"; $("#wq-in").focus(); return; }
      结(v);
    };
    $("#wq-no").onclick = () => 结(输入 === null ? false : null);
    $("#mx").onclick = () => 结(输入 === null ? false : null);
    el.onclick = (e) => { if (e.target === el) 结(输入 === null ? false : null); };
    const i = $("#wq-in"); (i || $("#wq-ok")).focus();
    if (i && !多行) i.onkeydown = (e) => { if (e.key === "Enter") $("#wq-ok").click(); };
  });
}
// 报错用页面里的弹层,不用 alert(10-26 用户截图:原生弹窗里露着 VALIDATION / write2.config.connection_version_id、星号没渲染)。
// 字段键「节点id.config.xxx」换成步骤名;同名的步骤(比如两个「写报告正文」)标「第几个」,不然分不清是哪一个
// 同名步骤(比如两个「写报告正文」)在列表、图上、面板标题都标「第几个」,不然分不清改的是哪一个(10-26)
function 同名后缀(n) {
  const ns = (图态 && 图态.定义 && 图态.定义.nodes) || [], 名 = 业务名(n);
  const 同 = ns.filter((x) => 业务名(x) === 名);
  return 同.length > 1 ? ` <span class="dup">(第 ${同.indexOf(n) + 1} 个)</span>` : "";
}
function 步骤称呼(id) {
  const ns = (typeof 图态 !== "undefined" && 图态 && 图态.定义 && 图态.定义.nodes) || [];
  const n = ns.find((x) => x.id === id);
  if (!n) return id === "图" ? "整张图" : id;
  const 同名 = ns.filter((x) => (x.name || x.id) === (n.name || n.id));
  return `「${n.name || n.id}」` + (同名.length > 1 ? `(第 ${同名.indexOf(n) + 1} 个)` : "");
}
function 中文化(s) { return String(s).replace(/[a-z][a-z_]*[a-z]/g, (k) => 字段中文[k] || k); }   // 字段中文 在搭建页那段定义(全局一份)
function 报错(e) {
  const b = e.体 || {};
  const 条 = Object.entries(b.field_errors || {}).map(([k, v]) => {
    const [id, ...余] = String(k).split(".");
    const 处 = 余.filter((x) => x !== "config").map(中文化).join(" · ");
    return `<li><b>${esc(步骤称呼(id))}</b>${处 ? " · " + esc(处) : ""}:${md(中文化(v))}</li>`;
  }).join("");
  弹层(b.code === "VALIDATION" ? "跑不了,先改这几处" : "没办成",
    `<p>${md(e.message)}</p>${条 ? `<ul>${条}</ul>` : ""}<p>下一步:${md(b.advice || "—")}</p>`
    + (b.code === "VALIDATION" ? `<p class="k">关掉这个框,下面的问题列表里点一条就能定位到那一步。</p>` : ""));
}
const 时间 = (s) => esc(String(s || "").slice(0, 16).replace("T", " "));

/* ── 列表 ─────────────────────────────────────────────────────── */
/* ── 页码条(用户 10-28 拍「页码」,不用「加载更多」)────────────────────────────
 * 吃接口的分页信封(页 / 页数 / total)。翻过头时接口给的页数是 null(拿不到总数,不写成 0)→ 只给「回第 1 页」。
 * 一页就够的不画。号码只摆当前页前后两个和首尾,中间用 … */
function 页码条(d) {
  const 页 = d["页"], 数 = d["页数"];
  if (数 == null) return 页 > 1 ? `<div class="pager"><span class="k">第 ${页} 页没有东西了</span> <button data-pg="1">回第 1 页</button></div>` : "";
  if (数 <= 1) return "";
  const 号 = [...new Set([1, 页 - 2, 页 - 1, 页, 页 + 1, 页 + 2, 数])].filter((x) => x >= 1 && x <= 数).sort((a, b) => a - b);
  let 前 = 0; const 钮 = [];
  for (const x of 号) {
    if (x - 前 > 1) 钮.push('<span class="k">…</span>');
    钮.push(x === 页 ? `<button class="pri" aria-current="page" disabled>${x}</button>` : `<button data-pg="${x}">${x}</button>`);
    前 = x;
  }
  return `<div class="pager"><button data-pg="${页 - 1}"${页 <= 1 ? " disabled" : ""}>上一页</button>${钮.join("")}
    <button data-pg="${页 + 1}"${页 >= 数 ? " disabled" : ""}>下一页</button>
    <span class="k">第 ${页} / ${数} 页 · 共 ${d.total} 条</span></div>`;
}
function 挂页码(根, 去) { 根.querySelectorAll(".pager [data-pg]").forEach((b) => { b.onclick = () => 去(+b.dataset.pg); }); }

/* ── 工作室:应用卡片(10-28 照 Dify;用户 10-27 拍第 9 条「应用类型五种都留」)────────────
 * 卡片上只放**一眼要判断的**:是什么类型、干什么用、线上跑的哪一版、最近跑得怎样、聊天里谁来做。
 * 版本 / 测试 / 发布这些进详情做。没接上的三种类型在「创建应用」里**摆出来、写明为什么点不了**,不藏 */
const 应用类型 = [
  ["workflow", "工作流", "流", "按固定步骤跑的流程:每一步用什么、数据从哪来都事先定好。", () => 弹_新建工作流()],
  ["chatflow", "对话流", "话", "带记忆的多轮对话,每一轮按固定步骤跑。", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["chat", "聊天助手", "聊", "澜绣聊天站里的岗位助手(店长、顾问…):改提示词、选模型和工具。", null,
    "聊天助手不在这里新建 —— 它们是聊天站代码里的岗位,用 tools/import_chat_assistant.py 导进来(先导了店长助手)"],
  ["agent", "Agent", "智", "模型自己决定下一步做什么,程序校验、执行、记录和限制它。", () => 弹_新建agent()],
  ["completion", "文本生成", "文", "给一段输入,出一段文字,没有多轮对话。", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
];

function 卡_工作流(r) {
  const 链 = (t) => `#/workflow/${encodeURIComponent(r.id)}/${encodeURIComponent(t)}`, 跑 = r["最近运行"];
  return `<div class="appcard" data-kind="workflow" data-id="${esc(r.id)}">
    <div class="ah"><span class="ico wf">流</span><div class="an"><a href="${链("概览")}"><b>${esc(r["名称"])}</b></a>
      <div class="k">工作流 · ${esc(r["负责人"] || "没写负责人")}</div></div>
      ${r["校验状态"] === "通过" ? '<span class="pill ok">校验通过</span>' : `<span class="pill warn">${esc(r["校验状态"])}</span>`}</div>
    <div class="ad">${esc(r["用途"] || "还没写用途")}</div>
    <div class="k" title="${esc(去粗(r["生产引用说明"]))}">线上(生产):${r["生产引用版本"] ? `<b>${esc(r["生产引用版本"])}</b>` : "还没发布"}
      ${r["最新冻结版本"] ? ` · 最新候选 ${esc(r["最新冻结版本"])}` : ""}</div>
    <div class="k">最近运行:${跑 ? `<a href="#/wfrun/${encodeURIComponent(跑.id)}">${esc(跑["状态中文"])}</a> ${时间(跑["时间"])}` : "还没跑过"}</div>
    <div class="k">${!r["对应技能"] ? "聊天里:没登记对应技能"
      : r["聊天接管"] ? `聊天里:「${esc(r["对应技能中文"] || r["对应技能"])}」<b>工作流接管中</b> <button class="mini" data-tk="${esc(r.id)}" data-on="0">关掉</button>`
      : `聊天里:「${esc(r["对应技能中文"] || r["对应技能"])}」交给 harness <button class="mini" data-tk="${esc(r.id)}" data-on="1">打开接管</button>`}</div>
    <div class="af"><span class="k">更新于 ${时间(r["更新时间"])}</span><span class="grow"></span>
      <a href="${链("搭建")}">编辑</a> · <a href="${链("测试")}">运行</a> · <a href="${链("运行记录")}">看记录</a>
      · <a href="#" class="k" data-arch="${esc(r.id)}" title="行不删:跑过的运行、发布清单、调用记录都还指着它;还有活密钥 / 没跑完的运行 / 开着接管会被拦">归档</a></div>
  </div>`;
}

function 卡_agent(r) {
  const 链 = `#/agent/${encodeURIComponent(r.id)}`;
  return `<div class="appcard" data-kind="agent" data-id="${esc(r.id)}">
    <div class="ah"><span class="ico ag">智</span><div class="an"><a href="${链}"><b>${esc(r["名称"])}</b></a>
      <div class="k">Agent · ${esc(r["模型连接"] || "没选模型连接")}</div></div>
      ${r["校验状态"] === "通过" ? '<span class="pill ok">校验通过</span>' : `<span class="pill warn">${esc(r["校验状态"])}</span>`}</div>
    <div class="ad">${esc(r["用途"] || "还没写用途")}</div>
    <div class="k">最新版本:${r["最新冻结版本"] ? esc(r["最新冻结版本"]) : "还没冻结过"}
      · <span title="${esc(去粗(r["工具数说明"]))}">${r["工具数"]} 个候选工具</span></div>
    <div class="k" title="${esc(去粗(r["生产引用说明"]))}">线上(生产):<span class="stale">还没接</span></div>
    <div class="af"><span class="grow"></span><a href="${链}">配置</a></div>
  </div>`;
}

async function 页_工作室(类, 页) {
  页 = Math.max(1, parseInt(页, 10) || 1);
  $("#main").innerHTML = `<div class="head"><div><h1>工作室</h1>
      <div class="sub">这个项目里的应用:按固定步骤跑的工作流、模型自己决定下一步的 Agent,以及聊天站里的岗位助手。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const [流, 智, 聊] = await Promise.all([["all", "workflow"].includes(类) ? 请求(`${P()}/workflows?page=${页}`) : null,
                                        ["all", "agent"].includes(类) ? 请求(`${P()}/agents?page=${页}`) : null,
                                        // 聊天助手一个岗位一个,不分页:只在第 1 页摆
                                        ["all", "chat"].includes(类) && 页 === 1 ? 请求(`${P()}/chat-assistants`) : null]);
    // 「全部」两种各翻各的同一页码:页数取大的那个,翻过了一种的尾页,那一种这页就没有卡(下面的说明写着各几条)
    const 们 = [流, 智].filter(Boolean);
    const 翻 = { 页, 页数: 们.some((d) => d["页数"] == null) ? null : Math.max(...们.map((d) => d["页数"])),
                total: 们.some((d) => d.total == null) ? null : 们.reduce((a, d) => a + d.total, 0) };
    const 卡们 = [...((聊 && 聊.items) || []).map(卡_聊天助手), ...((流 && 流.items) || []).map(卡_工作流),
                 ...((智 && 智.items) || []).map(卡_agent)];
    const 新 = `<button class="appcard new" id="new"><b>+ 创建应用</b>
        <span class="k">选一种类型:工作流 / 对话流 / 聊天助手 / Agent / 文本生成</span></button>`;
    // 空的时候也要一句人话(冒烟对账按结构判:state 块带标题和说明)
    const 空 = 卡们.length || 页 > 1 ? "" : 状态("", 类 === "agent" ? "还没有 Agent" : 类 === "workflow" ? "还没有工作流"
        : 类 === "chat" ? "还没有聊天助手" : "还没有应用",
      类 === "chat" ? "聊天助手不在这里新建 —— 它们是聊天站代码里的岗位,用 tools/import_chat_assistant.py 导进来(店长助手导在「澜绣」项目里)。"
        : "点「创建应用」选一种类型。工作流从模板起(音频整理 / 文本处理 / 空白);模板**只预填草稿** —— 不调模型、不绑生产环境。").html;
    $("#list").innerHTML = `${空}<div class="appcards">${新}${卡们.join("")}</div>${页码条(翻)}
      <div class="note">${[[流, "工作流"], [智, "Agent"]].filter((x) => x[0]).map(([d, 名]) =>
          `${名} ${d.total != null ? `共 ${d.total}` : "总数不知道"}(这一页 ${d.items.length})`).join(" · ")}。
        「线上(生产)」之外的版本都只是<b>候选</b> —— 要在「版本与发布」里发到生产(生产要审核)才算上线。
        ${流 ? "<br>「聊天里」<b>默认交给 harness</b>(聊天站的技能自己做);打开接管后改为发起这条工作流<b>生产环境里的那一版</b>,同一个技能同时只能被一条工作流接管。" : ""}
        ${聊 ? `<br>聊天助手:${md(聊.note)}` : ""}
        ${智 ? "<br>Agent 的「候选工具」数只表示授权候选集合的规模 —— 规格 §9.1 明写<b>不按工具数量给 Agent 打能力强弱分</b>。" : ""}</div>`;
    $("#new").onclick = 弹_新建应用;
    挂页码($("#list"), (n) => { location.hash = `#/studio/${类}/${n}`; });
    // 归档(11-24 包二):接口 11-13 就有、带三道闸(活密钥 / 没跑完的运行 / 开着接管 → 409),前端一直没按钮,只能靠脚本清。
    // 要写理由(进审计);被闸拦下就把接口的话原样显示 —— 它说清了先去哪儿解
    $("#list").querySelectorAll("[data-arch]").forEach((a) => {
      a.onclick = async (ev) => {
        ev.preventDefault();
        const 理由 = await 问一句("归档这条工作流?", "行不删:跑过的运行、发布清单、调用记录都还指着它,只是不再出现在列表里。<br>还有没吊销的访问密钥、没跑完的运行、开着的聊天接管,会被拦下来并告诉你先去哪儿解。",
          { 输入: "归档理由(进审计)", 必填: true, 确定: "归档" });
        if (理由 === null || 理由 === false || 理由 === undefined) return;
        try {
          const r = await 请求(`${P()}/workflows/${encodeURIComponent(a.dataset.arch)}/archive`, { method: "POST", body: JSON.stringify({ 理由 }) });
          if (r && r.note) alert(r.note);
          页_工作室(类, 页);
        } catch (e) { 报错(e); }
      };
    });
    $("#list").querySelectorAll("[data-tk]").forEach((b) => {
      b.onclick = async () => {   // 11-08 用户拍:接管开关一点就改线上真客户的行为 → 先确认
        const 开 = b.dataset.on === "1";
        if (!(await 问一句(开 ? "打开聊天接管?" : "关掉聊天接管?", 开 ? "打开后,聊天站碰到这件事会改为发起这条工作流<b>生产环境里的那一版</b> —— 线上真客户马上受影响。" : "关掉后,聊天站改回用技能自己判断怎么做 —— 线上真客户马上受影响。", { 确定: 开 ? "打开接管" : "关掉接管" }))) return;
        b.disabled = true; await 拨接管(b.dataset.tk, 开); 页_工作室(类, 页); };
    });
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* 创建应用:先选类型(照 Dify)。没接上的三种摆出来、灰着、写明为什么 —— 点不了的东西不藏,藏了人会以为「没这功能」 */
function 弹_新建应用() {
  弹层("创建应用", `<div class="k">选一种应用类型</div>
    <div class="apptypes">${应用类型.map(([k, 名, 字, 说, fn, 为什么]) => `<button class="apptype${fn ? "" : " off"}" data-type="${k}"
        ${fn ? "" : `aria-disabled="true" title="${esc(为什么)}"`}>
        <span class="ico">${字}</span><b>${esc(名)}</b><span class="k">${esc(说)}</span>
        ${fn ? "" : `<span class="why">${esc(为什么)}</span>`}</button>`).join("")}</div>`);
  document.querySelectorAll(".apptype").forEach((b) => {
    const 项 = 应用类型.find((x) => x[0] === b.dataset.type);
    b.onclick = () => { if (!项[4]) return; 关弹层(); 项[4](); };
  });
}

async function 拨接管(wid, 开, 技能) {
  // 拿最新的 revision 再改 —— 两个人同时拨,后到的不许悄悄盖掉先到的(PATCH /workflows/{id} 要 If-Match)
  try {
    const d = await 请求(`${P()}/workflows/${encodeURIComponent(wid)}`);
    return await 请求(`${P()}/workflows/${encodeURIComponent(wid)}`, { method: "PATCH",
      headers: { "If-Match": String(d.revision) },
      body: JSON.stringify(Object.assign({ 名称: d["名称"], 用途: d["用途"], 负责人: d["负责人"], 聊天接管: 开 },
        技能 === undefined ? {} : { 对应技能: 技能 || null })) });
  } catch (e) { 报错(e); return null; }
}

async function 弹_新建工作流() {
  let t;
  try { t = await 请求(`${P()}/workflow-templates`); } catch (e) { return 报错(e); }
  const 卡 = (m, i) => `<label class="tpl">
      <input type="radio" name="tpl" value="${esc(m["名"])}" ${i === 0 ? "checked" : ""}>
      <b>${esc(m["名"])}</b> ${m["能直接跑吗"] ? '<span class="pill ok">资源齐了</span>'
        : '<span class="pill warn">待配置</span>'}
      <div class="k">${esc(m["说明"])}</div>
      ${(m["步骤"] || []).length ? `<div class="k">步骤:${esc(m["步骤"].join(" → "))}</div>` : ""}
      ${(m["需要的资源"] || []).map((x) => `<div class="k">${x["有了吗"] ? "✅" : "⚠️"} ${esc(x["名"])}
          ${x["有了吗"] ? "" : `—— ${esc(x["怎么补"])}`}</div>`).join("")}
    </label>`;
  弹层("新建工作流", `
    <label class="f">名称</label><input id="nw-n" placeholder="例如:门店录音整理">
    <label class="f">用途(一句话:谁用、解决什么)</label>
    <input id="nw-p" placeholder="例如:从录音整理客户需求,核对后写进跟进">
    <label class="f">从哪个模板起</label>
    ${(t.items || []).map(卡).join("")}
    <div class="note">模板<b>只预填草稿</b>:不调模型、不绑生产环境。标「待配置」的也能建,
      建完在「搭建」里补上缺的那几项。</div>
    <div class="acts"><button class="pri" id="nw-ok">创建</button> <button id="nw-no">取消</button>
      <button id="nw-import" title="用「版本与发布」页导出的 JSON 备份建一条新流程(只建草稿)">从备份导入…</button></div>`);
  $("#nw-no").onclick = 关弹层;
  $("#nw-import").onclick = () => 弹_导入备份({ 覆盖: false });
  $("#nw-ok").onclick = async () => {
    const 名 = $("#nw-n").value.trim();
    if (!名) { $("#nw-n").focus(); return; }
    const 模板 = (document.querySelector('input[name="tpl"]:checked') || {}).value || "空白";
    try {
      const d = await 请求(`${P()}/workflows`, { method: "POST",
        body: JSON.stringify({ 名称: 名, 用途: $("#nw-p").value.trim() || null, 模板 }) });
      关弹层();
      location.hash = `#/workflow/${encodeURIComponent(d.id)}/搭建`;
    } catch (e) { 报错(e); }
  };
}

/* ── 详情:六个页签 ───────────────────────────────────────────── */
let 图态 = null;   // { wid, 名称, 用途, 负责人, 定义, 布局, revision, 选中, 报告, 脏, 页签, 资源, … }

async function 页_画布(路) {
  const [wid, 签] = String(路).split("/");
  // 同一条工作流切页签:**不重新拉**,未保存的改动跟着走(切个页签就把改动丢了,比不让切还糟)
  if (!(图态 && 图态.wid === wid)) {
    const [d, 资源] = await Promise.all([
      请求(`${P()}/workflows/${encodeURIComponent(wid)}`),
      请求(`${P()}/workflow-resources`).catch(() => ({ 模型: [], 处理要求: [], 工具: [], 角色: [], 拉取失败: true })),
    ]);
    图态 = { wid, 名称: d["名称"], 用途: d["用途"], 负责人: d["负责人"], 信息rev: d["revision"],
             对应技能: d["对应技能"], 聊天接管: d["聊天接管"], 可接管技能: d["可接管技能"],
             定义: d["草稿"]["定义"] || { nodes: [], edges: [] },
             布局: d["草稿"]["布局"] || {}, revision: d["草稿"]["revision"],
             节点库: d["节点库"], 版本们: d["版本们"], 选中: null, 面板页: "设置", 视图: "步骤",
             报告: d["草稿"]["上次校验报告"], 脏: false, 底Tab: "问题", 事件: [], 资源,
             最近测试: null,
             // 检查报告对着哪一份定义(§10.4):定义变了报告就标过期,不清掉也不冒充当前。
             // 服务端说「改过之后没再校验」时,载入的这份报告本来就过期了
             报告定义: d["校验状态"] === "改过之后没再校验" ? null : JSON.stringify(d["草稿"]["定义"] || { nodes: [], edges: [] }),
             报告rev: d["草稿"]["revision"], 编辑序号: 0, 已存序号: 0, 保存态: "已保存" };
  }
  图态.页签 = 工作流页签.includes(decodeURIComponent(签 || "")) ? decodeURIComponent(签) : "概览";
  画_画布();
}

/* 编排页是独立的全屏页(用户 10-26 拍):不带后台菜单,顶栏一行。地址仍是 #/workflow/<id>/搭建 ——
 * 撤销、保存、冲突、离开拦截这一套全挂在「搭建」上,换地址等于把它们全迁一遍 */
function 画_编排页() {
  const g = 图态, 链 = (t) => `#/workflow/${encodeURIComponent(g.wid)}/${encodeURIComponent(t)}`;
  document.body.classList.add("wf-full");
  $("#main").innerHTML = `
    <div class="wfbar" role="toolbar" aria-label="编排">
      <a class="back" href="${链("概览")}" title="回到这条工作流的概览">← 返回</a>
      <b class="nm" title="${esc(g.用途 || "")}">${esc(g.名称)}</b>
      <span id="savest" role="status" aria-live="polite"></span>
      <span class="grow"></span>
      <span class="seg" role="group" aria-label="视图"><button id="vw-s">列表</button><button id="vw-g">流程图</button></span>
      <button id="issues" hidden></button>
      <button id="trun" title="在右侧填一条输入试跑;跑完每一步标上结果" aria-pressed="false">▶ 试运行</button>
      <button id="rhist" title="这条流程最近的运行;点一次运行在画布上看各步结果(只读)" aria-haspopup="true">🕘 运行历史</button>
      <button class="pri" id="freeze">生成版本</button>
      <details class="more"><summary aria-label="更多">⋯</summary><div class="menu">
        <button id="save">保存草稿</button>
        <button id="v">检查配置</button>
        <label title="只存草稿:停顿 1.5 秒后保存;不运行、不发布"><input type="checkbox" id="autosave"> 自动保存草稿</label>
        <a href="${链("版本与发布")}">版本与发布</a><a href="${链("设置")}">设置</a><a href="${链("运行记录")}">运行记录</a>
      </div></details>
    </div>
    <div id="tabbody"></div>`;
  $("#save").onclick = 做_存草稿;
  $("#autosave").checked = 自动保存开着();
  $("#autosave").disabled = !能改图();
  $("#autosave").onchange = (e) => { try { localStorage.setItem("wf.自动保存", e.target.checked ? "1" : "0"); } catch (er) { /* 存不了就只对这一页有效 */ }
    if (e.target.checked) 自动保存排队(); };
  $("#v").onclick = 做_校验;
  $("#freeze").onclick = 弹_准备发布;
  $("#trun").onclick = () => { 图态.试面板 = !图态.试面板; 画_面板(); $("#trun").setAttribute("aria-pressed", String(!!图态.试面板)); };
  $("#issues").onclick = () => { 图态.问题开 = !图态.问题开; 图态.底Tab = "问题"; 画_问题(); 摆问题区(); };
  $("#rhist").onclick = () => 弹_运行历史($("#rhist"));
  画_搭建(); 画_底栏(); 画_保存状态(); 画_回放条();
  // 新建的空白流程第一次进来弹「怎么开始」(照 Dify);只弹一次,关掉了画布上的虚线占位还在,点它再弹。
  // 引导是锦上添花:它弹不出来**不许连累编排页**(11-20 页面冒烟的桩里弹层抛了,整页被报成空壳)
  if (开始待配置() && !g.开始引导过 && 能改图()) {
    g.开始引导过 = true;
    try { 弹_配置开始(); } catch (e) { console.warn("开始引导没弹出来(不影响编排):", e && e.message); }
  }
}

function 画_画布() {
  const g = 图态;
  if (g.页签 === "搭建") return 画_编排页();
  document.body.classList.remove("wf-full");
  画_应用侧栏(g);
  $("#main").innerHTML = `
    <div class="crumb">工作室 / <a href="#/studio/workflow">工作流</a> / ${esc(g.名称)}</div>
    <div class="head"><div><h1>${esc(g.名称)}</h1>
      <div class="sub"><span id="savest" role="status" aria-live="polite"></span>
        ${g.用途 ? ` · ${esc(g.用途)}` : ""}</div></div>
      <div><a class="btn pri" id="edit" href="#/workflow/${encodeURIComponent(g.wid)}/搭建">编辑编排</a>
        <button id="freeze">生成版本</button></div></div>
    <div id="tabbody"></div>
    <div class="footbar"><span id="fb"></span></div>`;
  $("#freeze").onclick = 弹_准备发布;
  ({ 概览: 画_概览, 搭建: 画_搭建, 测试: 画_测试, 运行记录: 画_运行记录, 版本与发布: 画_版本, 访问入口: 画_访问入口, 设置: 画_设置 }
    [g.页签] || 画_概览)();
  画_底栏(); 画_保存状态();
}

/* 应用详情侧栏(10-28 照 Dify,二期第 3 项;适配分析 5.5「照抄」):进到一个应用里,左边主导航换成这个应用自己的一列。
 * 地址不变(#/workflow/<id>/<页签>),只换显示名 —— 改地址要把撤销 / 离开拦截 / 测试全迁一遍,换来的只是一个词。
 * 没做的三项摆着、写明什么时候做,不藏。离开这条工作流时 路由() 会重画主导航 */
const 应用侧栏项 = [["搭建", "编排"], ["概览", "概览"], ["测试", "测试"], ["运行记录", "日志"], ["版本与发布", "部署"], ["访问入口", "访问 API"], ["设置", "设置"]];
const 应用侧栏待做 = [
  ["标注", "三期:人对每次运行的结果打标,回流成样本"],
  ["监测", "三期:这个应用自己的监测页,加一张 Dify 没有的「业务真完成率」(真写进了澜绣,不只是运行成功)"]];
function 画_应用侧栏(g) {
  const 链 = (t) => `#/workflow/${encodeURIComponent(g.wid)}/${encodeURIComponent(t)}`;
  $("#side").innerHTML = `<a class="back" href="#/studio/workflow">← 工作室</a>
    <div class="apphead"><span class="ico">流</span><div class="an"><b>${esc(g.名称)}</b><div class="k">工作流</div></div></div>
    ${应用侧栏项.map(([k, 名]) => `<a href="${链(k)}" data-tab="${esc(k)}"${k === g.页签 ? ' class="on"' : ""}${名 !== k ? ` title="原来叫「${k}」"` : ""}>${名}</a>`).join("")}
    <div class="grp">还没做</div>
    ${应用侧栏待做.map(([名, 为什么]) => `<a class="todo" title="${esc(为什么)}">${名}</a>`).join("")}`;
}

function 画_底栏() {
  const g = 图态, r = g.报告;
  const ib = $("#issues");   // 编排页没有底栏:「N 处要改」放顶栏,点开是下面的问题列表
  if (ib) {
    const 过 = 检查过期(), n = r && !r["通过"] ? r["阻断数"] : 0;
    ib.hidden = !r || (r["通过"] && !过);
    ib.className = n ? "warn" : "";
    ib.textContent = !r ? "" : 过 ? "配置改过,要重新检查" : n ? `⚠ ${n} 处要改` : `${r["警告数"]} 条提醒`;
    if (r && r["通过"] && !过 && r["警告数"]) ib.hidden = false;
  }
  if (!$("#fb")) return;
  $("#fb").innerHTML = g.脏
    ? "<b>有未保存的改动</b> —— 保存草稿不影响任何已生成的版本,也不影响线上。"
    : (r ? (r["通过"] ? "上次检查配置:<b>通过</b>"
            : `上次检查配置:<b>${r["阻断数"]} 处要改</b> / ${r["警告数"]} 条提醒(在编排页)`)
         : "还没检查过配置 —— 页面上看着没问题,不代替服务端检查");
}
function 标脏() {
  图态.脏 = true; 图态.编辑序号 = (图态.编辑序号 || 0) + 1;
  if (图态.保存态 !== "保存中" && 图态.保存态 !== "冲突") 图态.保存态 = "未保存";
  画_保存状态(); 画_底栏(); 自动保存排队();
  if (typeof 画_工具条态 === "function" && $("#cv")) 画_工具条态();
}

/* ── 保存状态(W02):未保存 / 保存中 / 已保存 rN / 失败 / 冲突 —— 一直看得见,**不靠提示消失代表成功** ── */
function 画_保存状态() {
  const el = $("#savest"); if (!el) return;
  const g = 图态, 态 = g.保存态;
  const 时 = g.存于 ? g.存于.toLocaleTimeString("zh-CN", { hour12: false }) : "";
  const 文 = { 已保存: 自动保存开着() && 时 ? `自动保存于 ${时} · 草稿 r${g.revision}` : `已保存 · 草稿 r${g.revision}`, 未保存: `有未保存的修改 · 草稿 r${g.revision}`,
    保存中: g.脏 && g.编辑序号 !== g.保存中序号 ? "保存中…(保存发出后你又改了,这些还没存)" : "保存中…",
    失败: "未保存成功,本页修改仍保留 —— 点「保存草稿」重试", 冲突: "其他人已更新这张图,你的修改仍在本页 —— 先处理冲突" }[态] || 态;
  el.textContent = 文;
  el.className = { 已保存: "ok", 未保存: "stale", 保存中: "stale", 失败: "err", 冲突: "err" }[态] || "";
  const b = $("#save"); if (b) b.disabled = 态 === "保存中" || !能改图();
}

/* ── 图编辑命令层(§12):所有改图的入口都从这里过 —— 记撤销、标未保存、判检查报告过期 ──
 * fn 返回 false = 这次不改(比如校验没过);fn 里抛错 = 回到改之前,不留半次。 */
function 能改图() {
  // 回放某次运行时画布只读(11-15,照 Dify「运行历史 → 只读回放,顶栏出『返回编辑模式』」)
  if (typeof 图态 !== "undefined" && 图态 && 图态.回放) return false;
  return typeof 我的角色 === "undefined" || 我的角色 === "editor" || 我的角色 === "admin";
}
/* 「x 分钟前」—— 运行历史里每一项的时间。现在 可传入(测试用),不传就是此刻 */
function 多久前(iso, 现在 = Date.now()) {
  const t = Date.parse(iso || ""); if (!Number.isFinite(t)) return "";
  const 秒 = Math.max(0, Math.round((现在 - t) / 1000));
  if (秒 < 60) return "刚刚";
  if (秒 < 3600) return `${Math.floor(秒 / 60)} 分钟前`;
  if (秒 < 86400) return `${Math.floor(秒 / 3600)} 小时前`;
  return `${Math.floor(秒 / 86400)} 天前`;
}
/* 运行历史弹层(11-15,工作流一期第五件;照 Dify 顶栏的时钟):这条流程最近 20 次运行,点一项 → 画布上回放那次各步的状态(只读) */
async function 弹_运行历史(锚) {
  const 旧 = $("#rh-pop"); if (旧 && 旧.isConnected) { 旧.remove(); return; }   // 再点一次 = 关
  let r;
  try { r = await 请求(`${P()}/execution-runs?workflow_id=${encodeURIComponent(图态.wid)}&limit=20`); }
  catch (e) { 报错(e); return; }
  const 全 = r["总数"] ?? r["total"] ?? (r.items || []).length;
  const 标 = { succeeded: "✅", failed: "❌", cancelled: "⏹", waiting_approval: "⏸", waiting_external: "⏸", running: "⏳", queued: "⏳" };
  const m = document.createElement("div");
  m.className = "wfmenu rhpop"; m.id = "rh-pop"; m.setAttribute("role", "menu");
  m.innerHTML = (r.items || []).length
    ? (r.items || []).map((x, i) => `<button role="menuitem" data-rh="${esc(x.id)}" data-no="${全 - i}">${标[x["执行状态"]] || "·"} 第 ${全 - i} 次 · ${esc(x["种类"] || "")}
        <span class="k">${esc(x["请求人"] || "")} · ${esc(多久前(x["开始"]))} · ${esc(x["执行状态中文"] || x["执行状态"])}</span></button>`).join("")
    : `<div class="k">这条流程还没跑过。点「▶ 试运行」跑一次,这里就有了。</div>`;
  document.body.appendChild(m);
  const b = 锚 && 锚.getBoundingClientRect ? 锚.getBoundingClientRect() : { left: 0, bottom: 0 };
  m.style.left = b.left + "px"; m.style.top = b.bottom + 4 + "px";
  m.querySelectorAll("[data-rh]").forEach((x) => { x.onclick = () => { m.remove(); 回放运行(x.dataset.rh, +x.dataset.no); }; });
  setTimeout(() => document.addEventListener("pointerdown", (e) => { if (!m.contains(e.target) && e.target !== 锚) m.remove(); }, { once: true }), 0);
}
async function 回放运行(rid, 序号) {
  if (图态.脏) { 轻提示("还有没保存的修改 —— 先保存,再看运行历史(回放时画布只读)"); return; }
  let d;
  try { d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`); } catch (e) { 报错(e); return; }
  图态.回放 = { rid, 序号, 态: d["执行状态中文"] };
  记运行态(d);
  画_回放条(); 重画全部();
}
function 退出回放() {
  图态.回放 = null; 图态.运行态 = {};
  画_回放条(); 重画全部();
}
function 画_回放条() {
  let 条 = $("#rh-bar");
  const g = 图态;
  if (!g || !g.回放) { if (条 && 条.isConnected) 条.remove(); return; }
  if (!条 || !条.isConnected) {
    条 = document.createElement("div"); 条.id = "rh-bar"; 条.className = "note rhbar"; 条.setAttribute("role", "status");
    const 体 = $("#tabbody"); if (体 && 体.parentNode && 体.parentNode.insertBefore) 体.parentNode.insertBefore(条, 体); else document.body.appendChild(条);
  }
  条.innerHTML = `正在看<b>第 ${esc(String(g.回放.序号 || ""))} 次运行</b>(${esc(g.回放.态 || "")})各步的结果 —— 画布只读。
    <button id="rh-exit" class="pri">返回编辑模式</button>`;
  const 钮 = 条.querySelector ? 条.querySelector("#rh-exit") : null; if (钮) 钮.onclick = 退出回放;
}
function 历史() { return 图态.历史 || (图态.历史 = 图逻辑.历史()); }
function 改图(名, fn, { 合并键 = null, 重绘 = true } = {}) {
  if (!能改图()) { 轻提示(图态 && 图态.回放 ? "正在回放运行记录(只读)—— 点上方「返回编辑模式」再改"
                                : "只读:你没有「改编排草稿」的权限 —— 可以查看、缩放、查找"); return false; }
  const g = 图态, 前 = 图逻辑.快照(g.定义, g.布局);
  let r;
  try { r = fn(); } catch (e) { 回到(前); throw e; }
  if (r === false) { 回到(前); if (重绘) 重画全部(); return false; }
  const 后 = 图逻辑.快照(g.定义, g.布局);
  if (前 === 后) return r;
  历史().记(名, 前, 后, 合并键);
  标脏();
  if (重绘) 重画全部();
  return r === undefined ? true : r;
}
function 回到(快照) { const o = JSON.parse(快照); 图态.定义 = o.定义; 图态.布局 = o.布局; }
function 撤销() {
  if (!能改图()) return;
  const x = 历史().撤销();
  if (!x) { 轻提示("没有可以撤销的编辑"); return; }
  回到(x.快照); if (typeof 清理选择 === "function") 清理选择(); 标脏(); 重画全部();
  轻提示(`已撤销:${x.名}`);
}
function 重做() {
  if (!能改图()) return;
  const x = 历史().重做();
  if (!x) { 轻提示("没有可以重做的编辑"); return; }
  回到(x.快照); if (typeof 清理选择 === "function") 清理选择(); 标脏(); 重画全部();
  轻提示(`已重做:${x.名}`);
}
function 重画全部() {
  if (!图态 || 图态.页签 !== "搭建" || !$("#pn")) { 画_底栏(); return; }
  if (图态.视图 === "流程图" && $("#steps")) 画_图(); else if ($("#steps")) 画_步骤();
  画_面板(); 画_问题(); 画_底栏();
}
const 检查过期 = () => !!(图态.报告 && 图态.报告定义 !== JSON.stringify(图态.定义));

/* 编辑区底部的结果提示 + 撤销入口(W29)。**自动消失不清撤销历史** */
let _提示时 = 0;
// 11-08 UI 检查:原来也叫「提示」,和上面的弹窗版重名 —— 后写的覆盖前面的,于是 17 处「提示(标题, 正文)」的正文
// 全被丢掉(发密钥 / 轮换密钥的原文不显示、发布被拦的理由不显示……)。底部小提示条改叫「轻提示」
function 轻提示(文, { 撤销: 可撤 = false } = {}) {
  let el = document.getElementById("wf-toast");
  if (!el) { el = document.createElement("div"); el.id = "wf-toast"; el.className = "wftoast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
  el.innerHTML = `<span>${esc(文)}</span>${可撤 && 能改图() ? ' <button id="wf-toast-u">撤销</button>' : ""}`;
  el.hidden = false;
  const u = document.getElementById("wf-toast-u"); if (u) u.onclick = () => { 撤销(); el.hidden = true; };
  clearTimeout(_提示时); _提示时 = setTimeout(() => { el.hidden = true; }, 6000);
}

/* 敏感节点:人工核对、写入类业务动作 —— 删的时候不提供快捷桥接(§7.1) */
function 是敏感节点(n) {
  if (n.type === "human") return true;
  if (n.type === "tool") { const t = 工具资源((n.config || {}).tool_version_id); return !t || t["读写"] !== "只读"; }
  return false;
}

/* 节点辅助:业务名、次级标签、缺了哪几项 */
const 节点 = (id) => 图态.定义.nodes.find((n) => n.id === id);
const 元 = (t) => 图态.节点库.find((x) => x["名"] === t) || {};
function 业务名(n) { return n.name || 步类型名[n.type] || n.type; }
function 工具资源(tv) { return (图态.资源.工具 || []).find((x) => x["版本id"] === tv); }
// HTTP 请求节点选的「工具连接」(capability_connections,11-16):列表来自 workflow-resources,密钥只给形状
function 工具连接(id) { return (图态.资源.工具连接 || []).find((x) => x.id === id); }
// 子工作流节点引的冻结版本(11-16 三期 3-3):列表来自 workflow-resources,带它要什么输入 / 返回什么
function 子流程版本(id) { return (图态.资源.工作流版本 || []).find((x) => x.id === id); }
function 次级标签(n) {
  const 在 = n.container && 图态 && 图态.定义 && 节点(n.container) ? ` · 在「${业务名(节点(n.container))}」里` : "";
  if (n.type === "tool") {
    const t = 工具资源((n.config || {}).tool_version_id);
    return (t ? `业务动作 · ${t["读写"]}` : "业务动作") + 在;
  }
  if (n.type === "http_request") {
    const k = 工具连接((n.config || {}).connection_id);
    return `HTTP 请求 · 只读${k ? ` · ${k["名"]}` : ""}` + 在;
  }
  if (n.type === "start") {
    if (开始待配置()) return "开始 · 还没配置怎么开始";
    const 式 = (n.config || {}).start_mode;
    // 定时触发器的卡片写「下次 …」(11-21 规划 2-1,照 Dify 卡片上的「下次执行时间」):取预览缓存,规则一改键就对不上、先不写,预览回来重画
    if (式 === "定时") {
      const 缓 = 图态 && 图态.定时预览 && 图态.定时预览.键 === JSON.stringify((n.config || {}).schedule_rule || {}) ? 图态.定时预览 : null;
      return `开始 · 定时触发器${缓 && 缓.下次 ? ` · 下次 ${时间(缓.下次)}` : ""}`;
    }
    return `开始 · ${开始方式名[式] || 开始方式名.用户输入}`;
  }
  return (步类型名[n.type] || n.type) + 在;
}
function 缺项(n) {
  return (元(n.type)["必填"] || []).filter((f) => {
    const v = (n.config || {})[f];
    return v === undefined || v === null || v === "" || (typeof v === "object" && !Object.keys(v).length);
  });
}
const 字段中文 = { title: "标题", file_prefix: "文件名前缀", template_version: "模板版本", connection_version_id: "用哪个模型", prompt_version_id: "这一步要完成什么(处理要求)",
  output_schema: "结果包含哪些内容", tool_version_id: "执行哪个业务动作", input_schema: "用户需要提供什么",
  branches: "满足什么条件", else_policy: "都不满足时怎么办", request_kind: "核对类型",
  candidate_roles: "谁来处理", expires_at_policy: "多久没处理就结束", operations: "怎么整理",
  knowledge_base_id: "查哪个资料库", retrieval_config_version_id: "怎么查", candidates: "汇合哪几路",
  output_field: "汇合后叫什么", agent_version_id: "用哪个 Agent", task_binding: "交给它的任务",
  sub_limits: "这一步的上限", bindings: "用到的数据", filter: "过滤", sort: "排序", limit: "只要前几个",
  item_output: "每一项交出什么", item_failure_policy: "某一项失败时", max_items: "最多做几项",
  connection_id: "用哪条工具连接", method: "方法", path: "路径", code: "代码", language: "语言",
  max_concurrency: "并发上限", wait_policy: "等待策略", workflow_version_id: "用哪一版子流程", input_mapping: "交给子流程什么" };
const 中文名 = (f) => 字段中文[f] || f;

/* 执行顺序:从开始沿边走;条件的每一路缩进一层。没接进流程的放最后 */
function 排步骤() {
  const g = 图态, 出 = [], 见 = new Set();
  const 后继 = (id) => (g.定义.edges || []).filter((e) => e.source === id);
  const 走 = (id, 深, 入口) => {
    if (!节点(id) || 见.has(id)) return;
    见.add(id); 出.push({ id, 深, 入口 });
    const 边 = 后继(id);
    if (节点(id).type === "condition") {
      边.forEach((e) => 走(e.target, 深 + 1, 图逻辑.分支名(e.branch_key)));
    } else {
      边.filter((e) => e.port !== "error").forEach((e) => 走(e.target, 深, null));
      边.filter((e) => e.port === "error").forEach((e) => 走(e.target, 深 + 1, "失败时"));
    }
  };
  const 起 = g.定义.nodes.find((n) => n.type === "start");
  if (起) 走(起.id, 0, null);
  const 散 = g.定义.nodes.filter((n) => !见.has(n.id)).map((n) => ({ id: n.id, 深: 0, 入口: null, 散: true }));
  return [...出, ...散];
}

/* ── 概览 ─────────────────────────────────────────────────────── */
async function 画_概览() {
  const g = 图态;
  const 起 = g.定义.nodes.find((n) => n.type === "start");
  const 终 = g.定义.nodes.find((n) => n.type === "end");
  const 字段表 = (sch) => Object.entries((sch || {}).properties || {}).map(([k, v]) =>
    `<li><b>${esc(v.title || k)}</b> <span class="k">${esc(k)} · ${esc((结果类型们.find((x) => x[0] === v.type) || [0, v.type])[1])}
      ${((sch.required || []).includes(k)) ? " · 必填" : ""}</span>${v.description ? ` —— ${esc(v.description)}` : ""}</li>`).join("")
    || '<li class="k">还没定义</li>';
  const 依赖 = g.定义.nodes.filter((n) => ["llm", "tool", "http_request", "human"].includes(n.type)).map((n) => {
    const 缺 = 缺项(n);
    let 用的 = "";
    if (n.type === "http_request") {
      const k = 工具连接(n.config.connection_id);
      用的 = k ? `工具连接:${esc(k["名"])}(${esc((k["允许的端点"] || [])[n.config.endpoint_index || 0] || "")})` : "工具连接:未选";
    } else if (n.type === "llm") {
      const m = (g.资源.模型 || []).find((x) => x["版本id"] === n.config.connection_version_id);
      const p = (g.资源.处理要求 || []).find((x) => x["版本id"] === n.config.prompt_version_id);
      用的 = `模型:${m ? esc(m["名"]) : "未选"} · 处理要求:${p ? esc(p["名"]) : "未选"}`;
    } else if (n.type === "tool") {
      const t = 工具资源(n.config.tool_version_id);
      用的 = t ? `${esc(t["名"])}(${esc(t["读写"])}${t["接入方式"] === "lanxiu_bridge" ? " · 由澜绣执行" : ""})` : "未选";
    } else {
      用的 = `谁来处理:${esc((n.config.candidate_roles || []).map((r) => (g.资源.角色.find((x) => x["码"] === r) || {})["中文"] || r).join("、") || "未选")}`;
    }
    return `<tr><td>${esc(业务名(n))}</td><td>${用的}</td>
      <td>${缺.length ? `<span class="pill warn">缺 ${缺.length} 项</span>` : '<span class="pill ok">配好了</span>'}</td></tr>`;
  }).join("");
  $("#tabbody").innerHTML = `
    <div class="two">
      <div class="card"><h3>这条流程做什么</h3>
        <div>${esc(g.用途 || "还没写用途 —— 在「设置」里补一句:谁用、解决什么")}</div>
        <div class="k">负责人 ${esc(g.负责人 || "—")} · 共 ${g.定义.nodes.length} 步</div>
        <h4>使用者要提供</h4><ul>${字段表(起 && 起.config.input_schema)}</ul>
        <h4>最后返回</h4><ul>${字段表(终 && 终.config.output_schema)}</ul></div>
      <div class="card"><h3>用到的资源</h3>
        ${依赖 ? `<table><thead><tr><th>步骤</th><th>用的是</th><th>状态</th></tr></thead><tbody>${依赖}</tbody></table>`
               : '<div class="k">这条流程不调模型、不调业务动作。</div>'}
        <h3>最近的运行</h3><div id="ov-runs" class="k">加载中…</div></div>
    </div>`;
  try {
    const r = await 请求(`${P()}/execution-runs?workflow_id=${encodeURIComponent(g.wid)}&limit=5`);
    $("#ov-runs").innerHTML = r.items.length ? r.items.map((x) =>
      `<div><a href="#/wfrun/${encodeURIComponent(x.id)}">${esc(x["执行状态中文"])}</a>
        <span class="k">${时间(x["开始"] || x["结束"])} · ${esc(x["停止原因"] || "")}</span></div>`).join("")
      : "还没跑过 —— 去「测试」跑一条。";
  } catch (e) { $("#ov-runs").textContent = "运行记录没拉到:" + e.message; }
}

/* ── 搭建 ─────────────────────────────────────────────────────── */
function 画_搭建() {
  const g = 图态;
  // 视图切换在顶栏(全屏编排页,10-26);两种视图改的是同一份定义,挪图上的位置只改画法
  $("#vw-s").className = g.视图 === "步骤" ? "on" : ""; $("#vw-g").className = g.视图 === "流程图" ? "on" : "";
  $("#vw-s").setAttribute("aria-pressed", String(g.视图 === "步骤")); $("#vw-g").setAttribute("aria-pressed", String(g.视图 === "流程图"));
  $("#tabbody").innerHTML = `
    <div class="wfbuild ${g.视图 === "流程图" ? "graph" : ""}">
      <div class="steps" id="steps"></div>
      <div class="wfpanel" id="pn"></div>
    </div>
    <div class="wfvarbar"><button id="vi-tg" aria-expanded="false">变量检查</button></div>
    <div class="wfvar" id="vi" hidden></div>
    <div class="wfbottom"><div class="body" id="bt"></div></div>`;
  $("#vi-tg").onclick = () => { 图态.变量开 = !图态.变量开; 画_变量检查(); };
  画_变量检查();
  // 切视图不丢配置、选中和定位(W07):两种视图读写同一份 图态
  $("#vw-s").onclick = () => { 图态.视图 = "步骤"; 画_搭建(); };
  $("#vw-g").onclick = () => { 图态.视图 = "流程图"; 画_搭建(); };
  if (g.视图 === "流程图") { if (图态.画 && 图态.选中) 图态.画.选 = new Set([图态.选中]); 画_图(); }
  else 画_步骤();
  画_面板(); 画_问题(); 摆问题区(); 挂面板拖宽();
}
// 右侧面板可拖宽,记住上次的宽度(10-26 方案 §2);只在全屏编排页
function 挂面板拖宽() {
  const 建 = document.querySelector(".wfbuild"), pn = $("#pn");
  if (!建 || !pn || !document.body.classList.contains("wf-full") || !pn.insertAdjacentHTML) return;
  let 宽 = 440; try { 宽 = +localStorage.getItem("wf.面板宽") || 440; } catch (e) { /* 读不到就用默认 */ }
  const 设 = (w) => { 宽 = Math.max(340, Math.min(720, Math.round(w))); 建.style.setProperty("--pw", 宽 + "px"); };
  设(宽);
  if (建.querySelector(".pgrip")) return;
  建.insertAdjacentHTML("beforeend", '<div class="pgrip" role="separator" aria-orientation="vertical" aria-label="拖动调整面板宽度" tabindex="0"></div>');
  const 把 = 建.querySelector(".pgrip");
  const 存 = () => { try { localStorage.setItem("wf.面板宽", String(宽)); } catch (e) { /* 存不了只影响下次 */ } };
  把.onpointerdown = (e) => {
    e.preventDefault(); 把.setPointerCapture(e.pointerId);
    const 右 = 建.getBoundingClientRect().right;
    把.onpointermove = (m) => 设(右 - m.clientX);
    把.onpointerup = () => { 把.onpointermove = null; 存(); };
  };
  把.onkeydown = (e) => { if (e.key === "ArrowLeft") { 设(宽 + 20); 存(); } if (e.key === "ArrowRight") { 设(宽 - 20); 存(); } };
}
// 编排页的问题列表默认收起,点顶栏「N 处要改」才展开(10-26:常驻底栏挤掉编排区);检查出了要改的会自动展开
function 摆问题区() {
  const wb = document.querySelector(".wfbottom");
  if (wb && document.body.classList.contains("wf-full")) wb.hidden = !图态.问题开;
  const ib = $("#issues"); if (ib) ib.setAttribute("aria-expanded", String(!!图态.问题开));
}

function 画_步骤() {
  const g = 图态, 坏 = {};
  (g.报告?.问题 || []).forEach((p) => { if (p.node_id && p["级别"] === "blocking") 坏[p.node_id] = true; });
  const 序 = 排步骤();
  let 号 = 0;
  $("#steps").innerHTML = 序.map((s) => {
    const n = 节点(s.id), 缺 = 缺项(n);
    号 += 1;
    const 头 = g.选中 === s.id ? '<div class="step sel"' : '<div class="step"';
    return `${s.入口 ? `<div class="k" style="margin-left:${s.深 * 18}px">↳ ${esc(s.入口)}</div>` : ""}
      ${s.散 && 序.findIndex((x) => x.散) === 序.indexOf(s) ? '<h4>还没接进流程</h4>' : ""}
      ${头} style="margin-left:${s.深 * 18}px" data-id="${esc(s.id)}">
        <button class="t" data-sel="${esc(s.id)}">${号}. ${esc(业务名(n))}${同名后缀(n)}</button>
        <span class="pill">${esc(次级标签(n))}</span>
        ${缺.length ? `<span class="pill warn">缺 ${缺.length} 项</span>` : ""}${运行标(s.id)}
        ${坏[s.id] ? '<span class="pill fail">有要改的</span>' : ""}
        <span class="acts">
          ${n.type === "end" || !能改图() ? "" : `<button data-after="${esc(s.id)}" title="在此后添加一步" aria-label="在「${esc(业务名(n))}」后添加一步">＋</button>`}
          ${n.type === "start" || !能改图() ? "" : `<button data-del="${esc(s.id)}">删除</button>`}
        </span></div>`;
  }).join("") + `<div class="note">按执行顺序排。「在此后添加」会把新的一步接在这个出口和它原来的下一步之间;
    要改去向,在右边「设置」最下面的「下一步」里选。删除不会自动接通前后步骤。</div>
    ${能改图() ? `<div class="acts"><button id="st-undo" ${历史().能撤() ? "" : "disabled"}>撤销${历史().能撤() ? ":" + esc(历史().下一撤()) : ""}</button>
      <button id="st-redo" ${历史().能重() ? "" : "disabled"}>重做</button></div>` : ""}`;
  if ($("#st-undo")) { $("#st-undo").onclick = 撤销; $("#st-redo").onclick = 重做; }
  $("#steps").querySelectorAll("[data-sel]").forEach((b) => {
    b.onclick = () => { 图态.选中 = b.dataset.sel; if (图态.画) 图态.画.选 = new Set([b.dataset.sel]); 画_步骤(); 画_面板(); };
  });
  $("#steps").querySelectorAll("[data-after]").forEach((b) => { b.onclick = () => 弹_在此后添加(b.dataset.after); });
  $("#steps").querySelectorAll("[data-del]").forEach((b) => { b.onclick = () => 弹_删除步骤(b.dataset.del); });
}

/* 出口:这一步从哪几个口出去(普通 = 成功;条件 = 每一路 + 都不满足;能失败的再加「失败时」) */
function 出口们(n) {
  if (n.type === "end") return [];
  if (n.type === "condition") {
    return [...(n.config.branches || []).map((b) => ({ port: "branch", branch_key: b.key, 名: 图逻辑.分支名(b.key) })),
            { port: "branch", branch_key: "else", 名: "都不满足" }];
  }
  if (n.type === "loop" || n.type === "foreach" || n.type === "classifier" || n.type === "parallel") return 图逻辑.出口们(n, 元);   // 进循环体 / 循环结束后 / 失败时;并行每条支路一个 —— 和画布同一份
  const 口 = [{ port: "success", branch_key: null, 名: "完成后" }];
  if ((元(n.type)["端口"] || []).includes("error")) 口.push({ port: "error", branch_key: null, 名: "失败时" });
  return 口;
}
const 同口 = (e, o) => e.port === o.port && (e.branch_key || null) === (o.branch_key || null);

function 弹_在此后添加(id) {
  const n = 节点(id), 口们 = 出口们(n);
  const 可加 = ["llm", "tool", "http_request", "human", "condition", "transform", "retrieve", "merge", "answer", "loop", "classifier", "extractor", "template", "assigner", "list_operator", "doc_extractor", "foreach", "parallel", "subworkflow", "code"]
    .filter((t) => (图态.节点库.find((x) => x["名"] === t) || {})["可用"]);
  弹层(`在「${业务名(n)}」之后添加一步`, `
    ${口们.length > 1 ? `<label class="f">从哪个出口接</label><select id="af-p">${口们.map((o, i) =>
        `<option value="${i}">${esc(o.名)}</option>`).join("")}</select>` : ""}
    <label class="f">加什么</label>
    ${可加.map((t, i) => `<label class="tpl"><input type="radio" name="af-t" value="${t}" ${i === 0 ? "checked" : ""}>
        <b>${esc(步类型名[t])}</b> <div class="k">${esc(去粗((元(t)["说明"] || "")).slice(0, 90))}</div></label>`).join("")}
    <div class="note">新的一步会接在这个出口和它原来的下一步之间 —— 原来的线不会断。</div>
    <div class="acts"><button class="pri" id="af-ok">添加</button> <button id="af-no">取消</button></div>`);
  $("#af-no").onclick = 关弹层;
  $("#af-ok").onclick = () => {
    const t = (document.querySelector('input[name="af-t"]:checked') || {}).value;
    const 口 = 口们[+(($("#af-p") || {}).value || 0)];
    if (!t || !口) return;
    关弹层(); 加节点(t, { 在后: id, 口 });
  };
}

function 默认配置(类型) {
  return { start: { input_schema: { type: "object", properties: {}, required: [] } },
           end: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} },
           condition: { branches: [], else_policy: "fail" },
           merge: { candidates: [], output_field: "out" },
           human: { request_kind: "核对", candidate_roles: ["approver", "admin"], allowed_fields: ["定稿"],
                    expires_at_policy: { 小时: 48, 到期: "fail" }, payload_binding: {} },
           llm: { bindings: {}, output_schema: { type: "object", properties: { text: { type: "string" } },
                  required: ["text"], additionalProperties: false } },
           tool: { bindings: {} },
           // HTTP 请求(11-16 三期 3-1):方法默认 GET(一期只开 GET/HEAD);连接 / 路径不预填 —— 检查配置会报「还没选」「没写路径」,不是手写的
           http_request: { method: "GET", query: {}, headers: {}, bindings: {} },
           answer: { template: "", bindings: {} },
           template: { template: "", bindings: {} },
           assigner: { assignments: [] },
           list_operator: { bindings: {} },
           doc_extractor: { bindings: {} },
           foreach: { bindings: {}, item_failure_policy: "fail" },
           // 并行与汇总(11-16 三期 3-2):一期并发上限固定 1(串行实现);支路不预填 —— 检查配置会报「还没加支路」
           parallel: { branches: [], max_concurrency: 1, wait_policy: "all_required" },
           // 子工作流(11-16 三期 3-3):版本不预填;上限留空 = 跟父流程一样
           subworkflow: { input_mapping: {}, sub_limits: {} },
           // 代码执行最小版(11-20 三期 3-4):给一个能跑的骨架;结果先空着 —— 检查配置会报「没声明返回什么」,不替人猜
           markdown_export: { bindings: {}, title: "" },   // 11-21:正文在「用到的数据」里绑;标题不填就用流程名
           code: { language: "python", code: "def main(**inputs):\n    # inputs 里是「输入变量」里配的那几项\n    return {}\n", input_mapping: {},
                   output_schema: { type: "object", properties: {}, required: [] }, sub_limits: { timeout_seconds: 5, memory_mb: 64 } },
           extractor: { parameters: [{ name: "", type: "string", description: "", required: false }], bindings: {}, instruction: "" },
           classifier: { classes: [{ key: "类别一", 说明: "" }, { key: "类别二", 说明: "" }], bindings: {}, instruction: "" },
           transform: { operations: [], output_schema: { type: "object" } },
           loop: { max_iterations: 3, condition: { op: "equals", left: null, right: { source: "constant", value: true } },
                   loop_state: { 还要做: { initial: true } } } }[类型] || {};
}

/* 在某个出口后面加一步:新的一步接在这个出口和它原来的下一步之间 —— **加节点、删原线、加两条线是一个原子动作**,撤销一次全回来(§5.2) */
function 加节点(类型, 接 = null) {
  const g = 图态;
  let id = null;
  改图(`添加「${步类型名[类型] || 类型}」`, () => {
    id = 图逻辑.新id(g.定义, 类型);
    g.定义.nodes.push({ id, type: 类型, name: 步类型名[类型], config: JSON.parse(JSON.stringify(默认配置(类型))) });
    g.定义.edges = g.定义.edges || [];
    if (接) {
      const 原 = g.定义.edges.find((e) => e.source === 接.在后 && 图逻辑.同口(e, 接.口));
      if (原 && !图逻辑.能插入吗(类型, 元).可以) {
        轻提示(`没加:${图逻辑.能插入吗(类型, 元).为什么}`); return false;
      }
      if (原) 图逻辑.插入到线(g.定义, 图逻辑.边键(原), g.定义.nodes.pop(), 元);
      else 图逻辑.连(g.定义, 接.在后, 接.口, id);
    }
    const 前 = (接 && g.布局[接.在后]) || null;
    const 已 = Object.keys(g.布局).filter((k) => !k.startsWith("$")).length;   // $线 折点、$注释 都不是步骤
    g.布局[id] = 前 ? { x: 前.x + 200, y: 前.y + 90 }
                   : { x: 40 + (已 % 4) * 200, y: 40 + Math.floor(已 / 4) * 110 };
    g.选中 = id; g.面板页 = "设置";
  }, { 重绘: false });
  if (id && 节点(id)) { if (g.画) g.画.选 = new Set([id]); if (g.页签 === "搭建") 画_搭建(); }
}

/* 更改节点(11-21,规划 1-5 节点菜单最后一项,照 Dify「更改节点:换类型不断线」):
 * 同一张卡换成别的类型 —— 进来的线全保留;出去的线按新类型的出口对得上的留(「完成后」「失败时」这两种大多数类型都有),
 * 对不上的(分支 / 支路 / 循环体这类)删掉并说清删了几条;配置换成新类型的默认配置(两种类型的配置不通用,硬留只会留一堆检查配置报红的旧键);
 * 名字:还是类型默认名的就跟着换,人改过的保留。「开始」「输出」不能换(一张图各只有一个、位置特殊)。可撤销。 */
const 不能换类型 = new Set(["start", "end"]);
function 可换成的类型(n) {
  const 出 = [];
  (typeof 菜单节点组 !== "undefined" ? 菜单节点组 : []).forEach(([, 项]) => 项.forEach(([t, 名]) => {
    if (!t || t === n.type || 不能换类型.has(t)) return;
    const 可 = (元(t) || {})["可用"] && !(t === "code" && typeof 我的角色 !== "undefined" && 我的角色 !== "admin");
    if (可) 出.push([t, 步类型名[t] || 名]);
  }));
  return 出;
}
function 更改节点类型(id, 新类型) {
  const g = 图态, n = 节点(id);
  if (!能改图() || !n || 不能换类型.has(n.type) || 不能换类型.has(新类型) || n.type === 新类型) return false;
  if (!可换成的类型(n).some(([t]) => t === 新类型)) { 轻提示(`不能换成「${步类型名[新类型] || 新类型}」`); return false; }
  const 旧名 = 步类型名[n.type] || n.type;
  let 删了 = [];
  const 做 = 改图(`「${业务名(n)}」换成「${步类型名[新类型]}」`, () => {
    const 旧类型 = n.type;
    n.type = 新类型;
    n.config = JSON.parse(JSON.stringify(默认配置(新类型)));
    if (!n.name || n.name === 步类型名[旧类型]) n.name = 步类型名[新类型];
    const 新口 = 图逻辑.出口们(n, 元);
    删了 = (g.定义.edges || []).filter((e) => e.source === id && !新口.some((o) => 图逻辑.同口(e, o)));
    g.定义.edges = (g.定义.edges || []).filter((e) => !删了.includes(e));
    g.选中 = id; g.面板页 = "设置";
  }, { 重绘: false });
  if (做 === false) return false;
  if (g.画) g.画.选 = new Set([id]);
  if (g.页签 === "搭建") 画_搭建();
  const 引 = 引用了它的(id);
  轻提示(`已把「${旧名}」换成「${步类型名[新类型]}」,进来的线都保留` + (删了.length ? `;新类型没有「${删了.map((e) => 图逻辑.口名(e)).join("」「")}」出口,删了 ${删了.length} 条线` : "")
    + (引.length ? `;有 ${引.length} 步取它的结果,结果字段变了要重新核对` : ""), { 撤销: true });
  return true;
}
function 弹_更改节点(id) {
  const n = 节点(id);
  if (!能改图() || !n) return;
  if (不能换类型.has(n.type)) { 轻提示(`「${业务名(n)}」不能换类型(一条流程只有一个「${步类型名[n.type]}」)`); return; }
  const 可 = 可换成的类型(n);
  弹层(`「${esc(业务名(n))}」换成哪一类步骤?`, `
    <p class="k">换类型会保留进来的线和位置;出去的线按新类型的出口对得上的保留;这一步的配置换成新类型的默认配置(两种类型的设置不通用)。能撤销。</p>
    <div class="two">${可.map(([t, 名]) => `<button type="button" class="tpl" data-retype="${esc(t)}"><b>${esc(名)}</b><div class="k">${esc(去章节(去粗((元(t) || {})["说明"] || "")).slice(0, 80))}</div></button>`).join("")}</div>
    <div class="acts"><button id="rt-no">先不换</button></div>`);
  document.querySelectorAll("[data-retype]").forEach((b) => { b.onclick = () => { 关弹层(); 更改节点类型(id, b.dataset.retype); }; });
  $("#rt-no").onclick = 关弹层;
}

function 引用了它的(id) {
  // 别的步骤里有没有「取这一步的结果」—— 结构化引用一律是 {source:"node", node_id:id, …}
  const 找 = (v) => v && typeof v === "object"
    && (v.source === "node" && v.node_id === id || Object.values(v).some(找));
  return 图态.定义.nodes.filter((n) => n.id !== id && 找(n.config || {}));
}

function 弹_删除步骤(id) { 弹_删除([id]); }

/* 删除影响弹层(W28 · §7.1)。数量来自当前图,不是模板数字;**默认不自动接通前后步骤**。
 * 没有引用、没有连线的普通步骤直接删 + 可撤销,不逐次弹确认。 */
function 弹_删除(ids) {
  if (!能改图()) return;
  const g = 图态, 影 = 图逻辑.删除影响(g.定义, ids, 是敏感节点);
  // 名字**删之前**就记下来:删完再取,那一步已经不在图里了(2026-10-25 桩测试逮到的崩溃)
  const 名表 = {}; g.定义.nodes.forEach((n) => { 名表[n.id] = 业务名(n); });
  const 名 = (id) => 名表[id] || id;
  if (!影.要删.length) { 轻提示(影.跳过.map((x) => x.为什么).join(";") || "没有可删的步骤"); return; }
  const 做 = (桥接) => {
    改图(影.要删.length > 1 ? `删除 ${影.要删.length} 步` : `删除「${名(影.要删[0])}」`, () => {
      图逻辑.删节点(g.定义, g.布局, 影.要删, { 桥接, 元, 是敏感: 是敏感节点 });
      if (g.画) { 影.要删.forEach((x) => g.画.选.delete(x)); g.画.线 = null; }
      if (影.要删.includes(g.选中)) g.选中 = null;
    });
    轻提示(`已删除 ${影.要删.map(名).join("、") || ""}` + (影.跳过.length ? `;保留:${影.跳过.map((x) => x.为什么).join(";")}` : "")
      + (影.引用.length ? `;${影.引用.length} 处数据来源标成「原来源已删除」,要改` : ""), { 撤销: true });
  };
  const 简单 = !影.删边.length && !影.引用.length && !影.跳过.length && !影.删结束;
  if (简单) { 做(false); return; }
  const 名们 = 影.要删.map(名);
  弹层(影.要删.length > 1 ? `删除 ${影.要删.length} 步?` : `删除「${名们[0]}」?`, `
    <p>将删除:<b>${影.要删.length}</b> 个步骤、<b>${影.删边.length}</b> 条连线。</p>
    ${影.跳过.length ? `<p class="k">保留:${影.跳过.map((x) => esc(x.为什么)).join(";")}</p>` : ""}
    ${影.引用.length ? `<div class="state err"><b>影响:</b>${影.引用.map((r) =>
        `「${esc(名(r.节点id))}」正在用「${esc(名(r.引用的))}」的「${esc(r.字段 || r.路径)}」`).join(";")}
        <br>删后那些地方会标「原来源已删除」,<b>不会自动改成别的来源</b>;运行和生成候选版本前要改好。</div>` : ""}
    ${影.删结束 ? `<p class="k">⚠ 删掉「结束」后这条流程就没有合法的出口了,检查配置会报出来。</p>` : ""}
    ${影.敏感.length ? `<p class="k">「${esc(影.敏感.map(名).join("、"))}」是人工核对或写入类步骤 —— 不提供「接通前后步骤」,免得删掉核对后直接写入。</p>` : ""}
    <p>默认:删除步骤并断开关联线。后续步骤保留,需要重新选择数据来源。</p>
    <div class="acts"><button id="dl-no">取消</button>
      ${影.可桥接 ? `<button id="dl-br">删除并接通「${esc(名(影.可桥接.从.source))}」→「${esc(名(影.可桥接.到))}」</button>` : ""}
      <button class="pri danger" id="dl-ok">删除步骤</button></div>`);
  $("#dl-no").onclick = 关弹层;
  $("#dl-ok").onclick = () => { 关弹层(); 做(false); };
  if ($("#dl-br")) $("#dl-br").onclick = () => { 关弹层(); 做(true); };
  $("#dl-no").focus();
}

/* ── 右边表单 ─────────────────────────────────────────────────── */
let 控件表 = [];
const 挂控件 = (fn) => { 控件表.push(fn); return 控件表.length - 1; };

function 画_面板() {
  const g = 图态;
  控件表 = [];
  if (g.试面板 && document.body.classList.contains("wf-full")) {
    $("#pn").innerHTML = `<div class="phd"><h3 style="margin:0">试运行</h3><button id="tr-x" aria-label="关闭试运行面板">关闭</button></div><div id="trbox"></div>`;
    $("#tr-x").onclick = () => { 图态.试面板 = false; 画_面板(); const b = $("#trun"); if (b) b.setAttribute("aria-pressed", "false"); };
    画_测试($("#trbox"));
    return;
  }
  if (!g.选中 || !节点(g.选中)) {
    $("#pn").innerHTML = `<div class="k">在左边选一步,右边配置它。</div>`;
    return;
  }
  const n = 节点(g.选中);
  n.config = n.config || {};
  // 不分页签,从上到下分段(10-26 用户:横向切来切去、超出屏幕的太多);「高级」默认收起
  const 段 = (标, 键, 体) => `<section class="psec" data-sec="${键}"><h4 class="psh">${标}</h4>${体}</section>`;
  const 高开 = g.面板页 === "高级" || g.高级开;
  const 缺 = 缺项(n);
  const 问 = (g.报告?.问题 || []).filter((q) => q.node_id === n.id);
  $("#pn").innerHTML = `
    <h3 style="margin:0">${esc(业务名(n))}${同名后缀(n)}</h3><div class="k">${esc(次级标签(n))}</div>
    ${缺.length ? `<div class="note">还缺:${缺.map((f) => `<b>${esc(中文名(f))}</b>`).join("、")}</div>` : ""}
    ${(() => { const 失 = 图逻辑.失效引用(g.定义).filter((x) => x.节点id === n.id);
      // 删除后「随即标记并定位」(§6.3 §7.1):不管停在哪个页签都看得到,不藏在「输入数据」里
      return 失.length ? `<div class="ferr" role="alert">有 ${失.length} 处数据来源的原来源已删除:${失.map((x) =>
        `「${esc(x.原名)} · ${esc(x.字段)}」`).join("、")} —— 在下面「用到的数据」里选新来源,或撤销那次删除</div>` : ""; })()}
    ${问.map((q) => `<div class="err" style="padding:6px;margin:6px 0">${md(q["消息"])}<br>
        <span class="k">怎么改:${md(q["建议"])}</span></div>`).join("")}
    <div id="pp">
      ${段("基本", "设置", 表_设置(n))}
      ${段("用到的数据", "输入数据", 表_输入(n))}
      ${段("结果", "结果字段", 表_结果(n))}
      <details class="psec" data-sec="高级"${高开 ? " open" : ""}><summary class="psh">高级</summary>${表_高级(n)}</details>
      ${n.type === "start" ? "" : 段("上次运行", "上次运行", `<div id="lastrun" data-nid="${esc(n.id)}"><div class="k">读取中…</div></div>`)}
      ${(() => { const 测 = 单测表(n); return 测 ? 段("试这一步", "试这一步", 测) : ""; })()}
    </div>`;
  挂单测(n);
  填上次运行(n);
  挂变量唤出(n);
  const 高 = $("#pn").querySelector('[data-sec="高级"]');
  if (高) 高.ontoggle = () => { 图态.高级开 = 高.open; };
  if ($("#adv-cancel")) $("#adv-cancel").onclick = () => { $("#adv-json").value = JSON.stringify(n.config, null, 1); $("#adv-err").textContent = ""; };
  $("#pn").querySelectorAll("[data-clr]").forEach((b) => {
    b.onclick = () => { const i = $("#pn").querySelector(`[data-k="${b.dataset.clr}"]`); if (!i) return; i.value = ""; i.dispatchEvent(new Event("change")); i.focus(); };
  });
  $("#pn").querySelectorAll("[data-k]").forEach((el) => {
    const fn = 控件表[+el.dataset.k];
    if (!能改图()) { el.disabled = true; return; }
    // 每个控件的改动都走命令层(撤销 / 未保存 / 检查过期)。fn 返回 false = 输入不合法,**不写进定义、留在框里**
    const 触 = () => 改图(`改「${业务名(n)}」的${el.dataset.lb || "配置"}`, () => fn(el),
      { 合并键: el.tagName === "BUTTON" ? null : `${n.id}:${el.dataset.k}`, 重绘: false });
    if (el.tagName === "BUTTON") el.onclick = 触; else el.onchange = 触;
  });
}
// 改完要重画的控件(比如加了一行字段):先改数据,再重画面板和步骤
const 重画 = () => 重画全部();

/* 键 → 值 的小表(HTTP 请求的查询串 / 请求头,11-16):改名字 = 删旧键放新键(顺序可能变,不影响语义);
 * 名字清空就是删这一项;值原样存文字 —— 查询串和请求头本来就是文字,不猜数字 */
function 键值表(n, 键名, 标题, 键提示, 值提示) {
  const o = n.config[键名] = (n.config[键名] && typeof n.config[键名] === "object") ? n.config[键名] : {};
  const 行 = Object.keys(o).map((k) => `<div class="fieldrow">
      ${输入框(k, (el) => { const 新 = el.value.trim(); const v = o[k]; delete o[k]; if (新) o[新] = v; 重画(); }, 键提示)}
      ${输入框(o[k] ?? "", (el) => { o[k] = el.value; }, 值提示)}
      <button data-k="${挂控件(() => { delete o[k]; 重画(); })}" aria-label="删掉 ${esc(k)}">删</button></div>`).join("");
  return `<label class="f">${esc(标题)}</label>${行 || `<div class="k">还没有。</div>`}
    <button data-k="${挂控件(() => { let i = 1, k = "名字"; while (Object.prototype.hasOwnProperty.call(o, k)) k = `名字${++i}`; o[k] = ""; 重画(); })}">加一项</button>`;
}
function 下拉(值, 选项, fn, 空 = "请选择") {
  const k = 挂控件(fn);
  return `<select data-k="${k}"><option value="">${esc(空)}</option>${选项.map(([v, t]) =>
    `<option value="${esc(v)}" ${v === 值 ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
}
function 输入框(值, fn, 提示 = "", { 可清空 = false } = {}) {
  const k = 挂控件(fn);
  // 「清空」只清文字,不删字段、不重置配置 —— 三个动作三种文案(§7.3)
  return `<span class="inwrap"><input data-k="${k}" value="${esc(值 ?? "")}" placeholder="${esc(提示)}">${可清空
    ? `<button type="button" class="clr" data-clr="${k}" aria-label="清空" title="清空这一格">×</button>` : ""}</span>`;
}
/* 整数 / 小数:**非法值不写进定义**,原样留在框里并说明(§8.3:不把 1.8 静默截成 1) */
function 数字框(值, fn, { 整数 = false, 最小 = null, 提示 = "" } = {}) {
  return 输入框(值, (el) => {
    const t = String(el.value).trim(), 错 = el.parentNode && el.parentNode.nextElementSibling;
    const 说 = (m) => { if (错 && 错.classList && 错.classList.contains("ferr")) 错.textContent = m; };
    if (t === "") { 说(""); return fn(undefined); }
    const v = Number(t);
    if (!Number.isFinite(v) || (整数 && !Number.isInteger(v)) || (最小 != null && v < 最小)) {
      说(`没改:要填${整数 ? "整数" : "数字"}${最小 != null ? `,不小于 ${最小}` : ""} —— 「${t}」不行`);
      return false;
    }
    说(""); return fn(v);
  }, 提示) + `<div class="ferr" role="alert"></div>`;
}

/* 资源选择器(W22 · §8.1):搜索、版本、用途、状态;**选的是明确版本**,不要用户手填版本 id。
 * · 当前选的不在列表里(历史版本 / 已停用 / 没权限)→ 保留原值并说明,不当成「没选」
 * · 列表拉取失败 → 保留当前选择 + 重试,**不当成「原资源不存在」**
 * 列表很长时先搜:输入框只筛选项,不改配置。 */
function 资源选择器(种类, 当前, 项们, 选了, 空话) {
  const g = 图态;
  if (g.资源.拉取失败) {
    return `<div class="note">暂时读取不到${esc(种类)}列表,<b>已保留当前选择</b>${当前 ? `(<code>${esc(当前)}</code>)` : ""} —— 不是「原来那个不存在了」。
      <button data-k="${挂控件(async () => { await 重取资源(); 重画(); return false; })}">重试</button></div>`;
  }
  // 空话可以给 {html}(11-18:HTTP 请求节点那句要带一个到「工具连接」页的链接);纯字串照旧转义
  if (!项们.length) return `<div class="note">${空话 && 空话.html ? 空话.html : esc(空话)}</div>`;
  const 词 = (g.资源搜 || {})[种类] || "";
  const 中 = 项们.filter((x) => !词 || `${x.名}${x.说}${x.版 || ""}${x.标}`.includes(词));
  const 现 = 项们.find((x) => x.id === 当前);
  const k搜 = 挂控件((el) => { (g.资源搜 = g.资源搜 || {})[种类] = el.value.trim(); 画_面板(); return false; });
  return `<div class="ressel">
    ${项们.length > 6 ? `<input data-k="${k搜}" value="${esc(词)}" placeholder="搜${esc(种类)}:名称、用途、版本" aria-label="搜索${esc(种类)}">` : ""}
    ${下拉(现 ? 当前 : "", 中.map((x) => [x.id, `${x.名}${x.版 ? " · " + x.版 : ""} · ${x.标}`]), (el) => 选了(el.value), 当前 && !现 ? "(当前的不在列表里)" : `请选择${种类}`)}
    ${词 && !中.length ? `<div class="k">没有包含「${esc(词)}」的${esc(种类)}。</div>` : ""}
    ${现 ? `<div class="k">${esc(现.说 || "")}${现.版 ? ` · 版本 ${esc(现.版)}` : ""} · ${esc(现.标)}</div>` : ""}
    ${当前 && !现 ? `<div class="ferr">当前选的${esc(种类)}(<code>${esc(当前)}</code>)不在可选列表里 —— 可能是历史版本、已停用,或你没有它的权限。
       <b>原值保留着</b>;要换就在上面选一个,运行前检查配置会报出来。</div>` : ""}
  </div>`;
}
async function 重取资源() {
  try { 图态.资源 = await 请求(`${P()}/workflow-resources`); 轻提示("资源列表已重新取到"); }
  catch (e) { 图态.资源 = { ...图态.资源, 拉取失败: true }; 轻提示("还是取不到:" + e.message + "(当前选择没动)"); }
}
/* 换业务动作:先摆出入参的**真实差异**(新增必填 / 移除 / 类型变化),确认后才换;
 * 同名且类型兼容的绑定保留,对不上的列出来待核对 —— **不把旧参数原样送进新工具,也不悄悄清空整份表单**(§8.1) */
function 入参差异(旧, 新) {
  const op = (旧 || {}).properties || {}, np = (新 || {}).properties || {}, nr = new Set((新 || {}).required || []);
  return { 新增必填: Object.keys(np).filter((k) => !op[k] && nr.has(k)), 新增选填: Object.keys(np).filter((k) => !op[k] && !nr.has(k)),
    移除: Object.keys(op).filter((k) => !np[k]), 类型变化: Object.keys(np).filter((k) => op[k] && (op[k].type || "") !== (np[k].type || "")) };
}
function 换业务动作(n, id) {
  const c = n.config, 旧t = 工具资源(c.tool_version_id), 新t = 工具资源(id);
  if (!id) { c.tool_version_id = undefined; 重画(); return; }
  if (!旧t || !新t || !Object.keys(c.bindings || {}).length) { c.tool_version_id = id; 重画(); return; }
  const 差 = 入参差异(旧t["入参"], 新t["入参"]);
  const 要删 = Object.keys(c.bindings || {}).filter((k) => 差.移除.includes(k));
  弹层(`把「${业务名(n)}」换成「${新t["名"]}」?`, `
    <p>参数的真实差异:新增必填 <b>${差.新增必填.length}</b> 项、移除 <b>${差.移除.length}</b> 项、类型变化 <b>${差.类型变化.length}</b> 项。</p>
    ${差.新增必填.length ? `<p class="k">新增必填:${差.新增必填.map(esc).join("、")} —— 换完要给它们选来源</p>` : ""}
    ${要删.length ? `<p class="k">新的不再要:${要删.map(esc).join("、")} —— 这几行绑定会去掉(可撤销)</p>` : ""}
    ${差.类型变化.length ? `<p class="k">类型变了:${差.类型变化.map(esc).join("、")} —— 绑定保留但要核对,不会悄悄转成字符串</p>` : ""}
    <p>同名、类型没变的绑定原样保留。</p>
    <div class="acts"><button class="pri" id="tw-ok">换</button> <button id="tw-no">取消</button></div>`);
  $("#tw-no").onclick = () => { 关弹层(); 画_面板(); };
  $("#tw-ok").onclick = () => {
    关弹层();
    改图(`换业务动作为「${新t["名"]}」`, () => { c.tool_version_id = id; 要删.forEach((k) => { delete c.bindings[k]; }); });
    if (差.类型变化.length) (图态.待核对 = 图态.待核对 || {})[n.id] = 差.类型变化;
    轻提示(`已换成「${新t["名"]}」` + (差.类型变化.length ? `;${差.类型变化.join("、")} 类型变了,请核对` : ""), { 撤销: true });
  };
  return false;     // 真改在确认之后;这一次控件变更本身不改定义
}

/* 条件分支一路的条件:新写法 conditions(+ logic),老写法只有一条 when —— 和后端 dsl.分支条件 同一个认法 */
function 分支条件们(b) { return Array.isArray(b.conditions) ? b.conditions : (b.when ? [b.when] : []); }
function 转新写法(b) {
  if (Array.isArray(b.conditions)) return;
  b.conditions = b.when ? [b.when] : []; b.logic = "and"; delete b.when;
  if (b.on_missing) { b.conditions.forEach((w) => { if (!w.on_missing) w.on_missing = b.on_missing; }); delete b.on_missing; }
}
/* 列表操作的过滤比较方式(11-12):和后端 dsl.操作符表 同名;一元的不填比较值 */
const 列表比法 = [["equals", "等于"], ["not_equals", "不等于"], ["gt", "大于"], ["gte", "大于等于"], ["lt", "小于"], ["lte", "小于等于"],
  ["contains", "包含"], ["exists", "有这一项"], ["not_exists", "没有这一项"], ["is_null", "是空(null)"], ["is_not_null", "不是空"],
  ["date_before", "早于(日期)"], ["date_after", "晚于(日期)"]];
const 列表一元比法 = ["exists", "not_exists", "is_null", "is_not_null"];
/* 比较值:比大小的转成数字;等于 / 包含跟着当前类型走(现在是数字就仍按数字)。转不成数字的原样留着 —— 检查配置会说「要填数字」,不悄悄当 0 */
function 列表比较值(op, 原, 旧) {
  const t = String(原).trim(), 数 = t !== "" && Number.isFinite(Number(t));
  if (["gt", "gte", "lt", "lte"].includes(op)) return 数 ? Number(t) : 原;
  if (["equals", "not_equals", "contains"].includes(op) && typeof 旧 === "number") return 数 ? Number(t) : 原;
  return 原;
}
function 表_设置(n) {
  const g = 图态, c = n.config;
  let 体 = `<div class="two"><div><label class="f">这一步叫什么</label>${输入框(n.name || "", (el) => { n.name = el.value.trim() || undefined; 重画(); })}</div>
    <div><label class="f">类型</label><div class="ro">${esc(次级标签(n))}</div></div></div>`;
  if (n.type === "llm") {
    const 模 = g.资源.模型 || [], 处 = g.资源.处理要求 || [];
    体 += `<label class="f">用哪个模型</label>`
      + 资源选择器("模型", c.connection_version_id, 模.map((m) => ({ id: m["版本id"], 名: m["名"],
          说: (m["支持的参数"] || []).length ? `支持:${m["支持的参数"].join("、")}` : "", 标: m["是假的"] ? "演示用,不真调" : "可用" })),
          (id) => { c.connection_version_id = id || undefined; 重画(); },
          "这个项目还没有可用的模型 —— 请平台管理员在「模型与连接」里接一个。")
      + `<label class="f">这一步要完成什么(处理要求)</label>`
      + 资源选择器("处理要求", c.prompt_version_id, 处.map((p) => ({ id: p["版本id"], 名: p["名"], 版: `v${p["版本"]}`, 说: p["用途"] || "", 标: "已存版本" })),
          (id) => { c.prompt_version_id = id || undefined; 重画(); },
          "还没有处理要求 —— 去「Prompt 管理」写一份并存版本。")
      + `<div class="k">要改处理要求本身,去「Prompt 管理」—— 这里只选用哪一版,不改所有流程共用的正式版本。</div>`;
  } else if (n.type === "classifier") {
    // 问题分类器(10-27,照 Dify):类别名同时是交给模型的选项和出口名 —— 改名走 分支改名,线跟着改
    const 模 = g.资源.模型 || [];
    c.classes = c.classes || [];
    体 += `<label class="f">用哪个模型</label>`
      + 资源选择器("模型", c.connection_version_id, 模.map((m) => ({ id: m["版本id"], 名: m["名"], 说: "", 标: m["是假的"] ? "演示用,不真调" : "可用" })),
          (id) => { c.connection_version_id = id || undefined; 重画(); },
          "这个项目还没有可用的模型 —— 请平台管理员在「模型与连接」里接一个。")
      + `<label class="f">分成哪几类</label>
        <div class="note">模型只能从这几个名字里挑一个,挑哪个就走哪个出口。答了不在里面的 → 这一步失败(可在「高级」里设成走「失败时」那条线,接人工)。</div>`
      + c.classes.map((x, i) => `<div class="card">
          <div class="k">第 ${i + 1} 类 · 叫</div>${输入框(x.key || "", (el) => {
            const r = 图逻辑.分支改名(图态.定义, n.id, x.key, el.value);
            if (!r.可以) { if (!r.没变) 轻提示(`没改名:${r.为什么}`); el.value = x.key || ""; return false; }
            重画(); })}
          <div class="k">什么样的算这一类(写给模型看)</div>${输入框(x.说明 || "", (el) => { x.说明 = el.value.trim() || undefined; }, "例如:客户问了价格、档期或约了到店", { 可清空: true })}
          <div class="acts"><button class="danger" data-k="${挂控件(() => {
              const r = 图逻辑.删分支(图态.定义, n.id, i);
              轻提示(`已删除「${r.键}」这一类` + (r.删边.length ? `和它的 ${r.删边.length} 条连线(目标步骤保留)` : ""), { 撤销: true }); 重画(); })}"
              aria-label="删掉第 ${i + 1} 类">删掉这一类</button></div></div>`).join("")
      + `<button data-k="${挂控件(() => { let j = c.classes.length + 1; while (c.classes.some((x) => x.key === `类别${j}`)) j++;
            c.classes.push({ key: `类别${j}` }); 重画(); })}">加一类</button>`
      + `<label class="f">分类时还要注意(选填)</label>`
      + 输入框(c.instruction || "", (el) => { c.instruction = el.value.trim() || undefined; }, "例如:只看客户说的话,别看顾问说的", { 可清空: true })
      + `<div class="k">要分类的内容在下面「用到的数据」里选,比如录音转写。</div>`;
  } else if (n.type === "assigner") {
    // 变量赋值(10-27,用户拍要做):改所在循环的循环状态,改完马上生效
    const 环 = n.container && 节点(n.container), 状 = (环 && (环.config || {}).loop_state) || {};
    c.assignments = c.assignments || [];
    if (!环) {
      体 += `<div class="ferr">变量赋值改的是循环状态 —— 先在下面「高级」的「放在哪个循环里」选一个循环。</div>`;
    } else {
      const 源们 = 上游字段(n.id);
      体 += `<label class="f">改「${esc(业务名(环))}」的哪几项</label>
        <div class="note">改完<b>马上生效</b>:这一轮后面的步骤取「循环状态 · 名字」就是新值。循环设置里已经写了「每一轮结束取自」的那一项不能在这里再改(两个写的人会打架)。</div>`
        + c.assignments.map((a, i) => `<div class="card">
          <div class="two"><div><div class="k">第 ${i + 1} 条 · 改哪一项</div>${下拉(a.variable || "", Object.keys(状).map((k) => [k, k]), (el) => { a.variable = el.value || undefined; 重画(); }, "选一项循环状态")}</div>
            <div><div class="k">怎么改</div>${下拉(a.op || "", [["set", "覆盖成"], ["add", "加上(数字)"], ["append", "追加到列表后面"], ["clear", "清空"]],
              (el) => { a.op = el.value || undefined; if (a.op === "clear") delete a.value; if (a.op === "add") a.value = { source: "constant", value: 1 }; 重画(); }, "选改法")}</div></div>
          ${a.op === "set" || a.op === "append" ? `<div class="k">${a.op === "set" ? "改成" : "追加"}什么</div>${下拉(引用值(a.value), 源们, (el) => { a.value = 解引用(el.value) || undefined; }, "选来源")}` : ""}
          ${a.op === "add" ? `<div class="k">加多少</div>${数字框(a.value?.value ?? 1, (v) => { a.value = v === undefined ? undefined : { source: "constant", value: v }; }, { 提示: "比如 1" })}` : ""}
          ${a.variable && 状[a.variable] && 状[a.variable].update ? `<div class="ferr">「${esc(a.variable)}」在循环设置里已经是「每一轮结束取自某一步」,检查配置会拦</div>` : ""}
          <div class="acts"><button class="danger" data-k="${挂控件(() => { c.assignments.splice(i, 1); 重画(); })}" aria-label="删掉第 ${i + 1} 条赋值">删掉这一条</button></div></div>`).join("")
        + `<button data-k="${挂控件(() => { c.assignments.push({ variable: Object.keys(状)[0], op: "set" }); 重画(); })}">加一条</button>`
        + (Object.keys(状).length ? "" : `<div class="k">这个循环还没有循环状态 —— 先去循环的设置里加一项。</div>`);
    }
  } else if (n.type === "extractor") {
    // 参数提取器(10-27,照 Dify):每项一行 —— 名字 / 类型 / 说明 / 必填;名字就是后面步骤取它用的名字
    const 模 = g.资源.模型 || [];
    c.parameters = c.parameters || [];
    体 += `<label class="f">用哪个模型</label>`
      + 资源选择器("模型", c.connection_version_id, 模.map((m) => ({ id: m["版本id"], 名: m["名"], 说: "", 标: m["是假的"] ? "演示用,不真调" : "可用" })),
          (id) => { c.connection_version_id = id || undefined; 重画(); },
          "这个项目还没有可用的模型 —— 请平台管理员在「模型与连接」里接一个。")
      + `<label class="f">要提取哪几项</label>
        <div class="note">原文没提到的那一项是<b>空</b>,不让模型编;<b>必填</b>的没抽到这一步就失败(可在「高级」里设成走「失败时」接人工)。</div>`
      + c.parameters.map((p, i) => `<div class="card">
          <div class="two"><div><div class="k">第 ${i + 1} 项 · 叫</div>${输入框(p.name || "", (el) => { p.name = el.value.trim(); 重画(); }, "例如:预算")}</div>
            <div><div class="k">类型</div>${下拉(p.type || "string", [["string", "文字"], ["number", "数字"], ["integer", "整数"], ["boolean", "是 / 否"], ["array", "列表"]],
              (el) => { p.type = el.value; })}</div></div>
          <div class="k">说明(写给模型看)</div>${输入框(p.description || "", (el) => { p.description = el.value.trim() || undefined; }, "例如:单位元,只写数字", { 可清空: true })}
          <label class="k"><input type="checkbox" data-k="${挂控件((el) => { p.required = el.checked; })}" ${p.required ? "checked" : ""}> 必填(没抽到就失败)</label>
          <div class="acts"><button class="danger" data-k="${挂控件(() => { c.parameters.splice(i, 1); 重画(); })}" aria-label="删掉第 ${i + 1} 项参数">删掉这一项</button></div></div>`).join("")
      + `<button data-k="${挂控件(() => { c.parameters.push({ name: "", type: "string" }); 重画(); })}">加一项</button>`
      + `<label class="f">提取时还要注意(选填)</label>`
      + 输入框(c.instruction || "", (el) => { c.instruction = el.value.trim() || undefined; }, "例如:金额按客户最后说的那个", { 可清空: true })
      + `<div class="k">从哪段内容里提取,在下面「用到的数据」里选,比如录音转写。</div>`;
  } else if (n.type === "tool") {
    const 工 = g.资源.工具 || [];
    体 += `<label class="f">执行哪个业务动作</label>`
      + 资源选择器("业务动作", c.tool_version_id, 工.map((t) => ({ id: t["版本id"], 名: t["名"], 版: t["版本"] != null ? `v${t["版本"]}` : "",
          说: t["说明"] || "", 标: t["读写"] + (t["接入方式"] === "lanxiu_bridge" ? " · 由澜绣执行" : "") })),
          (id) => 换业务动作(n, id),
          "这个项目还没有登记业务动作。");
    const t = 工具资源(c.tool_version_id);
    if (t && t["接入方式"] === "lanxiu_bridge") 体 += `<div class="note">这一步<b>由澜绣执行</b>:管理后台只记一张单、流程停下等;澜绣的同步程序拉回去用它自己的函数做完、回执,流程再接着走。
            ${t["读写"] !== "只读" ? "<b>写入类的动作之前必须有人工核对通过</b>,否则这次运行会直接失败。" : ""}</div>`;
  } else if (n.type === "http_request") {
    // HTTP 请求(11-16 三期 3-1):只能选已登记的工具连接,地址 = 连接白名单里的一条 + 这里的路径;一期只开 GET/HEAD(拍板 H6);
    // 凭据只从连接来 —— 这里填的鉴权头在发送前会被丢掉(拍板 H3)。查询串 / 请求头是「底」,「用到的数据」里绑定的同名值盖上去
    const 连 = g.资源.工具连接 || [], k = 工具连接(c.connection_id);
    体 += `<label class="f">用哪条工具连接</label>`
      + 资源选择器("工具连接", c.connection_id, 连.map((x) => ({ id: x.id, 名: x["名"], 说: (x["允许的端点"] || []).join("、"),
          // 鉴权方式(11-16,workflow-resources 带回;老连接 / 老接口没有就不显示):选的时候就知道这条连接带不带凭据
          标: (x["状态"] === "active" ? "可用" : `状态:${x["状态"] || "未知"}`) + ` · ${x["适配器"] || ""}` + (x["鉴权方式"] ? ` · 鉴权:${x["鉴权方式"]}` : "") })),
          (id) => { c.connection_id = id || undefined; delete c.endpoint_index; 重画(); },
          { html: `这个项目还没有登记工具连接 —— 请平台管理员在<a href="#/integrations/conns" target="_blank">集成 / 工具连接</a>里登记一条(填允许访问的地址和凭据引用),登记完回来重新打开这个节点。` })
      + `<div class="note">只许访问这条连接<b>登记过的地址</b>;解析到内网、跟着跳转去别处、超过 15 秒或 1 MB 都会被拦下 —— 一个字节都不会发到白名单外。</div>`;
    if (k && (k["允许的端点"] || []).length > 1) {
      体 += `<label class="f">用白名单里的哪一条地址</label>`
        + 下拉(String(c.endpoint_index || 0), (k["允许的端点"] || []).map((u, i) => [String(i), u]),
            (el) => { c.endpoint_index = +el.value || 0; 重画(); }, "第一条");
    }
    体 += `<div class="two"><div><label class="f">方法</label>${下拉(c.method || "GET", [["GET", "GET(读)"], ["HEAD", "HEAD(只看头)"]],
          (el) => { c.method = el.value || "GET"; 重画(); }, "GET")}
        <div class="k">一期只开读;POST / PUT / DELETE 这类会改对方数据的,检查配置会拦下。</div></div>
      <div><label class="f">路径</label>${输入框(c.path || "", (el) => { const v = el.value.trim(); if (v) c.path = v; else delete c.path; }, "例如 /stock 或 /orders/123", { 可清空: true })}
        <div class="k">接在上面地址后面;要按上游的值拼路径,在「用到的数据」里绑 path。</div></div></div>`
      + 键值表(n, "query", "查询串(?后面那部分)", "例如 sku", "例如 A1")
      + 键值表(n, "headers", "请求头", "例如 Accept", "例如 application/json")
      + `<div class="k">鉴权头(Authorization 这类)不用填 —— 凭据只从连接来,这里写的会在发送前被丢掉。</div>`
      + `<label class="f">最多读多少字节(选填)</label>` + 数字框(c.max_bytes, (v) => { if (v === undefined) delete c.max_bytes; else c.max_bytes = v; }, { 整数: true, 最小: 1, 提示: "留空 = 1 MB" })
      + `<div class="ferr"></div>`;
  } else if (n.type === "human") {
    const 角 = g.资源.角色 || [];
    体 += `<label class="f">谁来处理</label>` + 角.map((r) => {
      const 有 = (c.candidate_roles || []).includes(r["码"]);
      const k = 挂控件((el) => {
        const s = new Set(c.candidate_roles || []); el.checked ? s.add(r["码"]) : s.delete(r["码"]);
        c.candidate_roles = [...s];
      });
      return `<label class="k"><input type="checkbox" data-k="${k}" ${有 ? "checked" : ""}> ${esc(r["中文"])}
        ${r["能审批"] ? "" : "<span class='k'>(默认不能审批,要专项授权)</span>"}</label>`;
    }).join(" ")
      + `<label class="f">审核人能改哪些内容</label>`
      + ["定稿"].map((f) => {
        const k = 挂控件((el) => { c.allowed_fields = el.checked ? [f] : []; });
        return `<label class="k"><input type="checkbox" data-k="${k}" ${(c.allowed_fields || []).includes(f) ? "checked" : ""}>
          定稿(通过时写进去的那一版)</label>`;
      }).join("")
      + `<label class="f">多久没处理就结束(小时)</label>`
      + 输入框((c.expires_at_policy || {}).小时 ?? "", (el) => {
        const h = Number(el.value);
        c.expires_at_policy = h > 0 ? { 小时: h, 到期: "fail" } : undefined;
      }, "例如 48")
      + `<div class="k">到点没人处理:待办记「已过期」,不写任何东西。<b>接了下面「下一步」里的「超时」出口</b>(照 Dify),就从那条线接着走(比如通知总部、改派);没接,这次运行结束,想补就重新发起一次。</div>`;
    // 表单化(四期 4-1,11-20 照 Dify):说明(Markdown,可 {{材料键}})/ 要人填的字段 / 按钮(每个一个出口)/ 到这一步推飞书
    体 += `<label class="f">给核对人看的说明(照 Dify 的表单内容;可以写 {{材料键}} 带进「用到的数据」里的值)</label>
      <textarea data-k="${挂控件((el) => { c.form_markdown = el.value; })}" data-lb="说明" rows="3" placeholder="例如:客户 {{客户}} 的差评:{{摘要}}。请判断责任方。">${esc(c.form_markdown || "")}</textarea>`;
    const 字段们 = c.form_fields = Array.isArray(c.form_fields) ? c.form_fields : [];
    体 += `<label class="f">要核对人填的字段(照 Dify 的输入字段;填的值交给下一步)</label>`
      + (字段们.length ? `<table><thead><tr><th>名字</th><th>显示名</th><th>类型</th><th>选项(下拉用,逗号分开)</th><th>必填</th><th></th></tr></thead><tbody>`
        + 字段们.map((f, i) => `<tr>
          <td>${输入框(f.name || "", (el) => { f.name = el.value.trim(); 重画(); }, "如 备注")}</td>
          <td>${输入框(f.title || "", (el) => { f.title = el.value.trim() || undefined; }, "页面上显示的名字")}</td>
          <td>${下拉(f.type || "段落", [["段落", "段落(多行文字)"], ["下拉", "下拉(从选项里选)"], ["是否", "是 / 否"]], (el) => { f.type = el.value; 重画(); })}</td>
          <td>${f.type === "下拉" ? 输入框((f.options || []).join(","), (el) => { f.options = el.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean); }, "顾客责任,门店责任") : `<span class="k">—</span>`}</td>
          <td><input type="checkbox" data-k="${挂控件((el) => { f.required = !!el.checked; })}" ${f.required ? "checked" : ""}></td>
          <td><button class="danger" data-k="${挂控件(() => { 字段们.splice(i, 1); 重画(); })}">删除</button></td></tr>`).join("") + `</tbody></table>` : `<div class="k">还没有要填的字段。不加也行:核对人只看说明、点按钮。</div>`)
      + `<button data-k="${挂控件(() => { let j = 字段们.length + 1; while (字段们.some((x) => x.name === `字段${j}`)) j++; 字段们.push({ name: `字段${j}`, type: "段落", required: false }); 重画(); })}">加一个字段</button>`;
    const 按钮们 = c.actions = Array.isArray(c.actions) ? c.actions : [];
    体 += `<label class="f">按钮(照 Dify 的用户操作:每个按钮一个出口;不配就是原来的「通过 / 退回」)</label>`
      + (按钮们.length ? `<table><thead><tr><th>标识(= 出口名)</th><th>按钮文字</th><th>样式</th><th></th></tr></thead><tbody>`
        + 按钮们.map((a, i) => `<tr>
          <td>${输入框(a.id || "", (el) => { const r = 图逻辑.人工按钮改名(图态.定义, n.id, a.id, el.value); if (!r.可以) { if (!r.没变) 轻提示(`没改:${r.为什么}`); el.value = a.id; return false; } 重画(); }, "如 顾客责任")}</td>
          <td>${输入框(a.文字 || "", (el) => { a.文字 = el.value.trim() || undefined; }, "按钮上显示的字,不填用标识")}</td>
          <td>${下拉(a.样式 || "默认", [["主要", "主要(蓝)"], ["默认", "默认"], ["强调", "强调(红,删除 / 驳回这类)"], ["幽灵", "幽灵(淡)"]], (el) => { a.样式 = el.value; })}</td>
          <td><button class="danger" data-k="${挂控件(() => { const r = 图逻辑.删人工按钮(图态.定义, n.id, i); 轻提示(`已删除按钮「${r.键}」` + (r.删边.length ? `和它的 ${r.删边.length} 条连线` : ""), { 撤销: true }); 重画(); })}">删除</button></td></tr>`).join("") + `</tbody></table>`
        : `<div class="k">没配按钮:核对人看到「通过 / 退回」,通过走「完成后」那条线。</div>`)
      + `<button data-k="${挂控件(() => { let j = 按钮们.length + 1; while (按钮们.some((x) => x.id === `按钮${j}`)) j++; 按钮们.push({ id: `按钮${j}`, 样式: "默认" }); 重画(); })}">加一个按钮</button>
      <div class="k">配了按钮,画布上这一步每个按钮一个出口,人点哪个走哪条线;下游「用到的数据」里能取到 <b>__action_id</b>(点的哪个)和每个字段的值。到点没人处理照旧:运行结束、不写任何东西(超时出口没做)。</div>`;
    体 += `<label class="f">到这一步推一条飞书通知(可选)</label>`
      + 资源选择器("通知连接", c.notify_connection_id, (g.资源.工具连接 || []).map((x) => ({ id: x.id, 名: x["名"], 说: (x["允许的端点"] || []).join("、"), 标: x["状态"] || "" })),
          (id) => { c.notify_connection_id = id || undefined; 重画(); }, { html: `还没有工具连接 —— 到「集成 → 工具连接」登记一条飞书群机器人:允许的端点填 https://open.feishu.cn/open-apis/bot/v2/hook,密钥引用填 hook id。` })
      + `<div class="k">通知里只写哪条流程、哪一步、谁该处理、截止和链接,<b>不带客户数据</b>;推不出去只记事件,不影响运行。</div>`;
  } else if (n.type === "condition") {
    const 源们 = 上游字段(n.id);
    体 += `<label class="f">满足什么条件</label>
      <div class="note">从上往下,<b>第一个满足的分支生效</b> —— 调顺序就是改执行逻辑,改完要重新检查。</div>`
      + (c.branches || []).map((b, i) => `<div class="card">
          <div class="k">第 ${i + 1} 路 · 叫</div>${输入框(b.key, (el) => {
            const r = 图逻辑.分支改名(图态.定义, n.id, b.key, el.value);
            if (!r.可以) { if (!r.没变) 轻提示(`没改名:${r.为什么}`); el.value = b.key; return false; }
            重画(); })}
          ${(() => {
            // 一路几条条件,「且 / 或」连(10-27 照 Dify)。老写法只有一条 when:显示成一条;一动就转成新写法
            const 条们 = 分支条件们(b), 多 = 条们.length > 1;
            return (多 ? `<div class="k">这几条之间</div>` + 下拉(b.logic === "or" ? "or" : "and",
                  [["and", "且:都满足才走这一路"], ["or", "或:有一条满足就走"]], (el) => { 转新写法(b); b.logic = el.value; 重画(); }) : "")
              + 条们.map((w, j) => `<div class="condrow">
                ${多 ? `<div class="k">第 ${j + 1} 条${j ? (b.logic === "or" ? " · 或" : " · 且") : ""}</div>` : ""}
                <div class="k">取哪个值</div>${下拉(引用值(w.left), 源们, (el) => { 转新写法(b); b.conditions[j].left = 解引用(el.value); })}
                <div class="k">怎么比</div>${下拉(w.op || "equals", [["equals", "等于"], ["not_equals", "不等于"],
                    ["gt", "大于"], ["lt", "小于"], ["exists", "有值"], ["contains", "包含"]], (el) => {
                    转新写法(b); b.conditions[j].op = el.value; if (el.value === "exists") delete b.conditions[j].right; 重画(); })}
                ${w.op === "exists" ? "" : `<div class="k">和什么比(固定值)</div>${输入框(w.right?.value ?? "", (el) => {
                    转新写法(b); b.conditions[j].right = { source: "constant", value: el.value }; }, "", { 可清空: true })}`}
                ${!w.left ? `<div class="ferr">这条还没选「取哪个值」—— 条件为空不会当成始终满足,检查配置会拦</div>` : ""}
                ${多 ? `<button class="danger" data-k="${挂控件(() => { 转新写法(b); b.conditions.splice(j, 1); 重画(); })}" aria-label="删掉第 ${i + 1} 路第 ${j + 1} 条条件">删掉这条</button>` : ""}
              </div>`).join("")
              + `<button data-k="${挂控件(() => { 转新写法(b); b.conditions.push({ op: "exists", left: null }); 重画(); })}">加一条条件</button>`;
          })()}
          <div class="acts">
            <button data-k="${挂控件(() => { 图逻辑.分支移动(图态.定义, n.id, i, -1); 重画(); })}" ${i === 0 ? "disabled" : ""} aria-label="第 ${i + 1} 路上移">上移</button>
            <button data-k="${挂控件(() => { 图逻辑.分支移动(图态.定义, n.id, i, 1); 重画(); })}" ${i === c.branches.length - 1 ? "disabled" : ""} aria-label="第 ${i + 1} 路下移">下移</button>
            <button class="danger" data-k="${挂控件(() => {
              const r = 图逻辑.删分支(图态.定义, n.id, i);
              轻提示(`已删除「${r.键}」这一路` + (r.删边.length ? `和它的 ${r.删边.length} 条连线(目标步骤保留)` : ""), { 撤销: true }); 重画(); })}">删除分支</button></div></div>`).join("")
      + `<button data-k="${挂控件(() => { let j = (c.branches || []).length + 1; while ((c.branches || []).some((x) => x.key === `第${j}路`)) j++;
            (c.branches = c.branches || []).push({ key: `第${j}路`, logic: "and",
            conditions: [{ op: "equals", left: null, right: { source: "constant", value: "" } }] }); 重画(); })}">加一路</button>`
      + `<label class="f">都不满足时</label>`
      + 下拉(c.else_policy, [["fail", "记成没完成(incomplete)"], ["end", "正常结束"]], (el) => { c.else_policy = el.value; })
      + `<div class="k">接了「都不满足」那条线时,走那条线;没接才按这里的办法结束。</div>`;
  } else if (n.type === "loop") {
    // 有界循环(10-27):先判断后执行 —— 每一轮开始前看「继续条件」,满足才再跑一轮;跑满上限还没停 = 没做完
    const 源们 = 上游字段(n.id), 状 = c.loop_state = c.loop_state || {};
    c.condition = c.condition || { op: "equals", left: null, right: { source: "constant", value: true } };
    const w = c.condition;
    体 += `<label class="f">最多跑几轮(1–10)</label>` + 数字框(c.max_iterations ?? "", (v) => { c.max_iterations = v; }, { 整数: true, 最小: 1, 提示: "经营报告是 4:第一稿 + 3 次重写" })
      + `<div class="k">跑满还没停下 → 这次运行记「没做完」,不当成功。</div>`
      + `<label class="f">满足什么条件就再跑一轮</label>
        <div class="condrow"><div class="k">取哪个值</div>${下拉(引用值(w.left), 源们, (el) => { w.left = 解引用(el.value); })}
        <div class="k">怎么比</div>${下拉(w.op || "equals", [["equals", "等于"], ["not_equals", "不等于"], ["exists", "有值"]], (el) => {
          w.op = el.value; if (el.value === "exists") delete w.right; else w.right = w.right || { source: "constant", value: true }; 重画(); })}
        ${w.op === "exists" ? "" : `<div class="k">和什么比</div>${下拉(String(w.right?.value), [["true", "是"], ["false", "否"]], (el) => {
          w.right = { source: "constant", value: el.value === "true" }; })}`}
        ${!w.left ? `<div class="ferr">还没选「取哪个值」—— 一般选一项循环状态,比如「还要写」</div>` : ""}</div>`
      + `<label class="f">循环状态(每一轮之间记着的值)</label>`
      + Object.entries(状).map(([k, v]) => `<div class="condrow"><div class="k">名字</div><b>${esc(k)}</b>
          <div class="k">一开始是</div>${v && v.initial && typeof v.initial === "object" && v.initial.source
            ? `<div class="ro">取自 ${esc(引用值(v.initial))}</div>`
            : 输入框(v && v.initial != null ? JSON.stringify(v.initial) : "", (el) => {
                try { 状[k].initial = el.value.trim() === "" ? null : JSON.parse(el.value); } catch (e) { 状[k].initial = el.value; } }, "比如 true、\"\"、0")}
          <div class="k">每一轮结束取自</div>${下拉(引用值(v && v.update), 源们.filter(([x]) => x.startsWith("n:")), (el) => { 状[k].update = 解引用(el.value) || undefined; },
            "不更新(保持一开始的值)")}
          <button class="danger" data-k="${挂控件(() => { delete 状[k]; 重画(); })}">删掉</button></div>`).join("")
      + `<div class="two"><div>${输入框("", (el) => { const k = el.value.trim(); if (!k || 状[k]) return false; 状[k] = { initial: null }; 重画(); }, "新的状态名,回车加上")}</div></div>`
      + `<div class="k">循环里的步骤在「用到的数据」里能选「循环状态 · 名字」。这一轮没走到「取自」的那一步 → 那一项保持不变。</div>`;
  } else if (n.type === "code") {
    // 代码执行最小版(三期 3-4,11-20;用户 11-15 拍「做一个最小版备着」):只有管理员能加 / 改(服务端存草稿时核);照 Dify:输入变量 / 代码 / 输出变量。
    // 「同步函数签名至代码」没做(写清);两个上限只许往下配
    const 上 = c.sub_limits = c.sub_limits || { timeout_seconds: 5, memory_mb: 64 };
    体 += (我的角色 === "admin" ? "" : `<div class="note warn">「代码执行」只有<b>管理员</b>能加或改代码 —— 你改了这一步存不了草稿(服务端会拒);别的步骤照常。</div>`)
      + `<label class="f">代码(Python;写一个 main 函数,参数名 = 下面「用到的数据」里的变量名,返回一个字典)</label>
      <textarea data-k="${挂控件((el) => { c.code = el.value; })}" data-lb="代码" rows="10" spellcheck="false" style="font-family:ui-monospace,Menlo,monospace;font-size:12px;white-space:pre">${esc(c.code || "")}</textarea>
      <div class="k">跑在沙箱里:<b>不联网、不读写文件、不起进程、没有环境变量</b>;只能算。要取数,用前面的步骤取好再交进来。</div>`
      + `<label class="f">返回什么(照 Dify 的输出变量:名字 + 类型;代码返回的字典按这里核,类型不对这一步失败)</label>` + 字段表编辑(c.output_schema = c.output_schema || { type: "object", properties: {}, required: [] }, false)
      + `<div class="two"><div><label class="f">限时(秒,最多 5)</label>${数字框(上.timeout_seconds ?? 5, (v) => { 上.timeout_seconds = v; }, { 整数: true, 最小: 1, 最大: 5 })}</div>
          <div><label class="f">内存(MB,最多 64)</label>${数字框(上.memory_mb ?? 64, (v) => { 上.memory_mb = v; }, { 整数: true, 最小: 1, 最大: 64 })}</div></div>
      <div class="k">两个上限是写死的天花板(拍脑袋的数),只能往下配。内存那条在 macOS 上不是硬限制:每 0.1 秒看一眼用量、超了就杀。</div>`;
  } else if (n.type === "markdown_export") {
    体 += `<div class="note">${md("把前面某一步产出的**正文**存成一份 .md 文件:文件名服务端生成(标题_门店_统计日期_运行短号.md),写完**回读核哈希**才算存成;下载按项目和门店范围授权、逐次记审计。它只存文件,**不发消息、不派单**。")}</div>`;
    体 += `<label class="f">标题(进文件名;不填用流程名)</label>` + 输入框(c.title || "", (el) => { c.title = el.value.trim() || undefined; }, "例如 经营日报")
      + `<label class="f">文件名前缀(不填用标题)</label>` + 输入框(c.file_prefix || "", (el) => { c.file_prefix = el.value.trim() || undefined; }, "例如 经营日报")
      + `<label class="f">模板版本(记在文档上,方便以后知道这份是按哪版模板写的)</label>` + 输入框(c.template_version || "", (el) => { c.template_version = el.value.trim() || undefined; }, "例如 v1")
      + `<div class="k">正文、标题、统计起止、门店从哪来 —— 在下面「用到的数据」里绑。</div>`;
  } else if (n.type === "retrieve") {
    // 知识检索(三期 3-5,11-20 做通 —— 此前这个节点能加进图、却没有面板,「查哪个资料库」「怎么查」没地方选):
    // 选资料库时顺手记下它最新「已就绪」的索引(检索只在就绪的索引上跑);「召回设置」照 Dify 摆在这儿但**只读** ——
    // 我们的口径在检索配置版本上(候选数 / 最终片段数 / 召回方式 / 上下文预算),改了要重建索引才可比,所以这里只选用哪一版,不改数
    const 库们 = g.资源.资料库 || [], 配们 = g.资源.检索配置 || [];
    const 库 = 库们.find((x) => x.id === c.knowledge_base_id) || null;
    体 += `<label class="f">查哪个资料库</label>`
      + 资源选择器("资料库", c.knowledge_base_id, 库们.map((x) => ({ id: x.id, 名: x["名"], 说: x["就绪索引"] ? "有已就绪的索引" : "还没有已就绪的索引(选了检查配置会拦)", 标: x["状态"] || "" })),
          (id) => { c.knowledge_base_id = id || undefined; const k = 库们.find((x) => x.id === id);
            c.index_build_id = (k && k["就绪索引"]) || undefined;
            if (k && k["索引用的配置"] && !c.retrieval_config_version_id) c.retrieval_config_version_id = k["索引用的配置"];
            重画(); }, "这个项目还没有资料库 —— 先去「知识库」建一个、传资料、建索引")
      + (库 && !库["就绪索引"] ? `<div class="ferr">这个资料库还没有「已就绪」的索引 —— 先去「知识库」页建一次索引。不在没建好的索引上检索:结果会不完整,而那和「库里就这么点」长得一样。</div>` : "")
      + (库 && 库["就绪索引"] ? `<div class="k">用的索引:${esc(库["就绪索引"])}(这个资料库最新就绪的那一个;重建索引后要重新选一次资料库才换过去)</div>` : "");
    体 += `<label class="f">怎么查(检索配置版本)</label>`
      + 资源选择器("检索配置", c.retrieval_config_version_id, 配们.map((x) => ({ id: x.id, 名: x["名"], 说: x["建于"] ? `建于 ${时间(x["建于"])}` : "", 标: "已冻结" })),
          (id) => { c.retrieval_config_version_id = id || undefined; 重画(); }, "这个项目还没有检索配置版本 —— 建索引时会一起建");
    const 配 = 配们.find((x) => x.id === c.retrieval_config_version_id) || null;
    if (配) {
      // 照 Dify 的「召回设置」弹窗列同样几项,但只读:数在版本上,这里不改
      体 += `<label class="f">召回设置(只读,来自上面选的那一版)</label><div class="card">
        <div class="two"><div><div class="k">候选数(先召回多少条)</div><b>${esc(String(配["候选数"] ?? "—"))}</b></div>
          <div><div class="k">最终片段数(交给下一步几片)</div><b>${esc(String(配["最终片段数"] ?? "—"))}</b></div></div>
        <div class="two"><div><div class="k">召回方式</div><b>${esc((配["召回方式"] || []).join(" + ") || "—")}</b></div>
          <div><div class="k">上下文预算(token)</div><b>${esc(String(配["上下文预算"] ?? "—"))}</b></div></div>
        <div class="k">精排:${配["精排"] ? "有配置(检索时多调一次模型重排)" : "没配(按向量相似度排)"} · 分数阈值:我们没有这一项,靠最终片段数和预算截断</div>
        <div class="k">要改这些数:到「知识库」里新建一版检索配置并重建索引,回来选新的那一版 —— 改了口径的检索结果和旧的不可比,所以不在这里改。</div></div>`;
    }
    体 += `<div class="k">要查的话在下面「用到的数据」里绑「问题」;结果给下一步:片段(每片带原文和证据)、拼好的证据、召回数、选了几片。权限按发起运行的人的角色过滤,服务端强制。</div>`;
  } else if (n.type === "start") {
    // 开始方式(11-16,台账第六十九条,照 Dify):用户输入 / 定时触发器 / Webhook,**三选一** —— 定时开头的流程没人在场填东西。
    // 换法只在 设开始方式 写一份:这里的下拉、「开始」页签、新建空白时的引导弹窗三处同一个
    const 待配 = 开始待配置(), 方式 = 待配 ? "" : (c.start_mode || "用户输入");
    if (待配) 体 += `<div class="note warn">这条流程<b>还没配置怎么开始</b> —— 在下面选一种(画布上虚线那张「点击配置开始节点」也能点)。</div>`;
    体 += `<label class="f">开始方式</label>` + 下拉(方式, 菜单开始项.map(([值, 名, , , 说, 标]) => [值, `${名}:${说}${标 ? `(${标})` : ""}`]), (el) => {
      if (!el.value) return false;
      设开始方式(c, el.value);
      重画();
    }, "请选择") + `<div class="k">一条流程只有一个「开始」、只选一种开始方式 —— 触发器和「用户输入」不能同时存在于同一条流程(照 Dify);几种都要就复制一条流程。</div>`;
    if (方式 === "Webhook") {
      体 += `<div class="note">${md("外部系统推过来的 JSON 就是下面「使用者要提供什么」那张表里的参数(`{参数名: 值}`),类型不对会被拒并点名是哪一项。"
        + "地址和密钥在「**访问 API**」页签:**调试地址只跑草稿**(边改边让对方推一条试),正式地址跑生产那一版。"
        + "以发密钥的那个人的身份跑;**写数据的业务动作前面必须有「人工介入」**,让人核对后再写(检查配置会拦)。")}</div>`;
      // 照 Dify 的 Query / Header 参数表和响应配置(11-20 二期 2-2 尾巴):三张表合成一张平的输入,参数名不能撞;请求头只能是文字
      体 += `<label class="f">网址参数(照 Dify 的 Query:地址后面 ?名=值)</label>`
        + 字段表编辑(c.webhook_query_schema = c.webhook_query_schema || { type: "object", properties: {}, required: [] }, true)
        + `<div class="k">网址上来的都是文字:登记成整数 / 数字 / 是否时按类型转,转不了拒并点名;列表 / 对象不能从网址来。</div>`;
      体 += `<label class="f">请求头参数(照 Dify 的 Header)</label>`
        + 字段表编辑(c.webhook_header_schema = c.webhook_header_schema || { type: "object", properties: {}, required: [] }, true)
        + `<div class="k">只能是文字;名字不分大小写。三张表(请求体 / 网址 / 请求头)里的参数名不能重复,检查配置会拦。</div>`;
      const 回 = c.webhook_response || {};
      const k体 = 挂控件((el) => { const v = el.value; (c.webhook_response = c.webhook_response || {}).body = v; if (!v.trim() && !(c.webhook_response.status_code && c.webhook_response.status_code !== 202)) delete c.webhook_response; });
      体 += `<label class="f">返回给对方什么(照 Dify 的响应配置;不配就回默认的 202 + 运行编号)</label>`
        + 下拉(String(回.status_code || ""), [["202", "202 已受理(默认)"], ["200", "200"]], (el) => {
            if (!el.value) { if (c.webhook_response) delete c.webhook_response.status_code; }
            else (c.webhook_response = c.webhook_response || {}).status_code = Number(el.value);
            if (c.webhook_response && !c.webhook_response.status_code && !(c.webhook_response.body || "").trim()) delete c.webhook_response;
            重画(); }, "202 已受理(默认)")
        + `<textarea data-k="${k体}" data-lb="返回体" rows="3" placeholder='例如:{"ok": true, "单号": "{{单号}}", "运行": "{{运行编号}}"}'>${esc(回.body || "")}</textarea>
        <div class="k">写 <code>{{参数名}}</code> 带回对方推来的值,<code>{{运行编号}}</code> / <code>{{状态}}</code> / <code>{{跑的版本}}</code> / <code>{{查结果}}</code> 是系统给的;写出来能解成 JSON 就按 JSON 回,否则按文字回。参数错、密钥错这些由系统回 4xx,不在这里配。</div>`;
    }
    if (方式 === "定时") {
      const r = c.schedule_rule = c.schedule_rule || { 周期: "周", 周几: [0], 时刻: "08:00" };
      // 两种模式(11-21 规划 2-1,照 Dify 面板顶上的「可视化 / Cron 表达式」):切过去带等价表达式(服务端算的,预览里顺带回),切回来从头选
      const 是cron = r.周期 === "cron";
      体 += `<label class="f">怎么定频率</label><div class="seg" role="tablist">
        <button type="button" data-k="${挂控件(() => 切定时模式(r, "可视化"))}" data-lb="可视化模式" role="tab" aria-selected="${!是cron}">可视化</button>
        <button type="button" data-k="${挂控件(() => 切定时模式(r, "cron"))}" data-lb="Cron 模式" role="tab" aria-selected="${是cron}">Cron 表达式</button></div>`;
      if (是cron) {
        体 += `<label class="f">Cron 表达式(分 时 日 月 周,北京时间)</label>`
          + 输入框(r.表达式 || "", (el) => { r.表达式 = el.value.trim(); 重画(); }, "0 8 * * 1")
          + `<div class="k">例:<code>0 8 * * 1</code> 每周一 08:00 · <code>30 8,20 * * *</code> 每天两次 · <code>0 8 1 * *</code> 每月 1 号 · <code>0 8 1 1 *</code> 每年元旦。认 * / 数字 / 范围 / 逗号 / 步长(*/15),周 0 和 7 都是周日;「最后一天」Cron 写不出来,用可视化模式的「末」。</div>`;
      } else {
        体 += `<label class="f">多久跑一次</label>` + 下拉(r.周期 || "周", Object.entries(周期说法), (el) => {
          if (!el.value) return false;
          r.周期 = el.value;
          if (el.value === "周" && !(r.周几 || []).length) r.周几 = [0];
          if (el.value === "月" && !(r.几号 || []).length) r.几号 = [1];
          重画();
        }, "请选择");
        if (r.周期 === "周") 体 += `<div class="k">哪几天</div><div>` + 周几名.map((名, i) =>
          `<label class="k"><input type="checkbox" data-k="${挂控件((el) => { const w = new Set(r.周几 || []); if (el.checked) w.add(i); else w.delete(i); r.周几 = [...w].sort(); 重画(); })}" data-lb="周几" ${(r.周几 || []).includes(i) ? "checked" : ""}> ${名}</label>`).join(" ") + `</div>`;
        if (r.周期 === "月") 体 += `<label class="f">几号</label>` + 输入框((r.几号 || [1]).join(","), (el) => { r.几号 = 读几号(el.value); 重画(); }, "1,15,末")
          + `<div class="k">逗号分开;最后一天写「末」;31 号碰上小月落到月末跑。</div>`;
        体 += `<label class="f">${r.周期 === "时" ? "每小时的第几分(时:分里只用分)" : "几点跑(北京时间)"}</label>`
          + 输入框(r.时刻 || "08:00", (el) => { r.时刻 = el.value.trim() || "08:00"; 重画(); }, "08:00");
      }
      体 += `<div class="note">${md("只跑**生产那一版**;同一期只跑一次;关机错过的只补最近一期;上一次没跑完就跳过(10-26 拍)。开始交给下一步两项:**统计起 / 统计止** = 上一次该跑到这一次该跑之间。打开 / 关掉在「版本与发布」页签里。")}</div>
        <div id="sc-prev" class="k">接下来 5 次:读取中…</div>`;
      setTimeout(() => 填定时预览(r), 0);
    } else {
      体 += `<label class="f">使用者要提供什么</label>` + 字段表编辑(c.input_schema = c.input_schema || { type: "object", properties: {}, required: [] }, true);
    }
    // 术语(11-06 深夜补):整条流程选一版,挂在开始节点上 —— 模型步骤只带这一步提到的那几条
    体 += `<label class="f">这条流程用哪一版术语</label>`
      + 资源选择器("术语版本", c.glossary_version_id, (g.资源.术语 || []).map((v) => ({ id: v.id, 名: v["名称"], 版: v["版本"], 说: `${v["条数"]} 条`, 标: "已冻结" })),
          (id) => { c.glossary_version_id = id || undefined; 重画(); }, "这个项目还没有冻结的术语版本 —— 先去「术语配置」冻一版;不选就是不带术语")
      + (c.glossary_version_id ? `<div class="k">不想带术语:在上面选回「请选择术语版本」。换术语版本 = 改了流程,发生产前要重新跑通。</div>`
                                : `<div class="k">不选 = 不带术语。选了之后,每个模型步骤只带这一步提到的那几条。</div>`);
  } else if (n.type === "answer" || n.type === "template") {
    // 直接回复 / 模板转换(10-27):模板里写 {{名字}},名字在下面「用到的数据」里选来源。写了新名字就**自动加一行待选来源** ——
    // 不加的话,人写完模板以为好了,检查配置才说「单号没有来源」
    const 名们 = 回复占位名(c.template), 缺 = 名们.filter((k) => !(k in (c.bindings || {})));
    const k = 挂控件((el) => {
      c.template = el.value;
      c.bindings = c.bindings || {};
      回复占位名(el.value).forEach((x) => { if (!(x in c.bindings)) c.bindings[x] = null; });
      重画();
    });
    体 += n.type === "answer" ? `<label class="f">回复什么</label>
      <textarea data-k="${k}" data-vpick="1" data-lb="回复内容" rows="4" placeholder="例如:{{客户}}您好,您的需求已记下,店长核对后会联系您">${esc(c.template || "")}</textarea>
      <div class="k">这句话会发回聊天里;管理后台试运行时用对话气泡显示。要带上前面的结果就写 <code>{{名字}}</code>,名字在下面「用到的数据」里选来源。</div>`
      : `<label class="f">模板</label>
      <textarea data-k="${k}" data-vpick="1" data-lb="模板" rows="5" placeholder="例如:{{客户}} 想要 {{款式}},预算 {{预算}},下次跟进 {{日期}}">${esc(c.template || "")}</textarea>
      <div class="k">把前面的结果拼成一段文字,交给后面的步骤用(不发给聊天里的人)。写 <code>{{名字}}</code>,名字在下面「用到的数据」里选来源。
        只做替换 —— 要按条件写不同的话,用「条件分支」分开写。</div>`;
    // 变量标签(11-15,照 Dify):模板里每个 {{名字}} 一枚 —— 来源说得出就写「步骤 → 字段」,没选 / 来源删了 / 不在上游就标红
    const 标们 = 图逻辑.变量标签(c.template, c.bindings, 上游字段(n.id), 图态.定义, 引用值);
    体 += `<div class="vpick-pop" id="vpick-pop" role="listbox" hidden></div>
      <div class="k">输 <code>{</code> 或 <code>/</code> 选前面步骤的结果,会插成 <code>{{名字}}</code> 并自动填好来源。</div>`
      + (标们.length ? `<div class="vtags">${标们.map((x) => `<span class="vtag${x.坏 ? " bad" : ""}" title="${esc(x.坏 ? x.原因 : x.标签)}">{{${esc(x.名)}}} ${x.坏 ? `· ${esc(x.原因)}` : `← ${esc(x.标签)}`}</span>`).join("")}</div>` : "");
    体 += `
      ${缺.length ? `<div class="ferr">模板里的 ${缺.map((x) => `「${esc(x)}」`).join("、")} 还没在「用到的数据」里 —— 运行前要选来源</div>` : ""}`;
  } else if (n.type === "list_operator") {
    // 列表操作(11-12,照 Dify):先过滤、再排序、再取前几个。**规则全是选出来的,没有表达式框** —— 和后端 runtime/列表操作.py 同一套
    const f = c.filter, s = c.sort;
    体 += `<div class="note">顺序固定:<b>先过滤、再排序、再取前几个</b>。列表里是一条条记录时,「看哪一项」填记录里的名字(比如 金额);是一个个数字或文字时留空,就是比这一项本身。</div>`;
    体 += `<label class="f">过滤</label>`;
    if (!f) {
      体 += `<button data-k="${挂控件(() => { c.filter = { conditions: [{ op: "equals", value: "" }], logic: "and" }; 重画(); })}">加过滤条件</button>
        <div class="k">不过滤 = 全都留下。</div>`;
    } else {
      const 条们 = f.conditions = f.conditions || [];
      体 += (条们.length > 1 ? 下拉(f.logic || "and", [["and", "且:每条都满足才留下"], ["or", "或:有一条满足就留下"]], (el) => { f.logic = el.value; 重画(); }) : "")
        + 条们.map((w, j) => {
          const 一元 = 列表一元比法.includes(w.op);
          return `<div class="condrow">
            <div class="k">第 ${j + 1} 条${j ? (f.logic === "or" ? " · 或" : " · 且") : ""} · 看哪一项</div>${输入框(w.field || "", (el) => {
              const v = el.value.trim(); if (v) w.field = v; else delete w.field; }, "留空 = 这一项本身", { 可清空: true })}
            <div class="k">怎么比</div>${下拉(w.op || "", 列表比法, (el) => {
              w.op = el.value || undefined;
              if (列表一元比法.includes(w.op)) delete w.value; else if (!("value" in w)) w.value = "";
              重画(); }, "选比较方式")}
            ${一元 ? "" : `<div class="k">跟什么比</div>${输入框(w.value ?? "", (el) => { w.value = 列表比较值(w.op, el.value, w.value); 重画(); },
                ["gt", "gte", "lt", "lte"].includes(w.op) ? "填数字" : ["date_before", "date_after"].includes(w.op) ? "例如 2026-11-12" : "", { 可清空: true })}
              ${["equals", "not_equals", "contains"].includes(w.op) ? `<div class="k">现在按${typeof w.value === "number" ? "<b>数字</b>" : "<b>文字</b>"}比 ·
                <button data-k="${挂控件(() => { w.value = typeof w.value === "number" ? String(w.value) : (Number.isFinite(Number(w.value)) && String(w.value).trim() !== "" ? Number(w.value) : w.value); 重画(); })}">改成按${typeof w.value === "number" ? "文字" : "数字"}比</button>
                (文字「100」和数字 100 不一样,不会悄悄转换)</div>` : ""}`}
            <button class="danger" data-k="${挂控件(() => { 条们.splice(j, 1); if (!条们.length) delete c.filter; 重画(); })}" aria-label="删掉第 ${j + 1} 条过滤条件">删掉这条</button></div>`;
        }).join("")
        + `<button data-k="${挂控件(() => { 条们.push({ op: "exists" }); 重画(); })}">再加一条</button>
           <div class="k">某一项可能没有「看哪一项」那个名字时,先加一条「有这一项」并用「且」连 —— 不然跑到它这一步会失败。</div>`;
    }
    体 += `<label class="f">排序</label>` + (!s
      ? `<button data-k="${挂控件(() => { c.sort = { order: "asc" }; 重画(); })}">加排序</button><div class="k">不排序 = 保持原来的先后。</div>`
      : `<div class="two"><div><div class="k">按哪一项排</div>${输入框(s.field || "", (el) => { const v = el.value.trim(); if (v) s.field = v; else delete s.field; }, "留空 = 这一项本身", { 可清空: true })}</div>
          <div><div class="k">方向</div>${下拉(s.order || "", [["asc", "从小到大"], ["desc", "从大到小"]], (el) => { s.order = el.value || undefined; }, "选方向")}</div></div>
         <div class="k">一样大的保持原来的先后。那一项要么全是数字、要么全是文字;有的没有、或者混着,这一步会失败(不猜顺序)。</div>
         <button class="danger" data-k="${挂控件(() => { delete c.sort; 重画(); })}">不排序了</button>`);
    体 += `<label class="f">只要前几个(选填)</label>` + 数字框(c.limit, (v) => { if (v === undefined) delete c.limit; else c.limit = v; }, { 整数: true, 最小: 1, 提示: "留空 = 全都要" });
  } else if (n.type === "foreach") {
    // 列表迭代(11-12,照 Dify「迭代」):一次一项跑里面的步骤,收每一项交出的结果 —— 规则和后端 runtime/列表迭代.py 同一套
    const 里面 = g.定义.nodes.filter((x) => x.container === n.id);
    const 可交 = 里面.flatMap((x) => 结果字段名(x).map((f) => [`n:${x.id}:${f}`, `${业务名(x)} → ${f}`]));
    体 += `<div class="note">对「用到的数据」里的<b>列表</b>逐项跑一遍里面的步骤,<b>一次一项</b>;每一项交出的东西按原来的顺序收成「结果」。
      里面的步骤在「用到的数据」里能选 <b>迭代 · 当前项</b>(这一项本身,是记录的话可以往下取一项)和 <b>迭代 · 下标</b>(从 0 数)。</div>`;
    体 += `<label class="f">每一项做完交出什么</label>` + (里面.length
      ? 下拉(引用值(c.item_output), 可交, (el) => { c.item_output = 解引用(el.value) || undefined; 重画(); }, "选里面某一步的一项结果")
      : `<div class="ferr">迭代里面还没有步骤 —— 先往里面放步骤(在那一步的「高级」里选「放在哪个循环 / 迭代里」),再回来选</div>`);
    体 += `<label class="f">某一项失败时</label>` + 下拉(c.item_failure_policy || "", [["fail", "整步失败(走「失败时」那条线,记下是第几项、为什么)"],
        ["continue", "这一项留空位,接着做下一项"]], (el) => { c.item_failure_policy = el.value || undefined; 重画(); }, "选一种")
      + `<div class="k">留空位:那一项在「结果」里是空(null)、原因记进「失败项」—— 失败的那一项<b>不会被删掉</b>,删了后面会全体错位。</div>`;
    体 += `<label class="f">最多做几项(1–100)</label>` + 数字框(c.max_items ?? "", (v) => { if (v === undefined) delete c.max_items; else c.max_items = v; }, { 整数: true, 最小: 1, 提示: "按这条流程一次该处理多少条填" })
      + `<div class="k">列表比这个长,<b>一项都不做</b>,这一步直接失败(不会只做前几项交出一份缺尾巴的结果)。100 是一步里能装下的运行记录的技术上限,不是业务建议。
        里面不能再放循环或迭代。</div>`;
  } else if (n.type === "parallel") {
    // 并行与汇总(11-16 三期 3-2):语义照规格 §6.3(独立支路、等全部必需支路、两种等待策略),一期串行实现 —— 规则和后端 runtime/并行.py 同一套
    const 支路们 = Array.isArray(c.branches) ? c.branches : (c.branches = []);
    体 += `<div class="note">几条支路<b>各走各的</b>,全部做完再往下走;结果按支路名收(「结果 → 支路名」)。支路之间<b>不能互相取结果</b>(真并发时谁先做完不一定,一期虽然一条接一条跑,规矩和并发时一样)。
      每条支路从它自己的出口连到支路里的第一步;支路里的步骤在「高级」里选「放在哪个循环 / 迭代里 → 这个并行」。</div>`;
    体 += `<label class="f">支路</label>` + (支路们.length ? 支路们.map((b, i) => `<div class="card" data-branch="${esc(b.key || "")}">
        <div class="row"><label>支路名</label>${输入框(b.key || "", (el) => { const 旧 = b.key, 新 = String(el.value || "").trim();
            if (新) b.key = 新; else delete b.key;
            // 挂在这条支路出口上的连线跟着改名 —— 不然改个名就留一条挂在「不存在的支路」上的孤线(检查配置会报)
            if (旧 && 新) (g.定义.edges || []).forEach((e) => { if (e.source === n.id && e.port === "parallel" && e.branch_key === 旧) e.branch_key = 新; });
            重画(); }, "例如 查库存")}
        <label>要不要等它</label>${下拉(b.required === false ? "false" : "true", [["true", "必需(它失败整步按等待策略处理)"], ["false", "可选(做完了带上,失败只记状态)"]],
            (el) => { if (el.value === "false") b.required = false; else delete b.required; 重画(); })}
        <button data-k="${挂控件(() => { 支路们.splice(i, 1); 重画(); })}" aria-label="删掉支路 ${esc(b.key || "")}">删</button></div></div>`).join("")
      : `<div class="k">还没有支路 —— 点下面「加一条支路」,至少两条才有并行的意义。</div>`)
      + `<button data-k="${挂控件(() => { let j = 支路们.length + 1; while (支路们.some((x) => x.key === `支路${j}`)) j++; 支路们.push({ key: `支路${j}` }); 重画(); })}">加一条支路</button>`;
    体 += `<label class="f">等待策略</label>` + 下拉(c.wait_policy || "all_required",
        [["all_required", "等全部必需支路结束;任一必需支路失败,这一步失败(走「失败时」)"], ["allow_partial", "允许部分结果:失败的支路留空、状态记 failed,其余照样汇总"]],
        (el) => { c.wait_policy = el.value; 重画(); })
      + `<div class="k">「全部做完」才算这一步做完 —— <b>不会完成一条就宣告整组成功</b>。</div>`;
    体 += `<label class="f">并发上限</label><div class="k">一期固定 <b>1</b>(几条支路一条接一条跑);真并发下一期开,到时这里能填。</div>`;
    if (c.max_concurrency !== 1) c.max_concurrency = 1;
  } else if (n.type === "subworkflow") {
    // 子工作流(11-16 三期 3-3):只引冻结版、不许引自己(递归另有服务端静态检查)、预算随父 —— 规则和后端 runtime/子工作流.py 同一套
    const 版们 = (g.资源.工作流版本 || []).filter((x) => x["工作流id"] !== g.wid), v = 子流程版本(c.workflow_version_id);
    体 += `<div class="note">把一条<b>已冻结</b>的流程当成这里的一步来跑:交给它输入,它跑完把「最后返回什么」交回来。只能选版本(草稿还会变);
      不能选这条流程自己,也不能绕着圈引回来(检查配置会拦)。一期子流程在这一步里<b>一口气跑完</b> —— 里面不能有等人核对、Agent、写数据的动作。</div>`;
    体 += `<label class="f">用哪一版子流程</label>`
      + 资源选择器("子流程版本", c.workflow_version_id, 版们.map((x) => {
          // 「要什么 / 返回什么」放进选项文字(标),选的时候就看得见;「说」只用于搜索
          const 要 = Object.keys(((x["入参结构"] || {}).properties) || {}).join("、") || "(不要输入)";
          const 回 = Object.keys(((x["出参结构"] || {}).properties) || {}).join("、") || "(没声明)";
          return { id: x.id, 名: x["名"], 说: `${要} ${回}`, 标: `v${x["版本"]} · 要:${要} · 返回:${回}` };
        }),
          (id) => { c.workflow_version_id = id || undefined; c.input_mapping = {}; 重画(); },
          "这个项目里还没有别的流程冻结过版本 —— 先把要复用的那条流程「生成版本」,再回来选。");
    if (v) 体 += `<div class="k">它要的输入在下面「用到的数据」里逐项选来源;它返回什么见「结果」。</div>`;
    const 限 = c.sub_limits = c.sub_limits || {};
    体 += `<label class="f">这一步的上限(留空 = 跟父流程一样;填了不许超过父流程)</label>
      <div class="fieldrow"><label>最多调模型几次</label>${数字框(限.max_model_turns ?? "", (x) => { if (x === undefined) delete 限.max_model_turns; else 限.max_model_turns = x; }, { 整数: true, 最小: 1, 提示: "留空 = 跟父流程" })}</div>
      <div class="fieldrow"><label>最多调工具几次</label>${数字框(限.max_tool_calls ?? "", (x) => { if (x === undefined) delete 限.max_tool_calls; else 限.max_tool_calls = x; }, { 整数: true, 最小: 1, 提示: "留空 = 跟父流程" })}</div>
      <div class="k">子流程用掉的额度<b>计入这条流程</b>(嵌套不能重新拿一份预算)。</div>`;
  } else if (n.type === "doc_extractor") {
    // 文档提取器(11-12,照 Dify):文件在下面「用到的数据」里选
    体 += `<div class="note">从前面给的<b>已上传文件</b>里取出文字,交给后面的步骤(比如交给 AI 处理去总结)。
      文件是上传记录的编号,一般在「开始」里让使用者给;给一个就取出一段文字,给一组就取出一组。</div>
      <div class="k">现在能取:Markdown(.md)和纯文本(.txt),UTF-8 编码 —— 也就是上传那里收的那几种。<b>取不了的格式、没传完 / 校验没过的文件、空文件,这一步会失败</b>,不会交给后面一段空文字;
      要接人工,在「高级」里把「失败后怎么办」设成走「失败时」那条线。一步最多读 10 份。</div>`;
  } else if (n.type === "end") {
    体 += `<div class="k">返回哪些内容、各从哪来 —— 在下面「结果」和「用到的数据」里配。</div>`;
  } else {
    体 += `<div class="note">${md(元(n.type)["说明"] || "")}</div><div class="k">这一类步骤的细项在下面「高级」里(默认收起)。</div>`;
  }
  // 下一步(连线编辑)
  const 口们 = 出口们(n);
  if (口们.length) {
    // 同名步骤加简短序号区分 —— 业务人员不需要认内部 id(§6.2)
    const 同名 = {};
    const 候选 = 图态.定义.nodes.filter((x) => x.id !== n.id && x.type !== "start").map((x) => {
      const 名 = 业务名(x); 同名[名] = (同名[名] || 0) + 1;
      return [x.id, `${名}${图态.定义.nodes.filter((y) => 业务名(y) === 名).length > 1 ? ` #${同名[名]}` : ""} · ${次级标签(x)}`];
    });
    体 += `<h4>下一步</h4><div class="two">` + 口们.map((o) => {
      const e = 图态.定义.edges.find((x) => x.source === n.id && 同口(x, o));
      // 和图上拖线**同一套校验**(连接校验:环 / 开始 / 作用域);不合法 → 不改,说为什么
      return `<div class="fieldrow"><label>${esc(o.名)}</label>${下拉(e ? e.target : "", 候选, (el) => {
        if (!el.value) { if (e) 图逻辑.删边(图态.定义, 图逻辑.边键(e)); 重画(); return; }
        const v = 图逻辑.连接校验(图态.定义, n.id, o, el.value, 元);
        if (!v.可以) { 轻提示(`没改:${v.为什么}`); el.value = e ? e.target : ""; return false; }
        图逻辑.连(图态.定义, n.id, o, el.value);
        if (v.替换) 轻提示(`已把「${o.名}」的下一步从「${业务名(节点(v.替换.target))}」改为「${业务名(节点(el.value))}」`, { 撤销: true });
        重画();
      }, o.port === "error" ? "失败就结束这次运行" : o.port === "timeout" ? "(不接:到期这次运行结束)" : "(不接)")}</div>`;
    }).join("") + `</div>`;
  }
  return 体;
}

/* 数据从哪来:固定值 / 使用者输入 / 上一步结果。值编码成 "c:…" "i:字段" "n:步骤:字段" */
function 上游字段(id) {
  const g = 图态, 出 = [];
  const 起 = g.定义.nodes.find((n) => n.type === "start");
  Object.keys(((起 || {}).config?.input_schema || {}).properties || {}).forEach((k) => 出.push([`i:${k}`, `使用者输入 · ${k}`]));
  // 循环里的步骤(和循环自己的继续条件)能取「循环状态」(10-27)
  const 本 = g.定义.nodes.find((x) => x.id === id), 环 = 本 && (本.type === "loop" ? 本 : 本.container && 节点(本.container));
  if (环) Object.keys((环.config || {}).loop_state || {}).forEach((k) => 出.push([`s:${k}`, `循环状态 · ${k}`]));
  // 列表迭代里面的步骤能取「当前项」「下标」(11-12);迭代自己不能取 —— 它在逐项开始之前就要拿到列表
  const 迭 = 本 && 本.container && 节点(本.container);
  if (迭 && 迭.type === "foreach") 出.push(["s:当前项", "迭代 · 当前项"], ["s:下标", "迭代 · 下标(从 0 数)"]);
  // 只列**在它之前**的步骤(沿边倒着走)—— 列它之后的步骤,运行时一定取不到。
  // 而「在它之前」≠「一定走过」:分支 A 的结果在分支 B 那条路上没有值 —— 标出来,不悄悄当成必有(§8.2)
  const { 前驱: 前, 必经 } = 图逻辑.前驱与必经(g.定义, id);
  g.定义.nodes.filter((n) => 前.has(n.id) && n.type !== "start").forEach((n) => {
    结果字段名(n).forEach((f) => 出.push([`n:${n.id}:${f}`, `${业务名(n)} → ${f}${必经.has(n.id) ? "" : "(仅部分路径有值)"}`]));
  });
  return 出;
}
function 结果字段名(n) {
  const c = n.config || {};
  if (n.type === "human") {   // 11-20 表单化:核对人填的字段 + 点的哪个按钮(__action_id,照 Dify)也给下游
    const 字段 = (c.form_fields || []).map((f) => f && f.name).filter(Boolean);
    return [...new Set(["决定", "定稿", "理由", "处理人", ...字段, ...((c.actions || []).length ? ["__action_id"] : [])])];
  }
  if (n.type === "answer") return ["回复"];
  if (n.type === "template") return ["文本"];
  if (n.type === "list_operator") return ["结果", "个数", "第一个", "最后一个"];
  if (n.type === "doc_extractor") return ["文本", "文件名"];
  if (n.type === "foreach") return ["结果", "个数", "失败项"];
  if (n.type === "parallel") return ["结果", "状态", "失败支路"];
  if (n.type === "subworkflow") {   // 子流程返回什么 = 引的那一版「最后返回什么」里声明的字段
    const v = 子流程版本((n.config || {}).workflow_version_id);
    return Object.keys((((v || {})["出参结构"] || {}).properties) || {});
  }
  if (n.type === "assigner") return [...new Set((c.assignments || []).map((a) => a.variable).filter(Boolean))];
  if (n.type === "extractor") return (c.parameters || []).map((p) => p.name).filter(Boolean);
  if (n.type === "classifier") return ["类别", "理由"];
  // HTTP 请求固定返回(runtime/HTTP请求.py 的结果形状;mock 跑法同形):状态码 / 响应头 / 正文 / 解出的 JSON / 实际地址 / 执行模式
  if (n.type === "http_request") return ["status_code", "headers", "body", "json", "url", "execution_mode"];
  // 知识检索固定返回(workers/worker.py _retrieve 的结果形状;mock 跑法同形、全空)
  if (n.type === "retrieve") return ["片段", "证据", "召回数", "选了几片", "原问", "改写", "试跑id", "execution_mode"];
  // Markdown 导出固定返回(workers/worker.py _markdown_export 的结果形状)
  if (n.type === "markdown_export") return ["document_id", "file_name", "content_hash", "byte_count", "title", "门店", "下载", "execution_mode"];
  if (n.type === "condition") return ["branch"];
  if (n.type === "merge") return [c.output_field || "out"];
  if (n.type === "tool") {
    const t = 工具资源(c.tool_version_id);
    return Object.keys(((t || {})["出参"] || {}).properties || {});
  }
  return Object.keys((c.output_schema || {}).properties || {});
}
function 引用值(r) {
  if (!r) return "";
  if (r.source === "input") return `i:${String(r.pointer || "").replace(/^\//, "")}`;
  if (r.source === "node") return `n:${r.node_id}:${String(r.pointer || "").replace(/^\//, "")}`;
  if (r.source === "constant") return `c:${r.value ?? ""}`;
  if (r.source === "scope") return `s:${String(r.pointer || "").replace(/^\//, "")}`;
  return "";
}
function 解引用(v) {
  if (!v) return null;
  if (v.startsWith("i:")) return { source: "input", pointer: "/" + v.slice(2) };
  if (v.startsWith("n:")) { const [, id, ...f] = v.split(":"); return { source: "node", node_id: id, pointer: "/" + f.join(":") }; }
  if (v.startsWith("s:")) return { source: "scope", pointer: "/" + v.slice(2) };
  return { source: "constant", value: v.slice(2) };
}

function 绑定编辑(n, 键名, 契约 = null) {
  const 绑 = n.config[键名] = n.config[键名] || {};
  const 源们 = 上游字段(n.id);
  // 业务动作有自己的参数契约:**契约里的参数行由它生成、名字只读**,必填的不能删(只能移除来源后显示缺失);
  // 契约里没有的参数标出来(填了也不会用上)。工具定义在「工具目录」里改,不在流程里改(W24 · §7.3)
  const 契 = (契约 && 契约.properties) || null, 必 = new Set((契约 && 契约.required) || []);
  const 键们 = 契 ? [...new Set([...Object.keys(契), ...Object.keys(绑)])] : Object.keys(绑);
  const 待核 = ((图态.待核对 || {})[n.id]) || [];
  const 行 = 键们.map((k) => [k, 绑[k]]).map(([k, r]) => {
    const 在契约 = 契 && Object.prototype.hasOwnProperty.call(契, k);
    const 契约外 = 契 && !在契约;
    const 是固定 = r && r.source === "constant";
    const 失效 = r && r.source === "node" && !节点(r.node_id);
    const 部分 = r && r.source === "node" && 节点(r.node_id) && !图逻辑.前驱与必经(图态.定义, n.id).必经.has(r.node_id);
    return `<div class="card ${失效 ? "bad" : ""}">
      ${失效 ? `<div class="ferr">原来源「${esc(r.原名 || r.node_id)} · ${esc(String(r.pointer || "").replace(/^\//, ""))}」已删除 —— 选一个新来源,或撤销那次删除。运行和生成候选版本前要改好。</div>` : ""}
      ${部分 ? `<div class="ferr">这个来源只在部分路径上有值 —— 走另一条路时取不到。要么改成必经的来源,要么在汇合之后再取</div>` : ""}
      <div class="two"><div>${在契约 ? `<div class="k">参数</div><div><b>${esc(k)}</b> <span class="k">${esc(契[k].type || "")}${必.has(k) ? " · 必填" : " · 选填"}${契[k].description ? " · " + esc(契[k].description) : ""}</span></div>`
        : `<div class="k">字段</div>${输入框(k, (el) => {
        const 新 = el.value.trim(); if (!新 || 新 === k) return;
        绑[新] = 绑[k]; delete 绑[k]; 重画(); })}`}</div><div>
      <div class="k">从哪来</div>${下拉(是固定 ? "固定值" : 失效 ? "" : 引用值(r), [["固定值", "固定值(自己填)"], ...源们], (el) => {
        if (!el.value) { 绑[k] = null; 重画(); return; }
        const 新 = el.value === "固定值" ? { source: "constant", value: "" } : 解引用(el.value);
        if (新 && 新.source === "node" && 节点(新.node_id)) 新.原名 = 业务名(节点(新.node_id));   // 留原名:来源被删后还认得出是谁
        绑[k] = 新; 重画(); }, r ? "选一个来源" : "未设置来源")}</div></div>
      ${契约外 ? `<div class="ferr">「${esc(业务名(n))}」没有「${esc(k)}」这个参数 —— 填了不会用上,可以删掉</div>` : ""}
      ${待核.includes(k) ? `<div class="ferr">换业务动作后这个参数的类型变了 —— 核对来源的类型,不会悄悄转成字符串</div>` : ""}
      ${是固定 ? `<div class="k">填什么</div>${输入框(r.value, (el) => { r.value = el.value; }, "", { 可清空: true })}` : ""}
      <div class="k">${r && r.source === "node" && !失效 ? "正式运行时取那一步的真实结果;还没跑过,所以这里没有样例" : r ? "" : "未设置来源 —— 字段还在,运行前要选"}</div>
      <div class="acts">${r ? `<button data-k="${挂控件(() => { 绑[k] = null; 重画(); })}">移除来源</button>` : ""}
        ${在契约 && 必.has(k) ? `<span class="k">必填参数不能删,只能移除来源</span>`
          : 在契约 && !r ? "" : `<button class="danger" data-k="${挂控件(() => { delete 绑[k]; 轻提示(`已删除字段「${k}」`, { 撤销: true }); 重画(); })}">删除字段</button>`}</div></div>`;
  }).join("");
  return 行 + (契 ? "" : `<button data-k="${挂控件(() => {
      let i = 1; while (绑[`字段${i}`]) i++; 绑[`字段${i}`] = null; 重画(); })}">加一个字段</button>`)
    + (源们.length ? "" : `<div class="note">这一步前面还没有能取值的步骤 —— 先把它接到流程里(左边「在此后添加」或「下一步」)。</div>`);
}

function 表_输入(n) {
  if (n.type === "start") return `<div class="k">开始这一步没有上游 —— 使用者要提供什么在上面「基本」里配。</div>`;
  if (n.type === "human") return `<div class="k">审核人会看到这些(左边原文、右边摘要)。「摘要」就是通过时默认的定稿。</div>`
    + 绑定编辑(n, "payload_binding");
  if (n.type === "condition") return `<div class="k">条件用到的值在上面「基本」里每一路单独选。</div>`;
  if (n.type === "code") return `<div class="k">输入变量:左边是变量名(代码里 main 的参数名),右边选它从哪来。只有这里列的变量会交给代码。</div>` + 绑定编辑(n, "input_mapping");
  if (n.type === "retrieve") return `<div class="k">知识检索只读一项:<b>问题</b>(要查的话)—— 绑开始的某一项,或前面某一步产出的文本。</div>`
    + 绑定编辑(n, "bindings", { properties: { 问题: { type: "string", description: "要查什么" } }, required: ["问题"] });
  if (n.type === "markdown_export") return `<div class="k">要存成文件的<b>正文</b>(必填)从哪来 —— 一般是模型或模板转换产出的文本;可选:标题、统计起 / 统计止(定时开头的流程绑开始的那两项)、门店(决定哪家店的人能看到)。</div>`
    + 绑定编辑(n, "bindings", { properties: { 正文: { type: "string", description: "报告正文(Markdown)" }, 标题: { type: "string", description: "文件标题,进文件名" },
        统计起: { type: "string", description: "统计哪一段,起" }, 统计止: { type: "string", description: "统计哪一段,止" }, 门店: { type: "string", description: "门店编号,如 SH001" } }, required: ["正文"] });
  if (n.type === "parallel") return `<div class="k">并行这一步自己不取数 —— 每条支路里的步骤各自在自己的「用到的数据」里选(只能选并行外面的步骤,不能选另一条支路的)。</div>`;
  if (n.type === "subworkflow") {   // 交给子流程什么:按它那一版「要用户给什么」逐项选来源(契约行由它生成、名字只读,必填的不能删)
    const v = 子流程版本((n.config || {}).workflow_version_id);
    if (!v) return `<div class="k">先在「基本」里选一版子流程,这里再按它要的输入逐项选来源。</div>`;
    const 入 = v["入参结构"] || {};
    if (!Object.keys(入.properties || {}).length) return `<div class="k">这一版子流程不要任何输入。</div>`;
    return `<div class="k">子流程「${esc(v["名"])}」要这些输入,各从哪来:</div>` + 绑定编辑(n, "input_mapping", { properties: 入.properties || {}, required: 入.required || [] });
  }
  if (n.type === "list_operator" || n.type === "doc_extractor" || n.type === "foreach") {
    // 列表操作 / 文档提取器(11-12):只读固定的那一项(列表 / 文件),多出来的绑定不会被读 —— 检查配置会拦
    const 键 = n.type === "doc_extractor" ? "文件" : "列表", 绑 = n.config.bindings = n.config.bindings || {};
    const 多 = Object.keys(绑).filter((k) => k !== 键);
    return `<div class="k">${n.type === "foreach" ? "要逐项处理的列表从哪来(选一个列表类型的结果,比如 列表操作 → 结果)" : n.type === "list_operator" ? "要处理的列表从哪来(选一个列表类型的结果)" : "文件从哪来(上传记录的编号,一个或一组;一般是「开始」里让使用者给的)"}:</div>
      <div class="fieldrow"><label>${键}</label>${下拉(引用值(绑[键]), 上游字段(n.id), (el) => { if (el.value) 绑[键] = 解引用(el.value); else delete 绑[键]; 重画(); }, "选一个来源")}</div>`
      + (多.length ? `<div class="ferr">「用到的数据」里多了 ${多.map((k) => `「${esc(k)}」`).join("、")},这一步不读它们 ·
          <button data-k="${挂控件(() => { 多.forEach((k) => delete 绑[k]); 重画(); })}">删掉多出来的</button></div>` : "")
      + (上游字段(n.id).length ? "" : `<div class="note">这一步前面还没有能取值的步骤 —— 先把它接到流程里。</div>`);
  }
  if (n.type === "merge") return `<div class="k">汇合会取下面<b>第一个有值</b>的那一路(条件没走的那一路没有值)。</div>`
    + (n.config.candidates || []).map((r, i) => `<div class="fieldrow"><label>第 ${i + 1} 路</label>${下拉(引用值(r), 上游字段(n.id),
        (el) => { n.config.candidates[i] = 解引用(el.value); })}</div>`).join("")
    + `<button data-k="${挂控件(() => { (n.config.candidates = n.config.candidates || []).push(null); 重画(); })}">加一路</button>`;
  if (n.type === "http_request") {
    // 绑定只认这三项(worker 把它们盖在「基本」里写死的底上);别的键不会被读 —— 契约外的 绑定编辑 会标出来
    const 契约 = { type: "object", properties: {
      path: { type: "string", description: "路径(盖掉「基本」里写的那条)" },
      query: { type: "object", description: "查询串(整个对象;和「基本」里的合并,同名以这里为准)" },
      headers: { type: "object", description: "请求头(整个对象;鉴权头会被丢掉)" } }, required: [] };
    return `<div class="k">「基本」里写死的是底;要按上游的值拼地址,在这里把 path / query / headers 绑到某一步的结果。都不绑也行。</div>` + 绑定编辑(n, "bindings", 契约);
  }
  if (n.type === "tool") {
    const t = 工具资源(n.config.tool_version_id);
    if (!t) return `<div class="k">先在上面「基本」里选一个业务动作 —— 参数由它决定。</div>`;
    return `<div class="k">「${esc(t["名"])}」要这些参数(由它自己定义,这里只选每一项从哪来):</div>` + 绑定编辑(n, "bindings", t["入参"] || {});
  }
  return `<div class="k">这一步要用的数据,各自从哪来。</div>` + 绑定编辑(n, "bindings");
}

/* 哪些结构化引用指着这张字段表里的 k:开始节点的输入 → {source:"input"};某一步的结果 → {source:"node", node_id} */
function 字段引用(sch, k) {
  const g = 图态, 主 = g.定义.nodes.find((n) => n.config && (n.config.input_schema === sch || n.config.output_schema === sch));
  if (!主) return [];
  const 出 = [];
  const 扫 = (v) => {
    if (!v || typeof v !== "object") return;
    const 指 = String(v.pointer || "").replace(/^\//, "").split("/")[0];
    if (主.type === "start" && v.source === "input" && 指 === k) 出.push(v);
    if (主.type !== "start" && v.source === "node" && v.node_id === 主.id && 指 === k) 出.push(v);
    Object.values(v).forEach(扫);
  };
  g.定义.nodes.forEach((n) => { if (n !== 主) 扫(n.config); });
  return 出;
}
function 字段表编辑(sch, 是输入) {
  sch.properties = sch.properties || {}; sch.required = sch.required || [];
  const 行 = Object.entries(sch.properties).map(([k, v]) => `<tr>
      <td>${输入框(k, (el) => {
        const 新 = el.value.trim();
        if (!新 || 新 === k) { el.value = k; return false; }
        if (sch.properties[新]) { 轻提示(`没改:已经有字段叫「${新}」`); el.value = k; return false; }
        // 改的是**字段标识**:引用它的地方要同步,否则那几处会安静地取不到值
        const 引 = 字段引用(sch, k);
        sch.properties[新] = v; delete sch.properties[k];
        sch.required = sch.required.map((x) => (x === k ? 新 : x));
        if (引.length) 引.forEach((r) => { r.pointer = "/" + 新; });
        轻提示(引.length ? `已改字段标识「${k}」→「${新}」,同步更新了 ${引.length} 处引用(提示词正文里的文字不会被替换)` : `已改字段标识「${k}」→「${新}」`, { 撤销: true });
        重画(); })}</td>
      ${是输入 ? `<td>${输入框(v.title || "", (el) => { v.title = el.value.trim() || undefined; }, "页面上显示的名字")}</td>` : ""}
      <td>${下拉(v.type || "string", 结果类型们, (el) => { v.type = el.value; })}</td>
      <td><input type="checkbox" data-k="${挂控件((el) => {
        sch.required = el.checked ? [...new Set([...sch.required, k])] : sch.required.filter((x) => x !== k); })}"
        ${sch.required.includes(k) ? "checked" : ""}></td>
      <td>${输入框(v.description || "", (el) => { v.description = el.value.trim() || undefined; }, "说明 / 例子")}</td>
      <td><button class="danger" data-k="${挂控件(() => {
        const 引 = 字段引用(sch, k);
        delete sch.properties[k];
        sch.required = sch.required.filter((x) => x !== k);
        轻提示(`已删除字段「${k}」` + (引.length ? `;有 ${引.length} 处还在用它,已标「来源字段已删除」,要改` : ""), { 撤销: true });
        重画(); })}" aria-label="删除字段 ${esc(k)}">删除</button></td></tr>`).join("");
  return `<table><thead><tr><th>字段</th>${是输入 ? "<th>显示名</th>" : ""}<th>类型</th><th>必填</th><th>说明</th><th></th></tr></thead>
    <tbody>${行 || `<tr><td colspan="6" class="k">还没有字段</td></tr>`}</tbody></table>
    <button data-k="${挂控件(() => { let i = 1; while (sch.properties[`字段${i}`]) i++;
      sch.properties[`字段${i}`] = { type: "string" }; 重画(); })}">加一个字段</button>`;
}

function 表_结果(n) {
  const c = n.config;
  if (n.type === "tool") {
    const t = 工具资源(c.tool_version_id);
    const ps = Object.entries((((t || {})["出参"]) || {}).properties || {});
    return t ? `<div class="k">「${esc(t["名"])}」会返回这些(由它自己定义,这里不改):</div>
      <ul>${ps.map(([k, v]) => `<li><b>${esc(k)}</b> <span class="k">${esc(v.type || "")}</span></li>`).join("")}</ul>`
      : `<div class="k">先在上面「基本」里选一个业务动作。</div>`;
  }
  if (n.type === "http_request") return `<div class="k">固定返回:<b>status_code</b>(状态码)、<b>headers</b>(响应头)、<b>body</b>(正文文字)、<b>json</b>(正文能解成 JSON 时的对象,解不出就是空)、<b>url</b>(实际请求的完整地址)、<b>execution_mode</b>(live 真发了 / mock 一个字节没出去)。下游要取正文里某一项,绑 json 再在那一步里挑字段。</div>`;
  if (n.type === "human") return `<div class="k">人工核对固定返回:<b>决定</b>(approve / reject;配了按钮就是按钮标识)、<b>定稿</b>、<b>理由</b>、<b>处理人</b>${((c.form_fields || []).length ? `;表单字段:${(c.form_fields || []).map((f) => `<b>${esc(f.name || "")}</b>`).join("、")}` : "")}${((c.actions || []).length ? `;<b>__action_id</b>(点的哪个按钮)` : "")}。</div>`;
  if (n.type === "classifier") return `<div class="k">固定返回:<b>类别</b>(模型挑的那一个名字)、<b>理由</b>(它为什么这么分)。走哪条线由类别定。</div>`;
  if (n.type === "extractor") return `<div class="k">返回上面「基本」里列的每一项参数;<b>原文没提到的那一项是空</b>,必填的没抽到这一步就失败。</div>`;
  if (n.type === "assigner") return `<div class="k">返回改完之后的值(每一项一个)。循环里后面的步骤直接取「循环状态 · 名字」就是新值。</div>`;
  if (n.type === "list_operator") return `<div class="k">固定返回:<b>结果</b>(处理完的列表)、<b>个数</b>、<b>第一个</b>、<b>最后一个</b>。一个都不剩时结果是空列表,第一个 / 最后一个是空(null)—— 后面可以用条件分支判「个数 等于 0」。</div>`;
  if (n.type === "foreach") return `<div class="k">固定返回:<b>结果</b>(每一项交出的东西,顺序和给进来的列表一样)、<b>个数</b>、<b>失败项</b>(选了「留空位」时,哪一项、哪一步、为什么)。空列表时结果是空列表。</div>`;
  if (n.type === "parallel") return `<div class="k">固定返回:<b>结果</b>(按支路名存,每条支路的值 = 它最后一步交出的东西;失败的支路是空)、<b>状态</b>(每条支路 succeeded / failed)、<b>失败支路</b>(哪条、哪一步、为什么)。后面的步骤取「结果 → 支路名 → 字段」。</div>`;
  if (n.type === "subworkflow") {
    const v = 子流程版本((n.config || {}).workflow_version_id), 项 = 结果字段名(n);
    return `<div class="k">返回的就是引的那一版子流程「最后返回什么」:${v ? (项.length ? 项.map((f) => `<b>${esc(f)}</b>`).join("、") : "(那一版没声明返回什么)") : "先在「基本」里选一版子流程"}。另带「子流程步骤」摘要(里面每一步跑成什么样)。</div>`;
  }
  if (n.type === "doc_extractor") return `<div class="k">固定返回:<b>文本</b>(取出来的文字)、<b>文件名</b>。给的是一组文件时,两个都是列表、顺序和给进来的一样。</div>`;
  if (n.type === "template") return `<div class="k">固定返回:<b>文本</b>(填好名字之后的那一段)。后面的步骤在「用到的数据」里选它。</div>`;
  if (n.type === "answer") return `<div class="k">固定返回:<b>回复</b>(填好名字之后的那一句)。后面的步骤也能取它。</div>`;
  if (n.type === "end") {
    c.output_schema = c.output_schema || { type: "object", properties: {}, required: [] };
    return `<div class="k">最后返回哪些内容;每一项从哪来在上面「用到的数据」里选(字段名要和这里一致)。</div>`
      + 字段表编辑(c.output_schema, false);
  }
  if (["llm", "transform"].includes(n.type)) {
    c.output_schema = c.output_schema || { type: "object", properties: {}, required: [] };
    return `<div class="k">这一步的结果包含哪些内容。必填的没出来,这一步就算没做成。</div>` + 字段表编辑(c.output_schema, false);
  }
  return `<div class="k">这一类步骤的结果由它自己决定。</div>`;
}

function 表_高级(n) {
  const c = n.config, g = 图态, p = g.布局[n.id] || { x: 0, y: 0 };
  let 体 = "";
  // 放在哪个循环 / 迭代里(10-27 循环,11-12 迭代):里面的步骤每一轮 / 每一项都跑;循环、迭代、开始、输出不能放进去(不支持套着用)
  // 11-16 并行也是容器:普通步骤能放进去;循环 / 迭代 / 并行自己不给(不许套娃)
  const 环们 = g.定义.nodes.filter((x) => (x.type === "loop" || x.type === "foreach" || x.type === "parallel") && x.id !== n.id);
  if (环们.length && !["start", "end", "loop", "foreach", "parallel"].includes(n.type)) {
    体 += `<label class="f">放在哪个循环 / 迭代里</label>` + 下拉(n.container || "", 环们.map((x) => [x.id, `${业务名(x)}${x.type === "parallel" ? "(并行)" : ""}`]), (el) => {
      if (el.value) n.container = el.value; else delete n.container; 重画(); }, "不在循环 / 迭代 / 并行里")
      + `<div class="k">放进去之后:从循环的「进循环体」(迭代的「每一项做」、并行的某条「支路」)出口连到第一步;里面走到头 = 这一轮 / 这一项 / 这条支路做完。</div>`;
  }
  if ((元(n.type)["端口"] || []).includes("error")) {
    // 11-15 工作流一期第二件:第三种走法「按默认值继续」(照 Dify「异常处理 · 默认值」)。
    // 只给只读的那几类步骤;**写数据的业务动作不许**(用户 11-15 拍)—— 选了也会在「检查配置」里被挡住
    const 可默认 = !!元(n.type)["可按默认值继续"];
    const 走法 = [["fail_run", "这次运行失败"], ["branch", "走「失败时」那条线"]];
    if (可默认 || c.failure_policy === "default") 走法.push(["default", "按默认值继续(结果换成下面填的默认值)"]);
    体 += `<label class="f">失败后怎么办</label>` + 下拉(c.failure_policy || "fail_run", 走法,
      (el) => { c.failure_policy = el.value; if (el.value !== "default") delete c.default_output; 重画(); });
    if (c.failure_policy === "default") {
      体 += `<div class="k">这一步出错时,后面的步骤拿到的是这里填的值,外加系统自动写上的「错误类型 / 错误说明」两项;运行记录里这一步仍记「出错」。`
        + (n.type === "tool" ? `<b>会写数据的业务动作不能这样用</b>(发券失败却当成发了,后面会照着去通知顾客)—— 检查配置会挡住。` : "") + `</div>`;
      const 属性 = ((c.output_schema || {}).properties) || {};
      const 名们 = Object.keys(属性).length ? Object.keys(属性) : Object.keys(c.default_output || {});
      名们.forEach((k) => {
        const 型 = (属性[k] || {}).type || "string";
        const 现 = (c.default_output || {})[k];
        体 += `<label class="f">出错时「${esc(k)}」给什么</label>` + 输入框(现 === undefined ? "" : (型 === "string" ? 现 : JSON.stringify(现)), (el) => {
          const t = String(el.value);
          let v = t;
          if (型 !== "string") { try { v = JSON.parse(t); } catch (_) { v = t; } }
          c.default_output = { ...(c.default_output || {}) };
          if (t === "") delete c.default_output[k]; else c.default_output[k] = v;
          if (!Object.keys(c.default_output).length) delete c.default_output;
        }, 型 === "string" ? "比如:暂时查不到,请稍后再试" : `填 ${型} 的值`);
      });
      if (!名们.length) 体 += `<div class="k">这一步还没定输出长什么样 —— 先在「基本」里把输出字段定好,这里才知道要填哪几项。</div>`;
    }
  }
  if (n.type === "llm") {
    体 += `<label class="f">最多输出多少 token</label>` + 数字框(c.max_output_tokens ?? "", (v) => {
      c.max_output_tokens = v; }, { 整数: true, 最小: 1, 提示: "不填 = 用模型默认值" });
    const m = (g.资源.模型 || []).find((x) => x["版本id"] === c.connection_version_id);
    if (m && (m["支持的参数"] || []).includes("temperature")) {
      体 += `<label class="f">随机程度(temperature)</label>` + 数字框((c.sampling_params || {}).temperature ?? "", (v) => {
        if (v === undefined) { if (c.sampling_params) delete c.sampling_params.temperature; return; }
        c.sampling_params = { ...(c.sampling_params || {}), temperature: v }; }, { 最小: 0, 提示: "不填 = 用模型默认值" });
    }
  }
  体 += `<details><summary>技术详情</summary>
      <div class="k">步骤编号 <code>${esc(n.id)}</code>(改名不会改它)</div>
      <div class="fieldrow"><label>X</label>${数字框(p.x, (v) => { g.布局[n.id] = { ...(g.布局[n.id] || p), x: v ?? 0 }; 重画(); }, { 最小: 0 })}</div>
      <div class="fieldrow"><label>Y</label>${数字框(p.y, (v) => { g.布局[n.id] = { ...(g.布局[n.id] || p), y: v ?? 0 }; 重画(); }, { 最小: 0 })}</div>
      <div class="k">位置只影响画法,不进逻辑哈希。</div>
      <label class="f">完整配置(JSON,直接改要懂结构)</label>
      <textarea rows="8" id="adv-json" spellcheck="false">${esc(JSON.stringify(c, null, 1))}</textarea>
      <div class="ferr" id="adv-err" role="alert"></div>
      <div class="acts"><button data-k="${挂控件(() => {
        // 应用前先解析:**不合法就不覆盖**现有有效配置,错误位置写在框下面(不弹框打断)
        const t = ($("#adv-json") || {}).value || "";
        try { const v = JSON.parse(t); if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("顶层要是一个对象 {}");
          n.config = v; 重画(); }
        catch (e) { const m = /position (\d+)/.exec(e.message), 行 = m ? t.slice(0, +m[1]).split("\n").length : null;
          if ($("#adv-err")) $("#adv-err").textContent = `没应用:${行 ? `第 ${行} 行附近 —— ` : ""}${e.message}`; return false; }
      })}">应用</button> <button type="button" id="adv-cancel">取消改动</button></div>
    </details>`;
  return 体;
}

function 画_问题() {
  const r = 图态.报告;
  if (!$("#bt")) return;
  if (!r) { $("#bt").innerHTML = `<div class="k">还没检查过配置 —— 点右上「检查配置」。</div>`; return; }
  const 过期 = 检查过期();
  const 头 = `<div class="k">这是对草稿 r${esc(String(图态.报告rev ?? "?"))} 的检查${图态.报告时 ? ` · ${时间(图态.报告时)}` : ""}
    ${过期 ? `<b class="stale">· 配置已修改,需重新检查</b>(下面的结论对着的是修改前的图)` : ""}</div>`;
  if (!r["问题"].length) {
    $("#bt").innerHTML = 头 + `<div class="k">✅ 配置检查通过。<b>它只说明定义合法</b> —— 模型答得对不对、澜绣那边通不通,要去「测试」里跑一条。</div>`;
    return;
  }
  $("#bt").innerHTML = 头 + `<div class="acts"><button id="is-prev">定位上一项</button> <button id="is-next">定位下一项</button>
      <span class="k">共 ${r["问题"].length} 项</span></div>` + r["问题"].map((p, i) => `
    <button class="issue ${p["级别"] === "blocking" ? "b" : "w"} ${图态.问题位 === i ? "on" : ""}" data-i="${i}">
      ${p.node_id && 节点(p.node_id) ? `<b>${esc(业务名(节点(p.node_id)))}</b> · ` : p.node_id ? `<b>${esc(p.node_id)}(已删除)</b> · ` : ""}
      ${p.field_path ? `${esc(中文名(String(p.field_path).replace(/^config\./, "").split(/[./[]/)[0]))} · ` : ""}${md(p["消息"])}
      <br><span class="k">怎么改:${md(p["建议"])}</span></button>`).join("");
  const 到 = (i) => {
    const p = r["问题"][i]; 图态.问题位 = i;
    if (!p.node_id || !节点(p.node_id)) { 画_问题(); return; }
    图态.选中 = p.node_id; 图态.面板页 = "设置";
    if (图态.画) 图态.画.选 = new Set([p.node_id]);
    画_搭建();
    if (图态.视图 === "流程图" && typeof 画布动作 !== "undefined") 画布动作.选节点([p.node_id]);
  };
  $("#bt").querySelectorAll(".issue").forEach((b) => { b.onclick = () => 到(+b.dataset.i); });
  const n = r["问题"].length;
  $("#is-prev").onclick = () => 到(((图态.问题位 ?? 0) - 1 + n) % n);
  $("#is-next").onclick = () => 到(((图态.问题位 ?? -1) + 1) % n);
}

/* 流程图视图在 wf_canvas.js(和步骤列表改同一份定义;图怎么改走 wf_graph.js)*/

/* ── 测试 ─────────────────────────────────────────────────────── */
function 画_测试(盒 = null) {
  const g = 图态, 侧 = !!盒;   // 侧 = 画在编排页右侧面板里(10-26 第 4 块):单列
  盒 = 盒 || $("#tabbody");
  const 起 = g.定义.nodes.find((n) => n.type === "start");
  const sch = (起 && 起.config.input_schema) || { properties: {}, required: [] };
  const 框 = Object.entries(sch.properties || {}).map(([k, v]) => {
    const 必 = (sch.required || []).includes(k);
    const 标 = `${esc(v.title || k)}${必 ? " <b style='color:#f53f3f'>*</b>" : ""}`;
    const 说 = v.description ? `<div class="k">${esc(v.description)}</div>` : "";
    if (v.type === "boolean") return `<label class="f">${标}</label><select data-in="${esc(k)}" data-t="boolean">
        <option value="">不填</option><option value="true">是</option><option value="false">否</option></select>${说}`;
    if (v.type === "number" || v.type === "integer") return `<label class="f">${标}</label>
        <input type="number" data-in="${esc(k)}" data-t="${v.type}">${说}`;
    if (v.type === "array") return `<label class="f">${标}</label>
        <input data-in="${esc(k)}" data-t="array" placeholder="多项用逗号隔开">${说}`;
    return `<label class="f">${标}</label><textarea rows="2" data-in="${esc(k)}" data-t="string"></textarea>${说}`;
  }).join("");
  // 照 Dify「测试运行」面板(10-27):输入 / 结果 / 详情 / 追踪 四个页签,跑起来自动切页 ——
  // 点「开始运行」→ 结果;跑完(成功 / 失败)→ 详情;停在人工核对 → 结果(那里有「去核对」)
  盒.innerHTML = `<div class="trtabs" role="tablist">${["输入", "结果", "详情", "追踪"].map((t) =>
      `<button role="tab" data-trtab="${t}" aria-selected="false">${t}</button>`).join("")}</div>
    <div data-trpane="输入"><div class="card">
      ${样例条("tr")}
      ${跑法选择("tr")}
      ${定时开头(g) ? '<div class="note">这条流程由<b>定时触发器</b>开头:试运行不等到点,用当前时间模拟一期,统计起 / 统计止由系统填。</div>'
        : (框 || '<div class="k">这条流程不需要使用者提供任何东西。</div>')}
      <div class="note">测试用的是<b>草稿</b>,不是候选版本。模型连接是演示用的那条时不真调模型(结果带 [mock]);
        「由澜绣执行」的步骤会真的去澜绣取数;写跟进这类写入:<b>连接测试</b>只记会写什么、不发给澜绣,<b>正常</b>跑会真的写(写入之前一定先停在人工核对)。</div>
      <div id="tr-err"></div>
      <button class="pri" id="tr-go">开始运行</button></div></div>
    <div data-trpane="结果" hidden><div id="tr-st" class="k">还没跑。点「输入」页的「开始运行」。</div></div>
    <div data-trpane="详情" hidden><div id="tr-det" class="k">还没跑。</div></div>
    <div data-trpane="追踪" hidden><div id="tr-trace" class="k">还没跑。</div></div>`;
  盒.querySelectorAll("[data-trtab]").forEach((b) => { b.onclick = () => 试页(b.dataset.trtab); });
  试页(g.最近测试 ? (g.试页 || "结果") : "输入");
  挂样例条({ 前缀: "tr", node: null,
    填: (v) => document.querySelectorAll("[data-in]").forEach((el) => {
      const x = (v || {})[el.dataset.in];
      el.value = x === undefined || x === null ? "" : Array.isArray(x) ? x.join(",") : typeof x === "object" ? JSON.stringify(x) : String(x);
    }),
    取: () => 读试运行输入(sch).输入 });
  $("#tr-go").onclick = async () => {
    const 选 = 图态.样例选 && 图态.样例选.tr;
    if (选) return 做_试运行({}, 选.参数);       // 看不到原文的样例 / 历史输入:由服务端按 id 填
    const { 输入, 坏 } = 读试运行输入(sch);
    const 缺 = 定时开头(图态) ? [] : (sch.required || []).filter((k) => !(k in 输入));
    if (坏.length || 缺.length) {
      $("#tr-err").innerHTML = `<div class="err" style="padding:6px">${缺.length ? `还没填:${esc(缺.map((k) => (sch.properties[k] || {}).title || k).join("、"))}。` : ""}
        ${坏.length ? `不是数字:${esc(坏.join("、"))}。` : ""}<b>一个模型都没调。</b></div>`;
      return;
    }
    await 做_试运行(输入);
  };
  if (g.最近测试) 盯运行(g.最近测试);
  // 运行固定的是发起时的定义;之后改了图,这份结果就是旧版本的(§10.4 T20)—— 标出来,不覆盖到新图上
  if (g.最近测试 && g.最近测试定义 && g.最近测试定义 !== JSON.stringify(g.定义) && $("#tr-st"))
    document.querySelector(".trtabs").insertAdjacentHTML("afterend", `<div class="note"><b>这是修改前版本的运行结果</b> —— 之后你又改了图;要看当前草稿的效果,再跑一次。</div>`);
}

function 试页(t) {
  if (图态) 图态.试页 = t;
  document.querySelectorAll("[data-trtab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.trtab === t)));
  document.querySelectorAll("[data-trpane]").forEach((x) => { x.hidden = x.dataset.trpane !== t; });
}

async function 盯运行(rid, 自动切 = false) {
  // 轮询到「终态」或「停下来等」为止。等人 / 等澜绣都可能是几分钟到几小时 —— **离开页面不丢**:
  // 运行在服务端,回来点「刷新」或去运行记录都看得到
  for (let i = 0; i < 40; i++) {
    let d;
    try { d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`); } catch (e) { break; }
    if (!$("#tr-st") || (图态 && 图态.最近测试 !== rid)) return;
    $("#tr-st").innerHTML = 运行卡(d, rid);
    if ($("#tr-det")) $("#tr-det").innerHTML = 测试详情(d);
    if ($("#tr-trace")) $("#tr-trace").innerHTML = 测试追踪(d);
    记运行态(d);
    document.querySelectorAll("#tr-rf").forEach((b) => { b.onclick = () => 盯运行(rid); });
    document.querySelectorAll("#tr-trace [data-goto], #tr-st [data-goto]").forEach((b) => { b.onclick = () => 定位步骤(b.dataset.goto); });
    if (d["是终态吗"] || d["在等什么"]) {
      // 自动切页只在「这次是我点的开始运行」时做;回到页面重画时不抢人正在看的页签
      if (自动切) 试页(d["在等什么"] && d["在等什么"]["种类"] === "human" ? "结果" : d["是终态吗"] ? "详情" : "结果");
      return;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}

// 这次试运行每一步的结果(按节点):编排页的列表和图上都标出来(10-26 第 4 块)。只标发起时那份定义里的步骤
const 运行状态中文 = { succeeded: "成功", failed: "失败", waiting_human: "等人工核对", waiting_external: "等澜绣回执",
  running: "进行中", skipped: "跳过", cancelled: "取消", pending: "排队" };
/* 一步的「上次值」:除了值本身,还记它是什么时候采到的、对着哪份图跑的(DF-01 §5.2 第 1 / 2 条)。
 * 还算数 = 服务端拿那次运行对着的逻辑哈希和**现在的草稿**比出来的 —— 前端不自己比,只照着标 */
function 运行态条(d, s) {
  const 调 = d["调试"] || {};
  return { 状态: s["状态"], 默认顶上: ((s["错误细节"] || {})["处理"] === "按默认值继续"), 错误码: s["错误码"], 分支: s["走的分支"], 输入: s["输入"], 输出: s["输出"], 原文: !!d["看得到原文"],
    时间: s["结束于"] || s["开始于"], 运行: d.id, 还算数: 调["还算数"], 说法: 调["说法"] };
}
function 记运行态(d) {
  if (!图态) return;
  图态.上次缓存 = {};   // 有新的运行结果来了,「上次运行」页签的缓存作废(填上次运行 那边的 20 秒缓存)
  const 态 = {};
  (d["步骤"] || []).forEach((s) => { 态[s["节点"]] = 运行态条(d, s); });
  const 等 = d["在等什么"]; if (等 && 等["步骤"]) 态[等["步骤"]] = { 状态: 等["种类"] === "human" ? "waiting_human" : "waiting_external" };
  图态.运行态 = 态;
  if (document.body.classList.contains("wf-full")) { if (图态.视图 === "流程图") { if (typeof 画_节点 === "function") 画_节点(); } else if ($("#steps")) 画_步骤(); }
}
// 运行结果里点一步 → 在列表 / 图上选中并滚到它(试运行面板留着,好对照着看)
function 定位步骤(id) {
  if (!图态 || !节点(id)) return;
  图态.选中 = id;
  if (图态.视图 === "流程图" && typeof 画布动作 !== "undefined") { 画布动作.选节点([id]); }
  else if ($("#steps")) { 画_步骤(); const el = document.querySelector(`.step[data-id="${CSS.escape(id)}"]`); if (el) el.scrollIntoView({ block: "center" }); }
}
function 运行标(id) {
  const x = 图态 && 图态.运行态 && 图态.运行态[id];
  if (x && x.默认顶上) return `<span class="pill" data-run="defaulted" title="这一步出错了,按设置用默认值顶上、流程接着往下走">出错 · 按默认值继续</span>`;
  return x ? `<span class="pill" data-run="${esc(x.状态)}">${esc(运行状态中文[x.状态] || x.状态)}</span>` : "";
}
/* 每一步实际收到的 / 交出的(10-26)。没有「查看敏感输入」授权时接口只给形状(有哪些项、各多长),
 * 这里照实标出来 —— 不标的话,「<str · 1203 字>」会被当成这一步真的输出了这么一串 */
/* 变量唤出(11-15,工作流一期第四件;照 Dify):回复 / 模板框里输 { 或 / 弹出前面步骤的结果,↑↓ 选、回车或点一下插入。
 * 判断「在不在唤出」「插完文本和光标在哪」「名字撞了怎么办」都在 wf_graph.js(图逻辑.变量唤出 / 插入变量 / 变量名),这里只摆弹层。
 * 插入走 改图 命令层:能撤销、标未保存 —— 和别的改动同一条路 */
function 挂变量唤出(n) {
  const 框 = $("#pn") && $("#pn").querySelector("textarea[data-vpick]"), 弹 = $("#vpick-pop");
  if (!框 || !弹 || !能改图()) return;
  let 唤 = null, 选 = 0, 项 = [];
  const 关 = () => { 唤 = null; 弹.hidden = true; 弹.innerHTML = ""; };
  const 画 = () => {
    if (!项.length) { 弹.innerHTML = `<div class="k">前面没有叫「${esc(唤.词)}」的结果${上游字段(n.id).length ? "" : " —— 这一步前面还没有能取值的步骤"}</div>`; 弹.hidden = false; return; }
    弹.innerHTML = 项.map(([v, t], i) => `<div class="vopt${i === 选 ? " on" : ""}" role="option" aria-selected="${i === 选}" data-v="${esc(v)}">${esc(t)}</div>`).join("");
    弹.hidden = false;
    弹.querySelectorAll(".vopt").forEach((el, i) => { el.onmousedown = (ev) => { ev.preventDefault(); 插(i); }; });
  };
  const 插 = (i) => {
    const [v, t] = 项[i] || []; if (!v || !唤) return;
    const 引 = 解引用(v), 字段 = String(t).split(/→|·/).pop().replace(/(仅部分路径有值)/, "").trim();
    const 光 = 框.selectionStart, 唤住 = 唤;
    关();
    改图(`在「${业务名(n)}」里插入变量`, () => {
      const c = n.config; c.bindings = c.bindings || {};
      const 名 = 图逻辑.变量名(字段, c.bindings, 引);
      const r = 图逻辑.插入变量(框.value, 光, 唤住, 名);
      c.template = r.文本; c.bindings[名] = 引;
      setTimeout(() => { const 新 = $("#pn") && $("#pn").querySelector("textarea[data-vpick]"); if (新) { 新.focus(); 新.setSelectionRange(r.光标, r.光标); } }, 0);
    });
  };
  框.addEventListener("input", () => {
    唤 = 图逻辑.变量唤出(框.value, 框.selectionStart);
    if (!唤) return 关();
    const 词 = 唤.词.toLowerCase();
    项 = 上游字段(n.id).filter(([, t]) => !词 || String(t).toLowerCase().includes(词));
    选 = 0; 画();
  });
  框.addEventListener("keydown", (ev) => {
    if (!唤 || 弹.hidden || !项.length) { if (ev.key === "Escape") 关(); return; }
    if (ev.key === "ArrowDown") { ev.preventDefault(); 选 = (选 + 1) % 项.length; 画(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); 选 = (选 - 1 + 项.length) % 项.length; 画(); }
    else if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); 插(选); }
    else if (ev.key === "Escape") { ev.preventDefault(); 关(); }
  });
  框.addEventListener("blur", () => setTimeout(关, 150));
}
/* 「上次运行」页签(11-15,工作流一期第三件;照 Dify 面板的「设置 / 上次运行」):这条流程这一步最近一次真跑到它的记录。
 * 从服务端读,刷新页面也还在;**和运行详情同一权限,原文里的手机号前三后四、固话前三后三**(用户 11-22 拍,打码在服务端做)。
 * 这一页里刚跑完的那次也会写进库,所以不再单独认页内的运行态 —— 两个来源会说不一样的话 */
async function 填上次运行(n) {
  const 盒 = $("#lastrun");
  if (!盒 || !图态 || !图态.wid) return;
  let x;
  // 面板几乎每改一处就重画一次 —— 不缓存的话,打字时每个字都去问一次服务端。
  // 缓存 20 秒,或者这一页又跑了一次(最近测试换了)就作废
  const 缓 = (图态.上次缓存 = 图态.上次缓存 || {}), 键 = `${n.id}|${图态.最近测试 || ""}`, 旧 = 缓[n.id];
  if (旧 && 旧.键 === 键 && Date.now() - 旧.t < 20000) x = 旧.x;
  else {
    try { x = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/nodes/${encodeURIComponent(n.id)}/last-run`); }
    catch (e) { if ($("#lastrun") === 盒) 盒.innerHTML = `<div class="k">读不到上次运行:${esc(e.message || e)}</div>`; return; }
    缓[n.id] = { 键, t: Date.now(), x };
  }
  if ($("#lastrun") !== 盒 || 盒.dataset.nid !== n.id) return;   // 读回来时面板已经换成别的步骤了
  if (!x["有记录"]) { 盒.innerHTML = `<div class="k">${esc(x["说法"] || "这一步还没有跑过")}</div>`; return; }
  const 调 = x["调试"] || {};
  const 态 = x["按默认值继续"] ? `<span class="pill" data-run="defaulted">出错 · 按默认值继续</span>`
    : `<span class="pill" data-run="${esc(x["状态"])}">${esc(运行状态中文[x["状态"]] || x["状态"])}</span>`;
  const 秒 = x["耗时毫秒"] == null ? "" : ` · 用时 ${(x["耗时毫秒"] / 1000).toFixed(1)} 秒`;
  盒.innerHTML = `<div>${态} <span class="k">${esc(x["来源"])}${x["跑法"] && x["跑法"] !== "正常" ? `(${esc(x["跑法"])})` : ""}`
      + ` · ${esc((x["时间"] || "").replace("T", " ").slice(0, 16))}${秒}${x["尝试"] > 1 ? ` · 第 ${x["尝试"]} 次才成` : ""}</span></div>`
    + (调["还算数"] === false ? `<div class="note">跑完之后流程改过了,这是<b>修改前</b>的结果${调["说法"] ? ":" + esc(调["说法"]) : ""}</div>` : "")
    + (x["错误码"] ? `<div class="k">错误:<code>${esc(x["错误码"])}</code>${x["错误细节"] && x["错误细节"]["消息"] ? " · " + esc(x["错误细节"]["消息"]) : ""}</div>` : "")
    + (步骤IO({ 输入: x["输入"], 输出: x["按默认值继续"] && x["错误细节"] ? x["错误细节"]["默认值"] : x["输出"] }, x["看得到原文"], true)
       || `<div class="k">这一步没有记下输入输出(改版前跑的)。</div>`)
    + (x["看得到原文"] ? `<div class="k">手机号只显示后四位${x["打码了几处手机号"] ? `(这次打码了 ${x["打码了几处手机号"]} 处)` : ""};要看完整号码去顾客档案。</div>` : "")
    // 不摆跳转链接:编辑器里没有「打开某次运行」的现成入口,点了没反应比不摆糟 —— 写清在哪找
    + (x["运行"] ? `<div class="k">这次运行的全部步骤:上方「运行记录」页签里找运行编号 <code>${esc(x["运行"])}</code></div>` : "");
}
function 步骤IO(s, 原文, 开 = false) {
  const 有入 = s["输入"] != null, 有出 = s["输出"] != null;
  if (!有入 && !有出) return "";
  const 块 = (标, v) => v == null ? "" : `<div class="k">${标}</div><pre class="io">${esc(JSON.stringify(v, null, 1))}</pre>`;
  const 没存全 = [s["输入"], s["输出"]].some((v) => v && typeof v === "object" && v["__没存全__"]);
  return `<details class="stepio"${开 ? " open" : ""}><summary>看这一步收到 / 交出了什么</summary>
    ${原文 ? "" : `<div class="note">只看得到<b>形状</b>(有哪些项、各多长),看原文要「查看敏感输入」专项授权。</div>`}
    ${没存全 ? `<div class="note">内容太长,只存了前一段。</div>` : ""}
    ${块("收到的(输入)", s["输入"])}${块("交出的(输出)", s["输出"])}</details>`;
}
/* 「直接回复」说了什么(10-27,用户:「要呈现出来,不然测试时候不好看结果」)—— 按执行先后摆成对话气泡。
 * 认 {{名字}} 的写法和后端 dsl.回复占位名 是同一条:`{{` 空白 名字 空白 `}}` */
function 回复占位名(t) {
  return [...new Set([...String(t || "").matchAll(/\{\{\s*([^{}\s]+)\s*\}\}/g)].map((m) => m[1]))];
}
function 回复气泡(d) {
  const 们 = d["回复们"] || [];
  if (!们.length) return "";
  return `<div class="chatbox"><div class="k">直接回复(发回聊天的话,共 ${们.length} 句)</div>`
    + 们.map((x) => `<div class="chatmsg"><div class="chatwho">${esc(图态 && 图态.定义 && 节点(x["节点"]) ? 业务名(节点(x["节点"])) : x["节点"])}</div>
        <div class="chatbub">${x["文本"] != null ? esc(x["文本"]) : `<span class="k">(${esc(x["说明"] || "看不到原文")};共 ${esc(x["长度"])} 字)</span>`}</div>
        ${x["没存全"] ? `<div class="k">回复太长,只存了前一段</div>` : ""}</div>`).join("")
    + `</div>`;
}
/* 业务结果(10-26,方案 §8.2):先说「这次结果能不能用、差什么、下一步干什么」,执行状态退到小字 */
function 业务结果块(d, 带等待 = true) {
  // 等人 / 等澜绣的运行要给出口(11-18):接口的「在等什么」带 待办 / 桥请求,原来运行详情页只写「运行中」,人不知道去哪处理。
  // 画布上的运行卡自己画这一段(带步骤名),传 带等待=false 免得写两遍
  const 等 = (带等待 && d["在等什么"]) || {};
  const 等块 = (等["待办"]
    ? `<div class="k"><a href="#/human/${encodeURIComponent(等["待办"])}">去处理这条待办 →</a>${等["截止"] ? ` <span class="k">截止 ${时间(等["截止"])},到点没人处理这次运行就结束</span>` : ""}</div>` : "")
    + (等["桥请求"]
      ? `<div class="k">等澜绣执行${等["工具"] ? `「${esc(等["工具"])}」` : ""}并回执:桥请求 <a href="#/bridge/${encodeURIComponent(等["桥请求"])}"><code>${esc(等["桥请求"])}</code></a>${等["排于"] ? ` · 排于 ${时间(等["排于"])}` : ""}${等["截止"] ? ` · 截止 ${时间(等["截止"])}` : ""}</div>` : "");
  const r = d["业务结果"]; if (!r) return `<div><b>${esc(d["执行状态中文"])}</b>${等块}</div>`;
  const 色 = { "已完成": "ok", "已完成,需补充资料": "warn", "没做完": "warn", "失败": "err", "进行中": "" }[r["结论"]] || "";
  // 11-18:从人工待办 / 定时页深链进来时没有 图态(没经编辑器),节点() 直接 TypeError 整页崩 —— 42 条失败运行全中。有图才翻业务名
  const 有图 = typeof 图态 !== "undefined" && 图态 && 图态.定义 && Array.isArray(图态.定义.nodes);
  const 步名 = r["哪一步"] ? ((有图 && 节点(r["哪一步"])) ? 业务名(节点(r["哪一步"])) : r["哪一步"]) : "";
  return `<div class="bizres" data-res="${色}">${r["跑法"] === "连接测试" ? '<span class="pill">连接测试</span> ' : ""}<b>${esc(r["结论"])}</b>${步名 ? ` · 卡在「${esc(步名)}」` : ""}
    ${r["说明"] ? `<div>${md(r["说明"])}</div>` : ""}${r["下一步"] ? `<div class="k">下一步:${md(r["下一步"])}</div>` : ""}${等块}
    <div class="k">执行状态:${esc(d["执行状态中文"])}${d["停止原因"] ? ` <code>${esc(d["停止原因"])}</code>` : ""}</div></div>`;
}
function 运行卡(d, rid) {
  const 等 = d["在等什么"];
  const 步 = (d["步骤"] || []).length;      // 每一步的列表在「追踪」页(测试追踪);这里只看有没有开始跑
  return `${业务结果块(d, false)}
    ${回复气泡(d)}
    ${等 ? (等["种类"] === "human"
        ? `<div class="note">停在「${esc(业务名(节点(等["步骤"]) || {}))}」等人工核对。
            ${等["待办"] ? `<a href="#/human/${encodeURIComponent(等["待办"])}">去核对 →</a>` : ""}
            ${等["截止"] ? `<span class="k">截止 ${时间(等["截止"])},到点没人处理这次运行就结束</span>` : ""}</div>`
        : `<div class="note">停在「${esc(业务名(节点(等["步骤"]) || {}))}」等澜绣执行「${esc(等["工具"] || "")}」并回执。
            <span class="k">澜绣的同步程序每 30 秒拉一次;单子排于 ${时间(等["排于"])}。</span></div>`) : ""}
    ${步 ? "" : '<div class="k">排队中 —— 一个模型都还没调</div>'}
    ${d["是终态吗"] && d["输出"] && typeof d["输出"] === "object" ? `<h4>输出</h4>` + Object.entries(d["输出"]).map(([k, v]) =>
        `<div class="k">${esc(k)}</div>` + (typeof v === "string" ? `<div class="card"><div class="body">${md(v)}</div></div>`
          : `<pre class="io">${esc(JSON.stringify(v, null, 1))}</pre>`)).join("")
      : d["是终态吗"] && d["输出"] ? `<pre class="io">${esc(String(d["输出"]))}</pre>` : ""}
    <button id="tr-rf">刷新</button> <a href="#/wfrun/${encodeURIComponent(rid)}">完整详情 →</a>
    <a href="#/wfrun/${encodeURIComponent(rid)}" title="完整详情页上点「原始日志」—— 失败 / 取消的运行一样能看">原始日志 →</a>`;
}

/* 「详情」页(照 Dify):状态 / 运行时间 / 用量 → 输入 → 输出 → 元数据 */
function 测试详情(d) {
  const 时 = (d["事件"] || []).map((e) => e["时间"]).filter(Boolean);
  const 秒 = 时.length > 1 ? ((new Date(时[时.length - 1]) - new Date(时[0])) / 1000).toFixed(1) + " 秒" : "—";
  const 用 = d["用量"] || {};
  const 块 = (标, v) => `<div class="k">${标}</div><pre class="io">${esc(JSON.stringify(v ?? null, null, 1))}</pre>`;
  return `<div class="trmeta"><div><div class="k">状态</div><b>${esc(d["执行状态中文"])}</b></div>
      <div><div class="k">运行时间</div><b>${esc(秒)}</b></div>
      <div><div class="k">用量</div><b>${esc(Object.entries(用).map(([k, v]) => `${k} ${v}`).join(" · ") || "—")}</b></div></div>
    ${d["看得到原文"] ? "" : `<div class="note">只看得到<b>形状</b>,看原文要「查看敏感输入」专项授权。</div>`}
    ${块("输入", d["输入快照"])}${块("输出", d["输出"])}
    <h4>元数据</h4><table><tbody>
      <tr><td class="k">执行人</td><td>${esc(d["请求人"] || "—")}</td></tr>
      <tr><td class="k">跑法</td><td>${esc(d["跑法"] || "正常")}</td></tr>
      <tr><td class="k">开始时间</td><td>${esc(时[0] ? 时间(时[0]) : "—")}</td></tr>
      <tr><td class="k">运行步数</td><td>${(d["步骤"] || []).filter((x) => x["状态"] !== "skipped").length}</td></tr>
      <tr><td class="k">运行号</td><td><a href="#/wfrun/${encodeURIComponent(d.id)}">${esc(d.id)}</a></td></tr></tbody></table>`;
}
/* 「追踪」页(照 Dify):按执行顺序列每一步,点开看这一步收到 / 交出了什么;点名字在图上定位 */
function 测试追踪(d) {
  const 步 = d["步骤"] || [];
  if (!步.length) return `<div class="k">排队中 —— 一个模型都还没调</div>`;
  return `<ul class="trlist">` + 步.map((s) => `<li>${节点(s["节点"]) ? `<button class="lk" data-goto="${esc(s["节点"])}">${esc(业务名(节点(s["节点"])))}</button>`
        : esc(业务名({ type: s["类型"] }))} <span class="pill" data-run="${esc(s["状态"])}">${esc(运行状态中文[s["状态"]] || s["状态"])}</span>
      ${s["走的分支"] && s["走的分支"] !== "None" ? ` <span class="k">→ ${esc(图逻辑.分支名(s["走的分支"]))}</span>` : ""}
      ${s["错误码"] ? ` <code>${esc(s["错误码"])}</code>` : ""}${步骤IO(s, d["看得到原文"])}</li>`).join("") + `</ul>
    <div class="k">「跳过」是这一路没走到,不是失败。<a href="#/wfrun/${encodeURIComponent(d.id)}">完整运行详情 →</a></div>`;
}

/* ── 运行记录 ─────────────────────────────────────────────────── */
async function 画_运行记录(页 = 1) {
  $("#tabbody").innerHTML = `<div class="state">加载中…</div>`;
  try {
    const r = await 请求(`${P()}/execution-runs?workflow_id=${encodeURIComponent(图态.wid)}&page=${页}`);
    $("#tabbody").innerHTML = r.items.length ? `<table><thead><tr><th>状态</th><th>停止原因</th><th>用的哪版</th>
        <th>谁发起</th><th>开始</th><th>结束</th><th></th></tr></thead><tbody>`
      + r.items.map((x) => `<tr><td>${esc(x["执行状态中文"])}</td><td><code>${esc(x["停止原因"] || "")}</code></td>
          <td class="k">${esc(x["版本"] || "")}</td><td>${esc(x["请求人"] || "")}</td>
          <td class="k">${时间(x["开始"])}</td><td class="k">${时间(x["结束"])}</td>
          <td><a href="#/wfrun/${encodeURIComponent(x.id)}">看详情</a></td></tr>`).join("")
      + `</tbody></table>${页码条(r)}<div class="note">这条工作流共跑过 ${r.total} 次。停在「等待审批」「等澜绣回执」的是<b>还没结束</b>,不是失败。</div>`
      : 页 > 1 ? 页码条(r) : 状态("", "还没跑过", "去「测试」页签跑一条。").html;
    挂页码($("#tabbody"), (n) => 画_运行记录(n));
  } catch (e) { const s = 错误块(e, 画_运行记录); $("#tabbody").innerHTML = s.html; s.挂(); }
}

/* ── 版本与发布 ───────────────────────────────────────────────── */
/* 版本与发布(10-26 接上发布,方案 §8.4):上面三个环境各跑哪一版,下面每一版「发到测试 / 预发 / 生产」。
 * 生产只认审核过的清单:没审过点「发到生产」→ 服务端先出好清单再拦,这一行就出现「审核通过 / 驳回」;
 * 有生产审核权的人点了通过,再发。回滚 = 把旧的那一版再发一次生产(记成一次新发布,历史不动)。
 * 聊天接管和定时只跑「生产」指着的那一版。 */
const 环境中文 = { test: "测试", staging: "预发", production: "生产" };
async function 画_版本() {
  const g = 图态, wid = g.wid;
  $("#tabbody").innerHTML = `<div class="state">在取各环境的版本…</div>`;
  let 发;
  try { 发 = await 请求(`${P()}/workflows/${encodeURIComponent(wid)}/releases`); }
  catch (e) { const st = 错误块(e, 画_版本); $("#tabbody").innerHTML = st.html; st.挂(); return; }
  if (!图态 || 图态.wid !== wid || 图态.页签 !== "版本与发布") return;
  const 各环境 = 发["各环境"] || {}, 各版本 = 发["各版本"] || {};
  const 卡 = ["test", "staging", "production"].map((e) => { const x = 各环境[e] || {};
    return `<div class="card envcard"><div class="k">${环境中文[e]}${e === "production" ? " · 聊天接管和定时跑这个" : ""}</div>
      <div class="kpi">${x["版本号"] ? "v" + esc(String(x["版本号"])) : "还没发布"}</div></div>`; }).join("");
  const 行 = g.版本们.map((v) => {
    const 在 = ["test", "staging", "production"].filter((e) => (各环境[e] || {})["版本id"] === v.id);
    const 审 = 各版本[v.id] || null;
    const 生产态 = !审 ? "" : 审["生产能发吗"] ? `<span class="pill ok">生产审核通过</span>`
      : 审["审核"] === "驳回" ? `<span class="pill warn">生产审核被驳回</span>`
      : `<span class="pill warn">等生产审核</span>`;
    const 要审 = 审 && !审["生产能发吗"];
    return `<tr data-vrow="${esc(v.id)}"><td><span class="pill">${esc(v["版本"])}</span>${v["名称"] ? ` <b>${esc(v["名称"])}</b>` : ""}${在.map((e) => ` <span class="pill ok">${环境中文[e]}在跑</span>`).join("")}</td>
      <td data-raw="原文">${esc(v["变更说明"] || "")}</td><td class="k">${时间(v["冻结于"])}<div>${esc(v["冻结人"] || "")}</div></td>
      <td>${生产态}</td>
      <td class="relacts">${!(我的角色 === "approver" ||我的角色 === "admin") ? `<span class="k">发布 / 审核要「生产审核/发布/回滚」这条能力(approver 或 admin),你是 ${esc(我的角色 || "?")}</span>` : `${v.id ? ["test", "staging", "production"].map((e) =>
          `<button data-pub="${esc(v.id)}" data-env="${e}" ${在.includes(e) ? "disabled" : ""}>发到${环境中文[e]}</button>`).join(" ") : ""}
        ${要审 ? `<div class="k">生产要先审核这一版:<button data-rv="${esc(审["清单id"])}" data-ok="1">审核通过</button>
          <button data-rv="${esc(审["清单id"])}" data-ok="0">驳回</button></div>` : ""}`}
        ${v.id ? `<button data-vview="${esc(v.id)}">只读查看</button>
          <button data-vexp="${esc(v.id)}" title="导出这一版成我们自己的 JSON 备份(不含密钥)">导出</button>
          <button data-vname="${esc(v.id)}">${v["名称"] ? "改名字" : "起名字"}</button>
          <button class="danger" data-vdel="${esc(v.id)}" ${在.length ? `disabled title="${esc(在.map((e) => 环境中文[e]).join("、"))}正在跑这一版,不能删"` : ""}>删除</button>` : ""}</td></tr>`;
  }).join("");
  // 当前草稿置顶(10-27 照 Dify 版本历史):它不是一个版本,但人想知道「我现在改的这份」在哪、存没存
  const 草稿行 = `<tr class="draftrow"><td><span class="pill warn">当前草稿</span></td>
      <td class="k">在「搭建」里改的就是它;生成候选版本之后才会出现在下面</td>
      <td class="k">${g.revision != null ? `r${esc(String(g.revision))}` : ""}<div>${esc(g.保存态 || "")}</div></td><td></td>
      <td><a href="#/workflow/${encodeURIComponent(wid)}/${encodeURIComponent("搭建")}">去搭建</a> <button id="vexp-draft" title="导出当前草稿成我们自己的 JSON 备份(不含密钥)">导出草稿</button></td></tr>`;
  $("#tabbody").innerHTML = `<div class="cards">${卡}</div>`
    + (g.版本们.length ? `<table><thead><tr><th>版本</th><th>变更说明</th><th>生成</th><th>生产审核</th><th>发布</th></tr></thead><tbody>${草稿行}${行}</tbody></table>`
      : `<table><tbody>${草稿行}</tbody></table><div class="k">还没生成过候选版本。</div>`)
    + `<div id="vview"></div>
      <div class="note">路径:保存草稿 → 检查配置 → 测试 → <b>生成候选版本</b> → 发到测试 / 预发试用 → <b>审核后发到生产</b>。
        测试、预发直接切;生产只认审核过的那一版。要切回旧版,把旧的那一版再发一次生产(记成一次新的发布,历史不动)。</div>
      <button class="pri" id="pb">生成候选版本</button>
      <div id="schedbox"></div>`;
  $("#pb").onclick = 弹_准备发布;
  画_定时块(wid);
  document.querySelectorAll("[data-vview]").forEach((b) => { b.onclick = () => 看冻结版本(b.dataset.vview); });
  document.querySelectorAll("[data-vexp]").forEach((b) => { b.onclick = () => 弹_导出备份(b.dataset.vexp); });
  if ($("#vexp-draft")) $("#vexp-draft").onclick = () => 弹_导出备份(null);
  document.querySelectorAll("[data-vname]").forEach((b) => { b.onclick = () => 弹_版本起名(b.dataset.vname); });
  document.querySelectorAll("[data-vdel]").forEach((b) => { b.onclick = () => 做_删版本(b.dataset.vdel); });
  document.querySelectorAll("[data-pub]").forEach((b) => { b.onclick = () => 做_发布工作流(b.dataset.pub, b.dataset.env, 各环境); });
  document.querySelectorAll("[data-rv]").forEach((b) => { b.onclick = async () => {
    // 11-08 用户拍:审核通过后这一版就能发到生产
    if (b.dataset.ok === "1" && !(await 问一句("审核通过这一版?", "通过后,有发布权限的人就能把这一版发到生产。", { 确定: "审核通过" }))) return;
    做_审核发布(b.dataset.rv, b.dataset.ok === "1"); }; });
}
/* ── 导出 / 导入整条流程(四期 4-3,11-20 夜;用户 11-15 拍「导出 + 导入都做」)────────────────
 * 我们自己的 JSON,不和 Dify 互导。导出前照 Dify 问一句「不含密钥」;导入只建草稿(新流程)或覆盖当前草稿(先提示「请先导出备份」)。
 * 引用的模型 / 处理要求 / 业务动作 / 资料库 / 连接服务端按名字和版本号在本项目里找;找不到的保留原值,检查配置会标红 */
function 弹_导出备份(vid) {
  const g = 图态, v = vid ? (g.版本们.find((x) => x.id === vid) || {}) : null;
  const 叫 = v ? `${v["版本"]}${v["名称"] ? "(" + v["名称"] + ")" : ""}` : "当前草稿";
  弹层(`导出${esc(叫)}`, `
    <p>会下载一份 JSON:步骤、连线、布局,以及用到的模型 / 处理要求 / 业务动作 / 资料库 / 连接的<b>名字和版本号</b>。</p>
    <p class="k"><b>不含任何密钥 / 凭据值</b>(照 Dify:导出前说清)。导到别的项目时,引用按名字找,找不到的会标红让人重选。</p>
    <div class="acts"><button class="pri" id="ex-ok">导出</button> <button id="ex-no">取消</button></div>`);
  $("#ex-no").onclick = 关弹层;
  $("#ex-ok").onclick = async () => {
    try {
      const 备 = await 请求(`${P()}/workflows/${encodeURIComponent(g.wid)}/export${vid ? "?版本id=" + encodeURIComponent(vid) : ""}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(备, null, 1)], { type: "application/json" }));
      a.download = `工作流备份-${(g.名称 || g.wid).replace(/[\\/:*?"<>|]/g, "_")}-${v ? v["版本"] : "草稿"}.json`; a.click();
      关弹层();
      const 缺 = (备["引用"] || []).filter((r) => r["找不到"]);
      轻提示(`已导出${叫}:${(备["引用"] || []).length} 处引用` + (缺.length ? `,其中 ${缺.length} 处在本项目里已经找不到(导入时会标红)` : ""));
    } catch (e) { 报错(e); }
  };
}
function 弹_导入备份({ 覆盖 = false } = {}) {
  if (覆盖 && !能改图()) return;
  const g = 图态;
  弹层(覆盖 ? "从备份导入,覆盖当前草稿" : "从备份导入成一条新流程", `
    ${覆盖 ? `<div class="note warn"><b>当前草稿将被覆盖,请先导出备份。</b>冻结版本和生产不受影响;覆盖直接落到服务端,不能撤销。</div>` : ""}
    ${覆盖 ? "" : `<label class="f">名称(不填就用备份里的名字加「(导入)」)</label><input id="ib-n" placeholder="例如:门店录音整理(从总部导入)">`}
    <label class="f">备份文件(.json,从「版本与发布」页「导出」拿到的那份)</label><input type="file" id="ib-f" accept=".json,application/json">
    <div class="k">只建草稿,不发布。引用的模型 / 处理要求 / 业务动作 / 资料库 / 连接按名字和版本号在本项目里找;找不到的保留原值并标红,导入后去面板重新选。</div>
    <div id="ib-msg" class="k"></div>
    <div class="acts"><button class="pri" id="ib-ok">${覆盖 ? "覆盖并导入" : "导入"}</button> <button id="ib-no">取消</button></div>`);
  $("#ib-no").onclick = 关弹层;
  $("#ib-ok").onclick = async () => {
    const f = ($("#ib-f").files || [])[0];
    if (!f) { $("#ib-msg").textContent = "先选一个备份文件。"; return; }
    let 备;
    try { 备 = JSON.parse(await f.text()); } catch (e) { $("#ib-msg").textContent = "这个文件不是 JSON:" + e.message; return; }
    try {
      if (覆盖) {
        const r = await 请求(`${P()}/workflows/${encodeURIComponent(g.wid)}/import`, { method: "POST", headers: { "If-Match": String(g.revision) }, body: JSON.stringify({ 备份: 备 }) });
        关弹层();
        图态 = null; await 页_画布(`${g.wid}/搭建`);
        轻提示(`已覆盖导入(r${r.revision})` + 未找到话(r));
      } else {
        const 名 = ($("#ib-n") && $("#ib-n").value.trim()) || "";
        const r = await 请求(`${P()}/workflows/import`, { method: "POST", body: JSON.stringify({ 名称: 名 || undefined, 备份: 备 }) });
        关弹层();
        if ((r["未找到"] || []).length) 提示("导入好了,但有几处引用找不到", md(`**${r["未找到"].length} 处**引用在这个项目里找不到,原值保留着、检查配置会标红:\n` + r["未找到"].map((x) => `- 「${x["节点"]}」的${x["类型"]}:${x["原因"]}`).join("\n") + "\n\n到「搭建」里这几步的面板重新选。"));
        location.hash = `#/workflow/${encodeURIComponent(r.id)}/搭建`;
      }
    } catch (e) { 报错(e); }
  };
}
const 未找到话 = (r) => ((r["未找到"] || []).length ? `;${r["未找到"].length} 处引用找不到,检查配置会标红` : "");
/* 版本命名 / 删除(10-27 照 Dify 版本历史):名字和「删掉了」记在旁表上,冻结版本本身一个字不改 */
function 弹_版本起名(vid) {
  const v = 图态.版本们.find((x) => x.id === vid) || {};
  弹层(`给 ${esc(v["版本"] || "")} 起名字`, `
    <label class="f">名字(最多 40 个字;清空 = 去掉名字)</label>
    <input id="vn-in" value="${esc(v["名称"] || "")}" placeholder="例如:经营报告循环版" maxlength="40">
    <div class="k">只改名字,版本内容不变。变更说明还是生成时写的那句。</div>
    <div class="acts"><button class="pri" id="vn-ok">保存</button> <button id="vn-no">取消</button></div>`);
  $("#vn-no").onclick = 关弹层;
  $("#vn-ok").onclick = async () => {
    const 名 = $("#vn-in").value.trim();
    try {
      const r = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions/${encodeURIComponent(vid)}`, { method: "PATCH",
        headers: { "If-Match": String(v["标记revision"] ?? 0) }, body: JSON.stringify({ 名称: 名 }) });
      v["名称"] = 名 || null; v["标记revision"] = r["标记revision"]; 关弹层(); 轻提示(名 ? `已改名:${名}` : "已去掉名字"); 画_版本();
    } catch (e) { 报错(e); }
  };
}
async function 做_删版本(vid) {
  const v = 图态.版本们.find((x) => x.id === vid) || {};
  if (!(await 问一句(`删掉 ${v["版本"]}${v["名称"] ? "(" + v["名称"] + ")" : ""}?`,
      "删了之后它<b>不再出现在这张表里</b>,也不能再发到任何环境。跑过它的运行、出过的发布清单照样能打开。<b>不能撤销。</b>",
      { 确定: "删掉", 取消: "先不" }))) return;
  try {
    await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions/${encodeURIComponent(vid)}`, { method: "DELETE" });
    图态.版本们 = 图态.版本们.filter((x) => x.id !== vid);
    提示(`已删除 ${v["版本"]}`, "跑过它的运行照样能打开。"); 画_版本();
  } catch (e) { 报错(e); }
}
/* 定时(10-26,方案 §8.5):日 / 周 / 月,默认北京时间 8:00,**只跑生产那一版**,以打开它的人的身份跑。
 * 周报周一早上跑、统计上周一到上周日;关机错过的只补最近一期,更早的列在「最近几期」里,要补就手动发起。 */
/* 11-16 加三种频率(台账第六十八条,照 Dify):每周几(多选)/ 每月几号(多选,可写「末」)/ 每小时;
 * 统计哪一段 = 上一次该跑到这一次该跑之间(第七十三条),服务端算好放在「下次」「接下来」里,这里不再写死「统计上一个自然周」。 */
const 周期说法 = { 日: "每天", 周: "每周几", 月: "每月几号", 时: "每小时" };
const 周几名 = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
/* 定时开头的流程,「开始」交给下一步的只有这两项(定时自己填)—— 和 runtime/validator.py 的 定时自填 同一对 */
const 定时输入表 = () => ({ type: "object", properties: {
  统计起: { type: "string", title: "统计起", description: "这一期从哪天(或哪一刻)起,定时自己填" },
  统计止: { type: "string", title: "统计止", description: "这一期到哪天(或哪一刻)止,定时自己填" } }, required: ["统计起", "统计止"] });
const 只有统计字段 = (sch) => { const ks = Object.keys((sch || {}).properties || {}); return ks.length > 0 && ks.every((k) => k === "统计起" || k === "统计止"); };
const 定时开头 = (g) => { const 起 = g && g.定义 && g.定义.nodes.find((n) => n.type === "start"); return !!(起 && (起.config || {}).start_mode === "定时"); };

/* ── 开始方式三选一(11-20 二期 2-3「开始」页签与多开始,照 Dify)────────────────────
 * 一条流程只有一个「开始」;「多开始」我们做成**换开始方式**:「开始」页签里点一种,有「开始」就把它换成这种、没有就加一个。
 * 触发器和「用户输入」不能同时存在于同一条流程 —— 换的时候提示里说明(照 Dify 的互斥文案)。
 * 换法只写这一份:面板下拉 / 「开始」页签 / 新建空白时的引导弹窗三处都调它。 */
const 开始方式名 = { 用户输入: "用户输入", 定时: "定时触发器", Webhook: "自定义 Webhook" };
// 新建空白流程时服务端在布局里打的标(布局.$开始待配置,和 $注释 / $线 同一个做法:不进定义、不改执行语义):
// 画布上「开始」显示成虚线占位「点击配置开始节点」,进编排页弹一次引导;选了方式就摘掉
const 开始待配置 = () => !!(图态 && 图态.布局 && 图态.布局.$开始待配置 && 图态.定义 && 图态.定义.nodes.some((n) => n.type === "start"));
function 设开始方式(c, 值) {
  c.start_mode = 值;
  if (值 === "定时") { c.schedule_rule = c.schedule_rule || { 周期: "周", 周几: [0], 时刻: "08:00" }; c.input_schema = 定时输入表(); }
  else if (只有统计字段(c.input_schema)) c.input_schema = { type: "object", properties: {}, required: [] };
  if (值 !== "定时") delete c.schedule_rule;
  if (图态 && 图态.布局) delete 图态.布局.$开始待配置;
}
function 选开始方式(值) {
  if (!能改图() || !开始方式名[值]) return false;
  const g = 图态, 起 = g.定义.nodes.find((n) => n.type === "start");
  let id = 起 && 起.id, 提示;
  if (!起) {
    const 做 = 改图(`添加「开始」(${开始方式名[值]})`, () => {
      const n = { id: 图逻辑.新id(g.定义, "start"), type: "start", name: 步类型名.start, config: JSON.parse(JSON.stringify(默认配置("start"))) };
      设开始方式(n.config, 值); g.定义.nodes.push(n); g.布局[n.id] = { x: 40, y: 120 }; id = n.id;
    }, { 重绘: false });
    if (做 === false) return false;
    提示 = `已添加「开始」:${开始方式名[值]}`;
  } else {
    const 原 = (起.config || {}).start_mode || "用户输入", 待配 = 开始待配置();
    if (原 === 值 && !待配) { 轻提示(`「开始」已经是「${开始方式名[值]}」`); return false; }
    const 做 = 改图(`开始方式改成「${开始方式名[值]}」`, () => { 设开始方式(起.config = 起.config || {}, 值); }, { 重绘: false });
    if (做 === false) return false;
    提示 = 待配 ? `「开始」已配置成「${开始方式名[值]}」` + (值 === "用户输入" ? ",在右侧填使用者要提供什么" : "")
              : `触发器和「用户输入」不能同时存在于同一条流程(照 Dify)—— 已把「开始」从「${开始方式名[原]}」换成「${开始方式名[值]}」`;
  }
  g.选中 = id; g.面板页 = "设置";
  if (g.画) g.画.选 = new Set([id]);
  重画全部();
  轻提示(提示, { 撤销: true });
  return true;
}
/* 新建空白流程进编排页弹一次(照 Dify 的「用户输入 / 触发器」二选一);画布上虚线那张占位卡点一下也弹 */
function 弹_配置开始() {
  if (!能改图()) return;
  弹层("这条流程怎么开始?", `
    <p class="k">一条流程只有一个「开始」。有人来点、填好内容再跑,选「用户输入」;要它自己跑,选一种触发器 ——
      触发器和「用户输入」不能同时存在于同一条流程(照 Dify)。以后在「开始」的设置里随时能换。</p>
    ${菜单开始项.map(([值, 名, , , 说, 标]) => `<button type="button" class="tpl" data-startpick="${esc(值)}" style="width:100%;text-align:left">
        <b>${esc(名)}</b>${标 ? ` <span class="pill ok">${esc(标)}</span>` : ""}<div class="k">${esc(说)}</div></button>`).join("")}
    <div class="acts"><button id="sp-later">先不选</button></div>`);
  document.querySelectorAll("[data-startpick]").forEach((b) => { b.onclick = () => { 关弹层(); 选开始方式(b.dataset.startpick); }; });
  $("#sp-later").onclick = 关弹层;
}
/* 切「可视化 / Cron」模式(11-21 规划 2-1):可视化 → Cron 带上服务端算的等价表达式(预览缓存里有;没有就空着让人写);Cron → 可视化回到默认「每周一 08:00」 */
/* 11-21 复审 P1-03:转换**不是无损的就不许静默换** —— 「每月 31 号」转成 Cron 后四月会跳过,原来只弹个轻提示就换了。
 * 服务端 可视化转cron 给说明(非空 = 有损)/ 表达式可能是 null(只有「末」);有损 → 弹层把两边「接下来 5 次」摆出来让人选;
 * Cron 切回可视化会丢表达式、回到默认「每周一 08:00」→ 也要确认。无损(日 / 时 / 周 / 1–28 号)照旧直接换。 */
function 切定时模式(r, 到, { 已确认 = false } = {}) {
  if (到 === "cron" && r.周期 === "cron") return false;
  if (到 !== "cron" && r.周期 !== "cron") return false;
  const 缓 = 图态 && 图态.定时预览 && 图态.定时预览.键 === JSON.stringify(r) ? 图态.定时预览 : null;
  const 有损 = 到 === "cron" ? !!(缓 && (缓.等价Cron说明 || !缓.等价Cron)) : !!(r.表达式 || "").trim();
  if (有损 && !已确认) { 弹_切定时模式(r, 到, 缓); return false; }
  改图(到 === "cron" ? "定时改用 Cron 表达式" : "定时改用可视化", () => {
    for (const k of Object.keys(r)) delete r[k];
    if (到 === "cron") { r.周期 = "cron"; r.表达式 = (缓 && 缓.等价Cron) || ""; }
    else { r.周期 = "周"; r.周几 = [0]; r.时刻 = "08:00"; }
  });
  重画();
  return true;
}
function 弹_切定时模式(r, 到, 缓) {
  const 次 = (xs) => (xs || []).length ? `<ul class="k">${xs.map((x) => `<li>${时间(x["时刻"])}(统计 ${esc(x["统计起"])}${x["统计起"] !== x["统计止"] ? ` ~ ${esc(x["统计止"])}` : ""})</li>`).join("")}</ul>` : `<div class="k">(算不出接下来几次)</div>`;
  if (到 !== "cron") {
    弹层("切回可视化模式?", `<p>现在的 Cron 表达式 <code>${esc(r.表达式 || "")}</code>${缓 && 缓.说法 ? `(${esc(缓.说法)})` : ""} 会丢掉,可视化模式从默认的<b>每周一 08:00</b>重新选。能撤销。</p>
      <div class="acts"><button class="pri" id="sm-ok">切回可视化</button> <button id="sm-no">保留 Cron</button></div>`);
    $("#sm-ok").onclick = () => { 关弹层(); 切定时模式(r, "可视化", { 已确认: true }); };
    $("#sm-no").onclick = 关弹层;
    return;
  }
  const 表 = 缓 && 缓.等价Cron;
  弹层("换成 Cron 表达式会改变跑的时间", `
    <p class="warn">${esc((缓 && 缓.等价Cron说明) || "这条规则 Cron 写不出来")}</p>
    <div class="two"><div class="card"><h4>现在(可视化):${esc((缓 && 缓.说法) || "")}</h4>接下来 5 次:${次(缓 && 缓.接下来)}</div>
      <div class="card"><h4>换成 Cron:${表 ? `<code>${esc(表)}</code>` : "(写不出,留空自己写)"}</h4><div id="sm-cron-next">接下来 5 次:<span class="k">读取中…</span></div></div></div>
    <div class="acts"><button class="pri" id="sm-keep">保留可视化(不换)</button> <button id="sm-ok">${表 ? "接受 Cron 的新语义" : "切到 Cron,表达式自己写"}</button></div>`);
  $("#sm-keep").onclick = 关弹层;
  $("#sm-ok").onclick = () => { 关弹层(); 切定时模式(r, "cron", { 已确认: true }); };
  if (表) {
    请求(`${P()}/schedule-preview?${new URLSearchParams({ 周期: "cron", 表达式: 表 })}`)
      .then((d) => { const el = $("#sm-cron-next"); if (el) el.innerHTML = `接下来 5 次:${次(d["接下来"])}`; })
      .catch((e) => { const el = $("#sm-cron-next"); if (el) el.innerHTML = `<span class="ferr">${esc("算不出:" + e.message)}</span>`; });
  }
}
/* 预览的结果留一份在 图态.定时预览(键 = 规则的 JSON):画布上「开始」卡要同步显示「下次 …」(照 Dify 卡片上的「下次执行时间」),画卡是同步的、不能等接口 */
async function 填定时预览(r) {
  const el = $("#sc-prev"); if (!el) return;
  try {
    const q = new URLSearchParams(r.周期 === "cron" ? { 周期: "cron", 表达式: r.表达式 || "" } : { 周期: r.周期 || "周", 时刻: r.时刻 || "08:00" });
    if (r.周期 === "周") q.set("周几", (r.周几 || [0]).join(","));
    if (r.周期 === "月") q.set("几号", (r.几号 || [1]).join(","));
    const d = await 请求(`${P()}/schedule-preview?${q}`);
    if (图态) {
      图态.定时预览 = { 键: JSON.stringify(r), 说法: d["说法"], 下次: ((d["接下来"] || [])[0] || {})["时刻"] || null, 接下来: d["接下来"] || [], 等价Cron: d["等价Cron"] || "", 等价Cron说明: d["等价Cron说明"] || "" };
      if (typeof 画_节点 === "function" && 图态.画) 画_节点();
    }
    el.innerHTML = `<b>${esc(d["说法"])}</b> · 接下来 5 次(北京时间):${(d["接下来"] || []).map((x) =>
      `${时间(x["时刻"])}(统计 ${esc(x["统计起"])}${x["统计起"] !== x["统计止"] ? ` ~ ${esc(x["统计止"])}` : ""})`).join(" · ")}`;
    // 卡片上要说清「到点会不会真的跑」(规划 2-1 验收:生产没发布过 → 红字「还没发布,到点不跑」)
    const sc = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/schedule`);
    const 态 = !sc["生产版本"] ? `<span class="ferr">还没发布到生产 —— 到点不跑。</span>`
      : sc["生产开始方式"] !== "定时" ? `<span class="ferr">生产那一版还是「用户输入」开头 —— 这一版发布到生产后才会按上面的频率跑。</span>`
      : sc["定时"] && sc["定时"]["开着"] ? `<span class="pill ok">定时开着</span> 下次 ${sc["定时"]["下次"] ? 时间(sc["定时"]["下次"]["时刻"]) : "—"}`
      : `<span class="pill">定时关着</span> 到「版本与发布」页签打开。`;
    el.insertAdjacentHTML("beforeend", `<div>${态}</div>`);
  } catch (e) { el.innerHTML = `<span class="ferr">${esc("这条规则算不出来:" + e.message)}</span>`; }
}
const 读几号 = (文) => 文.split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean).map((x) => (x === "末" || x === "最后一天") ? "末" : Number(x));
const 期结果 = (x) => `${x["结果"] === "已发起" ? `<span class="pill ok">已发起</span>` : `<span class="pill warn">${esc(x["结果"])}</span>`}
  ${esc(x["起"])}${x["止"] !== x["起"] ? " ~ " + esc(x["止"]) : ""}
  ${x["运行"] ? ` · <a href="#/wfrun/${encodeURIComponent(x["运行"])}">看这次运行</a>` : ""}
  ${x["为什么"] ? `<div class="k">${esc(x["为什么"])}</div>` : ""}`;
async function 画_定时块(wid) {
  const el = $("#schedbox"); if (!el) return;
  let d;
  try { d = await 请求(`${P()}/workflows/${encodeURIComponent(wid)}/schedule`); }
  catch (e) { el.innerHTML = `<div class="note">${esc("定时没取到:" + e.message)}</div>`; return; }
  if (!图态 || 图态.wid !== wid || 图态.页签 !== "版本与发布") return;
  const s = d["定时"], 记录 = ((s && s["记录"]) || []).slice(-5).reverse();
  const 是定时 = d["生产开始方式"] === "定时";
  el.innerHTML = `<h2>定时</h2>
    <div class="sub">${md("到点自动跑**生产那一版**,以打开定时的人的身份跑。同一期只跑一次;关机错过的**只补最近一期**,更早的列在下面,要补就手动发起。频率在「开始」节点上定(一条流程要么人点、要么定时),这里只管开 / 关。")}</div>
    ${!d["生产版本"] ? `<div class="note">${md("这条工作流**还没发布到生产**,定时打不开 —— 先在上面把一版审核后发到生产。")}</div>`
      : !是定时 ? `<div class="note">${md("生产这一版是**「用户输入」开头**的,定时打不开。要定时跑:在编排页把「开始」的开始方式改成「定时触发器」,发布到生产后再来打开;两种都要就复制一条流程。")}</div>` : ""}
    <div class="card">
      ${是定时 ? `<div><b>${esc(d["开始节点规则"] || "")}</b> <span class="k">北京时间 · 来自生产版的开始节点</span></div>` : ""}
      <div class="k">${s ? (s["开着"] ? `<span class="pill ok">开着</span> 以 ${esc(s["以谁的身份"])} 的身份跑`
          + (s["下次"] ? ` · 下次 ${时间(s["下次"]["时刻"])},统计 ${esc(s["下次"]["统计起"])} ~ ${esc(s["下次"]["统计止"])}` : "")
          : `<span class="pill">关着</span>`) : "还没打开过定时。"}</div>
      ${s && (s["接下来"] || []).length ? `<div class="k">${s["开着"] ? "接下来 5 次" : "打开的话,接下来 5 次"}(北京时间):${s["接下来"].map((x) =>
          `${时间(x["时刻"])}(统计 ${esc(x["统计起"])}${x["统计起"] !== x["统计止"] ? ` ~ ${esc(x["统计止"])}` : ""})`).join(" · ")}</div>` : ""}
      <button class="pri" id="sc-on" ${d["生产版本"] && 是定时 ? "" : "disabled"}>${s && s["开着"] ? "保存" : "打开定时"}</button>
      ${s && s["开着"] ? `<button id="sc-off">关掉定时</button>` : ""}</div>
    ${记录.length ? `<h3>最近几期</h3><ul class="schedlog">${记录.map((x) => `<li>${期结果(x)}</li>`).join("")}</ul>` : ""}`;
  const 存 = async (开) => {
    if (开 && !(await 问一句(s && s["开着"] ? "保存定时?" : "打开定时?",
        `${esc(d["开始节点规则"] || "")} 自动跑<b>生产那一版</b>,<b>以你的身份</b>发起 —— 每跑一次就按真实用量花一次钱。`,
        { 确定: s && s["开着"] ? "保存" : "打开", 取消: "先不" }))) return;
    try {
      await 请求(`${P()}/workflows/${encodeURIComponent(wid)}/schedule`, { method: "PUT", body: JSON.stringify({ 开着: 开 }) });
      提示(开 ? "定时已保存" : "定时已关掉", 开 ? "到点会自动发起,结果出现在「最近几期」和运行记录里。" : "不会再自动发起。已经发起的运行不受影响。");
    } catch (e) { 报错(e); }
    await 画_定时块(wid);
  };
  $("#sc-on").onclick = () => 存(true);
  if ($("#sc-off")) $("#sc-off").onclick = () => 存(false);
}
/* ── 员工定时(11-22,台账第九十条):员工在聊天站交给助手的定时任务,这里是全项目的管理视角 ──
 * 建 / 改在聊天站「我的定时」;这里看全部、能停(管理员替停要留审计:PATCH status + 代改),默认把「开着但最近失败」的排前面。 */
/* ── 澜绣 AI 治理(11-24,用户拍):8760 的 Skill 管理 / MCP 服务与工具 / 知识问题三页收到这里 ──
 * 页面本体还在 8760(它们读写的是澜绣那边的 skill_registry / mcp_registry / 知识问题表,搬实现 = 两份真相),
 * 这里嵌进来并给同一套导航;登录和 8760 / 8770 是同一个 Cookie(同主机名不分端口)。
 * 8760 侧栏 11-24 起不再列这三页,直链照旧能开。 */
const 澜绣治理页 = {
  skills: ["Skill 管理", "聊天站助手能用哪些技能:开关、依赖、谁能改(只有总部运营)。状态管的是执行闸 —— 关了的技能模型调不到。"],
  mcp: ["MCP 服务与工具", "八个业务领域服务和它们的工具:停用工具、设超时和限流(只能收紧);体检看每个服务活没活。"],
  kbissues: ["知识问题", "门店问了知识库却查不到依据的那些问题:类型 / 维护人 / 处理状态 / 复验。非总部只看自己问的。"],
};
function 页_澜绣治理(哪页) {
  const [名, 说] = 澜绣治理页[哪页];
  // 协议和主机都给默认值:页面冒烟的假浏览器里 location.protocol 是空的,第一版拼成了「undefined//…」被它逮到
  const 地址 = `${location.protocol || "http:"}//${location.hostname || "127.0.0.1"}:8760/#${哪页}`;
  $("#main").innerHTML = `<div class="crumb">澜绣 AI 治理 / ${esc(名)}</div>
    <div class="head"><div><h1>${esc(名)}</h1><div class="sub">${md(说 + " 页面由数据后台(8760)提供、嵌在这里;**没登录会提示去登录**(和聊天站同一个登录)。")}</div></div>
      <div><a class="lk" href="${esc(地址)}" target="_blank" rel="noopener">在新窗口打开</a></div></div>
    <iframe title="${esc(名)}" src="${esc(地址)}" style="width:100%;height:calc(100vh - 180px);border:1px solid var(--line);border-radius:8px;background:#fff"></iframe>`;
}

/* 员工定时「上次失败」的原因(11-24 包二②):接口把最近一次运行的 error_detail 原样给出来({http, 回:{error, 怎么办}}),
 * 这里压成一句人话;解析不了就给原文前 160 字 —— 「失败了」三个字对看的人没有信息量。 */
function 定时失败原因(raw) {
  let d = raw;
  try { if (typeof raw === "string") d = JSON.parse(raw); } catch (e) { return String(raw).slice(0, 160); }
  if (!d || typeof d !== "object") return String(raw).slice(0, 160);
  const 回 = d["回"] || {};
  const 句 = 回.error || 回["错误"] || (typeof 回 === "string" ? 回 : "") || d.error || "";
  const 码 = d.http ? `聊天站回 ${d.http}` : "";
  // 聊天站 11-24 起 error 是人话、detail 才是异常原文 —— 管理后台是排障的人看的,两样都给
  const 细 = 回.detail ? `(${String(回.detail).slice(0, 120)})` : "";
  return [码, String(句).slice(0, 160) + 细, 回["怎么办"] ? `→ ${String(回["怎么办"]).slice(0, 80)}` : ""].filter(Boolean).join(":") || String(raw).slice(0, 160);
}
async function 页_员工定时(页 = 1) {
  const 头 = `<div class="crumb">待办与定时 / 员工定时</div>
    <div class="head"><div><h1>员工定时任务</h1>
      <div class="sub">${md("员工在聊天站里交给助手的定时任务:到点以**他本人的身份、只读工具**让聊天站助手跑一遍(真调模型,进门店月费用),或只提醒。"
        + "这里是全项目视角,能停;建和改在聊天站「我的定时」。连续 3 期失败自动停用。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d, 飞 = null;
  try { d = await 请求(`${P()}/chat-tasks?limit=50&page=${页}`); }
  catch (e) { const s = 错误块(e, 页_员工定时); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  // 飞书送达那块单独拉、单独兜:它挂了不该把任务列表一起带没
  try { 飞 = await 请求(`${P()}/chat-task-feishu?limit=10`); } catch (e) { 飞 = { 出错: e.message || String(e) }; }
  const 飞书块 = 画_飞书送达(飞);
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 飞书块 + 状态("", "还没有员工定时任务", "员工在聊天站顶栏「⏰ 我的定时」里建;建了就会出现在这里。").html;
    return;
  }
  const 排 = [...d.items].sort((a, b) => ((b.status === "启用" && b["上次结果"] === "失败") - (a.status === "启用" && a["上次结果"] === "失败")));
  $("#main").innerHTML = 头 + 飞书块 + `<table><thead><tr>
      <th>谁的</th><th>任务</th><th>频率</th><th>到点</th><th>状态</th><th class="num">成功</th><th>上次 / 下次</th><th></th>
    </tr></thead><tbody>`
    + 排.map((t) => `<tr data-id="${esc(t.id)}" data-rev="${esc(String(t.revision || 0))}">
        <td class="k">${esc(t.staff_code)}${t.store_id ? `<div class="k">${esc(t.store_id)}</div>` : ""}</td>
        <td><b>${esc(t.title)}</b><div class="k">${esc(String(t.instruction || "").slice(0, 100))}</div></td>
        <td class="k">${esc(t["频率说明"] || "")}</td>
        <td>${t.task_mode === "跑" ? "让助手跑" : "只提醒"}</td>
        <td><span class="pill ${t.status === "启用" ? "ok" : ""}">${esc(t.status)}</span>${t["上次结果"] === "失败" ? ` <span class="pill fail">上次失败</span>` : ""}
            ${t["上次结果"] === "失败" && t["上次错误"] ? `<div class="k" title="${esc(String(t["上次错误"]).slice(0, 400))}">原因:${esc(定时失败原因(t["上次错误"]))}</div>` : ""}
            ${t.note ? `<div class="k">${esc(t.note)}</div>` : ""}</td>
        <td class="num">${Number(t["成功次数"] || 0)}</td>
        <td class="k">${t["上次成功"] ? esc(String(t["上次成功"]).slice(5, 16).replace("T", " ")) : "—"}
          <div class="k">${(t["接下来几次"] || [])[0] ? "下次 " + esc(String(t["接下来几次"][0]).slice(5, 16).replace("T", " ")) : ""}</div></td>
        <td><button data-act="toggle">${t.status === "启用" ? "停用" : "启用"}</button> <button data-act="runs">执行记录</button> <span class="k ct-msg"></span></td>
      </tr>`).join("")
    + `</tbody></table>${页码条(d)}<div class="note">${md(d.note || "")}</div>`;
  挂页码($("#main"), (n) => 页_员工定时(n));
  // 执行记录(11-24 包二②的另一半):每一期跑成 / 失败 / 提醒、花了多少、飞书送没送到、失败原因 —— 接口 11-22 就有,页面一直没画
  $("#main").querySelectorAll("tr[data-id] button[data-act=runs]").forEach((b) => b.onclick = async () => {
    const tr = b.closest("tr"), id = tr.dataset.id, 旧 = tr.nextElementSibling;
    if (旧 && 旧.classList.contains("ct-runs")) { 旧.remove(); b.textContent = "执行记录"; return; }
    b.disabled = true; b.textContent = "取记录…";
    let r;
    try { r = await 请求(`${P()}/chat-tasks/${encodeURIComponent(id)}/runs?limit=10`); }
    catch (e) { b.disabled = false; b.textContent = "执行记录"; tr.querySelector(".ct-msg").textContent = `取不到执行记录:${e.message || e}`; return; }
    const 行 = document.createElement("tr"); 行.className = "ct-runs";
    const 时 = (s) => s ? esc(String(s).slice(5, 16).replace("T", " ")) : "—";
    const 飞 = (x) => {
      const d = x.feishu_detail || {};
      if (!d["状态"]) return "—";
      const 为 = d["为什么"] ? ' <span class="k">(' + esc(String(d["为什么"]).slice(0, 60)) + ')</span>' : "";
      return esc(d["状态"]) + 为;
    };
    行.innerHTML = `<td colspan="8">${(r.items || []).length ? `<table><thead><tr><th>期</th><th>到点</th><th>结果</th><th>完成于</th><th class="num">花费</th><th>飞书</th><th>原因 / 回答</th></tr></thead><tbody>`
      + r.items.map((x) => `<tr><td class="k">${esc(x.period_key || "")}</td><td>${x.kind === "跑" ? "让助手跑" : "只提醒"}</td>
          <td><span class="pill ${x.status === "失败" ? "fail" : (x.status === "跑了" || x.status === "提醒") ? "ok" : ""}">${esc(x.status || "")}</span></td>
          <td class="k">${时(x.ended_at || x.created_at)}</td>
          <td class="num">${x.cost_amount != null ? "$" + Number(x.cost_amount).toFixed(4) : "—"}</td>
          <td class="k">${飞(x)}</td>
          <td class="k">${x.status === "失败" ? esc(定时失败原因(x.error_detail)) : esc(String(x.answer_text || "").slice(0, 120))}${x.trace_id ? ` <a href="#/trace/${encodeURIComponent(x.trace_id)}">trace</a>` : ""}</td></tr>`).join("")
      + `</tbody></table>` : `<span class="k">还没有跑过一期 —— 到点才会有记录。</span>`}</td>`;
    tr.after(行); b.disabled = false; b.textContent = "收起记录";
  });
  $("#main").querySelectorAll("tr[data-id] button[data-act=toggle]").forEach((b) => {
    const tr = b.closest("tr"), id = tr.dataset.id, rev = tr.dataset.rev, 说 = tr.querySelector(".ct-msg");
    b.onclick = async () => {
      b.disabled = true;
      try {
        await 请求(`${P()}/chat-tasks/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "If-Match": String(rev) },
          body: JSON.stringify({ status: b.textContent === "停用" ? "停用" : "启用", 代改: "管理后台" }) });
        await 页_员工定时(页);
      } catch (e) { const bb = e.体 || {}; 说.textContent = `${bb.code || "出错"}:${e.message}`; b.disabled = false; }
    };
  });
}

/* 飞书送达(11-23,用户拍「统一用我的飞书,上线后再改每人各自」+「工作台内也要有地方展示」):
 * 页顶一块 —— 接收方配了没、发到谁、最近送达按四态计数、最近几条的结果。四态(已发 / 失败 / 未配置 / 策略不发)
 * 在「飞书没收到」上长得一模一样,所以每条都把 feishu_detail.状态 和 为什么 画出来。 */
function 画_飞书送达(飞) {
  if (!飞) return "";
  if (飞.出错) return `<div class="note">飞书送达状态拿不到:${esc(飞.出错)}</div>`;
  const 按 = 飞["按状态"] || {};
  const 头行 = 飞["配置了"]
    ? `飞书送达:<span class="pill ok">已配置</span> 统一发到 <b>${esc(飞["接收方"] || "")}</b> 的飞书 <span class="k">${esc(飞["备注"] || "")}</span>`
    : `飞书送达:<span class="pill fail">未配置</span> 没有接收方,结果只进站内收件箱 <span class="k">配法:在服务器上写 ${esc(飞["接收方文件"] || "接收方文件")}</span>`;
  const 计 = ["已发", "失败", "未配置", "策略不发"].map((k) => `${k} ${Number(按[k] || 0)}`).join(" · ");
  const 行 = (飞.items || []).map((r) => {
    const dd = r.feishu_detail || {}, s = dd["状态"] || "?";
    return `<tr><td class="k">${esc(String(r.ended_at || r.feishu_at || "").slice(5, 16).replace("T", " "))}</td>
      <td>${esc(r.title || "")}<div class="k">${esc(r.staff_code || "")}</div></td><td>${esc(r.status || "")}</td>
      <td><span class="pill ${s === "已发" ? "ok" : s === "失败" ? "fail" : ""}">${esc(s)}</span>${dd["为什么"] ? `<div class="k">${esc(String(dd["为什么"]).slice(0, 120))}</div>` : ""}</td></tr>`;
  }).join("");
  return `<div class="note ct-feishu"><div>${头行}</div><div class="k">最近送达:${计}</div>`
    + (行 ? `<table><thead><tr><th>时间</th><th>任务</th><th>结果</th><th>飞书</th></tr></thead><tbody>${行}</tbody></table>` : `<div class="k">还没有送达记录</div>`)
    + `</div>`;
}

async function 页_定时() {
  const 头 = `<div class="crumb">待办与定时 / 定时</div>
    <div class="head"><div><h1>定时</h1>
      <div class="sub">${md("哪些工作流会到点自动跑、下次什么时候、统计哪一段、最近一期怎样。**在每条工作流的「版本与发布」里设。**")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/schedules`); }
  catch (e) { const st = 错误块(e, 页_定时); $("#main").innerHTML = 头 + st.html; st.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 状态("", "还没有设过定时的工作流", "打开一条已经发布到生产的工作流,在「版本与发布」页下面设。").html;
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr><th>工作流</th><th>规则</th><th>生产在跑</th><th>下次</th><th>最近一期</th></tr></thead><tbody>`
    + d.items.map((x) => { const 末 = (x["记录"] || []).slice(-1)[0];
      return `<tr><td><a href="#/workflow/${encodeURIComponent(x["工作流"])}/${encodeURIComponent("版本与发布")}">${esc(x["名称"])}</a></td>
        <td>${x["开着"] ? `<span class="pill ok">开着</span>` : `<span class="pill">关着</span>`} ${esc(x["说法"] || `${周期说法[x["周期"]] || x["周期"]} ${x["时刻"]}`)}
          <div class="k">${x["下次"] ? `下次统计 ${esc(x["下次"]["统计起"])} ~ ${esc(x["下次"]["统计止"])}` : "统计上一次到这一次那一段"} · 以 ${esc(x["以谁的身份"])} 的身份</div></td>
        <td>${x["生产版本"] ? "v" + esc(String(x["生产版本"]["版本号"])) : `<span class="pill warn">没发布到生产</span>`}</td>
        <td>${x["下次"] ? `${时间(x["下次"]["时刻"])}<div class="k">统计 ${esc(x["下次"]["统计起"])} ~ ${esc(x["下次"]["统计止"])}</div>` : "—"}</td>
        <td>${末 ? 期结果(末) : `<span class="k">还没到过点</span>`}</td></tr>`; }).join("")
    + `</tbody></table>`;
}
async function 做_发布工作流(vid, 环境, 各环境) {
  const v = 图态.版本们.find((x) => x.id === vid) || {};
  // 生产前先说清这一版是用什么模型跑通的(用户 11-05 拍:演示模型跑通照样放行,但要标明,由点发布的人判断)
  let 模式话 = "";
  if (环境 === "production") {
    try {
      const vv = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions/${encodeURIComponent(vid)}`);
      const 验 = (vv || {})["验证记录"] || {};
      模式话 = 跑通模式话(验["跑通模式"], 验["够发生产"]);
    } catch (e) { 模式话 = "<br>(没取到这一版的验证记录)"; }
  }
  if (环境 === "production" && !(await 问一句(`把 ${v["版本"]} 发到生产?`,
      "发出去之后,<b>聊天接管和定时从这一刻起跑这一版</b>。生产只认审核过、而且对着这一版用真模型跑通过一次的那一版。" + 模式话,
      { 确定: "发到生产", 取消: "先不" }))) return;
  try {
    await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/releases`, { method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ 版本id: vid, 环境, 环境revision: (各环境[环境] || {}).revision ?? undefined }) });
    提示("已发布", `<b>${esc(v["版本"] || "")}</b> 已发到<b>${环境中文[环境]}</b>。${环境 === "production" ? "聊天接管和定时从现在起跑这一版。" : "只影响这个环境,生产不变。"}`);
  } catch (e) {
    const b = e.体 || {};
    if (b.code === "CANNOT_DEPLOY" && 环境 === "production") {
      // 照服务端给的每一条理由摆(没审核 / 没跑通 / 连接没探过 …),不自己猜是哪一条
      const 闸 = ((b.field_errors || {})["闸"] || []);
      提示("还不能发到生产", `${esc(v["版本"] || "这一版")} 没有发到生产,原因:<ul>${闸.map((x) => `<li>${md(x)}</li>`).join("")}</ul>
        ${闸.some((x) => x.includes("审核")) ? "审核入口已经出现在这一行:有生产审核权限的人点「审核通过」后,再点一次「发到生产」。" : ""}`);
    } else 报错(e);
  }
  await 画_版本();
}
async function 做_审核发布(清单id, 通过) {
  const 理由 = 通过 ? "" : await 问一句("驳回这一版", "写一句为什么驳回,发起的人会看到。", { 输入: "比如 测试里写跟进的格式不对", 必填: true, 确定: "驳回" });
  if (!通过 && 理由 === null) return;
  try {
    await 请求(`${P()}/releases/${encodeURIComponent(清单id)}/reviews`, { method: "POST",
      body: JSON.stringify({ 结论: 通过 ? "通过" : "驳回", 理由: 理由 || undefined }) });
  } catch (e) { 报错(e); }
  await 画_版本();
}

/* 冻结版本只读(§10.4 T20):**不可原地编辑**,只给看 + 「复制为草稿」。
 * 复制为草稿 = 一次可撤销的本地编辑(覆盖当前草稿的定义和布局),要保存才落到服务端 —— 不碰那个冻结版本本身 */
/* 这一版的验证记录(DF-01 §5.2-6):只列对着这一版逻辑跑的;对不上的照数说出来,不悄悄扔掉 */
// 用户 11-05 拍:发生产必须用真模型跑通(没有模型步骤的流程跑通就够)。「够不够」由服务端那道闸的同一个函数给,这里只照着说
function 跑通模式话(模式, 够) {
  const m = 模式 || [];
  if (!m.length) return "<br><b>⚠️ 这一版还没有对着它整条跑通过</b> —— 发生产会被拦,先在编排页照这一版试运行一次。";
  if (够 === false) return "<br><b>⚠️ 这一版只用演示模型跑通过</b>(不花钱的假模型)—— <b>发生产会被拦</b>:要用真模型照这一版从头跑通一次。";
  return m.includes("live") ? "<br>这一版用真模型跑通过。" : "<br>这一版跑通过(流程里没有模型步骤,不需要真模型)。";
}
function 验证记录块(x) {
  if (!x) return "";
  const 行 = (x["条目"] || []).map((r) => `<tr><td>${时间(r["时间"])}</td><td>${esc(r["种类"])}${r["步骤"] ? " · " + esc((节点(r["步骤"]) && 业务名(节点(r["步骤"]))) || r["步骤"]) : ""}</td>
      <td>${esc(r["跑法"])} · ${esc(r["模式"] === "mock" ? "演示模型" : "真模型")}</td><td>${esc(运行状态中文[r["状态"]] || r["状态"])}</td>
      <td><a href="#/wfrun/${encodeURIComponent(r["运行"])}">看 →</a></td></tr>`).join("");
  return `<h4>这一版的验证记录</h4>
    <div class="k">${跑通模式话(x["跑通模式"], x["够发生产"]).replace(/^<br>/, "")}</div>
    ${(x["停用的连接"] || []).length ? `<div class="ferr">⚠️ 这一版用到的模型连接 / 业务动作已经停用或归档:${esc(x["停用的连接"].join("、"))} —— 发生产会被拦(发上去每一跑都会失败)。</div>` : ""}
    <div class="k">对着这一版逻辑跑过 <b>${x["对得上"]}</b> 次${x["对不上不算"] ? `;另有 ${x["对不上不算"]} 次是对着别的版本 / 修改前后的图跑的,不算这一版的验证` : ""}(看了最近 ${x["看了最近几次"]} 次)。</div>
    ${行 ? `<table class="t"><thead><tr><th>时间</th><th>测了什么</th><th>跑法</th><th>结果</th><th></th></tr></thead><tbody>${行}</tbody></table>`
      : `<div class="note">还没有对着这一版的测试记录 —— <b>发到生产会被拦</b>:要先照这一版用真模型试运行、从头跑通一次(测试 / 预发不管这一条)。</div>`}`;
}
async function 看冻结版本(vid) {
  const el = $("#vview"); if (!el) return;
  el.innerHTML = `<div class="state">在取…</div>`;
  let v;
  try { v = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions/${encodeURIComponent(vid)}`); }
  catch (e) { el.innerHTML = `<div class="state err"><h3>取不到这个版本</h3><p>${esc(e.message)}</p></div>`; return; }
  const 定 = v["定义"] || { nodes: [], edges: [] }, 布 = v["布局"] || {}, 位 = (id) => 布[id] || { x: 0, y: 0 };
  const W = 176, H = 54;
  const 宽 = Math.max(400, ...定.nodes.map((n) => 位(n.id).x + W + 20)), 高 = Math.max(160, ...定.nodes.map((n) => 位(n.id).y + H + 20));
  const 线 = (定.edges || []).map((e) => { const a = 位(e.source), b = 位(e.target);
    return `<path d="M${a.x + W},${a.y + H / 2} C${a.x + W + 60},${a.y + H / 2} ${b.x - 60},${b.y + H / 2} ${b.x},${b.y + H / 2}" fill="none" stroke="#86909c" stroke-width="1.5"/>`; }).join("");
  const 点 = 定.nodes.map((n) => { const p = 位(n.id);
    return `<g><rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="8" fill="#fff" stroke="#c9cdd4"/>
      <text x="${p.x + 10}" y="${p.y + 22}" font-size="13" font-weight="600">${esc(业务名(n))}</text>
      <text x="${p.x + 10}" y="${p.y + 40}" font-size="11" fill="#86909c">${esc(步类型名[n.type] || n.type)}</text></g>`; }).join("");
  el.innerHTML = `<div class="card"><h3>${esc(v["版本"])} · 只读</h3>
    <div class="k">${esc(v["变更说明"] || "")} · ${时间(v["冻结于"])} · ${esc(v["冻结人"] || "")} · 逻辑哈希 <code>${esc(String(v["逻辑哈希"] || "").slice(0, 19))}…</code></div>
    <div class="note"><b>冻结版本不可原地编辑。</b>要在它的基础上改,点「复制为草稿」—— 会替换当前草稿(可撤销,保存后才落到服务端),这个版本本身不变。</div>
    <div style="overflow:auto;max-height:420px;border:1px solid var(--line);border-radius:6px"><svg width="${宽}" height="${高}">${线}${点}</svg></div>
    ${验证记录块(v["验证记录"])}
    <div class="acts">${能改图() ? `<button class="pri" id="vv-copy">复制为草稿</button>` : `<span class="k">只读:你没有改草稿的权限</span>`}
      <button id="vv-close">收起</button></div></div>`;
  $("#vv-close").onclick = () => { el.innerHTML = ""; };
  if ($("#vv-copy")) $("#vv-copy").onclick = () => {
    弹层(`把 ${v["版本"]} 复制为草稿?`, `<p>当前草稿的定义和布局会被替换成 ${esc(v["版本"])} 的内容。</p>
      ${图态.脏 ? `<p class="ferr">当前草稿还有未保存的修改 —— 替换后可以撤销回来,但建议先保存。</p>` : ""}
      <p class="k">这一步只改本页的草稿,要点「保存草稿」才落到服务端;冻结的 ${esc(v["版本"])} 不受影响。</p>
      <div class="acts"><button class="pri" id="vc-ok">复制为草稿</button> <button id="vc-no">取消</button></div>`);
    $("#vc-no").onclick = 关弹层;
    $("#vc-ok").onclick = () => {
      关弹层();
      改图(`复制 ${v["版本"]} 为草稿`, () => { 图态.定义 = JSON.parse(JSON.stringify(定)); 图态.布局 = JSON.parse(JSON.stringify(布)); 图态.选中 = null; });
      轻提示(`已把 ${v["版本"]} 复制为草稿(未保存)`, { 撤销: true });
    };
  };
}

function 弹_准备发布() {
  const g = 图态;
  const 查 = [
    [!g.脏, "草稿已保存", "有未保存的改动 —— 生成版本前会先保存"],
    [!!(g.报告 && g.报告["通过"]), "配置检查通过", "还没通过 —— 服务端会再查一遍,不通过就生成不了"],
    [g.最近测试状态 === "succeeded", "最近一次测试跑通了", "这次打开页面后还没跑通过一次测试(不拦,但建议先测)"],
  ];
  弹层("生成候选版本", `<ul>${查.map(([ok, 好, 坏]) => `<li>${ok ? "✅ " + esc(好) : "⚠️ " + esc(坏)}</li>`).join("")}</ul>
    <label class="f">这一版改了什么、为什么(必填)</label><textarea id="pb-n" rows="3"></textarea>
    <div class="note">它是以后对比版本时唯一能说清意图的东西 —— 哈希只能说明「变了」。
      生成的是<b>候选版本</b>,线上不会因此改变。</div>
    <div class="acts"><button class="pri" id="pb-ok">生成候选版本</button> <button id="pb-no">取消</button></div>`);
  $("#pb-no").onclick = 关弹层;
  $("#pb-ok").onclick = async () => {
    const 说明 = $("#pb-n").value.trim();
    if (!说明) { $("#pb-n").focus(); return; }
    关弹层(); await 做_冻结(说明);
  };
}

/* ── 设置 ─────────────────────────────────────────────────────── */
function 画_设置() {
  const g = 图态;
  $("#tabbody").innerHTML = `<div class="card" style="max-width:640px">
    <h3>日志采集</h3>
    <div class="k">这条流程的每次运行,管理后台会记下五类原始记录:<b>事件</b>(只追加)、<b>步骤的每一次尝试</b>、
      <b>工具调用</b>(先记意图再记结果)、<b>人工决定</b>(只追加)、<b>澜绣桥请求与回执</b>。
      在「运行记录」→ 某次运行 →「原始日志」里看;看原件要「查看敏感输入」专项授权,没有的看到的是部分打码副本;每次下载都记审计。</div>
    <div class="k">采哪五类是固定的(来源开关、正文策略这一版不做,不摆开关);模型请求与响应原文在运行记录(traces / spans)那一侧、服务商内部过程拿不到。</div>
    <div id="lp-box" class="k">采集策略读取中…</div>
  </div>
  <div class="card" style="max-width:640px">
    <label class="f">名称</label><input id="st-n" value="${esc(g.名称)}">
    <label class="f">用途(一句话:谁用、解决什么)</label><input id="st-p" value="${esc(g.用途 || "")}">
    <label class="f">负责人</label><input id="st-o" value="${esc(g.负责人 || "")}">
    <button class="pri" id="st-ok">保存</button> <span id="st-msg" class="k"></span>
    <h4>聊天里谁来做这件事</h4>
    <label class="f">对应澜绣聊天站的哪个技能</label>
    <select id="st-sk"><option value="">(不对应任何技能)</option>${Object.entries(g.可接管技能 || {}).map(([k, v]) =>
      `<option value="${esc(k)}" ${k === g.对应技能 ? "selected" : ""}>${esc(v)}(${esc(k)})</option>`).join("")}</select>
    <div style="margin:8px 0">${g.聊天接管
      ? '<button class="pri" id="st-tk" data-on="0">工作流接管中 · 关掉(交给 harness)</button>'
      : '<button id="st-tk" data-on="1">现在交给 harness · 打开接管</button>'}</div>
    <div class="k"><b>默认交给 harness</b>:聊天站用技能自己判断怎么做,不受固定步骤束缚。打开接管:聊天站碰到这件事,
      改为发起这条工作流<b>生产环境里的那一版</b>(要先在「版本与发布」里发布到生产),回给用户运行进度和核对入口。同一个技能同时只能被一条工作流接管。</div>
    <h4>什么时候运行</h4><div>手动(在「测试」或接口里发起),或者打开聊天接管后由聊天站发起。<span class="k">定时:频率在「搭建」里开始节点的「定时触发器」上定,开关在「版本与发布」页;到点由 worker 以设定的身份发起生产那一版。</span></div>
    <h4>运行上限</h4><div>每次最多调模型 8 次(发起时带的默认值)。<span class="k">超过就停、记「没完整完成」,不会无限调。</span></div>
    <h4>人工核对的截止</h4><div>每个核对步骤自己设(搭建 → 人工核对 → 设置)。到点没人处理,这次运行结束、记「已过期」。</div></div>`;
  画_日志策略();
  $("#st-tk").onclick = async () => {
    const 开 = $("#st-tk").dataset.on === "1";   // 11-08 用户拍:先确认(线上真客户马上受影响)
    if (!(await 问一句(开 ? "打开聊天接管?" : "关掉聊天接管?", "这一下会改线上聊天站真客户碰到这件事时的走法。", { 确定: 开 ? "打开接管" : "关掉接管" }))) return;
    const r = await 拨接管(g.wid, $("#st-tk").dataset.on === "1", $("#st-sk").value);
    if (r) { Object.assign(g, { 对应技能: r["对应技能"], 聊天接管: r["聊天接管"], 信息rev: r.revision }); 画_画布(); }
  };
  $("#st-ok").onclick = async () => {
    try {
      const d = await 请求(`${P()}/workflows/${encodeURIComponent(g.wid)}`, { method: "PATCH",
        headers: { "If-Match": String(g.信息rev) },
        body: JSON.stringify({ 名称: $("#st-n").value.trim(), 用途: $("#st-p").value.trim() || null,
                               负责人: $("#st-o").value.trim() || null, 对应技能: $("#st-sk").value || null }) });
      Object.assign(g, { 名称: d["名称"], 用途: d["用途"], 负责人: d["负责人"], 信息rev: d["revision"] });
      画_画布();
    } catch (e) { 报错(e); }
  };
}

/* 日志采集策略(11-14,用户拍第四十条「用建议值」30 天 / 5 GB / 80%):整个项目共用一份,存项目设置。
 * 到期清理不可逆 → 默认关;打开前必须先看到「到期会清哪些」,打开时再问一句。 */
function 字节(n) {
  const G = 1024 ** 3, M = 1024 ** 2;
  return n >= G ? (n / G).toFixed(2) + " GB" : n >= M ? (n / M).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
}
async function 画_日志策略() {
  const 盒 = $("#lp-box");
  if (!盒) return;
  let d;
  try { d = await 请求(`${P()}/log-policy`); } catch (e) { 盒.innerHTML = `<span class="ferr">采集策略读不到:${esc(String(e.message || e))}</span>`; return; }
  const 策 = d["策略"], 量 = d["用量"], 期 = d["到期"];
  const 超线 = 量["字节"] >= 量["告警线字节"];
  盒.innerHTML = `<h4>采集策略(整个项目共用)${d["来源"] === "建议值" ? ' <span class="pill">用的是建议值</span>' : ""}</h4>
    <div>已用 <b>${esc(字节(量["字节"]))}</b> / 上限 ${esc(字节(量["上限字节"]))}(${esc(String(量["占比"]))}%)
      ${超线 ? '<span class="pill warn">过了告警线</span>' : ""}</div>
    <div class="k">${Object.entries(量["各来源"]).map(([k, v]) => `${esc(k)} ${esc(String(v["条数"]))} 条 · ${esc(字节(v["字节"]))}`).join(" ｜ ")}</div>
    <label class="f">保留天数(${d["上下限"]["保留天数"].join("–")})</label><input id="lp-d" type="number" value="${esc(String(策["保留天数"]))}">
    <label class="f">每个项目最多(GB,${d["上下限"]["容量上限GB"].join("–")})</label><input id="lp-g" type="number" value="${esc(String(策["容量上限GB"]))}">
    <label class="f">用到多少告警(%)</label><input id="lp-a" type="number" value="${esc(String(Math.round(策["告警比例"] * 100)))}">
    <div style="margin:8px 0"><b>到期会清哪些</b>(早于 ${esc(String(期["截止"]).slice(0, 10))}、正文还在的):
      ${期["合计条数"] ? `${Object.entries(期["各来源"]).filter(([, v]) => v["条数"]).map(([k, v]) => `${esc(k)} ${esc(String(v["条数"]))} 条`).join("、")},共 ${esc(字节(期["合计字节"]))}` : "现在没有到期的"}</div>
    <label><input id="lp-p" type="checkbox" ${策["到期清理"] ? "checked" : ""}> 到期自动清理正文(骨架留着;<b>不可逆</b>)</label>
    <div><button class="pri" id="lp-ok">保存采集策略</button> <span id="lp-msg" class="k"></span></div>
    <div class="note">${esc(d["说明"])}</div>`;
  $("#lp-ok").onclick = async () => {
    const 清 = $("#lp-p").checked;
    if (清 && !策["到期清理"] && !(await 问一句("打开到期清理?",
      `保留期以外的正文会被换成一句「到期已删」,删了找不回。按刚才的保留天数,现在有 ${期["合计条数"]} 条会被清(上面列着)。`, { 确定: "打开到期清理" }))) return;
    try {
      const r = await 请求(`${P()}/log-policy`, { method: "PUT", headers: { "If-Match": String(d.revision) },
        body: JSON.stringify({ 保留天数: Number($("#lp-d").value), 容量上限GB: Number($("#lp-g").value),
                               告警比例: Number($("#lp-a").value) / 100, 到期清理: 清 }) });
      轻提示("采集策略已保存");
      画_日志策略();
      return r;
    } catch (e) { 报错(e); }
  };
}

if (typeof globalThis !== "undefined") globalThis.日志策略 = { 画: 画_日志策略 };   // 给 test_log_policy_page_actions.js 真走一遍

/* 访问 API(11-03,用户拍:一把绑一个应用 / 以发密钥的人的身份 / 先补记账按金额封顶)。
 * ⚠️ 原文**只在发出那一刻**弹一次 —— 列表接口从不返回原文,页面也不缓存它。 */
/* ── 访问密钥的有效期 / 轮换(用户 11-04 拍:发的时候必须选,最长 1 年,默认 90 天;Dify 对标 C05)── */
const 有效期档 = [30, 90, 180, 365];
function 有效期下拉(id) {
  return `<select id="${id}">` + 有效期档.map((d) => `<option value="${d}"${d === 90 ? " selected" : ""}>${d} 天${d === 365 ? "(最长)" : ""}</option>`).join("") + `</select>`;
}
function 到期格(k) {
  if (k["吊销于"]) return "—";
  if (k["过期了吗"]) return '<span class="pill fail">已过期</span>';
  const 剩 = k["还剩几天"];
  return `${esc(String(k["有效期至"] || "").slice(0, 10))}` + (剩 != null && 剩 <= 14 ? ` <span class="pill warn">还剩 ${esc(String(剩))} 天</span>` : "");
}
function 挂轮换(根, 重画) {
  根.querySelectorAll("[data-ak-rotate]").forEach((b) => b.onclick = async () => {
    const 天 = await 问一句("轮换这把密钥", "发一把绑同一个对象、同样上限的新钥;旧的再留 24 小时,让对方换上去。",
      { 输入: "新钥有效期天数(30 / 90 / 180 / 365)", 必填: true });
    if (!天) return;
    try {
      const r = await 请求(`${P()}/access-keys/${encodeURIComponent(b.dataset.akRotate)}/rotate`,
        { method: "POST", headers: { "If-Match": b.dataset.rev }, body: JSON.stringify({ 有效期天数: Number(天) }) });
      提示("新钥发好了 —— 现在就存好", `<div class="note"><b>这是唯一一次看得到新钥原文</b>。旧的还能用到 ${esc(String(r["旧的"]["有效期至"]).slice(0, 16).replace("T", " "))},到点自动拒。</div>
        <pre>${esc(r["新的"]["原文"])}</pre>`);
      重画();
    } catch (e) { 报错(e); }
  });
}

async function 画_访问入口() {
  const g = 图态, wid = encodeURIComponent(g.wid);
  $("#tabbody").innerHTML = `<div class="card"><div class="k">在取…</div></div>`;
  let d;
  try { d = await 请求(`${P()}/workflows/${wid}/access-keys`); }
  catch (e) {
    $("#tabbody").innerHTML = `<div class="card"><div class="note"><b>取不到</b>:${esc(e.message || String(e))}
      —— 这是取数失败,不是「一把密钥都没有」。发密钥要「配置密钥与预算」权限(管理员)。</div></div>`;
    return;
  }
  const 址 = location.origin + (d["调用地址"] || "/open/v1/apps/<应用编号>/runs");
  const 行 = (d["密钥"] || []).map((k) => `<tr><td>${esc(k["名字"])}</td><td><code>${esc(k["开头"])}</code></td>
      <td>${esc(k["发的人"] || "")}</td><td>${k["今天花了"] == null ? "—" : esc(k["今天花了"].toFixed(4))} / ${esc(String(k["每天上限"]))} ${esc(k["币种"])}
        ${k["今天算不出金额的账"] ? `<div class="k">今天有 ${esc(String(k["今天算不出金额的账"]))} 笔算不出金额 —— 这把今天不再受理</div>` : ""}</td>
      <td>${esc((k["最后一次用"] || "从没用过").replace("T", " ").slice(0, 19))}</td><td>${到期格(k)}</td>
      <td>${k["吊销于"] ? `已吊销(${esc(k["吊销人"] || "")})` : k["过期了吗"] ? "已过期 —— 重发一把" : `<button data-ak-lower="${esc(k.id)}" data-rev="${esc(String(k.revision))}">改小上限</button>
        <button data-ak-rotate="${esc(k.id)}" data-rev="${esc(String(k.revision))}">轮换</button>
        <button data-ak-revoke="${esc(k.id)}">吊销</button>`}</td></tr>`).join("");
  const 调 = (d["最近调用"] || []).map((x) => `<tr><td>${esc((x["时间"] || "").replace("T", " ").slice(0, 19))}</td>
      <td>${esc(x["密钥"])}</td><td>${esc(x["接口"])}</td><td>${esc(x["结果"])}(${esc(String(x["码"] || ""))})</td>
      <td>${x["运行"] ? `<a href="#/wfrun/${encodeURIComponent(x["运行"])}">${esc(x["运行"])}</a>` : "—"}</td><td>${esc(x["说明"] || "")}</td></tr>`).join("");
  $("#tabbody").innerHTML = `<div class="card">
    <h3>外部系统怎么调</h3>
    <div class="k">门店小程序、企业微信机器人这类外部系统带一把访问密钥调下面这个地址,跑的是这条流程<b>生产环境里的那一版</b>
      ${d["生产版本号"] ? `(现在是 v${esc(String(d["生产版本号"]))})` : `—— <b>它现在还没有生产版本,调用会被拒</b>,先在「部署」里审核并发布到生产`}。
      以<b>发密钥的那个人</b>的身份跑,他的权限每次都重核;要人核对的步骤照样要人核对。</div>
    <pre>POST ${esc(址)}
请求头:Authorization: Bearer lx-app-……   Idempotency-Key: 这次请求自己生成的编号
请求体:{"输入": { …这条流程开始那一步要的字段… }}
→ 202 {"运行编号": "xr_…", "状态": "排队中", "查结果": "/open/v1/runs/xr_…"}</pre>
    <div class="k">限量:每把每分钟 30 次(<b>查结果也算一次</b>,轮询请隔几秒);每天花费到上限就拒(按价目表算的参考价,美元)。</div>
    <button id="ak-doc">接入文档(按生产那一版的字段生成)</button> <span class="k" id="ak-doc-why"></span>
  </div>
  <div class="card"><h3>Webhook(外部系统推一条就跑)</h3>
    <div class="k">流程「开始」的开始方式选 <b>Webhook</b> 才收。参数照开始里登记的三张表给:请求体 / 网址参数 / 请求头;用同一把访问密钥、同样要带幂等键。</div>
    <pre>正式:POST ${esc(址.replace(/\/runs$/, "/webhook"))}?网址参数=值   ← 跑生产那一版
调试:POST ${esc(址.replace(/\/runs$/, "/webhook/debug"))}?网址参数=值   ← 只跑草稿,改着就能试
请求头:Authorization: Bearer 密钥 · Idempotency-Key: 每条一个 · 登记过的请求头参数: 值
请求体:{"参数名": 值, …}
→ 202 {"运行编号": "xr_…", "状态": "排队中"}(开始里配了「返回给对方什么」就按它回);参数类型不对 / 缺必填 → 422,说明里点名是哪一项</pre>
    <div class="k">对接方看的文档:《澜绣云裳agent-接入Webhook怎么做》(飞书产品文件夹)。</div>
  </div>
  <div class="card"><h3>密钥</h3>
    ${行 ? `<table><tr><th>名字</th><th>开头</th><th>发的人</th><th>今天花了 / 每天上限</th><th>最后一次用</th><th>有效期至</th><th></th></tr>${行}</table>`
         : `<div class="k">还没有发过密钥。</div>`}
    <h4>发一把新的</h4>
    <label class="f">名字(给谁用)</label><input id="ak-n" placeholder="比如:门店小程序">
    <label class="f">每天最多花多少(美元,必填)</label><input id="ak-cap" placeholder="比如 5">
    <label class="f">有效期(必选,最长 1 年)</label>${有效期下拉("ak-exp")}
    <button class="pri" id="ak-new">发密钥</button> <span id="ak-msg" class="k"></span>
    <div class="k">原文只在发出那一刻显示一次,库里只存哈希 —— 忘了就吊销重发。上限只许改小;要更大的额度就吊销重发。</div>
  </div>
  <div class="card"><h3>最近 ${esc(String(d["最近调用只列了"] || 20))} 次调用</h3>
    ${调 ? `<table><tr><th>时间</th><th>密钥</th><th>接口</th><th>结果</th><th>运行</th><th>说明</th></tr>${调}</table>`
         : `<div class="k">还没有调用。</div>`}</div>`;
  $("#ak-new").onclick = 只跑一次(async () => {
    const 名 = $("#ak-n").value.trim(), 上限 = $("#ak-cap").value.trim();
    if (!名 || !上限) { $("#ak-msg").textContent = "名字和每天上限都要填"; return; }
    try {
      const r = await 请求(`${P()}/workflows/${wid}/access-keys`, { method: "POST", body: JSON.stringify({ 名字: 名, 每天上限: Number(上限), 有效期天数: Number($("#ak-exp").value) }) });
      提示("密钥发好了 —— 现在就存好", `<div class="note"><b>这是唯一一次看得到原文</b>,关掉这个框就再也看不到了。</div>
        <pre>${esc(r["原文"])}</pre><div class="k">调用地址:${esc(location.origin + r["调用地址"])}</div>`);
      画_访问入口();
    } catch (e) { 报错(e); }
  });
  $("#tabbody").querySelectorAll("[data-ak-revoke]").forEach((b) => b.onclick = async () => {
    const 理由 = await 问一句("吊销这把密钥", "吊销立刻生效,用它的外部系统下一次调用就会被拒。", { 输入: "理由", 必填: true });
    if (!理由) return;
    try { await 请求(`${P()}/access-keys/${encodeURIComponent(b.dataset.akRevoke)}/revoke`, { method: "POST", body: JSON.stringify({ 理由 }) }); 画_访问入口(); }
    catch (e) { 报错(e); }
  });
  挂轮换($("#tabbody"), 画_访问入口);
  // 接入文档(11-04):**按生产那一版的 schema 现生成**,不手写 —— 手写的会和发布出去的那一版对不上
  $("#ak-doc").onclick = async () => {
    let 文;
    try { 文 = await 请求(`${P()}/workflows/${wid}/access-doc`); } catch (e) { 报错(e); return; }
    if (!文["有文档吗"]) { $("#ak-doc-why").textContent = 文["为什么"] || "还没有生产版本"; return; }
    提示(`接入文档 · 生产 v${文["生产版本号"]}`, `<div class="k">按生产那一版的定义现生成;生产换版本后重新打开这里,字段跟着变。下面是 Markdown 原文,可以整段复制给对接方。</div>
      ${md(文["markdown"])}<h4>Markdown 原文</h4><pre>${esc(文["markdown"])}</pre>`);
  };
  $("#tabbody").querySelectorAll("[data-ak-lower]").forEach((b) => b.onclick = async () => {
    const 新 = await 问一句("改小每天上限", "只许改小;要更大的额度就吊销重发。", { 输入: "新的每天上限(美元)", 必填: true });
    if (!新) return;
    try {
      await 请求(`${P()}/access-keys/${encodeURIComponent(b.dataset.akLower)}`, { method: "PATCH",
        headers: { "If-Match": b.dataset.rev }, body: JSON.stringify({ 每天上限: Number(新) }) });
      画_访问入口();
    } catch (e) { 报错(e); }
  });
}

/* ── 动作:保存 / 检查 / 生成版本 / 试运行 ─────────────────────────── */
/* 保存(§10.2):**请求固定为发起时的快照**。保存中继续改的,成功回来也只确认旧快照,新改动照旧标「未保存」;
 * 不同时发多个互相覆盖的保存请求 —— 正在存时再点,等这一次完了再存下一次。 */
async function 做_存草稿() {
  if (!图态) return false;
  if (图态.存中) {                     // 串行:等手上这一次,然后看还有没有没存的
    const r = await 图态.存中;
    if (!r) return false;
    return 图态.脏 ? 做_存草稿() : true;
  }
  const 发 = (async () => {
    const g = 图态, 体 = JSON.stringify({ 定义: g.定义, 布局: g.布局 }), 序 = g.编辑序号 || 0;
    g.保存态 = "保存中"; g.保存中序号 = 序; 画_保存状态();
    try {
      const d = await 请求(`${P()}/workflows/${encodeURIComponent(g.wid)}/draft`, {
        method: "PATCH", headers: { "If-Match": String(g.revision) }, body: 体,
      });
      g.revision = d.revision; g.已存序号 = 序; g.存于 = new Date();
      g.已存快照 = 体;
      g.脏 = (g.编辑序号 || 0) !== 序;        // 保存期间又改过 → 那些改动还没存
      g.保存态 = g.脏 ? "未保存" : "已保存";
      // 不整页重画:正在输入的框、输入法组合、焦点都留着(§8.3 T12/T13)
      画_保存状态(); 画_底栏(); 画_问题();
      return true;
    } catch (e) {
      // **没存上就返回 false,调用方必须停下** —— 检查 / 生成版本 / 试运行都是对着服务端那份草稿做的,
      // 存失败了还往下走,页面上是新图,实际冻结、试跑的是旧稿,而界面看不出来。
      // 冲突时也不自动刷新:刷新会把这一页没存上的改动扔掉,让人自己决定(§10.3)。
      if (e.码 === 409) { g.保存态 = "冲突"; 画_保存状态(); 弹_冲突(e); return false; }
      g.保存态 = "失败"; 画_保存状态();
      报错(e);
      return false;
    } finally {
      g.存中 = null;
    }
  })();
  图态.存中 = 发;
  return 发;
}

/* 409:其他人已更新。**不提供强制覆盖**(没有明确权限和服务端支持)—— 查看差异 / 保留本地副本 / 重新载入 */
function 弹_冲突(e) {
  const g = 图态;
  弹层("其他人已更新这张图", `<p>${esc(e.message)}</p>
    <p><b>你的修改仍在本页</b>,没有被覆盖,也没有被丢掉。</p>
    <div id="cf-diff" class="k"></div>
    <div class="acts"><button id="cf-diff-b">查看差异</button> <button id="cf-keep">保留本地副本(下载)</button>
      <button id="cf-reload" class="danger">重新载入(放弃本页修改)</button> <button id="cf-no">先留在这页</button></div>`);
  $("#cf-no").onclick = 关弹层;
  $("#cf-diff-b").onclick = async () => {
    try {
      const d = await 请求(`${P()}/workflows/${encodeURIComponent(g.wid)}`);
      const x = 图逻辑.差异(g.定义, d["草稿"]["定义"] || { nodes: [], edges: [] });
      const 列 = (t, a) => a.length ? `<div>${t}:${a.map(esc).join("、")}</div>` : "";
      $("#cf-diff").innerHTML = `对方现在是 r${esc(String(d["草稿"]["revision"]))}。`
        + 列("只在你这页的步骤", x.只在本地的步骤) + 列("只在对方那份的步骤", x.只在对方的步骤)
        + 列("两边都改了的步骤", x.两边都改了的步骤) + 列("只在你这页的连线", x.只在本地的线) + 列("只在对方那份的连线", x.只在对方的线)
        || "两份的步骤和连线一样(可能只差布局或名称)。";
    } catch (er) { $("#cf-diff").textContent = "读不到对方那份:" + er.message; }
  };
  $("#cf-keep").onclick = () => {
    const 文 = JSON.stringify({ 工作流: g.wid, 基于草稿: g.revision, 定义: g.定义, 布局: g.布局 }, null, 1);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([文], { type: "application/json" }));
    a.download = `工作流-${g.wid}-本地副本.json`; a.click();
    $("#cf-diff").textContent = "已下载本地副本。重新载入后可以对照着把改动补回去。";
  };
  $("#cf-reload").onclick = async () => {
    if (!(await 问一句("重新载入?", "会丢掉这一页没存上的修改(已下载的本地副本不受影响)。", { 确定: "重新载入", 取消: "先不" }))) return;
    关弹层(); 图态 = null; await 页_画布(`${g.wid}/${g.页签}`);
  };
}

/* 自动保存(第三批,§10.2「未来自动保存」):只存草稿,停顿 1.5 秒后串行提交;
 * 不运行、不发布、不改生效版本。保存失败 / 冲突时停下,不重试刷屏。
 * 10-27 起**默认开**(用户拍「照 Dify 编辑即保存,两人同时改仍提示冲突」);个人仍可关,关了记在本机。
 * 冲突照旧:两个人改同一张图,后存的那个拿到「其他人已更新」,不悄悄盖掉别人的 */
let _自存时 = 0;
function 自动保存开着() { try { return localStorage.getItem("wf.自动保存") !== "0"; } catch (e) { return true; } }
function 自动保存排队() {
  clearTimeout(_自存时);
  if (!自动保存开着() || !图态 || ["冲突", "失败"].includes(图态.保存态) || !能改图()) return;
  _自存时 = setTimeout(() => { if (图态 && 图态.脏) 做_存草稿(); }, 1500);
}

/* 离开(W30):站内切走时 保存并离开 / 留在此页 / 放弃本地修改;保存失败留在原页。关浏览器用原生提示 */
let _上个地址 = location.hash, _放行一次 = false;
function 离开拦截() {
  const 到 = location.hash;
  if (_放行一次) { _放行一次 = false; _上个地址 = 到; return false; }
  // 11-08 UI 检查:原来只拦工作流画布;智能体 / 聊天助手编辑页有「脏」标记却不拦,一离开改动全丢
  for (const [态, 前缀, 名] of [[agent态, "#/agent/", "智能体"], [聊态, "#/chat/", "聊天助手"]]) {
    if (!态 || !态.脏) continue;
    const 页 = 前缀 + encodeURIComponent(态.aid || 态.cid);
    if (到 === 页 || 到.startsWith(页 + "/") || decodeURIComponent(到) === 前缀 + (态.aid || 态.cid)) continue;
    const 回 = _上个地址;
    _放行一次 = true; location.hash = 回;
    弹层("有未保存的修改", `<p>这个${名}有还没保存的修改,离开就丢了。</p>
      <div class="acts"><button class="pri" id="lv-stay">留在此页</button> <button class="danger" id="lv-drop">放弃修改并离开</button></div>`);
    $("#lv-stay").onclick = 关弹层;
    $("#lv-drop").onclick = () => { 关弹层(); 态.脏 = false; location.hash = 到; };
    return true;
  }
  const g = 图态, 本页 = g ? `#/workflow/${encodeURIComponent(g.wid)}` : null;
  const 还在本条 = 本页 && (到 === 本页 || 到.startsWith(本页 + "/") || decodeURIComponent(到).startsWith(`#/workflow/${g.wid}/`));
  if (!g || !g.脏 || 还在本条) { _上个地址 = 到; return false; }
  const 回 = _上个地址;
  _放行一次 = true; location.hash = 回;           // 先回到原页,等人选
  弹层("有未保存的修改", `<p>这张图有还没保存的修改。</p>
    <div class="acts"><button class="pri" id="lv-save">保存并离开</button> <button id="lv-stay">留在此页</button>
      <button class="danger" id="lv-drop">放弃本地修改</button></div>`);
  $("#lv-stay").onclick = 关弹层;
  $("#lv-save").onclick = async () => { 关弹层(); if (await 做_存草稿()) { _放行一次 = true; location.hash = 到; } };
  $("#lv-drop").onclick = () => { 关弹层(); 图态 = null; location.hash = 到; };
  return true;
}
window.addEventListener("beforeunload", (e) => { if (图态 && 图态.脏) { e.preventDefault(); e.returnValue = ""; } });
/* Ctrl/Cmd+S:先让正在输入的框提交(失焦触发 change),再保存;非法输入会留在框里并标出来 */
window.addEventListener("keydown", (e) => {
  if (!图态 || !location.hash.startsWith("#/workflow/")) return;
  if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
    e.preventDefault();
    if (e.isComposing) return;
    const a = document.activeElement; if (a && /INPUT|TEXTAREA|SELECT/.test(a.tagName)) a.blur();
    setTimeout(() => 做_存草稿(), 0);
  }
});

// 测试入口(tests/e2e/test_workflow_save_gate.js):**存失败之后,后面三个动作都不许发请求**
const 编排动作 = {
  设图态: (s) => { 图态 = s; },
  存草稿: () => 做_存草稿(), 校验: () => 做_校验(), 冻结: (说明) => 做_冻结(说明), 试运行: (输入) => 做_试运行(输入),
};
if (typeof globalThis !== "undefined") globalThis.编排动作 = 编排动作;

async function 做_校验() {
  if (图态.脏 && !(await 做_存草稿())) return;
  try {
    const 定 = JSON.stringify(图态.定义), rev = 图态.revision;
    图态.报告 = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/validate`, { method: "POST" });
    图态.报告定义 = 定; 图态.报告rev = rev; 图态.报告时 = new Date().toISOString(); 图态.问题位 = null;
    图态.问题开 = !图态.报告["通过"];
    if (图态.页签 !== "搭建") { location.hash = `#/workflow/${encodeURIComponent(图态.wid)}/搭建`; return; }
    画_画布();
  } catch (e) { 报错(e); }
}

async function 做_冻结(说明) {
  if (!说明) return;
  if (图态.脏 && !(await 做_存草稿())) return;
  try {
    const d = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions`,
      { method: "POST", body: JSON.stringify({ 变更说明: 说明 }) });
    图态.版本们 = [{ id: d.id, 版本: d["版本"], 逻辑哈希: d["逻辑哈希"].slice(0, 19) + "…", 变更说明: 说明,
                    冻结于: new Date().toISOString(), 冻结人: "你" }, ...图态.版本们];
    location.hash = `#/workflow/${encodeURIComponent(图态.wid)}/版本与发布`;
    画_画布();
    提示("候选版本已生成", `<b>${esc(d["版本"])}</b> 已生成,<b>还没上线</b> —— 在「版本与发布」里选环境发布;生产要先审核。`);
  } catch (e) {
    报错(e);
    if ((e.体 || {}).code === "VALIDATION") return 做_校验();
  }
}

function 读试运行输入(sch) {
  const 输入 = {}, 坏 = [];
  document.querySelectorAll("[data-in]").forEach((el) => {
    const k = el.dataset.in, t = el.dataset.t, v = el.value.trim();
    if (!v) return;
    if (t === "number" || t === "integer") { const x = Number(v); if (!Number.isFinite(x)) 坏.push(k); else 输入[k] = t === "integer" ? Math.trunc(x) : x; }
    else if (t === "boolean") 输入[k] = v === "true";
    else if (t === "array") 输入[k] = v.split(/[,,]/).map((x) => x.trim()).filter(Boolean);
    else 输入[k] = v;
  });
  return { 输入, 坏 };
}
async function 做_试运行(输入 = {}, 额外 = {}) {
  if (图态.脏 && !(await 做_存草稿())) return;
  try {
    const d = await 请求(`${P()}/execution-runs`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ workflow_id: 图态.wid, 输入, 跑法: 选的跑法("tr"), ...额外 }),
    });
    图态.最近测试 = d.resource_id;
    图态.最近测试定义 = JSON.stringify(图态.定义);     // 这次试运行固定的是哪份定义(§10.4)
    if ($("#tr-err")) $("#tr-err").innerHTML = "";
    if ($("#tr-st")) $("#tr-st").innerHTML = `已受理 —— <b>排队中,一个模型都还没调</b>。`;
    试页("结果");
    await 盯运行(d.resource_id, true);
    try {
      const r = await 请求(`${P()}/execution-runs/${encodeURIComponent(d.resource_id)}`);
      图态.最近测试状态 = r["执行状态"];
    } catch (e) { /* 拉不到不影响测试页已经显示的状态 */ }
  } catch (e) {
    报错(e);
    if ((e.体 || {}).code === "VALIDATION") return 做_校验();
  }
}


/* ── 变量检查(10-27,照 Dify 画布底部那个抽屉)─────────────────────────────
 * 左:上次试运行里每一步交出的结果(「使用者输入」= 开始那一步);右:选中那一步的值,**可以直接改**。
 * 改过的值**只留在这一页**:不存服务端、不进运行记录;下一次「试这一步」会先用改过的值填输入框
 * (这就是 Dify「改了变量再单步运行」那件事)。「还原至上一次运行」/「重置所有」撤掉修改。
 * 没有「查看敏感输入」授权时上次的值只有形状 —— 只读,照实写为什么。 */
function 变量值(nid) {
  const 改 = (图态.变量改 || {})[nid];
  if (改 !== undefined) return { 值: 改, 改过: true };
  const 跑 = 图态.运行态 && 图态.运行态[nid];
  return 跑 && 跑.输出 != null ? { 值: 跑.输出, 原文: 跑.原文 } : null;
}
function 取指针值(v, ptr) {
  let 当前 = v;
  for (const 段 of String(ptr || "").replace(/^\//, "").split("/").filter(Boolean)) {
    if (当前 && typeof 当前 === "object" && 段 in 当前) 当前 = 当前[段]; else return undefined;
  }
  return 当前;
}
function 画_变量检查() {
  const 盒 = $("#vi"), 钮 = $("#vi-tg"); if (!盒 || !钮) return;
  const g = 图态, 开 = !!g.变量开;
  钮.setAttribute("aria-expanded", String(开)); 钮.hidden = 开; 盒.hidden = !开;
  if (!开) return;
  const 有 = g.定义.nodes.filter((n) => 变量值(n.id));
  if (!g.变量选 || !变量值(g.变量选)) g.变量选 = 有[0] ? 有[0].id : null;
  const 名 = (n) => n.type === "start" ? "使用者输入" : 业务名(n);
  const 左 = 有.length ? 有.map((n) => `${n.id === g.变量选 ? `<button class="lk on" data-vi="${esc(n.id)}">` : `<button class="lk" data-vi="${esc(n.id)}">`}${esc(名(n))}${
      (g.变量改 || {})[n.id] !== undefined ? ' <span class="pill warn">已编辑</span>'
        : ((g.运行态 || {})[n.id] || {}).还算数 === false ? ' <span class="pill fail" title="跑完之后流程改过了">修改前的</span>' : ""}</button>`).join("")
    : `<div class="k">在画布上试运行或单独测一步之后,这里能看到每一步交出的结果。</div>`;
  let 右 = "";
  const 选 = g.变量选 && 节点(g.变量选), x = 选 && 变量值(选.id);
  if (x) {
    const 原文 = x.改过 || x.原文;
    右 = `<div class="vihead"><b>${esc(名(选))}</b> <span class="k">${esc(Array.isArray(x.值) ? "列表" : typeof x.值 === "object" ? "对象" : typeof x.值)}</span>
        ${x.改过 ? `<span class="pill warn">已编辑</span> <button id="vi-back">还原至上一次运行</button>` : ""}
        <button id="vi-exp" title="导出变量为文件">导出</button></div>
      ${原文 ? `<textarea id="vi-val" rows="8" spellcheck="false">${esc(JSON.stringify(x.值, null, 1))}</textarea>
          <div class="k">直接改,点框外生效。改过的值只用在这一页的调试里(下一次「试这一步」会先用它填),不存、不进运行记录。</div><div id="vi-err" class="ferr"></div>`
        : `<pre class="io">${esc(JSON.stringify(x.值, null, 1))}</pre>
          <div class="note">只看得到<b>形状</b>(有哪些项、各多长)—— 看原文、改值要「查看敏感输入」专项授权。</div>`}`;
  }
  盒.innerHTML = `<div class="vihd"><b>变量检查</b> ${Object.keys(g.变量改 || {}).length ? '<button id="vi-reset">重置所有</button>' : ""}
      <button id="vi-x" aria-label="关闭变量检查">×</button></div>
    <div class="vibody"><div class="vileft">${左}</div><div class="viright">${右 || '<div class="k">在左边选一步。</div>'}</div></div>`;
  $("#vi-x").onclick = () => { g.变量开 = false; 画_变量检查(); };
  盒.querySelectorAll("[data-vi]").forEach((b) => { b.onclick = () => { g.变量选 = b.dataset.vi; 画_变量检查(); }; });
  const 重置 = $("#vi-reset"); if (重置) 重置.onclick = () => { g.变量改 = {}; 画_变量检查(); 轻提示("已撤掉所有修改,回到上一次运行的值"); };
  const 回 = $("#vi-back"); if (回) 回.onclick = () => { delete g.变量改[选.id]; 画_变量检查(); };
  const 出 = $("#vi-exp");
  if (出) 出.onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(x.值, null, 1)], { type: "application/json" }));
    a.download = `${名(选)}.json`; a.click(); URL.revokeObjectURL(a.href);
  };
  const 框 = $("#vi-val");
  if (框) 框.onchange = () => {
    try { (g.变量改 = g.变量改 || {})[选.id] = JSON.parse(框.value); 画_变量检查(); if (g.选中) 画_面板(); }
    catch (e) { $("#vi-err").textContent = "不是合法的 JSON(文字要带引号)—— 没改,框里留着你写的"; }
  };
}

/* ── 单步测试(10-26,方案 §8.1):只跑选中的这一步,不从头跑整条流程 ──────────────
 * 服务端拼「开始 → 这一步 → 结束」小图、走试运行同一个受理口;哪些能测、写入类为什么不行,
 * 以服务端为准(runtime/单步测试.py)。这里只是**不摆点了没用的按钮**:明知会被拒的类型直接说为什么 */
/* ── 测试样例与历史输入(10-26,方案 §8.1)───────────────────────────────
 * 一条栏两处用:试运行(整条流程,node 为空)和「试这一步」(node = 那一步)。
 * 选中时:看得到原文 → 直接填进输入框,可以改了再跑;看不到 → 输入框留空,
 * 记下「用哪条」,跑的时候只发 id、由服务端填 —— 原文不经过这个浏览器,但照样能用 */
function 样例条(前缀) {
  return `<div class="smpbar" id="${前缀}-smp"><select id="${前缀}-smpsel" aria-label="选一条样例或最近的输入"><option value="">加载样例…</option></select>
    <button id="${前缀}-smpdel" hidden>删掉这条样例</button>
    <span class="smpsave"><input id="${前缀}-smpname" placeholder="给这次填的起个名字" maxlength="60"><button id="${前缀}-smpsave">存为样例</button></span>
    <div id="${前缀}-smpmsg" class="k"></div></div>`;
}
async function 挂样例条({ 前缀, node, 填, 取 }) {
  const sel = $(`#${前缀}-smpsel`); if (!sel) return;
  const 话 = (h) => { const m = $(`#${前缀}-smpmsg`); if (m) m.innerHTML = h; };
  图态.样例选 = 图态.样例选 || {};
  图态.样例选[前缀] = null;
  const q = node ? `?node_id=${encodeURIComponent(node)}` : "";
  const 基 = `${P()}/workflows/${encodeURIComponent(图态.wid)}`;
  let 样, 近;
  try { [样, 近] = await Promise.all([请求(`${基}/test-samples${q}`), 请求(`${基}/recent-inputs${q}`)]); }
  catch (e) { sel.innerHTML = `<option value="">样例加载不了</option>`; return; }
  if (!$(`#${前缀}-smpsel`)) return;                    // 等的时候面板已经换了
  const 表 = {};
  (样.items || []).forEach((x) => { 表["s:" + x.id] = { 名: x["名称"], 内容: x["内容"], 参数: { 样例id: x.id }, 样例: x.id }; });
  (近.items || []).filter((x) => !x["没存全"]).forEach((x) => {
    表["r:" + x["运行"]] = { 名: `${时间(x["时间"])} 那次(${运行状态中文[x["状态"]] || x["状态"]})`, 内容: x["内容"], 参数: { 沿用运行: x["运行"] }, 运行: x["运行"] }; });
  const 原文 = !!样["看得到原文"];
  const 组 = (k, 标) => { const ks = Object.keys(表).filter((x) => x.startsWith(k)); return ks.length
    ? `<optgroup label="${标}">${ks.map((x) => `<option value="${esc(x)}">${esc(表[x].名)}</option>`).join("")}</optgroup>` : ""; };
  sel.innerHTML = `<option value="">${Object.keys(表).length ? "选一条样例或最近的输入…" : "还没有样例,也还没跑过"}</option>`
    + 组("s:", "存过的样例") + 组("r:", "最近运行收到的");
  sel.onchange = () => {
    const x = 表[sel.value]; const 删 = $(`#${前缀}-smpdel`);
    图态.样例选[前缀] = null; if (删) 删.hidden = !(x && x.样例);
    if (!x) { 话(""); return; }
    if (原文) { 填(x.内容); 话(`已填上「${esc(x.名)}」,可以改了再跑。`); return; }
    填({}); 图态.样例选[前缀] = x;
    话(`已选「${esc(x.名)}」。你没有「查看敏感输入」授权,看不到原文 —— <b>跑的时候由服务端把内容填进去</b>,照样能用。改选「选一条…」就回到手填。`);
  };
  const 删 = $(`#${前缀}-smpdel`);
  if (删) 删.onclick = async () => {
    const x = 表[sel.value]; if (!x || !x.样例) return;
    if (!(await 问一句("删掉这条样例?", `「${esc(x.名)}」是团队共用的测试样例,删掉后<b>恢复不了</b>。`, { 确定: "删掉" }))) return;   // 11-08 用户拍
    try { await 请求(`${基}/test-samples/${encodeURIComponent(x.样例)}`, { method: "DELETE" }); 话(`已删掉「${esc(x.名)}」。`); 挂样例条({ 前缀, node, 填, 取 }); }
    catch (e) { 报错(e); }
  };
  const 存 = $(`#${前缀}-smpsave`);
  if (存) 存.onclick = async () => {
    const 名 = ($(`#${前缀}-smpname`).value || "").trim();
    if (!名) { 话("先给这条样例起个名字。"); return; }
    const 选 = 图态.样例选[前缀];
    // 看不到原文时选的是「最近运行收到的」:服务端从那次运行原样拷,不经过浏览器
    const 体 = 选 && 选.运行 ? { 名称: 名, node_id: node, 来自运行: 选.运行 } : { 名称: 名, node_id: node, 输入: 取() };
    try { await 请求(`${基}/test-samples`, { method: "POST", body: JSON.stringify(体) }); 话(`已存为样例「${esc(名)}」,团队里的人都能用。`); 挂样例条({ 前缀, node, 填, 取 }); }
    catch (e) { 报错(e); }
  };
}

/* 跑法(10-26,方案 §8.1):连接测试 = 模型真调、澜绣数据真读,**写入类业务动作不发给澜绣**,只显示会写什么。
 * 默认连接测试(日常调提示词、换模型最常用);要真写选「正常」—— 写入前照旧停在人工核对 */
function 跑法选择(前缀, 只能演练 = false) {
  return `<label class="f">跑法</label><select id="${前缀}-mode" ${只能演练 ? "disabled" : ""}>
      <option value="连接测试">连接测试:真调模型、真读数据,写入类不真写</option>
      ${只能演练 ? "" : '<option value="正常">正常:写入类真的写(写前停在人工核对)</option>'}</select>
    ${只能演练 ? `<div class="k">这个业务动作会写数据,单独测时只能用连接测试 —— 正常跑会跳过前面的人工核对写出真记录。</div>` : ""}`;
}
function 选的跑法(前缀) { const el = $(`#${前缀}-mode`); return el ? el.value : "正常"; }

const 单测类型 = { llm: "模型", retrieve: "知识检索", tool: "业务动作", http_request: "HTTP 请求", code: "代码执行" };  // 与 runtime/单步测试.能单测的类型 同一张
function 单测字段(n) {
  return Object.entries((n.config || {}).bindings || {})
    .filter(([, r]) => !(r && (r.source === "constant" || r.source === "system"))).map(([k]) => k);
}
/* 每一项要填的:从哪来(哪一步 / 使用者输入)、什么类型、预填的值是什么时候采到的、还算不算这份图的(DF-01 §5.2-1 / 2)。
 * 预填来自修改前的图时**照填但标出来**:调试时拿旧值试是正常的,只是不能把它当成本版的产物 */
function 单测来源说明(n, f, 填自) {
  const r = ((n.config || {}).bindings || {})[f] || {};
  const 起点 = 图态.定义.nodes.find((x) => x.type === "start");
  const 源节点 = r.source === "node" ? 节点(r.node_id) : r.source === "input" ? 起点 : null;
  const 源名 = r.source === "node" ? (源节点 ? 业务名(源节点) : `已删除的步骤 ${r.node_id}`) : r.source === "input" ? "使用者输入" : "—";
  const 段 = String(r.pointer || "").replace(/^\//, "");
  const 式 = r.source === "input" ? ((起点 && (起点.config || {}).input_schema) || 图态.定义.input_schema || {})
    : 源节点 ? ((源节点.config || {}).output_schema || {}) : {};
  const 型 = ((式.properties || {})[段.split("/")[0]] || {}).type || "没声明";
  const 跑 = 填自 === "变量" ? (源节点 && 图态.运行态 && 图态.运行态[源节点.id]) : 填自 === "上次" ? (图态.运行态 && 图态.运行态[n.id]) : null;
  const 改过 = 填自 === "变量" && 源节点 && (图态.变量改 || {})[源节点.id] !== undefined;
  const 时 = 改过 ? "你在变量检查里改过的值(只在这一页)" : 跑 && 跑.时间 ? `${时间(跑.时间)} 采到` : 填自 ? "" : "没有上次的值,要手填";
  const 旧 = 跑 && !改过 && 跑.还算数 === false
    ? `<div class="ferr">⚠️ ${esc(跑.说法 || "这是修改前的图跑出来的值")} —— 可以拿来试,但测出的结果不算这一版的</div>` : "";
  return `<div class="k">来自 ${esc(源名)}${段 ? " · " + esc(段) : ""} · 类型 ${esc(型)}${时 ? " · " + esc(时) : ""}</div>${旧}`;
}
function 单测表(n) {
  if (!单测类型[n.type]) return "";
  let 只能演练 = false;
  if (n.type === "tool") {
    const t = 工具资源((n.config || {}).tool_version_id);
    if (!t) return `<div class="k">先在「基本」里选好业务动作,才能单独测。</div>`;
    // 写入类:正常跑法会跳过前面的人工核对写出真记录 —— 只许「连接测试」(不发给澜绣,只显示会写什么)
    只能演练 = t["读写"] !== "只读";
  }
  if (n.type === "http_request" && !工具连接((n.config || {}).connection_id)) {
    return `<div class="k">先在「基本」里选好工具连接,才能单独测(地址只能是它登记过的)。</div>`;
  }
  const 跑 = 图态.运行态 && 图态.运行态[n.id], 上次入 = 跑 && 跑.原文 && 跑.输入 && typeof 跑.输入 === "object" ? 跑.输入 : {};
  // 先用「变量检查」里的值(改过的优先)按这一项的来源去取;取不到再用这一步上次收到的
  const 起点 = 图态.定义.nodes.find((x) => x.type === "start");
  const 从变量 = (f) => {
    const r = ((n.config || {}).bindings || {})[f]; if (!r) return undefined;
    const 源 = r.source === "node" ? 变量值(r.node_id) : r.source === "input" && 起点 ? 变量值(起点.id) : null;
    return 源 && (源.改过 || 源.原文) ? 取指针值(源.值, r.pointer) : undefined;
  };
  const 框 = 单测字段(n).map((f) => {
    const 变 = 从变量(f), v = 变 !== undefined ? 变 : 上次入[f], 默 = v === undefined ? "" : typeof v === "string" ? v : JSON.stringify(v);
    return `<label class="f">${esc(f)}</label>${单测来源说明(n, f, 变 !== undefined ? "变量" : v !== undefined ? "上次" : null)}
      <textarea rows="2" data-st="${esc(f)}">${esc(默)}</textarea>`;
  }).join("");
  return `<div class="stest"><div class="k">单独跑这一步,不从头跑整条流程。${Object.keys(上次入).length ? "下面已填上它上次收到的内容,可以改。" : ""}
      ${n.type === "http_request" ? "会真发一次只读请求(GET / HEAD)到这条连接登记的地址;跑法选「连接测试」则不发、交一份替身。" : "用的是这一步选的模型:演示模型不花钱,真模型按一次调用计费。"}</div>
    ${样例条("st")}
    ${跑法选择("st", 只能演练)}
    ${框 || '<div class="k">这一步不需要填任何内容。</div>'}
    <button id="st-go">单独测这一步</button><div id="st-st" class="k"></div></div>`;
}
function 挂单测(n) {
  const b = $("#st-go"); if (!b) return;
  if (!能改图()) { b.disabled = true; b.title = "你只有查看权限"; return; }
  b.onclick = () => 做_单测(n.id);
  挂样例条({ 前缀: "st", node: n.id,
    填: (v) => document.querySelectorAll("[data-st]").forEach((el) => {
      const x = (v || {})[el.dataset.st];
      el.value = x === undefined || x === null ? "" : typeof x === "string" ? x : JSON.stringify(x);
    }),
    取: 读单测输入 });
}
function 读单测输入() {
  const 输入 = {};
  document.querySelectorAll("[data-st]").forEach((el) => {
    const v = el.value.trim(); if (!v) return;
    // 以 { 或 [ 开头的按 JSON 读(上次的输入是对象 / 列表时原样回填的就是 JSON);其余当文字
    if (/^[{[]/.test(v)) { try { 输入[el.dataset.st] = JSON.parse(v); return; } catch (e) { /* 不是 JSON 就当文字 */ } }
    输入[el.dataset.st] = v;
  });
  return 输入;
}
async function 做_单测(nid) {
  if (图态.脏 && !(await 做_存草稿())) return;      // 服务端读的是已保存的草稿
  const 选 = 图态.样例选 && 图态.样例选.st;
  const 体 = { ...(选 ? { 输入: {}, ...选.参数 } : { 输入: 读单测输入() }), 跑法: 选的跑法("st") };   // 看不到原文的样例:由服务端按 id 填
  const 盒 = () => $("#st-st");
  try {
    const d = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/steps/${encodeURIComponent(nid)}/test-runs`, {
      method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(体) });
    if (盒()) 盒().innerHTML = `已受理 —— <b>排队中,还没调模型</b>。`;
    await 盯单测(d.resource_id, nid);
  } catch (e) { 报错(e); }
}
// 这一次单测的账(DF-01 §5.2-5):第几次、耗时、费用 —— 每次都是新的一条运行,不覆盖上一次
function 单测账(d, s) {
  const 调 = d["调试"] || {}, 费 = 调["费用"] || {};
  const 钱 = 费["金额"] == null ? esc(费["状态"] || "—") : `${费["状态"] === "有算不出的" ? "至少 " : ""}¥${Number(费["金额"]).toFixed(4)}${
    费["算不出笔数"] ? `(另有 ${费["算不出笔数"]} 笔算不出)` : ""}`;
  return `<div class="k">这一步第 ${esc(String(调["第几次"] ?? "—"))} 次单独测 · 运行 <code>${esc(d.id)}</code>
    · 耗时 ${s && s["耗时毫秒"] != null ? (s["耗时毫秒"] / 1000).toFixed(1) + " 秒" : "—"} · 费用 ${钱}</div>`;
}
async function 盯单测(rid, nid) {
  for (let i = 0; i < 40; i++) {
    let d;
    try { d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`); } catch (e) { break; }
    const s = (d["步骤"] || []).find((x) => x["节点"] === nid);
    // 只更新这一步的标记,不覆盖其它步骤上次整条试运行的结果(小图里只有这一步)
    if (s) {
      图态.运行态 = Object.assign({}, 图态.运行态 || {}, { [nid]: 运行态条(d, s) });
    }
    const 完 = d["是终态吗"] || d["在等什么"];
    if ($("#st-st") && 图态.选中 === nid) {
      $("#st-st").innerHTML = `${业务结果块(d)}${单测账(d, s)}
        ${s ? 步骤IO(s, d["看得到原文"], true) : ""}<a href="#/wfrun/${encodeURIComponent(rid)}">完整详情 →</a>`;
    }
    if (完) {
      if (图态.选中 === nid) 画_面板();
      if (图态.视图 === "流程图") { if (typeof 画_节点 === "function") 画_节点(); } else if ($("#steps")) 画_步骤();   // 列表 / 图上的标记跟着更新
      return;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}


/* ── 运行详情 ─────────────────────────────────────────────────── */
/* ── 运行控制:暂停 / 继续 / 取消 / 核实外部状态 ────────────────────────
 *
 * ⚠️ 这四个动作**全都要幂等键,而前三个还要 revision**(乐观锁)。
 * 两个人同时点「取消」和「继续」时,少了乐观锁的那一个会**悄悄覆盖**另一个 ——
 * 而两边都收到「成功」。
 *
 * ⚠️ **`revision` 是 2026-09-29 才有地方拿的。** 在那之前
 * `GET /execution-runs/{id}` 不给它,于是这三个动作在界面上**做不起来** ——
 * 不是前端没写,是它拿不到必须带的那个值。
 *
 * ⚠️ 状态名一律**不在前端翻译**:`pause_requested` 是「请求暂停」而不是
 * 「已暂停」,而这两件事差得很远(在途的调用未必立刻停)。
 * 服务端返回的 `status` 原样显示 + 一句人话说明,**不自己编一套中文**:
 * 前端编一套的话,它和状态机会漂,而漂的表现是**界面上说停了、实际还在跑**。
 */
const 运行控制 = {
  async 暂停(rid, revision) { return await _控(rid, "pause", revision); },
  async 继续(rid, revision) { return await _控(rid, "resume", revision); },
  async 取消(rid, revision) { return await _控(rid, "cancel", revision); },
  async 核实(rid) {
    // 核实外部状态**不要乐观锁**(它不改状态,只去问一次外部系统),但要幂等键。
    return await 请求(
      `${P()}/execution-runs/${encodeURIComponent(rid)}/reconcile`,
      { method: "POST", headers: { "Idempotency-Key": 新键() },
        body: JSON.stringify({}) });
  },
};
async function _控(rid, 动作, revision) {
  // ⚠️ **revision 为空时当场报错,不发请求。**
  // 发出去的话服务端会回 422「要给 revision(或 If-Match 头)」——
  // 那句话是对的,但它让人以为是接口的问题,而真相是这一页没读到那个数。
  // 而且一条被拒的请求会在审计里留一行读不懂的失败。
  if (revision == null) {
    const e = new Error("这次运行的 revision 读不到 —— "
      + "运行详情接口应该给它(2026-09-29 补的)");
    e.体 = { code: "NO_RUN_REVISION",
             advice: "刷新一次;还是这样就是详情接口没返回 revision" };
    e.码 = 0;
    throw e;
  }
  return await 请求(
    `${P()}/execution-runs/${encodeURIComponent(rid)}/${动作}`,
    { method: "POST",
      headers: { "Idempotency-Key": 新键(), "If-Match": String(revision) },
      body: JSON.stringify({}) });
}
if (typeof globalThis !== "undefined") globalThis.运行控制 = 运行控制;

/* 按钮怎么摆:**终态就不摆**,而且说清为什么。
 *
 * ⚠️ 摆一个点了回「这次运行已经结束了」的按钮,和不摆是两件事:
 * 前者让人以为还能操作,而**「点了没用」比「没有这个按钮」更费时间**。
 * 所以终态时那一栏写的是状态本身,不是一排灰按钮。
 */
function 运行控制按钮(d) {
  if (d["是终态吗"]) {
    return `<span class="pill">已经是终态(${esc(d["执行状态中文"] || d["执行状态"])})
      —— <b>没有可执行的控制动作</b></span>`;
  }
  const 能控 = 我的角色 === "admin" || 我的角色 === "editor"
    || 我的角色 === "trainer" || 我的角色 === "approver";
  if (!能控) {
    return `<span class="k">控制这次运行要「运行编排测试」这条能力 ——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆按钮</b></span>`;
  }
  // ⚠️ revision 拿不到就**明说**,不摆一个注定 422 的按钮。
  if (d["revision"] == null) {
    return `<span class="pill warn">读不到这次运行的 <code>revision</code> ——
      <b>控制动作要拿它做 If-Match</b>,所以这里不摆按钮(多半是详情接口没返回它)</span>`;
  }
  // ⚠️ **只摆现在合法的那几个,不合法的说清为什么。**
  //
  // 第一版四个一起摆,而 `queued` 的运行点「请求暂停」会回 `BAD_TRANSITION`
  // (状态机只允许从 `running` 走)—— 正是上面那段注释里写的毛病。
  //
  // 合法与否**由接口算**(`可执行的控制动作`),不在这儿按状态自己判:
  // 那等于把状态机在前端再抄一遍,而抄件会漂 ——
  // 漂的表现是界面上摆着一个不合法的按钮、或者藏掉一个其实能用的,
  // **两者都不报错**。
  const 动作们 = d["可执行的控制动作"];
  if (!Array.isArray(动作们)) {
    // ⚠️ 接口没给这一栏时**不猜**。猜的话就回到了「前端抄一份状态机」。
    return `<span class="pill warn">详情接口没给 <code>可执行的控制动作</code> ——
      <b>所以这里不摆按钮</b>:摆哪几个要由接口算,前端猜等于把状态机抄一遍</span>`;
  }
  const 能的 = 动作们.filter((a) => a["现在能吗"]);
  const 不能的 = 动作们.filter((a) => !a["现在能吗"]);
  return (能的.map((a) => `<button data-rc="${esc(a["动作"])}"${
      a["动作"] === "reconcile" ? ' class="k"' : ""}>${esc(a["中文"])}</button>`).join(" ")
    || `<span class="k">现在没有可做的控制动作</span>`)
    + (不能的.length
      ? `<div class="k" style="margin-top:4px">现在做不了:${
          不能的.map((a) => `${esc(a["中文"])}（${esc(a["为什么不能"] || "")}）`).join("；")
        }</div>` : "")
    + `<div class="k" style="margin-top:4px">revision ${esc(d["revision"])}
      —— 控制动作拿它做 If-Match(**两个人同时点,后到的不许悄悄覆盖先到的**)</div>`;
}

function 挂运行控制(rid, d) {
  document.querySelectorAll("[data-rc]").forEach((b) => {
    b.onclick = async () => {
      const 动 = b.dataset.rc;
      // 11-08 UI 检查:取消运行原来点了就执行,撤不回
      if (动 === "cancel" && !(await 问一句("取消这次运行?", "正在跑的步骤会被停下,<b>取消之后不能恢复</b>,要重新发起一次。", { 确定: "取消运行", 取消: "继续跑" }))) return;
      b.disabled = true;
      if ($("#rcmsg")) $("#rcmsg").innerHTML = `<div class="state"><p>提交中…</p></div>`;
      try {
        const r = 动 === "reconcile"
          ? await 运行控制.核实(rid)
          : await 运行控制[{ pause: "暂停", resume: "继续", cancel: "取消" }[动]](
              rid, d["revision"]);
        // ⚠️ **原样显示服务端给的 status 和说明,不自己翻译。**
        // 前端编一套中文的话,它和状态机会漂 ——
        // 而漂的表现是**界面上说停了、实际还在跑**。
        // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
        await 页_运行详情(rid);
        if ($("#rcmsg")) {
          $("#rcmsg").innerHTML = `<div class="state"><p>
            <code>${esc(r.status || "")}</code>
            ${r["改了吗"] === false ? "（<b>没有改动</b>）" : ""}
            ${r["核实结论"] ? `<br><b>核实结论</b>:${esc(r["核实结论"])}` : ""}
            ${r.job_id ? `<br>已排任务 <code>${esc(r.job_id)}</code>,worker 从检查点接着跑` : ""}
            <br>${md(r.note || r["说明"] || "")}</p></div>`;
        }
      } catch (e) {
        if ($("#rcmsg")) {
          const s2 = 错误块(e, null);
          $("#rcmsg").innerHTML = s2.html;
        }
        b.disabled = false;
      }
    };
  });
}

/* ── 原始日志查看器(交互控件设计 §15 · L01–L07)───────────────────────
 * **只显示服务端库里已记下的原始记录**(事件 / 步骤尝试 / 工具调用 / 人工决定 / 桥请求),
 * 不重新执行任何东西,不让模型生成「日志」。默认原始视图;格式化只是换个排法,不覆盖原件。
 * 筛选后的结果写明「筛选子集 x / 共 y」,不把子集冒充全部;分页「加载更多」并写已加载多少。
 * 外部内容一律按纯文本显示(esc),不执行日志里的任何脚本或指令。 */
async function 原始日志(rid, 筛 = {}, 运行 = null) {
  const el = $("#rawlog"); if (!el) return;
  const 态 = { rid, 筛: { 节点: 筛.节点 || "", 来源: "", 只看错误: false, 尝试: 筛.尝试 ?? null }, 条目: [], 下一页: 0, 格式化: false, 跟随: false, 回: null };
  const 取 = async (续) => {
    const q = new URLSearchParams();
    if (态.筛.节点) q.set("节点", 态.筛.节点);
    if (态.筛.来源) q.set("来源", 态.筛.来源);
    if (态.筛.只看错误) q.set("只看错误", "true");
    if (态.筛.尝试 != null) q.set("尝试", String(态.筛.尝试));
    q.set("从", String(续 ? 态.下一页 : 0)); q.set("条数", "100");
    const d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}/raw-log?${q}`);
    态.回 = d; 态.条目 = 续 ? [...态.条目, ...d["条目"]] : d["条目"]; 态.下一页 = d["下一页从"];
  };
  const 画 = () => {
    const d = 态.回 || {}, 全 = d["共"] ?? 0, 筛后 = d["筛选后"] ?? 0, 是子集 = 筛后 !== 全;
    const 节点们 = [...new Set((运行 && 运行["步骤"] || []).map((x) => x["节点"]))];
    el.innerHTML = `<div class="card rawlog">
      <div class="acts" role="group" aria-label="原始日志筛选">
        <select id="rl-src" aria-label="来源"><option value="">全部来源</option>${["事件", "步骤尝试", "工具调用", "人工决定", "桥请求"].map((k) =>
          `<option ${态.筛.来源 === k ? "selected" : ""}>${k}</option>`).join("")}</select>
        <select id="rl-node" aria-label="节点"><option value="">全部节点</option>${节点们.map((k) => `<option ${态.筛.节点 === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>
        <label class="k"><input type="checkbox" id="rl-err" ${态.筛.只看错误 ? "checked" : ""}> 只看错误</label>
        ${态.筛.尝试 != null ? `<span class="pill">第 ${esc(态.筛.尝试)} 次尝试 <button id="rl-att-x" aria-label="不按尝试筛">×</button></span>` : ""}
        <span class="seg"><button id="rl-raw" aria-pressed="${!态.格式化}">原始记录</button><button id="rl-fmt" aria-pressed="${态.格式化}">格式化</button></span>
        ${运行 && !运行["是终态吗"] ? `<label class="k"><input type="checkbox" id="rl-follow" ${态.跟随 ? "checked" : ""}> 跟随新记录</label>` : ""}
        <button id="rl-copy">复制已加载的</button> <button id="rl-dl">下载</button> <button id="rl-x">收起</button>
      </div>
      <div class="k">${是子集 ? `<b>筛选子集</b> ${筛后} / 共 ${全} 条` : `共 ${全} 条`} · 已加载 ${态.条目.length} 条
        · 按来源:${Object.entries(d["按来源"] || {}).map(([k, v]) => `${esc(k)} ${v}`).join("、")}
        · ${d["能看原文"] ? "原件" : "<b>部分打码</b>(没有「查看敏感输入」授权)"}</div>
      <div class="note">${esc(d["采集边界"] || "")}</div>
      ${态.条目.length ? 态.条目.map((x, i) => `<div class="rlrow ${x["是错误"] ? "bad" : ""}">
          <div class="rlh"><span class="k">${时间(x["时间"])}</span> <b>${esc(x["来源"])}</b> <code>${esc(x["类型"])}</code>
            ${x["节点"] ? `<button class="lk" data-rlgo="${esc(x["节点"])}" title="到这一步">节点 ${esc(x["节点"])}</button>` : ""}
            ${x["尝试"] != null ? `<span class="k">第 ${esc(x["尝试"])} 次</span>` : ""}
            ${x["来源"] === "桥请求" && x["主键"] ? `<a href="#/bridge/${encodeURIComponent(x["主键"])}">看这张桥请求 →</a>` : ""}
            <span class="k" title="来源表 + 主键;指纹是原件的 SHA-256 前 16 位,打码副本和原件指纹一样,可以对">${esc(x["来源表"])} · ${esc(x["主键"])} · ${esc(x["字节数"])} 字节 · 指纹 ${esc(x["指纹"])}</span>
            ${x["是打码副本"] ? `<span class="pill warn">打码副本</span>` : ""}
            ${x["载荷在外部存储"] ? `<span class="pill warn" title="这一条只带了引用,正文不在这里">载荷在外部存储:${esc(x["载荷在外部存储"])}</span>` : ""}</div>
          <pre class="io">${esc(态.格式化 ? 格式化日志(x["原件"]) : JSON.stringify(x["原件"]))}</pre></div>`).join("")
        : `<div class="k">${全 ? "这个筛选条件下一条都没有。" : "这次运行还没有任何已记录的原始记录(排队中的运行一条都没有是正常的)。"}</div>`}
      ${态.下一页 != null ? `<button id="rl-more">加载更多(还有 ${筛后 - 态.条目.length} 条)</button>` : ""}
    </div>`;
    const 重取 = async () => { try { await 取(false); } catch (e) { 报错(e); } 画(); };
    $("#rl-src").onchange = (e) => { 态.筛.来源 = e.target.value; 重取(); };
    $("#rl-node").onchange = (e) => { 态.筛.节点 = e.target.value; 重取(); };
    $("#rl-err").onchange = (e) => { 态.筛.只看错误 = e.target.checked; 重取(); };
    if ($("#rl-att-x")) $("#rl-att-x").onclick = () => { 态.筛.尝试 = null; 重取(); };
    $("#rl-raw").onclick = () => { 态.格式化 = false; 画(); };
    $("#rl-fmt").onclick = () => { 态.格式化 = true; 画(); };
    $("#rl-x").onclick = () => { 态.跟随 = false; el.innerHTML = ""; };
    if ($("#rl-more")) $("#rl-more").onclick = async () => { try { await 取(true); } catch (e) { 报错(e); } 画(); };
    if ($("#rl-follow")) $("#rl-follow").onchange = (e) => { 态.跟随 = e.target.checked; if (态.跟随) 跟随(); };
    $("#rl-copy").onclick = () => {
      const 文 = JSON.stringify({ 运行: rid, 说明: 是子集 || 态.下一页 != null ? `这是已加载的 ${态.条目.length} 条(筛选后 ${筛后} / 共 ${全}),不是全部` : "全部",
        内容: d["能看原文"] ? "原件" : "部分打码", 条目: 态.条目 }, null, 1);
      (navigator.clipboard ? navigator.clipboard.writeText(文) : Promise.reject(new Error("浏览器不给剪贴板")))
        .then(() => 轻提示(`已复制 ${态.条目.length} 条(写明了是不是全部)`), (e) => 轻提示("复制不了:" + e.message));
    };
    $("#rl-dl").onclick = async () => {
      try {
        const 包 = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}/raw-log/export`, { method: "POST",
          body: JSON.stringify({ 节点: 态.筛.节点 || null, 来源: 态.筛.来源 || null, 只看错误: 态.筛.只看错误, 尝试: 态.筛.尝试 }) });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([JSON.stringify(包, null, 1)], { type: "application/json" }));
        a.download = `原始日志-${rid}${是子集 ? "-筛选子集" : ""}.json`; a.click();
        轻提示(`已下载 ${包["条目"].length} 条(${包["是全部还是子集"]} · ${包["内容"].slice(0, 4)});这次导出记进了审计`);
      } catch (e) { 报错(e); }
    };
    el.querySelectorAll("[data-rlgo]").forEach((b) => {
      b.onclick = () => {
        // L07:回到当时的步骤。当前草稿里已经没有它 → 明说,**不跳到当前同名步骤**
        const id = b.dataset.rlgo, wid = 运行 && 运行["定义来源"] && (运行["定义来源"].id || 运行["定义来源"].workflow_id);
        if (图态 && 图态.wid === wid && 节点(id)) { 图态.选中 = id; location.hash = `#/workflow/${encodeURIComponent(wid)}/搭建`; return; }
        轻提示(`「${id}」在你现在打开的草稿里没有 —— 这条记录属于当时的定义(定义哈希 ${String((态.回 || {})["定义哈希"] || "").slice(0, 12)}…),不跳到同名的当前步骤`);
      };
    });
  };
  const 跟随 = async () => {
    while (态.跟随 && el.isConnected !== false && $("#rawlog") === el) {
      await new Promise((r) => setTimeout(r, 3000));
      if (!态.跟随) break;
      try { await 取(false); 画(); } catch (e) { 态.跟随 = false; 轻提示("跟随中断:" + e.message + "(已加载的还在)"); 画(); }
    }
  };
  el.innerHTML = `<div class="state">在取原始记录…</div>`;
  try { await 取(false); } catch (e) {
    el.innerHTML = `<div class="state err"><h3>${e.码 === 403 ? "没有权限看这次运行" : "取不到原始日志"}</h3><p>${esc(e.message)}</p>
      <p class="k">${e.码 === 403 ? "这是权限问题,不是没有记录。" : "这是取数失败,不是这次运行没有记录。"}</p></div>`;
    return;
  }
  画();
}
function 格式化日志(v) {
  if (!v || typeof v !== "object") return String(v ?? "");
  return Object.entries(v).map(([k, x]) => `${k}: ${typeof x === "object" && x !== null ? JSON.stringify(x) : x}`).join("\n");
}

/* 桥请求详情(11-20,还体检欠账「桥请求没有详情页、运行页链不过去」)。
 * 运行停在「等澜绣执行」时,人要能看到:这张单发了什么参数、澜绣回了什么、运行还在不在等它。
 * 只读 —— 回执是澜绣同步程序的事,页面上不给「手工回执」按钮(那会绕开澜绣那边的身份和台账)。 */
async function 页_桥请求详情(cid) {
  const 头 = `<div class="crumb">工作室 / <a href="#/studio/workflow">工作流</a> / 桥请求 ${esc(cid)}</div>
    <div class="head"><div><h1>桥请求详情</h1><div class="sub">${esc(cid)}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/bridge-calls/${encodeURIComponent(cid)}`); }
  catch (e) {
    if (e.码 === 403) { $("#main").innerHTML = 头 + `<div class="state err"><h3>没有权限看桥请求</h3><p>${esc(e.message)}</p>
      <p class="k">桥请求的参数里有转写原文和客户订单号,要「运行评测」权限才看得到。这是权限问题,不是这张单不存在。</p></div>`; return; }
    const s = 错误块(e, () => 页_桥请求详情(cid)); $("#main").innerHTML = 头 + s.html; s.挂(); return;
  }
  const 色 = { "待执行": "warn", "已执行": "ok", "执行失败": "err" }[d["状态"]] || "";
  const 等说 = d["还在等它吗"]
    ? "运行停在这一步,等澜绣的同步程序拉走执行、回执;回执到了运行才接着走。"
    : d["状态"] === "待执行"
      ? `这张单还没回执,但运行已经不在等它了(运行现在是 ${esc(d["运行状态"] || "未知")}),澜绣不会再拉走它。`
      : `澜绣已回执「${esc(d["状态"])}」${d["acked_at"] ? ` · ${时间(d["acked_at"])}` : ""}。`;
  $("#main").innerHTML = 头 + `
    <div class="card">
      <div><span class="pill ${色}">${esc(d["状态"])}</span> 工具 <b>${esc(d["工具"])}</b> · 步骤 <code>${esc(d["步骤"])}</code>
        ${d["跑法"] && d["跑法"] !== "正常" ? `<span class="pill warn">${esc(d["跑法"])}</span>` : ""}</div>
      <div class="k">${等说}</div>
      <div class="k">属于运行 <code>${esc(d["运行"])}</code> · <a href="#/wfrun/${encodeURIComponent(d["运行"])}">去看这次运行 →</a></div>
      <div class="k">排于 ${时间(d["created_at"])} · 办事人 ${esc(d["办事人"] || "未知")}${d["办事人澜绣工号"] ? `(澜绣工号 ${esc(d["办事人澜绣工号"])})` : "(没绑澜绣工号)"}
        · 幂等键 <code>${esc(d["幂等键"] || "")}</code></div>
    </div>
    <h2>发了什么</h2>
    <pre data-raw="原文" class="io">${esc(JSON.stringify(d["参数"] || {}, null, 1))}</pre>
    <h2>回了什么</h2>
    ${d["状态"] === "已执行" ? `<pre data-raw="原文" class="io">${esc(JSON.stringify(d["结果"], null, 1))}</pre>`
      : d["状态"] === "执行失败" ? `<div class="state err"><h3>澜绣执行失败</h3><pre class="io">${esc(JSON.stringify(d["失败"], null, 1))}</pre></div>`
      : `<div class="k">还没有回执。</div>`}`;
}

/* 这次运行产出的文件(11-21,「Markdown 导出」节点):列表 + 下载;没有就不画(不是每条流程都导出) */
async function 画_文件产物(rid) {
  let d;
  try { d = await 请求(`${P()}/workflow-documents?run_id=${encodeURIComponent(rid)}`); } catch (e) { return; }
  const el = $("#docbox"); if (!el || !(d.items || []).length) return;
  el.innerHTML = `<h2>产出的文件</h2><table><thead><tr><th>文件</th><th>统计期</th><th>门店</th><th>大小</th><th>状态</th><th></th></tr></thead><tbody>`
    + d.items.map((x) => `<tr><td><b>${esc(x.file_name || x.title || x.id)}</b><div class="k">${esc(x.id)} · 哈希 ${esc(String(x.content_hash || "").slice(0, 12))}…</div></td>
        <td class="k">${esc(((x.period_detail || {}).起 || "—") + ((x.period_detail || {}).止 && (x.period_detail || {}).止 !== (x.period_detail || {}).起 ? " ~ " + (x.period_detail || {}).止 : ""))}</td>
        <td class="k">${esc(x.store_id || "不限")}</td><td class="num">${Number(x.byte_count || 0).toLocaleString()} 字节</td>
        <td>${x.status === "已存" ? `<span class="pill ok">已存(回读核过)</span>` : `<span class="pill warn">${esc(x.status || "")}</span>`}</td>
        <td>${x["下载"] ? `<button data-dl="${esc(x["下载"])}" data-name="${esc(x.file_name || x.id + ".md")}">下载 .md</button>` : `<span class="k">没存成,不给下载</span>`}</td></tr>`).join("")
    + `</tbody></table><div class="k">下载 = 交出系统,每次都记审计;「生成了」和「存成了」是两件事,只有存成的才有下载。全部文件在「日志与监测 / <a href="#/documents">报告与文件</a>」。</div>`;
  挂文件下载(el);   // 11-24:原来是裸 <a href>,不带 X-Dev-User,开发态点了就是 401
}
/* 报告与文件(11-24,包二「做了要像做了」第一件):项目里所有「Markdown 导出」存下来的文件 —— 08:00 定时日报就落在这里。
 * 此前只能从某次运行详情里的「产出的文件」点到,不知道运行号的人(店长、运营)根本找不到。
 * 列表和运行详情里那块画的是同一批字段;下载走带身份的 fetch 再落成文件(裸 <a href> 不带 X-Dev-User,开发态会被挡)。 */
async function 页_报告与文件() {
  const 头 = `<div class="crumb">日志与监测 / 报告与文件</div>
    <div class="head"><div><h1>报告与文件</h1>
      <div class="sub">${md("流程里「Markdown 导出」那一步**存成**的文件(定时日报 / 周报等),最新的在最上面。"
        + "**「生成了」和「存成了」是两件事**:只有回读核过哈希、状态是「已存」的才有下载;下载 = 交出系统,每次都记审计。"
        + "登记了门店的成员只看本店或不限门店的。")}</div></div>
      <div><a class="lk" href="#/outputs">门店助手写的日报 / 建议在「产出监督」</a></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/workflow-documents?limit=100`); }
  catch (e) { const s = 错误块(e, 页_报告与文件); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 项 = d.items || [];
  if (!项.length) {
    $("#main").innerHTML = 头 + `<div class="state">还没有存成的文件。${esc(d.note || "")}<br>
      <span class="k">定时日报要到点跑过一次才有;要现在就看一份,去「待办与定时 / 定时」对那条日报点「现在跑一次」。</span></div>`;
    return;
  }
  const 期 = (x) => { const p = x.period_detail || {}; return (p.起 || "—") + (p.止 && p.止 !== p.起 ? " ~ " + p.止 : ""); };
  $("#main").innerHTML = 头 + `<div class="k" style="margin:6px 0">共 ${esc(String(d.total ?? 项.length))} 份,这页 ${项.length} 份${d["我的门店"] ? ` · 只列 ${esc(d["我的门店"])} 门店的` : ""}</div>
    <table><thead><tr><th>文件</th><th>统计期</th><th>门店</th><th>生成于</th><th>大小</th><th>状态</th><th>来自哪次运行</th><th></th></tr></thead><tbody>`
    + 项.map((x) => `<tr><td><b>${esc(x.file_name || x.title || x.id)}</b><div class="k">${esc(x.id)} · 哈希 ${esc(String(x.content_hash || "").slice(0, 12))}…</div></td>
        <td class="k">${esc(期(x))}</td>
        <td class="k">${esc(x.store_id || "不限")}</td>
        <td class="k">${esc(String(x.generated_at || x.created_at || "").replace("T", " ").slice(0, 16))}</td>
        <td class="num">${Number(x.byte_count || 0).toLocaleString()} 字节</td>
        <td>${x.status === "已存" ? `<span class="pill ok">已存(回读核过)</span>` : `<span class="pill warn">${esc(x.status || "")}</span>`}</td>
        <td>${x.execution_run_id ? `<a href="#/wfrun/${encodeURIComponent(x.execution_run_id)}">${esc(x.execution_run_id)}</a>` : "—"}</td>
        <td>${x["下载"] ? `<button data-dl="${esc(x["下载"])}" data-name="${esc(x.file_name || x.id + ".md")}">下载 .md</button>` : `<span class="k">没存成,不给下载</span>`}</td></tr>`).join("")
    + `</tbody></table>`;
  挂文件下载($("#main"));
}
/* 带身份的文件下载(11-24):裸 <a href> 不带 X-Dev-User,开发态直接被接口挡回 401 —— 「修下载」修的就是这个。
 * 报告与文件页和运行详情里的「产出的文件」共用;按钮上写进度和结果,失败不装作成功。 */
function 挂文件下载(root) {
  root.querySelectorAll("button[data-dl]").forEach((b) => b.onclick = async () => {
    b.disabled = true; const 原 = b.textContent; b.textContent = "下载中…";
    try {
      const r = await fetch(b.dataset.dl, { headers: { "X-Dev-User": 我 } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = b.dataset.name; a.click();
      URL.revokeObjectURL(a.href); b.textContent = "已下载";
    } catch (e) { b.textContent = `下载失败:${e.message || e}`; }
    finally { setTimeout(() => { b.disabled = false; if (b.textContent !== "已下载") b.textContent = 原; }, 2500); }
  });
}
async function 页_运行详情(rid) {
  const d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`);
  const 步 = d["步骤"] || [];
  画_文件产物(rid);
  $("#main").innerHTML = `
    <div class="crumb">工作室 / <a href="#/studio/workflow">工作流</a> / 运行 ${esc(rid)}</div>
    <div class="head"><div><h1>运行详情</h1>
      <div class="sub">定义来源 <code data-raw="原文">${esc(JSON.stringify(d["定义来源"] || {}))}</code></div>
    </div>
      <div>${运行控制按钮(d)}</div>
    </div>
    <div id="rcmsg"></div>
    ${业务结果块(d)}
    <div id="docbox"></div>
    ${回复气泡(d)}
    <div class="cards">
      <div class="card"><div class="kpi">${esc(d["执行状态中文"])}</div>
        <div class="k">执行状态 <code>${esc(d["执行状态"])}</code>
          ${d["是终态吗"] ? "· 终态" : "· 还在动"}</div></div>
      <div class="card"><div class="kpi">${esc(d["任务达标"])}</div>
        <div class="k">任务达标状态</div>
        <div class="note" style="margin-top:6px">${md(d["达标说明"])}</div></div>
      <div class="card"><div class="kpi">${esc(d["模式"])}</div>
        <div class="k">执行方式 <span title="字段名">(execution_mode)</span></div>
        <div class="note" style="margin-top:6px">mock 和真实实现<b>同一个契约</b> ——
          正因为无缝,这个标记才是必需的(§19.4)。</div></div>
      <div class="card"><div class="kpi">${esc(JSON.stringify(d["用量"] || {}))}</div>
        <div class="k">用量</div>
        <div class="note" style="margin-top:6px">费用记成<b>「未知」不是 0</b> ——
          ${d["模式"] === "mock" ? "演示模型没有真实计价。"
            : "真模型这一次也记成未知:运行账本还没接供应商的计价,真花了多少要看供应商账单。"}</div></div>
    </div>
    <h3>步骤(${步.length}) <button id="rl-open">原始日志</button></h3>
    <div id="rawlog"></div>
    <table><thead><tr><th>节点</th><th>类型</th><th>状态</th><th>尝试</th>
      <th>执行键</th><th>分支 / 为什么跳过</th><th>错误</th><th>输入 / 输出</th><th></th></tr></thead><tbody>`
    + 步.map((s) => `<tr>
        <td><b>${esc(s["节点"])}</b></td><td class="k">${esc(s["类型"])}</td>
        <td>${s["状态"] === "succeeded" ? `<span class="pill ok">成功</span>`
            : s["状态"] === "skipped" ? `<span class="pill">未激活(跳过)</span>`
            : `<span class="pill warn">${esc(s["状态"])}</span>`}</td>
        <td class="k">${esc(s["尝试"])}</td>
        <td><code style="font-size:11px">${esc(s["执行键"])}</code></td>
        <td class="k">${esc(s["走的分支"] || s["为什么跳过"] || "")}</td>
        <td class="k">${esc(s["错误码"] || "")}</td>
        <td>${步骤IO(s, d["看得到原文"]) || '<span class="k">—</span>'}</td>
        <td><button data-rlnode="${esc(s["节点"])}" data-rlatt="${esc(s["尝试"] ?? "")}">查看该节点日志</button></td></tr>`).join("")
    + `</tbody></table>
    <div class="note"><b>「未激活(跳过)」和「失败」是两个状态</b>(§8)——
      未激活的支路既不阻塞汇合,<b>也不算「完成了的工作」</b>。
      合并之后,「这次跑过了 N 个节点」这句话就没有意义了。<br>
      执行键含 <code>(Run, node_id, 循环路径, 尝试次数)</code> ——
      <b>传输重试不改变它</b>,所以网络重发不会变成第二次写入(§8)。</div>
    <h3>输入输出</h3>
    <div class="two">
      <div class="card"><h4>输入快照</h4>
        <pre data-raw="原文" style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(d["输入快照"], null, 1))}</pre></div>
      <div class="card"><h4>输出</h4>
        <pre data-raw="原文" style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(d["输出"], null, 1))}</pre>
        <div class="note">原文默认<b>脱敏</b>;要看要「查看敏感输入/独立测试答案」
          专项授权(§14.3)。顶栏切到 U004 能看到区别。</div></div>
    </div>
    <h3>事件(${(d["事件"] || []).length})</h3>
    ${(d["事件"] || []).map((e) => `<div style="font-size:12px">
        <span class="k">${esc(String(e.seq).padStart(2, "0"))}</span>
        <code>${esc(e["类型"])}</code>
        <span data-raw="原文" class="k">${esc(JSON.stringify(e["载荷"] || {}).slice(0, 160))}</span></div>`).join("")}
    <div class="note">事件<b>只表达已记录的事实</b>(§17.2)——
      不会在外部返回成功之前先发一条成功事件。seq 在 Run 内单调,断线能按 seq 续。</div>`;
  // ⚠️ 事件要在 innerHTML 写完**之后**挂 —— 写之前挂的话那些按钮还不存在,
  // 而 `querySelectorAll` 返回空数组**不报错**:表现是「点了没反应」。
  挂运行控制(rid, d);
  $("#rl-open").onclick = () => 原始日志(rid, {}, d);
  document.querySelectorAll("[data-rlnode]").forEach((b) => {
    b.onclick = () => 原始日志(rid, { 节点: b.dataset.rlnode, 尝试: b.dataset.rlatt === "" ? null : +b.dataset.rlatt }, d);
  });
}

/* ══════════════════════════════════════════════════════════════════
 * 智能体 Agent(规格 §9)与工具目录(§11.1)
 * ══════════════════════════════════════════════════════════════════
 *
 * ## 这两页刻意做成什么样
 *
 * ① **工具数旁边写着它不是能力分**(§9.1:「不按工具数量给 Agent 打能力强弱分」)。
 *    一个显示「工具数 7」的列表天然会被读成「它比那个 3 的强」——
 *    而它只表示授权候选集合的规模。
 *
 * ② **模型连接那一栏直接显示「原生工具调用:支持 / 没声明」**。
 *    §9.3 要能力检查,附录 D.2 补了「**不按模型家族名字推断兼容**」——
 *    所以这里不显示模型叫什么,显示**探测回来的能力**。
 *    选一条「没声明」的连接,点校验会当场被挡住并说清为什么。
 *
 * ③ **运行限制每一条旁边写着它的强制执行位置和落地没落地**(§9.6 那一栏)。
 *    一个只存在于表单里、没有任何地方读的上限,**和没有这条限制一模一样** ——
 *    而界面上它是填好的。所以这里把「已落地 / 还没落地」显示出来。
 *
 * ④ 那几个默认值(回合 8 / 工具 12 / 期限 180 秒)标着「**设计初值**」——
 *    §9.6 结尾:「当前没有性能或模型优劣的实测结论」。
 */
async function 弹_新建agent() {
  const 名 = await 问一句("新建 Agent", "给它起个名字,一眼看得出它是干什么的。", { 输入: "比如 退款研判助手", 确定: "新建", 必填: true });
  if (!名) return;
  请求(`${P()}/agents`, { method: "POST", body: JSON.stringify({ 名称: 名 }) })
    .then((d) => { location.hash = `#/agent/${encodeURIComponent(d.id)}`; })
    .catch(报错);
}

let agent态 = null;

async function 页_agent配置(aid) {
  const d = await 请求(`${P()}/agents/${encodeURIComponent(aid)}`);
  agent态 = { aid, ...d, 脏: false, Tab: "行为", 事件: [], 跑结果: null };
  画_agent();
}

function 画_agent() {
  const g = agent态, cfg = g["草稿"]["配置"] || {};
  const 报 = g["草稿"]["上次校验报告"];
  const tabs = ["行为", "工具与知识", "权限与限制", "调试", "版本"];
  $("#main").innerHTML = `
    <div class="crumb">工作室 / <a href="#/studio/agent">Agent</a> / ${esc(g["名称"])}</div>
    <div class="head"><div><h1>${esc(g["名称"])}</h1>
      <div class="sub">草稿 r${g["草稿"]["revision"]}
        ${g.脏 ? `<span class="stale">有未保存的改动</span>` : ""}</div></div>
      <div><button id="v">校验</button><button id="run">试运行</button>
        <button class="pri" id="freeze">冻结为新版本</button></div></div>
    <div id="body"></div>
    <div class="footbar"><span id="fb">${報状态(报, g.脏)}</span>
      <span class="grow"></span><button id="save">保存草稿</button></div>`;
  $("#v").onclick = 做_校验agent;
  $("#run").onclick = 做_跑agent;
  $("#freeze").onclick = 做_冻结agent;
  $("#save").onclick = 做_存agent;
  画_agent侧栏(g, tabs);
  画_agent正文();
}

/* Agent 的应用侧栏(10-28,和工作流那一列同一个样子)。⚠️ 和工作流不同:这里**不改地址**,点了只换页签 ——
 * Agent 的页签一直是页内状态,未保存的改动挂在 agent态 上;改成换地址会重新拉一遍,把没存的改动丢掉 */
function 画_agent侧栏(g, tabs) {
  $("#side").innerHTML = `<a class="back" href="#/studio/agent">← 工作室</a>
    <div class="apphead"><span class="ico ag">智</span><div class="an"><b>${esc(g["名称"])}</b><div class="k">Agent</div></div></div>
    ${tabs.map((t) => `<a href="#" data-atab="${esc(t)}"${g.Tab === t ? ' class="on"' : ""}>${esc(t)}</a>`).join("")}
    <div class="grp">还没做</div>
    ${应用侧栏待做.map(([名, 为什么]) => `<a class="todo" title="${esc(为什么)}">${名}</a>`).join("")}`;
  $("#side").querySelectorAll("[data-atab]").forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); agent态.Tab = a.dataset.atab; 画_agent(); };
  });
}

function 報状态(报, 脏) {
  if (脏) return "<b>有未保存的改动</b> —— 保存草稿不影响任何已冻结版本,也不影响生产。";
  if (!报) return "还没校验过 —— <b>客户端看起来没问题不代替服务端校验</b>。";
  return 报["通过"] ? "上次校验:<b>通过</b>"
    : `上次校验:<b>${报["阻断数"]} 条阻断</b> / ${报["警告数"]} 条警告`;
}

// 11-08 UI 检查:页面上原样露出 pending / approved / production 这类英文值,店员和产品经理看不懂。
// 只翻显示,原值放进 title;后端返回的值本身不动(判断逻辑照旧用英文值)
// 11-08 UI 检查:这些按钮请求中原来还能连点 —— 试运行 / 单条试跑每点一次就真花一次钱,发密钥连点会发两把,批准 / 驳回会重复提交。
// 只跑一次():上一次没结束时再点直接忽略
function 只跑一次(fn) { let 忙 = false; return async (...a) => { if (忙) return; 忙 = true; try { return await fn(...a); } finally { 忙 = false; } }; }
// 函数声明会提升,所以在这里重新绑定就生效(工作流试运行 / 智能体试运行)
做_试运行 = 只跑一次(做_试运行); 做_跑agent = 只跑一次(做_跑agent);
const _英转中 = { pending: "待处理", approved: "已批准", rejected: "已驳回", expired: "已过期", cancelled: "已取消", info_requested: "待补充",
  running: "运行中", queued: "排队中", succeeded: "成功", failed: "失败", ok: "成功", denied: "被拒",
  test: "测试", staging: "预发", production: "生产", development: "开发" };
function 字段(标, 键, 值, 说明, 多行) {
  const v = 值 === undefined || 值 === null ? ""
    : (typeof 值 === "object" ? JSON.stringify(值, null, 1) : String(值));
  return `<div class="fieldrow"><label>${esc(标)}</label>
    ${多行 ? `<textarea data-k="${esc(键)}" data-raw="原文" rows="${多行}">${esc(v)}</textarea>`
           : `<input data-k="${esc(键)}" data-raw="原文" value="${esc(v)}">`}</div>
    ${说明 ? `<div class="note">${md(说明)}</div>` : ""}`;
}

function 画_agent正文() {
  const g = agent态, cfg = g["草稿"]["配置"] || {};
  const 问 = (报 => (报?.问题 || []))(g["草稿"]["上次校验报告"]);
  const 报错块 = 问.length ? `<div class="err" style="padding:10px;margin-bottom:12px">
      ${问.map((p) => `<div style="margin-bottom:6px">
        <b>${esc(p.code)}</b> ${p.field_path ? `<code>${esc(p.field_path)}</code>` : ""}
        <br>${md(p["消息"])}<br><span class="k">怎么改:${md(p["建议"])}</span></div>`).join("")}
    </div>` : "";
  if (g.Tab === "行为") {
    $("#body").innerHTML = 报错块 + `<div class="card">
      <h4>模型连接</h4>
      <div class="fieldrow"><label>模型连接版本 <span class="k">(connection_version_id)</span></label>
        <select data-k="connection_version_id">
          <option value="">(没选)</option>
          ${g["可选连接"].map((c) => `<option value="${esc(c.id)}"
            ${cfg.connection_version_id === c.id ? "selected" : ""}>
            ${esc(c["名称"])} · 原生工具调用:${c["原生工具调用"] ? "支持" : "没声明"}
            · ${esc(c["模式"] || "?")}${c["不在名单里"] ? ` · ${esc(c["不在名单里"])}` : ""}</option>`).join("")}
          ${cfg.connection_version_id && !g["可选连接"].some((c) => c.id === cfg.connection_version_id)
            ? `<option value="${esc(cfg.connection_version_id)}" selected>(当前选的已经查不到了)</option>` : ""}
        </select></div>
      <div class="note">这一栏显示的是<b>探测回来的能力</b>,不是模型叫什么名字。
        规格附录 D.2:<b>不按模型家族名字推断兼容</b> —— 能不能按契约调工具是按型号来的。
        选一条「没声明」的,点校验会当场被挡住。</div>
      </div>
      <div class="card">
      <h4>术语</h4>
      <div class="fieldrow"><label>用哪一版术语</label>
        <select data-k="glossary_version_id">
          <option value="">不带术语</option>
          ${(g["可选术语"] || []).map((v) => `<option value="${esc(v.id)}"
            ${cfg.glossary_version_id === v.id ? "selected" : ""}>${esc(v["名称"])} · ${esc(v["版本"])} · ${esc(v["条数"])} 条</option>`).join("")}
          ${cfg.glossary_version_id && !(g["可选术语"] || []).some((v) => v.id === cfg.glossary_version_id)
            ? `<option value="${esc(cfg.glossary_version_id)}" selected>(当前选的不在列表里)</option>` : ""}
        </select></div>
      <div class="note">每次运行只把任务和输入里提到的那几条术语拼在指令前面。只列<b>冻结了的</b>版本;换术语 = 改了这个智能体,要重新冻一版。</div>
      </div>
      <div class="card">${字段("目标模板", "task_template", cfg.task_template,
        "**和长期角色指令分开**(§9.3):这一次要交付什么,绑运行输入。", 3)}
        ${字段("指令(工作原则)", "instructions", cfg.instructions,
        "引用 Prompt 版本;**局部覆盖必须进版本 Diff**(§9.3)—— "
        + "一段只存在于某处覆盖里的提示词,在版本对比上看不见。", 3)}
        ${字段("输入 Schema", "input_schema", cfg.input_schema, "", 4)}
        ${字段("输出契约", "output_schema", cfg.output_schema,
        "**结构校验不能代替事实质量**(§9.3);声明的文件必须确实存在且可访问。", 6)}
        ${字段("完成判据", "completion_criteria", cfg.completion_criteria,
        "**必要证据里点名的字段必须真的在输出契约里** —— "
        + "一条点名了不存在字段的判据永远查不到东西,而它在界面上是填好的。", 3)}
        ${字段("无法完成策略", "incomplete_strategy", cfg.incomplete_strategy,
        "明确哪些情况允许部分完成;**不把所有结果统一显示成成功**(§9.3)。", 2)}
      </div>`;
  } else if (g.Tab === "工具与知识") {
    const 选中 = new Set((cfg.tools || []).map((t) => (t.tool_version_id || t)));
    $("#body").innerHTML = 报错块 + `<div class="card"><h4>工具(勾选=授权给它)</h4>
      <table><thead><tr><th></th><th>工具</th><th>版本</th><th>读写类型</th>
        <th>要确认</th><th>能查外部状态</th><th>可轮询</th>
        <th>服务端绑定参数</th></tr></thead><tbody>`
      + g["可选工具"].map((t) => `<tr>
        <td><input type="checkbox" data-tool="${esc(t.id)}"
            ${选中.has(t.id) ? "checked" : ""}></td>
        <td><b>${esc(t["名称"])}</b><div class="k">${esc(t["模型可见说明"] || "")}</div></td>
        <td class="k">${esc(t["版本"])}</td>
        <td>${t["读写类型"] === "只读" ? `<span class="pill">只读</span>`
              : `<span class="pill warn">${esc(t["读写类型"])}</span>`}</td>
        <td>${t["要确认吗"] ? "是" : `<span class="k">否</span>`}</td>
        <td>${t["能查外部状态吗"] ? "是" : `<span class="k">否</span>`}</td>
        <td>${t["可轮询吗"] ? "是" : `<span class="k">否</span>`}</td>
        <td class="k">${esc((t["服务端绑定参数"] || []).join(", ") || "—")}</td>
      </tr>`).join("") + `</tbody></table>
      <div class="note"><b>服务端绑定参数模型看不见,也不接受它传入</b>(§9.4)——
        输出目录、project_id、允许的文档库由服务端定。
        判据是「模型<b>提到</b>了这个键」,不是「值不一样」:
        它恰好填对了一次也不放行,因为<b>「这次值是对的」不是一条安全性质</b>。<br>
        <b>不可逆写入必须有确认策略</b>,而且<b>模型不能批准自己</b>(§9.6)。</div>
      </div>
      <div class="card"><h4>上下文与记忆</h4>
      ${字段("上下文策略(context_policy)", "context_policy", cfg.context_policy, "", 3)}
      <div class="note"><b>长期记忆首版关闭</b>(§9.5)——
        未经审核就持久化的错误事实会跨任务传染,而作用域、保留期限、撤回都还没实现。<br>
        资料里的指令<b>是资料,不是授权</b>:一句「忽略之前的规则」改不了 allowed_scopes。</div>
      </div>`;
    $("#body").querySelectorAll("[data-tool]").forEach((b) => {
      b.onchange = () => {
        const 现 = new Set((agent态["草稿"]["配置"].tools || [])
          .map((t) => (t.tool_version_id || t)));
        if (b.checked) 现.add(b.dataset.tool); else 现.delete(b.dataset.tool);
        agent态["草稿"]["配置"].tools = [...现];
        agent态.脏 = true; $("#fb").innerHTML = 報状态(null, true);
      };
    });
  } else if (g.Tab === "权限与限制") {
    $("#body").innerHTML = 报错块 + `<div class="card"><h4>运行限制</h4>
      ${字段("运行上限(limits)", "limits", cfg.limits, "", 5)}
      <div class="note">界面上那几个数字(回合 8 / 工具 12 / 期限 180 秒)是
        <b>设计初值</b> —— 规格 §9.6 结尾:<b>当前没有性能或模型优劣的实测结论</b>,
        真实任务要靠评测再定。人工确认场景的等待截止时间<b>不能照搬这几个秒数</b>。</div>
      </div>
      <div class="card"><h4>每条限制在哪儿被强制执行</h4>
      <table><thead><tr><th>限制</th><th>单位</th><th>强制执行位置</th>
        <th>落地了吗</th></tr></thead><tbody>`
      + g["运行限制说明"].map((l) => `<tr>
        <td><b>${esc(l["中文"])}</b><div class="k">${md(l["说明"])}</div></td>
        <td class="k">${esc(l["单位"])}</td>
        <td><code style="font-size:11px">${esc(l["强制执行位置"])}</code></td>
        <td>${l["已落地"] ? `<span class="pill ok">已落地</span>`
              : `<span class="pill warn">还没落地</span>`}</td>
      </tr>`).join("") + `</tbody></table>
      <div class="note"><b>为什么把「落地了吗」显示出来</b>:一个只存在于表单里、
        没有任何地方读的上限,<b>和没有这条限制一模一样</b> —— 而界面上它是填好的。
        标「还没落地」的那几条,现在<b>拦不住任何东西</b>。</div>
      </div>`;
  } else if (g.Tab === "调试") {
    const r = g.跑结果;
    $("#body").innerHTML = `<div class="two">
      <div class="card"><h4>本次任务</h4>
        ${字段("输入", "__输入", g.调试输入 || { products: ["甲", "乙"] }, "", 4)}
        <div class="note">输入<b>在调用前按 Schema 校验</b> ——
          §C.2「信息缺失」那一行要的是「询问或拦截,<b>不猜输入</b>」。</div>
      </div>
      <div class="card"><h4>这一次跑成什么样</h4>
        ${r ? `<div class="kpi">${esc(r["执行状态中文"] || r["执行状态"])}</div>
          <div class="k">停止原因 <code>${esc(r["停止原因"] || "—")}</code>
            · 任务达标 <b>${esc(r["任务达标"])}</b></div>
          <div class="note">${md(r["达标说明"] || "")}</div>
          <pre data-raw="原文" style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(r["输出"], null, 1))}</pre>
          <div class="k">用量 ${esc(JSON.stringify(r["用量"] || {}))}</div>
          <a href="#/wfrun/${encodeURIComponent(r.id)}">看完整运行详情 →</a>`
          : `<div class="k">还没跑过。点右上「试运行」——
              它返回 <b>202 排队中</b>,一个模型都还没调。</div>`}
      </div></div>
      <div class="card"><h4>真实回合与工具调用</h4>
      ${(g.事件 || []).length ? (g.事件 || []).map((e) => `<div style="font-size:12px">
          <span class="k">${esc(String(e.seq).padStart(2, "0"))}</span>
          <code>${esc(e["类型"])}</code>
          <span data-raw="原文" class="k">${esc(JSON.stringify(e["载荷"] || {}).slice(0, 150))}</span></div>`).join("")
        : `<div class="k">跑一次就有了。</div>`}
      <div class="note"><b>看这里能回答「它为什么没用那个工具」</b>:
        <code>agent.adapters</code> 说清接了哪些没接哪些;
        <code>tool.rejected</code> 说清被哪道闸挡了;
        <code>llm.tool_request_ignored</code> 说清「模型想调但这不是 Agent 节点」。<br>
        <b>不承诺展示模型的内部思考过程</b>(§14.3)—— 只记可观察的输入、动作、结果。</div>
      </div>`;
    const t = $("#body").querySelector('[data-k="__输入"]');
    if (t) t.onchange = () => {
      try { agent态.调试输入 = JSON.parse(t.value); }
      catch (e) { 提示("输入格式不对", `调试输入要是合法的 JSON(比如 <code>{"问题": "…"}</code>),没记下这次的改动。<br><span class="k">${esc(e.message)}</span>`); }
    };
  } else {
    $("#body").innerHTML = g["版本们"].length
      ? `<table><thead><tr><th>版本</th><th>内容哈希</th><th>变更说明</th>
          <th>冻结于</th><th>冻结人</th></tr></thead><tbody>`
        + g["版本们"].map((v) => `<tr><td><span class="pill">${esc(v["版本"])}</span></td>
            <td><code>${esc(v["内容哈希"])}</code></td>
            <td>${esc(v["变更说明"] || "")}</td>
            <td class="k">${esc((v["冻结于"] || "").slice(0, 16).replace("T", " "))}</td>
            <td class="k">${esc(v["冻结人"] || "")}</td></tr>`).join("")
        + `</tbody></table><div class="note">冻结了<b>不等于发布了</b>。
            工具和策略都固定成确切版本 —— <b>新 Agent 版本不会自动替换正在使用它的
            生产流程</b>(§3.2)。</div>`
      : `<div class="k">还没冻结过版本。</div>`;
  }
  // 表单字段回写
  $("#body").querySelectorAll("[data-k]").forEach((el) => {
    if (el.dataset.k.startsWith("__")) return;
    el.onchange = () => {
      const k = el.dataset.k, v = el.value.trim();
      const cfg2 = agent态["草稿"]["配置"];
      if (!v) { delete cfg2[k]; }
      else if (v[0] === "{" || v[0] === "[") {
        try { cfg2[k] = JSON.parse(v); }
        catch (e) { 提示("格式不对,这一项没保存", `「${esc(k)}」要是合法的 JSON。<br><span class="k">${esc(e.message)}</span>`); return; }
      } else { cfg2[k] = v; }
      agent态.脏 = true; $("#fb").innerHTML = 報状态(null, true);
    };
  });
}

async function 做_存agent() {
  try {
    const d = await 请求(`${P()}/agents/${encodeURIComponent(agent态.aid)}/draft`, {
      method: "PATCH", headers: { "If-Match": String(agent态["草稿"]["revision"]) },
      body: JSON.stringify({ 配置: agent态["草稿"]["配置"] }),
    });
    agent态["草稿"]["revision"] = d.revision;
    agent态.脏 = false;
    // 改过就把上次的校验报告作废 —— **一份对着旧配置的报告比没有报告更糟**
    agent态["草稿"]["上次校验报告"] = null;
    画_agent();
  } catch (e) {
    if (e.码 === 409) {
      const 我的 = JSON.stringify(agent态["草稿"]["配置"], null, 2);   // 11-08 用户拍:重载前把没保存的内容留给人复制
      await 路由();
      提示("别人刚改过", `${md(e.message)}<br>下一步:${md(e.体?.advice || "看一眼最新内容再改")}
        <details><summary>我这边没保存的内容(已经被最新版本盖掉,先复制下来再合并)</summary><pre class="io">${esc(我的)}</pre></details>`);
      return;
    }
    报错(e);
  }
}

async function 做_校验agent() {
  if (agent态.脏) await 做_存agent();
  try {
    agent态["草稿"]["上次校验报告"] =
      await 请求(`${P()}/agents/${encodeURIComponent(agent态.aid)}/validate`,
                { method: "POST" });
    画_agent();
  } catch (e) { 报错(e); }
}

async function 做_冻结agent() {
  const 说明 = await 问一句("生成版本", "写一句变更说明:这一版改了什么、为什么。", { 输入: "比如 收紧了退款判定,只认原路退回", 多行: true, 确定: "生成版本", 必填: true });
  if (说明 === null) return;
  if (agent态.脏) await 做_存agent();
  try {
    const d = await 请求(`${P()}/agents/${encodeURIComponent(agent态.aid)}/versions`,
      { method: "POST", body: JSON.stringify({ 变更说明: 说明 }) });
    await 路由();
    提示("版本已生成", `生成了 <b>${esc(d["版本"])}</b>。<br><span class="k">内容哈希 ${esc(d["内容哈希"].slice(0, 26))}…</span><br>${md(d.note || "")}`);
    return;
  } catch (e) {
    const b = e.体 || {};
    报错(e);
    if (b.code === "VALIDATION") return 做_校验agent();
  }
}

/* 按 JSON Schema 造一份占位输入(11-18):required 的字段按类型给最小值 —— string 给 "示例"、数字 1、布尔 false、
 * 数组给一个元素(按 items 类型)、对象递归;认不出 schema 就退回 {products:["甲","乙"]}(模板那份)。只是让「试运行」有东西可发,不是真数据 */
function 按Schema造输入(sch) {
  const 造 = (s, 深 = 0) => {
    if (!s || typeof s !== "object" || 深 > 4) return "示例";
    const t = Array.isArray(s.type) ? s.type[0] : s.type;
    if (s.enum && s.enum.length) return s.enum[0];
    if (t === "string") return "示例";
    if (t === "number" || t === "integer") return typeof s.minimum === "number" ? s.minimum : 1;
    if (t === "boolean") return false;
    if (t === "array") return [造(s.items || {}, 深 + 1)];
    if (t === "object" || s.properties) {
      const o = {};
      const 要 = (s.required && s.required.length) ? s.required : Object.keys(s.properties || {});
      要.forEach((k) => { o[k] = 造((s.properties || {})[k] || {}, 深 + 1); });
      return o;
    }
    return "示例";
  };
  if (!sch || typeof sch !== "object" || (!sch.properties && !sch.type)) return { products: ["甲", "乙"] };
  const 出 = 造(sch);
  return (出 && typeof 出 === "object" && !Array.isArray(出)) ? 出 : { products: ["甲", "乙"] };
}

async function 做_跑agent() {
  if (agent态.脏) await 做_存agent();
  // 11-18:原来写死 {products:[甲,乙]}(模板的 schema);改过 input_schema 后首跑必 422「输入不合法」。按当前 schema 生成一份占位输入
  const 输入 = agent态.调试输入 || 按Schema造输入((((agent态.草稿 || {}).配置) || {}).input_schema);   // 配置在 草稿.配置 里(接口形状)
  try {
    const d = await 请求(`${P()}/agent-runs`, {
      method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ agent_id: agent态.aid, 输入 }),
    });
    agent态.Tab = "调试"; 画_agent();
    for (let i = 0; i < 60; i++) {                       // 11-18:原来 20×600ms 只等 12 秒,真模型多轮常超过;现在 90 秒
      await new Promise((r) => setTimeout(r, 1500));
      let r;
      try { r = await 请求(`${P()}/execution-runs/${encodeURIComponent(d.resource_id)}`); }
      catch (e) { continue; }
      agent态.事件 = r["事件"] || [];
      if (r["是终态吗"]) { agent态.跑结果 = r; 画_agent(); return; }
      画_agent正文();
    }
    提示("还在跑", "等了 12 秒还没出结果。<b>这不代表它失败了</b> —— 可能后台执行程序没起来;过一会儿刷新再看。");
  } catch (e) {
    const b = e.体 || {};
    报错(e);
    if (b.code === "VALIDATION") return 做_校验agent();
  }
}

/* ── 工具目录(§11.1)──────────────────────────────────────────── */
/* ── 工具与能力:注册工具 / 改草稿 / 冻结版本 ──────────────────────────
 *
 * ⚠️ **接口不收可执行代码。** 表单上没有「代码」输入框,只有
 * 「哪个适配器 + 什么风险级别 + 什么用途」—— 适配器是**仓库里已有的实现**。
 * 这和模型连接那一页「只收引用不收明文」是同一个形状:
 * **界面上不开那个口子,而不是开了再靠后端拒。**
 *
 * ⚠️ **风险变大必须出新版本。** 改草稿时服务端会算 `风险变大了吗`,
 * 而这一页**原样显示那个结论,不自己比两个等级** ——
 * 自己比的话那条规矩就变成每个前端各实现一遍,
 * 而不一致的表现是**界面上少一句警告**。
 *
 * ⚠️ 改草稿的 `If-Match` 认 **`draft_revision`**,不是 `revision`。
 * 这两个数在工具上**一直相等**(同一个 UPDATE 里一起涨),
 * 所以拿错也不会报错 —— 运行时拦不住,只能靠 note 明说该用哪一个。
 */
const 工具动作 = {
  async 注册(体) {
    return await 请求(`${P()}/tools`,
      { method: "POST", body: JSON.stringify(体) });
  },
  async 改草稿(tid, 补丁, draft_revision) {
    if (draft_revision == null) {
      const e = new Error("这个工具读不到 draft_revision —— 工具详情应该给它");
      e.体 = { code: "NO_DRAFT_REVISION",
               advice: "刷新一次;注意**认的是 draft_revision,不是 revision**" };
      e.码 = 0;
      throw e;
    }
    return await 请求(`${P()}/tools/${encodeURIComponent(tid)}/draft`,
      { method: "PATCH", headers: { "If-Match": String(draft_revision) },
        body: JSON.stringify(补丁) });
  },
  async 冻结版本(tid, 体) {
    // ⚠️ **冻结是另一张表单,不是一个按钮。** 闸要的是:
    // 给模型的说明、入参 schema、(会写的工具还要)幂等策略。
    // 第一版我只传了一个「变更说明」—— 而**这条接口压根不收那个字段**,
    // 它是个摆设。一个被静默忽略的入参,和一个生效了的入参,
    // **在响应上长得一模一样**。
    return await 请求(`${P()}/tools/${encodeURIComponent(tid)}/versions`,
      { method: "POST", body: JSON.stringify(体 || {}) });
  },
};
if (typeof globalThis !== "undefined") globalThis.工具动作 = 工具动作;
/* ⚠️ **把 `画工具详情` 也暴露出来 —— 为了能验「页面上印了什么」。**
 *
 * 现有七个驱动测试都只能验**动作**(点了按钮会发什么请求),验不了**渲染**。
 * 而第三份规格 §8.2 那七个页签全是渲染内容 ——
 * 不暴露一个能真渲一遍的入口,那一阶段就只能靠「页面跑通了」那种粗判据,
 * 而**「渲染了」不等于「渲的是那些东西」**。
 *
 * 只暴露这一个(不是整个路由):路由会把 hash 和历史也带进来,
 * 而那会让测试去管一堆和它要验的事无关的状态。 */
if (typeof globalThis !== "undefined") globalThis.画工具详情 = 画工具详情;

function 页_工具表单(d) {
  const 能改 = 我的角色 === "editor" || 我的角色 === "admin";
  if (!能改) {
    return `<div class="note">注册工具要「改编排草稿」这条能力 ——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>。</div>`;
  }
  const 级们 = d["可选读写类型"] || [];
  const 接 = d["接入方式怎么填"] || {};
  const 快捷 = (接["这个项目已经在用的"] || [])
    .map((a) => `<button data-tfill="${esc(a)}" class="k">${esc(a)}</button>`).join(" ");
  return `<div class="state">
    <h3>注册一个工具</h3>
    <p class="k">${md(接["⚠️"] || "")}</p>
    <p><label>名称<br><input id="t-name" style="width:min(320px,90%)"></label></p>
    <p><label>用途（给模型看的说明）<br>
      <input id="t-purpose" style="width:min(420px,90%)"></label></p>
    <p><label>读写类型<br><select id="t-se">${
      级们.map((x) => `<option value="${esc(x["值"])}">${esc(x["中文"])}（${
        esc(x["值"])}）</option>`).join("")}</select></label>
      <br><span class="k">⚠️ <b>没标级别的工具一律被网关挡住</b>（未知不等于安全）</span></p>
    <p><label>接入方式（适配器名）<br>
      <input id="t-ad" style="width:min(320px,90%)" placeholder="MockSearch"></label>
      <br>${快捷 ? `<span class="k">已经在用的：</span>${快捷}` : ""}</p>
    <p class="k">⚠️ <b>这里没有「代码」输入框</b> ——
      接口<b>不收可执行代码</b>,适配器是仓库里已有的实现。</p>
    <p><button class="pri" id="t-go">注册</button></p></div>`;
}

async function 页_工具详情(tid) {
  $("#main").innerHTML = `<div class="crumb">集成 /
      <a href="#/integrations/tools">工具</a> / 详情</div>
    <div class="head"><div><h1 id="tt">工具</h1>
      <div class="sub"><b>草稿改不动已经冻结的版本</b> ——
        而引用这个工具的 Agent 认的是<b>版本</b>,不是草稿。</div></div></div>
    <div id="tdmsg"></div>
    <div id="tdbody"><div class="state">加载中…</div></div>`;
  await 画工具详情(tid);
}

async function 画工具详情(tid) {
  try {
    const [d, 目录] = await Promise.all([
      请求(`${P()}/tools/${encodeURIComponent(tid)}`),
      请求(`${P()}/tools`),
    ]);
    $("#tt").textContent = d["名称"] || tid;
    const 草 = d["草稿"] || {};
    const 版本们 = d["版本历史"] || [];
    const 级们 = 目录["可选读写类型"] || [];
    const 能改 = 我的角色 === "editor" || 我的角色 === "admin";
    // ⚠️ **风险变大这个结论由服务端给,这一页只负责显示。**
    // 自己比两个等级的话,那条规矩就变成每个前端各实现一遍,
    // 而不一致的表现是**界面上少一句警告**。
    // ⚠️ **校验器真支持的 Schema 关键字,从接口拿 —— 不在这里硬编。**
    //
    // 规格 §8.3 最后一句:「首版不能默认任意 JSON Schema 都被支持;
    // **界面必须用真实能力清单校验,不能静默忽略约束**」。
    //
    // 10-02 后端已经给出 `可用的Schema关键字` 和一句「别硬编」——
    // 而在这一段之前**没有任何界面在用它**。
    // > 一个给出来却没人用的字段,和没给,**在界面上长得一样**。
    //
    // 硬编一份的坏处很具体:它会和后端漂,而漂开时
    // 界面放过去的 Schema 会在**模型第一次真的调用**那一刻才失败 ——
    // 报出来是「工具调用失败」,不是「这个 Schema 当初就不该被接受」。
    const 关键字 = d["可用的Schema关键字"] || [];
    const 关键字区 = 关键字.length
      ? `<div class="note"><b>这个校验器只认这 ${关键字.length} 个关键字</b>
          （从接口取，<b>界面不硬编</b> —— 硬编的那份会和后端漂）：<br>
          ${关键字.map((k) => `<code>${esc(k)}</code>`).join(" ")}
          <br><span class="k">⚠️ 用别的关键字<b>冻结时就会被拦</b>（422）——
            这是有意的：不拦的话它会在<b>模型第一次真的调用</b>那一刻才失败，
            而那时报出来是「工具调用失败」。</span></div>`
      : `<div class="note warn">⚠️ <b>接口没给「可用的Schema关键字」</b> ——
          那这一页就没法替你先挡一遍。<b>这不是「随便填都行」</b>：
          冻结时服务端仍然会拦，只是你要到那一步才知道。</div>`;
    // ── 规格 §8.2 的「输入与输出」+「执行与权限」两页 ────────────────
    //
    // ⚠️ **只渲最新那一版。** 规格那张表把它们画成两个独立页签,
    // 而首版不做页签切换:七个页签里有三个要还没实现的接口
    // (配套关系要 `companion_map`、引用与运行要查哪些 Agent 引用它)——
    // **摆七个壳子、三个是空的,比摆两个满的糟**:
    // 空页签让人以为「这里没东西」,而真相是「这里还没做」。
    // 没做的那几个在下面**明写未实现**(仓库的规矩:
    // 「还没实现的入口保留但标未实现,不藏起来」)。
    const 新版 = 版本们[0] || null;
    const 看得到原文 = 能力.includes("查看敏感输入/独立测试答案");
    const JSON块 = (o) => o
      ? `<pre data-raw="原文" style="margin:4px 0;padding:6px 8px;background:#f7f8fa;
           border-left:3px solid var(--faint);font-size:11.5px;
           overflow:auto;max-height:200px">${esc(
             JSON.stringify(o, null, 1))}</pre>`
      : `<span class="k">—</span>`;
    // ⚠️ **这一段必须在模板之前定义。**
    // `const` 不会提升 —— 第一版我把它插在模板之后,渲染当场抛,
    // 表现是**九条内容断言一起红**,而**没有一条指向真因**。
        const 组们 = (新版 && (新版["谁在用它"] || {})["在哪些组里"]) || [];
    const 配套区 = !新版 ? "" : `
      <h2>最新版本 · 配套关系</h2>
      ${组们.length === 0
        ? `<div class="note">这个版本<b>不在任何工具组里</b>。
            <br>⚠️ <b>这不等于「它没有配套」</b> —— 配套关系是
            <b>在组里</b>定的（同一个工具可以在 A 组里配着 X、
            在 B 组里配着 Y）。不在组里，就还没人给它定过搭配。</div>`
        : `<table><thead><tr><th>在哪个组</th><th>这一轮必须给它吗</th>
            <th>给它就得一起给谁</th><th>谁被给了就得带上它</th>
            </tr></thead><tbody>`
          + 组们.map((g) => `<tr>
              <td><b>${esc(g["组名"] || g["组id"])}</b>
                <span class="k">v${esc(g["组版本"])}</span></td>
              <td>${g["这一轮必须给它吗"] === null
                ? `<span class="k">算不出来 ——
                    <b>别读成「不是必需的」</b></span>`
                : g["这一轮必须给它吗"]
                  ? `<span class="pill warn">必不可少</span>
                     <span class="k">预算先放它</span>`
                  : `<span class="pill">可选</span>`}
                ${g["加载角色"] ? `<span class="k">·
                  ${esc(g["加载角色"])}</span>` : ""}</td>
              <td class="k">${(g["给它就得一起给谁"] || []).length
                ? (g["给它就得一起给谁"] || []).map(esc).join("、")
                : "—"}</td>
              <td class="k">${(g["谁需要它一起"] || []).length
                ? (g["谁需要它一起"] || []).map(esc).join("、")
                : "—"}</td></tr>`).join("")
          + `</tbody></table>`}
      <div class="note">⚠️ <b>「必不可少」和「配套」是两件事</b>：
        前者是<b>这一轮必须给它</b>，后者是<b>给它就得一起给谁</b>。
        混起来的话，一个「可选但有配套」的工具会被当成必需的，
        <b>于是预算在它身上先花掉</b> —— 而那不是它该占的位置。
        <br>⚠️ <b>「添加配套」「检查依赖」两个按钮还没做</b> ——
        配套关系在<a href="#/integrations/groups">集成 / 工具组</a>里<b>冻结工具组版本</b>时给（那里有成环检查）。</div>`;
    // ── 规格 §8.2「模型说明」页签(2026-10-03)─────────────────────
    //
    // ⚠️⚠️ **三态从接口拿(`模型说明填了吗`),不在这里自己判。**
    // 这一页上 `null` 和 `[]` 是**两件不同的事**:
    //   · `null` = 没人说过      → 「待补」(这个页签要消灭的状态)
    //   · `[]`   = 有人看过、确认不需要 → 「已确认不需要」(**已经做完了**)
    // 而它们在 JavaScript 里**都是 falsy** —— 一句
    // `if (!别名) 显示「待补」` 会把后者也渲染成待补,
    // 于是「还有几个工具没人填过别名」这个数**永远填不完**,
    // 而那是衡量这件事做完没做完的唯一指标。
    //
    // ⚠️ 「预览模型所见内容」显示的是接口给的 `模型所见内容` ——
    // 它由 `agent_loop` 真跑时用的那同一个函数算出来。
    // **这一页绝不自己把几栏拼一遍当预览**:那是第二份实现,
    // 它会和真正发出去的那一段漂,而漂开的表现是
    // 「后台显示的」和「模型收到的」分家。
    const 态牌 = (t) => t === "没说过"
      ? `<span class="pill warn">待补</span>`
      : t === "确认不需要"
        ? `<span class="pill">已确认不需要</span>`
        : `<span class="pill ok">${esc(t || "")}</span>`;
    const 串串 = (xs) => (xs || []).length
      ? `<ul style="margin:4px 0 0 18px;padding:0">`
        + xs.map((x) => `<li>${esc(String(x))}</li>`).join("") + `</ul>`
      : `<span class="k">—</span>`;
    const 模型说明区 = !新版 ? "" : `
      <h2 style="display:flex;align-items:center;gap:10px">
        最新版本（${esc(新版["版本"])}）· 模型说明
        <button id="d-preview" style="font-size:12px;font-weight:400">
          预览模型所见内容</button></h2>
      <table><tbody>
        <tr><td class="k" style="width:120px">模型可见名称</td>
          <td><code>${esc(d["名称"] || "")}</code>
            <span class="k">模型按这个名字调它</span></td></tr>
        <tr><td class="k">描述</td>
          <td data-raw="原文">${esc(新版["给模型的说明"] || "—")}</td></tr>
        <tr><td class="k">别名
            ${态牌((新版["模型说明填了吗"] || {})["别名"])}</td>
          <td>${串串(新版["别名"])}
            ${(新版["模型说明填了吗"] || {})["别名"] === "没说过"
              ? `<div class="note warn">⚠️ <b>没人填过别名</b> ——
                  10-03 量到的病根就在这儿:<b>用户问的是业务，工具说明写的是系统</b>。
                  五道题的「需要的工具」和「用户的问法」<b>一个共同片段都没有</b>
                  （「还能发几件」对「查现货」）。<br>
                  <b>确认它真的不需要别名</b>的话，填一个空的一串 ——
                  那和「没人填过」在库里是两个不同的状态。</div>`
              : ""}</td></tr>
        <tr><td class="k">适用场景
            ${态牌((新版["模型说明填了吗"] || {})["适用不适用"])}</td>
          <td>${串串((新版["适用不适用"] || {})["适用"])}</td></tr>
        <tr><td class="k">不适用场景</td>
          <td>${串串((新版["适用不适用"] || {})["不适用"])}
            <div class="note">⚠️ <b>「不适用」不许单独空着</b> ——
              只写「适用」的话，「不适用」会<b>静默变成「没说过」</b>，
              而一个没说过不适用的工具，和一个处处适用的工具，
              <b>在模型眼里长得一模一样</b>。冻结时会拦（422）。</div></td></tr>
        <tr><td class="k">任务示例
            ${态牌((新版["模型说明填了吗"] || {})["任务示例"])}</td>
          <td>${(新版["任务示例"] || []).length
            ? `<table><thead><tr><th>真实问法</th><th>来路</th></tr></thead><tbody>`
              + (新版["任务示例"] || []).map((x) => `<tr>
                  <td>${esc(x["问法"] || "")}</td>
                  <td>${x["来源"] === "现编"
                    ? `<span class="pill warn">现编</span>
                       <span class="k">不能当评测真值</span>`
                    : `<span class="pill">${esc(x["来源"] || "")}</span>`}</td>
                  </tr>`).join("") + `</tbody></table>`
            : `<span class="k">—</span>`}
            <div class="note">⚠️ <b>每条都要带来路</b>（记录仪 / 业务口述 / 现编）。
              不带的话，一条编的例子和一条真实问法在这张表里长得一样 ——
              而 10-03 栽过：拿反推出来的别名跑出 21/21，<b>那是先看答案再出题</b>。</div>
          </td></tr>
      </tbody></table>
      <div class="note">⚠️ <b>这三样在澜绣那边维护，这一页只读</b>
        （2026-10-03 业务拍的）。真值在 <code>backend/工具模型说明.json</code>，
        靠导入带进后台。<br>
        <b>为什么不在这儿填</b>：① 这一页冻结出来的版本，内容哈希算法和导入那套
        <b>永远不可能相等</b> —— 同步判据会红，而它报的理由是
        「内容不一致，去跑导入」，指向一个错方向；
        ② 在这儿填的东西<b>澜绣线上读不到</b>（澜绣不从后台的库读工具说明）——
        那会出现「后台上看起来配好了，而线上一个字没变」。</div>
      <div id="preview-box" style="display:none">
        <h2>模型实际收到的那一段</h2>
        <pre data-raw="原文" style="margin:4px 0;padding:8px 10px;background:#f7f8fa;
          border-left:3px solid var(--ok,#2a7);font-size:12px;white-space:pre-wrap;
          overflow:auto;max-height:320px">${esc(新版["模型所见内容"] || "")}</pre>
        <div class="note">⚠️ 这一段<b>不是这一页拼的</b> —— 它由
          <code>capabilities.模型看到的工具</code> 算出来，
          而 <b>Agent 真跑时发给模型的就是同一个函数的返回</b>。<br>
          所以这里看到的就是模型看到的：<b>上面填的别名如果没出现在这一段里，
          那就是填了等于没填</b>。</div></div>`;
    const 最新版区 = !新版 ? "" : `
      <h2>最新版本（${esc(新版["版本"])}）· 输入与输出</h2>
      <table><tbody>
        <tr><td class="k">给模型的说明</td>
          <td data-raw="原文">${esc(新版["给模型的说明"] || "—")}</td></tr>
        <tr><td class="k">入参 schema</td><td>${JSON块(新版["入参"])}</td></tr>
        <tr><td class="k">出参 schema</td><td>${JSON块(新版["出参"])}
          ${新版["出参"] ? "" : `<span class="k">没声明出参 ——
            <b>「工具返回了什么」就只能靠读结果猜</b></span>`}</td></tr>
        <tr><td class="k">服务端绑定的参数</td><td>${
          看得到原文 ? JSON块(新版["服务端绑定的参数"])
          : `<span class="k">按权限脱敏（要「查看敏感输入」这条专项授权）</span>`}
          <div class="note">⚠️ <b>单独一栏，不和入参混在一张表里</b> ——
            模型看不到也改不了这些。并排摆会让人以为它们一样，
            于是有人把该服务端绑的字段写进入参 schema，
            <b>那一刻模型就能覆盖它了</b>。</div></td></tr>
      </tbody></table>
      <h2>最新版本 · 执行与权限</h2>
      <table><tbody>
        <tr><td class="k">读写类型</td><td>${esc(新版["读写类型"] || "—")}</td></tr>
        <tr><td class="k">连接</td><td>${新版["连接"]
          ? `<code>${esc(新版["连接"])}</code>` : `<span class="k">没绑连接</span>`}
          ${新版["配了凭据吗"]
            ? `<span class="pill ok">配了凭据</span>`
            : `<span class="pill">没配凭据</span>`}
          <span class="k">—— <b>只报配了没配，凭据本身不出返回值</b></span></td></tr>
        <tr><td class="k">对象范围</td><td>${JSON块(新版["对象范围"])}
          ${新版["对象范围"] ? "" : `<span class="k">没限范围 ——
            <b>那它能碰的就是适配器能碰的全部</b></span>`}</td></tr>
        <tr><td class="k">确认策略</td><td>${JSON块(新版["确认策略"])}</td></tr>
        <tr><td class="k">幂等策略</td><td>${JSON块(新版["幂等策略"])}
          ${新版["幂等策略"] ? "" : `<span class="k">没声明 ——
            <b>超时重发会把同一件事做两遍</b></span>`}</td></tr>
        <tr><td class="k">超时</td><td>${新版["超时秒"] != null
          ? esc(新版["超时秒"]) + " 秒" : `<span class="k">没设</span>`}</td></tr>
        <tr><td class="k">重试策略</td><td>${JSON块(新版["重试策略"])}</td></tr>
        <tr><td class="k">脱敏</td><td>${JSON块(新版["脱敏"])}
          ${新版["脱敏"] ? "" : `<span class="k">没声明 ——
            <b>这个工具的参数和返回会原样进 Trace 和导出</b></span>`}</td></tr>
        <tr><td class="k">能轮询吗</td><td>${新版["能轮询吗"] ? "能"
          : `<span class="k">没声明 —— 「调用两次」会被当成无进展</span>`}</td></tr>
        <tr><td class="k">查外部状态</td><td>${JSON块(新版["查外部状态"])}</td></tr>
      </tbody></table>
      <h2>最新版本 · 引用与运行</h2>
      <table><tbody>
        <tr><td class="k"><b>在生产上吗</b></td>
          <td>${(新版["谁在用它"] || {})["在生产上吗"]
            ? `<span class="pill fail">在生产上</span>
               <b>停用它会当场影响线上</b>`
            : `<span class="pill ok">不在生产上</span>
               <span class="k">—— 但下面那些引用仍然要看</span>`}
          <div class="note">走的是 <b>环境指针 → 发布清单 → Agent 版本</b>，
            不是「哪些清单记了它」——
            <b>一份三个月前回滚掉的清单照样记着它</b>。
            ⚠️ 2026-10-02 之前发布清单<b>没有 Agent 版本那一列</b>，
            所以那之前的清单这一栏算不出来（它们不计入，
            <b>join 不上就是没绑 Agent</b>）。</div></td></tr>
        <tr><td class="k">被 Agent 版本引用</td>
          <td><b>${esc((新版["谁在用它"] || {})["Agent 版本"] ?? "—")}</b> 个
          ${((新版["谁在用它"] || {})["Agent 版本"] || 0) > 0
            ? `<span class="k">—— <b>停用它之前要先看这些</b></span>` : ""}</td></tr>
        <tr><td class="k">被工具组版本引用</td>
          <td>${esc((新版["谁在用它"] || {})["工具组版本"] ?? "—")} 个</td></tr>
        <tr><td class="k">被真实运行加载过</td>
          <td>${esc((新版["谁在用它"] || {})["被加载过几次"] ?? "—")} 次
            <span class="k">—— <b>「被引用」和「真被加载过」是两件事</b>：
              前者是配置，后者是这个工具<b>真的进过模型输入</b></span></td></tr>
      </tbody></table>
      ${(d["⚠️在生产上吗怎么算的"] || d["⚠️答不出的"]) ? `<div class="note warn">⚠️ <b>「在生产上吗」是怎么算的</b>：
        ${md(d["⚠️在生产上吗怎么算的"] || d["⚠️答不出的"])}</div>` : ""}
      ${配套区}
      <div class="note"><b>规格 §8.2 那七个页签都在了</b>（模型说明那一页 11-14 补的：别名 / 适用不适用 / 任务示例）。
        <b>还没做的</b>：「添加配套」「检查依赖」两个按钮 —— <b>缺的是</b>从这一页直接把配套关系落到工具组版本上的入口；配套关系现在在<a href="#/integrations/groups">集成 / 工具组</a>里冻结版本时给（11-18 起有这一页了）。</div>`;
    // ── 规格 §8.2「版本与差异」:**哈希不同只说明改了,不说明改了什么** ──
    //
    // 这一页的价值不是「告诉你两版不一样」—— 内容哈希已经告诉你了。
    // 是**指出哪几个字段变了**,因为不同的变化对引用方后果完全不同:
    //   · 风险变大(只读 → 会写)→ 引用它的 Agent 还指着老说明,
    //     **而那份说明现在是错的**
    //   · Schema 变了 → 模型按老 schema 传参会被拒
    //   · 只是说明改了 → 引用方不用动
    //
    // ⚠️ **只比最新两版。** 规格那张表写的是「对比版本」(任选两版),
    // 而首版做「最新 vs 上一版」—— 那是**冻结之后最常问的那个问题**。
    // 任选两版要一个选择器,而选择器做了之后这一段还是现在这套比较逻辑,
    // 所以先把比较做对。**没做的那半在下面明写着。**
    const 比字段 = [
      ["读写类型", "读写类型", "**风险变了** —— 引用它的 Agent 还指着老说明"],
      ["给模型的说明", "给模型的说明", "模型靠它决定要不要调这个工具"],
      ["入参", "入参 schema", "**模型按老 schema 传参会被拒**"],
      ["出参", "出参 schema", "读结果的人按老结构解析会读错"],
      ["对象范围", "对象范围", "**它能碰的东西变了**"],
      ["确认策略", "确认策略", "要不要人点头变了"],
      ["幂等策略", "幂等策略", "超时重发的行为变了"],
      ["超时秒", "超时", ""],
      ["脱敏", "脱敏", "**进 Trace 和导出的内容变了**"],
      ["连接", "连接", "它走哪条连接变了"],
      ["配了凭据吗", "凭据", "配没配凭据变了"],
      ["能轮询吗", "能轮询吗", "「调用两次算不算无进展」变了"],
    ];
    const 上版 = 版本们[1] || null;
    const 同吗 = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    const 变了的 = (新版 && 上版)
      ? 比字段.filter(([k]) => !同吗(新版[k], 上版[k]))
      : [];
    const 版本差异区 = !(新版 && 上版) ? (版本们.length === 1
      ? `<h2>版本差异</h2><div class="note">只有一版，没有可比的上一版。
          <b>这不是「没有差异」</b> —— 是还没有第二版。</div>` : "")
      : `<h2>版本差异（${esc(上版["版本"])} → ${esc(新版["版本"])}）</h2>
      ${变了的.length === 0
        ? `<div class="note warn">${md(`⚠️ <b>这两版的内容哈希不同，而上面这些字段逐个比下来都一样</b>。
            说明改的是**这张表没列出来的东西**（比如重试策略、
            服务端绑定参数、查外部状态）——
            <b>别读成「没改」</b>：哈希是按全部字段算的。`)}</div>`
        : `<table><thead><tr><th>变了什么</th>
            <th>${esc(上版["版本"])}</th><th>${esc(新版["版本"])}</th>
            <th>对引用方意味着什么</th></tr></thead><tbody>`
          + 变了的.map(([k, 名, 后果]) => `<tr>
              <td class="k"><b>${esc(名)}</b></td>
              <td>${JSON块(上版[k])}</td>
              <td>${JSON块(新版[k])}</td>
              <td class="k">${md(后果 || "—")}</td></tr>`).join("")
          + `</tbody></table>`}
      <div class="note"><b>内容哈希不同只说明改了，不说明改了什么</b> ——
        所以这一页比的是字段，不是哈希。
        <br>⚠️ <b>只比最新两版</b>（规格那张表写的是「对比版本」，
        任选两版还没做）；<b>「基于此版建草稿」也还没做</b>。</div>`;
    // ── 规格 §8.2「配套关系」:**「必不可少」和「配套」是两件事** ──────
    //
    // ⚠️ 配套关系存在**工具组版本**里,不在工具版本上 ——
    // 所以这一页回答的是:**这个工具在哪些组里,而在那些组里它配着谁。**
    //
    // ⚠️⚠️ 两件事别混:
    //   · `必不可少吗` = **这一轮必须给它**(A-5 的预算先放必需的)
    //   · 配套 = **给它就得一起给谁**
    // 混起来的话,一个「可选但有配套」的工具会被当成必需的,
    // 于是预算在它身上先花掉 —— **而那不是它该占的位置**。
    const 风险警告 = d["风险变大了吗"]
      ? `<div class="note warn"><b>⚠️ 草稿比最新冻结版风险更大</b> ——
          冻结时<b>必须出新版本</b>:引用它的 Agent 还指着老说明,
          <b>而那份说明现在是错的</b>。</div>`
      : "";
    $("#tdbody").innerHTML = `${风险警告}
      <h2>草稿</h2>
      <table><tbody>
        <tr><td class="k">用途</td><td>${能改
          ? `<input id="d-purpose" data-raw="原文" style="width:min(420px,90%)"
              value="${esc(草["用途"] || "")}">`
          : esc(草["用途"] || "—")}</td></tr>
        <tr><td class="k">读写类型</td><td>${能改
          ? `<select id="d-se">${级们.map((x) => `<option value="${esc(x["值"])}"${
              x["值"] === 草["读写类型"] ? " selected" : ""}>${esc(x["中文"])}（${
              esc(x["值"])}）</option>`).join("")}</select>`
          : esc(草["读写类型中文"] || 草["读写类型"] || "—")}</td></tr>
        <tr><td class="k">接入方式</td><td><code>${esc(草["接入方式"] || "—")}</code>
          <span class="k">（接口不收可执行代码，这里也不给改）</span></td></tr>
        <tr><td class="k">草稿版本号 <span title="字段名">(draft_revision)</span></td>
          <td><code>${esc(d["draft_revision"])}</code>
            <span class="k">—— <b>改草稿的 If-Match 认这个</b>，不是下面那个
              <code>revision</code>（${esc(d["revision"])}）。
              这两个数现在<b>一起涨、一直相等</b>，<b>所以拿错也不会报错</b> ——
              运行时拦不住，只能靠这句话拦。</span></td></tr>
      </tbody></table>
      ${能改 ? `<p><button class="pri" id="d-save">保存草稿</button></p>
        <h2>冻结成新版本</h2>
        <div class="note">⚠️ <b>冻结固化的是「给模型看的那一份」</b> ——
          模型靠说明决定要不要调这个工具，靠 schema 知道传什么。
          <b>这些不在草稿里</b>（草稿管的是名字/用途/风险级别/适配器），
          每次冻结都要重新给 —— 因为<b>它们是版本的内容，不是工具的属性</b>。</div>
        <p><label>给模型的说明（<b>必填</b>）<br>
          <textarea id="f-desc" rows="2" style="width:min(520px,95%)" data-raw="原文"
            >${esc(草["用途"] || "")}</textarea></label>
          <br><span class="k">没有它，模型只能靠工具名猜</span></p>
        <p><label>入参 schema（<b>必填</b>，JSON）<br>
          <textarea id="f-in" rows="3" style="width:min(520px,95%)"
            >{"type":"object","properties":{}}</textarea></label>
          <br><span class="k">没有它，「模型传错了参数」和「工具自己坏了」分不开</span></p>
        <p><label>出参 schema（可不填，JSON）<br>
          <textarea id="f-out" rows="2" style="width:min(520px,95%)"></textarea></label></p>
        ${关键字区}
        <p><label>幂等策略（<b>会写的工具必填</b>）<br>
          <input id="f-idem" style="width:min(420px,90%)"
            placeholder="按 (工具, 对象, 执行键) 去重"></label></p>
        <p><button class="pri" id="d-freeze">冻结</button></p>`
        : `<div class="note">改草稿 / 冻结要「改编排草稿」这条能力 ——
          你现在是 <b>${esc(我的角色 || "?")}</b>，<b>所以这里不摆按钮</b>。</div>`}
      ${模型说明区}
      ${最新版区}
      ${版本差异区}
      <h2>版本历史（${版本们.length}）</h2>
      <table><thead><tr><th>版本</th><th>读写类型</th><th>确认策略</th>
        <th>能轮询吗</th><th>内容哈希</th><th>冻结</th></tr></thead><tbody>`
      + (版本们.length ? 版本们.map((v) => `<tr>
          <td><b>${esc(v["版本"])}</b></td>
          <td>${esc(v["读写类型"])}</td>
          <td class="k">${_策略文(v["确认策略"])}</td>
          <td class="k">${v["能轮询吗"] ? "能" : `<span class="k">没声明</span>`}</td>
          <td><code style="font-size:11px">${esc(
            String(v["内容哈希"] || "").slice(0, 12))}</code></td>
          <td class="k">${esc(String(v["冻结时间"] || "").slice(0, 19))}
            · ${esc(v["冻结的人"] || "")}</td></tr>`).join("")
        : `<tr><td colspan="6" class="k">还没冻结过版本 ——
            <b>没有版本的工具,Agent 引用不了</b></td></tr>`)
      + `</tbody></table>
      <div class="note">${md(d.note || "")}</div>`;
    if ($("#d-save")) {
      $("#d-save").onclick = async () => {
        $("#d-save").disabled = true; 报工具("保存草稿…");
        try {
          const r = await 工具动作.改草稿(tid, {
            用途: ($("#d-purpose").value || "").trim() || null,
            读写类型: $("#d-se").value,
          }, d["draft_revision"]);
          报工具(`改好了(draft_revision ${esc(r["draft_revision"])})`
            + `${r["风险变大了吗"] ? " —— **风险变大了,冻结时必须出新版本**" : ""}`
            + `${md(r.note ? "。" + r.note : "")}`);
          await 画工具详情(tid);
        } catch (e) { 报工具(闸文(e), true); $("#d-save").disabled = false; }
      };
    }
    // 规格 §8.2:区域右上「预览模型所见内容」。
    // ⚠️ 它**只是展开/收起**已经拿到的那一段 —— 不另发请求、不在这里拼。
    // 再发一次请求的话,「预览」和「页面上显示的」会是两个时刻的数据,
    // 而那种不一致只在别人同时改了它的那一刻出现(查都查不出来)。
    if ($("#d-preview")) {
      $("#d-preview").onclick = () => {
        const 盒 = $("#preview-box");
        const 开 = 盒.style.display === "none";
        盒.style.display = 开 ? "" : "none";
        $("#d-preview").textContent = 开 ? "收起预览" : "预览模型所见内容";
        if (开) 盒.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
    }
    if ($("#d-freeze")) {
      $("#d-freeze").onclick = async () => {
        $("#d-freeze").disabled = true; 报工具("冻结…");
        try {
          // ⚠️ JSON **在这儿解析,解析不了就当场说** ——
          // 直接把字符串发出去的话,服务端会回「入参 schema 没给」,
          // 而那句话让人以为是没填,真相是**填了但不是合法 JSON**。
          const 读json = (id, 名) => {
            const t = ($(id).value || "").trim();
            if (!t) return null;
            try { return JSON.parse(t); } catch (e2) {
              const err = new Error(`${名}不是合法 JSON:${e2.message}`);
              // ⚠️ JS 不像 Python 会自动拼相邻字符串 —— 少一个 `+` 就是语法错。
              err.体 = { code: "BAD_JSON",
                         advice: "**这是本地解析失败,还没发出去** —— "
                                 + "和服务端说「没给」不是一回事" };
              err.码 = 0;
              throw err;
            }
          };
          const 体 = {
            给模型的说明: ($("#f-desc").value || "").trim(),
            入参: 读json("#f-in", "入参 schema"),
            出参: 读json("#f-out", "出参 schema"),
            幂等策略: ($("#f-idem").value || "").trim() || null,
          };
          const r = await 工具动作.冻结版本(tid, 体);
          报工具(`冻结了 ${esc(JSON.stringify(r).slice(0, 160))}`);
          await 画工具详情(tid);
        } catch (e) { 报工具(闸文(e), true); $("#d-freeze").disabled = false; }
      };
    }
  } catch (e) {
    const s = 错误块(e, () => 画工具详情(tid));
    $("#tdbody").innerHTML = s.html; s.挂();
  }
}

function 报工具(文, 坏) {
  if ($("#tdmsg")) {
    $("#tdmsg").innerHTML = 文
      ? (坏 ? `<div class="state err">` : `<div class="state">`) + `<p>${md(文)}</p></div>` : "";
  }
}

// W38(11-17):工具目录里标出业务后台那边的开关 —— 管理后台说「有这个工具」,业务后台说「现在不放行」,两边一直对不上账;
// 接口的 `业务后台` 为 null = 不是业务后台的工具(不标);读到了吗=false = 那边的库读不到(明说,不装作全启用)
function 业务后台标(x) {
  if (!x) return "";
  if (x["读到了吗"] === false) return ` <span class="pill" title="业务后台的开关库读不到,这里不知道它放不放行">业务后台:未知</span>`;
  const 出 = [];
  if (x["启用"] === false) 出.push(`<span class="pill warn" title="业务后台里已停用:Agent 选不到它,目录里仍然有">业务后台已停用</span>`);
  if (x["限流每分钟"]) 出.push(`<span class="pill" title="业务后台里限了流">业务后台限流 ${esc(String(x["限流每分钟"]))}/分</span>`);
  return 出.length ? " " + 出.join(" ") : "";
}

async function 页_工具目录() {
  $("#main").innerHTML = `<div class="crumb">集成 / 工具</div>
    <div class="head"><div><h1>工具目录</h1>
      <div class="sub"><b>未注册的工具名一律拒绝</b>(§9.4)——
        不能让模型凭一个名字临时发网络请求。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/tools`);
    if (!d.items.length) {
      $("#list").innerHTML = 状态("", "还没有注册工具",
        "`make seed-demo` 会灌两个演示工具(搜索 / 写报告)。").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>名称</th><th>用途</th>
      <th>读写类型</th><th>接入方式</th><th>最新版本</th><th>状态</th>
      </tr></thead><tbody>`
      + d.items.map((r) => `<tr>
        <td><a href="#/tool/${encodeURIComponent(r.id)}"><b>${esc(r["名称"])}</b></a>
          </td><td data-raw="原文">${esc(r["用途"] || "—")}</td>
        <td>${r["读写类型"] === "只读" ? `<span class="pill">只读</span>`
              : `<span class="pill warn">${esc(r["读写类型"])}</span>`}</td>
        <td class="k">${esc(r["接入方式"])}</td>
        <td>${r["最新版本"] ? `<span class="pill">${esc(r["最新版本"])}</span>`
              : `<span class="k">还没冻结版本</span>`}</td>
        <td class="k">${esc(r["状态"])}${业务后台标(r["业务后台"])}</td></tr>`).join("")
      + `</tbody></table>
      <div class="note">工具执行只走<b>一个入口</b>(工具网关),门上六道闸:
        注册 → 服务端绑定 → Schema → 对象范围 → 确认 → 幂等。<br>
        <b>点工具名进详情</b>可以改草稿、冻结版本。
        注册在下面 —— <code>POST /tools</code> <b>不收可执行代码</b>,
        只收「哪个适配器 + 什么风险级别 + 什么用途」。</div>`
      + `<div id="tmsg"></div>` + 页_工具表单(d);
    挂工具表单();
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 挂工具表单() {
  document.querySelectorAll("[data-tfill]").forEach((b) => {
    b.onclick = () => { if ($("#t-ad")) $("#t-ad").value = b.dataset.tfill; };
  });
  if (!$("#t-go")) return;
  $("#t-go").onclick = async () => {
    const 体 = {
      名称: ($("#t-name").value || "").trim(),
      用途: ($("#t-purpose").value || "").trim() || null,
      读写类型: $("#t-se").value,
      接入方式: ($("#t-ad").value || "").trim(),
    };
    $("#t-go").disabled = true;
    if ($("#tmsg")) $("#tmsg").innerHTML = `<div class="state"><p>注册中…</p></div>`;
    try {
      const r = await 工具动作.注册(体);
      // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
      await 页_工具目录();
      if ($("#tmsg")) {
        $("#tmsg").innerHTML = `<div class="state"><p>注册好了
          <code>${esc(r.id || "")}</code> —— ${md("**下一步是冻结一个版本**")}:
          草稿改不动已经冻结的版本,而引用它的 Agent 认的是版本
          ${md(r.note ? "。" + r.note : "")}</p></div>`;
      }
    } catch (e) {
      if ($("#tmsg")) $("#tmsg").innerHTML = 错误块(e, null).html;
      $("#t-go").disabled = false;
    }
  };
}

/* ── 路由 ─────────────────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════
 * 知识与 RAG(规格 §9)
 *
 * ## 这两页要回答的问题不一样
 *
 *   知识库    「资料进来了没有、索引建好了没有、**现在能不能检索**」
 *   检索实验室 「问一句话,**整条链路**是怎么走到那几段的」(§9.5)
 *
 * ⚠️ **「有片段」不等于「能检索」。** 一个有 71 个片段、0 个就绪索引的知识库,
 * 检索时返回的是空 —— 而那和「知识库里就这么点东西」在界面上长得一样。
 * 所以列表里「能不能检索」是一列显式的东西,不让人从 0 里猜。
 * ══════════════════════════════════════════════════════════════════ */

function _mock标(是mock) {
  // ⚠️ mock 向量算出的相似度是个**看起来很正常的数字**(0.83),人会拿它当效果读。
  // 所以这个标记要一路传到界面上,不只写在文档里。
  // ⚠️ **tooltip 里不写加粗标记**(`title=` 属性渲染不了粗体,塞进去就是两个星号)。
  // 这一处是 2026-10-08 CI 抓到的,而**本地那一轮是绿的** ——
  // 因为本地索引是真 BGE、CI 是 mock(我自己给 CI 建的 mock 索引),
  // 于是这个分支只在 CI 上渲染。
  // > 一次「本地全绿」和一次「CI 全绿」,**在那个绿勾上长得一模一样** ——
  // > 而两边的**数据形状不同**:本地留着历次跑出来的产物,CI 每次从零。
  // 复现法:`AIMC_USER=U005 AIMC_PROJECT=project_demo_b node tests/e2e/page_smoke.js '#/kb'`
  // (那个项目里有一个 mock 索引 —— 验这个分支要有 mock 的数据)。
  if (是mock === null || 是mock === undefined) return "";
  return 是mock
    ? `<span class="pill fail" title="mock 向量从文本哈希派生,语义无感知 —— 相似度不代表语义">⚠️ mock 向量</span>`
    : `<span class="pill ok" title="真模型(本机 onnxruntime,离线)">真向量</span>`;
}

/* ── 人工待办 ────────────────────────────────────────────────────
 * ⚠️ 契约里两条**界面设计**的约束,不是技术约束:
 *
 *   ① **列表上不许有批准按钮**(§12.1)——
 *      批量批准的界面会让人按「全选」,而那正是不该发生的事
 *   ② **看不到要批准什么的批准按钮,是一个走过场的闸**(§12.1)——
 *      详情必须显示具体工具、脱敏参数、影响对象、必要证据
 *
 * 这两条把审批从一个流程变成一个**需要理解才能完成的动作**。
 * 做得「方便」在这里是错的。 */
async function 页_人工待办() {
  const 头 = `<div class="crumb">待办与定时 / 人工待办</div>
    <div class="head"><div><h1>人工待办</h1>
      <div class="sub">${md(`不可逆写入要人点头。**列表上没有批准按钮,这是有意的。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  // 「只看我能处理的」(11-21,按门店分开那一拍的第三样):记在本机,刷新还在;门店范围本身服务端就筛了,这里只是再按「还能处理吗」过一遍
  const 只看我的 = (() => { try { return localStorage.getItem("aimc.human.onlyMine") === "1"; } catch (e) { return false; } })();
  let d, 转;
  try { [d, 转] = await Promise.all([请求(`${P()}/human-requests${只看我的 ? "?mine=true" : ""}`), 请求(`${P()}/chat-handoffs?page_size=100`)]); }
  catch (e) { const s = 错误块(e, 页_人工待办); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 转栏 = 画_聊天转人工(转.items);
  const 过滤条 = `<div class="k" style="margin:6px 0"><label><input type="checkbox" id="hr-mine" ${只看我的 ? "checked" : ""}> 只看我能处理的</label>
      ${d["我的门店"] ? ` · 你登记在 <b>${esc(d["我的门店"])}</b> 门店,这里只列本店的单子` : ` · 你没登记门店,看全部门店的单子`}</div>`;
  const 挂过滤 = () => { const c = $("#hr-mine"); if (c) c.onchange = () => { try { localStorage.setItem("aimc.human.onlyMine", c.checked ? "1" : "0"); } catch (e) { /* 存不了就只管这一次 */ } 页_人工待办(); }; };
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 转栏 + 过滤条 + 状态("", 只看我的 ? "没有你能处理的待办" : "没有待批准的写入",
      只看我的 ? "取消勾选能看到门店范围内的全部待办(包括别人才能处理的)。" : "Agent 请求不可逆写入时会在这里出现。").html;
    挂_聊天转人工(); 挂过滤();
    return;
  }
  $("#main").innerHTML = 头 + 转栏 + 过滤条 + `<table><thead><tr>
      <th>要做什么</th><th>门店</th><th>状态</th><th>截止</th><th>你能处理吗</th><th></th>
    </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td>${r.risk_note ? md(r.risk_note) : esc(r.kind || r.id)}
          <div class="k">${esc(r.id)}</div>
          ${r["有人能批吗"] === false
            ? `<div class="k"><span class="pill fail">没人能批</span>
                 ${md(r["没人能批的原因"] || "")}</div>` : ""}</td>
        <td class="k">${r["门店"] ? esc(r["门店"]) : `<span title="挂起时从输入 / 材料 / 发起人都定不出门店;只有不限门店的人看得到">—</span>`}</td>
        <td><span class="pill ${r.status === "pending" ? "warn"
              : r.status === "approved" ? "ok" : ""}" title="${esc(r.status)}">${esc(_英转中[r.status] || r.status)}</span></td>
        <td class="k">${r.expires_at
              ? esc(String(r.expires_at).slice(5, 16).replace("T", " "))
              : `<span class="pill fail">没设截止</span>`}
          ${r["过期了吗"] === true ? `<span class="pill fail">已过期</span>` : ""}</td>
        <td>${r["还能处理吗"] ? `<span class="pill ok">能</span>`
              : `<span class="pill">不能</span>
                 <div class="k">${md(String(r["为什么不能处理"] || "").slice(0, 60))}</div>`}</td>
        <td><button data-hr="${esc(r.id)}">看详情</button></td>
      </tr>`).join("")
    + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
  $("#main").querySelectorAll("[data-hr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/human/" + encodeURIComponent(b.dataset.hr); };
  });
  挂_聊天转人工(); 挂过滤();
}

/* 聊天转人工(11-09):店长助手这一轮交给人处理的问题。列表不带原话,有受理权限的人点开才看;只能处理一次。 */
function 画_聊天转人工(行们) {
  if (!行们.length) return `<h3>聊天转人工</h3><div class="note">没有店长助手转来的问题。</div>`;
  return `<h3>聊天转人工</h3><table><thead><tr><th>谁问的</th><th>意图</th><th>为什么转人工</th><th>状态</th><th>什么时候</th><th></th></tr></thead><tbody>`
    + 行们.map((r) => { const 人 = r.asker_snapshot || {}; return `<tr>
        <td>${esc(人["姓名"] || 人["工号"] || "")}<div class="k">${esc(人["门店"] || "")}</div></td>
        <td>${esc(r.intent_name || "判不出")}</td>
        <td>${esc(r.reason_note || "")}</td>
        <td><span class="pill ${r.status === "待处理" ? "warn" : "ok"}">${esc(r.status)}</span></td>
        <td class="k">${esc(String(r.created_at || "").slice(5, 16).replace("T", " "))}</td>
        <td><button data-ho="${esc(r.id)}">看详情</button></td></tr>`; }).join("")
    + `</tbody></table>`;
}
function 挂_聊天转人工() {
  $("#main").querySelectorAll("[data-ho]").forEach((b) => { b.onclick = 只跑一次(() => 开_聊天转人工(b.dataset.ho)); });
}
async function 开_聊天转人工(编号) {
  let r;
  try { r = await 请求(`${P()}/chat-handoffs/${encodeURIComponent(编号)}`); }
  catch (e) { 提示("打不开这条转人工", `<div>${esc(e.message || String(e))}</div>`); return; }
  const 原话 = r["原话看得到吗"] ? `<div class="k">店长原话</div><div>${esc(r.question_note || "")}</div>`
    : `<div class="note">你没有受理权限,看不到店长原话。</div>`;
  const 已办 = r.status === "已处理" ? `<div class="k">处理说明</div><div>${esc(r.note || "")}</div>` : "";
  提示(`转人工 ${r.id}`, `${原话}<div class="k">为什么转人工</div><div>${esc(r.reason_note || "")}</div>${已办}
    ${r["还能处理吗"] ? `<div class="acts" style="margin-top:12px"><button id="ho-do">标记已处理</button></div>` : ""}`);
  const 钮 = $("#ho-do");
  if (钮) 钮.onclick = 只跑一次(async () => {
    const 说明 = await 问一句("标记已处理", "写一句怎么处理的,之后不能再改。", { 输入: "比如 已电话联系客户", 必填: true, 确定: "标记已处理" });
    if (!说明) return;
    try {
      await 请求(`${P()}/chat-handoffs/${encodeURIComponent(编号)}/resolve`, { method: "POST", headers: { "If-Match": String(r.revision) }, body: JSON.stringify({ 说明 }) });
      await 页_人工待办(); 轻提示("已标记处理");
    } catch (e) { 提示("没处理成功", `<div>${esc(e.message || String(e))}</div>`); }
  });
}

/* ── 人工核对(工作流里的 human 节点,2026-10-24)──────────────────────
 * 方案 §5.3 / §7:原文和摘要**并排**,定稿可改,决定只有「通过 / 驳回」(11-08 用户拍:「退回 / 驳回」统一叫驳回)。
 * 和工具审批那一页分开画:审批要看的是「写哪儿、写什么类型」,核对的活是**对着原文看摘要漏没漏、编没编** ——
 * 原文给形状(「419 字 · 开头……」)的话,审核人只能照着摘要点通过,这一步就成了走过场。
 */
/* 表单化的待办(四期 4-1,11-20 照 Dify):材料里带 __表单{说明, 字段, 按钮} → 画说明(Markdown)+ 字段控件 + 按钮(每个按钮一个决定);
 * 没配按钮的照旧 通过 / 退回。字段值走 edits 回去(请求的 allowed_fields 里已经有这些名字),必填的不填不让提交 */
function 画_表单待办(hid, d, 头, 表) {
  const 材 = d["核对材料"] || {}, 请 = d["请求"] || {};
  const 跑 = 请.execution_run_id || (d["影响对象"] || {})["运行"];
  const 字段 = (表["字段"] || []).filter((f) => f && f.name), 按钮 = (表["按钮"] || []).filter((a) => a && a.id);
  // 按钮样式写成整段字面 class(css_class_check 钉着拼出来的条数):主要 → pri,强调 → pri danger,默认 / 幽灵 → 普通按钮
  const 按钮html = (a) => a.样式 === "主要" ? `<button class="pri" data-ha="${esc(a.id)}">${esc(a.文字 || a.id)}</button>`
    : a.样式 === "强调" ? `<button class="pri danger" data-ha="${esc(a.id)}">${esc(a.文字 || a.id)}</button>`
    : `<button data-ha="${esc(a.id)}">${esc(a.文字 || a.id)}</button>`;
  const 控件 = (f, i) => f.type === "下拉" ? `<select data-hf="${i}"><option value="">请选择</option>${(f.options || []).map((o) => `<option>${esc(o)}</option>`).join("")}</select>`
    : f.type === "是否" ? `<select data-hf="${i}"><option value="">请选择</option><option value="是">是</option><option value="否">否</option></select>`
    : `<textarea data-hf="${i}" rows="3"></textarea>`;
  $("#main").innerHTML = 头 + `
    <div class="note">${跑 ? `来自运行 <code>${esc(跑)}</code> <a href="#/wfrun/${encodeURIComponent(跑)}">去看这次运行 →</a>` : ""}
      ${请.expires_at ? ` · 截止 ${esc(String(请.expires_at).slice(0, 16).replace("T", " "))}(到点没人处理,这次运行结束、不写任何东西)` : ""}</div>
    <div class="card"><h3>请核对</h3><div>${md(表["说明"] || "(这一步没写说明)")}</div>
      ${Object.keys(材).filter((k) => k !== "__表单").length ? `<details><summary class="k">给核对人的材料(原文)</summary><pre class="io" data-raw="原文">${esc(JSON.stringify(Object.fromEntries(Object.entries(材).filter(([k]) => k !== "__表单")), null, 2))}</pre></details>` : ""}
      ${d["你能处理吗"] ? `${字段.map((f, i) => `<label class="f">${esc(f.title || f.name)}${f.required ? " · 必填" : ""}</label>${控件(f, i)}`).join("")}
        <label class="f">理由(可选${按钮.length ? "" : ";驳回必填"})</label><textarea id="rv-why" rows="2"></textarea>
        <div class="acts">${按钮.length ? 按钮.map(按钮html).join(" ")
          : `<button class="pri" data-ha="approved">通过</button> <button data-ha="rejected">驳回</button>`}</div>
        <div id="rv-res"></div>` : `<div class="state err"><h3>你不能处理这条</h3><p>${md(d["为什么"] || "")}</p></div>`}
    </div>
    <h2>处理记录</h2>`
    + ((d["决定历史"] || []).length ? `<table><thead><tr><th>谁</th><th>决定</th><th>理由</th></tr></thead><tbody>`
        + d["决定历史"].map((x) => `<tr><td>${esc(x.actor)}</td><td>${x.decision === "approved" ? "通过" : x.decision === "rejected" ? "驳回" : esc((按钮.find((a) => a.id === x.decision) || {}).文字 || x.decision)}</td><td>${esc(x.reason || "")}</td></tr>`).join("")
        + `</tbody></table>` : `<div class="k">还没有人处理过。</div>`);
  if (!d["你能处理吗"]) return;
  const 发 = 只跑一次(async (决定) => {
    const 理由 = $("#rv-why").value.trim();
    if (决定 === "rejected" && !理由) { $("#rv-why").focus(); $("#rv-res").innerHTML = `<div class="k">驳回要写理由 —— 不然发起的人不知道错在哪。</div>`; return; }
    const edits = {};
    for (let i = 0; i < 字段.length; i++) {
      const v = (document.querySelector(`[data-hf="${i}"]`).value || "").trim();
      if (!v && 字段[i].required) { $("#rv-res").innerHTML = `<div class="k">「${esc(字段[i].title || 字段[i].name)}」是必填的。</div>`; return; }
      if (v) edits[字段[i].name] = v;
    }
    $("#rv-res").innerHTML = `<div class="k">提交中…</div>`;
    try {
      const r = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}/decisions`, {
        method: "POST", headers: { "Idempotency-Key": 新键() },
        body: JSON.stringify({ decision: 决定, request_revision: 请.revision, reason: 理由 || null, edits }) });
      $("#rv-res").innerHTML = `<div class="note">已提交「${esc((按钮.find((a) => a.id === 决定) || {}).文字 || 决定)}」—— 流程按这个按钮对应的那条线接着走${r["运行"] ? ` · <a href="#/wfrun/${encodeURIComponent(r["运行"].id)}">看这次运行</a>` : ""}</div>`;
      setTimeout(() => 页_待办详情(hid), 1500);
    } catch (e) { const s = 错误块(e, null); $("#rv-res").innerHTML = s.html; }
  });
  document.querySelectorAll("[data-ha]").forEach((b) => { b.onclick = () => 发(b.dataset.ha); });
}
function 画_核对页(hid, d, 头) {
  const 材 = d["核对材料"] || {}, 请 = d["请求"] || {}, 影 = d["影响对象"] || {};
  if (材["__表单"] && typeof 材["__表单"] === "object") return 画_表单待办(hid, d, 头, 材["__表单"]);
  // 待办 ↔ 运行互链(11-19,体检 #10):正源是 human_requests.execution_run_id(接口放在「请求」里),
  // target_ref.运行 只有部分流程会带 —— 原来只认后者,不带的那些待办看不到自己是哪次运行停下来等的
  const 跑 = 请.execution_run_id || 影["运行"];
  const 能改 = (d["允许编辑的字段"] || []).includes("定稿");
  // 定稿之外核对人能填的(10-24 录音的回电负责人 / 回电截止、10-25 订单风险的跟踪负责人 / 跟踪截止):
  // 负责人和时间由人填,不让模型猜;**全填了 = 要派,全空 = 不派**,只填一部分不提交。按字段名通用地画,不按流程写死
  const 额外 = (d["允许编辑的字段"] || []).filter((k) => k !== "定稿");
  const 待 = Array.isArray(材["待确认项"]) ? 材["待确认项"] : [];
  $("#main").innerHTML = 头 + `
    <div class="note">${材["客户"] ? `客户 <b>${esc(材["客户"])}</b>` : ""} ${材["通话"] ? ` · 通话 <b>${esc(材["通话"])}</b>` : ""}
      ${跑 ? ` · 来自运行 <code>${esc(跑)}</code> <a href="#/wfrun/${encodeURIComponent(跑)}">去看这次运行 →</a>` : ""}
      ${请.expires_at ? ` · 截止 ${esc(String(请.expires_at).slice(0, 16).replace("T", " "))}(到点没人处理,这次运行结束、不写任何东西)` : ""}</div>
    <div class="two">
      ${材["工具"] ? `<div class="card"><h3>Agent 要执行的写操作</h3>
        <div>工具 <b>${esc(材["工具"])}</b></div>
        <pre class="io" data-raw="原文">${esc(JSON.stringify(材["参数"] ?? {}, null, 2))}</pre>
        <div class="k">${esc(材["说明"] || "")} 批准 = 允许它按上面的参数真写进系统;看不清对谁写什么就驳回。</div></div>`
      : `<div class="card"><h3>原文</h3><pre class="io">${esc(材["原文"] || "(没有原文)")}</pre>
        <div class="k">手机号已打码。核对就是对着这里看:摘要里每一条,原文里找得到客户亲口说的吗?</div></div>`}
      <div class="card"><h3>AI 整理的摘要</h3><div>${esc(材["摘要"] || "")}</div>
        ${待.length ? `<h4>待确认项</h4><ul>${待.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${d["你能处理吗"] ? `
        <h4>定稿(通过后写进客户档案的那一版)</h4>
        ${能改 ? `<textarea id="rv-fin" rows="6">${esc(材["摘要"] || "")}</textarea>`
               : `<div class="k">这一步不允许改定稿 —— 通过就按上面的摘要写。</div>`}
        ${额外.length ? `<h4>派任务(可选)</h4>
        ${材["类别"] ? `<div class="k">AI 判断的类别:<b>${esc(材["类别"])}</b>。只有「明确需求 / 考虑中」才会派。</div>` : ""}
        ${材["风险"] ? `<div class="k">规则判的风险档:<b>${esc((材["风险"] || {})["档"] || "—")}</b>
          ${esc(((材["风险"] || {})["依据"] || []).join(";"))}</div>` : ""}
        <div class="k">下面几项<b>都填了才派</b>,全空就不派。</div>
        ${额外.map((k, i) => `<label class="f">${esc(k)}${/负责人/.test(k) ? "(工号或姓名)" : ""}</label>
          <input data-rvx="${i}" ${/截止/.test(k) ? 'type="datetime-local"' : /客户号/.test(k) ? 'placeholder="逗号分隔,如 C36892,C36090"' : 'placeholder="如 60000003"'}>`).join("")}` : ""}
        <label class="f">理由(驳回必填)</label><textarea id="rv-why" rows="2"></textarea>
        <button class="pri" id="rv-ok">通过</button> <button id="rv-no">驳回</button>
        <div id="rv-res"></div>` : `<div class="state err"><h3>你不能处理这条</h3><p>${md(d["为什么"] || "")}</p></div>`}
      </div></div>
    <h2>处理记录</h2>`
    + ((d["决定历史"] || []).length ? `<table><thead><tr><th>谁</th><th>决定</th><th>理由</th></tr></thead><tbody>`
        + d["决定历史"].map((x) => `<tr><td>${esc(x.actor)}</td><td>${x.decision === "approved" ? "通过"
            : x.decision === "rejected" ? "驳回" : esc(x.decision)}</td><td>${esc(x.reason || "")}</td></tr>`).join("")
        + `</tbody></table>` : `<div class="k">还没有人处理过。</div>`);
  if (!d["你能处理吗"]) return;
  const 发 = 只跑一次(async (决定) => {
    const 理由 = $("#rv-why").value.trim();
    if (决定 === "rejected" && !理由) { $("#rv-why").focus(); $("#rv-res").innerHTML = `<div class="k">驳回要写理由 —— 不然发起的人不知道错在哪。</div>`; return; }
    const edits = {};
    if (决定 === "approved" && 能改 && $("#rv-fin").value.trim() !== (材["摘要"] || "").trim()) edits["定稿"] = $("#rv-fin").value.trim();
    if (决定 === "approved" && 额外.length) {
      const 值 = 额外.map((k, i) => (document.querySelector(`[data-rvx="${i}"]`).value || "").trim());
      const 填了 = 值.filter(Boolean).length;
      if (填了 === 额外.length) 额外.forEach((k, i) => { edits[k] = 值[i].replace("T", " "); });
      else if (填了) { $("#rv-res").innerHTML = `<div class="k">${esc(额外.join("、"))} 要么都填、要么都不填 —— 只填一部分不会派。</div>`; return; }
    }
    $("#rv-res").innerHTML = `<div class="k">提交中…</div>`;
    try {
      const r = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}/decisions`, {
        method: "POST", headers: { "Idempotency-Key": 新键() },
        body: JSON.stringify({ decision: 决定, request_revision: 请.revision, reason: 理由 || null, edits }) });
      $("#rv-res").innerHTML = `<div class="note">${决定 === "approved" ? "已通过 —— 流程接着走,接下来的写入由澜绣的同步程序按定稿去办"
        : "已驳回 —— 这次运行记下理由后结束,什么都不写"}${r["运行"] ? ` · <a href="#/wfrun/${encodeURIComponent(r["运行"].id)}">看这次运行</a>` : ""}</div>`;
      setTimeout(() => 页_待办详情(hid), 1500);
    } catch (e) { const s = 错误块(e, null); $("#rv-res").innerHTML = s.html; }
  });
  $("#rv-ok").onclick = () => 发("approved");
  $("#rv-no").onclick = () => 发("rejected");
}

async function 页_待办详情(hid) {
  const 头 = `<div class="crumb">待办与定时 / <a href="#/human">人工待办</a> · 详情</div>
    <div class="head"><div><h1>待办详情</h1>
      <div class="sub">${esc(hid)}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}`); }
  catch (e) { const s = 错误块(e, () => 页_待办详情(hid)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (d["核对材料"]) return 画_核对页(hid, d, 头);
  const 证 = d["证据"] || {};
  const 工 = d["具体工具"];
  // 待办 ↔ 运行互链(11-19,体检 #10):运行详情那边早就能跳到待办(在等什么.待办),这边原来回不去,只能去运行列表翻
  const 跑 = (d["请求"] || {}).execution_run_id;
  $("#main").innerHTML = 头
    + (跑 ? `<div class="k">这条待办是运行 <code>${esc(跑)}</code> 停下来等的 · <a href="#/wfrun/${encodeURIComponent(跑)}">去看这次运行 →</a></div>` : "")
    + `<div class="note">${md(d.note || "")}</div>
    <h2>要批准什么</h2>
    <div class="card">
      <div class="k">影响对象</div>
      <pre data-raw="原文" class="k">${esc(JSON.stringify(d["影响对象"], null, 1))}</pre>
      <div class="k">具体工具</div>
      <pre class="k">${工 ? esc(JSON.stringify(工, null, 1)) : "(没绑工具版本)"}</pre>
      <div class="k">参数${d["看得到原文吗"] ? "（原文）" : "（已脱敏）"}</div>
      <pre data-raw="原文" class="k">${esc(JSON.stringify(d["脱敏参数"], null, 1))}</pre>
    </div>
    <h2>证据</h2>
    <table><tbody>`
    + Object.entries(证).map(([k, v]) =>
        `<tr><td class="k">${esc(k)}</td><td data-raw="原文">${esc(JSON.stringify(v))}</td></tr>`).join("")
    + `</tbody></table>
    <h2>决定</h2>`
    + (d["你能处理吗"]
        ? `<div class="card">
             <label class="f">理由（驳回必填）</label>
             <textarea id="why" rows="2"></textarea>
             <label class="f">改字段（JSON，只许改 ${esc(JSON.stringify(d["允许编辑的字段"]))}）</label>
             <textarea id="edits" rows="2">{}</textarea>
             <button class="pri" id="ap">批准</button>
             <button id="rj">驳回</button>
             <button id="info">要求补充</button>
             <div class="note">${md(`⚠️ **批准只产生批准记录,不等于已执行** ——
               真正执行时还要再查一遍权限和工具当前可用性。`)}</div>
             <div id="res"></div>
           </div>`
        : `<div class="state err"><h3>你不能处理这条</h3>
             <p>${md(d["为什么"] || "")}</p></div>`)
    + `<h2>决定历史</h2>`
    + ((d["决定历史"] || []).length
        ? `<table><thead><tr><th>谁</th><th>怎么判的</th><th>那时的 rev</th>
             <th>理由</th></tr></thead><tbody>`
          + d["决定历史"].map((x) => `<tr><td>${esc(x.actor)}</td>
              <td><span class="pill">${esc(x.decision)}</span></td>
              <td class="num">${x.request_revision}</td>
              <td>${esc(x.reason || "")}</td></tr>`).join("")
          + `</tbody></table>`
        : `<div class="state">还没有人处理过</div>`);
  if (!d["你能处理吗"]) return;
  const 发 = 只跑一次(async (决定) => {
    const res = $("#res");
    let edits;
    try { edits = JSON.parse($("#edits").value || "{}"); }
    catch (e) {
      res.innerHTML = `<div class="state err"><h3>改字段不是合法 JSON</h3></div>`; return;
    }
    res.innerHTML = `<div class="note">提交中…</div>`;
    try {
      const r = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}/decisions`, {
        method: "POST",
        headers: { "Idempotency-Key": "hd-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8) },
        body: JSON.stringify({ decision: 决定,
                               request_revision: (d["请求"] || {}).revision,
                               reason: $("#why").value || null, edits }),
      });
      res.innerHTML = `<div class="note">${esc(_英转中[r.decision] || r.decision)} →
        <b>${esc(r["当前状态"])}</b>（rev ${r["新的 revision"]}）<br>
        ${md(r.note || "")}</div>`;
      setTimeout(() => 页_待办详情(hid), 1200);
    } catch (e) { const s = 错误块(e, null); res.innerHTML = s.html; }
  });
  $("#ap").onclick = () => 发("approved");
  $("#rj").onclick = () => 发("rejected");
  $("#info").onclick = () => 发("info_requested");
}

/* ── 评测中心 / 回归验收(M4:/acceptance 重建)────────────────────────
 * ⚠️ **「有分数」不等于「能当结论」。** 规格 §18 要求四个东西同时在场:
 * 候选 + 基线 + 冻结的数据版本 + 记录在案的判据版本。
 * 缺任何一个,跑出来的数**看起来仍然是个分数** —— 而那是这一页的核心危险。 */
// 后台派发评测的终态 —— **照抄后端 eval_dispatch.评测终态们**,别自己加:
// 后端只对不在这几档里的评测受理取消,这里多写一档就是摆一个点了回 409 的按钮,少写一档就是藏掉一个能停的
const 评测终态们 = new Set(["已完成", "超时", "超出费用上限", "已取消"]);
// 看进度 / 发起 / 取消都走服务端「运行评测」这条能力;这里只决定摆不摆按钮(§5.2:前端不是授权)
const 能运行评测 = () => ["admin", "editor", "trainer", "approver"].includes(我的角色);
// 项目里所有工作流的已冻结版本(后台派发时候选 / 基线只认 workflow_versions.id)。
// 列表接口只给「最新冻结版本 vN」不给 id,所以要逐条进详情取 `版本们`;一次页面里只拉一遍
let 工作流版本缓存 = null;
async function 取工作流版本们() {
  if (工作流版本缓存) return 工作流版本缓存;
  const 流们 = [];
  for (let 页 = 1, 页数 = 1; 页 <= 页数 && 页 <= 50; 页++) {
    const d = await 请求(`${P()}/workflows?limit=100&page=${页}`);
    流们.push(...(d.items || []));
    页数 = d["页数"] || 1;
  }
  const 出 = [];
  for (const w of 流们) {
    if (!w["版本数"]) continue;             // 没冻结过的,进详情也是空的
    const x = await 请求(`${P()}/workflows/${encodeURIComponent(w.id)}`);
    (x["版本们"] || []).forEach((v) => 出.push({ id: v.id, 名: `${w["名称"]} · ${v["版本"]} · ${v.id}` }));
  }
  工作流版本缓存 = 出;
  return 出;
}

async function 页_评测中心() {
  工作流版本缓存 = null;      // 换项目 / 刚冻结了新版本,重进这一页要看到
  const 头 = `<div class="crumb">评测与训练 / 评测中心</div>
    <div class="head"><div><h1>回归验收</h1>
      <div class="sub">${md(`改完之后跑一遍,看有没有退步。**有分数 ≠ 能当结论。**`)}</div>
    </div><div><a href="#/compare"><button>实验对比</button></a></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d, 数据集 = null, 数据集错 = null;
  try {
    // 数据集列表拿不到(比如 viewer 没有「查看有权配置」)不该拖垮整页 —— 表单里明说,列表照常
    [d, 数据集] = await Promise.all([请求(`${P()}/evaluations`),
      请求(`${P()}/datasets`).catch((e) => { 数据集错 = e; return null; })]);
  }
  catch (e) { const s = 错误块(e, 页_评测中心); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  // 数据集版本下拉:从 `版本们` 来(11-18 加的字段)。老后端没有这个字段 → 退成文本框,别把人卡死
  const 版本项 = [];
  ((数据集 || {})["数据集"] || []).forEach((ds) => (ds["版本们"] || []).forEach((v) =>
    版本项.push({ id: v.id, 名: `${ds["名字"]} · ${v["样本数"] ?? "?"} 题 · ${v.id}` })));
  const 表单 = `<details class="card" id="ev-new"><summary><b>发起评测</b> <span class="k">候选 + 基线 + 冻结的数据版本 + 判据版本,四个都要在场</span></summary>
    <div style="margin-top:8px">
      <label class="f">执行方式</label>
      <select id="ev-mode"><option value="外部登记">外部登记(建一条记录,结果在外面跑完登记进来)</option>
        <option value="后台派发">后台派发(后台把每道题派成工作流运行,要花钱)</option></select>
      <div class="k" id="ev-mode-why">外部登记时候选 / 基线是任意引用(写清是哪一版、哪套提示词就行);后台派发时必须是已冻结的工作流版本。</div>
      <div id="ev-refs">
        <label class="f">候选 <span class="req">*</span></label><input id="ev-cand" style="width:100%" placeholder="比如 独立路由器 haiku-4-5 + 提示词缓存">
        <label class="f">基线 <span class="req">*</span></label><input id="ev-base" style="width:100%" placeholder="比如 关键词检索 @k=5">
      </div>
      <label class="f">数据集版本 <span class="req">*</span></label>
      ${版本项.length
        ? `<select id="ev-dsv"><option value="">请选择(只列冻结过的版本)</option>${版本项.map((v) => `<option value="${esc(v.id)}">${esc(v.名)}</option>`).join("")}</select>`
        : `<input id="ev-dsv" style="width:100%" placeholder="dsv_… 冻结版本 id">
           <div class="k">${数据集错 ? `数据集列表读不到(${esc(数据集错.message)}),先手填版本 id`
             : ((数据集 || {})["数据集"] || []).length && !((数据集 || {})["数据集"] || []).some((x) => "版本们" in x)
               ? "这个后端的数据集列表还没给版本 id(要 11-18 之后的后端),先手填"
               : md("项目里还没有冻结过的数据集版本 —— 去「数据集」页先冻一版,**不静默用当前样本**")}</div>`}
      <label class="f">判据版本 <span class="req">*</span></label><input id="ev-scorer" style="width:100%" placeholder="比如 router_probe@9ba7ef5c02c0 —— 换了判据的两轮不可比">
      <div id="ev-dispatch" style="display:none">
        <label class="f">超时分钟 <span class="req">*</span> <span style="color:var(--ink3)">1–1440;到点没跑完的取消、记成「超时」</span></label><input id="ev-timeout" type="number" min="1" max="1440" style="width:100%">
        <label class="f">费用上限(美元) <span class="req">*</span> <span style="color:var(--ink3)">已知花费超过它就停,记成「超出费用上限」</span></label><input id="ev-cap" type="number" min="0" step="0.01" style="width:100%">
        <label class="f">轮数 <span style="color:var(--ink3)">1–5,默认 2:只跑 1 轮看不出波动</span></label><input id="ev-rounds" type="number" min="1" max="5" value="2" style="width:100%">
        <label class="f">评审连接 <span style="color:var(--ink3)">选填;题里只有期望说明、要模型评审时必须给(模型连接版本 id)</span></label><input id="ev-judge" style="width:100%" placeholder="mcv_…">
      </div>
      <div class="acts" style="margin-top:10px"><button class="pri" id="ev-go">发起</button></div>
      <div id="ev-fb"></div>
    </div></details><div id="ev-msg"></div>`;
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 表单 + 状态("", "还没有评测实验",
      "点上面的「发起评测」建第一个:候选、基线、冻结的数据集版本、判据版本四个都要在场。外面跑完的也可以先建一条「外部登记」,再把逐题结果登记进来。").html;
    挂评测表单();
    return;
  }
  $("#main").innerHTML = 头 + 表单 + `<table><thead><tr>
      <th>候选</th><th>基线</th><th>状态</th><th class="num">题</th>
      <th>数据集版本</th><th>判据</th><th>能当结论吗</th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td><b>${esc((r.candidate_ref || {})["名"] || (r.candidate_ref || {})["ref"] || r.id)}</b>
          <div class="k">${esc(r.id)}</div></td>
        <td>${r["有基线吗"] ? esc((r.baseline_ref || {})["名"] || (r.baseline_ref || {})["ref"] || "有")
                            : `<span class="pill fail">没有基线</span>`}</td>
        <td>${esc(r.status || "—")}<div class="k">${esc(r.executor_code || "")}</div>
          ${r.executor_code !== "后台派发" ? ""
            : !能运行评测() ? `<div class="k">看进度 / 取消要「运行评测」能力 —— 你现在是 <b>${esc(我的角色 || "?")}</b>,所以这里不摆按钮</div>`
            : `<button data-evp="${esc(r.id)}">看进度</button>`
              + (评测终态们.has(r.status) ? "" : ` <button data-evc="${esc(r.id)}">取消</button>`)}</td>
        <td class="num">${r["题数"]}</td>
        <td class="k">${esc(String(r.dataset_version_id || "—").slice(-10))}</td>
        <td class="k">${esc(r.scorer_version || "—")}</td>
        <td>${r["能当结论吗"] ? `<span class="pill ok">能</span>`
              : `<span class="pill fail">不能</span>
                 <div class="k">${esc(r["为什么不能当结论"] || "")}</div>`}</td>
      </tr>`).join("")
    + `</tbody></table><div id="evp"></div><div class="note">${md(d.note || "")}</div>`;
  挂评测表单();
  // 取消(DF-05):要理由、要 If-Match(进度里的 revision)—— 半途停掉的评测,过后得说得出是谁停的、为什么
  $("#main").querySelectorAll("[data-evc]").forEach((b) => b.onclick = async () => {
    const eid = b.dataset.evc;
    const 理由 = await 问一句("取消这次评测", md("没跑完的运行会被取消,**已经收回的结果留着**;评测记成「已取消」,不能再恢复。"),
      { 输入: "为什么停(必填,会进审计)", 多行: true, 必填: true, 确定: "取消评测", 取消: "先不" });
    if (!理由) return;
    b.disabled = true;
    try {
      const g = await 请求(`${P()}/evaluations/${encodeURIComponent(eid)}/progress`);
      if (g.revision == null) throw Object.assign(new Error("进度接口没给 revision,取消要拿它做 If-Match"),
        { 体: { code: "NO_REVISION", advice: "刷新一次;还是这样就是进度接口的问题" } });
      const r = await 请求(`${P()}/evaluations/${encodeURIComponent(eid)}/cancel`,
        { method: "POST", headers: { "If-Match": String(g.revision) }, body: JSON.stringify({ 理由 }) });
      await 页_评测中心();
      $("#ev-msg").innerHTML = `<div class="note">已取消 ${esc(r.id)},取消了 ${esc(r["取消了"] ?? "?")} 次运行。${md(r.note || "")}</div>`;
    } catch (e) {
      b.disabled = false;
      const s = 错误块(e, null); $("#evp").innerHTML = s.html;
    }
  });
  // 后台派发的评测(DF-05):派了几次、收回几次、每次运行是谁在跑 —— **「已派发」只是排上队,不是在跑**
  $("#main").querySelectorAll("[data-evp]").forEach((b) => b.onclick = async () => {
    const box = $("#evp");
    box.innerHTML = `<div class="state">加载中…</div>`;
    let g;
    try { g = await 请求(`${P()}/evaluations/${encodeURIComponent(b.dataset.evp)}/progress`); }
    catch (e) { const s = 错误块(e, null); box.innerHTML = s.html; return; }
    const 时 = (t) => t ? esc(String(t).replace("T", " ").slice(0, 19)) : "—";
    box.innerHTML = `<div class="card"><h3>评测进度 · ${esc(g.id)}</h3>
      ${g["过了截止没收尾"] ? `<div class="state err">${md(g.note)}</div>` : `<div class="note">${md(g.note)}</div>`}
      <div class="k">状态 ${esc(g.status)}${g["结束原因"] ? " · " + esc(g["结束原因"]) : ""} ·
        派发 ${时(g["派发于"])} · 开始 ${时(g["开始于"])} · 心跳 ${时(g["心跳"])} · 截止 ${时(g["截止"])} · 结束 ${时(g["结束于"])}</div>
      <div class="k">已知费用 ${esc(g["已知费用"])} / 上限 ${esc(g["费用上限"])} 美元${g["算不出金额的笔数"] ? ` · ${g["算不出金额的笔数"]} 笔算不出金额(费用是「至少」)` : ""}</div>
      <table><thead><tr><th>边</th><th class="num">轮</th><th class="num">派了</th><th class="num">收回</th><th class="num">跑通</th><th class="num">跑通率</th></tr></thead><tbody>`
      + (g["分组"] || []).map((x) => `<tr><td>${esc(x["边"])}</td><td class="num">${x["轮"]}</td>
          <td class="num">${x["派了"]}</td><td class="num">${x["已收"]}</td><td class="num">${x["跑通"]}</td>
          <td class="num">${x["跑通率"] == null ? `<span class="pill warn">未知</span>` : x["跑通率"]}</td></tr>`).join("")
      + `</tbody></table>
      <table><thead><tr><th>题</th><th>边</th><th class="num">轮</th><th>运行</th><th>运行状态</th><th>执行者</th><th>收回了吗</th></tr></thead><tbody>`
      + (g["回执"] || []).map((x) => `<tr><td class="k">${esc(String(x["题"]).slice(-10))}</td><td>${esc(x["边"])}</td>
          <td class="num">${x["轮"]}</td><td class="k"><a href="#/wfrun/${encodeURIComponent(x["运行"])}">${esc(String(x["运行"]).slice(-8))}</a></td>
          <td>${esc(x["运行状态"])}</td><td class="k">${esc(x["执行者"] || "还没人领")}</td>
          <td>${x["收回了吗"] ? "是" : "否"}</td></tr>`).join("")
      + `</tbody></table></div>`;
  });
}

/* 发起评测表单的行为(11-18):切执行方式 → 候选 / 基线在文本框和「已冻结工作流版本」下拉之间换;
 * 提交带 Idempotency-Key(评测要花钱,超时重发一次就是再跑一遍题);
 * 422 的 field_errors **逐字段摆在表单下面** —— 这个后台的惯例是错误要能指到字段,一句「建不了」没人知道改哪 */
function 挂评测表单() {
  const 方式 = () => $("#ev-mode").value || "外部登记";
  const 文本框 = () => {
    $("#ev-refs").innerHTML = `<label class="f">候选 <span class="req">*</span></label><input id="ev-cand" style="width:100%" placeholder="比如 独立路由器 haiku-4-5 + 提示词缓存">
      <label class="f">基线 <span class="req">*</span></label><input id="ev-base" style="width:100%" placeholder="比如 关键词检索 @k=5">`;
  };
  $("#ev-mode").onchange = async () => {
    const 派 = 方式() === "后台派发";
    $("#ev-dispatch").style.display = 派 ? "" : "none";
    if (!派) { 文本框(); return; }
    $("#ev-refs").innerHTML = `<div class="k">正在读项目里的工作流版本…</div>`;
    let 版们;
    try { 版们 = await 取工作流版本们(); }
    catch (e) { $("#ev-refs").innerHTML = 错误块(e, null).html; return; }
    if (!版们.length) {
      $("#ev-refs").innerHTML = `<div class="state"><h3>项目里还没有冻结过的工作流版本</h3>
        <p>${md("后台派发要候选和基线都是**已冻结的工作流版本**。先到工作室把工作流冻结一版,或者换成「外部登记」。")}</p></div>`;
      return;
    }
    const 选 = (id) => `<select id="${id}"><option value="">请选择</option>${版们.map((v) => `<option value="${esc(v.id)}">${esc(v.名)}</option>`).join("")}</select>`;
    $("#ev-refs").innerHTML = `<label class="f">候选 <span class="req">*</span> <span style="color:var(--ink3)">工作流名 · 版本号 · id</span></label>${选("ev-cand")}
      <label class="f">基线 <span class="req">*</span> <span style="color:var(--ink3)">要和候选不同 —— 同一版自己比自己,差值只剩波动</span></label>${选("ev-base")}`;
  };
  $("#ev-go").onclick = async () => {
    const fb = $("#ev-fb");
    const 派 = 方式() === "后台派发";
    const 体 = { 执行方式: 方式(), 候选: ($("#ev-cand").value || "").trim(), 基线: ($("#ev-base").value || "").trim(),
      数据集版本: ($("#ev-dsv").value || "").trim(), 判据版本: ($("#ev-scorer").value || "").trim() };
    if (派) {
      // 空就不送:后端的 int()/float() 把空串也判成「必填」,但送个空值过去再被打回,不如本地先留白
      体.超时分钟 = $("#ev-timeout").value === "" ? null : Number($("#ev-timeout").value);
      体.费用上限 = $("#ev-cap").value === "" ? null : Number($("#ev-cap").value);
      体.轮数 = $("#ev-rounds").value === "" ? 2 : Number($("#ev-rounds").value);
      const 评审 = ($("#ev-judge").value || "").trim();
      if (评审) 体.评审连接 = 评审;
    }
    $("#ev-go").disabled = true;
    fb.innerHTML = `<div class="k">提交中…</div>`;
    try {
      const r = await 请求(`${P()}/evaluations`, { method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(体) });
      await 页_评测中心();
      $("#ev-msg").innerHTML = `<div class="note"><b>${r["新建了吗"] === false ? "没有新建" : "已建"} ${esc(r.id)}</b> · 状态 ${esc(r.status || "")}`
        + (r["派了"] != null ? ` · 派了 ${esc(r["派了"])} 次运行` : "") + `<br>${md(r.note || "")}</div>`;
    } catch (e) {
      $("#ev-go").disabled = false;
      const b = e.体 || {};
      const 条 = Object.entries(b.field_errors || {}).map(([k, v]) =>
        `<li><b>${esc(k)}</b>:${md(Array.isArray(v) ? v.join(";") : String(v))}</li>`).join("");
      fb.innerHTML = `<div class="state err"><h3>${esc(b.code || "出错了")} · ${esc(e.message)}</h3>
        ${条 ? `<ul>${条}</ul>` : ""}<p>${md(b.advice ? `**下一步:**${b.advice}` : "服务端没给建议")}</p></div>`;
    }
  };
}

/* ── 实验对比(M5:/experiments 重建)──────────────────────────────────
 * ⚠️ **先判可比,再给数。** 两轮用了不同的数据集版本或判据版本时,
 * 这里**不显示分数** —— 并排两个不可比的数比不显示糟得多:
 * 读的人会算出一个差值,而那个差值可能全来自题目或评分方式。 */
async function 页_实验对比() {
  const 头 = `<div class="crumb">评测与训练 / 实验对比</div>
    <div class="head"><div><h1>实验对比</h1>
      <div class="sub">${md(`同一套题两个版本并排。**不可比时不给分数。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/evaluations`); }
  catch (e) { const s = 错误块(e, 页_实验对比); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (d.items.length < 2) {
    $("#main").innerHTML = 头 + 状态("", "至少要两个评测实验才能对比",
      `现在有 ${d.items.length} 个。`).html;
    return;
  }
  const 选 = (id) => d.items.map((r) =>
    `<option value="${esc(r.id)}">${esc((r.candidate_ref || {})["名"] || (r.candidate_ref || {})["ref"] || r.id)} · ${esc(r.id)}</option>`).join("");
  $("#main").innerHTML = 头 + `
    <div class="card">
      <label class="f">甲</label><select id="ea">${选()}</select>
      <label class="f">乙</label><select id="eb">${选()}</select>
      <button class="pri" id="cmp">对比</button>
    </div><div id="res"></div>`;
  $("#eb").selectedIndex = Math.min(1, d.items.length - 1);
  $("#cmp").onclick = async () => {
    const res = $("#res");
    res.innerHTML = `<div class="note">对比中…</div>`;
    try {
      // ⚠️ 参数名是 `a` / `b`(ASCII)—— 中文参数名每个调用方都得记得编码,
      // 而忘了的表现是「接口没返回」不是报错。
      const r = await 请求(`${P()}/evaluations/compare`
        + `?a=${encodeURIComponent($("#ea").value)}`
        + `&b=${encodeURIComponent($("#eb").value)}`);
      if (!r["可比吗"]) {
        res.innerHTML = `<div class="state err"><h3>不可比,所以这里不给分数</h3>
          <p>${md(r["为什么"])}</p><p>${md(r.note || "")}</p></div>`;
        return;
      }
      const 名 = (x) => esc((x.candidate_ref || {})["名"] || (x.candidate_ref || {})["ref"] || x.id);   // 外部登记的评测写的是 ref 不是 名(11-18)
      const 维 = new Set();
      Object.values(r["分数"]).forEach((m) => Object.keys(m).forEach((k) => 维.add(k)));
      res.innerHTML = `<div class="note">${md("**" + r["为什么"] + "**")}</div>
        <table><thead><tr><th>维度</th><th>${名(r["甲"])}</th><th>${名(r["乙"])}</th>
          <th>差</th></tr></thead><tbody>`
        + [...维].map((k) => {
            const A = (r["分数"][r["甲"].id] || {})[k] || {};
            const B = (r["分数"][r["乙"].id] || {})[k] || {};
            const 格 = (v) => v["均分是未知吗"]
              ? `<span class="pill warn">未知</span>`
              : `${v["均分"]} <div class="k">${v["已知几条"]} 条已打分`
                + (v["没打分几条"] ? ` · ${v["没打分几条"]} 条没打分` : "") + `</div>`;
            const 可算 = !A["均分是未知吗"] && !B["均分是未知吗"];
            return `<tr><td><b>${esc(k)}</b></td><td>${格(A)}</td><td>${格(B)}</td>
              <td>${可算 ? (B["均分"] - A["均分"] >= 0 ? "+" : "")
                          + Math.round((B["均分"] - A["均分"]) * 10000) / 10000
                        : `<span class="pill warn">算不出</span>`}</td></tr>`;
          }).join("")
        + `</tbody></table><div class="note">${md(r.note || "")}</div>`;
    } catch (e) {
      const s = 错误块(e, null); res.innerHTML = s.html;
    }
  };
}

/* ── 单条试跑(M4:/workbench 重建)────────────────────────────────────
 * ⚠️ **接口早就有了**(`POST /prompt-runs`,实现并验过),缺的只是界面。
 * 所以这一页不是「重建一个功能」,是「把一个已有能力接出来」。
 *
 * ⚠️ **调试也花钱。** 那条接口要「运行评测」权限,不是因为它危险,
 * 是因为它真的会调模型 —— 一个不过额度闸的调试入口,
 * 会让「只是试一下」变成一笔没人预期的账。
 *
 * ⚠️ **202 不是答案。** 接口返回任务信封,不直接给结果 ——
 * 页面要如实显示「排队中」,而不是转个圈假装在等结果:
 * 一个用假进度冒充执行的界面,在任务卡住时看起来完全正常。 */
async function 页_单条试跑() {
  const 头 = `<div class="crumb">评测与训练 / 单条试跑</div>
    <div class="head"><div><h1>单条试跑</h1>
      <div class="sub">${md(`拿一条真输入试一次。**调试也花钱**,所以要过额度闸。`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let ps;
  // 接口上限 100,就装满 100;total 为 null 判不了有没有截断,所以下面照实写「只列前 100 条」
  try { ps = await 请求(`${P()}/prompts?limit=100`); }
  catch (e) { const s = 错误块(e, 页_单条试跑); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!(ps.items || []).length) {
    $("#main").innerHTML = 头 + 状态("", "这个项目还没有 Prompt",
      "先去「Prompt 管理」建一条。").html;
    return;
  }
  $("#main").innerHTML = 头 + `
    <div class="card">
      <label class="f">选一条 Prompt</label>
      <select id="pp">${ps.items.map((p) =>
        `<option value="${esc(p.id)}">${esc(p.name || p.key || p.id)}</option>`).join("")}</select>
      <div class="k">只列前 100 条,更多去 <a href="#/prompts">Prompt 管理</a> 搜</div>
      <div id="tconn"></div>
      <label class="f">变量(JSON)</label>
      <textarea id="vv" rows="4">{}</textarea>
      <button class="pri" id="go">试跑一次</button>
      <div class="note">${md(`⚠️ **这一次真的会调模型。** 返回的是任务信封(202),
        不是答案 —— 下面显示的是**真实状态**,不是假进度条。`)}</div>
      <div id="步"></div>
    </div>`;
  await 画模型连接("#tconn", "t-conn");
  $("#go").onclick = 只跑一次(async () => {
    const 步 = $("#步");
    let 变量;
    try { 变量 = JSON.parse($("#vv").value || "{}"); }
    catch (e) {
      步.innerHTML = `<div class="state err"><h3>变量不是合法 JSON</h3>
        <p>${esc(String(e.message))}</p></div>`;
      return;
    }
    步.innerHTML = `<div class="note">派任务中…</div>`;
    try {
      // 幂等键为这一次点击生成 —— 超时重发不会跑第二遍(也不会多花一次钱)
      const 键 = "tryout-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
      const r = await 请求(`${P()}/prompt-runs`, {
        method: "POST", headers: { "Idempotency-Key": 键 },
        body: JSON.stringify({ prompt_id: $("#pp").value, 变量, model_connection_id: 选中的连接("t-conn") }),
      });
      步.innerHTML = `<div class="note">
        派出去了:任务 <code>${esc(r.job_id)}</code>,状态 <b id="t-st" title="${esc(r.status)}">${esc(_英转中[r.status] || r.status)}</b><br>
        ${md("**202 —— 一个模型都还没调完。**"
             + "这是任务信封,不是答案;下面等它跑完(最多两分钟),等不到去运行记录看。")}
        ${r["模型连接"] ? "" : `<br>⚠️ ${esc(r["模型连接说明"] || "没绑模型连接")}`}
        ${r.note ? "<br>" + md(r.note) : ""}</div>
        <a href="#/runs"><button>去运行记录看</button></a><div id="t-out"></div>`;
      // 11-18 前这一页到此为止 —— 人只看到「排队中」三个字;现在等到终态把结果摆在下面
      const j = await 等任务(r.job_id, (x, 秒) => { const t = $("#t-st"); if (t) t.textContent = `${_英转中[x.status] || x.status} · 等了 ${秒} 秒`; });
      const t = $("#t-st"); if (t) t.textContent = _英转中[j.status] || j.status;
      const 出 = $("#t-out"); if (出) 出.innerHTML = `<div class="card"><div class="body">${运行结果html(j)}</div></div>`;
    } catch (e) {
      const s = 错误块(e, null);
      步.innerHTML = s.html;
    }
  });
}

/* ── 调用链(M5:/debug 在管理后台重建)──────────────────────────────
 * ⚠️ **重建不是搬。** 澜绣那一页读的是澜绣自己的 span 表,
 * 这里读的是管理后台自己的 `traces` / `spans` —— 而那两张表
 * 2026-09-28 之前基本是空的,是精排记账和 A1 上报让它们有了真内容。 */
async function 页_调用链(页 = 1) {
  const 头 = `<div class="crumb">日志与监测 / 调用链</div>
    <div class="head"><div><h1>调用链</h1>
      <div class="sub">${md(`每一次运行的调用树。**看得到 trace 不等于看得到原文。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces?limit=50&page=${页}`); }
  catch (e) { const s = 错误块(e, 页_调用链); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 状态("", "还没有运行记录",
      "跑一次召回测试,或者让门店助手上报一次调用(A1)。").html;
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr>
      <th>什么时候</th><th>调用方</th><th class="num">步</th>
      <th class="num">token</th><th class="num">金额</th><th>结果</th><th></th>
    </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td class="k">${esc(String(r.started_at).slice(5, 19).replace("T", " "))}
          <div class="k">${esc(r.id)}</div></td>
        <td>${r["调用方"] ? esc(r["调用方"]) : `<span class="pill warn">没标调用方</span>`}</td>
        <td class="num">${r["步数"]}${r["出错的步数"]
            ? ` <span class="pill fail">${r["出错的步数"]} 步出错</span>` : ""}</td>
        <td class="num">${Number(r["token数"]).toLocaleString()}</td>
        <td class="num">${_参考价(r["参考价"])}</td>
        <td>${r["成功吗"] === true ? `<span class="pill ok">${esc(r.end_reason || "完成")}</span>`
             : r["成功吗"] === false ? `<span class="pill fail">${esc(r.end_reason || "失败")}</span>`
             : `<span class="pill warn" title="还没结束,或结束原因认不出 —— 不算成功也不算失败">${esc(r.end_reason || (r["结束了吗"] ? "结束原因不明" : "未结束"))}</span>`}</td>
        <td><button data-tr="${esc(r.id)}">看调用树</button></td>
      </tr>`).join("")
    + `</tbody></table>${页码条(d)}<div class="note">${md(d.note || "")}</div>`;
  挂页码($("#main"), (n) => 页_调用链(n));
  $("#main").querySelectorAll("[data-tr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/trace/" + encodeURIComponent(b.dataset.tr); };
  });
}

// 聊天站那一轮的「结论 ↔ 证据逐句核对」(用户 2026-10-25 拍:后台也要看得到)。规则在聊天站 agentsite/claims.py 判,
// 这里只画。有问题的句子排前面;没授权时服务端只给状态和出处路径,句子正文不给(和每一步的入 / 出同一条授权)
const _核色 = { "已核对": "ok", "存在冲突": "fail", "缺少依据": "warn", "未判定": "" };
function 画逐句核对(k, 脱) {
  if (!k) return `<h2>结论和证据逐句核对</h2><div class="state">这一轮没有逐句核对 —— 不是聊天站的运行,或是 10-25 之前推过来的</div>`;
  const 计 = k["计数"] || {};
  const 序 = { "存在冲突": 0, "缺少依据": 1, "已核对": 2, "未判定": 3 };
  const 句们 = (k["句们"] || []).filter((x) => x["状态"] !== "未判定")
    .sort((a, b) => 序[a["状态"]] - 序[b["状态"]]);
  return `<h2>结论和证据逐句核对</h2>
    <div class="cards">
      ${["已核对", "存在冲突", "缺少依据", "未判定"].map((n) =>
        _卡(n, 计[n] || 0, n === "存在冲突" && (计[n] || 0) > 0, "", "聊天站推送时判的快照")).join("")}
    </div>`
    + 句们.map((x) => `<div class="card">
        <div class="k"><span class="pill ${_核色[x["状态"]] || ""}">${esc(x["状态"])}</span>
          ${脱 ? `<span class="k">(句子正文要「查看敏感输入」授权)</span>` : esc(String(x["句"] || "").slice(0, 160))}</div>
        ${!脱 && x["理由"] ? `<div class="k">${esc(x["理由"])}</div>` : ""}
        ${(x["依据"] || []).length ? `<div class="k">出处:${(x["依据"] || []).map((d) =>
            `${!脱 && d["值"] ? esc(d["值"]) + " ← " : ""}${esc(d["工具"] || "")} ${esc(d["路径"] || "")}`).join(" · ")}</div>` : ""}
      </div>`).join("")
    + `<div class="note">${esc(k["说明"] || "")}</div>`;
}

async function 页_调用树(tid) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/traces">调用链</a> · 调用树</div>
    <div class="head"><div><h1>调用树</h1>
      <div class="sub">${esc(tid)}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces/${encodeURIComponent(tid)}`); }
  catch (e) { const s = 错误块(e, () => 页_调用树(tid)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 脱 = !d["看得到原文吗"];
  $("#main").innerHTML = 头
    + (d.note ? `<div class="note ${脱 ? "" : "warn"}">${md(d.note)}</div>` : "")
    + `<div class="cards">
        ${_卡("步数", d["步数"], false, d["被截断了"] ? "被截断了" : "全部", "spans 表")}
        ${_卡("原文", 脱 ? "看不到" : "看得到", 脱,
              脱 ? "要「查看敏感输入/独立测试答案」授权" : "你有这条专项授权", "字段权限")}
      </div>
    <h2>用量</h2>`
    + ((d["用量"] || []).length
        ? `<table><thead><tr><th>用途</th><th>谁提供的</th><th>调用方</th>
             <th class="num">token</th><th class="num">金额</th></tr></thead><tbody>`
          + d["用量"].map((u) => `<tr><td>${esc(u.resource)}</td>
              <td>${u.provider ? esc(u.provider) : `<span class="pill">mock</span>`}</td>
              <td>${esc(u.caller || "—")}</td>
              <td class="num">${Number(u["token数"]).toLocaleString()}</td>
              <td class="num">${u["金额未知的行数"] > 0
                    ? `<span class="pill warn">未知</span>`
                    : `$${Number(u["已知金额"]).toFixed(4)}`}</td></tr>`).join("")
          + `</tbody></table>`
        : `<div class="state">这次运行没有用量记录</div>`)
    + 画逐句核对(d["结论"], 脱)
    + 画标注块(d["标注"])
    + `<h2>每一步</h2>`
    + (d["步们"] || []).map((s2, i) => `<div class="card">
        <div class="k">${i + 1}. ${esc(s2.stage)}
          ${s2["出错了吗"] ? `<span class="pill fail">出错</span>` : ""}</div>
        <pre data-raw="原文" class="k">${esc(JSON.stringify(
            脱 ? {入: s2["入_形状"], 出: s2["出_形状"], 错: s2["错_形状"]}
               : {入: s2["入"], 出: s2["出"], 错: s2["错"]}, null, 1))}</pre>
      </div>`).join("");
  挂标注块(d, tid);
}

/* ── 标注回复(11-21;用户 10-27 拍第 7 条)──────────────────────────────
 * 日志里一轮聊天站问答 → 点「标注成标准答案」写一条;项目总开关开了之后,聊天站对新问题先问模型「和哪条标注同义」,命中直接回。
 * 三条口径(用户 11-21 拍):能不能标由服务端按那一轮调过的工具判(取数 / 写工具的不许,原因写在块里);
 * 要「改 Prompt/知识候选」权限 + 看得到提问原文;总开关默认关、开了保存即生效。这里只画,规则不在前端。 */
function 画标注块(标) {
  if (!标) return "";   // 不是聊天站的一轮,服务端不给这块
  let 体;
  if (标["已有"]) {
    const a = 标["已有"];
    体 = `<div class="card"><div class="k"><span class="pill ${a.status === "启用" ? "ok" : ""}">${esc(a.status)}</span>
        已标成标准答案 · 命中 ${Number(a.hit_count || 0)} 次 · ${esc(a.created_by || "")}
        <a href="#/annotations" style="margin-left:8px">去「标注回复」页改 →</a></div>
      <pre class="k" data-raw="原文">${esc(a.standard_answer || "")}</pre>
      ${a.note ? `<div class="k">备注:${esc(a.note)}</div>` : ""}</div>`;
  } else if (!标["可以吗"]) {
    体 = `<div class="state">这一轮**不能标**:${md(标["原因"] || "")}
      ${(标["调过的工具"] || []).length ? `<div class="k">调过的工具:${esc((标["调过的工具"] || []).join("、"))}</div>` : ""}</div>`;
  } else if (!标["有权标吗"]) {
    体 = `<div class="state">这一轮可以标,但你标不了:${esc(标["没权的原因"] || "")}</div>`;
  } else {
    体 = `<div class="card" id="ann-form">
      <div class="k">这一轮只调了知识类工具${(标["调过的工具"] || []).length ? `(${esc((标["调过的工具"] || []).join("、"))})` : "(一个工具没调)"},
        可以标成标准答案。以后同义的新问题会**直接回这条**、不再调模型 —— 所以只标那种答案不随数据变的问题。</div>
      <button id="ann-open">标注成标准答案</button>
      <div id="ann-edit" hidden>
        <textarea id="ann-answer" rows="8" style="width:100%" placeholder="标准答案(默认带入这一轮的回答,改到满意再保存)"></textarea>
        <input id="ann-note" style="width:100%;margin-top:6px" placeholder="备注(可不填):为什么这样答、哪天核的">
        <div style="margin-top:6px"><button class="pri" id="ann-save">保存</button> <button id="ann-cancel">取消</button>
          <span class="k" id="ann-msg"></span></div>
      </div></div>`;
  }
  return `<h2>标注回复</h2>` + 体;
}
function 挂标注块(d, tid) {
  const 开 = $("#ann-open");
  if (!开) return;
  // 默认带入这一轮的回答:根步骤(invoke_agent …)的 出.回答;看不到原文的人根本进不到这个分支(服务端 有权标吗 已含原文授权)
  const 根 = (d["步们"] || []).find((s) => !s.parent_span_id && String(s.stage || "").startsWith("invoke_agent"));
  let 回答 = "";
  try { const o = 根 && 根["出"]; const j = typeof o === "string" ? JSON.parse(o) : o; 回答 = (j && j["回答"]) || ""; } catch (e) { 回答 = ""; }
  开.onclick = () => { $("#ann-edit").hidden = false; 开.hidden = true; $("#ann-answer").value = 回答; $("#ann-answer").focus(); };
  $("#ann-cancel").onclick = () => { $("#ann-edit").hidden = true; 开.hidden = false; };
  $("#ann-save").onclick = async () => {
    const 答 = $("#ann-answer").value.trim();
    if (!答) { $("#ann-msg").textContent = "标准答案不能空"; return; }
    $("#ann-save").disabled = true;
    try {
      const r = await 请求(`${P()}/chat-annotations`, { method: "POST",
        body: JSON.stringify({ trace_id: tid, standard_answer: 答, note: $("#ann-note").value.trim() || null }) });
      $("#ann-msg").textContent = r["提示"] || "已存";
      await 页_调用树(tid);
    } catch (e) {
      const b = e.体 || {};
      $("#ann-msg").textContent = `${b.code || "出错"}:${e.message}${b.advice ? " —— " + b.advice : ""}`;
      $("#ann-save").disabled = false;
    }
  };
}

async function 页_标注回复(页 = 1) {
  const 头 = `<div class="crumb">日志与监测 / 标注回复</div>
    <div class="head"><div><h1>标注回复</h1>
      <div class="sub">${md("日志里标出来的**标准答案**。总开关开着时,聊天站对新问题先比对这些标注,命中直接回、不再调模型。"
        + "**实时数据的问题(查客户 / 订单 / 库存 / 任务…)标不了** —— 在调用树页点「标注」时服务端按那一轮调过的工具判。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/chat-annotations?limit=50&page=${页}`); }
  catch (e) { const s = 错误块(e, 页_标注回复); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 开 = !!d["开关"];
  const 开关块 = `<div class="card"><div class="k"><span class="pill ${开 ? "ok" : "warn"}">${开 ? "总开关:开" : "总开关:关"}</span>
      ${开 ? "「启用」的标注聊天站都会拿去比对" : "关着时这些标注一条都不生效(默认关;打开要「改 Prompt/知识候选」权限)"}
      <button id="ann-switch" style="margin-left:8px">${开 ? "关掉" : "打开"}</button> <span class="k" id="ann-switch-msg"></span></div></div>`;
  const 表 = !d.items.length
    ? 状态("", "还没有标注", "到「调用链」里点开聊天站的一轮,只调了知识类工具的那种能「标注成标准答案」。").html
    : `<table><thead><tr><th>角色</th><th>提问</th><th>标准答案</th><th>状态</th><th class="num">命中</th><th>更新</th><th></th></tr></thead><tbody>`
      + d.items.map((a) => `<tr data-id="${esc(a.id)}" data-rev="${esc(String(a.revision || 0))}">
          <td class="k">${esc(a.assistant_role || "—")}</td>
          <td>${a.question != null ? esc(String(a.question).slice(0, 80)) : `<span class="k" title="${esc(a["原文要授权"] || "")}">(原文要授权 · ${Number(a["提问长度"] || 0)} 字)</span>`}</td>
          <td class="ann-answer-cell"><span class="k">${esc(String(a.standard_answer || "").slice(0, 120))}</span></td>
          <td><span class="pill ${a.status === "启用" ? "ok" : ""}">${esc(a.status)}</span></td>
          <td class="num">${Number(a.hit_count || 0)}</td>
          <td class="k">${esc(String(a.updated_at || a.created_at || "").slice(5, 16).replace("T", " "))}</td>
          <td><button data-act="toggle">${a.status === "启用" ? "停用" : "启用"}</button>
              <button data-act="edit">改</button>
              <button data-act="archive">归档</button></td>
        </tr>`).join("")
      + `</tbody></table>${页码条(d)}`;
  $("#main").innerHTML = 头 + 开关块 + 表 + `<div class="note">${md(d.note || "")}</div>`;
  挂页码($("#main"), (n) => 页_标注回复(n));
  $("#ann-switch").onclick = async () => {
    $("#ann-switch").disabled = true;
    try { const r = await 请求(`${P()}/chat-annotations/switch`, { method: "PUT", body: JSON.stringify({ enabled: !开 }) });
          $("#ann-switch-msg").textContent = r.note || ""; await 页_标注回复(页); }
    catch (e) { const b = e.体 || {}; $("#ann-switch-msg").textContent = `${b.code || "出错"}:${e.message}`; $("#ann-switch").disabled = false; }
  };
  $("#main").querySelectorAll("tr[data-id] button[data-act]").forEach((b) => {
    const tr = b.closest("tr"), id = tr.dataset.id, rev = tr.dataset.rev;
    const 发 = async (方法, 路, 体) => {
      try { await 请求(`${P()}/chat-annotations/${encodeURIComponent(id)}${路}`, { method: 方法, headers: { "If-Match": String(rev) }, body: 体 ? JSON.stringify(体) : undefined }); await 页_标注回复(页); }
      catch (e) { const bb = e.体 || {}; $("#ann-switch-msg").textContent = `${bb.code || "出错"}:${e.message}${bb.advice ? " —— " + bb.advice : ""}`; }
    };
    if (b.dataset.act === "toggle") b.onclick = () => 发("PATCH", "", { status: b.textContent === "停用" ? "停用" : "启用" });
    if (b.dataset.act === "archive") b.onclick = () => 发("POST", "/archive");
    if (b.dataset.act === "edit") b.onclick = () => {
      const cell = tr.querySelector(".ann-answer-cell"), 原 = (d.items.find((x) => x.id === id) || {}).standard_answer || "";
      cell.innerHTML = `<textarea rows="6" style="width:100%">${esc(原)}</textarea>
        <div><button class="pri" data-save>保存</button> <button data-cancel>取消</button></div>`;
      cell.querySelector("[data-save]").onclick = () => 发("PATCH", "", { standard_answer: cell.querySelector("textarea").value.trim() });
      cell.querySelector("[data-cancel]").onclick = () => 页_标注回复(页);
    };
  });
}

/* ── 产出监督(2026-10-10)──────────────────────────────────────────────
 * 用户:报告和 agent 建议「是怎么生成的」要能在这里**看 + 打回**。
 * 产出由澜绣推过来(管理后台不反查澜绣的库);打回只记一条决定,由澜绣拉回去执行。
 * ⚠️ 路由叫 #/outputs 不叫 #/artifacts —— 后者已经是「模型产物」(微调训练那一组)。 */
const _产出状态色 = { "正常": "ok", "已打回待执行": "warn", "已执行": "", "执行失败": "fail" };
let _产出筛 = { 类型: "", 状态: "" };
async function 页_产出监督() {
  const 头 = `<div class="crumb">日志与监测 / 产出监督</div>
    <div class="head"><div><h1>产出监督</h1>
      <div class="sub">${md(`门店助手写出来的**日报 / 周报 / 月报**和上新时给导购的**建议**,每一份都在这里:`
        + `用了哪些规矩、照着什么数据、哪个模型、写出了什么。不满意就**打回** ——`
        + `建议会由澜绣按你写的理由自动重写一版,报告会在店长那边标「被管理平台打回」、不许确认。`)}</div>
    </div></div>`;
  const 筛 = `<div class="filters">
      类型 <select id="of-k"><option value="">全部</option><option>报告</option><option>建议</option></select>
      状态 <select id="of-s"><option value="">全部</option><option>正常</option><option>已打回待执行</option>
        <option>已执行</option><option>执行失败</option></select></div>`;
  // 整页一次画完再挂事件 —— 先画「加载中」再换掉其中一块的写法,在冒烟的 DOM 桩上换不掉(10-10 实测)
  const 挂筛 = () => {
    $("#of-k").value = _产出筛.类型; $("#of-s").value = _产出筛.状态;
    $("#of-k").onchange = () => { _产出筛.类型 = $("#of-k").value; 页_产出监督(); };
    $("#of-s").onchange = () => { _产出筛.状态 = $("#of-s").value; 页_产出监督(); };
  };
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const q = new URLSearchParams({ limit: "100" });
  if (_产出筛.类型) q.set("类型", _产出筛.类型);
  if (_产出筛.状态) q.set("状态", _产出筛.状态);
  let d;
  try { d = await 请求(`${P()}/artifacts?${q}`); }
  catch (e) { const s = 错误块(e, 页_产出监督); $("#main").innerHTML = 头 + 筛 + s.html; 挂筛(); s.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 筛 + 状态("", (_产出筛.类型 || _产出筛.状态) ? "这个筛选下没有产出" : "还没有产出推过来",
      "店长在助手里存一份报告、或者上新时给导购写了建议,澜绣就会把它推到这里。").html;
    挂筛();
    return;
  }
  $("#main").innerHTML = 头 + 筛 + `<table><thead><tr>
      <th>什么时候</th><th>类型</th><th>标题</th><th>门店</th><th class="num">版本</th>
      <th>怎么写的</th><th>状态</th><th></th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td class="k">${esc(String(r.created_at).slice(5, 16).replace("T", " "))}
          ${r["世界日期"] ? `<div class="k">世界日 ${esc(r["世界日期"])}</div>` : ""}</td>
        <td>${esc(r["类型"])}</td>
        <td>${esc(r["标题"])}<div class="k">${esc(r["外部id"])}</div></td>
        <td>${esc(r["门店"] || "—")}</td>
        <td class="num">${r["版本"]}</td>
        <td>${esc(r["生成方式"] || "—")}${r["模型"] ? `<div class="k">${esc(r["模型"])}</div>` : ""}</td>
        <td><span class="pill ${_产出状态色[r["状态"]] || ""}">${esc(r["状态"])}</span>
          ${r["最近打回理由"] ? `<div class="k">${esc(r["最近打回理由"])}</div>` : ""}</td>
        <td><button data-out="${esc(r.id)}">看详情</button></td></tr>`).join("")
    + `</tbody></table><div class="note">共 ${d.total} 份${d.total > d.items.length ? `,这一页列了 ${d.items.length} 份` : ""}</div>`;
  挂筛();
  $("#main").querySelectorAll("[data-out]").forEach((b) => {
    b.onclick = () => { location.hash = "#/output/" + encodeURIComponent(b.dataset.out); };
  });
}

async function 页_产出详情(id) {
  const 头 = `<div class="crumb">日志与监测 / <a href="#/outputs">产出监督</a> · 详情</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/artifacts/${encodeURIComponent(id)}`); }
  catch (e) { const s = 错误块(e, () => 页_产出详情(id)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 链 = d["关联调用链"] || {};
  const 能打回 = 能力.includes("改训练样本");
  const 待执行 = d["状态"] === "已打回待执行";
  $("#main").innerHTML = 头
    + `<div class="head"><div><h1>${esc(d["标题"])}</h1>
        <div class="sub">${esc(d["类型"])} · ${esc(d["门店"] || "—")} · 第 ${d["版本"]} 版 ·
          ${esc(d["生成方式"] || "—")}${d["模型"] ? " · " + esc(d["模型"]) : ""} ·
          <span class="pill ${_产出状态色[d["状态"]] || ""}">${esc(d["状态"])}</span></div></div></div>`
    + `<div class="note">${md("**打回后会发生什么:**" + d["打回后会发生什么"])}</div>`
    + (d["入库时打码了几处手机号"] ? `<div class="note warn">${md(`入库时把 **${d["入库时打码了几处手机号"]}** 处完整手机号打了码 —— 发送方漏了,要回头查澜绣那边`)}</div>` : "")
    + `<h2>对应调用链</h2><div class="card">`
    + (链.trace_id ? `<a href="#/trace/${encodeURIComponent(链.trace_id)}">${esc(链.trace_id)}</a> · ${esc(链["说明"])}`
                   : `<span class="k">${esc(链["说明"] || "没有")}</span>`)
    + `</div><h2>用了哪些规矩(上报那一刻的快照)</h2>`
    + ((d["规则"] || []).length ? d["规则"].map((r) => `<div class="card"><div class="k">${esc(r["编号"])}</div>
        <pre class="io" data-raw="原文">${esc(r["正文"])}</pre></div>`).join("")
                                  : `<div class="state">这份产出没有登记规矩</div>`)
    + `<h2>输出</h2><div class="card"><pre class="io" data-raw="原文">${esc(d["输出"])}</pre></div>`
    + `<h2>输入(照着什么数据写的)</h2><details><summary>展开看完整输入</summary>
        <pre data-raw="原文" class="k">${esc(JSON.stringify(d["输入"], null, 2))}</pre></details>`
    + `<h2>版本历史</h2><table><thead><tr><th class="num">版本</th><th>什么时候</th><th>状态</th></tr></thead><tbody>`
    + d["版本们"].map((v) => `<tr><td class="num">${v.id === d.id ? `<b>${v["版本"]}</b>`
          : `<a href="#/output/${encodeURIComponent(v.id)}">${v["版本"]}</a>`}</td>
        <td class="k">${esc(String(v.created_at).slice(5, 16).replace("T", " "))}</td>
        <td><span class="pill ${_产出状态色[v["状态"]] || ""}">${esc(v["状态"])}</span></td></tr>`).join("")
    + `</tbody></table><h2>打回历史</h2>`
    + (d["打回历史"].length ? `<table><thead><tr><th>什么时候</th><th>谁</th><th>理由</th><th>执行情况</th></tr></thead><tbody>`
        + d["打回历史"].map((x) => `<tr><td class="k">${esc(String(x.created_at).slice(5, 16).replace("T", " "))}</td>
            <td>${esc(x.created_by)}</td><td>${esc(x["理由"])}</td>
            <td><span class="pill ${x["状态"] === "执行失败" ? "fail" : x["状态"] === "待执行" ? "warn" : ""}">${esc(x["状态"])}</span>
              ${x["结果"] ? esc(x["结果"]) : ""}${x["新版本"] ? ` → 第 ${x["新版本"]} 版` : ""}
              ${x["结果说明"] ? `<div class="k">${esc(x["结果说明"])}</div>` : ""}</td></tr>`).join("")
        + `</tbody></table>` : `<div class="state">还没有打回过</div>`)
    + `<h2>打回</h2>`
    + (!能打回 ? `<div class="note">${md("你的角色没有「改训练样本」这条能力,不能打回 —— 打回是人判内容、会回流成评测样本,归标注员 / 管理员")}</div>`
       : 待执行 ? `<div class="note">${md("这一版已经有一条打回在等澜绣执行,执行完才能再打回")}</div>`
       : `<div class="card"><textarea id="rj-why" rows="3" style="width:100%"
            placeholder="哪里不对?(至少 4 个字)—— 澜绣重写建议时会照着它改"></textarea>
          <div style="margin-top:8px"><button class="pri" id="rj-go">打回这一版</button>
          <span id="rj-msg" class="k"></span></div></div>`);
  const 按 = $("#rj-go");
  if (按) 按.onclick = async () => {
    const 理由 = $("#rj-why").value.trim();
    if (理由.length < 4) { $("#rj-msg").textContent = "理由至少 4 个字"; return; }
    // 11-08 用户拍:打回会触发澜绣那边自动重写
    if (!(await 问一句("打回这一版?", "打回后澜绣会按你写的理由自动重写一版,报告在店长那边标「被管理平台打回」、不许确认。", { 确定: "打回" }))) return;
    按.disabled = true;
    try {
      await 请求(`${P()}/artifacts/${encodeURIComponent(id)}/reject`,
                 { method: "POST", body: JSON.stringify({ 理由 }) });
      await 页_产出详情(id);
    } catch (e) {
      按.disabled = false;
      $("#rj-msg").textContent = ((e.体 && e.体.message) || e.message) + ((e.体 && e.体.advice) ? " —— " + e.体.advice : "");
    }
  };
}

/* ── 智能体健康(M4:/health 重建)────────────────────────────────────
 * ⚠️ **采纳率不是质量分。** 上线之后没有标准答案(线上问题不在评测集里),
 * 能拿到的只有「人采纳了没有」—— 而采纳率高也可能是因为人懒得改。
 * 这一页最重要的事是把这个区别写在脸上。 */
async function 页_智能体健康() {
  const 头 = `<div class="crumb">日志与监测 / 智能体健康</div>
    <div class="head"><div><h1>智能体健康</h1>
      <div class="sub">${md(`上线之后**没有标准答案** —— 能拿到的是采纳率,而它不是质量分。`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/agent-health`); }
  catch (e) { const s = 错误块(e, 页_智能体健康); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 未知 = d["采纳率是未知吗"];
  $("#main").innerHTML = 头 + `
    <div class="cards">
      ${_卡("采纳率", 未知 ? "" : d["采纳率"] + "%", 未知,
            `${d["判读数"]} 条人工判读`, "feedback 表")}
      ${_卡("改判率", 未知 ? "" : d["改判率"] + "%", 未知,
            "**改判最有价值** —— 它能回流成评测样本", "feedback 表")}
      ${_卡("覆盖率", d["这段时间的调用数"]
              ? Math.round(d["判读数"] * 1000 / d["这段时间的调用数"]) / 10 + "%"
              : "", !d["这段时间的调用数"],
            `${d["这段时间的调用数"]} 次调用里有判读的`, "traces + feedback")}
    </div>
    <div class="note warn">${md(d["说明"] || "")}</div>
    <h2>判读分档</h2>`
    + ((d["分档"] || []).length
        ? `<table><thead><tr><th>判读</th><th class="num">条数</th></tr></thead><tbody>`
          + d["分档"].map((x) => `<tr><td>${esc(x["判读"])}</td>
              <td class="num">${x.n}</td></tr>`).join("")
          + `</tbody></table>`
        : `<div class="state"><h3>还没有人工判读</h3>
             <p>${md("澜绣那边接上 A3 上报(`POST /feedback`)之后,这里才会有数。"
                     + "**现在显示「未知」而不是 0** —— 0 意味着「一条都没被采纳」。")}</p></div>`);
}

/* ── 用量与成本 ───────────────────────────────────────────────────
 * ⚠️ **这一页唯一不能做错的事:未知不许显示成 0。**
 *
 * 0 和未知在报表上差别巨大:0 意味着「跑了但不花钱」,
 * 未知意味着「花了多少还不知道」。而一个被压成 0 的未知,
 * **在下游任何一层都分不出来** —— 所以接口给的就是 null,这里也不许填 0。
 *
 * 第二件:**mock 的用量和真的分开显示。**
 * 一份 mock 的用量在数据形状上和真的一模一样,混在一起之后
 * 「这个月花了多少」里就掺着一堆根本没花钱的调用。 */
// 照工作台那套类名画卡(`.cards` / `.card.kpi` / `.n.unknown`)——
// **不另起一套**:两套卡片样式迟早长得不一样,而「未知」那个灰掉的样式
// 正是工作台已经做对的地方。
/* ⚠️ `分母` 过 `md()`、`来源` 用 `esc()` —— 前者是调用方传进来的**文案**
 * (会写加粗),后者是个表名。页面冒烟在 #/health 上抓到过这一处。
 * ⚠️ 这段说明**不能写成 HTML 注释** —— HTML 注释会被渲染进页面,
 * 于是注释里的加粗标记自己触发那条「渲染后不许有字面星号」的判据。
 * 今天同一个形状踩了四次(两次在 `画链路` 的注释里、一次反例照抄、这一次)——
 * **在一个会扫自己产物的判据的视野里,说明要放在不进产物的地方。** */
function _卡(名, 值, 未知, 分母, 来源) {
  const v = 未知 ? `<div class="n unknown">未知</div>`
                 : `<div class="n">${esc(值)}</div>`;
  return `<div class="card kpi"><div class="k">${esc(名)}</div>${v}
    <div class="meta">${分母 ? md(分母) + "<br>" : ""}来源:${esc(来源)}</div></div>`;
}

// ⚠️ 这个函数叫 `_参考价` 不叫 `_钱` —— 用户 2026-09-28 定的:
// **计量按 token 算,价格只给参考**。界面上一律写「参考价」不写「费用」,
// 因为真账单还受批量折扣、协议价、账单延迟、DeepSeek 时段浮动影响。
// > 一个被当成账单用的估算,比没有估算糟。
function _参考价(x) {
  // ⚠️ `x == null` 同时接住 null 和 undefined。写成 `x === null` 的话,
  // 一个字段名拼错(拿到 undefined)会显示成 `undefined`,而不是「未知」——
  // 那种时候更该显示「未知」,因为我们确实不知道。
  return x == null ? `<span class="pill warn">未知</span>` : `$${x.toFixed(4)}`;
}

async function 页_用量与成本() {
  const 头 = `<div class="crumb">日志与监测 / 用量与成本</div>
    <div class="head"><div><h1>用量与成本</h1>
      <div class="sub">${md(`谁花的、花在哪次调用上。**未知显示「未知」,不显示 0。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/usage`); }
  catch (e) { const s = 错误块(e, 页_用量与成本); $("#main").innerHTML = 头 + s.html; s.挂(); return; }

  const 合 = d["合计"] || {};
  const 不可信 = (合["算不出参考价的行数"] || 0) > 0;
  $("#main").innerHTML = 头 + `
    <div class="cards">
      ${_卡("调用次数", 合["调用次数"], false, d["时间范围"], "usage_ledger 表")}
      ${_卡("token 数", (合["token数"] || 0).toLocaleString(), false,
            "所有用途合计（真的和 mock 都算）", "usage_ledger 表")}
      ${_卡("参考价(不是账单)", 合["参考价"], 不可信,
            不可信 ? `${合["算不出参考价的行数"]} 行算不出金额` : "全部算得出",
            "usage_ledger 表")}
    </div>
    ${不可信 ? `<div class="state err"><h3>总额不可信</h3><p>${md(d["参考价怎么读"])}</p>
       <p>${md(d["为什么有算不出的"])}</p></div>` : ""}

    <h2>按调用方 —— ${md("**谁花的**")}</h2>
    <div class="note">${md(`⚠️ 这一张是 A1 上报链存在的**全部理由**。
      只有「按用途」的话,门店助手和管理后台自己的调用混在同一个用途里,
      **「门店助手今天花了多少」答不出来**,只答得出「一共花了多少」。`)}</div>
    <table><thead><tr><th>调用方</th><th>谁提供的</th><th>模式</th>
        <th class="num">调用</th><th class="num">token</th>
        <th class="num">金额</th></tr></thead><tbody>`
    + (d["按调用方"] || []).map((g) => `<tr>
        <td><b>${esc(g["调用方"])}</b></td>
        <td>${g.provider ? esc(g.provider) : `<span class="k">—</span>`}</td>
        <td>${g.source === "mock"
              ? `<span class="pill">mock · 没花钱</span>`
              : `<span class="pill ok">live</span>`}</td>
        <td class="num">${g["调用次数"]}</td>
        <td class="num">${Number(g["token数"]).toLocaleString()}</td>
        <td class="num">${g["金额未知的行数"] > 0
              ? `<span class="pill warn">未知</span>`
              : `$${Number(g["已知金额"]).toFixed(4)}`}</td>
      </tr>`).join("")
    + `</tbody></table>

    <h2>按用途</h2>
    <div class="note">${md(`⚠️ **「谁提供的」要和「用途」一起看** ——
      一份 mock 的用量在数据形状上和真的一模一样。
      这段时间里**真花过钱的用途有 ${d["真花过钱的用途数"]} 个**。`)}</div>
    <table><thead><tr><th>用途</th><th>谁提供的</th>
        <th class="num">调用</th><th class="num">token</th>
        <th class="num">金额</th></tr></thead><tbody>`
    + (d["按用途"] || []).map((g) => `<tr>
        <td><b>${esc(g.resource)}</b></td>
        <td>${g.source === "mock"
              ? `<span class="pill">mock · 没花钱</span>`
              : `<span class="pill ok">${esc(g.source)}</span>`}</td>
        <td class="num">${g["调用次数"]}</td>
        <td class="num">${Number(g["token数"]).toLocaleString()}</td>
        <td class="num">${g["金额未知的行数"] > 0
              ? `<span class="pill warn">未知</span><div class="k">${g["金额未知的行数"]} 行</div>`
              : `$${Number(g["已知金额"]).toFixed(4)}`}</td>
      </tr>`).join("")
    + `</tbody></table>

    <h2>明细</h2>
    <table><thead><tr><th>时间</th><th>调用方</th><th>用途</th><th>档</th>
        <th class="num">数量</th><th class="num">金额</th>
        <th>哪次调用</th></tr></thead><tbody>`
    + (d.items || []).map((r) => `<tr>
        <td class="k">${esc(String(r.created_at).slice(5, 19).replace("T", " "))}
            ${r.world_date ? `<div class="k">世界 ${esc(r.world_date)}</div>` : ""}</td>
        <td>${r.caller ? esc(r.caller) : `<span class="pill warn">没标调用方</span>`}</td>
        <td>${esc(r.resource)} ${r["是mock吗"] ? `<span class="pill">mock</span>` : ""}</td>
        <td class="k">${esc(r["档"] || "")}</td>
        <td class="num">${Number(r.quantity).toLocaleString()} ${esc(r.unit)}</td>
        <td class="num">${_参考价(r["参考价"])}</td>
        <td class="k">${esc(r.trace_id || "")}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">${md(`⚠️ **每次调用写几行,不是一行** —— token 分
         input / output / cache 几档记,因为**它们的单价差一个数量级**。
         合成一个数之后,补上价目表也算不回来了。`)}</div>

    <h2>预算</h2>
    <div id="bdg"><div class="k">正在读预算…</div></div>`;
  await 画预算块();
}

/* ── 预算(11-18 体检查出:后端 GET/POST /budgets 从 09 月就有,前端一页都没调 —— 用量页只看得见花了多少,
 * 设不了也看不见上限)。
 * ⚠️ 三条这一块特有的规矩,全部来自后端那两条接口的注释:
 *   ① **没有某个范围的那一行 = 没设上限**,不是「上限 0」—— 0 的意思是一分都不许花。所以上限 / 已预留是 null 时显示「未知」,不写 0;
 *   ② 「已预留」**不是**「已花」—— 预留是打算花,花掉是已经花。表头照后端的词写,不改成「已用」骗人;
 *   ③ GET 和 POST 要的是同一条能力「配置密钥与预算」(admin)—— 非 admin 连列表都是 403,这一块要自己接住,不能把整页拖红。
 * 空态不许承诺「超线会告警」:alert_rules.py 的 指标们 / 外部指标们 里**没有预算这一项**(11-18 查过),写了就是空头支票。 */
const _预算金额 = (x, 币) => x == null ? `<span class="pill warn">未知</span>` : `${Number(x).toFixed(2)} ${esc(币 || "")}`;

async function 画预算块() {
  const 能设 = 能力.includes("配置密钥与预算") || 我的角色 === "admin";
  let d;
  try { d = await 请求(`${P()}/budgets`); }
  catch (e) {
    const b = e.体 || {};
    if (e.码 === 403) {
      // 预期中的拒绝,不是出错:列表和设预算走同一条能力,看不到就是没这条能力
      $("#bdg").innerHTML = 状态("", "看不到预算", `${b.message || e.message}\n\n${b.advice ? `**下一步:**${b.advice}` : ""}`).html;
      return;
    }
    const s = 错误块(e, 画预算块); $("#bdg").innerHTML = s.html; s.挂(); return;
  }
  const 们 = d["预算"] || [];
  const 表 = !们.length
    ? 状态("", "还没设预算", `没有任何一行 = **没设上限**,不是「上限 0」。设了之后这里显示已预留 / 上限。
        ⚠️ **超线目前不会自动告警** —— 告警页能盯的指标里没有预算这一项,要看得回到这一页。`).html
    : `<table><thead><tr><th>范围</th><th>周期</th><th class="num">已预留 / 上限</th><th class="num">还能预留</th><th>说明</th></tr></thead><tbody>`
      + 们.map((r) => `<tr>
        <td><b>${esc(r["范围"])}</b><div class="k">${esc(r.id || "")}</div></td>
        <td>${esc(r["周期"])}</td>
        <td class="num">${_预算金额(r["已预留"], r["币种"])} / ${_预算金额(r["上限"], r["币种"])}</td>
        <td class="num">${_预算金额(r["还能预留"], r["币种"])}</td>
        <td class="k">${md(r.note || "")}</td>
      </tr>`).join("")
      + `</tbody></table>`;
  const 选 = (id, 项们) => `<select id="${id}">${项们.map((v) => `<option value="${v}">${v}</option>`).join("")}</select>`;
  const 表单 = 能设
    ? `<h3>设一条预算</h3>
      <div class="note">${md("同一个「范围 + 周期」再设一次是**改上限**,不是再建一行。想表达「不限」就别设;`0` 是一分都不许花。")}</div>
      <label class="f">范围 <span class="req">*</span></label>${选("bdg-scope", ["project", "connection"])}
      <label class="f">周期 <span class="req">*</span></label>${选("bdg-period", ["day", "month", "total"])}
      <label class="f">上限 <span class="req">*</span></label><input id="bdg-limit" type="number" min="0" step="0.01" placeholder="比如 50" style="width:100%">
      <label class="f">币种 <span class="req">*</span> <span style="color:var(--ink3)">不给默认值 —— 两个币种混在一列里,合计是个没意义的数</span></label><input id="bdg-cur" placeholder="比如 USD" style="width:100%">
      <button class="pri" id="bdg-go">设预算</button>
      <div id="bdg-fb"></div>`
    : `<div class="k">设预算要「配置密钥与预算」这条能力(admin 才有),你是 ${esc(我的角色 || "?")} —— 所以这里不摆表单。要设请让管理员在「成员与权限」里授权。</div>`;
  $("#bdg").innerHTML = `${们.length ? `<div class="k">${esc(String(d["条数"] != null ? d["条数"] : 们.length))} 条</div>` : ""}${表}
    <div class="note">${md(d.note || "")}</div>
    <div class="card">${表单}</div>`;
  if (!能设) return;
  $("#bdg-go").onclick = async () => {
    const fb = $("#bdg-fb");
    const 上限文 = ($("#bdg-limit").value || "").trim();
    // 空就送 null,让后端那句「上限必填,想不限就别建这一行」原话显示出来,不在前端另写一份口径
    const 体 = { 范围: $("#bdg-scope").value, 周期: $("#bdg-period").value,
      上限: 上限文 === "" ? null : Number(上限文), 币种: ($("#bdg-cur").value || "").trim() };
    $("#bdg-go").disabled = true;
    fb.innerHTML = `<div class="k">提交中…</div>`;
    try {
      const r = await 请求(`${P()}/budgets`, { method: "POST", body: JSON.stringify(体) });
      await 画预算块();
      $("#bdg-fb").innerHTML = `<div class="note"><b>${r["新建了吗"] === false ? "改了上限" : "已建"} ${esc(r.id || "")}</b> · ${esc(r["范围"] || "")} / ${esc(r["周期"] || "")}<br>${md(r.note || "")}</div>`;
    } catch (e) {
      $("#bdg-go").disabled = false;
      const b = e.体 || {};
      // 422 的 field_errors 是 {闸: [一条条的问题]};逐条列出来,每条自己带着 ** 所以过 md()
      const 条 = Object.entries(b.field_errors || {}).map(([k, v]) =>
        `<li><b>${esc(k)}</b>:${md(Array.isArray(v) ? v.join(";") : String(v))}</li>`).join("");
      fb.innerHTML = `<div class="state err"><h3>${esc(b.code || "出错了")} · ${esc(e.message)}</h3>
        ${条 ? `<ul>${条}</ul>` : ""}<p>${md(b.advice ? `**下一步:**${b.advice}` : "服务端没给建议")}</p></div>`;
    }
  };
}

/* ── 加资料(上传三步)─────────────────────────────────────────────
 * ⚠️ **这一页的全部价值是让「上传成功不等于内容可用」看得见**(规格 §17.1)。
 *
 * 界面上最容易犯的错是进度条走到 100% 就显示「成功」—— 那时候字节确实到了,
 * 而**内容还没被校验过**。于是用户以为资料能用了,直到建索引时报「解析失败」,
 * 而他会以为是解析器坏了。
 *
 * 所以这一页把三步分开显示,而且**第二步结束时明确写「还不能用」**:
 *
 *     ① 要地址   POST /uploads              → 待上传
 *     ② 传字节   PUT  /uploads/{id}/bytes   → 已上传(**还不能引用**)
 *     ③ 校验     POST /uploads/{id}/complete → 已校验 / 校验失败
 *
 * 校验没过是 **200 + 通过=false**,不是请求出错 —— 所以这里不能走 错误块(),
 * 要把「哪条规则没过、为什么」显示出来。一个坏文件不是一次失败的请求。 */
const _上传状态色 = { "待上传": "", "已上传": "warn", "已校验": "ok",
                  "校验失败": "fail", "已放弃": "" };

async function 页_加资料() {
  const 头 = `<div class="crumb">知识库 / 加资料</div>
    <div class="head"><div><h1>加资料</h1>
      <div class="sub">${md(`选文件 → 传 → **服务端校验**。只有「已校验」才算能用的文件引用(§17.1)。`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/uploads?limit=50`); }
  catch (e) { const s = 错误块(e, 页_加资料); $("#main").innerHTML = 头 + s.html; s.挂(); return; }

  $("#main").innerHTML = 头 + `
    <div class="card">
      <label class="f">选一个文件</label>
      <input type="file" id="f" accept=".md,.markdown,.txt">
      <button class="pri" id="go">上传并校验</button>
      <div class="note">${md(`收 .md / .markdown / .txt,单个不超过 5 MB。
        **PDF 和扫描件要 OCR,这一版没接** —— 会在第一步就被拒,不会让你白传一遍。`)}</div>
      <div id="步"></div>
    </div>
    <h2>传过的</h2>
    <div id="表"></div>`;
  画上传表(d);
  $("#go").onclick = 走三步;
}

function 画上传表(d) {
  const t = $("#表");
  if (!d.items.length) { t.innerHTML = `<div class="state">还没传过东西</div>`; return; }
  t.innerHTML = `<table><thead><tr>
      <th>文件</th><th>状态</th><th>能引用吗</th><th class="num">字节</th>
      <th>没过的规则</th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td><b>${esc(r.file_name || "")}</b><div class="k">${esc(r.id)}</div></td>
        <td><span class="pill ${_上传状态色[r["状态"]] || ""}">${esc(r["状态"])}</span></td>
        <td>${r["能引用吗"] ? `<span class="pill ok">能</span>`
                            : `<span class="pill fail">不能</span>`}</td>
        <td class="num">${r.byte_count == null ? "—" : r.byte_count}</td>
        <td>${((r["校验详情"] || {})["没过的规则"] || []).map(esc).join("、") || "—"}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">${md(`⚠️ **「能引用的」通常少于总数**(这里 ${d["能引用的"]} / ${d.total})。
         校验失败的那些**留着不删**:一条「传过但没通过」的记录是证据 ——
         删掉之后用户只会再传一次同一个坏文件。`)}</div>`;
}

async function 走三步() {
  const 文件 = $("#f").files[0];
  const 步 = $("#步");
  if (!文件) { 步.innerHTML = `<div class="state err"><h3>先选一个文件</h3></div>`; return; }
  const 画 = (行们) => { 步.innerHTML = `<div class="note">` + 行们.join("<br>") + `</div>`; };
  const 记 = [];
  const 说 = (t) => { 记.push(t); 画(记); };
  try {
    // ① 要地址。**byte_count 必填** —— 不声明就检不出截断上传
    说("① 要上传地址…");
    const a = await 请求(`${P()}/uploads`, {
      method: "POST",
      body: JSON.stringify({ file_name: 文件.name, byte_count: 文件.size,
                             content_type: 文件.type || null }),
    });
    说(`　拿到了,状态 <b>${esc(a["状态"])}</b>(还什么都没传)`);

    // ② 传字节。**这一步之后不许显示「成功」** —— 字节到了不等于内容可用
    说("② 传字节…");
    const r2 = await fetch(a["上传地址"], {
      method: "PUT", headers: { "X-Dev-User": 我, "content-type": "application/octet-stream" },
      body: 文件,
    });
    const b2 = await r2.json().catch(() => null);
    if (!r2.ok) { const e = new Error((b2 && b2.message) || `HTTP ${r2.status}`);
                  e.体 = b2 || {}; e.码 = r2.status; throw e; }
    说(`　字节到了(${b2["收到字节数"]} 字节),状态 <b>${esc(b2["状态"])}</b> —— `
       + `<b>还不能引用</b>,要过校验`);

    // ③ 校验。**没过是 200 + 通过=false**,不是请求出错
    说("③ 服务端校验(算哈希、严格解码、真的调一次解析器)…");
    const c = await 请求(`${P()}/uploads/${encodeURIComponent(a.id)}/complete`,
                        { method: "POST" });
    if (c["通过"]) {
      说(`　<b>已校验 —— 现在才算文件引用</b>。哈希 <code>`
         + esc(String(c.content_hash).slice(0, 26)) + `…</code>,`
         + `切出 ${(c["校验详情"] || {})["细节"]?.["块数"]} 块`);
      // 11-18:原来到这儿就停了 —— 文件校验过了,却没有任何按钮把它收进知识库(接口 POST /knowledge-bases/{kb}/documents 早就有)
      let kbs = { items: [] };
      try { kbs = await 请求(`${P()}/knowledge-bases`); } catch (e2) { /* 读不到就只提示 */ }
      if (kbs.items.length) {
        说(`　收进哪个知识库:<select id="up-kb">${kbs.items.map((k) => `<option value="${esc(k.id)}">${esc(k.name)}</option>`).join("")}</select>
            <button class="pri" id="up-ingest">收进知识库</button> <span class="k" id="up-msg"></span>`);
        const bt = $("#up-ingest");
        if (bt) bt.onclick = async () => {
          bt.disabled = true;
          try {
            const r = await 请求(`${P()}/knowledge-bases/${encodeURIComponent($("#up-kb").value)}/documents`,
                                { method: "POST", body: JSON.stringify({ upload_id: a.id, name: f.name }) });
            $("#up-msg").innerHTML = `收进去了:文档 <code>${esc(r.document_id || r.id || "")}</code>。`
              + `<a href="#/kb/${encodeURIComponent($("#up-kb").value)}">去建一次索引</a>(不建索引,检索还查不到它)`;
          } catch (e3) { const bb = e3.体 || {}; $("#up-msg").innerHTML = `<b style="color:var(--fail)">${esc(bb.message || e3.message)}</b> ${md(bb.advice || "")}`; bt.disabled = false; }
        };
      } else {
        说(`　这个项目还没有知识库:<input id="up-kbname" placeholder="知识库名字" style="width:200px"> <button class="pri" id="up-newkb">新建知识库并收进去</button> <span class="k" id="up-msg"></span>`);
        const nb = $("#up-newkb");
        if (nb) nb.onclick = async () => {
          const 名 = ($("#up-kbname").value || "").trim(); if (!名) { $("#up-msg").textContent = "先给知识库起个名字"; return; }
          nb.disabled = true;
          try {
            const k = await 请求(`${P()}/knowledge-bases`, { method: "POST", body: JSON.stringify({ name: 名 }) });
            const r = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(k.id)}/documents`, { method: "POST", body: JSON.stringify({ upload_id: a.id, name: f.name }) });
            $("#up-msg").innerHTML = `建了「${esc(名)}」并收进去了(文档 <code>${esc(r.document_id || r.id || "")}</code>)。<a href="#/kb/${encodeURIComponent(k.id)}">去建一次索引</a>`;
          } catch (e3) { const bb = e3.体 || {}; $("#up-msg").innerHTML = `<b style="color:var(--fail)">${esc(bb.message || e3.message)}</b> ${md(bb.advice || "")}`; nb.disabled = false; }
        };
      }
    } else {
      const 详 = c["校验详情"] || {};
      说(`　<b>校验没过</b>(而请求本身是成功的 —— 一个坏文件不是一次失败的请求):`);
      (详["理由们"] || []).forEach((x) => 说(`　· <b>${esc(x["规则"])}</b>:${esc(x["为什么"])}`));
      说(`　查了这些规则:${(详["规则全集"] || []).map(esc).join("、")}`);
      说(`　<b>这是终态</b> —— 同一个坏文件重传还是坏的;要传新文件请再走一遍`);
    }
    画上传表(await 请求(`${P()}/uploads?limit=50`));
  } catch (e) {
    const s = 错误块(e, null);
    步.innerHTML = 记.map((x) => `<div class="note">${x}</div>`).join("") + s.html;
  }
}

async function 页_知识库() {
  const 头 = `<div class="crumb">知识库</div>
    <div class="head"><div><h1>知识库</h1>
      <div class="sub">${md(`资料、片段、索引。**有片段不等于能检索** —— 要有一个「已就绪」的索引。`)}</div>
    </div><div><a href="#/uploads"><button>加资料</button></a></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/knowledge-bases`); }
  catch (e) { const s = 错误块(e, 页_知识库); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!d.items.length) {
    // ⚠️ 这段话原来写着「导入资料的接口还没做」。**做完了就要改** ——
    // 一句过期的说明比没有说明糟:它会让人不去试那条已经能用的路。
    const s0 = 状态("", "这个项目还没有知识库",
      "先去「加资料」把文件传上来(**传完还要过服务端校验才算能用**),校验通过后那一页有「收进知识库」;"
      + "收进来再到知识库的「看索引」里点「建一次索引」。\n\n"
      + "现有语料也可以用 `tools/ingest_lanxiu.py` 整批灌(澜绣的业务拍板记录就是这么进的)。",
      { 文: "去加资料", 做: () => { location.hash = "#/uploads"; } });
    $("#main").innerHTML = 头 + s0.html; s0.挂();
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr>
      <th>知识库</th><th class="num">文档</th><th class="num">片段</th>
      <th>能检索吗</th><th>索引</th><th></th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td><b>${esc(r.name)}</b><div class="k">${esc(r.id)}</div></td>
        <td class="num">${r["文档数"]}</td>
        <td class="num">${r["片段数"]}
            ${r["旧版本的片段数"]
              ? `<div class="k">索引收 ${r["最新版片段数"]}</div>` : ""}</td>
        <td>${r["能检索吗"]
              ? `<span class="pill ok">能</span>`
              : `<span class="pill fail">不能</span>
                 <div class="k">${md(r["为什么不能检索"] || "")}</div>`}</td>
        <td>${r["就绪索引数"]} 个已就绪 ${_mock标(r["索引是mock吗"])}
            ${r["索引模型"] ? `<div class="k">${esc(r["索引模型"])}</div>` : ""}</td>
        <td><button data-kb="${esc(r.id)}">看索引</button>
            <button data-docs="${esc(r.id)}">看文档</button>
            <button data-chunks="${esc(r.id)}">看切片</button>
            ${r["能检索吗"] ? `<button data-try="${esc(r.id)}">去检索</button>` : ""}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">${md(`⚠️ **「片段数」是资料切出来的条数,不是索引里的条数。**
         点「看索引」能看到每次构建的成员数。
         ⚠️ **而这两个数对不上有两种原因,别混**(2026-10-08 实测撞到):
         ① 索引不完整 —— 要去查谁写坏了数据;
         ② 那几条属于**文档的旧版本** —— 索引只收最新版,这完全正常。
         下面那行小字「索引收 N」就是第 ② 种;两种都会让索引**少返回几条而不报错**。`)}</div>`
    + (d.items.filter((r) => r["片段数怎么读"]).map((r) =>
        `<div class="note">${md(`**${r.name}**:` + r["片段数怎么读"])}</div>`).join(""));
  $("#main").querySelectorAll("[data-kb]").forEach((b) => {
    b.onclick = () => { location.hash = "#/kb/" + encodeURIComponent(b.dataset.kb); };
  });
  $("#main").querySelectorAll("[data-chunks]").forEach((b) => {
    b.onclick = () => {
      location.hash = "#/chunks/" + encodeURIComponent(b.dataset.chunks);
    };
  });
  $("#main").querySelectorAll("[data-docs]").forEach((b) => {
    b.onclick = () => { location.hash = "#/docs/" + encodeURIComponent(b.dataset.docs); };
  });
  $("#main").querySelectorAll("[data-try]").forEach((b) => {
    b.onclick = () => { location.hash = "#/retrieval/" + encodeURIComponent(b.dataset.try); };   // 带上库 id,到了那页就选这个库的索引
  });
}

/* ══════════════════════════════════════════════════════════════════
 * 切片栏目(业务 2026-10-07 要的)
 *
 * 切片级**权限**那一拍是不做(要收紧就拆成独立文档),但**看得见**要做:
 * 人得能回答「我导进去的那段话被切成了什么样」「为什么搜不到」。
 *
 * ## ⚠️ 这一页要显式回答的两件事
 *
 *   「在役索引数 0」  这一段**检索不到** —— 切出来了但没进任何已就绪的索引。
 *                     > 一个在役索引里的片段,和一个切出来没进索引的,
 *                     > **在这张表上长得一模一样** —— 后者检索不到,
 *                     > 看起来却像语料里有。
 *   「混着切的」      这个知识库**建不出索引**(整库查的那道闸)。
 *                     > 而每行标个版本号是不够的:人要把一屏的版本号比一遍
 *                     > 才看得出来,**而那正是「看起来正常」的样子**。
 *                     所以它是顶部一条独立告警,不是表格里的一列。
 * ══════════════════════════════════════════════════════════════ */

/* ⚠️ 分页状态放在模块变量里,**不进 hash**。
 * 取舍说清:这样刷新页面会回到第一页、浏览器后退也不回上一页。
 * 换成 hash 要改现有那套 `slice(n)` 的路由解析(它不解析查询串),
 * 而这一页是第一个有真分页的页面 —— **先把取舍写下来,别让它成为默认**。 */
let _切片页 = { kb: null, off: 0, doc: null };

/* ══════════════════════════════════════════════════════════════════
 * 文档列表(11-18 体检补的)
 *
 * 知识库页每行有「文档数」,而**没有任何地方能看见那几篇是什么** ——
 * 发新版本 / 拆文档都要文档 id,原来只能 curl 切片接口反推。
 * 这一页回答三件事:库里有哪几份资料 / 每份改过几版 / 最新那一版切了几段。
 *
 * ⚠️ 「片段数」是**最新版**的。片段绑的是文档版本不是文档,旧版本的片段留着
 * 但索引不收 —— 接口返回的 note 原样过 md() 摆在底部,别在这儿另写一遍口径。
 * 分页状态照切片页:放模块变量、不进 hash(取舍见 _切片页 上面那段)。
 * ══════════════════════════════════════════════════════════════ */
let _文档页 = { kb: null, off: 0 };

async function 页_文档列表(kbId) {
  if (_文档页.kb !== kbId) _文档页 = { kb: kbId, off: 0 };
  const 每页 = 30;
  const 头 = `<div class="crumb"><a href="#/kb">知识库</a> · 文档</div>
    <div class="head"><div><h1>文档</h1>
      <div class="sub">${md("这个知识库里有哪几份资料、每份改过几版。**改一篇资料不会动旧版本** —— 新版要再建一次索引才生效。")}</div>
    </div><div><a href="#/uploads"><button>加资料</button></a></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const q = new URLSearchParams({ limit: String(每页), offset: String(_文档页.off) });
  let d;
  try {
    d = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(kbId)}/documents?${q}`);
  } catch (e) {
    const s = 错误块(e, () => 页_文档列表(kbId));
    $("#main").innerHTML = 头 + s.html; s.挂(); return;
  }
  const 头2 = `<div class="crumb"><a href="#/kb">知识库</a> · ${esc(d["知识库"].name)} · 文档</div>
    <div class="head"><div><h1>文档</h1>
      <div class="sub">${md("这个知识库里有哪几份资料、每份改过几版。**改一篇资料不会动旧版本** —— 新版要再建一次索引才生效。")}</div>
    </div><div><a href="#/uploads"><button>加资料</button></a>
      <a href="#/chunks/${encodeURIComponent(kbId)}"><button>看切片</button></a></div></div>`;
  if (!d.total) {
    const s = 状态("", "这个知识库还没有文档",
      "先去「加资料」把文件传上来,校验通过后那一页有「收进知识库」。\n\n"
      + "⚠️ **也可能是你的角色看不到这个库里的文档** —— "
      + "「一篇都没有」和「一篇都看不到」在这个列表上长得一模一样,所以这句话要写出来。",
      { 文: "去加资料", 做: () => { location.hash = "#/uploads"; } });
    $("#main").innerHTML = 头2 + s.html; s.挂(); return;
  }
  const 末 = Math.min(_文档页.off + 每页, d.total);
  const 状 = (r) => r["停用了吗"] ? `<span class="pill fail">停用</span>`
    : !r["最新版本"] ? `<span class="pill fail">没有版本</span>`
    : `<span class="pill ok">在用</span>`;
  $("#main").innerHTML = 头2 + `<table><thead><tr>
      <th>名字</th><th>来源</th><th class="num">版本</th><th>最新版本</th><th>状态</th><th></th>
      </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td data-raw="原文"><b>${esc(r["名字"])}</b><div class="k">${esc(r.id)} · 建于 ${时间(r["建于"])}</div></td>
        <td>${esc(r["来源"] || "—")}</td>
        <td class="num">${r["版本数"]}</td>
        <td>${r["最新版本"]
              ? `<code>${esc(r["最新版本"]["哈希前12"] || "(没哈希)")}</code> · ${r["最新版本"]["片段数"]} 段 · v${r["最新版本"]["版次"]}
                 <div class="k">建于 ${时间(r["最新版本"]["建于"])} · ${esc(r["最新版本"].id)}</div>`
              : `<span class="k">—</span>`}</td>
        <td>${状(r)}${r["怎么读"] ? `<div class="k">${md(r["怎么读"])}</div>` : ""}</td>
        <td>${r["最新版本"] && !r["停用了吗"]
              ? `<button data-doc-chunks="${esc(r.id)}">看切片</button>` : ""}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">第 ${_文档页.off + 1}–${末} 篇,共 ${d.total} 篇
         <button id="pv"${_文档页.off ? "" : " disabled"}>上一页</button>
         <button id="nx"${末 < d.total ? "" : " disabled"}>下一页</button>
       </div>
       <div class="note">${md(d.note || "")}</div>`;
  const 跳 = (off) => { _文档页.off = off; 页_文档列表(kbId); };
  if ($("#pv")) $("#pv").onclick = () => 跳(Math.max(0, _文档页.off - 每页));
  if ($("#nx")) $("#nx").onclick = () => 跳(_文档页.off + 每页);
  $("#main").querySelectorAll("[data-doc-chunks]").forEach((b) => {
    // 切片页按 document_id 筛的状态在模块变量里(见 _切片页):先设筛选再换页,到了就只看这一篇
    b.onclick = () => {
      _切片页 = { kb: kbId, off: 0, doc: b.dataset.docChunks };
      location.hash = "#/chunks/" + encodeURIComponent(kbId);
    };
  });
}

async function 页_切片列表(kbId) {
  if (_切片页.kb !== kbId) _切片页 = { kb: kbId, off: 0, doc: null };
  const 每页 = 30;
  const 头 = `<div class="crumb"><a href="#/kb">知识库</a> · 切片</div>
    <div class="head"><div><h1>切片</h1>
      <div class="sub">${md("资料被切成了什么样。**切片级权限不做** —— 要给某几段单独设权限,把它们拆成独立文档。")}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const q = new URLSearchParams({ limit: String(每页), offset: String(_切片页.off) });
  if (_切片页.doc) q.set("document_id", _切片页.doc);
  let d;
  try {
    d = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(kbId)}/chunks?${q}`);
  } catch (e) {
    const s = 错误块(e, () => 页_切片列表(kbId));
    $("#main").innerHTML = 头 + s.html; s.挂(); return;
  }
  if (!d.total) {
    // ⚠️ 用 `状态()` 的标准成语:**拿到 `{html, 挂}` 两个都用**。
    // 原来我传了 `动作` 却不调 `.挂()`、自己手挂一遍 onclick ——
    // 那样能跑,但它是个危险的范本:
    // > 一段「传了动作并挂上了」的代码,和一段「传了动作而忘了调 `挂()`」的,
    // > **在那个按钮上长得一模一样** —— 按钮都在,只是点了没反应。
    const s = 状态("",
      _切片页.doc ? "这篇文档没有切片" : "这个知识库还没有切片",
      _切片页.doc
        ? "换个文档看看,或者清掉筛选。"
        : "先去「加资料」把文件传上来并切片。\n\n"
          + "⚠️ **也可能是你的角色看不到这个库里的文档** —— "
          + "「一条都没有」和「一条都看不到」在这个列表上长得一模一样,"
          + "所以这句话要写出来。",
      _切片页.doc
        ? { 文: "清掉筛选",
            做: () => { _切片页.doc = null; _切片页.off = 0; 页_切片列表(kbId); } }
        : { 文: "去加资料", 做: () => { location.hash = "#/uploads"; } });
    $("#main").innerHTML = 头 + s.html;
    s.挂();
    return;
  }
  // ── 顶部:**先说库级的** ────────────────────────────────────────
  // ⚠️ 2026-10-07 在浏览器里看到详情页才发现:那个库一个索引都没建过,
  // 于是**每一行**都标「检索不到」,而那不是各行自己的问题。
  // > 一个「这一段没进索引」的标记,和一个「整个库从没建过索引」的,
  // > **在那一列上长得一模一样** —— 前者让人去查那一段,后者建一次索引就好。
  const 库告警 = d["这个知识库有索引吗"] ? "" :
    `<div class="state err"><h3>这个知识库还没有索引</h3><p>${md(
      d["没索引会怎样"] || "")}</p></div>`;
  // ── 混版本告警(整库一起看,不受筛选影响)──────────────────────────
  const 告警 = d["混着切的吗"]
    ? `<div class="state err"><h3>这个知识库建不出索引</h3><p>${md(
        "切片器版本:**" + d["切片器版本们"].join(" / ") + "** · 解析器版本:**"
        + d["解析器版本们"].join(" / ") + "**\n\n" + (d["混了会怎样"] || ""))}</p></div>`
    : "";
  const 末 = Math.min(_切片页.off + 每页, d.total);
  const 筛 = _切片页.doc
    ? `<div class="note">只看文档 <code>${esc(_切片页.doc)}</code>
         <button id="clr">看全部</button></div>`
    : "";
  $("#main").innerHTML = 头 + 库告警 + 告警 + 筛 + `<table><thead><tr>
      <th class="num">段</th><th>节路径</th><th>正文</th>
      <th class="num">token</th><th>版本</th><th>索引</th><th></th>
      </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td class="num">${r.ordinal}<div class="k">v${r["版次"]}</div></td>
        <td data-raw="原文">${esc(r.section_path || "—")}
            <div class="k"><a href="#" data-doc="${esc(r["文档id"])}">只看这篇</a></div></td>
        <td data-raw="原文">${esc(r["正文预览"] || "")}${(r["正文长度"] > (r["正文预览"] || "").length) ? "…" : ""}
            <div class="k">${r["正文长度"]} 字</div></td>
        <td class="num">${r["token_count"] ?? "—"}</td>
        <td class="k">${esc(r["chunker_version"] || "(空)")} /
            ${esc(r["parser_version"] || "(空)")}</td>
        <td>${r["在役索引数"]
              ? `<span class="pill ok">在 ${r["在役索引数"]} 个</span>`
              : `<span class="pill fail">检索不到</span>`}</td>
        <td><button data-ch="${esc(r.id)}">详情</button></td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">第 ${_切片页.off + 1}–${末} 条,共 ${d.total} 条
         <button id="pv"${_切片页.off ? "" : " disabled"}>上一页</button>
         <button id="nx"${末 < d.total ? "" : " disabled"}>下一页</button>
       </div>
       <div class="note">${md(
         "⚠️ **这里只给每篇文档最新那一版的切片。** `chunks` 绑的是文档版本,"
         + "而一篇文档有多版 —— 列出所有版本的话会含着已经被改掉的内容,"
         + "而数量看着也像对的。索引取的也是最新版,**列表跟索引一致**才有参考价值。"
         + "\n\n⚠️ 标「检索不到」的那些是**切出来了但没进任何已就绪索引** ——"
         + "它在这张表上和能检索的长得一样,所以这一列必须显式标出来。")}</div>`;
  const 跳 = (off) => { _切片页.off = off; 页_切片列表(kbId); };
  if ($("#pv")) $("#pv").onclick = () => 跳(Math.max(0, _切片页.off - 每页));
  if ($("#nx")) $("#nx").onclick = () => 跳(_切片页.off + 每页);
  if ($("#clr")) $("#clr").onclick = () => { _切片页.doc = null; 跳(0); };
  $("#main").querySelectorAll("[data-ch]").forEach((b) => {
    b.onclick = () => { location.hash = "#/chunk/" + encodeURIComponent(b.dataset.ch); };
  });
  $("#main").querySelectorAll("[data-doc]").forEach((a) => {
    a.onclick = (ev) => { ev.preventDefault(); _切片页.doc = a.dataset.doc; 跳(0); };
  });
}

async function 页_切片详情(chunkId) {
  const 头 = `<div class="crumb"><a href="#/kb">知识库</a> · 切片</div>
    <div class="head"><div><h1>切片详情</h1></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/chunks/${encodeURIComponent(chunkId)}`); }
  catch (e) {
    const s = 错误块(e, () => 页_切片详情(chunkId));
    $("#main").innerHTML = 头 + s.html; s.挂(); return;
  }
  const 头2 = `<div class="crumb"><a href="#/kb">知识库</a> ·
      <a href="#/chunks/${encodeURIComponent(d["knowledge_base_id"])}">${esc(d["知识库名"])}</a>
      · 第 ${d.ordinal} 段</div>
    <div class="head"><div><h1>切片详情</h1>
      <div class="sub" data-raw="原文">${esc(d.section_path || "")}</div></div></div>`;
  // ⚠️ 标题要跟着分档 —— 「这一段检索不到」在整库没索引时是**误导**:
  // 它让人去查这一段出了什么事,而真相是建一次索引就好。
  const 检索 = d["检索得到吗"]
    ? `<span class="pill ok">检索得到</span>`
    : `<div class="state err"><h3>${d["这个知识库有索引吗"]
          ? "这一段检索不到" : "这个知识库还没有索引"}</h3>
        <p>${md(d["为什么检索不到"])}</p></div>`;
  $("#main").innerHTML = 头2 + 检索 + `
    <div class="card"><h3>正文</h3><pre class="io" data-raw="原文">${esc(d.text)}</pre>
      <div class="k">${d.text.length} 字 · ${d["token_count"] ?? "?"} token(粗估)
        · 哈希 ${esc((d["text_hash"] || "").slice(0, 16))}</div></div>
    <table><tbody>
      <tr><th>节路径</th><td data-raw="原文">${esc(d.section_path || "—")}</td></tr>
      <tr><th>各级标题</th><td>${(d["section_titles"] || []).map((x) =>
          `<code>${esc(x)}</code>`).join(" › ") || "—"}
        <div class="k">${md("⚠️ 要按级别做事的一律读**各级标题**(列表),"
          + "别拿分隔符去拆节路径 —— 全库有 29 个标题自己的名字里带那个分隔符")}</div></td></tr>
      <tr><th>切片器 / 解析器</th><td><code>${esc(d["chunker_version"] || "(空)")}</code> /
        <code>${esc(d["parser_version"] || "(空)")}</code>
        <div class="k">${md("**空不等于「和当前一样」** —— 它是这个字段加上之前切的")}</div></td></tr>
      <tr><th>文档版本</th><td>v${d["版次"]} ${d["是最新版吗"]
          ? `<span class="pill ok">最新</span>`
          : `<span class="pill fail">旧版本(索引只取最新版)</span>`}
        <div class="k">${esc(d["document_version_id"])}</div></td></tr>
      <tr><th>原文件</th><td><code>${esc(d["object_key"] || "—")}</code>
        <div class="k">来源:${esc(((d["source_info"] || {})["存储"]) || "(没记)")}</div></td></tr>
      <tr><th>在哪些索引里</th><td>${(d["在哪些索引里"] || []).map((x) =>
          `<span class="pill ${x.status === "已就绪" ? "ok" : "warn"}">${esc(x.status)}</span>
           <code>${esc(x.id)}</code>`).join("<br>") || "—(一个都没有)"}</td></tr>
      <tr><th>谁看得到</th><td>${(d["谁看得到"] || []).map((x) =>
          `<code>${esc(x)}</code>`).join(" ")}
        <div class="k">${esc(d["为什么是这些人"])}</div></td></tr>
    </tbody></table>
    <div class="note">${md("⚠️ **不能单独设这一段的权限。** " + d["为什么不能"])}</div>`;
}

async function 页_索引构建(kbId) {
  const 头 = `<div class="crumb"><a href="#/kb">知识库</a> · 索引构建</div>
    <div class="head"><div><h1>索引构建</h1>
      <div class="sub">每次构建的状态、模型、成员数、输入指纹。</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(kbId)}/index-builds`); }
  catch (e) { const s = 错误块(e, () => 页_索引构建(kbId)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 头2 = `<div class="crumb"><a href="#/kb">知识库</a> · ${esc(d["知识库"].name)}</div>
    <div class="head"><div><h1>索引构建</h1>
      <div class="sub">每次构建的状态、模型、成员数、输入指纹。</div></div></div>`;
  const 建索引卡 = (模型们) => `<div class="card" id="ib-card"><div class="body">
      <div style="font-weight:600;margin-bottom:6px">建一次索引</div>
      <label class="f">Embedding 模型</label>
      <select id="ib-model">${模型们.map((m) => `<option value="${esc(m)}">${esc(m)}${/mock/i.test(m) ? "(mock,相似度是假的)" : ""}</option>`).join("")}</select>
      <div style="margin-top:8px"><button class="pri" id="ib-go">建一次索引</button> <span class="k" id="ib-msg"></span></div>
      <div class="k">${md("会把这个知识库**最新版**的全部片段重新算向量;输入没变会续做、变了新建(§19.3)。真模型要 worker 本机跑,几百片约一两分钟。")}</div>
    </div></div>`;
  // 11-18:原来空态写「建索引的接口还没做」—— 接口(POST index-builds)和 worker 的 index_build 早就有了,页面一直没入口,
  // 只能 curl。现在两种态都摆「建一次索引」,派完用 等任务 等到终态再重画。
  const 已用模型 = [...new Set(d.items.map((r) => r.embedding_model_id).filter(Boolean))];
  const 模型们 = [...new Set([...已用模型, "bge-small-zh-v1.5", "emb-mock"])];
  const 挂建索引 = () => {
    const b = $("#ib-go"); if (!b) return;
    b.onclick = async () => {
      b.disabled = true; $("#ib-msg").textContent = "派任务…";
      try {
        const r = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(kbId)}/index-builds`, {
          method: "POST", headers: { "Idempotency-Key": (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()) },
          body: JSON.stringify({ embedding模型id: $("#ib-model").value }),
        });
        $("#ib-msg").textContent = `任务 ${r.job_id} · ${r.status}${r["怎么办"] ? " · " + r["怎么办"] : ""}`;
        const j = await 等任务(r.job_id, (x, 秒) => { $("#ib-msg").textContent = `任务 ${r.job_id} · ${x.status} · 等了 ${秒} 秒`; }, 300000);
        $("#ib-msg").textContent = `任务 ${r.job_id} · ${j.status}` + (j["error_code"] ? ` · ${j["error_code"]}:${((j["error_detail"] || {})["为什么"]) || ""}` : "");
        if (j["是终态吗"]) setTimeout(() => 页_索引构建(kbId), 1200);
      } catch (e) { const bb = e.体 || {}; $("#ib-msg").innerHTML = `<b style="color:var(--fail)">${esc(bb.message || e.message)}</b> ${md(bb.advice || "")}`; }
      b.disabled = false;
    };
  };
  if (!d.items.length) {
    $("#main").innerHTML = 头2 + 状态("", "还没建过索引",
      "没有索引时检索返回空,**而那和「知识库里没有」长得一样**。在下面建一次。").html + 建索引卡(模型们);
    挂建索引();
    return;
  }
  $("#main").innerHTML = 头2 + 建索引卡(模型们) + `<table><thead><tr>
      <th>构建</th><th>状态</th><th>模型</th><th class="num">成员</th>
      <th>输入指纹</th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td class="num">${esc(r.id)}<div class="k">${esc(r.created_at || "")}</div></td>
        <td><span class="pill ${r.status === "已就绪" ? "ok" : (r.status === "失败" ? "fail" : "warn")}">${esc(r.status)}</span></td>
        <td>${esc(r.embedding_model_id || "—")} ${r.embedding_dim ? `<span class="k">${r.embedding_dim} 维</span>` : ""}
            ${_mock标(r["是mock吗"])}</td>
        <td class="num">${r["成员数"]}</td>
        <td class="k">${esc(r["输入指纹短"] || "**没记**")}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">${md(`**输入指纹**覆盖:文档版本集合 + 检索配置 + Embedding 模型与维度
         + 切片器版本 + 解析器版本。少一项就会在**变过的输入上续做** ——
         产出一半旧边界一半新边界的索引,而它**不报错**,只是答得怪(§19.3)。
         <br>⚠️ 指纹那一栏写「没记」的是这个字段加上之前建的 ——
         它们会被强制重建,**因为「没记」不等于「一样」**。`)}</div>`;
  挂建索引();
}

/* ── 召回测试(10-27,照 Dify「召回测试」一页;用户 10-26 拍「检索实验室 + 检索试跑记录合成一页」)──
 *
 * 左:源文本输入框 + 测试记录(每页 10 条,点一行把那次的问题填回输入框);右:这次召回到的段落。
 * 和 Dify 不一样的地方,都是我们原来就有、不能丢的:
 *   · 右边结果还是「整条链路」(改写 → 召回 → 精排 → 选片 → 生成),Dify 只给段落和分数;
 *     片段对、答案错这种 RAG 最常见的失效,只看段落看不出来
 *   · 记录里带评价(聊天里的人打的 5 档)和「要分析」
 * ⚠️ **打开页面不再自动跑一次**:原来一进来就真调 Claude 精排,每打开一次都花钱;Dify 也是点「测试」才跑。
 * 「召回设置」只影响这一次测试,不改知识库的设置(Dify 同样如此)。
 */
let 召回态 = { 索引: null, 精排: true, 生成: false, 页: 0, 只看要分析的: false };
const 召回字数上限 = 200;

async function 页_召回测试(指定kb) {
  const 头 = `<div class="crumb">知识库 / 召回测试</div>
    <div class="head"><div><h1>召回测试</h1>
      <div class="sub">根据给定的查询文本测试知识的召回效果。</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let kbs;
  try { kbs = await 请求(`${P()}/knowledge-bases`); }
  catch (e) { const s = 错误块(e, 页_召回测试); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 可用 = kbs.items.filter((x) => x["能检索吗"]);
  if (!可用.length) {
    $("#main").innerHTML = 头 + 状态("", "没有能检索的知识库",
      "要有一个**「已就绪」的索引**才能检索。\n\n"
      + kbs.items.map((x) => `· ${x.name}:${x["为什么不能检索"] || ""}`).join("\n"),
      { 文: "去知识库", 做: () => { location.hash = "#/kb"; } }).html;
    const b = $("#st-act"); if (b) b.onclick = () => { location.hash = "#/kb"; };
    return;
  }
  // 11-18:原来只取 可用[0] 这一个库的索引 —— 真库有两个能检索的库,第二个的索引在页面上选不到,
  // 而 /knowledge-bases 按 updated_at 排、两个都是 null,谁是「第一个」都不确定。现在每个库的就绪索引都列,带库名。
  const 就绪 = [];
  for (const kb of 可用) {
    try {
      const b = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(kb.id)}/index-builds`);
      b.items.filter((x) => x.status === "已就绪").forEach((x) => 就绪.push(Object.assign({ 库名: kb.name, 库id: kb.id }, x)));
    } catch (e) { /* 这个库读不到索引就不列它 */ }
  }
  if (指定kb) { const 首 = 就绪.find((x) => x.库id === 指定kb); if (首) 召回态.索引 = 首.id; }
  if (!就绪.find((x) => x.id === 召回态.索引)) 召回态.索引 = 就绪[0] ? 就绪[0].id : null;
  const 方式名 = () => { const 当 = 就绪.find((x) => x.id === 召回态.索引); return `${当 ? 当.库名 + " · " : ""}${召回态.精排 ? "向量 + Claude 精排" : "只走向量"}${召回态.生成 ? " · 生成答案" : ""}`; };
  $("#main").innerHTML = 头 + `<div class="hit2">
      <div>
        <div class="card"><div class="body">
          <div class="hitbar"><b>源文本</b><button id="ht-set" title="召回设置">${esc(方式名())}</button></div>
          <textarea id="ht-q" rows="5" placeholder="请输入文本,建议使用简短的陈述句。"></textarea>
          <div class="hitbar"><span class="k" id="ht-n">0/${召回字数上限}</span>
            <button class="pri" id="ht-go" disabled>测试</button></div>
          <div class="k" id="ht-err"></div>
        </div></div>
        <h3>记录</h3><div id="ht-rec"><div class="state">加载中…</div></div>
      </div>
      <div><div id="ht-out"><div class="state">召回测试结果将展示在这里</div></div></div>
    </div>`;
  const 框 = $("#ht-q");
  const 核 = () => {
    const n = 框.value.trim().length;
    $("#ht-n").textContent = `${n}/${召回字数上限}`;
    $("#ht-err").textContent = n > 召回字数上限 ? `不超过 ${召回字数上限} 个字符` : "";
    $("#ht-go").disabled = !n || n > 召回字数上限 || !召回态.索引;
  };
  框.oninput = 核;
  框.onkeydown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !$("#ht-go").disabled) 跑(); };
  const 跑 = async () => {
    const q = 框.value.trim();
    const 几次 = (召回态.精排 ? 1 : 0) + (召回态.生成 ? 1 : 0);
    $("#ht-out").innerHTML = `<div class="state">检索中${几次 ? `(要调 ${几次} 次模型,稍等)` : ""}…</div>`;
    let d;
    try {
      d = await 请求(`${P()}/retrieval-tests`, {
        method: "POST",
        body: JSON.stringify({ 索引构建id: 召回态.索引, 问题: q, 要精排: 召回态.精排, 要生成: 召回态.生成 }),
      });
    } catch (e) { const s = 错误块(e, 跑); $("#ht-out").innerHTML = s.html; s.挂(); return; }
    $("#ht-out").innerHTML = `<h3 style="margin-top:0">${esc(d["选了几片"] ?? 0)} 个召回段落</h3>` + 画链路(d);
    召回态.页 = 0; 画召回记录();
  };
  $("#ht-go").onclick = 跑;
  $("#ht-set").onclick = () => 召回设置(就绪, () => { $("#ht-set").textContent = 方式名(); 核(); });
  核();
  await 画召回记录();
}

/* 召回设置:右侧抽屉。**只影响这一次测试**,不改知识库 */
function 召回设置(就绪, 存后) {
  关召回设置();
  const el = document.createElement("div");
  el.id = "drawer-mask"; el.className = "drawer-mask";
  el.innerHTML = `<div class="drawer" role="dialog" aria-modal="true" aria-label="召回设置">
      <div class="mh"><b>召回设置</b><button id="hs-x" aria-label="关闭">×</button></div>
      <div class="mb">
        <div class="k">只影响这一次测试,不改知识库的设置。</div>
        <label class="f">索引</label>
        <select id="hs-ib">${就绪.map((x) => `<option value="${esc(x.id)}" ${x.id === 召回态.索引 ? "selected" : ""}>${esc(x.库名 || "")} · ${esc(x.id)} · ${esc(x.embedding_model_id || "")}${x["是mock吗"] ? "(mock)" : ""}</option>`).join("")}</select>
        <label class="f">检索方式</label>
        <label class="tpl"><input type="checkbox" id="hs-rr" ${召回态.精排 ? "checked" : ""}> <b>Claude 精排</b>
          <div class="k">每次测试真调一次 Claude。去掉就只走向量 —— 那个排序不可靠:实测一个表格头排到过第 1 名,真答案第 2。</div></label>
        <label class="tpl"><input type="checkbox" id="hs-gen" ${召回态.生成 ? "checked" : ""}> <b>生成答案</b>
          <div class="k">再多调一次 Claude,底下多一张答案卡。片段选对了、模型答的时候自己补了内容 —— 只看段落看不出这种失效。</div></label>
        <div class="acts"><button class="pri" id="hs-ok">保存</button> <button id="hs-no">取消</button></div>
      </div></div>`;
  document.body.appendChild(el);
  $("#hs-x").onclick = 关召回设置; $("#hs-no").onclick = 关召回设置;
  el.onclick = (e) => { if (e.target === el) 关召回设置(); };
  $("#hs-ok").onclick = () => {
    召回态.索引 = $("#hs-ib").value || 召回态.索引;
    召回态.精排 = $("#hs-rr").checked; 召回态.生成 = $("#hs-gen").checked;
    关召回设置(); 存后();
  };
}
function 关召回设置() { const m = $("#drawer-mask"); if (m) m.remove(); }

/* 测试记录:每页 10 条,点一行把问题填回输入框;评价(聊天里打的)和「要分析」照旧显示 */
async function 画召回记录() {
  const 盒 = $("#ht-rec"); if (!盒) return;
  let d;
  try {
    d = await 请求(`${P()}/retrieval-runs?limit=10&offset=${召回态.页 * 10}`
      + (召回态.只看要分析的 ? "&只看要分析的=true" : ""));
  } catch (e) { const s = 错误块(e, 画召回记录); 盒.innerHTML = s.html; s.挂(); return; }
  const 汇 = d["汇总"] || {}, 共 = d.total || 0, 页数 = Math.max(1, Math.ceil(共 / 10));
  const 头 = `<div class="hitbar"><span class="k">${md(`共 ${共} 条 · 平均分 ${汇["平均分"] ?? "—"}(${汇["平均分怎么读"] || ""})`)}</span>
      ${汇["要分析的有几条"] || 召回态.只看要分析的 ? `<button id="hr-bad">${召回态.只看要分析的 ? "看全部" : `只看要分析的(${汇["要分析的有几条"]} 条低于 3 分)`}</button>` : ""}</div>`;
  if (!d.items.length) {
    盒.innerHTML = 头 + `<div class="state">最近无查询结果</div>`;
  } else {
    盒.innerHTML = 头 + `<table><thead><tr><th>查询内容</th><th>数据源</th><th>时间</th><th>评价</th><th></th></tr></thead><tbody>`
      + d.items.map((r, i) => `<tr class="hitrow" data-hi="${i}" title="点一下把这句填回输入框">
          <td><b>${esc(r["问题"])}</b>${r["改写"] && r["改写"] !== r["问题"] ? `<div class="k">改写:${esc(r["改写"])}</div>` : ""}</td>
          <td>${r["来源"] === "chat" ? `<span class="pill ok">聊天</span>` : `<span class="pill none">召回测试</span>`}</td>
          <td class="k" style="white-space:nowrap">${esc(String(r["什么时候"] || "").slice(0, 16))}</td>
          <td>${评分块(r)}</td>
          <td><a href="#/rrun/${encodeURIComponent(r.id)}">看详情</a></td></tr>`).join("")
      + `</tbody></table>
      <div class="hitbar"><button id="hr-prev" ${召回态.页 === 0 ? "disabled" : ""}>上一页</button>
        <span class="k">第 ${召回态.页 + 1} / ${页数} 页</span>
        <button id="hr-next" ${召回态.页 + 1 >= 页数 ? "disabled" : ""}>下一页</button></div>`;
    盒.querySelectorAll("[data-hi]").forEach((tr) => {
      tr.onclick = (e) => {
        if (e.target.closest("a")) return;
        const q = $("#ht-q"); if (!q) return;
        q.value = d.items[+tr.dataset.hi]["问题"] || ""; q.dispatchEvent(new Event("input")); q.focus();
      };
    });
    $("#hr-prev").onclick = () => { 召回态.页 -= 1; 画召回记录(); };
    $("#hr-next").onclick = () => { 召回态.页 += 1; 画召回记录(); };
  }
  const bad = $("#hr-bad");
  if (bad) bad.onclick = () => { 召回态.只看要分析的 = !召回态.只看要分析的; 召回态.页 = 0; 画召回记录(); };
}

/* ⚠️ **片段正文带 `data-raw="原文"`,而且故意用 `esc()` 不用 `md()`。**
 *
 * 语料片段**本身就是 Markdown**(那些 md 里到处是加粗),它是**数据不是文案** ——
 * 证据要能让人**照着它翻回原文核对**,渲染成粗体之后它和源文件就不再逐字相同;
 * 而且按 300 字截断会把一对 `**` 截成单边,那时渲染器不认它、星号照样露出来,
 * **只是变成了偶发红**(取决于截断点落在哪)。
 *
 * 这个标记让页面冒烟那条「渲染后不许有字面星号」的判据跳过它,
 * **而豁免因此是有名字的** —— 谁加这个标记,就是在说「这段是原始数据」。
 *
 * ⚠️ 这段说明**原来写在 HTML 注释里,连踩两次**:
 *   ① 里面的反引号在模板字符串里**直接终止了字符串** —— 整个 app.js 语法错,
 *      表现是「框架有、数据一个都不加载」(和 09 月那次 let 重复声明同一族);
 *   ② 去掉反引号之后,注释里的 `**故意**` **被渲染进了 HTML**,
 *      于是星号判据抓到了我自己的注释。
 * > **在一个会扫自己源码的判据的视野里举例,要描述那个坏写法,不能写出来。**
 * 密钥扫描那条规矩连踩三次,是同一件事;所以说明搬到这里 —— JS 注释不进页面。
 */
function 画链路(d) {
  const 行 = (k, v, n) => `<tr><td class="k">${esc(k)}</td><td>${v}${n ? `<div class="k">${n}</div>` : ""}</td></tr>`;
  const 链 = `<div class="card"><div class="k" style="padding:8px 10px 0">整条链路(§9.5)</div>
    <table><tbody>
    ${行("原问", esc(d["原问"]))}
    ${行("改写", d["改写"] === null
          ? `<span class="pill">没做</span>`
          : esc(d["改写"]),
          md(d["改写说明"] || ""))}
    ${行("召回", `${d["召回数"]} 条候选 · ${esc((d["召回方式"] || []).join("、"))}`)}
    ${行("向量", `${esc(d["embedding"]["模型"])} · ${d["embedding"]["维度"]} 维 ${_mock标(d["embedding"]["是mock"])}`)}
    ${行("精排", d["精排"]["做了"]
          ? `${esc(d["精排"]["模型"] || "")} · ${(d["精排"]["用量"] || {}).input_tokens || "?"} in / ${(d["精排"]["用量"] || {}).output_tokens || "?"} out`
          : `<span class="pill warn">没做</span>`,
          d["精排"]["做了"] ? "" : md(d["精排"]["为什么"] || ""))}
    ${行("截断", esc(d["截断"]))}
    ${行("选片", `${d["选了几片"]} 片 · ${d["用了多少token"]} token`,
          d["token是粗估"] ? md("token 数是**粗估** —— 不许拿它算钱") : "")}
    ${行("生成", 生成标(d["生成"]), 生成注(d["生成"]))}
    </tbody></table></div>`;

  const 警 = [];
  if (d["引文没通过校验的"]) 警.push(md(d["引文说明"] || ""));
  if (d["因为太大跳过的"] && d["因为太大跳过的"].length) 警.push(md(d["跳过说明"] || ""));

  const 片 = `<div class="card"><div class="k" style="padding:8px 10px 0">选中的片段(按精排分数)</div>
    ${d["选片"].map((x) => `<div class="body" style="border-top:1px solid var(--line)">
      <div>
        ${x["分数"] === null ? `<span class="pill">未精排</span>`
                            : `<span class="pill ${x["分数"] >= 7 ? "ok" : (x["分数"] >= 4 ? "warn" : "fail")}">${x["分数"]}/10</span>`}
        <span class="k">向量 ${x["相似度"]}</span>
        <b data-raw="原文" style="margin-left:8px">${esc(x["证据"])}</b>
      </div>
      ${x["引文"] ? `<div style="margin:4px 0">
          ${x["引文可信"] === false
            ? `<span class="pill fail" title="${esc(去粗(x["引文问题"] || ""))}">⚠️ 引文不可信</span> `
            : ``}
          <span data-raw="原文">引文「${esc(x["引文"])}」</span>
          ${x["引文可信"] === false
            ? `<div class="k">${md("**这句话在片段里找不到**(模型改写了原话)——"
               + "分数仍然保留,但它给的**理由不可信**。引文的用处是让人照着它"
               + "在原文里搜到那一句,搜不到就等于没有。")}</div>` : ""}
        </div>` : ""}
      <div class="k" data-raw="原文" style="white-space:pre-wrap">${esc((x["文"] || "").slice(0, 300))}</div>
    </div>`).join("")}</div>`;

  return 链
    + (警.length ? `<div class="note warn">${警.join("<br>")}</div>` : "")
    + 画答案(d["生成"])
    + 片
    + `<div class="note">${md(`**证据串**(「业务拍板 · 2026-09-27 / 二、几星算差评 · 第 4 段」)
        不是装饰 —— 顾问要能**照着它翻回原文核对**。
        一个查不回去的引用比没有引用糟:它看起来有出处。`)}</div>`;
}

/* ── 生成那一步(2026-10-08 补的 A)───────────────────────────────────
 *
 * 这一页原来停在「选了哪几片」。它回答得了「它怎么找、找到什么」,
 * **回答不了「它答成什么」** —— 而答案才是顾问真正拿到手的东西。
 *
 * ⚠️ 三种「没有答案」要分得开,而且**不靠认那段文案** ——
 * 接口给了结构化的 `哪一种`(这次没要 / 跑不成 / 炸了)。
 * 认文案会在下一个人改文案的那天静默失效(这个项目为枚举中文说法栽过七次)。
 */
function 生成标(g) {
  g = g || {};
  if (g["做了"]) {
    const u = g["用量"] || {};
    return `${g["够不够答"] === false
      ? `<span class="pill warn">证据不够</span>`
      : `<span class="pill ok">答了</span>`}
      <span class="k">${esc(g["模型"] || "")} · ${u.input_tokens || "?"} in /
      ${u.output_tokens || "?"} out · 引了 ${(g["引用们"] || []).length} 条证据</span>`;
  }
  // ⚠️ 「这次没要」用灰 pill,「跑不成 / 炸了」用红 —— **两种不同颜色**。
  // 同一个灰「没做」会让一次故障看起来像一个选择。
  return g["哪一种"] === "这次没要"
    ? `<span class="pill none">这次没要</span>`
    : `<span class="pill fail">${esc(g["哪一种"] || "没做")}</span>`;
}

function 生成注(g) {
  /* ⚠️ **两条出口都要过 `md()`。** 这里的文字里有 `**` ——
   * 而 `行()` 把 note 原样塞进 `<div class="k">`,不渲染。
   * 页面冒烟当场抓到(`#rr-chain` 上显示着字面星号):
   * > 一句「写了加粗」的文案,和一句「加粗真的生效了」的,
   * > **在源码上长得一模一样** —— 而 `tools/md_render_check.py` 扫的是
   * > 源码里的 `**` 有没有在同一处过 md,接口返回的那半它看不见。
   * 这一条(`g["为什么"]`)正是**从接口来的**。*/
  g = g || {};
  if (g["做了"]) {
    return md("⚠️ 验到的是它**指得出出处**(引用的原话真在证据里)——"
      + "**不是**它没有超出证据。后者要做句子级蕴含,这一版没做");
  }
  return md(g["为什么"] || "");
}

/* 底部那张答案卡。
 * ⚠️ 答案用 `md()` 不用 `esc()`:`md` 自己先 esc 再认 `**`,所以既安全、
 * 又不会把模型写的 `**` 原样显示成星号(10-07 验收时用户用眼睛抓到过
 * 32 处字面星号 —— 那次是文案写了 `**` 而没过 `md()`)。*/
function 画答案(g) {
  g = g || {};
  if (!g["做了"]) {
    // 「这次没要」不值得一张卡(人自己去掉的勾);跑不成要显眼。
    return g["哪一种"] === "这次没要" ? ""
      : `<div class="note warn">${md(g["为什么"] || "生成没做,而没说为什么")}</div>`;
  }
  const 引 = g["引用们"] || [];
  const 坏 = 引.filter((x) => x["原话可信"] === false);
  return `<div class="card"><div class="body">
    <div style="margin-bottom:6px">
      ${g["够不够答"] === false
        ? `<span class="pill warn">模型说证据不够</span>`
        : `<span class="pill ok">照着证据答的</span>`}
      <span class="k" style="margin-left:6px">${esc(g["照着谁答的"] || "")}</span>
      ${坏.length ? `<span class="pill fail" style="margin-left:6px">${坏.length}
        条出处对不上</span>` : ""}
    </div>
    <div style="white-space:pre-wrap;font-size:14px;line-height:1.7">${md(g["答案"] || "")}</div>
    ${g["缺什么"] ? `<div class="note warn" style="margin:8px 0 0">
        ${md("**模型说缺的是**:" + g["缺什么"])}</div>` : ""}
    ${引.length ? `<div class="k" style="margin-top:10px">它指的出处(每条都验过原话真在那片里)</div>
      <table><tbody>${引.map((x) => `<tr>
        <td class="k" data-raw="原文" style="white-space:nowrap">[${x["编号"]}] ${esc(x["证据"] || "")}</td>
        <td>${x["原话可信"] === false
          ? `<span class="pill fail" title="${esc(去粗(x["原话问题"] || ""))}">⚠️ 对不上</span> `
          : ""}<span data-raw="原文">「${esc(x["原话"] || "")}」</span>
          ${x["原话可信"] === false
            ? `<div class="k">${esc(x["原话问题"] || "")}</div>` : ""}</td>
        </tr>`).join("")}</tbody></table>`
      : `<div class="note" style="margin:8px 0 0">${md(
          "它一条出处都没指 —— 而 `enough=false` 时**不要求**出处"
          + "(要求一个「证据里没有」的回答给出引文,等于逼它为不存在的关联编证据)")}</div>`}
    <div class="note" style="margin:10px 0 0">${md(
      `⚠️ **这张卡验到的,和验不到的**:验到了「它指得出的出处真在证据里」`
      + `(编一个不存在的编号、改写原话都会被抓到);**没验**「答案里有没有超出证据的内容」——`
      + `那要做句子级蕴含,是另一次模型调用。\n`
      + `一个「每句话都指得出出处」的答案,和一个「有出处的那几句之外还加了两句自己的」,`
      + `**在这张卡上长得一模一样**。`)}</div>
  </div></div>`;
}

/* ── 检索试跑记录(业务 2026-10-08 要的栏目)─────────────────────────
 *
 * 检索实验室跑一次,结果在页面上,**刷新就没了**。而「这一版检索好不好用」
 * 要靠攒下来的试跑回答 —— 一次试跑是个印象,二十次才是个判断。
 *
 * ⚠️ 业务要的是「记录 chat 里的 RAG 检索」,而 **chat 现在不走这条链**
 * (它走澜绣那边的 V1/V2/V3,自己查 mcp/kb)。所以这个栏目现在全是
 * 实验室自己的试跑 —— 而那句话**写在页面上**:
 * > 一个「记录 chat 检索」的栏目,和一个永远是空的栏目,
 * > 在那个页面上长得一模一样。
 *
 * ⚠️ 打分**就在列表上**,不用点进详情。要人先点进去才拿得到 revision 的话,
 * 打分会被嫌麻烦而没人做 —— 而没人评的话这个栏目就只是一本日志。
 */
/* ⚠️ **class 写成字面量,不拼。** `tools/css_class_check.py` 钉着
 * 「拼出来的 class」的条数(19 处)—— 拼出来的它验不了,
 * 而 10-07 真撞过一次:某一处写了个 CSS 里**根本不存在的 class 名**
 * (那个名字和 `pill` 同义,只是没人定义过它),
 * 页面上那个标记一点样式都没有,而代码读起来完全正常。
 * 所以这里五档各写一份字面 class,而不是把档位变量插进 class 里。
 * ⚠️ **这段注释原来照抄了那个反例写法,于是 `css_class_check` 把注释本身
 * 数成了第 20 处拼接**(上限 19)—— 和密钥扫描那条规矩同一个形状:
 * **被扫描的文件里不要写出真实的匹配串,要举例就描述它。**
 * (那边连踩三次:规矩写进 CLAUDE.md → 文档匹配自己;挪进 .secretscan →
 *  规则文件匹配自己;在脚本注释里举例 → 脚本匹配自己。)*/
const 档位pill = {
  1: (文) => `<span class="pill fail">${文}</span>`,
  2: (文) => `<span class="pill fail">${文}</span>`,
  3: (文) => `<span class="pill warn">${文}</span>`,
  4: (文) => `<span class="pill ok">${文}</span>`,
  5: (文) => `<span class="pill ok">${文}</span>`,
};

function 评分块(r) {
  /* ⚠️ **只展示,不给打分按钮**(业务 2026-10-08 拍:
   *   「chat 问完直接给评分,让使用者来评,ai 管理后台只做展示」)。
   *
   * 这一版**原来是在这一页上打分的** —— 而那等于要顾问为了评一次
   * 专门打开另一个系统:
   * > 一个「有评分功能」的栏目,和一个「没人会去评」的,
   * > **在那个按钮上长得一模一样** —— 而后者的分数永远是空的。
   * 打分搬到了聊天框里(值班台那一页,答完就在气泡下面)。
   *
   * ⚠️ 「低于 3 分 = 要分析」**不在这儿比** —— 接口给了 `要分析吗`。
   * 界面自己比数的话,那个阈值就有了第二个定义点,而改一边不报错。*/
  const 现 = r["评分"];
  if (现 == null) return `<span class="pill none">还没评</span>`;
  const 要分析 = r["要分析吗"] === true;
  return `${档位pill[现] ? 档位pill[现](`${现} · ${esc(r["评分档位"] || "")}`)
            : `<span class="pill none">${现}</span>`}
    ${要分析 ? `<div class="k"><b>要分析</b> —— 打开看它当时找到了哪几段</div>` : ""}
    ${r["评语"] ? `<div class="k">「${esc(r["评语"])}」</div>` : ""}
    ${r["谁评的"] ? `<div class="k">${esc(r["谁评的"])}</div>` : ""}`;
}

let 档位名 = {};        // 从接口的档位表来(不在前端写死一份,两份会漂)

/* ⚠️ **这一页原来能打分,2026-10-08 搬走了。**
 *
 * 业务拍的是:「chat 问完直接给评分,让使用者来评,ai 管理后台只做展示」。
 * 而原来的做法要顾问为了评一次专门打开管理后台 ——
 * > 一个「有评分功能」的栏目,和一个「没人会去评」的,
 * > **在那个按钮上长得一模一样** —— 而后者的分数永远是空的。
 *
 * 打分现在在**聊天框里**(值班台 8770,答完就在气泡下面),
 * 它走 `POST /api/rate-rag` → 由那个站转发到这边的
 * `PATCH /retrieval-runs/{id}/rating`(If-Match 在服务端带,前端不用管)。
 * 这一页只负责**看**:哪几条低于 3 分、点开看它当时找到了哪几段。
 *
 * ⚠️ 打分那条接口**没删** —— 它还在契约里、还有判据(两个人同时评的
 * 静默覆盖那条)。删掉它等于让 chat 那条路也没法评。
 */


function 答案档标(档) {
  if (档 === "答了") return `<span class="pill ok">答了</span>`;
  if (档 === "证据不够") return `<span class="pill warn">证据不够</span>`;
  if (档 === "这次没要") return `<span class="pill none">这次没要</span>`;
  if (档 === "跑不成") return `<span class="pill fail">跑不成</span>`;
  return `<span class="k">—</span>`;
}

async function 页_试跑详情(rid) {
  const 头 = `<div class="crumb">知识库 / <a href="#/retrieval">召回测试</a> / 记录详情</div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  const 拉 = async () => {
    let d;
    try { d = await 请求(`${P()}/retrieval-runs/${encodeURIComponent(rid)}`); }
    catch (e) { const s = 错误块(e, () => 页_试跑详情(rid)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
    档位名 = (d["评价"] || {})["档位表"] || 档位名;
    const 评 = d["评价"] || {};
    const 行 = { id: d.id, 评分: 评["评分"], 评分档位: 评["评分档位"],
                 评语: 评["评语"], revision: d["revision"] };
    $("#main").innerHTML = 头 + `
      <div class="head"><div><h1>${esc(d["问题"])}</h1>
        <div class="sub">${esc(String(d["什么时候"] || "").slice(0, 19))} ·
          ${esc(d["来源"])} · ${esc(d["谁跑的"] || "")} ·
          知识库 ${esc(d["知识库"] || "—")}</div></div></div>
      <div class="card"><div class="body">
        <div class="k">这一次好不好用?(5 档;评分在聊天站的回答气泡下打,这里只看)</div>
        ${评分块(行)}
        ${评["谁评的"] ? `<div class="k">${esc(评["谁评的"])} 评于
           ${esc(String(评["什么时候评的"] || "").slice(0, 19))}</div>` : ""}
      </div></div>
      ${d["隐去了几片正文"]
        ? `<div class="note warn">${md(d["为什么隐去"] || "")}</div>` : ""}
      ${画答案(答案成链形(d))}
      <div id="rr-chain"></div>
      <div class="note">${md(d["note"] || "")}</div>`;
    // ⚠️ **复用检索实验室那一份 `画链路`** —— 不另写一份:
    // > 两份渲染迟早分叉,而分叉时两边各自都显示得很正常。
    // (业务要的就是「内容同检索实验室」。)
    $("#rr-chain").innerHTML = 画链路(d["链路"] || {});
  };
  await 拉();
}

/* 详情接口把答案单独给了一份(`答案`),而 `画答案` 吃的是链路里
 * `生成` 那一块的形状。**转一次,而不是给 `画答案` 加一个分支** ——
 * 加分支会让那一个函数有两种输入形状,而那是漏判的入口。 */
function 答案成链形(d) {
  const a = d["答案"] || {};
  const 档 = d["答案那一档"];
  if (档 === "答了" || 档 === "证据不够") {
    return { 做了: true, 答案: a["答案"], 够不够答: a["够不够答"],
             缺什么: a["缺什么"], 模型: a["模型"], 引用们: a["引用们"] || [],
             引用没通过校验的: a["引用没通过校验的"],
             照着谁答的: "原问(不是改写后的查询)" };
  }
  return { 做了: false, 哪一种: (档 === "这次没要" ? "这次没要" : 档),
           为什么: a["为什么没答"] || "(没记下为什么)" };
}

/* ══════════════════════════════════════════════════════════════════
 * 2026-09-29 补的七页 —— 侧栏上原来点不开的那七个
 * ══════════════════════════════════════════════════════════════════
 *
 * 这七页对应的接口是 09-28~29 两天做的(数据集/训练/发布/连接/设置/工具)。
 * **接口有了不等于人能用** —— 在这之前,这 65 条接口大部分只能用 curl 看。
 *
 * 每一页只突出**一条**最要紧的事,而不是把字段铺满:
 *
 *   审计    → 前面十几块写的留痕,终于读得出来
 *   应用    → **哪一版在给用户跑**(不是「有哪些应用」)
 *   连接    → 密钥**只给形状**;谁**还没探过** capabilities
 *   成员    → 他**实际能做什么**(不只是角色名)
 *   数据集  → **能不能导出,卡在哪**
 *   训练    → **是不是 mock 跑的**(三值:是/否/说不清)
 *   产物    → 这一份**能不能部署,还差什么**
 */

async function 页_审计记录() {
  $("#main").innerHTML = `<div class="crumb">设置 / 审计记录</div>
    <div class="head"><div><h1>审计记录</h1>
      <div class="sub"><b>只追加,不许删也不许改</b>(§15.4)——
        一个能删审计的接口,会让审计在最需要它的那一刻正好是空的。</div></div></div>
    <div class="note">按动作筛:<select id="f-act"><option value="">全部</option></select>
      <button id="f-go">看</button></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  const 拉 = async (动作) => {
    try {
      const q = 动作 ? `?action=${encodeURIComponent(动作)}&days=30` : "?days=30";
      const d = await 请求(`${P()}/audit-events${q}`);
      const sel = $("#f-act");
      if (sel && sel.options.length <= 1) {
        (d["这个范围里的动作分布"] || []).forEach((x) => {
          const o = document.createElement("option");
          o.value = x["动作"]; o.textContent = `${x["动作"]}(${x["次数"]})`;
          sel.appendChild(o);
        });
      }
      if (!d["记录"].length) {
        // ⚠️ 「本来就没有」和「被筛掉了」分开说 —— 接口已经分好了,这里照搬。
        $("#list").innerHTML = 状态("", "这个范围里没有记录", d.note || "").html;
        return;
      }
      $("#list").innerHTML = `<table><thead><tr><th>什么时候</th><th>谁</th>
        <th>做了什么</th><th>对象</th><th>结果</th><th>为什么</th></tr></thead><tbody>`
        + d["记录"].map((r) => `<tr>
          <td class="k">${esc(String(r["什么时候"] || "").slice(0, 19))}</td>
          <td>${esc(r["谁"] || "—")}</td>
          <td><b>${esc(r["做了什么"])}</b></td>
          <td class="k" data-raw="原文">${esc(JSON.stringify(r["对象"] || {}).slice(0, 60))}</td>
          <td>${r["结果"] === "ok" ? `<span class="pill" title="ok">成功</span>`
                : `<span class="pill warn" title="${esc(r["结果"] || "")}">${esc(_英转中[r["结果"]] || r["结果"] || "—")}</span>`}</td>
          <td class="k" data-raw="原文">${esc((r["为什么"] || "—").slice(0, 70))}</td></tr>`).join("")
        + `</tbody></table>`
        + (() => {   // 11-18:后端默认只给 200 条、不给总数;分布之和远大于 200 时原来一个字不提
          const 总 = (d["这个范围里的动作分布"] || []).reduce((n, x) => n + (x["次数"] || 0), 0);
          return 总 > d["记录"].length ? `<div class="note warn">只列了最近 ${d["记录"].length} 条;这个范围(${esc(d["时间范围"] || "最近 30 天")})里按分布算共 ${总} 条 —— 要看别的,按动作筛。</div>` : "";
        })()
        + `<div class="note">${md(d.note || "")}</div>`;
    } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
  };
  await 拉("");
  const go = $("#f-go"); if (go) go.onclick = () => 拉($("#f-act").value);
}

async function 页_应用与发布() {
  $("#main").innerHTML = `<div class="crumb">工作室 / 应用与发布</div>
    <div class="head"><div><h1>应用与发布</h1>
      <div class="sub">这一页回答的是 <b>哪一版在给用户跑</b> ——
        不是「有哪些应用」。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/applications`);
    if (!d["应用"].length) {
      $("#list").innerHTML = 状态("", "还没有应用",
        "建一个应用之后,给它挑齐依赖、出一份发布清单、审核、再发布 ——"
        + "**清单里全是确切版本,不许出现「用最新的那个」**。").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>应用</th><th>流水线</th>
      <th>生产在跑哪一版</th><th>预发</th><th>测试</th><th>候选</th><th></th>
      </tr></thead><tbody>`
      + d["应用"].map((r) => {
        const 指 = r["各环境指着哪一版"] || {};
        // ⚠️ 空的时候写「**还没有任何一版在跑**」,不写「—」——
        // 一个「—」会被读成「线上没在用」,而两者完全不是一回事。
        const 格 = (e) => 指[e]
          ? `<code>${esc(指[e])}</code>`
          : `<span class="k">还没有任何一版在跑</span>`;
        return `<tr><td><a href="#/app/${encodeURIComponent(r.id)}"><b>${esc(r["名字"])}</b></a>
            <div class="k">${esc(r.id)}</div></td>
          <td class="k">${esc(r["流水线"])}</td>
          <td>${格("production")}</td><td>${格("staging")}</td><td>${格("test")}</td>
          <td>${r["候选能出清单吗"] ? `<span class="pill">可以出清单</span>`
                : `<span class="pill warn">还差 ${(r["候选还差什么"] || []).length} 项</span>`}
            ${(r["候选还差什么"] || []).length
              ? `<div class="k">${md((r["候选还差什么"] || [])[0].slice(0, 46))}</div>` : ""}
          </td>
          <td><a href="#" class="k" data-arch-app="${esc(r.id)}" title="行不删:出过的清单、跑过的运行、调用记录都还指着它;挂着工作流的要去工作流那里归档,还有活密钥的会被拦">归档</a></td></tr>`; }).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        <b>点应用名进详情</b> —— 发布那四步(出清单 / 审核 / 切指针 / 回滚)在那一页。</div>`;
    // 归档(11-25 包二,用户拍「做归档」):接口 11-17 就有(apps_api.归档应用,两道闸:挂着工作流 / 还有活密钥 → 409),
    // 前端一直没按钮。要写理由(进审计);被闸拦下就把接口的话原样显示 —— 它说清了该去哪儿解(挂着工作流的去工作流卡上归档)
    $("#list").querySelectorAll("[data-arch-app]").forEach((a) => {
      a.onclick = async (ev) => {
        ev.preventDefault();
        const 理由 = await 问一句("归档这个应用?", "行不删:出过的发布清单、跑过的运行、调用记录都还指着它,只是不再出现在列表里、不再给用户跑。<br>挂着工作流的应用要到「工作流」卡上连工作流一起归档;还有没吊销的访问密钥会被拦下来并告诉你先去哪儿解。",
          { 输入: "归档理由(进审计)", 必填: true, 确定: "归档" });
        if (理由 === null || 理由 === false || 理由 === undefined) return;
        try {
          const r = await 请求(`${P()}/applications/${encodeURIComponent(a.dataset.archApp)}/archive`, { method: "POST", body: JSON.stringify({ 理由 }) });
          if (r && r.note) alert(r.note);
          页_应用与发布();
        } catch (e) { 报错(e); }
      };
    });
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* ── 应用详情:发布那条链**能点了**(§13.3)────────────────────────────
 *
 * 这一页之前只有「看」:列表告诉你哪一版在跑,而出清单 / 审核 / 切指针 / 回滚
 * 四步都只能用 curl。补它之前先补了三条读接口 —— 那条链原来**只写不读**:
 * 清单 id 只在 POST 的响应里出现一次,刷新页面就找不回来。
 *
 * ⚠️ 这一页有**两个 revision,而且不通用**:
 *   · `候选revision`        → 改候选(PATCH draft)的 If-Match
 *   · `各环境[e].revision`  → 发布(切指针)的 If-Match
 * 拿错一个就是 409,而 409 读起来像「别人改过了」。所以下面两处**分别取**,
 * 并且在界面上把它们**分开显示** —— 一个界面上看不见的数,人只会去猜。
 *
 * ⚠️ 危险动作不用 `confirm()`,用**页内两步确认**。理由不是风格:
 *   · confirm 的那句话里放不进「从哪一版切到哪一版」,而那正是要确认的东西;
 *   · 模态框会**挡住自动化**(冒烟一点它就卡住),而这一页正是要被冒烟打的。
 */
const 依赖中文 = {
  workflow_version_id: "工作流版本",       // 11-18 补:澜绣两个应用都是工作流流水线,原来这一项不在表里,对照表六行全显示「没挑」
  prompt_version_id: "Prompt 版本",
  connection_version_id: "模型连接版本",
  index_build_id: "知识索引构建",
  retrieval_config_version_id: "检索配置版本",
  model_artifact_id: "模型产物",
  evaluation_id: "评测实验",
};
const 环境们 = ["test", "staging", "production"];

/* 一次点击一个幂等键。
 * ⚠️ **不能在渲染时生成**:那样「点了没反应又点一次」会带着**新键**过去,
 * 于是同一个动作被当成两件事 —— 而发布和回滚正是最不该重复的两个。 */
const 新键 = () => (crypto.randomUUID ? crypto.randomUUID()
  : String(Date.now()) + Math.random());

function 值格(v) {
  return v ? `<code>${esc(v)}</code>` : `<span class="k">没挑</span>`;
}

/* ── 发布链的四个动作:**抽出来,因为接线本身要能被测** ────────────────
 *
 * 最容易错的不是按钮长什么样,是「**哪个 revision 放进哪个头**」:
 *   · 改候选要 `候选revision`,切指针要 `各环境[e].revision` —— 拿错就是 409,
 *     而 409 读起来像「别人改过了」;
 *   · 发布和回滚都要幂等键,而键要**一次点击一个**(渲染时生成的话,
 *     「点了没反应再点一次」会带着新键过去,同一个动作被当成两件事);
 *   · 第一次绑定某个环境时**没有 revision 可带**,硬塞一个是另一种错。
 *
 * 这些事埋在 onclick 里的时候,**只有真浏览器点得到它们** ——
 * 而真浏览器那一份(test_upload_page_firefox.py)要弹窗口、不进门禁。
 * 抽成独立函数之后,`tests/e2e/test_release_page_actions.js` 可以直接调它们,
 * 打的是**真接口**,验的是**真接线**。
 *
 * ⚠️ 挂到 globalThis 是**为了能被测**,不是图方便:冒烟夹具用
 * `new Function(src)()` 跑这份源码,里面的函数声明是**局部的**,外面调不到。
 */
const 发布链动作 = {
  async 出清单(aid) {
    return await 请求(`${P()}/applications/${encodeURIComponent(aid)}/releases`,
      { method: "POST" });
  },
  async 审核(rid, 结论, 理由) {
    return await 请求(`${P()}/releases/${encodeURIComponent(rid)}/reviews`,
      { method: "POST",
        body: JSON.stringify({ 结论, 理由: (理由 || "").trim() || null }) });
  },
  async 发布(rid, 环境, 指针revision) {
    const 头 = { "Idempotency-Key": 新键() };
    // ⚠️ **有绑定才带 If-Match。** 第一次绑定时没有 revision 可带 ——
    // 硬塞一个的话服务端会拿它去和一行不存在的记录比,那是另一种错。
    if (指针revision != null) 头["If-Match"] = String(指针revision);
    return await 请求(`${P()}/releases/${encodeURIComponent(rid)}/deploy`,
      { method: "POST", headers: 头, body: JSON.stringify({ 环境 }) });
  },
  async 回滚(aid, 回到哪一版, 环境) {
    return await 请求(`${P()}/applications/${encodeURIComponent(aid)}/rollbacks`,
      { method: "POST", headers: { "Idempotency-Key": 新键() },
        body: JSON.stringify({ 回到哪一版, 环境 }) });
  },
  async 改候选(aid, 补丁, 候选revision) {
    // ⚠️ **这里原来有一个走不到的兜底**:「候选revision 为 null 时不带 If-Match,
    // 因为第一次 PATCH 是把草稿建出来」。量过之后发现那是错的 ——
    //   · `POST /applications` **同时**就把草稿建出来了(revision 1);
    //   · `PATCH .../draft` **无条件**要 If-Match(不带就 409 IF_MATCH_REQUIRED)。
    // 所以那个分支永远走不到;而它真被触发的那天,它做的事
    // (不带 If-Match 发出去)会换来一个**读不懂的 409**。
    // > 一个走不到的兜底,在它终于被触发的那天做的是错的事。
    // 现在改成**当场说清**:null 只可能是草稿行丢了(数据异常)。
    if (候选revision == null) {
      const e = new Error("这个应用的候选(草稿)读不到 revision —— "
        + "建应用时就该建出草稿,所以这多半是数据异常,不是「还没建」");
      e.体 = { code: "NO_DRAFT_REVISION",
               advice: "刷新一次;还是这样就要看 application_drafts 里有没有这一行" };
      e.码 = 0;
      throw e;
    }
    return await 请求(`${P()}/applications/${encodeURIComponent(aid)}/draft`,
      { method: "PATCH", headers: { "If-Match": String(候选revision) },
        body: JSON.stringify(补丁) });
  },
};
if (typeof globalThis !== "undefined") globalThis.发布链动作 = 发布链动作;

async function 页_应用详情(aid) {
  $("#main").innerHTML = `<div class="crumb">工作室 /
      <a href="#/studio/app">应用与发布</a> / 详情</div>
    <div class="head"><div><h1 id="t">应用</h1>
      <div class="sub">${md(`这一页能**做**发布那四步 ——
        出清单 / 审核 / 切指针 / 回滚。`)}</div></div></div>
    <div id="msg"></div>
    <div id="body"><div class="state">加载中…</div></div>`;
  await 画应用详情(aid);
}

function 报(文, 坏) {
  $("#msg").innerHTML = 文
    ? (坏 ? `<div class="state err">` : `<div class="state">`) + `<p>${md(文)}</p></div>` : "";
}

/* 把服务端逐条给的「闸」显示出来。
 * ⚠️ 只显示 message 的话,人看到的是「这份清单不能发到这个环境」——
 * 而**为什么**在 field_errors.闸 里,一条一条写着。少显示它等于把最有用的部分丢了。 */
function 闸文(e) {
  const b = e.体 || {};
  const 闸 = (b.field_errors || {})["闸"] || [];
  return `**${esc(b.code || "出错了")}** · ${esc(e.message)}`
    + (闸.length ? "\n\n" + 闸.map((x) => "· " + x).join("\n") : "")
    + (b.advice ? `\n\n**下一步:**${b.advice}` : "");
}

async function 画应用详情(aid) {
  try {
    const [d, h] = await Promise.all([
      请求(`${P()}/applications/${encodeURIComponent(aid)}`),
      请求(`${P()}/applications/${encodeURIComponent(aid)}/releases`),
    ]);
    $("#t").textContent = d["名字"] || aid;
    const 环 = d["各环境"] || {};
    const 候 = d["候选"] || {};
    const 生产清单 = ((环.production || {})["那一版的内容"]) || null;
    const 能发 = 我的角色 === "approver" || 我的角色 === "admin";
    const 能改 = 我的角色 === "editor" || 我的角色 === "admin";

    /* 左:当前生产清单   右:候选清单(§13.3 那张图) */
    const 对照 = Object.keys(依赖中文).map((k) => {
      const 左 = 生产清单 ? 生产清单[k] : null;
      const 右 = 候[k] || null;
      // ⚠️ 只在**两边都有值且不同**时标「改了」。
      // 左边为空时不标 —— 那是「还没有任何一版在跑」,不是「改了」。
      const 变 = 生产清单 && 左 !== 右;
      return `<tr${变 ? ' class="warn-row"' : ""}>
        <td class="k">${esc(依赖中文[k])}</td>
        <td>${值格(左)}</td>
        <td>${值格(右)}${变 ? ` <span class="pill warn">改了</span>` : ""}</td></tr>`;
    }).join("");

    const 指针行 = 环境们.map((e) => {
      const v = 环[e];
      return `<tr><td class="k">${esc(e)}</td>
        <td>${v && v["指着哪一版"] ? `<code>${esc(v["指着哪一版"])}</code>`
          : `<span class="k">还没有任何一版在跑</span>`}</td>
        <td class="k">${v && v.revision != null ? `revision ${v.revision}`
          : `<span class="k">没有绑定</span>`}</td></tr>`;
    }).join("");

    const 候选块 = d["候选能出清单吗"]
      ? `<span class="pill">候选可以出清单</span>`
      : `<span class="pill warn">候选还差 ${(d["候选还差什么"] || []).length} 项</span>
         <ul class="k">${(d["候选还差什么"] || [])
            .map((x) => `<li>${md(x)}</li>`).join("")}</ul>`;

    const 历史 = (h["清单们"] || []);
    const 历史行 = 历史.length ? 历史.map((m) => {
      const 审 = m["审核"] || null;
      // ⚠️ **「审过了」和「审的是这一份」画成两种,不合成一个。**
      // 合成一个的后果很具体:改完候选另出一份清单之后,界面上仍然写着「已审核」,
      // 而那一份**没人审过** —— 而它和真的审过在界面上长得一模一样。
      const 审格 = !审
        ? `<span class="k">还没审</span>`
        : m["这次审核还算数吗"]
          ? `<span class="pill ok">审核通过 · 算数</span>
             <div class="k">${esc(审["审核人"] || "")}${
               审["理由"] ? " · " + esc(审["理由"]) : ""}</div>`
          : `<span class="pill warn">审过,但${md("**不算这一份**")}</span>
             <div class="k">${md(m["为什么"] || "")}</div>`;
      const 在线 = m["哪些环境指着它"] || [];
      const 动作 = [];
      if (能发 && !审) 动作.push(`<button data-act="review" data-id="${esc(m.id)}">审核…</button>`);
      if (能发 && m["这次审核还算数吗"]) {
        动作.push(`<button data-act="deploy" data-id="${esc(m.id)}">发到…</button>`);
      }
      if (能发 && 在线.length === 0 && 历史.some((x) => (x["哪些环境指着它"] || []).length)) {
        动作.push(`<button data-act="rollback" data-id="${esc(m.id)}">回滚到这一版</button>`);
      }
      return `<tr><td><code>${esc(m.id)}</code>
          <div class="k">${esc(String(m["出清单时间"] || "").slice(0, 19))}
            · ${esc(m["出清单的人"] || "")}</div></td>
        <td>${审格}</td>
        <td>${在线.length ? 在线.map((e) =>
            `<span class="pill ok">${esc(e)}</span>`).join(" ")
          : `<span class="k">从来没上过线</span>`}</td>
        <td>${动作.join(" ") || `<span class="k">—</span>`}</td></tr>`;
    }).join("") : `<tr><td colspan="4" class="k">还没出过任何一份清单</td></tr>`;

    $("#body").innerHTML = `
      <h2>各环境现在指着哪一版</h2>
      <table><thead><tr><th>环境</th><th>指着哪一版</th>
        <th>指针 revision(发布要用它做 If-Match)</th></tr></thead>
        <tbody>${指针行}</tbody></table>

      <h2>左:当前生产清单　右:候选清单</h2>
      <table><thead><tr><th>依赖</th><th>生产在跑的</th><th>候选</th>
        </tr></thead><tbody>${对照}</tbody></table>
      <div class="note">${候选块}
        <div class="k">候选 revision:${d["候选revision"] == null
          ? "<b>读不到 —— 多半是草稿行丢了(数据异常)</b>"
          : d["候选revision"]}　—　
          <b>这个数和上面那个指针 revision 不是一个</b>,各自独立地涨</div>
        ${d["候选能出清单吗"] && 能改
          ? `<div style="margin-top:8px"><button class="pri" id="b-freeze">出一份发布清单(冻结依赖)</button></div>`
          : !能改
            ? `<div class="k" style="margin-top:8px">你现在是 <b>${esc(我的角色 || "?")}</b>,
                出清单要 <b>改 Prompt/知识候选</b> 这条能力 —— <b>所以这里不摆按钮</b>,
                摆一个点了 403 的按钮只是把拒绝往后挪一步</div>`
            : ""}
      </div>

      <h2>清单历史（新的在前）</h2>
      <table><thead><tr><th>清单</th><th>审核</th><th>哪些环境指着它</th>
        <th>动作</th></tr></thead><tbody>${历史行}</tbody></table>
      <div class="note">${md(h.note || "")}<br>
        <b>回滚是一次新的部署动作,不是把历史改回去</b> ——
        改历史的后果很具体:「上周二在跑哪一版」会变成<b>现在这一版</b>,
        而那正是回滚之后最需要问的问题。
        ${能发 ? "" : `<br><span class="k">你现在是 <b>${esc(我的角色 || "?")}</b>,
          审核 / 发布 / 回滚要 <b>生产审核/发布/回滚</b> 这条能力 ——
          <b>所以那几个按钮不摆</b></span>`}</div>
      <div id="panel"></div>`;

    if ($("#b-freeze")) {
      $("#b-freeze").onclick = async () => {
        $("#b-freeze").disabled = true; 报("出清单…");
        try {
          const r = await 发布链动作.出清单(aid);
          报(r["新建了吗"]
            ? `出了新清单 \`${r.id}\` —— **写下就不许改**。要发生产还得先审核,`
              + `而审核认的是这一份的内容哈希`
            : `**没有新建** —— ${r.note || "依赖组合和已有的一份完全一样"}`);
          await 画应用详情(aid);
        } catch (e) { 报(闸文(e), true); $("#b-freeze").disabled = false; }
      };
    }
    document.querySelectorAll("[data-act]").forEach((b) => {
      b.onclick = () => 开面板(aid, b.dataset.act, b.dataset.id, 环, 历史);
    });
  } catch (e) {
    const s = 错误块(e, () => 画应用详情(aid));
    $("#body").innerHTML = s.html; s.挂();
  }
}

/* 页内两步确认。**先把「要改什么」摆出来,再给确认按钮。** */
function 开面板(aid, 动作, rid, 环, 历史) {
  报("");
  const 环选 = 环境们.map((e) => {
    const v = 环[e] || {};
    return `<option value="${e}">${e} —— 现在 ${v["指着哪一版"]
      ? v["指着哪一版"] : "还没有任何一版在跑"}</option>`;
  }).join("");

  if (动作 === "review") {
    $("#panel").innerHTML = `<div class="state">
      <h3>审核清单 <code>${esc(rid)}</code></h3>
      <p>${md("⚠️ **审核记的是「审的哪一份内容」,不是一个布尔** —— "
        + "这一份是不可变的,所以审过就永远算数;而改完候选另出一份,**那一份要重新审**。")}</p>
      <p><label>理由(驳回时**必须**写清 —— 一句「不通过」下一个人不知道该改什么)<br>
        <input id="p-why" style="width:min(460px,90%)" placeholder="依赖都对得上 / 评测没覆盖 X 场景"></label></p>
      <p><button class="pri" data-go="通过">确认:审核通过</button>
         <button data-go="驳回">确认:驳回</button>
         <button data-go="">取消</button></p></div>`;
    document.querySelectorAll("[data-go]").forEach((b) => {
      b.onclick = async () => {
        const 结论 = b.dataset.go;
        if (!结论) { $("#panel").innerHTML = ""; return; }
        报("提交审核…");
        try {
          const r = await 发布链动作.审核(rid, 结论, $("#p-why").value);
          报(`审核记下了:**${esc(r["结论"])}** · 审的哈希 \`${esc(r["审的哈希"])}\``);
          $("#panel").innerHTML = ""; await 画应用详情(aid);
        } catch (e) { 报(闸文(e), true); }
      };
    });
    return;
  }

  if (动作 === "deploy") {
    $("#panel").innerHTML = `<div class="state">
      <h3>把环境指针切到 <code>${esc(rid)}</code></h3>
      <p>${md("⚠️ **指针切换是原子的**,而且会带上当前指针的 `If-Match` —— "
        + "两个人同时发布不同版本时,**后到的那个会悄悄覆盖先到的,而两边都收到成功**。")}</p>
      <p><label>发到哪个环境<br><select id="p-env">${环选}</select></label></p>
      <p id="p-diff" class="k"></p>
      <p><button class="pri" data-go="1">确认发布</button>
         <button data-go="">取消</button></p></div>`;
    const 画差 = () => {
      const e = $("#p-env").value;
      const 从 = (环[e] || {})["指着哪一版"];
      $("#p-diff").innerHTML = 从
        ? `${esc(e)}:<code>${esc(从)}</code> → <code>${esc(rid)}</code>`
          + `（If-Match = ${(环[e] || {}).revision}）`
        : `${esc(e)}:<b>还没有任何一版在跑</b> → <code>${esc(rid)}</code>`
          + `（第一次绑定,不带 If-Match）`;
    };
    $("#p-env").onchange = 画差; 画差();
    document.querySelectorAll("[data-go]").forEach((b) => {
      b.onclick = async () => {
        if (!b.dataset.go) { $("#panel").innerHTML = ""; return; }
        const e = $("#p-env").value;
        const rev = (环[e] || {}).revision;
        b.disabled = true; 报("发布…");
        try {
          const r = await 发布链动作.发布(rid, e, rev);
          报(`**${esc(_英转中[r["环境"]] || r["环境"])}** 的指针切了:`
            + `${r["从"] ? `\`${esc(r["从"])}\`` : "（原来没有）"} → \`${esc(r["到"])}\``
            + `\n\n${r.note || ""}`);
          $("#panel").innerHTML = ""; await 画应用详情(aid);
        } catch (e2) { 报(闸文(e2), true); b.disabled = false; }
      };
    });
    return;
  }

  if (动作 === "rollback") {
    const 在线的 = 历史.filter((x) => (x["哪些环境指着它"] || []).length);
    $("#panel").innerHTML = `<div class="state">
      <h3>回滚到 <code>${esc(rid)}</code></h3>
      <p>${md("⚠️ **回滚是一次新的部署动作,不是把历史改回去。** "
        + "改历史的后果很具体:「上周二在跑哪一版」会变成**现在这一版** —— "
        + "而那正是回滚之后最需要问的问题。")}</p>
      <p class="k">现在在线的:${在线的.length
        ? 在线的.map((x) => `<code>${esc(x.id)}</code>(${
            (x["哪些环境指着它"] || []).join("/")})`).join("、")
        : "没有任何一版在跑 —— **那就没有可回滚的**"}</p>
      <p><label>回滚哪个环境<br><select id="p-env">${环选}</select></label></p>
      <p><button class="pri" data-go="1">确认回滚</button>
         <button data-go="">取消</button></p></div>`;
    document.querySelectorAll("[data-go]").forEach((b) => {
      b.onclick = async () => {
        if (!b.dataset.go) { $("#panel").innerHTML = ""; return; }
        b.disabled = true; 报("回滚…");
        try {
          const r = await 发布链动作.回滚(aid, rid, $("#p-env").value);
          报(`回滚提交了:${JSON.stringify(r).slice(0, 200)}`);
          $("#panel").innerHTML = ""; await 画应用详情(aid);
        } catch (e2) { 报(闸文(e2), true); b.disabled = false; }
      };
    });
  }
}

/* ── 模型与连接:建连接 + 探 capabilities ──────────────────────────────
 *
 * ⚠️ **这一页最要紧的一条:只收 `secret_ref`,不收明文。**
 * 表单上**没有「密钥」输入框**,而且这不是遗漏 ——
 * 服务端那条闸会把「名字像凭据而且给了值」的字段当场拒掉,理由是:
 * > 明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报;
 * > **换个字段名重发也救不回来那一次。**
 * 所以界面上也不给那个口子:摆一个明文框、再靠后端拒,
 * 等于把「已经出事了」往后挪一步。
 *
 * ⚠️ 用途和适配器的选项**从接口来,不在前端硬编**。
 * 硬编的代价不是难看,是它和契约会漂 —— 漂的表现是
 * 界面上少一个能用的选项、或者多一个已经不支持的,**两者都不报错**。
 * 而适配器接口明说了**不是穷尽清单**(契约只登记了族),
 * 所以这里画成「输入框 + 已在用的那几个当快捷填」,**不画下拉框** ——
 * 下拉框会让人以为不在里面的就不能用。
 */
const 连接动作 = {
  async 建(体) {
    return await 请求(`${P()}/model-connections`,
      { method: "POST", body: JSON.stringify(体) });
  },
  async 探(cid) {
    // ⚠️ 探测是**异步 + 花钱**(要真打一次模型端点),所以带幂等键。
    return await 请求(
      `${P()}/model-connections/${encodeURIComponent(cid)}/probe`,
      { method: "POST", headers: { "Idempotency-Key": 新键() } });
  },
  // 停用 / 启用都要 If-Match(列表里每条的 revision)—— 两个人同时操作,后到的不许静默覆盖
  async 停用(cid, rev) {
    return await 请求(`${P()}/model-connections/${encodeURIComponent(cid)}/archive`,
      { method: "POST", headers: { "If-Match": String(rev) } });
  },
  async 启用(cid, rev) {
    return await 请求(`${P()}/model-connections/${encodeURIComponent(cid)}/unarchive`,
      { method: "POST", headers: { "If-Match": String(rev) } });
  },
};
if (typeof globalThis !== "undefined") globalThis.连接动作 = 连接动作;

function 页_连接表单(d) {
  const 用途们 = d["可选用途"] || [];
  const 适 = d["适配器怎么填"] || {};
  const 能配 = 我的角色 === "admin";
  if (!能配) {
    return `<div class="note"><b>建连接要「配置密钥与预算」这条能力</b> ——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>:
      摆一个填完被 403 的表单,只是把拒绝往后挪一步。</div>`;
  }
  const 选项 = 用途们.map((u) => `<option value="${esc(u["值"])}"${
    u["这个项目占了吗"] ? " disabled" : ""}>${esc(u["中文"])}（${esc(u["值"])}）${
    u["这个项目占了吗"] ? ` —— 已经有 ${(u["占着的那几条"] || []).length} 条在用`
      : ""}</option>`).join("");
  const 快捷 = (适["这个项目已经在用的"] || [])
    .map((a) => `<button data-fill="${esc(a)}" class="k">${esc(a)}</button>`).join(" ");
  return `<div class="state">
    <h3>建一条连接</h3>
    <p class="k">${md(适["⚠️"] || "")}</p>
    <p><label>用途<br><select id="c-use">${选项}</select></label></p>
    <p><label>适配器（${md(适["规则"] || "")}）<br>
      <input id="c-ad" style="width:min(320px,90%)" placeholder="MockModelProvider">
      </label><br>${快捷 ? `<span class="k">已经在用的：</span>${快捷}` : ""}</p>
    <p><label>endpoint<br>
      <input id="c-ep" style="width:min(420px,90%)" placeholder="mock://local"></label></p>
    <p><label>密钥<b>引用</b>（不是密钥本身）<br>
      <input id="c-sr" style="width:min(420px,90%)" placeholder="secret://vault/xxx">
      </label></p>
    <p class="k">⚠️ <b>这里只收引用,没有明文密钥的输入框</b> ——
      明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报;
      <b>换个字段名重发也救不回来那一次</b>。</p>
    <p><label>名字（可不填）<br>
      <input id="c-nm" style="width:min(320px,90%)"></label></p>
    <p><button class="pri" id="c-go">建这条连接</button></p></div>`;
}

let _连接含停用 = false;     // 「显示已停用的」开关;默认不列,演示项目里 e2e 停用的有几百条会淹掉真在用的
async function 页_模型与连接() {
  $("#main").innerHTML = `<div class="crumb">集成 / 模型供应商</div>
    <div class="head"><div><h1>模型与连接</h1>
      <div class="sub"><b>密钥只给形状,不给内容</b> ——
        也不做截断:截到前几个字,那几个字仍然是原文。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/model-connections${_连接含停用 ? "?include_archived=true" : ""}`);
    const 停用开关 = d["停用的条数"] || _连接含停用
      ? `<div class="k" style="margin:6px 0"><label><input type="checkbox" id="c-arch" ${_连接含停用 ? "checked" : ""}>
          显示已停用的(${esc(d["停用的条数"] ?? "?")} 条)—— 要「启用」得先看得见它</label></div>` : "";
    if (!d["连接"].length) {
      $("#list").innerHTML = 状态("", "还没有模型连接",
        "**用途要分开**(生成 / Embedding / 重排 / 微调推理)—— 共用一条的话,"
        + "换生成模型会顺手把 Embedding 也换掉,而已经建好的索引会全部不可比。").html
        + 停用开关 + `<div id="msg2"></div>` + 页_连接表单(d);
      挂连接事件(d);
      return;
    }
    // 停用 / 启用(11-18):admin 才摆按钮;按钮带这一行的 revision,点的时候放进 If-Match
    const 停启 = (r) => 我的角色 !== "admin" ? ""
      : r["状态"] === "active"
        ? `<button data-arch="${esc(r.id)}" data-rev="${esc(r.revision)}" class="k">停用</button>`
        : r["状态"] === "archived"
          ? `<button data-unarch="${esc(r.id)}" data-rev="${esc(r.revision)}" class="k">启用</button>` : "";
    $("#list").innerHTML = 停用开关 + `<table><thead><tr><th>用途</th><th>名字</th>
      <th>适配器</th><th>密钥</th><th>探过 capabilities 吗</th><th>状态</th>
      </tr></thead><tbody>`
      + d["连接"].map((r) => {
        const v = (r["配置版本"] || [])[0] || {};
        const k = v["密钥"] || {};
        const 停了 = r["状态"] === "archived";
        return `<tr><td><b>${esc(r["用途中文"] || r["用途"])}</b></td>
          <td>${esc(r["名字"] || "—")}</td><td class="k">${esc(r["适配器"])}</td>
          <td>${k["配了吗"]
            ? `<span class="pill">${esc(k["存在哪"])}·${k["长度"]} 字</span>`
            : `<span class="pill warn">没配</span>`}</td>
          <td>${v["探过吗"] ? `<span class="pill">探过了</span>`
            : `<span class="pill warn">还没探过</span>`}</td>
          <td class="k">${停了 ? `<span class="pill warn">已停用</span>${r["停用于"] ? ` <span class="k">${时间(r["停用于"])}</span>` : ""}` : esc(r["状态"])}
            ${我的角色 === "admin" && !停了
              ? `<br><button data-probe="${esc(r.id)}" class="k">探一下</button> ` : "<br>"}${停启(r)}
          </td></tr>`; }).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        ⚠️ <b>「没探过」不等于「支持一切」</b> —— 不探的话,不支持的参数会在
        几天后某次真实调用上变成一个说不清的 400。<b>发到生产的清单要求它探过。</b>
        ${(d["⚠️同用途多条"] || []).map((x) => `<br><br>${md(x)}`).join("")}</div>`
      + `<div id="msg2"></div>` + 页_连接表单(d);
    挂连接事件(d);
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 报2(文, 坏) {
  if ($("#msg2")) {
    $("#msg2").innerHTML = 文
      ? (坏 ? `<div class="state err">` : `<div class="state">`) + `<p>${md(文)}</p></div>` : "";
  }
}

function 挂连接事件(d) {
  document.querySelectorAll("[data-fill]").forEach((b) => {
    b.onclick = () => { if ($("#c-ad")) $("#c-ad").value = b.dataset.fill; };
  });
  if ($("#c-arch")) $("#c-arch").onchange = async (e) => { _连接含停用 = Boolean(e.target.checked); await 页_模型与连接(); };
  // 停用 / 启用:点前问一句(停用的后果要先说清:每一跑都会失败,已发布版本也一样),带 If-Match,409 让人刷新
  document.querySelectorAll("[data-arch],[data-unarch]").forEach((b) => {
    b.onclick = async () => {
      const 停 = b.hasAttribute("data-arch"), cid = 停 ? b.dataset.arch : b.dataset.unarch;
      const 行 = (d["连接"] || []).find((x) => x.id === cid) || {};
      const 名 = `${行["名字"] || cid}(${行["用途中文"] || 行["用途"] || "?"})`;
      const 行吗 = await 问一句(停 ? "停用这条连接?" : "启用这条连接?", md(停
        ? `**${名}** 停用后:发到生产会被闸拦;**凡用到它的每一跑都会报 MODEL_CONNECTION_DISABLED** —— 已发布的版本不会自动下线,也一样失败。已建好的知识索引不受影响。`
        : `**${名}** 启用后,发生产那道闸和 worker 从这一刻起认它是在用的。同用途下已经有别的在用的连接会被拦住(409)。`),
        { 确定: 停 ? "停用" : "启用" });
      if (!行吗) return;
      b.disabled = true; 报2(停 ? "停用中…" : "启用中…");
      try {
        const r = await (停 ? 连接动作.停用(cid, b.dataset.rev) : 连接动作.启用(cid, b.dataset.rev));
        await 页_模型与连接();
        报2(`${停 ? "已停用" : "已启用"} \`${cid}\`${r && r.note ? ":" + r.note : ""}`);
      } catch (e) {
        const code = (e.体 || {}).code;
        报2((e.码 === 409 && (code === "REVISION_CONFLICT" || code === "IF_MATCH_REQUIRED")
          ? "**这条连接刚被别人改过,刷新页面再试。** " : "") + 闸文(e), true);
        b.disabled = false;
      }
    };
  });
  document.querySelectorAll("[data-probe]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true; 报2("探 capabilities…");
      try {
        const r = await 连接动作.探(b.dataset.probe);
        // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
        await 页_模型与连接();
        报2(`探测提交了${r && (r.note || r["说明"]) ? ":" + esc(r.note || r["说明"]) : ",结果在上面那一行「探过吗」里"}`);
      } catch (e) { 报2(闸文(e), true); b.disabled = false; }
    };
  });
  if (!$("#c-go")) return;
  $("#c-go").onclick = async () => {
    const 体 = {
      用途: $("#c-use").value,
      适配器: ($("#c-ad").value || "").trim(),
      endpoint: ($("#c-ep").value || "").trim(),
      secret_ref: ($("#c-sr").value || "").trim(),
    };
    const 名 = ($("#c-nm").value || "").trim();
    if (名) 体["名字"] = 名;
    $("#c-go").disabled = true; 报2("建连接…");
    try {
      const r = await 连接动作.建(体);
      // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
      await 页_模型与连接();
      报2(`建好了 \`${esc(r.id || "")}\` —— **下一步是探一次 capabilities**:`
        + `不探的话「没探过」会在发布那一刻把它挡住`);
    } catch (e) { 报2(闸文(e), true); $("#c-go").disabled = false; }
  };
}

/* ── 工具连接(capability_connections)──────────────────────────────────
 *
 * 11-18 体检:HTTP 请求节点提示「请平台管理员在「工具连接」里登记一条」,**而这一页不存在**,
 * 澜绣项目 `工具连接 = []`,HTTP 节点在页面上永远配不出来。接口在 tools_api(GET 列表 / POST 建)。
 * ⚠️ 和模型连接同口径:**只收密钥引用,表单上没有明文密钥框** —— 服务端那条「名字像凭据而且给了值就拒」的闸也在。
 * ⚠️ 鉴权只收「方式 + 头名」,密钥本身仍走引用;提示语里不写凭据类英文词(进 422 响应会被泄密检查判成 500)。 */
const 工具连接动作 = {
  async 建(体) {
    return await 请求(`${P()}/capability-connections`, { method: "POST", body: JSON.stringify(体) });
  },
};
if (typeof globalThis !== "undefined") globalThis.工具连接动作 = 工具连接动作;

/* 422 的 field_errors 逐字段显示(工具连接 / 工具组两页共用)。后端这两处把问题装在 `闸` 这一个键下、一条一条写;
 * 别的键(名称 / 用途 / 成员)也按同样的形状列 —— 只显示 message 等于把最有用的部分丢了 */
function 字段错块(e) {
  const b = e.体 || {}, fe = b.field_errors || {};
  const 条 = Object.entries(fe).map(([k, v]) => (Array.isArray(v) ? v : [v])
    .map((x) => `<li><b>${esc(k)}</b>:${md(String(x))}</li>`).join("")).join("");
  return `<div class="state err"><h3>${esc(b.code || "出错了")} · ${esc(e.message)}</h3>
    ${条 ? `<ul>${条}</ul>` : ""}<p>${b.advice ? md("**下一步:**" + b.advice) : "服务端没给建议 —— 这本身是个契约问题"}</p></div>`;
}

function 页_工具连接表单(d) {
  const 能配 = 我的角色 === "admin";    // 后端 要权限("配置密钥与预算"):只有 admin 默认有
  if (!能配) {
    return `<div class="note"><b>登记工具连接要「配置密钥与预算」这条能力</b>(和建模型连接同一条)——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>:
      摆一个填完被 403 的表单,只是把拒绝往后挪一步。</div>`;
  }
  const 已用 = [...new Set((d["连接"] || []).map((x) => x["适配器"]).filter(Boolean))];
  const 快捷 = [...new Set(["http", "MCP", ...已用])]
    .map((a) => `<button data-ccfill="${esc(a)}" class="k">${esc(a)}</button>`).join(" ");
  return `<div class="state">
    <h3>登记一条工具连接</h3>
    <p class="k">HTTP 请求节点只能打到这里登记过的地址 —— <b>允许的端点是一张白名单</b>,一行一条。</p>
    <p><label>名字<br><input id="cc-nm" style="width:min(320px,90%)" placeholder="比如:门店 MCP / 天气接口"></label></p>
    <p><label>适配器<br><input id="cc-ad" style="width:min(320px,90%)" placeholder="http"></label><br>
      <span class="k">HTTP 请求节点用 <code>http</code>;常用的:</span>${快捷}</p>
    <p><label>允许的端点(白名单,一行一条完整地址)<br>
      <textarea id="cc-ep" rows="3" style="width:min(520px,90%)" placeholder="https://api.example.com/v1"></textarea></label></p>
    <p><label>鉴权方式<br><select id="cc-au">
      <option value="无">无(公开接口,不带凭据)</option>
      <option value="令牌">令牌(标准的持有者令牌头)</option>
      <option value="自定义头">自定义头(下面填头名)</option></select></label>
      <label style="margin-left:12px">头名(只配「自定义头」)<br>
      <input id="cc-hd" style="width:min(240px,90%)" placeholder="x-api-key 这类,小写"></label></p>
    <p><label>密钥<b>引用</b>(不是密钥本身)<br>
      <input id="cc-sr" style="width:min(420px,90%)" placeholder="keychain://xxx / env://XXX / vault://path / ref:xxx"></label></p>
    <p class="k">⚠️ <b>这里只收引用,没有明文密钥的输入框</b> ——
      明文一旦进过请求体,它就已经进过日志、进过 APM、可能进过错误上报;<b>换个字段名重发也救不回来那一次</b>。</p>
    <p><button class="pri" id="cc-go">登记这条连接</button></p></div>`;
}

async function 页_工具连接() {
  $("#main").innerHTML = `<div class="crumb">集成 / 工具连接</div>
    <div class="head"><div><h1>工具连接</h1>
      <div class="sub"><b>密钥只给形状,不给内容</b> —— 工作流里的 HTTP 请求节点只能选这里登记过的连接,
        地址只能是它白名单里的一条。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/capability-connections`);
    const 连 = d["连接"] || [];
    const 尾 = `<div class="note">${md(d.note || "")}</div><div id="ccmsg"></div>` + 页_工具连接表单(d);
    if (!连.length) {
      $("#list").innerHTML = 状态("", "还没有工具连接",
        "工作流「搭建」里的 **HTTP 请求节点**要先在这里登记一条连接才配得出来:填允许访问的地址白名单和凭据引用。"
        + "登记要「配置密钥与预算」这条能力(admin)。").html + 尾;
      挂工具连接事件(d);
      return;
    }
    const 鉴文 = (a) => { a = a || {}; return esc(a["方式"] || "无") + (a["头名"] ? ` · <code>${esc(a["头名"])}</code>` : ""); };
    $("#list").innerHTML = `<table><thead><tr><th>名字</th><th>适配器</th><th>允许的端点</th>
      <th>密钥</th><th>鉴权</th><th>发现到的能力</th><th>状态</th><th>负责人</th><th>上次健康检查</th>
      </tr></thead><tbody>`
      + 连.map((r) => {
        const k = r["密钥"] || {}, 能 = r["发现到的能力"];
        return `<tr><td><b>${esc(r["名字"] || "—")}</b><br><code class="k">${esc(r.id)}</code></td>
          <td class="k">${esc(r["适配器"] || "—")}</td>
          <td>${(r["允许的端点"] || []).length ? (r["允许的端点"] || []).map((u) => `<code>${esc(u)}</code>`).join("<br>") : `<span class="k">—</span>`}</td>
          <td>${k["配了吗"] ? `<span class="pill">${esc(k["存在哪"])}·${esc(k["长度"])} 字</span>` : `<span class="pill warn">没配</span>`}</td>
          <td class="k">${鉴文(r["鉴权"])}</td>
          <td class="k">${能 == null ? "还没发现过" : Array.isArray(能) ? `${能.length} 项` : "有"}</td>
          <td>${r["状态"] === "active" ? `<span class="pill">在用</span>` : `<span class="pill warn">${esc(r["状态"] || "?")}</span>`}</td>
          <td class="k">${esc(r["负责人"] || "—")}</td>
          <td class="k">${r["上次健康检查"] ? 时间(r["上次健康检查"]) : "没查过"}</td></tr>`; }).join("")
      + `</tbody></table>` + 尾;
    挂工具连接事件(d);
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 挂工具连接事件(d) {
  document.querySelectorAll("[data-ccfill]").forEach((b) => {
    b.onclick = () => { if ($("#cc-ad")) $("#cc-ad").value = b.dataset.ccfill; };
  });
  if (!$("#cc-go")) return;
  const 报 = (html) => { if ($("#ccmsg")) $("#ccmsg").innerHTML = html; };
  $("#cc-go").onclick = async () => {
    const 方式 = $("#cc-au").value, 头名 = ($("#cc-hd").value || "").trim();
    const 体 = {
      名字: ($("#cc-nm").value || "").trim(),
      适配器: ($("#cc-ad").value || "").trim(),
      允许的端点: ($("#cc-ep").value || "").split(/\n/).map((x) => x.trim()).filter(Boolean),
      鉴权: 方式 === "自定义头" ? { 方式, 头名 } : { 方式 },
      secret_ref: ($("#cc-sr").value || "").trim(),
    };
    $("#cc-go").disabled = true; 报(`<div class="state"><p>登记中…</p></div>`);
    try {
      const r = await 工具连接动作.建(体);
      await 页_工具连接();   // 先重画再写结果,不然结果刚出来就被刷掉
      报(`<div class="state"><p>登记好了 <code>${esc(r.id || "")}</code> —— 现在去工作流「搭建」里的 HTTP 请求节点就能选到它。${md(r.note ? " " + r.note : "")}</p></div>`);
    } catch (e) { 报(字段错块(e)); $("#cc-go").disabled = false; }
  };
}

/* ── 工具组(tool_groups)─────────────────────────────────────────────────
 *
 * 11-18 体检:工具详情页说「配套关系只能在冻结工具组版本时给」,而**没有任何页面能冻结工具组版本**。
 * 接口在 toolgroups_api:GET 列表 / POST 建组(要「改编排草稿」)/ GET 详情 / PATCH 草稿(If-Match 认 draft_revision,缺了 409)
 * / POST 版本(冻结,三道校验在服务端:模型眼里同名 / 配套成环 / 成员版本还在不在;**不要 Idempotency-Key**,接口不读它)。
 * ⚠️ 成员要的是 tool_version_id,而工具详情接口**不给版本 id**(只给 v1 / v2 这种号)——
 *    这里从 workflow-resources 的 `工具` 取(每个在用工具的最新版本 id + 名字),所以成员只能选到**最新版本**;
 *    版本历史里的老 id 认不出名字时原样显示 id,不猜。 */
const 工具组动作 = {
  async 建(体) { return await 请求(`${P()}/tool-groups`, { method: "POST", body: JSON.stringify(体) }); },
  async 改草稿(gid, rev, 体) {
    return await 请求(`${P()}/tool-groups/${encodeURIComponent(gid)}/draft`,
      { method: "PATCH", headers: { "If-Match": String(rev) }, body: JSON.stringify(体) });
  },
  async 冻结(gid, 体) {
    return await 请求(`${P()}/tool-groups/${encodeURIComponent(gid)}/versions`, { method: "POST", body: JSON.stringify(体) });
  },
};
if (typeof globalThis !== "undefined") globalThis.工具组动作 = 工具组动作;
const 能改工具组 = () => 我的角色 === "editor" || 我的角色 === "admin";   // 后端 要权限("改编排草稿")

async function 页_工具组(gid) {
  if (gid) return await 页_工具组详情(decodeURIComponent(gid));
  $("#main").innerHTML = `<div class="crumb">集成 / 工具组</div>
    <div class="head"><div><h1>工具组</h1>
      <div class="sub"><b>组只是一份搭配,不是一份授权</b> —— Agent 绑了某个组版本,执行权仍要过工具网关的实时查验。
        组决定的是「这一轮给模型看哪些」。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/tool-groups`);
    const 表单 = 能改工具组()
      ? `<div class="state"><h3>新建一个组</h3>
          <p class="k">建完是一份<b>没有版本的草稿</b> —— 成员和配套关系在详情页「冻结一版」时给;没有版本的组 Agent 引用不了。</p>
          <p><label>名称<br><input id="tg-nm" style="width:min(320px,90%)" placeholder="说得出用途的名字"></label></p>
          <p><label>用途(必填 —— 说不出用途的组,下次没人知道该不该往里加工具)<br>
            <textarea id="tg-pu" rows="2" style="width:min(520px,90%)"></textarea></label></p>
          <p><button class="pri" id="tg-go">建这个组</button></p></div>`
      : `<div class="note"><b>建组 / 改草稿 / 冻结版本要「改编排草稿」这条能力</b>(editor 或 admin)——
          你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>。</div>`;
    const 尾 = `<div class="note">${md(d.note || "")}</div><div id="tgmsg"></div>` + 表单;
    if (!(d.items || []).length) {
      $("#list").innerHTML = 状态("", "还没有工具组",
        "工具组是给 Agent 的一份**稳定搭配**(哪些工具一起给、谁必不可少、谁配套谁)。"
        + "建一个组、再在详情页冻结一版,Agent 才引用得了。").html + 尾;
      挂工具组事件();
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>名称</th><th>用途</th><th>负责人</th><th>状态</th><th>版本数</th><th>草稿修订</th>
      </tr></thead><tbody>`
      + d.items.map((r) => `<tr>
        <td><a href="#/integrations/groups/${encodeURIComponent(r.id)}"><b>${esc(r["名称"] || r.id)}</b></a><br><code class="k">${esc(r.id)}</code></td>
        <td data-raw="原文">${esc(r["用途"] || "—")}</td>
        <td class="k">${esc(r["负责人"] || "—")}</td>
        <td class="k">${esc(r["状态"] || "—")}</td>
        <td>${r["版本数"] ? `<span class="pill">${esc(r["版本数"])} 版</span>` : `<span class="pill warn">还没冻结版本</span>`}</td>
        <td class="k">${esc(r["draft_revision"])}</td></tr>`).join("")
      + `</tbody></table><div class="note"><b>点组名进详情</b>:看成员、配套关系、版本历史;改草稿、冻结一版都在那里。</div>` + 尾;
    挂工具组事件();
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 挂工具组事件() {
  if (!$("#tg-go")) return;
  $("#tg-go").onclick = async () => {
    const 体 = { 名称: ($("#tg-nm").value || "").trim(), 用途: ($("#tg-pu").value || "").trim() };
    $("#tg-go").disabled = true;
    if ($("#tgmsg")) $("#tgmsg").innerHTML = `<div class="state"><p>建组中…</p></div>`;
    try {
      const r = await 工具组动作.建(体);
      location.hash = `#/integrations/groups/${encodeURIComponent(r.id)}`;   // 建完直奔详情:下一步(冻结一版)在那儿
    } catch (e) { if ($("#tgmsg")) $("#tgmsg").innerHTML = 字段错块(e); $("#tg-go").disabled = false; }
  };
}

// 冻结表单的在编状态:成员列表 + 配套关系(页内重画时保留;换组时清掉)
let 组冻结态 = { gid: null, 成员: [], 配套: {}, 说明: "" };

async function 页_工具组详情(gid) {
  $("#main").innerHTML = `<div class="crumb">集成 / <a href="#/integrations/groups">工具组</a> / 详情</div>
    <div class="head"><div><h1 id="tgt">工具组</h1>
      <div class="sub"><b>版本是不可变的</b> —— 冻结之后再发现问题,只能出一个新版本;改草稿改不动已经冻结的版本。</div></div></div>
    <div id="tgdmsg"></div>
    <div id="tgdbody"><div class="state">加载中…</div></div>`;
  if (组冻结态.gid !== gid) 组冻结态 = { gid, 成员: [], 配套: {}, 说明: "" };
  await 画工具组详情(gid);
}

async function 画工具组详情(gid) {
  try {
    // 工具名字表从 workflow-resources 来(它给每个在用工具的最新版本 id);拉不到就只显示 id,不把这一页整个变成错误
    const [d, 资] = await Promise.all([
      请求(`${P()}/tool-groups/${encodeURIComponent(gid)}`),
      请求(`${P()}/workflow-resources`).catch(() => null),
    ]);
    $("#tgt").textContent = d["名称"] || gid;
    const 工具们 = (资 && 资["工具"]) || [];
    const 名表 = {}; 工具们.forEach((t) => { 名表[t["版本id"]] = t; });
    const 名 = (vid) => { const t = 名表[vid]; return t ? `<b>${esc(t["名"])}</b> <code class="k">${esc(vid)}</code>` : `<code>${esc(vid)}</code> <span class="k">(不在当前可选工具里:历史版本 / 已停用 / 已归档)</span>`; };
    const 草 = d["草稿"] || {}, 版本们 = d["版本历史"] || [], 能改 = 能改工具组();
    // ── 草稿 ──
    const 草稿区 = `<h2>草稿 <span class="k">draft_revision ${esc(d.draft_revision)} · revision ${esc(d.revision)}</span></h2>
      ${能改 ? `<div class="state"><p><label>名称<br><input id="tgd-nm" style="width:min(320px,90%)" value="${esc(d["名称"] || "")}"></label></p>
          <p><label>用途<br><textarea id="tgd-pu" rows="2" style="width:min(520px,90%)" data-raw="原文">${esc(草["用途"] || "")}</textarea></label></p>
          <p><label>负责人<br><input id="tgd-ow" style="width:min(200px,90%)" value="${esc(草["负责人"] || "")}"></label></p>
          <p><button class="pri" id="tgd-save" data-rev="${esc(d.draft_revision)}">保存草稿</button>
            <span class="k">带 If-Match = ${esc(d.draft_revision)};别人先改了会报 409,刷新再改。<b>已经冻结的版本一个字不动。</b></span></p></div>`
        : `<table><tbody><tr><td class="k">用途</td><td data-raw="原文">${esc(草["用途"] || "—")}</td></tr>
            <tr><td class="k">负责人</td><td>${esc(草["负责人"] || "—")}</td></tr>
            <tr><td class="k">状态</td><td>${esc(d["状态"] || "—")}</td></tr></tbody></table>
          <div class="note">改草稿 / 冻结版本要「改编排草稿」这条能力(editor 或 admin)—— 你现在是 <b>${esc(我的角色 || "?")}</b>,所以这里不摆表单。</div>`}`;
    // ── 版本历史 ──
    const 版本区 = `<h2>版本历史 <span class="k">${版本们.length} 版</span></h2>` + (!版本们.length
      ? `<div class="state"><h3>还没有冻结过版本</h3><p>没有版本的组 Agent 引用不了 —— 在下面「冻结一版」里挑成员、给配套关系,服务端过三道校验就冻成 v1。</p></div>`
      : 版本们.map((v) => {
        const 配 = v["配套关系"] || {};
        return `<details ${v === 版本们[0] ? "open" : ""}><summary><b>${esc(v["版本"])}</b> · ${esc(v["成员数"])} 个成员,${esc(v["必不可少的"])} 个必不可少
            · ${v["冻结时间"] ? 时间(v["冻结时间"]) : "—"} · ${esc(v["冻结的人"] || "—")}
            ${v["变更说明"] ? `· <span class="k" data-raw="原文">${esc(v["变更说明"])}</span>` : ""}</summary>
          <table><thead><tr><th>成员(工具版本)</th><th>加载角色</th><th>这一轮必须给它吗</th><th>给它就得一起给谁</th></tr></thead><tbody>
          ${(v["成员"] || []).map((m) => { const o = typeof m === "string" ? { tool_version_id: m } : m; return `<tr>
            <td>${名(o.tool_version_id)}</td><td class="k">${esc(o["加载角色"] || "候选")}</td>
            <td>${o["必不可少吗"] ? `<span class="pill warn">必不可少</span> <span class="k">预算先放它</span>` : `<span class="pill">可选</span>`}</td>
            <td class="k">${(配[o.tool_version_id] || []).length ? (配[o.tool_version_id] || []).map(名).join("<br>") : "—"}</td></tr>`; }).join("")}
          </tbody></table><div class="k">内容哈希 <code>${esc(v["内容哈希"] || "—")}</code></div></details>`; }).join(""));
    // ── 冻结一版 ──
    const 态 = 组冻结态;
    const 可选 = 工具们.filter((t) => !态.成员.some((m) => m.tool_version_id === t["版本id"]));
    const 冻结区 = !能改 ? "" : `<h2>冻结一版</h2>
      <div class="state"><p class="k">成员选的是每个工具的<b>最新版本</b>(接口只给最新的那个 id)。
        「必不可少」= 这一轮必须给它(预算先放它);「配套」= 给它就得一起给谁 —— <b>两件事,别混</b>。
        ${版本们.length ? `<button id="tgf-copy" class="k">从 ${esc(版本们[0]["版本"])} 带入成员和配套</button>` : ""}
        ${!工具们.length ? `<br>⚠️ 这个项目里没有可选的在用工具(或工具列表拉不到)—— 没有成员冻不了版本。` : ""}</p>
      ${态.成员.length ? `<table><thead><tr><th>成员</th><th>加载角色</th><th>必不可少</th><th>给它就得一起给谁</th><th></th></tr></thead><tbody>
        ${态.成员.map((m, i) => `<tr><td>${名(m.tool_version_id)}</td>
          <td><select data-tgrole="${i}"><option value="候选"${m["加载角色"] === "候选" ? " selected" : ""}>候选</option><option value="常驻"${m["加载角色"] === "常驻" ? " selected" : ""}>常驻</option></select></td>
          <td><input type="checkbox" data-tgreq="${i}"${m["必不可少吗"] ? " checked" : ""}></td>
          <td>${态.成员.length > 1 ? `<select multiple size="${Math.min(4, 态.成员.length - 1)}" data-tgcomp="${m.tool_version_id}">
            ${态.成员.filter((x) => x.tool_version_id !== m.tool_version_id).map((x) => `<option value="${esc(x.tool_version_id)}"${(态.配套[m.tool_version_id] || []).includes(x.tool_version_id) ? " selected" : ""}>${esc((名表[x.tool_version_id] || {})["名"] || x.tool_version_id)}</option>`).join("")}
            </select>` : `<span class="k">再加一个成员才有得配</span>`}</td>
          <td><button data-tgdel="${i}" class="k">移出</button></td></tr>`).join("")}
        </tbody></table>` : `<p class="k">还没挑成员。</p>`}
      <p><label>加一个成员<br><select id="tgf-pick"><option value="">请选择工具(${可选.length} 个可选)</option>
        ${可选.map((t) => `<option value="${esc(t["版本id"])}">${esc(t["名"])} · ${esc(t["读写"] || "")}${t["版本"] ? " · " + esc(t["版本"]) : ""}</option>`).join("")}</select>
        <button id="tgf-add" class="k">加进来</button></label></p>
      <p><label>变更说明(可不填)<br><input id="tgf-note" style="width:min(520px,90%)" value="${esc(态.说明)}" data-raw="原文"></label></p>
      <p><button class="pri" id="tgf-go"${态.成员.length ? "" : " disabled"}>冻结成 v${版本们.length + 1}</button>
        <span class="k">服务端三道校验:模型眼里同名 / 配套成环 / 成员版本还在不在 —— 被拦的话下面逐条列出</span></p></div>`;
    $("#tgdbody").innerHTML = 草稿区 + 版本区 + 冻结区 + `<div class="note">${md(d.note || "")}</div>`;
    挂工具组详情事件(gid, d, 版本们);
  } catch (e) { const s = 错误块(e, () => 画工具组详情(gid)); $("#tgdbody").innerHTML = s.html; s.挂(); }
}

function 挂工具组详情事件(gid, d, 版本们) {
  const 报 = (html) => { if ($("#tgdmsg")) $("#tgdmsg").innerHTML = html; };
  const 态 = 组冻结态;
  const 重画 = () => 画工具组详情(gid);
  // 把表单上的即时改动收回状态(重画前),不然选了角色一重画就丢
  const 收 = () => {
    document.querySelectorAll("[data-tgrole]").forEach((s) => { 态.成员[Number(s.dataset.tgrole)]["加载角色"] = s.value; });
    document.querySelectorAll("[data-tgreq]").forEach((c) => { 态.成员[Number(c.dataset.tgreq)]["必不可少吗"] = c.checked; });
    document.querySelectorAll("[data-tgcomp]").forEach((s) => {
      const v = [...s.selectedOptions].map((o) => o.value);
      if (v.length) 态.配套[s.dataset.tgcomp] = v; else delete 态.配套[s.dataset.tgcomp];
    });
    if ($("#tgf-note")) 态.说明 = $("#tgf-note").value;
  };
  if ($("#tgd-save")) $("#tgd-save").onclick = async () => {
    const 体 = { 名称: ($("#tgd-nm").value || "").trim(), 用途: ($("#tgd-pu").value || "").trim(), 负责人: ($("#tgd-ow").value || "").trim() };
    $("#tgd-save").disabled = true; 报(`<div class="state"><p>保存中…</p></div>`);
    try {
      const r = await 工具组动作.改草稿(gid, $("#tgd-save").dataset.rev, 体);
      await 重画();
      报(`<div class="state"><p>草稿保存了,draft_revision 现在是 ${esc(r.draft_revision)}。${md(r.note ? " " + r.note : "")}</p></div>`);
    } catch (e) {
      const code = (e.体 || {}).code;
      报((e.码 === 409 && (code === "REVISION_CONFLICT" || code === "IF_MATCH_REQUIRED")
        ? `<div class="state err"><h3>这份草稿刚被别人改过</h3><p>${md(e.message)} —— 刷新页面拿新的 draft_revision 再改。</p></div>` : 字段错块(e)));
      $("#tgd-save").disabled = false;
    }
  };
  if ($("#tgf-copy")) $("#tgf-copy").onclick = async () => {
    const v = 版本们[0];
    态.成员 = (v["成员"] || []).map((m) => typeof m === "string" ? { tool_version_id: m, 加载角色: "候选", 必不可少吗: false }
      : { tool_version_id: m.tool_version_id, 加载角色: m["加载角色"] || "候选", 必不可少吗: Boolean(m["必不可少吗"]) });
    态.配套 = JSON.parse(JSON.stringify(v["配套关系"] || {}));
    await 重画();
  };
  if ($("#tgf-add")) $("#tgf-add").onclick = async () => {
    const vid = $("#tgf-pick").value; if (!vid) return;
    收(); 态.成员.push({ tool_version_id: vid, 加载角色: "候选", 必不可少吗: false }); await 重画();
  };
  document.querySelectorAll("[data-tgdel]").forEach((b) => b.onclick = async () => {
    收(); const [去] = 态.成员.splice(Number(b.dataset.tgdel), 1);
    if (去) { delete 态.配套[去.tool_version_id]; Object.keys(态.配套).forEach((k) => { 态.配套[k] = 态.配套[k].filter((x) => x !== 去.tool_version_id); if (!态.配套[k].length) delete 态.配套[k]; }); }
    await 重画();
  });
  if ($("#tgf-go")) $("#tgf-go").onclick = async () => {
    收();
    const 行吗 = await 问一句(`冻结成 v${版本们.length + 1}?`, md(`**${d["名称"] || gid}**:${态.成员.length} 个成员,${态.成员.filter((m) => m["必不可少吗"]).length} 个必不可少,${Object.keys(态.配套).length} 处配套。**冻结之后这一版不能改**,再发现问题只能出下一版。`), { 确定: "冻结" });
    if (!行吗) return;
    $("#tgf-go").disabled = true; 报(`<div class="state"><p>冻结中(服务端过三道校验)…</p></div>`);
    try {
      const r = await 工具组动作.冻结(gid, { 成员: 态.成员, 配套关系: 态.配套, 变更说明: 态.说明.trim() });
      组冻结态 = { gid, 成员: [], 配套: {}, 说明: "" };
      await 重画();
      报(`<div class="state"><p>冻结了 <b>${esc(r["版本"])}</b>(${esc(r["成员数"])} 个成员)。${md(r.note || "")}</p></div>`);
    } catch (e) { 报(字段错块(e)); if ($("#tgf-go")) $("#tgf-go").disabled = false; }
  };
}

/* ── 成员与权限:加成员 / 改角色与专项授权 ─────────────────────────────
 *
 * ⚠️ **这一页最硬的一条闸和别的都不一样。**
 * 别的闸拦「你做错了」,这一道拦「**你做完之后没法回头**」:
 * 不许把项目里**最后一个能改权限的人**降下来 —— 降了之后
 * 没有任何人能把权限加回来,而那一刻**界面上什么都不会报**。
 * 所以这一页把「现在有几个人能改权限」**显式写出来**,
 * 只剩一个的时候**标出来** —— 一个只在被拒那一刻才出现的警告,来得太晚。
 *
 * ⚠️ **`可授权` 那一档默认是关闭的。** 一个角色「可以被授权某条能力」
 * 和「默认就有它」是两件事,而**角色名上完全看不出来**。
 * 所以专项授权那一栏只列接口给的 `可授权的能力` ——
 * 把 12 条全列出来的话,大部分填了会被闸拒。
 *
 * ⚠️ **这个接口是「加成员 / 改权限」同一个口。** 同一个工号再 POST 一次
 * 就是改他 —— 所以表单上那个按钮写的是「保存」而不是「新增」:
 * 写「新增」会让人以为改权限要去别处找。
 */
const 成员动作 = {
  // 门店(11-21):传 undefined = 不动这一项;传 "" = 清成「不限门店」;传编号 = 登记到那个门店
  async 保存(工号, 角色, 专项授权, 门店) {
    const 体 = { 工号, 角色, 专项授权: 专项授权 || [] };
    if (门店 !== undefined) 体.门店 = 门店;
    return await 请求(`${P()}/memberships`, { method: "POST", body: JSON.stringify(体) });
  },
};
if (typeof globalThis !== "undefined") globalThis.成员动作 = 成员动作;
// 账号 ↔ 澜绣员工一对一绑定(10-24)。按钮只调这两个 —— 测试也调这两个,接线只有一份
const 绑定动作 = {
  async 绑(账号, 澜绣工号) {
    return await 请求(`${P()}/staff-bindings/${encodeURIComponent(账号)}`,
      { method: "PUT", body: JSON.stringify({ "澜绣工号": 澜绣工号 }) });
  },
  async 解绑(账号) {
    return await 请求(`${P()}/staff-bindings/${encodeURIComponent(账号)}`, { method: "DELETE" });
  },
};
if (typeof globalThis !== "undefined") globalThis.绑定动作 = 绑定动作;

function 页_成员表单(d, 预填) {
  const 能配 = 我的角色 === "admin";
  if (!能配) {
    return `<div class="note">改成员权限要「配置密钥与预算」这条能力 ——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>:
      摆一个填完被 403 的表单,只是把拒绝往后挪一步。</div>`;
  }
  const 角色们 = d["可选角色"] || [];
  const p = 预填 || {};
  const 已有 = new Set(p["专项授权"] || []);
  const 初角 = p["角色"] || (角色们[0] && 角色们[0]["值"]) || "";
  return `<div class="state">
    <h3>${p["工号"] ? `改 ${esc(p["工号"])} 的权限` : "加一个成员"}</h3>
    <p class="k">${md(d["⚠️可授权是默认关的"] || "")}</p>
    <p><label>工号<br><input id="m-uid" style="width:min(220px,80%)"
      value="${esc(p["工号"] || "")}"${p["工号"] ? " readonly" : ""}></label>
      ${p["工号"] ? `<span class="k">（同一个工号再提交一次就是改他 ——
        <b>加成员和改权限是同一个口</b>）</span>` : ""}</p>
    <p><label>角色<br><select id="m-role">${角色们.map((r) =>
      `<option value="${esc(r["值"])}"${r["值"] === p["角色"] ? " selected" : ""}
        >${esc(r["中文"])}（${esc(r["值"])}）</option>`).join("")}</select></label></p>
    <p><label>门店（照澜绣的门店编号,如 SH001;<b>留空 = 不限门店</b>）<br><input id="m-store" style="width:min(220px,80%)"
      value="${esc(p["门店"] || "")}" placeholder="不限门店"></label>
      <span class="k">只管一件事:人工待办他看哪些 —— 登记了门店就只看本店的单子;聊天站里店长处理待办走的也是这条范围。</span></p>
    <p>专项授权（<b>只列这个角色可授权的那几条</b>,换角色会跟着变）<br>
      <span id="m-grants">${授权框html(d, 初角, 已有)}</span></p>
    <p><button class="pri" id="m-go">保存</button>
      ${p["工号"] ? `<button id="m-cancel">取消</button>` : ""}</p></div>`;
}

/* 专项授权的勾选框:接口的 `可授权的能力` 是**按角色**给的(dict),不是一张总表 —— 给一个角色加它不能被授权的能力
 * 「存得下但不生效」。11-18 查实:页面原来把它当数组 `.map`,**管理员一打开成员页整页只剩「出错了」**;
 * CI 冒烟用的是 U002(非管理员,不摆表单),所以从没红过。 */
function 授权框html(d, 角色, 已有) {
  const 表 = d["可授权的能力"] || {};
  const 们 = Array.isArray(表) ? 表 : (表[角色] || []);
  if (!们.length) return `<span class="k">这个角色没有可授权的能力</span>`;
  return 们.map((c, i) => `<label style="display:inline-block;margin-right:10px">
    <input type="checkbox" data-grant="${i}" value="${esc(c)}"${已有.has(c) ? " checked" : ""}> ${esc(c)}</label>`).join("");
}

function 挂成员事件(d) {
  document.querySelectorAll("[data-edit]").forEach((b) => {
    b.onclick = () => {
      const 行 = (d["成员"] || []).find((x) => x["工号"] === b.dataset.edit);
      if ($("#mform")) $("#mform").innerHTML = 页_成员表单(d, 行);
      挂成员事件(d);
    };
  });
  if ($("#m-cancel")) {
    $("#m-cancel").onclick = () => {
      if ($("#mform")) $("#mform").innerHTML = 页_成员表单(d, null);
      挂成员事件(d);
    };
  }
  const 角 = $("#m-role");
  if (角 && $("#m-grants")) {
    角.onchange = () => {           // 换角色 → 可授权的那几条跟着换,已勾的还在名单里就保留
      const 勾 = new Set();
      document.querySelectorAll("[data-grant]").forEach((c) => { if (c.checked) 勾.add(c.value); });
      $("#m-grants").innerHTML = 授权框html(d, 角.value, 勾);
    };
  }
  if (!$("#m-go")) return;
  $("#m-go").onclick = async () => {
    const 专 = [];
    document.querySelectorAll("[data-grant]").forEach((c) => {
      if (c.checked) 专.push(c.value);
    });
    const uid = ($("#m-uid").value || "").trim();
    $("#m-go").disabled = true;
    if ($("#mmsg")) $("#mmsg").innerHTML = `<div class="state"><p>保存中…</p></div>`;
    try {
      const r = await 成员动作.保存(uid, $("#m-role").value, 专, $("#m-store") ? ($("#m-store").value || "").trim() : undefined);
      // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
      await 页_成员与权限();
      if ($("#mmsg")) {
        $("#mmsg").innerHTML = `<div class="state"><p>保存了 ——
          <b>实际能做的</b>:${esc(((r["实际能做的"] || []).join("、")) || "—")}
          ${md(r.note ? "。" + r.note : "")}</p></div>`;
      }
    } catch (e) {
      // ⚠️ **闸的每一条都要显示出来。** 这一页的闸里有一条
      // 「你是最后一个能改权限的人」—— 只显示 message 的话
      // 人看到的是「改不了」,而**为什么**在 field_errors.闸 里。
      if ($("#mmsg")) $("#mmsg").innerHTML = `<div class="state err">
        <p>${md(闸文(e))}</p></div>`;
      $("#m-go").disabled = false;
    }
  };
}

async function 页_成员与权限() {
  $("#main").innerHTML = `<div class="crumb">设置 / 成员与权限</div>
    <div class="head"><div><h1>成员与权限</h1>
      <div class="sub">给的是 <b>他实际能做什么</b>,不只是角色名 ——
        「可授权」那一档<b>默认是关闭的</b>,而角色名上看不出关没关。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/memberships`);
    // 账号 ↔ 澜绣员工一对一绑定(用户 10-24 拍):聊天站发起被接管的工作流时,按澜绣工号换成这里的账号
    const 绑 = {};
    try {
      ((await 请求(`${P()}/staff-bindings`)).items || []).forEach((x) => { 绑[x["账号"]] = x["澜绣工号"]; });
    } catch (e) { /* 读不到绑定不挡成员列表;那一栏显示「读不到」 */ 绑.__坏 = true; }
    $("#list").innerHTML = `<table><thead><tr><th>工号</th><th>角色</th><th>门店</th>
      <th>这条生效吗</th><th>专项授权</th><th>实际能做的</th><th>绑的澜绣员工</th><th>改</th>
      </tr></thead><tbody>`
      + d["成员"].map((r) => `<tr>
        <td><b>${esc(r["工号"])}</b></td>
        <td>${esc(r["角色中文"] || r["角色"])}<div class="k">${esc(r["角色"])}</div></td>
        <td>${r["门店"] ? esc(r["门店"]) : `<span class="k" title="没登记门店 = 不限门店,人工待办看全部">不限</span>`}</td>
        <td>${r["这条生效吗"] ? `<span class="pill">生效</span>`
              : `<span class="pill warn">不生效(登录那一步查不到)</span>`}</td>
        <td class="k">${esc((r["专项授权"] || []).join("、") || "—")}</td>
        <td>${(r["实际能做的"] || []).map((x) =>
              `<span class="pill">${esc(x)}</span>`).join(" ")}</td>
        <td>${绑.__坏 ? `<span class="k">读不到</span>`
            : 我的角色 === "admin"
            ? `<input data-bindin="${esc(r["工号"])}" value="${esc(绑[r["工号"]] || "")}" size="9"
                 placeholder="澜绣工号">
               <button data-bind="${esc(r["工号"])}">保存</button>
               ${绑[r["工号"]] ? `<button data-unbind="${esc(r["工号"])}">解绑</button>` : ""}`
            : esc(绑[r["工号"]] || "—")}</td>
        <td>${我的角色 === "admin"
            ? `<button data-edit="${esc(r["工号"])}">改权限</button>`
            : `<span class="k">要「配置密钥与预算」</span>`}</td></tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        <b>能改权限的（${(d["能改权限的"] || []).length} 人）:</b>
        ${esc((d["能改权限的"] || []).join("、") || "(一个都没有)")}
        ${(d["能改权限的"] || []).length <= 1
          ? `<br><b>⚠️ 只剩一个人能改权限</b> —— 把他降下来之后
             <b>没有任何人能把权限加回来</b>,而那一刻界面上什么都不会报。
             <b>先加一个再动他。</b>`
          : ""}
        <br>⚠️ <b>不许把最后一个能改权限的人去掉</b>:
        别的闸拦「做错了」,<b>这一道拦「做完之后没法回头」</b> ——
        那个状态<b>从接口这一侧救不回来</b>。</div>`
      + `<div id="mmsg"></div><div id="mform"></div>`;
    if ($("#mform")) $("#mform").innerHTML = 页_成员表单(d, null);
    挂成员事件(d);
    挂绑定事件();
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* 账号 ↔ 澜绣员工绑定(10-24)。一对一:工号已绑给别人 → 409 STAFF_TAKEN,原样显示 advice */
function 挂绑定事件() {
  const 说 = (html, 坏) => { if ($("#mmsg")) $("#mmsg").innerHTML = 坏
    ? `<div class="state err"><p>${html}</p></div>` : `<div class="state"><p>${html}</p></div>`; };
  document.querySelectorAll("[data-bind]").forEach((b) => {
    b.onclick = async () => {
      const 账号 = b.dataset.bind;
      const 框 = document.querySelector(`[data-bindin="${CSS.escape(账号)}"]`);
      const 工号 = ((框 && 框.value) || "").trim();
      if (!工号) { 说("要填澜绣工号;想解绑就点「解绑」", true); return; }
      b.disabled = true;
      try {
        await 绑定动作.绑(账号, 工号);
        await 页_成员与权限();
        说(`绑好了:${esc(账号)} ↔ 澜绣 ${esc(工号)}`);
      } catch (e) {
        说(`${esc(e.message)}${e.体 && e.体.advice ? " —— " + md(e.体.advice) : ""}`, true);
        b.disabled = false;
      }
    };
  });
  document.querySelectorAll("[data-unbind]").forEach((b) => {
    b.onclick = async () => {
      // 11-08 用户拍:解绑后这名员工在聊天里就发起不了被接管的工作流
      if (!(await 问一句("解绑这名员工?", `解绑后,工号 ${esc(b.dataset.unbind)} 在聊天里就发起不了被接管的工作流了。`, { 确定: "解绑" }))) return;
      b.disabled = true;
      try {
        await 绑定动作.解绑(b.dataset.unbind);
        const 谁 = b.dataset.unbind;
        await 页_成员与权限();
        说(`解绑了 ${esc(谁)} —— 他在聊天里碰到被接管的事,将发起不了工作流`);
      } catch (e) { 说(esc(e.message), true); b.disabled = false; }
    };
  });
}

/* ── 数据集:新建 / 冻结一版 / 导出 / 补脱敏声明 ──────────────────────
 *
 * 11-18 体检:这一页原来**零动作** —— 后端四条写口(建 / 冻结 / 导出 / 改样本)一条都没接,
 * 而「卡在哪」第一条常是「没声明脱敏策略……下一步是去声明」,**而全仓没有一条接口能声明**
 * (redaction_policy 只能在建的时候给)。真项目 3 个数据集里 2 个卡在这。
 * 所以今晚补的是:后端 PATCH /datasets/{id}(只收 脱敏策略 / 用途,要 If-Match),
 * 前端把四个动作摆上,「没声明脱敏策略」旁边直接给「去声明」。
 *
 * ⚠️ 导出那条**不是读一下数据**:成功返回的是 NDJSON 文件(不是 JSON),所以不走 请求();
 * 403 NEED_CONTENT_GRANT 是**权限不够**不是坏了 —— 把 advice 原样显示;
 * 422(一条都不剩 / 没声明 / 脱敏器没选型)把后端那几句原样显示 —— training.py 文件头:
 * 「一条都不剩必须是拒,不是空文件」,所以这里也不许把 422 画成「导出了 0 条」。
 *
 * 按钮按能力摆(服务端给的 `能力`,老接口没有时退回角色):改训练样本 → 建 / 冻结 / 改声明 / 导出;
 * 导出另要「查看敏感输入/独立测试答案」,摆不摆由前者定,后者只写一句提醒 —— 真拦截在服务端(§5.2)。 */
const 脱敏声明选项 = [
  ["无需", "无需脱敏:<理由> —— 这份数据里没有要脱的东西(导出放行,一个字都不改)"],
  ["需要", "需要脱敏(描述脱什么)—— 脱敏器还没选型,声明了导出仍会被拦,但拦的理由会变对"],
];
function 脱敏声明表单(当前) {
  const 当 = String(当前 || "");
  const 无需 = /^无需脱敏[::]/.test(当);
  const 种 = !当 ? "无需" : 无需 ? "无需" : "需要";
  const 文 = 无需 ? 当.replace(/^无需脱敏[::]/, "") : 当;
  return `<label class="f">脱敏策略</label>
    <select class="t" id="ds-种">${脱敏声明选项.map(([k, t]) =>
      `<option value="${k}"${k === 种 ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>
    <label class="f" id="ds-理由标"><span>${种 === "无需" ? "为什么无需脱敏" : "需要脱什么"}</span> <span class="req">*</span></label>
    <textarea class="t" id="ds-理由" rows="2" placeholder="比如:全部是评测题面,由标注员手写,不含客户信息">${esc(文)}</textarea>`;
}
function 读脱敏声明() {
  const 种 = $("#ds-种") ? $("#ds-种").value : "无需";
  const 理由 = ($("#ds-理由") ? $("#ds-理由").value : "").trim();
  if (!理由) return { 错: 种 === "无需" ? "「无需脱敏」后面要写理由 —— 导出会照它放行且一个字都不改" : "要写清需要脱什么" };
  return { 值: 种 === "无需" ? `无需脱敏:${理由}` : 理由 };
}
function 挂脱敏声明切换() {
  const s = $("#ds-种"); if (!s) return;
  s.onchange = () => { const l = $("#ds-理由标"); if (l) l.innerHTML = `<span>${s.value === "无需" ? "为什么无需脱敏" : "需要脱什么"}</span> <span class="req">*</span>`; };
}
const 数据集动作 = {
  能改() {
    return (能力 || []).includes("改训练样本") || 我的角色 === "annotator" || 我的角色 === "admin";
  },
  能看原文() { return (能力 || []).includes("查看敏感输入/独立测试答案"); },
  async 建(体) {
    return await 请求(`${P()}/datasets`, { method: "POST", body: JSON.stringify(体) });
  },
  async 冻结(dsid) {
    return await 请求(`${P()}/datasets/${encodeURIComponent(dsid)}/versions`, { method: "POST", body: "{}" });
  },
  async 改(dsid, 补丁, revision) {
    if (revision == null) {
      const e = new Error("这一行读不到 revision —— 列表接口应该给它");
      e.体 = { code: "NO_DATASET_REVISION", advice: "刷新一次;还是这样就是列表接口没返回 revision" }; e.码 = 0;
      throw e;
    }
    return await 请求(`${P()}/datasets/${encodeURIComponent(dsid)}`,
      { method: "PATCH", headers: { "If-Match": String(revision) }, body: JSON.stringify(补丁) });
  },
  // 导出成功是 NDJSON 文件,不是 JSON —— 自己 fetch,成功交回 { 文, 头 },失败抛和 请求() 同形的错
  async 导出(dsid, 要mock) {
    const r = await fetch(`${P()}/datasets/${encodeURIComponent(dsid)}/export${要mock ? "?要mock=1" : ""}`,
      { headers: { "X-Dev-User": 我 } });
    if (!r.ok) {
      let b = null; try { b = await r.json(); } catch (e) { b = null; }
      const err = new Error((b && b.message) || `HTTP ${r.status}`); err.体 = b || {}; err.码 = r.status; throw err;
    }
    const 文 = await r.text();
    const 头 = {}; ["x-sample-count", "x-contains-mock", "x-quarantined", "x-quarantined-by", "x-redacted", "content-disposition"]
      .forEach((k) => { 头[k] = r.headers.get(k); });
    return { 文, 头 };
  },
};
if (typeof globalThis !== "undefined") globalThis.数据集动作 = 数据集动作;

async function 页_数据集() {
  const 能改 = 数据集动作.能改();
  $("#main").innerHTML = `<div class="crumb">评测与训练 / 数据集</div>
    <div class="head"><div><h1>数据集</h1>
      <div class="sub">这一页回答 <b>能不能导出、卡在哪</b> ——
        而「能导出吗」是<b>现算</b>的,不是存的字段(存的会漂)。</div></div>
      <div class="acts">${能改 ? `<label class="k" title="mock 的产物不许计入真实训练 —— 只在自测导出流程时勾;不勾时遇到 mock 样本,服务端会拒并说明"><input type="checkbox" id="ds-mock"> 导出时包含演示(mock)样本</label>
        <button class="pri" id="ds-new">新建数据集</button>`
        : `<span class="k">新建 / 冻结 / 导出 / 改声明要「改训练样本」这条能力(标注员、管理员默认有;编辑、训练操作员要专项授权),你是 ${esc(我的角色 || "?")}</span>`}</div></div>
    <div id="dsmsg"></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  if (能改) $("#ds-new").onclick = 新建数据集表单;
  await 画数据集();
}

function 数据集提示(html, 坏) {
  if (!$("#dsmsg")) return;
  // class 写成两段字面,不拼 —— css_class_check 钉着「拼出来的 class 只许少不许多」
  $("#dsmsg").innerHTML = 坏 ? `<div class="note warn">${html}</div>` : `<div class="note">${html}</div>`;
}
// 把后端一条拒的错误体画成人能照着做的话:code · message · advice,field_errors 逐条原样(data-raw)
function 拒的明细(e) {
  const b = e.体 || {};
  const 条 = Object.entries(b.field_errors || {}).map(([k, v]) => {
    const 值 = Array.isArray(v) ? v : [v];
    return `<li><b>${esc(k)}</b>:${值.map((x) => `<span>${md(String(x))}</span>`).join("<br>")}</li>`;
  }).join("");
  return `<b>${esc(b.code || "出错了")}</b> · <span>${md(e.message || "")}</span>`
    + (b.advice ? `<br><b>下一步:</b><span>${md(b.advice)}</span>` : "")
    + (条 ? `<ul>${条}</ul>` : "");
}

async function 画数据集() {
  const 能改 = 数据集动作.能改(), 能看原文 = 数据集动作.能看原文();
  try {
    const d = await 请求(`${P()}/datasets`);
    if (!d["数据集"].length) {
      $("#list").innerHTML = 状态("", "还没有数据集",
        (d.note || "") + (能改 ? "\n\n点右上角「新建数据集」建第一个 —— 建的时候就把脱敏策略声明了,省得回头补。" : "")).html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>数据集</th><th>样本</th>
      <th>分档</th><th>冻结的版本</th><th>脱敏策略</th><th>能导出吗 / 卡在哪</th><th>动作</th></tr></thead><tbody>`
      + d["数据集"].map((r) => {
        const 卡 = r["卡在哪"] || [];
        // 后端那几句是判据,整句显示不截断(原来只给第一条的前 54 字);「没声明脱敏策略」旁边直接给「去声明」—— 建议指着的动作就在旁边
        const 卡块 = 卡.map((x) => `<div class="k">${md(x)}${
          能改 && /没声明脱敏策略/.test(x)
            ? ` <button class="mini" data-declare="${esc(r.id)}" data-rev="${esc(r.revision)}">去声明</button>` : ""}</div>`).join("");
        // 今晚刚加的 版本们(id / 样本数 / 冻结于);老后端没有它时退回计数
        const 版 = Array.isArray(r["版本们"])
          ? (r["版本们"].length
              ? r["版本们"].map((v) => `<div class="k"><code style="font-size:11px">${esc(v.id)}</code> · ${esc(v["样本数"])} 条 · ${时间(v["冻结于"])}</div>`).join("")
              : `<span class="k">还没冻结过</span>`)
          : `${esc(r["冻结过几版"])} 版`;
        return `<tr data-dsrow="${esc(r.id)}">
        <td><b>${md(r["名字"])}</b><div class="k">${esc(r.id)} · ${esc(r["格式"] || "?")}${r["用途"] ? ` · <span>${md(r["用途"])}</span>` : ""}</div>
          <div class="k">revision ${esc(r.revision)}</div></td>
        <td>${r["样本数"]
          ? `<a href="#/samples/${encodeURIComponent(r.id)}">${r["样本数"]}</a>`
          : `<span class="k">0</span>`}</td>
        <td class="k">${esc(Object.entries(r["分档"] || {})
              .map(([k, v]) => `${k} ${v}`).join("、") || "—")}</td>
        <td>${版}</td>
        <td>${r["脱敏策略"] ? `<span>${md(r["脱敏策略"])}</span>` : `<span class="pill warn">没声明</span>`}</td>
        <td>${r["能导出吗"] ? `<span class="pill ok">可以</span>` : `<span class="pill warn">不行</span>`}
          ${卡块}
          ${r["还有一道看内容的闸"]
            ? `<div class="k">⚠️ <span data-raw="原文">${esc(r["还有一道看内容的闸"])}</span></div>` : ""}
        </td>
        <td class="relacts">${能改 ? `
          <button class="mini" data-freeze="${esc(r.id)}">冻结一版</button>
          <button class="mini" data-export="${esc(r.id)}" title="${能看原文 ? "" : "你没有「查看敏感输入/独立测试答案」授权 —— 点了会被 403 拦,那不是坏了"}">导出</button>
          <button class="mini" data-declare="${esc(r.id)}" data-rev="${esc(r.revision)}">改脱敏策略 / 用途</button>
          ${能看原文 ? "" : `<div class="k">导出另要「查看敏感输入」授权</div>`}`
          : `<span class="k">要「改训练样本」</span>`}</td></tr>`;
      }).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
    if (!能改) return;
    document.querySelectorAll("[data-freeze]").forEach((b) => { b.onclick = () => 冻结一版(b); });
    document.querySelectorAll("[data-export]").forEach((b) => { b.onclick = () => 导出数据集(b); });
    document.querySelectorAll("[data-declare]").forEach((b) => {
      b.onclick = () => 改数据集表单(b.dataset.declare, b.dataset.rev,
        ((d["数据集"] || []).find((x) => x.id === b.dataset.declare) || {}));
    });
  } catch (e) { const s = 错误块(e, 画数据集); $("#list").innerHTML = s.html; s.挂(); }
}

async function 冻结一版(b) {
  const dsid = b.dataset.freeze;
  if (!(await 问一句("冻结一版?", `把 <code>${esc(dsid)}</code> 现在的全部样本<b>固化</b>成一个版本 —— 之后改样本不会改到这一版。<br>
    内容和上一版一模一样时<b>不会新建</b>(同样的字节冻出两个版本号,「那次评测用的是哪一版」就有了两个答案)。`, { 确定: "冻结" }))) return;
  b.disabled = true;
  数据集提示("冻结中…");
  try {
    const r = await 数据集动作.冻结(dsid);
    数据集提示(`${r["新建了吗"] === false ? "<b>没有新建</b>" : "<b>冻好了</b>"}:版本 <code>${esc(r.id)}</code> · ${esc(r["样本数"])} 条 · 分集 ${esc(Object.entries(r["分集"] || {}).map(([k, v]) => `${k} ${v}`).join("、") || "—")}<br>
      <span>${md(r.note || "")}</span>`, r["新建了吗"] === false);
    await 画数据集();
  } catch (e) {
    // 422 CANNOT_FREEZE 的 field_errors.样本 是一条条「还差什么」—— 一次报全,原样给
    数据集提示(拒的明细(e), true);
    b.disabled = false;
  }
}

async function 导出数据集(b) {
  const dsid = b.dataset.export;
  b.disabled = true;
  数据集提示("导出中…(服务端要过八道闸)");
  try {
    // 11-19:原来写死 false,后端的「要mock」开关页面上没处可开 —— 体检记录在案的那条
    const 要mock = !!($("#ds-mock") && $("#ds-mock").checked);
    const { 文, 头 } = await 数据集动作.导出(dsid, 要mock);
    const 条数 = (文 || "").split("\n").filter((x) => x.trim()).length;
    // ⚠️ 空文件按契约不该出现(一条不剩是 422)—— 真出现了就是后端的契约破了,明说,别画成「导出了 0 条」
    if (!条数) {
      数据集提示(`<b>服务端返回了一个空文件</b>(x-sample-count=${esc(头["x-sample-count"])})—— 按契约「一条都不剩必须是拒,不是空文件」,这是后端的契约破了,别拿它去训练。`, true);
      b.disabled = false; return;
    }
    const 名 = ((头["content-disposition"] || "").match(/filename="([^"]+)"/) || [])[1] || `${dsid}.jsonl`;
    let 链 = "";
    if (typeof Blob !== "undefined" && typeof URL !== "undefined" && URL.createObjectURL) {
      const url = URL.createObjectURL(new Blob([文], { type: "application/x-ndjson" }));
      链 = `<a href="${url}" download="${esc(名)}">下载 ${esc(名)}</a>`;
    }
    const 隔离 = Number(头["x-quarantined"] || 0);
    数据集提示(`<b>导出了 ${条数} 条</b>(JSONL,每行一条 {id, content})${链 ? " · " + 链 : ""}<br>
      <span class="k">含 mock:${esc(头["x-contains-mock"] || "?")} · 脱敏:${esc(头["x-redacted"] || "?")}
      · 被敏感信息检测隔离 ${隔离} 条${隔离 ? `(${esc(头["x-quarantined-by"] || "")};每条为什么在审计记录 dataset.export 里)` : ""}</span>
      <details><summary>看前 3 行</summary><pre class="io" data-raw="原文">${esc(文.split("\n").slice(0, 3).join("\n"))}</pre></details>`,
      隔离 > 0);
  } catch (e) {
    const b体 = e.体 || {};
    if (e.码 === 403 && b体.code === "NEED_CONTENT_GRANT") {
      // 权限不够不是坏了:能改样本不等于能把全部原文带走 —— 把 advice 原样显示
      数据集提示(`<b>导出要另一条授权</b>(${esc(b体.code)}):<span>${md(e.message)}</span><br>
        <b>下一步:</b><span>${md(b体.advice || "")}</span>`, true);
    } else {
      // 422:没声明 / 脱敏器没选型 / 一条都不剩 —— 后端的话原样给,field_errors.闸 / 账 / 隔离 逐条
      数据集提示(拒的明细(e), true);
    }
  }
  b.disabled = false;
}

function 新建数据集表单() {
  弹层("新建数据集", `
    <label class="f">名字 <span class="req">*</span></label><input class="t" id="ds-名" placeholder="比如:门店顾问问答留出集">
    <label class="f">格式 <span class="req">*</span></label><input class="t" id="ds-格" placeholder="qa 或 jsonl(现有的两种)" value="qa">
    <label class="f">用途</label><input class="t" id="ds-途" placeholder="评测 / 训练 / 其他(可不填)" value="评测">
    <div class="note">脱敏策略<b>建的时候就声明</b> —— 不声明也能建,但导出会被拦在「没声明」那道闸上,回头还得来补。</div>
    ${脱敏声明表单("")}
    <div id="ds-err" class="err"></div>
    <div class="acts" style="margin-top:12px"><button class="pri" id="ds-ok">建</button> <button id="ds-no">取消</button></div>`);
  挂脱敏声明切换();
  $("#ds-no").onclick = 关弹层;
  $("#ds-ok").onclick = async () => {
    const 名 = $("#ds-名").value.trim(), 格 = $("#ds-格").value.trim(), 途 = $("#ds-途").value.trim();
    if (!名 || !格) { $("#ds-err").textContent = "名字和格式都要填。"; return; }
    const 声 = 读脱敏声明();
    if (声.错) { $("#ds-err").textContent = 声.错; return; }
    $("#ds-ok").disabled = true;
    try {
      const r = await 数据集动作.建({ 名字: 名, 格式: 格, 用途: 途 || null, 脱敏策略: 声.值 });
      关弹层();
      数据集提示(`<b>建好了</b>:<code>${esc(r.id)}</code> ${esc(r["名字"])}。<span>${md(r.note || "")}</span>`);
      await 画数据集();
    } catch (e) {
      $("#ds-err").innerHTML = 拒的明细(e);
      $("#ds-ok").disabled = false;
    }
  };
}

function 改数据集表单(dsid, rev, 行) {
  弹层("改脱敏策略 / 用途", `
    <div class="k"><code>${esc(dsid)}</code> · ${esc(行["名字"] || "")} · revision ${esc(rev)}</div>
    ${脱敏声明表单(行["脱敏策略"] || "")}
    <label class="f">用途</label><input class="t" id="ds-途" placeholder="评测 / 训练 / 其他" value="${esc(行["用途"] || "")}">
    <div class="note">${md("只改这两项。名字 / 格式不在这里改:名字改了冻结过的版本对不上人话,格式改了样本不会跟着变 —— 那是「换一个数据集」的事。**声明成「需要脱敏」是对的**,但脱敏器还没选型,导出仍会被拦,拦的理由会从「没声明」变成「脱敏器没选型」。")}</div>
    <div id="ds-err" class="err"></div>
    <div class="acts" style="margin-top:12px"><button class="pri" id="ds-ok">保存</button> <button id="ds-no">取消</button></div>`);
  挂脱敏声明切换();
  $("#ds-no").onclick = 关弹层;
  $("#ds-ok").onclick = async () => {
    const 声 = 读脱敏声明();
    if (声.错) { $("#ds-err").textContent = 声.错; return; }
    const 补 = { 脱敏策略: 声.值, 用途: $("#ds-途").value.trim() || null };
    $("#ds-ok").disabled = true;
    try {
      const r = await 数据集动作.改(dsid, 补, rev);
      关弹层();
      数据集提示(`<b>改好了</b>(revision ${esc(r.revision)},改了 ${esc((r["改了"] || []).join("、"))})。
        现在${r["能导出吗"] ? `<span class="pill ok">能导出</span>` : `<span class="pill warn">仍不能导出</span>`}
        ${(r["卡在哪"] || []).map((x) => `<div class="k">${md(x)}</div>`).join("")}
        <span>${md(r.note || "")}</span>`, !r["能导出吗"]);
      await 画数据集();
    } catch (e) {
      const b = e.体 || {};
      if (e.码 === 409) {
        // IF_MATCH_REQUIRED / REVISION_CONFLICT:别人改过了 —— 提示刷新,不许用旧 revision 覆盖
        $("#ds-err").innerHTML = `${esc(b.code || "409")}:<span>${md(e.message)}</span>
          <br>${md(b.advice || "")} <button class="mini" id="ds-refresh">刷新列表</button>`;
        $("#ds-refresh").onclick = async () => { 关弹层(); await 画数据集(); };
      } else {
        $("#ds-err").innerHTML = 拒的明细(e);
      }
      $("#ds-ok").disabled = false;
    }
  };
}

/* ── 数据集 / 样本:看一条、改一条 ────────────────────────────────────
 *
 * ⚠️ **原文默认看不到,而这一页不去绕它。**
 * 样本是真实客户对话(姓名/手机/地址/尺寸)。接口给的是形状和标注
 * (分集、复核状态、内容哈希、**字数**、revision),原文要那条字段级授权。
 * 所以这一页:
 *   · 没有授权时显示**字数**,并明说为什么看不到 —— **不显示截断版**:
 *     截到前几个字,那几个字仍然是原文,而「截断过」会让人以为它安全了;
 *   · 「本来是空的」和「被挡住了」**画成两种** —— 下一步完全不同。
 *
 * ⚠️ 改样本的 `If-Match` 认的是**那条样本自己的 revision**,
 * 不是数据集的。混起来的表现是 409「这条样本已经被改过」,
 * 而它读起来像「别人改过了」。
 */
const 样本动作 = {
  async 改(dsid, sid, 补丁, 样本revision) {
    // ⚠️ revision 为空时当场报错,不发请求 —— 服务端会回
    // 409 IF_MATCH_REQUIRED,而那句话让人以为是接口的问题。
    if (样本revision == null) {
      const e = new Error("这条样本读不到 revision —— 样本列表应该给它");
      e.体 = { code: "NO_SAMPLE_REVISION",
               advice: "刷新一次;还是这样就是列表接口没返回 revision" };
      e.码 = 0;
      throw e;
    }
    return await 请求(
      `${P()}/datasets/${encodeURIComponent(dsid)}`
      + `/samples/${encodeURIComponent(sid)}`,
      { method: "PATCH", headers: { "If-Match": String(样本revision) },
        body: JSON.stringify(补丁) });
  },
};
if (typeof globalThis !== "undefined") globalThis.样本动作 = 样本动作;

async function 页_样本(dsid) {
  $("#main").innerHTML = `<div class="crumb">评测与训练 /
      <a href="#/datasets">数据集</a> / 样本</div>
    <div class="head"><div><h1>样本</h1>
      <div class="sub"><b>原文默认看不到</b> —— 样本是真实客户对话。
        给的是形状和标注,<b>不给截断版</b>:截到前几个字,那几个字仍然是原文。</div>
    </div></div>
    <div id="smsg"></div>
    <div id="slist"><div class="state">加载中…</div></div>`;
  await 画样本(dsid);
}

async function 画样本(dsid) {
  try {
    const d = await 请求(`${P()}/datasets/${encodeURIComponent(dsid)}/samples`);
    const 样本们 = d["样本们"] || [];
    if (!样本们.length) {
      $("#slist").innerHTML = 状态("", "这个数据集里一个样本都没有",
        "**空的导出文件看起来是成功的** —— 所以导出那道闸会先拦住它。").html;
      return;
    }
    const 分集选项 = (d["可选分集"] || []);
    const 复核选项 = (d["可选复核状态"] || []);
    const 能改 = 我的角色 === "annotator" || 我的角色 === "admin"
      || 我的角色 === "editor";
    $("#slist").innerHTML = `<div class="note">
        ${d["看得到原文吗"]
          ? `<b>你有「查看敏感输入」授权,下面显示原文。</b>`
          : `<b>你看不到原文</b>(要「查看敏感输入/独立测试答案」专项授权)——
             下面给的是字数和哈希,<b>足够做「改哪一条」这个动作</b>。`}
        <br>${md(d.note || "")}</div>
      <table><thead><tr><th>样本</th><th>分集</th><th>复核状态</th><th>组</th>
        <th>内容</th><th>改</th></tr></thead><tbody>`
      + 样本们.map((s) => {
        const 内 = s["内容"] || {};
        // ⚠️ 三种情况三种画法:给看 / 不给看 / 本来就是空的。
        const 内格 = !内["有内容吗"]
          ? `<span class="k">这条本身是空的</span>`
          : 内["原文"] != null
            ? `<code style="font-size:11px">${esc(
                 JSON.stringify(内["原文"]).slice(0, 80))}</code>`
            : `<span class="k">${内["字数"]} 字 · 被挡住(没授权)</span>`;
        return `<tr><td><code style="font-size:11px">${esc(s.id)}</code>
            <div class="k">revision ${esc(s["revision"])}
              —— <b>改它的 If-Match 认这个</b></div></td>
          <td>${能改
            ? `<select data-sp="split" data-sid="${esc(s.id)}">${
                分集选项.map((x) => `<option${x === s["分集"] ? " selected" : ""}
                  >${esc(x)}</option>`).join("")}</select>`
            : esc(s["分集"] || "—")}</td>
          <td>${能改
            ? `<select data-sp="review" data-sid="${esc(s.id)}">${
                复核选项.map((x) => `<option${x === s["复核状态"] ? " selected" : ""}
                  >${esc(x)}</option>`).join("")}</select>`
            : esc(s["复核状态"] || "—")}</td>
          <td class="k">${esc(s["组"] || "—")}</td>
          <td>${内格}</td>
          <td>${能改
            ? `<button data-save="${esc(s.id)}" data-rev="${esc(s["revision"])}"
                >保存</button>`
            : `<span class="k">要「改训练样本」</span>`}</td></tr>`;
      }).join("")
      + `</tbody></table>
        <div class="note">⚠️ <b>改一条已经被冻结版本引用过的样本是允许的</b> ——
          而且不会动那个版本,因为冻结<b>固化了内容</b>。
          如果冻结只存指针,这里每改一次都会<b>悄悄改掉历史上那一版评测用的题</b>,
          于是「同一批题、换个配置、分数变没变」这个问题就问不成了 ——
          <b>而那个变化不会报错,只会让两次的分数不可比而看起来可比</b>。
          ${能改 ? "" : `<br>你现在是 <b>${esc(我的角色 || "?")}</b>,
            改样本要「改训练样本」这条能力 —— <b>所以这里不摆表单</b>。`}</div>`;
    document.querySelectorAll("[data-save]").forEach((b) => {
      b.onclick = async () => {
        const sid = b.dataset.save;
        const 补 = {};
        const g = (名) => document.querySelector(
          `[data-sp="${名}"][data-sid="${sid}"]`);
        if (g("split")) 补["分集"] = g("split").value;
        if (g("review")) 补["复核状态"] = g("review").value;
        b.disabled = true;
        if ($("#smsg")) $("#smsg").innerHTML = `<div class="state"><p>保存中…</p></div>`;
        try {
          // ⚠️ revision 从**这一行的 data-rev** 拿,不是从某个全局变量 ——
          // 一页上有好多条样本,各自的 revision 各自涨。
          const r = await 样本动作.改(dsid, sid, 补, Number(b.dataset.rev));
          if ($("#smsg")) {
            $("#smsg").innerHTML = `<div class="state"><p>改好了 ——
              revision ${esc(r["revision"])}${md(r.note ? "。" + r.note : "")}</p></div>`;
          }
          await 画样本(dsid);
        } catch (e) {
          if ($("#smsg")) $("#smsg").innerHTML = 错误块(e, null).html;
          b.disabled = false;
        }
      };
    });
  } catch (e) {
    const s = 错误块(e, () => 画样本(dsid));
    $("#slist").innerHTML = s.html; s.挂();
  }
}

async function 页_训练任务() {
  $("#main").innerHTML = `<div class="crumb">评测与训练 / 训练任务</div>
    <div class="head"><div><h1>训练任务</h1>
      <div class="sub"><b>训练目标和参数更新方式是两个维度</b> ——
        SFT/DPO 是目标,LoRA/全量是更新方式,不是三选一。</div></div></div>
    <div class="note warn">⚠️ <b>训练执行器还没接</b>(11-18 拍:模型训练先不做)—— 这一页<b>只看登记</b>,提交入口没摆。
      体检查实「提交训练」只往表里插一行、永远排队,后台没有任何东西会去跑它。</div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/training-jobs`);
    if (!d["任务"].length) {
      // 11-18 前这里教人「提交训练要 trainer 角色」—— 而提交了也只是插一行永远排队(没有执行器)。先把真相写上,别教人去提交
      $("#list").innerHTML = 状态("", "还没有训练任务",
        "**训练执行器还没接(11-18 拍:模型训练先不做)—— 这一页只看登记,提交入口没摆。** "
        + "等执行器接上再开提交:那时要 **trainer 角色**(或拿了专项授权的 admin),"
        + "而且**幂等键是硬要求**:超时重发一次 = 再烧一遍 GPU。").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>任务</th><th>状态</th>
      <th>基座</th><th>训练目标</th><th>参数更新方式</th><th>是 mock 跑的吗</th>
      </tr></thead><tbody>`
      + d["任务"].map((r) => `<tr>
        <td class="k">${esc(r.id)}</td>
        <td title="${esc(r.status)}">${esc(_英转中[r.status] || r.status)}${r["请求取消了吗"]
              ? ` <span class="pill warn">请求取消中</span>` : ""}</td>
        <td class="k">${esc(r["基座模型"] || "—")}</td>
        <td>${esc(r["训练目标"] || "—")}</td>
        <td>${esc(r["参数更新方式"] || "—")}</td>
        <td>${r["是mock跑的"] === true ? `<span class="pill warn">mock</span>`
              : r["是mock跑的"] === false ? `<span class="pill">真实</span>`
              : `<span class="pill warn">说不清</span>`}</td></tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        ⚠️ <b>「说不清」不是「不是」</b> —— 说不清的产物<b>不许部署</b>。</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* ── 模型产物:部署 ────────────────────────────────────────────────
 *
 * ⚠️ **三道闸要分开显示,而不是合成一个「不能部署」。**
 * 没标可用 / mock 训练的 / **说不清是不是 mock** —— 三种都拦,
 * 而它们在列表上长得几乎一样,下一步却完全不同:
 * 第一种去校验,第二种换真训练,第三种**先把来路查清**。
 * 「未知不是『不是』」这条就靠第三种撑着。
 *
 * ⚠️ **「标可用」这一步没有接口**(2026-10-01 查出来的):
 * `verified_at` 整个仓库只有 seed 写过。所以这一页**明说这件事**,
 * 而不是摆一个点了没用的「标可用」按钮 ——
 * **「点了没用」比「没有这个按钮」更费时间。**
 */
const 产物动作 = {
  async 部署(aid, 环境) {
    return await 请求(`${P()}/deployments`,
      { method: "POST", headers: { "Idempotency-Key": 新键() },
        body: JSON.stringify({ 产物: aid, 环境 }) });
  },
};
if (typeof globalThis !== "undefined") globalThis.产物动作 = 产物动作;

function 挂产物事件() {
  document.querySelectorAll("[data-dep]").forEach((b) => {
    b.onclick = async () => {
      const aid = b.dataset.dep;
      const sel = document.querySelector(`[data-env="${aid}"]`);
      // 11-08 UI 检查:部署原来点了就提交(环境下拉里可能是生产),应用详情那页同类操作是有确认的
      if (!(await 问一句("部署这个模型产物?", `部署到 <b>${esc(sel ? sel.value : "")}</b>。部署后这个环境里调它的地方会换成这一份。`, { 确定: "部署", 取消: "先不" }))) return;
      b.disabled = true;
      if ($("#amsg")) $("#amsg").innerHTML = `<div class="state"><p>部署中…</p></div>`;
      try {
        const r = await 产物动作.部署(aid, sel ? sel.value : "");
        // 11-08 UI 检查:原来先写结果、再整页重画 —— 结果刚出来就被刷掉,点完看不到任何反馈。改成先重画、再写结果
        await 页_模型产物();
        if ($("#amsg")) {
          $("#amsg").innerHTML = `<div class="state"><p>部署提交了${r && (r.note || r["说明"]) ? ":" + md(r.note || r["说明"]) : "。"}</p></div>`;
        }
      } catch (e) {
        if ($("#amsg")) $("#amsg").innerHTML = 错误块(e, null).html;
        b.disabled = false;
      }
    };
  });
}

async function 页_模型产物() {
  $("#main").innerHTML = `<div class="crumb">评测与训练 / 模型产物</div>
    <div class="head"><div><h1>模型产物</h1>
      <div class="sub"><b>训练完成只代表得到产物</b> ——
        有产物 → 产物可用(校验过) → 在服务用户,是三件不同的事。</div></div></div>
    <div class="note warn">⚠️ <b>部署还没接执行侧</b>(11-18 拍:模型训练先不做)—— 「部署」按钮标灰了:
      体检查实它只往表里插一行,没有任何查询接口,点了只会永远「部署请求中」。登记和三道闸照旧显示。</div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/model-artifacts`);
    if (!d["产物"].length) {
      $("#list").innerHTML = 状态("", "还没有登记产物",
        "登记产物时 `usable` **一律从 false 起**,而且那个接口**不收这个参数** —— "
        + "收了就等于让调用方自己说「我校验过了」。").html;
      return;
    }
    // ⚠️ 环境白名单**从接口来**(`training.部署环境` 现读),不在这儿硬编。
    const 环境们 = d["可选部署环境"] || [];
    const 能部署 = 我的角色 === "approver" || 我的角色 === "admin";
    $("#list").innerHTML = `<table><thead><tr><th>产物</th><th>种类</th>
      <th>基座</th><th>标了可用吗</th><th>是 mock 训练的吗</th>
      <th>标可用还差什么</th><th>部署还差什么（<b>两栏别混</b>）</th><th>部署</th>
      </tr></thead><tbody>`
      + d["产物"].map((r) => `<tr>
        <td class="k">${esc(r.id)}</td><td>${esc(r["种类"])}</td>
        <td class="k">${esc(r["基座模型"] || "—")}</td>
        <td>${r["标了可用吗"] ? `<span class="pill">可用</span>`
              : `<span class="pill warn">没标可用</span>`}</td>
        <td>${r["是mock训练的"] === true ? `<span class="pill warn">mock</span>`
              : r["是mock训练的"] === false ? `<span class="pill">真实</span>`
              : `<span class="pill warn">说不清</span>`}</td>
        <td class="k">${(r["标可用还差什么"] || []).length
            ? (r["标可用还差什么"] || []).map((x) =>
                `<div>· ${md(x.slice(0, 90))}</div>`).join("")
            : `<span class="pill ok">能标可用</span>`}</td>
        <td class="k">${(r["部署还差什么"] || []).length
            ? (r["部署还差什么"] || []).map((x) =>
                `<div>· ${md(x.slice(0, 90))}</div>`).join("")
            : `<span class="pill ok">三道闸都过了</span>`}</td>
        <td>${能部署 && r["能部署吗"]
            // 11-18 拍「模型训练先不做」:部署没接执行侧,按钮 disabled(挂产物事件 的 onclick 仍在,点不动;接上那天把 disabled 去掉就行)
            ? `<select data-env="${esc(r.id)}" disabled>${环境们.map((e) =>
                `<option>${esc(e)}</option>`).join("")}</select>
               <button data-dep="${esc(r.id)}" disabled title="部署还没接执行侧">部署</button>
               <div class="k">部署还没接执行侧,点了只会永远「部署请求中」(11-18 拍:模型训练先不做)</div>`
            : 能部署
              ? `<span class="k">闸没过,不摆按钮</span>`
              : `<span class="k">要「生产审核/发布/回滚」</span>`}</td>
        </tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        ⚠️ 部署三道闸:<b>没标可用</b> / <b>mock 训练的</b> /
        <b>说不清是不是 mock</b> —— 三种都拦,而它们在这张表上长得几乎一样,
        <b>下一步却完全不同</b>:第一种去校验,第二种换真训练,
        第三种<b>先把来路查清</b>。所以上面那一栏<b>逐条列出来</b>,不合成一句。
        ${d["⚠️两栏别混"] ? `<br><br>${md(d["⚠️两栏别混"])}` : ""}
        ${d["⚠️标可用这一步还没有接口"]
          ? `<br><br>${md(d["⚠️标可用这一步还没有接口"])}`
          : ""}</div>`
      + `<div id="amsg"></div>`;
    挂产物事件();
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* ── 聊天助手(10-28,用户拍「分两步」)───────────────────────────────────────────────
 * 第 1 步后台这一半:看 / 改 / 出版本 / 上生产;第 2 步聊天站读生产那一版(只有接口说「接上了吗」的角色)。
 * 接没接每一屏顶上都写明(接上了 = 上生产就改线上;没接 = 改了线上不变)——
 * 否则「这里显示的」会被当成「聊天站在跑的」,或反过来。和 Agent 一样页签是页内状态(没存的改动挂在 聊态 上) */
let 聊态 = null;
function 卡_聊天助手(r) {
  const 链 = `#/chat/${encodeURIComponent(r.id)}`;
  return `<div class="appcard" data-kind="chat" data-id="${esc(r.id)}">
    <div class="ah"><span class="ico ch">聊</span><div class="an"><a href="${链}"><b>${esc(r["名称"])}</b></a>
      <div class="k">聊天助手 · 角色 ${esc(r["角色键"])}</div></div>${r["接上了吗"] ? '<span class="pill">聊天站读它</span>' : '<span class="pill warn">还没接到聊天站</span>'}</div>
    <div class="ad">${esc(r["用途"] || "还没写用途")}</div>
    <div class="k">最新版本:${r["最新版本"] ? esc(r["最新版本"]) : "还没有"} · ${r["工具数"]} 个工具开着</div>
    <div class="k">生产:${r["生产版本"] ? `<b>${esc(r["生产版本"])}</b>` : "还没指定"}
      ${r["接上了吗"] ? (r["生产版本"] ? "" : '<span class="stale">没指定生产,聊天用代码里那一份</span>')
                      : '<span class="stale">聊天现在用的仍是代码里那一份</span>'}</div>
    <div class="af"><span class="grow"></span><a href="${链}">配置</a></div>
  </div>`;
}

async function 页_聊天助手(cid) {
  const d = await 请求(`${P()}/chat-assistants/${encodeURIComponent(cid)}`);
  聊态 = { cid, ...d, 改: JSON.parse(JSON.stringify(d["草稿"]["配置"])), 脏: false,
           Tab: (聊态 && 聊态.cid === cid && 聊态.Tab) || "编排" };
  画_聊天助手();
}

// 「上了生产」和「聊天站用上了」并排(用户 11-11「按你的顺序做」第 ② 步):术语 / 实体识别 / 路由 / 意图
// 一个进程只同步一次,不重启聊天站就还是旧的 —— 后台页面原来只看得到「上了生产」那一半。**拿不到 / 没加载 ≠ 一致**。
async function 画_生效状态(角色) {
  const 框 = $("#c-adopt"); if (!框) return;
  let d;
  try { d = await 请求(`${P()}/chat-assistants/by-role/${encodeURIComponent(角色)}/adoption`); }
  catch (e) { 框.className = "err"; 框.textContent = "生效状态取不到:" + (e.message || e) + " —— 这是没问到,不是一致"; return; }
  const 色 = { "一致": "ok", "不一致": "bad", "聊天站还没加载": "warn", "拿不到实际": "warn" };
  框.className = d["都一致吗"] ? "note" : "err";
  框.innerHTML = `<b>生效状态</b>(目标 = 生产指着的 v${esc(String(d["目标版本"] ?? "—"))};实际 = 聊天站进程里加载的${d["聊天站进程启动于"] ? ",聊天站启动于 " + esc(d["聊天站进程启动于"]) : ""})
    <table><tr><th>项</th><th>目标</th><th>实际</th><th>状态</th></tr>${(d["行"] || []).map((r) =>
      `<tr><td>${esc(r["项"])}</td><td><code>${esc(r["目标"] || "没挂")}</code></td><td><code>${esc(r["实际"] || "—")}</code></td>
       <td><span class="pill ${色[r["状态"]] || "warn"}">${esc(r["状态"])}</span>${r["说明"] ? ` <small>${esc(r["说明"])}</small>` : ""}</td></tr>`).join("")}</table>`;
}

function 画_聊天助手() {
  const g = 聊态;
  $("#side").innerHTML = `<a class="back" href="#/studio/chat">← 工作室</a>
    <div class="apphead"><span class="ico ch">聊</span><div class="an"><b>${esc(g["名称"])}</b><div class="k">聊天助手</div></div></div>
    ${["编排", "版本", "访问 API"].map((t) => `<a href="#" data-ctab="${t}"${g.Tab === t ? ' class="on"' : ""}>${t}</a>`).join("")}
    ${g["接上了吗"] ? "" : '<div class="grp">还没做</div><a class="todo" title="第 2 步:聊天站读后台这一版,并核对「后台这一版 == 模型真收到的」">接到聊天站</a>'}`;
  $("#side").querySelectorAll("[data-ctab]").forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); 聊态.Tab = a.dataset.ctab; 画_聊天助手(); };
  });
  const 同 = g["草稿"]["和哪一版一样"];
  $("#main").innerHTML = `<div class="head"><div><h1>${esc(g["名称"])}</h1>
      <div class="sub">角色 ${esc(g["角色键"])} · 草稿 r${g["草稿"]["revision"]} · ${同 ? `和 ${esc(同)} 一样` : "<b>有没出版本的改动</b>"}
        · 生产:${g["生产版本"] ? esc(g["生产版本"]) : "还没指定"}
        ${g.脏 ? ' <span class="stale">有未保存的改动</span>' : ""}</div></div>
      <div>${g.Tab === "编排" ? '<button id="c-save" class="pri">保存草稿</button>' : g.Tab === "版本" ? '<button id="c-ver" class="pri">出版本</button>' : ""}</div></div>
    ${g["接上了吗"] ? `<div class="note" id="c-wire" style="padding:10px;margin-bottom:12px">${md(g.note)}</div>`
                     : `<div class="err" id="c-wire" style="padding:10px;margin-bottom:12px">${md(g.note)}</div>`}
    ${g["接上了吗"] ? '<div class="note" id="c-adopt" style="padding:10px;margin-bottom:12px">生效状态:在问聊天站…</div>' : ""}
    <div id="body"></div>`;
  if (g["接上了吗"]) 画_生效状态(g["角色键"]);
  if (g.Tab === "编排") { 画_聊天编排(); $("#c-save").onclick = 做_存聊天助手; }
  else if (g.Tab === "访问 API") 画_聊天访问();
  else { 画_聊天版本(); $("#c-ver").onclick = 做_出聊天版本; }
}

/* 聊天助手的访问 API(11-03 第二步):外部系统带密钥问一轮;**这一轮写工具不挂**(只能查、不能改)。原文只弹一次 */
async function 画_聊天访问() {
  const g = 聊态, cid = encodeURIComponent(g.cid);
  $("#body").innerHTML = `<div class="card"><div class="k">在取…</div></div>`;
  let d;
  try { d = await 请求(`${P()}/chat-assistants/${cid}/access-keys`); }
  catch (e) {
    $("#body").innerHTML = `<div class="card"><div class="note"><b>取不到</b>:${esc(e.message || String(e))}
      —— 这是取数失败,不是「一把密钥都没有」。发密钥要「配置密钥与预算」权限(管理员)。</div></div>`;
    return;
  }
  const 行 = (d["密钥"] || []).map((k) => `<tr><td>${esc(k["名字"])}</td><td><code>${esc(k["开头"])}</code></td>
      <td>${esc(k["发的人"] || "")}</td><td>${k["今天花了"] == null ? "—" : esc(k["今天花了"].toFixed(4))} / ${esc(String(k["每天上限"]))} ${esc(k["币种"])}</td>
      <td>${到期格(k)}</td>
      <td>${k["吊销于"] ? "已吊销" : k["过期了吗"] ? "已过期 —— 重发一把" : `<button data-ak-rotate="${esc(k.id)}" data-rev="${esc(String(k.revision))}">轮换</button>
        <button data-ak-revoke="${esc(k.id)}">吊销</button>`}</td></tr>`).join("");
  $("#body").innerHTML = `<div class="card"><h4>外部系统怎么调</h4>
      <div class="k">跑的是这个助手<b>生产指着的那一版</b>${d["生产版本号"] != null ? `(v${esc(String(d["生产版本号"]))})` : " —— <b>还没上生产,调用会被拒</b>"}${d["聊天站读后台配置吗"] ? "" : ";<b>这个角色聊天站还没读后台配置,调用会被拒</b>"}。
        以发密钥那个人绑的澜绣工号取数;<b>这一轮写入类工具不挂</b> —— 只能查、不能改,要改的事回答里会说「它想做什么」。会话归这把密钥。</div>
      <pre>POST ${esc(location.origin + d["调用地址"])}
请求头:Authorization: Bearer lx-app-……
请求体:{"问题": "……", "会话": null}   ← 续着问就带上回答里的「会话」
→ {"回答": "……", "会话": "……", "用了哪一版": "后台 vN"}</pre>
      <div class="k">限量:每把每分钟 30 次;每天花费到上限就拒(和工作流同一套)。</div></div>
    <div class="card"><h4>密钥</h4>
      ${行 ? `<table><tr><th>名字</th><th>开头</th><th>发的人</th><th>今天花了 / 每天上限</th><th>有效期至</th><th></th></tr>${行}</table>` : `<div class="k">还没有发过密钥。</div>`}
      <label class="f">名字(给谁用)</label><input id="cak-n" placeholder="比如:企业微信机器人">
      <label class="f">每天最多花多少(美元,必填)</label><input id="cak-cap" placeholder="比如 2">
      <label class="f">有效期(必选,最长 1 年)</label>${有效期下拉("cak-exp")}
      <button class="pri" id="cak-new">发密钥</button> <span id="cak-msg" class="k"></span>
      <div class="k">原文只在发出那一刻显示一次;发密钥的人要绑了澜绣工号,不然调用会被拒(聊天站不知道以谁的身份取数)。</div></div>`;
  $("#cak-new").onclick = 只跑一次(async () => {
    const 名 = $("#cak-n").value.trim(), 上限 = $("#cak-cap").value.trim();
    if (!名 || !上限) { $("#cak-msg").textContent = "名字和每天上限都要填"; return; }
    try {
      const r = await 请求(`${P()}/chat-assistants/${cid}/access-keys`, { method: "POST", body: JSON.stringify({ 名字: 名, 每天上限: Number(上限), 有效期天数: Number($("#cak-exp").value) }) });
      提示("密钥发好了 —— 现在就存好", `<div class="note"><b>这是唯一一次看得到原文</b>,关掉这个框就再也看不到了。</div><pre>${esc(r["原文"])}</pre>`);
      画_聊天访问();
    } catch (e) { 报错(e); }
  });
  挂轮换($("#body"), 画_聊天访问);
  $("#body").querySelectorAll("[data-ak-revoke]").forEach((b) => b.onclick = async () => {
    const 理由 = await 问一句("吊销这把密钥", "吊销立刻生效。", { 输入: "理由", 必填: true });
    if (!理由) return;
    try { await 请求(`${P()}/access-keys/${encodeURIComponent(b.dataset.akRevoke)}/revoke`, { method: "POST", body: JSON.stringify({ 理由 }) }); 画_聊天访问(); }
    catch (e) { 报错(e); }
  });
}

function 画_聊天编排() {
  const g = 聊态, c = g.改, 写 = (c["工具"] || []).filter((t) => t["写"]), 读 = (c["工具"] || []).filter((t) => !t["写"]);
  const 勾 = (t) => `<label class="k" style="display:inline-block;min-width:260px"><input type="checkbox" data-tool="${esc(t["名"])}"
      ${t["开"] ? "checked" : ""}> <code>${esc(t["名"].split("__").pop())}</code></label>`;
  const 规 = g["规矩"];
  $("#body").innerHTML = `<div class="card"><h4>开头提示词</h4>
      <textarea id="c-head" rows="8" style="width:100%">${esc(c["开头"] || "")}</textarea>
      <h4>结尾</h4><textarea id="c-foot" rows="2" style="width:100%">${esc(c["结尾"] || "")}</textarea>
      <div class="note">模型收到的是:开头 + 下面那几条规矩(按开着的工具挑)+ 结尾。</div>
      <div class="note" id="c-perm">⚠️ <b>能不能改数据,以下面的工具清单为准,不以这段话为准</b> —— 现在开着 ${写.filter((t) => t["开"]).length} 个写入类工具。
        提示词里写的「没有写权限」之类的话拦不住任何调用(10-28 查出店长助手开头写着「没有任何写权限」,而它挂着 26 个写入类工具)。</div></div>
    <div class="card"><h4>模型</h4><select id="c-model">${(g["草稿"]["可选模型"] || []).map((m) =>
        `<option value="${esc(m)}"${m === c["模型"] ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>
      <div class="note">清单从聊天站带过来(有单价的才在里面)。聊天页上的人仍能临时换,这里定的是这个助手的默认。</div></div>
    <div class="card"><h4>术语</h4><select id="c-glossary"><option value="">不带术语</option>${(g["可选术语"] || []).map((v) =>
        `<option value="${esc(v.id)}"${v.id === c["术语版本"] ? " selected" : ""}>${esc(v["名称"])} · ${esc(v["版本"])} · ${esc(v["条数"])} 条</option>`).join("")}
        ${c["术语版本"] && !(g["可选术语"] || []).some((v) => v.id === c["术语版本"]) ? `<option value="${esc(c["术语版本"])}" selected>(当前选的不在列表里)</option>` : ""}</select>
      <div class="note">每一轮只把顾客这句话里提到的那几条术语交给模型。只列<b>冻结了的</b>版本(草稿会变);换术语 = 出一版新的聊天助手、上生产才生效。
        ${(g["可选术语"] || []).length ? "" : "这个项目还没有冻结的术语版本 —— 先去「术语配置」冻一版。"}</div></div>
    <div class="card"><h4>实体识别</h4><select id="c-entity"><option value="">不做实体识别(只按术语找)</option>${(g["可选实体识别"] || []).map((v) =>
        `<option value="${esc(v.id)}"${v.id === c["实体识别版本"] ? " selected" : ""}>${esc(v["名称"])} · ${esc(v["版本"])} · ${esc(v["本数"])} 本词典</option>`).join("")}
        ${c["实体识别版本"] && !(g["可选实体识别"] || []).some((v) => v.id === c["实体识别版本"]) ? `<option value="${esc(c["实体识别版本"])}" selected>(当前选的不在列表里)</option>` : ""}</select>
      <div class="note">每一轮先把这句话里的客户名、员工名、着装人名认出来占位,剩下的字才去找术语 —— 免得「宋锦书」被当成面料。换实体识别版本 = 出一版新的聊天助手、上生产才生效。
        ${(g["可选实体识别"] || []).length ? "" : "这个项目还没有冻结的实体识别版本 —— 先去「实体识别」冻一版。"}</div></div>
    <div class="card"><h4>意图识别</h4><select id="c-intent"><option value="">不做意图分类</option>${c["意图版本"] && !(g["可选意图"] || []).some((v) => v.id === c["意图版本"]) ? `<option value="${esc(c["意图版本"])}" selected>(当前选的不在列表里)</option>` : ""}${(g["可选意图"] || []).map((v) => `<option value="${esc(v.id)}"${v.id === c["意图版本"] ? " selected" : ""}>${esc(v["名称"])} · ${esc(v["版本"])} · ${esc(v["本数"])} 个意图</option>`).join("")}</select>
      <div class="note">每轮先判一次店长想干什么(多一次最便宜档的模型调用)。换版本 = 出一版新的聊天助手、上生产才生效。</div></div>
    <div class="card"><h4>查询路由</h4><select id="c-route"><option value="">全走默认路由</option>${(g["可选路由"] || []).map((v) =>
        `<option value="${esc(v.id)}"${v.id === c["路由版本"] ? " selected" : ""}>${esc(v["名称"])} · ${esc(v["版本"])} · ${esc(v["本数"])} 条规则</option>`).join("")}
        ${c["路由版本"] && !(g["可选路由"] || []).some((v) => v.id === c["路由版本"]) ? `<option value="${esc(c["路由版本"])}" selected>(当前选的不在列表里)</option>` : ""}</select>
      <div class="note">认出来的实体、判出的意图各自去哪(带定义 / 只占位 / 提示 / 先调工具 / 交给技能)。不选 = 全走默认:术语带定义、人名只占位、拿不准提示一句。
        路由里点名的工具和技能必须是这个助手开着的,否则保存时会拦。${(g["可选路由"] || []).length ? "" : "这个项目还没有冻结的路由版本 —— 先去「查询路由」冻一版。"}</div></div>
    <div class="card" id="c-tools"><h4>工具(${(c["工具"] || []).filter((t) => t["开"]).length} / ${(c["工具"] || []).length} 开着)</h4>
      <div><b>写入类 ${写.length} 个</b> <span class="pill warn">会改业务数据</span></div><div>${写.map(勾).join("")}</div>
      <div style="margin-top:8px"><b>只读 ${读.length} 个</b></div><div>${读.map(勾).join("")}</div>
      <div class="note">只能在聊天站这个角色挂的工具里开关 —— 后台加不出别的。关掉一个工具,跟着它的规矩也不再带上(保存后重新推算)。</div></div>
    <div class="card" id="c-rules"><h4>随工具带上的规矩(${规["装上"].length} 条,只读)</h4>
      <div class="note">${md(规["说明"])}</div>
      <div class="note">⚠️ <b>这一页管的是开头 / 结尾 / 工具 / 模型,规矩那一半不在这一页里</b> ——
        规矩按开着的工具自动挑,正文在「Prompt 管理」里(从代码导入)。改了开头不等于改了整份提示词。</div>
      ${规["后台没有的"].length ? `<div class="err">这几条后台还没导进来:${esc(规["后台没有的"].join("、"))}</div>` : ""}
      <table class="swlog"><tr><th>编号</th><th>类</th><th>跟着哪些工具</th><th>正文</th></tr>
      ${规["装上"].map((r) => `<tr><td>${esc(r["编号"])}</td><td>${esc(r["范围"] || "")}</td>
        <td class="k">${esc((r["跟着哪些工具"] || []).join("、") || "(总带着)")}</td>
        <td><details><summary>${esc(r["正文"].slice(0, 40))}…</summary><div class="k">${esc(r["正文"])}</div></details></td></tr>`).join("")}</table></div>
    <div class="card"><h4>技能</h4><div class="k">当时放行的 ${(g["技能"]["当时放行的"] || []).length} 个:
      ${esc((g["技能"]["当时放行的"] || []).join("、"))}</div><div class="note">${md(g["技能"]["说明"])}</div></div>`;
  const 标脏 = () => { if (!聊态.脏) { 聊态.脏 = true; const s = $(".head .sub"); if (s) s.insertAdjacentHTML("beforeend", ' <span class="stale">有未保存的改动</span>'); } };
  $("#c-head").oninput = (e) => { c["开头"] = e.target.value; 标脏(); };
  $("#c-foot").oninput = (e) => { c["结尾"] = e.target.value; 标脏(); };
  $("#c-model").onchange = (e) => { c["模型"] = e.target.value; 标脏(); };
  $("#c-glossary").onchange = (e) => { c["术语版本"] = e.target.value || null; 标脏(); };
  $("#c-entity").onchange = (e) => { c["实体识别版本"] = e.target.value || null; 标脏(); };
  $("#c-intent").onchange = (e) => { c["意图版本"] = e.target.value || null; 标脏(); };
  $("#c-route").onchange = (e) => { c["路由版本"] = e.target.value || null; 标脏(); };
  $("#c-tools").querySelectorAll("[data-tool]").forEach((b) => {
    b.onchange = () => { c["工具"].find((t) => t["名"] === b.dataset.tool)["开"] = b.checked; 标脏(); };
  });
}

function 画_聊天版本() {
  const g = 聊态;
  $("#body").innerHTML = `<div class="card"><table class="swlog" id="c-vers">
    <tr><th>版本</th><th>来源</th><th>模型</th><th>工具</th><th>规矩</th><th>变更说明</th><th>出版本</th><th>生产</th></tr>
    ${g["版本们"].map((v) => `<tr data-v="${esc(v["版本"])}"><td><b>${esc(v["版本"])}</b> <span class="k">${esc(v["内容哈希"])}</span></td>
      <td>${esc(v["来源"])}</td><td class="k">${esc(v["模型"])}</td><td>${v["工具数"]}</td><td>${v["规矩数"]}</td>
      <td>${esc(v["变更说明"] || "")}</td><td class="k">${时间(v["冻结于"])} ${esc(v["冻结人"] || "")}</td>
      <td>${v["生产"] ? '<span class="pill ok">生产</span>' : `<button class="mini" data-prod="${esc(v["版本"].slice(1))}">上生产</button>`}</td></tr>`).join("")}
    </table><div class="note">「代码导入」= 从聊天站代码里算出来的那一份(导入那一刻和在跑的一样);「后台编辑」= 在这里改了出的版本。
      上生产要「生产审核」权限,工作台「开关」那块记着谁什么时候把哪一版换成了哪一版。</div></div>`;
  $("#c-vers").querySelectorAll("[data-prod]").forEach((b) => { b.onclick = () => 做_聊天上生产(+b.dataset.prod); });
}

async function 做_存聊天助手() {
  const g = 聊态;
  try {
    await 请求(`${P()}/chat-assistants/${encodeURIComponent(g.cid)}/draft`, { method: "PATCH",
      headers: { "If-Match": String(g["草稿"]["revision"]) }, body: JSON.stringify({ 配置: g.改 }) });
    await 页_聊天助手(g.cid);
  } catch (e) {
    if (e.码 === 409) { const 我的 = JSON.stringify(g.改, null, 2);   // 11-08 用户拍:重载前把没保存的内容留给人复制
      await 页_聊天助手(g.cid); 提示("别人刚改过", `${md(e.message)}<br>下一步:${md(e.体?.advice || "看一眼最新内容再改")}
        <details><summary>我这边没保存的内容(已经被最新版本盖掉,先复制下来再合并)</summary><pre class="io">${esc(我的)}</pre></details>`); return; }
    报错(e);
  }
}

function 做_出聊天版本() {
  弹层("出版本", `<label class="f">变更说明(这一版改了什么、为什么)</label><input id="cv-n">
    <div class="note">出版本<b>不等于上生产</b> —— 线上只认生产指着的那一版。</div>
    <div class="acts"><button class="pri" id="cv-ok">出版本</button> <button id="cv-no">取消</button></div>`);
  $("#cv-no").onclick = 关弹层;
  $("#cv-ok").onclick = async () => {
    try {
      await 请求(`${P()}/chat-assistants/${encodeURIComponent(聊态.cid)}/versions`, { method: "POST",
        body: JSON.stringify({ 变更说明: $("#cv-n").value.trim() }) });
      关弹层(); await 页_聊天助手(聊态.cid);
    } catch (e) { 报错(e); }
  };
}

function 做_聊天上生产(号) {
  弹层(`把生产换成 v${号}`, `<label class="f">理由(进审计)</label><input id="cp-r">
    <div class="note">${md(聊态.note)}</div>
    <div class="acts"><button class="pri" id="cp-ok">上生产</button> <button id="cp-no">取消</button></div>`);
  $("#cp-no").onclick = 关弹层;
  $("#cp-ok").onclick = async () => {
    try {
      await 请求(`${P()}/chat-assistants/${encodeURIComponent(聊态.cid)}/production`, { method: "POST",
        body: JSON.stringify({ 版本号: 号, 理由: $("#cp-r").value.trim() || null }) });
      关弹层(); await 页_聊天助手(聊态.cid);
    } catch (e) { 报错(e); }
  };
}

/* ── 澜绣旋钮与方案(11-18 体检:后端 lanxiu_api.py 五条接口全可用、前端零引用)────
 *
 * ⚠️ **这 6 个旋钮管的是澜绣 V3 怎么跑,不是后台自己的 Agent 配置**(接口 note 原话,页面上也明写)。
 * ⚠️ **落点核对不过的旋钮要标「不可信」**:接口说明原话 —— 拖动它什么都不会变,而人会以为自己在调。
 *   所以不过的那几行整行标 pill fail,不照常显示成可调。
 * ⚠️ **方案是单向同步到文件的**:库是编辑面,V3 真读 .feynman/prompt_candidates/{号}.json。
 *   建 / 改完**都没生效**,要跑 tools/export_knob_plans.py —— 接口返回的 note 原样显示出来,导出状态单独一栏。
 * 写操作要的后端能力是「改筛选策略」(perms.py:editor / admin 是,approver 可授权)—— 不够的身份不摆表单,写一句为什么。
 * 改草稿带 If-Match=draft_revision;409 提示刷新再改。422 的 field_errors 逐字段显示(这个后台的惯例)。 */
const 旋钮动作 = {
  async 建(体) {
    return await 请求(`${P()}/knob-plans`, { method: "POST", body: JSON.stringify(体) });
  },
  async 改(号, 版, 体) {
    return await 请求(`${P()}/knob-plans/${encodeURIComponent(号)}/draft`,
      { method: "PATCH", headers: { "If-Match": String(版) }, body: JSON.stringify(体) });
  },
};
if (typeof globalThis !== "undefined") globalThis.旋钮动作 = 旋钮动作;

function 旋钮_能改() {
  return 我的角色 === "editor" || 我的角色 === "admin" || (能力 || []).includes("改筛选策略");
}

/* 一个旋钮一个输入框:枚举 → select 列 取值;开关 → checkbox;整数 → number 带上下限;字符串 / 工具子集 → 文本。
 * 「不动」= 留空(枚举多一项「按默认」)—— 后端 校验() 本来就把等于默认的值丢掉,方案里只留真动过的。 */
function 旋钮_输入(k, 值) {
  const id = `kn-v-${k["名"]}`, 有 = 值 !== undefined && 值 !== null;
  if (k["类型"] === "枚举") {
    return `<select id="${esc(id)}" data-kn="${esc(k["名"])}"><option value="">按默认（${esc(k["默认"])}）</option>${
      (k["取值"] || []).map((v) => `<option value="${esc(v)}"${有 && String(值) === String(v) ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
  }
  if (k["类型"] === "开关") {
    const 勾 = 有 ? !!值 : !!k["默认"];
    return `<label><input type="checkbox" id="${esc(id)}" data-kn="${esc(k["名"])}"${勾 ? " checked" : ""}> 开（默认 ${k["默认"] ? "开" : "关"}）</label>`;
  }
  if (k["类型"] === "整数") {
    const [lo, hi] = k["取值"] || [];
    return `<input type="number" id="${esc(id)}" data-kn="${esc(k["名"])}" min="${esc(lo)}" max="${esc(hi)}" step="1"
      value="${有 ? esc(值) : ""}" placeholder="默认 ${esc(k["默认"])},留空不动" style="width:120px">`;
  }
  if (k["类型"] === "工具子集") {
    return `<input id="${esc(id)}" data-kn="${esc(k["名"])}" value="${esc(Array.isArray(值) ? 值.join(", ") : (值 || ""))}"
      placeholder="逗号分开的工具名;留空=全挂。只许收窄" style="width:min(420px,90%)">`;
  }
  return `<input id="${esc(id)}" data-kn="${esc(k["名"])}" value="${esc(有 ? 值 : "")}"
    placeholder="${esc(k["默认"] == null ? "留空=按凭证走默认" : "默认 " + k["默认"])}" style="width:min(320px,90%)">`;
}

function 旋钮_读表单(旋钮表) {
  const 旋 = {};
  for (const k of 旋钮表) {
    const el = $(`#kn-v-${k["名"]}`);
    if (!el) continue;
    if (k["类型"] === "开关") { 旋[k["名"]] = !!el.checked; continue; }
    const v = String(el.value || "").trim();
    if (!v) continue;
    if (k["类型"] === "整数") 旋[k["名"]] = Number(v);
    else if (k["类型"] === "工具子集") 旋[k["名"]] = v.split(/[,，\s]+/).filter(Boolean);
    else 旋[k["名"]] = v;
  }
  return 旋;
}

function 页_旋钮表单(旋钮表, 预填) {
  if (!旋钮_能改()) {
    return `<div class="note">建 / 改方案要「改筛选策略」这条能力(编辑、管理员默认有,审核发布者要授权)——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>:
      摆一个填完被 403 的表单,只是把拒绝往后挪一步。</div>`;
  }
  const p = 预填 || {}, 旋 = p["旋钮"] || {}, 改 = !!p["方案号"];
  return `<div class="state">
    <h3>${改 ? `改方案「${esc(p["方案号"])}」的草稿` : "新建方案"}</h3>
    <p class="k">${改
      ? `带 If-Match=<code>${esc(p.draft_revision)}</code> 提交;别人先改了就会 409,刷新这一页再改。<b>改了之后导出状态会被清掉</b>(库和文件已经不一样了)`
      : "方案号就是文件名(<code>.feynman/prompt_candidates/{号}.json</code>),不许带 / \\ 或 ..;「为什么」是下一个人判断这个实验还要不要留着的唯一线索"}</p>
    <p><label>方案号<br><input id="kn-key" style="width:min(320px,90%)" value="${esc(p["方案号"] || "")}"${改 ? " readonly" : ""}></label>
      <div class="k err" id="kn-fe-方案号"></div></p>
    <p><label>为什么<br><textarea id="kn-why" rows="3" data-raw="原文" style="width:min(520px,95%)">${esc(p["为什么"] || "")}</textarea></label>
      <div class="k err" id="kn-fe-为什么"></div></p>
    <p><b>旋钮</b>(留空 / 按默认 = 不动;方案里只留真动过的)</p>
    ${旋钮表.map((k) => `<p><label>${esc(k["中文"])} <code>${esc(k["名"])}</code><br>${旋钮_输入(k, 旋[k["名"]])}</label></p>`).join("")}
    <div class="k err" id="kn-fe-旋钮"></div>
    <p><button class="pri" id="kn-go">${改 ? "保存草稿" : "建方案"}</button>
      ${改 ? `<button id="kn-cancel">取消</button>` : ""}</p>
    <div class="k">${md("提交成功**也还没生效** —— 方案是单向同步到文件的,要跑 `python3 tools/export_knob_plans.py` 才写进 V3 真读的那份文件")}</div>
  </div>`;
}

function 挂旋钮事件(d, 方案们) {
  const 说 = (文, 坏) => { if ($("#kn-msg")) $("#kn-msg").innerHTML = 文
    ? (坏 ? `<div class="state err"><p>${文}</p></div>` : `<div class="state"><p>${文}</p></div>`) : ""; };
  const 清字段错 = () => ["方案号", "为什么", "旋钮"].forEach((f) => { if ($(`#kn-fe-${f}`)) $(`#kn-fe-${f}`).innerHTML = ""; });
  // 422 的 field_errors 逐字段显示;对不上字段名的并进总提示里
  const 报错 = (e) => {
    const b = e.体 || {}, fe = b.field_errors || {}, 剩 = [];
    清字段错();
    for (const [f, v] of Object.entries(fe)) {
      const 文 = (Array.isArray(v) ? v : [v]).map((x) => esc(typeof x === "string" ? x : JSON.stringify(x))).join(";");
      if ($(`#kn-fe-${f}`) && ["方案号", "为什么", "旋钮"].includes(f)) $(`#kn-fe-${f}`).innerHTML = "⚠️ " + 文;
      else 剩.push(`${esc(f)}:${文}`);
    }
    const 冲突 = e.码 === 409 ? "<br><b>这份草稿已经被改过,或方案号已经有了 —— 刷新这一页再改</b>" : "";
    说(md(闸文(e)) + (剩.length ? "<br>" + 剩.join("<br>") : "") + 冲突, true);
  };
  document.querySelectorAll("[data-kn-edit]").forEach((b) => {
    b.onclick = () => {
      const 行 = 方案们.find((x) => x["方案号"] === b.dataset.knEdit);
      if ($("#kn-form")) $("#kn-form").innerHTML = 页_旋钮表单(d.items, 行);
      挂旋钮事件(d, 方案们);
      if ($("#kn-form") && $("#kn-form").scrollIntoView) $("#kn-form").scrollIntoView();
    };
  });
  if ($("#kn-cancel")) {
    $("#kn-cancel").onclick = () => {
      if ($("#kn-form")) $("#kn-form").innerHTML = 页_旋钮表单(d.items, null);
      挂旋钮事件(d, 方案们);
    };
  }
  if (!$("#kn-go")) return;
  $("#kn-go").onclick = async () => {
    const 号 = String(($("#kn-key") && $("#kn-key").value) || "").trim();
    const 为什么 = String(($("#kn-why") && $("#kn-why").value) || "").trim();
    const 旋 = 旋钮_读表单(d.items);
    const 原 = 方案们.find((x) => x["方案号"] === 号);
    const 改 = !!($("#kn-cancel")) && !!原;   // 有「取消」按钮 = 开的是改表单
    $("#kn-go").disabled = true; 清字段错(); 说("提交中…");
    try {
      let r;
      if (改) r = await 旋钮动作.改(号, 原.draft_revision, { 旋钮: 旋, 为什么 });
      else r = await 旋钮动作.建({ 方案号: 号, 为什么, 旋钮: 旋 });
      // 先重画、再写结果(11-08 UI 检查的教训:反过来结果刚出来就被刷掉)
      await 页_旋钮与方案();
      说(`${改 ? "草稿保存了" : "建好了"} <b>${esc(号)}</b>${r && r["校验说明"] && r["校验说明"].length
        ? "<br>" + r["校验说明"].map((x) => "· " + md(x)).join("<br>") : ""}<br>${md(r && r.note || "")}`);
    } catch (e) { 报错(e); $("#kn-go").disabled = false; }
  };
}

async function 页_旋钮与方案() {
  $("#main").innerHTML = `<div class="crumb">设置 / 澜绣旋钮与方案</div>
    <div class="head"><div><h1>澜绣旋钮与方案</h1>
      <div class="sub">${md(`这 6 个旋钮管的是**澜绣 V3**(\`agentsite/sdk.py\`)怎么跑,**不是后台自己的 Agent 配置**(那在「工作室」里)。
        方案是**单向**同步到文件的:这里是编辑面,V3 真读的是方案文件 —— **建 / 改完都没生效,导出之后才算**。`)}</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/lanxiu-knobs`);
    const 核 = d["落点核对"] || {}, 问题 = 核["问题"] || [];
    // 落点核对的问题是按旋钮名报的:问题文本里出现了哪个旋钮名,那一行就是不可信
    // knobs.落点核对() 的每条问题以「旋钮名:」开头;按前缀认,别按包含认(model 会被 model_name 那条顺手命中)
    const 问题文 = (q) => String(typeof q === "string" ? q : JSON.stringify(q));
    const 这条的问题 = (k) => 问题.filter((q) => 问题文(q).startsWith(k["名"] + ":") || 问题文(q).startsWith(k["名"] + "："));
    const 不可信 = (k) => 核["过了吗"] === false && 这条的问题(k).length > 0;
    const 取值文 = (k) => k["取值"] == null ? "—" : Array.isArray(k["取值"])
      ? (k["类型"] === "整数" ? `${k["取值"][0]} – ${k["取值"][1]}` : k["取值"].map(String).join(" / ")) : String(k["取值"]);
    const 值文 = (v) => v == null ? "（空 = 按默认）" : Array.isArray(v) ? v.join(", ") : String(v);
    let 旋钮表html = `<h2>${(d.items || []).length} 个旋钮</h2>
      <div class="note">${md(d.note || "")}<br><br>${md(d["⚠️落点核对是什么"] || "")}<br><br>${md(d["⚠️定义是现读的"] || "")}</div>
      ${核["过了吗"] === false ? `<div class="note warn"><b>落点核对没过</b>(${问题.length} 条)—— 下面标「不可信」的那几行,调了不会有任何变化:<br>${
        问题.map((q) => "· " + esc(问题文(q))).join("<br>")}</div>`
        : `<div class="k">落点核对:过了 —— 每个旋钮声明的落点在那个文件里都搜得到</div>`}
      <table><thead><tr><th>中文</th><th>名</th><th>类型</th><th>取值</th><th>默认</th><th>落点</th><th>说明</th></tr></thead><tbody>
      ${(d.items || []).map((k) => { const 坏 = 不可信(k); return (坏 ? `<tr class="fail">` : `<tr>`) + `
        <td><b>${esc(k["中文"])}</b>${坏 ? ` <span class="pill fail">不可信</span>` : ""}${k["松"] ? ` <span class="pill warn" title="关掉它跑出来的分数是消融实验,不是这一版的成绩">松</span>` : ""}</td>
        <td><code>${esc(k["名"])}</code></td><td class="k">${esc(k["类型"])}</td>
        <td class="k">${esc(取值文(k))}</td><td>${esc(值文(k["默认"]))}</td>
        <td class="k"><code>${esc(k["落点"])}</code>${坏 ? `<div class="k">⚠️ ${这条的问题(k).map((q) => esc(问题文(q))).join(";")}</div>` : ""}</td>
        <td class="k">${md(k["说明"] || "")}</td></tr>`; }).join("")}
      </tbody></table>`;
    let 方案们 = [], 方案note = "", 方案块;
    try {
      const pd = await 请求(`${P()}/knob-plans`);
      方案们 = pd.items || []; 方案note = pd.note || "";
      const 导出文 = (p) => {
        if (!p["导出过吗"]) return `<span class="pill warn">还没导出,聊天站还没在用</span>`;
        if (!p["方案文件在吗"]) return `<span class="pill fail">导出过,文件不见了</span>`;
        if (p["文件还是导出那一份吗"] === false) return `<span class="pill fail">文件被手改过</span>`;
        return `<span class="pill ok">已导出</span><div class="k">${时间(p["导出时间"])}</div>`;
      };
      方案块 = 方案们.length
        ? `<table><thead><tr><th>方案号</th><th>为什么</th><th>负责人</th><th>状态</th><th>旋钮</th><th>导出状态</th><th>改</th></tr></thead><tbody>
          ${方案们.map((p) => `<tr data-plan="${esc(p["方案号"])}">
            <td><b>${esc(p["方案号"])}</b><div class="k">${esc(p.id)} · 草稿版 ${esc(p.draft_revision)}</div></td>
            <td class="k">${md(p["为什么"] || "—")}</td>
            <td class="k">${esc(p["负责人"] || "—")}</td><td class="k">${esc(p["状态"] || "—")}</td>
            <td class="k">${Object.keys(p["旋钮"] || {}).length
              ? Object.entries(p["旋钮"]).map(([k, v]) => `<code>${esc(k)}</code>=${esc(值文(v))}`).join("<br>")
              : "（一个都没动 = 全按默认）"}</td>
            <td>${导出文(p)}${p["⚠️文件被改过"] ? `<div class="k">${md(p["⚠️文件被改过"])}</div>` : ""}${p["⚠️文件不见了"] ? `<div class="k">${md(p["⚠️文件不见了"])}</div>` : ""}</td>
            <td>${旋钮_能改() ? `<button data-kn-edit="${esc(p["方案号"])}">改</button>` : `<span class="k">要「改筛选策略」</span>`}</td></tr>`).join("")}
          </tbody></table>`
        : 状态("", "这个项目还没有方案",
            "方案 = 一组旋钮取值 + 为什么。**连基线都没有就没法说「改了之后好了多少」** —— 先建一个「基线-默认」(什么都不动),再建要对比的那个。").html;
    } catch (e) {
      // 方案读不到不挡旋钮表;这一半单独显示错误块
      方案块 = 错误块(e, 路由).html;
    }
    $("#list").innerHTML = 旋钮表html
      + `<h2>方案（${方案们.length} 个）</h2>
        <div class="note">${md(方案note || "方案是**单向**同步到文件的:库是编辑面,V3 真读的是方案文件。改完要跑 `python3 tools/export_knob_plans.py` 才生效")}<br>
          <b>「还没导出」= 聊天站还没在用这个方案</b>;「已导出」也只说明文件是那一刻写的 —— 文件被手改过会单独标出来。</div>`
      + 方案块
      + `<div id="kn-msg"></div><div id="kn-form"></div>`;
    if ($("#kn-form")) $("#kn-form").innerHTML = 页_旋钮表单(d.items || [], null);
    挂旋钮事件(d, 方案们);
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

/* ── 工具选择策略(11-18)────────────────────────────────────────────────
 * 后端 selection_api.py 那套接口(列表 / 详情 / 建 / 改草稿 / 校验 / 冻结)此前**前端一处都没引**。
 * 真项目里有 1 条草稿「只开路由器」,而每个响应都带着「⚠️还没生效:这条策略还没有任何东西在消费它」——
 * **这句话原样显示在每一页最顶上**。规格 §16 第四阶段的检索实现没做,策略配得出来、冻得进去,
 * 而 agent_loop 不读它;少了这句,「配了」和「生效了」在页面上长得一模一样。
 * 权限:看要「查看有权配置」(谁都能看);建 / 改草稿 / 校验 / 冻结都要「改筛选策略」(编辑、管理员默认有,审核发布者要授权)——
 * 和旋钮方案是同一条能力,所以直接用 旋钮_能改()。
 * 头:改草稿带 If-Match=draft_revision(不带 409 IF_MATCH_REQUIRED,不对 409 REVISION_CONFLICT);
 * 这套接口**不要 Idempotency-Key**(建策略 / 冻结都没读它)。422 的 field_errors 逐字段摆(建策略是 名称 / 用途;冻结是 闸)。 */
const 选择策略动作 = {
  async 建(体) {
    return await 请求(`${P()}/tool-selection-policies`, { method: "POST", body: JSON.stringify(体) });
  },
  async 改草稿(pid, 版, 体) {
    return await 请求(`${P()}/tool-selection-policies/${encodeURIComponent(pid)}/draft`,
      { method: "PATCH", headers: { "If-Match": String(版) }, body: JSON.stringify(体) });
  },
  async 校验(pid, 配) {
    return await 请求(`${P()}/tool-selection-policies/${encodeURIComponent(pid)}/validate`,
      { method: "POST", body: JSON.stringify(配) });
  },
  async 冻结(pid, 配) {
    return await 请求(`${P()}/tool-selection-policies/${encodeURIComponent(pid)}/versions`,
      { method: "POST", body: JSON.stringify(配) });
  },
};
if (typeof globalThis !== "undefined") globalThis.选择策略动作 = 选择策略动作;

// 「还没生效」那条横幅:每个响应都带,**放在页面最顶上、表格之前**;后端哪天不带了就明说(别静默消失 —— 消失那天可能正是它开始生效的那天,也可能是字段改名了)
function 选择策略_生效横幅(d) {
  const 文 = d && d["⚠️还没生效"];
  return 文
    ? `<div class="note warn" id="sel-live"><b>⚠️ 还没生效</b> —— ${md(文)}</div>`
    : `<div class="note warn" id="sel-live"><b>⚠️ 接口这次没带「还没生效」这个字段</b> —— 要么策略已经开始被消费了,要么字段改了名。<b>别把这当成「生效了」</b>,去 selection_api.py 核一下</div>`;
}

// 422 的 field_errors 逐字段显示:对得上输入框的摆到字段下面(#sel-fe-<字段>),对不上的并进总提示;「闸」那组走 闸文()
function 选择策略_报错(e, 字段们, 说) {
  const b = e.体 || {}, fe = b.field_errors || {}, 剩 = [];
  字段们.forEach((f) => { if ($(`#sel-fe-${f}`)) $(`#sel-fe-${f}`).innerHTML = ""; });
  for (const [f, v] of Object.entries(fe)) {
    if (f === "闸") continue;   // 闸文() 已经逐条列出
    const 文 = (Array.isArray(v) ? v : [v]).map((x) => md(typeof x === "string" ? x : JSON.stringify(x))).join(";");
    if (字段们.includes(f) && $(`#sel-fe-${f}`)) $(`#sel-fe-${f}`).innerHTML = "⚠️ " + 文;
    else 剩.push(`${esc(f)}:${文}`);
  }
  const 冲突 = e.码 === 409 ? "<br><b>草稿已经被别人改过(或没带 If-Match)—— 刷新这一页,拿新的 draft_revision 再提交</b>" : "";
  说(md(闸文(e)).replace(/\n/g, "<br>") + (剩.length ? "<br>" + 剩.join("<br>") : "") + 冲突, true);
}

async function 页_工具选择策略() {
  $("#main").innerHTML = `<div class="crumb">集成 / 工具选择策略</div>
    <div class="head"><div><h1>工具选择策略</h1>
      <div class="sub">${md("策略指定 Agent **怎么从工具目录里挑工具**(固定组 / 关键词检索 / 预算 / 没结果怎么办),**不替谁授权** —— 规格 §3「筛选得分高不授予权限」。身份 / 授权 / 密钥 / 对象范围由服务端绑定,不进策略")}</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/tool-selection-policies`);
    const 项 = d.items || [];
    const 能改 = 旋钮_能改();
    const 表 = 项.length
      ? `<table><thead><tr><th>策略</th><th>用途</th><th>负责人</th><th>状态</th><th>版本数</th><th>草稿版</th><th></th></tr></thead><tbody>
        ${项.map((p) => `<tr data-policy="${esc(p.id)}">
          <td><a href="#/selection/${encodeURIComponent(p.id)}"><b>${esc(p["名称"] || p.id)}</b></a><div class="k">${esc(p.id)}</div></td>
          <td class="k" data-raw="原文">${esc(p["用途"] || "—")}</td>
          <td class="k">${esc(p["负责人"] || "—")}</td>
          <td>${p["状态"] === "active" ? `<span class="pill">active</span>` : `<span class="pill warn">${esc(p["状态"] || "?")}</span>`}
            <div class="k">「active」只是策略自己的状态字段 —— <b>不等于有东西在消费它</b>(见顶上)</div></td>
          <td class="k">${esc(p["版本数"] ?? 0)}${Number(p["版本数"] || 0) === 0 ? `<div class="k">没有版本的策略绑不上去</div>` : ""}</td>
          <td class="k">${esc(p.draft_revision ?? 0)}</td>
          <td><a href="#/selection/${encodeURIComponent(p.id)}">配置 / 版本 / 校验</a></td></tr>`).join("")}
        </tbody></table>`
      : 状态("", "这个项目还没有工具选择策略",
          "策略 = 一种挑工具的方式 + 预算 + 没结果 / 目录出错时怎么办。**首版只支持固定工具组和关键词检索**;建好之后要冻结出版本才绑得上去 —— 而就算冻结了,现在也还没有东西在消费它(见顶上那句)。").html;
    const 模式表 = (d["可选模式"] || []).length
      ? `<h2>可选模式</h2><table><thead><tr><th>值</th><th>中文</th><th>首版支持吗</th><th>说明</th></tr></thead><tbody>
        ${d["可选模式"].map((m) => `<tr><td><code>${esc(m["值"])}</code></td><td>${esc(m["中文"])}</td>
          <td>${m["首版支持吗"] ? `<span class="pill ok">首版支持</span>` : `<span class="pill warn">扩展,首版不支持</span>`}</td>
          <td class="k">${md(m["说明"] || "")}</td></tr>`).join("")}</tbody></table>` : "";
    const 动作表 = `<div class="note">${md(d["⚠️两个动作别混"] || "")}<br>
      <b>没结果怎么办</b>:${(d["可选的没结果怎么办"] || []).map((x) => `<code>${esc(x["值"])}</code> ${esc(x["中文"])}`).join(" · ")}<br>
      <b>目录出错怎么办</b>:${(d["可选的目录出错怎么办"] || []).map((x) => `<code>${esc(x["值"])}</code> ${esc(x["中文"])}`).join(" · ")}</div>`;
    const 建表单 = 能改
      ? `<div class="state" id="sel-new"><h3>新建策略</h3>
          <p class="k">只建一个空壳(名称 + 用途),配置在详情页里校验、冻结成版本。「用途」是下一个人判断它为什么长这样的唯一线索</p>
          <p><label>名称<br><input id="sel-name" style="width:min(320px,90%)"></label><div class="k err" id="sel-fe-名称"></div></p>
          <p><label>用途<br><textarea id="sel-purpose" rows="3" style="width:min(520px,95%)"></textarea></label><div class="k err" id="sel-fe-用途"></div></p>
          <p><button class="pri" id="sel-go">建策略</button></p>
          <div class="k">${md("建好**也还没生效** —— 没有版本的策略绑不上去;而且现在没有任何东西在消费这些策略")}</div></div>`
      : `<div class="note">建 / 改策略要「改筛选策略」这条能力(编辑、管理员默认有,审核发布者要授权)——
          你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>:摆一个填完被 403 的表单,只是把拒绝往后挪一步。</div>`;
    $("#list").innerHTML = 选择策略_生效横幅(d)
      + `<h2>${项.length} 条策略</h2><div class="note">${md(d.note || "")}</div>` + 表 + 模式表 + 动作表
      + `<div id="sel-msg"></div>` + 建表单;
    if (!$("#sel-go")) return;
    const 说 = (文, 坏) => { if ($("#sel-msg")) $("#sel-msg").innerHTML = 文
      ? (坏 ? `<div class="state err"><p>${文}</p></div>` : `<div class="state"><p>${文}</p></div>`) : ""; };
    $("#sel-go").onclick = async () => {
      const 名 = String(($("#sel-name") && $("#sel-name").value) || "").trim();
      const 用途 = String(($("#sel-purpose") && $("#sel-purpose").value) || "").trim();
      $("#sel-go").disabled = true; 说("提交中…");
      try {
        const r = await 选择策略动作.建({ 名称: 名, 用途 });
        await 页_工具选择策略();
        说(`建好了 <a href="#/selection/${encodeURIComponent(r.id)}"><b>${esc(r["名称"] || r.id)}</b></a>(${esc(r.id)})<br>${md(r.note || "")}<br>${md(r["⚠️还没生效"] || "")}`);
      } catch (e) { 选择策略_报错(e, ["名称", "用途"], 说); $("#sel-go").disabled = false; }
    };
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

// 一个版本一行里的「限额」:五个数,按后端的中文名显示
const 选择策略_限额名 = { initial_candidates: "初次候选数", new_definition_tokens: "单次新增定义额度",
  active_definition_tokens: "活动定义总额度", max_rediscovery: "最多补搜几次", selection_timeout_ms: "筛选超时(毫秒)" };

async function 页_工具选择策略详情(pid) {
  $("#main").innerHTML = `<div class="crumb"><a href="#/selection">集成 / 工具选择策略</a> / ${esc(pid)}</div>
    <div class="head"><div><h1 id="sel-t">${esc(pid)}</h1><div class="sub" id="sel-sub"></div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    // 详情接口不带词表(可选模式 / 两个动作),从列表接口拿;列表读不到不挡详情,表单退成文本框
    const [d, 表] = await Promise.all([
      请求(`${P()}/tool-selection-policies/${encodeURIComponent(pid)}`),
      请求(`${P()}/tool-selection-policies`).catch(() => ({})),
    ]);
    const 能改 = 旋钮_能改();
    const 草 = d["草稿"] || {}, 版本们 = d["版本历史"] || [], 最新 = 版本们[0] || null;
    $("#sel-t").textContent = d["名称"] || pid;
    $("#sel-sub").innerHTML = `${esc(pid)} · 状态 <b>${esc(d["状态"] || "?")}</b> · 草稿版 <code>${esc(d.draft_revision)}</code> · ${版本们.length} 个冻结版本 · ${md(d.note || "")}`;
    const 对 = (v) => v == null || v === "" ? `<span class="k">—</span>` : `<code>${esc(v)}</code>`;
    const 限额文 = (限) => 限 && typeof 限 === "object" && Object.keys(限).length
      ? Object.entries(限).map(([k, v]) => `<div>${esc(选择策略_限额名[k] || k)} <code>${esc(v)}</code></div>`).join("") : `<span class="k">—</span>`;
    const 版本表 = 版本们.length
      ? `<table><thead><tr><th>版本</th><th>模式</th><th>绑了什么</th><th>限额</th><th>没结果 / 目录出错</th><th>独立路由</th><th>候选缓存</th><th>变更说明</th><th>冻结</th></tr></thead><tbody>
        ${版本们.map((v) => `<tr data-version="${esc(v["版本"])}">
          <td><b>${esc(v["版本"])}</b><div class="k">哈希 ${esc(String(v["内容哈希"] || "").slice(0, 12))}</div></td>
          <td>${esc(v["模式中文"] || "?")}<div class="k"><code>${esc(v["模式"] || "")}</code> · ${esc(v["加载方式"] || "")}</div></td>
          <td class="k">目录快照 ${对(v["目录快照"])}<br>默认工具组版本 ${对(v["默认工具组版本"])}</td>
          <td class="k">${限额文(v["限额"])}</td>
          <td class="k">没结果:<code>${esc(v["没结果怎么办"] || "")}</code><br>目录出错:<code>${esc(v["目录出错怎么办"] || "")}</code></td>
          <td class="k">${v["开了独立路由吗"] ? `<span class="pill warn">开了</span><br>实验 ${对(v["路由实验"])}<br>模型连接 ${对(v["路由模型连接"])}` : `<span class="pill">关</span>`}</td>
          <td class="k">${v["开了候选缓存吗"] ? `<span class="pill warn">开了</span>` : `<span class="pill">关</span>`}</td>
          <td class="k" data-raw="原文">${esc(v["变更说明"] || "—")}</td>
          <td class="k">${时间(v["冻结时间"])}<br>${esc(v["冻结的人"] || "")}</td></tr>`).join("")}
        </tbody></table>`
      : 状态("", "还没有冻结过版本", "没有版本的策略绑不上去。下面填好配置 → 先「校验」→ 再「冻结成版本」。**校验过了不等于冻得进去**(冻结时还会再校一遍)。").html;
    const 不能改 = `<div class="note">改草稿 / 校验 / 冻结要「改筛选策略」这条能力(编辑、管理员默认有,审核发布者要授权)——
      你现在是 <b>${esc(我的角色 || "?")}</b>,<b>所以这里不摆表单</b>。</div>`;
    const 草稿块 = `<h2>草稿</h2><div class="note">改草稿要带 If-Match=<code>${esc(d.draft_revision)}</code>(就是上面那个草稿版号);别人先改了就 409,刷新再改。<b>已冻结的版本一个字不动</b></div>`
      + (能改
        ? `<div class="state" id="sel-draft"><h3>改名称 / 用途 / 负责人</h3>
            <p><label>名称<br><input id="sel-d-name" style="width:min(320px,90%)" value="${esc(d["名称"] || "")}"></label><div class="k err" id="sel-fe-名称"></div></p>
            <p><label>用途<br><textarea id="sel-d-purpose" rows="3" data-raw="原文" style="width:min(520px,95%)">${esc(草["用途"] || "")}</textarea></label><div class="k err" id="sel-fe-用途"></div></p>
            <p><label>负责人<br><input id="sel-d-owner" style="width:min(200px,90%)" value="${esc(草["负责人"] || "")}"></label><div class="k err" id="sel-fe-负责人"></div></p>
            <p><button class="pri" id="sel-d-go">保存草稿(If-Match ${esc(d.draft_revision)})</button></p></div>`
        : `<div class="k" data-raw="原文">用途:${esc(草["用途"] || "—")} · 负责人:${esc(草["负责人"] || "—")}</div>` + 不能改);
    // 配置表单:预填最新版本,没有版本就空着。词表从列表接口来;读不到就退成文本框
    const 模式们 = (表["可选模式"] || []), 空们 = (表["可选的没结果怎么办"] || []), 错们 = (表["可选的目录出错怎么办"] || []);
    const 选 = (id, 项们, 现, 空话) => 项们.length
      ? `<select id="${id}"><option value="">${esc(空话)}</option>${项们.map((x) => `<option value="${esc(x["值"])}"${现 === x["值"] ? " selected" : ""}>${esc(x["中文"])} (${esc(x["值"])})${x["首版支持吗"] === false ? " —— 扩展,首版不支持" : ""}</option>`).join("")}</select>`
      : `<input id="${id}" value="${esc(现 || "")}" placeholder="${esc(空话)}" style="width:min(320px,90%)">`;
    const 限 = (最新 && 最新["限额"]) || {};
    const 数 = (k) => `<label>${esc(选择策略_限额名[k])} <code>${esc(k)}</code><br><input type="number" id="sel-c-${k}" step="1" value="${限[k] == null ? "" : esc(限[k])}" placeholder="必填,不给默认值" style="width:140px"></label>`;
    const 配置块 = `<h2>配置 → 校验 → 冻结</h2>`
      + (能改
        ? `<div class="state" id="sel-cfg"><h3>${最新 ? `按 ${esc(最新["版本"])} 预填,改完冻结成新版本` : "第一版配置"}</h3>
            <p class="k">${md("限额**不给默认值**:一个猜出来的预算会在它不够用那天表现成「模型没看到那个工具」,而不报错。开独立路由要指一次跑完、有基线的评测,还要给探过的模型连接。身份 / 授权 / 密钥 / 范围类的键**不许进策略**")}</p>
            <p><label>模式<br>${选("sel-c-mode", 模式们, 最新 && 最新["模式"], "选一种")}</label></p>
            <p>${["initial_candidates", "new_definition_tokens", "active_definition_tokens", "max_rediscovery", "selection_timeout_ms"].map(数).join(" ")}</p>
            <p><label>没结果怎么办<br>${选("sel-c-empty", 空们, 最新 && 最新["没结果怎么办"], "选一种")}</label>
               <label style="margin-left:12px">目录出错怎么办<br>${选("sel-c-err", 错们, 最新 && 最新["目录出错怎么办"], "选一种")}</label></p>
            <p><label>目录快照 <span class="k">(关键词检索必填,只认「已就绪」)</span><br><input id="sel-c-snap" value="${esc((最新 && 最新["目录快照"]) || "")}" style="width:min(320px,90%)"></label>
               <label style="margin-left:12px">默认工具组版本 <span class="k">(固定工具组必填)</span><br><input id="sel-c-group" value="${esc((最新 && 最新["默认工具组版本"]) || "")}" style="width:min(320px,90%)"></label></p>
            <p><label><input type="checkbox" id="sel-c-router"${最新 && 最新["开了独立路由吗"] ? " checked" : ""}> 开独立路由</label>
               <label style="margin-left:12px">路由实验(评测 id)<br><input id="sel-c-evidence" value="${esc((最新 && 最新["路由实验"]) || "")}" style="width:min(260px,90%)"></label>
               <label style="margin-left:12px">路由模型连接(model_connections 的 id)<br><input id="sel-c-conn" value="${esc((最新 && 最新["路由模型连接"]) || "")}" style="width:min(260px,90%)"></label></p>
            <p><label><input type="checkbox" id="sel-c-cache"${最新 && 最新["开了候选缓存吗"] ? " checked" : ""}> 开候选缓存 <span class="k">(首版不许开,勾了校验会红)</span></label></p>
            <p><label>变更说明(冻结时写进版本)<br><textarea id="sel-c-note" rows="2" style="width:min(520px,95%)"></textarea></label></p>
            <p><button id="sel-c-validate">校验(不落版本)</button> <button class="pri" id="sel-c-freeze">冻结成新版本</button></p>
            <div id="sel-c-out"></div></div>`
        : 不能改);
    $("#list").innerHTML = 选择策略_生效横幅(d) + `<div id="sel-msg"></div>` + 草稿块
      + `<h2>版本历史(${版本们.length})</h2>` + 版本表 + 配置块;
    const 说 = (文, 坏) => { if ($("#sel-msg")) $("#sel-msg").innerHTML = 文
      ? (坏 ? `<div class="state err"><p>${文}</p></div>` : `<div class="state"><p>${文}</p></div>`) : ""; };
    if ($("#sel-d-go")) {
      $("#sel-d-go").onclick = async () => {
        const 体 = { 名称: String($("#sel-d-name").value || "").trim(), 用途: String($("#sel-d-purpose").value || "").trim(), 负责人: String($("#sel-d-owner").value || "").trim() };
        $("#sel-d-go").disabled = true; 说("提交中…");
        try {
          const r = await 选择策略动作.改草稿(pid, d.draft_revision, 体);
          await 页_工具选择策略详情(pid);
          说(`草稿保存了,草稿版现在是 <code>${esc(r.draft_revision)}</code><br>${md(r.note || "")}`);
        } catch (e) { 选择策略_报错(e, ["名称", "用途", "负责人"], 说); $("#sel-d-go").disabled = false; }
      };
    }
    if (!$("#sel-c-validate")) return;
    const 读配置 = () => {
      const v = (id) => String(($(id) && $(id).value) || "").trim();
      const 限额 = {};
      for (const k of Object.keys(选择策略_限额名)) { const s = v(`#sel-c-${k}`); if (s !== "") 限额[k] = Number(s); }
      const 配 = { 模式: v("#sel-c-mode"), 限额, 没结果怎么办: v("#sel-c-empty"), 目录出错怎么办: v("#sel-c-err"),
        加载方式: "append_within_run", 开独立路由: !!($("#sel-c-router") && $("#sel-c-router").checked),
        开候选缓存: !!($("#sel-c-cache") && $("#sel-c-cache").checked) };
      if (v("#sel-c-snap")) 配["目录快照"] = v("#sel-c-snap");
      if (v("#sel-c-group")) 配["默认工具组版本"] = v("#sel-c-group");
      if (配["开独立路由"]) { 配["路由实验"] = v("#sel-c-evidence"); 配["路由模型连接"] = v("#sel-c-conn"); }
      if (v("#sel-c-note")) 配["变更说明"] = v("#sel-c-note");
      return 配;
    };
    const 出 = (html) => { if ($("#sel-c-out")) $("#sel-c-out").innerHTML = html; };
    $("#sel-c-validate").onclick = async () => {
      $("#sel-c-validate").disabled = true; 出(`<div class="state"><p>校验中…</p></div>`);
      try {
        const r = await 选择策略动作.校验(pid, 读配置());
        const 问 = r["问题"] || [];
        出(`${问.length ? '<div class="state err">' : '<div class="state">'}<h3>${问.length ? `没过:${问.length} 条问题` : "校验过了"}</h3>
          ${问.length ? `<p>${问.map((x) => "· " + md(x)).join("<br>")}</p>` : ""}
          <p class="k">${md(r["⚠️校验过了不等于冻得进去"] || "")}</p>
          <p class="k">${md(r["⚠️还没生效"] || "")}</p>
          <details><summary>归一后的配置</summary><pre data-raw="原文">${esc(JSON.stringify(r["归一后的配置"] || {}, null, 1))}</pre></details></div>`);
      } catch (e) { 出(`<div class="state err"><p>${md(闸文(e)).replace(/\n/g, "<br>")}</p></div>`); }
      $("#sel-c-validate").disabled = false;
    };
    $("#sel-c-freeze").onclick = async () => {
      if (!(await 问一句("冻结成新版本?", `冻结后这一版<b>不可改</b>;会按同一套规则再校一遍,没过就 422 逐条列出。<br>冻结<b>不改变生产引用</b>,而且现在也没有东西在消费它。`, { 确定: "冻结", 取消: "先不" }))) return;
      $("#sel-c-freeze").disabled = true; 出(`<div class="state"><p>冻结中…</p></div>`);
      try {
        const r = await 选择策略动作.冻结(pid, 读配置());
        await 页_工具选择策略详情(pid);
        说(`冻结了 <b>${esc(r["版本"] || "")}</b>(${esc(r.id || "")})<br>${md(r.note || "")}<br>${md(r["⚠️还没生效"] || "")}`);
      } catch (e) {
        出(`<div class="state err"><p>${md(闸文(e)).replace(/\n/g, "<br>")}</p></div>`);
        $("#sel-c-freeze").disabled = false;
      }
    };
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

async function 路由() {
  if (离开拦截()) return;
  if (!location.hash.startsWith("#/workflow/")) document.body.classList.remove("wf-full");   // 只有编排页是全屏
  // 旧地址跳到新位置(10-28 导航照 Dify):replace 不留一条历史,点「后退」不会又跳回来
  if (旧地址跳[location.hash]) { location.replace(旧地址跳[location.hash]); return; }
  换页序++;
  画侧栏();
  $("#subnav").hidden = true; $("#subnav").innerHTML = "";
  const h = location.hash || "#/workbench";
  try {
    if (h === "#/workbench") return await 页_工作台();
    if (h.startsWith("#/studio/")) return await 页_分页签("#/studio", 工作室类型, h.slice(9));
    if (h.startsWith("#/integrations/")) return await 页_分页签("#/integrations", 集成类型, h.slice(15));
    if (h === "#/prompts") return await 页_prompt列表();
    if (h.startsWith("#/prompt/")) return await 页_prompt详情(decodeURIComponent(h.slice(9)));
    if (h === "#/glossaries") return await 页_术语列表();
    if (h === "#/entities") return await 页_实体识别列表();
    if (h === "#/routes") return await 页_路由列表();
    if (h === "#/intents") return await 页_意图列表();
    if (h.startsWith("#/intent/")) return await 页_意图详情(decodeURIComponent(h.slice(9)));
    if (h.startsWith("#/route/")) return await 页_路由详情(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/entity/")) return await 页_实体识别详情(decodeURIComponent(h.slice(9)));
    if (h.startsWith("#/glossary/")) return await 页_术语详情(decodeURIComponent(h.slice(11)));
    if (h === "#/human") return await 页_人工待办();
    if (h.startsWith("#/human/")) return await 页_待办详情(decodeURIComponent(h.slice(8)));
    if (h === "#/evals") return await 页_评测中心();
    if (h === "#/compare") return await 页_实验对比();
    if (h === "#/tryout") return await 页_单条试跑();
    if (h === "#/traces") return await 页_调用链();
    if (h.startsWith("#/trace/")) return await 页_调用树(decodeURIComponent(h.slice(8)));
    if (h === "#/annotations") return await 页_标注回复();
    if (h === "#/health") return await 页_智能体健康();
    if (h === "#/outputs") return await 页_产出监督();
    if (h === "#/documents") return await 页_报告与文件();
    if (h.startsWith("#/output/")) return await 页_产出详情(decodeURIComponent(h.slice(9)));
    if (h === "#/runs") return await 页_运行记录();
    if (h === "#/opinions") return await 页_意见受理();
    if (h === "#/monitoring") return await 页_监测();
    if (h === "#/alerts") return await 页_告警();
    if (h.startsWith("#/opinion/")) return await 页_意见详情(decodeURIComponent(h.slice(10)));
    if (h === "#/issues") return await 页_问题单清单();
    if (h.startsWith("#/issue/")) return await 页_问题单详情(decodeURIComponent(h.slice(8)));
    if (h === "#/knowledge-revisions") return await 页_知识修订清单();
    if (h.startsWith("#/knowledge-revision/")) return await 页_知识修订详情(decodeURIComponent(h.slice(21)));
    if (h.startsWith("#/verification/")) return await 页_验证记录详情(decodeURIComponent(h.slice(15)));
    if (h.startsWith("#/rollout/")) return await 页_发布记录详情(decodeURIComponent(h.slice(10)));
    if (h === "#/capabilities") return await 页_能力档案清单();
    if (h === "#/capability-board") return await 页_改进看板();
    if (h === "#/acceptance") return await 页_上线验收();
    if (h.startsWith("#/capability/")) return await 页_能力档案详情(decodeURIComponent(h.slice(13)));
    if (h === "#/schedules") return await 页_定时();
    if (h === "#/chat-tasks") return await 页_员工定时();
    if (h === "#/lanxiu-skills") return 页_澜绣治理("skills");
    if (h === "#/lanxiu-mcp") return 页_澜绣治理("mcp");
    if (h === "#/lanxiu-kb-issues") return 页_澜绣治理("kbissues");
    if (h.startsWith("#/workflow/")) return await 页_画布(decodeURIComponent(h.slice(11)));
    if (h.startsWith("#/wfrun/")) return await 页_运行详情(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/bridge/")) return await 页_桥请求详情(decodeURIComponent(h.slice(9)));
    if (h.startsWith("#/agent/")) return await 页_agent配置(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/chat/")) return await 页_聊天助手(decodeURIComponent(h.slice(7)));
    if (h.startsWith("#/tool/")) return await 页_工具详情(decodeURIComponent(h.slice(7)));
    if (h === "#/usage") return await 页_用量与成本();
    if (h === "#/uploads") return await 页_加资料();
    if (h === "#/kb") return await 页_知识库();
    // ⚠️ `#/chunks/` 和 `#/chunk/` 不冲突(第 8 个字符一个是 s 一个是 /),
    // 但更长的前缀写在前面 —— 下一个人加 `#/chunkset/` 时就不会踩。
    if (h.startsWith("#/chunks/")) return await 页_切片列表(decodeURIComponent(h.slice(9)));
    if (h.startsWith("#/chunk/")) return await 页_切片详情(decodeURIComponent(h.slice(8)));
    // `#/docs/` 是知识库的文档列表(11-18)。现在没有 `#/doc/`;以后加的话第 6 个字符一个是 s 一个是 /,
    // 不会互吃,但照上面的规矩长前缀写在前面
    if (h.startsWith("#/docs/")) return await 页_文档列表(decodeURIComponent(h.slice(7)));
    if (h.startsWith("#/kb/")) return await 页_索引构建(decodeURIComponent(h.slice(5)));
    if (h === "#/retrieval") return await 页_召回测试();
    if (h.startsWith("#/retrieval/")) return await 页_召回测试(decodeURIComponent(h.slice(12)));
    // ⚠️ 带参的写在前面(`#/rrun/` 比 `#/rruns` 长,但两者第 7 个字符不同,
    // 不会互相吃掉)—— 顺序照 `#/chunks/` 那段的理由。
    if (h.startsWith("#/rrun/")) return await 页_试跑详情(decodeURIComponent(h.slice(7)));
    if (h === "#/rruns") return await 页_召回测试();   // 旧地址(检索试跑记录)并进了召回测试
    if (h === "#/audit") return await 页_审计记录();
    if (h.startsWith("#/app/")) return await 页_应用详情(decodeURIComponent(h.slice(6)));
    if (h === "#/members") return await 页_成员与权限();
    if (h === "#/knobs") return await 页_旋钮与方案();
    if (h === "#/selection") return await 页_工具选择策略();
    if (h.startsWith("#/selection/")) return await 页_工具选择策略详情(decodeURIComponent(h.slice(12)));
    if (h === "#/datasets") return await 页_数据集();
    if (h.startsWith("#/samples/")) return await 页_样本(decodeURIComponent(h.slice(10)));
    if (h === "#/training") return await 页_训练任务();
    if (h === "#/artifacts") return await 页_模型产物();
    $("#main").innerHTML = 状态("", "这一页还没实现",
      "规格里有它,**入口保留着** —— 不能因为还没做就把需求删掉。").html;
  } catch (e) {
    const s = 错误块(e, 路由); $("#main").innerHTML = s.html; s.挂();
  }
}

async function 起() {
  画侧栏();
  const ok = await 画顶栏();
  if (ok) await 路由();
}
window.addEventListener("hashchange", 路由);
起();
