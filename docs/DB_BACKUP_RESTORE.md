# PostgreSQL Backup & Restore Guide

This guide explains how to back up the Timesheet database and restore it on another machine.

## Scope

- Source DB: `timesheet_db`
- Source user: `timesheet_user`
- Local default host/port: `localhost:5432`
- Dump format: PostgreSQL custom dump (`.dump`)

## Prerequisites

- PostgreSQL client tools installed on both machines (`pg_dump`, `pg_restore`, `psql`, `createdb`).
- Client major version should match server major version.
  - Example: if server is PostgreSQL 15, use PostgreSQL 15 `pg_dump/pg_restore`.

## 1) Create a Backup (Source Machine)

From project root:

```bash
cd /Users/bharat/Desktop/Timesheet
mkdir -p backups
PGPASSWORD='timesheet_pass' /opt/homebrew/opt/postgresql@15/bin/pg_dump \
  -h localhost -p 5432 -U timesheet_user -d timesheet_db \
  -Fc -f backups/timesheet_db_$(date +%Y%m%d_%H%M%S).dump
```

## 2) Validate the Dump

```bash
cd /Users/bharat/Desktop/Timesheet
latest_dump=$(ls -t backups/timesheet_db_*.dump | head -n 1)
/opt/homebrew/opt/postgresql@15/bin/pg_restore -l "$latest_dump" | head -n 20
```

If you see TOC output (table/type entries), the dump is valid.

## 3) Transfer Dump to Target Machine

Copy the `.dump` file using `scp`, USB, cloud drive, etc.

Example:

```bash
scp backups/timesheet_db_20260317_205701.dump user@target-host:/tmp/
```

## 4) Restore on Target Machine

Create target DB first:

```bash
createdb -h localhost -p 5432 -U timesheet_user timesheet_db
```

Restore:

```bash
PGPASSWORD='timesheet_pass' pg_restore \
  -h localhost -p 5432 -U timesheet_user \
  -d timesheet_db --clean --if-exists --no-owner \
  /tmp/timesheet_db_20260317_205701.dump
```

## 5) Verify Restore

Quick row counts:

```bash
psql -h localhost -p 5432 -U timesheet_user -d timesheet_db -c "SELECT COUNT(*) FROM users;"
psql -h localhost -p 5432 -U timesheet_user -d timesheet_db -c "SELECT COUNT(*) FROM projects;"
psql -h localhost -p 5432 -U timesheet_user -d timesheet_db -c "SELECT COUNT(*) FROM time_entries;"
```

## Common Issues

### Server/client version mismatch

Symptom:

```text
pg_dump: error: server version: 15.x; pg_dump version: 14.x
```

Fix:

- Use matching PostgreSQL client binaries for the server major version.
- On macOS Homebrew, explicitly call the right binary path, e.g.:

```bash
/opt/homebrew/opt/postgresql@15/bin/pg_dump
/opt/homebrew/opt/postgresql@15/bin/pg_restore
```

### Permission denied on restore

- Ensure target DB user has privileges on the database.
- Use `--no-owner` when restoring into a different role setup.

## Optional: Plain SQL backup

If you need SQL text instead of custom dump:

```bash
PGPASSWORD='timesheet_pass' /opt/homebrew/opt/postgresql@15/bin/pg_dump \
  -h localhost -p 5432 -U timesheet_user -d timesheet_db \
  -f backups/timesheet_db_$(date +%Y%m%d_%H%M%S).sql
```

Restore SQL backup:

```bash
PGPASSWORD='timesheet_pass' psql \
  -h localhost -p 5432 -U timesheet_user -d timesheet_db \
  -f backups/timesheet_db_YYYYMMDD_HHMMSS.sql
```
