#!/usr/bin/env bash
# Coverage of every test that runs without a real LLM (tests/live excluded), processes included. Fails below the gate.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f .coverage .coverage.*
.venv/bin/python -m coverage run -m pytest --ignore=tests/live -q -p no:cacheprovider "$@"
.venv/bin/python -m coverage combine -q
.venv/bin/python -m coverage html -q
.venv/bin/python -m coverage report
