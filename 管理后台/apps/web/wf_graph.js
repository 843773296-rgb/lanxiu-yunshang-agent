/* Workflow 编辑器 · 图操作逻辑层(交互控件详细设计 V1.0 §12「所有入口统一走图编辑命令层」)
 *
 * 这一层**不碰页面**:连线合不合法、删一步会影响什么、撤销恢复、复制粘贴、整理布局、变量从哪条路来 ——
 * 鼠标拖线、右侧「下一步」下拉、快捷键、右键菜单都调这里。**同一件事只有一份判断**:
 * 鼠标删线和下拉改去向各写一套的话,总有一套判松,而判松的那套看起来完全正常。
 *
 * 规则对齐服务端校验器(services/api/app/runtime/validator.py),**不另立一套**:
 *   · 不许有环(循环用有界循环 / 列表迭代容器表达)· 每个出口只接一个去向 · 开始节点没有进线 · 结束节点没有出线
 *   · 连线不能跨作用域(容器子图只能从容器进出)
 * 前端这层只是**及时反馈**;服务端「检查配置」才是最终依据(§12)。
 *
 * 连线没有 id(DSL 没有 edge id)。编辑层用「起点|出口|分支|终点」当身份 —— 同一个出口只接一个去向,
 * 所以它唯一;它只活在编辑层,**不写进定义**,不往运行器发新字段(§12)。
 */
(function (根) {
  "use strict";
  const 逻 = {};
  const 深拷 = (x) => JSON.parse(JSON.stringify(x));

  // ── 身份 ─────────────────────────────────────────────────────────
  逻.边键 = (e) => `${e.source}|${e.port}|${e.branch_key == null ? "" : e.branch_key}|${e.target}`;
  逻.同口 = (e, o) => e.port === o.port && (e.branch_key || null) === (o.branch_key || null);
  逻.找边 = (定义, 键) => (定义.edges || []).find((e) => 逻.边键(e) === 键) || null;
  逻.节点 = (定义, id) => (定义.nodes || []).find((n) => n.id === id) || null;

  /* 这一步从哪几个口出去。元(type) 给节点库那一行({端口:[...]}) */
  逻.出口们 = function (n, 元) {
    if (!n || n.type === "end") return [];
    if (n.type === "condition") {
      return [...((n.config || {}).branches || []).map((b) => ({ port: "branch", branch_key: b.key, 名: 逻.分支名(b.key) })),
              { port: "branch", branch_key: "else", 名: "都不满足" }];
    }
    const 口 = [{ port: "success", branch_key: null, 名: "完成后" }];
    if (((元(n.type) || {})["端口"] || []).includes("error")) 口.push({ port: "error", branch_key: null, 名: "失败时" });
    return 口;
  };
  /* 分支名给人看(10-26 改版):approve / same 这类内部键换成业务话;认不出的照原样带引号,不猜 */
  const 分支中文 = { approve: "通过了", reject: "退回了", same: "数据没变", changed: "数据变了", yes: "是", no: "否" };
  逻.分支名 = function (k) { return k === "else" ? "都不满足" : 分支中文[k] ? `${分支中文[k]}` : `满足「${k}」`; };
  逻.口名 = function (e) {
    if (e.port === "branch") return 逻.分支名(e.branch_key);
    return e.port === "error" ? "失败时" : "完成后";
  };

  // ── 走图 ─────────────────────────────────────────────────────────
  function 后继表(定义, 忽略键) {
    const 表 = new Map();
    (定义.edges || []).forEach((e) => {
      if (忽略键 && 逻.边键(e) === 忽略键) return;
      if (!表.has(e.source)) 表.set(e.source, []);
      表.get(e.source).push(e.target);
    });
    return 表;
  }
  /* 从 a 走得到 b 吗 */
  function 走得到(表, a, b) {
    const 见 = new Set([a]), 栈 = [a];
    while (栈.length) {
      const x = 栈.pop();
      if (x === b) return true;
      (表.get(x) || []).forEach((y) => { if (!见.has(y)) { 见.add(y); 栈.push(y); } });
    }
    return false;
  }

  /* 连一条 源 --口--> 目标,合不合法。→ {可以, 为什么, 替换(被换掉的那条线,或 null)}
   * 忽略键:重连时把原来那条线当成不存在再判(不然「换目标」会被它自己挡住)。 */
  逻.连接校验 = function (定义, 源id, 口, 目标id, 元, 忽略键 = null) {
    const a = 逻.节点(定义, 源id), b = 逻.节点(定义, 目标id);
    const 不 = (为什么) => ({ 可以: false, 为什么, 替换: null });
    if (!a || !b) return 不("这一步已经不在图里了");
    if (源id === 目标id) return 不("不能连到自己");
    if (b.type === "start") return 不("「开始」没有进线 —— 流程只能从它出发");
    if (a.type === "end") return 不("「结束」没有出线");
    const 口们 = 逻.出口们(a, 元);
    if (!口们.some((o) => 逻.同口(o, 口))) return 不(`「${a.name || a.type}」没有「${逻.口名(口)}」这个出口`);
    if ((a.container || null) !== (b.container || null) && b.container !== a.id && a.container !== b.id)
      return 不("跨了作用域 —— 循环 / 迭代里的步骤只能从容器节点进出");
    const 已有 = (定义.edges || []).filter((e) => 逻.边键(e) !== 忽略键 && e.source === 源id && 逻.同口(e, 口));
    if (已有.some((e) => e.target === 目标id)) return 不("这两步已经这样连着了");
    // 环:新线 a→b 之后,从 b 走得回 a 就成环。把这个出口原来那条线去掉再判(它会被替换掉)
    const 表 = 后继表({ edges: (定义.edges || []).filter((e) => !已有.includes(e)) }, 忽略键);
    if (走得到(表, 目标id, 源id))
      return 不("这条连接会形成当前不支持的循环 —— 循环要用「有界循环」或「列表迭代」步骤表达");
    return { 可以: true, 为什么: "", 替换: 已有[0] || null };
  };

  /* 真的连上。单目标出口:**原子替换**(先删原来那条,再加新的;不留两条线假装同时执行 §6.2) */
  逻.连 = function (定义, 源id, 口, 目标id) {
    定义.edges = (定义.edges || []).filter((e) => !(e.source === 源id && 逻.同口(e, 口)));
    const e = { source: 源id, target: 目标id, port: 口.port };
    if (口.branch_key != null) e.branch_key = 口.branch_key;
    定义.edges.push(e);
    return e;
  };

  逻.删边 = function (定义, 键) {
    const 前 = (定义.edges || []).length;
    定义.edges = (定义.edges || []).filter((e) => 逻.边键(e) !== 键);
    return 定义.edges.length < 前;
  };

  /* 拖端点重连:改目标 / 改起点(连出口)。不合法 → 原线保持,返回为什么(§6.4:重连失败不等于删线) */
  逻.重连 = function (定义, 键, 改, 元) {
    const e = 逻.找边(定义, 键);
    if (!e) return { 可以: false, 为什么: "这条线已经不在了" };
    const 源 = 改.source || e.source, 口 = 改.口 || { port: e.port, branch_key: e.branch_key ?? null };
    const 目 = 改.target || e.target;
    if (源 === e.source && 逻.同口(口, e) && 目 === e.target) return { 可以: false, 为什么: "未更改连接", 没变: true };
    const v = 逻.连接校验(定义, 源, 口, 目, 元, 键);
    if (!v.可以) return v;
    逻.删边(定义, 键);
    const 新 = 逻.连(定义, 源, 口, 目);
    return { 可以: true, 为什么: "", 新键: 逻.边键(新), 换了起点: 源 !== e.source || !逻.同口(口, e), 替换: v.替换 };
  };

  // ── 引用 ─────────────────────────────────────────────────────────
  /* 一个配置里所有结构化引用 {source:"node", node_id, pointer} 的路径 */
  function 扫引用(v, 路, 出) {
    if (!v || typeof v !== "object") return;
    if (v.source === "node" && v.node_id) 出.push({ 路径: 路, 引用: v });
    for (const [k, x] of Object.entries(v)) 扫引用(x, 路 ? `${路}.${k}` : k, 出);
  }
  逻.引用们 = function (n) { const 出 = []; 扫引用(n.config || {}, "", 出); return 出; };

  /* 谁在用 id 这一步的结果 → [{节点id, 路径, 字段}] */
  逻.引用了 = function (定义, id) {
    const 出 = [];
    (定义.nodes || []).forEach((n) => {
      if (n.id === id) return;
      逻.引用们(n).forEach((r) => {
        if (r.引用.node_id === id) 出.push({ 节点id: n.id, 路径: r.路径, 字段: String(r.引用.pointer || "").replace(/^\//, "") });
      });
    });
    return 出;
  };

  /* 失效引用:指向已经不在图里的步骤。**保留原名称,不改成空串或别的步骤**(§7.1) */
  逻.失效引用 = function (定义) {
    const 在 = new Set((定义.nodes || []).map((n) => n.id)), 出 = [];
    (定义.nodes || []).forEach((n) => 逻.引用们(n).forEach((r) => {
      if (!在.has(r.引用.node_id)) 出.push({ 节点id: n.id, 路径: r.路径, 原来源: r.引用.node_id,
        原名: r.引用.原名 || r.引用.node_id, 字段: String(r.引用.pointer || "").replace(/^\//, "") });
    }));
    return 出;
  };

  // ── 删除 ─────────────────────────────────────────────────────────
  /* 删之前算影响 —— **来自当前图,不显示固定模板数字**(§7.1)。
   * 是敏感(n) 由页面给:人工核对、写入类业务动作 —— 这些不提供快捷桥接。 */
  逻.删除影响 = function (定义, ids, 是敏感 = () => false) {
    const 要删 = [], 跳过 = [];
    ids.forEach((id) => {
      const n = 逻.节点(定义, id);
      if (!n) return;
      if (n.type === "start") 跳过.push({ id, 为什么: "「开始」受保护,不能删 —— 流程只能从它出发" });
      else 要删.push(n);
    });
    const 集 = new Set(要删.map((n) => n.id));
    const 删边 = (定义.edges || []).filter((e) => 集.has(e.source) || 集.has(e.target));
    const 引用 = [];
    要删.forEach((n) => 逻.引用了(定义, n.id).forEach((r) => { if (!集.has(r.节点id)) 引用.push({ ...r, 引用的: n.id }); }));
    const 敏感 = 要删.filter((n) => 是敏感(n));
    // 桥接只在「删一步、一进一出、它不敏感、接上后合法」时提供,且要单独选(§7.1:默认不桥接)
    let 可桥接 = null;
    if (要删.length === 1 && !敏感.length) {
      const id = 要删[0].id;
      const 进 = (定义.edges || []).filter((e) => e.target === id), 出 = (定义.edges || []).filter((e) => e.source === id);
      if (进.length === 1 && 出.length === 1 && 出[0].port === "success") 可桥接 = { 从: 进[0], 到: 出[0].target };
    }
    const 删结束 = 要删.some((n) => n.type === "end");
    return { 要删: 要删.map((n) => n.id), 跳过, 删边, 引用, 敏感: 敏感.map((n) => n.id), 可桥接, 删结束 };
  };

  /* 真删:节点 + 关联线 + 布局。**引用不动**(保留失效引用,检查配置会点名;撤销能恢复) */
  逻.删节点 = function (定义, 布局, ids, { 桥接 = false, 元 = () => ({}), 是敏感 = () => false } = {}) {
    const 影 = 逻.删除影响(定义, ids, 是敏感);       // 桥接与否照影响里的 可桥接 —— 敏感节点那里就是 null
    const 集 = new Set(影.要删);
    const 桥 = 桥接 && 影.可桥接;
    定义.edges = (定义.edges || []).filter((e) => !集.has(e.source) && !集.has(e.target));
    定义.nodes = (定义.nodes || []).filter((n) => !集.has(n.id));
    集.forEach((id) => { delete 布局[id]; });
    if (布局.$线) Object.keys(布局.$线).forEach((k) => { const [s, , , t] = k.split("|"); if (集.has(s) || 集.has(t)) delete 布局.$线[k]; });
    if (桥) {
      const 口 = { port: 桥.从.port, branch_key: 桥.从.branch_key ?? null };
      const v = 逻.连接校验(定义, 桥.从.source, 口, 桥.到, 元);
      if (v.可以) 逻.连(定义, 桥.从.source, 口, 桥.到);
    }
    return 影;
  };

  // ── 插入 ─────────────────────────────────────────────────────────
  /* 在 A→B 这条线上插一步 X:预览 A→X→B。X 没有「完成后」出口或不能有进线 → 拒,不硬插(§5.2) */
  逻.能插入吗 = function (类型, 元) {
    if (类型 === "start") return { 可以: false, 为什么: "「开始」不能插在中间" };
    if (类型 === "end") return { 可以: false, 为什么: "「结束」没有出线,插进去后面那一步就断了" };
    if (类型 === "condition") return { 可以: false, 为什么: "条件判断没有「完成后」出口 —— 插进去不知道原来的下一步该接在哪一路;改用普通新建再自己连" };
    if (!((元(类型) || {})["端口"] || []).includes("success")) return { 可以: false, 为什么: "这类步骤没有「完成后」出口,接不上原来的下一步" };
    return { 可以: true, 为什么: "" };
  };
  逻.插入到线 = function (定义, 键, 新节点, 元) {
    const e = 逻.找边(定义, 键);
    if (!e) return { 可以: false, 为什么: "这条线已经不在了" };
    const 能 = 逻.能插入吗(新节点.type, 元);
    if (!能.可以) return 能;
    定义.nodes.push(新节点);
    逻.删边(定义, 键);
    逻.连(定义, e.source, { port: e.port, branch_key: e.branch_key ?? null }, 新节点.id);
    逻.连(定义, 新节点.id, { port: "success", branch_key: null }, e.target);
    return { 可以: true, id: 新节点.id };
  };

  逻.新id = function (定义, 类型, 已占 = new Set()) {
    let i = 1, id;
    do { id = `${类型}_${i++}`; } while ((定义.nodes || []).some((n) => n.id === id) || 已占.has(id));
    return id;
  };

  // ── 复制粘贴(§5.3)────────────────────────────────────────────────
  /* 复制:配置 + 集合内部的线;**不复制**外部连线、运行结果、审核回执、密钥。开始节点跳过 */
  逻.复制 = function (定义, 布局, ids) {
    const 跳过 = [], 节点们 = [];
    ids.forEach((id) => {
      const n = 逻.节点(定义, id);
      if (!n) return;
      if (n.type === "start") { 跳过.push("已跳过开始节点"); return; }
      节点们.push(深拷(n));
    });
    const 集 = new Set(节点们.map((n) => n.id));
    const 线 = (定义.edges || []).filter((e) => 集.has(e.source) && 集.has(e.target)).map(深拷);
    const 位 = {};
    节点们.forEach((n) => { 位[n.id] = { ...(布局[n.id] || { x: 0, y: 0 }) }; });
    return { 节点们, 线, 位, 跳过 };
  };
  /* 粘贴:新 id 唯一;集合内部的引用重映射到新 id;**外部引用照旧指原步骤,并列出来让人核对**(不悄悄换来源) */
  /* 外部处理:跨流程导入时给(第三批)—— 原步骤不在这张图里,**同名步骤可能恰好存在**(两条流程都有 llm_1),
   * 照旧指 node_id 就会无声地挂到另一个步骤上。由调用方把外部引用改成一个明确不存在的来源。 */
  逻.粘贴 = function (定义, 布局, 板, 偏移 = { x: 40, y: 40 }, 外部处理 = null) {
    if (!板 || !板.节点们 || !板.节点们.length) return { 新ids: [], 外部引用: [] };
    const 映 = {}, 占 = new Set();
    板.节点们.forEach((n) => { 映[n.id] = 逻.新id(定义, n.type, 占); 占.add(映[n.id]); });
    const 外部引用 = [];
    const 改引用 = (v, 新id, 路) => {
      if (!v || typeof v !== "object") return;
      if (v.source === "node" && v.node_id) {
        if (映[v.node_id]) v.node_id = 映[v.node_id];
        else { 外部引用.push({ 节点id: 新id, 路径: 路, 仍引用: v.node_id }); if (外部处理) 外部处理(v); }
      }
      for (const [k, x] of Object.entries(v)) 改引用(x, 新id, 路 ? `${路}.${k}` : k);
    };
    板.节点们.forEach((n0) => {
      const n = 深拷(n0);
      n.id = 映[n0.id];
      if (n.name) n.name = `${n.name}(副本)`;
      改引用(n.config, n.id, "");
      定义.nodes.push(n);
      const p = 板.位[n0.id] || { x: 0, y: 0 };
      布局[n.id] = { x: p.x + 偏移.x, y: p.y + 偏移.y };
    });
    定义.edges = 定义.edges || [];
    板.线.forEach((e) => 定义.edges.push({ ...深拷(e), source: 映[e.source], target: 映[e.target] }));
    return { 新ids: 板.节点们.map((n) => 映[n.id]), 外部引用 };
  };

  // ── 条件分支(§7.2)──────────────────────────────────────────────
  /* 改分支名:**连线的 branch_key 跟着改**,不留旧键(否则线和分支对不上,运行时那一路没人接) */
  逻.分支改名 = function (定义, 节点id, 旧, 新) {
    const n = 逻.节点(定义, 节点id);
    新 = String(新 || "").trim();
    if (!n || n.type !== "condition") return { 可以: false, 为什么: "这一步不是条件判断" };
    if (!新) return { 可以: false, 为什么: "分支名不能为空" };
    if (新 === "else") return { 可以: false, 为什么: "「else」留给「都不满足」那一路" };
    if (新 === 旧) return { 可以: false, 为什么: "未更改", 没变: true };
    const bs = (n.config || {}).branches || [];
    if (bs.some((b) => b.key === 新)) return { 可以: false, 为什么: `已经有一路叫「${新}」了` };
    const b = bs.find((x) => x.key === 旧);
    if (!b) return { 可以: false, 为什么: `没有「${旧}」这一路` };
    b.key = 新;
    (定义.edges || []).forEach((e) => { if (e.source === 节点id && e.port === "branch" && e.branch_key === 旧) e.branch_key = 新; });
    return { 可以: true };
  };
  /* 调优先级:从上往下,第一个满足的生效 —— **调顺序就是改执行逻辑** */
  逻.分支移动 = function (定义, 节点id, i, 步) {
    const bs = ((逻.节点(定义, 节点id) || {}).config || {}).branches || [];
    const j = i + 步;
    if (i < 0 || j < 0 || i >= bs.length || j >= bs.length) return false;
    [bs[i], bs[j]] = [bs[j], bs[i]];
    return true;
  };
  /* 删一路:那一路的线一起删;目标节点和其余分支保留 */
  逻.删分支 = function (定义, 节点id, i) {
    const n = 逻.节点(定义, 节点id), bs = ((n || {}).config || {}).branches || [];
    if (!bs[i]) return { 删边: [] };
    const 键 = bs[i].key;
    const 删边 = (定义.edges || []).filter((e) => e.source === 节点id && e.port === "branch" && e.branch_key === 键);
    定义.edges = (定义.edges || []).filter((e) => !删边.includes(e));
    bs.splice(i, 1);
    return { 删边, 键 };
  };

  // ── 变量从哪来(§8.2):祖先 ≠ 必经 ──────────────────────────────────
  /* 每个前驱步骤标「必经 / 仅部分路径有值」。必经 = 从开始到这一步的**每一条路**都经过它(支配) */
  逻.前驱与必经 = function (定义, id) {
    const 起 = (定义.nodes || []).find((n) => n.type === "start");
    const 前 = new Set(), 栈 = [id];
    while (栈.length) {
      const x = 栈.pop();
      (定义.edges || []).filter((e) => e.target === x).forEach((e) => { if (!前.has(e.source)) { 前.add(e.source); 栈.push(e.source); } });
    }
    const 必经 = new Set();
    if (起) {
      const 表 = 后继表(定义);
      前.forEach((d) => {
        if (d === 起.id) { 必经.add(d); return; }
        // 去掉 d 之后,从开始还走得到 id → d 不是必经
        const 剪 = new Map([...表].filter(([k]) => k !== d).map(([k, v]) => [k, v.filter((y) => y !== d)]));
        if (!走得到(剪, 起.id, id)) 必经.add(d);
      });
    }
    return { 前驱: 前, 必经 };
  };

  // ── 整理布局(§W11):按从开始走的层数排列,不改逻辑 ──────────────────
  逻.整理布局 = function (定义, 旧布局 = {}, 宽 = 176, 列距 = 240, 行距 = 100) {
    const 起 = (定义.nodes || []).find((n) => n.type === "start");
    const 层 = {}, 表 = 后继表(定义);
    if (起) {
      // 最长路径分层(无环图上成立;有环时用访问次数兜底,不死循环)
      const 队 = [起.id]; 层[起.id] = 0; let 步 = 0;
      while (队.length && 步++ < 10000) {
        const x = 队.shift();
        (表.get(x) || []).forEach((y) => { if ((层[y] ?? -1) < 层[x] + 1 && 层[x] + 1 < (定义.nodes || []).length) { 层[y] = 层[x] + 1; 队.push(y); } });
      }
    }
    const 列 = {};
    let 散列 = Math.max(0, ...Object.values(层)) + 1;
    (定义.nodes || []).forEach((n) => { if (层[n.id] == null) 层[n.id] = 散列; });
    const 新 = { ...旧布局 };
    (定义.nodes || []).forEach((n) => {
      const c = 层[n.id];
      列[c] = (列[c] || 0) + 1;
      新[n.id] = { ...(旧布局[n.id] || {}), x: 40 + c * 列距, y: 40 + (列[c] - 1) * 行距 };
    });
    if (新.$线) 新.$线 = {};        // 折点按新位置不再成立 —— 一起恢复自动布线
    return 新;
  };

  // ── 撤销 / 重做(§10.1)───────────────────────────────────────────
  /* 一条命令 = 一次完整编辑动作的前后快照({定义, 布局})。连续文本输入按合并键并成一段。
   * 上限 100 条 + 总字数上限,超了丢最旧的,**不影响草稿内容**。 */
  逻.历史 = function (上限 = 100, 字数上限 = 30_000_000) {
    const 撤 = [], 重 = [];
    const 字数 = () => 撤.reduce((s, x) => s + x.前.length + x.后.length, 0);
    return {
      记(名, 前, 后, 合并键 = null, 时 = Date.now()) {
        if (前 === 后) return false;
        const 顶 = 撤[撤.length - 1];
        if (合并键 && 顶 && 顶.合并键 === 合并键 && 时 - 顶.时 < 1500) { 顶.后 = 后; 顶.时 = 时; 重.length = 0; return true; }
        撤.push({ 名, 前, 后, 合并键, 时 });
        重.length = 0;
        while (撤.length > 上限 || (撤.length > 1 && 字数() > 字数上限)) 撤.shift();
        return true;
      },
      撤销() { const x = 撤.pop(); if (!x) return null; 重.push(x); return { 快照: x.前, 名: x.名 }; },
      重做() { const x = 重.pop(); if (!x) return null; 撤.push(x); return { 快照: x.后, 名: x.名 }; },
      能撤: () => 撤.length > 0, 能重: () => 重.length > 0,
      下一撤: () => (撤[撤.length - 1] || {}).名 || null, 下一重: () => (重[重.length - 1] || {}).名 || null,
      条数: () => 撤.length,
    };
  };
  逻.快照 = (定义, 布局) => JSON.stringify({ 定义, 布局 });

  // ── 冲突时看差异(§10.3)────────────────────────────────────────────
  逻.差异 = function (本地, 远端) {
    const 按 = (d) => new Map((d.nodes || []).map((n) => [n.id, JSON.stringify(n)]));
    const a = 按(本地), b = 按(远端);
    const 线 = (d) => new Set((d.edges || []).map(逻.边键));
    const la = 线(本地), lb = 线(远端);
    return {
      只在本地的步骤: [...a.keys()].filter((k) => !b.has(k)),
      只在对方的步骤: [...b.keys()].filter((k) => !a.has(k)),
      两边都改了的步骤: [...a.keys()].filter((k) => b.has(k) && a.get(k) !== b.get(k)),
      只在本地的线: [...la].filter((k) => !lb.has(k)),
      只在对方的线: [...lb].filter((k) => !la.has(k)),
    };
  };

  /* 定义有没有变(布局变不算):决定旧的检查报告还算不算数(§10.4) */
  逻.逻辑变了 = (前快照, 后快照) => {
    try { return JSON.stringify(JSON.parse(前快照).定义) !== JSON.stringify(JSON.parse(后快照).定义); }
    catch (e) { return true; }
  };

  根.图逻辑 = 逻;
  if (typeof module !== "undefined" && module.exports) module.exports = 逻;
})(typeof globalThis !== "undefined" ? globalThis : this);
