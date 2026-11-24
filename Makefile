.PHONY: help install dev sync lock test lint format clean build docs check-docs

# Default target
help:
	@echo "Available commands:"
	@echo "  install            Install package with locked dependencies"
	@echo "  dev                Install development dependencies"
	@echo "  sync               Sync all extras from uv.lock"
	@echo "  lock               Update uv.lock"
	@echo "  test               Run tests"
	@echo "  check-docs         Verify alignment docs match the repository"
	@echo "  lint               Run linting"
	@echo "  format             Format code"
	@echo "  clean              Clean build artifacts"
	@echo "  build              Build package"
	@echo "  docs               Build documentation"

# Update the project lockfile
lock:
	uv lock --default-index https://pypi.org/simple

# Install the project and all extras from uv.lock
sync:
	uv sync --all-extras --locked --default-index https://pypi.org/simple

install: sync

# Install development dependencies in development mode
install-dev: sync
	pre-commit install

# Install development dependencies (alias for backward compatibility)
dev: install-dev

# Run tests
test:
	pytest tests/ -v --cov=midscene --cov-report=html --cov-report=term-missing

# Verify alignment docs against baseline, gap report and source facts
check-docs:
	python3 scripts/check_docs_consistency.py

# Run tests with specific markers
test-unit:
	pytest tests/ -v -m "unit"

test-integration:
	pytest tests/ -v -m "integration"

# Linting
lint:
	ruff check midscene/ tests/
	ruff format --check midscene/ tests/ examples/
	mypy midscene/

# Format code
format:
	ruff check --fix midscene/ tests/ examples/
	ruff format midscene/ tests/ examples/

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

# Build package
build: clean
	python -m build

# Build documentation
docs:
	mkdocs build

# Serve documentation locally
docs-serve:
	mkdocs serve

# Release to PyPI
release: build
	twine upload dist/*

# Release to Test PyPI
release-test: build
	twine upload --repository testpypi dist/*