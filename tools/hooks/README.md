# 提交前门禁的退出码不许被吞掉

## 它拦什么

2026-09-16，同一个错在这个项目里犯了两次：

```bash
./check.sh | tail -2 && git commit -m "..."
```

管道的退出码来自 `tail`（永远是 0），不是 `check.sh`。于是**门禁红着，提交照样成功**。
屏幕上印着 `❌ 3 项失败`，而提交已经落盘了 —— 这是这个项目反复遇到的那类故障：
**两个必须触发相反动作的状态，在表示上一模一样**。「门禁绿了」和「门禁的退出码被换掉了」，
在 `&&` 看来是同一件事。

## 判据贴着含义，不贴着字面

这道闸最容易犯的错，正是它要拦的那个错。

| 判据 | 后果 |
|---|---|
| ❌ 「命令里有没有管道」 | `./check.sh \| tail -2`（只想看结果，没提交）也被拦 → **误拦** → 闸被关掉 |
| ✅ 「门禁的退出码到不到得了 commit」 | 只在同一条命令里既有门禁、又有 commit、且通行证断了时才拦 |

落到 bash 语义上，就是看门禁后面**第一个**控制符：

| 形状 | 退出码 | 判定 |
|---|---|---|
| `门禁 && git commit` | 门禁自己的 | 放行 |
| `门禁 \| tail && git commit` | 来自 `tail` | **拦** |
| `门禁 ; git commit` | 丢了 | **拦** |
| `门禁 \|\| true && git commit` | 被咽下去了 | **拦** |
| `门禁 \|\| exit 1 ; git commit` | 用上了 | 放行 |
| `if 门禁; then git commit; fi` | 用上了（那个 `;` 是语法） | 放行 |
| `set -o pipefail; 门禁 \| tail && git commit` | 管道会传失败 | 放行 |
| `门禁; rc=$?; [ $rc -eq 0 ] && git commit` | 显式接住了 | 放行 |

**宁可漏，不可误**，两处故意不拦：
- 命令里只有 `git commit` 没有门禁 —— 门禁可能在上一次工具调用里跑过了，这道闸无从知道。拦了就是误拦。
- 命令里只有门禁没有 commit —— 看日志是正当的。

它自己出错时也**放行**（fail open）。它防的是手滑，不是攻击者；
一道会误拦的闸迟早被关掉，关掉之后它挡的那些错会一起回来。

## 咬合测试

```bash
node tools/hooks/commit-gate-exitcode.mjs --selftest
```

18 个用例，7 个该拦（含两个真实案发现场）、11 个该放（含 4 个专门防误拦的）。
改完判据必须重跑 —— 一道证明不了它拦得住什么的闸，等于没装。

## 装

拷到 `~/.claude/hooks/`，在 `~/.claude/settings.json` 的 `hooks.PreToolUse` 里加：

```json
{
  "matcher": "Bash",
  "hooks": [{
    "type": "command",
    "command": "/usr/local/bin/node /Users/eureka/.claude/hooks/commit-gate-exitcode.mjs",
    "timeout": 5,
    "statusMessage": "提交前门禁退出码检查"
  }]
}
```

门禁名单在文件顶部的 `GATES`：`check.sh` / `scan_secrets.sh` / `rebuild.sh` / `pytest`。
往里加名字前先想一遍：**这个命令的退出码，是不是真的「该不该提交」的判据**。不是的话别加，加了就是误拦的来源。
