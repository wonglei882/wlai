"""add shot retry fields

Revision ID: add_shot_retry
Revises: 9385218a2ea3
Create Date: 2026-09-13

添加镜头视觉重试相关字段：corrected_prompt, last_consistency_score
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_shot_retry'
down_revision = '9385218a2ea3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('comic_shots', sa.Column('corrected_prompt', sa.Text(), nullable=True,
                                           comment='修正后的提示词（视觉重试时注入）'))
    op.add_column('comic_shots', sa.Column('last_consistency_score', sa.Float(), nullable=True,
                                           comment='最近一次视觉一致性评分'))


def downgrade() -> None:
    op.drop_column('comic_shots', 'last_consistency_score')
    op.drop_column('comic_shots', 'corrected_prompt')
