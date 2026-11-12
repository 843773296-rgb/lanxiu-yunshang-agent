# -*- coding: utf-8 -*-
"""造「改进验证与发布」那一套证据的夹具(2026-11-12)—— 问题单 / 能力档案 / 改进验证三份端到端测试共用。

问题单「验证通过 / 发布生效 / 关闭」从 11-12 起要真的对象在场(意见收集 PRD §4.3):
  · 验证通过:一条验证记录,三组(复现 / 回归 / 保留)各关联一条**能当结论**的评测;
  · 发布生效:一条发布记录,关联的应用发布清单**生产指针指着它**,切过去之后有一次**跑完的生产运行**;
  · 关闭:这一轮上面两样都在。

评测 / 清单 / 指针 / 审计 / 运行直接写库(后台派发评测要 worker + 模型、发生产要审核 + 探测 + 真模型跑通 ——
端到端不调模型);**验证记录 / 发布记录走接口**(那是被测的东西)。
所有夹具行的 id 都以调用方给的「标」开头,`清掉()` 照前缀删。
"""
import json

from sqlalchemy import text


def 造评测与数据(cc, org, 项目, 标, 后缀, 候选="候选v2", 基线="基线v1", 判据="s1", 状态="已完成"):
    """→ (复现评测, 回归评测, 保留评测, 复现数据集版本)。复现组和保留组用两份不同的冻结数据集版本。"""
    dv1, dv2 = f"{标}-dv1-{后缀}", f"{标}-dv2-{后缀}"
    for dv, n in ((dv1, 3), (dv2, 2)):
        cc.execute(text("""insert into dataset_versions (id, organization_id, project_id, frozen_samples, created_at)
                           values (:i, :o, :p, cast(:fs as jsonb), now())"""),
                   {"i": dv, "o": org, "p": 项目, "fs": json.dumps([{"q": k} for k in range(n)])})
    评们 = []
    for 组, dv in (("re", dv1), ("rg", dv1), ("ho", dv2)):
        eid = f"{标}-ev{组}-{后缀}"
        cc.execute(text("""insert into evaluations (id, organization_id, project_id, candidate_ref, baseline_ref,
                               dataset_version_id, scorer_version, status, executor_code, created_at, updated_at, revision)
                           values (:i, :o, :p, cast(:c as jsonb), cast(:b as jsonb), :dv, :sc, :st, '外部登记', now(), now(), 1)"""),
                   {"i": eid, "o": org, "p": 项目, "dv": dv, "sc": 判据, "st": 状态,
                    "c": json.dumps({"ref": 候选}), "b": json.dumps({"ref": 基线})})
        评们.append(eid)
    return 评们[0], 评们[1], 评们[2], dv1


def 验证记录体(复现, 回归, 保留, dv, 候选="候选v2", 基线="基线v1", 判据="s1"):
    return {"原缺陷案例": "问加急能不能赶上婚期,答成了按当前负载能赶上", "预期结果": "按工序性质说明不能靠加钱赶",
            "禁止行为": "不许承诺具体交期", "基线版本": 基线, "候选版本": 候选, "数据集版本": dv, "判分规则": 判据,
            "复现组评测": 复现, "回归组评测": 回归, "保留组评测": 保留}


def 造生产发布(cc, org, 项目, 标, 后缀, 跑完=True):
    """→ 清单 id。应用 + 清单 + 生产指针指着它 + 一行 release.deploy 审计;跑完=True 再加一次切过去之后跑完的生产运行。"""
    app, rm, envb, aud, run = (f"{标}-{s}-{后缀}" for s in ("app", "rm", "envb", "aud", "run"))
    cc.execute(text("insert into applications (id, organization_id, project_id, name, created_at) values (:i, :o, :p, :n, now())"),
               {"i": app, "o": org, "p": 项目, "n": f"{标} 应用 {后缀}"})
    cc.execute(text("""insert into release_manifests (id, organization_id, project_id, application_id, content_hash, created_at)
                       values (:i, :o, :p, :a, :h, now())"""), {"i": rm, "o": org, "p": 项目, "a": app, "h": rm})
    cc.execute(text("""insert into environment_bindings (id, organization_id, project_id, application_id, environment,
                           release_manifest_id, created_at, updated_at, revision)
                       values (:i, :o, :p, :a, 'production', :r, now(), now(), 1)"""),
               {"i": envb, "o": org, "p": 项目, "a": app, "r": rm})
    cc.execute(text("""insert into audit_events (id, organization_id, project_id, actor, action, target_ref, environment, at,
                           result, created_at, created_by)
                       values (:i, :o, :p, 'e2e', 'release.deploy', cast(:t as jsonb), 'development',
                               now() - interval '1 minute', 'ok', now(), 'e2e')"""),
               {"i": aud, "o": org, "p": 项目, "t": json.dumps({"release_id": rm, "environment": "production", "从": None})})
    if 跑完:
        造生产运行(cc, org, 项目, run, rm)
    return rm


def 造生产运行(cc, org, 项目, run, rm, 状态="succeeded"):
    cc.execute(text("""insert into execution_runs (id, organization_id, project_id, kind, release_ref, environment, status,
                           execution_mode, created_at, updated_at, ended_at, revision)
                       values (:i, :o, :p, 'application', cast(:r as jsonb), 'production', :st, 'live', now(), now(), now(), 1)"""),
               {"i": run, "o": org, "p": 项目, "r": json.dumps({"id": rm, "kind": "release_manifest"}), "st": 状态})


def 发布记录体(清单):
    return {"种类": "应用发布清单", "发布清单": 清单, "改了哪些依赖版本": "工作流 v1 → v2(加急规则改按工序)",
            "批准人": "店长 林岚", "采用新版本的入口": "聊天站店长助手 / 访问 API", "试点范围": "先在本店手动启用",
            "观察指标": "加急类问答的差评数", "回退版本": "工作流 v1(上一份清单)", "回退触发条件": "出现一次承诺交期就回退"}


def 走齐证据(打, 库, org, 项目, P, iid, 标, 后缀):
    """建好能让「验证通过」「发布生效」放行的验证记录和发布记录 → (验证记录, 发布记录)。走接口建;失败就抛,让调用方当场看见。
    `库` 是 engine:夹具在自己的事务里**先提交**,接口那边(另一条连接)才看得见、外键才过得去。"""
    with 库.begin() as cc:
        复, 回, 保, dv = 造评测与数据(cc, org, 项目, 标, 后缀)
        rm = 造生产发布(cc, org, 项目, 标, 后缀)
    c, v = 打("POST", P + f"/issues/{iid}/verifications", 验证记录体(复, 回, 保, dv))
    if c != 201:
        raise AssertionError(f"建验证记录失败 {c} {v}")
    c, r = 打("POST", P + f"/issues/{iid}/releases", 发布记录体(rm))
    if c != 201:
        raise AssertionError(f"建发布记录失败 {c} {r}")
    return v["id"], r["id"]


def 清掉(cc, 项目, 标, 问题单条件="title like :t"):
    """先删挂在这些问题单上的验证 / 发布记录(外键 RESTRICT),再删夹具行。问题单本身由调用方删。"""
    我的单 = f"select id from issues where project_id=:p and {问题单条件}"
    参 = {"p": 项目, "t": 标 + "%"}
    cc.execute(text(f"delete from issue_releases where project_id=:p and issue_id in ({我的单})"), 参)
    cc.execute(text(f"delete from issue_verifications where project_id=:p and issue_id in ({我的单})"), 参)
    for 表 in ("execution_runs", "audit_events", "environment_bindings", "release_manifests", "applications",
              "chat_assistant_versions", "chat_assistants", "evaluations", "dataset_versions"):
        cc.execute(text(f"delete from {表} where project_id=:p and id like :t"), 参)
