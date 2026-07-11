#!/bin/bash
# mail_helpers.sh
# Shared field-cleaning functions for the View module.
# Source this file, don't execute it directly:
#   source ./mail_helpers.sh

# Strip angle-bracket address from a From header, keep display name if present.
# "Simon Kearns <simon@example.com>" -> "Simon Kearns"
# "<service@kiwibank.co.nz>"         -> "service@kiwibank.co.nz"  (falls back to bare address)
clean_from() {
    local raw="$1"
    local clean
    clean=$(echo "$raw" | sed -E 's/<[^>]*>//g; s/^"?//; s/"?[[:space:]]*$//' | sed 's/[[:space:]]*$//')
    if [ -z "$clean" ]; then
        clean=$(echo "$raw" | grep -oP '<\K[^>]*')
    fi
    echo "$clean"
}

# Decode RFC 2047 encoded-word subjects, e.g. =?utf-8?Q?...?=
# Falls back to the original string if decoding fails or python3 unavailable.
decode_subject() {
    local raw="$1"
    if command -v python3 >/dev/null 2>&1; then
        echo "$raw" | python3 -c "
import sys
from email.header import decode_header
try:
    parts = decode_header(sys.stdin.read().strip())
    print(''.join(str(t, e or 'utf-8') if isinstance(t, bytes) else t for t, e in parts))
except Exception:
    print(sys.stdin.read().strip())
" 2>/dev/null
    else
        echo "$raw"
    fi
}

# Reformat an RFC 5322 date string into something shorter for display.
# "Thu, 9 Jul 2026 08:04:16 +1200" -> "9 Jul 2026, 8:04am"
# Falls back to the original string if it can't be parsed.
trim_date() {
    local raw="$1"
    if command -v python3 >/dev/null 2>&1; then
        echo "$raw" | python3 -c "
import sys
from email.utils import parsedate_to_datetime
raw = sys.stdin.read().strip()
try:
    dt = parsedate_to_datetime(raw)
    hour12 = dt.strftime('%-I')
    ampm = 'am' if dt.hour < 12 else 'pm'
    print(dt.strftime(f'%-d %b %Y, {hour12}:%M') + ampm)
except Exception:
    print(raw)
" 2>/dev/null
    else
        echo "$raw"
    fi
}
