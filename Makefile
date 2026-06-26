.PHONY: help install-dev lint format typecheck test coverage check docker-build docker-up benchmark

COV_MIN ?= 90

help:
	@echo "Targets:"
	@echo "  install-dev   Install the package with dev extras"
	@echo "  lint          Run ruff lint checks"
	@echo "  format        Apply ruff formatting"
	@echo "  typecheck     Run mypy on the package"
	@echo "  test          Run the test suite"
	@echo "  coverage      Run tests with a coverage gate (COV_MIN=$(COV_MIN))"
	@echo "  check         lint + typecheck + coverage"
	@echo "  docker-build  Build the container image"
	@echo "  docker-up     Run the service via docker compose"
	@echo "  benchmark     Run the latency/throughput benchmark"

install-dev:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev,server]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy aisnekbox

test:
	pytest -q

coverage:
	pytest --cov=aisnekbox --cov-report=term-missing --cov-fail-under=$(COV_MIN)

check: lint typecheck coverage

docker-build:
	docker build -t aisnekbox:local .

docker-up:
	docker compose up --build

benchmark:
	python scripts/benchmark.py
