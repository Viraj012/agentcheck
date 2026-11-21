#!/usr/bin/env bash
# Rename the product everywhere in docs/config. Usage: scripts/rename.sh AgentCheck NewName
# Code reads the name from APP_NAME (backend) and src/lib/brand.ts (frontend), so update those too.
set -euo pipefail
OLD="$1"; NEW="$2"
old_l=$(echo "$OLD" | tr '[:upper:]' '[:lower:]'); new_l=$(echo "$NEW" | tr '[:upper:]' '[:lower:]')
grep -rlI -e "$OLD" -e "$old_l" --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.next . \
  | while read -r f; do sed -i '' -e "s/$OLD/$NEW/g" -e "s/$old_l/$new_l/g" "$f"; echo "updated: $f"; done
echo "Done. Also rename the project folder if you like, and update APP_NAME / brand.ts if they hold a custom value."
