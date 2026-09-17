#!/usr/bin/env node
// Claude Code PostToolUse hook：push 完了,把 CI 的结果推到眼前。
//
// 起因(2026-09-17,澜绣云裳agent):GitHub Actions 的 check 工作流
// **连续 30 次全红,一次都没绿过**,而我一路在说「门禁全绿」—— 说的都是本地。
// 根因是 CI 的建库那步手抄了配方(只跑 seed.py),而配方早已是 5 步。
//
// **「我跑过了」和「它在别处也跑得起来」是两件事,在开发机上长得一模一样。**
// 本地那份库早就有那两张表,没人会删了重建;CI 每次都从零建,所以只有它看得见。
//
// ⚠️ 这个缺口不是「不知道怎么修」,是**那 30 次红到不了我眼前**。
//    机器补得住的正是后者。所以这里做的是「把结果送过来」,不是「教怎么修」。
//
// ## 什么时候出声(其余时候一个字都不打)
//
//   · 这条命令里真的有 git push,而且看起来成功了
//   · 这个仓库真的配了 CI(.github/workflows/ 下有东西)
//   · 本机有 gh 而且登录着
//
// 少一条就闭嘴。**没有 CI 的仓库(小说、异常场景与验收助手)从不出声** ——
// 一个在不相干的地方反复说话的提醒,迟早被人关掉,关掉之后它要提醒的那件事一起没了。
//
// ## 报什么
//
//   最近几次全绿 → 一行,附一条等本次结果的命令(闭环,但不啰嗦)
//   最近有红的   → 报警:红了几次、最后一次绿是什么时候、怎么在本地从零复现
//
// 失败姿态:自己出错一律闭嘴(fail silent)。它是个提醒,不是闸;
// 提醒坏了最多是回到今天之前的样子,而一个会乱报的提醒比没有更糟。
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const GH_TIMEOUT_MS = 12000;
const LOOK_BACK = 8;               // 往回看几次运行

// heredoc 正文里的字不是要执行的命令 —— 这段判据和提交闸那道 hook 是同一件事,
// 所以**直接复用它,不在这里抄一份**。本文件讲的就是「同一件事别有两处写法」,
// 它自己抄一份会很难看,而且两份迟早漂。
async function 剥heredoc(cmd) {
  try {
    const m = await import("./commit-gate-exitcode.mjs");
    return typeof m.stripHeredocs === "function" ? m.stripHeredocs(cmd) : cmd;
  } catch { return cmd; }          // 那个 hook 不在或坏了,就按原样判,大不了多说一句
}

const PUSH = /\bgit\s+(?:-\S+\s+)*push\b/;
// push 失败时 git 会说这些。看不到这些就当成功 —— `git push -q` 成功时一个字都不打。
const 失败迹象 = /(?:^|\n)\s*(?:fatal:|error:|!\s*\[rejected\]|Permission denied|Authentication failed|无法|失败)/i;
// 这次什么都没推上去,也就不会有新的 CI 运行
const 没东西可推 = /Everything up-to-date|一切都是最新的/i;

function 仓库根(start) {
  let d = start;
  for (let i = 0; i < 40 && d && d !== path.dirname(d); i++) {
    if (fs.existsSync(path.join(d, ".git"))) return d;
    d = path.dirname(d);
  }
  return null;
}

function 有CI(root) {
  const dir = path.join(root, ".github", "workflows");
  try {
    return fs.statSync(dir).isDirectory() &&
           fs.readdirSync(dir).some((f) => /\.ya?ml$/i.test(f));
  } catch { return false; }
}

function 取运行(root) {
  const out = execFileSync(
    "gh", ["run", "list", "--limit", String(LOOK_BACK),
           "--json", "conclusion,status,createdAt,displayTitle,headSha,workflowName"],
    { cwd: root, timeout: GH_TIMEOUT_MS, encoding: "utf8",
      env: { ...process.env, GH_PAGER: "cat", NO_COLOR: "1" }, stdio: ["ignore", "pipe", "ignore"] });
  return JSON.parse(out);
}

// 本地从零复现的办法。写在报警里,而不是做成一份要人记得去加载的文档 ——
// 它只在这一刻有用。
function 怎么从零复现(root) {
  const 名 = path.basename(root);
  return [
    "本地从零复现(不碰工作区,gitignored 的产物不会跟着克隆走,所以这一份才是「从零」):",
    `    git clone ~/…/${名} /tmp/cisim && cd /tmp/cisim`,
    "    <照 .github/workflows/*.yml 里那几步装依赖、建数据>",
    "    <跑本仓的门禁脚本>,看它自己的退出码",
    "⚠️ 依赖要按 CI 的装法装(或软链现成的),否则**环境问题会和真问题混在一张报告里**。",
  ].join("\n");
}

export function 该不该出声(cmd, 输出) {
  if (!PUSH.test(cmd || "")) return { 出声: false, 因为: "命令里没有 git push" };
  const t = String(输出 || "");
  if (失败迹象.test(t)) return { 出声: false, 因为: "push 自己就失败了,CI 不会跑" };
  if (没东西可推.test(t)) return { 出声: false, 因为: "没东西可推,不会有新运行" };
  return { 出声: true };
}

export function 写报告(runs, root) {
  if (!runs || !runs.length) return null;
  const 完成 = runs.filter((r) => r.status === "completed");
  if (!完成.length) return null;
  const 红 = 完成.filter((r) => r.conclusion !== "success");
  const 最近一次绿 = 完成.find((r) => r.conclusion === "success");
  const 看结果 = "看本次结果:`gh run watch $(gh run list --limit 1 --json databaseId " +
                 "-q '.[0].databaseId') --exit-status`";

  // ⚠️ **报的是「现在是红是绿」,不是「历史上红过几次」。**
  // 第一版这里数的是回看窗口里的失败次数,于是刚把 CI 修绿的那一刻,
  // 它照样打「🔴 CI 是红的」,而同一段话里写着「当前连红 0 次」—— 自相矛盾。
  // 那是**误报**,而一个会误报的提醒迟早被关掉,关掉之后它要提醒的事一起没了。
  // 判据要贴着含义:最新一次完成的运行是什么结论,现在就是什么状态。
  if (完成[0].conclusion === "success") {
    const 尾巴 = 红.length
      ? `(最近 ${完成.length} 次里红过 ${红.length} 次,最新这次已经绿了)`
      : `(最近 ${完成.length} 次都是绿的)`;
    return `ℹ️ CI:上一次是**绿**的 ${尾巴}。${看结果}`;
  }

  const 连红 = 完成.findIndex((r) => r.conclusion === "success");
  const 连红数 = 连红 === -1 ? `至少 ${完成.length}` : String(连红);
  return [
    `🔴 **CI 现在是红的** —— 连红 ${连红数} 次(最近 ${完成.length} 次里红了 ${红.length} 次)。`,
    最近一次绿
      ? `   最近一次绿:${最近一次绿.createdAt.slice(0, 16)}(${最近一次绿.headSha.slice(0, 7)})`
      : `   **这 ${完成.length} 次里一次都没绿过。**`,
    `   最新一次:${完成[0].workflowName} · ${完成[0].conclusion} · ${String(完成[0].displayTitle).slice(0, 40)}`,
    "",
    "⚠️ **本地绿不等于 CI 绿。** 本地留着历次跑出来的产物,CI 每次从零 ——",
    "   两者只有在「从零建得起来」这件事上会分岔,而在开发机上它们长得一模一样。",
    "",
    "看日志:`gh run view <id> --log-failed`",
    怎么从零复现(root),
  ].join("\n");
}

if (process.argv.includes("--selftest")) {
  const 用例 = [
    ["git push", "", true, "最朴素的一次"],
    ["git add x && git commit -m y && git push -q", "", true, "串在一起也算"],
    ["git status", "", false, "没有 push"],
    ["git push", "fatal: Authentication failed", false, "push 自己失败了"],
    ["git push", "! [rejected] main -> main", false, "被拒了"],
    ["git push", "Everything up-to-date", false, "没东西可推"],
    ["git log --oneline | head", "", false, "只是看日志"],
  ];
  let 红 = 0;
  for (const [cmd, out, 该, 说明] of 用例) {
    const 实 = 该不该出声(cmd, out).出声;
    const 对 = 实 === 该;
    if (!对) 红++;
    console.log(`${对 ? "✅" : "❌"} 该${该 ? "出声" : "闭嘴"} | ${说明}  ${JSON.stringify(cmd)} ${out ? "→ " + JSON.stringify(out) : ""}`);
  }
  // 报告渲染:全绿一行,有红要报警,而且「一次都没绿过」这句必须打得出来
  const 全绿 = 写报告([{ status: "completed", conclusion: "success", createdAt: "2026-09-17T13:00", headSha: "abcdef1", displayTitle: "x", workflowName: "check" }], "/tmp/repo");
  const 有红 = 写报告([
    { status: "completed", conclusion: "failure", createdAt: "2026-09-17T13:00", headSha: "abcdef1", displayTitle: "x", workflowName: "check" },
    { status: "completed", conclusion: "failure", createdAt: "2026-09-17T12:00", headSha: "abcdef2", displayTitle: "y", workflowName: "check" },
  ], "/tmp/repo");
  // ⚠️ 这一条是第一版漏掉的状态:**之前红、最新一次绿**。
  // 漏掉它的后果不是少测一个分支,是那个分支**一直在误报**而自测全绿。
  const 刚修好 = 写报告([
    { status: "completed", conclusion: "success", createdAt: "2026-09-17T13:18", headSha: "5fdb085", displayTitle: "修 CI", workflowName: "check" },
    { status: "completed", conclusion: "failure", createdAt: "2026-09-17T13:06", headSha: "921a4f7", displayTitle: "x", workflowName: "check" },
    { status: "completed", conclusion: "failure", createdAt: "2026-09-17T12:00", headSha: "5d636f7", displayTitle: "y", workflowName: "check" },
  ], "/tmp/repo");
  const 断言 = [
    [!/🔴/.test(刚修好 || ""), "刚修好(最新一次绿、之前红)不许报警 —— 这是误报,第一版栽在这里"],
    [/上一次是\*\*绿\*\*的/.test(刚修好 || ""), "刚修好要说清上一次是绿的"],
    [/红过 2 次/.test(刚修好 || ""), "刚修好要把之前红过几次带上,不然看不出它刚恢复"],
    [/最近 1 次都是绿的/.test(全绿 || "") && /上一次是\*\*绿\*\*的/.test(全绿 || ""), "全绿时只报一行好消息"],
    [!/🔴/.test(全绿 || ""), "全绿时不许出现红色报警"],
    [/🔴/.test(有红 || ""), "有红时要报警"],
    [/一次都没绿过/.test(有红 || ""), "一次都没绿过这句要打得出来 —— 那正是这次踩的坑"],
    // ⚠️ 这条是补的:连红次数原来没有任何断言盖到,改坏它自测照样全绿。
    // 是「一处变异没咬住」把它暴露出来的 —— 没咬住不一定是变异写错了,
    // 也可能是**那个值根本没被测过**。
    [/连红 至少 2 次/.test(有红 || ""), "连红次数要算对(全红时是「至少 N」)"],
    [/从零复现/.test(有红 || ""), "报警里要带本地从零复现的办法"],
    [写报告([], "/tmp/repo") === null, "没有运行记录时闭嘴,不瞎报"],
    [写报告([{ status: "in_progress", conclusion: null }], "/tmp/repo") === null, "只有在跑的运行时闭嘴"],
  ];
  for (const [ok, 名] of 断言) { if (!ok) 红++; console.log(`${ok ? "✅" : "❌"} ${名}`); }
  console.log(`\n${用例.length + 断言.length - 红}/${用例.length + 断言.length} 通过` + (红 ? `  ❌ ${红} 项不符` : "  ✅ 全绿"));
  process.exit(红 ? 1 : 0);
}

if (process.argv[1] && !process.argv.includes("--selftest")) {
  let out = {};
  try {
    const input = JSON.parse(fs.readFileSync(0, "utf8"));
    if (input?.tool_name === "Bash") {
      const cmd = await 剥heredoc(String(input?.tool_input?.command || ""));
      const 回应 = typeof input?.tool_response === "string"
        ? input.tool_response : JSON.stringify(input?.tool_response ?? "");
      if (该不该出声(cmd, 回应).出声) {
        const root = 仓库根(input?.cwd || process.cwd());
        if (root && 有CI(root)) {
          const msg = 写报告(取运行(root), root);
          if (msg) out = { hookSpecificOutput: { hookEventName: "PostToolUse", additionalContext: msg } };
        }
      }
    }
  } catch { out = {}; }   // 自己坏了就闭嘴,见文件头
  process.stdout.write(`${JSON.stringify(out)}\n`);
}
