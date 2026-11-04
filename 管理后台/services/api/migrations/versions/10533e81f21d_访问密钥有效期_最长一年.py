"""访问密钥有效期_最长一年

Dify 对标 C05「API 凭证过期 → 拒绝并记录原因」(2026-11-04)。用户拍:**发的时候必须选有效期,最长 1 年**
(30 / 90 / 180 / 365 天,页面默认 90)。
**11-04 之前发的那些按发出那天加一年补上** —— 否则「忘了吊销的密钥最多活一年」对老密钥不成立。
已经发出去超过一年的,补完就是已过期:下一次调用会被拒并记「已过期」(这是对的 —— 它本来就该到期了)。

Revision ID: 10533e81f21d
Revises: 13fd23fe5b7f
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '10533e81f21d'
down_revision: Union[str, Sequence[str], None] = '13fd23fe5b7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('access_keys', sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.execute("update access_keys set expires_at = created_at + interval '365 days' where expires_at is null")
    op.alter_column('access_keys', 'expires_at', existing_type=sa.TIMESTAMP(timezone=True), nullable=False)
    op.create_check_constraint('ck_access_keys_expiry', 'access_keys',
                               "expires_at > created_at and expires_at <= created_at + interval '366 days'")


def downgrade() -> None:
    op.drop_constraint('ck_access_keys_expiry', 'access_keys', type_='check')
    op.drop_column('access_keys', 'expires_at')
