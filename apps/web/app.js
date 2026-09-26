/* AI 管理后台 · 前端
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
  ["#/apps", "应用与发布", false],
  ["#/conns", "模型与连接", false],
  ["#/prompts", "Prompt 管理", true],
  ["grp", "编排"],
  ["#/workflows", "工作流 Workflow", true, true],
  ["#/agents", "智能体 Agent", true, true],
  ["#/tools", "工具与能力", true, true],
  ["#/human", "人工待办", false, true],
  ["grp", "知识与 RAG"],
  ["#/kb", "知识库", false, true],
  ["#/retrieval", "检索实验室", false, true],
  ["#/datasets", "数据集", false],
  ["grp", "微调训练"],
  ["#/training", "训练任务", false, true],
  ["#/artifacts", "模型产物", false, true],
  ["#/evals", "评测中心", false],
  ["#/runs", "运行记录", true],
  ["#/usage", "用量与成本", false],
  ["grp", "设置"],
  ["#/members", "成员与权限", false, true],
  ["#/audit", "审计记录", false, true],
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
      document.body.classList.add("demo");
      $("#demo").style.display = "";
      $("#demo").innerHTML = `⚠️ <b>演示模式</b>:${md(h.演示说明 || "")}`;
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
async function 路由() {
  画侧栏();
  const h = location.hash || "#/workbench";
  try {
    if (h === "#/workbench") return await 页_工作台();
    if (h === "#/prompts") return await 页_prompt列表();
    if (h.startsWith("#/prompt/")) return await 页_prompt详情(decodeURIComponent(h.slice(9)));
    if (h === "#/runs") return await 页_运行记录();
    if (h === "#/workflows") return await 页_工作流列表();
    if (h.startsWith("#/workflow/")) return await 页_画布(decodeURIComponent(h.slice(11)));
    if (h.startsWith("#/wfrun/")) return await 页_运行详情(decodeURIComponent(h.slice(8)));
    if (h === "#/agents") return await 页_agent列表();
    if (h.startsWith("#/agent/")) return await 页_agent配置(decodeURIComponent(h.slice(8)));
    if (h === "#/tools") return await 页_工具目录();
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
