/* 编排页 · 图操作逻辑层(apps/web/wf_graph.js)—— 交互控件详细设计 V1.0 §5–§10 的规则,不起服务、不碰页面。
 *
 * 真调 wf_graph.js(不在这儿照样子重写一份)。夹具是自造的小图,形状照设计稿里的例子:
 *   开始 → 查订单 → 判断风险 ─需关注→ 人工核对 → 写入
 *                              └都不满足→ 结束
 * 和服务端校验器对齐的那几条(环 / 开始没有进线 / 一个出口一个去向),失败时这里先红,不等保存才发现。
 */
"use strict";
const path = require("path");
const 逻 = require(path.join(__dirname, "..", "..", "apps", "web", "wf_graph.js"));

let 过 = 0; const 挂 = [];
function ck(名, 真, 补) {
  console.log(`  ${真 ? "✅" : "❌"} ${名}${真 || 补 === undefined ? "" : "  " + JSON.stringify(补).slice(0, 200)}`);
  if (真) 过++; else 挂.push(名);
}
const 元表 = { start: { 端口: ["success"] }, end: { 端口: [] }, llm: { 端口: ["success", "error"] }, tool: { 端口: ["success", "error"] },
  human: { 端口: ["success", "error"] }, condition: { 端口: ["branch"] }, transform: { 端口: ["success", "error"] }, merge: { 端口: ["success"] } };
const 元 = (t) => 元表[t] || {};
const 成 = { port: "success", branch_key: null };
function 图() {
  return {
    定义: {
      nodes: [
        { id: "start", type: "start", config: { input_schema: { properties: { 单号: { type: "string" } } } } },
        { id: "tool_1", type: "tool", name: "查订单", config: { bindings: { 单号: { source: "input", pointer: "/单号" } } } },
        { id: "condition_1", type: "condition", name: "判断风险", config: { branches: [{ key: "需关注", when: { op: "equals", left: { source: "node", node_id: "tool_1", pointer: "/风险" } } }], else_policy: "fail" } },
        { id: "human_1", type: "human", name: "人工核对", config: { payload_binding: { 摘要: { source: "node", node_id: "tool_1", pointer: "/交期" } } } },
        { id: "tool_2", type: "tool", name: "写入", config: { bindings: { 定稿: { source: "node", node_id: "human_1", pointer: "/定稿" } } } },
        { id: "end", type: "end", config: { bindings: { 结果: { source: "node", node_id: "tool_2", pointer: "/ok" } } } },
      ],
      edges: [
        { source: "start", target: "tool_1", port: "success" },
        { source: "tool_1", target: "condition_1", port: "success" },
        { source: "condition_1", target: "human_1", port: "branch", branch_key: "需关注" },
        { source: "condition_1", target: "end", port: "branch", branch_key: "else" },
        { source: "human_1", target: "tool_2", port: "success" },
        { source: "tool_2", target: "end", port: "success" },
      ],
    },
    布局: { start: { x: 0, y: 0 }, tool_1: { x: 200, y: 0 }, condition_1: { x: 400, y: 0 }, human_1: { x: 600, y: 0 }, tool_2: { x: 800, y: 0 }, end: { x: 1000, y: 0 } },
  };
}
const 键 = (s, p, b, t) => `${s}|${p}|${b ?? ""}|${t}`;

console.log("编排页 · 图操作逻辑层(连 / 删 / 重连 / 插入 / 复制 / 分支 / 变量可达 / 撤销 / 冲突)");

console.log("\n▸ 建立连接(§6.2)—— 和服务端校验器同一套边界");
{
  const { 定义 } = 图();
  ck("不能接到「开始」", !逻.连接校验(定义, "tool_1", 成, "start", 元).可以);
  ck("不能接自己", !逻.连接校验(定义, "tool_1", 成, "tool_1", 元).可以);
  ck("「结束」没有出线", !逻.连接校验(定义, "end", 成, "tool_1", 元).可以);
  const 环 = 逻.连接校验(定义, "tool_2", { port: "error", branch_key: null }, "tool_1", 元);
  ck("会形成环 → 拒,并说清用循环容器", !环.可以 && 环.为什么.includes("循环"), 环);
  const 已 = 逻.连接校验(定义, "tool_1", 成, "condition_1", 元);
  ck("一模一样的线已经在 → 拒(不重复)", !已.可以, 已);
  const 换 = 逻.连接校验(定义, "tool_1", 成, "end", 元);
  ck("单目标出口再连 → 允许,但标出要替换掉的那条(查订单 → 判断风险)", 换.可以 && 换.替换 && 换.替换.target === "condition_1", 换);
  逻.连(定义, "tool_1", 成, "end");
  ck("T06 替换是原子的:A→B 换成 A→C,不留两条线假装同时执行",
     定义.edges.filter((e) => e.source === "tool_1" && e.port === "success").map((e) => e.target).join() === "end");
  const 跨 = JSON.parse(JSON.stringify(图().定义));
  跨.nodes.push({ id: "llm_9", type: "llm", container: "loop_1" });
  ck("跨作用域(从外面直接连进循环子图)→ 拒", !逻.连接校验(跨, "tool_1", 成, "llm_9", 元).可以);
}

console.log("\n▸ 删线 / 重连(§6.3 §6.4)");
{
  const { 定义 } = 图();
  const k = 键("tool_2", "success", null, "end");
  ck("T03 删线只删这一条,两端步骤和配置都在", 逻.删边(定义, k) && 定义.nodes.length === 6 && !逻.找边(定义, k));
  const g = 图().定义, k2 = 键("human_1", "success", null, "tool_2");
  const 坏 = 逻.重连(g, k2, { target: "tool_1" }, 元);
  ck("T05 重连到非法目标(会成环)→ 不改,原线还在", !坏.可以 && 逻.找边(g, k2), 坏);
  const 空 = 逻.重连(g, k2, {}, 元);
  ck("拖回原处 → 「未更改连接」,不算删线", !空.可以 && 空.没变 && 逻.找边(g, k2));
  const 好 = 逻.重连(g, k2, { target: "end" }, 元);
  ck("T05 重连到合法目标 → 原子替换(旧线没了、新线在)", 好.可以 && !逻.找边(g, k2) && 逻.找边(g, 键("human_1", "success", null, "end")), 好);
  const 换头 = 逻.重连(g, 键("human_1", "success", null, "end"), { 口: { port: "error", branch_key: null } }, 元);
  ck("换起点出口(完成后 → 失败时)→ 允许,并标「换了起点」(分支语义变了要提示)", 换头.可以 && 换头.换了起点, 换头);
}

console.log("\n▸ 删除节点(§7.1)—— 默认不桥接、敏感节点不给快捷桥接、引用不悄悄改");
{
  const 敏 = (n) => n.type === "human" || n.type === "tool";
  const { 定义, 布局 } = 图();
  const 影 = 逻.删除影响(定义, ["human_1"], 敏);
  ck("影响来自当前图:删 1 步、2 条线、1 处引用(写入在用它的定稿)",
     影.要删.length === 1 && 影.删边.length === 2 && 影.引用.length === 1 && 影.引用[0].节点id === "tool_2", 影);
  ck("T07 人工核对是敏感步骤 → 不提供「接通前后步骤」(不能删掉核对后直接写入)", 影.可桥接 === null && 影.敏感.includes("human_1"));
  逻.删节点(定义, 布局, ["human_1"], { 桥接: true, 元, 是敏感: 敏 });
  ck("T07 就算调用方要桥接,敏感步骤也不桥:判断风险 → 写入 没有被接上",
     !定义.edges.some((e) => e.source === "condition_1" && e.target === "tool_2"));
  ck("T08 下游的引用原样保留(不改成空串、不换成别的步骤)", 定义.nodes.find((n) => n.id === "tool_2").config.bindings.定稿.node_id === "human_1");
  const 失 = 逻.失效引用(定义);
  ck("T08 失效引用点得出来:写入 · 定稿 → 原来源 human_1 已删", 失.length === 1 && 失[0].节点id === "tool_2" && 失[0].原来源 === "human_1", 失);
  ck("布局里那一步的坐标一起删", !布局.human_1);
  const g2 = 图();
  const 普 = 逻.删除影响(g2.定义, ["tool_1"], () => false);
  ck("一进一出、不敏感 → 才出现「删除并接通」(要单独选,不是默认)", 普.可桥接 && 普.可桥接.到 === "condition_1");
  逻.删节点(g2.定义, g2.布局, ["tool_1"], { 元 });
  ck("默认(不选桥接)→ 开始 和 判断风险 之间没有线", !g2.定义.edges.some((e) => e.source === "start"));
  const g3 = 图();
  const 起 = 逻.删除影响(g3.定义, ["start", "tool_1"]);
  ck("多选删除含「开始」→ 开始写明保留原因,其余照删(不是悄悄全部失败)", 起.要删.join() === "tool_1" && 起.跳过[0].id === "start" && 起.跳过[0].为什么.includes("受保护"));
}

console.log("\n▸ 在线上插入一步(§5.2)");
{
  const { 定义 } = 图();
  const k = 键("tool_1", "success", null, "condition_1");
  const r = 逻.插入到线(定义, k, { id: "llm_1", type: "llm", config: {} }, 元);
  ck("A→B 插 X → A→X→B,原线没了", r.可以 && 逻.找边(定义, 键("tool_1", "success", null, "llm_1")) && 逻.找边(定义, 键("llm_1", "success", null, "condition_1")) && !逻.找边(定义, k));
  const { 定义: d2 } = 图();
  const 不 = 逻.插入到线(d2, k, { id: "condition_9", type: "condition", config: {} }, 元);
  ck("条件判断没有「完成后」出口 → 拒绝自动插入并说明(允许改为普通新建)", !不.可以 && 不.为什么.includes("完成后") && d2.nodes.length === 6, 不);
}

console.log("\n▸ 复制粘贴(§5.3 T16)");
{
  const { 定义, 布局 } = 图();
  const 板 = 逻.复制(定义, 布局, ["start", "human_1", "tool_2"]);
  ck("复制含「开始」→ 跳过它并说「已跳过开始节点」", 板.节点们.length === 2 && 板.跳过.includes("已跳过开始节点"));
  ck("只带集合内部的线(核对 → 写入),不带外部的", 板.线.length === 1 && 板.线[0].source === "human_1");
  const r = 逻.粘贴(定义, 布局, 板);
  const ids = r.新ids, 新写 = 定义.nodes.find((n) => n.id === ids[1]), 新核 = 定义.nodes.find((n) => n.id === ids[0]);
  ck("新 id 唯一", new Set(定义.nodes.map((n) => n.id)).size === 定义.nodes.length && !ids.includes("human_1"));
  ck("内部引用重映射:新写入取的是**新**核对的定稿", 新写.config.bindings.定稿.node_id === ids[0], 新写.config.bindings);
  ck("外部引用不悄悄换:新核对仍取原「查订单」,并列出来待核对",
     新核.config.payload_binding.摘要.node_id === "tool_1" && r.外部引用.some((x) => x.仍引用 === "tool_1"), r.外部引用);
  ck("内部的线也复制了(新核对 → 新写入)", 定义.edges.some((e) => e.source === ids[0] && e.target === ids[1]));
}

console.log("\n▸ 条件分支(§7.2 T09 T10)");
{
  const { 定义 } = 图();
  const r = 逻.分支改名(定义, "condition_1", "需关注", "高风险");
  ck("T09 改分支名 → 连线的 branch_key 跟着改,不留旧键", r.可以 && 逻.找边(定义, 键("condition_1", "branch", "高风险", "human_1")) && !定义.edges.some((e) => e.branch_key === "需关注"));
  ck("改成「else」→ 拒(留给都不满足)", !逻.分支改名(定义, "condition_1", "高风险", "else").可以);
  定义.nodes[2].config.branches.push({ key: "低风险", when: {} });
  ck("改成已有的名字 → 拒", !逻.分支改名(定义, "condition_1", "高风险", "低风险").可以);
  ck("T10 调优先级:下移 / 上移真的改了顺序", 逻.分支移动(定义, "condition_1", 0, 1) && 定义.nodes[2].config.branches.map((b) => b.key).join() === "低风险,高风险");
  ck("越界的移动不做", !逻.分支移动(定义, "condition_1", 0, -1));
  const d = 逻.删分支(定义, "condition_1", 1);
  ck("T09 删一路 → 那一路的线一起删,目标步骤保留", d.键 === "高风险" && d.删边.length === 1 && 定义.nodes.some((n) => n.id === "human_1"));
}

console.log("\n▸ 变量从哪来:祖先 ≠ 必经(§8.2 T19)");
{
  const { 定义 } = 图();
  const { 前驱, 必经 } = 逻.前驱与必经(定义, "end");
  ck("「结束」之前有人工核对和写入,但它们只在「需关注」那条路上", 前驱.has("human_1") && 前驱.has("tool_2"));
  ck("T19 人工核对 / 写入 → 仅部分路径有值(不是必经)", !必经.has("human_1") && !必经.has("tool_2"));
  ck("查订单 / 判断风险 → 必经", 必经.has("tool_1") && 必经.has("condition_1"));
}

console.log("\n▸ 撤销 / 重做(§10.1)");
{
  const h = 逻.历史(3);
  ck("前后一样不记", !h.记("空", "a", "a"));
  h.记("一", "a", "b"); h.记("二", "b", "c");
  ck("连续文本输入按合并键并成一段", h.记("打字", "c", "d", "k1", 1000) && h.记("打字", "d", "e", "k1", 1500) && h.条数() === 3);
  ck("撤销回到合并那段之前", h.撤销().快照 === "c");
  ck("重做回到合并之后", h.重做().快照 === "e");
  h.撤销(); h.记("新", "c", "x");
  ck("撤销后做新修改 → 清空重做分支", !h.能重());
  h.记("四", "x", "y"); h.记("五", "y", "z");
  ck("超过上限丢最旧的(不影响当前内容)", h.条数() === 3);
}

console.log("\n▸ 冲突看差异 / 整理布局 / 逻辑变没变");
{
  const a = 图().定义, b = 图().定义;
  a.nodes.push({ id: "llm_1", type: "llm" }); b.nodes[1].name = "查订单(对方改的)";
  const x = 逻.差异(a, b);
  ck("差异分得出:只在本地的步骤 / 两边都改了的步骤", x.只在本地的步骤.includes("llm_1") && x.两边都改了的步骤.includes("tool_1"), x);
  const { 定义, 布局 } = 图();
  布局.$线 = { [键("tool_1", "success", null, "condition_1")]: [{ x: 1, y: 1 }] };
  const 新 = 逻.整理布局(定义, 布局);
  ck("整理布局只改位置:按执行顺序从左到右,定义一个字没动",
     新.start.x < 新.tool_1.x && 新.tool_1.x < 新.condition_1.x && JSON.stringify(定义) === JSON.stringify(图().定义));
  ck("整理布局把手动折点一起恢复成自动布线", 新.$线 && !Object.keys(新.$线).length);
  const 前 = 逻.快照(定义, 布局), 只挪 = 逻.快照(定义, { ...布局, start: { x: 99, y: 0 } });
  ck("只挪位置不算逻辑变了(检查报告不作废)", !逻.逻辑变了(前, 只挪));
  const 改了 = JSON.parse(JSON.stringify(定义)); 改了.edges.pop();
  ck("改连线算逻辑变了", 逻.逻辑变了(前, 逻.快照(改了, 布局)));
}

console.log(`\n${挂.length ? "❌" : "✅"} 图操作逻辑层 ${过} 条过${挂.length ? `,挂 ${挂.length} 条:${挂.join(" / ")}` : ""}`);
process.exit(挂.length ? 1 : 0);
