# Infrastructure

`compose.yaml` defines the local PostgreSQL and Redis services. Persistent data
is kept in Docker-managed named volumes, not inside this repository.

Run from the repository root:

```bash
docker compose -f infrastructure/compose.yaml up -d --wait postgres redis
docker compose -f infrastructure/compose.yaml ps
```
