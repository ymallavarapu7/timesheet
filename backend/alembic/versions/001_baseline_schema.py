"""Baseline schema — captures the full pre-multitenancy state.

For an EXISTING (production) database that was bootstrapped via
SQLAlchemy's create_all, mark this migration as already applied WITHOUT
running it:

    cd backend
    alembic stamp 001_baseline_schema

For a FRESH database, run all migrations normally:

    alembic upgrade head

Revision ID: 001_baseline_schema
Revises:
Create Date: 2026-03-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_baseline_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE userrole AS ENUM (
                'EMPLOYEE', 'MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE timeentrystatus AS ENUM (
                'DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE timeofftype AS ENUM (
                'SICK_DAY', 'PTO', 'HALF_DAY', 'HOURLY_PERMISSION', 'OTHER_LEAVE'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE timeoffstatus AS ENUM (
                'DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ── users ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            username VARCHAR(255) NOT NULL UNIQUE,
            full_name VARCHAR(255) NOT NULL,
            title VARCHAR(255),
            department VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            has_changed_password BOOLEAN NOT NULL DEFAULT FALSE,
            role userrole NOT NULL DEFAULT 'EMPLOYEE',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)")

    # ── clients ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            quickbooks_customer_id VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)

    # ── projects ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            client_id INTEGER NOT NULL REFERENCES clients(id),
            billable_rate NUMERIC(10,2) NOT NULL,
            quickbooks_project_id VARCHAR(255),
            code VARCHAR(80),
            description TEXT,
            start_date DATE,
            end_date DATE,
            estimated_hours NUMERIC(10,2),
            budget_amount NUMERIC(12,2),
            currency VARCHAR(10),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_client_id ON projects (client_id)")

    # ── tasks ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name VARCHAR(255) NOT NULL,
            code VARCHAR(80),
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_project_id ON tasks (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_is_active ON tasks (is_active)")

    # ── time_entries ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS time_entries (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            task_id INTEGER REFERENCES tasks(id),
            entry_date DATE NOT NULL,
            hours NUMERIC(5,2) NOT NULL,
            description TEXT NOT NULL,
            is_billable BOOLEAN NOT NULL DEFAULT TRUE,
            status timeentrystatus NOT NULL DEFAULT 'DRAFT',
            submitted_at TIMESTAMP WITH TIME ZONE,
            approved_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMP WITH TIME ZONE,
            rejection_reason TEXT,
            created_by INTEGER REFERENCES users(id),
            updated_by INTEGER REFERENCES users(id),
            last_edit_reason TEXT,
            last_history_summary TEXT,
            quickbooks_time_activity_id VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_entries_user_id ON time_entries (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_entries_project_id ON time_entries (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_entries_task_id ON time_entries (task_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_entries_entry_date ON time_entries (entry_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_entries_status ON time_entries (status)")

    # ── time_entry_edit_history ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS time_entry_edit_history (
            id BIGSERIAL PRIMARY KEY,
            time_entry_id INTEGER NOT NULL REFERENCES time_entries(id),
            edited_by INTEGER NOT NULL REFERENCES users(id),
            edited_at TIMESTAMP WITH TIME ZONE NOT NULL,
            edit_reason TEXT NOT NULL,
            history_summary TEXT NOT NULL,
            previous_project_id INTEGER NOT NULL REFERENCES projects(id),
            previous_entry_date DATE NOT NULL,
            previous_hours NUMERIC(5,2) NOT NULL,
            previous_description TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_time_entry_edit_history_time_entry_id ON time_entry_edit_history (time_entry_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_time_entry_edit_history_edited_by ON time_entry_edit_history (edited_by)")

    # ── time_off_requests ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS time_off_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_date DATE NOT NULL,
            hours NUMERIC(5,2) NOT NULL,
            leave_type timeofftype NOT NULL,
            reason TEXT NOT NULL,
            status timeoffstatus NOT NULL DEFAULT 'DRAFT',
            submitted_at TIMESTAMP WITH TIME ZONE,
            approved_by INTEGER REFERENCES users(id),
            created_by INTEGER REFERENCES users(id),
            updated_by INTEGER REFERENCES users(id),
            approved_at TIMESTAMP WITH TIME ZONE,
            rejection_reason TEXT,
            external_reference VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_off_requests_user_id ON time_off_requests (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_off_requests_request_date ON time_off_requests (request_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_off_requests_leave_type ON time_off_requests (leave_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_time_off_requests_status ON time_off_requests (status)")

    # ── employee_manager_assignments ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_manager_assignments (
            employee_id INTEGER NOT NULL REFERENCES users(id),
            manager_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_employee_manager_assignments_manager_id ON employee_manager_assignments (manager_id)")

    # ── user_project_access ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_project_access (
            user_id INTEGER NOT NULL REFERENCES users(id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, project_id)
        )
    """)

    # ── user_notification_states ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_notification_states (
            user_id INTEGER NOT NULL REFERENCES users(id),
            notification_id VARCHAR(120) NOT NULL,
            last_read_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (user_id, notification_id)
        )
    """)

    # ── user_notification_dismissals ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_notification_dismissals (
            user_id INTEGER NOT NULL REFERENCES users(id),
            notification_id VARCHAR(120) NOT NULL,
            deleted_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (user_id, notification_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_notification_dismissals")
    op.execute("DROP TABLE IF EXISTS user_notification_states")
    op.execute("DROP TABLE IF EXISTS user_project_access")
    op.execute("DROP TABLE IF EXISTS employee_manager_assignments")
    op.execute("DROP TABLE IF EXISTS time_off_requests")
    op.execute("DROP TABLE IF EXISTS time_entry_edit_history")
    op.execute("DROP TABLE IF EXISTS time_entries")
    op.execute("DROP TABLE IF EXISTS tasks")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS clients")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TYPE IF EXISTS timeoffstatus")
    op.execute("DROP TYPE IF EXISTS timeofftype")
    op.execute("DROP TYPE IF EXISTS timeentrystatus")
    op.execute("DROP TYPE IF EXISTS userrole")
