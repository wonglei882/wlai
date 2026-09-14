"""add comic consistency snapshot table

Revision ID: wlai_add_pm_consistency_state_comic
Revises: wlai_add_pm_evolution
Create Date: 2026-09-14

新增漫剧一致性状态快照表（P1-1）：
- pm_consistency_state_comic  镜头门控通过后自动写入的状态快照
  （角色视觉/场景/镜头/前向衔接/后向一致性评分/全局序列）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'wlai_add_pm_consistency_state_comic'
down_revision: Union[str, Sequence[str], None] = 'wlai_add_pm_evolution'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pm_consistency_state_comic',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('episode_id', sa.String(36), nullable=True),
        sa.Column('shot_id', sa.String(36), nullable=False),
        sa.Column('shot_number', sa.Integer(), nullable=False, comment='镜号'),
        sa.Column('character_visual_states', sa.JSON(), nullable=False, comment='镜头内角色的定稿外貌'),
        sa.Column('scene_state', sa.JSON(), nullable=False, comment='场景类型/画面描述'),
        sa.Column('camera_state', sa.JSON(), nullable=False, comment='镜头运动/景别状态'),
        sa.Column('forward', sa.JSON(), nullable=False, comment='前向一致性（与前一镜衔接）'),
        sa.Column('backward_consistency_score', sa.Float(), nullable=True, comment='后向视觉一致性评分'),
        sa.Column('global_sequence', sa.Integer(), nullable=True, comment='镜头的全局序列号'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False, comment='快照创建时间'),
        sa.ForeignKeyConstraint(['episode_id'], ['comic_episodes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shot_id'], ['comic_shots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'shot_id', name='uq_pm_consistency_comic_project_shot'),
    )
    op.create_index('ix_pm_consistency_state_comic_project_id', 'pm_consistency_state_comic', ['project_id'])
    op.create_index('ix_pm_consistency_state_comic_shot_id', 'pm_consistency_state_comic', ['shot_id'])


def downgrade() -> None:
    op.drop_index('ix_pm_consistency_state_comic_shot_id', table_name='pm_consistency_state_comic')
    op.drop_index('ix_pm_consistency_state_comic_project_id', table_name='pm_consistency_state_comic')
    op.drop_table('pm_consistency_state_comic')