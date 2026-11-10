#!/usr/bin/env bash
# Copy the integration to a Home Assistant instance over SSH.
#
#   HA_SSH=<ssh host> tools/deploy.sh
#
# HA_CONFIG is the configuration folder on that host (default /config).
# Python changes need a restart of Home Assistant afterwards; a change to
# the dashboard strategy only needs the browser to reload.
set -euo pipefail

: "${HA_SSH:?set HA_SSH to the SSH host of Home Assistant}"
config=${HA_CONFIG:-/config}
here=$(cd "$(dirname "$0")/.." && pwd)

# The folder often belongs to root; sudo is used where the SSH user may not write.
remote="
target='$config/custom_components'
run() { if [ -w \"\$target\" ]; then \"\$@\"; else sudo -n \"\$@\"; fi; }
run mkdir -p \"\$target\" &&
    run rm -rf \"\$target/skoda_api\" &&
    run tar -C \"\$target\" --no-same-owner -xzf - &&
    grep -o '\"version\": \"[^\"]*\"' \"\$target/skoda_api/manifest.json\"
"

tar -C "$here/custom_components" \
    --exclude='__pycache__' --exclude='._*' --exclude='.DS_Store' \
    -czf - skoda_api | ssh "$HA_SSH" "$remote"
