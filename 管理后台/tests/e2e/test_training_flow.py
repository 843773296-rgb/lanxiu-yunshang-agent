#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微调训练链端到端(§17.4):训练任务 / 产物 / 部署。

## 这一份守的一句话

规格开篇第 4 条:

> **训练完成仅代表得到产物;须经过登记、兼容检查、评测、部署与发布才能服务用户。**

所以这条链上有**四个各不相同的状态**:

    训练完成  →  有产物  →  产物可用(校验过)  →  在服务用户(部署了)

**把任意两个合成一个,界面上看起来一切正常** —— 一个没校验过的产物会显示成
「可以用了」。所以这一份的重点不是「能不能训成」,是**三道边界各自拦不拦得住**。

## ⚠️ 里面有一条是真 bug 换来的

`POST /training-jobs/{id}/cancel` 第一版把「直接取消」写成
「状态机允许走到『已取消』就走」—— 而「取消请求中 → 已取消」那条边
**只该由后台确认的时候走**。于是**连点两次取消,系统就自己宣布「已取消」**,
正是契约明令禁止的那件事。

⚠️ 同一条判断在 `runctl.py` 里写过(两次提交之前),换到这个模块又漏了。
**教训不会自动跟着代码走** —— 它只跟着「被写成判据的地方」走。
所以这一份里那条断言点名验「**第二次点不许改变状态**」。

⚠️ 前提 `make dev` + `python3 tools/seed_training.py`(它会补一个 trainer ——
没有他,这一组接口**一条都跑不起来**:`提交真实训练` 只有 trainer 和
被授权的 admin 有,而 demo 项目里原来一个 trainer 都没有)。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
基址 = os.environ.get("AIMC_BASE", "http://127.0.0.1:8801")
项目 = os.environ.get("AIMC_PROJECT", "project_demo_a")
P = f"/api/v1/projects/{项目}"
过, 挂 = [], []

训练员 = "U008"      # trainer(seed_training.py 补的)
发布员 = "U001"      # admin:「生产审核/发布/回滚」默认有


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:150]) if 补 else ''}")
    (过 if 真 else 挂).append(名)


def 打(方法, 路, 体=None, 谁=None, 键=None):
    req = urllib.request.Request(
        基址 + urllib.parse.quote(路, safe="/?&=:%"), method=方法,
        data=json.dumps(体, ensure_ascii=False).encode() if 体 is not None else None)
    req.add_header("X-Dev-User", 谁 or 训练员)
    if 键:
        req.add_header("Idempotency-Key", 键)
    if 体 is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"     连不上 {基址}:{e} —— 先 `make dev`")
        sys.exit(1)


from sqlalchemy import text            # noqa: E402
from db import 连接                     # noqa: E402


def 冻结版本():
    with 连接() as c:
        return c.execute(text("""select id from dataset_versions
                               where project_id=:p and frozen_samples is not null
                               order by created_at desc limit 1"""),
                         {"p": 项目}).scalar()


def 任务状态(jid):
    with 连接() as c:
        return c.execute(text("""select status from training_jobs
                               where project_id=:p and id=:i"""),
                         {"p": 项目, "i": jid}).scalar()


def 审计有(action, 键名, 值):
    with 连接() as c:
        return bool(c.execute(text(f"""select 1 from audit_events
                                    where project_id=:p and action=:a
                                      and target_ref->>'{键名}' = :v limit 1"""),
                              {"p": 项目, "a": action, "v": 值}).first())


def K():
    return "tj-e2e-" + uuid.uuid4().hex[:10]


def main():
    print("\n\033[1m▸ 微调训练链 · 四个状态之间的三道边界\033[0m")
    V = 冻结版本()
    if not V:
        print("     没有固化过的数据集版本 —— 先 python3 tools/seed_datasets.py "
              "再冻一版(或跑 test_datasets_flow.py)"); sys.exit(1)

    # ── 一、谁能提交:**没有 trainer 的话这一组一条都跑不起来** ──────────
    码, 体 = 打("GET", f"{P}/training-jobs")
    ck("GET /training-jobs 200", 码 == 200, 码)
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "SFT", "参数更新方式": "LoRA",
               "数据集版本": V}, 谁="U002", 键=K())
    ck("editor 提交训练 → 403(`提交真实训练` 只有 trainer / 被授权的 admin)",
       码 == 403, 码)
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "SFT", "参数更新方式": "LoRA",
               "数据集版本": V}, 谁="U003", 键=K())
    ck("viewer 提交训练 → 403", 码 == 403, 码)

    # ── 二、两个维度,不是三选一 ─────────────────────────────────────
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "LoRA", "参数更新方式": "LoRA",
               "数据集版本": V}, 键=K())
    ck("把 LoRA 填进「训练目标」→ 422(SFT/DPO 和 LoRA/全量是**两个维度**)",
       码 == 422 and "训练目标" in ((体 or {}).get("field_errors") or {}),
       (码, list(((体 or {}).get("field_errors") or {}).keys())))
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "SFT", "数据集版本": V}, 键=K())
    ck("漏了「参数更新方式」→ 422(不许只选一个维度)",
       码 == 422 and "参数更新方式" in ((体 or {}).get("field_errors") or {}), 码)

    # ── 三、幂等键是硬要求:超时重发一次 = 再烧一遍 GPU ────────────────
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "SFT", "参数更新方式": "LoRA",
               "数据集版本": V})
    ck("不带幂等键 → 409(**超时重发一次 = 再烧一遍 GPU**)",
       码 == 409 and (体 or {}).get("code") == "IDEMPOTENCY_KEY_REQUIRED",
       (码, (体 or {}).get("code")))

    # ── 四、语义闸没过要**留痕**,格式错不留痕 ──────────────────────────
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "q", "训练目标": "SFT", "参数更新方式": "LoRA"}, 键=K())
    ck("没给冻结版本 → 422 CANNOT_TRAIN",
       码 == 422 and (体 or {}).get("code") == "CANNOT_TRAIN",
       (码, (体 or {}).get("code")))
    留痕 = ((体 or {}).get("field_errors") or {}).get("training_job_id")
    ck("这次尝试**建了一条「失败」的任务留痕**(会烧钱的模块,试过什么要记)",
       bool(留痕) and 任务状态(留痕) == "失败", (留痕, 任务状态(留痕) if 留痕 else None))
    ck("拦下的理由进了审计", 审计有("training_job.submit", "training_job_id", 留痕 or "x"))

    # ── 五、正常提交:mock 要当场标出来 ───────────────────────────────
    键 = K()
    码, 体 = 打("POST", f"{P}/training-jobs",
              {"基座模型": "qwen2.5-7b", "训练目标": "SFT",
               "参数更新方式": "LoRA", "数据集版本": V}, 键=键)
    ck("正常提交 → 202", 码 == 202, (码, (体 or {}).get("code")))
    jid = (体 or {}).get("id")
    ck("本机 TRAINING_ADAPTER=mock → **当场标出是 mock 跑的**",
       (体 or {}).get("是mock跑的") is True, (体 or {}).get("是mock跑的"))
    ck("而且说清后果(产物不许计入真实评测或发布)",
       "不许" in str((体 or {}).get("note")), str((体 or {}).get("note"))[:60])
    码, 体2 = 打("POST", f"{P}/training-jobs",
               {"基座模型": "qwen2.5-7b", "训练目标": "SFT",
                "参数更新方式": "LoRA", "数据集版本": V}, 键=键)
    ck("同一个幂等键再提 → **没有再烧一遍 GPU**",
       (体2 or {}).get("id") == jid and (体2 or {}).get("新建了吗") is False,
       ((体2 or {}).get("id"), (体2 or {}).get("新建了吗")))

    # ── 六、取消:**「请求取消」不是「取消」** ────────────────────────
    码, c1 = 打("POST", f"{P}/training-jobs/{jid}/cancel", 键=K())
    ck("取消 → 202 且状态是「取消请求中」,**不是「已取消」**",
       码 == 202 and (c1 or {}).get("status") == "取消请求中",
       (码, (c1 or {}).get("status")))
    # ⚠️ **这一条是真 bug 换来的**:第一版连点两次就宣布「已取消」,
    #    而契约写着「最终状态由后台确认,UI 不许直接显示成已取消」。
    码, c2 = 打("POST", f"{P}/training-jobs/{jid}/cancel", 键=K())
    ck("**再点一次不许把它变成「已取消」**(最终状态由后台确认)",
       (c2 or {}).get("status") == "取消请求中" and (c2 or {}).get("改了吗") is False,
       ((c2 or {}).get("status"), (c2 or {}).get("改了吗")))
    ck("库里也确实还是「取消请求中」", 任务状态(jid) == "取消请求中", 任务状态(jid))
    # 终态上取消 → 保留真实终态,不谎报
    码, c3 = 打("POST", f"{P}/training-jobs/tj_seed_真/cancel", 键=K())
    ck("已完成的任务上点取消 → **保留真实终态,不谎报成已取消**",
       (c3 or {}).get("改了吗") is False and (c3 or {}).get("status") == "已完成",
       ((c3 or {}).get("改了吗"), (c3 or {}).get("status")))

    # ── 七、详情:四个状态说得清楚 ───────────────────────────────────
    码, d = 打("GET", f"{P}/training-jobs/{jid}")
    ck("GET /training-jobs/{id} 200", 码 == 200, 码)
    ck("详情里点明「已完成只代表得到产物」", "只代表得到产物" in str((d or {}).get("note")),
       str((d or {}).get("note"))[:50])
    ck("详情给出「下一步能走哪些状态」", isinstance((d or {}).get("下一步"), list),
       (d or {}).get("下一步"))

    # ── 八、登记产物:**usable 一律从 false 起,而且不收这个参数** ────────
    码, a = 打("POST", f"{P}/model-artifacts",
             {"种类": "adapter", "基座模型": "qwen2.5-7b",
              "文件清单": ["adapter_model.safetensors"],
              # 故意硬塞 —— 接口不收,塞了也没用
              "usable": True, "标了可用吗": True}, 键=K())
    ck("登记产物 → 201", 码 == 201, 码)
    ck("**硬塞 `usable=true` 也没用**(收了就等于让调用方自己说「我校验过了」)",
       (a or {}).get("标了可用吗") is False, (a or {}).get("标了可用吗"))
    码, 体 = 打("POST", f"{P}/model-artifacts",
              {"种类": "adapter", "基座模型": "q"}, 键=K())
    ck("没给文件清单 → 422(少一个文件的产物**装载时才报错**,那时已标可用)",
       码 == 422 and "文件清单" in ((体 or {}).get("field_errors") or {}), 码)
    码, 体 = 打("POST", f"{P}/model-artifacts",
              {"种类": "adapter", "基座模型": "q", "文件清单": ["a"],
               "训练任务": "tj_根本不存在"}, 键=K())
    ck("给了不存在的训练任务 → 422,**不静默改成 NULL 收下**",
       码 == 422 and (体 or {}).get("code") == "TRAINING_JOB_NOT_FOUND",
       (码, (体 or {}).get("code")))

    # ── 九、部署:三道闸,四种产物里只有一种能过 ──────────────────────
    闸 = [
        ("ma_seed_未校验", "没标可用", "「有产物」和「产物可用」是两个状态"),
        ("ma_seed_mock", "mock 训练适配器", "铁律:mock 产物不许计入真实发布"),
        ("ma_seed_说不清", "说不清", "**未知不是「不是」**"),
    ]
    for aid, 关键词, 说 in 闸:
        码, 体 = 打("POST", f"{P}/deployments",
                  {"产物": aid, "环境": "production"}, 谁=发布员, 键=K())
        理由 = " ".join(((体 or {}).get("field_errors") or {}).get("闸", []))
        ck(f"部署闸:{说} → 422",
           码 == 422 and (体 or {}).get("code") == "CANNOT_DEPLOY" and 关键词 in 理由,
           (码, (体 or {}).get("code"), 理由[:60]))
        ck(f"  ↳ 被拦这件事进了审计({aid})",
           审计有("deployment.blocked", "model_artifact_id", aid))

    码, 体 = 打("POST", f"{P}/deployments",
              {"产物": "ma_seed_可部署", "环境": "乱写的环境"}, 谁=发布员, 键=K())
    ck("环境认不出 → 422(**不给默认值**:默认成 test 会把生产部署记成测试)",
       码 == 422, 码)
    码, 体 = 打("POST", f"{P}/deployments",
              {"产物": "ma_seed_可部署", "环境": "production"}, 谁="U003", 键=K())
    ck("viewer 部署 → 403", 码 == 403, 码)

    # **对照**:校验过 + 真适配器 + 环境合法 → 放得出去。
    # 没有这一条,一个「什么都不放行」的实现照样能让上面全绿。
    键2 = K()
    码, dep = 打("POST", f"{P}/deployments",
               {"产物": "ma_seed_可部署", "环境": "production"}, 谁=发布员, 键=键2)
    ck("对照:校验过的真产物 → 202(闸不是一刀切)", 码 == 202, (码, (dep or {}).get("code")))
    ck("状态是「部署请求中」,**不是「在服务用户」**",
       (dep or {}).get("status") == "部署请求中", (dep or {}).get("status"))
    码, dep2 = 打("POST", f"{P}/deployments",
                {"产物": "ma_seed_可部署", "环境": "production"}, 谁=发布员, 键=键2)
    ck("同一个幂等键再部署 → 不新建", (dep2 or {}).get("新建了吗") is False,
       (dep2 or {}).get("新建了吗"))
    # 放行时依据了什么,要留在行里 —— 不能只留在某个人的记忆里
    with 连接() as c:
        证据 = c.execute(text("""select gate_evidence from deployments
                              where project_id=:p and id=:i"""),
                        {"p": 项目, "i": (dep or {}).get("id")}).scalar()
    ck("放行依据写进了 `gate_evidence`(部署是不可逆的对外动作)",
       bool(证据) and "是mock训练的" in str(证据), str(证据)[:80])

    # ── 十、产物列表:说不清的要显示成 null,不是 false ────────────────
    码, 体 = 打("GET", f"{P}/model-artifacts")
    ck("GET /model-artifacts 200", 码 == 200, 码)
    表 = {x["id"]: x for x in (体 or {}).get("产物", [])}
    ck("没有训练任务的产物,`是mock训练的` 是 **null 不是 false**",
       "ma_seed_说不清" in 表 and 表["ma_seed_说不清"]["是mock训练的"] is None,
       表.get("ma_seed_说不清", {}).get("是mock训练的"))
    ck("没校验过的产物,列表上就标着「还差什么」",
       "ma_seed_未校验" in 表 and 表["ma_seed_未校验"]["能标可用吗"] is False
       and 表["ma_seed_未校验"]["还差什么"],
       表.get("ma_seed_未校验", {}).get("还差什么"))

    print(f"\n{'✅' if not 挂 else '❌'} 过 {len(过)} / 挂 {len(挂)}")
    if 挂:
        for x in 挂:
            print("   挂:", x)
    return 1 if 挂 else 0


if __name__ == "__main__":
    sys.exit(main())
