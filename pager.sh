#!/bin/bash
# pager.sh
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "$SCRIPT_DIR/mail_helpers.sh"
MAILDIRS=("$HOME/Mail/INBOX/cur" "$HOME/Mail/INBOX/new")
LIMIT=10

# newest $LIMIT messages by UID
while IFS=$'\t' read -r uid f; do
    dir=$(dirname "$f")
    [[ "$dir" == */new ]] && read_status="unread" || read_status="read"
    from=$(clean_from "$(grep -m1 "^From:" "$f" | sed 's/From: //')")
    subject=$(grep -m1 "^Subject:" "$f" | sed 's/Subject: //')
    date=$(trim_date "$(grep -m1 "^Date:" "$f" | sed 's/Date: //')")
    warning=$(python3 "$SCRIPT_DIR/classify_mail.py" "$f")
    echo "UID: $uid | $read_status"
    echo "From:    $from"
    echo "Subject: $subject"
    echo "Date:    $date"
    [ -n "$warning" ] && echo "Warning: $warning"
    echo "---"
done < <(
    for dir in "${MAILDIRS[@]}"; do
        for f in "$dir"/*; do
            [ -f "$f" ] || continue
            uid=$(basename "$f" | grep -oP 'U=\K[0-9]+')
            [ -z "$uid" ] && continue
            printf '%s\t%s\n' "$uid" "$f"
        done
    done | sort -t$'\t' -k1,1nr | head -n "$LIMIT"
)
