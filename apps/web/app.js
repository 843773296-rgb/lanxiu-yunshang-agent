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

/* ── 路由 ─────────────────────────────────────────────────────── */
async function 路由() {
  画侧栏();
  const h = location.hash || "#/workbench";
  try {
    if (h === "#/workbench") return await 页_工作台();
    if (h === "#/prompts") return await 页_prompt列表();
    if (h.startsWith("#/prompt/")) return await 页_prompt详情(decodeURIComponent(h.slice(9)));
    if (h === "#/runs") return await 页_运行记录();
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
