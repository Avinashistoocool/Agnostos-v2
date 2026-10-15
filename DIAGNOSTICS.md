# Agnostos diagnostics

Use this when something isn't working. Start with the quick check, then find your error message in the tables below.

> **Never paste your `.env` or passwords** into an issue or chat. Redact API keys and `SMTP_PASSWORD`/`IMAP_PASSWORD`.

---

## 1. Quick health check (2 minutes)

Run these from the repo folder, with the virtual environment active:

```bash
python --version                         # must be 3.10+
python -m outreach.cli tls-check         # certificates + reachability of SMTP, IMAP, LLM, OpenAlex
python -m outreach.cli profile           # resume parsing
python -m outreach.cli models            # LLM key works, model list
python -m outreach.cli stats             # workbook funnel + "why so few were sent"
python -m outreach.cli send --dry-run --preview 1   # drafts load, nothing is sent
python -m outreach.cli check-replies --dry-run      # IMAP login + reply detection
```

| Command | Healthy output |
|---|---|
| `tls-check` | `ok` on every host, and a trust source of "OS trust store (truststore)" or a certifi path |
| `profile` | your name, email, interests and projects |
| `models` | a list of model IDs |
| `stats` | counts, plus a "Why so few were sent" list if anything is blocked |
| `send --dry-run` | `dry-run` lines, then `failed=0` |
| `check-replies --dry-run` | `Folders: INBOX, ...`, then a summary |

The first command that fails tells you which section below to read.

---

## 2. Certificates / TLS

**Symptoms**
```
ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1144)
```
You may also see `APIConnectionError: Connection error.` from the LLM, or empty results from `verify`/`discover`.

**Cause.** Python can't find a CA store. This happens almost always with **python.org Python on macOS**, which ships without certificates. It also happens on Windows with some university chains, and behind antivirus or corporate proxies that inspect HTTPS.

**Fix, in order:**
1. `pip install -U truststore certifi`. Agnostos then uses the OS trust store (Keychain, Windows CertStore or `/etc/ssl`).
2. macOS python.org build: double-click `/Applications/Python 3.x/Install Certificates.command`.
3. Linux: `sudo apt install --reinstall ca-certificates` (or your distro's equivalent).
4. Behind a proxy or antivirus that inspects TLS, export its root CA and set:
   `SSL_CERT_FILE=/path/to/root.pem` (Windows: `$env:SSL_CERT_FILE="C:\path\root.pem"`)
5. Re-run `python -m outreach.cli tls-check`.

Never "fix" this by turning verification off.

---

## 3. Sending (SMTP)

| Error | Meaning | Fix |
|---|---|---|
| `SMTPAuthenticationError` (535) | Login rejected | Use an **app password** (Gmail/iCloud), not your normal password. Check `SMTP_USER` is the full address |
| `SMTPSenderRefused` | From address not allowed | `SMTP_FROM` must equal the mailbox in `SMTP_USER` |
| `SMTPServerDisconnected: Connection unexpectedly closed` / `read operation timed out` | The server dropped the session. University relays drop idle sessions after about 2 minutes | Agnostos reconnects before each email and retries the connection 3 times. If it persists: raise `SEND_DELAY_MIN`, lower `DAILY_SEND_CAP`, and wait an hour, because you may be temporarily rate-limited |
| `SMTPConnectError` / `TimeoutError` on connect | Can't reach host:port | Check `SMTP_HOST`/`SMTP_PORT`/`SMTP_SECURITY` (465 uses `ssl`, 587 uses `starttls`). Some networks and VPS providers block SMTP ports, so try another network |
| `SMTPRecipientsRefused` | Bad recipient address | Run `verify --repair --apply` on that row |
| `SMTPDataError` (550/554) | Message rejected, often as spam | Shorten the draft, remove links, send fewer per day |
| `! Stopped: 3 consecutive SMTP failures` | Safety stop | The rest stay unsent and safe. Fix the cause above and re-run |
| `skipped: invalid address` | `verify` marked it undeliverable | `verify --repair --apply`, or `--allow-unverified` if you're sure |
| `held ... outside local window` | It's outside 9-17 for that professor | Expected. Re-run later or add `--wait` |
| `is open in Excel (or otherwise locked)` | Workbook locked | Close Excel. If a sidecar `.pending-status.json` exists, it is merged automatically |

**Is my account flagged?** Check these signs:
- Your own sent copies arrive in your inbox fine, but professors say they got nothing: you're probably landing in spam.
- Many `bounced` rows in `check-replies` with "rejected" or "blocked" wording.
- Login suddenly fails after many sends.

If you see these, stop for 24-48 hours, then resume at 20-30 per day.

**Test SMTP without emailing anyone:**
```bash
python -m outreach.cli send --review --top 1     # sends one draft to YOU
```

---

## 4. Reading replies (IMAP)

| Error | Fix |
|---|---|
| `IMAP failed: ... AUTHENTICATIONFAILED` | Set `IMAP_USER`/`IMAP_PASSWORD`, which default to the SMTP ones. Gmail needs IMAP enabled in settings and an app password |
| `IMAP failed: ... getaddrinfo failed` | `IMAP_HOST` is wrong. It defaults to `imap.<smtp domain>`, so set it explicitly |
| Replies exist but aren't detected | They may be in a folder that isn't scanned. Set `IMAP_FOLDERS=INBOX;Spam;Junk;<folder>` |
| `replies` finds threads but no "student" messages | Your server doesn't keep a Sent copy. That's fine, because the original email is taken from the workbook |

---

## 5. Drafting (LLM)

| Error / symptom | Fix |
|---|---|
| `~ endpoint rejected structured outputs ... retrying without it` | Normal. The endpoint doesn't support that feature and Agnostos adapts |
| `response truncated; raise MAX_OUTPUT_TOKENS` | Reasoning models (gpt-5, o-series) use hidden tokens. Agnostos now raises the budget automatically. For other models, set `MAX_OUTPUT_TOKENS=3000` |
| `Three consecutive failures; aborting to avoid wasted spend` | Look at the `LLM Status` column for the real error, then re-run `run` |
| `AuthenticationError` / 401 | Wrong or expired API key |
| `NotFoundError` / model not found | Check `DRAFT_MODEL` against `python -m outreach.cli models` |
| `RateLimitError` / 429 | Groq free tier limit. Wait a minute, lower `--max-professors`, or switch provider |
| `Set DRAFT_MODEL in .env` | Add `DRAFT_MODEL=...` |
| Drafts sound robotic | Keep `HUMANIZE_REWRITE=true` and lower `HUMANIZE_THRESHOLD` |

---

## 6. Finding professors and emails

| Symptom | Fix |
|---|---|
| `OpenAlex rate limit hit` | Set `OPENALEX_MAILTO=you@...` (polite pool), or get a free `OPENALEX_API_KEY` |
| Many `invalid` / `no address on this row` | `verify --repair --apply --workers 6`. Some professors don't publish an address, and those are left blank on purpose |
| `discover` finds too few | Broaden `--query` topics, widen `--countries`, lower `--min-h-index` |
| `verify` very slow | Lower `--workers` if you get blocked, or raise it if your network is fast |

---

## 7. Interruptions (sleep, crash, power cut)

Nothing that was sent is ever lost or re-sent.

1. Check whether a send is still running:
   - Windows: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match "send --live"`
   - macOS/Linux: `pgrep -af "outreach.cli send"`
2. Check what happened: `tail -n 40 output/daily_send.log` (Windows: `Get-Content output\daily_send.log -Tail 40`)
3. Check the counts: `python -m outreach.cli stats`
4. If nothing is running and rows are still unsent, re-run the same `send --live ...` command. It continues from where it stopped.

Windows sleep and wake history: `Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter'} -MaxEvents 20`
macOS: `pmset -g log | grep -E "Sleep|Wake" | tail -20` · Linux: `journalctl -b -u systemd-suspend`

---

## 8. Workbook problems

| Symptom | Fix |
|---|---|
| `PermissionError` / `is open in Excel` | Close Excel or LibreOffice |
| Columns not recognised | Headers must include a name column and an email column. See README "header mapping" |
| Something got overwritten | Restore from `output/professors.backup-YYYYMMDD-HHMMSS.xlsx` |
| Statuses "missing" after a run | Look for `professors.xlsx.pending-status.json`. It is merged on the next run, or run `stats` (which already counts it) |

---

## 9. Reporting a bug

Include:
1. Your OS and `python --version`
2. The exact command you ran
3. The full error output, with **emails, keys and passwords redacted**
4. The output of `python -m outreach.cli tls-check` and `python -m outreach.cli stats`
5. The last 40 lines of `output/daily_send.log`, if it was a scheduled send

Open an issue at https://github.com/Avinashistoocool/Agnostos-v2/issues.
