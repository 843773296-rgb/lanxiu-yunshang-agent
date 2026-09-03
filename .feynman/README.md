# 本项目的费曼状态目录

**本项目独立于「帕鲁打工仔」(`~/Desktop/chatgpt`)。两者不是一个项目,不共用任何东西。**

| 东西 | 本项目 | 帕鲁打工仔 |
|---|---|---|
| 台账 | `.feynman/ledger.md` | 它自己的,**不要碰** |
| 报告 | `.feynman/report.md` | 它自己的 |
| 发布脚本 | `tools/feishu_publish.py` | 它自己的一份 |
| 飞书凭证 | `~/.feishu-publish/`(两个项目之外) | 它 `tools/` 下自己那份 |
| 飞书文件夹 | `QexpfF7ejlotM8db6JEcZH5tnZf` | `PJWWffc04lhlBJd7uYIcmWYWnde` |

## 为什么要隔离(踩过的坑)

发布脚本按**文件名**清理同名旧版。两个项目都用 `report.md` 这个模板文件名,
于是本项目发第 1 版报告时,**静默删掉了帕鲁打工仔的第 12 版报告**,
只打了一行「已清理 1 份同名旧文档」。

根因不是脚本有 bug,是**用文件名当身份** —— 而文件名不是身份。

## 规矩

1. 发飞书的文件名**必须带项目名**(`澜绣云裳agent-项目解读报告.md`),不用通用名
2. 台账只写本目录,不写 `~/Desktop/chatgpt/.feynman/ledger.md`
3. `~/Desktop/chatgpt/` 一律**只读**:可以读它的代码作参考,不修改任何文件
