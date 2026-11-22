#!/usr/bin/env bash
# Serve the Northwind sample help center at http://localhost:${1:-8001} for manual browsing.
set -euo pipefail
cd "$(dirname "$0")/../fixtures/northwind/site"
exec python3 -m http.server "${1:-8001}" --bind 127.0.0.1
