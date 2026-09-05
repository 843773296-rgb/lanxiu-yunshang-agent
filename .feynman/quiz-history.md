# 考试记录


## 2026-09-04 · 架构题

**题**:把 `backend/api.py` 那 19 个函数直接搬进 `agentsite/sdk.py`,省掉 MCP 这一层,
系统能不能照跑?会失去什么?

**学员答**:能跑,但会不稳定 —— MCP 是一套完整的接口规范,负责跨系统的信息流转;
没有 MCP 就没有规范,agent 就会不稳定。

**判定:半对。**

- ✅ 「能跑」——对。
- ✅ 「MCP 是规范、负责跨系统信息流转」——对,而且抓到了重点。
- ❌ **「没有 MCP 就没有规范 → agent 不稳定」——因果链不成立。**
  ① 工具的规范来自 **JSON Schema**(每个工具的 `inputSchema`),不来自 MCP 的传输层;
  ② SDK 里「搬进去」的标准做法是 `@tool` + `create_sdk_mcp_server`,
     那是**进程内 MCP**,不是没有 MCP。schema 还在,稳定性不变。
  真正的差别是 **stdio 子进程 vs 进程内**,不是「有 MCP vs 没 MCP」。

**真正失去的四样**:进程隔离(只读保证从结构退化成纪律)· 可挂进 Claude Code ·
通道等价测试失去对象 · 权限没法按服务收。

**薄弱点**:把「协议」和「约束的来源」混为一谈。
建议回炉:MCP 到底管什么、不管什么。

## 2026-09-04 · 找茬题:MCP 管什么

**题**:mcp/protocol.py 这 90 行,七件事里哪些管、哪些不管。

**学员答**:1234567 都管。

**判定:3 对 / 1 半对 / 3 错。**

| # | 事 | 真相 | 学员 |
|---|---|---|---|
| 1 | 报工具清单与参数说明 | ✅ 管(tools/list) | ✅ |
| 2 | 校验参数对不对 | ⚠️ 协议不管,靠 Python 抛 TypeError 兜 | ❌ |
| 3 | 权限(该不该让它调) | ❌ 在 sdk.py 的 allowed_tools | ❌ |
| 4 | 真正查数据库 | ❌ 在 backend/api.py | ❌ |
| 5 | 报错不崩 | ✅ 管(包成 isError) | ✅ |
| 6 | 保证只读 | ❌ MCP 不知道工具是读是写 | ❌ |
| 7 | 让 Claude Code 也能挂 | ✅ 管(标准协议) | ✅ |

**错的三条是同一个错**:把「经过 MCP 的东西」当成「MCP 负责的东西」。
和上一题(以为去掉 MCP 就没规范)是同一个薄弱点的两个面。

**证据**:`grep -c "allowed|permission|readonly|validate" mcp/protocol.py` = **0**;
`grep -c "INSERT|UPDATE|DELETE" backend/api.py` = **0**(只读靠这个,不靠 MCP)。
