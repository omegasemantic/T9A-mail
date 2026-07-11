#!/bin/bash
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   mbsync posteo
   "$SCRIPT_DIR/pager.sh" > "$SCRIPT_DIR/headers.txt"
   "$SCRIPT_DIR/browser.sh"
   "$SCRIPT_DIR/rawmail2md.sh" && cat body.md
