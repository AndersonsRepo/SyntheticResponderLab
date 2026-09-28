#!/bin/bash
# One entry point for DONE.md checks. Runs from anywhere inside the worktree.
set -eo pipefail
ROOT=$(git rev-parse --show-toplevel)
PY=${PY:-/Users/andersonedmond/dev/SyntheticResponderLab/apps/api/.venv/bin/python}
TSC="$ROOT/apps/web/node_modules/.bin/tsc"
case "$1" in
  api) cd "$ROOT/apps/api" && "$PY" -m pytest -q "tests/test_human_interview.py::$2" ;;
  # A name pattern that matches nothing still exits 0, so require at least one pass.
  web) cd "$ROOT/apps/web" && rm -rf .test-dist && "$TSC" -p tsconfig.test.json \
         && out=$(node --test --test-name-pattern="$2" .test-dist/tests/human-interview.test.js) \
         && echo "$out" && grep -q "^ℹ pass [1-9]" <<<"$out" ;;
  api-all) cd "$ROOT/apps/api" && "$PY" -m pytest -q ;;
  web-all) cd "$ROOT/apps/web" && npm run test:unit ;;
  typecheck) cd "$ROOT/apps/web" && "$TSC" --noEmit -p tsconfig.json ;;
  # Prerender needs the production env names set; placeholders, nothing is contacted at build time.
  build) cd "$ROOT/apps/web" && API_BASE_URL=${API_BASE_URL:-https://api.example.invalid} DEPLOYMENT_SHARED_SECRET=${DEPLOYMENT_SHARED_SECRET:-build-placeholder} APP_ACCESS_PASSWORD=${APP_ACCESS_PASSWORD:-build-placeholder} npm run build ;;
  *) echo "unknown case $1" >&2; exit 2 ;;
esac
