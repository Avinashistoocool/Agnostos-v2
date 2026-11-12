# Agnostos diagnostics

Use this page when a function of the tool does not work. Start with the quick check. Then find your error message in the tables below.

> **Never paste your `.env` or your passwords** into an issue or a chat. Remove API keys and `SMTP_PASSWORD`/`IMAP_PASSWORD` first.

---

## 1. Quick health check (2 minutes)

Run these commands from the folder of the repository, with the virtual environment active:

```bash
python --version                         # must be 3.10+
python -m outreach.cli tls-check         # certificates + reachability of SMTP, IMAP, LLM, OpenAlex
python -m outreach.cli profile           # resume parsing
python -m outreach.cli models            # LLM key works, model list
python -m outreach.cli stats             # workbook funnel + "why so few were sent"
python -m outreach.cli send --dry-run --preview 1   # drafts load, nothing is sent
python -m outreach.cli check-replies --dry-run      # IMAP login + reply detection
```

| Command | Correct output |
|---|---|
| `tls-check` | `ok` on each host, and a trust source of "OS trust store (truststore)" or a certifi path |
| `profile` | your name, email, interests and projects |
| `models` | a list of model IDs |
| `stats` | counts, plus a "Why so few were sent" list if the tool blocks some rows |
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
You can also see `APIConnectionError: Connection error.` from the LLM, or empty results from `verify`/`discover`.

**Cause.** Python cannot find a CA store. This occurs almost always with **python.org Python on macOS**, because that Python has no certificates. It also occurs on Windows with some university certificate chains. It also occurs behind antivirus software or company proxies that inspect HTTPS.

**Fix, in sequence:**
1. Run `pip install -U truststore certifi`. Then Agnostos uses the trust store of the OS (Keychain, Windows CertStore or `/etc/ssl`).
2. For the python.org build on macOS, double-click `/Applications/Python 3.x/Install Certificates.command`.
3. On Linux, run `sudo apt install --reinstall ca-certificates` (or the equivalent command of your distribution).
4. Behind a proxy or antivirus software that inspects TLS, export its root CA and set:
   `SSL_CERT_FILE=/path/to/root.pem` (Windows: `$env:SSL_CERT_FILE="C:\path\root.pem"`)
5. Run `python -m outreach.cli tls-check` again.

Do not turn off verification to "fix" this problem.

---

## 3. Sending (SMTP)

| Error | Meaning | Fix |
|---|---|---|
| `SMTPAuthenticationError` (535) | The server rejected the login | Use an **app password** (Gmail/iCloud), not your usual password. Make sure that `SMTP_USER` is the full address |
| `SMTPSenderRefused` | The server does not accept the From address | `SMTP_FROM` must be the same as the mailbox in `SMTP_USER` |
| `SMTPServerDisconnected: Connection unexpectedly closed` / `read operation timed out` | The server closed the session. University relays close idle sessions after about 2 minutes | Agnostos connects again before each email, and tries the connection 3 times. If the problem continues: increase `SEND_DELAY_MIN`, decrease `DAILY_SEND_CAP`, and wait one hour. The server possibly applies a temporary rate limit |
| `SMTPConnectError` / `TimeoutError` on connect | The tool cannot connect to host:port | Check `SMTP_HOST`/`SMTP_PORT`/`SMTP_SECURITY` (465 uses `ssl`, 587 uses `starttls`). Some networks and VPS providers block SMTP ports. Try a different network |
| `SMTPRecipientsRefused` | Incorrect recipient address | Run `verify --repair --apply` on that row |
| `SMTPDataError` (550/554) | The server rejected the message, frequently as spam | Make the draft shorter, remove links, and send fewer emails each day |
| `! Stopped: 3 consecutive SMTP failures` | Safety stop | The remaining rows stay unsent and safe. Fix the cause above and run the command again |
| `skipped: invalid address` | `verify` marked the address as undeliverable | Run `verify --repair --apply`. If you are sure that the address is correct, use `--allow-unverified` |
| `held ... outside local window` | The time is outside 9-17 for that professor | This is correct behaviour. Run the command again later, or add `--wait` |
| `is open in Excel (or otherwise locked)` | The workbook is locked | Close Excel. If a sidecar `.pending-status.json` file exists, the tool merges it automatically |

**Does the provider flag my account?** Look for these signs:
- Your own sent copies arrive in your inbox correctly, but professors say that they got nothing. Your emails probably go to spam.
- `check-replies` shows many `bounced` rows with the words "rejected" or "blocked".
- The login fails suddenly after many sends.

If you see these signs, stop for 24-48 hours. Then start again at 20-30 emails each day.

**Test SMTP without an email to a professor:**
```bash
python -m outreach.cli send --review --top 1     # sends one draft to YOU
```

---

## 4. Reading replies (IMAP)

| Error | Fix |
|---|---|
| `IMAP failed: ... AUTHENTICATIONFAILED` | Set `IMAP_USER`/`IMAP_PASSWORD`. By default, they are the same as the SMTP values. For Gmail, enable IMAP in the settings and use an app password |
| `IMAP failed: ... getaddrinfo failed` | `IMAP_HOST` is incorrect. Its default is `imap.<smtp domain>`. Set it explicitly |
| Replies exist, but the tool does not find them | They are possibly in a folder that the tool does not scan. Set `IMAP_FOLDERS=INBOX;Spam;Junk;<folder>` |
| `replies` finds threads but no "student" messages | Your server does not keep a Sent copy. This is not a problem, because the tool gets the original email from the workbook |

---

## 5. Drafting (LLM)

| Error / symptom | Fix |
|---|---|
| `~ endpoint rejected structured outputs ... retrying without it` | This is usual. The endpoint does not support that function, and Agnostos adapts |
| `response truncated; raise MAX_OUTPUT_TOKENS` | Reasoning models (gpt-5, o-series) use hidden tokens. Agnostos now increases the budget automatically. For other models, set `MAX_OUTPUT_TOKENS=3000` |
| `Three consecutive failures; aborting to avoid wasted spend` | Look at the `LLM Status` column for the real error. Then run `run` again |
| `AuthenticationError` / 401 | The API key is incorrect or expired |
| `NotFoundError` / model not found | Compare `DRAFT_MODEL` with the output of `python -m outreach.cli models` |
| `RateLimitError` / 429 | Limit of the Groq free tier. Wait one minute, decrease `--max-professors`, or change the provider |
| `Set DRAFT_MODEL in .env` | Add `DRAFT_MODEL=...` |
| Drafts sound like a machine | Keep `HUMANIZE_REWRITE=true` and decrease `HUMANIZE_THRESHOLD` |

---

## 6. Finding professors and emails

| Symptom | Fix |
|---|---|
| `OpenAlex rate limit hit` | Set `OPENALEX_MAILTO=you@...` (polite pool), or get a free `OPENALEX_API_KEY` |
| Many `invalid` / `no address on this row` | Run `verify --repair --apply --workers 6`. Some professors do not publish an address. The tool intentionally keeps those cells blank |
| `discover` finds too few persons | Use wider `--query` topics and more `--countries`, and decrease `--min-h-index` |
| `verify` is too slow | If sites block you, decrease `--workers`. If your network is fast, increase it |

---

## 7. Interruptions (sleep, crash, power cut)

The tool never loses or sends again an email that it sent.

1. Find out if a send is still active:
   - Windows: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match "send --live"`
   - macOS/Linux: `pgrep -af "outreach.cli send"`
2. Find out what occurred: `tail -n 40 output/daily_send.log` (Windows: `Get-Content output\daily_send.log -Tail 40`)
3. Check the counts: `python -m outreach.cli stats`
4. If no send is active and some rows are still unsent, run the same `send --live ...` command again. It continues from the point where it stopped.

Windows sleep and wake history: `Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter'} -MaxEvents 20`
macOS: `pmset -g log | grep -E "Sleep|Wake" | tail -20` · Linux: `journalctl -b -u systemd-suspend`

---

## 8. Workbook problems

| Symptom | Fix |
|---|---|
| `PermissionError` / `is open in Excel` | Close Excel or LibreOffice |
| The tool does not recognise the columns | The headers must include a name column and an email column. See "header mapping" in the README |
| The tool overwrote data | Restore the data from `output/professors.backup-YYYYMMDD-HHMMSS.xlsx` |
| Statuses are "missing" after a run | Look for `professors.xlsx.pending-status.json`. The tool merges it on the next run. Alternatively, run `stats` (it already counts that file) |

---

## 9. Reporting a bug

Include these items:
1. Your OS and the output of `python --version`
2. The exact command that you ran
3. The full error output, with **emails, keys and passwords removed**
4. The output of `python -m outreach.cli tls-check` and `python -m outreach.cli stats`
5. The last 40 lines of `output/daily_send.log`, if the problem occurred during a scheduled send

Open an issue at https://github.com/Avinashistoocool/Agnostos-v2/issues.
