"""「拆句」改名「实体识别」:表 / 列 / 约束 / 索引 / 触发器一起改(用户 2026-11-08 拍「拆句应该有专业的 AI 词汇」→
「查询理解」分组下的实体识别 / 查询路由 / 意图识别,并且「连代码英文名一起改」)

split_dict_drafts → entity_dict_drafts;split_dict_versions → entity_dict_versions;
chat_assistant_versions.split_version_id → entity_version_id。数据原样保留(只改名字)。
约束 / 索引名也改 —— 不改的话,库里留着 split_* 名字,而契约派生出来的是 entity_*,「库结构 vs 契约」会对不上。

Revision ID: 8e2c4b6d1f37
Revises: 5d1e7a9c3b20
Create Date: 2026-11-08 13:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '8e2c4b6d1f37'
down_revision: Union[str, Sequence[str], None] = '5d1e7a9c3b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_表 = [("split_dict_drafts", "entity_dict_drafts"), ("split_dict_versions", "entity_dict_versions")]
_约束 = [("entity_dict_drafts", "pk_split_dict_drafts", "pk_entity_dict_drafts"),
         ("entity_dict_drafts", "fk_split_dict_drafts_projects", "fk_entity_dict_drafts_projects"),
         ("entity_dict_versions", "pk_split_dict_versions", "pk_entity_dict_versions"),
         ("entity_dict_versions", "fk_split_dict_versions_projects", "fk_entity_dict_versions_projects"),
         ("entity_dict_versions", "uq_split_dict_versions_project_id_key_content_hash", "uq_entity_dict_versions_project_id_key_content_hash"),
         ("entity_dict_versions", "uq_split_dict_versions_project_id_key_version_no", "uq_entity_dict_versions_project_id_key_version_no")]
_索引 = [("ix_split_dict_drafts_proj_updated", "ix_entity_dict_drafts_proj_updated"),
         ("ix_split_dict_versions_hash", "ix_entity_dict_versions_hash"),
         ("ix_split_dict_versions_proj_updated", "ix_entity_dict_versions_proj_updated")]


def upgrade() -> None:
    for 旧, 新 in _表:
        op.rename_table(旧, 新)
    for 表, 旧, 新 in _约束:
        op.execute(f'alter table {表} rename constraint "{旧}" to "{新}"')
    for 旧, 新 in _索引:
        op.execute(f'alter index "{旧}" rename to "{新}"')
    op.execute('alter trigger "trg_split_dict_versions_不可原地改" on entity_dict_versions rename to "trg_entity_dict_versions_不可原地改"')
    op.alter_column('chat_assistant_versions', 'split_version_id', new_column_name='entity_version_id')


def downgrade() -> None:
    op.alter_column('chat_assistant_versions', 'entity_version_id', new_column_name='split_version_id')
    op.execute('alter trigger "trg_entity_dict_versions_不可原地改" on entity_dict_versions rename to "trg_split_dict_versions_不可原地改"')
    for 旧, 新 in _索引:
        op.execute(f'alter index "{新}" rename to "{旧}"')
    for 表, 旧, 新 in _约束:
        op.execute(f'alter table {表} rename constraint "{新}" to "{旧}"')
    for 旧, 新 in reversed(_表):
        op.rename_table(新, 旧)
