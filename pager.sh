#!/bin/bash
# pager.sh
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "$SCRIPT_DIR/mail_helpers.sh"
MAILDIRS=("$HOME/Mail/INBOX/cur" "$HOME/Mail/INBOX/new")
for dir in "${MAILDIRS[@]}"; do
    for f in "$dir"/*; do
        [ -f "$f" ] || continue
        filename=$(basename "$f")
        uid=$(echo "$filename" | grep -oP 'U=\K[0-9]+')
        [ -z "$uid" ] && continue
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
    done
done
