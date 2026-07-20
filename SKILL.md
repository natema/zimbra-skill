---
name: zimbra-mail
description: >-
  Read, search, and draft email on any Zimbra mailbox (e.g. university/lab
  Zimbra, RENATER Partage, Inria, CNRS) via IMAP/SMTP using the dependency-free
  zmail.py CLI. Use when the user wants to check their Zimbra inbox, summarize or
  find messages, or prepare a reply as a draft they can review in webmail. Drafts
  are staged by default; sending is separate and requires explicit confirmation.
---

# Zimbra mail (zmail)

A stdlib-only Python CLI (`zmail.py`) over Zimbra IMAP/SMTP. Accounts and
credentials live in `~/.config/zimbra/config.toml` (never in the repo).

**Safety posture:** the default action STAGES a draft in the user's Drafts folder
(visible/editable/sendable from Zimbra webmail). Only run `send` after the user
explicitly asks to send, and it still requires `--yes-really-send`.

## Setup check (do this first if anything fails)

```bash
python3 zmail.py accounts          # lists configured accounts; proves config loads
```
If it errors about missing config, the user hasn't created
`~/.config/zimbra/config.toml` yet — point them to `README.md` / `config.example.toml`.
If IMAP login fails, the connection worked but credentials were rejected: check the
`username` form, or (if 2FA is on) use an **application passcode** generated in webmail
(Preferences > Accounts > Applications > Add Application Code).

## Reading

```bash
# newest 20 in INBOX (• marks unread). Add --unread for only-unread.
python3 zmail.py -a work check --limit 20
python3 zmail.py -a work check --unread --json      # JSON for parsing

python3 zmail.py -a work folders                     # list folders
python3 zmail.py -a work read 12345                  # full message by UID
python3 zmail.py -a work read 12345 --json           # structured (has message_id)
python3 zmail.py -a work search "grant deadline" --limit 10
```

`check`/`search` print a UID in `[brackets]`; feed that UID to `read`.
`read --json` returns `message_id` — pass it to `--in-reply-to` for threaded replies.

## Drafting (default, safe)

```bash
python3 zmail.py -a work draft \
  --to "someone@example.org" \
  --subject "Re: paper" \
  --body-file /path/to/body.txt          # or --body "short text"

# threaded reply:
python3 zmail.py -a work draft --to "x@y.z" --subject "Re: ..." \
  --in-reply-to "<original-message-id>" --body-file body.txt

# with attachments (repeat --attach; MIME type guessed from extension):
python3 zmail.py -a work draft --to "x@y.z" --subject "Report" \
  --body-file body.txt --attach report.pdf --attach data.csv
```

### Replying to a message (preferred for replies)

`reply <UID>` auto-fills the recipient, `Re:` subject, and threading headers from the
original — no need to look up the Message-ID yourself. Stages a draft by default.

```bash
# find the UID with check/search, then:
python3 zmail.py -a work reply 12345 --body-file reply.txt          # To: sender
python3 zmail.py -a work reply 12345 --body-file reply.txt --reply-all
python3 zmail.py -a work reply 12345 --body-file reply.txt --quote  # include quoted original
python3 zmail.py -a work reply 12345 --folder Archive --body-file reply.txt
```
Use `reply` instead of `draft --in-reply-to` when responding to an existing message.
It defaults to a draft; only add `--yes-really-send` if the user explicitly asks to send.
For multi-line/accented bodies, write the body to a temp file and use `--body-file`
(avoids shell-quoting problems). Then tell the user the draft is in webmail Drafts.

## Sending (only on explicit request)

```bash
python3 zmail.py -a work send --to "x@y.z" --subject "..." \
  --body-file body.txt --yes-really-send
```
Never add `--yes-really-send` unless the user has clearly said to send. Prefer
`draft` and let the human hit send.

## Conventions
- Replace `work` with the relevant account name; omit `-a` to use the config default.
- Use `--json` when you need to parse; plain text when showing the user.
- Don't `--mark-read` unless asked; reading is read-only by default.
- UIDs are per-folder; the same message has different UIDs in different folders.
