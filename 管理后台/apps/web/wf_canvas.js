/* Workflow 编辑器 · 画布(交互控件详细设计 V1.0 §3–§9,W07–W20、W28、W29)
 *
 * 这一份只管「画出来、接住手势」。**图怎么改**一律交给 wf_graph.js(图逻辑)经 app.js 的 改图() ——
 * 那里记撤销、标未保存、判检查报告过期。这里不直接动定义。
 *
 * 用到 app.js 里的全局:图态 / 节点 / 元 / 业务名 / 次级标签 / 缺项 / 改图 / 撤销 / 重做 / 能改图 / 提示 /
 * 弹层 / 关弹层 / 画_面板 / 新节点 / 弹_删除 / 是敏感节点 / 步类型名 / esc / $。都在调用时才取,加载顺序无关。
 *
 * 几条设计稿里的硬要求,落在哪:
 *   · 拖动只从节点本体开始,端口 / 按钮 / 输入框不触发拖动;移动超过 4 屏幕像素才算拖(§5.1)
 *   · 拖动中连线实时跟着重画;松手只记一条历史;Esc / 失焦 / 指针取消 → 回到拖动前(§5.1)
 *   · 缩放后的位移换算成画布坐标(50% 时不会偏一倍)(§5.1)
 *   · 连线:2px 可见 + 16px 透明命中区;选中后才出端点把手;重连失败原线保留(§6.3 §6.4)
 *   · 连接点热区至少 24×24;状态不只靠颜色(图标 + 文字)(§6.1)
 *   · 拖拽都有点击替代:点出口再点目标、「下一步」下拉、位置与对齐、上移 / 下移(§5.1 §6.2 W3C 2.5.7)
 */
"use strict";

const 画布 = { W: 184, 头: 32, 口距: 24, 吸附: 8, 拖阈: 4, 最小缩放: 0.25, 最大缩放: 2 };

/* ── 视口(个人的,存本地,不算业务配置)────────────────────────────── */
function 视口() {
  const g = 图态;
  if (!g.视口) {
    let v = null;
    try { v = JSON.parse(localStorage.getItem(`wf.视口.${g.wid}`) || "null"); } catch (e) { v = null; }
    g.视口 = v && Number.isFinite(v.z) ? v : { x: 0, y: 0, z: 1, 首次: true };
  }
  return g.视口;
}
function 存视口() {
  try { const v = 视口(); localStorage.setItem(`wf.视口.${图态.wid}`, JSON.stringify({ x: v.x, y: v.y, z: v.z })); } catch (e) { /* 存不了不影响编辑 */ }
}
function 画态() {
  return 图态.画 || (图态.画 = { 工具: "选择", 选: new Set(), 线: null, 待连: null, 剪贴板: null, 小地图: true, 库开: false, 找: { 词: "", i: -1 } });   // 窄屏默认收起步骤库(§3)
}
const 位 = (id) => 图态.布局[id] || { x: 20, y: 20 };

/* ── 几何 ───────────────────────────────────────────────────────── */
function 节点高(n) {
  const 口 = 图逻辑.出口们(n, 元).length;
  return Math.max(66, 画布.头 + 34 + Math.max(0, 口 - 1) * 画布.口距);
}
function 出口边(id) { return (图态.布局[id] || {}).出口边 === "下" ? "下" : "右"; }
function 出口点(n, 口) {
  const p = 位(n.id), 口们 = 图逻辑.出口们(n, 元);
  const i = Math.max(0, 口们.findIndex((o) => 图逻辑.同口(o, 口)));
  if (出口边(n.id) === "下") return { x: p.x + 画布.W * (i + 1) / (口们.length + 1), y: p.y + 节点高(n), 向: "下" };
  return { x: p.x + 画布.W, y: p.y + 画布.头 + 12 + i * 画布.口距, 向: "右" };
}
function 入口点(n) { const p = 位(n.id); return { x: p.x, y: p.y + 画布.头 / 2 + 4 }; }
function 线路径(a, b, 折) {
  if (折 && 折.length) {
    const 点 = [a, ...折, b];
    return "M" + 点.map((q) => `${q.x},${q.y}`).join(" L");
  }
  const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
  if (a.向 === "下") return `M${a.x},${a.y} C${a.x},${a.y + dx} ${b.x - dx},${b.y} ${b.x},${b.y}`;
  return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
}
function 屏到图(cx, cy) {
  const r = $("#cv").getBoundingClientRect(), v = 视口();
  return { x: (cx - r.left - v.x) / v.z, y: (cy - r.top - v.y) / v.z };
}
function 走不到的() {
  const g = 图态, 起 = g.定义.nodes.find((n) => n.type === "start");
  if (!起) return new Set();
  const 见 = new Set([起.id]), 栈 = [起.id];
  while (栈.length) {
    const x = 栈.pop();
    (g.定义.edges || []).filter((e) => e.source === x).forEach((e) => { if (!见.has(e.target)) { 见.add(e.target); 栈.push(e.target); } });
  }
  return new Set(g.定义.nodes.filter((n) => !见.has(n.id) && !n.container).map((n) => n.id));
}

/* ── 画 ─────────────────────────────────────────────────────────── */
function 画_图() {
  const g = 图态, s = 画态(), 改 = 能改图();
  if (!$("#steps")) return;
  if (!$("#cv")) {
    $("#steps").innerHTML = `
      <div class="wftool" role="toolbar" aria-label="流程图工具">
        <span class="seg"><button data-tool="选择" aria-pressed="true">选择</button><button data-tool="手形" aria-pressed="false">拖动画布</button></span>
        <button id="wf-undo">撤销</button><button id="wf-redo">重做</button>
        <button id="wf-layout" ${改 ? "" : "disabled"}>整理布局</button>
        <span class="find"><input id="wf-find" placeholder="查找步骤" aria-label="查找步骤"><span id="wf-findmsg" class="k" role="status"></span></span>
        <button id="wf-libtg" aria-expanded="false">＋ 添加步骤</button>
        <button id="wf-import" ${改 ? "" : "disabled"}>导入步骤</button>
      </div>
      <div class="wfstage">
        <div class="wflib2" id="wf-lib"></div>
        <div class="wfcv" id="cv" tabindex="0" aria-label="流程图画布。方向键移动选中的步骤,Delete 删除,Ctrl/Cmd+Z 撤销">
          <div class="wfworld" id="wf-world"><svg id="wf-svg" class="wfsvg" width="1" height="1"></svg><div id="wf-nodes"></div>
            <svg id="wf-svg2" class="wfsvg top" width="1" height="1"></svg>
            <div id="wf-marq" class="wfmarq" hidden></div></div>
          <div class="wfedgebar" id="wf-edgebar" hidden></div>
          <div class="wfzoom" role="group" aria-label="缩放">
            <button id="wf-zo" aria-label="缩小">−</button>
            <select id="wf-zsel" aria-label="缩放比例">${[25, 50, 75, 100, 125, 150, 200].map((z) => `<option value="${z}">${z}%</option>`).join("")}</select>
            <button id="wf-zi" aria-label="放大">+</button>
            <button id="wf-fit">适应画布</button><button id="wf-loc">定位选中</button>
            <button id="wf-minitg" aria-pressed="true">小地图</button>
          </div>
          <div class="wfmini" id="wf-mini" aria-hidden="true"></div>
          <div class="wfstatus" id="wf-status" role="status"></div>
        </div>
      </div>`;
    挂画布事件();
  }
  画_库(); 画_节点(); 画_线(); 画_视口(); 画_工具条态();
  if (视口().首次) { 视口().首次 = false; 适应画布(); }
}

function 画_工具条态() {
  const s = 画态(), h = 历史();
  document.querySelectorAll("[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === s.工具)));
  const u = $("#wf-undo"), r = $("#wf-redo");
  if (u) { u.disabled = !h.能撤() || !能改图(); u.title = h.能撤() ? `撤销:${h.下一撤()}` : "没有可以撤销的编辑"; }
  if (r) { r.disabled = !h.能重() || !能改图(); r.title = h.能重() ? `重做:${h.下一重()}` : "没有可以重做的编辑"; }
  const lib = $("#wf-lib"); if (lib) lib.hidden = !s.库开 || !能改图();
  const tg = $("#wf-libtg"); if (tg) { tg.setAttribute("aria-expanded", String(s.库开)); tg.hidden = !能改图(); }
  const mini = $("#wf-mini"); if (mini) mini.hidden = !s.小地图;
  const mt = $("#wf-minitg"); if (mt) mt.setAttribute("aria-pressed", String(s.小地图));
  画_状态栏();
}

function 画_状态栏(临时) {
  const el = $("#wf-status"); if (!el) return;
  const s = 画态();
  if (临时) { el.textContent = 临时; return; }
  if (s.待连) { el.textContent = `连线中:从「${业务名(节点(s.待连.源))}」的「${s.待连.口.名}」出发 —— 点目标步骤完成,Esc 或再点一次出口取消`; return; }
  if (s.线) {
    const e = 图逻辑.找边(图态.定义, s.线);
    el.textContent = e ? `选中连线:${业务名(节点(e.source))} · ${图逻辑.口名(e)} → ${业务名(节点(e.target))}` : "";
    return;
  }
  const 选 = [...s.选].filter((id) => 节点(id));
  el.textContent = 选.length > 1 ? `选中 ${选.length} 步;一起拖动保持相对位置` :
    选.length === 1 ? `当前选中:${业务名(节点(选[0]))};移位置不影响执行顺序` : (能改图() ? "点一步选中;拖步骤移位置,从右侧圆点拖线连到下一步" : "只读:你没有改编排草稿的权限,只能查看、缩放和查找");
}

// 说明文字里的设计文档章节号(§6.1)不给用户看(10-26 改版)
const 去章节 = (t) => String(t).replace(/[(（]\s*§[^)）]*[)）]/g, "").replace(/§[\d.]+/g, "").replace(/\s{2,}/g, " ").trim();
/* ── 添加节点菜单(10-27,照 Dify「添加节点」:节点 / 工具 / 开始 三个页签)──────────────
 * 分组和顺序照 Dify:(默认组)→ 问题理解 → 逻辑 → 转换 → 工具;组内顺序也照它。
 * **Dify 有、我们还没做的照样列出来,置灰写「还没做」** —— 不藏起来(藏了就看不出离照抄还差几个),
 * 也不摆一个点了没反应的按钮(规格 §6.1:未完成的节点标「未实现」)。
 * 「工具」页签列的是我们自己的业务动作(工具注册表),选一个直接生成那个业务动作的一步。
 * ⚠️ 图标颜色每种写一整段字面 class(css_class_check 钉着拼接 class 的条数)。 */
const 图标色 = {
  蓝: (字) => `<span class="bi bi-blue">${字}</span>`, 靛: (字) => `<span class="bi bi-indigo">${字}</span>`,
  橙: (字) => `<span class="bi bi-orange">${字}</span>`, 青: (字) => `<span class="bi bi-cyan">${字}</span>`,
  紫: (字) => `<span class="bi bi-violet">${字}</span>`, 绿: (字) => `<span class="bi bi-green">${字}</span>`,
  品: (字) => `<span class="bi bi-brand">${字}</span>`,
};
// [我们的类型(没做的为 null), Dify 名, 图标字, 颜色, 没做时说明]
const 菜单节点组 = [
  ["", [["llm", "LLM", "AI", "靛"], ["retrieve", "知识检索", "检", "绿"], ["end", "输出", "出", "橙"],
        ["answer", "直接回复", "回", "橙"], ["agent", "Agent", "A", "靛"]]],
  ["问题理解", [[null, "问题分类器", "分", "绿", "还没做(一期:录音跟进按「有意向 / 没意向 / 说不清」分三路)"]]],
  ["逻辑", [["condition", "条件分支", "if", "青"], ["human", "人工介入", "人", "青"],
           ["foreach", "迭代", "迭", "青"], ["loop", "循环", "环", "青"]]],
  ["转换", [[null, "代码执行", "码", "蓝", "还没做(放进隔离沙箱,只有管理员能加)"],
           [null, "模板转换", "模", "蓝", "还没做(写一段模板拼一句话;现在的「整理字段」只能做固定几种转换)"],
           ["transform", "整理字段", "转", "蓝"], ["merge", "变量聚合器", "聚", "蓝"],   // 整理字段是我们自己的,Dify 没有对应节点
           [null, "文档提取器", "文", "绿", "暂不做(6 条流程都没有上传文件)"],
           [null, "变量赋值", "赋", "蓝", "还没做(用户 10-27 拍要做)"],
           [null, "参数提取器", "参", "蓝", "还没做"]]],
  ["工具", [[null, "HTTP 请求", "H", "紫", "还没做(只许访问登记过的地址)"], [null, "列表操作", "列", "青", "还没做"]]],
];
const 菜单开始项 = [["start", "用户输入", "入", "品"],
  [null, "定时触发器", "时", "紫", "现在在「版本与发布」页设定;挪到画布上还没做"],
  [null, "自定义 Webhook", "W", "蓝", "暂不做(二期和「访问 API」一起)"]];
function 菜单项(类型, 名, 字, 色, 没做, 附 = "") {
  const 元信息 = 类型 ? (元(类型) || {}) : {};
  const 能 = 类型 && 元信息["可用"];
  const 为什么 = 没做 || (类型 && !能 ? "还没做" : "");
  return `<div class="libit ${能 ? "" : "off"}" ${能 ? `data-lib="${esc(类型)}"` : ""} data-pv="${esc(名)}"
      data-pvs="${esc(为什么 || 去章节(去粗(元信息["说明"] || "")).slice(0, 120))}" tabindex="${能 ? 0 : -1}">
    ${(图标色[色] || 图标色.蓝)(esc(字))}<b>${esc(类型 && 步类型名[类型] || 名)}</b>${类型 && 步类型名[类型] && 步类型名[类型] !== 名 ? `<span class="k">Dify:${esc(名)}</span>` : ""}${附}
    ${能 ? "" : `<span class="k">${esc(为什么)}</span>`}</div>`;
}

function 画_库() {
  const el = $("#wf-lib"); if (!el || !能改图()) return;
  const s = 画态(); s.库页 = s.库页 || "节点"; s.库词 = s.库词 || {};
  const 页 = s.库页, 词 = s.库词[页] || "";
  const 有焦 = document.activeElement && document.activeElement.id === "wf-libq";
  const 占位 = { 节点: "搜索节点、Agent、人工、知识库", 工具: "搜索业务动作", 开始: "搜索触发器" }[页];
  let 体 = "";
  if (页 === "节点") {
    体 = 菜单节点组.map(([组, 项]) => {
      const 中 = 项.filter((x) => !词 || x[1].includes(词) || (x[0] && (步类型名[x[0]] || "").includes(词)));
      if (!中.length) return "";
      return `${组 ? `<div class="libgrp">${esc(组)}</div>` : ""}` + 中.map((x) => {
        const 已有 = x[0] === "end" && 图态.定义.nodes.some((n) => n.type === "end");
        return 已有 ? 菜单项(null, x[1], x[2], x[3], "已添加(一条流程只有一个输出)") : 菜单项(...x);
      }).join("");
    }).join("");
  } else if (页 === "工具") {
    const 工 = (图态.资源.工具 || []).filter((t) => !词 || `${t["名"]}${t["说明"] || ""}`.includes(词));
    体 = 工.map((t) => `<div class="libit" data-lib="tool" data-tool="${esc(t["版本id"])}" data-pv="${esc(t["名"])}"
        data-pvs="${esc((t["读写"] || "") + (t["接入方式"] === "lanxiu_bridge" ? " · 由澜绣执行" : "") + " · " + (t["说明"] || ""))}" tabindex="0">
        ${图标色.蓝("工")}<b>${esc(t["名"])}</b><span class="k">${esc(t["读写"] || "")}</span></div>`).join("");
    if (!(图态.资源.工具 || []).length) 体 = `<div class="k">这个项目还没有登记业务动作。</div>`;
  } else {
    体 = 菜单开始项.filter((x) => !词 || x[1].includes(词)).map((x) => {
      const 已有 = x[0] === "start" && 图态.定义.nodes.some((n) => n.type === "start");
      return 已有 ? 菜单项(null, x[1], x[2], x[3], "已添加(原始开始节点)") : 菜单项(...x);
    }).join("");
  }
  el.innerHTML = `<div class="libtabs" role="tablist">${["节点", "工具", "开始"].map((t) =>
      `<button role="tab" data-libtab="${t}" aria-selected="${t === 页}">${t}</button>`).join("")}</div>
    <input id="wf-libq" placeholder="${esc(占位)}" value="${esc(词)}" aria-label="${esc(占位)}">
    <div class="libbody">${体 || `<div class="k">未找到匹配项</div>`}</div>
    <div class="libpv" id="wf-libpv" hidden></div>
    <div class="k">点一下放到画布中间;也可以按住拖进画布。</div>`;
  el.querySelectorAll("[data-libtab]").forEach((b) => { b.onclick = () => { s.库页 = b.dataset.libtab; 画_库(); }; });
  const q = $("#wf-libq");
  q.oninput = () => { s.库词[页] = q.value; 画_库(); const q2 = $("#wf-libq"); q2.focus(); q2.setSelectionRange(q2.value.length, q2.value.length); };
  if (有焦) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  const pv = $("#wf-libpv");
  let 计时 = null;
  el.querySelectorAll(".libit").forEach((it) => {
    // 悬停 150ms 弹预览卡(Dify 同样的延迟):名称 + 说明;没做的写为什么没做
    it.onmouseenter = () => { clearTimeout(计时); 计时 = setTimeout(() => {
      pv.innerHTML = `<b>${esc(it.dataset.pv)}</b><div class="k">${esc(it.dataset.pvs || "")}</div>`; pv.hidden = false; }, 150); };
    it.onmouseleave = () => { clearTimeout(计时); pv.hidden = true; };
  });
  el.querySelectorAll(".libit:not(.off)").forEach((it) => {
    const 预设 = it.dataset.tool ? 工具预设(it.dataset.tool) : null;
    // 点一下 = 放到画布中间;按住移动超过 4px 才算拖 —— 一按下就进拖拽的话,单击也会走一遍「拖到画布外」
    let 拖了 = false;
    it.onclick = () => { if (拖了) { 拖了 = false; return; } 加到视口中间(it.dataset.lib, 预设); };
    it.onkeydown = (e) => { if (e.key === "Enter") 加到视口中间(it.dataset.lib, 预设); };
    it.onpointerdown = (ev) => {
      if (ev.button !== 0) return;
      const x0 = ev.clientX, y0 = ev.clientY;
      const 动 = (e) => { if (Math.hypot(e.clientX - x0, e.clientY - y0) > 4) { 停(); 拖了 = true; 从库拖入(e, it.dataset.lib, 预设); } };
      const 停 = () => { window.removeEventListener("pointermove", 动); window.removeEventListener("pointerup", 停); };
      window.addEventListener("pointermove", 动); window.addEventListener("pointerup", 停);
    };
  });
}
/* 「工具」页签选中一个业务动作:生成的那一步直接选好它,名字用它的名字(Dify:标题为工具名) */
function 工具预设(版本id) {
  const t = (图态.资源.工具 || []).find((x) => x["版本id"] === 版本id);
  return t ? { name: t["名"], config: { tool_version_id: 版本id } } : null;
}

function 画_节点() {
  const g = 图态, s = 画态(), 坏 = {}, 改 = 能改图();
  (g.报告?.问题 || []).forEach((p) => { if (p.node_id && p["级别"] === "blocking") 坏[p.node_id] = true; });
  const 丢 = 走不到的();
  const 失效 = new Set(图逻辑.失效引用(g.定义).map((x) => x.节点id));
  const 待 = s.待连;
  $("#wf-nodes").innerHTML = g.定义.nodes.map((n) => {
    const p = 位(n.id), 缺 = 缺项(n), 选 = s.选.has(n.id), h = 节点高(n);
    let 可连 = "";
    if (待) { const v = 图逻辑.连接校验(g.定义, 待.源, 待.口, n.id, 元); 可连 = n.id === 待.源 ? "" : (v.可以 ? "canlink" : "nolink"); }
    const 口们 = 图逻辑.出口们(n, 元), 下 = 出口边(n.id) === "下";
    const 标 = [缺.length ? `<span class="miss">缺 ${缺.length} 项</span>` : "",
      丢.has(n.id) && n.type !== "start" ? `<span class="miss" title="从开始走不到这一步">⚠ 没接进流程</span>` : "",
      失效.has(n.id) ? `<span class="miss" title="它取值的那一步已经被删了">⚠ 原来源已删除</span>` : "",
      坏[n.id] ? `<span class="miss">有要改的</span>` : ""].filter(Boolean).join(" ");
    const 跑 = 图态.运行态 && 图态.运行态[n.id];   // 试运行结果标在图上(10-26 第 4 块)
    return `<div class="wfnode2 ${选 ? "sel" : ""} ${坏[n.id] ? "bad" : ""} ${可连}"${跑 ? ` data-run="${esc(跑.状态)}"` : ""} data-id="${esc(n.id)}" tabindex="0" role="button"
        style="left:${p.x}px;top:${p.y}px;height:${h}px"
        aria-label="${esc(业务名(n) + "," + 次级标签(n) + (缺.length ? ",缺 " + 缺.length + " 项" : "") + (选 ? ",已选中" : ""))}">
      <div class="nh"><span class="t">${esc(业务名(n))}${typeof 同名后缀 === "function" ? 同名后缀(n) : ""}</span>${typeof 运行标 === "function" ? 运行标(n.id) : ""}
        ${改 && typeof 单测类型 !== "undefined" && 单测类型[n.type] ? `<button class="run1" data-run1="${esc(n.id)}" title="单独测这一步" aria-label="单独测「${esc(业务名(n))}」这一步" tabindex="-1">▶</button>` : ""}
        ${改 || n.type !== "start" ? `<button class="more" data-more="${esc(n.id)}" aria-label="更多操作" tabindex="-1">⋯</button>` : ""}</div>
      <div class="k">${esc(次级标签(n))}</div><div class="tags">${标}</div>
      ${n.type === "start" ? "" : `<span class="wfport in" data-in="${esc(n.id)}" title="入口" aria-hidden="true"></span>`}
      ${口们.map((o, i) => `<button class="wfport out ${下 ? "down" : ""} ${o.port === "error" ? "err" : ""}" data-out="${esc(n.id)}" data-oi="${i}"
          style="${下 ? `left:${(画布.W * (i + 1) / (口们.length + 1)) - 12}px;top:${h - 12}px` : `top:${画布.头 + i * 画布.口距}px`}"
          aria-label="${esc(业务名(n))} 的出口:${esc(o.名)}${(g.定义.edges || []).some((e) => e.source === n.id && 图逻辑.同口(e, o)) ? "(已连接)" : "(未连接)"}"
          ${改 ? "" : "disabled"}><i></i><span class="pl">${esc(o.名)}</span></button>`).join("")}
    </div>`;
  }).join("");
}

function 画_线(拖中 = null) {
  const g = 图态, s = 画态(), 折们 = (g.布局.$线 || {});
  let 宽 = 800, 高 = 500;
  g.定义.nodes.forEach((n) => { const p = 位(n.id); 宽 = Math.max(宽, p.x + 画布.W + 200); 高 = Math.max(高, p.y + 节点高(n) + 200); });
  const 段 = (g.定义.edges || []).map((e) => {
    const a = 节点(e.source), b = 节点(e.target);
    if (!a || !b) return "";
    const 键 = 图逻辑.边键(e), p = 出口点(a, { port: e.port, branch_key: e.branch_key ?? null }), q = 入口点(b);
    const 折 = 折们[键], d = 线路径(p, q, 折), 选 = s.线 === 键;
    const 标 = e.port === "branch" ? (e.branch_key === "else" ? "都不满足" : e.branch_key) : (e.port === "error" ? "失败时" : "");
    const 中 = 折 && 折.length ? 折[Math.floor(折.length / 2)] : { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 };
    return `<g class="edge ${选 ? "sel" : ""} ${e.port === "error" ? "err" : ""}">
        <path class="hit" d="${d}" data-edge="${esc(键)}"/>
        <path class="vis" d="${d}"/>
        ${标 ? `<text x="${中.x}" y="${中.y - 6}" text-anchor="middle">${esc(标)}</text>` : ""}
      </g>`;
  }).join("");
  const 临 = 拖中 ? `<path class="temp ${拖中.坏 ? "bad" : ""}" d="${线路径(拖中.a, 拖中.b)}"/>` : "";
  const svg = $("#wf-svg");
  svg.setAttribute("width", 宽); svg.setAttribute("height", 高);
  svg.innerHTML = 段;
  // 选中那条线的端点把手 / 折点 / 拖线时的临时线画在**步骤卡片上面**一层 ——
  // 画在下面的话,终点把手正好压在目标步骤的左边缘,按下去拿到的是步骤,于是「拖端点」变成了「拖走整个步骤」
  // (2026-10-25 真浏览器测试逮到的)。把手半径随缩放反向调,屏幕上始终约 9 像素。
  const 顶 = $("#wf-svg2"), 半 = Math.max(7, 9 / 视口().z);
  let 把手 = "";
  const se = s.线 && 能改图() && 图逻辑.找边(g.定义, s.线);
  if (se && 节点(se.source) && 节点(se.target)) {
    const p = 出口点(节点(se.source), { port: se.port, branch_key: se.branch_key ?? null }), q = 入口点(节点(se.target));
    把手 = `<circle class="endh" data-endh="src" cx="${p.x}" cy="${p.y}" r="${半}"><title>拖动换起点</title></circle>
      <circle class="endh" data-endh="dst" cx="${q.x}" cy="${q.y}" r="${半}"><title>拖动换终点</title></circle>`
      + ((折们[s.线]) || []).map((b, i) => `<rect class="bend" data-bend="${i}" x="${b.x - 半}" y="${b.y - 半}" width="${半 * 2}" height="${半 * 2}"/>`).join("");
  }
  顶.setAttribute("width", 宽); 顶.setAttribute("height", 高);
  顶.innerHTML = 把手 + 临;
  画_线工具条();
  画_小地图();
}

function 画_线工具条() {
  const bar = $("#wf-edgebar"), s = 画态();
  const e = s.线 && 图逻辑.找边(图态.定义, s.线);
  if (!bar) return;
  if (!e || !节点(e.source) || !节点(e.target)) { bar.hidden = true; s.线 = e ? s.线 : null; return; }
  const p = 出口点(节点(e.source), { port: e.port, branch_key: e.branch_key ?? null }), q = 入口点(节点(e.target)), v = 视口();
  const 折 = (图态.布局.$线 || {})[s.线];
  bar.hidden = false;
  bar.style.left = `${((p.x + q.x) / 2) * v.z + v.x}px`;
  bar.style.top = `${((p.y + q.y) / 2) * v.z + v.y + 14}px`;
  const 改 = 能改图();
  bar.innerHTML = `<span class="k">${esc(业务名(节点(e.source)))} · ${esc(图逻辑.口名(e))} → ${esc(业务名(节点(e.target)))}</span>
    ${改 ? `<button data-eb="ins">插入步骤</button><button data-eb="re">重新连接</button>
      <button data-eb="bend">加折点</button>${折 ? `<button data-eb="auto">恢复自动布线</button>` : ""}
      <button data-eb="del" class="danger">删除连线</button>` : ""}`;
  bar.querySelectorAll("[data-eb]").forEach((b) => { b.onclick = () => 线工具(b.dataset.eb); });
}

function 画_视口() {
  const v = 视口(), w = $("#wf-world");
  if (!w) return;
  w.style.transform = `translate(${v.x}px,${v.y}px) scale(${v.z})`;
  const sel = $("#wf-zsel"), 百 = Math.round(v.z * 100);
  if (sel) {
    if (![...sel.options].some((o) => +o.value === 百)) {
      [...sel.options].filter((o) => o.dataset.tmp).forEach((o) => o.remove());
      const o = document.createElement("option"); o.value = 百; o.textContent = `${百}%`; o.dataset.tmp = "1"; sel.appendChild(o);
    }
    sel.value = String(百);
  }
  const zo = $("#wf-zo"), zi = $("#wf-zi"), loc = $("#wf-loc");
  if (zo) zo.disabled = v.z <= 画布.最小缩放 + 1e-6;
  if (zi) zi.disabled = v.z >= 画布.最大缩放 - 1e-6;
  if (loc) loc.disabled = !画态().选.size;
  画_线工具条(); 画_小地图();
}

function 画_小地图() {
  const m = $("#wf-mini"), cv = $("#cv");
  if (!m || m.hidden || !cv) return;
  const ns = 图态.定义.nodes;
  if (!ns.length) { m.innerHTML = ""; return; }
  const xs = ns.map((n) => 位(n.id).x), ys = ns.map((n) => 位(n.id).y);
  const x0 = Math.min(...xs) - 40, y0 = Math.min(...ys) - 40, x1 = Math.max(...xs) + 画布.W + 40, y1 = Math.max(...ys) + 120;
  const MW = 180, MH = 120, k = Math.min(MW / (x1 - x0), MH / (y1 - y0));
  const v = 视口(), r = cv.getBoundingClientRect();
  const vx = (-v.x / v.z - x0) * k, vy = (-v.y / v.z - y0) * k, vw = (r.width / v.z) * k, vh = (r.height / v.z) * k;
  m.innerHTML = `<svg width="${MW}" height="${MH}">${ns.map((n) => { const p = 位(n.id);
      return `<rect x="${(p.x - x0) * k}" y="${(p.y - y0) * k}" width="${画布.W * k}" height="${节点高(n) * k}" class="${画态().选.has(n.id) ? "s" : ""}"/>`; }).join("")}
    <rect class="vp" x="${vx}" y="${vy}" width="${vw}" height="${vh}"/></svg>`;
  m.dataset.k = k; m.dataset.x0 = x0; m.dataset.y0 = y0;
}

/* ── 视口操作 ───────────────────────────────────────────────────── */
function 缩放到(z, 锚 = null) {
  const v = 视口(), cv = $("#cv"); if (!cv) return;
  z = Math.min(画布.最大缩放, Math.max(画布.最小缩放, z));
  const r = cv.getBoundingClientRect();
  const a = 锚 || { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  const 图点 = 屏到图(a.x, a.y);
  v.z = z; v.x = a.x - r.left - 图点.x * z; v.y = a.y - r.top - 图点.y * z;
  画_视口(); 存视口();
}
function 适应画布() {
  const cv = $("#cv"), ns = 图态.定义.nodes; if (!cv || !ns.length) return;
  const r = cv.getBoundingClientRect(), 边 = 40;
  // 全屏编排页的工具条浮在画布顶上、缩放条和小地图在底下(10-26):适应时上下各让出它们的高度,别让步骤藏在工具条底下
  const 上 = document.body.classList.contains("wf-full") ? 64 : 0, 下 = document.body.classList.contains("wf-full") ? 56 : 0;
  const xs = ns.map((n) => 位(n.id).x), ys = ns.map((n) => 位(n.id).y);
  const x0 = Math.min(...xs), y0 = Math.min(...ys), x1 = Math.max(...ns.map((n) => 位(n.id).x + 画布.W)), y1 = Math.max(...ns.map((n) => 位(n.id).y + 节点高(n)));
  const z = Math.min(1, Math.max(画布.最小缩放, Math.min((r.width - 边 * 2) / Math.max(1, x1 - x0), (r.height - 边 * 2 - 上 - 下) / Math.max(1, y1 - y0))));
  const v = 视口(); v.z = z || 1; v.x = 边 - x0 * v.z; v.y = 边 + 上 - y0 * v.z;
  画_视口(); 存视口();
}
function 定位到(ids) {
  const cv = $("#cv"); if (!cv || !ids.length) return;
  const r = cv.getBoundingClientRect(), v = 视口();
  const ps = ids.map((id) => 位(id));
  const cx = (Math.min(...ps.map((p) => p.x)) + Math.max(...ps.map((p) => p.x)) + 画布.W) / 2;
  const cy = (Math.min(...ps.map((p) => p.y)) + Math.max(...ps.map((p) => p.y)) + 60) / 2;
  v.x = r.width / 2 - cx * v.z; v.y = r.height / 2 - cy * v.z;
  画_视口(); 存视口();
}

/* ── 选择 ───────────────────────────────────────────────────────── */
function 选节点(ids, { 追加 = false, 切换 = false } = {}) {
  const s = 画态();
  if (!追加 && !切换) s.选 = new Set();
  ids.forEach((id) => { if (切换 && s.选.has(id)) s.选.delete(id); else s.选.add(id); });
  s.线 = null;
  图态.选中 = s.选.size === 1 ? [...s.选][0] : (s.选.size ? 图态.选中 : null);
  if (图态.选中 && !s.选.has(图态.选中)) 图态.选中 = [...s.选][0] || null;
  画_节点(); 画_线(); 画_面板(); 画_状态栏(); 画_视口();
}
function 选线(键) {
  const s = 画态(); s.线 = 键; s.选 = new Set();
  画_节点(); 画_线(); 画_状态栏();
}
function 清理选择() {
  const s = 画态();
  s.选 = new Set([...s.选].filter((id) => 节点(id)));
  if (s.线 && !图逻辑.找边(图态.定义, s.线)) s.线 = null;
  if (图态.选中 && !节点(图态.选中)) 图态.选中 = null;
}

/* ── 事件 ───────────────────────────────────────────────────────── */
function 挂画布事件() {
  const cv = $("#cv"), s = 画态();
  document.querySelectorAll("[data-tool]").forEach((b) => { b.onclick = () => { s.工具 = b.dataset.tool; 画_工具条态(); cv.focus(); }; });
  $("#wf-undo").onclick = () => 撤销();
  $("#wf-redo").onclick = () => 重做();
  $("#wf-layout").onclick = 整理布局;
  $("#wf-libtg").onclick = () => { s.库开 = !s.库开; 画_工具条态(); };
  $("#wf-import").onclick = 弹_导入;
  $("#wf-minitg").onclick = () => { s.小地图 = !s.小地图; 画_工具条态(); 画_小地图(); };
  $("#wf-zo").onclick = () => 缩放到(视口().z - 0.25);
  $("#wf-zi").onclick = () => 缩放到(视口().z + 0.25);
  $("#wf-zsel").onchange = (e) => 缩放到(+e.target.value / 100);
  $("#wf-fit").onclick = 适应画布;
  $("#wf-loc").onclick = () => 定位到([...s.选]);
  $("#wf-find").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); 查找(e.target.value, e.shiftKey ? -1 : 1); } };
  $("#wf-mini").onpointerdown = 小地图拖;
  cv.addEventListener("pointerdown", 画布按下);
  cv.addEventListener("wheel", 画布滚轮, { passive: false });
  cv.addEventListener("dblclick", (ev) => {
    const nd = ev.target.closest(".wfnode2");
    if (nd && 能改图() && ev.target.closest(".t")) 重命名节点(nd.dataset.id);
  });
  cv.addEventListener("click", (ev) => {
    const m = ev.target.closest("[data-more]");
    if (m) { ev.stopPropagation(); 节点菜单(m.dataset.more, m); }
    // 节点上的 ▶(照 Dify 单步运行):选中这一步,右侧面板直接到「试这一步」,光标放在第一个要填的框 ——
    // 填什么、用什么跑法、写入类只能连接测试,都沿用面板里那一份(不在卡片上另做一份表单)
    const r1 = ev.target.closest("[data-run1]");
    if (r1) {
      ev.stopPropagation(); 选节点([r1.dataset.run1]);
      const 段 = document.querySelector('#pn [data-sec="试这一步"]');
      if (段) { 段.scrollIntoView({ block: "start" }); const 框 = 段.querySelector("textarea[data-st]") || $("#st-go"); if (框) 框.focus(); }
    }
  });
  // 右键菜单和「⋯」/ 连线工具条是同一套能力(§9:右键菜单和工具条提供相同能力,菜单关闭后焦点回原对象)
  cv.addEventListener("contextmenu", (ev) => {
    const nd = ev.target.closest(".wfnode2"), ed = ev.target.closest("[data-edge]");
    if (nd) { ev.preventDefault(); if (!画态().选.has(nd.dataset.id)) 选节点([nd.dataset.id]); 节点菜单(nd.dataset.id, nd); }
    else if (ed) { ev.preventDefault(); 选线(ed.dataset.edge); }
  });
  cv.addEventListener("keydown", 画布按键);
  cv.addEventListener("keyup", (e) => { if (e.key === " " && s.空格) { s.空格 = false; 画_状态栏(); } });
}

function 是输入(t) { return t && t.closest && t.closest("input,textarea,select,[contenteditable]"); }

function 画布按下(ev) {
  const s = 画态(), t = ev.target;
  if (是输入(t)) return;
  if (ev.button === 2) return;              // 右键留给上下文菜单
  const out = t.closest("[data-out]");
  if (out && 能改图()) { ev.preventDefault(); return 出口按下(ev, out); }
  if (t.closest("[data-more]") || t.closest("[data-run1]")) return;
  const eh = t.closest("[data-endh]");
  if (eh && 能改图()) { ev.preventDefault(); return 拖端点(ev, eh.dataset.endh); }
  const bd = t.closest("[data-bend]");
  if (bd && 能改图()) { ev.preventDefault(); return 拖折点(ev, +bd.dataset.bend); }
  const ed = t.closest("[data-edge]");
  if (ed) { ev.preventDefault(); if (s.待连) 取消连线(); return 选线(ed.dataset.edge); }
  const nd = t.closest(".wfnode2");
  if (nd) {
    if (s.待连) { ev.preventDefault(); return 完成连线(nd.dataset.id); }
    return 节点按下(ev, nd);
  }
  if (s.待连) { 取消连线(); return; }
  if (ev.button === 1 || s.工具 === "手形" || s.空格) { ev.preventDefault(); return 平移(ev); }
  if (ev.button === 0) return 框选(ev);
}

/* 一个指针手势的通用骨架:捕获指针、超过阈值才算拖、Esc / 失焦 / 取消都走 取消()。
 * ⚠️ 失焦不收尾的话,松开鼠标时浏览器不在前台,节点会一直跟着鼠标(§5.1) */
function 手势(ev, { 移, 完, 取消: 撤 = () => {}, 阈 = 画布.拖阈 }) {
  const cv = $("#cv"), x0 = ev.clientX, y0 = ev.clientY;
  let 拖了 = false, 结束 = false;
  try { cv.setPointerCapture(ev.pointerId); } catch (e) { /* 桩环境没有 */ }
  const 收 = () => {
    结束 = true;
    cv.removeEventListener("pointermove", m); cv.removeEventListener("pointerup", u);
    cv.removeEventListener("pointercancel", c); window.removeEventListener("blur", c); window.removeEventListener("keydown", k, true);
  };
  const m = (e) => {
    if (!拖了 && Math.hypot(e.clientX - x0, e.clientY - y0) <= 阈) return;
    // 拖动中浮层(连线工具条 / 缩放 / 小地图)不接鼠标:不然松手时拿到的是盖在目标步骤上的工具条(真浏览器测试逮到的)
    if (!拖了) cv.classList.add("dragging");
    拖了 = true; 移(e, e.clientX - x0, e.clientY - y0);
  };
  // ⚠️ 先判落点、再让浮层恢复接鼠标 —— 反过来的话,松手那一刻 elementFromPoint 拿到的是盖在目标上的连线工具条
  const u = (e) => { if (结束) return; 收(); try { 完(e, 拖了); } finally { cv.classList.remove("dragging"); } };
  const c = () => { if (结束) return; 收(); try { 撤(); } finally { cv.classList.remove("dragging"); } };
  const k = (e) => { if (e.key === "Escape") { e.stopPropagation(); c(); } };
  cv.addEventListener("pointermove", m); cv.addEventListener("pointerup", u);
  cv.addEventListener("pointercancel", c); window.addEventListener("blur", c); window.addEventListener("keydown", k, true);
  return { 取消: c };
}

let _帧 = 0;
function 下一帧重画线() {
  if (_帧) return;
  const 请 = (typeof requestAnimationFrame === "function") ? requestAnimationFrame : (f) => setTimeout(f, 16);
  _帧 = 请(() => { _帧 = 0; 画_线(画态().拖线 || null); });
}

function 节点按下(ev, nd) {
  const s = 画态(), id = nd.dataset.id, cv = $("#cv");
  cv.focus({ preventScroll: true });
  const 追加 = ev.ctrlKey || ev.metaKey;
  if (ev.shiftKey && !追加) { /* Shift 点节点也当追加选择 */ }
  const 一起 = s.选.has(id) && !追加 ? [...s.选] : [id];
  if (!能改图() || ev.button !== 0) { 选节点([id], { 切换: 追加 }); return; }
  const 起 = {}; 一起.forEach((k) => { 起[k] = { ...位(k) }; });
  const 前 = 图逻辑.快照(图态.定义, 图态.布局), z = 视口().z;
  const 吸 = (v) => (s.不吸附 ? Math.round(v) : Math.round(v / 画布.吸附) * 画布.吸附);
  手势(ev, {
    移: (e, dx, dy) => {
      一起.forEach((k) => {
        const p = { x: Math.max(0, 吸(起[k].x + dx / z)), y: Math.max(0, 吸(起[k].y + dy / z)) };
        图态.布局[k] = { ...(图态.布局[k] || {}), ...p };
        const el = document.querySelector(`.wfnode2[data-id="${CSS.escape(k)}"]`);
        if (el) { el.style.left = p.x + "px"; el.style.top = p.y + "px"; }
      });
      边缘平移(e);
      下一帧重画线();
    },
    完: (e, 拖了) => {
      if (!拖了) { 选节点([id], { 切换: 追加 }); return; }
      const 后 = 图逻辑.快照(图态.定义, 图态.布局);
      if (历史().记(一起.length > 1 ? `移动 ${一起.length} 步` : `移动「${业务名(节点(id))}」`, 前, 后)) 标脏();
      if (!s.选.has(id)) 选节点([id]); else { 画_节点(); 画_线(); }
      画_工具条态();
    },
    取消: () => { 一起.forEach((k) => { 图态.布局[k] = { ...(图态.布局[k] || {}), ...起[k] }; }); 画_节点(); 画_线(); 画_状态栏("已取消拖动,回到原位"); },
  });
}

function 边缘平移(e) {
  const cv = $("#cv"), r = cv.getBoundingClientRect(), v = 视口(), 带 = 28;
  let dx = 0, dy = 0;
  if (e.clientX < r.left + 带) dx = 12; else if (e.clientX > r.right - 带) dx = -12;
  if (e.clientY < r.top + 带) dy = 12; else if (e.clientY > r.bottom - 带) dy = -12;
  if (dx || dy) { v.x += dx; v.y += dy; 画_视口(); }
}

function 平移(ev) {
  const v = 视口(), x0 = v.x, y0 = v.y, cv = $("#cv");
  cv.classList.add("panning");
  手势(ev, {
    阈: 0,
    移: (e, dx, dy) => { v.x = x0 + dx; v.y = y0 + dy; 画_视口(); },
    完: () => { cv.classList.remove("panning"); 存视口(); },
    取消: () => { cv.classList.remove("panning"); v.x = x0; v.y = y0; 画_视口(); },
  });
}

function 框选(ev) {
  const s = 画态(), 起 = 屏到图(ev.clientX, ev.clientY), mq = $("#wf-marq"), 追加 = ev.shiftKey;
  $("#cv").focus({ preventScroll: true });
  手势(ev, {
    移: (e) => {
      const p = 屏到图(e.clientX, e.clientY);
      const x = Math.min(起.x, p.x), y = Math.min(起.y, p.y), w = Math.abs(p.x - 起.x), h = Math.abs(p.y - 起.y);
      mq.hidden = false; Object.assign(mq.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
      s.框 = { x, y, w, h };
    },
    完: (e, 拖了) => {
      mq.hidden = true;
      if (!拖了) { s.选 = new Set(); s.线 = null; 图态.选中 = null; 画_节点(); 画_线(); 画_面板(); 画_状态栏(); 画_视口(); return; }
      const b = s.框; s.框 = null;
      // 只选**被框完整包住**的节点;框里经过的线不算选中(§5.3)
      const 中 = 图态.定义.nodes.filter((n) => { const p = 位(n.id);
        return p.x >= b.x && p.y >= b.y && p.x + 画布.W <= b.x + b.w && p.y + 节点高(n) <= b.y + b.h; }).map((n) => n.id);
      选节点(中, { 追加 });
    },
    取消: () => { mq.hidden = true; s.框 = null; },
  });
}

function 画布滚轮(ev) {
  const cv = $("#cv");
  // 只在画布有焦点时接管滚轮 —— 不然鼠标路过画布,整页就滚不动了(§9)
  if (document.activeElement !== cv && !cv.contains(document.activeElement)) return;
  ev.preventDefault();
  if (ev.ctrlKey || ev.metaKey) { 缩放到(视口().z * (ev.deltaY < 0 ? 1.1 : 1 / 1.1), { x: ev.clientX, y: ev.clientY }); return; }
  const v = 视口(); v.x -= ev.deltaX; v.y -= ev.deltaY; 画_视口(); 存视口();
}

function 小地图拖(ev) {
  const m = $("#wf-mini"), k = +m.dataset.k, x0 = +m.dataset.x0, y0 = +m.dataset.y0;
  if (!k) return;
  ev.preventDefault(); ev.stopPropagation();
  const 到 = (e) => {
    const r = m.getBoundingClientRect(), cv = $("#cv").getBoundingClientRect(), v = 视口();
    const gx = (e.clientX - r.left) / k + x0, gy = (e.clientY - r.top) / k + y0;
    v.x = cv.width / 2 - gx * v.z; v.y = cv.height / 2 - gy * v.z; 画_视口();
  };
  到(ev);
  const mv = (e) => 到(e), up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); 存视口(); };
  window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
}

/* ── 连线 ───────────────────────────────────────────────────────── */
function 出口按下(ev, el) {
  const s = 画态(), 源 = el.dataset.out, n = 节点(源), 口 = 图逻辑.出口们(n, 元)[+el.dataset.oi];
  if (s.待连 && s.待连.源 === 源 && 图逻辑.同口(s.待连.口, 口)) { 取消连线(); return; }    // 再点一次原点 = 取消
  const a = 出口点(n, 口);
  手势(ev, {
    移: (e) => {
      const b = 屏到图(e.clientX, e.clientY);
      const 下 = document.elementFromPoint ? document.elementFromPoint(e.clientX, e.clientY) : null;
      const nd = 下 && 下.closest && 下.closest(".wfnode2");
      let 坏 = false, 提 = "松到目标步骤上完成连接,松到空白处取消";
      if (nd && nd.dataset.id !== 源) {
        const v = 图逻辑.连接校验(图态.定义, 源, 口, nd.dataset.id, 元);
        坏 = !v.可以; 提 = v.可以 ? (v.替换 ? `松开:把「${口.名}」的下一步从「${业务名(节点(v.替换.target))}」改成「${业务名(节点(nd.dataset.id))}」` : `松开连到「${业务名(节点(nd.dataset.id))}」`) : `不能连:${v.为什么}`;
      }
      s.拖线 = { a, b, 坏 }; 画_状态栏(提); 边缘平移(e); 下一帧重画线();
    },
    完: (e, 拖了) => {
      s.拖线 = null;
      if (!拖了) { s.待连 = { 源, 口 }; s.线 = null; 画_节点(); 画_线(); 画_状态栏(); return; }   // 点一下 = 进入「点目标」模式
      const 下 = document.elementFromPoint ? document.elementFromPoint(e.clientX, e.clientY) : null;
      const nd = 下 && 下.closest && 下.closest(".wfnode2");
      画_线();
      if (!nd || nd.dataset.id === 源) { 画_状态栏("没连 —— 松在空白处不会新建步骤"); return; }
      连上(源, 口, nd.dataset.id);
    },
    取消: () => { s.拖线 = null; 画_线(); 画_状态栏("已取消连线"); },
  });
}
function 完成连线(目标) {
  const s = 画态(), 待 = s.待连;
  s.待连 = null;
  if (目标 === 待.源) { 画_节点(); 画_状态栏("已取消连线"); return; }
  连上(待.源, 待.口, 目标);
}
function 取消连线() { 画态().待连 = null; 画_节点(); 画_线(); 画_状态栏("已取消连线"); }

/* 图上连和「下一步」下拉走同一个函数:单目标出口再连 → 预览替换、确认后原子替换(§6.2) */
function 连上(源, 口, 目标, { 已确认 = false } = {}) {
  const v = 图逻辑.连接校验(图态.定义, 源, 口, 目标, 元);
  if (!v.可以) { 提示(`不能连:${v.为什么}`); 画_节点(); return false; }
  if (v.替换 && !已确认) {
    弹层("替换下一步", `<p>「${esc(业务名(节点(源)))}」的「${esc(口.名)}」现在接的是 <b>${esc(业务名(节点(v.替换.target)))}</b>。</p>
      <p>将把下一步从 <b>${esc(业务名(节点(v.替换.target)))}</b> 改为 <b>${esc(业务名(节点(目标)))}</b> —— 一个出口只接一个去向,不会两条线同时执行。</p>
      <div class="acts"><button class="pri" id="rp-ok">替换</button> <button id="rp-no">取消</button></div>`);
    $("#rp-no").onclick = () => { 关弹层(); 画_节点(); };
    $("#rp-ok").onclick = () => { 关弹层(); 连上(源, 口, 目标, { 已确认: true }); };
    return false;
  }
  改图(`连线:${业务名(节点(源))} → ${业务名(节点(目标))}`, () => { 图逻辑.连(图态.定义, 源, 口, 目标); 剪折点(); });
  const 缺 = 缺项(节点(目标));
  提示(v.替换 ? `已把下一步改为「${业务名(节点(目标))}」` : `已连接「${业务名(节点(源))}」→「${业务名(节点(目标))}」`
    + (缺.length ? `;仍需配置:${缺.map(中文名).join("、")}` : ""), { 撤销: true });
  return true;
}
function 剪折点() {
  const 在 = new Set((图态.定义.edges || []).map(图逻辑.边键));
  if (图态.布局.$线) Object.keys(图态.布局.$线).forEach((k) => { if (!在.has(k)) delete 图态.布局.$线[k]; });
}

function 删线(键) {
  const e = 图逻辑.找边(图态.定义, 键); if (!e) return;
  const 名 = `${业务名(节点(e.source))} → ${业务名(节点(e.target))}`;
  const 丢前 = 走不到的();
  改图(`删除连线 ${名}`, () => { 图逻辑.删边(图态.定义, 键); 剪折点(); });
  画态().线 = null;
  const 新丢 = [...走不到的()].filter((id) => !丢前.has(id));
  提示(`已断开「${名}」` + (新丢.length ? `;「${新丢.map((id) => 业务名(节点(id))).join("、")}」从开始走不到了` : ""), { 撤销: true });
  if (新丢.length) 定位到(新丢);
  画_线(); 画_状态栏();
}

function 拖端点(ev, 哪头) {
  const s = 画态(), 键 = s.线, e = 图逻辑.找边(图态.定义, 键); if (!e) return;
  const a0 = 出口点(节点(e.source), { port: e.port, branch_key: e.branch_key ?? null }), b0 = 入口点(节点(e.target));
  手势(ev, {
    移: (m) => {
      const p = 屏到图(m.clientX, m.clientY);
      s.拖线 = 哪头 === "dst" ? { a: a0, b: p } : { a: p, b: b0 }; 下一帧重画线();
    },
    完: (m, 拖了) => {
      s.拖线 = null; 画_线();
      if (!拖了) return;
      const 下 = document.elementFromPoint ? document.elementFromPoint(m.clientX, m.clientY) : null;
      const nd = 下 && 下.closest && 下.closest(".wfnode2");
      if (!nd) { 提示("未更改连接 —— 原线保留(要断开请用「删除连线」)"); return; }
      let 改 = {};
      if (哪头 === "dst") 改 = { target: nd.dataset.id };
      else {
        const po = 下.closest("[data-out]"), n = 节点(nd.dataset.id), 口们 = 图逻辑.出口们(n, 元);
        const 口 = po ? 口们[+po.dataset.oi] : 口们.find((o) => o.port === e.port && (e.port !== "branch" || o.branch_key === e.branch_key)) || 口们[0];
        if (!口) { 提示("那一步没有出口,未更改连接"); return; }
        改 = { source: nd.dataset.id, 口 };
      }
      重连(键, 改);
    },
    取消: () => { s.拖线 = null; 画_线(); 提示("未更改连接"); },
  });
}
function 重连(键, 改) {
  const 试 = JSON.parse(JSON.stringify(图态.定义));
  const v = 图逻辑.重连(试, 键, 改, 元);
  if (!v.可以) { 提示(v.没变 ? "未更改连接" : `没改:${v.为什么} —— 原线保留`); return false; }
  改图("重新连接", () => { 图逻辑.重连(图态.定义, 键, 改, 元); 剪折点(); });
  画态().线 = v.新键;
  提示(v.换了起点 ? "已改连接的起点 —— 出口变了,这条路什么时候走也跟着变了,请核对" : "已改连接的终点", { 撤销: true });
  画_线(); 画_状态栏();
  return true;
}

function 拖折点(ev, i) {
  const s = 画态(), 键 = s.线, 折 = ((图态.布局.$线 || {})[键] || []);
  if (!折[i]) return;
  const 前 = 图逻辑.快照(图态.定义, 图态.布局), 起 = { ...折[i] }, z = 视口().z;
  手势(ev, {
    移: (e, dx, dy) => { 折[i] = { x: Math.round(起.x + dx / z), y: Math.round(起.y + dy / z) }; 下一帧重画线(); },
    完: (e, 拖了) => { if (拖了 && 历史().记("挪折点", 前, 图逻辑.快照(图态.定义, 图态.布局))) 标脏(); },
    取消: () => { 折[i] = 起; 画_线(); },
  });
}

function 线工具(动作) {
  const s = 画态(), 键 = s.线, e = 图逻辑.找边(图态.定义, 键); if (!e) return;
  if (动作 === "del") return 删线(键);
  if (动作 === "ins") return 弹_插入到线(键);
  if (动作 === "re") return 弹_重新连接(键);
  if (动作 === "bend") {
    const p = 出口点(节点(e.source), { port: e.port, branch_key: e.branch_key ?? null }), q = 入口点(节点(e.target));
    改图("加折点", () => { const t = (图态.布局.$线 = 图态.布局.$线 || {}); (t[键] = t[键] || []).push({ x: Math.round((p.x + q.x) / 2), y: Math.round((p.y + q.y) / 2) + 30 }); });
    提示("加了一个折点:拖小方块调整线的走向;只改画法,不改执行逻辑", { 撤销: true });
  }
  if (动作 === "auto") { 改图("恢复自动布线", () => { delete 图态.布局.$线[键]; }); 提示("已恢复自动布线", { 撤销: true }); }
}

function 弹_插入到线(键) {
  const e = 图逻辑.找边(图态.定义, 键);
  const 类 = 图态.节点库.filter((x) => x["可用"] && !["start", "end"].includes(x["名"]));
  弹层("在这条线上插入一步", `<p class="k">${esc(业务名(节点(e.source)))} · ${esc(图逻辑.口名(e))} → <b>新的一步</b> → ${esc(业务名(节点(e.target)))}</p>
    ${类.map((x, i) => { const 能 = 图逻辑.能插入吗(x["名"], 元);
      return `<label class="tpl ${能.可以 ? "" : "off"}"><input type="radio" name="ins-t" value="${esc(x["名"])}" ${能.可以 ? "" : "disabled"} ${i === 0 && 能.可以 ? "checked" : ""}>
        <b>${esc(步类型名[x["名"]] || x["中文"])}</b> ${能.可以 ? "" : `<span class="k">—— ${esc(能.为什么)}</span>`}</label>`; }).join("")}
    <div class="acts"><button class="pri" id="ins-ok">插入</button> <button id="ins-no">取消</button></div>`);
  $("#ins-no").onclick = 关弹层;
  $("#ins-ok").onclick = () => {
    const t = (document.querySelector('input[name="ins-t"]:checked') || {}).value;
    if (!t) return;
    关弹层();
    let 新 = null;
    改图(`插入「${步类型名[t] || t}」`, () => {
      const n = 新节点(t);
      const r = 图逻辑.插入到线(图态.定义, 键, n, 元);
      if (!r.可以) { 提示(r.为什么); return false; }
      const a = 位(e.source), b = 位(e.target);
      图态.布局[n.id] = { x: Math.round((a.x + b.x) / 2 / 8) * 8, y: Math.round((a.y + b.y) / 2 / 8) * 8 + 40 };
      剪折点(); 新 = n.id;
    });
    if (新) { 选节点([新]); 提示(`已插入「${业务名(节点(新))}」—— 它还需要配置`, { 撤销: true }); }
  };
}

function 弹_重新连接(键) {
  const e = 图逻辑.找边(图态.定义, 键);
  const 起点们 = 图态.定义.nodes.filter((n) => n.type !== "end").flatMap((n) => 图逻辑.出口们(n, 元).map((o, i) => [`${n.id}|${i}`, `${业务名(n)} · ${o.名}`]));
  const 终点们 = 图态.定义.nodes.filter((n) => n.type !== "start").map((n) => [n.id, `${业务名(n)}(${次级标签(n)})`]);
  const 现口 = 图逻辑.出口们(节点(e.source), 元).findIndex((o) => 图逻辑.同口(o, e));
  弹层("重新连接", `<label class="f">从(哪一步的哪个出口)</label><select id="rc-s">${起点们.map(([v, t]) =>
      `<option value="${esc(v)}" ${v === `${e.source}|${现口}` ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
    <label class="f">到</label><select id="rc-t">${终点们.map(([v, t]) => `<option value="${esc(v)}" ${v === e.target ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
    <div class="note">改起点时,这条路「什么时候走」也会变(比如从「完成后」变成「失败时」)。</div>
    <div class="acts"><button class="pri" id="rc-ok">改连接</button> <button id="rc-no">取消</button></div>`);
  $("#rc-no").onclick = 关弹层;
  $("#rc-ok").onclick = () => {
    const [sid, oi] = $("#rc-s").value.split("|");
    const 口 = 图逻辑.出口们(节点(sid), 元)[+oi];
    关弹层(); 重连(键, { source: sid, 口, target: $("#rc-t").value });
  };
}

/* ── 节点操作 ───────────────────────────────────────────────────── */
function 新节点(类型, 预设 = null) {
  const id = 图逻辑.新id(图态.定义, 类型);
  const 配 = Object.assign(JSON.parse(JSON.stringify(默认配置(类型))), (预设 && 预设.config) || {});
  // 同名再加时标题自动编号「AI 处理 2」「AI 处理 3」(照 Dify)—— 两步同名,连线和报错里分不清是哪一步
  const 基 = (预设 && 预设.name) || 步类型名[类型];
  const 名们 = new Set(图态.定义.nodes.map((n) => n.name));
  let 名 = 基, k = 2; while (名们.has(名)) 名 = `${基} ${k++}`;
  return { id, type: 类型, name: 名, config: 配 };
}
function 空位(x, y) {
  const 占 = (px, py) => 图态.定义.nodes.some((n) => { const p = 位(n.id); return Math.abs(p.x - px) < 画布.W && Math.abs(p.y - py) < 80; });
  let k = 0; while (占(x, y) && k++ < 40) y += 88;
  return { x: Math.round(x / 8) * 8, y: Math.round(y / 8) * 8 };
}
function 加到视口中间(类型, 预设 = null) {
  if (!(元(类型) || {})["可用"]) { 提示("这类步骤还没实现,不能加入"); return; }
  const r = $("#cv").getBoundingClientRect(), c = 屏到图(r.left + r.width / 2, r.top + r.height / 2);
  let id = null;
  改图(`添加「${步类型名[类型] || 类型}」`, () => { const n = 新节点(类型, 预设); 图态.定义.nodes.push(n); 图态.布局[n.id] = 空位(c.x - 画布.W / 2, c.y - 30); id = n.id; });
  选节点([id]);
  提示(`已添加「${业务名(节点(id))}」,还没接进流程 —— 从上一步的出口拖线连过来`, { 撤销: true });
}
function 从库拖入(ev, 类型, 预设 = null) {
  ev.preventDefault();
  const 影 = document.createElement("div");
  影.className = "wfghost"; 影.textContent = 步类型名[类型] || 类型;
  document.body.appendChild(影);
  const 跟 = (e) => { 影.style.left = e.clientX + 8 + "px"; 影.style.top = e.clientY + 8 + "px"; };
  跟(ev);
  const mv = (e) => 跟(e);
  const 收 = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); window.removeEventListener("keydown", esc键, true); 影.remove(); };
  const up = (e) => {
    收();
    const r = $("#cv").getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { 画_状态栏("拖到画布外,没有添加"); return; }
    const p = 屏到图(e.clientX, e.clientY);
    let id = null;
    改图(`添加「${步类型名[类型] || 类型}」`, () => { const n = 新节点(类型, 预设); 图态.定义.nodes.push(n); 图态.布局[n.id] = { x: Math.max(0, Math.round((p.x - 画布.W / 2) / 8) * 8), y: Math.max(0, Math.round((p.y - 16) / 8) * 8) }; id = n.id; });
    选节点([id]); 提示(`已添加「${业务名(节点(id))}」`, { 撤销: true });
  };
  const esc键 = (e) => { if (e.key === "Escape") { 收(); 画_状态栏("已取消添加"); } };
  window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up); window.addEventListener("keydown", esc键, true);
}

function 重命名节点(id) {
  const n = 节点(id);
  弹层("改步骤名称", `<input id="rn-v" value="${esc(业务名(n))}" maxlength="40">
    <div class="k">只改显示名;步骤编号 <code>${esc(id)}</code> 不变,引用它的地方不受影响。</div>
    <div class="acts"><button class="pri" id="rn-ok">确定</button> <button id="rn-no">取消</button></div>`);
  const i = $("#rn-v"); i.focus(); i.select();
  const 定 = () => { const v = i.value.trim(); 关弹层(); if (!v) { 提示("名称不能为空,没改"); return; } 改图("改名称", () => { n.name = v; }); };
  i.onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) 定(); if (e.key === "Escape") 关弹层(); };
  $("#rn-ok").onclick = 定; $("#rn-no").onclick = 关弹层;
}

function 节点菜单(id, 锚) {
  关菜单();
  const n = 节点(id), 改 = 能改图(), 用它 = 图逻辑.引用了(图态.定义, id);
  const m = document.createElement("div");
  m.className = "wfmenu"; m.id = "wf-menu"; m.setAttribute("role", "menu");
  const 项 = [
    改 && n.type !== "start" ? ["copy", "复制"] : null,
    ["refs", `定位引用(${用它.length})`],
    改 ? ["pos", "位置与对齐"] : null,
    改 && n.type !== "end" ? ["side", 出口边(id) === "下" ? "出口放回右边" : "出口改到下边"] : null,
    改 ? ["rename", "改名称"] : null,
    改 && n.type !== "start" ? ["reset", "重置配置"] : null,
    改 && n.type !== "start" ? ["del", "删除"] : null,
  ].filter(Boolean);
  m.innerHTML = 项.map(([k, t]) => `<button role="menuitem" data-mi="${k}" ${k === "del" ? 'class="danger"' : ""}>${esc(t)}</button>`).join("")
    + (n.type === "start" ? `<div class="k">「开始」不能复制、不能删</div>` : "");
  document.body.appendChild(m);
  const r = 锚.getBoundingClientRect();
  m.style.left = r.left + "px"; m.style.top = r.bottom + 4 + "px";
  const 第一个 = m.querySelector("button"); if (第一个) 第一个.focus();
  m.onkeydown = (e) => { if (e.key === "Escape") { 关菜单(); 锚.closest(".wfnode2")?.focus(); } };
  m.querySelectorAll("[data-mi]").forEach((b) => {
    b.onclick = () => {
      关菜单();
      const k = b.dataset.mi;
      if (k === "copy") { 复制选中([id]); 粘贴(); }
      if (k === "refs") 弹_定位引用(id);
      if (k === "pos") 弹_位置(id);
      if (k === "side") 改图(出口边(id) === "下" ? "出口放回右边" : "出口改到下边", () => {
        const p = 图态.布局[id] = { ...位(id) }; if (出口边(id) === "下") delete p.出口边; else p.出口边 = "下"; });
      if (k === "rename") 重命名节点(id);
      if (k === "reset") 弹_重置配置(id);
      if (k === "del") 弹_删除([id]);
      const nd = document.querySelector(`.wfnode2[data-id="${CSS.escape(id)}"]`); if (nd && k !== "del") nd.focus();
    };
  });
  setTimeout(() => document.addEventListener("pointerdown", 菜单外点, { once: true }), 0);
}
function 菜单外点(e) { const m = $("#wf-menu"); if (m && !m.contains(e.target)) 关菜单(); }
function 关菜单() { const m = $("#wf-menu"); if (m) m.remove(); }

function 弹_定位引用(id) {
  const 用它 = 图逻辑.引用了(图态.定义, id);
  弹层(`谁在用「${业务名(节点(id))}」的结果`, 用它.length
    ? 用它.map((r, i) => `<button class="tpl" data-ref="${i}">${esc(业务名(节点(r.节点id)))} · ${esc(r.路径)}(取「${esc(r.字段)}」)</button>`).join("")
    : `<div class="k">没有别的步骤在用它的结果。</div>`);
  document.querySelectorAll("[data-ref]").forEach((b) => { b.onclick = () => { const r = 用它[+b.dataset.ref]; 关弹层(); 选节点([r.节点id]); 定位到([r.节点id]); }; });
}
function 弹_位置(id) {
  const p = 位(id);
  弹层("位置与对齐", `<div class="fieldrow"><label>X</label><input id="ps-x" type="number" step="8" value="${p.x}"></div>
    <div class="fieldrow"><label>Y</label><input id="ps-y" type="number" step="8" value="${p.y}"></div>
    <div>${[["←", -8, 0], ["→", 8, 0], ["↑", 0, -8], ["↓", 0, 8]].map(([t, dx, dy]) => `<button data-mv="${dx},${dy}">${t} 8</button>`).join(" ")}</div>
    <div class="k">只改画法,不改执行顺序。</div>
    <div class="acts"><button class="pri" id="ps-ok">应用</button> <button id="ps-no">关闭</button></div>`);
  document.querySelectorAll("[data-mv]").forEach((b) => { b.onclick = () => { const [dx, dy] = b.dataset.mv.split(",").map(Number);
    $("#ps-x").value = +$("#ps-x").value + dx; $("#ps-y").value = +$("#ps-y").value + dy; }; });
  $("#ps-no").onclick = 关弹层;
  $("#ps-ok").onclick = () => {
    const x = Number($("#ps-x").value), y = Number($("#ps-y").value);
    if (!Number.isFinite(x) || !Number.isFinite(y)) { 提示("X / Y 要是数字,没改"); return; }
    关弹层(); 改图("位置与对齐", () => { 图态.布局[id] = { ...位(id), x: Math.max(0, x), y: Math.max(0, y) }; });
  };
}
function 弹_重置配置(id) {
  const n = 节点(id);
  弹层(`重置「${业务名(n)}」的配置`, `<p>会把这一步的<b>全部可编辑配置</b>恢复成新建时的样子:${esc(Object.keys(n.config || {}).map(中文名).join("、") || "(目前没有配置)")}。</p>
    <p class="k">保留这一步本身和它的连线;不动共享的模型、业务动作、处理要求。可以撤销。</p>
    <div class="acts"><button class="pri danger" id="rs-ok">重置配置</button> <button id="rs-no">取消</button></div>`);
  $("#rs-no").onclick = 关弹层;
  $("#rs-ok").onclick = () => { 关弹层(); 改图(`重置「${业务名(n)}」的配置`, () => { n.config = JSON.parse(JSON.stringify(默认配置(n.type))); }); 提示("已重置配置", { 撤销: true }); };
}

/* ── 复制粘贴 / 批量 ────────────────────────────────────────────── */
function 复制选中(ids) {
  const s = 画态();
  s.剪贴板 = 图逻辑.复制(图态.定义, 图态.布局, ids);
  if (s.剪贴板.跳过.length) 提示("已跳过开始节点");
  s.粘贴次 = 0;
  return s.剪贴板.节点们.length;
}
function 粘贴() {
  const s = 画态();
  if (!s.剪贴板 || !s.剪贴板.节点们.length) { 提示("剪贴板里没有步骤"); return; }
  s.粘贴次 = (s.粘贴次 || 0) + 1;
  let r = null;
  改图(`粘贴 ${s.剪贴板.节点们.length} 步`, () => { r = 图逻辑.粘贴(图态.定义, 图态.布局, s.剪贴板, { x: 40 * s.粘贴次, y: 40 * s.粘贴次 }); });
  选节点(r.新ids);
  if (r.外部引用.length)
    提示(`已粘贴 ${r.新ids.length} 步;其中 ${r.外部引用.length} 处数据来源仍引用原步骤,请核对(没有悄悄换来源)`, { 撤销: true });
  else 提示(`已粘贴 ${r.新ids.length} 步`, { 撤销: true });
}

function 整理布局() {
  弹层("整理布局", `<p>按执行顺序从左到右重新排列步骤,<b>只改位置,不改连线和配置</b>;手动加的折点会一起恢复成自动布线。</p>
    <p class="k">不满意可以撤销。</p><div class="acts"><button class="pri" id="lo-ok">整理</button> <button id="lo-no">取消</button></div>`);
  $("#lo-no").onclick = 关弹层;
  $("#lo-ok").onclick = () => { 关弹层(); 改图("整理布局", () => { 图态.布局 = 图逻辑.整理布局(图态.定义, 图态.布局); }); 适应画布(); 提示("已整理布局", { 撤销: true }); };
}

function 查找(词, 方向 = 1) {
  const s = 画态(), msg = $("#wf-findmsg");
  词 = String(词 || "").trim();
  if (!词) { msg.textContent = ""; return; }
  const 中 = 图态.定义.nodes.filter((n) => 业务名(n).includes(词) || n.id.includes(词));
  if (!中.length) { msg.textContent = `没找到「${词}」`; return; }   // 无结果不改变画布(W12)
  if (s.找.词 !== 词) { s.找 = { 词, i: -1 }; }
  s.找.i = (s.找.i + 方向 + 中.length) % 中.length;
  const n = 中[s.找.i];
  msg.textContent = `${s.找.i + 1} / ${中.length}`;
  选节点([n.id]); 定位到([n.id]);
}

/* ── 键盘(画布有焦点时)────────────────────────────────────────────── */
function 画布按键(e) {
  if (是输入(e.target)) return;                 // 输入框里的 Delete / Ctrl+Z 归文本(§9)
  if (e.isComposing) return;                    // 中文输入法组合中不抢键
  const s = 画态(), 改 = 能改图(), 主 = e.ctrlKey || e.metaKey, k = e.key;
  if (k === " " && !s.空格) { s.空格 = true; 画_状态栏("按住空格:拖动画布"); e.preventDefault(); return; }
  if (k === "Escape") {
    if (s.待连) return 取消连线();
    关菜单(); s.选 = new Set(); s.线 = null; 图态.选中 = null; 画_节点(); 画_线(); 画_面板(); 画_状态栏(); return;
  }
  if (主 && (k === "z" || k === "Z") && !e.shiftKey) { e.preventDefault(); return 撤销(); }
  if (主 && ((k === "z" || k === "Z") && e.shiftKey || k === "y")) { e.preventDefault(); return 重做(); }
  if (主 && k === "a") { e.preventDefault(); return 选节点(图态.定义.nodes.map((n) => n.id)); }
  if (主 && k === "c") { if (s.选.size) { e.preventDefault(); const c = 复制选中([...s.选]); 提示(`已复制 ${c} 步`); } return; }
  if (主 && k === "v") { if (改) { e.preventDefault(); 粘贴(); } return; }
  if ((k === "Delete" || k === "Backspace") && 改) {
    e.preventDefault();
    if (s.线) return 删线(s.线);
    if (s.选.size) return 弹_删除([...s.选]);
    return;
  }
  const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[k];
  if (d && 改) {
    const 焦 = e.target.closest && e.target.closest(".wfnode2");
    const ids = 焦 && !s.选.has(焦.dataset.id) ? [焦.dataset.id] : [...s.选];
    if (!ids.length) return;
    e.preventDefault();
    const 步 = e.shiftKey ? 24 : 8;
    改图(ids.length > 1 ? `移动 ${ids.length} 步` : `移动「${业务名(节点(ids[0]))}」`, () => {
      ids.forEach((id) => { const p = 位(id); 图态.布局[id] = { ...p, x: Math.max(0, p.x + d[0] * 步), y: Math.max(0, p.y + d[1] * 步) }; });
    }, { 合并键: `键移:${ids.join(",")}` });
    const nd = document.querySelector(`.wfnode2[data-id="${CSS.escape(ids[0])}"]`); if (nd) nd.focus();
    return;
  }
  if (k === "Enter") {
    const po = e.target.closest && e.target.closest("[data-out]");
    if (po && 改) { const n = 节点(po.dataset.out); s.待连 = { 源: n.id, 口: 图逻辑.出口们(n, 元)[+po.dataset.oi] }; 画_节点(); 画_状态栏(); return; }
    const nd = e.target.closest && e.target.closest(".wfnode2");
    if (nd && s.待连) return 完成连线(nd.dataset.id);
    if (nd) return 选节点([nd.dataset.id]);
  }
}

if (typeof globalThis !== "undefined") globalThis.画布动作 = { 连上, 删线, 重连, 粘贴, 复制选中, 查找, 缩放到, 适应画布, 选节点, 选线, 画态, 视口, 节点按下, 出口按下, 画布按键, 整理布局 };


/* ── 从其他工作流导入(第三批 · §5.3「跨项目导入需独立设计,不复用无校验的剪贴板粘贴」)──────────
 * 只在**同一个项目**里导(权限、连接是同一套);逐步核对资源在本项目可选列表里有没有;
 * 外部引用(指向没一起导入的步骤)**改成明确的「来源在另一条工作流」**,显示为待修、运行前必须改 ——
 * 不照旧指 node_id:两条流程都有 llm_1 时,那样会无声地挂到另一个步骤上。 */
async function 弹_导入() {
  let 列 = [];
  try { const d = await 请求(`${P()}/workflows`); 列 = (d.items || d.rows || []).filter((w) => (w.id || w["id"]) !== 图态.wid); }
  catch (e) { 提示("读不到工作流列表:" + e.message); return; }
  if (!列.length) { 提示("这个项目里没有别的工作流可以导入"); return; }
  弹层("从其他工作流导入步骤", `<label class="f">从哪条工作流</label>
    <select id="im-w">${列.map((w) => `<option value="${esc(w.id)}">${esc(w["名称"] || w.name || w.id)}</option>`).join("")}</select>
    <button id="im-read">读取它的步骤</button><div id="im-list" class="k">选一条,点「读取它的步骤」。</div>`);
  $("#im-read").onclick = async () => {
    const wid = $("#im-w").value, 名 = $("#im-w").selectedOptions ? $("#im-w").selectedOptions[0].textContent : wid;
    let d;
    try { d = await 请求(`${P()}/workflows/${encodeURIComponent(wid)}`); }
    catch (e) { $("#im-list").textContent = "读不到:" + e.message; return; }
    const 定 = d["草稿"]["定义"] || { nodes: [], edges: [] }, 布 = d["草稿"]["布局"] || {};
    const 资 = 图态.资源 || {}, 有 = (表, id) => !id || (表 || []).some((x) => x["版本id"] === id);
    const 核 = (n) => { const c = n.config || {}, 缺 = [];
      if (!有(资.模型, c.connection_version_id)) 缺.push("模型");
      if (!有(资.处理要求, c.prompt_version_id)) 缺.push("处理要求");
      if (!有(资.工具, c.tool_version_id)) 缺.push("业务动作");
      return 缺; };
    const 可 = 定.nodes.filter((n) => n.type !== "start");
    $("#im-list").innerHTML = 可.length ? 可.map((n) => { const 缺 = 核(n);
        return `<label class="tpl"><input type="checkbox" data-imn="${esc(n.id)}" checked> <b>${esc(n.name || 步类型名[n.type] || n.type)}</b>
          <span class="k">${esc(步类型名[n.type] || n.type)}</span>
          ${缺.length ? `<span class="ferr">它用的${缺.join("、")}在本项目可选列表里没有 —— 导入后原值保留并标出来,要换</span>` : ""}</label>`; }).join("")
        + `<div class="note">没一起导入的上一步,在这里取不到值 —— 那些数据来源会标成「来源在另一条工作流」,运行前要改。</div>
           <div class="acts"><button class="pri" id="im-ok">导入选中的步骤</button></div>`
      : "这条工作流除了开始没有别的步骤。";
    if (!$("#im-ok")) return;
    $("#im-ok").onclick = () => {
      const ids = [...document.querySelectorAll("[data-imn]")].filter((x) => x.checked).map((x) => x.dataset.imn);
      if (!ids.length) { 提示("没选步骤"); return; }
      关弹层();
      const 板 = 图逻辑.复制(定, 布, ids);
      const r0 = $("#cv").getBoundingClientRect(), c = 屏到图(r0.left + r0.width / 2, r0.top + r0.height / 2);
      const xs = Object.values(板.位).map((p) => p.x), ys = Object.values(板.位).map((p) => p.y);
      const 偏 = { x: Math.round(c.x - Math.min(...xs)), y: Math.round(c.y - Math.min(...ys)) };
      let r = null;
      改图(`从「${名}」导入 ${板.节点们.length} 步`, () => {
        r = 图逻辑.粘贴(图态.定义, 图态.布局, 板, 偏, (v) => { v.原名 = `「${名}」里的 ${v.node_id}`; v.node_id = `外部:${wid}:${v.node_id}`; });
      });
      选节点(r.新ids);
      提示(`已从「${名}」导入 ${r.新ids.length} 步(未保存)` + (r.外部引用.length ? `;${r.外部引用.length} 处数据来源在另一条工作流,标成待修了` : ""), { 撤销: true });
    };
  };
}
