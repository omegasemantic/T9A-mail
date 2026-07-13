#!/bin/bash
# reply.sh
# Parses mail.raw (written by browser.sh's [r]eply) and writes a Resend-
# ready request.json. Does NOT send anything — that's send_json.sh's job.
#
# Usage: ./reply.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAILRAW="$SCRIPT_DIR/mail.raw"
OUT="$SCRIPT_DIR/request.json"
FROM_ADDR="hello@omegasemantic.org"

if [ ! -f "$MAILRAW" ]; then
    echo "ERROR: $MAILRAW not found. Run browser.sh [r]eply first." >&2
    exit 1
fi

# Extract To, Subject, In-Reply-To, References using Python's email
# library — handles RFC 2047 decoding and header folding correctly,
# same reasoning as mail_helpers.sh using python3 rather than shell
# text-munging for header parsing. Output is JSON, parsed back out
# below via separate python3 calls rather than shell word-splitting
# (which would break on spaces in subjects).
PARSED=$(python3 - "$MAILRAW" <<'PYSCRIPT'
import sys, json
from email import message_from_file
from email.utils import parseaddr

def unfold(value):
    # RFC 5322 allows long header values to be "folded" across multiple
    # lines (continuation lines start with whitespace). Python's email
    # library preserves the embedded newline when reading these back,
    # which Resend's API rejects outright ("Header keys and values
    # cannot contain carriage return, line feed, or null characters").
    # Collapse any run of whitespace (including embedded \n) to a
    # single space, matching how the header would actually be read.
    return " ".join(value.split())

path = sys.argv[1]
with open(path, "r", errors="replace") as f:
    msg = message_from_file(f)

_, from_addr = parseaddr(msg.get("From", ""))

subject = unfold(msg.get("Subject", ""))
if not subject.lower().startswith("re:"):
    subject = f"Re: {subject}"

msgid = unfold(msg.get("Message-ID", ""))

orig_refs = unfold(msg.get("References", ""))
references = f"{orig_refs} {msgid}".strip() if orig_refs else msgid

print(json.dumps({
    "to": from_addr,
    "subject": subject,
    "in_reply_to": msgid,
    "references": references
}))
PYSCRIPT
)

if [ -z "$PARSED" ]; then
    echo "ERROR: failed to parse $MAILRAW" >&2
    exit 1
fi

TO_ADDR=$(echo "$PARSED" | python3 -c "import json,sys; print(json.load(sys.stdin)['to'])")
SUBJECT=$(echo "$PARSED" | python3 -c "import json,sys; print(json.load(sys.stdin)['subject'])")
IN_REPLY_TO=$(echo "$PARSED" | python3 -c "import json,sys; print(json.load(sys.stdin)['in_reply_to'])")
REFERENCES=$(echo "$PARSED" | python3 -c "import json,sys; print(json.load(sys.stdin)['references'])")

if [ -z "$TO_ADDR" ] || [ -z "$IN_REPLY_TO" ]; then
    echo "ERROR: could not extract To/Message-ID from $MAILRAW" >&2
    exit 1
fi

echo "Reply to: $TO_ADDR"
echo "Subject:  $SUBJECT"
echo
echo "Enter reply body (end with Ctrl-D on its own line):"
BODY=$(cat)

if [ -z "$BODY" ]; then
    echo "ERROR: empty body, aborting." >&2
    exit 1
fi

# Write request.json using Python's json module for correct escaping —
# same reasoning as elsewhere in the project: don't hand-roll JSON
# string escaping in bash. BODY is passed as an argument (not via
# stdin) because "python3 -" already consumes stdin as its own
# program source — piping BODY in afterward would hit EOF immediately.
python3 - "$OUT" "$FROM_ADDR" "$TO_ADDR" "$SUBJECT" "$IN_REPLY_TO" "$REFERENCES" "$BODY" <<'PYSCRIPT'
import sys, json

out, from_addr, to_addr, subject, in_reply_to, references, body = sys.argv[1:8]

payload = {
    "from": from_addr,
    "to": [to_addr],
    "subject": subject,
    "text": body,
    "headers": {
        "In-Reply-To": in_reply_to,
        "References": references
    }
}

with open(out, "w") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")

print(f"Wrote {out}")
PYSCRIPT
