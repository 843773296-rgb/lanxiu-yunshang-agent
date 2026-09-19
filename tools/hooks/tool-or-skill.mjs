#!/usr/bin/env node
// Claude Code PostToolUse hook：**正要新增一个 agent 工具时，问一句它该不该是工具。**
//
// 起因（2026-09-19，澜绣云裳agent 项目）：这个项目长到了 60 个 MCP 工具、3 个技能。
// 业务方看了一眼就说中了要害：
//     「skill 那么少，说明需要 agent 决定的地方有点少；
//       mcp 那么多，说明重复的固定流程有点多。」
//
// 复盘下来，60 个里有 13 个装的是**流程不是取数** —— 多步、步间有判断，
// 被压成了一次调用。而平均每轮只调 1.08 个工具 ——
// 那个数一直被当成「效率高」在报，实际是症状：
// **每轮只调一次，因为每个工具都已经把一整件事做完了。**
//
// > 用 Agent 的壳，跑 workflow 的芯。
//
// 关键在于：**没有任何一次是错的，是每一次都「只多一个」**。
// 需要看自己的任务加一个、店长看团队再加一个、待分配池又一个……
// 每一步都合理，而代价不落在那一步上 —— 它落在此后每一次调用上
//（实测：工具 26→59，提示词 21KB→55KB，成本涨 38%，能力没变）。
//
// 所以这道闸装在「正要多加一个」的那一刻。它**不阻止**任何事，只出声。
//
// ⚠️ 这道闸自己最容易犯的错，正是它要提醒的那类：判据贴着字面而不是含义。
//    「文件里有 name/description/input_schema」是字面 —— 会把改一个错别字也算成新增工具。
//    「这次改动新增了一个工具定义」是含义。所以判的是**新增的那几行里**有没有
//    完整的工具定义骨架，而不是整个文件里有没有。
//
// 失败姿态：出错时**闭嘴**（fail silent）。它是提醒不是门禁，
//   误报的代价（被关掉）远高于漏报一次。

import { readFileSync, realpathSync } from "node:fs";

// ── 判据本体。自测和 hook 走**同一个函数** ──────────────────────────
// 复刻一份给自测用,那就成了第二个来源:改了一边忘了另一边,
// 自测照样全绿,而闸已经不是那个闸了。
export function 该不该出声(工具名, inp) {
  if (!["Write", "Edit", "NotebookEdit"].includes(工具名)) return null;
  const 路径 = inp?.file_path || "";
  // 白名单,会漏 —— 但这是提醒不是门禁,宁可漏:
  // 一个在无关文件上反复出声的 hook,三天内就会被关掉。
  if (!/\.(py|ts|js|mjs|json)$/i.test(路径)) return null;

  // 这次改动**新增**了什么。Edit 只看新串 —— 含义是「这次加了什么」,
  // 不是「这个文件里有什么」。看整个文件的话,改一个错别字也会被算成新增工具。
  const 新增 = 工具名 === "Edit" ? (inp.new_string || "") : (inp.content || "");
  if (!新增 || 新增.length < 40) return null;

  // 三样齐了才算一个完整的工具定义骨架;少一样多半是在改已有工具。
  const 有名 = /["']name["']\s*:/.test(新增);
  const 有述 = /["']description["']\s*:/.test(新增);
  const 有参 = /["'](input_schema|inputSchema|parameters)["']\s*:/.test(新增);
  if (!(有名 && 有述 && 有参)) return null;

  const 说明 = (新增.match(/["']description["']\s*:\s*["'`]([^"'`]{0,400})/) || [])[1] || "";
  const 流程味 = [
    "先", "再", "然后", "依次", "逐条", "逐个", "一次算完", "一并",
    "漏斗", "排序", "优先", "建议", "看板", "清单", "复盘", "对比",
    "→", "步骤", "流程",
  ].filter((w) => 说明.includes(w));
  const 名 = (新增.match(/["']name["']\s*:\s*["'`]([^"'`]+)/) || [])[1] || "这个新工具";
  return { 名, 流程味 };
}

export function 写提醒({ 名, 流程味 }) {
  const 行 = [];
  行.push(`🧭 看到新增了一个 agent 工具:${名}`);
  行.push("");
  行.push("**先问一句:这件事该由谁判断?**");
  行.push("  代码判断 → 工具(每一步都有唯一正确答案)");
  行.push("  模型判断 → **技能**(前一步的结果决定下一步查什么)");
  行.push("  人判断   → 写口 + 确认(判错了要担责任)");
  if (流程味.length >= 2) {
    行.push("");
    行.push(`⚠️ 它的说明里有「${流程味.slice(0, 4).join("、")}」——**闻起来像多步流程,不像一次取数**。`);
    行.push("   多步且步间有判断的,冻进工具等于**把本该 agent 做的判断提前替它做了**。");
  }
  行.push("");
  行.push("**两个当场能用的自检:**");
  行.push("  · 名字里有动词或业务场景吗?有的话多半该是技能(工具跟表走,不跟场景走)");
  行.push("  · 换个熟练员工来做,他会不会中途改主意?会 → 判断是活的 → 技能");
  行.push("");
  行.push("**代价提醒**:工具定义每次调用都全带上。实测过一次 —— 工具 26→59、");
  行.push("提示词 21KB→55KB,**成本涨 38%,而调用数、耗时、能力一点没变**。");
  行.push("");
  行.push("**别忘了配套的两样**(缺一不可):");
  行.push("  · 管它的规矩 —— 「工具给了、规矩没给」比「工具没给」更危险");
  行.push("  · 验法 —— 绝对判定逐例标真值;相对指标验性质");
  行.push("");
  行.push("详见 /ai-product-shape。");
  return 行.join("\n");
}

// ── 自测 ────────────────────────────────────────────────────────────
// ⚠️ **只认 argv 里的 --selftest**。这个项目栽过两次:
//    自测整段没跑却退出 0(一次是相对路径,一次是 /tmp 软链),
//    而「跑过了全对」和「压根没跑」在输出上长得一模一样。
if (process.argv.includes("--selftest")) {
  const 工具定义 = (述) =>
    `{"name":"foo","description":"${述}","input_schema":{"type":"object"}}`;
  const 用例 = [
    // [该不该出声, 说明, 工具名, 入参]
    [true, "新增一个完整的工具定义", "Write",
      { file_path: "a.py", content: 工具定义("查订单") + " ".repeat(40) }],
    [true, "Edit 里新增一个工具定义", "Edit",
      { file_path: "a.py", new_string: 工具定义("查库存") + " ".repeat(40) }],
    [false, "只改了 description 的错别字(缺 name/input_schema)", "Edit",
      { file_path: "a.py", new_string: '"description":"查订单(改了个错别字)"' + " ".repeat(40) }],
    [false, "改的是 markdown,不是放工具定义的地方", "Write",
      { file_path: "a.md", content: 工具定义("查订单") + " ".repeat(40) }],
    [false, "读文件不是写", "Read", { file_path: "a.py" }],
    [false, "改动太短,多半不是新增工具", "Edit",
      { file_path: "a.py", new_string: '"name":"x"' }],
    // **不出声的那一半和出声的一样重要** —— 只测「该出声的出声了」,
    // 会写出一个见谁都出声的 hook,而那种 hook 三天内就会被关掉。
  ];
  let 挂 = 0;
  for (const [该, 说, 名, inp] of 用例) {
    const r = 该不该出声(名, inp);
    const 实 = r !== null;
    const 好 = 实 === 该;
    if (!好) 挂++;
    console.log(`  ${好 ? "✅" : "❌"} ${该 ? "该出声" : "该闭嘴"}  ${说}  → ${实 ? "出声了" : "闭嘴了"}`);
  }

  // 措辞那一支也要验:流程味够了才加那段警告
  const 多步 = 该不该出声("Write", {
    file_path: "a.py",
    content: 工具定义("先查 A,再根据结果查 B,然后按金额排序给出建议") + " ".repeat(40),
  });
  const 单步 = 该不该出声("Write", {
    file_path: "a.py",
    content: 工具定义("按订单号取一条订单") + " ".repeat(40),
  });
  const a = 写提醒(多步).includes("闻起来像多步流程");
  const b = !写提醒(单步).includes("闻起来像多步流程");
  console.log(`  ${a ? "✅" : "❌"} 多步说明 → 带上「像流程」那段警告`);
  console.log(`  ${b ? "✅" : "❌"} 一次取数 → **不**带那段警告(免得见谁都喊)`);
  if (!a) 挂++;
  if (!b) 挂++;

  console.log(挂 ? `\n❌ ${挂} 条没过` : `\n✅ ${用例.length + 2}/${用例.length + 2} 通过`);
  process.exit(挂 ? 1 : 0);
}

// ── hook 分支 ───────────────────────────────────────────────────────
// ⚠️ 用 realpathSync 比对:`/tmp` 在 macOS 上是 `/private/tmp` 的软链,
//    不解析的话,从软链路径跑起来的自测会走进 hook 分支然后卡在读 stdin 上。
const 我 = realpathSync(new URL(import.meta.url).pathname);
const 入口 = process.argv[1] ? realpathSync(process.argv[1]) : "";
if (我 === 入口) {
  let 输入 = "";
  try {
    输入 = readFileSync(0, "utf8");
  } catch {
    process.exit(0);
  }
  let ev;
  try {
    ev = JSON.parse(输入);
  } catch {
    process.exit(0);
  }
  let r = null;
  try {
    r = 该不该出声(ev?.tool_name || "", ev?.tool_input || {});
  } catch {
    process.exit(0); // fail silent —— 它是提醒不是门禁
  }
  if (r) console.log(写提醒(r));
  process.exit(0);
}
