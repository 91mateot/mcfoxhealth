#!/bin/bash
# Sync backend/shared/shared/ → backend/functions/*/shared/
# Run before every `sam build` to prevent stale-shared bugs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/shared/shared"

if [ ! -d "$SRC" ]; then
  echo "ERROR: $SRC not found" >&2
  exit 1
fi

for fn_dir in "$ROOT"/functions/*/; do
  DST="$fn_dir/shared"
  mkdir -p "$DST"
  rsync -a --delete \
    --exclude '__pycache__' \
    "$SRC/" "$DST/"
  echo "synced shared/ → $(basename "$fn_dir")"
done
echo "✓ all functions in sync with shared/"
