#!/usr/bin/env python3
"""zmail — a tiny, dependency-free CLI over Zimbra's IMAP/SMTP interfaces.

Designed so an agent (or a human) can: list/read mail, search, and stage
*drafts* that show up in Zimbra webmail's Drafts folder for human review.
Sending is a separate, explicitly-confirmed command.

Only the Python standard library is used (imaplib, smtplib, email, tomllib).

Config lives OUTSIDE this repo, default: ~/.config/zimbra/config.toml
(override with $ZMAIL_CONFIG). See config.example.toml.
"""
from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import mimetypes
import os
import smtplib
import ssl
import subprocess
import sys
import tomllib
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any

__version__ = "0.1.0"


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def config_path() -> Path:
    return Path(os.environ.get("ZMAIL_CONFIG", Path.home() / ".config/zimbra/config.toml"))


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        die(f"No config at {path}. Copy config.example.toml there and fill it in.")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def get_account(cfg: dict[str, Any], name: str | None) -> tuple[str, dict[str, Any]]:
    accounts = cfg.get("accounts", {})
    if not accounts:
        die("Config has no [accounts.*] sections.")
    if name is None:
        name = cfg.get("default")
        if name is None:
            if len(accounts) == 1:
                name = next(iter(accounts))
            else:
                die(f"No account given and no default set. Accounts: {', '.join(accounts)}")
    if name not in accounts:
        die(f"Unknown account '{name}'. Known: {', '.join(accounts)}")
    return name, accounts[name]


def resolve_password(acct: dict[str, Any]) -> str:
    """Password sources, in priority order: command, env var, inline."""
    if cmd := acct.get("password_cmd"):
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if out.returncode != 0:
            die(f"password_cmd failed: {out.stderr.strip()}")
        return out.stdout.splitlines()[0] if out.stdout else ""
    if env := acct.get("password_env"):
        val = os.environ.get(env)
        if val is None:
            die(f"password_env '{env}' is not set in the environment.")
        return val
    if "password" in acct:
        return acct["password"]
    die("No password source configured (password_cmd / password_env / password).")


# --------------------------------------------------------------------------- #
# IMAP helpers
# --------------------------------------------------------------------------- #
def imap_connect(acct: dict[str, Any]) -> imaplib.IMAP4:
    host = acct.get("imap_host") or die("account missing imap_host")
    port = int(acct.get("imap_port", 993))
    user = acct.get("username") or acct.get("email") or die("account missing username/email")
    pw = resolve_password(acct)
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    try:
        conn.login(user, pw)
    except imaplib.IMAP4.error as e:
        die(f"IMAP login failed for {user}@{host}: {e}\n"
            "  If 2FA is on, generate an application passcode in Zimbra:\n"
            "  Preferences > Accounts > Applications > Add Application Code.")
    return conn


def _decode(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _imap_check(typ: str, data: Any, what: str) -> Any:
    if typ != "OK":
        die(f"IMAP {what} failed: {data!r}")
    return data


def parse_message(raw_bytes: bytes) -> dict[str, Any]:
    msg = email.message_from_bytes(raw_bytes)
    body = extract_text(msg)
    return {
        "from": _decode(msg.get("From")),
        "to": _decode(msg.get("To")),
        "cc": _decode(msg.get("Cc")),
        "date": _decode(msg.get("Date")),
        "subject": _decode(msg.get("Subject")),
        "message_id": (msg.get("Message-ID") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
        "references": (msg.get("References") or "").strip(),
        "body": body,
    }


def extract_text(msg: email.message.Message) -> str:
    """Prefer text/plain; fall back to a crude strip of text/html."""
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                plain = _part_text(part)
            elif ctype == "text/html" and html is None:
                html = _part_text(part)
    else:
        if msg.get_content_type() == "text/html":
            html = _part_text(msg)
        else:
            plain = _part_text(msg)
    if plain:
        return plain.strip()
    if html:
        import re
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        import html as _h
        return _h.unescape(text).strip()
    return ""


def _part_text(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_accounts(args: argparse.Namespace) -> None:
    cfg = load_config()
    default = cfg.get("default")
    rows = []
    for name, a in cfg.get("accounts", {}).items():
        rows.append({
            "name": name,
            "default": name == default,
            "email": a.get("email"),
            "imap": f"{a.get('imap_host')}:{a.get('imap_port', 993)}",
            "smtp": f"{a.get('smtp_host')}:{a.get('smtp_port', 587)}",
        })
    emit(args, rows, lambda: "\n".join(
        f"{'* ' if r['default'] else '  '}{r['name']:8} {r['email'] or '?':32} "
        f"imap={r['imap']} smtp={r['smtp']}" for r in rows))


def cmd_folders(args: argparse.Namespace) -> None:
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    conn = imap_connect(acct)
    try:
        typ, data = conn.list()
        _imap_check(typ, data, "LIST")
        names = []
        for line in data:
            if line is None:
                continue
            decoded = line.decode() if isinstance(line, bytes) else str(line)
            # folder name is the last quoted token
            name = decoded.split(' "/" ')[-1].strip().strip('"')
            names.append(name)
        emit(args, names, lambda: "\n".join(names))
    finally:
        conn.logout()


def cmd_check(args: argparse.Namespace) -> None:
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    conn = imap_connect(acct)
    try:
        typ, _ = conn.select(f'"{args.folder}"', readonly=True)
        _imap_check(typ, _, f"SELECT {args.folder}")
        criteria = "UNSEEN" if args.unread else "ALL"
        typ, data = conn.uid("search", None, criteria)
        _imap_check(typ, data, "SEARCH")
        uids = data[0].split()
        uids = uids[-args.limit:][::-1]  # newest first
        # Determine unread status via a dedicated UNSEEN search: fetching FLAGS
        # alongside a literal is unreliable (some servers, notably Zimbra's IMAP
        # proxy, return FLAGS *after* the literal, where ParseFlags won't see them).
        typ, unseen_data = conn.uid("search", None, "UNSEEN")
        unseen = set(unseen_data[0].split()) if typ == "OK" and unseen_data[0] else set()
        rows = []
        for uid in uids:
            typ, fetched = conn.uid(
                "fetch", uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not fetched or fetched[0] is None:
                continue
            header_bytes = fetched[0][1]
            hmsg = email.message_from_bytes(header_bytes)
            rows.append({
                "uid": uid.decode(),
                "unread": uid in unseen,
                "date": _decode(hmsg.get("Date")),
                "from": _decode(hmsg.get("From")),
                "subject": _decode(hmsg.get("Subject")),
            })
        emit(args, rows, lambda: _fmt_list(rows))
    finally:
        conn.logout()


def cmd_read(args: argparse.Namespace) -> None:
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    conn = imap_connect(acct)
    try:
        typ, _ = conn.select(f'"{args.folder}"', readonly=not args.mark_read)
        _imap_check(typ, _, f"SELECT {args.folder}")
        typ, fetched = conn.uid("fetch", args.uid.encode(), "(RFC822)")
        _imap_check(typ, fetched, "FETCH")
        if not fetched or fetched[0] is None:
            die(f"No message with UID {args.uid} in {args.folder}.")
        parsed = parse_message(fetched[0][1])
        parsed["uid"] = args.uid
        emit(args, parsed, lambda: _fmt_message(parsed))
    finally:
        conn.logout()


def cmd_search(args: argparse.Namespace) -> None:
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    conn = imap_connect(acct)
    try:
        typ, _ = conn.select(f'"{args.folder}"', readonly=True)
        _imap_check(typ, _, f"SELECT {args.folder}")
        # Search FROM/SUBJECT/BODY for the term; charset UTF-8 for accents.
        term = args.query
        typ, data = conn.uid(
            "search", "UTF-8",
            "OR", "OR", "FROM", _q(term), "SUBJECT", _q(term), "BODY", _q(term))
        if typ != "OK":  # some servers dislike charset; retry ASCII SUBJECT-only
            typ, data = conn.uid("search", None, "SUBJECT", _q(term))
        _imap_check(typ, data, "SEARCH")
        uids = data[0].split()[-args.limit:][::-1]
        rows = []
        for uid in uids:
            typ, fetched = conn.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not fetched or fetched[0] is None:
                continue
            hmsg = email.message_from_bytes(fetched[0][1])
            rows.append({
                "uid": uid.decode(),
                "date": _decode(hmsg.get("Date")),
                "from": _decode(hmsg.get("From")),
                "subject": _decode(hmsg.get("Subject")),
            })
        emit(args, rows, lambda: _fmt_list(rows))
    finally:
        conn.logout()


def _q(s: str) -> str:
    return s  # imaplib quotes args containing spaces automatically


def build_message(acct: dict[str, Any], args: argparse.Namespace) -> EmailMessage:
    msg = EmailMessage()
    from_name = acct.get("from_name")
    from_addr = acct.get("email") or die("account missing email")
    msg["From"] = email.utils.formataddr((from_name, from_addr)) if from_name else from_addr
    msg["To"] = args.to
    if args.cc:
        msg["Cc"] = args.cc
    msg["Subject"] = args.subject
    if getattr(args, "in_reply_to", None):
        msg["In-Reply-To"] = args.in_reply_to
        msg["References"] = getattr(args, "references", None) or args.in_reply_to
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text()
    msg.set_content(body or "")
    for path in getattr(args, "attach", None) or []:
        _attach_file(msg, path)
    return msg


def _attach_file(msg: EmailMessage, path: str) -> None:
    p = Path(path).expanduser()
    if not p.is_file():
        die(f"attachment not found: {path}")
    ctype, encoding = mimetypes.guess_type(str(p))
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"  # unknown or compressed -> generic binary
    maintype, subtype = ctype.split("/", 1)
    msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype,
                       filename=p.name)


def cmd_draft(args: argparse.Namespace) -> None:
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    msg = build_message(acct, args)
    conn = imap_connect(acct)
    try:
        folder = args.folder
        raw = msg.as_bytes()
        typ, data = conn.append(f'"{folder}"', "(\\Draft)", None, raw)
        _imap_check(typ, data, f"APPEND to {folder}")
        result = {"status": "draft_saved", "folder": folder,
                  "to": args.to, "subject": args.subject,
                  "detail": data[0].decode() if data and data[0] else ""}
        emit(args, result,
             lambda: f"Draft saved to '{folder}'. Review & send from Zimbra webmail.\n"
                     f"  To: {args.to}\n  Subject: {args.subject}")
    finally:
        conn.logout()


def cmd_send(args: argparse.Namespace) -> None:
    if not args.yes_really_send:
        die("Refusing to send without --yes-really-send. "
            "Use 'draft' to stage for review instead.")
    cfg = load_config()
    _, acct = get_account(cfg, args.account)
    msg = build_message(acct, args)
    host = acct.get("smtp_host") or die("account missing smtp_host")
    port = int(acct.get("smtp_port", 587))
    security = (acct.get("smtp_security") or "starttls").lower()
    user = acct.get("username") or acct.get("email")
    pw = resolve_password(acct)
    ctx = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, context=ctx)
    else:
        server = smtplib.SMTP(host, port)
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
    try:
        server.login(user, pw)
        server.send_message(msg)
    except smtplib.SMTPException as e:
        die(f"SMTP send failed: {e}")
    finally:
        server.quit()
    # Optionally file a copy into Sent (Zimbra usually does NOT auto-save for SMTP)
    if not args.no_save_sent:
        try:
            conn = imap_connect(acct)
            conn.append('"Sent"', "(\\Seen)", None, msg.as_bytes())
            conn.logout()
        except Exception as e:
            print(f"warning: could not save to Sent: {e}", file=sys.stderr)
    emit(args, {"status": "sent", "to": args.to, "subject": args.subject},
         lambda: f"Sent to {args.to}: {args.subject}")


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def emit(args: argparse.Namespace, obj: Any, text_fn) -> None:
    if getattr(args, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(text_fn())


def _fmt_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(no messages)"
    out = []
    for r in rows:
        flag = "•" if r.get("unread") else " "
        out.append(f"{flag} [{r['uid']:>6}] {r.get('date','')[:16]:16}  "
                   f"{r.get('from','')[:30]:30}  {r.get('subject','')}")
    return "\n".join(out)


def _fmt_message(m: dict[str, Any]) -> str:
    hdr = (f"From:    {m['from']}\nTo:      {m['to']}\n"
           f"{('Cc:      ' + m['cc'] + chr(10)) if m['cc'] else ''}"
           f"Date:    {m['date']}\nSubject: {m['subject']}\n"
           f"UID:     {m.get('uid','')}\nMsg-ID:  {m['message_id']}\n"
           f"{'-'*60}")
    return f"{hdr}\n{m['body']}"


def die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="zmail", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-a", "--account", help="account name from config (default: config 'default')")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("accounts", help="list configured accounts").set_defaults(func=cmd_accounts)

    sp = sub.add_parser("folders", help="list IMAP folders")
    sp.set_defaults(func=cmd_folders)

    sp = sub.add_parser("check", help="list recent messages in a folder")
    sp.add_argument("--folder", default="INBOX")
    sp.add_argument("--unread", action="store_true", help="only unread")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("read", help="show one message by UID")
    sp.add_argument("uid")
    sp.add_argument("--folder", default="INBOX")
    sp.add_argument("--mark-read", action="store_true", help="clear the unread flag")
    sp.set_defaults(func=cmd_read)

    sp = sub.add_parser("search", help="search FROM/SUBJECT/BODY for a term")
    sp.add_argument("query")
    sp.add_argument("--folder", default="INBOX")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    for name, help_ in (("draft", "stage a draft in the Drafts folder"),
                        ("send", "send a message via SMTP (guarded)")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--to", required=True)
        sp.add_argument("--subject", required=True)
        sp.add_argument("--body", help="message body text")
        sp.add_argument("--body-file", help="read body from a file")
        sp.add_argument("--cc")
        sp.add_argument("--attach", action="append", metavar="PATH",
                        help="file to attach (repeatable)")
        sp.add_argument("--in-reply-to", help="Message-ID being replied to (for threading)")
        sp.add_argument("--references", help="References header value")
        if name == "draft":
            sp.add_argument("--folder", default="Drafts")
            sp.set_defaults(func=cmd_draft)
        else:
            sp.add_argument("--yes-really-send", action="store_true",
                            help="required confirmation to actually send")
            sp.add_argument("--no-save-sent", action="store_true",
                            help="do not append a copy to the Sent folder")
            sp.set_defaults(func=cmd_send)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
