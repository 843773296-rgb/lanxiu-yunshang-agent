"""评测记「模型评审用哪条连接」(判对规则 C,用户 2026-11-05 拍)

Revision ID: b3e8f1c5a9d2
Revises: 9a6c1d3e7f42
Create Date: 2026-11-05

判法 C:能写成字段判据的题按字段比;写不成的(只有「期望说明」)交给模型评审,结果标明「模型判的」。
模型评审要知道用哪条模型连接 —— 记在评测上(**哪次评测用哪个评审是这次实验的一部分**:换了评审的两次不可比,
和「换了判据版本的两轮不可比」是同一条)。

可空:题全是字段判据的评测不需要评审连接;有要模型评审的题、却没给连接 → 建评测时就拒(evals_api)。
**没挂库外键**:models 按列名约定(<父>_id)推外键,这一列不合约定 —— 挂了的话 alembic check 会报模型和库不一致。
「只能指向本项目的连接」由建评测时那一道查(evals_api,按 project_id 查得到才收),e2e 攻一次跨项目的。
"""
from alembic import op

revision = "b3e8f1c5a9d2"
down_revision = "9a6c1d3e7f42"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("alter table evaluations add column judge_connection_version_id text")


def downgrade():
    op.execute("alter table evaluations drop column if exists judge_connection_version_id")
