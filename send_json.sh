#!/bin/bash
# send_json.sh
# Reads request.json (written by reply.sh or compose_new.sh) and POSTs
# it to the Resend API as-is. Generic — knows nothing about mail.raw,
# replies, or headers; its only contract is the request.json file.
#
# Usage: ./send_json.sh [path-to-request.json]
#   Defaults to ./request.json if no path given.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUEST_FILE="${1:-$SCRIPT_DIR/request.json}"

source "$HOME/.resendrc"
if [ -z "$RESEND_API_KEY" ]; then
    echo "ERROR: RESEND_API_KEY not set. Check ~/.resendrc" >&2
    exit 1
fi

if [ ! -f "$REQUEST_FILE" ]; then
    echo "ERROR: $REQUEST_FILE not found." >&2
    exit 1
fi

# Sanity-check it's valid JSON before sending — fail loudly here
# rather than let Resend reject a malformed payload silently.
if ! python3 -c "import json; json.load(open('$REQUEST_FILE'))" 2>/dev/null; then
    echo "ERROR: $REQUEST_FILE is not valid JSON." >&2
    exit 1
fi

echo "Sending $REQUEST_FILE ..."

response=$(curl -s -X POST 'https://api.resend.com/emails' \
  -H "Authorization: Bearer $RESEND_API_KEY" \
  -H 'Content-Type: application/json' \
  -d @"$REQUEST_FILE")

echo "$response"

# Surface a clear pass/fail rather than leaving the raw response as
# the only signal — Resend returns {"id": ...} on success or
# {"statusCode": ..., "message": ...} on failure.
echo "$response" | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)
except Exception:
    print('WARNING: could not parse Resend response as JSON', file=sys.stderr)
    sys.exit(1)
if 'id' in r:
    print(f\"Sent OK — id: {r['id']}\")
else:
    print(f\"ERROR: send failed — {r.get('message', r)}\", file=sys.stderr)
    sys.exit(1)
"
