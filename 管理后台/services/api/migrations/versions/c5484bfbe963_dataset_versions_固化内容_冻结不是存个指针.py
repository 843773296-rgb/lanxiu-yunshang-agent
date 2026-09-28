"""dataset_versions.frozen_samples:冻结要固化内容,不是存个指针

契约(`endpoints.py` 里 `POST /datasets/{id}/versions` 那条)写得很清楚:
**冻结要固化内容,不是存个指针 —— 否则样本一改,「冻结版本」跟着变。**

而这张表原来只有 `content_hash` 和 `sample_count`,**没有装内容的地方**。
只存哈希的话:样本改了 → 哈希对不上 → 能发现「变了」,
但**发现不了变成什么了**,更拿不回原来那一版去重跑。
而评测要回答的正是「同一批题,换个配置分数变没变」——
拿不回原来那批题,这个问题就问不成。

⚠️ **没往 `split_map` 里塞。** 那一列是分集映射,再塞一份内容进去就是
「一列两个含义」—— 这个仓库今天已经为这个形状付过两次代价
(`usage_ledger.source` 装执行模式又装供应商、`feedback.note` 是 TEXT 当 JSONB 用)。

⚠️ revision id 用 `uuid.uuid4().hex[:12]` 生成,**别手编** ——
本轮手编的那个撞上了仓库里已有的一条,而 alembic 报的是
「Multiple head revisions」,离真因很远。

⚠️ 写这个文件时踩了一个:**未加引号的 heredoc 里,反引号会被 shell 当命令替换执行。**
`cat > f <<PYEOF` 配上正文里的 `` `endpoints.py` ``,shell 真的去跑了 `endpoints.py`,
报 `command not found`,而**文件照样写成了,只是那段话被吃掉了一截**。
迁移跑成功、退出码 0、只有一行不显眼的警告 —— 这是「成功了但内容不对」的又一种。
用 `<<'PYEOF'`(加引号)就不会。同一族:凡是要过一层解析的东西,别指望它照原样过去。

Revision ID: c5484bfbe963
Revises: cca1abb72298
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c5484bfbe963"
down_revision = "cca1abb72298"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dataset_versions",
                  sa.Column("frozen_samples", postgresql.JSONB(), nullable=True))
    # 不回填。已有的版本行确实没有固化内容 —— 把它们标成「有」是撒谎,
    # 而「这一版拿不回原题」是个必须看得见的事实。


def downgrade():
    op.drop_column("dataset_versions", "frozen_samples")
