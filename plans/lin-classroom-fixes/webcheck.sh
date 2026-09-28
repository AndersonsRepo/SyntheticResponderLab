#!/bin/sh
# Run the web unit tests whose name matches $1; fail if none matched (a typo must not pass).
set -e
cd "$(git rev-parse --show-toplevel)/apps/web"
rm -rf .test-dist && ./node_modules/.bin/tsc -p tsconfig.test.json
out=$(node --test --test-isolation=none --test-name-pattern="$1" '.test-dist/tests/**/*.js' 2>&1) || { echo "$out" | tail -40; exit 1; }
echo "$out" | grep -E '^ℹ (pass|fail)'
echo "$out" | grep -qE '^ℹ pass [1-9]' || { echo "no test matched: $1"; exit 1; }
echo "$out" | grep -qE '^ℹ fail 0' || exit 1
