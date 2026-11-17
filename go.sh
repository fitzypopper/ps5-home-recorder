#!/usr/bin/env bash
# One-command PS5 home-screen recorder.
#   go.sh [seconds] [fps]
#   go.sh 30        -> 30s @ 15fps
#   go.sh 30 60     -> 30s @ 60fps
#   go.sh           -> record until Ctrl+C @ 15fps
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    exec python3 ps5rec.py --help
fi
seconds="${1:-0}"
fps="${2:-15}"
args=(--fps "$fps")
if [[ "$seconds" != "0" ]]; then args+=(--seconds "$seconds"); fi
exec python3 ps5rec.py "${args[@]}" record
