from bottle import Bottle, request, redirect, response, static_file
import os, re, quopri, json, subprocess
from email import message_from_string
from email.utils import parseaddr
from email.header import decode_header

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # ~/T9A/mail

HEADERS_FILE = os.path.join(SCRIPT_DIR, "headers.txt")
MAILDIRS = [
    os.path.expanduser("~/Mail/INBOX/cur"),
    os.path.expanduser("~/Mail/INBOX/new"),
]

MAILRAW_OUT = os.path.join(SCRIPT_DIR, "mail.raw")
REQUEST_JSON = os.path.join(SCRIPT_DIR, "request.json")
SEND_SCRIPT = os.path.join(SCRIPT_DIR, "send_json.sh")
FROM_ADDR = "hello@omegasemantic.org"

app = Bottle()


def decode_mime_subject(raw_subject):
    """RFC 2047 decode (=?utf-8?Q?...?= etc.) — mirrors mail_helpers.sh's
    decode_subject. headers.txt stores subjects as pager.sh wrote them,
    which is the raw encoded form; this decodes for display, same as
    browser.sh already does via mail_helpers.sh."""
    if not raw_subject:
        return raw_subject
    try:
        parts = decode_header(raw_subject)
        decoded = "".join(
            (chunk.decode(enc or "utf-8", errors="replace") if isinstance(chunk, bytes) else chunk)
            for chunk, enc in parts
        )
        return decoded
    except Exception:
        # Fail soft — show the raw string rather than crashing the
        # whole list/message page over one malformed subject.
        return raw_subject


def parse_headers():
    """Parse headers.txt into an ordered list of dicts, oldest first —
    same order/format browser.sh already assumes (last entry = most
    recent). Re-read fresh on every call: headers.txt is a snapshot,
    not something to cache or hold across requests."""
    entries = []
    current = {}
    with open(HEADERS_FILE) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("UID:"):
                m = re.match(r"UID:\s*(\d+)(?:\s*\|\s*(\w+))?", line)
                current["uid"] = m.group(1)
                current["status"] = m.group(2) or ""
            elif line.startswith("From:"):
                current["from"] = line[len("From:"):].strip()
            elif line.startswith("Subject:"):
                current["subject"] = decode_mime_subject(line[len("Subject:"):].strip())
            elif line.startswith("Date:"):
                current["date"] = line[len("Date:"):].strip()
            elif line.startswith("Warning:"):
                current["warning"] = line[len("Warning:"):].strip()
            elif line == "---":
                entries.append(current)
                current = {}
    return entries


def find_entry(uid):
    """Locate a UID's entry and its neighbours in the current
    headers.txt order. Returns (entry, older_uid, newer_uid) or
    (None, None, None) if the UID isn't present — e.g. a stale link
    to a message no longer in the current snapshot."""
    entries = parse_headers()
    for i, e in enumerate(entries):
        if e["uid"] == uid:
            older = entries[i - 1]["uid"] if i > 0 else None
            newer = entries[i + 1]["uid"] if i < len(entries) - 1 else None
            return e, older, newer
    return None, None, None


def generate_raw(uid):
    """Find the real message file for this UID, checking both cur/ and
    new/ — mirrors browser.sh's generate_raw exactly."""
    for maildir in MAILDIRS:
        if not os.path.isdir(maildir):
            continue
        for fname in os.listdir(maildir):
            if f",U={uid}:" in fname:
                src = os.path.join(maildir, fname)
                with open(src, errors="replace") as f:
                    content = f.read()
                with open(MAILRAW_OUT, "w") as f:
                    f.write(content)
                return content
    return None


def render_body(raw):
    """Mirrors browser.sh's render_body: decode quoted-printable if
    declared, strip HTML tags if content-type is text/html."""
    headers, _, body = raw.partition("\n\n")
    encoding = ""
    content_type = ""
    for line in headers.splitlines():
        if line.lower().startswith("content-transfer-encoding:"):
            encoding = line.split(":", 1)[1].strip()
        elif line.lower().startswith("content-type:"):
            content_type = line.split(":", 1)[1].strip()

    if "quoted-printable" in encoding.lower():
        body = quopri.decodestring(body.encode()).decode("utf-8", errors="replace")

    if "text/html" in content_type.lower():
        body = re.sub(r"<br[^>]*>", "\n", body, flags=re.IGNORECASE)
        body = re.sub(r"<[^>]*>", "", body)

    return body.strip()


def unfold(value):
    # RFC 5322 header folding: long values can be split across lines
    # with continuation whitespace. Resend rejects embedded \n in
    # header values outright — a real bug found and fixed during
    # testing (see TODO/handover).
    return " ".join((value or "").split())


def derive_reply_fields(raw):
    """Header derivation for a reply: to/subject/In-Reply-To/References
    from the original message's mail.raw content."""
    msg = message_from_string(raw)

    _, to_addr = parseaddr(msg.get("From", ""))

    subject = decode_mime_subject(unfold(msg.get("Subject", "")))
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    msgid = unfold(msg.get("Message-ID", ""))

    orig_refs = unfold(msg.get("References", ""))
    references = f"{orig_refs} {msgid}".strip() if orig_refs else msgid

    return to_addr, subject, msgid, references


def page(title, body_html):
    """Minimal wrapper, no CSS — matches the project's proven Opera
    Extreme rendering (plain text/basic HTML, styling is stripped
    anyway)."""
    return f"<html><head><title>{title}</title></head><body>{body_html}</body></html>"


@app.route("/")
def list_messages():
    entries = parse_headers()
    rows = []
    for e in reversed(entries):  # most recent first, matches browser.sh's start position
        flag = " (N)" if e["status"] == "unread" else ""
        warn = " !" if e.get("warning") else ""
        rows.append(
            f'<p><a href="/message?uid={e["uid"]}">{e["from"]} — {e["subject"]}{flag}{warn}</a><br>'
            f'{e["date"]}</p>'
        )
    return page("Inbox", "<h3>Inbox</h3>" + "".join(rows))


@app.route("/hello.html")
def hello():
    # Retained from the original placeholder app.py — harmless, not
    # part of the real nav chain, no reason to force its removal.
    return static_file('hello.html', root='./static')


@app.route("/message")
def message_view():
    uid = request.query.uid
    entry, older, newer = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found in current headers.txt.</p><p><a href='/'>Back to list</a></p>")

    warn = f"<p>Warning: {entry['warning']}</p>" if entry.get("warning") else ""
    flag = " (N)" if entry["status"] == "unread" else ""

    nav = []
    if older:
        nav.append(f'<a href="/message?uid={older}">[older]</a>')
    if newer:
        nav.append(f'<a href="/message?uid={newer}">[newer]</a>')
    nav_html = " ".join(nav)

    body = f"""
    <h3>UID: {entry['uid']}{flag}</h3>
    <p>From: {entry['from']}<br>
    Subject: {entry['subject']}<br>
    Date: {entry['date']}</p>
    {warn}
    <p><a href="/view?uid={uid}">[view]</a> <a href="/reply?uid={uid}">[reply]</a></p>
    <p>{nav_html}</p>
    <p><a href="/">[list]</a></p>
    """
    return page(f"Message {uid}", body)


@app.route("/view")
def view_body():
    uid = request.query.uid
    entry, older, newer = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found.</p><p><a href='/'>Back to list</a></p>")

    raw = generate_raw(uid)
    if raw is None:
        rendered = "(no message file found for this UID)"
    else:
        rendered = render_body(raw)

    nav = []
    if older:
        nav.append(f'<a href="/view?uid={older}">[older]</a>')
    if newer:
        nav.append(f'<a href="/view?uid={newer}">[newer]</a>')
    nav_html = " ".join(nav)

    body = f"""
    <h3>From: {entry['from']}</h3>
    <p>Subject: {entry['subject']}</p>
    <hr>
    <pre>{rendered}</pre>
    <hr>
    <p><a href="/reply?uid={uid}">[reply]</a></p>
    <p>{nav_html}</p>
    <p><a href="/message?uid={uid}">[back to message]</a> <a href="/">[list]</a></p>
    """
    return page(f"View {uid}", body)


@app.route("/reply")
def reply_form():
    uid = request.query.uid
    entry, _, _ = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found.</p><p><a href='/'>Back to list</a></p>")

    raw = generate_raw(uid)
    if raw is None:
        return page("Error", f"<p>No message file found for UID {uid} — cannot reply.</p><p><a href='/message?uid={uid}'>[back]</a></p>")

    to_addr, subject, in_reply_to, references = derive_reply_fields(raw)

    body = f"""
    <h3>Reply to: {to_addr}</h3>
    <p>Subject: {subject}</p>
    <form action="/reply" method="POST">
        <input type="hidden" name="uid" value="{uid}">
        <textarea name="body" rows="6" cols="30" placeholder="Your reply..."></textarea>
        <br><br>
        <input type="submit" value="Send">
    </form>
    <p><a href="/message?uid={uid}">[cancel]</a></p>
    """
    return page(f"Reply {uid}", body)


@app.route("/reply", method="POST")
def reply_submit():
    uid = request.forms.uid
    reply_body = request.forms.body

    if not reply_body or not reply_body.strip():
        return page("Error", f"<p>Empty reply body — nothing sent.</p><p><a href='/reply?uid={uid}'>[back]</a></p>")

    raw = generate_raw(uid)
    if raw is None:
        return page("Error", f"<p>No message file found for UID {uid} — cannot send.</p><p><a href='/message?uid={uid}'>[back]</a></p>")

    to_addr, subject, in_reply_to, references = derive_reply_fields(raw)

    payload = {
        "from": FROM_ADDR,
        "to": [to_addr],
        "subject": subject,
        "text": reply_body,
        "headers": {
            "In-Reply-To": in_reply_to,
            "References": references
        }
    }

    with open(REQUEST_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    result = subprocess.run(
        ["bash", SEND_SCRIPT, REQUEST_JSON],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        # On success, land back on the same message — looks like
        # nothing happened, per the agreed nav pattern.
        redirect(f"/message?uid={uid}", code=303)
    else:
        return page("Send failed", f"""
        <h3>Send failed</h3>
        <pre>{result.stdout}{result.stderr}</pre>
        <p><a href="/reply?uid={uid}">[try again]</a></p>
        """)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
