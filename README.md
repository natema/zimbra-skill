# zimbra-skill · `zmail`

A tiny, **dependency-free** command-line tool to **read, search, draft, and reply to
email on any Zimbra mailbox** over standard IMAP/SMTP.

It's just a CLI, so **any AI agent or automation can drive it** — Claude, ChatGPT/Codex,
a cron job, a shell script — by running commands and reading their (optionally JSON)
output. No server, no MCP endpoint, nothing to `pip install`: a single Python
standard-library file. It also ships with a ready-made [Claude Code](https://docs.claude.com/en/docs/claude-code)
skill (`SKILL.md`) for zero-config use there.

Drafts you stage appear in **Zimbra webmail's Drafts folder**, ready for you to
review and send. Sending is a separate, explicitly-confirmed command — the agent
never sends mail on its own.

```text
$ zmail check --unread
• [ 4821] Tue, 15 Jul 2026   program-chairs@confer…   Reviews for submission #217 are available
  [ 4817] Mon, 14 Jul 2026   coauthor@example.org     Re: draft of section 4
```

## Why another email tool?

Zimbra + AI already exists as **MCP servers** (which need a running server process,
a runtime, and client wiring), and there are **generic** IMAP/SMTP tools for agents.
This project fills a different niche:

- **A CLI, not a server.** No daemon, no npm, no MCP endpoint. Any agent or script
  can call it; a Claude Code skill is included but not required.
- **Zero dependencies.** One `python3` stdlib file. Nothing to `pip install`.
- **Zimbra-aware.** Drafts land in webmail via IMAP `APPEND`; it works around a
  Zimbra IMAP-proxy quirk in `FLAGS` reporting; and it documents the auth gotchas of
  real-world academic Zimbra (Inria, CNRS, RENATER Partage).
- **Draft-first and safe.** The default action stages a draft; `send` refuses to run
  without `--yes-really-send`.

## Requirements

- **Python 3.11+** (uses the stdlib `tomllib`; nothing else).
- A Zimbra account reachable over IMAPS/SMTP (most are).

## Install

```bash
git clone https://github.com/natema/zimbra-skill.git
cd zimbra-skill
python3 zmail.py --help          # standalone CLI works immediately
```

Use it as a **Claude Code skill** by symlinking it into your skills directory:

```bash
ln -s "$PWD" ~/.claude/skills/zimbra-mail
```

Claude will then invoke it (e.g. `/zimbra-mail`) or trigger it when you ask it to
check or draft mail. See [`SKILL.md`](SKILL.md) for the agent-facing instructions.

### With any other agent

There's nothing Claude-specific about the tool itself. To use it from another agent
or harness (ChatGPT/Codex, a custom bot, an automation), just let it run `zmail.py`
and read the output — `--json` gives structured results. The command reference in
[`SKILL.md`](SKILL.md) is a good, compact prompt to hand the agent so it knows the
available verbs and the draft-first workflow.

## Configure

```bash
mkdir -p ~/.config/zimbra
cp config.example.toml ~/.config/zimbra/config.toml
chmod 600 ~/.config/zimbra/config.toml
$EDITOR ~/.config/zimbra/config.toml
```

Each account is a `[accounts.<name>]` block. Server settings for common Zimbra
services (fill in your own address/login):

| Service | IMAP | SMTP |
|---|---|---|
| Generic Zimbra | `mail.example.org:993` (SSL) | `mail.example.org:587` (STARTTLS) |
| Inria | `zimbra.inria.fr:993` (SSL) | `smtp.inria.fr:587` (STARTTLS) |
| CNRS (central) | `webmail.cnrs.fr:993` (SSL) | `webmail.cnrs.fr:465` (SSL) |
| RENATER Partage | `imap.partage.renater.fr:993` (SSL) | `smtp.partage.renater.fr:465` (SSL) |

> **Login vs. email.** `username` is the account **login**, which may differ from
> your display address (a short Unix login at some sites, or a hosting-provider
> backend address at others). Copy it verbatim from webmail *Preferences → Accounts*
> or an existing mail client.

## Authentication setup

Each account picks exactly one password source: `password_cmd` (a shell command whose
stdout is the password), `password_env` (an env-var name), or inline `password`.

### Recommended: a file-based secret

A keyring (`secret-tool`, `pass`) is a poor fit on a headless server: the login
keyring is often missing or stays **locked** on key-based SSH logins, so an
unattended lookup fails. A `chmod 600` file that only you can read is simpler and
works every time.

1. Point the account at a secret file in `config.toml`:
   ```toml
   password_cmd = "cat ~/.config/zimbra/work.pass"
   ```
2. Write the password/passcode into that file **without it touching your shell
   history or the command line** (silent read, `600` perms via `umask`):
   ```bash
   (umask 077; printf 'IMAP password/passcode: '; read -rs P; \
     printf '%s' "$P" > ~/.config/zimbra/work.pass; unset P; echo)
   ```
3. Sanity-check (shows size, not contents) — expect `-rw-------`:
   ```bash
   ls -l ~/.config/zimbra/*.pass
   ```

A trailing newline in the file is harmless (only the first line is used). To rotate,
re-run the write command; to revoke, delete the file (and the app-passcode in webmail
if you made one).

### Alternatives

- **Env var** — `password_env = "ZMAIL_WORK_PASSWORD"`, then export it (e.g. from a
  sourced, `600`-permission file).
- **Inline** — `password = "…"` directly in `config.toml`. Simplest; acceptable only
  because the file is `chmod 600` and an app-passcode is revocable.
- **Keyring / `pass`** — fine on an unlocked desktop keyring, e.g.
  `password_cmd = "secret-tool lookup service zimbra account work"`. Not recommended
  on headless hosts, for the reason above.

### Two-factor auth

If the account has 2FA, your normal password is rejected over IMAP/SMTP. Generate an
**application passcode** in webmail (*Preferences → Accounts → Applications → Add
Application Code*) and use that as the secret instead.

### Debugging login

If a command prints `IMAP login failed`, the connection to the server **succeeded**
but the credentials were rejected — it's the `username` form or the password/passcode,
not the host. Fix those rather than hammering retries (accounts can lock out).

## Usage

```bash
python3 zmail.py -a work check [--unread] [--limit N] [--folder INBOX]
python3 zmail.py -a work read <UID> [--folder INBOX] [--mark-read]
python3 zmail.py -a work search "term" [--limit N]
python3 zmail.py -a work folders
python3 zmail.py -a work draft --to X --subject S (--body T | --body-file F) \
                     [--cc ...] [--attach FILE ...] [--in-reply-to <msg-id>]
python3 zmail.py -a work reply <UID> (--body T | --body-file F) \
                     [--reply-all] [--cc ...] [--attach FILE ...] [--quote]
python3 zmail.py -a work send  ... --yes-really-send        # guarded
python3 zmail.py accounts
```

- Omit `-a/--account` to use the `default` from your config.
- Add `--json` to any read command for machine-readable output (handy for agents).
- Attach files with `--attach PATH` (repeat for several); the MIME type is guessed
  from the extension. Works for `draft`, `reply`, and `send`.
- `check`/`search` print a `UID` in `[brackets]`; pass it to `read`. `read --json`
  includes the `message_id`, which you feed to `--in-reply-to` for a threaded reply.

### Replying

`reply <UID>` is a shortcut that reads the original message and pre-fills the reply:
recipient (its `Reply-To`/`From`), a `Re:` subject, and the `In-Reply-To`/`References`
threading headers. Add `--reply-all` to Cc the original recipients (minus yourself),
`--quote` to append the quoted original, and `--attach` for files. It stages a **draft**
by default; pass `--yes-really-send` to send it immediately instead.

### How drafting works

`draft` builds a MIME message (with `In-Reply-To`/`References` when replying) and
IMAP-`APPEND`s it to your `Drafts` folder with the `\Draft` flag. It then shows up in
Zimbra webmail exactly like a draft you started there — edit and send it from any
device. This keeps a human in the loop by design.

## Security

- Your real `config.toml` lives **outside** the repo (`~/.config/zimbra/`) and is
  `.gitignore`d regardless.
- Prefer `password_cmd`/`password_env` over inline passwords; `chmod 600` either way.
- The agent stages **drafts** by default and cannot send without `--yes-really-send`.
- Nothing is transmitted anywhere except your own Zimbra server over TLS.

## Roadmap / ideas

- Optional Zimbra **SOAP** backend for calendar/contacts and native draft save.
- `XOAUTH2`/OAuth2 authentication for providers that require it.
- HTML-body composition (bodies are plain text today).

Contributions welcome — it's deliberately small; keep it dependency-free.

## License

[MIT](LICENSE) © 2026 Emanuele Natale · contact: emanuele.natale@cnrs.fr
