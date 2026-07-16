"""add_operators_and_auth_relations

Revision ID: 9cb22dd7adfe
Revises: ab9fec45bd4e
Create Date: 2026-07-16 08:16:57.407415

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9cb22dd7adfe"
down_revision: str | Sequence[str] | None = "ab9fec45bd4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_operators_api_key_hash"), "operators", ["api_key_hash"], unique=True
    )
    op.create_index(
        op.f("ix_operators_username"), "operators", ["username"], unique=True
    )

    with op.batch_alter_table("approval_records") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_approval_records_operator_id",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_audit_events_operator_id",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("fk_audit_events_operator_id", type_="foreignkey")
        batch_op.drop_column("operator_id")

    with op.batch_alter_table("approval_records") as batch_op:
        batch_op.drop_constraint("fk_approval_records_operator_id", type_="foreignkey")
        batch_op.drop_column("operator_id")

    op.drop_index(op.f("ix_operators_username"), table_name="operators")
    op.drop_index(op.f("ix_operators_api_key_hash"), table_name="operators")
    op.drop_table("operators")
