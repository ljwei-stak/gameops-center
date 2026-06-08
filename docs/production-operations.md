# GameOps Production Operations

This guide captures the production defaults added on top of the local demo stack.

## Managed MySQL

- Start from `deploy/mysql/managed-mysql.example.env`.
- Enable provider automated backups/PITR, slow query logging, TLS, and separate app/migration users.
- Exported app-side metrics include `gameops_mysql_pool_in_use`, `gameops_mysql_pool_idle`, `gameops_mysql_pool_overflow_total`, `gameops_mysql_slow_queries_total`, and `gameops_mysql_managed`.
- `ops/backup/mysql-backup.ps1` provides a portable `mysqldump` helper for self-managed or break-glass exports.

## Migrations

Alembic:

```powershell
alembic -c migrations/alembic.ini upgrade head
```

Flyway:

```powershell
flyway -url="jdbc:mysql://$env:GAMEOPS_MYSQL_HOST:$env:GAMEOPS_MYSQL_PORT/$env:GAMEOPS_MYSQL_DATABASE" -user="$env:GAMEOPS_MYSQL_USER" -password="$env:GAMEOPS_MYSQL_PASSWORD" -locations="filesystem:migrations/flyway/sql" migrate
```

The app still has idempotent table creation for local demos. Production should run migrations before app rollout.

## SSO/OIDC And RBAC

- Set `GAMEOPS_LOCAL_LOGIN_ENABLED=false` in production so demo accounts are not seeded and password login is disabled.
- Configure `GAMEOPS_OIDC_ISSUER`, `GAMEOPS_OIDC_CLIENT_ID`, and `GAMEOPS_OIDC_JWKS_URL`.
- Map groups with `GAMEOPS_OIDC_ADMIN_GROUP` and `GAMEOPS_OIDC_RELEASE_GROUP`.
- Unsigned development ID tokens require `GAMEOPS_OIDC_ALLOW_UNSIGNED_DEV_TOKENS=true`; do not set it in production.

## Release Governance

- `POST /api/deploy` creates a pending approval instead of executing immediately.
- Admins approve or reject through `POST /api/deploy/approvals/{id}/approve`.
- Release owners execute approved changes with `POST /api/deploy/approvals/{id}/execute`.
- Execution validates `GAMEOPS_CHANGE_WINDOW` or the request-level `change_window`.
- Rollbacks are recorded through `POST /api/deployments/{id}/rollback` and listed at `GET /api/rollbacks`.

## Kubernetes Safety

- `deploy/kubernetes/gameops-center.yaml` uses managed MySQL and a namespace-scoped `Role`/`RoleBinding` in `game-prod`, not cluster-wide RBAC.
- The default manifest keeps `GAMEOPS_DRY_RUN=true` and `GAMEOPS_TRUSTED_RUNTIME=false`.
- Apply `deploy/kubernetes/trusted-runtime-patch.yaml` only in a reviewed, trusted production namespace.

## Long-Term Observability

- Prometheus owns long-term metrics and evaluates rules in `deploy/prometheus/rules/gameops-alerts.yml`.
- Grafana provisions dashboards from `deploy/grafana/dashboards`.
- Alertmanager routes alerts to `/api/alertmanager`, where GameOps persists the event and fans out through Webhook, WeCom, DingTalk, or email channels.
