# mirror-bench developer Makefile.
# `make ci-local` runs exactly what CI runs (minus Docker push/publish bits).
# `make help` lists every target with a one-line blurb.

SHELL := /bin/bash
PYTHON_VERSION := 3.14
IMAGE ?= mirror-bench
TAG ?= dev

UV := uv

.DEFAULT_GOAL := help

## help: Show this help.
.PHONY: help
help:
	@awk 'BEGIN {FS=":.*## "; printf "Targets:\n"} /^## / {gsub(/^## /, ""); print}' $(MAKEFILE_LIST)
	@echo
	@awk 'BEGIN {FS=":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## install: Sync runtime + dev dependencies via uv.
.PHONY: install
install:
	$(UV) sync --all-extras

## hooks: Install pre-commit git hooks.
.PHONY: hooks
hooks:
	$(UV) run --with pre-commit pre-commit install --install-hooks
	$(UV) run --with pre-commit pre-commit install --hook-type commit-msg

## fmt: Format sources with ruff.
.PHONY: fmt
fmt:
	$(UV) run ruff format .

## fmt-check: Fail if formatting would change anything.
.PHONY: fmt-check
fmt-check:
	$(UV) run ruff format --check .

## lint: Run ruff lint checks.
.PHONY: lint
lint:
	$(UV) run ruff check .

## typecheck: Run mypy (strict) against src/ and tests/.
.PHONY: typecheck
typecheck:
	$(UV) run mypy src tests

## test: Run the unit test suite.
.PHONY: test
test:
	$(UV) run pytest -v --tb=short

## test-integration: Run opt-in integration tests against real mirrors.
.PHONY: test-integration
test-integration:
	MIRROR_BENCH_INTEGRATION=1 $(UV) run pytest -m integration -v

## security: Run bandit + pip-audit against runtime deps.
.PHONY: security
security:
	$(UV) run --with "bandit[toml]" bandit -c pyproject.toml -r src
	$(UV) export --no-emit-project --format requirements.txt > .audit-reqs.txt
	$(UV) run --with pip-audit pip-audit --progress-spinner off --strict --disable-pip -r .audit-reqs.txt
	@rm -f .audit-reqs.txt

## pre-commit: Run the full pre-commit suite against every file.
.PHONY: pre-commit
pre-commit:
	$(UV) run --with pre-commit pre-commit run --all-files --show-diff-on-failure

## docker-build: Build the release container.
.PHONY: docker-build
docker-build:
	docker build -t $(IMAGE):$(TAG) .

## docker-test: Build + smoke-test the container.
.PHONY: docker-test
docker-test: docker-build
	docker run --rm $(IMAGE):$(TAG) --help
	docker run --rm $(IMAGE):$(TAG) list --distro arch --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['mirrors'], 'expected non-empty mirrors'"

## build: Build sdist + wheel via uv.
.PHONY: build
build:
	$(UV) build

## clean: Remove caches and build artifacts.
.PHONY: clean
clean:
	rm -rf dist build .ruff_cache .mypy_cache .pytest_cache htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

## ci-local: Run the full CI pipeline locally (lint, typecheck, test, security, docker-test).
.PHONY: ci-local
ci-local: fmt-check lint typecheck test security docker-test
	@echo "✅ ci-local: all checks passed"
