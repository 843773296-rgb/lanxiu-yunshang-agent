"""工具连接加鉴权方式列auth

Revision ID: 5a9f567d29b4
Revises: 2ae099e8e0f0
Create Date: 2026-11-16 20:03:46.809882

为什么:HTTP 请求节点(三期 3-1)发送时按连接上登记的「鉴权方式」把凭据装进请求头
(secretref.凭据头:无 / bearer / 自定义头名),而 capability_connections 原来只有 secret_ref(密钥在哪),
没有「怎么用它」—— worker 里一直写死空字典、按默认走。这列存 {"方式": "无"|"bearer"|"header", "头名": "x-api-key"}。
⚠️ 只存方式和头名,**不存任何密钥值**(密钥仍只以 secret_ref 引用);为空 = 老连接,按「无」处理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5a9f567d29b4'
down_revision: Union[str, Sequence[str], None] = '2ae099e8e0f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('capability_connections',
                  sa.Column('auth', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('capability_connections', 'auth')
