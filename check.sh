#!/usr/bin/env bash
# The full pre-commit gate, in the order that matters: auto-fixes first, then
# formatting (fixes can leave unformatted code), then checks that nothing is
# left to fix, then types and tests, then the dependency audit, then the
# secret scan of what is staged.
set -euo pipefail
cd "$(dirname "$0")"

ruff check --fix .
ruff format .
ruff check .
ruff format --check .
mypy
pytest -q
# pip-audit runs in its own uv-managed environment: its own dependencies need
# a newer Python than this project targets, and must not end up in the lock.
uvx --python 3.12 pip-audit==2.10.1 -r requirements-dev.txt --disable-pip \
    --progress-spinner off
git add -A
gitleaks git . --staged --no-banner
