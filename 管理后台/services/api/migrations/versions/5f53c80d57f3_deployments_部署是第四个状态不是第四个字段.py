"""deployments:部署是第四个状态,不是第四个字段

规格开篇第 4 条:

> **训练完成仅代表得到产物;须经过登记、兼容检查、评测、部署与发布才能服务用户。**

所以这条链上有**四个各不相同的状态**:

    训练完成  →  有产物  →  产物可用(校验过)  →  在服务用户(部署了)

把任意两个合成一个,就是这个模块最容易出的错 ——
而合并之后**界面上看起来一切正常**:一个没校验过的产物会显示成「可以用了」。

之所以要一张表而不是在 `model_artifacts` 上加一个 `deployed` 布尔:
**同一个产物可以部署到不同环境、可以回滚、可以部署两次** ——
一个布尔答不出「它现在在哪儿跑、是谁在哪天放上去的」,
而那正是出事时唯一要问的问题。

⚠️ revision id 用 `uuid.uuid4().hex[:12]` 生成,别手编(手编的撞过一次)。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "5f53c80d57f3"
down_revision = "c5484bfbe963"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deployments",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.BigInteger()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("model_artifact_id", sa.Text(), nullable=False),
        # 环境:test / staging / production。**不给默认值** ——
        # 默认成 test 的话,一次忘了传就把生产部署记成了测试部署。
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("endpoint_ref", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        # 为什么允许这次部署 —— 部署是不可逆的对外动作,
        # 「当时凭什么放行」必须留在行里,不能只留在某个人的记忆里。
        sa.Column("gate_evidence", postgresql.JSONB()),
        sa.PrimaryKeyConstraint("project_id", "id", name="pk_deployments"),
        sa.ForeignKeyConstraint(
            ["project_id", "model_artifact_id"],
            ["model_artifacts.project_id", "model_artifacts.id"],
            name="fk_deployments_model_artifact"),
        # ⚠️ 幂等键唯一。部署是异步 + 对外的动作,超时重发是常态 ——
        # **能用约束表达的不要用判据表达**:约束在每次 INSERT 上生效,
        # 判据只在有人调用它的时候生效(这个仓库今天为此兑现过四次)。
        sa.UniqueConstraint("project_id", "idempotency_key",
                            name="uq_deployments_project_id_idempotency_key"),
    )
    op.create_index("ix_deployments_project_artifact", "deployments",
                    ["project_id", "model_artifact_id"])


def downgrade():
    op.drop_index("ix_deployments_project_artifact", table_name="deployments")
    op.drop_table("deployments")
