#!/usr/bin/env node
// Claude Code PreToolUse hook：提交前门禁的退出码不许被吞掉。
//
// 起因（2026-09-16，澜绣云裳agent 项目）：我在一条命令里写了两次
//     ./check.sh | tail -2 && git commit -m "..."
// 管道的退出码来自 tail（永远是 0），不是 check.sh。于是门禁红着，commit 照样过。
// 屏幕上还印着 "❌ 3 项失败"，而提交已经落盘了。
//
// ⚠️ 这道闸自己最容易犯的错，就是它要拦的那个错：判据贴着字面而不是含义。
//    「有没有管道」是字面 —— 会把 `./check.sh | tail -2`（只想看结果，没提交）也拦下来。
//    「退出码有没有到达 commit」是含义 —— 这才是要拦的。
//    一道会误拦的闸迟早被人关掉，关掉之后它挡的那些错会一起回来。所以这里宁可漏，不可误。
//
// 判据（贴着 bash 语义）：同一条命令里既出现门禁、又出现 git commit/push 时，
//   看门禁后面**第一个**控制符：
//     &&        → 门禁的成败传下去了            → 放行
//     |         → 退出码被管道末端顶替了        → 拦
//     ; 或换行  → 退出码直接丢了                → 拦
//     ||        → 后面接 exit/return 才算数     → 否则拦
//   例外（这些都是真的把退出码用上了，不能拦）：
//     - 命令里设了 pipefail
//     - 门禁到 commit 之间出现 $?（显式接住了）
//     - 门禁处在 if / while / until / ! 的条件位（那个 ; 是语法，不是丢弃）
//
// 不拦的情况（重要，这是「宁可漏」的落点）：
//   - 命令里只有 git commit，没有门禁 —— 门禁可能在上一次调用里跑过了，这道闸无从知道，拦了就是误拦。
//   - 命令里只有门禁，没有 commit —— 看日志是正当的。
//
// 失败姿态：这道闸自己出错时**放行**（fail open）。它防的是我的手滑，不是攻击者；
//   误拦的代价（闸被关掉）比漏拦一次高。

import fs from "node:fs";
import { fileURLToPath } from "node:url";

// 门禁命令名单。加名字前先想一遍：这个命令的退出码是不是真的「该不该提交」的判据。
const GATES = ["check\\.sh", "scan_secrets\\.sh", "rebuild\\.sh", "pytest", "[\\w-]*_check\\.py"];
// _check.py：这个项目有 48 个单项检查脚本，check.sh 里调了 55 次，开发时常单独跑某一个再提交。
// ⚠️ 白名单必然有漏，漏掉的那个和没装一样。加名字前先问：它的退出码是不是真的「该不该提交」的判据。

// 门禁必须处在「命令位」：行首或控制符之后，可带解释器前缀和路径。
// 这样 `cat check.sh | head -40 && git commit` 里的 check.sh 是 cat 的参数，不算门禁。
const GATE_RE = new RegExp(
  "(?:^|[;&|(\\n])\\s*(?:(?:bash|sh|zsh|python3?)\\s+)?(?:[.~]?[\\w./-]*\\/)?(" + GATES.join("|") + ")\\b",
  "g"
);
const COMMIT_RE = /\bgit\s+(?:-\S+\s+)*(?:commit|push)\b/;
const FIRST_OP_RE = /&&|\|\||\||;|\n/;
const CONDITION_POS_RE = /(?:^|[;&|(\n])\s*(?:if|while|until|!)\s+$/;

// heredoc 的正文是喂给别的程序的数据，bash 不执行它，所以先剥掉再判。
// 不剥的话 `python3 - <<'PY' ... PY` 里出现的门禁名会被当成真的跑了门禁 —— 实测误拦过一次。
// 剥过头只会导致漏（不拦），不会导致误拦；这个方向的错更便宜。
export function stripHeredocs(cmd) {
  return cmd.replace(/<<-?\s*(['\"]?)([A-Za-z_]\w*)\1[\s\S]*?^\s*\2\s*$/gm, "<<HEREDOC");
}

export function verdict(rawCommand) {
  if (typeof rawCommand !== "string" || !rawCommand) return null;
  const command = stripHeredocs(rawCommand);

  const commit = COMMIT_RE.exec(command);
  if (!commit) return null;                       // 没提交动作，不关这道闸的事

  // ⚠️ **commit 之前的每一个门禁都要看,不是只看最近那个。**
  //
  // 2026-09-20 实际漏掉过一次,而且是我自己写的命令:
  //     ./check.sh > log 2>&1; echo "退出码 $?"; ./tools/scan_secrets.sh && git commit ...
  // 最近的门禁是 `scan_secrets.sh && commit` —— 合格,于是放行。
  // 而前面那个被 `;` 断开的 `./check.sh` **根本没被检查**,当时它是红的。
  //
  // > **只要在最后接一个用 `&&` 连的轻量门禁,
  // > 前面所有用 `;` 断开的重门禁都会被漏掉。**
  //
  // 这正是这道闸本来要防的那个形状 —— 它自己栽在了同一个形状上。
  if (/\bpipefail\b/.test(command)) return null;   // 管道会传失败，退出码没丢

  const gates = [];
  GATE_RE.lastIndex = 0;
  for (let m; (m = GATE_RE.exec(command)); ) {
    if (m.index >= commit.index) break;            // commit 之后的(比如写在 message 里的)不算
    gates.push(m);
  }
  if (!gates.length) return null;                  // 这条命令里没跑门禁 —— 无从判断，放行

  for (const gate of gates) {
    const gateEnd = gate.index + gate[0].length;
    const seg = command.slice(gateEnd, commit.index);

    // ⚠️ **「读了退出码」不等于「用退出码把关」。**
    //    原来写的是 `if (/\$\?/.test(seg)) return null;  // 显式接住了退出码`,
    //    而 `echo "退出码 $?"` 也匹配 —— 把它打印出来,然后无视它继续提交。
    //    **这两种写法在字面上长得一模一样,而一个把关一个不把关。**
    //    现在要求 `$?` 真的被**接住或拿去判断**:rc=$? / [ $? -eq 0 ] / if ... $? ...
    if (/(?:^|[^<>])\b\w+=\$\?/.test(seg) || /\[\s*"?\$(?:\?|\{\?\})"?\s*(?:-eq|-ne|==|!=)/.test(seg)) continue;

    // 门禁在 if/while/until 的条件位：紧跟其后的 ; 是语法的一部分，不是丢弃
    if (CONDITION_POS_RE.test(command.slice(0, gate.index + gate[0].length - gate[1].length))) continue;

    const op = FIRST_OP_RE.exec(seg);
    if (!op) continue;                             // 门禁和 commit 之间没有控制符，形状不认识，放行
    if (op[0] === "&&") continue;                  // 通行证正常传递
    if (op[0] === "||" && /\b(?:exit|return)\b/.test(seg)) continue; // `门禁 || exit 1` 是对的

    const 名字 = gate[1].replace(/\\/g, "");
    const 形状 = op[0] === "|" ? `管道（退出码来自管道最后一段，不是 ${名字}）`
               : op[0] === "||" ? `|| 分支（没有 exit，失败被咽下去了）`
               : `${op[0] === "\n" ? "换行" : "分号"}（退出码被直接丢弃）`;
    return { 名字, 形状 };                          // **任何一个门禁被断开,就拦**
  }
  return null;
}

function deny(v) {
  return {
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        `退出码被吞：这条命令用 ${v.名字} 当提交的通行证，但中间是${v.形状}。` +
        `门禁红着也会提交成功。\n` +
        `改成两步：先单独跑门禁、看它自己的退出码，绿了再单独发 commit；` +
        `或者在同一条里写成 \`${v.名字} && git commit ...\`（不要接管道）。` +
        `要留日志就 \`${v.名字} > /tmp/gate.log 2>&1; rc=$?; tail -20 /tmp/gate.log; [ $rc -eq 0 ] && git commit ...\`。`
    }
  };
}

// 「我是不是被直接运行」这个判断，跟「要不要跑自测」其实没关系 —— 只是碰巧常常一致。
// 2026-09-16 它两次把自测整段跳过还退出 0：一次是相对路径调用，一次是 /tmp 软链到 /private/tmp。
// 坏了是绿的，比没有自测更糟。所以自测只认 argv 里的 --selftest，不挂在那个判断下面。
function isMain() {
  try {
    return !!process.argv[1] &&
      fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(process.argv[1]);
  } catch { return false; }
}

if (process.argv.includes("--selftest")) {
  {
    // 咬合测试：一道闸如果我证明不了它拦得住，它就等于没装。
    const 用例 = [
      // [命令, 该不该拦, 说明]
      ["./check.sh | tail -2 && git commit -m x", true, "真实案发现场①"],
      ["cd /p && ./check.sh 2>&1 | tail -2 && git commit -m '收尾'", true, "真实案发现场②带 cd"],
      ["./check.sh > /tmp/o 2>&1; git commit -m x", true, "分号丢退出码"],
      ["./check.sh\ngit commit -m x", true, "换行丢退出码"],
      ["./tools/scan_secrets.sh | grep -c FAIL && git push", true, "扫密钥同样的形状"],
      ["pytest -q | tail -5 && git commit -m x", true, "pytest 同形状"],
      ["./check.sh || true && git commit -m x", true, "|| true 咽掉失败"],

      ["./check.sh && git commit -m x", false, "正确写法"],
      ["./check.sh > /tmp/o 2>&1 && git commit -m x", false, "重定向后 && 仍然正确"],
      ["./check.sh; rc=$?; [ $rc -eq 0 ] && git commit -m x", false, "显式接住退出码"],
      ["if ./check.sh; then git commit -m x; fi", false, "if 条件位的分号是语法"],
      ["set -o pipefail; ./check.sh | tail -2 && git commit -m x", false, "pipefail 让管道传失败"],
      ["./check.sh || exit 1; git commit -m x", false, "|| exit 是对的"],
      ["./check.sh | tail -2", false, "只看日志，没提交 —— 拦了就是误拦"],
      ["git commit -m x", false, "门禁在上一次调用里跑过，无从判断"],
      ["cat check.sh | head -40 && git commit -m x", false, "check.sh 是 cat 的参数，不是门禁"],
      ["python3 backend/stock_check.py | tail -5 && git commit -m x", true, "单项检查脚本，同样的形状"],

      // ── 2026-09-20 真实漏网的那一条,以及它的两个变种 ──────────────
      ['./check.sh > /tmp/g.log 2>&1; echo "退出码 $?"; ./tools/scan_secrets.sh && git commit -m x',
       true, "**真实漏网**:最后接一个 && 连的轻量门禁,前面被 ; 断开的重门禁就被漏掉"],
      ['./check.sh; echo "$?"; git commit -m x',
       true, "把退出码**打印出来**然后无视它 —— 读了不等于用了"],
      ['./check.sh > /tmp/g.log 2>&1; rc=$?; ./tools/scan_secrets.sh && [ $rc -eq 0 ] && git commit -m x',
       false, "接住并拿去判断,这才算把关"],
      ["cat <<'EOF' > /tmp/x\nhello\nEOF\n./check.sh | tail -2 && git commit -m x", true, "heredoc 之后的真命令仍要拦"],
      ["cat backend/stock_check.py | head -20 && git commit -m x", false, "_check.py 是 cat 的参数，别误拦"],
      ["cat <<'PY' > /tmp/t.py\n./check.sh | tail -2 && git commit -m x\nPY", false, "heredoc 里是数据，bash 不执行 —— 真误拦过"],
      ["git log --oneline | head -5; ./check.sh", false, "git log 不是 commit"],
      ["git commit -m '修好 check.sh | tail 吞退出码的毛病'", false, "门禁名出现在 commit message 里"],
    ];
    let 红 = 0;
    for (const [cmd, 该拦, 说明] of 用例) {
      const 实际 = verdict(cmd) !== null;
      const 对 = 实际 === 该拦;
      if (!对) 红++;
      console.log(`${对 ? "✅" : "❌"} ${该拦 ? "该拦" : "该放"} | ${说明}\n     ${JSON.stringify(cmd)}`);
    }
    console.log(`\n${用例.length - 红}/${用例.length} 通过` + (红 ? `  ❌ ${红} 项不符` : "  ✅ 全绿"));
    process.exit(红 ? 1 : 0);
  }
} else if (isMain()) {
  let out = {};
  try {
    const input = JSON.parse(fs.readFileSync(0, "utf8"));
    const v = input?.tool_name === "Bash" ? verdict(input?.tool_input?.command) : null;
    if (v) out = deny(v);
  } catch {
    out = {};   // fail open：这道闸自己坏了就放行，见文件头
  }
  process.stdout.write(`${JSON.stringify(out)}\n`);
}
