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
  return { html, 挂: () => { if (动作) $("#st-act").onclick = 动作.做; } };
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
  ["#/kb", "知识库", true],
  ["#/uploads", "加资料", true, true],
  ["#/retrieval", "召回测试", true, true],
  ["#/integrations", "集成", true],
  ["grp", "待办与定时"],
  ["#/human", "人工待办", true, true],
  ["#/schedules", "定时", true, true],
  ["grp", "日志与监测"],
  ["#/runs", "运行记录", true, true],
  ["#/traces", "调用链", true, true],
  ["#/outputs", "产出监督", true, true],
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
  ["#/members", "成员与权限", true, true],
  ["#/audit", "审计记录", true, true],
];
/* 工作室、集成的页签(照 Dify:工作室按应用类型分、集成分模型供应商 / 工具)。
 * 没接上的类型**留着入口、写明为什么**,不藏(侧栏同一条规矩) */
// 10-28 工作室做成卡片(二期第 2 项):页签照 Dify 的筛选 —— 全部 / 工作流 / 对话流 / 聊天助手 / Agent / 文本生成;
// 「应用与发布」不是一种应用类型(它答的是「哪一版在给用户跑」),放在最右
const 工作室类型 = [["all", "全部", () => 页_工作室("all")], ["workflow", "工作流", () => 页_工作室("workflow")],
  ["chatflow", "对话流", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["chat", "聊天助手", null, "澜绣聊天站里的各个岗位助手;先拿店长任务助手试点,配置页还在做"],
  ["agent", "Agent", () => 页_工作室("agent")],
  ["completion", "文本生成", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["app", "应用与发布", () => 页_应用与发布()]];
const 集成类型 = [["models", "模型供应商", () => 页_模型与连接()], ["tools", "工具", () => 页_工具目录()]];
const 旧地址跳 = { "#/workflows": "#/studio/workflow", "#/agents": "#/studio/agent", "#/apps": "#/studio/app",
  "#/conns": "#/integrations/models", "#/tools": "#/integrations/tools",
  "#/studio": "#/studio/all", "#/integrations": "#/integrations/models" };
async function 页_分页签(根, 表, 键) {
  const 项 = 表.find((x) => x[0] === 键);
  const 条 = `<div class="subtabs" role="tablist">${表.map(([k, 名, fn, 为什么]) => fn
    ? (k === 键 ? `<a role="tab" href="${根}/${k}" class="on" aria-selected="true">${esc(名)}</a>`
                : `<a role="tab" href="${根}/${k}" aria-selected="false">${esc(名)}</a>`)
    : `<a role="tab" class="todo" title="${esc(为什么 || "")}" aria-disabled="true">${esc(名)}</a>`).join("")}</div>`;
  $("#subnav").innerHTML = 条; $("#subnav").hidden = false;
  if (!项 || !项[2]) { $("#main").innerHTML = 状态("", "这一类还没接上", (项 && 项[3]) || "换一个页签看看").html; return; }
  return await 项[2]();
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
  if (!ps.some((p) => p.id === 项目)) 项目 = ps[0].id;
  localStorage.setItem("aimc.proj", 项目);
  $("#proj").innerHTML = ps.map((p) =>
    `<option value="${p.id}"${p.id === 项目 ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  $("#proj").onchange = (e) => {
    项目 = e.target.value; localStorage.setItem("aimc.proj", 项目);
    // **切项目后清掉旧项目的对象选择**(§4)—— 不能带着上个项目的 ID 过去
    location.hash = "#/workbench"; 路由();
  };
  const me = ps.find((p) => p.id === 项目);
  能力 = (me && me.special_grants) || [];
  我的角色 = (me && me.role) || "";
  $("#whoami").textContent = `${我} · ${(me && me.role) || "?"}`;
  return true;
}

const P = () => `/api/v1/projects/${encodeURIComponent(项目)}`;

/* ── 工作台(§6)──────────────────────────────────────────────────
 * 每张卡要带**时间范围、分母、环境、数据来源、更新时间**。
 * **质量评分不能用 HTTP 成功率代替;没有评测覆盖显示「尚未评测」,不显示 0 分。** */
async function 页_工作台() {
  const 头 = `<div class="crumb">工作台</div>
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
      return `<div class="card kpi">
        <div class="k">${esc(c.名)}</div>${值}
        ${c.说明 ? `<div class="why">${md(c.说明)}</div>` : ""}
        <div class="meta">
          ${c.分母 ? `分母:${esc(c.分母)}<br>` : ""}
          ${esc(c.时间范围)} · 环境 ${esc(c.环境)}<br>
          来源:${esc(c.数据来源)}<br>更新:${esc(c.更新时间)}
        </div></div>`;
    };
    $("#main").innerHTML = 头
      + `<div class="cards">${(d.卡片 || []).map(卡).join("")}</div>`
      + `<div class="note warn">${md(`**「未知」不是 0。** 费用未知是因为 mock 适配器没有真实计价;
         质量分未知是因为还没有评测覆盖 —— 显示 0 会被读成「质量很差」,而真相是「没测过」。`)}</div>`;
    $("#wb-h").value = h;
    $("#wb-h").onchange = 画;
  };
  await 画();
}

/* ── Prompt 列表(§8.1)─────────────────────────────────────────── */
async function 页_prompt列表() {
  const 头 = `<div class="crumb">Prompt 管理</div>
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
  const 画 = async () => {
    const q = $("#f-q").value.trim(), pr = $("#f-prod").value;
    let u = `${P()}/prompts?limit=20`;
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
        <th>标识</th><th>用途</th><th>标签</th>
        <th>最新保存版本</th><th>生产引用版本</th>
        <th>最近评测</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rs.map((r) => `
        <tr><td class="num">${esc(r.key)}</td>
          <td>${esc((r.用途 || "").slice(0, 40)) || '<span style="color:var(--faint)">—</span>'}</td>
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
        <div class="right">${d.next_cursor ? `<button id="more">下一页</button>` : ""}</div>
      </div>`;
    if (d.next_cursor) $("#more").onclick = () => 提示("还不能翻页", "翻页还没接 —— 服务端已经给了游标,前端还没用上。");
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
  $("#f-q").oninput = (() => { let t; return () => { clearTimeout(t); t = setTimeout(画, 300); }; })();
  $("#f-prod").onchange = 画;
  $("#f-reset").onclick = () => { $("#f-q").value = ""; $("#f-prod").value = ""; 画(); };
  await 画();
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
  const 草 = d.草稿, m = 草.messages || {}, 变量 = 草.variable_schema || [];
  let rev = 草.revision;                 // 乐观锁:每次保存后要更新它
  let 脏 = false;                        // 未保存标记(§5.4「未保存」状态)
  const 出要 = 草.output_schema || {};

  const 版本行 = (d.版本历史 || []).map((v) => `
    <tr><td class="num">v${v.version_no}</td>
      <td class="num">${esc(String(v.content_hash || "").slice(0, 12))}</td>
      <td>${esc(v.变更说明 || "—")}</td>
      <td class="num">${esc(String(v.created_at || "").slice(0, 16))}</td>
      <td>${esc(v.created_by || "")}</td></tr>`).join("");

  $("#main").innerHTML = `
    <div class="crumb"><a href="#/prompts">Prompt 管理</a> / ${esc(草.key)}</div>
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

        <label class="f">输入变量</label>
        <div id="vars"></div>
        <div class="note">${md(`**定义变量不等于已经取得数据。** 每个变量都要说清来源
          (用户输入 / 上一步结果 / 检索上下文 / 受控系统字段)—— 来源没绑上,
          它在运行时就是空的。`)}</div>

        <label class="f">输出要求</label>
        <pre class="io" id="e-out" data-raw="原文">${esc(JSON.stringify(出要, null, 2))}</pre>

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
          <div class="note warn">${md(`当前是 **mock 适配器** —— 它返回的是编出来的回答,
            **不许计入真实评测或发布**。接真实连接后这里会列出该连接**实际支持**的参数
            (不支持的参数会返回明确错误,不会被静默忽略)。`)}</div>
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

  /* 变量表(左)+ 测试输入(右)—— 同一份变量定义,两个用途 */
  const 画变量 = () => {
    $("#vars").innerHTML = 变量.length ? `<table><thead><tr>
        <th>名称</th><th>说明</th><th>类型</th><th>来源</th><th>必填</th><th>默认值</th>
      </tr></thead><tbody>${变量.map((v) => `<tr>
        <td class="num">${esc(v.名称)}</td><td>${esc(v.说明 || "")}</td>
        <td>${esc(v.类型 || "string")}</td><td>${esc(v.来源 || "—")}</td>
        <td>${v.必填 ? '<span class="pill warn">必填</span>' : "可选"}</td>
        <td>${esc(v.默认值 ?? "—")}</td></tr>`).join("")}</tbody></table>`
      : `<div class="note">${md(`还没定义变量。模板里写了 <code>{{x}}</code> 但没定义的话,
          「保存为新版本」会被拦住 —— 那不是刁难:**没定义来源的变量在运行时是空的**。`)}</div>`;
    $("#testvars").innerHTML = 变量.length ? 变量.map((v) => `
      <label class="f">${esc(v.名称)}${v.必填 ? ' <span class="req">*</span>' : ""}
        <span style="color:var(--ink3)">${esc(v.说明 || "")}</span></label>
      <textarea class="t" data-tv="${esc(v.名称)}" rows="${v.名称 === "article" ? 4 : 1}"
        placeholder="${esc(v.默认值 ?? "")}"></textarea>`).join("")
      : `<div class="note">这条 Prompt 没有变量 —— 直接点运行测试。</div>`;
  };
  画变量();

  const 标脏 = () => { 脏 = true; $("#fb").textContent = "有未保存的改动"; $("#fb").className = "msg"; };
  ["#e-用途", "#e-system", "#e-user", "#e-why"].forEach((s) => { $(s).oninput = 标脏; });

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
    $("#b-draft").disabled = true;
    try {
      const r = await 请求(`${P()}/prompts/${encodeURIComponent(pid)}/draft`, {
        method: "PATCH",
        headers: { "If-Match": String(rev) },      // **必填** —— 否则就是「最后写的人赢」
        body: JSON.stringify({
          用途: $("#e-用途").value, system: $("#e-system").value,
          user: $("#e-user").value, 变更说明: $("#e-why").value,
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
        body: JSON.stringify({ prompt_id: pid, 变量: 变 }),
      });
      $("#runmsg").textContent = `任务 ${r.job_id} · ${r.status}`;
      await 画运行(r.job_id);
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

  async function 画运行(job) {
    const j = await 请求(`${P()}/jobs/${encodeURIComponent(job)}`);
    const 果 = j.结果 || {};
    const 段 = 果.阶段 || [];
    const 用 = 果.用量 || [];
    $("#runout").style.display = "";
    $("#runout").innerHTML = `
      <div style="font-weight:600;margin-bottom:6px">实际输出
        <span class="vtag">· ${esc(j.status)}${j.是终态吗 ? "(终态)" : "(**还没结束**)"}</span></div>
      ${段.map((s) => `
        <div class="vtag">阶段:${esc(s.阶段)}</div>
        <pre class="io">${esc(typeof s.输出 === "string" ? s.输出
                                : (s.输出 && s.输出.text) || JSON.stringify(s.输出, null, 2))}</pre>
        <details><summary>应用实际发送给模型的内容${果.看得到原文 ? "" : "(已脱敏)"}</summary>
          <pre class="io" data-raw="原文">${esc(JSON.stringify(s.实际发送, null, 2))}</pre>
          ${果.看得到原文 ? "" : `<div class="note">${md(`**默认脱敏。** 看原文要
            「查看敏感输入/独立测试答案」专项权限 —— 换成 U004 能看到差别。`)}</div>`}
        </details>`).join("")}
      <div class="two" style="margin-top:8px">
        <div><div class="vtag">用量</div>
          ${用.map((u) => `<div style="font-size:12.5px">
            ${esc(u.resource || "")} ${esc(u.quantity)} ${esc(u.unit || "")} ·
            费用 ${u.amount_known ? esc(u.amount) : "<b>未知</b>"} (来源 ${esc(u.source || "")})
          </div>`).join("") || "—"}
          <div class="note">${md(果.费用说明 || "")}</div></div>
        <div><div class="vtag">事件</div>
          ${(j.事件 || []).map((e) => `<div style="font-size:12.5px">
            #${e.seq} ${esc(e.kind)} ${esc(String(e.at || "").slice(0, 19))}</div>`).join("")}
          <div class="note">Trace <code>${esc(果.trace_id || "—")}</code></div></div>
      </div>
      <div class="note">${md(`跑完可以「加入问题集」「保存为评测样本」—— 新样本**先进待审核**,
        避免把错误答案当成真值。(这两个按钮还没实现)`)}</div>`;
  }
}

/* ── 运行记录(占位:列表已有接口,详情页还没做)────────────────── */
async function 页_运行记录() {
  // 证据中心第四个工作包(10-25):原来是占位页。现在列**聊天站**推过来的每一轮(entry_kind=聊天站),
  // 点进去是同一个调用树页 —— 原文看不看得到由那边的字段权限管(查看敏感输入),这一页不另判
  const 头 = `<div class="crumb">运行记录</div>
    <div class="head"><div><h1>运行记录</h1>
      <div class="sub">${md("聊天站每一轮实际调了哪些工具、传了什么、回了什么。**原文要「查看敏感输入」授权**,没有的只看到形状。")}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces?limit=100&entry_kind=${encodeURIComponent("聊天站")}`); }
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
    + `</tbody></table><div class="note">${md("「进行中」超过半小时没收尾的,聊天站那边会判成「中断」再推一次。")}</div>`;
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
const 工作流页签 = ["概览", "搭建", "测试", "运行记录", "版本与发布", "设置"];
// 10-27 照 Dify 改了两个名字(适配分析 5.1 定的):结束 →「输出」、分支汇合 →「变量聚合器」;其余保留业务叫法
const 步类型名 = { start: "开始", end: "输出", llm: "AI 处理", tool: "业务动作", retrieve: "查资料",
  condition: "按条件分流", transform: "整理字段", merge: "变量聚合器", loop: "循环", human: "人工核对", agent: "Agent", answer: "直接回复", classifier: "问题分类器", template: "模板转换", extractor: "参数提取器", assigner: "变量赋值" };
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
/* ── 工作室:应用卡片(10-28 照 Dify;用户 10-27 拍第 9 条「应用类型五种都留」)────────────
 * 卡片上只放**一眼要判断的**:是什么类型、干什么用、线上跑的哪一版、最近跑得怎样、聊天里谁来做。
 * 版本 / 测试 / 发布这些进详情做。没接上的三种类型在「创建应用」里**摆出来、写明为什么点不了**,不藏 */
const 应用类型 = [
  ["workflow", "工作流", "流", "按固定步骤跑的流程:每一步用什么、数据从哪来都事先定好。", () => 弹_新建工作流()],
  ["chatflow", "对话流", "话", "带记忆的多轮对话,每一轮按固定步骤跑。", null, "暂无对应业务(用户 10-27 拍:五种都留,这一种先空着)"],
  ["chat", "聊天助手", "聊", "澜绣聊天站里的岗位助手(店长、顾问…):改提示词、选模型和工具。", null, "配置页还在做,先拿店长任务助手试点"],
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
      <a href="${链("搭建")}">编辑</a> · <a href="${链("测试")}">运行</a> · <a href="${链("运行记录")}">看记录</a></div>
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

async function 页_工作室(类) {
  $("#main").innerHTML = `<div class="head"><div><h1>工作室</h1>
      <div class="sub">这个项目里的应用:按固定步骤跑的工作流、模型自己决定下一步的 Agent,以及聊天站里的岗位助手。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const [流, 智] = await Promise.all([类 !== "agent" ? 请求(`${P()}/workflows`) : null,
                                        类 !== "workflow" ? 请求(`${P()}/agents`) : null]);
    const 卡们 = [...((流 && 流.items) || []).map(卡_工作流), ...((智 && 智.items) || []).map(卡_agent)];
    const 新 = `<button class="appcard new" id="new"><b>+ 创建应用</b>
        <span class="k">选一种类型:工作流 / 对话流 / 聊天助手 / Agent / 文本生成</span></button>`;
    // 空的时候也要一句人话(冒烟对账按结构判:state 块带标题和说明)
    const 空 = 卡们.length ? "" : 状态("", 类 === "agent" ? "还没有 Agent" : 类 === "workflow" ? "还没有工作流" : "还没有应用",
      "点「创建应用」选一种类型。工作流从模板起(音频整理 / 文本处理 / 空白);模板**只预填草稿** —— 不调模型、不绑生产环境。").html;
    $("#list").innerHTML = `${空}<div class="appcards">${新}${卡们.join("")}</div>
      <div class="note">${[[流, "工作流"], [智, "Agent"]].filter((x) => x[0]).map(([d, 名]) =>
          `${名} ${d.total != null && d.total > d.items.length ? `显示 ${d.items.length} / 共 ${d.total}(翻页还没做)` : `${d.items.length}`}`).join(" · ")}。
        「线上(生产)」之外的版本都只是<b>候选</b> —— 要在「版本与发布」里发到生产(生产要审核)才算上线。
        ${流 ? "<br>「聊天里」<b>默认交给 harness</b>(聊天站的技能自己做);打开接管后改为发起这条工作流<b>生产环境里的那一版</b>,同一个技能同时只能被一条工作流接管。" : ""}
        ${智 ? "<br>Agent 的「候选工具」数只表示授权候选集合的规模 —— 规格 §9.1 明写<b>不按工具数量给 Agent 打能力强弱分</b>。" : ""}</div>`;
    $("#new").onclick = 弹_新建应用;
    $("#list").querySelectorAll("[data-tk]").forEach((b) => {
      b.onclick = async () => { b.disabled = true; await 拨接管(b.dataset.tk, b.dataset.on === "1"); 页_工作室(类); };
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
    <div class="acts"><button class="pri" id="nw-ok">创建</button> <button id="nw-no">取消</button></div>`);
  $("#nw-no").onclick = 关弹层;
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
  画_搭建(); 画_底栏(); 画_保存状态();
}

function 画_画布() {
  const g = 图态;
  if (g.页签 === "搭建") return 画_编排页();
  document.body.classList.remove("wf-full");
  const 签 = 工作流页签.filter((t) => t !== "搭建").map((t) => t === g.页签
    ? `<a class="on" href="#/workflow/${encodeURIComponent(g.wid)}/${encodeURIComponent(t)}">${t}</a>`
    : `<a href="#/workflow/${encodeURIComponent(g.wid)}/${encodeURIComponent(t)}">${t}</a>`).join("");
  $("#main").innerHTML = `
    <div class="crumb"><a href="#/workflows">工作流</a> / ${esc(g.名称)}</div>
    <div class="head"><div><h1>${esc(g.名称)}</h1>
      <div class="sub"><span id="savest" role="status" aria-live="polite"></span>
        ${g.用途 ? ` · ${esc(g.用途)}` : ""}</div></div>
      <div><a class="btn pri" id="edit" href="#/workflow/${encodeURIComponent(g.wid)}/搭建">编辑编排</a>
        <button id="freeze">生成版本</button></div></div>
    <nav class="wftabs">${签}</nav>
    <div id="tabbody"></div>
    <div class="footbar"><span id="fb"></span></div>`;
  $("#freeze").onclick = 弹_准备发布;
  ({ 概览: 画_概览, 搭建: 画_搭建, 测试: 画_测试, 运行记录: 画_运行记录, 版本与发布: 画_版本, 设置: 画_设置 }
    [g.页签] || 画_概览)();
  画_底栏(); 画_保存状态();
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
function 能改图() { return typeof 我的角色 === "undefined" || 我的角色 === "editor" || 我的角色 === "admin"; }
function 历史() { return 图态.历史 || (图态.历史 = 图逻辑.历史()); }
function 改图(名, fn, { 合并键 = null, 重绘 = true } = {}) {
  if (!能改图()) { 提示("只读:你没有「改编排草稿」的权限 —— 可以查看、缩放、查找"); return false; }
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
  if (!x) { 提示("没有可以撤销的编辑"); return; }
  回到(x.快照); if (typeof 清理选择 === "function") 清理选择(); 标脏(); 重画全部();
  提示(`已撤销:${x.名}`);
}
function 重做() {
  if (!能改图()) return;
  const x = 历史().重做();
  if (!x) { 提示("没有可以重做的编辑"); return; }
  回到(x.快照); if (typeof 清理选择 === "function") 清理选择(); 标脏(); 重画全部();
  提示(`已重做:${x.名}`);
}
function 重画全部() {
  if (!图态 || 图态.页签 !== "搭建" || !$("#pn")) { 画_底栏(); return; }
  if (图态.视图 === "流程图" && $("#steps")) 画_图(); else if ($("#steps")) 画_步骤();
  画_面板(); 画_问题(); 画_底栏();
}
const 检查过期 = () => !!(图态.报告 && 图态.报告定义 !== JSON.stringify(图态.定义));

/* 编辑区底部的结果提示 + 撤销入口(W29)。**自动消失不清撤销历史** */
let _提示时 = 0;
function 提示(文, { 撤销: 可撤 = false } = {}) {
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
function 次级标签(n) {
  const 在 = n.container && 图态 && 图态.定义 && 节点(n.container) ? ` · 在「${业务名(节点(n.container))}」里` : "";
  if (n.type === "tool") {
    const t = 工具资源((n.config || {}).tool_version_id);
    return (t ? `业务动作 · ${t["读写"]}` : "业务动作") + 在;
  }
  return (步类型名[n.type] || n.type) + 在;
}
function 缺项(n) {
  return (元(n.type)["必填"] || []).filter((f) => {
    const v = (n.config || {})[f];
    return v === undefined || v === null || v === "" || (typeof v === "object" && !Object.keys(v).length);
  });
}
const 字段中文 = { connection_version_id: "用哪个模型", prompt_version_id: "这一步要完成什么(处理要求)",
  output_schema: "结果包含哪些内容", tool_version_id: "执行哪个业务动作", input_schema: "用户需要提供什么",
  branches: "满足什么条件", else_policy: "都不满足时怎么办", request_kind: "核对类型",
  candidate_roles: "谁来处理", expires_at_policy: "多久没处理就结束", operations: "怎么整理",
  knowledge_base_id: "查哪个资料库", retrieval_config_version_id: "怎么查", candidates: "汇合哪几路",
  output_field: "汇合后叫什么", agent_version_id: "用哪个 Agent", task_binding: "交给它的任务",
  sub_limits: "这一步的上限", bindings: "用到的数据" };
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
  const 依赖 = g.定义.nodes.filter((n) => ["llm", "tool", "human"].includes(n.type)).map((n) => {
    const 缺 = 缺项(n);
    let 用的 = "";
    if (n.type === "llm") {
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
  if (n.type === "loop" || n.type === "classifier") return 图逻辑.出口们(n, 元);   // 进循环体 / 循环结束后 / 失败时 —— 和画布同一份
  const 口 = [{ port: "success", branch_key: null, 名: "完成后" }];
  if ((元(n.type)["端口"] || []).includes("error")) 口.push({ port: "error", branch_key: null, 名: "失败时" });
  return 口;
}
const 同口 = (e, o) => e.port === o.port && (e.branch_key || null) === (o.branch_key || null);

function 弹_在此后添加(id) {
  const n = 节点(id), 口们 = 出口们(n);
  const 可加 = ["llm", "tool", "human", "condition", "transform", "retrieve", "merge", "answer", "loop", "classifier", "extractor", "template", "assigner"]
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
           answer: { template: "", bindings: {} },
           template: { template: "", bindings: {} },
           assigner: { assignments: [] },
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
        提示(`没加:${图逻辑.能插入吗(类型, 元).为什么}`); return false;
      }
      if (原) 图逻辑.插入到线(g.定义, 图逻辑.边键(原), g.定义.nodes.pop(), 元);
      else 图逻辑.连(g.定义, 接.在后, 接.口, id);
    }
    const 前 = (接 && g.布局[接.在后]) || null;
    const 已 = Object.keys(g.布局).filter((k) => k !== "$线").length;
    g.布局[id] = 前 ? { x: 前.x + 200, y: 前.y + 90 }
                   : { x: 40 + (已 % 4) * 200, y: 40 + Math.floor(已 / 4) * 110 };
    g.选中 = id; g.面板页 = "设置";
  }, { 重绘: false });
  if (id && 节点(id)) { if (g.画) g.画.选 = new Set([id]); if (g.页签 === "搭建") 画_搭建(); }
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
  if (!影.要删.length) { 提示(影.跳过.map((x) => x.为什么).join(";") || "没有可删的步骤"); return; }
  const 做 = (桥接) => {
    改图(影.要删.length > 1 ? `删除 ${影.要删.length} 步` : `删除「${名(影.要删[0])}」`, () => {
      图逻辑.删节点(g.定义, g.布局, 影.要删, { 桥接, 元, 是敏感: 是敏感节点 });
      if (g.画) { 影.要删.forEach((x) => g.画.选.delete(x)); g.画.线 = null; }
      if (影.要删.includes(g.选中)) g.选中 = null;
    });
    提示(`已删除 ${影.要删.map(名).join("、") || ""}` + (影.跳过.length ? `;保留:${影.跳过.map((x) => x.为什么).join(";")}` : "")
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
      ${(() => { const 跑 = g.运行态 && g.运行态[n.id];   // 上次跑这一步收到 / 交出了什么(10-26)+ 单独测这一步
        const 上次 = 跑 ? `<div class="k">上次:${esc(运行状态中文[跑.状态] || 跑.状态)}${跑.错误码 ? ` · <code>${esc(跑.错误码)}</code>` : ""}</div>`
          + (步骤IO({ 输入: 跑.输入, 输出: 跑.输出 }, 跑.原文, true) || `<div class="k">这一步没有记下输入输出(没跑到它,或是改版前跑的)。</div>`) : "";
        const 测 = 单测表(n);
        return 上次 || 测 ? 段("试这一步", "试这一步", 上次 + 测) : ""; })()}
    </div>`;
  挂单测(n);
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
  if (!项们.length) return `<div class="note">${esc(空话)}</div>`;
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
  try { 图态.资源 = await 请求(`${P()}/workflow-resources`); 提示("资源列表已重新取到"); }
  catch (e) { 图态.资源 = { ...图态.资源, 拉取失败: true }; 提示("还是取不到:" + e.message + "(当前选择没动)"); }
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
    提示(`已换成「${新t["名"]}」` + (差.类型变化.length ? `;${差.类型变化.join("、")} 类型变了,请核对` : ""), { 撤销: true });
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
            if (!r.可以) { if (!r.没变) 提示(`没改名:${r.为什么}`); el.value = x.key || ""; return false; }
            重画(); })}
          <div class="k">什么样的算这一类(写给模型看)</div>${输入框(x.说明 || "", (el) => { x.说明 = el.value.trim() || undefined; }, "例如:客户问了价格、档期或约了到店", { 可清空: true })}
          <div class="acts"><button class="danger" data-k="${挂控件(() => {
              const r = 图逻辑.删分支(图态.定义, n.id, i);
              提示(`已删除「${r.键}」这一类` + (r.删边.length ? `和它的 ${r.删边.length} 条连线(目标步骤保留)` : ""), { 撤销: true }); 重画(); })}"
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
      + `<div class="k">到点没人处理:这次运行结束、记「已过期」,不写任何东西;想补就重新发起一次。</div>`;
  } else if (n.type === "condition") {
    const 源们 = 上游字段(n.id);
    体 += `<label class="f">满足什么条件</label>
      <div class="note">从上往下,<b>第一个满足的分支生效</b> —— 调顺序就是改执行逻辑,改完要重新检查。</div>`
      + (c.branches || []).map((b, i) => `<div class="card">
          <div class="k">第 ${i + 1} 路 · 叫</div>${输入框(b.key, (el) => {
            const r = 图逻辑.分支改名(图态.定义, n.id, b.key, el.value);
            if (!r.可以) { if (!r.没变) 提示(`没改名:${r.为什么}`); el.value = b.key; return false; }
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
              提示(`已删除「${r.键}」这一路` + (r.删边.length ? `和它的 ${r.删边.length} 条连线(目标步骤保留)` : ""), { 撤销: true }); 重画(); })}">删除分支</button></div></div>`).join("")
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
  } else if (n.type === "start") {
    体 += `<label class="f">使用者要提供什么</label>` + 字段表编辑(c.input_schema = c.input_schema || { type: "object", properties: {}, required: [] }, true);
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
      <textarea data-k="${k}" data-lb="回复内容" rows="4" placeholder="例如:{{客户}}您好,您的需求已记下,店长核对后会联系您">${esc(c.template || "")}</textarea>
      <div class="k">这句话会发回聊天里;管理后台试运行时用对话气泡显示。要带上前面的结果就写 <code>{{名字}}</code>,名字在下面「用到的数据」里选来源。</div>`
      : `<label class="f">模板</label>
      <textarea data-k="${k}" data-lb="模板" rows="5" placeholder="例如:{{客户}} 想要 {{款式}},预算 {{预算}},下次跟进 {{日期}}">${esc(c.template || "")}</textarea>
      <div class="k">把前面的结果拼成一段文字,交给后面的步骤用(不发给聊天里的人)。写 <code>{{名字}}</code>,名字在下面「用到的数据」里选来源。
        只做替换 —— 要按条件写不同的话,用「条件分支」分开写。</div>`;
    体 += `
      ${缺.length ? `<div class="ferr">模板里的 ${缺.map((x) => `「${esc(x)}」`).join("、")} 还没在「用到的数据」里 —— 运行前要选来源</div>` : ""}`;
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
        if (!v.可以) { 提示(`没改:${v.为什么}`); el.value = e ? e.target : ""; return false; }
        图逻辑.连(图态.定义, n.id, o, el.value);
        if (v.替换) 提示(`已把「${o.名}」的下一步从「${业务名(节点(v.替换.target))}」改为「${业务名(节点(el.value))}」`, { 撤销: true });
        重画();
      }, o.port === "error" ? "失败就结束这次运行" : "(不接)")}</div>`;
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
  if (n.type === "human") return ["决定", "定稿", "理由", "处理人"];
  if (n.type === "answer") return ["回复"];
  if (n.type === "template") return ["文本"];
  if (n.type === "assigner") return [...new Set((c.assignments || []).map((a) => a.variable).filter(Boolean))];
  if (n.type === "extractor") return (c.parameters || []).map((p) => p.name).filter(Boolean);
  if (n.type === "classifier") return ["类别", "理由"];
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
          : 在契约 && !r ? "" : `<button class="danger" data-k="${挂控件(() => { delete 绑[k]; 提示(`已删除字段「${k}」`, { 撤销: true }); 重画(); })}">删除字段</button>`}</div></div>`;
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
  if (n.type === "merge") return `<div class="k">汇合会取下面<b>第一个有值</b>的那一路(条件没走的那一路没有值)。</div>`
    + (n.config.candidates || []).map((r, i) => `<div class="fieldrow"><label>第 ${i + 1} 路</label>${下拉(引用值(r), 上游字段(n.id),
        (el) => { n.config.candidates[i] = 解引用(el.value); })}</div>`).join("")
    + `<button data-k="${挂控件(() => { (n.config.candidates = n.config.candidates || []).push(null); 重画(); })}">加一路</button>`;
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
        if (sch.properties[新]) { 提示(`没改:已经有字段叫「${新}」`); el.value = k; return false; }
        // 改的是**字段标识**:引用它的地方要同步,否则那几处会安静地取不到值
        const 引 = 字段引用(sch, k);
        sch.properties[新] = v; delete sch.properties[k];
        sch.required = sch.required.map((x) => (x === k ? 新 : x));
        if (引.length) 引.forEach((r) => { r.pointer = "/" + 新; });
        提示(引.length ? `已改字段标识「${k}」→「${新}」,同步更新了 ${引.length} 处引用(提示词正文里的文字不会被替换)` : `已改字段标识「${k}」→「${新}」`, { 撤销: true });
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
        提示(`已删除字段「${k}」` + (引.length ? `;有 ${引.length} 处还在用它,已标「来源字段已删除」,要改` : ""), { 撤销: true });
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
  if (n.type === "human") return `<div class="k">人工核对固定返回:<b>决定</b>(approve / reject)、<b>定稿</b>、<b>理由</b>、<b>处理人</b>。</div>`;
  if (n.type === "classifier") return `<div class="k">固定返回:<b>类别</b>(模型挑的那一个名字)、<b>理由</b>(它为什么这么分)。走哪条线由类别定。</div>`;
  if (n.type === "extractor") return `<div class="k">返回上面「基本」里列的每一项参数;<b>原文没提到的那一项是空</b>,必填的没抽到这一步就失败。</div>`;
  if (n.type === "assigner") return `<div class="k">返回改完之后的值(每一项一个)。循环里后面的步骤直接取「循环状态 · 名字」就是新值。</div>`;
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
  // 放在哪个循环里(10-27):循环里的步骤每一轮都跑;循环本身、开始、输出不能放进去(不支持循环套循环)
  const 环们 = g.定义.nodes.filter((x) => x.type === "loop" && x.id !== n.id);
  if (环们.length && !["start", "end", "loop"].includes(n.type)) {
    体 += `<label class="f">放在哪个循环里</label>` + 下拉(n.container || "", 环们.map((x) => [x.id, 业务名(x)]), (el) => {
      if (el.value) n.container = el.value; else delete n.container; 重画(); }, "不在循环里")
      + `<div class="k">放进去之后:从循环的「进循环体」出口连到第一步;循环里走到头(或连回循环)= 这一轮做完。</div>`;
  }
  if ((元(n.type)["端口"] || []).includes("error")) {
    体 += `<label class="f">失败后怎么办</label>` + 下拉(c.failure_policy || "fail_run",
      [["fail_run", "这次运行失败"], ["branch", "走「失败时」那条线"]], (el) => { c.failure_policy = el.value; });
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
      ${框 || '<div class="k">这条流程不需要使用者提供任何东西。</div>'}
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
    const 缺 = (sch.required || []).filter((k) => !(k in 输入));
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
function 记运行态(d) {
  if (!图态) return;
  const 态 = {};
  (d["步骤"] || []).forEach((s) => { 态[s["节点"]] = { 状态: s["状态"], 错误码: s["错误码"], 分支: s["走的分支"],
    输入: s["输入"], 输出: s["输出"], 原文: !!d["看得到原文"] }; });
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
  return x ? `<span class="pill" data-run="${esc(x.状态)}">${esc(运行状态中文[x.状态] || x.状态)}</span>` : "";
}
/* 每一步实际收到的 / 交出的(10-26)。没有「查看敏感输入」授权时接口只给形状(有哪些项、各多长),
 * 这里照实标出来 —— 不标的话,「<str · 1203 字>」会被当成这一步真的输出了这么一串 */
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
function 业务结果块(d) {
  const r = d["业务结果"]; if (!r) return `<div><b>${esc(d["执行状态中文"])}</b></div>`;
  const 色 = { "已完成": "ok", "已完成,需补充资料": "warn", "没做完": "warn", "失败": "err", "进行中": "" }[r["结论"]] || "";
  const 步名 = r["哪一步"] ? (节点(r["哪一步"]) ? 业务名(节点(r["哪一步"])) : r["哪一步"]) : "";
  return `<div class="bizres" data-res="${色}">${r["跑法"] === "连接测试" ? '<span class="pill">连接测试</span> ' : ""}<b>${esc(r["结论"])}</b>${步名 ? ` · 卡在「${esc(步名)}」` : ""}
    ${r["说明"] ? `<div>${md(r["说明"])}</div>` : ""}${r["下一步"] ? `<div class="k">下一步:${md(r["下一步"])}</div>` : ""}
    <div class="k">执行状态:${esc(d["执行状态中文"])}${d["停止原因"] ? ` <code>${esc(d["停止原因"])}</code>` : ""}</div></div>`;
}
function 运行卡(d, rid) {
  const 等 = d["在等什么"];
  const 步 = (d["步骤"] || []).length;      // 每一步的列表在「追踪」页(测试追踪);这里只看有没有开始跑
  return `${业务结果块(d)}
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
async function 画_运行记录() {
  $("#tabbody").innerHTML = `<div class="state">加载中…</div>`;
  try {
    const r = await 请求(`${P()}/execution-runs?workflow_id=${encodeURIComponent(图态.wid)}&limit=50`);
    $("#tabbody").innerHTML = r.items.length ? `<table><thead><tr><th>状态</th><th>停止原因</th><th>用的哪版</th>
        <th>谁发起</th><th>开始</th><th>结束</th><th></th></tr></thead><tbody>`
      + r.items.map((x) => `<tr><td>${esc(x["执行状态中文"])}</td><td><code>${esc(x["停止原因"] || "")}</code></td>
          <td class="k">${esc(x["版本"] || "")}</td><td>${esc(x["请求人"] || "")}</td>
          <td class="k">${时间(x["开始"])}</td><td class="k">${时间(x["结束"])}</td>
          <td><a href="#/wfrun/${encodeURIComponent(x.id)}">看详情</a></td></tr>`).join("")
      + `</tbody></table><div class="note">共 ${r.total} 次。停在「等待审批」「等澜绣回执」的是<b>还没结束</b>,不是失败。</div>`
      : 状态("", "还没跑过", "去「测试」页签跑一条。").html;
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
      <td>${esc(v["变更说明"] || "")}</td><td class="k">${时间(v["冻结于"])}<div>${esc(v["冻结人"] || "")}</div></td>
      <td>${生产态}</td>
      <td class="relacts">${v.id ? ["test", "staging", "production"].map((e) =>
          `<button data-pub="${esc(v.id)}" data-env="${e}" ${在.includes(e) ? "disabled" : ""}>发到${环境中文[e]}</button>`).join(" ") : ""}
        ${要审 ? `<div class="k">生产要先审核这一版:<button data-rv="${esc(审["清单id"])}" data-ok="1">审核通过</button>
          <button data-rv="${esc(审["清单id"])}" data-ok="0">驳回</button></div>` : ""}
        ${v.id ? `<button data-vview="${esc(v.id)}">只读查看</button>
          <button data-vname="${esc(v.id)}">${v["名称"] ? "改名字" : "起名字"}</button>
          <button class="danger" data-vdel="${esc(v.id)}" ${在.length ? `disabled title="${esc(在.map((e) => 环境中文[e]).join("、"))}正在跑这一版,不能删"` : ""}>删除</button>` : ""}</td></tr>`;
  }).join("");
  // 当前草稿置顶(10-27 照 Dify 版本历史):它不是一个版本,但人想知道「我现在改的这份」在哪、存没存
  const 草稿行 = `<tr class="draftrow"><td><span class="pill warn">当前草稿</span></td>
      <td class="k">在「搭建」里改的就是它;生成候选版本之后才会出现在下面</td>
      <td class="k">${g.revision != null ? `r${esc(String(g.revision))}` : ""}<div>${esc(g.保存态 || "")}</div></td><td></td>
      <td><a href="#/workflow/${encodeURIComponent(wid)}/${encodeURIComponent("搭建")}">去搭建</a></td></tr>`;
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
  document.querySelectorAll("[data-vname]").forEach((b) => { b.onclick = () => 弹_版本起名(b.dataset.vname); });
  document.querySelectorAll("[data-vdel]").forEach((b) => { b.onclick = () => 做_删版本(b.dataset.vdel); });
  document.querySelectorAll("[data-pub]").forEach((b) => { b.onclick = () => 做_发布工作流(b.dataset.pub, b.dataset.env, 各环境); });
  document.querySelectorAll("[data-rv]").forEach((b) => { b.onclick = () => 做_审核发布(b.dataset.rv, b.dataset.ok === "1"); });
}
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
      v["名称"] = 名 || null; v["标记revision"] = r["标记revision"]; 关弹层(); 提示(名 ? `已改名:${名}` : "已去掉名字"); 画_版本();
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
const 周期说法 = { 日: "每天", 周: "每周一", 月: "每月 1 号" };
const 统计说法 = { 日: "前一天", 周: "上一个自然周(周一到周日)", 月: "上一个自然月" };
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
  const s = d["定时"], 要填 = d["要填"] || [], 固定 = (s && s["固定输入"]) || {};
  const 记录 = ((s && s["记录"]) || []).slice(-5).reverse();
  el.innerHTML = `<h2>定时</h2>
    <div class="sub">${md("到点自动跑**生产那一版**,以打开定时的人的身份跑。同一期只跑一次;关机错过的**只补最近一期**,更早的列在下面,要补就手动发起。")}</div>
    ${!d["生产版本"] ? `<div class="note">${md("这条工作流**还没发布到生产**,定时打不开 —— 先在上面把一版审核后发到生产。")}</div>` : ""}
    <div class="card"><div class="schedform">
      <label>多久跑一次 <select id="sc-c">${["日", "周", "月"].map((p) =>
        `<option value="${p}" ${(s ? s["周期"] : "周") === p ? "selected" : ""}>${周期说法[p]}(统计${统计说法[p]})</option>`).join("")}</select></label>
      <label>几点跑 <input id="sc-t" value="${esc(s ? s["时刻"] : "08:00")}" size="6"> <span class="k">北京时间</span></label>
      ${要填.map((f) => `<label>${esc(f["说明"] || f["字段"])} <input data-fx="${esc(f["字段"])}" value="${esc(固定[f["字段"]] ?? "")}"
        placeholder="每次定时都用这个值"></label>`).join("")}
    </div>
    <div class="k">${s ? (s["开着"] ? `<span class="pill ok">开着</span> 以 ${esc(s["以谁的身份"])} 的身份跑`
        + (s["下次"] ? ` · 下次 ${时间(s["下次"]["时刻"])},统计 ${esc(s["下次"]["统计起"])} ~ ${esc(s["下次"]["统计止"])}` : "")
        : `<span class="pill">关着</span>`) : "还没设过定时。"}</div>
    <button class="pri" id="sc-on" ${d["生产版本"] ? "" : "disabled"}>${s && s["开着"] ? "保存" : "打开定时"}</button>
    ${s && s["开着"] ? `<button id="sc-off">关掉定时</button>` : ""}</div>
    ${记录.length ? `<h3>最近几期</h3><ul class="schedlog">${记录.map((x) => `<li>${期结果(x)}</li>`).join("")}</ul>` : ""}`;
  const 存 = async (开) => {
    const 固定输入 = {};
    el.querySelectorAll("[data-fx]").forEach((i) => { if (i.value.trim()) 固定输入[i.dataset.fx] = i.value.trim(); });
    if (开 && !(await 问一句(s && s["开着"] ? "保存定时?" : "打开定时?",
        `${周期说法[$("#sc-c").value]} ${esc($("#sc-t").value)} 自动跑<b>生产那一版</b>,<b>以你的身份</b>发起 —— 每跑一次就按真实用量花一次钱。`,
        { 确定: s && s["开着"] ? "保存" : "打开", 取消: "先不" }))) return;
    try {
      await 请求(`${P()}/workflows/${encodeURIComponent(wid)}/schedule`, { method: "PUT",
        body: JSON.stringify({ 周期: $("#sc-c").value, 时刻: $("#sc-t").value.trim(), 开着: 开, 固定输入 }) });
      提示(开 ? "定时已保存" : "定时已关掉", 开 ? "到点会自动发起,结果出现在「最近几期」和运行记录里。" : "不会再自动发起。已经发起的运行不受影响。");
    } catch (e) { 报错(e); }
    await 画_定时块(wid);
  };
  $("#sc-on").onclick = () => 存(true);
  if ($("#sc-off")) $("#sc-off").onclick = () => 存(false);
}
async function 页_定时() {
  const 头 = `<div class="crumb">定时</div>
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
        <td>${x["开着"] ? `<span class="pill ok">开着</span>` : `<span class="pill">关着</span>`} ${周期说法[x["周期"]] || esc(x["周期"])} ${esc(x["时刻"])}
          <div class="k">统计${统计说法[x["周期"]] || ""} · 以 ${esc(x["以谁的身份"])} 的身份</div></td>
        <td>${x["生产版本"] ? "v" + esc(String(x["生产版本"]["版本号"])) : `<span class="pill warn">没发布到生产</span>`}</td>
        <td>${x["下次"] ? `${时间(x["下次"]["时刻"])}<div class="k">统计 ${esc(x["下次"]["统计起"])} ~ ${esc(x["下次"]["统计止"])}</div>` : "—"}</td>
        <td>${末 ? 期结果(末) : `<span class="k">还没到过点</span>`}</td></tr>`; }).join("")
    + `</tbody></table>`;
}
async function 做_发布工作流(vid, 环境, 各环境) {
  const v = 图态.版本们.find((x) => x.id === vid) || {};
  if (环境 === "production" && !(await 问一句(`把 ${v["版本"]} 发到生产?`,
      "发出去之后,<b>聊天接管和定时从这一刻起跑这一版</b>。生产只认审核过的那一版;没审过的会先停在「等生产审核」。",
      { 确定: "发到生产", 取消: "先不" }))) return;
  try {
    await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/releases`, { method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ 版本id: vid, 环境, 环境revision: (各环境[环境] || {}).revision ?? undefined }) });
    提示("已发布", `<b>${esc(v["版本"] || "")}</b> 已发到<b>${环境中文[环境]}</b>。${环境 === "production" ? "聊天接管和定时从现在起跑这一版。" : "只影响这个环境,生产不变。"}`);
  } catch (e) {
    const b = e.体 || {};
    if (b.code === "CANNOT_DEPLOY" && 环境 === "production") {
      提示("等生产审核", `这一版还没审核过,没有发到生产。<br>审核入口已经出现在这一行:有生产审核权限的人点「审核通过」后,再点一次「发到生产」。`);
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
      提示(`已把 ${v["版本"]} 复制为草稿(未保存)`, { 撤销: true });
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
    <div class="note"><b>可配置的采集策略(来源开关、正文策略、容量、保留期、告警)还没有做</b> —— 这里不摆开关,免得拧了不算数。
      现在的边界是固定的:采上面五类、模型请求与响应原文在运行记录(traces / spans)那一侧、服务商内部过程拿不到。</div>
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
    <h4>什么时候运行</h4><div>手动(在「测试」或接口里发起),或者打开聊天接管后由聊天站发起。<span class="k">定时触发还没做 —— 不摆一个选了没反应的选项。</span></div>
    <h4>运行上限</h4><div>每次最多调模型 8 次(发起时带的默认值)。<span class="k">超过就停、记「没完整完成」,不会无限调。</span></div>
    <h4>人工核对的截止</h4><div>每个核对步骤自己设(搭建 → 人工核对 → 设置)。到点没人处理,这次运行结束、记「已过期」。</div></div>`;
  $("#st-tk").onclick = async () => {
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
      (g.变量改 || {})[n.id] !== undefined ? ' <span class="pill warn">已编辑</span>' : ""}</button>`).join("")
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
  const 重置 = $("#vi-reset"); if (重置) 重置.onclick = () => { g.变量改 = {}; 画_变量检查(); 提示("已撤掉所有修改,回到上一次运行的值"); };
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

const 单测类型 = { llm: "模型", retrieve: "知识检索", tool: "业务动作" };
function 单测字段(n) {
  return Object.entries((n.config || {}).bindings || {})
    .filter(([, r]) => !(r && (r.source === "constant" || r.source === "system"))).map(([k]) => k);
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
    return `<label class="f">${esc(f)}</label><textarea rows="2" data-st="${esc(f)}">${esc(默)}</textarea>`;
  }).join("");
  return `<div class="stest"><div class="k">单独跑这一步,不从头跑整条流程。${Object.keys(上次入).length ? "下面已填上它上次收到的内容,可以改。" : ""}
      用的是这一步选的模型:演示模型不花钱,真模型按一次调用计费。</div>
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
async function 盯单测(rid, nid) {
  for (let i = 0; i < 40; i++) {
    let d;
    try { d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`); } catch (e) { break; }
    const s = (d["步骤"] || []).find((x) => x["节点"] === nid);
    // 只更新这一步的标记,不覆盖其它步骤上次整条试运行的结果(小图里只有这一步)
    if (s) {
      图态.运行态 = Object.assign({}, 图态.运行态 || {}, { [nid]: { 状态: s["状态"], 错误码: s["错误码"], 分支: s["走的分支"],
        输入: s["输入"], 输出: s["输出"], 原文: !!d["看得到原文"] } });
    }
    const 完 = d["是终态吗"] || d["在等什么"];
    if ($("#st-st") && 图态.选中 === nid) {
      $("#st-st").innerHTML = `${业务结果块(d)}
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
        if ($("#rcmsg")) {
          $("#rcmsg").innerHTML = `<div class="state"><p>
            <code>${esc(r.status || "")}</code>
            ${r["改了吗"] === false ? "（<b>没有改动</b>）" : ""}
            ${md(r.note || r["说明"] || "")}</p></div>`;
        }
        await 页_运行详情(rid);
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
        .then(() => 提示(`已复制 ${态.条目.length} 条(写明了是不是全部)`), (e) => 提示("复制不了:" + e.message));
    };
    $("#rl-dl").onclick = async () => {
      try {
        const 包 = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}/raw-log/export`, { method: "POST",
          body: JSON.stringify({ 节点: 态.筛.节点 || null, 来源: 态.筛.来源 || null, 只看错误: 态.筛.只看错误, 尝试: 态.筛.尝试 }) });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([JSON.stringify(包, null, 1)], { type: "application/json" }));
        a.download = `原始日志-${rid}${是子集 ? "-筛选子集" : ""}.json`; a.click();
        提示(`已下载 ${包["条目"].length} 条(${包["是全部还是子集"]} · ${包["内容"].slice(0, 4)});这次导出记进了审计`);
      } catch (e) { 报错(e); }
    };
    el.querySelectorAll("[data-rlgo]").forEach((b) => {
      b.onclick = () => {
        // L07:回到当时的步骤。当前草稿里已经没有它 → 明说,**不跳到当前同名步骤**
        const id = b.dataset.rlgo, wid = 运行 && 运行["定义来源"] && (运行["定义来源"].id || 运行["定义来源"].workflow_id);
        if (图态 && 图态.wid === wid && 节点(id)) { 图态.选中 = id; location.hash = `#/workflow/${encodeURIComponent(wid)}/搭建`; return; }
        提示(`「${id}」在你现在打开的草稿里没有 —— 这条记录属于当时的定义(定义哈希 ${String((态.回 || {})["定义哈希"] || "").slice(0, 12)}…),不跳到同名的当前步骤`);
      };
    });
  };
  const 跟随 = async () => {
    while (态.跟随 && el.isConnected !== false && $("#rawlog") === el) {
      await new Promise((r) => setTimeout(r, 3000));
      if (!态.跟随) break;
      try { await 取(false); 画(); } catch (e) { 态.跟随 = false; 提示("跟随中断:" + e.message + "(已加载的还在)"); 画(); }
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

async function 页_运行详情(rid) {
  const d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`);
  const 步 = d["步骤"] || [];
  $("#main").innerHTML = `
    <div class="crumb"><a href="#/workflows">工作流</a> / 运行 ${esc(rid)}</div>
    <div class="head"><div><h1>运行详情</h1>
      <div class="sub">定义来源 <code data-raw="原文">${esc(JSON.stringify(d["定义来源"] || {}))}</code></div>
    </div>
      <div>${运行控制按钮(d)}</div>
    </div>
    <div id="rcmsg"></div>
    ${业务结果块(d)}
    ${回复气泡(d)}
    <div class="cards">
      <div class="card"><div class="kpi">${esc(d["执行状态中文"])}</div>
        <div class="k">执行状态 <code>${esc(d["执行状态"])}</code>
          ${d["是终态吗"] ? "· 终态" : "· 还在动"}</div></div>
      <div class="card"><div class="kpi">${esc(d["任务达标"])}</div>
        <div class="k">任务达标状态</div>
        <div class="note" style="margin-top:6px">${md(d["达标说明"])}</div></div>
      <div class="card"><div class="kpi">${esc(d["模式"])}</div>
        <div class="k">execution_mode</div>
        <div class="note" style="margin-top:6px">mock 和真实实现<b>同一个契约</b> ——
          正因为无缝,这个标记才是必需的(§19.4)。</div></div>
      <div class="card"><div class="kpi">${esc(JSON.stringify(d["用量"] || {}))}</div>
        <div class="k">用量</div>
        <div class="note" style="margin-top:6px">费用记成<b>「未知」不是 0</b> ——
          mock 没有真实计价。</div></div>
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
    <div class="crumb"><a href="#/agents">智能体</a> / ${esc(g["名称"])}</div>
    <div class="head"><div><h1>${esc(g["名称"])}</h1>
      <div class="sub">草稿 r${g["草稿"]["revision"]}
        ${g.脏 ? `<span class="stale">有未保存的改动</span>` : ""}</div></div>
      <div><button id="v">校验</button><button id="run">试运行</button>
        <button class="pri" id="freeze">冻结为新版本</button></div></div>
    <div class="filters">${tabs.map((t) =>
      `<button data-tab="${t}" class="${g.Tab === t ? "pri" : ""}">${t}</button>`).join("")}</div>
    <div id="body"></div>
    <div class="footbar"><span id="fb">${報状态(报, g.脏)}</span>
      <span class="grow"></span><button id="save">保存草稿</button></div>`;
  $("#v").onclick = 做_校验agent;
  $("#run").onclick = 做_跑agent;
  $("#freeze").onclick = 做_冻结agent;
  $("#save").onclick = 做_存agent;
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => { agent态.Tab = b.dataset.tab; 画_agent(); };
  });
  画_agent正文();
}

function 報状态(报, 脏) {
  if (脏) return "<b>有未保存的改动</b> —— 保存草稿不影响任何已冻结版本,也不影响生产。";
  if (!报) return "还没校验过 —— <b>客户端看起来没问题不代替服务端校验</b>。";
  return 报["通过"] ? "上次校验:<b>通过</b>"
    : `上次校验:<b>${报["阻断数"]} 条阻断</b> / ${报["警告数"]} 条警告`;
}

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
      <div class="fieldrow"><label>connection_version_id</label>
        <select data-k="connection_version_id">
          <option value="">(没选)</option>
          ${g["可选连接"].map((c) => `<option value="${esc(c.id)}"
            ${cfg.connection_version_id === c.id ? "selected" : ""}>
            ${esc(c["名称"])} · 原生工具调用:${c["原生工具调用"] ? "支持" : "没声明"}
            · ${esc(c["模式"] || "?")}</option>`).join("")}
        </select></div>
      <div class="note">这一栏显示的是<b>探测回来的能力</b>,不是模型叫什么名字。
        规格附录 D.2:<b>不按模型家族名字推断兼容</b> —— 能不能按契约调工具是按型号来的。
        选一条「没声明」的,点校验会当场被挡住。</div>
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
      ${字段("context_policy", "context_policy", cfg.context_policy, "", 3)}
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
      ${字段("limits", "limits", cfg.limits, "", 5)}
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
      await 路由();
      提示("别人刚改过", `${md(e.message)}<br>下一步:${md(e.体?.advice || "看一眼最新内容再改")}`);
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

async function 做_跑agent() {
  if (agent态.脏) await 做_存agent();
  const 输入 = agent态.调试输入 || { products: ["甲", "乙"] };
  try {
    const d = await 请求(`${P()}/agent-runs`, {
      method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ agent_id: agent态.aid, 输入 }),
    });
    agent态.Tab = "调试"; 画_agent();
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 600));
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
  $("#main").innerHTML = `<div class="crumb">编排 /
      <a href="#/tools">工具与能力</a> / 详情</div>
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
      ? `<pre style="margin:4px 0;padding:6px 8px;background:#f7f8fa;
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
        配套关系现在只能在<b>冻结工具组版本</b>时给（那里有成环检查）。</div>`;
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
      ${d["⚠️答不出的"] ? `<div class="note warn">⚠️ <b>这一页答不出一件事</b>：
        ${md(d["⚠️答不出的"])}</div>` : ""}
      ${配套区}
      <div class="note"><b>规格 §8.2 那七个页签，这里做了六个</b>。
        <b>还没做的一个</b>：模型说明那一页（要
        <code>别名 / 适用场景 / 任务示例</code> 三个字段，
        <b>契约里现在没有它们</b> —— 加字段要先定「旧版本那几列为空读成什么」）。
        <br>⚠️ <b>没摆空壳子是有意的</b>：空页签让人以为「这里没东西」，
        而真相是「这里还没做」。</div>`;
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
          ? `<input id="d-purpose" style="width:min(420px,90%)"
              value="${esc(草["用途"] || "")}">`
          : esc(草["用途"] || "—")}</td></tr>
        <tr><td class="k">读写类型</td><td>${能改
          ? `<select id="d-se">${级们.map((x) => `<option value="${esc(x["值"])}"${
              x["值"] === 草["读写类型"] ? " selected" : ""}>${esc(x["中文"])}（${
              esc(x["值"])}）</option>`).join("")}</select>`
          : esc(草["读写类型中文"] || 草["读写类型"] || "—")}</td></tr>
        <tr><td class="k">接入方式</td><td><code>${esc(草["接入方式"] || "—")}</code>
          <span class="k">（接口不收可执行代码，这里也不给改）</span></td></tr>
        <tr><td class="k">draft_revision</td>
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
          <textarea id="f-desc" rows="2" style="width:min(520px,95%)"
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
      ? `<div class="state ${坏 ? "err" : ""}"><p>${md(文)}</p></div>` : "";
  }
}

async function 页_工具目录() {
  $("#main").innerHTML = `<div class="crumb">编排 / 工具与能力</div>
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
          </td><td>${esc(r["用途"] || "—")}</td>
        <td>${r["读写类型"] === "只读" ? `<span class="pill">只读</span>`
              : `<span class="pill warn">${esc(r["读写类型"])}</span>`}</td>
        <td class="k">${esc(r["接入方式"])}</td>
        <td>${r["最新版本"] ? `<span class="pill">${esc(r["最新版本"])}</span>`
              : `<span class="k">还没冻结版本</span>`}</td>
        <td class="k">${esc(r["状态"])}</td></tr>`).join("")
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
      if ($("#tmsg")) {
        $("#tmsg").innerHTML = `<div class="state"><p>注册好了
          <code>${esc(r.id || "")}</code> —— **下一步是冻结一个版本**:
          草稿改不动已经冻结的版本,而引用它的 Agent 认的是版本
          ${md(r.note ? "。" + r.note : "")}</p></div>`;
      }
      await 页_工具目录();
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
  const 头 = `<div class="crumb">人工待办</div>
    <div class="head"><div><h1>人工待办</h1>
      <div class="sub">${md(`不可逆写入要人点头。**列表上没有批准按钮,这是有意的。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/human-requests`); }
  catch (e) { const s = 错误块(e, 页_人工待办); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 状态("", "没有待办",
      "Agent 请求不可逆写入时会在这里出现。").html;
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr>
      <th>要做什么</th><th>状态</th><th>截止</th><th>你能处理吗</th><th></th>
    </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td>${r.risk_note ? md(r.risk_note) : esc(r.kind || r.id)}
          <div class="k">${esc(r.id)}</div>
          ${r["有人能批吗"] === false
            ? `<div class="k"><span class="pill fail">没人能批</span>
                 ${md(r["没人能批的原因"] || "")}</div>` : ""}</td>
        <td><span class="pill ${r.status === "pending" ? "warn"
              : r.status === "approved" ? "ok" : ""}">${esc(r.status)}</span></td>
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
}

/* ── 人工核对(工作流里的 human 节点,2026-10-24)──────────────────────
 * 方案 §5.3 / §7:原文和摘要**并排**,定稿可改,决定只有「通过 / 退回」。
 * 和工具审批那一页分开画:审批要看的是「写哪儿、写什么类型」,核对的活是**对着原文看摘要漏没漏、编没编** ——
 * 原文给形状(「419 字 · 开头……」)的话,审核人只能照着摘要点通过,这一步就成了走过场。
 */
function 画_核对页(hid, d, 头) {
  const 材 = d["核对材料"] || {}, 请 = d["请求"] || {}, 影 = d["影响对象"] || {};
  const 能改 = (d["允许编辑的字段"] || []).includes("定稿");
  // 定稿之外核对人能填的(10-24 录音的回电负责人 / 回电截止、10-25 订单风险的跟踪负责人 / 跟踪截止):
  // 负责人和时间由人填,不让模型猜;**全填了 = 要派,全空 = 不派**,只填一部分不提交。按字段名通用地画,不按流程写死
  const 额外 = (d["允许编辑的字段"] || []).filter((k) => k !== "定稿");
  const 待 = Array.isArray(材["待确认项"]) ? 材["待确认项"] : [];
  $("#main").innerHTML = 头 + `
    <div class="note">${材["客户"] ? `客户 <b>${esc(材["客户"])}</b>` : ""} ${材["通话"] ? ` · 通话 <b>${esc(材["通话"])}</b>` : ""}
      ${影["运行"] ? ` · 来自运行 <a href="#/wfrun/${encodeURIComponent(影["运行"])}">${esc(影["运行"])}</a>` : ""}
      ${请.expires_at ? ` · 截止 ${esc(String(请.expires_at).slice(0, 16).replace("T", " "))}(到点没人处理,这次运行结束、不写任何东西)` : ""}</div>
    <div class="two">
      <div class="card"><h3>原文</h3><pre class="io">${esc(材["原文"] || "(没有原文)")}</pre>
        <div class="k">手机号已打码。核对就是对着这里看:摘要里每一条,原文里找得到客户亲口说的吗?</div></div>
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
        <label class="f">理由(退回必填)</label><textarea id="rv-why" rows="2"></textarea>
        <button class="pri" id="rv-ok">通过</button> <button id="rv-no">退回</button>
        <div id="rv-res"></div>` : `<div class="state err"><h3>你不能处理这条</h3><p>${md(d["为什么"] || "")}</p></div>`}
      </div></div>
    <h2>处理记录</h2>`
    + ((d["决定历史"] || []).length ? `<table><thead><tr><th>谁</th><th>决定</th><th>理由</th></tr></thead><tbody>`
        + d["决定历史"].map((x) => `<tr><td>${esc(x.actor)}</td><td>${x.decision === "approved" ? "通过"
            : x.decision === "rejected" ? "退回" : esc(x.decision)}</td><td>${esc(x.reason || "")}</td></tr>`).join("")
        + `</tbody></table>` : `<div class="k">还没有人处理过。</div>`);
  if (!d["你能处理吗"]) return;
  const 发 = async (决定) => {
    const 理由 = $("#rv-why").value.trim();
    if (决定 === "rejected" && !理由) { $("#rv-why").focus(); $("#rv-res").innerHTML = `<div class="k">退回要写理由 —— 不然发起的人不知道错在哪。</div>`; return; }
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
        : "已退回 —— 这次运行记下理由后结束,什么都不写"}${r["运行"] ? ` · <a href="#/wfrun/${encodeURIComponent(r["运行"].id)}">看这次运行</a>` : ""}</div>`;
      setTimeout(() => 页_待办详情(hid), 1500);
    } catch (e) { const s = 错误块(e, null); $("#rv-res").innerHTML = s.html; }
  };
  $("#rv-ok").onclick = () => 发("approved");
  $("#rv-no").onclick = () => 发("rejected");
}

async function 页_待办详情(hid) {
  const 头 = `<div class="crumb"><a href="#/human">人工待办</a> · 详情</div>
    <div class="head"><div><h1>待办详情</h1>
      <div class="sub">${esc(hid)}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}`); }
  catch (e) { const s = 错误块(e, () => 页_待办详情(hid)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (d["核对材料"]) return 画_核对页(hid, d, 头);
  const 证 = d["证据"] || {};
  const 工 = d["具体工具"];
  $("#main").innerHTML = 头
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
  const 发 = async (决定) => {
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
      res.innerHTML = `<div class="note">${esc(r.decision)} →
        <b>${esc(r["当前状态"])}</b>（rev ${r["新的 revision"]}）<br>
        ${md(r.note || "")}</div>`;
      setTimeout(() => 页_待办详情(hid), 1200);
    } catch (e) { const s = 错误块(e, null); res.innerHTML = s.html; }
  };
  $("#ap").onclick = () => 发("approved");
  $("#rj").onclick = () => 发("rejected");
  $("#info").onclick = () => 发("info_requested");
}

/* ── 评测中心 / 回归验收(M4:/acceptance 重建)────────────────────────
 * ⚠️ **「有分数」不等于「能当结论」。** 规格 §18 要求四个东西同时在场:
 * 候选 + 基线 + 冻结的数据版本 + 记录在案的判据版本。
 * 缺任何一个,跑出来的数**看起来仍然是个分数** —— 而那是这一页的核心危险。 */
async function 页_评测中心() {
  const 头 = `<div class="crumb">评测中心</div>
    <div class="head"><div><h1>回归验收</h1>
      <div class="sub">${md(`改完之后跑一遍,看有没有退步。**有分数 ≠ 能当结论。**`)}</div>
    </div><div><a href="#/compare"><button>实验对比</button></a></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/evaluations`); }
  catch (e) { const s = 错误块(e, 页_评测中心); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 状态("", "还没有评测实验",
      "跑 `tools/seed_evals.py` 可以灌一组示例。").html;
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr>
      <th>候选</th><th>基线</th><th class="num">题</th>
      <th>数据集版本</th><th>判据</th><th>能当结论吗</th></tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td><b>${esc((r.candidate_ref || {})["名"] || r.id)}</b>
          <div class="k">${esc(r.id)}</div></td>
        <td>${r["有基线吗"] ? esc((r.baseline_ref || {})["名"] || "有")
                            : `<span class="pill fail">没有基线</span>`}</td>
        <td class="num">${r["题数"]}</td>
        <td class="k">${esc(String(r.dataset_version_id || "—").slice(-10))}</td>
        <td class="k">${esc(r.scorer_version || "—")}</td>
        <td>${r["能当结论吗"] ? `<span class="pill ok">能</span>`
              : `<span class="pill fail">不能</span>
                 <div class="k">${esc(r["为什么不能当结论"] || "")}</div>`}</td>
      </tr>`).join("")
    + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
}

/* ── 实验对比(M5:/experiments 重建)──────────────────────────────────
 * ⚠️ **先判可比,再给数。** 两轮用了不同的数据集版本或判据版本时,
 * 这里**不显示分数** —— 并排两个不可比的数比不显示糟得多:
 * 读的人会算出一个差值,而那个差值可能全来自题目或评分方式。 */
async function 页_实验对比() {
  const 头 = `<div class="crumb"><a href="#/evals">评测中心</a> · 实验对比</div>
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
    `<option value="${esc(r.id)}">${esc((r.candidate_ref || {})["名"] || r.id)}</option>`).join("");
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
      const 名 = (x) => esc((x.candidate_ref || {})["名"] || x.id);
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
  const 头 = `<div class="crumb">Prompt 管理</div>
    <div class="head"><div><h1>单条试跑</h1>
      <div class="sub">${md(`拿一条真输入试一次。**调试也花钱**,所以要过额度闸。`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let ps;
  try { ps = await 请求(`${P()}/prompts?limit=50`); }
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
      <label class="f">变量(JSON)</label>
      <textarea id="vv" rows="4">{}</textarea>
      <button class="pri" id="go">试跑一次</button>
      <div class="note">${md(`⚠️ **这一次真的会调模型。** 返回的是任务信封(202),
        不是答案 —— 下面显示的是**真实状态**,不是假进度条。`)}</div>
      <div id="步"></div>
    </div>`;
  $("#go").onclick = async () => {
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
        body: JSON.stringify({ prompt_id: $("#pp").value, 变量 }),
      });
      步.innerHTML = `<div class="note">
        派出去了:任务 <code>${esc(r.job_id)}</code>,状态 <b>${esc(r.status)}</b><br>
        ${md("**202 —— 一个模型都还没调完。**"
             + "这是任务信封,不是答案;要看结果去运行记录。")}
        ${r.note ? "<br>" + md(r.note) : ""}</div>
        <a href="#/runs"><button>去运行记录看</button></a>`;
    } catch (e) {
      const s = 错误块(e, null);
      步.innerHTML = s.html;
    }
  };
}

/* ── 调用链(M5:/debug 在管理后台重建)──────────────────────────────
 * ⚠️ **重建不是搬。** 澜绣那一页读的是澜绣自己的 span 表,
 * 这里读的是管理后台自己的 `traces` / `spans` —— 而那两张表
 * 2026-09-28 之前基本是空的,是精排记账和 A1 上报让它们有了真内容。 */
async function 页_调用链() {
  const 头 = `<div class="crumb">运行记录</div>
    <div class="head"><div><h1>调用链</h1>
      <div class="sub">${md(`每一次运行的调用树。**看得到 trace 不等于看得到原文。**`)}</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces?limit=50`); }
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
        <td>${r["成功吗"] ? `<span class="pill ok">${esc(r.end_reason || "完成")}</span>`
                          : `<span class="pill fail">${esc(r.end_reason || "失败")}</span>`}</td>
        <td><button data-tr="${esc(r.id)}">看调用树</button></td>
      </tr>`).join("")
    + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
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
  const 头 = `<div class="crumb"><a href="#/traces">调用链</a> · 调用树</div>
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
    + `<h2>每一步</h2>`
    + (d["步们"] || []).map((s2, i) => `<div class="card">
        <div class="k">${i + 1}. ${esc(s2.stage)}
          ${s2["出错了吗"] ? `<span class="pill fail">出错</span>` : ""}</div>
        <pre data-raw="原文" class="k">${esc(JSON.stringify(
            脱 ? {入: s2["入_形状"], 出: s2["出_形状"], 错: s2["错_形状"]}
               : {入: s2["入"], 出: s2["出"], 错: s2["错"]}, null, 1))}</pre>
      </div>`).join("");
}

/* ── 产出监督(2026-10-10)──────────────────────────────────────────────
 * 用户:报告和 agent 建议「是怎么生成的」要能在这里**看 + 打回**。
 * 产出由澜绣推过来(管理后台不反查澜绣的库);打回只记一条决定,由澜绣拉回去执行。
 * ⚠️ 路由叫 #/outputs 不叫 #/artifacts —— 后者已经是「模型产物」(微调训练那一组)。 */
const _产出状态色 = { "正常": "ok", "已打回待执行": "warn", "已执行": "", "执行失败": "fail" };
let _产出筛 = { 类型: "", 状态: "" };
async function 页_产出监督() {
  const 头 = `<div class="crumb">评测与监督</div>
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
  const 头 = `<div class="crumb"><a href="#/outputs">产出监督</a> · 详情</div>`;
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
  const 头 = `<div class="crumb">评测中心</div>
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
  const 头 = `<div class="crumb">用量与成本</div>
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
         合成一个数之后,补上价目表也算不回来了。`)}</div>`;
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
  const 头 = `<div class="crumb">知识与 RAG</div>
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
  const 头 = `<div class="crumb">知识与 RAG</div>
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
      "先去「加资料」把文件传上来(**传完还要过服务端校验才算能用**)。\n\n"
      + "现有语料是 `tools/ingest_lanxiu.py` 直接灌的(澜绣的业务拍板记录);"
      + "**把上传变成文档版本、再建索引**那几条接口还没做(M2)。",
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
  $("#main").querySelectorAll("[data-try]").forEach((b) => {
    b.onclick = () => { location.hash = "#/retrieval"; };
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
  if (!d.items.length) {
    $("#main").innerHTML = 头2 + 状态("", "还没建过索引",
      "建索引的接口(`POST /knowledge-bases/{id}/index-builds`)**还没做** —— "
      + "现在是直接派 `index_build` 任务建的。\n\n"
      + "⚠️ 没有索引时检索返回空,**而那和「知识库里没有」长得一样**。").html;
    return;
  }
  $("#main").innerHTML = 头2 + `<table><thead><tr>
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

async function 页_召回测试() {
  const 头 = `<div class="crumb">知识与 RAG</div>
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
  let builds = { items: [] };
  try { builds = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(可用[0].id)}/index-builds`); }
  catch (e) { /* 下面会显示「没有可用索引」 */ }
  const 就绪 = builds.items.filter((x) => x.status === "已就绪");
  if (!就绪.find((x) => x.id === 召回态.索引)) 召回态.索引 = 就绪[0] ? 就绪[0].id : null;
  const 方式名 = () => `${召回态.精排 ? "向量 + Claude 精排" : "只走向量"}${召回态.生成 ? " · 生成答案" : ""}`;
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
        <select id="hs-ib">${就绪.map((x) => `<option value="${esc(x.id)}" ${x.id === 召回态.索引 ? "selected" : ""}>${esc(x.id)} · ${esc(x.embedding_model_id || "")}${x["是mock吗"] ? "(mock)" : ""}</option>`).join("")}</select>
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
  const 头 = `<div class="crumb"><a href="#/retrieval">召回测试</a> / 记录详情</div>`;
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
        <div class="k">这一次好不好用?(5 档,点数字)</div>
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
          <td class="k">${esc(JSON.stringify(r["对象"] || {}).slice(0, 60))}</td>
          <td>${r["结果"] === "ok" ? `<span class="pill">ok</span>`
                : `<span class="pill warn">${esc(r["结果"] || "—")}</span>`}</td>
          <td class="k">${esc((r["为什么"] || "—").slice(0, 70))}</td></tr>`).join("")
        + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
    } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
  };
  await 拉("");
  const go = $("#f-go"); if (go) go.onclick = () => 拉($("#f-act").value);
}

async function 页_应用与发布() {
  $("#main").innerHTML = `<div class="crumb">发布 / 应用</div>
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
      <th>生产在跑哪一版</th><th>预发</th><th>测试</th><th>候选</th>
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
          </td></tr>`; }).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        <b>点应用名进详情</b> —— 发布那四步(出清单 / 审核 / 切指针 / 回滚)在那一页。</div>`;
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
  $("#main").innerHTML = `<div class="crumb">发布 / 应用 /
      <a href="#/apps">列表</a></div>
    <div class="head"><div><h1 id="t">应用</h1>
      <div class="sub">${md(`这一页能**做**发布那四步 ——
        出清单 / 审核 / 切指针 / 回滚。`)}</div></div></div>
    <div id="msg"></div>
    <div id="body"><div class="state">加载中…</div></div>`;
  await 画应用详情(aid);
}

function 报(文, 坏) {
  $("#msg").innerHTML = 文
    ? `<div class="state ${坏 ? "err" : ""}"><p>${md(文)}</p></div>` : "";
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
          报(`**${esc(r["环境"])}** 的指针切了:`
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

async function 页_模型与连接() {
  $("#main").innerHTML = `<div class="crumb">设置 / 模型与连接</div>
    <div class="head"><div><h1>模型与连接</h1>
      <div class="sub"><b>密钥只给形状,不给内容</b> ——
        也不做截断:截到前几个字,那几个字仍然是原文。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/model-connections`);
    if (!d["连接"].length) {
      $("#list").innerHTML = 状态("", "还没有模型连接",
        "**用途要分开**(生成 / Embedding / 重排 / 微调推理)—— 共用一条的话,"
        + "换生成模型会顺手把 Embedding 也换掉,而已经建好的索引会全部不可比。").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>用途</th><th>名字</th>
      <th>适配器</th><th>密钥</th><th>探过 capabilities 吗</th><th>状态</th>
      </tr></thead><tbody>`
      + d["连接"].map((r) => {
        const v = (r["配置版本"] || [])[0] || {};
        const k = v["密钥"] || {};
        return `<tr><td><b>${esc(r["用途中文"] || r["用途"])}</b></td>
          <td>${esc(r["名字"] || "—")}</td><td class="k">${esc(r["适配器"])}</td>
          <td>${k["配了吗"]
            ? `<span class="pill">${esc(k["存在哪"])}·${k["长度"]} 字</span>`
            : `<span class="pill warn">没配</span>`}</td>
          <td>${v["探过吗"] ? `<span class="pill">探过了</span>`
            : `<span class="pill warn">还没探过</span>`}</td>
          <td class="k">${esc(r["状态"])}
            ${我的角色 === "admin"
              ? `<br><button data-probe="${esc(r.id)}" class="k">探一下</button>` : ""}
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
      ? `<div class="state ${坏 ? "err" : ""}"><p>${md(文)}</p></div>` : "";
  }
}

function 挂连接事件(d) {
  document.querySelectorAll("[data-fill]").forEach((b) => {
    b.onclick = () => { if ($("#c-ad")) $("#c-ad").value = b.dataset.fill; };
  });
  document.querySelectorAll("[data-probe]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true; 报2("探 capabilities…");
      try {
        const r = await 连接动作.探(b.dataset.probe);
        报2(`探测提交了:${esc(JSON.stringify(r).slice(0, 180))}`);
        await 页_模型与连接();
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
      报2(`建好了 \`${esc(r.id || "")}\` —— **下一步是探一次 capabilities**:`
        + `不探的话「没探过」会在发布那一刻把它挡住`);
      await 页_模型与连接();
    } catch (e) { 报2(闸文(e), true); $("#c-go").disabled = false; }
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
  async 保存(工号, 角色, 专项授权) {
    return await 请求(`${P()}/memberships`,
      { method: "POST",
        body: JSON.stringify({ 工号, 角色, 专项授权: 专项授权 || [] }) });
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
  const 可授权 = d["可授权的能力"] || [];
  const p = 预填 || {};
  const 已有 = new Set(p["专项授权"] || []);
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
    <p>专项授权（<b>只列可授权的那几条</b>）<br>
      ${可授权.map((c, i) => `<label style="display:inline-block;margin-right:10px">
        <input type="checkbox" data-grant="${i}" value="${esc(c)}"${
          已有.has(c) ? " checked" : ""}> ${esc(c)}</label>`).join("")}</p>
    <p><button class="pri" id="m-go">保存</button>
      ${p["工号"] ? `<button id="m-cancel">取消</button>` : ""}</p></div>`;
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
      const r = await 成员动作.保存(uid, $("#m-role").value, 专);
      if ($("#mmsg")) {
        $("#mmsg").innerHTML = `<div class="state"><p>保存了 ——
          <b>实际能做的</b>:${esc(((r["实际能做的"] || []).join("、")) || "—")}
          ${md(r.note ? "。" + r.note : "")}</p></div>`;
      }
      await 页_成员与权限();
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
    $("#list").innerHTML = `<table><thead><tr><th>工号</th><th>角色</th>
      <th>这条生效吗</th><th>专项授权</th><th>实际能做的</th><th>绑的澜绣员工</th><th>改</th>
      </tr></thead><tbody>`
      + d["成员"].map((r) => `<tr>
        <td><b>${esc(r["工号"])}</b></td>
        <td>${esc(r["角色中文"] || r["角色"])}<div class="k">${esc(r["角色"])}</div></td>
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

async function 页_数据集() {
  $("#main").innerHTML = `<div class="crumb">微调 / 数据集</div>
    <div class="head"><div><h1>数据集</h1>
      <div class="sub">这一页回答 <b>能不能导出、卡在哪</b> ——
        而「能导出吗」是<b>现算</b>的,不是存的字段(存的会漂)。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/datasets`);
    if (!d["数据集"].length) {
      $("#list").innerHTML = 状态("", "还没有数据集", d.note || "").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>数据集</th><th>样本</th>
      <th>分档</th><th>冻结过几版</th><th>能导出吗</th></tr></thead><tbody>`
      + d["数据集"].map((r) => `<tr>
        <td><b>${esc(r["名字"])}</b><div class="k">${esc(r.id)}</div></td>
        <td>${r["样本数"]
          ? `<a href="#/samples/${encodeURIComponent(r.id)}">${r["样本数"]}</a>`
          : `<span class="k">0</span>`}</td>
        <td class="k">${esc(Object.entries(r["分档"] || {})
              .map(([k, v]) => `${k} ${v}`).join("、") || "—")}</td>
        <td>${r["冻结过几版"]}</td>
        <td>${r["能导出吗"] ? `<span class="pill">可以</span>`
              : `<span class="pill warn">不行</span>`}
          ${(r["卡在哪"] || []).length
            ? `<div class="k">${md((r["卡在哪"] || [])[0].slice(0, 54))}</div>` : ""}
          ${r["还有一道看内容的闸"]
            ? `<div class="k">⚠️ ${esc(r["还有一道看内容的闸"].slice(0, 54))}</div>` : ""}
        </td></tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
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
  $("#main").innerHTML = `<div class="crumb">评测 /
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
  $("#main").innerHTML = `<div class="crumb">微调 / 训练任务</div>
    <div class="head"><div><h1>训练任务</h1>
      <div class="sub"><b>训练目标和参数更新方式是两个维度</b> ——
        SFT/DPO 是目标,LoRA/全量是更新方式,不是三选一。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/training-jobs`);
    if (!d["任务"].length) {
      $("#list").innerHTML = 状态("", "还没有训练任务",
        "提交训练要 **trainer 角色**(或拿了专项授权的 admin)—— "
        + "而且**幂等键是硬要求**:超时重发一次 = 再烧一遍 GPU。").html;
      return;
    }
    $("#list").innerHTML = `<table><thead><tr><th>任务</th><th>状态</th>
      <th>基座</th><th>训练目标</th><th>参数更新方式</th><th>是 mock 跑的吗</th>
      </tr></thead><tbody>`
      + d["任务"].map((r) => `<tr>
        <td class="k">${esc(r.id)}</td>
        <td>${esc(r.status)}${r["请求取消了吗"]
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
      b.disabled = true;
      if ($("#amsg")) $("#amsg").innerHTML = `<div class="state"><p>部署中…</p></div>`;
      try {
        const r = await 产物动作.部署(aid, sel ? sel.value : "");
        if ($("#amsg")) {
          $("#amsg").innerHTML = `<div class="state"><p>部署提交了:
            ${esc(JSON.stringify(r).slice(0, 220))}</p></div>`;
        }
        await 页_模型产物();
      } catch (e) {
        if ($("#amsg")) $("#amsg").innerHTML = 错误块(e, null).html;
        b.disabled = false;
      }
    };
  });
}

async function 页_模型产物() {
  $("#main").innerHTML = `<div class="crumb">微调 / 模型产物</div>
    <div class="head"><div><h1>模型产物</h1>
      <div class="sub"><b>训练完成只代表得到产物</b> ——
        有产物 → 产物可用(校验过) → 在服务用户,是三件不同的事。</div></div></div>
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
            ? `<select data-env="${esc(r.id)}">${环境们.map((e) =>
                `<option>${esc(e)}</option>`).join("")}</select>
               <button data-dep="${esc(r.id)}">部署</button>`
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
    if (h === "#/human") return await 页_人工待办();
    if (h.startsWith("#/human/")) return await 页_待办详情(decodeURIComponent(h.slice(8)));
    if (h === "#/evals") return await 页_评测中心();
    if (h === "#/compare") return await 页_实验对比();
    if (h === "#/tryout") return await 页_单条试跑();
    if (h === "#/traces") return await 页_调用链();
    if (h.startsWith("#/trace/")) return await 页_调用树(decodeURIComponent(h.slice(8)));
    if (h === "#/health") return await 页_智能体健康();
    if (h === "#/outputs") return await 页_产出监督();
    if (h.startsWith("#/output/")) return await 页_产出详情(decodeURIComponent(h.slice(9)));
    if (h === "#/runs") return await 页_运行记录();
    if (h === "#/schedules") return await 页_定时();
    if (h.startsWith("#/workflow/")) return await 页_画布(decodeURIComponent(h.slice(11)));
    if (h.startsWith("#/wfrun/")) return await 页_运行详情(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/agent/")) return await 页_agent配置(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/tool/")) return await 页_工具详情(decodeURIComponent(h.slice(7)));
    if (h === "#/usage") return await 页_用量与成本();
    if (h === "#/uploads") return await 页_加资料();
    if (h === "#/kb") return await 页_知识库();
    // ⚠️ `#/chunks/` 和 `#/chunk/` 不冲突(第 8 个字符一个是 s 一个是 /),
    // 但更长的前缀写在前面 —— 下一个人加 `#/chunkset/` 时就不会踩。
    if (h.startsWith("#/chunks/")) return await 页_切片列表(decodeURIComponent(h.slice(9)));
    if (h.startsWith("#/chunk/")) return await 页_切片详情(decodeURIComponent(h.slice(8)));
    if (h.startsWith("#/kb/")) return await 页_索引构建(decodeURIComponent(h.slice(5)));
    if (h === "#/retrieval") return await 页_召回测试();
    // ⚠️ 带参的写在前面(`#/rrun/` 比 `#/rruns` 长,但两者第 7 个字符不同,
    // 不会互相吃掉)—— 顺序照 `#/chunks/` 那段的理由。
    if (h.startsWith("#/rrun/")) return await 页_试跑详情(decodeURIComponent(h.slice(7)));
    if (h === "#/rruns") return await 页_召回测试();   // 旧地址(检索试跑记录)并进了召回测试
    if (h === "#/audit") return await 页_审计记录();
    if (h.startsWith("#/app/")) return await 页_应用详情(decodeURIComponent(h.slice(6)));
    if (h === "#/members") return await 页_成员与权限();
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
