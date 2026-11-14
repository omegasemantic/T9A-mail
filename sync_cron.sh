#!/bin/bash
# sync_cron.sh
# Wrapper for the VPS cron job: mbsync + regenerate headers.txt.
# A lock file prevents overlapping runs if mbsync is ever slow (e.g.
# a large mailbox or a slow network moment) — without it, cron could
# start a second sync before the first finishes, and two mbsync
# processes touching the same Maildir at once is worth avoiding
# entirely rather than debugging later.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCKFILE="/tmp/t9amail-sync.lock"
LOGFILE="$SCRIPT_DIR/sync_cron.log"

if [ -e "$LOCKFILE" ]; then
    echo "$(date -Iseconds) skipped — previous run still in progress (lockfile present)" >> "$LOGFILE"
    exit 0
fi
trap 'rm -f "$LOCKFILE"' EXIT
touch "$LOCKFILE"

{
    echo "--- $(date -Iseconds) ---"
    mbsync posteo
    if [ $? -ne 0 ]; then
        echo "ERROR: mbsync failed, not regenerating headers.txt"
    else
        cd "$SCRIPT_DIR"
        ./pager.sh > headers.txt
        echo "headers.txt regenerated"
    fi
} >> "$LOGFILE" 2>&1
