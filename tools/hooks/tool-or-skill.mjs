#!/usr/bin/env node
// Claude Code PostToolUse hook：**正要新增一个 agent 工具时，问一句它该不该是工具。**
//
// ── 起因与一次自我纠错 ──────────────────────────────────────────────
//
// 起因（2026-09-19，澜绣云裳agent）：项目长到 60 个 MCP 工具、3 个技能。
// 业务方一句话说中要害：「skill 那么少，说明需要 agent 决定的地方少；
// mcp 那么多，说明重复的固定流程多。」
//
// ⚠️ **这个 hook 的第一版判据是错的，而且错得很典型。**
//    第一版判的是「工具说明里有没有『先、再、然后、排序』这类词」——
//    有就提醒「像多步流程，该做成技能」。
//
//    查了 Anthropic 官方三篇之后发现方向反了：官方**鼓励**把
//    `list_users`+`list_events`+`create_event` 合成一个 `schedule_event`——
//    一次调用办完一件完整的事，正是好设计。按第一版判据，`schedule_event`
//    会被判成「该解冻」。
//
//    **真正的分界是「中间结果要不要经过模型」，不是「实现里有几步」。**
//    前者是信息的流向，后者是代码的形状 —— 而它们经常长得一样。
//
// ── 所以这一版判什么 ────────────────────────────────────────────────
//
// 「中间结果要不要经过模型」**没法从文本看出来**，所以不硬判。改成两件能判的：
//
//   ① 新增了工具 → 问一句「该由谁判断」，并提醒配套的规矩和验法（无条件）
//   ② **同一个资源被切成好几个工具** → 这是可检测的真信号
//
// 第 ② 条对应官方那句最硬的判据：
//   **「如果一个人类工程师都说不准某个场景该用哪个工具，AI 不可能做得更好。」**
//
// 「工具多」有两种，方向相反，别治反了：
//   好的多：一件事要调三次才办完   → 往上合（schedule_event）
//   坏的多：一件事按筛选条件切五个 → 合成一个 + 参数（my_tasks/team_tasks/...）
//
// 失败姿态：出错时**闭嘴**（fail silent）。它是提醒不是门禁，
//   误报的代价（被关掉）远高于漏报一次。
//
// 依据：
//   https://www.anthropic.com/engineering/writing-tools-for-agents
//   https://www.anthropic.com/engineering/code-execution-with-mcp
//   https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills

import { readFileSync, realpathSync } from "node:fs";

// ── 判据本体。自测和 hook 走**同一个函数** ──────────────────────────
// 复刻一份给自测用，那就成了第二个来源：改了一边忘了另一边，
// 自测照样全绿，而闸已经不是那个闸了。

// 通用词，不算「资源词」。拿它们判重叠会把所有 get_* 都算成同一族。
const 通用词 = new Set([
  "get", "list", "search", "query", "fetch", "read", "create", "update",
  "delete", "set", "my", "all", "new", "batch", "check", "run", "do",
]);

export function 该不该出声(工具名, inp, 读文件 = readFileSync) {
  if (!["Write", "Edit", "NotebookEdit"].includes(工具名)) return null;
  const 路径 = inp?.file_path || "";
  // 白名单，会漏 —— 但这是提醒不是门禁，宁可漏：
  // 一个在无关文件上反复出声的 hook，三天内就会被关掉。
  if (!/\.(py|ts|js|mjs|json)$/i.test(路径)) return null;

  // 这次改动**新增**了什么。Edit 只看新串 —— 含义是「这次加了什么」，
  // 不是「这个文件里有什么」。看整个文件的话，改一个错别字也会被算成新增工具。
  const 新增 = 工具名 === "Edit" ? (inp.new_string || "") : (inp.content || "");
  if (!新增 || 新增.length < 40) return null;

  // 三样齐了才算一个完整的工具定义骨架；少一样多半是在改已有工具。
  const 有名 = /["']name["']\s*:/.test(新增);
  const 有述 = /["']description["']\s*:/.test(新增);
  const 有参 = /["'](input_schema|inputSchema|parameters)["']\s*:/.test(新增);
  if (!(有名 && 有述 && 有参)) return null;

  const 名 = (新增.match(/["']name["']\s*:\s*["'`]([^"'`]+)/) || [])[1] || "";
  if (!名) return null;

  // ── 同族检测：这个文件里，有没有别的工具在查同一个资源 ────────────
  // PostToolUse 时文件已经落盘，所以能看到全貌 —— 这是这个 hook
  // 唯一能拿到「上下文」的地方，也是它比 skill 强的地方：
  // **skill 要人想起来才看，hook 在你正加第六个同族工具时当场出声。**
  let 同族 = [];
  try {
    const 全文 = 读文件(路径, "utf8");
    const 全部名 = [...全文.matchAll(/["']name["']\s*:\s*["'`]([^"'`]+)/g)]
      .map((m) => m[1])
      .filter((n) => n !== 名);
    const 词 = (n) => n.split(/[_\-.]/).filter((w) => w && !通用词.has(w.toLowerCase()));
    const 我的词 = new Set(词(名).map((w) => w.toLowerCase()));
    if (我的词.size) {
      同族 = 全部名.filter((n) =>
        词(n).some((w) => 我的词.has(w.toLowerCase())));
    }
  } catch {
    同族 = []; // 读不到就不说这一段，别猜
  }

  return { 名, 同族 };
}

export function 写提醒({ 名, 同族 }) {
  const 行 = [];
  行.push(`🧭 新增了一个 agent 工具：${名}`);
  行.push("");
  行.push("**先问一句：中间结果要不要经过模型？**");
  行.push("  **不要经过** → 工具。一次调用办完一件完整的事");
  行.push("  **要经过**   → **技能**。中间那一步的结果决定下一步做什么");
  行.push("  判错了要担责任 → 写口 + 人确认");
  行.push("");
  行.push("⚠️ 别拿「实现里有几步」当判据 —— 那是代码的形状，不是信息的流向。");
  行.push("   官方鼓励把三次调用合成一个（`schedule_event`），**步骤多不等于该拆**。");

  if (同族.length >= 2) {
    行.push("");
    行.push(`🔴 **这个文件里还有 ${同族.length} 个名字里带同一个资源词的工具**：`);
    行.push(`   ${同族.slice(0, 6).join("、")}${同族.length > 6 ? " …" : ""}`);
    行.push("");
    行.push("   官方最硬的一条自检：");
    行.push("   > **如果一个人类工程师都说不准某个场景该用哪个工具，AI 不可能做得更好。**");
    行.push("");
    行.push("   **你说得准吗？** 说不准的话，这一族该合成一个 + 参数，");
    行.push("   而不是再加第 " + (同族.length + 1) + " 个。");
  }

  行.push("");
  行.push("**省 token 的顺序（从便宜到贵，别一上来就动结构）：**");
  行.push("  ① 改工具描述 —— 官方实测：只改描述，任务完成时间降 40%");
  行.push("  ② 改返回格式 —— 加 `response_format` 让模型选详略（Slack 案例省 ⅔）");
  行.push("  ③ 按需加载工具定义 —— 不删任何工具就能省掉前置开销");
  行.push("  ④ 最后才考虑删或合并 —— 改一个能跑的东西，风险最大");
  行.push("");
  行.push("**别忘了配套的两样**（缺一不可）：");
  行.push("  · 管它的规矩 —— 「工具给了、规矩没给」比「工具没给」更危险");
  行.push("  · 验法 —— 绝对判定逐例标真值；相对指标验性质");
  行.push("");
  行.push("详见 /ai-product-shape。");
  return 行.join("\n");
}

// ── 自测 ────────────────────────────────────────────────────────────
// ⚠️ **只认 argv 里的 --selftest**。这个项目栽过两次：
//    自测整段没跑却退出 0（一次是相对路径，一次是 /tmp 软链），
//    而「跑过了全对」和「压根没跑」在输出上长得一模一样。
if (process.argv.includes("--selftest")) {
  const 定义 = (名, 述) =>
    `{"name":"${名}","description":"${述}","input_schema":{"type":"object"}}`;
  const 假读 = (内容) => () => 内容;
  const 空读 = () => "";

  let 挂 = 0;
  const 断 = (好, 说) => {
    console.log(`  ${好 ? "✅" : "❌"} ${说}`);
    if (!好) 挂++;
  };

  // ① 出声 / 闭嘴
  const 用例 = [
    [true, "新增一个完整的工具定义", "Write",
      { file_path: "a.py", content: 定义("get_order", "查订单") + " ".repeat(40) }],
    [true, "Edit 里新增一个工具定义", "Edit",
      { file_path: "a.py", new_string: 定义("get_stock", "查库存") + " ".repeat(40) }],
    [false, "只改 description 的错别字（缺 name/input_schema）", "Edit",
      { file_path: "a.py", new_string: '"description":"查订单(改了个错别字)"' + " ".repeat(40) }],
    [false, "改的是 markdown，不是放工具定义的地方", "Write",
      { file_path: "a.md", content: 定义("get_order", "查订单") + " ".repeat(40) }],
    [false, "读文件不是写", "Read", { file_path: "a.py" }],
    [false, "改动太短，多半不是新增工具", "Edit",
      { file_path: "a.py", new_string: '"name":"x"' }],
    // **不出声的那一半和出声的一样重要** —— 只测「该出声的出声了」，
    // 会写出一个见谁都出声的 hook，而那种三天内就会被关掉。
  ];
  for (const [该, 说, 名, inp] of 用例) {
    const r = 该不该出声(名, inp, 空读);
    断((r !== null) === 该, `${该 ? "该出声" : "该闭嘴"}  ${说}`);
  }

  // ② 同族检测 —— 这一版的新判据，正反都要测
  const 一族 = [
    定义("my_tasks", "看我的任务"),
    定义("team_tasks", "看团队的任务"),
    定义("get_task", "看一条任务"),
    定义("dispatch_pool", "待分配池"),
  ].join(",");
  const 同族命中 = 该不该出声("Write",
    { file_path: "a.py", content: 定义("list_tasks", "列待处理任务") + " ".repeat(40) },
    假读(一族 + "," + 定义("list_tasks", "列待处理任务")));
  断(同族命中 && 同族命中.同族.length >= 2,
    `同族检测：第 5 个 tasks 工具 → 认出 ${同族命中?.同族.length ?? 0} 个同族`);
  // ⚠️ 断言查的串要**和文案逐字对得上**。第一版查的是「说不准该用哪个」,
  //    而文案里写的是「说不准**某个场景**该用哪个工具」—— 中间隔着字,匹配不上。
  //    当时自测报红,而**红的是断言不是功能** —— 差一点就去改功能了。
  //    所以改成查一个短到不会被插字打断的锚点。
  断(写提醒(同族命中).includes("AI 不可能做得更好"),
    "同族命中 → 亮出官方那条「说不准该用哪个工具」自检");

  // 反向：资源词不同，不许乱认亲
  const 不同族 = 该不该出声("Write",
    { file_path: "a.py", content: 定义("get_order", "查订单") + " ".repeat(40) },
    假读(定义("get_stock", "查库存") + "," + 定义("get_order", "查订单")));
  断(不同族 && 不同族.同族.length === 0,
    "反向：order 和 stock 资源词不同 → **不**认作同族");
  断(!写提醒(不同族).includes("AI 不可能做得更好"),
    "不同族 → **不**亮那段（免得见谁都喊）");

  // 通用词不算资源词：get_order / get_stock 都带 get，不能因此算同族
  const 只共享通用词 = 该不该出声("Write",
    { file_path: "a.py", content: 定义("get_wearer", "查着装人") + " ".repeat(40) },
    假读([定义("get_order", "查订单"), 定义("get_stock", "查库存"),
         定义("get_wearer", "查着装人")].join(",")));
  断(只共享通用词 && 只共享通用词.同族.length === 0,
    "只共享 `get` 这种通用词 → **不**算同族（否则所有 get_* 都是一族）");

  // ③ 措辞:无论如何都要问「中间结果要不要经过模型」
  断(写提醒(不同族).includes("中间结果要不要经过模型"),
    "任何情况下都问那句核心判据");
  断(写提醒(不同族).includes("步骤多不等于该拆"),
    "带上纠错提示：别拿「实现里有几步」当判据");

  console.log(挂 ? `\n❌ ${挂} 条没过` : `\n✅ 全部通过`);
  process.exit(挂 ? 1 : 0);
}

// ── hook 分支 ───────────────────────────────────────────────────────
// ⚠️ 用 realpathSync 比对：`/tmp` 在 macOS 上是 `/private/tmp` 的软链，
//    不解析的话，从软链路径跑起来的自测会走进 hook 分支然后卡在读 stdin 上。
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
