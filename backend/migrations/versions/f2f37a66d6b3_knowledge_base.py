"""knowledge base

Revision ID: f2f37a66d6b3
Revises: 507d531376f7
Create Date: 2026-10-26 08:59:48.756116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f2f37a66d6b3'
down_revision: Union[str, Sequence[str], None] = '507d531376f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('kb_spaces',
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('team_id', sa.Uuid(), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(kind = 'org' AND team_id IS NULL AND project_id IS NULL) OR (kind = 'team' AND team_id IS NOT NULL AND project_id IS NULL) OR (kind = 'project' AND project_id IS NOT NULL AND team_id IS NULL)", name='kb_spaces_owner_check'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', name='kb_spaces_project_id_key'),
    sa.UniqueConstraint('team_id', name='kb_spaces_team_id_key')
    )
    op.create_index('ix_kb_spaces_org', 'kb_spaces', ['kind'], unique=True, postgresql_where=sa.text("kind = 'org'"))
    op.create_table('kb_folders',
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_id'], ['kb_folders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['space_id'], ['kb_spaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('space_id', 'parent_id', 'name', name='kb_folders_space_parent_name_key', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_kb_folders_space_id'), 'kb_folders', ['space_id'], unique=False)
    op.create_table('kb_documents',
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('folder_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body_md', sa.Text(), nullable=False),
    sa.Column('latest_revision', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('search_tsv', postgresql.TSVECTOR(), sa.Computed("setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || setweight(to_tsvector('simple'::regconfig, left(coalesce(body_md, ''), 100000)), 'B')", persisted=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['folder_id'], ['kb_folders.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['space_id'], ['kb_spaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('space_id', 'folder_id', 'title', name='kb_documents_space_folder_title_key', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_kb_documents_folder_id'), 'kb_documents', ['folder_id'], unique=False)
    op.create_index('ix_kb_documents_search_tsv', 'kb_documents', ['search_tsv'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_kb_documents_space_id'), 'kb_documents', ['space_id'], unique=False)
    op.create_table('kb_chunks',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
    sa.Column('embedding_model', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kb_chunks_document_id'), 'kb_chunks', ['document_id'], unique=False)
    op.create_table('kb_filings',
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'kind')
    )
    op.create_table('kb_links',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('target_task_id', sa.Uuid(), nullable=True),
    sa.Column('target_document_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('(target_task_id IS NULL) <> (target_document_id IS NULL)', name='kb_links_one_target_check'),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_document_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kb_links_document_id'), 'kb_links', ['document_id'], unique=False)
    op.create_index(op.f('ix_kb_links_target_document_id'), 'kb_links', ['target_document_id'], unique=False)
    op.create_index(op.f('ix_kb_links_target_task_id'), 'kb_links', ['target_task_id'], unique=False)
    op.create_table('kb_revisions',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body_md', sa.Text(), nullable=False),
    sa.Column('summary', sa.String(length=200), nullable=True),
    sa.Column('author_user_id', sa.Uuid(), nullable=True),
    sa.Column('author_agent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['author_agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['document_id'], ['kb_documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'revision', name='kb_revisions_document_id_revision_key')
    )
    # backfill: one org space, one space per existing team and project
    op.execute("INSERT INTO kb_spaces (id, kind) VALUES (gen_random_uuid(), 'org')")
    op.execute("INSERT INTO kb_spaces (id, kind, team_id) SELECT gen_random_uuid(), 'team', id FROM teams")
    op.execute("INSERT INTO kb_spaces (id, kind, project_id) SELECT gen_random_uuid(), 'project', id FROM projects")


def downgrade() -> None:
    """Downgrade schema. The vector extension stays installed."""
    op.drop_table('kb_revisions')
    op.drop_index(op.f('ix_kb_links_target_task_id'), table_name='kb_links')
    op.drop_index(op.f('ix_kb_links_target_document_id'), table_name='kb_links')
    op.drop_index(op.f('ix_kb_links_document_id'), table_name='kb_links')
    op.drop_table('kb_links')
    op.drop_table('kb_filings')
    op.drop_index(op.f('ix_kb_chunks_document_id'), table_name='kb_chunks')
    op.drop_table('kb_chunks')
    op.drop_index(op.f('ix_kb_documents_space_id'), table_name='kb_documents')
    op.drop_index('ix_kb_documents_search_tsv', table_name='kb_documents', postgresql_using='gin')
    op.drop_index(op.f('ix_kb_documents_folder_id'), table_name='kb_documents')
    op.drop_table('kb_documents')
    op.drop_index(op.f('ix_kb_folders_space_id'), table_name='kb_folders')
    op.drop_table('kb_folders')
    op.drop_index('ix_kb_spaces_org', table_name='kb_spaces', postgresql_where=sa.text("kind = 'org'"))
    op.drop_table('kb_spaces')
