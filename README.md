# 澜绣云裳 · 门店客户运营管理后台 + 人工任务智能体

一个完整可跑的仿真项目:38 个页面的管理后台、15 个状态机的流转引擎、
一个替人做「退款失败定因」和「客户合并判断」的智能体,以及它的正向/负向评测集。

无第三方依赖,只用 Python 标准库。

## 跑起来

```bash
python3 backend/seed.py      # 重建模拟库(固定种子,结果可复现)
python3 backend/server.py    # 启动,http://127.0.0.1:8760
./check.sh                   # 五项检查,任一失败即整体失败
```

三个页面:

| 地址 | 是什么 |
|---|---|
| `/` | 管理后台本体,38 个页面 |
| `/agent` | **智能体工作台** —— 选一道待处理任务现场跑,看轨迹、看草稿、对答案 |
| `/acceptance` | **验收台** —— 91 条异常场景逐条打到状态机引擎上的结果 |

## 目录

```
backend/
  server.py     单文件 HTTP 服务(标准库),所有页面和接口
  api.py        智能体的工具层 —— 5 个只读接口,0 个写接口
  fsm.py        状态流转引擎,15 个状态机;非法流转一律拒绝并说明理由
  rules.py      写入校验(重复手机号、预约提前量、附件、批量导入)
  seed.py       模拟库生成,固定种子
  selftest.py   验证 truth 表不通过任何接口暴露
  ui_audit.py   控件审计:每个控件必须「能用 / 显式禁用 / 删掉」三选一
  web/          三个页面
agent/
  v1.py         V1 纯 API 循环,自己写 while(tool_use)
  eval.py       正向评测集(20 道)+ 判分器
  negative.py   负向评测集(8 道)—— 考「不该做的事有没有不做」
  offline_test.py  不花 token 的循环机制自测
data/
  answer-set-lanxiu/  状态机定义 + 91 条异常场景(由分析工具产出,见下)
  lanxiu/prd-v15.json PRD
```

## 智能体现在的成绩

模型 `claude-haiku-4-5`(小模型是独立额度池,不和本机 Claude Code 抢)。

| | 题数 | 命中 | 成本 |
|---|---:|---:|---:|
| 正向(查根因) | 20 | 18 = 90% | $0.2348 |
| 负向(不该做的别做) | 8 | 5 = 63% | $0.0958 |

```bash
ANTHROPIC_MODEL=claude-haiku-4-5 python3 agent/eval.py 12 8   # 跑正向
ANTHROPIC_MODEL=claude-haiku-4-5 python3 agent/negative.py    # 跑负向
python3 agent/eval.py rescore                                  # 只重判,不重跑模型
```

细节见 `本期交付说明.md` 第 11、12 章。

## 和「异常场景与验收助手」的关系

那是**另一个项目**(默认在 `../异常场景与验收助手`),是把 PRD 和 Figma 里的状态机
机械推导成异常场景清单的分析工具。两者的边界:

- 它**产出**答案集(91 条异常场景)→ 本项目 `data/answer-set-lanxiu/` 是消费副本
- 它**验收**本项目的状态机引擎 → 结果写回本项目 `data/acceptance-lanxiu.json`
- `/acceptance` 页面上的「重跑」按钮会去调它;找不到时会明确报错,而不是静默失败
  (位置可用环境变量 `ACCEPTANCE_TOOL` 指定)

```bash
# 在分析工具那边重跑验收并重新出页面
cd ../异常场景与验收助手
TARGET=../澜绣云裳agent python3 tools/acceptance.py
TARGET=../澜绣云裳agent python3 tools/build_demo.py
```
