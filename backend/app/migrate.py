"""Lightweight schema migration utility.

Run with:
    python -m app.migrate

This script is intentionally idempotent and focuses on additive schema
changes so local databases can be upgraded without reseeding.
"""

import asyncio

from sqlalchemy import inspect, text

from app.db import engine


def _table_exists(sync_conn, table_name: str) -> bool:
    inspector = inspect(sync_conn)
    return table_name in inspector.get_table_names()


def _column_exists(sync_conn, table_name: str, column_name: str) -> bool:
    inspector = inspect(sync_conn)
    if table_name not in inspector.get_table_names():
        return False
    columns = inspector.get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


async def migrate() -> None:
    async with engine.begin() as conn:
        dialect = conn.dialect.name

        columns_to_add = [
            ("time_entries", "last_edit_reason", "TEXT"),
            ("time_entries", "last_history_summary", "TEXT"),
            ("time_entries", "created_by", "INTEGER"),
            ("time_entries", "updated_by", "INTEGER"),
            ("time_entries", "task_id", "INTEGER"),
            ("time_entries", "is_billable", "BOOLEAN DEFAULT TRUE"),
            ("time_entries", "ingestion_timesheet_id", "VARCHAR(36)"),
            ("time_entries", "ingestion_line_item_id", "VARCHAR(36)"),
            ("time_entries", "ingestion_approved_by_name", "VARCHAR(255)"),
            ("time_entries", "ingestion_source_tenant", "VARCHAR(255)"),
            ("projects", "code", "VARCHAR(80)"),
            ("projects", "description", "TEXT"),
            ("projects", "start_date", "DATE"),
            ("projects", "end_date", "DATE"),
            ("projects", "estimated_hours", "NUMERIC(10,2)"),
            ("projects", "budget_amount", "NUMERIC(12,2)"),
            ("projects", "currency", "VARCHAR(10)"),
            ("projects", "is_active", "BOOLEAN DEFAULT TRUE"),
            ("projects", "ingestion_project_id", "VARCHAR(36)"),
            ("users", "title", "VARCHAR(255)"),
            ("users", "department", "VARCHAR(255)"),
            ("users", "ingestion_employee_id", "VARCHAR(36)"),
            ("users", "ingestion_created_by", "VARCHAR(255)"),
            ("clients", "ingestion_client_id", "VARCHAR(36)"),
            ("time_off_requests", "created_by", "INTEGER"),
            ("time_off_requests", "updated_by", "INTEGER"),
        ]

        for table_name, column_name, column_type in columns_to_add:
            exists = await conn.run_sync(_column_exists, table_name, column_name)
            if exists:
                continue

            if dialect == "postgresql":
                await conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                    )
                )
            else:
                await conn.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    )
                )

        history_exists = await conn.run_sync(
            _table_exists, "time_entry_edit_history")
        if not history_exists:
            if dialect == "postgresql":
                await conn.execute(
                    text(
                        """
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
                        """
                    )
                )
            else:
                await conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS time_entry_edit_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            time_entry_id INTEGER NOT NULL,
                            edited_by INTEGER NOT NULL,
                            edited_at TIMESTAMP NOT NULL,
                            edit_reason TEXT NOT NULL,
                            history_summary TEXT NOT NULL,
                            previous_project_id INTEGER NOT NULL,
                            previous_entry_date DATE NOT NULL,
                            previous_hours NUMERIC(5,2) NOT NULL,
                            previous_description TEXT NOT NULL,
                            FOREIGN KEY(time_entry_id) REFERENCES time_entries(id),
                            FOREIGN KEY(edited_by) REFERENCES users(id),
                            FOREIGN KEY(previous_project_id) REFERENCES projects(id)
                        )
                        """
                    )
                )

        for index_sql in [
            "CREATE INDEX IF NOT EXISTS idx_time_entry_edit_history_time_entry_id ON time_entry_edit_history(time_entry_id)",
            "CREATE INDEX IF NOT EXISTS idx_time_entry_edit_history_edited_by ON time_entry_edit_history(edited_by)",
            "CREATE INDEX IF NOT EXISTS idx_time_entries_task_id ON time_entries(task_id)",
            "CREATE INDEX IF NOT EXISTS ix_time_entries_ingestion_timesheet_id ON time_entries(ingestion_timesheet_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_time_entries_ingestion_line_item_id ON time_entries(ingestion_line_item_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_ingestion_employee_id ON users(ingestion_employee_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_clients_ingestion_client_id ON clients(ingestion_client_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_ingestion_project_id ON projects(ingestion_project_id)",
        ]:
            await conn.execute(text(index_sql))

        tasks_exists = await conn.run_sync(_table_exists, "tasks")
        if not tasks_exists:
            if dialect == "postgresql":
                await conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS tasks (
                            id BIGSERIAL PRIMARY KEY,
                            project_id INTEGER NOT NULL REFERENCES projects(id),
                            name VARCHAR(255) NOT NULL,
                            code VARCHAR(80),
                            description TEXT,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                )
            else:
                await conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS tasks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            project_id INTEGER NOT NULL,
                            name VARCHAR(255) NOT NULL,
                            code VARCHAR(80),
                            description TEXT,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY(project_id) REFERENCES projects(id)
                        )
                        """
                    )
                )

        for task_index_sql in [
            "CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_is_active ON tasks(is_active)",
        ]:
            await conn.execute(text(task_index_sql))

    print("[OK] Migration completed")


if __name__ == "__main__":
    asyncio.run(migrate())
