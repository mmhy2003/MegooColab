# MegooColab

Open-source, self-hosted project management for humans and coding agents. See [docs/brd.md](docs/brd.md).

## Development quick-start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# 1. Database (PostgreSQL 17 + pgvector on localhost:5433; also creates megoo_test)
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. Backend
cd backend
uv sync
uv run pytest                      # test suite (uses the megoo_test database)
SECRET_KEY=dev uv run fastapi dev app/main.py   # API on http://localhost:8000/api/docs
```
