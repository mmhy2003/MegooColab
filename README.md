# MegooColab

Open-source, self-hosted project management for humans and coding agents. See [docs/brd.md](docs/brd.md).

## Install (self-hosted)

Requirements: a Linux server (or any Docker host) with Docker and Docker Compose.

```bash
git clone <this repo> megoocolab && cd megoocolab/deploy
cp .env.example .env
# edit .env:
#   SECRET_KEY        -> output of: openssl rand -hex 32
#   POSTGRES_PASSWORD -> any strong password
#   SITE_ADDRESS      -> your domain (e.g. megoo.example.com) for automatic HTTPS,
#                        or :80 for plain HTTP (trial / behind another proxy)
#   PUBLIC_URL        -> the URL people open, e.g. https://megoo.example.com
#   COOKIE_SECURE     -> true when served over HTTPS
docker compose up -d --build
```

Open `PUBLIC_URL`. The first visit asks you to create the organization and its admin account.
Database migrations run automatically when the backend starts.

Optional: **Admin → Settings** to configure email (SMTP) for invitations and password resets.
Without email, admins copy invite and reset links from the Users page.

**Upgrade:** `git pull && docker compose up -d --build` (migrations run on start).
**Backups:** the `pgdata` (database) and `uploads` (attachments) volumes hold all data.

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

### End-to-end test

Runs against a fresh production-style stack on http://localhost:8080:

```bash
cp deploy/.env.example .superpowers/e2e.env   # set SECRET_KEY, HTTP_PORT=8080, PUBLIC_URL=http://localhost:8080
docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env up -d --build --wait
cd frontend && npx playwright install chromium && npx playwright test
docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env down -v
```
