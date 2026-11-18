from bottle import Bottle, request, redirect, response, static_file
import os, re, quopri, json, subprocess, html
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
CONTACTS_FILE = os.path.expanduser("~/.t9a_contacts")
SEEN_FILE = os.path.join(SCRIPT_DIR, "seen.txt")
HIDDEN_FILE = os.path.join(SCRIPT_DIR, "hidden.txt")
UIDVALIDITY_FILE = os.path.expanduser("~/Mail/INBOX/.uidvalidity")

SWITCH_SERVICES = {
    'mail': 't9amail-web.service',
    'map': 't9amap-web.service',
    'drive': 't9adrive-web.service',
}
RESTART_SCRIPT = '/root/restart'

app = Bottle()


def decode_mime_subject(raw_subject):
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
        return raw_subject


def read_validity():
    try:
        with open(UIDVALIDITY_FILE) as f:
            return f.readline().strip()
    except Exception:
        return ""


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            lines = f.read().splitlines()
        if not lines or lines[0] != read_validity():
            return set()
        return set(lines[1:])
    except Exception:
        return set()


def mark_seen(uid):
    try:
        seen = load_seen()
        seen.add(uid)
        with open(SEEN_FILE, "w") as f:
            f.write(read_validity() + "\n")
            for uid_str in sorted(seen, key=int):
                f.write(uid_str + "\n")
    except OSError:
        pass


def load_hidden():
    try:
        with open(HIDDEN_FILE) as f:
            lines = f.read().splitlines()
        if not lines or lines[0] != read_validity():
            return set()
        return set(lines[1:])
    except Exception:
        return set()


def hide_uid(uid):
    try:
        hidden = load_hidden()
        hidden.add(uid)
        with open(HIDDEN_FILE, "w") as f:
            f.write(read_validity() + "\n")
            for uid_str in sorted(hidden, key=int):
                f.write(uid_str + "\n")
    except OSError:
        pass


def parse_headers():
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
    entries.sort(key=lambda e: int(e["uid"]))
    return entries


def find_entry(uid):
    entries = parse_headers()
    for i, e in enumerate(entries):
        if e["uid"] == uid:
            older = entries[i - 1]["uid"] if i > 0 else None
            newer = entries[i + 1]["uid"] if i < len(entries) - 1 else None
            return e, older, newer
    return None, None, None


def generate_raw(uid):
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


def _decode_part_payload(part):
    """Decode a single message/part's payload to text, honouring its own
    Content-Transfer-Encoding and charset."""
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""


def _strip_html(text):
    text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", text)
    return text


def wrap_long(text, n=25):
    pieces = re.split(r'(\s+)', text)
    result = []
    for piece in pieces:
        if re.match(r'^\s+$', piece):
            result.append(html.escape(piece))
        elif len(piece) > n:
            escaped = html.escape(piece)
            chunks = [escaped[i:i+n] for i in range(0, len(escaped), n)]
            result.append("<wbr>".join(chunks))
        else:
            result.append(html.escape(piece))
    return "".join(result)


def render_body(raw):
    """Render a raw RFC 5322 message to safe, displayable HTML.

    Walks MIME structure properly: for multipart/alternative, prefers the
    text/plain part and renders it directly (no tag-stripping needed).
    Falls back to the text/html part (stripped) if no usable plain part
    exists, and finally falls back to the old single-part behaviour for
    non-multipart messages.
    """
    msg = message_from_string(raw)

    if msg.is_multipart():
        plain_part = None
        html_part = None
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain_part is None:
                plain_part = part
            elif ctype == "text/html" and html_part is None:
                html_part = part

        if plain_part is not None:
            body = _decode_part_payload(plain_part).strip()
            body = wrap_long(body)
        elif html_part is not None:
            body = _decode_part_payload(html_part).strip()
            body = _strip_html(body)
            body = wrap_long(body)
        else:
            body = "(no displayable part found in this message)"

        body = body.replace("\n", "<br>\n")
        return body

    # Non-multipart fallback (original single-part logic)
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

    body = body.strip()

    if "text/html" in content_type.lower():
        body = _strip_html(body)
        body = wrap_long(body)
    else:
        body = wrap_long(body)

    body = body.replace("\n", "<br>\n")
    return body


def unfold(value):
    return " ".join((value or "").split())


def load_contacts(path=None):
    contacts_path = path if path is not None else CONTACTS_FILE
    try:
        with open(contacts_path) as f:
            contacts = []
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                tokens = line.split()
                if not tokens:
                    continue
                address = tokens[-1]
                if "@" not in address or " " in address:
                    continue
                name = " ".join(tokens[:-1])
                contacts.append((name, address))
            return contacts
    except FileNotFoundError:
        return []


def check_compose(to, subject, body, contacts):
    valid_addresses = {addr for name, addr in contacts}
    if to not in valid_addresses:
        return "To address not in contacts list"
    if not " ".join(subject.split()).strip():
        return "Subject cannot be empty"
    if not body.strip():
        return "Body cannot be empty"
    return ""


def build_compose_payload(to, subject, body):
    return {
        "from": FROM_ADDR,
        "to": [to],
        "subject": " ".join(subject.split()),
        "text": body
    }


def derive_reply_fields(raw):
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
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>body {{ overflow-wrap: anywhere; }}</style>
</head>
<body>
{body_html}
</body>
</html>"""


@app.route("/")
def root():
    return list_messages()


@app.route("/list")
def list_messages():
    entries = parse_headers()
    seen = load_seen()
    hidden = load_hidden()
    rows = []
    for e in reversed(entries):
        if e["uid"] in hidden:
            continue
        is_unread = e["status"] == "unread" and e["uid"] not in seen
        flag = "(N) " if is_unread else ""
        warn = " !" if e.get("warning") else ""
        rows.append(
            f'<p><a href="/view?uid={e["uid"]}">{flag}{html.escape(e["from"])} \u2014 {html.escape(e["subject"])}{warn}</a><br>'
            f'{html.escape(e["date"])}</p>'
        )
    return page("Inbox", '<p><a href="/ticket.html">switcher</a> | <a href="/compose">compose</a> | <a href="/list">refresh</a></p><h3>Messages</h3>' + "".join(rows))


@app.route("/hello.html")
def hello():
    return static_file('hello.html', root='./static')


@app.route("/ticket.html")
def ticket_page():
    return static_file('ticket.html', root=os.path.join(SCRIPT_DIR, 'static'))


@app.route('/switch/<name>', method='POST')
def switch(name):
    if name not in SWITCH_SERVICES:
        return "unknown service"
    subprocess.Popen(['systemd-run', '--unit=t9aswitch', RESTART_SCRIPT, name])
    return '<p>Switching... <a href="/">Wait a few seceonds then click to reload></p>'


@app.route("/test/<filename>")
def design_sandbox(filename):
    return static_file(filename, root='./static/test')


@app.route("/message")
def message_view():
    uid = request.query.uid
    if not uid.isdigit():
        response.status = 404
        return page("Not found", "<p>Not found.</p>")
    redirect(f"/view?uid={uid}", code=302)


def message_view_content(uid):
    entry, older, newer = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found in current headers.txt.</p>")

    warn = f"<p><strong>Warning: {html.escape(entry['warning'])}</strong></p>" if entry.get("warning") else ""
    flag = " (N)" if entry["status"] == "unread" else ""

    nav_links = []
    if older:
        nav_links.append(f'<a href="/message?uid={older}">[old]</a>')
    if newer:
        nav_links.append(f'<a href="/message?uid={newer}">[new]</a>')
    nav_links.append('<a href="/list">[list]</a>')

    body = f"""
    <p><strong>From:</strong> {html.escape(entry['from'])}<br>
    <strong>Subject:</strong> {html.escape(entry['subject'])}{flag}<br>
    <strong>Date:</strong> {html.escape(entry['date'])}</p>
    {warn}
    <p><a href="/view?uid={uid}">[view]</a> | <a href="/reply?uid={uid}">[reply]</a></p>
    <p>{" | ".join(nav_links)}</p>
    """
    return page(f"Message {uid}", body)


@app.route("/view")
def view_body():
    uid = request.query.uid
    if not uid.isdigit():
        response.status = 404
        return page("Not found", "<p>Not found.</p>")
    entry, older, newer = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found.</p>")
    mark_seen(uid)

    raw = generate_raw(uid)
    if raw is None:
        rendered = "(no message file found for this UID)"
    else:
        rendered = render_body(raw)

    body = f"""
    <p><strong>From:</strong> {html.escape(entry['from'])}<br>
    <strong>Subject:</strong> {html.escape(entry['subject'])}<br>
    <strong>Date:</strong> {html.escape(entry['date'])}</p>
    <p>{rendered}</p>
    <p><a href="/reply?uid={uid}">[reply]</a> | <a href="/list">[list]</a></p>
    <form action="/hide" method="POST">
    <input type="hidden" name="uid" value="{uid}">
    <input type="submit" value="Hide"></form>
    """
    return page(f"View {uid}", body)


@app.route("/reply")
def reply_form():
    uid = request.query.uid
    if not uid.isdigit():
        response.status = 404
        return page("Not found", "<p>Not found.</p>")
    entry, _, _ = find_entry(uid)
    if not entry:
        response.status = 404
        return page("Not found", f"<p>UID {uid} not found.</p>")

    raw = generate_raw(uid)
    if raw is None:
        return page("Error", f"<p>No message file found for UID {uid} -- cannot reply.</p><p><a href='/message?uid={uid}'>[cancel]</a></p>")

    to_addr, subject, in_reply_to, references = derive_reply_fields(raw)

    body = f"""
    <p><strong>Reply to:</strong> {html.escape(to_addr)}<br>
    <strong>Subject:</strong> {html.escape(subject)}</p>
    <form action="/reply" method="POST">
        <input type="hidden" name="uid" value="{uid}">
        <textarea name="body" rows="6" placeholder=""></textarea>
        <br><br>
        <input type="submit" value="Send">
    </form>
    <p><a href="/message?uid={uid}">[cancel]</a></p>
    """
    return page(f"Reply {uid}", body)


@app.route("/reply", method="POST")
def reply_submit():
    uid = request.forms.uid
    if not uid.isdigit():
        response.status = 404
        return page("Not found", "<p>Not found.</p>")
    reply_body = request.forms.body

    if not reply_body or not reply_body.strip():
        return page("Error", f"<p>Empty reply body -- nothing sent.</p><p><a href='/reply?uid={uid}'>[back]</a></p>")

    raw = generate_raw(uid)
    if raw is None:
        return page("Error", f"<p>No message file found for UID {uid} -- cannot send.</p><p><a href='/message?uid={uid}'>[back]</a></p>")

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
        redirect(f"/message?uid={uid}", code=303)
    else:
        return page("Send failed", f"""
        <p><strong>Send failed</strong></p>
        <p>{html.escape(result.stdout + result.stderr)}</p>
        <p><a href="/reply?uid={uid}">[try again]</a></p>
        """)


@app.route("/hide", method="POST")
def hide_message():
    uid = request.forms.uid
    if not uid.isdigit():
        response.status = 404
        return page("Not found", "<p>Not found.</p>")
    hide_uid(uid)
    redirect("/list", code=303)


@app.route("/compose")
def compose_form():
    contacts = load_contacts()
    if not contacts:
        return page("Compose", "<p>No contacts configured.</p>")

    options = "".join(
        f'<option value="{html.escape(address)}">{html.escape(name)}</option>'
        for name, address in contacts
    )

    body = f"""
    <form action="/compose" method="POST">
        <label>To: <select name="to" required>{options}</select></label><br>
        <label>Subject: <input name="subject" required></label><br>
        <label>Body: <textarea name="body" rows="6" required></textarea></label><br>
        <input type="submit" value="Send">
    </form>
    <p><a href="/list">[cancel]</a></p>
    """
    return page("Compose", body)


@app.route("/compose", method="POST")
def compose_submit():
    to = request.forms.to
    subject = request.forms.subject
    body = request.forms.body
    contacts = load_contacts()

    error = check_compose(to, subject, body, contacts)
    if error:
        return page("Compose error", f"""
        <p>{html.escape(error)}</p>
        <p><a href="/compose">[back]</a></p>
        """)

    payload = build_compose_payload(to, subject, body)

    with open(REQUEST_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    result = subprocess.run(
        ["bash", SEND_SCRIPT, REQUEST_JSON],
        capture_output=True, text=True
    )

    contact_name = next((name for name, addr in contacts if addr == to), to)

    if result.returncode == 0:
        return page("Sent", f"""
        <p>Sent to {html.escape(contact_name)}</p>
        <p><a href="/list">[list]</a></p>
        """)
    else:
        return page("Send failed", f"""
        <p><strong>Send failed</strong></p>
        <p>{html.escape(result.stdout + result.stderr)}</p>
        <p><a href="/compose">[try again]</a></p>
        """)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
