#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/lanzou_update_push_api_server/config.json"
EXAMPLE="$ROOT/lanzou_update_push_api_server/config.example.json"

if [ ! -f "$CONFIG" ]; then
  cp "$EXAMPLE" "$CONFIG"
  echo "Created local config: $CONFIG"
fi

export LANZOU_MONITOR_CONFIG="$CONFIG"
cd "$ROOT"
python -m lanzou_update_push_api_server
