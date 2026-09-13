"""add comic production + consistency agent tables

Revision ID: a1b2c3d4e5f6
Revises: 9385218a2ea3
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9385218a2ea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === content_segments ===
    op.create_table('content_segments',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(500)),
        sa.Column('content', sa.Text()),
        sa.Column('metadata_json', postgresql.JSON()),
        sa.Column('parent_id', sa.String(36)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['content_segments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_content_segments_project_id', 'content_segments', ['project_id'])
    op.create_index('ix_content_segments_user_id', 'content_segments', ['user_id'])
    op.create_index('ix_content_segments_content_type', 'content_segments', ['content_type'])

    # === comic_panels ===
    op.create_table('comic_panels',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('panel_number', sa.Integer(), nullable=False),
        sa.Column('global_sequence', sa.Integer()),
        sa.Column('scene_description', sa.Text()),
        sa.Column('camera_angle', sa.String(50)),
        sa.Column('transition_type', sa.String(50)),
        sa.Column('characters_visual', postgresql.JSON()),
        sa.Column('dialogue', postgresql.JSON()),
        sa.Column('scene_metadata', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_panels_project_id', 'comic_panels', ['project_id'])
    op.create_index('ix_comic_panels_user_id', 'comic_panels', ['user_id'])
    op.create_index('ix_comic_panels_global_sequence', 'comic_panels', ['global_sequence'])

    # === visual_references ===
    op.create_table('visual_references',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('character_name', sa.String(200), nullable=False),
        sa.Column('canonical_appearance', postgresql.JSON()),
        sa.Column('expression_variants', postgresql.JSON()),
        sa.Column('outfit_variants', postgresql.JSON()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_visual_references_project_id', 'visual_references', ['project_id'])

    # === webhook_configs ===
    op.create_table('webhook_configs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('url', sa.String(2000), nullable=False),
        sa.Column('events', postgresql.JSON(), nullable=False),
        sa.Column('secret', sa.String(200), nullable=False),
        sa.Column('is_active', sa.Boolean()),
        sa.Column('last_triggered_at', sa.DateTime()),
        sa.Column('last_status', sa.String(20)),
        sa.Column('description', sa.Text()),
        sa.Column('metadata_json', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhook_configs_project_id', 'webhook_configs', ['project_id'])
    op.create_index('ix_webhook_configs_user_id', 'webhook_configs', ['user_id'])

    # === setting_bibles ===
    op.create_table('setting_bibles',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('world_name', sa.String(200), nullable=False),
        sa.Column('summary', sa.Text()),
        sa.Column('time_period', sa.String(100)),
        sa.Column('location_rules', postgresql.JSON()),
        sa.Column('magic_system', postgresql.JSON()),
        sa.Column('tone', sa.String(100)),
        sa.Column('extra', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_setting_bibles_project_id', 'setting_bibles', ['project_id'])
    op.create_index('ix_setting_bibles_user_id', 'setting_bibles', ['user_id'])

    # === character_cards ===
    op.create_table('character_cards',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('bible_id', sa.String(36)),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('age', sa.String(50)),
        sa.Column('gender', sa.String(20)),
        sa.Column('hair', sa.String(200)),
        sa.Column('eyes', sa.String(100)),
        sa.Column('outfit', sa.String(500)),
        sa.Column('accessories', postgresql.JSON()),
        sa.Column('personality', sa.Text()),
        sa.Column('catchphrase', sa.String(200)),
        sa.Column('voice_timbre', sa.String(200)),
        sa.Column('appearance_prompt', sa.Text()),
        sa.Column('reference_images', postgresql.JSON()),
        sa.Column('negative_traits', postgresql.JSON()),
        sa.Column('status', sa.String(20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bible_id'], ['setting_bibles.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_character_cards_project_id', 'character_cards', ['project_id'])
    op.create_index('ix_character_cards_user_id', 'character_cards', ['user_id'])

    # === art_style_cards ===
    op.create_table('art_style_cards',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('style_name', sa.String(100), nullable=False),
        sa.Column('color_palette', postgresql.JSON()),
        sa.Column('line_style', sa.String(100)),
        sa.Column('lighting', sa.String(100)),
        sa.Column('base_prompt', sa.Text()),
        sa.Column('negative_prompt', sa.Text()),
        sa.Column('seed', sa.Integer()),
        sa.Column('reference_images', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_art_style_cards_project_id', 'art_style_cards', ['project_id'])

    # === negative_prompt_libraries ===
    op.create_table('negative_prompt_libraries',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('prompts', postgresql.JSON()),
        sa.Column('description', sa.String(500)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_negative_prompt_libraries_project_id', 'negative_prompt_libraries', ['project_id'])

    # === comic_episodes ===
    op.create_table('comic_episodes',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('episode_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200)),
        sa.Column('summary', sa.Text()),
        sa.Column('next_hook', sa.Text()),
        sa.Column('status', sa.String(20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_episodes_project_id', 'comic_episodes', ['project_id'])
    op.create_index('ix_comic_episodes_user_id', 'comic_episodes', ['user_id'])

    # === comic_storyboards ===
    op.create_table('comic_storyboards',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('episode_id', sa.String(36)),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('title', sa.String(200)),
        sa.Column('source_text', sa.Text()),
        sa.Column('shot_count', sa.Integer()),
        sa.Column('status', sa.String(20)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['comic_episodes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_storyboards_project_id', 'comic_storyboards', ['project_id'])
    op.create_index('ix_comic_storyboards_user_id', 'comic_storyboards', ['user_id'])

    # === comic_shots ===
    op.create_table('comic_shots',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('storyboard_id', sa.String(36), nullable=False),
        sa.Column('episode_id', sa.String(36)),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('shot_number', sa.Integer(), nullable=False),
        sa.Column('duration', sa.Float()),
        sa.Column('scene_type', sa.String(50)),
        sa.Column('visual_description', sa.Text()),
        sa.Column('character_action', sa.Text()),
        sa.Column('dialogue', sa.String(100)),
        sa.Column('sound_effect', sa.String(200)),
        sa.Column('camera_movement', sa.String(100)),
        sa.Column('status', sa.String(30)),
        sa.Column('compiled_prompt', sa.Text()),
        sa.Column('negative_prompt', sa.Text()),
        sa.Column('seed', sa.Integer()),
        sa.Column('retry_count', sa.Integer()),
        sa.Column('metadata_json', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['storyboard_id'], ['comic_storyboards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['comic_episodes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_shots_project_id', 'comic_shots', ['project_id'])
    op.create_index('ix_comic_shots_storyboard_id', 'comic_shots', ['storyboard_id'])

    # === comic_shot_assets ===
    op.create_table('comic_shot_assets',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('shot_id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer()),
        sa.Column('file_url', sa.String(2000)),
        sa.Column('prompt_used', sa.Text()),
        sa.Column('parameters', postgresql.JSON()),
        sa.Column('status', sa.String(20)),
        sa.Column('qc_result', postgresql.JSON()),
        sa.Column('naming', sa.String(500)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['shot_id'], ['comic_shots.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_shot_assets_shot_id', 'comic_shot_assets', ['shot_id'])
    op.create_index('ix_comic_shot_assets_project_id', 'comic_shot_assets', ['project_id'])

    # === comic_review_checkpoints ===
    op.create_table('comic_review_checkpoints',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('review_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('reviewer_notes', sa.Text()),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('reviewed_by', sa.String(100)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comic_review_checkpoints_project_id', 'comic_review_checkpoints', ['project_id'])
    op.create_index('ix_comic_review_checkpoints_user_id', 'comic_review_checkpoints', ['user_id'])
    op.create_index('ix_comic_review_checkpoints_target_id', 'comic_review_checkpoints', ['target_id'])

    # === async_tasks ===
    op.create_table('async_tasks',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(100), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('progress', sa.Float()),
        sa.Column('result', postgresql.JSON()),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_async_tasks_project_id', 'async_tasks', ['project_id'])
    op.create_index('ix_async_tasks_user_id', 'async_tasks', ['user_id'])
    op.create_index('ix_async_tasks_status', 'async_tasks', ['status'])


def downgrade() -> None:
    op.drop_table('async_tasks')
    op.drop_index('ix_comic_review_checkpoints_target_id', 'comic_review_checkpoints')
    op.drop_index('ix_comic_review_checkpoints_user_id', 'comic_review_checkpoints')
    op.drop_index('ix_comic_review_checkpoints_project_id', 'comic_review_checkpoints')
    op.drop_table('comic_review_checkpoints')
    op.drop_index('ix_comic_shot_assets_project_id', 'comic_shot_assets')
    op.drop_index('ix_comic_shot_assets_shot_id', 'comic_shot_assets')
    op.drop_table('comic_shot_assets')
    op.drop_index('ix_comic_shots_storyboard_id', 'comic_shots')
    op.drop_index('ix_comic_shots_project_id', 'comic_shots')
    op.drop_table('comic_shots')
    op.drop_index('ix_comic_storyboards_user_id', 'comic_storyboards')
    op.drop_index('ix_comic_storyboards_project_id', 'comic_storyboards')
    op.drop_table('comic_storyboards')
    op.drop_index('ix_comic_episodes_user_id', 'comic_episodes')
    op.drop_index('ix_comic_episodes_project_id', 'comic_episodes')
    op.drop_table('comic_episodes')
    op.drop_index('ix_negative_prompt_libraries_project_id', 'negative_prompt_libraries')
    op.drop_table('negative_prompt_libraries')
    op.drop_index('ix_art_style_cards_project_id', 'art_style_cards')
    op.drop_table('art_style_cards')
    op.drop_index('ix_character_cards_user_id', 'character_cards')
    op.drop_index('ix_character_cards_project_id', 'character_cards')
    op.drop_table('character_cards')
    op.drop_index('ix_setting_bibles_user_id', 'setting_bibles')
    op.drop_index('ix_setting_bibles_project_id', 'setting_bibles')
    op.drop_table('setting_bibles')
    op.drop_index('ix_webhook_configs_user_id', 'webhook_configs')
    op.drop_index('ix_webhook_configs_project_id', 'webhook_configs')
    op.drop_table('webhook_configs')
    op.drop_index('ix_visual_references_project_id', 'visual_references')
    op.drop_table('visual_references')
    op.drop_index('ix_comic_panels_global_sequence', 'comic_panels')
    op.drop_index('ix_comic_panels_user_id', 'comic_panels')
    op.drop_index('ix_comic_panels_project_id', 'comic_panels')
    op.drop_table('comic_panels')
    op.drop_index('ix_content_segments_content_type', 'content_segments')
    op.drop_index('ix_content_segments_user_id', 'content_segments')
    op.drop_index('ix_content_segments_project_id', 'content_segments')
    op.drop_table('content_segments')
