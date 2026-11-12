"""一次性:把端到端测试留在共享库里的假运行还原(2026-11-12)。

怎么来的(查实,不是推测):
- `tests/e2e/test_runctl_flow.py` 每次拿「最新一条真运行」当夹具、直接改库造状态,
  最后一步停在 running,从不还原 —— 攒出「正在跑、背后没有活物」的运行。
  原状态按步骤判:结束节点成功 → succeeded;有 run.failed 事件且带完成原因 → failed。
- `test_debug_evals_flow.py` 的分叉调试、`test_release_flow.py` 的应用调用:接口按设计只登记不入队,
  测试没归档 → 永远「排队中」。另有几条没有任何任务的 workflow 排队记录,同样是测试残留。

默认只打印要改什么(--dry-run);加 --写 才改。每改一条都在 run_events 记一笔 `run.data_fix`,
载荷里带「从 / 到 / 为什么」,改错了能照着改回去。测试本身已在同一次提交里改成用完就还 / 归档。
"""
import json
import os
import sys
import uuid

_根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_根, "services", "api", "app"))
from sqlalchemy import text  # noqa: E402
from db import 事务, 连接  # noqa: E402

写 = "--写" in sys.argv

查 = {
    "还原成功": """select r.id, r.project_id, r.organization_id, r.status from execution_runs r
                 where r.status='running' and r.archived_at is null
                   and exists(select 1 from run_steps s where s.execution_run_id=r.id
                              and s.kind='end' and s.status='succeeded')""",
    "还原失败": """select r.id, r.project_id, r.organization_id, r.status from execution_runs r
                 where r.status='running' and r.archived_at is null and r.completion_reason is not null
                   and exists(select 1 from run_events e where e.execution_run_id=r.id and e.event_type='run.failed')""",
    "测试残留": """select r.id, r.project_id, r.organization_id, r.status from execution_runs r
                 where r.status='queued' and r.archived_at is null
                   and (r.kind in ('application', 'fork_test')
                        or (r.kind='workflow' and r.created_at < now() - interval '1 day'
                            and not exists(select 1 from jobs j where j.target_ref->>'run_id'=r.id
                                           and j.status in ('排队中','执行中'))))""",
}
改成 = {"还原成功": ("succeeded", None, False), "还原失败": ("failed", "keep", False),
      "测试残留": ("cancelled", "TEST_RESIDUE", True)}


def main():
    with 连接() as c:
        批 = {k: [dict(x) for x in c.execute(text(q)).mappings()] for k, q in 查.items()}
    for k, 行们 in 批.items():
        print(f"  {k}:{len(行们)} 条 → {改成[k][0]}")
    if not 写:
        print("\n(只看不改;加 --写 才真改)")
        return 0
    with 事务() as c:
        for k, 行们 in 批.items():
            到, 原因, 归档 = 改成[k]
            for x in 行们:
                c.execute(text(f"""update execution_runs set status=:s,
                                   {'completion_reason=:cr,' if 原因 not in (None, 'keep') else ''}
                                   ended_at=coalesce(ended_at, now()),
                                   pause_requested=false, cancel_requested=false,
                                   {'archived_at=now(),' if 归档 else ''}
                                   updated_at=now(), revision=revision+1
                                   where project_id=:p and id=:i and status=:old"""),
                          {"s": 到, "cr": 原因, "p": x["project_id"], "i": x["id"], "old": x["status"]})
                seq = c.execute(text("select coalesce(max(seq),0)+1 from run_events where project_id=:p and execution_run_id=:r"),
                                {"p": x["project_id"], "r": x["id"]}).scalar()
                c.execute(text("""insert into run_events (id, organization_id, project_id, execution_run_id,
                                    seq, event_type, payload, occurred_at, created_at, created_by)
                                  values (:i,:o,:p,:r,:s,'run.data_fix',:pl, now(), now(), 'data_fix')"""),
                          {"i": "re_" + uuid.uuid4().hex[:12], "o": x["organization_id"], "p": x["project_id"],
                           "r": x["id"], "s": seq,
                           "pl": json.dumps({"从": x["status"], "到": 到, "为什么": k,
                                             "来源": "tools/fix_test_residue_runs.py 2026-11-12"},
                                            ensure_ascii=False)})
    with 连接() as c:
        剩 = c.execute(text("select status, count(*) from execution_runs where status in ('running','queued') "
                           "and archived_at is null group by 1")).all()
    print("  改完还剩:", dict(剩) or "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
