#!/bin/bash
# rawmail2md.sh
# Usage: ./rawmail2md.sh [mail.raw] [output.md]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/mail_helpers.sh"

RAW="${1:-mail.raw}"
OUT="${2:-body.md}"

from_raw=$(grep -m1 "^From:" "$RAW" | sed 's/From: //')
subject_raw=$(grep -m1 "^Subject:" "$RAW" | sed 's/Subject: //')
date_raw=$(grep -m1 "^Date:" "$RAW" | sed 's/Date: //')
encoding=$(grep -im1 "^Content-Transfer-Encoding:" "$RAW" | sed 's/.*: //' | tr -d '\r')
content_type=$(grep -im1 "^Content-Type:" "$RAW")

from=$(clean_from "$from_raw")
subject=$(decode_subject "$subject_raw")
date=$(trim_date "$date_raw")

# Extract raw body: everything after the first blank line
raw_body=$(sed -n '/^$/,$p' "$RAW" | tail -n +2)

# Decode quoted-printable if needed
if echo "$encoding" | grep -qi "quoted-printable"; then
    body=$(echo "$raw_body" | python3 -c "
import sys, quopri
sys.stdout.write(quopri.decodestring(sys.stdin.read()).decode('utf-8', errors='replace'))
")
else
    body="$raw_body"
fi

# Strip HTML tags if this is an HTML-typed message
if echo "$content_type" | grep -qi "text/html"; then
    body=$(echo "$body" | sed -e 's/<br[^>]*>/\n/gi' -e 's/<[^>]*>//g')
fi

{
    echo "**From:** $from"
    echo ""
    echo "**Subject:** $subject"
    echo ""
    echo "**Date:** $date"
    echo ""
    echo "---"
    echo ""
    echo "$body"
} > "$OUT"

echo "Wrote $OUT"
