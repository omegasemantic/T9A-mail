#!/usr/bin/env python3
import sys
from email import message_from_string

STUB_MIN_LEN = 40

def is_attachment_part(part):
    disp = (part.get("Content-Disposition") or "").lower()
    if "attachment" in disp:
        return True
    ctype = part.get_content_type()
    if ctype not in ("text/plain", "text/html"):
        return True
    return False

def get_plain_text(part):
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()
    except Exception:
        return ""

def classify(raw):
    msg = message_from_string(raw)

    if not msg.is_multipart():
        if msg.get_content_type() == "text/plain":
            return ""
        return "! unreadable"

    if msg.get_content_type() == "multipart/related":
        return "! attachment"

    plain_text = ""
    for part in msg.walk():
        if part.is_multipart():
            continue
        if is_attachment_part(part):
            return "! attachment"
        if part.get_content_type() == "text/plain" and not plain_text:
            plain_text = get_plain_text(part)

    if len(plain_text) >= STUB_MIN_LEN:
        return ""
    return "! unreadable"

if __name__ == "__main__":
    with open(sys.argv[1], errors="replace") as f:
        raw = f.read()
    print(classify(raw))
