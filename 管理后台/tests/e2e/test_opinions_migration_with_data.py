#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意见单三条迁移**带数据**从零连着跑(2026-11-04;并行会话提醒「每一轮只在 0 行的表上验过,CI 也是空库」)。

## 为什么要自己建库、自己造数据

opinions 在共享库和 CI 上都是空的 —— **空表上所有 CHECK 自动成立**,迁移「跑得过」证明不了它对。
这一份自己建一个临时库,每升一步之前先插那一版形状的数据,再往上升;最后往下降。
**红不红只取决于迁移代码,不取决于哪个库里碰巧有什么**(CLAUDE.md 第 9 节)。

## 判据

  ① 升到建表那一版(807d1cc1d238),插三种形状的行(有帮助 / 有问题 / 执行失败)
  ② 升第二条(2d2eb200f027):现存行都满足新 CHECK;再插一条独立建议
  ③ 升到最新:现存行都在,时间线表能写
  ④ **有独立建议时往下降 → 拒绝**:退出码非 0、报错说出「几条独立建议」、整段回滚(版本还在最新、时间线一行没丢)
     —— 11-04 第一次带数据跑时,这里报的是「ck_opinions_problem 被某行违反」,照着没法行动;现在要说清楚
  ⑤ 删掉独立建议之后:降到建表之前、再升回最新,都过

用完把临时库删掉(不管过没过)。
"""
import os
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

过, 挂 = [], []
_根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_api = os.path.join(_根, "services", "api")
_alembic = os.path.join(_根, ".venv", "bin", "alembic")
建表之前, 建表, 第二条 = "72a7e0a33c0e", "807d1cc1d238", "2d2eb200f027"


def ck(名, 真, 补=""):
    print(f"  {'✅' if 真 else '❌'} {名}{('  ' + str(补)[:400]) if 补 and not 真 else ''}")
    (过 if 真 else 挂).append(名)


def main():
    基 = make_url(os.environ.get("DATABASE_URL") or f"postgresql+psycopg://{os.environ.get('USER')}@localhost:5432/aimc_dev")
    名 = "aimc_mig_op_" + uuid.uuid4().hex[:8]
    临 = 基.set(database=名)
    管 = create_engine(基, isolation_level="AUTOCOMMIT")
    with 管.connect() as c:
        c.execute(text(f'create database "{名}"'))
    库 = create_engine(临)
    env = {**os.environ, "DATABASE_URL": 临.render_as_string(hide_password=False)}

    def 迁(方向, 到):
        p = subprocess.run([_alembic, 方向, 到], cwd=_api, env=env, capture_output=True, text=True, timeout=600)
        return p.returncode, (p.stdout + p.stderr)

    def 执(sql, **参):
        with 库.begin() as c:
            return c.execute(text(sql), 参)

    def 读(sql, **参):
        with 库.connect() as c:
            return c.execute(text(sql), 参).scalar()

    try:
        print("▸ ① 升到建表那一版,插三种形状")
        码, 出 = 迁("upgrade", 建表)
        ck("升到 807d1cc1d238", 码 == 0, 出[-400:])
        执("insert into organizations (id, name, created_at) values ('org_m', 'm', now())")
        执("insert into projects (id, organization_id, created_at) values ('p_m', 'org_m', now())")
        执("""insert into opinions (id, organization_id, project_id, created_at, source, chat_trace_ref, verdict,
                  problem_type, note, asker_staff_code, status, history_snapshot) values
              ('o1','org_m','p_m',now(),'问答','t1','有帮助',null,null,'s1','待受理','[]'),
              ('o2','org_m','p_m',now(),'问答','t2','有问题','答错','错了','s1','核实中','[]'),
              ('o3','org_m','p_m',now(),'执行失败','t3','有问题','太慢或失败','卡住','s2','不采纳','[]')""")
        ck("建表那一版插了 3 行", 读("select count(*) from opinions") == 3)

        print("\n▸ ② 升第二条(提交键 + 建议)")
        码, 出 = 迁("upgrade", 第二条)
        ck("现存 3 行上升得过(新 CHECK 对它们成立)", 码 == 0, 出[-400:])
        执("""insert into opinions (id, organization_id, project_id, created_at, source, verdict, problem_type, note,
                  asker_staff_code, status, submit_ref)
              values ('o4','org_m','p_m',now(),'独立建议','建议','新增能力','想要导出','s1','待受理','k1')""")
        ck("能插独立建议", 读("select count(*) from opinions where source='独立建议'") == 1)

        print("\n▸ ③ 升到最新(受理台)")
        码, 出 = 迁("upgrade", "head")
        ck("4 行上升得过", 码 == 0, 出[-400:])
        执("""insert into opinion_events (id, organization_id, project_id, created_at, opinion_id, action_code,
                  from_status, to_status) values ('e1','org_m','p_m',now(),'o2','开始核实','待受理','核实中')""")
        ck("时间线表能写", 读("select count(*) from opinion_events") == 1)
        最新 = 读("select version_num from alembic_version")

        print("\n▸ ④ 有独立建议时往下降")
        码, 出 = 迁("downgrade", 建表之前)
        ck("**降级被拒**(退出码非 0)", 码 != 0, 出[-300:])
        ck("**报错说清楚:有几条独立建议、不自动删**(不是「某行违反约束」)",
           "1 条独立建议" in 出 and "不自动删" in 出, 出[-500:])
        ck("整段回滚:版本还在最新、时间线一行没丢、4 行都在",
           读("select version_num from alembic_version") == 最新 and 读("select count(*) from opinion_events") == 1
           and 读("select count(*) from opinions") == 4, 出[-200:])

        print("\n▸ ⑤ 删掉独立建议之后能降能升")
        执("delete from opinions where source='独立建议'")
        码, 出 = 迁("downgrade", 建表之前)
        ck("降到建表之前", 码 == 0 and 读("select to_regclass('opinions')") is None, 出[-400:])
        码, 出 = 迁("upgrade", "head")
        ck("再升回最新", 码 == 0 and 读("select version_num from alembic_version") == 最新, 出[-400:])
    finally:
        库.dispose()
        with 管.connect() as c:
            c.execute(text(f'drop database if exists "{名}" with (force)'))
        管.dispose()

    print()
    if 挂:
        print(f"❌ {len(挂)} 条不过:{' / '.join(挂)}")
        return 1
    print(f"✅ 意见单迁移带数据连跑:{len(过)} 条全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
