"""create new tables

Revision ID: 44ac4fa6b4d9
Revises: c9f847550338
Create Date: 2025-09-06 19:53:31.951412

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44ac4fa6b4d9"
down_revision: str | Sequence[str] | None = "c9f847550338"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    bind = op.get_bind()

    # 1) Enums
    appt_status_enum = sa.Enum(
        "SCHEDULED", "CONFIRMED", "CANCELLED", "DONE", name="appointment_status_enum"
    )
    appt_status_enum.create(bind, checkfirst=True)

    # 2) users
    op.add_column(
        "users",
        sa.Column("name", sa.String(length=120), nullable=False),
    )

    # 3) professionals
    op.create_table(
        "professionals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("speciality", sa.String(length=120), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # 4) students
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "guardian_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_students_guardian", "students", ["guardian_user_id"])

    # 5) appointments
    op.drop_column(
        "appointments",
        "family_id",
    )
    op.add_column(
        "appointments",
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    op.alter_column(
        "appointments",
        "start_at",
        new_column_name="starts_at",
    )
    op.alter_column(
        "appointments",
        "end_at",
        new_column_name="ends_at",
    )
    op.alter_column(
        "appointments",
        "status",
        existing_type=appt_status_enum,
        server_default=sa.text("'SCHEDULED'"),
    )
    op.create_check_constraint(
        "ck_appt_time_order", "appointments", "ends_at > starts_at"
    )
    op.create_unique_constraint(
        "uq_appt_prof_start", "appointments", ["professional_id", "starts_at"]
    )
    op.create_index("ix_appt_starts_at", "appointments", ["starts_at"])
    op.create_index("ix_appt_professional_id", "appointments", ["professional_id"])
    op.create_index("ix_appt_student_id", "appointments", ["student_id"])

    # 6) availability (composta)
    op.create_table(
        "availability",
        sa.Column(
            "professional_id",
            sa.Integer(),
            sa.ForeignKey("professionals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("starts_utc", sa.Time(), nullable=False),
        sa.Column("ends_utc", sa.Time(), nullable=False),
        sa.CheckConstraint(
            "weekday >= 0 AND weekday <= 6", name="ck_availability_weekday"
        ),
        sa.CheckConstraint("ends_utc > starts_utc", name="ck_availability_time_order"),
        sa.PrimaryKeyConstraint(
            "professional_id", "weekday", "starts_utc", name="pk_availability"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    # 7) audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "timestamp_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
    )
    op.create_index("ix_audit_timestamp_utc", "audit_logs", ["timestamp_utc"])
    op.create_index("ix_audit_user_id", "audit_logs", ["user_id"])


def downgrade():
    # drop order: dependentes -> bases; índices caem junto com a tabela se não nomeados externamente
    op.drop_index("ix_audit_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_timestamp_utc", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_table("availability")

    op.drop_index("ix_appt_student_id", table_name="appointments")
    op.drop_index("ix_appt_professional_id", table_name="appointments")
    op.drop_index("ix_appt_starts_at", table_name="appointments")
    op.drop_table("appointments")

    op.drop_index("ix_students_guardian", table_name="students")
    op.drop_table("students")

    op.drop_table("professionals")

    op.drop_column(
        "users",
        "name",
    )

    # appointments
    op.add_column(
        "appointments",
        sa.Column(
            "family_id",
            sa.Integer(),
            nullable=False,
        ),
    )
    op.drop_column(
        "appointments",
        "student_id",
    )
    op.alter_column(
        "appointments",
        "starts_at",
        new_column_name="start_at",
    )
    op.alter_column(
        "appointments",
        "ends_at",
        new_column_name="end_at",
    )
    op.drop_constraint("ck_appt_time_order", "appointments")
    op.drop_constraint("uq_appt_prof_start", "appointments")
    op.drop_index("ix_appt_starts_at", "appointments")
    op.drop_index("ix_appt_professional_id", "appointments")
    op.drop_index("ix_appt_student_id", "appointments")

    # enums por último
    bind = op.get_bind()
    sa.Enum(name="appointment_status_enum").drop(bind, checkfirst=True)
