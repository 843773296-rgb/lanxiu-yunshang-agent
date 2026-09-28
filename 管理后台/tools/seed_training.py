#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铺微调训练链的夹具:**一个能提交训练的人,和四种各不相同的产物**。

    python3 tools/seed_training.py

## 为什么第一件事是「补一个人」

`提交真实训练` 这条权限:`trainer=有额度`、`admin=可授权`,其余角色**否**。
而 `project_demo_a` 里**一个 trainer 都没有**,admin 也没拿那条专项授权 ——
于是接口做完了,**没有任何人能提交训练**。

> **一道拦得住但没有放行入口的闸,是做了一半的机制。**
> 而它在检查上是绿的:「没有权限的人提交训练被挡住」照样过。

(同一个形状 09-28 已经出现过一次:§12 的人工待办闸拦得住,
 而在那之前没有任何代码能生产一条批准。)

## 四种产物,各考一道闸

产物这条链上有**四个各不相同的状态**,而闸守的是它们之间的边界:

    训练完成  →  有产物  →  产物可用(校验过)  →  在服务用户(部署了)

所以夹具也按边界铺,而不是铺「几个正常的产物」:

  · **没校验过的**            → 不许标可用,更不许部署
  · **校验过、真适配器跑的**   → 唯一一个能部署的
  · **校验过、mock 跑的**      → 铁律拦住(§17.4:mock 产物不许计入真实发布)
  · **校验过、没有训练任务**   → **说不清是不是 mock** → 也拦住(**未知不是「不是」**)

最后那一种最容易被漏掉:它看起来「干干净净什么问题都没有」,
而正因为什么都查不到,它才必须被拦 —— 放行的话,那条铁律靠的就只是运气。
"""
import json, os, sys, uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "services", "api", "app"))
from sqlalchemy import text
from db import 事务

项目 = os.environ.get("SEED_PROJECT", "project_demo_a")
训练员 = "U008"


def main():
    with 事务() as c:
        org = c.execute(text("select organization_id from projects where id=:p"),
                        {"p": 项目}).scalar()
        if not org:
            print(f"❌ 没有项目 {项目}"); return 1

        # ① 补一个 trainer —— 没有他,这一组接口一条都跑不起来
        有 = c.execute(text("""select role from memberships
                             where project_id=:p and user_id=:u"""),
                       {"p": 项目, "u": 训练员}).scalar()
        if not 有:
            # ⚠️ 这一条插入栽了**两次**,而两次的形状不一样:
            #
            # ① `memberships` 有自己的 `id` 列而且 NOT NULL → 当场 NotNullViolation。
            # ② `status` 没设。它**可空**,所以插入一声不响地成功了 ——
            #    而 `deps.取身份()` 的查询带着 `m.status = 'active'`,
            #    于是这一行**在表里看着好好的,每条读路径都捞不到**。
            #    报出来的是另一个地方的 404(「这个项目下没有你的成员记录」),
            #    离真因隔了一层。
            #
            # > **「INSERT 成功」不等于「这一行有用」。**
            # > 今天「没查表结构就写 SQL」第八次,而前七次都是**写不进去**(当场报错),
            # > 这次是**写进去了却没人看得见** —— 后者贵得多。
            c.execute(text("""insert into memberships
                (id, user_id, organization_id, project_id, role, status,
                 special_grants, created_at, created_by, updated_at, revision)
                values (:i,:u,:o,:p,'trainer','active', cast('[]' as jsonb),
                        now(),'seed', now(), 1)"""),
                      {"i": f"mem_{uuid.uuid4().hex[:12]}",
                       "u": 训练员, "o": org, "p": 项目})
            print(f"  ✅ 补了一个 trainer:{训练员}")
        else:
            print(f"  · {训练员} 已经在({有})")

        # ② 一个「真适配器跑的」训练任务 —— 本机 TRAINING_ADAPTER=mock,
        #    所以真适配器那一份只能是夹具。**这正是它要考的事**:
        #    真/mock 的产物在数据形状上一模一样,只能靠这个标记认。
        任务 = {}
        for 名, 适配器 in (("真", "真实适配器"), ("mock", "mock")):
            jid = f"tj_seed_{名}"
            c.execute(text("delete from model_artifacts where project_id=:p and training_job_id=:i"),
                      {"p": 项目, "i": jid})
            c.execute(text("delete from training_jobs where project_id=:p and id=:i"),
                      {"p": 项目, "i": jid})
            c.execute(text("""insert into training_jobs
                (id, organization_id, project_id, config_snapshot, base_model,
                 objective, param_update_method, status, idempotency_key,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p, cast(:cs as jsonb), 'qwen2.5-7b','SFT','LoRA',
                        '已完成', :k, now(),'seed', now(), 1)"""),
                      {"i": jid, "o": org, "p": 项目,
                       "cs": json.dumps({"训练适配器": 适配器}, ensure_ascii=False),
                       "k": f"seed-{名}-{uuid.uuid4().hex[:6]}"})
            任务[名] = jid

        # ③ 四种产物
        产物 = [
            ("ma_seed_未校验", 任务["真"], None,
             "没校验过 → 不许标可用,更不许部署"),
            ("ma_seed_可部署", 任务["真"], "now()",
             "校验过 + 真适配器 → **唯一一个能部署的**"),
            ("ma_seed_mock", 任务["mock"], "now()",
             "校验过但 mock 跑的 → 铁律拦住(§17.4)"),
            ("ma_seed_说不清", None, "now()",
             "校验过但**没有训练任务** → 说不清是不是 mock → 也拦住(未知不是「不是」)"),
        ]
        for aid, jid, 校验, 考什么 in 产物:
            c.execute(text("delete from deployments where project_id=:p and model_artifact_id=:i"),
                      {"p": 项目, "i": aid})
            c.execute(text("delete from model_artifacts where project_id=:p and id=:i"),
                      {"p": 项目, "i": aid})
            c.execute(text(f"""insert into model_artifacts
                (id, organization_id, project_id, training_job_id, kind, base_model,
                 file_manifest, content_hash, verified_at, usable,
                 created_at, created_by, updated_at, revision)
                values (:i,:o,:p,:j,'adapter','qwen2.5-7b',
                        cast(:fm as jsonb), :h, {校验 or 'null'},
                        {'true' if 校验 else 'false'},
                        now(),'seed', now(), 1)"""),
                      {"i": aid, "o": org, "p": 项目, "j": jid,
                       "fm": json.dumps(["adapter_model.safetensors",
                                         "adapter_config.json"], ensure_ascii=False),
                       "h": uuid.uuid4().hex[:32]})
            print(f"  {aid:18} → {考什么}")
    print(f"\n⚠️ 四种里**只有一种能部署** —— 另外三种各被一道不同的闸拦住,"
          f"而它们在界面上长得几乎一样")
    return 0


if __name__ == "__main__":
    sys.exit(main())
