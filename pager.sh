#!/bin/bash

# pager.sh
# claude: add comment here


MAILDIRS=("$HOME/Mail/INBOX/cur" "$HOME/Mail/INBOX/new")


for dir in "${MAILDIRS[@]}"; do
    for f in "$dir"/*; do
        [ -f "$f" ] || continue
        filename=$(basename "$f")
        uid=$(echo "$filename" | grep -oP 'U=\K[0-9]+')
        [ -z "$uid" ] && continue

        [[ "$dir" == */new ]] && read_status="unread" || read_status="read"

        from=$(grep -m1 "^From:" "$f" | sed 's/From: //')
        subject=$(grep -m1 "^Subject:" "$f" | sed 's/Subject: //')
        date=$(grep -m1 "^Date:" "$f" | sed 's/Date: //')

        content_type=$(grep -im1 "^Content-Type:" "$f")
        warning=""
        if [ -n "$content_type" ] && echo "$content_type" | grep -qiv "text/plain"; then
            warning="! ouch"
        fi

        echo "UID: $uid | $read_status"
        echo "From:    $from"
        echo "Subject: $subject"
        echo "Date:    $date"
        [ -n "$warning" ] && echo "Warning: $warning"
        echo "---"
    done
done
