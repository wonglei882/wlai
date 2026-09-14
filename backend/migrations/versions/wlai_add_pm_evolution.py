"""add pm evolution tables

Revision ID: wlai_add_pm_evolution
Revises: wlai_add_users
Create Date: 2026-09-14

新增 PM 自进化三层闭环持久化表：
- pm_evolution_state   进化状态（信号聚合 + 运行时阈值 + 维度节流）
- pm_exclusion_rule    用户驳回学习的噪声排除规则
- pm_evolution_event   进化事件日志
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'wlai_add_pm_evolution'
down_revision: Union[str, Sequence[str], None] = 'wlai_add_users'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pm_evolution_state',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('dimension', sa.String(50), nullable=False),
        sa.Column('signals_aggregated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_decisions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('hit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('fp_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('fix_rate', sa.Float(), server_default='0.5', nullable=True),
        sa.Column('fp_rate', sa.Float(), server_default='0', nullable=True),
        sa.Column('threshold_key', sa.String(50), nullable=True),
        sa.Column('threshold_value', sa.Float(), nullable=True),
        sa.Column('threshold_original', sa.Float(), nullable=True),
        sa.Column('threshold_min', sa.Float(), nullable=True),
        sa.Column('threshold_max', sa.Float(), nullable=True),
        sa.Column('confidence', sa.Float(), server_default='0.5', nullable=True),
        sa.Column('baseline_total_decisions', sa.Integer(), nullable=True),
        sa.Column('baseline_fp_rate', sa.Float(), nullable=True),
        sa.Column('baseline_fix_rate', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), server_default='stable', nullable=True),
        sa.Column('throttle_until', sa.DateTime(), nullable=True),
        sa.Column('consecutive_clean_rounds', sa.Integer(), server_default='0', nullable=True),
        sa.Column('last_evolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pm_evolution_state_project_id', 'pm_evolution_state', ['project_id'])
    op.create_index('idx_evolution_project_dimension', 'pm_evolution_state', ['project_id', 'dimension'])

    op.create_table(
        'pm_exclusion_rule',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('dimension', sa.String(50), nullable=False),
        sa.Column('rule_type', sa.String(30), nullable=True),
        sa.Column('rule_key', sa.String(200), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('source', sa.String(30), server_default='user_rejection', nullable=True),
        sa.Column('hits', sa.Integer(), server_default='0', nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pm_exclusion_rule_project_id', 'pm_exclusion_rule', ['project_id'])
    op.create_index('ix_pm_exclusion_rule_dimension', 'pm_exclusion_rule', ['dimension'])
    op.create_index('idx_exclusion_scope', 'pm_exclusion_rule', ['project_id', 'dimension'])

    op.create_table(
        'pm_evolution_event',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('dimension', sa.String(50), nullable=True),
        sa.Column('event_type', sa.String(30), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pm_evolution_event_project_id', 'pm_evolution_event', ['project_id'])
    op.create_index('ix_pm_evolution_event_dimension', 'pm_evolution_event', ['dimension'])
    op.create_index('ix_pm_evolution_event_created_at', 'pm_evolution_event', ['created_at'])
    op.create_index('idx_evolution_event_scope', 'pm_evolution_event', ['project_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('idx_evolution_event_scope', table_name='pm_evolution_event')
    op.drop_index('ix_pm_evolution_event_created_at', table_name='pm_evolution_event')
    op.drop_index('ix_pm_evolution_event_dimension', table_name='pm_evolution_event')
    op.drop_index('ix_pm_evolution_event_project_id', table_name='pm_evolution_event')
    op.drop_table('pm_evolution_event')
    op.drop_index('idx_exclusion_scope', table_name='pm_exclusion_rule')
    op.drop_index('ix_pm_exclusion_rule_dimension', table_name='pm_exclusion_rule')
    op.drop_index('ix_pm_exclusion_rule_project_id', table_name='pm_exclusion_rule')
    op.drop_table('pm_exclusion_rule')
    op.drop_index('idx_evolution_project_dimension', table_name='pm_evolution_state')
    op.drop_index('ix_pm_evolution_state_project_id', table_name='pm_evolution_state')
    op.drop_table('pm_evolution_state')
