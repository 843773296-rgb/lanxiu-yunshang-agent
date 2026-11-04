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
 *   UserPromptSubmit  到预警线就报数(提前知道,好安排)
 *   Stop              过线且交接不新鲜 → **exit 2,不许收工**
 *   PreCompact        压缩真发生时记一笔:当时交接新不新鲜
 *
 * ## ⚠️ 那条线不是写死的 80% —— 它从台账学(2026-11-04 改)
 *
 * 原来写死 80%。2026-11-03 查出来:这台机器上 auto 压缩**实际发生在 30%**,
 * 于是 80% 那条线**一次都没到过** —— `越线于` 从不设置,Stop 从不拦,
 * 而 PreCompact 因为拿不到基准,一律记「交接过期」。
 * 当天三次压缩全是这样,`拦过` 计数从头到尾是 0。
 *
 * > **一道从不触发的闸,和一道守得住的闸,在「没拦过」这件事上长得一模一样。**
 *
 * 根因是**百分比这个口径本身会漂**:同样的 80%,在 20 万窗口上是 16 万
 * (压缩前,闸有效),在 100 万窗口上是 80 万(压缩早就发生了,闸没用)。
 * 写死一个比例,等于把判据锚在一个**含义会变**的数上。
 *
 * 改成从**观测**学:台账里记着每次压缩时的真实占用,拿它当线。
 * 判据锚在「这台机器实际在什么占用上被压过」,而不是锚在一个比例上。
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

// ⚠️ 这两个是**上限**,不是最终值 —— 下面 学阈值() 可能把它们调低。
//    环境变量给死值时(自测、临时覆盖)照旧说一不二。
let 阈值 = Number(process.env.HANDOFF_GATE_PCT || 80) / 100;
let 预警 = Number(process.env.HANDOFF_GATE_WARN_PCT || 65) / 100;
const 阈值写死了 = !!process.env.HANDOFF_GATE_PCT;
const 学线下限 = 0.15;                      // 学到的线不低于这个 —— 再低就是一开始就拦
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
  const 造 = (总, 子 = false, 时 = null) => writeFileSync(join(D, "t.jsonl"), JSON.stringify(
    { type: "assistant", isSidechain: 子, ...(时 ? { timestamp: 时 } : {}),
      message: { model: "claude-opus-5", usage: {
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

  // ── ⑩ 真实漏过的那个形状:交接在项目根,而会话跑在深层子目录 ──────
  //
  // 2026-09-19 漏了一次真的:会话的 cwd 是
  //   交互设计师工具/capability-evolution/reaudit/repairs/<批次>/<轮次>
  // 而 HANDOFF.md 在**第 5 层**的项目根上。第一版往上只走 4 层,没找到,
  // 于是走了「这个项目不用交接」那条路 —— 只提醒不拦 ——
  // 那个会话一路开到 96% 自动压缩,一句交接都没写。
  //
  // ⚠️ **上面九条当时全绿。** 它们每一条都把交接放在 cwd 里,
  // 而真实项目的交接在项目根上、会话在子目录里跑。
  // **测试覆盖的是我想到的形状,不是会发生的形状。**
  const 仓 = join(D, "repo"); mkdirSync(join(仓, ".git"), { recursive: true });
  const 仓交 = join(仓, "HANDOFF.md");
  writeFileSync(仓交, "old"); { const t = new Date(2020, 0, 1); utimesSync(仓交, t, t); }
  const 深 = join(仓, "a", "b", "c", "d", "e");   // 五层深,比第一版走的 4 层还深
  mkdirSync(深, { recursive: true });
  造(170_000);
  ck("⑩ 交接在项目根、会话在深层子目录 → 照样拦得住", 跑("Stop", 深, "s10"), 2);
  ck("   ↳ 拦的时候指的是项目根上那一份", 末.err.includes(仓交), true);

  // ⑪ 在仓库里但没有交接:**不拦**(只读的顾问项目不能被逼着写文件),
  //    但话要说清是「这个仓库里没有」,不能和「不在仓库里」混成一句。
  const 空仓 = join(D, "emptyrepo"); mkdirSync(join(空仓, ".git"), { recursive: true });
  const 空深 = join(空仓, "x", "y"); mkdirSync(空深, { recursive: true });
  ck("⑪ 仓库里没有交接 → 不拦", 跑("Stop", 空深, "s11"), 0);
  跑("UserPromptSubmit", 空深, "s11");
  ck("   ↳ 但明说是「仓库里没有」,并给出关掉的办法",
     末.out.includes("没有 HANDOFF.md") && 末.out.includes("no-handoff-gate"), true);

  // ⑫ 不在任何仓库里:门禁彻底不介入,话也不一样
  造(170_000);
  跑("UserPromptSubmit", 空, "s12");
  ck("⑫ 不在仓库里 → 说的是「不介入」,不跟上面那条混", 末.out.includes("不在任何 git 仓库"), true);

  // ⑬ 真实踩过的顺序:先被提示 → 照提示刷交接 → 收工。**必须放行。**
  //    ①–⑫ 全绿时这条是挂的:越线时刻只在 Stop 里记,提前刷的交接被判成旧的。
  变旧(); 造(170_000);
  跑("UserPromptSubmit", 项, "s13");
  ck("⑬ 提示时就记下越线,并叫它刷", /尚未刷新[\s\S]*现在就该刷交接/.test(末.out), true);
  spawnSync("sleep", ["0.05"]);
  writeFileSync(交件, "new");
  ck("   ↳ 照提示刷了交接再收工 → 放行", 跑("Stop", 项, "s13"), 0);
  跑("UserPromptSubmit", 项, "s13");
  ck("   ↳ 再发消息时说的是「本轮已刷新」", 末.out.includes("本轮已刷新"), true);

  // ⑭ **没过线时不许说「尚未刷新」**(2026-10-15 真实踩的)。
  //    「新鲜」要拿 `交.mtime > st.越线于` 算,而越线时刻**只在过线之后才记** ——
  //    过线之前没有基准,算不出新鲜度。而原来那句话是无条件印的:
  //    **刷了也说「尚未刷新」,不刷也说「尚未刷新」**。
  //    实测:70%~80% 之间每一轮都这么提示,而那几轮交接刚刷过、刚提交过。
  //    > 一个「真的没刷新」和一个「还没到能判断的时候」,
  //    > **在「尚未刷新」这四个字上长得一模一样。**
  // ⚠️ 自测把窗口固定成 200_000(见 `跑()` 里的 HANDOFF_GATE_WINDOW),所以
  //    **这里的数字要除以 20 万才是百分比**。第一版我写 `造(72_000)` 并注释「72%」——
  //    实际是 36%,低于预警线 65%,**那一整段分支根本没执行**,
  //    而第一条断言(「不说尚未刷新」)照样绿:它确实没说,因为什么都没打印。
  //    144_000 / 200_000 = 72% —— 预警线(65%)之上、阈值线(80%)之下。
  变旧(); 造(144_000);
  跑("UserPromptSubmit", 项, "s14");
  ck("⑭ 没过线时不说「尚未刷新」(那时根本没有基准可比)",
     !末.out.includes("尚未刷新"), true);
  ck("   ↳ 而是如实说「这一轮不判新鲜度」", 末.out.includes("不判新鲜度"), true);
  ck("   ↳ 也不催「现在就该刷交接」(还没到那条线)",
     !末.out.includes("现在就该刷交接"), true);

  // ── ⑮–㉑ 那条线从台账学(2026-11-04 加)──────────────────────────────
  //
  // **逼出这几条的那次翻车**:2026-11-03 当天三次 auto 压缩分别发生在
  // 31% / 40% / 30%,而闸线写死 80% —— **一次都没到过**。
  // `拦过` 从头到尾是 0,PreCompact 因为拿不到基准,三次全记「交接过期」。
  // 那天交接最后一次刷在压缩前 **70 分钟**,中间那 70 分钟一个字没进交接。
  //
  // ⚠️ 这几条**必须自己造台账**:真实台账在 ~/.claude/state 下,而自测的
  //    STATE 指向临时目录(本来就该分开,见文件头那条注释)。不造的话
  //    学阈值() 永远返回 null,下面这几条逻辑**一行都跑不到** ——
  //    而那时它们照样全绿。
  const 造台账 = 行 => {
    mkdirSync(join(D, "state"), { recursive: true });
    writeFileSync(join(D, "state", "compactions.log"),
      行.map(c => c.join("\t")).join("\n") + (行.length ? "\n" : ""));
  };
  const 台 = (会, 触发, 万数) => [new Date(2026, 0, 1).toISOString(), 会, 触发,
    `上下文 ${万数} 万 / 20.0 万 = ${Math.round(万数 / 20 * 100)}%`, "交接过期", 交件];

  变旧();
  // ⑮ 主判据:台账说这台机器在 12 万就被压过 → 线挪到 51%,于是 55% 这个
  //    「固定 80% 下安全得很」的占用必须被拦住。
  造台账([台("sA", "auto", 12), 台("sA", "auto", 13)]);
  造(110_000);
  ck("⑮ 台账说 12 万就压过 → 55% 也要拦(线从台账学)", 跑("Stop", 项, "sA"), 2);
  ck("   ↳ 报数里说清线是多少、学自哪", /线 \d+%,学自/.test(末.err), true);

  // ⑯ **反向**:manual 不算 —— 人主动压的,压在什么占用上由人决定。
  //    缺了这条,台账里一条 8% 的 manual 就能把线学到荒谬的低位。
  造台账([台("sB", "manual", 12), 台("sB", "manual", 13)]);
  ck("⑯ 只有 manual 的台账 → 不学(人主动压的不代表窗口压力)", 跑("Stop", 项, "sB"), 0);

  // ⑰ **反向**:一条记录学不出线。「学了个不靠谱的线」比「没学」更糟 ——
  //    它把闸挪到一个没有依据的位置,而输出上看不出来。
  造台账([台("sC", "auto", 12)]);
  ck("⑰ 只有 1 次 auto → 样本不足,不学", 跑("Stop", 项, "sC"), 0);

  // ⑱ **反向**:学到的线有下限。台账里都是极低占用时不许把闸挪到 4%,
  //    否则会话一开始就被拦 —— 一道在正常工作里误拦的闸迟早被整个关掉。
  造台账([台("sD", "auto", 1), 台("sD", "auto", 1.1)]);
  造(20_000);
  ck("⑱ 台账占用极低时守下限,不许学到一开始就拦", 跑("Stop", 项, "sD"), 0);

  // ⑲ PreCompact:**没有基准时要说「判不了」,不许说「过期」**。
  //    这正是 11-03 那三条「交接过期」的真相 —— 它们说的其实是「判不了」。
  造台账([]);
  造(110_000);
  跑("PreCompact", 项, "sE");
  const 账E = readFileSync(join(D, "state", "compactions.log"), "utf8");
  ck("⑲ 没有基准 → 台账记「判不了」", /判不了/.test(账E), true);
  ck("   ↳ 而且不许记成「过期」(两者动作不同:一个去刷,一个去查为什么判不了)",
     !/交接过期/.test(账E), true);

  // ⑳ 有上次压缩当基准 → 判得出来。交接比那次压缩新 → 新鲜。
  造台账([台("sF", "auto", 12)]);
  writeFileSync(交件, "fresh");            // mtime = 现在,晚于台账里那条(2026-01-01)
  跑("PreCompact", 项, "sF");
  const 账F = readFileSync(join(D, "state", "compactions.log"), "utf8").trim().split("\n").pop();
  ck("⑳ 拿上次压缩当基准 → 判得出「新鲜」", /交接新鲜/.test(账F), true);

  // ㉑ **数旧了要说。** 11-03 门禁报的 29.7 万是 54 分钟前那一轮的,
  //    而报数里看不出来 —— 「刚算的 30%」和「54 分钟前的 30%」印得一模一样。
  变旧();
  造台账([]);
  造(140_000, false, new Date(Date.now() - 54 * 60 * 1000).toISOString());
  跑("UserPromptSubmit", 项, "sG");
  ck("㉑ 占用数是旧的 → 报数里标出多久前", /54 分钟前那一轮/.test(末.out), true);
  造(140_000);                              // 不带时刻 → 不该标
  跑("UserPromptSubmit", 项, "sH");
  ck("   ↳ 反向:数是新的就不标(不许一律加这句话)",
     !/分钟前那一轮/.test(末.out), true);

  // ── ㉒㉓ 催不催 /compact 是**有条件的**(2026-11-04 加)────────────────
  //
  // 用户 2026-10-28 定过:**没到 75% 别提 /compact**。而这道闸的线刚从
  // 写死的 80% 降到「从台账学」(这台机器上约 25%)—— 线一降,原来那句
  // 「一律在最后提一句 /compact」就等于**在 25% 占用时催用户压缩**,
  // 正是他说过别做的事。
  //
  // > 闸提前了,催促的话就不能照搬 —— 否则这道闸会开始在用户明确不想
  // > 被打扰的时候打扰他,而它迟早因此被整个关掉。
  //
  // ⚠️ ㉓ 是**反向用例**。缺了它,「一律提 /compact」也能判成通过。
  变旧();
  造台账([]);                                // 不学 → 线守 80%
  造(170_000);                               // 85%,过 75%
  跑("Stop", 项, "sI");
  ck("㉒ 占用过 75% → 照旧催用户 /compact", /建议现在输入 \/compact/.test(末.err), true);

  造台账([台("sJ", "auto", 12), 台("sJ", "auto", 13)]);   // 线学到 51%
  造(110_000);                               // 55%:过线要拦,但没到 75%
  // ⚠️ 变量名只用 ASCII。第一版写的是 `rc㉓` —— **圈号不是合法标识符**
  //    (中文是,圈号不是:它的 Unicode 类别是 No,不在 ID_Start 里),
  //    整个文件直接语法错、一条自测都跑不起来。
  //    上面那些 `变旧` / `造台账` 是合法的,**恰恰是那份合法性让人放松**。
  //    > 同一个坑在 bash 里记过五次(`tools/gate_lock.sh:12`),这次换到 JS,
  //    > 而「JS 允许中文变量名」正好掩护了它。
  const rc23 = 跑("Stop", 项, "sJ");
  ck("㉓ 过线但没到 75% → 照旧拦住", rc23, 2);
  ck("   ↳ 反向:这时**不许**催 /compact(用户 10-28 定的)",
     !/建议现在输入 \/compact/.test(末.err), true);
  ck("   ↳ 而且要说清为什么不催,不是闷着不说",
     /没到 75% 别提/.test(末.err), true);

  // ── ㉔㉕ 「刷过了」≠「覆盖到现在了」(2026-11-04 加)────────────────────
  //
  // 线降下来之后机制是「到线拦一次 → 刷了交接 → 一路放行」。而真实台账说
  // 这个会话被压缩的占用横跨 **26 万到 97 万** —— 22% 时刷一次,然后可能
  // 一路干到 97 万才压缩,中间七十多万 token 的工作一个字进不了交接。
  // 这正是逼出本次改动那件事的放大版(那次是 70 分钟没进交接)。
  //
  // ⚠️ ㉕ 是**反向用例**:涨得不多就不许拦,否则刷完交接立刻又被拦住,
  //    会话原地卡死 —— 而那种闸迟早被整个关掉。
  变旧();
  造台账([台("sK", "auto", 5), 台("sK", "auto", 6)]);   // 线 21%,增量 4.2 万
  造(50_000);                                            // 25% > 21% → 拦
  ck("   (铺垫)过线且交接旧 → 拦", 跑("Stop", 项, "sK"), 2);
  writeFileSync(交件, "fresh-1");                        // 照提示刷了
  ck("   (铺垫)刷了 → 放行,并记下当时的水位", 跑("Stop", 项, "sK"), 0);
  造(60_000);                                            // 只涨 1 万
  ck("㉕ 刷过、占用没涨多少 → 放行(不许刷完立刻又拦)", 跑("Stop", 项, "sK"), 0);
  造(95_000);                                            // 涨 4.5 万 ≥ 增量
  ck("㉔ 刷过、但占用又涨了一条线的量 → 重新拦", 跑("Stop", 项, "sK"), 2);
  ck("   ↳ 这一次拦的计数是重新起算的(不是接着上一轮)",
     /这是第 1 次拦/.test(末.err), true);

  // ── ㉖ 线取**低分位**,不取最低值 ──────────────────────────────────
  //
  // 第一版取 Math.min。真实台账上一看就不对:25 条样本横跨 26 万到 97 万,
  // 一个异常低值就能把线拽到地板上(极端情况按到下限 15%)。
  // 这条用例造 1 个异常低值 + 9 个正常值:
  //   分位数(跳过那个异常值)→ 线 42%,于是 30% 的占用**不该**拦
  //   取最低值           → 线会落到下限 15%,30% 就会被拦
  // **所以它只有在「用分位数」时才是放行的。**
  变旧();
  造台账([台("sL", "auto", 1), ...Array.from({ length: 9 }, () => 台("sL", "auto", 10))]);
  造(60_000);                                            // 30%
  ck("㉖ 一个异常低值不许把线拽到地板(用低分位,不用最低值)",
     跑("Stop", 项, "sL"), 0);

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
      // ⚠️ **连这条消息的时刻一起返回。** 2026-11-03 栽在这儿:
      //    门禁报「29.7 万 / 30%」,而那条消息是 **54 分钟前**那一轮的 ——
      //    那 54 分钟全在等后台任务,涌进来的 user-role 内容(任务通知、
      //    跨会话消息、工具输出)**不产生 assistant 的 usage 记录**,
      //    门禁完全看不见。压缩就在那之后发生。
      //    > 「上一轮请求时的占用」和「现在的占用」,在报数里印成同一个数。
      //    算不准没法根治(涌入量确实无从得知),但**必须让人看见这个数多旧**。
      const 时刻 = Date.parse(d.timestamp || "") || null;
      return { 量: (u.input_tokens || 0) + (u.cache_read_input_tokens || 0)
                 + (u.cache_creation_input_tokens || 0) + (u.output_tokens || 0),
               时刻 };
    }
  } catch { } finally { if (fd !== undefined) try { closeSync(fd); } catch { } }
  return null;
}

// ── 这个项目用不用交接 ────────────────────────────────────────────────
// 判据是「**项目里已经有 HANDOFF.md**」,不是「我觉得该有」。
// 没有的项目(比如只读的顾问会话)只提醒不拦 —— 一道会在正常工作里
// 误拦的闸,迟早会被关掉。
function 找交接() {
  // ⚠️ **走到项目根,不数固定层数。**
  //
  // 2026-09-19 第一版写的是「往上走 4 层」,当天就漏了一次真的:
  // 一个会话的工作目录是
  //   交互设计师工具/capability-evolution/reaudit/repairs/<批次>/<轮次>
  // 而 HANDOFF.md 在**第 5 层**的项目根上。它没找到,于是走了
  // 「这个项目不用交接」那条路 —— **只提醒不拦** ——
  // 结果那个会话一路开到 96% 自动压缩,一句交接都没写。
  //
  // 根因不是层数不够,是**判据用错了东西**:层数是目录的形状,
  // 而「项目到哪儿为止」是仓库的事。git 根就是项目根,不用猜。
  //
  // 更要紧的是失败方式:**「没找到」和「这个项目不需要」原来长得一模一样**,
  // 两者都走「不拦」。现在分成三种状态,见下面的返回值。
  const 家 = homedir();
  let d = cwd, 根 = null;
  for (let i = 0; i < 24; i++) {
    if (existsSync(join(d, ".claude", "no-handoff-gate"))) return { 关掉: true };
    for (const n of ["HANDOFF.md", "HANDOFF.MD", "handoff.md"]) {
      const f = join(d, n);
      if (existsSync(f)) return { 路径: f, mtime: statSync(f).mtimeMs, 根: 根 || d };
    }
    // `.git` 可能是目录(普通仓库)也可能是文件(worktree / submodule),
    // 两种都算根 —— existsSync 不区分,正好。
    if (!根 && existsSync(join(d, ".git"))) 根 = d;
    const 上 = dirname(d);
    if (上 === d || d === 家) break;    // 别走到家目录以外去
    d = 上;
  }
  // 在仓库里却没有交接:**这和「不在仓库里」是两回事**。
  // 但仍然不拦 —— 有些仓库是只读顾问项目(看得见、不该写),
  // 逼它建文件是越界。这里只把话说明白,由人决定建不建。
  return 根 ? { 仓库根: 根 } : {};
}

function 读状态() {
  try { return JSON.parse(readFileSync(join(状态目录, 会话 + ".json"), "utf8")); }
  catch { return { 拦过: 0 }; }
}
function 写状态(s) {
  try { mkdirSync(状态目录, { recursive: true }); writeFileSync(join(状态目录, 会话 + ".json"), JSON.stringify(s)); } catch { }
}

// ── 台账:这台机器实际在什么占用上被压缩过 ────────────────────────
// 台账每行:时刻 \t 会话 \t 触发 \t 报数 \t 状态 \t 路径
function 读台账() {
  try {
    return readFileSync(join(状态目录, "compactions.log"), "utf8")
      .split("\n").filter(Boolean).map(l => l.split("\t"));
  } catch { return []; }
}

// 从台账学那条线。**只看 auto** —— manual 是人主动压的,压在什么占用上
// 由人的心情决定,不代表窗口压力;拿它学线会把线学到荒谬的低位(台账里
// 有一条 manual 发生在 8%)。
function 学阈值(窗) {
  const 本会话 = [], 全局 = [];
  for (const c of 读台账()) {
    if (c[2] !== "auto") continue;
    const m = /上下文 ([\d.]+) 万/.exec(c[3] || "");
    if (!m) continue;
    const n = Number(m[1]) * 10000;
    if (!(n > 0)) continue;
    全局.push(n);
    if (c[1] === 会话) 本会话.push(n);
  }
  // ⚠️ **样本不足就别说话。** 一条记录学不出线,而「学了个不靠谱的线」
  //    比「没学」更糟:它会把闸挪到一个没有依据的位置,而输出上看不出来。
  const 本会话够 = 本会话.length >= 2;
  const 样本 = 本会话够 ? 本会话 : 全局;
  if (样本.length < 2) return null;
  // ⚠️ **用低分位,不用最低值。** 第一版取 Math.min —— 真实台账上一看就不对:
  //    25 条样本横跨 26 万到 97 万,一个异常低值就能把线拽到地板上。
  //    (极端情况:某次压缩因为别的原因发生在 5 万,线就被按到下限。)
  //    分位数只被「下端够密」影响,不被单个异常值左右。
  const 排 = [...样本].sort((a, b) => a - b);
  const 低 = 排[Math.max(0, Math.floor(排.length * 0.1))];
  // 打个折:压在那个分位之前就该拦住,不是压的时候才拦。
  const 线 = Math.max(低 * 0.85 / 窗, 学线下限);
  return { 线, 据: `${本会话够 ? "本会话" : "这台机器"} ${样本.length} 次 auto 压缩,一成分位 ${(低 / 10000).toFixed(1)} 万` };
}

function 上次压缩时刻() {
  // 本会话优先 —— 跨会话的压缩跟这份交接的新鲜度没关系。
  const 本 = 读台账().filter(c => c[1] === 会话);
  for (let i = 本.length - 1; i >= 0; i--) {
    const t = Date.parse(本[i][0] || "");
    if (t) return t;
  }
  return null;
}

// ── 主流程 ────────────────────────────────────────────────────────────
const 占对象 = 已占用();
if (占对象 === null) process.exit(0);       // 读不到就别瞎拦
const 占 = 占对象.量;
const 窗 = 窗口大小(占);
const 学 = 阈值写死了 ? null : 学阈值(窗);
// 取较低者:学到的线高于 80% 时说明这台机器压得很晚,那就守着 80% 更保险。
if (学 && 学.线 < 阈值) { 阈值 = 学.线; 预警 = Math.min(预警, 阈值 * 0.8); }
const 比 = 占 / 窗;
const 万 = n => (n / 10000).toFixed(1) + " 万";
// ⚠️ 这个数可能已经旧了(见 已占用() 里那段)。**旧了就得说**,
//    否则「刚算的 30%」和「54 分钟前的 30%」印出来一模一样。
const 龄 = 占对象.时刻 ? Date.now() - 占对象.时刻 : null;
const 太旧 = 龄 !== null && 龄 > 5 * 60 * 1000;
const 报数 = `上下文 ${万(占)} / ${万(窗)} = ${(比 * 100).toFixed(0)}%`
  + (学 ? `(线 ${(阈值 * 100).toFixed(0)}%,学自${学.据})` : "")
  + (太旧 ? `  ⚠️ 这个数是 ${Math.round(龄 / 60000)} 分钟前那一轮的,之后涌进来的没算在内` : "");
const 交 = 找交接();
const st = 读状态();

if (事件 === "PreCompact") {
  // 压缩真发生了。**这是唯一能确认门禁有没有白干的地方。**
  // ⚠️ **基准不止一个,而且「判不了」要和「过期」分开**(2026-11-04 改)。
  //    原来基准只有 `st.越线于`,它只在过线之后才记 —— 而那条线一次都没到过,
  //    于是基准恒空、新鲜度恒判「过期」。台账里那三条「交接过期」,
  //    说的其实是「没有基准,判不了」。
  //    > 一条真的过期了的交接,和一条根本没法判的交接,
  //    > **在台账里印成同一个词。**
  //    退路:拿**上一次压缩**当基准 —— 交接在那之后刷过没有,这才是要问的。
  const 基准 = st.越线于 || 上次压缩时刻();
  const 新鲜度 = !交.mtime ? "判不了(读不到交接的时间)"
               : !基准 ? "判不了(这个会话还没压过,没有基准)"
               : 交.mtime > 基准 ? "新鲜" : "过期";
  try {
    mkdirSync(状态目录, { recursive: true });
    appendFileSync(join(状态目录, "compactions.log"),
      // **三种状态要在台账里分得开。** 原来「找不到交接」和「这个项目不用交接」
      // 都写成「交接没有」—— 而正是那一行掩盖了 2026-09-19 那次漏拦:
      // 交接明明在项目根上,只是往上走的层数不够。
      `${new Date().toISOString()}\t${会话}\t${inp.trigger || "?"}\t${报数}\t`
      + (交.路径 ? `交接${新鲜度}\t${交.路径}`
         : 交.仓库根 ? `仓库里没有交接\t${交.仓库根}`
         : `不在仓库里\t${cwd}`) + "\n");
  } catch { }
  写状态({ 拦过: 0 });                       // 压缩后重新计一轮
  process.exit(0);
}

if (事件 === "UserPromptSubmit") {
  if (比 >= 预警) {
    // UserPromptSubmit 的 stdout 会作为上下文交给模型(官方明确写了这条)
    if (交.关掉) process.exit(0);
    if (!交.路径) {
      // 在仓库里却没有交接,和根本不在仓库里,**不是一回事**,话要分开说。
      // 仍然不拦:有些仓库是只读的顾问项目(看得见、不该写),逼它建文件是越界。
      console.log(交.仓库根
        ? `[交接门禁] ${报数}。仓库 ${交.仓库根} 里**没有 HANDOFF.md**,所以门禁只提醒不拦。`
          + `这是个会跨多轮的项目,建议现在在仓库根上建一份(跑 handoff-before-compact 技能);`
          + `如果这个项目确实不需要交接,放一个 ${交.仓库根}/.claude/no-handoff-gate 空文件,这条提醒就不再出现。`
        : `[交接门禁] ${报数}。当前目录不在任何 git 仓库里,门禁不介入。`);
    } else {
      // ⚠️ **越线时刻要在这里就记下,不能等到收工。**
      //    2026-09-22 抓到的:下面这句话叫 AI「现在就该刷交接」,它照做了 ——
      //    可越线时刻原来只在 Stop 里才记,于是提前刷的交接比「越线时刻」还早,
      //    收工时照样被判过期、照样被拦。**照提示做了反而过不去,这道闸在惩罚听话。**
      if (比 >= 阈值 && !st.越线于) { st.越线于 = Date.now(); 写状态(st); }
      // ⚠️ **没越线就别说「尚未刷新」**(2026-10-15 抓到的)。
      //    「新鲜」是拿 `交.mtime > st.越线于` 算的,而越线时刻**只在过线之后才记**。
      //    过线之前 `st.越线于` 是空的 —— 没有基准,算不出新鲜度,
      //    而原来那句话照样印「尚未刷新」:**刷了也这么说,不刷也这么说**。
      //    今天实测:70%~80% 之间每一轮都提示「尚未刷新」,
      //    而那几轮里交接刚刷过、刚提交过。
      //    > 一个「真的没刷新」和一个「还没到能判断的时候」,
      //    > **在「尚未刷新」这四个字上长得一模一样。**
      //    同一行里「已过 80% 线」「现在就该刷交接」都是有条件显示的,
      //    唯独这句是无条件的 —— 补上它该有的条件。
      const 可判 = !!st.越线于;
      const 新鲜 = 可判 && 交.mtime > st.越线于;
      console.log(`[交接门禁] ${报数}${比 >= 阈值 ? `,已过 ${阈值 * 100}% 线` : ""}。`
        + (可判
            ? `交接文件 ${交.路径} ${新鲜 ? "本轮已刷新" : "尚未刷新"}。`
            : `交接文件 ${交.路径}(还没过 ${阈值 * 100}% 线,这一轮不判新鲜度)。`)
        + (比 >= 阈值 && !新鲜 ? ` **现在就该刷交接**,不要等收工时被拦。` : ""));
    }
  }
  process.exit(0);
}

if (事件 === "Stop" || 事件 === "SubagentStop") {
  if (事件 === "SubagentStop") process.exit(0);   // 子任务有自己的上下文,不归这儿管
  if (比 < 阈值 || 交.关掉 || !交.路径) process.exit(0);

  if (!st.越线于) { st.越线于 = Date.now(); 写状态(st); }

  // ── 越线之后刷过了 → 放行。**但「刷过了」不等于「覆盖到现在」** ──────
  //
  // ⚠️⚠️ 2026-11-04 补的第二半,而**第一半刚修完我就在这儿照样踩了一次**。
  //    第一半修的是「那条线从没到过」;线降下来之后机制变成
  //    「到线拦一次 → 刷了交接 → 一路放行」。可台账说这个会话实际被压缩的
  //    占用横跨 **26 万到 97 万** —— 也就是 22% 时刷一次,然后可能一路干到
  //    97 万才压缩,中间七十多万 token 的工作**一个字进不了交接**。
  //
  //    > **「刷过了」和「覆盖到现在了」,在 `交.mtime > 越线于` 上长得一模一样。**
  //
  //    这正是逼出这次改动的那件事的放大版(那次是 70 分钟没进交接)。
  //    所以放行要记下**当时的占用**,占用又涨了一条线的量就再拦一次。
  if (交.mtime > st.越线于) {
    const 增量 = 阈值 * 窗;                  // 每涨「一条线的量」就该再刷一次
    if (st.刷于 === undefined) {             // 这是刷完后第一次收工 —— 记下水位,放行
      写状态({ ...st, 刷于: 占 }); process.exit(0);
    }
    if (占 - st.刷于 < 增量) process.exit(0);
    // 涨太多了:把越线时刻挪到现在、清掉拦截计数、忘掉旧水位,于是下面照常拦。
    // ⚠️ 必须清 `拦过` —— 不清的话上一轮拦满 2 次的计数会让这一轮直接放行,
    //    而那正是「涨了一大截却没人要求刷交接」。
    st.越线于 = Date.now(); st.拦过 = 0; delete st.刷于; 写状态(st);
  }

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
  2. 刷完说一句「交接已刷新」。${比 >= 0.75
    ? `\n     占用已过 75%,**再单独写一行**原样告诉用户:「建议现在输入 /compact」。`
    : `\n     **这一轮不要提 /compact**(用户 2026-10-28 定的:没到 75% 别提)——\n`
    + `     自动压缩本来就会来(这台机器实测 30% 占用就压),不需要人手动压;\n`
    + `     这道闸要的是**压缩来之前交接已经在那了**,不是催人去压缩。`}

(这是第 ${st.拦过} 次拦;拦满 ${最多拦几次} 次会放行,但压缩时会把当时的新鲜度记进台账。)`);
  process.exit(2);
}
process.exit(0);
