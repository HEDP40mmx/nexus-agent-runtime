#!/usr/bin/env bash
# Fails when required runtime files or tests are missing.
set -euo pipefail
missing=0
for p in pyproject.toml nexus tests; do
  [ -e "$p" ] || { echo "MISSING required path: $p" >&2; missing=1; }
done
if [ -d tests ] && ! find tests -name 'test_*.py' -o -name '*_test.py' | grep -q .; then
  echo "MISSING test files under tests/" >&2; missing=1
fi
if [ -d nexus ] && ! find nexus -name '*.py' | grep -q .; then
  echo "MISSING Python sources under nexus/" >&2; missing=1
fi
exit $missing
