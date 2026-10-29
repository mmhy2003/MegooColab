# MegooColab: build and run the production stack, the development setup and the runner.
# `make` alone lists the commands. Recipes avoid shell-specific syntax (no `cd`, no inline VAR=value,
# messages through $(info)), so they work from PowerShell or cmd as well as from Git Bash.

.DEFAULT_GOAL := help

# built from this checkout (deploy/docker-compose.build.yml); servers pull the published images instead
COMPOSE     := docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.build.yml
DEV_COMPOSE := docker compose -f deploy/docker-compose.dev.yml

ifeq ($(OS),Windows_NT)
EXE := .exe
endif

# The runner's version: runner/VERSION with -dev+<commit> after it, so a local build is never taken for a
# release (no update arrow in the app). `make runner VERSION=1.2.3` overrides.
VERSION := $(strip $(file < runner/VERSION))-dev+$(shell git rev-parse --short HEAD)

# The targets GoReleaser ships (runner/.goreleaser.yaml)
RUNNER_PLATFORMS := windows/amd64 windows/arm64 linux/amd64 linux/arm64 darwin/amd64 darwin/arm64

.PHONY: help build up stop logs runner env-check dev-build dev dev-stop dev-runner dev-up dev-migrate \
	_dev-api _dev-worker _dev-web

help:
	@$(info Production, the Docker stack configured by deploy/.env:)
	@$(info   make build       build the Docker images and the runner for every platform)
	@$(info   make up          build if needed, start everything in the background, wait until healthy)
	@$(info   make stop        stop the stack, keeping its data)
	@$(info   make logs        follow the logs)
	@$(info   make runner      build the runner for every platform into runner/bin, VERSION=x.y.z to override)
	@$(info Development, see README Development quick-start:)
	@$(info   make dev-build   install the backend and frontend packages and build the dev runner)
	@$(info   make dev         start the dev containers, then the API, worker and frontend; Ctrl+C stops them)
	@$(info   make dev-stop    stop the dev containers, keeping their data)
	@$(info   make dev-runner  build the runner for this machine into runner/bin)
	@exit 0

# --- Production ---

env-check:
	$(if $(wildcard deploy/.env),,$(error deploy/.env is missing: copy deploy/.env.example to deploy/.env and fill it in))

build: env-check runner
	$(COMPOSE) build

up: env-check
	$(COMPOSE) up -d --build --wait

stop:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

define RUNNER_TARGET
.PHONY: runner-$(1)-$(2)
runner: runner-$(1)-$(2)
runner-$(1)-$(2): export GOOS := $(1)
runner-$(1)-$(2): export GOARCH := $(2)
runner-$(1)-$(2): export CGO_ENABLED := 0
runner-$(1)-$(2):
	go build -C runner -trimpath -ldflags "-s -w -X main.version=$(VERSION)" -o bin/megoocolab-runner_$(1)_$(2)$(if $(filter windows,$(1)),.exe) .
endef
$(foreach p,$(RUNNER_PLATFORMS),$(eval $(call RUNNER_TARGET,$(word 1,$(subst /, ,$(p))),$(word 2,$(subst /, ,$(p))))))

runner:
	@$(info Runner $(VERSION) built into runner/bin)
	@exit 0

# --- Development ---

# Dev-only keys (the API wants a SECRET_KEY of 16+ characters; Meilisearch's is the dev container's), for the
# dev targets only: exported globally they would override deploy/.env in `docker compose` (the shell's
# environment wins over the .env file).
dev dev-migrate _dev-api _dev-worker: export SECRET_KEY := megoo-dev-secret-key-not-for-production
dev dev-migrate _dev-api _dev-worker: export MEILI_MASTER_KEY := megoo-dev-master-key
dev dev-migrate _dev-api _dev-worker: export VALKEY_URL := valkey://:megoo-dev-valkey@localhost:6379/0
# coloured log levels in terminals that do not say they are one (Git Bash's mintty)
_dev-api _dev-worker: export FORCE_COLOR := 1

dev-build: dev-runner
	uv --directory backend sync
	npm --prefix frontend install

dev: dev-migrate
	@$(info Starting the API, the worker and the frontend; open http://localhost:8080. Ctrl+C stops them.)
	@$(MAKE) --no-print-directory -j3 _dev-api _dev-worker _dev-web

dev-up:
	$(DEV_COMPOSE) up -d --wait

# The API migrates on start too; doing it first keeps the worker from starting on an empty database.
dev-migrate: dev-up
	uv --directory backend run alembic upgrade head

_dev-api:
	uv --directory backend run fastapi dev app/main.py

_dev-worker:
	uv --directory backend run python -m app.worker

_dev-web:
	npm --prefix frontend run dev

dev-stop:
	$(DEV_COMPOSE) down

dev-runner:
	go build -C runner -ldflags "-X main.version=$(VERSION)" -o bin/megoocolab-runner$(EXE) .
