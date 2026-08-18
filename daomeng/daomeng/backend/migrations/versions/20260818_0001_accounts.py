"""Create user accounts, sessions, and ownership tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("normalized_email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("display_name", sa.String(length=80), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("email_verified", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("normalized_email"),
        )
    _create_index_if_missing(
        "users", "ix_users_normalized_email", ["normalized_email"], unique=True
    )
    _create_index_if_missing("users", "ix_users_role", ["role"])

    if "auth_sessions" not in existing_tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("refresh_token_hash"),
        )
    _create_index_if_missing("auth_sessions", "ix_auth_sessions_expires_at", ["expires_at"])
    _create_index_if_missing(
        "auth_sessions", "ix_auth_sessions_refresh_token_hash", ["refresh_token_hash"], unique=True
    )
    _create_index_if_missing("auth_sessions", "ix_auth_sessions_user_id", ["user_id"])

    if "project_ownership" not in existing_tables:
        op.create_table(
            "project_ownership",
            sa.Column("project_id", sa.String(length=80), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("project_id"),
        )
    _create_index_if_missing("project_ownership", "ix_project_ownership_user_id", ["user_id"])

    if "task_ownership" not in existing_tables:
        op.create_table(
            "task_ownership",
            sa.Column("task_id", sa.String(length=80), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("task_kind", sa.String(length=24), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("task_id"),
        )
    _create_index_if_missing(
        "task_ownership", "ix_task_ownership_user_kind", ["user_id", "task_kind"]
    )
    _create_index_if_missing("task_ownership", "ix_task_ownership_user_id", ["user_id"])


def _create_index_if_missing(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=unique)


def downgrade() -> None:
    op.drop_index("ix_task_ownership_user_id", table_name="task_ownership")
    op.drop_index("ix_task_ownership_user_kind", table_name="task_ownership")
    op.drop_table("task_ownership")
    op.drop_index("ix_project_ownership_user_id", table_name="project_ownership")
    op.drop_table("project_ownership")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_refresh_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_normalized_email", table_name="users")
    op.drop_table("users")
