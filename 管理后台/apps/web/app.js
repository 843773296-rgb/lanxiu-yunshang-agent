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
async function 请求(path, opt = {}) {
  const h = Object.assign({ "X-Dev-User": 我 }, opt.headers || {});
  if (opt.body) h["content-type"] = "application/json";
  const r = await fetch(path, Object.assign({}, opt, { headers: h }));
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
const 导航 = [
  ["#/workbench", "工作台", true],
  ["#/apps", "应用与发布", true],
  ["#/conns", "模型与连接", true],
  ["#/prompts", "Prompt 管理", true],
  ["#/tryout", "单条试跑", true, true],
  ["grp", "编排"],
  ["#/workflows", "工作流 Workflow", true, true],
  ["#/agents", "智能体 Agent", true, true],
  ["#/tools", "工具与能力", true, true],
  ["#/human", "人工待办", true, true],
  ["grp", "知识与 RAG"],
  ["#/uploads", "加资料", true, true],
  ["#/kb", "知识库", true, true],
  ["#/retrieval", "检索实验室", true, true],
  ["#/datasets", "数据集", true],
  ["grp", "微调训练"],
  ["#/training", "训练任务", true, true],
  ["#/artifacts", "模型产物", true, true],
  ["#/health", "智能体健康", true, true],
  ["#/evals", "评测中心", true],
  ["#/compare", "实验对比", true, true],
  ["#/runs", "运行记录", true],
  ["#/traces", "调用链", true, true],
  ["#/usage", "用量与成本", true],
  ["grp", "设置"],
  ["#/members", "成员与权限", true, true],
  ["#/audit", "审计记录", true, true],
];
function 画侧栏() {
  const cur = location.hash || "#/workbench";
  $("#side").innerHTML = 导航.map((x) => {
    if (x[0] === "grp") return `<div class="grp">${esc(x[1])}</div>`;
    const [href, 名, 做了, 子] = x;
    const cls = [做了 ? "" : "todo", 子 ? "sub" : "", href === cur ? "on" : ""]
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
    $("#env").textContent = h.env;
    $("#env").className = "envtag" + (h.env === "production" ? " prod" : "");
    if (h.演示模式) {
      // ⚠️ 2026-09-29 用户要求**去掉那条占满一行的黄条**。
      //
      // 规格第 3 条(实施必须遵守)写的是「演示模式……和**醒目标记**」,
      // 所以这里不是把标记删干净,而是**换了个不占一行的地方**:
      // 顶栏那个环境标签后面挂一句话,鼠标停上去有全文。
      //
      // ⚠️ **接口里那个标记一个字没动**(`/api/healthz` 的 `演示模式` /
      // `演示说明`),`test_api_flow` 那条断言验的正是它 ——
      // 所以那条判据仍然验着真东西,没有变成一条守着空气的绿检查。
      // > **把界面上的提示删掉、而判据还在绿着,比两个都删掉更糟** ——
      // > 它让人以为还有人在看着。
      document.body.classList.add("demo");
      const t = $("#env");
      if (t) {
        t.classList.add("demo-env");
        t.title = "演示模式:" + (h.演示说明 || "").replace(/\*\*/g, "");
        t.textContent = h.env + " · 演示";
      }
    }
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
      <div class="sub">先知道哪里需要处理。每张卡都写清它**算的是什么范围、分母是什么、数据从哪来** ——
        一个没有分母的比率没法判断它可不可信。</div>
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
      + `<div class="note warn">**「未知」不是 0。** 费用未知是因为 mock 适配器没有真实计价;
         质量分未知是因为还没有评测覆盖 —— 显示 0 会被读成「质量很差」,而真相是「没测过」。</div>`;
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
      <div class="sub">「最新保存版本」和「生产引用版本」**并排显示** ——
        避免以为保存就上线了。生产用哪一版由**发布清单 + 环境指针**决定,不是「最新的那个」。</div>
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
    if (d.next_cursor) $("#more").onclick = () => alert("翻页还没接 —— 游标已经从服务端给了");
  };
  const 新建 = async () => {
    const key = prompt("给它一个稳定标识(项目内唯一,创建后不随意改):");
    if (!key) return;
    try {
      await 请求(`${P()}/prompts`, {
        method: "POST",
        body: JSON.stringify({ key, 用途: "", 标签: [], system: "", user: "" }),
      });
      画();
    } catch (e) {
      const b = e.体 || {};
      alert(`没建成:${b.message || e.message}\n\n下一步:${b.advice || "(服务端没给建议)"}`);
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
        <br>**保存草稿不会影响任何已保存版本,也不影响生产。**</div>
    </div></div>

    <div class="split">
      <div class="card">
        <label class="f">用途 / 面向谁 / 完成标准</label>
        <textarea class="t" id="e-用途" placeholder="比如:把文章整理成结论、依据、待核实事项">${esc(m.用途 || "")}</textarea>

        <label class="f">系统指令</label>
        <textarea class="t mono" id="e-system" rows="6">${esc(m.system || "")}</textarea>

        <label class="f">用户模板　<span style="color:var(--ink3)">变量写成 <code>{{名称}}</code></span></label>
        <textarea class="t mono" id="e-user" rows="6">${esc(m.user || "")}</textarea>

        <label class="f">输入变量</label>
        <div id="vars"></div>
        <div class="note">**定义变量不等于已经取得数据。** 每个变量都要说清来源
          (用户输入 / 上一步结果 / 检索上下文 / 受控系统字段)—— 来源没绑上,
          它在运行时就是空的。</div>

        <label class="f">输出要求</label>
        <pre class="io" id="e-out">${esc(JSON.stringify(出要, null, 2))}</pre>

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
          <div class="note warn">当前是 **mock 适配器** —— 它返回的是编出来的回答,
            **不许计入真实评测或发布**。接真实连接后这里会列出该连接**实际支持**的参数
            (不支持的参数会返回明确错误,不会被静默忽略)。</div>
          <label class="f">测试输入　<span style="color:var(--ink3)">和模板独立保存,运行结果不会覆盖模板</span></label>
          <div id="testvars"></div>
          <div class="btns" style="margin-top:10px">
            <button class="pri" id="b-run">运行测试</button>
            <span class="msg" id="runmsg" style="font-size:12.5px;color:var(--ink2)"></span>
          </div>
          <div class="note">期望答案放在**独立的评分区域**,不会自动传给被测模型 ——
            否则等于把答案给了考生。</div>
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
      : `<div class="note">还没定义变量。模板里写了 <code>{{x}}</code> 但没定义的话,
          「保存为新版本」会被拦住 —— 那不是刁难:**没定义来源的变量在运行时是空的**。</div>`;
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

  $("#b-cancel").onclick = () => {
    // **未保存离开时提示**(§5.2)
    if (脏 && !confirm("有未保存的改动,离开会丢掉。确定?")) return;
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
    if (脏 && !confirm("有未保存的草稿改动。正式版本是从**草稿**建的 —— 先保存草稿再存版本?")) return;
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
          <pre class="io">${esc(JSON.stringify(s.实际发送, null, 2))}</pre>
          ${果.看得到原文 ? "" : `<div class="note">**默认脱敏。** 看原文要
            「查看敏感输入/独立测试答案」专项权限 —— 换成 U004 能看到差别。</div>`}
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
      <div class="note">跑完可以「加入问题集」「保存为评测样本」—— 新样本**先进待审核**,
        避免把错误答案当成真值。(这两个按钮还没实现)</div>`;
  }
}

/* ── 运行记录(占位:列表已有接口,详情页还没做)────────────────── */
async function 页_运行记录() {
  $("#main").innerHTML = `<div class="crumb">运行记录</div>
    <div class="head"><div><h1>运行记录</h1>
      <div class="sub">每次请求实际经过了哪些阶段、收到什么、返回什么。</div></div></div>`
    + 状态("", "这一页还没实现",
        "接口已经有了(`GET /traces`、`GET /traces/{id}`,原文按**字段级权限**返回),"
        + "页面还没做。**保留入口是有意的** —— 规格里有这一页。\n\n"
        + "现在能看到 trace 的地方:Prompt 详情里跑一次测试,下方会展开阶段、用量和 Trace 号。",
        { 文: "去 Prompt 管理", 做: () => { location.hash = "#/prompts"; } }).html;
  const s = $("#st-act"); if (s) s.onclick = () => { location.hash = "#/prompts"; };
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
async function 页_工作流列表() {
  $("#main").innerHTML = `<div class="crumb">编排 / 工作流</div>
    <div class="head"><div><h1>工作流</h1>
      <div class="sub">按预设路径调度的流程。<b>能画出流程图不等于能执行流程</b> ——
        这里每张图都要过服务端校验才能冻结版本。</div></div>
      <div><button class="pri" id="new">新建工作流</button></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  $("#new").onclick = 弹_新建工作流;
  try {
    const d = await 请求(`${P()}/workflows`);
    if (!d.items.length) {
      const s = 状态("", "还没有工作流",
        "**首次空态**:新建一个,或者用「文本处理」模板起一张最小图"
        + "(开始 → LLM → 结束)。\n\n模板**只预填草稿** —— 它不调模型、不绑生产环境。",
        { 文: "新建工作流", 做: 弹_新建工作流 });
      $("#list").innerHTML = s.html; s.挂(); return;
    }
    $("#list").innerHTML = `<table><thead><tr>
      <th>名称</th><th>用途</th><th>负责人</th>
      <th>最新冻结版本</th><th>生产引用版本</th><th>校验状态</th>
      <th>更新时间</th><th></th></tr></thead><tbody>`
      + d.items.map((r) => `<tr>
        <td><a href="#/workflow/${encodeURIComponent(r.id)}">${esc(r["名称"])}</a>
            <div class="k">草稿 r${esc(r["草稿 revision"])}</div></td>
        <td>${esc(r["用途"] || "—")}</td><td>${esc(r["负责人"] || "—")}</td>
        <td>${r["最新冻结版本"] ? `<span class="pill">${esc(r["最新冻结版本"])}</span>`
              : `<span class="k">还没冻结过</span>`}</td>
        <td><span class="stale" title="${esc(r["生产引用说明"])}">还没接</span></td>
        <td>${r["校验状态"] === "通过" ? `<span class="pill ok">通过</span>`
              : `<span class="pill warn">${esc(r["校验状态"])}</span>`}</td>
        <td class="k">${esc((r["更新时间"] || "").slice(0, 16).replace("T", " "))}</td>
        <td><a href="#/workflow/${encodeURIComponent(r.id)}">编辑</a></td>
      </tr>`).join("") + `</tbody></table>
      <div class="note">共 ${d.total} 条。<b>「生产引用版本」这一栏写的是「还没接」,
        不是「—」</b> —— 发布清单还没扩展到 Workflow(规格 §15.3),
        而一个「—」会被读成「线上没在用」。</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 弹_新建工作流() {
  const 名 = prompt("工作流名称(名称不等于执行 ID —— 改名不影响任何引用):");
  if (!名) return;
  const 模板 = confirm("用「文本处理」模板起一张最小图(开始 → LLM → 结束)?\n\n"
    + "取消 = 空白(只有开始和结束两个节点)。\n\n"
    + "规格 §4.2 还列了「RAG 问答」「受控调研」两个模板,那两个还没做 ——"
    + "所以这里不摆一个选了没反应的选项。") ? "文本处理" : "空白";
  请求(`${P()}/workflows`, { method: "POST", body: JSON.stringify({ 名称: 名, 模板 }) })
    .then((d) => { location.hash = `#/workflow/${encodeURIComponent(d.id)}`; })
    .catch((e) => alert(`${e.体?.code || "出错"}:${e.message}\n\n下一步:${e.体?.advice || "—"}`));
}

/* ── 画布 ─────────────────────────────────────────────────────── */
let 图态 = null;   // { wid, 定义, 布局, revision, 选中, 报告, 脏 }

async function 页_画布(wid) {
  const d = await 请求(`${P()}/workflows/${encodeURIComponent(wid)}`);
  图态 = { wid, 名称: d["名称"], 定义: d["草稿"]["定义"] || { nodes: [], edges: [] },
           布局: d["草稿"]["布局"] || {}, revision: d["草稿"]["revision"],
           节点库: d["节点库"], 版本们: d["版本们"], 选中: null,
           报告: d["草稿"]["上次校验报告"], 脏: false, 底Tab: "问题", 事件: [] };
  画_画布();
}

function 画_画布() {
  const g = 图态;
  $("#main").innerHTML = `
    <div class="crumb"><a href="#/workflows">工作流</a> / ${esc(g.名称)}</div>
    <div class="head"><div><h1>${esc(g.名称)}</h1>
      <div class="sub">草稿 r${g.revision}
        <span id="dirty" class="stale" style="display:${g.脏 ? "" : "none"}">有未保存的改动</span>
      </div></div>
      <div>
        <button id="v">校验</button>
        <button id="run">试运行</button>
        <button class="pri" id="freeze">冻结为新版本</button>
      </div></div>
    <div class="wfwrap">
      <div class="wflib" id="lib"></div>
      <div class="wfcanvas" id="cv" tabindex="0"></div>
      <div class="wfpanel" id="pn"></div>
    </div>
    <div class="wfbottom">
      <div class="tabs">
        <button data-t="问题" class="${g.底Tab === "问题" ? "on" : ""}">校验问题</button>
        <button data-t="事件" class="${g.底Tab === "事件" ? "on" : ""}">试运行事件</button>
        <button data-t="版本" class="${g.底Tab === "版本" ? "on" : ""}">版本</button>
      </div>
      <div class="body" id="bt"></div>
    </div>
    <div class="footbar"><span id="fb"></span>
      <span class="grow"></span>
      <button id="save">保存草稿</button></div>`;
  $("#v").onclick = 做_校验;
  $("#run").onclick = 做_试运行;
  $("#freeze").onclick = 做_冻结;
  $("#save").onclick = 做_存草稿;
  document.querySelectorAll(".wfbottom .tabs button").forEach((b) => {
    b.onclick = () => { 图态.底Tab = b.dataset.t; 画_底部(); 
      document.querySelectorAll(".wfbottom .tabs button").forEach((x) =>
        x.classList.toggle("on", x.dataset.t === 图态.底Tab)); };
  });
  画_节点库(); 画_图(); 画_面板(); 画_底部(); 画_底栏();
}

function 画_底栏() {
  const g = 图态, r = g.报告;
  $("#fb").innerHTML = g.脏
    ? "<b>有未保存的改动</b> —— 保存草稿不会影响任何已冻结版本,也不影响生产。"
    : (r ? (r["通过"] ? "上次校验:<b>通过</b>" 
            : `上次校验:<b>${r["阻断数"]} 条阻断</b> / ${r["警告数"]} 条警告`)
         : "还没校验过 —— <b>客户端看起来没问题不代替服务端校验</b>(§5.3)");
}

function 画_节点库() {
  const 分组 = [["输入/输出", ["start", "end"]], ["模型/检索", ["llm", "retrieve"]],
               ["工具/控制流", ["tool", "condition", "transform", "merge"]],
               ["Agent/人工", ["agent", "human"]],
               ["还没实现", ["parallel", "loop", "foreach", "subworkflow"]]];
  const 按名 = {}; 图态.节点库.forEach((n) => { 按名[n["名"]] = n; });
  $("#lib").innerHTML = `<div class="k">从这里加节点。<b>每个都有「加入」按钮</b> ——
      拖拽不是唯一操作方法(§3.3)。</div>`
    + 分组.map(([标, 们]) => `<h4>${esc(标)}</h4>` + 们.map((k) => {
        const n = 按名[k]; if (!n) return "";
        return `<div class="nd ${n["可用"] ? "" : "off"}" title="${esc(n["说明"])}">
          <span>${esc(n["中文"])}</span>
          ${n["可用"] ? `<button data-add="${k}">加入</button>`
                      : `<span class="k">未实现</span>`}</div>`;
      }).join("")).join("")
    + `<div class="note">标「未实现」的四个<b>登记了但执行器还没做</b>(§6.1)——
        校验器会当场挡住用了它们的图。<b>不摆一个点了没反应的按钮。</b></div>`;
  $("#lib").querySelectorAll("[data-add]").forEach((b) => {
    b.onclick = () => 加节点(b.dataset.add);
  });
}

function 加节点(类型) {
  const g = 图态;
  let i = 1, id;
  do { id = `${类型}_${i++}`; } while (g.定义.nodes.some((n) => n.id === id));
  const 默认配置 = { start: { input_schema: { type: "object", properties: {}, required: [] } },
                    end: { output_schema: { type: "object", properties: {}, required: [] }, bindings: {} },
                    condition: { branches: [], else_policy: "fail" },
                    merge: { candidates: [], output_field: "out" },
                    transform: { operations: [], output_schema: { type: "object" } } }[类型] || {};
  g.定义.nodes.push({ id, type: 类型, config: JSON.parse(JSON.stringify(默认配置)) });
  const 已 = Object.values(g.布局);
  g.布局[id] = { x: 40 + (已.length % 4) * 200, y: 40 + Math.floor(已.length / 4) * 110 };
  g.选中 = id; g.脏 = true; 画_图(); 画_面板(); 画_底栏();
  $("#dirty").style.display = "";
}

function 画_图() {
  const g = 图态, 坏 = {};
  (g.报告?.问题 || []).forEach((p) => { if (p.node_id && p["级别"] === "blocking") 坏[p.node_id] = true; });
  const 按名 = {}; g.节点库.forEach((n) => { 按名[n["名"]] = n; });
  const 位 = (id) => g.布局[id] || { x: 20, y: 20 };
  const W = 176, H = 62;
  const 线 = (g.定义.edges || []).map((e) => {
    const a = 位(e.source), b = 位(e.target);
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
    const mx = (x1 + x2) / 2;
    const 标 = e.port === "branch" ? (e.branch_key || "else")
             : (e.port === "error" ? "失败" : "");
    return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"
              fill="none" stroke="${e.port === "error" ? "#f53f3f" : "#86909c"}"
              stroke-width="1.5" stroke-dasharray="${e.port === "error" ? "4 3" : "0"}"/>`
      + (标 ? `<text x="${mx}" y="${(y1 + y2) / 2 - 4}" font-size="11"
                 fill="#4e5969" text-anchor="middle">${esc(标)}</text>` : "");
  }).join("");
  const 宽 = Math.max(720, ...g.定义.nodes.map((n) => 位(n.id).x + W + 40));
  const 高 = Math.max(440, ...g.定义.nodes.map((n) => 位(n.id).y + H + 40));
  $("#cv").innerHTML = `<svg width="${宽}" height="${高}">${线}</svg>`
    + g.定义.nodes.map((n) => {
        const p = 位(n.id), 元 = 按名[n.type];
        const 缺 = (元?.["必填"] || []).filter((f) => {
          const v = (n.config || {})[f];
          return v === undefined || v === null || v === "" ||
                 (typeof v === "object" && !Object.keys(v).length);
        });
        return `<div class="wfnode ${g.选中 === n.id ? "sel" : ""} ${坏[n.id] ? "bad" : ""}"
          style="left:${p.x}px;top:${p.y}px" data-id="${esc(n.id)}" tabindex="0"
          role="button" aria-label="${esc((元?.["中文"] || n.type) + " 节点 " + n.id
            + (缺.length ? ",缺 " + 缺.length + " 项必填配置" : ""))}">
          <div class="t">${esc(元?.["中文"] || n.type)}</div>
          <div class="k">${esc(n.id)}</div>
          ${缺.length ? `<div class="miss">缺 ${缺.length} 项必填:${esc(缺.join(", "))}</div>` : ""}
        </div>`;
      }).join("");
  $("#cv").querySelectorAll(".wfnode").forEach((el) => {
    el.onclick = () => { 图态.选中 = el.dataset.id; 画_图(); 画_面板(); };
    el.onfocus = () => { 图态.选中 = el.dataset.id; 画_面板(); };
    // **键盘挪位置**:方向键 8px 一步,Shift 24px。拖拽只是另一条路。
    el.onkeydown = (ev) => {
      const 步 = ev.shiftKey ? 24 : 8;
      const d = { ArrowLeft: [-步, 0], ArrowRight: [步, 0],
                  ArrowUp: [0, -步], ArrowDown: [0, 步] }[ev.key];
      if (!d) return;
      ev.preventDefault();
      const p = 图态.布局[el.dataset.id] || { x: 20, y: 20 };
      图态.布局[el.dataset.id] = { x: Math.max(0, p.x + d[0]), y: Math.max(0, p.y + d[1]) };
      图态.脏 = true; 画_图(); 画_面板(); 画_底栏();
      const n = $(`.wfnode[data-id="${CSS.escape(el.dataset.id)}"]`); if (n) n.focus();
    };
    // 拖:按下移动。**它是可选路径,不是唯一路径。**
    el.onmousedown = (ev) => {
      if (ev.target.tagName === "BUTTON") return;
      const id = el.dataset.id, 起 = 图态.布局[id] || { x: 20, y: 20 };
      const x0 = ev.clientX, y0 = ev.clientY;
      const 动 = (m) => {
        图态.布局[id] = { x: Math.max(0, 起.x + m.clientX - x0),
                        y: Math.max(0, 起.y + m.clientY - y0) };
        el.style.left = 图态.布局[id].x + "px"; el.style.top = 图态.布局[id].y + "px";
      };
      const 停 = () => {
        document.removeEventListener("mousemove", 动);
        document.removeEventListener("mouseup", 停);
        图态.脏 = true; 画_图(); 画_面板(); 画_底栏();
      };
      document.addEventListener("mousemove", 动);
      document.addEventListener("mouseup", 停);
    };
  });
}

function 画_面板() {
  const g = 图态;
  if (!g.选中) {
    $("#pn").innerHTML = `<div class="k">选一个节点看它的配置。</div>
      <div class="note">配置字段是<b>登记过的那些</b>(§16.5:节点 Schema 由契约注册表
        声明,不接收任意自由字段)—— 一个从来没被读过的配置项,
        和一个坏了的配置项,在界面上长得一模一样。</div>`;
    return;
  }
  const n = g.定义.nodes.find((x) => x.id === g.选中);
  if (!n) { g.选中 = null; return 画_面板(); }
  const 元 = g.节点库.find((x) => x["名"] === n.type) || {};
  const p = g.布局[n.id] || { x: 0, y: 0 };
  const 问 = (g.报告?.问题 || []).filter((q) => q.node_id === n.id);
  $("#pn").innerHTML = `
    <h3 style="margin:0 0 4px">${esc(元["中文"] || n.type)}</h3>
    <div class="k">node_id <code>${esc(n.id)}</code> —— <b>改名不会改它</b>(§5.2)</div>
    ${问.length ? `<div class="err" style="margin:8px 0;padding:8px;font-size:12px">`
      + 问.map((q) => `<div><b>${esc(q.code)}</b> ${md(q["消息"])}<br>
          <span class="k">怎么改:${md(q["建议"])}</span></div>`).join("<hr>") + `</div>` : ""}
    <h4>位置</h4>
    <div class="fieldrow"><label>X</label>
      <input type="number" id="px" value="${p.x}" step="8"></div>
    <div class="fieldrow"><label>Y</label>
      <input type="number" id="py" value="${p.y}" step="8"></div>
    <div class="k">坐标<b>不进逻辑哈希</b>(附录 A-9)—— 挪位置不算改执行逻辑。</div>
    <h4>配置(${(元["必填"] || []).length} 项必填)</h4>
    ${(元["配置"] || []).map((f) => {
      const v = (n.config || {})[f];
      const 必 = (元["必填"] || []).includes(f);
      const 是对象 = v !== null && typeof v === "object";
      return `<div class="fieldrow"><label title="${必 ? "必填" : "可选"}">
          ${esc(f)}${必 ? " <b style='color:#f53f3f'>*</b>" : ""}</label>
        <textarea data-f="${esc(f)}" rows="${是对象 ? 3 : 1}"
          placeholder="${必 ? "必填" : "可空"}">${esc(是对象
            ? JSON.stringify(v) : (v ?? ""))}</textarea></div>`;
    }).join("")}
    ${(元["不适用"] || []).length ? `<div class="note"><b>这个节点用不上</b>
      ${esc((元["不适用"] || []).join("、"))} —— 界面上不显示它们。
      规格 §6:<b>不能出现全节点通用却不生效的设置</b>。</div>` : ""}
    <div class="note">${md(元["说明"] || "")}</div>`;
  const 存位 = () => {
    图态.布局[n.id] = { x: +$("#px").value || 0, y: +$("#py").value || 0 };
    图态.脏 = true; 画_图(); 画_底栏();
    const el = $(`.wfnode[data-id="${CSS.escape(n.id)}"]`); if (el) el.focus();
  };
  $("#px").onchange = 存位; $("#py").onchange = 存位;
  $("#pn").querySelectorAll("[data-f]").forEach((t) => {
    t.onchange = () => {
      const f = t.dataset.f, s = t.value.trim();
      n.config = n.config || {};
      if (!s) { delete n.config[f]; }
      else if (s[0] === "{" || s[0] === "[") {
        try { n.config[f] = JSON.parse(s); }
        catch (e) { alert(`${f} 不是合法 JSON:${e.message}\n\n没有保存这一项 —— ` +
          `一个存进去的坏 JSON 会在冻结版本的时候才炸,而那时候离这里很远。`); return; }
      } else { n.config[f] = s; }
      图态.脏 = true; 画_图(); 画_底栏();
    };
  });
}

function 画_底部() {
  const g = 图态;
  if (g.底Tab === "版本") {
    $("#bt").innerHTML = g.版本们.length
      ? `<table><thead><tr><th>版本</th><th>逻辑哈希</th><th>变更说明</th>
           <th>冻结于</th><th>冻结人</th></tr></thead><tbody>`
        + g.版本们.map((v) => `<tr><td><span class="pill">${esc(v["版本"])}</span></td>
            <td><code>${esc(v["逻辑哈希"])}</code></td><td>${esc(v["变更说明"] || "")}</td>
            <td class="k">${esc((v["冻结于"] || "").slice(0, 16).replace("T", " "))}</td>
            <td class="k">${esc(v["冻结人"] || "")}</td></tr>`).join("")
        + `</tbody></table><div class="note">冻结了<b>不等于发布了</b> ——
            生产指针没有任何变化(§15.6)。</div>`
      : `<div class="k">还没冻结过版本。</div>`;
    return;
  }
  if (g.底Tab === "事件") {
    $("#bt").innerHTML = g.事件.length
      ? g.事件.map((e) => `<div style="font-size:12px">
          <span class="k">${esc(String(e.seq).padStart(2, "0"))}</span>
          <code>${esc(e["类型"])}</code>
          <span class="k">${esc(JSON.stringify(e["载荷"] || {}).slice(0, 120))}</span></div>`).join("")
      : `<div class="k">还没试运行过。<b>点「试运行」会返回 202 排队中</b> ——
          一个模型都还没调,要等 Worker 捞到才真跑。</div>`;
    return;
  }
  const r = g.报告;
  if (!r) {
    $("#bt").innerHTML = `<div class="k">还没校验过。<b>客户端看起来没问题不代替服务端
      校验通过</b>(§5.3)—— 点右上「校验」。</div>`;
    return;
  }
  if (!r["问题"].length) {
    $("#bt").innerHTML = `<div class="k">✅ 没有问题。<b>但服务端校验过了也只说明
      定义合法</b> —— 不说明模型答得对,也不说明外部服务可用(附录 A-1)。</div>`;
    return;
  }
  $("#bt").innerHTML = r["问题"].map((p, i) => `
    <button class="issue ${p["级别"] === "blocking" ? "b" : "w"}" data-i="${i}">
      <span class="c">${esc(p.code)}</span>
      ${p.node_id ? ` · <b>${esc(p.node_id)}</b>` : ""}
      ${p.field_path ? ` · <span class="c">${esc(p.field_path)}</span>` : ""}
      <br>${md(p["消息"])}<br><span class="k">怎么改:${md(p["建议"])}</span>
    </button>`).join("")
    + `<div class="note"><b>点一条能定位到节点</b>(§5.2:错误内容要可修复)。</div>`;
  $("#bt").querySelectorAll(".issue").forEach((b) => {
    b.onclick = () => {
      const p = r["问题"][+b.dataset.i];
      if (!p.node_id) return;
      图态.选中 = p.node_id; 画_图(); 画_面板();
      const el = $(`.wfnode[data-id="${CSS.escape(p.node_id)}"]`);
      if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.focus(); }
    };
  });
}

async function 做_存草稿() {
  try {
    const d = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/draft`, {
      method: "PATCH", headers: { "If-Match": String(图态.revision) },
      body: JSON.stringify({ 定义: 图态.定义, 布局: 图态.布局 }),
    });
    图态.revision = d.revision; 图态.脏 = false;
    // 改过就把上次的校验报告作废 —— **一份对着旧图的报告比没有报告更糟**
    图态.报告 = null;
    画_画布();
  } catch (e) {
    if (e.码 === 409) {
      alert(`版本冲突:${e.message}\n\n下一步:${e.体?.advice || ""}\n\n`
        + `这一页不会替你覆盖 —— 刷新看一眼别人改了什么再合并。`);
      return 路由();
    }
    alert(`${e.体?.code || "出错"}:${e.message}\n\n下一步:${e.体?.advice || "—"}`);
  }
}

async function 做_校验() {
  if (图态.脏) { await 做_存草稿(); }
  try {
    图态.报告 = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/validate`,
                        { method: "POST" });
    图态.底Tab = "问题"; 画_画布();
  } catch (e) { alert(`${e.体?.code || "出错"}:${e.message}`); }
}

async function 做_冻结() {
  const 说明 = prompt("变更说明(必填)——「这一版改了什么、为什么」。\n\n"
    + "它是版本对比时唯一能说清意图的东西:哈希只能说明「变了」。");
  if (说明 === null) return;
  if (图态.脏) { await 做_存草稿(); }
  try {
    const d = await 请求(`${P()}/workflows/${encodeURIComponent(图态.wid)}/versions`,
      { method: "POST", body: JSON.stringify({ 变更说明: 说明 }) });
    alert(`冻结成 ${d["版本"]}。\n\n逻辑哈希 ${d["逻辑哈希"].slice(0, 26)}…\n`
      + `依赖:\n${(d["依赖"] || []).join("\n")}\n\n${d.note}`);
    return 路由();
  } catch (e) {
    const b = e.体 || {};
    alert(`${b.code || "出错"}:${e.message}\n\n下一步:${b.advice || "—"}`
      + (b.field_errors ? `\n\n` + Object.entries(b.field_errors)
          .map(([k, v]) => `· ${k}:${v}`).join("\n") : ""));
    if (b.code === "VALIDATION") { 图态.底Tab = "问题"; return 做_校验(); }
  }
}

async function 做_试运行() {
  const 图 = 图态.定义;
  const 需 = ((图.nodes.find((n) => n.type === "start") || {}).config?.input_schema
              ?.required) || [];
  const 输入 = {};
  for (const k of 需) {
    const v = prompt(`试运行输入 · ${k}(必填)`);
    if (v === null) return;
    输入[k] = v;
  }
  if (图态.脏) { await 做_存草稿(); }
  try {
    const d = await 请求(`${P()}/execution-runs`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ workflow_id: 图态.wid, 输入 }),
    });
    图态.底Tab = "事件"; 画_底部();
    $("#bt").innerHTML = `<div class="k">已受理 <code>${esc(d.resource_id)}</code> ——
      <b>${esc(d.status)},一个模型都还没调</b>。正在等 Worker…</div>`;
    await 轮询运行(d.resource_id);
  } catch (e) {
    const b = e.体 || {};
    alert(`${b.code || "出错"}:${e.message}\n\n下一步:${b.advice || "—"}`);
    if (b.code === "VALIDATION") { 图态.底Tab = "问题"; return 做_校验(); }
  }
}

async function 轮询运行(rid) {
  // ⚠️ 这是**轮询**,不是 SSE。运行事件的 SSE 端点已经登记在契约里
  // (`GET /execution-runs/{id}/events`),但 `EventSource` 带不了自定义请求头,
  // 而开发身份在 `X-Dev-User` 头上 —— 要接 SSE 得先把身份挪到 cookie
  // 或者改用 fetch 流,而那个选择影响生产接 OIDC。**先诚实地轮询。**
  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 600));
    let d;
    try { d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`); }
    catch (e) { continue; }
    图态.事件 = d["事件"] || [];
    if (图态.底Tab === "事件") 画_底部();
    if (d["是终态吗"]) {
      $("#bt").innerHTML = `<div style="font-size:13px;margin-bottom:8px">
        执行状态 <b>${esc(d["执行状态中文"])}</b>(<code>${esc(d["执行状态"])}</code>)
        ${d["停止原因"] ? ` · 停止原因 <code>${esc(d["停止原因"])}</code>` : ""}
        <br>任务达标 <b>${esc(d["任务达标"])}</b>
        <span class="k">${md(d["达标说明"])}</span>
        <br><a href="#/wfrun/${encodeURIComponent(rid)}">看这次运行的完整详情 →</a>
      </div>` + $("#bt").innerHTML;
      return;
    }
  }
  $("#bt").innerHTML = `<div class="err" style="padding:8px">轮询了 12 秒还没到终态。
    <b>这不代表它失败了</b> —— 可能 Worker 没起来(<code>make dev</code> 会一起起)。
    去 <a href="#/wfrun/${encodeURIComponent(rid)}">运行详情</a>看实际状态。</div>`;
}

/* ── 运行详情 ─────────────────────────────────────────────────── */
async function 页_运行详情(rid) {
  const d = await 请求(`${P()}/execution-runs/${encodeURIComponent(rid)}`);
  const 步 = d["步骤"] || [];
  $("#main").innerHTML = `
    <div class="crumb"><a href="#/workflows">工作流</a> / 运行 ${esc(rid)}</div>
    <div class="head"><div><h1>运行详情</h1>
      <div class="sub">定义来源 <code>${esc(JSON.stringify(d["定义来源"] || {}))}</code></div>
    </div></div>
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
    <h3>步骤(${步.length})</h3>
    <table><thead><tr><th>节点</th><th>类型</th><th>状态</th><th>尝试</th>
      <th>执行键</th><th>分支 / 为什么跳过</th><th>错误</th></tr></thead><tbody>`
    + 步.map((s) => `<tr>
        <td><b>${esc(s["节点"])}</b></td><td class="k">${esc(s["类型"])}</td>
        <td>${s["状态"] === "succeeded" ? `<span class="pill ok">成功</span>`
            : s["状态"] === "skipped" ? `<span class="pill">未激活(跳过)</span>`
            : `<span class="pill warn">${esc(s["状态"])}</span>`}</td>
        <td class="k">${esc(s["尝试"])}</td>
        <td><code style="font-size:11px">${esc(s["执行键"])}</code></td>
        <td class="k">${esc(s["走的分支"] || s["为什么跳过"] || "")}</td>
        <td class="k">${esc(s["错误码"] || "")}</td></tr>`).join("")
    + `</tbody></table>
    <div class="note"><b>「未激活(跳过)」和「失败」是两个状态</b>(§8)——
      未激活的支路既不阻塞汇合,<b>也不算「完成了的工作」</b>。
      合并之后,「这次跑过了 N 个节点」这句话就没有意义了。<br>
      执行键含 <code>(Run, node_id, 循环路径, 尝试次数)</code> ——
      <b>传输重试不改变它</b>,所以网络重发不会变成第二次写入(§8)。</div>
    <h3>输入输出</h3>
    <div class="two">
      <div class="card"><h4>输入快照</h4>
        <pre style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(d["输入快照"], null, 1))}</pre></div>
      <div class="card"><h4>输出</h4>
        <pre style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(d["输出"], null, 1))}</pre>
        <div class="note">原文默认<b>脱敏</b>;要看要「查看敏感输入/独立测试答案」
          专项授权(§14.3)。顶栏切到 U004 能看到区别。</div></div>
    </div>
    <h3>事件(${(d["事件"] || []).length})</h3>
    ${(d["事件"] || []).map((e) => `<div style="font-size:12px">
        <span class="k">${esc(String(e.seq).padStart(2, "0"))}</span>
        <code>${esc(e["类型"])}</code>
        <span class="k">${esc(JSON.stringify(e["载荷"] || {}).slice(0, 160))}</span></div>`).join("")}
    <div class="note">事件<b>只表达已记录的事实</b>(§17.2)——
      不会在外部返回成功之前先发一条成功事件。seq 在 Run 内单调,断线能按 seq 续。</div>`;
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
async function 页_agent列表() {
  $("#main").innerHTML = `<div class="crumb">编排 / 智能体</div>
    <div class="head"><div><h1>智能体 Agent</h1>
      <div class="sub">模型自己决定下一步做什么,<b>而程序校验、执行、记录和限制它</b>。
        模型说「调用工具」是请求 —— 真正执行的是服务端的工具网关。</div></div>
      <div><button class="pri" id="new">新建 Agent</button></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  $("#new").onclick = 弹_新建agent;
  try {
    const d = await 请求(`${P()}/agents`);
    if (!d.items.length) {
      const s = 状态("", "还没有 Agent",
        "新建一个 —— 模板会预填**一条声明了支持原生工具调用的连接**、"
        + "两个演示工具(搜索 / 写报告)和一组限制初值。\n\n"
        + "模板**只预填草稿**:不调模型、不绑生产环境。",
        { 文: "新建 Agent", 做: 弹_新建agent });
      $("#list").innerHTML = s.html; s.挂(); return;
    }
    $("#list").innerHTML = `<table><thead><tr>
      <th>名称</th><th>用途</th><th>模型连接</th><th>工具数</th>
      <th>最新冻结版本</th><th>生产引用版本</th><th>校验状态</th><th></th>
      </tr></thead><tbody>`
      + d.items.map((r) => `<tr>
        <td><a href="#/agent/${encodeURIComponent(r.id)}">${esc(r["名称"])}</a></td>
        <td>${esc(r["用途"] || "—")}</td>
        <td class="k">${esc(r["模型连接"] || "没选")}</td>
        <td title="${esc(r["工具数说明"])}">${r["工具数"]}
            <span class="k">个候选</span></td>
        <td>${r["最新冻结版本"] ? `<span class="pill">${esc(r["最新冻结版本"])}</span>`
              : `<span class="k">还没冻结过</span>`}</td>
        <td><span class="stale" title="${esc(r["生产引用说明"])}">还没接</span></td>
        <td>${r["校验状态"] === "通过" ? `<span class="pill ok">通过</span>`
              : `<span class="pill warn">${esc(r["校验状态"])}</span>`}</td>
        <td><a href="#/agent/${encodeURIComponent(r.id)}">配置</a></td>
      </tr>`).join("") + `</tbody></table>
      <div class="note"><b>「工具数」那一栏只表示授权候选集合的规模</b> ——
        规格 §9.1 明写<b>不按工具数量给 Agent 打能力强弱分</b>。
        一个显示 7 的会被读成「比那个 3 的强」,而那两件事没有关系。</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

function 弹_新建agent() {
  const 名 = prompt("Agent 名称:");
  if (!名) return;
  请求(`${P()}/agents`, { method: "POST", body: JSON.stringify({ 名称: 名 }) })
    .then((d) => { location.hash = `#/agent/${encodeURIComponent(d.id)}`; })
    .catch((e) => alert(`${e.体?.code || "出错"}:${e.message}\n\n下一步:${e.体?.advice || "—"}`));
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
    ${多行 ? `<textarea data-k="${esc(键)}" rows="${多行}">${esc(v)}</textarea>`
           : `<input data-k="${esc(键)}" value="${esc(v)}">`}</div>
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
          <pre style="font-size:12px;white-space:pre-wrap">${esc(JSON.stringify(r["输出"], null, 1))}</pre>
          <div class="k">用量 ${esc(JSON.stringify(r["用量"] || {}))}</div>
          <a href="#/wfrun/${encodeURIComponent(r.id)}">看完整运行详情 →</a>`
          : `<div class="k">还没跑过。点右上「试运行」——
              它返回 <b>202 排队中</b>,一个模型都还没调。</div>`}
      </div></div>
      <div class="card"><h4>真实回合与工具调用</h4>
      ${(g.事件 || []).length ? (g.事件 || []).map((e) => `<div style="font-size:12px">
          <span class="k">${esc(String(e.seq).padStart(2, "0"))}</span>
          <code>${esc(e["类型"])}</code>
          <span class="k">${esc(JSON.stringify(e["载荷"] || {}).slice(0, 150))}</span></div>`).join("")
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
      catch (e) { alert(`输入不是合法 JSON:${e.message}`); }
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
        catch (e) { alert(`${k} 不是合法 JSON:${e.message}\n\n没保存这一项。`); return; }
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
      alert(`版本冲突:${e.message}\n\n下一步:${e.体?.advice || ""}`);
      return 路由();
    }
    alert(`${e.体?.code || "出错"}:${e.message}\n\n下一步:${e.体?.advice || "—"}`);
  }
}

async function 做_校验agent() {
  if (agent态.脏) await 做_存agent();
  try {
    agent态["草稿"]["上次校验报告"] =
      await 请求(`${P()}/agents/${encodeURIComponent(agent态.aid)}/validate`,
                { method: "POST" });
    画_agent();
  } catch (e) { alert(`${e.体?.code || "出错"}:${e.message}`); }
}

async function 做_冻结agent() {
  const 说明 = prompt("变更说明(必填)——「这一版改了什么、为什么」。");
  if (说明 === null) return;
  if (agent态.脏) await 做_存agent();
  try {
    const d = await 请求(`${P()}/agents/${encodeURIComponent(agent态.aid)}/versions`,
      { method: "POST", body: JSON.stringify({ 变更说明: 说明 }) });
    alert(`冻结成 ${d["版本"]}。\n\n内容哈希 ${d["内容哈希"].slice(0, 26)}…\n\n${d.note}`);
    return 路由();
  } catch (e) {
    const b = e.体 || {};
    alert(`${b.code || "出错"}:${e.message}\n\n下一步:${b.advice || "—"}`
      + (b.field_errors ? "\n\n" + Object.entries(b.field_errors)
          .map(([k, v]) => `· ${k}:${v}`).join("\n") : ""));
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
    alert("轮询了 12 秒还没到终态。**这不代表它失败了** —— "
      + "可能 Worker 没起来(make dev 会一起起)。");
  } catch (e) {
    const b = e.体 || {};
    alert(`${b.code || "出错"}:${e.message}\n\n下一步:${b.advice || "—"}`
      + (b.field_errors ? "\n\n" + Object.entries(b.field_errors)
          .map(([k, v]) => `· ${k}:${v}`).join("\n") : ""));
    if (b.code === "VALIDATION") return 做_校验agent();
  }
}

/* ── 工具目录(§11.1)──────────────────────────────────────────── */
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
        <td><b>${esc(r["名称"])}</b></td><td>${esc(r["用途"] || "—")}</td>
        <td>${r["读写类型"] === "只读" ? `<span class="pill">只读</span>`
              : `<span class="pill warn">${esc(r["读写类型"])}</span>`}</td>
        <td class="k">${esc(r["接入方式"])}</td>
        <td>${r["最新版本"] ? `<span class="pill">${esc(r["最新版本"])}</span>`
              : `<span class="k">还没冻结版本</span>`}</td>
        <td class="k">${esc(r["状态"])}</td></tr>`).join("")
      + `</tbody></table>
      <div class="note">工具执行只走<b>一个入口</b>(工具网关),门上六道闸:
        注册 → 服务端绑定 → Schema → 对象范围 → 确认 → 幂等。<br>
        <b>「注册工具」这个按钮还没做</b> —— 接口有了(<code>POST /tools</code>,
        它<b>不收可执行代码</b>,只收「哪个适配器 + 什么 Schema + 什么风险级别」),
        页面上的表单没做。<b>不摆一个点了没反应的按钮。</b></div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
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
  if (是mock === null || 是mock === undefined) return "";
  return 是mock
    ? `<span class="tag crit" title="mock 向量从文本哈希派生,**语义无感知** —— 相似度不代表语义">⚠️ mock 向量</span>`
    : `<span class="tag ok" title="真模型(本机 onnxruntime,离线)">真向量</span>`;
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
      <div class="sub">不可逆写入要人点头。**列表上没有批准按钮,这是有意的。**</div>
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
        <td>${esc(r.risk_note || r.kind || r.id)}
          <div class="k">${esc(r.id)}</div>
          ${r["有人能批吗"] === false
            ? `<div class="k"><span class="tag crit">没人能批</span>
                 ${esc(r["没人能批的原因"] || "")}</div>` : ""}</td>
        <td><span class="tag ${r.status === "pending" ? "warn"
              : r.status === "approved" ? "ok" : ""}">${esc(r.status)}</span></td>
        <td class="k">${r.expires_at
              ? esc(String(r.expires_at).slice(5, 16).replace("T", " "))
              : `<span class="tag crit">没设截止</span>`}
          ${r["过期了吗"] === true ? `<span class="tag crit">已过期</span>` : ""}</td>
        <td>${r["还能处理吗"] ? `<span class="tag ok">能</span>`
              : `<span class="tag">不能</span>
                 <div class="k">${esc(String(r["为什么不能处理"] || "").slice(0, 60))}</div>`}</td>
        <td><button data-hr="${esc(r.id)}">看详情</button></td>
      </tr>`).join("")
    + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
  $("#main").querySelectorAll("[data-hr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/human/" + encodeURIComponent(b.dataset.hr); };
  });
}

async function 页_待办详情(hid) {
  const 头 = `<div class="crumb"><a href="#/human">人工待办</a> · 详情</div>
    <div class="head"><div><h1>待办详情</h1>
      <div class="sub">${esc(hid)}</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/human-requests/${encodeURIComponent(hid)}`); }
  catch (e) { const s = 错误块(e, () => 页_待办详情(hid)); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 证 = d["证据"] || {};
  const 工 = d["具体工具"];
  $("#main").innerHTML = 头
    + `<div class="note">${md(d.note || "")}</div>
    <h2>要批准什么</h2>
    <div class="card">
      <div class="k">影响对象</div>
      <pre class="k">${esc(JSON.stringify(d["影响对象"], null, 1))}</pre>
      <div class="k">具体工具</div>
      <pre class="k">${工 ? esc(JSON.stringify(工, null, 1)) : "(没绑工具版本)"}</pre>
      <div class="k">参数${d["看得到原文吗"] ? "（原文）" : "（已脱敏）"}</div>
      <pre class="k">${esc(JSON.stringify(d["脱敏参数"], null, 1))}</pre>
    </div>
    <h2>证据</h2>
    <table><tbody>`
    + Object.entries(证).map(([k, v]) =>
        `<tr><td class="k">${esc(k)}</td><td>${esc(JSON.stringify(v))}</td></tr>`).join("")
    + `</tbody></table>
    <h2>决定</h2>`
    + (d["你能处理吗"]
        ? `<div class="card">
             <div class="lbl">理由（驳回必填）</div>
             <textarea id="why" rows="2"></textarea>
             <div class="lbl">改字段（JSON，只许改 ${esc(JSON.stringify(d["允许编辑的字段"]))}）</div>
             <textarea id="edits" rows="2">{}</textarea>
             <button class="pri" id="ap">批准</button>
             <button id="rj">驳回</button>
             <button id="info">要求补充</button>
             <div class="note">⚠️ **批准只产生批准记录,不等于已执行** ——
               真正执行时还要再查一遍权限和工具当前可用性。</div>
             <div id="res"></div>
           </div>`
        : `<div class="state err"><h3>你不能处理这条</h3>
             <p>${md(d["为什么"] || "")}</p></div>`)
    + `<h2>决定历史</h2>`
    + ((d["决定历史"] || []).length
        ? `<table><thead><tr><th>谁</th><th>怎么判的</th><th>那时的 rev</th>
             <th>理由</th></tr></thead><tbody>`
          + d["决定历史"].map((x) => `<tr><td>${esc(x.actor)}</td>
              <td><span class="tag">${esc(x.decision)}</span></td>
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
      <div class="sub">改完之后跑一遍,看有没有退步。**有分数 ≠ 能当结论。**</div>
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
                            : `<span class="tag crit">没有基线</span>`}</td>
        <td class="num">${r["题数"]}</td>
        <td class="k">${esc(String(r.dataset_version_id || "—").slice(-10))}</td>
        <td class="k">${esc(r.scorer_version || "—")}</td>
        <td>${r["能当结论吗"] ? `<span class="tag ok">能</span>`
              : `<span class="tag crit">不能</span>
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
      <div class="sub">同一套题两个版本并排。**不可比时不给分数。**</div>
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
      <div class="lbl">甲</div><select id="ea">${选()}</select>
      <div class="lbl">乙</div><select id="eb">${选()}</select>
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
              ? `<span class="tag warn">未知</span>`
              : `${v["均分"]} <div class="k">${v["已知几条"]} 条已打分`
                + (v["没打分几条"] ? ` · ${v["没打分几条"]} 条没打分` : "") + `</div>`;
            const 可算 = !A["均分是未知吗"] && !B["均分是未知吗"];
            return `<tr><td><b>${esc(k)}</b></td><td>${格(A)}</td><td>${格(B)}</td>
              <td>${可算 ? (B["均分"] - A["均分"] >= 0 ? "+" : "")
                          + Math.round((B["均分"] - A["均分"]) * 10000) / 10000
                        : `<span class="tag warn">算不出</span>`}</td></tr>`;
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
      <div class="sub">拿一条真输入试一次。**调试也花钱**,所以要过额度闸。</div>
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
      <div class="lbl">选一条 Prompt</div>
      <select id="pp">${ps.items.map((p) =>
        `<option value="${esc(p.id)}">${esc(p.name || p.key || p.id)}</option>`).join("")}</select>
      <div class="lbl">变量(JSON)</div>
      <textarea id="vv" rows="4">{}</textarea>
      <button class="pri" id="go">试跑一次</button>
      <div class="note">⚠️ **这一次真的会调模型。** 返回的是任务信封(202),
        不是答案 —— 下面显示的是**真实状态**,不是假进度条。</div>
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
      <div class="sub">每一次运行的调用树。**看得到 trace 不等于看得到原文。**</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/traces?limit=50`); }
  catch (e) { const s = 错误块(e, 页_调用链); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  if (!d.items.length) {
    $("#main").innerHTML = 头 + 状态("", "还没有运行记录",
      "跑一次检索实验室,或者让门店助手上报一次调用(A1)。").html;
    return;
  }
  $("#main").innerHTML = 头 + `<table><thead><tr>
      <th>什么时候</th><th>调用方</th><th class="num">步</th>
      <th class="num">token</th><th class="num">金额</th><th>结果</th><th></th>
    </tr></thead><tbody>`
    + d.items.map((r) => `<tr>
        <td class="k">${esc(String(r.started_at).slice(5, 19).replace("T", " "))}
          <div class="k">${esc(r.id)}</div></td>
        <td>${r["调用方"] ? esc(r["调用方"]) : `<span class="tag warn">没标调用方</span>`}</td>
        <td class="num">${r["步数"]}${r["出错的步数"]
            ? ` <span class="tag crit">${r["出错的步数"]} 步出错</span>` : ""}</td>
        <td class="num">${Number(r["token数"]).toLocaleString()}</td>
        <td class="num">${_参考价(r["参考价"])}</td>
        <td>${r["成功吗"] ? `<span class="tag ok">${esc(r.end_reason || "完成")}</span>`
                          : `<span class="tag crit">${esc(r.end_reason || "失败")}</span>`}</td>
        <td><button data-tr="${esc(r.id)}">看调用树</button></td>
      </tr>`).join("")
    + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
  $("#main").querySelectorAll("[data-tr]").forEach((b) => {
    b.onclick = () => { location.hash = "#/trace/" + encodeURIComponent(b.dataset.tr); };
  });
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
              <td>${u.provider ? esc(u.provider) : `<span class="tag">mock</span>`}</td>
              <td>${esc(u.caller || "—")}</td>
              <td class="num">${Number(u["token数"]).toLocaleString()}</td>
              <td class="num">${u["金额未知的行数"] > 0
                    ? `<span class="tag warn">未知</span>`
                    : `$${Number(u["已知金额"]).toFixed(4)}`}</td></tr>`).join("")
          + `</tbody></table>`
        : `<div class="state">这次运行没有用量记录</div>`)
    + `<h2>每一步</h2>`
    + (d["步们"] || []).map((s2, i) => `<div class="card">
        <div class="k">${i + 1}. ${esc(s2.stage)}
          ${s2["出错了吗"] ? `<span class="tag crit">出错</span>` : ""}</div>
        <pre class="k">${esc(JSON.stringify(
            脱 ? {入: s2["入_形状"], 出: s2["出_形状"], 错: s2["错_形状"]}
               : {入: s2["入"], 出: s2["出"], 错: s2["错"]}, null, 1))}</pre>
      </div>`).join("");
}

/* ── 智能体健康(M4:/health 重建)────────────────────────────────────
 * ⚠️ **采纳率不是质量分。** 上线之后没有标准答案(线上问题不在评测集里),
 * 能拿到的只有「人采纳了没有」—— 而采纳率高也可能是因为人懒得改。
 * 这一页最重要的事是把这个区别写在脸上。 */
async function 页_智能体健康() {
  const 头 = `<div class="crumb">评测中心</div>
    <div class="head"><div><h1>智能体健康</h1>
      <div class="sub">上线之后**没有标准答案** —— 能拿到的是采纳率,而它不是质量分。</div>
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
function _卡(名, 值, 未知, 分母, 来源) {
  const v = 未知 ? `<div class="n unknown">未知</div>`
                 : `<div class="n">${esc(值)}</div>`;
  return `<div class="card kpi"><div class="k">${esc(名)}</div>${v}
    <div class="meta">${分母 ? esc(分母) + "<br>" : ""}来源:${esc(来源)}</div></div>`;
}

// ⚠️ 这个函数叫 `_参考价` 不叫 `_钱` —— 用户 2026-09-28 定的:
// **计量按 token 算,价格只给参考**。界面上一律写「参考价」不写「费用」,
// 因为真账单还受批量折扣、协议价、账单延迟、DeepSeek 时段浮动影响。
// > 一个被当成账单用的估算,比没有估算糟。
function _参考价(x) {
  // ⚠️ `x == null` 同时接住 null 和 undefined。写成 `x === null` 的话,
  // 一个字段名拼错(拿到 undefined)会显示成 `undefined`,而不是「未知」——
  // 那种时候更该显示「未知」,因为我们确实不知道。
  return x == null ? `<span class="tag warn">未知</span>` : `$${x.toFixed(4)}`;
}

async function 页_用量与成本() {
  const 头 = `<div class="crumb">用量与成本</div>
    <div class="head"><div><h1>用量与成本</h1>
      <div class="sub">谁花的、花在哪次调用上。**未知显示「未知」,不显示 0。**</div>
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

    <h2>按调用方 —— **谁花的**</h2>
    <div class="note">⚠️ 这一张是 A1 上报链存在的**全部理由**。
      只有「按用途」的话,门店助手和管理后台自己的调用混在同一个用途里,
      **「门店助手今天花了多少」答不出来**,只答得出「一共花了多少」。</div>
    <table><thead><tr><th>调用方</th><th>谁提供的</th><th>模式</th>
        <th class="num">调用</th><th class="num">token</th>
        <th class="num">金额</th></tr></thead><tbody>`
    + (d["按调用方"] || []).map((g) => `<tr>
        <td><b>${esc(g["调用方"])}</b></td>
        <td>${g.provider ? esc(g.provider) : `<span class="k">—</span>`}</td>
        <td>${g.source === "mock"
              ? `<span class="tag">mock · 没花钱</span>`
              : `<span class="tag ok">live</span>`}</td>
        <td class="num">${g["调用次数"]}</td>
        <td class="num">${Number(g["token数"]).toLocaleString()}</td>
        <td class="num">${g["金额未知的行数"] > 0
              ? `<span class="tag warn">未知</span>`
              : `$${Number(g["已知金额"]).toFixed(4)}`}</td>
      </tr>`).join("")
    + `</tbody></table>

    <h2>按用途</h2>
    <div class="note">⚠️ **「谁提供的」要和「用途」一起看** ——
      一份 mock 的用量在数据形状上和真的一模一样。
      这段时间里**真花过钱的用途有 ${d["真花过钱的用途数"]} 个**。</div>
    <table><thead><tr><th>用途</th><th>谁提供的</th>
        <th class="num">调用</th><th class="num">token</th>
        <th class="num">金额</th></tr></thead><tbody>`
    + (d["按用途"] || []).map((g) => `<tr>
        <td><b>${esc(g.resource)}</b></td>
        <td>${g.source === "mock"
              ? `<span class="tag">mock · 没花钱</span>`
              : `<span class="tag ok">${esc(g.source)}</span>`}</td>
        <td class="num">${g["调用次数"]}</td>
        <td class="num">${Number(g["token数"]).toLocaleString()}</td>
        <td class="num">${g["金额未知的行数"] > 0
              ? `<span class="tag warn">未知</span><div class="k">${g["金额未知的行数"]} 行</div>`
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
        <td>${r.caller ? esc(r.caller) : `<span class="tag warn">没标调用方</span>`}</td>
        <td>${esc(r.resource)} ${r["是mock吗"] ? `<span class="tag">mock</span>` : ""}</td>
        <td class="k">${esc(r["档"] || "")}</td>
        <td class="num">${Number(r.quantity).toLocaleString()} ${esc(r.unit)}</td>
        <td class="num">${_参考价(r["参考价"])}</td>
        <td class="k">${esc(r.trace_id || "")}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">⚠️ **每次调用写几行,不是一行** —— token 分
         input / output / cache 几档记,因为**它们的单价差一个数量级**。
         合成一个数之后,补上价目表也算不回来了。</div>`;
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
                  "校验失败": "crit", "已放弃": "" };

async function 页_加资料() {
  const 头 = `<div class="crumb">知识与 RAG</div>
    <div class="head"><div><h1>加资料</h1>
      <div class="sub">选文件 → 传 → **服务端校验**。只有「已校验」才算能用的文件引用(§17.1)。</div>
    </div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let d;
  try { d = await 请求(`${P()}/uploads?limit=50`); }
  catch (e) { const s = 错误块(e, 页_加资料); $("#main").innerHTML = 头 + s.html; s.挂(); return; }

  $("#main").innerHTML = 头 + `
    <div class="card">
      <div class="lbl">选一个文件</div>
      <input type="file" id="f" accept=".md,.markdown,.txt">
      <button class="pri" id="go">上传并校验</button>
      <div class="note">收 `.md` / `.markdown` / `.txt`,单个不超过 5 MB。
        **PDF 和扫描件要 OCR,这一版没接** —— 会在第一步就被拒,不会让你白传一遍。</div>
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
        <td><span class="tag ${_上传状态色[r["状态"]] || ""}">${esc(r["状态"])}</span></td>
        <td>${r["能引用吗"] ? `<span class="tag ok">能</span>`
                            : `<span class="tag crit">不能</span>`}</td>
        <td class="num">${r.byte_count == null ? "—" : r.byte_count}</td>
        <td>${((r["校验详情"] || {})["没过的规则"] || []).map(esc).join("、") || "—"}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">⚠️ **「能引用的」通常少于总数**(这里 ${d["能引用的"]} / ${d.total})。
         校验失败的那些**留着不删**:一条「传过但没通过」的记录是证据 ——
         删掉之后用户只会再传一次同一个坏文件。</div>`;
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
      <div class="sub">资料、片段、索引。**有片段不等于能检索** —— 要有一个「已就绪」的索引。</div>
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
        <td class="num">${r["片段数"]}</td>
        <td>${r["能检索吗"]
              ? `<span class="tag ok">能</span>`
              : `<span class="tag crit">不能</span>
                 <div class="k">${esc(r["为什么不能检索"] || "")}</div>`}</td>
        <td>${r["就绪索引数"]} 个已就绪 ${_mock标(r["索引是mock吗"])}
            ${r["索引模型"] ? `<div class="k">${esc(r["索引模型"])}</div>` : ""}</td>
        <td><button data-kb="${esc(r.id)}">看索引</button>
            ${r["能检索吗"] ? `<button data-try="${esc(r.id)}">去检索</button>` : ""}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">⚠️ **「片段数」是资料切出来的条数,不是索引里的条数。**
         两个对不上就说明索引不完整 —— 而一个不完整的索引检索时只是「少返回几条」,
         **不报错**。点「看索引」能看到每次构建的成员数。</div>`;
  $("#main").querySelectorAll("[data-kb]").forEach((b) => {
    b.onclick = () => { location.hash = "#/kb/" + encodeURIComponent(b.dataset.kb); };
  });
  $("#main").querySelectorAll("[data-try]").forEach((b) => {
    b.onclick = () => { location.hash = "#/retrieval"; };
  });
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
        <td><span class="tag ${r.status === "已就绪" ? "ok" : (r.status === "失败" ? "crit" : "warn")}">${esc(r.status)}</span></td>
        <td>${esc(r.embedding_model_id || "—")} ${r.embedding_dim ? `<span class="k">${r.embedding_dim} 维</span>` : ""}
            ${_mock标(r["是mock吗"])}</td>
        <td class="num">${r["成员数"]}</td>
        <td class="k">${esc(r["输入指纹短"] || "**没记**")}</td>
      </tr>`).join("")
    + `</tbody></table>
       <div class="note">**输入指纹**覆盖:文档版本集合 + 检索配置 + Embedding 模型与维度
         + 切片器版本 + 解析器版本。少一项就会在**变过的输入上续做** ——
         产出一半旧边界一半新边界的索引,而它**不报错**,只是答得怪(§19.3)。
         <br>⚠️ 指纹那一栏写「没记」的是这个字段加上之前建的 ——
         它们会被强制重建,**因为「没记」不等于「一样」**。</div>`;
}

async function 页_检索实验室() {
  const 头 = `<div class="crumb">知识与 RAG</div>
    <div class="head"><div><h1>检索实验室</h1>
      <div class="sub">问一句话,看**整条链路**怎么走到那几段(§9.5)。</div></div></div>`;
  $("#main").innerHTML = 头 + `<div class="state">加载中…</div>`;
  let kbs;
  try { kbs = await 请求(`${P()}/knowledge-bases`); }
  catch (e) { const s = 错误块(e, 页_检索实验室); $("#main").innerHTML = 头 + s.html; s.挂(); return; }
  const 可用 = kbs.items.filter((x) => x["能检索吗"]);
  if (!可用.length) {
    $("#main").innerHTML = 头 + 状态("", "没有能检索的知识库",
      "要有一个**「已就绪」的索引**才能检索。\n\n"
      + kbs.items.map((x) => `· ${x.name}:${x["为什么不能检索"] || ""}`).join("\n"),
      { 文: "去知识库", 做: () => { location.hash = "#/kb"; } }).html;
    const b = $("#st-act"); if (b) b.onclick = () => { location.hash = "#/kb"; };
    return;
  }
  // 取第一个能检索的知识库的已就绪索引
  let builds = { items: [] };
  try { builds = await 请求(`${P()}/knowledge-bases/${encodeURIComponent(可用[0].id)}/index-builds`); }
  catch (e) { /* 下面会显示「没有可用索引」 */ }
  const 就绪 = builds.items.filter((x) => x.status === "已就绪");
  $("#main").innerHTML = 头 + `<div class="card"><div class="body">
      <label class="k">索引</label>
      <select id="rt-ib">${就绪.map((x) => `<option value="${esc(x.id)}">${esc(x.id)} · ${esc(x.embedding_model_id || "")} ${x["是mock吗"] ? "(mock)" : ""}</option>`).join("")}</select>
      <label class="k" style="margin-left:10px">问题</label>
      <input id="rt-q" style="width:44%" placeholder="客户给了差评要怎么处理"
             value="客户给了差评要怎么处理">
      <label class="k" style="margin-left:10px">
        <input type="checkbox" id="rt-rr" checked> Claude 精排</label>
      <button id="rt-go" style="margin-left:10px">检索</button>
      <div class="note">⚠️ 勾着精排会**真调一次 Claude**(几百毫秒到两秒),用量记在记录仪里。
        去掉勾只走向量 —— **那个排序不可靠**:实测一个表格头排到过第 1 名(0.6849),
        而真答案第 2(0.6329)。</div>
    </div></div><div id="rt-out"></div>`;
  const 跑 = async () => {
    const ib = $("#rt-ib") ? $("#rt-ib").value : "";
    const q = ($("#rt-q").value || "").trim();
    const rr = $("#rt-rr").checked;
    $("#rt-out").innerHTML = `<div class="state">检索中${rr ? "(要调一次模型,稍等)" : ""}…</div>`;
    let d;
    try {
      d = await 请求(`${P()}/retrieval-tests`, {
        method: "POST", body: JSON.stringify({ 索引构建id: ib, 问题: q, 要精排: rr }),
      });
    } catch (e) { const s = 错误块(e, 跑); $("#rt-out").innerHTML = s.html; s.挂(); return; }
    $("#rt-out").innerHTML = 画链路(d);
  };
  $("#rt-go").onclick = 跑;
  $("#rt-q").onkeydown = (e) => { if (e.key === "Enter") 跑(); };
  await 跑();
}

function 画链路(d) {
  const 行 = (k, v, n) => `<tr><td class="k">${esc(k)}</td><td>${v}${n ? `<div class="k">${n}</div>` : ""}</td></tr>`;
  const 链 = `<div class="card"><div class="k" style="padding:8px 10px 0">整条链路(§9.5)</div>
    <table><tbody>
    ${行("原问", esc(d["原问"]))}
    ${行("改写", d["改写"] === null
          ? `<span class="tag">没做</span>`
          : esc(d["改写"]),
          md(d["改写说明"] || ""))}
    ${行("召回", `${d["召回数"]} 条候选 · ${esc((d["召回方式"] || []).join("、"))}`)}
    ${行("向量", `${esc(d["embedding"]["模型"])} · ${d["embedding"]["维度"]} 维 ${_mock标(d["embedding"]["是mock"])}`)}
    ${行("精排", d["精排"]["做了"]
          ? `${esc(d["精排"]["模型"] || "")} · ${(d["精排"]["用量"] || {}).input_tokens || "?"} in / ${(d["精排"]["用量"] || {}).output_tokens || "?"} out`
          : `<span class="tag warn">没做</span>`,
          d["精排"]["做了"] ? "" : md(d["精排"]["为什么"] || ""))}
    ${行("截断", esc(d["截断"]))}
    ${行("选片", `${d["选了几片"]} 片 · ${d["用了多少token"]} token`,
          d["token是粗估"] ? "token 数是**粗估** —— 不许拿它算钱" : "")}
    </tbody></table></div>`;

  const 警 = [];
  if (d["引文没通过校验的"]) 警.push(md(d["引文说明"] || ""));
  if (d["因为太大跳过的"] && d["因为太大跳过的"].length) 警.push(md(d["跳过说明"] || ""));

  const 片 = `<div class="card"><div class="k" style="padding:8px 10px 0">选中的片段(按精排分数)</div>
    ${d["选片"].map((x) => `<div class="body" style="border-top:1px solid var(--line)">
      <div>
        ${x["分数"] === null ? `<span class="tag">未精排</span>`
                            : `<span class="tag ${x["分数"] >= 7 ? "ok" : (x["分数"] >= 4 ? "warn" : "crit")}">${x["分数"]}/10</span>`}
        <span class="k">向量 ${x["相似度"]}</span>
        <b style="margin-left:8px">${esc(x["证据"])}</b>
      </div>
      ${x["引文"] ? `<div style="margin:4px 0">
          ${x["引文可信"] === false
            ? `<span class="tag crit" title="${esc(x["引文问题"] || "")}">⚠️ 引文不可信</span> `
            : ``}
          引文「${esc(x["引文"])}」
          ${x["引文可信"] === false
            ? `<div class="k">**这句话在片段里找不到**(模型改写了原话)——
                 分数仍然保留,但它给的**理由不可信**。引文的用处是让人照着它
                 在原文里搜到那一句,搜不到就等于没有。</div>` : ""}
        </div>` : ""}
      <div class="k" style="white-space:pre-wrap">${esc((x["文"] || "").slice(0, 300))}</div>
    </div>`).join("")}</div>`;

  return 链
    + (警.length ? `<div class="note warn">${警.join("<br>")}</div>` : "")
    + 片
    + `<div class="note">**证据串**(「业务拍板 · 2026-09-27 / 二、几星算差评 · 第 4 段」)
        不是装饰 —— 顾问要能**照着它翻回原文核对**。
        一个查不回去的引用比没有引用糟:它看起来有出处。</div>`;
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
      <button class="btn" id="f-go">看</button></div>
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
              ? `<div class="k">${esc((r["候选还差什么"] || [])[0].slice(0, 46))}</div>` : ""}
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
      <div class="sub">这一页能**做**发布那四步 ——
        出清单 / 审核 / 切指针 / 回滚。</div></div></div>
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
          : `<span class="pill warn">审过,但**不算这一份**</span>
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

async function 页_成员与权限() {
  $("#main").innerHTML = `<div class="crumb">设置 / 成员与权限</div>
    <div class="head"><div><h1>成员与权限</h1>
      <div class="sub">给的是 <b>他实际能做什么</b>,不只是角色名 ——
        「可授权」那一档<b>默认是关闭的</b>,而角色名上看不出关没关。</div></div></div>
    <div id="list"><div class="state">加载中…</div></div>`;
  try {
    const d = await 请求(`${P()}/memberships`);
    $("#list").innerHTML = `<table><thead><tr><th>工号</th><th>角色</th>
      <th>这条生效吗</th><th>专项授权</th><th>实际能做的</th></tr></thead><tbody>`
      + d["成员"].map((r) => `<tr>
        <td><b>${esc(r["工号"])}</b></td>
        <td>${esc(r["角色中文"] || r["角色"])}<div class="k">${esc(r["角色"])}</div></td>
        <td>${r["这条生效吗"] ? `<span class="pill">生效</span>`
              : `<span class="pill warn">不生效(登录那一步查不到)</span>`}</td>
        <td class="k">${esc((r["专项授权"] || []).join("、") || "—")}</td>
        <td>${(r["实际能做的"] || []).map((x) =>
              `<span class="pill">${esc(x)}</span>`).join(" ")}</td></tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        <b>能改权限的:</b> ${esc((d["能改权限的"] || []).join("、") || "(一个都没有)")}
        —— ⚠️ <b>不许把最后一个能改权限的人去掉</b>:
        改完就没人能改权限了,而那个状态<b>从接口这一侧救不回来</b>。</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
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
        <td>${r["样本数"]}</td>
        <td class="k">${esc(Object.entries(r["分档"] || {})
              .map(([k, v]) => `${k} ${v}`).join("、") || "—")}</td>
        <td>${r["冻结过几版"]}</td>
        <td>${r["能导出吗"] ? `<span class="pill">可以</span>`
              : `<span class="pill warn">不行</span>`}
          ${(r["卡在哪"] || []).length
            ? `<div class="k">${esc((r["卡在哪"] || [])[0].slice(0, 54))}</div>` : ""}
          ${r["还有一道看内容的闸"]
            ? `<div class="k">⚠️ ${esc(r["还有一道看内容的闸"].slice(0, 54))}</div>` : ""}
        </td></tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
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
    $("#list").innerHTML = `<table><thead><tr><th>产物</th><th>种类</th>
      <th>基座</th><th>标了可用吗</th><th>是 mock 训练的吗</th><th>还差什么</th>
      </tr></thead><tbody>`
      + d["产物"].map((r) => `<tr>
        <td class="k">${esc(r.id)}</td><td>${esc(r["种类"])}</td>
        <td class="k">${esc(r["基座模型"] || "—")}</td>
        <td>${r["标了可用吗"] ? `<span class="pill">可用</span>`
              : `<span class="pill warn">没标可用</span>`}</td>
        <td>${r["是mock训练的"] === true ? `<span class="pill warn">mock</span>`
              : r["是mock训练的"] === false ? `<span class="pill">真实</span>`
              : `<span class="pill warn">说不清</span>`}</td>
        <td class="k">${esc(((r["还差什么"] || [])[0] || "—").slice(0, 50))}</td>
        </tr>`).join("")
      + `</tbody></table><div class="note">${md(d.note || "")}<br>
        ⚠️ 部署三道闸:<b>没标可用</b> / <b>mock 训练的</b> /
        <b>说不清是不是 mock</b> —— 三种都拦,而它们在这张表上长得几乎一样。</div>`;
  } catch (e) { const s = 错误块(e, 路由); $("#list").innerHTML = s.html; s.挂(); }
}

async function 路由() {
  画侧栏();
  const h = location.hash || "#/workbench";
  try {
    if (h === "#/workbench") return await 页_工作台();
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
    if (h === "#/runs") return await 页_运行记录();
    if (h === "#/workflows") return await 页_工作流列表();
    if (h.startsWith("#/workflow/")) return await 页_画布(decodeURIComponent(h.slice(11)));
    if (h.startsWith("#/wfrun/")) return await 页_运行详情(decodeURIComponent(h.slice(8)));
    if (h === "#/agents") return await 页_agent列表();
    if (h.startsWith("#/agent/")) return await 页_agent配置(decodeURIComponent(h.slice(8)));
    if (h === "#/tools") return await 页_工具目录();
    if (h === "#/usage") return await 页_用量与成本();
    if (h === "#/uploads") return await 页_加资料();
    if (h === "#/kb") return await 页_知识库();
    if (h.startsWith("#/kb/")) return await 页_索引构建(decodeURIComponent(h.slice(5)));
    if (h === "#/retrieval") return await 页_检索实验室();
    if (h === "#/audit") return await 页_审计记录();
    if (h === "#/apps") return await 页_应用与发布();
    if (h.startsWith("#/app/")) return await 页_应用详情(decodeURIComponent(h.slice(6)));
    if (h === "#/conns") return await 页_模型与连接();
    if (h === "#/members") return await 页_成员与权限();
    if (h === "#/datasets") return await 页_数据集();
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
