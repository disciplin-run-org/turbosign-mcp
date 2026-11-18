#!/usr/bin/env bash
# suite.sh - the turbosign-mcp suite: what the Tests workflow ran, now run by
# scripts/release.sh at the commit it releases (and by hand at a PR head).
#
#   1. The self-test, as the real console entry point would run it, on an
#      uncredentialled machine: no TURBODOCX_* variable, an empty home.
#   2. The unit suite. Its last line is the totals the release tag records.
#
# The interpreter is $PYTHON, else .venv/bin/python in the checkout, else
# python3. It needs the dev extras: pip install -e ".[dev]".
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
py="${PYTHON:-}"
if [ -z "$py" ]; then
  if [ -x .venv/bin/python ]; then py=.venv/bin/python; else py=python3; fi
fi

home="$(mktemp -d)"
trap 'rm -rf "$home"' EXIT
unset_args=()
for name in $(compgen -e); do
  case "$name" in TURBODOCX_*) unset_args+=(-u "$name") ;; esac
done
env "${unset_args[@]}" TURBOSIGN_HOME="$home" PYTHONPATH=src \
  "$py" -m turbosign_mcp.server --selftest

"$py" -m pytest -q -p no:cacheprovider
