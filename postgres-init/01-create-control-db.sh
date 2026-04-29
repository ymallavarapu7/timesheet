#!/usr/bin/env bash
# Create the control-plane database on first Postgres boot.
#
# This script runs inside the postgres image's
# /docker-entrypoint-initdb.d/ hook, which only fires when the data
# directory is empty (i.e. a fresh volume). On existing volumes you
# need to create the database manually:
#
#   docker compose exec db createdb -U timesheet_user acufy_control
#
# The control plane holds tenants, platform_admins, platform_settings,
# and provisioning audit logs. Per-tenant data continues to live in
# the existing timesheet_db (and, after Phase 3.C, in per-tenant
# databases acufy_tenant_<slug>).

set -euo pipefail

psql --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
  SELECT 'CREATE DATABASE acufy_control'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'acufy_control')
  \gexec
EOSQL

echo "control-plane database 'acufy_control' is ready."
