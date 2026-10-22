# MegooColab

Open-source, self-hosted project management for humans and coding agents. See [docs/brd.md](docs/brd.md).

## Development quick-start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# 1. Database (PostgreSQL 17 + pgvector on localhost:5433; also creates megoo_test)
#    and Caddy on http://localhost:8080 (/api -> :8000, everything else -> :3000)
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. Backend
cd backend
uv sync
uv run pytest                      # test suite (uses the megoo_test database)
SECRET_KEY=dev uv run fastapi dev app/main.py   # API on http://localhost:8000/api/docs

# 3. Frontend
cd frontend
npm install
npm test                           # unit tests (Vitest)
npm run gen:api                    # regenerate src/lib/api-types.ts after API changes
npm run dev                        # then open http://localhost:8080
```
