#!/usr/bin/env node
/**
 * 交接门禁 —— **压缩是察觉不到的,所以不能靠「记得」。**
 *
 * ## 起因
 *
 * 上下文满了会自动压缩。压缩保的是「读起来连贯」,不保「哪些事还没验」。
 * 压完之后的我**不知道自己被压过** —— 摘要读起来完整、自洽、没有窟窿,
 * 于是我接着往下干,而那些「跑过但结论作废的」「预判了还没验的」
 * 「说好不能碰的」已经没了。
 *
 * 这件事被抓过两次,两次的修法都是「以后记得写交接」——
 * **而「记得」正是压缩要拿走的东西。** 所以这次改成门禁。
 *
 * ## 三个挂载点,各管一段,缺一不可
 *
 *   UserPromptSubmit  到 65% 就报数(提前知道,好安排)
 *   Stop              到 80% 且交接不新鲜 → **exit 2,不许收工**
 *   PreCompact        压缩真发生时记一笔:当时交接新不新鲜
 *
 * 只有 Stop 能拦(官方文档:Stop 的 exit 2 = 不让它停,继续对话)。
 * PostToolUse 拦不住,所以不挂 —— **挂一个拦不住的点,等于没挂。**
 *
 * ## 为什么要自己算 token
 *
 * hook 的输入里**没有上下文用量**(官方字段就那几个:session_id /
 * transcript_path / cwd / permission_mode / effort / hook_event_name …)。
 * 但 transcript 里每条助手消息都带 usage,所以从那里算。
 *
 *   已占用 = input + cache_read + cache_creation + output
 *
 * cache_read 必须算进去 —— 它是**读缓存**,不是「没花的钱」,
 * 那些 token 实实在在占着窗口。漏掉它会把 77% 算成 3%,门禁永不触发。
 */
import { readFileSync, writeFileSync, existsSync, statSync, openSync, readSync, fstatSync, closeSync, appendFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { homedir } from "node:os";

const 阈值 = Number(process.env.HANDOFF_GATE_PCT || 80) / 100;
const 预警 = Number(process.env.HANDOFF_GATE_WARN_PCT || 65) / 100;
const 最多拦几次 = 2;                       // 防死循环:拦到第 3 次就放行并留话
// ⚠️ 状态目录可改 —— **自测必须跟真实运行分开存。**
// 第一版没分,自测写进了真实目录,上一轮的「拦过几次」漏到下一轮,
// 于是咬合时红的不是被改坏的那一条。**测试和被测共用状态,测出来的不算数。**
const 状态目录 = process.env.HANDOFF_GATE_STATE
  || join(homedir(), ".claude", "state", "handoff-gate");

// ── 自测 ──────────────────────────────────────────────────────────────
// **自测写在 hook 自己身上,不写成外挂脚本。** 外挂的会跟本体分家:
// 改了本体忘了改脚本,脚本就慢慢烂掉 —— 而**烂掉的样子和好着的样子一模一样**。
// 这样它能作为一条进门禁(`node tools/hooks/handoff-gate.mjs --selftest`)。
if (process.argv.includes("--selftest")) {
  const { spawnSync } = await import("node:child_process");
  const { mkdtempSync, rmSync, utimesSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  // ⚠️ 用 fileURLToPath,别用 `new URL(...).pathname`。
  //    路径里有中文时 pathname 拿到的是百分号编码的串,当文件名用找不到文件,
  //    于是自测整个跑不起来 —— 而「跑不起来」和「全挂了」在输出上一模一样。
  //    在 ~/.claude(纯 ASCII)下测不出来,搬进仓库(路径含中文)才炸。
  const { fileURLToPath } = await import("node:url");
  const 本文件 = fileURLToPath(import.meta.url);
  const D = mkdtempSync(join(tmpdir(), "handoff-gate-"));
  let 过 = 0, 败 = [];
  const ck = (名, 实, 期) => 实 === 期 ? (过++, console.log(`  ✅ ${名}`))
    : (败.push(名), console.log(`  ❌ ${名}  期望[${期}] 实得[${实}]`));
  const 造 = (总, 子 = false) => writeFileSync(join(D, "t.jsonl"), JSON.stringify(
    { type: "assistant", isSidechain: 子, message: { model: "claude-opus-5", usage: {
      input_tokens: 2, cache_read_input_tokens: 总 - 2, cache_creation_input_tokens: 0, output_tokens: 0 } } }) + "\n");
  let 末 = { out: "", err: "" };
  const 跑 = (事件, 目录, 会) => {
    const r = spawnSync(process.execPath, [本文件], {
      input: JSON.stringify({ hook_event_name: 事件, session_id: 会, cwd: 目录, transcript_path: join(D, "t.jsonl") }),
      env: { ...process.env, HANDOFF_GATE_WINDOW: "200000", HANDOFF_GATE_STATE: join(D, "state") },
      encoding: "utf8" });
    末 = { out: r.stdout || "", err: r.stderr || "" };
    return r.status;
  };
  const 项 = join(D, "proj"); mkdirSync(项, { recursive: true });
  const 交件 = join(项, "HANDOFF.md");
  const 变旧 = () => { writeFileSync(交件, "old"); const t = new Date(2020, 0, 1); utimesSync(交件, t, t); };
  变旧();

  console.log("交接门禁 · 自测");
  造(100_000); ck("① 一半的时候不拦", 跑("Stop", 项, "s1"), 0);
  造(170_000); ck("② 过 80% 且交接过期 → 拦住(exit 2)", 跑("Stop", 项, "s2"), 2);
  ck("   ↳ 拦的时候说清了要做什么", /不能收工[\s\S]*刷新/.test(末.err), true);
  // ③ 越线之后刷了交接 → 放行。**这条验的是「刷过就放行」那一步**,
  //    少了它,写完交接也出不去,会话卡死。
  writeFileSync(交件, "new");
  ck("③ 越线后刷了交接 → 放行", 跑("Stop", 项, "s2"), 0);
  变旧();
  const a = 跑("Stop", 项, "s4"), b = 跑("Stop", 项, "s4"), c = 跑("Stop", 项, "s4");
  ck("④ 拦满 2 次后放行(不许把会话卡死)", `${a}${b}${c}`, "220");
  // ⑤ 没有 HANDOFF.md 的项目只提醒不拦 —— 只读的顾问会话不能被逼着写文件
  const 空 = join(D, "bare"); mkdirSync(空, { recursive: true });
  ck("⑤ 没有交接文件的项目不拦", 跑("Stop", 空, "s5"), 0);
  const 关 = join(D, "off"); mkdirSync(join(关, ".claude"), { recursive: true });
  writeFileSync(join(关, "HANDOFF.md"), "x"); writeFileSync(join(关, ".claude", "no-handoff-gate"), "");
  ck("⑥ 放了 no-handoff-gate 就彻底不管", 跑("Stop", 关, "s6"), 0);
  造(140_000); 跑("UserPromptSubmit", 项, "s7");
  ck("⑦ 预警走 stdout(才会进模型上下文,stderr 不会)", /交接门禁/.test(末.out), true);
  // ⑧ 子任务有自己的上下文。不排掉的话,一个跑大了的子任务会把主线误判成快满。
  造(170_000, true); ck("⑧ 子任务跑大了不误判主线", 跑("Stop", 项, "s8"), 0);
  const r9 = spawnSync(process.execPath, [本文件], {
    input: JSON.stringify({ hook_event_name: "Stop", session_id: "s9", cwd: 项, transcript_path: "/nope" }),
    env: { ...process.env, HANDOFF_GATE_STATE: join(D, "state") }, encoding: "utf8" });
  ck("⑨ 读不到用量就不拦(宁可漏也不瞎拦)", r9.status, 0);

  rmSync(D, { recursive: true, force: true });
  if (败.length) { console.log(`❌ ${败.length} 条没过:${败.join("、")}`); process.exit(1); }
  console.log(`✅ 交接门禁 ${过} 条全过`); process.exit(0);
}

// ── 读输入 ────────────────────────────────────────────────────────────
let inp = {};
try { inp = JSON.parse(readFileSync(0, "utf8") || "{}"); } catch { }
const 事件 = inp.hook_event_name || "";
const 会话 = inp.session_id || "unknown";
const cwd = inp.cwd || process.cwd();

// ── 上下文窗口多大 ────────────────────────────────────────────────────
// transcript 里的 model 只写 "claude-opus-5",**不带 [1m] 后缀**,
// 所以从那里看不出是 20 万还是 100 万的窗口。改从配置读,并留一条
// 观测兜底:真见过超过 20 万的占用,那它必然是 100 万的窗口。
function 窗口大小(已占用) {
  if (process.env.HANDOFF_GATE_WINDOW) return Number(process.env.HANDOFF_GATE_WINDOW);
  let w = 200_000;
  try {
    const s = JSON.parse(readFileSync(join(homedir(), ".claude", "settings.json"), "utf8"));
    if (/\[1m\]|1m/i.test(String(s.model || ""))) w = 1_000_000;
  } catch { }
  if (已占用 > 200_000) w = 1_000_000;      // 20 万的窗口里不可能出现这个数
  return w;
}

// ── 从 transcript 尾部算已占用 ────────────────────────────────────────
// 只读尾部 4MB。整份读会随会话变长而越来越慢,而这个 hook 每次收工都跑。
function 已占用() {
  const p = inp.transcript_path;
  if (!p || !existsSync(p)) return null;
  let fd;
  try {
    fd = openSync(p, "r");
    const 尺寸 = fstatSync(fd).size;
    const 取 = Math.min(尺寸, 4 * 1024 * 1024);
    const buf = Buffer.alloc(取);
    readSync(fd, buf, 0, 取, 尺寸 - 取);
    let 行 = buf.toString("utf8").split("\n");
    if (取 < 尺寸) 行.shift();               // 头一行多半是截断的半行
    for (let i = 行.length - 1; i >= 0; i--) {
      if (!行[i].trim()) continue;
      let d; try { d = JSON.parse(行[i]); } catch { continue; }
      // ⚠️ 子任务(sidechain)有自己的上下文,它的 usage 跟主线无关。
      //    不排掉的话,一个子任务跑大了会把主线误判成快满。
      if (d.isSidechain) continue;
      const u = d?.message?.usage;
      if (!u) continue;
      return (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
           + (u.cache_creation_input_tokens || 0) + (u.output_tokens || 0);
    }
  } catch { } finally { if (fd !== undefined) try { closeSync(fd); } catch { } }
  return null;
}

// ── 这个项目用不用交接 ────────────────────────────────────────────────
// 判据是「**项目里已经有 HANDOFF.md**」,不是「我觉得该有」。
// 没有的项目(比如只读的顾问会话)只提醒不拦 —— 一道会在正常工作里
// 误拦的闸,迟早会被关掉。
function 找交接() {
  let d = cwd;
  for (let i = 0; i < 4; i++) {
    if (existsSync(join(d, ".claude", "no-handoff-gate"))) return { 关掉: true };
    for (const n of ["HANDOFF.md", "HANDOFF.MD", "handoff.md"]) {
      const f = join(d, n);
      if (existsSync(f)) return { 路径: f, mtime: statSync(f).mtimeMs };
    }
    const 上 = dirname(d);
    if (上 === d) break;
    d = 上;
  }
  return {};
}

function 读状态() {
  try { return JSON.parse(readFileSync(join(状态目录, 会话 + ".json"), "utf8")); }
  catch { return { 拦过: 0 }; }
}
function 写状态(s) {
  try { mkdirSync(状态目录, { recursive: true }); writeFileSync(join(状态目录, 会话 + ".json"), JSON.stringify(s)); } catch { }
}

// ── 主流程 ────────────────────────────────────────────────────────────
const 占 = 已占用();
if (占 === null) process.exit(0);           // 读不到就别瞎拦
const 窗 = 窗口大小(占);
const 比 = 占 / 窗;
const 万 = n => (n / 10000).toFixed(1) + " 万";
const 报数 = `上下文 ${万(占)} / ${万(窗)} = ${(比 * 100).toFixed(0)}%`;
const 交 = 找交接();
const st = 读状态();

if (事件 === "PreCompact") {
  // 压缩真发生了。**这是唯一能确认门禁有没有白干的地方。**
  const 新鲜 = 交.mtime && st.越线于 && 交.mtime > st.越线于;
  try {
    mkdirSync(状态目录, { recursive: true });
    appendFileSync(join(状态目录, "compactions.log"),
      `${new Date().toISOString()}\t${会话}\t${inp.trigger || "?"}\t${报数}\t交接${交.路径 ? (新鲜 ? "新鲜" : "过期") : "没有"}\t${交.路径 || cwd}\n`);
  } catch { }
  写状态({ 拦过: 0 });                       // 压缩后重新计一轮
  process.exit(0);
}

if (事件 === "UserPromptSubmit") {
  if (比 >= 预警) {
    // UserPromptSubmit 的 stdout 会作为上下文交给模型(官方明确写了这条)
    if (交.关掉) process.exit(0);
    if (!交.路径) {
      console.log(`[交接门禁] ${报数}。这个项目里没有 HANDOFF.md,所以门禁只提醒不拦。`
        + `如果这是个会跨多轮的项目,建议现在建一个(跑 handoff-before-compact 技能),否则压缩时的判断依据会丢。`);
    } else {
      const 新鲜 = st.越线于 && 交.mtime > st.越线于;
      console.log(`[交接门禁] ${报数}${比 >= 阈值 ? `,已过 ${阈值 * 100}% 线` : ""}。`
        + `交接文件 ${交.路径} ${新鲜 ? "本轮已刷新" : "尚未刷新"}。`
        + (比 >= 阈值 && !新鲜 ? ` **现在就该刷交接**,不要等收工时被拦。` : ""));
    }
  }
  process.exit(0);
}

if (事件 === "Stop" || 事件 === "SubagentStop") {
  if (事件 === "SubagentStop") process.exit(0);   // 子任务有自己的上下文,不归这儿管
  if (比 < 阈值 || 交.关掉 || !交.路径) process.exit(0);

  if (!st.越线于) { st.越线于 = Date.now(); 写状态(st); }
  if (交.mtime > st.越线于) process.exit(0);      // 越线之后刷过了,放行

  if (st.拦过 >= 最多拦几次) {
    // **拦不动就得放行。** 一道卡死会话的闸,比一道漏报的闸更糟 ——
    // 用户会把它整个关掉,那时候连提醒都没了。
    写状态({ ...st, 拦过: st.拦过 + 1 });
    process.exit(0);
  }
  st.拦过 += 1;
  写状态(st);

  console.error(
`[交接门禁] ${报数} —— 已过 ${阈值 * 100}% 线,现在**不能收工**。

接下来自动压缩随时会发生,而压缩会拿走「哪些结论还没验」「当时为什么这么判」
「哪些事说好不能碰」—— 压完之后的你读不出缺了这些。

现在做两件事,按顺序:

  1. 刷新 ${交.路径}
     用 handoff-before-compact 技能里的六项,**只写压缩留不下的那些**:
     未验证的预判 / 判据(为什么这么判) / 作废的结果 / 禁区 / 下一步第一个动作 / 悬而未决的问题
  2. 刷完在回复最后单独写一行,原样告诉用户:
     「交接已刷新,建议现在输入 /compact」

(这是第 ${st.拦过} 次拦;拦满 ${最多拦几次} 次会放行,但压缩时会记一笔交接过期。)`);
  process.exit(2);
}
process.exit(0);
