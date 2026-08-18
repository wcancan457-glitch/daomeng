"""Add durable queue status columns to pipeline tasks."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0002"
down_revision: Union[str, None] = "20260818_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("task_ownership")}
    with op.batch_alter_table("task_ownership") as batch_op:
        if "status" not in columns:
            batch_op.add_column(
                sa.Column("status", sa.String(length=24), nullable=False, server_default="pending")
            )
        if "updated_at" not in columns:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )

    task_table = sa.table(
        "task_ownership",
        sa.column("task_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("payload", sa.JSON()),
    )
    connection = op.get_bind()
    for row in connection.execute(sa.select(task_table.c.task_id, task_table.c.payload)).mappings():
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        connection.execute(
            task_table.update()
            .where(task_table.c.task_id == row["task_id"])
            .values(status=str(payload.get("status") or "pending"))
        )

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("task_ownership")}
    if "ix_task_ownership_status" not in indexes:
        op.create_index("ix_task_ownership_status", "task_ownership", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_ownership_status", table_name="task_ownership")
    with op.batch_alter_table("task_ownership") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("status")
