#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/mail_helpers.sh"

HEADERS="${1:-headers.txt}"
MAILDIRS=("$HOME/Mail/INBOX/new" "$HOME/Mail/INBOX/cur")
TMPFILE="mail.raw"

uids=()
froms=()
subjects=()
warnings=()

uid=""
from=""
subject=""
warning=""

while IFS= read -r line; do
    if [[ "$line" == UID:* ]]; then
        uid=$(echo "$line" | grep -oP 'UID: \K[0-9]+')
    elif [[ "$line" == From:* ]]; then
        from="${line#From:    }"
    elif [[ "$line" == Subject:* ]]; then
        subject="${line#Subject: }"
    elif [[ "$line" == Warning:* ]]; then
        warning="${line#Warning: }"
    elif [[ "$line" == "---" ]]; then
        uids+=("$uid")
        froms+=("$from")
        subjects+=("$subject")
        warnings+=("$warning")
        uid=""; from=""; subject=""; warning=""
    fi
done < "$HEADERS"

for i in "${!uids[@]}"; do
    display_from=$(clean_from "${froms[$i]}")

    if [ -n "${warnings[$i]}" ]; then
        printf "%2d) UID %-4s [%s] From: %s: %s\n" "$((i+1))" "${uids[$i]}" "${warnings[$i]}" "$display_from" "${subjects[$i]}"
    else
        printf "%2d) UID %-4s From: %s: %s\n" "$((i+1))" "${uids[$i]}" "$display_from" "${subjects[$i]}"
    fi
done

read -p "Select message: " choice
selected_uid="${uids[$((choice-1))]}"

file=""
for dir in "${MAILDIRS[@]}"; do
    match=$(ls "$dir" 2>/dev/null | grep ",U=${selected_uid}:")
    if [ -n "$match" ]; then
        file="$dir/$match"
        break
    fi
done

if [ -z "$file" ]; then
    echo "UID $selected_uid not found in new/ or cur/"
    exit 1
fi

cp "$file" "$TMPFILE"
echo "Raw message copied to $TMPFILE"
