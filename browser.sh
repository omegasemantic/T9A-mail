#!/bin/bash
# browse.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/mail_helpers.sh"
HEADERS="$SCRIPT_DIR/headers.txt"
MAILDIRS=("$HOME/Mail/INBOX/cur" "$HOME/Mail/INBOX/new")
TMPFILE="$SCRIPT_DIR/mail.raw"
uids=(); froms=(); subjects=(); warnings=(); dates=(); statuses=()
uid=""; from=""; subject=""; warning=""; date=""; status=""
while IFS= read -r line; do
    if [[ "$line" == UID:* ]]; then
        uid=$(echo "$line" | grep -oP 'UID: \K[0-9]+')
        status=$(echo "$line" | grep -oP '\| \K\w+')
    elif [[ "$line" == From:* ]]; then
        from="${line#From:    }"
    elif [[ "$line" == Subject:* ]]; then
        subject="${line#Subject: }"
    elif [[ "$line" == Date:* ]]; then
        date="${line#Date:    }"
    elif [[ "$line" == Warning:* ]]; then
        warning="${line#Warning: }"
    elif [[ "$line" == "---" ]]; then
        uids+=("$uid"); froms+=("$from"); subjects+=("$subject")
        warnings+=("$warning"); dates+=("$date"); statuses+=("$status")
        uid=""; from=""; subject=""; warning=""; date=""; status=""
    fi
done < "$HEADERS"
generate_raw() {
    local target_uid="$1"
    for dir in "${MAILDIRS[@]}"; do
        match=$(ls "$dir" 2>/dev/null | grep ",U=${target_uid}:")
        if [ -n "$match" ]; then
            cp "$dir/$match" "$TMPFILE"
            return 0
        fi
    done
    return 1
}
# Decode mail.raw's body for display: handles quoted-printable and strips
# HTML tags if the message is HTML-typed. Mirrors rawmail2md.sh's logic.
render_body() {
    local raw_file="$1"
    local encoding content_type raw_body body
    encoding=$(grep -im1 "^Content-Transfer-Encoding:" "$raw_file" | sed 's/.*: //' | tr -d '\r')
    content_type=$(grep -im1 "^Content-Type:" "$raw_file")
    raw_body=$(sed -n '/^$/,$p' "$raw_file" | tail -n +2)
    if echo "$encoding" | grep -qi "quoted-printable"; then
        body=$(echo "$raw_body" | python3 -c "
import sys, quopri
sys.stdout.write(quopri.decodestring(sys.stdin.read()).decode('utf-8', errors='replace'))
")
    else
        body="$raw_body"
    fi
    if echo "$content_type" | grep -qi "text/html"; then
        body=$(echo "$body" | sed -e 's/<br[^>]*>/\n/gi' -e 's/<[^>]*>//g')
    fi
    echo "$body"
}
idx=$((${#uids[@]} - 1))   # start at most recent
while true; do
    clear
    display_from=$(clean_from "${froms[$idx]}")
    display_subject=$(decode_subject "${subjects[$idx]}")
    display_date=$(trim_date "${dates[$idx]}")
    indicator=""
    [ "${statuses[$idx]}" == "unread" ] && indicator=" (N)"
    echo "UID: ${uids[$idx]}$indicator"
    echo "From:    $display_from"
    echo "Subject: $display_subject"
    echo "Date:    $display_date"
    [ -n "${warnings[$idx]}" ] && echo "Warning: ${warnings[$idx]}"
    echo "---"
    echo "[n]ext  [p]revious  [v]iew  [r]eply  [q]uit"
    read -p "> " cmd
    case "$cmd" in
        n) [ $idx -gt 0 ] && idx=$((idx-1)) ;;
        p) [ $idx -lt $((${#uids[@]}-1)) ] && idx=$((idx+1)) ;;
        v)
            generate_raw "${uids[$idx]}"
            clear
            echo "=== From: $display_from ==="
            echo "=== Subject: $display_subject ==="
            echo "---"
            render_body "$TMPFILE"
            echo "---"
            echo "[n]ext  [p]revious  [r]eply  [q]uit"
            read -p "> " cmd2
            case "$cmd2" in
                n) [ $idx -gt 0 ] && idx=$((idx-1)) ;;
                p) [ $idx -lt $((${#uids[@]}-1)) ] && idx=$((idx+1)) ;;
                r) generate_raw "${uids[$idx]}"; echo "mail.raw ready. (Reply construction not yet built.)"; read -p "Press enter..." _ ;;
                q) exit 0 ;;
            esac
            ;;
        r)
            generate_raw "${uids[$idx]}"
            echo "mail.raw generated. (Reply construction not yet built.)"
            read -p "Press enter to continue..." _
            ;;
        q) break ;;
    esac
done
