"""Initial schema."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    locker_state = sa.Enum(
        "idle",
        "arming",
        "running",
        "ending",
        "completed",
        "start_failed",
        "degraded_locked",
        "restore_failed_locked",
        name="lockerstate",
    )
    locker_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_string_session", sa.Text(), nullable=False),
        sa.Column("encrypted_baseline_password", sa.Text(), nullable=False),
        sa.Column("admin_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("current_state", locker_state, nullable=False, server_default="idle"),
        sa.Column("default_duration_seconds", sa.Integer(), nullable=False, server_default="14400"),
        sa.Column("pending_command_kind", sa.String(length=32), nullable=True),
        sa.Column("pending_command_payload", sa.JSON(), nullable=True),
        sa.Column("pending_command_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_password_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("telegram_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "detox_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state", locker_state, nullable=False),
        sa.Column("requested_by_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encrypted_current_detox_password", sa.Text(), nullable=True),
        sa.Column("start_reason", sa.String(length=64), nullable=False),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("last_restore_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_detox_runs_state", "detox_runs", ["state"], unique=False)

    op.create_table(
        "authorizations_seen",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("detox_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("authorization_hash", sa.BigInteger(), nullable=False),
        sa.Column("device", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "authorization_hash", name="uq_run_authorization_hash"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("detox_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("authorizations_seen")
    op.drop_index("ix_detox_runs_state", table_name="detox_runs")
    op.drop_table("detox_runs")
    op.drop_table("settings")
    locker_state = sa.Enum(name="lockerstate")
    locker_state.drop(op.get_bind(), checkfirst=True)
