from bottle import Bottle, request, redirect, response
import os, re, quopri, json, subprocess
from email import message_from_string
from email.utils import parseaddr

# Now reading REAL data: headers.txt and Maildir. Both read-only —
# nothing here writes back into ~/T9A/mail or ~/Mail. Writes stay
# confined to webproto/ (mail.raw, request.json), same isolation
# principle as before, just with real input instead of dummy input.
#
# The one exception is the send step, which subprocess-calls the
# real, already-proven send_json.sh — safe to do because that script
# is itself read-only on the /mail side: it only reads whatever
# request.json path it's given and POSTs it, writing nothing back.

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIL_DIR = os.path.dirname(SCRIPT_DIR)  # parent: ~/T9A/mail

HEADERS_FILE = os.path.expanduser("~/T9A/mail/headers.txt")
MAILDIRS = [
    os.path.expanduser("~/Mail/INBOX/cur"),
    os.path.expanduser("~/Mail/INBOX/new"),
]

MAILRAW_OUT = os.path.join(SCRIPT_DIR, "mail.raw")       # webproto's own copy
REQUEST_JSON = os.path.join(SCRIPT_DIR, "request.json")  # webproto's own copy
SEND_SCRIPT = os.path.join(MAIL_DIR, "send_json.sh")      # the real, proven script
FROM_ADDR = "hello@omegasemantic.org"

app = Bottle()


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
                current["subject"] = line[len("Subject:"):].strip()
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
    new/ — mirrors browser.sh's generate_raw exactly. Read-only: copies
    the found file into webproto/mail.raw, never touches the source."""
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
    # header values outright — this was a real bug found and fixed
    # in reply.sh, same fix needed here.
    return " ".join((value or "").split())


def derive_reply_fields(raw):
    """Port of reply.sh's header derivation. Takes raw mail.raw text,
    returns (to_addr, subject, in_reply_to, references)."""
    msg = message_from_string(raw)

    _, to_addr = parseaddr(msg.get("From", ""))

    subject = unfold(msg.get("Subject", ""))
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
        rendered = "(no message file found for this UID — dummy data gap)"
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

    # Subprocess-call the real, already-proven send_json.sh, pointed
    # at webproto's own request.json. This does not touch /mail — the
    # script only reads the given path and POSTs it.
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
