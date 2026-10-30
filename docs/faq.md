# Agnostos FAQ

These are common questions about using Agnostos (v2, the command-line tool). For setup, see the guide for your OS: [Windows](install-windows.md) · [macOS](install-macos.md) · [Linux](install-linux.md). If something is broken, go to [Diagnostics](diagnostics.md).

---

## General

**What does Agnostos actually do?**
It reads your resume and finds professors whose recent papers overlap with your work (or uses a list you give it). It checks their email addresses and drafts one short, honest email per professor. It sends them slowly from your own mailbox, during each professor's working hours. It then watches your inbox for replies and drafts follow-ups for you to approve.

**Does it send from my email address?**
Yes. Mail goes out through your own SMTP account, so replies come back to your normal inbox. Nothing passes through a third-party mail service.

**Is it free?**
The tool is free and open source. The only cost is the language model:
- **Groq** has a free tier that covers normal use.
- **OpenAI** `gpt-5-mini` costs roughly $0.004 per drafted email, so 300 drafts cost about $1.20.

Before any paid call, `run` shows a cost estimate and asks Y/N. `BUDGET_USD` sets a hard limit.

**What data leaves my computer?**
- To the model provider: your resume summary and each professor's public info (name, institution, recent paper titles).
- To OpenAlex and university websites: lookups of public academic data.
- To your mail server: the emails themselves.

Your `.env`, workbook and logs stay local. `.env` is git-ignored, so never commit it.

---

## Drafting

**Will it make up achievements or results?**
It is instructed not to. Drafts describe what you *built and tried*, never metrics, "improvements" or novelty claims. A cleanup pass removes common AI-sounding phrases, and drafts that still read as machine-written get rewritten. Always read a few drafts yourself with `send --review --top 3` before sending for real.

**Why were only some professors drafted?**
Run `python -m outreach.cli stats`. Its "Why rows were / weren't drafted" section gives the reason for each row:
- `skipped: no email` means there is no address. Try `verify --repair --apply`.
- `skipped: local score ... < 0.25` means the topic overlap is weak. Lower it with `run --min-score 0.15`.
- `skipped: over max-professors cap` means the cap was hit. Raise it with `run --max-professors 400`.
- `skipped: budget exhausted` means `BUDGET_USD` was reached.
- `failed: ...` means a model error. See [Diagnostics](diagnostics.md).

**Can I edit a draft before it's sent?**
Yes. Open the workbook and edit the **Custom Email Draft** or **Email Subject** cell, then save and close it. The sender uses whatever is in the cell.

**Can I re-draft everything with a different model?**
`run --model gpt-4.1 --max-professors N` redrafts. Rows already marked `sent` keep their status and are never mailed again.

**What's the "Probability of Acceptance"?**
It is the model's calibrated guess (1-100) at how likely this professor is to take you. It's useful for ordering who to email first (`send --top 20`), not as a prediction.

---

## Sending

**Why does it send so slowly?**
On purpose. University and Gmail servers throttle or flag accounts that send many near-identical emails quickly. The defaults are 40 per day, 5-10 minutes apart, and only 9:00-17:00 on weekdays in the professor's own time zone. This keeps your account healthy and makes it more likely your email is read.

**Can I send more per day?**
You can raise `DAILY_SEND_CAP`, but more than about 50 per day from one personal mailbox risks rate limits or spam flags. A better approach is to schedule a daily run (see your OS guide) and let it finish over a week or two.

**Will anyone get emailed twice?**
No:
- A row marked `sent` is skipped on every later run unless you pass `--resend`.
- Each successful send is written to the workbook immediately, so a crash, sleep or power cut can't lose that record.
- If the workbook is open in Excel, statuses are saved to `<workbook>.pending-status.json` and merged on the next run.

**What do `--local-window 9-17 --wait` do?**
`--local-window 9-17` only sends while it's 9:00-17:00 on a weekday at the professor's location (taken from the Country column). Without `--wait`, rows outside that window are "held" for a later run. With `--wait`, the process stays running and sends each row when its window opens.

**What's the difference between `--dry-run`, `--review` and `--live`?**
| Flag | Who receives it | Marks rows sent? |
|---|---|---|
| `--dry-run` (default) | nobody, it only prints | no |
| `--review` | **you** (subject starts `[DRAFT -> prof@...]`) | no (marked `review-sent`, doesn't block the real send) |
| `--live` | the professors | yes |
| `--export` | writes `.eml` files to `output/drafts/` | no |

**Is my CV attached?**
Only if you set `ATTACHMENTS=/path/to/cv.pdf` in `.env`. Separate multiple files with `;`. Follow-up replies are sent without attachments.

**Why was an address skipped as "invalid"?**
`verify` found it undeliverable, for example a nonexistent domain or a format the university doesn't use. Run `verify --repair --apply` to find the right one. Use `--allow-unverified` only if you are sure the address is correct.

**Can I stop a send halfway?**
Yes. Press Ctrl+C, or close the window. Everything sent so far is already recorded, and the next run continues where it stopped.

---

## Replies

**How does it know who replied?**
`check-replies` logs into your mailbox over IMAP (read-only). It matches messages by the professor's address and by the original `Message-ID`, then sorts each one into **replied**, **auto-reply** (out-of-office) or **bounced**. It writes the result to the **Reply Status** column. It checks INBOX and any spam/junk folders.

**How are follow-ups drafted?**
`replies` reads the whole thread for each professor, both your sent messages and theirs. For every thread where the professor wrote last, it chooses one of:
- **reply**: they asked something or left a door open, so it answers their questions.
- **thank**: a polite no. It drafts a short thank-you, often asking whether they know a colleague who takes students.
- **none**: nothing worth sending.

Drafts are saved to `output/reply_queue.json`. Nothing is sent until you set `"approved": true` and run `replies --send --live`.

**Will follow-ups show up in the same thread?**
Yes. They're sent with `Re:` in the subject and with `In-Reply-To`/`References` headers, so mail clients group them with the original conversation.

**It wrote `[FILL: ...]` in a reply. Why?**
The professor asked for something the model doesn't know, such as your GPA, exact dates or a transcript link. Replace the placeholder before approving.

---

## Running unattended

**Can I leave it running overnight or close my laptop?**
Closing the lid usually sleeps the machine and pauses sending. Nothing is lost, and it resumes when the machine wakes. To keep it sending:
- **Windows:** turn off the lid-close sleep action on AC power, or use PowerToys Awake.
- **macOS:** `caffeinate -i` (already in the launchd example), or clamshell mode.
- **Linux:** `systemd-inhibit` (already in the systemd example).

**How do I check progress from my phone?**
Install Tailscale on both devices, SSH into the computer, and run `python -m outreach.cli stats` or `tail -f output/daily_send.log`. Your OS guide has the details.

**Where are the logs?**
| File | Contents |
|---|---|
| `output/professors.xlsx` | Everything: drafts, statuses, sent times, replies |
| `output/send_log.csv` | One line per send attempt (dry-run, review, live), kept even if the sheet is edited |
| `output/daily_send.log` | Console output of scheduled sends |
| `output/reply_queue.json` | Drafted follow-ups awaiting approval |
| `output/professors.backup-*.xlsx` | Automatic backups taken before each `run` |

---

## Accounts and providers

**Which email providers work?**
Anything with SMTP and IMAP:
| Provider | SMTP | IMAP | Notes |
|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` 465 ssl | `imap.gmail.com` 993 | Needs 2FA and an app password |
| Outlook / Microsoft 365 | `smtp.office365.com` 587 starttls | `outlook.office365.com` 993 | Many orgs disable SMTP AUTH, so ask IT |
| iCloud | `smtp.mail.me.com` 587 starttls | `imap.mail.me.com` 993 | App-specific password |
| Most universities | `smtp.<uni>` 465 ssl or 587 starttls | `imap.<uni>` 993 | Check your IT pages |

**Is sending from my university address better than Gmail?**
Usually yes. Professors are more likely to open it, and university mail is less likely to land in spam. Universities also rate-limit more strictly, so keep the default pacing.

**Can I use a different model provider?**
Yes, any OpenAI-compatible endpoint works. Set `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=<url>`, `OPENAI_API_KEY=<key>` and `DRAFT_MODEL=<model>`. Agnostos detects at runtime which request features the endpoint supports.
