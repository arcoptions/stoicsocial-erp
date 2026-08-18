#!/usr/bin/env bash
#
# BoldERP Shopify catch-up sync.
#
# Webhooks are the primary path into the ERP. Shopify never replays a delivery it
# failed to make, so any outage - a wrong URL, a rotated signing secret, a few
# minutes of downtime - loses those orders permanently unless something polls.
# This is that poll. It is a backstop, not the main path.
#
# Invoked every 10 minutes by cron (or by bolderp-shopify-sync.timer under systemd).
# Safe to run by hand at any time; ingest_order upserts on shopify_order_id and
# lines already claimed by a print batch are left alone, so re-runs are no-ops.

set -uo pipefail

APP_DIR="${BOLDERP_APP_DIR:-/opt/bolderp/app}"
VENV_PY="${BOLDERP_PYTHON:-/opt/bolderp/venv/bin/python}"
LOG_DIR="${BOLDERP_LOG_DIR:-/opt/bolderp/logs}"
LOG_FILE="$LOG_DIR/shopify-sync.log"
LOCK_FILE="${BOLDERP_LOCK_FILE:-/tmp/bolderp-shopify-sync.lock}"

# Look back further than the interval so a slow or skipped run cannot leave a gap.
LOOKBACK_MINUTES="${BOLDERP_SYNC_LOOKBACK:-30}"

# Keep the log bounded; this runs ~52k times a year.
MAX_LOG_LINES="${BOLDERP_SYNC_LOG_LINES:-2000}"

mkdir -p "$LOG_DIR"

# -n: if a previous run is still going, skip this one rather than piling up.
# SQLite has a single writer, so overlapping syncs would just contend for the lock.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) skipped: previous run still in progress" >>"$LOG_FILE"
  exit 0
fi

cd "$APP_DIR" || { echo "$(date -Is) FAILED: no such directory $APP_DIR" >>"$LOG_FILE"; exit 1; }

start=$(date -Is)
output=$("$VENV_PY" manage.py sync_shopify_orders \
           --since-minutes "$LOOKBACK_MINUTES" \
           --apply-inventory 2>&1)
rc=$?

if [ $rc -eq 0 ]; then
  # Collapse the routine case to one line; per-batch chatter is not worth keeping.
  summary=$(printf '%s\n' "$output" | grep -E 'Sync complete|Dry-run complete' || printf '%s' "$output" | tail -n 1)
  echo "$start ok  $summary" >>"$LOG_FILE"
else
  echo "$start FAILED (exit $rc)" >>"$LOG_FILE"
  printf '%s\n' "$output" | sed 's/^/    /' >>"$LOG_FILE"
fi

# Trim in place so the inode (and any tail -f) survives.
if [ "$(wc -l <"$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_LINES" ]; then
  trimmed=$(tail -n "$MAX_LOG_LINES" "$LOG_FILE") && printf '%s\n' "$trimmed" >"$LOG_FILE"
fi

exit $rc
