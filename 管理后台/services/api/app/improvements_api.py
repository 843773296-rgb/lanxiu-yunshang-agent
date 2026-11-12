# -*- coding: utf-8 -*-
"""改进验证与发布(2026-11-12)。口径照《意见收集与能力持续改进 PRD》(10-24)§4.3 / §5.2 / §7.1 / §7.2。

接在问题单后面:问题单「验证通过 / 发布生效 / 关闭」这三步,以前只看请求体里有没有字(完成证据是一段文字),
现在要**真的对象**在场 —— 这里管两样对象和三条前置条件。

## 改进验证记录(issue_verifications)

挂在一张问题单上:原缺陷案例(文字 + 可选关联意见 / 聊天站那一轮)、预期结果、禁止行为、基线版本、候选版本、
固定数据集版本、判分规则(只存引用)。三组 —— 复现组 / 回归组 / 保留组 —— 各关联**一条同项目里真有的评测**,
**复用 evaluations,不复制一套评分**。「能不能当结论」只在 `evals.能当结论吗` 一处(能力档案也用它)。

「验证通过」的前置条件:三组都关联了、每条评测都能当结论、和这条记录说的对得上(候选 / 基线一致;复现组用的就是
记录上的数据集版本和判分规则;保留组和复现组不是同一份数据集版本)。**不按分数判过没过**(门槛 PRD §10 待定)——
三组证据齐了,才**允许**人点;算不算通过由点的人判,记成审批人。

## 发布记录(issue_releases)

关联一条**真实的发布**:应用发布清单(环境指针 → release_manifests)或聊天助手的某一版(production_version_no)。
写:改了哪些依赖版本、批准人、采用新版本的入口、试点范围、观察指标(可空)、回退版本及触发条件。**没有灰度开关**:
后台不支持按门店 / 用户灰度,不摆(PRD)。

「发布生效」的前置条件 = **实际采用回执**,不是「配置保存成功」(PRD §4.3):
  · 应用发布清单:生产指针现在指着它,而且**切过去之后**生产上有一次用这份清单跑完(succeeded)的运行
    (execution_runs.release_ref / definition_ref 里记着清单 id 和环境 —— 那是运行受理时从指针解析出来、跟着运行走的);
  · 聊天助手版本:生产指针是这一版,而且聊天站报的实际加载和生产那一版逐项一致 —— **判法就是聊天助手页「生效状态」那一套**
    (chat_assistants_api.生效对比),不另写。⚠️ 聊天站只回报术语 / 实体识别 / 路由 / 意图四样的版本,开头 / 结尾 / 工具不回报 ——
    这一半核不了,回执里写着。
取不到 → 不许点,并说清为什么。

回滚 = **新记一行**(指着被回滚的那条),原来那行一个字不改;建的时候核生产指针确实指回去了。
**后台不替人回滚、不自动发布、不改生产配置**(PRD §5.2 末段)—— 真回滚在发布页做,这里只记、只核。

## 暂定 / 没做的(写清楚,别当成做了)

- **权限暂定**:读「查看有权配置」,写「受理意见」—— PRD §10 质量 / 发布负责人分工没拍。
- 通过分数门槛、观察窗口、样本量:PRD §10 待定,一个数都不定。
- 保留组「按会话 / 客户 / 业务事件分组隔离」(PRD §4.3)查不了 —— 只核了「不是复现组那份数据集版本」。
- 评审是演示模型判的(scores.value_known 否)不在「能当结论」里看 —— 那是逐题分数的事。
- 「用户纠正的答案先进待审核样本」「模型改动同题两轮对比报质量 / 异常 / 成本 / 时延」不在这次范围。
"""
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text

from db import 连接, 事务
from deps import 身份, 要权限, _错
import evals as EV
import improvement_flow as F
import issue_flow as IF
from issues_api import _字, _给人看, _json体, _记一步 as _记问题单一步

router = APIRouter()
前缀 = "/api/v1/projects/{project_id}"
长文上限 = 2000
短上限 = 200
说明最长 = 1000

# ── 字段表:请求体里的名字 → 列 ─────────────────────────────────────────
组字段 = {f"{组}评测": 列 for 组, 列, _ in F.验证分组}
验证字段 = {
    "原缺陷案例": "defect_case_note", "关联意见": "opinion_id", "关联trace": "chat_trace_ref",
    "预期结果": "expected_result_note", "禁止行为": "forbidden_behavior_note",
    "基线版本": "baseline_version_ref", "候选版本": "candidate_version_ref",
    "数据集版本": "dataset_version_id", "判分规则": "scorer_version_ref", **组字段,
}
验证必填 = ("原缺陷案例", "预期结果", "禁止行为", "基线版本", "候选版本", "数据集版本", "判分规则")
验证短字段 = ("关联意见", "关联trace", "基线版本", "候选版本", "数据集版本", "判分规则", *组字段)

发布文字字段 = {k: 列 for k, 列 in F.发布必填 + F.发布选填}
发布字段 = {"种类": "target_type", "发布清单": "release_manifest_id", "聊天助手": "chat_assistant_id",
          "聊天助手版本号": "chat_assistant_version_no", **发布文字字段}


def _新id(前):
    return f"{前}_{_uuid.uuid4().hex[:12]}"


def _变化(旧行, 出, 字段表):
    return {中: [_给人看(旧行[列]), _给人看(出[列])] for 中, 列 in 字段表.items() if 列 in 出 and 旧行[列] != 出[列]}


# ── 校验(纯函数,只看请求体给了的键)───────────────────────────────────
def 校验验证字段(体, 新建=False):
    出, 坏 = {}, {}
    for k, 列 in 验证字段.items():
        if k not in 体:
            continue
        v = _字(体, k)
        上 = 短上限 if k in 验证短字段 else 长文上限
        if v and len(v) > 上:
            坏[k] = f"最多 {上} 字"
            continue
        出[列] = v
    for k in 验证必填:
        列 = 验证字段[k]
        if (新建 and not 出.get(列)) or (not 新建 and 列 in 出 and not 出[列]):
            坏[k] = "必填(PRD §4.3:改进任务至少绑定原缺陷案例、预期结果、禁止行为、基线、候选、固定数据集版本、判分规则)"
    给了的组 = [出[列] for 列 in 组字段.values() if 出.get(列)]
    if len(给了的组) != len(set(给了的组)):
        坏["三组评测"] = "三组要各是一条评测 —— 同一条评测当两组用,等于少了一组证据"
    return 出, 坏


def 校验发布字段(体, 新建=False):
    出, 坏 = {}, {}
    for k, 列 in 发布字段.items():
        if k not in 体:
            continue
        if k == "聊天助手版本号":
            v = 体.get(k)
            if v in (None, ""):
                出[列] = None
            elif isinstance(v, bool) or not isinstance(v, int) or v < 0:
                坏[k] = "要是整数(v3 就给 3)"
            else:
                出[列] = v
            continue
        v = _字(体, k)
        if v and len(v) > (短上限 if k in ("种类", "发布清单", "聊天助手", "批准人") else 长文上限):
            坏[k] = "太长"
            continue
        出[列] = v
    if "target_type" in 出 and 出["target_type"] not in F.发布对象种类们:
        坏["种类"] = f"只收 {list(F.发布对象种类们)} —— 后台里有生产指针的就这两种"
    for k, 列 in F.发布必填:
        if (新建 and not 出.get(列)) or (not 新建 and 列 in 出 and not 出[列]):
            坏[k] = "必填(PRD §4.3 发布记录要写清这一样)"
    if 新建 and not 出.get("target_type"):
        坏["种类"] = f"必填,只收 {list(F.发布对象种类们)}"
    灰 = sorted(k for k in 体 if "灰度" in str(k))
    if 灰:
        坏["灰度"] = "后台不支持按门店 / 用户灰度,不收灰度开关(PRD:不支持就不摆)—— 试点范围写在「试点范围」里,手动启用"
    return 出, 坏


# ── 引用核对(同项目里真有)────────────────────────────────────────────
def _问题单(c, project_id, iid, 锁=False):
    x = c.execute(text("select * from issues where project_id=:p and id=:i" + (" for update" if 锁 else "")),
                  {"p": project_id, "i": iid}).mappings().first()
    if not x:
        raise _错(404, "NOT_FOUND", "没有这张问题单", "回清单重新进")
    return x


def _核验证引用(c, project_id, 后):
    """后 = 合并后的整行(列名 → 值)。→ 坏字段。外键也会拒,但那是 500;这里给 422 定位到字段。"""
    坏 = {}
    if 后.get("opinion_id") and not c.execute(text("select count(*) from opinions where project_id=:p and id=:i"),
                                             {"p": project_id, "i": 后["opinion_id"]}).scalar():
        坏["关联意见"] = "这个项目里没有这条意见"
    if 后.get("dataset_version_id") and not c.execute(text("select count(*) from dataset_versions where project_id=:p and id=:i"),
                                                     {"p": project_id, "i": 后["dataset_version_id"]}).scalar():
        坏["数据集版本"] = "这个项目里没有这个数据集版本(要冻结过的那一版的编号)"
    for 组, 列, _ in F.验证分组:
        if 后.get(列) and not c.execute(text("select count(*) from evaluations where project_id=:p and id=:i and archived_at is null"),
                                       {"p": project_id, "i": 后[列]}).scalar():
            坏[f"{组}评测"] = "这个项目里没有这条评测(只能关联同一个项目里真有的评测 —— PRD §7.2)"
    组们 = [后.get(列) for _, 列, _ in F.验证分组 if 后.get(列)]
    if len(组们) != len(set(组们)):
        坏["三组评测"] = "三组要各是一条评测"
    return 坏


def _核发布对象(c, project_id, 后):
    坏 = {}
    种 = 后.get("target_type")
    if 种 == "应用发布清单":
        if not 后.get("release_manifest_id"):
            坏["发布清单"] = "种类是应用发布清单,要给清单编号"
        elif not c.execute(text("select count(*) from release_manifests where project_id=:p and id=:i"),
                           {"p": project_id, "i": 后["release_manifest_id"]}).scalar():
            坏["发布清单"] = "这个项目里没有这份发布清单(只能关联同一个项目里真实的发布 —— PRD §7.2)"
        if 后.get("chat_assistant_id") or 后.get("chat_assistant_version_no") is not None:
            坏["聊天助手"] = "种类是应用发布清单,聊天助手那两项要空着"
    elif 种 == "聊天助手版本":
        if not 后.get("chat_assistant_id") or 后.get("chat_assistant_version_no") is None:
            坏["聊天助手"] = "种类是聊天助手版本,要给聊天助手编号和版本号"
        elif not c.execute(text("""select count(*) from chat_assistant_versions
                                   where project_id=:p and chat_assistant_id=:a and version_no=:n"""),
                           {"p": project_id, "a": 后["chat_assistant_id"], "n": 后["chat_assistant_version_no"]}).scalar():
            坏["聊天助手版本号"] = "这个项目里没有这个聊天助手的这一版(只能关联真实存在的版本)"
        if 后.get("release_manifest_id"):
            坏["发布清单"] = "种类是聊天助手版本,发布清单要空着"
    return 坏


# ── 三组证据(「验证通过」的前置条件;详情页也拿它预演)────────────────────
def 三组证据(c, project_id, v):
    """→ (问题们, 组们)。问题们空 = 允许点「验证通过」。**不看分数**。"""
    问, 组们 = [], []
    评 = {}
    for 组, 列, 证明 in F.验证分组:
        eid = v[列]
        if not eid:
            问.append(f"{组}没关联评测({证明})")
            组们.append({"组": 组, "证明什么": 证明, "评测": None})
            continue
        e = c.execute(text("""select id, status, executor_code, candidate_ref, baseline_ref, dataset_version_id, scorer_version,
                                     ended_at from evaluations where project_id=:p and id=:i"""),
                      {"p": project_id, "i": eid}).mappings().first()
        if not e:
            问.append(f"{组}的评测 {eid} 找不到了")
            组们.append({"组": 组, "证明什么": 证明, "评测": {"id": eid, "找得到": False}})
            continue
        评[组] = e
        能, 为什么 = EV.能当结论吗(e)
        候, 基 = (e["candidate_ref"] or {}).get("ref"), (e["baseline_ref"] or {}).get("ref")
        对不上 = []
        if 候 != v["candidate_version_ref"]:
            对不上.append(f"评测的候选是「{候}」,这条记录的候选版本是「{v['candidate_version_ref']}」")
        if 基 != v["baseline_version_ref"]:
            对不上.append(f"评测的基线是「{基}」,这条记录的基线版本是「{v['baseline_version_ref']}」")
        if 组 == "复现组":
            if e["dataset_version_id"] != v["dataset_version_id"]:
                对不上.append(f"复现组评测用的数据集版本是 {e['dataset_version_id']},记录上固定的是 {v['dataset_version_id']}")
            if e["scorer_version"] != v["scorer_version_ref"]:
                对不上.append(f"复现组评测的判据版本是「{e['scorer_version']}」,记录上的判分规则是「{v['scorer_version_ref']}」")
        问 += [f"{组}:{x}" for x in 为什么 + 对不上]
        组们.append({"组": 组, "证明什么": 证明, "评测": {
            "id": e["id"], "找得到": True, "状态": e["status"], "执行方式": e["executor_code"],
            "候选": 候, "基线": 基, "数据集版本": e["dataset_version_id"], "判据版本": e["scorer_version"],
            "结束于": _给人看(e["ended_at"]), "能当结论吗": 能, "为什么不能": 为什么, "和记录对不上的": 对不上}})
    if "复现组" in 评 and "保留组" in 评 and 评["复现组"]["dataset_version_id"] == 评["保留组"]["dataset_version_id"]:
        问.append("保留组和复现组用的是同一份数据集版本 —— 保留组要是没见过的题(PRD §4.3「避免只针对见过的题调优」)")
    return 问, 组们


# ── 实际采用回执(「发布生效」的前置条件)──────────────────────────────
def 实际采用(c, project_id, r, me):
    """→ {确认了, 为什么, 回执}。**配置切过去 ≠ 用上了**:要从新版本真跑出来的东西确认。"""
    if r["target_type"] == "应用发布清单":
        rid = r["release_manifest_id"]
        m = c.execute(text("select id, application_id from release_manifests where project_id=:p and id=:i"),
                      {"p": project_id, "i": rid}).mappings().first()
        if not m:
            return {"确认了": False, "为什么": f"发布清单 {rid} 找不到了", "回执": None}
        指 = c.execute(text("""select release_manifest_id from environment_bindings
                                where project_id=:p and application_id=:a and environment='production'"""),
                       {"p": project_id, "a": m["application_id"]}).scalar()
        if 指 != rid:
            return {"确认了": False, "回执": None,
                    "为什么": (f"生产指针现在指着 {指 or '(没有)'},不是这份清单 {rid} —— 先在发布页把它审核、发到生产;"
                            "后台不替人发布")}
        切 = c.execute(text("""select max(at) from audit_events
                                where project_id=:p and action in ('release.deploy', 'release.rollback') and result='ok'
                                  and target_ref->>'environment' = 'production'
                                  and coalesce(target_ref->>'release_id', target_ref->>'到') = :r"""),
                       {"p": project_id, "r": rid}).scalar()
        if not 切:
            return {"确认了": False, "回执": None,
                    "为什么": "找不到把生产切到这份清单的发布记录(审计里的 release.deploy / release.rollback)—— 说不清从什么时候起算"}
        run = c.execute(text("""select id, kind, status, execution_mode, created_at, ended_at from execution_runs
                                 where project_id=:p and status='succeeded' and created_at >= :t
                                   and ((release_ref->>'id' = :r and environment = 'production')
                                     or (definition_ref->>'清单id' = :r and definition_ref->>'环境' = 'production'))
                                 order by created_at, id limit 1"""),
                       {"p": project_id, "r": rid, "t": 切}).mappings().first()
        if not run:
            return {"确认了": False, "回执": None,
                    "为什么": (f"生产切到这份清单({_给人看(切)})之后,还没有一次用它跑完(succeeded)的运行 —— "
                            "指针切过去不等于用上了;等新版本在生产上真跑完一次再点")}
        return {"确认了": True, "为什么": "生产指针指着这份清单,切过去之后有一次用它跑完的运行",
                "回执": {"依据": "生产运行回执", "清单": rid, "生产切换于": _给人看(切), "运行": run["id"],
                        "运行种类": run["kind"], "执行模式": run["execution_mode"],
                        "受理于": _给人看(run["created_at"]), "跑完于": _给人看(run["ended_at"])}}
    # 聊天助手版本:判法照聊天助手页「生效状态」(生效对比),不另写
    import chat_assistants_api as CA
    a = c.execute(text("select id, role_key, production_version_no from chat_assistants where project_id=:p and id=:i"),
                  {"p": project_id, "i": r["chat_assistant_id"]}).mappings().first()
    号 = r["chat_assistant_version_no"]
    if not a:
        return {"确认了": False, "为什么": "这个聊天助手找不到了", "回执": None}
    if a["production_version_no"] != 号:
        return {"确认了": False, "回执": None,
                "为什么": f"聊天助手的生产现在是 v{a['production_version_no']},不是 v{号} —— 先在聊天助手页审核上生产;后台不替人发布"}
    if a["role_key"] not in CA.聊天站读的角色:
        return {"确认了": False, "回执": None,
                "为什么": "聊天站不读这个角色的后台配置(上了生产线上也不变)—— 取不到实际采用,不能算生效"}
    try:
        pv = CA.生产版本(project_id, a["role_key"], me)
    except Exception as e:
        return {"确认了": False, "回执": None, "为什么": f"读不到生产那一版:{getattr(e, 'detail', e)}"}
    实际 = CA._问聊天站加载了什么()
    行 = CA.生效对比(pv, 实际)
    if not all(x["状态"] == "一致" for x in 行):
        摘 = ";".join(f"{x['项']}:{x['状态']}" + (f"({x['说明']})" if x.get("说明") else "") for x in 行)
        return {"确认了": False, "回执": None,
                "为什么": f"聊天站报的实际加载和生产 v{号} 对不上 —— {摘}。拿不到 / 没加载不等于一致"}
    return {"确认了": True, "为什么": f"生产是 v{号},聊天站报的实际加载逐项一致",
            "回执": {"依据": "聊天站实际加载回执(/internal/loaded,判法同聊天助手页「生效状态」)", "生产版本": f"v{号}",
                    "逐项": 行, "聊天站进程启动于": (实际 or {}).get("进程启动于") if isinstance(实际, dict) else None,
                    "查询于": (实际 or {}).get("查询于") if isinstance(实际, dict) else None,
                    "盲区": "聊天站只回报术语 / 实体识别 / 路由 / 意图四样的版本;开头 / 结尾 / 工具不回报,这一半核不了"}}


# ── 问题单那三步的前置条件(issues_api 在流转里调)────────────────────────
def _本轮事件(c, project_id, iid):
    """最近一次进「处理中」之后的时间线(那之前的验证 / 发布属于上一轮,复发过就不算数了)。"""
    线 = c.execute(text("""select action_code, to_status, change_snapshot from issue_events
                            where project_id=:p and issue_id=:i order by created_at, id"""),
                   {"p": project_id, "i": iid}).mappings().all()
    起 = max((k for k, e in enumerate(线) if e["to_status"] == "处理中" and e["action_code"] not in IF.不是流转的事件), default=-1)
    return 线[起 + 1:]


def _锁记录(c, 表, project_id, 编号, iid, 字段名):
    r = c.execute(text(f"select * from {表} where project_id=:p and id=:i for update"),
                  {"p": project_id, "i": 编号}).mappings().first()
    if not r or r["issue_id"] != iid:
        raise _错(422, "VALIDATION", f"这张问题单上没有这条{字段名}", f"给这张单上的{字段名}编号(问题单详情里列着)",
                  field_errors={字段名: "不是这张单的 / 不存在"})
    return r


def _被回滚了(c, project_id, rid):
    return c.execute(text("select id from issue_releases where project_id=:p and rollback_of_id=:r limit 1"),
                     {"p": project_id, "r": rid}).scalar()


def 前置检查(c, project_id, x, 动作, 体, me, 说明):
    """问题单走 `动作` 之前,查别的对象满不满足(issue_flow.前置条件 那张表),顺手把记录标成通过 / 失败 / 生效。
    → 要记进这一步时间线「变化」里的东西(dict);不满足就抛 409。和问题单那一步在同一个事务里 —— 问题单没走成,记录也不动。"""
    iid = x["id"]
    if 动作 == "验证通过":
        v = _锁记录(c, "issue_verifications", project_id, _字(体, "验证记录"), iid, "验证记录")
        if v["status"] != "待验证":
            raise _错(409, "VERIFICATION_CONCLUDED", f"这条验证记录已经是「{v['status']}」了",
                      "一条记录只下一次结论;这一轮要重新验证就新建一条(失败的那条留着)")
        问, 组们 = 三组证据(c, project_id, v)
        if 问:
            raise _错(409, "VERIFICATION_EVIDENCE_INCOMPLETE", f"三组证据还不齐({len(问)} 处)",
                      "三组(复现 / 回归 / 保留)都要关联评测,每条都要能当结论、和这条记录对得上;**不按分数判**,齐了由人判",
                      field_errors={"验证记录": 问})
        c.execute(text("""update issue_verifications set status='通过', approver_ref=:u, concluded_at=now(), conclusion_note=:n,
                              revision=revision+1, updated_at=now() where project_id=:p and id=:i"""),
                  {"u": me.user_id, "n": 说明, "p": project_id, "i": v["id"]})
        return {"验证记录": v["id"], "三组评测": {g["组"]: (g["评测"] or {}).get("id") for g in 组们}}
    if 动作 == "验证失败" and _字(体, "验证记录"):
        v = _锁记录(c, "issue_verifications", project_id, _字(体, "验证记录"), iid, "验证记录")
        if v["status"] != "待验证":
            raise _错(409, "VERIFICATION_CONCLUDED", f"这条验证记录已经是「{v['status']}」了", "不带验证记录也能记验证失败")
        c.execute(text("""update issue_verifications set status='未通过', approver_ref=:u, concluded_at=now(), conclusion_note=:n,
                              revision=revision+1, updated_at=now() where project_id=:p and id=:i"""),
                  {"u": me.user_id, "n": 说明, "p": project_id, "i": v["id"]})
        return {"验证记录": v["id"], "结论": "未通过(失败的实验留着)"}
    if 动作 == "发布生效":
        r = _锁记录(c, "issue_releases", project_id, _字(体, "发布记录"), iid, "发布记录")
        if r["event_code"] != "发布" or r["status"] != "待生效":
            raise _错(409, "RELEASE_NOT_PENDING", f"这条发布记录是「{r['event_code']} · {r['status']}」,不是待生效的发布",
                      "记过失败 / 已生效的不能再用;新建一条发布记录")
        采 = 实际采用(c, project_id, r, me)
        if not 采["确认了"]:
            raise _错(409, "ADOPTION_NOT_CONFIRMED", "还确认不了新版本已经实际用上: " + 采["为什么"],
                      "PRD §4.3:配置保存成功 / 部署命令返回成功都不算;要从新版本的实际运行回执确认",
                      field_errors={"发布记录": 采["为什么"]})
        c.execute(text("""update issue_releases set status='已生效', effective_at=now(), adoption_snapshot=cast(:s as jsonb),
                              revision=revision+1, updated_at=now() where project_id=:p and id=:i"""),
                  {"s": _json.dumps(采["回执"], ensure_ascii=False, default=str), "p": project_id, "i": r["id"]})
        return {"发布记录": r["id"], "实际采用回执": 采["回执"]}
    if 动作 == "发布失败" and _字(体, "发布记录"):
        r = _锁记录(c, "issue_releases", project_id, _字(体, "发布记录"), iid, "发布记录")
        if r["event_code"] != "发布" or r["status"] != "待生效":
            raise _错(409, "RELEASE_NOT_PENDING", f"这条发布记录是「{r['event_code']} · {r['status']}」", "不带发布记录也能记发布失败")
        c.execute(text("""update issue_releases set status='发布失败', failure_note=:n, revision=revision+1, updated_at=now()
                           where project_id=:p and id=:i"""), {"n": 说明, "p": project_id, "i": r["id"]})
        return {"发布记录": r["id"], "结论": "发布失败(记录留着)"}
    if 动作 == "关闭":
        本轮 = _本轮事件(c, project_id, iid)
        取 = lambda a, k: next(((e["change_snapshot"] or {}).get(k) for e in reversed(本轮) if e["action_code"] == a), None)
        vid, rid = 取("验证通过", "验证记录"), 取("发布生效", "发布记录")
        问 = []
        if not vid:
            问.append("这一轮的「验证通过」没有绑验证记录(可能是验证记录上线之前点的)")
        if not rid:
            问.append("这一轮的「发布生效」没有绑发布记录(可能是发布记录上线之前点的)")
        v = vid and c.execute(text("select status from issue_verifications where project_id=:p and id=:i"),
                              {"p": project_id, "i": vid}).scalar()
        r = rid and c.execute(text("select status from issue_releases where project_id=:p and id=:i"),
                              {"p": project_id, "i": rid}).scalar()
        if vid and v != "通过":
            问.append(f"验证记录 {vid} 现在是「{v}」,不是通过")
        if rid and r != "已生效":
            问.append(f"发布记录 {rid} 现在是「{r}」,不是已生效")
        回 = rid and _被回滚了(c, project_id, rid)
        if 回:
            问.append(f"发布记录 {rid} 已经被回滚(回滚记录 {回})—— 修复版本现在没在生产上")
        if 问:
            raise _错(409, "CLOSE_EVIDENCE_MISSING", "关不了:这一轮的验证记录 / 发布记录不齐",
                      "关闭要这一轮验证通过 + 发布已生效且没回滚(PRD §5.2「修复版本已实际生效、原案例与必要回归通过」);"
                      "旧单没绑记录的,走「观察期复发」回处理中,建验证记录 / 发布记录重走一遍",
                      field_errors={"完成证据": 问})
        return {"验证记录": vid, "发布记录": rid}
    return {}


# 启动时核对:issue_flow.前置条件 里每一步这里都有实现(那张表是给人看的,实现在上面)—— 少一条就当场炸,不静默放行
_有实现的 = {"验证通过", "发布生效", "关闭"}
assert set(IF.前置条件) == _有实现的, f"issue_flow.前置条件 和 improvements_api 的实现对不上:{set(IF.前置条件) ^ _有实现的}"


# ── 给问题单详情用:这张单上的验证记录 / 发布记录(摘要)──────────────────
def 问题单的记录(c, project_id, iid):
    vs = c.execute(text("""select id, status, candidate_version_ref, baseline_version_ref, created_at, concluded_at,
                                  repro_evaluation_id, regression_evaluation_id, holdout_evaluation_id
                             from issue_verifications where project_id=:p and issue_id=:i order by created_at, id"""),
                   {"p": project_id, "i": iid}).mappings().all()
    rs = c.execute(text("""select id, event_code, status, target_type, release_manifest_id, chat_assistant_id,
                                  chat_assistant_version_no, rollback_of_id, created_at, effective_at
                             from issue_releases where project_id=:p and issue_id=:i order by created_at, id"""),
                   {"p": project_id, "i": iid}).mappings().all()
    回滚了 = {r["rollback_of_id"]: r["id"] for r in rs if r["rollback_of_id"]}
    return ([{"id": v["id"], "状态": v["status"], "候选版本": v["candidate_version_ref"], "基线版本": v["baseline_version_ref"],
              "三组关联了几组": sum(1 for _, 列, _ in F.验证分组 if v[列]), "建于": _给人看(v["created_at"]),
              "结论于": _给人看(v["concluded_at"])} for v in vs],
            [{"id": r["id"], "事件": r["event_code"], "状态": r["status"], "种类": r["target_type"],
              "关联的发布": _发布对象名(r), "回滚的是": r["rollback_of_id"], "被回滚": 回滚了.get(r["id"]),
              "建于": _给人看(r["created_at"]), "生效于": _给人看(r["effective_at"])} for r in rs])


def _发布对象名(r):
    return (r["release_manifest_id"] if r["target_type"] == "应用发布清单"
            else f"{r['chat_assistant_id']} v{r['chat_assistant_version_no']}")


def _锁一条(c, 表, project_id, 编号, if_match, 叫):
    if not if_match:
        raise _错(409, "IF_MATCH_REQUIRED", "要带 If-Match", f"把这条{叫}详情里的 revision 放进 If-Match 头")
    r = c.execute(text(f"select * from {表} where project_id=:p and id=:i for update"),
                  {"p": project_id, "i": 编号}).mappings().first()
    if not r:
        raise _错(404, "NOT_FOUND", f"没有这条{叫}", "回问题单详情重新进")
    if str(r["revision"]) != str(if_match).strip('"'):
        raise _错(409, "REVISION_CONFLICT", f"这条{叫}刚被别人改过", "刷新看一眼最新的再改")
    return r


def _问题单还能动(x):
    if x["status"] in IF.不许改字段的状态:
        raise _错(409, "TRANSITION_NOT_ALLOWED", f"「{x['status']}」的问题单不能再挂 / 改验证记录和发布记录",
                  "已关闭的要先「关闭后复发」重开;重复单去主问题上做")


def _碰一下问题单(c, project_id, iid):
    # 不动 revision:验证 / 发布记录各有自己的 revision;问题单详情页拿着的那个 revision 不该因为挂了条记录就作废
    c.execute(text("update issues set updated_at=now() where project_id=:p and id=:i"), {"p": project_id, "i": iid})


def _插(c, 表, 行):
    列 = list(行)
    值 = ", ".join(f"cast(:{k} as jsonb)" if k == "adoption_snapshot" else f":{k}" for k in 列)
    c.execute(text(f"insert into {表} ({', '.join(列)}, created_at, updated_at) values ({值}, now(), now())"), 行)


# ══ 改进验证记录 ══════════════════════════════════════════════════════
@router.post(前缀 + "/issues/{issue_id}/verifications", status_code=201)
async def 建验证记录(project_id: str, issue_id: str, request: Request, me: 身份 = Depends(要权限("受理意见"))):
    """`{原缺陷案例, 关联意见?, 关联trace?, 预期结果, 禁止行为, 基线版本, 候选版本, 数据集版本, 判分规则,
    复现组评测?, 回归组评测?, 保留组评测?, 说明?}`。新记录在「待验证」;三组评测可以后补(评测可能还在跑)。
    ⚠️ 写权限**暂用「受理意见」**(PRD §10 质量负责人分工没拍)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验验证字段(体, 新建=True)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "验证记录的字段不合格", "见字段错误", field_errors=坏)
    vid = _新id("iv")
    with 事务() as c:
        x = _问题单(c, project_id, issue_id, 锁=True)
        _问题单还能动(x)
        坏 = _核验证引用(c, project_id, 出)
        if 坏:
            raise _错(422, "VALIDATION", "验证记录引用了这个项目里没有的东西", "只能关联同一个项目里真有的意见 / 数据集版本 / 评测",
                      field_errors=坏)
        _插(c, "issue_verifications", {"id": vid, "organization_id": x["organization_id"], "project_id": project_id,
                                        "created_by": me.user_id, "revision": 1, "issue_id": issue_id, "status": "待验证",
                                        **出})
        _碰一下问题单(c, project_id, issue_id)
        _记问题单一步(c, x["organization_id"], project_id, me, issue_id, "建验证记录", x["status"], x["status"], 说明,
                    {"验证记录": vid})
    return {"id": vid, "状态": "待验证", "revision": 1,
            "note": "建好了。三组评测都关联上、都能当结论之后,在问题单上点「验证通过」(带这条记录的编号)"}


@router.get(前缀 + "/issue-verifications")
def 验证记录清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            issue: str = Query(None), limit: int = Query(30, ge=1, le=200), page: int = Query(1, ge=1)):
    """按问题单筛;最近建的在前。"""
    条件, 参 = "v.project_id=:p", {"p": project_id, "lim": limit, "off": (page - 1) * limit}
    if issue:
        条件 += " and v.issue_id=:iss"; 参["iss"] = issue
    with 连接() as c:
        rs = c.execute(text(f"""select count(*) over () 全量, v.*, i.title from issue_verifications v
                                  join issues i on i.project_id=v.project_id and i.id=v.issue_id
                                 where {条件} order by v.created_at desc, v.id desc limit :lim offset :off"""), 参).mappings().all()
    from workflows_api import 分页信封
    return {"items": [{"id": v["id"], "问题单": v["issue_id"], "问题单标题": v["title"], "状态": v["status"],
                       "候选版本": v["candidate_version_ref"], "基线版本": v["baseline_version_ref"],
                       "三组关联了几组": sum(1 for _, 列, _ in F.验证分组 if v[列]),
                       "建于": _给人看(v["created_at"]), "revision": v["revision"]} for v in rs],
            **分页信封(rs, page, limit), "note": "是不是算通过由人在问题单上点「验证通过」;这里不按分数判"}


@router.get(前缀 + "/issue-verifications/{vid}")
def 验证记录详情(project_id: str, vid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一条验证记录 + 三组评测现查(状态、能不能当结论、和记录对不对得上)+ 现在能不能点「验证通过」(预演,不改任何东西)。"""
    with 连接() as c:
        v = c.execute(text("select * from issue_verifications where project_id=:p and id=:i"),
                      {"p": project_id, "i": vid}).mappings().first()
        if not v:
            raise _错(404, "NOT_FOUND", "没有这条验证记录", "回问题单详情重新进")
        x = c.execute(text("select id, title, status from issues where project_id=:p and id=:i"),
                      {"p": project_id, "i": v["issue_id"]}).mappings().first()
        问, 组们 = 三组证据(c, project_id, v)
        题数 = c.execute(text("""select case when jsonb_typeof(frozen_samples) = 'array' then jsonb_array_length(frozen_samples) end
                                  from dataset_versions where project_id=:p and id=:i"""),
                        {"p": project_id, "i": v["dataset_version_id"]}).scalar()
        意见 = (c.execute(text("select id, status, verdict, note, issue_id from opinions where project_id=:p and id=:i"),
                         {"p": project_id, "i": v["opinion_id"]}).mappings().first() if v["opinion_id"] else None)
    return {"id": v["id"], "问题单": {"id": x["id"], "标题": x["title"], "状态": x["status"]}, "状态": v["status"],
            "原缺陷案例": v["defect_case_note"], "关联trace": v["chat_trace_ref"],
            "关联意见": ({"id": 意见["id"], "状态": 意见["status"], "评价": 意见["verdict"], "说明": 意见["note"],
                       "挂在哪张问题单": 意见["issue_id"]} if 意见 else None),
            "预期结果": v["expected_result_note"], "禁止行为": v["forbidden_behavior_note"],
            "基线版本": v["baseline_version_ref"], "候选版本": v["candidate_version_ref"],
            "数据集版本": {"id": v["dataset_version_id"], "题数": 题数}, "判分规则": v["scorer_version_ref"],
            "三组": 组们, "能点验证通过吗": v["status"] == "待验证" and not 问,
            "还差什么": 问 if v["status"] == "待验证" else [],
            "结论说明": v["conclusion_note"], "审批人": v["approver_ref"], "结论于": _给人看(v["concluded_at"]),
            "能改": v["status"] == "待验证" and x["status"] not in IF.不许改字段的状态,
            "建于": _给人看(v["created_at"]), "最近更新": _给人看(v["updated_at"]), "revision": v["revision"],
            "note": ("三组评测是现查的;**不按分数判过没过**(门槛 PRD §10 待定)—— 三组都能当结论才允许点通过,算不算通过由人判;"
                     "写权限暂用「受理意见」")}


@router.patch(前缀 + "/issue-verifications/{vid}")
async def 改验证记录(project_id: str, vid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("受理意见"))):
    """只改给了的键(补三组评测多半走这里),带 If-Match;只有「待验证」的能改。每次在问题单时间线记一行「改验证记录」带前后值。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验验证字段(体)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if not 出 and not 坏:
        坏["字段"] = f"一个能改的字段都没给 —— 能改的:{list(验证字段)}"
    if 坏:
        raise _错(422, "VALIDATION", "验证记录的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        v = _锁一条(c, "issue_verifications", project_id, vid, if_match, "验证记录")
        x = _问题单(c, project_id, v["issue_id"])
        _问题单还能动(x)
        if v["status"] != "待验证":
            raise _错(409, "VERIFICATION_CONCLUDED", f"这条验证记录已经是「{v['status']}」了,不能再改",
                      "下了结论的实验原样留着;要重新验证就新建一条")
        变化 = _变化(v, 出, 验证字段)
        if not 变化:
            raise _错(422, "VALIDATION", "给的值和现在一样,没有要改的", "改了再保存", field_errors={"字段": "没有变化"})
        坏 = _核验证引用(c, project_id, {**dict(v), **出})
        if 坏:
            raise _错(422, "VALIDATION", "验证记录引用了这个项目里没有的东西", "只能关联同一个项目里真有的意见 / 数据集版本 / 评测",
                      field_errors=坏)
        设 = ", ".join(f"{列}=:c_{列}" for 列 in 出)
        r = c.execute(text(f"""update issue_verifications set {设}, revision=revision+1, updated_at=now()
                                where project_id=:p and id=:i returning revision"""),
                      {"p": project_id, "i": vid, **{"c_" + k: val for k, val in 出.items()}}).mappings().first()
        _碰一下问题单(c, project_id, v["issue_id"])
        _记问题单一步(c, x["organization_id"], project_id, me, v["issue_id"], "改验证记录", x["status"], x["status"], 说明,
                    {"验证记录": vid, **变化})
    return {"id": vid, "revision": r["revision"], "改了": list(变化)}


# ══ 改进发布记录 ══════════════════════════════════════════════════════
@router.post(前缀 + "/issues/{issue_id}/releases", status_code=201)
async def 建发布记录(project_id: str, issue_id: str, request: Request, me: 身份 = Depends(要权限("受理意见"))):
    """`{种类: 应用发布清单 | 聊天助手版本, 发布清单? | 聊天助手? + 聊天助手版本号?, 改了哪些依赖版本, 批准人, 采用新版本的入口,
    试点范围, 观察指标?, 回退版本, 回退触发条件, 说明?}`。新记录在「待生效」—— **只记,不发布**:真发布在发布页 / 聊天助手页做。
    ⚠️ 写权限**暂用「受理意见」**(PRD §10 发布负责人分工没拍)。没有灰度开关(后台不支持,不摆)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验发布字段(体, 新建=True)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "发布记录的字段不合格", "见字段错误", field_errors=坏)
    rid = _新id("ir")
    with 事务() as c:
        x = _问题单(c, project_id, issue_id, 锁=True)
        _问题单还能动(x)
        坏 = _核发布对象(c, project_id, 出)
        if 坏:
            raise _错(422, "VALIDATION", "关联的发布不对", "只能关联同一个项目里真实存在的发布清单 / 聊天助手版本", field_errors=坏)
        _插(c, "issue_releases", {"id": rid, "organization_id": x["organization_id"], "project_id": project_id,
                                   "created_by": me.user_id, "revision": 1, "issue_id": issue_id, "event_code": "发布",
                                   "status": "待生效", **出})
        _碰一下问题单(c, project_id, issue_id)
        _记问题单一步(c, x["organization_id"], project_id, me, issue_id, "建发布记录", x["status"], x["status"], 说明,
                    {"发布记录": rid, "关联的发布": {"种类": 出["target_type"],
                                               "编号": 出.get("release_manifest_id") or 出.get("chat_assistant_id"),
                                               "版本号": 出.get("chat_assistant_version_no")}})
    return {"id": rid, "状态": "待生效", "revision": 1,
            "note": "记好了(没发布任何东西)。在发布页真发到生产、新版本真跑起来之后,在问题单上点「发布生效」(带这条记录的编号)"}


def _发布对象现查(c, project_id, r):
    """关联的那个真实发布现在什么样 —— 改了哪些依赖(清单里钉的那几项 / 聊天助手那一版挂的几样)、审核人、生产指针。"""
    if r["target_type"] == "应用发布清单":
        import release as RL
        m = c.execute(text("select * from release_manifests where project_id=:p and id=:i"),
                      {"p": project_id, "i": r["release_manifest_id"]}).mappings().first()
        if not m:
            return {"找得到": False}
        审 = m["approval"]
        if isinstance(审, str):
            try:
                审 = _json.loads(审)
            except ValueError:
                审 = None
        a = c.execute(text("select name from applications where project_id=:p and id=:i"),
                      {"p": project_id, "i": m["application_id"]}).scalar()
        指 = c.execute(text("""select release_manifest_id from environment_bindings
                                where project_id=:p and application_id=:a and environment='production'"""),
                       {"p": project_id, "a": m["application_id"]}).scalar()
        return {"找得到": True, "应用": {"id": m["application_id"], "名字": a},
                "清单钉的版本": {名: m[键] for 键, 名 in RL.依赖项 if m.get(键)},
                "清单审核": ({"审核人": (审 or {}).get("审核人"), "结论": (审 or {}).get("结论")} if 审 else None),
                "生产现在指着": 指, "生产指着它吗": 指 == m["id"]}
    a = c.execute(text("select id, name, role_key, production_version_no from chat_assistants where project_id=:p and id=:i"),
                  {"p": project_id, "i": r["chat_assistant_id"]}).mappings().first()
    vv = c.execute(text("""select version_no, model_name, glossary_version_id, entity_version_id, route_version_id, intent_version_id,
                                  content_hash, change_note from chat_assistant_versions
                            where project_id=:p and chat_assistant_id=:a and version_no=:n"""),
                   {"p": project_id, "a": r["chat_assistant_id"], "n": r["chat_assistant_version_no"]}).mappings().first()
    if not a or not vv:
        return {"找得到": False}
    return {"找得到": True, "聊天助手": {"id": a["id"], "名字": a["name"], "角色键": a["role_key"]},
            "这一版挂的": {"模型": vv["model_name"], "术语版本": vv["glossary_version_id"], "实体识别版本": vv["entity_version_id"],
                       "路由版本": vv["route_version_id"], "意图版本": vv["intent_version_id"], "内容哈希": vv["content_hash"]},
            "这一版的变更说明": vv["change_note"],
            "生产现在是": (f"v{a['production_version_no']}" if a["production_version_no"] is not None else None),
            "生产是它吗": a["production_version_no"] == r["chat_assistant_version_no"]}


@router.get(前缀 + "/issue-releases")
def 发布记录清单(project_id: str, me: 身份 = Depends(要权限("查看有权配置")),
            issue: str = Query(None), limit: int = Query(30, ge=1, le=200), page: int = Query(1, ge=1)):
    条件, 参 = "r.project_id=:p", {"p": project_id, "lim": limit, "off": (page - 1) * limit}
    if issue:
        条件 += " and r.issue_id=:iss"; 参["iss"] = issue
    with 连接() as c:
        rs = c.execute(text(f"""select count(*) over () 全量, r.*, i.title from issue_releases r
                                  join issues i on i.project_id=r.project_id and i.id=r.issue_id
                                 where {条件} order by r.created_at desc, r.id desc limit :lim offset :off"""), 参).mappings().all()
    from workflows_api import 分页信封
    return {"items": [{"id": r["id"], "问题单": r["issue_id"], "问题单标题": r["title"], "事件": r["event_code"],
                       "状态": r["status"], "种类": r["target_type"], "关联的发布": _发布对象名(r),
                       "回滚的是": r["rollback_of_id"], "建于": _给人看(r["created_at"]), "revision": r["revision"]} for r in rs],
            **分页信封(rs, page, limit), "note": "回滚是新的一行(回滚的是 → 指着被回滚的那条),原来那行不改"}


@router.get(前缀 + "/issue-releases/{rid}")
def 发布记录详情(project_id: str, rid: str, me: 身份 = Depends(要权限("查看有权配置"))):
    """一条发布记录 + 关联的发布现在什么样 + 实际采用(待生效的现查一次,已生效的给当时记下的回执)+ 回滚关系。"""
    with 连接() as c:
        r = c.execute(text("select * from issue_releases where project_id=:p and id=:i"),
                      {"p": project_id, "i": rid}).mappings().first()
        if not r:
            raise _错(404, "NOT_FOUND", "没有这条发布记录", "回问题单详情重新进")
        x = c.execute(text("select id, title, status from issues where project_id=:p and id=:i"),
                      {"p": project_id, "i": r["issue_id"]}).mappings().first()
        对象 = _发布对象现查(c, project_id, r)
        现查 = 实际采用(c, project_id, r, me) if (r["event_code"] == "发布" and r["status"] == "待生效") else None
        回 = _被回滚了(c, project_id, rid)
    return {"id": r["id"], "问题单": {"id": x["id"], "标题": x["title"], "状态": x["status"]},
            "事件": r["event_code"], "状态": r["status"], "种类": r["target_type"],
            "发布清单": r["release_manifest_id"], "聊天助手": r["chat_assistant_id"], "聊天助手版本号": r["chat_assistant_version_no"],
            "关联的发布现在": 对象,
            **{k: r[列] for k, 列 in F.发布必填 + F.发布选填},
            "实际采用": ({"现查": True, **现查} if 现查 else
                       {"现查": False, "确认了": r["status"] in ("已生效", "已回滚"), "回执": r["adoption_snapshot"],
                        "说明": "这是当时记下的回执(发布生效 / 记回滚那一刻),不是现查的"}),
            "生效于": _给人看(r["effective_at"]), "失败说明": r["failure_note"],
            "回滚的是": r["rollback_of_id"], "被回滚": 回,
            "能改": r["event_code"] == "发布" and r["status"] == "待生效" and x["status"] not in IF.不许改字段的状态,
            "能记回滚": r["event_code"] == "发布" and r["status"] == "已生效" and not 回,
            "可选种类": list(F.发布对象种类们),
            "建于": _给人看(r["created_at"]), "最近更新": _给人看(r["updated_at"]), "revision": r["revision"],
            "note": ("**只记、只核,不发布、不回滚、不改生产配置**(PRD §5.2 末段)—— 真发布 / 真回滚在发布页做;"
                     "没有灰度开关(后台不支持按门店 / 用户灰度);写权限暂用「受理意见」")}


@router.patch(前缀 + "/issue-releases/{rid}")
async def 改发布记录(project_id: str, rid: str, request: Request,
                if_match: str = Header(default=None, alias="If-Match"),
                me: 身份 = Depends(要权限("受理意见"))):
    """只改给了的键,带 If-Match;只有「待生效」的发布能改。每次在问题单时间线记一行「改发布记录」带前后值。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    出, 坏 = 校验发布字段(体)
    说明 = _字(体, "说明")
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if not 出 and not 坏:
        坏["字段"] = f"一个能改的字段都没给 —— 能改的:{list(发布字段)}"
    if 坏:
        raise _错(422, "VALIDATION", "发布记录的字段不合格", "见字段错误", field_errors=坏)
    with 事务() as c:
        r = _锁一条(c, "issue_releases", project_id, rid, if_match, "发布记录")
        x = _问题单(c, project_id, r["issue_id"])
        _问题单还能动(x)
        if r["event_code"] != "发布" or r["status"] != "待生效":
            raise _错(409, "RELEASE_NOT_PENDING", f"这条是「{r['event_code']} · {r['status']}」,不能再改", "记录原样留着;要改就新建一条")
        变化 = _变化(r, 出, 发布字段)
        if not 变化:
            raise _错(422, "VALIDATION", "给的值和现在一样,没有要改的", "改了再保存", field_errors={"字段": "没有变化"})
        # 换种类要把另一种的那几项清空(给空串)—— 核对按合并后的整行来,两种的字段都填着会被拒(库 CHECK 也拦)
        坏 = _核发布对象(c, project_id, {**dict(r), **出})
        if 坏:
            raise _错(422, "VALIDATION", "关联的发布不对", "只能关联同一个项目里真实存在的发布清单 / 聊天助手版本", field_errors=坏)
        设 = ", ".join(f"{列}=:c_{列}" for 列 in 出)
        n = c.execute(text(f"""update issue_releases set {设}, revision=revision+1, updated_at=now()
                                where project_id=:p and id=:i returning revision"""),
                      {"p": project_id, "i": rid, **{"c_" + k: val for k, val in 出.items()}}).mappings().first()
        _碰一下问题单(c, project_id, r["issue_id"])
        _记问题单一步(c, x["organization_id"], project_id, me, r["issue_id"], "改发布记录", x["status"], x["status"], 说明,
                    {"发布记录": rid, **变化})
    return {"id": rid, "revision": n["revision"], "改了": list(变化)}


@router.post(前缀 + "/issue-releases/{rid}/rollbacks", status_code=201)
async def 记回滚(project_id: str, rid: str, request: Request,
              if_match: str = Header(default=None, alias="If-Match"),
              me: 身份 = Depends(要权限("受理意见"))):
    """`{回到: 发布清单编号(应用发布清单)| 版本号(聊天助手版本), 触发原因, 说明?}`,If-Match 带**被回滚的那条**发布记录的 revision。
    **新记一行**(事件 = 回滚,指着被回滚的那条),原来那行内容一个字不改(只 revision +1,防两个人各记一次)。
    ⚠️ **这里不回滚任何东西**:先在发布页 / 聊天助手页真回滚,这里核生产指针确实指回去了才记;没指回去 → 409。
    已创建的任务、报告等业务写入不会跟着撤销(PRD §4.3)。"""
    体 = await _json体(request)
    if 体 is None:
        raise _错(422, "VALIDATION", "请求体要是 JSON 对象", "见接口说明")
    因, 说明 = _字(体, "触发原因"), _字(体, "说明")
    坏 = {}
    if not 因:
        坏["触发原因"] = "必填 —— 为什么回滚(对照发布记录上写的回退触发条件)"
    elif len(因) > 长文上限:
        坏["触发原因"] = f"最多 {长文上限} 字"
    if 体.get("回到") in (None, ""):
        坏["回到"] = "必填:回到哪一份清单(编号)/ 聊天助手的哪一版(版本号)"
    if 说明 and len(说明) > 说明最长:
        坏["说明"] = f"最多 {说明最长} 字"
    if 坏:
        raise _错(422, "VALIDATION", "回滚记录缺东西", "见字段错误", field_errors=坏)
    nid = _新id("ir")
    with 事务() as c:
        r = _锁一条(c, "issue_releases", project_id, rid, if_match, "发布记录")
        x = _问题单(c, project_id, r["issue_id"])
        if r["event_code"] != "发布" or r["status"] != "已生效":
            raise _错(409, "NOT_ROLLBACKABLE", f"这条是「{r['event_code']} · {r['status']}」—— 只有已生效的发布能记回滚", "")
        已 = _被回滚了(c, project_id, rid)
        if 已:
            raise _错(409, "ALREADY_ROLLED_BACK", f"这条发布已经记过回滚({已})", "回滚之后再发布要新建一条发布记录")
        到 = 体.get("回到")
        行 = {"id": nid, "organization_id": x["organization_id"], "project_id": project_id, "created_by": me.user_id,
              "revision": 1, "issue_id": r["issue_id"], "event_code": "回滚", "rollback_of_id": rid, "status": "已回滚",
              "target_type": r["target_type"], "rollback_trigger_note": 因}
        if r["target_type"] == "应用发布清单":
            到 = str(到).strip()
            m = c.execute(text("select application_id from release_manifests where project_id=:p and id=:i"),
                          {"p": project_id, "i": 到}).scalar()
            原应用 = c.execute(text("select application_id from release_manifests where project_id=:p and id=:i"),
                             {"p": project_id, "i": r["release_manifest_id"]}).scalar()
            if not m or m != 原应用:
                raise _错(422, "VALIDATION", "回到的那份清单不是这个应用的(或者不存在)", "给同一个应用的历史清单编号",
                          field_errors={"回到": "不是同一个应用的清单"})
            指 = c.execute(text("""select release_manifest_id from environment_bindings
                                    where project_id=:p and application_id=:a and environment='production'"""),
                           {"p": project_id, "a": m}).scalar()
            if 指 != 到:
                raise _错(409, "ROLLBACK_NOT_DONE", f"生产指针现在指着 {指 or '(没有)'},不是 {到} —— 回滚还没真做",
                          "先在发布页把生产回滚到那一份(后台不替人回滚),再来记")
            行["release_manifest_id"] = 到
            回执 = {"依据": "生产指针", "生产现在指着": 到}
        else:
            if isinstance(到, bool) or not isinstance(到, int):
                raise _错(422, "VALIDATION", "聊天助手回到哪一版要给整数版本号", "v3 就给 3", field_errors={"回到": "要整数"})
            if not c.execute(text("""select count(*) from chat_assistant_versions
                                     where project_id=:p and chat_assistant_id=:a and version_no=:n"""),
                             {"p": project_id, "a": r["chat_assistant_id"], "n": 到}).scalar():
                raise _错(422, "VALIDATION", f"这个聊天助手没有 v{到}", "回聊天助手页看版本列表", field_errors={"回到": "没有这一版"})
            产 = c.execute(text("select production_version_no from chat_assistants where project_id=:p and id=:i"),
                          {"p": project_id, "i": r["chat_assistant_id"]}).scalar()
            if 产 != 到:
                raise _错(409, "ROLLBACK_NOT_DONE", f"聊天助手的生产现在是 v{产},不是 v{到} —— 回滚还没真做",
                          "先在聊天助手页把生产切回那一版(后台不替人回滚),再来记")
            行.update(chat_assistant_id=r["chat_assistant_id"], chat_assistant_version_no=到)
            回执 = {"依据": "生产指针", "生产现在是": f"v{到}"}
        行["adoption_snapshot"] = _json.dumps({**回执, "说明": "回滚只核了生产指针指回去了;已创建的任务 / 报告等业务写入不会跟着撤销"},
                                         ensure_ascii=False)
        _插(c, "issue_releases", 行)
        c.execute(text("update issue_releases set revision=revision+1, updated_at=now() where project_id=:p and id=:i"),
                  {"p": project_id, "i": rid})
        _碰一下问题单(c, project_id, r["issue_id"])
        _记问题单一步(c, x["organization_id"], project_id, me, r["issue_id"], "记回滚", x["status"], x["status"], 说明 or 因,
                    {"回滚记录": nid, "回滚的是": rid, "回到": 到})
    return {"id": nid, "回滚的是": rid, "状态": "已回滚",
            "note": "记好了:新的一行,原来那条发布记录内容没动。问题单要不要回处理中(观察期复发)由人决定 —— 后台不自动改状态"}
