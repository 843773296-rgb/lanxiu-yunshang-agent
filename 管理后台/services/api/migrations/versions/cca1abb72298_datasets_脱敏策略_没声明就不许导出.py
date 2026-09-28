"""datasets.redaction_policy:没声明脱敏策略的数据集不许导出

一份训练数据导出的危险之处不是「脱得不够干净」,是**没人声明过它该怎么脱**。
没声明的时候,`脱=True` 这个参数看起来做了防护,而它到底脱掉了什么
取决于实现里恰好写了哪几条正则 —— 而那件事在调用点上**看不见**。

所以这一列不是「脱敏配置」,是**一句声明**:这个数据集里有什么敏感内容、
按哪条策略脱。没有它,导出接口一律拒 —— 拒的理由是「策略没声明」,
不是「脱不干净」,两者下一步不同(去声明 / 去改脱敏器)。

⚠️ **可以为空,而且默认为空。** 给个默认值('none' / '无')就等于替所有
已经存在的数据集声明了「不用脱」—— 而那正是这一列要防的那件事。
空 = 没人声明过,而「没人声明过」必须是个**会被拦住**的状态,不是一个默认放行的状态。

⚠️ **revision id 用随机生成的,别手编。** 这个文件第一版手写了
`a1b2c3d4e5f6`,而仓库里已经有一条同 id 的(`embeddings 向量表` 那条,
它也是手编的)。撞上之后 alembic 报的是 **「Multiple head revisions are present」**——
那条消息指向「有两个头,请指定一个」,**离真因(两个文件同名)很远**,
而且 `alembic heads` 会把被顶掉的那条列成 head,看起来像是漏了个 down_revision。
`python3 -c "import uuid;print(uuid.uuid4().hex[:12])"`。

Revision ID: cca1abb72298
Revises: d5967668bab7
"""
from alembic import op
import sqlalchemy as sa

revision = "cca1abb72298"
down_revision = "d5967668bab7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("datasets", sa.Column("redaction_policy", sa.Text(), nullable=True))
    # 不回填。见文件头:回填等于替所有旧数据集声明「不用脱」。


def downgrade():
    op.drop_column("datasets", "redaction_policy")
