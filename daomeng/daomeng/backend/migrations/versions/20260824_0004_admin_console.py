"""Add test-user quotas and administrator audit logs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0004"
down_revision: Union[str, None] = "20260818_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "daily_llm_limit" not in user_columns:
            batch_op.add_column(
                sa.Column("daily_llm_limit", sa.Integer(), nullable=False, server_default="100")
            )
        if "daily_image_limit" not in user_columns:
            batch_op.add_column(
                sa.Column("daily_image_limit", sa.Integer(), nullable=False, server_default="10")
            )
        if "daily_video_limit" not in user_columns:
            batch_op.add_column(
                sa.Column("daily_video_limit", sa.Integer(), nullable=False, server_default="2")
            )

    if "admin_audit_logs" not in inspector.get_table_names():
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=False),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("target_type", sa.String(length=40), nullable=False),
            sa.Column("target_id", sa.String(length=120), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_admin_audit_logs_actor_id", "admin_audit_logs", ["actor_id"])
        op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
        op.create_index("ix_admin_audit_logs_target_type", "admin_audit_logs", ["target_type"])
        op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("daily_video_limit")
        batch_op.drop_column("daily_image_limit")
        batch_op.drop_column("daily_llm_limit")
