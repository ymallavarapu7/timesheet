# Self-Hosted Deployment

## Prerequisites

- Docker 24+
- Docker Compose v2
- A valid self-hosted license key

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in the database password, `SECRET_KEY`, `ENCRYPTION_KEY`, and license values.
3. Start the stack:

```bash
docker compose up -d
```

The API container runs `alembic upgrade head` automatically before starting.

## Getting a License Key

Contact support or your platform administrator to have a self-hosted license issued for your server hostname and database name.

## Upgrading

1. Pull the latest images.
2. Restart the stack:

```bash
docker compose pull
docker compose up -d
```

Migrations run automatically when the API container starts.

## Backup

Use `pg_dump` against the running Postgres container:

```bash
docker compose exec db pg_dump -U ${DB_USER:-timesheet} ${DB_NAME:-timesheet} > backup.sql
```

## Troubleshooting

Check the API logs first:

```bash
docker compose logs api
```

If the app fails licensing startup checks, confirm `DEPLOYMENT_MODE=self_hosted`, `LICENSE_KEY`, `LICENSE_PUBLIC_KEY_PEM`, and `LICENSE_SERVER_HASH_SALT` are all set correctly.
